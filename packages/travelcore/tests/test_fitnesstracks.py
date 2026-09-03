from pathlib import Path

import pytest
from gpx_fixtures import write_gpx
from sqlalchemy import select

from travelcore.database.models import GpsPoint, Project, SourceFile
from travelcore.database.project_store import OpenProject
from travelcore.exceptions import ProjectError
from travelcore.gps.fitnesstracks import (
    ACTIVITY_TRACKS_DIRNAME,
    index_fitness_gpx_file,
    is_activity_track_path,
)
from travelcore.gps.track_badge import TRACK_BADGE_ACT
from travelcore.media.gallery import list_gallery_items
from travelcore.media.indexer import FileIndexer, count_by_kind
from travelcore.media.purge import plan_source_sync
from travelcore.media.scanner import scan_source_directory


def _media_root(tmp_path: Path) -> Path:
    root = tmp_path / "import"
    root.mkdir(exist_ok=True)
    return root


def test_is_activity_track_path() -> None:
    assert is_activity_track_path(Path("D:/fotos/.ActivityTracks/ride.gpx"))
    assert is_activity_track_path(Path("D:/fotos/.FitnessTracks/ride.gpx"))
    assert is_activity_track_path(Path("D:/fotos/.fitnesstracks/ride.gpx"))
    assert not is_activity_track_path(Path("D:/fotos/.MapTracks/Map-Track.gpx"))
    assert not is_activity_track_path(Path("D:/fotos/tag1/track.gpx"))


def test_fitness_track_is_indexed_scanned_and_in_gallery(
    open_project: OpenProject, tmp_path: Path
) -> None:
    media = _media_root(tmp_path)
    dest_dir = media / ACTIVITY_TRACKS_DIRNAME
    dest_dir.mkdir(parents=True)
    dest = write_gpx(
        dest_dir / "ride.gpx",
        [(47.0, 11.0, None, None), (47.1, 11.1, None, None)],
        name="Kitesurfen",
    )

    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        row = index_fitness_gpx_file(
            session,
            project,
            dest,
            project_dir=open_project.directory,
        )
        session.commit()
        assert row is not None
        source_id = row.id
        assert row.parked is False
        assert is_activity_track_path(row.path)
        assert Path(row.path).parent == media / ACTIVITY_TRACKS_DIRNAME
        points = list(session.scalars(select(GpsPoint)))
        assert len(points) >= 2
        thumbs = open_project.directory / "thumbnails"
        thumbs.mkdir(exist_ok=True)
        gallery = list_gallery_items(session, open_project.project_id, thumbs)
        found = next(item for item in gallery if item.source_file_id == source_id)
        assert found.track_badge == TRACK_BADGE_ACT
        counts = count_by_kind(session, open_project.project_id)
        assert counts["act"] == 1
        assert counts["map"] == 0
        assert counts["flights"] == 0
        assert counts["other"] == 0
        assert counts["gps"] == 1
        scanned = {item.filename for item in scan_source_directory(media)}
        assert "ride.gpx" in scanned
        plan = plan_source_sync(session, open_project.project_id, media)
        assert plan.missing_count == 0
        assert plan.new_count == 0
        FileIndexer().index(
            session,
            project,
            media,
            project_dir=open_project.directory,
            generate_thumbnails=False,
            remove_missing=True,
        )
        session.commit()
        kept = session.get(SourceFile, source_id)
        assert kept is not None
        assert kept.parked is False
        again = index_fitness_gpx_file(
            session,
            project,
            dest,
            project_dir=open_project.directory,
        )
        session.commit()
        assert again is not None
        assert again.id == source_id


def test_empty_fitness_gpx_is_rejected(open_project: OpenProject, tmp_path: Path) -> None:
    media = _media_root(tmp_path)
    dest_dir = media / ACTIVITY_TRACKS_DIRNAME
    dest_dir.mkdir(parents=True)
    dest = dest_dir / "empty.gpx"
    dest.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1"></gpx>',
        encoding="utf-8",
    )
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        with pytest.raises(ProjectError, match="keine Trackpunkte"):
            index_fitness_gpx_file(
                session,
                project,
                dest,
                project_dir=open_project.directory,
            )
        session.rollback()
        assert session.scalar(select(SourceFile)) is None


def test_unlink_unwanted_files_clears_dest_orphans_and_legacy(tmp_path: Path) -> None:
    from travelcore.gps.fitnesstracks import (
        LEGACY_ACTIVITY_TRACKS_DIRNAME,
        unlink_unwanted_files,
    )

    dest = tmp_path / ACTIVITY_TRACKS_DIRNAME
    dest.mkdir()
    keep = dest / "keep.gpx"
    keep.write_text("keep", encoding="utf-8")
    orphan = dest / "orphan.gpx"
    orphan.write_text("gone", encoding="utf-8")
    legacy = tmp_path / LEGACY_ACTIVITY_TRACKS_DIRNAME
    legacy.mkdir()
    (legacy / "keep.gpx").write_text("dup", encoding="utf-8")
    (legacy / "old.gpx").write_text("old", encoding="utf-8")
    removed = unlink_unwanted_files(
        [dest, legacy], dest=dest, wanted_names={"keep.gpx"}, suffix=".gpx"
    )
    assert keep.exists()
    assert not orphan.exists()
    assert not (legacy / "keep.gpx").exists()
    assert not (legacy / "old.gpx").exists()
    assert removed == 3
