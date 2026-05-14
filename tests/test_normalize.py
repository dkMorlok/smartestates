"""Tests for CZ-specific normalization.

This is the highest-risk code: every CZ real estate analytics tool ships
the družstevní bug at least once. These tests guard the boundaries.
"""
from __future__ import annotations

import pytest

from shared.enums import (
    BuildingType,
    Condition,
    Disposition,
    EnergyClass,
    OwnershipType,
)
from shared.normalize import (
    normalize_address,
    normalize_for_match,
    parse_building_type,
    parse_condition,
    parse_disposition,
    parse_energy_class,
    parse_floor,
    parse_house_number,
    parse_ownership,
    praha_district_from_postcode,
    strip_diacritics,
)


class TestDiacritics:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("Náměstí Míru", "Namesti Miru"),
            ("Příkopy", "Prikopy"),
            ("ŽIŽKOV", "ZIZKOV"),
            ("plain ascii", "plain ascii"),
            ("", ""),
        ],
    )
    def test_strip_diacritics(self, raw: str, expected: str) -> None:
        assert strip_diacritics(raw) == expected

    def test_normalize_for_match_lowercases_and_collapses(self) -> None:
        assert normalize_for_match("  Náměstí   Míru  ") == "namesti miru"


class TestDisposition:
    @pytest.mark.parametrize(
        "text, expected",
        [
            ("Prodej bytu 2+kk, 56 m²", Disposition.D_2KK),
            ("Byt 3 + 1", Disposition.D_3_1),
            ("3+kk Praha 5", Disposition.D_3KK),
            ("garsoniéra 25m2", Disposition.GARSONIERA),
            ("Garsoniera 22m2", Disposition.GARSONIERA),
            ("1+1, 38 m², Vinohrady", Disposition.D_1_1),
            ("Atypický byt 90m2", Disposition.ATYPICKY),
            ("7+kk velký dům", Disposition.D_6_PLUS),
            ("", None),
            (None, None),
            ("dům bez dispozice", None),
        ],
    )
    def test_parse_disposition(self, text: str | None, expected: Disposition | None) -> None:
        assert parse_disposition(text) == expected

    def test_no_false_positive_in_size(self) -> None:
        # '2+1' is the disposition, not '21'
        assert parse_disposition("Cena 2 100 000 Kč") is None


class TestOwnership:
    """The single most important test in this codebase.

    Misclassifying družstevní as osobní (or worse, treating them as the same
    segment) is the highest-impact bug we can ship.
    """

    @pytest.mark.parametrize(
        "text, expected",
        [
            ("Osobní", OwnershipType.OSOBNI),
            ("osobní vlastnictví", OwnershipType.OSOBNI),
            ("OV", OwnershipType.OSOBNI),
            ("Družstevní", OwnershipType.DRUZSTEVNI),
            ("družstevní vlastnictví", OwnershipType.DRUZSTEVNI),
            ("DV", OwnershipType.DRUZSTEVNI),
            ("druzstevni", OwnershipType.DRUZSTEVNI),  # no diacritics
            ("Státní", OwnershipType.STATNI),
            ("obecní", OwnershipType.STATNI),
            ("", None),
            (None, None),
            ("nějaký nesmysl", None),
        ],
    )
    def test_parse_ownership(self, text: str | None, expected: OwnershipType | None) -> None:
        assert parse_ownership(text) == expected

    def test_osobni_and_druzstevni_are_never_equal(self) -> None:
        """The bedrock guarantee."""
        assert parse_ownership("Osobní") != parse_ownership("Družstevní")


class TestBuildingType:
    @pytest.mark.parametrize(
        "text, expected",
        [
            ("panelová", BuildingType.PANEL),
            ("Panelový dům", BuildingType.PANEL),
            ("cihla", BuildingType.CIHLA),
            ("Cihlová", BuildingType.CIHLA),
            ("smíšená konstrukce", BuildingType.SMISENA),
            ("dřevěný srub", BuildingType.DREVO),
            ("kamenný", BuildingType.KAMEN),
            ("ostatní", BuildingType.OSTATNI),
            ("", None),
            (None, None),
        ],
    )
    def test_parse_building_type(self, text: str | None, expected: BuildingType | None) -> None:
        assert parse_building_type(text) == expected


class TestCondition:
    @pytest.mark.parametrize(
        "text, expected",
        [
            ("Novostavba", Condition.NOVOSTAVBA),
            ("Velmi dobrý", Condition.VELMI_DOBRY),
            ("Dobrý stav", Condition.DOBRY),
            ("v rekonstrukci", Condition.V_REKONSTRUKCI),
            ("Po rekonstrukci", Condition.PO_REKONSTRUKCI),
            ("Před rekonstrukcí", Condition.PRED_REKONSTRUKCI),
            ("Špatný", Condition.SPATNY),
            ("Projekt", Condition.PROJEKT),
            ("", None),
        ],
    )
    def test_parse_condition(self, text: str, expected: Condition | None) -> None:
        assert parse_condition(text) == expected


class TestEnergyClass:
    @pytest.mark.parametrize(
        "text, expected",
        [
            ("B", EnergyClass.B),
            ("class g", EnergyClass.G),
            ("Třída B - úsporná", EnergyClass.B),
            ("nezadáno", None),
            ("", None),
            (None, None),
        ],
    )
    def test_parse_energy_class(self, text: str | None, expected: EnergyClass | None) -> None:
        assert parse_energy_class(text) == expected


class TestFloor:
    def test_x_of_y(self) -> None:
        info = parse_floor("2. patro z 5")
        assert info.current == 2
        assert info.total == 5

    def test_slash(self) -> None:
        info = parse_floor("4/5")
        assert info.current == 4
        assert info.total == 5

    def test_ground(self) -> None:
        info = parse_floor("Přízemí")
        assert info.current == 0
        assert info.total is None

    def test_raised_ground(self) -> None:
        info = parse_floor("Zvýšené přízemí")
        assert info.current == 0

    def test_int_only(self) -> None:
        info = parse_floor("3")
        assert info.current == 3
        assert info.total is None

    def test_empty(self) -> None:
        info = parse_floor(None)
        assert info.current is None and info.total is None


class TestAddress:
    def test_normalize_address_abbreviations(self) -> None:
        assert normalize_address("ul. Vinohradská") == "ulice Vinohradská"
        assert normalize_address("nám. Míru") == "naměsti Míru"
        assert normalize_address("tř. Svobody 12") == "třida Svobody 12"

    def test_normalize_collapses_whitespace(self) -> None:
        assert normalize_address("  ulice  Václavské   ") == "ulice Václavské"

    def test_parse_house_number_both(self) -> None:
        hn = parse_house_number("Vinohradská 2128/175")
        assert hn.popisne == "2128"
        assert hn.orientacni == "175"

    def test_parse_house_number_with_letter(self) -> None:
        hn = parse_house_number("Husova 12/3a")
        assert hn.popisne == "12"
        assert hn.orientacni == "3a"

    def test_parse_house_number_none(self) -> None:
        hn = parse_house_number("Vinohradská")
        assert hn.popisne is None and hn.orientacni is None


class TestPrahaPostcode:
    @pytest.mark.parametrize(
        "pc, expected",
        [
            ("11000", "Praha 1"),
            ("12000", "Praha 2"),
            ("13000", "Praha 3"),
            ("190 00", "Praha 9"),  # space tolerated via .replace
            ("60200", None),  # Brno
            ("", None),
            (None, None),
        ],
    )
    def test_district_from_postcode(self, pc: str | None, expected: str | None) -> None:
        assert praha_district_from_postcode(pc) == expected
