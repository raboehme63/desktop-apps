from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select

from fitnesscore.ingest import import_path
from fitnesscore.store import init_store
from travelcore.database.models import Project, SourceFile
from travelcore.database.project_store import ProjectStore
from travelcore.exceptions import ProjectError
from travelcore.gps.igctracks import IGC_TRACKS_DIRNAME
from travelcore.media.indexer import FileIndexer
from travelcore.media.purge import plan_source_sync
from travelcore.project_settings import load_project_settings, save_project_settings
from traveljournal.services.workspace import Workspace


def _igc_bytes() -> bytes:
    lines = [
        "AXXX FITNESSCORE",
        "HFDTEDATE:290826",
        "HFPLTPILOTINCHARGE:Testpilot",
        "HFGTYGLIDERTYPE:Ozone",
        "B1231504629881N01121180EA0123401234",
        "B1232104630000N01121600EA0124001240",
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def _seed_igc_store(tmp_path: Path) -> Path:
    store_dir = tmp_path / "fitness"
    store = init_store(store_dir)
    source = tmp_path / "flights"
    source.mkdir()
    (source / "flug.igc").write_bytes(_igc_bytes())
    result = import_path(store, source)
    assert result.by_kind.get("igc_flight") == 1
    return store_dir


def _open_workspace(tmp_path: Path) -> tuple[Workspace, Path]:
    opened = ProjectStore().create(tmp_path / "reise", "IGC")
    media = tmp_path / "import"
    media.mkdir()
    settings = load_project_settings(opened.directory)
    settings.paths.source_root = str(media)
    save_project_settings(opened.directory, settings)
    workspace = Workspace()
    workspace.current = opened
    return workspace, media


def test_workspace_import_igc_tracks_and_rescan(tmp_path: Path) -> None:
    workspace, media = _open_workspace(tmp_path)
    workspace.save_trip_span(date(2026, 8, 1), date(2026, 9, 1))
    store_dir = _seed_igc_store(tmp_path)
    count = workspace.import_igc_tracks(store_dir)
    assert count == 1
    files = list((media / IGC_TRACKS_DIRNAME).glob("*.igc"))
    assert len(files) == 1
    opened = workspace.current
    assert opened is not None
    with opened.session_factory() as session:
        rows = list(session.scalars(select(SourceFile)))
        assert len(rows) == 1
        assert rows[0].parked is False
        source_id = rows[0].id
        plan = plan_source_sync(session, opened.project_id, media)
        assert plan.missing_count == 0
        assert plan.new_count == 0
        project = session.get(Project, opened.project_id)
        assert project is not None
        FileIndexer().index(
            session,
            project,
            media,
            project_dir=opened.directory,
            generate_thumbnails=False,
            remove_missing=True,
        )
        session.commit()
        assert session.get(SourceFile, source_id) is not None
    assert workspace.import_igc_tracks(store_dir) == 1
    with opened.session_factory() as session:
        assert len(list(session.scalars(select(SourceFile)))) == 1


def test_workspace_import_igc_requires_trip_span(tmp_path: Path) -> None:
    workspace, _media = _open_workspace(tmp_path)
    store_dir = _seed_igc_store(tmp_path)
    with pytest.raises(ProjectError, match="Zeitraum von"):
        workspace.import_igc_tracks(store_dir)


def test_workspace_import_igc_requires_store(tmp_path: Path) -> None:
    workspace, _media = _open_workspace(tmp_path)
    workspace.save_trip_span(date(2026, 8, 1), date(2026, 9, 1))
    with pytest.raises(ProjectError, match="Activity-Datenbank"):
        workspace.import_igc_tracks(tmp_path / "missing-store")


def test_workspace_import_igc_reports_progress(tmp_path: Path) -> None:
    workspace, _media = _open_workspace(tmp_path)
    workspace.save_trip_span(date(2026, 8, 1), date(2026, 9, 1))
    store_dir = _seed_igc_store(tmp_path)
    seen: list[tuple[int, int, str]] = []
    count = workspace.import_igc_tracks(store_dir, progress=lambda c, t, m: seen.append((c, t, m)))
    assert count == 1
    assert seen
    assert any("Schreibe" in message or "Indexiere" in message for _, _, message in seen)


def test_workspace_reload_deletes_orphan_igc_on_disk(tmp_path: Path) -> None:
    from travelcore.media.indexer import count_by_kind

    workspace, media = _open_workspace(tmp_path)
    workspace.save_trip_span(date(2026, 8, 1), date(2026, 9, 1))
    store_dir = _seed_igc_store(tmp_path)
    assert workspace.import_igc_tracks(store_dir) == 1
    dest = media / IGC_TRACKS_DIRNAME
    orphan = dest / "orphan.igc"
    orphan.write_text("AXXX\n", encoding="ascii")
    opened = workspace.current
    assert opened is not None
    with opened.session_factory() as session:
        before = count_by_kind(session, opened.project_id)["flights"]
    assert workspace.import_igc_tracks(store_dir) == 1
    assert not orphan.exists()
    assert list(dest.glob("*.igc"))
    with opened.session_factory() as session:
        assert count_by_kind(session, opened.project_id)["flights"] == before == 1
