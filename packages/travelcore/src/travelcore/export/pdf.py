"""PDF export: raster Travelbook pages, then JPEG-in-PDF.

The first ``PdfRenderer`` is the raster writer. HTML-print and LaTeX remain
later backends behind the same protocol. PyMuPDF is not a dependency.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Protocol

from travelcore.exceptions import ExportError
from travelcore.export.base import Exporter, ExportResult
from travelcore.export.book import book_pages, export_rotations, export_sources
from travelcore.export.catalog import assert_supported, page_size
from travelcore.export.document import TravelbookDocument
from travelcore.export.paint import encode_jpeg, render_book_page
from travelcore.export.pdfwrite import write_jpeg_pdf
from travelcore.export.quality import DEFAULT_QUALITY_ID, pdf_quality
from travelcore.export.raster import page_pixels
from travelcore.timeline.types import TimelineSnapshot
from travelcore.trip.models import Trip

_SLUG = re.compile(r"[^\w\-]+", re.UNICODE)


class PdfRenderer(Protocol):
    def write(
        self,
        pages: Sequence[tuple[bytes, int, int]],
        destination: Path,
        *,
        width_mm: float,
        height_mm: float,
    ) -> Path:
        """Write JPEG page payloads to a PDF without coupling the exporter to one engine."""
        ...


class RasterPdfRenderer:
    """Default renderer: one JPEG image per page (Pillow encode, custom PDF)."""

    def write(
        self,
        pages: Sequence[tuple[bytes, int, int]],
        destination: Path,
        *,
        width_mm: float,
        height_mm: float,
    ) -> Path:
        return write_jpeg_pdf(pages, destination, width_mm=width_mm, height_mm=height_mm)


class PdfExporter(Exporter):
    name = "pdf"

    def __init__(self, renderer: PdfRenderer | None = None) -> None:
        self.renderer = renderer or RasterPdfRenderer()

    def export(self, trip: Trip, destination: Path) -> ExportResult:
        del trip
        raise ExportError("PDF-Export erwartet ein Travelbook-Dokument. Nutzen Sie export_travelbook_pdf().")

    def export_document(
        self,
        document: TravelbookDocument,
        snapshot: TimelineSnapshot,
        destination: Path,
        *,
        sources: Mapping[int, Path] | None = None,
        rotations: Mapping[int, int] | None = None,
        dpi: float | None = None,
        quality: str = DEFAULT_QUALITY_ID,
        progress: Callable[[int, int], None] | None = None,
    ) -> ExportResult:
        return export_travelbook_pdf(
            document,
            snapshot,
            destination,
            renderer=self.renderer,
            sources=sources,
            rotations=rotations,
            dpi=dpi,
            quality=quality,
            progress=progress,
        )


def export_filename(title: str) -> str:
    slug = _SLUG.sub("-", (title or "").strip()).strip("-")
    slug = slug[:48] or "travelbook"
    return f"{slug}.pdf"


def normalize_pdf_save_path(chosen: str | Path) -> Path:
    """Ensure a user-picked path ends with ``.pdf``."""

    path = Path(chosen)
    if path.suffix.lower() != ".pdf":
        path = path.with_suffix(".pdf")
    return path


def unique_export_path(directory: Path, filename: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    index = 2
    while True:
        candidate = directory / f"{stem}-{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def export_travelbook_pdf(
    document: TravelbookDocument,
    snapshot: TimelineSnapshot,
    destination: Path,
    *,
    renderer: PdfRenderer | None = None,
    sources: Mapping[int, Path] | None = None,
    rotations: Mapping[int, int] | None = None,
    dpi: float | None = None,
    quality: str = DEFAULT_QUALITY_ID,
    jpeg_quality: int | None = None,
    jpeg_subsampling: int | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> ExportResult:
    """Rasterize the composed Travelbook and write a PDF. Originals are not written."""

    product = document.product or "travelbook"
    assert_supported(product, "pdf")
    if product != "travelbook":
        raise ExportError(f"PDF für Ausgabetyp '{product}' ist in dieser Version noch nicht implementiert.")
    preset = pdf_quality(quality)
    used_dpi = float(dpi) if dpi is not None else preset.dpi
    used_jpeg = int(jpeg_quality) if jpeg_quality is not None else preset.jpeg_quality
    used_sub = jpeg_subsampling if jpeg_subsampling is not None else preset.jpeg_subsampling
    size = page_size(document.page_size)
    width_mm = float(size["width_mm"])
    height_mm = float(size["height_mm"])
    pixel_w, pixel_h = page_pixels(width_mm, height_mm, dpi=used_dpi)
    pages = book_pages(document, snapshot)
    resolved = sources if sources is not None else export_sources(snapshot)
    turns = rotations if rotations is not None else export_rotations(snapshot)
    encoded: list[tuple[bytes, int, int]] = []
    total = len(pages)
    for index, page in enumerate(pages, start=1):
        image = render_book_page(page, resolved, pixel_w, pixel_h, dpi=used_dpi, rotation_degrees=turns)
        try:
            encoded.append(encode_jpeg(image, quality=used_jpeg, subsampling=used_sub))
        finally:
            image.close()
        if progress is not None:
            progress(index, total)
    engine = renderer or RasterPdfRenderer()
    output = engine.write(encoded, Path(destination), width_mm=width_mm, height_mm=height_mm)
    return ExportResult(output_path=output, files_written=(output,))
