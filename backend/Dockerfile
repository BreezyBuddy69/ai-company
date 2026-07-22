FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# libpq is needed at runtime by psycopg[binary] on some slim base images;
# build-essential kept out on purpose to keep the image small — psycopg's
# binary wheel and fastembed's onnxruntime wheel are both pure prebuilt.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
    && rm -rf /var/lib/apt/lists/*

# NOTE: build context is the ai-company/ repo root (see docker-compose.yml),
# not backend/, so this Dockerfile can pull in the shared agents/skills/registry.
COPY backend/requirements.txt .
RUN pip install -r requirements.txt

COPY backend/app ./app
COPY agents /agents
COPY skills /skills
COPY model_registry.yaml /model_registry.yaml

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/health', timeout=3).raise_for_status()" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
