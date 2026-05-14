"""Listings API. Minimal Week-1 implementation; expands in Week 4."""
from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from db.orm import Listing
from db.session import get_session_factory

router = APIRouter(prefix="/listings", tags=["listings"])


def get_db() -> Session:
    factory = get_session_factory()
    session = factory()
    try:
        yield session
    finally:
        session.close()


class ListingSummary(BaseModel):
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

    class Config:
        from_attributes = True


class ListingPage(BaseModel):
    data: list[ListingSummary]
    meta: dict[str, int | str | None]


@router.get("", response_model=ListingPage)
def list_listings(
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status_filter: str = Query("active", alias="status"),
    property_type: str | None = None,
    disposition: str | None = None,
    ownership_type: str | None = None,
    min_price: int | None = None,
    max_price: int | None = None,
) -> ListingPage:
    stmt = select(Listing).where(Listing.status == status_filter)
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

    stmt = stmt.order_by(Listing.last_seen_at.desc()).limit(limit).offset(offset)
    rows = db.execute(stmt).scalars().all()

    data = [
        ListingSummary(
            id=r.id,
            source_slug="sreality",  # join to source in Week 4
            canonical_url=r.canonical_url,
            property_type=r.property_type,
            disposition=r.disposition,
            ownership_type=r.ownership_type,
            building_type=r.building_type,
            condition=r.condition,
            size_m2=r.size_m2,
            price_czk=r.price,
            locality=None,  # join to property in Week 4
            city_district=None,
            status=r.status,
        )
        for r in rows
    ]
    return ListingPage(data=data, meta={"limit": limit, "offset": offset})


@router.get("/{listing_id}", response_model=ListingSummary)
def get_listing(
    listing_id: int,
    db: Annotated[Session, Depends(get_db)],
) -> ListingSummary:
    row = db.get(Listing, listing_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    return ListingSummary(
        id=row.id,
        source_slug="sreality",
        canonical_url=row.canonical_url,
        property_type=row.property_type,
        disposition=row.disposition,
        ownership_type=row.ownership_type,
        building_type=row.building_type,
        condition=row.condition,
        size_m2=row.size_m2,
        price_czk=row.price,
        locality=None,
        city_district=None,
        status=row.status,
    )
