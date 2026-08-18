"""Time-based matching of media to GPS track points."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from travelcore.gps.types import GpsFix, TrackPoint
from travelcore.metadata.time import parse_offset

SOURCE_INTERPOLATED = "gpx_interpolated"
SOURCE_NEAREST = "gpx_nearest"
PROTECTED_SOURCES = frozenset({"exif", "quicktime", "manual"})


def interpolate_position(moment: datetime, before: TrackPoint, after: TrackPoint) -> GpsFix:
    """Linearly interpolate lat/lon/alt between two timed track points."""

    start = _require_time(before)
    end = _require_time(after)
    span = (end - start).total_seconds()
    if span <= 0:
        delta = abs((moment - start).total_seconds())
        return GpsFix(
            latitude=before.latitude,
            longitude=before.longitude,
            altitude=before.altitude,
            source=SOURCE_NEAREST,
            confidence=_confidence(delta, span or 1.0),
            time_delta_seconds=delta,
            from_exif=False,
        )
    fraction = (moment - start).total_seconds() / span
    fraction = max(0.0, min(1.0, fraction))
    altitude = None
    if before.altitude is not None and after.altitude is not None:
        altitude = before.altitude + fraction * (after.altitude - before.altitude)
    nearest = min(abs((moment - start).total_seconds()), abs((moment - end).total_seconds()))
    return GpsFix(
        latitude=before.latitude + fraction * (after.latitude - before.latitude),
        longitude=_lerp_longitude(before.longitude, after.longitude, fraction),
        altitude=altitude,
        source=SOURCE_INTERPOLATED,
        confidence=_confidence(nearest, span),
        time_delta_seconds=nearest,
        from_exif=False,
    )


def match_position(
    moment: datetime,
    points: Sequence[TrackPoint],
    *,
    max_delta_seconds: float = 120.0,
) -> GpsFix | None:
    """Return an interpolated or nearest fix if ``moment`` lies near the track."""

    timed = sorted(
        (point for point in points if point.recorded_at is not None),
        key=lambda item: _require_time(item),
    )
    if not timed:
        return None
    moment = _as_utc(moment)
    index = _bisect_right(timed, moment)
    previous = timed[index - 1] if index > 0 else None
    following = timed[index] if index < len(timed) else None
    max_delta = timedelta(seconds=max_delta_seconds)

    if previous is not None and following is not None:
        prev_t = _require_time(previous)
        next_t = _require_time(following)
        if prev_t <= moment <= next_t:
            to_prev = moment - prev_t
            to_next = next_t - moment
            if to_prev <= max_delta and to_next <= max_delta:
                return interpolate_position(moment, previous, following)
            nearer = previous if to_prev <= to_next else following
            delta = min(to_prev, to_next)
            if delta <= max_delta:
                return _nearest_fix(moment, nearer)

    if previous is not None:
        delta = moment - _require_time(previous)
        if timedelta(0) <= delta <= max_delta:
            return _nearest_fix(moment, previous)
    if following is not None:
        delta = _require_time(following) - moment
        if timedelta(0) <= delta <= max_delta:
            return _nearest_fix(moment, following)
    return None


def media_time_utc(
    captured_at: datetime,
    *,
    timezone_name: str | None = None,
    timezone_unknown: bool = True,
    default_timezone: str | None = None,
) -> datetime:
    """Convert a stored capture time to UTC for comparison with GPX points.

    Aware values are converted directly. Naive values use ``timezone_name``,
    then the project default, then UTC as last resort — without changing the
    stored ``timezone_unknown`` flag on the source row.
    """

    _ = timezone_unknown
    if captured_at.tzinfo is not None:
        return captured_at.astimezone(UTC)
    zone = _resolve_zone(timezone_name) or _resolve_zone(default_timezone)
    if zone is not None:
        return captured_at.replace(tzinfo=zone).astimezone(UTC)
    return captured_at.replace(tzinfo=UTC)


def _nearest_fix(moment: datetime, point: TrackPoint) -> GpsFix:
    recorded = _require_time(point)
    delta = abs((moment - recorded).total_seconds())
    return GpsFix(
        latitude=point.latitude,
        longitude=point.longitude,
        altitude=point.altitude,
        source=SOURCE_NEAREST,
        confidence=_confidence(delta, max(delta, 1.0)),
        time_delta_seconds=delta,
        from_exif=False,
    )


def _confidence(nearest_delta: float, reference: float) -> float:
    span = max(reference, 1.0)
    ratio = min(abs(nearest_delta) / span, 1.0)
    return round(max(0.2, 0.99 - 0.5 * ratio), 4)


def _lerp_longitude(start: float, end: float, fraction: float) -> float:
    delta = end - start
    if delta > 180.0:
        delta -= 360.0
    elif delta < -180.0:
        delta += 360.0
    return ((start + fraction * delta + 180.0) % 360.0) - 180.0


def _bisect_right(points: Sequence[TrackPoint], moment: datetime) -> int:
    low = 0
    high = len(points)
    while low < high:
        mid = (low + high) // 2
        if _require_time(points[mid]) <= moment:
            low = mid + 1
        else:
            high = mid
    return low


def _require_time(point: TrackPoint) -> datetime:
    if point.recorded_at is None:
        raise ValueError("track point has no time")
    return _as_utc(point.recorded_at)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _resolve_zone(name: str | None):
    if not name:
        return None
    text = name.strip()
    if not text:
        return None
    if text.upper() in {"UTC", "Z"}:
        return UTC
    offset = parse_offset(text)
    if offset is not None:
        return offset
    try:
        return ZoneInfo(text)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return None
