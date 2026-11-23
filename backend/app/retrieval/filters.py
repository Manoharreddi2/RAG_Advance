"""Metadata filters, translated both to Qdrant payload filters and to an in-memory predicate (BM25)."""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field
from qdrant_client import models as qm


def date_to_int(d: date | str | None) -> int | None:
    if d is None:
        return None
    if isinstance(d, str):
        d = date.fromisoformat(d[:10])
    return d.year * 10000 + d.month * 100 + d.day


class SearchFilters(BaseModel):
    document_ids: list[str] = Field(default_factory=list)
    filenames: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    authors: list[str] = Field(default_factory=list)
    date_from: date | None = None
    date_to: date | None = None

    def is_empty(self) -> bool:
        return not (self.document_ids or self.filenames or self.categories or self.authors
                    or self.date_from or self.date_to)

    def to_qdrant(self) -> qm.Filter | None:
        if self.is_empty():
            return None
        must: list = []
        for key, values in (("document_id", self.document_ids), ("filename", self.filenames),
                            ("category", self.categories), ("author", self.authors)):
            if values:
                must.append(qm.FieldCondition(key=key, match=qm.MatchAny(any=list(values))))
        if self.date_from or self.date_to:
            must.append(qm.FieldCondition(key="doc_date_int", range=qm.Range(
                gte=date_to_int(self.date_from), lte=date_to_int(self.date_to))))
        return qm.Filter(must=must)

    def matches(self, payload: dict) -> bool:
        if self.document_ids and payload.get("document_id") not in self.document_ids:
            return False
        if self.filenames and payload.get("filename") not in self.filenames:
            return False
        if self.categories and payload.get("category") not in self.categories:
            return False
        if self.authors and payload.get("author") not in self.authors:
            return False
        d = payload.get("doc_date_int")
        if self.date_from and (d is None or d < date_to_int(self.date_from)):
            return False
        if self.date_to and (d is None or d > date_to_int(self.date_to)):
            return False
        return True
