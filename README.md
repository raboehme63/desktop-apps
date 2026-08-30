# Reisetagebuch

Windows-Desktop-Anwendung, die aus Fotos, Videos, GPS-Tracks und Textdateien
ein bearbeitbares digitales Reisetagebuch rekonstruiert.

Die Geschäftslogik liegt in der GUI-freien Bibliothek `travelcore`. Die
PySide6-Oberfläche `traveljournal` orchestriert nur Import, Bearbeitung und
Export. Dieselbe Bibliothek ist für eine spätere Anwendung `PhotoInspector`
vorgesehen (Dublettensuche, Qualitätsbewertung).

Aktueller Stand: **Phase 7** plus Medien-Pipeline, Software **R3.0.0**
(`Reisetagebuch R3.0.0` in der Titelleiste).

Die Anwendung importiert Medien, liest Metadaten und GPS-Tracks, erzeugt
Vorschaubilder, zeigt eine Karte (Titelbild-Kreise, Verbindungslinien mit
Verkehrssymbolen, Leiste, Cover-Zoom, Foto-Popup, Detail) und baut eine
bearbeitbare Timeline aus Tagen, Transfers und Aufenthalten (alle als
Abschnitte mit Mitgliedern). Nicht zugeordnete Medien liegen im Medienpool.
Auf der Medienseite stapeln echte Dubletten (SHA-256), gruppieren ähnliche
Fotos, eine Qualitätsampel bewertet die Technik, und eine Statistikleiste zählt den Bestand. Medieninspektor (Schlüsselfotos,
**Zur Karte**), Bewertungen für Fotos und Tracks, Anzeigedrehung, Drag & Drop,
Track-Vorschauen und Rückgängig/Wiederherstellen (Strg+Z / Strg+Y) gehören dazu.
HTML-Export folgt in Phase 8. Unechte Dubletten (pHash) bleiben offen.

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

## JSON nach GPX (Hilfsprogramm)

Polar-Trainings-JSON mit nichtleerer `routes`-Sektion (primäre `route.wayPoints`,
nicht `transitionRoute`) wird **nicht** von der App importiert. Das Skript
`scripts/json_routes_to_gpx.py` schreibt eine GPX-Datei **neben** die JSON-Datei
(gleiche Basis, Endung `.gpx`). Die JSON-Datei bleibt unverändert. JSON ohne
Routen wird übersprungen.

Genau eine Quelle angeben: `-f` **oder** `-d`. `-r` gilt nur mit `-d`.

```powershell
.\.venv\Scripts\python.exe scripts\json_routes_to_gpx.py -h
.\.venv\Scripts\python.exe scripts\json_routes_to_gpx.py -f D:\tracks\session.json
.\.venv\Scripts\python.exe scripts\json_routes_to_gpx.py -d D:\tracks
.\.venv\Scripts\python.exe scripts\json_routes_to_gpx.py -d D:\tracks -r
```

Kurzhilfe (`-h`):

```
usage: json_routes_to_gpx.py [-h] [-f DATEI] [-d VERZEICHNIS] [-r]

Erzeugt GPX-Tracks aus JSON-Dateien mit nichtleerer Routes-Sektion.

options:
  -h, --help      show this help message and exit
  -f DATEI        einzelne JSON-Datei
  -d VERZEICHNIS  Ordner mit JSON-Dateien
  -r              mit -d auch Unterverzeichnisse einbeziehen
```

`-f` gibt den GPX-Pfad aus oder `keine Routen: …`. `-d` schreibt einen Punkt
pro JSON-Datei und am Ende `JSON n, GPX m`.

Die erzeugte GPX kann anschließend wie jede andere Trackdatei importiert werden.

## Windows-Installer

Ein Setup für Endnutzer (ohne Python) wird mit Build-Skripten unter
`packaging/` erzeugt, ohne die Anwendung selbst zu ändern:

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

Details, Zip-Variante und Inno Setup: [packaging/README.md](packaging/README.md).
macOS ist kein Ziel.

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
- [Windows-Paketierung](packaging/README.md) — Installer, Zip, PyInstaller, Inno Setup

## Datenschutz

Alle Analysen laufen standardmäßig lokal. Fotos, GPS-Tracks und Reisedaten
werden nicht automatisch an externe Dienste übertragen.

Originaldateien werden niemals verändert.
