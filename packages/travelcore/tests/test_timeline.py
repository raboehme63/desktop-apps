from datetime import UTC, datetime
from pathlib import Path

from jpeg_fixtures import write_jpeg_with_exif

from travelcore.database.models import Project
from travelcore.database.project_store import OpenProject
from travelcore.geolocation.stays import cluster_stays, haversine_m
from travelcore.media.indexer import FileIndexer
from travelcore.timeline import (
    add_overnight_stay,
    add_place_suggestions,
    confirm_place,
    load_timeline,
    save_day_text,
    set_cover_photo,
    set_photo_journal_flag,
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


def test_overnight_and_journal_flags(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "cover.jpg",
        datetime_original="2025:05:15 20:00:00",
        offset_original="+02:00",
    )
    snapshot = _index_and_sync(open_project, source)
    day_id = snapshot.days[0].id
    photo_id = snapshot.days[0].photos[0].source_file_id
    with open_project.session_factory() as session:
        add_overnight_stay(
            session,
            day_id,
            name="Hotel",
            location_name="Bozen",
            latitude=46.5,
            longitude=11.35,
            description="Erste Nacht",
        )
        set_photo_journal_flag(session, photo_id, True)
        set_cover_photo(session, open_project.project_id, photo_id)
        project = session.get(Project, open_project.project_id)
        assert project is not None
        loaded = load_timeline(session, project)
        session.commit()

    assert loaded is not None
    stay = loaded.days[0].stays[0]
    assert stay.name == "Hotel"
    assert stay.location_name == "Bozen"
    assert stay.origin == "manual"
    photo = loaded.days[0].photos[0]
    assert photo.used_in_journal is True
    assert photo.is_cover is True


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
