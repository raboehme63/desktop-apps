from datetime import UTC, datetime

from fitnesscore.parse.fit import FitRecordPoint, FitSession, points_for_session, semicircle_to_deg


def test_semicircle_to_deg_south_bavaria() -> None:
    lat = semicircle_to_deg(569809493)
    lon = semicircle_to_deg(137779011)
    assert 47.7 < lat < 47.9
    assert 11.5 < lon < 11.6


def test_points_for_session_cuts_on_timestamps() -> None:
    t0 = datetime(2026, 8, 29, 7, 30, tzinfo=UTC)
    t1 = datetime(2026, 8, 29, 11, 44, tzinfo=UTC)
    t2 = datetime(2026, 8, 29, 11, 50, tzinfo=UTC)
    points = [
        FitRecordPoint(t0, 47.0, 11.0, 800.0),
        FitRecordPoint(t1, 47.1, 11.1, 810.0),
        FitRecordPoint(t2, 47.2, 11.2, 20.0),
    ]
    first = FitSession(
        sport="cycling",
        sub_sport="mountain",
        start_time=t0,
        end_time=t1,
        elapsed_s=None,
        timer_s=None,
        distance_m=None,
        ascent_m=None,
        descent_m=None,
        calories=None,
        hr_avg=None,
        hr_max=None,
    )
    window = points_for_session(points, first)
    assert [point.recorded_at for point in window] == [t0, t1]
