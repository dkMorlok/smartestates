"""Normalize stage: write parsed payload into the canonical `listing` table.

Geocoding and dedup happen in later stages (Week 3).
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from celery import shared_task
from sqlalchemy import select

from db.orm import Listing, Photo, RawListing
from db.session import session_scope
from shared.logging import get_logger

log = get_logger("worker.normalize")


def _safe_decimal(v: Any) -> Decimal | None:
    if v is None:
        return None
    try:
        return Decimal(str(v))
    except Exception:
        return None


@shared_task(name="normalize.from_raw", bind=False)
def normalize_from_raw(raw_listing_id: int) -> dict[str, Any]:
    with session_scope() as db:
        row = db.get(RawListing, raw_listing_id)
        if row is None or row.parsed_jsonb is None:
            log.warning("normalize.skip_no_parsed", raw_listing_id=raw_listing_id)
            return {"status": "skipped"}

        parsed = row.parsed_jsonb
        now = datetime.now(tz=UTC)

        existing = db.execute(
            select(Listing).where(
                Listing.source_id == row.source_id,
                Listing.source_listing_id == row.source_listing_id,
            )
        ).scalar_one_or_none()

        # Map ParsedListing JSON to ORM Listing fields.
        features = {
            k: parsed.get(k)
            for k in [
                "has_balcony",
                "has_loggia",
                "has_terrace",
                "has_cellar",
                "has_lift",
                "has_parking",
                "has_garage",
                "has_garden",
                "furnished",
            ]
            if parsed.get(k) is not None
        }

        common_fields = {
            "source_id": row.source_id,
            "source_listing_id": row.source_listing_id,
            "canonical_url": parsed["canonical_url"],
            "last_seen_at": now,
            "status": parsed.get("status", "active"),
            "price": _safe_decimal(parsed.get("price_czk")),
            "currency": parsed.get("currency", "CZK"),
            "price_hidden": bool(parsed.get("price_hidden")),
            "size_m2": _safe_decimal(parsed.get("size_m2")),
            "usable_area_m2": _safe_decimal(parsed.get("usable_area_m2")),
            "land_area_m2": _safe_decimal(parsed.get("land_area_m2")),
            "rooms": parsed.get("rooms"),
            "bathrooms": parsed.get("bathrooms"),
            "floor_current": parsed.get("floor_current"),
            "floor_total": parsed.get("floor_total"),
            "year_built": parsed.get("year_built"),
            "property_type": parsed["property_type"],
            "disposition": parsed.get("disposition"),
            "ownership_type": parsed.get("ownership_type"),
            "building_type": parsed.get("building_type"),
            "condition": parsed.get("condition"),
            "energy_class": parsed.get("energy_class"),
            "features_jsonb": features,
            "description": parsed.get("description"),
            "agency": parsed.get("agency"),
            "agent_name": parsed.get("agent_name"),
            "is_owner_direct": parsed.get("is_owner_direct"),
            "raw_listing_id": raw_listing_id,
            "parser_version": parsed.get("parser_version"),
        }

        if existing is None:
            listing = Listing(
                first_seen_at=now,
                **common_fields,
            )
            db.add(listing)
            db.flush()
            listing_id = int(listing.id)
            created = True
        else:
            for k, v in common_fields.items():
                setattr(existing, k, v)
            listing_id = int(existing.id)
            created = False

        # Photos: simple replace (Week 1). Phase 2 introduces phash + diff.
        db.execute(Photo.__table__.delete().where(Photo.listing_id == listing_id))
        for i, ph in enumerate(parsed.get("photos") or []):
            db.add(
                Photo(
                    listing_id=listing_id,
                    ord=i,
                    url_source=ph["url"],
                    width=ph.get("width"),
                    height=ph.get("height"),
                )
            )

        log.info(
            "normalize.done",
            listing_id=listing_id,
            created=created,
            source_listing_id=row.source_listing_id,
        )
        return {"listing_id": listing_id, "created": created}
