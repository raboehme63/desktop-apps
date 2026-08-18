from travelcore.export.base import Exporter
from travelcore.export.cewe import CeweExporter
from travelcore.export.html import HtmlExporter
from travelcore.export.latex import LatexExporter
from travelcore.export.pdf import PdfExporter
from travelcore.maps import MapBackend
from travelcore.metadata.provider import TIME_SOURCE_PRIORITY, MetadataProvider
from travelcore.timeline.ranking import RankingStrategy


def test_exporters_share_interface() -> None:
    for cls in (HtmlExporter, PdfExporter, LatexExporter, CeweExporter):
        assert issubclass(cls, Exporter)


def test_time_source_priority_has_exif_first() -> None:
    assert TIME_SOURCE_PRIORITY[0] == "exif_datetime_original"
    assert TIME_SOURCE_PRIORITY[-1] == "filesystem_mtime"


def test_protocols_are_importable() -> None:
    assert MetadataProvider is not None
    assert RankingStrategy is not None
    assert MapBackend is not None
