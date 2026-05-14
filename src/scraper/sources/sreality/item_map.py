"""Sreality `items[]` key → canonical field map.

The detail JSON contains an `items` array of {name, value, type, unit}
records. This module owns the mapping from CZ name strings to our schema.

Keep keys exact (with diacritics). Use a fallback lookup that strips
diacritics for robustness against unicode variations.
"""
from __future__ import annotations

import unicodedata
from typing import Final

# Canonical field name we want in ParsedListing.extra_features or top-level.
# 'top:foo' means populate ParsedListing.foo
# 'feat:foo' means features_jsonb['foo']
# 'extra:foo' means extra_features['foo']
SREALITY_ITEM_MAP: Final[dict[str, str]] = {
    # physical
    "Užitná plocha": "top:usable_area_m2",
    "Plocha podlahová": "top:size_m2",
    "Celková plocha": "top:size_m2",
    "Plocha pozemku": "top:land_area_m2",
    "Zastavěná plocha": "extra:zastavena_plocha_m2",
    "Plocha zahrady": "extra:plocha_zahrady_m2",

    # building / condition
    "Stavba": "top:building_type_raw",        # 'panelová', 'cihlová', ...
    "Stav objektu": "top:condition_raw",
    "Vlastnictví": "top:ownership_raw",
    "Druh objektu": "extra:druh_objektu",
    "Typ domu": "extra:typ_domu",

    # year / floors
    "Rok kolaudace": "top:year_built",
    "Rok rekonstrukce": "extra:year_renovated",
    "Poschodí": "top:floor_text",

    # energy
    "Energetická náročnost budovy": "top:energy_class_raw",
    "Třída energetické náročnosti": "top:energy_class_raw",

    # boolean features
    "Výtah": "feat:has_lift",
    "Balkón": "feat:has_balcony",
    "Lodžie": "feat:has_loggia",
    "Terasa": "feat:has_terrace",
    "Sklep": "feat:has_cellar",
    "Garáž": "feat:has_garage",
    "Parkování": "feat:has_parking",
    "Bezbariérový": "feat:bezbarierovy",
    "Vybavení": "feat:vybaveni",

    # fees
    "Anuita": "extra:anuita_czk",
    "Náklady na bydlení": "extra:naklady_bydleni_czk",
    "Poplatek RK z prodeje": "extra:rk_fee",

    # location parts
    "PSČ": "top:postcode",

    # legal
    "Půdní vestavba": "extra:pudni_vestavba",
    "Bezbariérový přístup": "feat:bezbariery",
}


def _strip_diacritics(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    )


# Precomputed diacritic-less lookup for robustness
SREALITY_ITEM_MAP_FOLDED: Final[dict[str, str]] = {
    _strip_diacritics(k).lower(): v for k, v in SREALITY_ITEM_MAP.items()
}


def resolve_item_key(name: str) -> str | None:
    """Return canonical target or None if unknown."""
    if name in SREALITY_ITEM_MAP:
        return SREALITY_ITEM_MAP[name]
    folded = _strip_diacritics(name).lower()
    return SREALITY_ITEM_MAP_FOLDED.get(folded)


# Sreality category enum mappings -----------------------------------------

CATEGORY_MAIN_TO_PROPERTY_TYPE: Final[dict[int, str]] = {
    1: "byt",
    2: "dum",
    3: "pozemek",
    4: "komercni",
    5: "ostatni",
}

CATEGORY_TYPE_TO_LISTING_KIND: Final[dict[int, str]] = {
    1: "prodej",
    2: "pronajem",
    3: "drazba",
}

REGION_ID_TO_NAME: Final[dict[int, str]] = {
    10: "Hlavní město Praha",
    11: "Středočeský kraj",
    12: "Jihočeský kraj",
    13: "Plzeňský kraj",
    14: "Karlovarský kraj",
    15: "Ústecký kraj",
    16: "Liberecký kraj",
    17: "Královéhradecký kraj",
    18: "Pardubický kraj",
    19: "Vysočina",
    20: "Jihomoravský kraj",
    21: "Olomoucký kraj",
    22: "Zlínský kraj",
    23: "Moravskoslezský kraj",
}
