# Deployment guide

## 1. Docker Compose (single host)

```bash
cp backend/.env.example backend/.env      # set JWT_SECRET, and OPENAI_API_KEY if you use OpenAI
docker compose up --build -d
```

* UI: <http://localhost:8080> (nginx serves the SPA and proxies `/api` to the API with SSE buffering off)
* API + Swagger: <http://localhost:8000/docs>
* Services: `postgres`, `redis`, `qdrant`, `api` (runs `alembic upgrade head` on start), `worker` (arq
  ingestion worker), `frontend`. Data lives in named volumes.
* Register the first account in the UI — it becomes the admin.
* Scale ingestion with `docker compose up -d --scale worker=3`. The API is stateless and can be scaled
  behind a load balancer the same way (shared state is in Postgres, Redis and Qdrant).

Open-source LLM instead of OpenAI:

```bash
docker compose --profile ollama up -d
docker compose exec ollama ollama pull llama3.1:8b
LLM_PROVIDER=openai_compatible OPENAI_BASE_URL=http://ollama:11434/v1 OPENAI_MODEL=llama3.1:8b docker compose up -d api
```

Or run a Hugging Face model in-process with `LLM_PROVIDER=local LOCAL_LLM_MODEL=Qwen/Qwen2.5-1.5B-Instruct`
(needs ~7 GB RAM on CPU; use `DEVICE=cuda` on a GPU host).

## 2. Render

The repository contains a Blueprint, [`render.yaml`](../render.yaml), that provisions:

| Render resource | Name | Purpose |
|---|---|---|
| Web service (Docker, `backend/`) | `edi-api` | FastAPI; runs migrations on start; health check `/health`; 10 GB disk for uploads |
| Static site (`frontend/`) | `edi-frontend` | React build, SPA rewrite |
| Private service (image `qdrant/qdrant:v1.12.4`) | `edi-qdrant` | Vector database with a 10 GB persistent disk |
| PostgreSQL | `edi-postgres` | Metadata, chunks, conversations, query logs, eval runs |
| Key Value (Redis) | `edi-redis` | Cache, rate limits, index version, job queue |

### Steps

1. Push the repository to GitHub (or GitLab).
2. In the Render dashboard choose **New → Blueprint**, select the repository, and confirm the resources
   from `render.yaml`.
3. When prompted, set `OPENAI_API_KEY` for `edi-api` (it is declared with `sync: false`, so it is never
   stored in the repo). `JWT_SECRET` is generated automatically.
4. If you rename services, update `CORS_ORIGINS` on `edi-api` and `VITE_API_URL` on `edi-frontend` to the
   real `onrender.com` URLs (or your custom domains), then redeploy the frontend.
5. Open the frontend URL and register the first (admin) account.
6. Optional: seed the benchmark corpus and import results — upload `backend/eval/corpus/*` from the
   Documents page, then press **Import** on the Evaluation page.

### Notes and sizing

* **Memory.** The embedding model and the cross-encoder are loaded in every API process (~1 GB RSS with
  CPU torch), so use at least the *Standard* (2 GB) plan and `WEB_CONCURRENCY=1`; scale out with more
  instances rather than more workers per instance. The free plan (512 MB) is too small for local models.
* **Ingestion mode.** Render disks attach to a single service, so the Blueprint uses `INGEST_MODE=inline`
  (ingestion runs as background tasks inside the API instance that received the upload). To run a separate
  Background Worker (`arq app.ingestion.worker.WorkerSettings`) on Render, store uploads in shared object
  storage (S3/R2) instead of the local disk — the worker and API then only share Postgres, Redis and Qdrant.
* **LLM.** With `OPENAI_API_KEY` set the provider resolves to OpenAI automatically. For a free option use Google Gemini: `LLM_PROVIDER=openai_compatible`, `OPENAI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/`, `OPENAI_MODEL=gemini-2.5-flash`, `LLM_REASONING_EFFORT=none`, your Gemini key in `OPENAI_API_KEY`, and `PRICE_INPUT_PER_M=0` / `PRICE_OUTPUT_PER_M=0`. Running the local
  Hugging Face LLM on Render needs a high-memory plan; an external OpenAI-compatible endpoint (vLLM, Ollama
  on a GPU box, or a hosted provider) is usually the better choice: set `LLM_PROVIDER=openai_compatible`,
  `OPENAI_BASE_URL` and `OPENAI_MODEL`.
* **Qdrant Cloud** can replace the private service: set `QDRANT_URL` and `QDRANT_API_KEY` and delete the
  `edi-qdrant` service and the `QDRANT_HOST` variable.
* **Migrations** run on every API start (`alembic upgrade head`), which is idempotent.
* **Health checks.** `/health` for liveness; `/api/v1/health/ready` reports Postgres, Redis and Qdrant.

## 3. Production checklist

* `ENVIRONMENT=production` — the API refuses to start unless `JWT_SECRET` is ≥ 32 characters.
* Set `ALLOW_REGISTRATION=false` after creating accounts, and manage roles on the Users page.
* Restrict `CORS_ORIGINS` to your frontend origin(s).
* Put the API behind TLS (Render does this automatically).
* Tune `RATE_LIMIT_PER_MINUTE`, `RATE_LIMIT_CHAT_PER_MINUTE`, `CACHE_TTL_SECONDS`, `MAX_UPLOAD_MB`.
* Set `PRICE_INPUT_PER_M` / `PRICE_OUTPUT_PER_M` to your model's prices so cost analytics are right.
* Logs are JSON on stdout (one line per request and per query, with request ids) — ship them to your log
  platform. The `query_logs` table is the durable audit trail.
* Back up Postgres and the Qdrant volume. The Qdrant collection can be rebuilt from the stored files with
  the re-index action; Postgres holds the source of truth for documents and chunks.
