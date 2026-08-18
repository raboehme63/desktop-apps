from pathlib import Path
from typing import Any

from travelcore.metadata.exiftool_provider import (
    ExifToolMetadataProvider,
    metadata_from_exiftool_json,
)


class _FakeSession:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def execute_json(self, paths: list[str], *, timeout: float = 30.0) -> list[dict[str, Any]]:
        _ = timeout
        self.calls.append(list(paths))
        return [
            {
                "SourceFile": path,
                "Make": "Canon",
                "Model": "EOS R6",
                "ImageWidth": 64,
                "ImageHeight": 48,
            }
            for path in paths
        ]

    def close(self) -> None:
        return None


def test_exiftool_json_priority_and_signed_gps() -> None:
    metadata = metadata_from_exiftool_json(
        {
            "DateTimeOriginal": "2025:05:15 08:20:00",
            "CreateDate": "2025:05:15 09:00:00",
            "OffsetTimeOriginal": "+02:00",
            "GPSLatitude": 46.498,
            "GPSLongitude": 11.353,
            "GPSAltitude": 262,
            "Make": "Canon",
            "Model": "EOS R6",
            "ImageWidth": 6000,
            "ImageHeight": 4000,
        }
    )
    assert metadata.captured is not None
    assert metadata.captured.source == "exif_datetime_original"
    assert metadata.captured.timezone_unknown is False
    assert metadata.position is not None
    assert abs(metadata.position.latitude - 46.498) < 1e-9
    assert abs(metadata.position.longitude - 11.353) < 1e-9
    assert metadata.camera == "Canon EOS R6"
    assert metadata.width == 6000


def test_exiftool_json_video_creation_time() -> None:
    metadata = metadata_from_exiftool_json({"MediaCreateDate": "2025:05:15 08:20:00"})
    assert metadata.captured is not None
    assert metadata.captured.source == "video_creation_time"
    assert metadata.captured.timezone_unknown is True


def test_exiftool_json_quicktime_gps_coordinates() -> None:
    metadata = metadata_from_exiftool_json(
        {"GPSCoordinates": "46.498011 11.353000 262", "Make": "Apple", "Model": "iPhone 15"}
    )
    assert metadata.position is not None
    assert abs(metadata.position.latitude - 46.498011) < 1e-6
    assert abs(metadata.position.longitude - 11.353) < 1e-6
    assert metadata.position.source == "quicktime"
    assert metadata.camera == "Apple iPhone 15"


def test_exiftool_provider_read_uses_session(tmp_path: Path) -> None:
    session = _FakeSession()
    provider = ExifToolMetadataProvider("exiftool", session=session)
    path = tmp_path / "foto.jpg"
    path.write_bytes(b"\xff\xd8\xff")
    metadata = provider.read(path)
    assert metadata.camera == "Canon EOS R6"
    assert session.calls == [[str(path)]]
    provider.close()


def test_exiftool_provider_read_many_batches_paths(tmp_path: Path) -> None:
    session = _FakeSession()
    provider = ExifToolMetadataProvider("exiftool", session=session)
    first = tmp_path / "a.jpg"
    second = tmp_path / "b.heic"
    first.write_bytes(b"a")
    second.write_bytes(b"b")
    result = provider.read_many([first, second])
    assert set(result) == {str(first), str(second)}
    assert result[str(first)].width == 64
    assert session.calls == [[str(first), str(second)]]
