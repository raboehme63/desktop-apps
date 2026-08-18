"""Metadata extraction behind a swappable provider interface."""

from travelcore.metadata.composite import DefaultMetadataProvider
from travelcore.metadata.exiftool_provider import ExifToolMetadataProvider
from travelcore.metadata.pillow_provider import PillowMetadataProvider
from travelcore.metadata.provider import (
    TIME_SOURCE_PRIORITY,
    CapturedTime,
    GeoPosition,
    MediaMetadata,
    MetadataProvider,
)

__all__ = [
    "TIME_SOURCE_PRIORITY",
    "CapturedTime",
    "DefaultMetadataProvider",
    "ExifToolMetadataProvider",
    "GeoPosition",
    "MediaMetadata",
    "MetadataProvider",
    "PillowMetadataProvider",
]
