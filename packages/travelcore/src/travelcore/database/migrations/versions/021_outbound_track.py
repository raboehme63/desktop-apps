"""021 outbound connection track on Tag/Stay sections

Revision ID: 021_outbound_track
Revises: 020_trip_countries
Create Date: 2026-09-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "021_outbound_track"
down_revision: str | None = "020_trip_countries"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    with op.batch_alter_table("trip_sections") as batch:
        batch.add_column(sa.Column("outbound_track_source_file_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("trip_sections") as batch:
        batch.drop_column("outbound_track_source_file_id")
