"""Map scene assembled from the project index. Originals are never written."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from math import ceil
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from travelcore.database.models import GpsPoint, GpsTrack, OvernightStay, Place, SourceFile, Trip, TripDay
from travelcore.media.thumbnails import cached_thumbnail_path
from travelcore.media.types import FileKind

MAX_TRACK_DISPLAY_POINTS = 2500
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


@dataclass(frozen=True, slots=True)
class MapPolyline:
    name: str
    points: tuple[tuple[float, float], ...]
    kind: str = "track"


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
    """Collect tracks, geotagged media, stays, and places for a map backend."""

    polylines = tuple(_track_polylines(session, project_id))
    markers = (
        *_photo_markers(session, project_id, thumbs_dir, size=size),
        *_overnight_markers(session, project_id),
        *_place_markers(session, project_id),
    )
    center = _center(markers, polylines)
    return MapScene(markers=markers, polylines=polylines, center=center)


def _track_polylines(session: Session, project_id: int) -> list[MapPolyline]:
    rows = session.execute(
        select(GpsPoint, GpsTrack)
        .join(GpsTrack, GpsPoint.track_id == GpsTrack.id)
        .where(GpsTrack.project_id == project_id)
        .order_by(GpsTrack.id.asc(), GpsPoint.segment_id.asc(), GpsPoint.sequence_index.asc())
    )
    grouped: dict[tuple[int, int], list[tuple[float, float]]] = defaultdict(list)
    names: dict[tuple[int, int], str] = {}
    for point, track in rows:
        key = (track.id, point.segment_id)
        grouped[key].append((point.latitude, point.longitude))
        names[key] = track.name or f"Track {track.id}"
    lines: list[MapPolyline] = []
    for key, coords in grouped.items():
        sampled = downsample_points(coords)
        if len(sampled) < 2:
            continue
        segment = key[1]
        label = names[key] if segment == 0 else f"{names[key]} ({segment + 1})"
        lines.append(MapPolyline(name=label, points=tuple(sampled)))
    return lines


def _photo_markers(
    session: Session,
    project_id: int,
    thumbs_dir: Path,
    *,
    size: int,
) -> list[MapMarker]:
    rows = session.scalars(
        select(SourceFile)
        .where(
            SourceFile.project_id == project_id,
            SourceFile.file_kind.in_((FileKind.PHOTO.value, FileKind.VIDEO.value)),
            SourceFile.gps_latitude.is_not(None),
            SourceFile.gps_longitude.is_not(None),
        )
        .order_by(SourceFile.captured_at.asc().nulls_last(), SourceFile.filename.asc())
    )
    day_index: dict[str, int] = {}
    markers: list[MapMarker] = []
    for row in rows:
        if row.gps_latitude is None or row.gps_longitude is None:
            continue
        day_key = _day_key(row.captured_at)
        if day_key not in day_index:
            day_index[day_key] = len(day_index)
        color = _DAY_COLORS[day_index[day_key] % len(_DAY_COLORS)]
        kind = "photo" if row.file_kind == FileKind.PHOTO.value else "video"
        markers.append(
            MapMarker(
                latitude=row.gps_latitude,
                longitude=row.gps_longitude,
                label=row.filename,
                kind=kind,
                preview_path=cached_thumbnail_path(
                    thumbs_dir,
                    source_file_id=row.id,
                    sha256=row.sha256,
                    size=size,
                ),
                day_key=day_key,
                color=color,
            )
        )
    return markers


def _overnight_markers(session: Session, project_id: int) -> list[MapMarker]:
    rows = session.scalars(
        select(OvernightStay)
        .join(TripDay, OvernightStay.day_id == TripDay.id)
        .join(Trip, TripDay.trip_id == Trip.id)
        .where(
            Trip.project_id == project_id,
            OvernightStay.latitude.is_not(None),
            OvernightStay.longitude.is_not(None),
        )
    )
    markers: list[MapMarker] = []
    for stay in rows:
        if stay.latitude is None or stay.longitude is None:
            continue
        label = stay.location_name or stay.name
        markers.append(
            MapMarker(
                latitude=stay.latitude,
                longitude=stay.longitude,
                label=label,
                kind="overnight",
                day_key=_day_key(stay.stayed_on),
                color="black",
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
