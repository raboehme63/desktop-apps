from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select

from fitnesscore.ingest import import_path
from fitnesscore.store import init_store, open_store
from travelcore.database.models import Project, SourceFile
from travelcore.database.project_store import ProjectStore
from travelcore.exceptions import ProjectError
from travelcore.gps.fitnesstracks import ACTIVITY_TRACKS_DIRNAME
from travelcore.media.indexer import FileIndexer
from travelcore.media.purge import plan_source_sync
from travelcore.project_settings import load_project_settings, save_project_settings
from traveljournal.services.workspace import Workspace


def _session_json() -> dict[str, object]:
    return {
        "identifier": "abc-1",
        "name": "Kitesurfen",
        "startTime": "2026-08-29T13:45:15",
        "stopTime": "2026-08-29T14:23:27",
        "timezoneOffsetMinutes": 120,
        "distanceMeters": 11572.9,
        "durationMillis": 2292000,
        "sport": {"id": "100"},
        "exercises": [
            {
                "startTime": "2026-08-29T13:45:15",
                "timezoneOffsetMinutes": 120,
                "sport": {"id": "100"},
                "routes": {
                    "route": {
                        "wayPoints": [
                            {
                                "latitude": 47.67,
                                "longitude": 11.56,
                                "altitude": 600,
                                "elapsedMillis": 0,
                            },
                            {
                                "latitude": 47.68,
                                "longitude": 11.57,
                                "altitude": 610,
                                "elapsedMillis": 1000,
                            },
                        ],
                        "startTime": "2026-08-29T13:45:15",
                    }
                },
            }
        ],
    }


def _seed_fitness(tmp_path: Path) -> Path:
    store_dir = tmp_path / "fitness"
    store = init_store(store_dir)
    source = tmp_path / "polar"
    source.mkdir()
    (source / "training-session_2026-08-29.json").write_text(
        json.dumps(_session_json()), encoding="utf-8"
    )
    result = import_path(store, source)
    assert result.tracks >= 1
    return store_dir


def _open_workspace(tmp_path: Path) -> tuple[Workspace, Path]:
    opened = ProjectStore().create(tmp_path / "reise", "Fitness")
    media = tmp_path / "import"
    media.mkdir()
    settings = load_project_settings(opened.directory)
    settings.paths.source_root = str(media)
    save_project_settings(opened.directory, settings)
    workspace = Workspace()
    workspace.current = opened
    return workspace, media


def test_workspace_import_fitness_tracks_and_rescan(tmp_path: Path) -> None:
    workspace, media = _open_workspace(tmp_path)
    workspace.save_trip_span(date(2026, 8, 1), date(2026, 9, 1))
    store_dir = _seed_fitness(tmp_path)
    count = workspace.import_fitness_tracks(store_dir)
    assert count == 1
    files = list((media / ACTIVITY_TRACKS_DIRNAME).glob("*.gpx"))
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
        kept = session.get(SourceFile, source_id)
        assert kept is not None
    assert workspace.import_fitness_tracks(store_dir) == 1
    with opened.session_factory() as session:
        assert len(list(session.scalars(select(SourceFile)))) == 1


def test_workspace_import_fitness_requires_trip_span(tmp_path: Path) -> None:
    workspace, _media = _open_workspace(tmp_path)
    store_dir = _seed_fitness(tmp_path)
    with pytest.raises(ProjectError, match="Zeitraum von"):
        workspace.import_fitness_tracks(store_dir)


def test_workspace_import_fitness_uses_date_override(tmp_path: Path) -> None:
    workspace, media = _open_workspace(tmp_path)
    workspace.save_trip_span(date(2026, 1, 1), date(2026, 1, 31))
    store_dir = _seed_fitness(tmp_path)
    assert workspace.import_fitness_tracks(store_dir) == 0
    count = workspace.import_fitness_tracks(
        store_dir,
        date_from=date(2026, 8, 1),
        date_to=date(2026, 9, 1),
    )
    assert count == 1
    assert list((media / ACTIVITY_TRACKS_DIRNAME).glob("*.gpx"))


def test_workspace_import_fitness_requires_store(tmp_path: Path) -> None:
    workspace, _media = _open_workspace(tmp_path)
    workspace.save_trip_span(date(2026, 8, 1), date(2026, 9, 1))
    with pytest.raises(ProjectError, match="Activity-Datenbank"):
        workspace.import_fitness_tracks(tmp_path / "missing-store")


def test_workspace_import_fitness_reports_progress(tmp_path: Path) -> None:
    workspace, _media = _open_workspace(tmp_path)
    workspace.save_trip_span(date(2026, 8, 1), date(2026, 9, 1))
    store_dir = _seed_fitness(tmp_path)
    seen: list[tuple[int, int, str]] = []
    count = workspace.import_fitness_tracks(store_dir, progress=lambda c, t, m: seen.append((c, t, m)))
    assert count == 1
    assert seen
    assert any("Schreibe" in message or "Indexiere" in message for _, _, message in seen)


def test_workspace_reload_drops_stale_activity_tracks(tmp_path: Path) -> None:
    workspace, media = _open_workspace(tmp_path)
    workspace.save_trip_span(date(2026, 8, 1), date(2026, 9, 1))
    store_dir = _seed_fitness(tmp_path)
    assert workspace.import_activity_tracks(
        store_dir, include_activities=True, include_flights=False
    ) == 1
    files = list((media / ACTIVITY_TRACKS_DIRNAME).glob("*.gpx"))
    assert len(files) == 1
    gpx = files[0]
    opened = workspace.current
    assert opened is not None
    with opened.session_factory() as session:
        assert len(list(session.scalars(select(SourceFile)))) == 1
    assert (
        workspace.import_activity_tracks(
            store_dir,
            include_activities=True,
            include_flights=False,
            date_from=date(2026, 1, 1),
            date_to=date(2026, 1, 31),
        )
        == 0
    )
    assert not gpx.exists()
    with opened.session_factory() as session:
        assert list(session.scalars(select(SourceFile))) == []


def test_workspace_reload_activities_leaves_flights(tmp_path: Path) -> None:
    from travelcore.gps.igctracks import IGC_TRACKS_DIRNAME

    workspace, media = _open_workspace(tmp_path)
    workspace.save_trip_span(date(2026, 8, 1), date(2026, 9, 1))
    store_dir = _seed_fitness(tmp_path)
    flights = tmp_path / "flights"
    flights.mkdir()
    (flights / "flug.igc").write_bytes(
        (
            "AXXX FITNESSCORE\n"
            "HFDTEDATE:290826\n"
            "HFPLTPILOTINCHARGE:Testpilot\n"
            "B1231504629881N01121180EA0123401234\n"
            "B1232104630000N01121600EA0124001240\n"
        ).encode("ascii")
    )
    import_path(open_store(store_dir), flights)
    assert workspace.import_activity_tracks(store_dir) == 2
    assert list((media / ACTIVITY_TRACKS_DIRNAME).glob("*.gpx"))
    assert list((media / IGC_TRACKS_DIRNAME).glob("*.igc"))
    assert (
        workspace.import_activity_tracks(
            store_dir,
            include_activities=True,
            include_flights=False,
            date_from=date(2026, 1, 1),
            date_to=date(2026, 1, 31),
        )
        == 0
    )
    assert not list((media / ACTIVITY_TRACKS_DIRNAME).glob("*.gpx"))
    assert list((media / IGC_TRACKS_DIRNAME).glob("*.igc"))
    opened = workspace.current
    assert opened is not None
    with opened.session_factory() as session:
        rows = list(session.scalars(select(SourceFile)))
        assert len(rows) == 1
        assert rows[0].filename.endswith(".igc") or rows[0].extension == ".igc"


def test_workspace_reload_deletes_orphan_files_on_disk(tmp_path: Path) -> None:
    from travelcore.media.indexer import count_by_kind

    workspace, media = _open_workspace(tmp_path)
    workspace.save_trip_span(date(2026, 8, 1), date(2026, 9, 1))
    store_dir = _seed_fitness(tmp_path)
    assert workspace.import_activity_tracks(
        store_dir, include_activities=True, include_flights=False
    ) == 1
    dest = media / ACTIVITY_TRACKS_DIRNAME
    orphan = dest / "orphan.gpx"
    orphan.write_text("<gpx></gpx>", encoding="utf-8")
    legacy = media / ".FitnessTracks"
    legacy.mkdir()
    leftover = legacy / "old.gpx"
    leftover.write_text("<gpx></gpx>", encoding="utf-8")
    opened = workspace.current
    assert opened is not None
    with opened.session_factory() as session:
        before = count_by_kind(session, opened.project_id)["act"]
    assert workspace.import_activity_tracks(
        store_dir, include_activities=True, include_flights=False
    ) == 1
    assert not orphan.exists()
    assert not leftover.exists()
    assert list(dest.glob("*.gpx"))
    with opened.session_factory() as session:
        assert count_by_kind(session, opened.project_id)["act"] == before == 1
