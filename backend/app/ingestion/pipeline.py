"""Document processing: parse -> chunk -> embed -> index (Qdrant + Postgres).

``build_chunks`` and ``index_chunks`` are pure building blocks also used by the evaluation harness.
``process_document`` is the job executed by the worker for an uploaded document.
"""
from __future__ import annotations

import asyncio
import traceback
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import delete, select

from app.config import get_settings
from app.core.redis import bump_index_version
from app.db.models import Chunk, Document, IngestionJob
from app.db.session import get_sessionmaker
from app.ingestion.chunking import ChunkData, chunk_document, contextualize
from app.ingestion.parsers import ParsedDocument, parse_file
from app.logging import get_logger
from app.retrieval.filters import date_to_int
from app.retrieval.models import get_embedder
from app.retrieval.vector_store import VectorStore

log = get_logger("ingestion")


def build_chunks(path: str, filename: str, strategy: str = "structured", **kw) -> tuple[ParsedDocument, list[ChunkData]]:
    parsed = parse_file(path, filename)
    if strategy == "structured":
        s = get_settings()
        kw.setdefault("max_tokens", s.chunk_max_tokens)
        kw.setdefault("overlap_sentences", s.chunk_overlap_sentences)
    return parsed, chunk_document(parsed, strategy, **kw)


def chunk_payload(doc_meta: dict, c: ChunkData, contextual: bool = True) -> dict:
    doc_date = doc_meta.get("doc_date")
    if isinstance(doc_date, date):
        doc_date = doc_date.isoformat()
    return {
        "document_id": doc_meta["document_id"], "filename": doc_meta["filename"], "title": doc_meta.get("title"),
        "category": doc_meta.get("category"), "author": doc_meta.get("author"), "doc_date": doc_date,
        "doc_date_int": date_to_int(doc_date), "version": doc_meta.get("version", 1), "chunk_index": c.chunk_index,
        "page_start": c.page_start, "page_end": c.page_end, "section_path": c.section_path,
        "chunk_type": c.chunk_type, "text": c.text,
        "index_text": contextualize(c.text, doc_meta.get("title"), c.section_path) if contextual else c.text,
    }


async def index_chunks(store: VectorStore, doc_meta: dict, chunks: list[ChunkData], ids: list[str] | None = None,
                       contextual: bool = True) -> list[str]:
    embedder = get_embedder()
    await store.ensure_collection(embedder.dim)
    ids = ids or [str(uuid.uuid4()) for _ in chunks]
    payloads = [chunk_payload(doc_meta, c, contextual) for c in chunks]
    vectors = await asyncio.to_thread(embedder.embed_documents, [p["index_text"] for p in payloads])
    await store.upsert(ids, vectors, payloads)
    return ids


async def process_document(document_id: str, job_id: str | None = None) -> None:
    """Worker job: (re)index one document. Idempotent: previous chunks/vectors of the document are replaced."""
    sm = get_sessionmaker()
    store = VectorStore()
    async with sm() as db:
        doc = await db.get(Document, uuid.UUID(document_id))
        if doc is None:
            log.warning("ingest_missing_document", document_id=document_id)
            return
        job = await db.get(IngestionJob, uuid.UUID(job_id)) if job_id else None
        doc.status, doc.error = "processing", None
        if job:
            job.status, job.started_at, job.attempts = "running", datetime.now(timezone.utc), job.attempts + 1
        await db.commit()
        t0 = datetime.now(timezone.utc)
        try:
            parsed, chunks = await asyncio.to_thread(build_chunks, doc.storage_path, doc.filename)
            if not chunks:
                raise ValueError("No extractable text found in document")
            # user-supplied metadata wins over metadata parsed from the file
            doc.title = doc.title or parsed.title or doc.filename
            doc.author = doc.author or parsed.author
            doc.doc_date = doc.doc_date or parsed.doc_date
            doc.page_count = parsed.page_count
            meta = {"document_id": str(doc.id), "filename": doc.filename, "title": doc.title, "category": doc.category,
                    "author": doc.author, "doc_date": doc.doc_date, "version": doc.version}
            # replace previous version atomically from the reader's perspective: delete old vectors, then upsert
            await store.delete_document(str(doc.id))
            ids = [str(uuid.uuid4()) for _ in chunks]
            await index_chunks(store, meta, chunks, ids)
            await db.execute(delete(Chunk).where(Chunk.document_id == doc.id))
            db.add_all([Chunk(id=uuid.UUID(i), document_id=doc.id, chunk_index=c.chunk_index, text=c.text,
                              section_path=c.section_path[:1024] if c.section_path else None, page_start=c.page_start,
                              page_end=c.page_end, chunk_type=c.chunk_type, token_count=c.token_count)
                        for i, c in zip(ids, chunks)])
            doc.chunk_count, doc.status = len(chunks), "ready"
            if job:
                job.status, job.finished_at = "succeeded", datetime.now(timezone.utc)
            await db.commit()
            await bump_index_version()
            log.info("ingest_succeeded", document_id=document_id, filename=doc.filename, chunks=len(chunks),
                     pages=parsed.page_count, seconds=(datetime.now(timezone.utc) - t0).total_seconds())
        except Exception as e:
            await db.rollback()
            doc = await db.get(Document, uuid.UUID(document_id))
            doc.status, doc.error = "failed", f"{type(e).__name__}: {e}"[:2000]
            if job_id:
                job = await db.get(IngestionJob, uuid.UUID(job_id))
                job.status, job.error, job.finished_at = "failed", traceback.format_exc()[-4000:], datetime.now(timezone.utc)
            await db.commit()
            log.error("ingest_failed", document_id=document_id, error=str(e))


async def delete_document_index(document_id: str) -> None:
    await VectorStore().delete_document(document_id)
    await bump_index_version()


async def pending_documents() -> list[str]:
    async with get_sessionmaker()() as db:
        rows = await db.execute(select(Document.id).where(Document.status.in_(("pending", "processing"))))
        return [str(r) for r in rows.scalars()]
