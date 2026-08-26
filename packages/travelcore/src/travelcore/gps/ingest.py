"""Persist GPX tracks and fill media positions from the track timeline."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from travelcore.database.models import FileError, GpsPoint, GpsTrack, Project, SourceFile
from travelcore.exceptions import GpsError
from travelcore.gps.igc import parse_igc
from travelcore.gps.match import (
    DERIVED_SOURCES,
    PROTECTED_SOURCES,
    SOURCE_IGC_INTERPOLATED,
    SOURCE_IGC_NEAREST,
    SOURCE_INTERPOLATED,
    SOURCE_NEAREST,
    SOURCE_PHOTO_INTERPOLATED,
    SOURCE_PHOTO_NEAREST,
    match_position,
    media_time_utc,
)
from travelcore.gps.parse import ParsedTrack, parse_gpx
from travelcore.gps.types import GpsFix, TrackPoint

logger = logging.getLogger(__name__)

ProgressFn = Callable[[int, int, str, str], None]

SOURCE_TRACK = "gpx_track"
SOURCE_IGC_TRACK = "igc_track"
_TRACK_POSITION_SOURCES = {SOURCE_TRACK, SOURCE_IGC_TRACK}
_TRACK_SUFFIXES = {".gpx": parse_gpx, ".igc": parse_igc}
REPRESENTATIVE_POINT_LIMIT = 20
TRACK_POSITION_CONFIDENCE = 0.9


@dataclass(slots=True)
class GpsIngestResult:
    tracks: int = 0
    points: int = 0
    matched: int = 0
    errors: int = 0
    skipped: int = 0


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
    skip_unchanged_ids: set[int] | frozenset[int] | None = None,
) -> GpsIngestResult:
    """Parse GPX and IGC source files, store points, and match media without EXIF GPS.

    Photos and videos without a protected position are filled in this order:
    nearby geotagged photos, then GPX, then IGC.

    Unchanged source files that already have stored points are not parsed again.
    """

    result = GpsIngestResult()
    skip_ids = skip_unchanged_ids or frozenset()
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
        skip_this = row.id in skip_ids and _source_has_stored_points(session, row.id)
        if progress is not None:
            progress(index, total, row.path, "skip" if skip_this else "track")
        if skip_this:
            result.skipped += 1
            continue
        suffix = Path(row.path).suffix.lower()
        parser = _TRACK_SUFFIXES.get(suffix)
        if parser is None:
            continue
        try:
            parsed = parser(Path(row.path))
        except GpsError as exc:
            stage = "igc" if suffix == ".igc" else "gpx"
            logger.warning("%s parse failed for %s: %s", stage.upper(), row.path, exc)
            session.add(
                FileError(
                    project_id=project.id,
                    path=row.path,
                    stage=stage,
                    message=str(exc),
                )
            )
            result.errors += 1
            continue
        stored = _replace_tracks(session, project, row, parsed)
        result.tracks += stored[0]
        result.points += stored[1]

    session.flush()
    media_rows = list(
        session.scalars(
            select(SourceFile).where(
                SourceFile.project_id == project.id,
                SourceFile.file_kind.in_(("photo", "video")),
            )
        )
    )
    photo_points = _sorted_points(_photo_reference_points(media_rows, project))
    gpx_points = _load_timed_points(session, project.id, track_format="gpx")
    igc_points = _load_timed_points(session, project.id, track_format="igc")
    if not photo_points and not gpx_points and not igc_points:
        return result
    media_total = max(len(media_rows), 1)
    for index, row in enumerate(media_rows, start=1):
        if progress is not None:
            progress(index, media_total, row.path, "match")
        if not _should_match(row) or row.captured_at is None:
            continue
        fix = _match_media_position(
            row,
            project,
            photo_points,
            gpx_points,
            igc_points,
            max_delta_seconds=float(max_delta_seconds),
        )
        if fix is None:
            continue
        _apply_fix(row, fix)
        result.matched += 1
    if progress is not None:
        progress(media_total, media_total, "", "done")
    return result


def _should_match(row: SourceFile) -> bool:
    if row.captured_at is None:
        return False
    if row.gps_latitude is None:
        return True
    return row.position_source in DERIVED_SOURCES


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
    existing = list(session.scalars(select(GpsTrack).where(GpsTrack.source_file_id == source.id)))
    kept_url = next((row.external_url for row in existing if row.external_url), None)
    existing_ids = [row.id for row in existing]
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
            track_format=item.format,
            pilot=item.pilot,
            external_url=kept_url,
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
    _apply_track_source_metadata(source, parsed)
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


def _apply_track_source_metadata(source: SourceFile, parsed: tuple[ParsedTrack, ...]) -> None:
    summary = summarize_parsed_tracks(parsed)
    fmt = parsed[0].format if parsed else "gpx"
    label = SOURCE_IGC_TRACK if fmt == "igc" else SOURCE_TRACK
    _apply_gpx_position(source, summary, label=label)
    _apply_gpx_time(source, summary, label=label)
    if fmt == "igc":
        source.camera = next((item.pilot for item in parsed if item.pilot), None)


def _apply_gpx_source_metadata(source: SourceFile, parsed: tuple[ParsedTrack, ...]) -> None:
    _apply_track_source_metadata(source, parsed)


def _apply_gpx_position(source: SourceFile, summary: GpxSourceSummary, *, label: str = SOURCE_TRACK) -> None:
    if source.position_source in PROTECTED_SOURCES:
        return
    if summary.latitude is None or summary.longitude is None:
        if source.position_source in _TRACK_POSITION_SOURCES:
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
    source.position_source = label
    source.position_confidence = TRACK_POSITION_CONFIDENCE
    source.position_time_delta_seconds = None


def _apply_gpx_time(source: SourceFile, summary: GpxSourceSummary, *, label: str = SOURCE_TRACK) -> None:
    if source.captured_at_source not in {None, *_TRACK_POSITION_SOURCES}:
        return
    if summary.started_at is None:
        if source.captured_at_source in _TRACK_POSITION_SOURCES:
            source.captured_at = None
            source.captured_at_raw = None
            source.captured_at_source = None
            source.timezone_name = None
            source.timezone_unknown = True
        return
    started = summary.started_at
    source.captured_at = started
    source.captured_at_raw = started.isoformat()
    source.captured_at_source = label
    source.timezone_unknown = started.tzinfo is None
    offset = started.utcoffset() if started.tzinfo is not None else None
    source.timezone_name = "UTC" if offset is not None and offset.total_seconds() == 0 else None


def track_urls_by_source(session: Session, project_id: int) -> dict[int, str]:
    """Return DHV-Leonardo (or other) URLs keyed by source_file_id."""

    rows = session.scalars(select(GpsTrack).where(GpsTrack.project_id == project_id))
    mapping: dict[int, str] = {}
    for track in rows:
        if track.source_file_id is None or not track.external_url:
            continue
        mapping[track.source_file_id] = track.external_url
    return mapping


def set_track_external_url(session: Session, source_file_id: int, url: str | None) -> None:
    """Store a DHV-Leonardo link on all tracks of one source file."""

    normalized = _normalize_external_url(url)
    tracks = list(session.scalars(select(GpsTrack).where(GpsTrack.source_file_id == source_file_id)))
    for track in tracks:
        track.external_url = normalized


def _normalize_external_url(value: str | None) -> str | None:
    text = (value or "").strip()
    if not text:
        return None
    if not (text.startswith("https://") or text.startswith("http://")):
        raise ValueError("Der DHV-Leonardo-Link muss mit http:// oder https:// beginnen.")
    return text


def _source_has_stored_points(session: Session, source_file_id: int) -> bool:
    return (
        session.scalar(
            select(GpsPoint.id)
            .join(GpsTrack, GpsPoint.track_id == GpsTrack.id)
            .where(GpsTrack.source_file_id == source_file_id)
            .limit(1)
        )
        is not None
    )


def _load_timed_points(session: Session, project_id: int, *, track_format: str) -> list[TrackPoint]:
    rows = session.execute(
        select(GpsPoint, GpsTrack.id)
        .join(GpsTrack, GpsPoint.track_id == GpsTrack.id)
        .where(
            GpsTrack.project_id == project_id,
            GpsTrack.track_format == track_format,
            GpsPoint.recorded_at.is_not(None),
        )
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


def _photo_reference_points(rows: list[SourceFile], project: Project) -> list[TrackPoint]:
    points: list[TrackPoint] = []
    for row in rows:
        if row.file_kind != "photo":
            continue
        if row.id is None or row.captured_at is None:
            continue
        if row.gps_latitude is None or row.gps_longitude is None:
            continue
        if row.position_source not in PROTECTED_SOURCES:
            continue
        recorded = media_time_utc(
            row.captured_at,
            timezone_name=row.timezone_name,
            timezone_unknown=row.timezone_unknown,
            default_timezone=project.default_timezone,
        )
        points.append(
            TrackPoint(
                latitude=row.gps_latitude,
                longitude=row.gps_longitude,
                altitude=row.gps_altitude,
                recorded_at=recorded,
                track_id=str(row.id),
                segment_id=0,
                sequence_index=row.id,
            )
        )
    return points


def _sorted_points(points: list[TrackPoint]) -> list[TrackPoint]:
    timed = [point for point in points if point.recorded_at is not None]
    timed.sort(key=lambda item: _aware_time(item.recorded_at))
    return timed


def _aware_time(value: datetime | None) -> datetime:
    if value is None:
        return datetime.min.replace(tzinfo=UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _match_media_position(
    row: SourceFile,
    project: Project,
    photo_points: list[TrackPoint],
    gpx_points: list[TrackPoint],
    igc_points: list[TrackPoint],
    *,
    max_delta_seconds: float,
) -> GpsFix | None:
    if row.captured_at is None:
        return None
    moment = media_time_utc(
        row.captured_at,
        timezone_name=row.timezone_name,
        timezone_unknown=row.timezone_unknown,
        default_timezone=project.default_timezone,
    )
    # Photos without a protected EXIF/QuickTime fix are not in ``photo_points``.
    fix = match_position(
        moment,
        photo_points,
        max_delta_seconds=max_delta_seconds,
        source_interpolated=SOURCE_PHOTO_INTERPOLATED,
        source_nearest=SOURCE_PHOTO_NEAREST,
        points_sorted=True,
    )
    if fix is not None:
        return fix
    fix = match_position(
        moment,
        gpx_points,
        max_delta_seconds=max_delta_seconds,
        source_interpolated=SOURCE_INTERPOLATED,
        source_nearest=SOURCE_NEAREST,
        points_sorted=True,
    )
    if fix is not None:
        return fix
    return match_position(
        moment,
        igc_points,
        max_delta_seconds=max_delta_seconds,
        source_interpolated=SOURCE_IGC_INTERPOLATED,
        source_nearest=SOURCE_IGC_NEAREST,
        points_sorted=True,
    )
