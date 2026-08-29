"""016 ordered connection lines on transfer sections

Revision ID: 016_transfer_links
Revises: 015_section_pin
Create Date: 2026-08-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "016_transfer_links"
down_revision: str | None = "015_section_pin"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "transfer_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "section_id",
            sa.Integer(),
            sa.ForeignKey("trip_sections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sort_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("geometry", sa.String(length=16), nullable=False, server_default="line"),
        sa.Column("dash", sa.String(length=16), nullable=False, server_default="solid"),
        sa.Column("symbol", sa.String(length=16), nullable=True),
        sa.Column("end_latitude", sa.Float(), nullable=True),
        sa.Column("end_longitude", sa.Float(), nullable=True),
        sa.Column(
            "track_source_file_id",
            sa.Integer(),
            sa.ForeignKey("source_files.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.UniqueConstraint("section_id", "sort_index", name="uq_transfer_links_order"),
    )
    op.create_index("ix_transfer_links_section_id", "transfer_links", ["section_id"])


def downgrade() -> None:
    op.drop_index("ix_transfer_links_section_id", table_name="transfer_links")
    op.drop_table("transfer_links")
