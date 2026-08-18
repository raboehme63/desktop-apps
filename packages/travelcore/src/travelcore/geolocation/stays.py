"""Cluster geotagged points into stay suggestions. Originals are never written."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import asin, cos, radians, sin, sqrt

_EARTH_M = 6_371_000.0


@dataclass(frozen=True, slots=True)
class StayCluster:
    latitude: float
    longitude: float
    point_count: int
    duration_minutes: float
    started_at: datetime | None
    ended_at: datetime | None


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in meters."""

    phi1, phi2 = radians(lat1), radians(lat2)
    d_phi = radians(lat2 - lat1)
    d_lambda = radians(lon2 - lon1)
    chord = sin(d_phi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(d_lambda / 2) ** 2
    return 2 * _EARTH_M * asin(min(1.0, sqrt(chord)))


def cluster_stays(
    points: list[tuple[float, float, datetime | None]],
    *,
    radius_meters: float = 150.0,
    min_duration_minutes: float = 0.0,
) -> list[StayCluster]:
    """Greedy clusters: a point joins the first cluster within ``radius_meters``."""

    clusters: list[list[tuple[float, float, datetime | None]]] = []
    for point in points:
        assigned = False
        for group in clusters:
            lat, lon, _time = _mean(group)
            if haversine_m(lat, lon, point[0], point[1]) <= radius_meters:
                group.append(point)
                assigned = True
                break
        if not assigned:
            clusters.append([point])

    result: list[StayCluster] = []
    for group in clusters:
        lat, lon, _ = _mean(group)
        times = [item[2] for item in group if item[2] is not None]
        started = min(times) if times else None
        ended = max(times) if times else None
        duration = 0.0
        if started is not None and ended is not None:
            duration = max(0.0, (ended - started).total_seconds() / 60.0)
        if duration < min_duration_minutes and min_duration_minutes > 0 and len(group) < 2:
            continue
        result.append(
            StayCluster(
                latitude=lat,
                longitude=lon,
                point_count=len(group),
                duration_minutes=duration,
                started_at=started,
                ended_at=ended,
            )
        )
    return result


def _mean(group: list[tuple[float, float, datetime | None]]) -> tuple[float, float, None]:
    lat = sum(item[0] for item in group) / len(group)
    lon = sum(item[1] for item in group) / len(group)
    return lat, lon, None
