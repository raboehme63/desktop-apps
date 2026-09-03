"""Engine, sessions, and Alembic upgrades for a project SQLite file."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
_SQLITE_BUSY_TIMEOUT_MS = 30_000


def sqlite_url(db_path: Path, *, read_only: bool = False) -> str:
    """Build a SQLAlchemy SQLite URL that works with Windows drive letters."""

    posix = db_path.resolve().as_posix()
    if read_only:
        return db_path.resolve().as_uri() + "?mode=ro"
    return "sqlite:///" + posix


def create_engine_for_path(db_path: Path, *, read_only: bool = False) -> Engine:
    timeout = _SQLITE_BUSY_TIMEOUT_MS / 1000
    if read_only:
        uri = sqlite_url(db_path, read_only=True)

        def _connect() -> sqlite3.Connection:
            return sqlite3.connect(uri, uri=True, timeout=timeout, check_same_thread=False)

        engine = create_engine("sqlite://", future=True, creator=_connect)
    else:
        engine = create_engine(
            sqlite_url(db_path),
            future=True,
            connect_args={"check_same_thread": False, "timeout": timeout},
        )
    _enable_sqlite_pragmas(engine, read_only=read_only)
    return engine


def _enable_sqlite_pragmas(engine: Engine, *, read_only: bool = False) -> None:
    @event.listens_for(engine, "connect")
    def _set_pragma(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        if read_only:
            cursor.execute("PRAGMA query_only=ON")
        else:
            cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute(f"PRAGMA busy_timeout={_SQLITE_BUSY_TIMEOUT_MS}")
        cursor.close()


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def upgrade_database(db_path: Path) -> None:
    """Apply Alembic migrations up to head for the given SQLite file."""

    cfg = Config()
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", sqlite_url(db_path))
    command.upgrade(cfg, "head")
