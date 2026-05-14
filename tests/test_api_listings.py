"""API tests for the listings search, detail, and map endpoints.

These hit a real Postgres/PostGIS via the `seeded_listings` fixture. The
fixture uses synthetic district names and remote coordinates so assertions
isolate exactly the seeded rows even when the DB already holds real data.
"""
from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import SeededData

DISTRICT_A = "TEST-DISTRICT-A"  # properties: smichov; listings: 2+kk, 1+kk
DISTRICT_B = "TEST-DISTRICT-B"  # property: vinohrady; listing: 3+1

# A tight box around the fixture's synthetic coordinates (13.00, 49.00).
TEST_BBOX = {
    "min_lon": 12.99,
    "min_lat": 48.99,
    "max_lon": 13.01,
    "max_lat": 49.01,
}


@pytest.fixture
def client() -> TestClient:
    from api.main import app

    return TestClient(app)


def _by_id(rows: list[dict[str, Any]], listing_id: int) -> dict[str, Any] | None:
    return next((r for r in rows if r["id"] == listing_id), None)


# ---------------------------------------------------------------------------
# GET /v1/listings
# ---------------------------------------------------------------------------


class TestListListings:
    def test_seeded_listings_are_returned(
        self, client: TestClient, seeded_listings: SeededData
    ) -> None:
        # Newest-first ordering puts the just-inserted fixture rows up front.
        r = client.get("/v1/listings", params={"limit": 200})
        assert r.status_code == 200
        body = r.json()
        ids = {row["id"] for row in body["data"]}
        assert {
            seeded_listings.listing_smichov_2kk,
            seeded_listings.listing_vinohrady_3_1,
            seeded_listings.listing_smichov_1kk,
            seeded_listings.listing_unlinked,
        } <= ids
        assert body["meta"]["total"] >= 4

    def test_linked_listing_has_coordinates_and_locality(
        self, client: TestClient, seeded_listings: SeededData
    ) -> None:
        r = client.get("/v1/listings", params={"city_district": DISTRICT_A})
        row = _by_id(r.json()["data"], seeded_listings.listing_smichov_2kk)
        assert row is not None
        assert row["city_district"] == DISTRICT_A
        assert row["locality"] == "TEST Locality A"
        assert row["lat"] == pytest.approx(49.0010, abs=1e-4)
        assert row["lon"] == pytest.approx(13.0010, abs=1e-4)

    def test_unlinked_listing_has_null_geo(
        self, client: TestClient, seeded_listings: SeededData
    ) -> None:
        r = client.get("/v1/listings", params={"limit": 200})
        row = _by_id(r.json()["data"], seeded_listings.listing_unlinked)
        assert row is not None
        assert row["lat"] is None
        assert row["city_district"] is None

    def test_filter_by_city_district(
        self, client: TestClient, seeded_listings: SeededData
    ) -> None:
        r = client.get("/v1/listings", params={"city_district": DISTRICT_A})
        ids = {row["id"] for row in r.json()["data"]}
        assert ids == {
            seeded_listings.listing_smichov_2kk,
            seeded_listings.listing_smichov_1kk,
        }

    def test_filter_by_ownership_type(
        self, client: TestClient, seeded_listings: SeededData
    ) -> None:
        r = client.get(
            "/v1/listings",
            params={"city_district": DISTRICT_B, "ownership_type": "druzstevni"},
        )
        body = r.json()
        assert {row["id"] for row in body["data"]} == {
            seeded_listings.listing_vinohrady_3_1
        }

    def test_filter_by_price_range(
        self, client: TestClient, seeded_listings: SeededData
    ) -> None:
        r = client.get(
            "/v1/listings",
            params={
                "city_district": DISTRICT_A,
                "min_price": 6_000_000,
                "max_price": 7_000_000,
            },
        )
        assert {row["id"] for row in r.json()["data"]} == {
            seeded_listings.listing_smichov_2kk
        }

    def test_filter_by_size_range(
        self, client: TestClient, seeded_listings: SeededData
    ) -> None:
        r = client.get(
            "/v1/listings",
            params={"city_district": DISTRICT_B, "min_size": 80},
        )
        assert {row["id"] for row in r.json()["data"]} == {
            seeded_listings.listing_vinohrady_3_1
        }


# ---------------------------------------------------------------------------
# GET /v1/listings/{id}
# ---------------------------------------------------------------------------


class TestListingDetail:
    def test_detail_includes_photos_and_coords(
        self, client: TestClient, seeded_listings: SeededData
    ) -> None:
        r = client.get(f"/v1/listings/{seeded_listings.listing_smichov_2kk}")
        assert r.status_code == 200
        body = r.json()
        assert body["disposition"] == "2+kk"
        assert body["ownership_type"] == "osobni"
        assert body["postcode"] == "150 00"
        assert body["lat"] == pytest.approx(49.0010, abs=1e-4)
        assert len(body["photos"]) == 2
        assert body["photos"][0]["url"] == "https://img/1.jpg"

    def test_detail_unknown_id_returns_404(self, client: TestClient) -> None:
        r = client.get("/v1/listings/999999999")
        assert r.status_code == 404

    def test_detail_of_unlinked_listing_has_null_address(
        self, client: TestClient, seeded_listings: SeededData
    ) -> None:
        r = client.get(f"/v1/listings/{seeded_listings.listing_unlinked}")
        assert r.status_code == 200
        body = r.json()
        assert body["postcode"] is None
        assert body["photos"] == []


# ---------------------------------------------------------------------------
# GET /v1/listings/map
# ---------------------------------------------------------------------------


class TestMapListings:
    def test_pins_at_high_zoom(
        self, client: TestClient, seeded_listings: SeededData
    ) -> None:
        r = client.get("/v1/listings/map", params={**TEST_BBOX, "zoom": 15})
        assert r.status_code == 200
        body = r.json()
        assert body["mode"] == "pins"
        ids = {pin["id"] for pin in body["pins"]}
        # The three linked listings appear; the unlinked one does not.
        assert ids == {
            seeded_listings.listing_smichov_2kk,
            seeded_listings.listing_vinohrady_3_1,
            seeded_listings.listing_smichov_1kk,
        }

    def test_clusters_at_low_zoom(
        self, client: TestClient, seeded_listings: SeededData
    ) -> None:
        r = client.get("/v1/listings/map", params={**TEST_BBOX, "zoom": 10})
        assert r.status_code == 200
        body = r.json()
        assert body["mode"] == "clusters"
        total = sum(c["count"] for c in body["clusters"])
        assert total == 3  # the three linked listings

    def test_inverted_bbox_is_422(self, client: TestClient) -> None:
        r = client.get(
            "/v1/listings/map",
            params={
                "min_lon": 14.7,
                "min_lat": 50.2,
                "max_lon": 14.2,
                "max_lat": 49.9,
                "zoom": 15,
            },
        )
        assert r.status_code == 422

    def test_empty_bbox_returns_no_pins(self, client: TestClient) -> None:
        # A bbox in the Atlantic — nothing there.
        r = client.get(
            "/v1/listings/map",
            params={
                "min_lon": -30.0,
                "min_lat": 0.0,
                "max_lon": -29.0,
                "max_lat": 1.0,
                "zoom": 15,
            },
        )
        assert r.status_code == 200
        assert r.json()["pins"] == []
