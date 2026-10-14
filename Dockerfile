# Finnie backend image for Cloudflare Containers (built by `wrangler deploy`, see wrangler.jsonc).
# State lives outside the container: Turso (TURSO_*) for the DB, Qdrant Cloud (QDRANT_CLUSTER_*) for the KB.
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 FASTEMBED_CACHE_PATH=/app/.fastembed
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Bake the bge-small embedding model into the image so a cold start doesn't download it.
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5')"

COPY config.yaml .
COPY scripts ./scripts
COPY src ./src

EXPOSE 8000
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
