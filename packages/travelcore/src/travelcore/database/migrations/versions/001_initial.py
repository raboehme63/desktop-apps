"""Initial project schema.

Revision ID: 001_initial
Revises:
Create Date: 2026-08-18
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "001_initial"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_root", sa.Text(), nullable=True),
        sa.Column("default_timezone", sa.String(length=64), nullable=True),
        sa.Column("settings_json", sa.Text(), nullable=True),
    )
    op.create_table(
        "source_files",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("filename", sa.String(length=512), nullable=False),
        sa.Column("file_kind", sa.String(length=32), nullable=False),
        sa.Column("extension", sa.String(length=32), nullable=False),
        sa.Column("mime_type", sa.String(length=128), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("fs_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fs_modified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("captured_at_raw", sa.String(length=64), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("timezone_name", sa.String(length=64), nullable=True),
        sa.Column("timezone_unknown", sa.Boolean(), nullable=False),
        sa.Column("gps_latitude", sa.Float(), nullable=True),
        sa.Column("gps_longitude", sa.Float(), nullable=True),
        sa.Column("gps_altitude", sa.Float(), nullable=True),
        sa.Column("position_source", sa.String(length=32), nullable=True),
        sa.Column("position_confidence", sa.Float(), nullable=True),
        sa.Column("position_time_delta_seconds", sa.Float(), nullable=True),
        sa.Column("camera", sa.String(length=255), nullable=True),
        sa.Column("lens", sa.String(length=255), nullable=True),
        sa.Column("focal_length", sa.Float(), nullable=True),
        sa.Column("iso", sa.Integer(), nullable=True),
        sa.Column("exposure_time", sa.String(length=64), nullable=True),
        sa.Column("aperture", sa.String(length=32), nullable=True),
        sa.Column("orientation", sa.Integer(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.UniqueConstraint("project_id", "path", name="uq_source_files_path"),
    )
    op.create_index("ix_source_files_project_id", "source_files", ["project_id"])
    op.create_index("ix_source_files_file_kind", "source_files", ["file_kind"])
    op.create_index("ix_source_files_sha256", "source_files", ["sha256"])

    op.create_table(
        "file_errors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("stage", sa.String(length=64), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_file_errors_project_id", "file_errors", ["project_id"])

    op.create_table(
        "photos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_file_id", sa.Integer(), sa.ForeignKey("source_files.id"), nullable=False),
        sa.Column("is_favorite", sa.Boolean(), nullable=False),
        sa.Column("used_in_journal", sa.Boolean(), nullable=False),
        sa.Column("is_cover", sa.Boolean(), nullable=False),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("sort_index", sa.Integer(), nullable=True),
        sa.Column("origin", sa.String(length=16), nullable=False),
        sa.UniqueConstraint("source_file_id"),
    )
    op.create_table(
        "videos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_file_id", sa.Integer(), sa.ForeignKey("source_files.id"), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("origin", sa.String(length=16), nullable=False),
        sa.UniqueConstraint("source_file_id"),
    )
    op.create_table(
        "gps_tracks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("source_file_id", sa.Integer(), sa.ForeignKey("source_files.id"), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("origin", sa.String(length=16), nullable=False),
    )
    op.create_index("ix_gps_tracks_project_id", "gps_tracks", ["project_id"])
    op.create_table(
        "gps_points",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("track_id", sa.Integer(), sa.ForeignKey("gps_tracks.id"), nullable=False),
        sa.Column("segment_id", sa.Integer(), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("altitude", sa.Float(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sequence_index", sa.Integer(), nullable=False),
    )
    op.create_index("ix_gps_points_track_id", "gps_points", ["track_id"])

    op.create_table(
        "trips",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("origin", sa.String(length=16), nullable=False),
    )
    op.create_index("ix_trips_project_id", "trips", ["project_id"])
    op.create_table(
        "trip_days",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("trip_id", sa.Integer(), sa.ForeignKey("trips.id"), nullable=False),
        sa.Column("day_index", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("origin", sa.String(length=16), nullable=False),
    )
    op.create_index("ix_trip_days_trip_id", "trip_days", ["trip_id"])
    op.create_table(
        "places",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("day_id", sa.Integer(), sa.ForeignKey("trip_days.id"), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("radius_meters", sa.Float(), nullable=True),
        sa.Column("arrived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("departed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed", sa.Boolean(), nullable=False),
        sa.Column("origin", sa.String(length=16), nullable=False),
    )
    op.create_index("ix_places_day_id", "places", ["day_id"])
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("day_id", sa.Integer(), sa.ForeignKey("trip_days.id"), nullable=True),
        sa.Column("place_id", sa.Integer(), sa.ForeignKey("places.id"), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sort_index", sa.Integer(), nullable=False),
        sa.Column("origin", sa.String(length=16), nullable=False),
    )
    op.create_index("ix_events_day_id", "events", ["day_id"])
    op.create_table(
        "overnight_stays",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("day_id", sa.Integer(), sa.ForeignKey("trip_days.id"), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("location_name", sa.String(length=255), nullable=True),
        sa.Column("stayed_on", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("origin", sa.String(length=16), nullable=False),
    )
    op.create_index("ix_overnight_stays_day_id", "overnight_stays", ["day_id"])
    op.create_table(
        "text_notes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("day_id", sa.Integer(), sa.ForeignKey("trip_days.id"), nullable=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id"), nullable=True),
        sa.Column("source_file_id", sa.Integer(), sa.ForeignKey("source_files.id"), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("origin", sa.String(length=16), nullable=False),
    )
    op.create_index("ix_text_notes_day_id", "text_notes", ["day_id"])
    op.create_table(
        "photo_analyses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("photo_id", sa.Integer(), sa.ForeignKey("photos.id"), nullable=False),
        sa.Column("resolution_score", sa.Float(), nullable=True),
        sa.Column("brightness", sa.Float(), nullable=True),
        sa.Column("contrast", sa.Float(), nullable=True),
        sa.Column("sharpness", sa.Float(), nullable=True),
        sa.Column("overexposed", sa.Boolean(), nullable=True),
        sa.Column("underexposed", sa.Boolean(), nullable=True),
        sa.Column("technical_quality", sa.Float(), nullable=True),
        sa.Column("analyzed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("photo_id"),
    )
    op.create_table(
        "similarity_groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("method", sa.String(length=64), nullable=False),
    )
    op.create_index("ix_similarity_groups_project_id", "similarity_groups", ["project_id"])
    op.create_table(
        "similarity_group_members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "group_id",
            sa.Integer(),
            sa.ForeignKey("similarity_groups.id"),
            nullable=False,
        ),
        sa.Column("source_file_id", sa.Integer(), sa.ForeignKey("source_files.id"), nullable=False),
        sa.Column("distance", sa.Float(), nullable=True),
    )
    op.create_index("ix_similarity_group_members_group_id", "similarity_group_members", ["group_id"])
    op.create_table(
        "export_configs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("exporter", sa.String(length=64), nullable=False),
        sa.Column("settings_json", sa.Text(), nullable=True),
        sa.Column("last_export_path", sa.Text(), nullable=True),
        sa.Column("last_exported_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_export_configs_project_id", "export_configs", ["project_id"])


def downgrade() -> None:
    op.drop_table("export_configs")
    op.drop_table("similarity_group_members")
    op.drop_table("similarity_groups")
    op.drop_table("photo_analyses")
    op.drop_table("text_notes")
    op.drop_table("overnight_stays")
    op.drop_table("events")
    op.drop_table("places")
    op.drop_table("trip_days")
    op.drop_table("trips")
    op.drop_table("gps_points")
    op.drop_table("gps_tracks")
    op.drop_table("videos")
    op.drop_table("photos")
    op.drop_table("file_errors")
    op.drop_table("source_files")
    op.drop_table("projects")
