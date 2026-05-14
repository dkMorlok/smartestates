"""Ingestion tasks: discover → fetch → parse.

Each stage is idempotent.

- discover: enumerates listings for a (source, params) combination,
  diffs against current `listing.updated_at`, enqueues fetch for new/changed.
- fetch: retrieves the raw payload, snapshots to S3, writes raw_listing.
  Skips when content_hash matches the previous row (page unchanged).
- parse: validates with pydantic into ParsedListing, stores parsed_jsonb,
  enqueues normalize.from_raw.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from celery import shared_task
from sqlalchemy import select

from db.orm import RawListing, Source, SourceRun
from db.session import session_scope
from scraper.base import ListingRef, RawDocument, get_source
from scraper.http import NonRetryableHTTPError
from scraper.storage import put_raw
from shared.logging import get_logger
from shared.schemas import ParsedListing

log = get_logger("worker.ingest")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _source_id(slug: str) -> int:
    with session_scope() as db:
        sid = db.execute(select(Source.id).where(Source.slug == slug)).scalar_one_or_none()
        if sid is None:
            raise RuntimeError(f"Unknown source slug: {slug}")
        return int(sid)


def _start_run(source_slug: str, stage: str) -> int:
    sid = _source_id(source_slug)
    with session_scope() as db:
        run = SourceRun(
            source_id=sid,
            stage=stage,
            started_at=datetime.now(tz=UTC),
            status="running",
            stats_jsonb={},
        )
        db.add(run)
        db.flush()
        return int(run.id)


def _finish_run(run_id: int, status: str, stats: dict[str, Any], error: str | None = None) -> None:
    with session_scope() as db:
        run = db.get(SourceRun, run_id)
        if run is None:
            return
        run.finished_at = datetime.now(tz=UTC)
        run.status = status
        run.stats_jsonb = stats
        run.error_text = error


# ---------------------------------------------------------------------------
# discover
# ---------------------------------------------------------------------------


@shared_task(
    name="ingest.discover",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
    bind=False,
)
def discover(source_slug: str, params: dict[str, Any]) -> dict[str, Any]:
    """Discover listings and enqueue fetches for new/changed ones."""
    log.info("ingest.discover.start", source=source_slug, params=params)
    run_id = _start_run(source_slug, "discover")
    source = get_source(source_slug)

    discovered = 0
    enqueued = 0
    skipped = 0

    try:
        for ref in source.discover(params):
            discovered += 1
            # Diff against the latest raw_listing we have for this id.
            # If we already have a recent successful row, skip enqueue.
            # (Phase 2 will also diff against listing.updated_at and the
            # hint['last_modification'] timestamp from the search response.)
            with session_scope() as db:
                sid = _source_id(source_slug)
                latest = db.execute(
                    select(RawListing)
                    .where(
                        RawListing.source_id == sid,
                        RawListing.source_listing_id == ref.source_listing_id,
                    )
                    .order_by(RawListing.fetched_at.desc())
                    .limit(1)
                ).scalar_one_or_none()

                # naive: fetch if we have nothing or last fetch was > 24h ago
                if latest is None or (
                    datetime.now(tz=UTC) - latest.fetched_at.replace(tzinfo=UTC)
                ).total_seconds() > 86400:
                    fetch.delay(  # type: ignore[attr-defined]
                        source_slug,
                        ref.source_listing_id,
                        ref.url,
                        ref.hint,
                    )
                    enqueued += 1
                else:
                    skipped += 1
    except Exception as e:
        _finish_run(
            run_id,
            "failed",
            {"discovered": discovered, "enqueued": enqueued, "skipped": skipped},
            str(e)[:1000],
        )
        raise

    stats = {"discovered": discovered, "enqueued": enqueued, "skipped": skipped}
    _finish_run(run_id, "ok", stats)
    log.info("ingest.discover.done", source=source_slug, **stats)
    return stats


# ---------------------------------------------------------------------------
# fetch
# ---------------------------------------------------------------------------


@shared_task(
    name="ingest.fetch",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 5, "countdown": 60},
    dont_autoretry_for=(NonRetryableHTTPError,),
    bind=False,
)
def fetch(
    source_slug: str,
    source_listing_id: str,
    url: str,
    hint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fetch one listing, snapshot raw to S3, write raw_listing."""
    log.info(
        "ingest.fetch.start",
        source=source_slug,
        source_listing_id=source_listing_id,
        url=url,
    )
    source = get_source(source_slug)
    ref = ListingRef(
        source_slug=source_slug,
        source_listing_id=source_listing_id,
        url=url,
        hint=hint or {},
    )

    raw: RawDocument = source.fetch(ref)
    s3_key, content_hash = put_raw(
        source_slug=source_slug,
        source_listing_id=source_listing_id,
        fetched_at=raw.fetched_at,
        content_bytes=raw.content_bytes,
        content_type=raw.content_type,
    )

    sid = _source_id(source_slug)
    skip_parse = False

    with session_scope() as db:
        # Skip parse if content_hash matches the most recent prior row.
        prev = db.execute(
            select(RawListing.content_hash)
            .where(
                RawListing.source_id == sid,
                RawListing.source_listing_id == source_listing_id,
            )
            .order_by(RawListing.fetched_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if prev == content_hash:
            log.info(
                "ingest.fetch.unchanged",
                source_listing_id=source_listing_id,
                hash=content_hash[:12],
            )
            skip_parse = True

        row = RawListing(
            source_id=sid,
            source_listing_id=source_listing_id,
            fetched_at=raw.fetched_at,
            url=raw.url,
            http_status=raw.http_status,
            content_hash=content_hash,
            raw_s3_key=s3_key,
        )
        db.add(row)
        db.flush()
        raw_id = int(row.id)

    if not skip_parse:
        parse.delay(raw_id)  # type: ignore[attr-defined]

    return {
        "raw_listing_id": raw_id,
        "s3_key": s3_key,
        "content_hash": content_hash[:12],
        "enqueued_parse": not skip_parse,
    }


# ---------------------------------------------------------------------------
# parse
# ---------------------------------------------------------------------------


@shared_task(name="ingest.parse", bind=False)
def parse(raw_listing_id: int) -> dict[str, Any]:
    """Parse a raw_listing row into a validated ParsedListing JSON."""
    from scraper.storage import get_raw

    with session_scope() as db:
        row = db.get(RawListing, raw_listing_id)
        if row is None:
            raise RuntimeError(f"raw_listing {raw_listing_id} not found")
        source_slug = db.execute(
            select(Source.slug).where(Source.id == row.source_id)
        ).scalar_one()
        s3_key = row.raw_s3_key
        url = row.url
        source_listing_id = row.source_listing_id
        fetched_at = row.fetched_at

    content_bytes = get_raw(s3_key)
    source = get_source(source_slug)
    raw_doc = RawDocument(
        source_slug=source_slug,
        source_listing_id=source_listing_id,
        url=url,
        http_status=200,
        content_type="application/json",
        content_bytes=content_bytes,
        fetched_at=fetched_at.replace(tzinfo=UTC) if fetched_at.tzinfo is None else fetched_at,
    )

    parse_status = "ok"
    parse_error: str | None = None
    parsed: ParsedListing | None = None
    try:
        parsed = source.parse(raw_doc)
    except Exception as e:
        parse_status = "quarantine"
        parse_error = f"{type(e).__name__}: {e}"[:1000]
        log.warning(
            "ingest.parse.quarantine",
            raw_listing_id=raw_listing_id,
            error=parse_error,
        )

    with session_scope() as db:
        row = db.get(RawListing, raw_listing_id)
        if row is None:
            return {"status": "missing"}
        row.parsed_jsonb = parsed.model_dump(mode="json") if parsed else None
        row.parser_version = parsed.parser_version if parsed else source.parser_version
        row.parse_status = parse_status
        row.parse_error = parse_error

    if parsed is not None:
        # Hand off to normalize stage (defined in normalize.py).
        from worker.tasks.normalize import normalize_from_raw

        normalize_from_raw.delay(raw_listing_id)  # type: ignore[attr-defined]

    return {
        "raw_listing_id": raw_listing_id,
        "status": parse_status,
    }
