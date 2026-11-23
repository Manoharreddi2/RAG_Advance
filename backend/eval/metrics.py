"""Evaluation metrics. All are computed from gold labels in the dataset — nothing is hand-entered.

Relevance: a retrieved chunk is *relevant* to an evidence span if it comes from the evidence's document
and contains at least ``COVERAGE`` of the span's content tokens. This is chunking-agnostic, so different
chunking strategies are judged against the same gold evidence.
"""
from __future__ import annotations

import re
from collections import Counter

from app.generation.answer import cited_indices
from app.retrieval.bm25 import analyze

COVERAGE = 0.7
_CITE = re.compile(r"\[\d+(?:\s*[,;–-]\s*\d+)*\]")
_SENT = re.compile(r"(?<=[.!?])\s+")


def evidence_coverage(chunk_text: str, evidence: str) -> float:
    ev = Counter(analyze(evidence))
    if not ev:
        return 0.0
    ch = Counter(analyze(chunk_text))
    return sum(min(n, ch[t]) for t, n in ev.items()) / sum(ev.values())


def relevant_evidence(chunk: dict, evidence: list[dict]) -> set[int]:
    """Indices of evidence spans this chunk covers."""
    return {i for i, ev in enumerate(evidence)
            if chunk.get("filename") == ev["doc"] and evidence_coverage(chunk.get("text", ""), ev["text"]) >= COVERAGE}


def retrieval_metrics(chunks: list[dict], evidence: list[dict], ks=(1, 3, 5, 10)) -> dict:
    rel = [relevant_evidence(c, evidence) for c in chunks]
    out = {}
    for k in ks:
        top = rel[:k]
        covered = set().union(*top) if top else set()
        out[f"recall@{k}"] = len(covered) / len(evidence)
        out[f"precision@{k}"] = sum(1 for r in top if r) / k
        out[f"hit@{k}"] = float(bool(covered))
    first = next((i for i, r in enumerate(rel) if r), None)
    out["mrr"] = 0.0 if first is None else 1.0 / (first + 1)
    # document-level: is the top-1 chunk from a gold document? (relevant to versioned questions)
    gold_docs = {e["doc"] for e in evidence}
    out["top1_doc_correct"] = float(bool(chunks) and chunks[0].get("filename") in gold_docs)
    return out


def _norm_fact(s: str) -> str:
    s = s.lower().replace("–", "-").replace("−", "-")
    s = re.sub(r"(?<=\d),(?=\d{3})", "", s)  # 1,500 -> 1500
    return re.sub(r"\s+", " ", s).strip()


_NUM_WORDS = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7",
              "eight": "8", "nine": "9", "ten": "10", "twice": "2"}


def _fact_present(fact: str, answer: str) -> bool:
    a, f = _norm_fact(answer), _norm_fact(fact)
    swap = lambda s: " ".join(_NUM_WORDS.get(w, w) for w in s.split())  # noqa: E731
    # numbers must match as whole numbers ("5" must not match "15" or "5.5"), also inside phrases
    pattern = r"(?<![\w.])" + re.escape(swap(f)).replace(r"\ ", r"\s+") + r"(?![\d]|\.\d)"
    return re.search(pattern, swap(a)) is not None


def answer_correctness(answer: str, key_facts: list[str], answerable: bool, abstained: bool) -> dict:
    if not answerable:
        return {"key_fact_recall": None, "correct": float(abstained)}
    if abstained:
        return {"key_fact_recall": 0.0, "correct": 0.0}
    hits = [_fact_present(f, answer) for f in key_facts]
    recall = sum(hits) / len(hits) if hits else 0.0
    return {"key_fact_recall": recall, "correct": float(recall == 1.0)}


def answer_claims(answer: str) -> list[str]:
    text = _CITE.sub("", answer)
    return [s.strip() for s in _SENT.split(text) if len(s.strip().split()) >= 3]


def faithfulness(answer: str, passages: list[str], nli, threshold: float = 0.5) -> dict:
    """Share of answer sentences entailed by at least one retrieved passage (NLI cross-encoder)."""
    claims = answer_claims(answer)
    if not claims or not passages:
        return {"faithfulness": None, "n_claims": len(claims)}
    pairs = [(p, c) for c in claims for p in passages]
    probs = nli.entailment(pairs)
    per_claim = [max(probs[i * len(passages):(i + 1) * len(passages)]) for i in range(len(claims))]
    supported = [p >= threshold for p in per_claim]
    return {"faithfulness": sum(supported) / len(claims), "n_claims": len(claims),
            "unsupported_claims": [c for c, ok in zip(claims, supported) if not ok]}


def citation_metrics(answer: str, chunks: list[dict], evidence: list[dict], gold_pages: list[dict]) -> dict:
    """citation_precision: share of cited passages that contain gold evidence.
    citation_page_accuracy: share of cited passages whose (document, page range) contains a gold page."""
    cited = cited_indices(answer, len(chunks))
    if not cited:
        return {"has_citation": 0.0, "citation_precision": None, "citation_page_accuracy": None, "n_cited": 0}
    prec = [bool(relevant_evidence(chunks[i - 1], evidence)) for i in cited]
    page_ok = []
    for i in cited:
        c = chunks[i - 1]
        ps, pe = c.get("page_start") or 1, c.get("page_end") or c.get("page_start") or 1
        page_ok.append(any(g["doc"] == c.get("filename") and ps <= g["page"] <= pe for g in gold_pages))
    return {"has_citation": 1.0, "citation_precision": sum(prec) / len(prec),
            "citation_page_accuracy": sum(page_ok) / len(page_ok), "n_cited": len(cited)}


def mean(values) -> float | None:
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def percentile(values, p: float) -> float | None:
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    k = (len(vals) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(vals) - 1)
    return vals[lo] + (vals[hi] - vals[lo]) * (k - lo)
