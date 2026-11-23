# Architecture — Enterprise Document Intelligence

This document was written before implementation and is kept in sync with the code. It covers the
system architecture, database schema, API surface, folder structure and end-to-end data flow.

## 1. System architecture

```mermaid
flowchart LR
  subgraph Client
    UI[React + Vite SPA<br/>docs · search · chat · eval · analytics]
  end

  subgraph API["FastAPI (uvicorn, async)"]
    AUTH[JWT auth + RBAC]
    RL[Redis rate limiter]
    DOCS[/documents/]
    SEARCH[/search/]
    CHAT[/chat (SSE)/]
    EVAL[/eval + analytics/]
  end

  subgraph Worker["Ingestion worker (arq on Redis)"]
    PARSE[Parsers<br/>PDF · DOCX · TXT · MD]
    CHUNK[Structure-aware chunker]
    EMB[Sentence-Transformers<br/>bge-small-en-v1.5]
  end

  subgraph Retrieval["Retrieval pipeline (configurable)"]
    VEC[Dense search<br/>Qdrant]
    BM25[BM25 keyword index]
    RRF[Reciprocal Rank Fusion]
    RR[Cross-encoder reranker<br/>ms-marco-MiniLM-L-6-v2]
  end

  LLM[LLM provider<br/>OpenAI · OpenAI-compatible · local HF]
  PG[(PostgreSQL<br/>metadata · chunks · conversations · query logs · eval runs)]
  QD[(Qdrant<br/>chunk vectors + payload)]
  RD[(Redis<br/>job queue · answer cache · rate limits · index version)]
  FS[(Object storage<br/>uploaded files)]

  UI -->|REST + SSE| API
  DOCS -->|enqueue job| RD --> Worker
  DOCS --> FS
  Worker --> FS
  PARSE --> CHUNK --> EMB --> QD
  CHUNK --> PG
  SEARCH --> Retrieval
  CHAT --> Retrieval --> LLM
  VEC --> QD
  BM25 --> PG
  VEC --> RRF
  BM25 --> RRF --> RR
  CHAT --> RD
  API --> PG
```

**Design principles**

* **One retrieval code path.** The API, the evaluation harness and the tests all call the same
  `RetrievalPipeline` with a `RetrievalConfig`. Evaluation therefore measures the code that ships.
* **Every stage is switchable.** Dense / BM25 / hybrid, RRF `k`, candidate depth, reranker on/off,
  metadata filters on/off and top-k are fields of `RetrievalConfig`, accepted by the `/search` and
  `/chat` endpoints so approaches can be compared live from the UI.
* **Grounded generation.** The LLM only sees numbered context passages, must cite `[n]`, and must
  answer with the fixed abstention sentence when evidence is missing. A retrieval-score gate also
  abstains *before* calling the LLM when no passage clears the relevance threshold.
* **Provider-agnostic LLM.** `openai` (default when a key is present), `openai_compatible`
  (Ollama, vLLM, LM Studio, TGI) and `local` (Hugging Face transformers on CPU/GPU).
* **Stateless API processes.** All shared state is in Postgres, Qdrant and Redis, so the API scales
  horizontally. The in-process BM25 index is rebuilt lazily when the Redis `index_version` changes.

## 2. Database schema (PostgreSQL)

| Table | Key columns | Notes |
|---|---|---|
| `users` | `id uuid PK`, `email unique`, `hashed_password`, `full_name`, `role` (`admin`/`editor`/`viewer`), `is_active`, `created_at` | First registered user becomes admin. |
| `documents` | `id uuid PK`, `filename`, `title`, `content_hash` (sha256, indexed), `mime_type`, `size_bytes`, `category`, `author`, `doc_date date`, `tags jsonb`, `version int`, `status` (`pending`/`processing`/`ready`/`failed`), `error`, `page_count`, `chunk_count`, `storage_path`, `uploaded_by FK users`, `created_at`, `updated_at` | Unique on `filename` (logical document). Same hash ⇒ duplicate rejected; same filename + new hash ⇒ new `version`, chunks replaced. |
| `chunks` | `id uuid PK` (= Qdrant point id), `document_id FK cascade`, `chunk_index`, `text`, `section_path`, `page_start`, `page_end`, `chunk_type` (`text`/`table`), `token_count`, `created_at` | Index on `(document_id, chunk_index)`. Source of truth for BM25 and citations. |
| `ingestion_jobs` | `id uuid PK`, `document_id FK`, `status`, `attempts`, `error`, `created_at`, `started_at`, `finished_at` | Async processing audit trail. |
| `conversations` | `id uuid PK`, `user_id FK`, `title`, `created_at`, `updated_at` | |
| `messages` | `id uuid PK`, `conversation_id FK cascade`, `role` (`user`/`assistant`), `content`, `citations jsonb`, `created_at` | Index on `(conversation_id, created_at)`. |
| `query_logs` | `id uuid PK`, `user_id`, `conversation_id`, `endpoint`, `query`, `standalone_query`, `retrieval_config jsonb`, `filters jsonb`, `retrieved jsonb` (chunk ids, scores, ranks), `response`, `retrieval_ms`, `generation_ms`, `total_ms`, `prompt_tokens`, `completion_tokens`, `cost_usd`, `model`, `cache_hit`, `abstained`, `error`, `created_at` | Index on `created_at`. Powers performance analytics. |
| `eval_runs` | `id uuid PK`, `name`, `config jsonb`, `metrics jsonb`, `per_question jsonb`, `environment jsonb`, `created_at` | Imported from `eval/results/*.json`; never edited by hand. |

Migrations are managed by Alembic (`backend/alembic/versions`).

## 3. API endpoints (prefix `/api/v1`)

| Method & path | Role | Purpose |
|---|---|---|
| `GET /health`, `GET /health/ready` | public | Liveness; readiness checks Postgres, Redis, Qdrant. |
| `POST /auth/register`, `POST /auth/login`, `GET /auth/me` | public / user | JWT bearer tokens (OAuth2 password flow compatible). |
| `GET /users`, `PATCH /users/{id}` | admin | User and role management. |
| `POST /documents` (multipart, many files) | editor | Batch upload with metadata; returns per-file `created` / `updated` / `duplicate`. |
| `GET /documents` | viewer | List with filters (`category`, `author`, `status`, `q`) and pagination. |
| `GET /documents/{id}` | viewer | Metadata + ingestion status. |
| `GET /documents/{id}/chunks` | viewer | Parsed chunks with pages and sections (document preview). |
| `GET /documents/{id}/file` | viewer | Original file (inline preview / download). |
| `POST /documents/{id}/reindex`, `DELETE /documents/{id}` | editor | Re-process / delete (removes vectors and chunks). |
| `GET /documents/facets` | viewer | Distinct categories, authors, date range for filter UI. |
| `POST /search` | viewer | Retrieval only, with `RetrievalConfig` + filters; returns ranked chunks with per-stage scores and timings. |
| `POST /chat` | viewer | Non-streaming grounded answer with citations. |
| `POST /chat/stream` | viewer | Same, streamed via Server-Sent Events (`sources`, `token`, `done`, `error`). |
| `GET /conversations`, `GET /conversations/{id}`, `DELETE /conversations/{id}` | viewer (own) | Conversation history. |
| `GET /analytics/summary`, `GET /analytics/queries` | admin | Latency percentiles, cache hit rate, tokens, cost, errors, recent query log. |
| `GET /eval/runs`, `GET /eval/runs/{id}`, `POST /eval/import` | viewer / admin | Evaluation results for the dashboard. |

Interactive OpenAPI docs are served at `/docs` (Swagger) and `/redoc`; see `docs/API.md`.

## 4. Folder structure

```
backend/
  app/
    main.py               FastAPI app factory, middleware, routers
    config.py             pydantic-settings (all env vars)
    logging.py            structlog JSON logging + request ids
    deps.py               DI: db session, current user, role guards
    api/                  routers: auth, users, documents, search, chat, conversations, analytics, eval, health
    core/                 security (JWT, bcrypt), rate_limit, cache, errors
    db/                   SQLAlchemy models, async session
    ingestion/            parsers/, chunking.py, pipeline.py, worker.py
    retrieval/            embeddings.py, vector_store.py, bm25.py, fusion.py, reranker.py, pipeline.py, filters.py
    generation/           llm.py (providers), prompts.py, answer.py (citations, abstention), rewrite.py
    services/             documents, conversations, query logging
  alembic/                migrations
  eval/                   corpus builder, dataset, metrics, runner, report generator
  tests/                  unit + integration tests
frontend/                 React + Vite + TypeScript SPA
docs/                     architecture, API, deployment, benchmark report, screenshots
docker-compose.yml, render.yaml
```

## 5. Data flow

**Ingestion.** `POST /documents` streams each file to storage while hashing it. If the sha256 matches
an existing document it is reported as a duplicate and nothing is re-processed. If the filename
exists with a different hash the document becomes a new version. A `documents` row
(`status=pending`) and an `ingestion_jobs` row are written and the job is enqueued on Redis (arq). The
worker parses the file into a list of *blocks* (heading, paragraph, list, table) each tagged with page
number and heading path; PDFs use PyMuPDF font-size statistics to detect headings and its table
finder to extract tables, DOCX uses paragraph styles and native tables, Markdown uses the markdown-it
token stream, TXT uses heuristic heading detection. The structure-aware chunker packs consecutive
blocks within a section up to a token budget, never splits a table or sentence, prefixes each chunk
with its heading path, and adds sentence-level overlap. Chunks are embedded in batches, upserted to
Qdrant with filterable payload (`document_id`, `filename`, `category`, `author`, `doc_date`, pages),
written to Postgres, the old version's chunks are removed, the Redis `index_version` is bumped, and
the document flips to `ready`.

**Query.** `POST /chat/stream` → rate-limit check → if the conversation has history, the question is
rewritten into a standalone query → Redis cache lookup on (standalone query, filters, config,
corpus version) → retrieval: dense top-N from Qdrant and BM25 top-N, each honouring metadata filters,
fused with RRF, re-scored by the cross-encoder, cut to top-k → relevance gate (abstain if the best
reranker score is below threshold) → prompt with numbered passages → streamed tokens over SSE →
citations parsed from `[n]` markers and mapped to document/page/quote → assistant message saved,
query log written (retrieved chunk ids and scores, timings, token usage, cost, errors) → answer cached.

**Evaluation.** `python -m eval.run` builds the benchmark corpus, ingests it with each chunking
strategy into isolated Qdrant collections using the production ingestion code, runs every
question through each of the five retrieval configurations, computes retrieval metrics against gold
evidence, generates answers with the configured LLM, scores correctness, faithfulness (NLI
entailment against retrieved context), citation accuracy, latency and cost, and writes JSON + Markdown
reports and charts. The dashboard reads the same JSON.
