"""Travelbook page sequence for renderers (PDF first; HTML later).

One ``BookPage`` is one sheet. Spreads in the editor become two consecutive pages.
Hidden timeline sections are omitted, matching the map and the Qt preview.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from travelcore.export.document import (
    PhotoElement,
    TravelbookDocument,
    book_media_items,
    layout_is_photos,
    sync_document,
)
from travelcore.export.stats import trip_summary_metrics
from travelcore.geo.catalog import country_at
from travelcore.timeline.types import TimelineEntry, TimelinePhoto, TimelineSection, TimelineSnapshot

KIND_COVER = "cover"
KIND_BLANK = "blank"
KIND_TITLE = "title"
KIND_SUMMARY_COUNTRIES = "summary_countries"
KIND_SUMMARY_MAP = "summary_map"
KIND_INTRO = "intro"
KIND_PHOTOS = "photos"
KIND_JOURNAL = "journal"

_KIND_LABELS = {"day": "Tag", "stay": "Aufenthalt", "movement": "Transfer"}
_PHOTO_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp"}


@dataclass(frozen=True, slots=True)
class BookPage:
    """One printable sheet of a Travelbook."""

    kind: str
    number: int | None = None
    title: str = ""
    kicker: str = ""
    year: str = ""
    notes: str = ""
    dates: str = ""
    cover_id: int | None = None
    elements: tuple[PhotoElement, ...] = ()
    countries: tuple[str, ...] = ()
    metrics: tuple[tuple[str, str], ...] = ()
    country: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    span_start: float = 0.0
    span_end: float = 0.0


def format_book_dates(started_at: datetime | None, ended_at: datetime | None) -> str:
    """Section intro dates: ``01.01.1900`` or ``01.01.1900 bis 22.02.1900``."""

    start = started_at
    end = ended_at or started_at
    if start is None:
        return ""
    start_day = start.date()
    end_day = end.date() if end is not None else start_day
    if start_day == end_day:
        return start_day.strftime("%d.%m.%Y")
    return f"{start_day.strftime('%d.%m.%Y')} bis {end_day.strftime('%d.%m.%Y')}"


def book_pages(document: TravelbookDocument, snapshot: TimelineSnapshot) -> tuple[BookPage, ...]:
    """Cover, title spread, trip summary, then every stored chronicle spread."""

    synced = sync_document(document, snapshot, page_size=document.page_size)
    entries = snapshot.published_entries()
    title = (snapshot.title or "").strip() or "Reise"
    year = _year(entries)
    cover_id = _first_cover_id(entries)
    trip_start, trip_end = _trip_dates(snapshot)
    metrics = trip_summary_metrics(snapshot)
    countries = snapshot.countries
    by_section = {entry.section.id: entry for entry in entries if entry.section is not None}
    pages: list[BookPage] = [
        BookPage(kind=KIND_COVER, title=title.upper(), year=str(year) if year else "", cover_id=cover_id),
        BookPage(kind=KIND_BLANK),
        BookPage(kind=KIND_TITLE, title=title),
        BookPage(
            kind=KIND_SUMMARY_COUNTRIES,
            number=1,
            countries=countries,
            metrics=metrics,
        ),
        BookPage(kind=KIND_SUMMARY_MAP, number=2, cover_id=cover_id),
    ]
    number = 3
    for chapter in synced.chapters:
        entry = by_section.get(chapter.section_id)
        if entry is None or entry.section is None:
            continue
        context = _section_context(entry, snapshot, trip_start, trip_end)
        for spread in chapter.spreads:
            pages.append(_page_from_instance(spread.verso, context, number))
            pages.append(_page_from_instance(spread.recto, context, number + 1))
            number += 2
    return tuple(pages)


def media_index(snapshot: TimelineSnapshot) -> dict[int, TimelinePhoto]:
    """source_file_id → media row, including pool days (for path lookup)."""

    found: dict[int, TimelinePhoto] = {}
    for entry in snapshot.entries:
        section = entry.section
        if section is None:
            continue
        for item in section.items:
            found.setdefault(item.source_file_id, item)
    for day in snapshot.days:
        for item in day.photos:
            found.setdefault(item.source_file_id, item)
    return found


def resolve_export_source(item: TimelinePhoto) -> Path:
    """Prefer a Pillow-readable original; otherwise the thumbnail. Never writes."""

    original = Path(item.path)
    thumb = item.thumbnail_path
    if item.file_kind == "photo" and original.is_file() and original.suffix.lower() in _PHOTO_SUFFIXES:
        return original
    if thumb.is_file():
        return thumb
    return original


def export_sources(snapshot: TimelineSnapshot) -> dict[int, Path]:
    return {item.source_file_id: resolve_export_source(item) for item in media_index(snapshot).values()}


def export_rotations(snapshot: TimelineSnapshot) -> dict[int, int]:
    return {item.source_file_id: item.rotation_degrees for item in media_index(snapshot).values()}


@dataclass(frozen=True, slots=True)
class _SectionContext:
    kicker: str
    title: str
    notes: str
    dates: str
    cover_id: int | None
    country: str | None
    latitude: float | None
    longitude: float | None
    span_start: float
    span_end: float
    fallback_elements: tuple[PhotoElement, ...] = field(default_factory=tuple)


def _page_from_instance(page, context: _SectionContext, number: int) -> BookPage:
    layout = page.layout
    if layout == "section_intro":
        return BookPage(
            kind=KIND_INTRO,
            number=number,
            title=context.title,
            kicker=context.kicker,
            notes=context.notes,
            dates=context.dates,
            cover_id=context.cover_id,
            country=context.country,
            latitude=context.latitude,
            longitude=context.longitude,
            span_start=context.span_start,
            span_end=context.span_end,
        )
    if layout == "journal":
        return BookPage(
            kind=KIND_JOURNAL,
            number=number,
            title=context.title,
            notes=context.notes,
        )
    if layout_is_photos(layout):
        return BookPage(kind=KIND_PHOTOS, number=number, elements=page.elements)
    return BookPage(kind=KIND_BLANK, number=number)


def _section_context(
    entry: TimelineEntry,
    snapshot: TimelineSnapshot,
    trip_start: date | None,
    trip_end: date | None,
) -> _SectionContext:
    section = entry.section
    assert section is not None
    cover_id = section.cover_source_file_id
    if cover_id is None:
        media = book_media_items(section)
        cover_id = media[0].source_file_id if media else None
    iso, latitude, longitude = _section_place(section, snapshot.countries)
    start, end = _span_fracs(section.started_at, section.ended_at, trip_start, trip_end)
    heading = (section.title or "").strip() or _KIND_LABELS.get(entry.card_kind, "Abschnitt")
    return _SectionContext(
        kicker=_KIND_LABELS.get(entry.card_kind, "Abschnitt"),
        title=heading,
        notes=(section.notes or "").strip(),
        dates=format_book_dates(section.started_at, section.ended_at),
        cover_id=cover_id,
        country=iso,
        latitude=latitude,
        longitude=longitude,
        span_start=start,
        span_end=end,
    )


def _year(entries: tuple[TimelineEntry, ...]) -> int | None:
    for entry in entries:
        started = entry.section.started_at if entry.section is not None else None
        if started is not None:
            return started.year
    return None


def _first_cover_id(entries: tuple[TimelineEntry, ...]) -> int | None:
    for entry in entries:
        section = entry.section
        if section is None:
            continue
        if section.cover_source_file_id is not None:
            return section.cover_source_file_id
        media = book_media_items(section)
        if media:
            return media[0].source_file_id
    return None


def _trip_dates(snapshot: TimelineSnapshot) -> tuple[date | None, date | None]:
    start = snapshot.start_date
    end = snapshot.end_date
    starts: list[date] = []
    ends: list[date] = []
    for entry in snapshot.published_entries():
        section = entry.section
        if section is None:
            continue
        if section.started_at is not None:
            starts.append(section.started_at.date())
        if section.ended_at is not None:
            ends.append(section.ended_at.date())
        elif section.started_at is not None:
            ends.append(section.started_at.date())
    if start is None and starts:
        start = min(starts)
    if end is None and ends:
        end = max(ends)
    if start is not None and end is not None and end < start:
        return end, start
    return start, end


def _span_fracs(
    started_at: datetime | None,
    ended_at: datetime | None,
    trip_start: date | None,
    trip_end: date | None,
) -> tuple[float, float]:
    if trip_start is None or trip_end is None:
        return 0.0, 1.0
    total = (trip_end - trip_start).days
    if total <= 0:
        return 0.0, 1.0
    start_day = started_at.date() if started_at is not None else trip_start
    end_day = ended_at.date() if ended_at is not None else start_day
    start_day = min(max(start_day, trip_start), trip_end)
    end_day = min(max(end_day, trip_start), trip_end)
    return (start_day - trip_start).days / total, (end_day - trip_start).days / total


def _section_place(
    section: TimelineSection,
    trip_countries: tuple[str, ...],
) -> tuple[str | None, float | None, float | None]:
    pos = _section_position(section)
    if pos is not None:
        found = country_at(pos[0], pos[1], preferred=trip_countries)
        return (found.iso2 if found is not None else None), pos[0], pos[1]
    if len(trip_countries) == 1:
        return trip_countries[0], None, None
    return None, None, None


def _section_position(section: TimelineSection) -> tuple[float, float] | None:
    if section.pin_latitude is not None and section.pin_longitude is not None:
        return (section.pin_latitude, section.pin_longitude)
    cover_id = section.cover_source_file_id
    if cover_id is not None:
        for item in section.items:
            if item.source_file_id == cover_id:
                pos = _item_position(item)
                if pos is not None:
                    return pos
    for item in section.items:
        pos = _item_position(item)
        if pos is not None:
            return pos
    return None


def _item_position(item: TimelinePhoto) -> tuple[float, float] | None:
    if item.display_latitude is not None and item.display_longitude is not None:
        return (item.display_latitude, item.display_longitude)
    if item.gps_latitude is not None and item.gps_longitude is not None:
        return (item.gps_latitude, item.gps_longitude)
    return None
