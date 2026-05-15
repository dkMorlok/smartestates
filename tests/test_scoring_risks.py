"""Tests for the risk-flag evaluation module."""
from __future__ import annotations

from decimal import Decimal

import pytest

from scoring.risks import (
    MAX_SUM_FOR_100,
    SEVERITY_WEIGHT,
    RiskInputs,
    SegmentRefs,
    evaluate_risk_flags,
    risk_score,
)


def _baseline_inputs(**kw) -> RiskInputs:
    base = {
        "price": Decimal("8_000_000"),
        "size_m2": Decimal("70"),
        "ownership_type": "osobni",
        "building_type": "cihla",
        "year_built": 2015,
        "floor_current": 2,
        "floor_total": 5,
        "has_lift": True,
        "energy_class": "B",
        "photo_count": 10,
        "description": "Hezký byt v centru.",
    }
    base.update(kw)
    return RiskInputs(**base)


def _baseline_refs(**kw) -> SegmentRefs:
    base = {"ppm2_median": 120_000.0, "ppm2_p25": 100_000.0}
    base.update(kw)
    return SegmentRefs(**base)


class TestPriceTooLow:
    def test_below_threshold_triggers(self) -> None:
        # ppm2 = 4_000_000/70 ≈ 57_142; threshold = 0.6 * 100_000 = 60_000.
        flags = evaluate_risk_flags(
            _baseline_inputs(price=Decimal("4_000_000")),
            _baseline_refs(),
        )
        assert "price_too_low" in flags

    def test_above_threshold_no_flag(self) -> None:
        flags = evaluate_risk_flags(_baseline_inputs(), _baseline_refs())
        assert "price_too_low" not in flags

    def test_p25_none_no_flag(self) -> None:
        flags = evaluate_risk_flags(
            _baseline_inputs(price=Decimal("4_000_000")),
            _baseline_refs(ppm2_p25=None),
        )
        assert "price_too_low" not in flags

    def test_missing_price_no_flag(self) -> None:
        flags = evaluate_risk_flags(
            _baseline_inputs(price=None),
            _baseline_refs(),
        )
        assert "price_too_low" not in flags


class TestLegalEncumbrance:
    def test_exekuce_triggers(self) -> None:
        flags = evaluate_risk_flags(
            _baseline_inputs(description="Na bytě je exekuce."),
            _baseline_refs(),
        )
        assert "legal_encumbrance" in flags

    def test_bremen_triggers(self) -> None:
        flags = evaluate_risk_flags(
            _baseline_inputs(description="Žádné břemeno."),
            _baseline_refs(),
        )
        assert "legal_encumbrance" in flags

    def test_clean_description_no_flag(self) -> None:
        flags = evaluate_risk_flags(
            _baseline_inputs(description="Pěkný byt."),
            _baseline_refs(),
        )
        assert "legal_encumbrance" not in flags

    def test_none_description_no_flag(self) -> None:
        flags = evaluate_risk_flags(
            _baseline_inputs(description=None),
            _baseline_refs(),
        )
        assert "legal_encumbrance" not in flags

    def test_case_insensitive(self) -> None:
        flags = evaluate_risk_flags(
            _baseline_inputs(description="EXEKUC NA NEMOVITOSTI"),
            _baseline_refs(),
        )
        assert "legal_encumbrance" in flags


class TestDruzstevniMismarked:
    def test_unknown_ownership_low_price_triggers(self) -> None:
        # median price = 120_000 * 70 = 8_400_000; 0.85 * = 7_140_000.
        flags = evaluate_risk_flags(
            _baseline_inputs(ownership_type=None, price=Decimal("6_000_000")),
            _baseline_refs(),
        )
        assert "druzstevni_mismarked" in flags

    def test_already_marked_druzstevni_no_flag(self) -> None:
        flags = evaluate_risk_flags(
            _baseline_inputs(ownership_type="druzstevni", price=Decimal("6_000_000")),
            _baseline_refs(),
        )
        assert "druzstevni_mismarked" not in flags

    def test_unknown_ownership_at_median_no_flag(self) -> None:
        # price 8_400_000 == median exactly → not < 0.85 * median.
        flags = evaluate_risk_flags(
            _baseline_inputs(ownership_type=None, price=Decimal("8_400_000")),
            _baseline_refs(),
        )
        assert "druzstevni_mismarked" not in flags


class TestPanelCapexDue:
    def test_old_panel_without_revitaliz_triggers(self) -> None:
        flags = evaluate_risk_flags(
            _baseline_inputs(
                building_type="panel",
                year_built=1975,
                description="Pěkný byt v centru.",
            ),
            _baseline_refs(),
        )
        assert "panel_capex_due" in flags

    def test_revitalizace_in_description_no_flag(self) -> None:
        flags = evaluate_risk_flags(
            _baseline_inputs(
                building_type="panel",
                year_built=1975,
                description="Po revitalizaci v roce 2020.",
            ),
            _baseline_refs(),
        )
        assert "panel_capex_due" not in flags

    def test_cihla_no_flag(self) -> None:
        flags = evaluate_risk_flags(
            _baseline_inputs(building_type="cihla", year_built=1975),
            _baseline_refs(),
        )
        assert "panel_capex_due" not in flags

    def test_panel_outside_year_range_no_flag(self) -> None:
        flags = evaluate_risk_flags(
            _baseline_inputs(building_type="panel", year_built=2005),
            _baseline_refs(),
        )
        assert "panel_capex_due" not in flags


class TestTopFloorNoLift:
    def test_top_floor_no_lift_triggers(self) -> None:
        flags = evaluate_risk_flags(
            _baseline_inputs(
                floor_current=5,
                floor_total=5,
                has_lift=False,
            ),
            _baseline_refs(),
        )
        assert "top_floor_no_lift" in flags

    def test_has_lift_no_flag(self) -> None:
        flags = evaluate_risk_flags(
            _baseline_inputs(
                floor_current=5,
                floor_total=5,
                has_lift=True,
            ),
            _baseline_refs(),
        )
        assert "top_floor_no_lift" not in flags

    def test_unknown_lift_no_flag(self) -> None:
        flags = evaluate_risk_flags(
            _baseline_inputs(
                floor_current=5,
                floor_total=5,
                has_lift=None,
            ),
            _baseline_refs(),
        )
        assert "top_floor_no_lift" not in flags

    def test_total_three_no_flag(self) -> None:
        flags = evaluate_risk_flags(
            _baseline_inputs(
                floor_current=3,
                floor_total=3,
                has_lift=False,
            ),
            _baseline_refs(),
        )
        assert "top_floor_no_lift" not in flags


class TestClassGEnergy:
    def test_g_triggers(self) -> None:
        flags = evaluate_risk_flags(
            _baseline_inputs(energy_class="G"),
            _baseline_refs(),
        )
        assert "class_g_energy" in flags

    def test_f_triggers(self) -> None:
        flags = evaluate_risk_flags(
            _baseline_inputs(energy_class="F"),
            _baseline_refs(),
        )
        assert "class_g_energy" in flags

    def test_lowercase_g_triggers(self) -> None:
        flags = evaluate_risk_flags(
            _baseline_inputs(energy_class="g"),
            _baseline_refs(),
        )
        assert "class_g_energy" in flags

    def test_c_no_flag(self) -> None:
        flags = evaluate_risk_flags(
            _baseline_inputs(energy_class="C"),
            _baseline_refs(),
        )
        assert "class_g_energy" not in flags

    def test_none_no_flag(self) -> None:
        flags = evaluate_risk_flags(
            _baseline_inputs(energy_class=None),
            _baseline_refs(),
        )
        assert "class_g_energy" not in flags


class TestPhotoCountLow:
    def test_three_triggers(self) -> None:
        flags = evaluate_risk_flags(
            _baseline_inputs(photo_count=3),
            _baseline_refs(),
        )
        assert "photo_count_low" in flags

    def test_four_no_flag(self) -> None:
        flags = evaluate_risk_flags(
            _baseline_inputs(photo_count=4),
            _baseline_refs(),
        )
        assert "photo_count_low" not in flags

    def test_none_no_flag(self) -> None:
        flags = evaluate_risk_flags(
            _baseline_inputs(photo_count=None),
            _baseline_refs(),
        )
        assert "photo_count_low" not in flags


class TestDescriptionKeywords:
    def test_havarijni_stav_triggers(self) -> None:
        flags = evaluate_risk_flags(
            _baseline_inputs(description="Havarijní stav, k demolici."),
            _baseline_refs(),
        )
        assert "description_keywords" in flags

    def test_clean_description_no_flag(self) -> None:
        flags = evaluate_risk_flags(
            _baseline_inputs(description="Krásný a obyvatelný."),
            _baseline_refs(),
        )
        assert "description_keywords" not in flags

    def test_neobyvatelny_triggers(self) -> None:
        flags = evaluate_risk_flags(
            _baseline_inputs(description="Byt je bohužel neobyvatelný."),
            _baseline_refs(),
        )
        assert "description_keywords" in flags


class TestEvaluateRiskFlags:
    def test_baseline_no_flags(self) -> None:
        flags = evaluate_risk_flags(_baseline_inputs(), _baseline_refs())
        assert flags == []

    def test_multiple_triggers_in_fixed_order(self) -> None:
        # Stack: price_too_low + class_g_energy + photo_count_low.
        flags = evaluate_risk_flags(
            _baseline_inputs(
                price=Decimal("4_000_000"),
                energy_class="G",
                photo_count=2,
            ),
            _baseline_refs(),
        )
        assert flags == ["price_too_low", "class_g_energy", "photo_count_low"]


class TestRiskScore:
    def test_empty_returns_zero(self) -> None:
        assert risk_score([]) == 0.0

    def test_single_low_severity(self) -> None:
        # class_g_energy weight 1.0 → 100 * (1.0/8.0) = 12.5.
        assert risk_score(["class_g_energy"]) == pytest.approx(12.5, abs=1e-6)

    def test_mix_above_max_caps_at_100(self) -> None:
        # 3 + 3 + 2 + 1 = 9.0 → 112.5 → capped at 100.
        flags = [
            "price_too_low",
            "legal_encumbrance",
            "panel_capex_due",
            "class_g_energy",
        ]
        assert risk_score(flags) == 100.0

    def test_all_high_severity_caps_at_100(self) -> None:
        flags = ["price_too_low", "legal_encumbrance", "druzstevni_mismarked"]
        assert risk_score(flags) == 100.0

    def test_unknown_flag_contributes_zero(self) -> None:
        assert risk_score(["totally_made_up"]) == 0.0


class TestSeverityTable:
    def test_contains_all_expected_flags(self) -> None:
        expected = {
            "price_too_low",
            "legal_encumbrance",
            "druzstevni_mismarked",
            "panel_capex_due",
            "top_floor_no_lift",
            "class_g_energy",
            "photo_count_low",
            "description_keywords",
        }
        assert set(SEVERITY_WEIGHT.keys()) == expected

    def test_high_severity_weights(self) -> None:
        assert SEVERITY_WEIGHT["price_too_low"] == 3.0
        assert SEVERITY_WEIGHT["legal_encumbrance"] == 3.0
        assert SEVERITY_WEIGHT["druzstevni_mismarked"] == 3.0

    def test_max_sum_for_100(self) -> None:
        assert MAX_SUM_FOR_100 == 8.0
