"""One optional connection from a Tag/Stay to the next non-Transfer section."""

from __future__ import annotations

from sqlalchemy.orm import Session

from travelcore.database.models import TripSection
from travelcore.exceptions import ProjectError
from travelcore.timeline.sections import KIND_MOVEMENT
from travelcore.timeline.transfer_links import (
    LINK_DASH_SOLID,
    LINK_GEOMETRY_ARC,
    LINK_GEOMETRY_LINE,
    parse_dash,
    parse_symbol,
)
from travelcore.timeline.types import TimelineLink

LINK_GEOMETRY_NONE = "none"
OUTBOUND_GEOMETRIES = (LINK_GEOMETRY_LINE, LINK_GEOMETRY_ARC)


def parse_outbound_geometry(raw: str | None) -> str:
    value = (raw or "").strip()
    if value == LINK_GEOMETRY_NONE:
        return LINK_GEOMETRY_NONE
    if value == LINK_GEOMETRY_ARC:
        return LINK_GEOMETRY_ARC
    return LINK_GEOMETRY_LINE


def outbound_is_hidden(link: TimelineLink | None) -> bool:
    return link is not None and link.geometry == LINK_GEOMETRY_NONE


def normalize_outbound(
    geometry: str | None,
    dash: str | None,
    symbol: str | None,
) -> tuple[str | None, str | None, str | None]:
    """All-default (gerade, solid, no symbol) stores as NULL. ``none`` hides the line."""

    geo = parse_outbound_geometry(geometry)
    if geo == LINK_GEOMETRY_NONE:
        return LINK_GEOMETRY_NONE, None, None
    dsh = parse_dash(dash)
    sym = parse_symbol(symbol)
    if geo == LINK_GEOMETRY_LINE and dsh == LINK_DASH_SOLID and sym is None:
        return None, None, None
    return geo, dsh, sym


def outbound_from_columns(
    geometry: str | None,
    dash: str | None,
    symbol: str | None,
) -> TimelineLink | None:
    geo, dsh, sym = normalize_outbound(geometry, dash, symbol)
    if geo is None:
        return None
    return TimelineLink(id=0, sort_index=0, geometry=geo, dash=dsh or LINK_DASH_SOLID, symbol=sym)


def outbound_from_section(section: TripSection) -> TimelineLink | None:
    return outbound_from_columns(
        section.outbound_geometry,
        section.outbound_dash,
        section.outbound_symbol,
    )


def apply_outbound_columns(section: TripSection, link: TimelineLink | None) -> None:
    if link is None:
        section.outbound_geometry = None
        section.outbound_dash = None
        section.outbound_symbol = None
        return
    geo, dsh, sym = normalize_outbound(link.geometry, link.dash, link.symbol)
    section.outbound_geometry = geo
    section.outbound_dash = dsh
    section.outbound_symbol = sym


def save_outbound_link(session: Session, section_id: int, link: TimelineLink | None) -> TimelineLink | None:
    section = session.get(TripSection, section_id)
    if section is None:
        raise ProjectError("Reiseabschnitt nicht gefunden.")
    if section.kind == KIND_MOVEMENT:
        raise ProjectError("Die Ausgangslinie gibt es nur an Tag und Aufenthalt.")
    apply_outbound_columns(section, link)
    session.flush()
    return outbound_from_section(section)
