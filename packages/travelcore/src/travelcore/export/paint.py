"""Paint Travelbook pages at print resolution with Pillow.

Photo pages reuse ``raster.render_photo_page``. Cover, title, journal, intro and
the trip summary are drawn here so PDF export does not depend on Qt.
"""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError

from travelcore.export.book import (
    KIND_COVER,
    KIND_INTRO,
    KIND_JOURNAL,
    KIND_PHOTOS,
    KIND_SUMMARY_COUNTRIES,
    KIND_SUMMARY_MAP,
    KIND_TITLE,
    BookPage,
)
from travelcore.export.raster import render_photo_page
from travelcore.geo.catalog import country_label, outline_rings, resolve_countries
from travelcore.media.orientation import orient_image

PAGE_BG = (247, 244, 238)
PAGE_FG = (26, 39, 68)
PAGE_MUTED = (92, 107, 122)
NAVY_BG = (26, 39, 68)
NAVY_FG = (244, 247, 251)
NAVY_MUTED = (158, 201, 184)
ACCENT = (44, 154, 143)
SHAPE_FILL = (184, 193, 206)
SHAPE_SECTION = (139, 149, 165)
NOTES_BOX = (228, 223, 214)
SPAN_TRACK = (207, 200, 188)
PLACEHOLDER = (217, 211, 199)

_FONT_REGULAR = (
    Path(r"C:\Windows\Fonts\segoeui.ttf"),
    Path(r"C:\Windows\Fonts\arial.ttf"),
)
_FONT_BOLD = (
    Path(r"C:\Windows\Fonts\segoeuib.ttf"),
    Path(r"C:\Windows\Fonts\arialbd.ttf"),
)


def render_book_page(
    page: BookPage,
    sources: Mapping[int, Path],
    width: int,
    height: int,
    *,
    dpi: float,
    rotation_degrees: Mapping[int, int] | None = None,
) -> Image.Image:
    """Return an RGB page. Caller owns the image."""

    rotations = rotation_degrees or {}
    if page.kind == KIND_PHOTOS:
        canvas = render_photo_page(page.elements, sources, width, height, rotation_degrees=rotations)
    else:
        canvas = Image.new("RGB", (max(1, width), max(1, height)), PAGE_BG)
        draw = ImageDraw.Draw(canvas)
        if page.kind == KIND_COVER:
            _paint_cover(canvas, draw, page, sources, rotations, dpi)
        elif page.kind == KIND_TITLE:
            _paint_title(draw, page, width, height, dpi)
        elif page.kind == KIND_JOURNAL:
            _paint_journal(draw, page, width, height, dpi)
        elif page.kind == KIND_SUMMARY_COUNTRIES:
            _paint_summary_countries(canvas, draw, page, width, height, dpi)
        elif page.kind == KIND_SUMMARY_MAP:
            _paint_summary_map(canvas, draw, page, sources, rotations, width, height, dpi)
        elif page.kind == KIND_INTRO:
            _paint_intro(canvas, draw, page, sources, rotations, width, height, dpi)
    fill = NAVY_MUTED if page.kind == KIND_SUMMARY_COUNTRIES else PAGE_MUTED
    _paint_page_number(ImageDraw.Draw(canvas), page.number, canvas.width, canvas.height, dpi, fill=fill)
    return canvas


def encode_jpeg(
    image: Image.Image,
    *,
    quality: int = 88,
    subsampling: int | None = None,
) -> tuple[bytes, int, int]:
    rgb = image if image.mode == "RGB" else image.convert("RGB")
    buffer = BytesIO()
    options: dict[str, object] = {"format": "JPEG", "quality": int(quality), "optimize": True}
    if subsampling is not None:
        options["subsampling"] = subsampling
    rgb.save(buffer, **options)
    return buffer.getvalue(), rgb.width, rgb.height


def _pt(points: float, dpi: float) -> int:
    return max(8, round(points * dpi / 72.0))


@lru_cache(maxsize=8)
def _font_path(bold: bool) -> Path | None:
    for candidate in _FONT_BOLD if bold else _FONT_REGULAR:
        if candidate.is_file():
            return candidate
    return None


def _font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    path = _font_path(bold)
    if path is not None:
        return ImageFont.truetype(str(path), max(8, size))
    try:
        return ImageFont.load_default(max(8, size))
    except TypeError:
        return ImageFont.load_default()


def _text_width(font: ImageFont.ImageFont, text: str) -> int:
    if not text:
        return 0
    bbox = font.getbbox(text)
    return max(0, bbox[2] - bbox[0])


def _text_height(font: ImageFont.ImageFont) -> int:
    bbox = font.getbbox("Ag")
    return max(8, bbox[3] - bbox[1])


def _wrap(text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in (text or "").splitlines() or [""]:
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        current = words[0]
        for word in words[1:]:
            trial = f"{current} {word}"
            if _text_width(font, trial) <= max_width:
                current = trial
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


def _draw_wrapped(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    box: tuple[int, int, int, int],
    fill: tuple[int, int, int],
    *,
    align: str = "left",
    line_gap: float = 1.25,
) -> None:
    left, top, right, bottom = box
    width = max(1, right - left)
    lines = _wrap(text, font, width)
    line_h = round(_text_height(font) * line_gap)
    y = top
    for line in lines:
        if y + line_h > bottom:
            break
        x = left
        if align == "center":
            x = left + max(0, (width - _text_width(font, line)) // 2)
        draw.text((x, y), line, font=font, fill=fill)
        y += line_h


def _open_image(path: Path | None, degrees: int) -> Image.Image | None:
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


def _paste_cover(
    canvas: Image.Image,
    source: Image.Image,
    box: tuple[int, int, int, int],
) -> None:
    left, top, right, bottom = box
    width = max(1, right - left)
    height = max(1, bottom - top)
    fitted = ImageOps.fit(source.convert("RGB"), (width, height), method=Image.Resampling.BICUBIC)
    canvas.paste(fitted, (left, top))
    fitted.close()


def _paste_contain(
    canvas: Image.Image,
    source: Image.Image,
    box: tuple[int, int, int, int],
    background: tuple[int, int, int],
) -> None:
    left, top, right, bottom = box
    width = max(1, right - left)
    height = max(1, bottom - top)
    contained = ImageOps.contain(source.convert("RGB"), (width, height), method=Image.Resampling.BICUBIC)
    x = left + (width - contained.width) // 2
    y = top + (height - contained.height) // 2
    canvas.paste(Image.new("RGB", (width, height), background), (left, top))
    canvas.paste(contained, (x, y))
    contained.close()


def _paint_cover(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    page: BookPage,
    sources: Mapping[int, Path],
    rotations: Mapping[int, int],
    dpi: float,
) -> None:
    draw.rectangle((0, 0, canvas.width, canvas.height), fill=NAVY_BG)
    margin = round(canvas.width * 0.08)
    y = margin
    if page.year:
        badge = _font(_pt(11, dpi), bold=True)
        draw.text((margin, y), page.year, font=badge, fill=NAVY_MUTED)
        y += _text_height(badge) + _pt(8, dpi)
    title_font = _font(_pt(22, dpi), bold=True)
    title_bottom = y + round(canvas.height * 0.18)
    _draw_wrapped(
        draw,
        page.title or "REISE",
        title_font,
        (margin, y, canvas.width - margin, title_bottom),
        NAVY_FG,
        align="center",
    )
    photo_top = title_bottom + _pt(12, dpi)
    image = _open_image(sources.get(page.cover_id or -1), rotations.get(page.cover_id or -1, 0))
    box = (0, photo_top, canvas.width, canvas.height)
    if image is None:
        draw.rectangle(box, fill=(18, 21, 28))
        return
    try:
        _paste_cover(canvas, image, box)
    finally:
        image.close()


def _paint_title(
    draw: ImageDraw.ImageDraw,
    page: BookPage,
    width: int,
    height: int,
    dpi: float,
) -> None:
    font = _font(_pt(22, dpi), bold=True)
    margin = round(width * 0.12)
    _draw_wrapped(
        draw,
        page.title or "Reise",
        font,
        (margin, round(height * 0.35), width - margin, round(height * 0.65)),
        PAGE_FG,
        align="center",
    )


def _paint_journal(
    draw: ImageDraw.ImageDraw,
    page: BookPage,
    width: int,
    height: int,
    dpi: float,
) -> None:
    margin = round(width * 0.08)
    title_font = _font(_pt(16, dpi), bold=True)
    body_font = _font(_pt(11, dpi))
    heading = (page.title or "Tagebuch").strip().upper() or "TAGEBUCH"
    _draw_wrapped(
        draw,
        heading,
        title_font,
        (margin, margin, width - margin, margin + _pt(36, dpi)),
        PAGE_FG,
    )
    _draw_wrapped(
        draw,
        page.notes,
        body_font,
        (margin, margin + _pt(44, dpi), width - margin, height - round(height * 0.08)),
        PAGE_FG,
    )


def _paint_summary_countries(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    page: BookPage,
    width: int,
    height: int,
    dpi: float,
) -> None:
    split = round(width * 0.4)
    draw.rectangle((0, 0, split, height), fill=NAVY_BG)
    margin = round(width * 0.04)
    kicker = _font(_pt(10, dpi), bold=True)
    draw.text((margin, round(height * 0.05)), "LÄNDER", font=kicker, fill=NAVY_MUTED)
    countries = resolve_countries(page.countries)
    if not countries:
        empty = _font(_pt(11, dpi))
        draw.text((margin, round(height * 0.12)), "Keine Länder gewählt", font=empty, fill=NAVY_MUTED)
    else:
        slot = max(60, (height - round(height * 0.16)) // max(1, len(countries)))
        top = round(height * 0.12)
        for index, country in enumerate(countries):
            y0 = top + index * slot
            y1 = min(height - margin, y0 + slot - _pt(8, dpi))
            _draw_silhouette(
                draw,
                country.iso2,
                (margin, y0, split - margin, y0 + round((y1 - y0) * 0.62)),
                SHAPE_FILL,
            )
            name_font = _font(_pt(11, dpi), bold=True)
            label = country.name_de.upper()
            draw.text((margin, y0 + round((y1 - y0) * 0.66)), label, font=name_font, fill=NAVY_FG)
    heading = _font(_pt(10, dpi), bold=True)
    draw.text((split + margin, round(height * 0.05)), "REISEÜBERSICHT", font=heading, fill=PAGE_MUTED)
    value_font = _font(_pt(28, dpi), bold=True)
    label_font = _font(_pt(11, dpi))
    y = round(height * 0.14)
    for value, label in page.metrics:
        draw.text((split + margin, y), value, font=value_font, fill=PAGE_FG)
        y += _text_height(value_font) + _pt(4, dpi)
        draw.text((split + margin, y), label, font=label_font, fill=PAGE_MUTED)
        y += _text_height(label_font) + _pt(16, dpi)


def _paint_summary_map(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    page: BookPage,
    sources: Mapping[int, Path],
    rotations: Mapping[int, int],
    width: int,
    height: int,
    dpi: float,
) -> None:
    margin = round(width * 0.06)
    kicker = _font(_pt(10, dpi), bold=True)
    title = _font(_pt(16, dpi), bold=True)
    draw.text((margin, margin), "KARTE", font=kicker, fill=PAGE_MUTED)
    draw.text((margin, margin + _pt(16, dpi)), "Satellitenkarte", font=title, fill=PAGE_FG)
    box = (margin, margin + _pt(40, dpi), width - margin, height - round(height * 0.1))
    image = _open_image(sources.get(page.cover_id or -1), rotations.get(page.cover_id or -1, 0))
    if image is None:
        draw.rectangle(box, fill=PLACEHOLDER)
        return
    try:
        _paste_cover(canvas, image, box)
    finally:
        image.close()


def _paint_intro(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    page: BookPage,
    sources: Mapping[int, Path],
    rotations: Mapping[int, int],
    width: int,
    height: int,
    dpi: float,
) -> None:
    margin = round(width * 0.07)
    header_h = round(height * 0.28)
    split = round(width * 0.42)
    if page.country:
        _draw_silhouette(
            draw,
            page.country,
            (margin, margin, split, margin + header_h),
            SHAPE_SECTION,
            pin=(page.latitude, page.longitude),
        )
        name_font = _font(_pt(11, dpi), bold=True)
        draw.text(
            (margin, margin + header_h + _pt(4, dpi)),
            country_label(page.country).upper(),
            font=name_font,
            fill=PAGE_FG,
        )
    cover_box = (split + _pt(8, dpi), margin, width - margin, margin + header_h)
    image = _open_image(sources.get(page.cover_id or -1), rotations.get(page.cover_id or -1, 0))
    if image is None:
        draw.rectangle(cover_box, fill=PLACEHOLDER)
    else:
        try:
            _paste_contain(canvas, image, cover_box, PAGE_BG)
        finally:
            image.close()
    y = margin + header_h + _pt(28, dpi)
    title_font = _font(_pt(16, dpi), bold=True)
    date_font = _font(_pt(11, dpi))
    heading = (page.title or page.kicker or "Abschnitt").upper()
    _draw_wrapped(draw, heading, title_font, (margin, y, width - margin, y + _pt(40, dpi)), PAGE_FG)
    y += _pt(40, dpi)
    if page.dates:
        draw.text((margin, y), page.dates, font=date_font, fill=PAGE_MUTED)
        y += _text_height(date_font) + _pt(10, dpi)
    box_top = y
    box_bottom = height - round(height * 0.14)
    radius = max(6, _pt(4, dpi))
    draw.rounded_rectangle((margin, box_top, width - margin, box_bottom), radius=radius, fill=NOTES_BOX)
    if page.notes:
        _draw_wrapped(
            draw,
            page.notes,
            _font(_pt(11, dpi)),
            (
                margin + _pt(8, dpi),
                box_top + _pt(8, dpi),
                width - margin - _pt(8, dpi),
                box_bottom - _pt(8, dpi),
            ),
            PAGE_FG,
        )
    _paint_span_bar(
        draw,
        page.dates,
        page.span_start,
        page.span_end,
        (margin, height - round(height * 0.1), width - margin, height - round(height * 0.05)),
        dpi,
    )


def _paint_span_bar(
    draw: ImageDraw.ImageDraw,
    label: str,
    start: float,
    end: float,
    box: tuple[int, int, int, int],
    dpi: float,
) -> None:
    left, top, right, bottom = box
    width = max(1, right - left)
    mid_y = (top + bottom) // 2
    draw.line((left, mid_y, right, mid_y), fill=SPAN_TRACK, width=max(2, _pt(1.5, dpi)))
    x0 = left + round(max(0.0, min(1.0, start)) * width)
    x1 = left + round(max(start, min(1.0, end)) * width)
    x1 = max(x1, x0 + 4)
    draw.line((x0, mid_y, x1, mid_y), fill=ACCENT, width=max(3, _pt(2.2, dpi)))
    if not label:
        return
    font = _font(_pt(9, dpi), bold=True)
    pad = _pt(6, dpi)
    text_w = _text_width(font, label) + pad * 2
    text_h = _text_height(font) + pad
    badge_x = x0
    if badge_x + text_w > right:
        badge_x = max(left, right - text_w)
    badge_y = mid_y - text_h - 2
    if badge_y < top:
        badge_y = mid_y + 4
    draw.rounded_rectangle(
        (badge_x, badge_y, badge_x + text_w, badge_y + text_h),
        radius=max(4, pad // 2),
        fill=ACCENT,
    )
    draw.text((badge_x + pad, badge_y + pad // 2), label, font=font, fill=NAVY_FG)


def _draw_silhouette(
    draw: ImageDraw.ImageDraw,
    iso2: str,
    box: tuple[int, int, int, int],
    fill: tuple[int, int, int],
    pin: tuple[float | None, float | None] | None = None,
) -> None:
    rings = outline_rings(iso2)
    if not rings:
        return
    left, top, right, bottom = box
    width = max(1, right - left)
    height = max(1, bottom - top)
    xs = [point[0] for ring in rings for point in ring]
    ys = [point[1] for ring in rings for point in ring]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span_x = max(max_x - min_x, 1e-6)
    span_y = max(max_y - min_y, 1e-6)
    scale = min(width / span_x, height / span_y) * 0.92
    dx = left + (width - span_x * scale) / 2
    dy = top + (height - span_y * scale) / 2

    def project(x: float, y: float) -> tuple[int, int]:
        return (round(dx + (x - min_x) * scale), round(dy + (y - min_y) * scale))

    for ring in rings:
        if len(ring) < 3:
            continue
        draw.polygon([project(x, y) for x, y in ring], fill=fill)
    if pin is None or pin[0] is None or pin[1] is None:
        return
    latitude, longitude = pin
    px, py = project(longitude, -latitude)
    radius = max(3, min(width, height) * 0.035)
    draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=ACCENT, outline=(255, 255, 255))


def folio_outer_x(number: int, width: int, text_width: int, margin: int) -> int:
    """Travelbook numbers verso first (1–2/n): odd left, even right, both on the outer edge."""

    if number % 2:
        return margin
    return max(0, width - margin - text_width)


def _paint_page_number(
    draw: ImageDraw.ImageDraw,
    number: int | None,
    width: int,
    height: int,
    dpi: float,
    *,
    fill: tuple[int, int, int] = PAGE_MUTED,
) -> None:
    if number is None:
        return
    font = _font(_pt(9, dpi))
    text = str(number)
    tw = _text_width(font, text)
    margin = _pt(14, dpi)
    x = folio_outer_x(number, width, tw, margin)
    draw.text((x, height - margin), text, font=font, fill=fill)
