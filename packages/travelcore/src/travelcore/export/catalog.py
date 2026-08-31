"""Product templates (Ausgabetyp) and the type × format matrix.

Templates live next to this module as JSON. A renderer (HTML, PDF, …) consumes
a bound document; it does not hard-code Travelbook vs. Jahrbuch.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from travelcore.exceptions import ExportError

_TEMPLATES = Path(__file__).resolve().parent / "templates"
_CATALOG_FILE = "catalog.json"

KNOWN_FORMATS = ("html", "pdf", "epub", "latex", "cewe", "video")
_LAYOUT_DIR = "page_layouts"


def templates_dir() -> Path:
    return _TEMPLATES


def _read_json(relative: str) -> dict[str, Any]:
    path = _TEMPLATES / relative
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ExportError(f"Export-Template nicht lesbar: {relative}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ExportError(f"Export-Template ungültig: {relative}") from exc
    if not isinstance(data, dict):
        raise ExportError(f"Export-Template muss ein Objekt sein: {relative}")
    return data


@lru_cache(maxsize=1)
def load_catalog() -> dict[str, Any]:
    catalog = _read_json(_CATALOG_FILE)
    products = catalog.get("products")
    if not isinstance(products, list) or not products:
        raise ExportError("Export-Katalog ohne Produkte.")
    return catalog


def list_product_ids() -> tuple[str, ...]:
    return tuple(str(item["id"]) for item in load_catalog()["products"])


def _template_path(product_id: str) -> str:
    for item in load_catalog()["products"]:
        if item.get("id") == product_id:
            template = item.get("template")
            if not isinstance(template, str) or not template:
                raise ExportError(f"Produkt '{product_id}' ohne Template-Pfad.")
            return template
    raise ExportError(f"Unbekannter Ausgabetyp '{product_id}'.")


def _merge_product(child: dict[str, Any], parent: dict[str, Any]) -> dict[str, Any]:
    """Parent pages fill gaps; child replaces formats, viewer, label, and matching page keys."""

    merged = dict(parent)
    for key, value in child.items():
        if key == "pages":
            continue
        merged[key] = value
    child_pages = child.get("pages")
    if isinstance(child_pages, list):
        parent_pages = parent.get("pages", [])
        by_id = {
            page["id"]: page
            for page in parent_pages
            if isinstance(page, dict) and "id" in page
        }
        pages: list[dict[str, Any]] = []
        for page in child_pages:
            if not isinstance(page, dict) or "id" not in page:
                continue
            if page["id"] in by_id:
                combined = dict(by_id[page["id"]])
                combined.update(page)
                pages.append(combined)
            else:
                pages.append(dict(page))
        merged["pages"] = pages
    merged["id"] = child["id"]
    return merged


@lru_cache(maxsize=16)
def load_product(product_id: str, *, _stack: tuple[str, ...] = ()) -> dict[str, Any]:
    """Return a product template, resolving ``extends`` against the parent."""

    if product_id in _stack:
        cycle = " → ".join((*_stack, product_id))
        raise ExportError(f"Zyklus in Export-Templates: {cycle}")
    data = _read_json(_template_path(product_id))
    parent_id = data.get("extends")
    if isinstance(parent_id, str) and parent_id:
        parent = load_product(parent_id, _stack=(*_stack, product_id))
        data = _merge_product(data, parent)
    formats = data.get("formats")
    if not isinstance(formats, list) or not formats:
        raise ExportError(f"Ausgabetyp '{product_id}' ohne Formate.")
    unknown = [item for item in formats if item not in KNOWN_FORMATS]
    if unknown:
        raise ExportError(f"Ausgabetyp '{product_id}' mit unbekanntem Format: {unknown[0]}.")
    return data


def product_formats(product_id: str) -> tuple[str, ...]:
    catalog = load_catalog()
    matrix = catalog.get("matrix")
    if isinstance(matrix, dict) and product_id in matrix:
        listed = matrix[product_id]
        if not isinstance(listed, list) or not listed:
            raise ExportError(f"Matrix ohne Formate für '{product_id}'.")
        return tuple(str(item) for item in listed)
    return tuple(str(item) for item in load_product(product_id)["formats"])


def supports(product_id: str, format_id: str) -> bool:
    return format_id in product_formats(product_id)


def first_path() -> tuple[str, str]:
    """Default implementation pair (Travelbook × HTML)."""

    listed = load_catalog().get("first_path")
    if isinstance(listed, dict):
        product = str(listed.get("product") or "")
        fmt = str(listed.get("format") or "")
        if product and fmt:
            return product, fmt
    return "travelbook", "html"


def list_page_sizes() -> tuple[dict[str, Any], ...]:
    """Paper sizes for one book page (cover or one half of a spread)."""

    items = load_catalog().get("page_sizes")
    if not isinstance(items, list) or not items:
        raise ExportError("Export-Katalog ohne Seitenformate.")
    sizes = tuple(item for item in items if isinstance(item, dict) and item.get("id"))
    if not sizes:
        raise ExportError("Export-Katalog ohne Seitenformate.")
    return sizes


def default_page_size_id() -> str:
    listed = load_catalog().get("default_page_size")
    if isinstance(listed, str) and listed:
        return listed
    return str(list_page_sizes()[0]["id"])


def page_size(size_id: str) -> dict[str, Any]:
    for item in list_page_sizes():
        if item.get("id") == size_id:
            width = item.get("width_mm")
            height = item.get("height_mm")
            if not isinstance(width, (int, float)) or not isinstance(height, (int, float)):
                raise ExportError(f"Seitenformat '{size_id}' ohne Maße.")
            if width <= 0 or height <= 0:
                raise ExportError(f"Seitenformat '{size_id}' mit ungültigen Maßen.")
            return item
    raise ExportError(f"Unbekanntes Seitenformat '{size_id}'.")


def assert_supported(product_id: str, format_id: str) -> None:
    if not supports(product_id, format_id):
        raise ExportError(
            f"Ausgabeformat '{format_id}' ist für Ausgabetyp '{product_id}' nicht vorgesehen."
        )


def load_page_layout(layout_id: str) -> dict[str, Any]:
    """Load a page layout template (section_intro, photos_1–8, journal)."""

    if not layout_id or "/" in layout_id or "\\" in layout_id or ".." in layout_id:
        raise ExportError("Ungültiges Seiten-Layout.")
    data = _read_json(f"{_LAYOUT_DIR}/{layout_id}.json")
    if data.get("id") != layout_id:
        raise ExportError(f"Seiten-Layout '{layout_id}' hat die falsche id.")
    return data


def chronicle_page_layouts(product_id: str = "travelbook") -> tuple[str, ...]:
    """Layouts the editor may put on added pages (not section_intro)."""

    editor = load_product(product_id).get("editor")
    if not isinstance(editor, dict):
        return ()
    chronicle = editor.get("chronicle")
    if not isinstance(chronicle, dict):
        return ()
    listed = chronicle.get("page_layouts")
    if not isinstance(listed, list):
        return ()
    return tuple(str(item) for item in listed)
