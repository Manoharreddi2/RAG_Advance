"""Unit tests: parsers and chunking (no external services)."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.ingestion.chunking import count_tokens, fixed_chunks, structured_chunks
from app.ingestion.parsers import UnsupportedFileType, mime_for, parse_file
from app.ingestion.parsers.base import Block, ParsedDocument

CORPUS = Path(__file__).resolve().parents[1] / "eval" / "corpus"


@pytest.fixture(scope="session", autouse=True)
def corpus():
    from eval import build_corpus
    assert build_corpus.main() == 0
    return CORPUS


def test_mime_and_unsupported():
    assert mime_for("a.PDF") == "application/pdf"
    with pytest.raises(UnsupportedFileType):
        mime_for("archive.zip")


@pytest.mark.parametrize("name", ["travel_expense_policy_2024.pdf", "information_security_policy_2024.docx",
                                  "customer_support_sla.md", "incident_response_runbook.txt"])
def test_parsers_extract_headings_and_text(name):
    doc = parse_file(str(CORPUS / name), name)
    headings = [b for b in doc.blocks if b.type == "heading"]
    assert len(headings) >= 5
    assert doc.title
    assert len(doc.full_text) > 1000


def test_pdf_pages_tables_and_metadata():
    doc = parse_file(str(CORPUS / "travel_expense_policy_2024.pdf"))
    assert doc.page_count == 3
    assert doc.author == "Priya Raman"
    tables = [b for b in doc.blocks if b.type == "table"]
    assert len(tables) == 1
    assert "| Tier 1 | New York, San Francisco, London, Tokyo | 320 |" in tables[0].text
    assert tables[0].page == 2
    # numbered section headings must be detected as headings, not list items
    assert any(b.type == "heading" and b.text == "3. Meals and Per Diem" for b in doc.blocks)


def test_docx_tables_and_page_breaks():
    doc = parse_file(str(CORPUS / "vendor_procurement_procedure.docx"))
    table = next(b for b in doc.blocks if b.type == "table")
    assert "| Above 250,000 | CFO and CEO | Formal request for proposal (RFP) |" in table.text
    onboarding = next(b for b in doc.blocks if b.text.startswith("New vendors must be registered"))
    assert onboarding.page == 2


def test_text_parser_heading_heuristics():
    doc = parse_file(str(CORPUS / "incident_response_runbook.txt"))
    heads = [b.text for b in doc.blocks if b.type == "heading"]
    assert "INCIDENT RESPONSE RUNBOOK" in heads and "5. Common Error Codes" in heads


def _doc(blocks):
    return ParsedDocument(blocks=blocks, page_count=max(b.page for b in blocks))


def test_structured_chunks_respect_sections_and_tables():
    long_para = " ".join(f"Sentence number {i} explains a detail of the rule." for i in range(80))
    blocks = [Block("heading", "Policy", 1, 1), Block("heading", "A", 1, 2), Block("paragraph", long_para, 1),
              Block("table", "| h1 | h2 |\n| --- | --- |\n| a | b |", 2), Block("heading", "B", 2, 2),
              Block("paragraph", "Short section text that is long enough to stand alone as its own chunk here.", 3)]
    chunks = structured_chunks(_doc(blocks), max_tokens=120, overlap_sentences=1)
    assert all(c.token_count <= 120 * 1.25 for c in chunks)
    assert {c.section_path for c in chunks} == {"Policy > A", "Policy > B"}
    table = [c for c in chunks if c.chunk_type == "table"]
    assert len(table) == 1 and table[0].text.startswith("| h1 |") and table[0].page_start == 2
    a_chunks = [c for c in chunks if c.section_path == "Policy > A" and c.chunk_type == "text"]
    assert len(a_chunks) > 1
    # sentence overlap: chunk 2 starts with the last sentence of chunk 1
    last_sentence = a_chunks[0].text.rsplit(". ", 1)[-1]
    assert a_chunks[1].text.startswith(last_sentence.split(".")[0])
    # no sentence is cut in the middle
    assert all(c.text.rstrip().endswith(".") for c in a_chunks)


def test_large_table_split_repeats_header():
    rows = "\n".join(f"| row{i} | value {i} with several words of content |" for i in range(60))
    blocks = [Block("heading", "T", 1, 1), Block("table", "| k | v |\n| --- | --- |\n" + rows, 1)]
    chunks = structured_chunks(_doc(blocks), max_tokens=100)
    assert len(chunks) > 1 and all(c.text.startswith("| k | v |\n| --- | --- |") for c in chunks)


def test_fixed_chunks_baseline():
    blocks = [Block("paragraph", "x " * 900, 1), Block("paragraph", "y " * 900, 2)]
    chunks = fixed_chunks(_doc(blocks), size_chars=1000)
    assert len(chunks) == 4 and chunks[0].page_start == 1 and chunks[-1].page_end == 2


def test_count_tokens_monotonic():
    assert count_tokens("one two three") < count_tokens("one two three four five six")
