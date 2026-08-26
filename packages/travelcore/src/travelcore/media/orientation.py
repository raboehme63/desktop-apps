"""Display rotation on top of EXIF orientation. Original files are never written."""

from __future__ import annotations

from PIL import Image, ImageOps

from travelcore.media.types import GPS_EXTENSIONS, PHOTO_EXTENSIONS, VIDEO_EXTENSIONS

_CLOCKWISE = {
    90: Image.Transpose.ROTATE_270,
    180: Image.Transpose.ROTATE_180,
    270: Image.Transpose.ROTATE_90,
}


def normalize_rotation_degrees(value: int | None) -> int:
    """Snap to 0/90/180/270 clockwise degrees."""

    if value is None:
        return 0
    return ((int(value) % 360 + 45) // 90 % 4) * 90


def can_rotate_media(extension: str) -> bool:
    suffix = extension.lower()
    if suffix in GPS_EXTENSIONS:
        return False
    return suffix in PHOTO_EXTENSIONS | VIDEO_EXTENSIONS


def apply_display_rotation(image: Image.Image, degrees: int | None) -> Image.Image:
    """Rotate clockwise after EXIF transpose. 0 leaves the image unchanged."""

    snapped = normalize_rotation_degrees(degrees)
    op = _CLOCKWISE.get(snapped)
    if op is None:
        return image
    return image.transpose(op)


def orient_image(image: Image.Image, *, rotation_degrees: int | None = 0) -> Image.Image:
    """Apply camera EXIF orientation, then the user display rotation."""

    transposed = ImageOps.exif_transpose(image)
    working = transposed if transposed is not None else image
    return apply_display_rotation(working, rotation_degrees)
