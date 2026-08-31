"""Travelbook trip-summary figures from a timeline snapshot."""

from __future__ import annotations

from datetime import date

from travelcore.media.gallery import SORT_REJECTED
from travelcore.timeline.links import is_igc_filename
from travelcore.timeline.types import TimelinePhoto, TimelineSnapshot

METRIC_LABELS = (
    ("duration_days", "Tage"),
    ("section_count", "Reiseabschnitte"),
    ("photo_count", "Fotos"),
    ("youtube_count", "YouTube-Videos"),
    ("flight_count", "Gleitschirmflüge"),
)


def trip_summary_counts(snapshot: TimelineSnapshot | None) -> dict[str, int]:
    entries = snapshot.published_entries() if snapshot is not None else ()
    photos = 0
    youtube: set[str] = set()
    for entry in entries:
        section = entry.section
        if section is None:
            continue
        youtube.update(url for url in section.youtube_urls if url)
        for item in section.items:
            if _is_visible_photo(item):
                photos += 1
    flights = _flight_items(snapshot)
    pilots = {(item.pilot or "").strip().casefold() for item in flights if (item.pilot or "").strip()}
    return {
        "duration_days": _duration_days(snapshot),
        "section_count": len(entries),
        "photo_count": photos,
        "youtube_count": len(youtube),
        "flight_count": len(flights),
        "pilot_count": len(pilots),
    }


def trip_summary_metrics(snapshot: TimelineSnapshot | None) -> tuple[tuple[str, str], ...]:
    """Pairs of display value and German label; zero counts are omitted."""

    counts = trip_summary_counts(snapshot)
    rows: list[tuple[str, str]] = []
    for key, label in METRIC_LABELS:
        value = counts[key]
        if value <= 0:
            continue
        if key == "flight_count" and counts["pilot_count"] > 1:
            label = f"{label} ({counts['pilot_count']} Piloten)"
        rows.append((str(value), label))
    return tuple(rows)


def _duration_days(snapshot: TimelineSnapshot | None) -> int:
    if snapshot is None:
        return 0
    start = snapshot.start_date
    end = snapshot.end_date
    if start is None or end is None:
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
        if not starts or not ends:
            return 0
        start, end = min(starts), max(ends)
    if end < start:
        start, end = end, start
    return (end - start).days + 1


def _flight_items(snapshot: TimelineSnapshot | None) -> tuple[TimelinePhoto, ...]:
    """Unique IGC files on the trip, including pool media that still have a calendar day."""

    if snapshot is None:
        return ()
    found: dict[int, TimelinePhoto] = {}

    def add(item: TimelinePhoto) -> None:
        if not _is_flight(item):
            return
        found.setdefault(item.source_file_id, item)

    for entry in snapshot.published_entries():
        if entry.section is not None:
            for item in entry.section.items:
                add(item)
        elif entry.leftover_day is not None:
            for item in entry.leftover_day.photos:
                add(item)
    for day in snapshot.days:
        for item in day.photos:
            add(item)
    return tuple(found.values())


def _is_visible_photo(item: TimelinePhoto) -> bool:
    if item.file_kind != "photo" or item.sort_status == SORT_REJECTED:
        return False
    if item.stack_size > 1 and not item.is_stack_key:
        return False
    return not (item.group_size > 1 and not item.is_group_key)


def _is_flight(item: TimelinePhoto) -> bool:
    if item.sort_status == SORT_REJECTED:
        return False
    return item.file_kind == "gps" and is_igc_filename(item.filename)
