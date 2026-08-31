"""Flip-through Travelbook preview (cover, then double-page spreads)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPalette, QPixmap, QResizeEvent
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

from travelcore.export.stats import trip_summary_metrics
from travelcore.geo.catalog import Country, get_country
from travelcore.timeline.sections import format_card_dates
from travelcore.timeline.types import TimelineEntry, TimelineSnapshot
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
_SHAPE_FILL = "#b8c1ce"
_SHAPE_WIDTH_RATIO = 0.88
_NAME_FLAG = QSize(18, 14)


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


def leaves_from_snapshot(snapshot: TimelineSnapshot | None) -> list[BookLeaf]:
    """Front matter plus one intro spread per published section."""

    title = (snapshot.title if snapshot is not None else "").strip() or "Reise"
    entries = snapshot.published_entries() if snapshot is not None else ()
    section_count = len(entries)
    total = 4 + 2 * section_count
    cover_image = _first_cover(entries)
    year = _year(entries)
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
            indicator=f"2/{total}",
            right_title=title,
        ),
        BookLeaf(
            kind="spread",
            variant="summary",
            indicator=f"3–4/{total}",
            countries=snapshot.countries if snapshot is not None else (),
            metrics=trip_summary_metrics(snapshot),
            right_kicker="Karte",
            right_title="Satellitenkarte",
            right_detail="statisches Bild der Route",
            right_image=cover_image,
        ),
    ]
    for index, entry in enumerate(entries):
        page = 5 + 2 * index
        section = entry.section
        heading = _entry_title(entry)
        dates = ""
        youtube = ""
        image = None
        if section is not None:
            dates = format_card_dates(section.started_at, section.ended_at)
            if section.youtube_urls:
                youtube = f"{len(section.youtube_urls)} YouTube-Link(s), inkl. QR"
            image = _section_cover(entry)
        leaves.append(
            BookLeaf(
                kind="spread",
                indicator=f"{page}–{page + 1}/{total}",
                left_kicker=_KIND_LABELS.get(entry.card_kind, "Abschnitt"),
                left_title=heading,
                left_detail="\n".join(part for part in (dates, youtube) if part),
                left_image=image,
                right_kicker="1 Foto",
                right_title="Medienseite",
                right_detail="Template photos_1 — per Drag-and-drop befüllen",
                right_image=image,
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

        for page in (standard, blank, title_page, summary):
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
        if self._path is None or not self._path.is_file():
            self.image.clear()
            self.image.setText("")
            return
        pixmap = QPixmap(str(self._path))
        if pixmap.isNull():
            self.image.clear()
            return
        target = self.image.size()
        if target.width() < 8 or target.height() < 8:
            return
        self.image.setPixmap(
            pixmap.scaled(
                target,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
        )


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
