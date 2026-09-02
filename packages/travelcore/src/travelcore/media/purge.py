"""Remove source files that vanished from disk from the journal index."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from travelcore.database.models import (
    FileError,
    GpsPoint,
    GpsTrack,
    Photo,
    PhotoAnalysis,
    SectionMember,
    SimilarityGroupMember,
    SourceFile,
    TextNote,
    TripDay,
    TripSection,
    Video,
)
from travelcore.gps.maptracks import is_map_track_path
from travelcore.media.scanner import is_skipped_source_path, scan_source_directory

logger = logging.getLogger(__name__)

_IN_CHUNK = 400
_NAME_SAMPLE = 5


@dataclass(frozen=True, slots=True)
class SourceSyncPlan:
    """Diff between the source tree and the index, without hashing."""

    new_count: int
    missing_count: int
    present_count: int
    new_names: tuple[str, ...]
    missing_names: tuple[str, ...]


def plan_source_sync(session: Session, project_id: int, source_root: Path) -> SourceSyncPlan:
    """Count new and missing files for the Import sync dialog."""

    source_root = source_root.expanduser().resolve()
    scanned = list(scan_source_directory(source_root))
    scanned_paths = {str(item.path) for item in scanned}
    existing = [
        row
        for row in session.scalars(select(SourceFile).where(SourceFile.project_id == project_id))
        if not is_skipped_source_path(Path(row.path)) and not is_map_track_path(row.path)
    ]
    existing_paths = {row.path for row in existing}
    missing = [row for row in existing if row.path not in scanned_paths]
    new_files = [item for item in scanned if str(item.path) not in existing_paths]
    present = existing_paths & scanned_paths
    return SourceSyncPlan(
        new_count=len(new_files),
        missing_count=len(missing),
        present_count=len(present),
        new_names=tuple(item.filename for item in new_files[:_NAME_SAMPLE]),
        missing_names=tuple(row.filename for row in missing[:_NAME_SAMPLE]),
    )


def purge_source_files(
    session: Session,
    rows: Sequence[SourceFile],
    *,
    existing: dict[str, SourceFile] | None = None,
    thumbs_dir: Path | None = None,
) -> int:
    """Delete index rows, journal membership, GPS tracks, and cached thumbnails.

    Originals on disk are never written. ``row.path`` itself is not unlinked.
    """

    stale = [row for row in rows if row.id is not None]
    if not stale:
        return 0
    ids = [row.id for row in stale]
    paths = [row.path for row in stale]
    project_id = stale[0].project_id

    for chunk in _chunks(ids):
        session.execute(delete(SectionMember).where(SectionMember.source_file_id.in_(chunk)))
        session.execute(
            update(TripSection)
            .where(TripSection.cover_source_file_id.in_(chunk))
            .values(cover_source_file_id=None)
        )
        session.execute(
            update(TripSection)
            .where(TripSection.outbound_track_source_file_id.in_(chunk))
            .values(outbound_track_source_file_id=None)
        )
        session.execute(
            update(TripDay).where(TripDay.cover_source_file_id.in_(chunk)).values(cover_source_file_id=None)
        )
        photo_ids = list(session.scalars(select(Photo.id).where(Photo.source_file_id.in_(chunk))))
        if photo_ids:
            session.execute(delete(PhotoAnalysis).where(PhotoAnalysis.photo_id.in_(photo_ids)))
        session.execute(delete(Photo).where(Photo.source_file_id.in_(chunk)))
        session.execute(delete(Video).where(Video.source_file_id.in_(chunk)))
        session.execute(
            delete(SimilarityGroupMember).where(SimilarityGroupMember.source_file_id.in_(chunk))
        )
        track_ids = list(session.scalars(select(GpsTrack.id).where(GpsTrack.source_file_id.in_(chunk))))
        if track_ids:
            session.execute(delete(GpsPoint).where(GpsPoint.track_id.in_(track_ids)))
            session.execute(delete(GpsTrack).where(GpsTrack.id.in_(track_ids)))
        session.execute(update(TextNote).where(TextNote.source_file_id.in_(chunk)).values(source_file_id=None))
        session.execute(delete(SourceFile).where(SourceFile.id.in_(chunk)))

    for chunk_paths in _chunks(paths):
        session.execute(
            delete(FileError).where(FileError.project_id == project_id, FileError.path.in_(chunk_paths))
        )

    _unlink_cached_thumbnails(thumbs_dir, stale)
    if existing is not None:
        for row in stale:
            existing.pop(row.path, None)
    session.flush()
    return len(stale)


def _unlink_cached_thumbnails(thumbs_dir: Path | None, rows: Sequence[SourceFile]) -> None:
    if thumbs_dir is None or not thumbs_dir.is_dir():
        return
    for row in rows:
        original = Path(row.path)
        prefixes: list[str] = []
        if row.sha256:
            prefixes.append(f"{row.sha256}_")
        if row.id is not None:
            prefixes.append(f"sf{row.id}_")
        for path in thumbs_dir.iterdir():
            if not path.is_file():
                continue
            name = path.name
            if not any(name.startswith(prefix) for prefix in prefixes):
                continue
            try:
                if path.resolve() == original.resolve():
                    continue
            except OSError:
                continue
            try:
                path.unlink()
            except OSError:
                logger.debug("Could not remove thumbnail %s", path)


def _chunks[T](items: Sequence[T], size: int = _IN_CHUNK) -> list[Sequence[T]]:
    return [items[index : index + size] for index in range(0, len(items), size)]
