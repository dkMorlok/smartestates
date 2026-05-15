"""Location-score layer: transit, amenities, green, quiet → 0..100 subscores.

Pure functions only — no DB, no ORM, no HTTP. The caller is expected to have
already computed distances (in metres) and POI counts from GTFS / OSM data
sources and pass them in as `LocationInputs`. The actual GTFS / OSM
integration lives in a separate ingestion stage.

Subscore design (see docs/SCORING.md §Location):

* **Transit** — distance to nearest metro / tram / train. Linear from
  `TRANSIT_BEST_M` (=100) down to `TRANSIT_WORST_M` (=0); clamped.
* **Amenities** — sum of POI counts within 800m across the canonical
  `AMENITY_KEYS` categories. Linear up to `AMENITY_FULL_COUNT` (=100); clamped.
* **Green** — distance to nearest park ≥ 1 ha. Linear from `PARK_BEST_M` (=100)
  down to `PARK_WORST_M` (=0); clamped.
* **Quiet** — *inverse* distance to nearest primary / secondary road. Far away
  (≥ `ROAD_QUIET_BEST_M`) → 100, close (≤ `ROAD_QUIET_WORST_M`) → 0; clamped.
* **Schools** — ČŠI inspection data; Phase 2, not implemented here.

Any signal can be `None` (no data available); its subscore is then `None`
and it is simply omitted from the composite mean. If every subscore is
`None`, the composite is `None` — we do not fabricate a score from nothing.
"""
from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Tuning constants — exported so tests and downstream code can refer to them.
# ---------------------------------------------------------------------------

TRANSIT_BEST_M: float = 300.0    # ≤300m to nearest stop = 100
TRANSIT_WORST_M: float = 2000.0  # ≥2000m = 0

PARK_BEST_M: float = 300.0       # ≤300m to nearest ≥1ha park = 100
PARK_WORST_M: float = 1500.0     # ≥1500m = 0

ROAD_QUIET_BEST_M: float = 200.0  # ≥200m from major road = quiet=100
ROAD_QUIET_WORST_M: float = 20.0  # ≤20m = quiet=0

AMENITY_KEYS: tuple[str, ...] = (
    "grocery",
    "cafe",
    "restaurant",
    "pharmacy",
    "school",
)
AMENITY_FULL_COUNT: int = 20  # 20+ recognised amenities within 800m = 100


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LocationInputs:
    """Pre-computed location signals for one listing.

    `None` means "no data" (e.g. GTFS coverage gap, listing outside a city
    with POI coverage). The subscore layer treats missing inputs by
    returning a `None` subscore — never a zero — so that a data-coverage
    hole does not silently penalise the listing.
    """

    # Transit — metres to nearest stop of each modality.
    distance_to_metro_m: float | None
    distance_to_tram_m: float | None
    distance_to_train_m: float | None
    # Amenities — count of POIs within 800m, by category.
    amenity_counts: dict[str, int] | None
    # Green — metres to nearest park ≥ 1 ha.
    distance_to_park_m: float | None
    # Quiet — metres to nearest primary/secondary road.
    distance_to_major_road_m: float | None


@dataclass(frozen=True)
class LocationBreakdown:
    """Per-subscore detail for transparency in `score.components_jsonb`."""

    transit: float | None
    amenities: float | None
    green: float | None
    quiet: float | None
    composite: float | None  # mean of available subscores; None if all missing


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _linear_descending(distance_m: float, best_m: float, worst_m: float) -> float:
    """Map distance → 0..100, where best_m=100 and worst_m=0. Clamped.

    `best_m < worst_m` is assumed (closer is better). For `quiet`, swap the
    arguments — see `_linear_ascending`.
    """
    if distance_m <= best_m:
        return 100.0
    if distance_m >= worst_m:
        return 0.0
    span = worst_m - best_m
    return 100.0 * (1.0 - (distance_m - best_m) / span)


def _linear_ascending(distance_m: float, worst_m: float, best_m: float) -> float:
    """Map distance → 0..100, where worst_m=0 and best_m=100. Clamped.

    Used for `quiet`: farther from a major road is better. `worst_m < best_m`.
    """
    if distance_m <= worst_m:
        return 0.0
    if distance_m >= best_m:
        return 100.0
    span = best_m - worst_m
    return 100.0 * (distance_m - worst_m) / span


# ---------------------------------------------------------------------------
# Subscores
# ---------------------------------------------------------------------------


def transit_subscore(inputs: LocationInputs) -> float | None:
    """Best (smallest) of metro/tram/train distance → 0..100.

    Considers only modalities with non-None distances. Returns `None` if
    every modality is missing (no GTFS coverage at all).
    """
    candidates = [
        d
        for d in (
            inputs.distance_to_metro_m,
            inputs.distance_to_tram_m,
            inputs.distance_to_train_m,
        )
        if d is not None
    ]
    if not candidates:
        return None
    best = float(min(candidates))
    return _linear_descending(best, TRANSIT_BEST_M, TRANSIT_WORST_M)


def amenities_subscore(counts: dict[str, int] | None) -> float | None:
    """Sum of recognised AMENITY_KEYS counts → 0..100.

    Unknown keys are ignored (forward-compatibility: if OSM adds a category
    we don't yet recognise, it should not change the score). Returns `None`
    if the counts dict itself is None (no POI data); an empty dict is a
    legitimate zero.
    """
    if counts is None:
        return None
    total = sum(int(counts.get(k, 0)) for k in AMENITY_KEYS)
    score = total / AMENITY_FULL_COUNT * 100.0
    return min(100.0, score)


def green_subscore(distance_to_park_m: float | None) -> float | None:
    """Distance to nearest park (≥1ha) → 0..100. Linear, clamped."""
    if distance_to_park_m is None:
        return None
    return _linear_descending(float(distance_to_park_m), PARK_BEST_M, PARK_WORST_M)


def quiet_subscore(distance_to_major_road_m: float | None) -> float | None:
    """Distance to nearest major road → 0..100 (inverse: farther = quieter).

    Linear, clamped. Returns `None` if no major-road distance is available.
    """
    if distance_to_major_road_m is None:
        return None
    return _linear_ascending(
        float(distance_to_major_road_m), ROAD_QUIET_WORST_M, ROAD_QUIET_BEST_M
    )


# ---------------------------------------------------------------------------
# Composite
# ---------------------------------------------------------------------------


def compute_location(inputs: LocationInputs) -> LocationBreakdown:
    """Compute all four subscores plus their equal-weight mean composite.

    The composite is the arithmetic mean of the non-None subscores, so a
    missing data source (e.g. no GTFS coverage) does not drag the score
    toward zero — it is simply excluded. `composite` is `None` if and only
    if every subscore is `None`.
    """
    transit = transit_subscore(inputs)
    amenities = amenities_subscore(inputs.amenity_counts)
    green = green_subscore(inputs.distance_to_park_m)
    quiet = quiet_subscore(inputs.distance_to_major_road_m)

    available = [s for s in (transit, amenities, green, quiet) if s is not None]
    composite = sum(available) / len(available) if available else None

    return LocationBreakdown(
        transit=transit,
        amenities=amenities,
        green=green,
        quiet=quiet,
        composite=composite,
    )
