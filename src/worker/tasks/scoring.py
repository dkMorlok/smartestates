"""Scoring pipeline tasks: segments + market stats, regression, per-listing scores.

Two Celery tasks live here:

* :func:`materialize_segments_and_stats` (Week 5a) — rebuilds market_segment
  rows and appends today's per-segment ppm² statistics.
* :func:`score_active_listings` (Week 5b) — fits a per-(city, property_type,
  ownership_type) hedonic regression, evaluates risk flags + confidence +
  composite for every active listing, writes a new ``score`` row per listing,
  and refreshes ``score_latest`` CONCURRENTLY.

Both tasks are idempotent across reruns: segment upserts are
``ON CONFLICT DO NOTHING`` by natural key, and ``score`` rows are PK'd by
``(listing_id, model_version, computed_at)`` so a fresh run never collides
with a previous one.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from celery import shared_task
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DBAPIError

from db.orm import (
    Listing,
    MarketSegment,
    MarketStat,
    Photo,
    Property,
    Score,
    ScoringConfig,
)
from db.session import get_engine, session_scope
from scoring.composite import (
    DEFAULT_REFS,
    ComponentRef,
    CompositeInputs,
    compute_composite,
)
from scoring.confidence import (
    CRITICAL_FIELDS,
    compute_confidence,
    field_completeness,
)
from scoring.hedonic import (
    HedonicFeatures,
    HedonicModel,
    fit_hedonic,
    predict_log_ppm2,
    undervaluation_pct,
)
from scoring.risks import (
    RiskInputs,
    SegmentRefs,
    evaluate_risk_flags,
    risk_score,
)
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


# ---------------------------------------------------------------------------
# Week 5b: per-listing scoring
# ---------------------------------------------------------------------------


_DEFAULT_MODEL_VERSION = "v1"


def _parent_city(district: str | None) -> str | None:
    """Mirror of ``segments._parent_city`` for the hedonic grouping key."""
    if not district:
        return district
    if district.lower().startswith("praha"):
        return "Praha"
    return district


def _bool_feature(listing: Listing, key: str) -> bool | None:
    """Read a typed boolean from ``features_jsonb``; missing → None."""
    feats = listing.features_jsonb or {}
    val = feats.get(key)
    if val is None:
        return None
    return bool(val)


def _hedonic_features(listing: Listing, district: str | None) -> HedonicFeatures:
    return HedonicFeatures(
        size_m2=listing.size_m2,
        floor_current=listing.floor_current,
        floor_total=listing.floor_total,
        has_lift=_bool_feature(listing, "has_lift"),
        has_balcony=_bool_feature(listing, "has_balcony"),
        has_loggia=_bool_feature(listing, "has_loggia"),
        has_terrace=_bool_feature(listing, "has_terrace"),
        has_cellar=_bool_feature(listing, "has_cellar"),
        has_parking=_bool_feature(listing, "has_parking"),
        building_type=listing.building_type,
        disposition=listing.disposition,
        condition=listing.condition,
        year_built=listing.year_built,
        energy_class=listing.energy_class,
        city_district=district,
    )


def _segment_key_from_orm(seg: MarketSegment) -> SegmentKey:
    return SegmentKey(
        city_district=seg.city_district,
        locality=seg.locality,
        property_type=seg.property_type,
        disposition=seg.disposition,
        ownership_type=seg.ownership_type,
        building_type=seg.building_type,
        size_bucket=seg.size_bucket,
        condition_bucket=seg.condition_bucket,
    )


def _listing_critical_completeness(
    listing: Listing,
    district: str | None,
) -> float:
    """Fraction of ``CRITICAL_FIELDS`` populated for this listing."""
    present = 0
    for field in CRITICAL_FIELDS:
        if field == "city_district":
            if district:
                present += 1
            continue
        value = getattr(listing, field, None)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        present += 1
    return field_completeness(present, len(CRITICAL_FIELDS))


def _dec(value: float | None, places: int) -> Decimal | None:
    """Wrap a float for ``Numeric`` columns without going through Decimal(float)."""
    if value is None:
        return None
    if not math.isfinite(value):
        return None
    return Decimal(f"{value:.{places}f}")


def _load_segments_and_stats(
    db: Any,
) -> tuple[dict[SegmentKey, int], dict[SegmentKey, MarketStat]]:
    """All segment ids + their latest market_stat row, keyed by SegmentKey."""
    latest = (
        select(
            MarketStat.segment_id,
            func.max(MarketStat.as_of_date).label("as_of"),
        )
        .group_by(MarketStat.segment_id)
        .subquery()
    )
    stat_rows = db.execute(
        select(MarketSegment, MarketStat)
        .join(MarketStat, MarketSegment.id == MarketStat.segment_id)
        .join(
            latest,
            (MarketStat.segment_id == latest.c.segment_id)
            & (MarketStat.as_of_date == latest.c.as_of),
        )
    ).all()
    stat_by_key: dict[SegmentKey, MarketStat] = {}
    seg_id_by_key: dict[SegmentKey, int] = {}
    for seg, stat in stat_rows:
        key = _segment_key_from_orm(seg)
        stat_by_key[key] = stat
        seg_id_by_key[key] = seg.id

    # Fill in segment ids for segments that have no stat yet.
    for seg in db.execute(select(MarketSegment)).scalars():
        key = _segment_key_from_orm(seg)
        seg_id_by_key.setdefault(key, seg.id)

    return seg_id_by_key, stat_by_key


def _load_scoring_config(
    db: Any,
    model_version: str,
) -> tuple[dict[str, float], dict[str, ComponentRef]] | None:
    config = db.execute(
        select(ScoringConfig).where(ScoringConfig.model_version == model_version)
    ).scalar_one_or_none()
    if config is None:
        return None
    weights_jsonb = config.weights_jsonb or {}
    component_weights: dict[str, float] = {
        k: float(v) for k, v in (weights_jsonb.get("components") or {}).items()
    }
    refs_jsonb = weights_jsonb.get("refs") or {}
    refs: dict[str, ComponentRef] = (
        {
            name: ComponentRef(mean=float(r["mean"]), stddev=float(r["stddev"]))
            for name, r in refs_jsonb.items()
        }
        or DEFAULT_REFS
    )
    return component_weights, refs


def _refresh_score_latest() -> None:
    """``REFRESH MATERIALIZED VIEW CONCURRENTLY score_latest``, with fallback.

    CONCURRENTLY requires the mview to be populated at least once — on the
    very first run we fall back to a plain (blocking) refresh so the unique
    index can index initial rows. Subsequent runs use CONCURRENTLY.
    """
    engine = get_engine()
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        try:
            conn.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY score_latest"))
        except DBAPIError as exc:
            log.warning("scoring.score.refresh_fallback", error=str(exc))
            conn.execute(text("REFRESH MATERIALIZED VIEW score_latest"))


@shared_task(name="scoring.score_active_listings", bind=False)
def score_active_listings(
    city_prefix: str = "Praha",
    model_version: str = _DEFAULT_MODEL_VERSION,
) -> dict[str, Any]:
    """Score every active listing in the given city using the named model_version.

    Pipeline:
      1. Load weights + ref distributions from ``scoring_config``.
      2. Load active recent listings (last 90d) with their property's
         ``city_district``, ``address_precision`` and a per-listing photo count.
      3. Load each segment's most recent ``market_stat`` for risk refs +
         confidence sample-size.
      4. Group listings by (parent_city, property_type, ownership_type) and
         fit one robust hedonic regression per group.
      5. For every listing: predict log ppm² → undervaluation, evaluate risk
         flags + risk_score, compute confidence + composite, write a ``score``
         row.
      6. ``REFRESH MATERIALIZED VIEW CONCURRENTLY score_latest``.

    Returns a stats dict for the Celery result. Idempotent across reruns
    (PK = listing+model_version+computed_at).
    """
    now = datetime.now(tz=UTC)

    with session_scope() as db:
        config = _load_scoring_config(db, model_version)
        if config is None:
            log.error("scoring.score.no_config", model_version=model_version)
            return {"status": "error", "reason": "no_config", "scored": 0}
        component_weights, refs = config

        photo_count_subq = (
            select(Photo.listing_id, func.count(Photo.id).label("photo_count"))
            .group_by(Photo.listing_id)
            .subquery()
        )
        cutoff = now - timedelta(days=_LOOKBACK_DAYS)
        rows = db.execute(
            select(
                Listing,
                Property.city_district,
                Property.address_precision,
                photo_count_subq.c.photo_count,
            )
            .join(Property, Listing.property_id == Property.id, isouter=True)
            .join(
                photo_count_subq,
                Listing.id == photo_count_subq.c.listing_id,
                isouter=True,
            )
            .where(
                Listing.status == "active",
                Listing.last_seen_at >= cutoff,
                Property.city_district.ilike(f"{city_prefix}%"),
            )
        ).all()

        if not rows:
            log.info("scoring.score.no_listings", city_prefix=city_prefix)
            return {"status": "empty", "scored": 0}

        seg_id_by_key, stat_by_key = _load_segments_and_stats(db)

        # Group for hedonic fitting.
        groups: dict[
            tuple[str, str, str],
            list[tuple[Listing, str | None]],
        ] = defaultdict(list)
        for listing, district, _, _ in rows:
            parent = _parent_city(district)
            if parent is None or listing.ownership_type is None:
                continue
            groups[(parent, listing.property_type, listing.ownership_type)].append(
                (listing, district)
            )

        models: dict[tuple[str, str, str], HedonicModel | None] = {}
        for gkey, group_rows in groups.items():
            features: list[HedonicFeatures] = []
            targets: list[float] = []
            for listing, district in group_rows:
                value = ppm2(listing.price, listing.size_m2)
                if value is None or value <= 0:
                    continue
                features.append(_hedonic_features(listing, district))
                targets.append(math.log(value))
            models[gkey] = fit_hedonic(features, targets, group_key=gkey)

        scored = 0
        skipped = 0
        for listing, district, precision, photo_count in rows:
            feat = _hedonic_features(listing, district)

            parent = _parent_city(district)
            listing_gkey: tuple[str, str, str] | None = (
                (parent, listing.property_type, listing.ownership_type)
                if parent and listing.ownership_type
                else None
            )
            model = models.get(listing_gkey) if listing_gkey is not None else None

            actual_ppm2 = ppm2(listing.price, listing.size_m2)
            actual_log = (
                math.log(actual_ppm2)
                if actual_ppm2 is not None and actual_ppm2 > 0
                else None
            )

            predicted_log = (
                predict_log_ppm2(model, feat) if model is not None else None
            )

            uv_pct: float | None = None
            uv_abs: float | None = None
            if predicted_log is not None and actual_log is not None:
                uv_pct = undervaluation_pct(predicted_log, actual_log)
                size_f = float(listing.size_m2) if listing.size_m2 else None
                price_f = float(listing.price) if listing.price else None
                if size_f and price_f:
                    predicted_ppm2 = math.exp(predicted_log)
                    uv_abs = predicted_ppm2 * size_f - price_f

            # Segment refs for risks + confidence.
            seg_key = segment_key_for(
                ListingLike(
                    city_district=district,
                    locality=None,
                    property_type=listing.property_type,
                    disposition=listing.disposition,
                    ownership_type=listing.ownership_type,
                    building_type=listing.building_type,
                    size_m2=listing.size_m2,
                    condition=listing.condition,
                )
            )
            stat = stat_by_key.get(seg_key)
            segment_id = seg_id_by_key.get(seg_key)
            relaxation_level = stat.relaxation_level if stat is not None else MAX_RELAXATION_LEVEL
            sample_size = stat.n_samples if stat is not None else 0
            ppm2_median = (
                float(stat.ppm2_median)
                if stat is not None and stat.ppm2_median is not None
                else None
            )
            ppm2_p25 = (
                float(stat.ppm2_p25)
                if stat is not None and stat.ppm2_p25 is not None
                else None
            )

            risk_inputs = RiskInputs(
                price=listing.price,
                size_m2=listing.size_m2,
                ownership_type=listing.ownership_type,
                building_type=listing.building_type,
                year_built=listing.year_built,
                floor_current=listing.floor_current,
                floor_total=listing.floor_total,
                has_lift=_bool_feature(listing, "has_lift"),
                energy_class=listing.energy_class,
                photo_count=int(photo_count) if photo_count is not None else None,
                description=listing.description,
            )
            seg_refs = SegmentRefs(ppm2_median=ppm2_median, ppm2_p25=ppm2_p25)
            flags = evaluate_risk_flags(risk_inputs, seg_refs)
            risk = risk_score(flags)

            completeness = _listing_critical_completeness(listing, district)
            freshness_days = max(0, (now - listing.first_seen_at).days)
            confidence = compute_confidence(
                sample_size=sample_size,
                relaxation_level=relaxation_level,
                completeness=completeness,
                geocode_precision=precision,
                freshness_days=freshness_days,
            )

            comp_inputs = CompositeInputs(
                undervaluation_pct=uv_pct,
                yield_gross_pct=None,
                yield_confidence=None,
                liquidity_score=None,
                location_score=None,
                risk_score=risk,
            )
            try:
                composite = compute_composite(
                    comp_inputs, component_weights, refs=refs
                )
            except KeyError as exc:
                log.error("scoring.score.bad_weights", missing=str(exc))
                skipped += 1
                continue

            score_row = Score(
                listing_id=listing.id,
                model_version=model_version,
                computed_at=now,
                segment_id=segment_id,
                undervaluation_pct=_dec(uv_pct, 3),
                undervaluation_abs=_dec(uv_abs, 2),
                yield_gross_pct=None,
                yield_confidence=None,
                liquidity_score=None,
                location_score=None,
                risk_score=_dec(risk, 2),
                confidence_score=_dec(confidence, 3),
                composite=_dec(composite, 2),
                components_jsonb={
                    "predicted_log_ppm2": predicted_log,
                    "actual_log_ppm2": actual_log,
                    "sample_size": sample_size,
                    "relaxation_level": relaxation_level,
                    "completeness": completeness,
                    "freshness_days": freshness_days,
                    "hedonic_fit": listing_gkey is not None
                    and models.get(listing_gkey) is not None,
                },
                risk_flags=flags,
            )
            db.add(score_row)
            scored += 1

    # The refresh runs in its own autocommit connection — CONCURRENTLY cannot
    # execute inside a transaction. Score inserts above are already committed
    # by session_scope().
    _refresh_score_latest()

    log.info(
        "scoring.score.done",
        scored=scored,
        skipped=skipped,
        model_version=model_version,
        groups_fitted=sum(1 for m in models.values() if m is not None),
        groups_total=len(models),
    )
    return {
        "status": "ok",
        "scored": scored,
        "skipped": skipped,
        "computed_at": now.isoformat(),
        "model_version": model_version,
        "groups_fitted": sum(1 for m in models.values() if m is not None),
        "groups_total": len(models),
    }
