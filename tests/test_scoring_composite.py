"""Tests for the pure-function composite-score blender."""
from __future__ import annotations

import math

import pytest

from scoring.composite import (
    COMPONENT_NAMES,
    DEFAULT_REFS,
    ComponentRef,
    CompositeInputs,
    compute_composite,
    z_score,
)

_V1_WEIGHTS = {
    "undervaluation_pct": 1.5,
    "yield_gross_pct": 0.6,
    "liquidity_score": 0.3,
    "location_score": 0.3,
    "risk_score": -0.8,
}


class TestZScore:
    def test_zero_value_unit_stddev(self) -> None:
        assert z_score(0, ComponentRef(mean=0, stddev=1)) == pytest.approx(0.0, abs=1e-3)

    def test_one_stddev_above_zero_mean(self) -> None:
        assert z_score(15, ComponentRef(mean=0, stddev=15)) == pytest.approx(1.0, abs=1e-3)

    def test_value_equals_mean(self) -> None:
        assert z_score(50, ComponentRef(mean=50, stddev=20)) == pytest.approx(0.0, abs=1e-3)

    def test_multiple_stddevs_above_mean(self) -> None:
        assert z_score(100, ComponentRef(mean=50, stddev=20)) == pytest.approx(2.5, abs=1e-3)

    def test_zero_stddev_returns_zero(self) -> None:
        assert z_score(42, ComponentRef(mean=0, stddev=0)) == pytest.approx(0.0, abs=1e-3)

    def test_negative_stddev_returns_zero(self) -> None:
        assert z_score(42, ComponentRef(mean=0, stddev=-1)) == pytest.approx(0.0, abs=1e-3)


class TestCOMPONENT_NAMES:
    def test_length(self) -> None:
        assert len(COMPONENT_NAMES) == 5

    def test_contains_expected_names(self) -> None:
        assert "undervaluation_pct" in COMPONENT_NAMES
        assert "risk_score" in COMPONENT_NAMES
        assert "yield_gross_pct" in COMPONENT_NAMES


class TestComputeComposite:
    def test_all_none_inputs_yields_fifty(self) -> None:
        inputs = CompositeInputs(
            undervaluation_pct=None,
            yield_gross_pct=None,
            yield_confidence=None,
            liquidity_score=None,
            location_score=None,
            risk_score=None,
        )
        assert compute_composite(inputs, _V1_WEIGHTS) == pytest.approx(50.0, abs=1e-3)

    def test_strongly_undervalued(self) -> None:
        inputs = CompositeInputs(
            undervaluation_pct=30,
            yield_gross_pct=None,
            yield_confidence=None,
            liquidity_score=None,
            location_score=None,
            risk_score=None,
        )
        # z = 30/15 = 2.0; weighted = 1.5 * 2.0 = 3.0; sigmoid(3.0) ≈ 0.9526
        expected = 1.0 / (1.0 + math.exp(-3.0)) * 100.0
        result = compute_composite(inputs, _V1_WEIGHTS)
        assert result == pytest.approx(expected, abs=1e-3)
        assert result == pytest.approx(95.257, abs=1e-3)

    def test_strongly_risky(self) -> None:
        inputs = CompositeInputs(
            undervaluation_pct=None,
            yield_gross_pct=None,
            yield_confidence=None,
            liquidity_score=None,
            location_score=None,
            risk_score=70,
        )
        # z = (70-10)/15 = 4.0; weighted = -0.8 * 4.0 = -3.2; sigmoid(-3.2) ≈ 0.0392
        expected = 1.0 / (1.0 + math.exp(3.2)) * 100.0
        result = compute_composite(inputs, _V1_WEIGHTS)
        assert result == pytest.approx(expected, abs=1e-3)
        assert result == pytest.approx(3.917, abs=1e-3)

    def test_yield_with_none_confidence_contributes_zero(self) -> None:
        inputs = CompositeInputs(
            undervaluation_pct=None,
            yield_gross_pct=10,
            yield_confidence=None,
            liquidity_score=None,
            location_score=None,
            risk_score=None,
        )
        assert compute_composite(inputs, _V1_WEIGHTS) == pytest.approx(50.0, abs=1e-3)

    def test_yield_scales_with_full_confidence(self) -> None:
        inputs = CompositeInputs(
            undervaluation_pct=None,
            yield_gross_pct=8.0,
            yield_confidence=1.0,
            liquidity_score=None,
            location_score=None,
            risk_score=None,
        )
        # z = (8-4.5)/1.5 ≈ 2.333; weighted = 0.6 * 2.333 * 1.0 ≈ 1.4
        z = (8.0 - 4.5) / 1.5
        weighted = 0.6 * z * 1.0
        expected = 1.0 / (1.0 + math.exp(-weighted)) * 100.0
        result = compute_composite(inputs, _V1_WEIGHTS)
        assert result == pytest.approx(expected, abs=1e-3)
        assert result == pytest.approx(80.218, abs=1e-3)

    def test_yield_with_zero_confidence_neutralises(self) -> None:
        inputs = CompositeInputs(
            undervaluation_pct=None,
            yield_gross_pct=8.0,
            yield_confidence=0.0,
            liquidity_score=None,
            location_score=None,
            risk_score=None,
        )
        assert compute_composite(inputs, _V1_WEIGHTS) == pytest.approx(50.0, abs=1e-3)

    def test_all_components_present_in_range(self) -> None:
        inputs = CompositeInputs(
            undervaluation_pct=10.0,
            yield_gross_pct=5.5,
            yield_confidence=0.8,
            liquidity_score=60.0,
            location_score=55.0,
            risk_score=20.0,
        )
        result = compute_composite(inputs, _V1_WEIGHTS)
        assert math.isfinite(result)
        assert 0.0 <= result <= 100.0

    def test_missing_weight_raises_key_error(self) -> None:
        bad_weights = {
            "undervaluation_pct": 1.5,
            "yield_gross_pct": 0.6,
            "liquidity_score": 0.3,
            "location_score": 0.3,
            # "risk_score" intentionally missing
        }
        inputs = CompositeInputs(
            undervaluation_pct=10.0,
            yield_gross_pct=None,
            yield_confidence=None,
            liquidity_score=None,
            location_score=None,
            risk_score=None,
        )
        with pytest.raises(KeyError):
            compute_composite(inputs, bad_weights)


class TestRefsCustom:
    def test_custom_refs_override_defaults(self) -> None:
        inputs = CompositeInputs(
            undervaluation_pct=10,
            yield_gross_pct=None,
            yield_confidence=None,
            liquidity_score=None,
            location_score=None,
            risk_score=None,
        )
        custom_refs = {
            "undervaluation_pct": ComponentRef(mean=0.0, stddev=5.0),
            "yield_gross_pct": DEFAULT_REFS["yield_gross_pct"],
            "liquidity_score": DEFAULT_REFS["liquidity_score"],
            "location_score": DEFAULT_REFS["location_score"],
            "risk_score": DEFAULT_REFS["risk_score"],
        }

        default_result = compute_composite(inputs, _V1_WEIGHTS)
        custom_result = compute_composite(inputs, _V1_WEIGHTS, refs=custom_refs)

        # Custom refs give z=10/5=2 (weighted 3.0) vs default z≈0.667 (weighted 1.0),
        # so the custom result must be materially higher.
        assert custom_result > default_result + 10.0

        expected_custom = 1.0 / (1.0 + math.exp(-3.0)) * 100.0
        assert custom_result == pytest.approx(expected_custom, abs=1e-3)


class TestDefaultRefs:
    def test_default_refs_keys_match_component_names(self) -> None:
        assert set(DEFAULT_REFS.keys()) == set(COMPONENT_NAMES)
