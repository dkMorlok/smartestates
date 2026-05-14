"""Source SDK — the contract every source implements.

Adding a source = adding a folder with a Source subclass. Core pipeline
never imports source modules directly; they're discovered via the registry.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from shared.schemas import ParsedListing


@dataclass(frozen=True)
class ListingRef:
    """Pointer to a listing on a source. Emitted by discover()."""
    source_slug: str
    source_listing_id: str
    url: str
    hint: dict[str, Any]  # source-provided info that may avoid a detail fetch


@dataclass(frozen=True)
class RawDocument:
    """A fetched but not yet parsed payload."""
    source_slug: str
    source_listing_id: str
    url: str
    http_status: int
    content_type: str
    content_bytes: bytes
    fetched_at: datetime


@dataclass(frozen=True)
class SourceHealth:
    ok: bool
    detail: str = ""


class Source(ABC):
    """Per-source implementation. Subclass in sources/<slug>/source.py."""

    slug: str
    kind: str           # 'json_api' | 'html' | 'feed'
    rate_limit_rps: float
    parser_version: str

    @abstractmethod
    def discover(self, params: dict[str, Any]) -> Iterator[ListingRef]:
        """Yield candidate listing refs given source-specific search params."""

    @abstractmethod
    def fetch(self, ref: ListingRef) -> RawDocument:
        """Retrieve the raw payload for a listing."""

    @abstractmethod
    def parse(self, raw: RawDocument) -> ParsedListing:
        """Parse raw payload into the canonical ParsedListing schema."""

    @abstractmethod
    def health_check(self) -> SourceHealth:
        """Lightweight liveness probe (e.g. fetch one known stable listing)."""


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


_REGISTRY: dict[str, type[Source]] = {}


def register_source(cls: type[Source]) -> type[Source]:
    """Decorator to register a Source subclass."""
    _REGISTRY[cls.slug] = cls
    return cls


def get_source(slug: str) -> Source:
    if slug not in _REGISTRY:
        # ensure source modules are imported once
        import scraper.sources  # noqa: F401
    if slug not in _REGISTRY:
        raise KeyError(f"Unknown source: {slug}")
    return _REGISTRY[slug]()


def all_source_slugs() -> list[str]:
    import scraper.sources  # noqa: F401
    return sorted(_REGISTRY.keys())
