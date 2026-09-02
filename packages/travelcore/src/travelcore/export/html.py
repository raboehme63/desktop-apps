"""HTML exporters.

Travelbook (book) remains a later Jinja2 flipbook.
Travelbook (interaktiv) writes a read-only Leaflet directory: ``index.html``,
copied thumbnails, 1920 px viewer JPEGs under ``media/full/``, and vendored
Leaflet. Basemap tiles stay remote. Hidden timeline sections are omitted,
matching the in-app map. Original media files are never written.
"""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Callable, Iterable
from dataclasses import replace
from html import escape
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from travelcore.config import DEFAULT_THUMBNAIL_SIZE
from travelcore.database.models import SourceFile, Trip
from travelcore.exceptions import ExportError
from travelcore.export.base import ExportResult, NotImplementedExporter
from travelcore.export.catalog import assert_supported
from travelcore.export.map_chrome import chrome_markup
from travelcore.maps.backend import FoliumMapBackend
from travelcore.maps.cache import tiles_for_map_provider
from travelcore.maps.groups import (
    MapTimelineCard,
    build_map_group_detail,
    build_map_timeline,
    resolve_map_group,
)
from travelcore.maps.interaction import leaflet_payload, timeline_js_cards
from travelcore.maps.scene import MapMarker, MapScene, apply_map_track_color, build_map_scene
from travelcore.media.thumbnails import write_viewer_jpeg
from travelcore.project_settings import (
    DEFAULT_MAP_TRACK_COLOR,
    DEFAULT_STAY_LINK_COLOR,
    normalize_map_track_color,
    normalize_stay_link_color,
)

_SLUG = re.compile(r"[^\w\-]+", re.UNICODE)
_TITLE = re.compile(r"<title>[^<]*</title>", re.IGNORECASE)
_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
_VENDOR_DIR = Path(__file__).resolve().parent / "static" / "leaflet"
_CDN_ASSETS = (
    ("https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/leaflet.js", "leaflet.js"),
    ("https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/leaflet.css", "leaflet.css"),
    (
        "https://cdnjs.cloudflare.com/ajax/libs/leaflet.markercluster/1.1.0/leaflet.markercluster.js",
        "leaflet.markercluster.js",
    ),
    (
        "https://cdnjs.cloudflare.com/ajax/libs/leaflet.markercluster/1.1.0/MarkerCluster.css",
        "MarkerCluster.css",
    ),
    (
        "https://cdnjs.cloudflare.com/ajax/libs/leaflet.markercluster/1.1.0/MarkerCluster.Default.css",
        "MarkerCluster.Default.css",
    ),
)

PRODUCT_ID = "travelbook-interactive"


class HtmlExporter(NotImplementedExporter):
    name = "html"


def export_interactive_dirname(title: str) -> str:
    slug = _SLUG.sub("-", (title or "").strip()).strip("-")
    slug = slug[:48] or "travelbook"
    return f"{slug}-interaktiv"


def unique_export_dir(directory: Path, name: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    if not path.exists():
        return path
    index = 2
    while True:
        candidate = directory / f"{name}-{index}"
        if not candidate.exists():
            return candidate
        index += 1


def normalize_html_dir(chosen: str | Path) -> Path:
    """Treat a save-dialog path as a directory (strip a trailing ``.html``)."""

    path = Path(chosen)
    if path.suffix.lower() == ".html":
        path = path.with_suffix("")
    return path


def export_travelbook_interactive(
    session: Session,
    project_id: int,
    thumbs_dir: Path,
    destination: Path,
    *,
    size: int = DEFAULT_THUMBNAIL_SIZE,
    map_provider: str = "leaflet",
    map_link_color: str = DEFAULT_STAY_LINK_COLOR,
    map_track_color: str = DEFAULT_MAP_TRACK_COLOR,
    title: str | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> ExportResult:
    """Write a portable read-only map website. Originals are not copied.

    Photo pop-ups use cached thumbs. Double-click opens a 1920 px JPEG
    preview written into ``media/full/``.
    """

    assert_supported(PRODUCT_ID, "html")
    color = normalize_stay_link_color(map_link_color)
    track_color = normalize_map_track_color(map_track_color)
    scene = apply_map_track_color(
        build_map_scene(session, project_id, thumbs_dir, size=size),
        track_color,
    )
    if scene.empty:
        raise ExportError("Keine Karte zum Exportieren. Fotos mit Ort oder GPX-/IGC-Tracks importieren.")
    used_title = (title or "").strip() or _trip_title(session, project_id)
    dest = Path(destination)
    _prepare_destination(dest)
    html_path = dest / "index.html"
    media_dir = dest / "media"

    covers = [marker for marker in scene.markers if marker.kind == "cover" and marker.group_key]
    keys = [marker.group_key for marker in covers if marker.group_key]
    timeline = build_map_timeline(session, project_id, thumbs_dir, size=size)
    details: dict[str, tuple[MapScene, list[str]]] = {}
    total = max(len(keys) + 2, 1)
    if progress is not None:
        progress(1, total)
    for index, key in enumerate(keys, start=1):
        resolved = resolve_map_group(session, project_id, key, thumbs_dir, size=size)
        detail = apply_map_track_color(
            build_map_group_detail(
                session,
                project_id,
                key,
                thumbs_dir,
                size=size,
                resolved=resolved,
            ),
            track_color,
        )
        details[key] = (detail, list(resolved.youtube_urls) if resolved is not None else [])
        if progress is not None:
            progress(index + 1, total)

    copied = _copy_previews(
        [marker.preview_path for marker in scene.markers]
        + [marker.preview_path for detail, _urls in details.values() for marker in detail.markers]
        + [card.cover_path for card in timeline],
        media_dir,
    )
    scene = _remap_scene(scene, copied)
    remapped_details = {
        key: (_remap_scene(detail, copied), urls) for key, (detail, urls) in details.items()
    }
    timeline = tuple(_remap_card(card, copied) for card in timeline)
    fallback = _preview_fallback(scene, remapped_details, html_path)
    source_ids = _collect_source_ids(scene, remapped_details)
    media = _write_viewers(session, source_ids, dest / "media" / "full", html_path, fallback)
    FoliumMapBackend(
        tiles=tiles_for_map_provider(map_provider),
        link_color=color,
        map_track_color=track_color,
    ).render(scene, html_path)
    packed: dict[str, Any] = {}
    for key, (detail, youtube_urls) in remapped_details.items():
        payload = leaflet_payload(detail, html_path, read_only=True)
        payload["youtube_urls"] = youtube_urls
        packed[key] = payload
    text = html_path.read_text(encoding="utf-8")
    text = _localize_leaflet(text, dest)
    text = _inject_standalone(
        text,
        title=used_title,
        details=packed,
        timeline=timeline_js_cards(timeline, html_path),
        media=media,
    )
    html_path.write_text(text, encoding="utf-8")
    if progress is not None:
        progress(total, total)
    written = _written_tree(dest)
    return ExportResult(output_path=html_path, files_written=written)


def _trip_title(session: Session, project_id: int) -> str:
    trip = session.scalars(select(Trip).where(Trip.project_id == project_id)).first()
    name = (trip.title or "").strip() if trip is not None else ""
    return name or "Reise"


def _prepare_destination(destination: Path) -> None:
    if destination.exists():
        if not destination.is_dir():
            raise ExportError(f"Ziel ist kein Ordner: {destination}")
        if any(destination.iterdir()):
            raise ExportError(f"Zielordner ist nicht leer: {destination}")
        return
    destination.mkdir(parents=True, exist_ok=True)


def _copy_previews(paths: Iterable[Path | None], media_dir: Path) -> dict[Path, Path]:
    media_dir.mkdir(parents=True, exist_ok=True)
    copied: dict[Path, Path] = {}
    for raw in paths:
        if raw is None:
            continue
        source = raw.resolve()
        if source in copied or not source.is_file():
            continue
        suffix = source.suffix.lower() if source.suffix else ".jpg"
        if suffix not in _IMAGE_SUFFIXES:
            suffix = ".jpg"
        dest = media_dir / f"{len(copied):04d}{suffix}"
        shutil.copy2(source, dest)
        copied[source] = dest
    return copied


def _remap_preview(marker: MapMarker, copied: dict[Path, Path]) -> MapMarker:
    if marker.preview_path is None:
        return marker
    dest = copied.get(marker.preview_path.resolve())
    if dest is None:
        return replace(marker, preview_path=None)
    return replace(marker, preview_path=dest)


def _remap_scene(scene: MapScene, copied: dict[Path, Path]) -> MapScene:
    return replace(scene, markers=tuple(_remap_preview(marker, copied) for marker in scene.markers))


def _remap_card(card: MapTimelineCard, copied: dict[Path, Path]) -> MapTimelineCard:
    if card.cover_path is None:
        return card
    dest = copied.get(card.cover_path.resolve())
    if dest is None:
        return replace(card, cover_path=None)
    return replace(card, cover_path=dest)


def _collect_source_ids(
    scene: MapScene,
    details: dict[str, tuple[MapScene, list[str]]],
) -> set[int]:
    ids: set[int] = set()
    for marker in scene.markers:
        if marker.source_file_id:
            ids.add(marker.source_file_id)
    for detail, _urls in details.values():
        for marker in detail.markers:
            if marker.source_file_id:
                ids.add(marker.source_file_id)
    return ids


def _rel_src(html_path: Path, path: Path | None) -> str:
    if path is None or not path.is_file():
        return ""
    try:
        return path.resolve().relative_to(html_path.parent.resolve()).as_posix()
    except ValueError:
        return ""


def _preview_fallback(
    scene: MapScene,
    details: dict[str, tuple[MapScene, list[str]]],
    html_path: Path,
) -> dict[int, str]:
    found: dict[int, str] = {}
    markers = list(scene.markers)
    for detail, _urls in details.values():
        markers.extend(detail.markers)
    for marker in markers:
        if marker.source_file_id is None:
            continue
        href = _rel_src(html_path, marker.preview_path)
        if href:
            found[marker.source_file_id] = href
    return found


def _write_viewers(
    session: Session,
    source_ids: set[int],
    full_dir: Path,
    html_path: Path,
    fallback: dict[int, str],
) -> dict[str, dict[str, str]]:
    if not source_ids:
        return {}
    rows = session.scalars(select(SourceFile).where(SourceFile.id.in_(source_ids))).all()
    media: dict[str, dict[str, str]] = {}
    for row in rows:
        dest = full_dir / f"{row.id:04d}.jpg"
        src = ""
        path = Path(row.path)
        if path.is_file():
            written = write_viewer_jpeg(path, dest, rotation_degrees=row.rotation_degrees)
            if written is not None:
                src = _rel_src(html_path, written)
        if not src:
            src = fallback.get(row.id, "")
        if not src:
            continue
        media[str(row.id)] = {"src": src, "label": row.filename or ""}
    return media


def _localize_leaflet(html: str, dest_dir: Path) -> str:
    if not _VENDOR_DIR.is_dir():
        raise ExportError("Leaflet-Dateien für den HTML-Export fehlen.")
    vendor = dest_dir / "vendor" / "leaflet"
    vendor.mkdir(parents=True, exist_ok=True)
    for item in _VENDOR_DIR.iterdir():
        if item.is_file():
            shutil.copy2(item, vendor / item.name)
            continue
        if item.name != "images" or not item.is_dir():
            continue
        images = vendor / "images"
        images.mkdir(parents=True, exist_ok=True)
        for image in item.iterdir():
            if image.is_file():
                shutil.copy2(image, images / image.name)
    text = html
    for cdn, name in _CDN_ASSETS:
        text = text.replace(cdn, f"vendor/leaflet/{name}")
    return text


def _inject_standalone(
    html: str,
    *,
    title: str,
    details: dict[str, Any],
    timeline: list[dict[str, Any]],
    media: dict[str, dict[str, str]] | None = None,
) -> str:
    heading = f"<title>{escape(title)}</title>"
    if _TITLE.search(html):
        headed = _TITLE.sub(heading, html, count=1)
    elif "<head>" in html:
        headed = html.replace("<head>", f"<head>\n    {heading}", 1)
    else:
        headed = heading + html
    patch = json.dumps(
        {
            "read_only": True,
            "details": details,
            "timeline": timeline,
            "media": media or {},
        },
        ensure_ascii=True,
    )
    boot = (
        "<script>window.traveljournalConfig = Object.assign("
        f"window.traveljournalConfig || {{}}, {patch});</script>\n"
        "<style>.tj-rate{display:none!important}</style>\n" + chrome_markup(title=title)
    )
    marker = "</body>" if "</body>" in headed else "</html>"
    if marker in headed:
        return headed.replace(marker, boot + marker, 1)
    return headed + boot


def _written_tree(root: Path) -> tuple[Path, ...]:
    files = [path for path in root.rglob("*") if path.is_file()]
    return tuple(sorted(files))
