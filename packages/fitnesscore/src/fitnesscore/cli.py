"""Command line for the fitness store: init, import, GPX export."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any

from fitnesscore.exceptions import QueryError, StoreError
from fitnesscore.ingest import ImportResult, import_path
from fitnesscore.query_gpx import export_gpx, list_track_sports
from fitnesscore.query_igc import export_igc
from fitnesscore.sports import parse_sport_args
from fitnesscore.store import init_store, open_store


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="fitnessdb",
        description=(
            "Lokale Fitness-Datenbank: importiert Polar-JSON, FIT und IGC vollständig. "
            "GPX-Abfrage für Polar/FIT, IGC-Abfrage liefert die Originaldatei."
        ),
    )
    parser.add_argument(
        "--db",
        metavar="ORDNER",
        help="Store-Ordner oder fitness.sqlite (Standard: ./fitness)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    init_p = sub.add_parser("init", help="Store-Ordner und leere Datenbank anlegen")
    init_p.add_argument("target", nargs="?", help="Ordner (Standard: --db oder ./fitness)")

    imp = sub.add_parser("import", help="JSON-, FIT- und IGC-Dateien importieren (alles, nicht nur Routen)")
    source = imp.add_mutually_exclusive_group(required=True)
    source.add_argument("-f", metavar="DATEI", dest="file", help="einzelne Datei")
    source.add_argument("-d", metavar="VERZEICHNIS", dest="directory", help="Ordner")
    imp.add_argument(
        "-r",
        "--recursive",
        action="store_true",
        dest="recursive",
        help="mit -d Unterverzeichnisse (-r oder --recursive)",
    )

    gpx = sub.add_parser("export-gpx", help="GPX (Polar/FIT) nach optionaler Sportart und Datumsbereich")
    _add_export_args(gpx, dest_help="Zielordner für GPX-Dateien")

    igc = sub.add_parser("export-igc", help="Original-IGC nach optionaler Sportart und Datumsbereich")
    _add_export_args(igc, dest_help="Zielordner für IGC-Dateien")

    sub.add_parser("sports", help="Sportarten auflisten, für die eine Route vorliegt")

    args = parser.parse_args(list(argv) if argv is not None else None)
    db_target = Path(args.db) if args.db else Path("fitness")
    if args.command == "init":
        return _cmd_init(Path(args.target) if args.target else db_target)
    if args.command == "import":
        if args.recursive and not args.directory:
            imp.error("-r gilt nur zusammen mit -d")
        return _cmd_import(db_target, args)
    if args.command == "export-gpx":
        return _cmd_export_gpx(db_target, args)
    if args.command == "export-igc":
        return _cmd_export_igc(db_target, args)
    if args.command == "sports":
        return _cmd_sports(db_target)
    parser.error(f"Unbekanntes Kommando: {args.command}")
    return 2


def _cmd_init(target: Path) -> int:
    try:
        opened = init_store(target)
    except StoreError as exc:
        print(exc, file=sys.stderr)
        return 2
    print(opened.db_path)
    return 0


def _cmd_import(db_target: Path, args: argparse.Namespace) -> int:
    try:
        store = open_store(db_target)
    except StoreError as exc:
        print(exc, file=sys.stderr)
        return 2
    source = Path(args.file) if args.file else Path(args.directory)
    if not source.exists():
        print(f"nicht gefunden: {source}", file=sys.stderr)
        return 2

    def progress(index: int, total: int, name: str) -> None:
        print(".", end="", flush=True)
        _ = (index, total, name)

    result = import_path(store, source, recursive=args.recursive, progress=progress)
    if result.scanned:
        print()
    _print_import(result)
    return 1 if result.errors else 0


def _add_export_args(parser: argparse.ArgumentParser, *, dest_help: str) -> None:
    parser.add_argument(
        "--sports",
        "--sport",
        dest="sports",
        nargs="+",
        metavar="SPORT",
        help="optional: Sportarten (Komma oder mehrere Werte); ohne Angabe alle im Zeitraum",
    )
    parser.add_argument(
        "--from",
        dest="date_from",
        required=True,
        metavar="DATUM",
        help="von (YYYY-MM-DD, UTC)",
    )
    parser.add_argument(
        "--to",
        dest="date_to",
        required=True,
        metavar="DATUM",
        help="bis einschließlich (YYYY-MM-DD, UTC)",
    )
    parser.add_argument("--out", required=True, metavar="ORDNER", help=dest_help)


def _cmd_export_gpx(db_target: Path, args: argparse.Namespace) -> int:
    return _run_export(db_target, args, kind="GPX", exporter=export_gpx)


def _cmd_export_igc(db_target: Path, args: argparse.Namespace) -> int:
    return _run_export(db_target, args, kind="IGC", exporter=export_igc)


def _run_export(
    db_target: Path,
    args: argparse.Namespace,
    *,
    kind: str,
    exporter: Callable[..., list[Any]],
) -> int:
    try:
        store = open_store(db_target)
        hits = exporter(
            store,
            sports=parse_sport_args(args.sports),
            date_from=_parse_date(args.date_from),
            date_to=_parse_date(args.date_to),
            dest=Path(args.out),
        )
    except (StoreError, QueryError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 2
    if not hits:
        print(f"keine {kind}")
        return 0
    for hit in hits:
        print(hit.path)
    print(f"{kind} {len(hits)}")
    return 0


def _cmd_sports(db_target: Path) -> int:
    try:
        store = open_store(db_target)
    except StoreError as exc:
        print(exc, file=sys.stderr)
        return 2
    rows = list_track_sports(store)
    if not rows:
        print("keine Tracks")
        return 0
    for slug, count in rows:
        print(f"{count:5}  {slug}")
    return 0


def _print_import(result: ImportResult) -> None:
    kinds = ", ".join(f"{name} {count}" for name, count in sorted(result.by_kind.items()))
    extra = f", {kinds}" if kinds else ""
    print(
        f"Dateien {result.scanned}, importiert {result.imported}, "
        f"übersprungen {result.skipped}, Fehler {result.errors}, "
        f"Dokumente {result.documents}, Tracks {result.tracks}{extra}"
    )


def _parse_date(text: str) -> date:
    return datetime.strptime(text, "%Y-%m-%d").date()


if __name__ == "__main__":
    raise SystemExit(main())
