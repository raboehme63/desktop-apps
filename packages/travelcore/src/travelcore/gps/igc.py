"""Parse IGC flight logs (paragliding / hang gliding). Originals are read-only."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

from travelcore.exceptions import GpsError
from travelcore.gps.parse import ParsedTrack
from travelcore.gps.types import TrackPoint

_IGC_SUFFIXES = {".igc"}
_HEADER_DATE = re.compile(r"(\d{2})[^\d]*(\d{2})[^\d]*(\d{2})")
_PILOT_KEYS = (
    "PLTPILOTINCHARGE",
    "PLTPILOT",
    "PILOTINCHARGE",
    "PILOT",
)


def parse_igc(path: Path) -> tuple[ParsedTrack, ...]:
    """Read B-record fixes from an IGC file.

    An empty but decodable file yields an empty tuple. Unreadable bytes raise
    ``GpsError`` so the caller can record a per-file error and continue.
    """

    if path.suffix.lower() not in _IGC_SUFFIXES:
        return ()
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            text = path.read_text(encoding="latin-1")
        except (OSError, UnicodeDecodeError) as exc:
            raise GpsError(f"IGC-Datei nicht lesbar: {path.name}") from exc
    except OSError as exc:
        raise GpsError(f"IGC-Datei nicht lesbar: {path.name}") from exc

    flight_date: date | None = None
    pilot: str | None = None
    glider: str | None = None
    points: list[TrackPoint] = []
    sequence = 0
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
        stamp = converted[3] + timedelta(days=extra_days)
        if last_stamp is not None and stamp < last_stamp:
            extra_days += 1
            stamp = converted[3] + timedelta(days=extra_days)
        last_stamp = stamp
        points.append(
            TrackPoint(
                latitude=converted[0],
                longitude=converted[1],
                altitude=converted[2],
                recorded_at=stamp,
                track_id="igc-0",
                segment_id=0,
                sequence_index=sequence,
            )
        )
        sequence += 1

    if not points:
        return ()
    name = path.stem
    if glider:
        name = f"{glider} ({path.stem})"
    return (ParsedTrack(name=name, points=tuple(points), format="igc", pilot=pilot),)


def _header_date(line: str) -> date | None:
    upper = line.upper()
    if "DTE" not in upper:
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
    valid = line[24].upper()
    if valid != "A":
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
    altitude = _igc_altitude(line)
    recorded = datetime.combine(flight_date, time(hour, minute, second), tzinfo=UTC)
    return latitude, longitude, altitude, recorded


def _igc_lat(raw: str, hemisphere: str) -> float | None:
    if len(raw) != 7:
        return None
    degrees = int(raw[0:2])
    minutes = int(raw[2:7]) / 1000.0
    value = degrees + minutes / 60.0
    if hemisphere.upper() == "S":
        value = -value
    if not -90.0 <= value <= 90.0:
        return None
    return value


def _igc_lon(raw: str, hemisphere: str) -> float | None:
    if len(raw) != 8:
        return None
    degrees = int(raw[0:3])
    minutes = int(raw[3:8]) / 1000.0
    value = degrees + minutes / 60.0
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
