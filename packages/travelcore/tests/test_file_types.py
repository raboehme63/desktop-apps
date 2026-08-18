from pathlib import Path

from travelcore.media.types import FileKind, classify_path, mime_for_path


def test_jpeg_is_photo() -> None:
    assert classify_path(Path("urlaub.JPG")) is FileKind.PHOTO
    assert classify_path(Path("urlaub.jpeg")) is FileKind.PHOTO


def test_gpx_is_gps() -> None:
    assert classify_path(Path("track.gpx")) is FileKind.GPS
    assert mime_for_path(Path("track.gpx")) == "application/gpx+xml"


def test_markdown_is_text() -> None:
    assert classify_path(Path("notes.md")) is FileKind.TEXT


def test_unsupported_returns_none() -> None:
    assert classify_path(Path("archive.zip")) is None


def test_raw_is_photo_for_metadata_later() -> None:
    assert classify_path(Path("DSC_0001.NEF")) is FileKind.PHOTO
