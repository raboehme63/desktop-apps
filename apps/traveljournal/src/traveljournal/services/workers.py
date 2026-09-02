"""Qt worker adapters. travelcore itself stays free of Qt threads."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QRunnable, Signal

from travelcore.config import AppSettings
from travelcore.database.models import Project
from travelcore.database.project_store import OpenProject
from travelcore.database.session import session_scope
from travelcore.exceptions import ProjectError
from travelcore.export.quality import DEFAULT_QUALITY_ID
from travelcore.maps import ensure_map_cache
from travelcore.media.indexer import FileIndexer, IndexProgress, IndexResult
from travelcore.media.thumbnails import generate_project_thumbnails
from travelcore.parallel import WorkerPool
from travelcore.project_settings import (
    DEFAULT_MAP_TRACK_COLOR,
    DEFAULT_STAY_LINK_COLOR,
    load_project_settings,
)
from travelcore.timeline.sections import park_media

if TYPE_CHECKING:
    from traveljournal.services.workspace import Workspace


class IndexSignals(QObject):
    progress = Signal(int, int, str, str)
    files_ready = Signal()
    finished = Signal(object)
    failed = Signal(str)


class IndexRunnable(QRunnable):
    def __init__(
        self,
        open_project: OpenProject,
        source_root: Path,
        *,
        remove_missing: bool = False,
        park_new_media: bool = False,
    ) -> None:
        super().__init__()
        self.open_project = open_project
        self.source_root = source_root
        self.remove_missing = remove_missing
        self.park_new_media = park_new_media
        self.signals = IndexSignals()
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            settings = AppSettings()
            with WorkerPool(max_workers=settings.worker_count) as pool:
                indexer = FileIndexer(compute_hash=True, pool=pool)

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
                        remove_missing=self.remove_missing,
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
                        pool=pool,
                    )
                if self.park_new_media and result.new_media_ids:
                    with session_scope(self.open_project.session_factory) as session:
                        park_media(session, result.new_media_ids)
            self.signals.finished.emit(result)
        except Exception as exc:  # noqa: BLE001 - surface any import failure to the UI
            self.signals.failed.emit(str(exc))


class QualitySignals(QObject):
    progress = Signal(int, int)
    finished = Signal(int, int, int)
    failed = Signal(str)


class QualityRunnable(QRunnable):
    def __init__(self, open_project: OpenProject) -> None:
        super().__init__()
        self.open_project = open_project
        self.signals = QualitySignals()
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            from travelcore.image_analysis import analyze_project_photos

            settings = AppSettings()

            def on_progress(current: int, total: int) -> None:
                self.signals.progress.emit(current, total)

            with session_scope(self.open_project.session_factory) as session:
                result = analyze_project_photos(
                    session,
                    self.open_project.project_id,
                    max_workers=settings.worker_count,
                    progress=on_progress,
                )
            self.signals.finished.emit(result.analyzed, result.skipped, result.failed)
        except Exception as exc:  # noqa: BLE001 - surface quality failures to the UI
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


class ExportPdfSignals(QObject):
    progress = Signal(int, int)
    finished = Signal(object)
    failed = Signal(str)


class ExportMcfSignals(QObject):
    progress = Signal(int, int)
    finished = Signal(object)
    failed = Signal(str)


class ExportMcfRunnable(QRunnable):
    """Write a CEWE .mcf project off the GUI thread."""

    def __init__(
        self,
        document: object,
        snapshot: object,
        destination: Path,
        sources: dict[int, Path],
        rotations: dict[int, int],
        host: QObject | None = None,
    ) -> None:
        super().__init__()
        self.document = document
        self.snapshot = snapshot
        self.destination = destination
        self.sources = sources
        self.rotations = rotations
        self.signals = ExportMcfSignals(host)
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            from travelcore.export.cewe import export_travelbook_mcf

            def on_progress(current: int, total: int) -> None:
                self.signals.progress.emit(current, total)

            result = export_travelbook_mcf(
                self.document,
                self.snapshot,
                self.destination,
                sources=self.sources,
                rotations=self.rotations,
                progress=on_progress,
            )
            self.signals.finished.emit(result)
        except Exception as exc:  # noqa: BLE001 - surface export failures to the UI
            self.signals.failed.emit(str(exc))


class ExportPdfRunnable(QRunnable):
    """Rasterize the Travelbook to PDF off the GUI thread."""

    def __init__(
        self,
        document: object,
        snapshot: object,
        destination: Path,
        sources: dict[int, Path],
        rotations: dict[int, int],
        quality: str = DEFAULT_QUALITY_ID,
        host: QObject | None = None,
    ) -> None:
        super().__init__()
        self.document = document
        self.snapshot = snapshot
        self.destination = destination
        self.sources = sources
        self.rotations = rotations
        self.quality = quality
        self.signals = ExportPdfSignals(host)
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            from travelcore.export.pdf import export_travelbook_pdf

            def on_progress(current: int, total: int) -> None:
                self.signals.progress.emit(current, total)

            result = export_travelbook_pdf(
                self.document,
                self.snapshot,
                self.destination,
                sources=self.sources,
                rotations=self.rotations,
                quality=self.quality,
                progress=on_progress,
            )
            self.signals.finished.emit(result)
        except Exception as exc:  # noqa: BLE001 - surface export failures to the UI
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
                loaded = load_project_settings(self.open_project.directory)
                provider = loaded.placeholders.map_provider
                link_color = loaded.placeholders.map_link_color
                track_color = loaded.placeholders.map_track_color
            except ProjectError:
                provider = "leaflet"
                link_color = DEFAULT_STAY_LINK_COLOR
                track_color = DEFAULT_MAP_TRACK_COLOR
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
                map_link_color=link_color,
                map_track_color=track_color,
                force=self.force,
            )
            self.signals.finished.emit(result)
        except Exception as exc:  # noqa: BLE001 - surface map build failures to the UI
            self.signals.failed.emit(str(exc))


class MapsTrackSignals(QObject):
    finished = Signal(str, str)
    failed = Signal(str)


class MapsTrackRunnable(QRunnable):
    """Resolve a Google Maps directions URL to GPX XML off the GUI thread."""

    def __init__(self, url: str, host: QObject | None = None) -> None:
        super().__init__()
        self.url = url
        self.signals = MapsTrackSignals(host)
        self.setAutoDelete(True)

    def run(self) -> None:
        from travelcore.gps.maps_url import (
            MapsGpxError,
            directions_to_gpx,
            resolve_directions,
            route_filename_stem,
            route_geometry,
        )

        try:
            directions = resolve_directions(self.url)
            track = route_geometry(directions)
            xml = directions_to_gpx(directions, track)
            self.signals.finished.emit(xml, route_filename_stem(directions))
        except MapsGpxError as exc:
            self.signals.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 - surface conversion failures to the UI
            self.signals.failed.emit(str(exc))


class StoreImportSignals(QObject):
    progress = Signal(int, int, str)
    finished = Signal(int)
    failed = Signal(str)


class StoreImportRunnable(QRunnable):
    def __init__(
        self,
        workspace: Workspace,
        kind: str,
        store_path: Path,
        *,
        source_root: str | None,
        date_from: date,
        date_to: date,
    ) -> None:
        super().__init__()
        self.workspace = workspace
        self.kind = kind
        self.store_path = store_path
        self.source_root = source_root
        self.date_from = date_from
        self.date_to = date_to
        self.signals = StoreImportSignals()
        self.setAutoDelete(True)

    def run(self) -> None:
        def on_progress(current: int, total: int, message: str) -> None:
            self.signals.progress.emit(current, total, message)

        try:
            if self.kind == "igc":
                count = self.workspace.import_igc_tracks(
                    self.store_path,
                    source_root=self.source_root,
                    date_from=self.date_from,
                    date_to=self.date_to,
                    progress=on_progress,
                )
            else:
                count = self.workspace.import_fitness_tracks(
                    self.store_path,
                    source_root=self.source_root,
                    date_from=self.date_from,
                    date_to=self.date_to,
                    progress=on_progress,
                )
            self.signals.finished.emit(count)
        except ProjectError as exc:
            self.signals.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 - surface store-import failures to the UI
            self.signals.failed.emit(str(exc))
