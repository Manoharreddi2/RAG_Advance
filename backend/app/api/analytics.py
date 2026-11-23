"""Performance analytics computed from the query log (SQL aggregates, no sampling)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Integer, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document, QueryLog, User
from app.db.session import get_db
from app.deps import require_role

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/summary")
async def summary(days: int = Query(7, ge=1, le=365), _: User = Depends(require_role("admin")),
                  db: AsyncSession = Depends(get_db)):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    base = QueryLog.created_at >= since
    agg = (await db.execute(select(
        func.count(QueryLog.id),
        func.avg(QueryLog.total_ms),
        func.percentile_cont(0.5).within_group(QueryLog.total_ms),
        func.percentile_cont(0.95).within_group(QueryLog.total_ms),
        func.avg(QueryLog.retrieval_ms),
        func.avg(QueryLog.generation_ms),
        func.sum(QueryLog.prompt_tokens),
        func.sum(QueryLog.completion_tokens),
        func.sum(QueryLog.cost_usd),
        func.avg(cast(QueryLog.cache_hit, Integer)),
        func.avg(cast(QueryLog.abstained, Integer)),
        func.count(QueryLog.error),
    ).where(base))).one()
    by_endpoint = dict((await db.execute(select(QueryLog.endpoint, func.count()).where(base)
                                         .group_by(QueryLog.endpoint))).all())
    day = func.date_trunc("day", QueryLog.created_at)
    series = (await db.execute(select(day, func.count(), func.avg(QueryLog.total_ms),
                                      func.percentile_cont(0.95).within_group(QueryLog.total_ms),
                                      func.sum(QueryLog.prompt_tokens + QueryLog.completion_tokens),
                                      func.sum(QueryLog.cost_usd), func.count(QueryLog.error))
                               .where(base).group_by(day).order_by(day))).all()
    docs = dict((await db.execute(select(Document.status, func.count()).group_by(Document.status))).all())
    chunks = await db.scalar(select(func.coalesce(func.sum(Document.chunk_count), 0)))
    f = lambda v, n=1: round(float(v), n) if v is not None else None  # noqa: E731
    return {
        "window_days": days,
        "queries": agg[0], "by_endpoint": by_endpoint,
        "latency_ms": {"avg": f(agg[1]), "p50": f(agg[2]), "p95": f(agg[3]), "retrieval_avg": f(agg[4]),
                       "generation_avg": f(agg[5])},
        "tokens": {"prompt": int(agg[6] or 0), "completion": int(agg[7] or 0)},
        "cost_usd": round(float(agg[8] or 0), 6),
        "cache_hit_rate": f(agg[9], 4), "abstention_rate": f(agg[10], 4), "errors": agg[11],
        "documents": {"by_status": docs, "chunks": int(chunks or 0)},
        "series": [{"day": d.date().isoformat(), "queries": n, "avg_ms": f(a), "p95_ms": f(p), "tokens": int(t or 0),
                    "cost_usd": round(float(c or 0), 6), "errors": e} for d, n, a, p, t, c, e in series],
    }


@router.get("/queries")
async def queries(limit: int = Query(50, ge=1, le=500), errors_only: bool = False,
                  _: User = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)):
    stmt = select(QueryLog).order_by(QueryLog.created_at.desc()).limit(limit)
    if errors_only:
        stmt = stmt.where(QueryLog.error.isnot(None))
    rows = await db.scalars(stmt)
    return [{"id": str(r.id), "created_at": r.created_at, "endpoint": r.endpoint, "query": r.query,
             "standalone_query": r.standalone_query, "total_ms": r.total_ms, "retrieval_ms": r.retrieval_ms,
             "generation_ms": r.generation_ms, "prompt_tokens": r.prompt_tokens, "completion_tokens": r.completion_tokens,
             "cost_usd": r.cost_usd, "model": r.model, "cache_hit": r.cache_hit, "abstained": r.abstained,
             "error": r.error, "retrieved": r.retrieved, "config": r.retrieval_config, "filters": r.filters}
            for r in rows]
