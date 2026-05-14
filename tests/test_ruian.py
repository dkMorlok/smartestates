"""Tests for RÚIAN parsing and projection (scraper/ruian.py).

The spatial lookup (`nearest_ruian_address`) needs PostGIS and is exercised
via the pipeline, not here. These cover the pure pieces: the S-JTSK→WGS84
projection and the OB_ADR CSV contract.
"""
from __future__ import annotations

import pytest
from pyproj import Transformer

from scraper.ruian import (
    COL_KOD_ADM,
    parse_ruian_csv_row,
    read_ruian_csv,
    sjtsk_to_wgs84,
)

# Praha, Staroměstské náměstí — a known point well inside the country.
PRAHA_LAT, PRAHA_LON = 50.0875, 14.4213

_TO_SJTSK = Transformer.from_crs(4326, 5514, always_xy=True)


def _sjtsk(lat: float, lon: float) -> tuple[float, float]:
    """WGS84 → RÚIAN (Souřadnice X, Souřadnice Y) in S-JTSK."""
    easting, northing = _TO_SJTSK.transform(lon, lat)
    return northing, easting  # CSV order: X = northing, Y = easting


_HEADER = (
    "Kód ADM;Kód obce;Název obce;Kód MOMC;Název MOMC;Kód obvodu Prahy;"
    "Název obvodu Prahy;Kód části obce;Název části obce;Kód ulice;Název ulice;"
    "Typ SO;Číslo domovní;Číslo orientační;Znak čísla orientačního;PSČ;"
    "Souřadnice Y;Souřadnice X;Platí Od"
)


def _csv_row(
    *,
    kod_adm: str = "21745671",
    x: float | None = None,
    y: float | None = None,
    cislo_orientacni: str = "175",
    znak: str = "",
) -> str:
    if x is None or y is None:
        x, y = _sjtsk(PRAHA_LAT, PRAHA_LON)
    return (
        f"{kod_adm};554782;Praha;500054;Praha 2;;;490067;Vinohrady;"
        f"724topo;Vinohradská;č.p.;2128;{cislo_orientacni};{znak};12000;"
        f"{y};{x};2026-01-01"
    )


class TestProjection:
    def test_roundtrip_praha(self) -> None:
        x, y = _sjtsk(PRAHA_LAT, PRAHA_LON)
        lat, lon = sjtsk_to_wgs84(x, y)
        assert lat == pytest.approx(PRAHA_LAT, abs=1e-5)
        assert lon == pytest.approx(PRAHA_LON, abs=1e-5)

    def test_result_lands_in_czechia(self) -> None:
        x, y = _sjtsk(49.5, 15.5)  # roughly the centre of the country
        lat, lon = sjtsk_to_wgs84(x, y)
        assert 48.5 <= lat <= 51.1
        assert 12.0 <= lon <= 18.9


class TestParseRow:
    def _row(self, line: str) -> dict[str, str]:
        import csv
        import io

        reader = csv.DictReader(io.StringIO(f"{_HEADER}\n{line}"), delimiter=";")
        return next(iter(reader))

    def test_happy_path(self) -> None:
        addr = parse_ruian_csv_row(self._row(_csv_row()))
        assert addr is not None
        assert addr.kod_adm == "21745671"
        assert addr.nazev_obce == "Praha"
        assert addr.nazev_momc == "Praha 2"
        assert addr.nazev_casti_obce == "Vinohrady"
        assert addr.nazev_ulice == "Vinohradská"
        assert addr.cislo_domovni == "2128"
        assert addr.cislo_orientacni == "175"
        assert addr.psc == "12000"
        assert addr.lat == pytest.approx(PRAHA_LAT, abs=1e-4)
        assert addr.lon == pytest.approx(PRAHA_LON, abs=1e-4)

    def test_orientacni_znak_is_appended(self) -> None:
        addr = parse_ruian_csv_row(self._row(_csv_row(cislo_orientacni="12", znak="a")))
        assert addr is not None
        assert addr.cislo_orientacni == "12a"

    def test_missing_coords_returns_none(self) -> None:
        line = _csv_row()
        # Blank out both coordinate columns (last two before the date).
        parts = line.split(";")
        parts[16] = ""  # Souřadnice Y
        parts[17] = ""  # Souřadnice X
        addr = parse_ruian_csv_row(self._row(";".join(parts)))
        assert addr is None

    def test_missing_kod_adm_returns_none(self) -> None:
        addr = parse_ruian_csv_row(self._row(_csv_row(kod_adm="")))
        assert addr is None


class TestReadCsv:
    def test_reads_multiple_rows(self) -> None:
        x, y = _sjtsk(PRAHA_LAT, PRAHA_LON)
        blob = "\n".join(
            [
                _HEADER,
                _csv_row(kod_adm="111", x=x, y=y),
                _csv_row(kod_adm="222", x=x, y=y),
            ]
        ).encode("cp1250")
        addrs = list(read_ruian_csv(blob))
        assert [a.kod_adm for a in addrs] == ["111", "222"]

    def test_skips_unusable_rows(self) -> None:
        good = _csv_row(kod_adm="111")
        bad = _csv_row(kod_adm="")  # no kod_adm → skipped
        blob = "\n".join([_HEADER, good, bad]).encode("cp1250")
        addrs = list(read_ruian_csv(blob))
        assert [a.kod_adm for a in addrs] == ["111"]

    def test_bad_header_raises(self) -> None:
        blob = b"not;the;right;header\n1;2;3;4"
        with pytest.raises(ValueError, match=COL_KOD_ADM):
            list(read_ruian_csv(blob))

    def test_handles_cp1250_diacritics(self) -> None:
        blob = "\n".join([_HEADER, _csv_row()]).encode("cp1250")
        addrs = list(read_ruian_csv(blob))
        assert addrs[0].nazev_ulice == "Vinohradská"
