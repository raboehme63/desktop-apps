"""Create and open a fitness store (folder + SQLite file)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from fitnesscore.database.engine import (
    DB_NAME,
    LEGACY_DB_NAME,
    create_engine_for_path,
    create_session_factory,
    init_schema,
)
from fitnesscore.exceptions import StoreError


@dataclass(frozen=True, slots=True)
class OpenStore:
    directory: Path
    db_path: Path
    session_factory: sessionmaker[Session]


def resolve_db_path(target: Path, *, create: bool = False) -> Path:
    """Return the SQLite path for a store folder or an explicit ``.sqlite`` file.

    Folders use ``activity.sqlite``. An existing ``fitness.sqlite`` is still opened
    when the new name is absent. New stores always get ``activity.sqlite``.
    """

    path = target.expanduser()
    if path.suffix.lower() == ".sqlite":
        return path
    preferred = path / DB_NAME
    if create or preferred.is_file():
        return preferred
    legacy = path / LEGACY_DB_NAME
    if legacy.is_file():
        return legacy
    return preferred


def init_store(target: Path) -> OpenStore:
    """Create the store folder and empty database."""

    db_path = resolve_db_path(target, create=True)
    directory = db_path.parent
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise StoreError(f"Ordner nicht anlegbar: {directory}") from exc
    if db_path.exists():
        raise StoreError(f"Datenbank existiert bereits: {db_path}")
    return _open(db_path, create=True)


def open_store(target: Path) -> OpenStore:
    """Open an existing store, or create the schema if the file is new."""

    db_path = resolve_db_path(target)
    if not db_path.parent.exists():
        raise StoreError(f"Ordner nicht gefunden: {db_path.parent}")
    return _open(db_path, create=True)


def _open(db_path: Path, *, create: bool) -> OpenStore:
    engine = create_engine_for_path(db_path)
    if create:
        init_schema(engine)
    return OpenStore(
        directory=db_path.parent,
        db_path=db_path,
        session_factory=create_session_factory(engine),
    )
