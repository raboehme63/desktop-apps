"""Export cached GPX tracks filtered by sport and date range."""

from __future__ import annotations

import zlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from fitnesscore.database.models import Document, Track
from fitnesscore.exceptions import QueryError
from fitnesscore.parse.classify import KIND_IGC_FLIGHT
from fitnesscore.sports import match_sports
from fitnesscore.store import OpenStore

ProgressFn = Callable[[int, int, str], None]


@dataclass(frozen=True, slots=True)
class GpxHit:
    document_id: int
    sport_slug: str | None
    started_at: datetime | None
    title: str | None
    point_count: int
    path: Path


def export_gpx(
    store: OpenStore,
    *,
    date_from: date,
    date_to: date,
    dest: Path,
    sports: Sequence[str] | None = None,
    progress: ProgressFn | None = None,
) -> list[GpxHit]:
    if date_to < date_from:
        raise QueryError("Datumsbereich: --to liegt vor --from.")
    dest.mkdir(parents=True, exist_ok=True)
    # SQLite stores DateTime(timezone=True) as naive UTC; aware bounds do not match.
    start = datetime(date_from.year, date_from.month, date_from.day)
    end = datetime(date_to.year, date_to.month, date_to.day) + timedelta(days=1)
    hits: list[GpxHit] = []
    with store.session_factory() as session:
        rows = [
            (document, track)
            for document, track in _matching_tracks(session, start=start, end=end)
            if match_sports(sports, document.sport_slug)
        ]
        total = len(rows)
        for index, (document, track) in enumerate(rows, start=1):
            path = dest / _gpx_filename(document)
            path.write_text(zlib.decompress(track.gpx_zlib).decode("utf-8"), encoding="utf-8")
            hits.append(
                GpxHit(
                    document_id=document.id,
                    sport_slug=document.sport_slug,
                    started_at=document.started_at,
                    title=document.title,
                    point_count=track.point_count,
                    path=path,
                )
            )
            if progress is not None:
                progress(index, total, path.name)
    return hits


def list_track_sports(store: OpenStore) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    with store.session_factory() as session:
        rows = session.execute(
            select(Document.sport_slug).join(Track).where(Document.sport_slug.is_not(None))
        )
        for (slug,) in rows:
            if slug:
                counts[slug] = counts.get(slug, 0) + 1
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))


def _matching_tracks(
    session: Session,
    *,
    start: datetime,
    end: datetime,
) -> list[tuple[Document, Track]]:
    stmt = (
        select(Document, Track)
        .join(Track, Track.document_id == Document.id)
        .where(Document.kind != KIND_IGC_FLIGHT)
        .where(Document.started_at.is_not(None))
        .where(Document.started_at >= start)
        .where(Document.started_at < end)
        .order_by(Document.started_at, Document.id)
    )
    return list(session.execute(stmt).all())


def _gpx_filename(document: Document) -> str:
    stamp = "unknown-time"
    if document.started_at is not None:
        started = document.started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        stamp = started.astimezone(UTC).strftime("%Y-%m-%dT%H-%M-%S")
    sport = document.sport_slug or "unknown-sport"
    return f"{stamp}_{sport}_{document.id}.gpx"
