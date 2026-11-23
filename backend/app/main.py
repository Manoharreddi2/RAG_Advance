from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import analytics, auth, chat, conversations, documents, eval as eval_api, health, search
from app.config import get_settings
from app.core.redis import close_redis
from app.db.session import dispose_engine
from app.logging import configure_logging, get_logger
from app.retrieval.vector_store import close_qdrant

log = get_logger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    s.storage_dir.mkdir(parents=True, exist_ok=True)
    log.info("startup", environment=s.environment, llm_provider=s.resolved_llm_provider, ingest_mode=s.ingest_mode)
    yield
    await close_qdrant()
    await close_redis()
    await dispose_engine()


def create_app() -> FastAPI:
    s = get_settings()
    s.validate_for_production()
    configure_logging(s.log_level, json=s.environment != "development")
    app = FastAPI(
        title=s.app_name, version="1.0.0", lifespan=lifespan,
        description="Production-grade RAG: hybrid retrieval (dense + BM25 + RRF), cross-encoder reranking, "
                    "metadata filtering, grounded answers with citations, SSE streaming and an evaluation suite.",
        openapi_tags=[{"name": n} for n in ("auth", "users", "documents", "search", "chat", "conversations",
                                             "analytics", "evaluation", "health")])
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_origins, allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=rid, path=request.url.path, method=request.method)
        t = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            log.exception("unhandled_error")
            response = JSONResponse({"detail": "Internal server error", "request_id": rid}, status_code=500)
        ms = (time.perf_counter() - t) * 1000
        response.headers["X-Request-ID"] = rid
        response.headers["X-Response-Time-ms"] = f"{ms:.1f}"
        if request.url.path.startswith(s.api_prefix):
            log.info("request", status=response.status_code, ms=round(ms, 1))
        return response

    @app.exception_handler(StarletteHTTPException)
    async def http_exc(request: Request, exc: StarletteHTTPException):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def validation_exc(request: Request, exc: RequestValidationError):
        return JSONResponse({"detail": "Validation error", "errors": jsonable(exc.errors())}, status_code=422)

    for r in (health.router, auth.router, auth.users_router, documents.router, search.router, chat.router,
              conversations.router, analytics.router, eval_api.router):
        app.include_router(r, prefix=s.api_prefix)
    app.include_router(health.router)  # /health at root for load balancers

    # Optionally serve the built SPA (single-service deployments)
    dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if dist.exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa(full_path: str):
            f = dist / full_path
            return FileResponse(f if full_path and f.is_file() else dist / "index.html")
    return app


def jsonable(errors):
    from fastapi.encoders import jsonable_encoder
    return jsonable_encoder(errors, custom_encoder={Exception: str})


app = create_app()
