"""Chunking strategies.

* ``structured`` (production): section-aware packing of parsed blocks. Chunks never cross a heading
  boundary, never split a sentence or table row, carry their heading path for context, and overlap
  by N sentences with the previous chunk of the same section. Tables become their own chunks (large
  tables are split by rows with the header repeated).
* ``fixed`` (baseline for evaluation): the classic fixed-size character window over the raw text,
  ignoring structure. Kept only so the benefit of structured chunking can be measured.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.ingestion.parsers.base import Block, ParsedDocument

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])")
_WORD = re.compile(r"\S+")


def count_tokens(text: str) -> int:
    """Fast approximation of subword tokens (≈1.3 tokens per whitespace word)."""
    return int(len(_WORD.findall(text)) * 1.3) + 1


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT_SPLIT.split(text) if s.strip()]


@dataclass
class ChunkData:
    text: str
    chunk_index: int
    page_start: int | None
    page_end: int | None
    section_path: str = ""
    chunk_type: str = "text"
    token_count: int = 0
    meta: dict = field(default_factory=dict)


def contextualize(chunk_text: str, title: str | None, section_path: str | None) -> str:
    """Text actually embedded / keyword-indexed: document title and heading path give each chunk context."""
    header = " > ".join(p for p in [title or "", section_path or ""] if p)
    return f"{header}\n{chunk_text}" if header else chunk_text


def _split_long(text: str, max_tokens: int) -> list[str]:
    """Split an over-long paragraph on sentence boundaries (falls back to word windows)."""
    out, cur = [], []
    for s in split_sentences(text):
        if count_tokens(s) > max_tokens:  # pathological sentence: hard-wrap by words
            words = s.split()
            step = int(max_tokens / 1.3)
            out.extend(" ".join(words[i:i + step]) for i in range(0, len(words), step))
            continue
        if cur and count_tokens(" ".join(cur + [s])) > max_tokens:
            out.append(" ".join(cur))
            cur = []
        cur.append(s)
    if cur:
        out.append(" ".join(cur))
    return out


def _split_table(md: str, max_tokens: int) -> list[str]:
    lines = md.splitlines()
    if count_tokens(md) <= max_tokens or len(lines) <= 3:
        return [md]
    header, rows = lines[:2], lines[2:]
    out, cur = [], []
    for r in rows:
        if cur and count_tokens("\n".join(header + cur + [r])) > max_tokens:
            out.append("\n".join(header + cur))
            cur = []
        cur.append(r)
    if cur:
        out.append("\n".join(header + cur))
    return out


def structured_chunks(doc: ParsedDocument, max_tokens: int = 350, overlap_sentences: int = 1,
                      min_tokens: int = 40) -> list[ChunkData]:
    chunks: list[ChunkData] = []
    heading_stack: list[tuple[int, str]] = []

    # 1) group blocks into sections keyed by heading path
    sections: list[tuple[str, list[Block]]] = []
    for b in doc.blocks:
        if b.type == "heading":
            while heading_stack and heading_stack[-1][0] >= b.level:
                heading_stack.pop()
            heading_stack.append((b.level, b.text))
            sections.append((" > ".join(h for _, h in heading_stack), []))
            continue
        if not sections:
            sections.append(("", []))
        sections[-1][1].append(b)

    def emit(text, pages, path, ctype="text"):
        chunks.append(ChunkData(text=text.strip(), chunk_index=len(chunks), page_start=min(pages),
                                page_end=max(pages), section_path=path, chunk_type=ctype,
                                token_count=count_tokens(text)))

    # 2) pack each section
    for path, blocks in sections:
        buf: list[str] = []
        pages: list[int] = []
        carry: list[str] = []  # overlap sentences from the previous chunk in this section

        def flush():
            nonlocal buf, pages, carry
            if buf:
                body = "\n\n".join(buf)
                text = (" ".join(carry) + "\n\n" + body) if carry else body
                emit(text, pages, path)
                sents = split_sentences(buf[-1])
                carry = sents[-overlap_sentences:] if overlap_sentences and sents else []
            buf, pages = [], []

        for b in blocks:
            if b.type == "table":
                flush()
                carry = []
                for part in _split_table(b.text, max_tokens):
                    emit(part, [b.page], path, "table")
                continue
            pieces = _split_long(b.text, max_tokens) if count_tokens(b.text) > max_tokens else [b.text]
            for piece in pieces:
                if buf and count_tokens("\n\n".join(buf + [piece])) > max_tokens:
                    flush()
                buf.append(piece)
                pages.append(b.page)
        flush()

    # 3) merge tiny trailing chunks into their predecessor when in the same section
    merged: list[ChunkData] = []
    for c in chunks:
        prev = merged[-1] if merged else None
        if (prev and c.chunk_type == "text" and prev.chunk_type == "text" and c.section_path == prev.section_path
                and c.token_count < min_tokens and prev.token_count + c.token_count <= max_tokens * 1.2):
            prev.text += "\n\n" + c.text
            prev.page_end = max(prev.page_end or 0, c.page_end or 0)
            prev.token_count = count_tokens(prev.text)
        else:
            merged.append(c)
    for i, c in enumerate(merged):
        c.chunk_index = i
    return merged


def fixed_chunks(doc: ParsedDocument, size_chars: int = 1000, overlap_chars: int = 0) -> list[ChunkData]:
    """Naive baseline: fixed character windows over concatenated text."""
    text_parts, page_at = [], []
    pos = 0
    for b in doc.blocks:
        t = b.text + "\n"
        text_parts.append(t)
        page_at.append((pos, b.page))
        pos += len(t)
    text = "".join(text_parts)

    def page_for(offset: int) -> int:
        p = 1
        for start, page in page_at:
            if start > offset:
                break
            p = page
        return p

    chunks = []
    step = max(1, size_chars - overlap_chars)
    for i, start in enumerate(range(0, len(text), step)):
        piece = text[start:start + size_chars]
        if not piece.strip():
            continue
        chunks.append(ChunkData(text=piece.strip(), chunk_index=len(chunks), page_start=page_for(start),
                                page_end=page_for(min(len(text) - 1, start + size_chars - 1)),
                                token_count=count_tokens(piece)))
    return chunks


def chunk_document(doc: ParsedDocument, strategy: str = "structured", **kw) -> list[ChunkData]:
    if strategy == "structured":
        return structured_chunks(doc, **kw)
    if strategy == "fixed":
        return fixed_chunks(doc, **kw)
    raise ValueError(f"unknown chunking strategy {strategy}")
