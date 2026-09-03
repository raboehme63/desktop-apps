"""Read-only overview of travel project folders. Does not open or upgrade SQLite."""

from __future__ import annotations

import fnmatch
import os
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from travelcore.database.project_store import PROJECT_DB_NAME
from travelcore.timeline.countries import country_labels, parse_countries

_DATE_NONE = date.min
CATALOG_SORT_NAME = "name"
CATALOG_SORT_DATE = "date"
CATALOG_SORTS = (CATALOG_SORT_NAME, CATALOG_SORT_DATE)


@dataclass(frozen=True, slots=True)
class ProjectDescriptor:
    """Lightweight row for the project overview. ``missing`` means no ``project.sqlite``."""

    directory: Path
    name: str
    start_date: date | None = None
    end_date: date | None = None
    countries: tuple[str, ...] = ()
    missing: bool = False
    in_root: bool = False
    is_open: bool = False

    def span_label(self) -> str:
        if self.start_date is None and self.end_date is None:
            return "Ohne Datum"
        start = self.start_date or self.end_date
        end = self.end_date or self.start_date
        assert start is not None and end is not None
        if start == end:
            return start.strftime("%d.%m.%Y")
        return f"{start.strftime('%d.%m.%Y')} – {end.strftime('%d.%m.%Y')}"

    def list_label(self) -> str:
        """One overview line: title, date, directory."""

        folder = str(self.directory)
        if self.missing:
            folder = f"Ordner fehlt · {folder}"
        return f"{self.name}  ·  {self.span_label()}  ·  {folder}"

    def location_span_label(self) -> str:
        return self.list_label()


def is_project_directory(directory: Path) -> bool:
    return (directory / PROJECT_DB_NAME).is_file()


def scan_projects_root(root: Path | None) -> list[Path]:
    """Direct children of ``root`` that contain ``project.sqlite``. Not recursive."""

    if root is None:
        return []
    try:
        if not root.is_dir():
            return []
        children = list(root.iterdir())
    except OSError:
        return []
    found = [child for child in children if child.is_dir() and is_project_directory(child)]
    found.sort(key=lambda path: path.name.casefold())
    return found


def describe_project(
    directory: Path,
    *,
    in_root: bool = False,
    is_open: bool = False,
) -> ProjectDescriptor:
    path = _normalize(directory)
    db_path = path / PROJECT_DB_NAME
    fallback = path.name or str(path)
    if not db_path.is_file():
        return ProjectDescriptor(
            directory=path,
            name=fallback,
            missing=True,
            in_root=in_root,
            is_open=is_open,
        )
    name, start, end, countries = _read_sqlite_meta(db_path)
    return ProjectDescriptor(
        directory=path,
        name=name or fallback,
        start_date=start,
        end_date=end,
        countries=countries,
        missing=False,
        in_root=in_root,
        is_open=is_open,
    )


def list_project_catalog(
    *,
    root: Path | None,
    recents: Sequence[Path] = (),
    current: Path | None = None,
) -> list[ProjectDescriptor]:
    """Merge one-level root scan with recent paths. Root wins on duplicates."""

    seen: list[Path] = []
    rows: list[ProjectDescriptor] = []

    def add(directory: Path, *, in_root: bool) -> None:
        path = _normalize(directory)
        if any(_same_path(path, existing) for existing in seen):
            return
        seen.append(path)
        rows.append(
            describe_project(
                path,
                in_root=in_root,
                is_open=current is not None and _same_path(path, current),
            )
        )

    for directory in scan_projects_root(root):
        add(directory, in_root=True)
    for directory in recents:
        add(Path(directory), in_root=False)
    return sort_project_catalog(rows, CATALOG_SORT_NAME)


def normalize_catalog_sort(value: object) -> str:
    text = str(value or "").strip().casefold()
    return CATALOG_SORT_DATE if text == CATALOG_SORT_DATE else CATALOG_SORT_NAME


def catalog_wildcard_pattern(query: str) -> str:
    """If the query has no `*` or `?`, treat it as a contains-match (`*query*`)."""

    text = query.strip()
    if not text:
        return "*"
    if "*" in text or "?" in text:
        return text
    return f"*{text}*"


def catalog_row_matches(row: ProjectDescriptor, query: str) -> bool:
    pattern = catalog_wildcard_pattern(query).casefold()
    fields = [
        row.name,
        str(row.directory),
        row.directory.name,
        row.span_label(),
        row.list_label(),
        *row.countries,
        *country_labels(row.countries),
    ]
    return any(fnmatch.fnmatch(field.casefold(), pattern) for field in fields if field)


def filter_project_catalog(rows: Sequence[ProjectDescriptor], query: str) -> list[ProjectDescriptor]:
    text = query.strip()
    if not text:
        return list(rows)
    return [row for row in rows if catalog_row_matches(row, text)]


def sort_project_catalog(rows: Sequence[ProjectDescriptor], by: str) -> list[ProjectDescriptor]:
    key = normalize_catalog_sort(by)
    return sorted(rows, key=lambda row: _sort_key(row, key))


def _sort_key(row: ProjectDescriptor, by: str) -> tuple[object, ...]:
    if by == CATALOG_SORT_DATE:
        start = row.start_date or _DATE_NONE
        date_rank = -start.toordinal() if start is not _DATE_NONE else 0
        return (row.missing, date_rank, row.name.casefold())
    return (row.missing, row.name.casefold(), str(row.directory).casefold())


def _normalize(directory: Path) -> Path:
    expanded = directory.expanduser()
    try:
        return expanded.resolve()
    except OSError:
        return expanded


def _same_path(left: Path, right: Path) -> bool:
    left_n = _normalize(left)
    right_n = _normalize(right)
    return os.path.normcase(os.path.normpath(str(left_n))) == os.path.normcase(
        os.path.normpath(str(right_n))
    )


def _read_sqlite_meta(
    db_path: Path,
) -> tuple[str | None, date | None, date | None, tuple[str, ...]]:
    try:
        connection = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True, timeout=1.0)
    except sqlite3.Error:
        return None, None, None, ()
    try:
        connection.execute("PRAGMA query_only=ON")
        project = _first_row(connection, "projects")
        name = None
        project_id = None
        if project is not None:
            raw_name = project.get("name")
            name = str(raw_name).strip() if raw_name else None
            project_id = _as_int(project.get("id"))
        start = None
        end = None
        countries: tuple[str, ...] = ()
        trip_id = None
        trip = _first_row(connection, "trips")
        if trip is not None:
            trip_id = _as_int(trip.get("id"))
            start = _parse_date(trip.get("start_date"))
            end = _parse_date(trip.get("end_date"))
            countries = parse_countries(trip.get("countries"))
        if start is None or end is None:
            inferred = _infer_sqlite_dates(connection, project_id, trip_id)
            start = start or inferred[0]
            end = end or inferred[1]
        if start is not None and end is not None and end < start:
            start, end = end, start
        return name, start, end, countries
    except sqlite3.Error:
        return None, None, None, ()
    finally:
        connection.close()


def _has_table(connection: sqlite3.Connection, name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
        (name,),
    ).fetchone()
    return row is not None


def _has_column(connection: sqlite3.Connection, table: str, column: str) -> bool:
    try:
        rows = connection.execute(f'PRAGMA table_info("{table}")').fetchall()
    except sqlite3.Error:
        return False
    wanted = column.casefold()
    return any(str(row[1]).casefold() == wanted for row in rows)


def _first_row(connection: sqlite3.Connection, table: str) -> dict[str, object] | None:
    if not _has_table(connection, table):
        return None
    cursor = connection.execute(f'SELECT * FROM "{table}" ORDER BY id ASC LIMIT 1')
    row = cursor.fetchone()
    if row is None or cursor.description is None:
        return None
    return {str(column[0]): row[index] for index, column in enumerate(cursor.description)}


def _as_int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _infer_sqlite_dates(
    connection: sqlite3.Connection,
    project_id: int | None,
    trip_id: int | None,
) -> tuple[date | None, date | None]:
    """Same sources as ``resolve_trip_dates``: media, sections, trip days."""

    keys: list[date] = []
    if project_id is not None and _has_column(connection, "source_files", "captured_at"):
        keys.extend(
            _minmax_dates(
                connection,
                "SELECT MIN(captured_at), MAX(captured_at) FROM source_files WHERE project_id = ?",
                (project_id,),
            )
        )
    if trip_id is not None:
        if _has_table(connection, "trip_sections"):
            keys.extend(
                _minmax_dates(
                    connection,
                    "SELECT MIN(started_at), MAX(started_at), MIN(ended_at), MAX(ended_at) "
                    "FROM trip_sections WHERE trip_id = ?",
                    (trip_id,),
                )
            )
        if _has_column(connection, "trip_days", "date"):
            keys.extend(
                _minmax_dates(
                    connection,
                    "SELECT MIN(date), MAX(date) FROM trip_days WHERE trip_id = ?",
                    (trip_id,),
                )
            )
    if not keys:
        return None, None
    return min(keys), max(keys)


def _minmax_dates(
    connection: sqlite3.Connection,
    sql: str,
    params: tuple[object, ...],
) -> list[date]:
    try:
        row = connection.execute(sql, params).fetchone()
    except sqlite3.Error:
        return []
    if row is None:
        return []
    return [parsed for parsed in (_parse_date(value) for value in row) if parsed is not None]


def _parse_date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if text.endswith(" UTC"):
        text = text[:-4].strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None
