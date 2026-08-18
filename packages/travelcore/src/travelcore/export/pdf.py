"""PDF export via a swappable renderer (HTML print engine or LaTeX).

PyMuPDF is not a required dependency. It may only be added after an explicit
license decision (AGPL vs commercial).
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from travelcore.export.base import NotImplementedExporter


class PdfRenderer(Protocol):
    def render(self, source: Path, destination: Path) -> Path:
        """Turn HTML or TeX into a PDF without coupling the exporter to one engine."""
        ...


class PdfExporter(NotImplementedExporter):
    name = "pdf"

    def __init__(self, renderer: PdfRenderer | None = None) -> None:
        self.renderer = renderer
