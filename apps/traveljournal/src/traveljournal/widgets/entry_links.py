"""Dialogs for YouTube and DHV-Leonardo links on a day or section."""

from __future__ import annotations

import html

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QMouseEvent, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from travelcore.exceptions import ProjectError
from travelcore.timeline.links import (
    is_igc_filename,
    normalize_youtube_url,
    youtube_thumbnail_url,
)
from travelcore.timeline.types import TimelinePhoto

_THUMB_SIZE = (160, 90)
_NETWORK: QNetworkAccessManager | None = None


def _network() -> QNetworkAccessManager:
    global _NETWORK
    if _NETWORK is None:
        _NETWORK = QNetworkAccessManager()
    return _NETWORK


class YouTubeThumbLabel(QLabel):
    def __init__(self, url: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._url = url
        self._reply: QNetworkReply | None = None
        width, height = _THUMB_SIZE
        self.setFixedSize(width, height)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setObjectName("youtubeThumb")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(url)
        placeholder = QPixmap(width, height)
        placeholder.fill(Qt.GlobalColor.transparent)
        self.setPixmap(placeholder)
        thumb = youtube_thumbnail_url(url)
        if thumb:
            self._reply = _network().get(QNetworkRequest(QUrl(thumb)))
            self._reply.finished.connect(self._on_loaded)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._url:
            QDesktopServices.openUrl(QUrl(self._url))
        super().mouseReleaseEvent(event)

    def _on_loaded(self) -> None:
        reply = self._reply
        self._reply = None
        if reply is None:
            return
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                return
            pixmap = QPixmap()
            if not pixmap.loadFromData(reply.readAll()):
                return
            self.setPixmap(
                pixmap.scaled(
                    self.size(),
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        finally:
            reply.deleteLater()


class YouTubeThumbsRow(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(8)
        self._layout.addStretch(1)

    def set_urls(self, urls: list[str] | tuple[str, ...]) -> None:
        while self._layout.count() > 1:
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for url in urls:
            self._layout.insertWidget(self._layout.count() - 1, YouTubeThumbLabel(url, self))
        self.setVisible(bool(urls))


class YouTubeLinksDialog(QDialog):
    def __init__(self, urls: tuple[str, ...] | list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("YouTube-Links")
        self.resize(640, 460)
        self._urls: list[str] = []
        for item in urls:
            try:
                normalized = normalize_youtube_url(item)
            except ProjectError:
                continue
            if normalized and normalized not in self._urls:
                self._urls.append(normalized)
        root = QVBoxLayout(self)
        intro = QLabel(
            "YouTube-Link einfügen und hinzufügen. Die Vorschau kommt von YouTube. "
            "Übernehmen speichert erst in der Ansicht; dauerhaft wird es mit Speichern."
        )
        intro.setWordWrap(True)
        intro.setObjectName("pageSubtitle")
        root.addWidget(intro)
        add_row = QHBoxLayout()
        self._url_edit = QLineEdit(self)
        self._url_edit.setPlaceholderText("https://youtu.be/…")
        self._url_edit.returnPressed.connect(self._add_current)
        add_button = QPushButton("Hinzufügen", self)
        add_button.clicked.connect(self._add_current)
        add_row.addWidget(self._url_edit, 1)
        add_row.addWidget(add_button)
        root.addLayout(add_row)
        self._list_host = QWidget(self)
        self._list_layout = QVBoxLayout(self._list_host)
        self._list_layout.setContentsMargins(0, 0, 8, 0)
        self._list_layout.setSpacing(8)
        self._list_layout.addStretch(1)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._list_host)
        root.addWidget(scroll, 1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Übernehmen")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Abbrechen")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self._rebuild_rows()

    def urls(self) -> list[str]:
        return list(self._urls)

    def _add_current(self) -> None:
        raw = self._url_edit.text().strip()
        if not raw:
            return
        try:
            normalized = normalize_youtube_url(raw)
        except ProjectError as exc:
            QMessageBox.warning(self, "YouTube-Links", str(exc))
            return
        if not normalized:
            return
        if normalized in self._urls:
            self._url_edit.clear()
            return
        self._urls.append(normalized)
        self._url_edit.clear()
        self._rebuild_rows()

    def _remove_at(self, index: int) -> None:
        if 0 <= index < len(self._urls):
            del self._urls[index]
            self._rebuild_rows()

    def _rebuild_rows(self) -> None:
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for index, url in enumerate(self._urls):
            self._list_layout.insertWidget(index, self._make_row(index, url))

    def _make_row(self, index: int, url: str) -> QWidget:
        row = QWidget(self._list_host)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(YouTubeThumbLabel(url, row), 0, Qt.AlignmentFlag.AlignTop)
        text = QLabel(f'<a href="{html.escape(url, quote=True)}">{html.escape(url)}</a>', row)
        text.setObjectName("pageSubtitle")
        text.setWordWrap(True)
        text.setOpenExternalLinks(True)
        text.setTextFormat(Qt.TextFormat.RichText)
        text.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(text, 1)
        delete = QPushButton("Löschen", row)
        delete.clicked.connect(lambda _checked=False, at=index: self._remove_at(at))
        layout.addWidget(delete, 0, Qt.AlignmentFlag.AlignTop)
        return row


class LeonardoLinksDialog(QDialog):
    def __init__(
        self,
        flights: list[tuple[int, str, str]],
        extra_urls: tuple[str, ...] | list[str] = (),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("DHV-Leonardo")
        self.resize(560, 360 if flights else 260)
        root = QVBoxLayout(self)
        if flights:
            intro_text = (
                "Vorhandene IGC-Dateien können einen DHV-Leonardo-Link erhalten. "
                "Zusätzlich können Links ohne IGC eingetragen werden (ein Link je Zeile)."
            )
        else:
            intro_text = (
                "Dieser Eintrag enthält keine IGC-Datei. "
                "Du kannst trotzdem DHV-Leonardo-Links eintragen (ein Link je Zeile)."
            )
        intro = QLabel(intro_text)
        intro.setWordWrap(True)
        intro.setObjectName("pageSubtitle")
        root.addWidget(intro)
        self._edits: dict[int, QLineEdit] = {}
        if flights:
            group = QGroupBox("IGC-Dateien", self)
            form = QFormLayout(group)
            for source_id, filename, url in flights:
                edit = QLineEdit(url, group)
                edit.setPlaceholderText("https://de.dhv.de/dbnx/…")
                form.addRow(filename, edit)
                self._edits[source_id] = edit
            root.addWidget(group)
        extra_group = QGroupBox("Weitere Links (ohne IGC)" if flights else "DHV-Leonardo-Links", self)
        extra_layout = QVBoxLayout(extra_group)
        self._extra_edit = QPlainTextEdit("\n".join(extra_urls), extra_group)
        self._extra_edit.setPlaceholderText("https://de.dhv.de/dbnx/…")
        extra_layout.addWidget(self._extra_edit)
        root.addWidget(extra_group, 1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Speichern")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Abbrechen")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def values(self) -> dict[int, str]:
        return {source_id: edit.text().strip() for source_id, edit in self._edits.items()}

    def extra_urls(self) -> list[str]:
        return [line.strip() for line in self._extra_edit.toPlainText().splitlines() if line.strip()]


def igc_flights(items: tuple[TimelinePhoto, ...] | list[TimelinePhoto]) -> list[tuple[int, str, str]]:
    flights: list[tuple[int, str, str]] = []
    for item in items:
        if not is_igc_filename(item.filename):
            continue
        flights.append((item.source_file_id, item.filename, item.external_url or ""))
    return flights


def links_html(
    youtube: tuple[str, ...] | list[str],
    flights: list[tuple[int, str, str]],
    extra: tuple[str, ...] | list[str] = (),
) -> str:
    lines: list[str] = []
    for index, url in enumerate(youtube, start=1):
        href = html.escape(url, quote=True)
        label = html.escape(url)
        prefix = "YouTube" if len(youtube) == 1 else f"YouTube {index}"
        lines.append(f'<a href="{href}">{prefix}</a> — {label}')
    for _source_id, filename, url in flights:
        if not url:
            continue
        href = html.escape(url, quote=True)
        name = html.escape(filename)
        lines.append(f'<a href="{href}">DHV-Leonardo · {name}</a>')
    extras = list(extra)
    for index, url in enumerate(extras, start=1):
        href = html.escape(url, quote=True)
        label = html.escape(url)
        prefix = "DHV-Leonardo" if len(extras) == 1 else f"DHV-Leonardo {index}"
        lines.append(f'<a href="{href}">{prefix}</a> — {label}')
    return "<br/>".join(lines)
