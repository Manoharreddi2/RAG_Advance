"""Lazily-loaded singletons for the embedding model, cross-encoder reranker and NLI model."""
from __future__ import annotations

import threading
from functools import lru_cache

import numpy as np

from app.config import get_settings

_lock = threading.Lock()


class Embedder:
    def __init__(self, model_name: str, query_prefix: str = "", device: str = "cpu", batch_size: int = 32):
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(model_name, device=device)
        self.query_prefix = query_prefix
        self.batch_size = batch_size
        self.dim = self.model.get_sentence_embedding_dimension()
        self.name = model_name

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return self.model.encode(texts, batch_size=self.batch_size, normalize_embeddings=True,
                                 convert_to_numpy=True, show_progress_bar=False)

    def embed_query(self, text: str) -> np.ndarray:
        return self.model.encode([self.query_prefix + text], normalize_embeddings=True, convert_to_numpy=True,
                                 show_progress_bar=False)[0]


class Reranker:
    def __init__(self, model_name: str, device: str = "cpu"):
        from sentence_transformers import CrossEncoder
        self.model = CrossEncoder(model_name, device=device, max_length=512)
        self.name = model_name

    def score(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        return [float(s) for s in self.model.predict([(query, p) for p in passages], batch_size=32,
                                                      show_progress_bar=False)]


class NLIScorer:
    """Entailment probability of hypothesis given premise (used for faithfulness evaluation)."""

    def __init__(self, model_name: str, device: str = "cpu"):
        from sentence_transformers import CrossEncoder
        self.model = CrossEncoder(model_name, device=device, max_length=512)
        labels = {v.lower(): k for k, v in self.model.model.config.id2label.items()}
        self.entail_idx = labels.get("entailment", 1)

    def entailment(self, pairs: list[tuple[str, str]]) -> list[float]:
        if not pairs:
            return []
        logits = self.model.predict(pairs, batch_size=16, show_progress_bar=False, apply_softmax=True)
        return [float(row[self.entail_idx]) for row in np.atleast_2d(logits)]


@lru_cache
def get_embedder() -> Embedder:
    s = get_settings()
    with _lock:
        return Embedder(s.embedding_model, s.embedding_query_prefix, s.device, s.embedding_batch_size)


@lru_cache
def get_reranker() -> Reranker:
    s = get_settings()
    with _lock:
        return Reranker(s.reranker_model, s.device)


@lru_cache
def get_nli() -> NLIScorer:
    s = get_settings()
    with _lock:
        return NLIScorer(s.nli_model, s.device)
