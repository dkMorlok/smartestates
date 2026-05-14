"""Smoke tests for the FastAPI app. Readyz is skipped without a real DB."""
from __future__ import annotations

from fastapi.testclient import TestClient


def test_healthz_ok() -> None:
    from api.main import app

    with TestClient(app) as client:
        r = client.get("/healthz")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


def test_request_id_header_round_trip() -> None:
    from api.main import app

    with TestClient(app) as client:
        r = client.get("/healthz", headers={"x-request-id": "abc123"})
        assert r.headers.get("x-request-id") == "abc123"
