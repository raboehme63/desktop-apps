"""Import FIT and JSON files into the fitness store."""

from __future__ import annotations

import hashlib
import json
import zlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from fitnesscore.database.models import Document, ImportErrorRow, Source, Track
from fitnesscore.parse.classify import classify_path, is_importable
from fitnesscore.parse.fit import documents_from_fit
from fitnesscore.parse.gpx import bbox, tracks_to_gpx
from fitnesscore.parse.igc import documents_from_igc
from fitnesscore.parse.json_doc import documents_from_json
from fitnesscore.parse.types import ParsedDocument
from fitnesscore.store import OpenStore

ProgressFn = Callable[[int, int, str], None]
_COMMIT_EVERY = 40


@dataclass
class ImportResult:
    scanned: int = 0
    imported: int = 0
    skipped: int = 0
    errors: int = 0
    documents: int = 0
    tracks: int = 0
    by_kind: dict[str, int] = field(default_factory=dict)

    def add_kind(self, kind: str) -> None:
        self.by_kind[kind] = self.by_kind.get(kind, 0) + 1


def collect_import_files(target: Path, *, recursive: bool) -> list[Path]:
    if target.is_file():
        return [target] if is_importable(target) else []
    iterator = target.rglob("*") if recursive else target.iterdir()
    files = [path for path in iterator if is_importable(path)]
    return sorted(files, key=lambda item: str(item).lower())


def import_path(
    store: OpenStore,
    target: Path,
    *,
    recursive: bool = False,
    progress: ProgressFn | None = None,
) -> ImportResult:
    files = collect_import_files(target, recursive=recursive)
    result = ImportResult(scanned=len(files))
    if not files:
        return result
    with store.session_factory() as session:
        for index, path in enumerate(files, start=1):
            if progress:
                progress(index, len(files), path.name)
            nested = session.begin_nested()
            try:
                outcome = _import_file(session, path, result)
                nested.commit()
            except Exception as exc:  # noqa: BLE001 - one bad file must not stop the bulk
                nested.rollback()
                result.errors += 1
                session.add(ImportErrorRow(path=str(path), message=str(exc)))
                continue
            if outcome == "skipped":
                result.skipped += 1
            else:
                result.imported += 1
                result.add_kind(outcome)
            if index % _COMMIT_EVERY == 0:
                session.commit()
        session.commit()
    return result


def _import_file(session: Session, path: Path, result: ImportResult) -> str:
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    existing = session.scalar(select(Source).where(Source.sha256 == digest))
    if existing is not None:
        return "skipped"
    kind = classify_path(path)
    if kind is None:
        return "skipped"
    suffix = path.suffix.lower()
    fmt = {".fit": "fit", ".igc": "igc"}.get(suffix, "json")
    parsed = _parse_documents(raw, kind=kind, filename=path.name)
    source = Source(
        path=str(path.resolve()),
        filename=path.name,
        sha256=digest,
        size_bytes=len(raw),
        mtime=_mtime(path),
        format=fmt,
        kind=kind,
        payload_zlib=zlib.compress(raw, level=6),
        status="ok",
    )
    session.add(source)
    session.flush()
    for document in parsed:
        _store_document(session, source, document, result)
    return kind


def _parse_documents(raw: bytes, *, kind: str, filename: str) -> tuple[ParsedDocument, ...]:
    if kind == "fit_activity":
        return documents_from_fit(raw)
    if kind == "igc_flight":
        return documents_from_igc(raw, filename=filename)
    text = raw.decode("utf-8-sig")
    data = json.loads(text)
    return documents_from_json(data, kind=kind, filename=filename)


def _store_document(session: Session, source: Source, parsed: ParsedDocument, result: ImportResult) -> None:
    document = None
    if parsed.dedup_key:
        document = session.scalar(select(Document).where(Document.dedup_key == parsed.dedup_key))
    if document is None:
        document = Document(
            source_id=source.id,
            kind=parsed.kind,
            external_id=parsed.external_id,
            title=parsed.title or None,
            started_at=parsed.started_at,
            ended_at=parsed.ended_at,
            sport_slug=parsed.sport_slug,
            sport_raw=parsed.sport_raw,
            polar_sport_id=parsed.polar_sport_id,
            distance_m=parsed.distance_m,
            duration_s=parsed.duration_s,
            ascent_m=parsed.ascent_m,
            descent_m=parsed.descent_m,
            calories=parsed.calories,
            hr_avg=parsed.hr_avg,
            hr_max=parsed.hr_max,
            dedup_key=parsed.dedup_key,
        )
        session.add(document)
        session.flush()
        result.documents += 1
    _store_track(session, document, parsed, result)


def _store_track(session: Session, document: Document, parsed: ParsedDocument, result: ImportResult) -> None:
    if not parsed.tracks:
        return
    point_count = sum(len(track.points) for track in parsed.tracks)
    existing = session.scalar(select(Track).where(Track.document_id == document.id))
    if existing is not None and existing.point_count >= point_count:
        return
    xml = tracks_to_gpx(parsed.tracks)
    box = bbox(parsed.tracks)
    payload = zlib.compress(xml.encode("utf-8"), level=6)
    if existing is None:
        session.add(
            Track(
                document_id=document.id,
                name=parsed.tracks[0].name,
                point_count=point_count,
                min_lat=box[0] if box else None,
                max_lat=box[1] if box else None,
                min_lon=box[2] if box else None,
                max_lon=box[3] if box else None,
                gpx_zlib=payload,
            )
        )
        result.tracks += 1
        return
    existing.name = parsed.tracks[0].name
    existing.point_count = point_count
    existing.min_lat = box[0] if box else None
    existing.max_lat = box[1] if box else None
    existing.min_lon = box[2] if box else None
    existing.max_lon = box[3] if box else None
    existing.gpx_zlib = payload


def _mtime(path: Path) -> datetime | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    except OSError:
        return None
