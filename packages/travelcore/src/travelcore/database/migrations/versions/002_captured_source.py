"""002 captured_at_source

Revision ID: 002_captured_source
Revises: 001_initial
Create Date: 2026-08-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "002_captured_source"
down_revision: str | None = "001_initial"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("source_files", sa.Column("captured_at_source", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("source_files", "captured_at_source")
