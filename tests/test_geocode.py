"""Tests for the geocoding core (scraper/geocode.py).

Pure-function coverage: bounding-box checks, Nominatim response
interpretation, the resolve_location decision tree, and property linking.
Nominatim is exercised via an in-memory fake — no network.
"""
from __future__ import annotations

from typing import Any

from scraper.geocode import (
    PRAHA_BBOX,
    BBox,
    GeocodeResult,
    PropertyCandidate,
    choose_property_link,
    classify_nominatim_precision,
    resolve_location,
)
from shared.enums import AddressPrecision

# A point in Smíchov, Praha 5 — inside PRAHA_BBOX.
PRAHA_LAT, PRAHA_LON = 50.0721, 14.4044
# Brno — well outside PRAHA_BBOX.
BRNO_LAT, BRNO_LON = 49.1951, 16.6068


class FakeNominatim:
    """Stand-in for NominatimClient with canned reverse/search responses."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        reverse_result: dict[str, Any] | None = None,
        search_result: dict[str, Any] | None = None,
    ) -> None:
        self._enabled = enabled
        self._reverse = reverse_result
        self._search = search_result

    @property
    def enabled(self) -> bool:
        return self._enabled

    def reverse(self, lat: float, lon: float) -> dict[str, Any] | None:
        return self._reverse

    def search(self, **kwargs: Any) -> dict[str, Any] | None:
        return self._search


class FakeRuianMatch:
    """Structurally satisfies geocode.RuianMatch."""

    def __init__(
        self,
        *,
        kod_adm: str = "21745671",
        nazev_momc: str | None = "Praha 5",
        nazev_casti_obce: str | None = "Smíchov",
        psc: str | None = "150 00",
    ) -> None:
        self.kod_adm = kod_adm
        self.nazev_momc = nazev_momc
        self.nazev_casti_obce = nazev_casti_obce
        self.psc = psc


class TestBBox:
    def test_contains_inside(self) -> None:
        assert PRAHA_BBOX.contains(PRAHA_LAT, PRAHA_LON) is True

    def test_contains_outside(self) -> None:
        assert PRAHA_BBOX.contains(BRNO_LAT, BRNO_LON) is False

    def test_contains_on_edge(self) -> None:
        box = BBox(min_lat=0.0, max_lat=1.0, min_lon=0.0, max_lon=1.0)
        assert box.contains(0.0, 1.0) is True


class TestClassifyPrecision:
    def test_building_addresstype_is_rooftop(self) -> None:
        r = {"addresstype": "building", "address": {}}
        assert classify_nominatim_precision(r) == AddressPrecision.ROOFTOP

    def test_house_number_is_rooftop(self) -> None:
        r = {"addresstype": "place", "address": {"house_number": "2128/175", "road": "x"}}
        assert classify_nominatim_precision(r) == AddressPrecision.ROOFTOP

    def test_road_only_is_street(self) -> None:
        r = {"addresstype": "road", "address": {"road": "Vinohradská"}}
        assert classify_nominatim_precision(r) == AddressPrecision.STREET

    def test_nothing_is_locality(self) -> None:
        r = {"addresstype": "city", "address": {"city": "Praha"}}
        assert classify_nominatim_precision(r) == AddressPrecision.LOCALITY


class TestResolveLocation:
    def test_source_gps_inside_bbox_no_nominatim(self) -> None:
        res = resolve_location(
            source_geo={"lat": PRAHA_LAT, "lon": PRAHA_LON},
            locality="Praha 5 - Smíchov",
        )
        assert res.precision == AddressPrecision.SOURCE_GPS
        assert res.has_point is True
        assert res.linkable is True
        assert res.lat == PRAHA_LAT

    def test_source_gps_outside_bbox_falls_through(self) -> None:
        # GPS for Brno on a "Praha" listing — must not be trusted.
        res = resolve_location(
            source_geo={"lat": BRNO_LAT, "lon": BRNO_LON},
            locality="Praha 5",
        )
        assert res.precision == AddressPrecision.LOCALITY
        assert res.has_point is False
        assert res.linkable is False

    def test_source_gps_enriched_by_nominatim(self) -> None:
        nominatim = FakeNominatim(
            reverse_result={
                "addresstype": "building",
                "address": {"city_district": "Praha 5", "postcode": "150 00"},
                "extratags": {"ref:ruian:addr": "21731451"},
                "display_name": "Plzeňská 123, Praha 5",
            }
        )
        res = resolve_location(
            source_geo={"lat": PRAHA_LAT, "lon": PRAHA_LON},
            locality="Praha 5 - Smíchov",
            nominatim=nominatim,  # type: ignore[arg-type]
        )
        assert res.precision == AddressPrecision.ROOFTOP
        assert res.ruian_address_code == "21731451"
        assert res.city_district == "Praha 5"
        assert res.note == "source_gps+nominatim"

    def test_ruian_lookup_upgrades_to_rooftop(self) -> None:
        res = resolve_location(
            source_geo={"lat": PRAHA_LAT, "lon": PRAHA_LON},
            locality="Praha 5 - Smíchov",
            ruian_lookup=lambda lat, lon: FakeRuianMatch(),  # type: ignore[arg-type,return-value]
        )
        assert res.precision == AddressPrecision.ROOFTOP
        assert res.ruian_address_code == "21745671"
        assert res.city_district == "Praha 5"
        assert res.cadastral_area == "Smíchov"
        assert res.note == "source_gps+ruian"

    def test_ruian_takes_priority_over_nominatim(self) -> None:
        # RÚIAN hit short-circuits — Nominatim must not even be consulted.
        nominatim = FakeNominatim(reverse_result={"addresstype": "city", "address": {}})
        res = resolve_location(
            source_geo={"lat": PRAHA_LAT, "lon": PRAHA_LON},
            ruian_lookup=lambda lat, lon: FakeRuianMatch(),  # type: ignore[arg-type,return-value]
            nominatim=nominatim,  # type: ignore[arg-type]
        )
        assert res.note == "source_gps+ruian"
        assert res.precision == AddressPrecision.ROOFTOP

    def test_ruian_miss_falls_back_to_nominatim(self) -> None:
        nominatim = FakeNominatim(
            reverse_result={"addresstype": "building", "address": {}, "extratags": {}}
        )
        res = resolve_location(
            source_geo={"lat": PRAHA_LAT, "lon": PRAHA_LON},
            ruian_lookup=lambda lat, lon: None,
            nominatim=nominatim,  # type: ignore[arg-type]
        )
        assert res.note == "source_gps+nominatim"
        assert res.precision == AddressPrecision.ROOFTOP

    def test_forward_geocode_when_no_source_gps(self) -> None:
        nominatim = FakeNominatim(
            search_result={
                "lat": str(PRAHA_LAT),
                "lon": str(PRAHA_LON),
                "addresstype": "building",
                "address": {"house_number": "175", "road": "Vinohradská"},
                "extratags": {},
            }
        )
        res = resolve_location(
            source_geo=None,
            address_raw="Vinohradská 175",
            locality="Praha 2",
            nominatim=nominatim,  # type: ignore[arg-type]
        )
        assert res.precision == AddressPrecision.ROOFTOP
        assert res.has_point is True
        assert res.note == "nominatim_forward"

    def test_forward_geocode_result_outside_bbox_rejected(self) -> None:
        nominatim = FakeNominatim(
            search_result={"lat": str(BRNO_LAT), "lon": str(BRNO_LON), "address": {}}
        )
        res = resolve_location(
            source_geo=None,
            address_raw="Náměstí Svobody",
            locality="Brno",
            nominatim=nominatim,  # type: ignore[arg-type]
        )
        assert res.precision == AddressPrecision.LOCALITY
        assert res.has_point is False

    def test_no_hints_at_all_is_locality(self) -> None:
        res = resolve_location(source_geo=None)
        assert res.precision == AddressPrecision.LOCALITY
        assert res.linkable is False
        assert res.note == "unresolved"

    def test_city_district_from_postcode_fallback(self) -> None:
        res = resolve_location(
            source_geo={"lat": PRAHA_LAT, "lon": PRAHA_LON},
            postcode="12000",
        )
        assert res.city_district == "Praha 2"

    def test_malformed_source_geo_ignored(self) -> None:
        res = resolve_location(source_geo={"lat": "not-a-number", "lon": PRAHA_LON})
        assert res.precision == AddressPrecision.LOCALITY


def _result(
    *,
    ruian: str | None = None,
    addr: str | None = None,
) -> GeocodeResult:
    return GeocodeResult(
        precision=AddressPrecision.SOURCE_GPS,
        lat=PRAHA_LAT,
        lon=PRAHA_LON,
        address_normalized=addr,
        ruian_address_code=ruian,
    )


class TestChoosePropertyLink:
    def test_ruian_exact_match_wins(self) -> None:
        candidates = [
            PropertyCandidate(7, 12.0, "Plzenska 123", "21731451"),
        ]
        decision = choose_property_link(_result(ruian="21731451"), candidates)
        assert decision.property_id == 7
        assert decision.method == "ruian_exact"

    def test_within_3m_same_address(self) -> None:
        candidates = [
            PropertyCandidate(9, 2.4, "Plzeňská 123", None),
        ]
        decision = choose_property_link(
            _result(addr="Plzeňská 123"), candidates
        )
        assert decision.property_id == 9
        assert decision.method == "geo_3m_addr"

    def test_within_30m_fuzzy_address(self) -> None:
        candidates = [
            PropertyCandidate(11, 18.0, "Plzenska 123", None),
        ]
        decision = choose_property_link(
            _result(addr="Plzenska 124"), candidates
        )
        assert decision.property_id == 11
        assert decision.method == "geo_30m_fuzzy"

    def test_far_away_creates_new(self) -> None:
        candidates = [
            PropertyCandidate(13, 80.0, "Some Other Street 1", None),
        ]
        decision = choose_property_link(_result(addr="Plzeňská 123"), candidates)
        assert decision.property_id is None
        assert decision.method == "new"

    def test_no_candidates_creates_new(self) -> None:
        decision = choose_property_link(_result(addr="Plzeňská 123"), [])
        assert decision.property_id is None
        assert decision.method == "new"

    def test_fuzzy_too_different_creates_new(self) -> None:
        candidates = [
            PropertyCandidate(15, 10.0, "Completely Different 999", None),
        ]
        decision = choose_property_link(_result(addr="Plzeňská 123"), candidates)
        assert decision.property_id is None
        assert decision.method == "new"
