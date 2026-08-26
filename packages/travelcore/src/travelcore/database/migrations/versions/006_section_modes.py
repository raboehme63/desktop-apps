"""006 allow multiple transfer modes on a section

Revision ID: 006_section_modes
Revises: 005_trip_sections
Create Date: 2026-08-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "006_section_modes"
down_revision: str | None = "005_trip_sections"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    with op.batch_alter_table("trip_sections") as batch:
        batch.alter_column(
            "mode",
            existing_type=sa.String(length=32),
            type_=sa.String(length=128),
            existing_nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("trip_sections") as batch:
        batch.alter_column(
            "mode",
            existing_type=sa.String(length=128),
            type_=sa.String(length=32),
            existing_nullable=True,
        )
