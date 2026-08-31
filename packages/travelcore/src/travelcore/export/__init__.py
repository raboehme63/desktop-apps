"""Export backends. HTML is implemented in phase 8; others stay abstract.

Ausgabetyp (Travelbook, Jahrbuch, …) ist ein JSON-Template.
Ausgabeformat (HTML, PDF, …) ist der Renderer. Nicht jede Zelle der Matrix
ist erlaubt; der erste Pfad ist Travelbook × HTML.
"""

from travelcore.export.base import Exporter, ExportResult
from travelcore.export.catalog import first_path, load_page_layout, load_product, supports
from travelcore.export.cewe import CeweExporter
from travelcore.export.html import HtmlExporter
from travelcore.export.latex import LatexExporter
from travelcore.export.pdf import PdfExporter, PdfRenderer

__all__ = [
    "CeweExporter",
    "ExportResult",
    "Exporter",
    "HtmlExporter",
    "LatexExporter",
    "PdfExporter",
    "PdfRenderer",
    "first_path",
    "load_page_layout",
    "load_product",
    "supports",
]
