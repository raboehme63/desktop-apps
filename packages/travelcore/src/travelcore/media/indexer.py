"""Index a source directory into the project SQLite database."""

from __future__ import annotations

import logging
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from travelcore.config import AppSettings
from travelcore.database.models import FileError, Project, SourceFile
from travelcore.exceptions import MetadataError, ProjectError
from travelcore.gps.ingest import ingest_gps_tracks
from travelcore.media.hashing import sha256_file
from travelcore.media.scanner import ScannedFile, scan_source_directory
from travelcore.media.thumbnails import ensure_photo_and_video_rows, generate_project_thumbnails
from travelcore.media.types import FileKind
from travelcore.metadata.apply import apply_metadata
from travelcore.metadata.composite import DefaultMetadataProvider
from travelcore.metadata.provider import MetadataProvider
from travelcore.metadata.time import filesystem_captured_time
from travelcore.project_settings import update_source_root

logger = logging.getLogger(__name__)

ProgressCallback = Callable[["IndexProgress"], None]
CheckpointCallback = Callable[[], None]
_DEFAULT_CHECKPOINT_EVERY = 20
_CHECKPOINT_MIN_SECONDS = 0.4


@dataclass(frozen=True, slots=True)
class IndexProgress:
    current: int
    total: int
    path: str
    message: str


@dataclass(slots=True)
class IndexResult:
    scanned: int = 0
    indexed: int = 0
    updated: int = 0
    skipped_unchanged: int = 0
    errors: int = 0
    tracks_ingested: int = 0
    track_points: int = 0
    positions_matched: int = 0
    thumbnails_written: int = 0
    thumbnails_skipped: int = 0
    by_kind: dict[str, int] = field(default_factory=dict)


class FileIndexer:
    """Create or refresh the central source-file index.

    Original files are never modified. A defective file is recorded as an
    error and does not abort the remaining import.
    """

    def __init__(
        self,
        *,
        compute_hash: bool = True,
        metadata_provider: MetadataProvider | None = None,
        settings: AppSettings | None = None,
    ) -> None:
        self.compute_hash = compute_hash
        self.metadata_provider = metadata_provider or DefaultMetadataProvider.from_environment()
        self.settings = settings or AppSettings()

    def index(
        self,
        session: Session,
        project: Project,
        source_root: Path,
        *,
        progress: ProgressCallback | None = None,
        project_dir: Path | None = None,
        generate_thumbnails: bool = True,
        checkpoint: CheckpointCallback | None = None,
        checkpoint_every: int = _DEFAULT_CHECKPOINT_EVERY,
    ) -> IndexResult:
        source_root = source_root.expanduser().resolve()
        project.source_root = str(source_root)
        project.updated_at = datetime.now(tz=UTC)
        gps_delta = self.settings.gps_match_max_delta_seconds
        settings_dir = project_dir or _project_dir_from_session(session)
        if settings_dir is not None:
            try:
                stored = update_source_root(settings_dir, source_root)
                gps_delta = stored.matching.gps_match_max_delta_seconds
                if stored.matching.default_timezone:
                    project.default_timezone = stored.matching.default_timezone
            except (OSError, ProjectError) as exc:
                logger.warning("Project settings not updated: %s", exc)

        scanned_files = list(scan_source_directory(source_root))
        total = len(scanned_files)
        result = IndexResult(scanned=total)
        counts: Counter[str] = Counter()

        existing = {
            row.path: row
            for row in session.scalars(select(SourceFile).where(SourceFile.project_id == project.id))
        }

        last_checkpoint = 0.0
        interval = max(checkpoint_every, 1)

        def maybe_checkpoint(index: int) -> None:
            nonlocal last_checkpoint
            if checkpoint is None or total == 0:
                return
            now = time.monotonic()
            count_due = index == 1 or index == total or index % interval == 0
            time_due = now - last_checkpoint >= _CHECKPOINT_MIN_SECONDS
            if not count_due and not time_due:
                return
            session.flush()
            checkpoint()
            last_checkpoint = now

        for index, scanned in enumerate(scanned_files, start=1):
            path_str = str(scanned.path)
            if progress is not None:
                progress(
                    IndexProgress(
                        current=index,
                        total=total,
                        path=path_str,
                        message=f"Indexiere {scanned.filename}",
                    )
                )
            try:
                action, metadata_error = self._upsert_file(session, project, scanned, existing.get(path_str))
                if action == "indexed":
                    result.indexed += 1
                elif action == "updated":
                    result.updated += 1
                else:
                    result.skipped_unchanged += 1
                if metadata_error:
                    result.errors += 1
                counts[scanned.kind.value] += 1
            except OSError as exc:
                result.errors += 1
                logger.exception("Failed to index %s", path_str)
                session.add(
                    FileError(
                        project_id=project.id,
                        path=path_str,
                        stage="index",
                        message=str(exc),
                    )
                )
            maybe_checkpoint(index)

        result.by_kind = dict(counts)
        session.flush()
        self._ingest_gps(session, project, result, progress, gps_delta)
        if checkpoint is not None:
            checkpoint()
        if generate_thumbnails:
            self.build_previews(session, project, result, progress, project_dir)
        return result

    def _ingest_gps(
        self,
        session: Session,
        project: Project,
        result: IndexResult,
        progress: ProgressCallback | None,
        max_delta_seconds: int | None = None,
    ) -> None:
        def on_gps_progress(current: int, total: int, path: str) -> None:
            if progress is None:
                return
            progress(
                IndexProgress(
                    current=current,
                    total=max(total, 1),
                    path=path,
                    message="GPS-Tracks und Positionen",
                )
            )

        gps_result = ingest_gps_tracks(
            session,
            project,
            max_delta_seconds=max_delta_seconds or self.settings.gps_match_max_delta_seconds,
            progress=on_gps_progress,
        )
        result.tracks_ingested = gps_result.tracks
        result.track_points = gps_result.points
        result.positions_matched = gps_result.matched
        result.errors += gps_result.errors

    def build_previews(
        self,
        session: Session,
        project: Project,
        result: IndexResult,
        progress: ProgressCallback | None,
        project_dir: Path | None,
    ) -> None:
        folder = project_dir or _project_dir_from_session(session)
        if folder is None:
            return
        ensure_photo_and_video_rows(session, project)
        thumbs_dir = folder / "thumbnails"
        thumbs_dir.mkdir(parents=True, exist_ok=True)

        def on_thumb_progress(current: int, total: int, path: str) -> None:
            if progress is None:
                return
            progress(
                IndexProgress(
                    current=current,
                    total=max(total, 1),
                    path=path,
                    message="Vorschaubilder",
                )
            )

        thumbs = generate_project_thumbnails(
            session,
            project,
            thumbs_dir,
            size=self.settings.default_thumbnail_size,
            progress=on_thumb_progress,
        )
        result.thumbnails_written = thumbs.written
        result.thumbnails_skipped = thumbs.skipped

    def _upsert_file(
        self,
        session: Session,
        project: Project,
        scanned: ScannedFile,
        existing: SourceFile | None,
    ) -> tuple[str, bool]:
        if existing is not None and _unchanged(existing, scanned):
            existing.status = "ok"
            existing.error_message = None
            metadata_error = self._fill_metadata(session, project, existing, scanned)
            return "skipped", metadata_error

        digest = sha256_file(scanned.path) if self.compute_hash else None
        now = datetime.now(tz=UTC)

        if existing is None:
            row = SourceFile(
                project_id=project.id,
                path=str(scanned.path),
                filename=scanned.filename,
                file_kind=scanned.kind.value,
                extension=scanned.path.suffix.lower(),
                mime_type=scanned.mime_type,
                size_bytes=scanned.size_bytes,
                fs_created_at=scanned.fs_created_at,
                fs_modified_at=scanned.fs_modified_at,
                sha256=digest,
                imported_at=now,
                status="ok",
                timezone_unknown=True,
                position_source=None,
            )
            session.add(row)
            metadata_error = self._fill_metadata(session, project, row, scanned)
            return "indexed", metadata_error

        existing.filename = scanned.filename
        existing.file_kind = scanned.kind.value
        existing.extension = scanned.path.suffix.lower()
        existing.mime_type = scanned.mime_type
        existing.size_bytes = scanned.size_bytes
        existing.fs_created_at = scanned.fs_created_at
        existing.fs_modified_at = scanned.fs_modified_at
        existing.sha256 = digest
        existing.imported_at = now
        existing.status = "ok"
        existing.error_message = None
        metadata_error = self._fill_metadata(session, project, existing, scanned)
        return "updated", metadata_error

    def _fill_metadata(
        self,
        session: Session,
        project: Project,
        row: SourceFile,
        scanned: ScannedFile,
    ) -> bool:
        if scanned.kind not in {FileKind.PHOTO, FileKind.VIDEO}:
            return False
        has_real_time = row.captured_at is not None and row.captured_at_source != "filesystem_mtime"
        has_gps = row.gps_latitude is not None
        has_camera = bool(row.camera)
        if has_real_time and has_gps and has_camera:
            return False
        try:
            apply_metadata(row, scanned.path, self.metadata_provider)
            return False
        except (MetadataError, OSError, ValueError) as exc:
            logger.warning("Metadata failed for %s: %s", scanned.path, exc)
            session.add(
                FileError(
                    project_id=project.id,
                    path=str(scanned.path),
                    stage="metadata",
                    message=str(exc),
                )
            )
            fallback = filesystem_captured_time(scanned.path)
            if row.captured_at is None and fallback is not None and fallback.normalized is not None:
                row.captured_at_raw = fallback.raw_value
                row.captured_at = fallback.normalized
                row.captured_at_source = fallback.source
                row.timezone_name = None
                row.timezone_unknown = True
            return True


def _unchanged(existing: SourceFile, scanned: ScannedFile) -> bool:
    if existing.size_bytes != scanned.size_bytes:
        return False
    if existing.fs_modified_at is None or scanned.fs_modified_at is None:
        return False
    existing_mtime = existing.fs_modified_at
    if existing_mtime.tzinfo is None:
        existing_mtime = existing_mtime.replace(tzinfo=UTC)
    if abs((existing_mtime - scanned.fs_modified_at).total_seconds()) > 1:
        return False
    return existing.sha256 is not None


def _project_dir_from_session(session: Session) -> Path | None:
    bind = session.get_bind()
    database = getattr(bind.url, "database", None)
    if not database:
        return None
    return Path(database).resolve().parent


def count_by_kind(session: Session, project_id: int) -> dict[str, int]:
    rows = session.scalars(select(SourceFile).where(SourceFile.project_id == project_id))
    counts: Counter[str] = Counter()
    for row in rows:
        counts[row.file_kind] += 1
        if row.gps_latitude is not None:
            counts["located"] += 1
    for kind in FileKind:
        counts.setdefault(kind.value, 0)
    counts.setdefault("located", 0)
    return dict(counts)
