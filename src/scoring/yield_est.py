"""Yield estimation for a single listing (docs/SCORING.md §Yield estimation).

Gross yield = (monthly_rent_estimate * 12 - annual_hoa) / asking_price.

Rent estimate comes from rental comps in the same segment within the last 90
days (caller pre-aggregates to a trimmed mean of price_per_m²_per_month). If
fewer than `MIN_RENTAL_COMPS` comps survive at the tightest segment, the caller
relaxes the segment hierarchy and re-runs; each relaxation step lowers the
returned confidence. If no comps exist at any relaxation, yield is `None` and
confidence is `0.0` — we never fabricate.

HOA (`SVJ poplatky`) is taken from the listing when stated, otherwise a flat
`DEFAULT_HOA_CZK_PER_M2_PER_MONTH` default is applied and confidence is halved.

Pure functions only — no DB, no ORM. Caller wraps the float results in Decimal
before persisting.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

# ---------------------------------------------------------------------------
# Constants (per docs/SCORING.md §Yield estimation)
# ---------------------------------------------------------------------------

MIN_RENTAL_COMPS: int = 10
DEFAULT_HOA_CZK_PER_M2_PER_MONTH: float = 50.0
HOA_DEFAULT_CONFIDENCE_PENALTY: float = 0.5

# Mirror src/scoring/confidence.py:relaxation_factor — inlined to keep this
# module self-contained (no cross-module coupling inside scoring/).
_RELAXATION_FLOOR: float = 0.6
_RELAXATION_MAX_LEVEL: int = 5

# Sample-size thresholds for the rental-comps confidence factor.
_FULL_CONFIDENCE_N: int = 30

# Clamp gross-yield output to a sane band so a single bad comp can't poison
# the composite score. Lower bound is negative because pathological HOA values
# can drive net rent below zero — we surface that rather than hide it.
_YIELD_MIN_PCT: float = -5.0
_YIELD_MAX_PCT: float = 25.0


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class YieldInputs:
    """Per-listing inputs to the yield estimator.

    `rent_ppm2_per_month_trimmed_mean` is the segment statistic the caller
    already computed (trimmed mean of rental comps in CZK/m²/month). `None`
    means no rental comps were found at any relaxation level.
    """

    asking_price_czk: Decimal | float | None
    size_m2: Decimal | float | None
    hoa_czk_per_month_known: float | None  # None -> apply DEFAULT_HOA
    rent_ppm2_per_month_trimmed_mean: float | None  # None -> no comps
    rental_n_comps: int
    relaxation_level: int


@dataclass(frozen=True)
class YieldResult:
    """Output of `compute_yield`. All fields are float (or None) for now;
    the Celery task wraps them in Decimal before writing to `score_latest`."""

    yield_gross_pct: float | None
    yield_confidence: float
    monthly_rent_estimate_czk: float | None
    annual_hoa_estimate_czk: float | None
    used_default_hoa: bool


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _to_float_or_none(value: Decimal | float | int | None) -> float | None:
    """Coerce Decimal/float/int to float; return None for None or on failure."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _relaxation_factor(level: int) -> float:
    """1.0 at level 0, linearly to 0.6 at level 5. Clamped to [0.6, 1.0].

    Inlined twin of src/scoring/confidence.py:relaxation_factor — kept here
    so this module has no intra-package imports.
    """
    if level <= 0:
        return 1.0
    if level >= _RELAXATION_MAX_LEVEL:
        return _RELAXATION_FLOOR
    span = 1.0 - _RELAXATION_FLOOR
    return 1.0 - span * (level / _RELAXATION_MAX_LEVEL)


def _sample_size_factor(n: int) -> float:
    """1.0 at n>=30, 0.5 at MIN_RENTAL_COMPS<=n<30, 0.0 below MIN_RENTAL_COMPS."""
    if n >= _FULL_CONFIDENCE_N:
        return 1.0
    if n >= MIN_RENTAL_COMPS:
        return 0.5
    return 0.0


def _clamp(value: float, lo: float, hi: float) -> float:
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


_NO_YIELD = YieldResult(
    yield_gross_pct=None,
    yield_confidence=0.0,
    monthly_rent_estimate_czk=None,
    annual_hoa_estimate_czk=None,
    used_default_hoa=False,
)


def compute_yield(inputs: YieldInputs) -> YieldResult:
    """Return gross yield + confidence per docs/SCORING.md §Yield.

    Returns `_NO_YIELD` (all None / confidence 0) when we lack enough comps
    or the listing's asking price / size are unusable. The caller persists
    `yield_gross_pct = NULL` in that case — we do not fabricate a number.
    """
    rent_ppm2 = inputs.rent_ppm2_per_month_trimmed_mean
    price = _to_float_or_none(inputs.asking_price_czk)
    size = _to_float_or_none(inputs.size_m2)

    # Guard: need real rental comps and usable price/size.
    if rent_ppm2 is None:
        return _NO_YIELD
    if inputs.rental_n_comps < MIN_RENTAL_COMPS:
        return _NO_YIELD
    if price is None or price <= 0.0:
        return _NO_YIELD
    if size is None or size <= 0.0:
        return _NO_YIELD

    monthly_rent = float(rent_ppm2) * size

    if inputs.hoa_czk_per_month_known is not None:
        hoa_monthly = float(inputs.hoa_czk_per_month_known)
        used_default_hoa = False
    else:
        hoa_monthly = DEFAULT_HOA_CZK_PER_M2_PER_MONTH * size
        used_default_hoa = True

    annual_hoa = hoa_monthly * 12.0
    net_annual_rent = monthly_rent * 12.0 - annual_hoa
    raw_yield_pct = net_annual_rent / price * 100.0
    yield_pct = _clamp(raw_yield_pct, _YIELD_MIN_PCT, _YIELD_MAX_PCT)

    # Confidence: product of sample-size, relaxation, and HOA-default penalty.
    confidence = (
        1.0
        * _sample_size_factor(inputs.rental_n_comps)
        * _relaxation_factor(inputs.relaxation_level)
    )
    if used_default_hoa:
        confidence *= HOA_DEFAULT_CONFIDENCE_PENALTY

    confidence = round(_clamp(confidence, 0.0, 1.0), 3)

    return YieldResult(
        yield_gross_pct=yield_pct,
        yield_confidence=confidence,
        monthly_rent_estimate_czk=monthly_rent,
        annual_hoa_estimate_czk=annual_hoa,
        used_default_hoa=used_default_hoa,
    )
