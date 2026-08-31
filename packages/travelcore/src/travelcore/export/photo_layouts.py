"""User photo-page templates, scoped to a page size (aspect ratio).

Built-in ``photos_1``–``photos_8`` stay in the packaged catalog and apply to every
format. Saved layouts live under the app config dir and only appear for the
page size they were created with.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from uuid import uuid4

from travelcore.exceptions import ExportError
from travelcore.export.geometry import Frame, clamp_frame

USER_LAYOUT_PREFIX = "user_"
_FILENAME = "photo_layouts.json"
_user_dir: Path | None = None


def set_user_layouts_dir(path: Path | None) -> None:
    """Tests and the app call this so user templates never hit an implicit path."""

    global _user_dir
    _user_dir = Path(path) if path is not None else None


def user_layouts_dir() -> Path | None:
    return _user_dir


def new_user_layout_id() -> str:
    return f"{USER_LAYOUT_PREFIX}{uuid4().hex[:12]}"


def is_user_layout(layout_id: str) -> bool:
    return layout_id.startswith(USER_LAYOUT_PREFIX)


def user_layouts_path() -> Path | None:
    if _user_dir is None:
        return None
    return _user_dir / _FILENAME


def load_user_layout(layout_id: str) -> dict[str, Any] | None:
    for item in _read_all():
        if item.get("id") == layout_id:
            return item
    return None


def list_user_layouts(page_size: str) -> tuple[dict[str, Any], ...]:
    return tuple(item for item in _read_all() if item.get("page_size") == page_size)


def layout_from_frames(
    frames: Sequence[Frame],
    *,
    name: str,
    page_size: str,
    layout_id: str | None = None,
) -> dict[str, Any]:
    caption = name.strip()
    if not caption:
        raise ExportError("Vorlagenname fehlt.")
    if not page_size.strip():
        raise ExportError("Seitenformat für die Vorlage fehlt.")
    slots: list[dict[str, Any]] = []
    for index, frame in enumerate(frames):
        box = clamp_frame(frame)
        slots.append(
            {
                "id": f"p{index + 1}",
                "type": "media",
                "accept": ["photo", "video", "track"],
                "x": round(box.x, 4),
                "y": round(box.y, 4),
                "w": round(box.w, 4),
                "h": round(box.h, 4),
                "fit": "cover",
            }
        )
    if not slots:
        raise ExportError("Eine Vorlage braucht mindestens einen Rahmen.")
    return {
        "schema_version": 1,
        "id": layout_id or new_user_layout_id(),
        "kind": "photos",
        "page_size": page_size,
        "label": {"de": caption, "en": caption},
        "applies_to": "page",
        "photo_count": len(slots),
        "slots": slots,
    }


def save_user_layout(layout: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize(layout)
    if normalized is None:
        raise ExportError("Ungültige Fotoseiten-Vorlage.")
    path = _require_path()
    items = [item for item in _read_all() if item.get("id") != normalized["id"]]
    items.append(normalized)
    _write_all(path, items)
    return normalized


def rename_user_layout(layout_id: str, name: str) -> dict[str, Any]:
    caption = name.strip()
    if not caption:
        raise ExportError("Vorlagenname fehlt.")
    current = load_user_layout(layout_id)
    if current is None:
        raise ExportError(f"Vorlage '{layout_id}' nicht gefunden.")
    current["label"] = {"de": caption, "en": caption}
    return save_user_layout(current)


def delete_user_layout(layout_id: str) -> None:
    if not is_user_layout(layout_id):
        raise ExportError("Standardvorlagen können nicht gelöscht werden.")
    path = _require_path()
    items = [item for item in _read_all() if item.get("id") != layout_id]
    _write_all(path, items)


def _require_path() -> Path:
    path = user_layouts_path()
    if path is None:
        raise ExportError("Vorlagenordner ist nicht gesetzt.")
    return path


def _read_all() -> list[dict[str, Any]]:
    path = user_layouts_path()
    if path is None or not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    listed = raw.get("layouts") if isinstance(raw, dict) else None
    if not isinstance(listed, list):
        return []
    layouts: list[dict[str, Any]] = []
    for item in listed:
        if not isinstance(item, dict):
            continue
        normalized = _normalize(item)
        if normalized is not None:
            layouts.append(normalized)
    return layouts


def _write_all(path: Path, layouts: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": 1, "layouts": list(layouts)}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _normalize(raw: dict[str, Any]) -> dict[str, Any] | None:
    layout_id = raw.get("id")
    page_size = raw.get("page_size")
    if not isinstance(layout_id, str) or not is_user_layout(layout_id):
        return None
    if "/" in layout_id or "\\" in layout_id or ".." in layout_id:
        return None
    if not isinstance(page_size, str) or not page_size.strip():
        return None
    slots_raw = raw.get("slots")
    if not isinstance(slots_raw, list) or not slots_raw:
        return None
    slots: list[dict[str, Any]] = []
    for index, slot in enumerate(slots_raw):
        if not isinstance(slot, dict):
            continue
        try:
            box = clamp_frame(
                Frame(
                    x=float(slot.get("x", 0)),
                    y=float(slot.get("y", 0)),
                    w=float(slot.get("w", 100)),
                    h=float(slot.get("h", 100)),
                )
            )
        except (TypeError, ValueError):
            continue
        slots.append(
            {
                "id": str(slot.get("id") or f"p{index + 1}"),
                "type": "media",
                "accept": ["photo", "video", "track"],
                "x": box.x,
                "y": box.y,
                "w": box.w,
                "h": box.h,
                "fit": "cover",
            }
        )
    if not slots:
        return None
    label = raw.get("label")
    if isinstance(label, str) and label.strip():
        names = {"de": label.strip(), "en": label.strip()}
    elif isinstance(label, dict):
        text = str(label.get("de") or label.get("en") or layout_id).strip()
        names = {"de": text, "en": str(label.get("en") or text)}
    else:
        names = {"de": layout_id, "en": layout_id}
    return {
        "schema_version": 1,
        "id": layout_id,
        "kind": "photos",
        "page_size": page_size.strip(),
        "label": names,
        "applies_to": "page",
        "photo_count": len(slots),
        "slots": slots,
    }
