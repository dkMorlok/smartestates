"""Run the full Sreality discover→fetch→parse→normalize chain inline.

Sidesteps the Celery worker (which is wedged on a stale image without numpy
+ shapely) by walking the pipeline synchronously from the api container.
Used to seed new regions; in steady state the beat-driven discover task
should do this on schedule once the worker image is rebuilt.

    docker compose exec -T api python scripts/discover_sync.py \\
        --region 14 --district 72 --max-pages 25

The defaults match the new Brno-město beat entry: byty prodej.
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import UTC
from typing import Any

from sqlalchemy import func, select

from db.orm import Listing, Property, RawListing, Source
from db.session import session_scope
from scraper.base import RawDocument, get_source
from scraper.storage import get_raw, put_raw
from worker.tasks.normalize import normalize_from_raw


def _link_property_inline(listing_id: int, parsed: dict[str, Any]) -> None:
    """Create or attach a Property row from parsed geo + locality fields.

    Mirrors scripts/reparse_sreality.py — same shape, kept duplicated rather
    than imported because both scripts are throw-away seeders.
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="sreality")
    ap.add_argument("--region", type=int, required=True)
    ap.add_argument("--district", type=int, default=None)
    ap.add_argument("--category-main", type=int, default=1)  # byty
    ap.add_argument("--category-type", type=int, default=1)  # prodej
    ap.add_argument("--max-pages", type=int, default=25)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    source = get_source(args.source)
    params: dict[str, Any] = {
        "region": args.region,
        "category_main": args.category_main,
        "category_type": args.category_type,
        "max_pages": args.max_pages,
    }
    if args.district is not None:
        params["district"] = args.district

    print(f"discover {args.source} params={params}", flush=True)

    with session_scope() as db:
        source_id = db.execute(
            select(Source.id).where(Source.slug == args.source)
        ).scalar_one()

    discovered = 0
    fetched = 0
    parsed_ok = 0
    skipped_unchanged = 0
    linked = 0
    errors = 0

    for ref in source.discover(params):
        discovered += 1
        if args.limit is not None and discovered > args.limit:
            break

        try:
            raw: RawDocument = source.fetch(ref)
        except Exception as e:  # noqa: BLE001
            errors += 1
            if errors <= 5:
                print(f"  fetch err {ref.source_listing_id}: {e}", flush=True)
            continue
        fetched += 1

        s3_key, content_hash = put_raw(
            source_slug=args.source,
            source_listing_id=ref.source_listing_id,
            fetched_at=raw.fetched_at,
            content_bytes=raw.content_bytes,
            content_type=raw.content_type,
        )

        with session_scope() as db:
            prev_hash = db.execute(
                select(RawListing.content_hash)
                .where(
                    RawListing.source_id == source_id,
                    RawListing.source_listing_id == ref.source_listing_id,
                )
                .order_by(RawListing.fetched_at.desc())
                .limit(1)
            ).scalar_one_or_none()
            row = RawListing(
                source_id=source_id,
                source_listing_id=ref.source_listing_id,
                fetched_at=raw.fetched_at,
                url=raw.url,
                http_status=raw.http_status,
                content_hash=content_hash,
                raw_s3_key=s3_key,
            )
            db.add(row)
            db.flush()
            raw_id = int(row.id)
            unchanged = prev_hash == content_hash

        if unchanged:
            # Content hash matches the prior fetch — leave the new row with
            # parse_status NULL; existing parsed_jsonb/listing already cover
            # this estate.
            skipped_unchanged += 1
            continue

        # Parse + persist parsed_jsonb
        try:
            parsed = source.parse(raw)
        except Exception as e:  # noqa: BLE001
            errors += 1
            if errors <= 5:
                print(f"  parse err {ref.source_listing_id}: {e}", flush=True)
            with session_scope() as db:
                row = db.get(RawListing, raw_id)
                if row is not None:
                    row.parse_status = "quarantine"
                    row.parse_error = f"{type(e).__name__}: {e}"[:1000]
            continue

        with session_scope() as db:
            row = db.get(RawListing, raw_id)
            if row is None:
                continue
            row.parsed_jsonb = parsed.model_dump(mode="json")
            row.parser_version = parsed.parser_version
            row.parse_status = "ok"

        parsed_ok += 1

        res = normalize_from_raw(raw_id)
        listing_id = res.get("listing_id") if isinstance(res, dict) else None
        if isinstance(listing_id, int):
            _link_property_inline(listing_id, parsed.model_dump(mode="json"))
            linked += 1

        if discovered % 50 == 0:
            print(
                f"  discovered={discovered} fetched={fetched} parsed={parsed_ok} "
                f"linked={linked} unchanged={skipped_unchanged} errors={errors}",
                flush=True,
            )

    print(
        f"\ndone. discovered={discovered} fetched={fetched} parsed={parsed_ok} "
        f"linked={linked} unchanged={skipped_unchanged} errors={errors}",
        flush=True,
    )
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
