"""Configurable retrieval pipeline: dense | bm25 | hybrid(RRF) -> optional cross-encoder rerank -> top-k.

The same class is used by the API and by the evaluation harness so measured numbers reflect production code.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from app.config import get_settings
from app.retrieval.bm25 import BM25Index
from app.retrieval.filters import SearchFilters


class RetrievalConfig(BaseModel):
    mode: Literal["dense", "bm25", "hybrid"] = "hybrid"
    top_k: int = Field(default_factory=lambda: get_settings().retrieval_top_k, ge=1, le=50)
    candidates: int = Field(default_factory=lambda: get_settings().retrieval_candidates, ge=1, le=200)
    rrf_k: int = Field(default_factory=lambda: get_settings().rrf_k, ge=1)
    rerank: bool = True
    rerank_depth: int = Field(default=30, ge=1, le=200)  # how many fused candidates are re-scored
    use_filters: bool = True


@dataclass
class RetrievedChunk:
    chunk_id: str
    payload: dict
    score: float
    scores: dict = field(default_factory=dict)  # per-stage scores: dense, bm25, rrf, rerank
    ranks: dict = field(default_factory=dict)

    @property
    def text(self) -> str:
        return self.payload.get("text", "")

    def to_dict(self) -> dict:
        p = self.payload
        return {"chunk_id": self.chunk_id, "document_id": p.get("document_id"), "filename": p.get("filename"),
                "title": p.get("title"), "section": p.get("section_path"), "page_start": p.get("page_start"),
                "page_end": p.get("page_end"), "chunk_type": p.get("chunk_type"), "category": p.get("category"),
                "author": p.get("author"), "doc_date": p.get("doc_date"), "text": p.get("text"),
                "score": round(self.score, 6), "scores": {k: round(v, 6) for k, v in self.scores.items()},
                "ranks": self.ranks}


@dataclass
class RetrievalResult:
    chunks: list[RetrievedChunk]
    timings_ms: dict
    config: dict
    filters: dict

    @property
    def best_rerank_score(self) -> float | None:
        vals = [c.scores["rerank"] for c in self.chunks if "rerank" in c.scores]
        return max(vals) if vals else None


def reciprocal_rank_fusion(ranked_lists: dict[str, list[str]], k: int = 60) -> dict[str, float]:
    """RRF(d) = Σ_lists 1 / (k + rank_list(d)), ranks starting at 1."""
    fused: dict[str, float] = {}
    for ids in ranked_lists.values():
        for rank, cid in enumerate(ids, start=1):
            fused[cid] = fused.get(cid, 0.0) + 1.0 / (k + rank)
    return fused


class RetrievalPipeline:
    def __init__(self, vector_store, embedder, reranker=None, bm25_provider=None):
        """bm25_provider: async callable returning a BM25Index for the current corpus."""
        self.store = vector_store
        self.embedder = embedder
        self.reranker = reranker
        self.bm25_provider = bm25_provider

    async def retrieve(self, query: str, config: RetrievalConfig | None = None,
                       filters: SearchFilters | None = None) -> RetrievalResult:
        cfg = config or RetrievalConfig()
        flt = filters if (filters and cfg.use_filters and not filters.is_empty()) else None
        timings: dict[str, float] = {}
        t_all = time.perf_counter()
        pool: dict[str, RetrievedChunk] = {}
        ranked: dict[str, list[str]] = {}

        async def dense():
            t = time.perf_counter()
            vec = await asyncio.to_thread(self.embedder.embed_query, query)
            hits = await self.store.search(vec, cfg.candidates, flt.to_qdrant() if flt else None)
            timings["dense_ms"] = (time.perf_counter() - t) * 1000
            return hits

        async def keyword():
            t = time.perf_counter()
            idx: BM25Index = await self.bm25_provider()
            hits = await asyncio.to_thread(idx.search, query, cfg.candidates, flt)
            timings["bm25_ms"] = (time.perf_counter() - t) * 1000
            return hits

        tasks = {}
        if cfg.mode in ("dense", "hybrid"):
            tasks["dense"] = dense()
        if cfg.mode in ("bm25", "hybrid"):
            if self.bm25_provider is None:
                raise ValueError("BM25 requested but no index provider configured")
            tasks["bm25"] = keyword()
        results = dict(zip(tasks.keys(), await asyncio.gather(*tasks.values())))

        for name, hits in results.items():
            ranked[name] = []
            for rank, (cid, score, payload) in enumerate(hits, start=1):
                c = pool.setdefault(cid, RetrievedChunk(cid, payload, 0.0))
                c.scores[name] = score
                c.ranks[name] = rank
                ranked[name].append(cid)

        if cfg.mode == "hybrid":
            fused = reciprocal_rank_fusion(ranked, cfg.rrf_k)
            for cid, s in fused.items():
                pool[cid].scores["rrf"] = s
            order = sorted(fused, key=fused.get, reverse=True)
        else:
            order = ranked[cfg.mode]
        candidates = [pool[cid] for cid in order]
        for c in candidates:
            c.score = c.scores.get("rrf", c.scores.get(cfg.mode, 0.0))

        if cfg.rerank and self.reranker is not None and candidates:
            t = time.perf_counter()
            head = candidates[: cfg.rerank_depth]
            texts = [c.payload.get("index_text") or c.text for c in head]
            scores = await asyncio.to_thread(self.reranker.score, query, texts)
            for c, s in zip(head, scores):
                c.scores["rerank"] = s
                c.score = s
            candidates = sorted(head, key=lambda c: c.score, reverse=True)
            timings["rerank_ms"] = (time.perf_counter() - t) * 1000

        final = candidates[: cfg.top_k]
        for i, c in enumerate(final, start=1):
            c.ranks["final"] = i
        timings["total_ms"] = (time.perf_counter() - t_all) * 1000
        return RetrievalResult(final, {k: round(v, 2) for k, v in timings.items()}, cfg.model_dump(),
                               flt.model_dump(mode="json") if flt else {})
