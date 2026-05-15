"""Liquidity score (docs/SCORING.md §Liquidity).

Maps a segment's days-on-market (DOM) and quarterly turnover into a 0..100
liquidity score using the formula::

    liquidity_score = scale(
        -0.6 * segment_dom_median_days
        -0.4 * (1 / segment_turnover_quarterly)
    )

Higher is more liquid. Calibration target (from SCORING.md): DOM under
30 days and turnover > 0.1/quarter → high liquidity.

Pure functions over scalars — no DB, no ORM. The materialise task loads the
segment stats and calls :func:`compute_liquidity_score`; the caller wraps the
returned float into a Decimal for DB storage.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Imputation defaults for partial inputs
# ---------------------------------------------------------------------------
# When only one of (dom, turnover) is available, we fall back to "neutral"
# values rather than refusing to score — a partial signal still beats no
# signal, and confidence will already be down-weighting these segments via
# the sample-size factor.
#
# The neutral values are picked at the calibration "neutral segment"
# (see DEFAULT_SCALE docstring): turnover=0.1/quarter and dom=60 days.

_NEUTRAL_TURNOVER_QUARTERLY = 0.1
_NEUTRAL_DOM_DAYS = 60.0


# ---------------------------------------------------------------------------
# Inputs / scale
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LiquidityInputs:
    """Per-segment liquidity inputs needed by the scoring formula."""

    dom_median_days: float | None  # how long active listings have been on market
    turnover_quarterly: float | None  # listings turned over / quarter (active+sold/withdrawn)


@dataclass(frozen=True)
class LiquidityScale:
    """Reference scale (min/max raw-score) used to map to 0..100.

    Initial defaults are set from a pragmatic CZ market view (see SCORING.md
    "DOM under 30 days and turnover > 0.1/quarter → high liquidity"):
    raw = -0.6 * dom - 0.4 / turnover.
    The scale must be wide enough to cover real markets without saturating.

    Calibration intuitions::

        ideal   (dom=20,  turnover=0.30): raw ≈ -13.33 → ~96.3 / 100
        neutral (dom=60,  turnover=0.10): raw =  -40   → ~66.7 / 100
        bad     (dom=150, turnover=0.02): raw = -110   → 0     / 100 (clamped)
    """

    raw_min: float  # raw value mapping to liquidity_score = 0
    raw_max: float  # raw value mapping to liquidity_score = 100


DEFAULT_SCALE = LiquidityScale(raw_min=-100.0, raw_max=-10.0)


# ---------------------------------------------------------------------------
# Raw and scaled liquidity
# ---------------------------------------------------------------------------


def _coerce_dom(dom: float | None) -> float | None:
    """Defensive: negative DOMs are treated as 0; None passes through."""
    if dom is None:
        return None
    d = float(dom)
    if d < 0:
        return 0.0
    return d


def _coerce_turnover(turnover: float | None) -> float | None:
    """Pass-through; None means missing. Non-positive is the caller's signal
    for "no observed turnover" — handled in :func:`raw_liquidity`."""
    if turnover is None:
        return None
    return float(turnover)


def raw_liquidity(inputs: LiquidityInputs) -> float | None:
    """The unscaled ``-0.6*dom - 0.4/turnover`` number.

    Returns ``None`` when both inputs are missing — there's nothing to score.
    If only one input is missing, imputes a neutral value (see module
    docstring) so the segment still gets a finite raw score.

    Edge cases:
      * ``turnover_quarterly <= 0`` → treated as 1/turnover = +∞, so the raw
        score saturates to ``-inf`` (clamps to 0 once scaled).
      * ``dom_median_days < 0`` → defensive clamp to 0.
    """
    dom = _coerce_dom(inputs.dom_median_days)
    turnover = _coerce_turnover(inputs.turnover_quarterly)

    if dom is None and turnover is None:
        return None

    if dom is None:
        dom = _NEUTRAL_DOM_DAYS
    if turnover is None:
        turnover = _NEUTRAL_TURNOVER_QUARTERLY

    if turnover <= 0:
        # 1 / turnover → +∞ ⇒ -0.4 * (+∞) = -∞
        return -math.inf

    return -0.6 * dom - 0.4 / turnover


def compute_liquidity_score(
    inputs: LiquidityInputs,
    *,
    scale: LiquidityScale = DEFAULT_SCALE,
) -> float | None:
    """Map raw to 0..100 via linear-scale-then-clamp.

    Returns ``None`` when :func:`raw_liquidity` returns ``None`` (both inputs
    missing). Higher liquidity → higher score.
    """
    raw = raw_liquidity(inputs)
    if raw is None:
        return None

    span = scale.raw_max - scale.raw_min
    if span <= 0:
        # Degenerate scale — collapse to neutral.
        return 50.0

    if math.isinf(raw):
        # -inf saturates to 0, +inf to 100. Only -inf is reachable from real
        # inputs (turnover<=0), but handle both for safety.
        return 0.0 if raw < 0 else 100.0

    pct = (raw - scale.raw_min) / span * 100.0
    if pct < 0.0:
        return 0.0
    if pct > 100.0:
        return 100.0
    return pct
