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
    assert reopened.read_only is False


def test_open_read_only_sqlite_rejects_writes(tmp_path: Path) -> None:
    from sqlalchemy.exc import OperationalError

    directory = tmp_path / "alpen"
    ProjectStore().create(directory, "Alpen 2025")
    settings = directory / "settings.toml"
    stamp = settings.stat().st_mtime_ns
    opened = ProjectStore().open(directory, read_only=True)
    assert opened.read_only is True
    assert settings.stat().st_mtime_ns == stamp
    with pytest.raises(OperationalError):
        with opened.session_factory() as session:
            project = session.scalar(select(Project))
            assert project is not None
            project.name = "Schreibversuch"
            session.commit()


def test_schema_contains_core_tables(tmp_path: Path) -> None:
    opened = ProjectStore().create(tmp_path / "schema", "Schema")
    with opened.session_factory() as session:
        inspector = inspect(session.get_bind())
        tables = set(inspector.get_table_names())
        columns = {column["name"] for column in inspector.get_columns("gps_tracks")}
        source_columns = {column["name"] for column in inspector.get_columns("source_files")}
    assert "trip_sections" in tables
    assert "transfer_links" in tables
    assert "section_members" in tables
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
    assert "rotation_degrees" in source_columns
    day_columns = {column["name"] for column in inspector.get_columns("trip_days")}
    section_columns = {column["name"] for column in inspector.get_columns("trip_sections")}
    assert "youtube_urls" in day_columns
    assert "youtube_urls" in section_columns
    assert "leonardo_urls" in day_columns
    assert "leonardo_urls" in section_columns
    photo_columns = {column["name"] for column in inspector.get_columns("photos")}
    assert "sort_status" in photo_columns
    assert "cover_source_file_id" in day_columns
    assert "cover_source_file_id" in section_columns
    assert "outbound_geometry" in section_columns
    assert "outbound_dash" in section_columns
    assert "outbound_symbol" in section_columns
    assert "outbound_track_source_file_id" in section_columns
    assert "hidden" in section_columns
    cluster_columns = {column["name"] for column in inspector.get_columns("similarity_groups")}
    member_columns = {column["name"] for column in inspector.get_columns("similarity_group_members")}
    assert "cluster_type" in cluster_columns
    assert "status" in cluster_columns
    assert "origin" in cluster_columns
    assert "is_key" in member_columns


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
