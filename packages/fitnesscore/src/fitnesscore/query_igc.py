"""Export original IGC flight logs filtered by sport and date range."""

from __future__ import annotations

import zlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from fitnesscore.database.models import Document, Source
from fitnesscore.exceptions import QueryError
from fitnesscore.parse.classify import KIND_IGC_FLIGHT
from fitnesscore.sports import match_sports
from fitnesscore.store import OpenStore

ProgressFn = Callable[[int, int, str], None]


@dataclass(frozen=True, slots=True)
class IgcHit:
    document_id: int
    sport_slug: str | None
    started_at: datetime | None
    title: str | None
    path: Path


def export_igc(
    store: OpenStore,
    *,
    date_from: date,
    date_to: date,
    dest: Path,
    sports: Sequence[str] | None = None,
    progress: ProgressFn | None = None,
) -> list[IgcHit]:
    if date_to < date_from:
        raise QueryError("Datumsbereich: --to liegt vor --from.")
    dest.mkdir(parents=True, exist_ok=True)
    # SQLite stores DateTime(timezone=True) as naive UTC; aware bounds do not match.
    start = datetime(date_from.year, date_from.month, date_from.day)
    end = datetime(date_to.year, date_to.month, date_to.day) + timedelta(days=1)
    hits: list[IgcHit] = []
    with store.session_factory() as session:
        rows = [
            (document, source)
            for document, source in _matching_flights(session, start=start, end=end)
            if match_sports(sports, document.sport_slug)
        ]
        total = len(rows)
        for index, (document, source) in enumerate(rows, start=1):
            path = dest / _igc_filename(document, source)
            path.write_bytes(zlib.decompress(source.payload_zlib))
            hits.append(
                IgcHit(
                    document_id=document.id,
                    sport_slug=document.sport_slug,
                    started_at=document.started_at,
                    title=document.title,
                    path=path,
                )
            )
            if progress is not None:
                progress(index, total, path.name)
    return hits


def _matching_flights(
    session: Session,
    *,
    start: datetime,
    end: datetime,
) -> list[tuple[Document, Source]]:
    stmt = (
        select(Document, Source)
        .join(Source, Source.id == Document.source_id)
        .where(Document.kind == KIND_IGC_FLIGHT)
        .where(Source.format == "igc")
        .where(Document.started_at.is_not(None))
        .where(Document.started_at >= start)
        .where(Document.started_at < end)
        .order_by(Document.started_at, Document.id)
    )
    return list(session.execute(stmt).all())


def _igc_filename(document: Document, source: Source) -> str:
    stamp = "unknown-time"
    if document.started_at is not None:
        started = document.started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        stamp = started.astimezone(UTC).strftime("%Y-%m-%dT%H-%M-%S")
    stem = Path(source.filename).stem or "flight"
    return f"{stamp}_{stem}_{document.id}.igc"
