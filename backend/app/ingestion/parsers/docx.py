"""DOCX parser: heading styles, native tables, list paragraphs, page breaks -> page numbers."""
from __future__ import annotations

import re

import docx
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.ingestion.parsers.base import Block, ParsedDocument, table_to_markdown


def _page_breaks(p: Paragraph) -> int:
    n = 0
    for br in p._p.iter(qn("w:br")):
        if br.get(qn("w:type")) == "page":
            n += 1
    return n


def parse_docx(path: str) -> ParsedDocument:
    d = docx.Document(path)
    blocks: list[Block] = []
    page = 1
    has_title = False
    for child in d.element.body.iterchildren():
        if child.tag == qn("w:p"):
            p = Paragraph(child, d)
            breaks = _page_breaks(p)
            if p.paragraph_format.page_break_before:
                page += 1
            text = p.text.strip()
            if text:
                style = (p.style.name if p.style is not None else "") or ""
                m = re.match(r"Heading (\d)", style)
                ppr = child.find(qn("w:pPr"))
                numbered = ppr is not None and ppr.find(qn("w:numPr")) is not None
                if style == "Title":
                    has_title = True
                    blocks.append(Block("heading", text, page, level=1))
                elif m:
                    blocks.append(Block("heading", text, page, level=int(m[1]) + (1 if has_title else 0)))
                elif "List" in style or numbered:
                    blocks.append(Block("list", "- " + text, page))
                else:
                    blocks.append(Block("paragraph", text, page))
            page += breaks
        elif child.tag == qn("w:tbl"):
            t = Table(child, d)
            rows = [[c.text for c in r.cells] for r in t.rows]
            md = table_to_markdown(rows)
            if md:
                blocks.append(Block("table", md, page))
    cp = d.core_properties
    title = (cp.title or "").strip() or next((b.text for b in blocks if b.type == "heading"), None)
    doc_date = (cp.created.date() if cp.created else None)
    return ParsedDocument(blocks=blocks, page_count=page, title=title, author=(cp.author or "").strip() or None,
                          doc_date=doc_date)
