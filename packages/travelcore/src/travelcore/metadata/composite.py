"""Default MetadataProvider: Pillow first, then ExifTool / HEIC container metadata."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import replace
from pathlib import Path

from travelcore.exceptions import MetadataError
from travelcore.metadata.exiftool_provider import ExifToolMetadataProvider
from travelcore.metadata.heic import read_heic_container_metadata
from travelcore.metadata.pillow_provider import PillowMetadataProvider
from travelcore.metadata.provider import MediaMetadata, MetadataProvider

_EXIFTOOL_FORMATS = {
    ".heic",
    ".heif",
    ".cr2",
    ".cr3",
    ".nef",
    ".arw",
    ".dng",
    ".raf",
    ".orf",
    ".rw2",
}


class DefaultMetadataProvider:
    """Compose adapters without leaking ExifTool or Pillow into callers."""

    def __init__(
        self,
        *,
        pillow: MetadataProvider | None = None,
        exiftool: MetadataProvider | None = None,
    ) -> None:
        self._pillow = pillow or PillowMetadataProvider()
        self._exiftool = exiftool

    @classmethod
    def from_environment(cls) -> DefaultMetadataProvider:
        return cls(exiftool=ExifToolMetadataProvider.from_environment())

    def read(self, path: Path) -> MediaMetadata:
        result = self._pillow.read(path)
        suffix = path.suffix.lower()
        if self._exiftool is not None and (not _is_complete(result) or suffix in _EXIFTOOL_FORMATS):
            with suppress(MetadataError):
                result = merge_metadata(result, self._exiftool.read(path))
        if suffix in {".heic", ".heif"}:
            embedded = read_heic_container_metadata(path)
            if embedded is not None:
                result = merge_metadata(result, embedded)
        return result

    def close(self) -> None:
        closer = getattr(self._exiftool, "close", None)
        if callable(closer):
            closer()


def _is_complete(metadata: MediaMetadata) -> bool:
    has_time = metadata.captured is not None and metadata.captured.normalized is not None
    has_size = metadata.width is not None and metadata.height is not None
    return has_time and has_size


def merge_metadata(primary: MediaMetadata, extra: MediaMetadata) -> MediaMetadata:
    """Keep primary fields; fill only missing values from ``extra``."""

    captured = primary.captured
    if captured is None or captured.normalized is None:
        captured = extra.captured
    position = primary.position or extra.position
    return replace(
        primary,
        captured=captured,
        position=position,
        camera=primary.camera or extra.camera,
        lens=primary.lens or extra.lens,
        focal_length=primary.focal_length if primary.focal_length is not None else extra.focal_length,
        iso=primary.iso if primary.iso is not None else extra.iso,
        exposure_time=primary.exposure_time or extra.exposure_time,
        aperture=primary.aperture or extra.aperture,
        orientation=primary.orientation if primary.orientation is not None else extra.orientation,
        width=primary.width if primary.width is not None else extra.width,
        height=primary.height if primary.height is not None else extra.height,
    )
