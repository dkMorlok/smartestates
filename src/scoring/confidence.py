"""Multiplicative confidence layer for the score (docs/SCORING.md §Confidence).

Each scored listing carries a confidence in [0, 1] that's the product of five
independent factors — segment sample size, relaxation level, field
completeness, geocode precision and listing freshness. The API hides scores
with `confidence < 0.3` from public lists; this module just computes the
number, the filtering happens at the call site.

Pure functions over scalars — no DB, no ORM. The materialise task feeds in
values it has already loaded.
"""
from __future__ import annotations

import math

# ---------------------------------------------------------------------------
# Critical fields whose presence drives `field_completeness`
# ---------------------------------------------------------------------------

CRITICAL_FIELDS: tuple[str, ...] = (
    "price",
    "size_m2",
    "disposition",
    "ownership_type",
    "condition",
    "building_type",
    "floor_current",
    "year_built",
    "city_district",
)


# ---------------------------------------------------------------------------
# Individual factors
# ---------------------------------------------------------------------------

_SIGMOID_K = 0.1
_SIGMOID_MIDPOINT = 30


def sample_size_factor(n_samples: int) -> float:
    """Sigmoid around N=30. f(0)=0.05, f(30)=0.5, f(60)=0.95, f(inf)->1.0."""
    n = 0 if n_samples <= 0 else int(n_samples)
    # 1 / (1 + exp(-k * (n - 30)))
    return 1.0 / (1.0 + math.exp(-_SIGMOID_K * (n - _SIGMOID_MIDPOINT)))


_RELAXATION_FLOOR = 0.6
_RELAXATION_MAX_LEVEL = 5


def relaxation_factor(level: int) -> float:
    """1.0 at level 0, linearly to 0.6 at level 5. Clamped to [0.6, 1.0]."""
    if level <= 0:
        return 1.0
    if level >= _RELAXATION_MAX_LEVEL:
        return _RELAXATION_FLOOR
    span = 1.0 - _RELAXATION_FLOOR
    return 1.0 - span * (level / _RELAXATION_MAX_LEVEL)


def field_completeness(present: int, total_critical: int) -> float:
    """Fraction present / total. Bounded [0, 1]. total_critical==0 -> 1.0."""
    if total_critical <= 0:
        return 1.0
    if present <= 0:
        return 0.0
    ratio = present / total_critical
    if ratio >= 1.0:
        return 1.0
    return ratio


_GEOCODE_PRECISION_TABLE: dict[str, float] = {
    "rooftop": 1.0,
    "parcel": 0.95,
    "street": 0.85,
    "source_gps": 0.6,
    "locality": 0.5,
}


def geocode_precision_factor(precision: str | None) -> float:
    """rooftop=1.0, parcel=0.95, street=0.85, source_gps=0.6, locality=0.5, None=0.5."""
    if precision is None:
        return 0.5
    return _GEOCODE_PRECISION_TABLE.get(precision, 0.5)


_FRESHNESS_FRESH_DAYS = 30
_FRESHNESS_STALE_DAYS = 180
_FRESHNESS_FLOOR = 0.5


def listing_freshness_factor(days_since_first_seen: int | float | None) -> float:
    """1.0 for <=30d, linearly to 0.5 at 180d, 0.5 floor afterward. None->0.5."""
    if days_since_first_seen is None:
        return 0.5
    try:
        days = float(days_since_first_seen)
    except (TypeError, ValueError):
        return 0.5
    if days < 0:
        days = 0.0
    if days <= _FRESHNESS_FRESH_DAYS:
        return 1.0
    if days >= _FRESHNESS_STALE_DAYS:
        return _FRESHNESS_FLOOR
    span_days = _FRESHNESS_STALE_DAYS - _FRESHNESS_FRESH_DAYS
    span_factor = 1.0 - _FRESHNESS_FLOOR
    return 1.0 - span_factor * ((days - _FRESHNESS_FRESH_DAYS) / span_days)


# ---------------------------------------------------------------------------
# Composite
# ---------------------------------------------------------------------------


def compute_confidence(
    *,
    sample_size: int,
    relaxation_level: int,
    completeness: float,
    geocode_precision: str | None,
    freshness_days: int | float | None,
) -> float:
    """Product of all five factors, clamped [0, 1]. Rounded to 3 dp."""
    completeness_clamped = max(0.0, min(1.0, float(completeness)))
    product = (
        sample_size_factor(sample_size)
        * relaxation_factor(relaxation_level)
        * completeness_clamped
        * geocode_precision_factor(geocode_precision)
        * listing_freshness_factor(freshness_days)
    )
    if product < 0.0:
        product = 0.0
    elif product > 1.0:
        product = 1.0
    return round(product, 3)
