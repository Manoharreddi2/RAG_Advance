"""Unit tests: BM25, RRF, filters, answer post-processing, eval metrics, security."""
from __future__ import annotations

from datetime import date

import pytest

from app.core.security import create_access_token, decode_token, has_role, hash_password, verify_password
from app.generation.answer import build_citations, cited_indices, is_abstention, postprocess, verify_quotes
from app.generation.prompts import NO_ANSWER, build_messages
from app.retrieval.bm25 import BM25Index, analyze
from app.retrieval.filters import SearchFilters, date_to_int
from app.retrieval.pipeline import reciprocal_rank_fusion
from eval.metrics import answer_correctness, citation_metrics, evidence_coverage, retrieval_metrics


def test_rrf_formula_and_ordering():
    fused = reciprocal_rank_fusion({"dense": ["a", "b", "c"], "bm25": ["c", "a"]}, k=60)
    assert fused["a"] == pytest.approx(1 / 61 + 1 / 62)
    assert fused["c"] == pytest.approx(1 / 63 + 1 / 61)
    assert fused["b"] == pytest.approx(1 / 62)
    assert sorted(fused, key=fused.get, reverse=True) == ["a", "c", "b"]


def test_analyzer_stems_and_drops_stopwords():
    assert analyze("The policies for travelling employees") == analyze("policy travelling employee")
    assert analyze("classes boxes") == ["class", "box"]
    assert "hx-503" in analyze("Error HX-503 occurred")


def test_bm25_ranking_and_filters():
    payloads = [{"filename": "a.pdf", "category": "HR", "doc_date_int": 20230101},
                {"filename": "b.pdf", "category": "Finance", "doc_date_int": 20240101},
                {"filename": "c.pdf", "category": "Finance", "doc_date_int": 20240501}]
    texts = ["vacation days and parental leave", "hotel cap for tier one cities is 320 dollars",
             "hotel cap was 275 dollars in tier one cities"]
    idx = BM25Index(["1", "2", "3"], texts, payloads)
    hits = idx.search("hotel cap tier one", 3)
    assert {h[0] for h in hits} == {"2", "3"}  # zero-score docs are dropped
    f = SearchFilters(date_to=date(2024, 2, 1), categories=["Finance"])
    assert [h[0] for h in idx.search("hotel cap", 3, f)] == ["2"]


def test_filters_qdrant_translation():
    f = SearchFilters(filenames=["x.pdf"], date_from=date(2024, 1, 1))
    q = f.to_qdrant()
    keys = {c.key for c in q.must}
    assert keys == {"filename", "doc_date_int"}
    assert SearchFilters().to_qdrant() is None
    assert date_to_int("2024-03-15") == 20240315


CHUNKS = [{"chunk_id": "c1", "text": "The per diem for domestic travel is 75 USD per day. Alcohol is excluded.",
           "filename": "t.pdf", "page_start": 2, "page_end": 2},
          {"chunk_id": "c2", "text": "Hotels in Tier 1 cities are capped at 320 USD.", "filename": "t.pdf",
           "page_start": 2, "page_end": 2}]


def test_citation_parsing():
    assert cited_indices("A [1]. B [2, 1]. C [7]. D [1-2]", 2) == [1, 2]
    cits = build_citations("Per diem is 75 USD [1]. Hotel cap is 320 USD [2].", CHUNKS)
    assert [c["chunk_id"] for c in cits] == ["c1", "c2"]
    assert cits[0]["quote"].startswith("The per diem for domestic travel")


def test_quote_verification_detects_invented_quotes():
    q = verify_quotes('It says "The per diem for domestic travel is 75 USD per day" and "employees get free cars always"', CHUNKS)
    assert [x["verified"] for x in q] == [True, False]


def test_abstention_detection():
    assert is_abstention(NO_ANSWER)
    assert not is_abstention("The per diem is 75 USD per day [1].")
    p = postprocess(NO_ANSWER, CHUNKS)
    assert p["abstained"] and p["citations"] == []


def test_prompt_contains_numbered_context_and_rules():
    msgs = build_messages("What is the per diem?", CHUNKS, history=[{"role": "user", "content": "hi"}])
    assert msgs[0]["role"] == "system" and NO_ANSWER in msgs[0]["content"]
    assert "[1] t.pdf, p. 2:" in msgs[-1]["content"] and "[2]" in msgs[-1]["content"]
    assert msgs[1] == {"role": "user", "content": "hi"}


def test_retrieval_metrics():
    ev = [{"doc": "t.pdf", "text": "The per diem for domestic travel is 75 USD per day."}]
    m = retrieval_metrics([CHUNKS[1], CHUNKS[0]], ev, ks=(1, 2))
    assert m["recall@1"] == 0 and m["recall@2"] == 1 and m["mrr"] == 0.5 and m["precision@2"] == 0.5
    assert evidence_coverage(CHUNKS[0]["text"], ev[0]["text"]) == 1.0
    # a chunk from another document never counts as relevant
    assert retrieval_metrics([{**CHUNKS[0], "filename": "other.pdf"}], ev, ks=(1,))["recall@1"] == 0


def test_answer_correctness_and_citations():
    assert answer_correctness("It is 1500 USD [1]", ["1,500"], True, False)["correct"] == 1.0
    assert answer_correctness("Two bags are covered", ["two bags"], True, False)["correct"] == 1.0
    assert answer_correctness("It is 15 days", ["5"], True, False)["correct"] == 0.0  # no partial number match
    assert answer_correctness(NO_ANSWER, [], False, True)["correct"] == 1.0
    ev = [{"doc": "t.pdf", "text": "Hotels in Tier 1 cities are capped at 320 USD."}]
    c = citation_metrics("Cap is 320 [2]. Also [1].", CHUNKS, ev, [{"doc": "t.pdf", "page": 2}])
    assert c["citation_precision"] == 0.5 and c["citation_page_accuracy"] == 1.0


def test_password_hashing_and_tokens():
    h = hash_password("s3cret-password")
    assert verify_password("s3cret-password", h) and not verify_password("wrong", h)
    tok = create_access_token("abc", "editor")
    assert decode_token(tok)["sub"] == "abc"
    assert has_role("admin", "editor") and has_role("editor", "viewer") and not has_role("viewer", "editor")
