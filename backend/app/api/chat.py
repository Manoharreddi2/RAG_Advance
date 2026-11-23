"""Grounded chat: JSON endpoint and Server-Sent Events streaming endpoint.

Both share ``_run_chat`` which handles conversation persistence, the Redis answer cache, the RAG
event stream and query logging.
"""
from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.api.schemas import ChatIn, ChatOut
from app.core.cache import cache_get, cache_set, make_key
from app.core.rate_limit import rate_limiter
from app.db.models import Conversation, Message, User
from app.db.session import get_db, get_sessionmaker
from app.deps import get_current_user
from app.generation.llm import get_llm
from app.logging import get_logger
from app.retrieval.service import get_pipeline
from app.services.query_log import summarize_retrieved, write_query_log
from app.services.rag import answer_stream

router = APIRouter(prefix="/chat", tags=["chat"],
                   dependencies=[Depends(rate_limiter("chat", "rate_limit_chat_per_minute"))])
log = get_logger("chat")


async def _conversation(db: AsyncSession, user: User, conv_id: uuid.UUID | None, first_message: str) -> Conversation:
    if conv_id:
        conv = await db.get(Conversation, conv_id)
        if not conv or conv.user_id != user.id:
            raise HTTPException(404, "Conversation not found")
        return conv
    conv = Conversation(user_id=user.id, title=first_message[:80])
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return conv


async def _history(db: AsyncSession, conv_id: uuid.UUID) -> list[dict]:
    rows = await db.scalars(select(Message).where(Message.conversation_id == conv_id)
                            .order_by(Message.created_at.desc()).limit(6))
    return [{"role": m.role, "content": m.content} for m in reversed(list(rows))]


async def _run_chat(body: ChatIn, user: User, db: AsyncSession) -> AsyncIterator[dict]:
    t0 = time.perf_counter()
    conv = await _conversation(db, user, body.conversation_id, body.message)
    history = await _history(db, conv.id)
    yield {"type": "conversation", "conversation_id": str(conv.id)}

    key = await make_key("chat", {"q": body.message.strip().lower(), "h": history[-4:],
                                  "c": body.config.model_dump(), "f": body.filters.model_dump(mode="json")})
    cached = await cache_get(key) if body.use_cache else None
    final, sources, error = None, [], None
    try:
        if cached:
            sources = cached["sources"]
            yield {"type": "sources", "chunks": sources, "timings_ms": {}, "cached": True}
            yield {"type": "token", "text": cached["answer"]}
            final = {**cached["done"], "cache_hit": True}
        else:
            async for ev in answer_stream(body.message, get_pipeline(), get_llm(), history, body.config, body.filters):
                if ev["type"] == "sources":
                    sources = ev["chunks"]
                if ev["type"] == "done":
                    final = {**ev, "cache_hit": False}
                    continue
                yield ev
            if final and not final.get("error"):
                await cache_set(key, {"sources": sources, "answer": final["answer"], "done": final})
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
        log.exception("chat_failed", error=error)
        yield {"type": "error", "detail": "Answer generation failed. The error has been logged."}

    total_ms = (time.perf_counter() - t0) * 1000
    async with get_sessionmaker()() as s2:
        s2.add(Message(conversation_id=conv.id, role="user", content=body.message))
        assistant = None
        if final:
            assistant = Message(conversation_id=conv.id, role="assistant", content=final["answer"],
                                citations=final["citations"])
            s2.add(assistant)
        c = await s2.get(Conversation, conv.id)
        c.title = c.title or body.message[:80]
        await s2.commit()
    usage = (final or {}).get("usage", {})
    timings = (final or {}).get("timings_ms", {})
    await write_query_log(
        user_id=user.id, conversation_id=conv.id, endpoint="chat", query=body.message,
        standalone_query=(final or {}).get("standalone_query"), retrieval_config=body.config.model_dump(),
        filters=body.filters.model_dump(mode="json"), retrieved=summarize_retrieved(sources),
        response=(final or {}).get("answer"), retrieval_ms=None if final and final["cache_hit"] else timings.get("retrieval_ms"),
        generation_ms=None if final and final["cache_hit"] else timings.get("generation_ms"), total_ms=total_ms,
        prompt_tokens=0 if final and final["cache_hit"] else usage.get("prompt_tokens", 0),
        completion_tokens=0 if final and final["cache_hit"] else usage.get("completion_tokens", 0),
        cost_usd=0.0 if final and final["cache_hit"] else usage.get("cost_usd", 0.0),
        model=(final or {}).get("model"), cache_hit=bool(final and final["cache_hit"]),
        abstained=bool(final and final.get("abstained")), error=error)
    if final:
        yield {"type": "done", **final, "conversation_id": str(conv.id),
               "message_id": str(assistant.id) if assistant else None, "sources": sources,
               "timings_ms": {**final.get("timings_ms", {}), "request_total_ms": round(total_ms, 1)}}


@router.post("", response_model=ChatOut, summary="Grounded answer with citations (non-streaming)")
async def chat(body: ChatIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    final = None
    async for ev in _run_chat(body, user, db):
        if ev["type"] == "error":
            raise HTTPException(502, ev["detail"])
        if ev["type"] == "done":
            final = ev
    return ChatOut(conversation_id=final["conversation_id"], message_id=final["message_id"], answer=final["answer"],
                   citations=final["citations"], quotes=final["quotes"], abstained=final["abstained"],
                   sources=final["sources"], standalone_query=final["standalone_query"], usage=final["usage"],
                   timings_ms=final["timings_ms"], model=final["model"], cache_hit=final["cache_hit"])


@router.post("/stream", summary="Grounded answer streamed as Server-Sent Events",
             description="Events: `conversation`, `rewrite`, `sources`, `token`, `done`, `error` (JSON data).")
async def chat_stream(body: ChatIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    async def gen():
        async for ev in _run_chat(body, user, db):
            yield {"event": ev["type"], "data": json.dumps(ev, default=str)}
    return EventSourceResponse(gen(), ping=15, headers={"X-Accel-Buffering": "no"})
