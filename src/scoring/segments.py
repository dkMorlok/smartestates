"""Segment definition + relaxation hierarchy (docs/SCORING.md).

Segments group listings that should be priced comparably — same district,
disposition, ownership, building type, size and condition bracket. Stats
and hedonic models are scoped per segment.

When a segment is too thin to be reliable (n < `MIN_SAMPLES`) we relax it
along a documented hierarchy, recording the relaxation level so confidence
can be discounted.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal

# ---------------------------------------------------------------------------
# Size + condition buckets
# ---------------------------------------------------------------------------

# Inclusive lower bound, exclusive upper, label.
_SIZE_BUCKETS: tuple[tuple[float, float, str], ...] = (
    (0.0, 35.0, "<35"),
    (35.0, 50.0, "35-50"),
    (50.0, 70.0, "50-70"),
    (70.0, 90.0, "70-90"),
    (90.0, 120.0, "90-120"),
    (120.0, 160.0, "120-160"),
    (160.0, float("inf"), ">160"),
)

SIZE_BUCKET_LABELS: tuple[str, ...] = tuple(b[2] for b in _SIZE_BUCKETS)
UNKNOWN_BUCKET = "unknown"


def size_bucket(size_m2: Decimal | float | int | None) -> str:
    """Map a flat's area to one of the canonical size buckets."""
    if size_m2 is None:
        return UNKNOWN_BUCKET
    try:
        value = float(size_m2)
    except (TypeError, ValueError):
        return UNKNOWN_BUCKET
    if value <= 0:
        return UNKNOWN_BUCKET
    for low, high, label in _SIZE_BUCKETS:
        if low <= value < high:
            return label
    return _SIZE_BUCKETS[-1][2]  # >160 catch-all


# Condition codes from shared.enums.Condition.
_CONDITION_TO_BUCKET: dict[str, str] = {
    "novostavba": "new",
    "velmi_dobry": "very_good",
    "po_rekonstrukci": "very_good",
    "dobry": "good",
    "pred_rekonstrukci": "needs_work",
    "v_rekonstrukci": "needs_work",
    "spatny": "ruin",
    "projekt": "new",
}

CONDITION_BUCKET_LABELS: tuple[str, ...] = (
    "new",
    "very_good",
    "good",
    "needs_work",
    "before_reconstruction",
    "ruin",
)


def condition_bucket(condition: str | None) -> str:
    """Collapse the raw condition value into the coarser segmentation bucket."""
    if not condition:
        return UNKNOWN_BUCKET
    return _CONDITION_TO_BUCKET.get(condition, UNKNOWN_BUCKET)


# ---------------------------------------------------------------------------
# Segment key + relaxation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SegmentKey:
    """A market_segment row's natural key (matches the table's UNIQUE)."""

    city_district: str | None
    locality: str | None
    property_type: str
    disposition: str | None
    ownership_type: str | None
    building_type: str | None
    size_bucket: str
    condition_bucket: str | None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "city_district": self.city_district,
            "locality": self.locality,
            "property_type": self.property_type,
            "disposition": self.disposition,
            "ownership_type": self.ownership_type,
            "building_type": self.building_type,
            "size_bucket": self.size_bucket,
            "condition_bucket": self.condition_bucket,
        }


@dataclass(frozen=True)
class ListingLike:
    """The fields segment_key_for needs. A duck-typed adapter at the call site."""

    city_district: str | None
    locality: str | None
    property_type: str
    disposition: str | None
    ownership_type: str | None
    building_type: str | None
    size_m2: Decimal | float | int | None
    condition: str | None


def segment_key_for(listing: ListingLike) -> SegmentKey:
    """Build the segment key for one listing."""
    return SegmentKey(
        city_district=listing.city_district,
        locality=None,  # MVP segments at city-district granularity, not finer.
        property_type=listing.property_type,
        disposition=listing.disposition,
        ownership_type=listing.ownership_type,
        building_type=listing.building_type,
        size_bucket=size_bucket(listing.size_m2),
        condition_bucket=condition_bucket(listing.condition),
    )


# The fixed relaxation hierarchy from SCORING.md. Level 0 is the exact key;
# each higher level drops one constraint to gather more comparable listings.
# Ownership and property_type are NEVER relaxed away (the družstevní trap).
MAX_RELAXATION_LEVEL = 5


def _widen_size_bucket(bucket: str) -> str:
    """Coalesce adjacent base buckets into one of 4 wider buckets.

    Adjacent-pair widening with exact equality is impossible (each base
    bucket would need to belong to two overlapping pairs at once); we use
    fixed coarser ranges instead. This pools the obvious neighbours while
    keeping segments well-defined.
    """
    mapping = {
        "<35": "<50",
        "35-50": "<50",
        "50-70": "50-90",
        "70-90": "50-90",
        "90-120": "90-160",
        "120-160": "90-160",
        ">160": ">160",
    }
    return mapping.get(bucket, UNKNOWN_BUCKET)


def _widen_condition_bucket(bucket: str | None) -> str | None:
    """Drop to a coarser any-non-ruin bucket; for ruin keep as-is."""
    if bucket in (None, UNKNOWN_BUCKET, "ruin"):
        return bucket
    return "any_habitable"


def relax(key: SegmentKey, level: int) -> SegmentKey | None:
    """Return the key after applying `level` relaxation steps; None if past max."""
    if level <= 0:
        return key
    if level > MAX_RELAXATION_LEVEL:
        return None

    relaxed = key
    if level >= 1:
        relaxed = replace(relaxed, size_bucket=_widen_size_bucket(relaxed.size_bucket))
    if level >= 2:
        relaxed = replace(
            relaxed,
            condition_bucket=_widen_condition_bucket(relaxed.condition_bucket),
        )
    if level >= 3:
        relaxed = replace(relaxed, building_type=None)
    if level >= 4:
        # Widen admin area: city_district → its parent city.
        relaxed = replace(relaxed, city_district=_parent_city(relaxed.city_district))
    if level >= 5:
        relaxed = replace(relaxed, disposition=None)
    return relaxed


def _parent_city(district: str | None) -> str | None:
    """`Praha 5` → `Praha`; otherwise keep the value (we don't know its parent)."""
    if not district:
        return district
    if district.lower().startswith("praha"):
        return "Praha"
    return district


MIN_SAMPLES = 30
"""Minimum number of comparable listings before a segment is considered usable."""
