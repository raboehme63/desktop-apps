"""Read GPS and camera from HEIC/HEIF without ExifTool.

iPhone HEIC files store location either as ISO 6709 in
``com.apple.quicktime.location.ISO6709`` or in an embedded EXIF TIFF.
Camera make/model is in that EXIF blob or in QuickTime ``data`` boxes.
Pillow cannot open HEIC here, so we scan the container bytes read-only.
"""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

from travelcore.metadata.exif_blob import parse_embedded_exif
from travelcore.metadata.gps import position_from_coordinates_text
from travelcore.metadata.provider import GeoPosition, MediaMetadata

_HEIC_SUFFIXES = {".heic", ".heif"}
_MAX_READ_BYTES = 128 * 1024 * 1024
_ISO6709_IN_FILE = re.compile(rb"([+-]\d+(?:\.\d+)?)([+-]\d+(?:\.\d+)?)([+-]\d+(?:\.\d+)?)?/")
_APPLE_LOCATION_KEY = b"com.apple.quicktime.location.ISO6709"
_UTF8_DATA = b"data\x00\x00\x00\x01\x00\x00\x00\x00"
_KNOWN_MAKES = {
    "apple",
    "samsung",
    "google",
    "huawei",
    "xiaomi",
    "sony",
    "canon",
    "nikon",
    "fujifilm",
    "olympus",
    "leica",
    "dji",
    "oneplus",
    "motorola",
}


def read_heic_container_metadata(path: Path) -> MediaMetadata | None:
    """Return GPS, camera and EXIF time from a HEIC/HEIF container, if present."""

    if path.suffix.lower() not in _HEIC_SUFFIXES:
        return None
    data = _read_container_bytes(path)
    if not data:
        return None
    result = parse_embedded_exif(data) or MediaMetadata(captured=None, position=None)
    if result.position is None:
        position = _position_from_heic_bytes(data)
        if position is not None:
            result = replace(result, position=position)
    if not result.camera:
        camera = _camera_from_quicktime_data(data)
        if camera:
            result = replace(result, camera=camera)
    if not _has_useful_fields(result):
        return None
    return result


def read_heic_quicktime_location(path: Path) -> MediaMetadata | None:
    """Compatibility wrapper: same as :func:`read_heic_container_metadata`."""

    return read_heic_container_metadata(path)


def _read_container_bytes(path: Path) -> bytes:
    try:
        size = path.stat().st_size
        if size <= _MAX_READ_BYTES:
            return path.read_bytes()
        # Meta boxes in HEIC can sit after mdat; keep head and tail.
        half = _MAX_READ_BYTES // 2
        with path.open("rb") as handle:
            head = handle.read(half)
            handle.seek(max(0, size - half))
            tail = handle.read(half)
        return head + tail
    except OSError:
        return b""


def _position_from_heic_bytes(data: bytes) -> GeoPosition | None:
    start = 0
    if _APPLE_LOCATION_KEY in data:
        start = data.find(_APPLE_LOCATION_KEY)
    window = data[start : start + 8192] if start else data
    match = _ISO6709_IN_FILE.search(window) or _ISO6709_IN_FILE.search(data)
    if match is None:
        return None
    text = match.group(0).decode("ascii", errors="ignore")
    return position_from_coordinates_text(text, source="quicktime")


def _camera_from_quicktime_data(data: bytes) -> str | None:
    strings: list[str] = []
    start = 0
    while True:
        idx = data.find(_UTF8_DATA, start)
        if idx < 0:
            break
        payload_start = idx + len(_UTF8_DATA)
        payload = b""
        if idx >= 4:
            size = int.from_bytes(data[idx - 4 : idx], "big")
            if 16 <= size <= 256:
                payload = data[payload_start : idx - 4 + size]
        if not payload:
            end = data.find(b"\x00", payload_start, payload_start + 80)
            payload = data[payload_start : end if end >= 0 else payload_start + 80]
        text = payload.decode("utf-8", errors="ignore").strip("\x00 ").strip()
        if 2 <= len(text) <= 64 and all(32 <= ord(char) < 127 for char in text):
            strings.append(text)
        start = idx + 4
    make = next((item for item in strings if item.lower() in _KNOWN_MAKES), None)
    model = next(
        (
            item
            for item in strings
            if item.lower().startswith(("iphone", "ipad", "pixel", "galaxy", "sm-"))
            or "iphone" in item.lower()
        ),
        None,
    )
    if make and model:
        return model if model.lower().startswith(make.lower()) else f"{make} {model}"
    return model or (make.title() if make else None)


def _has_useful_fields(metadata: MediaMetadata) -> bool:
    return bool(
        metadata.camera
        or metadata.position is not None
        or (metadata.captured is not None and metadata.captured.normalized is not None)
    )
