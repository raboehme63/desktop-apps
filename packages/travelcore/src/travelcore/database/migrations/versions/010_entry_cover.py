"""010 cover image per trip day and section

Revision ID: 010_entry_cover
Revises: 009_photo_sort_status
Create Date: 2026-08-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "010_entry_cover"
down_revision: str | None = "009_photo_sort_status"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    with op.batch_alter_table("trip_days") as batch:
        batch.add_column(sa.Column("cover_source_file_id", sa.Integer(), nullable=True))
    with op.batch_alter_table("trip_sections") as batch:
        batch.add_column(sa.Column("cover_source_file_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("trip_sections") as batch:
        batch.drop_column("cover_source_file_id")
    with op.batch_alter_table("trip_days") as batch:
        batch.drop_column("cover_source_file_id")
