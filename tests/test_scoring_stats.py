"""Tests for ppm² statistics aggregation."""
from __future__ import annotations

import pytest

from scoring.stats import compute_ppm2_stats, ppm2


class TestPpm2:
    def test_happy_path(self) -> None:
        assert ppm2(6_950_000, 56) == pytest.approx(124107.14, rel=1e-3)

    def test_missing_inputs(self) -> None:
        assert ppm2(None, 56) is None
        assert ppm2(6_950_000, None) is None

    def test_zero_or_negative(self) -> None:
        assert ppm2(0, 56) is None
        assert ppm2(6_950_000, 0) is None
        assert ppm2(-1, 56) is None


class TestComputeStats:
    def test_empty_returns_none(self) -> None:
        assert compute_ppm2_stats([]) is None

    def test_single_value(self) -> None:
        s = compute_ppm2_stats([100_000.0])
        assert s is not None
        assert s.n_samples == 1
        assert s.median == 100_000.0
        assert s.trimmed_mean == 100_000.0
        assert s.p25 == 100_000.0
        assert s.p75 == 100_000.0
        assert s.stddev == 0.0

    def test_known_distribution(self) -> None:
        # Values 1..9 — well-known quartiles.
        s = compute_ppm2_stats([1.0, 2, 3, 4, 5, 6, 7, 8, 9])
        assert s is not None
        assert s.n_samples == 9
        assert s.median == 5.0
        assert s.p25 == 3.0
        assert s.p75 == 7.0

    def test_trimmed_mean_drops_outliers(self) -> None:
        # 1000 is an extreme outlier; trimmed mean should be close to 5.
        values = [1.0, 2, 3, 4, 5, 6, 7, 8, 9, 1000.0]
        s = compute_ppm2_stats(values, trim_pct=0.10)
        assert s is not None
        # Median is robust regardless.
        assert s.median == pytest.approx(5.5, abs=1e-6)
        # Trimmed mean drops 1 from each tail → mean of 2..9 = 5.5
        assert s.trimmed_mean == pytest.approx(5.5, abs=1e-6)

    def test_drops_invalid_values(self) -> None:
        s = compute_ppm2_stats([1.0, float("nan"), 2.0, 0.0, -1.0, 3.0])
        assert s is not None
        assert s.n_samples == 3

    def test_is_usable_threshold(self) -> None:
        s = compute_ppm2_stats([float(i) for i in range(1, 31)])
        assert s is not None
        assert s.is_usable(min_samples=30) is True
        assert s.is_usable(min_samples=31) is False
