from pathlib import Path

from jpeg_fixtures import write_jpeg_with_exif
from sqlalchemy import select

from travelcore.database.models import Project, SectionMember, SourceFile, TripSection
from travelcore.media.indexer import FileIndexer
from travelcore.timeline import KIND_STAY, photo_sort_status, sync_timeline
from traveljournal.services.workspace import Workspace


def test_workspace_undo_rating_and_park(tmp_path: Path) -> None:
    store_dir = tmp_path / "reise"
    media = tmp_path / "media"
    media.mkdir()
    write_jpeg_with_exif(
        media / "bild.jpg",
        datetime_original="2025:05:19 10:00:00",
        offset_original="+02:00",
    )
    workspace = Workspace()
    opened = workspace.create_project(store_dir.parent, "UndoReise")
    with opened.session_factory() as session:
        project = session.get(Project, opened.project_id)
        assert project is not None
        FileIndexer().index(session, project, media, project_dir=opened.directory)
        session.commit()
        sync_timeline(session, project, thumbs_dir=opened.directory / "thumbnails")
        session.commit()
    items = workspace.gallery_items()
    assert items
    photo_id = items[0].source_file_id

    workspace.set_sort_status(photo_id, "favorite")
    with opened.session_factory() as session:
        assert photo_sort_status(session, photo_id) == "favorite"
    assert workspace.history.can_undo()
    workspace.history.undo()
    with opened.session_factory() as session:
        assert photo_sort_status(session, photo_id) is None
    workspace.history.redo()
    with opened.session_factory() as session:
        assert photo_sort_status(session, photo_id) == "favorite"

    workspace.park_media([photo_id])
    parked = {item.source_file_id: item.parked for item in workspace.gallery_items()}
    assert parked[photo_id] is True
    workspace.history.undo()
    parked = {item.source_file_id: item.parked for item in workspace.gallery_items()}
    assert parked[photo_id] is False
    workspace.history.redo()
    parked = {item.source_file_id: item.parked for item in workspace.gallery_items()}
    assert parked[photo_id] is True


def test_workspace_undo_create_and_delete_section(tmp_path: Path) -> None:
    media = tmp_path / "media"
    media.mkdir()
    write_jpeg_with_exif(
        media / "bild.jpg",
        datetime_original="2025:05:19 10:00:00",
        offset_original="+02:00",
    )
    workspace = Workspace()
    opened = workspace.create_project(tmp_path, "UndoAbschnitt")
    with opened.session_factory() as session:
        project = session.get(Project, opened.project_id)
        assert project is not None
        FileIndexer().index(session, project, media, project_dir=opened.directory)
        session.commit()
        sync_timeline(session, project, thumbs_dir=opened.directory / "thumbnails")
        session.commit()
    photo_id = workspace.gallery_items()[0].source_file_id
    snapshot = workspace.load_timeline()
    assert snapshot is not None
    day_id = next(entry.section.id for entry in snapshot.entries if entry.section is not None)

    section_id = workspace.create_section([photo_id], kind=KIND_STAY, title="Besuch")
    with opened.session_factory() as session:
        assert session.get(TripSection, section_id) is not None
    workspace.history.undo()
    with opened.session_factory() as session:
        assert session.get(TripSection, section_id) is None
        member = session.scalar(select(SectionMember).where(SectionMember.source_file_id == photo_id))
        assert member is not None
        assert member.section_id == day_id
        row = session.get(SourceFile, photo_id)
        assert row is not None
        assert row.parked is False
    workspace.history.redo()
    with opened.session_factory() as session:
        rows = list(session.scalars(select(TripSection).where(TripSection.title == "Besuch")))
        assert len(rows) == 1
        section_id = rows[0].id

    workspace.delete_section(section_id)
    with opened.session_factory() as session:
        assert session.get(TripSection, section_id) is None
        row = session.get(SourceFile, photo_id)
        assert row is not None
        assert row.parked is True
    workspace.history.undo()
    with opened.session_factory() as session:
        restored = session.get(TripSection, section_id)
        assert restored is not None
        assert restored.title == "Besuch"
        row = session.get(SourceFile, photo_id)
        assert row is not None
        assert row.parked is False


def _open_indexed(tmp_path: Path, name: str) -> tuple[Workspace, object, int]:
    media = tmp_path / "media"
    media.mkdir()
    write_jpeg_with_exif(
        media / "bild.jpg",
        datetime_original="2025:05:19 10:00:00",
        offset_original="+02:00",
    )
    workspace = Workspace()
    opened = workspace.create_project(tmp_path, name)
    with opened.session_factory() as session:
        project = session.get(Project, opened.project_id)
        assert project is not None
        FileIndexer().index(session, project, media, project_dir=opened.directory)
        session.commit()
        sync_timeline(session, project, thumbs_dir=opened.directory / "thumbnails")
        session.commit()
    photo_id = workspace.gallery_items()[0].source_file_id
    return workspace, opened, photo_id


def test_workspace_undo_dissolve_journal_notes_cover_rotation(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    workspace, opened, photo_id = _open_indexed(tmp_path, "UndoMehr")
    snapshot = workspace.load_timeline()
    assert snapshot is not None
    stay_id = workspace.create_section([photo_id], kind=KIND_STAY, title="Markt")
    workspace.history.clear()

    workspace.dissolve_section(stay_id)
    with opened.session_factory() as session:
        assert session.get(TripSection, stay_id) is None
    workspace.history.undo()
    with opened.session_factory() as session:
        restored = session.get(TripSection, stay_id)
        assert restored is not None
        assert restored.title == "Markt"

    workspace.set_journal_at([photo_id], datetime(2025, 5, 21, 12, 0, tzinfo=UTC))
    workspace.history.undo()
    workspace.reset_journal([photo_id])
    assert workspace.history.can_undo()
    workspace.history.undo()

    workspace.save_section_text(stay_id, title="Markt", notes="Abendessen")
    workspace.history.undo()
    with opened.session_factory() as session:
        row = session.get(TripSection, stay_id)
        assert row is not None
        assert (row.notes or "") != "Abendessen"

    workspace.save_trip_title(snapshot.trip_id, "Italien")
    workspace.history.undo()

    workspace.set_entry_cover("section", stay_id, photo_id)
    workspace.history.undo()
    with opened.session_factory() as session:
        row = session.get(TripSection, stay_id)
        assert row is not None
        assert row.cover_source_file_id is None

    workspace.add_rotation(photo_id, 90)
    item = next(entry for entry in workspace.gallery_items() if entry.source_file_id == photo_id)
    assert item.rotation_degrees == 90
    workspace.history.undo()
    item = next(entry for entry in workspace.gallery_items() if entry.source_file_id == photo_id)
    assert item.rotation_degrees == 0
