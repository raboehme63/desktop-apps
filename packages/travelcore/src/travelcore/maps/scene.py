"""Map scene assembled from the project index. Originals are never written."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from math import atan, ceil, degrees
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from travelcore.database.models import (
    GpsPoint,
    GpsTrack,
    Photo,
    Place,
    SectionMember,
    SourceFile,
    Trip,
    TripDay,
)
from travelcore.media.gallery import SORT_REJECTED, effective_sort_status
from travelcore.media.orientation import normalize_rotation_degrees
from travelcore.media.thumbnails import cached_thumbnail_path
from travelcore.media.types import FileKind
from travelcore.timeline.journal import aware, calendar_key

MAX_TRACK_DISPLAY_POINTS = 2500
MAX_FLIGHT_DISPLAY_POINTS = 1200
FLIGHT_LINE_MIN_ZOOM = 10
PHOTO_STACK_DISABLE_ZOOM = 17
PHOTO_CONE_MIN_ZOOM = 17
DEFAULT_PHOTO_FOV_DEGREES = 63.0
COVER_ICON_PX = 54
COVER_LINE_INSET_PX = 23
STAY_LINK_STYLE_STRAIGHT = "straight"
STAY_LINK_STYLE_CURVE = "curve"
STAY_LINK_STYLE_TRACK = "track"
_DAY_COLORS = (
    "blue",
    "green",
    "purple",
    "orange",
    "darkred",
    "cadetblue",
    "darkpurple",
    "pink",
)


@dataclass(frozen=True, slots=True)
class MapMarker:
    latitude: float
    longitude: float
    label: str
    kind: str
    preview_path: Path | None = None
    day_key: str | None = None
    color: str = "blue"
    subtitle: str | None = None
    group_key: str | None = None
    source_file_id: int | None = None
    sort_status: str | None = None
    heading_degrees: float | None = None
    fov_degrees: float | None = None


@dataclass(frozen=True, slots=True)
class MapPolyline:
    name: str
    points: tuple[tuple[float, float], ...]
    kind: str = "track"
    color: str = "#2eb8a0"
    min_zoom: int = 0
    pilot: str | None = None
    external_url: str | None = None
    source_file_id: int | None = None
    sort_status: str | None = None


@dataclass(frozen=True, slots=True)
class StayLink:
    """Overview connection between two consecutive stay covers."""

    start: tuple[float, float]
    end: tuple[float, float]
    start_key: str
    end_key: str
    style: str = STAY_LINK_STYLE_STRAIGHT
    via_transfer: bool = False


@dataclass(frozen=True, slots=True)
class MapScene:
    markers: tuple[MapMarker, ...] = ()
    polylines: tuple[MapPolyline, ...] = ()
    stay_links: tuple[StayLink, ...] = ()
    center: tuple[float, float] | None = None

    @property
    def empty(self) -> bool:
        return not self.markers and not self.polylines and self.center is None


def stay_link_visible(pixel_distance: float, *, cover_px: float = COVER_ICON_PX) -> bool:
    """Hide the line when stay circles overlap or touch at the current zoom."""

    return pixel_distance > cover_px


def downsample_points(
    points: list[tuple[float, float]],
    *,
    max_points: int = MAX_TRACK_DISPLAY_POINTS,
) -> list[tuple[float, float]]:
    """Keep start and end, stride the rest so Leaflet stays responsive."""

    if max_points < 2 or len(points) <= max_points:
        return list(points)
    step = max(1, ceil(len(points) / max_points))
    sampled = list(points[::step])
    if sampled[-1] != points[-1]:
        sampled.append(points[-1])
    return sampled


def build_map_scene(
    session: Session,
    project_id: int,
    thumbs_dir: Path,
    *,
    size: int = 256,
) -> MapScene:
    """Overview: one cover per Tag, Aufenthalt or Transfer."""

    from travelcore.maps.groups import build_map_overview

    return build_map_overview(session, project_id, thumbs_dir, size=size)


def track_polylines(
    session: Session,
    project_id: int,
    *,
    source_file_ids: set[int] | None = None,
) -> list[MapPolyline]:
    query = (
        select(GpsPoint, GpsTrack)
        .join(GpsTrack, GpsPoint.track_id == GpsTrack.id)
        .where(GpsTrack.project_id == project_id)
        .order_by(GpsTrack.id.asc(), GpsPoint.segment_id.asc(), GpsPoint.sequence_index.asc())
    )
    if source_file_ids is not None:
        if not source_file_ids:
            return []
        query = query.where(GpsTrack.source_file_id.in_(source_file_ids))
    rows = session.execute(query)
    grouped: dict[tuple[int, int], list[tuple[float, float]]] = defaultdict(list)
    meta: dict[int, GpsTrack] = {}
    started: dict[int, datetime] = {}
    for point, track in rows:
        key = (track.id, point.segment_id)
        grouped[key].append((point.latitude, point.longitude))
        meta[track.id] = track
        if point.recorded_at is not None:
            current = started.get(track.id)
            if current is None or point.recorded_at < current:
                started[track.id] = point.recorded_at
    statuses = _sort_status_map(
        session, {track.source_file_id for track in meta.values() if track.source_file_id}
    )
    lines: list[MapPolyline] = []
    for key, coords in grouped.items():
        track = meta[key[0]]
        status = statuses.get(track.source_file_id) if track.source_file_id else None
        if status == SORT_REJECTED:
            continue
        is_flight = track.track_format == "igc"
        sampled = downsample_points(
            coords,
            max_points=MAX_FLIGHT_DISPLAY_POINTS if is_flight else MAX_TRACK_DISPLAY_POINTS,
        )
        if len(sampled) < 2:
            continue
        label = _day_key(started.get(track.id))
        lines.append(
            MapPolyline(
                name=label,
                points=tuple(sampled),
                kind="flight" if is_flight else "track",
                color="#e07a3d" if is_flight else "#2eb8a0",
                min_zoom=FLIGHT_LINE_MIN_ZOOM if is_flight else 0,
                pilot=track.pilot,
                external_url=track.external_url,
                source_file_id=track.source_file_id,
                sort_status=status,
            )
        )
    return lines


def _photo_markers(
    session: Session,
    project_id: int,
    thumbs_dir: Path,
    *,
    size: int,
    source_file_ids: set[int] | None = None,
    positions: dict[int, tuple[float, float, bool]] | None = None,
) -> list[MapMarker]:
    if source_file_ids is not None and not source_file_ids:
        return []
    filters = [
        SourceFile.project_id == project_id,
        SourceFile.file_kind.in_((FileKind.PHOTO.value, FileKind.VIDEO.value, FileKind.GPS.value)),
    ]
    if positions is None:
        filters.append(SourceFile.gps_latitude.is_not(None))
        filters.append(SourceFile.gps_longitude.is_not(None))
    query = (
        select(SourceFile)
        .options(selectinload(SourceFile.photo))
        .where(*filters)
    )
    if source_file_ids is not None:
        query = query.where(SourceFile.id.in_(source_file_ids))
    rows = list(session.scalars(query))
    moments = _journal_moments(session, [row.id for row in rows if row.id is not None])

    def row_moment(row: SourceFile) -> datetime | None:
        return aware(moments.get(row.id) or row.captured_at)

    rows.sort(
        key=lambda row: (
            0 if row_moment(row) is not None else 1,
            row_moment(row) or datetime.max.replace(tzinfo=UTC),
            row.filename,
        )
    )
    day_index: dict[str, int] = {}
    markers: list[MapMarker] = []
    for row in rows:
        if row.id is None:
            continue
        if positions is not None and row.id in positions:
            latitude, longitude, _inherited = positions[row.id]
        elif row.gps_latitude is not None and row.gps_longitude is not None:
            latitude, longitude = row.gps_latitude, row.gps_longitude
        else:
            continue
        photo = row.photo
        status = effective_sort_status(
            photo.sort_status if photo is not None else None,
            bool(photo.is_favorite) if photo is not None else False,
        )
        if status == SORT_REJECTED:
            continue
        moment = row_moment(row)
        day_key = _day_key(moment)
        if day_key not in day_index:
            day_index[day_key] = len(day_index)
        color = _DAY_COLORS[day_index[day_key] % len(_DAY_COLORS)]
        if row.file_kind == FileKind.PHOTO.value:
            kind = "photo"
        elif row.file_kind == FileKind.VIDEO.value:
            kind = "video"
        else:
            kind = "track"
        heading = row.heading_degrees if kind == "photo" else None
        fov = photo_fov_degrees(row.focal_length_35mm, row.focal_length) if heading is not None else None
        markers.append(
            MapMarker(
                latitude=latitude,
                longitude=longitude,
                label=day_key,
                kind=kind,
                preview_path=cached_thumbnail_path(
                    thumbs_dir,
                    source_file_id=row.id,
                    sha256=row.sha256,
                    size=size,
                    rotation_degrees=normalize_rotation_degrees(row.rotation_degrees),
                ),
                day_key=day_key,
                color=color,
                subtitle=row.filename,
                source_file_id=row.id,
                sort_status=status,
                heading_degrees=heading,
                fov_degrees=fov,
            )
        )
    return markers


def _place_markers(session: Session, project_id: int) -> list[MapMarker]:
    rows = session.scalars(
        select(Place)
        .join(TripDay, Place.day_id == TripDay.id)
        .join(Trip, TripDay.trip_id == Trip.id)
        .where(
            Trip.project_id == project_id,
            Place.latitude.is_not(None),
            Place.longitude.is_not(None),
        )
    )
    return [
        MapMarker(
            latitude=place.latitude,
            longitude=place.longitude,
            label=place.name,
            kind="place",
            color="gray",
        )
        for place in rows
        if place.latitude is not None and place.longitude is not None
    ]


def _day_key(value: datetime | None) -> str:
    key = calendar_key(value)
    if key is None:
        return "Ohne Datum"
    return key.isoformat()


def _journal_moments(session: Session, source_ids: list[int]) -> dict[int, datetime | None]:
    if not source_ids:
        return {}
    rows = session.execute(
        select(SectionMember.source_file_id, SectionMember.journal_at).where(
            SectionMember.source_file_id.in_(source_ids)
        )
    )
    return {source_id: journal_at for source_id, journal_at in rows}


def photo_fov_degrees(focal_35mm: float | None, focal_mm: float | None = None) -> float:
    """Horizontal field of view from 35 mm equivalent (full-frame width 36 mm)."""

    fl = None
    if focal_35mm is not None and focal_35mm > 0:
        fl = focal_35mm
    elif focal_mm is not None and focal_mm > 0:
        fl = focal_mm
    if fl is None:
        return DEFAULT_PHOTO_FOV_DEGREES
    fov = 2 * degrees(atan(18.0 / fl))
    return max(8.0, min(fov, 140.0))


def _sort_status_map(session: Session, source_ids: set[int]) -> dict[int, str | None]:
    if not source_ids:
        return {}
    rows = session.execute(
        select(Photo.source_file_id, Photo.sort_status, Photo.is_favorite).where(
            Photo.source_file_id.in_(source_ids)
        )
    )
    return {source_id: effective_sort_status(status, favorite) for source_id, status, favorite in rows}


def _center(
    markers: tuple[MapMarker, ...] | list[MapMarker],
    polylines: tuple[MapPolyline, ...] | list[MapPolyline],
) -> tuple[float, float] | None:
    coords: list[tuple[float, float]] = [(item.latitude, item.longitude) for item in markers]
    for line in polylines:
        coords.extend(line.points)
    if not coords:
        return None
    lat = sum(item[0] for item in coords) / len(coords)
    lon = sum(item[1] for item in coords) / len(coords)
    return (lat, lon)
