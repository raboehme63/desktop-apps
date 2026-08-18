"""LaTeX exporter (phase 8+). Compilation to PDF remains optional."""

from __future__ import annotations

from travelcore.export.base import NotImplementedExporter


class LatexExporter(NotImplementedExporter):
    name = "latex"
