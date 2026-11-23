"""Integration fixtures: real Postgres (migrated with Alembic), Redis, Qdrant (embedded), real models.

Requires a Postgres database reachable at TEST_DATABASE_URL and Redis at TEST_REDIS_URL.
The LLM is replaced by a deterministic test double so the tests don't depend on generation speed.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
os.environ.update({
    "DATABASE_URL": os.environ.get("TEST_DATABASE_URL", "postgresql+asyncpg://rag:rag@localhost:5432/rag_test"),
    "REDIS_URL": os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/15"),
    "QDRANT_URL": ":memory:",
    "INGEST_MODE": "inline",
    "STORAGE_DIR": tempfile.mkdtemp(prefix="rag-test-"),
    "JWT_SECRET": "test-secret-key-that-is-at-least-32-bytes-long",
    "RATE_LIMIT_CHAT_PER_MINUTE": "8",
    "ENVIRONMENT": "test",
    "LLM_PROVIDER": "local",
})


class EchoLLM:
    """Test double: answers with the first sentence of passage [1] and cites it; abstains on 'unknowable'."""
    name = "test-echo-llm"

    async def stream(self, messages, max_tokens=None, temperature=None):
        user = messages[-1]["content"]
        if "unknowable" in user.lower():
            from app.generation.prompts import NO_ANSWER
            yield "token", NO_ANSWER
        else:
            first = user.split("[1]", 1)[1].split(":\n", 1)[1].split("\n\n[2]")[0]
            sentence = first.split(". ")[0].strip().rstrip(".")
            for word in f"According to the documents, {sentence} [1].".split(" "):
                yield "token", word + " "
        yield "usage", {"prompt_tokens": len(user) // 4, "completion_tokens": 20, "model": self.name}

    async def complete(self, messages, max_tokens=None, temperature=None):
        if "Standalone question" in messages[-1]["content"]:
            last = messages[-1]["content"].split("Last message:")[1].split("\n")[0].strip()
            return f"parental leave {last}", {"prompt_tokens": 10, "completion_tokens": 5}
        parts = []
        async for k, v in self.stream(messages):
            if k == "token":
                parts.append(v)
        return "".join(parts), {}


@pytest.fixture(scope="session", autouse=True)
def migrated_db():
    url = os.environ["DATABASE_URL"]
    env = {**os.environ, "DATABASE_URL": url}
    subprocess.run([sys.executable, "-m", "alembic", "downgrade", "base"], cwd=BACKEND, env=env, check=True,
                   capture_output=True)
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env, check=True,
                   capture_output=True)
    yield


@pytest.fixture(scope="session")
async def app():
    import redis.asyncio as aioredis
    r = aioredis.from_url(os.environ["REDIS_URL"])
    await r.flushdb()
    await r.aclose()
    from app.api import chat
    chat.get_llm = lambda: EchoLLM()
    from app.main import create_app
    yield create_app()


@pytest.fixture(scope="session")
async def client(app):
    import httpx
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", timeout=120) as c:
        yield c
