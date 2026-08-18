from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from travelcore.database.project_store import OpenProject, ProjectStore


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    return tmp_path / "reise_test"


@pytest.fixture
def open_project(project_dir: Path) -> Iterator[OpenProject]:
    store = ProjectStore()
    opened = store.create(project_dir, "Testreise")
    yield opened


@pytest.fixture
def session(open_project: OpenProject) -> Iterator[Session]:
    with open_project.session_factory() as db:
        yield db
        db.rollback()
