# API image. Build from the repo root:  docker build -f infra/api.Dockerfile -t pla-api .
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/apps/api \
    DATABASE_URL=sqlite:///data/demo.db

WORKDIR /app

# Dependencies first so code changes do not reinstall them.
COPY apps/api/requirements.txt apps/api/requirements.txt
RUN pip install -r apps/api/requirements.txt

# Code plus the committed docs/contract used by the chat RAG fallback corpus.
COPY apps/api apps/api
COPY contract contract
COPY docs docs

# Non-root user; data/ is a bind mount (see docker-compose.yml) holding demo.db, rag/ and logs.
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /app/data \
    && chown -R app:app /app/data
USER app

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)" || exit 1

# Build a synthetic DB on first start when none is mounted, then serve.
CMD ["sh", "-c", "[ -f data/demo.db ] || python -m core.etl.build_demo_db --synthetic; exec uvicorn app.main:app --app-dir apps/api --host 0.0.0.0 --port 8000"]
