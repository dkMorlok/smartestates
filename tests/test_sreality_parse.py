"""Tests for Sreality detail JSON parsing.

Uses a representative fixture modeled on the real Sreality v2 response
shape. Real captures from production go to tests/fixtures/sreality/ later.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from scraper.sources.sreality.parse import parse_sreality_detail
from shared.enums import (
    BuildingType,
    Condition,
    Disposition,
    EnergyClass,
    ListingKind,
    OwnershipType,
    PropertyType,
)


def make_detail(**overrides: object) -> dict:
    """A baseline byty/prodej detail JSON resembling Sreality's v2 shape."""
    base = {
        "name": {"value": "Prodej bytu 2+kk, 56 m², Praha 5 - Smíchov"},
        "meta_description": "2+kk, 56 m², osobní vlastnictví, cihlová stavba",
        "price": 6_950_000,
        "price_czk": {"value_raw": 6_950_000},
        "locality": {"value": "Praha 5 - Smíchov"},
        "gps": {"lat": 50.0721, "lon": 14.4044},
        "seo": {
            "category_main_cb": 1,  # byty
            "category_type_cb": 1,  # prodej
            "locality": "praha-5-smichov",
        },
        "text": {"value": "Krásný byt po rekonstrukci v cihlovém domě..."},
        "items": [
            {"name": "Užitná plocha", "value": 56, "unit": "m²", "type": "integer"},
            {"name": "Stavba", "value": "Cihlová", "type": "string"},
            {"name": "Stav objektu", "value": "Po rekonstrukci", "type": "string"},
            {"name": "Vlastnictví", "value": "Osobní", "type": "string"},
            {"name": "Poschodí", "value": "3. patro z 5", "type": "string"},
            {"name": "Rok kolaudace", "value": 1932, "type": "integer"},
            {"name": "Energetická náročnost budovy", "value": "C", "type": "string"},
            {"name": "Výtah", "value": "ano", "type": "boolean"},
            {"name": "Balkón", "value": "ano", "type": "boolean"},
            {"name": "Sklep", "value": "ano", "type": "boolean"},
            {"name": "Lodžie", "value": "ne", "type": "boolean"},
            {"name": "PSČ", "value": "150 00", "type": "string"},
        ],
        "_embedded": {
            "images": [
                {"_links": {"view": {"href": "https://img.sreality.cz/1.jpg"}}},
            ],
        },
    }
    base.update(overrides)  # type: ignore[arg-type]
    return base


class TestSrealityParse:
    def test_byt_prodej_happy_path(self) -> None:
        d = make_detail()
        p = parse_sreality_detail(
            d,
            hash_id="12345",
            canonical_url="https://www.sreality.cz/detail/prodej/byt/12345",
            fetched_at=datetime(2026, 5, 14, 10, 0, tzinfo=UTC),
        )
        assert p.source_slug == "sreality"
        assert p.source_listing_id == "12345"
        assert p.property_type == PropertyType.BYT
        assert p.listing_kind == ListingKind.PRODEJ
        assert p.price_czk == 6_950_000
        assert p.price_hidden is False
        assert p.usable_area_m2 == 56
        assert p.disposition == Disposition.D_2KK
        assert p.ownership_type == OwnershipType.OSOBNI
        assert p.building_type == BuildingType.CIHLA
        assert p.condition == Condition.PO_REKONSTRUKCI
        assert p.energy_class == EnergyClass.C
        assert p.floor_current == 3
        assert p.floor_total == 5
        assert p.year_built == 1932
        assert p.has_lift is True
        assert p.has_balcony is True
        assert p.has_cellar is True
        assert p.has_loggia is False
        assert p.geo is not None and pytest.approx(p.geo.lat, abs=0.001) == 50.0721
        assert p.postcode == "150 00"

    def test_druzstevni_listing(self) -> None:
        """Critical: druzstevni must not silently become osobni."""
        d = make_detail()
        for it in d["items"]:
            if it["name"] == "Vlastnictví":
                it["value"] = "Družstevní"
        p = parse_sreality_detail(
            d,
            hash_id="22222",
            canonical_url="https://www.sreality.cz/detail/prodej/byt/22222",
        )
        assert p.ownership_type == OwnershipType.DRUZSTEVNI

    def test_hidden_price(self) -> None:
        d = make_detail(price=0, price_czk={"value_raw": 0})
        p = parse_sreality_detail(
            d,
            hash_id="33333",
            canonical_url="https://www.sreality.cz/detail/prodej/byt/33333",
        )
        assert p.price_hidden is True
        assert p.price_czk is None

    def test_unknown_item_goes_to_extras(self) -> None:
        d = make_detail()
        d["items"].append({"name": "Vymyšlený atribut", "value": "neco", "type": "string"})
        p = parse_sreality_detail(
            d,
            hash_id="44444",
            canonical_url="https://www.sreality.cz/detail/prodej/byt/44444",
        )
        assert "Vymyšlený atribut" in p.extra_features.get("unknown_keys", [])

    def test_missing_category_raises(self) -> None:
        d = make_detail()
        del d["seo"]["category_main_cb"]
        with pytest.raises(ValueError, match="category_main_cb"):
            parse_sreality_detail(
                d,
                hash_id="55555",
                canonical_url="https://www.sreality.cz/detail/prodej/byt/55555",
            )

    def test_house_listing_3kk_disposition_from_name(self) -> None:
        d = make_detail(
            name={"value": "Prodej rodinného domu 5+1, 220 m², Říčany"},
        )
        d["seo"]["category_main_cb"] = 2  # dum
        p = parse_sreality_detail(
            d,
            hash_id="66666",
            canonical_url="https://www.sreality.cz/detail/prodej/dum/66666",
        )
        assert p.property_type == PropertyType.DUM
        assert p.disposition == Disposition.D_5_1
