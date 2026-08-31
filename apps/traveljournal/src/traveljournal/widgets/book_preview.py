"""Flip-through Travelbook preview (cover, then double-page spreads)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from PySide6.QtCore import QRect, QRectF, QSize, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPaintEvent,
    QPalette,
    QPen,
    QPixmap,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from travelcore.export.catalog import load_page_layout
from travelcore.export.stats import trip_summary_metrics
from travelcore.geo.catalog import Country, country_at, get_country
from travelcore.media.gallery import SORT_REJECTED
from travelcore.timeline.types import TimelineEntry, TimelinePhoto, TimelineSection, TimelineSnapshot
from traveljournal.widgets.svg_pixmaps import svg_pixmap, svg_renderer

_STAGE_MARGIN = 20
_SPREAD_GUTTER = 8
_KIND_LABELS = {"day": "Tag", "stay": "Aufenthalt", "movement": "Transfer"}
_PAGE_BG = "#f7f4ee"
_PAGE_FG = "#1a2744"
_NAVY_BG = "#1a2744"
_NAVY_FG = "#f4f7fb"
_NAVY_MUTED = "#9ec9b8"
_PAGE_MUTED = "#5c6b7a"
_ACCENT = "#2c9a8f"
_SHAPE_FILL = "#b8c1ce"
_SHAPE_SECTION = "#8b95a5"
_SHAPE_WIDTH_RATIO = 0.88
_NAME_FLAG = QSize(18, 14)
_SECTION_FLAG = QSize(22, 16)
_LOCATOR_MAX_H = 128
_COVER_MAX_H = 200
_NOTES_BOX = "#e4dfd6"
_SPAN_TRACK = "#cfc8bc"


def _paint(widget: QWidget, background: str, foreground: str) -> None:
    """Force readable page colors; the app-wide QWidget rule would otherwise stay dark."""

    widget.setAutoFillBackground(True)
    widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    palette = widget.palette()
    fill = QColor(background)
    ink = QColor(foreground)
    for role in (
        QPalette.ColorRole.Window,
        QPalette.ColorRole.Base,
        QPalette.ColorRole.Button,
        QPalette.ColorRole.AlternateBase,
    ):
        palette.setColor(role, fill)
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        palette.setColor(role, ink)
    widget.setPalette(palette)
    widget.setStyleSheet(f"background-color: {background}; color: {foreground}; border: none;")


def _ink(
    label: QLabel,
    color: str,
    *,
    background: str | None = None,
    point_size: int | None = None,
    bold: bool = False,
) -> None:
    palette = label.palette()
    palette.setColor(QPalette.ColorRole.WindowText, QColor(color))
    palette.setColor(QPalette.ColorRole.Text, QColor(color))
    if background is None:
        label.setAutoFillBackground(False)
        fill = "transparent"
    else:
        label.setAutoFillBackground(True)
        palette.setColor(QPalette.ColorRole.Window, QColor(background))
        palette.setColor(QPalette.ColorRole.Base, QColor(background))
        fill = background
    label.setPalette(palette)
    font = label.font()
    if point_size is not None:
        font.setPointSize(point_size)
    font.setBold(bold)
    label.setFont(font)
    label.setStyleSheet(f"background-color: {fill}; color: {color}; border: none;")


def _clear_layout(layout: QVBoxLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()


def _fit_rect(available: QRect, aspect: float) -> QRectF:
    if available.width() < 1 or available.height() < 1 or aspect <= 0:
        return QRectF()
    box_aspect = available.width() / available.height()
    if box_aspect > aspect:
        height = float(available.height())
        width = height * aspect
    else:
        width = float(available.width())
        height = width / aspect
    x = available.x() + (available.width() - width) / 2
    y = available.y() + (available.height() - height) / 2
    return QRectF(x, y, width, height)


class _CountrySilhouette(QWidget):
    """Light-gray country outline, scaled to the column."""

    def __init__(self, country: Country, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("bookCountryMark")
        _paint(self, _NAVY_BG, _NAVY_FG)
        policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self.setMinimumHeight(28)
        self._shape = svg_renderer(country.shape_svg, fill=_SHAPE_FILL)
        box = self._shape.viewBoxF()
        self._aspect = box.height() / box.width() if box.width() > 0 and box.height() > 0 else 1.0

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        inner = max(width - 8, 8) * _SHAPE_WIDTH_RATIO
        natural = inner * self._aspect
        capped = min(natural, max(width - 8, 8) * 1.2)
        return max(28, int(capped) + 4)

    def sizeHint(self) -> QSize:  # noqa: N802
        width = 96
        return QSize(width, self.heightForWidth(width))

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        area = self.rect().adjusted(4, 2, -4, -2)
        if area.width() < 8 or area.height() < 8 or not self._shape.isValid():
            return
        shape_area = QRect(
            area.x() + round(area.width() * (1 - _SHAPE_WIDTH_RATIO) / 2),
            area.y(),
            max(8, round(area.width() * _SHAPE_WIDTH_RATIO)),
            area.height(),
        )
        fitted = _fit_rect(shape_area, 1 / self._aspect if self._aspect else 1.0)
        if fitted.width() < 4 or fitted.height() < 4:
            return
        self._shape.render(painter, fitted)


class _SectionLocator(QWidget):
    """Cream-page country outline with an optional GPS pin."""

    def __init__(
        self,
        country: Country,
        *,
        latitude: float | None = None,
        longitude: float | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("bookSectionLocator")
        _paint(self, _PAGE_BG, _PAGE_FG)
        policy = QSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self.setMaximumWidth(240)
        self.setMinimumHeight(48)
        self.setMaximumHeight(_LOCATOR_MAX_H)
        self._latitude = latitude
        self._longitude = longitude
        self._shape = svg_renderer(country.shape_svg, fill=_SHAPE_SECTION)
        box = self._shape.viewBoxF()
        self._aspect = box.height() / box.width() if box.width() > 0 and box.height() > 0 else 1.0

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        inner = max(width - 4, 8)
        natural = inner * self._aspect
        return max(48, min(int(natural) + 4, _LOCATOR_MAX_H))

    def sizeHint(self) -> QSize:  # noqa: N802
        width = 160
        return QSize(width, self.heightForWidth(width))

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        area = self.rect().adjusted(2, 2, -2, -2)
        if area.width() < 8 or area.height() < 8 or not self._shape.isValid():
            return
        fitted = _fit_rect(area, 1 / self._aspect if self._aspect else 1.0)
        if fitted.width() < 4 or fitted.height() < 4:
            return
        self._shape.render(painter, fitted)
        self._paint_pin(painter, fitted)

    def _paint_pin(self, painter: QPainter, fitted: QRectF) -> None:
        if self._latitude is None or self._longitude is None:
            return
        box = self._shape.viewBoxF()
        if box.width() <= 0 or box.height() <= 0:
            return
        svg_x, svg_y = _lonlat_to_svg(self._latitude, self._longitude, box)
        if (
            svg_x < box.x()
            or svg_x > box.x() + box.width()
            or svg_y < box.y()
            or svg_y > box.y() + box.height()
        ):
            return
        x = fitted.x() + (svg_x - box.x()) / box.width() * fitted.width()
        y = fitted.y() + (svg_y - box.y()) / box.height() * fitted.height()
        radius = max(3.5, min(fitted.width(), fitted.height()) * 0.035)
        painter.setPen(QPen(QColor("#ffffff"), max(1.2, radius * 0.35)))
        painter.setBrush(QBrush(QColor(_ACCENT)))
        painter.drawEllipse(QRectF(x - radius, y - radius, radius * 2, radius * 2))


def _lonlat_to_svg(latitude: float, longitude: float, box: QRectF) -> tuple[float, float]:
    x = longitude
    y = -latitude
    right = box.x() + box.width()
    if x < box.x() and x + 360.0 <= right + 1:
        x += 360.0
    elif x > right and x - 360.0 >= box.x() - 1:
        x -= 360.0
    return x, y


def _format_book_dates(started_at: datetime | None, ended_at: datetime | None) -> str:
    """Section intro dates: ``01.01.1900`` or ``01.01.1900 bis 22.02.1900``."""

    start = started_at
    end = ended_at or started_at
    if start is None:
        return ""
    start_day = start.date()
    end_day = end.date() if end is not None else start_day
    if start_day == end_day:
        return start_day.strftime("%d.%m.%Y")
    return f"{start_day.strftime('%d.%m.%Y')} bis {end_day.strftime('%d.%m.%Y')}"


class _SectionCover(QLabel):
    """Titelbild next to the country block, letterboxed in the photo's aspect ratio."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("bookSectionCover")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setLineWidth(0)
        self.setMargin(0)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self.setMinimumHeight(48)
        self.setMaximumHeight(_COVER_MAX_H)
        self._source = QPixmap()
        _paint(self, _PAGE_BG, _PAGE_FG)

    def set_photo(self, path: Path | None) -> None:
        if path is None or not path.is_file():
            self._source = QPixmap()
            self.clear()
            self.hide()
            self.updateGeometry()
            return
        pixmap = QPixmap(str(path))
        self._source = pixmap
        self.setVisible(not pixmap.isNull())
        self.updateGeometry()
        self._apply()

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return not self._source.isNull()

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        if self._source.isNull() or self._source.width() < 1:
            return 48
        height = round(width * self._source.height() / self._source.width())
        return max(48, min(height, _COVER_MAX_H))

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._apply()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(_PAGE_BG))
        pixmap = self.pixmap()
        if pixmap is None or pixmap.isNull():
            return
        x = self.rect().x() + (self.width() - pixmap.width()) // 2
        y = self.rect().y() + (self.height() - pixmap.height()) // 2
        painter.drawPixmap(x, y, pixmap)

    def _apply(self) -> None:
        if self._source.isNull():
            self.clear()
            return
        size = self.size()
        if size.width() < 8 or size.height() < 8:
            return
        self.setPixmap(
            self._source.scaled(
                size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )


def _cover_crop(pixmap: QPixmap, size: QSize) -> QPixmap:
    if pixmap.isNull() or size.width() < 1 or size.height() < 1:
        return QPixmap()
    scaled = pixmap.scaled(
        size,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    x = max(0, (scaled.width() - size.width()) // 2)
    y = max(0, (scaled.height() - size.height()) // 2)
    return scaled.copy(x, y, size.width(), size.height())


class _TripSpanBar(QWidget):
    """Trip-duration bar; the date badge sits on this section's place in the journey."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("bookTripSpan")
        _paint(self, _PAGE_BG, _PAGE_FG)
        self.setMinimumHeight(36)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._label = ""
        self._start = 0.0
        self._end = 0.0

    def set_span(self, label: str, start: float, end: float) -> None:
        self._label = label
        self._start = max(0.0, min(1.0, start))
        self._end = max(self._start, min(1.0, end))
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = self.width()
        height = self.height()
        if width < 8 or height < 8:
            return
        mid_y = height / 2
        painter.setPen(QPen(QColor(_SPAN_TRACK), 2))
        painter.drawLine(0, round(mid_y), width, round(mid_y))
        x0 = self._start * width
        x1 = max(self._end * width, x0 + 6)
        painter.setPen(QPen(QColor(_ACCENT), 3))
        painter.drawLine(round(x0), round(mid_y), round(x1), round(mid_y))
        if not self._label:
            return
        font = QFont(self.font())
        font.setBold(True)
        font.setPointSize(9)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        pad_x = 10
        pad_y = 5
        text_w = metrics.horizontalAdvance(self._label) + pad_x * 2
        text_h = metrics.height() + pad_y * 2
        badge_x = x0
        if badge_x + text_w > width:
            badge_x = max(0.0, width - text_w)
        if badge_x < 0:
            badge_x = 0.0
        badge = QRectF(badge_x, (height - text_h) / 2, min(text_w, width), text_h)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(_ACCENT)))
        painter.drawRoundedRect(badge, 3, 3)
        painter.setPen(QPen(QColor("#ffffff")))
        painter.drawText(badge, int(Qt.AlignmentFlag.AlignCenter), self._label)


class _PhotoGrid(QWidget):
    """Section photos laid out with the photos_1–8 templates."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("bookPhotoGrid")
        _paint(self, _PAGE_BG, _PAGE_FG)
        self._cells: list[QLabel] = []
        self._slots: list[dict] = []
        self._pixmaps: list[QPixmap] = []

    def set_photos(self, paths: tuple[Path, ...]) -> None:
        for cell in self._cells:
            cell.deleteLater()
        self._cells = []
        self._slots = []
        self._pixmaps = []
        count = min(len(paths), 8)
        if count <= 0:
            return
        layout = load_page_layout(f"photos_{count}")
        raw_slots = layout.get("slots")
        slots = raw_slots if isinstance(raw_slots, list) else []
        for index, slot in enumerate(slots):
            if not isinstance(slot, dict):
                continue
            label = QLabel(self)
            label.setObjectName("bookGridCell")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            _paint(label, "#d9d3c7", _PAGE_FG)
            path = paths[index] if index < len(paths) else None
            pixmap = QPixmap(str(path)) if path is not None and path.is_file() else QPixmap()
            self._slots.append(slot)
            self._pixmaps.append(pixmap)
            self._cells.append(label)
            label.show()
        self._place()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._place()

    def _place(self) -> None:
        width = self.width()
        height = self.height()
        if width < 8 or height < 8:
            return
        for label, slot, pixmap in zip(self._cells, self._slots, self._pixmaps, strict=True):
            x = int(width * float(slot.get("x", 0)) / 100)
            y = int(height * float(slot.get("y", 0)) / 100)
            cell_w = max(1, int(width * float(slot.get("w", 100)) / 100))
            cell_h = max(1, int(height * float(slot.get("h", 100)) / 100))
            label.setGeometry(x, y, cell_w, cell_h)
            if pixmap.isNull():
                label.clear()
                continue
            label.setPixmap(_cover_crop(pixmap, QSize(cell_w, cell_h)))


class _CountryStackItem(QWidget):
    """Outline, then uppercase name with a small flag after it."""

    def __init__(self, country: Country, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("bookCountryItem")
        _paint(self, _NAVY_BG, _NAVY_FG)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(_CountrySilhouette(country), 0)
        caption = QWidget()
        _paint(caption, _NAVY_BG, _NAVY_FG)
        caption_row = QHBoxLayout(caption)
        caption_row.setContentsMargins(0, 0, 0, 0)
        caption_row.setSpacing(6)
        name = QLabel(country.name_de.upper())
        name.setObjectName("bookCountryName")
        name.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        name.setWordWrap(True)
        _ink(name, _NAVY_FG, background=_NAVY_BG, point_size=9, bold=True)
        flag = QLabel()
        flag.setObjectName("bookCountryFlag")
        flag.setFixedSize(_NAME_FLAG)
        flag.setPixmap(svg_pixmap(country.flag_svg, _NAME_FLAG))
        caption_row.addStretch(1)
        caption_row.addWidget(name, 0)
        caption_row.addWidget(flag, 0)
        caption_row.addStretch(1)
        layout.addWidget(caption, 0)


def fitted_sheet_size(
    available: QSize,
    page_width_mm: float,
    page_height_mm: float,
    *,
    page_count: int = 1,
    gutter: int = _SPREAD_GUTTER,
) -> QSize:
    """Largest single-page size that fits ``page_count`` sheets into ``available``."""

    if (
        available.width() < 1
        or available.height() < 1
        or page_count < 1
        or page_width_mm <= 0
        or page_height_mm <= 0
    ):
        return QSize(0, 0)
    aspect = page_width_mm / page_height_mm
    extra = gutter * (page_count - 1)
    height = float(available.height())
    width = height * aspect
    if page_count * width + extra <= available.width():
        return QSize(max(1, round(width)), max(1, round(height)))
    width = (available.width() - extra) / page_count
    if width < 1:
        return QSize(0, 0)
    height = width / aspect
    return QSize(max(1, round(width)), max(1, round(height)))


@dataclass(frozen=True, slots=True)
class BookLeaf:
    """One flip position: a cover sheet or a verso/recto spread."""

    kind: str
    indicator: str
    variant: str = "content"
    left_kicker: str = ""
    left_title: str = ""
    left_detail: str = ""
    right_kicker: str = ""
    right_title: str = ""
    right_detail: str = ""
    left_image: Path | None = None
    right_image: Path | None = None
    countries: tuple[str, ...] = ()
    metrics: tuple[tuple[str, str], ...] = ()
    country: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    notes: str = ""
    dates: str = ""
    span_start: float = 0.0
    span_end: float = 0.0
    photos: tuple[Path, ...] = ()


def leaves_from_snapshot(snapshot: TimelineSnapshot | None) -> list[BookLeaf]:
    """Front matter plus one intro spread per published section."""

    title = (snapshot.title if snapshot is not None else "").strip() or "Reise"
    entries = snapshot.published_entries() if snapshot is not None else ()
    section_count = len(entries)
    numbered = 2 + 2 * section_count
    cover_image = _first_cover(entries)
    year = _year(entries)
    trip_start, trip_end = _trip_dates(snapshot)
    leaves = [
        BookLeaf(
            kind="cover",
            indicator="Cover",
            right_kicker=str(year) if year else "",
            right_title=title.upper(),
            right_image=cover_image,
        ),
        BookLeaf(
            kind="spread",
            variant="title",
            indicator="Titelseite",
            right_title=title,
        ),
        BookLeaf(
            kind="spread",
            variant="summary",
            indicator=_spread_indicator(1, numbered),
            countries=snapshot.countries if snapshot is not None else (),
            metrics=trip_summary_metrics(snapshot),
            right_kicker="Karte",
            right_title="Satellitenkarte",
            right_detail="statisches Bild der Route",
            right_image=cover_image,
        ),
    ]
    for index, entry in enumerate(entries):
        page = 3 + 2 * index
        section = entry.section
        heading = _entry_title(entry)
        dates = ""
        notes = ""
        image = None
        iso = None
        latitude = None
        longitude = None
        span_start = 0.0
        span_end = 0.0
        photos: tuple[Path, ...] = ()
        if section is not None:
            dates = _format_book_dates(section.started_at, section.ended_at)
            notes = (section.notes or "").strip()
            image = _section_cover(entry)
            photos = _section_photos(entry)
            span_start, span_end = _span_fracs(
                section.started_at,
                section.ended_at,
                trip_start,
                trip_end,
            )
            found, latitude, longitude = _section_place(
                section,
                snapshot.countries if snapshot is not None else (),
            )
            iso = found.iso2 if found is not None else None
        leaves.append(
            BookLeaf(
                kind="spread",
                variant="section",
                indicator=_spread_indicator(page, numbered),
                left_kicker=_KIND_LABELS.get(entry.card_kind, "Abschnitt"),
                left_title=heading,
                left_image=image,
                notes=notes,
                dates=dates,
                span_start=span_start,
                span_end=span_end,
                country=iso,
                latitude=latitude,
                longitude=longitude,
                photos=photos,
            )
        )
    return leaves


def _year(entries: tuple[TimelineEntry, ...]) -> int | None:
    for entry in entries:
        started = entry.section.started_at if entry.section is not None else None
        if started is not None:
            return started.year
    return None


def _entry_title(entry: TimelineEntry) -> str:
    section = entry.section
    if section is not None and (section.title or "").strip():
        return section.title.strip()
    return _KIND_LABELS.get(entry.card_kind, "Abschnitt")


def _section_cover(entry: TimelineEntry) -> Path | None:
    section = entry.section
    if section is None:
        return None
    cover_id = section.cover_source_file_id
    if cover_id is not None:
        for item in section.items:
            if item.source_file_id == cover_id:
                return item.thumbnail_path
    for item in section.items:
        if item.file_kind == "photo":
            return item.thumbnail_path
    if section.items:
        return section.items[0].thumbnail_path
    return None


def _first_cover(entries: tuple[TimelineEntry, ...]) -> Path | None:
    for entry in entries:
        path = _section_cover(entry)
        if path is not None:
            return path
    return None


def _spread_indicator(first: int, total: int) -> str:
    return f"{first}–{first + 1}/{total}"


def _trip_dates(snapshot: TimelineSnapshot | None) -> tuple[date | None, date | None]:
    if snapshot is None:
        return None, None
    start = snapshot.start_date
    end = snapshot.end_date
    starts: list[date] = []
    ends: list[date] = []
    for entry in snapshot.published_entries():
        section = entry.section
        if section is None:
            continue
        if section.started_at is not None:
            starts.append(section.started_at.date())
        if section.ended_at is not None:
            ends.append(section.ended_at.date())
        elif section.started_at is not None:
            ends.append(section.started_at.date())
    if start is None and starts:
        start = min(starts)
    if end is None and ends:
        end = max(ends)
    if start is not None and end is not None and end < start:
        return end, start
    return start, end


def _span_fracs(
    started_at: datetime | None,
    ended_at: datetime | None,
    trip_start: date | None,
    trip_end: date | None,
) -> tuple[float, float]:
    if trip_start is None or trip_end is None:
        return 0.0, 0.0
    total = (trip_end - trip_start).days
    if total <= 0:
        return 0.0, 1.0
    start_day = started_at.date() if started_at is not None else trip_start
    end_day = ended_at.date() if ended_at is not None else start_day
    start_day = min(max(start_day, trip_start), trip_end)
    end_day = min(max(end_day, trip_start), trip_end)
    return (start_day - trip_start).days / total, (end_day - trip_start).days / total


def _section_photos(entry: TimelineEntry) -> tuple[Path, ...]:
    section = entry.section
    if section is None:
        return ()
    photos = [item for item in section.items if _is_book_photo(item)]
    ordered: list[TimelinePhoto] = []
    cover_id = section.cover_source_file_id
    if cover_id is not None:
        ordered.extend(item for item in photos if item.source_file_id == cover_id)
    ordered.extend(item for item in photos if item.source_file_id != cover_id)
    paths: list[Path] = []
    for item in ordered[:8]:
        if item.thumbnail_path:
            paths.append(item.thumbnail_path)
    return tuple(paths)


def _is_book_photo(item: TimelinePhoto) -> bool:
    return item.file_kind == "photo" and item.sort_status != SORT_REJECTED


def _section_place(
    section: TimelineSection,
    trip_countries: tuple[str, ...],
) -> tuple[Country | None, float | None, float | None]:
    pos = _section_position(section)
    if pos is not None:
        found = country_at(pos[0], pos[1], preferred=trip_countries)
        return found, pos[0], pos[1]
    if len(trip_countries) == 1:
        return get_country(trip_countries[0]), None, None
    return None, None, None


def _section_position(section: TimelineSection) -> tuple[float, float] | None:
    if section.pin_latitude is not None and section.pin_longitude is not None:
        return (section.pin_latitude, section.pin_longitude)
    cover_id = section.cover_source_file_id
    if cover_id is not None:
        for item in section.items:
            if item.source_file_id == cover_id:
                pos = _item_position(item)
                if pos is not None:
                    return pos
    for item in section.items:
        pos = _item_position(item)
        if pos is not None:
            return pos
    return None


def _item_position(item: TimelinePhoto) -> tuple[float, float] | None:
    if item.display_latitude is not None and item.display_longitude is not None:
        return (item.display_latitude, item.display_longitude)
    if item.gps_latitude is not None and item.gps_longitude is not None:
        return (item.gps_latitude, item.gps_longitude)
    return None


class _PageSheet(QFrame):
    def __init__(self, parent: QWidget | None = None, *, cover: bool = False) -> None:
        super().__init__(parent)
        self.setObjectName("bookCover" if cover else "bookPage")
        self._path: Path | None = None
        self._center_title = QLabel("")
        page_bg = _NAVY_BG if cover else _PAGE_BG
        page_fg = _NAVY_FG if cover else _PAGE_FG
        _paint(self, page_bg, page_fg)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._stack = QStackedWidget()
        _paint(self._stack, page_bg, page_fg)
        outer.addWidget(self._stack)

        standard = QWidget()
        _paint(standard, page_bg, page_fg)
        layout = QVBoxLayout(standard)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        self.kicker = QLabel("")
        self.kicker.setObjectName("bookKicker")
        self.kicker.setWordWrap(True)
        self.title = QLabel("")
        self.title.setObjectName("bookPageTitle")
        self.title.setWordWrap(True)
        self.image = QLabel("")
        self.image.setObjectName("bookImage")
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setMinimumHeight(0)
        self.image.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.detail = QLabel("")
        self.detail.setObjectName("bookDetail")
        self.detail.setWordWrap(True)
        _ink(self.kicker, _NAVY_MUTED if cover else _PAGE_MUTED, background=page_bg, point_size=10)
        _ink(self.title, page_fg, background=page_bg, point_size=16, bold=True)
        _ink(self.detail, page_fg, background=page_bg, point_size=11)
        _paint(self.image, "#12151c" if cover else "#d9d3c7", page_fg)
        layout.addWidget(self.kicker)
        layout.addWidget(self.title)
        layout.addWidget(self.image, 1)
        layout.addWidget(self.detail)

        blank = QWidget()
        _paint(blank, _PAGE_BG, _PAGE_FG)

        title_page = QWidget()
        _paint(title_page, _PAGE_BG, _PAGE_FG)
        title_layout = QVBoxLayout(title_page)
        title_layout.setContentsMargins(28, 28, 28, 28)
        title_layout.addStretch(1)
        self._center_title.setObjectName("bookCenteredTitle")
        self._center_title.setWordWrap(True)
        self._center_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _ink(self._center_title, _PAGE_FG, background=_PAGE_BG, point_size=22, bold=True)
        title_layout.addWidget(self._center_title)
        title_layout.addStretch(1)

        summary = QWidget()
        _paint(summary, _PAGE_BG, _PAGE_FG)
        summary_layout = QHBoxLayout(summary)
        summary_layout.setContentsMargins(0, 0, 0, 0)
        summary_layout.setSpacing(0)
        countries_panel = QFrame()
        countries_panel.setObjectName("bookCountries")
        _paint(countries_panel, _NAVY_BG, _NAVY_FG)
        countries_layout = QVBoxLayout(countries_panel)
        countries_layout.setContentsMargins(16, 20, 16, 20)
        countries_layout.setSpacing(10)
        countries_kicker = QLabel("LÄNDER")
        countries_kicker.setObjectName("bookCountriesKicker")
        self._countries_host = QVBoxLayout()
        self._countries_host.setContentsMargins(0, 0, 0, 0)
        self._countries_host.setSpacing(10)
        _ink(countries_kicker, _NAVY_MUTED, background=_NAVY_BG, point_size=10, bold=True)
        countries_layout.addWidget(countries_kicker)
        countries_layout.addLayout(self._countries_host, 1)
        metrics_panel = QFrame()
        metrics_panel.setObjectName("bookMetrics")
        _paint(metrics_panel, _PAGE_BG, _PAGE_FG)
        metrics_layout = QVBoxLayout(metrics_panel)
        metrics_layout.setContentsMargins(20, 20, 20, 20)
        metrics_layout.setSpacing(12)
        heading = QLabel("REISEÜBERSICHT")
        heading.setObjectName("bookMetricsHeading")
        _ink(heading, _PAGE_MUTED, background=_PAGE_BG, point_size=10, bold=True)
        metrics_layout.addWidget(heading)
        self._metrics_host = QVBoxLayout()
        self._metrics_host.setSpacing(14)
        metrics_layout.addLayout(self._metrics_host, 1)
        summary_layout.addWidget(countries_panel, 2)
        summary_layout.addWidget(metrics_panel, 3)

        section = QWidget()
        _paint(section, _PAGE_BG, _PAGE_FG)
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(22, 20, 22, 16)
        section_layout.setSpacing(10)
        header = QWidget()
        _paint(header, _PAGE_BG, _PAGE_FG)
        header_row = QHBoxLayout(header)
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(12)
        self._section_place_left = QWidget()
        self._section_place_left.setObjectName("bookSectionPlaceLeft")
        _paint(self._section_place_left, _PAGE_BG, _PAGE_FG)
        self._section_place_left.setMinimumWidth(96)
        self._section_place_left.setMaximumWidth(240)
        self._section_place_left.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding
        )
        left_wrap = QVBoxLayout(self._section_place_left)
        left_wrap.setContentsMargins(0, 0, 0, 0)
        left_wrap.setSpacing(0)
        left_wrap.addStretch(1)
        place_block = QWidget()
        _paint(place_block, _PAGE_BG, _PAGE_FG)
        place_block.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        block_layout = QVBoxLayout(place_block)
        block_layout.setContentsMargins(0, 0, 0, 0)
        block_layout.setSpacing(6)
        self._section_locator_column = QWidget()
        self._section_locator_column.setObjectName("bookSectionLocatorColumn")
        _paint(self._section_locator_column, _PAGE_BG, _PAGE_FG)
        self._section_locator_column.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred
        )
        self._section_locator_host = QVBoxLayout(self._section_locator_column)
        self._section_locator_host.setContentsMargins(0, 0, 0, 0)
        self._section_locator_host.setSpacing(0)
        country_row = QWidget()
        _paint(country_row, _PAGE_BG, _PAGE_FG)
        country_layout = QHBoxLayout(country_row)
        country_layout.setContentsMargins(0, 0, 0, 0)
        country_layout.setSpacing(8)
        self._section_flag = QLabel()
        self._section_flag.setObjectName("bookSectionFlag")
        self._section_flag.setFixedSize(_SECTION_FLAG)
        self._section_country = QLabel("")
        self._section_country.setObjectName("bookSectionCountry")
        self._section_country.setWordWrap(True)
        _ink(self._section_country, _PAGE_FG, background=_PAGE_BG, point_size=10, bold=True)
        country_layout.addWidget(self._section_flag, 0)
        country_layout.addWidget(self._section_country, 1)
        self._section_country_row = country_row
        block_layout.addWidget(self._section_locator_column, 0)
        block_layout.addWidget(country_row, 0)
        left_wrap.addWidget(place_block, 0)
        left_wrap.addStretch(1)
        header_row.addWidget(self._section_place_left, 0)
        self._section_cover = _SectionCover()
        header_row.addWidget(self._section_cover, 1)
        self._section_header = header
        section_layout.addWidget(header, 0)
        self._section_title = QLabel("")
        self._section_title.setObjectName("bookSectionTitle")
        self._section_title.setWordWrap(True)
        _ink(self._section_title, _PAGE_FG, background=_PAGE_BG, point_size=16, bold=True)
        self._section_dates = QLabel("")
        self._section_dates.setObjectName("bookSectionDates")
        self._section_dates.setWordWrap(True)
        _ink(self._section_dates, _PAGE_MUTED, background=_PAGE_BG, point_size=11)
        self._section_notes_box = QFrame()
        self._section_notes_box.setObjectName("bookNotesBox")
        _paint(self._section_notes_box, _NOTES_BOX, _PAGE_FG)
        self._section_notes_box.setMinimumHeight(88)
        self._section_notes_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        notes_layout = QVBoxLayout(self._section_notes_box)
        notes_layout.setContentsMargins(12, 10, 12, 10)
        self._section_notes = QLabel("")
        self._section_notes.setObjectName("bookSectionNotes")
        self._section_notes.setWordWrap(True)
        self._section_notes.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._section_notes.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        _ink(self._section_notes, _PAGE_FG, background=_NOTES_BOX, point_size=10)
        notes_layout.addWidget(self._section_notes, 1)
        section_layout.addWidget(self._section_title, 0)
        section_layout.addWidget(self._section_dates, 0)
        section_layout.addWidget(self._section_notes_box, 1)
        self._section_span = _TripSpanBar()
        section_layout.addWidget(self._section_span, 0)

        photos = _PhotoGrid()
        self._photo_grid = photos

        for page in (standard, blank, title_page, summary, section, photos):
            page.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            self._stack.addWidget(page)

    def set_blank(self) -> None:
        self._path = None
        self._stack.setCurrentIndex(1)

    def set_centered_title(self, title: str) -> None:
        self._path = None
        self._center_title.setText(title.strip() or "Reise")
        _ink(self._center_title, _PAGE_FG, background=_PAGE_BG, point_size=22, bold=True)
        self._stack.setCurrentIndex(2)

    def set_summary(self, countries: tuple[str, ...], metrics: tuple[tuple[str, str], ...]) -> None:
        self._path = None
        _clear_layout(self._countries_host)
        rows: list[Country] = []
        unknown: list[str] = []
        for token in countries:
            country = get_country(token)
            if country is None:
                unknown.append(token)
            else:
                rows.append(country)
        if rows:
            for country in rows:
                self._countries_host.addStretch(1)
                self._countries_host.addWidget(_CountryStackItem(country), 0)
            self._countries_host.addStretch(1)
        if unknown:
            leftover = QLabel("\n".join(unknown))
            leftover.setObjectName("bookCountriesList")
            leftover.setWordWrap(True)
            leftover.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
            _ink(leftover, _NAVY_FG, background=_NAVY_BG, point_size=12, bold=True)
            self._countries_host.addWidget(leftover, 0)
        if not rows and not unknown:
            empty = QLabel("Noch keine Länder.\nAuf der Projektseite eintragen.")
            empty.setObjectName("bookCountriesList")
            empty.setWordWrap(True)
            empty.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
            _ink(empty, _NAVY_FG, background=_NAVY_BG, point_size=14, bold=True)
            self._countries_host.addWidget(empty, 1)
        while self._metrics_host.count():
            item = self._metrics_host.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for value, label in metrics:
            block = QWidget()
            _paint(block, _PAGE_BG, _PAGE_FG)
            block_layout = QVBoxLayout(block)
            block_layout.setContentsMargins(0, 0, 0, 0)
            block_layout.setSpacing(2)
            value_label = QLabel(value)
            value_label.setObjectName("bookMetricValue")
            caption = QLabel(label)
            caption.setObjectName("bookMetricCaption")
            _ink(value_label, _PAGE_FG, background=_PAGE_BG, point_size=22, bold=True)
            _ink(caption, _PAGE_MUTED, background=_PAGE_BG, point_size=11)
            block_layout.addWidget(value_label)
            block_layout.addWidget(caption)
            self._metrics_host.addWidget(block)
        self._metrics_host.addStretch(1)
        self._stack.setCurrentIndex(3)

    def set_section_intro(
        self,
        *,
        country: str | None,
        latitude: float | None,
        longitude: float | None,
        title: str,
        notes: str,
        dates: str,
        span_start: float,
        span_end: float,
        cover: Path | None,
    ) -> None:
        self._path = None
        _clear_layout(self._section_locator_host)
        resolved = get_country(country)
        if resolved is not None:
            locator = _SectionLocator(resolved, latitude=latitude, longitude=longitude)
            self._section_locator_host.addWidget(
                locator,
                0,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
            )
            locator.raise_()
            self._section_flag.setPixmap(svg_pixmap(resolved.flag_svg, _SECTION_FLAG))
            self._section_country.setText(resolved.name_de.upper())
            self._section_country_row.show()
            self._section_place_left.show()
        else:
            self._section_flag.clear()
            self._section_country.setText("")
            self._section_country_row.hide()
            self._section_place_left.hide()
        self._section_cover.set_photo(cover)
        self._section_header.setVisible(resolved is not None or self._section_cover.isVisible())
        self._section_title.setText(title.strip().upper())
        self._section_dates.setText(dates)
        self._section_dates.setVisible(bool(dates.strip()))
        self._section_notes.setText(notes)
        self._section_notes_box.show()
        self._section_span.set_span(dates, span_start, span_end)
        self._stack.setCurrentIndex(4)

    def set_photos(self, paths: tuple[Path, ...]) -> None:
        self._path = None
        self._photo_grid.set_photos(paths)
        self._stack.setCurrentIndex(5)

    def set_content(
        self,
        *,
        kicker: str,
        title: str,
        detail: str,
        image: Path | None,
    ) -> None:
        self.kicker.setText(kicker)
        self.title.setText(title)
        self.detail.setText(detail)
        self._path = image
        self._stack.setCurrentIndex(0)
        self._fit_image()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._fit_image()

    def _fit_image(self) -> None:
        if self._stack.currentIndex() != 0:
            return
        target = self.image
        if self._path is None or not self._path.is_file():
            target.clear()
            target.setText("")
            return
        pixmap = QPixmap(str(self._path))
        if pixmap.isNull():
            target.clear()
            return
        size = target.size()
        if size.width() < 8 or size.height() < 8:
            return
        target.setPixmap(_cover_crop(pixmap, size))


class _BookStage(QWidget):
    """Canvas that recenters sheets whenever the remaining window area changes."""

    def __init__(self, relayout: Callable[[], None], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("bookStage")
        self._relayout = relayout

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._relayout()


class BookPreview(QWidget):
    """Travelbook stage that letterboxes pages into the remaining window."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("bookPreview")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._leaves: list[BookLeaf] = []
        self._index = 0
        self._page_width_mm = 210.0
        self._page_height_mm = 297.0

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        flip = QHBoxLayout()
        flip.setContentsMargins(0, 0, 0, 0)
        flip.setSpacing(8)
        self._prev = QPushButton("←")
        self._next = QPushButton("→")
        for button in (self._prev, self._next):
            button.setObjectName("bookFlip")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFixedWidth(44)
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self._prev.clicked.connect(lambda: self._go(self._index - 1))
        self._next.clicked.connect(lambda: self._go(self._index + 1))
        self._stage = _BookStage(self._fit_sheets)
        self._stage.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._verso = _PageSheet(self._stage)
        self._recto = _PageSheet(self._stage)
        self._cover = _PageSheet(self._stage, cover=True)
        flip.addWidget(self._prev)
        flip.addWidget(self._stage, 1)
        flip.addWidget(self._next)
        root.addLayout(flip, 1)

        self._indicator = QLabel("Cover")
        self._indicator.setObjectName("bookIndicator")
        self._indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self._indicator)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def mousePressEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        super().mousePressEvent(event)

    def set_page_size(self, width_mm: float, height_mm: float) -> None:
        self._page_width_mm = width_mm
        self._page_height_mm = height_mm
        self._fit_sheets()

    def set_leaves(self, leaves: list[BookLeaf]) -> None:
        self._leaves = leaves or [BookLeaf(kind="cover", indicator="Cover", right_title="Keine Seiten")]
        self._go(0)

    def keyPressEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        key = event.key()
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Backspace):
            self._go(self._index - 1)
            return
        if key in (Qt.Key.Key_Right, Qt.Key.Key_Space):
            self._go(self._index + 1)
            return
        if key == Qt.Key.Key_Home:
            self._go(0)
            return
        if key == Qt.Key.Key_End:
            self._go(len(self._leaves) - 1)
            return
        super().keyPressEvent(event)

    def _go(self, index: int) -> None:
        if not self._leaves:
            return
        self._index = max(0, min(index, len(self._leaves) - 1))
        leaf = self._leaves[self._index]
        is_cover = leaf.kind == "cover"
        if is_cover:
            self._cover.set_content(
                kicker=leaf.right_kicker,
                title=leaf.right_title,
                detail=leaf.right_detail,
                image=leaf.right_image,
            )
        else:
            if leaf.variant == "title":
                self._verso.set_blank()
                self._recto.set_centered_title(leaf.right_title)
            elif leaf.variant == "summary":
                self._verso.set_summary(leaf.countries, leaf.metrics)
                self._recto.set_content(
                    kicker=leaf.right_kicker,
                    title=leaf.right_title,
                    detail=leaf.right_detail,
                    image=leaf.right_image,
                )
            elif leaf.variant == "section":
                self._verso.set_section_intro(
                    country=leaf.country,
                    latitude=leaf.latitude,
                    longitude=leaf.longitude,
                    title=leaf.left_title,
                    notes=leaf.notes,
                    dates=leaf.dates,
                    span_start=leaf.span_start,
                    span_end=leaf.span_end,
                    cover=leaf.left_image,
                )
                self._recto.set_photos(leaf.photos)
            else:
                self._verso.set_content(
                    kicker=leaf.left_kicker,
                    title=leaf.left_title,
                    detail=leaf.left_detail,
                    image=leaf.left_image,
                )
                self._recto.set_content(
                    kicker=leaf.right_kicker,
                    title=leaf.right_title,
                    detail=leaf.right_detail,
                    image=leaf.right_image,
                )
        self._indicator.setText(leaf.indicator)
        at_start = self._index == 0
        at_end = self._index == len(self._leaves) - 1
        self._prev.setEnabled(not at_start)
        self._next.setEnabled(not at_end)
        self._fit_sheets()

    def _current_is_cover(self) -> bool:
        return bool(self._leaves) and self._leaves[self._index].kind == "cover"

    def _fit_sheets(self) -> None:
        if getattr(self, "_cover", None) is None:
            return
        inner = self._stage.rect().adjusted(_STAGE_MARGIN, _STAGE_MARGIN, -_STAGE_MARGIN, -_STAGE_MARGIN)
        is_cover = self._current_is_cover()
        page_count = 1 if is_cover or not self._leaves else 2
        size = fitted_sheet_size(
            inner.size(),
            self._page_width_mm,
            self._page_height_mm,
            page_count=page_count,
            gutter=_SPREAD_GUTTER,
        )
        if size.width() < 1 or size.height() < 1:
            self._cover.hide()
            self._verso.hide()
            self._recto.hide()
            return
        total_w = page_count * size.width() + _SPREAD_GUTTER * (page_count - 1)
        x0 = inner.x() + max(0, (inner.width() - total_w) // 2)
        y0 = inner.y() + max(0, (inner.height() - size.height()) // 2)
        if is_cover:
            self._cover.setGeometry(x0, y0, size.width(), size.height())
            self._cover.show()
            self._verso.hide()
            self._recto.hide()
        else:
            self._verso.setGeometry(x0, y0, size.width(), size.height())
            self._recto.setGeometry(x0 + size.width() + _SPREAD_GUTTER, y0, size.width(), size.height())
            self._verso.show()
            self._recto.show()
            self._cover.hide()
