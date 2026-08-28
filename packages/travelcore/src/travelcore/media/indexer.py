"""Index a source directory into the project SQLite database."""

from __future__ import annotations

import logging
import time
from collections import Counter
from collections.abc import Callable, Sequence
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from travelcore.config import AppSettings
from travelcore.database.models import FileError, Project, SourceFile
from travelcore.exceptions import MetadataError, ProjectError
from travelcore.gps.ingest import ingest_gps_tracks
from travelcore.gps.match import DERIVED_SOURCES
from travelcore.media.extract import ExtractRequest, FileFacts, extract_many, init_extract_worker
from travelcore.media.hashing import sha256_file
from travelcore.media.purge import purge_source_files
from travelcore.media.scanner import ScannedFile, is_skipped_source_path, scan_source_directory
from travelcore.media.thumbnails import ensure_photo_and_video_rows, generate_project_thumbnails
from travelcore.media.types import FileKind
from travelcore.metadata.apply import apply_metadata
from travelcore.metadata.composite import DefaultMetadataProvider
from travelcore.metadata.provider import MetadataProvider
from travelcore.metadata.time import filesystem_captured_time
from travelcore.parallel import WorkerPool, resolve_worker_count
from travelcore.pipeline import PipelineStage, run_pipeline
from travelcore.project_settings import ProjectSettings, load_project_settings, update_source_root

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
    tracks_skipped: int = 0
    track_points: int = 0
    positions_matched: int = 0
    positions_unmatched: int = 0
    thumbnails_written: int = 0
    thumbnails_skipped: int = 0
    removed: int = 0
    media_changed: bool = False
    new_media_ids: list[int] = field(default_factory=list)
    by_kind: dict[str, int] = field(default_factory=dict)


@dataclass
class IndexContext:
    """Shared state for one import run. Stages read and write this object."""

    indexer: FileIndexer
    session: Session
    project: Project
    source_root: Path
    result: IndexResult
    workers: int
    pool: WorkerPool | None = None
    progress: ProgressCallback | None = None
    checkpoint: CheckpointCallback | None = None
    checkpoint_every: int = _DEFAULT_CHECKPOINT_EVERY
    project_dir: Path | None = None
    generate_thumbnails: bool = True
    remove_missing: bool = False
    gps_delta: int = 120
    scanned_files: list[ScannedFile] = field(default_factory=list)
    existing: dict[str, SourceFile] = field(default_factory=dict)
    facts_by_path: dict[str, FileFacts] = field(default_factory=dict)
    unchanged_gps_ids: set[int] = field(default_factory=set)
    stored: ProjectSettings | None = None


def default_index_stages() -> tuple[PipelineStage, ...]:
    """TravelJournal import: scan, extract, persist, GPS, optional previews."""

    return (ScanStage(), ExtractStage(), PersistStage(), GpsIngestStage(), PreviewStage())


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
        max_workers: int | None = None,
        pool: WorkerPool | None = None,
        stages: Sequence[PipelineStage] | None = None,
    ) -> None:
        self.compute_hash = compute_hash
        self._owns_provider = metadata_provider is None
        self.metadata_provider = metadata_provider or DefaultMetadataProvider.from_environment()
        self.settings = settings or AppSettings()
        self.max_workers = max_workers
        self._pool = pool
        self._stages = stages

    def index(
        self,
        session: Session,
        project: Project,
        source_root: Path,
        *,
        progress: ProgressCallback | None = None,
        project_dir: Path | None = None,
        generate_thumbnails: bool = True,
        remove_missing: bool = False,
        checkpoint: CheckpointCallback | None = None,
        checkpoint_every: int = _DEFAULT_CHECKPOINT_EVERY,
    ) -> IndexResult:
        source_root = source_root.expanduser().resolve()
        project.source_root = str(source_root)
        project.updated_at = datetime.now(tz=UTC)
        gps_delta = self.settings.gps_match_max_delta_seconds
        settings_dir = project_dir or _project_dir_from_session(session)
        stored: ProjectSettings | None = None
        if settings_dir is not None:
            try:
                stored = update_source_root(settings_dir, source_root)
                gps_delta = stored.matching.gps_match_max_delta_seconds
                if stored.matching.default_timezone:
                    project.default_timezone = stored.matching.default_timezone
            except (OSError, ProjectError) as exc:
                logger.warning("Project settings not updated: %s", exc)

        workers = self._resolve_workers(stored)
        pool_cm = (
            nullcontext(self._pool)
            if self._pool is not None
            else WorkerPool(max_workers=workers, initializer=init_extract_worker)
        )
        ctx = IndexContext(
            indexer=self,
            session=session,
            project=project,
            source_root=source_root,
            result=IndexResult(),
            workers=workers,
            pool=self._pool,
            progress=progress,
            checkpoint=checkpoint,
            checkpoint_every=checkpoint_every,
            project_dir=project_dir,
            generate_thumbnails=generate_thumbnails,
            remove_missing=remove_missing,
            gps_delta=gps_delta,
            stored=stored,
        )
        try:
            with pool_cm as pool:
                ctx.pool = pool
                run_pipeline(ctx, self._stages or default_index_stages())
            return ctx.result
        finally:
            if self._owns_provider:
                closer = getattr(self.metadata_provider, "close", None)
                if callable(closer):
                    closer()

    def _extract_facts(
        self,
        scanned_files: list[ScannedFile],
        existing: dict[str, SourceFile],
        workers: int,
        progress: ProgressCallback | None,
        pool: WorkerPool | None = None,
    ) -> dict[str, FileFacts]:
        requests: list[ExtractRequest] = []
        chunk = self.settings.hash_chunk_size
        for scanned in scanned_files:
            path_str = str(scanned.path)
            row = existing.get(path_str)
            unchanged = row is not None and _unchanged(row, scanned)
            need_hash = self.compute_hash and not unchanged
            if unchanged and scanned.kind == FileKind.GPS and self.compute_hash:
                need_hash = True
            need_meta = _needs_metadata(row, scanned)
            if not need_hash and not need_meta:
                continue
            requests.append(
                ExtractRequest(
                    path=path_str,
                    compute_hash=need_hash,
                    read_metadata=need_meta,
                    hash_chunk_size=chunk,
                )
            )
        if not requests:
            return {}

        def on_progress(current: int, total: int, path: str) -> None:
            if progress is None:
                return
            name = Path(path).name
            progress(
                IndexProgress(
                    current=current,
                    total=max(total, 1),
                    path=path,
                    message=f"Analysiere {name}" if name else "Analysiere Dateien",
                )
            )

        return extract_many(
            requests,
            provider=self.metadata_provider,
            max_workers=workers,
            progress=on_progress,
            pool=pool,
        )

    def _resolve_workers(self, stored: ProjectSettings | None) -> int:
        if self.max_workers is not None:
            requested = self.max_workers
        elif stored is not None and stored.performance.worker_count:
            requested = stored.performance.worker_count
        else:
            requested = self.settings.worker_count
        return resolve_worker_count(requested)

    def _ingest_gps(
        self,
        session: Session,
        project: Project,
        result: IndexResult,
        progress: ProgressCallback | None,
        max_delta_seconds: int | None = None,
        skip_unchanged_ids: set[int] | None = None,
        pool: WorkerPool | None = None,
    ) -> None:
        def on_gps_progress(current: int, total: int, path: str, stage: str = "track") -> None:
            if progress is None:
                return
            name = Path(path).name
            labels = {
                "track": "Track einlesen",
                "skip": "Track unverändert",
                "match": "GPS-Abgleich",
                "done": "GPS-Abgleich fertig",
            }
            heading = labels.get(stage, "Track einlesen")
            text = f"{heading}: {name}" if name else heading
            progress(
                IndexProgress(
                    current=current,
                    total=max(total, 1),
                    path=path,
                    message=text,
                )
            )

        gps_result = ingest_gps_tracks(
            session,
            project,
            max_delta_seconds=max_delta_seconds or self.settings.gps_match_max_delta_seconds,
            progress=on_gps_progress,
            skip_unchanged_ids=skip_unchanged_ids,
            max_workers=self.max_workers,
            pool=pool,
        )
        result.tracks_ingested = gps_result.tracks
        result.tracks_skipped = gps_result.skipped
        result.track_points = gps_result.points
        result.positions_matched = gps_result.matched
        result.positions_unmatched = count_by_kind(session, project.id)["unlocated"]
        result.errors += gps_result.errors

    def build_previews(
        self,
        session: Session,
        project: Project,
        result: IndexResult,
        progress: ProgressCallback | None,
        project_dir: Path | None,
        pool: WorkerPool | None = None,
    ) -> None:
        folder = project_dir or _project_dir_from_session(session)
        if folder is None:
            return
        ensure_photo_and_video_rows(session, project)
        thumbs_dir = folder / "thumbnails"
        thumbs_dir.mkdir(parents=True, exist_ok=True)
        stored: ProjectSettings | None = None
        try:
            stored = load_project_settings(folder)
        except (OSError, ProjectError):
            stored = None
        workers = self._resolve_workers(stored)

        def on_thumb_progress(current: int, total: int, path: str) -> None:
            if progress is None:
                return
            name = Path(path).name
            phase = f"Vorschaubild: {name}" if name else "Vorschaubilder unverändert"
            progress(
                IndexProgress(
                    current=current,
                    total=max(total, 1),
                    path=path,
                    message=phase,
                )
            )

        thumbs = generate_project_thumbnails(
            session,
            project,
            thumbs_dir,
            size=self.settings.default_thumbnail_size,
            progress=on_thumb_progress,
            max_workers=workers,
            pool=pool,
        )
        result.thumbnails_written = thumbs.written
        result.thumbnails_skipped = thumbs.skipped

    def _upsert_file(
        self,
        session: Session,
        project: Project,
        scanned: ScannedFile,
        existing: SourceFile | None,
        facts: FileFacts | None,
    ) -> tuple[str, bool, SourceFile]:
        if facts is not None and facts.io_error:
            raise OSError(facts.io_error)

        if existing is not None and _unchanged(existing, scanned):
            facts_hash = facts.sha256 if facts is not None else None
            if (
                scanned.kind == FileKind.GPS
                and facts_hash
                and existing.sha256
                and facts_hash != existing.sha256
            ):
                pass
            else:
                existing.status = "ok"
                existing.error_message = None
                metadata_error = self._apply_facts(session, project, existing, scanned, facts)
                return "skipped", metadata_error, existing

        digest = _digest_from_facts(facts, scanned, self.compute_hash)
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
            metadata_error = self._apply_facts(session, project, row, scanned, facts)
            return "indexed", metadata_error, row

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
        metadata_error = self._apply_facts(session, project, existing, scanned, facts)
        return "updated", metadata_error, existing

    def _apply_facts(
        self,
        session: Session,
        project: Project,
        row: SourceFile,
        scanned: ScannedFile,
        facts: FileFacts | None,
    ) -> bool:
        if scanned.kind not in {FileKind.PHOTO, FileKind.VIDEO}:
            return False
        if not _needs_metadata(row, scanned) and (facts is None or facts.metadata is None):
            return False
        if facts is not None and facts.metadata_error:
            logger.warning("Metadata failed for %s: %s", scanned.path, facts.metadata_error)
            session.add(
                FileError(
                    project_id=project.id,
                    path=str(scanned.path),
                    stage="metadata",
                    message=facts.metadata_error,
                )
            )
            fallback = facts.filesystem_captured or filesystem_captured_time(scanned.path)
            if row.captured_at is None and fallback is not None and fallback.normalized is not None:
                row.captured_at_raw = fallback.raw_value
                row.captured_at = fallback.normalized
                row.captured_at_source = fallback.source
                row.timezone_name = None
                row.timezone_unknown = True
            return True
        try:
            apply_metadata(
                row,
                scanned.path,
                None if facts is not None and facts.metadata is not None else self.metadata_provider,
                metadata=facts.metadata if facts is not None else None,
                filesystem_fallback=facts.filesystem_captured if facts is not None else None,
            )
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


class ScanStage:
    name = "scan"

    def run(self, ctx: IndexContext) -> None:
        if ctx.progress is not None:
            ctx.progress(
                IndexProgress(
                    current=0,
                    total=0,
                    path=str(ctx.source_root),
                    message="Verzeichnis wird durchsucht…",
                )
            )
        ctx.scanned_files = list(scan_source_directory(ctx.source_root))
        ctx.result.scanned = len(ctx.scanned_files)
        if ctx.progress is not None:
            total = ctx.result.scanned
            found = f"{total} Dateien gefunden" if total else "Keine unterstützten Dateien gefunden"
            ctx.progress(
                IndexProgress(
                    current=0,
                    total=total,
                    path=str(ctx.source_root),
                    message=found,
                )
            )
        ctx.existing = {
            row.path: row
            for row in ctx.session.scalars(select(SourceFile).where(SourceFile.project_id == ctx.project.id))
        }
        thumbs_dir = (ctx.project_dir / "thumbnails") if ctx.project_dir is not None else None
        _drop_skipped_source_files(ctx.session, ctx.existing, thumbs_dir=thumbs_dir)
        if ctx.remove_missing:
            scanned_paths = {str(item.path) for item in ctx.scanned_files}
            missing = [row for path, row in list(ctx.existing.items()) if path not in scanned_paths]
            ctx.result.removed = purge_source_files(
                ctx.session,
                missing,
                existing=ctx.existing,
                thumbs_dir=thumbs_dir,
            )


class ExtractStage:
    name = "extract"

    def run(self, ctx: IndexContext) -> None:
        ctx.facts_by_path = ctx.indexer._extract_facts(
            ctx.scanned_files,
            ctx.existing,
            ctx.workers,
            ctx.progress,
            pool=ctx.pool,
        )


class PersistStage:
    name = "persist"

    def run(self, ctx: IndexContext) -> None:
        session = ctx.session
        project = ctx.project
        result = ctx.result
        existing = ctx.existing
        facts_by_path = ctx.facts_by_path
        scanned_files = ctx.scanned_files
        total = len(scanned_files)
        counts: Counter[str] = Counter()
        last_checkpoint = 0.0
        interval = max(ctx.checkpoint_every, 1)
        new_media_rows: list[SourceFile] = []

        def maybe_checkpoint(index: int) -> None:
            nonlocal last_checkpoint
            if ctx.checkpoint is None or total == 0:
                return
            now = time.monotonic()
            count_due = index == 1 or index == total or index % interval == 0
            time_due = now - last_checkpoint >= _CHECKPOINT_MIN_SECONDS
            if not count_due and not time_due:
                return
            session.flush()
            ctx.checkpoint()
            last_checkpoint = now

        for index, scanned in enumerate(scanned_files, start=1):
            path_str = str(scanned.path)
            if ctx.progress is not None:
                ctx.progress(
                    IndexProgress(
                        current=index,
                        total=total,
                        path=path_str,
                        message=f"Indexiere {scanned.filename}",
                    )
                )
            try:
                action, metadata_error, row = ctx.indexer._upsert_file(
                    session,
                    project,
                    scanned,
                    existing.get(path_str),
                    facts_by_path.get(path_str),
                )
                if action == "indexed":
                    result.indexed += 1
                    if scanned.kind != FileKind.TEXT:
                        new_media_rows.append(row)
                elif action == "updated":
                    result.updated += 1
                else:
                    result.skipped_unchanged += 1
                    row = existing.get(path_str)
                    if scanned.kind == FileKind.GPS and row is not None and row.id is not None:
                        facts = facts_by_path.get(path_str)
                        digest = facts.sha256 if facts is not None else row.sha256
                        if digest and digest == row.sha256:
                            ctx.unchanged_gps_ids.add(row.id)
                if action in {"indexed", "updated"} and scanned.kind in {
                    FileKind.PHOTO,
                    FileKind.VIDEO,
                }:
                    result.media_changed = True
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
        result.new_media_ids = [row.id for row in new_media_rows if row.id is not None]


class GpsIngestStage:
    name = "gps"

    def run(self, ctx: IndexContext) -> None:
        ctx.indexer._ingest_gps(
            ctx.session,
            ctx.project,
            ctx.result,
            ctx.progress,
            ctx.gps_delta,
            skip_unchanged_ids=ctx.unchanged_gps_ids,
            pool=ctx.pool,
        )
        ctx.session.flush()


class PreviewStage:
    name = "preview"

    def run(self, ctx: IndexContext) -> None:
        if not ctx.generate_thumbnails:
            return
        ctx.indexer.build_previews(
            ctx.session,
            ctx.project,
            ctx.result,
            ctx.progress,
            ctx.project_dir,
            pool=ctx.pool,
        )


def _digest_from_facts(facts: FileFacts | None, scanned: ScannedFile, compute_hash: bool) -> str | None:
    if not compute_hash:
        return None
    if facts is not None and facts.sha256:
        return facts.sha256
    return sha256_file(scanned.path)


def _needs_metadata(existing: SourceFile | None, scanned: ScannedFile) -> bool:
    if scanned.kind not in {FileKind.PHOTO, FileKind.VIDEO}:
        return False
    if existing is None:
        return True
    has_real_time = existing.captured_at is not None and existing.captured_at_source != "filesystem_mtime"
    has_gps = existing.gps_latitude is not None
    has_camera = bool(existing.camera)
    has_heading = existing.heading_source is not None
    return not (has_real_time and has_gps and has_camera and has_heading)


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


def _drop_skipped_source_files(
    session: Session,
    existing: dict[str, SourceFile],
    *,
    thumbs_dir: Path | None = None,
) -> int:
    """Remove previously indexed JPEG caches (thumbnails/) from the file index."""

    stale = [row for path, row in existing.items() if is_skipped_source_path(Path(path))]
    return purge_source_files(session, stale, existing=existing, thumbs_dir=thumbs_dir)


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
        if row.file_kind in ("photo", "video"):
            if row.gps_latitude is None:
                counts["unlocated"] += 1
            elif row.position_source in DERIVED_SOURCES:
                counts["matched"] += 1
    for kind in FileKind:
        counts.setdefault(kind.value, 0)
    counts.setdefault("located", 0)
    counts.setdefault("matched", 0)
    counts.setdefault("unlocated", 0)
    return dict(counts)
