"""Engine, sessions, and Alembic upgrades for a project SQLite file."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def sqlite_url(db_path: Path) -> str:
    """Build a SQLAlchemy SQLite URL that works with Windows drive letters."""

    return "sqlite:///" + db_path.resolve().as_posix()


def create_engine_for_path(db_path: Path) -> Engine:
    engine = create_engine(sqlite_url(db_path), future=True)
    _enable_sqlite_foreign_keys(engine)
    return engine


def _enable_sqlite_foreign_keys(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _set_pragma(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
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
