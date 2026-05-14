"""Canonical enums for CZ real estate data.

These are the values we normalize to. Source-specific values (e.g. Sreality's
Czech strings) are mapped to these via per-source item maps.

References: docs/CZ_NOTES.md
"""
from __future__ import annotations

from enum import StrEnum


class PropertyType(StrEnum):
    BYT = "byt"
    DUM = "dum"
    POZEMEK = "pozemek"
    KOMERCNI = "komercni"
    CHATA = "chata"
    GARAZ = "garaz"
    OSTATNI = "ostatni"


class ListingKind(StrEnum):
    PRODEJ = "prodej"
    PRONAJEM = "pronajem"
    DRAZBA = "drazba"


class Disposition(StrEnum):
    """Czech flat layout descriptor.

    `+kk` = with kitchenette (kuchyňský kout)
    `+1`  = with separate kitchen
    """
    GARSONIERA = "garsoniera"
    D_1KK = "1+kk"
    D_1_1 = "1+1"
    D_2KK = "2+kk"
    D_2_1 = "2+1"
    D_3KK = "3+kk"
    D_3_1 = "3+1"
    D_4KK = "4+kk"
    D_4_1 = "4+1"
    D_5KK = "5+kk"
    D_5_1 = "5+1"
    D_6_PLUS = "6+"
    ATYPICKY = "atypicky"


class OwnershipType(StrEnum):
    """The biggest CZ scoring trap. NEVER average across these values.

    See docs/CZ_NOTES.md / SCORING.md.
    """
    OSOBNI = "osobni"       # personal / freehold
    DRUZSTEVNI = "druzstevni"  # cooperative
    STATNI = "statni"       # state / municipal


class BuildingType(StrEnum):
    PANEL = "panel"
    CIHLA = "cihla"
    SMISENA = "smisena"
    DREVO = "drevo"
    KAMEN = "kamen"
    OSTATNI = "ostatni"


class Condition(StrEnum):
    NOVOSTAVBA = "novostavba"
    VELMI_DOBRY = "velmi_dobry"
    DOBRY = "dobry"
    V_REKONSTRUKCI = "v_rekonstrukci"
    PO_REKONSTRUKCI = "po_rekonstrukci"
    PRED_REKONSTRUKCI = "pred_rekonstrukci"
    SPATNY = "spatny"
    PROJEKT = "projekt"


class EnergyClass(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"
    F = "F"
    G = "G"


class ListingStatus(StrEnum):
    ACTIVE = "active"
    WITHDRAWN = "withdrawn"
    SOLD = "sold"
    UNKNOWN = "unknown"


class AddressPrecision(StrEnum):
    ROOFTOP = "rooftop"
    PARCEL = "parcel"
    STREET = "street"
    LOCALITY = "locality"
    SOURCE_GPS = "source_gps"  # coords given by source, building unknown


class ParseStatus(StrEnum):
    OK = "ok"
    QUARANTINE = "quarantine"
    FAILED = "failed"
