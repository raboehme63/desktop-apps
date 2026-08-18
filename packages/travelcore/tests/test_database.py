from pathlib import Path

from sqlalchemy import inspect, select

from travelcore.database.models import Project
from travelcore.database.project_store import PROJECT_SUBDIRS, ProjectStore


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
    assert "source_files" in tables
    assert "gps_points" in tables
    assert "trips" in tables
    assert "photo_analyses" in tables
    assert "similarity_groups" in tables
    assert "export_configs" in tables
    assert "alembic_version" in tables
