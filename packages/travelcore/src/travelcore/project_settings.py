"""Project-folder settings file. Original media files are never written."""

from __future__ import annotations

import logging
import os
import re
import tomllib
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from travelcore.database.models import Project, SourceFile
from travelcore.exceptions import ProjectError

logger = logging.getLogger(__name__)

SETTINGS_FILENAME = "settings.toml"
ExportFormat = Literal["html", "pdf", "latex", "cewe"]
EXPORT_FORMATS: tuple[ExportFormat, ...] = ("html", "pdf", "latex", "cewe")
DEFAULT_STAY_LINK_COLOR = "#ffffff"
DEFAULT_MAP_TRACK_COLOR = "#5b8def"
_HEX_COLOR = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def normalize_stay_link_color(value: object) -> str:
    """CSS hex color for stay-link lines; unknown values become white."""

    return _normalize_hex_color(value, DEFAULT_STAY_LINK_COLOR, aliases={"white": DEFAULT_STAY_LINK_COLOR})


def normalize_map_track_color(value: object) -> str:
    """CSS hex color for Map-Track polylines; unknown values become blue."""

    return _normalize_hex_color(value, DEFAULT_MAP_TRACK_COLOR)


def _normalize_hex_color(
    value: object,
    default: str,
    *,
    aliases: dict[str, str] | None = None,
) -> str:
    text = str(value or "").strip()
    if aliases:
        mapped = aliases.get(text.lower())
        if mapped is not None:
            return mapped
    if not _HEX_COLOR.fullmatch(text):
        return default
    if len(text) == 4:
        return "#" + "".join(char * 2 for char in text[1:]).lower()
    return text.lower()


def parse_default_link_geometry(value: object) -> str:
    """Trip default is Gerade or Bogenlinie. Map-Track stays a per-section choice."""

    return "arc" if str(value or "").strip() == "arc" else "line"


def parse_default_link_dash(value: object) -> str:
    return "dashed" if str(value or "").strip() == "dashed" else "solid"


def parse_default_link_symbol(value: object) -> str:
    from travelcore.timeline.symbols import TRANSPORT_SYMBOLS

    text = str(value or "").strip()
    allowed = {item.key for item in TRANSPORT_SYMBOLS}
    return text if text in allowed else ""


_HEADER = """# Reisetagebuch – Projekteinstellungen
# Liegt im Projektordner. Änderungen auch über Projekt → Einstellungen.

"""


class PathSettings(BaseModel):
    """Location of the original media tree."""

    source_root: str | None = None

    @field_validator("source_root", mode="before")
    @classmethod
    def _blank_root(cls, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None


class ExportSettings(BaseModel):
    default_format: ExportFormat = "html"

    @field_validator("default_format", mode="before")
    @classmethod
    def _known_format(cls, value: object) -> str:
        text = str(value).strip().lower() if value else "html"
        return text if text in EXPORT_FORMATS else "html"


class MatchingSettings(BaseModel):
    gps_match_max_delta_seconds: int = Field(default=120, ge=1, le=86_400)
    default_timezone: str | None = None

    @field_validator("default_timezone", mode="before")
    @classmethod
    def _blank_zone(cls, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None


class PerformanceSettings(BaseModel):
    """CPU workers for hash, metadata and thumbnail extraction."""

    worker_count: int = Field(default=0, ge=0, le=64)


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


class PlaceholderSettings(BaseModel):
    """Keys reserved for later phases. Unknown extras are kept on round-trip."""

    model_config = ConfigDict(extra="allow")

    map_provider: str = "leaflet"
    map_link_color: str = "#ffffff"
    map_track_color: str = "#5b8def"
    map_show_photo_cones: bool = False
    map_show_reserve: bool = False
    map_show_sat_labels: bool = False
    map_show_sat_streets: bool = False
    map_show_flights: bool = True
    map_show_activities: bool = True
    default_link_geometry: str = "line"
    default_link_dash: str = "solid"
    default_link_symbol: str = ""
    journal_language: str = "de"

    @field_validator("map_link_color", mode="before")
    @classmethod
    def _link_color(cls, value: object) -> str:
        return normalize_stay_link_color(value)

    @field_validator("map_track_color", mode="before")
    @classmethod
    def _track_color(cls, value: object) -> str:
        return normalize_map_track_color(value)

    @field_validator("default_link_geometry", mode="before")
    @classmethod
    def _default_geometry(cls, value: object) -> str:
        return parse_default_link_geometry(value)

    @field_validator("default_link_dash", mode="before")
    @classmethod
    def _default_dash(cls, value: object) -> str:
        return parse_default_link_dash(value)

    @field_validator("default_link_symbol", mode="before")
    @classmethod
    def _default_symbol(cls, value: object) -> str:
        return parse_default_link_symbol(value)

    @field_validator(
        "map_show_photo_cones",
        "map_show_reserve",
        "map_show_sat_labels",
        "map_show_sat_streets",
        "map_show_flights",
        "map_show_activities",
        mode="before",
    )
    @classmethod
    def _map_flags(cls, value: object) -> bool:
        return _as_bool(value)


class ProjectSettings(BaseModel):
    """Typed project settings stored next to ``project.sqlite``."""

    model_config = ConfigDict(extra="allow")

    schema_version: int = 1
    paths: PathSettings = Field(default_factory=PathSettings)
    export: ExportSettings = Field(default_factory=ExportSettings)
    matching: MatchingSettings = Field(default_factory=MatchingSettings)
    performance: PerformanceSettings = Field(default_factory=PerformanceSettings)
    placeholders: PlaceholderSettings = Field(default_factory=PlaceholderSettings)

    @property
    def source_root(self) -> str | None:
        return self.paths.source_root

    @source_root.setter
    def source_root(self, value: str | None) -> None:
        self.paths.source_root = value


def settings_path(project_dir: Path) -> Path:
    return project_dir / SETTINGS_FILENAME


def roots_equal(left: Path | str, right: Path | str) -> bool:
    left_text = os.path.normcase(os.path.normpath(str(Path(left).expanduser())))
    right_text = os.path.normcase(os.path.normpath(str(Path(right).expanduser())))
    return left_text.rstrip("\\/") == right_text.rstrip("\\/")


def load_project_settings(project_dir: Path) -> ProjectSettings:
    """Load settings from the project folder, or defaults if the file is missing."""

    path = settings_path(project_dir)
    if not path.is_file():
        return ProjectSettings()
    try:
        raw = path.read_text(encoding="utf-8")
        data = tomllib.loads(raw) if raw.strip() else {}
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ProjectError(f"Projekteinstellungen nicht lesbar: {path.name}") from exc
    if not isinstance(data, dict):
        raise ProjectError(f"Projekteinstellungen ungültig: {path.name}")
    return ProjectSettings.model_validate(data)


def save_project_settings(project_dir: Path, settings: ProjectSettings) -> Path:
    """Write ``settings.toml``. Does not touch original media files."""

    project_dir.mkdir(parents=True, exist_ok=True)
    path = settings_path(project_dir)
    payload = settings.model_dump(mode="python")
    path.write_text(_HEADER + _dump_toml(payload), encoding="utf-8")
    return path


def ensure_project_settings(
    project_dir: Path,
    *,
    source_root: str | None = None,
    default_timezone: str | None = None,
) -> ProjectSettings:
    """Create the settings file if missing, filling known values from the database."""

    path = settings_path(project_dir)
    if path.is_file():
        settings = load_project_settings(project_dir)
    else:
        settings = ProjectSettings()
        settings.paths.source_root = source_root
        settings.matching.default_timezone = default_timezone
        save_project_settings(project_dir, settings)
        return settings
    changed = False
    if settings.paths.source_root is None and source_root:
        settings.paths.source_root = source_root
        changed = True
    if settings.matching.default_timezone is None and default_timezone:
        settings.matching.default_timezone = default_timezone
        changed = True
    if changed:
        save_project_settings(project_dir, settings)
    return settings


def update_source_root(project_dir: Path, source_root: Path) -> ProjectSettings:
    """Persist a newly chosen original-files root without dropping other keys."""

    settings = ensure_project_settings(project_dir)
    settings.paths.source_root = str(source_root.expanduser().resolve())
    save_project_settings(project_dir, settings)
    return settings


def rebase_source_file_paths(
    session: Session,
    project_id: int,
    *,
    old_root: Path,
    new_root: Path,
) -> int:
    """Rewrite indexed paths from ``old_root`` to ``new_root``. Originals are not moved."""

    old = old_root.expanduser()
    new = new_root.expanduser().resolve()
    rows = list(session.scalars(select(SourceFile).where(SourceFile.project_id == project_id)))
    updated = 0
    for row in rows:
        relative = _relative_to_root(row.path, old)
        if relative is None:
            continue
        row.path = str((new / relative).resolve()) if relative.parts else str(new)
        updated += 1
    project = session.get(Project, project_id)
    if project is not None:
        project.source_root = str(new)
    return updated


def _relative_to_root(path: str, root: Path) -> Path | None:
    root_norm = os.path.normpath(str(root)).rstrip("\\/")
    path_norm = os.path.normpath(path)
    if os.path.normcase(path_norm) == os.path.normcase(root_norm):
        return Path()
    prefix = os.path.normcase(root_norm + os.sep)
    if not os.path.normcase(path_norm).startswith(prefix):
        return None
    return Path(path_norm[len(root_norm) :].lstrip("\\/"))


def _dump_toml(data: dict[str, Any]) -> str:
    lines: list[str] = []
    scalars = {key: value for key, value in data.items() if not isinstance(value, dict)}
    tables = {key: value for key, value in data.items() if isinstance(value, dict)}
    for key, value in scalars.items():
        lines.append(f"{key} = {_literal(value)}")
    for name, table in tables.items():
        lines.append("")
        lines.append(f"[{name}]")
        for key, value in table.items():
            if isinstance(value, dict):
                continue
            lines.append(f"{key} = {_literal(value)}")
    return "\n".join(lines) + "\n"


def _literal(value: Any) -> str:
    if value is None:
        return '""'
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    text = str(value).replace("\\", "/").replace('"', '\\"')
    return f'"{text}"'
