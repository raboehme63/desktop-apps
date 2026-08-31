"""HTML exporter (implemented in phase 8 with Jinja2 templates).

Hidden timeline sections (``TimelineSnapshot.published_entries``) are omitted,
matching the map.
"""

from __future__ import annotations

from travelcore.export.base import NotImplementedExporter


class HtmlExporter(NotImplementedExporter):
    name = "html"
