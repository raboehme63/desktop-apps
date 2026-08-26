"""009 photo sort status for favorite/reserve/rejected

Revision ID: 009_photo_sort_status
Revises: 008_leonardo_urls
Create Date: 2026-08-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "009_photo_sort_status"
down_revision: str | None = "008_leonardo_urls"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    with op.batch_alter_table("photos") as batch:
        batch.add_column(sa.Column("sort_status", sa.String(length=16), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("photos") as batch:
        batch.drop_column("sort_status")
