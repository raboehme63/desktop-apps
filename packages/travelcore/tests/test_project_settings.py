from pathlib import Path

import pytest
from sqlalchemy import select

from travelcore.database.models import Project, SourceFile
from travelcore.database.project_store import ProjectStore
from travelcore.exceptions import ProjectError
from travelcore.project_settings import (
    SETTINGS_FILENAME,
    ProjectSettings,
    ensure_project_settings,
    load_project_settings,
    normalize_stay_link_color,
    rebase_source_file_paths,
    save_project_settings,
)


def test_new_project_writes_settings_file(tmp_path: Path) -> None:
    directory = tmp_path / "alpen"
    ProjectStore().create(directory, "Alpen 2025")
    path = directory / SETTINGS_FILENAME
    assert path.is_file()
    settings = load_project_settings(directory)
    assert settings.export.default_format == "html"
    assert settings.placeholders.map_provider == "leaflet"
    assert settings.placeholders.map_link_color == "#ffffff"
    assert settings.placeholders.map_show_photo_cones is False
    assert settings.placeholders.map_show_reserve is False
    assert settings.placeholders.map_show_sat_labels is False
    assert settings.placeholders.map_show_sat_streets is False


def test_settings_roundtrip_preserves_values(tmp_path: Path) -> None:
    directory = tmp_path / "reise"
    directory.mkdir()
    settings = ProjectSettings()
    settings.paths.source_root = str((tmp_path / "fotos").resolve())
    settings.export.default_format = "pdf"
    settings.matching.gps_match_max_delta_seconds = 45
    settings.matching.default_timezone = "Europe/Berlin"
    settings.performance.worker_count = 4
    settings.placeholders.journal_language = "it"
    settings.placeholders.map_link_color = "#aabbcc"
    settings.placeholders.map_show_photo_cones = True
    settings.placeholders.map_show_reserve = True
    settings.placeholders.map_show_sat_labels = True
    settings.placeholders.map_show_sat_streets = True
    save_project_settings(directory, settings)
    loaded = load_project_settings(directory)
    assert loaded.export.default_format == "pdf"
    assert loaded.matching.gps_match_max_delta_seconds == 45
    assert loaded.matching.default_timezone == "Europe/Berlin"
    assert loaded.performance.worker_count == 4
    assert loaded.placeholders.journal_language == "it"
    assert loaded.placeholders.map_link_color == "#aabbcc"
    assert loaded.placeholders.map_show_photo_cones is True
    assert loaded.placeholders.map_show_reserve is True
    assert loaded.placeholders.map_show_sat_labels is True
    assert loaded.placeholders.map_show_sat_streets is True
    assert loaded.paths.source_root is not None
    assert Path(loaded.paths.source_root) == tmp_path / "fotos"


def test_normalize_stay_link_color_accepts_hex_and_falls_back() -> None:
    assert normalize_stay_link_color("#ABC") == "#aabbcc"
    assert normalize_stay_link_color("white") == "#ffffff"
    assert normalize_stay_link_color("nope") == "#ffffff"
    assert normalize_stay_link_color("#00FF00") == "#00ff00"


def test_corrupt_settings_raise(tmp_path: Path) -> None:
    directory = tmp_path / "kaputt"
    directory.mkdir()
    (directory / SETTINGS_FILENAME).write_text("not = [toml", encoding="utf-8")
    with pytest.raises(ProjectError, match="nicht lesbar"):
        load_project_settings(directory)


def test_ensure_fills_source_root_from_database(tmp_path: Path) -> None:
    directory = tmp_path / "alt"
    directory.mkdir()
    settings = ensure_project_settings(directory, source_root=str(tmp_path / "media"))
    assert settings.paths.source_root is not None
    assert Path(settings.paths.source_root) == tmp_path / "media"


def test_rebase_rewrites_indexed_paths(tmp_path: Path) -> None:
    old_root = tmp_path / "alt"
    new_root = tmp_path / "neu"
    old_root.mkdir()
    new_root.mkdir()
    opened = ProjectStore().create(tmp_path / "projekt", "Rebase")
    old_file = old_root / "tag" / "foto.jpg"
    with opened.session_factory() as session:
        project = session.get(Project, opened.project_id)
        assert project is not None
        project.source_root = str(old_root)
        session.add(
            SourceFile(
                project_id=project.id,
                path=str(old_file),
                filename="foto.jpg",
                file_kind="photo",
                extension=".jpg",
                size_bytes=12,
                imported_at=project.created_at,
                status="ok",
                timezone_unknown=True,
            )
        )
        session.commit()

    with opened.session_factory() as session:
        count = rebase_source_file_paths(
            session,
            opened.project_id,
            old_root=old_root,
            new_root=new_root,
        )
        session.commit()
        row = session.scalar(select(SourceFile))
        project = session.get(Project, opened.project_id)

    assert count == 1
    assert row is not None
    assert Path(row.path) == new_root / "tag" / "foto.jpg"
    assert project is not None
    assert Path(project.source_root or "") == new_root
