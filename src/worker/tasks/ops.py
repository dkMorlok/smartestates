"""Operational tasks: canaries, health checks, housekeeping."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from celery import shared_task
from sqlalchemy import select

from db.orm import Source
from db.session import session_scope
from scraper.base import get_source
from shared.logging import get_logger

log = get_logger("worker.ops")


@shared_task(name="ops.source_canary", bind=False)
def source_canary(source_slug: str) -> dict[str, Any]:
    """Probe a source's liveness. Updates source.health and last_ok_at."""
    source = get_source(source_slug)
    result = source.health_check()
    now = datetime.now(tz=UTC)

    with session_scope() as db:
        row = db.execute(select(Source).where(Source.slug == source_slug)).scalar_one_or_none()
        if row is None:
            return {"status": "no_such_source"}
        row.health = "ok" if result.ok else "degraded"
        if result.ok:
            row.last_ok_at = now

    log.info(
        "ops.canary",
        source=source_slug,
        ok=result.ok,
        detail=result.detail[:200],
    )
    return {"source": source_slug, "ok": result.ok, "detail": result.detail}


@shared_task(name="ops.canary_all", bind=False)
def canary_all() -> dict[str, Any]:
    from scraper.base import all_source_slugs

    results = {}
    for slug in all_source_slugs():
        results[slug] = source_canary(slug)
    return results
