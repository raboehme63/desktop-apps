"""Create cached JPEG thumbnails. Original media files are never written."""

from __future__ import annotations

import io
import logging
import math
import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from travelcore.config import DEFAULT_THUMBNAIL_SIZE
from travelcore.database.models import Photo, Project, SourceFile, Video
from travelcore.exceptions import GpsError, ProjectError
from travelcore.gps.geojson import parse_geojson
from travelcore.gps.igc import parse_igc
from travelcore.gps.kml import parse_kml
from travelcore.gps.parse import ParsedTrack, parse_gpx
from travelcore.media.heic_win import decode_windows_thumbnail
from travelcore.media.heif_items import extract_heif_jpeg_item
from travelcore.media.orientation import apply_display_rotation, normalize_rotation_degrees
from travelcore.media.types import GPS_EXTENSIONS, PHOTO_EXTENSIONS, VIDEO_EXTENSIONS, FileKind
from travelcore.parallel import WorkerPool, map_in_processes
from travelcore.project_settings import load_project_settings

logger = logging.getLogger(__name__)

_PILLOW_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}
_HEIC_SUFFIXES = {".heic", ".heif"}
_RAW_SUFFIXES = PHOTO_EXTENSIONS - _PILLOW_SUFFIXES - _HEIC_SUFFIXES
_JPEG_SOI = b"\xff\xd8\xff"
_THUMB_FILL = (18, 21, 28)
# Full-size decode above this is too expensive. JPEG still uses Image.draft first.
_MAX_THUMB_SOURCE_PIXELS = 40_000_000
_MAX_TRACK_POINTS = 800
_RAW_PREVIEW_BYTES = 32 * 1024 * 1024
_VIDEO_PREVIEW_BYTES = 8 * 1024 * 1024

ProgressFn = Callable[[int, int, str], None]


@dataclass(frozen=True, slots=True)
class ThumbnailJob:
    source: str
    destination: str
    size: int
    tile_cache: str = ""
    use_map_tiles: bool = True
    rotation_degrees: int = 0


@dataclass(slots=True)
class ThumbnailResult:
    written: int = 0
    skipped: int = 0
    failed: int = 0


_LEGACY_THUMBNAIL_SIZES = (256,)


def cached_thumbnail_path(
    thumbs_dir: Path,
    *,
    source_file_id: int,
    sha256: str | None,
    size: int,
    rotation_degrees: int | None = 0,
    prefer_existing: bool = False,
) -> Path:
    """Return the cache path for a thumbnail. The file may not exist yet."""

    dest = _thumbnail_cache_path(
        thumbs_dir,
        source_file_id=source_file_id,
        sha256=sha256,
        size=size,
        rotation_degrees=rotation_degrees,
    )
    if not prefer_existing or dest.is_file():
        return dest
    for legacy in _LEGACY_THUMBNAIL_SIZES:
        if legacy == size:
            continue
        candidate = _thumbnail_cache_path(
            thumbs_dir,
            source_file_id=source_file_id,
            sha256=sha256,
            size=legacy,
            rotation_degrees=rotation_degrees,
        )
        if candidate.is_file():
            return candidate
    return dest


def _thumbnail_cache_path(
    thumbs_dir: Path,
    *,
    source_file_id: int,
    sha256: str | None,
    size: int,
    rotation_degrees: int | None,
) -> Path:
    suffix = ""
    degrees = normalize_rotation_degrees(rotation_degrees)
    if degrees:
        suffix = f"_r{degrees}"
    if sha256:
        return thumbs_dir / f"{sha256}_{size}{suffix}.jpg"
    return thumbs_dir / f"sf{source_file_id}_{size}{suffix}.jpg"


def ensure_thumbnail(
    source: Path,
    destination: Path,
    *,
    size: int = DEFAULT_THUMBNAIL_SIZE,
    orientation: int | None = None,
    rotation_degrees: int | None = 0,
    tile_cache: Path | None = None,
    use_map_tiles: bool = True,
) -> Path | None:
    """Build a square JPEG thumbnail at ``destination``. Returns None on failure."""

    _ = orientation
    if destination.is_file() and destination.stat().st_size > 0:
        return destination
    if source.suffix.lower() in GPS_EXTENSIONS:
        return _write_track_thumbnail(
            source,
            destination,
            size=size,
            tile_cache=tile_cache,
            use_map_tiles=use_map_tiles,
        )
    image = _open_preview(source, size=size)
    if image is None:
        return None
    try:
        transposed = ImageOps.exif_transpose(image)
        working = transposed if transposed is not None else image
        working = apply_display_rotation(working, rotation_degrees)
        fitted = _fit_square(working, size)
        destination.parent.mkdir(parents=True, exist_ok=True)
        fitted.save(destination, format="JPEG", quality=85, optimize=True)
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError) as exc:
        logger.warning("Thumbnail failed for %s: %s", source.name, exc)
        return None
    finally:
        image.close()
    return destination if destination.is_file() else None


def write_project_gps_thumbnail(
    project_dir: Path,
    row: SourceFile,
    *,
    size: int = DEFAULT_THUMBNAIL_SIZE,
    overwrite: bool = False,
) -> Path | None:
    """Write a GPS thumbnail using the project's Leaflet/OSM tile cache."""

    thumbs = Path(project_dir) / "thumbnails"
    dest = cached_thumbnail_path(
        thumbs,
        source_file_id=row.id,
        sha256=row.sha256,
        size=size,
    )
    tile_cache, use_map_tiles = _track_tile_cache(thumbs)
    if overwrite and dest.is_file():
        dest.unlink(missing_ok=True)
    return ensure_thumbnail(
        Path(row.path),
        dest,
        size=size,
        tile_cache=Path(tile_cache) if tile_cache else None,
        use_map_tiles=use_map_tiles,
    )


def _write_track_thumbnail(
    source: Path,
    destination: Path,
    *,
    size: int,
    tile_cache: Path | None = None,
    use_map_tiles: bool = True,
) -> Path | None:
    try:
        tracks = _parse_track_file(source)
    except GpsError as exc:
        logger.warning("Track-Thumbnail fehlgeschlagen für %s: %s", source.name, exc)
        return None
    segments = _track_segments(tracks)
    if not segments:
        return None
    try:
        image = _render_track_image(segments, size, tile_cache=tile_cache, use_map_tiles=use_map_tiles)
        destination.parent.mkdir(parents=True, exist_ok=True)
        image.save(destination, format="JPEG", quality=90, optimize=True)
    except (OSError, ValueError) as exc:
        logger.warning("Track-Thumbnail fehlgeschlagen für %s: %s", source.name, exc)
        return None
    return destination if destination.is_file() else None


def _parse_track_file(source: Path) -> tuple[ParsedTrack, ...]:
    suffix = source.suffix.lower()
    if suffix == ".gpx":
        return parse_gpx(source)
    if suffix == ".igc":
        return parse_igc(source)
    if suffix == ".kml":
        return parse_kml(source)
    if suffix == ".geojson":
        return parse_geojson(source)
    return ()


def _track_segments(tracks: tuple[ParsedTrack, ...]) -> list[list[tuple[float, float]]]:
    segments: list[list[tuple[float, float]]] = []
    for track in tracks:
        grouped: dict[int, list[tuple[float, float]]] = {}
        order: list[int] = []
        for point in track.points:
            bucket = grouped.get(point.segment_id)
            if bucket is None:
                bucket = []
                grouped[point.segment_id] = bucket
                order.append(point.segment_id)
            bucket.append((point.latitude, point.longitude))
        for segment_id in order:
            coords = _downsample_track(grouped[segment_id])
            if coords:
                segments.append(coords)
    return segments


def _downsample_track(coords: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if len(coords) <= _MAX_TRACK_POINTS:
        return coords
    step = math.ceil(len(coords) / _MAX_TRACK_POINTS)
    sampled = coords[::step]
    if sampled[-1] != coords[-1]:
        sampled.append(coords[-1])
    return sampled


def _render_track_image(
    segments: list[list[tuple[float, float]]],
    size: int,
    *,
    tile_cache: Path | None = None,
    use_map_tiles: bool = True,
) -> Image.Image:
    from travelcore.maps.static import render_leaflet_excerpt

    if not use_map_tiles:
        return render_leaflet_excerpt(segments, size, fetch=_blank_map_tile)
    return render_leaflet_excerpt(segments, size, cache_dir=tile_cache)


def _blank_map_tile(_z: int, _x: int, _y: int) -> Image.Image | None:
    return None


def render_thumbnail_batch(jobs: tuple[ThumbnailJob, ...]) -> list[tuple[str, str, bool]]:
    """Module-level pool entry: write thumbnails for a chunk of jobs."""

    results: list[tuple[str, str, bool]] = []
    for job in jobs:
        written = ensure_thumbnail(
            Path(job.source),
            Path(job.destination),
            size=job.size,
            rotation_degrees=job.rotation_degrees,
            tile_cache=Path(job.tile_cache) if job.tile_cache else None,
            use_map_tiles=job.use_map_tiles,
        )
        results.append((job.source, job.destination, written is not None))
    return results


def generate_project_thumbnails(
    session: Session,
    project: Project,
    thumbs_dir: Path,
    *,
    size: int = DEFAULT_THUMBNAIL_SIZE,
    progress: ProgressFn | None = None,
    max_workers: int | None = None,
    pool: WorkerPool | None = None,
) -> ThumbnailResult:
    """Create missing thumbnails for photos, videos, and GPS tracks. Originals are read-only."""

    thumbs_dir.mkdir(parents=True, exist_ok=True)
    rows = list(
        session.scalars(
            select(SourceFile).where(
                SourceFile.project_id == project.id,
                SourceFile.file_kind.in_((FileKind.PHOTO.value, FileKind.VIDEO.value, FileKind.GPS.value)),
            )
        )
    )
    result = ThumbnailResult()
    jobs: list[ThumbnailJob] = []
    queued_dests: set[str] = set()
    tile_cache, use_map_tiles = _track_tile_cache(thumbs_dir)
    for row in rows:
        rotation = normalize_rotation_degrees(row.rotation_degrees)
        dest = cached_thumbnail_path(
            thumbs_dir,
            source_file_id=row.id,
            sha256=row.sha256,
            size=size,
            rotation_degrees=rotation,
        )
        dest_key = str(dest)
        if dest.is_file() and dest.stat().st_size > 0:
            if not _should_refresh_gps_thumbnail(row, dest, use_map_tiles=use_map_tiles):
                result.skipped += 1
                continue
            dest.unlink(missing_ok=True)
            if dest.is_file():
                result.skipped += 1
                continue
        if dest_key in queued_dests:
            result.skipped += 1
            continue
        queued_dests.add(dest_key)
        jobs.append(
            ThumbnailJob(
                source=row.path,
                destination=dest_key,
                size=size,
                tile_cache=tile_cache,
                use_map_tiles=use_map_tiles,
                rotation_degrees=rotation,
            )
        )

    total = max(len(rows), 1)
    done = result.skipped

    if not jobs:
        if progress is not None:
            progress(total, total, "")
        return result

    outcomes = _render_thumbnail_jobs(
        jobs,
        max_workers=max_workers,
        pool=pool,
        progress=progress,
        total=total,
        skipped=done,
    )
    for _source, _destination, ok in outcomes:
        if ok:
            result.written += 1
        else:
            result.failed += 1
    return result


def _needs_com_preview(source: str) -> bool:
    """True when Windows Shell/WIC must run on an STA thread, not in a process pool."""

    if sys.platform != "win32":
        return False
    suffix = Path(source).suffix.lower()
    return suffix in _HEIC_SUFFIXES or suffix in _RAW_SUFFIXES or suffix in VIDEO_EXTENSIONS


def _init_com_thread() -> None:
    from travelcore.media.heic_win import ensure_com

    ensure_com()


def _render_thumbnail_jobs(
    jobs: list[ThumbnailJob],
    *,
    max_workers: int | None,
    pool: WorkerPool | None,
    progress: ProgressFn | None,
    total: int,
    skipped: int,
) -> list[tuple[str, str, bool]]:
    cpu_jobs = [job for job in jobs if not _needs_com_preview(job.source)]
    com_jobs = [job for job in jobs if _needs_com_preview(job.source)]
    outcomes: list[tuple[str, str, bool]] = []

    def on_cpu(completed: int, _job_total: int) -> None:
        if progress is None:
            return
        path = cpu_jobs[min(completed, len(cpu_jobs)) - 1].source if cpu_jobs and completed else ""
        progress(min(skipped + completed, total), total, path)

    com_executor: ThreadPoolExecutor | None = None
    com_future = None
    if com_jobs:
        com_executor = ThreadPoolExecutor(max_workers=1, initializer=_init_com_thread)
        com_future = com_executor.submit(render_thumbnail_batch, tuple(com_jobs))
    try:
        if cpu_jobs:
            outcomes.extend(
                map_in_processes(
                    render_thumbnail_batch,
                    cpu_jobs,
                    max_workers=max_workers,
                    progress=on_cpu,
                    pool=pool,
                )
            )
        if com_future is not None:
            outcomes.extend(com_future.result())
            if progress is not None:
                path = com_jobs[-1].source if com_jobs else ""
                progress(min(skipped + len(jobs), total), total, path)
    finally:
        if com_executor is not None:
            com_executor.shutdown(wait=True)
    return outcomes


def _should_refresh_gps_thumbnail(
    row: SourceFile, dest: Path, *, use_map_tiles: bool
) -> bool:
    """Rewrite import-folder GPS thumbs that were saved without OSM tiles."""

    if not use_map_tiles or row.file_kind != FileKind.GPS.value:
        return False
    from travelcore.gps.fitnesstracks import is_fitness_track_path
    from travelcore.gps.igctracks import is_igc_track_path
    from travelcore.gps.maptracks import is_map_track_path

    if not (
        is_fitness_track_path(row.path)
        or is_igc_track_path(row.path)
        or is_map_track_path(row.path)
    ):
        return False
    return _track_thumbnail_lacks_map(dest)


def _track_thumbnail_lacks_map(path: Path) -> bool:
    """True when the JPEG looks like the no-tiles fallback (black + red line)."""

    try:
        with Image.open(path) as image:
            rgb = image.convert("RGB")
            pixels = rgb.load()
            width, height = rgb.size
            if pixels is None or width * height == 0:
                return False
            black = 0
            for row in range(height):
                for column in range(width):
                    red, green, blue = pixels[column, row][:3]
                    if red < 40 and green < 40 and blue < 40:
                        black += 1
    except OSError:
        return False
    return black > width * height * 0.45


def _track_tile_cache(thumbs_dir: Path) -> tuple[str, bool]:
    project_dir = thumbs_dir.parent
    try:
        provider = load_project_settings(project_dir).placeholders.map_provider
    except ProjectError:
        provider = "leaflet"
    if provider.strip().lower() == "offline":
        return "", False
    cache = project_dir / "cache" / "map_tiles" / "osmde"
    try:
        cache.mkdir(parents=True, exist_ok=True)
    except OSError:
        return "", True
    return str(cache), True


def ensure_photo_and_video_rows(session: Session, project: Project) -> None:
    """Create ``photos`` / ``videos`` rows for indexed media if they are missing."""

    session.flush()
    photo_ids = _present_source_ids(session, Photo)
    video_ids = _present_source_ids(session, Video)
    files = list(session.scalars(select(SourceFile).where(SourceFile.project_id == project.id)))
    photos: list[dict[str, object]] = []
    videos: list[dict[str, object]] = []
    for row in files:
        if row.id is None:
            continue
        if row.file_kind == FileKind.PHOTO.value and row.id not in photo_ids:
            photos.append(
                {
                    "source_file_id": row.id,
                    "is_favorite": False,
                    "used_in_journal": False,
                    "is_cover": False,
                    "origin": "auto",
                }
            )
            photo_ids.add(row.id)
        elif row.file_kind == FileKind.VIDEO.value and row.id not in video_ids:
            videos.append({"source_file_id": row.id, "origin": "auto"})
            video_ids.add(row.id)
    if photos:
        stmt = sqlite_insert(Photo).on_conflict_do_nothing(index_elements=["source_file_id"])
        session.execute(stmt, photos)
    if videos:
        stmt = sqlite_insert(Video).on_conflict_do_nothing(index_elements=["source_file_id"])
        session.execute(stmt, videos)
    session.flush()


def _present_source_ids(session: Session, model: type[Photo] | type[Video]) -> set[int]:
    found = {value for value in session.scalars(select(model.source_file_id)) if value is not None}
    for obj in session.new:
        if isinstance(obj, model) and obj.source_file_id is not None:
            found.add(obj.source_file_id)
    return found


def extract_largest_embedded_jpeg(data: bytes) -> bytes | None:
    """Return the largest JPEG payload embedded in a HEIC/HEIF container, if any."""

    best: bytes | None = None
    best_pixels = 0
    start = 0
    found = 0
    while found < 24:
        idx = data.find(_JPEG_SOI, start)
        if idx < 0:
            break
        end = _jpeg_end(data, idx)
        start = idx + 3
        if end is None or end - idx < 128:
            continue
        blob = data[idx:end]
        pixels = _jpeg_pixel_count(blob)
        found += 1
        if pixels > best_pixels:
            best = blob
            best_pixels = pixels
    return best if best_pixels >= 16 * 16 else None


def _open_preview(source: Path, *, size: int = DEFAULT_THUMBNAIL_SIZE) -> Image.Image | None:
    suffix = source.suffix.lower()
    try:
        if suffix in _PILLOW_SUFFIXES:
            image = Image.open(source)
            width, height = image.size
            if width * height > _MAX_THUMB_SOURCE_PIXELS:
                if suffix in {".jpg", ".jpeg"}:
                    drafted = _draft_or_close(image, size)
                    if drafted is not None:
                        return drafted
                    windows = decode_windows_thumbnail(source, size=max(int(size), DEFAULT_THUMBNAIL_SIZE))
                    if windows is not None:
                        return windows
                else:
                    image.close()
                logger.warning(
                    "Thumbnail skipped, image too large: %s (%sx%s)",
                    source.name,
                    width,
                    height,
                )
                return None
            return image
        if suffix in _HEIC_SUFFIXES:
            windows = decode_windows_thumbnail(source, size=max(int(size), DEFAULT_THUMBNAIL_SIZE))
            if windows is not None:
                return windows
            payload = source.read_bytes()
            embedded = extract_heif_jpeg_item(payload) or extract_largest_embedded_jpeg(payload)
            if embedded is not None:
                return Image.open(io.BytesIO(embedded))
            return None
        if suffix in _RAW_SUFFIXES or suffix in VIDEO_EXTENSIONS:
            windows = decode_windows_thumbnail(source, size=max(int(size), DEFAULT_THUMBNAIL_SIZE))
            if windows is not None:
                return windows
            limit = _VIDEO_PREVIEW_BYTES if suffix in VIDEO_EXTENSIONS else _RAW_PREVIEW_BYTES
            embedded = extract_largest_embedded_jpeg(_read_prefix(source, limit))
            if embedded is not None:
                return Image.open(io.BytesIO(embedded))
            return _type_placeholder(suffix, size=size)
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        logger.debug("No preview image for %s", source.name)
        return None
    return None


def _draft_or_close(image: Image.Image, size: int) -> Image.Image | None:
    """Decode JPEG/MPO at a reduced size so 48 MP phone photos still get a thumbnail."""

    target = max(int(size) * 4, 512)
    try:
        image.draft("RGB", (target, target))
    except (OSError, ValueError, SyntaxError):
        image.close()
        return None
    width, height = image.size
    if width * height > _MAX_THUMB_SOURCE_PIXELS:
        image.close()
        return None
    return image


def _read_prefix(source: Path, limit: int) -> bytes:
    with source.open("rb") as handle:
        return handle.read(limit)


def _type_placeholder(suffix: str, *, size: int = DEFAULT_THUMBNAIL_SIZE) -> Image.Image:
    canvas = Image.new("RGB", (size, size), _THUMB_FILL)
    draw = ImageDraw.Draw(canvas)
    label = suffix.lstrip(".").upper() or "?"
    bbox = draw.textbbox((0, 0), label)
    width, height = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((size - width) // 2, (size - height) // 2), label, fill=(197, 205, 219))
    return canvas


def _fit_square(image: Image.Image, size: int) -> Image.Image:
    rgb = image.convert("RGB")
    rgb.thumbnail((size, size), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (size, size), _THUMB_FILL)
    left = (size - rgb.width) // 2
    top = (size - rgb.height) // 2
    canvas.paste(rgb, (left, top))
    return canvas


def _jpeg_end(data: bytes, start: int) -> int | None:
    if start + 2 > len(data) or data[start] != 0xFF or data[start + 1] != 0xD8:
        return None
    index = start + 2
    length = len(data)
    while index + 1 < length:
        if data[index] != 0xFF:
            return None
        while index < length and data[index] == 0xFF:
            index += 1
        if index >= length:
            return None
        marker = data[index]
        index += 1
        if marker == 0xD9:
            return index
        if marker in {0xD8, 0x01} or 0xD0 <= marker <= 0xD7:
            continue
        if marker == 0xDA:
            while index + 1 < length:
                if data[index] == 0xFF and data[index + 1] != 0x00:
                    nxt = data[index + 1]
                    if nxt == 0xD9:
                        return index + 2
                    if 0xD0 <= nxt <= 0xD7:
                        index += 2
                        continue
                index += 1
            return None
        if index + 2 > length:
            return None
        size = int.from_bytes(data[index : index + 2], "big")
        if size < 2:
            return None
        index += size
    return None


def _jpeg_pixel_count(blob: bytes) -> int:
    try:
        with Image.open(io.BytesIO(blob)) as image:
            image.load()
            width, height = image.size
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
        return 0
    return width * height
