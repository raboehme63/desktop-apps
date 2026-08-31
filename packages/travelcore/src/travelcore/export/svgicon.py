"""Rasterize simple SVG icons (bundled 4×3 flags) with Pillow.

travelcore stays Qt-free; flag-icons paths are rects, lines, cubics, and arcs.
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw

_TOKEN = re.compile(r"[MmLlHhVvCcSsQqTtAaZz]|[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?")
_NUM = re.compile(r"[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?")
_NAMED = {
    "none": None,
    "transparent": None,
    "red": (255, 0, 0, 255),
    "white": (255, 255, 255, 255),
    "black": (0, 0, 0, 255),
    "navy": (0, 0, 128, 255),
    "blue": (0, 0, 255, 255),
    "green": (0, 128, 0, 255),
    "gold": (255, 215, 0, 255),
    "yellow": (255, 255, 0, 255),
}


def rasterize_svg(path: Path, width: int, height: int) -> Image.Image:
    """Return an RGBA image. Degenerate sizes yield a transparent pixel."""

    width = max(1, int(width))
    height = max(1, int(height))
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    if not Path(path).is_file():
        return canvas
    try:
        root = ET.fromstring(Path(path).read_text(encoding="utf-8"))
    except ET.ParseError:
        return canvas
    view = _view_box(root)
    sx = width / max(view[2], 1e-9)
    sy = height / max(view[3], 1e-9)
    draw = ImageDraw.Draw(canvas, "RGBA")
    state = _Style(fill=(0, 0, 0, 255), stroke=None, stroke_width=1.0, evenodd=False)
    try:
        _paint_node(draw, root, view, sx, sy, state, _identity())
    except (ValueError, ZeroDivisionError, IndexError):
        return canvas
    return canvas


@lru_cache(maxsize=64)
def rasterize_flag(path: Path, width: int, height: int) -> Image.Image:
    return rasterize_svg(path, width, height)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _view_box(root: ET.Element) -> tuple[float, float, float, float]:
    raw = root.get("viewBox") or root.get("viewbox")
    if raw:
        parts = _NUM.findall(raw)
        if len(parts) == 4:
            return (float(parts[0]), float(parts[1]), float(parts[2]), float(parts[3]))
    width = float(root.get("width") or 640)
    height = float(root.get("height") or 480)
    return (0.0, 0.0, width, height)


class _Style:
    __slots__ = ("fill", "stroke", "stroke_width", "evenodd")

    def __init__(
        self,
        fill: tuple[int, int, int, int] | None,
        stroke: tuple[int, int, int, int] | None,
        stroke_width: float,
        evenodd: bool,
    ) -> None:
        self.fill = fill
        self.stroke = stroke
        self.stroke_width = stroke_width
        self.evenodd = evenodd

    def child(self, element: ET.Element) -> _Style:
        fill = self.fill if element.get("fill") is None else _color(element.get("fill"))
        stroke = self.stroke if element.get("stroke") is None else _color(element.get("stroke"))
        width = _length(element.get("stroke-width"), self.stroke_width)
        evenodd = self.evenodd or element.get("fill-rule") == "evenodd"
        return _Style(fill, stroke, width, evenodd)


def _identity() -> tuple[float, float, float, float, float, float]:
    return (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _mul(
    a: tuple[float, float, float, float, float, float],
    b: tuple[float, float, float, float, float, float],
) -> tuple[float, float, float, float, float, float]:
    return (
        a[0] * b[0] + a[2] * b[1],
        a[1] * b[0] + a[3] * b[1],
        a[0] * b[2] + a[2] * b[3],
        a[1] * b[2] + a[3] * b[3],
        a[0] * b[4] + a[2] * b[5] + a[4],
        a[1] * b[4] + a[3] * b[5] + a[5],
    )


def _apply(
    matrix: tuple[float, float, float, float, float, float], x: float, y: float
) -> tuple[float, float]:
    return (matrix[0] * x + matrix[2] * y + matrix[4], matrix[1] * x + matrix[3] * y + matrix[5])


def _parse_transform(value: str | None) -> tuple[float, float, float, float, float, float]:
    matrix = _identity()
    if not value:
        return matrix
    for kind, args in re.findall(r"([a-zA-Z]+)\(([^)]*)\)", value):
        nums = [float(item) for item in _NUM.findall(args)]
        name = kind.lower()
        extra = _identity()
        if name == "matrix" and len(nums) >= 6:
            extra = (nums[0], nums[1], nums[2], nums[3], nums[4], nums[5])
        elif name == "translate":
            extra = (1.0, 0.0, 0.0, 1.0, nums[0] if nums else 0.0, nums[1] if len(nums) > 1 else 0.0)
        elif name == "scale":
            sx = nums[0] if nums else 1.0
            extra = (sx, 0.0, 0.0, nums[1] if len(nums) > 1 else sx, 0.0, 0.0)
        matrix = _mul(matrix, extra)
    return matrix


def _length(value: str | None, default: float) -> float:
    if value is None:
        return default
    match = _NUM.search(value)
    return float(match.group(0)) if match else default


def _color(value: str | None) -> tuple[int, int, int, int] | None:
    if value is None:
        return (0, 0, 0, 255)
    raw = value.strip().lower()
    if raw in _NAMED:
        return _NAMED[raw]
    if raw.startswith("url("):
        return None
    if raw.startswith("#"):
        hex_value = raw[1:]
        if len(hex_value) == 3:
            hex_value = "".join(ch * 2 for ch in hex_value)
        if len(hex_value) >= 6:
            return (int(hex_value[0:2], 16), int(hex_value[2:4], 16), int(hex_value[4:6], 16), 255)
    return (0, 0, 0, 255)


def _paint_node(
    draw: ImageDraw.ImageDraw,
    element: ET.Element,
    view: tuple[float, float, float, float],
    sx: float,
    sy: float,
    style: _Style,
    matrix: tuple[float, float, float, float, float, float],
) -> None:
    name = _local(element.tag)
    if name in {"defs", "clippath", "marker", "lineargradient", "radialgradient"}:
        return
    style = style.child(element)
    matrix = _mul(matrix, _parse_transform(element.get("transform")))
    if name == "path":
        _draw_path(draw, element.get("d") or "", view, sx, sy, style, matrix)
    elif name == "rect":
        x = _length(element.get("x"), 0.0)
        y = _length(element.get("y"), 0.0)
        width = _length(element.get("width"), 0.0)
        height = _length(element.get("height"), 0.0)
        _draw_path(draw, f"M{x} {y}h{width}v{height}h{-width}z", view, sx, sy, style, matrix)
    elif name == "circle":
        cx = _length(element.get("cx"), 0.0)
        cy = _length(element.get("cy"), 0.0)
        radius = _length(element.get("r"), 0.0)
        _draw_ellipse(draw, cx, cy, radius, radius, view, sx, sy, style, matrix)
    elif name == "ellipse":
        cx = _length(element.get("cx"), 0.0)
        cy = _length(element.get("cy"), 0.0)
        _draw_ellipse(
            draw,
            cx,
            cy,
            _length(element.get("rx"), 0.0),
            _length(element.get("ry"), 0.0),
            view,
            sx,
            sy,
            style,
            matrix,
        )
    for child in element:
        _paint_node(draw, child, view, sx, sy, style, matrix)


def _map_point(
    x: float,
    y: float,
    view: tuple[float, float, float, float],
    sx: float,
    sy: float,
    matrix: tuple[float, float, float, float, float, float],
) -> tuple[float, float]:
    px, py = _apply(matrix, x, y)
    return ((px - view[0]) * sx, (py - view[1]) * sy)


def _draw_ellipse(
    draw: ImageDraw.ImageDraw,
    cx: float,
    cy: float,
    rx: float,
    ry: float,
    view: tuple[float, float, float, float],
    sx: float,
    sy: float,
    style: _Style,
    matrix: tuple[float, float, float, float, float, float],
) -> None:
    if rx <= 0 or ry <= 0:
        return
    points = []
    for index in range(32):
        angle = 2 * math.pi * index / 32
        points.append(_map_point(cx + math.cos(angle) * rx, cy + math.sin(angle) * ry, view, sx, sy, matrix))
    _stroke_fill(draw, [points], style)


def _draw_path(
    draw: ImageDraw.ImageDraw,
    data: str,
    view: tuple[float, float, float, float],
    sx: float,
    sy: float,
    style: _Style,
    matrix: tuple[float, float, float, float, float, float],
) -> None:
    rings = _flatten_path(data)
    mapped = [[_map_point(x, y, view, sx, sy, matrix) for x, y in ring] for ring in rings if len(ring) >= 2]
    _stroke_fill(draw, mapped, style)


def _stroke_fill(
    draw: ImageDraw.ImageDraw,
    rings: list[list[tuple[float, float]]],
    style: _Style,
) -> None:
    for ring in rings:
        if style.fill is not None and len(ring) >= 3:
            draw.polygon(ring, fill=style.fill)
        if style.stroke is not None and style.stroke_width > 0 and len(ring) >= 2:
            width = max(1, round(style.stroke_width))
            draw.line(ring, fill=style.stroke, width=width, joint="curve")


def _flatten_path(data: str) -> list[list[tuple[float, float]]]:
    tokens = _TOKEN.findall(data.replace(",", " "))
    rings: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    x = y = 0.0
    start = (0.0, 0.0)
    last_c = (0.0, 0.0)
    last_q = (0.0, 0.0)
    command = "M"
    index = 0

    def take(count: int) -> list[float]:
        nonlocal index
        values = [float(tokens[index + offset]) for offset in range(count)]
        index += count
        return values

    def add(px: float, py: float) -> None:
        nonlocal x, y
        x, y = px, py
        current.append((x, y))

    while index < len(tokens):
        token = tokens[index]
        if token.isalpha():
            command = token
            index += 1
            if command in "Zz":
                add(*start)
                if current:
                    rings.append(current)
                current = []
            continue
        if command in "Mm":
            if current:
                rings.append(current)
                current = []
            nx, ny = take(2)
            if command == "m":
                nx, ny = x + nx, y + ny
            add(nx, ny)
            start = (x, y)
            command = "l" if command == "m" else "L"
        elif command in "Ll":
            nx, ny = take(2)
            if command == "l":
                nx, ny = x + nx, y + ny
            add(nx, ny)
        elif command in "Hh":
            nx = take(1)[0]
            add(x + nx if command == "h" else nx, y)
        elif command in "Vv":
            ny = take(1)[0]
            add(x, y + ny if command == "v" else ny)
        elif command in "Cc":
            nums = take(6)
            if command == "c":
                nums = [x + nums[0], y + nums[1], x + nums[2], y + nums[3], x + nums[4], y + nums[5]]
            _cubic(current, x, y, nums)
            last_c = (nums[2], nums[3])
            add(nums[4], nums[5])
        elif command in "Ss":
            nums = take(4)
            if command == "s":
                nums = [x + nums[0], y + nums[1], x + nums[2], y + nums[3]]
            cx1, cy1 = 2 * x - last_c[0], 2 * y - last_c[1]
            _cubic(current, x, y, [cx1, cy1, nums[0], nums[1], nums[2], nums[3]])
            last_c = (nums[0], nums[1])
            add(nums[2], nums[3])
        elif command in "Qq":
            nums = take(4)
            if command == "q":
                nums = [x + nums[0], y + nums[1], x + nums[2], y + nums[3]]
            _quad(current, x, y, nums)
            last_q = (nums[0], nums[1])
            add(nums[2], nums[3])
        elif command in "Tt":
            nums = take(2)
            if command == "t":
                nums = [x + nums[0], y + nums[1]]
            cx, cy = 2 * x - last_q[0], 2 * y - last_q[1]
            _quad(current, x, y, [cx, cy, nums[0], nums[1]])
            last_q = (cx, cy)
            add(nums[0], nums[1])
        elif command in "Aa":
            nums = take(7)
            end = (x + nums[5], y + nums[6]) if command == "a" else (nums[5], nums[6])
            _arc(current, x, y, nums[0], nums[1], nums[2], nums[3], nums[4], end[0], end[1])
            add(*end)
        else:
            index += 1
        if command not in "CcSs":
            last_c = (x, y)
        if command not in "QqTt":
            last_q = (x, y)
    if current:
        rings.append(current)
    return rings


def _cubic(points: list[tuple[float, float]], x: float, y: float, nums: list[float]) -> None:
    for step in range(1, 8):
        t = step / 8
        u = 1 - t
        px = u**3 * x + 3 * u**2 * t * nums[0] + 3 * u * t**2 * nums[2] + t**3 * nums[4]
        py = u**3 * y + 3 * u**2 * t * nums[1] + 3 * u * t**2 * nums[3] + t**3 * nums[5]
        points.append((px, py))


def _quad(points: list[tuple[float, float]], x: float, y: float, nums: list[float]) -> None:
    for step in range(1, 8):
        t = step / 8
        u = 1 - t
        px = u**2 * x + 2 * u * t * nums[0] + t**2 * nums[2]
        py = u**2 * y + 2 * u * t * nums[1] + t**2 * nums[3]
        points.append((px, py))


def _arc(
    points: list[tuple[float, float]],
    x1: float,
    y1: float,
    rx: float,
    ry: float,
    rotation: float,
    large: float,
    sweep: float,
    x2: float,
    y2: float,
) -> None:
    rx = abs(rx)
    ry = abs(ry)
    if rx < 1e-9 or ry < 1e-9:
        return
    phi = math.radians(rotation)
    cos_a = math.cos(phi)
    sin_a = math.sin(phi)
    dx = (x1 - x2) / 2
    dy = (y1 - y2) / 2
    x1p = cos_a * dx + sin_a * dy
    y1p = -sin_a * dx + cos_a * dy
    lam = (x1p**2) / (rx**2) + (y1p**2) / (ry**2)
    if lam > 1:
        scale = math.sqrt(lam)
        rx *= scale
        ry *= scale
    sign = -1 if large == sweep else 1
    num = rx**2 * ry**2 - rx**2 * y1p**2 - ry**2 * x1p**2
    den = rx**2 * y1p**2 + ry**2 * x1p**2
    coef = sign * math.sqrt(max(num / den, 0.0)) if den else 0.0
    cxp = coef * rx * y1p / ry
    cyp = -coef * ry * x1p / rx
    cx = cos_a * cxp - sin_a * cyp + (x1 + x2) / 2
    cy = sin_a * cxp + cos_a * cyp + (y1 + y2) / 2

    def angle(ux: float, uy: float, vx: float, vy: float) -> float:
        dot = ux * vx + uy * vy
        det = ux * vy - uy * vx
        denom = math.hypot(ux, uy) * math.hypot(vx, vy)
        return math.copysign(math.acos(max(-1.0, min(1.0, dot / denom))), det)

    theta1 = angle(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    delta = angle((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry)
    if sweep == 0 and delta > 0:
        delta -= 2 * math.pi
    elif sweep != 0 and delta < 0:
        delta += 2 * math.pi
    steps = max(8, int(abs(delta) / (math.pi / 8)))
    for step in range(1, steps):
        t = theta1 + delta * step / steps
        px = cx + rx * math.cos(t) * cos_a - ry * math.sin(t) * sin_a
        py = cy + rx * math.cos(t) * sin_a + ry * math.sin(t) * cos_a
        points.append((px, py))
