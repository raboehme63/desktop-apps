"""Read-only gallery listing from the project index."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from travelcore.config import DEFAULT_THUMBNAIL_SIZE
from travelcore.database.models import Photo, PhotoAnalysis, SourceFile
from travelcore.gps.maptracks import is_map_track_path
from travelcore.gps.track_badge import TRACK_BADGE_MAP, track_badge_for
from travelcore.image_analysis.quality import quality_light, quality_tooltip
from travelcore.media.orientation import normalize_rotation_degrees
from travelcore.media.thumbnails import cached_thumbnail_path
from travelcore.media.types import FileKind
from travelcore.similarity.clusters import load_cluster_overlay

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
    parked: bool = False
    journal_at: datetime | None = None
    display_latitude: float | None = None
    display_longitude: float | None = None
    stack_id: int | None = None
    stack_size: int = 0
    is_stack_key: bool = False
    group_id: int | None = None
    group_size: int = 0
    is_group_key: bool = False
    group_status: str | None = None
    quality_light: str | None = None
    quality_tooltip: str | None = None
    is_map_track: bool = False
    track_badge: str | None = None


def list_gallery_items(
    session: Session,
    project_id: int,
    thumbs_dir: Path,
    *,
    size: int = DEFAULT_THUMBNAIL_SIZE,
    source_file_ids: Sequence[int] | None = None,
    hide_cluster_hidden: bool = True,
) -> list[GalleryItem]:
    """Return photos, videos, and tracks in capture-time order with cache paths."""

    if source_file_ids is not None and not source_file_ids:
        return []
    query = (
        select(SourceFile, Photo, PhotoAnalysis)
        .outerjoin(Photo, Photo.source_file_id == SourceFile.id)
        .outerjoin(PhotoAnalysis, PhotoAnalysis.photo_id == Photo.id)
        .where(
            SourceFile.project_id == project_id,
            SourceFile.file_kind.in_((FileKind.PHOTO.value, FileKind.VIDEO.value, FileKind.GPS.value)),
        )
        .order_by(SourceFile.captured_at.asc().nulls_last(), SourceFile.filename.asc())
    )
    if source_file_ids is not None:
        query = query.where(SourceFile.id.in_(tuple(source_file_ids)))
    rows = session.execute(query)
    overlay = load_cluster_overlay(session, project_id)
    items: list[GalleryItem] = []
    for source, photo, analysis in rows:
        if is_map_track_path(source.path):
            continue
        if hide_cluster_hidden and overlay.is_hidden(source.id):
            continue
        rotation = normalize_rotation_degrees(source.rotation_degrees)
        marks = overlay.for_source(source.id)
        badge = track_badge_for(source.path, source.filename)
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
                    prefer_existing=True,
                ),
                sort_status=effective_sort_status(
                    photo.sort_status if photo is not None else None,
                    bool(photo.is_favorite) if photo is not None else False,
                ),
                rotation_degrees=rotation,
                parked=bool(source.parked),
                stack_id=marks.stack_id,
                stack_size=marks.stack_size,
                is_stack_key=marks.is_stack_key,
                group_id=marks.group_id,
                group_size=marks.group_size,
                is_group_key=marks.is_group_key,
                group_status=marks.group_status,
                quality_light=quality_light(
                    analysis.technical_quality if analysis is not None else None
                ),
                quality_tooltip=quality_tooltip(
                    technical_quality=analysis.technical_quality if analysis is not None else None,
                    resolution_score=analysis.resolution_score if analysis is not None else None,
                    sharpness=analysis.sharpness if analysis is not None else None,
                    contrast=analysis.contrast if analysis is not None else None,
                    overexposed=analysis.overexposed if analysis is not None else None,
                    underexposed=analysis.underexposed if analysis is not None else None,
                    width=source.width,
                    height=source.height,
                ),
                is_map_track=badge == TRACK_BADGE_MAP,
                track_badge=badge,
            )
        )
    return items
