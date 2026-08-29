"""Build and update the trip timeline. Manual rows are never overwritten."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from datetime import UTC, date, datetime, time
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from travelcore.config import AppSettings
from travelcore.database.models import (
    Event,
    Photo,
    Place,
    Project,
    SectionMember,
    SourceFile,
    Trip,
    TripDay,
    TripSection,
)
from travelcore.exceptions import ProjectError
from travelcore.geolocation.stays import cluster_stays
from travelcore.gps.ingest import track_urls_by_source
from travelcore.media.gallery import SORT_FAVORITE, SORT_STATUSES, effective_sort_status
from travelcore.media.orientation import normalize_rotation_degrees
from travelcore.media.thumbnails import cached_thumbnail_path, ensure_photo_and_video_rows
from travelcore.media.types import FileKind
from travelcore.timeline.journal import aware, display_position
from travelcore.timeline.links import (
    parse_leonardo_urls,
    parse_youtube_urls,
    serialize_leonardo_urls,
    serialize_youtube_urls,
)
from travelcore.timeline.sections import (
    KIND_DAY,
    KIND_MOVEMENT,
    KIND_STAY,
    calendar_key,
    day_section_for_date,
    ensure_day_memberships,
)
from travelcore.timeline.texts import (
    JOURNAL_TEXT_SUFFIXES,
    combine_imported_texts,
    date_from_text_filename,
    read_imported_text,
)
from travelcore.timeline.transfer_links import load_transfer_links_for_sections
from travelcore.timeline.types import (
    PendingSectionSpec,
    TimelineDay,
    TimelineEntry,
    TimelineEvent,
    TimelinePhoto,
    TimelinePlace,
    TimelineSection,
    TimelineSnapshot,
)

ORIGIN_AUTO = "auto"
ORIGIN_MANUAL = "manual"


def sync_timeline(
    session: Session,
    project: Project,
    *,
    thumbs_dir: Path | None = None,
    size: int = 256,
    suggest_places: bool = False,
    settings: AppSettings | None = None,
) -> TimelineSnapshot:
    """Create missing trip/days from media and note dates. Manual titles and notes stay."""

    ensure_photo_and_video_rows(session, project)
    media = _media_rows(session, project.id)
    texts = _text_rows(session, project.id)
    by_date = _group_by_date(media)
    texts_by_date = _group_texts_by_date(texts)
    trip = _ensure_trip(session, project)
    existing = _days_by_key(session, trip.id)
    ordered_keys = sorted(
        set(by_date) | set(texts_by_date),
        key=lambda item: (item is None, item or date.min),
    )
    kept_ids: set[int] = set()
    for index, key in enumerate(ordered_keys):
        day = existing.get(key)
        if day is None:
            day = TripDay(
                trip_id=trip.id,
                day_index=index,
                date=_date_as_datetime(key),
                title=_auto_title(key),
                origin=ORIGIN_AUTO,
            )
            session.add(day)
            session.flush()
        else:
            day.day_index = index
            if day.origin != ORIGIN_MANUAL and not (day.notes or "").strip():
                day.origin = ORIGIN_AUTO
        if day.origin != ORIGIN_MANUAL:
            _apply_text_prefill(day, key, texts_by_date.get(key, []))
        _ensure_auto_event(session, day, len(by_date.get(key, [])))
        kept_ids.add(day.id)
    _drop_empty_auto_days(session, trip.id, kept_ids)
    session.flush()
    trip_days = list(session.scalars(select(TripDay).where(TripDay.trip_id == trip.id)))
    titles = {calendar_key(day.date): day.title for day in trip_days}
    notes = {calendar_key(day.date): day.notes for day in trip_days}
    youtube = {calendar_key(day.date): day.youtube_urls for day in trip_days}
    leonardo = {calendar_key(day.date): day.leonardo_urls for day in trip_days}
    covers = {calendar_key(day.date): day.cover_source_file_id for day in trip_days}
    ensure_day_memberships(
        session,
        trip.id,
        [row for row, _photo in media],
        titles=titles,
        notes=notes,
        youtube=youtube,
        leonardo=leonardo,
        covers=covers,
    )
    _ensure_placeholder_day_sections(session, trip.id, trip_days)
    session.flush()
    if suggest_places:
        add_place_suggestions(session, project, settings=settings)
    session.flush()
    snapshot = load_timeline(session, project, thumbs_dir=thumbs_dir, size=size)
    if snapshot is None:
        raise RuntimeError("Timeline fehlt nach dem Abgleich.")
    return snapshot


def load_timeline(
    session: Session,
    project: Project,
    *,
    thumbs_dir: Path | None = None,
    size: int = 256,
) -> TimelineSnapshot | None:
    """Return the persisted timeline, or None if no trip exists yet."""

    trip = session.scalar(select(Trip).where(Trip.project_id == project.id).order_by(Trip.id.asc()))
    if trip is None:
        return None
    days = list(
        session.scalars(select(TripDay).where(TripDay.trip_id == trip.id).order_by(TripDay.day_index.asc()))
    )
    media = _media_rows(session, project.id)
    by_date = _group_by_date(media)
    track_urls = track_urls_by_source(session, project.id)
    snapshot_days: list[TimelineDay] = []
    for day in days:
        key = day.date.date() if day.date is not None else None
        day_media = by_date.get(key, [])
        snapshot_days.append(
            TimelineDay(
                id=day.id,
                day_index=day.day_index,
                date=key,
                title=day.title,
                notes=day.notes,
                origin=day.origin,
                youtube_urls=parse_youtube_urls(day.youtube_urls),
                leonardo_urls=parse_leonardo_urls(day.leonardo_urls),
                cover_source_file_id=day.cover_source_file_id,
                photos=tuple(
                    _photo_view(row, photo, thumbs_dir, size, track_urls.get(row.id))
                    for row, photo in day_media
                ),
                places=tuple(_place_view(item) for item in _places_for_day(session, day.id)),
                events=tuple(_event_view(item) for item in _events_for_day(session, day.id)),
            )
        )
    sections = _section_views(session, trip.id, thumbs_dir, size, track_urls)
    entries = _build_entries(sections)
    ordered_sections = tuple(entry.section for entry in entries if entry.section is not None)
    return TimelineSnapshot(
        trip_id=trip.id,
        title=trip.title,
        origin=trip.origin,
        days=tuple(snapshot_days),
        sections=ordered_sections,
        entries=tuple(entries),
    )


def add_place_suggestions(
    session: Session,
    project: Project,
    *,
    settings: AppSettings | None = None,
) -> int:
    """Add unconfirmed auto places for days that have GPS photos and no places yet."""

    cfg = settings or AppSettings()
    trip = session.scalar(select(Trip).where(Trip.project_id == project.id).order_by(Trip.id.asc()))
    if trip is None:
        return 0
    media = _media_rows(session, project.id)
    by_date = _group_by_date(media)
    added = 0
    days = session.scalars(select(TripDay).where(TripDay.trip_id == trip.id))
    for day in days:
        existing = _places_for_day(session, day.id)
        if existing:
            continue
        key = day.date.date() if day.date is not None else None
        points = [
            (float(row.gps_latitude), float(row.gps_longitude), row.captured_at)
            for row, _photo in by_date.get(key, [])
            if row.gps_latitude is not None and row.gps_longitude is not None
        ]
        if not points:
            continue
        for cluster in cluster_stays(points, radius_meters=cfg.stay_radius_meters, min_duration_minutes=0):
            session.add(
                Place(
                    day_id=day.id,
                    name=f"Vorschlag {cluster.latitude:.4f}, {cluster.longitude:.4f}",
                    latitude=cluster.latitude,
                    longitude=cluster.longitude,
                    radius_meters=cfg.stay_radius_meters,
                    arrived_at=cluster.started_at,
                    departed_at=cluster.ended_at,
                    confirmed=False,
                    origin=ORIGIN_AUTO,
                )
            )
            added += 1
    return added


def save_day_text(session: Session, day_id: int, *, title: str, notes: str) -> None:
    day = session.get(TripDay, day_id)
    if day is None:
        return
    day.title = title.strip() or day.title
    day.notes = notes
    day.origin = ORIGIN_MANUAL


def save_trip_title(session: Session, trip_id: int, title: str) -> None:
    trip = session.get(Trip, trip_id)
    if trip is None:
        return
    cleaned = title.strip()
    if not cleaned:
        return
    trip.title = cleaned
    trip.origin = ORIGIN_MANUAL


def save_day_youtube_urls(session: Session, day_id: int, urls: list[str]) -> None:
    day = session.get(TripDay, day_id)
    if day is None:
        return
    day.youtube_urls = serialize_youtube_urls(urls)
    day.origin = ORIGIN_MANUAL


def save_day_leonardo_urls(session: Session, day_id: int, urls: list[str]) -> None:
    day = session.get(TripDay, day_id)
    if day is None:
        return
    day.leonardo_urls = serialize_leonardo_urls(urls)
    day.origin = ORIGIN_MANUAL


def set_photo_journal_flag(session: Session, source_file_id: int, used: bool) -> None:
    photo = session.scalar(select(Photo).where(Photo.source_file_id == source_file_id))
    if photo is None:
        session.add(
            Photo(
                source_file_id=source_file_id,
                is_favorite=False,
                used_in_journal=used,
                is_cover=False,
                origin=ORIGIN_MANUAL,
            )
        )
        return
    photo.used_in_journal = used
    photo.origin = ORIGIN_MANUAL


def set_photo_sort_status(session: Session, source_file_id: int, status: str | None) -> None:
    normalized = status if status in SORT_STATUSES else None
    favorite = normalized == SORT_FAVORITE
    photo = session.scalar(select(Photo).where(Photo.source_file_id == source_file_id))
    if photo is None:
        session.add(
            Photo(
                source_file_id=source_file_id,
                is_favorite=favorite,
                used_in_journal=False,
                is_cover=False,
                sort_status=normalized,
                origin=ORIGIN_MANUAL,
            )
        )
        return
    photo.sort_status = normalized
    photo.is_favorite = favorite
    photo.origin = ORIGIN_MANUAL


def add_source_rotation(session: Session, source_file_id: int, delta_degrees: int) -> int:
    """Store a clockwise display rotation. Originals are not written."""

    row = session.get(SourceFile, source_file_id)
    if row is None:
        raise ProjectError("Datei nicht gefunden.")
    row.rotation_degrees = normalize_rotation_degrees(
        normalize_rotation_degrees(row.rotation_degrees) + delta_degrees
    )
    return row.rotation_degrees


def set_cover_photo(session: Session, project_id: int, source_file_id: int) -> None:
    photos = list(
        session.scalars(
            select(Photo)
            .join(SourceFile, Photo.source_file_id == SourceFile.id)
            .where(SourceFile.project_id == project_id)
        )
    )
    found = False
    for photo in photos:
        photo.is_cover = photo.source_file_id == source_file_id
        if photo.is_cover:
            photo.origin = ORIGIN_MANUAL
            photo.used_in_journal = True
            found = True
    if not found:
        session.add(
            Photo(
                source_file_id=source_file_id,
                is_favorite=False,
                used_in_journal=True,
                is_cover=True,
                origin=ORIGIN_MANUAL,
            )
        )


def set_entry_cover(session: Session, kind: str, entity_id: int, source_file_id: int | None) -> None:
    """Store one title image per section. Compact views come later."""

    if kind == "section":
        section = session.get(TripSection, entity_id)
        if section is None:
            return
        if source_file_id is not None and not _cover_in_section(session, entity_id, source_file_id):
            raise ProjectError("Titelbild muss ein Foto oder Track dieses Abschnitts sein.")
        section.cover_source_file_id = source_file_id
        section.origin = ORIGIN_MANUAL
        return
    day = session.get(TripDay, entity_id)
    if day is None:
        return
    if source_file_id is not None and not _cover_in_day(session, day, source_file_id):
        raise ProjectError("Titelbild muss ein Foto oder Track dieses Tages sein.")
    day.cover_source_file_id = source_file_id
    day.origin = ORIGIN_MANUAL


def _cover_in_section(session: Session, section_id: int, source_file_id: int) -> bool:
    row = session.get(SourceFile, source_file_id)
    if row is None or not _can_be_entry_cover(row):
        return False
    member = session.scalar(
        select(SectionMember.id).where(
            SectionMember.section_id == section_id,
            SectionMember.source_file_id == source_file_id,
        )
    )
    return member is not None


def _cover_in_day(session: Session, day: TripDay, source_file_id: int) -> bool:
    row = session.get(SourceFile, source_file_id)
    if row is None or not _can_be_entry_cover(row):
        return False
    day_key = day.date.date() if day.date is not None else None
    file_key = row.captured_at.date() if row.captured_at is not None else None
    return day_key == file_key


def _can_be_entry_cover(row: SourceFile) -> bool:
    return row.file_kind in (FileKind.PHOTO.value, FileKind.GPS.value)


def confirm_place(session: Session, place_id: int, name: str) -> None:
    place = session.get(Place, place_id)
    if place is None:
        return
    place.name = name.strip() or place.name
    place.confirmed = True
    place.origin = ORIGIN_MANUAL


def delete_place(session: Session, place_id: int) -> None:
    place = session.get(Place, place_id)
    if place is not None:
        session.delete(place)


def _text_rows(session: Session, project_id: int) -> list[SourceFile]:
    return list(
        session.scalars(
            select(SourceFile)
            .where(
                SourceFile.project_id == project_id,
                SourceFile.file_kind == FileKind.TEXT.value,
            )
            .order_by(SourceFile.captured_at.asc().nulls_last(), SourceFile.filename.asc())
        )
    )


def _group_texts_by_date(rows: list[SourceFile]) -> dict[date | None, list[SourceFile]]:
    grouped: dict[date | None, list[SourceFile]] = defaultdict(list)
    for row in rows:
        suffix = Path(row.filename).suffix.lower()
        if suffix not in JOURNAL_TEXT_SUFFIXES:
            continue
        key = date_from_text_filename(row.filename)
        if key is None and row.captured_at is not None:
            key = row.captured_at.date()
        grouped[key].append(row)
    return grouped


def _apply_text_prefill(day: TripDay, key: date | None, rows: list[SourceFile]) -> None:
    parts = [read_imported_text(Path(row.path)) for row in rows]
    title, notes = combine_imported_texts(parts)
    day.title = title or _auto_title(key)
    day.notes = notes


def _media_rows(session: Session, project_id: int) -> list[tuple[SourceFile, Photo | None]]:
    rows = session.execute(
        select(SourceFile, Photo)
        .outerjoin(Photo, Photo.source_file_id == SourceFile.id)
        .where(
            SourceFile.project_id == project_id,
            SourceFile.file_kind.in_((FileKind.PHOTO.value, FileKind.VIDEO.value, FileKind.GPS.value)),
        )
        .order_by(SourceFile.captured_at.asc().nulls_last(), SourceFile.filename.asc())
    )
    return list(rows)


def _group_by_date(
    media: list[tuple[SourceFile, Photo | None]],
) -> dict[date | None, list[tuple[SourceFile, Photo | None]]]:
    grouped: dict[date | None, list[tuple[SourceFile, Photo | None]]] = defaultdict(list)
    for row, photo in media:
        key = row.captured_at.date() if row.captured_at is not None else None
        grouped[key].append((row, photo))
    return grouped


def _ensure_trip(session: Session, project: Project) -> Trip:
    trip = session.scalar(select(Trip).where(Trip.project_id == project.id).order_by(Trip.id.asc()))
    if trip is None:
        trip = Trip(project_id=project.id, title=project.name, origin=ORIGIN_AUTO)
        session.add(trip)
        session.flush()
        return trip
    if trip.origin != ORIGIN_MANUAL:
        trip.title = project.name
    return trip


def _days_by_key(session: Session, trip_id: int) -> dict[date | None, TripDay]:
    days = session.scalars(select(TripDay).where(TripDay.trip_id == trip_id))
    result: dict[date | None, TripDay] = {}
    for day in days:
        key = day.date.date() if day.date is not None else None
        result[key] = day
    return result


def _date_as_datetime(value: date | None) -> datetime | None:
    if value is None:
        return None
    return datetime.combine(value, time.min, tzinfo=UTC)


def _auto_title(value: date | None) -> str:
    if value is None:
        return "Ohne Datum"
    return value.strftime("%d.%m.%Y")


def _ensure_placeholder_day_sections(session: Session, trip_id: int, days: list[TripDay]) -> None:
    """Keep a Tag section for calendar days that have text, places, or a manual origin."""

    for day in days:
        key = calendar_key(day.date)
        if day_section_for_date(session, trip_id, key, create=False) is not None:
            continue
        has_place = session.scalar(select(Place.id).where(Place.day_id == day.id).limit(1))
        if day.origin != ORIGIN_MANUAL and not (day.notes or "").strip() and has_place is None:
            continue
        section = day_section_for_date(session, trip_id, key, create=True)
        if section is None:
            continue
        if section.origin == ORIGIN_AUTO:
            section.title = day.title or section.title
            section.notes = day.notes
            section.youtube_urls = day.youtube_urls
            section.leonardo_urls = day.leonardo_urls
            section.cover_source_file_id = day.cover_source_file_id
            if day.origin == ORIGIN_MANUAL:
                section.origin = ORIGIN_MANUAL
    session.flush()


def _ensure_auto_event(session: Session, day: TripDay, photo_count: int) -> None:
    events = list(
        session.scalars(select(Event).where(Event.day_id == day.id).order_by(Event.sort_index.asc()))
    )
    auto = next((item for item in events if item.origin == ORIGIN_AUTO), None)
    title = f"{photo_count} Medien" if photo_count else "Tag"
    if auto is None:
        session.add(
            Event(
                day_id=day.id,
                title=title,
                occurred_at=day.date,
                sort_index=0,
                origin=ORIGIN_AUTO,
            )
        )
        return
    auto.title = title
    auto.occurred_at = day.date


def _drop_empty_auto_days(session: Session, trip_id: int, keep_ids: set[int]) -> None:
    days = list(session.scalars(select(TripDay).where(TripDay.trip_id == trip_id)))
    for day in days:
        if day.id in keep_ids:
            continue
        if day.origin == ORIGIN_MANUAL or (day.notes or "").strip():
            continue
        places = _places_for_day(session, day.id)
        if places:
            continue
        for event in _events_for_day(session, day.id):
            session.delete(event)
        session.delete(day)


def _places_for_day(session: Session, day_id: int) -> list[Place]:
    return list(session.scalars(select(Place).where(Place.day_id == day_id).order_by(Place.id.asc())))


def _events_for_day(session: Session, day_id: int) -> list[Event]:
    return list(
        session.scalars(
            select(Event).where(Event.day_id == day_id).order_by(Event.sort_index.asc(), Event.id.asc())
        )
    )


def _photo_view(
    row: SourceFile,
    photo: Photo | None,
    thumbs_dir: Path | None,
    size: int,
    external_url: str | None = None,
    *,
    journal_at: datetime | None = None,
    journal_timezone_name: str | None = None,
    display_latitude: float | None = None,
    display_longitude: float | None = None,
    position_inherited: bool = False,
) -> TimelinePhoto:
    folder = thumbs_dir if thumbs_dir is not None else Path(".")
    rotation = normalize_rotation_degrees(row.rotation_degrees)
    thumb = cached_thumbnail_path(
        folder,
        source_file_id=row.id,
        sha256=row.sha256,
        size=size,
        rotation_degrees=rotation,
    )
    return TimelinePhoto(
        source_file_id=row.id,
        filename=row.filename,
        path=row.path,
        thumbnail_path=thumb,
        captured_at=row.captured_at,
        used_in_journal=bool(photo.used_in_journal) if photo is not None else False,
        is_cover=bool(photo.is_cover) if photo is not None else False,
        is_favorite=bool(photo.is_favorite) if photo is not None else False,
        gps_latitude=row.gps_latitude,
        gps_longitude=row.gps_longitude,
        file_kind=row.file_kind,
        external_url=external_url,
        sort_status=effective_sort_status(
            photo.sort_status if photo is not None else None,
            bool(photo.is_favorite) if photo is not None else False,
        ),
        rotation_degrees=rotation,
        journal_at=journal_at,
        journal_timezone_name=journal_timezone_name,
        display_latitude=display_latitude if display_latitude is not None else row.gps_latitude,
        display_longitude=display_longitude if display_longitude is not None else row.gps_longitude,
        position_inherited=position_inherited,
    )


def _section_views(
    session: Session,
    trip_id: int,
    thumbs_dir: Path | None,
    size: int,
    track_urls: dict[int, str],
) -> list[TimelineSection]:
    sections = list(
        session.scalars(
            select(TripSection)
            .where(TripSection.trip_id == trip_id)
            .order_by(TripSection.started_at.asc().nulls_last(), TripSection.id.asc())
        )
    )
    links_by_section = load_transfer_links_for_sections(session, [section.id for section in sections])
    views: list[TimelineSection] = []
    for section in sections:
        members = list(
            session.execute(
                select(SourceFile, Photo, SectionMember)
                .join(SectionMember, SectionMember.source_file_id == SourceFile.id)
                .outerjoin(Photo, Photo.source_file_id == SourceFile.id)
                .where(SectionMember.section_id == section.id)
                .order_by(SectionMember.sort_index.asc(), SourceFile.filename.asc())
            )
        )
        files = [row for row, _photo, _member in members]
        members.sort(key=_member_display_sort_key)
        items = []
        for row, photo, member in members:
            position, inherited = display_position(session, row, member, section, files)
            items.append(
                _photo_view(
                    row,
                    photo,
                    thumbs_dir,
                    size,
                    track_urls.get(row.id),
                    journal_at=member.journal_at,
                    journal_timezone_name=member.journal_timezone_name,
                    display_latitude=position[0] if position is not None else None,
                    display_longitude=position[1] if position is not None else None,
                    position_inherited=inherited,
                )
            )
        views.append(
            TimelineSection(
                id=section.id,
                kind=section.kind,
                mode=section.mode,
                title=section.title,
                notes=section.notes,
                started_at=section.started_at,
                ended_at=section.ended_at,
                location_name=section.location_name,
                location_from=section.location_from,
                location_to=section.location_to,
                origin=section.origin,
                youtube_urls=parse_youtube_urls(section.youtube_urls),
                leonardo_urls=parse_leonardo_urls(section.leonardo_urls),
                cover_source_file_id=section.cover_source_file_id,
                pin_latitude=section.pin_latitude,
                pin_longitude=section.pin_longitude,
                items=tuple(items),
                links=links_by_section.get(section.id, ()),
            )
        )
    return views


def apply_pending_sections(
    snapshot: TimelineSnapshot,
    pending: list[PendingSectionSpec],
) -> TimelineSnapshot:
    """Preview unsaved sections on a loaded snapshot without writing the database."""

    if not pending:
        return snapshot
    photos: dict[int, TimelinePhoto] = {}
    for day in snapshot.days:
        for photo in day.photos:
            photos[photo.source_file_id] = photo
    for section in snapshot.sections:
        for item in section.items:
            photos[item.source_file_id] = item
    extra: list[TimelineSection] = []
    pending_ids = {item_id for spec in pending for item_id in spec.source_file_ids}
    trimmed: list[TimelineSection] = []
    for section in snapshot.sections:
        items = tuple(item for item in section.items if item.source_file_id not in pending_ids)
        if (
            not items
            and section.kind == KIND_DAY
            and section.origin == "auto"
            and not (section.notes or "").strip()
        ):
            continue
        trimmed.append(replace(section, items=items))
    for spec in pending:
        items = tuple(photos[item_id] for item_id in spec.source_file_ids if item_id in photos)
        if items:
            times = [
                item.journal_at or item.captured_at
                for item in items
                if item.journal_at or item.captured_at
            ]
            started_at = min(times) if times else spec.started_at
            ended_at = max(times) if times else spec.ended_at
        elif spec.started_at is None:
            continue
        else:
            started_at = spec.started_at
            ended_at = spec.ended_at or spec.started_at
        extra.append(
            TimelineSection(
                id=spec.local_id,
                kind=spec.kind,
                mode=spec.mode,
                title=spec.title,
                notes=spec.notes,
                started_at=started_at,
                ended_at=ended_at,
                location_name=spec.location_name,
                location_from=spec.location_from,
                location_to=spec.location_to,
                origin="manual",
                youtube_urls=spec.youtube_urls,
                leonardo_urls=spec.leonardo_urls,
                cover_source_file_id=spec.cover_source_file_id,
                items=items,
                links=spec.links,
            )
        )
    sections = tuple(trimmed) + tuple(extra)
    entries = _build_entries(list(sections))
    ordered_sections = tuple(entry.section for entry in entries if entry.section is not None)
    return replace(snapshot, sections=ordered_sections, entries=tuple(entries))


def _build_entries(sections: list[TimelineSection]) -> list[TimelineEntry]:
    entries: list[TimelineEntry] = [
        TimelineEntry(started_at=section.started_at, section=section) for section in sections
    ]
    entries.sort(key=_entry_sort_key)
    return entries


def _entry_moment(entry: TimelineEntry) -> datetime | None:
    if entry.section is not None:
        times = [
            aware(item.journal_at or item.captured_at)
            for item in entry.section.items
            if item.journal_at or item.captured_at
        ]
        timed = [item for item in times if item is not None]
        if timed:
            return min(timed)
        return aware(entry.section.started_at)
    return aware(entry.started_at)


def _entry_sort_key(entry: TimelineEntry) -> tuple[int, date, datetime, int, int]:
    """Chronological feed: calendar day, then clock, then Tag before Stay/Transfer."""

    moment = _entry_moment(entry)
    if moment is None:
        return (1, date.max, datetime.max.replace(tzinfo=UTC), 9, 0)
    kind = entry.card_kind
    if kind == KIND_DAY:
        kind_order = 0
    elif kind == KIND_STAY:
        kind_order = 1
    elif kind == KIND_MOVEMENT:
        kind_order = 2
    else:
        kind_order = 3
    section_id = entry.section.id if entry.section is not None else 0
    return (0, calendar_key(moment) or date.max, moment, kind_order, section_id)


def _member_display_sort_key(
    row: tuple[SourceFile, Photo | None, SectionMember],
) -> tuple[int, datetime, str]:
    source, _photo, member = row
    moment = aware(member.journal_at or source.captured_at)
    if moment is None:
        return (1, datetime.max.replace(tzinfo=UTC), source.filename)
    return (0, moment, source.filename)


def _place_view(item: Place) -> TimelinePlace:
    return TimelinePlace(
        id=item.id,
        name=item.name,
        latitude=item.latitude,
        longitude=item.longitude,
        confirmed=item.confirmed,
        origin=item.origin,
    )


def _event_view(item: Event) -> TimelineEvent:
    return TimelineEvent(
        id=item.id,
        title=item.title,
        occurred_at=item.occurred_at,
        origin=item.origin,
    )
