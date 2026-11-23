"""Application settings, loaded from environment variables (and an optional .env file)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- app ---
    app_name: str = "Enterprise Document Intelligence"
    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    api_prefix: str = "/api/v1"
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["http://localhost:5173", "http://localhost:8080"])

    # --- security ---
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 12
    allow_registration: bool = True

    # --- infrastructure ---
    database_url: str = "postgresql+asyncpg://rag:rag@localhost:5432/rag"
    redis_url: str = "redis://localhost:6379/0"
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None
    qdrant_collection: str = "chunks"
    storage_dir: Path = Path("./data/uploads")
    max_upload_mb: int = 50

    # --- ingestion ---
    ingest_mode: Literal["queue", "inline"] = "queue"  # inline = process in the API process (tests, small deploys)
    chunk_max_tokens: int = 350
    chunk_overlap_sentences: int = 1

    # --- models ---
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_query_prefix: str = "Represent this sentence for searching relevant passages: "
    embedding_batch_size: int = 32
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    nli_model: str = "cross-encoder/nli-deberta-v3-xsmall"
    device: str = "cpu"

    # --- LLM ---
    llm_provider: Literal["auto", "openai", "openai_compatible", "local"] = "auto"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str | None = None  # for openai_compatible (Ollama/vLLM/LM Studio)
    local_llm_model: str = "Qwen/Qwen2.5-1.5B-Instruct"
    llm_temperature: float = 0.0
    llm_max_tokens: int = 512
    # Passed as `reasoning_effort` when set (e.g. "none" for Gemini 2.5 Flash, "low" for o-series models).
    llm_reasoning_effort: str | None = None
    # USD per 1M tokens actually charged for the configured model (0 for free tiers / local models).
    price_input_per_m: float = 0.15
    price_output_per_m: float = 0.60
    # Reference price used for the *projected* cost in evaluation reports (default: gpt-4o-mini list price).
    projected_price_input_per_m: float = 0.15
    projected_price_output_per_m: float = 0.60

    # --- retrieval defaults ---
    retrieval_top_k: int = 5
    retrieval_candidates: int = 30
    rrf_k: int = 60
    abstain_threshold: float = -4.0  # min cross-encoder logit for the best passage

    # --- performance ---
    cache_ttl_seconds: int = 3600
    rate_limit_per_minute: int = 60
    rate_limit_chat_per_minute: int = 20

    qdrant_host: str | None = None  # "host:port" (e.g. a Render private service); overrides qdrant_url

    @field_validator("database_url", mode="after")
    @classmethod
    def _async_driver(cls, v: str) -> str:
        # managed providers (Render, Heroku) hand out postgres:// or postgresql:// URLs
        for prefix in ("postgres://", "postgresql://"):
            if v.startswith(prefix):
                return "postgresql+asyncpg://" + v[len(prefix):]
        return v

    @field_validator("qdrant_url", mode="after")
    @classmethod
    def _strip_slash(cls, v: str) -> str:
        return v.rstrip("/")

    def model_post_init(self, __context) -> None:
        if self.qdrant_host:
            self.qdrant_url = self.qdrant_host if "://" in self.qdrant_host else f"http://{self.qdrant_host}"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v):
        if isinstance(v, str):
            if v.strip().startswith("["):
                import json
                return json.loads(v)
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    def validate_for_production(self) -> None:
        if self.environment == "production" and (self.jwt_secret == "change-me-in-production" or len(self.jwt_secret) < 32):
            raise RuntimeError("JWT_SECRET must be set to a random value of at least 32 characters in production")

    @property
    def resolved_llm_provider(self) -> str:
        if self.llm_provider != "auto":
            return self.llm_provider
        if self.openai_api_key:
            return "openai"
        if self.openai_base_url:
            return "openai_compatible"
        return "local"


@lru_cache
def get_settings() -> Settings:
    return Settings()
