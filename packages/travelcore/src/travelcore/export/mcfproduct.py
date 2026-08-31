"""One CEWE product for the Travelbook MCF export (Fotobuch Groß, Hochformat).

Dimensions follow the public community description of classic ``.mcf`` files
(units of 0.1 mm). Product codes are the well-known ALB82 A4/Groß portrait
album used by open MCF readers. A Creator update may require adjusting
``PRODUCT_NAME`` after opening an empty book of that SKU.
"""

from __future__ import annotations

from travelcore.export.geometry import Frame

PAGE_SIZE_ID = "a4-portrait"
PRODUCT_NAME = "ALB82"
ARTICLE_NAME = "CEWE FOTOBUCH Groß"
MCF_VERSION = "4.0"

# Travelbook A4 is 210×297 mm; CEWE Groß is about 21×28 cm.
PAGE_WIDTH_MM = 210.0
PAGE_HEIGHT_MM = 280.0
MCF_PER_MM = 10.0
PAGE_WIDTH_MCF = int(PAGE_WIDTH_MM * MCF_PER_MM)
PAGE_HEIGHT_MCF = int(PAGE_HEIGHT_MM * MCF_PER_MM)

MIN_CONTENT_PAGES = 26
MAX_CONTENT_PAGES = 202
GRAPHIC_DPI = 250.0

# Layout boxes in page percent — same proportions as ``paint.py``.
COVER_YEAR = Frame(8.0, 6.0, 24.0, 6.0)
COVER_TITLE = Frame(8.0, 13.0, 84.0, 16.0)
COVER_PHOTO = Frame(0.0, 32.0, 100.0, 68.0)
COVER_BG = Frame(0.0, 0.0, 100.0, 100.0)

TITLE_TEXT = Frame(12.0, 35.0, 76.0, 30.0)

JOURNAL_TITLE = Frame(8.0, 8.0, 84.0, 10.0)
JOURNAL_BODY = Frame(8.0, 20.0, 84.0, 72.0)

INTRO_COUNTRY = Frame(7.0, 7.0, 35.0, 32.0)
INTRO_COVER = Frame(44.0, 7.0, 49.0, 28.0)
INTRO_TITLE = Frame(7.0, 40.0, 86.0, 8.0)
INTRO_DATES = Frame(7.0, 49.0, 86.0, 5.0)
INTRO_NOTES = Frame(7.0, 55.0, 86.0, 30.0)
INTRO_SPAN = Frame(7.0, 88.0, 86.0, 7.0)

SUMMARY_COUNTRIES = Frame(0.0, 0.0, 40.0, 100.0)
SUMMARY_HEADING = Frame(44.0, 5.0, 52.0, 6.0)
SUMMARY_METRIC_VALUE = Frame(44.0, 14.0, 52.0, 6.0)
SUMMARY_METRIC_LABEL = Frame(44.0, 20.0, 52.0, 4.0)
SUMMARY_METRIC_STEP = 12.0

MAP_KICKER = Frame(6.0, 4.0, 40.0, 4.0)
MAP_TITLE = Frame(6.0, 8.5, 60.0, 6.0)
MAP_IMAGE = Frame(6.0, 16.0, 88.0, 74.0)

PAGE_NUMBER = Frame(88.0, 94.0, 8.0, 4.0)
PAGE_NUMBER_LEFT = Frame(4.0, 94.0, 8.0, 4.0)


def padded_content_count(n: int) -> int:
    """CEWE Groß: at least 26 pages, and ``4k + 2`` so the inside back cover is odd."""

    count = max(int(n), MIN_CONTENT_PAGES)
    if count > MAX_CONTENT_PAGES:
        return count
    remainder = count % 4
    if remainder == 2:
        return count
    return min(MAX_CONTENT_PAGES, count + ((2 - remainder) % 4))


def frame_to_mcf(frame: Frame, *, origin_left: float = 0.0) -> tuple[float, float, float, float]:
    """Percent frame → MCF ``(left, top, width, height)`` on a spread."""

    left = origin_left + PAGE_WIDTH_MCF * float(frame.x) / 100.0
    top = PAGE_HEIGHT_MCF * float(frame.y) / 100.0
    width = PAGE_WIDTH_MCF * float(frame.w) / 100.0
    height = PAGE_HEIGHT_MCF * float(frame.h) / 100.0
    return (left, top, width, height)
