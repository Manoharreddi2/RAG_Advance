"""Asynchronous ingestion.

* ``queue`` mode (default): jobs are enqueued on Redis and executed by the arq worker process
  (``arq app.ingestion.worker.WorkerSettings``), so the API never blocks on parsing/embedding.
* ``inline`` mode: jobs run as background asyncio tasks inside the API process (single-container
  deployments such as a Render free instance, and integration tests).
"""
from __future__ import annotations

import asyncio

from arq import create_pool
from arq.connections import RedisSettings

from app.config import get_settings
from app.ingestion.pipeline import process_document
from app.logging import configure_logging, get_logger

log = get_logger("worker")
_pool = None
_inline_sem = asyncio.Semaphore(2)
_inline_tasks: set[asyncio.Task] = set()


async def _get_pool():
    global _pool
    if _pool is None:
        _pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    return _pool


async def enqueue_ingestion(document_id: str, job_id: str) -> None:
    if get_settings().ingest_mode == "inline":
        async def run():
            async with _inline_sem:
                await process_document(document_id, job_id)
        t = asyncio.create_task(run())
        _inline_tasks.add(t)
        t.add_done_callback(_inline_tasks.discard)
        return
    pool = await _get_pool()
    await pool.enqueue_job("ingest_document", document_id, job_id, _job_id=f"ingest:{job_id}")


async def wait_inline_jobs() -> None:
    """Testing helper: wait for in-process ingestion tasks to finish."""
    while _inline_tasks:
        await asyncio.gather(*list(_inline_tasks), return_exceptions=True)


async def ingest_document(ctx, document_id: str, job_id: str) -> None:
    await process_document(document_id, job_id)


async def _startup(ctx):
    configure_logging(get_settings().log_level)
    from app.retrieval.models import get_embedder
    await asyncio.to_thread(get_embedder)  # warm the model once per worker
    log.info("worker_started")


class WorkerSettings:
    functions = [ingest_document]
    on_startup = _startup
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_jobs = 2
    job_timeout = 1800
    max_tries = 3
