"""Supported source file types and MIME mapping.

Classification uses the file extension only. Content inspection happens later
in metadata and analysis modules.
"""

from __future__ import annotations

import mimetypes
from enum import StrEnum
from pathlib import Path

_mimetypes_initialized = False


class FileKind(StrEnum):
    PHOTO = "photo"
    VIDEO = "video"
    GPS = "gps"
    TEXT = "text"


PHOTO_EXTENSIONS = frozenset(
    {
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
        ".tif",
        ".tiff",
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
)

VIDEO_EXTENSIONS = frozenset({".mp4", ".mov", ".avi", ".mkv"})
GPS_EXTENSIONS = frozenset({".gpx", ".kml", ".geojson"})
TEXT_EXTENSIONS = frozenset({".txt", ".md", ".markdown", ".json"})

_KIND_BY_EXTENSION: dict[str, FileKind] = {}
_KIND_BY_EXTENSION.update(dict.fromkeys(PHOTO_EXTENSIONS, FileKind.PHOTO))
_KIND_BY_EXTENSION.update(dict.fromkeys(VIDEO_EXTENSIONS, FileKind.VIDEO))
_KIND_BY_EXTENSION.update(dict.fromkeys(GPS_EXTENSIONS, FileKind.GPS))
_KIND_BY_EXTENSION.update(dict.fromkeys(TEXT_EXTENSIONS, FileKind.TEXT))

_EXTRA_MIME = {
    ".heic": "image/heic",
    ".heif": "image/heif",
    ".cr2": "image/x-canon-cr2",
    ".cr3": "image/x-canon-cr3",
    ".nef": "image/x-nikon-nef",
    ".arw": "image/x-sony-arw",
    ".dng": "image/x-adobe-dng",
    ".raf": "image/x-fuji-raf",
    ".orf": "image/x-olympus-orf",
    ".rw2": "image/x-panasonic-rw2",
    ".gpx": "application/gpx+xml",
    ".kml": "application/vnd.google-earth.kml+xml",
    ".geojson": "application/geo+json",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
}


def _ensure_mimetypes() -> None:
    global _mimetypes_initialized
    if _mimetypes_initialized:
        return
    mimetypes.init()
    _mimetypes_initialized = True


def classify_path(path: Path) -> FileKind | None:
    """Return the logical kind for a supported path, or None if unsupported."""

    return _KIND_BY_EXTENSION.get(path.suffix.lower())


def mime_for_path(path: Path) -> str | None:
    """Return a MIME type for the path, preferring explicit travel-media mappings."""

    suffix = path.suffix.lower()
    if suffix in _EXTRA_MIME:
        return _EXTRA_MIME[suffix]
    _ensure_mimetypes()
    guessed, _encoding = mimetypes.guess_type(str(path))
    return guessed


def is_supported(path: Path) -> bool:
    return classify_path(path) is not None
