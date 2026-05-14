"""baseline schema

Revision ID: 0001_baseline
Revises:
Create Date: 2026-05-14
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geography
from sqlalchemy.dialects import postgresql

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Extensions
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # ---- source ----
    op.create_table(
        "source",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("slug", sa.String(64), nullable=False, unique=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("base_url", sa.Text, nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("rate_limit_rps", sa.Numeric(6, 3), nullable=False, server_default="1"),
        sa.Column(
            "config_jsonb",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("health", sa.String(16), nullable=False, server_default="unknown"),
        sa.Column("last_ok_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # ---- source_run ----
    op.create_table(
        "source_run",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column(
            "source_id",
            sa.Integer,
            sa.ForeignKey("source.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "stats_jsonb",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("error_text", sa.Text),
    )
    op.create_index(
        "ix_source_run_source_started",
        "source_run",
        ["source_id", "started_at"],
    )

    # ---- raw_listing ----
    # Note: in production we partition by month. MVP keeps it as a regular
    # table; the partitioning migration ships in Phase 2 once volume is real.
    op.create_table(
        "raw_listing",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "source_id",
            sa.Integer,
            sa.ForeignKey("source.id"),
            nullable=False,
        ),
        sa.Column("source_listing_id", sa.String(128), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("http_status", sa.SmallInteger),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("raw_s3_key", sa.Text, nullable=False),
        sa.Column("parsed_jsonb", postgresql.JSONB),
        sa.Column("parser_version", sa.String(32)),
        sa.Column("parse_status", sa.String(16)),
        sa.Column("parse_error", sa.Text),
    )
    op.create_index(
        "ix_raw_listing_source_lid_time",
        "raw_listing",
        ["source_id", "source_listing_id", "fetched_at"],
    )
    op.create_index("ix_raw_listing_content_hash", "raw_listing", ["content_hash"])

    # ---- property ----
    op.create_table(
        "property",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("geom", Geography(geometry_type="POINT", srid=4326)),
        sa.Column("address_normalized", sa.Text),
        sa.Column("address_precision", sa.String(16), nullable=False),
        sa.Column("country", sa.String(2), nullable=False, server_default="CZ"),
        sa.Column("admin1", sa.String(64)),
        sa.Column("admin2", sa.String(64)),
        sa.Column("locality", sa.String(128)),
        sa.Column("city_district", sa.String(64)),
        sa.Column("cadastral_area", sa.String(128)),
        sa.Column("postcode", sa.String(16)),
        sa.Column("ruian_address_code", sa.String(32)),
        sa.Column("ruian_building_code", sa.String(32)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_property_ruian_addr",
        "property",
        ["ruian_address_code"],
        unique=True,
        postgresql_where=sa.text("ruian_address_code IS NOT NULL"),
    )
    op.create_index(
        "ix_property_district_locality",
        "property",
        ["city_district", "locality"],
    )

    # ---- listing ----
    op.create_table(
        "listing",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("property_id", sa.BigInteger, sa.ForeignKey("property.id")),
        sa.Column(
            "source_id",
            sa.Integer,
            sa.ForeignKey("source.id"),
            nullable=False,
        ),
        sa.Column("source_listing_id", sa.String(128), nullable=False),
        sa.Column("canonical_url", sa.Text, nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("price", sa.Numeric(14, 2)),
        sa.Column("currency", sa.String(3), nullable=False, server_default="CZK"),
        sa.Column(
            "price_hidden",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("size_m2", sa.Numeric(10, 2)),
        sa.Column("usable_area_m2", sa.Numeric(10, 2)),
        sa.Column("land_area_m2", sa.Numeric(12, 2)),
        sa.Column("rooms", sa.SmallInteger),
        sa.Column("bathrooms", sa.SmallInteger),
        sa.Column("floor_current", sa.SmallInteger),
        sa.Column("floor_total", sa.SmallInteger),
        sa.Column("year_built", sa.SmallInteger),
        sa.Column("property_type", sa.String(16), nullable=False),
        sa.Column("disposition", sa.String(16)),
        sa.Column("ownership_type", sa.String(16)),
        sa.Column("building_type", sa.String(16)),
        sa.Column("condition", sa.String(32)),
        sa.Column("energy_class", sa.String(1)),
        sa.Column(
            "features_jsonb",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("description", sa.Text),
        sa.Column("agency", sa.String(256)),
        sa.Column("agent_name", sa.String(256)),
        sa.Column("is_owner_direct", sa.Boolean),
        sa.Column("dedup_cluster_id", sa.BigInteger),
        sa.Column("raw_listing_id", sa.BigInteger),
        sa.Column("parser_version", sa.String(32)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("source_id", "source_listing_id", name="uq_listing_source_lid"),
        sa.CheckConstraint("price IS NULL OR price >= 0", name="ck_listing_price_nonneg"),
        sa.CheckConstraint("size_m2 IS NULL OR size_m2 > 0", name="ck_listing_size_positive"),
    )
    op.create_index(
        "ix_listing_active_price",
        "listing",
        ["price"],
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index("ix_listing_property", "listing", ["property_id"])
    op.create_index("ix_listing_dedup_cluster", "listing", ["dedup_cluster_id"])
    op.create_index(
        "ix_listing_typekey",
        "listing",
        ["property_type", "ownership_type", "disposition"],
    )
    op.create_index("ix_listing_last_seen", "listing", ["last_seen_at"])

    # ---- listing_version ----
    op.create_table(
        "listing_version",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "listing_id",
            sa.BigInteger,
            sa.ForeignKey("listing.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("price", sa.Numeric(14, 2)),
        sa.Column("status", sa.String(16)),
        sa.Column("fields_changed", postgresql.JSONB, nullable=False),
    )
    op.create_index(
        "ix_listing_version_listing_time",
        "listing_version",
        ["listing_id", "observed_at"],
    )

    # ---- photo ----
    op.create_table(
        "photo",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "listing_id",
            sa.BigInteger,
            sa.ForeignKey("listing.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ord", sa.SmallInteger, nullable=False),
        sa.Column("url_source", sa.Text, nullable=False),
        sa.Column("phash", postgresql.BYTEA),
        sa.Column("s3_thumb_key", sa.Text),
        sa.Column("width", sa.Integer),
        sa.Column("height", sa.Integer),
        sa.UniqueConstraint("listing_id", "ord", name="uq_photo_listing_ord"),
    )

    # ---- dedup_cluster ----
    op.create_table(
        "dedup_cluster",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("canonical_listing_id", sa.BigInteger, sa.ForeignKey("listing.id")),
        sa.Column("method", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("reviewed_by", sa.String(64)),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
    )

    # ---- market_segment ----
    op.create_table(
        "market_segment",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("city_district", sa.String(64)),
        sa.Column("locality", sa.String(128)),
        sa.Column("property_type", sa.String(16), nullable=False),
        sa.Column("disposition", sa.String(16)),
        sa.Column("ownership_type", sa.String(16)),
        sa.Column("building_type", sa.String(16)),
        sa.Column("size_bucket", sa.String(16), nullable=False),
        sa.Column("condition_bucket", sa.String(32)),
        sa.Column("geom", Geography(geometry_type="POLYGON", srid=4326)),
        sa.UniqueConstraint(
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

    # ---- score ----
    op.create_table(
        "score",
        sa.Column(
            "listing_id",
            sa.BigInteger,
            sa.ForeignKey("listing.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("model_version", sa.String(32), primary_key=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("segment_id", sa.BigInteger, sa.ForeignKey("market_segment.id")),
        sa.Column("undervaluation_pct", sa.Numeric(6, 3)),
        sa.Column("undervaluation_abs", sa.Numeric(14, 2)),
        sa.Column("yield_gross_pct", sa.Numeric(5, 2)),
        sa.Column("yield_confidence", sa.Numeric(4, 3)),
        sa.Column("liquidity_score", sa.Numeric(5, 2)),
        sa.Column("location_score", sa.Numeric(5, 2)),
        sa.Column("risk_score", sa.Numeric(5, 2)),
        sa.Column("confidence_score", sa.Numeric(4, 3)),
        sa.Column("composite", sa.Numeric(5, 2)),
        sa.Column(
            "components_jsonb",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "risk_flags",
            postgresql.ARRAY(sa.String(32)),
            nullable=False,
            server_default=sa.text("ARRAY[]::varchar[]"),
        ),
    )
    # Composite index supporting "recent scores ordered by composite" queries.
    # A partial predicate with now() is rejected by Postgres (now() is STABLE,
    # not IMMUTABLE) and would go stale regardless, so the recency filter is
    # served by the leading computed_at column instead.
    op.create_index(
        "ix_score_composite_recent",
        "score",
        ["computed_at", "composite"],
    )

    # ---- seed sources ----
    op.execute(
        """
        INSERT INTO source (slug, kind, base_url, rate_limit_rps, enabled)
        VALUES ('sreality', 'json_api', 'https://www.sreality.cz', 1.0, true)
        """
    )


def downgrade() -> None:
    op.drop_table("score")
    op.drop_table("market_segment")
    op.drop_table("dedup_cluster")
    op.drop_table("photo")
    op.drop_table("listing_version")
    op.drop_table("listing")
    op.drop_table("property")
    op.drop_table("raw_listing")
    op.drop_table("source_run")
    op.drop_table("source")
