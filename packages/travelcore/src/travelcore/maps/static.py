"""Raster map excerpts using the same OSM tiles as Leaflet/Folium."""

from __future__ import annotations

import io
import logging
import math
import threading
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

from PIL import Image, ImageDraw

logger = logging.getLogger(__name__)

TILE_SIZE = 256
MIN_ZOOM = 3
MAX_ZOOM = 16
MAX_TILES = 25
_OSM_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
_USER_AGENT = "TravelJournal/0.1 (desktop; Leaflet map thumbnails)"
_FETCH_LOCK = threading.Lock()
_TRACK_LINE = (220, 24, 24)
_FALLBACK = (0, 0, 0)

TileFetch = Callable[[int, int, int], Image.Image | None]


def latlon_to_world_px(lat: float, lon: float, zoom: int) -> tuple[float, float]:
    """Leaflet/Web-Mercator world pixel at the given zoom (tile size 256)."""

    lat = max(-85.05112878, min(85.05112878, lat))
    n = TILE_SIZE * (2**zoom)
    x = (lon + 180.0) / 360.0 * n
    siny = math.sin(math.radians(lat))
    y = (0.5 - math.log((1 + siny) / (1 - siny)) / (4 * math.pi)) * n
    return x, y


def fetch_osm_tile(z: int, x: int, y: int, *, cache_dir: Path | None = None) -> Image.Image | None:
    """Download one OSM raster tile (Leaflet default). Originals are never written."""

    n = 2**z
    x = x % n
    if y < 0 or y >= n:
        return None
    cached = cache_dir / str(z) / str(x) / f"{y}.png" if cache_dir is not None else None
    if cached is not None and cached.is_file() and cached.stat().st_size > 0:
        try:
            with Image.open(cached) as image:
                return image.convert("RGB")
        except OSError:
            pass
    request = urllib.request.Request(
        _OSM_URL.format(z=z, x=x, y=y),
        headers={"User-Agent": _USER_AGENT},
    )
    try:
        with _FETCH_LOCK, urllib.request.urlopen(request, timeout=8) as response:
            data = response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.debug("OSM-Kachel %s/%s/%s fehlgeschlagen: %s", z, x, y, exc)
        return None
    try:
        with Image.open(io.BytesIO(data)) as image:
            rgb = image.convert("RGB")
    except OSError:
        return None
    if cached is not None:
        try:
            cached.parent.mkdir(parents=True, exist_ok=True)
            cached.write_bytes(data)
        except OSError:
            logger.debug("Kachel-Cache nicht schreibbar: %s", cached)
    return rgb


def render_leaflet_excerpt(
    segments: list[list[tuple[float, float]]],
    size: int,
    *,
    cache_dir: Path | None = None,
    fetch: TileFetch | None = None,
) -> Image.Image:
    """Square map excerpt with a red track, matching Leaflet's OSM tiles."""

    zoom, left, top, span = _view_window(segments, size)
    canvas_size = max(int(math.ceil(span)), size)
    scale = canvas_size / span
    image = Image.new("RGB", (canvas_size, canvas_size), _FALLBACK)
    getter = fetch if fetch is not None else (
        lambda z, x, y: fetch_osm_tile(z, x, y, cache_dir=cache_dir)
    )
    tx0 = int(math.floor(left / TILE_SIZE))
    ty0 = int(math.floor(top / TILE_SIZE))
    tx1 = int(math.floor((left + span) / TILE_SIZE))
    ty1 = int(math.floor((top + span) / TILE_SIZE))
    pasted_any = False
    misses = 0
    for tile_x in range(tx0, tx1 + 1):
        for tile_y in range(ty0, ty1 + 1):
            tile = getter(zoom, tile_x, tile_y)
            if tile is None:
                misses += 1
                if not pasted_any and misses >= 2:
                    break
                continue
            pasted_any = True
            x = int(round((tile_x * TILE_SIZE - left) * scale))
            y = int(round((tile_y * TILE_SIZE - top) * scale))
            pasted = tile.resize(
                (max(1, int(round(TILE_SIZE * scale))), max(1, int(round(TILE_SIZE * scale)))),
                Image.Resampling.BILINEAR,
            )
            image.paste(pasted, (x, y))
        else:
            continue
        break
    draw = ImageDraw.Draw(image)
    width = max(2, round(canvas_size / 72))
    for segment in segments:
        pixels = [_to_canvas(lat, lon, zoom, left, top, scale) for lat, lon in segment]
        if len(pixels) == 1:
            x, y = pixels[0]
            radius = max(width, 3)
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=_TRACK_LINE)
            continue
        draw.line(pixels, fill=_TRACK_LINE, width=width)
    if canvas_size == size:
        return image
    return image.resize((size, size), Image.Resampling.LANCZOS)


def _to_canvas(
    lat: float, lon: float, zoom: int, left: float, top: float, scale: float
) -> tuple[int, int]:
    x, y = latlon_to_world_px(lat, lon, zoom)
    return int(round((x - left) * scale)), int(round((y - top) * scale))


def _view_window(
    segments: list[list[tuple[float, float]]], size: int
) -> tuple[int, float, float, float]:
    lats = [lat for segment in segments for lat, _lon in segment]
    lons = [lon for segment in segments for _lat, lon in segment]
    min_lat, max_lat = min(lats), max(lats)
    min_lon, max_lon = min(lons), max(lons)
    if max_lat - min_lat < 1e-6:
        min_lat -= 0.004
        max_lat += 0.004
    if max_lon - min_lon < 1e-6:
        min_lon -= 0.004
        max_lon += 0.004
    pad_lat = (max_lat - min_lat) * 0.12
    pad_lon = (max_lon - min_lon) * 0.12
    min_lat -= pad_lat
    max_lat += pad_lat
    min_lon -= pad_lon
    max_lon += pad_lon
    chosen = MIN_ZOOM
    x0, y0 = latlon_to_world_px(max_lat, min_lon, chosen)
    x1, y1 = latlon_to_world_px(min_lat, max_lon, chosen)
    span = max(abs(x1 - x0), abs(y1 - y0), size)
    cx = (x0 + x1) / 2.0
    cy = (y0 + y1) / 2.0
    for zoom in range(MAX_ZOOM, MIN_ZOOM - 1, -1):
        x0, y0 = latlon_to_world_px(max_lat, min_lon, zoom)
        x1, y1 = latlon_to_world_px(min_lat, max_lon, zoom)
        next_span = max(abs(x1 - x0), abs(y1 - y0), size)
        tiles = (int(next_span / TILE_SIZE) + 2) ** 2
        if tiles > MAX_TILES:
            continue
        chosen = zoom
        cx = (x0 + x1) / 2.0
        cy = (y0 + y1) / 2.0
        span = next_span
        break
    span = min(span, float(TILE_SIZE * int(math.sqrt(MAX_TILES))))
    return chosen, cx - span / 2.0, cy - span / 2.0, span
