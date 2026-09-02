"""Parsed documents and tracks before they are stored."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True, slots=True)
class RoutePoint:
    latitude: float
    longitude: float
    elevation: float | None
    recorded_at: datetime | None


@dataclass(frozen=True, slots=True)
class ParsedTrack:
    name: str
    points: tuple[RoutePoint, ...]


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    kind: str
    title: str = ""
    external_id: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    sport_slug: str | None = None
    sport_raw: str | None = None
    polar_sport_id: str | None = None
    distance_m: float | None = None
    duration_s: float | None = None
    ascent_m: float | None = None
    descent_m: float | None = None
    calories: float | None = None
    hr_avg: float | None = None
    hr_max: float | None = None
    tracks: tuple[ParsedTrack, ...] = field(default_factory=tuple)

    @property
    def dedup_key(self) -> str | None:
        if self.kind not in {"training_session", "fit_activity", "igc_flight"}:
            return None
        if self.started_at is None:
            return None
        stamp = self.started_at.replace(second=0, microsecond=0).isoformat()
        sport = self.sport_slug or ""
        return f"{stamp}|{sport}"
