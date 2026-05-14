"""Sreality detail JSON → ParsedListing.

The detail endpoint returns a dict with at least:
  - hash_id, name, meta_description, text.value
  - locality.value
  - price, price_czk, seo.locality, seo.category_main_cb, seo.category_type_cb
  - gps.lat, gps.lon
  - items: [{name, value, type, unit}, ...]
  - _embedded.images[].url
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from shared.enums import (
    AddressPrecision,
    ListingKind,
    ListingStatus,
    PropertyType,
)
from shared.normalize import (
    parse_building_type,
    parse_condition,
    parse_disposition,
    parse_energy_class,
    parse_floor,
    parse_ownership,
)
from shared.schemas import GeoPoint, ParsedListing

from .item_map import (
    CATEGORY_MAIN_TO_PROPERTY_TYPE,
    CATEGORY_TYPE_TO_LISTING_KIND,
    resolve_item_key,
)

PARSER_VERSION = "sreality-2026.05.14-1"


def _to_int(v: Any) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _to_decimal(v: Any) -> Decimal | None:
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v))
    except (TypeError, InvalidOperation):
        return None


def _to_bool(v: Any) -> bool | None:
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    s = str(v).strip().lower()
    if s in {"ano", "true", "1", "yes"}:
        return True
    if s in {"ne", "false", "0", "no"}:
        return False
    return None


def parse_sreality_detail(
    detail: dict[str, Any],
    *,
    hash_id: str,
    canonical_url: str,
    fetched_at: datetime | None = None,
) -> ParsedListing:
    """Parse Sreality detail JSON. Raises on schema violations to quarantine."""
    fetched_at = fetched_at or datetime.now(tz=UTC)

    seo = detail.get("seo") or {}
    category_main = _to_int(seo.get("category_main_cb"))
    category_type = _to_int(seo.get("category_type_cb"))

    if category_main is None or category_type is None:
        raise ValueError("Missing seo.category_main_cb or seo.category_type_cb")

    property_type_str = CATEGORY_MAIN_TO_PROPERTY_TYPE.get(category_main, "ostatni")
    listing_kind_str = CATEGORY_TYPE_TO_LISTING_KIND.get(category_type, "prodej")

    # ---- price ----
    price_czk = _to_int(detail.get("price_czk")) or _to_int(detail.get("price"))
    price_hidden = bool(detail.get("price_hidden")) or price_czk in (None, 0, 1)
    if price_hidden:
        price_czk = None

    # ---- location ----
    gps = detail.get("gps") or {}
    geo: GeoPoint | None = None
    if "lat" in gps and "lon" in gps:
        try:
            geo = GeoPoint(
                lat=float(gps["lat"]),
                lon=float(gps["lon"]),
                precision=AddressPrecision.SOURCE_GPS,
            )
        except (TypeError, ValueError):
            geo = None

    locality_obj = detail.get("locality") or {}
    locality_str = locality_obj.get("value") if isinstance(locality_obj, dict) else None

    # ---- text/description ----
    text_obj = detail.get("text") or {}
    description = text_obj.get("value") if isinstance(text_obj, dict) else None
    name = detail.get("name", {}).get("value") if isinstance(detail.get("name"), dict) else detail.get("name")
    meta_desc = detail.get("meta_description")

    # ---- disposition ----
    # Sreality includes disposition in name/meta_description for flats.
    # Prefer the listing name (most authoritative), then meta_description,
    # then locality: parse_disposition returns the first pattern match, so
    # concatenating the fields would let a stale phrase in a lower-priority
    # field win over the real value in the name.
    disposition = None
    for candidate in (name, meta_desc, locality_str):
        disposition = parse_disposition(candidate)
        if disposition is not None:
            break

    # ---- iterate items[] ----
    fields: dict[str, Any] = {}     # top-level overrides
    feats: dict[str, Any] = {}      # features_jsonb
    extras: dict[str, Any] = {}     # extra_features (unknown / raw)
    unknown_keys: list[str] = []

    for item in detail.get("items") or []:
        if not isinstance(item, dict):
            continue
        item_name = item.get("name")
        if not isinstance(item_name, str):
            continue
        value = item.get("value")
        unit = item.get("unit")

        target = resolve_item_key(item_name)
        if target is None:
            unknown_keys.append(item_name)
            extras[item_name] = value
            continue

        prefix, _, key = target.partition(":")
        if prefix == "top":
            fields[key] = value
        elif prefix == "feat":
            b = _to_bool(value)
            feats[key] = b if b is not None else value
        else:  # extra
            extras[key] = {"value": value, "unit": unit} if unit else value

    # ---- map raw fields into typed values ----
    floor_info = parse_floor(fields.get("floor_text"))

    parsed = ParsedListing(
        source_slug="sreality",
        source_listing_id=hash_id,
        canonical_url=canonical_url,  # type: ignore[arg-type]
        fetched_at=fetched_at,
        listing_kind=ListingKind(listing_kind_str),
        property_type=PropertyType(property_type_str),
        price_czk=price_czk,
        price_hidden=price_hidden,
        currency="CZK",
        size_m2=_to_decimal(fields.get("size_m2")),
        usable_area_m2=_to_decimal(fields.get("usable_area_m2")),
        land_area_m2=_to_decimal(fields.get("land_area_m2")),
        floor_current=floor_info.current,
        floor_total=floor_info.total,
        year_built=_to_int(fields.get("year_built")),
        disposition=disposition,
        ownership_type=parse_ownership(fields.get("ownership_raw")),
        building_type=parse_building_type(fields.get("building_type_raw")),
        condition=parse_condition(fields.get("condition_raw")),
        energy_class=parse_energy_class(fields.get("energy_class_raw")),
        address_raw=locality_str,
        locality=locality_str,
        postcode=fields.get("postcode"),
        geo=geo,
        has_balcony=_to_bool(feats.get("has_balcony")),
        has_loggia=_to_bool(feats.get("has_loggia")),
        has_terrace=_to_bool(feats.get("has_terrace")),
        has_cellar=_to_bool(feats.get("has_cellar")),
        has_lift=_to_bool(feats.get("has_lift")),
        has_parking=_to_bool(feats.get("has_parking")),
        has_garage=_to_bool(feats.get("has_garage")),
        description=description,
        status=ListingStatus.ACTIVE,
        extra_features={"unknown_keys": unknown_keys, **extras},
        parser_version=PARSER_VERSION,
    )
    return parsed
