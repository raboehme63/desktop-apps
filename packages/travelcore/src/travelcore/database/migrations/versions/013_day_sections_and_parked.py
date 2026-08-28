"""013 Tag sections with members, parked media pool

Revision ID: 013_day_sections_parked
Revises: 012_drop_overnight_stays
Create Date: 2026-08-28
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

revision: str = "013_day_sections_parked"
down_revision: str | None = "012_drop_overnight_stays"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    with op.batch_alter_table("source_files") as batch:
        batch.add_column(sa.Column("parked", sa.Boolean(), nullable=False, server_default=sa.false()))
    _backfill_day_sections()


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(text("DELETE FROM section_members WHERE section_id IN (SELECT id FROM trip_sections WHERE kind = 'day')"))
    conn.execute(text("DELETE FROM trip_sections WHERE kind = 'day'"))
    with op.batch_alter_table("source_files") as batch:
        batch.drop_column("parked")


def _backfill_day_sections() -> None:
    conn = op.get_bind()
    already = conn.execute(text("SELECT COUNT(*) FROM trip_sections WHERE kind = 'day'")).scalar()
    if already:
        return
    days = conn.execute(
        text(
            "SELECT d.id, d.trip_id, d.date, d.title, d.notes, d.youtube_urls, "
            "d.leonardo_urls, d.cover_source_file_id, t.project_id "
            "FROM trip_days d JOIN trips t ON t.id = d.trip_id"
        )
    ).fetchall()
    claimed = {
        row[0]
        for row in conn.execute(text("SELECT source_file_id FROM section_members")).fetchall()
    }
    for _day_id, trip_id, day_date, title, notes, youtube, leonardo, cover, project_id in days:
        key = _as_date(day_date)
        started = datetime.combine(key, time.min, tzinfo=UTC) if key is not None else None
        conn.execute(
            text(
                "INSERT INTO trip_sections (trip_id, kind, title, notes, started_at, ended_at, "
                "youtube_urls, leonardo_urls, cover_source_file_id, sort_index, origin) "
                "VALUES (:trip_id, 'day', :title, :notes, :started, :ended, "
                ":youtube, :leonardo, :cover, 0, 'auto')"
            ),
            {
                "trip_id": trip_id,
                "title": title,
                "notes": notes,
                "started": started,
                "ended": started,
                "youtube": youtube,
                "leonardo": leonardo,
                "cover": cover,
            },
        )
        section_id = conn.execute(text("SELECT last_insert_rowid()")).scalar()
        files = conn.execute(
            text(
                "SELECT id, captured_at FROM source_files "
                "WHERE project_id = :project_id AND file_kind IN ('photo', 'video', 'gps')"
            ),
            {"project_id": project_id},
        ).fetchall()
        sort_index = 0
        for source_id, captured_at in files:
            if source_id in claimed:
                continue
            if _as_date(captured_at) != key:
                continue
            conn.execute(
                text(
                    "INSERT INTO section_members (section_id, source_file_id, sort_index) "
                    "VALUES (:section_id, :source_id, :sort_index)"
                ),
                {"section_id": section_id, "source_id": source_id, "sort_index": sort_index},
            )
            claimed.add(source_id)
            sort_index += 1


def _as_date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        moment = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return moment.date()
    if isinstance(value, date):
        return value
    text_value = str(value)
    if not text_value:
        return None
    try:
        parsed = datetime.fromisoformat(text_value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.date()
