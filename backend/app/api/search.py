from __future__ import annotations

import time

from fastapi import APIRouter, Depends

from app.api.schemas import SearchIn, SearchOut
from app.core.rate_limit import rate_limiter
from app.db.models import User
from app.deps import get_current_user
from app.retrieval.service import get_pipeline
from app.services.query_log import summarize_retrieved, write_query_log

router = APIRouter(tags=["search"], dependencies=[Depends(rate_limiter("search"))])


@router.post("/search", response_model=SearchOut, summary="Retrieval only (configurable pipeline + metadata filters)")
async def search(body: SearchIn, user: User = Depends(get_current_user)):
    t = time.perf_counter()
    error = None
    try:
        res = await get_pipeline().retrieve(body.query, body.config, body.filters)
        results = [c.to_dict() for c in res.chunks]
        return SearchOut(query=body.query, results=results, timings_ms=res.timings_ms, config=res.config,
                         filters=res.filters)
    except Exception as e:
        error, results = f"{type(e).__name__}: {e}", []
        raise
    finally:
        ms = (time.perf_counter() - t) * 1000
        await write_query_log(user_id=user.id, endpoint="search", query=body.query,
                              retrieval_config=body.config.model_dump(), filters=body.filters.model_dump(mode="json"),
                              retrieved=summarize_retrieved(results), retrieval_ms=ms, total_ms=ms, error=error)
