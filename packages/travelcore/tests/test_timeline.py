from datetime import UTC, datetime
from pathlib import Path

from jpeg_fixtures import write_jpeg_with_exif
from sqlalchemy import select

from travelcore.database.models import Photo, Project
from travelcore.database.project_store import OpenProject
from travelcore.geolocation.stays import cluster_stays, haversine_m
from travelcore.media.indexer import FileIndexer
from travelcore.timeline import (
    add_place_suggestions,
    add_source_rotation,
    confirm_place,
    load_timeline,
    save_day_leonardo_urls,
    save_day_text,
    save_day_youtube_urls,
    save_trip_title,
    set_cover_photo,
    set_photo_journal_flag,
    set_photo_sort_status,
    sync_timeline,
)
from travelcore.timeline.types import TimelineSnapshot


def test_cluster_stays_joins_nearby_points() -> None:
    started = datetime(2025, 5, 15, 10, 0, tzinfo=UTC)
    ended = datetime(2025, 5, 15, 10, 5, tzinfo=UTC)
    clusters = cluster_stays(
        [(46.0, 11.0, started), (46.0005, 11.0004, ended)],
        radius_meters=150.0,
    )
    assert len(clusters) == 1
    assert clusters[0].point_count == 2
    assert clusters[0].duration_minutes == 5.0


def test_cluster_stays_splits_distant_points() -> None:
    clusters = cluster_stays(
        [(46.0, 11.0, None), (46.02, 11.0, None)],
        radius_meters=150.0,
    )
    assert len(clusters) == 2
    assert haversine_m(46.0, 11.0, 46.02, 11.0) > 150.0


def test_sync_timeline_creates_one_day_per_date(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "tag1.jpg",
        datetime_original="2025:05:15 08:20:00",
        offset_original="+02:00",
    )
    write_jpeg_with_exif(
        source / "tag2.jpg",
        datetime_original="2025:05:16 18:00:00",
        offset_original="+02:00",
    )
    snapshot = _index_and_sync(open_project, source)
    assert snapshot.day_count == 2
    assert [day.date.isoformat() for day in snapshot.days if day.date is not None] == [
        "2025-05-15",
        "2025-05-16",
    ]
    assert snapshot.days[0].photos[0].filename == "tag1.jpg"
    assert snapshot.days[0].origin == "auto"
    assert snapshot.days[0].events[0].title == "1 Medien"


def test_manual_day_text_survives_resync(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "ankunft.jpg",
        datetime_original="2025:05:15 08:20:00",
        offset_original="+02:00",
    )
    first = _index_and_sync(open_project, source)
    day_id = first.days[0].id
    with open_project.session_factory() as session:
        save_day_text(session, day_id, title="Bozen", notes="Ankunft am Abend.")
        session.commit()

    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        snapshot = sync_timeline(session, project)
        session.commit()

    assert snapshot.days[0].title == "Bozen"
    assert snapshot.days[0].notes == "Ankunft am Abend."
    assert snapshot.days[0].origin == "manual"


def test_manual_trip_title_survives_resync(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "ankunft.jpg",
        datetime_original="2025:05:15 08:20:00",
        offset_original="+02:00",
    )
    first = _index_and_sync(open_project, source)
    assert first.title == "Testreise"
    assert first.origin == "auto"
    with open_project.session_factory() as session:
        save_trip_title(session, first.trip_id, "Dolomiten 2025")
        session.commit()

    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        snapshot = sync_timeline(session, project)
        session.commit()

    assert snapshot.title == "Dolomiten 2025"
    assert snapshot.origin == "manual"


def test_youtube_urls_roundtrip_on_day(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "ankunft.jpg",
        datetime_original="2025:05:15 08:20:00",
        offset_original="+02:00",
    )
    first = _index_and_sync(open_project, source)
    with open_project.session_factory() as session:
        save_day_youtube_urls(
            session,
            first.days[0].id,
            ["https://youtu.be/abc123", "https://www.youtube.com/watch?v=xyz"],
        )
        session.commit()
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        loaded = load_timeline(session, project)
    assert loaded is not None
    assert loaded.days[0].youtube_urls == (
        "https://youtu.be/abc123",
        "https://www.youtube.com/watch?v=xyz",
    )


def test_leonardo_urls_roundtrip_on_day(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "ankunft.jpg",
        datetime_original="2025:05:15 08:20:00",
        offset_original="+02:00",
    )
    first = _index_and_sync(open_project, source)
    with open_project.session_factory() as session:
        save_day_leonardo_urls(
            session,
            first.days[0].id,
            ["https://de.dhv.de/dbnx/nx.php?id=42", "https://de.dhv.de/dbnx/nx.php?id=99"],
        )
        session.commit()
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        loaded = load_timeline(session, project)
    assert loaded is not None
    assert loaded.days[0].leonardo_urls == (
        "https://de.dhv.de/dbnx/nx.php?id=42",
        "https://de.dhv.de/dbnx/nx.php?id=99",
    )


def test_place_suggestion_not_auto_assigned_to_gps_media(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "platz.jpg",
        datetime_original="2025:05:15 15:32:00",
        offset_original="+02:00",
        latitude=(46.0, 0.0, 0.0),
        longitude=(11.0, 0.0, 0.0),
    )
    snapshot = _index_and_sync(open_project, source)
    assert snapshot.days[0].places == ()

    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        added = add_place_suggestions(session, project)
        session.commit()
        again = load_timeline(session, project)

    assert added == 1
    assert again is not None
    assert len(again.days[0].places) == 1
    place_id = again.days[0].places[0].id
    with open_project.session_factory() as session:
        confirm_place(session, place_id, "Waltherplatz")
        project = session.get(Project, open_project.project_id)
        assert project is not None
        synced = sync_timeline(session, project)
        session.commit()

    assert len(synced.days[0].places) == 1
    assert synced.days[0].places[0].name == "Waltherplatz"
    assert synced.days[0].places[0].confirmed is True
    assert synced.days[0].places[0].origin == "manual"


def test_journal_flags_and_cover(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "cover.jpg",
        datetime_original="2025:05:15 20:00:00",
        offset_original="+02:00",
    )
    snapshot = _index_and_sync(open_project, source)
    photo_id = snapshot.days[0].photos[0].source_file_id
    with open_project.session_factory() as session:
        set_photo_journal_flag(session, photo_id, True)
        set_cover_photo(session, open_project.project_id, photo_id)
        project = session.get(Project, open_project.project_id)
        assert project is not None
        loaded = load_timeline(session, project)
        session.commit()

    assert loaded is not None
    photo = loaded.days[0].photos[0]
    assert photo.used_in_journal is True
    assert photo.is_cover is True


def test_sync_prefills_title_and_notes_from_imported_text(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "ankunft.jpg",
        datetime_original="2025:05:15 08:20:00",
        offset_original="+02:00",
    )
    (source / "2025-05-15.md").write_text("# Bozen\n\nAnkunft am Abend.\n", encoding="utf-8")
    snapshot = _index_and_sync(open_project, source)
    assert snapshot.day_count == 1
    assert snapshot.days[0].title == "Bozen"
    assert snapshot.days[0].notes == "Ankunft am Abend."
    assert snapshot.days[0].origin == "auto"
    assert snapshot.days[0].photos[0].filename == "ankunft.jpg"


def test_imported_text_does_not_overwrite_manual_day(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "ankunft.jpg",
        datetime_original="2025:05:15 08:20:00",
        offset_original="+02:00",
    )
    (source / "2025-05-15.md").write_text("# Bozen\n\nAus der Datei.\n", encoding="utf-8")
    first = _index_and_sync(open_project, source)
    day_id = first.days[0].id
    with open_project.session_factory() as session:
        save_day_text(session, day_id, title="Manuell", notes="Bleibt stehen.")
        session.commit()
    (source / "2025-05-15.md").write_text("# Neu\n\nSollte nicht gewinnen.\n", encoding="utf-8")
    again = _index_and_sync(open_project, source)
    assert again.days[0].title == "Manuell"
    assert again.days[0].notes == "Bleibt stehen."
    assert again.days[0].origin == "manual"


def test_text_only_note_creates_a_day(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    (source / "2025-06-01.md").write_text("# Pause\n\nKein Foto an diesem Tag.\n", encoding="utf-8")
    snapshot = _index_and_sync(open_project, source)
    assert snapshot.day_count == 1
    assert snapshot.days[0].date is not None
    assert snapshot.days[0].date.isoformat() == "2025-06-01"
    assert snapshot.days[0].title == "Pause"
    assert snapshot.days[0].notes == "Kein Foto an diesem Tag."
    assert snapshot.days[0].photos == ()


def test_photo_sort_status_keeps_favorite_in_sync(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "bewertet.jpg",
        datetime_original="2025:05:15 08:20:00",
        offset_original="+02:00",
    )
    snapshot = _index_and_sync(open_project, source)
    photo_id = snapshot.days[0].photos[0].source_file_id
    with open_project.session_factory() as session:
        set_photo_sort_status(session, photo_id, "favorite")
        session.commit()
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        loaded = load_timeline(session, project)
        session.commit()
    assert loaded is not None
    photo = loaded.days[0].photos[0]
    assert photo.sort_status == "favorite"
    assert photo.is_favorite is True

    with open_project.session_factory() as session:
        set_photo_sort_status(session, photo_id, "reserve")
        session.commit()
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        loaded = load_timeline(session, project)
        session.commit()
    assert loaded is not None
    photo = loaded.days[0].photos[0]
    assert photo.sort_status == "reserve"
    assert photo.is_favorite is False

    with open_project.session_factory() as session:
        row = session.scalar(select(Photo).where(Photo.source_file_id == photo_id))
        assert row is not None
        row.sort_status = None
        row.is_favorite = True
        session.commit()
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        loaded = load_timeline(session, project)
        session.commit()
    assert loaded is not None
    photo = loaded.days[0].photos[0]
    assert photo.sort_status == "favorite"
    assert photo.is_favorite is True


def test_source_rotation_is_stored_and_used_for_thumbs(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "gedreht.jpg",
        datetime_original="2025:05:15 08:20:00",
        offset_original="+02:00",
        size=(40, 20),
    )
    snapshot = _index_and_sync(open_project, source)
    photo_id = snapshot.days[0].photos[0].source_file_id
    assert snapshot.days[0].photos[0].rotation_degrees == 0
    assert "_r90" not in snapshot.days[0].photos[0].thumbnail_path.name
    with open_project.session_factory() as session:
        assert add_source_rotation(session, photo_id, 90) == 90
        session.commit()
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        loaded = load_timeline(session, project)
        session.commit()
    assert loaded is not None
    photo = loaded.days[0].photos[0]
    assert photo.rotation_degrees == 90
    assert photo.thumbnail_path.name.endswith("_r90.jpg")
    with open_project.session_factory() as session:
        assert add_source_rotation(session, photo_id, 90) == 180
        session.commit()
    with open_project.session_factory() as session:
        from travelcore.database.models import SourceFile

        row = session.get(SourceFile, photo_id)
        assert row is not None
        assert row.rotation_degrees == 180


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
