"""End-to-end RAG answering as a stream of events (no persistence — used by API and evaluation).

Events (dicts with a ``type`` key):
  {"type": "rewrite", "standalone_query": str}
  {"type": "sources", "chunks": [...], "timings_ms": {...}}
  {"type": "token", "text": str}
  {"type": "done", "answer", "citations", "quotes", "abstained", "usage", "timings_ms", "model"}
"""
from __future__ import annotations

import time
from collections.abc import AsyncIterator

from app.config import get_settings
from app.generation.answer import postprocess
from app.generation.llm import BaseLLM, cost_usd
from app.generation.prompts import NO_ANSWER, build_messages
from app.generation.rewrite import standalone_question
from app.retrieval.filters import SearchFilters
from app.retrieval.pipeline import RetrievalConfig, RetrievalPipeline


async def answer_stream(question: str, pipeline: RetrievalPipeline, llm: BaseLLM, history: list[dict] | None = None,
                        config: RetrievalConfig | None = None, filters: SearchFilters | None = None,
                        abstain_threshold: float | None = None) -> AsyncIterator[dict]:
    s = get_settings()
    t0 = time.perf_counter()
    history = history or []
    usage_total = {"prompt_tokens": 0, "completion_tokens": 0}

    query, rw_usage = await standalone_question(llm, question, history)
    for k in usage_total:
        usage_total[k] += rw_usage.get(k, 0)
    if query != question:
        yield {"type": "rewrite", "standalone_query": query}

    result = await pipeline.retrieve(query, config, filters)
    chunks = [c.to_dict() for c in result.chunks]
    retrieval_ms = (time.perf_counter() - t0) * 1000
    yield {"type": "sources", "chunks": chunks, "timings_ms": result.timings_ms, "config": result.config,
           "filters": result.filters}

    threshold = s.abstain_threshold if abstain_threshold is None else abstain_threshold
    best = result.best_rerank_score
    gate_abstain = not chunks or (best is not None and best < threshold)

    t_gen = time.perf_counter()
    model = getattr(llm, "name", "unknown")
    if gate_abstain:
        # Relevance gate: nothing relevant was retrieved, so do not let the LLM improvise.
        text = NO_ANSWER
        yield {"type": "token", "text": text}
    else:
        parts = []
        async for kind, val in llm.stream(build_messages(question if not history else query, chunks, history)):
            if kind == "token":
                parts.append(val)
                yield {"type": "token", "text": val}
            else:
                for k in usage_total:
                    usage_total[k] += val.get(k, 0)
                model = val.get("model", model)
        text = "".join(parts)
    gen_ms = (time.perf_counter() - t_gen) * 1000

    post = postprocess(text, chunks)
    usage_total["cost_usd"] = cost_usd(usage_total)
    yield {"type": "done", **post, "standalone_query": query, "gated": gate_abstain, "usage": usage_total,
           "model": model, "timings_ms": {"retrieval_ms": round(retrieval_ms, 1), "generation_ms": round(gen_ms, 1),
                                          "total_ms": round((time.perf_counter() - t0) * 1000, 1),
                                          **{f"retrieval_{k}": v for k, v in result.timings_ms.items()}}}
