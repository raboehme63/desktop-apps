"""Interactive project map. Original media files are never written."""

from __future__ import annotations

from PySide6.QtCore import QUrl, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from travelcore.exceptions import ProjectError
from travelcore.maps import FLIGHT_LINE_MIN_ZOOM, MapScene
from traveljournal.services.workspace import Workspace

try:
    from PySide6.QtWebEngineCore import QWebEngineSettings
    from PySide6.QtWebEngineWidgets import QWebEngineView
except ImportError:  # pragma: no cover - optional Qt WebEngine
    QWebEngineView = None  # type: ignore[misc, assignment]
    QWebEngineSettings = None  # type: ignore[misc, assignment]


class MapView(QWidget):
    status_message = Signal(str)

    def __init__(self, workspace: Workspace, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.workspace = workspace
        self._web: QWebEngineView | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(12)

        title = QLabel("Karte")
        title.setObjectName("pageTitle")
        self._subtitle = QLabel(
            "Tracks und IGC-Flugspuren als Linie, Fotos als Marker. "
            "Flugtracks erscheinen ab Zoomstufe 10; Start und Landung sind immer sichtbar."
        )
        self._subtitle.setObjectName("pageSubtitle")
        self._subtitle.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(self._subtitle)

        toolbar = QHBoxLayout()
        refresh = QPushButton("Karte aktualisieren")
        refresh.clicked.connect(self.refresh)
        toolbar.addWidget(refresh)
        toolbar.addStretch(1)
        root.addLayout(toolbar)

        self._stack = QStackedWidget()
        self._message = QLabel("Bitte ein Projekt öffnen.")
        self._message.setObjectName("pageSubtitle")
        self._message.setWordWrap(True)
        self._stack.addWidget(self._message)
        self._web_host = QWidget()
        host_layout = QVBoxLayout(self._web_host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        self._stack.addWidget(self._web_host)
        root.addWidget(self._stack, 1)

    def refresh(self) -> None:
        if self.workspace.current is None:
            self._show_message("Bitte ein Projekt öffnen.")
            return
        try:
            scene, html_path = self.workspace.render_map()
        except ProjectError as exc:
            self._show_message(str(exc))
            return
        self._subtitle.setText(_summary(scene))
        if scene.empty or html_path is None:
            self._show_message("Keine GPS-Daten im Index. Fotos mit Ort, GPX- oder IGC-Tracks importieren.")
            self.status_message.emit("Karte: keine GPS-Daten")
            return
        if QWebEngineView is None:
            self._show_message(f"Qt WebEngine ist nicht installiert. Die Karte liegt unter:\n{html_path}")
            return
        self._ensure_web()
        assert self._web is not None
        self._web.setUrl(QUrl.fromLocalFile(str(html_path.resolve())))
        self._stack.setCurrentWidget(self._web_host)
        self.status_message.emit(_summary(scene))

    def _ensure_web(self) -> None:
        if self._web is not None or QWebEngineView is None:
            return
        self._web = QWebEngineView(self._web_host)
        settings = self._web.settings()
        if QWebEngineSettings is not None:
            settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
            settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        layout = self._web_host.layout()
        if layout is not None:
            layout.addWidget(self._web)

    def _show_message(self, text: str) -> None:
        self._message.setText(text)
        self._stack.setCurrentWidget(self._message)


def _summary(scene: MapScene) -> str:
    photos = sum(1 for item in scene.markers if item.kind in {"photo", "video"})
    stays = sum(1 for item in scene.markers if item.kind == "overnight")
    places = sum(1 for item in scene.markers if item.kind == "place")
    flights = sum(1 for item in scene.polylines if item.kind == "flight")
    tracks = len(scene.polylines) - flights
    return (
        f"{tracks} Tracks, {flights} Flugtracks (IGC ab Zoom {FLIGHT_LINE_MIN_ZOOM}), "
        f"{photos} Medien mit Ort, {stays} Übernachtungen, {places} Orte. "
        "Klick auf einen Marker zeigt die Vorschau, sofern vorhanden."
    )
