from __future__ import annotations

import time

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.config import get_settings
from app.core.redis import get_redis
from app.db.session import get_sessionmaker
from app.retrieval.vector_store import get_qdrant

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    return {"status": "ok", "service": get_settings().app_name}


@router.get("/health/ready")
async def ready():
    checks: dict[str, dict] = {}

    async def probe(name, fn):
        t = time.perf_counter()
        try:
            await fn()
            checks[name] = {"ok": True, "ms": round((time.perf_counter() - t) * 1000, 1)}
        except Exception as e:
            checks[name] = {"ok": False, "error": f"{type(e).__name__}: {e}"[:300]}

    async def db():
        async with get_sessionmaker()() as s:
            await s.execute(text("SELECT 1"))

    await probe("postgres", db)
    await probe("redis", lambda: get_redis().ping())
    await probe("qdrant", lambda: get_qdrant().get_collections())
    ok = all(c["ok"] for c in checks.values())
    return JSONResponse({"status": "ready" if ok else "degraded", "checks": checks,
                         "llm_provider": get_settings().resolved_llm_provider}, status_code=200 if ok else 503)
