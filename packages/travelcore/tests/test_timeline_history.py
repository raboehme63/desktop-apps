from datetime import date
from pathlib import Path

from jpeg_fixtures import write_jpeg_with_exif
from sqlalchemy import select

from travelcore.database.models import Project, SectionMember, SourceFile, TripSection
from travelcore.database.project_store import OpenProject
from travelcore.media.indexer import FileIndexer
from travelcore.timeline import (
    KIND_MOVEMENT,
    KIND_STAY,
    capture_placement_edit,
    capture_section_edit,
    create_section,
    delete_section,
    dissolve_section,
    load_timeline,
    move_members,
    park_media,
    photo_sort_status,
    restore_journal_edit,
    save_section_text,
    section_pin,
    set_photo_sort_status,
    set_section_pin,
    set_section_span,
    span_for_manual_dates,
    sync_timeline,
    update_section_kind,
)
from travelcore.timeline.types import TimelineSnapshot


def test_restore_park_brings_back_auto_day(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "eins.jpg",
        datetime_original="2025:06:01 09:00:00",
        offset_original="+02:00",
    )
    first = _index_and_sync(open_project, source)
    photo_id = first.days[0].photos[0].source_file_id
    day = next(entry.section for entry in first.entries if entry.section is not None)
    assert day is not None
    with open_project.session_factory() as session:
        before = capture_placement_edit(session, [photo_id])
        park_media(session, [photo_id])
        session.commit()
        assert session.get(TripSection, day.id) is None
        restore_journal_edit(session, before)
        session.commit()
        section = session.get(TripSection, day.id)
        member = session.scalar(select(SectionMember).where(SectionMember.source_file_id == photo_id))
        row = session.get(SourceFile, photo_id)
        assert section is not None
        assert member is not None
        assert member.section_id == day.id
        assert row is not None
        assert row.parked is False


def test_restore_move_members_returns_file(open_project: OpenProject, tmp_path: Path) -> None:
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
    moved_id = by_name["zwei.jpg"].source_file_id
    with open_project.session_factory() as session:
        before = capture_placement_edit(session, [moved_id], extra_section_ids=(day_a.id,))
        move_members(session, day_a.id, [moved_id])
        session.commit()
        member = session.scalar(select(SectionMember).where(SectionMember.source_file_id == moved_id))
        assert member is not None
        assert member.section_id == day_a.id
        restore_journal_edit(session, before)
        session.commit()
        member = session.scalar(select(SectionMember).where(SectionMember.source_file_id == moved_id))
        assert member is not None
        assert member.section_id != day_a.id


def test_restore_section_kind_and_span(open_project: OpenProject, tmp_path: Path) -> None:
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
        section = create_section(session, first.trip_id, ids, kind=KIND_STAY, title="Bozen")
        session.commit()
        section_id = section.id
        before = capture_section_edit(session, section_id)
        assert before is not None
        update_section_kind(session, section_id, KIND_MOVEMENT, mode="train")
        session.commit()
        restore_journal_edit(session, before)
        session.commit()
        project = session.get(Project, open_project.project_id)
        assert project is not None
        loaded = load_timeline(session, project)
    entry = loaded.entries[0].section
    assert entry is not None
    assert entry.kind == KIND_STAY
    assert entry.title == "Bozen"
    with open_project.session_factory() as session:
        before = capture_section_edit(session, section_id)
        assert before is not None
        started, ended = span_for_manual_dates(KIND_STAY, date(2025, 5, 19), date(2025, 5, 21))
        set_section_span(session, section_id, started, ended)
        session.commit()
        restore_journal_edit(session, before)
        session.commit()
        row = session.get(TripSection, section_id)
        assert row is not None
        assert row.started_at is not None
        assert row.started_at.date() == date(2025, 5, 19)
        assert row.ended_at is not None
        assert row.ended_at.date() == date(2025, 5, 19)


def test_restore_pin_and_title(open_project: OpenProject, tmp_path: Path) -> None:
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
        section = create_section(session, first.trip_id, ids, kind=KIND_STAY, title="Alt")
        session.commit()
        section_id = section.id
        assert section_pin(session, section_id) == (None, None)
        before = capture_section_edit(session, section_id)
        assert before is not None
        set_section_pin(session, section_id, 46.5, 11.3)
        save_section_text(session, section_id, title="Neu", notes="")
        session.commit()
        assert section_pin(session, section_id) == (46.5, 11.3)
        restore_journal_edit(session, before)
        session.commit()
        assert section_pin(session, section_id) == (None, None)
        row = session.get(TripSection, section_id)
        assert row is not None
        assert row.title == "Alt"


def test_restore_deleted_section(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "ort.jpg",
        datetime_original="2025:05:19 10:00:00",
        offset_original="+02:00",
    )
    first = _index_and_sync(open_project, source)
    photo_id = first.days[0].photos[0].source_file_id
    with open_project.session_factory() as session:
        section = create_section(session, first.trip_id, [photo_id], kind=KIND_STAY, title="Markt")
        session.commit()
        section_id = section.id
        before = capture_section_edit(session, section_id)
        assert before is not None
        delete_section(session, section_id)
        session.commit()
        assert session.get(TripSection, section_id) is None
        row = session.get(SourceFile, photo_id)
        assert row is not None
        assert row.parked is True
        restore_journal_edit(session, before)
        session.commit()
        restored = session.get(TripSection, section_id)
        member = session.scalar(select(SectionMember).where(SectionMember.source_file_id == photo_id))
        row = session.get(SourceFile, photo_id)
        assert restored is not None
        assert restored.title == "Markt"
        assert member is not None
        assert member.section_id == section_id
        assert row is not None
        assert row.parked is False


def test_restore_after_create_removes_new_section(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "eins.jpg",
        datetime_original="2025:06:01 09:00:00",
        offset_original="+02:00",
    )
    first = _index_and_sync(open_project, source)
    photo_id = first.days[0].photos[0].source_file_id
    day = next(entry.section for entry in first.entries if entry.section is not None)
    assert day is not None
    with open_project.session_factory() as session:
        before = capture_placement_edit(session, [photo_id])
        created = create_section(session, first.trip_id, [photo_id], kind=KIND_STAY, title="Neu")
        session.commit()
        created_id = created.id
        assert created_id != day.id
        restore_journal_edit(session, before)
        delete_section(session, created_id)
        session.commit()
        assert session.get(TripSection, created_id) is None
        member = session.scalar(select(SectionMember).where(SectionMember.source_file_id == photo_id))
        assert member is not None
        assert member.section_id == day.id


def test_restore_dissolved_section(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "morgen.jpg",
        datetime_original="2025:05:14 09:00:00",
        offset_original="+02:00",
    )
    first = _index_and_sync(open_project, source)
    photo_id = first.days[0].photos[0].source_file_id
    with open_project.session_factory() as session:
        stay = create_section(session, first.trip_id, [photo_id], kind=KIND_STAY, title="Berlin")
        session.commit()
        stay_id = stay.id
        before = capture_section_edit(session, stay_id)
        assert before is not None
        dissolve_section(session, stay_id)
        session.commit()
        assert session.get(TripSection, stay_id) is None
        restore_journal_edit(session, before)
        session.commit()
        restored = session.get(TripSection, stay_id)
        member = session.scalar(select(SectionMember).where(SectionMember.source_file_id == photo_id))
        assert restored is not None
        assert restored.kind == KIND_STAY
        assert restored.title == "Berlin"
        assert member is not None
        assert member.section_id == stay_id


def test_photo_sort_status_roundtrip(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "bild.jpg",
        datetime_original="2025:05:19 10:00:00",
        offset_original="+02:00",
    )
    first = _index_and_sync(open_project, source)
    photo_id = first.days[0].photos[0].source_file_id
    with open_project.session_factory() as session:
        assert photo_sort_status(session, photo_id) is None
        set_photo_sort_status(session, photo_id, "favorite")
        session.commit()
        assert photo_sort_status(session, photo_id) == "favorite"
        set_photo_sort_status(session, photo_id, None)
        session.commit()
        assert photo_sort_status(session, photo_id) is None


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
