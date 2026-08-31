"""Export backends. HTML is implemented in phase 8; others stay abstract.

Ausgabetyp (Travelbook, Jahrbuch, …) ist ein JSON-Template.
Ausgabeformat (HTML, PDF, …) ist der Renderer. Nicht jede Zelle der Matrix
ist erlaubt; der erste Pfad ist Travelbook × HTML.
"""

from travelcore.export.base import Exporter, ExportResult
from travelcore.export.catalog import first_path, load_page_layout, load_product, supports
from travelcore.export.cewe import CeweExporter
from travelcore.export.document import (
    DOCUMENT_FILENAME,
    TravelbookDocument,
    load_or_create,
    save_document,
    sync_document,
)
from travelcore.export.html import HtmlExporter
from travelcore.export.latex import LatexExporter
from travelcore.export.pdf import PdfExporter, PdfRenderer

__all__ = [
    "DOCUMENT_FILENAME",
    "CeweExporter",
    "ExportResult",
    "Exporter",
    "HtmlExporter",
    "LatexExporter",
    "PdfExporter",
    "PdfRenderer",
    "TravelbookDocument",
    "first_path",
    "load_or_create",
    "load_page_layout",
    "load_product",
    "save_document",
    "supports",
    "sync_document",
]
