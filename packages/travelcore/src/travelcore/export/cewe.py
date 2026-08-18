"""CEWE photobook placeholder.

The concrete CEWE project format will only be implemented after the target
file format has been examined technically and legally. No proprietary format
is reverse-engineered or guessed here.
"""

from __future__ import annotations

from travelcore.export.base import NotImplementedExporter


class CeweExporter(NotImplementedExporter):
    name = "cewe"
