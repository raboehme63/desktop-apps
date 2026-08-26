"""Parse KML tracks into typed points. Original files are read-only."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from travelcore.exceptions import GpsError
from travelcore.gps.parse import ParsedTrack
from travelcore.gps.types import TrackPoint

_KML_SUFFIXES = {".kml"}


def parse_kml(path: Path) -> tuple[ParsedTrack, ...]:
    """Read LineString / gx:Track coordinates from a KML file."""

    if path.suffix.lower() not in _KML_SUFFIXES:
        return ()
    try:
        tree = ET.parse(path)
    except (ET.ParseError, OSError) as exc:
        raise GpsError(f"Ungültige KML-Datei: {path.name}") from exc
    tracks: list[ParsedTrack] = []
    gx_points: list[TrackPoint] = []
    index = 0
    for element in tree.getroot().iter():
        local = _local_name(element.tag)
        if local == "coordinates":
            if gx_points:
                tracks.append(_reindex(path.stem, gx_points))
                gx_points = []
            points = _points_from_kml_coordinates(element.text or "", track_key=f"kml-{index}")
            if points:
                tracks.append(ParsedTrack(name=path.stem, points=tuple(points), format="kml"))
                index += 1
            continue
        if local != "coord":
            continue
        converted = _gx_coord(element.text or "")
        if converted is None:
            continue
        gx_points.append(
            TrackPoint(
                latitude=converted[1],
                longitude=converted[0],
                altitude=converted[2],
                recorded_at=None,
                track_id="gx-0",
                segment_id=0,
                sequence_index=len(gx_points),
            )
        )
    if gx_points:
        tracks.append(_reindex(path.stem, gx_points))
    return tuple(tracks)


def _reindex(name: str, points: list[TrackPoint]) -> ParsedTrack:
    ordered = [
        TrackPoint(
            latitude=point.latitude,
            longitude=point.longitude,
            altitude=point.altitude,
            recorded_at=point.recorded_at,
            track_id="gx-0",
            segment_id=0,
            sequence_index=index,
        )
        for index, point in enumerate(points)
    ]
    return ParsedTrack(name=name, points=tuple(ordered), format="kml")


def _points_from_kml_coordinates(text: str, *, track_key: str) -> list[TrackPoint]:
    points: list[TrackPoint] = []
    for index, token in enumerate(text.replace("\n", " ").split()):
        parts = token.split(",")
        if len(parts) < 2:
            continue
        try:
            longitude = float(parts[0])
            latitude = float(parts[1])
            altitude = float(parts[2]) if len(parts) > 2 and parts[2] else None
        except ValueError:
            continue
        if not -90.0 <= latitude <= 90.0 or not -180.0 <= longitude <= 180.0:
            continue
        points.append(
            TrackPoint(
                latitude=latitude,
                longitude=longitude,
                altitude=altitude,
                recorded_at=None,
                track_id=track_key,
                segment_id=0,
                sequence_index=index,
            )
        )
    return points


def _gx_coord(text: str) -> tuple[float, float, float | None] | None:
    parts = text.replace(",", " ").split()
    if len(parts) < 2:
        return None
    try:
        longitude = float(parts[0])
        latitude = float(parts[1])
        altitude = float(parts[2]) if len(parts) > 2 else None
    except ValueError:
        return None
    if not -90.0 <= latitude <= 90.0 or not -180.0 <= longitude <= 180.0:
        return None
    return longitude, latitude, altitude


def _local_name(tag: str) -> str:
    if tag.startswith("{") and "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag
