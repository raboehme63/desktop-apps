"""Application-level project workspace. Thin wrapper around travelcore."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from travelcore.config import AppSettings
from travelcore.database.models import Photo, Project, SourceFile
from travelcore.database.project_store import OpenProject, ProjectStore
from travelcore.exceptions import ProjectError
from travelcore.gps.ingest import set_track_external_url, track_urls_by_source
from travelcore.maps import FoliumMapBackend, MapScene, build_map_scene
from travelcore.media.gallery import GalleryItem, list_gallery_items
from travelcore.media.indexer import count_by_kind
from travelcore.media.thumbnails import generate_project_thumbnails
from travelcore.project_settings import (
    ProjectSettings,
    load_project_settings,
    rebase_source_file_paths,
    roots_equal,
    save_project_settings,
)
from travelcore.timeline import TimelineSnapshot
from travelcore.timeline import build as timeline_build

_RECENT_PATH = Path.home() / "AppData" / "Local" / "TravelJournal" / "recent.json"


class Workspace:
    def __init__(self) -> None:
        self._store = ProjectStore()
        self.current: OpenProject | None = None

    def create_project(self, parent: Path, name: str) -> OpenProject:
        opened = self._store.create_under(parent, name)
        self.current = opened
        self._remember(opened.directory)
        return opened

    def open_project(self, directory: Path) -> OpenProject:
        self.close()
        self.current = self._store.open(directory)
        self._remember(self.current.directory)
        return self.current

    def close(self) -> None:
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

    def render_map(self) -> tuple[MapScene, Path | None]:
        """Build a map scene and write ``cache/map.html``. Returns (scene, html or None)."""

        if self.current is None:
            raise ProjectError("Kein Projekt geöffnet.")
        thumbs = self.current.directory / "thumbnails"
        size = AppSettings().default_thumbnail_size
        tiles: str | None = "OpenStreetMap"
        try:
            provider = load_project_settings(self.current.directory).placeholders.map_provider
        except ProjectError:
            provider = "leaflet"
        if provider.strip().lower() == "offline":
            tiles = None
        with self.current.session_factory() as session:
            scene = build_map_scene(session, self.current.project_id, thumbs, size=size)
        if scene.empty:
            return scene, None
        html_path = self.current.directory / "cache" / "map.html"
        FoliumMapBackend(tiles=tiles).render(scene, html_path)
        return scene, html_path

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
        self._mutate(lambda session: timeline_build.save_day_text(session, day_id, title=title, notes=notes))

    def set_photo_in_journal(self, source_file_id: int, used: bool) -> None:
        self._mutate(lambda session: timeline_build.set_photo_journal_flag(session, source_file_id, used))

    def set_cover_photo(self, source_file_id: int) -> None:
        opened = self._require_open()
        with opened.session_factory() as session:
            timeline_build.set_cover_photo(session, opened.project_id, source_file_id)
            session.commit()

    def confirm_place(self, place_id: int, name: str) -> None:
        self._mutate(lambda session: timeline_build.confirm_place(session, place_id, name))

    def delete_place(self, place_id: int) -> None:
        self._mutate(lambda session: timeline_build.delete_place(session, place_id))

    def add_overnight_stay(
        self,
        day_id: int,
        *,
        name: str,
        location_name: str | None,
        latitude: float | None,
        longitude: float | None,
        description: str | None,
    ) -> None:
        self._mutate(
            lambda session: timeline_build.add_overnight_stay(
                session,
                day_id,
                name=name,
                location_name=location_name,
                latitude=latitude,
                longitude=longitude,
                description=description,
            )
        )

    def delete_overnight_stay(self, stay_id: int) -> None:
        self._mutate(lambda session: timeline_build.delete_overnight_stay(session, stay_id))

    def thumbs_dir(self) -> Path | None:
        if self.current is None:
            return None
        path = self.current.directory / "thumbnails"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def set_favorite(self, source_file_id: int, value: bool) -> None:
        if self.current is None:
            raise ProjectError("Kein Projekt geöffnet.")
        with self.current.session_factory() as session:
            photo = session.scalar(select(Photo).where(Photo.source_file_id == source_file_id))
            if photo is None:
                photo = Photo(
                    source_file_id=source_file_id,
                    is_favorite=value,
                    used_in_journal=False,
                    is_cover=False,
                    origin="manual",
                )
                session.add(photo)
            else:
                photo.is_favorite = value
                photo.origin = "manual"
            session.commit()

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
