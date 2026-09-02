"""Parse Polar/Garmin FIT activity files into documents and tracks."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from typing import Any

import fitdecode

from fitnesscore.parse.classify import KIND_FIT_ACTIVITY
from fitnesscore.parse.types import ParsedDocument, ParsedTrack, RoutePoint
from fitnesscore.sports import resolve_sport

SEMICIRCLE_TO_DEG = 180.0 / 2**31


@dataclass(frozen=True, slots=True)
class FitRecordPoint:
    recorded_at: datetime | None
    latitude: float | None
    longitude: float | None
    elevation: float | None


@dataclass(frozen=True, slots=True)
class FitSession:
    sport: str | None
    sub_sport: str | None
    start_time: datetime | None
    end_time: datetime | None
    elapsed_s: float | None
    timer_s: float | None
    distance_m: float | None
    ascent_m: float | None
    descent_m: float | None
    calories: float | None
    hr_avg: float | None
    hr_max: float | None


def semicircle_to_deg(value: float | int) -> float:
    return float(value) * SEMICIRCLE_TO_DEG


def documents_from_fit(payload: bytes) -> tuple[ParsedDocument, ...]:
    sessions, points = read_fit(payload)
    if not sessions:
        return (
            ParsedDocument(
                kind=KIND_FIT_ACTIVITY,
                title="FIT activity",
                tracks=_track_from_points("FIT", points),
            ),
        )
    documents: list[ParsedDocument] = []
    for session in sessions:
        sport = resolve_sport(fit_sport=session.sport, fit_sub_sport=session.sub_sport)
        window = points_for_session(points, session)
        title = sport.slug if sport else (session.sport or "FIT")
        documents.append(
            ParsedDocument(
                kind=KIND_FIT_ACTIVITY,
                title=title,
                started_at=session.start_time,
                ended_at=session.end_time,
                sport_slug=sport.slug if sport else None,
                sport_raw=sport.raw if sport else session.sport,
                distance_m=session.distance_m,
                duration_s=session.timer_s or session.elapsed_s,
                ascent_m=session.ascent_m,
                descent_m=session.descent_m,
                calories=session.calories,
                hr_avg=session.hr_avg,
                hr_max=session.hr_max,
                tracks=_track_from_points(title, window),
            )
        )
    return tuple(documents)


def read_fit(payload: bytes) -> tuple[list[FitSession], list[FitRecordPoint]]:
    sessions: list[FitSession] = []
    points: list[FitRecordPoint] = []
    with fitdecode.FitReader(BytesIO(payload)) as reader:
        for frame in reader:
            if not isinstance(frame, fitdecode.FitDataMessage):
                continue
            name = frame.name or ""
            if name == "session":
                sessions.append(_session_from_frame(frame))
            elif name == "record":
                points.append(_point_from_frame(frame))
    return sessions, points


def points_for_session(points: Iterable[FitRecordPoint], session: FitSession) -> list[FitRecordPoint]:
    start = session.start_time
    end = session.end_time
    chosen: list[FitRecordPoint] = []
    for point in points:
        stamp = point.recorded_at
        if stamp is None:
            continue
        if start is not None and stamp < start:
            continue
        if end is not None and stamp > end:
            continue
        chosen.append(point)
    return chosen


def _track_from_points(name: str, points: Iterable[FitRecordPoint]) -> tuple[ParsedTrack, ...]:
    route: list[RoutePoint] = []
    for point in points:
        if point.latitude is None or point.longitude is None:
            continue
        route.append(
            RoutePoint(
                latitude=point.latitude,
                longitude=point.longitude,
                elevation=point.elevation,
                recorded_at=point.recorded_at,
            )
        )
    if not route:
        return ()
    return (ParsedTrack(name=name, points=tuple(route)),)


def _session_from_frame(frame: Any) -> FitSession:
    return FitSession(
        sport=_text_field(frame, "sport"),
        sub_sport=_text_field(frame, "sub_sport"),
        start_time=_field(frame, "start_time"),
        end_time=_field(frame, "timestamp"),
        elapsed_s=_as_float(_field(frame, "total_elapsed_time")),
        timer_s=_as_float(_field(frame, "total_timer_time")),
        distance_m=_as_float(_field(frame, "total_distance")),
        ascent_m=_as_float(_field(frame, "total_ascent")),
        descent_m=_as_float(_field(frame, "total_descent")),
        calories=_as_float(_field(frame, "total_calories")),
        hr_avg=_as_float(_field(frame, "avg_heart_rate")),
        hr_max=_as_float(_field(frame, "max_heart_rate")),
    )


def _point_from_frame(frame: Any) -> FitRecordPoint:
    lat = _field(frame, "position_lat")
    lon = _field(frame, "position_long")
    elevation = _field(frame, "enhanced_altitude")
    if elevation is None:
        elevation = _field(frame, "altitude")
    return FitRecordPoint(
        recorded_at=_field(frame, "timestamp"),
        latitude=semicircle_to_deg(lat) if lat is not None else None,
        longitude=semicircle_to_deg(lon) if lon is not None else None,
        elevation=_as_float(elevation),
    )


def _text_field(frame: Any, name: str) -> str | None:
    value = _field(frame, name)
    if value is None:
        return None
    return str(value)


def _field(frame: Any, name: str) -> Any:
    if not frame.has_field(name):
        return None
    try:
        return frame.get_value(name)
    except Exception:  # noqa: BLE001 - fitdecode raises several types for missing/invalid fields
        return None


def _as_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
