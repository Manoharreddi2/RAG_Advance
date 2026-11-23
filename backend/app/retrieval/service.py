"""Wiring of the production retrieval pipeline (singleton per process)."""
from __future__ import annotations

from functools import lru_cache

from app.core.redis import get_index_version
from app.retrieval.bm25 import bm25_manager
from app.retrieval.models import get_embedder, get_reranker
from app.retrieval.pipeline import RetrievalPipeline
from app.retrieval.vector_store import VectorStore


@lru_cache
def get_pipeline() -> RetrievalPipeline:
    store = VectorStore()

    async def bm25_provider():
        return await bm25_manager.get(store, await get_index_version())

    return RetrievalPipeline(store, get_embedder(), get_reranker(), bm25_provider)
