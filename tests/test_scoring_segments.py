"""Tests for segment bucketing and the relaxation hierarchy."""
from __future__ import annotations

from decimal import Decimal

from scoring.segments import (
    MAX_RELAXATION_LEVEL,
    UNKNOWN_BUCKET,
    ListingLike,
    condition_bucket,
    relax,
    segment_key_for,
    size_bucket,
)


class TestSizeBucket:
    def test_boundaries(self) -> None:
        assert size_bucket(34) == "<35"
        assert size_bucket(35) == "35-50"
        assert size_bucket(49.99) == "35-50"
        assert size_bucket(50) == "50-70"
        assert size_bucket(70) == "70-90"
        assert size_bucket(90) == "90-120"
        assert size_bucket(120) == "120-160"
        assert size_bucket(160) == ">160"
        assert size_bucket(500) == ">160"

    def test_unknown_inputs(self) -> None:
        assert size_bucket(None) == UNKNOWN_BUCKET
        assert size_bucket(0) == UNKNOWN_BUCKET
        assert size_bucket(-5) == UNKNOWN_BUCKET

    def test_decimal_input(self) -> None:
        assert size_bucket(Decimal("56.0")) == "50-70"


class TestConditionBucket:
    def test_known_mappings(self) -> None:
        assert condition_bucket("novostavba") == "new"
        assert condition_bucket("velmi_dobry") == "very_good"
        assert condition_bucket("po_rekonstrukci") == "very_good"
        assert condition_bucket("dobry") == "good"
        assert condition_bucket("spatny") == "ruin"

    def test_unknown_inputs(self) -> None:
        assert condition_bucket(None) == UNKNOWN_BUCKET
        assert condition_bucket("") == UNKNOWN_BUCKET
        assert condition_bucket("invented") == UNKNOWN_BUCKET


def _listing(**overrides: object) -> ListingLike:
    base = {
        "city_district": "Praha 5",
        "locality": None,
        "property_type": "byt",
        "disposition": "2+kk",
        "ownership_type": "osobni",
        "building_type": "cihla",
        "size_m2": Decimal("56"),
        "condition": "velmi_dobry",
    }
    base.update(overrides)
    return ListingLike(**base)  # type: ignore[arg-type]


class TestSegmentKey:
    def test_for_byt_listing(self) -> None:
        key = segment_key_for(_listing())
        assert key.city_district == "Praha 5"
        assert key.property_type == "byt"
        assert key.disposition == "2+kk"
        assert key.ownership_type == "osobni"
        assert key.building_type == "cihla"
        assert key.size_bucket == "50-70"
        assert key.condition_bucket == "very_good"


class TestRelax:
    def test_level_0_is_identity(self) -> None:
        key = segment_key_for(_listing())
        assert relax(key, 0) == key

    def test_levels_progressively_relax(self) -> None:
        key = segment_key_for(_listing())
        # Level 1: size bucket widens
        l1 = relax(key, 1)
        assert l1 is not None
        assert l1.size_bucket == "50-90"
        # Level 2: condition bucket widens
        l2 = relax(key, 2)
        assert l2 is not None
        assert l2.condition_bucket == "any_habitable"
        # Level 3: building_type dropped
        l3 = relax(key, 3)
        assert l3 is not None
        assert l3.building_type is None
        # Level 4: admin area widened
        l4 = relax(key, 4)
        assert l4 is not None
        assert l4.city_district == "Praha"
        # Level 5: disposition dropped (ownership stays — družstevní trap)
        l5 = relax(key, 5)
        assert l5 is not None
        assert l5.disposition is None
        assert l5.ownership_type == "osobni"

    def test_past_max_returns_none(self) -> None:
        key = segment_key_for(_listing())
        assert relax(key, MAX_RELAXATION_LEVEL + 1) is None

    def test_relax_is_pure(self) -> None:
        key = segment_key_for(_listing())
        before = key.as_dict()
        relax(key, 5)
        assert key.as_dict() == before

    def test_adjacent_size_buckets_pool_after_level_1(self) -> None:
        # <35 and 35-50 both map to "<50" — they pool at level 1.
        a = segment_key_for(_listing(size_m2=30))
        b = segment_key_for(_listing(size_m2=40))
        assert a.size_bucket != b.size_bucket
        ra, rb = relax(a, 1), relax(b, 1)
        assert ra is not None and rb is not None
        assert ra == rb
