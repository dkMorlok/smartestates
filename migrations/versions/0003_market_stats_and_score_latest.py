"""market_stat, scoring_config, score_latest materialized view

The score table already exists from the baseline. This adds the missing
machinery needed for the Week-5 scoring job: per-segment statistics over
time, the scoring-config registry (weights versioned by model_version),
and the score_latest mview that the API reads.

Revision ID: 0003_market_stats_and_score_latest
Revises: 0002_ruian_address
Create Date: 2026-05-15
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_market_stats_and_score_latest"
down_revision = "0002_ruian_address"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- market_stat -------------------------------------------------------
    op.create_table(
        "market_stat",
        sa.Column(
            "segment_id",
            sa.BigInteger,
            sa.ForeignKey("market_segment.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("as_of_date", sa.Date, primary_key=True),
        sa.Column("n_samples", sa.Integer, nullable=False),
        sa.Column("ppm2_median", sa.Numeric(14, 2)),
        sa.Column("ppm2_trimmed_mean", sa.Numeric(14, 2)),
        sa.Column("ppm2_p25", sa.Numeric(14, 2)),
        sa.Column("ppm2_p75", sa.Numeric(14, 2)),
        sa.Column("ppm2_stddev", sa.Numeric(14, 2)),
        sa.Column("dom_median_days", sa.Numeric(8, 2)),
        sa.Column("rent_ppm2_median", sa.Numeric(14, 2)),
        sa.Column("relaxation_level", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_market_stat_segment_recent",
        "market_stat",
        ["segment_id", sa.text("as_of_date DESC")],
    )

    # ---- scoring_config ----------------------------------------------------
    # Weights for the composite formula live here, versioned by model_version.
    # The score table already references model_version as part of its PK.
    op.create_table(
        "scoring_config",
        sa.Column("model_version", sa.String(32), primary_key=True),
        sa.Column("weights_jsonb", postgresql.JSONB, nullable=False),
        sa.Column("notes", sa.Text),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # ---- score_latest materialized view -----------------------------------
    # Fast "current score per listing" lookups for the listings API. Refreshed
    # CONCURRENTLY at the tail of the score job; that needs the unique index.
    op.execute(
        """
        CREATE MATERIALIZED VIEW score_latest AS
        SELECT DISTINCT ON (listing_id) *
        FROM score
        ORDER BY listing_id, computed_at DESC
        WITH NO DATA
        """
    )
    op.execute("CREATE UNIQUE INDEX uq_score_latest_listing ON score_latest (listing_id)")
    op.execute("CREATE INDEX ix_score_latest_composite ON score_latest (composite DESC)")

    # ---- score table: add the listing_id+time index missing from baseline --
    # baseline only indexed (computed_at, composite); per-listing latest reads
    # need (listing_id, computed_at DESC) to be fast.
    op.create_index(
        "ix_score_listing_recent",
        "score",
        ["listing_id", sa.text("computed_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_score_listing_recent", table_name="score")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS score_latest")
    op.drop_table("scoring_config")
    op.drop_index("ix_market_stat_segment_recent", table_name="market_stat")
    op.drop_table("market_stat")
