"""Build StayLink segments from Transfer connection lines, including gap fillers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import atan2, cos, radians, sin, sqrt

from travelcore.maps.scene import (
    STAY_LINK_ROLE_GAP,
    STAY_LINK_ROLE_USER,
    STAY_LINK_STYLE_CURVE,
    STAY_LINK_STYLE_ROUTE,
    STAY_LINK_STYLE_STRAIGHT,
    STAY_LINK_STYLE_TRACK,
    StayLinkSegment,
    downsample_points,
)
from travelcore.timeline.transfer_links import (
    ARC_BULGE,
    ARC_SAMPLES,
    GAP_MIN_METERS,
    LINK_DASH_SOLID,
    LINK_GEOMETRY_ARC,
    LINK_GEOMETRY_LINE,
    LINK_GEOMETRY_ROUTE,
    LINK_GEOMETRY_TRACK,
    OVERVIEW_TRACK_POINTS,
)
from travelcore.timeline.types import TimelineLink

_EARTH_M = 6371000.0
_STYLE_BY_GEOMETRY = {
    LINK_GEOMETRY_LINE: STAY_LINK_STYLE_STRAIGHT,
    LINK_GEOMETRY_TRACK: STAY_LINK_STYLE_TRACK,
    LINK_GEOMETRY_ARC: STAY_LINK_STYLE_CURVE,
    LINK_GEOMETRY_ROUTE: STAY_LINK_STYLE_ROUTE,
}


def style_for_geometry(geometry: str) -> str:
    return _STYLE_BY_GEOMETRY.get(geometry, STAY_LINK_STYLE_STRAIGHT)


def build_stay_segments(
    start: tuple[float, float],
    end: tuple[float, float],
    links: Sequence[TimelineLink],
    tracks: Mapping[int, tuple[tuple[float, float], ...]] | None = None,
) -> tuple[StayLinkSegment, ...]:
    """User geometries in list order, then dotted straight fillers for leftover gaps."""

    tracks = tracks or {}
    if not links:
        return ()
    users = _user_segments(start, end, links, tracks)
    return insert_gap_segments(start, end, users)


def insert_gap_segments(
    start: tuple[float, float],
    end: tuple[float, float],
    users: Sequence[StayLinkSegment],
) -> tuple[StayLinkSegment, ...]:
    """Insert dotted straight segments between covers and user endpoints that do not meet."""

    if not users:
        return ()
    chain: list[StayLinkSegment] = []
    cursor = start
    for user in users:
        if not user.points:
            continue
        first = user.points[0]
        gap = _gap_segment(cursor, first)
        if gap is not None:
            chain.append(gap)
        chain.append(user)
        cursor = user.points[-1]
    tail = _gap_segment(cursor, end)
    if tail is not None:
        chain.append(tail)
    return tuple(chain)


def arc_points(
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    samples: int = ARC_SAMPLES,
    bulge: float = ARC_BULGE,
) -> tuple[tuple[float, float], ...]:
    """Geographic bulge to the right of the travel direction."""

    if start == end:
        return (start, end)
    count = max(3, samples)
    mid_lat = (start[0] + end[0]) / 2.0
    dx = end[1] - start[1]
    dy = end[0] - start[0]
    length = sqrt(dx * dx + dy * dy)
    if length <= 0:
        return (start, end)
    nx, ny = -dy / length, dx / length
    control = (mid_lat + ny * length * bulge, (start[1] + end[1]) / 2.0 + nx * length * bulge)
    points = [_quad_bezier(start, control, end, index / (count - 1)) for index in range(count)]
    return tuple(points)


def distance_meters(start: tuple[float, float], end: tuple[float, float]) -> float:
    lat1, lon1 = radians(start[0]), radians(start[1])
    lat2, lon2 = radians(end[0]), radians(end[1])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    angle = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * _EARTH_M * atan2(sqrt(angle), sqrt(max(0.0, 1.0 - angle)))


def orient_track(
    points: Sequence[tuple[float, float]],
    start: tuple[float, float],
    end: tuple[float, float],
) -> list[tuple[float, float]]:
    """Reverse a track when its first point is closer to the chain end than the start."""

    coords = list(points)
    if len(coords) < 2:
        return coords
    head, tail = coords[0], coords[-1]
    forward = distance_meters(head, start) + distance_meters(tail, end)
    backward = distance_meters(tail, start) + distance_meters(head, end)
    if backward + 1.0 < forward:
        coords.reverse()
    return coords


def _user_segments(
    start: tuple[float, float],
    end: tuple[float, float],
    links: Sequence[TimelineLink],
    tracks: Mapping[int, tuple[tuple[float, float], ...]],
) -> list[StayLinkSegment]:
    segments: list[StayLinkSegment] = []
    cursor = start
    for index, link in enumerate(links):
        following = links[index + 1] if index + 1 < len(links) else None
        vertex = _end_vertex(link, following, end, tracks)
        track_pts = _track_points(link, tracks)
        if link.geometry == LINK_GEOMETRY_TRACK and track_pts:
            aligned = orient_track(track_pts, cursor, vertex or end)
            points = downsample_points(aligned, max_points=OVERVIEW_TRACK_POINTS)
            if len(points) >= 2:
                segments.append(_user_segment(link, points))
                cursor = points[-1]
                continue
        if vertex is None:
            continue
        points = list(arc_points(cursor, vertex)) if link.geometry == LINK_GEOMETRY_ARC else [cursor, vertex]
        if len(points) >= 2 and points[0] != points[-1]:
            segments.append(_user_segment(link, points))
        cursor = vertex
    return segments


def _end_vertex(
    link: TimelineLink,
    following: TimelineLink | None,
    cover_end: tuple[float, float],
    tracks: Mapping[int, tuple[tuple[float, float], ...]],
) -> tuple[float, float] | None:
    if link.end_latitude is not None and link.end_longitude is not None:
        return (link.end_latitude, link.end_longitude)
    if following is None:
        return cover_end
    nxt = _track_points(following, tracks)
    if nxt:
        return nxt[0]
    own = _track_points(link, tracks)
    if own:
        return own[-1]
    return cover_end


def _track_points(
    link: TimelineLink,
    tracks: Mapping[int, tuple[tuple[float, float], ...]],
) -> tuple[tuple[float, float], ...]:
    if link.geometry != LINK_GEOMETRY_TRACK or link.track_source_file_id is None:
        return ()
    return tracks.get(link.track_source_file_id, ())


def _user_segment(link: TimelineLink, points: Sequence[tuple[float, float]]) -> StayLinkSegment:
    return StayLinkSegment(
        role=STAY_LINK_ROLE_USER,
        style=style_for_geometry(link.geometry),
        dash=link.dash or LINK_DASH_SOLID,
        symbol=link.symbol,
        points=tuple(points),
    )


def _gap_segment(
    start: tuple[float, float], end: tuple[float, float]
) -> StayLinkSegment | None:
    if distance_meters(start, end) < GAP_MIN_METERS:
        return None
    return StayLinkSegment(
        role=STAY_LINK_ROLE_GAP,
        style=STAY_LINK_STYLE_STRAIGHT,
        dash="dotted",
        symbol=None,
        points=(start, end),
    )


def _quad_bezier(
    start: tuple[float, float],
    control: tuple[float, float],
    end: tuple[float, float],
    t: float,
) -> tuple[float, float]:
    rest = 1.0 - t
    lat = rest * rest * start[0] + 2 * rest * t * control[0] + t * t * end[0]
    lon = rest * rest * start[1] + 2 * rest * t * control[1] + t * t * end[1]
    return (lat, lon)
