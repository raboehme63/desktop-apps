from pathlib import Path

from jpeg_fixtures import write_jpeg_with_exif, write_plain_jpeg

from travelcore.metadata.pillow_provider import PillowMetadataProvider


def test_datetime_original_preferred_over_create_date(tmp_path: Path) -> None:
    path = write_jpeg_with_exif(
        tmp_path / "shot.jpg",
        datetime_original="2025:05:15 08:20:00",
        create_date="2025:05:15 09:00:00",
    )
    metadata = PillowMetadataProvider().read(path)
    assert metadata.captured is not None
    assert metadata.captured.source == "exif_datetime_original"
    assert metadata.captured.raw_value == "2025:05:15 08:20:00"
    assert metadata.captured.normalized is not None
    assert metadata.captured.normalized.year == 2025
    assert metadata.captured.normalized.hour == 8
    assert metadata.captured.timezone_unknown is True


def test_offset_marks_timezone_known(tmp_path: Path) -> None:
    path = write_jpeg_with_exif(
        tmp_path / "tz.jpg",
        datetime_original="2025:05:15 08:20:00",
        offset_original="+02:00",
    )
    captured = PillowMetadataProvider().read(path).captured
    assert captured is not None
    assert captured.timezone_unknown is False
    assert captured.timezone_name == "+02:00"
    assert captured.normalized is not None
    assert captured.normalized.tzinfo is not None


def test_gps_and_camera_from_exif(tmp_path: Path) -> None:
    path = write_jpeg_with_exif(
        tmp_path / "bozen.jpg",
        datetime_original="2025:05:15 15:10:00",
        make="Canon",
        model="EOS R6",
        latitude=(46.0, 29.0, 53.0),
        longitude=(11.0, 21.0, 12.0),
        altitude=262.0,
        size=(64, 48),
    )
    metadata = PillowMetadataProvider().read(path)
    assert metadata.camera == "Canon EOS R6"
    assert metadata.width == 64
    assert metadata.height == 48
    assert metadata.orientation == 1
    assert metadata.position is not None
    assert metadata.position.source == "exif"
    assert abs(metadata.position.latitude - (46 + 29 / 60 + 53 / 3600)) < 1e-6
    assert abs(metadata.position.longitude - (11 + 21 / 60 + 12 / 3600)) < 1e-6
    assert metadata.position.altitude == 262.0
    assert metadata.heading_degrees is None
    assert metadata.focal_length_35mm is None


def test_heading_and_35mm_from_exif(tmp_path: Path) -> None:
    path = write_jpeg_with_exif(
        tmp_path / "view.jpg",
        datetime_original="2025:05:15 15:10:00",
        latitude=(46.0, 29.0, 53.0),
        longitude=(11.0, 21.0, 12.0),
        heading=123.5,
        heading_ref="T",
        focal_length=8.0,
        focal_length_35mm=24,
    )
    metadata = PillowMetadataProvider().read(path)
    assert metadata.heading_degrees is not None
    assert abs(metadata.heading_degrees - 123.5) < 1e-6
    assert metadata.heading_ref == "T"
    assert metadata.heading_source == "gps_img_direction"
    assert metadata.focal_length == 8.0
    assert metadata.focal_length_35mm == 24.0


def test_plain_jpeg_has_no_capture_time(tmp_path: Path) -> None:
    path = write_plain_jpeg(tmp_path / "plain.jpg")
    metadata = PillowMetadataProvider().read(path)
    assert metadata.captured is None
    assert metadata.position is None
    assert metadata.width == 16
