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
    file_kind: str = "photo"
    external_url: str | None = None
    sort_status: str | None = None
    rotation_degrees: int = 0
    journal_at: datetime | None = None
    journal_timezone_name: str | None = None
    display_latitude: float | None = None
    display_longitude: float | None = None
    position_inherited: bool = False


@dataclass(frozen=True, slots=True)
class TimelinePlace:
    id: int
    name: str
    latitude: float | None
    longitude: float | None
    confirmed: bool
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
    youtube_urls: tuple[str, ...] = ()
    leonardo_urls: tuple[str, ...] = ()
    cover_source_file_id: int | None = None
    photos: tuple[TimelinePhoto, ...] = ()
    places: tuple[TimelinePlace, ...] = ()
    events: tuple[TimelineEvent, ...] = ()


@dataclass(frozen=True, slots=True)
class TimelineSection:
    id: int
    kind: str
    mode: str | None
    title: str | None
    notes: str | None
    started_at: datetime | None
    ended_at: datetime | None
    location_name: str | None
    location_from: str | None
    location_to: str | None
    origin: str
    youtube_urls: tuple[str, ...] = ()
    leonardo_urls: tuple[str, ...] = ()
    cover_source_file_id: int | None = None
    pin_latitude: float | None = None
    pin_longitude: float | None = None
    items: tuple[TimelinePhoto, ...] = ()


@dataclass(frozen=True, slots=True)
class TimelineEntry:
    """One row in the journal feed: a Tag, Aufenthalt, or Transfer section."""

    started_at: datetime | None
    section: TimelineSection | None = None
    leftover_day: TimelineDay | None = None

    @property
    def is_section(self) -> bool:
        return self.section is not None

    @property
    def card_kind(self) -> str:
        """Map/timeline type: ``day``, ``stay``, or ``movement``."""

        if self.section is not None:
            return self.section.kind
        return "day"


@dataclass(frozen=True, slots=True)
class TimelineSnapshot:
    trip_id: int
    title: str
    origin: str
    days: tuple[TimelineDay, ...] = field(default_factory=tuple)
    sections: tuple[TimelineSection, ...] = field(default_factory=tuple)
    entries: tuple[TimelineEntry, ...] = field(default_factory=tuple)

    @property
    def day_count(self) -> int:
        return len(self.days)


@dataclass
class PendingSectionSpec:
    """In-memory section that is only written when the user saves the timeline."""

    local_id: int
    source_file_ids: tuple[int, ...]
    kind: str
    mode: str | None = None
    title: str | None = None
    notes: str | None = None
    location_name: str | None = None
    location_from: str | None = None
    location_to: str | None = None
    youtube_urls: tuple[str, ...] = ()
    leonardo_urls: tuple[str, ...] = ()
    cover_source_file_id: int | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
