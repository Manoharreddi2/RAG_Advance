"""Evaluation runner: compares five retrieval configurations end to end on the benchmark dataset.

  1. basic_vector          fixed 1000-char chunks, raw text embeddings, dense search
  2. chunking_vector       structure-aware chunks with heading context, dense search
  3. hybrid                (2) + BM25, fused with Reciprocal Rank Fusion
  4. hybrid_rerank         (3) + cross-encoder reranking (+ relevance-gated abstention)
  5. hybrid_rerank_filter  (4) + the question's user-supplied metadata filters

Everything runs through the production code paths (parsers, chunkers, embedder, Qdrant, BM25, RRF,
reranker, prompt, citation parser). Results are written to eval/results/<run>.json and a Markdown report
with charts to docs/benchmarks/. Usage:

  python -m eval.run                      # full run (retrieval + generation)
  python -m eval.run --no-generation      # retrieval metrics only (minutes)
  python -m eval.run --limit 20           # quick smoke run
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import random
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

from app.config import get_settings  # noqa: E402
from app.generation.answer import postprocess  # noqa: E402
from app.generation.llm import cost_usd  # noqa: E402
from app.generation.prompts import NO_ANSWER, build_messages, format_passage  # noqa: E402
from app.generation.rewrite import standalone_question  # noqa: E402
from app.ingestion.pipeline import build_chunks, index_chunks  # noqa: E402
from app.retrieval.bm25 import BM25Index  # noqa: E402
from app.retrieval.filters import SearchFilters  # noqa: E402
from app.retrieval.models import get_embedder, get_nli, get_reranker  # noqa: E402
from app.retrieval.pipeline import RetrievalConfig, RetrievalPipeline  # noqa: E402
from app.retrieval.vector_store import VectorStore, get_qdrant  # noqa: E402
from eval import build_corpus  # noqa: E402
from eval.metrics import (answer_correctness, citation_metrics, faithfulness, mean, percentile,  # noqa: E402
                          retrieval_metrics)

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
REPORTS = ROOT.parent.parent / "docs" / "benchmarks"

CONFIGS = [
    {"name": "basic_vector", "label": "1. Basic vector search", "strategy": "fixed",
     "retrieval": {"mode": "dense", "rerank": False, "use_filters": False}},
    {"name": "chunking_vector", "label": "2. Improved chunking + vector", "strategy": "structured",
     "retrieval": {"mode": "dense", "rerank": False, "use_filters": False}},
    {"name": "hybrid", "label": "3. Hybrid (BM25 + vector, RRF)", "strategy": "structured",
     "retrieval": {"mode": "hybrid", "rerank": False, "use_filters": False}},
    {"name": "hybrid_rerank", "label": "4. Hybrid + reranking", "strategy": "structured",
     "retrieval": {"mode": "hybrid", "rerank": True, "use_filters": False}},
    {"name": "hybrid_rerank_filter", "label": "5. Hybrid + reranking + filters", "strategy": "structured",
     "retrieval": {"mode": "hybrid", "rerank": True, "use_filters": True}},
]
CONTEXT_K = 5      # passages given to the LLM
RETRIEVE_K = 10    # depth retrieved for Recall@10


def load_questions(limit: int | None) -> list[dict]:
    qs = [json.loads(line) for line in (ROOT / "dataset" / "questions.jsonl").read_text().splitlines() if line.strip()]
    return qs[:limit] if limit else qs


async def build_indexes(qdrant_url: str, strategies: set[str]) -> tuple[dict, dict]:
    manifest = json.loads((ROOT / "corpus" / "manifest.json").read_text())["documents"]
    pipelines, stats = {}, {}
    embedder, reranker = get_embedder(), get_reranker()
    for strategy in sorted(strategies):
        store = VectorStore(collection=f"eval_{strategy}", client=get_qdrant(qdrant_url))
        await store.recreate(embedder.dim)
        t, n_chunks, tokens = time.perf_counter(), 0, []
        for name, meta in manifest.items():
            kw = {"size_chars": 1000, "overlap_chars": 0} if strategy == "fixed" else {}
            _, chunks = build_chunks(str(ROOT / "corpus" / name), name, strategy, **kw)
            doc_meta = {**meta, "document_id": str(uuid.uuid5(uuid.NAMESPACE_URL, name))}
            # deterministic ids so cached generations stay valid across re-runs
            ids = [str(uuid.uuid5(uuid.NAMESPACE_URL, f"{strategy}/{name}/{c.chunk_index}/{c.text}")) for c in chunks]
            await index_chunks(store, doc_meta, chunks, ids=ids, contextual=(strategy == "structured"))
            n_chunks += len(chunks)
            tokens += [c.token_count for c in chunks]
        ids, texts, payloads = [], [], []
        async for pid, pl in store.scroll_all():
            ids.append(pid)
            texts.append(pl["index_text"])
            payloads.append(pl)
        bm25 = BM25Index(ids, texts, payloads)

        async def provider(idx=bm25):
            return idx
        pipelines[strategy] = RetrievalPipeline(store, embedder, reranker, provider)
        stats[strategy] = {"chunks": n_chunks, "avg_tokens": round(sum(tokens) / len(tokens), 1),
                           "index_seconds": round(time.perf_counter() - t, 2)}
        print(f"indexed strategy={strategy}: {stats[strategy]}", flush=True)
    return pipelines, stats


class PacedLLM:
    """Wraps an LLM for long benchmark runs: optional requests-per-minute pacing and retry with backoff on
    rate-limit / transient errors, so free-tier quotas slow the run down instead of corrupting results."""

    def __init__(self, llm, rpm: float | None = None, retries: int = 8):
        self.llm, self.name, self.retries = llm, llm.name, retries
        self.min_interval = 60.0 / rpm if rpm else 0.0
        self._last = 0.0

    async def complete(self, messages, max_tokens=None, temperature=None):
        for attempt in range(self.retries + 1):
            wait = self._last + self.min_interval - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last = time.monotonic()
            try:
                return await self.llm.complete(messages, max_tokens, temperature)
            except Exception as e:  # LLMError wraps the provider error text
                msg = str(e)
                if "per day" in msg or "PerDay" in msg:
                    raise SystemExit(f"Daily LLM quota exhausted - completed generations are checkpointed; "
                                     f"re-run the same command after the quota resets.\n{msg[:600]}")
                transient = any(k in msg for k in ("429", "RateLimit", "rate limit", "503", "500", "Timeout", "overloaded"))
                if not transient or attempt == self.retries:
                    raise
                delay = min(15 * (attempt + 1), 90)
                print(f"  LLM transient error ({msg[:300]}), retry {attempt + 1} in {delay}s", flush=True)
                await asyncio.sleep(delay)


class GenCache:
    """Append-only checkpoint so long generation runs can resume."""

    def __init__(self, path: Path):
        self.path = path
        self.data = {}
        if path.exists():
            for line in path.read_text().splitlines():
                if line.strip():
                    rec = json.loads(line)
                    self.data[rec["key"]] = rec
        self.fh = path.open("a")

    def get(self, key):
        return self.data.get(key)

    def put(self, rec):
        self.data[rec["key"]] = rec
        self.fh.write(json.dumps(rec) + "\n")
        self.fh.flush()


async def run(args) -> Path:
    s = get_settings()
    assert build_corpus.main() == 0, "corpus build/validation failed"
    gold_pages = json.loads((ROOT / "corpus" / "manifest.json").read_text())["gold_pages"]
    questions = load_questions(args.limit)
    configs = [c for c in CONFIGS if not args.configs or c["name"] in args.configs]
    pipelines, index_stats = await build_indexes(args.qdrant, {c["strategy"] for c in configs})

    llm = None
    if not args.no_generation:
        from app.generation.llm import get_llm
        llm = PacedLLM(get_llm(), rpm=args.llm_rpm)
        nli = get_nli()
    RESULTS.mkdir(exist_ok=True)
    model_name = getattr(llm, "name", None)
    cache = GenCache(RESULTS / f".gen_cache_{hashlib.md5(str(model_name).encode()).hexdigest()[:8]}.jsonl")

    # Conversational follow-ups: rewrite once into a standalone query (shared by all configs).
    standalone = {}
    for q in questions:
        if q.get("history"):
            if llm:
                key = f"rewrite|{q['id']}|{q['question']}"
                rec = cache.get(key)
                if not rec:
                    text, usage = await standalone_question(llm, q["question"], q["history"])
                    rec = {"key": key, "text": text, "usage": usage}
                    cache.put(rec)
                standalone[q["id"]] = rec["text"]
            else:
                prev = next(m["content"] for m in reversed(q["history"]) if m["role"] == "user")
                standalone[q["id"]] = f"{prev} {q['question']}"

    per_question = []
    for cfg in configs:
        pipe = pipelines[cfg["strategy"]]
        rcfg = RetrievalConfig(top_k=RETRIEVE_K, candidates=30, rerank_depth=30, **cfg["retrieval"])
        print(f"\n== {cfg['label']} ==", flush=True)
        for i, q in enumerate(questions, start=1):
            query = standalone.get(q["id"], q["question"])
            filters = SearchFilters(**q["filters"]) if q.get("filters") else None
            res = await pipe.retrieve(query, rcfg, filters)
            chunks = [c.to_dict() for c in res.chunks]
            row = {"config": cfg["name"], "id": q["id"], "type": q["type"], "answerable": bool(q["evidence"]),
                   "has_filters": bool(q.get("filters")), "query": query,
                   "retrieval_ms": res.timings_ms["total_ms"],
                   "retrieved": [{"filename": c["filename"], "page_start": c["page_start"], "score": c["score"],
                                  "chunk_id": c["chunk_id"]} for c in chunks]}
            if q["evidence"]:
                row.update(retrieval_metrics(chunks, q["evidence"]))
            if llm:
                ctx = chunks[:CONTEXT_K]
                best = max((c["scores"].get("rerank", float("-inf")) for c in ctx), default=None)
                gated = cfg["retrieval"]["rerank"] and (not ctx or best < s.abstain_threshold)
                key = "gen|" + hashlib.sha256(json.dumps([q["id"], query, [c["chunk_id"] for c in ctx], gated,
                                                          model_name]).encode()).hexdigest()
                rec = cache.get(key)
                if not rec:
                    t = time.perf_counter()
                    if gated:
                        text, usage = NO_ANSWER, {"prompt_tokens": 0, "completion_tokens": 0}
                    else:
                        text, usage = await llm.complete(build_messages(query if q.get("history") else q["question"],
                                                                        ctx, q.get("history")),
                                                         max_tokens=args.max_tokens)
                    rec = {"key": key, "text": text, "usage": usage, "generation_ms": (time.perf_counter() - t) * 1000}
                    cache.put(rec)
                    row["generation_cached"] = False
                else:
                    row["generation_cached"] = True
                post = postprocess(rec["text"], ctx)
                row.update({"answer": rec["text"], "abstained": post["abstained"], "gated": gated,
                            "generation_ms": rec["generation_ms"], "prompt_tokens": rec["usage"].get("prompt_tokens", 0),
                            "completion_tokens": rec["usage"].get("completion_tokens", 0)})
                row["total_ms"] = row["retrieval_ms"] + row["generation_ms"]
                row["cost_usd"] = cost_usd(rec["usage"])
                row["projected_cost_usd"] = (row["prompt_tokens"] * s.projected_price_input_per_m
                                             + row["completion_tokens"] * s.projected_price_output_per_m) / 1e6
                row.update(answer_correctness(rec["text"], q["key_facts"], bool(q["evidence"]), post["abstained"]))
                if q["evidence"] and not post["abstained"]:
                    # judge against the passages exactly as the LLM saw them (header: title, date, page, section)
                    row.update(faithfulness(rec["text"], [format_passage(i, c) for i, c in enumerate(ctx, 1)], nli))
                    row.update(citation_metrics(rec["text"], ctx, q["evidence"], gold_pages.get(q["id"], [])))
            per_question.append(row)
            if i % 10 == 0 or i == len(questions):
                print(f"  {i}/{len(questions)}", flush=True)

    summary = summarize(per_question, configs)
    env = {"embedding_model": s.embedding_model, "reranker_model": s.reranker_model, "nli_model": s.nli_model,
           "llm": model_name, "llm_provider": s.resolved_llm_provider if llm else None,
           "price_per_m_tokens": {"input": s.price_input_per_m, "output": s.price_output_per_m},
           "projected_price_per_m_tokens": {"input": s.projected_price_input_per_m,
                                            "output": s.projected_price_output_per_m},
           "llm_reasoning_effort": s.llm_reasoning_effort,
           "context_k": CONTEXT_K, "retrieve_k": RETRIEVE_K, "abstain_threshold": s.abstain_threshold,
           "index": index_stats, "n_questions": len(questions),
           "n_answerable": sum(1 for q in questions if q["evidence"]),
           "n_with_filters": sum(1 for q in questions if q.get("filters")),
           "python": platform.python_version(), "machine": platform.machine(), "cpu_count": os.cpu_count(),
           "device": s.device, "generation": llm is not None}
    run_name = args.run_name or f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    out = {"run_name": run_name, "created_at": datetime.now(timezone.utc).isoformat(), "environment": env,
           "configurations": configs, "summary": summary, "per_question": per_question}
    path = RESULTS / f"{run_name}.json"
    path.write_text(json.dumps(out, indent=1, default=str))
    print(f"\nwrote {path}")
    from eval.report import write_report
    print(f"report: {write_report(out, REPORTS)}")
    return path


def bootstrap_ci(values: list[float], n: int = 2000, seed: int = 7) -> tuple[float, float] | None:
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return None
    rng = random.Random(seed)
    means = sorted(sum(rng.choice(vals) for _ in vals) / len(vals) for _ in range(n))
    return round(means[int(0.025 * n)], 4), round(means[int(0.975 * n)], 4)


def _agg(rows: list[dict]) -> dict:
    ans = [r for r in rows if r["answerable"]]
    m = {}
    for key in ("recall@1", "recall@3", "recall@5", "recall@10", "precision@1", "precision@3", "precision@5",
                "hit@5", "mrr", "top1_doc_correct"):
        m[key] = mean(r.get(key) for r in ans)
    m["recall@5_ci95"] = bootstrap_ci([r.get("recall@5") for r in ans])
    m["mrr_ci95"] = bootstrap_ci([r.get("mrr") for r in ans])
    m["retrieval_ms_p50"] = percentile([r["retrieval_ms"] for r in rows], 0.5)
    m["retrieval_ms_p95"] = percentile([r["retrieval_ms"] for r in rows], 0.95)
    if rows and "answer" in rows[0]:
        unans = [r for r in rows if not r["answerable"]]
        m["answer_correctness"] = mean(r["correct"] for r in ans)
        m["answer_correctness_ci95"] = bootstrap_ci([r["correct"] for r in ans])
        m["key_fact_recall"] = mean(r["key_fact_recall"] for r in ans)
        m["faithfulness"] = mean(r.get("faithfulness") for r in ans)
        m["citation_precision"] = mean(r.get("citation_precision") for r in ans)
        m["citation_page_accuracy"] = mean(r.get("citation_page_accuracy") for r in ans)
        m["citation_rate"] = mean(r.get("has_citation", 0.0) for r in ans if not r["abstained"])
        m["false_abstention_rate"] = mean(float(r["abstained"]) for r in ans)
        m["unanswerable_abstention_rate"] = mean(float(r["abstained"]) for r in unans)
        m["overall_correctness"] = mean(r["correct"] for r in rows)
        m["latency_ms_p50"] = percentile([r["total_ms"] for r in rows], 0.5)
        m["latency_ms_p95"] = percentile([r["total_ms"] for r in rows], 0.95)
        m["latency_ms_mean"] = mean(r["total_ms"] for r in rows)
        m["generation_ms_mean"] = mean(r["generation_ms"] for r in rows)
        m["prompt_tokens_mean"] = mean(r["prompt_tokens"] for r in rows)
        m["completion_tokens_mean"] = mean(r["completion_tokens"] for r in rows)
        m["cost_per_query_usd"] = mean(r["cost_usd"] for r in rows)
        m["projected_cost_per_query_usd"] = mean(r["projected_cost_usd"] for r in rows)
    m["n"] = len(rows)
    m["n_answerable"] = len(ans)
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in m.items()}


def summarize(rows: list[dict], configs: list[dict]) -> dict:
    out = {}
    for cfg in configs:
        rs = [r for r in rows if r["config"] == cfg["name"]]
        out[cfg["name"]] = {
            "label": cfg["label"], "overall": _agg(rs),
            "with_filters": _agg([r for r in rs if r["has_filters"]]),
            "without_filters": _agg([r for r in rs if not r["has_filters"]]),
            "by_type": {t: _agg([r for r in rs if r["type"] == t]) for t in sorted({r["type"] for r in rs})},
        }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-generation", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--configs", nargs="*")
    ap.add_argument("--qdrant", default=os.environ.get("EVAL_QDRANT_URL", get_settings().qdrant_url))
    ap.add_argument("--max-tokens", type=int, default=300)
    ap.add_argument("--llm-rpm", type=float, help="max LLM requests per minute (free-tier quotas)")
    ap.add_argument("--run-name")
    asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    main()
