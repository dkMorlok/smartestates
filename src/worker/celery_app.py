"""Celery application with queue routing and beat schedule."""
from __future__ import annotations

from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_process_init

from shared.config import get_settings
from shared.logging import configure_logging

settings = get_settings()

celery_app = Celery(
    "realitni",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "worker.tasks.ingest",
        "worker.tasks.normalize",
        "worker.tasks.geocode",
        "worker.tasks.dedup",
        "worker.tasks.scoring",
        "worker.tasks.ops",
    ],
)

celery_app.conf.update(
    timezone="Europe/Prague",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_default_queue="default",
    task_routes={
        "ingest.discover": {"queue": "ingest.discover"},
        "ingest.discover_one": {"queue": "ingest.discover"},
        "ingest.fetch": {"queue": "ingest.fetch"},
        "ingest.parse": {"queue": "ingest.parse"},
        "normalize.from_raw": {"queue": "normalize"},
        "geocode.listing": {"queue": "geocode"},
        "dedup.tier1": {"queue": "dedup"},
        "scoring.materialize_segments_and_stats": {"queue": "scoring"},
        "scoring.score_active_listings": {"queue": "scoring"},
        "ops.source_canary": {"queue": "default"},
    },
    task_default_retry_delay=60,
    task_publish_retry=True,
    broker_transport_options={"visibility_timeout": 3600},
    result_expires=86400,
)

celery_app.conf.beat_schedule = {
    "sreality-discover-praha-byty-prodej": {
        "task": "ingest.discover",
        "schedule": crontab(minute=0, hour="*/6"),
        "args": (
            "sreality",
            {"region": 10, "category_main": 1, "category_type": 1},
        ),
        "options": {"queue": "ingest.discover"},
    },
    "sreality-discover-brno-byty-prodej": {
        "task": "ingest.discover",
        # Offset by 30 minutes from Praha so the two discovery sweeps don't
        # contend for the same fetch queue.
        "schedule": crontab(minute=30, hour="*/6"),
        "args": (
            "sreality",
            {
                "region": 14,
                "district": 72,  # Brno-město
                "category_main": 1,
                "category_type": 1,
            },
        ),
        "options": {"queue": "ingest.discover"},
    },
    "sreality-canary": {
        "task": "ops.source_canary",
        "schedule": crontab(minute=0, hour="*"),
        "args": ("sreality",),
    },
    "nightly-segments-stats": {
        "task": "scoring.materialize_segments_and_stats",
        "schedule": crontab(minute=30, hour=3),
        "args": ("Praha",),
        "options": {"queue": "scoring"},
    },
    "nightly-score-active-listings": {
        # 04:00 Europe/Prague per docs/SCORING.md; segment stats finish by 03:55
        # in nightly so this run sees today's market_stat refresh.
        "task": "scoring.score_active_listings",
        "schedule": crontab(minute=0, hour=4),
        "args": ("Praha", "v1"),
        "options": {"queue": "scoring"},
    },
}


@worker_process_init.connect
def _init_logging(**_: object) -> None:
    configure_logging()
