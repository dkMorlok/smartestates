"""Sreality source.

Uses the undocumented but stable JSON endpoints used by the sreality SPA:
  GET /api/cs/v2/estates?...     (search)
  GET /api/cs/v2/estates/{hash_id}  (detail)

Politeness: 1 rps sustained, identifies as RealitniSkener with contact email.
We snapshot every payload to S3, so re-fetch is not required after parser
changes.
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

from scraper.base import (
    ListingRef,
    RawDocument,
    Source,
    SourceHealth,
    register_source,
)
from scraper.http import NonRetryableHTTPError, get_with_retry, make_client
from scraper.ratelimit import TokenBucket
from shared.config import get_settings
from shared.logging import get_logger
from shared.schemas import ParsedListing

from .item_map import REGION_ID_TO_NAME
from .parse import PARSER_VERSION, parse_sreality_detail

log = get_logger("scraper.sreality")


@register_source
class SrealitySource(Source):
    slug = "sreality"
    kind = "json_api"
    parser_version = PARSER_VERSION

    def __init__(self) -> None:
        settings = get_settings()
        self.base_url = settings.sreality_base_url.rstrip("/")
        self.rate_limit_rps = settings.sreality_rate_limit_rps
        self._bucket = TokenBucket(name=self.slug, rate_per_sec=self.rate_limit_rps)

    # ----- discover -----------------------------------------------------

    def discover(self, params: dict[str, Any]) -> Iterator[ListingRef]:
        """
        Required params:
          region        int  (locality_region_id, e.g. 10 = Praha)
          category_main int  (1=byty, 2=domy, 3=pozemky, 4=komercni, 5=ostatni)
          category_type int  (1=prodej, 2=pronajem, 3=drazby)
        Optional:
          per_page      int  (default 60; max ~999)
          max_pages     int  (safety cap)
        """
        region = int(params["region"])
        category_main = int(params["category_main"])
        category_type = int(params["category_type"])
        per_page = int(params.get("per_page", 60))
        max_pages = int(params.get("max_pages", 200))

        log.info(
            "sreality.discover.start",
            region=region,
            region_name=REGION_ID_TO_NAME.get(region, "?"),
            category_main=category_main,
            category_type=category_type,
        )

        seen_ids: set[str] = set()
        with make_client() as client:
            for page in range(1, max_pages + 1):
                qs = {
                    "category_main_cb": category_main,
                    "category_type_cb": category_type,
                    "locality_region_id": region,
                    "page": page,
                    "per_page": per_page,
                }
                url = f"{self.base_url}/api/cs/v2/estates?{urlencode(qs)}"
                self._bucket.acquire()
                try:
                    resp = get_with_retry(client, url)
                except NonRetryableHTTPError as e:
                    log.warning("sreality.discover.http_error", url=url, error=str(e))
                    break

                try:
                    payload = resp.json()
                except json.JSONDecodeError:
                    log.warning("sreality.discover.bad_json", url=url)
                    break

                items = (payload.get("_embedded") or {}).get("estates") or []
                if not items:
                    log.info("sreality.discover.end", page=page, reason="empty_page")
                    break

                new_on_page = 0
                for it in items:
                    hash_id = str(it.get("hash_id") or it.get("id") or "")
                    if not hash_id or hash_id in seen_ids:
                        continue
                    seen_ids.add(hash_id)
                    new_on_page += 1
                    yield ListingRef(
                        source_slug=self.slug,
                        source_listing_id=hash_id,
                        url=self._detail_url(hash_id),
                        hint={
                            "price_czk": it.get("price_czk") or it.get("price"),
                            "gps": it.get("gps"),
                            "locality": (it.get("locality") or {}).get("value")
                            if isinstance(it.get("locality"), dict)
                            else it.get("locality"),
                            "thumb": (it.get("_links") or {}).get("image"),
                            "name": it.get("name"),
                        },
                    )

                if new_on_page == 0:
                    log.info("sreality.discover.end", page=page, reason="no_new")
                    break

                # If the API tells us a result count, stop when paginated past it.
                total = payload.get("result_size")
                if isinstance(total, int) and page * per_page >= total:
                    log.info(
                        "sreality.discover.end",
                        page=page,
                        reason="total_reached",
                        total=total,
                    )
                    break

    # ----- fetch --------------------------------------------------------

    def fetch(self, ref: ListingRef) -> RawDocument:
        url = self._detail_url(ref.source_listing_id)
        self._bucket.acquire()
        with make_client() as client:
            resp = get_with_retry(client, url)
        return RawDocument(
            source_slug=self.slug,
            source_listing_id=ref.source_listing_id,
            url=url,
            http_status=resp.status_code,
            content_type=resp.headers.get("content-type", "application/json"),
            content_bytes=resp.content,
            fetched_at=datetime.now(tz=UTC),
        )

    # ----- parse --------------------------------------------------------

    def parse(self, raw: RawDocument) -> ParsedListing:
        detail = json.loads(raw.content_bytes.decode("utf-8"))
        return parse_sreality_detail(
            detail,
            hash_id=raw.source_listing_id,
            canonical_url=self._listing_human_url(raw.source_listing_id),
            fetched_at=raw.fetched_at,
        )

    # ----- health -------------------------------------------------------

    def health_check(self) -> SourceHealth:
        # A search for Praha byty prodej with per_page=1 is a cheap probe.
        url = (
            f"{self.base_url}/api/cs/v2/estates"
            "?category_main_cb=1&category_type_cb=1&locality_region_id=10"
            "&page=1&per_page=1"
        )
        self._bucket.acquire()
        try:
            with make_client(timeout_s=10) as client:
                resp = get_with_retry(client, url)
            payload = resp.json()
            estates = (payload.get("_embedded") or {}).get("estates") or []
            if not estates:
                return SourceHealth(ok=False, detail="empty estates list")
            return SourceHealth(ok=True, detail=f"hash_id={estates[0].get('hash_id')}")
        except Exception as e:
            return SourceHealth(ok=False, detail=str(e)[:200])

    # ----- helpers ------------------------------------------------------

    def _detail_url(self, hash_id: str) -> str:
        return f"{self.base_url}/api/cs/v2/estates/{hash_id}"

    def _listing_human_url(self, hash_id: str) -> str:
        # Sreality has a stable public URL pattern using the hash_id.
        return f"{self.base_url}/detail/prodej/byt/{hash_id}"
