from travelcore.media.gallery import (
    SORT_FAVORITE,
    SORT_REJECTED,
    SORT_RESERVE,
    effective_sort_status,
)


def test_effective_sort_status_prefers_stored_value() -> None:
    assert effective_sort_status(SORT_RESERVE, True) == SORT_RESERVE
    assert effective_sort_status(SORT_REJECTED, False) == SORT_REJECTED
    assert effective_sort_status(SORT_FAVORITE, False) == SORT_FAVORITE


def test_effective_sort_status_falls_back_to_favorite_flag() -> None:
    assert effective_sort_status(None, True) == SORT_FAVORITE
    assert effective_sort_status(None, False) is None
    assert effective_sort_status("unknown", True) == SORT_FAVORITE
    assert effective_sort_status("unknown", False) is None
