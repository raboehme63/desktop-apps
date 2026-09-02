"""Extract Polar ``routes.wayPoints`` tracks (not ``transitionRoute``)."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta

from fitnesscore.parse.common import as_float, as_int, as_text, as_utc, json_first, json_get, parse_time
from fitnesscore.parse.types import ParsedTrack, RoutePoint

_TRANSITION_KEYS = frozenset({"transitionroute", "transition_route"})


@dataclass
class _Context:
    name: str = ""
    start: datetime | None = None
    offset_minutes: int | None = None

    def child(self, node: dict) -> _Context:
        name = as_text(json_get(node, "name")) or self.name
        start = parse_time(json_get(node, "startTime")) or self.start
        offset = as_int(json_get(node, "timezoneOffsetMinutes"))
        if offset is None:
            offset = self.offset_minutes
        return _Context(name=name, start=start, offset_minutes=offset)


def tracks_from_json(data: object) -> tuple[ParsedTrack, ...]:
    session_name = as_text(json_get(data, "name")) if isinstance(data, dict) else ""
    collected: list[ParsedTrack] = []
    for index, (routes, context) in enumerate(_iter_routes(data, _Context()), 1):
        points = waypoints_from_routes(routes, context)
        if not points:
            continue
        name = context.name or session_name or f"Track {index}"
        collected.append(ParsedTrack(name=name, points=tuple(points)))
    return tuple(collected)


def waypoints_from_routes(routes: object, context: _Context | None = None) -> list[RoutePoint]:
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
    primary = json_get(routes, "route")
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


def tracks_from_planned(data: object) -> tuple[ParsedTrack, ...]:
    if not isinstance(data, dict):
        return ()
    name = as_text(json_get(data, "name")) or "Planned route"
    rows = json_get(data, "waypoints") or json_get(data, "wayPoints")
    if not isinstance(rows, list):
        return ()
    points: list[RoutePoint] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        location = json_get(row, "location") if json_get(row, "location") else row
        lat = as_float(json_first(location, "latitude", "lat"))
        lon = as_float(json_first(location, "longitude", "lon", "lng"))
        if lat is None or lon is None:
            continue
        ele = as_float(json_first(location, "altitude", "elevation", "ele"))
        points.append(RoutePoint(latitude=lat, longitude=lon, elevation=ele, recorded_at=None))
    if not points:
        return ()
    return (ParsedTrack(name=name, points=tuple(points)),)


def _iter_routes(node: object, context: _Context) -> Iterator[tuple[object, _Context]]:
    if isinstance(node, dict):
        current = context.child(node)
        routes = json_get(node, "routes")
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
    points = json_get(node, "wayPoints") or json_get(node, "waypoints") or json_get(node, "points")
    if isinstance(points, list) and points:
        return _points_from_list(points, nested)
    return []


def _points_from_list(rows: list[object], context: _Context) -> list[RoutePoint]:
    points: list[RoutePoint] = []
    start = context.start
    for row in rows:
        if not isinstance(row, dict):
            continue
        lat = as_float(json_first(row, "latitude", "lat"))
        lon = as_float(json_first(row, "longitude", "lon", "lng"))
        if lat is None or lon is None:
            continue
        ele = as_float(json_first(row, "altitude", "elevation", "ele"))
        elapsed = as_int(json_first(row, "elapsedMillis", "elapsed_ms"))
        recorded = None
        if start is not None and elapsed is not None:
            recorded = as_utc(start, context.offset_minutes) + timedelta(milliseconds=elapsed)
        else:
            stamp = parse_time(json_first(row, "time", "timestamp"))
            if stamp is not None:
                recorded = as_utc(stamp, context.offset_minutes)
        points.append(RoutePoint(latitude=lat, longitude=lon, elevation=ele, recorded_at=recorded))
    return points


def _is_point_dict(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    lat = json_first(value, "latitude", "lat")
    lon = json_first(value, "longitude", "lon", "lng")
    return lat is not None and lon is not None
