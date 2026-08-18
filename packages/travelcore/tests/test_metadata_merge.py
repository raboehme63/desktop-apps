from travelcore.metadata.composite import merge_metadata
from travelcore.metadata.provider import CapturedTime, GeoPosition, MediaMetadata
from travelcore.metadata.time import parse_exif_datetime, with_source


def test_merge_fills_missing_fields_only() -> None:
    primary = MediaMetadata(
        captured=None,
        position=None,
        camera=None,
        width=32,
        height=24,
    )
    extra = MediaMetadata(
        captured=with_source(parse_exif_datetime("2025:05:15 08:20:00"), "exif_datetime_original"),
        position=GeoPosition(46.0, 11.0, 200.0, "exif", 1.0, None),
        camera="Sony A7",
        width=6000,
        height=4000,
    )
    merged = merge_metadata(primary, extra)
    assert merged.captured is not None
    assert isinstance(merged.captured, CapturedTime)
    assert merged.position is not None
    assert merged.camera == "Sony A7"
    assert merged.width == 32
    assert merged.height == 24
