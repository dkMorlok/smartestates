"""Tests for the pure-function hedonic regression module."""
from __future__ import annotations

import math
import random
from decimal import Decimal

import pytest

from scoring.hedonic import (
    MIN_FIT_SAMPLES,
    UNDERVALUATION_CLAMP_PCT,
    HedonicFeatures,
    HedonicModel,
    fit_hedonic,
    predict_log_ppm2,
    undervaluation_pct,
)


def _synthetic_features(
    n: int, *, seed: int = 0
) -> tuple[list[HedonicFeatures], list[float]]:
    rng = random.Random(seed)
    features: list[HedonicFeatures] = []
    targets: list[float] = []
    for _ in range(n):
        size = rng.uniform(30, 150)
        true_log_ppm2 = 11.0 + 0.05 * math.log(size) + rng.gauss(0, 0.05)
        features.append(
            HedonicFeatures(
                size_m2=Decimal(f"{size:.2f}"),
                floor_current=rng.randint(1, 8),
                floor_total=rng.randint(3, 10),
                has_lift=rng.choice([True, False, None]),
                has_balcony=rng.choice([True, False, None]),
                has_loggia=None,
                has_terrace=None,
                has_cellar=None,
                has_parking=None,
                building_type=rng.choice(["panel", "cihla"]),
                disposition=rng.choice(["2+kk", "3+kk"]),
                condition="velmi_dobry",
                year_built=rng.randint(1960, 2020),
                energy_class=rng.choice(["B", "C", "D"]),
                city_district=rng.choice(["Praha 5", "Praha 6"]),
            )
        )
        targets.append(true_log_ppm2)
    return features, targets


def _empty_features(size_m2: Decimal | float | int | None) -> HedonicFeatures:
    """Minimal listing fixture — only size_m2 set."""
    return HedonicFeatures(
        size_m2=size_m2,
        floor_current=None,
        floor_total=None,
        has_lift=None,
        has_balcony=None,
        has_loggia=None,
        has_terrace=None,
        has_cellar=None,
        has_parking=None,
        building_type=None,
        disposition=None,
        condition=None,
        year_built=None,
        energy_class=None,
        city_district=None,
    )


class TestUndervaluationPct:
    def test_zero_residual(self) -> None:
        assert undervaluation_pct(11.5, 11.5) == pytest.approx(0.0, abs=1e-9)

    def test_predicted_above_actual(self) -> None:
        # log diff of +0.10 → (exp(0.10) - 1) * 100 ≈ 10.517%
        assert undervaluation_pct(11.10, 11.00) == pytest.approx(10.517, rel=1e-3)

    def test_clamped_negative(self) -> None:
        # Large negative log diff drives pct well below -50% and must clamp.
        assert undervaluation_pct(10.0, 15.0) == pytest.approx(
            -UNDERVALUATION_CLAMP_PCT, rel=1e-9
        )

    def test_clamped_positive(self) -> None:
        # Large positive log diff (e.g. +5.0) far exceeds the +50% cap.
        assert undervaluation_pct(15.0, 10.0) == pytest.approx(
            UNDERVALUATION_CLAMP_PCT, rel=1e-9
        )

    def test_symmetric_clamp_value(self) -> None:
        # The clamp magnitude is the same on both sides.
        hi = undervaluation_pct(20.0, 10.0)
        lo = undervaluation_pct(10.0, 20.0)
        assert hi == pytest.approx(UNDERVALUATION_CLAMP_PCT, rel=1e-9)
        assert lo == pytest.approx(-UNDERVALUATION_CLAMP_PCT, rel=1e-9)
        assert hi == pytest.approx(-lo, rel=1e-9)


class TestFitHedonic:
    def test_insufficient_samples_returns_none(self) -> None:
        features, targets = _synthetic_features(MIN_FIT_SAMPLES - 1, seed=1)
        result = fit_hedonic(
            features, targets, group_key=("Praha", "byt", "osobni")
        )
        assert result is None

    def test_fits_synthetic_linear_data(self) -> None:
        features, targets = _synthetic_features(60, seed=2)
        model = fit_hedonic(
            features, targets, group_key=("Praha", "byt", "osobni")
        )
        assert model is not None
        assert isinstance(model, HedonicModel)
        assert model.n_samples >= MIN_FIT_SAMPLES
        assert "log_size_m2" in model.columns
        # True intercept ≈ 11.0. With only ~60 noisy samples plus dozens of
        # categorical dummies in the design matrix, the recovered log_size_m2
        # coefficient is biased; we only check sign + order-of-magnitude.
        assert model.intercept == pytest.approx(11.0, rel=0.05)
        log_size_coef = model.coef_by_column["log_size_m2"]
        assert log_size_coef > 0.0
        assert log_size_coef < 0.20
        assert model.group_key == ("Praha", "byt", "osobni")

    def test_mismatched_lengths_returns_none(self) -> None:
        features, targets = _synthetic_features(60, seed=3)
        result = fit_hedonic(
            features, targets[:-1], group_key=("Praha", "byt", "osobni")
        )
        assert result is None

    def test_all_missing_size_returns_none(self) -> None:
        features = [_empty_features(None) for _ in range(MIN_FIT_SAMPLES + 5)]
        targets = [11.5 for _ in features]
        result = fit_hedonic(
            features, targets, group_key=("Praha", "byt", "osobni")
        )
        assert result is None


class TestPredictLogPpm2:
    def test_in_range_prediction_matches_truth(self) -> None:
        features, targets = _synthetic_features(80, seed=4)
        model = fit_hedonic(
            features, targets, group_key=("Praha", "byt", "osobni")
        )
        assert model is not None

        # A never-seen listing whose size sits in the training range.
        test = HedonicFeatures(
            size_m2=Decimal("75.00"),
            floor_current=3,
            floor_total=6,
            has_lift=True,
            has_balcony=True,
            has_loggia=None,
            has_terrace=None,
            has_cellar=None,
            has_parking=None,
            building_type="cihla",
            disposition="2+kk",
            condition="velmi_dobry",
            year_built=1995,
            energy_class="C",
            city_district="Praha 5",
        )
        predicted = predict_log_ppm2(model, test)
        assert predicted is not None
        true_value = 11.0 + 0.05 * math.log(75.0)
        # Generous tolerance — the design matrix has many other coefficients
        # absorbing small amounts of variance even on cleanly-generated data.
        assert predicted == pytest.approx(true_value, abs=0.20)

    def test_missing_size_returns_none(self) -> None:
        features, targets = _synthetic_features(60, seed=5)
        model = fit_hedonic(
            features, targets, group_key=("Praha", "byt", "osobni")
        )
        assert model is not None
        result = predict_log_ppm2(model, _empty_features(None))
        assert result is None

    def test_unseen_categorical_level_still_predicts(self) -> None:
        features, targets = _synthetic_features(60, seed=6)
        model = fit_hedonic(
            features, targets, group_key=("Praha", "byt", "osobni")
        )
        assert model is not None

        unseen = HedonicFeatures(
            size_m2=Decimal("60.00"),
            floor_current=2,
            floor_total=5,
            has_lift=True,
            has_balcony=None,
            has_loggia=None,
            has_terrace=None,
            has_cellar=None,
            has_parking=None,
            building_type="srub",  # unseen during fit
            disposition="9+kk",  # unseen during fit
            condition="velmi_dobry",
            year_built=2005,
            energy_class="A",  # unseen during fit
            city_district="Praha 99",  # unseen during fit
        )
        predicted = predict_log_ppm2(model, unseen)
        assert predicted is not None
        assert math.isfinite(predicted)


class TestBuildFeatureRowSemantics:
    def test_top_floor_walkup_column_is_in_design_matrix(self) -> None:
        # Direct introspection — the private encoder must surface this flag.
        features, targets = _synthetic_features(60, seed=7)
        model = fit_hedonic(
            features, targets, group_key=("Praha", "byt", "osobni")
        )
        assert model is not None
        assert "top_floor_walkup" in model.columns
        assert "top_floor_walkup" in model.coef_by_column

    def test_top_floor_walkup_shifts_prediction(self) -> None:
        # Build a fitted model, then evaluate two identical listings whose
        # only difference is the top-floor-walkup flag. The prediction delta
        # must equal the model's coefficient on that column.
        features, targets = _synthetic_features(60, seed=8)
        model = fit_hedonic(
            features, targets, group_key=("Praha", "byt", "osobni")
        )
        assert model is not None

        walkup = HedonicFeatures(
            size_m2=Decimal("60.00"),
            floor_current=5,
            floor_total=5,
            has_lift=False,
            has_balcony=None,
            has_loggia=None,
            has_terrace=None,
            has_cellar=None,
            has_parking=None,
            building_type="cihla",
            disposition="2+kk",
            condition="velmi_dobry",
            year_built=1970,
            energy_class="C",
            city_district="Praha 5",
        )
        not_walkup = HedonicFeatures(
            size_m2=Decimal("60.00"),
            floor_current=2,  # not the top floor → flag off
            floor_total=5,
            has_lift=False,
            has_balcony=None,
            has_loggia=None,
            has_terrace=None,
            has_cellar=None,
            has_parking=None,
            building_type="cihla",
            disposition="2+kk",
            condition="velmi_dobry",
            year_built=1970,
            energy_class="C",
            city_district="Praha 5",
        )
        p_walkup = predict_log_ppm2(model, walkup)
        p_not = predict_log_ppm2(model, not_walkup)
        assert p_walkup is not None and p_not is not None

        # The delta should equal coef(top_floor_walkup) + coef(floor_current) * Δfloor.
        expected_delta = (
            model.coef_by_column["top_floor_walkup"]
            + model.coef_by_column["floor_current"] * (5 - 2)
        )
        assert (p_walkup - p_not) == pytest.approx(expected_delta, rel=1e-6, abs=1e-9)
