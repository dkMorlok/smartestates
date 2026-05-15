"""API tests for the per-listing score endpoints.

Unlike the listings tests, these do NOT use the real Postgres ``seeded_listings``
fixture. The Week-5 scoring job is required to populate ``score_latest`` and
``score`` rows, but standing that up just for an API test is heavy and
brittle. Instead we override the router's ``get_db`` dependency with a fake
session that intercepts the small set of statements the router executes.

This lets us exercise the public contract:
- 404 when no score row exists
- 404 when the latest score is below the public confidence threshold
- ``?include_low_confidence=true`` reveals low-confidence scores
- /scores returns rows newest-first with limit + offset honoured
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.routers import scores as scores_router

# ---------------------------------------------------------------------------
# Fake DB plumbing
# ---------------------------------------------------------------------------


class _FakeRowMapping:
    """Behaves like a SQLAlchemy RowMapping (subscriptable)."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def __getitem__(self, key: str) -> Any:
        return self._data[key]


class _FakeMappingsResult:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row

    def one_or_none(self) -> _FakeRowMapping | None:
        return _FakeRowMapping(self._row) if self._row is not None else None


class _FakeRawResult:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row

    def mappings(self) -> _FakeMappingsResult:
        return _FakeMappingsResult(self._row)


class _FakeOrmObject:
    """Stands in for an ORM ``Score`` row in scalars().all()."""

    def __init__(self, data: dict[str, Any]) -> None:
        for k, v in data.items():
            setattr(self, k, v)


class _FakeScalarsResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def all(self) -> list[_FakeOrmObject]:
        return [_FakeOrmObject(r) for r in self._rows]


class _FakeOrmResult:
    def __init__(
        self,
        *,
        scalar: int | None = None,
        rows: list[dict[str, Any]] | None = None,
    ) -> None:
        self._scalar = scalar
        self._rows = rows or []

    def scalar_one(self) -> int:
        assert self._scalar is not None
        return self._scalar

    def scalars(self) -> _FakeScalarsResult:
        return _FakeScalarsResult(self._rows)


class FakeSession:
    """Minimal session that routes statements based on a simple selector.

    The scores router executes exactly two kinds of statements:
    1. ``sa.text("SELECT * FROM score_latest WHERE listing_id = :id")``
       — for the /score endpoint.
    2. SELECT count() and SELECT Score ORM statements — for /scores.

    We dispatch on the presence of ``score_latest`` in the compiled SQL.
    """

    def __init__(
        self,
        *,
        latest_row: dict[str, Any] | None = None,
        history_rows: list[dict[str, Any]] | None = None,
    ) -> None:
        self.latest_row = latest_row
        self.history_rows = history_rows or []
        # Track captured limit/offset for assertions on pagination.
        self.last_limit: int | None = None
        self.last_offset: int | None = None

    def execute(self, statement: Any, params: dict[str, Any] | None = None) -> Any:
        sql_str = str(statement).lower()

        if "score_latest" in sql_str:
            return _FakeRawResult(self.latest_row)

        if "count(" in sql_str:
            return _FakeOrmResult(scalar=len(self.history_rows))

        # Otherwise treat as the Score history select. Try to extract
        # LIMIT/OFFSET from the compiled SQL (best-effort).
        self.last_limit, self.last_offset = _parse_limit_offset(statement)
        sliced = _apply_slice(
            self.history_rows, self.last_limit, self.last_offset
        )
        return _FakeOrmResult(rows=sliced)

    def close(self) -> None:  # pragma: no cover - interface compat
        pass


def _parse_limit_offset(statement: Any) -> tuple[int | None, int | None]:
    """Pull LIMIT/OFFSET values from a compiled SQLAlchemy statement."""
    try:
        compiled = statement.compile(compile_kwargs={"literal_binds": True})
    except Exception:  # pragma: no cover - defensive
        return None, None
    text = str(compiled).lower()
    limit = _find_int_after(text, "limit ")
    offset = _find_int_after(text, "offset ")
    return limit, offset


def _find_int_after(text: str, marker: str) -> int | None:
    idx = text.find(marker)
    if idx == -1:
        return None
    rest = text[idx + len(marker):].strip()
    digits = ""
    for ch in rest:
        if ch.isdigit():
            digits += ch
        else:
            break
    return int(digits) if digits else None


def _apply_slice(
    rows: list[dict[str, Any]], limit: int | None, offset: int | None
) -> list[dict[str, Any]]:
    start = offset or 0
    end = start + limit if limit is not None else None
    return rows[start:end]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_session() -> FakeSession:
    return FakeSession()


@pytest.fixture
def client(fake_session: FakeSession) -> Any:
    """TestClient with the scores router's get_db overridden."""

    def _override() -> Any:
        yield fake_session

    app.dependency_overrides[scores_router.get_db] = _override
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(scores_router.get_db, None)


def _score_row(
    *,
    listing_id: int = 42,
    model_version: str = "v0.1",
    computed_at: datetime | None = None,
    composite: str | None = "78.5",
    confidence: str | None = "0.62",
    risk_flags: list[str] | None = None,
    components: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "listing_id": listing_id,
        "model_version": model_version,
        "computed_at": computed_at or datetime(2026, 5, 14, 12, 0, tzinfo=UTC),
        "composite": Decimal(composite) if composite is not None else None,
        "undervaluation_pct": Decimal("-8.2"),
        "undervaluation_abs": Decimal("-420000.00"),
        "yield_gross_pct": Decimal("4.30"),
        "yield_confidence": Decimal("0.55"),
        "liquidity_score": Decimal("62.10"),
        "location_score": Decimal("71.00"),
        "risk_score": Decimal("12.40"),
        "confidence_score": Decimal(confidence) if confidence is not None else None,
        "risk_flags": risk_flags if risk_flags is not None else ["panel_pre_1980"],
        "components_jsonb": components if components is not None else {
            "ppm2_predicted": 105000.0,
            "ppm2_observed": 96400.0,
        },
    }


# ---------------------------------------------------------------------------
# GET /v1/listings/{id}/score
# ---------------------------------------------------------------------------


class TestGetListingScore:
    def test_returns_404_when_no_score_row(
        self, client: TestClient, fake_session: FakeSession
    ) -> None:
        fake_session.latest_row = None
        r = client.get("/v1/listings/123/score")
        assert r.status_code == 404
        assert "no score" in r.json()["detail"].lower()

    def test_returns_latest_score_when_confident(
        self, client: TestClient, fake_session: FakeSession
    ) -> None:
        fake_session.latest_row = _score_row(listing_id=42, confidence="0.62")
        r = client.get("/v1/listings/42/score")
        assert r.status_code == 200
        body = r.json()
        assert body["listing_id"] == 42
        assert body["model_version"] == "v0.1"
        assert Decimal(body["composite"]) == Decimal("78.5")
        assert Decimal(body["confidence_score"]) == Decimal("0.62")
        assert body["risk_flags"] == ["panel_pre_1980"]
        assert body["components"]["ppm2_predicted"] == 105000.0

    def test_low_confidence_hidden_by_default(
        self, client: TestClient, fake_session: FakeSession
    ) -> None:
        fake_session.latest_row = _score_row(confidence="0.20")
        r = client.get("/v1/listings/42/score")
        assert r.status_code == 404
        assert "confident" in r.json()["detail"].lower()

    def test_low_confidence_surfaced_with_flag(
        self, client: TestClient, fake_session: FakeSession
    ) -> None:
        fake_session.latest_row = _score_row(confidence="0.20")
        r = client.get(
            "/v1/listings/42/score",
            params={"include_low_confidence": "true"},
        )
        assert r.status_code == 200
        assert Decimal(r.json()["confidence_score"]) == Decimal("0.20")

    def test_null_confidence_treated_as_low(
        self, client: TestClient, fake_session: FakeSession
    ) -> None:
        fake_session.latest_row = _score_row(confidence=None)
        r = client.get("/v1/listings/42/score")
        assert r.status_code == 404
        # …but admin opt-in surfaces it.
        r2 = client.get(
            "/v1/listings/42/score",
            params={"include_low_confidence": "true"},
        )
        assert r2.status_code == 200
        assert r2.json()["confidence_score"] is None


# ---------------------------------------------------------------------------
# GET /v1/listings/{id}/scores
# ---------------------------------------------------------------------------


class TestGetListingScoreHistory:
    def test_returns_multiple_versions_newest_first(
        self, client: TestClient, fake_session: FakeSession
    ) -> None:
        # The router orders by computed_at DESC server-side; here we just
        # provide rows already in the order the SQL would return them.
        now = datetime(2026, 5, 14, 12, 0, tzinfo=UTC)
        fake_session.history_rows = [
            _score_row(model_version="v0.2", computed_at=now),
            _score_row(model_version="v0.1", computed_at=now - timedelta(days=7)),
            _score_row(
                model_version="v0.0",
                computed_at=now - timedelta(days=14),
                confidence="0.10",  # low-conf rows are NOT filtered from history
            ),
        ]
        r = client.get("/v1/listings/42/scores")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 3
        assert [item["model_version"] for item in body["items"]] == [
            "v0.2",
            "v0.1",
            "v0.0",
        ]
        # The low-confidence row is present — history is for transparency.
        assert Decimal(body["items"][2]["confidence_score"]) == Decimal("0.10")

    def test_empty_history_returns_empty_items(
        self, client: TestClient, fake_session: FakeSession
    ) -> None:
        fake_session.history_rows = []
        r = client.get("/v1/listings/9999/scores")
        assert r.status_code == 200
        body = r.json()
        assert body == {"items": [], "total": 0}

    def test_respects_limit_and_offset(
        self, client: TestClient, fake_session: FakeSession
    ) -> None:
        now = datetime(2026, 5, 14, 12, 0, tzinfo=UTC)
        fake_session.history_rows = [
            _score_row(model_version=f"v0.{i}", computed_at=now - timedelta(days=i))
            for i in range(5)
        ]
        r = client.get(
            "/v1/listings/42/scores",
            params={"limit": 2, "offset": 1},
        )
        assert r.status_code == 200
        body = r.json()
        # total reflects all rows; items reflects the page.
        assert body["total"] == 5
        assert len(body["items"]) == 2
        assert [item["model_version"] for item in body["items"]] == ["v0.1", "v0.2"]
        # And the captured LIMIT/OFFSET match what we sent.
        assert fake_session.last_limit == 2
        assert fake_session.last_offset == 1
