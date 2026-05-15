"""Risk-flag evaluation (docs/SCORING.md §"Risk flags").

Pure functions over a listing's fields plus its segment's market stats.
No DB, no ORM. The UI displays the flag names verbatim — the strings in
``SEVERITY_WEIGHT`` (and returned by :func:`evaluate_risk_flags`) are the
canonical labels.

Deferred to Phase 2:
    * ``flood_zone`` — requires DIBAVOD Q100 floodplain geojson.
    * ``agency_high_churn`` — requires cross-listing stats (median DOM,
      relisting frequency) that we don't compute yet.
    * ``price_dropped_fast`` — needs price-history tracking.

These are intentionally omitted here; once their inputs land, add helpers
alongside the existing ones and register their severities in
``SEVERITY_WEIGHT``.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from decimal import Decimal

# ---------------------------------------------------------------------------
# Pre-compiled regexes
# ---------------------------------------------------------------------------

_LEGAL_ENCUMBRANCE_RE = re.compile(
    r"exekuc|dražb|břemen|předkupní|zástavní|dluh",
    re.IGNORECASE,
)
_REVITALIZ_RE = re.compile(r"revitaliz", re.IGNORECASE)
_DESCRIPTION_KEYWORDS_RE = re.compile(
    r"havarijní stav|na demolici|k demolici|neobyvatel",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RiskInputs:
    """Listing-side fields needed to evaluate the risk flags."""

    price: Decimal | float | None
    size_m2: Decimal | float | None
    ownership_type: str | None
    building_type: str | None
    year_built: int | None
    floor_current: int | None
    floor_total: int | None
    has_lift: bool | None
    energy_class: str | None
    photo_count: int | None
    description: str | None


@dataclass(frozen=True)
class SegmentRefs:
    """Segment-side stats needed to evaluate the risk flags."""

    ppm2_median: float | None
    ppm2_p25: float | None


# ---------------------------------------------------------------------------
# Severity table + score scaling
# ---------------------------------------------------------------------------

SEVERITY_WEIGHT: dict[str, float] = {
    "price_too_low": 3.0,
    "legal_encumbrance": 3.0,
    "druzstevni_mismarked": 3.0,
    "panel_capex_due": 2.0,
    "top_floor_no_lift": 1.0,
    "class_g_energy": 1.0,
    "photo_count_low": 1.0,
    "description_keywords": 2.0,
}

MAX_SUM_FOR_100: float = 8.0
"""Sum of severities that maps to risk_score=100; higher values cap there."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ppm2_or_none(price: Decimal | float | None, size: Decimal | float | None) -> float | None:
    """Defensive ppm² for the flag helpers (skip the flag rather than crash)."""
    if price is None or size is None:
        return None
    try:
        p = float(price)
        s = float(size)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(p) and math.isfinite(s)):
        return None
    if p <= 0 or s <= 0:
        return None
    return p / s


def _price_or_none(price: Decimal | float | None) -> float | None:
    if price is None:
        return None
    try:
        p = float(price)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(p) or p <= 0:
        return None
    return p


# ---------------------------------------------------------------------------
# Per-flag helpers (private; one per flag for easy unit-testing)
# ---------------------------------------------------------------------------


def _flag_price_too_low(listing: RiskInputs, refs: SegmentRefs) -> bool:
    if refs.ppm2_p25 is None or not math.isfinite(refs.ppm2_p25) or refs.ppm2_p25 <= 0:
        return False
    ppm2 = _ppm2_or_none(listing.price, listing.size_m2)
    if ppm2 is None:
        return False
    return ppm2 < 0.6 * refs.ppm2_p25


def _flag_legal_encumbrance(listing: RiskInputs, refs: SegmentRefs) -> bool:
    if not listing.description:
        return False
    return _LEGAL_ENCUMBRANCE_RE.search(listing.description) is not None


def _flag_druzstevni_mismarked(listing: RiskInputs, refs: SegmentRefs) -> bool:
    if listing.ownership_type is not None:
        return False
    if refs.ppm2_median is None:
        # The doc spec compares against segment_median (of price), but we only
        # have ppm2 aggregates available -- fall back to ppm2 * size as a proxy.
        return False
    price = _price_or_none(listing.price)
    size = listing.size_m2
    if price is None or size is None:
        return False
    try:
        size_f = float(size)
    except (TypeError, ValueError):
        return False
    if not math.isfinite(size_f) or size_f <= 0:
        return False
    if not math.isfinite(refs.ppm2_median) or refs.ppm2_median <= 0:
        return False
    segment_median_price = refs.ppm2_median * size_f
    return price < segment_median_price * 0.85


def _flag_panel_capex_due(listing: RiskInputs, refs: SegmentRefs) -> bool:
    if listing.building_type != "panel":
        return False
    if listing.year_built is None:
        return False
    if not (1960 <= listing.year_built <= 1990):
        return False
    return not (listing.description and _REVITALIZ_RE.search(listing.description))


def _flag_top_floor_no_lift(listing: RiskInputs, refs: SegmentRefs) -> bool:
    if listing.floor_current is None or listing.floor_total is None:
        return False
    if listing.has_lift is not False:
        # Trigger only when explicitly known to lack a lift.
        return False
    if listing.floor_current != listing.floor_total:
        return False
    return listing.floor_total > 3


def _flag_class_g_energy(listing: RiskInputs, refs: SegmentRefs) -> bool:
    if not listing.energy_class:
        return False
    return listing.energy_class.upper() in ("F", "G")


def _flag_photo_count_low(listing: RiskInputs, refs: SegmentRefs) -> bool:
    if listing.photo_count is None:
        return False
    return listing.photo_count < 4


def _flag_description_keywords(listing: RiskInputs, refs: SegmentRefs) -> bool:
    if not listing.description:
        return False
    return _DESCRIPTION_KEYWORDS_RE.search(listing.description) is not None


# Fixed evaluation order — matches the order in SEVERITY_WEIGHT and is what
# evaluate_risk_flags returns to the caller.
_FLAG_CHECKS: tuple[tuple[str, object], ...] = (
    ("price_too_low", _flag_price_too_low),
    ("legal_encumbrance", _flag_legal_encumbrance),
    ("druzstevni_mismarked", _flag_druzstevni_mismarked),
    ("panel_capex_due", _flag_panel_capex_due),
    ("top_floor_no_lift", _flag_top_floor_no_lift),
    ("class_g_energy", _flag_class_g_energy),
    ("photo_count_low", _flag_photo_count_low),
    ("description_keywords", _flag_description_keywords),
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def evaluate_risk_flags(listing: RiskInputs, refs: SegmentRefs) -> list[str]:
    """Return triggered flag names, in fixed (definition) order."""
    triggered: list[str] = []
    for name, check in _FLAG_CHECKS:
        if check(listing, refs):  # type: ignore[operator]
            triggered.append(name)
    return triggered


def risk_score(flags: list[str]) -> float:
    """Map triggered flags to a 0..100 score.

    Sums each flag's severity weight and scales linearly so that a total of
    ``MAX_SUM_FOR_100`` (or more) yields 100. Unknown flag names are ignored
    (defensive — keeps callers from crashing on stale labels).
    """
    if not flags:
        return 0.0
    total = sum(SEVERITY_WEIGHT.get(f, 0.0) for f in flags)
    if total <= 0:
        return 0.0
    scaled = (total / MAX_SUM_FOR_100) * 100.0
    return min(scaled, 100.0)
