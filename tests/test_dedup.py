"""Tests for tier-1 dedup clustering (worker/tasks/dedup.py).

Covers the pure clustering function: which same-source listings collapse,
which stay separate, and the canonical-first ordering.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from worker.tasks.dedup import DedupRow, cluster_same_source

_T0 = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)


def _row(
    listing_id: int,
    *,
    source_id: int = 1,
    first_seen: datetime | None = None,
    size: str | None = "56",
    disposition: str | None = "2+kk",
    ownership: str | None = "osobni",
) -> DedupRow:
    return DedupRow(
        listing_id=listing_id,
        source_id=source_id,
        first_seen_at=first_seen or _T0,
        size_m2=Decimal(size) if size is not None else None,
        disposition=disposition,
        ownership_type=ownership,
    )


class TestClusterSameSource:
    def test_two_identical_listings_cluster(self) -> None:
        rows = [_row(1, first_seen=_T0), _row(2, first_seen=_T0 + timedelta(days=3))]
        clusters = cluster_same_source(rows)
        assert clusters == [[1, 2]]

    def test_canonical_is_earliest_first_seen(self) -> None:
        rows = [
            _row(10, first_seen=_T0 + timedelta(days=5)),
            _row(20, first_seen=_T0),
        ]
        clusters = cluster_same_source(rows)
        # Earliest first_seen leads — listing 20 is canonical.
        assert clusters == [[20, 10]]

    def test_different_size_stays_separate(self) -> None:
        rows = [_row(1, size="56"), _row(2, size="72")]
        assert cluster_same_source(rows) == []

    def test_different_disposition_stays_separate(self) -> None:
        rows = [_row(1, disposition="2+kk"), _row(2, disposition="3+kk")]
        assert cluster_same_source(rows) == []

    def test_different_ownership_stays_separate(self) -> None:
        # The družstevní/osobní trap: never collapse across ownership.
        rows = [_row(1, ownership="osobni"), _row(2, ownership="druzstevni")]
        assert cluster_same_source(rows) == []

    def test_different_source_stays_separate(self) -> None:
        # Cross-source dedup is tier 2 (Phase 2), not tier 1.
        rows = [_row(1, source_id=1), _row(2, source_id=2)]
        assert cluster_same_source(rows) == []

    def test_unknown_size_never_clusters(self) -> None:
        rows = [_row(1, size=None), _row(2, size=None)]
        assert cluster_same_source(rows) == []

    def test_size_rounds_to_whole_m2(self) -> None:
        rows = [_row(1, size="56.2"), _row(2, size="55.8")]
        # Both round to 56 m².
        assert cluster_same_source(rows) == [[1, 2]]

    def test_singleton_not_a_cluster(self) -> None:
        assert cluster_same_source([_row(1)]) == []

    def test_two_separate_clusters(self) -> None:
        rows = [
            _row(1, size="56"),
            _row(2, size="56"),
            _row(3, size="90", disposition="3+1"),
            _row(4, size="90", disposition="3+1"),
        ]
        clusters = sorted(cluster_same_source(rows))
        assert clusters == [[1, 2], [3, 4]]
