"""Read-only gallery listing from the project index."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from travelcore.database.models import Photo, SourceFile
from travelcore.media.orientation import normalize_rotation_degrees
from travelcore.media.thumbnails import cached_thumbnail_path
from travelcore.media.types import FileKind

SORT_FAVORITE = "favorite"
SORT_RESERVE = "reserve"
SORT_REJECTED = "rejected"
SORT_STATUSES = (SORT_FAVORITE, SORT_RESERVE, SORT_REJECTED)


def effective_sort_status(sort_status: str | None, is_favorite: bool = False) -> str | None:
    if sort_status in SORT_STATUSES:
        return sort_status
    if is_favorite:
        return SORT_FAVORITE
    return None


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
    sort_status: str | None = None
    is_entry_cover: bool = False
    rotation_degrees: int = 0


def list_gallery_items(
    session: Session,
    project_id: int,
    thumbs_dir: Path,
    *,
    size: int = 256,
    source_file_ids: Sequence[int] | None = None,
) -> list[GalleryItem]:
    """Return photos, videos, and tracks in capture-time order with cache paths."""

    if source_file_ids is not None and not source_file_ids:
        return []
    query = (
        select(SourceFile, Photo)
        .outerjoin(Photo, Photo.source_file_id == SourceFile.id)
        .where(
            SourceFile.project_id == project_id,
            SourceFile.file_kind.in_(
                (FileKind.PHOTO.value, FileKind.VIDEO.value, FileKind.GPS.value)
            ),
        )
        .order_by(SourceFile.captured_at.asc().nulls_last(), SourceFile.filename.asc())
    )
    if source_file_ids is not None:
        query = query.where(SourceFile.id.in_(tuple(source_file_ids)))
    rows = session.execute(query)
    items: list[GalleryItem] = []
    for source, photo in rows:
        rotation = normalize_rotation_degrees(source.rotation_degrees)
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
                    rotation_degrees=rotation,
                ),
                sort_status=effective_sort_status(
                    photo.sort_status if photo is not None else None,
                    bool(photo.is_favorite) if photo is not None else False,
                ),
                rotation_degrees=rotation,
            )
        )
    return items
