"""CEWE project export: Travelbook → classic ``.mcf`` plus image folder.

The file is meant to be opened in the CEWE Creator for fine-tuning. Photos and
text stay native objects; country outlines, flags, the intro timeline and the
overview map are replaceable images. This is not an official CEWE interface.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path

from travelcore.exceptions import ExportError
from travelcore.export.base import Exporter, ExportResult
from travelcore.export.book import book_pages, export_rotations, export_sources
from travelcore.export.catalog import assert_supported
from travelcore.export.document import TravelbookDocument
from travelcore.export.mcfproduct import MAX_CONTENT_PAGES, PAGE_SIZE_ID
from travelcore.export.mcfwrite import (
    McfAssetStore,
    content_pages,
    mcf_folder_name,
    slug_filename,
    write_fotobook,
)
from travelcore.timeline.types import TimelineSnapshot
from travelcore.trip.models import Trip


class CeweExporter(Exporter):
    name = "cewe"

    def export(self, trip: Trip, destination: Path) -> ExportResult:
        del trip
        raise ExportError("CEWE-Export erwartet ein Travelbook-Dokument. Nutzen Sie export_travelbook_mcf().")

    def export_document(
        self,
        document: TravelbookDocument,
        snapshot: TimelineSnapshot,
        destination: Path,
        *,
        sources: Mapping[int, Path] | None = None,
        rotations: Mapping[int, int] | None = None,
        progress: Callable[[int, int], None] | None = None,
    ) -> ExportResult:
        return export_travelbook_mcf(
            document,
            snapshot,
            destination,
            sources=sources,
            rotations=rotations,
            progress=progress,
        )


def export_mcf_filename(title: str) -> str:
    return slug_filename(title)


def normalize_mcf_save_path(chosen: str | Path) -> Path:
    path = Path(chosen)
    if path.suffix.lower() != ".mcf":
        path = path.with_suffix(".mcf")
    return path


def export_travelbook_mcf(
    document: TravelbookDocument,
    snapshot: TimelineSnapshot,
    destination: Path,
    *,
    sources: Mapping[int, Path] | None = None,
    rotations: Mapping[int, int] | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> ExportResult:
    """Write an editable CEWE project. Originals are only read."""

    product = document.product or "travelbook"
    assert_supported(product, "cewe")
    if product != "travelbook":
        raise ExportError(f"CEWE für Ausgabetyp '{product}' ist in dieser Version noch nicht implementiert.")
    if document.page_size != PAGE_SIZE_ID:
        raise ExportError(
            "CEWE-Export gibt es in dieser Version nur für DIN A4 Hochformat (CEWE Fotobuch Groß)."
        )
    pages = book_pages(document, snapshot)
    cover, interiors = content_pages(pages)
    if len(interiors) > MAX_CONTENT_PAGES:
        raise ExportError(
            f"CEWE-Fotobuch Groß erlaubt höchstens {MAX_CONTENT_PAGES} Innenseiten."
        )
    output = normalize_mcf_save_path(destination)
    folder = output.parent / mcf_folder_name(output)
    if folder.exists() and not folder.is_dir():
        raise ExportError(f"Bilderordner existiert schon als Datei: {folder}")
    assets = McfAssetStore(folder)
    resolved = sources if sources is not None else export_sources(snapshot)
    turns = rotations if rotations is not None else export_rotations(snapshot)
    write_fotobook(
        output,
        cover,
        interiors,
        title=snapshot.title or cover.title,
        sources=resolved,
        rotations=turns,
        assets=assets,
        progress=progress,
    )
    written = (output, *tuple(assets.written))
    return ExportResult(output_path=output, files_written=written)
