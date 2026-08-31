"""Travelbook composition (travelbook.json) — photo elements on pages.

Schema 2 stores free-form photo elements (frame, crop, z). Schema 1 ``media``
arrays are migrated on load. Templates under ``page_layouts/`` remain factories
for the initial frames.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any
from uuid import uuid4

from travelcore.exceptions import ExportError
from travelcore.export.catalog import load_page_layout
from travelcore.export.geometry import Crop, Frame, clamp_crop, clamp_frame, clamp_stored_frame
from travelcore.export.photo_layouts import is_user_layout
from travelcore.media.gallery import SORT_REJECTED
from travelcore.media.types import FileKind
from travelcore.timeline.types import TimelinePhoto, TimelineSection, TimelineSnapshot

DOCUMENT_FILENAME = "travelbook.json"
SCHEMA_VERSION = 2
_BOOK_KINDS = frozenset({FileKind.PHOTO.value, FileKind.VIDEO.value, FileKind.GPS.value})
_PHOTO_LAYOUT_MAX = 8


@dataclass(frozen=True, slots=True)
class PhotoElement:
    """One photo (or video/track preview) on a page."""

    id: str
    source_file_id: int
    frame: Frame
    crop: Crop = field(default_factory=Crop)
    z: int = 1


@dataclass(frozen=True, slots=True)
class PageInstance:
    layout: str
    locked: bool = False
    elements: tuple[PhotoElement, ...] = ()


@dataclass(frozen=True, slots=True)
class Spread:
    id: str
    verso: PageInstance
    recto: PageInstance
    initial: bool = False


@dataclass(frozen=True, slots=True)
class Chapter:
    section_id: int
    spreads: tuple[Spread, ...]


@dataclass(frozen=True, slots=True)
class TravelbookDocument:
    product: str = "travelbook"
    schema_version: int = SCHEMA_VERSION
    page_size: str = "a4-portrait"
    photo_layouts: dict[str, str] = field(default_factory=dict)
    spread_overlap: bool = False
    chapters: tuple[Chapter, ...] = ()

    @property
    def photo_layout(self) -> str:
        value = self.photo_layouts.get(self.page_size, "")
        return value if layout_is_photos(value) else ""


def new_element_id() -> str:
    return uuid4().hex[:12]


def layout_is_photos(layout_id: str) -> bool:
    if layout_id.startswith("photos_"):
        return True
    return is_user_layout(layout_id)


def _photo_layouts_from_dict(data: dict[str, Any], page_size: str) -> dict[str, str]:
    result: dict[str, str] = {}
    raw = data.get("photo_layouts")
    if isinstance(raw, dict):
        for key, value in raw.items():
            if isinstance(key, str) and isinstance(value, str) and layout_is_photos(value):
                result[key] = value
    single = data.get("photo_layout")
    if isinstance(single, str) and layout_is_photos(single) and page_size not in result:
        result[page_size] = single
    return result


def photo_layout_id(count: int) -> str:
    """Template that fits ``count`` photos (1–8). Empty pages use photos_1."""

    n = min(max(int(count), 1), _PHOTO_LAYOUT_MAX)
    return f"photos_{n}"


def book_media_items(section: TimelineSection) -> tuple[TimelinePhoto, ...]:
    """Visible section members that may appear on photo pages."""

    visible = [item for item in section.items if _is_book_media(item)]
    cover_id = section.cover_source_file_id
    if cover_id is None:
        return tuple(visible)
    ordered = [item for item in visible if item.source_file_id == cover_id]
    ordered.extend(item for item in visible if item.source_file_id != cover_id)
    return tuple(ordered)


def elements_from_layout(layout_id: str, source_file_ids: Sequence[int | None]) -> tuple[PhotoElement, ...]:
    """Instantiate photo elements from a page-layout template. Empty slots are skipped."""

    if not layout_is_photos(layout_id):
        return ()
    try:
        layout = load_page_layout(layout_id)
    except ExportError:
        return ()
    slots = layout.get("slots")
    if not isinstance(slots, list):
        return ()
    elements: list[PhotoElement] = []
    z = 1
    for index, slot in enumerate(slots):
        if not isinstance(slot, dict) or slot.get("type") != "media":
            continue
        if index >= len(source_file_ids):
            break
        source_id = source_file_ids[index]
        if source_id is None:
            continue
        elements.append(
            PhotoElement(
                id=str(slot.get("id") or f"p{index + 1}"),
                source_file_id=int(source_id),
                frame=clamp_frame(
                    Frame(
                        x=float(slot.get("x", 0)),
                        y=float(slot.get("y", 0)),
                        w=float(slot.get("w", 100)),
                        h=float(slot.get("h", 100)),
                    )
                ),
                z=z,
            )
        )
        z += 1
    return tuple(elements)


def next_z(elements: Sequence[PhotoElement]) -> int:
    if not elements:
        return 1
    return max(item.z for item in elements) + 1


def sorted_by_z(elements: Sequence[PhotoElement]) -> tuple[PhotoElement, ...]:
    return tuple(sorted(elements, key=lambda item: (item.z, item.id)))


def replace_elements(page: PageInstance, elements: Sequence[PhotoElement]) -> PageInstance:
    return replace(page, elements=tuple(elements))


def bring_to_front(elements: Sequence[PhotoElement], element_id: str) -> tuple[PhotoElement, ...]:
    current = next((item for item in elements if item.id == element_id), None)
    if current is None:
        return tuple(elements)
    top = next_z(elements)
    return tuple(replace(item, z=top) if item.id == element_id else item for item in elements)


def send_to_back(elements: Sequence[PhotoElement], element_id: str) -> tuple[PhotoElement, ...]:
    current = next((item for item in elements if item.id == element_id), None)
    if current is None:
        return tuple(elements)
    floor = min((item.z for item in elements), default=1) - 1
    return tuple(replace(item, z=floor) if item.id == element_id else item for item in elements)


def remove_element(elements: Sequence[PhotoElement], element_id: str) -> tuple[PhotoElement, ...]:
    return tuple(item for item in elements if item.id != element_id)


def add_photo_element(
    elements: Sequence[PhotoElement],
    source_file_id: int,
    *,
    frame: Frame | None = None,
) -> tuple[PhotoElement, ...]:
    placed = clamp_stored_frame(frame if frame is not None else Frame(x=12.0, y=12.0, w=40.0, h=36.0))
    added = PhotoElement(
        id=new_element_id(),
        source_file_id=source_file_id,
        frame=placed,
        z=next_z(elements),
    )
    return (*elements, added)


def replace_source(
    elements: Sequence[PhotoElement], element_id: str, source_file_id: int
) -> tuple[PhotoElement, ...]:
    return tuple(
        replace(item, source_file_id=source_file_id, crop=Crop()) if item.id == element_id else item
        for item in elements
    )


def update_element(elements: Sequence[PhotoElement], updated: PhotoElement) -> tuple[PhotoElement, ...]:
    return tuple(updated if item.id == updated.id else item for item in elements)


def overflow_visitors(neighbor: Sequence[PhotoElement], *, onto: str) -> tuple[PhotoElement, ...]:
    """Neighbor frames that cross the gutter, shifted into ``onto`` page coordinates."""

    visitors: list[PhotoElement] = []
    for item in neighbor:
        if onto == "verso" and item.frame.x < -1e-9:
            frame = Frame(item.frame.x + 100.0, item.frame.y, item.frame.w, item.frame.h)
            visitors.append(replace(item, frame=frame))
        elif onto == "recto" and item.frame.x + item.frame.w > 100.0 + 1e-9:
            frame = Frame(item.frame.x - 100.0, item.frame.y, item.frame.w, item.frame.h)
            visitors.append(replace(item, frame=frame))
    return tuple(visitors)


def document_path(project_dir: Path) -> Path:
    return Path(project_dir) / DOCUMENT_FILENAME


def load_document(path: Path) -> TravelbookDocument:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ExportError(f"Travelbook-Dokument nicht lesbar: {path}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ExportError(f"Travelbook-Dokument ungültig: {path}") from exc
    if not isinstance(data, dict):
        raise ExportError(f"Travelbook-Dokument muss ein Objekt sein: {path}")
    return document_from_dict(data)


def save_document(path: Path, document: TravelbookDocument) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = document_to_dict(document)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_or_create(
    project_dir: Path,
    snapshot: TimelineSnapshot,
    *,
    page_size: str = "a4-portrait",
    photo_layout: str = "",
) -> TravelbookDocument:
    path = document_path(project_dir)
    if path.is_file():
        document = load_document(path)
    else:
        layout = photo_layout if layout_is_photos(photo_layout) else ""
        layouts = {page_size: layout} if layout else {}
        document = TravelbookDocument(page_size=page_size, photo_layouts=layouts)
    synced = sync_document(document, snapshot, page_size=page_size)
    if synced != document or not path.is_file():
        save_document(path, synced)
    return synced


def sync_document(
    document: TravelbookDocument,
    snapshot: TimelineSnapshot,
    *,
    page_size: str | None = None,
) -> TravelbookDocument:
    """Ensure one initial spread per published section. Extra spreads stay."""

    published = snapshot.published_entries()
    wanted = [entry.section.id for entry in published if entry.section is not None]
    by_id = {chapter.section_id: chapter for chapter in document.chapters}
    chapters: list[Chapter] = []
    for section_id in wanted:
        existing = by_id.get(section_id)
        if existing is not None and existing.spreads:
            chapters.append(existing)
            continue
        section = next(
            entry.section
            for entry in published
            if entry.section is not None and entry.section.id == section_id
        )
        chapters.append(_initial_chapter(section, photo_layout=document.photo_layout))
    size = page_size if page_size else document.page_size
    return replace(document, schema_version=SCHEMA_VERSION, page_size=size, chapters=tuple(chapters))


def add_spread(
    chapter: Chapter,
    *,
    verso_layout: str | None = None,
    recto_layout: str | None = None,
    photo_layout: str = "",
) -> Chapter:
    layout = photo_layout if layout_is_photos(photo_layout) else "photos_1"
    extra = Spread(
        id=f"section-{chapter.section_id}-extra-{_next_extra_index(chapter)}",
        initial=False,
        verso=PageInstance(layout=verso_layout or layout, locked=False, elements=()),
        recto=PageInstance(layout=recto_layout or layout, locked=False, elements=()),
    )
    return replace(chapter, spreads=(*chapter.spreads, extra))


def remove_spread(chapter: Chapter, spread_id: str) -> Chapter:
    remaining = tuple(spread for spread in chapter.spreads if spread.id != spread_id or spread.initial)
    if not remaining:
        return chapter
    return replace(chapter, spreads=remaining)


def replace_chapter(document: TravelbookDocument, chapter: Chapter) -> TravelbookDocument:
    chapters = tuple(chapter if item.section_id == chapter.section_id else item for item in document.chapters)
    return replace(document, chapters=chapters)


def replace_spread(chapter: Chapter, spread: Spread) -> Chapter:
    spreads = tuple(spread if item.id == spread.id else item for item in chapter.spreads)
    return replace(chapter, spreads=spreads)


def replace_page(spread: Spread, side: str, page: PageInstance) -> Spread:
    if side == "verso":
        return replace(spread, verso=page)
    if side == "recto":
        return replace(spread, recto=page)
    raise ExportError(f"Unbekannte Buchseite '{side}'.")


def apply_photo_layout(
    document: TravelbookDocument,
    layout_id: str,
    snapshot: TimelineSnapshot | None = None,
) -> TravelbookDocument:
    """Re-arrange every photo page to ``layout_id``. Intro and journal pages stay."""

    if not layout_is_photos(layout_id):
        raise ExportError(f"Unbekanntes Foto-Layout '{layout_id}'.")
    fallback: dict[int, list[int]] = {}
    if snapshot is not None:
        for entry in snapshot.published_entries():
            section = entry.section
            if section is None:
                continue
            fallback[section.id] = [item.source_file_id for item in book_media_items(section)]
    chapters = []
    for chapter in document.chapters:
        section_ids = fallback.get(chapter.section_id, [])
        spreads = []
        for spread in chapter.spreads:
            recto_ids = section_ids if spread.initial else []
            spreads.append(
                replace(
                    spread,
                    verso=_relayout_photo_page(spread.verso, layout_id, ()),
                    recto=_relayout_photo_page(spread.recto, layout_id, recto_ids),
                )
            )
        chapters.append(replace(chapter, spreads=tuple(spreads)))
    layouts = dict(document.photo_layouts)
    layouts[document.page_size] = layout_id
    return replace(document, photo_layouts=layouts, chapters=tuple(chapters))


def _relayout_photo_page(page: PageInstance, layout_id: str, fallback_ids: Sequence[int]) -> PageInstance:
    if page.locked or not layout_is_photos(page.layout):
        return page
    existing = [item.source_file_id for item in sorted_by_z(page.elements)]
    ids: Sequence[int | None] = existing if existing else list(fallback_ids)
    return replace(page, layout=layout_id, elements=elements_from_layout(layout_id, ids))


def document_from_dict(data: dict[str, Any]) -> TravelbookDocument:
    chapters_raw = data.get("chapters")
    if not isinstance(chapters_raw, list):
        chapters_raw = []
    chapters = tuple(_chapter_from_dict(item) for item in chapters_raw if isinstance(item, dict))
    page_size = data.get("page_size")
    size_id = str(page_size) if isinstance(page_size, str) and page_size else "a4-portrait"
    return TravelbookDocument(
        product=str(data.get("product") or "travelbook"),
        schema_version=SCHEMA_VERSION,
        page_size=size_id,
        photo_layouts=_photo_layouts_from_dict(data, size_id),
        spread_overlap=bool(data.get("spread_overlap", False)),
        chapters=chapters,
    )


def document_to_dict(document: TravelbookDocument) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "product": document.product,
        "page_size": document.page_size,
        "chapters": [_chapter_to_dict(chapter) for chapter in document.chapters],
    }
    layouts = {
        size: layout_id
        for size, layout_id in document.photo_layouts.items()
        if isinstance(size, str) and layout_is_photos(layout_id)
    }
    if layouts:
        payload["photo_layouts"] = layouts
    if document.spread_overlap:
        payload["spread_overlap"] = True
    return payload


def _is_book_media(item: TimelinePhoto) -> bool:
    if item.sort_status == SORT_REJECTED:
        return False
    if item.file_kind not in _BOOK_KINDS:
        return False
    if item.stack_id is not None and not item.is_stack_key:
        return False
    hidden_group = item.group_id is not None and item.group_status == "accepted"
    return not hidden_group or item.is_group_key


def _initial_chapter(section: TimelineSection, *, photo_layout: str = "") -> Chapter:
    media = book_media_items(section)
    ids = [item.source_file_id for item in media[:_PHOTO_LAYOUT_MAX]]
    layout = photo_layout if layout_is_photos(photo_layout) else photo_layout_id(len(ids))
    return Chapter(
        section_id=section.id,
        spreads=(
            Spread(
                id=f"section-{section.id}-initial",
                initial=True,
                verso=PageInstance(layout="section_intro", locked=True),
                recto=PageInstance(
                    layout=layout,
                    locked=False,
                    elements=elements_from_layout(layout, ids),
                ),
            ),
        ),
    )


def _next_extra_index(chapter: Chapter) -> int:
    extras = [spread for spread in chapter.spreads if not spread.initial]
    return len(extras) + 1


def _chapter_from_dict(data: dict[str, Any]) -> Chapter:
    section_id = data.get("section_id")
    if not isinstance(section_id, int):
        raise ExportError("Kapitel ohne section_id.")
    spreads_raw = data.get("spreads")
    if not isinstance(spreads_raw, list) or not spreads_raw:
        raise ExportError(f"Kapitel {section_id} ohne Doppelseiten.")
    spreads = tuple(_spread_from_dict(item, section_id) for item in spreads_raw if isinstance(item, dict))
    if not spreads:
        raise ExportError(f"Kapitel {section_id} ohne Doppelseiten.")
    return Chapter(section_id=section_id, spreads=spreads)


def _spread_from_dict(data: dict[str, Any], section_id: int) -> Spread:
    spread_id = data.get("id")
    if not isinstance(spread_id, str) or not spread_id:
        spread_id = f"section-{section_id}-{uuid4().hex[:8]}"
    verso = _page_from_dict(data.get("verso"))
    recto = _page_from_dict(data.get("recto"))
    return Spread(
        id=spread_id,
        initial=bool(data.get("initial", False)),
        verso=verso,
        recto=recto,
    )


def _page_from_dict(raw: object) -> PageInstance:
    if not isinstance(raw, dict):
        return PageInstance(layout="photos_1")
    layout = str(raw.get("layout") or "photos_1")
    locked = bool(raw.get("locked", False))
    elements_raw = raw.get("elements")
    if isinstance(elements_raw, list):
        elements = tuple(_element_from_dict(item) for item in elements_raw if isinstance(item, dict))
        return PageInstance(layout=layout, locked=locked, elements=elements)
    media = raw.get("media")
    ids: list[int | None] = []
    if isinstance(media, list):
        for item in media:
            if item is None:
                ids.append(None)
            elif isinstance(item, int):
                ids.append(item)
    return PageInstance(layout=layout, locked=locked, elements=elements_from_layout(layout, ids))


def _element_from_dict(data: dict[str, Any]) -> PhotoElement:
    source_id = data.get("source_file_id")
    if not isinstance(source_id, int):
        raise ExportError("Bildelement ohne source_file_id.")
    frame_raw = data.get("frame")
    if isinstance(frame_raw, dict):
        frame = Frame(
            x=float(frame_raw.get("x", 0)),
            y=float(frame_raw.get("y", 0)),
            w=float(frame_raw.get("w", 100)),
            h=float(frame_raw.get("h", 100)),
        )
    else:
        frame = Frame(0.0, 0.0, 100.0, 100.0)
    crop_raw = data.get("crop")
    if isinstance(crop_raw, dict):
        crop = clamp_crop(
            Crop(
                scale=float(crop_raw.get("scale", 1.0)),
                pan_x=float(crop_raw.get("pan_x", 0.0)),
                pan_y=float(crop_raw.get("pan_y", 0.0)),
                angle=float(crop_raw.get("angle", 0.0)),
            )
        )
    else:
        crop = Crop()
    z_raw = data.get("z", 1)
    z = int(z_raw) if isinstance(z_raw, (int, float)) else 1
    element_id = data.get("id")
    return PhotoElement(
        id=str(element_id) if isinstance(element_id, str) and element_id else new_element_id(),
        source_file_id=source_id,
        frame=clamp_stored_frame(frame),
        crop=crop,
        z=z,
    )


def _chapter_to_dict(chapter: Chapter) -> dict[str, Any]:
    return {
        "section_id": chapter.section_id,
        "spreads": [_spread_to_dict(spread) for spread in chapter.spreads],
    }


def _spread_to_dict(spread: Spread) -> dict[str, Any]:
    return {
        "id": spread.id,
        "initial": spread.initial,
        "verso": _page_to_dict(spread.verso),
        "recto": _page_to_dict(spread.recto),
    }


def _page_to_dict(page: PageInstance) -> dict[str, Any]:
    payload: dict[str, Any] = {"layout": page.layout, "locked": page.locked}
    if page.elements:
        payload["elements"] = [_element_to_dict(item) for item in page.elements]
    return payload


def _element_to_dict(element: PhotoElement) -> dict[str, Any]:
    crop: dict[str, float] = {
        "scale": element.crop.scale,
        "pan_x": element.crop.pan_x,
        "pan_y": element.crop.pan_y,
    }
    if abs(element.crop.angle) > 1e-9:
        crop["angle"] = element.crop.angle
    return {
        "id": element.id,
        "type": "photo",
        "source_file_id": element.source_file_id,
        "frame": {"x": element.frame.x, "y": element.frame.y, "w": element.frame.w, "h": element.frame.h},
        "crop": crop,
        "z": element.z,
    }
