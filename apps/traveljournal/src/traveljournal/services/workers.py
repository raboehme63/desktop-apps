"""Qt worker adapters. travelcore itself stays free of Qt threads."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QRunnable, Signal

from travelcore.config import AppSettings
from travelcore.database.models import Project
from travelcore.database.project_store import OpenProject
from travelcore.database.session import session_scope
from travelcore.exceptions import ProjectError
from travelcore.maps import ensure_map_cache
from travelcore.media.indexer import FileIndexer, IndexProgress, IndexResult
from travelcore.media.thumbnails import generate_project_thumbnails
from travelcore.project_settings import load_project_settings

if TYPE_CHECKING:
    from traveljournal.services.workspace import Workspace


class IndexSignals(QObject):
    progress = Signal(int, int, str, str)
    files_ready = Signal()
    finished = Signal(object)
    failed = Signal(str)


class IndexRunnable(QRunnable):
    def __init__(self, open_project: OpenProject, source_root: Path) -> None:
        super().__init__()
        self.open_project = open_project
        self.source_root = source_root
        self.signals = IndexSignals()
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            indexer = FileIndexer(compute_hash=True)

            def on_progress(item: IndexProgress) -> None:
                self.signals.progress.emit(item.current, item.total, item.path, item.message)

            with session_scope(self.open_project.session_factory) as session:
                project = session.get(Project, self.open_project.project_id)
                if project is None:
                    raise RuntimeError("Projektzeile fehlt.")

                def checkpoint() -> None:
                    session.commit()
                    self.signals.files_ready.emit()

                result: IndexResult = indexer.index(
                    session,
                    project,
                    self.source_root,
                    progress=on_progress,
                    project_dir=self.open_project.directory,
                    generate_thumbnails=False,
                    checkpoint=checkpoint,
                )
            on_progress(
                IndexProgress(
                    current=0,
                    total=1,
                    path="",
                    message="Vorschaubilder werden erzeugt…",
                )
            )
            with session_scope(self.open_project.session_factory) as session:
                project = session.get(Project, self.open_project.project_id)
                if project is None:
                    raise RuntimeError("Projektzeile fehlt.")
                indexer.build_previews(
                    session,
                    project,
                    result,
                    on_progress,
                    self.open_project.directory,
                )
            self.signals.finished.emit(result)
        except Exception as exc:  # noqa: BLE001 - surface any import failure to the UI
            self.signals.failed.emit(str(exc))


class ThumbnailSignals(QObject):
    finished = Signal(int)
    failed = Signal(str)


class ThumbnailRunnable(QRunnable):
    def __init__(self, open_project: OpenProject) -> None:
        super().__init__()
        self.open_project = open_project
        self.signals = ThumbnailSignals()
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            settings = AppSettings()
            with session_scope(self.open_project.session_factory) as session:
                project = session.get(Project, self.open_project.project_id)
                if project is None:
                    raise RuntimeError("Projektzeile fehlt.")
                result = generate_project_thumbnails(
                    session,
                    project,
                    self.open_project.directory / "thumbnails",
                    size=settings.default_thumbnail_size,
                    max_workers=settings.worker_count,
                )
            self.signals.finished.emit(result.written)
        except Exception as exc:  # noqa: BLE001 - surface thumbnail failures to the UI
            self.signals.failed.emit(str(exc))


class IndexLoadSignals(QObject):
    ready = Signal(object, object)
    failed = Signal(str)


class IndexLoadRunnable(QRunnable):
    """Load the file index for the UI without blocking the GUI thread."""

    def __init__(self, workspace: Workspace) -> None:
        super().__init__()
        self.workspace = workspace
        self.signals = IndexLoadSignals()
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            rows = self.workspace.source_files()
            urls = self.workspace.gps_track_urls() if rows else {}
            self.signals.ready.emit(rows, urls)
        except Exception as exc:  # noqa: BLE001 - surface load failures to the UI
            self.signals.failed.emit(str(exc))


class MapRenderSignals(QObject):
    finished = Signal(object)
    failed = Signal(str)


class MapRenderRunnable(QRunnable):
    """Build or reuse ``cache/map.html`` off the GUI thread."""

    def __init__(
        self,
        open_project: OpenProject,
        *,
        force: bool = False,
        host: QObject | None = None,
    ) -> None:
        super().__init__()
        self.open_project = open_project
        self.force = force
        self.signals = MapRenderSignals(host)
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            settings = AppSettings()
            try:
                provider = load_project_settings(self.open_project.directory).placeholders.map_provider
            except ProjectError:
                provider = "leaflet"
            thumbs = self.open_project.directory / "thumbnails"
            thumbs.mkdir(parents=True, exist_ok=True)
            result = ensure_map_cache(
                self.open_project.session_factory,
                self.open_project.project_id,
                self.open_project.directory,
                thumbs,
                db_path=self.open_project.db_path,
                size=settings.default_thumbnail_size,
                map_provider=provider,
                force=self.force,
            )
            self.signals.finished.emit(result)
        except Exception as exc:  # noqa: BLE001 - surface map build failures to the UI
            self.signals.failed.emit(str(exc))
