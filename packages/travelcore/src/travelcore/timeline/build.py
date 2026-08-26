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
    OvernightStay,
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
from travelcore.timeline.links import (
    parse_leonardo_urls,
    parse_youtube_urls,
    serialize_leonardo_urls,
    serialize_youtube_urls,
)
from travelcore.timeline.sections import claimed_source_ids
from travelcore.timeline.texts import (
    JOURNAL_TEXT_SUFFIXES,
    combine_imported_texts,
    date_from_text_filename,
    read_imported_text,
)
from travelcore.timeline.types import (
    PendingSectionSpec,
    TimelineDay,
    TimelineEntry,
    TimelineEvent,
    TimelinePhoto,
    TimelinePlace,
    TimelineSection,
    TimelineSnapshot,
    TimelineStay,
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
                stays=tuple(_stay_view(item) for item in _stays_for_day(session, day.id)),
                events=tuple(_event_view(item) for item in _events_for_day(session, day.id)),
            )
        )
    claimed = claimed_source_ids(session, trip.id)
    sections = _section_views(session, trip.id, thumbs_dir, size, track_urls)
    entries = _build_entries(snapshot_days, sections, claimed)
    return TimelineSnapshot(
        trip_id=trip.id,
        title=trip.title,
        origin=trip.origin,
        days=tuple(snapshot_days),
        sections=tuple(sections),
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


def set_entry_cover(
    session: Session, kind: str, entity_id: int, source_file_id: int | None
) -> None:
    """Store one title image per leftover day or section. Compact views come later."""

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


def add_overnight_stay(
    session: Session,
    day_id: int,
    *,
    name: str,
    location_name: str | None,
    latitude: float | None,
    longitude: float | None,
    description: str | None,
) -> OvernightStay:
    day = session.get(TripDay, day_id)
    stay = OvernightStay(
        day_id=day_id,
        name=name.strip() or "Übernachtung",
        location_name=location_name.strip() if location_name else None,
        stayed_on=day.date if day is not None else None,
        latitude=latitude,
        longitude=longitude,
        description=description.strip() if description else None,
        origin=ORIGIN_MANUAL,
    )
    session.add(stay)
    session.flush()
    return stay


def delete_overnight_stay(session: Session, stay_id: int) -> None:
    stay = session.get(OvernightStay, stay_id)
    if stay is not None:
        session.delete(stay)


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
        stays = _stays_for_day(session, day.id)
        if places or stays:
            continue
        for event in _events_for_day(session, day.id):
            session.delete(event)
        session.delete(day)


def _places_for_day(session: Session, day_id: int) -> list[Place]:
    return list(session.scalars(select(Place).where(Place.day_id == day_id).order_by(Place.id.asc())))


def _stays_for_day(session: Session, day_id: int) -> list[OvernightStay]:
    return list(
        session.scalars(
            select(OvernightStay).where(OvernightStay.day_id == day_id).order_by(OvernightStay.id.asc())
        )
    )


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
                items=tuple(
                    _photo_view(row, photo, thumbs_dir, size, track_urls.get(row.id))
                    for row, photo, _member in members
                ),
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
    claimed = {item.source_file_id for section in snapshot.sections for item in section.items}
    for spec in pending:
        items = tuple(photos[item_id] for item_id in spec.source_file_ids if item_id in photos)
        if not items:
            continue
        times = [item.captured_at for item in items if item.captured_at is not None]
        extra.append(
            TimelineSection(
                id=spec.local_id,
                kind=spec.kind,
                mode=spec.mode,
                title=spec.title,
                notes=spec.notes,
                started_at=min(times) if times else None,
                ended_at=max(times) if times else None,
                location_name=spec.location_name,
                location_from=spec.location_from,
                location_to=spec.location_to,
                origin="manual",
                youtube_urls=spec.youtube_urls,
                leonardo_urls=spec.leonardo_urls,
                cover_source_file_id=spec.cover_source_file_id,
                items=items,
            )
        )
        claimed.update(item.source_file_id for item in items)
    sections = snapshot.sections + tuple(extra)
    entries = _build_entries(list(snapshot.days), list(sections), claimed)
    return replace(snapshot, sections=sections, entries=tuple(entries))


def _build_entries(
    days: list[TimelineDay],
    sections: list[TimelineSection],
    claimed: set[int],
) -> list[TimelineEntry]:
    entries: list[TimelineEntry] = [
        TimelineEntry(started_at=section.started_at, section=section) for section in sections
    ]
    for day in days:
        leftover = tuple(item for item in day.photos if item.source_file_id not in claimed)
        notes_only = not day.photos and bool((day.notes or "").strip() or day.origin == ORIGIN_MANUAL)
        if not leftover and not notes_only:
            continue
        shown = replace(day, photos=leftover)
        entries.append(TimelineEntry(started_at=_leftover_started_at(shown), leftover_day=shown))
    entries.sort(key=_entry_sort_key)
    return entries


def _leftover_started_at(day: TimelineDay) -> datetime | None:
    times = [item.captured_at for item in day.photos if item.captured_at is not None]
    if times:
        return min(times)
    if day.date is None:
        return None
    return datetime.combine(day.date, time.min, tzinfo=UTC)


def _entry_sort_key(entry: TimelineEntry) -> tuple[int, datetime, int]:
    moment = entry.started_at
    if moment is None:
        return (1, datetime.min.replace(tzinfo=UTC), 0)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    kind_order = 0 if entry.leftover_day is not None else 1
    return (0, moment, kind_order)


def _place_view(item: Place) -> TimelinePlace:
    return TimelinePlace(
        id=item.id,
        name=item.name,
        latitude=item.latitude,
        longitude=item.longitude,
        confirmed=item.confirmed,
        origin=item.origin,
    )


def _stay_view(item: OvernightStay) -> TimelineStay:
    return TimelineStay(
        id=item.id,
        name=item.name,
        location_name=item.location_name,
        stayed_on=item.stayed_on,
        latitude=item.latitude,
        longitude=item.longitude,
        description=item.description,
        origin=item.origin,
    )


def _event_view(item: Event) -> TimelineEvent:
    return TimelineEvent(
        id=item.id,
        title=item.title,
        occurred_at=item.occurred_at,
        origin=item.origin,
    )
