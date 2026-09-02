"""SQLite engine and schema bootstrap for the fitness store."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from fitnesscore.database.models import Base, Meta

SCHEMA_VERSION = "1"
_SQLITE_BUSY_TIMEOUT_MS = 30_000
DB_NAME = "fitness.sqlite"


def sqlite_url(db_path: Path) -> str:
    return "sqlite:///" + db_path.resolve().as_posix()


def create_engine_for_path(db_path: Path) -> Engine:
    engine = create_engine(
        sqlite_url(db_path),
        future=True,
        connect_args={"check_same_thread": False, "timeout": _SQLITE_BUSY_TIMEOUT_MS / 1000},
    )
    _enable_sqlite_pragmas(engine)
    return engine


def _enable_sqlite_pragmas(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _set_pragma(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute(f"PRAGMA busy_timeout={_SQLITE_BUSY_TIMEOUT_MS}")
        cursor.close()


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def init_schema(engine: Engine) -> None:
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        existing = session.scalar(select(Meta).where(Meta.key == "schema_version"))
        if existing is None:
            session.add(Meta(key="schema_version", value=SCHEMA_VERSION))
            session.commit()
