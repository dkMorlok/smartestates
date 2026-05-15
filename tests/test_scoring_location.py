"""Tests for the pure-function location-score layer."""
from __future__ import annotations

import pytest

from scoring.location import (
    AMENITY_FULL_COUNT,
    AMENITY_KEYS,
    PARK_BEST_M,
    PARK_WORST_M,
    ROAD_QUIET_BEST_M,
    ROAD_QUIET_WORST_M,
    TRANSIT_BEST_M,
    TRANSIT_WORST_M,
    LocationBreakdown,
    LocationInputs,
    amenities_subscore,
    compute_location,
    green_subscore,
    quiet_subscore,
    transit_subscore,
)


def _inputs(
    *,
    metro: float | None = None,
    tram: float | None = None,
    train: float | None = None,
    amenities: dict[str, int] | None = None,
    park: float | None = None,
    road: float | None = None,
) -> LocationInputs:
    return LocationInputs(
        distance_to_metro_m=metro,
        distance_to_tram_m=tram,
        distance_to_train_m=train,
        amenity_counts=amenities,
        distance_to_park_m=park,
        distance_to_major_road_m=road,
    )


class TestTransitSubscore:
    def test_all_three_within_best_distance(self) -> None:
        s = transit_subscore(_inputs(metro=200, tram=200, train=200))
        assert s == pytest.approx(100.0, abs=1e-6)

    def test_all_none_returns_none(self) -> None:
        assert transit_subscore(_inputs()) is None

    def test_picks_best_of_available_modalities(self) -> None:
        # metro=300 is the best; tram=1500 worse; train missing.
        s = transit_subscore(_inputs(metro=300, tram=1500, train=None))
        assert s == pytest.approx(100.0, abs=1e-6)

    def test_at_worst_distance_returns_zero(self) -> None:
        s = transit_subscore(_inputs(metro=2000))
        assert s == pytest.approx(0.0, abs=1e-6)

    def test_midpoint_returns_roughly_fifty(self) -> None:
        # Midpoint between 300 and 2000 is 1150 → ~50.
        s = transit_subscore(_inputs(metro=1150))
        assert s is not None
        assert s == pytest.approx(50.0, abs=0.5)

    def test_beyond_worst_clamps_to_zero(self) -> None:
        assert transit_subscore(_inputs(metro=5000)) == pytest.approx(0.0, abs=1e-6)

    def test_only_train_available(self) -> None:
        s = transit_subscore(_inputs(train=300))
        assert s == pytest.approx(100.0, abs=1e-6)


class TestAmenitiesSubscore:
    def test_none_dict_returns_none(self) -> None:
        assert amenities_subscore(None) is None

    def test_empty_dict_returns_zero(self) -> None:
        assert amenities_subscore({}) == pytest.approx(0.0, abs=1e-6)

    def test_twenty_amenities_full_score(self) -> None:
        # 10 grocery + 10 cafe = 20 → 100
        assert amenities_subscore({"grocery": 10, "cafe": 10}) == pytest.approx(
            100.0, abs=1e-6
        )

    def test_five_grocery_quarter_score(self) -> None:
        # 5 / 20 * 100 = 25
        assert amenities_subscore({"grocery": 5}) == pytest.approx(25.0, abs=1e-6)

    def test_unknown_key_is_ignored(self) -> None:
        assert amenities_subscore({"unknown_key": 100}) == pytest.approx(0.0, abs=1e-6)

    def test_overfull_count_clamps_to_hundred(self) -> None:
        assert amenities_subscore({"grocery": 1000}) == pytest.approx(100.0, abs=1e-6)


class TestGreenSubscore:
    def test_at_best_distance_full_score(self) -> None:
        assert green_subscore(300) == pytest.approx(100.0, abs=1e-6)

    def test_at_worst_distance_zero(self) -> None:
        assert green_subscore(1500) == pytest.approx(0.0, abs=1e-6)

    def test_midpoint(self) -> None:
        # midpoint between 300 and 1500 = 900 → 50
        assert green_subscore(900) == pytest.approx(50.0, abs=1e-6)

    def test_below_best_clamps(self) -> None:
        assert green_subscore(200) == pytest.approx(100.0, abs=1e-6)

    def test_none_returns_none(self) -> None:
        assert green_subscore(None) is None


class TestQuietSubscore:
    def test_far_from_road_full_score(self) -> None:
        assert quiet_subscore(200) == pytest.approx(100.0, abs=1e-6)

    def test_at_worst_close_road_zero(self) -> None:
        assert quiet_subscore(20) == pytest.approx(0.0, abs=1e-6)

    def test_midpoint(self) -> None:
        # midpoint between 20 and 200 = 110 → 50
        assert quiet_subscore(110) == pytest.approx(50.0, abs=1e-6)

    def test_very_close_clamps_to_zero(self) -> None:
        assert quiet_subscore(5) == pytest.approx(0.0, abs=1e-6)

    def test_none_returns_none(self) -> None:
        assert quiet_subscore(None) is None


class TestComputeLocation:
    def test_all_inputs_populated(self) -> None:
        inp = _inputs(
            metro=200,  # transit=100
            tram=400,
            train=None,
            amenities={"grocery": 5},  # amenities=25
            park=900,  # green=50
            road=110,  # quiet=50
        )
        b = compute_location(inp)
        assert isinstance(b, LocationBreakdown)
        assert b.transit == pytest.approx(100.0, abs=1e-6)
        assert b.amenities == pytest.approx(25.0, abs=1e-6)
        assert b.green == pytest.approx(50.0, abs=1e-6)
        assert b.quiet == pytest.approx(50.0, abs=1e-6)
        assert b.composite == pytest.approx((100 + 25 + 50 + 50) / 4, abs=1e-6)

    def test_all_inputs_missing(self) -> None:
        b = compute_location(_inputs())
        assert b.transit is None
        assert b.amenities is None
        assert b.green is None
        assert b.quiet is None
        assert b.composite is None

    def test_only_transit_available(self) -> None:
        b = compute_location(_inputs(metro=300))
        assert b.transit == pytest.approx(100.0, abs=1e-6)
        assert b.amenities is None
        assert b.green is None
        assert b.quiet is None
        assert b.composite == pytest.approx(100.0, abs=1e-6)

    def test_two_subscores_available(self) -> None:
        # green=50, quiet=50; transit + amenities missing.
        b = compute_location(_inputs(park=900, road=110))
        assert b.transit is None
        assert b.amenities is None
        assert b.green == pytest.approx(50.0, abs=1e-6)
        assert b.quiet == pytest.approx(50.0, abs=1e-6)
        assert b.composite == pytest.approx(50.0, abs=1e-6)

    def test_empty_amenities_dict_counts_as_present(self) -> None:
        # An empty dict means "we looked and found nothing" — score 0, NOT None.
        b = compute_location(_inputs(amenities={}))
        assert b.amenities == pytest.approx(0.0, abs=1e-6)
        assert b.composite == pytest.approx(0.0, abs=1e-6)


class TestConstants:
    def test_amenity_keys_contains_grocery_and_school(self) -> None:
        assert "grocery" in AMENITY_KEYS
        assert "school" in AMENITY_KEYS

    def test_transit_best_less_than_worst(self) -> None:
        assert TRANSIT_BEST_M < TRANSIT_WORST_M

    def test_park_best_less_than_worst(self) -> None:
        assert PARK_BEST_M < PARK_WORST_M

    def test_road_quiet_worst_less_than_best(self) -> None:
        # Quiet is inverse: small distance = bad, large = good.
        assert ROAD_QUIET_WORST_M < ROAD_QUIET_BEST_M

    def test_amenity_full_count_positive(self) -> None:
        assert AMENITY_FULL_COUNT > 0
