FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy project files BEFORE pip install. setuptools needs src/ to exist
# to discover the packages declared by [tool.setuptools.packages.find].
COPY pyproject.toml README.md ./
COPY src ./src
COPY tests ./tests
COPY migrations ./migrations
COPY alembic.ini ./alembic.ini

# Install project + dev deps (dev deps are tiny and needed for `make test`,
# `make lint`, `make typecheck` running inside the container).
RUN pip install --upgrade pip && pip install -e ".[dev]"

ENV PYTHONPATH=/app/src

# ---- api target ----
FROM base AS api
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/healthz || exit 1
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ---- worker target ----
FROM base AS worker
CMD ["celery", "-A", "worker.celery_app", "worker", "--loglevel=INFO"]
