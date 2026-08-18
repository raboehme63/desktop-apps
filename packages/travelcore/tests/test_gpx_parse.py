from datetime import UTC, datetime
from pathlib import Path

from gpx_fixtures import write_gpx

from travelcore.exceptions import GpsError
from travelcore.gps.ingest import summarize_parsed_tracks
from travelcore.gps.parse import parse_gpx


def test_parse_gpx_track_and_segment(tmp_path: Path) -> None:
    path = write_gpx(
        tmp_path / "route.gpx",
        [
            (46.498011, 11.353, 262.0, "2025-05-15T13:31:50Z"),
            (46.4982, 11.3534, 263.0, "2025-05-15T13:32:10Z"),
        ],
        extra_segment=[(46.5, 11.36, None, "2025-05-15T13:40:00Z")],
        name="Bozen",
    )
    tracks = parse_gpx(path)
    assert len(tracks) == 1
    assert tracks[0].name == "Bozen"
    assert len(tracks[0].points) == 3
    first = tracks[0].points[0]
    assert abs(first.latitude - 46.498011) < 1e-6
    assert first.altitude == 262.0
    assert first.recorded_at == datetime(2025, 5, 15, 13, 31, 50, tzinfo=UTC)
    assert first.segment_id == 0
    assert tracks[0].points[2].segment_id == 1


def test_summarize_mean_of_first_points_and_start_time(tmp_path: Path) -> None:
    path = write_gpx(
        tmp_path / "route.gpx",
        [
            (46.0, 11.0, 260.0, "2025-05-15T13:31:50Z"),
            (46.2, 11.2, 280.0, "2025-05-15T13:32:10Z"),
        ],
    )
    summary = summarize_parsed_tracks(parse_gpx(path))
    assert summary.latitude is not None
    assert summary.longitude is not None
    assert abs(summary.latitude - 46.1) < 1e-9
    assert abs(summary.longitude - 11.1) < 1e-9
    assert summary.altitude is not None
    assert abs(summary.altitude - 270.0) < 1e-9
    assert summary.started_at == datetime(2025, 5, 15, 13, 31, 50, tzinfo=UTC)


def test_summarize_uses_first_timed_point_even_if_later(tmp_path: Path) -> None:
    path = write_gpx(
        tmp_path / "route.gpx",
        [
            (46.0, 11.0, None, None),
            (46.2, 11.2, None, "2025-05-15T13:32:10Z"),
        ],
    )
    summary = summarize_parsed_tracks(parse_gpx(path))
    assert abs((summary.latitude or 0) - 46.1) < 1e-9
    assert summary.started_at == datetime(2025, 5, 15, 13, 32, 10, tzinfo=UTC)


def test_summarize_untimed_points_have_position_but_no_start(tmp_path: Path) -> None:
    path = write_gpx(
        tmp_path / "route.gpx",
        [
            (46.0, 11.0, 100.0, None),
            (46.2, 11.2, 200.0, None),
        ],
    )
    summary = summarize_parsed_tracks(parse_gpx(path))
    assert abs((summary.latitude or 0) - 46.1) < 1e-9
    assert summary.started_at is None


def test_summarize_empty_gpx_has_no_fake_coordinates(tmp_path: Path) -> None:
    path = tmp_path / "empty.gpx"
    path.write_text("<gpx></gpx>", encoding="utf-8")
    summary = summarize_parsed_tracks(parse_gpx(path))
    assert summary.latitude is None
    assert summary.longitude is None
    assert summary.started_at is None


def test_empty_gpx_is_not_an_error(tmp_path: Path) -> None:
    path = tmp_path / "empty.gpx"
    path.write_text("<gpx></gpx>", encoding="utf-8")
    assert parse_gpx(path) == ()


def test_corrupt_gpx_raises(tmp_path: Path) -> None:
    path = tmp_path / "broken.gpx"
    path.write_text("this is not xml", encoding="utf-8")
    try:
        parse_gpx(path)
    except GpsError as exc:
        assert "broken.gpx" in str(exc)
    else:
        raise AssertionError("expected GpsError")
