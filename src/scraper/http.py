"""Shared httpx client with retries and identifying User-Agent."""
from __future__ import annotations

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from shared.config import get_settings


def make_client(timeout_s: float = 20.0) -> httpx.Client:
    settings = get_settings()
    return httpx.Client(
        timeout=httpx.Timeout(timeout_s),
        headers={
            "User-Agent": settings.scraper_user_agent,
            "Accept": "application/json, text/html;q=0.9",
            "Accept-Language": "cs-CZ,cs;q=0.9,en;q=0.5",
        },
        follow_redirects=True,
    )


class RetryableHTTPError(Exception):
    """5xx or 429 — retry."""


class NonRetryableHTTPError(Exception):
    """4xx (except 429) — do not retry."""


@retry(
    retry=retry_if_exception_type((httpx.NetworkError, httpx.TimeoutException, RetryableHTTPError)),
    wait=wait_exponential(multiplier=2, min=2, max=60),
    stop=stop_after_attempt(5),
    reraise=True,
)
def get_with_retry(client: httpx.Client, url: str, **kwargs: object) -> httpx.Response:
    resp = client.get(url, **kwargs)  # type: ignore[arg-type]
    if resp.status_code in (429,) or 500 <= resp.status_code < 600:
        raise RetryableHTTPError(f"{resp.status_code} from {url}")
    if 400 <= resp.status_code < 500:
        raise NonRetryableHTTPError(f"{resp.status_code} from {url}: {resp.text[:200]}")
    return resp
