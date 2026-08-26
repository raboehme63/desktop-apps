"""011 user display rotation on source files

Revision ID: 011_rotation_degrees
Revises: 010_entry_cover
Create Date: 2026-08-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "011_rotation_degrees"
down_revision: str | None = "010_entry_cover"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    with op.batch_alter_table("source_files") as batch:
        batch.add_column(
            sa.Column("rotation_degrees", sa.Integer(), nullable=False, server_default="0")
        )


def downgrade() -> None:
    with op.batch_alter_table("source_files") as batch:
        batch.drop_column("rotation_degrees")
