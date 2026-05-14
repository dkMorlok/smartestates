from __future__ import annotations

import sys
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

# Ensure src/ is importable when running locally without install
SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@dataclass
class SeededData:
    """IDs of the rows inserted by the `seeded_listings` fixture."""

    listing_smichov_2kk: int
    listing_vinohrady_3_1: int
    listing_smichov_1kk: int
    listing_unlinked: int
    property_smichov: int
    property_vinohrady: int


@pytest.fixture
def seeded_listings() -> Iterator[SeededData]:
    """Insert a small fixture dataset (2 properties, 4 listings) and clean up.

    The API opens its own DB session, so these rows must be committed; the
    fixture deletes exactly what it created on teardown.
    """
    from sqlalchemy import select

    from db.orm import Listing, Photo, Property, Source
    from db.session import session_scope

    now = datetime.now(tz=UTC)
    listing_ids: list[int] = []
    property_ids: list[int] = []

    with session_scope() as db:
        source_id = db.execute(
            select(Source.id).where(Source.slug == "sreality")
        ).scalar_one()

        # Coordinates and district names are deliberately synthetic so the
        # tests isolate exactly these rows even when the DB already holds
        # real ingested listings.
        smichov = Property(
            geom="SRID=4326;POINT(13.0010 49.0010)",
            address_precision="rooftop",
            address_normalized="TEST Plzeňská 123",
            locality="TEST Locality A",
            city_district="TEST-DISTRICT-A",
            postcode="150 00",
        )
        vinohrady = Property(
            geom="SRID=4326;POINT(13.0050 49.0050)",
            address_precision="rooftop",
            locality="TEST Locality B",
            city_district="TEST-DISTRICT-B",
            postcode="120 00",
        )
        db.add_all([smichov, vinohrady])
        db.flush()
        property_ids = [int(smichov.id), int(vinohrady.id)]

        def _listing(
            sid: str,
            *,
            property_id: int | None,
            disposition: str,
            ownership: str,
            price: int,
            size: int,
        ) -> Listing:
            return Listing(
                source_id=source_id,
                source_listing_id=sid,
                canonical_url=f"https://www.sreality.cz/detail/prodej/byt/{sid}",
                first_seen_at=now,
                last_seen_at=now,
                status="active",
                property_id=property_id,
                property_type="byt",
                disposition=disposition,
                ownership_type=ownership,
                building_type="cihla",
                condition="po_rekonstrukci",
                price=Decimal(price),
                size_m2=Decimal(size),
            )

        l1 = _listing(
            "test-smichov-2kk",
            property_id=int(smichov.id),
            disposition="2+kk",
            ownership="osobni",
            price=6_950_000,
            size=56,
        )
        l2 = _listing(
            "test-vinohrady-3-1",
            property_id=int(vinohrady.id),
            disposition="3+1",
            ownership="druzstevni",
            price=8_500_000,
            size=90,
        )
        l3 = _listing(
            "test-smichov-1kk",
            property_id=int(smichov.id),
            disposition="1+kk",
            ownership="osobni",
            price=4_000_000,
            size=35,
        )
        l4 = _listing(
            "test-unlinked",
            property_id=None,
            disposition="2+kk",
            ownership="osobni",
            price=5_000_000,
            size=50,
        )
        db.add_all([l1, l2, l3, l4])
        db.flush()
        listing_ids = [int(x.id) for x in (l1, l2, l3, l4)]

        db.add_all(
            [
                Photo(listing_id=int(l1.id), ord=0, url_source="https://img/1.jpg",
                      width=800, height=600),
                Photo(listing_id=int(l1.id), ord=1, url_source="https://img/2.jpg",
                      width=800, height=600),
            ]
        )

        seeded = SeededData(
            listing_smichov_2kk=int(l1.id),
            listing_vinohrady_3_1=int(l2.id),
            listing_smichov_1kk=int(l3.id),
            listing_unlinked=int(l4.id),
            property_smichov=int(smichov.id),
            property_vinohrady=int(vinohrady.id),
        )

    try:
        yield seeded
    finally:
        from sqlalchemy import delete

        from db.orm import Listing as L
        from db.orm import Photo as P
        from db.orm import Property as Pr

        with session_scope() as db:
            db.execute(delete(P).where(P.listing_id.in_(listing_ids)))
            db.execute(delete(L).where(L.id.in_(listing_ids)))
            db.execute(delete(Pr).where(Pr.id.in_(property_ids)))
