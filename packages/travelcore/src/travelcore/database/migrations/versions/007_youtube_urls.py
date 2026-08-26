"""007 youtube urls on days and sections

Revision ID: 007_youtube_urls
Revises: 006_section_modes
Create Date: 2026-08-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "007_youtube_urls"
down_revision: str | None = "006_section_modes"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    with op.batch_alter_table("trip_days") as batch:
        batch.add_column(sa.Column("youtube_urls", sa.Text(), nullable=True))
    with op.batch_alter_table("trip_sections") as batch:
        batch.add_column(sa.Column("youtube_urls", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("trip_sections") as batch:
        batch.drop_column("youtube_urls")
    with op.batch_alter_table("trip_days") as batch:
        batch.drop_column("youtube_urls")
