"""Capture-time parsing and source priority.

EXIF times without an offset stay naive. The library never attaches UTC in that
case; ``timezone_unknown`` remains True.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from travelcore.metadata.provider import TIME_SOURCE_PRIORITY, CapturedTime

_EXIF_DATETIME = re.compile(
    r"^(?P<year>\d{4})[:\-](?P<month>\d{2})[:\-](?P<day>\d{2})[ T]"
    r"(?P<hour>\d{2}):(?P<minute>\d{2}):(?P<second>\d{2})"
    r"(?:\.(?P<fraction>\d+))?"
    r"(?P<offset>Z|[+-]\d{2}:?\d{2})?$"
)
_OFFSET = re.compile(r"^(?P<sign>[+-])(?P<hours>\d{2}):?(?P<minutes>\d{2})$")


def parse_offset(value: str | None) -> timezone | None:
    """Parse an EXIF offset such as ``+02:00`` or ``+0200``. ``Z`` means UTC."""

    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if text.upper() == "Z":
        return UTC
    match = _OFFSET.match(text)
    if match is None:
        return None
    hours = int(match.group("hours"))
    minutes = int(match.group("minutes"))
    delta = timedelta(hours=hours, minutes=minutes)
    if match.group("sign") == "-":
        delta = -delta
    return timezone(delta)


def parse_exif_datetime(value: str | None, *, offset: str | None = None) -> CapturedTime | None:
    """Parse an EXIF/XMP datetime string into a CapturedTime.

    If neither the value nor ``offset`` contains a timezone, the result is naive
    and ``timezone_unknown`` is True.
    """

    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    match = _EXIF_DATETIME.match(text)
    if match is None:
        return None
    try:
        parsed = datetime(
            int(match.group("year")),
            int(match.group("month")),
            int(match.group("day")),
            int(match.group("hour")),
            int(match.group("minute")),
            int(match.group("second")),
        )
    except ValueError:
        return None

    embedded = match.group("offset")
    tzinfo = parse_offset(embedded) if embedded else parse_offset(offset)
    if tzinfo is not None:
        parsed = parsed.replace(tzinfo=tzinfo)
        tz_name = embedded or (offset.strip() if offset else None)
        if tz_name and tz_name.upper() == "Z":
            tz_name = "UTC"
        return CapturedTime(
            raw_value=text,
            normalized=parsed,
            timezone_name=tz_name,
            timezone_unknown=False,
            source="",
        )
    return CapturedTime(
        raw_value=text,
        normalized=parsed,
        timezone_name=None,
        timezone_unknown=True,
        source="",
    )


def with_source(captured: CapturedTime, source: str) -> CapturedTime:
    return CapturedTime(
        raw_value=captured.raw_value,
        normalized=captured.normalized,
        timezone_name=captured.timezone_name,
        timezone_unknown=captured.timezone_unknown,
        source=source,
    )


def choose_captured_time(candidates: dict[str, CapturedTime | None]) -> CapturedTime | None:
    """Pick the first usable time according to ``TIME_SOURCE_PRIORITY``."""

    for source in TIME_SOURCE_PRIORITY:
        candidate = candidates.get(source)
        if candidate is None or candidate.normalized is None:
            continue
        return candidate if candidate.source == source else with_source(candidate, source)
    return None


def filesystem_captured_time(path: Path) -> CapturedTime | None:
    """Use the file's modification time as a naive local wall clock.

    POSIX timestamps are instants, but the travel timezone is unknown. The
    value is therefore stored naive in the local timezone of this computer
    and flagged as timezone-unknown — never labelled as UTC.
    """

    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    naive = datetime.fromtimestamp(mtime)
    return CapturedTime(
        raw_value=naive.isoformat(sep=" ", timespec="seconds"),
        normalized=naive,
        timezone_name=None,
        timezone_unknown=True,
        source="filesystem_mtime",
    )
