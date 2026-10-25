"""Cross-check columns and the corroboration table.

Revision ID: b7e2a1c94d10
Revises: a2c7d4e81f03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b7e2a1c94d10"
down_revision = "a2c7d4e81f03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("outbreak_reports", sa.Column("data_as_of", sa.DateTime(timezone=True)))
    op.add_column("outbreak_observations", sa.Column("data_as_of", sa.DateTime(timezone=True)))
    op.add_column(
        "outbreak_observations",
        sa.Column("corroboration_status", sa.String(length=32)),
    )
    op.add_column("country_flows", sa.Column("cross_check_source", sa.String(length=64)))
    op.add_column("country_flows", sa.Column("cross_check_ratio", sa.Float()))
    op.create_table(
        "observation_corroborations",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "primary_observation_id",
            sa.UUID(),
            sa.ForeignKey("outbreak_observations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "other_observation_id",
            sa.UUID(),
            sa.ForeignKey("outbreak_observations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("metric", sa.String(length=32), nullable=False),
        sa.Column("primary_value", sa.Float(), nullable=False),
        sa.Column("other_value", sa.Float(), nullable=False),
        sa.Column("aligned_value", sa.Float()),
        sa.Column("date_gap_days", sa.Float()),
        sa.Column("relative_difference", sa.Float()),
        sa.Column("verdict", sa.String(length=32), nullable=False),
        sa.Column("rule_version", sa.String(length=16), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("observation_corroborations")
    op.drop_column("country_flows", "cross_check_ratio")
    op.drop_column("country_flows", "cross_check_source")
    op.drop_column("outbreak_observations", "corroboration_status")
    op.drop_column("outbreak_observations", "data_as_of")
    op.drop_column("outbreak_reports", "data_as_of")
