"""GPX files for connection Map-Tracks, stored under {import}/.MapTracks/."""

from __future__ import annotations

import re
import shutil
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from travelcore.config import DEFAULT_THUMBNAIL_SIZE
from travelcore.database.models import Project, SourceFile
from travelcore.exceptions import ProjectError
from travelcore.gps.parse import parse_gpx

MAP_TRACKS_DIRNAME = ".MapTracks"
LEGACY_MAP_TRACKS_DIRNAME = "MapTracks"
MAP_TRACK_STEM = "Map-Track"
_MAP_TRACK_DIR_NAMES = frozenset({MAP_TRACKS_DIRNAME.lower(), LEGACY_MAP_TRACKS_DIRNAME.lower()})


def map_tracks_dir(source_root: Path) -> Path:
    return Path(source_root) / MAP_TRACKS_DIRNAME


def resolve_source_root(source_root: Path | str | None) -> Path:
    """Import folder that owns ``.MapTracks``. Missing or invalid paths fail clearly."""

    text = str(source_root or "").strip()
    if not text:
        raise ProjectError("Bitte zuerst den Import-Ordner unter Projekt → Einstellungen setzen.")
    path = Path(text).expanduser().resolve()
    if not path.is_dir():
        raise ProjectError(f"Import-Ordner existiert nicht: {path}")
    return path


def is_map_track_path(path: str | Path) -> bool:
    return any(part.lower() in _MAP_TRACK_DIR_NAMES for part in Path(path).parts)


def map_track_display_name(filename: str) -> str:
    """Stable label in galleries and combos: Map-Track, Map-Track 2, or the route start–end stem."""

    stem = Path(filename).stem
    prefix = MAP_TRACK_STEM + "-"
    if stem == MAP_TRACK_STEM:
        return MAP_TRACK_STEM
    if stem.startswith(prefix) and stem[len(prefix) :].isdigit():
        return f"{MAP_TRACK_STEM} {stem[len(prefix) :]}"
    return stem or MAP_TRACK_STEM


def map_track_name_suggestion(stem: str) -> str:
    """Editable default in the Maps-Link name dialog: dashes become spaces."""

    text = Path(stem).stem.replace("-", " ").strip()
    return text or MAP_TRACK_STEM


def list_map_tracks(session: Session, project_id: int) -> list[tuple[int, str]]:
    from travelcore.media.types import FileKind

    rows = session.scalars(
        select(SourceFile)
        .where(SourceFile.project_id == project_id, SourceFile.file_kind == FileKind.GPS.value)
        .order_by(SourceFile.filename.asc(), SourceFile.id.asc())
    )
    found: list[tuple[int, str]] = []
    for row in rows:
        if row.id is None or not is_map_track_path(row.path):
            continue
        found.append((row.id, map_track_display_name(row.filename)))
    return found


def referenced_map_track_ids(outbound: object | None, links: object = ()) -> list[int]:
    found: list[int] = []
    extra = tuple(links) if links else ()
    for link in ((outbound,) if outbound is not None else ()) + extra:
        geometry = str(getattr(link, "geometry", "") or "")
        source_id = getattr(link, "track_source_file_id", None)
        if geometry != "map_track" or source_id is None:
            continue
        if source_id not in found:
            found.append(int(source_id))
    return found


def import_map_track_file(
    session: Session,
    project: Project,
    source: Path,
    *,
    source_root: Path | str | None,
    project_dir: Path,
    stem: str | None = None,
) -> SourceFile:
    """Copy a GPX into ``{import}/.MapTracks``, index it, and ingest points. The original is only read."""

    path = source.expanduser().resolve()
    if not path.is_file():
        raise ProjectError(f"Datei nicht gefunden: {path}")
    if path.suffix.lower() != ".gpx":
        raise ProjectError("Bitte eine GPX-Datei wählen.")
    return _store_map_track(
        session,
        project,
        resolve_source_root(source_root),
        project_dir,
        path,
        stem=stem or MAP_TRACK_STEM,
    )


def import_map_track_gpx(
    session: Session,
    project: Project,
    xml: str,
    *,
    source_root: Path | str | None,
    project_dir: Path,
    stem: str | None = None,
) -> SourceFile:
    """Write generated GPX XML into ``{import}/.MapTracks`` and ingest it."""

    text = xml.strip()
    if not text:
        raise ProjectError("Die GPX-Datei ist leer.")
    dest_dir = _ensure_map_tracks_dir(resolve_source_root(source_root))
    dest = _unique_gpx_path(dest_dir, stem or MAP_TRACK_STEM)
    dest.write_text(xml if xml.endswith("\n") else xml + "\n", encoding="utf-8")
    return _index_and_ingest(session, project, dest, project_dir)


def _store_map_track(
    session: Session,
    project: Project,
    source_root: Path,
    project_dir: Path,
    source: Path,
    *,
    stem: str,
) -> SourceFile:
    dest_dir = _ensure_map_tracks_dir(source_root)
    dest = _unique_gpx_path(dest_dir, stem)
    shutil.copy2(source, dest)
    return _index_and_ingest(session, project, dest, project_dir)


def _index_and_ingest(session: Session, project: Project, dest: Path, project_dir: Path) -> SourceFile:
    from travelcore.gps.ingest import ingest_gps_source
    from travelcore.media.hashing import sha256_file
    from travelcore.media.types import FileKind, mime_for_path

    try:
        parsed = parse_gpx(dest)
    except Exception as exc:
        dest.unlink(missing_ok=True)
        raise ProjectError(f"Ungültige GPX-Datei: {exc}") from exc
    if not any(track.points for track in parsed):
        dest.unlink(missing_ok=True)
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
        parked=True,
    )
    session.add(row)
    session.flush()
    ingest_gps_source(session, project, row)
    session.flush()
    _write_map_track_thumbnail(project_dir, row)
    return row


def _write_map_track_thumbnail(project_dir: Path, row: SourceFile) -> None:
    from travelcore.media.thumbnails import write_project_gps_thumbnail

    write_project_gps_thumbnail(project_dir, row, size=DEFAULT_THUMBNAIL_SIZE)


def _ensure_map_tracks_dir(source_root: Path) -> Path:
    dest = map_tracks_dir(source_root)
    dest.mkdir(parents=True, exist_ok=True)
    return dest


def _unique_gpx_path(directory: Path, stem: str) -> Path:
    cleaned = _safe_stem(stem)
    candidate = directory / f"{cleaned}.gpx"
    index = 2
    while candidate.exists():
        candidate = directory / f"{cleaned}-{index}.gpx"
        index += 1
    return candidate


def _safe_stem(stem: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]', "", stem)
    cleaned = re.sub(r"\s+", "-", cleaned.strip())
    cleaned = cleaned.strip(".-")
    return cleaned[:80] or MAP_TRACK_STEM
