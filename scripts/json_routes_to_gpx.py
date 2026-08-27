"""Convert Polar-style training JSON (non-empty routes) to a sibling GPX track."""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

CREATOR = "json_routes_to_gpx"
_TRANSITION_KEYS = frozenset({"transitionroute", "transition_route"})


@dataclass(frozen=True, slots=True)
class RoutePoint:
    latitude: float
    longitude: float
    elevation: float | None
    recorded_at: datetime | None


@dataclass(frozen=True, slots=True)
class RouteTrack:
    name: str
    points: tuple[RoutePoint, ...]


def json_files_in(directory: Path, *, recursive: bool) -> list[Path]:
    iterator = directory.rglob("*") if recursive else directory.iterdir()
    files = [path for path in iterator if path.is_file() and path.suffix.lower() == ".json"]
    return sorted(files, key=lambda item: str(item).lower())


def convert_file(path: Path) -> Path | None:
    """Write ``path`` with suffix ``.gpx`` when a non-empty routes section exists."""

    data = json.loads(path.read_text(encoding="utf-8-sig"))
    tracks = tracks_from_json(data)
    if not tracks:
        return None
    dest = path.with_suffix(".gpx")
    dest.write_text(tracks_to_gpx(tracks), encoding="utf-8")
    return dest


def tracks_from_json(data: object) -> tuple[RouteTrack, ...]:
    session_name = _text(_get(data, "name")) if isinstance(data, dict) else ""
    collected: list[RouteTrack] = []
    for index, (routes, context) in enumerate(_iter_routes(data, _Context()), 1):
        points = waypoints_from_routes(routes, context)
        if not points:
            continue
        name = context.name or session_name or f"Track {index}"
        collected.append(RouteTrack(name=name, points=tuple(points)))
    return tuple(collected)


def waypoints_from_routes(routes: object, context: _Context | None = None) -> list[RoutePoint]:
    """Return the primary track from a Polar ``routes`` object (not transitionRoute)."""

    ctx = context or _Context()
    if not routes:
        return []
    if isinstance(routes, list):
        if routes and _is_point_dict(routes[0]):
            return _points_from_list(routes, ctx)
        points: list[RoutePoint] = []
        for item in routes:
            points.extend(waypoints_from_routes(item, ctx))
        return points
    if not isinstance(routes, dict):
        return []
    primary = _get(routes, "route")
    if primary is not None:
        nested = _waypoints_container(primary, ctx)
        if nested:
            return nested
    direct = _waypoints_container(routes, ctx)
    if direct:
        return direct
    for key, value in routes.items():
        if str(key).lower().replace("-", "_") in _TRANSITION_KEYS:
            continue
        nested = _waypoints_container(value, ctx)
        if nested:
            return nested
    for key, value in routes.items():
        if str(key).lower().replace("-", "_") in _TRANSITION_KEYS:
            nested = _waypoints_container(value, ctx)
            if nested:
                return nested
    return []


def tracks_to_gpx(tracks: Sequence[RouteTrack]) -> str:
    root = ET.Element(
        "gpx",
        {
            "version": "1.1",
            "creator": CREATOR,
            "xmlns": "http://www.topografix.com/GPX/1/1",
        },
    )
    first_time = next(
        (point.recorded_at for track in tracks for point in track.points if point.recorded_at),
        None,
    )
    if tracks or first_time is not None:
        meta = ET.SubElement(root, "metadata")
        if tracks and tracks[0].name:
            ET.SubElement(meta, "name").text = tracks[0].name
        if first_time is not None:
            ET.SubElement(meta, "time").text = _gpx_time(first_time)
    for track in tracks:
        trk = ET.SubElement(root, "trk")
        if track.name:
            ET.SubElement(trk, "name").text = track.name
        seg = ET.SubElement(trk, "trkseg")
        for point in track.points:
            trkpt = ET.SubElement(
                seg,
                "trkpt",
                {"lat": _coord(point.latitude), "lon": _coord(point.longitude)},
            )
            if point.elevation is not None:
                ET.SubElement(trkpt, "ele").text = _number(point.elevation)
            if point.recorded_at is not None:
                ET.SubElement(trkpt, "time").text = _gpx_time(point.recorded_at)
    ET.indent(root, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Erzeugt GPX-Tracks aus JSON-Dateien mit nichtleerer Routes-Sektion."
    )
    parser.add_argument("-f", metavar="DATEI", dest="file", help="einzelne JSON-Datei")
    parser.add_argument("-d", metavar="VERZEICHNIS", dest="directory", help="Ordner mit JSON-Dateien")
    parser.add_argument(
        "-r",
        action="store_true",
        dest="recursive",
        help="mit -d auch Unterverzeichnisse einbeziehen",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    if bool(args.file) == bool(args.directory):
        parser.error("Bitte genau eine Option angeben: -f <Datei> oder -d <Verzeichnis>")
    if args.recursive and not args.directory:
        parser.error("-r gilt nur zusammen mit -d")
    if args.file:
        return _run_file(Path(args.file))
    return _run_directory(Path(args.directory), recursive=args.recursive)


@dataclass
class _Context:
    name: str = ""
    start: datetime | None = None
    offset_minutes: int | None = None

    def child(self, node: dict) -> _Context:
        name = _text(_get(node, "name")) or self.name
        start = _parse_time(_get(node, "startTime")) or self.start
        offset = _int(_get(node, "timezoneOffsetMinutes"))
        if offset is None:
            offset = self.offset_minutes
        return _Context(name=name, start=start, offset_minutes=offset)


def _iter_routes(node: object, context: _Context) -> Iterator[tuple[object, _Context]]:
    if isinstance(node, dict):
        current = context.child(node)
        routes = _get(node, "routes")
        if routes is not None:
            yield routes, current
        for key, value in node.items():
            if str(key).lower() == "routes":
                continue
            yield from _iter_routes(value, current)
        return
    if isinstance(node, list):
        for item in node:
            yield from _iter_routes(item, context)


def _waypoints_container(node: object, context: _Context) -> list[RoutePoint]:
    if isinstance(node, list):
        return waypoints_from_routes(node, context)
    if not isinstance(node, dict):
        return []
    nested = context.child(node)
    points = _get(node, "wayPoints") or _get(node, "waypoints") or _get(node, "points")
    if isinstance(points, list) and points:
        return _points_from_list(points, nested)
    return []


def _points_from_list(rows: list[object], context: _Context) -> list[RoutePoint]:
    points: list[RoutePoint] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        lat = _float(_first_key(row, "latitude", "lat"))
        lon = _float(_first_key(row, "longitude", "lon", "lng"))
        if lat is None or lon is None:
            continue
        ele = _float(_first_key(row, "altitude", "elevation", "ele"))
        elapsed = _int(_first_key(row, "elapsedMillis", "elapsed_ms"))
        recorded = None
        if context.start is not None and elapsed is not None:
            recorded = _as_utc(context.start, context.offset_minutes) + timedelta(milliseconds=elapsed)
        else:
            stamp = _parse_time(_first_key(row, "time", "timestamp"))
            if stamp is not None:
                recorded = _as_utc(stamp, context.offset_minutes)
        points.append(RoutePoint(latitude=lat, longitude=lon, elevation=ele, recorded_at=recorded))
    return points


def _is_point_dict(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    lat = _first_key(value, "latitude", "lat")
    lon = _first_key(value, "longitude", "lon", "lng")
    return lat is not None and lon is not None


def _first_key(node: object, *names: str) -> object | None:
    for name in names:
        if not isinstance(node, dict):
            return None
        if any(str(key).lower() == name.lower() for key in node):
            return _get(node, name)
    return None


def _get(node: object, name: str) -> object | None:
    if not isinstance(node, dict):
        return None
    wanted = name.lower()
    for key, value in node.items():
        if str(key).lower() == wanted:
            return value
    return None


def _text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_time(value: object) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _as_utc(value: datetime | None, offset_minutes: int | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(UTC)
    if offset_minutes is None:
        return value.replace(tzinfo=UTC)
    return (value - timedelta(minutes=offset_minutes)).replace(tzinfo=UTC)


def _gpx_time(value: datetime) -> str:
    stamp = value.astimezone(UTC).replace(microsecond=0)
    return stamp.strftime("%Y-%m-%dT%H:%M:%SZ")


def _coord(value: float) -> str:
    return f"{value:.8f}".rstrip("0").rstrip(".")


def _number(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _run_file(path: Path) -> int:
    if not path.is_file():
        print(f"Datei nicht gefunden: {path}", file=sys.stderr)
        return 2
    try:
        written = convert_file(path)
    except json.JSONDecodeError as exc:
        print(f"{path}: ungültiges JSON ({exc.msg})", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"{path}: {exc}", file=sys.stderr)
        return 1
    if written is None:
        print(f"keine Routen: {path}")
        return 0
    print(written)
    return 0


def _run_directory(directory: Path, *, recursive: bool) -> int:
    if not directory.is_dir():
        print(f"Verzeichnis nicht gefunden: {directory}", file=sys.stderr)
        return 2
    files = json_files_in(directory, recursive=recursive)
    json_count = 0
    gpx_count = 0
    for path in files:
        json_count += 1
        print(".", end="", flush=True)
        try:
            if convert_file(path) is not None:
                gpx_count += 1
        except (json.JSONDecodeError, OSError) as exc:
            print(f"\n{path}: {exc}", file=sys.stderr)
    if json_count:
        print()
    print(f"JSON {json_count}, GPX {gpx_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
