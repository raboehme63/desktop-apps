from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy.orm import Session

from travelcore.database.project_store import OpenProject, ProjectStore

MAP_TILE_COLOR = (186, 200, 168)


@pytest.fixture(autouse=True)
def stub_osm_map_tiles(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep tests off the OSM tile network; Leaflet excerpts stay deterministic."""

    def fake_tile(_z: int, _x: int, _y: int, *, cache_dir=None) -> Image.Image:
        return Image.new("RGB", (256, 256), MAP_TILE_COLOR)

    monkeypatch.setattr("travelcore.maps.static.fetch_osm_tile", fake_tile)


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
