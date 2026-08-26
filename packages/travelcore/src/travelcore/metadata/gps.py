"""Convert EXIF GPS structures and QuickTime coordinate strings to decimal degrees."""

from __future__ import annotations

import math
import re
from collections.abc import Sequence

from travelcore.metadata.provider import GeoPosition

HEADING_SOURCE_IMG = "gps_img_direction"
HEADING_SOURCE_DEST = "gps_dest_bearing"
HEADING_SOURCE_ABSENT = "absent"

_GPS_SOURCE_EXIF = "exif"
_GPS_SOURCE_QUICKTIME = "quicktime"

_ISO6709 = re.compile(r"(?P<lat>[+-]\d+(?:\.\d+)?)(?P<lon>[+-]\d+(?:\.\d+)?)(?P<alt>[+-]\d+(?:\.\d+)?)?/")
_DECIMAL_PAIR = re.compile(
    r"(?P<lat>[+-]?\d+(?:\.\d+)?)\s*[, ]\s*(?P<lon>[+-]?\d+(?:\.\d+)?)"
    r"(?:\s*[, ]\s*(?P<alt>[+-]?\d+(?:\.\d+)?))?"
)
_DMS_PAIR = re.compile(
    r"(?P<lat_d>\d+(?:\.\d+)?)\s*deg\s*(?P<lat_m>\d+(?:\.\d+)?)'\s*"
    r'(?P<lat_s>\d+(?:\.\d+)?)"?\s*(?P<lat_ref>[NS])\s*,\s*'
    r"(?P<lon_d>\d+(?:\.\d+)?)\s*deg\s*(?P<lon_m>\d+(?:\.\d+)?)'\s*"
    r'(?P<lon_s>\d+(?:\.\d+)?)"?\s*(?P<lon_ref>[EW])',
    re.IGNORECASE,
)


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return float(value[0]) if value else None
    if hasattr(value, "numerator") and hasattr(value, "denominator"):
        denominator = float(value.denominator)
        if denominator == 0:
            return None
        return float(value.numerator) / denominator
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and len(value) == 2:
        denominator = float(value[1])
        if denominator == 0:
            return None
        return float(value[0]) / denominator
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def dms_to_decimal(dms: object, ref: str | None) -> float | None:
    """Convert EXIF degrees/minutes/seconds plus N/S/E/W to a signed decimal."""

    if not isinstance(dms, Sequence) or isinstance(dms, (str, bytes)) or len(dms) < 3:
        as_float = _to_float(dms)
        if as_float is None:
            return None
        decimal = as_float
    else:
        degrees = _to_float(dms[0])
        minutes = _to_float(dms[1])
        seconds = _to_float(dms[2])
        if degrees is None or minutes is None or seconds is None:
            return None
        decimal = degrees + minutes / 60.0 + seconds / 3600.0
    direction = (ref or "").strip().upper()
    if direction in {"S", "W"} and decimal > 0:
        decimal = -decimal
    return decimal


def heading_from_exif(
    *,
    img_direction: object = None,
    img_direction_ref: object = None,
    dest_bearing: object = None,
    dest_bearing_ref: object = None,
) -> tuple[float, str, str] | None:
    """Return ``(degrees, ref, source)`` from GPSImgDirection, else GPSDestBearing.

    Degrees are normalized to ``[0, 360)``. ``ref`` is ``T`` (true) or ``M``
    (magnetic); missing ref defaults to true north.
    """

    heading = _one_heading(img_direction, img_direction_ref, HEADING_SOURCE_IMG)
    if heading is None:
        heading = _one_heading(dest_bearing, dest_bearing_ref, HEADING_SOURCE_DEST)
    return heading


def _one_heading(value: object, ref: object, source: str) -> tuple[float, str, str] | None:
    degrees = _to_float(value)
    if degrees is None or not math.isfinite(degrees):
        return None
    degrees %= 360.0
    if degrees < 0:
        degrees += 360.0
    text = _heading_ref(ref)
    return degrees, text, source


def _heading_ref(value: object) -> str:
    if isinstance(value, (bytes, bytearray)):
        text = bytes(value).split(b"\x00", 1)[0].decode("ascii", errors="replace").strip()
    elif value is None:
        text = ""
    else:
        text = str(value).strip().strip("\x00")
    letter = text[:1].upper()
    return letter if letter in {"T", "M"} else "T"


def position_from_exif(
    *,
    latitude: object,
    latitude_ref: str | None,
    longitude: object,
    longitude_ref: str | None,
    altitude: object | None = None,
    altitude_ref: object | None = None,
) -> GeoPosition | None:
    """Build a GeoPosition from EXIF GPS fields. Returns None if incomplete."""

    lat = dms_to_decimal(latitude, latitude_ref)
    lon = dms_to_decimal(longitude, longitude_ref)
    return _geo(lat, lon, altitude, altitude_ref, _GPS_SOURCE_EXIF)


def position_from_coordinates_text(
    value: object, *, source: str = _GPS_SOURCE_QUICKTIME
) -> GeoPosition | None:
    """Parse QuickTime/Apple ``GPSCoordinates`` or ISO 6709 location strings."""

    if value is None or isinstance(value, (int, float)):
        return None
    text = str(value).strip()
    if not text:
        return None
    iso = _ISO6709.search(text.replace(" ", ""))
    if iso:
        return _geo(
            float(iso.group("lat")),
            float(iso.group("lon")),
            iso.group("alt"),
            None,
            source,
        )
    dms = _DMS_PAIR.search(text)
    if dms:
        lat = dms_to_decimal(
            (float(dms.group("lat_d")), float(dms.group("lat_m")), float(dms.group("lat_s"))),
            dms.group("lat_ref"),
        )
        lon = dms_to_decimal(
            (float(dms.group("lon_d")), float(dms.group("lon_m")), float(dms.group("lon_s"))),
            dms.group("lon_ref"),
        )
        return _geo(lat, lon, None, None, source)
    pair = _DECIMAL_PAIR.search(text)
    if pair:
        return _geo(
            float(pair.group("lat")),
            float(pair.group("lon")),
            pair.group("alt"),
            None,
            source,
        )
    return None


def _geo(
    lat: float | None,
    lon: float | None,
    altitude: object | None,
    altitude_ref: object | None,
    source: str,
) -> GeoPosition | None:
    if lat is None or lon is None:
        return None
    if not -90.0 <= lat <= 90.0 or not -180.0 <= lon <= 180.0:
        return None
    alt = _to_float(altitude) if altitude is not None else None
    if alt is not None:
        ref = _to_float(altitude_ref)
        if ref == 1:
            alt = -abs(alt)
    return GeoPosition(
        latitude=lat,
        longitude=lon,
        altitude=alt,
        source=source,
        confidence=1.0,
        time_delta_seconds=None,
    )
