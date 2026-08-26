from pathlib import Path

import pytest
from sqlalchemy import inspect, select, text

from travelcore.database.models import Project
from travelcore.database.project_store import PROJECT_SUBDIRS, ProjectStore, folder_name_from_project_name
from travelcore.exceptions import ProjectError


def test_create_project_layout_and_row(tmp_path: Path) -> None:
    directory = tmp_path / "alpen"
    opened = ProjectStore().create(directory, "Alpen 2025")

    assert (directory / "project.sqlite").is_file()
    assert (directory / "settings.toml").is_file()
    for name in PROJECT_SUBDIRS:
        assert (directory / name).is_dir()
    assert opened.name == "Alpen 2025"

    with opened.session_factory() as session:
        project = session.scalar(select(Project))
        assert project is not None
        assert project.name == "Alpen 2025"


def test_open_existing_project(tmp_path: Path) -> None:
    directory = tmp_path / "alpen"
    ProjectStore().create(directory, "Alpen 2025")
    reopened = ProjectStore().open(directory)
    assert reopened.name == "Alpen 2025"


def test_schema_contains_core_tables(tmp_path: Path) -> None:
    opened = ProjectStore().create(tmp_path / "schema", "Schema")
    with opened.session_factory() as session:
        inspector = inspect(session.get_bind())
        tables = set(inspector.get_table_names())
        columns = {column["name"] for column in inspector.get_columns("gps_tracks")}
        source_columns = {column["name"] for column in inspector.get_columns("source_files")}
    assert "source_files" in tables
    assert "gps_points" in tables
    assert "trips" in tables
    assert "photo_analyses" in tables
    assert "similarity_groups" in tables
    assert "export_configs" in tables
    assert "alembic_version" in tables
    assert "track_format" in columns
    assert "pilot" in columns
    assert "external_url" in columns
    assert "heading_degrees" in source_columns
    assert "heading_ref" in source_columns
    assert "heading_source" in source_columns
    assert "focal_length_35mm" in source_columns


def test_folder_name_from_project_name_strips_invalid_chars() -> None:
    assert folder_name_from_project_name("Italien 2025") == "Italien 2025"
    assert folder_name_from_project_name("Italien: Dolomiten") == "Italien Dolomiten"
    assert folder_name_from_project_name("  Rom / Florenz  ") == "Rom Florenz"
    assert folder_name_from_project_name("???") == ""
    assert folder_name_from_project_name("CON") == "Projekt CON"


def test_create_under_uses_name_as_subdirectory(tmp_path: Path) -> None:
    parent = tmp_path / "reisen"
    parent.mkdir()
    opened = ProjectStore().create_under(parent, "Alpen 2025")
    expected = parent / "Alpen 2025"
    assert opened.directory == expected.resolve()
    assert opened.name == "Alpen 2025"
    assert (expected / "project.sqlite").is_file()
    assert (expected / "settings.toml").is_file()
    for name in PROJECT_SUBDIRS:
        assert (expected / name).is_dir()


def test_create_under_sanitizes_folder_but_keeps_display_name(tmp_path: Path) -> None:
    opened = ProjectStore().create_under(tmp_path, "Italien: 2025")
    assert opened.name == "Italien: 2025"
    assert opened.directory == (tmp_path / "Italien 2025").resolve()
    assert (tmp_path / "Italien 2025" / "project.sqlite").is_file()


def test_create_under_rejects_existing_project(tmp_path: Path) -> None:
    parent = tmp_path / "reisen"
    parent.mkdir()
    store = ProjectStore()
    store.create_under(parent, "Alpen 2025")
    with pytest.raises(ProjectError, match="existiert bereits"):
        store.create_under(parent, "Alpen 2025")


def test_create_under_rejects_empty_name(tmp_path: Path) -> None:
    with pytest.raises(ProjectError, match="Projektnamen"):
        ProjectStore().create_under(tmp_path, "   ")


def test_sqlite_waits_when_busy(tmp_path: Path) -> None:
    opened = ProjectStore().create(tmp_path / "lock", "Lock")
    with opened.session_factory() as session:
        timeout = session.scalar(text("PRAGMA busy_timeout"))
        mode = session.scalar(text("PRAGMA journal_mode"))
    assert int(timeout or 0) >= 30_000
    assert str(mode).lower() == "wal"
