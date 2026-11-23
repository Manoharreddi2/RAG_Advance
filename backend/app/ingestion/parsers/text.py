"""Markdown and plain-text parsers. Form feeds (\\f) are treated as page breaks."""
from __future__ import annotations

import re

from app.ingestion.parsers.base import Block, ParsedDocument

_MD_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_LIST = re.compile(r"^\s*(?:[-*+•]|\d{1,3}[.)])\s+")
_NUMBERED_HEADING = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+[A-Z][^.!?]{0,80}$")
_FRONT_MATTER = re.compile(r"^---\n(.*?)\n---\n", re.S)


def _read(path: str) -> str:
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _front_matter(text: str) -> tuple[dict, str]:
    m = _FRONT_MATTER.match(text)
    if not m:
        return {}, text
    meta = {}
    for line in m[1].splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip().lower()] = v.strip().strip('"\'')
    return meta, text[m.end():]


def _group(lines: list[str], page: int, blocks: list[Block], md: bool) -> None:
    """Group a run of non-heading lines into paragraph / list / table blocks."""
    buf: list[str] = []
    kind = None

    def flush():
        nonlocal kind
        if buf:
            sep = "\n" if kind in ("list", "table") else " "
            blocks.append(Block(kind or "paragraph", sep.join(s.strip() if kind != "table" else s.rstrip() for s in buf).strip(), page))
            buf.clear()
        kind = None

    for line in lines:
        if not line.strip():
            flush()
            continue
        k = "table" if md and line.lstrip().startswith("|") else "list" if _LIST.match(line) else "paragraph"
        if kind is not None and k != kind and not (kind == "list" and k == "paragraph" and line.startswith(("  ", "\t"))):
            flush()
        kind = kind or k
        buf.append(line)
    flush()


def parse_markdown(path: str) -> ParsedDocument:
    meta, text = _front_matter(_read(path))
    blocks: list[Block] = []
    for pno, page_text in enumerate(text.split("\f"), start=1):
        run: list[str] = []
        in_code = False
        for line in page_text.splitlines():
            if line.strip().startswith("```"):
                in_code = not in_code
                run.append(line)
                continue
            m = None if in_code else _MD_HEADING.match(line)
            if m:
                _group(run, pno, blocks, md=True)
                run = []
                blocks.append(Block("heading", m[2], pno, level=len(m[1])))
            else:
                run.append(line)
        _group(run, pno, blocks, md=True)
    return _finish(blocks, text.count("\f") + 1, meta)


def parse_text(path: str) -> ParsedDocument:
    meta, text = _front_matter(_read(path))
    blocks: list[Block] = []
    for pno, page_text in enumerate(text.split("\f"), start=1):
        lines = page_text.splitlines()
        run: list[str] = []
        for i, line in enumerate(lines):
            s = line.strip()
            prev_blank = i == 0 or not lines[i - 1].strip()
            next_blank = i + 1 >= len(lines) or not lines[i + 1].strip()
            heading = False
            level = 1
            if s and prev_blank and next_blank and len(s) < 90 and not s.endswith((".", ",", ";", ":")):
                if m := _NUMBERED_HEADING.match(s):
                    heading, level = True, m[1].count(".") + 1
                elif s.isupper() and len(s.split()) <= 10:
                    heading = True
                elif s.istitle() and len(s.split()) <= 8:
                    heading, level = True, 2
            if heading:
                _group(run, pno, blocks, md=False)
                run = []
                blocks.append(Block("heading", s, pno, level=level))
            else:
                run.append(line)
        _group(run, pno, blocks, md=False)
    return _finish(blocks, text.count("\f") + 1, meta)


def _finish(blocks: list[Block], pages: int, meta: dict) -> ParsedDocument:
    from datetime import date
    doc_date = None
    if meta.get("date"):
        try:
            doc_date = date.fromisoformat(meta["date"][:10])
        except ValueError:
            pass
    title = meta.get("title") or next((b.text for b in blocks if b.type == "heading"), None)
    return ParsedDocument(blocks=blocks, page_count=pages, title=title, author=meta.get("author"), doc_date=doc_date,
                          extra={k: v for k, v in meta.items() if k not in ("title", "author", "date")})
