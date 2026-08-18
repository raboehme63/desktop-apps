"""ExifTool adapter. Callers must use this class, never invoke ExifTool directly."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from travelcore.exceptions import MetadataError
from travelcore.metadata.gps import position_from_coordinates_text, position_from_exif
from travelcore.metadata.provider import MediaMetadata
from travelcore.metadata.time import choose_captured_time, parse_exif_datetime, with_source


class ExifToolMetadataProvider:
    """Optional metadata backend for formats Pillow cannot read (HEIC, RAW)."""

    def __init__(self, executable: str) -> None:
        self.executable = executable

    @classmethod
    def from_environment(cls) -> ExifToolMetadataProvider | None:
        path = _find_exiftool()
        if path is None:
            return None
        return cls(path)

    def read(self, path: Path) -> MediaMetadata:
        payload = self._run(path)
        return metadata_from_exiftool_json(payload)

    def _run(self, path: Path) -> dict[str, Any]:
        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            completed = subprocess.run(  # noqa: S603 - executable is resolved, args are a list
                [
                    self.executable,
                    "-json",
                    "-n",
                    "-charset",
                    "filename=UTF8",
                    str(path),
                ],
                check=False,
                capture_output=True,
                timeout=30,
                creationflags=creationflags,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise MetadataError(f"ExifTool konnte {path.name} nicht lesen.") from exc
        if completed.returncode != 0:
            raise MetadataError(
                completed.stderr.decode("utf-8", errors="replace").strip()
                or f"ExifTool-Fehler bei {path.name}"
            )
        try:
            rows = json.loads(completed.stdout.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise MetadataError(f"ExifTool lieferte ungültiges JSON für {path.name}.") from exc
        if not rows or not isinstance(rows, list) or not isinstance(rows[0], dict):
            raise MetadataError(f"ExifTool lieferte keine Metadaten für {path.name}.")
        return rows[0]


def metadata_from_exiftool_json(data: dict[str, Any]) -> MediaMetadata:
    """Map an ExifTool JSON object (``-n`` numeric mode) onto MediaMetadata."""

    original = parse_exif_datetime(
        _text(data.get("DateTimeOriginal")),
        offset=_text(data.get("OffsetTimeOriginal")),
    )
    created = parse_exif_datetime(
        _text(data.get("CreateDate")),
        offset=_text(data.get("OffsetTimeDigitized") or data.get("OffsetTime")),
    )
    xmp_time = parse_exif_datetime(_text(data.get("DateCreated") or data.get("XMP:CreateDate")))
    video_time = parse_exif_datetime(
        _text(data.get("MediaCreateDate") or data.get("TrackCreateDate") or data.get("CreationDate"))
    )
    captured = choose_captured_time(
        {
            "exif_datetime_original": with_source(original, "exif_datetime_original") if original else None,
            "exif_create_date": with_source(created, "exif_create_date") if created else None,
            "xmp_create_date": with_source(xmp_time, "xmp_create_date") if xmp_time else None,
            "video_creation_time": with_source(video_time, "video_creation_time") if video_time else None,
        }
    )
    latitude = data.get("GPSLatitude")
    longitude = data.get("GPSLongitude")
    position = None
    if latitude is not None and longitude is not None:
        lat_ref = _text(data.get("GPSLatitudeRef"))
        lon_ref = _text(data.get("GPSLongitudeRef"))
        try:
            if lat_ref is None:
                lat_ref = "S" if float(latitude) < 0 else "N"
            if lon_ref is None:
                lon_ref = "W" if float(longitude) < 0 else "E"
        except (TypeError, ValueError):
            pass
        position = position_from_exif(
            latitude=latitude,
            latitude_ref=lat_ref,
            longitude=longitude,
            longitude_ref=lon_ref,
            altitude=data.get("GPSAltitude"),
            altitude_ref=data.get("GPSAltitudeRef"),
        )
    if position is None:
        for key in (
            "GPSCoordinates",
            "Keys:GPSCoordinates",
            "ItemList:GPSCoordinates",
            "UserData:GPSCoordinates",
            "GPSPosition",
        ):
            position = position_from_coordinates_text(data.get(key))
            if position is not None:
                break
    make = _text(data.get("Make"))
    model = _text(data.get("Model"))
    camera = None
    if make and model:
        camera = model if model.lower().startswith(make.lower()) else f"{make} {model}"
    else:
        camera = model or make
    return MediaMetadata(
        captured=captured,
        position=position,
        camera=camera,
        lens=_text(data.get("LensModel") or data.get("Lens")),
        focal_length=_float(data.get("FocalLength")),
        iso=_int(data.get("ISO")),
        exposure_time=_text(data.get("ExposureTime")),
        aperture=_aperture(data.get("FNumber") or data.get("Aperture")),
        orientation=_int(data.get("Orientation")),
        width=_int(data.get("ImageWidth") or data.get("ExifImageWidth")),
        height=_int(data.get("ImageHeight") or data.get("ExifImageHeight")),
    )


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _aperture(value: object) -> str | None:
    number = _float(value)
    if number is None:
        return _text(value)
    return f"f/{number:g}"


def _find_exiftool() -> str | None:
    for name in ("exiftool", "exiftool.exe"):
        found = shutil.which(name)
        if found:
            return found
    extras = (
        Path.home() / "exiftool.exe",
        Path.home() / "AppData" / "Local" / "Programs" / "exiftool" / "exiftool.exe",
        Path(r"C:\Program Files\exiftool\exiftool.exe"),
        Path(r"C:\Windows\exiftool.exe"),
    )
    for candidate in extras:
        if candidate.is_file():
            return str(candidate)
    return None
