from datetime import UTC, date, datetime
from pathlib import Path
from zlib import crc32

from travelcore.export.stats import trip_summary_counts, trip_summary_metrics
from travelcore.media.gallery import SORT_REJECTED
from travelcore.timeline.types import (
    TimelineDay,
    TimelineEntry,
    TimelinePhoto,
    TimelineSection,
    TimelineSnapshot,
)


def _photo(
    *,
    filename: str,
    kind: str = "photo",
    status: str | None = None,
    pilot: str | None = None,
    source_file_id: int | None = None,
) -> TimelinePhoto:
    identity = source_file_id if source_file_id is not None else (crc32(filename.encode()) & 0x7FFFFFFF) or 1
    return TimelinePhoto(
        source_file_id=identity,
        filename=filename,
        path=filename,
        thumbnail_path=Path(filename),
        captured_at=None,
        used_in_journal=False,
        is_cover=False,
        is_favorite=False,
        gps_latitude=None,
        gps_longitude=None,
        file_kind=kind,
        sort_status=status,
        pilot=pilot,
    )


def _snapshot(*, youtube: tuple[str, ...] = (), items: tuple[TimelinePhoto, ...] = ()) -> TimelineSnapshot:
    start = datetime(2023, 2, 21, tzinfo=UTC)
    end = datetime(2023, 3, 9, tzinfo=UTC)
    section = TimelineSection(
        id=1,
        kind="day",
        mode=None,
        title="Tag",
        notes=None,
        started_at=start,
        ended_at=end,
        location_name=None,
        location_from=None,
        location_to=None,
        origin="manual",
        youtube_urls=youtube,
        items=items,
    )
    return TimelineSnapshot(
        trip_id=1,
        title="Reise",
        origin="manual",
        countries=("IT",),
        entries=(TimelineEntry(started_at=start, section=section),),
    )


def test_trip_summary_counts_days_sections_media_and_flights() -> None:
    snapshot = _snapshot(
        youtube=("https://youtu.be/aaaaaaaaaaa", "https://youtu.be/aaaaaaaaaaa"),
        items=(
            _photo(filename="a.jpg"),
            _photo(filename="b.jpg", status=SORT_REJECTED),
            _photo(filename="flug.igc", kind="gps", pilot="Ralf"),
            _photo(filename="route.gpx", kind="gps"),
        ),
    )
    counts = trip_summary_counts(snapshot)
    assert counts["duration_days"] == 17
    assert counts["section_count"] == 1
    assert counts["photo_count"] == 1
    assert counts["youtube_count"] == 1
    assert counts["flight_count"] == 1
    assert counts["pilot_count"] == 1
    metrics = trip_summary_metrics(snapshot)
    assert [label for _value, label in metrics] == [
        "Tage",
        "Reiseabschnitte",
        "Fotos",
        "YouTube-Videos",
        "Gleitschirmflüge",
    ]


def test_trip_summary_omits_zero_metrics() -> None:
    snapshot = _snapshot(items=(_photo(filename="a.jpg"),))
    metrics = trip_summary_metrics(snapshot)
    assert [label for _value, label in metrics] == ["Tage", "Reiseabschnitte", "Fotos"]
    assert trip_summary_metrics(None) == ()


def test_trip_summary_flight_label_includes_pilot_count() -> None:
    one_pilot = _snapshot(
        items=(
            _photo(filename="a.igc", kind="gps", pilot="Ralf"),
            _photo(filename="b.igc", kind="gps", pilot="Ralf"),
        )
    )
    two_pilots = _snapshot(
        items=(
            _photo(filename="a.igc", kind="gps", pilot="Ralf"),
            _photo(filename="b.igc", kind="gps", pilot="Anna"),
        )
    )
    assert trip_summary_counts(one_pilot)["pilot_count"] == 1
    assert [label for _value, label in trip_summary_metrics(one_pilot)] == [
        "Tage",
        "Reiseabschnitte",
        "Gleitschirmflüge",
    ]
    assert trip_summary_counts(two_pilots)["pilot_count"] == 2
    assert [label for _value, label in trip_summary_metrics(two_pilots)][-1] == "Gleitschirmflüge (2 Piloten)"
    assert [value for value, _label in trip_summary_metrics(two_pilots)][-1] == "2"


def test_trip_summary_counts_igc_on_days_even_without_section_members() -> None:
    flight = _photo(filename="2024-11-16-XTR-D9C41AF9717A-01.IGC", kind="gps", pilot="Ralf Boehme")
    day = TimelineDay(
        id=1,
        day_index=0,
        date=date(2024, 11, 16),
        title="Tag",
        notes=None,
        origin="auto",
        photos=(flight,),
    )
    snapshot = TimelineSnapshot(
        trip_id=1,
        title="Reise",
        origin="auto",
        days=(day,),
    )
    assert trip_summary_counts(snapshot)["flight_count"] == 1
    assert [label for _value, label in trip_summary_metrics(snapshot)] == ["Gleitschirmflüge"]


def test_trip_summary_prefers_snapshot_span_over_sections() -> None:
    snapshot = TimelineSnapshot(
        trip_id=1,
        title="Reise",
        origin="manual",
        countries=("IT",),
        start_date=date(2023, 2, 21),
        end_date=date(2023, 2, 22),
        entries=_snapshot().entries,
    )
    assert trip_summary_counts(snapshot)["duration_days"] == 2
