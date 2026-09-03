"""Ordered connection lines on Transfer sections. Gap fillers are not stored."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from travelcore.database.models import TransferLink, TripSection
from travelcore.exceptions import ProjectError
from travelcore.timeline.sections import KIND_MOVEMENT, MOVEMENT_MODES, parse_modes, serialize_modes
from travelcore.timeline.types import TimelineLink

LINK_GEOMETRY_LINE = "line"
LINK_GEOMETRY_TRACK = "track"
LINK_GEOMETRY_MAP_TRACK = "map_track"
LINK_GEOMETRY_ARC = "arc"
LINK_GEOMETRY_ROUTE = "route"
LINK_GEOMETRIES = (
    LINK_GEOMETRY_LINE,
    LINK_GEOMETRY_TRACK,
    LINK_GEOMETRY_MAP_TRACK,
    LINK_GEOMETRY_ARC,
    LINK_GEOMETRY_ROUTE,
)
LINK_DASH_SOLID = "solid"
LINK_DASH_DASHED = "dashed"
LINK_DASHES = (LINK_DASH_SOLID, LINK_DASH_DASHED)
SEGMENT_ROLE_USER = "user"
SEGMENT_ROLE_GAP = "gap"
GAP_MIN_METERS = 25.0
ARC_SAMPLES = 32
ARC_BULGE = 0.22


@dataclass(frozen=True, slots=True)
class TransferLinkSpec:
    geometry: str
    dash: str = LINK_DASH_SOLID
    symbol: str | None = None
    end_latitude: float | None = None
    end_longitude: float | None = None
    track_source_file_id: int | None = None


def parse_geometry(raw: str | None) -> str:
    value = (raw or "").strip()
    if value in LINK_GEOMETRIES:
        return value
    return LINK_GEOMETRY_LINE


def uses_track_points(geometry: str | None) -> bool:
    """True when the line follows a GPX (recorded Track or Map-Track)."""

    return (geometry or "").strip() in {LINK_GEOMETRY_TRACK, LINK_GEOMETRY_MAP_TRACK}


def is_map_track_geometry(geometry: str | None) -> bool:
    return (geometry or "").strip() == LINK_GEOMETRY_MAP_TRACK


def parse_dash(raw: str | None) -> str:
    value = (raw or "").strip()
    if value in LINK_DASHES:
        return value
    return LINK_DASH_SOLID


def parse_symbol(raw: str | None) -> str | None:
    value = (raw or "").strip()
    if value in MOVEMENT_MODES:
        return value
    return None


def links_from_modes(mode: str | None) -> tuple[TimelineLink, ...]:
    """One line segment per selected mode, in canonical order."""

    return tuple(
        TimelineLink(id=0, sort_index=index, geometry=LINK_GEOMETRY_LINE, symbol=symbol)
        for index, symbol in enumerate(parse_modes(mode))
    )


def link_view(row: TransferLink) -> TimelineLink:
    return TimelineLink(
        id=row.id,
        sort_index=row.sort_index,
        geometry=parse_geometry(row.geometry),
        dash=parse_dash(row.dash),
        symbol=parse_symbol(row.symbol),
        end_latitude=row.end_latitude,
        end_longitude=row.end_longitude,
        track_source_file_id=row.track_source_file_id,
    )


def load_transfer_links(session: Session, section_id: int) -> tuple[TimelineLink, ...]:
    rows = list(
        session.scalars(
            select(TransferLink)
            .where(TransferLink.section_id == section_id)
            .order_by(TransferLink.sort_index.asc(), TransferLink.id.asc())
        )
    )
    return tuple(link_view(row) for row in rows)


def load_transfer_links_for_sections(
    session: Session, section_ids: list[int]
) -> dict[int, tuple[TimelineLink, ...]]:
    wanted = [item for item in dict.fromkeys(section_ids) if item]
    if not wanted:
        return {}
    rows = list(
        session.scalars(
            select(TransferLink)
            .where(TransferLink.section_id.in_(wanted))
            .order_by(TransferLink.section_id.asc(), TransferLink.sort_index.asc(), TransferLink.id.asc())
        )
    )
    grouped: dict[int, list[TimelineLink]] = {item: [] for item in wanted}
    for row in rows:
        grouped.setdefault(row.section_id, []).append(link_view(row))
    return {key: tuple(value) for key, value in grouped.items()}


def save_transfer_links(
    session: Session,
    section_id: int,
    specs: list[TransferLinkSpec] | list[TimelineLink],
) -> tuple[TimelineLink, ...]:
    """Replace every connection line on a Transfer. Updates the mode cache."""

    section = session.get(TripSection, section_id)
    if section is None:
        raise ProjectError("Reiseabschnitt nicht gefunden.")
    if section.kind != KIND_MOVEMENT:
        raise ProjectError("Verbindungslinien gibt es nur am Transfer.")
    parsed = [_normalize_spec(item) for item in specs]
    used_tracks: set[int] = set()
    for item in parsed:
        track_id = item.track_source_file_id
        if track_id is None:
            continue
        if track_id in used_tracks:
            raise ProjectError("Eine Spur kann nur einer Verbindungslinie zugeordnet werden.")
        used_tracks.add(track_id)
    session.execute(delete(TransferLink).where(TransferLink.section_id == section_id))
    session.flush()
    for index, item in enumerate(parsed):
        session.add(
            TransferLink(
                section_id=section_id,
                sort_index=index,
                geometry=item.geometry,
                dash=item.dash,
                symbol=item.symbol,
                end_latitude=item.end_latitude,
                end_longitude=item.end_longitude,
                track_source_file_id=item.track_source_file_id,
            )
        )
    section.mode = serialize_modes([item.symbol for item in parsed if item.symbol])
    session.flush()
    return load_transfer_links(session, section_id)


def delete_transfer_links(session: Session, section_id: int) -> None:
    session.execute(delete(TransferLink).where(TransferLink.section_id == section_id))


def clear_transfer_track_refs(session: Session, source_file_ids: list[int]) -> None:
    """Drop a track choice when the file leaves the section. Geometry stays Track."""

    ids = list(dict.fromkeys(source_file_ids))
    if not ids:
        return
    session.execute(
        update(TransferLink)
        .where(TransferLink.track_source_file_id.in_(ids))
        .values(track_source_file_id=None)
    )


def drop_track_usages(session: Session, source_file_ids: list[int]) -> None:
    """Remove connection lines that pointed at deleted tracks. No replacement track."""

    ids = [item for item in dict.fromkeys(source_file_ids) if item]
    if not ids:
        return
    section_ids = list(
        dict.fromkeys(
            session.scalars(
                select(TransferLink.section_id).where(TransferLink.track_source_file_id.in_(ids))
            )
        )
    )
    session.execute(delete(TransferLink).where(TransferLink.track_source_file_id.in_(ids)))
    session.flush()
    for section_id in section_ids:
        remaining = list(load_transfer_links(session, section_id))
        save_transfer_links(session, section_id, remaining)
    session.execute(
        update(TripSection)
        .where(
            TripSection.outbound_track_source_file_id.in_(ids),
            TripSection.outbound_geometry == LINK_GEOMETRY_MAP_TRACK,
        )
        .values(
            outbound_track_source_file_id=None,
            outbound_geometry=None,
            outbound_dash=None,
            outbound_symbol=None,
        )
    )
    session.execute(
        update(TripSection)
        .where(TripSection.outbound_track_source_file_id.in_(ids))
        .values(outbound_track_source_file_id=None)
    )


def _normalize_spec(item: TransferLinkSpec | TimelineLink) -> TransferLinkSpec:
    geometry = parse_geometry(item.geometry)
    track_id = item.track_source_file_id if uses_track_points(geometry) else None
    end_lat = item.end_latitude
    end_lon = item.end_longitude
    if end_lat is None or end_lon is None:
        end_lat, end_lon = None, None
    elif not -90.0 <= float(end_lat) <= 90.0 or not -180.0 <= float(end_lon) <= 180.0:
        raise ProjectError("Ungültiges Gelenk.")
    else:
        end_lat, end_lon = float(end_lat), float(end_lon)
    return TransferLinkSpec(
        geometry=geometry,
        dash=parse_dash(item.dash),
        symbol=parse_symbol(item.symbol),
        end_latitude=end_lat,
        end_longitude=end_lon,
        track_source_file_id=track_id,
    )
