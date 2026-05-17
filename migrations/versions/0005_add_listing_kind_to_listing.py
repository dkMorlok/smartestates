"""add listing_kind to listing

Adds listing_kind VARCHAR(16) NOT NULL DEFAULT 'prodej' to the listing table.
All 5922 existing rows are prodej (Sreality category_type=1); the DEFAULT
backfills them correctly. Supersedes ix_listing_typekey with the wider
ix_listing_kind_typekey so rental/auction queries can filter on kind first.

Revision ID: 0005_add_listing_kind_to_listing
Revises: 0004_seed_scoring_config_v1
Create Date: 2026-05-18
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_add_listing_kind_to_listing"
down_revision = "0004_seed_scoring_config_v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add the column with a server-side DEFAULT so Postgres fills all existing
    # rows atomically as part of the DDL — no separate UPDATE pass needed.
    op.add_column(
        "listing",
        sa.Column(
            "listing_kind",
            sa.String(16),
            nullable=False,
            server_default="prodej",
        ),
    )

    # Drop the narrower index that this one supersedes.
    op.drop_index("ix_listing_typekey", table_name="listing")

    # New composite index — listing_kind leads so range scans on a single kind
    # (e.g. pronajem) can skip unrelated rows before touching property_type.
    op.create_index(
        "ix_listing_kind_typekey",
        "listing",
        ["listing_kind", "property_type", "ownership_type", "disposition"],
    )


def downgrade() -> None:
    op.drop_index("ix_listing_kind_typekey", table_name="listing")
    op.create_index(
        "ix_listing_typekey",
        "listing",
        ["property_type", "ownership_type", "disposition"],
    )
    op.drop_column("listing", "listing_kind")
