"""Turn any Polar JSON object into one or more parsed documents."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fitnesscore.parse.classify import (
    KIND_ACTIVITY_DAY,
    KIND_OHR,
    KIND_PLANNED_ROUTE,
    KIND_TRAINING_SESSION,
)
from fitnesscore.parse.common import as_float, as_int, as_text, as_utc, json_get, parse_time
from fitnesscore.parse.routes import tracks_from_json, tracks_from_planned
from fitnesscore.parse.types import ParsedDocument
from fitnesscore.sports import SportRef, resolve_sport


def documents_from_json(data: object, *, kind: str, filename: str) -> tuple[ParsedDocument, ...]:
    if kind == KIND_TRAINING_SESSION:
        return (_training_document(data),)
    if kind == KIND_PLANNED_ROUTE:
        return (_planned_document(data),)
    if kind == KIND_ACTIVITY_DAY:
        return (_activity_day(data, filename),)
    if kind == KIND_OHR:
        return (_dated_file_document(kind, data, filename, title="24/7 HR"),)
    return (_generic_document(kind, data, filename),)


def _training_document(data: object) -> ParsedDocument:
    offset = as_int(json_get(data, "timezoneOffsetMinutes")) if isinstance(data, dict) else None
    start = as_utc(parse_time(json_get(data, "startTime")), offset) if isinstance(data, dict) else None
    stop = as_utc(parse_time(json_get(data, "stopTime")), offset) if isinstance(data, dict) else None
    title = as_text(json_get(data, "name")) if isinstance(data, dict) else ""
    polar_id, sport_name = _polar_sport(data)
    sport = resolve_sport(polar_id=polar_id, name=sport_name or title or None)
    duration_ms = as_float(json_get(data, "durationMillis")) if isinstance(data, dict) else None
    distance = as_float(json_get(data, "distanceMeters")) if isinstance(data, dict) else None
    calories = as_float(json_get(data, "calories")) if isinstance(data, dict) else None
    hr_avg = as_float(json_get(data, "hrAvg")) if isinstance(data, dict) else None
    hr_max = as_float(json_get(data, "hrMax")) if isinstance(data, dict) else None
    identifier = as_text(json_get(data, "identifier")) if isinstance(data, dict) else ""
    ascent, descent = _ascent_descent(data)
    return ParsedDocument(
        kind=KIND_TRAINING_SESSION,
        title=title,
        external_id=identifier or None,
        started_at=start,
        ended_at=stop,
        sport_slug=_slug(sport),
        sport_raw=sport.raw if sport else (sport_name or title or None),
        polar_sport_id=polar_id,
        distance_m=distance,
        duration_s=duration_ms / 1000.0 if duration_ms is not None else _duration_s(start, stop),
        ascent_m=ascent,
        descent_m=descent,
        calories=calories,
        hr_avg=hr_avg,
        hr_max=hr_max,
        tracks=tracks_from_json(data),
    )


def _planned_document(data: object) -> ParsedDocument:
    title = as_text(json_get(data, "name")) if isinstance(data, dict) else ""
    external = as_text(json_get(data, "id")) if isinstance(data, dict) else ""
    distance = as_float(json_get(data, "distance")) if isinstance(data, dict) else None
    return ParsedDocument(
        kind=KIND_PLANNED_ROUTE,
        title=title,
        external_id=external or None,
        distance_m=distance,
        tracks=tracks_from_planned(data),
    )


def _activity_day(data: object, filename: str) -> ParsedDocument:
    raw_date = json_get(data, "date") if isinstance(data, dict) else None
    started = as_utc(parse_time(raw_date), 0) if raw_date else _date_from_filename(filename)
    return ParsedDocument(
        kind=KIND_ACTIVITY_DAY,
        title=as_text(raw_date) or filename,
        started_at=started,
    )


def _dated_file_document(kind: str, data: object, filename: str, *, title: str) -> ParsedDocument:
    start = parse_time(json_get(data, "startTime")) if isinstance(data, dict) else None
    offset = as_int(json_get(data, "timezoneOffsetMinutes")) if isinstance(data, dict) else None
    started = as_utc(start, offset)
    if started is None:
        started = _date_from_filename(filename)
    return ParsedDocument(kind=kind, title=title, started_at=started)


def _generic_document(kind: str, data: object, filename: str) -> ParsedDocument:
    start = None
    title = filename
    external = None
    if isinstance(data, dict):
        offset = as_int(json_get(data, "timezoneOffsetMinutes"))
        start = as_utc(parse_time(json_get(data, "startTime")), offset)
        title = as_text(json_get(data, "name")) or filename
        external = as_text(json_get(data, "id") or json_get(data, "identifier")) or None
    if start is None:
        start = _date_from_filename(filename)
    return ParsedDocument(kind=kind, title=title, external_id=external, started_at=start)


def _polar_sport(data: object) -> tuple[str | None, str | None]:
    if not isinstance(data, dict):
        return None, None
    sport = json_get(data, "sport")
    polar_id, name = _sport_fields(sport)
    if polar_id or name:
        return polar_id, name
    exercises = json_get(data, "exercises")
    if isinstance(exercises, list) and exercises and isinstance(exercises[0], dict):
        return _sport_fields(json_get(exercises[0], "sport"))
    return None, None


def _sport_fields(sport: object) -> tuple[str | None, str | None]:
    if isinstance(sport, str):
        return None, sport
    if isinstance(sport, dict):
        polar_id = as_text(json_get(sport, "id")) or None
        name = as_text(json_get(sport, "name") or json_get(sport, "sport")) or None
        return polar_id, name
    return None, None


def _ascent_descent(data: object) -> tuple[float | None, float | None]:
    if not isinstance(data, dict):
        return None, None
    exercises = json_get(data, "exercises")
    if isinstance(exercises, list) and exercises and isinstance(exercises[0], dict):
        first = exercises[0]
        return as_float(json_get(first, "ascentMeters")), as_float(json_get(first, "descentMeters"))
    return None, None


def _duration_s(start: datetime | None, stop: datetime | None) -> float | None:
    if start is None or stop is None:
        return None
    return (stop - start).total_seconds()


def _slug(sport: SportRef | None) -> str | None:
    return sport.slug if sport else None


def _date_from_filename(filename: str) -> datetime | None:
    stem = Path(filename).stem
    digits: list[str] = []
    for part in stem.replace("T", "-").replace("_", "-").split("-"):
        if part.isdigit() and len(part) in {2, 4}:
            digits.append(part)
        if len(digits) >= 3 and len(digits[0]) == 4:
            try:
                year, month, day = int(digits[0]), int(digits[1]), int(digits[2])
                return datetime(year, month, day, tzinfo=UTC)
            except ValueError:
                return None
    if len(digits) >= 2 and len(digits[0]) == 4:
        try:
            return datetime(int(digits[0]), int(digits[1]), 1, tzinfo=UTC)
        except ValueError:
            return None
    return None
