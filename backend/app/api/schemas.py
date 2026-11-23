from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.retrieval.filters import SearchFilters
from app.retrieval.pipeline import RetrievalConfig


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---- auth ----
class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = None


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserOut"


class UserOut(ORM):
    id: uuid.UUID
    email: str
    full_name: str | None
    role: str
    is_active: bool
    created_at: datetime


class UserUpdate(BaseModel):
    role: str | None = Field(default=None, pattern="^(viewer|editor|admin)$")
    is_active: bool | None = None


# ---- documents ----
class DocumentOut(ORM):
    id: uuid.UUID
    filename: str
    title: str | None
    mime_type: str
    size_bytes: int
    category: str | None
    author: str | None
    doc_date: date | None
    tags: list
    version: int
    status: str
    error: str | None
    page_count: int | None
    chunk_count: int
    created_at: datetime
    updated_at: datetime


class UploadResult(BaseModel):
    filename: str
    status: str  # created | updated | duplicate | rejected
    document: DocumentOut | None = None
    detail: str | None = None


class DocumentList(BaseModel):
    items: list[DocumentOut]
    total: int
    page: int
    page_size: int


class ChunkOut(ORM):
    id: uuid.UUID
    chunk_index: int
    text: str
    section_path: str | None
    page_start: int | None
    page_end: int | None
    chunk_type: str
    token_count: int


class DocumentUpdate(BaseModel):
    title: str | None = None
    category: str | None = None
    author: str | None = None
    doc_date: date | None = None
    tags: list[str] | None = None


class Facets(BaseModel):
    categories: list[str]
    authors: list[str]
    filenames: list[str]
    date_min: date | None
    date_max: date | None


# ---- search / chat ----
class SearchIn(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    config: RetrievalConfig = Field(default_factory=RetrievalConfig)
    filters: SearchFilters = Field(default_factory=SearchFilters)


class SearchOut(BaseModel):
    query: str
    results: list[dict]
    timings_ms: dict
    config: dict
    filters: dict


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: uuid.UUID | None = None
    config: RetrievalConfig = Field(default_factory=RetrievalConfig)
    filters: SearchFilters = Field(default_factory=SearchFilters)
    use_cache: bool = True


class ChatOut(BaseModel):
    conversation_id: uuid.UUID
    message_id: uuid.UUID
    answer: str
    citations: list[dict]
    quotes: list[dict]
    abstained: bool
    sources: list[dict]
    standalone_query: str
    usage: dict
    timings_ms: dict
    model: str
    cache_hit: bool


class MessageOut(ORM):
    id: uuid.UUID
    role: str
    content: str
    citations: list
    created_at: datetime


class ConversationOut(ORM):
    id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationDetail(ConversationOut):
    messages: list[MessageOut]


TokenOut.model_rebuild()
