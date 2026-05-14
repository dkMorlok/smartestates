"""Listings API — search, detail, and map endpoints.

Backs the Week-4 web skeleton: a filterable table, a property detail page,
and a map view. Filters are plain query params so the frontend can keep
them URL-encoded.
"""
from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from typing import Annotated, Any, Literal, TypedDict

from fastapi import APIRouter, Depends, HTTPException, Query
from geoalchemy2.shape import to_shape
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Select, func, select, text
from sqlalchemy.orm import Session, joinedload

from db.orm import Listing, Property, Source
from db.session import get_session_factory

router = APIRouter(prefix="/listings", tags=["listings"])

# Map view never returns more than this many individual pins; above it the
# client should zoom in or the server clusters (see docs/GEO.md).
_MAX_MAP_PINS = 500
# Below this zoom the map endpoint clusters server-side via ST_ClusterDBSCAN.
_CLUSTER_ZOOM_THRESHOLD = 13


def get_db() -> Iterator[Session]:
    factory = get_session_factory()
    session = factory()
    try:
        yield session
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class ListingSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_slug: str
    canonical_url: str
    property_type: str
    disposition: str | None
    ownership_type: str | None
    building_type: str | None
    condition: str | None
    size_m2: Decimal | None
    price_czk: Decimal | None
    locality: str | None
    city_district: str | None
    status: str
    lat: float | None
    lon: float | None


class PhotoOut(BaseModel):
    url: str
    width: int | None
    height: int | None


class ListingDetail(ListingSummary):
    usable_area_m2: Decimal | None
    land_area_m2: Decimal | None
    rooms: int | None
    bathrooms: int | None
    floor_current: int | None
    floor_total: int | None
    year_built: int | None
    energy_class: str | None
    description: str | None
    agency: str | None
    agent_name: str | None
    is_owner_direct: bool | None
    features: dict[str, object]
    postcode: str | None
    cadastral_area: str | None
    address_normalized: str | None
    photos: list[PhotoOut]


class ListingPage(BaseModel):
    data: list[ListingSummary]
    meta: dict[str, int | str | None]


class MapPin(BaseModel):
    id: int
    lat: float
    lon: float
    price_czk: Decimal | None
    disposition: str | None


class MapCluster(BaseModel):
    lat: float
    lon: float
    count: int


class MapResponse(BaseModel):
    mode: Literal["pins", "clusters"]
    pins: list[MapPin]
    clusters: list[MapCluster]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _coords(prop: Property | None) -> tuple[float | None, float | None]:
    """Pull (lat, lon) out of a property's geography point, if present."""
    if prop is None or prop.geom is None:
        return None, None
    point = to_shape(prop.geom)
    return float(point.y), float(point.x)


def _summary(listing: Listing, source_slug: str) -> ListingSummary:
    prop = listing.property_ref
    lat, lon = _coords(prop)
    return ListingSummary(
        id=listing.id,
        source_slug=source_slug,
        canonical_url=listing.canonical_url,
        property_type=listing.property_type,
        disposition=listing.disposition,
        ownership_type=listing.ownership_type,
        building_type=listing.building_type,
        condition=listing.condition,
        size_m2=listing.size_m2,
        price_czk=listing.price,
        locality=prop.locality if prop else None,
        city_district=prop.city_district if prop else None,
        status=listing.status,
        lat=lat,
        lon=lon,
    )


def _source_slugs(db: Session) -> dict[int, str]:
    return {
        int(sid): slug
        for sid, slug in db.execute(select(Source.id, Source.slug)).all()
    }


class _Filters(TypedDict):
    status_filter: str
    property_type: str | None
    disposition: str | None
    ownership_type: str | None
    city_district: str | None
    min_price: int | None
    max_price: int | None
    min_size: int | None
    max_size: int | None


def _apply_filters(
    stmt: Select[Any],
    *,
    status_filter: str,
    property_type: str | None,
    disposition: str | None,
    ownership_type: str | None,
    city_district: str | None,
    min_price: int | None,
    max_price: int | None,
    min_size: int | None,
    max_size: int | None,
) -> Select[Any]:
    stmt = stmt.where(Listing.status == status_filter)
    if property_type:
        stmt = stmt.where(Listing.property_type == property_type)
    if disposition:
        stmt = stmt.where(Listing.disposition == disposition)
    if ownership_type:
        stmt = stmt.where(Listing.ownership_type == ownership_type)
    if min_price is not None:
        stmt = stmt.where(Listing.price >= min_price)
    if max_price is not None:
        stmt = stmt.where(Listing.price <= max_price)
    if min_size is not None:
        stmt = stmt.where(Listing.size_m2 >= min_size)
    if max_size is not None:
        stmt = stmt.where(Listing.size_m2 <= max_size)
    if city_district:
        stmt = stmt.join(Property, Listing.property_id == Property.id).where(
            Property.city_district == city_district
        )
    return stmt


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=ListingPage)
def list_listings(
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status_filter: str = Query("active", alias="status"),
    property_type: str | None = None,
    disposition: str | None = None,
    ownership_type: str | None = None,
    city_district: str | None = None,
    min_price: int | None = Query(None, ge=0),
    max_price: int | None = Query(None, ge=0),
    min_size: int | None = Query(None, ge=0),
    max_size: int | None = Query(None, ge=0),
) -> ListingPage:
    """Filterable listing search. Filters are AND-combined."""
    filter_kwargs: _Filters = {
        "status_filter": status_filter,
        "property_type": property_type,
        "disposition": disposition,
        "ownership_type": ownership_type,
        "city_district": city_district,
        "min_price": min_price,
        "max_price": max_price,
        "min_size": min_size,
        "max_size": max_size,
    }

    total = db.execute(
        _apply_filters(select(func.count(Listing.id)), **filter_kwargs)
    ).scalar_one()

    stmt = _apply_filters(
        select(Listing).options(joinedload(Listing.property_ref)),
        **filter_kwargs,
    )
    stmt = stmt.order_by(Listing.last_seen_at.desc()).limit(limit).offset(offset)
    rows = db.execute(stmt).scalars().unique().all()

    slugs = _source_slugs(db)
    data = [_summary(r, slugs.get(r.source_id, "unknown")) for r in rows]
    return ListingPage(
        data=data,
        meta={"limit": limit, "offset": offset, "total": int(total)},
    )


@router.get("/map", response_model=MapResponse)
def map_listings(
    db: Annotated[Session, Depends(get_db)],
    min_lon: float = Query(..., ge=-180, le=180),
    min_lat: float = Query(..., ge=-90, le=90),
    max_lon: float = Query(..., ge=-180, le=180),
    max_lat: float = Query(..., ge=-90, le=90),
    zoom: int = Query(13, ge=1, le=22),
    status_filter: str = Query("active", alias="status"),
) -> MapResponse:
    """Listings within a bounding box.

    Below zoom 13 the result is clustered server-side (ST_ClusterDBSCAN);
    at zoom 13+ it returns individual pins, capped at 500.
    """
    if min_lon > max_lon or min_lat > max_lat:
        raise HTTPException(status_code=422, detail="Inverted bounding box")

    bbox = {
        "min_lon": min_lon,
        "min_lat": min_lat,
        "max_lon": max_lon,
        "max_lat": max_lat,
        "status": status_filter,
    }

    if zoom < _CLUSTER_ZOOM_THRESHOLD:
        # eps shrinks as zoom grows: ~9 km at zoom 6, ~140 m at zoom 12.
        eps = 0.08 / (2 ** max(0, zoom - 6))
        rows = db.execute(
            text(
                """
                WITH pts AS (
                    SELECT p.geom::geometry AS g
                    FROM listing l
                    JOIN property p ON p.id = l.property_id
                    WHERE l.status = :status
                      AND p.geom::geometry && ST_MakeEnvelope(
                          :min_lon, :min_lat, :max_lon, :max_lat, 4326)
                ),
                clustered AS (
                    SELECT g, ST_ClusterDBSCAN(g, eps := :eps, minpoints := 1)
                               OVER () AS cid
                    FROM pts
                )
                SELECT count(*) AS cnt,
                       ST_Y(ST_Centroid(ST_Collect(g))) AS lat,
                       ST_X(ST_Centroid(ST_Collect(g))) AS lon
                FROM clustered
                GROUP BY cid
                """
            ),
            {**bbox, "eps": eps},
        ).all()
        clusters = [
            MapCluster(lat=float(r.lat), lon=float(r.lon), count=int(r.cnt))
            for r in rows
        ]
        return MapResponse(mode="clusters", pins=[], clusters=clusters)

    rows = db.execute(
        text(
            """
            SELECT l.id,
                   ST_Y(p.geom::geometry) AS lat,
                   ST_X(p.geom::geometry) AS lon,
                   l.price AS price_czk,
                   l.disposition
            FROM listing l
            JOIN property p ON p.id = l.property_id
            WHERE l.status = :status
              AND p.geom::geometry && ST_MakeEnvelope(
                  :min_lon, :min_lat, :max_lon, :max_lat, 4326)
            ORDER BY l.last_seen_at DESC
            LIMIT :limit
            """
        ),
        {**bbox, "limit": _MAX_MAP_PINS},
    ).all()
    pins = [
        MapPin(
            id=int(r.id),
            lat=float(r.lat),
            lon=float(r.lon),
            price_czk=r.price_czk,
            disposition=r.disposition,
        )
        for r in rows
    ]
    return MapResponse(mode="pins", pins=pins, clusters=[])


@router.get("/{listing_id}", response_model=ListingDetail)
def get_listing(
    listing_id: int,
    db: Annotated[Session, Depends(get_db)],
) -> ListingDetail:
    """Full detail for one listing, including photos and coordinates."""
    listing = db.execute(
        select(Listing)
        .options(
            joinedload(Listing.property_ref),
            joinedload(Listing.photos),
        )
        .where(Listing.id == listing_id)
    ).scalars().unique().one_or_none()
    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found")

    slugs = _source_slugs(db)
    summary = _summary(listing, slugs.get(listing.source_id, "unknown"))
    prop = listing.property_ref
    photos = sorted(listing.photos, key=lambda p: p.ord)

    return ListingDetail(
        **summary.model_dump(),
        usable_area_m2=listing.usable_area_m2,
        land_area_m2=listing.land_area_m2,
        rooms=listing.rooms,
        bathrooms=listing.bathrooms,
        floor_current=listing.floor_current,
        floor_total=listing.floor_total,
        year_built=listing.year_built,
        energy_class=listing.energy_class,
        description=listing.description,
        agency=listing.agency,
        agent_name=listing.agent_name,
        is_owner_direct=listing.is_owner_direct,
        features=dict(listing.features_jsonb or {}),
        postcode=prop.postcode if prop else None,
        cadastral_area=prop.cadastral_area if prop else None,
        address_normalized=prop.address_normalized if prop else None,
        photos=[
            PhotoOut(url=p.url_source, width=p.width, height=p.height)
            for p in photos
        ],
    )
