"""Persist GPX tracks and fill media positions from the track timeline."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from travelcore.database.models import FileError, GpsPoint, GpsTrack, Project, SourceFile
from travelcore.exceptions import GpsError
from travelcore.gps.match import (
    PROTECTED_SOURCES,
    SOURCE_INTERPOLATED,
    SOURCE_NEAREST,
    match_position,
    media_time_utc,
)
from travelcore.gps.parse import ParsedTrack, parse_gpx
from travelcore.gps.types import GpsFix, TrackPoint

logger = logging.getLogger(__name__)

ProgressFn = Callable[[int, int, str], None]

SOURCE_TRACK = "gpx_track"
REPRESENTATIVE_POINT_LIMIT = 20
TRACK_POSITION_CONFIDENCE = 0.9


@dataclass(slots=True)
class GpsIngestResult:
    tracks: int = 0
    points: int = 0
    matched: int = 0
    errors: int = 0


@dataclass(frozen=True, slots=True)
class GpxSourceSummary:
    """Representative position and start time for a GPX source file row."""

    latitude: float | None = None
    longitude: float | None = None
    altitude: float | None = None
    started_at: datetime | None = None


def ingest_gps_tracks(
    session: Session,
    project: Project,
    *,
    max_delta_seconds: int = 120,
    progress: ProgressFn | None = None,
) -> GpsIngestResult:
    """Parse GPX source files, store points, and match media without EXIF GPS."""

    result = GpsIngestResult()
    gps_rows = list(
        session.scalars(
            select(SourceFile).where(
                SourceFile.project_id == project.id,
                SourceFile.file_kind == "gps",
            )
        )
    )
    total = max(len(gps_rows), 1)
    for index, row in enumerate(gps_rows, start=1):
        if progress is not None:
            progress(index, total, row.path)
        suffix = Path(row.path).suffix.lower()
        if suffix != ".gpx":
            continue
        try:
            parsed = parse_gpx(Path(row.path))
        except GpsError as exc:
            logger.warning("GPX parse failed for %s: %s", row.path, exc)
            session.add(
                FileError(
                    project_id=project.id,
                    path=row.path,
                    stage="gpx",
                    message=str(exc),
                )
            )
            result.errors += 1
            continue
        stored = _replace_tracks(session, project, row, parsed)
        result.tracks += stored[0]
        result.points += stored[1]

    session.flush()
    timed_points = _load_timed_points(session, project.id)
    if not timed_points:
        return result
    media_rows = list(
        session.scalars(
            select(SourceFile).where(
                SourceFile.project_id == project.id,
                SourceFile.file_kind.in_(("photo", "video")),
            )
        )
    )
    media_total = max(len(media_rows), 1)
    for index, row in enumerate(media_rows, start=1):
        if progress is not None:
            progress(index, media_total, row.path)
        if not _should_match(row) or row.captured_at is None:
            continue
        moment = media_time_utc(
            row.captured_at,
            timezone_name=row.timezone_name,
            timezone_unknown=row.timezone_unknown,
            default_timezone=project.default_timezone,
        )
        fix = match_position(moment, timed_points, max_delta_seconds=float(max_delta_seconds))
        if fix is None:
            continue
        _apply_fix(row, fix)
        result.matched += 1
    return result


def _should_match(row: SourceFile) -> bool:
    if row.captured_at is None:
        return False
    if row.gps_latitude is None:
        return True
    return row.position_source in {SOURCE_INTERPOLATED, SOURCE_NEAREST}


def _apply_fix(row: SourceFile, fix: GpsFix) -> None:
    row.gps_latitude = fix.latitude
    row.gps_longitude = fix.longitude
    row.gps_altitude = fix.altitude
    row.position_source = fix.source
    row.position_confidence = fix.confidence
    row.position_time_delta_seconds = fix.time_delta_seconds


def _replace_tracks(
    session: Session,
    project: Project,
    source: SourceFile,
    parsed: tuple[ParsedTrack, ...],
) -> tuple[int, int]:
    existing_ids = list(session.scalars(select(GpsTrack.id).where(GpsTrack.source_file_id == source.id)))
    if existing_ids:
        session.execute(delete(GpsPoint).where(GpsPoint.track_id.in_(existing_ids)))
        session.execute(delete(GpsTrack).where(GpsTrack.id.in_(existing_ids)))
        session.flush()
    track_count = 0
    point_count = 0
    for item in parsed:
        if not item.points:
            continue
        track = GpsTrack(
            project_id=project.id,
            source_file_id=source.id,
            name=item.name,
            origin="auto",
        )
        session.add(track)
        session.flush()
        session.add_all(
            [
                GpsPoint(
                    track_id=track.id,
                    segment_id=point.segment_id,
                    latitude=point.latitude,
                    longitude=point.longitude,
                    altitude=point.altitude,
                    recorded_at=point.recorded_at,
                    sequence_index=point.sequence_index,
                )
                for point in item.points
            ]
        )
        track_count += 1
        point_count += len(item.points)
    _apply_gpx_source_metadata(source, parsed)
    return track_count, point_count


def summarize_parsed_tracks(
    parsed: tuple[ParsedTrack, ...],
    *,
    limit: int = REPRESENTATIVE_POINT_LIMIT,
) -> GpxSourceSummary:
    """Mean of the first ``limit`` points plus the first timed point."""

    sample: list[TrackPoint] = []
    started_at: datetime | None = None
    for point in _iter_track_points(parsed):
        if len(sample) < limit:
            sample.append(point)
        if started_at is None and point.recorded_at is not None:
            started_at = point.recorded_at
        if len(sample) >= limit and started_at is not None:
            break
    if not sample:
        return GpxSourceSummary()
    altitudes = [point.altitude for point in sample if point.altitude is not None]
    return GpxSourceSummary(
        latitude=sum(point.latitude for point in sample) / len(sample),
        longitude=sum(point.longitude for point in sample) / len(sample),
        altitude=sum(altitudes) / len(altitudes) if altitudes else None,
        started_at=started_at,
    )


def _iter_track_points(parsed: tuple[ParsedTrack, ...]) -> Iterable[TrackPoint]:
    for track in parsed:
        yield from track.points


def _apply_gpx_source_metadata(source: SourceFile, parsed: tuple[ParsedTrack, ...]) -> None:
    summary = summarize_parsed_tracks(parsed)
    _apply_gpx_position(source, summary)
    _apply_gpx_time(source, summary)


def _apply_gpx_position(source: SourceFile, summary: GpxSourceSummary) -> None:
    if source.position_source in PROTECTED_SOURCES:
        return
    if summary.latitude is None or summary.longitude is None:
        if source.position_source == SOURCE_TRACK:
            source.gps_latitude = None
            source.gps_longitude = None
            source.gps_altitude = None
            source.position_source = None
            source.position_confidence = None
            source.position_time_delta_seconds = None
        return
    source.gps_latitude = summary.latitude
    source.gps_longitude = summary.longitude
    source.gps_altitude = summary.altitude
    source.position_source = SOURCE_TRACK
    source.position_confidence = TRACK_POSITION_CONFIDENCE
    source.position_time_delta_seconds = None


def _apply_gpx_time(source: SourceFile, summary: GpxSourceSummary) -> None:
    if source.captured_at_source not in {None, SOURCE_TRACK}:
        return
    if summary.started_at is None:
        if source.captured_at_source == SOURCE_TRACK:
            source.captured_at = None
            source.captured_at_raw = None
            source.captured_at_source = None
            source.timezone_name = None
            source.timezone_unknown = True
        return
    started = summary.started_at
    source.captured_at = started
    source.captured_at_raw = started.isoformat()
    source.captured_at_source = SOURCE_TRACK
    source.timezone_unknown = started.tzinfo is None
    offset = started.utcoffset() if started.tzinfo is not None else None
    source.timezone_name = "UTC" if offset is not None and offset.total_seconds() == 0 else None


def _load_timed_points(session: Session, project_id: int) -> list[TrackPoint]:
    rows = session.execute(
        select(GpsPoint, GpsTrack.id)
        .join(GpsTrack, GpsPoint.track_id == GpsTrack.id)
        .where(GpsTrack.project_id == project_id, GpsPoint.recorded_at.is_not(None))
        .order_by(GpsPoint.recorded_at.asc(), GpsPoint.sequence_index.asc())
    )
    points: list[TrackPoint] = []
    for point, track_pk in rows:
        points.append(
            TrackPoint(
                latitude=point.latitude,
                longitude=point.longitude,
                altitude=point.altitude,
                recorded_at=point.recorded_at,
                track_id=str(track_pk),
                segment_id=point.segment_id,
                sequence_index=point.sequence_index,
            )
        )
    return points
