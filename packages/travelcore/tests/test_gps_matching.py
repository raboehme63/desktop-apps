from datetime import UTC, datetime, timedelta, timezone

from travelcore.gps.match import SOURCE_INTERPOLATED, SOURCE_NEAREST, match_position, media_time_utc
from travelcore.gps.types import TrackPoint


def _point(lat: float, lon: float, seconds: int, altitude: float | None = 200.0) -> TrackPoint:
    return TrackPoint(
        latitude=lat,
        longitude=lon,
        altitude=altitude,
        recorded_at=datetime(2025, 5, 15, 13, 31, 50, tzinfo=UTC) + timedelta(seconds=seconds),
        track_id="trk-0",
        segment_id=0,
        sequence_index=seconds,
    )


def test_interpolate_between_surrounding_points() -> None:
    before = _point(46.0, 11.0, 0, 260.0)
    after = _point(46.2, 11.2, 20, 280.0)
    moment = datetime(2025, 5, 15, 13, 32, 0, tzinfo=UTC)
    fix = match_position(moment, [before, after], max_delta_seconds=120)
    assert fix is not None
    assert fix.source == SOURCE_INTERPOLATED
    assert fix.from_exif is False
    assert abs(fix.latitude - 46.1) < 1e-9
    assert abs(fix.longitude - 11.1) < 1e-9
    assert fix.altitude is not None
    assert abs(fix.altitude - 270.0) < 1e-9
    assert fix.time_delta_seconds == 10.0
    assert 0.2 <= fix.confidence < 1.0


def test_nearest_when_only_one_side_within_window() -> None:
    point = _point(46.5, 11.3, 0)
    moment = datetime(2025, 5, 15, 13, 32, 50, tzinfo=UTC)
    fix = match_position(moment, [point], max_delta_seconds=120)
    assert fix is not None
    assert fix.source == SOURCE_NEAREST
    assert abs(fix.latitude - 46.5) < 1e-9
    assert fix.time_delta_seconds == 60.0


def test_match_position_accepts_pre_sorted_points() -> None:
    before = _point(46.0, 11.0, 0)
    after = _point(46.2, 11.2, 20)
    moment = datetime(2025, 5, 15, 13, 32, 0, tzinfo=UTC)
    unsorted = match_position(moment, [after, before], max_delta_seconds=120)
    sorted_fix = match_position(
        moment,
        [before, after],
        max_delta_seconds=120,
        points_sorted=True,
    )
    assert unsorted is not None
    assert sorted_fix is not None
    assert abs(unsorted.latitude - sorted_fix.latitude) < 1e-9


def test_no_match_outside_max_delta() -> None:
    point = _point(46.5, 11.3, 0)
    moment = datetime(2025, 5, 15, 13, 40, 0, tzinfo=UTC)
    assert match_position(moment, [point], max_delta_seconds=120) is None


def test_media_time_uses_project_offset_for_naive_capture() -> None:
    naive = datetime(2025, 5, 15, 15, 32, 0)
    converted = media_time_utc(naive, timezone_unknown=True, default_timezone="+02:00")
    assert converted == datetime(2025, 5, 15, 13, 32, 0, tzinfo=UTC)


def test_aware_capture_is_converted_to_utc() -> None:
    local = datetime(2025, 5, 15, 15, 32, 0, tzinfo=timezone(timedelta(hours=2)))
    converted = media_time_utc(local, timezone_unknown=False)
    assert converted == datetime(2025, 5, 15, 13, 32, 0, tzinfo=UTC)
