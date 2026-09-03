from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from travelcore.database.models import SourceFile, Trip, TripDay
from travelcore.database.project_catalog import (
    describe_project,
    list_project_catalog,
    scan_projects_root,
)
from travelcore.database.project_store import PROJECT_DB_NAME, ProjectStore
from travelcore.timeline.build import save_trip_countries, save_trip_dates


def test_scan_projects_root_one_level_only(tmp_path: Path) -> None:
    root = tmp_path / "reisen"
    nested_parent = root / "archiv"
    nested_parent.mkdir(parents=True)
    ProjectStore().create(root / "Italien", "Italien 2025")
    ProjectStore().create(nested_parent / "Versteckt", "Versteckt")
    (root / "kein_projekt").mkdir()
    found = scan_projects_root(root)
    assert [path.name for path in found] == ["Italien"]
    assert scan_projects_root(None) == []
    assert scan_projects_root(tmp_path / "fehlt") == []


def test_describe_project_reads_name_span_and_countries(tmp_path: Path) -> None:
    opened = ProjectStore().create(tmp_path / "Alpen", "Alpen 2025")
    with opened.session_factory() as session:
        _write_trip(
            session,
            opened.project_id,
            "Alpen 2025",
            date(2025, 6, 1),
            date(2025, 6, 10),
            ["AT", "IT"],
        )
        session.commit()
    row = describe_project(opened.directory, in_root=True)
    assert row.missing is False
    assert row.in_root is True
    assert row.name == "Alpen 2025"
    assert row.start_date == date(2025, 6, 1)
    assert row.end_date == date(2025, 6, 10)
    assert row.countries == ("AT", "IT")
    assert row.span_label() == "01.06.2025 – 10.06.2025"
    assert row.list_label() == (
        f"{row.name}  ·  01.06.2025 – 10.06.2025  ·  {row.directory}"
    )


def test_describe_project_infers_span_from_media_when_trip_dates_empty(tmp_path: Path) -> None:
    opened = ProjectStore().create(tmp_path / "Alpen", "Alpen 2025")
    with opened.session_factory() as session:
        session.add(
            _photo(
                opened.project_id,
                tmp_path / "a.jpg",
                datetime(2025, 6, 1, 8, 0, tzinfo=UTC),
            )
        )
        session.add(
            _photo(
                opened.project_id,
                tmp_path / "b.jpg",
                datetime(2025, 6, 10, 18, 0, tzinfo=UTC),
            )
        )
        session.commit()
    row = describe_project(opened.directory)
    assert row.start_date == date(2025, 6, 1)
    assert row.end_date == date(2025, 6, 10)
    assert row.span_label() == "01.06.2025 – 10.06.2025"


def test_describe_project_infers_span_from_trip_days(tmp_path: Path) -> None:
    opened = ProjectStore().create(tmp_path / "Dolomiten", "Dolomiten")
    with opened.session_factory() as session:
        trip = Trip(project_id=opened.project_id, title="Dolomiten", origin="auto")
        session.add(trip)
        session.flush()
        session.add(
            TripDay(
                trip_id=trip.id,
                day_index=0,
                date=datetime(2024, 8, 12, tzinfo=UTC),
                origin="auto",
            )
        )
        session.add(
            TripDay(
                trip_id=trip.id,
                day_index=1,
                date=datetime(2024, 8, 15, tzinfo=UTC),
                origin="auto",
            )
        )
        session.commit()
    row = describe_project(opened.directory)
    assert row.start_date == date(2024, 8, 12)
    assert row.end_date == date(2024, 8, 15)
    assert "Ohne Datum" not in row.list_label()
    assert row.span_label() == "12.08.2024 – 15.08.2024"


def test_describe_project_saved_span_overrides_inferred_media(tmp_path: Path) -> None:
    opened = ProjectStore().create(tmp_path / "Alpen", "Alpen 2025")
    with opened.session_factory() as session:
        session.add(
            _photo(
                opened.project_id,
                tmp_path / "a.jpg",
                datetime(2025, 6, 1, 8, 0, tzinfo=UTC),
            )
        )
        _write_trip(
            session,
            opened.project_id,
            "Alpen 2025",
            date(2025, 5, 1),
            date(2025, 5, 5),
            [],
        )
        session.commit()
    row = describe_project(opened.directory)
    assert row.span_label() == "01.05.2025 – 05.05.2025"


def test_describe_project_marks_missing_folder(tmp_path: Path) -> None:
    gone = tmp_path / "weg"
    row = describe_project(gone)
    assert row.missing is True
    assert row.name == "weg"
    assert row.span_label() == "Ohne Datum"
    assert row.list_label().startswith(f"{row.name}  ·  Ohne Datum  ·  Ordner fehlt · ")


def test_describe_project_survives_unreadable_sqlite(tmp_path: Path) -> None:
    directory = tmp_path / "kaputt"
    directory.mkdir()
    (directory / PROJECT_DB_NAME).write_bytes(b"not a database")
    row = describe_project(directory)
    assert row.missing is False
    assert row.name == "kaputt"


def test_list_project_catalog_merges_root_and_recents(tmp_path: Path) -> None:
    root = tmp_path / "reisen"
    outside = tmp_path / "anders" / "Norwegen"
    gone = tmp_path / "gelöscht" / "Island"
    root.mkdir()
    ProjectStore().create(root / "Italien", "Italien")
    ProjectStore().create(outside, "Norwegen")
    gone.mkdir(parents=True)
    rows = list_project_catalog(
        root=root,
        recents=[outside, gone, root / "Italien"],
        current=root / "Italien",
    )
    names = [row.name for row in rows]
    assert names == ["Italien", "Norwegen", "Island"]
    by_name = {row.name: row for row in rows}
    assert by_name["Italien"].in_root is True
    assert by_name["Italien"].is_open is True
    assert by_name["Norwegen"].in_root is False
    assert by_name["Island"].missing is True


def test_catalog_does_not_require_alembic_version(tmp_path: Path) -> None:
    directory = tmp_path / "alt"
    directory.mkdir()
    import sqlite3

    db = directory / PROJECT_DB_NAME
    connection = sqlite3.connect(db)
    try:
        connection.execute("CREATE TABLE projects (id INTEGER PRIMARY KEY, name TEXT)")
        connection.execute("INSERT INTO projects (id, name) VALUES (1, 'Altprojekt')")
        connection.commit()
    finally:
        connection.close()
    row = describe_project(directory)
    assert row.name == "Altprojekt"
    assert row.missing is False


def test_filter_project_catalog_supports_wildcards(tmp_path: Path) -> None:
    from travelcore.database.project_catalog import filter_project_catalog

    root = tmp_path / "reisen"
    root.mkdir()
    ProjectStore().create(root / "Italien 2025", "Italien 2025")
    ProjectStore().create(root / "Norwegen", "Norwegen")
    ProjectStore().create(root / "Alpen 2024", "Alpen 2024")
    rows = list_project_catalog(root=root)
    names = {row.name for row in filter_project_catalog(rows, "ital")}
    assert names == {"Italien 2025"}
    names = {row.name for row in filter_project_catalog(rows, "*202?")}
    assert names == {"Italien 2025", "Alpen 2024"}
    names = {row.name for row in filter_project_catalog(rows, "?orwegen")}
    assert names == {"Norwegen"}
    assert filter_project_catalog(rows, "xyz") == []
    assert [row.name for row in filter_project_catalog(rows, "")] == [
        "Alpen 2024",
        "Italien 2025",
        "Norwegen",
    ]


def test_sort_project_catalog_by_name_and_date(tmp_path: Path) -> None:
    from travelcore.database.project_catalog import sort_project_catalog

    root = tmp_path / "reisen"
    root.mkdir()
    early = ProjectStore().create(root / "Alpen", "Alpen")
    late = ProjectStore().create(root / "Italien", "Italien")
    ProjectStore().create(root / "OhneDatum", "Ohne Datum")
    with early.session_factory() as session:
        _write_trip(session, early.project_id, "Alpen", date(2024, 1, 1), date(2024, 1, 5), [])
        session.commit()
    with late.session_factory() as session:
        _write_trip(session, late.project_id, "Italien", date(2025, 6, 1), date(2025, 6, 10), [])
        session.commit()
    rows = list_project_catalog(root=root)
    by_name = [row.name for row in sort_project_catalog(rows, "name")]
    assert by_name == ["Alpen", "Italien", "Ohne Datum"]
    by_date = [row.name for row in sort_project_catalog(rows, "date")]
    assert by_date == ["Italien", "Alpen", "Ohne Datum"]


def _photo(project_id: int, path: Path, captured_at: datetime) -> SourceFile:
    return SourceFile(
        project_id=project_id,
        path=str(path),
        filename=path.name,
        file_kind="photo",
        extension=path.suffix or ".jpg",
        size_bytes=10,
        imported_at=captured_at,
        status="ok",
        timezone_unknown=True,
        captured_at=captured_at,
    )


def _write_trip(
    session: Session,
    project_id: int,
    title: str,
    start: date,
    end: date,
    countries: list[str],
) -> None:
    trip = Trip(project_id=project_id, title=title, origin="auto")
    session.add(trip)
    session.flush()
    save_trip_dates(session, trip.id, start, end)
    save_trip_countries(session, trip.id, countries)
