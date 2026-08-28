"""014 journal clock and inherited position on section members

Revision ID: 014_section_member_journal
Revises: 013_day_sections_parked
Create Date: 2026-08-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

revision: str = "014_section_member_journal"
down_revision: str | None = "013_day_sections_parked"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    with op.batch_alter_table("section_members") as batch:
        batch.add_column(sa.Column("journal_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("journal_timezone_name", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("journal_latitude", sa.Float(), nullable=True))
        batch.add_column(sa.Column("journal_longitude", sa.Float(), nullable=True))
    conn = op.get_bind()
    conn.execute(
        text(
            "UPDATE section_members SET "
            "journal_at = (SELECT captured_at FROM source_files "
            "WHERE source_files.id = section_members.source_file_id), "
            "journal_timezone_name = (SELECT timezone_name FROM source_files "
            "WHERE source_files.id = section_members.source_file_id)"
        )
    )
    _snapshot_day_inherit(conn)


def downgrade() -> None:
    with op.batch_alter_table("section_members") as batch:
        batch.drop_column("journal_longitude")
        batch.drop_column("journal_latitude")
        batch.drop_column("journal_timezone_name")
        batch.drop_column("journal_at")


def _snapshot_day_inherit(conn) -> None:  # noqa: ANN001
    days = conn.execute(
        text("SELECT id, cover_source_file_id FROM trip_sections WHERE kind = 'day'")
    ).fetchall()
    for section_id, cover_id in days:
        members = conn.execute(
            text(
                "SELECT m.id, s.id, s.file_kind, s.gps_latitude, s.gps_longitude "
                "FROM section_members m JOIN source_files s ON s.id = m.source_file_id "
                "WHERE m.section_id = :section_id ORDER BY m.sort_index ASC, m.id ASC"
            ),
            {"section_id": section_id},
        ).fetchall()
        files = [
            {
                "member_id": member_id,
                "source_id": source_id,
                "file_kind": file_kind,
                "lat": lat,
                "lon": lon,
            }
            for member_id, source_id, file_kind, lat, lon in members
        ]
        anchor = _cover_anchor(files, cover_id)
        if anchor is None:
            continue
        for item in files:
            if item["lat"] is not None and item["lon"] is not None:
                continue
            conn.execute(
                text(
                    "UPDATE section_members SET journal_latitude = :lat, journal_longitude = :lon "
                    "WHERE id = :member_id"
                ),
                {"lat": anchor[0], "lon": anchor[1], "member_id": item["member_id"]},
            )


def _cover_anchor(files: list[dict], cover_id: object) -> tuple[float, float] | None:
    by_id = {item["source_id"]: item for item in files}
    if cover_id in by_id:
        chosen = by_id[cover_id]
        if chosen["lat"] is not None and chosen["lon"] is not None:
            return (float(chosen["lat"]), float(chosen["lon"]))
    for item in files:
        if item["file_kind"] == "photo" and item["lat"] is not None and item["lon"] is not None:
            return (float(item["lat"]), float(item["lon"]))
    for item in files:
        if item["file_kind"] == "gps" and item["lat"] is not None and item["lon"] is not None:
            return (float(item["lat"]), float(item["lon"]))
    coords = [
        (float(item["lat"]), float(item["lon"]))
        for item in files
        if item["lat"] is not None and item["lon"] is not None
    ]
    if not coords:
        return None
    lat = sum(item[0] for item in coords) / len(coords)
    lon = sum(item[1] for item in coords) / len(coords)
    return (lat, lon)
