"""GPX exported from the activity store into {import}/.ActivityTracks/."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from travelcore.config import DEFAULT_THUMBNAIL_SIZE
from travelcore.database.models import Project, SourceFile
from travelcore.exceptions import ProjectError
from travelcore.gps.parse import parse_gpx

ACTIVITY_TRACKS_DIRNAME = ".ActivityTracks"
LEGACY_ACTIVITY_TRACKS_DIRNAME = ".FitnessTracks"
FITNESS_TRACKS_DIRNAME = ACTIVITY_TRACKS_DIRNAME
_ACTIVITY_DIR_NAMES = frozenset(
    {ACTIVITY_TRACKS_DIRNAME.lower(), LEGACY_ACTIVITY_TRACKS_DIRNAME.lower()}
)


def activity_tracks_dir(source_root: Path) -> Path:
    return Path(source_root) / ACTIVITY_TRACKS_DIRNAME


def fitness_tracks_dir(source_root: Path) -> Path:
    return activity_tracks_dir(source_root)


def activity_track_folders(source_root: Path) -> tuple[Path, ...]:
    """Canonical ``.ActivityTracks`` plus a leftover ``.FitnessTracks`` folder."""

    root = Path(source_root)
    canonical = root / ACTIVITY_TRACKS_DIRNAME
    legacy = root / LEGACY_ACTIVITY_TRACKS_DIRNAME
    folders = [canonical]
    if normalized_path_key(legacy) != normalized_path_key(canonical):
        folders.append(legacy)
    return tuple(folders)


def is_activity_track_path(path: str | Path) -> bool:
    return any(part.lower() in _ACTIVITY_DIR_NAMES for part in Path(path).parts)


def is_fitness_track_path(path: str | Path) -> bool:
    return is_activity_track_path(path)


def normalized_path_key(path: Path) -> str:
    """Stable identity for path comparison on Windows and POSIX."""

    try:
        resolved = path.expanduser().resolve()
    except OSError:
        resolved = path.expanduser()
    return str(resolved).replace("\\", "/").casefold()


def unlink_unwanted_files(
    folders: Sequence[Path],
    *,
    dest: Path,
    wanted_names: Iterable[str],
    suffix: str,
) -> int:
    """Delete exported files that are not in the current load set.

    Keeps matching names only in ``dest``. Copies in a legacy folder are removed.
    """

    wanted = {name.casefold() for name in wanted_names}
    dest_key = normalized_path_key(dest)
    removed = 0
    for folder in folders:
        if not folder.is_dir():
            continue
        keep_wanted = normalized_path_key(folder) == dest_key
        for leftover in list(folder.iterdir()):
            if not leftover.is_file() or leftover.suffix.lower() != suffix:
                continue
            if keep_wanted and leftover.name.casefold() in wanted:
                continue
            leftover.unlink(missing_ok=True)
            removed += 1
    return removed


def index_fitness_gpx_file(
    session: Session,
    project: Project,
    dest: Path,
    *,
    project_dir: Path,
) -> SourceFile | None:
    """Index one exported fitness GPX. Already-indexed paths are left unchanged."""

    path = dest.expanduser().resolve()
    if not path.is_file() or path.suffix.lower() != ".gpx":
        return None
    existing = session.scalar(select(SourceFile).where(SourceFile.path == str(path)))
    if existing is None:
        key = normalized_path_key(path)
        for row in session.scalars(
            select(SourceFile).where(SourceFile.project_id == project.id, SourceFile.filename == path.name)
        ):
            if normalized_path_key(Path(row.path)) == key:
                existing = row
                break
    if existing is not None:
        return existing
    return _index_and_ingest(session, project, path, project_dir)


def _index_and_ingest(session: Session, project: Project, dest: Path, project_dir: Path) -> SourceFile:
    from travelcore.gps.ingest import ingest_gps_source
    from travelcore.media.hashing import sha256_file
    from travelcore.media.thumbnails import write_project_gps_thumbnail
    from travelcore.media.types import FileKind, mime_for_path

    try:
        parsed = parse_gpx(dest)
    except Exception as exc:
        raise ProjectError(f"Ungültige GPX-Datei: {exc}") from exc
    if not any(track.points for track in parsed):
        raise ProjectError("Die GPX-Datei enthält keine Trackpunkte.")
    stat = dest.stat()
    row = SourceFile(
        project_id=project.id,
        path=str(dest.resolve()),
        filename=dest.name,
        file_kind=FileKind.GPS.value,
        extension=dest.suffix.lower(),
        mime_type=mime_for_path(dest),
        size_bytes=int(stat.st_size),
        sha256=sha256_file(dest),
        imported_at=datetime.now(tz=UTC),
        status="ok",
        timezone_unknown=True,
        parked=False,
    )
    session.add(row)
    session.flush()
    ingest_gps_source(session, project, row)
    session.flush()
    write_project_gps_thumbnail(project_dir, row, size=DEFAULT_THUMBNAIL_SIZE)
    return row
