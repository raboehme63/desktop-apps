"""HTML exporter (implemented in phase 8 with Jinja2 templates)."""

from __future__ import annotations

from travelcore.export.base import NotImplementedExporter


class HtmlExporter(NotImplementedExporter):
    name = "html"
