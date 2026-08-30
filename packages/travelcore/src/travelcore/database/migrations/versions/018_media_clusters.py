"""018 stack/group columns on similarity clusters

Revision ID: 018_media_clusters
Revises: 017_section_outbound
Create Date: 2026-08-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "018_media_clusters"
down_revision: str | None = "017_section_outbound"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    with op.batch_alter_table("similarity_groups") as batch:
        batch.add_column(sa.Column("cluster_type", sa.String(length=16), nullable=False, server_default="stack"))
        batch.add_column(sa.Column("status", sa.String(length=16), nullable=False, server_default="accepted"))
        batch.add_column(sa.Column("origin", sa.String(length=16), nullable=False, server_default="auto"))
    with op.batch_alter_table("similarity_group_members") as batch:
        batch.add_column(sa.Column("is_key", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("similarity_group_members") as batch:
        batch.drop_column("is_key")
    with op.batch_alter_table("similarity_groups") as batch:
        batch.drop_column("origin")
        batch.drop_column("status")
        batch.drop_column("cluster_type")
