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
    stack_id: int | None = None
    stack_size: int = 0
    is_stack_key: bool = False
    group_id: int | None = None
    group_size: int = 0
    is_group_key: bool = False
    group_status: str | None = None
    quality_light: str | None = None
    quality_tooltip: str | None = None
    pilot: str | None = None
    width: int | None = None
    height: int | None = None


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
    hidden: bool = False
    items: tuple[TimelinePhoto, ...] = ()
    links: tuple[TimelineLink, ...] = ()
    outbound: TimelineLink | None = None


@dataclass(frozen=True, slots=True)
class TimelineLink:
    """One connection line on a Transfer, in sort order."""

    id: int
    sort_index: int
    geometry: str
    dash: str = "solid"
    symbol: str | None = None
    end_latitude: float | None = None
    end_longitude: float | None = None
    track_source_file_id: int | None = None


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

    @property
    def is_published(self) -> bool:
        """False when the section is hidden from map and export."""

        return self.section is None or not self.section.hidden


@dataclass(frozen=True, slots=True)
class TimelineSnapshot:
    trip_id: int
    title: str
    origin: str
    countries: tuple[str, ...] = field(default_factory=tuple)
    start_date: date | None = None
    end_date: date | None = None
    days: tuple[TimelineDay, ...] = field(default_factory=tuple)
    sections: tuple[TimelineSection, ...] = field(default_factory=tuple)
    entries: tuple[TimelineEntry, ...] = field(default_factory=tuple)

    @property
    def day_count(self) -> int:
        return len(self.days)

    def published_entries(self) -> tuple[TimelineEntry, ...]:
        """Timeline rows that belong to the trip on the map and in export."""

        return tuple(entry for entry in self.entries if entry.is_published)


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
    links: tuple[TimelineLink, ...] = ()
    outbound: TimelineLink | None = None
    hidden: bool = False
