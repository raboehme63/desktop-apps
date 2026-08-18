from datetime import UTC, datetime
from pathlib import Path

from gpx_fixtures import write_gpx
from igc_fixtures import bozen_points, write_igc
from jpeg_fixtures import write_jpeg_with_exif
from sqlalchemy import select

from travelcore.database.models import OvernightStay, Place, Project, SourceFile, Trip, TripDay
from travelcore.database.project_store import OpenProject
from travelcore.gps.ingest import set_track_external_url
from travelcore.maps import (
    FLIGHT_LINE_MIN_ZOOM,
    FoliumMapBackend,
    MapBackend,
    MapPolyline,
    MapScene,
    build_map_scene,
    downsample_points,
)
from travelcore.media.indexer import FileIndexer


def test_downsample_keeps_endpoints() -> None:
    points = [(float(index), 0.0) for index in range(100)]
    sampled = downsample_points(points, max_points=10)
    assert sampled[0] == points[0]
    assert sampled[-1] == points[-1]
    assert len(sampled) <= 11


def test_map_scene_has_track_and_photo(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "platz.jpg",
        datetime_original="2025:05:15 15:32:00",
        offset_original="+02:00",
        latitude=(46.0, 0.0, 0.0),
        longitude=(11.0, 0.0, 0.0),
    )
    write_gpx(
        source / "spur.gpx",
        [
            (46.0, 11.0, 260.0, "2025-05-15T13:31:50Z"),
            (46.2, 11.2, 280.0, "2025-05-15T13:32:10Z"),
        ],
    )
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        FileIndexer().index(session, project, source, project_dir=open_project.directory)
        session.commit()

    thumbs = open_project.directory / "thumbnails"
    with open_project.session_factory() as session:
        scene = build_map_scene(session, open_project.project_id, thumbs)

    assert not scene.empty
    assert len(scene.polylines) == 1
    assert scene.polylines[0].points[0] == (46.0, 11.0)
    photos = [item for item in scene.markers if item.kind == "photo"]
    assert len(photos) == 1
    assert photos[0].label == "2025-05-15"
    assert photos[0].subtitle == "platz.jpg"
    assert photos[0].day_key == "2025-05-15"


def test_map_scene_includes_overnight_and_place(open_project: OpenProject) -> None:
    now = datetime(2025, 5, 15, tzinfo=UTC)
    with open_project.session_factory() as session:
        trip = Trip(project_id=open_project.project_id, title="Test", origin="auto")
        session.add(trip)
        session.flush()
        day = TripDay(trip_id=trip.id, day_index=0, date=now, origin="auto")
        session.add(day)
        session.flush()
        session.add(
            OvernightStay(
                day_id=day.id,
                name="Hotel",
                location_name="Bozen",
                stayed_on=now,
                latitude=46.5,
                longitude=11.35,
                origin="manual",
            )
        )
        session.add(
            Place(
                day_id=day.id,
                name="Markt",
                latitude=46.51,
                longitude=11.36,
                confirmed=True,
                origin="manual",
            )
        )
        session.commit()

    thumbs = open_project.directory / "thumbnails"
    with open_project.session_factory() as session:
        scene = build_map_scene(session, open_project.project_id, thumbs)

    kinds = {item.kind for item in scene.markers}
    assert "overnight" in kinds
    assert "place" in kinds
    stay = next(item for item in scene.markers if item.kind == "overnight")
    assert stay.label == "Bozen"


def test_folium_backend_writes_html(tmp_path: Path) -> None:
    scene = MapScene(
        markers=(),
        polylines=(MapPolyline(name="Spur", points=((46.0, 11.0), (46.1, 11.1))),),
        center=(46.05, 11.05),
    )
    written = FoliumMapBackend().render(scene, tmp_path / "map.html")
    text = written.read_text(encoding="utf-8")
    assert written.is_file()
    assert "46.0" in text
    assert "leaflet" in text.lower()
    assert isinstance(FoliumMapBackend(), MapBackend)


def test_map_scene_includes_igc_flight(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_igc(source / "flug.igc", bozen_points(), pilot="Ralf Muster")
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        FileIndexer().index(session, project, source, generate_thumbnails=False)
        gps = session.scalar(select(SourceFile))
        assert gps is not None
        set_track_external_url(session, gps.id, "https://de.dhv.de/dbnx/nx.php?id=99")
        session.commit()

    thumbs = open_project.directory / "thumbnails"
    with open_project.session_factory() as session:
        scene = build_map_scene(session, open_project.project_id, thumbs)

    assert len(scene.polylines) == 1
    flight = scene.polylines[0]
    assert flight.kind == "flight"
    assert flight.min_zoom == FLIGHT_LINE_MIN_ZOOM
    assert flight.pilot == "Ralf Muster"
    assert flight.external_url == "https://de.dhv.de/dbnx/nx.php?id=99"
    html = FoliumMapBackend().render(scene, tmp_path / "igc.html").read_text(encoding="utf-8")
    assert "DHV-Leonardo" in html
    assert "Ralf Muster" in html
    assert "minZoom" in html
    assert "Flugtracks" in html


def test_offline_backend_omits_osm_tiles(tmp_path: Path) -> None:
    scene = MapScene(
        polylines=(MapPolyline(name="Spur", points=((46.0, 11.0), (46.1, 11.1))),),
        center=(46.0, 11.0),
    )
    text = FoliumMapBackend(tiles=None).render(scene, tmp_path / "offline.html").read_text(encoding="utf-8")
    assert "openstreetmap.org" not in text.lower()
