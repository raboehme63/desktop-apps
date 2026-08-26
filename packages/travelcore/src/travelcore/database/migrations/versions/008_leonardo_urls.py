"""008 leonardo urls on days and sections

Revision ID: 008_leonardo_urls
Revises: 007_youtube_urls
Create Date: 2026-08-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "008_leonardo_urls"
down_revision: str | None = "007_youtube_urls"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    with op.batch_alter_table("trip_days") as batch:
        batch.add_column(sa.Column("leonardo_urls", sa.Text(), nullable=True))
    with op.batch_alter_table("trip_sections") as batch:
        batch.add_column(sa.Column("leonardo_urls", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("trip_sections") as batch:
        batch.drop_column("leonardo_urls")
    with op.batch_alter_table("trip_days") as batch:
        batch.drop_column("leonardo_urls")
