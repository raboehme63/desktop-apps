from pathlib import Path

from igc_fixtures import bozen_points, write_igc
from sqlalchemy import select

from travelcore.database.models import GpsPoint, Project, SourceFile
from travelcore.database.project_store import OpenProject
from travelcore.gps.igctracks import IGC_TRACKS_DIRNAME, index_igc_file, is_igc_track_path
from travelcore.gps.track_badge import TRACK_BADGE_IGC
from travelcore.media.gallery import list_gallery_items
from travelcore.media.indexer import FileIndexer, count_by_kind
from travelcore.media.purge import plan_source_sync
from travelcore.media.scanner import scan_source_directory


def test_is_igc_track_path() -> None:
    assert is_igc_track_path(Path("D:/fotos/.IGCTracks/flug.igc"))
    assert is_igc_track_path(Path("D:/fotos/.igctracks/flug.igc"))
    assert not is_igc_track_path(Path("D:/fotos/.FitnessTracks/ride.gpx"))
    assert not is_igc_track_path(Path("D:/fotos/tag1/flug.igc"))


def test_igc_track_is_indexed_scanned_and_in_gallery(open_project: OpenProject, tmp_path: Path) -> None:
    media = tmp_path / "import"
    dest_dir = media / IGC_TRACKS_DIRNAME
    dest_dir.mkdir(parents=True)
    dest = write_igc(dest_dir / "flug.igc", bozen_points())

    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        row = index_igc_file(
            session,
            project,
            dest,
            project_dir=open_project.directory,
        )
        session.commit()
        assert row is not None
        source_id = row.id
        assert row.parked is False
        assert is_igc_track_path(row.path)
        assert Path(row.path).parent == media / IGC_TRACKS_DIRNAME
        assert len(list(session.scalars(select(GpsPoint)))) >= 2
        thumbs = open_project.directory / "thumbnails"
        thumbs.mkdir(exist_ok=True)
        gallery = list_gallery_items(session, open_project.project_id, thumbs)
        found = next(item for item in gallery if item.source_file_id == source_id)
        assert found.track_badge == TRACK_BADGE_IGC
        counts = count_by_kind(session, open_project.project_id)
        assert counts["flights"] == 1
        assert counts["act"] == 0
        assert counts["map"] == 0
        assert counts["other"] == 0
        assert counts["gps"] == 1
        assert "flug.igc" in {item.filename for item in scan_source_directory(media)}
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
