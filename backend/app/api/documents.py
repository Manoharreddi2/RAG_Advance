from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import date
from pathlib import Path

import aiofiles
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ChunkOut, DocumentList, DocumentOut, DocumentUpdate, Facets, UploadResult
from app.config import get_settings
from app.core.rate_limit import rate_limiter
from app.db.models import Chunk, Document, IngestionJob, User
from app.db.session import get_db
from app.deps import get_current_user, require_role
from app.ingestion.parsers import UnsupportedFileType, mime_for
from app.ingestion.pipeline import delete_document_index
from app.ingestion.worker import enqueue_ingestion
from app.logging import get_logger

router = APIRouter(prefix="/documents", tags=["documents"], dependencies=[Depends(rate_limiter("documents"))])
log = get_logger("documents")


def _safe_name(name: str) -> str:
    name = os.path.basename(name or "upload").replace("\x00", "")
    return name[:255] or "upload"


async def _save_upload(f: UploadFile, max_bytes: int) -> tuple[Path, str, int]:
    s = get_settings()
    s.storage_dir.mkdir(parents=True, exist_ok=True)
    tmp = s.storage_dir / f".tmp-{uuid.uuid4().hex}"
    h, size = hashlib.sha256(), 0
    async with aiofiles.open(tmp, "wb") as out:
        while chunk := await f.read(1024 * 1024):
            size += len(chunk)
            if size > max_bytes:
                await out.close()
                tmp.unlink(missing_ok=True)
                raise ValueError(f"File exceeds {max_bytes // (1024 * 1024)} MB limit")
            h.update(chunk)
            await out.write(chunk)
    return tmp, h.hexdigest(), size


@router.post("", response_model=list[UploadResult], status_code=202,
             summary="Batch upload documents (duplicates detected by content hash; same filename = new version)")
async def upload_documents(
    files: list[UploadFile] = File(...),
    category: str | None = Form(None), author: str | None = Form(None), doc_date: date | None = Form(None),
    tags: str | None = Form(None, description="Comma-separated tags applied to all files"),
    metadata: str | None = Form(None, description='Optional JSON: {"<filename>": {"category":..,"author":..,"doc_date":..,"title":..}}'),
    user: User = Depends(require_role("editor")), db: AsyncSession = Depends(get_db),
):
    s = get_settings()
    per_file = json.loads(metadata) if metadata else {}
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    results: list[UploadResult] = []
    jobs: list[tuple[str, str]] = []
    for f in files:
        name = _safe_name(f.filename)
        try:
            mime = mime_for(name)
            tmp, digest, size = await _save_upload(f, s.max_upload_mb * 1024 * 1024)
        except (UnsupportedFileType, ValueError) as e:
            results.append(UploadResult(filename=name, status="rejected", detail=str(e)))
            continue
        if size == 0:
            tmp.unlink(missing_ok=True)
            results.append(UploadResult(filename=name, status="rejected", detail="Empty file"))
            continue
        meta = per_file.get(name, {})
        dup = await db.scalar(select(Document).where(Document.content_hash == digest))
        if dup:
            tmp.unlink(missing_ok=True)
            results.append(UploadResult(filename=name, status="duplicate", document=DocumentOut.model_validate(dup),
                                        detail=f"Identical content already ingested as '{dup.filename}'"))
            continue
        existing = await db.scalar(select(Document).where(Document.filename == name))
        dest_dir = s.storage_dir / digest[:2]
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{digest}{Path(name).suffix.lower()}"
        os.replace(tmp, dest)
        d_date = meta.get("doc_date") or doc_date
        if isinstance(d_date, str):
            d_date = date.fromisoformat(d_date)
        if existing:  # document update -> new version; chunks are replaced by the worker
            old_path = existing.storage_path
            existing.content_hash, existing.size_bytes, existing.storage_path = digest, size, str(dest)
            existing.version += 1
            existing.status, existing.error = "pending", None
            existing.title = meta.get("title") or existing.title
            existing.category = meta.get("category") or category or existing.category
            existing.author = meta.get("author") or author or existing.author
            existing.doc_date = d_date or existing.doc_date
            existing.tags = meta.get("tags") or tag_list or existing.tags
            doc, status = existing, "updated"
            if old_path != str(dest):
                Path(old_path).unlink(missing_ok=True)
        else:
            doc = Document(filename=name, title=meta.get("title"), content_hash=digest, mime_type=mime, size_bytes=size,
                           category=meta.get("category") or category, author=meta.get("author") or author,
                           doc_date=d_date, tags=meta.get("tags") or tag_list, storage_path=str(dest),
                           uploaded_by=user.id)
            db.add(doc)
            status = "created"
        await db.flush()
        job = IngestionJob(document_id=doc.id)
        db.add(job)
        await db.commit()
        await db.refresh(doc)
        jobs.append((str(doc.id), str(job.id)))
        results.append(UploadResult(filename=name, status=status, document=DocumentOut.model_validate(doc)))
        log.info("document_uploaded", filename=name, status=status, size=size, version=doc.version)
    for doc_id, job_id in jobs:
        await enqueue_ingestion(doc_id, job_id)
    return results


@router.get("", response_model=DocumentList)
async def list_documents(q: str | None = None, category: str | None = None, author: str | None = None,
                         status: str | None = None, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
                         _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    stmt = select(Document)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Document.filename.ilike(like), Document.title.ilike(like)))
    if category:
        stmt = stmt.where(Document.category == category)
    if author:
        stmt = stmt.where(Document.author == author)
    if status:
        stmt = stmt.where(Document.status == status)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = await db.scalars(stmt.order_by(Document.updated_at.desc()).offset((page - 1) * page_size).limit(page_size))
    return DocumentList(items=list(rows), total=total or 0, page=page, page_size=page_size)


@router.get("/facets", response_model=Facets)
async def facets(_: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    ready = Document.status == "ready"
    cats = await db.scalars(select(Document.category).where(ready, Document.category.isnot(None)).distinct())
    auths = await db.scalars(select(Document.author).where(ready, Document.author.isnot(None)).distinct())
    names = await db.scalars(select(Document.filename).where(ready).order_by(Document.filename))
    dmin, dmax = (await db.execute(select(func.min(Document.doc_date), func.max(Document.doc_date)).where(ready))).one()
    return Facets(categories=sorted(cats), authors=sorted(auths), filenames=list(names), date_min=dmin, date_max=dmax)


async def _get_doc(db: AsyncSession, document_id: uuid.UUID) -> Document:
    doc = await db.get(Document, document_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    return doc


@router.get("/{document_id}", response_model=DocumentOut)
async def get_document(document_id: uuid.UUID, _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await _get_doc(db, document_id)


@router.patch("/{document_id}", response_model=DocumentOut)
async def update_document(document_id: uuid.UUID, body: DocumentUpdate, _: User = Depends(require_role("editor")),
                          db: AsyncSession = Depends(get_db)):
    """Update metadata; triggers re-indexing so vector payload filters stay consistent."""
    doc = await _get_doc(db, document_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(doc, k, v)
    doc.status = "pending"
    job = IngestionJob(document_id=doc.id)
    db.add(job)
    await db.commit()
    await db.refresh(doc)
    await enqueue_ingestion(str(doc.id), str(job.id))
    return doc


@router.get("/{document_id}/chunks", response_model=list[ChunkOut])
async def document_chunks(document_id: uuid.UUID, _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _get_doc(db, document_id)
    rows = await db.scalars(select(Chunk).where(Chunk.document_id == document_id).order_by(Chunk.chunk_index))
    return list(rows)


@router.get("/{document_id}/file")
async def document_file(document_id: uuid.UUID, _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    doc = await _get_doc(db, document_id)
    if not Path(doc.storage_path).exists():
        raise HTTPException(410, "Stored file is missing")
    return FileResponse(doc.storage_path, media_type=doc.mime_type, filename=doc.filename,
                        content_disposition_type="inline")


@router.post("/{document_id}/reindex", response_model=DocumentOut, status_code=202)
async def reindex(document_id: uuid.UUID, _: User = Depends(require_role("editor")), db: AsyncSession = Depends(get_db)):
    doc = await _get_doc(db, document_id)
    doc.status = "pending"
    job = IngestionJob(document_id=doc.id)
    db.add(job)
    await db.commit()
    await db.refresh(doc)
    await enqueue_ingestion(str(doc.id), str(job.id))
    return doc


@router.delete("/{document_id}", status_code=204)
async def delete_document(document_id: uuid.UUID, _: User = Depends(require_role("editor")),
                          db: AsyncSession = Depends(get_db)):
    doc = await _get_doc(db, document_id)
    path = doc.storage_path
    await delete_document_index(str(doc.id))
    await db.delete(doc)
    await db.commit()
    Path(path).unlink(missing_ok=True)
