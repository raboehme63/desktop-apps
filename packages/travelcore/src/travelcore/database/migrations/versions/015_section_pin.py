"""015 map pin on trip sections

Revision ID: 015_section_pin
Revises: 014_section_member_journal
Create Date: 2026-08-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "015_section_pin"
down_revision: str | None = "014_section_member_journal"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    with op.batch_alter_table("trip_sections") as batch:
        batch.add_column(sa.Column("pin_latitude", sa.Float(), nullable=True))
        batch.add_column(sa.Column("pin_longitude", sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("trip_sections") as batch:
        batch.drop_column("pin_longitude")
        batch.drop_column("pin_latitude")
