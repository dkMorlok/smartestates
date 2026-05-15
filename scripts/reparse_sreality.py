"""One-off: reparse + renormalize existing Sreality raw_listing rows.

After fixing the Sreality price parser (price_czk dict shape, see
src/scraper/sources/sreality/parse.py), historical rows still carry the old
broken parsed_jsonb (price_czk=null) and the downstream listing.price is
NULL for every row. This script re-runs the parser against the raw bytes
in object storage and reruns normalize so listing.price is populated.

Run inside the api container (which has the deps and DB env):

    docker compose exec -T api python scripts/reparse_sreality.py [--limit N]
"""
from __future__ import annotations

import argparse
import sys
from datetime import UTC

from sqlalchemy import func, select

from db.orm import Listing, Property, RawListing, Source
from db.session import session_scope
from scraper.base import RawDocument, get_source
from scraper.storage import get_raw
from worker.tasks.normalize import normalize_from_raw


def _link_property_inline(listing_id: int, parsed: dict[str, object]) -> None:
    """Create/link a Property row from parsed geo + locality fields.

    Sidesteps the Celery geocode pipeline (which is wedged on the worker
    image). Uses Sreality's own coords + city_district/locality strings;
    no Nominatim or RUIAN lookup.
    """
    geo = parsed.get("geo") or None
    if not isinstance(geo, dict):
        return
    lat = geo.get("lat")
    lon = geo.get("lon")
    if lat is None or lon is None:
        return

    locality = parsed.get("locality")
    city_district = parsed.get("city_district")
    address_raw = parsed.get("address_raw")
    point_wkt = f"SRID=4326;POINT({float(lon)} {float(lat)})"

    with session_scope() as db:
        listing = db.get(Listing, listing_id)
        if listing is None:
            return
        # Reuse existing property if one already covers this point + locality
        # within ~10 m; otherwise create a fresh one. Cheap approximation —
        # the real dedup pipeline tightens this in a later stage.
        match = db.execute(
            select(Property.id)
            .where(
                func.ST_DWithin(Property.geom, func.ST_GeogFromText(point_wkt), 10),
                Property.locality.is_not_distinct_from(locality),
            )
            .limit(1)
        ).scalar_one_or_none()
        if match is not None:
            listing.property_id = int(match)
            return

        prop = Property(
            geom=point_wkt,
            address_normalized=address_raw if isinstance(address_raw, str) else None,
            address_precision="source_gps",
            country="CZ",
            locality=locality if isinstance(locality, str) else None,
            city_district=city_district if isinstance(city_district, str) else None,
        )
        db.add(prop)
        db.flush()
        listing.property_id = int(prop.id)


def reparse_one(raw_listing_id: int) -> tuple[bool, str | None]:
    with session_scope() as db:
        row = db.get(RawListing, raw_listing_id)
        if row is None:
            return False, "missing raw_listing"
        source_slug = db.execute(
            select(Source.slug).where(Source.id == row.source_id)
        ).scalar_one()
        s3_key = row.raw_s3_key
        url = row.url
        source_listing_id = row.source_listing_id
        fetched_at = row.fetched_at

    try:
        content_bytes = get_raw(s3_key)
    except Exception as e:  # noqa: BLE001
        return False, f"get_raw: {e}"

    source = get_source(source_slug)
    raw_doc = RawDocument(
        source_slug=source_slug,
        source_listing_id=source_listing_id,
        url=url,
        http_status=200,
        content_type="application/json",
        content_bytes=content_bytes,
        fetched_at=(
            fetched_at.replace(tzinfo=UTC) if fetched_at.tzinfo is None else fetched_at
        ),
    )

    try:
        parsed = source.parse(raw_doc)
    except Exception as e:  # noqa: BLE001
        return False, f"parse: {type(e).__name__}: {e}"

    with session_scope() as db:
        row = db.get(RawListing, raw_listing_id)
        if row is None:
            return False, "missing raw_listing (post-parse)"
        row.parsed_jsonb = parsed.model_dump(mode="json")
        row.parser_version = parsed.parser_version
        row.parse_status = "ok"
        row.parse_error = None

    # Normalize inline (function body runs synchronously when called directly).
    res = normalize_from_raw(raw_listing_id)
    listing_id = res.get("listing_id") if isinstance(res, dict) else None
    if isinstance(listing_id, int):
        _link_property_inline(listing_id, parsed.model_dump(mode="json"))
    return True, None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--source", default="sreality")
    args = ap.parse_args()

    with session_scope() as db:
        source_id = db.execute(
            select(Source.id).where(Source.slug == args.source)
        ).scalar_one()
        stmt = select(RawListing.id).where(RawListing.source_id == source_id).order_by(
            RawListing.id
        )
        if args.limit is not None:
            stmt = stmt.limit(args.limit)
        ids = [int(r) for r in db.execute(stmt).scalars().all()]

    total = len(ids)
    print(f"reparsing {total} raw_listing rows for source={args.source}", flush=True)

    ok = 0
    errs = 0
    for i, rid in enumerate(ids, 1):
        success, err = reparse_one(rid)
        if success:
            ok += 1
        else:
            errs += 1
            if errs <= 10:
                print(f"  err {rid}: {err}", flush=True)
        if i % 200 == 0:
            print(f"  {i}/{total}  ok={ok}  err={errs}", flush=True)

    print(f"done. ok={ok}  err={errs}  total={total}")
    return 0 if errs == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
