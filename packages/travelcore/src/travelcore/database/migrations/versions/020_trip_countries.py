"""020 store visited countries on the trip

Revision ID: 020_trip_countries
Revises: 019_section_hidden
Create Date: 2026-08-31
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "020_trip_countries"
down_revision: str | None = "019_section_hidden"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    with op.batch_alter_table("trips") as batch:
        batch.add_column(sa.Column("countries", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("trips") as batch:
        batch.drop_column("countries")
