from __future__ import annotations

import redis.asyncio as aioredis

from app.config import get_settings

_client: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _client
    if _client is None:
        _client = aioredis.from_url(get_settings().redis_url, decode_responses=True)
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
    _client = None


INDEX_VERSION_KEY = "rag:index_version"


async def get_index_version() -> int:
    v = await get_redis().get(INDEX_VERSION_KEY)
    return int(v or 0)


async def bump_index_version() -> int:
    return int(await get_redis().incr(INDEX_VERSION_KEY))
