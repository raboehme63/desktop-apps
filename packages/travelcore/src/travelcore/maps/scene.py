"""Map scene assembled from the project index. Originals are never written."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from math import ceil
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from travelcore.database.models import GpsPoint, GpsTrack, Place, SourceFile, Trip, TripDay
from travelcore.media.orientation import normalize_rotation_degrees
from travelcore.media.thumbnails import cached_thumbnail_path
from travelcore.media.types import FileKind

MAX_TRACK_DISPLAY_POINTS = 2500
MAX_FLIGHT_DISPLAY_POINTS = 1200
FLIGHT_LINE_MIN_ZOOM = 10
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


@dataclass(frozen=True, slots=True)
class MapPolyline:
    name: str
    points: tuple[tuple[float, float], ...]
    kind: str = "track"
    color: str = "#2eb8a0"
    min_zoom: int = 0
    pilot: str | None = None
    external_url: str | None = None


@dataclass(frozen=True, slots=True)
class MapScene:
    markers: tuple[MapMarker, ...] = ()
    polylines: tuple[MapPolyline, ...] = ()
    center: tuple[float, float] | None = None

    @property
    def empty(self) -> bool:
        return not self.markers and not self.polylines


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
    """Overview: one cover per section or leftover day."""

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
    lines: list[MapPolyline] = []
    for key, coords in grouped.items():
        track = meta[key[0]]
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
) -> list[MapMarker]:
    if source_file_ids is not None and not source_file_ids:
        return []
    query = (
        select(SourceFile)
        .where(
            SourceFile.project_id == project_id,
            SourceFile.file_kind.in_(
                (FileKind.PHOTO.value, FileKind.VIDEO.value, FileKind.GPS.value)
            ),
            SourceFile.gps_latitude.is_not(None),
            SourceFile.gps_longitude.is_not(None),
        )
        .order_by(SourceFile.captured_at.asc().nulls_last(), SourceFile.filename.asc())
    )
    if source_file_ids is not None:
        query = query.where(SourceFile.id.in_(source_file_ids))
    rows = session.scalars(query)
    day_index: dict[str, int] = {}
    markers: list[MapMarker] = []
    for row in rows:
        if row.gps_latitude is None or row.gps_longitude is None:
            continue
        day_key = _day_key(row.captured_at)
        if day_key not in day_index:
            day_index[day_key] = len(day_index)
        color = _DAY_COLORS[day_index[day_key] % len(_DAY_COLORS)]
        if row.file_kind == FileKind.PHOTO.value:
            kind = "photo"
        elif row.file_kind == FileKind.VIDEO.value:
            kind = "video"
        else:
            kind = "track"
        markers.append(
            MapMarker(
                latitude=row.gps_latitude,
                longitude=row.gps_longitude,
                label=_day_key(row.captured_at),
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
    if value is None:
        return "Ohne Datum"
    return value.date().isoformat()


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
