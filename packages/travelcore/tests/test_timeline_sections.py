from datetime import UTC, datetime
from pathlib import Path

from gpx_fixtures import write_gpx
from jpeg_fixtures import write_jpeg_with_exif
from sqlalchemy import select

from travelcore.database.models import Project, SectionMember
from travelcore.database.project_store import OpenProject
from travelcore.media.indexer import FileIndexer
from travelcore.timeline import (
    KIND_DAY,
    KIND_MOVEMENT,
    KIND_STAY,
    PendingSectionSpec,
    apply_pending_sections,
    create_section,
    dissolve_section,
    expand_range_selection,
    format_section_duration,
    format_section_span,
    format_section_when,
    load_timeline,
    parse_modes,
    serialize_modes,
    set_entry_cover,
    sync_timeline,
    update_section_kind,
)
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


def test_dissolve_section_returns_files_to_leftover_days(open_project: OpenProject, tmp_path: Path) -> None:
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
    assert snapshot.sections == ()
    assert members == []
    leftover = next(entry.leftover_day for entry in snapshot.entries if entry.leftover_day is not None)
    assert leftover is not None
    assert {photo.filename for photo in leftover.photos} == {"morgen.jpg", "abend.jpg"}


def test_leftover_day_sits_between_sections(open_project: OpenProject, tmp_path: Path) -> None:
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
    assert len(members) == 2
    leftover_names = [
        entry.leftover_day.photos[0].filename for entry in snapshot.entries if entry.leftover_day is not None
    ]
    assert leftover_names == ["anreise.jpg", "weiter.jpg"]
    assert snapshot.entries[0].leftover_day is not None
    assert snapshot.entries[0].card_kind == KIND_DAY
    assert snapshot.entries[1].section is not None
    assert snapshot.entries[1].card_kind == KIND_STAY
    assert snapshot.entries[1].section.title == "Besuch von Berlin"
    assert format_section_span(
        snapshot.entries[1].section.started_at, snapshot.entries[1].section.ended_at
    ) == ("von 14.05.2025 bis 15.05.2025")
    assert snapshot.entries[2].leftover_day is not None
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
    leftover = snapshot.entries[0].leftover_day
    section = snapshot.entries[1].section
    assert leftover is not None
    assert leftover.photos[0].filename == "stadt.jpg"
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
    from travelcore.timeline.types import TimelineDay, TimelinePhoto, TimelineSnapshot

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
    day = TimelineDay(
        id=10,
        day_index=0,
        date=morning.date(),
        title=None,
        notes=None,
        origin="auto",
        photos=(first, second),
    )
    snapshot = TimelineSnapshot(trip_id=1, title="Reise", origin="auto", days=(day,), sections=(), entries=())
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
    assert snapshot.sections == ()
    assert len(shown.sections) == 1
    assert shown.sections[0].id == -1
    assert shown.sections[0].title == "Markt"
    assert shown.sections[0].youtube_urls == ("https://youtu.be/dQw4w9WgXcQ",)
    assert shown.sections[0].leonardo_urls == ("https://de.dhv-leonardo.de/track/1",)
    assert shown.sections[0].cover_source_file_id == 1
    leftover = next(entry.leftover_day for entry in shown.entries if entry.leftover_day is not None)
    assert leftover is not None
    assert [photo.filename for photo in leftover.photos] == ["abend.jpg"]


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
    day_id = first.days[0].id
    ids = [photo.source_file_id for photo in first.days[0].photos]
    with open_project.session_factory() as session:
        set_entry_cover(session, "day", day_id, ids[0])
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
        set_entry_cover(session, "section", snapshot.sections[0].id, None)
        session.commit()
        cleared = load_timeline(session, project)

    assert snapshot.days[0].cover_source_file_id == ids[0]
    assert snapshot.sections[0].cover_source_file_id == ids[1]
    assert cleared is not None
    assert cleared.sections[0].cover_source_file_id is None


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
