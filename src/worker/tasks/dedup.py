"""Dedup tier 1: collapse same-source duplicates within one property.

A flat that gets relisted (new `source_listing_id`, same physical unit)
shows up as several `listing` rows on the same property. Tier 1 clusters
them by (source, size, disposition, ownership_type) — the attributes that
are stable across a relist. Cross-source dedup (tier 2/3) is Phase 2.

Triggered per property by the geocode stage. Clustering is recomputed for
the whole property each run so it stays correct as listings come and go.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from celery import shared_task
from sqlalchemy import select

from db.orm import DedupCluster, Listing
from db.session import session_scope
from shared.logging import get_logger

log = get_logger("worker.dedup")

_METHOD = "tier1_same_source"
_CONFIDENCE = Decimal("0.9")


@dataclass(frozen=True)
class DedupRow:
    """The fields tier-1 clustering needs from a listing."""

    listing_id: int
    source_id: int
    first_seen_at: datetime
    size_m2: Decimal | None
    disposition: str | None
    ownership_type: str | None


def _size_bucket(size_m2: Decimal | None) -> int | None:
    """Round area to whole m². None when unknown — unknown size can't cluster."""
    if size_m2 is None:
        return None
    return int(size_m2.to_integral_value())


def cluster_same_source(rows: list[DedupRow]) -> list[list[int]]:
    """Group listings that are the same physical unit relisted on one source.

    Returns one list of listing ids per cluster of size >= 2, each ordered
    canonical-first (earliest first_seen, then lowest id). Listings with an
    unknown size are never clustered — too risky without a second signal.
    """
    groups: dict[tuple[int, int, str | None, str | None], list[DedupRow]] = {}
    for r in rows:
        bucket = _size_bucket(r.size_m2)
        if bucket is None:
            continue
        key = (r.source_id, bucket, r.disposition, r.ownership_type)
        groups.setdefault(key, []).append(r)

    clusters: list[list[int]] = []
    for members in groups.values():
        if len(members) < 2:
            continue
        ordered = sorted(members, key=lambda m: (m.first_seen_at, m.listing_id))
        clusters.append([m.listing_id for m in ordered])
    return clusters


@shared_task(name="dedup.tier1", bind=False)
def dedup_tier1(property_id: int) -> dict[str, Any]:
    """Recompute tier-1 dedup clusters for one property."""
    with session_scope() as db:
        listings = list(
            db.execute(
                select(Listing).where(
                    Listing.property_id == property_id,
                    Listing.status == "active",
                )
            ).scalars()
        )
        if not listings:
            return {"status": "empty", "property_id": property_id}

        rows = [
            DedupRow(
                listing_id=int(listing.id),
                source_id=int(listing.source_id),
                first_seen_at=listing.first_seen_at,
                size_m2=listing.size_m2,
                disposition=listing.disposition,
                ownership_type=listing.ownership_type,
            )
            for listing in listings
        ]
        clusters = cluster_same_source(rows)

        by_id = {int(listing.id): listing for listing in listings}
        clustered_ids: set[int] = set()
        cluster_count = 0

        for member_ids in clusters:
            canonical_id = member_ids[0]
            # Reuse a cluster row already attached to one of these members,
            # otherwise create a fresh one.
            existing_cluster_id = next(
                (
                    by_id[mid].dedup_cluster_id
                    for mid in member_ids
                    if by_id[mid].dedup_cluster_id is not None
                ),
                None,
            )
            if existing_cluster_id is not None:
                cluster = db.get(DedupCluster, existing_cluster_id)
            else:
                cluster = None
            if cluster is None:
                cluster = DedupCluster(method=_METHOD, confidence=_CONFIDENCE)
                db.add(cluster)
                db.flush()
            cluster.canonical_listing_id = canonical_id
            cluster.method = _METHOD
            cluster.confidence = _CONFIDENCE

            for mid in member_ids:
                by_id[mid].dedup_cluster_id = int(cluster.id)
                clustered_ids.add(mid)
            cluster_count += 1

        # Listings no longer part of any cluster lose their cluster id.
        for listing in listings:
            if int(listing.id) not in clustered_ids and listing.dedup_cluster_id is not None:
                listing.dedup_cluster_id = None

    log.info(
        "dedup.tier1.done",
        property_id=property_id,
        listings=len(listings),
        clusters=cluster_count,
        clustered_listings=len(clustered_ids),
    )
    return {
        "status": "ok",
        "property_id": property_id,
        "listings": len(listings),
        "clusters": cluster_count,
        "clustered_listings": len(clustered_ids),
    }
