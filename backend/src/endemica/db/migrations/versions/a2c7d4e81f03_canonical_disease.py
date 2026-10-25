"""Canonical disease grouping on outbreak reports.

Revision ID: a2c7d4e81f03
Revises: 9b1f01336904
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a2c7d4e81f03"
down_revision = "9b1f01336904"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "outbreak_reports",
        sa.Column(
            "disease_key",
            sa.String(length=64),
            nullable=True,
            comment="Canonical disease key, so wording variants group into one disease.",
        ),
    )
    op.add_column(
        "outbreak_reports",
        sa.Column(
            "disease_name",
            sa.String(length=128),
            nullable=True,
            comment="Canonical display name for disease_key.",
        ),
    )
    op.add_column(
        "outbreak_reports",
        sa.Column(
            "disease_family",
            sa.String(length=64),
            nullable=True,
            comment="Broad grouping, e.g. 'Viral haemorrhagic fever'.",
        ),
    )
    op.create_index(
        "ix_outbreak_reports_disease_key", "outbreak_reports", ["disease_key"], unique=False
    )
    op.create_index(
        "ix_outbreak_reports_disease_name", "outbreak_reports", ["disease_name"], unique=False
    )
    op.create_index(
        "ix_outbreak_reports_disease_family", "outbreak_reports", ["disease_family"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_outbreak_reports_disease_family", table_name="outbreak_reports")
    op.drop_index("ix_outbreak_reports_disease_name", table_name="outbreak_reports")
    op.drop_index("ix_outbreak_reports_disease_key", table_name="outbreak_reports")
    op.drop_column("outbreak_reports", "disease_family")
    op.drop_column("outbreak_reports", "disease_name")
    op.drop_column("outbreak_reports", "disease_key")
