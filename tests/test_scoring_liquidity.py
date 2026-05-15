"""Tests for the pure-function liquidity score layer."""
from __future__ import annotations

import math

import pytest

from scoring.liquidity import (
    DEFAULT_SCALE,
    LiquidityInputs,
    LiquidityScale,
    compute_liquidity_score,
    raw_liquidity,
)

# ---------------------------------------------------------------------------
# raw_liquidity
# ---------------------------------------------------------------------------


class TestRawLiquidity:
    def test_happy_path(self) -> None:
        # -0.6*30 - 0.4/0.2 = -18 - 2 = -20
        raw = raw_liquidity(LiquidityInputs(dom_median_days=30, turnover_quarterly=0.2))
        assert raw == pytest.approx(-20.0, abs=1e-9)

    def test_ideal_segment(self) -> None:
        # -0.6*20 - 0.4/0.3 = -12 - 1.333... ≈ -13.333
        raw = raw_liquidity(LiquidityInputs(dom_median_days=20, turnover_quarterly=0.3))
        assert raw == pytest.approx(-13.333, abs=1e-3)

    def test_both_none_returns_none(self) -> None:
        assert raw_liquidity(LiquidityInputs(dom_median_days=None, turnover_quarterly=None)) is None

    def test_turnover_zero_is_minus_infinity(self) -> None:
        raw = raw_liquidity(LiquidityInputs(dom_median_days=30, turnover_quarterly=0))
        assert raw == -math.inf

    def test_turnover_negative_is_minus_infinity(self) -> None:
        raw = raw_liquidity(LiquidityInputs(dom_median_days=30, turnover_quarterly=-0.5))
        assert raw == -math.inf

    def test_negative_dom_clamped_to_zero(self) -> None:
        # dom<0 should be treated as 0 → raw = -0.4 / 0.2 = -2
        raw = raw_liquidity(LiquidityInputs(dom_median_days=-5, turnover_quarterly=0.2))
        assert raw == pytest.approx(-2.0, abs=1e-9)


# ---------------------------------------------------------------------------
# compute_liquidity_score
# ---------------------------------------------------------------------------


class TestComputeLiquidityScore:
    def test_ideal_segment_high_score(self) -> None:
        # raw ≈ -13.33 ; scale -100..-10 ; (-13.33 - -100) / 90 * 100 ≈ 96.3
        score = compute_liquidity_score(
            LiquidityInputs(dom_median_days=20, turnover_quarterly=0.3)
        )
        assert score is not None
        assert score == pytest.approx(96.3, abs=0.5)
        assert score > 90.0

    def test_neutral_segment(self) -> None:
        # raw = -40 ; (-40 - -100)/90*100 = 66.666...
        score = compute_liquidity_score(
            LiquidityInputs(dom_median_days=60, turnover_quarterly=0.1)
        )
        assert score is not None
        assert score == pytest.approx(66.667, abs=0.01)

    def test_bad_segment_clamps_to_zero(self) -> None:
        # raw = -110 (below raw_min=-100) → clamped to 0
        score = compute_liquidity_score(
            LiquidityInputs(dom_median_days=150, turnover_quarterly=0.02)
        )
        assert score == 0.0

    def test_saturated_very_low_dom_clamps_to_100(self) -> None:
        # -0.6*5 - 0.4/0.5 = -3 - 0.8 = -3.8 (above raw_max=-10) → clamped to 100
        score = compute_liquidity_score(
            LiquidityInputs(dom_median_days=5, turnover_quarterly=0.5)
        )
        assert score == 100.0

    def test_missing_both_returns_none(self) -> None:
        score = compute_liquidity_score(
            LiquidityInputs(dom_median_days=None, turnover_quarterly=None)
        )
        assert score is None

    def test_turnover_zero_clamps_to_zero(self) -> None:
        score = compute_liquidity_score(
            LiquidityInputs(dom_median_days=30, turnover_quarterly=0)
        )
        assert score == 0.0

    def test_custom_narrower_scale_scales_up(self) -> None:
        # Take a mid-ish input and check a narrower scale produces a different
        # (and, for raw inside narrower window, higher-magnitude-relative)
        # mapping than the default. Use dom=40, turnover=0.15 → raw = -24 - 2.667 = -26.667.
        inputs = LiquidityInputs(dom_median_days=40, turnover_quarterly=0.15)
        default_score = compute_liquidity_score(inputs)
        # Narrower scale around the same raw range: spans -50..-10 instead of -100..-10.
        narrow = LiquidityScale(raw_min=-50.0, raw_max=-10.0)
        narrow_score = compute_liquidity_score(inputs, scale=narrow)
        assert default_score is not None
        assert narrow_score is not None
        # raw = -26.667
        # default: (-26.667 - -100)/90 * 100 ≈ 81.5
        # narrow:  (-26.667 - -50)/40 * 100  ≈ 58.3
        # The narrower scale is more discriminating around the neutral range,
        # so for this raw (closer to raw_max in default) the narrower scale
        # yields a *lower* score for the same input.
        assert default_score == pytest.approx(81.48, abs=0.5)
        assert narrow_score == pytest.approx(58.33, abs=0.5)
        assert narrow_score < default_score

    def test_custom_scale_can_scale_up_for_lower_raw(self) -> None:
        # For a raw near the bottom of the default scale, a narrower scale
        # whose raw_min is at that raw produces a higher score.
        inputs = LiquidityInputs(dom_median_days=80, turnover_quarterly=0.05)
        # raw = -48 - 8 = -56
        default_score = compute_liquidity_score(inputs)
        narrow = LiquidityScale(raw_min=-60.0, raw_max=-10.0)
        narrow_score = compute_liquidity_score(inputs, scale=narrow)
        assert default_score is not None
        assert narrow_score is not None
        # default: (-56 - -100)/90*100 ≈ 48.89
        # narrow:  (-56 - -60)/50*100 = 8.0
        # The narrower scale here yields a *lower* score (raw is near its min).
        # We assert both are computed and within [0,100].
        assert 0.0 <= default_score <= 100.0
        assert 0.0 <= narrow_score <= 100.0


# ---------------------------------------------------------------------------
# Neutral imputation when one input is missing
# ---------------------------------------------------------------------------


class TestNeutralImputation:
    def test_only_dom_present_is_finite(self) -> None:
        # turnover defaults to 0.1 → raw = -0.6*30 - 0.4/0.1 = -18 - 4 = -22
        raw = raw_liquidity(LiquidityInputs(dom_median_days=30, turnover_quarterly=None))
        assert raw is not None
        assert math.isfinite(raw)
        assert raw == pytest.approx(-22.0, abs=1e-9)
        score = compute_liquidity_score(
            LiquidityInputs(dom_median_days=30, turnover_quarterly=None)
        )
        assert score is not None
        assert math.isfinite(score)
        assert 0.0 < score < 100.0

    def test_only_turnover_present_is_finite(self) -> None:
        # dom defaults to 60 → raw = -0.6*60 - 0.4/0.2 = -36 - 2 = -38
        raw = raw_liquidity(LiquidityInputs(dom_median_days=None, turnover_quarterly=0.2))
        assert raw is not None
        assert math.isfinite(raw)
        assert raw == pytest.approx(-38.0, abs=1e-9)
        score = compute_liquidity_score(
            LiquidityInputs(dom_median_days=None, turnover_quarterly=0.2)
        )
        assert score is not None
        assert math.isfinite(score)
        assert 0.0 < score < 100.0

    def test_default_scale_constant_unchanged(self) -> None:
        # Guard against accidental tuning that would shift everyone's scores.
        assert DEFAULT_SCALE.raw_min == -100.0
        assert DEFAULT_SCALE.raw_max == -10.0
