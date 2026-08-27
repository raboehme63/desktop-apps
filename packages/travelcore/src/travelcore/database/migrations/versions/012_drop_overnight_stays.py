"""012 drop overnight_stays

Revision ID: 012_drop_overnight_stays
Revises: 011_rotation_degrees
Create Date: 2026-08-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "012_drop_overnight_stays"
down_revision: str | None = "011_rotation_degrees"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.drop_table("overnight_stays")


def downgrade() -> None:
    op.create_table(
        "overnight_stays",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("day_id", sa.Integer(), sa.ForeignKey("trip_days.id"), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("location_name", sa.String(length=255), nullable=True),
        sa.Column("stayed_on", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("origin", sa.String(length=16), nullable=False),
    )
    op.create_index("ix_overnight_stays_day_id", "overnight_stays", ["day_id"])
