"""ruian address points

Local copy of RÚIAN address points (ČÚZK), used by the geocode stage to
resolve a source GPS coordinate to a building: rooftop precision plus the
official RÚIAN address code, which is the bulletproof key for property
linking and dedup. Seeded by scripts/seed_ruian.py.

Revision ID: 0002_ruian_address
Revises: 0001_baseline
Create Date: 2026-05-15
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geography

revision = "0002_ruian_address"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ruian_address",
        # "Kód ADM" — RÚIAN address-place code, globally unique.
        sa.Column("kod_adm", sa.String(12), primary_key=True),
        sa.Column("kod_obce", sa.String(12), nullable=False),
        sa.Column("nazev_obce", sa.Text, nullable=False),
        sa.Column("nazev_momc", sa.Text),           # městská část / městský obvod
        sa.Column("nazev_casti_obce", sa.Text),     # část obce (~ cadastral area)
        sa.Column("nazev_ulice", sa.Text),
        sa.Column("cislo_domovni", sa.String(8)),   # číslo popisné/evidenční
        sa.Column("cislo_orientacni", sa.String(8)),
        sa.Column("psc", sa.String(8)),
        sa.Column(
            "geom",
            Geography(geometry_type="POINT", srid=4326),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    # GeoAlchemy2 auto-creates the GIST index on `geom` (idx_ruian_address_geom)
    # from the Geography column — no explicit spatial index needed here.
    op.create_index("ix_ruian_address_obec", "ruian_address", ["kod_obce"])


def downgrade() -> None:
    op.drop_table("ruian_address")
