"""Overview covers and per-entry map detail. Originals are never written."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from travelcore.database.models import (
    Place,
    Project,
    SectionMember,
    SourceFile,
    Trip,
    TripDay,
    TripSection,
)
from travelcore.maps.scene import (
    STAY_LINK_STYLE_STRAIGHT,
    MapMarker,
    MapScene,
    StayLink,
    _center,
    _day_key,
    _photo_markers,
    track_polylines,
)
from travelcore.media.gallery import SORT_REJECTED
from travelcore.media.orientation import normalize_rotation_degrees
from travelcore.media.thumbnails import cached_thumbnail_path
from travelcore.media.types import FileKind
from travelcore.timeline.build import load_timeline
from travelcore.timeline.links import parse_youtube_urls
from travelcore.timeline.sections import (
    KIND_DAY,
    KIND_MOVEMENT,
    claimed_source_ids,
    format_section_span,
)
from travelcore.timeline.types import TimelineDay, TimelineEntry, TimelinePhoto, TimelineSection


@dataclass(frozen=True, slots=True)
class MapGroupRef:
    source_ids: list[int]
    day_id: int | None = None
    youtube_urls: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MapTimelineCard:
    """One compact row in the map strip: title, cover, time span, optional GPS."""

    group_key: str
    title: str
    time_label: str
    cover_path: Path | None = None
    latitude: float | None = None
    longitude: float | None = None
    card_kind: str = "stay"


def build_map_overview(
    session: Session,
    project_id: int,
    thumbs_dir: Path,
    *,
    size: int = 256,
) -> MapScene:
    """One cover marker per section or leftover day; no individual tracks or photos."""

    project = session.get(Project, project_id)
    snapshot = load_timeline(session, project, thumbs_dir=thumbs_dir, size=size) if project else None
    if snapshot is not None and snapshot.entries:
        entries = list(snapshot.entries)
        covers = _covers_from_entries(entries)
        links = stay_links_from_entries(entries)
    else:
        covers = _covers_from_source_files(session, project_id, thumbs_dir, size=size)
        links = []
    center = _center(covers, ())
    return MapScene(markers=tuple(covers), polylines=(), stay_links=tuple(links), center=center)


def build_map_timeline(
    session: Session,
    project_id: int,
    thumbs_dir: Path,
    *,
    size: int = 256,
) -> tuple[MapTimelineCard, ...]:
    """Saved sections and leftover days in timeline order, for the strip under the map."""

    project = session.get(Project, project_id)
    snapshot = load_timeline(session, project, thumbs_dir=thumbs_dir, size=size) if project else None
    if snapshot is not None and snapshot.entries:
        cards = [_card_from_entry(entry) for entry in snapshot.entries]
        return tuple(card for card in cards if card is not None)
    return tuple(_cards_from_source_files(session, project_id, thumbs_dir, size=size))


def build_map_group_detail(
    session: Session,
    project_id: int,
    group_key: str,
    thumbs_dir: Path,
    *,
    size: int = 256,
    resolved: MapGroupRef | None = None,
) -> MapScene:
    """Photos, videos, tracks and places that belong to one overview entry."""

    if resolved is None:
        resolved = resolve_map_group(session, project_id, group_key, thumbs_dir, size=size)
    if resolved is None:
        return MapScene()
    wanted = set(resolved.source_ids)
    photo_markers = _photo_markers_for_ids(session, project_id, thumbs_dir, size=size, source_ids=wanted)
    lines = track_polylines(session, project_id, source_file_ids=wanted)
    extra = _places_for_day(session, resolved.day_id) if resolved.day_id is not None else []
    markers = tuple(photo_markers + extra)
    return MapScene(markers=markers, polylines=tuple(lines), center=_center(markers, lines))


def resolve_map_group(
    session: Session,
    project_id: int,
    group_key: str,
    thumbs_dir: Path,
    *,
    size: int = 256,
) -> MapGroupRef | None:
    """Ordered source-file ids, leftover day id and YouTube links for one overview entry."""

    del thumbs_dir, size
    kind, raw_id = parse_group_key(group_key)
    if kind is None:
        return None
    if kind == "section":
        return _resolve_section_group(session, project_id, int(raw_id))
    if kind == "day":
        return _resolve_day_group(session, project_id, int(raw_id))
    if kind == "loose":
        return MapGroupRef(source_ids=list(_source_ids_for_loose_day(session, project_id, str(raw_id))))
    return None


def _resolve_section_group(session: Session, project_id: int, section_id: int) -> MapGroupRef | None:
    section = session.get(TripSection, section_id)
    if section is None:
        return None
    trip = session.get(Trip, section.trip_id)
    if trip is None or trip.project_id != project_id:
        return None
    ids = list(
        session.scalars(
            select(SectionMember.source_file_id)
            .where(SectionMember.section_id == section.id)
            .order_by(SectionMember.sort_index.asc(), SectionMember.id.asc())
        )
    )
    return MapGroupRef(
        source_ids=ids,
        youtube_urls=parse_youtube_urls(section.youtube_urls),
    )


def _resolve_day_group(session: Session, project_id: int, day_id: int) -> MapGroupRef | None:
    day = session.get(TripDay, day_id)
    if day is None:
        return None
    trip = session.get(Trip, day.trip_id)
    if trip is None or trip.project_id != project_id:
        return None
    claimed = claimed_source_ids(session, trip.id)
    return MapGroupRef(
        source_ids=_leftover_source_ids_for_day(session, project_id, day, claimed),
        day_id=day.id,
        youtube_urls=parse_youtube_urls(day.youtube_urls),
    )


def parse_group_key(group_key: str) -> tuple[str | None, int | str | None]:
    text = (group_key or "").strip()
    if ":" not in text:
        return None, None
    kind, _, rest = text.partition(":")
    rest = rest.strip()
    if kind in {"section", "day"}:
        try:
            return kind, int(rest)
        except ValueError:
            return None, None
    if kind == "loose" and rest:
        return kind, rest
    return None, None


def pick_cover_item(items: list[TimelinePhoto], cover_id: int | None) -> TimelinePhoto | None:
    """Stored cover, else first GPS photo, else first GPS track. Rejected media never count."""

    visible = [item for item in items if item.sort_status != SORT_REJECTED]
    by_id = {item.source_file_id: item for item in visible}
    if cover_id is not None and cover_id in by_id:
        return by_id[cover_id]
    for item in visible:
        if item.file_kind == FileKind.PHOTO.value and _item_has_gps(item):
            return item
    for item in visible:
        if item.file_kind == FileKind.GPS.value:
            return item
    return None


def _item_has_gps(item: TimelinePhoto) -> bool:
    return item.gps_latitude is not None and item.gps_longitude is not None


def position_for_cover(
    cover: TimelinePhoto | None,
    items: list[TimelinePhoto],
) -> tuple[float, float] | None:
    if cover is not None and cover.gps_latitude is not None and cover.gps_longitude is not None:
        return (cover.gps_latitude, cover.gps_longitude)
    coords = [
        (item.gps_latitude, item.gps_longitude)
        for item in items
        if item.sort_status != SORT_REJECTED
        and item.gps_latitude is not None
        and item.gps_longitude is not None
    ]
    if not coords:
        return None
    lat = sum(item[0] for item in coords) / len(coords)
    lon = sum(item[1] for item in coords) / len(coords)
    return (lat, lon)


def _card_from_entry(entry: TimelineEntry) -> MapTimelineCard | None:
    if entry.section is not None:
        items = list(entry.section.items)
        cover_id = entry.section.cover_source_file_id
        key = f"section:{entry.section.id}"
        title = _section_title(entry.section)
        started, ended = entry.section.started_at, entry.section.ended_at
        leftover = None
    elif entry.leftover_day is not None:
        leftover = entry.leftover_day
        items = list(leftover.photos)
        cover_id = leftover.cover_source_file_id
        key = f"day:{leftover.id}"
        title = _day_label(leftover)
        started, ended = _items_span(items)
        if started is None:
            started, ended = _day_as_span(leftover)
    else:
        return None
    chosen = pick_cover_item(items, cover_id)
    position = position_for_cover(chosen, items)
    if position is None and leftover is not None:
        marker = _fallback_place_marker(leftover, key, title)
        if marker is not None:
            position = (marker.latitude, marker.longitude)
    cover_path = chosen.thumbnail_path if chosen is not None else None
    lat = position[0] if position is not None else None
    lon = position[1] if position is not None else None
    return MapTimelineCard(
        group_key=key,
        title=title,
        time_label=format_section_span(started, ended),
        cover_path=cover_path,
        latitude=lat,
        longitude=lon,
        card_kind=entry.card_kind,
    )


def stay_links_from_entries(entries: list[TimelineEntry]) -> list[StayLink]:
    """Straight links between Tag and Aufenthalt covers in timeline order.

    Transfer circles are not endpoints. A transfer between two linked covers is
    recorded so a later pass can pick a curved line or a track trace.
    """

    stops: list[tuple[int, MapMarker]] = []
    for index, entry in enumerate(entries):
        if entry.card_kind == KIND_MOVEMENT:
            continue
        marker = _cover_marker_for_entry(entry)
        if marker is None:
            continue
        stops.append((index, marker))
    links: list[StayLink] = []
    for (left, start), (right, end) in zip(stops, stops[1:], strict=False):
        between = entries[left + 1 : right]
        via_transfer = any(item.card_kind == KIND_MOVEMENT for item in between)
        links.append(
            StayLink(
                start=(start.latitude, start.longitude),
                end=(end.latitude, end.longitude),
                start_key=start.group_key or "",
                end_key=end.group_key or "",
                style=stay_link_style(via_transfer=via_transfer),
                via_transfer=via_transfer,
            )
        )
    return links


def stay_link_style(*, via_transfer: bool) -> str:
    """Line look between two Tag/Aufenthalt covers. Transfers will later choose curve or track."""

    del via_transfer
    return STAY_LINK_STYLE_STRAIGHT


def _covers_from_entries(entries: list[TimelineEntry]) -> list[MapMarker]:
    covers: list[MapMarker] = []
    for entry in entries:
        marker = _cover_marker_for_entry(entry)
        if marker is not None:
            covers.append(marker)
    return covers


def _cover_marker_for_entry(entry: TimelineEntry) -> MapMarker | None:
    if entry.section is not None:
        items = list(entry.section.items)
        cover_id = entry.section.cover_source_file_id
        key = f"section:{entry.section.id}"
        label = _section_label(entry.section)
        leftover = None
    elif entry.leftover_day is not None:
        leftover = entry.leftover_day
        items = list(leftover.photos)
        cover_id = leftover.cover_source_file_id
        key = f"day:{leftover.id}"
        label = _day_label(leftover)
    else:
        return None
    chosen = pick_cover_item(items, cover_id)
    position = position_for_cover(chosen, items)
    if position is None and leftover is not None:
        return _fallback_place_marker(leftover, key, label)
    if chosen is None or position is None:
        return None
    return _cover_marker(chosen, key, label, position)


def _cover_marker(
    item: TimelinePhoto,
    group_key: str,
    label: str,
    position: tuple[float, float],
) -> MapMarker:
    return MapMarker(
        latitude=position[0],
        longitude=position[1],
        label=label,
        kind="cover",
        preview_path=item.thumbnail_path,
        day_key=group_key,
        color="blue",
        subtitle=item.filename,
        group_key=group_key,
        source_file_id=item.source_file_id,
    )


def _fallback_place_marker(day: TimelineDay, group_key: str, label: str) -> MapMarker | None:
    for place in day.places:
        if place.latitude is None or place.longitude is None:
            continue
        return MapMarker(
            latitude=place.latitude,
            longitude=place.longitude,
            label=label,
            kind="cover",
            day_key=group_key,
            color="gray",
            subtitle=place.name,
            group_key=group_key,
        )
    return None


def _covers_from_source_files(
    session: Session,
    project_id: int,
    thumbs_dir: Path,
    *,
    size: int,
) -> list[MapMarker]:
    rows = list(
        session.scalars(
            select(SourceFile)
            .where(
                SourceFile.project_id == project_id,
                SourceFile.file_kind.in_((FileKind.PHOTO.value, FileKind.VIDEO.value, FileKind.GPS.value)),
            )
            .order_by(SourceFile.captured_at.asc().nulls_last(), SourceFile.filename.asc())
        )
    )
    grouped: dict[date | None, list[SourceFile]] = defaultdict(list)
    for row in rows:
        key = row.captured_at.date() if row.captured_at is not None else None
        grouped[key].append(row)
    covers: list[MapMarker] = []
    for day, files in grouped.items():
        items = [_timeline_photo_from_source(row, thumbs_dir, size=size) for row in files]
        chosen = pick_cover_item(items, None)
        position = position_for_cover(chosen, items)
        if chosen is None or position is None:
            continue
        day_key = day.isoformat() if day is not None else "Ohne Datum"
        covers.append(_cover_marker(chosen, f"loose:{day_key}", day_key, position))
    return covers


def _cards_from_source_files(
    session: Session,
    project_id: int,
    thumbs_dir: Path,
    *,
    size: int,
) -> list[MapTimelineCard]:
    rows = list(
        session.scalars(
            select(SourceFile)
            .where(
                SourceFile.project_id == project_id,
                SourceFile.file_kind.in_((FileKind.PHOTO.value, FileKind.VIDEO.value, FileKind.GPS.value)),
            )
            .order_by(SourceFile.captured_at.asc().nulls_last(), SourceFile.filename.asc())
        )
    )
    grouped: dict[date | None, list[SourceFile]] = defaultdict(list)
    for row in rows:
        key = row.captured_at.date() if row.captured_at is not None else None
        grouped[key].append(row)
    cards: list[MapTimelineCard] = []
    for day, files in grouped.items():
        items = [_timeline_photo_from_source(row, thumbs_dir, size=size) for row in files]
        chosen = pick_cover_item(items, None)
        position = position_for_cover(chosen, items)
        day_key = day.isoformat() if day is not None else "Ohne Datum"
        title = day.strftime("%d.%m.%Y") if day is not None else "Ohne Datum"
        started, ended = _items_span(items)
        cards.append(
            MapTimelineCard(
                group_key=f"loose:{day_key}",
                title=title,
                time_label=format_section_span(started, ended),
                cover_path=chosen.thumbnail_path if chosen is not None else None,
                latitude=position[0] if position is not None else None,
                longitude=position[1] if position is not None else None,
                card_kind=KIND_DAY,
            )
        )
    return cards


def _timeline_photo_from_source(row: SourceFile, thumbs_dir: Path, *, size: int) -> TimelinePhoto:
    rotation = normalize_rotation_degrees(row.rotation_degrees)
    return TimelinePhoto(
        source_file_id=row.id,
        filename=row.filename,
        path=row.path,
        thumbnail_path=cached_thumbnail_path(
            thumbs_dir,
            source_file_id=row.id,
            sha256=row.sha256,
            size=size,
            rotation_degrees=rotation,
        ),
        captured_at=row.captured_at,
        used_in_journal=False,
        is_cover=False,
        is_favorite=False,
        gps_latitude=row.gps_latitude,
        gps_longitude=row.gps_longitude,
        file_kind=row.file_kind,
        rotation_degrees=rotation,
    )


def _source_ids_for_loose_day(session: Session, project_id: int, day_key: str) -> set[int]:
    rows = session.scalars(
        select(SourceFile).where(
            SourceFile.project_id == project_id,
            SourceFile.file_kind.in_((FileKind.PHOTO.value, FileKind.VIDEO.value, FileKind.GPS.value)),
        )
    )
    return {row.id for row in rows if _day_key(row.captured_at) == day_key}


def _photo_markers_for_ids(
    session: Session,
    project_id: int,
    thumbs_dir: Path,
    *,
    size: int,
    source_ids: set[int],
) -> list[MapMarker]:
    return _photo_markers(session, project_id, thumbs_dir, size=size, source_file_ids=source_ids)


def _leftover_source_ids_for_day(
    session: Session,
    project_id: int,
    day: TripDay,
    claimed: set[int],
) -> list[int]:
    day_key = _day_key(day.date)
    rows = session.execute(
        select(SourceFile.id, SourceFile.captured_at)
        .where(
            SourceFile.project_id == project_id,
            SourceFile.file_kind.in_((FileKind.PHOTO.value, FileKind.VIDEO.value, FileKind.GPS.value)),
        )
        .order_by(SourceFile.captured_at.asc().nulls_last(), SourceFile.filename.asc())
    )
    return [
        source_id
        for source_id, captured_at in rows
        if source_id not in claimed and _day_key(captured_at) == day_key
    ]


def _places_for_day(session: Session, day_id: int) -> list[MapMarker]:
    markers: list[MapMarker] = []
    places = session.scalars(
        select(Place).where(
            Place.day_id == day_id,
            Place.latitude.is_not(None),
            Place.longitude.is_not(None),
        )
    )
    for place in places:
        if place.latitude is None or place.longitude is None:
            continue
        markers.append(
            MapMarker(
                latitude=place.latitude,
                longitude=place.longitude,
                label=place.name,
                kind="place",
                color="gray",
            )
        )
    return markers


def _section_label(section: TimelineSection) -> str:
    kind = "Transfer" if section.kind == KIND_MOVEMENT else "Aufenthalt"
    title = (section.title or "").strip() or kind
    span = format_section_span(section.started_at, section.ended_at)
    return f"{title} · {span}"


def _section_title(section: TimelineSection) -> str:
    title = (section.title or "").strip()
    if title:
        return title
    if section.kind == KIND_MOVEMENT:
        origin = (section.location_from or "").strip()
        dest = (section.location_to or "").strip()
        if origin or dest:
            return f"{origin or '?'} → {dest or '?'}"
        return "Transfer"
    place = (section.location_name or "").strip()
    return place or "Aufenthalt"


def _day_label(day: TimelineDay) -> str:
    title = (day.title or "").strip()
    if title:
        return title
    if day.date is None:
        return "Ohne Datum"
    return day.date.strftime("%d.%m.%Y")


def _items_span(items: list[TimelinePhoto]) -> tuple[datetime | None, datetime | None]:
    times = [item.captured_at for item in items if item.captured_at is not None]
    if not times:
        return None, None
    return min(times), max(times)


def _day_as_span(day: TimelineDay) -> tuple[datetime | None, datetime | None]:
    if day.date is None:
        return None, None
    stamp = datetime(day.date.year, day.date.month, day.date.day, tzinfo=UTC)
    return stamp, stamp
