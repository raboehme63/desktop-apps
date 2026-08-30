from datetime import UTC, date, datetime
from pathlib import Path

from travelcore.media.gallery import GalleryItem
from traveljournal.widgets.media_filter import (
    matches_date_range,
    matches_quality_filter,
    matches_rating_filter,
)


def _item(
    *,
    quality_light: str | None = None,
    sort_status: str | None = None,
    captured: datetime | None = datetime(2025, 6, 15, 10, 0, tzinfo=UTC),
) -> GalleryItem:
    return GalleryItem(
        source_file_id=1,
        path="foto.jpg",
        filename="foto.jpg",
        extension=".jpg",
        captured_at=captured,
        timezone_unknown=False,
        gps_latitude=None,
        gps_longitude=None,
        camera=None,
        is_favorite=sort_status == "favorite",
        used_in_journal=False,
        thumbnail_path=Path("."),
        sort_status=sort_status,
        quality_light=quality_light,
    )


def test_quality_filter_empty_keeps_all() -> None:
    item = _item(quality_light="red")
    assert matches_quality_filter(item, frozenset())
    assert matches_quality_filter(item, frozenset({"red"}))
    assert not matches_quality_filter(item, frozenset({"green", "yellow"}))
    assert matches_quality_filter(_item(), frozenset({"none"}))


def test_rating_filter_multi_select() -> None:
    fav = _item(sort_status="favorite")
    plain = _item()
    assert matches_rating_filter(fav, frozenset({"favorite", "reserve"}))
    assert not matches_rating_filter(plain, frozenset({"favorite", "reserve"}))
    assert matches_rating_filter(plain, frozenset({"none"}))


def test_date_range_inclusive() -> None:
    item = _item()
    assert matches_date_range(item, None, None)
    assert matches_date_range(item, date(2025, 6, 1), date(2025, 6, 30))
    assert not matches_date_range(item, date(2025, 7, 1), date(2025, 7, 31))
    assert not matches_date_range(_item(captured=None), date(2025, 1, 1), date(2025, 12, 31))
