"""Scoring pipeline tasks: segments + market stats, regression, per-listing scores.

Week 5 scope is the segment + stats half (this commit); hedonic regression
and per-listing scoring land in 5b. The segment build is idempotent — each
nightly run upserts `market_segment` rows and adds one `market_stat` row
per (segment, as_of_date).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from celery import shared_task
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from db.orm import Listing, MarketSegment, MarketStat, Property
from db.session import session_scope
from scoring.segments import (
    MAX_RELAXATION_LEVEL,
    MIN_SAMPLES,
    ListingLike,
    SegmentKey,
    relax,
    segment_key_for,
)
from scoring.stats import PpmStats, compute_ppm2_stats, ppm2
from shared.logging import get_logger

log = get_logger("worker.scoring")

# Only listings observed in the last 90 days feed the stats — older asking
# prices are stale (see docs/SCORING.md "Market stats").
_LOOKBACK_DAYS = 90


def _listing_like(listing: Listing, city_district: str | None) -> ListingLike:
    return ListingLike(
        city_district=city_district,
        locality=None,
        property_type=listing.property_type,
        disposition=listing.disposition,
        ownership_type=listing.ownership_type,
        building_type=listing.building_type,
        size_m2=listing.size_m2,
        condition=listing.condition,
    )


def _load_active_listings(db: Any, city_prefix: str) -> list[tuple[Listing, str | None]]:
    """Active listings + their property city_district, filtered to recent ones."""
    cutoff = datetime.now(tz=UTC) - timedelta(days=_LOOKBACK_DAYS)
    rows = db.execute(
        select(Listing, Property.city_district)
        .join(Property, Listing.property_id == Property.id, isouter=True)
        .where(
            Listing.status == "active",
            Listing.last_seen_at >= cutoff,
            Property.city_district.ilike(f"{city_prefix}%"),
        )
    ).all()
    return [(listing, district) for listing, district in rows]


def _resolve_segment(
    base_key: SegmentKey,
    groups: dict[SegmentKey, list[float]],
) -> tuple[int, PpmStats] | None:
    """Walk the relaxation hierarchy until the segment has enough comps."""
    for level in range(MAX_RELAXATION_LEVEL + 1):
        relaxed = relax(base_key, level)
        if relaxed is None:
            return None
        pooled: list[float] = []
        for other_key, values in groups.items():
            if relax(other_key, level) == relaxed:
                pooled.extend(values)
        stats = compute_ppm2_stats(pooled)
        if stats is not None and stats.is_usable(MIN_SAMPLES):
            return level, stats
    return None


def _upsert_segment(db: Any, key: SegmentKey) -> int:
    """Upsert market_segment by its natural key and return its id."""
    stmt = (
        pg_insert(MarketSegment)
        .values(**key.as_dict())
        .on_conflict_do_nothing(constraint="uq_market_segment_key")
        .returning(MarketSegment.id)
    )
    inserted = db.execute(stmt).scalar()
    if inserted is not None:
        return int(inserted)
    # Conflict → fetch the existing row.
    cond = [
        getattr(MarketSegment, column).is_(value)
        if value is None
        else getattr(MarketSegment, column) == value
        for column, value in key.as_dict().items()
    ]
    existing = db.execute(select(MarketSegment.id).where(*cond)).scalar_one()
    return int(existing)


def _upsert_stat(
    db: Any,
    *,
    segment_id: int,
    as_of: date,
    stats: PpmStats,
    relaxation_level: int,
) -> None:
    stmt = pg_insert(MarketStat).values(
        segment_id=segment_id,
        as_of_date=as_of,
        n_samples=stats.n_samples,
        ppm2_median=Decimal(f"{stats.median:.2f}"),
        ppm2_trimmed_mean=Decimal(f"{stats.trimmed_mean:.2f}"),
        ppm2_p25=Decimal(f"{stats.p25:.2f}"),
        ppm2_p75=Decimal(f"{stats.p75:.2f}"),
        ppm2_stddev=Decimal(f"{stats.stddev:.2f}"),
        relaxation_level=relaxation_level,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["segment_id", "as_of_date"],
        set_={
            "n_samples": stmt.excluded.n_samples,
            "ppm2_median": stmt.excluded.ppm2_median,
            "ppm2_trimmed_mean": stmt.excluded.ppm2_trimmed_mean,
            "ppm2_p25": stmt.excluded.ppm2_p25,
            "ppm2_p75": stmt.excluded.ppm2_p75,
            "ppm2_stddev": stmt.excluded.ppm2_stddev,
            "relaxation_level": stmt.excluded.relaxation_level,
        },
    )
    db.execute(stmt)


@shared_task(name="scoring.materialize_segments_and_stats", bind=False)
def materialize_segments_and_stats(city_prefix: str = "Praha") -> dict[str, Any]:
    """Rebuild market_segment + insert today's market_stat for the given city.

    `city_prefix` is matched against `property.city_district` with ILIKE — so
    'Praha' picks up 'Praha 1' through 'Praha 22'.
    """
    today = datetime.now(tz=UTC).date()
    with session_scope() as db:
        rows = _load_active_listings(db, city_prefix)
        if not rows:
            log.info("scoring.materialize.no_listings", city_prefix=city_prefix)
            return {"status": "empty", "segments": 0, "stats": 0}

        # Group ppm² values by base segment key.
        groups: dict[SegmentKey, list[float]] = defaultdict(list)
        for listing, district in rows:
            key = segment_key_for(_listing_like(listing, district))
            value = ppm2(listing.price, listing.size_m2)
            if value is not None:
                groups[key].append(value)

        segments_written = 0
        stats_written = 0
        unresolved = 0

        for base_key in groups:
            resolved = _resolve_segment(base_key, groups)
            segment_id = _upsert_segment(db, base_key)
            segments_written += 1
            if resolved is None:
                unresolved += 1
                continue
            level, stats = resolved
            _upsert_stat(
                db,
                segment_id=segment_id,
                as_of=today,
                stats=stats,
                relaxation_level=level,
            )
            stats_written += 1

    log.info(
        "scoring.materialize.done",
        city_prefix=city_prefix,
        segments=segments_written,
        stats=stats_written,
        unresolved=unresolved,
    )
    return {
        "status": "ok",
        "as_of": today.isoformat(),
        "segments": segments_written,
        "stats": stats_written,
        "unresolved": unresolved,
    }
