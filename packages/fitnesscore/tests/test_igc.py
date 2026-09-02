from datetime import UTC, datetime
from pathlib import Path

from fitnesscore.cli import main
from fitnesscore.ingest import import_path
from fitnesscore.parse.igc import documents_from_igc
from fitnesscore.query_gpx import export_gpx
from fitnesscore.query_igc import export_igc
from fitnesscore.sports import resolve_igc_sport
from fitnesscore.store import init_store


def _igc_text(
    *,
    date_ddmmyy: str = "150525",
    pilot: str = "Testpilot",
    glider: str = "Ozone",
) -> bytes:
    lines = [
        "AXXX FITNESSCORE",
        f"HFDTEDATE:{date_ddmmyy}",
        f"HFPLTPILOTINCHARGE:{pilot}",
        f"HFGTYGLIDERTYPE:{glider}",
        "B1231504629881N01121180EA0123401234",
        "B1232104630000N01121600EA0124001240",
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def test_documents_from_igc_sets_utc_and_paragliding() -> None:
    docs = documents_from_igc(_igc_text(), filename="flug.igc")
    assert len(docs) == 1
    doc = docs[0]
    assert doc.kind == "igc_flight"
    assert doc.sport_slug == "paragliding"
    assert doc.started_at == datetime(2025, 5, 15, 12, 31, 50, tzinfo=UTC)
    assert doc.ended_at == datetime(2025, 5, 15, 12, 32, 10, tzinfo=UTC)
    assert doc.duration_s == 20
    assert doc.tracks and len(doc.tracks[0].points) == 2
    first = doc.tracks[0].points[0]
    assert abs(first.latitude - 46.4980167) < 1e-4
    assert abs(first.longitude - 11.353) < 1e-4
    assert first.elevation == 1234.0


def test_resolve_igc_sport_from_glider_text() -> None:
    assert resolve_igc_sport("Aeros Discus Hangglider").slug == "hang-gliding"
    assert resolve_igc_sport("LS8 Segelflugzeug").slug == "gliding"
    assert resolve_igc_sport("Ozone Rush").slug == "paragliding"


def test_import_igc_and_export_original_by_sport(tmp_path: Path) -> None:
    store = init_store(tmp_path / "fitness")
    payload = _igc_text(glider="Gleitschirm")
    path = tmp_path / "flug.igc"
    path.write_bytes(payload)
    result = import_path(store, path)
    assert result.imported == 1
    assert result.by_kind["igc_flight"] == 1

    hits = export_igc(
        store,
        sports=("paragliding",),
        date_from=datetime(2025, 5, 1).date(),
        date_to=datetime(2025, 5, 31).date(),
        dest=tmp_path / "out",
    )
    assert len(hits) == 1
    assert hits[0].path.suffix == ".igc"
    assert hits[0].path.read_bytes() == payload
    assert "flug" in hits[0].path.name

    assert (
        export_gpx(
            store,
            sports=("paragliding",),
            date_from=datetime(2025, 5, 1).date(),
            date_to=datetime(2025, 5, 31).date(),
            dest=tmp_path / "gpx",
        )
        == []
    )
    assert (
        export_igc(
            store,
            sports=("kitesurfing",),
            date_from=datetime(2025, 5, 1).date(),
            date_to=datetime(2025, 5, 31).date(),
            dest=tmp_path / "empty",
        )
        == []
    )


def test_export_igc_writes_original_payload(tmp_path: Path) -> None:
    store = init_store(tmp_path / "fitness")
    payload = _igc_text(date_ddmmyy="290826", glider="Gleitschirm")
    path = tmp_path / "flug.igc"
    path.write_bytes(payload)
    assert import_path(store, path).imported == 1

    hits = export_igc(
        store,
        date_from=datetime(2026, 8, 1).date(),
        date_to=datetime(2026, 9, 1).date(),
        dest=tmp_path / "out",
    )
    assert len(hits) == 1
    assert hits[0].path.suffix == ".igc"
    assert hits[0].path.read_bytes() == payload
    outside = export_igc(
        store,
        date_from=datetime(2026, 1, 1).date(),
        date_to=datetime(2026, 1, 31).date(),
        dest=tmp_path / "empty",
    )
    assert outside == []


def test_cli_export_igc(tmp_path: Path) -> None:
    db = tmp_path / "store"
    source = tmp_path / "flug.igc"
    payload = _igc_text()
    source.write_bytes(payload)
    out = tmp_path / "out"
    assert main(["--db", str(db), "init"]) == 0
    assert main(["--db", str(db), "import", "-f", str(source)]) == 0
    assert (
        main(
            [
                "--db",
                str(db),
                "export-igc",
                "--sports",
                "paragliding",
                "--from",
                "2025-05-01",
                "--to",
                "2025-05-31",
                "--out",
                str(out),
            ]
        )
        == 0
    )
    files = list(out.glob("*.igc"))
    assert len(files) == 1
    assert files[0].read_bytes() == payload
    assert list(out.glob("*.gpx")) == []
