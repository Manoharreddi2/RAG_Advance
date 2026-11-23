"""Answer cache in Redis. Keys include the corpus index version, so any ingestion invalidates them."""
from __future__ import annotations

import hashlib
import json

from app.config import get_settings
from app.core.redis import get_index_version, get_redis
from app.logging import get_logger

log = get_logger("cache")


async def make_key(kind: str, payload: dict) -> str:
    version = await get_index_version()
    raw = json.dumps(payload, sort_keys=True, default=str)
    return f"cache:{kind}:v{version}:{hashlib.sha256(raw.encode()).hexdigest()}"


async def cache_get(key: str) -> dict | None:
    try:
        v = await get_redis().get(key)
        return json.loads(v) if v else None
    except Exception as e:  # pragma: no cover
        log.warning("cache_get_failed", error=str(e))
        return None


async def cache_set(key: str, value: dict, ttl: int | None = None) -> None:
    try:
        await get_redis().set(key, json.dumps(value, default=str), ex=ttl or get_settings().cache_ttl_seconds)
    except Exception as e:  # pragma: no cover
        log.warning("cache_set_failed", error=str(e))
