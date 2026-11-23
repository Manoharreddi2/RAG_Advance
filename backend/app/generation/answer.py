"""Post-processing of generated answers: citation extraction, supporting quotes, quote verification, abstention."""
from __future__ import annotations

import re

from app.generation.prompts import NO_ANSWER
from app.retrieval.bm25 import analyze

_CITE = re.compile(r"\[(\d+(?:\s*[,;–-]\s*\d+)*)\]")
_QUOTE = re.compile(r"[\"“]([^\"”]{20,400})[\"”]")
_SENT = re.compile(r"(?<=[.!?])\s+")
_ABSTAIN_PATTERNS = ("could not find sufficient evidence", "not enough information", "do not contain",
                     "does not contain", "no information", "not mentioned in the", "not provided in the",
                     "cannot find", "could not find")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s%$.]", " ", s.lower())).strip()


def cited_indices(answer: str, n_passages: int) -> list[int]:
    seen: list[int] = []
    for m in _CITE.finditer(answer):
        for part in re.split(r"\s*[,;]\s*", m[1]):
            if re.match(r"^\d+\s*[–-]\s*\d+$", part):
                a, b = (int(x) for x in re.split(r"\s*[–-]\s*", part))
                nums = range(a, b + 1)
            else:
                nums = [int(part)] if part.strip().isdigit() else []
            for n in nums:
                if 1 <= n <= n_passages and n not in seen:
                    seen.append(n)
    return seen


def best_quote(chunk_text: str, claim: str, max_len: int = 300) -> str:
    """Sentence(s) of the chunk with the highest lexical overlap with the claim that cites it."""
    sents = [s.strip() for s in _SENT.split(chunk_text) if len(s.strip()) > 15] or [chunk_text]
    claim_toks = set(analyze(claim))
    best = max(sents, key=lambda s: len(claim_toks & set(analyze(s))) / (1 + 0.01 * len(s)))
    return best[:max_len]


def is_abstention(answer: str) -> bool:
    a = answer.lower()
    if NO_ANSWER.lower()[:40] in a:
        return True
    # short answers that are essentially "not in the documents"
    return len(a) < 260 and any(p in a for p in _ABSTAIN_PATTERNS)


def build_citations(answer: str, chunks: list[dict]) -> list[dict]:
    sentences = [s for s in _SENT.split(answer) if s.strip()]
    out = []
    for n in cited_indices(answer, len(chunks)):
        claim = " ".join(s for s in sentences if re.search(rf"\[[^\]]*\b{n}\b[^\]]*\]", s)) or answer
        c = chunks[n - 1]
        out.append({"index": n, "chunk_id": c["chunk_id"], "document_id": c.get("document_id"),
                    "filename": c.get("filename"), "title": c.get("title"), "page_start": c.get("page_start"),
                    "page_end": c.get("page_end"), "section": c.get("section"),
                    "quote": best_quote(c["text"], claim)})
    return out


def verify_quotes(answer: str, chunks: list[dict]) -> list[dict]:
    """Every passage the model put in double quotes must appear (normalized) in the context."""
    context = _norm(" ".join(c["text"] for c in chunks))
    return [{"quote": q, "verified": _norm(q) in context} for q in _QUOTE.findall(answer)]


def postprocess(answer: str, chunks: list[dict]) -> dict:
    abstained = is_abstention(answer)
    return {"answer": answer.strip(), "citations": [] if abstained else build_citations(answer, chunks),
            "quotes": verify_quotes(answer, chunks), "abstained": abstained}
