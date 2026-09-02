"""Export backends. Interactive HTML writes a read-only map site; the book HTML is later.

Ausgabetyp (Travelbook, Jahrbuch, …) ist ein JSON-Template.
Ausgabeformat (HTML, PDF, …) ist der Renderer. Nicht jede Zelle der Matrix
ist erlaubt; der erste Pfad ist Travelbook × HTML. PDF (Travelbook) nutzt
den Raster-PdfRenderer.
"""

from travelcore.export.base import Exporter, ExportResult
from travelcore.export.catalog import first_path, load_page_layout, load_product, supports
from travelcore.export.cewe import CeweExporter, export_travelbook_mcf
from travelcore.export.document import (
    DOCUMENT_FILENAME,
    TravelbookDocument,
    load_or_create,
    save_document,
    sync_document,
)
from travelcore.export.html import HtmlExporter, export_travelbook_interactive
from travelcore.export.latex import LatexExporter
from travelcore.export.pdf import PdfExporter, PdfRenderer, export_travelbook_pdf
from travelcore.export.quality import DEFAULT_QUALITY_ID, list_pdf_qualities, pdf_quality

__all__ = [
    "DEFAULT_QUALITY_ID",
    "DOCUMENT_FILENAME",
    "CeweExporter",
    "ExportResult",
    "Exporter",
    "HtmlExporter",
    "LatexExporter",
    "PdfExporter",
    "PdfRenderer",
    "TravelbookDocument",
    "export_travelbook_interactive",
    "export_travelbook_mcf",
    "export_travelbook_pdf",
    "first_path",
    "list_pdf_qualities",
    "load_or_create",
    "load_page_layout",
    "load_product",
    "pdf_quality",
    "save_document",
    "supports",
    "sync_document",
]
