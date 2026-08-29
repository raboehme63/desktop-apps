"""Persistent Folium HTML cache. Original media files are never written."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from travelcore.maps.backend import OSM_LATIN_TILES, FoliumMapBackend
from travelcore.maps.scene import MapScene, build_map_scene
from travelcore.project_settings import DEFAULT_STAY_LINK_COLOR, normalize_stay_link_color

MAP_CACHE_VERSION = 67
MAP_HTML_NAME = "map.html"
MAP_STAMP_NAME = "map.stamp.json"


@dataclass(frozen=True, slots=True)
class MapRenderResult:
    """What the UI needs to show a map without rebuilding the scene."""

    html_path: Path | None
    empty: bool
    from_cache: bool
    tracks: int = 0
    flights: int = 0
    photos: int = 0
    places: int = 0
    groups: int = 0
    render_seq: int = 0

    def summary_line(self) -> str:
        if self.empty:
            return "Keine GPS-Daten im Index. Fotos mit Ort, GPX- oder IGC-Tracks importieren."
        return (
            f"{self.groups} Titelbilder (Tage, Transfers und Aufenthalte). "
            "Klick auf ein Titelbild zeigt Fotos und Tracks dieses Eintrags."
        )


def map_html_path(project_dir: Path) -> Path:
    return project_dir / "cache" / MAP_HTML_NAME


def map_stamp_path(project_dir: Path) -> Path:
    return project_dir / "cache" / MAP_STAMP_NAME


def tiles_for_map_provider(map_provider: str) -> str | None:
    if map_provider.strip().lower() == "offline":
        return None
    return OSM_LATIN_TILES


def map_cache_identity(
    *,
    db_path: Path,
    map_provider: str,
    thumbnail_size: int,
    map_link_color: str = DEFAULT_STAY_LINK_COLOR,
) -> dict[str, Any]:
    """Fingerprint of inputs that change the rendered HTML."""

    files: list[dict[str, int | str]] = []
    for path in (db_path, Path(f"{db_path}-wal"), Path(f"{db_path}-shm")):
        if path.is_file():
            stat = path.stat()
            files.append({"name": path.name, "mtime_ns": stat.st_mtime_ns, "size": stat.st_size})
        else:
            files.append({"name": path.name, "mtime_ns": 0, "size": 0})
    return {
        "version": MAP_CACHE_VERSION,
        "files": files,
        "map_provider": map_provider.strip().lower(),
        "map_link_color": normalize_stay_link_color(map_link_color),
        "thumbnail_size": int(thumbnail_size),
    }


def read_cached_map(
    project_dir: Path,
    identity: dict[str, Any],
) -> MapRenderResult | None:
    """Return the stamped result when HTML (or emptiness) still matches ``identity``."""

    stamp = _read_stamp(project_dir)
    if stamp is None or not _identity_matches(stamp, identity):
        return None
    empty = bool(stamp.get("empty"))
    html_path = map_html_path(project_dir)
    if empty:
        return _result_from_stamp(stamp, html_path=None, from_cache=True)
    if not html_path.is_file():
        return None
    return _result_from_stamp(stamp, html_path=html_path, from_cache=True)


def is_map_cache_current(project_dir: Path, identity: dict[str, Any]) -> bool:
    return read_cached_map(project_dir, identity) is not None


def ensure_map_cache(
    session_factory: Callable[[], Session],
    project_id: int,
    project_dir: Path,
    thumbs_dir: Path,
    *,
    db_path: Path,
    size: int,
    map_provider: str,
    map_link_color: str = DEFAULT_STAY_LINK_COLOR,
    force: bool = False,
) -> MapRenderResult:
    """Reuse ``cache/map.html`` when the stamp still matches, otherwise rebuild.

    The stamp is written after the session closes so a SQLite WAL close cannot
    immediately invalidate the cache.
    """

    color = normalize_stay_link_color(map_link_color)
    identity = map_cache_identity(
        db_path=db_path,
        map_provider=map_provider,
        thumbnail_size=size,
        map_link_color=color,
    )
    if not force:
        cached = read_cached_map(project_dir, identity)
        if cached is not None:
            return cached
    tiles = tiles_for_map_provider(map_provider)
    with session_factory() as session:
        scene = build_map_scene(session, project_id, thumbs_dir, size=size)
        counts = counts_from_scene(scene)
        html_path = map_html_path(project_dir)
        html_path.parent.mkdir(parents=True, exist_ok=True)
        seq = _next_render_seq(project_dir)
        if scene.empty:
            if html_path.is_file():
                html_path.unlink()
            rendered = MapRenderResult(html_path=None, empty=True, from_cache=False, render_seq=seq, **counts)
        else:
            FoliumMapBackend(tiles=tiles, link_color=color).render(scene, html_path)
            rendered = MapRenderResult(
                html_path=html_path,
                empty=False,
                from_cache=False,
                render_seq=seq,
                **counts,
            )
    identity = map_cache_identity(
        db_path=db_path,
        map_provider=map_provider,
        thumbnail_size=size,
        map_link_color=color,
    )
    _write_stamp(
        project_dir,
        identity,
        empty=rendered.empty,
        render_seq=rendered.render_seq,
        counts={
            "tracks": rendered.tracks,
            "flights": rendered.flights,
            "photos": rendered.photos,
            "places": rendered.places,
            "groups": rendered.groups,
        },
    )
    return rendered


def counts_from_scene(scene: MapScene) -> dict[str, int]:
    groups = sum(1 for item in scene.markers if item.kind == "cover")
    photos = sum(1 for item in scene.markers if item.kind in {"photo", "video"})
    places = sum(1 for item in scene.markers if item.kind == "place")
    flights = sum(1 for item in scene.polylines if item.kind == "flight")
    tracks = len(scene.polylines) - flights
    return {
        "tracks": tracks,
        "flights": flights,
        "photos": photos,
        "places": places,
        "groups": groups,
    }


def _identity_matches(stamp: dict[str, Any], identity: dict[str, Any]) -> bool:
    return (
        stamp.get("version") == identity.get("version")
        and stamp.get("files") == identity.get("files")
        and stamp.get("map_provider") == identity.get("map_provider")
        and stamp.get("map_link_color") == identity.get("map_link_color")
        and stamp.get("thumbnail_size") == identity.get("thumbnail_size")
    )


def _result_from_stamp(
    stamp: dict[str, Any],
    *,
    html_path: Path | None,
    from_cache: bool,
) -> MapRenderResult:
    return MapRenderResult(
        html_path=html_path,
        empty=bool(stamp.get("empty")),
        from_cache=from_cache,
        tracks=int(stamp.get("tracks") or 0),
        flights=int(stamp.get("flights") or 0),
        photos=int(stamp.get("photos") or 0),
        places=int(stamp.get("places") or 0),
        groups=int(stamp.get("groups") or 0),
        render_seq=int(stamp.get("render_seq") or 0),
    )


def _read_stamp(project_dir: Path) -> dict[str, Any] | None:
    path = map_stamp_path(project_dir)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def _next_render_seq(project_dir: Path) -> int:
    stamp = _read_stamp(project_dir)
    if stamp is None:
        return 1
    try:
        return int(stamp.get("render_seq") or 0) + 1
    except (TypeError, ValueError):
        return 1


def _write_stamp(
    project_dir: Path,
    identity: dict[str, Any],
    *,
    empty: bool,
    render_seq: int,
    counts: dict[str, int],
) -> None:
    path = map_stamp_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        **identity,
        "empty": empty,
        "render_seq": int(render_seq),
        **counts,
    }
    path.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")
