"""Recursive discovery of supported source files."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

try:
    from stat import FILE_ATTRIBUTE_HIDDEN
except ImportError:  # pragma: no cover - non-Windows
    FILE_ATTRIBUTE_HIDDEN = 2

from travelcore.media.types import FileKind, classify_path, mime_for_path


@dataclass(frozen=True, slots=True)
class ScannedFile:
    """A supported file found during a source-directory walk."""

    path: Path
    filename: str
    kind: FileKind
    mime_type: str | None
    size_bytes: int
    fs_created_at: datetime | None
    fs_modified_at: datetime | None


def _to_datetime(timestamp: float | None) -> datetime | None:
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, tz=UTC)


def _is_hidden(path: Path) -> bool:
    if path.name.startswith("."):
        return True
    try:
        attrs = path.stat().st_file_attributes  # type: ignore[attr-defined]
    except AttributeError:
        return False
    return bool(attrs & FILE_ATTRIBUTE_HIDDEN)


def scan_source_directory(root: Path) -> Iterator[ScannedFile]:
    """Yield supported files under ``root`` (recursive).

    Hidden files and directories are skipped. A single unreadable file does
    not abort the scan; the caller decides how to record errors.
    """

    root = root.expanduser().resolve()
    if not root.is_dir():
        raise NotADirectoryError(str(root))

    for path in root.rglob("*"):
        try:
            if not path.is_file() or _is_hidden(path):
                continue
            kind = classify_path(path)
            if kind is None:
                continue
            stat = path.stat()
            yield ScannedFile(
                path=path,
                filename=path.name,
                kind=kind,
                mime_type=mime_for_path(path),
                size_bytes=stat.st_size,
                fs_created_at=_to_datetime(getattr(stat, "st_ctime", None)),
                fs_modified_at=_to_datetime(stat.st_mtime),
            )
        except OSError:
            continue
