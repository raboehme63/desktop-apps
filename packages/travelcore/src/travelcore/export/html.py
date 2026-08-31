"""HTML exporter (implemented in phase 8 with Jinja2 templates).

First path: Ausgabetyp Travelbook × Format HTML — a static flipbook.
The book is composed in edit mode (project ``travelbook.json``) before export:
one intro spread per published section, extra spreads with page layouts.
Section media and tracks are assigned by drag-and-drop from a thumbnail tray.
Travelbook (interaktiv) is a separate HTML renderer: the read-only map website.

Hidden timeline sections (``TimelineSnapshot.published_entries``) are omitted,
matching the map.
"""

from __future__ import annotations

from travelcore.export.base import NotImplementedExporter


class HtmlExporter(NotImplementedExporter):
    name = "html"
