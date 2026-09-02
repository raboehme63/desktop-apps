"""Shared JSON/time helpers for Polar and FIT parsers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


def json_get(node: object, name: str) -> object | None:
    if not isinstance(node, dict):
        return None
    wanted = name.lower()
    for key, value in node.items():
        if str(key).lower() == wanted:
            return value
    return None


def json_first(node: object, *names: str) -> object | None:
    for name in names:
        value = json_get(node, name)
        if value is not None:
            return value
    return None


def as_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def as_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def as_int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_time(value: object) -> datetime | None:
    text = as_text(value)
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def as_utc(value: datetime | None, offset_minutes: int | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(UTC)
    if offset_minutes is None:
        return value.replace(tzinfo=UTC)
    return (value - timedelta(minutes=offset_minutes)).replace(tzinfo=UTC)


def gpx_time(value: datetime) -> str:
    stamp = value.astimezone(UTC).replace(microsecond=0)
    return stamp.strftime("%Y-%m-%dT%H:%M:%SZ")


def format_coord(value: float) -> str:
    return f"{value:.8f}".rstrip("0").rstrip(".")


def format_number(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return f"{value:.3f}".rstrip("0").rstrip(".")
