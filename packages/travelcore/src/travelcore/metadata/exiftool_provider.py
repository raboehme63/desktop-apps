"""ExifTool adapter. Callers must use this class, never invoke ExifTool directly."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
import threading
import time
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path
from typing import Any

from travelcore.exceptions import MetadataError
from travelcore.metadata.gps import position_from_coordinates_text, position_from_exif
from travelcore.metadata.provider import MediaMetadata
from travelcore.metadata.time import choose_captured_time, parse_exif_datetime, with_source

logger = logging.getLogger(__name__)

_READY = b"{ready}"
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


class ExifToolSession:
    """Reusable ExifTool process (stay_open) with argfile fallback."""

    def __init__(self, executable: str) -> None:
        self.executable = executable
        self._proc: subprocess.Popen[bytes] | None = None
        self._lock = threading.Lock()
        self._stay_open_disabled = False

    def execute_json(self, paths: Sequence[str], *, timeout: float = 30.0) -> list[dict[str, Any]]:
        if not paths:
            return []
        total_timeout = min(max(timeout, 30.0) * max(len(paths), 1), 600.0)
        if not self._stay_open_disabled:
            try:
                raw = self._via_stay_open(list(paths), total_timeout)
                return _parse_json_rows(raw, Path(paths[0]).name)
            except MetadataError as exc:
                logger.debug("ExifTool stay_open failed: %s", exc)
                self._disable_stay_open()
        raw = self._via_argfile(list(paths), total_timeout)
        return _parse_json_rows(raw, Path(paths[0]).name)

    def close(self) -> None:
        with self._lock:
            self._stop_locked()

    def _via_stay_open(self, paths: list[str], timeout: float) -> bytes:
        with self._lock:
            proc = self._ensure_locked()
            payload = "\n".join(["-json", "-n", "-charset", "filename=UTF8", *paths, "-execute"]) + "\n"
            if proc.stdin is None or proc.stdout is None:
                raise MetadataError("ExifTool-Prozess hat keine Standardströme.")
            try:
                proc.stdin.write(payload.encode("utf-8"))
                proc.stdin.flush()
            except OSError as exc:
                self._stop_locked()
                raise MetadataError("ExifTool stay_open ist nicht erreichbar.") from exc
            return _read_until_ready(proc, timeout)

    def _via_argfile(self, paths: list[str], timeout: float) -> bytes:
        argfile = Path(tempfile.gettempdir()) / f"travelcore-exiftool-{os.getpid()}-{time.monotonic_ns()}.txt"
        try:
            lines = ["-json", "-n", "-charset", "filename=UTF8", *paths]
            argfile.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
            completed = subprocess.run(  # noqa: S603 - executable is resolved, args are a list
                [self.executable, "-@", str(argfile)],
                check=False,
                capture_output=True,
                timeout=timeout,
                creationflags=_CREATE_NO_WINDOW,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise MetadataError("ExifTool konnte die Dateiliste nicht lesen.") from exc
        finally:
            argfile.unlink(missing_ok=True)
        if completed.returncode != 0:
            raise MetadataError(
                completed.stderr.decode("utf-8", errors="replace").strip() or "ExifTool-Fehler"
            )
        return completed.stdout

    def _ensure_locked(self) -> subprocess.Popen[bytes]:
        if self._proc is not None and self._proc.poll() is None:
            return self._proc
        try:
            self._proc = subprocess.Popen(  # noqa: S603 - executable is resolved, args are a list
                [self.executable, "-stay_open", "True", "-@", "-"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=_CREATE_NO_WINDOW,
            )
        except OSError as exc:
            raise MetadataError("ExifTool konnte nicht gestartet werden.") from exc
        stderr = self._proc.stderr
        if stderr is not None:
            threading.Thread(
                target=_drain_stream,
                args=(stderr,),
                name="exiftool-stderr",
                daemon=True,
            ).start()
        return self._proc

    def _disable_stay_open(self) -> None:
        with self._lock:
            self._stay_open_disabled = True
            self._stop_locked()

    def _stop_locked(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        try:
            if proc.stdin is not None and proc.poll() is None:
                proc.stdin.write(b"-stay_open\nFalse\n")
                proc.stdin.flush()
            proc.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            proc.kill()
            with suppress(OSError, subprocess.TimeoutExpired):
                proc.wait(timeout=2)
        finally:
            for stream in (proc.stdin, proc.stdout, proc.stderr):
                if stream is not None:
                    with suppress(OSError):
                        stream.close()


class ExifToolMetadataProvider:
    """Optional metadata backend for formats Pillow cannot read (HEIC, RAW)."""

    def __init__(self, executable: str, *, session: ExifToolSession | None = None) -> None:
        self.executable = executable
        self._session = session or ExifToolSession(executable)

    @classmethod
    def from_environment(cls) -> ExifToolMetadataProvider | None:
        path = _find_exiftool()
        if path is None:
            return None
        return cls(path)

    def read(self, path: Path) -> MediaMetadata:
        rows = self._session.execute_json([str(path)])
        if not rows:
            raise MetadataError(f"ExifTool lieferte keine Metadaten für {path.name}.")
        return metadata_from_exiftool_json(rows[0])

    def read_many(self, paths: Sequence[Path]) -> dict[str, MediaMetadata]:
        if not paths:
            return {}
        rows = self._session.execute_json([str(path) for path in paths])
        by_source = _index_exiftool_rows(rows)
        result: dict[str, MediaMetadata] = {}
        for path in paths:
            key = _norm_path(path)
            payload = by_source.get(key)
            if payload is None and rows:
                payload = rows[0] if len(paths) == 1 else None
            if payload is None:
                continue
            result[str(path)] = metadata_from_exiftool_json(payload)
        return result

    def close(self) -> None:
        self._session.close()


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


def _drain_stream(stream: Any) -> None:
    with suppress(OSError):
        while stream.readline():
            pass


def _parse_json_rows(raw: bytes, label: str) -> list[dict[str, Any]]:
    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        raise MetadataError(f"ExifTool lieferte keine Metadaten für {label}.")
    try:
        rows = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MetadataError(f"ExifTool lieferte ungültiges JSON für {label}.") from exc
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        raise MetadataError(f"ExifTool lieferte keine Metadaten für {label}.")
    return rows


def _index_exiftool_rows(rows: Sequence[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        source = row.get("SourceFile")
        if isinstance(source, str) and source:
            indexed[_norm_path(source)] = row
    return indexed


def _norm_path(path: Path | str) -> str:
    return os.path.normcase(os.path.normpath(str(path)))


def _read_until_ready(proc: subprocess.Popen[bytes], timeout: float) -> bytes:
    stdout = proc.stdout
    if stdout is None:
        raise MetadataError("ExifTool-Prozess hat keine Standardausgabe.")
    chunks: list[bytes] = []
    finished = threading.Event()
    error: list[BaseException] = []

    def _read() -> None:
        try:
            while True:
                line = stdout.readline()
                if not line:
                    if proc.poll() is not None:
                        raise MetadataError("ExifTool stay_open wurde beendet.")
                    continue
                if line.strip() == _READY:
                    return
                chunks.append(line)
        except BaseException as exc:  # noqa: BLE001 - propagate into waiter
            error.append(exc)
        finally:
            finished.set()

    worker = threading.Thread(target=_read, name="exiftool-stdout", daemon=True)
    worker.start()
    if not finished.wait(timeout):
        proc.kill()
        raise MetadataError("ExifTool stay_open hat das Zeitlimit überschritten.")
    worker.join(timeout=1)
    if error:
        raise MetadataError(str(error[0])) from error[0]
    return b"".join(chunks)


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
