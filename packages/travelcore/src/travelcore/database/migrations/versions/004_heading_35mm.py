"""004 heading and 35 mm equivalent focal length

Revision ID: 004_heading_35mm
Revises: 003_igc_tracks
Create Date: 2026-08-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "004_heading_35mm"
down_revision: str | None = "003_igc_tracks"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    with op.batch_alter_table("source_files") as batch:
        batch.add_column(sa.Column("heading_degrees", sa.Float(), nullable=True))
        batch.add_column(sa.Column("heading_ref", sa.String(length=8), nullable=True))
        batch.add_column(sa.Column("heading_source", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("focal_length_35mm", sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("source_files") as batch:
        batch.drop_column("focal_length_35mm")
        batch.drop_column("heading_source")
        batch.drop_column("heading_ref")
        batch.drop_column("heading_degrees")
