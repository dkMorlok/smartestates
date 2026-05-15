"""Hedonic regression of log(price_per_m²) per (city, property_type, ownership_type).

Pure functions over plain dataclasses — no DB, no ORM. The materialise task
loads the rows and passes typed ``HedonicFeatures`` plus the per-listing
``log(ppm²)`` targets in here.

See ``docs/SCORING.md`` §"Hedonic regression" for the model spec. The fit
uses a robust Huber M-estimator (``statsmodels.RLM`` with ``HuberT``) so a
handful of mispriced listings can't drag the whole segment.

Per-listing **undervaluation** is the log-space residual converted to
percent and clamped to ±50, matching the spec.

Week 5b MVP intentionally omits the GTFS-derived
``distance_to_metro_m`` / ``distance_to_tram_m`` / ``distance_to_train_m``
features — those will land once the transit dataset is wired through.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal

import numpy as np
import statsmodels.api as sm

MIN_FIT_SAMPLES: int = 50
"""Minimum usable rows required before we'll attempt a fit."""

UNDERVALUATION_CLAMP_PCT: float = 50.0
"""Symmetric clamp on the percent-space undervaluation output."""


# ---------------------------------------------------------------------------
# Input / output dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HedonicFeatures:
    """One listing's typed attributes, as consumed by the hedonic model.

    All fields are nullable — the model handles missing data via imputation
    or by treating the row as 'reference level' for that categorical.
    """

    size_m2: Decimal | float | int | None
    floor_current: int | None
    floor_total: int | None
    has_lift: bool | None
    has_balcony: bool | None
    has_loggia: bool | None
    has_terrace: bool | None
    has_cellar: bool | None
    has_parking: bool | None
    building_type: str | None
    disposition: str | None
    condition: str | None
    year_built: int | None
    energy_class: str | None
    city_district: str | None


@dataclass(frozen=True)
class HedonicModel:
    """A fitted hedonic model for a single (city, property_type, ownership) group.

    Contains everything ``predict_log_ppm2`` needs to re-encode a fresh
    listing into the same feature space. Frozen because we cache fitted
    models per group during a scoring run.
    """

    intercept: float
    coef_by_column: dict[str, float]
    columns: tuple[str, ...]
    n_samples: int
    n_features: int
    residual_stddev: float
    group_key: tuple[str, str, str]  # (city, property_type, ownership_type)


# ---------------------------------------------------------------------------
# Feature engineering
# ---------------------------------------------------------------------------


# Categorical feature names → attribute on HedonicFeatures.
_CATEGORICAL_FIELDS: tuple[str, ...] = (
    "building_type",
    "disposition",
    "condition",
    "energy_class",
    "city_district",
    "year_built_bucket",
)

# Binary feature columns (1.0/0.0; None → 0.0).
_BINARY_COLUMNS: tuple[str, ...] = (
    "has_balcony",
    "has_loggia",
    "has_terrace",
    "has_cellar",
    "has_parking",
    "top_floor_walkup",
)

# Continuous columns kept in the design matrix.
_CONTINUOUS_COLUMNS: tuple[str, ...] = (
    "log_size_m2",
    "floor_current",
)


def _to_float(value: Decimal | float | int | None) -> float | None:
    """Defensive ``float()`` cast that tolerates Decimal / int / None."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _year_built_bucket(year: int | None) -> str:
    """Coarse era bucket — matches ``docs/SCORING.md`` hedonic spec."""
    if year is None:
        return "unknown"
    if year < 1948:
        return "<1948"
    if year < 1990:
        return "1948-1989"
    if year < 2010:
        return "1990-2009"
    return "2010+"


def _top_floor_walkup(f: HedonicFeatures) -> float:
    """1.0 iff the listing is the top floor of a walk-up taller than 3 floors."""
    if f.floor_current is None or f.floor_total is None:
        return 0.0
    if f.has_lift is not False:
        return 0.0
    if f.floor_total <= 3:
        return 0.0
    if f.floor_current != f.floor_total:
        return 0.0
    return 1.0


def _categorical_value(f: HedonicFeatures, name: str) -> str | None:
    """Resolve a categorical feature's value, including derived buckets."""
    if name == "year_built_bucket":
        return _year_built_bucket(f.year_built)
    raw = getattr(f, name, None)
    if raw is None:
        return None
    return str(raw)


def _binary_value(f: HedonicFeatures, name: str) -> float:
    """Map a binary attribute (or derived flag) to 1.0/0.0."""
    if name == "top_floor_walkup":
        return _top_floor_walkup(f)
    raw = getattr(f, name, None)
    return 1.0 if raw else 0.0


def _collect_levels(features: list[HedonicFeatures]) -> dict[str, list[str]]:
    """For each categorical field, the sorted distinct levels seen in training.

    The first level (alphabetically) is dropped at one-hot time to avoid the
    dummy-variable trap.
    """
    levels: dict[str, set[str]] = {name: set() for name in _CATEGORICAL_FIELDS}
    for f in features:
        for name in _CATEGORICAL_FIELDS:
            val = _categorical_value(f, name)
            if val is None:
                continue
            levels[name].add(val)
    return {name: sorted(vals) for name, vals in levels.items()}


def _kept_levels(levels: dict[str, list[str]]) -> dict[str, list[str]]:
    """Drop the first level per categorical (one-hot reference)."""
    return {name: vals[1:] for name, vals in levels.items() if len(vals) > 1}


def _design_columns(kept_levels: dict[str, list[str]]) -> tuple[str, ...]:
    """The full ordered column list for the design matrix (no intercept)."""
    cols: list[str] = []
    cols.extend(_CONTINUOUS_COLUMNS)
    cols.extend(_BINARY_COLUMNS)
    for name in _CATEGORICAL_FIELDS:
        for level in kept_levels.get(name, []):
            cols.append(f"cat__{name}__{level}")
    return tuple(cols)


def _build_feature_row(
    f: HedonicFeatures,
    columns: tuple[str, ...],
) -> dict[str, float] | None:
    """Encode one listing as ``column_name -> value``.

    Returns ``None`` when ``size_m2`` is missing/non-positive — we can't
    take ``log(size_m2)`` then, so the row is unusable both for fit and
    predict. Unknown categorical levels silently map to 0 on every dummy,
    which is the same encoding as the dropped reference level.
    """
    size = _to_float(f.size_m2)
    if size is None or size <= 0:
        return None

    row: dict[str, float] = dict.fromkeys(columns, 0.0)
    row["log_size_m2"] = math.log(size)
    row["floor_current"] = float(f.floor_current) if f.floor_current is not None else 0.0

    for name in _BINARY_COLUMNS:
        if name in row:
            row[name] = _binary_value(f, name)

    for name in _CATEGORICAL_FIELDS:
        val = _categorical_value(f, name)
        if val is None:
            continue
        key = f"cat__{name}__{val}"
        if key in row:
            row[key] = 1.0

    return row


# ---------------------------------------------------------------------------
# Fit / predict
# ---------------------------------------------------------------------------


def fit_hedonic(
    features: list[HedonicFeatures],
    log_ppm2: list[float],
    *,
    group_key: tuple[str, str, str],
) -> HedonicModel | None:
    """Fit a robust (Huber) hedonic regression for one segment group.

    Returns ``None`` when there are fewer than :data:`MIN_FIT_SAMPLES`
    usable rows, when the design matrix would be degenerate, or when the
    underlying solver raises. Rows with missing ``size_m2`` or non-finite
    ``log_ppm2`` are dropped before counting.
    """
    if len(features) != len(log_ppm2):
        return None

    levels = _collect_levels(features)
    kept = _kept_levels(levels)
    columns = _design_columns(kept)

    usable_rows: list[list[float]] = []
    usable_y: list[float] = []
    for f, y in zip(features, log_ppm2, strict=False):
        if y is None or not math.isfinite(y):
            continue
        row = _build_feature_row(f, columns)
        if row is None:
            continue
        usable_rows.append([row[c] for c in columns])
        usable_y.append(float(y))

    if len(usable_rows) < MIN_FIT_SAMPLES:
        return None

    try:
        X = np.asarray(usable_rows, dtype=float)
        y_arr = np.asarray(usable_y, dtype=float)
        X_with_const = sm.add_constant(X, has_constant="add")
        model = sm.RLM(y_arr, X_with_const, M=sm.robust.norms.HuberT())
        results = model.fit()
        params = np.asarray(results.params, dtype=float)
        if params.shape[0] != len(columns) + 1:
            return None
        intercept = float(params[0])
        coef_by_column = {col: float(params[i + 1]) for i, col in enumerate(columns)}
        residual_stddev = float(np.std(np.asarray(results.resid, dtype=float)))
    except Exception:
        # Solver may raise broadly (singular matrix, convergence, etc.); treat as no-fit.
        return None

    return HedonicModel(
        intercept=intercept,
        coef_by_column=coef_by_column,
        columns=columns,
        n_samples=len(usable_rows),
        n_features=len(columns),
        residual_stddev=residual_stddev,
        group_key=group_key,
    )


def predict_log_ppm2(model: HedonicModel, f: HedonicFeatures) -> float | None:
    """Predict ``log(price_per_m²)`` for one listing using a fitted model.

    Returns ``None`` if ``size_m2`` is missing — the rest of the features
    can be sparse and still produce a prediction (unknown categorical
    levels just collapse to the reference level).
    """
    row = _build_feature_row(f, model.columns)
    if row is None:
        return None
    total = model.intercept
    for col, coef in model.coef_by_column.items():
        total += coef * row.get(col, 0.0)
    return total


def undervaluation_pct(predicted_log_ppm2: float, actual_log_ppm2: float) -> float:
    """Convert a log-space residual to a clamped percent figure.

    Working in log space gives a symmetric, scale-free residual; we then
    map back through ``exp`` to get a true percent ratio
    (``(predicted / actual) - 1``), and clamp to ±50% per the spec to keep
    extreme outliers from dominating downstream composites.
    """
    diff = predicted_log_ppm2 - actual_log_ppm2
    pct = (math.exp(diff) - 1.0) * 100.0
    if pct > UNDERVALUATION_CLAMP_PCT:
        return UNDERVALUATION_CLAMP_PCT
    if pct < -UNDERVALUATION_CLAMP_PCT:
        return -UNDERVALUATION_CLAMP_PCT
    return pct
