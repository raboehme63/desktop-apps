"""Parse IGC flight logs into a fitness document and GPX track."""

from __future__ import annotations

import math
import re
from datetime import UTC, date, datetime, time, timedelta

from fitnesscore.parse.classify import KIND_IGC_FLIGHT
from fitnesscore.parse.types import ParsedDocument, ParsedTrack, RoutePoint
from fitnesscore.sports import resolve_igc_sport

_HEADER_DATE = re.compile(r"(\d{2})[^\d]*(\d{2})[^\d]*(\d{2})")
_PILOT_KEYS = (
    "PLTPILOTINCHARGE",
    "PLTPILOT",
    "PILOTINCHARGE",
    "PILOT",
)
_EARTH_M = 6_371_000.0


def documents_from_igc(payload: bytes, *, filename: str) -> tuple[ParsedDocument, ...]:
    text = _decode(payload)
    flight_date, pilot, glider, points = _parse_text(text)
    if not points:
        sport = resolve_igc_sport(glider)
        return (
            ParsedDocument(
                kind=KIND_IGC_FLIGHT,
                title=_title(filename, glider, pilot),
                started_at=datetime.combine(flight_date, time.min, tzinfo=UTC) if flight_date else None,
                sport_slug=sport.slug,
                sport_raw=sport.raw,
            ),
        )
    started = points[0].recorded_at
    ended = points[-1].recorded_at
    duration = None
    if started is not None and ended is not None:
        duration = (ended - started).total_seconds()
    sport = resolve_igc_sport(glider)
    name = _title(filename, glider, pilot)
    return (
        ParsedDocument(
            kind=KIND_IGC_FLIGHT,
            title=name,
            started_at=started,
            ended_at=ended,
            sport_slug=sport.slug,
            sport_raw=sport.raw,
            distance_m=_distance_m(points),
            duration_s=duration,
            ascent_m=_ascent_m(points),
            tracks=(ParsedTrack(name=name, points=tuple(points)),),
        ),
    )


def _decode(payload: bytes) -> str:
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError:
        return payload.decode("latin-1")


def _parse_text(text: str) -> tuple[date | None, str | None, str | None, list[RoutePoint]]:
    flight_date: date | None = None
    pilot: str | None = None
    glider: str | None = None
    points: list[RoutePoint] = []
    last_stamp: datetime | None = None
    extra_days = 0
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        kind = line[0].upper()
        if kind == "H":
            if flight_date is None:
                flight_date = _header_date(line)
            if pilot is None:
                pilot = _header_pilot(line)
            if glider is None:
                glider = _header_glider(line)
            continue
        if kind != "B":
            continue
        converted = _b_record(line, flight_date=flight_date or date(1970, 1, 1))
        if converted is None:
            continue
        lat, lon, ele, stamp = converted
        stamp = stamp + timedelta(days=extra_days)
        if last_stamp is not None and stamp < last_stamp:
            extra_days += 1
            stamp = converted[3] + timedelta(days=extra_days)
        last_stamp = stamp
        points.append(RoutePoint(latitude=lat, longitude=lon, elevation=ele, recorded_at=stamp))
    return flight_date, pilot, glider, points


def _title(filename: str, glider: str | None, pilot: str | None) -> str:
    stem = filename.rsplit(".", 1)[0] if filename else "IGC"
    if glider and pilot:
        return f"{glider} ({pilot})"
    if glider:
        return f"{glider} ({stem})"
    if pilot:
        return f"{pilot} ({stem})"
    return stem


def _header_date(line: str) -> date | None:
    if "DTE" not in line.upper():
        return None
    match = _HEADER_DATE.search(line)
    if match is None:
        return None
    day = int(match.group(1))
    month = int(match.group(2))
    year = int(match.group(3))
    year = 1900 + year if year >= 80 else 2000 + year
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _header_pilot(line: str) -> str | None:
    upper = line.upper().replace(" ", "")
    if not any(key in upper for key in _PILOT_KEYS):
        return None
    if ":" not in line:
        return None
    value = line.split(":", 1)[1].strip()
    return value or None


def _header_glider(line: str) -> str | None:
    upper = line.upper().replace(" ", "")
    if "GTYGLIDERTYPE" not in upper and "GLIDERTYPE" not in upper:
        return None
    if ":" not in line:
        return None
    value = line.split(":", 1)[1].strip()
    return value or None


def _b_record(line: str, *, flight_date: date) -> tuple[float, float, float | None, datetime] | None:
    if len(line) < 35:
        return None
    if line[24].upper() != "A":
        return None
    try:
        hour = int(line[1:3])
        minute = int(line[3:5])
        second = int(line[5:7])
        latitude = _igc_lat(line[7:14], line[14])
        longitude = _igc_lon(line[15:23], line[23])
    except (TypeError, ValueError):
        return None
    if latitude is None or longitude is None:
        return None
    recorded = datetime.combine(flight_date, time(hour, minute, second), tzinfo=UTC)
    return latitude, longitude, _igc_altitude(line), recorded


def _igc_lat(raw: str, hemisphere: str) -> float | None:
    if len(raw) != 7:
        return None
    value = int(raw[0:2]) + int(raw[2:7]) / 1000.0 / 60.0
    if hemisphere.upper() == "S":
        value = -value
    if not -90.0 <= value <= 90.0:
        return None
    return value


def _igc_lon(raw: str, hemisphere: str) -> float | None:
    if len(raw) != 8:
        return None
    value = int(raw[0:3]) + int(raw[3:8]) / 1000.0 / 60.0
    if hemisphere.upper() == "W":
        value = -value
    if not -180.0 <= value <= 180.0:
        return None
    return value


def _igc_altitude(line: str) -> float | None:
    if len(line) < 35:
        return None
    gnss = _signed_meters(line[30:35])
    if gnss is not None:
        return gnss
    return _signed_meters(line[25:30])


def _signed_meters(raw: str) -> float | None:
    text = raw.strip()
    if not text or not re.fullmatch(r"-?\d+", text):
        return None
    try:
        return float(int(text))
    except ValueError:
        return None


def _distance_m(points: list[RoutePoint]) -> float | None:
    if len(points) < 2:
        return None
    total = 0.0
    previous = points[0]
    for point in points[1:]:
        total += _haversine_m(previous.latitude, previous.longitude, point.latitude, point.longitude)
        previous = point
    return total


def _ascent_m(points: list[RoutePoint]) -> float | None:
    previous: float | None = None
    climbed = 0.0
    seen = False
    for point in points:
        if point.elevation is None:
            continue
        seen = True
        if previous is not None and point.elevation > previous:
            climbed += point.elevation - previous
        previous = point.elevation
    return climbed if seen else None


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    return 2 * _EARTH_M * math.atan2(math.sqrt(a), math.sqrt(1 - a))
