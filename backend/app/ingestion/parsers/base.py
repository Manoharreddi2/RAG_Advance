"""Common parsed-document representation produced by every parser."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

BlockType = Literal["heading", "paragraph", "list", "table"]


@dataclass
class Block:
    type: BlockType
    text: str
    page: int = 1
    level: int = 0  # heading level (1 = top); 0 for non-headings


@dataclass
class ParsedDocument:
    blocks: list[Block]
    page_count: int = 1
    title: str | None = None
    author: str | None = None
    doc_date: date | None = None
    extra: dict = field(default_factory=dict)

    @property
    def full_text(self) -> str:
        return "\n\n".join(b.text for b in self.blocks)


def table_to_markdown(rows: list[list[str | None]]) -> str:
    rows = [[(c or "").replace("\n", " ").strip() for c in r] for r in rows if r and any((c or "").strip() for c in r)]
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    header, body = rows[0], rows[1:]
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    lines += ["| " + " | ".join(r) + " |" for r in body]
    return "\n".join(lines)
