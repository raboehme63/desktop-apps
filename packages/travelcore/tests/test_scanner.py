from pathlib import Path

from travelcore.media.scanner import scan_source_directory
from travelcore.media.types import FileKind

MIN_JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"


def test_scan_finds_supported_files_recursively(tmp_path: Path) -> None:
    photos = tmp_path / "day1"
    photos.mkdir()
    (photos / "a.jpg").write_bytes(MIN_JPEG)
    (photos / "b.JPEG").write_bytes(MIN_JPEG)
    (tmp_path / "track.gpx").write_text("<gpx></gpx>", encoding="utf-8")
    (tmp_path / "notes.md").write_text("# Reise", encoding="utf-8")
    (tmp_path / "ignore.zip").write_bytes(b"nope")

    found = list(scan_source_directory(tmp_path))
    kinds = {item.kind for item in found}
    names = {item.filename.lower() for item in found}

    assert FileKind.PHOTO in kinds
    assert FileKind.GPS in kinds
    assert FileKind.TEXT in kinds
    assert "a.jpg" in names
    assert "b.jpeg" in names
    assert "ignore.zip" not in names
    assert len(found) == 4


def test_scan_finds_igc_flight_log(tmp_path: Path) -> None:
    (tmp_path / "flug.IGC").write_text("AXXX\n", encoding="utf-8")
    found = list(scan_source_directory(tmp_path))
    assert len(found) == 1
    assert found[0].kind is FileKind.GPS
    assert found[0].filename == "flug.IGC"
