"""017 outbound connection on Tag/Stay sections

Revision ID: 017_section_outbound
Revises: 016_transfer_links
Create Date: 2026-08-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "017_section_outbound"
down_revision: str | None = "016_transfer_links"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    with op.batch_alter_table("trip_sections") as batch:
        batch.add_column(sa.Column("outbound_geometry", sa.String(length=16), nullable=True))
        batch.add_column(sa.Column("outbound_dash", sa.String(length=16), nullable=True))
        batch.add_column(sa.Column("outbound_symbol", sa.String(length=16), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("trip_sections") as batch:
        batch.drop_column("outbound_symbol")
        batch.drop_column("outbound_dash")
        batch.drop_column("outbound_geometry")
