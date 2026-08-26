"""005 trip sections and section members

Revision ID: 005_trip_sections
Revises: 004_heading_35mm
Create Date: 2026-08-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "005_trip_sections"
down_revision: str | None = "004_heading_35mm"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "trip_sections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("trip_id", sa.Integer(), sa.ForeignKey("trips.id"), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("location_name", sa.String(length=255), nullable=True),
        sa.Column("location_from", sa.String(length=255), nullable=True),
        sa.Column("location_to", sa.String(length=255), nullable=True),
        sa.Column("sort_index", sa.Integer(), nullable=False),
        sa.Column("origin", sa.String(length=16), nullable=False),
    )
    op.create_index("ix_trip_sections_trip_id", "trip_sections", ["trip_id"])
    op.create_table(
        "section_members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("section_id", sa.Integer(), sa.ForeignKey("trip_sections.id"), nullable=False),
        sa.Column("source_file_id", sa.Integer(), sa.ForeignKey("source_files.id"), nullable=False),
        sa.Column("sort_index", sa.Integer(), nullable=False),
        sa.UniqueConstraint("source_file_id", name="uq_section_members_source"),
    )
    op.create_index("ix_section_members_section_id", "section_members", ["section_id"])
    op.create_index("ix_section_members_source_file_id", "section_members", ["source_file_id"])


def downgrade() -> None:
    op.drop_index("ix_section_members_source_file_id", table_name="section_members")
    op.drop_index("ix_section_members_section_id", table_name="section_members")
    op.drop_table("section_members")
    op.drop_index("ix_trip_sections_trip_id", table_name="trip_sections")
    op.drop_table("trip_sections")
