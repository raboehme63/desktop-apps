from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from json_routes_to_gpx import (  # noqa: E402
    convert_file,
    json_files_in,
    main,
    tracks_from_json,
    tracks_to_gpx,
    waypoints_from_routes,
)


def _polar_session(
    *,
    waypoints: list[dict[str, object]] | None,
    transition: list[dict[str, object]] | None = None,
    extra_exercise: dict[str, object] | None = None,
) -> dict[str, object]:
    route: dict[str, object] = {"startTime": "2019-01-15T17:06:08.000"}
    if waypoints is not None:
        route["wayPoints"] = waypoints
    routes: dict[str, object] = {"route": route}
    if transition is not None:
        routes["transitionRoute"] = {"wayPoints": transition, "startTime": "2019-01-15T17:06:08.000"}
    exercise: dict[str, object] = {
        "startTime": "2019-01-15T17:06:08",
        "timezoneOffsetMinutes": 60,
        "routes": routes,
    }
    exercises = [exercise]
    if extra_exercise is not None:
        exercises.append(extra_exercise)
    return {
        "name": "Freest.-Skilangl.",
        "startTime": "2019-01-15T17:06:08",
        "timezoneOffsetMinutes": 60,
        "exercises": exercises,
    }


def test_waypoints_from_routes_uses_route_not_transition() -> None:
    routes = {
        "route": {
            "wayPoints": [
                {"latitude": 47.1, "longitude": 11.1, "altitude": 600, "elapsedMillis": 1000},
            ]
        },
        "transitionRoute": {
            "wayPoints": [
                {"latitude": 46.0, "longitude": 10.0, "altitude": 1, "elapsedMillis": 0},
                {"latitude": 46.1, "longitude": 10.1, "altitude": 2, "elapsedMillis": 1000},
            ]
        },
    }
    points = waypoints_from_routes(routes)
    assert len(points) == 1
    assert points[0].latitude == 47.1


def test_empty_routes_yield_no_tracks() -> None:
    assert tracks_from_json({"name": "ohne", "routes": {}}) == ()
    assert tracks_from_json({"name": "ohne", "exercises": [{"routes": {"route": {"wayPoints": []}}}]}) == ()
    assert tracks_from_json({"name": "ohne"}) == ()


def test_tracks_from_polar_json_sets_utc_time_and_elevation() -> None:
    data = _polar_session(
        waypoints=[
            {"latitude": 47.679275, "longitude": 11.56078333, "altitude": 605.0, "elapsedMillis": 38000},
            {"latitude": 47.67926667, "longitude": 11.56074667, "altitude": 603.0, "elapsedMillis": 39000},
        ]
    )
    tracks = tracks_from_json(data)
    assert len(tracks) == 1
    assert tracks[0].name == "Freest.-Skilangl."
    assert len(tracks[0].points) == 2
    first = tracks[0].points[0]
    assert first.elevation == 605.0
    assert first.recorded_at == datetime(2019, 1, 15, 16, 6, 46, tzinfo=UTC)


def test_convert_file_writes_sibling_gpx(tmp_path: Path) -> None:
    source = tmp_path / "training-session.json"
    source.write_text(
        json.dumps(
            _polar_session(
                waypoints=[
                    {"latitude": 47.5, "longitude": 11.5, "altitude": 610, "elapsedMillis": 0},
                    {"latitude": 47.51, "longitude": 11.51, "altitude": 612, "elapsedMillis": 1000},
                ]
            )
        ),
        encoding="utf-8",
    )
    written = convert_file(source)
    assert written == tmp_path / "training-session.gpx"
    text = written.read_text(encoding="utf-8")
    assert 'creator="json_routes_to_gpx"' in text
    assert 'lat="47.5"' in text
    assert "<ele>610</ele>" in text
    assert "<time>2019-01-15T16:06:08Z</time>" in text
    from travelcore.gps.parse import parse_gpx

    parsed = parse_gpx(written)
    assert len(parsed) == 1
    assert len(parsed[0].points) == 2


def test_convert_file_skips_without_routes(tmp_path: Path) -> None:
    source = tmp_path / "leer.json"
    source.write_text(json.dumps({"name": "nix"}), encoding="utf-8")
    assert convert_file(source) is None
    assert not (tmp_path / "leer.gpx").exists()


def test_directory_mode_prints_dots_and_counts(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    nested = tmp_path / "sub"
    nested.mkdir()
    (tmp_path / "a.json").write_text(
        json.dumps(
            _polar_session(
                waypoints=[{"latitude": 46.0, "longitude": 11.0, "altitude": 100, "elapsedMillis": 0}]
            )
        ),
        encoding="utf-8",
    )
    (tmp_path / "b.json").write_text(json.dumps({"name": "ohne"}), encoding="utf-8")
    (nested / "c.json").write_text(
        json.dumps(
            _polar_session(
                waypoints=[{"latitude": 47.0, "longitude": 12.0, "altitude": 200, "elapsedMillis": 0}]
            )
        ),
        encoding="utf-8",
    )
    assert json_files_in(tmp_path, recursive=False) == [tmp_path / "a.json", tmp_path / "b.json"]
    code = main(["-d", str(tmp_path)])
    assert code == 0
    out = capsys.readouterr().out
    assert out.startswith("..")
    assert "JSON 2, GPX 1" in out
    assert (tmp_path / "a.gpx").is_file()
    assert not (tmp_path / "b.gpx").exists()
    assert not (nested / "c.gpx").exists()
    code = main(["-d", str(tmp_path), "-r"])
    assert code == 0
    out = capsys.readouterr().out
    assert "JSON 3, GPX 2" in out
    assert (nested / "c.gpx").is_file()


def test_file_mode_writes_path(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = tmp_path / "eine.json"
    source.write_text(
        json.dumps(
            _polar_session(
                waypoints=[{"latitude": 46.5, "longitude": 11.3, "altitude": 250, "elapsedMillis": 2000}]
            )
        ),
        encoding="utf-8",
    )
    assert main(["-f", str(source)]) == 0
    line = capsys.readouterr().out.strip()
    assert line.endswith("eine.gpx")
    assert Path(line).is_file()


def test_tracks_to_gpx_escapes_name() -> None:
    from json_routes_to_gpx import RoutePoint, RouteTrack

    xml = tracks_to_gpx(
        (
            RouteTrack(
                name="A & B",
                points=(RoutePoint(46.0, 11.0, 10.0, None),),
            ),
        )
    )
    assert "A &amp; B" in xml
