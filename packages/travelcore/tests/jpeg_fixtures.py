"""Helpers to write synthetic JPEGs for tests. No personal GPS data."""

from __future__ import annotations

from pathlib import Path

from PIL import Image
from PIL.ExifTags import GPS, IFD, Base


def write_plain_jpeg(path: Path, *, size: tuple[int, int] = (16, 12)) -> Path:
    Image.new("RGB", size, (12, 24, 48)).save(path, format="JPEG")
    return path


def write_jpeg_with_exif(
    path: Path,
    *,
    datetime_original: str | None = None,
    create_date: str | None = None,
    offset_original: str | None = None,
    make: str | None = "Canon",
    model: str | None = "EOS R6",
    orientation: int | None = 1,
    latitude: tuple[float, float, float] | None = None,
    latitude_ref: str = "N",
    longitude: tuple[float, float, float] | None = None,
    longitude_ref: str = "E",
    altitude: float | None = None,
    size: tuple[int, int] = (32, 24),
) -> Path:
    image = Image.new("RGB", size, (30, 60, 90))
    exif = Image.Exif()
    if make:
        exif[Base.Make] = make
    if model:
        exif[Base.Model] = model
    if orientation is not None:
        exif[Base.Orientation] = orientation
    exif_ifd = exif.get_ifd(IFD.Exif)
    if datetime_original:
        exif_ifd[Base.DateTimeOriginal] = datetime_original
    if create_date:
        exif_ifd[Base.DateTimeDigitized] = create_date
    if offset_original:
        exif_ifd[Base.OffsetTimeOriginal] = offset_original
    if latitude is not None and longitude is not None:
        gps_ifd = exif.get_ifd(IFD.GPSInfo)
        gps_ifd[GPS.GPSLatitudeRef] = latitude_ref
        gps_ifd[GPS.GPSLatitude] = latitude
        gps_ifd[GPS.GPSLongitudeRef] = longitude_ref
        gps_ifd[GPS.GPSLongitude] = longitude
        if altitude is not None:
            gps_ifd[GPS.GPSAltitude] = altitude
            gps_ifd[GPS.GPSAltitudeRef] = 0
    image.save(path, format="JPEG", exif=exif)
    return path


def jpeg_exif_app1(path: Path) -> bytes:
    """Return the JPEG APP1 payload starting at ``Exif\\x00\\x00``."""

    data = path.read_bytes()
    if data[:2] != b"\xff\xd8":
        raise ValueError(f"{path} is not a JPEG")
    offset = 2
    while offset + 4 <= len(data) and data[offset] == 0xFF:
        marker = data[offset + 1]
        if marker == 0xDA:
            break
        if marker in {0xD8, 0xD9}:
            offset += 2
            continue
        length = int.from_bytes(data[offset + 2 : offset + 4], "big")
        payload = data[offset + 4 : offset + 2 + length]
        if marker == 0xE1 and payload.startswith(b"Exif\x00\x00"):
            return payload
        offset += 2 + length
    raise ValueError(f"{path} has no EXIF APP1 segment")

