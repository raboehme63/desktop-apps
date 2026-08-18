"""Create, open, and describe a travel project folder."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from travelcore.database.models import Project
from travelcore.database.session import (
    create_engine_for_path,
    create_session_factory,
    upgrade_database,
)
from travelcore.exceptions import ProjectError
from travelcore.project_settings import ensure_project_settings

PROJECT_DB_NAME = "project.sqlite"
PROJECT_SUBDIRS = ("thumbnails", "cache", "exports", "logs")


@dataclass(frozen=True, slots=True)
class OpenProject:
    """A project folder with an open SQLite session factory."""

    directory: Path
    db_path: Path
    session_factory: sessionmaker[Session]
    project_id: int
    name: str


class ProjectStore:
    """Manages the on-disk project layout and database lifecycle."""

    def create(self, directory: Path, name: str) -> OpenProject:
        directory = directory.expanduser().resolve()
        if directory.exists() and any(directory.iterdir()):
            db_path = directory / PROJECT_DB_NAME
            if not db_path.exists():
                raise ProjectError(f"Verzeichnis ist nicht leer und enthält kein Projekt: {directory}")
            return self.open(directory)

        directory.mkdir(parents=True, exist_ok=True)
        self._ensure_layout(directory)
        db_path = directory / PROJECT_DB_NAME
        upgrade_database(db_path)
        ensure_project_settings(directory)

        engine = create_engine_for_path(db_path)
        factory = create_session_factory(engine)
        now = datetime.now(tz=UTC)
        with factory() as session:
            project = Project(name=name, created_at=now, updated_at=now)
            session.add(project)
            session.commit()
            session.refresh(project)
            project_id = project.id

        return OpenProject(
            directory=directory,
            db_path=db_path,
            session_factory=factory,
            project_id=project_id,
            name=name,
        )

    def open(self, directory: Path) -> OpenProject:
        directory = directory.expanduser().resolve()
        db_path = directory / PROJECT_DB_NAME
        if not db_path.is_file():
            raise ProjectError(f"Kein Projekt gefunden: {db_path}")

        self._ensure_layout(directory)
        upgrade_database(db_path)
        engine = create_engine_for_path(db_path)
        factory = create_session_factory(engine)
        with factory() as session:
            project = session.scalar(select(Project).order_by(Project.id.asc()))
            if project is None:
                raise ProjectError("Projektdatenbank enthält keinen Projekteintrag.")
            ensure_project_settings(
                directory,
                source_root=project.source_root,
                default_timezone=project.default_timezone,
            )
            return OpenProject(
                directory=directory,
                db_path=db_path,
                session_factory=factory,
                project_id=project.id,
                name=project.name,
            )

    def get_project(self, open_project: OpenProject) -> Project:
        with open_project.session_factory() as session:
            project = session.get(Project, open_project.project_id)
            if project is None:
                raise ProjectError("Projektzeile fehlt in der Datenbank.")
            session.expunge(project)
            return project

    def rename(self, open_project: OpenProject, name: str) -> None:
        with open_project.session_factory() as session:
            project = session.get(Project, open_project.project_id)
            if project is None:
                raise ProjectError("Projektzeile fehlt in der Datenbank.")
            project.name = name
            project.updated_at = datetime.now(tz=UTC)
            session.commit()

    def _ensure_layout(self, directory: Path) -> None:
        for name in PROJECT_SUBDIRS:
            (directory / name).mkdir(parents=True, exist_ok=True)
