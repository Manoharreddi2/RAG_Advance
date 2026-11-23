# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    HF_HOME=/opt/hf TOKENIZERS_PARALLELISM=false
WORKDIR /app

# CPU-only PyTorch keeps the image ~1.5 GB smaller than the CUDA build
RUN pip install torch==2.15.0 --index-url https://download.pytorch.org/whl/cpu
COPY requirements.txt .
RUN pip install -r requirements.txt

# Bake the embedding + reranker models into the image (no download on cold start).
ARG PRELOAD_MODELS=1
ARG EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
ARG RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2
RUN if [ "$PRELOAD_MODELS" = "1" ]; then python -c "from sentence_transformers import SentenceTransformer, CrossEncoder; \
SentenceTransformer('$EMBEDDING_MODEL'); CrossEncoder('$RERANKER_MODEL')"; fi

COPY . .
RUN useradd -m -u 10001 app && mkdir -p /data/uploads && chown -R app /app /data /opt/hf
USER app
ENV STORAGE_DIR=/data/uploads PORT=8000
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
  CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://localhost:{os.environ.get(\"PORT\",\"8000\")}/health', timeout=4)" || exit 1
# Apply migrations, then serve. Workers: 2 per container (models are loaded per worker process).
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers ${WEB_CONCURRENCY:-2} --proxy-headers --forwarded-allow-ips='*'"]
