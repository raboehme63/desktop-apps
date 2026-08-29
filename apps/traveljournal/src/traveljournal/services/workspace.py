"""Application-level project workspace. Thin wrapper around travelcore."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from travelcore.config import AppSettings
from travelcore.database.models import Project, SourceFile, Trip
from travelcore.database.project_store import OpenProject, ProjectStore
from travelcore.exceptions import ProjectError
from travelcore.gps.ingest import set_track_external_url, track_urls_by_source
from travelcore.maps import (
    MapRenderResult,
    MapTimelineCard,
    build_map_timeline,
    ensure_map_cache,
    map_cache_identity,
    read_cached_map,
)
from travelcore.media.gallery import GalleryItem, list_gallery_items
from travelcore.media.indexer import count_by_kind
from travelcore.media.orientation import can_rotate_media
from travelcore.media.purge import SourceSyncPlan, plan_source_sync
from travelcore.media.thumbnails import cached_thumbnail_path, ensure_thumbnail, generate_project_thumbnails
from travelcore.media.types import GPS_EXTENSIONS
from travelcore.project_settings import (
    DEFAULT_STAY_LINK_COLOR,
    ProjectSettings,
    load_project_settings,
    rebase_source_file_paths,
    roots_equal,
    save_project_settings,
)
from travelcore.timeline import TimelineSnapshot
from travelcore.timeline import build as timeline_build
from travelcore.timeline import history as timeline_history
from travelcore.timeline import sections as timeline_sections
from traveljournal.services.edit_history import EditHistory

_CONFIG_DIR = Path.home() / "AppData" / "Local" / "TravelJournal"
_RECENT_PATH = _CONFIG_DIR / "recent.json"
_UI_CONFIG_PATH = _CONFIG_DIR / "config.json"
TIMELINE_MEDIA_TABS = ("all", "favorite", "reserve", "rejected")


def normalize_timeline_media_tab(value: object) -> str:
    if isinstance(value, str) and value in TIMELINE_MEDIA_TABS:
        return value
    return "all"


def resolve_projects_root(
    *,
    settings_root: str | None,
    stored_root: str | None,
    recents: list[Path],
) -> Path | None:
    """Prefer env/app settings, then saved config, then the last project parent."""

    for raw in (settings_root, stored_root):
        if not raw or not str(raw).strip():
            continue
        path = Path(str(raw).strip()).expanduser()
        if path.is_dir():
            return path.resolve()
    for recent in recents:
        parent = recent.parent
        if parent.is_dir():
            return parent.resolve()
    return None


class Workspace:
    def __init__(self) -> None:
        self._store = ProjectStore()
        self.current: OpenProject | None = None
        self.history = EditHistory()

    def create_project(self, parent: Path, name: str) -> OpenProject:
        self.history.clear()
        opened = self._store.create_under(parent, name)
        self.current = opened
        self._remember(opened.directory)
        self.remember_projects_root(parent)
        return opened

    def open_project(self, directory: Path) -> OpenProject:
        self.close()
        self.current = self._store.open(directory)
        self._remember(self.current.directory)
        self.remember_projects_root(self.current.directory.parent)
        return self.current

    def close(self) -> None:
        self.history.clear()
        self.current = None

    def rename(self, name: str) -> None:
        if self.current is None:
            raise ProjectError("Kein Projekt geöffnet.")
        self._store.rename(self.current, name)
        self.current = OpenProject(
            directory=self.current.directory,
            db_path=self.current.db_path,
            session_factory=self.current.session_factory,
            project_id=self.current.project_id,
            name=name,
        )

    def project_settings(self) -> ProjectSettings:
        if self.current is None:
            raise ProjectError("Kein Projekt geöffnet.")
        return load_project_settings(self.current.directory)

    def apply_project_settings(self, settings: ProjectSettings) -> int:
        """Write settings.toml and rebase indexed paths when the source root changes."""

        if self.current is None:
            raise ProjectError("Kein Projekt geöffnet.")
        self.history.clear()
        previous = load_project_settings(self.current.directory)
        save_project_settings(self.current.directory, settings)
        rebased = 0
        old_root = previous.paths.source_root
        new_root = settings.paths.source_root
        with self.current.session_factory() as session:
            project = session.get(Project, self.current.project_id)
            if project is None:
                raise ProjectError("Projektzeile fehlt.")
            project.default_timezone = settings.matching.default_timezone
            if new_root:
                project.source_root = str(Path(new_root).expanduser().resolve())
            else:
                project.source_root = None
            if old_root and new_root and not roots_equal(old_root, new_root):
                rebased = rebase_source_file_paths(
                    session,
                    self.current.project_id,
                    old_root=Path(old_root),
                    new_root=Path(new_root),
                )
            session.commit()
        return rebased

    def project_row(self) -> Project | None:
        if self.current is None:
            return None
        return self._store.get_project(self.current)

    def file_counts(self) -> dict[str, int]:
        if self.current is None:
            return {}
        with self.current.session_factory() as session:
            return count_by_kind(session, self.current.project_id)

    def source_files(self, limit: int | None = None) -> list[SourceFile]:
        if self.current is None:
            return []
        with self.current.session_factory() as session:
            query = (
                select(SourceFile)
                .where(SourceFile.project_id == self.current.project_id)
                .order_by(SourceFile.captured_at.asc().nulls_last(), SourceFile.filename.asc())
            )
            if limit is not None:
                query = query.limit(limit)
            rows = list(session.scalars(query))
            for row in rows:
                session.expunge(row)
            return rows

    def plan_source_sync(self, source_root: Path) -> SourceSyncPlan:
        """Count new and missing files in the source tree versus the index."""

        opened = self._require_open()
        with opened.session_factory() as session:
            return plan_source_sync(session, opened.project_id, source_root)

    def gps_track_urls(self) -> dict[int, str]:
        if self.current is None:
            return {}
        with self.current.session_factory() as session:
            return track_urls_by_source(session, self.current.project_id)

    def set_gps_track_url(self, source_file_id: int, url: str | None) -> None:
        self._mutate(lambda session: set_track_external_url(session, source_file_id, url))

    def gallery_items(self) -> list[GalleryItem]:
        if self.current is None:
            return []
        thumbs = self.current.directory / "thumbnails"
        size = AppSettings().default_thumbnail_size
        with self.current.session_factory() as session:
            return list_gallery_items(session, self.current.project_id, thumbs, size=size)

    def map_provider(self) -> str:
        opened = self._require_open()
        try:
            return load_project_settings(opened.directory).placeholders.map_provider
        except ProjectError:
            return "leaflet"

    def map_link_color(self) -> str:
        opened = self._require_open()
        try:
            return load_project_settings(opened.directory).placeholders.map_link_color
        except ProjectError:
            return DEFAULT_STAY_LINK_COLOR

    def map_show_photo_cones(self) -> bool:
        if self.current is None:
            return False
        try:
            return load_project_settings(self.current.directory).placeholders.map_show_photo_cones
        except ProjectError:
            return False

    def map_show_reserve(self) -> bool:
        if self.current is None:
            return False
        try:
            return load_project_settings(self.current.directory).placeholders.map_show_reserve
        except ProjectError:
            return False

    def set_map_display_flags(self, *, photo_cones: bool, show_reserve: bool) -> None:
        """Persist Zahnrad options in ``settings.toml`` for the open project."""

        if self.current is None:
            return
        try:
            settings = load_project_settings(self.current.directory)
        except ProjectError:
            return
        cones = bool(photo_cones)
        reserve = bool(show_reserve)
        if (
            settings.placeholders.map_show_photo_cones == cones
            and settings.placeholders.map_show_reserve == reserve
        ):
            return
        settings.placeholders.map_show_photo_cones = cones
        settings.placeholders.map_show_reserve = reserve
        save_project_settings(self.current.directory, settings)

    def map_cache_identity(self) -> dict[str, object]:
        opened = self._require_open()
        _thumbs, size = self._thumbs_and_size()
        return map_cache_identity(
            db_path=opened.db_path,
            map_provider=self.map_provider(),
            thumbnail_size=size,
            map_link_color=self.map_link_color(),
        )

    def load_cached_map(self) -> MapRenderResult | None:
        if self.current is None:
            return None
        return read_cached_map(self.current.directory, self.map_cache_identity())

    def render_map(self, *, force: bool = False) -> MapRenderResult:
        """Reuse ``cache/map.html`` when the stamp matches, otherwise rebuild."""

        opened = self._require_open()
        thumbs, size = self._thumbs_and_size()
        provider = self.map_provider()
        return ensure_map_cache(
            opened.session_factory,
            opened.project_id,
            opened.directory,
            thumbs,
            db_path=opened.db_path,
            size=size,
            map_provider=provider,
            map_link_color=self.map_link_color(),
            force=force,
        )

    def map_group_detail(self, group_key: str) -> dict[str, object]:
        """Leaflet payload for one section or leftover day."""

        opened = self._require_open()
        thumbs, size = self._thumbs_and_size()
        from travelcore.maps import leaflet_payload
        from travelcore.maps.groups import build_map_group_detail, resolve_map_group

        html_path = opened.directory / "cache" / "map.html"
        with opened.session_factory() as session:
            resolved = resolve_map_group(session, opened.project_id, group_key, thumbs, size=size)
            scene = build_map_group_detail(
                session,
                opened.project_id,
                group_key,
                thumbs,
                size=size,
                resolved=resolved,
            )
        payload = leaflet_payload(scene, html_path)
        payload["youtube_urls"] = list(resolved.youtube_urls) if resolved is not None else []
        return payload

    def map_group_gallery_items(self, group_key: str) -> list[GalleryItem]:
        """Timeline-order media of one map entry, for the media inspector."""

        opened = self._require_open()
        thumbs, size = self._thumbs_and_size()
        from travelcore.maps.groups import resolve_map_group

        with opened.session_factory() as session:
            resolved = resolve_map_group(session, opened.project_id, group_key, thumbs, size=size)
        if resolved is None:
            return []
        return self.gallery_items_for_ids(resolved.source_ids)

    def map_timeline_cards(self) -> tuple[MapTimelineCard, ...]:
        """Compact section cards for the horizontal strip under the map."""

        if self.current is None:
            return ()
        opened = self.current
        thumbs, size = self._thumbs_and_size()
        with opened.session_factory() as session:
            return build_map_timeline(session, opened.project_id, thumbs, size=size)

    def gallery_items_for_ids(self, source_ids: list[int]) -> list[GalleryItem]:
        wanted = [item_id for item_id in source_ids if item_id]
        if not wanted:
            return []
        opened = self._require_open()
        thumbs, size = self._thumbs_and_size()
        from travelcore.media.gallery import list_gallery_items

        with opened.session_factory() as session:
            found = list_gallery_items(
                session,
                opened.project_id,
                thumbs,
                size=size,
                source_file_ids=wanted,
            )
        by_id = {item.source_file_id: item for item in found}
        return [by_id[item_id] for item_id in source_ids if item_id in by_id]

    def sync_timeline(self) -> TimelineSnapshot:
        opened = self._require_open()
        thumbs, size = self._thumbs_and_size()
        try:
            with opened.session_factory() as session:
                project = session.get(Project, opened.project_id)
                if project is None:
                    raise ProjectError("Projektzeile fehlt.")
                snapshot = timeline_build.sync_timeline(session, project, thumbs_dir=thumbs, size=size)
                session.commit()
                return snapshot
        except OperationalError as exc:
            raise ProjectError(
                "Die Projektdatenbank ist gerade beschäftigt. "
                "Bitte einen Moment warten und die Seite erneut öffnen."
            ) from exc

    def load_timeline(self) -> TimelineSnapshot | None:
        if self.current is None:
            return None
        thumbs, size = self._thumbs_and_size()
        with self.current.session_factory() as session:
            project = session.get(Project, self.current.project_id)
            if project is None:
                return None
            return timeline_build.load_timeline(session, project, thumbs_dir=thumbs, size=size)

    def save_day_text(self, day_id: int, *, title: str, notes: str) -> None:
        self._save_entry_text("day", day_id, title=title, notes=notes)

    def save_trip_title(self, trip_id: int, title: str) -> None:
        previous = self._read_trip_title(trip_id) or ""
        cleaned = title.strip()
        if not cleaned or cleaned == previous.strip():
            return
        self._apply_trip_title(trip_id, cleaned)
        self.history.push(
            "Reisetitel",
            lambda: self._apply_trip_title(trip_id, previous),
            lambda: self._apply_trip_title(trip_id, cleaned),
        )

    def save_section_text(self, section_id: int, *, title: str, notes: str) -> None:
        self._save_entry_text("section", section_id, title=title, notes=notes)

    def save_youtube_urls(self, kind: str, entity_id: int, urls: list[str]) -> None:
        if kind == "section":
            self._mutate(
                lambda session: timeline_sections.save_section_youtube_urls(session, entity_id, urls)
            )
            return
        self._mutate(lambda session: timeline_build.save_day_youtube_urls(session, entity_id, urls))

    def save_leonardo_urls(self, kind: str, entity_id: int, urls: list[str]) -> None:
        if kind == "section":
            self._mutate(
                lambda session: timeline_sections.save_section_leonardo_urls(session, entity_id, urls)
            )
            return
        self._mutate(lambda session: timeline_build.save_day_leonardo_urls(session, entity_id, urls))

    def create_section(
        self,
        source_file_ids: list[int],
        *,
        kind: str,
        mode: str | None = None,
        title: str | None = None,
        notes: str | None = None,
        location_name: str | None = None,
        location_from: str | None = None,
        location_to: str | None = None,
        youtube_urls: list[str] | None = None,
        leonardo_urls: list[str] | None = None,
        cover_source_file_id: int | None = None,
        started_at: datetime | None = None,
        ended_at: datetime | None = None,
        record: bool = True,
    ) -> int:
        ids = list(dict.fromkeys(source_file_ids))
        before = self._capture_placement(ids)
        section_id = self._apply_create(
            ids,
            kind=kind,
            mode=mode,
            title=title,
            notes=notes,
            location_name=location_name,
            location_from=location_from,
            location_to=location_to,
            youtube_urls=youtube_urls,
            leonardo_urls=leonardo_urls,
            cover_source_file_id=cover_source_file_id,
            started_at=started_at,
            ended_at=ended_at,
        )
        if record:
            created = [section_id]
            self.history.push(
                "Abschnitt einfügen",
                lambda: self._undo_created_section(before, created),
                lambda: created.__setitem__(
                    0,
                    self._apply_create(
                        ids,
                        kind=kind,
                        mode=mode,
                        title=title,
                        notes=notes,
                        location_name=location_name,
                        location_from=location_from,
                        location_to=location_to,
                        youtube_urls=youtube_urls,
                        leonardo_urls=leonardo_urls,
                        cover_source_file_id=cover_source_file_id,
                        started_at=started_at,
                        ended_at=ended_at,
                    ),
                ),
            )
        return section_id

    def update_section_kind(self, section_id: int, kind: str, *, mode: str | None = None) -> None:
        before = self._capture_section_edit(section_id)
        self._apply_section_kind(section_id, kind, mode=mode)
        if before is None:
            return
        self.history.push(
            "Abschnittstyp",
            lambda: self._apply_restore(before),
            lambda: self._apply_section_kind(section_id, kind, mode=mode),
        )

    def dissolve_section(self, section_id: int) -> None:
        before = self._capture_section_edit(section_id)
        self._apply_dissolve(section_id)
        if before is None:
            return
        self.history.push(
            "Abschnitt auflösen",
            lambda: self._apply_restore(before),
            lambda: self._apply_dissolve(section_id),
        )

    def delete_section(self, section_id: int) -> None:
        before = self._capture_section_edit(section_id)
        self._apply_delete(section_id)
        if before is None:
            return
        self.history.push(
            "Abschnitt löschen",
            lambda: self._apply_restore(before),
            lambda: self._apply_delete(section_id),
        )

    def set_section_pin(self, section_id: int, latitude: float, longitude: float) -> None:
        previous = self._read_section_pin(section_id)
        self._apply_section_pin(section_id, latitude, longitude)
        self.history.push(
            "Kartenposition",
            lambda: self._apply_section_pin(section_id, previous[0], previous[1]),
            lambda: self._apply_section_pin(section_id, latitude, longitude),
        )

    def set_section_span(
        self,
        section_id: int,
        started_at: datetime,
        ended_at: datetime | None = None,
    ) -> None:
        before = self._capture_section_edit(section_id)
        self._apply_section_span(section_id, started_at, ended_at)
        if before is None:
            return
        self.history.push(
            "Datum",
            lambda: self._apply_restore(before),
            lambda: self._apply_section_span(section_id, started_at, ended_at),
        )

    def park_media(self, source_file_ids: list[int]) -> None:
        ids = list(dict.fromkeys(source_file_ids))
        if not ids:
            return
        before = self._capture_placement(ids)
        self._apply_park(ids)
        self.history.push("Pool", lambda: self._apply_restore(before), lambda: self._apply_park(ids))

    def unpark_media(self, source_file_ids: list[int]) -> None:
        ids = list(dict.fromkeys(source_file_ids))
        if not ids:
            return
        self._apply_unpark(ids)
        self.history.push("Zurückholen", lambda: self._apply_park(ids), lambda: self._apply_unpark(ids))

    def move_members(
        self,
        section_id: int,
        source_file_ids: list[int],
        *,
        keep_gps: bool = True,
    ) -> None:
        ids = list(dict.fromkeys(source_file_ids))
        if not ids:
            return
        before = self._capture_placement(ids, extra_section_ids=(section_id,))
        self._apply_move(section_id, ids, keep_gps=keep_gps)
        self.history.push(
            "Zuordnen",
            lambda: self._apply_restore(before),
            lambda: self._apply_move(section_id, ids, keep_gps=keep_gps),
        )

    def set_journal_at(
        self,
        source_file_ids: list[int],
        journal_at: datetime | None,
        *,
        timezone_name: str | None = None,
    ) -> None:
        ids = list(dict.fromkeys(source_file_ids))
        if not ids:
            return
        before = self._capture_placement(ids)
        self._apply_journal_at(ids, journal_at, timezone_name=timezone_name)
        self.history.push(
            "Journal-Zeit",
            lambda: self._apply_restore(before),
            lambda: self._apply_journal_at(ids, journal_at, timezone_name=timezone_name),
        )

    def reset_journal(self, source_file_ids: list[int]) -> None:
        ids = list(dict.fromkeys(source_file_ids))
        if not ids:
            return
        before = self._capture_placement(ids)
        self._apply_reset_journal(ids)
        self.history.push(
            "Originalzeit",
            lambda: self._apply_restore(before),
            lambda: self._apply_reset_journal(ids),
        )

    def sort_members_by_journal(self, section_id: int) -> None:
        self._mutate(lambda session: timeline_sections.sort_members_by_journal(session, section_id))

    def set_entry_cover(self, kind: str, entity_id: int, source_file_id: int | None) -> None:
        previous = self._read_entry_cover(kind, entity_id)
        if previous == source_file_id:
            return
        self._apply_entry_cover(kind, entity_id, source_file_id)
        self.history.push(
            "Titelbild",
            lambda: self._apply_entry_cover(kind, entity_id, previous),
            lambda: self._apply_entry_cover(kind, entity_id, source_file_id),
        )

    def thumbs_dir(self) -> Path | None:
        if self.current is None:
            return None
        path = self.current.directory / "thumbnails"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def set_favorite(self, source_file_id: int, value: bool) -> None:
        self.set_sort_status(source_file_id, "favorite" if value else None)

    def set_sort_status(self, source_file_id: int, status: str | None) -> None:
        previous = self._read_sort_status(source_file_id)
        if previous == status:
            return
        self._apply_sort_status(source_file_id, status)
        self.history.push(
            "Bewertung",
            lambda: self._apply_sort_status(source_file_id, previous),
            lambda: self._apply_sort_status(source_file_id, status),
        )

    def add_rotation(self, source_file_id: int, delta_degrees: int) -> tuple[int, Path]:
        """Rotate a photo/video clockwise in 90° steps. Originals stay read-only."""

        result = self._apply_rotation(source_file_id, delta_degrees)
        if delta_degrees:
            self.history.push(
                "Drehung",
                lambda: self._apply_rotation(source_file_id, -delta_degrees),
                lambda: self._apply_rotation(source_file_id, delta_degrees),
            )
        return result

    def generate_missing_thumbnails(self) -> int:
        if self.current is None:
            return 0
        settings = AppSettings()
        with self.current.session_factory() as session:
            project = session.get(Project, self.current.project_id)
            if project is None:
                return 0
            result = generate_project_thumbnails(
                session,
                project,
                self.current.directory / "thumbnails",
                size=settings.default_thumbnail_size,
            )
        return result.written

    def projects_root(self) -> Path | None:
        stored = self._load_ui_config().get("projects_root")
        stored_text = stored if isinstance(stored, str) else None
        return resolve_projects_root(
            settings_root=AppSettings().projects_root,
            stored_root=stored_text,
            recents=self.recent_projects(),
        )

    def timeline_media_tab(self) -> str:
        return normalize_timeline_media_tab(self._load_ui_config().get("timeline_media_tab"))

    def set_timeline_media_tab(self, key: str) -> None:
        normalized = normalize_timeline_media_tab(key)
        data = self._load_ui_config()
        if data.get("timeline_media_tab") == normalized:
            return
        data["timeline_media_tab"] = normalized
        self._save_ui_config(data)

    def sidebar_collapsed(self) -> bool:
        return self._load_ui_config().get("sidebar_collapsed") is True

    def set_sidebar_collapsed(self, collapsed: bool) -> None:
        flag = bool(collapsed)
        data = self._load_ui_config()
        if bool(data.get("sidebar_collapsed")) == flag:
            return
        data["sidebar_collapsed"] = flag
        self._save_ui_config(data)

    def timeline_pool_visible(self) -> bool:
        return self._load_ui_config().get("timeline_pool_visible") is True

    def set_timeline_pool_visible(self, visible: bool) -> None:
        flag = bool(visible)
        data = self._load_ui_config()
        if bool(data.get("timeline_pool_visible")) == flag:
            return
        data["timeline_pool_visible"] = flag
        self._save_ui_config(data)

    def pool_width(self) -> int:
        from traveljournal.widgets.pool_pane import clamp_pool_width

        return clamp_pool_width(self._load_ui_config().get("pool_width"))

    def set_pool_width(self, width: int) -> None:
        from traveljournal.widgets.pool_pane import clamp_pool_width

        clamped = clamp_pool_width(width)
        data = self._load_ui_config()
        if data.get("pool_width") == clamped:
            return
        data["pool_width"] = clamped
        self._save_ui_config(data)

    def pool_media_tab(self) -> str:
        return normalize_timeline_media_tab(self._load_ui_config().get("pool_media_tab"))

    def set_pool_media_tab(self, key: str) -> None:
        normalized = normalize_timeline_media_tab(key)
        data = self._load_ui_config()
        if data.get("pool_media_tab") == normalized:
            return
        data["pool_media_tab"] = normalized
        self._save_ui_config(data)

    def show_rejected_in_all(self) -> bool:
        return self._load_ui_config().get("show_rejected_in_all") is True

    def set_show_rejected_in_all(self, visible: bool) -> None:
        flag = bool(visible)
        data = self._load_ui_config()
        if bool(data.get("show_rejected_in_all")) == flag:
            return
        data["show_rejected_in_all"] = flag
        self._save_ui_config(data)

    def inspector_size(self) -> tuple[int, int]:
        from traveljournal.widgets.media_inspector import clamp_inspector_size

        data = self._load_ui_config()
        return clamp_inspector_size(data.get("inspector_width"), data.get("inspector_height"))

    def inspector_maximized(self) -> bool:
        return self._load_ui_config().get("inspector_maximized") is True

    def set_inspector_geometry(self, width: int, height: int, *, maximized: bool = False) -> None:
        from traveljournal.widgets.media_inspector import clamp_inspector_size

        clamped_w, clamped_h = clamp_inspector_size(width, height)
        flag = bool(maximized)
        data = self._load_ui_config()
        if (
            data.get("inspector_width") == clamped_w
            and data.get("inspector_height") == clamped_h
            and bool(data.get("inspector_maximized")) == flag
        ):
            return
        data["inspector_width"] = clamped_w
        data["inspector_height"] = clamped_h
        data["inspector_maximized"] = flag
        self._save_ui_config(data)

    def remember_projects_root(self, directory: Path) -> None:
        path = directory.expanduser().resolve()
        if not path.is_dir():
            return
        data = self._load_ui_config()
        data["projects_root"] = str(path)
        self._save_ui_config(data)

    def recent_projects(self) -> list[Path]:
        if not _RECENT_PATH.is_file():
            return []
        try:
            raw = json.loads(_RECENT_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        paths = [Path(item) for item in raw if isinstance(item, str)]
        return [path for path in paths if (path / "project.sqlite").is_file()]

    def _remember(self, directory: Path) -> None:
        items = [str(directory)]
        for existing in self.recent_projects():
            if existing.resolve() != directory.resolve():
                items.append(str(existing))
        _RECENT_PATH.parent.mkdir(parents=True, exist_ok=True)
        _RECENT_PATH.write_text(json.dumps(items[:10], indent=2), encoding="utf-8")

    def _load_ui_config(self) -> dict[str, object]:
        if not _UI_CONFIG_PATH.is_file():
            return {}
        try:
            raw = json.loads(_UI_CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return raw if isinstance(raw, dict) else {}

    def _save_ui_config(self, data: dict[str, object]) -> None:
        _UI_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        _UI_CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _require_open(self) -> OpenProject:
        if self.current is None:
            raise ProjectError("Kein Projekt geöffnet.")
        return self.current

    def _thumbs_and_size(self) -> tuple[Path, int]:
        opened = self._require_open()
        thumbs = opened.directory / "thumbnails"
        thumbs.mkdir(parents=True, exist_ok=True)
        return thumbs, AppSettings().default_thumbnail_size

    def _mutate(self, action: Callable[..., object]) -> None:
        opened = self._require_open()
        with opened.session_factory() as session:
            action(session)
            session.commit()

    def _read_sort_status(self, source_file_id: int) -> str | None:
        opened = self._require_open()
        with opened.session_factory() as session:
            return timeline_history.photo_sort_status(session, source_file_id)

    def _apply_sort_status(self, source_file_id: int, status: str | None) -> None:
        self._mutate(lambda session: timeline_build.set_photo_sort_status(session, source_file_id, status))

    def _read_section_pin(self, section_id: int) -> tuple[float | None, float | None]:
        opened = self._require_open()
        with opened.session_factory() as session:
            return timeline_history.section_pin(session, section_id)

    def _apply_section_pin(
        self,
        section_id: int,
        latitude: float | None,
        longitude: float | None,
    ) -> None:
        self._mutate(
            lambda session: timeline_sections.set_section_pin(session, section_id, latitude, longitude)
        )

    def _apply_section_kind(self, section_id: int, kind: str, *, mode: str | None = None) -> None:
        self._mutate(
            lambda session: timeline_sections.update_section_kind(session, section_id, kind, mode=mode)
        )

    def _apply_section_span(
        self,
        section_id: int,
        started_at: datetime,
        ended_at: datetime | None,
    ) -> None:
        self._mutate(
            lambda session: timeline_sections.set_section_span(
                session, section_id, started_at, ended_at=ended_at
            )
        )

    def _apply_create(
        self,
        source_file_ids: list[int],
        *,
        kind: str,
        mode: str | None = None,
        title: str | None = None,
        notes: str | None = None,
        location_name: str | None = None,
        location_from: str | None = None,
        location_to: str | None = None,
        youtube_urls: list[str] | None = None,
        leonardo_urls: list[str] | None = None,
        cover_source_file_id: int | None = None,
        started_at: datetime | None = None,
        ended_at: datetime | None = None,
    ) -> int:
        opened = self._require_open()
        with opened.session_factory() as session:
            trip_id = session.scalar(
                select(Trip.id).where(Trip.project_id == opened.project_id).order_by(Trip.id.asc())
            )
            if trip_id is None:
                raise ProjectError("Keine Timeline. Bitte zuerst die Timeline aktualisieren.")
            section = timeline_sections.create_section(
                session,
                trip_id,
                source_file_ids,
                kind=kind,
                mode=mode,
                title=title,
                notes=notes,
                location_name=location_name,
                location_from=location_from,
                location_to=location_to,
                youtube_urls=youtube_urls,
                leonardo_urls=leonardo_urls,
                cover_source_file_id=cover_source_file_id,
                started_at=started_at,
                ended_at=ended_at,
            )
            section_id = section.id
            session.commit()
        return section_id

    def _apply_delete(self, section_id: int) -> None:
        self._mutate(lambda session: timeline_sections.delete_section(session, section_id))

    def _apply_dissolve(self, section_id: int) -> None:
        self._mutate(lambda session: timeline_sections.dissolve_section(session, section_id))

    def _apply_journal_at(
        self,
        source_file_ids: list[int],
        journal_at: datetime | None,
        *,
        timezone_name: str | None = None,
    ) -> None:
        self._mutate(
            lambda session: timeline_sections.set_journal_at(
                session, source_file_ids, journal_at, timezone_name=timezone_name
            )
        )

    def _apply_reset_journal(self, source_file_ids: list[int]) -> None:
        self._mutate(lambda session: timeline_sections.reset_journal(session, source_file_ids))

    def _apply_entry_cover(self, kind: str, entity_id: int, source_file_id: int | None) -> None:
        self._mutate(lambda session: timeline_build.set_entry_cover(session, kind, entity_id, source_file_id))

    def _apply_rotation(self, source_file_id: int, delta_degrees: int) -> tuple[int, Path]:
        opened = self._require_open()
        thumbs, size = self._thumbs_and_size()
        with opened.session_factory() as session:
            degrees = timeline_build.add_source_rotation(session, source_file_id, delta_degrees)
            row = session.get(SourceFile, source_file_id)
            if row is None:
                raise ProjectError("Datei nicht gefunden.")
            dest = cached_thumbnail_path(
                thumbs,
                source_file_id=row.id,
                sha256=row.sha256,
                size=size,
                rotation_degrees=degrees,
            )
            source_path = Path(row.path)
            extension = row.extension
            session.commit()
        if can_rotate_media(extension) and source_path.suffix.lower() not in GPS_EXTENSIONS:
            try:
                if dest.is_file():
                    dest.unlink()
            except OSError:
                pass
            ensure_thumbnail(source_path, dest, size=size, rotation_degrees=degrees)
        return degrees, dest

    def _undo_created_section(
        self,
        before: timeline_history.JournalEdit,
        created: list[int],
    ) -> None:
        self._apply_restore(before)
        if created and created[0]:
            self._apply_delete(created[0])

    def _apply_park(self, source_file_ids: list[int]) -> None:
        self._mutate(lambda session: timeline_sections.park_media(session, source_file_ids))

    def _apply_unpark(self, source_file_ids: list[int]) -> None:
        opened = self._require_open()
        with opened.session_factory() as session:
            timeline_sections.unpark_media(session, source_file_ids)
            project = session.get(Project, opened.project_id)
            if project is not None:
                thumbs, size = self._thumbs_and_size()
                timeline_build.sync_timeline(session, project, thumbs_dir=thumbs, size=size)
            session.commit()

    def _apply_move(self, section_id: int, source_file_ids: list[int], *, keep_gps: bool) -> None:
        self._mutate(
            lambda session: timeline_sections.move_members(
                session, section_id, source_file_ids, keep_gps=keep_gps
            )
        )

    def _capture_placement(
        self,
        source_file_ids: list[int],
        extra_section_ids: tuple[int, ...] = (),
    ) -> timeline_history.JournalEdit:
        opened = self._require_open()
        with opened.session_factory() as session:
            return timeline_history.capture_placement_edit(
                session, source_file_ids, extra_section_ids=extra_section_ids
            )

    def _capture_section_edit(self, section_id: int) -> timeline_history.JournalEdit | None:
        opened = self._require_open()
        with opened.session_factory() as session:
            return timeline_history.capture_section_edit(session, section_id)

    def _apply_restore(self, edit: timeline_history.JournalEdit) -> None:
        self._mutate(lambda session: timeline_history.restore_journal_edit(session, edit))

    def _read_entry_title(self, kind: str, entity_id: int) -> str | None:
        opened = self._require_open()
        with opened.session_factory() as session:
            return timeline_history.entry_title(session, kind, entity_id)

    def _read_entry_notes(self, kind: str, entity_id: int) -> str | None:
        opened = self._require_open()
        with opened.session_factory() as session:
            return timeline_history.entry_notes(session, kind, entity_id)

    def _apply_entry_text(self, kind: str, entity_id: int, *, title: str, notes: str) -> None:
        if kind == "section":
            self._mutate(
                lambda session: timeline_sections.save_section_text(
                    session, entity_id, title=title, notes=notes
                )
            )
            return
        self._mutate(
            lambda session: timeline_build.save_day_text(session, entity_id, title=title, notes=notes)
        )

    def _read_trip_title(self, trip_id: int) -> str | None:
        opened = self._require_open()
        with opened.session_factory() as session:
            return timeline_history.trip_title(session, trip_id)

    def _apply_trip_title(self, trip_id: int, title: str) -> None:
        self._mutate(lambda session: timeline_build.save_trip_title(session, trip_id, title))

    def _read_entry_cover(self, kind: str, entity_id: int) -> int | None:
        opened = self._require_open()
        with opened.session_factory() as session:
            return timeline_history.entry_cover(session, kind, entity_id)

    def _save_entry_text(self, kind: str, entity_id: int, *, title: str, notes: str) -> None:
        previous_title = self._read_entry_title(kind, entity_id)
        previous_notes = self._read_entry_notes(kind, entity_id) or ""
        self._apply_entry_text(kind, entity_id, title=title, notes=notes)
        applied_title = title.strip() or previous_title
        title_changed = (previous_title or "").strip() != (applied_title or "").strip()
        notes_changed = previous_notes != notes
        if not title_changed and not notes_changed:
            return
        label = "Titel" if title_changed and not notes_changed else "Tagebucheintrag"
        self.history.push(
            label,
            lambda: self._apply_entry_text(
                kind, entity_id, title=previous_title or "", notes=previous_notes
            ),
            lambda: self._apply_entry_text(kind, entity_id, title=applied_title or "", notes=notes),
        )
