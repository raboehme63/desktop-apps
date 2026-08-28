from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from gpx_fixtures import write_gpx
from igc_fixtures import bozen_points, write_igc
from jpeg_fixtures import write_jpeg_with_exif
from sqlalchemy import select

from travelcore.database.models import Place, Project, SourceFile, Trip, TripDay
from travelcore.database.project_store import OpenProject
from travelcore.gps.ingest import set_track_external_url
from travelcore.maps import (
    COVER_ICON_PX,
    FLIGHT_LINE_MIN_ZOOM,
    PHOTO_STACK_DISABLE_ZOOM,
    FoliumMapBackend,
    MapBackend,
    MapMarker,
    MapPolyline,
    MapScene,
    StayLink,
    build_map_group_detail,
    build_map_overview,
    build_map_scene,
    build_map_timeline,
    downsample_points,
    ensure_map_cache,
    photo_fov_degrees,
    stay_link_visible,
    stay_links_from_entries,
)
from travelcore.maps.cache import map_html_path, map_stamp_path
from travelcore.maps.groups import MapTimelineCard, count_card_media, parse_group_key, pick_cover_item
from travelcore.media.gallery import SORT_REJECTED, SORT_RESERVE
from travelcore.media.indexer import FileIndexer
from travelcore.timeline import KIND_MOVEMENT, KIND_STAY, create_section, set_photo_sort_status, sync_timeline
from travelcore.timeline.types import TimelineDay, TimelineEntry, TimelinePhoto, TimelineSection


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
        covers = [item for item in scene.markers if item.kind == "cover"]
        assert not scene.empty
        assert scene.polylines == ()
        assert len(covers) == 1
        assert covers[0].group_key is not None
        assert covers[0].group_key.startswith("loose:")
        detail = build_map_group_detail(session, open_project.project_id, covers[0].group_key, thumbs)
    photos = [item for item in detail.markers if item.kind == "photo"]
    assert len(photos) == 1
    assert photos[0].subtitle == "platz.jpg"
    tracks = [item for item in detail.markers if item.kind == "track"]
    assert len(tracks) == 1
    assert len(detail.polylines) == 1
    assert detail.polylines[0].points[0] == (46.0, 11.0)


def test_map_scene_includes_place(open_project: OpenProject) -> None:
    now = datetime(2025, 5, 15, tzinfo=UTC)
    with open_project.session_factory() as session:
        trip = Trip(project_id=open_project.project_id, title="Test", origin="auto")
        session.add(trip)
        session.flush()
        day = TripDay(trip_id=trip.id, day_index=0, date=now, origin="manual")
        session.add(day)
        session.flush()
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
        covers = [item for item in scene.markers if item.kind == "cover"]
        assert len(covers) == 1
        assert covers[0].group_key is not None
        detail = build_map_group_detail(session, open_project.project_id, covers[0].group_key, thumbs)
    kinds = {item.kind for item in detail.markers}
    assert "place" in kinds
    place = next(item for item in detail.markers if item.kind == "place")
    assert place.label == "Markt"


def test_folium_overview_cover_uses_expand_url(tmp_path: Path) -> None:
    scene = MapScene(
        markers=(
            MapMarker(
                latitude=46.0,
                longitude=11.0,
                label="Aufenthalt",
                kind="cover",
                group_key="section:1",
            ),
            MapMarker(
                latitude=47.5,
                longitude=12.2,
                label="Gipfel",
                kind="cover",
                group_key="section:2",
            ),
        ),
        stay_links=(
            StayLink(
                start=(46.0, 11.0),
                end=(47.5, 12.2),
                start_key="section:1",
                end_key="section:2",
                via_transfer=True,
            ),
        ),
        center=(46.75, 11.6),
    )
    text = FoliumMapBackend().render(scene, tmp_path / "overview.html").read_text(encoding="utf-8")
    assert "window.traveljournalConfig" in text
    assert "data-group-key" in text
    assert "section:1" in text
    assert "border-radius: 50%" in text
    assert "width: 47px" in text
    assert "border: 3px solid #fff" in text
    assert "tj-thumb" in text
    assert "Reiseabschnitt schließen" in text
    assert "traveljournalCloseSection" in text
    assert "tj-close-section" in text
    assert "traveljournalOpenMedia" in text
    assert "dblclick" in text
    assert "bindPopup" in text
    assert "popupopen" in text
    assert "tj-popup-thumb" in text
    assert "traveljournalShowDetail" in text
    assert "covers.eachLayer" in text
    assert "window.traveljournalExpand(key)" in text
    assert "layerKey" in text
    assert "group_key" in text
    assert "getLayers().length" in text
    assert "latLngToContainerPoint" in text
    assert "map.dragging.disable" in text
    assert "if (item.source_file_id)" in text
    assert "if item.source_file_id)" not in text
    assert "bindCover" in text
    assert "pointerup" in text
    assert "zoom: {animate: false}" in text
    assert "traveljournalSetTimeline" not in text
    assert 'id="tj-timeline"' not in text
    assert "expandTimer" not in text
    assert "pointer-events: auto" in text
    assert "fitOverview" in text
    assert "traveljournalFitOverview" in text
    assert "doubleClickZoom.disable" in text
    assert "covers.getBounds" in text
    assert "traveljournalFocusCover" in text
    assert "map.unproject(point" in text
    assert "animate: true" in text
    assert "traveljournalOverlayPad" in text
    assert "tj-focused" in text
    assert "46.0" in text and "47.5" in text
    assert "traveljournalShowOverview" not in text
    assert "var stayLinks" in text
    assert "drawStayLinks" in text
    assert "stayLinkVisible" in text
    assert "var COVER_PX = 54" in text
    assert "var INSET_PX = 23" in text
    assert 'var LINK_COLOR = "#ffffff"' in text or "var LINK_COLOR = '#ffffff'" in text
    assert "tj-stay-arrow" in text
    assert "tj-stay-arrow-rot" in text
    assert "iconAnchor: [9, 9]" in text or "iconAnchor:[9,9]" in text
    assert "tj-stay-link" in text
    assert "traveljournalDrawStayLinks" in text
    assert '"via_transfer": true' in text
    assert "if (savedView)" in text
    assert "[[46.0, 11.0], [47.5, 12.2]]" in text or "[[46.0, 11.0],[47.5, 12.2]]" in text
    assert "Satellit" in text
    assert "Topo" in text
    assert "Straßenkarte" in text
    assert "Gelände" not in text
    assert "opentopomap" in text
    assert "World_Imagery" in text
    assert "tj-basemap" in text
    assert "tj-basemap-menu" in text
    assert "tj-basemap-btn" in text
    assert "Kartentyp" in text
    assert "traveljournalSetBasemap" in text
    assert "traveljournal-basemap" in text
    assert "tj-settings" in text
    assert "Fotokegel anzeigen" in text
    assert "Reserve-Elemente anzeigen" in text
    assert "traveljournal-photo-cones" in text
    assert "traveljournal-show-reserve" in text
    assert "saveMapSettings" in text
    assert "traveljournalApplyStoredMapFlags" in text
    assert "traveljournalMapFlags" in text
    assert "setShowReserve" in text
    assert "tj-photo-cone" in text
    assert "focusPhoto" in text
    assert "clearPhotoFocus" in text
    assert "syncPhotoStack" in text
    assert "overlapPhotoGroups" in text
    assert "tj-photo-date" in text
    assert "tooltipAnchor: [0, 26]" in text or "tooltipAnchor:[0,26]" in text
    assert "leaflet-tooltip-bottom.tj-photo-date" in text
    assert "Karteneinstellungen" in text
    assert 'r=\\"11\\"' in text


def test_overview_offline_omits_satellite(tmp_path: Path) -> None:
    scene = MapScene(
        markers=(
            MapMarker(
                latitude=46.0,
                longitude=11.0,
                label="Aufenthalt",
                kind="cover",
                group_key="section:1",
            ),
        ),
        center=(46.0, 11.0),
    )
    text = FoliumMapBackend(tiles=None).render(scene, tmp_path / "off.html").read_text(encoding="utf-8")
    assert "World_Imagery" not in text
    assert "arcgisonline" not in text.lower()
    assert "opentopomap" not in text.lower()
    assert "traveljournalSetBasemap" not in text
    assert "Fotokegel anzeigen" in text
    assert "Karteneinstellungen" in text


def test_timeline_js_cards_uses_relative_cover(tmp_path: Path) -> None:
    from travelcore.maps import timeline_js_cards
    from travelcore.maps.groups import MapTimelineCard

    html_path = tmp_path / "cache" / "map.html"
    html_path.parent.mkdir()
    html_path.write_text("<html></html>", encoding="utf-8")
    cover = tmp_path / "cache" / "cover.jpg"
    cover.write_bytes(b"x")
    cards = timeline_js_cards(
        (
            MapTimelineCard(
                group_key="section:1",
                title="Eins",
                time_label="am 01.05.2025",
                cover_path=cover,
                latitude=46.0,
                longitude=11.0,
            ),
        ),
        html_path,
    )
    assert cards[0]["key"] == "section:1"
    assert cards[0]["cover"] == "cover.jpg"
    assert cards[0]["lat"] == 46.0


def test_leaflet_payload_includes_source_file_id(tmp_path: Path) -> None:
    from travelcore.maps import leaflet_payload

    html_path = tmp_path / "map.html"
    html_path.write_text("<html></html>", encoding="utf-8")
    thumb = tmp_path / "thumb.jpg"
    thumb.write_bytes(b"x")
    scene = MapScene(
        markers=(
            MapMarker(
                latitude=46.0,
                longitude=11.0,
                label="foto",
                kind="photo",
                source_file_id=7,
                preview_path=thumb,
            ),
        ),
        center=(46.0, 11.0),
    )
    payload = leaflet_payload(scene, html_path)
    assert payload["markers"][0]["source_file_id"] == 7
    assert payload["markers"][0]["preview"] == "thumb.jpg"
    html = payload["markers"][0]["popup_html"]
    assert "tj-popup-thumb" in html
    assert 'data-source-id="7"' in html
    assert 'width="180"' in html
    heading_scene = MapScene(
        markers=(
            MapMarker(
                latitude=46.0,
                longitude=11.0,
                label="foto",
                kind="photo",
                source_file_id=7,
                heading_degrees=90.0,
                fov_degrees=63.0,
                sort_status="reserve",
            ),
        ),
        center=(46.0, 11.0),
    )
    headed = leaflet_payload(heading_scene, html_path)["markers"][0]
    assert headed["heading"] == 90.0
    assert headed["fov"] == 63.0
    assert headed["sort_status"] == "reserve"


def test_interaction_config_is_declarative_payload(tmp_path: Path) -> None:
    from travelcore.maps import interaction_config

    html_path = tmp_path / "map.html"
    html_path.write_text("<html></html>", encoding="utf-8")
    scene = MapScene(
        markers=(
            MapMarker(
                latitude=46.0,
                longitude=11.0,
                label="Tag",
                kind="cover",
                group_key="loose:1",
            ),
        ),
        stay_links=(
            StayLink(
                start=(46.0, 11.0),
                end=(47.0, 12.0),
                start_key="loose:1",
                end_key="loose:2",
            ),
        ),
        center=(46.5, 11.5),
    )
    config = interaction_config(scene, html_path, link_color="#ffffff")
    assert config["cover_px"] == COVER_ICON_PX
    assert config["stay_links"][0]["start_key"] == "loose:1"
    assert "detail" in config
    assert config["link_color"] == "#ffffff"


def test_detail_stacks_nearby_photos_until_zoom_17(tmp_path: Path) -> None:
    overview = MapScene(
        markers=(
            MapMarker(
                latitude=46.0,
                longitude=11.0,
                label="Aufenthalt",
                kind="cover",
                group_key="section:1",
            ),
        ),
        center=(46.0, 11.0),
    )
    text = FoliumMapBackend().render(overview, tmp_path / "overview.html").read_text(encoding="utf-8")
    assert "leaflet.markercluster" in text.lower()
    assert "photoClusterGroup" in text
    assert f"disableClusteringAtZoom: {PHOTO_STACK_DISABLE_ZOOM}" in text
    assert "spiderfyOnMaxZoom: false" in text
    assert "syncPhotoStack" in text
    assert "overlapPhotoGroups" in text
    assert "PHOTO_ROTATE_MS" in text
    assert "getChildCount" in text
    assert "tj-stack" in text
    assert "tj-photo-date" in text
    assert "item.kind !== 'place'" in text
    assert "cluster.addTo(detail)" in text

    scene = MapScene(
        markers=(
            MapMarker(
                latitude=46.0,
                longitude=11.0,
                label="a",
                kind="photo",
                day_key="2024-06-01",
            ),
            MapMarker(
                latitude=46.0001,
                longitude=11.0001,
                label="b",
                kind="photo",
                day_key="2024-06-02",
            ),
            MapMarker(latitude=47.0, longitude=12.0, label="Ort", kind="place"),
        ),
        center=(46.0, 11.0),
    )
    detail = FoliumMapBackend().render(scene, tmp_path / "detail.html").read_text(encoding="utf-8")
    assert "markerClusterGroup" in detail
    assert "disableClusteringAtZoom" in detail
    assert str(PHOTO_STACK_DISABLE_ZOOM) in detail
    assert "getChildCount" in detail
    assert "tj-stack" in detail


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
    assert "tile.openstreetmap.de" in text
    assert "World_Imagery" in text
    assert "Satellit" in text
    assert "Topo" in text
    assert "Straßenkarte" in text
    assert "opentopomap" in text
    assert "tj-basemap-menu" in text
    assert "traveljournalSetBasemap" in text
    assert "Karteneinstellungen" in text
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
        overview = build_map_scene(session, open_project.project_id, thumbs)
        covers = [item for item in overview.markers if item.kind == "cover"]
        assert len(covers) == 1
        assert covers[0].group_key is not None
        scene = build_map_group_detail(session, open_project.project_id, covers[0].group_key, thumbs)

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
    assert "openstreetmap.de" not in text.lower()
    assert "arcgisonline" not in text.lower()
    assert "World_Imagery" not in text
    assert "opentopomap" not in text.lower()


def _index_gpx_track(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
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
        FileIndexer().index(session, project, source, generate_thumbnails=False)
        session.commit()


def test_map_cache_reuses_html_when_inputs_unchanged(
    open_project: OpenProject, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _index_gpx_track(open_project, tmp_path)
    thumbs = open_project.directory / "thumbnails"
    calls = {"n": 0}
    original = FoliumMapBackend.render

    def wrapped(self: FoliumMapBackend, scene: MapScene, output_html: Path) -> Path:
        calls["n"] += 1
        return original(self, scene, output_html)

    monkeypatch.setattr("travelcore.maps.cache.FoliumMapBackend.render", wrapped)
    kwargs = {
        "session_factory": open_project.session_factory,
        "project_id": open_project.project_id,
        "project_dir": open_project.directory,
        "thumbs_dir": thumbs,
        "db_path": open_project.db_path,
        "size": 256,
        "map_provider": "leaflet",
    }
    first = ensure_map_cache(**kwargs)
    assert not first.from_cache
    assert first.render_seq == 1
    assert first.html_path == map_html_path(open_project.directory)
    assert first.html_path is not None and first.html_path.is_file()
    html = first.html_path.read_text(encoding="utf-8")
    assert "traveljournalExpand" in html
    assert "pointerup" in html
    assert "border-radius: 50%" in html
    assert "traveljournalShowDetail" in html
    assert map_stamp_path(open_project.directory).is_file()
    assert calls["n"] == 1
    second = ensure_map_cache(**kwargs)
    assert second.from_cache
    assert second.tracks == first.tracks
    assert second.render_seq == first.render_seq
    assert calls["n"] == 1


def test_map_cache_rebuilds_when_provider_or_force_changes(
    open_project: OpenProject, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _index_gpx_track(open_project, tmp_path)
    thumbs = open_project.directory / "thumbnails"
    calls = {"n": 0}
    original = FoliumMapBackend.render

    def wrapped(self: FoliumMapBackend, scene: MapScene, output_html: Path) -> Path:
        calls["n"] += 1
        return original(self, scene, output_html)

    monkeypatch.setattr("travelcore.maps.cache.FoliumMapBackend.render", wrapped)
    kwargs = {
        "session_factory": open_project.session_factory,
        "project_id": open_project.project_id,
        "project_dir": open_project.directory,
        "thumbs_dir": thumbs,
        "db_path": open_project.db_path,
        "size": 256,
    }
    ensure_map_cache(**kwargs, map_provider="leaflet")
    ensure_map_cache(**kwargs, map_provider="offline")
    assert calls["n"] == 2
    ensure_map_cache(**kwargs, map_provider="offline")
    assert calls["n"] == 2
    ensure_map_cache(**kwargs, map_provider="offline", force=True)
    assert calls["n"] == 3
    forced = ensure_map_cache(**kwargs, map_provider="offline", force=True)
    assert not forced.from_cache
    assert forced.render_seq >= 2


def test_map_cache_rebuilds_when_link_color_changes(
    open_project: OpenProject, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _index_gpx_track(open_project, tmp_path)
    thumbs = open_project.directory / "thumbnails"
    calls = {"n": 0}
    original = FoliumMapBackend.render

    def wrapped(self: FoliumMapBackend, scene: MapScene, output_html: Path) -> Path:
        calls["n"] += 1
        return original(self, scene, output_html)

    monkeypatch.setattr("travelcore.maps.cache.FoliumMapBackend.render", wrapped)
    kwargs = {
        "session_factory": open_project.session_factory,
        "project_id": open_project.project_id,
        "project_dir": open_project.directory,
        "thumbs_dir": thumbs,
        "db_path": open_project.db_path,
        "size": 256,
        "map_provider": "leaflet",
    }
    ensure_map_cache(**kwargs, map_link_color="#ffffff")
    ensure_map_cache(**kwargs, map_link_color="#ffffff")
    assert calls["n"] == 1
    ensure_map_cache(**kwargs, map_link_color="#ff0000")
    assert calls["n"] == 2
    html = map_html_path(open_project.directory).read_text(encoding="utf-8")
    assert "#ff0000" in html


def test_map_cache_empty_project_stamps_without_html(open_project: OpenProject) -> None:
    thumbs = open_project.directory / "thumbnails"
    first = ensure_map_cache(
        open_project.session_factory,
        open_project.project_id,
        open_project.directory,
        thumbs,
        db_path=open_project.db_path,
        size=256,
        map_provider="leaflet",
    )
    assert first.empty
    assert first.html_path is None
    assert not map_html_path(open_project.directory).is_file()
    second = ensure_map_cache(
        open_project.session_factory,
        open_project.project_id,
        open_project.directory,
        thumbs,
        db_path=open_project.db_path,
        size=256,
        map_provider="leaflet",
    )
    assert second.from_cache
    assert second.empty


def _timeline_photo(
    name: str,
    *,
    file_id: int,
    latitude: float | None,
    longitude: float | None = 11.0,
    file_kind: str = "photo",
    sort_status: str | None = None,
) -> TimelinePhoto:
    return TimelinePhoto(
        source_file_id=file_id,
        filename=name,
        path=name,
        thumbnail_path=Path("thumb.jpg"),
        captured_at=None,
        used_in_journal=False,
        is_cover=False,
        is_favorite=False,
        gps_latitude=latitude,
        gps_longitude=longitude if latitude is not None else None,
        file_kind=file_kind,
        sort_status=sort_status,
    )


def test_pick_cover_item_uses_first_gps_photo() -> None:
    items = [
        _timeline_photo("route.gpx", file_id=1, latitude=46.0, file_kind="gps"),
        _timeline_photo("ohne.jpg", file_id=2, latitude=None),
        _timeline_photo("mit.jpg", file_id=3, latitude=46.5),
        _timeline_photo("spaeter.jpg", file_id=4, latitude=47.0),
    ]
    chosen = pick_cover_item(items, None)
    assert chosen is not None
    assert chosen.filename == "mit.jpg"


def test_pick_cover_item_uses_first_gps_track_without_photo_fix() -> None:
    items = [
        _timeline_photo("ohne.jpg", file_id=1, latitude=None),
        _timeline_photo("clip.mp4", file_id=2, latitude=46.4, file_kind="video"),
        _timeline_photo("route.gpx", file_id=3, latitude=46.5, file_kind="gps"),
        _timeline_photo("later.gpx", file_id=4, latitude=47.0, file_kind="gps"),
    ]
    chosen = pick_cover_item(items, None)
    assert chosen is not None
    assert chosen.filename == "route.gpx"


def test_pick_cover_item_falls_back_when_stored_cover_missing() -> None:
    items = [
        _timeline_photo("ohne.jpg", file_id=1, latitude=None),
        _timeline_photo("mit.jpg", file_id=2, latitude=46.5),
    ]
    chosen = pick_cover_item(items, 99)
    assert chosen is not None
    assert chosen.filename == "mit.jpg"


def test_pick_cover_item_prefers_stored_cover() -> None:
    items = [
        _timeline_photo("eins.jpg", file_id=1, latitude=46.0),
        _timeline_photo("zwei.jpg", file_id=2, latitude=47.0),
    ]
    chosen = pick_cover_item(items, 2)
    assert chosen is not None
    assert chosen.filename == "zwei.jpg"


def test_pick_cover_item_skips_rejected() -> None:
    items = [
        _timeline_photo("weg.jpg", file_id=1, latitude=46.0, sort_status=SORT_REJECTED),
        _timeline_photo("ok.jpg", file_id=2, latitude=46.5),
        _timeline_photo("reserve.jpg", file_id=3, latitude=47.0, sort_status=SORT_RESERVE),
    ]
    chosen = pick_cover_item(items, 1)
    assert chosen is not None
    assert chosen.filename == "ok.jpg"


def test_count_card_media_splits_reserve_and_skips_rejected() -> None:
    items = [
        _timeline_photo("ok.jpg", file_id=1, latitude=46.0),
        _timeline_photo("reserve.jpg", file_id=2, latitude=46.0, sort_status=SORT_RESERVE),
        _timeline_photo("weg.jpg", file_id=3, latitude=46.0, sort_status=SORT_REJECTED),
        _timeline_photo("clip.mp4", file_id=4, latitude=46.0, file_kind="video"),
        _timeline_photo("route.gpx", file_id=5, latitude=46.0, file_kind="gps"),
        _timeline_photo("spare.gpx", file_id=6, latitude=46.0, file_kind="gps", sort_status=SORT_RESERVE),
        _timeline_photo("flight.igc", file_id=7, latitude=46.0, file_kind="gps"),
        _timeline_photo("spare.igc", file_id=8, latitude=46.0, file_kind="gps", sort_status=SORT_RESERVE),
        _timeline_photo("weg.igc", file_id=9, latitude=46.0, file_kind="gps", sort_status=SORT_REJECTED),
    ]
    photos, photo_reserve, tracks, track_reserve, igc, igc_reserve, youtube = count_card_media(
        items, ["https://youtu.be/aaaaaaaaaaa"]
    )
    assert (photos, photo_reserve, tracks, track_reserve, igc, igc_reserve, youtube) == (
        2,
        1,
        1,
        1,
        1,
        1,
        1,
    )
    card = MapTimelineCard(
        group_key="section:1",
        title="Bozen",
        time_label="am 15.05.2025",
        photo_count=photos,
        photo_reserve_count=photo_reserve,
        track_count=tracks,
        track_reserve_count=track_reserve,
        igc_count=igc,
        igc_reserve_count=igc_reserve,
        youtube_count=youtube,
    )
    assert card.visible_counts(show_reserve=False) == (2, 1, 1, 1)
    assert card.visible_counts(show_reserve=True) == (3, 2, 2, 1)


def test_photo_fov_degrees_from_35mm() -> None:
    wide = photo_fov_degrees(24.0)
    tele = photo_fov_degrees(200.0)
    assert wide > tele
    assert 70 < wide < 90
    assert photo_fov_degrees(None) == 63.0


def test_map_detail_omits_rejected_photo(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "keep.jpg",
        datetime_original="2025:05:15 15:32:00",
        offset_original="+02:00",
        latitude=(46.0, 0.0, 0.0),
        longitude=(11.0, 0.0, 0.0),
        heading=90.0,
        heading_ref="T",
        focal_length_35mm=24,
    )
    write_jpeg_with_exif(
        source / "drop.jpg",
        datetime_original="2025:05:15 15:33:00",
        offset_original="+02:00",
        latitude=(46.01, 0.0, 0.0),
        longitude=(11.01, 0.0, 0.0),
    )
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        FileIndexer().index(session, project, source, project_dir=open_project.directory)
        dropped = session.scalar(select(SourceFile).where(SourceFile.filename == "drop.jpg"))
        assert dropped is not None
        set_photo_sort_status(session, dropped.id, SORT_REJECTED)
        session.commit()

    thumbs = open_project.directory / "thumbnails"
    with open_project.session_factory() as session:
        overview = build_map_scene(session, open_project.project_id, thumbs)
        covers = [item for item in overview.markers if item.kind == "cover"]
        assert len(covers) == 1
        detail = build_map_group_detail(session, open_project.project_id, covers[0].group_key, thumbs)
    names = {item.subtitle for item in detail.markers if item.kind == "photo"}
    assert names == {"keep.jpg"}
    keep = next(item for item in detail.markers if item.subtitle == "keep.jpg")
    assert keep.heading_degrees is not None
    assert abs(keep.heading_degrees - 90.0) < 1e-6
    assert keep.fov_degrees is not None
    assert keep.fov_degrees > 70


def test_parse_group_key_accepts_section_day_and_loose() -> None:
    assert parse_group_key("section:12") == ("section", 12)
    assert parse_group_key("day:4") == ("day", 4)
    assert parse_group_key("loose:2025-05-15") == ("loose", "2025-05-15")
    assert parse_group_key("nope") == (None, None)


def test_build_map_timeline_cards_from_section(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "morgen.jpg",
        datetime_original="2025:05:15 09:00:00",
        offset_original="+02:00",
        latitude=(46.0, 0.0, 0.0),
        longitude=(11.0, 0.0, 0.0),
    )
    write_jpeg_with_exif(
        source / "abend.jpg",
        datetime_original="2025:05:15 18:00:00",
        offset_original="+02:00",
        latitude=(46.1, 0.0, 0.0),
        longitude=(11.1, 0.0, 0.0),
    )
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        FileIndexer().index(session, project, source, project_dir=open_project.directory)
        session.commit()
    thumbs = open_project.directory / "thumbnails"
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        snapshot = sync_timeline(session, project, thumbs_dir=thumbs)
        ids = [photo.source_file_id for photo in snapshot.days[0].photos]
        create_section(
            session,
            snapshot.trip_id,
            ids,
            kind=KIND_STAY,
            title="Bozen",
            notes="Ankunft am Abend.",
            youtube_urls=["https://youtu.be/dQw4w9WgXcQ"],
        )
        session.commit()
        cards = build_map_timeline(session, open_project.project_id, thumbs)
    assert len(cards) == 1
    card = cards[0]
    assert card.group_key.startswith("section:")
    assert card.title == "Bozen"
    assert "am 15.05.2025" in card.time_label
    assert "Std." not in card.time_label
    assert card.latitude == 46.0
    assert card.longitude == 11.0
    assert card.cover_path is not None
    assert card.card_kind == KIND_STAY
    assert card.notes == "Ankunft am Abend."
    assert card.stored_title == "Bozen"
    assert card.youtube_urls == ("https://youtu.be/dQw4w9WgXcQ",)
    assert card.photo_count == 2
    assert card.photo_reserve_count == 0
    assert card.track_count == 0
    assert card.igc_count == 0
    assert card.youtube_count == 1
    assert card.visible_counts(show_reserve=False) == (2, 0, 0, 1)


def _stay_entry(section_id: int, latitude: float | None, longitude: float = 11.0) -> TimelineEntry:
    items = ()
    if latitude is not None:
        items = (
            _timeline_photo(
                f"s{section_id}.jpg",
                file_id=section_id,
                latitude=latitude,
                longitude=longitude,
            ),
        )
    return TimelineEntry(
        started_at=datetime(2025, 5, 15, tzinfo=UTC),
        section=TimelineSection(
            id=section_id,
            kind=KIND_STAY,
            mode=None,
            title=f"Stay {section_id}",
            notes=None,
            started_at=datetime(2025, 5, 15, tzinfo=UTC),
            ended_at=datetime(2025, 5, 16, tzinfo=UTC),
            location_name=None,
            location_from=None,
            location_to=None,
            origin="test",
            items=items,
        ),
    )


def _movement_entry(section_id: int) -> TimelineEntry:
    return TimelineEntry(
        started_at=datetime(2025, 5, 15, 12, tzinfo=UTC),
        section=TimelineSection(
            id=section_id,
            kind=KIND_MOVEMENT,
            mode="train",
            title="Transfer",
            notes=None,
            started_at=datetime(2025, 5, 15, 12, tzinfo=UTC),
            ended_at=datetime(2025, 5, 15, 14, tzinfo=UTC),
            location_name=None,
            location_from="A",
            location_to="B",
            origin="test",
            items=(_timeline_photo("t.jpg", file_id=section_id, latitude=46.5, longitude=11.5),),
        ),
    )


def _leftover_day_entry(
    day_id: int,
    latitude: float | None = 46.2,
    longitude: float = 11.0,
) -> TimelineEntry:
    photos = ()
    if latitude is not None:
        photos = (
            _timeline_photo(
                f"day{day_id}.jpg",
                file_id=900 + day_id,
                latitude=latitude,
                longitude=longitude,
            ),
        )
    return TimelineEntry(
        started_at=datetime(2025, 5, 15, tzinfo=UTC),
        leftover_day=TimelineDay(
            id=day_id,
            day_index=0,
            date=date(2025, 5, 15),
            title="Tag",
            notes=None,
            origin="test",
            photos=photos,
        ),
    )


def test_stay_links_connect_days_and_stays_in_timeline_order() -> None:
    first = _stay_entry(1, 46.0, 11.0)
    day = _leftover_day_entry(3)
    second = _stay_entry(2, 47.0, 12.0)
    links = stay_links_from_entries([first, day, second])
    assert len(links) == 2
    assert links[0].start == (46.0, 11.0)
    assert links[0].end == (46.2, 11.0)
    assert links[0].start_key == "section:1"
    assert links[0].end_key == "day:3"
    assert links[1].start_key == "day:3"
    assert links[1].end_key == "section:2"
    assert links[0].via_transfer is False
    assert links[1].via_transfer is False


def test_stay_links_connect_leftover_days() -> None:
    links = stay_links_from_entries(
        [
            _leftover_day_entry(1, 46.0, 11.0),
            _leftover_day_entry(2, 47.0, 12.0),
        ]
    )
    assert len(links) == 1
    assert links[0].start_key == "day:1"
    assert links[0].end_key == "day:2"
    assert links[0].start == (46.0, 11.0)
    assert links[0].end == (47.0, 12.0)


def test_stay_links_skip_transfer_as_endpoint() -> None:
    links = stay_links_from_entries(
        [
            _leftover_day_entry(1, 46.0, 11.0),
            _movement_entry(9),
            _leftover_day_entry(2, 47.0, 12.0),
        ]
    )
    assert len(links) == 1
    assert links[0].start == (46.0, 11.0)
    assert links[0].end == (47.0, 12.0)
    assert links[0].via_transfer is True


def test_stay_links_mark_transfer_between_stays() -> None:
    links = stay_links_from_entries(
        [_stay_entry(1, 46.0, 11.0), _movement_entry(9), _stay_entry(2, 47.0, 12.0)]
    )
    assert len(links) == 1
    assert links[0].via_transfer is True
    assert links[0].style == "straight"


def test_stay_links_skip_stays_without_gps() -> None:
    links = stay_links_from_entries(
        [_stay_entry(1, 46.0, 11.0), _stay_entry(2, None), _stay_entry(3, 47.0, 12.0)]
    )
    assert len(links) == 1
    assert links[0].start_key == "section:1"
    assert links[0].end_key == "section:3"


def test_stay_link_hidden_when_covers_overlap() -> None:
    assert stay_link_visible(COVER_ICON_PX - 1) is False
    assert stay_link_visible(float(COVER_ICON_PX)) is False
    assert stay_link_visible(COVER_ICON_PX + 1) is True


def test_build_map_overview_links_consecutive_stays(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "bozen.jpg",
        datetime_original="2025:05:15 09:00:00",
        offset_original="+02:00",
        latitude=(46.0, 0.0, 0.0),
        longitude=(11.0, 0.0, 0.0),
    )
    write_jpeg_with_exif(
        source / "zug.jpg",
        datetime_original="2025:05:15 12:00:00",
        offset_original="+02:00",
        latitude=(46.5, 0.0, 0.0),
        longitude=(11.4, 0.0, 0.0),
    )
    write_jpeg_with_exif(
        source / "innsbruck.jpg",
        datetime_original="2025:05:15 18:00:00",
        offset_original="+02:00",
        latitude=(47.2, 0.0, 0.0),
        longitude=(11.4, 0.0, 0.0),
    )
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        FileIndexer().index(session, project, source, project_dir=open_project.directory)
        session.commit()
    thumbs = open_project.directory / "thumbnails"
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        snapshot = sync_timeline(session, project, thumbs_dir=thumbs)
        photos = {item.filename: item.source_file_id for item in snapshot.days[0].photos}
        create_section(session, snapshot.trip_id, [photos["bozen.jpg"]], kind=KIND_STAY, title="Bozen")
        create_section(session, snapshot.trip_id, [photos["zug.jpg"]], kind=KIND_MOVEMENT, title="Zug")
        create_section(
            session, snapshot.trip_id, [photos["innsbruck.jpg"]], kind=KIND_STAY, title="Innsbruck"
        )
        session.commit()
        scene = build_map_overview(session, open_project.project_id, thumbs)
    assert len(scene.stay_links) == 1
    link = scene.stay_links[0]
    assert link.start == (46.0, 11.0)
    assert link.end == (47.2, 11.4)
    assert link.via_transfer is True
    assert link.style == "straight"


def test_build_map_overview_links_leftover_days(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "eins.jpg",
        datetime_original="2025:05:15 09:00:00",
        offset_original="+02:00",
        latitude=(46.0, 0.0, 0.0),
        longitude=(11.0, 0.0, 0.0),
    )
    write_jpeg_with_exif(
        source / "zwei.jpg",
        datetime_original="2025:05:16 09:00:00",
        offset_original="+02:00",
        latitude=(47.0, 0.0, 0.0),
        longitude=(12.0, 0.0, 0.0),
    )
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        FileIndexer().index(session, project, source, project_dir=open_project.directory)
        session.commit()
    thumbs = open_project.directory / "thumbnails"
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        sync_timeline(session, project, thumbs_dir=thumbs)
        session.commit()
        scene = build_map_overview(session, open_project.project_id, thumbs)
    covers = [item for item in scene.markers if item.kind == "cover"]
    assert len(covers) == 2
    assert len(scene.stay_links) == 1
    link = scene.stay_links[0]
    assert link.start == (46.0, 11.0)
    assert link.end == (47.0, 12.0)
    assert link.start_key.startswith("day:")
    assert link.end_key.startswith("day:")
    assert link.via_transfer is False
