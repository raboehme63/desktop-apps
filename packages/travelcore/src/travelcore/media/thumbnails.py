"""Create cached JPEG thumbnails. Original media files are never written."""

from __future__ import annotations

import io
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session

from travelcore.database.models import Photo, Project, SourceFile, Video
from travelcore.media.heic_win import decode_heic_preview
from travelcore.media.heif_items import extract_heif_jpeg_item
from travelcore.media.types import FileKind
from travelcore.parallel import map_in_threads

logger = logging.getLogger(__name__)

_PILLOW_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}
_HEIC_SUFFIXES = {".heic", ".heif"}
_JPEG_SOI = b"\xff\xd8\xff"
_THUMB_FILL = (18, 21, 28)
_MAX_THUMB_SOURCE_PIXELS = 40_000_000

ProgressFn = Callable[[int, int, str], None]


@dataclass(frozen=True, slots=True)
class ThumbnailJob:
    source: str
    destination: str
    size: int


@dataclass(slots=True)
class ThumbnailResult:
    written: int = 0
    skipped: int = 0
    failed: int = 0


def cached_thumbnail_path(
    thumbs_dir: Path,
    *,
    source_file_id: int,
    sha256: str | None,
    size: int,
) -> Path:
    """Return the cache path for a thumbnail. The file may not exist yet."""

    if sha256:
        return thumbs_dir / f"{sha256}_{size}.jpg"
    return thumbs_dir / f"sf{source_file_id}_{size}.jpg"


def ensure_thumbnail(
    source: Path,
    destination: Path,
    *,
    size: int = 256,
    orientation: int | None = None,
) -> Path | None:
    """Build a square JPEG thumbnail at ``destination``. Returns None on failure."""

    _ = orientation
    if destination.is_file() and destination.stat().st_size > 0:
        return destination
    image = _open_preview(source)
    if image is None:
        return None
    try:
        transposed = ImageOps.exif_transpose(image)
        working = transposed if transposed is not None else image
        fitted = _fit_square(working, size)
        destination.parent.mkdir(parents=True, exist_ok=True)
        fitted.save(destination, format="JPEG", quality=85, optimize=True)
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError) as exc:
        logger.warning("Thumbnail failed for %s: %s", source.name, exc)
        return None
    finally:
        image.close()
    return destination if destination.is_file() else None


def render_thumbnail_batch(jobs: tuple[ThumbnailJob, ...]) -> list[tuple[str, str, bool]]:
    """Module-level pool entry: write thumbnails for a chunk of jobs."""

    results: list[tuple[str, str, bool]] = []
    for job in jobs:
        written = ensure_thumbnail(Path(job.source), Path(job.destination), size=job.size)
        results.append((job.source, job.destination, written is not None))
    return results


def generate_project_thumbnails(
    session: Session,
    project: Project,
    thumbs_dir: Path,
    *,
    size: int = 256,
    progress: ProgressFn | None = None,
    max_workers: int | None = None,
) -> ThumbnailResult:
    """Create missing thumbnails for photo source files. Originals are read-only."""

    thumbs_dir.mkdir(parents=True, exist_ok=True)
    rows = list(
        session.scalars(
            select(SourceFile).where(
                SourceFile.project_id == project.id,
                SourceFile.file_kind == FileKind.PHOTO.value,
            )
        )
    )
    result = ThumbnailResult()
    jobs: list[ThumbnailJob] = []
    queued_dests: set[str] = set()
    for row in rows:
        dest = cached_thumbnail_path(
            thumbs_dir,
            source_file_id=row.id,
            sha256=row.sha256,
            size=size,
        )
        dest_key = str(dest)
        if dest.is_file() and dest.stat().st_size > 0:
            result.skipped += 1
            continue
        if dest_key in queued_dests:
            result.skipped += 1
            continue
        queued_dests.add(dest_key)
        jobs.append(ThumbnailJob(source=row.path, destination=dest_key, size=size))

    total = max(len(rows), 1)
    done = result.skipped

    def on_progress(completed: int, _job_total: int) -> None:
        if progress is None:
            return
        current = min(done + completed, total)
        path = jobs[min(completed, len(jobs)) - 1].source if jobs and completed else ""
        progress(current, total, path)

    if not jobs:
        if progress is not None:
            progress(total, total, "")
        return result

    outcomes = map_in_threads(
        render_thumbnail_batch,
        jobs,
        max_workers=max_workers,
        progress=on_progress,
    )
    for _source, _destination, ok in outcomes:
        if ok:
            result.written += 1
        else:
            result.failed += 1
    return result


def ensure_photo_and_video_rows(session: Session, project: Project) -> None:
    """Create ``photos`` / ``videos`` rows for indexed media if they are missing."""

    photo_ids = set(session.scalars(select(Photo.source_file_id)))
    video_ids = set(session.scalars(select(Video.source_file_id)))
    rows = session.scalars(select(SourceFile).where(SourceFile.project_id == project.id))
    for row in rows:
        if row.file_kind == FileKind.PHOTO.value and row.id not in photo_ids:
            session.add(
                Photo(
                    source_file_id=row.id,
                    is_favorite=False,
                    used_in_journal=False,
                    is_cover=False,
                    origin="auto",
                )
            )
        elif row.file_kind == FileKind.VIDEO.value and row.id not in video_ids:
            session.add(Video(source_file_id=row.id, origin="auto"))
    session.flush()


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


def _open_preview(source: Path) -> Image.Image | None:
    suffix = source.suffix.lower()
    try:
        if suffix in _PILLOW_SUFFIXES:
            image = Image.open(source)
            width, height = image.size
            if width * height > _MAX_THUMB_SOURCE_PIXELS:
                logger.warning(
                    "Thumbnail skipped, image too large: %s (%sx%s)",
                    source.name,
                    width,
                    height,
                )
                image.close()
                return None
            return image
        if suffix in _HEIC_SUFFIXES:
            windows = decode_heic_preview(source, size=256)
            if windows is not None:
                return windows
            payload = source.read_bytes()
            embedded = extract_heif_jpeg_item(payload) or extract_largest_embedded_jpeg(payload)
            if embedded is not None:
                image = Image.open(io.BytesIO(embedded))
                return image
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        logger.debug("No preview image for %s", source.name)
        return None
    return None


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
