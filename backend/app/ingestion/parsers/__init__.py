from __future__ import annotations

from pathlib import Path

from app.ingestion.parsers.base import Block, ParsedDocument

SUPPORTED = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
}


class UnsupportedFileType(ValueError):
    pass


def mime_for(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED:
        raise UnsupportedFileType(f"Unsupported file type '{ext}'. Supported: {', '.join(sorted(SUPPORTED))}")
    return SUPPORTED[ext]


def parse_file(path: str, filename: str | None = None) -> ParsedDocument:
    ext = Path(filename or path).suffix.lower()
    if ext == ".pdf":
        from app.ingestion.parsers.pdf import parse_pdf
        return parse_pdf(path)
    if ext == ".docx":
        from app.ingestion.parsers.docx import parse_docx
        return parse_docx(path)
    if ext in (".md", ".markdown"):
        from app.ingestion.parsers.text import parse_markdown
        return parse_markdown(path)
    if ext == ".txt":
        from app.ingestion.parsers.text import parse_text
        return parse_text(path)
    raise UnsupportedFileType(ext)


__all__ = ["Block", "ParsedDocument", "parse_file", "mime_for", "SUPPORTED", "UnsupportedFileType"]
