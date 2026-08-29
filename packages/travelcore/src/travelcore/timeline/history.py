"""Snapshots and restore for reversible journal edits."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from travelcore.database.models import (
    Photo,
    SectionMember,
    SourceFile,
    TransferLink,
    Trip,
    TripDay,
    TripSection,
)
from travelcore.media.gallery import effective_sort_status
from travelcore.timeline.sections import drop_empty_auto_day_sections


@dataclass(frozen=True, slots=True)
class MemberPlacement:
    source_file_id: int
    parked: bool
    section_id: int | None
    sort_index: int = 0
    journal_at: datetime | None = None
    timezone_name: str | None = None
    journal_latitude: float | None = None
    journal_longitude: float | None = None


@dataclass(frozen=True, slots=True)
class SectionSnapshot:
    id: int
    trip_id: int
    kind: str
    mode: str | None
    title: str | None
    notes: str | None
    started_at: datetime | None
    ended_at: datetime | None
    location_name: str | None
    location_from: str | None
    location_to: str | None
    pin_latitude: float | None
    pin_longitude: float | None
    youtube_urls: str | None
    leonardo_urls: str | None
    cover_source_file_id: int | None
    sort_index: int
    origin: str


@dataclass(frozen=True, slots=True)
class TransferLinkSnapshot:
    id: int
    section_id: int
    sort_index: int
    geometry: str
    dash: str
    symbol: str | None
    end_latitude: float | None
    end_longitude: float | None
    track_source_file_id: int | None


@dataclass(frozen=True, slots=True)
class JournalEdit:
    sections: tuple[SectionSnapshot, ...] = ()
    placements: tuple[MemberPlacement, ...] = ()
    transfer_links: tuple[TransferLinkSnapshot, ...] = ()


def photo_sort_status(session: Session, source_file_id: int) -> str | None:
    photo = session.scalar(select(Photo).where(Photo.source_file_id == source_file_id))
    if photo is None:
        return None
    return effective_sort_status(photo.sort_status, photo.is_favorite)


def section_pin(session: Session, section_id: int) -> tuple[float | None, float | None]:
    section = session.get(TripSection, section_id)
    if section is None:
        return None, None
    return section.pin_latitude, section.pin_longitude


def entry_title(session: Session, kind: str, entity_id: int) -> str | None:
    if kind == "section":
        row = session.get(TripSection, entity_id)
        return None if row is None else row.title
    day = session.get(TripDay, entity_id)
    return None if day is None else day.title


def entry_notes(session: Session, kind: str, entity_id: int) -> str | None:
    if kind == "section":
        row = session.get(TripSection, entity_id)
        return None if row is None else row.notes
    day = session.get(TripDay, entity_id)
    return None if day is None else day.notes


def trip_title(session: Session, trip_id: int) -> str | None:
    trip = session.get(Trip, trip_id)
    return None if trip is None else trip.title


def entry_cover(session: Session, kind: str, entity_id: int) -> int | None:
    if kind == "section":
        row = session.get(TripSection, entity_id)
        return None if row is None else row.cover_source_file_id
    day = session.get(TripDay, entity_id)
    return None if day is None else day.cover_source_file_id


def capture_section(session: Session, section_id: int) -> SectionSnapshot | None:
    section = session.get(TripSection, section_id)
    if section is None:
        return None
    return _section_snapshot(section)


def capture_sections(session: Session, section_ids: set[int] | list[int]) -> tuple[SectionSnapshot, ...]:
    wanted = [item for item in dict.fromkeys(section_ids) if item]
    if not wanted:
        return ()
    rows = list(session.scalars(select(TripSection).where(TripSection.id.in_(wanted))))
    by_id = {row.id: row for row in rows}
    return tuple(_section_snapshot(by_id[item]) for item in wanted if item in by_id)


def capture_member_placements(
    session: Session, source_file_ids: list[int] | tuple[int, ...]
) -> tuple[MemberPlacement, ...]:
    ids = list(dict.fromkeys(source_file_ids))
    if not ids:
        return ()
    files = list(session.scalars(select(SourceFile).where(SourceFile.id.in_(ids))))
    by_id = {row.id: row for row in files}
    members = list(session.scalars(select(SectionMember).where(SectionMember.source_file_id.in_(ids))))
    member_by_id = {member.source_file_id: member for member in members}
    placements: list[MemberPlacement] = []
    for source_id in ids:
        row = by_id.get(source_id)
        if row is None:
            continue
        member = member_by_id.get(source_id)
        if member is None:
            placements.append(MemberPlacement(source_file_id=source_id, parked=row.parked, section_id=None))
            continue
        placements.append(
            MemberPlacement(
                source_file_id=source_id,
                parked=row.parked,
                section_id=member.section_id,
                sort_index=member.sort_index,
                journal_at=member.journal_at,
                timezone_name=member.journal_timezone_name,
                journal_latitude=member.journal_latitude,
                journal_longitude=member.journal_longitude,
            )
        )
    return tuple(placements)


def capture_section_members(session: Session, section_id: int) -> tuple[MemberPlacement, ...]:
    ids = [
        source.id
        for source, _member in session.execute(
            select(SourceFile, SectionMember)
            .join(SectionMember, SectionMember.source_file_id == SourceFile.id)
            .where(SectionMember.section_id == section_id)
        )
        if source.id is not None
    ]
    return capture_member_placements(session, ids)


def capture_placement_edit(
    session: Session,
    source_file_ids: list[int] | tuple[int, ...],
    extra_section_ids: list[int] | tuple[int, ...] | set[int] = (),
) -> JournalEdit:
    placements = capture_member_placements(session, source_file_ids)
    section_ids = {item.section_id for item in placements if item.section_id is not None}
    section_ids.update(item for item in extra_section_ids if item)
    return JournalEdit(
        sections=capture_sections(session, section_ids),
        placements=placements,
        transfer_links=capture_transfer_links(session, section_ids),
    )


def capture_section_edit(session: Session, section_id: int) -> JournalEdit | None:
    section = capture_section(session, section_id)
    if section is None:
        return None
    return JournalEdit(
        sections=(section,),
        placements=capture_section_members(session, section_id),
        transfer_links=capture_transfer_links(session, [section_id]),
    )


def capture_transfer_links(
    session: Session, section_ids: set[int] | list[int]
) -> tuple[TransferLinkSnapshot, ...]:
    wanted = [item for item in dict.fromkeys(section_ids) if item]
    if not wanted:
        return ()
    rows = list(
        session.scalars(
            select(TransferLink)
            .where(TransferLink.section_id.in_(wanted))
            .order_by(TransferLink.section_id.asc(), TransferLink.sort_index.asc())
        )
    )
    return tuple(
        TransferLinkSnapshot(
            id=row.id,
            section_id=row.section_id,
            sort_index=row.sort_index,
            geometry=row.geometry,
            dash=row.dash,
            symbol=row.symbol,
            end_latitude=row.end_latitude,
            end_longitude=row.end_longitude,
            track_source_file_id=row.track_source_file_id,
        )
        for row in rows
    )


def restore_journal_edit(session: Session, edit: JournalEdit) -> None:
    """Recreate sections and memberships exactly as captured. Does not touch originals."""

    trip_ids = {item.trip_id for item in edit.sections}
    for snapshot in edit.sections:
        _upsert_section(session, snapshot)
    session.flush()
    _restore_transfer_links(session, edit)
    _restore_placements(session, edit.placements)
    for placement in edit.placements:
        if placement.section_id is None:
            continue
        section = session.get(TripSection, placement.section_id)
        if section is not None:
            trip_ids.add(section.trip_id)
    for trip_id in trip_ids:
        drop_empty_auto_day_sections(session, trip_id)


def _section_snapshot(section: TripSection) -> SectionSnapshot:
    return SectionSnapshot(
        id=section.id,
        trip_id=section.trip_id,
        kind=section.kind,
        mode=section.mode,
        title=section.title,
        notes=section.notes,
        started_at=section.started_at,
        ended_at=section.ended_at,
        location_name=section.location_name,
        location_from=section.location_from,
        location_to=section.location_to,
        pin_latitude=section.pin_latitude,
        pin_longitude=section.pin_longitude,
        youtube_urls=section.youtube_urls,
        leonardo_urls=section.leonardo_urls,
        cover_source_file_id=section.cover_source_file_id,
        sort_index=section.sort_index,
        origin=section.origin,
    )


def _upsert_section(session: Session, snapshot: SectionSnapshot) -> TripSection:
    section = session.get(TripSection, snapshot.id)
    if section is None:
        section = TripSection(id=snapshot.id, trip_id=snapshot.trip_id, kind=snapshot.kind)
        session.add(section)
    section.trip_id = snapshot.trip_id
    section.kind = snapshot.kind
    section.mode = snapshot.mode
    section.title = snapshot.title
    section.notes = snapshot.notes
    section.started_at = snapshot.started_at
    section.ended_at = snapshot.ended_at
    section.location_name = snapshot.location_name
    section.location_from = snapshot.location_from
    section.location_to = snapshot.location_to
    section.pin_latitude = snapshot.pin_latitude
    section.pin_longitude = snapshot.pin_longitude
    section.youtube_urls = snapshot.youtube_urls
    section.leonardo_urls = snapshot.leonardo_urls
    section.cover_source_file_id = snapshot.cover_source_file_id
    section.sort_index = snapshot.sort_index
    section.origin = snapshot.origin
    return section


def _restore_transfer_links(session: Session, edit: JournalEdit) -> None:
    section_ids = {item.id for item in edit.sections}
    section_ids.update(item.section_id for item in edit.transfer_links)
    if section_ids:
        session.execute(delete(TransferLink).where(TransferLink.section_id.in_(section_ids)))
        session.flush()
    for item in edit.transfer_links:
        session.add(
            TransferLink(
                id=item.id,
                section_id=item.section_id,
                sort_index=item.sort_index,
                geometry=item.geometry,
                dash=item.dash,
                symbol=item.symbol,
                end_latitude=item.end_latitude,
                end_longitude=item.end_longitude,
                track_source_file_id=item.track_source_file_id,
            )
        )
    session.flush()


def _restore_placements(session: Session, placements: tuple[MemberPlacement, ...]) -> None:
    ids = [item.source_file_id for item in placements]
    if not ids:
        return
    session.execute(delete(SectionMember).where(SectionMember.source_file_id.in_(ids)))
    session.flush()
    rows = list(session.scalars(select(SourceFile).where(SourceFile.id.in_(ids))))
    by_id = {row.id: row for row in rows}
    for placement in placements:
        row = by_id.get(placement.source_file_id)
        if row is None:
            continue
        row.parked = placement.parked
        if placement.parked or placement.section_id is None:
            continue
        if session.get(TripSection, placement.section_id) is None:
            continue
        session.add(
            SectionMember(
                section_id=placement.section_id,
                source_file_id=placement.source_file_id,
                sort_index=placement.sort_index,
                journal_at=placement.journal_at,
                journal_timezone_name=placement.timezone_name,
                journal_latitude=placement.journal_latitude,
                journal_longitude=placement.journal_longitude,
            )
        )
    session.flush()
