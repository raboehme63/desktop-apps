"""Apply MediaMetadata onto a SourceFile row. Original files are not written."""

from __future__ import annotations

from pathlib import Path

from travelcore.database.models import SourceFile
from travelcore.metadata.gps import HEADING_SOURCE_ABSENT
from travelcore.metadata.provider import CapturedTime, MediaMetadata, MetadataProvider
from travelcore.metadata.time import filesystem_captured_time


def apply_metadata(
    row: SourceFile,
    path: Path,
    provider: MetadataProvider | None = None,
    *,
    metadata: MediaMetadata | None = None,
    allow_filesystem_fallback: bool = True,
    filesystem_fallback: CapturedTime | None = None,
) -> None:
    """Fill capture time, GPS and camera fields from a provider or DTO.

    Missing EXIF does not raise. The caller should catch provider failures so a
    single defective file cannot abort an import.
    """

    if metadata is None:
        if provider is None:
            raise TypeError("apply_metadata requires metadata or a provider.")
        metadata = provider.read(path)
    if row.captured_at is None:
        _apply_captured(
            row,
            path,
            metadata,
            allow_filesystem_fallback,
            filesystem_fallback=filesystem_fallback,
        )
    elif row.captured_at_source == "filesystem_mtime" and metadata.captured is not None:
        _apply_captured(row, path, metadata, allow_filesystem_fallback=False)
    if row.gps_latitude is None:
        _apply_position(row, metadata)
    _apply_camera(row, metadata)


def _apply_captured(
    row: SourceFile,
    path: Path,
    metadata: MediaMetadata,
    allow_filesystem_fallback: bool,
    filesystem_fallback: CapturedTime | None = None,
) -> None:
    captured = metadata.captured
    if (captured is None or captured.normalized is None) and allow_filesystem_fallback:
        captured = filesystem_fallback or filesystem_captured_time(path)
    if captured is None or captured.normalized is None:
        return
    row.captured_at_raw = captured.raw_value
    row.captured_at = captured.normalized
    row.captured_at_source = captured.source or None
    row.timezone_name = captured.timezone_name
    row.timezone_unknown = captured.timezone_unknown


def _apply_position(row: SourceFile, metadata: MediaMetadata) -> None:
    position = metadata.position
    if position is None:
        return
    row.gps_latitude = position.latitude
    row.gps_longitude = position.longitude
    row.gps_altitude = position.altitude
    row.position_source = position.source
    row.position_confidence = position.confidence
    row.position_time_delta_seconds = position.time_delta_seconds


def _apply_camera(row: SourceFile, metadata: MediaMetadata) -> None:
    if metadata.camera:
        row.camera = metadata.camera
    if metadata.lens:
        row.lens = metadata.lens
    if metadata.focal_length is not None:
        row.focal_length = metadata.focal_length
    if metadata.focal_length_35mm is not None and row.focal_length_35mm is None:
        row.focal_length_35mm = metadata.focal_length_35mm
    if metadata.iso is not None:
        row.iso = metadata.iso
    if metadata.exposure_time:
        row.exposure_time = metadata.exposure_time
    if metadata.aperture:
        row.aperture = metadata.aperture
    if metadata.orientation is not None:
        row.orientation = metadata.orientation
    if metadata.width is not None:
        row.width = metadata.width
    if metadata.height is not None:
        row.height = metadata.height
    _apply_heading(row, metadata)


def _apply_heading(row: SourceFile, metadata: MediaMetadata) -> None:
    if metadata.heading_degrees is not None:
        if row.heading_degrees is None:
            row.heading_degrees = metadata.heading_degrees
            row.heading_ref = metadata.heading_ref
            row.heading_source = metadata.heading_source
        return
    if row.heading_source is None:
        row.heading_source = HEADING_SOURCE_ABSENT
