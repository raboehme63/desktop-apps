"""003 igc flight tracks

Revision ID: 003_igc_tracks
Revises: 002_captured_source
Create Date: 2026-08-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "003_igc_tracks"
down_revision: str | None = "002_captured_source"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    with op.batch_alter_table("gps_tracks") as batch:
        batch.add_column(sa.Column("track_format", sa.String(length=16), nullable=False, server_default="gpx"))
        batch.add_column(sa.Column("pilot", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("external_url", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("gps_tracks") as batch:
        batch.drop_column("external_url")
        batch.drop_column("pilot")
        batch.drop_column("track_format")
