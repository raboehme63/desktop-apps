from datetime import UTC, datetime
from pathlib import Path

import pytest
from gpx_fixtures import write_gpx
from sqlalchemy import select

from travelcore.database.models import GpsPoint, Project, SourceFile
from travelcore.database.project_store import OpenProject
from travelcore.exceptions import ProjectError
from travelcore.gps.maptracks import (
    MAP_TRACKS_DIRNAME,
    import_map_track_file,
    import_map_track_gpx,
    is_map_track_path,
    list_map_tracks,
    map_track_display_name,
    map_track_name_suggestion,
)
from travelcore.media.gallery import list_gallery_items
from travelcore.media.indexer import FileIndexer, count_by_kind
from travelcore.media.purge import plan_source_sync
from travelcore.timeline.outbound import save_outbound_link
from travelcore.timeline.types import TimelineLink

_GPX_TWO_POINTS = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">'
    "<trk><trkseg>"
    '<trkpt lat="46.5" lon="11.3"></trkpt>'
    '<trkpt lat="46.6" lon="11.4"></trkpt>'
    "</trkseg></trk></gpx>"
)


def _media_root(tmp_path: Path) -> Path:
    root = tmp_path / "import"
    root.mkdir(exist_ok=True)
    return root


def test_import_map_track_copies_into_import_folder(open_project: OpenProject, tmp_path: Path) -> None:
    media = _media_root(tmp_path)
    original = write_gpx(
        tmp_path / "route.gpx",
        [(47.0, 11.0, None, None), (47.1, 11.1, None, None)],
        name="Alpen",
    )
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        row = import_map_track_file(
            session,
            project,
            original,
            source_root=media,
            project_dir=open_project.directory,
        )
        session.commit()
        source_id = row.id
        stored = Path(row.path)
        assert row.parked is True
    assert original.is_file()
    assert stored.is_file()
    assert stored.parent == media / MAP_TRACKS_DIRNAME
    assert stored.name == "Map-Track.gpx"
    assert is_map_track_path(stored)
    assert not (open_project.directory / "MapTracks").exists()
    with open_project.session_factory() as session:
        assert list_map_tracks(session, open_project.project_id) == [(source_id, "Map-Track")]
        points = list(session.scalars(select(GpsPoint)))
        assert len(points) >= 2
        thumbs = open_project.directory / "thumbnails"
        thumbs.mkdir(exist_ok=True)
        gallery = list_gallery_items(session, open_project.project_id, thumbs)
        assert all(item.source_file_id != source_id for item in gallery)
        counts = count_by_kind(session, open_project.project_id)
        assert counts["map"] == 1
        assert counts["act"] == 0
        assert counts["flights"] == 0
        assert counts["other"] == 0
        assert counts["gps"] == 1
        plan = plan_source_sync(session, open_project.project_id, media)
        assert plan.missing_count == 0
        assert plan.new_count == 0
        project = session.get(Project, open_project.project_id)
        assert project is not None
        FileIndexer().index(
            session,
            project,
            media,
            project_dir=open_project.directory,
            generate_thumbnails=False,
            remove_missing=True,
        )
        session.commit()
        assert session.get(SourceFile, source_id) is not None
        assert list_map_tracks(session, open_project.project_id) == [(source_id, "Map-Track")]


def test_import_map_track_requires_source_root(open_project: OpenProject, tmp_path: Path) -> None:
    original = write_gpx(
        tmp_path / "route.gpx",
        [(47.0, 11.0, None, None), (47.1, 11.1, None, None)],
        name="Alpen",
    )
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        with pytest.raises(ProjectError, match="Import-Ordner"):
            import_map_track_file(
                session,
                project,
                original,
                source_root=None,
                project_dir=open_project.directory,
            )
        with pytest.raises(ProjectError, match="Import-Ordner"):
            import_map_track_gpx(
                session,
                project,
                _GPX_TWO_POINTS,
                source_root=None,
                project_dir=open_project.directory,
            )


def test_is_map_track_path_accepts_legacy_and_dot_folder() -> None:
    assert is_map_track_path(Path("D:/fotos/.MapTracks/Map-Track.gpx"))
    assert is_map_track_path(Path("D:/projekt/MapTracks/Map-Track.gpx"))
    assert not is_map_track_path(Path("D:/fotos/tag1/track.gpx"))


def test_import_map_track_gpx_and_outbound_link(open_project: OpenProject, tmp_path: Path) -> None:
    from travelcore.timeline.sections import KIND_STAY, create_section

    media = _media_root(tmp_path)
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        row = import_map_track_gpx(
            session,
            project,
            _GPX_TWO_POINTS,
            source_root=media,
            project_dir=open_project.directory,
        )
        section = create_section(
            session,
            _trip_id(session, project.id),
            [],
            kind=KIND_STAY,
            title="Bozen",
            started_at=datetime(2026, 9, 2, 10, 0, tzinfo=UTC),
        )
        session.flush()
        saved = save_outbound_link(
            session,
            section.id,
            TimelineLink(
                id=0,
                sort_index=0,
                geometry="map_track",
                dash="dashed",
                symbol="car",
                track_source_file_id=row.id,
            ),
        )
        session.commit()
        assert saved is not None
        assert saved.geometry == "map_track"
        assert saved.track_source_file_id == row.id
        reloaded = session.get(type(section), section.id)
        assert reloaded is not None
        assert reloaded.outbound_geometry == "map_track"
        assert reloaded.outbound_track_source_file_id == row.id
        assert (media / MAP_TRACKS_DIRNAME / "Map-Track.gpx").is_file()
        assert not (open_project.directory / "MapTracks").exists()


def test_map_track_appears_on_timeline_and_overview(open_project: OpenProject, tmp_path: Path) -> None:
    from travelcore.maps.groups import build_map_group_detail, build_map_overview
    from travelcore.timeline import KIND_STAY, create_section, load_timeline

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">'
        "<trk><trkseg>"
        '<trkpt lat="46.2" lon="11.1"></trkpt>'
        '<trkpt lat="46.4" lon="11.2"></trkpt>'
        '<trkpt lat="46.6" lon="11.3"></trkpt>'
        "</trkseg></trk></gpx>"
    )
    media = _media_root(tmp_path)
    thumbs = open_project.directory / "thumbnails"
    thumbs.mkdir(exist_ok=True)
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        row = import_map_track_gpx(
            session,
            project,
            xml,
            source_root=media,
            project_dir=open_project.directory,
        )
        left = create_section(
            session,
            _trip_id(session, project.id),
            [],
            kind=KIND_STAY,
            title="Start",
            started_at=datetime(2026, 9, 2, 10, 0, tzinfo=UTC),
        )
        right = create_section(
            session,
            _trip_id(session, project.id),
            [],
            kind=KIND_STAY,
            title="Ziel",
            started_at=datetime(2026, 9, 3, 10, 0, tzinfo=UTC),
        )
        session.flush()
        left.pin_latitude = 46.0
        left.pin_longitude = 11.0
        right.pin_latitude = 47.0
        right.pin_longitude = 12.0
        save_outbound_link(
            session,
            left.id,
            TimelineLink(
                id=0,
                sort_index=0,
                geometry="map_track",
                dash="solid",
                track_source_file_id=row.id,
            ),
        )
        session.commit()
        left_id = left.id
        source_id = row.id
        snapshot = load_timeline(session, project, thumbs_dir=thumbs)
        scene = build_map_overview(session, open_project.project_id, thumbs)
        detail = (
            build_map_group_detail(session, open_project.project_id, f"section:{left_id}", thumbs)
        )
    assert snapshot is not None
    section = next(item for item in snapshot.sections if item.id == left_id)
    names = [item.filename for item in section.items]
    assert "Map-Track" in names
    assert any(item.source_file_id == source_id for item in section.items)
    tracks = [line for line in scene.polylines if line.source_file_id == source_id]
    assert tracks
    assert tracks[0].map_track is True
    assert tracks[0].color == "#5b8def"
    assert tracks[0].points[0] == (46.2, 11.1)
    users = [item for item in scene.stay_links[0].segments if item.role == "user"]
    assert users
    assert users[0].style == "track"
    assert users[0].map_track is True
    assert users[0].points[0] == (46.2, 11.1)
    assert any(line.source_file_id == source_id for line in detail.polylines)


def test_transfer_map_track_persists(open_project: OpenProject, tmp_path: Path) -> None:
    from travelcore.timeline import KIND_MOVEMENT, create_section
    from travelcore.timeline.transfer_links import (
        LINK_GEOMETRY_MAP_TRACK,
        load_transfer_links,
        save_transfer_links,
    )

    media = _media_root(tmp_path)
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        row = import_map_track_gpx(
            session,
            project,
            _GPX_TWO_POINTS,
            source_root=media,
            project_dir=open_project.directory,
        )
        section = create_section(
            session,
            _trip_id(session, project.id),
            [],
            kind=KIND_MOVEMENT,
            title="Fahrt",
            started_at=datetime(2026, 9, 2, 10, 0, tzinfo=UTC),
        )
        session.flush()
        save_transfer_links(
            session,
            section.id,
            [
                TimelineLink(
                    id=0,
                    sort_index=0,
                    geometry=LINK_GEOMETRY_MAP_TRACK,
                    track_source_file_id=row.id,
                )
            ],
        )
        session.commit()
        loaded = load_transfer_links(session, section.id)
    assert loaded[0].geometry == LINK_GEOMETRY_MAP_TRACK
    assert loaded[0].track_source_file_id == row.id


def test_import_map_track_gpx_uses_route_stem(open_project: OpenProject, tmp_path: Path) -> None:
    media = _media_root(tmp_path)
    stem = "Bad-Tölz-to-CAMPING-RUDI"
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        first = import_map_track_gpx(
            session,
            project,
            _GPX_TWO_POINTS,
            source_root=media,
            project_dir=open_project.directory,
            stem=stem,
        )
        session.commit()
        first_id = first.id
        stored = Path(first.path)
        assert stored.name == f"{stem}.gpx"
        assert list_map_tracks(session, open_project.project_id) == [(first_id, stem)]
        second = import_map_track_gpx(
            session,
            project,
            _GPX_TWO_POINTS,
            source_root=media,
            project_dir=open_project.directory,
            stem=stem,
        )
        session.commit()
        assert Path(second.path).name == f"{stem}-2.gpx"
        names = {name for _id, name in list_map_tracks(session, open_project.project_id)}
        assert names == {stem, f"{stem}-2"}


def test_map_track_display_name_keeps_route_stem() -> None:
    assert map_track_display_name("Map-Track.gpx") == "Map-Track"
    assert map_track_display_name("Map-Track-2.gpx") == "Map-Track 2"
    assert map_track_display_name("Bad-Tölz-to-CAMPING-RUDI.gpx") == "Bad-Tölz-to-CAMPING-RUDI"
    assert map_track_display_name("Bad-Tölz-to-CAMPING-RUDI-2.gpx") == "Bad-Tölz-to-CAMPING-RUDI-2"


def test_map_track_name_suggestion_is_editable() -> None:
    assert (
        map_track_name_suggestion("Häselgehr-to-Parkplatz-Wasserauen")
        == "Häselgehr to Parkplatz Wasserauen"
    )
    assert (
        map_track_name_suggestion("Stop-1-to-Parkplatz-Wasserauen.gpx")
        == "Stop 1 to Parkplatz Wasserauen"
    )
    assert map_track_name_suggestion("") == "Map-Track"


def test_empty_gpx_is_rejected(open_project: OpenProject, tmp_path: Path) -> None:
    media = _media_root(tmp_path)
    empty = tmp_path / "leer.gpx"
    empty.write_text(
        '<?xml version="1.0"?><gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1"></gpx>',
        encoding="utf-8",
    )
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        with pytest.raises(ProjectError, match="keine Trackpunkte"):
            import_map_track_file(
                session,
                project,
                empty,
                source_root=media,
                project_dir=open_project.directory,
            )
        assert list(session.scalars(select(SourceFile))) == []
        hidden = media / MAP_TRACKS_DIRNAME
        assert not hidden.exists() or list(hidden.glob("*.gpx")) == []


def _trip_id(session, project_id: int) -> int:
    from travelcore.database.models import Trip

    trip = session.scalar(select(Trip).where(Trip.project_id == project_id))
    if trip is None:
        trip = Trip(project_id=project_id, title="Testreise", origin="auto")
        session.add(trip)
        session.flush()
    return trip.id
