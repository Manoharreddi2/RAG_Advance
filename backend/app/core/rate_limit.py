"""Redis sliding-window rate limiter (sorted set per identity + bucket)."""
from __future__ import annotations

import time
import uuid

from fastapi import HTTPException, Request, status

from app.core.redis import get_redis
from app.logging import get_logger

log = get_logger("rate_limit")


async def check_rate_limit(identity: str, bucket: str, limit: int, window_s: int = 60) -> tuple[bool, int]:
    """Returns (allowed, remaining). Fails open if Redis is unavailable (logged)."""
    key = f"rl:{bucket}:{identity}"
    now = time.time()
    r = get_redis()
    try:
        async with r.pipeline(transaction=True) as p:
            p.zremrangebyscore(key, 0, now - window_s)
            p.zadd(key, {f"{now}:{uuid.uuid4().hex[:8]}": now})
            p.zcard(key)
            p.expire(key, window_s + 1)
            _, _, count, _ = await p.execute()
    except Exception as e:  # pragma: no cover - infrastructure failure
        log.warning("rate_limit_unavailable", error=str(e))
        return True, limit
    return count <= limit, max(0, limit - count)


def _identity(request: Request) -> str:
    """Authenticated user id from the bearer token if valid, else client IP."""
    from app.core.security import decode_token
    auth = request.headers.get("authorization", "")
    token = auth[7:] if auth.lower().startswith("bearer ") else request.query_params.get("access_token")
    if token:
        try:
            return "u:" + decode_token(token)["sub"]
        except Exception:
            pass
    fwd = request.headers.get("x-forwarded-for")
    return "ip:" + (fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "unknown"))


def rate_limiter(bucket: str, limit_attr: str = "rate_limit_per_minute"):
    """FastAPI dependency factory. Identity = authenticated user id, else client IP."""
    from app.config import get_settings

    async def dep(request: Request):
        limit = getattr(get_settings(), limit_attr)
        ident = _identity(request)
        allowed, remaining = await check_rate_limit(ident, bucket, limit)
        request.state.rate_limit_remaining = remaining
        if not allowed:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail=f"Rate limit exceeded ({limit}/min)",
                                headers={"Retry-After": "60"})
    return dep
