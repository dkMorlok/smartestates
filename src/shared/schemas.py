"""Canonical parsed-listing schema.

Every source's parse() must produce one of these. Type-validated;
unknown fields go into `extra_features` rather than being dropped.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from shared.enums import (
    AddressPrecision,
    BuildingType,
    Condition,
    Disposition,
    EnergyClass,
    ListingKind,
    ListingStatus,
    OwnershipType,
    PropertyType,
)


class GeoPoint(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    precision: AddressPrecision = AddressPrecision.SOURCE_GPS


class ParsedPhoto(BaseModel):
    url: HttpUrl
    width: int | None = None
    height: int | None = None
    ord: int = 0


class ParsedListing(BaseModel):
    """Canonical normalized output of any source.parse().

    Required fields are minimal. Optional fields use None / sentinel.
    Unknown source-specific facts go in `extra_features` as JSON.
    """
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    # Identity
    source_slug: str
    source_listing_id: str
    canonical_url: HttpUrl
    fetched_at: datetime

    # What kind of listing
    listing_kind: ListingKind
    property_type: PropertyType

    # Pricing
    price_czk: int | None = None
    price_hidden: bool = False
    currency: str = "CZK"

    # Physical
    size_m2: Decimal | None = None
    usable_area_m2: Decimal | None = None
    land_area_m2: Decimal | None = None
    rooms: int | None = None
    bathrooms: int | None = None
    floor_current: int | None = None
    floor_total: int | None = None
    year_built: int | None = None

    # CZ-specific
    disposition: Disposition | None = None
    ownership_type: OwnershipType | None = None
    building_type: BuildingType | None = None
    condition: Condition | None = None
    energy_class: EnergyClass | None = None

    # Location
    address_raw: str | None = None
    locality: str | None = None        # obec
    city_district: str | None = None   # městská část
    admin1: str | None = None          # kraj
    admin2: str | None = None          # okres
    postcode: str | None = None
    cadastral_area: str | None = None  # katastrální území
    ruian_address_code: str | None = None
    geo: GeoPoint | None = None

    # Features (boolean toggles)
    has_balcony: bool | None = None
    has_loggia: bool | None = None
    has_terrace: bool | None = None
    has_cellar: bool | None = None
    has_lift: bool | None = None
    has_parking: bool | None = None
    has_garage: bool | None = None
    has_garden: bool | None = None
    furnished: bool | None = None

    # SVJ / fees
    svj_fee_czk_per_month: int | None = None

    # Rich content
    description: str | None = None
    photos: list[ParsedPhoto] = Field(default_factory=list)

    # Listing metadata
    agency: str | None = None
    agent_name: str | None = None
    is_owner_direct: bool | None = None
    first_seen_at: datetime | None = None  # if source exposes
    status: ListingStatus = ListingStatus.ACTIVE

    # Anything else worth keeping (raw, unstructured)
    extra_features: dict[str, Any] = Field(default_factory=dict)

    # Bookkeeping
    parser_version: str

    @field_validator("currency")
    @classmethod
    def currency_must_be_czk(cls, v: str) -> str:
        if v != "CZK":
            # we model only CZK pricing; reject anything else to quarantine
            raise ValueError("Only CZK is supported in MVP")
        return v

    @field_validator("year_built")
    @classmethod
    def sane_year(cls, v: int | None) -> int | None:
        if v is None:
            return v
        if v < 1700 or v > datetime.now().year + 5:
            raise ValueError(f"Implausible year_built={v}")
        return v
