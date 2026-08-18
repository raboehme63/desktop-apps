# Reisetagebuch

Windows-Desktop-Anwendung, die aus Fotos, Videos, GPS-Tracks und Textdateien
ein bearbeitbares digitales Reisetagebuch rekonstruiert.

Die Geschäftslogik liegt in der GUI-freien Bibliothek `travelcore`. Die
PySide6-Oberfläche `traveljournal` orchestriert nur Import, Bearbeitung und
Export. Dieselbe Bibliothek ist für eine spätere Anwendung `PhotoInspector`
vorgesehen (Dublettensuche, Qualitätsbewertung).

Aktueller Stand: **Phase 6** (Karte).

## Voraussetzungen

- Windows 10/11
- Python 3.12

## Einrichtung

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\pip install -e packages/travelcore -e apps/traveljournal
.\.venv\Scripts\pip install pytest ruff
```

## Anwendung starten

```powershell
.\.venv\Scripts\python.exe -m traveljournal
```

## Tests ausführen

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Linting:

```powershell
.\.venv\Scripts\python.exe -m ruff check packages apps tests
.\.venv\Scripts\python.exe -m ruff format --check packages apps tests
```

## Dokumentation

- [Pflichtenheft](docs/pflichtenheft.md) — verbindliche Anforderungen
- [Konzept](docs/konzept.md) — Produktidee, Abläufe, Leitlinien
- [Architektur](docs/architecture.md) — Schichten, Projektordner, Phasen
- [Testdokumentation](docs/testdokumentation.md) — Strategie, Automatisierung, manuelle Fälle
- [Abhängigkeiten](docs/dependencies.md) — Bibliotheken, Versionen, Lizenzen

## Datenschutz

Alle Analysen laufen standardmäßig lokal. Fotos, GPS-Tracks und Reisedaten
werden nicht automatisch an externe Dienste übertragen.

Originaldateien werden niemals verändert.
