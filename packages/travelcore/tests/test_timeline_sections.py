from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from gpx_fixtures import write_gpx
from jpeg_fixtures import write_jpeg_with_exif
from sqlalchemy import select

from travelcore.database.models import Place, Project, SectionMember, SourceFile
from travelcore.database.project_store import OpenProject
from travelcore.exceptions import ProjectError
from travelcore.geolocation.stays import haversine_m
from travelcore.media.indexer import FileIndexer
from travelcore.timeline import (
    KIND_DAY,
    KIND_MOVEMENT,
    KIND_STAY,
    PendingSectionSpec,
    apply_pending_sections,
    create_section,
    delete_section,
    dissolve_section,
    expand_range_selection,
    format_card_dates,
    format_scroll_date,
    format_section_duration,
    format_section_span,
    format_section_when,
    insert_dates_between,
    load_timeline,
    move_members,
    park_media,
    parse_modes,
    reset_journal,
    serialize_modes,
    set_entry_cover,
    set_journal_at,
    set_section_span,
    sort_members_by_journal,
    span_for_manual_dates,
    sync_timeline,
    update_section_kind,
)
from travelcore.timeline.journal import aware, scattered_positions
from travelcore.timeline.types import TimelineSnapshot


def test_expand_range_selection_fills_between_first_and_last() -> None:
    ordered = [10, 20, 30, 40, 50]
    assert expand_range_selection(ordered, {20, 40}) == {20, 30, 40}
    assert expand_range_selection(ordered, {10, 50}) == {10, 20, 30, 40, 50}
    assert expand_range_selection(ordered, {30}) == {30}
    assert expand_range_selection(ordered, set()) == set()
    assert expand_range_selection(ordered, {20, 30, 50}) == {20, 30, 40, 50}
    assert expand_range_selection(ordered, {20, 40}, excluded={30}) == {20, 40}
    assert expand_range_selection(ordered, {20, 40}, excluded={20, 30}) == {20, 40}


def test_parse_and_serialize_transfer_modes() -> None:
    assert parse_modes(None) == []
    assert parse_modes("bus") == ["bus"]
    assert parse_modes("train,bus,walk") == ["bus", "train", "walk"]
    assert serialize_modes([]) is None
    assert serialize_modes(["train", "bus"]) == "bus,train"
    assert serialize_modes(["bus", "unknown"]) == "bus"


def test_format_section_span_uses_object_dates() -> None:
    start = datetime(2025, 5, 14, 8, 0, tzinfo=UTC)
    same_day = datetime(2025, 5, 14, 18, 30, tzinfo=UTC)
    later = datetime(2025, 5, 16, 9, 0, tzinfo=UTC)
    assert format_section_span(start, same_day) == "am 14.05.2025"
    assert format_section_span(start, later) == "von 14.05.2025 bis 16.05.2025"
    assert format_section_span(None, None) == "ohne Zeit"


def test_format_card_dates_omits_am_von_bis() -> None:
    start = datetime(2026, 11, 11, 8, 0, tzinfo=UTC)
    same_day = datetime(2026, 11, 11, 18, 0, tzinfo=UTC)
    later = datetime(2026, 11, 21, 9, 0, tzinfo=UTC)
    assert format_card_dates(start, same_day) == "11.11.2026"
    assert format_card_dates(start, later) == "11.11.2026 - 21.11.2026"
    assert format_card_dates(None, None) == "Ohne Datum"


def test_format_scroll_date_is_compact() -> None:
    start = datetime(2025, 5, 14, 8, 0, tzinfo=UTC)
    same_day = datetime(2025, 5, 14, 18, 30, tzinfo=UTC)
    later_same_month = datetime(2025, 5, 16, 9, 0, tzinfo=UTC)
    later_month = datetime(2025, 8, 10, 9, 0, tzinfo=UTC)
    later_year = datetime(2026, 1, 2, 9, 0, tzinfo=UTC)
    assert format_scroll_date(start, same_day) == "14.05.2025"
    assert format_scroll_date(start, later_same_month) == "14.–16.05.2025"
    assert format_scroll_date(start, later_month) == "14.05.–10.08.2025"
    assert format_scroll_date(start, later_year) == "14.05.2025–02.01.2026"
    assert format_scroll_date(None, None) == "Ohne Datum"


def test_insert_dates_between_uses_open_gap() -> None:
    assert insert_dates_between(date(2025, 5, 14), date(2025, 5, 20)) == (
        date(2025, 5, 15),
        date(2025, 5, 19),
    )
    assert insert_dates_between(date(2025, 5, 14), date(2025, 5, 15)) == (
        date(2025, 5, 14),
        date(2025, 5, 14),
    )
    assert insert_dates_between(date(2025, 8, 10), None) == (date(2025, 8, 10), date(2025, 8, 10))
    assert insert_dates_between(None, date(2025, 8, 1)) == (date(2025, 8, 1), date(2025, 8, 1))


def test_format_section_duration_and_when() -> None:
    start = datetime(2025, 5, 14, 8, 0, tzinfo=UTC)
    same_day = datetime(2025, 5, 14, 18, 30, tzinfo=UTC)
    later = datetime(2025, 5, 16, 9, 0, tzinfo=UTC)
    assert format_section_duration(None, None) is None
    assert format_section_duration(start, start) is None
    assert format_section_duration(start, datetime(2025, 5, 14, 8, 20, tzinfo=UTC)) == "20 Min."
    assert format_section_duration(start, same_day) == "10 Std. 30 Min."
    assert format_section_duration(start, later) == "2 Tage 1 Std."
    assert format_section_when(start, same_day) == "am 14.05.2025 · 10 Std. 30 Min."
    assert format_section_when(None, None) == "ohne Zeit"


def test_create_section_same_day_is_am(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "morgen.jpg",
        datetime_original="2025:05:14 09:00:00",
        offset_original="+02:00",
    )
    write_jpeg_with_exif(
        source / "abend.jpg",
        datetime_original="2025:05:14 18:00:00",
        offset_original="+02:00",
    )
    first = _index_and_sync(open_project, source)
    ids = [photo.source_file_id for photo in first.days[0].photos]
    with open_project.session_factory() as session:
        section = create_section(
            session,
            first.trip_id,
            ids,
            kind=KIND_STAY,
            title="Berlin",
            youtube_urls=["https://youtu.be/dQw4w9WgXcQ"],
        )
        session.commit()
        assert format_section_span(section.started_at, section.ended_at) == "am 14.05.2025"

    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        snapshot = load_timeline(session, project)

    assert snapshot is not None
    assert len(snapshot.sections) == 1
    assert snapshot.sections[0].title == "Berlin"
    assert snapshot.sections[0].kind == KIND_STAY
    assert snapshot.sections[0].youtube_urls == ("https://youtu.be/dQw4w9WgXcQ",)
    assert len(snapshot.entries) == 1
    assert snapshot.entries[0].section is not None
    leftover_photos = [photo.filename for day in snapshot.days for photo in day.photos]
    assert leftover_photos  # calendar days still list all files
    assert snapshot.entries[0].leftover_day is None
    assert snapshot.entries[0].section is not None
    assert snapshot.entries[0].section.kind == KIND_STAY


def test_dissolve_section_returns_files_to_day_sections(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "morgen.jpg",
        datetime_original="2025:05:14 09:00:00",
        offset_original="+02:00",
    )
    write_jpeg_with_exif(
        source / "abend.jpg",
        datetime_original="2025:05:14 18:00:00",
        offset_original="+02:00",
    )
    first = _index_and_sync(open_project, source)
    ids = [photo.source_file_id for photo in first.days[0].photos]
    with open_project.session_factory() as session:
        section = create_section(session, first.trip_id, ids, kind=KIND_STAY, title="Berlin")
        session.commit()
        section_id = section.id
    with open_project.session_factory() as session:
        dissolve_section(session, section_id)
        session.commit()
        project = session.get(Project, open_project.project_id)
        assert project is not None
        snapshot = load_timeline(session, project)
        members = list(session.scalars(select(SectionMember)))
    assert snapshot is not None
    assert len(snapshot.sections) == 1
    day = snapshot.entries[0].section
    assert day is not None
    assert day.kind == KIND_DAY
    assert {photo.filename for photo in day.items} == {"morgen.jpg", "abend.jpg"}
    assert {member.source_file_id for member in members} == {item.source_file_id for item in day.items}


def test_create_empty_section_uses_manual_date(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "morgen.jpg",
        datetime_original="2025:05:14 09:00:00",
        offset_original="+02:00",
    )
    first = _index_and_sync(open_project, source)
    stamp = datetime(2025, 8, 20, 12, 0, tzinfo=UTC)
    with open_project.session_factory() as session:
        section = create_section(
            session,
            first.trip_id,
            [],
            kind=KIND_STAY,
            title="Leer",
            started_at=stamp,
        )
        session.commit()
        assert section.started_at == stamp
        assert section.ended_at == stamp
        members = list(session.scalars(select(SectionMember).where(SectionMember.section_id == section.id)))
        assert members == []

    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        snapshot = load_timeline(session, project)
    assert snapshot is not None
    titles = [entry.section.title for entry in snapshot.entries if entry.section is not None]
    assert "Leer" in titles


def test_span_for_manual_dates_tag_and_range() -> None:
    started, ended = span_for_manual_dates(KIND_DAY, date(2025, 8, 20))
    assert started == datetime(2025, 8, 20, tzinfo=UTC)
    assert ended == started
    started, ended = span_for_manual_dates(KIND_STAY, date(2025, 8, 1), date(2025, 8, 10))
    assert started == datetime(2025, 8, 1, tzinfo=UTC)
    assert ended == datetime(2025, 8, 10, tzinfo=UTC)
    with pytest.raises(ProjectError, match="Endedatum"):
        span_for_manual_dates(KIND_MOVEMENT, date(2025, 8, 10), date(2025, 8, 1))


def test_create_empty_stay_keeps_von_bis_span(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "morgen.jpg",
        datetime_original="2025:05:14 09:00:00",
        offset_original="+02:00",
    )
    first = _index_and_sync(open_project, source)
    started, ended = span_for_manual_dates(KIND_STAY, date(2025, 8, 1), date(2025, 8, 10))
    with open_project.session_factory() as session:
        section = create_section(
            session,
            first.trip_id,
            [],
            kind=KIND_STAY,
            title="Urlaub",
            started_at=started,
            ended_at=ended,
        )
        session.commit()
        assert section.started_at == started
        assert section.ended_at == ended
        assert format_section_span(section.started_at, section.ended_at) == "von 01.08.2025 bis 10.08.2025"


def test_empty_stays_sort_by_span_not_creation(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "anker.jpg",
        datetime_original="2025:05:14 09:00:00",
        offset_original="+02:00",
    )
    first = _index_and_sync(open_project, source)
    later, later_end = span_for_manual_dates(KIND_STAY, date(2025, 8, 20), date(2025, 8, 22))
    earlier, earlier_end = span_for_manual_dates(KIND_STAY, date(2025, 8, 1), date(2025, 8, 3))
    with open_project.session_factory() as session:
        later_section = create_section(
            session,
            first.trip_id,
            [],
            kind=KIND_STAY,
            title="Spaeter",
            started_at=later,
            ended_at=later_end,
        )
        earlier_section = create_section(
            session,
            first.trip_id,
            [],
            kind=KIND_STAY,
            title="Frueher",
            started_at=earlier,
            ended_at=earlier_end,
        )
        session.commit()
        later_id = later_section.id
        earlier_id = earlier_section.id

    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        snapshot = load_timeline(session, project)
    titles = [
        entry.section.title
        for entry in snapshot.entries
        if entry.section is not None and entry.section.title in {"Frueher", "Spaeter"}
    ]
    assert titles == ["Frueher", "Spaeter"]

    moved, moved_end = span_for_manual_dates(KIND_STAY, date(2025, 8, 25), date(2025, 8, 27))
    with open_project.session_factory() as session:
        set_section_span(session, earlier_id, moved, moved_end)
        session.commit()
        project = session.get(Project, open_project.project_id)
        assert project is not None
        snapshot = load_timeline(session, project)
    titles = [
        entry.section.title
        for entry in snapshot.entries
        if entry.section is not None and entry.section.title in {"Frueher", "Spaeter"}
    ]
    assert titles == ["Spaeter", "Frueher"]
    assert later_id != earlier_id


def test_set_section_span_snaps_tag_members(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "morgen.jpg",
        datetime_original="2025:05:14 09:00:00",
        offset_original="+02:00",
    )
    first = _index_and_sync(open_project, source)
    day = next(entry.section for entry in first.entries if entry.section is not None)
    assert day is not None
    assert day.kind == KIND_DAY
    member_id = day.items[0].source_file_id
    target, _ended = span_for_manual_dates(KIND_DAY, date(2025, 8, 20))
    with open_project.session_factory() as session:
        set_section_span(session, day.id, target)
        session.commit()
        member = session.scalar(select(SectionMember).where(SectionMember.source_file_id == member_id))
        source_row = session.get(SourceFile, member_id)
        assert member is not None
        assert member.journal_at is not None
        assert source_row is not None
        captured = aware(source_row.captured_at)
        journal = aware(member.journal_at)
        assert journal is not None and captured is not None
        assert journal.date() == date(2025, 8, 20)
        assert (journal.hour, journal.minute, journal.second) == (
            captured.hour,
            captured.minute,
            captured.second,
        )
        project = session.get(Project, open_project.project_id)
        assert project is not None
        snapshot = load_timeline(session, project)
    moved = next(
        entry.section
        for entry in snapshot.entries
        if entry.section is not None and entry.section.id == day.id
    )
    assert moved is not None
    assert moved.started_at is not None
    assert moved.started_at.date() == date(2025, 8, 20)


def test_delete_section_parks_members_in_pool(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "morgen.jpg",
        datetime_original="2025:05:14 09:00:00",
        offset_original="+02:00",
    )
    write_jpeg_with_exif(
        source / "abend.jpg",
        datetime_original="2025:05:14 18:00:00",
        offset_original="+02:00",
    )
    first = _index_and_sync(open_project, source)
    ids = [photo.source_file_id for photo in first.days[0].photos]
    with open_project.session_factory() as session:
        section = create_section(session, first.trip_id, ids, kind=KIND_STAY, title="Berlin")
        session.commit()
        section_id = section.id
    with open_project.session_factory() as session:
        delete_section(session, section_id)
        session.commit()
        project = session.get(Project, open_project.project_id)
        assert project is not None
        snapshot = load_timeline(session, project)
        parked = list(session.scalars(select(SourceFile).where(SourceFile.parked.is_(True))))
        leftover = list(session.scalars(select(SectionMember)))
    assert snapshot is not None
    assert all(entry.section is None or entry.section.id != section_id for entry in snapshot.entries)
    assert {row.filename for row in parked} == {"morgen.jpg", "abend.jpg"}
    assert leftover == []


def test_day_section_sits_between_stays(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "anreise.jpg",
        datetime_original="2025:05:12 12:00:00",
        offset_original="+02:00",
    )
    write_jpeg_with_exif(
        source / "berlin1.jpg",
        datetime_original="2025:05:14 10:00:00",
        offset_original="+02:00",
    )
    write_jpeg_with_exif(
        source / "berlin2.jpg",
        datetime_original="2025:05:15 16:00:00",
        offset_original="+02:00",
    )
    write_jpeg_with_exif(
        source / "weiter.jpg",
        datetime_original="2025:05:16 09:00:00",
        offset_original="+02:00",
    )
    first = _index_and_sync(open_project, source)
    by_name = {photo.filename: photo.source_file_id for day in first.days for photo in day.photos}
    with open_project.session_factory() as session:
        create_section(
            session,
            first.trip_id,
            [by_name["berlin1.jpg"], by_name["berlin2.jpg"]],
            kind=KIND_STAY,
            title="Besuch von Berlin",
            location_name="Berlin",
        )
        session.commit()

    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        snapshot = load_timeline(session, project)
        members = list(session.scalars(select(SectionMember)))

    assert snapshot is not None
    assert len(members) == 4
    leftover_names = [
        entry.section.items[0].filename
        for entry in snapshot.entries
        if entry.section is not None and entry.section.kind == KIND_DAY
    ]
    assert leftover_names == ["anreise.jpg", "weiter.jpg"]
    assert snapshot.entries[0].section is not None
    assert snapshot.entries[0].card_kind == KIND_DAY
    assert snapshot.entries[1].section is not None
    assert snapshot.entries[1].card_kind == KIND_STAY
    assert snapshot.entries[1].section.title == "Besuch von Berlin"
    assert format_section_span(
        snapshot.entries[1].section.started_at, snapshot.entries[1].section.ended_at
    ) == ("von 14.05.2025 bis 15.05.2025")
    assert snapshot.entries[2].section is not None
    assert snapshot.entries[2].card_kind == KIND_DAY
    assert "berlin1.jpg" not in leftover_names


def test_create_movement_section_from_last_day_files(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "stadt.jpg",
        datetime_original="2025:05:17 09:00:00",
        offset_original="+02:00",
    )
    write_jpeg_with_exif(
        source / "bus.jpg",
        datetime_original="2025:05:17 16:40:00",
        offset_original="+02:00",
    )
    first = _index_and_sync(open_project, source)
    by_name = {photo.filename: photo.source_file_id for photo in first.days[0].photos}
    with open_project.session_factory() as session:
        create_section(
            session,
            first.trip_id,
            [by_name["bus.jpg"]],
            kind=KIND_MOVEMENT,
            mode="bus",
            title="Weiterfahrt",
            location_from="Berlin",
            location_to="Hamburg",
        )
        session.commit()

    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        snapshot = load_timeline(session, project)

    assert snapshot is not None
    assert len(snapshot.entries) == 2
    leftover = snapshot.entries[0].section
    section = snapshot.entries[1].section
    assert leftover is not None
    assert leftover.kind == KIND_DAY
    assert leftover.items[0].filename == "stadt.jpg"
    assert section is not None
    assert section.kind == KIND_MOVEMENT
    assert section.mode == "bus"
    assert format_section_span(section.started_at, section.ended_at) == "am 17.05.2025"


def test_transfer_mode_is_optional_and_can_be_multiple(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "start.jpg",
        datetime_original="2025:05:18 08:00:00",
        offset_original="+02:00",
    )
    write_jpeg_with_exif(
        source / "ende.jpg",
        datetime_original="2025:05:18 18:00:00",
        offset_original="+02:00",
    )
    first = _index_and_sync(open_project, source)
    ids = [photo.source_file_id for photo in first.days[0].photos]
    with open_project.session_factory() as session:
        empty = create_section(session, first.trip_id, [ids[0]], kind=KIND_MOVEMENT)
        mixed = create_section(
            session,
            first.trip_id,
            [ids[1]],
            kind=KIND_MOVEMENT,
            mode="train,bus",
        )
        session.commit()
        assert empty.mode is None
        assert mixed.mode == "bus,train"


def test_update_section_kind_switches_stay_and_transfer(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "ort.jpg",
        datetime_original="2025:05:19 10:00:00",
        offset_original="+02:00",
    )
    first = _index_and_sync(open_project, source)
    ids = [photo.source_file_id for photo in first.days[0].photos]
    with open_project.session_factory() as session:
        section = create_section(
            session,
            first.trip_id,
            ids,
            kind=KIND_STAY,
            title="Bozen",
            location_name="Bozen",
        )
        session.commit()
        section_id = section.id
        update_section_kind(session, section_id, KIND_MOVEMENT, mode="train")
        session.commit()
        project = session.get(Project, open_project.project_id)
        assert project is not None
        loaded = load_timeline(session, project)
    assert loaded is not None
    entry = loaded.entries[0].section
    assert entry is not None
    assert entry.kind == KIND_MOVEMENT
    assert entry.mode == "train"
    assert entry.location_name is None
    with open_project.session_factory() as session:
        update_section_kind(session, section_id, KIND_STAY)
        session.commit()
        project = session.get(Project, open_project.project_id)
        assert project is not None
        loaded = load_timeline(session, project)
    assert loaded is not None
    back = loaded.entries[0].section
    assert back is not None
    assert back.kind == KIND_STAY
    assert back.mode is None


def test_apply_pending_sections_is_preview_only() -> None:
    from travelcore.timeline.types import TimelinePhoto, TimelineSection, TimelineSnapshot

    morning = datetime(2025, 5, 14, 9, 0, tzinfo=UTC)
    evening = datetime(2025, 5, 14, 18, 0, tzinfo=UTC)
    first = TimelinePhoto(
        source_file_id=1,
        filename="morgen.jpg",
        path="morgen.jpg",
        thumbnail_path=Path("."),
        captured_at=morning,
        used_in_journal=False,
        is_cover=False,
        is_favorite=False,
        gps_latitude=None,
        gps_longitude=None,
    )
    second = TimelinePhoto(
        source_file_id=2,
        filename="abend.jpg",
        path="abend.jpg",
        thumbnail_path=Path("."),
        captured_at=evening,
        used_in_journal=False,
        is_cover=False,
        is_favorite=False,
        gps_latitude=None,
        gps_longitude=None,
    )
    day_section = TimelineSection(
        id=10,
        kind=KIND_DAY,
        mode=None,
        title="14.05.2025",
        notes=None,
        started_at=morning,
        ended_at=morning,
        location_name=None,
        location_from=None,
        location_to=None,
        origin="auto",
        items=(first, second),
    )
    snapshot = TimelineSnapshot(
        trip_id=1, title="Reise", origin="auto", days=(), sections=(day_section,), entries=()
    )
    shown = apply_pending_sections(
        snapshot,
        [
            PendingSectionSpec(
                local_id=-1,
                source_file_ids=(1,),
                kind=KIND_STAY,
                title="Markt",
                youtube_urls=("https://youtu.be/dQw4w9WgXcQ",),
                leonardo_urls=("https://de.dhv-leonardo.de/track/1",),
                cover_source_file_id=1,
            )
        ],
    )
    assert snapshot.sections[0].items == (first, second)
    assert len(shown.sections) == 2
    pending = shown.sections[0]
    remaining = shown.sections[1]
    assert pending.id == -1
    assert pending.title == "Markt"
    assert pending.youtube_urls == ("https://youtu.be/dQw4w9WgXcQ",)
    assert pending.leonardo_urls == ("https://de.dhv-leonardo.de/track/1",)
    assert pending.cover_source_file_id == 1
    assert remaining.kind == KIND_DAY
    assert [photo.filename for photo in remaining.items] == ["abend.jpg"]


def test_apply_pending_empty_section_keeps_manual_date() -> None:
    from travelcore.timeline.types import TimelinePhoto, TimelineSection, TimelineSnapshot

    morning = datetime(2025, 5, 14, 9, 0, tzinfo=UTC)
    first = TimelinePhoto(
        source_file_id=1,
        filename="morgen.jpg",
        path="morgen.jpg",
        thumbnail_path=Path("."),
        captured_at=morning,
        used_in_journal=False,
        is_cover=False,
        is_favorite=False,
        gps_latitude=None,
        gps_longitude=None,
    )
    day_section = TimelineSection(
        id=10,
        kind=KIND_DAY,
        mode=None,
        title="14.05.2025",
        notes=None,
        started_at=morning,
        ended_at=morning,
        location_name=None,
        location_from=None,
        location_to=None,
        origin="auto",
        items=(first,),
    )
    snapshot = TimelineSnapshot(
        trip_id=1, title="Reise", origin="auto", days=(), sections=(day_section,), entries=()
    )
    stamp = datetime(2025, 8, 20, 12, 0, tzinfo=UTC)
    shown = apply_pending_sections(
        snapshot,
        [
            PendingSectionSpec(
                local_id=-2,
                source_file_ids=(),
                kind=KIND_STAY,
                title="Leer",
                started_at=stamp,
                ended_at=stamp,
            )
        ],
    )
    pending = next(section for section in shown.sections if section.id == -2)
    assert pending.title == "Leer"
    assert pending.items == ()
    assert pending.started_at == stamp
    assert snapshot.sections[0].items == (first,)


def test_apply_pending_empty_stay_keeps_range() -> None:
    from travelcore.timeline.types import TimelineSnapshot

    snapshot = TimelineSnapshot(trip_id=1, title="Reise", origin="auto", days=(), sections=(), entries=())
    started, ended = span_for_manual_dates(KIND_STAY, date(2025, 8, 1), date(2025, 8, 10))
    shown = apply_pending_sections(
        snapshot,
        [
            PendingSectionSpec(
                local_id=-3,
                source_file_ids=(),
                kind=KIND_STAY,
                title="Urlaub",
                started_at=started,
                ended_at=ended,
            )
        ],
    )
    pending = next(section for section in shown.sections if section.id == -3)
    assert pending.started_at == started
    assert pending.ended_at == ended
    assert shown.entries[0].section is pending


def test_set_entry_cover_on_day_and_section(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "morgen.jpg",
        datetime_original="2025:05:14 09:00:00",
        offset_original="+02:00",
    )
    write_jpeg_with_exif(
        source / "abend.jpg",
        datetime_original="2025:05:14 18:00:00",
        offset_original="+02:00",
    )
    first = _index_and_sync(open_project, source)
    day_section = next(entry.section for entry in first.entries if entry.section is not None)
    assert day_section is not None
    ids = [photo.source_file_id for photo in first.days[0].photos]
    with open_project.session_factory() as session:
        set_entry_cover(session, "section", day_section.id, ids[0])
        section = create_section(
            session,
            first.trip_id,
            ids,
            kind=KIND_STAY,
            title="Berlin",
            cover_source_file_id=ids[1],
        )
        session.commit()
        assert section.cover_source_file_id == ids[1]

    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        snapshot = load_timeline(session, project)
        assert snapshot is not None
        stay = next(item for item in snapshot.sections if item.kind == KIND_STAY)
        set_entry_cover(session, "section", stay.id, None)
        session.commit()
        cleared = load_timeline(session, project)

    assert stay.cover_source_file_id == ids[1]
    assert cleared is not None
    cleared_stay = next(item for item in cleared.sections if item.kind == KIND_STAY)
    assert cleared_stay.cover_source_file_id is None


def test_set_entry_cover_accepts_gps_track(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "foto.jpg",
        datetime_original="2025:05:14 09:00:00",
        offset_original="+02:00",
    )
    write_gpx(
        source / "spur.gpx",
        [
            (46.0, 11.0, None, "2025-05-14T08:00:00+02:00"),
            (46.1, 11.1, None, "2025-05-14T09:00:00+02:00"),
        ],
    )
    snapshot = _index_and_sync(open_project, source)
    day = snapshot.days[0]
    track = next(photo for photo in day.photos if photo.filename.endswith(".gpx"))
    with open_project.session_factory() as session:
        set_entry_cover(session, "day", day.id, track.source_file_id)
        session.commit()
        project = session.get(Project, open_project.project_id)
        assert project is not None
        loaded = load_timeline(session, project)
    assert loaded is not None
    assert loaded.days[0].cover_source_file_id == track.source_file_id


def test_sync_assigns_media_to_day_sections(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "eins.jpg",
        datetime_original="2025:06:01 09:00:00",
        offset_original="+02:00",
    )
    write_jpeg_with_exif(
        source / "zwei.jpg",
        datetime_original="2025:06:02 18:00:00",
        offset_original="+02:00",
    )
    snapshot = _index_and_sync(open_project, source)
    assert [entry.card_kind for entry in snapshot.entries] == [KIND_DAY, KIND_DAY]
    assert {item.filename for item in snapshot.entries[0].section.items} == {"eins.jpg"}
    assert {item.filename for item in snapshot.entries[1].section.items} == {"zwei.jpg"}


def test_parked_media_stay_out_of_days_on_resync(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "foto.jpg",
        datetime_original="2025:06:03 10:00:00",
        offset_original="+02:00",
    )
    first = _index_and_sync(open_project, source)
    photo_id = first.days[0].photos[0].source_file_id
    with open_project.session_factory() as session:
        park_media(session, [photo_id])
        session.commit()
        project = session.get(Project, open_project.project_id)
        assert project is not None
        snapshot = sync_timeline(session, project)
        session.commit()
    assert snapshot.entries == ()
    assert snapshot.days[0].photos[0].source_file_id == photo_id


def test_move_members_assigns_parked_file_to_section(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "eins.jpg",
        datetime_original="2025:06:01 09:00:00",
        offset_original="+02:00",
    )
    write_jpeg_with_exif(
        source / "zwei.jpg",
        datetime_original="2025:06:02 10:00:00",
        offset_original="+02:00",
    )
    first = _index_and_sync(open_project, source)
    by_name = {photo.filename: photo for day in first.days for photo in day.photos}
    day_a = first.entries[0].section
    assert day_a is not None
    parked_id = by_name["zwei.jpg"].source_file_id
    with open_project.session_factory() as session:
        park_media(session, [parked_id])
        session.commit()
        move_members(session, day_a.id, [parked_id])
        session.commit()
        row = session.get(SourceFile, parked_id)
        assert row is not None
        assert row.parked is False
        member = session.scalar(select(SectionMember).where(SectionMember.source_file_id == parked_id))
        assert member is not None
        assert member.section_id == day_a.id


def test_scattered_positions_do_not_coincide() -> None:
    points = scattered_positions((46.0, 11.0), 4)
    assert len(points) == 4
    assert len(set(points)) == 4
    for index, left in enumerate(points):
        for right in points[index + 1 :]:
            distance = haversine_m(left[0], left[1], right[0], right[1])
            assert 5.0 < distance < 80.0


def test_move_members_keeps_original_gps_on_map(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "ort.jpg",
        datetime_original="2025:08:14 10:00:00",
        offset_original="+02:00",
        latitude=(46.0, 0.0, 0.0),
        longitude=(11.0, 0.0, 0.0),
    )
    write_jpeg_with_exif(
        source / "dokument.jpg",
        datetime_original="2025:08:14 11:00:00",
        offset_original="+02:00",
        latitude=(52.5, 0.0, 0.0),
        longitude=(13.4, 0.0, 0.0),
    )
    first = _index_and_sync(open_project, source)
    by_name = {item.filename: item for item in first.entries[0].section.items}
    with open_project.session_factory() as session:
        stay = create_section(
            session, first.trip_id, [by_name["ort.jpg"].source_file_id], kind=KIND_STAY, title="Museum"
        )
        session.commit()
        move_members(session, stay.id, [by_name["dokument.jpg"].source_file_id])
        session.commit()
        project = session.get(Project, open_project.project_id)
        assert project is not None
        snapshot = load_timeline(session, project)
        row = session.get(SourceFile, by_name["dokument.jpg"].source_file_id)
    stay_entry = next(entry for entry in snapshot.entries if entry.card_kind == KIND_STAY)
    doc = next(item for item in stay_entry.section.items if item.filename == "dokument.jpg")
    assert row is not None
    assert row.gps_latitude is not None and abs(row.gps_latitude - 52.5) < 0.01
    assert doc.position_inherited is False
    assert doc.display_latitude is not None and abs(doc.display_latitude - 52.5) < 0.01


def test_move_members_adopts_section_position_and_scatters(
    open_project: OpenProject, tmp_path: Path
) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "ort.jpg",
        datetime_original="2025:08:15 10:00:00",
        offset_original="+02:00",
        latitude=(46.0, 0.0, 0.0),
        longitude=(11.0, 0.0, 0.0),
    )
    write_jpeg_with_exif(
        source / "ausweis.jpg",
        datetime_original="2025:08:15 11:00:00",
        offset_original="+02:00",
        latitude=(52.5, 0.0, 0.0),
        longitude=(13.4, 0.0, 0.0),
    )
    write_jpeg_with_exif(
        source / "ticket.jpg",
        datetime_original="2025:08:15 11:05:00",
        offset_original="+02:00",
        latitude=(52.5, 0.0, 0.0),
        longitude=(13.4, 0.0, 0.0),
    )
    first = _index_and_sync(open_project, source)
    by_name = {item.filename: item for item in first.entries[0].section.items}
    doc_ids = [by_name["ausweis.jpg"].source_file_id, by_name["ticket.jpg"].source_file_id]
    with open_project.session_factory() as session:
        stay = create_section(
            session, first.trip_id, [by_name["ort.jpg"].source_file_id], kind=KIND_STAY, title="Museum"
        )
        session.commit()
        move_members(session, stay.id, doc_ids, keep_gps=False)
        session.commit()
        project = session.get(Project, open_project.project_id)
        assert project is not None
        snapshot = load_timeline(session, project)
        originals = [session.get(SourceFile, item_id) for item_id in doc_ids]
    stay_entry = next(entry for entry in snapshot.entries if entry.card_kind == KIND_STAY)
    docs = [item for item in stay_entry.section.items if item.filename in {"ausweis.jpg", "ticket.jpg"}]
    assert len(docs) == 2
    for row in originals:
        assert row is not None
        assert row.gps_latitude is not None and abs(row.gps_latitude - 52.5) < 0.01
    for item in docs:
        assert item.position_inherited is True
        assert item.display_latitude is not None
        assert haversine_m(item.display_latitude, item.display_longitude or 0.0, 46.0, 11.0) < 80.0
    left, right = docs
    assert haversine_m(
        left.display_latitude or 0.0,
        left.display_longitude or 0.0,
        right.display_latitude or 0.0,
        right.display_longitude or 0.0,
    ) > 5.0


def test_move_to_other_day_keeps_captured_at(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "a.jpg",
        datetime_original="2025:06:04 09:00:00",
        offset_original="+02:00",
    )
    write_jpeg_with_exif(
        source / "b.jpg",
        datetime_original="2025:06:05 18:00:00",
        offset_original="+02:00",
    )
    first = _index_and_sync(open_project, source)
    by_name = {photo.filename: photo for day in first.days for photo in day.photos}
    day_a = first.entries[0].section
    day_b = first.entries[1].section
    assert day_a is not None and day_b is not None
    original = by_name["b.jpg"].captured_at
    with open_project.session_factory() as session:
        move_members(session, day_a.id, [by_name["b.jpg"].source_file_id])
        session.commit()
        project = session.get(Project, open_project.project_id)
        assert project is not None
        snapshot = load_timeline(session, project)
        row = session.get(SourceFile, by_name["b.jpg"].source_file_id)
        member = session.scalar(
            select(SectionMember).where(SectionMember.source_file_id == by_name["b.jpg"].source_file_id)
        )
    assert snapshot is not None
    assert row is not None
    assert row.captured_at == original
    assert member is not None
    assert member.journal_at is not None
    assert member.journal_at.date() == datetime(2025, 6, 4, tzinfo=UTC).date()
    assert {item.filename for item in snapshot.entries[0].section.items} == {"a.jpg", "b.jpg"}
    assert len(snapshot.entries) == 1


def test_snap_clock_to_section_clamps_into_span() -> None:
    from types import SimpleNamespace

    from travelcore.timeline.journal import snap_clock_to_section

    start = datetime(2025, 6, 1, tzinfo=UTC)
    end = datetime(2025, 6, 10, tzinfo=UTC)
    stay = SimpleNamespace(kind=KIND_STAY, started_at=start, ended_at=end)
    inside = datetime(2025, 6, 5, 14, 30, tzinfo=UTC)
    assert snap_clock_to_section(inside, stay) == inside
    before = snap_clock_to_section(datetime(2025, 5, 1, 8, 0, tzinfo=UTC), stay)
    assert before is not None
    assert before.date() == date(2025, 6, 1)
    assert before.hour == 8
    after = snap_clock_to_section(datetime(2025, 6, 20, 11, 0, tzinfo=UTC), stay)
    assert after is not None
    assert after.date() == date(2025, 6, 10)
    tag = SimpleNamespace(kind=KIND_DAY, started_at=start, ended_at=start)
    snapped_tag = snap_clock_to_section(datetime(2025, 6, 20, 11, 0, tzinfo=UTC), tag)
    assert snapped_tag is not None
    assert snapped_tag.date() == date(2025, 6, 1)


def test_move_members_adopts_target_section_date(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "stay.jpg",
        datetime_original="2025:06:01 09:00:00",
        offset_original="+02:00",
    )
    write_jpeg_with_exif(
        source / "inside.jpg",
        datetime_original="2025:06:05 14:30:00",
        offset_original="+02:00",
    )
    write_jpeg_with_exif(
        source / "late.jpg",
        datetime_original="2025:06:20 11:00:00",
        offset_original="+02:00",
    )
    first = _index_and_sync(open_project, source)
    by_name = {photo.filename: photo for day in first.days for photo in day.photos}
    start, end = span_for_manual_dates(KIND_STAY, date(2025, 6, 1), date(2025, 6, 10))
    with open_project.session_factory() as session:
        stay = create_section(
            session, first.trip_id, [by_name["stay.jpg"].source_file_id], kind=KIND_STAY, title="Hotel"
        )
        set_section_span(session, stay.id, start, end)
        session.commit()
        move_members(session, stay.id, [by_name["late.jpg"].source_file_id])
        session.commit()
        late = session.scalar(
            select(SectionMember).where(
                SectionMember.source_file_id == by_name["late.jpg"].source_file_id
            )
        )
        move_members(session, stay.id, [by_name["inside.jpg"].source_file_id])
        session.commit()
        inside = session.scalar(
            select(SectionMember).where(
                SectionMember.source_file_id == by_name["inside.jpg"].source_file_id
            )
        )
        captured = session.get(SourceFile, by_name["late.jpg"].source_file_id)
    assert inside is not None and inside.journal_at is not None
    assert inside.journal_at.date() == date(2025, 6, 5)
    assert late is not None and late.journal_at is not None
    assert late.journal_at.date() == date(2025, 6, 10)
    assert captured is not None
    assert captured.captured_at is not None
    assert captured.captured_at.date() == date(2025, 6, 20)


def test_dissolve_multi_day_stay_splits_by_original_date(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "t1.jpg",
        datetime_original="2025:06:06 09:00:00",
        offset_original="+02:00",
    )
    write_jpeg_with_exif(
        source / "t2.jpg",
        datetime_original="2025:06:07 18:00:00",
        offset_original="+02:00",
    )
    first = _index_and_sync(open_project, source)
    ids = [photo.source_file_id for day in first.days for photo in day.photos]
    with open_project.session_factory() as session:
        stay = create_section(session, first.trip_id, ids, kind=KIND_STAY, title="Ausflug")
        session.commit()
        dissolve_section(session, stay.id)
        session.commit()
        project = session.get(Project, open_project.project_id)
        assert project is not None
        snapshot = load_timeline(session, project)
    assert snapshot is not None
    assert [entry.card_kind for entry in snapshot.entries] == [KIND_DAY, KIND_DAY]
    assert snapshot.entries[0].section.items[0].filename == "t1.jpg"
    assert snapshot.entries[1].section.items[0].filename == "t2.jpg"


def test_update_section_kind_rejects_multi_day_stay_to_tag(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "t1.jpg",
        datetime_original="2025:06:08 09:00:00",
        offset_original="+02:00",
    )
    write_jpeg_with_exif(
        source / "t2.jpg",
        datetime_original="2025:06:09 18:00:00",
        offset_original="+02:00",
    )
    first = _index_and_sync(open_project, source)
    ids = [photo.source_file_id for day in first.days for photo in day.photos]
    with open_project.session_factory() as session:
        stay = create_section(session, first.trip_id, ids, kind=KIND_STAY, title="Lang")
        session.commit()
        try:
            update_section_kind(session, stay.id, KIND_DAY)
            raise AssertionError("expected ProjectError")
        except ProjectError as exc:
            assert "Kalendertag" in str(exc)


def test_set_journal_at_moves_clip_to_other_day(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "a.jpg",
        datetime_original="2025:07:01 09:00:00",
        offset_original="+02:00",
    )
    write_jpeg_with_exif(
        source / "b.jpg",
        datetime_original="2025:07:01 18:00:00",
        offset_original="+02:00",
    )
    first = _index_and_sync(open_project, source)
    by_name = {item.filename: item for item in first.entries[0].section.items}
    original = by_name["b.jpg"].captured_at
    with open_project.session_factory() as session:
        set_journal_at(session, [by_name["b.jpg"].source_file_id], datetime(2025, 7, 2, 12, 0, tzinfo=UTC))
        session.commit()
        project = session.get(Project, open_project.project_id)
        assert project is not None
        snapshot = load_timeline(session, project)
        row = session.get(SourceFile, by_name["b.jpg"].source_file_id)
        member = session.scalar(
            select(SectionMember).where(SectionMember.source_file_id == by_name["b.jpg"].source_file_id)
        )
    assert snapshot is not None
    assert row is not None
    assert row.captured_at == original
    assert member is not None
    assert aware(member.journal_at) == datetime(2025, 7, 2, 12, 0, tzinfo=UTC)
    assert [entry.card_kind for entry in snapshot.entries] == [KIND_DAY, KIND_DAY]
    names = [{item.filename for item in entry.section.items} for entry in snapshot.entries]
    assert names == [{"a.jpg"}, {"b.jpg"}]


def test_reset_journal_restores_original_day(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "foto.jpg",
        datetime_original="2025:07:03 09:00:00",
        offset_original="+02:00",
    )
    first = _index_and_sync(open_project, source)
    photo_id = first.entries[0].section.items[0].source_file_id
    with open_project.session_factory() as session:
        set_journal_at(session, [photo_id], datetime(2025, 7, 4, 15, 0, tzinfo=UTC))
        session.commit()
        reset_journal(session, [photo_id])
        session.commit()
        project = session.get(Project, open_project.project_id)
        assert project is not None
        snapshot = load_timeline(session, project)
        member = session.scalar(select(SectionMember).where(SectionMember.source_file_id == photo_id))
        row = session.get(SourceFile, photo_id)
    assert snapshot is not None
    assert len(snapshot.entries) == 1
    assert snapshot.entries[0].section.items[0].filename == "foto.jpg"
    assert member is not None and row is not None
    assert member.journal_at == row.captured_at


def test_dissolve_after_journal_move_uses_journal_date(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "t1.jpg",
        datetime_original="2025:07:05 09:00:00",
        offset_original="+02:00",
    )
    write_jpeg_with_exif(
        source / "t2.jpg",
        datetime_original="2025:07:05 18:00:00",
        offset_original="+02:00",
    )
    first = _index_and_sync(open_project, source)
    ids = [item.source_file_id for item in first.entries[0].section.items]
    by_name = {item.filename: item.source_file_id for item in first.entries[0].section.items}
    with open_project.session_factory() as session:
        stay = create_section(session, first.trip_id, ids, kind=KIND_STAY, title="Ausflug")
        session.commit()
        set_journal_at(session, [by_name["t2.jpg"]], datetime(2025, 7, 6, 10, 0, tzinfo=UTC))
        session.commit()
        dissolve_section(session, stay.id)
        session.commit()
        project = session.get(Project, open_project.project_id)
        assert project is not None
        snapshot = load_timeline(session, project)
    assert snapshot is not None
    assert [entry.card_kind for entry in snapshot.entries] == [KIND_DAY, KIND_DAY]
    assert snapshot.entries[0].section.items[0].filename == "t1.jpg"
    assert snapshot.entries[1].section.items[0].filename == "t2.jpg"


def test_resync_keeps_existing_journal_at(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "foto.jpg",
        datetime_original="2025:07:07 09:00:00",
        offset_original="+02:00",
    )
    first = _index_and_sync(open_project, source)
    photo_id = first.entries[0].section.items[0].source_file_id
    moved = datetime(2025, 7, 8, 11, 0, tzinfo=UTC)
    with open_project.session_factory() as session:
        set_journal_at(session, [photo_id], moved)
        session.commit()
        project = session.get(Project, open_project.project_id)
        assert project is not None
        sync_timeline(session, project)
        session.commit()
        member = session.scalar(select(SectionMember).where(SectionMember.source_file_id == photo_id))
    assert member is not None
    assert aware(member.journal_at) == moved


def test_tag_without_gps_inherits_cover_position(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "mit.jpg",
        datetime_original="2025:07:09 09:00:00",
        offset_original="+02:00",
        latitude=(46.0, 0.0, 0.0),
        longitude=(11.0, 0.0, 0.0),
    )
    write_jpeg_with_exif(
        source / "ohne.jpg",
        datetime_original="2025:07:09 10:00:00",
        offset_original="+02:00",
    )
    snapshot = _index_and_sync(open_project, source)
    by_name = {item.filename: item for item in snapshot.entries[0].section.items}
    located = by_name["mit.jpg"]
    inherited = by_name["ohne.jpg"]
    assert located.gps_latitude is not None
    assert inherited.gps_latitude is None
    assert inherited.position_inherited is True
    assert inherited.display_latitude == located.gps_latitude
    assert inherited.display_longitude == located.gps_longitude


def test_stay_without_gps_inherits_place(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "ohne.jpg",
        datetime_original="2025:07:10 09:00:00",
        offset_original="+02:00",
    )
    first = _index_and_sync(open_project, source)
    photo_id = first.entries[0].section.items[0].source_file_id
    day_id = first.days[0].id
    with open_project.session_factory() as session:
        create_section(session, first.trip_id, [photo_id], kind=KIND_STAY, title="Hotel")
        session.add(
            Place(
                day_id=day_id,
                name="Hotel",
                latitude=47.5,
                longitude=12.25,
                confirmed=True,
                origin="manual",
            )
        )
        session.commit()
        project = session.get(Project, open_project.project_id)
        assert project is not None
        snapshot = load_timeline(session, project)
    assert snapshot is not None
    stay_entry = next(entry for entry in snapshot.entries if entry.card_kind == KIND_STAY)
    item = stay_entry.section.items[0]
    assert item.gps_latitude is None
    assert item.position_inherited is True
    assert item.display_latitude == 47.5
    assert item.display_longitude == 12.25


def test_transfer_without_gps_inherits_track_time(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "ohne.jpg",
        datetime_original="2025:07:11 11:00:00",
        offset_original="+00:00",
    )
    write_gpx(
        source / "route.gpx",
        [
            (46.0, 11.0, None, "2025-07-11T10:00:00Z"),
            (48.0, 13.0, None, "2025-07-11T12:00:00Z"),
        ],
    )
    first = _index_and_sync(open_project, source)
    by_name = {item.filename: item.source_file_id for entry in first.entries for item in entry.section.items}
    with open_project.session_factory() as session:
        create_section(
            session,
            first.trip_id,
            [by_name["ohne.jpg"], by_name["route.gpx"]],
            kind=KIND_MOVEMENT,
            title="Fahrt",
        )
        session.commit()
        project = session.get(Project, open_project.project_id)
        assert project is not None
        snapshot = load_timeline(session, project)
        photo = session.get(SourceFile, by_name["ohne.jpg"])
    assert snapshot is not None
    assert photo is not None
    assert photo.gps_latitude is None
    movement = next(entry for entry in snapshot.entries if entry.card_kind == KIND_MOVEMENT)
    item = next(photo for photo in movement.section.items if photo.filename == "ohne.jpg")
    assert item.position_inherited is True
    assert item.display_latitude is not None
    assert abs(item.display_latitude - 47.0) < 0.01
    assert abs(item.display_longitude - 12.0) < 0.01


def test_sort_members_by_journal_does_not_change_clock(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "a.jpg",
        datetime_original="2025:07:12 09:00:00",
        offset_original="+02:00",
    )
    write_jpeg_with_exif(
        source / "b.jpg",
        datetime_original="2025:07:12 10:00:00",
        offset_original="+02:00",
    )
    first = _index_and_sync(open_project, source)
    section_id = first.entries[0].section.id
    by_name = {item.filename: item.source_file_id for item in first.entries[0].section.items}
    with open_project.session_factory() as session:
        set_journal_at(session, [by_name["a.jpg"]], datetime(2025, 7, 12, 18, 0, tzinfo=UTC))
        session.commit()
        sort_members_by_journal(session, section_id)
        session.commit()
        members = list(
            session.scalars(
                select(SectionMember)
                .where(SectionMember.section_id == section_id)
                .order_by(SectionMember.sort_index.asc())
            )
        )
        clocks = {member.source_file_id: member.journal_at for member in members}
    assert [member.source_file_id for member in members] == [by_name["b.jpg"], by_name["a.jpg"]]
    assert aware(clocks[by_name["a.jpg"]]) == datetime(2025, 7, 12, 18, 0, tzinfo=UTC)


def test_section_cards_follow_calendar_not_creation_order(open_project: OpenProject, tmp_path: Path) -> None:
    later = tmp_path / "later"
    later.mkdir()
    write_jpeg_with_exif(
        later / "spaeter.jpg",
        datetime_original="2025:08:20 12:00:00",
        offset_original="+02:00",
    )
    first = _index_and_sync(open_project, later)
    later_id = first.entries[0].section.items[0].source_file_id
    with open_project.session_factory() as session:
        create_section(session, first.trip_id, [later_id], kind=KIND_STAY, title="Spaeter")
        session.commit()

    earlier = tmp_path / "earlier"
    earlier.mkdir()
    write_jpeg_with_exif(
        earlier / "frueher.jpg",
        datetime_original="2025:08:01 09:00:00",
        offset_original="+02:00",
    )
    snapshot = _index_and_sync(open_project, earlier)
    names = [
        entry.section.items[0].filename
        for entry in snapshot.entries
        if entry.section is not None and entry.section.items
    ]
    assert names == ["frueher.jpg", "spaeter.jpg"]
    assert [entry.card_kind for entry in snapshot.entries] == [KIND_DAY, KIND_STAY]


def test_section_card_items_follow_journal_time(open_project: OpenProject, tmp_path: Path) -> None:
    evening = tmp_path / "evening"
    evening.mkdir()
    write_jpeg_with_exif(
        evening / "abend.jpg",
        datetime_original="2025:08:12 18:00:00",
        offset_original="+02:00",
    )
    _index_and_sync(open_project, evening)

    morning = tmp_path / "morning"
    morning.mkdir()
    write_jpeg_with_exif(
        morning / "morgen.jpg",
        datetime_original="2025:08:12 09:00:00",
        offset_original="+02:00",
    )
    snapshot = _index_and_sync(open_project, morning)
    assert len(snapshot.entries) == 1
    assert snapshot.entries[0].section is not None
    assert [item.filename for item in snapshot.entries[0].section.items] == ["morgen.jpg", "abend.jpg"]


def _index_and_sync(open_project: OpenProject, source: Path) -> TimelineSnapshot:
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        FileIndexer().index(session, project, source, project_dir=open_project.directory)
        session.commit()

    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        snapshot = sync_timeline(session, project, thumbs_dir=open_project.directory / "thumbnails")
        session.commit()
        return snapshot
