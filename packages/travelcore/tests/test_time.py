from datetime import UTC, datetime, timedelta, timezone

from travelcore.metadata.time import choose_captured_time, parse_exif_datetime, parse_offset, with_source


def test_datetime_original_beats_create_date() -> None:
    original = with_source(parse_exif_datetime("2025:05:15 08:20:00"), "exif_datetime_original")
    created = with_source(parse_exif_datetime("2025:05:15 09:00:00"), "exif_create_date")
    chosen = choose_captured_time(
        {
            "exif_datetime_original": original,
            "exif_create_date": created,
            "filesystem_mtime": with_source(parse_exif_datetime("2025:01:01 00:00:00"), "filesystem_mtime"),
        }
    )
    assert chosen is not None
    assert chosen.source == "exif_datetime_original"
    assert chosen.normalized == datetime(2025, 5, 15, 8, 20, 0)
    assert chosen.timezone_unknown is True
    assert chosen.timezone_name is None


def test_create_date_used_when_original_missing() -> None:
    created = with_source(parse_exif_datetime("2025:05:15 11:40:00"), "exif_create_date")
    chosen = choose_captured_time({"exif_create_date": created})
    assert chosen is not None
    assert chosen.source == "exif_create_date"


def test_missing_timezone_is_not_called_utc() -> None:
    captured = parse_exif_datetime("2025:05:15 08:20:00")
    assert captured is not None
    assert captured.normalized is not None
    assert captured.normalized.tzinfo is None
    assert captured.timezone_unknown is True
    assert captured.timezone_name is None


def test_offset_makes_timezone_known() -> None:
    captured = parse_exif_datetime("2025:05:15 08:20:00", offset="+02:00")
    assert captured is not None
    assert captured.timezone_unknown is False
    assert captured.timezone_name == "+02:00"
    assert captured.normalized == datetime(2025, 5, 15, 8, 20, 0, tzinfo=timezone(timedelta(hours=2)))


def test_embedded_z_is_utc() -> None:
    captured = parse_exif_datetime("2025-05-15T08:20:00Z")
    assert captured is not None
    assert captured.timezone_unknown is False
    assert captured.normalized == datetime(2025, 5, 15, 8, 20, 0, tzinfo=UTC)
    assert parse_offset("Z") is UTC


def test_invalid_value_returns_none() -> None:
    assert parse_exif_datetime("not-a-date") is None
    assert parse_exif_datetime("") is None
    assert parse_exif_datetime(None) is None
