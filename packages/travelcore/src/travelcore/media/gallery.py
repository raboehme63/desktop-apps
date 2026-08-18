"""Read-only gallery listing from the project index."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from travelcore.database.models import Photo, SourceFile
from travelcore.media.thumbnails import cached_thumbnail_path
from travelcore.media.types import FileKind


@dataclass(frozen=True, slots=True)
class GalleryItem:
    source_file_id: int
    path: str
    filename: str
    extension: str
    captured_at: datetime | None
    timezone_unknown: bool
    gps_latitude: float | None
    gps_longitude: float | None
    camera: str | None
    is_favorite: bool
    used_in_journal: bool
    thumbnail_path: Path


def list_gallery_items(
    session: Session,
    project_id: int,
    thumbs_dir: Path,
    *,
    size: int = 256,
) -> list[GalleryItem]:
    """Return photos in capture-time order with cache paths (file may be missing)."""

    rows = session.execute(
        select(SourceFile, Photo)
        .outerjoin(Photo, Photo.source_file_id == SourceFile.id)
        .where(
            SourceFile.project_id == project_id,
            SourceFile.file_kind == FileKind.PHOTO.value,
        )
        .order_by(SourceFile.captured_at.asc().nulls_last(), SourceFile.filename.asc())
    )
    items: list[GalleryItem] = []
    for source, photo in rows:
        items.append(
            GalleryItem(
                source_file_id=source.id,
                path=source.path,
                filename=source.filename,
                extension=source.extension,
                captured_at=source.captured_at,
                timezone_unknown=source.timezone_unknown,
                gps_latitude=source.gps_latitude,
                gps_longitude=source.gps_longitude,
                camera=source.camera,
                is_favorite=bool(photo.is_favorite) if photo is not None else False,
                used_in_journal=bool(photo.used_in_journal) if photo is not None else False,
                thumbnail_path=cached_thumbnail_path(
                    thumbs_dir,
                    source_file_id=source.id,
                    sha256=source.sha256,
                    size=size,
                ),
            )
        )
    return items
