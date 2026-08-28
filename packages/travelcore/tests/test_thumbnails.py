from io import BytesIO
from pathlib import Path

import pytest
from gpx_fixtures import write_gpx
from igc_fixtures import bozen_points, write_igc
from jpeg_fixtures import write_jpeg_with_exif, write_plain_jpeg
from PIL import Image

from travelcore.media.heif_items import extract_heif_jpeg_item
from travelcore.media.thumbnails import (
    cached_thumbnail_path,
    ensure_thumbnail,
    extract_largest_embedded_jpeg,
)


def test_ensure_thumbnail_writes_square_jpeg(tmp_path: Path) -> None:
    source = write_plain_jpeg(tmp_path / "foto.jpg", size=(64, 48))
    original_mtime = source.stat().st_mtime
    dest = tmp_path / "thumbs" / "a_256.jpg"
    written = ensure_thumbnail(source, dest, size=32)
    assert written == dest
    assert dest.is_file()
    with Image.open(dest) as image:
        assert image.size == (32, 32)
        assert image.format == "JPEG"
    assert source.stat().st_mtime == original_mtime


def test_ensure_thumbnail_skips_existing(tmp_path: Path) -> None:
    source = write_plain_jpeg(tmp_path / "foto.jpg")
    dest = tmp_path / "thumb.jpg"
    ensure_thumbnail(source, dest, size=32)
    first = dest.stat().st_mtime
    again = ensure_thumbnail(source, dest, size=32)
    assert again == dest
    assert dest.stat().st_mtime == first


def test_ensure_thumbnail_writes_png(tmp_path: Path) -> None:
    source = tmp_path / "karte.png"
    Image.new("RGB", (48, 32), "teal").save(source)
    dest = tmp_path / "karte.jpg"
    written = ensure_thumbnail(source, dest, size=32)
    assert written == dest
    with Image.open(dest) as image:
        assert image.size == (32, 32)
        assert image.format == "JPEG"


def test_ensure_thumbnail_skips_huge_png(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import travelcore.media.thumbnails as thumbs

    monkeypatch.setattr(thumbs, "_MAX_THUMB_SOURCE_PIXELS", 10)
    source = tmp_path / "huge.png"
    Image.new("RGB", (8, 8), "red").save(source)
    dest = tmp_path / "out.jpg"
    assert thumbs.ensure_thumbnail(source, dest, size=32) is None
    assert not dest.is_file()


def test_ensure_thumbnail_drafts_huge_jpeg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import travelcore.media.thumbnails as thumbs

    monkeypatch.setattr(thumbs, "_MAX_THUMB_SOURCE_PIXELS", 1_000_000)
    source = write_plain_jpeg(tmp_path / "phone.jpg", size=(1600, 1200))
    original_mtime = source.stat().st_mtime
    dest = tmp_path / "out.jpg"
    written = thumbs.ensure_thumbnail(source, dest, size=32)
    assert written == dest
    assert dest.is_file()
    with Image.open(dest) as image:
        assert image.size == (32, 32)
        assert image.format == "JPEG"
    assert source.stat().st_mtime == original_mtime


def test_corrupt_jpeg_returns_none(tmp_path: Path) -> None:
    source = tmp_path / "broken.jpg"
    source.write_bytes(b"not-a-jpeg")
    assert ensure_thumbnail(source, tmp_path / "out.jpg", size=32) is None
    assert not (tmp_path / "out.jpg").is_file()


def test_heic_uses_embedded_jpeg_preview(tmp_path: Path) -> None:
    jpeg = write_plain_jpeg(tmp_path / "inner.jpg", size=(40, 30))
    heic = tmp_path / "IMG_0001.HEIC"
    heic.write_bytes(b"ftypheic" + b"\x00" * 32 + jpeg.read_bytes())
    dest = tmp_path / "heic.jpg"
    written = ensure_thumbnail(heic, dest, size=32)
    assert written == dest
    with Image.open(dest) as image:
        assert image.size == (32, 32)


def test_extract_largest_embedded_jpeg(tmp_path: Path) -> None:
    small = write_plain_jpeg(tmp_path / "s.jpg", size=(16, 12))
    large = write_jpeg_with_exif(tmp_path / "l.jpg", size=(48, 32))
    blob = b"xx" + small.read_bytes() + b"yy" + large.read_bytes()
    extracted = extract_largest_embedded_jpeg(blob)
    assert extracted is not None
    with Image.open(BytesIO(extracted)) as image:
        assert image.size == (48, 32)


def test_cached_thumbnail_path_uses_hash() -> None:
    path = cached_thumbnail_path(Path("thumbs"), source_file_id=9, sha256="abc123", size=256)
    assert path.name == "abc123_256.jpg"


def test_cached_thumbnail_path_includes_rotation() -> None:
    path = cached_thumbnail_path(
        Path("thumbs"), source_file_id=9, sha256="abc123", size=256, rotation_degrees=90
    )
    assert path.name == "abc123_256_r90.jpg"
    unchanged = cached_thumbnail_path(
        Path("thumbs"), source_file_id=9, sha256="abc123", size=256, rotation_degrees=0
    )
    assert unchanged.name == "abc123_256.jpg"


def test_ensure_thumbnail_applies_display_rotation(tmp_path: Path) -> None:
    source = write_plain_jpeg(tmp_path / "foto.jpg", size=(40, 20))
    dest = tmp_path / "r90.jpg"
    written = ensure_thumbnail(source, dest, size=32, rotation_degrees=90)
    assert written == dest
    assert dest.is_file()
    with Image.open(dest) as image:
        assert image.size == (32, 32)


def test_gpx_thumbnail_is_red_track_on_map(tmp_path: Path) -> None:
    source = write_gpx(
        tmp_path / "spur.gpx",
        [
            (46.0, 11.0, None, None),
            (46.2, 11.0, None, None),
            (46.2, 11.3, None, None),
            (46.0, 11.3, None, None),
        ],
    )
    dest = tmp_path / "spur.jpg"
    written = ensure_thumbnail(source, dest, size=64)
    assert written == dest
    _assert_red_on_map(dest, size=64)


def test_igc_thumbnail_is_red_track_on_map(tmp_path: Path) -> None:
    source = write_igc(tmp_path / "flug.igc", bozen_points())
    dest = tmp_path / "flug.jpg"
    written = ensure_thumbnail(source, dest, size=64)
    assert written == dest
    _assert_red_on_map(dest, size=64)


def test_empty_gpx_does_not_write_thumbnail(tmp_path: Path) -> None:
    source = tmp_path / "leer.gpx"
    source.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1"></gpx>',
        encoding="utf-8",
    )
    dest = tmp_path / "leer.jpg"
    assert ensure_thumbnail(source, dest, size=32) is None
    assert not dest.is_file()


def test_kml_thumbnail_is_red_track_on_map(tmp_path: Path) -> None:
    source = tmp_path / "route.kml"
    source.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<kml xmlns="http://www.opengis.net/kml/2.2"><Document><Placemark>'
        "<LineString><coordinates>11.0,46.0,0 11.3,46.0,0 11.3,46.2,0</coordinates>"
        "</LineString></Placemark></Document></kml>",
        encoding="utf-8",
    )
    dest = tmp_path / "route.jpg"
    written = ensure_thumbnail(source, dest, size=64)
    assert written == dest
    _assert_red_on_map(dest, size=64)


def test_geojson_thumbnail_is_red_track_on_map(tmp_path: Path) -> None:
    source = tmp_path / "route.geojson"
    source.write_text(
        '{"type":"LineString","coordinates":[[11.0,46.0],[11.3,46.0],[11.3,46.2]]}',
        encoding="utf-8",
    )
    dest = tmp_path / "route.jpg"
    written = ensure_thumbnail(source, dest, size=64)
    assert written == dest
    _assert_red_on_map(dest, size=64)


def test_gpx_thumbnail_falls_back_to_black_without_map_tiles(tmp_path: Path) -> None:
    source = write_gpx(
        tmp_path / "spur.gpx",
        [
            (46.0, 11.0, None, None),
            (46.2, 11.3, None, None),
        ],
    )
    dest = tmp_path / "spur.jpg"
    written = ensure_thumbnail(source, dest, size=64, use_map_tiles=False)
    assert written == dest
    _assert_red_on_black(dest, size=64)


def test_raw_uses_embedded_jpeg_preview(tmp_path: Path) -> None:
    jpeg = write_plain_jpeg(tmp_path / "inner.jpg", size=(40, 30))
    source = tmp_path / "shot.cr2"
    source.write_bytes(b"CRAW\x00" + jpeg.read_bytes())
    dest = tmp_path / "shot.jpg"
    written = ensure_thumbnail(source, dest, size=32)
    assert written == dest
    with Image.open(dest) as image:
        assert image.size == (32, 32)
        assert image.format == "JPEG"


def test_video_uses_embedded_jpeg_preview(tmp_path: Path) -> None:
    jpeg = write_plain_jpeg(tmp_path / "inner.jpg", size=(40, 30))
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"ftypisom" + jpeg.read_bytes())
    dest = tmp_path / "clip.jpg"
    written = ensure_thumbnail(source, dest, size=32)
    assert written == dest
    with Image.open(dest) as image:
        assert image.size == (32, 32)
        assert image.format == "JPEG"


def test_video_without_preview_writes_placeholder(tmp_path: Path) -> None:
    source = tmp_path / "leer.avi"
    source.write_bytes(b"RIFF....AVI ")
    dest = tmp_path / "leer.jpg"
    written = ensure_thumbnail(source, dest, size=32)
    assert written == dest
    with Image.open(dest) as image:
        assert image.size == (32, 32)
        assert image.format == "JPEG"


def _assert_red_on_map(path: Path, *, size: int) -> None:
    map_color = (186, 200, 168)
    with Image.open(path) as image:
        assert image.size == (size, size)
        assert image.format == "JPEG"
        pixels = [
            image.getpixel((column, row)) for row in range(image.height) for column in range(image.width)
        ]
    mapped = sum(1 for pixel in pixels if _near_color(pixel, map_color, delta=40))
    red = sum(
        1 for pixel in pixels if pixel[0] > 90 and pixel[0] > pixel[1] + 40 and pixel[0] > pixel[2] + 40
    )
    assert mapped > len(pixels) * 0.45
    assert red > 8


def _assert_red_on_black(path: Path, *, size: int) -> None:
    with Image.open(path) as image:
        assert image.size == (size, size)
        assert image.format == "JPEG"
        pixels = [
            image.getpixel((column, row)) for row in range(image.height) for column in range(image.width)
        ]
    black = sum(1 for pixel in pixels if pixel[0] < 40 and pixel[1] < 40 and pixel[2] < 40)
    red = sum(
        1 for pixel in pixels if pixel[0] > 90 and pixel[0] > pixel[1] + 40 and pixel[0] > pixel[2] + 40
    )
    assert black > len(pixels) * 0.45
    assert red > 8


def _near_color(pixel: tuple[int, ...], color: tuple[int, int, int], *, delta: int) -> bool:
    return all(abs(pixel[index] - color[index]) <= delta for index in range(3))


def _box(kind: bytes, payload: bytes) -> bytes:
    return (8 + len(payload)).to_bytes(4, "big") + kind + payload


def _full_box(kind: bytes, version: int, payload: bytes) -> bytes:
    return _box(kind, bytes([version, 0, 0, 0]) + payload)


def test_heic_jpeg_item_becomes_thumbnail(tmp_path: Path) -> None:
    jpeg = write_plain_jpeg(tmp_path / "inner.jpg", size=(40, 30)).read_bytes()
    infe = _full_box(
        b"infe",
        2,
        (1).to_bytes(2, "big") + (0).to_bytes(2, "big") + b"jpeg" + b"\x00",
    )
    iinf = _full_box(b"iinf", 0, (1).to_bytes(2, "big") + infe)

    def iloc(offset: int) -> bytes:
        body = bytes([0x44, 0x00])
        body += (1).to_bytes(2, "big")
        body += (1).to_bytes(2, "big")
        body += (0).to_bytes(2, "big")
        body += (1).to_bytes(2, "big")
        body += offset.to_bytes(4, "big")
        body += len(jpeg).to_bytes(4, "big")
        return _full_box(b"iloc", 0, body)

    ftyp = _box(b"ftyp", b"heic" + (0).to_bytes(4, "big") + b"mif1heic")
    meta = _full_box(b"meta", 0, iinf + iloc(0))
    jpeg_offset = len(ftyp) + len(meta) + 8
    meta = _full_box(b"meta", 0, iinf + iloc(jpeg_offset))
    heic = tmp_path / "item.heic"
    payload = ftyp + meta + _box(b"mdat", jpeg)
    heic.write_bytes(payload)
    extracted = extract_heif_jpeg_item(payload)
    assert extracted is not None
    dest = tmp_path / "from_item.jpg"
    written = ensure_thumbnail(heic, dest, size=32)
    assert written == dest
    with Image.open(dest) as image:
        assert image.size == (32, 32)


def test_windows_heic_helper_handles_garbage(tmp_path: Path) -> None:
    from travelcore.media.heic_win import decode_heic_preview

    junk = tmp_path / "nope.heic"
    junk.write_bytes(b"ftypheic\x00\x00")
    assert decode_heic_preview(junk) is None
