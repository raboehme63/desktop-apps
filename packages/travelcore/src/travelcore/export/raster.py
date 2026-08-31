"""Rasterize a photo page at print resolution.

Preview paints thumbnails in Qt; this module opens originals with Pillow and
uses the same ``source_rect`` math. Original files are never written.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from travelcore.export.document import PhotoElement, sorted_by_z
from travelcore.export.geometry import affine_to_source, frame_pixels
from travelcore.media.orientation import orient_image

DEFAULT_DPI = 300
_MM_PER_INCH = 25.4
_PAGE_BG = (247, 244, 238)
_PLACEHOLDER = (217, 211, 199)


def page_pixels(width_mm: float, height_mm: float, dpi: float = DEFAULT_DPI) -> tuple[int, int]:
    """Convert page millimetres to integer pixels at ``dpi``."""

    return (
        max(1, round(float(width_mm) / _MM_PER_INCH * dpi)),
        max(1, round(float(height_mm) / _MM_PER_INCH * dpi)),
    )


def render_photo_page(
    elements: Sequence[PhotoElement],
    sources: Mapping[int, Path],
    page_width: int,
    page_height: int,
    *,
    background: tuple[int, int, int] = _PAGE_BG,
    rotation_degrees: Mapping[int, int] | None = None,
) -> Image.Image:
    """Composite photo elements onto an RGB page. Later ``z`` paints on top."""

    width = max(1, int(page_width))
    height = max(1, int(page_height))
    canvas = Image.new("RGB", (width, height), background)
    rotations = rotation_degrees or {}
    for element in sorted_by_z(elements):
        dest = _visible_box(width, height, element)
        if dest is None:
            continue
        dx, dy, dw, dh, full_w, full_h, crop_x, crop_y = dest
        image = _open_source(sources.get(element.source_file_id), rotations.get(element.source_file_id, 0))
        if image is None:
            canvas.paste(Image.new("RGB", (dw, dh), _PLACEHOLDER), (dx, dy))
            continue
        try:
            fitted = _fit_element(image, element, full_w, full_h)
            piece = fitted.crop((crop_x, crop_y, crop_x + dw, crop_y + dh))
            overlay = piece if piece.mode == "RGBA" else piece.convert("RGBA")
            canvas.paste(overlay, (dx, dy), overlay)
            if overlay is not piece:
                overlay.close()
            piece.close()
            fitted.close()
        finally:
            image.close()
    return canvas


def _visible_box(
    page_width: int, page_height: int, element: PhotoElement
) -> tuple[int, int, int, int, int, int, int, int] | None:
    """Page intersection of a frame that may extend past the gutter.

    Returns ``(dx, dy, dw, dh, full_w, full_h, crop_x, crop_y)``.
    """

    left, top, frame_w, frame_h = frame_pixels(page_width, page_height, element.frame)
    full_w = max(1, int(round(frame_w)))
    full_h = max(1, int(round(frame_h)))
    ix0 = max(0.0, left)
    iy0 = max(0.0, top)
    ix1 = min(float(page_width), left + frame_w)
    iy1 = min(float(page_height), top + frame_h)
    if ix1 <= ix0 or iy1 <= iy0:
        return None
    dx = int(round(ix0))
    dy = int(round(iy0))
    dw = max(1, int(round(ix1)) - dx)
    dh = max(1, int(round(iy1)) - dy)
    if dx >= page_width or dy >= page_height or dw <= 0 or dh <= 0:
        return None
    dw = min(dw, page_width - dx)
    dh = min(dh, page_height - dy)
    crop_x = min(max(0, dx - int(round(left))), max(full_w - dw, 0))
    crop_y = min(max(0, dy - int(round(top))), max(full_h - dh, 0))
    return (dx, dy, dw, dh, full_w, full_h, crop_x, crop_y)


def _open_source(path: Path | None, degrees: int) -> Image.Image | None:
    if path is None or not Path(path).is_file():
        return None
    try:
        raw = Image.open(path)
    except (OSError, UnidentifiedImageError):
        return None
    try:
        rgba = raw.convert("RGBA")
    except OSError:
        raw.close()
        return None
    raw.close()
    return orient_image(rgba, rotation_degrees=degrees)


def _fit_element(image: Image.Image, element: PhotoElement, dest_w: int, dest_h: int) -> Image.Image:
    coeffs = affine_to_source(image.width, image.height, dest_w, dest_h, element.crop)
    resample = Image.Resampling.BICUBIC
    if image.mode != "RGBA":
        image = image.convert("RGBA")
    return image.transform((dest_w, dest_h), Image.Transform.AFFINE, coeffs, resample=resample)
