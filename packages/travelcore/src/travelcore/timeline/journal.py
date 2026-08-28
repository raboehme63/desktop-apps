"""Journal clock and inherited map position on section membership.

Original capture time and GPS on SourceFile stay untouched. Timeline order,
Tag membership and display coordinates use the journal overlay.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime, time
from math import cos, pi, radians, sin, sqrt

from sqlalchemy import select
from sqlalchemy.orm import Session

from travelcore.database.models import (
    GpsPoint,
    GpsTrack,
    Place,
    SectionMember,
    SourceFile,
    TripDay,
    TripSection,
)
from travelcore.gps.types import TrackPoint
from travelcore.media.types import FileKind

KIND_DAY = "day"
KIND_STAY = "stay"
KIND_MOVEMENT = "movement"


def aware(moment: datetime | None) -> datetime | None:
    if moment is None:
        return None
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment


def calendar_key(moment: datetime | None) -> date | None:
    stamp = aware(moment)
    if stamp is None:
        return None
    return stamp.date()


def init_journal_clock(
    source: SourceFile,
    section: TripSection | None = None,
) -> tuple[datetime | None, str | None]:
    """Copy original capture time, or the section clock when the file has none."""

    if source.captured_at is not None:
        return aware(source.captured_at), source.timezone_name
    if section is None:
        return None, None
    if section.kind == KIND_DAY:
        key = calendar_key(section.started_at)
        if key is None:
            return None, None
        return datetime.combine(key, time(12, 0), tzinfo=UTC), source.timezone_name
    return aware(section.started_at), source.timezone_name


def snap_clock_to_date(moment: datetime | None, key: date | None) -> datetime | None:
    """Keep the clock, replace the calendar day. Noon UTC when there is no time."""

    if key is None:
        return aware(moment)
    stamp = aware(moment)
    if stamp is None:
        return datetime.combine(key, time(12, 0), tzinfo=UTC)
    return stamp.replace(year=key.year, month=key.month, day=key.day)


def original_position(source: SourceFile) -> tuple[float, float] | None:
    if source.gps_latitude is None or source.gps_longitude is None:
        return None
    return (float(source.gps_latitude), float(source.gps_longitude))


def files_cover_anchor(
    files: Iterable[SourceFile],
    cover_id: int | None,
) -> tuple[float, float] | None:
    rows = list(files)
    by_id = {row.id: row for row in rows}
    if cover_id is not None and cover_id in by_id:
        chosen = original_position(by_id[cover_id])
        if chosen is not None:
            return chosen
    for row in rows:
        if row.file_kind == FileKind.PHOTO.value:
            chosen = original_position(row)
            if chosen is not None:
                return chosen
    for row in rows:
        if row.file_kind == FileKind.GPS.value:
            chosen = original_position(row)
            if chosen is not None:
                return chosen
    coords = [item for item in (original_position(row) for row in rows) if item is not None]
    if not coords:
        return None
    lat = sum(item[0] for item in coords) / len(coords)
    lon = sum(item[1] for item in coords) / len(coords)
    return (lat, lon)


_METERS_PER_DEG = 111_320.0
_SCATTER_M = 12.0
_GOLDEN_ANGLE = pi * (3.0 - 5.0**0.5)


def offset_meters(lat: float, lon: float, east_m: float, north_m: float) -> tuple[float, float]:
    dlat = north_m / _METERS_PER_DEG
    denom = _METERS_PER_DEG * cos(radians(lat))
    dlon = east_m / denom if abs(denom) > 1e-9 else 0.0
    return (lat + dlat, lon + dlon)


def scattered_positions(
    anchor: tuple[float, float],
    count: int,
    *,
    radius_m: float = _SCATTER_M,
) -> list[tuple[float, float]]:
    """Spread ``count`` points around ``anchor`` so map markers do not coincide."""

    if count <= 0:
        return []
    if count == 1:
        return [anchor]
    lat, lon = anchor
    points: list[tuple[float, float]] = []
    for index in range(count):
        dist = radius_m * sqrt(index + 1)
        angle = index * _GOLDEN_ANGLE
        points.append(offset_meters(lat, lon, dist * sin(angle), dist * cos(angle)))
    return points


def snapshot_tag_position(
    source: SourceFile,
    files: Iterable[SourceFile],
    cover_id: int | None,
) -> tuple[float | None, float | None]:
    if original_position(source) is not None:
        return None, None
    anchor = files_cover_anchor(files, cover_id)
    if anchor is None:
        return None, None
    return anchor


def stay_live_anchor(
    session: Session,
    section: TripSection,
    files: Iterable[SourceFile],
) -> tuple[float, float] | None:
    place = _stay_place(session, section)
    if place is not None and place.latitude is not None and place.longitude is not None:
        return (float(place.latitude), float(place.longitude))
    return files_cover_anchor(files, section.cover_source_file_id)


def transfer_position_at(
    session: Session,
    source_file_ids: Iterable[int],
    moment: datetime | None,
) -> tuple[float, float] | None:
    if moment is None:
        return None
    ids = [item for item in source_file_ids if item is not None]
    if not ids:
        return None
    points = _track_points_for_sources(session, ids)
    return position_on_track(moment, points)


def position_on_track(moment: datetime, points: list[TrackPoint]) -> tuple[float, float] | None:
    timed = sorted(
        (point for point in points if point.recorded_at is not None),
        key=lambda item: aware(item.recorded_at) or datetime.min.replace(tzinfo=UTC),
    )
    if not timed:
        return None
    stamp = aware(moment)
    if stamp is None:
        return None
    stamp = stamp.astimezone(UTC)
    first = aware(timed[0].recorded_at)
    last = aware(timed[-1].recorded_at)
    if first is None or last is None:
        return None
    first = first.astimezone(UTC)
    last = last.astimezone(UTC)
    if stamp < first or stamp > last:
        return None
    previous = timed[0]
    following = timed[-1]
    for point in timed:
        recorded = aware(point.recorded_at)
        if recorded is None:
            continue
        recorded = recorded.astimezone(UTC)
        if recorded <= stamp:
            previous = point
        if recorded >= stamp:
            following = point
            break
    start = aware(previous.recorded_at)
    end = aware(following.recorded_at)
    if start is None or end is None:
        return (previous.latitude, previous.longitude)
    start = start.astimezone(UTC)
    end = end.astimezone(UTC)
    span = (end - start).total_seconds()
    if span <= 0:
        return (previous.latitude, previous.longitude)
    fraction = (stamp - start).total_seconds() / span
    fraction = max(0.0, min(1.0, fraction))
    lat = previous.latitude + fraction * (following.latitude - previous.latitude)
    lon = _lerp_longitude(previous.longitude, following.longitude, fraction)
    return (lat, lon)


def section_map_anchor(
    session: Session,
    section: TripSection,
    files: Iterable[SourceFile],
    *,
    ignore_source_ids: set[int] | None = None,
) -> tuple[float, float] | None:
    """Map position of a section, ignoring originals of ``ignore_source_ids``."""

    ignored = ignore_source_ids or set()
    usable = [row for row in files if row.id not in ignored]
    cover_id = section.cover_source_file_id
    if cover_id in ignored:
        cover_id = None
    if section.kind == KIND_STAY:
        return stay_live_anchor(session, section, usable)
    if section.kind == KIND_MOVEMENT:
        track_ids = [
            row.id
            for row in files
            if row.id is not None and row.file_kind == FileKind.GPS.value and row.id not in ignored
        ]
        anchor = transfer_position_at(session, track_ids, section.started_at)
        if anchor is not None:
            return anchor
        return files_cover_anchor(usable, cover_id)
    return files_cover_anchor(usable, cover_id)


def display_position(
    session: Session,
    source: SourceFile,
    member: SectionMember,
    section: TripSection,
    files: Iterable[SourceFile],
) -> tuple[tuple[float, float] | None, bool]:
    """Journal overlay if set; otherwise original GPS; otherwise live section inherit."""

    if member.journal_latitude is not None and member.journal_longitude is not None:
        return (float(member.journal_latitude), float(member.journal_longitude)), True
    original = original_position(source)
    if original is not None:
        return original, False
    rows = list(files)
    if section.kind == KIND_STAY:
        anchor = stay_live_anchor(session, section, rows)
        return anchor, anchor is not None
    if section.kind == KIND_MOVEMENT:
        ids = [row.id for row in rows if row.id is not None]
        anchor = transfer_position_at(session, ids, member.journal_at)
        return anchor, anchor is not None
    fallback = files_cover_anchor(rows, section.cover_source_file_id)
    return fallback, fallback is not None


def display_positions_for_ids(
    session: Session,
    source_ids: Iterable[int],
) -> dict[int, tuple[float, float, bool]]:
    ids = list(dict.fromkeys(source_ids))
    if not ids:
        return {}
    members = list(
        session.execute(
            select(SectionMember, SourceFile, TripSection)
            .join(SourceFile, SourceFile.id == SectionMember.source_file_id)
            .join(TripSection, TripSection.id == SectionMember.section_id)
            .where(SectionMember.source_file_id.in_(ids))
        )
    )
    by_section: dict[int, list[tuple[SectionMember, SourceFile, TripSection]]] = {}
    for member, source, section in members:
        by_section.setdefault(section.id, []).append((member, source, section))
    result: dict[int, tuple[float, float, bool]] = {}
    for rows in by_section.values():
        files = [source for _member, source, _section in rows]
        section = rows[0][2]
        extra = _section_files(session, section.id, already={row.id for row in files if row.id is not None})
        all_files = files + extra
        for member, source, _section in rows:
            if source.id is None:
                continue
            position, inherited = display_position(session, source, member, section, all_files)
            if position is None:
                continue
            result[source.id] = (position[0], position[1], inherited)
    missing = [item for item in ids if item not in result]
    if missing:
        leftovers = list(session.scalars(select(SourceFile).where(SourceFile.id.in_(missing))))
        for source in leftovers:
            original = original_position(source)
            if original is None or source.id is None:
                continue
            result[source.id] = (original[0], original[1], False)
    return result


def _section_files(session: Session, section_id: int, already: set[int]) -> list[SourceFile]:
    rows = list(
        session.scalars(
            select(SourceFile)
            .join(SectionMember, SectionMember.source_file_id == SourceFile.id)
            .where(SectionMember.section_id == section_id)
        )
    )
    return [row for row in rows if row.id not in already]


def _stay_place(session: Session, section: TripSection) -> Place | None:
    start = calendar_key(section.started_at)
    end = calendar_key(section.ended_at if section.ended_at is not None else section.started_at)
    days = list(session.scalars(select(TripDay).where(TripDay.trip_id == section.trip_id)))
    day_ids: list[int] = []
    for day in days:
        if day.id is None:
            continue
        key = calendar_key(day.date)
        if key is None:
            continue
        if start is not None and end is not None:
            if start <= key <= end:
                day_ids.append(day.id)
        elif key == start:
            day_ids.append(day.id)
    if not day_ids:
        return None
    places = list(
        session.scalars(
            select(Place).where(
                Place.day_id.in_(day_ids),
                Place.latitude.is_not(None),
                Place.longitude.is_not(None),
            )
        )
    )
    confirmed = [item for item in places if item.confirmed]
    ordered = confirmed or places
    return ordered[0] if ordered else None


def _track_points_for_sources(session: Session, source_ids: list[int]) -> list[TrackPoint]:
    tracks = list(session.scalars(select(GpsTrack).where(GpsTrack.source_file_id.in_(source_ids))))
    if not tracks:
        return []
    track_ids = [track.id for track in tracks if track.id is not None]
    if not track_ids:
        return []
    rows = list(
        session.scalars(
            select(GpsPoint)
            .where(GpsPoint.track_id.in_(track_ids))
            .order_by(GpsPoint.track_id.asc(), GpsPoint.sequence_index.asc())
        )
    )
    points: list[TrackPoint] = []
    for point in rows:
        points.append(
            TrackPoint(
                latitude=point.latitude,
                longitude=point.longitude,
                altitude=point.altitude,
                recorded_at=point.recorded_at,
                track_id=str(point.track_id),
                segment_id=point.segment_id,
                sequence_index=point.sequence_index,
            )
        )
    return points


def _lerp_longitude(start: float, end: float, fraction: float) -> float:
    delta = end - start
    if delta > 180.0:
        delta -= 360.0
    elif delta < -180.0:
        delta += 360.0
    return ((start + fraction * delta + 180.0) % 360.0) - 180.0
