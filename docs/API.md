# API reference

Base URL: `http://localhost:8000/api/v1`. Interactive documentation is served by the running API at
`/docs` (Swagger UI) and `/redoc`; the machine-readable spec is committed at [`openapi.json`](openapi.json).

All endpoints except `/health*`, `/auth/register` and `/auth/login` need a bearer token:
`Authorization: Bearer <access_token>`. Roles are hierarchical: `viewer` < `editor` < `admin`.

Example payloads below show the response *shape*; their values are illustrative, not measurements
(measured numbers are in [`benchmarks/`](benchmarks/)).

Errors use one shape: `{"detail": "..."}` (validation errors add `errors`). Every response carries
`X-Request-ID` and `X-Response-Time-ms` headers. Rate-limited endpoints return `429` with `Retry-After`.

## Authentication

| Method | Path | Role | Notes |
|---|---|---|---|
| POST | `/auth/register` | public | `{email, password (≥8), full_name?}` → token. The first user becomes `admin`; later users are `viewer`. Disable with `ALLOW_REGISTRATION=false`. |
| POST | `/auth/login` | public | OAuth2 password form: `username`, `password` → `{access_token, token_type, user}` |
| GET | `/auth/me` | any | Current user |
| GET | `/users` | admin | List users |
| PATCH | `/users/{id}` | admin | `{role?, is_active?}` (admins cannot demote/disable themselves) |

```bash
TOKEN=$(curl -s -X POST localhost:8000/api/v1/auth/login \
  -d username=admin@example.com -d password='admin-pass-123' | jq -r .access_token)
```

## Documents

| Method | Path | Role | Notes |
|---|---|---|---|
| POST | `/documents` | editor | Multipart batch upload. Fields: `files` (repeat), optional `category`, `author`, `doc_date` (YYYY-MM-DD), `tags` (comma-separated) applied to all files, and `metadata` — JSON keyed by filename for per-file values. Returns `202` with one result per file: `created`, `updated` (same filename, new content → version + 1, chunks replaced), `duplicate` (identical sha256 already ingested) or `rejected` (type/size/empty). Processing is asynchronous. |
| GET | `/documents` | viewer | `q`, `category`, `author`, `status`, `page`, `page_size` |
| GET | `/documents/facets` | viewer | Distinct categories, authors, filenames and date range (for filter UIs) |
| GET | `/documents/{id}` | viewer | Metadata and status (`pending` → `processing` → `ready` / `failed` with `error`) |
| PATCH | `/documents/{id}` | editor | Update `title`, `category`, `author`, `doc_date`, `tags`; re-indexes so vector payloads stay in sync |
| GET | `/documents/{id}/chunks` | viewer | Parsed chunks with `section_path`, `page_start/page_end`, `chunk_type` (`text`/`table`) |
| GET | `/documents/{id}/file` | viewer | Original file, served inline |
| POST | `/documents/{id}/reindex` | editor | Re-run ingestion |
| DELETE | `/documents/{id}` | editor | Removes the file, chunks and vectors |

```bash
curl -X POST localhost:8000/api/v1/documents -H "Authorization: Bearer $TOKEN" \
  -F files=@policy_2024.pdf -F files=@handbook.docx -F category=HR -F doc_date=2024-03-15 \
  -F 'metadata={"handbook.docx": {"author": "Elena Rodriguez"}}'
```

## Retrieval configuration and filters

`/search`, `/chat` and `/chat/stream` accept the same two objects, so different retrieval strategies can be
compared on live data:

```json
{
  "config": {"mode": "hybrid", "top_k": 5, "candidates": 30, "rrf_k": 60,
             "rerank": true, "rerank_depth": 30, "use_filters": true},
  "filters": {"filenames": [], "document_ids": [], "categories": ["Finance"], "authors": [],
              "date_from": "2024-01-01", "date_to": "2024-12-31"}
}
```

`mode`: `dense` (Qdrant), `bm25` (keyword) or `hybrid` (both, fused with Reciprocal Rank Fusion).
`candidates` is the depth fetched from each retriever; `rerank_depth` how many fused candidates the
cross-encoder re-scores. Filters are applied inside both retrievers (Qdrant payload filter and BM25 mask).

## Search

`POST /search` `{query, config?, filters?}` → ranked chunks with per-stage scores and timings:

```json
{"query": "hotel cap tier 1", "results": [{"chunk_id": "…", "document_id": "…", "filename": "travel_expense_policy_2024.pdf",
  "title": "Travel and Expense Policy 2024", "section": "… > 2.2 Hotels", "page_start": 2, "page_end": 2,
  "chunk_type": "table", "text": "| City tier | …", "score": 7.91,
  "scores": {"dense": 0.83, "bm25": 9.12, "rrf": 0.0328, "rerank": 7.91}, "ranks": {"dense": 1, "bm25": 1, "final": 1}}],
 "timings_ms": {"dense_ms": 21.4, "bm25_ms": 1.2, "rerank_ms": 310.5, "total_ms": 334.0}, "config": {…}, "filters": {…}}
```

## Chat

`POST /chat` `{message, conversation_id?, config?, filters?, use_cache?}` → grounded answer:

```json
{"conversation_id": "…", "message_id": "…",
 "answer": "Tier 1 cities are capped at 320 USD per night [1].",
 "citations": [{"index": 1, "chunk_id": "…", "document_id": "…", "filename": "travel_expense_policy_2024.pdf",
                "page_start": 2, "page_end": 2, "section": "…", "quote": "| Tier 1 | New York, … | 320 |"}],
 "quotes": [{"quote": "…", "verified": true}], "abstained": false, "sources": [ … retrieved chunks … ],
 "standalone_query": "…", "usage": {"prompt_tokens": 812, "completion_tokens": 24, "cost_usd": 0.00013},
 "timings_ms": {"retrieval_ms": 340.2, "generation_ms": 1210.5, "total_ms": 1551.0}, "model": "gpt-4o-mini", "cache_hit": false}
```

* With a `conversation_id`, the last turns are used to rewrite the question into a standalone query
  before retrieval (`standalone_query`) and are passed to the LLM as history.
* `abstained: true` means the documents did not contain sufficient evidence — either the reranker's best
  score was below `ABSTAIN_THRESHOLD` (the LLM is not called) or the model answered with the fixed refusal.
* `quotes[].verified` is `false` if the model put text in quotation marks that does not occur in the sources.
* Identical requests (same message, recent history, config, filters and corpus version) are served from the
  Redis cache (`cache_hit: true`); any ingestion invalidates the cache.

### Streaming (Server-Sent Events)

`POST /chat/stream` takes the same body and returns `text/event-stream`. Each event's `data` is JSON with
a `type` equal to the event name:

| Event | Payload |
|---|---|
| `conversation` | `{conversation_id}` |
| `rewrite` | `{standalone_query}` (follow-ups only) |
| `sources` | `{chunks, timings_ms}` — sent before generation starts |
| `token` | `{text}` — repeated |
| `done` | full result as in `/chat` |
| `error` | `{detail}` |

```bash
curl -N -X POST localhost:8000/api/v1/chat/stream -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"message": "What does error HX-503 mean?"}'
```

Browsers cannot send POST bodies or headers with `EventSource`; the frontend uses `fetch` with a stream
reader (`frontend/src/api.ts → streamChat`).

## Conversations

`GET /conversations`, `GET /conversations/{id}` (messages with citations), `DELETE /conversations/{id}`.
Users only see their own conversations.

## Analytics (admin)

* `GET /analytics/summary?days=7` — query count by endpoint; latency avg/p50/p95 and retrieval/generation
  averages; prompt/completion tokens; cost; cache-hit rate; abstention rate; errors; document/chunk counts;
  per-day series.
* `GET /analytics/queries?limit=50&errors_only=false` — the query log: query, standalone query, retrieved
  chunks with scores and ranks, timings, tokens, cost, model, cache hit, abstention and error.

## Evaluation

* `GET /eval/runs`, `GET /eval/runs/{id}` — benchmark runs with summary metrics and per-question results.
* `POST /eval/import` (admin) — import `backend/eval/results/*.json` produced by `python -m eval.run`.

## Health

* `GET /health` (also at the root) — liveness.
* `GET /health/ready` — checks Postgres, Redis and Qdrant; `503` with per-dependency errors when degraded.
