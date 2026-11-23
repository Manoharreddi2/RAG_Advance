"""Persist one row per user query: retrieved chunks, timings, tokens, cost, cache hit, errors."""
from __future__ import annotations

import uuid

from app.db.models import QueryLog
from app.db.session import get_sessionmaker
from app.logging import get_logger

log = get_logger("query_log")


def summarize_retrieved(chunks: list[dict]) -> list[dict]:
    return [{"chunk_id": c.get("chunk_id"), "document_id": c.get("document_id"), "filename": c.get("filename"),
             "page_start": c.get("page_start"), "score": c.get("score"), "scores": c.get("scores"),
             "rank": i + 1} for i, c in enumerate(chunks)]


async def write_query_log(**fields) -> None:
    """Best effort: logging must never break a user request."""
    try:
        for k in ("user_id", "conversation_id"):
            if isinstance(fields.get(k), str):
                fields[k] = uuid.UUID(fields[k])
        async with get_sessionmaker()() as db:
            db.add(QueryLog(**fields))
            await db.commit()
        log.info("query", endpoint=fields.get("endpoint"), total_ms=fields.get("total_ms"),
                 cache_hit=fields.get("cache_hit"), prompt_tokens=fields.get("prompt_tokens"),
                 completion_tokens=fields.get("completion_tokens"), error=fields.get("error"),
                 n_retrieved=len(fields.get("retrieved") or []))
    except Exception as e:  # pragma: no cover
        log.error("query_log_failed", error=str(e))
