"""seed scoring_config with v1 weights

Inserts the initial composite-formula weights so the Week-5 scoring worker
can resolve `model_version = "v1"`. Component refs are static defaults
pending corpus-derived recomputation; see docs/SCORING.md §Composite.

Revision ID: 0004_seed_scoring_config_v1
Revises: 0003_market_stats_and_score_latest
Create Date: 2026-05-15
"""
from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "0004_seed_scoring_config_v1"
down_revision = "0003_market_stats_and_score_latest"
branch_labels = None
depends_on = None


V1_WEIGHTS = {
    "components": {
        "undervaluation_pct": 1.5,
        "yield_gross_pct": 0.6,
        "liquidity_score": 0.3,
        "location_score": 0.3,
        "risk_score": -0.8,
    },
    "refs": {
        "undervaluation_pct": {"mean": 0.0, "stddev": 15.0},
        "yield_gross_pct": {"mean": 4.5, "stddev": 1.5},
        "liquidity_score": {"mean": 50.0, "stddev": 20.0},
        "location_score": {"mean": 50.0, "stddev": 20.0},
        "risk_score": {"mean": 10.0, "stddev": 15.0},
    },
    "composite_scale_max": 100,
    "confidence_hide_threshold": 0.3,
}

V1_NOTES = (
    "Initial weights from docs/SCORING.md §Composite. "
    "Component refs are static defaults pending corpus-derived recomputation."
)


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO scoring_config (model_version, weights_jsonb, notes)
            VALUES ('v1', CAST(:weights AS jsonb), :notes)
            ON CONFLICT (model_version) DO NOTHING
            """
        ).bindparams(
            weights=json.dumps(V1_WEIGHTS),
            notes=V1_NOTES,
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM scoring_config WHERE model_version = 'v1'"))
