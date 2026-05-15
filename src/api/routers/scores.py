"""Per-listing score endpoints.

Reads the latest composite score from the ``score_latest`` materialized view
(populated by the Week-5 scoring job) and exposes the full per-listing score
history from the underlying ``score`` table.

Per ``docs/SCORING.md`` rule: scores with ``confidence_score < 0.3`` are
hidden from public endpoints. The ``/score`` endpoint accepts an opt-in
``?include_low_confidence=true`` flag for admin use; ``/scores`` (history)
is unfiltered because it exists for transparency.
"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from db.orm import Score
from db.session import get_session_factory

router = APIRouter(prefix="/listings", tags=["scores"])

# Per docs/SCORING.md: scores below this confidence are hidden from public
# lists and treated as "not yet confidently scored" by the public API.
_PUBLIC_CONFIDENCE_THRESHOLD = Decimal("0.3")


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


class ScoreOut(BaseModel):
    listing_id: int
    model_version: str
    computed_at: datetime
    composite: Decimal | None
    undervaluation_pct: Decimal | None
    undervaluation_abs: Decimal | None
    yield_gross_pct: Decimal | None
    yield_confidence: Decimal | None
    liquidity_score: Decimal | None
    location_score: Decimal | None
    risk_score: Decimal | None
    confidence_score: Decimal | None
    risk_flags: list[str]
    components: dict[str, Any]


class ScoreHistory(BaseModel):
    items: list[ScoreOut]
    total: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_to_score_out(row: Any) -> ScoreOut:
    """Map a row from ``score_latest`` or the ``score`` table to ScoreOut.

    Works for both raw SQL Row objects (``score_latest``) and ORM Score
    instances, since both expose the same attribute names.
    """
    risk_flags = list(getattr(row, "risk_flags", None) or [])
    components_raw = getattr(row, "components_jsonb", None) or {}
    return ScoreOut(
        listing_id=int(row.listing_id),
        model_version=str(row.model_version),
        computed_at=row.computed_at,
        composite=row.composite,
        undervaluation_pct=row.undervaluation_pct,
        undervaluation_abs=row.undervaluation_abs,
        yield_gross_pct=row.yield_gross_pct,
        yield_confidence=row.yield_confidence,
        liquidity_score=row.liquidity_score,
        location_score=row.location_score,
        risk_score=row.risk_score,
        confidence_score=row.confidence_score,
        risk_flags=risk_flags,
        components=dict(components_raw),
    )


def _is_low_confidence(confidence: Decimal | None) -> bool:
    """Return True if a score is below the public-display threshold.

    A NULL confidence is treated as low (we don't know how good it is).
    """
    if confidence is None:
        return True
    return Decimal(confidence) < _PUBLIC_CONFIDENCE_THRESHOLD


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/{listing_id}/score", response_model=ScoreOut)
def get_listing_score(
    listing_id: int,
    db: Annotated[Session, Depends(get_db)],
    include_low_confidence: bool = Query(
        False,
        description=(
            "If true, return scores even when confidence_score < 0.3. "
            "Default false (public behaviour)."
        ),
    ),
) -> ScoreOut:
    """Latest score for one listing, read from the ``score_latest`` mview.

    Returns 404 if no score row exists for the listing, or if the latest
    score is below the public confidence threshold (unless
    ``include_low_confidence=true``).
    """
    # Raw SQL against the mview — keeping it off the ORM avoids polluting
    # orm.py with a stub class for a relation that's read-only by design.
    row = db.execute(
        sa.text("SELECT * FROM score_latest WHERE listing_id = :id"),
        {"id": listing_id},
    ).mappings().one_or_none()

    if row is None:
        raise HTTPException(status_code=404, detail="No score for listing")

    # mappings() gives a dict-like; expose as attributes via SimpleNamespace.
    score_row = _MappingProxy(row)

    if not include_low_confidence and _is_low_confidence(score_row.confidence_score):
        raise HTTPException(
            status_code=404,
            detail="Listing not yet confidently scored",
        )

    return _row_to_score_out(score_row)


@router.get("/{listing_id}/scores", response_model=ScoreHistory)
def get_listing_score_history(
    listing_id: int,
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> ScoreHistory:
    """Full score history for one listing across model_versions, newest first.

    No confidence filtering — history is for transparency and may include
    early low-confidence rows.
    """
    total = db.execute(
        select(sa.func.count())
        .select_from(Score)
        .where(Score.listing_id == listing_id)
    ).scalar_one()

    rows = db.execute(
        select(Score)
        .where(Score.listing_id == listing_id)
        .order_by(Score.computed_at.desc())
        .limit(limit)
        .offset(offset)
    ).scalars().all()

    return ScoreHistory(
        items=[_row_to_score_out(r) for r in rows],
        total=int(total),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


class _MappingProxy:
    """Tiny attribute-access wrapper around a SQLAlchemy RowMapping.

    Lets ``_row_to_score_out`` use ``row.foo`` uniformly for both ORM rows
    and raw mapping rows from the score_latest mview.
    """

    __slots__ = ("_m",)

    def __init__(self, mapping: Any) -> None:
        self._m = mapping

    def __getattr__(self, item: str) -> Any:
        try:
            return self._m[item]
        except KeyError as exc:
            raise AttributeError(item) from exc
