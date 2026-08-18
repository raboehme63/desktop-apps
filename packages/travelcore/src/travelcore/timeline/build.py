"""Build and update the trip timeline. Manual rows are never overwritten."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, time
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from travelcore.config import AppSettings
from travelcore.database.models import Event, OvernightStay, Photo, Place, Project, SourceFile, Trip, TripDay
from travelcore.geolocation.stays import cluster_stays
from travelcore.media.thumbnails import cached_thumbnail_path, ensure_photo_and_video_rows
from travelcore.media.types import FileKind
from travelcore.timeline.types import (
    TimelineDay,
    TimelineEvent,
    TimelinePhoto,
    TimelinePlace,
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
    suggest_places: bool = True,
    settings: AppSettings | None = None,
) -> TimelineSnapshot:
    """Create missing trip/days from media dates. Manual titles and notes stay."""

    ensure_photo_and_video_rows(session, project)
    media = _media_rows(session, project.id)
    by_date = _group_by_date(media)
    trip = _ensure_trip(session, project)
    existing = _days_by_key(session, trip.id)
    ordered_keys = sorted(by_date.keys(), key=lambda item: (item is None, item or date.min))
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
            if day.origin != ORIGIN_MANUAL:
                day.title = _auto_title(key)
                if not day.notes:
                    day.origin = ORIGIN_AUTO
        _ensure_auto_event(session, day, len(by_date[key]))
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
                photos=tuple(_photo_view(row, photo, thumbs_dir, size) for row, photo in day_media),
                places=tuple(_place_view(item) for item in _places_for_day(session, day.id)),
                stays=tuple(_stay_view(item) for item in _stays_for_day(session, day.id)),
                events=tuple(_event_view(item) for item in _events_for_day(session, day.id)),
            )
        )
    return TimelineSnapshot(trip_id=trip.id, title=trip.title, origin=trip.origin, days=tuple(snapshot_days))


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


def _media_rows(session: Session, project_id: int) -> list[tuple[SourceFile, Photo | None]]:
    rows = session.execute(
        select(SourceFile, Photo)
        .outerjoin(Photo, Photo.source_file_id == SourceFile.id)
        .where(
            SourceFile.project_id == project_id,
            SourceFile.file_kind.in_((FileKind.PHOTO.value, FileKind.VIDEO.value)),
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
) -> TimelinePhoto:
    folder = thumbs_dir if thumbs_dir is not None else Path(".")
    thumb = cached_thumbnail_path(
        folder,
        source_file_id=row.id,
        sha256=row.sha256,
        size=size,
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
    )


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
