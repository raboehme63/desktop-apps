"""Shared GPS value objects."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class TrackPoint:
    latitude: float
    longitude: float
    altitude: float | None
    recorded_at: datetime | None
    track_id: str
    segment_id: int
    sequence_index: int


@dataclass(frozen=True, slots=True)
class GpsFix:
    latitude: float
    longitude: float
    altitude: float | None
    source: str
    confidence: float
    time_delta_seconds: float | None
    from_exif: bool
