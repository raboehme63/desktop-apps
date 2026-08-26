"""Provider protocol for EXIF, XMP, IPTC, and video metadata.

Concrete adapters (Pillow, ExifTool, ffprobe) live in later phases. Callers
must never invoke ExifTool or FFmpeg directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class CapturedTime:
    """Normalized capture time plus the original raw value.

    If the source does not include a timezone, ``timezone_unknown`` stays True.
    The library never claims UTC in that case.
    """

    raw_value: str | None
    normalized: datetime | None
    timezone_name: str | None
    timezone_unknown: bool
    source: str


@dataclass(frozen=True, slots=True)
class GeoPosition:
    latitude: float
    longitude: float
    altitude: float | None
    source: str
    confidence: float
    time_delta_seconds: float | None


@dataclass(frozen=True, slots=True)
class MediaMetadata:
    captured: CapturedTime | None
    position: GeoPosition | None
    camera: str | None = None
    lens: str | None = None
    focal_length: float | None = None
    focal_length_35mm: float | None = None
    iso: int | None = None
    exposure_time: str | None = None
    aperture: str | None = None
    orientation: int | None = None
    width: int | None = None
    height: int | None = None
    heading_degrees: float | None = None
    heading_ref: str | None = None
    heading_source: str | None = None


@runtime_checkable
class MetadataProvider(Protocol):
    """Read-only metadata access for a single media file."""

    def read(self, path: Path) -> MediaMetadata:
        """Return metadata without modifying the original file."""
        ...


TIME_SOURCE_PRIORITY = (
    "exif_datetime_original",
    "exif_create_date",
    "xmp_create_date",
    "video_creation_time",
    "filesystem_mtime",
)
