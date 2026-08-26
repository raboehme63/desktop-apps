from pathlib import Path

from PIL import Image

from travelcore.maps.static import latlon_to_world_px, render_leaflet_excerpt
from travelcore.media.thumbnails import _track_tile_cache
from travelcore.project_settings import ProjectSettings, save_project_settings

_MAP = (186, 200, 168)
_TRACK = ((46.0, 11.0), (46.2, 11.3))


def test_latlon_to_world_px_origin_at_zoom_zero() -> None:
    x, y = latlon_to_world_px(0.0, 0.0, 0)
    assert round(x) == 128
    assert round(y) == 128


def test_leaflet_excerpt_paints_red_track_on_stub_tiles() -> None:
    def fetch(_z: int, _x: int, _y: int) -> Image.Image:
        return Image.new("RGB", (256, 256), _MAP)

    image = render_leaflet_excerpt([list(_TRACK)], 64, fetch=fetch)
    assert image.size == (64, 64)
    pixels = [
        image.getpixel((column, row))
        for row in range(image.height)
        for column in range(image.width)
    ]
    mapped = sum(
        1
        for pixel in pixels
        if all(abs(pixel[index] - _MAP[index]) <= 12 for index in range(3))
    )
    red = sum(
        1 for pixel in pixels if pixel[0] > 90 and pixel[0] > pixel[1] + 40 and pixel[0] > pixel[2] + 40
    )
    assert mapped > len(pixels) * 0.45
    assert red > 8


def test_leaflet_excerpt_falls_back_to_black_without_tiles() -> None:
    image = render_leaflet_excerpt([list(_TRACK)], 64, fetch=lambda _z, _x, _y: None)
    pixels = [
        image.getpixel((column, row))
        for row in range(image.height)
        for column in range(image.width)
    ]
    black = sum(1 for pixel in pixels if pixel[0] < 40 and pixel[1] < 40 and pixel[2] < 40)
    red = sum(
        1 for pixel in pixels if pixel[0] > 90 and pixel[0] > pixel[1] + 40 and pixel[0] > pixel[2] + 40
    )
    assert black > len(pixels) * 0.45
    assert red > 8


def test_leaflet_provider_creates_tile_cache_dir(tmp_path: Path) -> None:
    thumbs = tmp_path / "reise" / "thumbnails"
    thumbs.mkdir(parents=True)
    save_project_settings(thumbs.parent, ProjectSettings())
    cache, use_tiles = _track_tile_cache(thumbs)
    assert use_tiles is True
    assert Path(cache) == thumbs.parent / "cache" / "map_tiles"
    assert Path(cache).is_dir()


def test_offline_provider_skips_osm_tiles(tmp_path: Path) -> None:
    thumbs = tmp_path / "reise" / "thumbnails"
    thumbs.mkdir(parents=True)
    settings = ProjectSettings()
    settings.placeholders.map_provider = "offline"
    save_project_settings(thumbs.parent, settings)
    cache, use_tiles = _track_tile_cache(thumbs)
    assert cache == ""
    assert use_tiles is False
