"""Render the benchmark corpus (eval/corpus_src/*.md) into PDF, DOCX, TXT and Markdown files and
validate the question dataset against it.

* Every evidence span in eval/dataset/questions.jsonl must occur verbatim in its source document;
  the build fails otherwise (no silently broken gold labels).
* Gold page numbers are computed from the rendered files (PDF pages are located by text search,
  DOCX pages by explicit page breaks), and written to eval/corpus/manifest.json.

Usage:  python -m eval.build_corpus
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC, OUT, DATASET = ROOT / "corpus_src", ROOT / "corpus", ROOT / "dataset" / "questions.jsonl"
PAGEBREAK = "<!-- pagebreak -->"


def read_source(path: Path) -> tuple[dict, str]:
    text = path.read_text()
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    meta = dict(line.split(": ", 1) for line in m[1].splitlines())
    return meta, text[m.end():]


def md_blocks(body: str):
    """Tiny markdown reader for the corpus sources: headings, paragraphs, lists, tables, page breaks."""
    blocks, buf, kind = [], [], None

    def flush():
        nonlocal buf, kind
        if buf:
            if kind == "table":
                rows = [[c.strip() for c in ln.strip().strip("|").split("|")] for ln in buf
                        if not re.match(r"^\|\s*-", ln.strip())]
                blocks.append(("table", rows))
            elif kind == "list":
                blocks.append(("list", [ln.lstrip("- ").strip() for ln in buf]))
            else:
                blocks.append(("p", " ".join(s.strip() for s in buf)))
        buf, kind = [], None

    for line in body.splitlines():
        s = line.strip()
        if s == PAGEBREAK:
            flush()
            blocks.append(("pagebreak", None))
        elif m := re.match(r"^(#{1,6})\s+(.*)", s):
            flush()
            blocks.append((f"h{len(m[1])}", m[2]))
        elif not s:
            flush()
        else:
            k = "table" if s.startswith("|") else "list" if s.startswith("- ") else "p"
            if kind and k != kind:
                flush()
            kind = k
            buf.append(line)
    flush()
    return blocks


def render_pdf(meta, blocks, dest: Path):
    from reportlab import rl_config
    rl_config.invariant = 1  # reproducible output: fixed creation date and document id
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import ListFlowable, ListItem, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    ss = getSampleStyleSheet()
    styles = {"h1": ParagraphStyle("H1", parent=ss["Heading1"], fontSize=18, spaceAfter=10),
              "h2": ParagraphStyle("H2", parent=ss["Heading2"], fontSize=14),
              "h3": ParagraphStyle("H3", parent=ss["Heading3"], fontSize=12),
              "p": ParagraphStyle("Body", parent=ss["BodyText"], fontSize=10, leading=14)}
    story = []
    for kind, val in blocks:
        if kind == "pagebreak":
            story.append(PageBreak())
        elif kind in styles and kind != "p":
            story.append(Paragraph(val, styles[kind]))
        elif kind == "p":
            story.append(Paragraph(val, styles["p"]))
        elif kind == "list":
            story.append(ListFlowable([ListItem(Paragraph(v, styles["p"])) for v in val], bulletType="bullet"))
        elif kind == "table":
            cell = ParagraphStyle("cell", parent=styles["p"], fontSize=9, leading=11)
            t = Table([[Paragraph(c, cell) for c in r] for r in val], repeatRows=1)
            t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                                   ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8edf5")),
                                   ("VALIGN", (0, 0), (-1, -1), "TOP")]))
            story += [t, Spacer(1, 8)]
    doc = SimpleDocTemplate(str(dest), pagesize=A4, title=meta["title"], author=meta["author"],
                            leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm)
    doc.build(story)


def render_docx(meta, blocks, dest: Path):
    import docx
    d = docx.Document()
    from datetime import datetime
    d.core_properties.title, d.core_properties.author = meta["title"], meta["author"]
    # reproducible output: timestamps from the document date instead of "now"
    stamp = datetime.fromisoformat(meta["date"])
    d.core_properties.created = d.core_properties.modified = stamp
    d.core_properties.last_printed = stamp
    d.core_properties.revision = 1
    for kind, val in blocks:
        if kind == "pagebreak":
            d.add_page_break()
        elif kind.startswith("h"):
            d.add_heading(val, level=int(kind[1]))
        elif kind == "p":
            d.add_paragraph(val)
        elif kind == "list":
            for v in val:
                d.add_paragraph(v, style="List Bullet")
        elif kind == "table":
            t = d.add_table(rows=len(val), cols=len(val[0]))
            t.style = "Table Grid"
            for i, r in enumerate(val):
                for j, c in enumerate(r):
                    t.cell(i, j).text = c
    d.save(dest)
    # zip entries carry the current time: rewrite them with a fixed timestamp for byte-identical rebuilds
    import zipfile
    with zipfile.ZipFile(dest) as z:
        entries = [(i.filename, z.read(i.filename)) for i in z.infolist()]
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in entries:
            z.writestr(zipfile.ZipInfo(name, date_time=(stamp.year, stamp.month, stamp.day, 0, 0, 0)), data,
                       compress_type=zipfile.ZIP_DEFLATED)


def _words(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", s.lower())


def gold_pages(fmt: str, dest: Path, body: str, evidence: str) -> int:
    if fmt == "pdf":
        import fitz
        ev = " ".join(_words(evidence))
        with fitz.open(dest) as doc:
            for pno, page in enumerate(doc, start=1):
                if ev in " ".join(_words(page.get_text())):
                    return pno
        raise AssertionError(f"evidence not found in rendered PDF {dest.name}: {evidence[:60]}")
    if fmt == "docx":
        idx = body.index(evidence)
        return body[:idx].count(PAGEBREAK) + 1
    return 1


def main() -> int:
    OUT.mkdir(exist_ok=True)
    manifest = {}
    sources = {}
    for src in sorted(SRC.glob("*.md")):
        meta, body = read_source(src)
        name = meta["output"]
        fmt = name.rsplit(".", 1)[1]
        dest = OUT / name
        blocks = md_blocks(body)
        if fmt == "pdf":
            render_pdf(meta, blocks, dest)
        elif fmt == "docx":
            render_docx(meta, blocks, dest)
        elif fmt == "txt":
            dest.write_text(body.replace(PAGEBREAK + "\n", "\f"))
        elif fmt == "md":
            dest.write_text(body.replace(PAGEBREAK + "\n", ""))
        sources[name] = (fmt, dest, body)
        manifest[name] = {"filename": name, "title": meta["title"], "category": meta["category"],
                          "author": meta["author"], "doc_date": meta["date"], "format": fmt}

    questions = [json.loads(line) for line in DATASET.read_text().splitlines() if line.strip()]
    errors, gold = [], {}
    for q in questions:
        for ev in q["evidence"]:
            if ev["doc"] not in sources:
                errors.append(f"{q['id']}: unknown doc {ev['doc']}")
                continue
            fmt, dest, body = sources[ev["doc"]]
            if ev["text"] not in body:
                errors.append(f"{q['id']}: evidence not found verbatim in {ev['doc']}: {ev['text'][:70]}")
                continue
            gold.setdefault(q["id"], []).append({"doc": ev["doc"], "page": gold_pages(fmt, dest, body, ev["text"])})
    if errors:
        print("\n".join(errors))
        return 1
    ids = [q["id"] for q in questions]
    assert len(ids) == len(set(ids)), "duplicate question ids"
    (OUT / "manifest.json").write_text(json.dumps({"documents": manifest, "gold_pages": gold}, indent=2))
    n_ans = sum(1 for q in questions if q["evidence"])
    print(f"built {len(manifest)} documents; {len(questions)} questions ({n_ans} answerable, "
          f"{len(questions) - n_ans} unanswerable, {sum(1 for q in questions if q.get('filters'))} with filters); "
          f"all evidence verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
