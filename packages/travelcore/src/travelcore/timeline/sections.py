"""Thematic trip sections. Tag, Aufenthalt and Transfer share membership."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from travelcore.database.models import SectionMember, SourceFile, TripSection
from travelcore.exceptions import ProjectError
from travelcore.media.types import FileKind
from travelcore.timeline.journal import (
    aware,
    calendar_key,
    init_journal_clock,
    scattered_positions,
    section_map_anchor,
    snap_clock_to_date,
    snapshot_tag_position,
)
from travelcore.timeline.links import serialize_leonardo_urls, serialize_youtube_urls

KIND_DAY = "day"
KIND_STAY = "stay"
KIND_MOVEMENT = "movement"
SECTION_KINDS = frozenset({KIND_DAY, KIND_STAY, KIND_MOVEMENT})
ORIGIN_AUTO = "auto"
ORIGIN_MANUAL = "manual"
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


@dataclass(slots=True)
class _Clock:
    journal_at: datetime | None
    timezone_name: str | None
    latitude: float | None = None
    longitude: float | None = None


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


def day_bounds(key: date | None) -> tuple[datetime | None, datetime | None]:
    """Journal span of a Tag: midnight UTC of that calendar day, twice."""

    if key is None:
        return None, None
    start = datetime.combine(key, time.min, tzinfo=UTC)
    return start, start


def span_is_single_calendar_day(started_at: datetime | None, ended_at: datetime | None) -> bool:
    start = calendar_key(started_at)
    end = calendar_key(ended_at if ended_at is not None else started_at)
    return start is not None and start == end


def claimed_source_ids(session: Session, trip_id: int) -> set[int]:
    rows = session.execute(
        select(SectionMember.source_file_id)
        .join(TripSection, SectionMember.section_id == TripSection.id)
        .where(TripSection.trip_id == trip_id)
    )
    return {row[0] for row in rows}


def span_from_moments(moments: list[datetime | None]) -> tuple[datetime | None, datetime | None]:
    times = [item for item in (aware(moment) for moment in moments) if item is not None]
    if not times:
        return None, None
    return min(times), max(times)


def span_from_files(rows: list[SourceFile]) -> tuple[datetime | None, datetime | None]:
    return span_from_moments([row.captured_at for row in rows])


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
    origin: str = ORIGIN_MANUAL,
) -> TripSection:
    """Create a section from selected files. Tag span is one calendar day; others follow objects."""

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
    clocks = _take_member_clocks(session, ids)
    session.execute(delete(SectionMember).where(SectionMember.source_file_id.in_(ids)))
    for row in rows:
        row.parked = False
        if row.id not in clocks:
            clocks[row.id] = _Clock(*init_journal_clock(row, None))
    ordered = sorted(rows, key=lambda row: _clock_sort_key(clocks[row.id].journal_at, row.filename))
    if kind == KIND_DAY:
        keys = {calendar_key(clocks[row.id].journal_at) for row in ordered}
        if len(keys) > 1:
            raise ProjectError("Ein Tag ist genau ein Kalendertag. Auswahl umfasst mehrere Daten.")
        started_at, ended_at = day_bounds(next(iter(keys)))
    else:
        started_at, ended_at = span_from_moments([clocks[row.id].journal_at for row in ordered])
    section = TripSection(
        trip_id=trip_id,
        kind=kind,
        mode=serialize_modes(parse_modes(mode)) if kind == KIND_MOVEMENT else None,
        title=(title or "").strip() or None,
        notes=notes,
        started_at=started_at,
        ended_at=ended_at,
        location_name=(location_name or "").strip() or None if kind == KIND_STAY else None,
        location_from=(location_from or "").strip() or None if kind == KIND_MOVEMENT else None,
        location_to=(location_to or "").strip() or None if kind == KIND_MOVEMENT else None,
        youtube_urls=serialize_youtube_urls(list(youtube_urls or [])),
        leonardo_urls=serialize_leonardo_urls(list(leonardo_urls or [])),
        cover_source_file_id=_valid_cover_id(ordered, cover_source_file_id),
        sort_index=0,
        origin=origin,
    )
    session.add(section)
    session.flush()
    _add_members(session, section, ordered, clocks)
    drop_empty_auto_day_sections(session, trip_id)
    return section


def update_section_kind(
    session: Session,
    section_id: int,
    kind: str,
    *,
    mode: str | None = None,
) -> None:
    """Switch a saved section between Tag, Aufenthalt and Transfer. Does not touch originals."""

    if kind not in SECTION_KINDS:
        raise ProjectError("Unbekannter Abschnittstyp.")
    section = session.get(TripSection, section_id)
    if section is None:
        raise ProjectError("Reiseabschnitt nicht gefunden.")
    if kind == KIND_DAY and not span_is_single_calendar_day(section.started_at, section.ended_at):
        raise ProjectError(
            "Ein Tag ist genau ein Kalendertag. Bitte den Abschnitt zuerst auflösen, "
            "dann entstehen Tage nach der Journal-Zeit der Medien."
        )
    members = _member_rows(session, section.id)
    files = [source for source, _member in members]
    section.kind = kind
    section.origin = ORIGIN_MANUAL
    if kind == KIND_DAY:
        key = calendar_key(section.started_at) or (
            calendar_key(members[0][1].journal_at) if members else None
        )
        section.started_at, section.ended_at = day_bounds(key)
        section.mode = None
        section.location_name = None
        section.location_from = None
        section.location_to = None
        for source, member in members:
            member.journal_at = snap_clock_to_date(member.journal_at, key)
            lat, lon = snapshot_tag_position(source, files, section.cover_source_file_id)
            member.journal_latitude = lat
            member.journal_longitude = lon
        return
    if kind == KIND_MOVEMENT:
        section.mode = serialize_modes(parse_modes(mode)) if mode else section.mode
        section.location_name = None
        for _source, member in members:
            member.journal_latitude = None
            member.journal_longitude = None
        _refresh_section_span(session, section)
        return
    section.mode = None
    section.location_from = None
    section.location_to = None
    for _source, member in members:
        member.journal_latitude = None
        member.journal_longitude = None
    _refresh_section_span(session, section)


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
    """Drop stay/transfer (or a Tag); unparked files return to Tags by journal date."""

    section = session.get(TripSection, section_id)
    if section is None:
        return
    trip_id = section.trip_id
    payload = _member_rows(session, section_id)
    clocks = {
        source.id: _Clock(
            journal_at=member.journal_at,
            timezone_name=member.journal_timezone_name,
            latitude=member.journal_latitude,
            longitude=member.journal_longitude,
        )
        for source, member in payload
        if source.id is not None
    }
    files = [source for source, _member in payload]
    session.execute(delete(SectionMember).where(SectionMember.section_id == section_id))
    session.delete(section)
    session.flush()
    rehome_files_to_day_sections(session, trip_id, files, clocks=clocks)
    drop_empty_auto_day_sections(session, trip_id)


def move_members(
    session: Session,
    section_id: int,
    source_file_ids: list[int],
    *,
    keep_gps: bool = True,
) -> None:
    """Move files onto an existing section. Tag membership snaps the journal date."""

    section = session.get(TripSection, section_id)
    if section is None:
        raise ProjectError("Reiseabschnitt nicht gefunden.")
    ids = list(dict.fromkeys(source_file_ids))
    if not ids:
        return
    rows = list(session.scalars(select(SourceFile).where(SourceFile.id.in_(ids))))
    by_id = {row.id: row for row in rows}
    missing = [item for item in ids if item not in by_id]
    if missing:
        raise ProjectError("Mindestens eine Datei gehört nicht zum Projekt.")
    clocks = _take_member_clocks(session, ids)
    session.execute(delete(SectionMember).where(SectionMember.source_file_id.in_(ids)))
    for row in rows:
        row.parked = False
        if row.id not in clocks:
            clocks[row.id] = _Clock(*init_journal_clock(row, section))
    ordered = sorted(rows, key=lambda row: _clock_sort_key(clocks[row.id].journal_at, row.filename))
    existing = list(
        session.scalars(
            select(SectionMember)
            .where(SectionMember.section_id == section_id)
            .order_by(SectionMember.sort_index.asc())
        )
    )
    start = (existing[-1].sort_index + 1) if existing else 0
    _add_members(session, section, ordered, clocks, start=start)
    if not keep_gps:
        _adopt_section_positions(session, section, ordered)
    _refresh_section_span(session, section)
    drop_empty_auto_day_sections(session, section.trip_id)


def _adopt_section_positions(session: Session, section: TripSection, rows: list[SourceFile]) -> None:
    """Pin display coordinates to the section. Original GPS on SourceFile stays."""

    wanted = {row.id for row in rows if row.id is not None}
    members = _member_rows(session, section.id)
    files = [source for source, _member in members]
    incoming = [(source, member) for source, member in members if source.id in wanted]
    if not incoming:
        return
    ignore = {source.id for source, _member in incoming}
    anchor = section_map_anchor(session, section, files, ignore_source_ids=ignore)
    if anchor is None:
        return
    points = scattered_positions(anchor, len(incoming))
    for (_source, member), point in zip(incoming, points, strict=True):
        member.journal_latitude = point[0]
        member.journal_longitude = point[1]
    session.flush()


def park_media(session: Session, source_file_ids: list[int]) -> None:
    """Remove journal membership; files stay in the media pool until unparked."""

    ids = list(dict.fromkeys(source_file_ids))
    if not ids:
        return
    rows = list(session.scalars(select(SourceFile).where(SourceFile.id.in_(ids))))
    member_sections = list(
        session.execute(
            select(SectionMember.section_id, TripSection.trip_id)
            .join(TripSection, TripSection.id == SectionMember.section_id)
            .where(SectionMember.source_file_id.in_(ids))
        )
    )
    section_ids = {section_id for section_id, _trip_id in member_sections}
    trip_ids = {trip_id for _section_id, trip_id in member_sections}
    session.execute(delete(SectionMember).where(SectionMember.source_file_id.in_(ids)))
    for row in rows:
        row.parked = True
    session.flush()
    for section_id in section_ids:
        section = session.get(TripSection, section_id)
        if section is not None:
            _refresh_section_span(session, section)
    for trip_id in trip_ids:
        drop_empty_auto_day_sections(session, trip_id)


def unpark_media(session: Session, source_file_ids: list[int]) -> None:
    """Clear the parked flag. Caller runs sync so files join Auto-Tags by original date."""

    ids = list(dict.fromkeys(source_file_ids))
    if not ids:
        return
    rows = list(session.scalars(select(SourceFile).where(SourceFile.id.in_(ids))))
    for row in rows:
        row.parked = False


def set_journal_at(
    session: Session,
    source_file_ids: list[int],
    journal_at: datetime | None,
    *,
    timezone_name: str | None = None,
) -> None:
    """Move clips on the journal clock. Original capture time is not written."""

    ids = list(dict.fromkeys(source_file_ids))
    if not ids:
        return
    stamp = aware(journal_at)
    members = list(
        session.scalars(select(SectionMember).where(SectionMember.source_file_id.in_(ids)))
    )
    section_ids: set[int] = set()
    for member in members:
        member.journal_at = stamp
        if timezone_name is not None:
            member.journal_timezone_name = timezone_name
        section_ids.add(member.section_id)
    session.flush()
    for section_id in section_ids:
        _apply_magnetic_day(session, section_id, ids)
        section = session.get(TripSection, section_id)
        if section is not None:
            _refresh_section_span(session, section)
            drop_empty_auto_day_sections(session, section.trip_id)


def reset_journal(session: Session, source_file_ids: list[int]) -> None:
    """Copy original capture time back onto the journal clock and re-home magnetically."""

    ids = list(dict.fromkeys(source_file_ids))
    if not ids:
        return
    rows = list(session.scalars(select(SourceFile).where(SourceFile.id.in_(ids))))
    by_id = {row.id: row for row in rows}
    members = list(
        session.scalars(select(SectionMember).where(SectionMember.source_file_id.in_(ids)))
    )
    section_ids: set[int] = set()
    for member in members:
        source = by_id.get(member.source_file_id)
        if source is None:
            continue
        member.journal_at, member.journal_timezone_name = init_journal_clock(source, None)
        member.journal_latitude = None
        member.journal_longitude = None
        section_ids.add(member.section_id)
    session.flush()
    for section_id in section_ids:
        _apply_magnetic_day(session, section_id, ids)
        section = session.get(TripSection, section_id)
        if section is not None:
            _refresh_section_span(session, section)
            drop_empty_auto_day_sections(session, section.trip_id)


def sort_members_by_journal(session: Session, section_id: int) -> None:
    """Reorder membership by journal_at. Does not change the clock."""

    rows = _member_rows(session, section_id)
    ordered = sorted(
        rows,
        key=lambda item: _clock_sort_key(item[1].journal_at, item[0].filename),
    )
    for index, (_source, member) in enumerate(ordered):
        member.sort_index = index
    session.flush()


def ensure_day_memberships(
    session: Session,
    trip_id: int,
    media: list[SourceFile],
    *,
    titles: dict[date | None, str | None] | None = None,
    notes: dict[date | None, str | None] | None = None,
    youtube: dict[date | None, str | None] | None = None,
    leonardo: dict[date | None, str | None] | None = None,
    covers: dict[date | None, int | None] | None = None,
) -> None:
    """Assign unclaimed, unparked files to Auto-Tag sections by original capture date."""

    claimed = claimed_source_ids(session, trip_id)
    grouped: dict[date | None, list[SourceFile]] = {}
    for row in media:
        if row.parked or row.id in claimed:
            continue
        grouped.setdefault(calendar_key(row.captured_at), []).append(row)
    for key, rows in grouped.items():
        section = day_section_for_date(session, trip_id, key, create=True)
        if section is None:
            continue
        if section.origin == ORIGIN_AUTO:
            if titles and titles.get(key):
                section.title = titles[key]
            if notes and notes.get(key):
                section.notes = notes[key]
            if youtube:
                section.youtube_urls = youtube.get(key)
            if leonardo:
                section.leonardo_urls = leonardo.get(key)
            if covers and covers.get(key):
                section.cover_source_file_id = covers[key]
        _append_members(session, section, rows)
    drop_empty_auto_day_sections(session, trip_id)


def rehome_files_to_day_sections(
    session: Session,
    trip_id: int,
    files: list[SourceFile],
    *,
    clocks: dict[int, _Clock] | None = None,
) -> None:
    """Put unparked files onto Tag sections keyed by journal_at (fallback captured_at)."""

    claimed = claimed_source_ids(session, trip_id)
    grouped: dict[date | None, list[SourceFile]] = {}
    resolved: dict[int, _Clock] = dict(clocks or {})
    for row in files:
        if row.parked or row.id in claimed:
            continue
        clock = resolved.get(row.id) or _Clock(*init_journal_clock(row, None))
        resolved[row.id] = clock
        grouped.setdefault(calendar_key(clock.journal_at), []).append(row)
    for key, rows in grouped.items():
        section = day_section_for_date(session, trip_id, key, create=True)
        if section is None:
            continue
        _add_members(session, section, rows, resolved)


def day_section_for_date(
    session: Session,
    trip_id: int,
    key: date | None,
    *,
    create: bool,
) -> TripSection | None:
    """The Tag section for a calendar day. Prefers origin=auto when several exist."""

    matches: list[TripSection] = []
    sections = session.scalars(
        select(TripSection).where(TripSection.trip_id == trip_id, TripSection.kind == KIND_DAY)
    )
    for section in sections:
        if calendar_key(section.started_at) == key:
            matches.append(section)
    auto = [item for item in matches if item.origin == ORIGIN_AUTO]
    if auto:
        return auto[0]
    if matches:
        return matches[0]
    if not create:
        return None
    started_at, ended_at = day_bounds(key)
    title = "Ohne Datum" if key is None else key.strftime("%d.%m.%Y")
    section = TripSection(
        trip_id=trip_id,
        kind=KIND_DAY,
        title=title,
        started_at=started_at,
        ended_at=ended_at,
        sort_index=0,
        origin=ORIGIN_AUTO,
    )
    session.add(section)
    session.flush()
    return section


def drop_empty_auto_day_sections(session: Session, trip_id: int) -> None:
    """Remove auto Tags that have no members and no journal text."""

    sections = list(
        session.scalars(
            select(TripSection).where(
                TripSection.trip_id == trip_id,
                TripSection.kind == KIND_DAY,
                TripSection.origin == ORIGIN_AUTO,
            )
        )
    )
    for section in sections:
        has_member = session.scalar(
            select(SectionMember.id).where(SectionMember.section_id == section.id).limit(1)
        )
        if has_member is not None:
            continue
        if (section.notes or "").strip() or (section.youtube_urls or "").strip():
            continue
        session.delete(section)
    session.flush()


def _append_members(session: Session, section: TripSection, rows: list[SourceFile]) -> None:
    clocks = {row.id: _Clock(*init_journal_clock(row, section)) for row in rows if row.id is not None}
    _add_members(session, section, rows, clocks)


def _add_members(
    session: Session,
    section: TripSection,
    rows: list[SourceFile],
    clocks: dict[int, _Clock],
    *,
    start: int | None = None,
) -> None:
    existing = {
        row[0]
        for row in session.execute(
            select(SectionMember.source_file_id).where(SectionMember.section_id == section.id)
        )
    }
    offset = len(existing) if start is None else start
    incoming = [row for row in rows if row.id not in existing]
    siblings = _member_files(session, section.id) + incoming
    tag_key = calendar_key(section.started_at) if section.kind == KIND_DAY else None
    stay_or_move = section.kind in {KIND_STAY, KIND_MOVEMENT}
    for index, row in enumerate(incoming):
        row.parked = False
        clock = clocks.get(row.id) or _Clock(*init_journal_clock(row, section))
        journal_at = clock.journal_at
        latitude = clock.latitude
        longitude = clock.longitude
        if tag_key is not None or (section.kind == KIND_DAY):
            journal_at = snap_clock_to_date(journal_at, tag_key)
            latitude, longitude = snapshot_tag_position(row, siblings, section.cover_source_file_id)
        elif stay_or_move:
            latitude = None
            longitude = None
        session.add(
            SectionMember(
                section_id=section.id,
                source_file_id=row.id,
                sort_index=offset + index,
                journal_at=journal_at,
                journal_timezone_name=clock.timezone_name,
                journal_latitude=latitude,
                journal_longitude=longitude,
            )
        )
    session.flush()
    if incoming:
        sort_members_by_journal(session, section.id)


def _member_files(session: Session, section_id: int) -> list[SourceFile]:
    return [source for source, _member in _member_rows(session, section_id)]


def _member_rows(session: Session, section_id: int) -> list[tuple[SourceFile, SectionMember]]:
    rows = list(
        session.execute(
            select(SourceFile, SectionMember)
            .join(SectionMember, SectionMember.source_file_id == SourceFile.id)
            .where(SectionMember.section_id == section_id)
            .order_by(SectionMember.sort_index.asc(), SourceFile.filename.asc())
        )
    )
    return [(source, member) for source, member in rows]


def _take_member_clocks(session: Session, source_file_ids: list[int]) -> dict[int, _Clock]:
    rows = list(
        session.scalars(select(SectionMember).where(SectionMember.source_file_id.in_(source_file_ids)))
    )
    return {
        member.source_file_id: _Clock(
            journal_at=member.journal_at,
            timezone_name=member.journal_timezone_name,
            latitude=member.journal_latitude,
            longitude=member.journal_longitude,
        )
        for member in rows
    }


def _apply_magnetic_day(session: Session, section_id: int, source_file_ids: list[int]) -> None:
    section = session.get(TripSection, section_id)
    if section is None or section.kind != KIND_DAY:
        return
    wanted = set(source_file_ids)
    rows = [
        (source, member)
        for source, member in _member_rows(session, section_id)
        if source.id in wanted
    ]
    for source, member in rows:
        key = calendar_key(member.journal_at)
        if key == calendar_key(section.started_at):
            siblings = _member_files(session, section.id)
            lat, lon = snapshot_tag_position(source, siblings, section.cover_source_file_id)
            if member.journal_latitude is None or member.journal_longitude is None:
                member.journal_latitude = lat
                member.journal_longitude = lon
            continue
        target = day_section_for_date(session, section.trip_id, key, create=True)
        if target is None or target.id == section.id:
            continue
        clock = _Clock(
            journal_at=member.journal_at,
            timezone_name=member.journal_timezone_name,
            latitude=None,
            longitude=None,
        )
        session.delete(member)
        session.flush()
        _add_members(session, target, [source], {source.id: clock})


def _refresh_section_span(session: Session, section: TripSection) -> None:
    if section.kind == KIND_DAY:
        return
    moments = [member.journal_at for _source, member in _member_rows(session, section.id)]
    started, ended = span_from_moments(moments)
    if started is None and ended is None:
        return
    section.started_at = started
    section.ended_at = ended


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


def _clock_sort_key(moment: datetime | None, filename: str) -> tuple[int, datetime, str]:
    stamp = aware(moment)
    if stamp is None:
        return (1, datetime.max.replace(tzinfo=UTC), filename)
    return (0, stamp, filename)


def _member_sort_key(row: SourceFile) -> tuple[int, datetime, str]:
    return _clock_sort_key(row.captured_at, row.filename)


def _valid_cover_id(rows: list[SourceFile], source_file_id: int | None) -> int | None:
    if source_file_id is None:
        return None
    for row in rows:
        if row.id == source_file_id and row.file_kind == FileKind.PHOTO.value:
            return source_file_id
    return None
