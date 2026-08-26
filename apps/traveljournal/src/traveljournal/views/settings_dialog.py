"""Project settings dialog. Original media files are never written."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from travelcore.project_settings import EXPORT_FORMATS, ProjectSettings

_FORMAT_LABELS = {
    "html": "HTML (Reisebericht)",
    "pdf": "PDF",
    "latex": "LaTeX",
    "cewe": "CEWE (Platzhalter)",
}


class SettingsDialog(QDialog):
    def __init__(self, settings: ProjectSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Projekteinstellungen")
        self.resize(560, 620)
        self._settings = settings.model_copy(deep=True)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        intro = QLabel(
            "Die Werte werden in settings.toml im Projektordner gespeichert. "
            "Originaldateien werden nicht verändert."
        )
        intro.setObjectName("pageSubtitle")
        intro.setWordWrap(True)
        root.addWidget(intro)

        paths = QGroupBox("Originaldateien")
        paths_form = QFormLayout(paths)
        row = QHBoxLayout()
        self.source_edit = QLineEdit(self._settings.paths.source_root or "")
        self.source_edit.setPlaceholderText("Wurzelverzeichnis der Originale")
        browse = QPushButton("Ordner wählen")
        browse.clicked.connect(self._browse_source)
        row.addWidget(self.source_edit, 1)
        row.addWidget(browse)
        paths_form.addRow("Wurzelverzeichnis", row)
        hint = QLabel(
            "Wenn der Ordner verschoben wurde, hier den neuen Pfad eintragen. "
            "Die Pfade im Index werden umgeschrieben, die Dateien selbst nicht."
        )
        hint.setObjectName("pageSubtitle")
        hint.setWordWrap(True)
        paths_form.addRow("", hint)
        root.addWidget(paths)

        export = QGroupBox("Export")
        export_form = QFormLayout(export)
        self.format_combo = QComboBox()
        for key in EXPORT_FORMATS:
            self.format_combo.addItem(_FORMAT_LABELS[key], key)
        index = max(self.format_combo.findData(self._settings.export.default_format), 0)
        self.format_combo.setCurrentIndex(index)
        export_form.addRow("Standardformat", self.format_combo)
        root.addWidget(export)

        matching = QGroupBox("Zuordnung")
        matching_form = QFormLayout(matching)
        self.delta_spin = QSpinBox()
        self.delta_spin.setRange(1, 86_400)
        self.delta_spin.setSuffix(" s")
        self.delta_spin.setValue(self._settings.matching.gps_match_max_delta_seconds)
        matching_form.addRow("GPS-Zeitfenster", self.delta_spin)
        self.timezone_edit = QLineEdit(self._settings.matching.default_timezone or "")
        self.timezone_edit.setPlaceholderText("z. B. Europe/Berlin (optional)")
        matching_form.addRow("Standard-Zeitzone", self.timezone_edit)
        root.addWidget(matching)

        extra = QGroupBox("Karte und Weitere")
        extra_form = QFormLayout(extra)
        self.map_combo = QComboBox()
        self.map_combo.setEditable(True)
        self.map_combo.addItems(["leaflet", "offline"])
        self.map_combo.setCurrentText(self._settings.placeholders.map_provider)
        extra_form.addRow("Kartenanbieter", self.map_combo)
        self.language_edit = QLineEdit(self._settings.placeholders.journal_language)
        extra_form.addRow("Tagebuchsprache", self.language_edit)
        note = QLabel(
            "leaflet: OpenStreetMap-Kacheln mit lateinischen bzw. deutschen Namen "
            "(Netzwerk, openstreetmap.de). offline: nur Track und Marker. "
            "Tagebuchsprache folgt in einer späteren Phase."
        )
        note.setObjectName("pageSubtitle")
        note.setWordWrap(True)
        extra_form.addRow("", note)
        root.addWidget(extra)

        performance = QGroupBox("Leistung")
        performance_form = QFormLayout(performance)
        self.workers_spin = QSpinBox()
        self.workers_spin.setRange(0, 64)
        self.workers_spin.setSpecialValueText("Automatisch (Kerne − 1)")
        self.workers_spin.setValue(self._settings.performance.worker_count)
        performance_form.addRow("CPU-Worker", self.workers_spin)
        workers_hint = QLabel(
            "Hash, Metadaten und Vorschaubilder laufen in mehreren Prozessen. "
            "0 nutzt alle Kerne minus einen für die Oberfläche. SQLite schreibt weiter nur in einem Prozess."
        )
        workers_hint.setObjectName("pageSubtitle")
        workers_hint.setWordWrap(True)
        performance_form.addRow("", workers_hint)
        root.addWidget(performance)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Speichern")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Abbrechen")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _browse_source(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Wurzelverzeichnis der Originale")
        if directory:
            self.source_edit.setText(directory)

    def result_settings(self) -> ProjectSettings:
        settings = self._settings.model_copy(deep=True)
        root = self.source_edit.text().strip()
        settings.paths.source_root = root or None
        data = self.format_combo.currentData()
        if isinstance(data, str):
            settings.export.default_format = data  # type: ignore[assignment]
        settings.matching.gps_match_max_delta_seconds = int(self.delta_spin.value())
        zone = self.timezone_edit.text().strip()
        settings.matching.default_timezone = zone or None
        settings.placeholders.map_provider = self.map_combo.currentText().strip() or "leaflet"
        language = self.language_edit.text().strip() or "de"
        settings.placeholders.journal_language = language
        settings.performance.worker_count = int(self.workers_spin.value())
        return settings
