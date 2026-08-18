"""Read models for the chronological trip timeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class TimelinePhoto:
    source_file_id: int
    filename: str
    path: str
    thumbnail_path: Path
    captured_at: datetime | None
    used_in_journal: bool
    is_cover: bool
    is_favorite: bool
    gps_latitude: float | None
    gps_longitude: float | None


@dataclass(frozen=True, slots=True)
class TimelinePlace:
    id: int
    name: str
    latitude: float | None
    longitude: float | None
    confirmed: bool
    origin: str


@dataclass(frozen=True, slots=True)
class TimelineStay:
    id: int
    name: str
    location_name: str | None
    stayed_on: datetime | None
    latitude: float | None
    longitude: float | None
    description: str | None
    origin: str


@dataclass(frozen=True, slots=True)
class TimelineEvent:
    id: int
    title: str
    occurred_at: datetime | None
    origin: str


@dataclass(frozen=True, slots=True)
class TimelineDay:
    id: int
    day_index: int
    date: date | None
    title: str | None
    notes: str | None
    origin: str
    photos: tuple[TimelinePhoto, ...] = ()
    places: tuple[TimelinePlace, ...] = ()
    stays: tuple[TimelineStay, ...] = ()
    events: tuple[TimelineEvent, ...] = ()


@dataclass(frozen=True, slots=True)
class TimelineSnapshot:
    trip_id: int
    title: str
    origin: str
    days: tuple[TimelineDay, ...] = field(default_factory=tuple)

    @property
    def day_count(self) -> int:
        return len(self.days)
