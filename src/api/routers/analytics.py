"""Analytics API — aggregate views over active listings.

Powers the /analytics dashboard: groups active listings by disposition or
locality and returns count, avg/min/max price, avg & median ppm², a centroid
for map plotting, and a 6-month change in median ppm² (computed against
listing_version snapshots). Filters mirror /v1/listings so the UI can
propagate the search bar straight through.
"""
from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from db.session import get_session_factory

router = APIRouter(prefix="/analytics", tags=["analytics"])


def get_db() -> Iterator[Session]:
    factory = get_session_factory()
    session = factory()
    try:
        yield session
    finally:
        session.close()


GroupBy = Literal["disposition", "locality", "city_district"]

# group_by → SQL expression that yields the group key.
# Kept as a fixed mapping (not user-substituted) so the SQL stays injection-safe.
_GROUP_EXPR: dict[GroupBy, str] = {
    "disposition": "COALESCE(l.disposition, '(neuvedeno)')",
    "locality": "COALESCE(p.locality, '(neuvedeno)')",
    "city_district": "COALESCE(p.city_district, '(neuvedeno)')",
}


class BreakdownRow(BaseModel):
    group_key: str
    count: int
    avg_price_czk: Decimal | None
    min_price_czk: Decimal | None
    max_price_czk: Decimal | None
    avg_ppm2: Decimal | None
    median_ppm2: Decimal | None
    median_ppm2_180d_ago: Decimal | None
    change_pct_6m: float | None
    centroid_lat: float | None
    centroid_lon: float | None


class BreakdownResponse(BaseModel):
    group_by: GroupBy
    rows: list[BreakdownRow]


@router.get("/breakdown", response_model=BreakdownResponse)
def breakdown(
    db: Annotated[Session, Depends(get_db)],
    group_by: GroupBy = Query("disposition"),
    property_type: str | None = None,
    disposition: str | None = None,
    ownership_type: str | None = None,
    city_district: str | None = None,
    min_price: int | None = Query(None, ge=0),
    max_price: int | None = Query(None, ge=0),
    min_size: int | None = Query(None, ge=0),
    max_size: int | None = Query(None, ge=0),
) -> BreakdownResponse:
    """Aggregate active listings into groups (by disposition or locality).

    For each group:
      * count, avg/min/max price, avg & median ppm² (currently active).
      * centroid lat/lon of properties in the group (for map plotting).
      * median ppm² 180 days ago for listings that already existed then,
        plus the percentage change to today's median.

    The 180-day snapshot uses each listing's `listing_version` history to
    find its price at that point; listings with no versions are assumed to
    have held their current price.
    """
    group_expr = _GROUP_EXPR[group_by]

    where: list[str] = [
        "l.status = 'active'",
        "l.price IS NOT NULL",
        "l.size_m2 IS NOT NULL",
        "l.size_m2 > 0",
    ]
    params: dict[str, Any] = {}
    if property_type:
        where.append("l.property_type = :property_type")
        params["property_type"] = property_type
    if disposition:
        where.append("l.disposition = :disposition")
        params["disposition"] = disposition
    if ownership_type:
        where.append("l.ownership_type = :ownership_type")
        params["ownership_type"] = ownership_type
    if city_district:
        where.append("p.city_district = :city_district")
        params["city_district"] = city_district
    if min_price is not None:
        where.append("l.price >= :min_price")
        params["min_price"] = min_price
    if max_price is not None:
        where.append("l.price <= :max_price")
        params["max_price"] = max_price
    if min_size is not None:
        where.append("l.size_m2 >= :min_size")
        params["min_size"] = min_size
    if max_size is not None:
        where.append("l.size_m2 <= :max_size")
        params["max_size"] = max_size

    where_sql = " AND ".join(where)

    sql = f"""
    WITH active AS (
        SELECT l.id,
               l.price,
               l.size_m2,
               l.first_seen_at,
               {group_expr} AS group_key,
               p.geom::geometry AS geom
        FROM listing l
        LEFT JOIN property p ON p.id = l.property_id
        WHERE {where_sql}
    ),
    today_agg AS (
        SELECT group_key,
               COUNT(*)                                              AS n,
               AVG(price)                                            AS avg_price,
               MIN(price)                                            AS min_price,
               MAX(price)                                            AS max_price,
               AVG(price / size_m2)                                  AS avg_ppm2,
               PERCENTILE_CONT(0.5) WITHIN GROUP
                   (ORDER BY price / size_m2)                        AS median_ppm2,
               ST_Y(ST_Centroid(ST_Collect(geom)))                   AS lat,
               ST_X(ST_Centroid(ST_Collect(geom)))                   AS lon
        FROM active
        GROUP BY group_key
    ),
    then_prices AS (
        SELECT a.group_key,
               a.size_m2,
               COALESCE(
                   (SELECT lv.price
                      FROM listing_version lv
                     WHERE lv.listing_id = a.id
                       AND lv.observed_at <= NOW() - INTERVAL '180 days'
                       AND lv.price IS NOT NULL
                     ORDER BY lv.observed_at DESC
                     LIMIT 1),
                   a.price
               ) AS price_then
        FROM active a
        WHERE a.first_seen_at <= NOW() - INTERVAL '180 days'
    ),
    then_agg AS (
        SELECT group_key,
               PERCENTILE_CONT(0.5) WITHIN GROUP
                   (ORDER BY price_then / size_m2)                   AS median_ppm2_then
        FROM then_prices
        WHERE price_then IS NOT NULL
        GROUP BY group_key
    )
    SELECT t.group_key,
           t.n,
           t.avg_price,
           t.min_price,
           t.max_price,
           t.avg_ppm2,
           t.median_ppm2,
           th.median_ppm2_then,
           t.lat,
           t.lon
    FROM today_agg t
    LEFT JOIN then_agg th USING (group_key)
    ORDER BY t.n DESC
    """

    stmt = text(sql)
    for name in params:
        stmt = stmt.bindparams(bindparam(name))
    rows = db.execute(stmt, params).all()

    out: list[BreakdownRow] = []
    for r in rows:
        median_now = r.median_ppm2
        median_then = r.median_ppm2_then
        change_pct: float | None = None
        if median_now is not None and median_then is not None and median_then > 0:
            change_pct = float((median_now - median_then) / median_then * 100)
        out.append(
            BreakdownRow(
                group_key=str(r.group_key),
                count=int(r.n),
                avg_price_czk=r.avg_price,
                min_price_czk=r.min_price,
                max_price_czk=r.max_price,
                avg_ppm2=r.avg_ppm2,
                median_ppm2=r.median_ppm2,
                median_ppm2_180d_ago=r.median_ppm2_then,
                change_pct_6m=change_pct,
                centroid_lat=float(r.lat) if r.lat is not None else None,
                centroid_lon=float(r.lon) if r.lon is not None else None,
            )
        )

    return BreakdownResponse(group_by=group_by, rows=out)
