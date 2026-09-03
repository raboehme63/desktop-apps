"""Application-level project workspace. Thin wrapper around travelcore."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from travelcore.config import AppSettings
from travelcore.database.models import Project, SourceFile, Trip
from travelcore.database.project_catalog import ProjectDescriptor, list_project_catalog
from travelcore.database.project_store import OpenProject, ProjectStore, project_cache_dir
from travelcore.exceptions import ProjectError, ReadOnlyProjectError
from travelcore.export.photo_layouts import set_user_layouts_dir
from travelcore.gps.ingest import set_track_external_url, track_urls_by_source
from travelcore.image_analysis import QualityRunResult, analyze_project_photos
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
    DEFAULT_MAP_TRACK_COLOR,
    DEFAULT_STAY_LINK_COLOR,
    ProjectSettings,
    load_project_settings,
    rebase_source_file_paths,
    roots_equal,
    save_project_settings,
)
from travelcore.similarity import clusters as media_clusters
from travelcore.similarity.clusters import ClusterRecord, MediaStats
from travelcore.timeline import TimelineSnapshot
from travelcore.timeline import build as timeline_build
from travelcore.timeline import history as timeline_history
from travelcore.timeline import sections as timeline_sections
from traveljournal.services.edit_history import EditHistory

_CONFIG_DIR = Path.home() / "AppData" / "Local" / "TravelJournal"
_UI_CONFIG_PATH = _CONFIG_DIR / "config.json"
TIMELINE_MEDIA_TABS = ("all", "favorite", "reserve", "rejected")


def _recent_file() -> Path:
    """Resolve at call time so tests can patch ``_CONFIG_DIR``."""

    return _CONFIG_DIR / "recent.json"


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
        set_user_layouts_dir(_CONFIG_DIR)

    def create_project(self, parent: Path, name: str) -> OpenProject:
        self.history.clear()
        opened = self._store.create_under(parent, name)
        self.current = opened
        self._remember(opened.directory)
        self.remember_projects_root(parent)
        return opened

    def open_project(self, directory: Path, *, read_only: bool = True) -> OpenProject:
        self.close()
        self.current = self._store.open(directory, read_only=read_only)
        self._remember(self.current.directory)
        self.remember_projects_root(self.current.directory.parent)
        return self.current

    def close(self) -> None:
        self.history.clear()
        self.current = None

    def rename(self, name: str) -> None:
        opened = self.require_writable()
        self._store.rename(opened, name)
        self.current = OpenProject(
            directory=opened.directory,
            db_path=opened.db_path,
            session_factory=opened.session_factory,
            project_id=opened.project_id,
            name=name,
            read_only=False,
        )

    def project_settings(self) -> ProjectSettings:
        if self.current is None:
            raise ProjectError("Kein Projekt geöffnet.")
        return load_project_settings(self.current.directory)

    def link_defaults(self):
        from travelcore.timeline.outbound import LinkDefaults, link_defaults_from_settings

        if self.current is None:
            return LinkDefaults()
        try:
            return link_defaults_from_settings(load_project_settings(self.current.directory))
        except ProjectError:
            return LinkDefaults()

    def apply_project_settings(self, settings: ProjectSettings) -> int:
        """Write settings.toml and rebase indexed paths when the source root changes."""

        if self.current is None:
            raise ProjectError("Kein Projekt geöffnet.")
        self.require_writable()
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

    def media_stats(self) -> MediaStats:
        if self.current is None:
            return MediaStats()
        with self.current.session_factory() as session:
            return media_clusters.compute_media_stats(session, self.current.project_id)

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

    def map_track_color(self) -> str:
        opened = self._require_open()
        try:
            return load_project_settings(opened.directory).placeholders.map_track_color
        except ProjectError:
            return DEFAULT_MAP_TRACK_COLOR

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

    def map_show_sat_labels(self) -> bool:
        if self.current is None:
            return False
        try:
            return load_project_settings(self.current.directory).placeholders.map_show_sat_labels
        except ProjectError:
            return False

    def map_show_sat_streets(self) -> bool:
        if self.current is None:
            return False
        try:
            return load_project_settings(self.current.directory).placeholders.map_show_sat_streets
        except ProjectError:
            return False

    def map_show_flights(self) -> bool:
        if self.current is None:
            return True
        try:
            return load_project_settings(self.current.directory).placeholders.map_show_flights
        except ProjectError:
            return True

    def map_show_activities(self) -> bool:
        if self.current is None:
            return True
        try:
            return load_project_settings(self.current.directory).placeholders.map_show_activities
        except ProjectError:
            return True

    def set_map_display_flags(
        self,
        *,
        photo_cones: bool,
        show_reserve: bool,
        sat_labels: bool = False,
        sat_streets: bool = False,
        show_flights: bool = True,
        show_activities: bool = True,
    ) -> None:
        """Persist map display options in ``settings.toml`` for the open project."""

        if self.current is None:
            return
        try:
            settings = load_project_settings(self.current.directory)
        except ProjectError:
            return
        cones = bool(photo_cones)
        reserve = bool(show_reserve)
        labels = bool(sat_labels)
        streets = bool(sat_streets)
        flights = bool(show_flights)
        activities = bool(show_activities)
        if (
            settings.placeholders.map_show_photo_cones == cones
            and settings.placeholders.map_show_reserve == reserve
            and settings.placeholders.map_show_sat_labels == labels
            and settings.placeholders.map_show_sat_streets == streets
            and settings.placeholders.map_show_flights == flights
            and settings.placeholders.map_show_activities == activities
        ):
            return
        self.require_writable()
        settings.placeholders.map_show_photo_cones = cones
        settings.placeholders.map_show_reserve = reserve
        settings.placeholders.map_show_sat_labels = labels
        settings.placeholders.map_show_sat_streets = streets
        settings.placeholders.map_show_flights = flights
        settings.placeholders.map_show_activities = activities
        save_project_settings(self.current.directory, settings)

    def map_cache_identity(self) -> dict[str, object]:
        opened = self._require_open()
        _thumbs, size = self._thumbs_and_size()
        return map_cache_identity(
            db_path=opened.db_path,
            map_provider=self.map_provider(),
            thumbnail_size=size,
            map_link_color=self.map_link_color(),
            map_track_color=self.map_track_color(),
            project_dir=self._map_cache_root(),
        )

    def load_cached_map(self) -> MapRenderResult | None:
        if self.current is None:
            return None
        return read_cached_map(self._map_cache_root(), self.map_cache_identity())

    def render_map(self, *, force: bool = False) -> MapRenderResult:
        """Reuse ``cache/map.html`` when the stamp matches, otherwise rebuild."""

        opened = self._require_open()
        thumbs, size = self._thumbs_and_size()
        provider = self.map_provider()
        return ensure_map_cache(
            opened.session_factory,
            opened.project_id,
            self._map_cache_root(),
            thumbs,
            db_path=opened.db_path,
            size=size,
            map_provider=provider,
            map_link_color=self.map_link_color(),
            map_track_color=self.map_track_color(),
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
        from travelcore.maps.scene import apply_map_track_color

        scene = apply_map_track_color(scene, self.map_track_color())
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

    def map_group_key_for_source(self, source_file_id: int) -> str | None:
        """Overview key for one journal file, or None if it is parked or unknown."""

        opened = self._require_open()
        from travelcore.maps.groups import map_group_key_for_source as resolve_source_group

        with opened.session_factory() as session:
            return resolve_source_group(session, opened.project_id, source_file_id)

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

    def analyze_photo_quality(self, *, force: bool = False) -> QualityRunResult:
        opened = self.require_writable()

        with opened.session_factory() as session:
            result = analyze_project_photos(
                session,
                opened.project_id,
                force=force,
                max_workers=AppSettings().worker_count,
            )
            session.commit()
        return result

    def accept_exact_stacks(self) -> int:
        opened = self.require_writable()
        with opened.session_factory() as session:
            count = media_clusters.accept_exact_stacks(session, opened.project_id)
            session.commit()
        return count

    def propose_scene_groups(self) -> int:
        opened = self.require_writable()
        with opened.session_factory() as session:
            count = media_clusters.propose_scene_groups(session, opened.project_id)
            session.commit()
        return count

    def create_manual_group(self, source_file_ids: list[int]) -> int:
        opened = self.require_writable()
        with opened.session_factory() as session:
            cluster_id = media_clusters.create_manual_group(
                session, opened.project_id, source_file_ids
            )
            session.commit()
        return cluster_id

    def cluster_record(self, cluster_id: int) -> ClusterRecord:
        opened = self._require_open()
        with opened.session_factory() as session:
            return media_clusters.load_cluster(session, cluster_id)

    def cluster_items(self, cluster_id: int) -> list[GalleryItem]:
        record = self.cluster_record(cluster_id)
        opened = self._require_open()
        thumbs, size = self._thumbs_and_size()
        with opened.session_factory() as session:
            found = list_gallery_items(
                session,
                opened.project_id,
                thumbs,
                size=size,
                source_file_ids=record.member_ids,
                hide_cluster_hidden=False,
            )
        by_id = {item.source_file_id: item for item in found}
        return [by_id[item_id] for item_id in record.member_ids if item_id in by_id]

    def set_stack_key(self, cluster_id: int, source_file_id: int) -> None:
        self._mutate(lambda session: media_clusters.set_stack_key(session, cluster_id, source_file_id))

    def set_group_keys(self, cluster_id: int, source_file_ids: list[int]) -> None:
        self._mutate(lambda session: media_clusters.set_group_keys(session, cluster_id, source_file_ids))

    def dismiss_cluster(self, cluster_id: int) -> None:
        self._mutate(lambda session: media_clusters.dismiss_cluster(session, cluster_id))

    def dissolve_group(self, cluster_id: int) -> None:
        self._mutate(lambda session: media_clusters.dissolve_group(session, cluster_id))

    def sync_timeline(self) -> TimelineSnapshot:
        opened = self.require_writable()
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

    def load_trip_countries(self) -> tuple[str, ...]:
        snapshot = self.load_timeline()
        if snapshot is None:
            return ()
        return snapshot.countries

    def save_trip_countries(self, names: list[str]) -> None:
        if self.current is None:
            return
        project_id = self.current.project_id

        def _write(session) -> None:  # noqa: ANN001
            trip = session.scalar(select(Trip).where(Trip.project_id == project_id).order_by(Trip.id.asc()))
            if trip is None:
                return
            timeline_build.save_trip_countries(session, trip.id, names)

        self._mutate(_write)

    def load_trip_span(self) -> tuple[date | None, date | None]:
        if self.current is None:
            return None, None
        with self.current.session_factory() as session:
            project = session.get(Project, self.current.project_id)
            if project is None:
                return None, None
            trip = session.scalar(
                select(Trip).where(Trip.project_id == project.id).order_by(Trip.id.asc())
            )
            if trip is None:
                return timeline_build.infer_trip_dates(session, project.id)
            return timeline_build.resolve_trip_dates(session, trip)

    def save_trip_span(self, start: date | None, end: date | None) -> None:
        if self.current is None:
            return
        project_id = self.current.project_id

        def _write(session) -> None:  # noqa: ANN001
            project = session.get(Project, project_id)
            if project is None:
                return
            trip = session.scalar(select(Trip).where(Trip.project_id == project_id).order_by(Trip.id.asc()))
            if trip is None:
                trip = Trip(project_id=project_id, title=project.name, origin="auto")
                session.add(trip)
                session.flush()
            timeline_build.save_trip_dates(session, trip.id, start, end)

        self._mutate(_write)

    def save_transfer_links(self, section_id: int, links: list) -> None:
        from travelcore.timeline.outbound import compact_inherited_links
        from travelcore.timeline.transfer_links import save_transfer_links

        compacted = compact_inherited_links(links, self.link_defaults())
        self._mutate(lambda session: save_transfer_links(session, section_id, compacted))

    def save_outbound_link(self, section_id: int, link) -> None:
        from travelcore.timeline.outbound import save_outbound_link

        defaults = self.link_defaults()
        self._mutate(lambda session: save_outbound_link(session, section_id, link, defaults))

    def import_fitness_tracks(
        self,
        store_path: Path,
        *,
        source_root: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        progress: Callable[[int, int, str], None] | None = None,
    ) -> int:
        """Export GPX from the activity store into ``{import}/.ActivityTracks``."""

        return self.import_activity_tracks(
            store_path,
            source_root=source_root,
            date_from=date_from,
            date_to=date_to,
            include_activities=True,
            include_flights=False,
            progress=progress,
        )

    def import_igc_tracks(
        self,
        store_path: Path,
        *,
        source_root: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        progress: Callable[[int, int, str], None] | None = None,
    ) -> int:
        """Export IGC flights from the activity store into ``{import}/.IGCTracks``."""

        return self.import_activity_tracks(
            store_path,
            source_root=source_root,
            date_from=date_from,
            date_to=date_to,
            include_activities=False,
            include_flights=True,
            progress=progress,
        )

    def import_activity_tracks(
        self,
        store_path: Path,
        *,
        source_root: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        include_activities: bool = True,
        include_flights: bool = True,
        progress: Callable[[int, int, str], None] | None = None,
    ) -> int:
        """Load activity GPX and/or IGC from one store and drop tracks that disappeared."""

        from fitnesscore.exceptions import QueryError, StoreError
        from fitnesscore.query_gpx import export_gpx
        from fitnesscore.query_igc import export_igc
        from fitnesscore.store import open_store, resolve_db_path
        from travelcore.gps.fitnesstracks import (
            activity_track_folders,
            activity_tracks_dir,
            index_fitness_gpx_file,
            is_activity_track_path,
            normalized_path_key,
            unlink_unwanted_files,
        )
        from travelcore.gps.igctracks import igc_tracks_dir, index_igc_file, is_igc_track_path
        from travelcore.gps.maptracks import resolve_source_root
        from travelcore.media.purge import purge_source_files
        from travelcore.media.types import FileKind

        if not include_activities and not include_flights:
            raise ProjectError("Bitte Activity-Tracks oder Flüge auswählen.")
        opened = self.require_writable()
        trip_start, trip_end = self.load_trip_span()
        start = date_from or trip_start
        end = date_to or trip_end
        if start is None or end is None:
            raise ProjectError("Bitte einen Zeitraum von–bis setzen.")
        if end < start:
            raise ProjectError("Das Endedatum liegt vor dem Startdatum.")
        db_path = resolve_db_path(Path(store_path))
        if not db_path.is_file():
            raise ProjectError(f"Keine Activity-Datenbank: {db_path}")
        root = resolve_source_root(source_root) if source_root else self._import_root()
        try:
            store = open_store(db_path)
        except StoreError as exc:
            raise ProjectError(str(exc)) from exc
        kinds: list[tuple[str, Path, object, object, object]] = []
        if include_activities:
            kinds.append(
                (
                    "GPX",
                    activity_tracks_dir(root),
                    export_gpx,
                    index_fitness_gpx_file,
                    is_activity_track_path,
                )
            )
        if include_flights:
            kinds.append(
                (
                    "IGC",
                    igc_tracks_dir(root),
                    export_igc,
                    index_igc_file,
                    is_igc_track_path,
                )
            )
        written = 0
        removed = 0
        thumbs_dir = opened.directory / "thumbnails"
        for label, dest, exporter, indexer, is_kind_path in kinds:
            if progress is not None:
                progress(0, 1, f"Suche {label}…")
            try:
                hits = exporter(
                    store,
                    date_from=start,
                    date_to=end,
                    dest=dest,
                    progress=(
                        (
                            lambda current, total, name: progress(
                                current, max(total, 1), f"Schreibe {name}"
                            )
                        )
                        if progress is not None
                        else None
                    ),
                )
            except (StoreError, QueryError) as exc:
                raise ProjectError(str(exc)) from exc
            wanted = {hit.path.name for hit in hits}
            wanted_keys = {normalized_path_key(hit.path) for hit in hits}
            suffix = ".gpx" if label == "GPX" else ".igc"
            folders: tuple[Path, ...] = (dest,)
            if label == "GPX":
                folders = activity_track_folders(root)
            unlink_unwanted_files(folders, dest=dest, wanted_names=wanted, suffix=suffix)
            with opened.session_factory() as session:
                project = session.get(Project, opened.project_id)
                if project is None:
                    raise ProjectError("Projektzeile fehlt.")
                indexed = [
                    row
                    for row in session.scalars(
                        select(SourceFile).where(
                            SourceFile.project_id == opened.project_id,
                            SourceFile.file_kind == FileKind.GPS.value,
                        )
                    )
                    if is_kind_path(row.path)
                ]
                stale = [
                    row
                    for row in indexed
                    if normalized_path_key(Path(row.path)) not in wanted_keys
                ]
                if stale:
                    for row in stale:
                        Path(row.path).unlink(missing_ok=True)
                    purge_source_files(
                        session,
                        stale,
                        thumbs_dir=thumbs_dir if thumbs_dir.is_dir() else None,
                    )
                    removed += len(stale)
                total = len(hits)
                for index, hit in enumerate(hits, start=1):
                    indexer(session, project, hit.path, project_dir=opened.directory)
                    if progress is not None:
                        progress(index, max(total, 1), f"Indexiere {hit.path.name}")
                session.commit()
            written += len(hits)
        if written or removed:
            if progress is not None:
                progress(1, 1, "Timeline wird aktualisiert…")
            self.sync_timeline()
        elif progress is not None:
            progress(1, 1, "Keine Tracks")
        return written

    def _import_root(self, project: Project | None = None) -> Path:
        from travelcore.gps.maptracks import resolve_source_root

        opened = self._require_open()
        root = None
        try:
            root = load_project_settings(opened.directory).paths.source_root
        except ProjectError:
            root = None
        if not root and project is not None:
            root = project.source_root
        elif not root:
            with opened.session_factory() as session:
                row = session.get(Project, opened.project_id)
                root = row.source_root if row is not None else None
        return resolve_source_root(root)

    def list_map_tracks(self) -> list[tuple[int, str]]:
        from travelcore.gps.maptracks import list_map_tracks

        opened = self._require_open()
        with opened.session_factory() as session:
            return list_map_tracks(session, opened.project_id)

    def import_map_track_file(self, source: Path) -> tuple[int, str]:
        from travelcore.gps.maptracks import import_map_track_file

        opened = self.require_writable()
        with opened.session_factory() as session:
            project = session.get(Project, opened.project_id)
            if project is None:
                raise ProjectError("Projektzeile fehlt.")
            row = import_map_track_file(
                session,
                project,
                source,
                source_root=self._import_root(project),
                project_dir=opened.directory,
            )
            session.commit()
            return int(row.id), row.filename

    def import_map_track_gpx(self, xml: str, *, stem: str | None = None) -> tuple[int, str]:
        from travelcore.gps.maptracks import import_map_track_gpx

        opened = self.require_writable()
        with opened.session_factory() as session:
            project = session.get(Project, opened.project_id)
            if project is None:
                raise ProjectError("Projektzeile fehlt.")
            row = import_map_track_gpx(
                session,
                project,
                xml,
                source_root=self._import_root(project),
                project_dir=opened.directory,
                stem=stem,
            )
            session.commit()
            return int(row.id), row.filename

    def map_track_gallery_item(self, source_id: int) -> GalleryItem | None:
        from travelcore.config import DEFAULT_THUMBNAIL_SIZE
        from travelcore.gps.maptracks import is_map_track_path, map_track_display_name
        from travelcore.gps.track_badge import TRACK_BADGE_MAP
        from travelcore.media.thumbnails import cached_thumbnail_path

        opened = self._require_open()
        thumbs, size = self._thumbs_and_size()
        with opened.session_factory() as session:
            row = session.get(SourceFile, source_id)
            if row is None or not is_map_track_path(row.path):
                return None
            return GalleryItem(
                source_file_id=row.id,
                path=row.path,
                filename=map_track_display_name(row.filename),
                extension=row.extension,
                captured_at=row.captured_at,
                timezone_unknown=bool(row.timezone_unknown),
                gps_latitude=row.gps_latitude,
                gps_longitude=row.gps_longitude,
                camera=row.camera,
                is_favorite=False,
                used_in_journal=False,
                thumbnail_path=cached_thumbnail_path(
                    thumbs,
                    source_file_id=row.id,
                    sha256=row.sha256,
                    size=size or DEFAULT_THUMBNAIL_SIZE,
                    prefer_existing=True,
                ),
                parked=bool(row.parked),
                display_latitude=row.gps_latitude,
                display_longitude=row.gps_longitude,
                is_map_track=True,
                track_badge=TRACK_BADGE_MAP,
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
        hidden: bool = False,
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
            hidden=hidden,
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
                        hidden=hidden,
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

    def set_section_hidden(self, section_id: int, hidden: bool) -> None:
        previous = self._read_section_hidden(section_id)
        if previous == bool(hidden):
            return
        self._apply_section_hidden(section_id, hidden)
        self.history.push(
            "Ausblenden" if hidden else "Einblenden",
            lambda: self._apply_section_hidden(section_id, previous),
            lambda: self._apply_section_hidden(section_id, hidden),
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
        if self.current is None or self.current.read_only:
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

    def project_catalog_sort(self) -> str:
        from travelcore.database.project_catalog import normalize_catalog_sort

        return normalize_catalog_sort(self._load_ui_config().get("project_catalog_sort"))

    def set_project_catalog_sort(self, key: str) -> None:
        from travelcore.database.project_catalog import normalize_catalog_sort

        normalized = normalize_catalog_sort(key)
        data = self._load_ui_config()
        if data.get("project_catalog_sort") == normalized:
            return
        data["project_catalog_sort"] = normalized
        self._save_ui_config(data)

    def project_catalog_collapsed(self) -> bool:
        stored = self._load_ui_config().get("project_catalog_collapsed")
        if stored is None:
            return True
        return stored is True

    def set_project_catalog_collapsed(self, collapsed: bool) -> None:
        flag = bool(collapsed)
        if self.project_catalog_collapsed() == flag:
            return
        data = self._load_ui_config()
        data["project_catalog_collapsed"] = flag
        self._save_ui_config(data)

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

    def timeline_galleries_collapsed(self) -> bool:
        return self._load_ui_config().get("timeline_galleries_collapsed") is True

    def set_timeline_galleries_collapsed(self, collapsed: bool) -> None:
        flag = bool(collapsed)
        data = self._load_ui_config()
        if bool(data.get("timeline_galleries_collapsed")) == flag:
            return
        data["timeline_galleries_collapsed"] = flag
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

    def timeline_thumb_zoom(self) -> int:
        from traveljournal.widgets.thumb_zoom import clamp_thumb_zoom

        return clamp_thumb_zoom(self._load_ui_config().get("timeline_thumb_zoom"))

    def set_timeline_thumb_zoom(self, percent: int) -> None:
        from traveljournal.widgets.thumb_zoom import clamp_thumb_zoom

        zoom = clamp_thumb_zoom(percent)
        data = self._load_ui_config()
        if data.get("timeline_thumb_zoom") == zoom:
            return
        data["timeline_thumb_zoom"] = zoom
        self._save_ui_config(data)

    def media_thumb_zoom(self) -> int:
        from traveljournal.widgets.thumb_zoom import clamp_thumb_zoom

        return clamp_thumb_zoom(self._load_ui_config().get("media_thumb_zoom"))

    def set_media_thumb_zoom(self, percent: int) -> None:
        from traveljournal.widgets.thumb_zoom import clamp_thumb_zoom

        zoom = clamp_thumb_zoom(percent)
        data = self._load_ui_config()
        if data.get("media_thumb_zoom") == zoom:
            return
        data["media_thumb_zoom"] = zoom
        self._save_ui_config(data)

    def map_thumb_zoom(self) -> int:
        from traveljournal.widgets.thumb_zoom import clamp_thumb_zoom

        return clamp_thumb_zoom(self._load_ui_config().get("map_thumb_zoom"))

    def set_map_thumb_zoom(self, percent: int) -> None:
        from traveljournal.widgets.thumb_zoom import clamp_thumb_zoom

        zoom = clamp_thumb_zoom(percent)
        data = self._load_ui_config()
        if data.get("map_thumb_zoom") == zoom:
            return
        data["map_thumb_zoom"] = zoom
        self._save_ui_config(data)

    def activity_db_path(self) -> str:
        data = self._load_ui_config()
        stored = data.get("activity_db_path") or data.get("fitness_db_path") or data.get("igc_db_path")
        if not isinstance(stored, str) or not stored.strip():
            return ""
        path = Path(stored.strip())
        if path.suffix.lower() == ".sqlite":
            return str(path)
        from fitnesscore.store import resolve_db_path

        return str(resolve_db_path(path))

    def set_activity_db_path(self, path: str) -> None:
        text = path.strip()
        data = self._load_ui_config()
        changed = False
        for old in ("fitness_db_path", "igc_db_path"):
            if old in data:
                data.pop(old, None)
                changed = True
        current = data.get("activity_db_path")
        current_text = current.strip() if isinstance(current, str) else ""
        if text:
            if current_text != text:
                data["activity_db_path"] = text
                changed = True
        elif "activity_db_path" in data:
            data.pop("activity_db_path", None)
            changed = True
        if changed:
            self._save_ui_config(data)

    def activity_load_kinds(self) -> tuple[bool, bool]:
        data = self._load_ui_config()
        activities = data.get("activity_load_activities")
        flights = data.get("activity_load_flights")
        return (
            True if activities is None else bool(activities),
            True if flights is None else bool(flights),
        )

    def set_activity_load_kinds(self, activities: bool, flights: bool) -> None:
        data = self._load_ui_config()
        wanted_activities = bool(activities)
        wanted_flights = bool(flights)
        if (
            bool(data.get("activity_load_activities", True)) == wanted_activities
            and bool(data.get("activity_load_flights", True)) == wanted_flights
        ):
            return
        data["activity_load_activities"] = wanted_activities
        data["activity_load_flights"] = wanted_flights
        self._save_ui_config(data)

    def fitness_db_path(self) -> str:
        return self.activity_db_path()

    def set_fitness_db_path(self, path: str) -> None:
        self.set_activity_db_path(path)

    def igc_db_path(self) -> str:
        return self.activity_db_path()

    def set_igc_db_path(self, path: str) -> None:
        self.set_activity_db_path(path)

    def _set_stored_path(self, key: str, path: str) -> None:
        text = path.strip()
        data = self._load_ui_config()
        if data.get(key) == text:
            return
        if text:
            data[key] = text
        else:
            data.pop(key, None)
        self._save_ui_config(data)

    def import_thumb_zoom(self) -> int:
        from traveljournal.widgets.thumb_zoom import clamp_thumb_zoom

        return clamp_thumb_zoom(self._load_ui_config().get("import_thumb_zoom"))

    def set_import_thumb_zoom(self, percent: int) -> None:
        from traveljournal.widgets.thumb_zoom import clamp_thumb_zoom

        zoom = clamp_thumb_zoom(percent)
        data = self._load_ui_config()
        if data.get("import_thumb_zoom") == zoom:
            return
        data["import_thumb_zoom"] = zoom
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

    def inspector_show_rejected(self) -> bool:
        return self._load_ui_config().get("inspector_show_rejected") is True

    def set_inspector_show_rejected(self, visible: bool) -> None:
        flag = bool(visible)
        data = self._load_ui_config()
        if bool(data.get("inspector_show_rejected")) == flag:
            return
        data["inspector_show_rejected"] = flag
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

    def recent_project_entries(self) -> list[Path]:
        """Paths from ``recent.json``, including folders that no longer exist."""

        path = _recent_file()
        if not path.is_file():
            return []
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return [Path(item) for item in raw if isinstance(item, str)]

    def recent_projects(self) -> list[Path]:
        return [path for path in self.recent_project_entries() if (path / "project.sqlite").is_file()]

    def list_known_projects(self) -> list[ProjectDescriptor]:
        current = self.current.directory if self.current is not None else None
        return list_project_catalog(
            root=self.projects_root(),
            recents=self.recent_project_entries(),
            current=current,
        )

    def _remember(self, directory: Path) -> None:
        items = [str(directory)]
        for existing in self.recent_projects():
            if existing.resolve() != directory.resolve():
                items.append(str(existing))
        path = _recent_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(items[:10], indent=2), encoding="utf-8")

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

    def require_writable(self) -> OpenProject:
        opened = self._require_open()
        if opened.read_only:
            raise ReadOnlyProjectError()
        return opened

    def is_read_only(self) -> bool:
        return self.current is not None and self.current.read_only

    def _map_cache_root(self) -> Path:
        return project_cache_dir(self._require_open())

    def _thumbs_and_size(self) -> tuple[Path, int]:
        opened = self._require_open()
        thumbs = opened.directory / "thumbnails"
        if not opened.read_only:
            thumbs.mkdir(parents=True, exist_ok=True)
        return thumbs, AppSettings().default_thumbnail_size

    def _mutate(self, action: Callable[..., object]) -> None:
        opened = self.require_writable()
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

    def _read_section_hidden(self, section_id: int) -> bool:
        opened = self._require_open()
        with opened.session_factory() as session:
            return timeline_history.section_hidden(session, section_id)

    def _apply_section_hidden(self, section_id: int, hidden: bool) -> None:
        self._mutate(lambda session: timeline_sections.set_section_hidden(session, section_id, hidden))

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
        hidden: bool = False,
    ) -> int:
        opened = self.require_writable()
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
                hidden=hidden,
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
        opened = self.require_writable()
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
