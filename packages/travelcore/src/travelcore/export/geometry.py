"""Frame and crop math for Travelbook photo elements.

Coordinates:
- ``frame`` is percent of a single page (0–100).
- ``crop.scale`` is relative to CSS-cover (1.0 fills the frame; below 1 shows margins).
- ``crop.pan_x`` / ``pan_y`` are −1…1 (0 = centered, −1 = left/top).
- ``crop.angle`` is clockwise degrees inside the frame.

Preview and export share these functions; only the pixel size of the page
and of the source image change.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

_MIN_SCALE = 0.2
_MAX_SCALE = 8.0
_MIN_FRAME_PCT = 6.0


@dataclass(frozen=True, slots=True)
class Frame:
    """Photo frame on the page, in percent (0–100)."""

    x: float
    y: float
    w: float
    h: float


@dataclass(frozen=True, slots=True)
class Crop:
    """Zoom, pan, and rotation of the image inside its frame."""

    scale: float = 1.0
    pan_x: float = 0.0
    pan_y: float = 0.0
    angle: float = 0.0


def clamp_pan(value: float) -> float:
    return max(-1.0, min(1.0, float(value)))


def clamp_scale(value: float) -> float:
    return max(_MIN_SCALE, min(_MAX_SCALE, float(value)))


def clamp_angle(value: float) -> float:
    """Normalize to (−180, 180]."""

    angle = float(value) % 360.0
    if angle > 180.0:
        angle -= 360.0
    if angle <= -180.0:
        angle += 360.0
    return angle


def clamp_crop(crop: Crop) -> Crop:
    return Crop(
        scale=clamp_scale(crop.scale),
        pan_x=clamp_pan(crop.pan_x),
        pan_y=clamp_pan(crop.pan_y),
        angle=clamp_angle(crop.angle),
    )


def clamp_frame(frame: Frame, *, gutter_side: str | None = None) -> Frame:
    """Keep the frame on the page, or allow overflow only toward the spread gutter.

    ``gutter_side`` is the inner edge of the owning page: ``right`` (verso) or
    ``left`` (recto). At least ``_MIN_FRAME_PCT`` stays on the owning page.
    """

    height = max(_MIN_FRAME_PCT, min(100.0, float(frame.h)))
    y = max(0.0, min(100.0 - height, float(frame.y)))
    if gutter_side not in {"left", "right"}:
        width = max(_MIN_FRAME_PCT, min(100.0, float(frame.w)))
        x = max(0.0, min(100.0 - width, float(frame.x)))
        return Frame(x=x, y=y, w=width, h=height)
    width = max(_MIN_FRAME_PCT, min(200.0, float(frame.w)))
    x = float(frame.x)
    if gutter_side == "right":
        x = max(0.0, min(100.0 - _MIN_FRAME_PCT, x))
        width = min(max(_MIN_FRAME_PCT, width), 200.0 - x)
        return Frame(x=x, y=y, w=width, h=height)
    right = min(100.0, max(x + width, _MIN_FRAME_PCT))
    x = max(-100.0, right - width)
    width = max(_MIN_FRAME_PCT, right - x)
    if x + width > 100.0:
        width = 100.0 - x
    return Frame(x=x, y=y, w=width, h=height)


def clamp_stored_frame(frame: Frame) -> Frame:
    """Preserve gutter overflow already stored on a page."""

    if frame.x < -1e-9:
        return clamp_frame(frame, gutter_side="left")
    if frame.x + frame.w > 100.0 + 1e-9:
        return clamp_frame(frame, gutter_side="right")
    return clamp_frame(frame)


def cover_scale(image_width: float, image_height: float, frame_width: float, frame_height: float) -> float:
    """Minimum scale that makes the image cover the frame (CSS ``object-fit: cover``)."""

    if image_width <= 0 or image_height <= 0 or frame_width <= 0 or frame_height <= 0:
        return 1.0
    return max(frame_width / image_width, frame_height / image_height)


def frame_pixels(page_width: float, page_height: float, frame: Frame) -> tuple[float, float, float, float]:
    """Return ``(left, top, width, height)`` in page pixels."""

    return (
        page_width * frame.x / 100.0,
        page_height * frame.y / 100.0,
        page_width * frame.w / 100.0,
        page_height * frame.h / 100.0,
    )


def pixels_to_frame(
    page_width: float,
    page_height: float,
    left: float,
    top: float,
    width: float,
    height: float,
    *,
    gutter_side: str | None = None,
) -> Frame:
    if page_width <= 0 or page_height <= 0:
        return Frame(0.0, 0.0, 100.0, 100.0)
    return clamp_frame(
        Frame(
            x=100.0 * left / page_width,
            y=100.0 * top / page_height,
            w=100.0 * width / page_width,
            h=100.0 * height / page_height,
        ),
        gutter_side=gutter_side,
    )


def source_rect(
    image_width: float,
    image_height: float,
    frame_width: float,
    frame_height: float,
    crop: Crop,
) -> tuple[float, float, float, float]:
    """Rectangle in source-image pixels that fills the frame.

    Returns ``(x, y, width, height)``. Degenerate sizes yield the full image.
    """

    if image_width <= 0 or image_height <= 0 or frame_width <= 0 or frame_height <= 0:
        return (0.0, 0.0, max(image_width, 0.0), max(image_height, 0.0))
    box_w, box_h = rotated_frame_size(frame_width, frame_height, crop.angle)
    zoom = cover_scale(image_width, image_height, box_w, box_h) * clamp_scale(crop.scale)
    if zoom <= 0:
        return (0.0, 0.0, image_width, image_height)
    src_w = box_w / zoom
    src_h = box_h / zoom
    overflow_x = image_width - src_w
    overflow_y = image_height - src_h
    src_x = overflow_x * (clamp_pan(crop.pan_x) + 1.0) / 2.0
    src_y = overflow_y * (clamp_pan(crop.pan_y) + 1.0) / 2.0
    src_x = max(0.0, min(max(image_width - src_w, 0.0), src_x))
    src_y = max(0.0, min(max(image_height - src_h, 0.0), src_y))
    src_w = min(src_w, image_width)
    src_h = min(src_h, image_height)
    return (src_x, src_y, src_w, src_h)


def contain_fit(
    image_width: float, image_height: float, box_width: float, box_height: float
) -> tuple[float, float, float, float]:
    """Place the image inside ``box`` like CSS ``object-fit: contain`` / PIL ``thumbnail``.

    Returns ``(offset_x, offset_y, content_width, content_height)``.
    """

    if image_width <= 0 or image_height <= 0 or box_width <= 0 or box_height <= 0:
        return (0.0, 0.0, max(box_width, 0.0), max(box_height, 0.0))
    scale = min(box_width / image_width, box_height / image_height)
    content_w = image_width * scale
    content_h = image_height * scale
    return ((box_width - content_w) / 2.0, (box_height - content_h) / 2.0, content_w, content_h)


def map_rect_to_contained(
    image_width: float,
    image_height: float,
    box_width: float,
    box_height: float,
    x: float,
    y: float,
    width: float,
    height: float,
) -> tuple[float, float, float, float]:
    """Map a rectangle in image pixels onto a contain-fitted (letterboxed) box.

    Square crop windows stay square. Independent X/Y scales would stretch.
    """

    if image_width <= 0 or image_height <= 0:
        return (0.0, 0.0, max(box_width, 0.0), max(box_height, 0.0))
    scale = min(box_width / image_width, box_height / image_height)
    ox, oy, _cw, _ch = contain_fit(image_width, image_height, box_width, box_height)
    return (ox + x * scale, oy + y * scale, width * scale, height * scale)


def rotated_frame_size(frame_width: float, frame_height: float, angle_deg: float) -> tuple[float, float]:
    """Width/height of the axis-aligned frame after rotating the image by ``angle_deg``."""

    rad = math.radians(clamp_angle(angle_deg))
    cosine = abs(math.cos(rad))
    sine = abs(math.sin(rad))
    return (frame_width * cosine + frame_height * sine, frame_width * sine + frame_height * cosine)


def image_rect_in_rotated_frame(
    image_width: float,
    image_height: float,
    frame_width: float,
    frame_height: float,
    crop: Crop,
) -> tuple[float, float, float, float]:
    """Where the full image sits in rotated frame space (origin = frame centre)."""

    fitted = clamp_crop(crop)
    box_w, box_h = rotated_frame_size(frame_width, frame_height, fitted.angle)
    zoom = cover_scale(image_width, image_height, box_w, box_h) * fitted.scale
    disp_w = image_width * zoom
    disp_h = image_height * zoom
    left = -disp_w / 2.0 - fitted.pan_x * (disp_w - box_w) / 2.0
    top = -disp_h / 2.0 - fitted.pan_y * (disp_h - box_h) / 2.0
    return (left, top, disp_w, disp_h)


def affine_to_source(
    image_width: float,
    image_height: float,
    frame_width: float,
    frame_height: float,
    crop: Crop,
) -> tuple[float, float, float, float, float, float]:
    """Affine map from frame pixel ``(x, y)`` to source pixel ``(sx, sy)`` (PIL/Qt)."""

    fitted = clamp_crop(crop)
    left, top, disp_w, disp_h = image_rect_in_rotated_frame(
        image_width, image_height, frame_width, frame_height, fitted
    )
    if disp_w <= 0 or disp_h <= 0 or image_width <= 0 or image_height <= 0:
        return (1.0, 0.0, 0.0, 0.0, 1.0, 0.0)
    rad = math.radians(fitted.angle)
    cosine = math.cos(rad)
    sine = math.sin(rad)
    cx = frame_width / 2.0
    cy = frame_height / 2.0
    sx_scale = image_width / disp_w
    sy_scale = image_height / disp_h
    return (
        cosine * sx_scale,
        sine * sx_scale,
        (-cx * cosine - cy * sine - left) * sx_scale,
        -sine * sy_scale,
        cosine * sy_scale,
        (cx * sine - cy * cosine - top) * sy_scale,
    )


def pan_from_delta(
    image_width: float,
    image_height: float,
    frame_width: float,
    frame_height: float,
    crop: Crop,
    delta_x: float,
    delta_y: float,
) -> Crop:
    """Pan so the image follows a screen-space drag (y down, rotation clockwise)."""

    fitted = clamp_crop(crop)
    box_w, box_h = rotated_frame_size(frame_width, frame_height, fitted.angle)
    _left, _top, disp_w, disp_h = image_rect_in_rotated_frame(
        image_width, image_height, frame_width, frame_height, fitted
    )
    rad = math.radians(fitted.angle)
    cosine = math.cos(rad)
    sine = math.sin(rad)
    rot_x = delta_x * cosine + delta_y * sine
    rot_y = -delta_x * sine + delta_y * cosine
    overflow_x = disp_w - box_w
    overflow_y = disp_h - box_h
    pan_x = fitted.pan_x
    pan_y = fitted.pan_y
    if abs(overflow_x) > 1e-9:
        pan_x = clamp_pan(fitted.pan_x - 2.0 * rot_x / overflow_x)
    if abs(overflow_y) > 1e-9:
        pan_y = clamp_pan(fitted.pan_y - 2.0 * rot_y / overflow_y)
    return Crop(scale=fitted.scale, pan_x=pan_x, pan_y=pan_y, angle=fitted.angle)


def zoom_keeping_point(
    image_width: float,
    image_height: float,
    frame_width: float,
    frame_height: float,
    crop: Crop,
    new_scale: float,
    frame_x: float,
    frame_y: float,
) -> Crop:
    """Zoom so the image point under ``(frame_x, frame_y)`` stays put."""

    fitted = clamp_crop(crop)
    rad = math.radians(fitted.angle)
    cosine = math.cos(rad)
    sine = math.sin(rad)
    u = frame_x - frame_width / 2.0
    v = frame_y - frame_height / 2.0
    rot_x = u * cosine + v * sine
    rot_y = -u * sine + v * cosine
    left, top, disp_w, disp_h = image_rect_in_rotated_frame(
        image_width, image_height, frame_width, frame_height, fitted
    )
    rel_x = 0.5 if disp_w <= 0 else (rot_x - left) / disp_w
    rel_y = 0.5 if disp_h <= 0 else (rot_y - top) / disp_h
    zoomed = clamp_crop(Crop(scale=new_scale, pan_x=0.0, pan_y=0.0, angle=fitted.angle))
    box_w, box_h = rotated_frame_size(frame_width, frame_height, fitted.angle)
    _l2, _t2, dw, dh = image_rect_in_rotated_frame(
        image_width, image_height, frame_width, frame_height, zoomed
    )
    overflow_x = dw - box_w
    overflow_y = dh - box_h
    pan_x = 0.0
    pan_y = 0.0
    if abs(overflow_x) > 1e-9:
        pan_x = clamp_pan(-2.0 * (rot_x - rel_x * dw + dw / 2.0) / overflow_x)
    if abs(overflow_y) > 1e-9:
        pan_y = clamp_pan(-2.0 * (rot_y - rel_y * dh + dh / 2.0) / overflow_y)
    return Crop(scale=zoomed.scale, pan_x=pan_x, pan_y=pan_y, angle=fitted.angle)


def pan_from_source(
    image_width: float,
    image_height: float,
    frame_width: float,
    frame_height: float,
    scale: float,
    source_x: float,
    source_y: float,
) -> tuple[float, float]:
    """Inverse of ``source_rect`` pan: given a source origin, return pan_x/pan_y."""

    zoom = cover_scale(image_width, image_height, frame_width, frame_height) * clamp_scale(scale)
    if zoom <= 0:
        return (0.0, 0.0)
    src_w = min(frame_width / zoom, image_width)
    src_h = min(frame_height / zoom, image_height)
    overflow_x = image_width - src_w
    overflow_y = image_height - src_h
    pan_x = 0.0 if overflow_x <= 1e-9 else (2.0 * source_x / overflow_x) - 1.0
    pan_y = 0.0 if overflow_y <= 1e-9 else (2.0 * source_y / overflow_y) - 1.0
    return (clamp_pan(pan_x), clamp_pan(pan_y))
