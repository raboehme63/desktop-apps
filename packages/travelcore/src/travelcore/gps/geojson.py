"""Parse GeoJSON tracks into typed points. Original files are read-only."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from travelcore.exceptions import GpsError
from travelcore.gps.parse import ParsedTrack
from travelcore.gps.types import TrackPoint

_GEOJSON_SUFFIXES = {".geojson"}


def parse_geojson(path: Path) -> tuple[ParsedTrack, ...]:
    """Read LineString / Polygon coordinates from a GeoJSON file."""

    if path.suffix.lower() not in _GEOJSON_SUFFIXES:
        return ()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GpsError(f"Ungültige GeoJSON-Datei: {path.name}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise GpsError(f"Ungültige GeoJSON-Datei: {path.name}") from exc
    if not isinstance(payload, dict):
        return ()
    tracks: list[ParsedTrack] = []
    _collect(payload, tracks, path.stem)
    return tuple(track for track in tracks if track.points)


def _collect(node: Any, tracks: list[ParsedTrack], name: str) -> None:
    if isinstance(node, list):
        for item in node:
            _collect(item, tracks, name)
        return
    if not isinstance(node, dict):
        return
    kind = node.get("type")
    if kind == "FeatureCollection":
        _collect(node.get("features"), tracks, name)
        return
    if kind == "Feature":
        _collect(node.get("geometry"), tracks, name)
        return
    coords = node.get("coordinates")
    if kind == "LineString":
        tracks.append(_line(coords, name, f"line-{len(tracks)}"))
    elif kind == "MultiLineString" and isinstance(coords, list):
        for index, line in enumerate(coords):
            tracks.append(_line(line, name, f"multi-{len(tracks)}-{index}"))
    elif kind == "Polygon" and isinstance(coords, list) and coords:
        tracks.append(_line(coords[0], name, f"poly-{len(tracks)}"))
    elif kind == "MultiPolygon" and isinstance(coords, list):
        for index, polygon in enumerate(coords):
            if isinstance(polygon, list) and polygon:
                tracks.append(_line(polygon[0], name, f"mpoly-{len(tracks)}-{index}"))
    elif kind == "GeometryCollection":
        _collect(node.get("geometries"), tracks, name)


def _line(coords: Any, name: str, track_key: str) -> ParsedTrack:
    points: list[TrackPoint] = []
    if not isinstance(coords, list):
        return ParsedTrack(name=name, points=(), format="geojson")
    for index, pair in enumerate(coords):
        if not isinstance(pair, list | tuple) or len(pair) < 2:
            continue
        try:
            longitude = float(pair[0])
            latitude = float(pair[1])
            altitude = float(pair[2]) if len(pair) > 2 and pair[2] is not None else None
        except (TypeError, ValueError):
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
    return ParsedTrack(name=name, points=tuple(points), format="geojson")
