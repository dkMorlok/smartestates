"""CZ-specific normalization utilities.

- Address normalization (diacritics, abbreviations, house numbers)
- Disposition parsing
- Ownership / building / condition string mapping (used by all sources)

Source modules call these to map their native strings to canonical enums.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from shared.enums import (
    BuildingType,
    Condition,
    Disposition,
    EnergyClass,
    OwnershipType,
)

# ---------------------------------------------------------------------------
# Diacritic-insensitive matching
# ---------------------------------------------------------------------------


def strip_diacritics(s: str) -> str:
    """`Náměstí Míru` -> `Namesti Miru`. For matching only; keep original for display."""
    return "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    )


def normalize_for_match(s: str) -> str:
    s = strip_diacritics(s).lower()
    s = re.sub(r"\s+", " ", s).strip()
    return s


# ---------------------------------------------------------------------------
# Disposition (1+kk, 2+1, ...)
# ---------------------------------------------------------------------------

_DISPOSITION_PATTERNS: tuple[tuple[re.Pattern[str], Disposition], ...] = (
    (re.compile(r"\bgarsoni[eé]ra\b", re.I), Disposition.GARSONIERA),
    (re.compile(r"\b1\s*\+\s*kk\b", re.I), Disposition.D_1KK),
    (re.compile(r"\b1\s*\+\s*1\b", re.I), Disposition.D_1_1),
    (re.compile(r"\b2\s*\+\s*kk\b", re.I), Disposition.D_2KK),
    (re.compile(r"\b2\s*\+\s*1\b", re.I), Disposition.D_2_1),
    (re.compile(r"\b3\s*\+\s*kk\b", re.I), Disposition.D_3KK),
    (re.compile(r"\b3\s*\+\s*1\b", re.I), Disposition.D_3_1),
    (re.compile(r"\b4\s*\+\s*kk\b", re.I), Disposition.D_4KK),
    (re.compile(r"\b4\s*\+\s*1\b", re.I), Disposition.D_4_1),
    (re.compile(r"\b5\s*\+\s*kk\b", re.I), Disposition.D_5KK),
    (re.compile(r"\b5\s*\+\s*1\b", re.I), Disposition.D_5_1),
    (re.compile(r"\b[6-9]\s*\+\s*(kk|1)\b", re.I), Disposition.D_6_PLUS),
    (re.compile(r"\batypick[yáé]\b", re.I), Disposition.ATYPICKY),
)


def parse_disposition(text: str | None) -> Disposition | None:
    if not text:
        return None
    normalized = strip_diacritics(text)
    for pat, value in _DISPOSITION_PATTERNS:
        if pat.search(normalized):
            return value
    return None


# ---------------------------------------------------------------------------
# Ownership type
# ---------------------------------------------------------------------------

_OWNERSHIP_MAP: dict[str, OwnershipType] = {
    "osobni": OwnershipType.OSOBNI,
    "osobni vlastnictvi": OwnershipType.OSOBNI,
    "ov": OwnershipType.OSOBNI,
    "druzstevni": OwnershipType.DRUZSTEVNI,
    "druzstevni vlastnictvi": OwnershipType.DRUZSTEVNI,
    "dv": OwnershipType.DRUZSTEVNI,
    "statni": OwnershipType.STATNI,
    "obecni": OwnershipType.STATNI,
    "statni / obecni": OwnershipType.STATNI,
}


def parse_ownership(text: str | None) -> OwnershipType | None:
    if not text:
        return None
    key = normalize_for_match(text)
    if key in _OWNERSHIP_MAP:
        return _OWNERSHIP_MAP[key]
    for needle, value in _OWNERSHIP_MAP.items():
        if needle in key:
            return value
    return None


# ---------------------------------------------------------------------------
# Building type
# ---------------------------------------------------------------------------

_BUILDING_MAP: dict[str, BuildingType] = {
    "panel": BuildingType.PANEL,
    "panelovy": BuildingType.PANEL,
    "panelova": BuildingType.PANEL,
    "cihla": BuildingType.CIHLA,
    "cihlovy": BuildingType.CIHLA,
    "cihlova": BuildingType.CIHLA,
    "smisena": BuildingType.SMISENA,
    "smiseny": BuildingType.SMISENA,
    "drevo": BuildingType.DREVO,
    "dreveny": BuildingType.DREVO,
    "drevena": BuildingType.DREVO,
    "kamen": BuildingType.KAMEN,
    "kamenny": BuildingType.KAMEN,
    "kamenna": BuildingType.KAMEN,
    "ostatni": BuildingType.OSTATNI,
}


def parse_building_type(text: str | None) -> BuildingType | None:
    if not text:
        return None
    key = normalize_for_match(text)
    for needle, value in _BUILDING_MAP.items():
        if needle in key:
            return value
    return None


# ---------------------------------------------------------------------------
# Condition (Sreality 'Stav objektu')
# ---------------------------------------------------------------------------

_CONDITION_MAP: dict[str, Condition] = {
    "novostavba": Condition.NOVOSTAVBA,
    "velmi dobry": Condition.VELMI_DOBRY,
    "dobry": Condition.DOBRY,
    "v rekonstrukci": Condition.V_REKONSTRUKCI,
    "po rekonstrukci": Condition.PO_REKONSTRUKCI,
    "pred rekonstrukci": Condition.PRED_REKONSTRUKCI,
    "spatny": Condition.SPATNY,
    "projekt": Condition.PROJEKT,
}


def parse_condition(text: str | None) -> Condition | None:
    if not text:
        return None
    key = normalize_for_match(text)
    if key in _CONDITION_MAP:
        return _CONDITION_MAP[key]
    # be lenient — substring contains
    for needle, value in _CONDITION_MAP.items():
        if needle in key:
            return value
    return None


# ---------------------------------------------------------------------------
# Energy class
# ---------------------------------------------------------------------------

_ENERGY_RE = re.compile(r"\b([A-G])\b")


def parse_energy_class(text: str | None) -> EnergyClass | None:
    if not text:
        return None
    m = _ENERGY_RE.search(text.upper())
    if not m:
        return None
    return EnergyClass(m.group(1))


# ---------------------------------------------------------------------------
# Floor parsing
# ---------------------------------------------------------------------------

_FLOOR_RE = re.compile(
    r"(?P<current>-?\d+)\s*\.?\s*(?:patro|np|podlazi)?\s*(?:z|of|/)\s*(?P<total>\d+)",
    re.I,
)
_GROUND_RE = re.compile(r"\b(prizemi|zvysene\s*prizemi)\b", re.I)


@dataclass
class FloorInfo:
    current: int | None
    total: int | None


def parse_floor(text: str | None) -> FloorInfo:
    """Parse strings like '2. patro z 5', 'přízemí', '4/5'."""
    if not text:
        return FloorInfo(None, None)
    norm = normalize_for_match(text)
    if _GROUND_RE.search(norm):
        # ground floor; total unknown from this string alone
        return FloorInfo(0, None)
    m = _FLOOR_RE.search(norm)
    if not m:
        # try a plain integer fallback
        if (m2 := re.search(r"\b(-?\d+)\b", norm)):
            return FloorInfo(int(m2.group(1)), None)
        return FloorInfo(None, None)
    return FloorInfo(int(m.group("current")), int(m.group("total")))


# ---------------------------------------------------------------------------
# Address normalization
# ---------------------------------------------------------------------------

_ABBREV_MAP = {
    r"\bul\.\s*": "ulice ",
    r"\bnám\.\s*": "naměsti ",
    r"\bnam\.\s*": "naměsti ",
    r"\btř\.\s*": "třida ",
    r"\btr\.\s*": "třida ",
    r"\bč\.p\.\s*": "",
    r"\bč\.\s*": "",
}


def normalize_address(addr: str) -> str:
    """Expand common abbreviations and collapse whitespace.

    Diacritics are NOT stripped here (we keep original for display). Use
    `normalize_for_match` on top when doing fuzzy comparisons.
    """
    s = addr
    for pat, repl in _ABBREV_MAP.items():
        s = re.sub(pat, repl, s, flags=re.I)
    s = re.sub(r"\s+", " ", s).strip()
    return s


_HOUSE_NUMBER_RE = re.compile(r"\b(?P<popisne>\d{1,5})\s*/\s*(?P<orientacni>\d{1,5}[a-z]?)\b", re.I)


@dataclass
class HouseNumber:
    popisne: str | None       # descriptive (building-level)
    orientacni: str | None    # orientation (street-level)


def parse_house_number(addr: str) -> HouseNumber:
    """CZ has two house numbers: popisné/orientační. E.g. 'Vinohradská 2128/175'."""
    m = _HOUSE_NUMBER_RE.search(addr)
    if not m:
        return HouseNumber(None, None)
    return HouseNumber(m.group("popisne"), m.group("orientacni"))


# ---------------------------------------------------------------------------
# Praha district from postcode
# ---------------------------------------------------------------------------

_PRAHA_POSTCODE_RE = re.compile(r"^1[0-9]{4}$")


def praha_district_from_postcode(postcode: str | None) -> str | None:
    """'11000' -> 'Praha 1'. Returns None if not a Praha postcode.

    Czech postcodes for Praha follow `1Dxxx` where D is the district digit:
    11000 = Praha 1, 12000 = Praha 2, ..., 19000 = Praha 9.
    Higher districts (10-22) use different prefixes (10x, 19x, 25x...) which
    we don't try to disambiguate by postcode alone.
    """
    if not postcode:
        return None
    pc = postcode.replace(" ", "")
    if not _PRAHA_POSTCODE_RE.match(pc):
        return None
    try:
        d = int(pc[1])
    except (ValueError, IndexError):
        return None
    if 1 <= d <= 9:
        return f"Praha {d}"
    return None
