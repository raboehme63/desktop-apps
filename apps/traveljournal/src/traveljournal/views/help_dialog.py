"""Help dialog: transport symbols on Transfer connection lines."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from travelcore.timeline.symbols import TRANSPORT_SYMBOLS
from traveljournal.widgets.transport_icons import transport_badge_pixmap


class HelpDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("helpDialog")
        self.setWindowTitle("Hilfe")
        self.setMinimumSize(480, 420)
        self.resize(540, 620)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        title = QLabel("Verkehrsmittelsymbole")
        title.setObjectName("pageTitle")
        intro = QLabel(
            "Auf der Karte sitzt das Symbol auf der Verbindungslinie: "
            "weißes Piktogramm auf schwarzem Kreis, die Spitze zeigt in Fahrtrichtung. "
            "Am Transfer wählen Sie es je Zeile, an Tag und Aufenthalt unter "
            "„Verbindung zum nächsten Abschnitt“, wenn der nächste Eintrag kein Transfer ist "
            "(Gerade, Map-Track, Bogenlinie; oder „Keine Linie“, dann entfällt die Verbindung). "
            "Am Transfer gibt es zusätzlich Track aus den GPX-Mitgliedern des Abschnitts. "
            "Map-Track: GPX-Datei oder Google-Maps-Routenlink, abgelegt unter .MapTracks im Import-Ordner. "
            "Fitness- und IGC-Tracks holt man auf der Seite Import "
            "aus einer Activity-Datenbank (Dateiname, Standard activity.sqlite; "
            "Laden mit Zeitraum und Auswahl Activity-Tracks/Flüge, Neu laden gleicht ab) "
            "nach .ActivityTracks bzw. .IGCTracks. "
            "Unter Tracks trägt jede Spur den Chip Map, Act oder igc; "
            "die Vorschau liegt auf einem Leaflet-Kartenausschnitt. "
            "Scan und Synchronisieren nehmen sie mit (normale GPS-Dateien). "
            "Beim Maps-Link schlägt die App einen Namen vor, den man überschreiben kann. "
            "Gepunktete Systemlücken zwischen Spur, Gelenk und Cover haben kein Symbol."
        )
        intro.setObjectName("pageSubtitle")
        intro.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(intro)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("helpSymbolList")
        rows = QVBoxLayout(body)
        rows.setContentsMargins(0, 0, 8, 0)
        rows.setSpacing(10)
        for item in TRANSPORT_SYMBOLS:
            rows.addWidget(self._row(item.key, item.label, item.summary, body))
        rows.addStretch(1)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        close = buttons.button(QDialogButtonBox.StandardButton.Close)
        if close is not None:
            close.setText("Schließen")
        root.addWidget(buttons)

    def _row(self, key: str, label: str, summary: str, parent: QWidget) -> QWidget:
        frame = QFrame(parent)
        frame.setObjectName(f"helpSymbol-{key}")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(14)
        icon = QLabel(frame)
        icon.setFixedSize(48, 48)
        icon.setPixmap(transport_badge_pixmap(key, 48))
        icon.setObjectName("helpSymbolIcon")
        texts = QWidget(frame)
        text_layout = QVBoxLayout(texts)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)
        name = QLabel(label, texts)
        name.setObjectName("fieldCaption")
        explain = QLabel(summary, texts)
        explain.setObjectName("pageSubtitle")
        explain.setWordWrap(True)
        text_layout.addWidget(name)
        text_layout.addWidget(explain)
        layout.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(texts, 1)
        return frame
