"""Qt worker adapters. travelcore itself stays free of Qt threads."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal

from travelcore.config import AppSettings
from travelcore.database.models import Project
from travelcore.database.project_store import OpenProject
from travelcore.database.session import session_scope
from travelcore.media.indexer import FileIndexer, IndexProgress, IndexResult
from travelcore.media.thumbnails import generate_project_thumbnails


class IndexSignals(QObject):
    progress = Signal(int, int, str)
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
                self.signals.progress.emit(item.current, item.total, item.path)

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
                )
            self.signals.finished.emit(result.written)
        except Exception as exc:  # noqa: BLE001 - surface thumbnail failures to the UI
            self.signals.failed.emit(str(exc))
