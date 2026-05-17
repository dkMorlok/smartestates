"""SQLAlchemy 2.0 ORM models.

Matches the schema in docs/DATA_MODEL.md. Only the subset needed for Week 1
ingestion is fully fleshed out; scoring/score tables are stubs.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, ClassVar

from geoalchemy2 import Geography
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Project base. All models inherit from this."""

    type_annotation_map: ClassVar = {
        dict[str, Any]: JSONB,
    }


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------


class Source(Base):
    __tablename__ = "source"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    kind: Mapped[str] = mapped_column(String(32))
    base_url: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    rate_limit_rps: Mapped[Decimal] = mapped_column(Numeric(6, 3), default=1)
    config_jsonb: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    health: Mapped[str] = mapped_column(String(16), default="unknown")
    last_ok_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SourceRun(Base):
    __tablename__ = "source_run"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("source.id", ondelete="CASCADE"))
    stage: Mapped[str] = mapped_column(String(32))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16))
    stats_jsonb: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    error_text: Mapped[str | None] = mapped_column(Text)


# ---------------------------------------------------------------------------
# Raw layer
# ---------------------------------------------------------------------------


class RawListing(Base):
    """Immutable raw payloads from scrapers. Partition by month in prod."""

    __tablename__ = "raw_listing"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("source.id"))
    source_listing_id: Mapped[str] = mapped_column(String(128))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    url: Mapped[str] = mapped_column(Text)
    http_status: Mapped[int | None] = mapped_column(SmallInteger)
    content_hash: Mapped[str] = mapped_column(String(64))
    raw_s3_key: Mapped[str] = mapped_column(Text)
    parsed_jsonb: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    parser_version: Mapped[str | None] = mapped_column(String(32))
    parse_status: Mapped[str | None] = mapped_column(String(16))
    parse_error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("ix_raw_listing_source_lid_time", "source_id", "source_listing_id", "fetched_at"),
        Index("ix_raw_listing_content_hash", "content_hash"),
    )


# ---------------------------------------------------------------------------
# Property + Listing
# ---------------------------------------------------------------------------


class Property(Base):
    __tablename__ = "property"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    geom: Mapped[Any | None] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=True),
        nullable=True,
    )
    address_normalized: Mapped[str | None] = mapped_column(Text)
    address_precision: Mapped[str] = mapped_column(String(16))
    country: Mapped[str] = mapped_column(String(2), default="CZ")
    admin1: Mapped[str | None] = mapped_column(String(64))
    admin2: Mapped[str | None] = mapped_column(String(64))
    locality: Mapped[str | None] = mapped_column(String(128))
    city_district: Mapped[str | None] = mapped_column(String(64))
    cadastral_area: Mapped[str | None] = mapped_column(String(128))
    postcode: Mapped[str | None] = mapped_column(String(16))
    ruian_address_code: Mapped[str | None] = mapped_column(String(32))
    ruian_building_code: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("ix_property_ruian_addr", "ruian_address_code", unique=True),
        Index("ix_property_district_locality", "city_district", "locality"),
    )

    listings: Mapped[list[Listing]] = relationship(back_populates="property_ref")


class Listing(Base):
    __tablename__ = "listing"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    property_id: Mapped[int | None] = mapped_column(ForeignKey("property.id"))
    source_id: Mapped[int] = mapped_column(ForeignKey("source.id"))
    source_listing_id: Mapped[str] = mapped_column(String(128))
    canonical_url: Mapped[str] = mapped_column(Text)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="active")

    # Pricing
    price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3), default="CZK")
    price_hidden: Mapped[bool] = mapped_column(Boolean, default=False)

    # Physical
    size_m2: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    usable_area_m2: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    land_area_m2: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    rooms: Mapped[int | None] = mapped_column(SmallInteger)
    bathrooms: Mapped[int | None] = mapped_column(SmallInteger)
    floor_current: Mapped[int | None] = mapped_column(SmallInteger)
    floor_total: Mapped[int | None] = mapped_column(SmallInteger)
    year_built: Mapped[int | None] = mapped_column(SmallInteger)

    # CZ-specific (see CZ_NOTES.md)
    listing_kind: Mapped[str] = mapped_column(String(16), default="prodej", nullable=False)
    property_type: Mapped[str] = mapped_column(String(16))
    disposition: Mapped[str | None] = mapped_column(String(16))
    ownership_type: Mapped[str | None] = mapped_column(String(16))
    building_type: Mapped[str | None] = mapped_column(String(16))
    condition: Mapped[str | None] = mapped_column(String(32))
    energy_class: Mapped[str | None] = mapped_column(String(1))

    # Features
    features_jsonb: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    description: Mapped[str | None] = mapped_column(Text)
    agency: Mapped[str | None] = mapped_column(String(256))
    agent_name: Mapped[str | None] = mapped_column(String(256))
    is_owner_direct: Mapped[bool | None] = mapped_column(Boolean)

    dedup_cluster_id: Mapped[int | None] = mapped_column(BigInteger)
    raw_listing_id: Mapped[int | None] = mapped_column(BigInteger)
    parser_version: Mapped[str | None] = mapped_column(String(32))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    property_ref: Mapped[Property | None] = relationship(back_populates="listings")
    photos: Mapped[list[Photo]] = relationship(
        back_populates="listing", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("source_id", "source_listing_id", name="uq_listing_source_lid"),
        Index(
            "ix_listing_active_price",
            "price",
            postgresql_where="status = 'active'",
        ),
        Index("ix_listing_property", "property_id"),
        Index("ix_listing_dedup_cluster", "dedup_cluster_id"),
        Index("ix_listing_kind_typekey", "listing_kind", "property_type", "ownership_type", "disposition"),
        Index("ix_listing_last_seen", "last_seen_at"),
        CheckConstraint("price IS NULL OR price >= 0", name="ck_listing_price_nonneg"),
        CheckConstraint("size_m2 IS NULL OR size_m2 > 0", name="ck_listing_size_positive"),
    )


class ListingVersion(Base):
    """Append-only history of detected changes per listing."""

    __tablename__ = "listing_version"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listing.id", ondelete="CASCADE"))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    status: Mapped[str | None] = mapped_column(String(16))
    fields_changed: Mapped[dict[str, Any]] = mapped_column(JSONB)

    __table_args__ = (
        Index("ix_listing_version_listing_time", "listing_id", "observed_at"),
    )


class Photo(Base):
    __tablename__ = "photo"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listing.id", ondelete="CASCADE"))
    ord: Mapped[int] = mapped_column(SmallInteger)
    url_source: Mapped[str] = mapped_column(Text)
    phash: Mapped[bytes | None] = mapped_column()  # raw 8 bytes
    s3_thumb_key: Mapped[str | None] = mapped_column(Text)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)

    listing: Mapped[Listing] = relationship(back_populates="photos")

    __table_args__ = (
        UniqueConstraint("listing_id", "ord", name="uq_photo_listing_ord"),
    )


# ---------------------------------------------------------------------------
# Dedup
# ---------------------------------------------------------------------------


class DedupCluster(Base):
    __tablename__ = "dedup_cluster"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    canonical_listing_id: Mapped[int | None] = mapped_column(ForeignKey("listing.id"))
    method: Mapped[str] = mapped_column(String(32))
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    reviewed_by: Mapped[str | None] = mapped_column(String(64))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ---------------------------------------------------------------------------
# Scoring (placeholders; filled in Week 5)
# ---------------------------------------------------------------------------


class MarketSegment(Base):
    __tablename__ = "market_segment"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    city_district: Mapped[str | None] = mapped_column(String(64))
    locality: Mapped[str | None] = mapped_column(String(128))
    property_type: Mapped[str] = mapped_column(String(16))
    disposition: Mapped[str | None] = mapped_column(String(16))
    ownership_type: Mapped[str | None] = mapped_column(String(16))
    building_type: Mapped[str | None] = mapped_column(String(16))
    size_bucket: Mapped[str] = mapped_column(String(16))
    condition_bucket: Mapped[str | None] = mapped_column(String(32))
    geom: Mapped[Any | None] = mapped_column(
        Geography(geometry_type="POLYGON", srid=4326, spatial_index=True),
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "city_district",
            "locality",
            "property_type",
            "disposition",
            "ownership_type",
            "building_type",
            "size_bucket",
            "condition_bucket",
            name="uq_market_segment_key",
        ),
    )


class RuianAddress(Base):
    """Local copy of RÚIAN address points (ČÚZK). Seeded by scripts/seed_ruian.py.

    The geocode stage does a nearest-neighbour lookup against `geom` to turn a
    source GPS coordinate into a building: rooftop precision + the official
    RÚIAN address code.
    """

    __tablename__ = "ruian_address"

    kod_adm: Mapped[str] = mapped_column(String(12), primary_key=True)
    kod_obce: Mapped[str] = mapped_column(String(12))
    nazev_obce: Mapped[str] = mapped_column(Text)
    nazev_momc: Mapped[str | None] = mapped_column(Text)
    nazev_casti_obce: Mapped[str | None] = mapped_column(Text)
    nazev_ulice: Mapped[str | None] = mapped_column(Text)
    cislo_domovni: Mapped[str | None] = mapped_column(String(8))
    cislo_orientacni: Mapped[str | None] = mapped_column(String(8))
    psc: Mapped[str | None] = mapped_column(String(8))
    geom: Mapped[Any] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=True)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (Index("ix_ruian_address_obec", "kod_obce"),)


class MarketStat(Base):
    """Per-segment ppm² statistics computed nightly from active listings."""

    __tablename__ = "market_stat"

    segment_id: Mapped[int] = mapped_column(
        ForeignKey("market_segment.id", ondelete="CASCADE"), primary_key=True
    )
    as_of_date: Mapped[date] = mapped_column(primary_key=True)
    n_samples: Mapped[int] = mapped_column(Integer)
    ppm2_median: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    ppm2_trimmed_mean: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    ppm2_p25: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    ppm2_p75: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    ppm2_stddev: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    dom_median_days: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    rent_ppm2_median: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    relaxation_level: Mapped[int] = mapped_column(Integer, default=0)


class ScoringConfig(Base):
    """Composite-score weights, versioned by model_version. See SCORING.md."""

    __tablename__ = "scoring_config"

    model_version: Mapped[str] = mapped_column(String(32), primary_key=True)
    weights_jsonb: Mapped[dict[str, Any]] = mapped_column(JSONB)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Score(Base):
    __tablename__ = "score"

    listing_id: Mapped[int] = mapped_column(
        ForeignKey("listing.id", ondelete="CASCADE"), primary_key=True
    )
    model_version: Mapped[str] = mapped_column(String(32), primary_key=True)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True
    )
    segment_id: Mapped[int | None] = mapped_column(ForeignKey("market_segment.id"))

    undervaluation_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    undervaluation_abs: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    yield_gross_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    yield_confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    liquidity_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    location_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    risk_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    confidence_score: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    composite: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    components_jsonb: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    risk_flags: Mapped[list[str]] = mapped_column(ARRAY(String(32)), default=list)
