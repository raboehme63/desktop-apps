"""Parse GPX files into typed track points. Original files are read-only."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import gpxpy
import gpxpy.gpx

from travelcore.exceptions import GpsError
from travelcore.gps.types import TrackPoint

_GPX_SUFFIXES = {".gpx"}


class _HasCoordinates(Protocol):
    latitude: float | None
    longitude: float | None
    elevation: float | None
    time: datetime | None


@dataclass(frozen=True, slots=True)
class ParsedTrack:
    """One GPS track or route before it is stored."""

    name: str | None
    points: tuple[TrackPoint, ...]
    format: str = "gpx"
    pilot: str | None = None


def parse_gpx(path: Path) -> tuple[ParsedTrack, ...]:
    """Read tracks and routes from a GPX file.

    An empty but well-formed file yields an empty tuple. Corrupt XML raises
    ``GpsError`` so the caller can record a per-file error and continue.
    """

    if path.suffix.lower() not in _GPX_SUFFIXES:
        return ()
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            text = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError) as exc:
            raise GpsError(f"GPX-Datei nicht lesbar: {path.name}") from exc
    except OSError as exc:
        raise GpsError(f"GPX-Datei nicht lesbar: {path.name}") from exc

    try:
        gpx = gpxpy.parse(text)
    except Exception as exc:  # noqa: BLE001 - gpxpy/XML parsers raise several types
        raise GpsError(f"Ungültige GPX-Datei: {path.name}") from exc

    tracks: list[ParsedTrack] = []
    for index, track in enumerate(gpx.tracks):
        points = _points_from_track(track, track_key=f"trk-{index}")
        if points:
            tracks.append(ParsedTrack(name=track.name or path.stem, points=tuple(points)))
    for index, route in enumerate(gpx.routes):
        points = _points_from_route(route, track_key=f"rte-{index}")
        if points:
            tracks.append(ParsedTrack(name=route.name or f"{path.stem} route", points=tuple(points)))
    return tuple(tracks)


def _points_from_track(track: gpxpy.gpx.GPXTrack, *, track_key: str) -> list[TrackPoint]:
    points: list[TrackPoint] = []
    sequence = 0
    for segment_id, segment in enumerate(track.segments):
        for raw in segment.points:
            converted = _from_gpx_point(raw, track_key=track_key, segment_id=segment_id, sequence=sequence)
            if converted is None:
                continue
            points.append(converted)
            sequence += 1
    return points


def _points_from_route(route: gpxpy.gpx.GPXRoute, *, track_key: str) -> list[TrackPoint]:
    points: list[TrackPoint] = []
    for sequence, raw in enumerate(route.points):
        converted = _from_gpx_point(raw, track_key=track_key, segment_id=0, sequence=sequence)
        if converted is not None:
            points.append(converted)
    return points


def _from_gpx_point(
    raw: _HasCoordinates,
    *,
    track_key: str,
    segment_id: int,
    sequence: int,
) -> TrackPoint | None:
    if raw.latitude is None or raw.longitude is None:
        return None
    try:
        latitude = float(raw.latitude)
        longitude = float(raw.longitude)
    except (TypeError, ValueError):
        return None
    if not -90.0 <= latitude <= 90.0 or not -180.0 <= longitude <= 180.0:
        return None
    altitude = None
    if raw.elevation is not None:
        try:
            altitude = float(raw.elevation)
        except (TypeError, ValueError):
            altitude = None
    return TrackPoint(
        latitude=latitude,
        longitude=longitude,
        altitude=altitude,
        recorded_at=_as_utc(raw.time),
        track_id=track_key,
        segment_id=segment_id,
        sequence_index=sequence,
    )


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
