"""Tests for the pure-function confidence layer."""
from __future__ import annotations

import pytest

from scoring.confidence import (
    CRITICAL_FIELDS,
    compute_confidence,
    field_completeness,
    geocode_precision_factor,
    listing_freshness_factor,
    relaxation_factor,
    sample_size_factor,
)


class TestSampleSizeFactor:
    def test_zero_is_very_low(self) -> None:
        assert sample_size_factor(0) == pytest.approx(0.047, abs=1e-3)

    def test_midpoint_at_thirty(self) -> None:
        assert sample_size_factor(30) == pytest.approx(0.5, abs=1e-3)

    def test_sixty_is_near_one(self) -> None:
        assert sample_size_factor(60) == pytest.approx(0.953, abs=1e-3)

    def test_large_n_approaches_one(self) -> None:
        assert sample_size_factor(1000) == pytest.approx(1.0, abs=1e-3)

    def test_negative_clamped_to_zero(self) -> None:
        assert sample_size_factor(-5) == pytest.approx(sample_size_factor(0), abs=1e-9)


class TestRelaxationFactor:
    def test_zero_level_is_one(self) -> None:
        assert relaxation_factor(0) == 1.0

    def test_max_level_is_floor(self) -> None:
        assert relaxation_factor(5) == pytest.approx(0.6, abs=1e-9)

    def test_interpolation_at_two(self) -> None:
        # 1 - 0.4 * (2/5) = 0.84
        assert relaxation_factor(2) == pytest.approx(0.84, abs=1e-3)

    def test_above_max_clamped(self) -> None:
        assert relaxation_factor(10) == pytest.approx(0.6, abs=1e-9)

    def test_negative_is_one(self) -> None:
        assert relaxation_factor(-1) == 1.0


class TestFieldCompleteness:
    def test_zero_present(self) -> None:
        assert field_completeness(0, 9) == 0.0

    def test_all_present(self) -> None:
        assert field_completeness(9, 9) == 1.0

    def test_partial(self) -> None:
        assert field_completeness(4, 9) == pytest.approx(4 / 9, abs=1e-9)

    def test_overflow_clamped(self) -> None:
        assert field_completeness(10, 9) == 1.0

    def test_zero_total_is_complete(self) -> None:
        assert field_completeness(5, 0) == 1.0


class TestGeocodePrecisionFactor:
    def test_rooftop(self) -> None:
        assert geocode_precision_factor("rooftop") == 1.0

    def test_parcel(self) -> None:
        assert geocode_precision_factor("parcel") == pytest.approx(0.95, abs=1e-9)

    def test_street(self) -> None:
        assert geocode_precision_factor("street") == pytest.approx(0.85, abs=1e-9)

    def test_source_gps(self) -> None:
        assert geocode_precision_factor("source_gps") == pytest.approx(0.6, abs=1e-9)

    def test_locality(self) -> None:
        assert geocode_precision_factor("locality") == 0.5

    def test_none(self) -> None:
        assert geocode_precision_factor(None) == 0.5

    def test_unknown_fallback(self) -> None:
        assert geocode_precision_factor("garbage") == 0.5


class TestListingFreshnessFactor:
    def test_zero_days(self) -> None:
        assert listing_freshness_factor(0) == 1.0

    def test_thirty_days_edge(self) -> None:
        assert listing_freshness_factor(30) == 1.0

    def test_midpoint(self) -> None:
        # Midpoint between 30 and 180 is 105 → halfway from 1.0 to 0.5 = 0.75
        assert listing_freshness_factor(105) == pytest.approx(0.75, abs=1e-3)

    def test_one_eighty_floor(self) -> None:
        assert listing_freshness_factor(180) == pytest.approx(0.5, abs=1e-9)

    def test_far_past_floor(self) -> None:
        assert listing_freshness_factor(365) == pytest.approx(0.5, abs=1e-9)

    def test_none(self) -> None:
        assert listing_freshness_factor(None) == 0.5

    def test_negative_is_fresh(self) -> None:
        assert listing_freshness_factor(-7) == 1.0


class TestComputeConfidence:
    def test_all_best_case_near_one(self) -> None:
        result = compute_confidence(
            sample_size=100,
            relaxation_level=0,
            completeness=1.0,
            geocode_precision="rooftop",
            freshness_days=10,
        )
        assert result == pytest.approx(1.0, abs=1e-2)

    def test_all_worst_case_zero(self) -> None:
        result = compute_confidence(
            sample_size=0,
            relaxation_level=5,
            completeness=0.0,
            geocode_precision=None,
            freshness_days=365,
        )
        assert result == 0.0

    def test_mid_case_matches_product(self) -> None:
        sample_size = 30
        relaxation_level = 2
        completeness = 0.75
        geocode_precision = "street"
        freshness_days = 105

        expected = (
            sample_size_factor(sample_size)
            * relaxation_factor(relaxation_level)
            * completeness
            * geocode_precision_factor(geocode_precision)
            * listing_freshness_factor(freshness_days)
        )
        expected_rounded = round(expected, 3)

        result = compute_confidence(
            sample_size=sample_size,
            relaxation_level=relaxation_level,
            completeness=completeness,
            geocode_precision=geocode_precision,
            freshness_days=freshness_days,
        )
        assert result == pytest.approx(expected_rounded, abs=1e-3)

    def test_negative_completeness_clamped(self) -> None:
        result = compute_confidence(
            sample_size=100,
            relaxation_level=0,
            completeness=-0.5,
            geocode_precision="rooftop",
            freshness_days=10,
        )
        assert result == 0.0

    def test_overflow_completeness_clamped(self) -> None:
        # With completeness > 1.0 clamped to 1.0, result equals the all-best case (~1.0).
        result = compute_confidence(
            sample_size=100,
            relaxation_level=0,
            completeness=2.5,
            geocode_precision="rooftop",
            freshness_days=10,
        )
        assert result == pytest.approx(1.0, abs=1e-2)


class TestCriticalFields:
    def test_count(self) -> None:
        assert len(CRITICAL_FIELDS) == 9

    def test_contains_staples(self) -> None:
        assert "price" in CRITICAL_FIELDS
        assert "size_m2" in CRITICAL_FIELDS
        assert "ownership_type" in CRITICAL_FIELDS
