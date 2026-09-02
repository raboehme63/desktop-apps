"""GPX exported from the fitness store into {import}/.FitnessTracks/."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from travelcore.config import DEFAULT_THUMBNAIL_SIZE
from travelcore.database.models import Project, SourceFile
from travelcore.exceptions import ProjectError
from travelcore.gps.parse import parse_gpx

FITNESS_TRACKS_DIRNAME = ".FitnessTracks"


def fitness_tracks_dir(source_root: Path) -> Path:
    return Path(source_root) / FITNESS_TRACKS_DIRNAME


def is_fitness_track_path(path: str | Path) -> bool:
    return any(part.lower() == FITNESS_TRACKS_DIRNAME.lower() for part in Path(path).parts)


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
