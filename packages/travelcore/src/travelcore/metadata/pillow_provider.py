"""Pillow-based EXIF / XMP reader. Original files are opened read-only."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError
from PIL.ExifTags import GPS, IFD, Base

from travelcore.exceptions import MetadataError
from travelcore.metadata.gps import position_from_exif
from travelcore.metadata.provider import CapturedTime, MediaMetadata
from travelcore.metadata.time import choose_captured_time, parse_exif_datetime, with_source

logger = logging.getLogger(__name__)

_SUPPORTED = {".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".png"}

_XMP_DATE_KEYS = (
    "DateCreated",
    "CreateDate",
    "DateTimeOriginal",
    "DateTimeDigitized",
)


class PillowMetadataProvider:
    """Read photo metadata via Pillow. Does not invoke ExifTool."""

    def read(self, path: Path) -> MediaMetadata:
        suffix = path.suffix.lower()
        if suffix not in _SUPPORTED:
            return MediaMetadata(captured=None, position=None)
        try:
            with Image.open(path) as image:
                image.load()
                width, height = image.size
                exif = image.getexif()
                xmp = _safe_xmp(image)
        except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as exc:
            raise MetadataError(f"Metadaten konnten nicht gelesen werden: {path.name}") from exc

        exif_ifd = _ifd(exif, IFD.Exif)
        gps_ifd = _ifd(exif, IFD.GPSInfo)
        captured = _captured_from_pillow(exif, exif_ifd, xmp)
        position = _position_from_pillow(gps_ifd)
        return MediaMetadata(
            captured=captured,
            position=position,
            camera=_camera(exif, exif_ifd),
            lens=_text(exif_ifd.get(Base.LensModel) or exif.get(Base.LensModel)),
            focal_length=_first_float(exif_ifd.get(Base.FocalLength)),
            iso=_iso(exif_ifd.get(Base.ISOSpeedRatings)),
            exposure_time=_exposure(exif_ifd.get(Base.ExposureTime)),
            aperture=_aperture(exif_ifd.get(Base.FNumber)),
            orientation=_int_or_none(exif.get(Base.Orientation)),
            width=width,
            height=height,
        )


def _ifd(exif: Image.Exif, ifd_id: int) -> dict[int, Any]:
    try:
        return dict(exif.get_ifd(ifd_id) or {})
    except Exception:  # noqa: BLE001 - Pillow raises various errors for missing IFDs
        return {}


def _safe_xmp(image: Image.Image) -> dict[str, Any]:
    try:
        import defusedxml  # noqa: F401
    except ImportError:
        return {}
    getter = getattr(image, "getxmp", None)
    if getter is None:
        return {}
    try:
        data = getter()
    except Exception:  # noqa: BLE001 - XMP is optional
        logger.debug("XMP could not be parsed for %s", getattr(image, "filename", ""))
        return {}
    return data if isinstance(data, dict) else {}


def _captured_from_pillow(
    exif: Image.Exif,
    exif_ifd: dict[int, Any],
    xmp: dict[str, Any],
) -> CapturedTime | None:
    original = parse_exif_datetime(
        _text(exif_ifd.get(Base.DateTimeOriginal) or exif.get(Base.DateTimeOriginal)),
        offset=_text(exif_ifd.get(Base.OffsetTimeOriginal)),
    )
    created = parse_exif_datetime(
        _text(exif_ifd.get(Base.DateTimeDigitized) or exif.get(Base.DateTimeDigitized)),
        offset=_text(exif_ifd.get(Base.OffsetTimeDigitized)),
    )
    xmp_time = parse_exif_datetime(_xmp_date(xmp))
    return choose_captured_time(
        {
            "exif_datetime_original": with_source(original, "exif_datetime_original") if original else None,
            "exif_create_date": with_source(created, "exif_create_date") if created else None,
            "xmp_create_date": with_source(xmp_time, "xmp_create_date") if xmp_time else None,
        }
    )


def _position_from_pillow(gps_ifd: dict[int, Any]):
    if not gps_ifd:
        return None
    return position_from_exif(
        latitude=gps_ifd.get(GPS.GPSLatitude),
        latitude_ref=_text(gps_ifd.get(GPS.GPSLatitudeRef)),
        longitude=gps_ifd.get(GPS.GPSLongitude),
        longitude_ref=_text(gps_ifd.get(GPS.GPSLongitudeRef)),
        altitude=gps_ifd.get(GPS.GPSAltitude),
        altitude_ref=gps_ifd.get(GPS.GPSAltitudeRef),
    )


def _camera(exif: Image.Exif, exif_ifd: dict[int, Any]) -> str | None:
    make = _text(exif.get(Base.Make) or exif_ifd.get(Base.Make))
    model = _text(exif.get(Base.Model) or exif_ifd.get(Base.Model))
    if make and model:
        if model.lower().startswith(make.lower()):
            return model
        return f"{make} {model}"
    return model or make


def _xmp_date(xmp: dict[str, Any]) -> str | None:
    found: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                local = str(key).split(":")[-1]
                if local in _XMP_DATE_KEYS and isinstance(value, str):
                    found.append(value)
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(xmp)
    return found[0] if found else None


def _text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace").strip("\x00 ").strip()
        return text or None
    text = str(value).strip("\x00 ").strip()
    return text or None


def _first_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (tuple, list)) and value:
        value = value[0]
    if hasattr(value, "numerator") and hasattr(value, "denominator"):
        denominator = float(value.denominator)
        return None if denominator == 0 else float(value.numerator) / denominator
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _int_or_none(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, (tuple, list)) and value:
        value = value[0]
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _iso(value: object) -> int | None:
    return _int_or_none(value)


def _exposure(value: object) -> str | None:
    number = _first_float(value)
    if number is None:
        return _text(value)
    if number == 0:
        return None
    if number >= 1:
        return f"{number:g}"
    denominator = round(1 / number)
    if denominator > 0:
        return f"1/{denominator}"
    return f"{number:g}"


def _aperture(value: object) -> str | None:
    number = _first_float(value)
    if number is None:
        return _text(value)
    return f"f/{number:g}"
