from pathlib import Path

from jpeg_fixtures import jpeg_exif_app1, write_jpeg_with_exif

from travelcore.metadata.composite import DefaultMetadataProvider
from travelcore.metadata.exif_blob import parse_embedded_exif
from travelcore.metadata.heic import read_heic_container_metadata, read_heic_quicktime_location


def _synthetic_iphone_heic(path: Path) -> Path:
    """Bytes that resemble an iPhone location atom. Not a real HEIC image."""

    payload = (
        b"ftypheic"
        + b"\x00" * 32
        + b"com.apple.quicktime.location.ISO6709"
        + b"\x00\x00\x00\x01"
        + b"+46.498011+011.353000+0262.000/"
        + b"\x00" * 16
    )
    path.write_bytes(payload)
    return path


def _heic_with_embedded_jpeg_exif(path: Path) -> Path:
    jpeg_path = path.with_suffix(".jpg")
    write_jpeg_with_exif(
        jpeg_path,
        datetime_original="2025:05:15 15:10:00",
        make="Apple",
        model="iPhone 15 Pro",
        latitude=(46.0, 30.0, 0.0),
        longitude=(11.0, 21.0, 0.0),
        altitude=262.0,
    )
    path.write_bytes(b"ftypheic" + b"\x00" * 64 + jpeg_exif_app1(jpeg_path) + b"\x00" * 16)
    return path


def _utf8_data_box(text: bytes) -> bytes:
    inner = b"data\x00\x00\x00\x01\x00\x00\x00\x00" + text
    return (len(inner) + 4).to_bytes(4, "big") + inner


def _heic_with_apple_data_boxes(path: Path) -> Path:
    path.write_bytes(
        b"ftypheic"
        + _utf8_data_box(b"Apple")
        + _utf8_data_box(b"iPhone 15 Pro")
        + b"com.apple.quicktime.location.ISO6709"
        + b"+46.498011+011.353000/"
    )
    return path


def test_heic_iso6709_is_read_without_exiftool(tmp_path: Path) -> None:
    path = _synthetic_iphone_heic(tmp_path / "IMG_0001.HEIC")
    embedded = read_heic_quicktime_location(path)
    assert embedded is not None
    assert embedded.position is not None
    assert abs(embedded.position.latitude - 46.498011) < 1e-6
    assert abs(embedded.position.longitude - 11.353) < 1e-6
    assert embedded.position.source == "quicktime"


def test_default_provider_fills_heic_gps_without_exiftool(tmp_path: Path) -> None:
    path = _synthetic_iphone_heic(tmp_path / "photo.heic")
    provider = DefaultMetadataProvider(exiftool=None)
    metadata = provider.read(path)
    assert metadata.position is not None
    assert metadata.position.source == "quicktime"
    assert abs(metadata.position.latitude - 46.498011) < 1e-6


def test_embedded_exif_tiff_from_jpeg_app1(tmp_path: Path) -> None:
    jpeg = write_jpeg_with_exif(
        tmp_path / "bozen.jpg",
        datetime_original="2025:05:15 15:10:00",
        make="Apple",
        model="iPhone 15 Pro",
        latitude=(46.0, 30.0, 0.0),
        longitude=(11.0, 21.0, 0.0),
        heading=80.0,
        heading_ref="T",
        focal_length_35mm=26,
    )
    metadata = parse_embedded_exif(jpeg.read_bytes())
    assert metadata is not None
    assert metadata.camera == "Apple iPhone 15 Pro"
    assert metadata.position is not None
    assert abs(metadata.position.latitude - 46.5) < 1e-6
    assert metadata.captured is not None
    assert metadata.captured.raw_value == "2025:05:15 15:10:00"
    assert metadata.heading_degrees == 80.0
    assert metadata.focal_length_35mm == 26.0


def test_heic_embedded_exif_fills_gps_and_camera(tmp_path: Path) -> None:
    path = _heic_with_embedded_jpeg_exif(tmp_path / "IMG_0002.HEIC")
    metadata = read_heic_container_metadata(path)
    assert metadata is not None
    assert metadata.camera == "Apple iPhone 15 Pro"
    assert metadata.position is not None
    assert metadata.position.source == "exif"
    assert abs(metadata.position.latitude - 46.5) < 1e-6
    assert metadata.captured is not None
    assert metadata.captured.source == "exif_datetime_original"


def test_default_provider_fills_heic_camera_from_exif(tmp_path: Path) -> None:
    path = _heic_with_embedded_jpeg_exif(tmp_path / "IMG_0003.heic")
    metadata = DefaultMetadataProvider(exiftool=None).read(path)
    assert metadata.camera == "Apple iPhone 15 Pro"
    assert metadata.position is not None
    assert metadata.position.source == "exif"


def test_heic_quicktime_data_boxes_provide_camera(tmp_path: Path) -> None:
    path = _heic_with_apple_data_boxes(tmp_path / "IMG_0004.HEIC")
    metadata = read_heic_container_metadata(path)
    assert metadata is not None
    assert metadata.camera == "Apple iPhone 15 Pro"
    assert metadata.position is not None
    assert metadata.position.source == "quicktime"
