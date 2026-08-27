"""Thematic trip sections. Membership is per source file; time comes from the files."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from travelcore.database.models import SectionMember, SourceFile, TripSection
from travelcore.exceptions import ProjectError
from travelcore.media.types import FileKind
from travelcore.timeline.links import serialize_leonardo_urls, serialize_youtube_urls

KIND_DAY = "day"
KIND_STAY = "stay"
KIND_MOVEMENT = "movement"
SECTION_KINDS = frozenset({KIND_STAY, KIND_MOVEMENT})
MOVEMENT_MODES = (
    "bus",
    "train",
    "plane",
    "walk",
    "car",
    "bike",
    "boat",
    "other",
)


def parse_modes(raw: str | None) -> list[str]:
    """Split a stored mode string into known transfer modes, preserving canonical order."""

    if not raw:
        return []
    wanted = {part.strip() for part in raw.split(",") if part.strip()}
    return [mode for mode in MOVEMENT_MODES if mode in wanted]


def serialize_modes(modes: list[str] | None) -> str | None:
    """Store selected transfer modes as a comma-separated string."""

    if not modes:
        return None
    wanted = {mode.strip() for mode in modes if mode and mode.strip()}
    ordered = [mode for mode in MOVEMENT_MODES if mode in wanted]
    return ",".join(ordered) or None


def claimed_source_ids(session: Session, trip_id: int) -> set[int]:
    rows = session.execute(
        select(SectionMember.source_file_id)
        .join(TripSection, SectionMember.section_id == TripSection.id)
        .where(TripSection.trip_id == trip_id)
    )
    return {row[0] for row in rows}


def span_from_files(rows: list[SourceFile]) -> tuple[datetime | None, datetime | None]:
    times: list[datetime] = []
    for row in rows:
        moment = row.captured_at
        if moment is None:
            continue
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        times.append(moment)
    if not times:
        return None, None
    return min(times), max(times)


def format_section_span(started_at: datetime | None, ended_at: datetime | None) -> str:
    """Human date range from member timestamps: ``am`` or ``von … bis …``."""

    start = started_at
    end = ended_at or started_at
    if start is None:
        return "ohne Zeit"
    start_day = start.date()
    end_day = end.date() if end is not None else start_day
    if start_day == end_day:
        return f"am {start_day.strftime('%d.%m.%Y')}"
    return f"von {start_day.strftime('%d.%m.%Y')} bis {end_day.strftime('%d.%m.%Y')}"


def format_section_duration(started_at: datetime | None, ended_at: datetime | None) -> str | None:
    """Elapsed time between first and last object, or None if shorter than a minute."""

    if started_at is None:
        return None
    end = ended_at or started_at
    seconds = int((end - started_at).total_seconds())
    if seconds < 60:
        return None
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} Min."
    hours, rem = divmod(minutes, 60)
    days, hour_part = divmod(hours, 24)
    if days == 0:
        if rem == 0:
            return f"{hours} Std."
        return f"{hours} Std. {rem} Min."
    if days == 1 and hour_part == 0 and rem == 0:
        return "1 Tag"
    if hour_part == 0 and rem == 0:
        return f"{days} Tage"
    if hour_part == 0:
        return f"{days} Tage"
    return f"{days} Tage {hour_part} Std."


def format_section_when(started_at: datetime | None, ended_at: datetime | None) -> str:
    """Date range plus duration when the span is longer than a minute."""

    span = format_section_span(started_at, ended_at)
    duration = format_section_duration(started_at, ended_at)
    if duration:
        return f"{span} · {duration}"
    return span


def create_section(
    session: Session,
    trip_id: int,
    source_file_ids: list[int],
    *,
    kind: str,
    mode: str | None = None,
    title: str | None = None,
    notes: str | None = None,
    location_name: str | None = None,
    location_from: str | None = None,
    location_to: str | None = None,
    youtube_urls: list[str] | None = None,
    leonardo_urls: list[str] | None = None,
    cover_source_file_id: int | None = None,
) -> TripSection:
    """Create a section from selected files. Time span follows the objects."""

    if kind not in SECTION_KINDS:
        raise ProjectError("Unbekannter Abschnittstyp.")
    ids = list(dict.fromkeys(source_file_ids))
    if not ids:
        raise ProjectError("Bitte zuerst Objekte auswählen.")
    rows = list(session.scalars(select(SourceFile).where(SourceFile.id.in_(ids))))
    by_id = {row.id: row for row in rows}
    missing = [item for item in ids if item not in by_id]
    if missing:
        raise ProjectError("Mindestens eine Datei gehört nicht zum Projekt.")
    ordered = sorted(rows, key=_member_sort_key)
    started_at, ended_at = span_from_files(ordered)
    session.execute(delete(SectionMember).where(SectionMember.source_file_id.in_(ids)))
    section = TripSection(
        trip_id=trip_id,
        kind=kind,
        mode=serialize_modes(parse_modes(mode)) if kind == KIND_MOVEMENT else None,
        title=(title or "").strip() or None,
        notes=notes,
        started_at=started_at,
        ended_at=ended_at,
        location_name=(location_name or "").strip() or None,
        location_from=(location_from or "").strip() or None,
        location_to=(location_to or "").strip() or None,
        youtube_urls=serialize_youtube_urls(list(youtube_urls or [])),
        leonardo_urls=serialize_leonardo_urls(list(leonardo_urls or [])),
        cover_source_file_id=_valid_cover_id(ordered, cover_source_file_id),
        sort_index=0,
        origin="manual",
    )
    session.add(section)
    session.flush()
    for index, row in enumerate(ordered):
        session.add(SectionMember(section_id=section.id, source_file_id=row.id, sort_index=index))
    session.flush()
    return section


def update_section_kind(
    session: Session,
    section_id: int,
    kind: str,
    *,
    mode: str | None = None,
) -> None:
    """Switch a saved section between stay and transfer. Does not touch originals."""

    if kind not in SECTION_KINDS:
        raise ProjectError("Unbekannter Abschnittstyp.")
    section = session.get(TripSection, section_id)
    if section is None:
        raise ProjectError("Reiseabschnitt nicht gefunden.")
    section.kind = kind
    section.origin = "manual"
    if kind == KIND_MOVEMENT:
        section.mode = serialize_modes(parse_modes(mode)) if mode else section.mode
        section.location_name = None
        return
    section.mode = None
    section.location_from = None
    section.location_to = None


def save_section_text(session: Session, section_id: int, *, title: str, notes: str) -> None:
    section = session.get(TripSection, section_id)
    if section is None:
        return
    section.title = title.strip() or section.title
    section.notes = notes
    section.origin = "manual"


def save_section_youtube_urls(session: Session, section_id: int, urls: list[str]) -> None:
    section = session.get(TripSection, section_id)
    if section is None:
        return
    section.youtube_urls = serialize_youtube_urls(urls)
    section.origin = "manual"


def save_section_leonardo_urls(session: Session, section_id: int, urls: list[str]) -> None:
    section = session.get(TripSection, section_id)
    if section is None:
        return
    section.leonardo_urls = serialize_leonardo_urls(urls)
    section.origin = "manual"


def dissolve_section(session: Session, section_id: int) -> None:
    """Drop the section; files become leftover days again."""

    session.execute(delete(SectionMember).where(SectionMember.section_id == section_id))
    section = session.get(TripSection, section_id)
    if section is not None:
        session.delete(section)


def expand_range_selection(
    ordered_ids: list[int],
    selected: set[int],
    *,
    excluded: set[int] | None = None,
) -> set[int]:
    """Select every id between the first and last selected entries in ``ordered_ids``.

    ``excluded`` ids strictly inside that span stay unselected (Ctrl+click holes).
    Endpoints are never excluded.
    """

    if len(selected) < 2:
        return set(selected)
    indices = [index for index, item in enumerate(ordered_ids) if item in selected]
    if len(indices) < 2:
        return set(selected)
    start, end = min(indices), max(indices)
    filled = set(ordered_ids[start : end + 1])
    if not excluded:
        return filled
    endpoints = {ordered_ids[start], ordered_ids[end]}
    return filled - (excluded - endpoints)


def _member_sort_key(row: SourceFile) -> tuple[int, datetime, str]:
    moment = row.captured_at
    if moment is None:
        return (1, datetime.max.replace(tzinfo=UTC), row.filename)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return (0, moment, row.filename)


def _valid_cover_id(rows: list[SourceFile], source_file_id: int | None) -> int | None:
    if source_file_id is None:
        return None
    for row in rows:
        if row.id == source_file_id and row.file_kind == FileKind.PHOTO.value:
            return source_file_id
    return None
