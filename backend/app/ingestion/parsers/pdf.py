"""PDF parser (PyMuPDF): headings from font-size statistics, tables via the table finder, page numbers."""
from __future__ import annotations

import re
from collections import Counter
from datetime import date

import fitz  # PyMuPDF

from app.ingestion.parsers.base import Block, ParsedDocument, table_to_markdown

_LIST_RE = re.compile(r"^\s*(?:[-•▪●◦*]|\d{1,2}[.)]|[a-z][.)])\s+")


def _pdf_date(raw: str | None) -> date | None:
    m = re.match(r"D:(\d{4})(\d{2})(\d{2})", raw or "")
    if not m:
        return None
    try:
        return date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        return None


def _inside(bbox, rects) -> bool:
    x0, y0, x1, y1 = bbox
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    return any(r.x0 - 1 <= cx <= r.x1 + 1 and r.y0 - 1 <= cy <= r.y1 + 1 for r in rects)


def parse_pdf(path: str) -> ParsedDocument:
    doc = fitz.open(path)
    try:
        pages = []
        size_counter: Counter[float] = Counter()
        for pno, page in enumerate(doc, start=1):
            tables = []
            try:
                for t in page.find_tables().tables:
                    # read each cell by its bounding box: preserves spaces in wrapped cell text
                    rows = [[" ".join(page.get_textbox(fitz.Rect(c)).split()) if c else "" for c in r.cells]
                            for r in t.rows]
                    md = table_to_markdown(rows)
                    if md and len(rows) >= 2:
                        tables.append((fitz.Rect(t.bbox), md))
            except Exception:  # table finder is best-effort
                tables = []
            rects = [r for r, _ in tables]
            lines = []
            d = page.get_text("dict", sort=True)
            for b in d["blocks"]:
                if b.get("type") != 0:
                    continue
                if _inside(b["bbox"], rects):
                    continue
                for ln in b["lines"]:
                    spans = [s for s in ln["spans"] if s["text"].strip()]
                    if not spans:
                        continue
                    text = "".join(s["text"] for s in ln["spans"]).strip()
                    size = round(max(s["size"] for s in spans), 1)
                    bold = all((s["flags"] & 16) or "Bold" in s["font"] for s in spans)
                    size_counter[size] += len(text)
                    lines.append({"text": text, "size": size, "bold": bold, "y0": ln["bbox"][1], "y1": ln["bbox"][3],
                                  "block": id(b)})
            pages.append((pno, lines, tables))

        body_size = size_counter.most_common(1)[0][0] if size_counter else 10.0
        heading_sizes = sorted({s for s in size_counter if s >= body_size * 1.12}, reverse=True)
        level_of = {s: min(i + 1, 4) for i, s in enumerate(heading_sizes)}

        blocks: list[Block] = []
        for pno, lines, tables in pages:
            # emit table blocks in reading order by their y position
            pending_tables = sorted(tables, key=lambda t: t[0].y0)
            para: list[str] = []
            last = None

            def flush():
                if para:
                    txt = " ".join(para).strip()
                    txt = re.sub(r"(\w)- (\w)", r"\1\2", txt)  # de-hyphenate line breaks
                    blocks.append(Block("list" if _LIST_RE.match(txt) else "paragraph", txt, pno))
                    para.clear()

            for ln in lines:
                while pending_tables and pending_tables[0][0].y0 < ln["y0"]:
                    flush()
                    blocks.append(Block("table", pending_tables.pop(0)[1], pno))
                short = len(ln["text"]) < 150
                by_size = ln["size"] in level_of and short
                # same-size bold lines count as headings only if they don't look like list items / sentences
                by_bold = (ln["bold"] and len(ln["text"]) < 90 and not ln["text"].endswith((".", ":", ",", ";"))
                           and not _LIST_RE.match(ln["text"]))
                if by_size or by_bold:
                    flush()
                    lvl = level_of.get(ln["size"], len(heading_sizes) + 1)
                    # merge multi-line headings
                    if blocks and blocks[-1].type == "heading" and last and last.get("heading") \
                            and blocks[-1].level == lvl and last["size"] == ln["size"] \
                            and blocks[-1].page == pno and abs(ln["y0"] - last["y1"]) < ln["size"] * 0.5:
                        blocks[-1].text += " " + ln["text"]
                    else:
                        blocks.append(Block("heading", ln["text"], pno, level=lvl))
                    last = {**ln, "heading": True}
                    continue
                new_para = (last is None or last.get("heading") or ln["block"] != last["block"]
                            or (ln["y0"] - last["y1"]) > ln["size"] * 0.8 or _LIST_RE.match(ln["text"]))
                if new_para:
                    flush()
                para.append(ln["text"])
                last = ln
            flush()
            for _, md in pending_tables:
                blocks.append(Block("table", md, pno))

        meta = doc.metadata or {}
        title = (meta.get("title") or "").strip() or next((b.text for b in blocks if b.type == "heading"), None)
        return ParsedDocument(blocks=blocks, page_count=doc.page_count, title=title,
                              author=(meta.get("author") or "").strip() or None,
                              doc_date=_pdf_date(meta.get("creationDate")))
    finally:
        doc.close()
