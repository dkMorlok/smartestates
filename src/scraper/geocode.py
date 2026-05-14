"""Geocoding core: turn a listing's location hints into a point + precision.

Strategy (see docs/GEO.md):
  1. Prefer the source-provided GPS (Sreality `gps`). Trust the coordinates,
     but verify they fall inside the stated locality's bounding box — some
     Sreality listings carry GPS for the wrong place.
  2. Enrich a trusted point via reverse geocoding against a self-hosted
     Nominatim (RÚIAN-seeded): upgrades precision and fills the RÚIAN code.
  3. With no usable point, fall back to forward geocoding the address.
  4. With nothing, return a `locality`-precision result with no point — the
     caller must not link or create a property from it (flag for review).

Nominatim is optional. When `NOMINATIM_URL` is unset or the service is down
the module degrades to source-GPS-only, which still covers ~all Sreality
listings (they almost always include `gps`).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from scraper.http import make_client
from shared.config import get_settings
from shared.enums import AddressPrecision
from shared.logging import get_logger
from shared.normalize import normalize_address, normalize_for_match, praha_district_from_postcode

log = get_logger("scraper.geocode")


# ---------------------------------------------------------------------------
# Bounding boxes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BBox:
    """A simple lat/lon rectangle."""

    min_lat: float
    max_lat: float
    min_lon: float
    max_lon: float

    def contains(self, lat: float, lon: float) -> bool:
        return (
            self.min_lat <= lat <= self.max_lat
            and self.min_lon <= lon <= self.max_lon
        )


# Hlavní město Praha, generous margin. MVP is Praha-only; this is the
# "verify GPS falls within the stated locality" check from GEO.md.
PRAHA_BBOX = BBox(min_lat=49.94, max_lat=50.18, min_lon=14.22, max_lon=14.71)


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass
class GeocodeResult:
    """Outcome of resolving one listing's location."""

    precision: AddressPrecision
    lat: float | None = None
    lon: float | None = None
    address_normalized: str | None = None
    locality: str | None = None
    city_district: str | None = None
    cadastral_area: str | None = None
    postcode: str | None = None
    ruian_address_code: str | None = None
    ruian_building_code: str | None = None
    # Why this result looks the way it does — useful in logs/ops review.
    note: str | None = None

    @property
    def has_point(self) -> bool:
        return self.lat is not None and self.lon is not None

    @property
    def linkable(self) -> bool:
        """Whether this result is precise enough to link to a property.

        `locality`-precision results have no usable point; GEO.md says do not
        link or create a property from them — flag for review instead.
        """
        return self.has_point and self.precision != AddressPrecision.LOCALITY


# ---------------------------------------------------------------------------
# Nominatim response interpretation (pure)
# ---------------------------------------------------------------------------


def classify_nominatim_precision(result: dict[str, Any]) -> AddressPrecision:
    """Map a Nominatim result to our precision ladder.

    A RÚIAN-seeded Nominatim resolves real CZ addresses to building polygons;
    we treat a house number or a building/house addresstype as rooftop.
    """
    addresstype = result.get("addresstype") or result.get("type")
    category = result.get("category")
    addr = result.get("address") or {}

    if category == "building" or addresstype in ("building", "house"):
        return AddressPrecision.ROOFTOP
    if addr.get("house_number"):
        return AddressPrecision.ROOFTOP
    if addresstype in ("parcel", "land"):
        return AddressPrecision.PARCEL
    if addr.get("road"):
        return AddressPrecision.STREET
    return AddressPrecision.LOCALITY


def _extract_ruian(result: dict[str, Any]) -> tuple[str | None, str | None]:
    """Pull RÚIAN address + building codes out of a Nominatim result.

    A RÚIAN-seeded import carries them in `extratags` under `ref:ruian:*`.
    Absent on a vanilla OSM Nominatim — returns (None, None) then.
    """
    extra = result.get("extratags") or {}
    addr_code = extra.get("ref:ruian:addr") or extra.get("ref:ruian")
    bld_code = extra.get("ref:ruian:building")
    return (
        str(addr_code) if addr_code else None,
        str(bld_code) if bld_code else None,
    )


def _apply_nominatim(target: GeocodeResult, result: dict[str, Any]) -> None:
    """Fold a Nominatim result's address detail into an existing GeocodeResult."""
    addr = result.get("address") or {}
    addr_code, bld_code = _extract_ruian(result)
    if addr_code:
        target.ruian_address_code = addr_code
    if bld_code:
        target.ruian_building_code = bld_code
    # Praha's administrative districts surface under varying keys.
    district = (
        addr.get("city_district")
        or addr.get("borough")
        or addr.get("suburb")
        or addr.get("municipality")
    )
    if district and not target.city_district:
        target.city_district = district
    if not target.cadastral_area:
        target.cadastral_area = addr.get("quarter") or addr.get("neighbourhood")
    if not target.postcode:
        target.postcode = addr.get("postcode")
    display = result.get("display_name")
    if display and not target.address_normalized:
        target.address_normalized = normalize_address(display)


# ---------------------------------------------------------------------------
# Nominatim client (graceful, optional)
# ---------------------------------------------------------------------------


class NominatimClient:
    """Thin client over a self-hosted Nominatim. Never raises — returns None.

    Geocoding must never break the ingestion pipeline; a missing or degraded
    Nominatim simply means we keep the source GPS at `source_gps` precision.
    """

    def __init__(self, base_url: str | None = None, timeout_s: float = 8.0) -> None:
        raw = base_url if base_url is not None else get_settings().nominatim_url
        self.base_url = (raw or "").rstrip("/")
        self.timeout_s = timeout_s

    @property
    def enabled(self) -> bool:
        return bool(self.base_url)

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any] | list[Any] | None:
        if not self.enabled:
            return None
        try:
            with make_client(self.timeout_s) as client:
                resp = client.get(f"{self.base_url}{path}", params=params)
        except httpx.HTTPError as e:
            log.warning("geocode.nominatim.error", path=path, error=str(e)[:200])
            return None
        if resp.status_code != 200:
            log.warning("geocode.nominatim.bad_status", path=path, status=resp.status_code)
            return None
        try:
            data: Any = resp.json()
        except ValueError:
            log.warning("geocode.nominatim.bad_json", path=path)
            return None
        if isinstance(data, dict):
            return None if data.get("error") else data
        if isinstance(data, list):
            return data
        return None

    def reverse(self, lat: float, lon: float) -> dict[str, Any] | None:
        """Reverse-geocode a point to an address + RÚIAN codes."""
        data = self._get(
            "/reverse",
            {
                "lat": lat,
                "lon": lon,
                "format": "jsonv2",
                "addressdetails": 1,
                "extratags": 1,
                "zoom": 18,
            },
        )
        return data if isinstance(data, dict) else None

    def search(
        self,
        *,
        street: str | None = None,
        city: str | None = None,
        postalcode: str | None = None,
        country: str = "Czech Republic",
    ) -> dict[str, Any] | None:
        """Forward-geocode a structured address. Returns the top hit."""
        params: dict[str, Any] = {
            "format": "jsonv2",
            "addressdetails": 1,
            "extratags": 1,
            "limit": 1,
            "countrycodes": "cz",
            "country": country,
        }
        if street:
            params["street"] = street
        if city:
            params["city"] = city
        if postalcode:
            params["postalcode"] = postalcode
        if not (street or city or postalcode):
            return None
        data = self._get("/search", params)
        if isinstance(data, list) and data:
            first = data[0]
            return first if isinstance(first, dict) else None
        return None


# ---------------------------------------------------------------------------
# RÚIAN lookup contract
# ---------------------------------------------------------------------------


class RuianMatch(Protocol):
    """The fields resolve_location needs from a RÚIAN address hit.

    scraper.ruian.RuianAddress satisfies this structurally; keeping it a
    Protocol lets the geocode core stay independent of the RÚIAN module and
    the database. Members are read-only properties so a frozen dataclass
    satisfies the contract.
    """

    @property
    def kod_adm(self) -> str: ...

    @property
    def nazev_momc(self) -> str | None: ...

    @property
    def nazev_casti_obce(self) -> str | None: ...

    @property
    def psc(self) -> str | None: ...


# (lat, lon) -> nearest RÚIAN address within a tolerance, or None.
RuianLookup = Callable[[float, float], "RuianMatch | None"]


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _coords_from_source_geo(source_geo: dict[str, Any] | None) -> tuple[float, float] | None:
    if not source_geo:
        return None
    lat = source_geo.get("lat")
    lon = source_geo.get("lon")
    if lat is None or lon is None:
        return None
    try:
        return float(lat), float(lon)
    except (TypeError, ValueError):
        return None


def resolve_location(
    *,
    source_geo: dict[str, Any] | None,
    address_raw: str | None = None,
    locality: str | None = None,
    city_district: str | None = None,
    postcode: str | None = None,
    ruian_lookup: RuianLookup | None = None,
    nominatim: NominatimClient | None = None,
    bbox: BBox = PRAHA_BBOX,
) -> GeocodeResult:
    """Resolve one listing's location hints into a point + precision.

    Orchestration only: side effects are the optional RÚIAN lookup and
    Nominatim calls, both of which are expected never to raise. When a source
    GPS point is trusted, RÚIAN is consulted first (it gives rooftop precision
    plus the official address code); Nominatim is the fallback enrichment.
    """
    district_fallback = city_district or praha_district_from_postcode(postcode)
    addr_norm = normalize_address(address_raw) if address_raw else None

    # 1. Source GPS — trusted, but only if it lands in the stated locality.
    coords = _coords_from_source_geo(source_geo)
    if coords is not None:
        lat, lon = coords
        if bbox.contains(lat, lon):
            result = GeocodeResult(
                precision=AddressPrecision.SOURCE_GPS,
                lat=lat,
                lon=lon,
                address_normalized=addr_norm,
                locality=locality,
                city_district=district_fallback,
                postcode=postcode,
                note="source_gps",
            )
            # RÚIAN first — a hit gives rooftop precision + the address code.
            if ruian_lookup is not None:
                match = ruian_lookup(lat, lon)
                if match is not None:
                    result.precision = AddressPrecision.ROOFTOP
                    result.ruian_address_code = match.kod_adm
                    if match.nazev_momc:
                        result.city_district = match.nazev_momc
                    if match.nazev_casti_obce:
                        result.cadastral_area = match.nazev_casti_obce
                    if match.psc and not result.postcode:
                        result.postcode = match.psc
                    result.note = "source_gps+ruian"
                    return result
            # Otherwise fall back to reverse geocoding via Nominatim.
            if nominatim is not None and nominatim.enabled:
                rev = nominatim.reverse(lat, lon)
                if rev is not None:
                    result.precision = classify_nominatim_precision(rev)
                    _apply_nominatim(result, rev)
                    result.note = "source_gps+nominatim"
            return result
        log.warning(
            "geocode.gps_outside_bbox",
            lat=lat,
            lon=lon,
            locality=locality,
        )

    # 2. Forward geocode the address.
    if nominatim is not None and nominatim.enabled and (address_raw or locality or postcode):
        hit = nominatim.search(
            street=address_raw,
            city=locality or "Praha",
            postalcode=postcode,
        )
        if hit is not None:
            try:
                lat = float(hit["lat"])
                lon = float(hit["lon"])
            except (KeyError, TypeError, ValueError):
                lat = lon = None  # type: ignore[assignment]
            if lat is not None and lon is not None and bbox.contains(lat, lon):
                result = GeocodeResult(
                    precision=classify_nominatim_precision(hit),
                    lat=lat,
                    lon=lon,
                    address_normalized=addr_norm,
                    locality=locality,
                    city_district=district_fallback,
                    postcode=postcode,
                    note="nominatim_forward",
                )
                _apply_nominatim(result, hit)
                return result

    # 3. Nothing usable — locality precision, no point. Caller flags for review.
    return GeocodeResult(
        precision=AddressPrecision.LOCALITY,
        address_normalized=addr_norm,
        locality=locality,
        city_district=district_fallback,
        postcode=postcode,
        note="unresolved",
    )


# ---------------------------------------------------------------------------
# Property linking (pure decision over spatial candidates)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PropertyCandidate:
    """A nearby existing property, as returned by the spatial query."""

    property_id: int
    distance_m: float
    address_normalized: str | None
    ruian_address_code: str | None


def _levenshtein(a: str, b: str) -> int:
    """Plain iterative edit distance. Inputs are short address strings."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        curr = [i]
        for j, cb in enumerate(b, start=1):
            curr.append(
                min(
                    prev[j] + 1,
                    curr[j - 1] + 1,
                    prev[j - 1] + (0 if ca == cb else 1),
                )
            )
        prev = curr
    return prev[-1]


@dataclass(frozen=True)
class LinkDecision:
    """How a listing should attach to a property."""

    property_id: int | None  # None → create a new property
    method: str
    confidence: float


def choose_property_link(
    result: GeocodeResult,
    candidates: list[PropertyCandidate],
) -> LinkDecision:
    """Decide which existing property a geocoded listing belongs to.

    Preference order from docs/GEO.md:
      1. RÚIAN address code exact match — bulletproof.
      2. within 3 m AND identical normalized address — same building.
      3. within 30 m AND fuzzy address match (Levenshtein < 5) — likely same.
      4. otherwise: create a new property.
    """
    # 1. RÚIAN exact.
    if result.ruian_address_code:
        for c in candidates:
            if c.ruian_address_code == result.ruian_address_code:
                return LinkDecision(c.property_id, "ruian_exact", 1.0)

    target_addr = (
        normalize_for_match(result.address_normalized)
        if result.address_normalized
        else None
    )

    # 2. Tight radius + exact normalized address.
    if target_addr:
        for c in candidates:
            if (
                c.distance_m <= 3.0
                and c.address_normalized
                and normalize_for_match(c.address_normalized) == target_addr
            ):
                return LinkDecision(c.property_id, "geo_3m_addr", 0.95)

    # 3. Loose radius + fuzzy address.
    if target_addr:
        best: tuple[int, int] | None = None  # (distance_edits, property_id)
        for c in candidates:
            if c.distance_m <= 30.0 and c.address_normalized:
                edits = _levenshtein(normalize_for_match(c.address_normalized), target_addr)
                if edits < 5 and (best is None or edits < best[0]):
                    best = (edits, c.property_id)
        if best is not None:
            return LinkDecision(best[1], "geo_30m_fuzzy", 0.75)

    # 4. New property.
    return LinkDecision(None, "new", 1.0)
