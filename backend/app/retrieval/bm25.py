"""BM25 keyword index (Okapi BM25 on an in-memory inverted index) with a light English analyzer.

The index is held in memory per API process and rebuilt from Qdrant payloads whenever the Redis
``index_version`` changes (see ``BM25Manager``). For corpora beyond a few million chunks, swap this
class for an external engine (OpenSearch/Elasticsearch or Postgres full-text search); the pipeline
only depends on ``search()``.
"""
from __future__ import annotations

import asyncio
import re

import numpy as np

from app.retrieval.filters import SearchFilters

_TOKEN = re.compile(r"[a-z0-9]+(?:[.\-'][a-z0-9]+)*")
STOPWORDS = frozenset("""a an and are as at be been but by can could did do does for from had has have how i if in
into is it its may me might must my no not of on or our shall should so such than that the their them then there
these they this those to too under up us was we were what when where which while who whom why will with would you
your about above after again against all am any because before being below between both during each few further
here himself herself itself just more most nor only other out over own same she he some very""".split())


def _stem(t: str) -> str:
    """Very light English suffix stripping (consistent for singular/plural forms)."""
    if len(t) <= 4 or t[-1].isdigit():
        return t
    if t.endswith(("ies", "ied")) and len(t) > 5:
        return t[:-3] + "y"
    if t.endswith(("sses", "shes", "ches", "xes", "zes")):
        return t[:-2]
    if t.endswith("s") and not t.endswith(("ss", "us", "is")):
        t = t[:-1]
    for suf in ("ingly", "edly", "ing", "ed", "ly"):
        if len(t) > len(suf) + 3 and t.endswith(suf):
            return t[: -len(suf)]
    return t


def analyze(text: str) -> list[str]:
    toks = _TOKEN.findall(text.lower())
    return [_stem(t) for t in toks if t not in STOPWORDS]


class BM25Index:
    """Okapi BM25 over an inverted index (numpy postings), with Lucene's non-negative IDF:
    idf(t) = ln(1 + (N - df + 0.5) / (df + 0.5)). Scoring cost is O(postings of the query terms)."""

    def __init__(self, ids: list[str], texts: list[str], payloads: list[dict], k1: float = 1.2, b: float = 0.75):
        self.ids, self.payloads, self.k1, self.b = ids, payloads, k1, b
        self.n = len(ids)
        postings: dict[str, dict[int, int]] = {}
        lengths = np.zeros(self.n, dtype=np.float32)
        for i, text in enumerate(texts):
            toks = analyze(text)
            lengths[i] = len(toks)
            for t in toks:
                d = postings.setdefault(t, {})
                d[i] = d.get(i, 0) + 1
        self.avgdl = float(lengths.mean()) if self.n else 0.0
        self.norm = (k1 * (1 - b + b * lengths / (self.avgdl or 1))).astype(np.float32)
        self.postings = {t: (np.fromiter(d.keys(), dtype=np.int32, count=len(d)),
                             np.fromiter(d.values(), dtype=np.float32, count=len(d))) for t, d in postings.items()}

    def __len__(self) -> int:
        return self.n

    def idf(self, term: str) -> float:
        df = len(self.postings[term][0]) if term in self.postings else 0
        return float(np.log(1 + (self.n - df + 0.5) / (df + 0.5)))

    def get_scores(self, query_terms: list[str]) -> np.ndarray:
        scores = np.zeros(self.n, dtype=np.float32)
        for t in set(query_terms):
            if t not in self.postings:
                continue
            docs, tf = self.postings[t]
            scores[docs] += self.idf(t) * tf * (self.k1 + 1) / (tf + self.norm[docs])
        return scores

    def search(self, query: str, limit: int, filters: SearchFilters | None = None) -> list[tuple[str, float, dict]]:
        if not self.n:
            return []
        q = analyze(query)
        if not q:
            return []
        scores = self.get_scores(q).astype(np.float64)
        if filters and not filters.is_empty():
            mask = np.array([filters.matches(p) for p in self.payloads], dtype=bool)
            scores = np.where(mask, scores, -np.inf)
        order = np.argsort(-scores)[:limit]
        return [(self.ids[i], float(scores[i]), self.payloads[i]) for i in order if np.isfinite(scores[i]) and scores[i] > 0]


class BM25Manager:
    """Caches a BM25 index per collection and rebuilds it when the corpus version changes."""

    def __init__(self):
        self._indexes: dict[str, tuple[int, BM25Index]] = {}
        self._lock = asyncio.Lock()

    async def get(self, store, version: int) -> BM25Index:
        cached = self._indexes.get(store.collection)
        if cached and cached[0] == version:
            return cached[1]
        async with self._lock:
            cached = self._indexes.get(store.collection)
            if cached and cached[0] == version:
                return cached[1]
            ids, texts, payloads = [], [], []
            async for pid, pl in store.scroll_all():
                ids.append(pid)
                texts.append(pl.get("index_text") or pl.get("text", ""))
                payloads.append(pl)
            idx = await asyncio.to_thread(BM25Index, ids, texts, payloads)
            self._indexes[store.collection] = (version, idx)
            return idx

    def invalidate(self, collection: str | None = None) -> None:
        if collection:
            self._indexes.pop(collection, None)
        else:
            self._indexes.clear()


bm25_manager = BM25Manager()
