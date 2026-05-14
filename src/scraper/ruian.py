"""RÚIAN address-point parsing, projection, and lookup.

RÚIAN (Registr územní identifikace, adres a nemovitostí) is the official CZ
address registry, published by ČÚZK. Its bulk "OB_ADR" CSV export gives every
address place with S-JTSK coordinates. We import it into `ruian_address` and
use it during geocoding to resolve a source GPS coordinate to a building.

This module owns:
  - the CSV column contract + row parsing
  - the S-JTSK (EPSG:5514) → WGS84 (EPSG:4326) projection
  - the nearest-address spatial lookup used by the geocode stage

The seeding entrypoint is scripts/seed_ruian.py.
"""
from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from shared.logging import get_logger

log = get_logger("scraper.ruian")

# MVP is Praha-only. ČÚZK keys per-obec CSV files by the obec code; Praha is
# a single obec. Add entries here to widen coverage.
PRAHA_OBEC_CODE = "554782"
REGION_TO_OBEC_CODE: dict[str, str] = {"praha": PRAHA_OBEC_CODE}

# The OB_ADR CSV is Windows-1250 encoded and semicolon-delimited.
RUIAN_CSV_ENCODING = "cp1250"
RUIAN_CSV_DELIMITER = ";"

# Column headers, exactly as they appear in the ČÚZK export.
COL_KOD_ADM = "Kód ADM"
COL_KOD_OBCE = "Kód obce"
COL_NAZEV_OBCE = "Název obce"
COL_NAZEV_MOMC = "Název MOMC"
COL_NAZEV_CAST_OBCE = "Název části obce"
COL_NAZEV_ULICE = "Název ulice"
COL_CISLO_DOMOVNI = "Číslo domovní"
COL_CISLO_ORIENTACNI = "Číslo orientační"
COL_ZNAK_ORIENTACNI = "Znak čísla orientačního"
COL_PSC = "PSČ"
COL_SOURADNICE_X = "Souřadnice X"
COL_SOURADNICE_Y = "Souřadnice Y"


@dataclass(frozen=True)
class RuianAddress:
    """One RÚIAN address place, projected to WGS84."""

    kod_adm: str
    kod_obce: str
    nazev_obce: str
    nazev_momc: str | None
    nazev_casti_obce: str | None
    nazev_ulice: str | None
    cislo_domovni: str | None
    cislo_orientacni: str | None
    psc: str | None
    lat: float
    lon: float


# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------

# Lazily built — pyproj transformer construction is not free, and importing
# this module must stay cheap (it's imported by the geocode path).
_TRANSFORMER: Any = None


def _transformer() -> Any:
    global _TRANSFORMER
    if _TRANSFORMER is None:
        from pyproj import Transformer

        # EPSG:5514 = S-JTSK / Krovak East North. always_xy → (easting, northing).
        _TRANSFORMER = Transformer.from_crs(5514, 4326, always_xy=True)
    return _TRANSFORMER


def sjtsk_to_wgs84(x: float, y: float) -> tuple[float, float]:
    """Project a RÚIAN coordinate pair to (lat, lon) in WGS84.

    `x` and `y` are the RÚIAN CSV's "Souřadnice X" / "Souřadnice Y" — S-JTSK
    (EPSG:5514), both negative over Czechia. In S-JTSK East-North the easting
    is "Y" and the northing is "X", so we feed the transformer (y, x).
    """
    lon, lat = _transformer().transform(y, x)
    return float(lat), float(lon)


# ---------------------------------------------------------------------------
# CSV parsing
# ---------------------------------------------------------------------------


def _clean(value: str | None) -> str | None:
    """Trim, and treat empty strings as missing."""
    if value is None:
        return None
    v = value.strip()
    return v or None


def _to_float(value: str | None) -> float | None:
    v = _clean(value)
    if v is None:
        return None
    # ČÚZK uses a dot decimal separator, but be tolerant of a comma.
    try:
        return float(v.replace(",", "."))
    except ValueError:
        return None


def parse_ruian_csv_row(row: dict[str, str]) -> RuianAddress | None:
    """Parse one OB_ADR CSV row. Returns None when it has no usable coordinates.

    Raises KeyError only if the header is missing required columns — the
    caller treats that as a malformed file.
    """
    kod_adm = _clean(row[COL_KOD_ADM])
    if kod_adm is None:
        return None

    x = _to_float(row.get(COL_SOURADNICE_X))
    y = _to_float(row.get(COL_SOURADNICE_Y))
    if x is None or y is None:
        # Address places without coordinates exist but are useless to us.
        return None

    lat, lon = sjtsk_to_wgs84(x, y)

    cislo_orientacni = _clean(row.get(COL_CISLO_ORIENTACNI))
    znak = _clean(row.get(COL_ZNAK_ORIENTACNI))
    if cislo_orientacni is not None and znak is not None:
        cislo_orientacni = f"{cislo_orientacni}{znak}"

    return RuianAddress(
        kod_adm=kod_adm,
        kod_obce=_clean(row.get(COL_KOD_OBCE)) or "",
        nazev_obce=_clean(row.get(COL_NAZEV_OBCE)) or "",
        nazev_momc=_clean(row.get(COL_NAZEV_MOMC)),
        nazev_casti_obce=_clean(row.get(COL_NAZEV_CAST_OBCE)),
        nazev_ulice=_clean(row.get(COL_NAZEV_ULICE)),
        cislo_domovni=_clean(row.get(COL_CISLO_DOMOVNI)),
        cislo_orientacni=cislo_orientacni,
        psc=_clean(row.get(COL_PSC)),
        lat=lat,
        lon=lon,
    )


def read_ruian_csv(raw: bytes) -> Iterator[RuianAddress]:
    """Decode and parse a RÚIAN OB_ADR CSV blob, yielding usable addresses."""
    text = raw.decode(RUIAN_CSV_ENCODING)
    reader = csv.DictReader(io.StringIO(text), delimiter=RUIAN_CSV_DELIMITER)
    if reader.fieldnames is None or COL_KOD_ADM not in reader.fieldnames:
        raise ValueError(
            f"RÚIAN CSV missing expected header column {COL_KOD_ADM!r}; "
            f"got {reader.fieldnames}"
        )
    skipped = 0
    for row in reader:
        addr = parse_ruian_csv_row(row)
        if addr is None:
            skipped += 1
            continue
        yield addr
    if skipped:
        log.info("ruian.csv.rows_skipped", skipped=skipped)


# ---------------------------------------------------------------------------
# Spatial lookup (used by the geocode stage)
# ---------------------------------------------------------------------------

# How close a source GPS point must be to a RÚIAN address to count as the
# same building. Sreality coordinates are usually within a few metres of the
# building; 25 m absorbs the noise without grabbing the wrong house.
DEFAULT_LOOKUP_RADIUS_M = 25.0


def nearest_ruian_address(
    db: Any,
    lat: float,
    lon: float,
    max_m: float = DEFAULT_LOOKUP_RADIUS_M,
) -> RuianAddress | None:
    """Return the closest RÚIAN address within `max_m`, or None."""
    from sqlalchemy import text

    row = db.execute(
        text(
            """
            SELECT kod_adm, kod_obce, nazev_obce, nazev_momc, nazev_casti_obce,
                   nazev_ulice, cislo_domovni, cislo_orientacni, psc,
                   ST_Y(geom::geometry) AS lat,
                   ST_X(geom::geometry) AS lon
            FROM ruian_address
            WHERE ST_DWithin(
                      geom,
                      ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
                      :radius
                  )
            ORDER BY geom <-> ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography
            LIMIT 1
            """
        ),
        {"lat": lat, "lon": lon, "radius": max_m},
    ).first()
    if row is None:
        return None
    return RuianAddress(
        kod_adm=row.kod_adm,
        kod_obce=row.kod_obce,
        nazev_obce=row.nazev_obce,
        nazev_momc=row.nazev_momc,
        nazev_casti_obce=row.nazev_casti_obce,
        nazev_ulice=row.nazev_ulice,
        cislo_domovni=row.cislo_domovni,
        cislo_orientacni=row.cislo_orientacni,
        psc=row.psc,
        lat=float(row.lat),
        lon=float(row.lon),
    )
