"""Parse EXIF TIFF blobs embedded in JPEG APP1 or HEIC Exif items.

Original files are only read. This avoids Pillow/libheif for container formats.
"""

from __future__ import annotations

from typing import Any

from travelcore.metadata.gps import position_from_exif
from travelcore.metadata.provider import MediaMetadata
from travelcore.metadata.time import choose_captured_time, parse_exif_datetime, with_source

_EXIF_PREFIX = b"Exif\x00\x00"
_TAG_MAKE = 0x010F
_TAG_MODEL = 0x0110
_TAG_ORIENTATION = 0x0112
_TAG_DATETIME = 0x0132
_TAG_EXIF_IFD = 0x8769
_TAG_GPS_IFD = 0x8825
_TAG_DATETIME_ORIGINAL = 0x9003
_TAG_DATETIME_DIGITIZED = 0x9004
_TAG_OFFSET_ORIGINAL = 0x9011
_TAG_OFFSET_DIGITIZED = 0x9012
_TAG_PIXEL_X = 0xA002
_TAG_PIXEL_Y = 0xA003
_GPS_LAT_REF = 1
_GPS_LAT = 2
_GPS_LON_REF = 3
_GPS_LON = 4
_GPS_ALT_REF = 5
_GPS_ALT = 6

_TYPE_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 9: 4, 10: 8}


def parse_embedded_exif(data: bytes) -> MediaMetadata | None:
    """Find and parse the first valid EXIF TIFF in ``data``."""

    start = 0
    while True:
        idx = data.find(_EXIF_PREFIX, start)
        if idx < 0:
            break
        metadata = parse_tiff_exif(data[idx + 6 :])
        if metadata is not None and _has_useful_fields(metadata):
            return metadata
        start = idx + 4
    for magic in (b"II*\x00", b"MM\x00*"):
        start = 0
        while True:
            idx = data.find(magic, start)
            if idx < 0:
                break
            metadata = parse_tiff_exif(data[idx:])
            if metadata is not None and _has_useful_fields(metadata):
                return metadata
            start = idx + 2
    return None


def parse_tiff_exif(tiff: bytes) -> MediaMetadata | None:
    """Parse a TIFF-encoded EXIF structure starting at offset 0."""

    if len(tiff) < 8:
        return None
    if tiff[:2] == b"II":
        little = True
    elif tiff[:2] == b"MM":
        little = False
    else:
        return None
    try:
        if _u16(tiff, 2, little) != 42:
            return None
        ifd0 = _read_ifd(tiff, _u32(tiff, 4, little), little)
        if not ifd0:
            return None
        exif_ifd = _read_ifd(tiff, _as_int(ifd0.get(_TAG_EXIF_IFD)), little) if _TAG_EXIF_IFD in ifd0 else {}
        gps_ifd = _read_ifd(tiff, _as_int(ifd0.get(_TAG_GPS_IFD)), little) if _TAG_GPS_IFD in ifd0 else {}
    except ValueError:
        return None

    original = parse_exif_datetime(
        _as_text(exif_ifd.get(_TAG_DATETIME_ORIGINAL) or ifd0.get(_TAG_DATETIME_ORIGINAL)),
        offset=_as_text(exif_ifd.get(_TAG_OFFSET_ORIGINAL)),
    )
    created = parse_exif_datetime(
        _as_text(exif_ifd.get(_TAG_DATETIME_DIGITIZED) or ifd0.get(_TAG_DATETIME)),
        offset=_as_text(exif_ifd.get(_TAG_OFFSET_DIGITIZED)),
    )
    captured = choose_captured_time(
        {
            "exif_datetime_original": with_source(original, "exif_datetime_original") if original else None,
            "exif_create_date": with_source(created, "exif_create_date") if created else None,
        }
    )
    position = None
    if _GPS_LAT in gps_ifd and _GPS_LON in gps_ifd:
        position = position_from_exif(
            latitude=gps_ifd.get(_GPS_LAT),
            latitude_ref=_as_text(gps_ifd.get(_GPS_LAT_REF)),
            longitude=gps_ifd.get(_GPS_LON),
            longitude_ref=_as_text(gps_ifd.get(_GPS_LON_REF)),
            altitude=gps_ifd.get(_GPS_ALT),
            altitude_ref=gps_ifd.get(_GPS_ALT_REF),
        )
    camera = _camera_name(_as_text(ifd0.get(_TAG_MAKE)), _as_text(ifd0.get(_TAG_MODEL)))
    return MediaMetadata(
        captured=captured,
        position=position,
        camera=camera,
        orientation=_as_int(ifd0.get(_TAG_ORIENTATION)),
        width=_as_int(exif_ifd.get(_TAG_PIXEL_X)),
        height=_as_int(exif_ifd.get(_TAG_PIXEL_Y)),
    )


def _camera_name(make: str | None, model: str | None) -> str | None:
    make = _plausible_name(make)
    model = _plausible_name(model)
    if make and model:
        return model if model.lower().startswith(make.lower()) else f"{make} {model}"
    return model or make


def _plausible_name(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if not 2 <= len(text) <= 80:
        return None
    if not all(32 <= ord(char) < 127 for char in text):
        return None
    if sum(char.isalpha() for char in text) < 2:
        return None
    return text


def _has_useful_fields(metadata: MediaMetadata) -> bool:
    return bool(
        metadata.camera
        or metadata.position is not None
        or (metadata.captured is not None and metadata.captured.normalized is not None)
    )


def _read_ifd(data: bytes, offset: int | None, little: bool) -> dict[int, Any]:
    if offset is None or offset < 8 or offset + 2 > len(data):
        return {}
    count = _u16(data, offset, little)
    if count <= 0 or count > 64:
        return {}
    entries: dict[int, Any] = {}
    cursor = offset + 2
    for _ in range(count):
        if cursor + 12 > len(data):
            break
        tag = _u16(data, cursor, little)
        typ = _u16(data, cursor + 2, little)
        number = _u32(data, cursor + 4, little)
        value_off = cursor + 8
        size = _TYPE_SIZE.get(typ, 1) * number
        if size > 4:
            ptr = _u32(data, value_off, little)
            blob = data[ptr : ptr + size] if 0 <= ptr <= len(data) else b""
        else:
            blob = data[value_off : value_off + max(size, 4)]
        parsed = _parse_value(typ, number, blob, little)
        if parsed is not None:
            entries[tag] = parsed
        cursor += 12
    return entries


def _parse_value(typ: int, count: int, blob: bytes, little: bool) -> object | None:
    if not blob:
        return None
    if typ == 2:
        text = blob.split(b"\x00", 1)[0].decode("utf-8", errors="replace").strip()
        return text or None
    if typ in {1, 7} and count == 1:
        return blob[0]
    if typ in {3, 4}:
        width = 2 if typ == 3 else 4
        values = []
        for index in range(count):
            start = index * width
            if start + width > len(blob):
                break
            values.append(_u16(blob, start, little) if width == 2 else _u32(blob, start, little))
        if not values:
            return None
        return values[0] if count == 1 else values
    if typ == 5:
        rationals = []
        for index in range(count):
            start = index * 8
            if start + 8 > len(blob):
                break
            num = _u32(blob, start, little)
            den = _u32(blob, start + 4, little)
            rationals.append((num, den) if den else (0, 1))
        if len(rationals) == 1:
            return rationals[0]
        return rationals or None
    return None


def _u16(data: bytes, offset: int, little: bool) -> int:
    if offset + 2 > len(data):
        raise ValueError("truncated u16")
    return int.from_bytes(data[offset : offset + 2], "little" if little else "big")


def _u32(data: bytes, offset: int, little: bool) -> int:
    if offset + 4 > len(data):
        raise ValueError("truncated u32")
    return int.from_bytes(data[offset : offset + 4], "little" if little else "big")


def _as_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray)):
        text = bytes(value).split(b"\x00", 1)[0].decode("utf-8", errors="replace").strip()
        return text or None
    text = str(value).strip("\x00 ").strip()
    return text or None


def _as_int(value: object) -> int | None:
    if value is None or isinstance(value, (bytes, bytearray, str)):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, (tuple, list)) and value and isinstance(value[0], int):
        return int(value[0])
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
