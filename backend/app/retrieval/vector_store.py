"""Qdrant vector store. Each point is a chunk; payload carries text + filterable document metadata.

``qdrant_url`` may be an http(s) URL (server), ``:memory:`` or ``path:/some/dir`` (embedded local mode,
used by tests and the offline evaluation when no server is running).
"""
from __future__ import annotations

from qdrant_client import AsyncQdrantClient
from qdrant_client import models as qm

from app.config import get_settings

_clients: dict[str, AsyncQdrantClient] = {}

PAYLOAD_INDEXES = {
    "document_id": qm.PayloadSchemaType.KEYWORD,
    "filename": qm.PayloadSchemaType.KEYWORD,
    "category": qm.PayloadSchemaType.KEYWORD,
    "author": qm.PayloadSchemaType.KEYWORD,
    "doc_date_int": qm.PayloadSchemaType.INTEGER,
}


def get_qdrant(url: str | None = None) -> AsyncQdrantClient:
    s = get_settings()
    url = url or s.qdrant_url
    if url not in _clients:
        if url == ":memory:":
            _clients[url] = AsyncQdrantClient(location=":memory:")
        elif url.startswith("path:"):
            _clients[url] = AsyncQdrantClient(path=url[5:])
        else:
            _clients[url] = AsyncQdrantClient(url=url, api_key=s.qdrant_api_key, timeout=30)
    return _clients[url]


async def close_qdrant() -> None:
    for c in _clients.values():
        await c.close()
    _clients.clear()


class VectorStore:
    def __init__(self, collection: str | None = None, client: AsyncQdrantClient | None = None):
        self.collection = collection or get_settings().qdrant_collection
        self.client = client or get_qdrant()

    async def ensure_collection(self, dim: int) -> None:
        if await self.client.collection_exists(self.collection):
            return
        await self.client.create_collection(
            self.collection, vectors_config=qm.VectorParams(size=dim, distance=qm.Distance.COSINE),
            hnsw_config=qm.HnswConfigDiff(m=16, ef_construct=128))
        for field, schema in PAYLOAD_INDEXES.items():
            try:
                await self.client.create_payload_index(self.collection, field, field_schema=schema)
            except Exception:  # local mode does not support payload indexes
                pass

    async def recreate(self, dim: int) -> None:
        if await self.client.collection_exists(self.collection):
            await self.client.delete_collection(self.collection)
        await self.ensure_collection(dim)

    async def upsert(self, ids: list[str], vectors, payloads: list[dict], batch: int = 256) -> None:
        for i in range(0, len(ids), batch):
            await self.client.upsert(self.collection, points=[
                qm.PointStruct(id=pid, vector=vec.tolist() if hasattr(vec, "tolist") else vec, payload=pl)
                for pid, vec, pl in zip(ids[i:i + batch], vectors[i:i + batch], payloads[i:i + batch])], wait=True)

    async def delete_document(self, document_id: str) -> None:
        if not await self.client.collection_exists(self.collection):
            return
        await self.client.delete(self.collection, points_selector=qm.FilterSelector(filter=qm.Filter(
            must=[qm.FieldCondition(key="document_id", match=qm.MatchValue(value=document_id))])), wait=True)

    async def search(self, vector, limit: int, flt: qm.Filter | None = None) -> list[tuple[str, float, dict]]:
        res = await self.client.query_points(self.collection, query=vector.tolist() if hasattr(vector, "tolist") else vector,
                                             limit=limit, query_filter=flt, with_payload=True,
                                             search_params=qm.SearchParams(hnsw_ef=128))
        return [(str(p.id), float(p.score), p.payload or {}) for p in res.points]

    async def scroll_all(self, batch: int = 1024):
        """Yield (id, payload) for every point — used to (re)build the BM25 index."""
        if not await self.client.collection_exists(self.collection):
            return
        offset = None
        while True:
            points, offset = await self.client.scroll(self.collection, limit=batch, offset=offset,
                                                      with_payload=True, with_vectors=False)
            for p in points:
                yield str(p.id), p.payload or {}
            if offset is None:
                break

    async def count(self) -> int:
        if not await self.client.collection_exists(self.collection):
            return 0
        return (await self.client.count(self.collection, exact=True)).count
