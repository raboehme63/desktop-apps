from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select

from fitnesscore.cli import main
from fitnesscore.database.models import Document, Source
from fitnesscore.ingest import import_path
from fitnesscore.query_gpx import export_gpx
from fitnesscore.store import init_store, open_store


def _session_json(
    *,
    name: str = "Kitesurfen",
    start: str = "2026-08-29T13:45:15",
    offset: int = 120,
    sport_id: str = "100",
    waypoints: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    points = waypoints or [
        {"latitude": 47.67, "longitude": 11.56, "altitude": 600, "elapsedMillis": 0},
        {"latitude": 47.68, "longitude": 11.57, "altitude": 610, "elapsedMillis": 1000},
    ]
    return {
        "identifier": "abc-1",
        "name": name,
        "startTime": start,
        "stopTime": "2026-08-29T14:23:27",
        "timezoneOffsetMinutes": offset,
        "distanceMeters": 11572.9,
        "durationMillis": 2292000,
        "sport": {"id": sport_id},
        "exercises": [
            {
                "startTime": start,
                "timezoneOffsetMinutes": offset,
                "sport": {"id": sport_id},
                "routes": {"route": {"wayPoints": points, "startTime": start}},
            }
        ],
    }


def test_import_all_kinds_but_gpx_only_from_sessions(tmp_path: Path) -> None:
    store = init_store(tmp_path / "fitness")
    source = tmp_path / "in"
    source.mkdir()
    (source / "training-session_2026-08-29.json").write_text(json.dumps(_session_json()), encoding="utf-8")
    (source / "activity-2026-08-29-x.json").write_text(
        json.dumps({"exportVersion": "2.6", "date": "2026-08-29", "samples": [1, 2, 3]}),
        encoding="utf-8",
    )
    (source / "247ohr_2026_08-x.json").write_text(
        json.dumps({"deviceDays": [{"day": "2026-08-01"}]}),
        encoding="utf-8",
    )
    (source / "planned-route-1.json").write_text(
        json.dumps(
            {
                "id": 9,
                "name": "Runde",
                "distance": 1000,
                "waypoints": [
                    {"location": {"latitude": 46.0, "longitude": 11.0, "altitude": 100}},
                    {"location": {"latitude": 46.1, "longitude": 11.1, "altitude": 120}},
                ],
            }
        ),
        encoding="utf-8",
    )
    (source / "ignore.gpx").write_text("<gpx></gpx>", encoding="utf-8")

    result = import_path(store, source)
    assert result.imported == 4
    assert result.scanned == 4
    assert result.tracks == 2
    assert result.by_kind["training_session"] == 1
    assert result.by_kind["activity_day"] == 1
    assert result.by_kind["ohr_247"] == 1
    assert result.by_kind["planned_route"] == 1

    with store.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Source)) == 4
        kinds = {row[0] for row in session.execute(select(Document.kind))}
        assert kinds == {"training_session", "activity_day", "ohr_247", "planned_route"}
        payloads = [row[0] for row in session.execute(select(Source.payload_zlib))]
        assert all(payloads)

    out = tmp_path / "gpx"
    hits = export_gpx(
        store,
        sports=("kitesurfing",),
        date_from=datetime(2026, 8, 1).date(),
        date_to=datetime(2026, 8, 31).date(),
        dest=out,
    )
    assert len(hits) == 1
    assert hits[0].sport_slug == "kitesurfing"
    text = hits[0].path.read_text(encoding="utf-8")
    assert 'lat="47.67"' in text
    assert "<time>2026-08-29T11:45:15Z</time>" in text

    empty = export_gpx(
        store,
        sports=("hiking",),
        date_from=datetime(2026, 8, 1).date(),
        date_to=datetime(2026, 8, 31).date(),
        dest=tmp_path / "empty",
    )
    assert empty == []
    all_hits = export_gpx(
        store,
        date_from=datetime(2026, 8, 1).date(),
        date_to=datetime(2026, 8, 31).date(),
        dest=tmp_path / "all",
    )
    assert len(all_hits) == 1


def test_duplicate_hash_is_skipped(tmp_path: Path) -> None:
    store = init_store(tmp_path / "fitness")
    path = tmp_path / "training-session_one.json"
    path.write_text(json.dumps(_session_json()), encoding="utf-8")
    first = import_path(store, path)
    second = import_path(store, path)
    assert first.imported == 1
    assert second.skipped == 1


def test_cli_init_import_export(tmp_path: Path) -> None:
    db = tmp_path / "store"
    source = tmp_path / "training-session_kite.json"
    source.write_text(json.dumps(_session_json()), encoding="utf-8")
    out = tmp_path / "out"
    assert main(["--db", str(db), "init"]) == 0
    assert (db / "activity.sqlite").is_file()
    assert main(["--db", str(db), "import", "-f", str(source)]) == 0
    assert (
        main(
            [
                "--db",
                str(db),
                "export-gpx",
                "--sports",
                "kitesurfing",
                "--from",
                "2026-08-01",
                "--to",
                "2026-09-02",
                "--out",
                str(out),
            ]
        )
        == 0
    )
    files = list(out.glob("*.gpx"))
    assert len(files) == 1
    out_all = tmp_path / "out-all"
    assert (
        main(
            [
                "--db",
                str(db),
                "export-gpx",
                "--from",
                "2026-08-01",
                "--to",
                "2026-09-02",
                "--out",
                str(out_all),
            ]
        )
        == 0
    )
    assert len(list(out_all.glob("*.gpx"))) == 1


def test_cli_import_recursive_flag(tmp_path: Path) -> None:
    db = tmp_path / "store"
    nested = tmp_path / "tracks" / "sub"
    nested.mkdir(parents=True)
    (nested / "training-session_kite.json").write_text(json.dumps(_session_json()), encoding="utf-8")
    assert main(["--db", str(db), "init"]) == 0
    assert main(["--db", str(db), "import", "-d", str(tmp_path / "tracks")]) == 0
    store = open_store(db)
    with store.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Document)) == 0
    assert main(["--db", str(db), "import", "-d", str(tmp_path / "tracks"), "--r"]) == 0
    with store.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Document)) == 1
    assert main(["--db", str(db), "import", "-d", str(tmp_path / "tracks"), "--recursive"]) == 0
    with store.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Document)) == 1


def test_training_start_is_converted_from_offset() -> None:
    from fitnesscore.parse.json_doc import documents_from_json

    docs = documents_from_json(
        _session_json(),
        kind="training_session",
        filename="training-session.json",
    )
    assert docs[0].started_at == datetime(2026, 8, 29, 11, 45, 15, tzinfo=UTC)
    assert docs[0].sport_slug == "kitesurfing"
    assert len(docs[0].tracks) == 1


def test_resolve_db_path_prefers_activity_and_falls_back(tmp_path: Path) -> None:
    from fitnesscore.store import resolve_db_path

    folder = tmp_path / "store"
    folder.mkdir()
    assert resolve_db_path(folder).name == "activity.sqlite"
    assert resolve_db_path(folder, create=True).name == "activity.sqlite"
    (folder / "fitness.sqlite").write_bytes(b"")
    assert resolve_db_path(folder).name == "fitness.sqlite"
    (folder / "activity.sqlite").write_bytes(b"")
    assert resolve_db_path(folder).name == "activity.sqlite"
    named = folder / "other.sqlite"
    assert resolve_db_path(named) == named
