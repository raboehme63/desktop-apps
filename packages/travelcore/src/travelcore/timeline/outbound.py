"""One optional connection from a Tag/Stay to the next non-Transfer section."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from travelcore.database.models import TripSection
from travelcore.exceptions import ProjectError
from travelcore.timeline.sections import KIND_MOVEMENT
from travelcore.timeline.transfer_links import (
    LINK_DASH_SOLID,
    LINK_GEOMETRY_ARC,
    LINK_GEOMETRY_LINE,
    LINK_GEOMETRY_MAP_TRACK,
    LINK_GEOMETRY_TRACK,
    parse_dash,
    parse_symbol,
)
from travelcore.timeline.types import TimelineLink

LINK_GEOMETRY_NONE = "none"
OUTBOUND_GEOMETRIES = (LINK_GEOMETRY_LINE, LINK_GEOMETRY_ARC, LINK_GEOMETRY_MAP_TRACK)


@dataclass(frozen=True, slots=True)
class LinkDefaults:
    """Trip-wide line style. Sections store NULL to inherit, or explicit overrides."""

    geometry: str = LINK_GEOMETRY_LINE
    dash: str = LINK_DASH_SOLID
    symbol: str | None = None

    def as_link(self, *, sort_index: int = 0, link_id: int = 0) -> TimelineLink:
        return TimelineLink(
            id=link_id,
            sort_index=sort_index,
            geometry=self.geometry,
            dash=self.dash,
            symbol=self.symbol,
        )

    def matches(self, link: TimelineLink | None) -> bool:
        if link is None:
            return True
        if link.geometry == LINK_GEOMETRY_NONE:
            return False
        geometry = parse_outbound_geometry(link.geometry)
        if geometry not in {LINK_GEOMETRY_LINE, LINK_GEOMETRY_ARC}:
            return False
        if link.track_source_file_id is not None:
            return False
        if link.end_latitude is not None or link.end_longitude is not None:
            return False
        return (
            geometry == self.geometry
            and parse_dash(link.dash) == self.dash
            and parse_symbol(link.symbol) == self.symbol
        )


def link_defaults_from_settings(settings: object | None) -> LinkDefaults:
    placeholders = getattr(settings, "placeholders", None)
    if placeholders is None:
        return LinkDefaults()
    geometry = (
        LINK_GEOMETRY_ARC
        if str(getattr(placeholders, "default_link_geometry", "") or "").strip() == LINK_GEOMETRY_ARC
        else LINK_GEOMETRY_LINE
    )
    dash = parse_dash(str(getattr(placeholders, "default_link_dash", "") or "") or None)
    symbol = parse_symbol(str(getattr(placeholders, "default_link_symbol", "") or "") or None)
    return LinkDefaults(geometry=geometry, dash=dash, symbol=symbol)


def link_defaults_from_project_dir(project_dir: Path | None) -> LinkDefaults:
    if project_dir is None:
        return LinkDefaults()
    from travelcore.project_settings import load_project_settings

    try:
        return link_defaults_from_settings(load_project_settings(project_dir))
    except (OSError, ProjectError):
        return LinkDefaults()


def compact_inherited_links(
    links: Sequence[TimelineLink],
    defaults: LinkDefaults | None = None,
) -> list[TimelineLink]:
    """Drop a single row that still matches the trip default so the section inherits."""

    items = list(links)
    if len(items) != 1:
        return items
    if (defaults or LinkDefaults()).matches(items[0]):
        return []
    return items


def parse_outbound_geometry(raw: str | None) -> str:
    value = (raw or "").strip()
    if value == LINK_GEOMETRY_NONE:
        return LINK_GEOMETRY_NONE
    if value == LINK_GEOMETRY_TRACK:
        return LINK_GEOMETRY_MAP_TRACK
    if value in {LINK_GEOMETRY_ARC, LINK_GEOMETRY_MAP_TRACK}:
        return value
    return LINK_GEOMETRY_LINE


def outbound_is_hidden(link: TimelineLink | None) -> bool:
    return link is not None and link.geometry == LINK_GEOMETRY_NONE


def normalize_outbound(
    geometry: str | None,
    dash: str | None,
    symbol: str | None,
) -> tuple[str | None, str | None, str | None]:
    """All-NULL columns inherit the trip default. ``none`` hides the line."""

    if geometry is None and dash is None and symbol is None:
        return None, None, None
    geo = parse_outbound_geometry(geometry)
    if geo == LINK_GEOMETRY_NONE:
        return LINK_GEOMETRY_NONE, None, None
    return geo, parse_dash(dash), parse_symbol(symbol)


def outbound_from_columns(
    geometry: str | None,
    dash: str | None,
    symbol: str | None,
    track_source_file_id: int | None = None,
    defaults: LinkDefaults | None = None,
) -> TimelineLink | None:
    geo, dsh, sym = normalize_outbound(geometry, dash, symbol)
    if geo is None:
        if track_source_file_id is not None:
            return TimelineLink(
                id=0,
                sort_index=0,
                geometry=LINK_GEOMETRY_MAP_TRACK,
                dash=LINK_DASH_SOLID,
                track_source_file_id=track_source_file_id,
            )
        return defaults.as_link() if defaults is not None else None
    track_id = track_source_file_id if geo == LINK_GEOMETRY_MAP_TRACK else None
    return TimelineLink(
        id=0,
        sort_index=0,
        geometry=geo,
        dash=dsh or LINK_DASH_SOLID,
        symbol=sym,
        track_source_file_id=track_id,
    )


def outbound_from_section(
    section: TripSection,
    defaults: LinkDefaults | None = None,
) -> TimelineLink | None:
    return outbound_from_columns(
        section.outbound_geometry,
        section.outbound_dash,
        section.outbound_symbol,
        section.outbound_track_source_file_id,
        defaults=defaults,
    )


def apply_outbound_columns(
    section: TripSection,
    link: TimelineLink | None,
    defaults: LinkDefaults | None = None,
) -> None:
    if link is None or (defaults is not None and defaults.matches(link)):
        section.outbound_geometry = None
        section.outbound_dash = None
        section.outbound_symbol = None
        section.outbound_track_source_file_id = None
        return
    geo, dsh, sym = normalize_outbound(link.geometry, link.dash, link.symbol)
    section.outbound_geometry = geo
    section.outbound_dash = dsh
    section.outbound_symbol = sym
    if geo == LINK_GEOMETRY_MAP_TRACK:
        section.outbound_track_source_file_id = link.track_source_file_id
    else:
        section.outbound_track_source_file_id = None


def save_outbound_link(
    session: Session,
    section_id: int,
    link: TimelineLink | None,
    defaults: LinkDefaults | None = None,
) -> TimelineLink | None:
    section = session.get(TripSection, section_id)
    if section is None:
        raise ProjectError("Reiseabschnitt nicht gefunden.")
    if section.kind == KIND_MOVEMENT:
        raise ProjectError("Die Ausgangslinie gibt es nur an Tag und Aufenthalt.")
    apply_outbound_columns(section, link, defaults)
    session.flush()
    return outbound_from_section(section)
