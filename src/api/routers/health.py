"""Liveness and readiness endpoints."""
from __future__ import annotations

import redis
from fastapi import APIRouter, status
from sqlalchemy import text

from db.session import get_engine
from shared.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/healthz", status_code=status.HTTP_200_OK)
def healthz() -> dict[str, str]:
    """Liveness probe. Process is alive."""
    return {"status": "ok"}


@router.get("/readyz")
def readyz() -> dict[str, dict[str, str]]:
    """Readiness probe. External deps reachable."""
    checks: dict[str, dict[str, str]] = {}
    settings = get_settings()

    # DB
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["postgres"] = {"status": "ok"}
    except Exception as e:
        checks["postgres"] = {"status": "error", "detail": str(e)[:200]}

    # Redis
    try:
        r = redis.from_url(settings.redis_url)
        r.ping()
        checks["redis"] = {"status": "ok"}
    except Exception as e:
        checks["redis"] = {"status": "error", "detail": str(e)[:200]}

    return checks
