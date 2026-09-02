from pathlib import Path

import pytest
from jpeg_fixtures import write_jpeg_with_exif

from travelcore.database.models import Project
from travelcore.database.project_store import OpenProject
from travelcore.exceptions import ExportError
from travelcore.export.html import (
    export_interactive_dirname,
    export_travelbook_interactive,
    normalize_html_dir,
    unique_export_dir,
)
from travelcore.maps.interaction import leaflet_payload
from travelcore.maps.scene import MapMarker, MapPolyline, MapScene
from travelcore.media.indexer import FileIndexer
from travelcore.media.thumbnails import generate_project_thumbnails
from travelcore.timeline import KIND_STAY, create_section, set_section_hidden, sync_timeline


def test_export_interactive_dirname_and_unique_dir(tmp_path: Path) -> None:
    assert export_interactive_dirname("Alpen 2026") == "Alpen-2026-interaktiv"
    assert export_interactive_dirname("") == "travelbook-interaktiv"
    first = unique_export_dir(tmp_path, "reise-interaktiv")
    first.mkdir()
    second = unique_export_dir(tmp_path, "reise-interaktiv")
    assert second.name == "reise-interaktiv-2"
    assert normalize_html_dir(tmp_path / "reise.html") == tmp_path / "reise"
    assert normalize_html_dir(tmp_path / "reise") == tmp_path / "reise"


def test_leaflet_payload_read_only_omits_rating(tmp_path: Path) -> None:
    html_path = tmp_path / "index.html"
    html_path.write_text("<html></html>", encoding="utf-8")
    scene = MapScene(
        markers=(
            MapMarker(
                latitude=46.0,
                longitude=11.0,
                label="foto",
                kind="photo",
                source_file_id=7,
                sort_status="favorite",
            ),
        ),
        polylines=(
            MapPolyline(
                name="spur",
                points=((46.0, 11.0), (46.1, 11.1)),
                source_file_id=4,
                sort_status="reserve",
            ),
        ),
        center=(46.0, 11.0),
    )
    payload = leaflet_payload(scene, html_path, read_only=True)
    assert "tj-rate" not in payload["markers"][0]["popup_html"]
    assert "tj-rate" not in payload["polylines"][0]["popup_html"]


def test_interactive_html_writes_portable_map(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    original = write_jpeg_with_exif(
        source / "platz.jpg",
        datetime_original="2025:05:15 15:32:00",
        offset_original="+02:00",
        latitude=(46.0, 0.0, 0.0),
        longitude=(11.0, 0.0, 0.0),
    )
    before_mtime = original.stat().st_mtime_ns
    before_size = original.stat().st_size
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        FileIndexer().index(session, project, source, project_dir=open_project.directory)
        session.commit()
        generate_project_thumbnails(session, project, open_project.directory / "thumbnails")

    dest = tmp_path / "export" / "alpen-interaktiv"
    steps: list[tuple[int, int]] = []
    with open_project.session_factory() as session:
        result = export_travelbook_interactive(
            session,
            open_project.project_id,
            open_project.directory / "thumbnails",
            dest,
            title="Alpen",
            progress=lambda current, total: steps.append((current, total)),
        )
    html = result.output_path.read_text(encoding="utf-8")
    assert result.output_path == dest / "index.html"
    assert (dest / "vendor" / "leaflet" / "leaflet.js").is_file()
    assert (dest / "vendor" / "leaflet" / "leaflet.markercluster.js").is_file()
    assert "vendor/leaflet/leaflet.js" in html
    assert "cdn.jsdelivr.net/npm/leaflet@" not in html
    assert "cdnjs.cloudflare.com/ajax/libs/leaflet.markercluster" not in html
    assert "<title>Alpen</title>" in html
    assert '"read_only": true' in html
    assert "window.traveljournalConfig.details" in html or '"details":' in html
    assert "packed[key]" in html
    assert "tj-rate{display:none" in html.replace(" ", "")
    assert "../thumbnails" not in html
    assert "file://" not in html
    media = list((dest / "media").glob("*"))
    assert media
    assert "media/" in html
    assert 'id="tj-strip"' in html
    assert 'id="tj-notes"' in html
    assert 'id="tj-youtube"' in html
    assert 'id="tj-zoom"' in html
    assert 'id="tj-lightbox"' in html
    assert "host.scrollLeft" in html
    assert '"timeline":' in html
    assert '"media":' in html
    assert "traveljournalZoomToCover" in html
    assert "traveljournalSetThumbZoom" in html
    assert list((dest / "media" / "full").glob("*.jpg"))
    assert "media/full/" in html
    assert all(path.is_relative_to(dest) for path in result.files_written)
    assert original.stat().st_mtime_ns == before_mtime
    assert original.stat().st_size == before_size
    assert steps
    assert steps[-1][0] == steps[-1][1]


def test_interactive_html_omits_hidden_section(open_project: OpenProject, tmp_path: Path) -> None:
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
        source / "pause.jpg",
        datetime_original="2025:05:15 12:00:00",
        offset_original="+02:00",
        latitude=(46.5, 0.0, 0.0),
        longitude=(11.4, 0.0, 0.0),
    )
    thumbs = open_project.directory / "thumbnails"
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        FileIndexer().index(session, project, source, project_dir=open_project.directory)
        session.commit()
        generate_project_thumbnails(session, project, thumbs)
        snapshot = sync_timeline(session, project, thumbs_dir=thumbs)
        photos = {item.filename: item.source_file_id for item in snapshot.days[0].photos}
        create_section(session, snapshot.trip_id, [photos["bozen.jpg"]], kind=KIND_STAY, title="Bozen")
        pause = create_section(
            session, snapshot.trip_id, [photos["pause.jpg"]], kind=KIND_STAY, title="Pause"
        )
        set_section_hidden(session, pause.id, True)
        session.commit()
        dest = tmp_path / "site"
        result = export_travelbook_interactive(
            session, open_project.project_id, thumbs, dest, title="Südtirol"
        )
    html = result.output_path.read_text(encoding="utf-8")
    assert "Bozen" in html
    assert "Pause" not in html


def test_interactive_html_includes_journal_and_youtube(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "platz.jpg",
        datetime_original="2025:05:15 15:32:00",
        offset_original="+02:00",
        latitude=(46.0, 0.0, 0.0),
        longitude=(11.0, 0.0, 0.0),
    )
    thumbs = open_project.directory / "thumbnails"
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        FileIndexer().index(session, project, source, project_dir=open_project.directory)
        session.commit()
        generate_project_thumbnails(session, project, thumbs)
        snapshot = sync_timeline(session, project, thumbs_dir=thumbs)
        photo_id = snapshot.days[0].photos[0].source_file_id
        create_section(
            session,
            snapshot.trip_id,
            [photo_id],
            kind=KIND_STAY,
            title="Bozen",
            notes="Ankunft am Abend.",
            youtube_urls=["https://youtu.be/dQw4w9WgXcQ"],
        )
        session.commit()
        dest = tmp_path / "journal-site"
        result = export_travelbook_interactive(session, open_project.project_id, thumbs, dest, title="Alpen")
    html = result.output_path.read_text(encoding="utf-8")
    assert "Ankunft am Abend." in html
    assert "https://youtu.be/dQw4w9WgXcQ" in html
    assert "img.youtube.com" in html
    assert "Tagebucheintrag" in html
    assert '"kind": "stay"' in html


def test_interactive_html_rejects_empty_map(open_project: OpenProject, tmp_path: Path) -> None:
    dest = tmp_path / "empty-site"
    with open_project.session_factory() as session, pytest.raises(ExportError, match="Keine Karte"):
        export_travelbook_interactive(
            session,
            open_project.project_id,
            open_project.directory / "thumbnails",
            dest,
        )
    assert not dest.exists()


def test_interactive_html_rejects_occupied_destination(open_project: OpenProject, tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    write_jpeg_with_exif(
        source / "platz.jpg",
        datetime_original="2025:05:15 15:32:00",
        offset_original="+02:00",
        latitude=(46.0, 0.0, 0.0),
        longitude=(11.0, 0.0, 0.0),
    )
    dest = tmp_path / "taken"
    dest.mkdir()
    (dest / "keep.txt").write_text("x", encoding="utf-8")
    with open_project.session_factory() as session:
        project = session.get(Project, open_project.project_id)
        assert project is not None
        FileIndexer().index(session, project, source, project_dir=open_project.directory)
        session.commit()
        with pytest.raises(ExportError, match="nicht leer"):
            export_travelbook_interactive(
                session,
                open_project.project_id,
                open_project.directory / "thumbnails",
                dest,
            )
    assert (dest / "keep.txt").read_text(encoding="utf-8") == "x"
