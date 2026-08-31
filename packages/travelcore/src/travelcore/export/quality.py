"""PDF raster quality presets (screen, home print, magazine).

Magazine quality targets a good color laser: 300 dpi (print-standard 2× 150 lpi)
and JPEG 4:4:4 so photo pages keep chroma. Originals are never written.
"""

from __future__ import annotations

from dataclasses import dataclass

from travelcore.exceptions import ExportError

QUALITY_SCREEN = "screen"
QUALITY_PRINT = "print"
QUALITY_MAGAZINE = "magazine"
DEFAULT_QUALITY_ID = QUALITY_PRINT


@dataclass(frozen=True, slots=True)
class PdfQuality:
    id: str
    label_de: str
    note_de: str
    dpi: float
    jpeg_quality: int
    jpeg_subsampling: int | None = None


PDF_QUALITIES: tuple[PdfQuality, ...] = (
    PdfQuality(
        id=QUALITY_SCREEN,
        label_de="Bildschirm",
        note_de="150 dpi — schnell, klein, für Bildschirm und Versand.",
        dpi=150.0,
        jpeg_quality=85,
    ),
    PdfQuality(
        id=QUALITY_PRINT,
        label_de="Druck",
        note_de="250 dpi — guter Farblaser oder Tintenstrahl zu Hause.",
        dpi=250.0,
        jpeg_quality=92,
    ),
    PdfQuality(
        id=QUALITY_MAGAZINE,
        label_de="Beste Qualität",
        note_de="300 dpi, volle Farbauflösung — Fotodruck auf einem guten Farblaser.",
        dpi=300.0,
        jpeg_quality=95,
        jpeg_subsampling=0,
    ),
)


def list_pdf_qualities() -> tuple[PdfQuality, ...]:
    return PDF_QUALITIES


def pdf_quality(quality_id: str | None) -> PdfQuality:
    wanted = (quality_id or DEFAULT_QUALITY_ID).strip() or DEFAULT_QUALITY_ID
    for item in PDF_QUALITIES:
        if item.id == wanted:
            return item
    raise ExportError(f"Unbekannte PDF-Qualität '{wanted}'.")
