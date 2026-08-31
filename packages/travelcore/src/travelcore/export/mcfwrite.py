"""Write a classic CEWE ``.mcf`` plus ``Name_mcf-Dateien`` from Travelbook pages.

The XML shape follows the publicly documented ``<fotobook>`` album used by
open MCF readers: double-page bundles, ``area`` + ``position``, ``image`` /
``text``. No Creator binary is inspected. Product codes live in ``mcfproduct``.
"""

from __future__ import annotations

import html
import io
import re
import shutil
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

from PIL import Image, UnidentifiedImageError

from travelcore.exceptions import ExportError
from travelcore.export.book import (
    KIND_BLANK,
    KIND_COVER,
    KIND_INTRO,
    KIND_JOURNAL,
    KIND_PHOTOS,
    KIND_SUMMARY_COUNTRIES,
    KIND_SUMMARY_MAP,
    KIND_TITLE,
    BookPage,
)
from travelcore.export.document import PhotoElement
from travelcore.export.geometry import Frame, source_rect
from travelcore.export.mcfproduct import (
    ARTICLE_NAME,
    COVER_BG,
    COVER_PHOTO,
    COVER_TITLE,
    COVER_YEAR,
    GRAPHIC_DPI,
    INTRO_COUNTRY,
    INTRO_COVER,
    INTRO_DATES,
    INTRO_NOTES,
    INTRO_SPAN,
    INTRO_TITLE,
    JOURNAL_BODY,
    JOURNAL_TITLE,
    MAP_IMAGE,
    MAP_KICKER,
    MAP_TITLE,
    MCF_VERSION,
    PAGE_HEIGHT_MCF,
    PAGE_HEIGHT_MM,
    PAGE_NUMBER,
    PAGE_NUMBER_LEFT,
    PAGE_WIDTH_MCF,
    PAGE_WIDTH_MM,
    PRODUCT_NAME,
    SUMMARY_COUNTRIES,
    SUMMARY_HEADING,
    SUMMARY_METRIC_LABEL,
    SUMMARY_METRIC_STEP,
    SUMMARY_METRIC_VALUE,
    TITLE_TEXT,
    frame_to_mcf,
    padded_content_count,
)
from travelcore.export.paint import NAVY_BG, encode_jpeg, render_book_page
from travelcore.export.raster import page_pixels
from travelcore.media.orientation import orient_image

_SLUG = re.compile(r"[^\w.\-]+", re.UNICODE)
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")

COLOR_FG = "#ff1a2744"
COLOR_CREAM = "#fff4f7fb"
COLOR_MUTED = "#ff5c6b7a"
COLOR_NAVY_MUTED = "#ff9ec9b8"


@dataclass(frozen=True, slots=True)
class _CopiedImage:
    filename: str
    width: int
    height: int


class McfAssetStore:
    """Copy (or encode) images into the sidecar folder. Originals stay untouched."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self._by_source: dict[tuple[int, int], _CopiedImage] = {}
        self._used_names: set[str] = set()
        self.written: list[Path] = []

    def add_source(
        self,
        source_id: int,
        path: Path,
        *,
        rotation_degrees: int = 0,
    ) -> _CopiedImage | None:
        key = (source_id, int(rotation_degrees))
        found = self._by_source.get(key)
        if found is not None:
            return found
        if not path.is_file():
            return None
        name = self._unique_name(f"src{source_id}_{path.name}")
        dest = self.directory / name
        image = _open_oriented(path, rotation_degrees)
        if image is None:
            shutil.copy2(path, dest)
            copied = _CopiedImage(filename=name, width=0, height=0)
        else:
            try:
                rgb = image.convert("RGB")
                rgb.save(dest, format="JPEG", quality=92)
                copied = _CopiedImage(filename=name, width=rgb.width, height=rgb.height)
                rgb.close()
            finally:
                image.close()
        self._by_source[key] = copied
        self.written.append(dest)
        return copied

    def add_bytes(self, prefix: str, payload: bytes, suffix: str = ".jpg") -> _CopiedImage:
        name = self._unique_name(f"{prefix}{suffix}")
        dest = self.directory / name
        dest.write_bytes(payload)
        width, height = _jpeg_size(payload)
        copied = _CopiedImage(filename=name, width=width, height=height)
        self.written.append(dest)
        return copied

    def _unique_name(self, raw: str) -> str:
        stem = Path(raw).stem
        suffix = Path(raw).suffix.lower() or ".jpg"
        if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
            suffix = ".jpg"
        cleaned = _SAFE_NAME.sub("-", stem).strip("-._")[:48] or "bild"
        candidate = f"{cleaned}{suffix}"
        index = 2
        while candidate in self._used_names:
            candidate = f"{cleaned}-{index}{suffix}"
            index += 1
        self._used_names.add(candidate)
        return candidate


def content_pages(pages: tuple[BookPage, ...]) -> tuple[BookPage, tuple[BookPage, ...]]:
    """Cover plus interior sheets. The blank after the cover is the inside front."""

    if not pages or pages[0].kind != KIND_COVER:
        raise ExportError("MCF-Export erwartet Cover als erste Seite.")
    rest = list(pages[1:])
    if rest and rest[0].kind == KIND_BLANK:
        rest = rest[1:]
    target = padded_content_count(len(rest))
    while len(rest) < target:
        rest.append(BookPage(kind=KIND_BLANK))
    return pages[0], tuple(rest)


def write_fotobook(
    destination: Path,
    cover: BookPage,
    interiors: tuple[BookPage, ...],
    *,
    title: str,
    sources: Mapping[int, Path],
    rotations: Mapping[int, int],
    assets: McfAssetStore,
    progress: Callable[[int, int], None] | None = None,
) -> None:
    if len(interiors) > 202:
        raise ExportError(
            f"CEWE-Fotobuch Groß erlaubt höchstens 202 Innenseiten, dieses Travelbook hat {len(interiors)}."
        )
    folder_name = assets.directory.name
    root = ET.Element(
        "fotobook",
        {
            "productname": PRODUCT_NAME,
            "article_name": ARTICLE_NAME,
            "imagedir": folder_name,
            "version": MCF_VERSION,
            "isDataMcf": "0",
            "startdatecalendarium": "",
            "useSpineLogo": "0",
            "folderID": str(uuid.uuid4()),
        },
    )
    if title.strip():
        root.set("title", title.strip())
    _boilerplate(root, len(interiors))
    z = [1000]
    _append_covers(root, cover, sources, rotations, assets, z)
    _append_interiors(root, interiors, sources, rotations, assets, z, progress)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(_serialize(root), encoding="utf-8")


def _boilerplate(root: ET.Element, normal_pages: int) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    project = ET.SubElement(root, "project")
    project.set("projectID", str(uuid.uuid4()))
    project.set("createdWithHPSVersion", "8.0.5")
    project.set("multiPurposeText", "Traveljournal CEWE-Projekt")
    saving = ET.SubElement(root, "savingVersion")
    saving.set("compatibilityVersion", "6.4.2")
    saving.set("programversion", "8.0.5")
    saving.set("savetime", now)
    history = ET.SubElement(root, "creationHistory")
    history.set("creationDate", now)
    history.set("clientVersion", "traveljournal")
    config = ET.SubElement(root, "articleConfig")
    config.set("normalpages", str(normal_pages))
    config.set("totalpages", str(normal_pages + 5))
    config.set("pagenaming", "1")


def _empty_page(pagenr: int, page_type: str) -> ET.Element:
    page = ET.Element("page", {"pagenr": str(pagenr), "type": page_type, "rotation": "0"})
    ET.SubElement(
        page,
        "bundlesize",
        {"width": str(PAGE_WIDTH_MCF * 2), "height": str(PAGE_HEIGHT_MCF)},
    )
    return page


def _append_covers(
    root: ET.Element,
    cover: BookPage,
    sources: Mapping[int, Path],
    rotations: Mapping[int, int],
    assets: McfAssetStore,
    z: list[int],
) -> None:
    spread = _empty_page(0, "fullcover")
    _add_cover_areas(spread, cover, PAGE_WIDTH_MCF, sources, rotations, assets, z)
    root.append(spread)
    root.append(_empty_page(0, "spine"))
    root.append(_empty_page(0, "fullcover"))
    root.append(_empty_page(0, "emptypage"))


def _append_interiors(
    root: ET.Element,
    interiors: tuple[BookPage, ...],
    sources: Mapping[int, Path],
    rotations: Mapping[int, int],
    assets: McfAssetStore,
    z: list[int],
    progress: Callable[[int, int], None] | None,
) -> None:
    total = len(interiors)
    # First interior is odd (right of inside-front). Its areas live on emptypage 0.
    first_bundle = root[-1]
    _add_page_areas(first_bundle, interiors[0], PAGE_WIDTH_MCF, sources, rotations, assets, z)
    if progress is not None:
        progress(1, total)
    root.append(_empty_page(1, "normalpage"))

    index = 1
    while index < total:
        left = interiors[index]
        pagenr = index + 1
        bundle = _empty_page(pagenr, "normalpage")
        _add_page_areas(bundle, left, 0.0, sources, rotations, assets, z)
        if progress is not None:
            progress(index + 1, total)
        if index + 1 < total:
            _add_page_areas(
                bundle, interiors[index + 1], float(PAGE_WIDTH_MCF), sources, rotations, assets, z
            )
            if progress is not None:
                progress(index + 2, total)
            root.append(bundle)
            root.append(_empty_page(pagenr + 1, "normalpage"))
        else:
            root.append(bundle)
        index += 2
    root.append(_empty_page(0, "emptypage"))


def _add_cover_areas(
    page: ET.Element,
    cover: BookPage,
    origin: float,
    sources: Mapping[int, Path],
    rotations: Mapping[int, int],
    assets: McfAssetStore,
    z: list[int],
) -> None:
    navy = Image.new("RGB", page_pixels(PAGE_WIDTH_MM, PAGE_HEIGHT_MM, GRAPHIC_DPI), NAVY_BG)
    payload, _, _ = encode_jpeg(navy, quality=88)
    navy.close()
    bg = assets.add_bytes("gfx-cover-bg", payload)
    _image_area(page, COVER_BG, origin, bg, z, cutout=None)
    if cover.cover_id is not None:
        copied = assets.add_source(
            cover.cover_id,
            sources.get(cover.cover_id, Path()),
            rotation_degrees=rotations.get(cover.cover_id, 0),
        )
        if copied is not None:
            _image_area(page, COVER_PHOTO, origin, copied, z, cutout=None)
    if cover.year:
        _text_area(page, COVER_YEAR, origin, cover.year, z, size=11, bold=True, color=COLOR_NAVY_MUTED)
    heading = (cover.title or "REISE").strip() or "REISE"
    _text_area(
        page,
        COVER_TITLE,
        origin,
        heading,
        z,
        size=22,
        bold=True,
        color=COLOR_CREAM,
        align="center",
        valign="center",
    )


def _add_page_areas(
    page: ET.Element,
    book: BookPage,
    origin: float,
    sources: Mapping[int, Path],
    rotations: Mapping[int, int],
    assets: McfAssetStore,
    z: list[int],
) -> None:
    if book.kind == KIND_PHOTOS:
        for element in book.elements:
            _photo_element(page, element, origin, sources, rotations, assets, z)
        _page_number(page, book, origin, z)
        return
    if book.kind == KIND_TITLE:
        _text_area(
            page,
            TITLE_TEXT,
            origin,
            book.title or "Reise",
            z,
            size=22,
            bold=True,
            align="center",
            valign="center",
        )
        return
    if book.kind == KIND_JOURNAL:
        heading = (book.title or "Tagebuch").strip().upper() or "TAGEBUCH"
        _text_area(page, JOURNAL_TITLE, origin, heading, z, size=16, bold=True)
        if book.notes:
            _text_area(page, JOURNAL_BODY, origin, book.notes, z, size=11)
        _page_number(page, book, origin, z)
        return
    if book.kind == KIND_INTRO:
        _intro_areas(page, book, origin, sources, rotations, assets, z)
        return
    if book.kind == KIND_SUMMARY_COUNTRIES:
        _summary_country_areas(page, book, origin, sources, rotations, assets, z)
        return
    if book.kind == KIND_SUMMARY_MAP:
        _summary_map_areas(page, book, origin, sources, rotations, assets, z)
        return
    _page_number(page, book, origin, z)


def _intro_areas(
    page: ET.Element,
    book: BookPage,
    origin: float,
    sources: Mapping[int, Path],
    rotations: Mapping[int, int],
    assets: McfAssetStore,
    z: list[int],
) -> None:
    country = _island(book, sources, rotations, INTRO_COUNTRY)
    if country:
        _image_area(page, INTRO_COUNTRY, origin, assets.add_bytes("gfx-intro-country", country), z)
    if book.cover_id is not None:
        copied = assets.add_source(
            book.cover_id,
            sources.get(book.cover_id, Path()),
            rotation_degrees=rotations.get(book.cover_id, 0),
        )
        if copied is not None:
            _image_area(page, INTRO_COVER, origin, copied, z, cutout=None)
    heading = (book.title or book.kicker or "Abschnitt").upper()
    _text_area(page, INTRO_TITLE, origin, heading, z, size=16, bold=True)
    if book.dates:
        _text_area(page, INTRO_DATES, origin, book.dates, z, size=11, color=COLOR_MUTED)
    if book.notes:
        _text_area(page, INTRO_NOTES, origin, book.notes, z, size=11)
    span = _island(book, sources, rotations, INTRO_SPAN)
    if span:
        _image_area(page, INTRO_SPAN, origin, assets.add_bytes("gfx-intro-span", span), z)
    _page_number(page, book, origin, z)


def _summary_country_areas(
    page: ET.Element,
    book: BookPage,
    origin: float,
    sources: Mapping[int, Path],
    rotations: Mapping[int, int],
    assets: McfAssetStore,
    z: list[int],
) -> None:
    column = _island(book, sources, rotations, SUMMARY_COUNTRIES)
    if column:
        _image_area(page, SUMMARY_COUNTRIES, origin, assets.add_bytes("gfx-summary-countries", column), z)
    _text_area(page, SUMMARY_HEADING, origin, "REISEÜBERSICHT", z, size=10, bold=True, color=COLOR_MUTED)
    for index, (value, label) in enumerate(book.metrics):
        value_frame = Frame(
            SUMMARY_METRIC_VALUE.x,
            SUMMARY_METRIC_VALUE.y + index * SUMMARY_METRIC_STEP,
            SUMMARY_METRIC_VALUE.w,
            SUMMARY_METRIC_VALUE.h,
        )
        label_frame = Frame(
            SUMMARY_METRIC_LABEL.x,
            SUMMARY_METRIC_LABEL.y + index * SUMMARY_METRIC_STEP,
            SUMMARY_METRIC_LABEL.w,
            SUMMARY_METRIC_LABEL.h,
        )
        _text_area(page, value_frame, origin, value, z, size=28, bold=True)
        _text_area(page, label_frame, origin, label, z, size=11, color=COLOR_MUTED)
    _page_number(page, book, origin, z)


def _summary_map_areas(
    page: ET.Element,
    book: BookPage,
    origin: float,
    sources: Mapping[int, Path],
    rotations: Mapping[int, int],
    assets: McfAssetStore,
    z: list[int],
) -> None:
    _text_area(page, MAP_KICKER, origin, "KARTE", z, size=10, bold=True, color=COLOR_MUTED)
    _text_area(page, MAP_TITLE, origin, "Satellitenkarte", z, size=16, bold=True)
    mapped = _island(book, sources, rotations, MAP_IMAGE)
    if mapped:
        _image_area(page, MAP_IMAGE, origin, assets.add_bytes("gfx-summary-map", mapped), z)
    _page_number(page, book, origin, z)


def _photo_element(
    page: ET.Element,
    element: PhotoElement,
    origin: float,
    sources: Mapping[int, Path],
    rotations: Mapping[int, int],
    assets: McfAssetStore,
    z: list[int],
) -> None:
    path = sources.get(element.source_file_id)
    if path is None:
        return
    copied = assets.add_source(
        element.source_file_id, path, rotation_degrees=rotations.get(element.source_file_id, 0)
    )
    if copied is None:
        return
    cutout = None
    if copied.width > 0 and copied.height > 0:
        _left, _top, area_w, area_h = frame_to_mcf(element.frame)
        src = source_rect(copied.width, copied.height, area_w, area_h, element.crop)
        cutout = _cutout_from_source(src, area_w)
    _image_area(page, element.frame, origin, copied, z, cutout=cutout, rotation=element.crop.angle)


def _page_number(page: ET.Element, book: BookPage, origin: float, z: list[int]) -> None:
    if book.number is None:
        return
    frame = PAGE_NUMBER_LEFT if origin == 0.0 else PAGE_NUMBER
    _text_area(page, frame, origin, str(book.number), z, size=9, color=COLOR_MUTED, align="center")


def _image_area(
    page: ET.Element,
    frame: Frame,
    origin: float,
    image: _CopiedImage,
    z: list[int],
    cutout: tuple[float, float, float] | None = None,
    rotation: float = 0.0,
) -> None:
    left, top, width, height = frame_to_mcf(frame, origin_left=origin)
    area = ET.SubElement(page, "area", {"areatype": "imagearea"})
    pos = ET.SubElement(area, "position")
    pos.set("left", f"{left:.2f}")
    pos.set("top", f"{top:.2f}")
    pos.set("width", f"{width:.2f}")
    pos.set("height", f"{height:.2f}")
    pos.set("rotation", f"{rotation:.2f}")
    pos.set("zposition", str(z[0]))
    z[0] += 1
    image_el = ET.SubElement(area, "image")
    image_el.set("filename", f"safecontainer:/{image.filename}")
    image_el.set("backgroundPosition", "CENTER_MIDDLE")
    if cutout is not None:
        cut = ET.SubElement(image_el, "cutout")
        cut.set("left", f"{cutout[0]:.4f}")
        cut.set("top", f"{cutout[1]:.4f}")
        cut.set("scale", f"{cutout[2]:.6f}")
    ET.SubElement(area, "decoration")


def _text_area(
    page: ET.Element,
    frame: Frame,
    origin: float,
    text: str,
    z: list[int],
    *,
    size: int = 12,
    bold: bool = False,
    color: str = COLOR_FG,
    align: str = "left",
    valign: str = "top",
) -> None:
    if not text:
        return
    left, top, width, height = frame_to_mcf(frame, origin_left=origin)
    area = ET.SubElement(page, "area", {"areatype": "textarea"})
    pos = ET.SubElement(area, "position")
    pos.set("left", f"{left:.2f}")
    pos.set("top", f"{top:.2f}")
    pos.set("width", f"{width:.2f}")
    pos.set("height", f"{height:.2f}")
    pos.set("rotation", "0")
    pos.set("zposition", str(z[0]))
    z[0] += 1
    ET.SubElement(area, "decoration")
    text_el = ET.SubElement(area, "text")
    text_el.set("applySpotColor", "0")
    text_el.set("areaTextType", "content")
    text_el.text = _richtext(text, size=size, bold=bold, color=_css_color(color), align=align)
    ET.SubElement(text_el, "outline", {"width": "0"})
    fmt = ET.SubElement(text_el, "textFormat")
    fmt.set("Alignment", _align_token(align, valign))
    fmt.set("IndentMargin", "4")
    fmt.set("VerticalIndentMargin", "50")
    fmt.set("backgroundColor", "#00000000")
    weight = "700" if bold else "400"
    fmt.set("font", f"Arial,{size},-1,5,{weight},0,0,0,0,0,0,1,0,0,0,1")
    fmt.set("foregroundColor", color)
    fmt.set("hasOutline", "0")
    fmt.set("hyphenation", "0")
    fmt.set("letterSpacing", "0")
    fmt.set("lineHeight", "100")


def _island(
    page: BookPage,
    sources: Mapping[int, Path],
    rotations: Mapping[int, int],
    box: Frame,
) -> bytes | None:
    width, height = page_pixels(PAGE_WIDTH_MM, PAGE_HEIGHT_MM, GRAPHIC_DPI)
    canvas = render_book_page(page, sources, width, height, dpi=GRAPHIC_DPI, rotation_degrees=rotations)
    try:
        left = max(0, min(width - 1, round(width * box.x / 100.0)))
        top = max(0, min(height - 1, round(height * box.y / 100.0)))
        right = max(left + 1, min(width, round(width * (box.x + box.w) / 100.0)))
        bottom = max(top + 1, min(height, round(height * (box.y + box.h) / 100.0)))
        piece = canvas.crop((left, top, right, bottom))
        payload, _, _ = encode_jpeg(piece, quality=88)
        piece.close()
    finally:
        canvas.close()
    return payload


def _cutout_from_source(
    source: tuple[float, float, float, float], area_width_mcf: float
) -> tuple[float, float, float] | None:
    src_x, src_y, src_w, src_h = source
    if src_w <= 0 or src_h <= 0 or area_width_mcf <= 0:
        return None
    scale = area_width_mcf / src_w
    return (-src_x * scale, -src_y * scale, scale)


def _richtext(text: str, *, size: int, bold: bool, color: str, align: str) -> str:
    weight = "700" if bold else "400"
    body = html.escape(text).replace("\n", "<br/>")
    return (
        '<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.0//EN" '
        '"http://www.w3.org/TR/REC-html40/strict.dtd">'
        '<html><head><meta name="qrichtext" content="1"/></head>'
        f'<body style="font-family:\'Arial\'; font-size:{size}pt; font-weight:{weight}; color:{color};">'
        f'<p style="margin:0; text-align:{align};">{body}</p></body></html>'
    )


def _css_color(argb: str) -> str:
    raw = argb.lstrip("#")
    if len(raw) == 8:
        return f"#{raw[2:]}"
    return argb if argb.startswith("#") else f"#{raw}"


def _align_token(align: str, valign: str) -> str:
    vertical = {"center": "ALIGNVCENTER", "bottom": "ALIGNBOTTOM"}.get(valign, "ALIGNTOP")
    horizontal = {"center": "ALIGNHCENTER", "right": "ALIGNRIGHT"}.get(align, "ALIGNLEFT")
    return f"{vertical},{horizontal}"


def _open_oriented(path: Path, rotation_degrees: int) -> Image.Image | None:
    try:
        raw = Image.open(path)
    except (OSError, UnidentifiedImageError):
        return None
    try:
        return orient_image(raw.convert("RGB"), rotation_degrees=rotation_degrees)
    except OSError:
        return None
    finally:
        raw.close()


def _jpeg_size(payload: bytes) -> tuple[int, int]:
    try:
        image = Image.open(io.BytesIO(payload))
    except (OSError, UnidentifiedImageError):
        return (0, 0)
    try:
        return image.size
    finally:
        image.close()


def _serialize(root: ET.Element) -> str:
    tokens: list[str] = []
    for text_el in root.iter("text"):
        if text_el.text:
            token = f"@@MCFTEXT{len(tokens)}@@"
            tokens.append(text_el.text)
            text_el.text = token
    body = ET.tostring(root, encoding="unicode")
    for index, snippet in enumerate(tokens):
        body = body.replace(f"@@MCFTEXT{index}@@", f"<![CDATA[{snippet}]]>")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + body + "\n"


def mcf_folder_name(mcf_path: Path) -> str:
    return f"{mcf_path.stem}_mcf-Dateien"


def slug_filename(title: str) -> str:
    slug = _SLUG.sub("-", (title or "").strip()).strip("-")
    slug = slug[:48] or "travelbook"
    return f"{slug}.mcf"
