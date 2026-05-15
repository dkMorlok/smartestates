"""Tests for the pure-function yield estimator (src/scoring/yield_est.py)."""
from __future__ import annotations

from decimal import Decimal

import pytest

from scoring.yield_est import (
    DEFAULT_HOA_CZK_PER_M2_PER_MONTH,
    HOA_DEFAULT_CONFIDENCE_PENALTY,
    MIN_RENTAL_COMPS,
    YieldInputs,
    YieldResult,
    compute_yield,
)


def _base_inputs(**overrides: object) -> YieldInputs:
    """Happy-path inputs; override single fields per test."""
    defaults: dict[str, object] = {
        "asking_price_czk": Decimal("8000000"),
        "size_m2": Decimal("70"),
        "hoa_czk_per_month_known": 3500.0,
        "rent_ppm2_per_month_trimmed_mean": 400.0,
        "rental_n_comps": 40,
        "relaxation_level": 0,
    }
    defaults.update(overrides)
    return YieldInputs(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# TestComputeYield
# ---------------------------------------------------------------------------


class TestComputeYield:
    def test_no_comps_returns_none_yield_and_zero_confidence(self) -> None:
        result = compute_yield(_base_inputs(rent_ppm2_per_month_trimmed_mean=None))
        assert result.yield_gross_pct is None
        assert result.yield_confidence == 0.0
        assert result.monthly_rent_estimate_czk is None
        assert result.annual_hoa_estimate_czk is None
        assert result.used_default_hoa is False

    def test_below_min_rental_comps_returns_none(self) -> None:
        result = compute_yield(_base_inputs(rental_n_comps=5))
        assert result.yield_gross_pct is None
        assert result.yield_confidence == 0.0
        assert result.monthly_rent_estimate_czk is None
        assert result.annual_hoa_estimate_czk is None

    def test_happy_path_known_hoa(self) -> None:
        result = compute_yield(_base_inputs())
        # monthly_rent = 400 * 70 = 28000
        # annual_rent = 336000; annual_hoa = 42000; net = 294000
        # yield = 294000 / 8_000_000 * 100 = 3.675
        assert result.yield_gross_pct == pytest.approx(3.675, abs=1e-3)
        assert result.monthly_rent_estimate_czk == pytest.approx(28000.0, abs=1e-3)
        assert result.annual_hoa_estimate_czk == pytest.approx(42000.0, abs=1e-3)
        assert result.used_default_hoa is False
        # n=40 (>=30), level 0, known HOA -> full confidence 1.0
        assert result.yield_confidence == pytest.approx(1.0, abs=1e-3)

    def test_default_hoa_used_halves_confidence(self) -> None:
        result = compute_yield(_base_inputs(hoa_czk_per_month_known=None))
        assert result.used_default_hoa is True
        # HOA = 50 * 70 = 3500 CZK/mo -> annual 42000 (same as known case here)
        assert result.annual_hoa_estimate_czk == pytest.approx(
            DEFAULT_HOA_CZK_PER_M2_PER_MONTH * 70.0 * 12.0, abs=1e-3
        )
        # Confidence halved by HOA penalty
        assert result.yield_confidence == pytest.approx(
            HOA_DEFAULT_CONFIDENCE_PENALTY, abs=1e-3
        )
        # Yield value unchanged in this case because 50*70 == 3500
        assert result.yield_gross_pct == pytest.approx(3.675, abs=1e-3)

    def test_relaxed_segment_reduces_confidence_linearly(self) -> None:
        # Level 3 of 5: factor = 1.0 - 0.4 * (3/5) = 0.76
        result = compute_yield(_base_inputs(relaxation_level=3))
        assert result.yield_confidence == pytest.approx(0.76, abs=1e-3)

    def test_sample_size_between_min_and_thirty_half_confidence(self) -> None:
        result = compute_yield(_base_inputs(rental_n_comps=15))
        # 10 <= 15 < 30 -> 0.5 sample-size factor; level 0; known HOA
        assert result.yield_confidence == pytest.approx(0.5, abs=1e-3)
        # Still produces a yield value
        assert result.yield_gross_pct is not None

    def test_yield_clamped_at_max_when_rent_extreme(self) -> None:
        # 5000 CZK/m²/mo rent on a 70 m² flat at 8M asking is unrealistic; check clamp
        result = compute_yield(
            _base_inputs(rent_ppm2_per_month_trimmed_mean=5000.0)
        )
        assert result.yield_gross_pct == pytest.approx(25.0, abs=1e-6)

    def test_asking_price_zero_returns_none(self) -> None:
        result = compute_yield(_base_inputs(asking_price_czk=Decimal("0")))
        assert result.yield_gross_pct is None
        assert result.yield_confidence == 0.0

    def test_size_zero_returns_none(self) -> None:
        result = compute_yield(_base_inputs(size_m2=Decimal("0")))
        assert result.yield_gross_pct is None
        assert result.yield_confidence == 0.0

    def test_negative_net_rent_clamped_at_min(self) -> None:
        # Huge HOA -> net rent strongly negative -> clamp at -5
        result = compute_yield(
            _base_inputs(hoa_czk_per_month_known=1_000_000.0)
        )
        assert result.yield_gross_pct is not None
        assert result.yield_gross_pct == pytest.approx(-5.0, abs=1e-6)
        assert result.yield_gross_pct >= -5.0

    def test_returns_yield_result_dataclass(self) -> None:
        result = compute_yield(_base_inputs())
        assert isinstance(result, YieldResult)

    def test_accepts_plain_float_price_and_size(self) -> None:
        result = compute_yield(
            _base_inputs(asking_price_czk=8_000_000.0, size_m2=70.0)
        )
        assert result.yield_gross_pct == pytest.approx(3.675, abs=1e-3)

    def test_none_price_returns_none(self) -> None:
        result = compute_yield(_base_inputs(asking_price_czk=None))
        assert result.yield_gross_pct is None
        assert result.yield_confidence == 0.0

    def test_none_size_returns_none(self) -> None:
        result = compute_yield(_base_inputs(size_m2=None))
        assert result.yield_gross_pct is None
        assert result.yield_confidence == 0.0


# ---------------------------------------------------------------------------
# TestConstants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_min_rental_comps_is_ten(self) -> None:
        assert MIN_RENTAL_COMPS == 10

    def test_default_hoa_per_m2_per_month(self) -> None:
        assert DEFAULT_HOA_CZK_PER_M2_PER_MONTH == 50.0

    def test_hoa_default_penalty_halves_confidence(self) -> None:
        assert HOA_DEFAULT_CONFIDENCE_PENALTY == 0.5
