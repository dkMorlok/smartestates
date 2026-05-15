"""Composite-score blender: combine component scores into a 0..100 score.

Pure functions only — no DB, no ORM. The Celery task loads weights from the
`scoring_config` table and the per-component reference distributions, then
calls `compute_composite` with the listing's component values.

The blend formula (see docs/SCORING.md §Composite):

    composite = sigmoid(
        +w_undervaluation * z(undervaluation_pct)
        +w_yield          * z(yield_gross_pct) * yield_confidence
        +w_liquidity      * z(liquidity_score)
        +w_location       * z(location_score)
        -w_risk           * z(risk_score)            # note: sign baked into the weight
    ) * 100

Weights are passed in by the caller (never hardcoded here) so that
`scoring_config.model_version` can A/B different blends without a code change.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class CompositeInputs:
    """Per-listing component scores fed into the blender.

    Any field may be None — a None component contributes exactly 0 to the
    pre-sigmoid sum (it is not z-scored and does not penalise the listing).
    """

    undervaluation_pct: float | None
    yield_gross_pct: float | None
    yield_confidence: float | None
    liquidity_score: float | None
    location_score: float | None
    risk_score: float | None


@dataclass(frozen=True)
class ComponentRef:
    """Reference distribution (mean, stddev) for a single component."""

    mean: float
    stddev: float


COMPONENT_NAMES: tuple[str, ...] = (
    "undervaluation_pct",
    "yield_gross_pct",
    "liquidity_score",
    "location_score",
    "risk_score",
)


DEFAULT_REFS: dict[str, ComponentRef] = {
    "undervaluation_pct": ComponentRef(mean=0.0, stddev=15.0),
    "yield_gross_pct": ComponentRef(mean=4.5, stddev=1.5),
    "liquidity_score": ComponentRef(mean=50.0, stddev=20.0),
    "location_score": ComponentRef(mean=50.0, stddev=20.0),
    "risk_score": ComponentRef(mean=10.0, stddev=15.0),
}


def z_score(value: float, ref: ComponentRef) -> float:
    """Return (value - ref.mean) / ref.stddev. Returns 0.0 if stddev <= 0."""
    if ref.stddev <= 0:
        return 0.0
    return (value - ref.mean) / ref.stddev


def _sigmoid(x: float) -> float:
    """Numerically stable logistic sigmoid 1 / (1 + exp(-x))."""
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def compute_composite(
    inputs: CompositeInputs,
    weights: dict[str, float],
    *,
    refs: dict[str, ComponentRef] | None = None,
) -> float:
    """Blend components into a 0..100 score using passed-in weights.

    `weights` must contain every name in `COMPONENT_NAMES`; a missing key
    raises KeyError (fail loud — we never silently default a weight, because
    the whole point of `scoring_config.model_version` is to make weights
    explicit and auditable).

    `refs` defaults to `DEFAULT_REFS` but can be overridden to A/B reference
    distributions independently of weights.

    Component handling:
      * A None component contributes 0 to the pre-sigmoid sum (it is NOT
        z-scored — we don't want a missing field to look like an extreme value).
      * `yield_gross_pct`'s contribution is multiplied by `yield_confidence`
        (which is treated as 0.0 when None — a yield with no confidence
        doesn't move the score).

    Returns a float in [0.0, 100.0].
    """
    used_refs = refs if refs is not None else DEFAULT_REFS

    # Fail loud on missing weights — see docstring.
    w = {name: float(weights[name]) for name in COMPONENT_NAMES}

    total = 0.0

    if inputs.undervaluation_pct is not None:
        total += w["undervaluation_pct"] * z_score(
            float(inputs.undervaluation_pct), used_refs["undervaluation_pct"]
        )

    if inputs.yield_gross_pct is not None:
        yc = 0.0 if inputs.yield_confidence is None else float(inputs.yield_confidence)
        total += (
            w["yield_gross_pct"]
            * z_score(float(inputs.yield_gross_pct), used_refs["yield_gross_pct"])
            * yc
        )

    if inputs.liquidity_score is not None:
        total += w["liquidity_score"] * z_score(
            float(inputs.liquidity_score), used_refs["liquidity_score"]
        )

    if inputs.location_score is not None:
        total += w["location_score"] * z_score(
            float(inputs.location_score), used_refs["location_score"]
        )

    if inputs.risk_score is not None:
        # The caller supplies the sign in the weight (risk weight is negative
        # in the canonical config) so risk is treated identically to the
        # positive components above.
        total += w["risk_score"] * z_score(
            float(inputs.risk_score), used_refs["risk_score"]
        )

    return _sigmoid(total) * 100.0
