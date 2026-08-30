"""Run quality analysis for a project. Originals are never written."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from travelcore.database.models import Photo, PhotoAnalysis, SourceFile
from travelcore.image_analysis.quality import QualityMetrics, analyze_photo
from travelcore.media.types import FileKind
from travelcore.parallel import WorkerPool, map_in_processes

ProgressFn = Callable[[int, int], None]


@dataclass(frozen=True, slots=True)
class QualityJob:
    photo_id: int
    path: str
    width: int | None
    height: int | None


@dataclass(frozen=True, slots=True)
class QualityJobResult:
    photo_id: int
    metrics: QualityMetrics | None


@dataclass(frozen=True, slots=True)
class QualityRunResult:
    analyzed: int = 0
    skipped: int = 0
    failed: int = 0


def analyze_quality_chunk(jobs: tuple[QualityJob, ...]) -> list[QualityJobResult]:
    """Module-level worker entry. Must stay importable after Windows spawn."""

    results: list[QualityJobResult] = []
    for job in jobs:
        try:
            metrics = analyze_photo(
                Path(job.path),
                width_hint=job.width,
                height_hint=job.height,
            )
        except (OSError, ValueError):
            metrics = None
        results.append(QualityJobResult(photo_id=job.photo_id, metrics=metrics))
    return results


def analyze_project_photos(
    session: Session,
    project_id: int,
    *,
    force: bool = False,
    max_workers: int | None = None,
    pool: WorkerPool | None = None,
    progress: ProgressFn | None = None,
) -> QualityRunResult:
    """Analyze indexed photos. Does not change ``sort_status`` or originals."""

    rows = list(
        session.execute(
            select(Photo, SourceFile, PhotoAnalysis)
            .join(SourceFile, SourceFile.id == Photo.source_file_id)
            .outerjoin(PhotoAnalysis, PhotoAnalysis.photo_id == Photo.id)
            .where(
                SourceFile.project_id == project_id,
                SourceFile.file_kind == FileKind.PHOTO.value,
            )
        )
    )
    jobs: list[QualityJob] = []
    skipped = 0
    for photo, source, existing in rows:
        if existing is not None and existing.technical_quality is not None and not force:
            skipped += 1
            continue
        jobs.append(
            QualityJob(
                photo_id=photo.id,
                path=source.path,
                width=source.width,
                height=source.height,
            )
        )
    if not jobs:
        if progress is not None:
            progress(0, 0)
        return QualityRunResult(skipped=skipped)

    if progress is not None:
        progress(0, len(jobs))
    outcomes = map_in_processes(
        analyze_quality_chunk,
        jobs,
        max_workers=max_workers,
        pool=pool,
        progress=progress,
    )
    now = datetime.now(tz=UTC)
    analyzed = 0
    failed = 0
    by_photo = {photo.id: existing for photo, _source, existing in rows}
    for outcome in outcomes:
        if outcome.metrics is None or outcome.metrics.technical_quality is None:
            failed += 1
            continue
        _upsert_analysis(session, outcome.photo_id, outcome.metrics, now, by_photo.get(outcome.photo_id))
        analyzed += 1
    return QualityRunResult(analyzed=analyzed, skipped=skipped, failed=failed)


def _upsert_analysis(
    session: Session,
    photo_id: int,
    metrics: QualityMetrics,
    analyzed_at: datetime,
    existing: PhotoAnalysis | None,
) -> None:
    if existing is None:
        session.add(
            PhotoAnalysis(
                photo_id=photo_id,
                resolution_score=metrics.resolution_score,
                brightness=metrics.brightness,
                contrast=metrics.contrast,
                sharpness=metrics.sharpness,
                overexposed=metrics.overexposed,
                underexposed=metrics.underexposed,
                technical_quality=metrics.technical_quality,
                analyzed_at=analyzed_at,
            )
        )
        return
    existing.resolution_score = metrics.resolution_score
    existing.brightness = metrics.brightness
    existing.contrast = metrics.contrast
    existing.sharpness = metrics.sharpness
    existing.overexposed = metrics.overexposed
    existing.underexposed = metrics.underexposed
    existing.technical_quality = metrics.technical_quality
    existing.analyzed_at = analyzed_at
