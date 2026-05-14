"""Geocode stage: give every listing a point and link it to a property.

Runs after `normalize`. For each listing:
  1. Resolve a location from the parsed payload (source GPS, Nominatim).
  2. Link to an existing `property` (RÚIAN / spatial proximity) or create one.
  3. Hand off to `dedup.tier1` for the affected property.

A `locality`-precision result has no usable point: the listing is left
unlinked (property_id stays NULL) and flagged in the run log for review,
per docs/GEO.md.
"""
from __future__ import annotations

from typing import Any

from celery import shared_task
from sqlalchemy import text

from db.orm import Listing, Property, RawListing
from db.session import session_scope
from scraper.geocode import (
    GeocodeResult,
    NominatimClient,
    PropertyCandidate,
    choose_property_link,
    resolve_location,
)
from shared.logging import get_logger

log = get_logger("worker.geocode")

# Spatial search radius for property linking. choose_property_link applies
# the tighter 3 m / 30 m rules; this just bounds the candidate set.
_CANDIDATE_RADIUS_M = 30.0


def _spatial_candidates(db: Any, lat: float, lon: float) -> list[PropertyCandidate]:
    """Existing properties within the candidate radius, nearest first."""
    rows = db.execute(
        text(
            """
            SELECT id,
                   ST_Distance(
                       geom,
                       ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography
                   ) AS dist_m,
                   address_normalized,
                   ruian_address_code
            FROM property
            WHERE geom IS NOT NULL
              AND ST_DWithin(
                      geom,
                      ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
                      :radius
                  )
            ORDER BY dist_m
            LIMIT 10
            """
        ),
        {"lat": lat, "lon": lon, "radius": _CANDIDATE_RADIUS_M},
    ).all()
    return [
        PropertyCandidate(
            property_id=int(r.id),
            distance_m=float(r.dist_m),
            address_normalized=r.address_normalized,
            ruian_address_code=r.ruian_address_code,
        )
        for r in rows
    ]


def _link_or_create_property(db: Any, result: GeocodeResult) -> tuple[int, str]:
    """Attach the geocoded result to a property; create one if none fits.

    Returns (property_id, method). Assumes result.linkable is True.
    """
    assert result.lat is not None and result.lon is not None
    candidates = _spatial_candidates(db, result.lat, result.lon)
    decision = choose_property_link(result, candidates)

    if decision.property_id is not None:
        # RÚIAN code may have been discovered now but absent on the existing
        # row — backfill it so future links hit the bulletproof path.
        if result.ruian_address_code:
            prop = db.get(Property, decision.property_id)
            if prop is not None and prop.ruian_address_code is None:
                prop.ruian_address_code = result.ruian_address_code
        return decision.property_id, decision.method

    prop = Property(
        geom=f"SRID=4326;POINT({result.lon} {result.lat})",
        address_normalized=result.address_normalized,
        address_precision=result.precision.value,
        locality=result.locality,
        city_district=result.city_district,
        cadastral_area=result.cadastral_area,
        postcode=result.postcode,
        ruian_address_code=result.ruian_address_code,
        ruian_building_code=result.ruian_building_code,
    )
    db.add(prop)
    db.flush()
    return int(prop.id), "new"


@shared_task(
    name="geocode.listing",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
    bind=False,
)
def geocode_listing(listing_id: int) -> dict[str, Any]:
    """Resolve a listing's location and link it to a property."""
    nominatim = NominatimClient()

    with session_scope() as db:
        listing = db.get(Listing, listing_id)
        if listing is None:
            return {"status": "missing", "listing_id": listing_id}

        parsed: dict[str, Any] = {}
        if listing.raw_listing_id is not None:
            raw = db.get(RawListing, listing.raw_listing_id)
            if raw is not None and raw.parsed_jsonb is not None:
                parsed = raw.parsed_jsonb

        result = resolve_location(
            source_geo=parsed.get("geo"),
            address_raw=parsed.get("address_raw"),
            locality=parsed.get("locality"),
            city_district=parsed.get("city_district"),
            postcode=parsed.get("postcode"),
            nominatim=nominatim,
        )

        if not result.linkable:
            # No usable point — do not invent a property. Leave unlinked.
            listing.property_id = None
            log.warning(
                "geocode.unlinked",
                listing_id=listing_id,
                precision=result.precision.value,
                note=result.note,
            )
            return {
                "status": "unlinked",
                "listing_id": listing_id,
                "precision": result.precision.value,
            }

        property_id, method = _link_or_create_property(db, result)
        listing.property_id = property_id

    log.info(
        "geocode.done",
        listing_id=listing_id,
        property_id=property_id,
        precision=result.precision.value,
        method=method,
    )

    # Re-cluster the property now that its listing set may have changed.
    from worker.tasks.dedup import dedup_tier1

    dedup_tier1.delay(property_id)

    return {
        "status": "linked",
        "listing_id": listing_id,
        "property_id": property_id,
        "precision": result.precision.value,
        "method": method,
    }
