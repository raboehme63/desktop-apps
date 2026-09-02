# Reisetagebuch

Windows-Desktop-Anwendung, die aus Fotos, Videos, GPS-Tracks und Textdateien
ein bearbeitbares digitales Reisetagebuch rekonstruiert.

Die Geschäftslogik liegt in der GUI-freien Bibliothek `travelcore`. Die
PySide6-Oberfläche `traveljournal` orchestriert nur Import, Bearbeitung und
Export. Dieselbe Bibliothek ist für eine spätere Anwendung `PhotoInspector`
vorgesehen (Dublettensuche, Qualitätsbewertung).

Aktueller Stand: **Phase 7** plus Medien-Pipeline, Software **R3.3.0**
(`Reisetagebuch R3.3.0` in der Titelleiste). Abschnitte lassen sich in der
Timeline für Karte und Export ausblenden; **Speichern** ist sonst grau.
Auf der Projektseite wählt man bereiste Länder aus dem Katalog und setzt
Reise von–bis (vorbefüllt aus den Daten, danach editierbar).

Die Anwendung importiert Medien, liest Metadaten und GPS-Tracks, erzeugt
Vorschaubilder, zeigt eine Karte (Titelbild-Kreise, Verbindungslinien mit
Verkehrssymbolen, Leiste, Cover-Zoom, Foto-Popup, Detail mit **Flüge anzeigen**
und **Aktivitäten anzeigen**) und baut eine
bearbeitbare Timeline aus Tagen, Transfers und Aufenthalten (alle als
Abschnitte mit Mitgliedern). Nicht zugeordnete Medien liegen im Medienpool.
Auf der Medienseite stapeln echte Dubletten (SHA-256), gruppieren ähnliche
Fotos, **Filtern** schränkt nach Qualität, Zeitraum und Bewertung ein, eine
Qualitätsampel bewertet die Technik (Hover begründet gelb/rot), und eine
Statistikleiste zählt den Bestand. Der Thumbnail-Schieber gilt auch auf Import.
Medieninspektor (Schlüsselfotos,
**Zur Karte**), Bewertungen für Fotos und Tracks, Anzeigedrehung, Drag & Drop,
Track-Vorschauen und Rückgängig/Wiederherstellen (Strg+Z / Strg+Y) gehören dazu.
Travelbook-PDF, CEWE-Projekt (`.mcf`, zum Feinschliff im Creator) und
Travelbook (interaktiv) als HTML-Ordner sind da; Buch-HTML folgt in Phase 8.
Unechte Dubletten (pHash) bleiben offen.

## Voraussetzungen

- Windows 10/11
- Python 3.12

## Einrichtung

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\pip install -e packages/travelcore -e packages/fitnesscore -e apps/traveljournal
.\.venv\Scripts\pip install pytest ruff
```

## Anwendung starten

```powershell
.\.venv\Scripts\python.exe -m traveljournal
```

## Fitness-Datenbank (CLI)

Eigenständige SQLite-Datenbank für Polar-JSON, FIT und IGC, **unabhängig** vom
Reisetagebuch (`packages/fitnesscore`). Der Import legt alle erkannten Dateien
ab (Training, Tagesaktivität, 24/7-Puls, Tests, geplante Routen, Konto, FIT,
IGC-Flüge, …),
komprimiert als Payload. Originale werden nur gelesen. Abfragen: GPX (Polar/FIT)
und Original-IGC, jeweils nach optionaler Sportart und Datumsbereich
(UTC-Kalendertage).
Im Reisetagebuch: Seite **Import** → Fitness-DB bzw. IGC-DB wählen → Zeitraum
(von Reise von–bis vorbefüllt, überschreibbar) → **Fitnessdaten Importieren**
bzw. **IGC-Daten Importieren** (jeweils mit Fortschrittsanzeige). Schreibt nach
`{Import}/.FitnessTracks/` bzw. `{Import}/.IGCTracks/`.
Scan und Synchronisieren nehmen beide Ordner mit
(normale GPS-Dateien; `.MapTracks/` bleibt ausgeblendet).
Parameter und Aufruf auch in [packages/fitnesscore/README.md](packages/fitnesscore/README.md).

Zwei gleichwertige Aufrufe (nach `pip install -e packages/fitnesscore`):

```powershell
.\.venv\Scripts\python.exe -m fitnesscore -h
.\.venv\Scripts\fitnessdb.exe -h
```

`--db` steht **vor** dem Unterbefehl und gilt für alle Kommandos außer `init`,
das den Ordner auch als Positionsargument nimmt.

```powershell
.\.venv\Scripts\python.exe -m fitnesscore -h
.\.venv\Scripts\python.exe -m fitnesscore --db D:\Fitness init
.\.venv\Scripts\python.exe -m fitnesscore --db D:\Fitness import -h
.\.venv\Scripts\python.exe -m fitnesscore --db D:\Fitness import -d D:\tracks
.\.venv\Scripts\python.exe -m fitnesscore --db D:\Fitness import -d D:\tracks -r
.\.venv\Scripts\python.exe -m fitnesscore --db D:\Fitness import -d D:\tracks --r
.\.venv\Scripts\python.exe -m fitnesscore --db D:\Fitness import -d D:\tracks --recursive
.\.venv\Scripts\python.exe -m fitnesscore --db D:\Fitness import -f D:\tracks\fahrt.FIT
.\.venv\Scripts\python.exe -m fitnesscore --db D:\Fitness import -d D:\flights
.\.venv\Scripts\python.exe -m fitnesscore --db D:\Fitness export-igc --sports paragliding --from 2025-05-01 --to 2025-05-31 --out D:\out
.\.venv\Scripts\python.exe -m fitnesscore --db D:\Fitness sports
.\.venv\Scripts\python.exe -m fitnesscore --db D:\Fitness export-gpx --from 2026-08-01 --to 2026-09-02 --out D:\out
.\.venv\Scripts\python.exe -m fitnesscore --db D:\Fitness export-gpx --sports kitesurfing e-biking --from 2026-08-01 --to 2026-09-02 --out D:\out
```

Kurzhilfe (`-h`):

```
usage: fitnessdb [-h] [--db ORDNER] {init,import,export-gpx,export-igc,sports} ...

Lokale Fitness-Datenbank: importiert Polar-JSON, FIT und IGC vollständig.
GPX-Abfrage für Polar/FIT, IGC-Abfrage liefert die Originaldatei.

  init         Store-Ordner und leere Datenbank anlegen
  import       JSON-, FIT- und IGC-Dateien importieren (alles, nicht nur Routen)
  export-gpx   GPX (Polar/FIT) nach optionaler Sportart und Datumsbereich
  export-igc   Original-IGC nach optionaler Sportart und Datumsbereich
  sports       Sportarten auflisten, für die eine Route vorliegt

  --db ORDNER  Store-Ordner oder fitness.sqlite (Standard: ./fitness)
```

`init`:

```
usage: fitnessdb init [-h] [target]

  target  Ordner (Standard: --db oder ./fitness)
```

`import` — genau eine Quelle: `-f` **oder** `-d`. Rekursiv nur mit `-d`:
**`-r`**, **`--r`** oder **`--recursive`**.

Es gibt kein eigenes `update`. Derselbe `import` über denselben Ordner ist das
Update: neue oder inhaltlich geänderte Dateien (neuer SHA-256) kommen dazu,
bereits bekannte Hashes werden übersprungen. Gelöschte Dateien im Quellordner
bleiben in der Datenbank.

```
usage: fitnessdb import [-h] (-f DATEI | -d VERZEICHNIS) [-r]

  -f DATEI        einzelne .json-, .fit- oder .igc-Datei
  -d VERZEICHNIS  Ordner
  -r, --recursive mit -d auch Unterverzeichnisse einbeziehen
```

`export-gpx` und `export-igc` — `--from`, `--to` und `--out` sind Pflicht.
`--sports` ist optional. IGC-Auswahl schreibt die **Originaldatei**, keine GPX.

```
usage: fitnessdb export-gpx [-h] [--sports SPORT [SPORT ...]] --from DATUM
                            --to DATUM --out ORDNER
usage: fitnessdb export-igc [-h] [--sports SPORT [SPORT ...]] --from DATUM
                            --to DATUM --out ORDNER

  --sports SPORT [SPORT ...], --sport SPORT [SPORT ...]
                  optional: eine oder mehrere Sportarten; ohne Angabe alle
                  Treffer im Zeitraum. Mehrere Tokens oder Kommata.
  --from DATUM    von (YYYY-MM-DD, UTC, einschließlich)
  --to DATUM      bis (YYYY-MM-DD, UTC, einschließlich)
  --out ORDNER    Zielordner (wird angelegt)
```

`sports` hat keine weiteren Parameter; es braucht `--db` wie die anderen
Kommandos.

| Parameter | Pflicht | Bedeutung |
| --- | --- | --- |
| `--db ORDNER` | nein | Store-Ordner (`fitness.sqlite` darin) oder Pfad zu einer `.sqlite`-Datei. Standard: `./fitness` im aktuellen Verzeichnis. |
| `init [target]` | nein | Legt den Ordner und eine leere Datenbank an. Bricht ab, wenn die Datei schon existiert. Ohne `target` gilt `--db`. |
| `import -f DATEI` | eine von beiden | Eine Polar-JSON-, FIT- oder IGC-Datei. |
| `import -d VERZEICHNIS` | eine von beiden | Ordner; nur `.json`, `.fit` und `.igc`. Andere Endungen (z. B. `.gpx`) werden ignoriert. |
| `import -r` / `--r` / `--recursive` | nein | Mit `-d`: Unterverzeichnisse. Ohne `-d` Fehler. |
| `export-gpx --from` / `--to` | ja | UTC-Kalendertage, beide einschließlich. Nur Polar/FIT-Sessions, keine IGC. |
| `export-gpx --out` | ja | Zielordner. Dateiname `{UTC-Start}_{sport}_{id}.gpx`. |
| `export-igc --from` / `--to` | ja | Dieselben UTC-Tage. Nur IGC-Flüge. |
| `export-igc --out` | ja | Zielordner. Originalbytes, Dateiname `{UTC-Start}_{Originalname}_{id}.igc`. |
| `export-gpx` / `export-igc --sports` | nein | Slugs oder Aliasse. Mehrere: `--sports a b` oder `--sports a,b`. `--sport` ist Alias. Ohne Flag: alle Treffer im Zeitraum. |
| `sports` | — | Liste `Anzahl  slug` nur für Sessions, die eine Route haben. |

`import` schreibt einen Punkt pro Datei und am Ende
`Dateien n, importiert i, übersprungen s, Fehler e, Dokumente d, Tracks t`
plus eine Aufschlüsselung nach Dateiart. Beim erneuten Lauf (Update) sind `i`
die Neuankömmlinge und `s` die schon bekannten SHA-256. `export-gpx` schreibt
jeden GPX-Pfad und `GPX n`, oder `keine GPX`.
`export-igc` schreibt jeden IGC-Pfad und `IGC n`, oder `keine IGC`. Ein
Polar-Gesamtexport kann mehrere Gigabyte groß sein; der erste Bulk-Import
dauert entsprechend.

Dieselbe Einheit als JSON-Export und FIT-Download wird über Startzeit (Minute,
UTC) und Sport zusammengeführt. Eine FIT-Datei mit mehreren Sessions liefert
mehrere GPX. IGC-Flüge bekommen Sport aus dem Gleitschirmtyp (`paragliding`,
`hang-gliding`, `gliding`; Standard Gleitschirm); die Abfrage gibt die
importierte IGC-Datei zurück, keine umgewandelte GPX. Geplante Polar-Routen
liegen in der Datenbank, erscheinen in `export-gpx` aber nicht (kein
Session-Datum).

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

## Google-Maps-Link nach GPX (Hilfsprogramm)

Auf der Timeline-Karte von Tag oder Aufenthalt: **Verbindung zum nächsten Abschnitt**
→ **Map-Track** → **Datei…** oder **Maps-Link…**. Am Transfer gibt es denselben Typ
zusätzlich zu **Track** (GPX-Mitglieder des Abschnitts). Die GPX liegt im Import-Ordner unter
`.MapTracks/`. Ein Datei-Import heißt **Map-Track**. Ein Maps-Link schlägt den
Namen aus Start und Ziel vor (Dialog, überschreibbar; fehlt der Name, Nominatim
oder `Stop-n`). Die Straßenführung kommt von
OpenStreetMap über OSRM, nicht von Google.

Dasselbe kann das CLI `scripts/maps_url_to_gpx.py` ohne GUI. Kurzlinks
`maps.app.goo.gl` werden aufgelöst. `--waypoints-only` verbindet nur die Stopps,
ohne Router. Skript und Timeline sprechen dazu Google (Redirect) und OSRM an;
übrige App-Funktionen bleiben lokal.

```powershell
.\.venv\Scripts\python.exe scripts\maps_url_to_gpx.py -h
.\.venv\Scripts\python.exe scripts\maps_url_to_gpx.py "https://maps.app.goo.gl/…"
.\.venv\Scripts\python.exe scripts\maps_url_to_gpx.py -o D:\tracks\route.gpx "https://maps.app.goo.gl/…"
.\.venv\Scripts\python.exe scripts\maps_url_to_gpx.py --waypoints-only -o D:\tracks\stops.gpx "https://maps.app.goo.gl/…"
```

Kurzhilfe (`-h`):

```
usage: maps_url_to_gpx.py [-h] [-o DATEI] [--waypoints-only] [--router URL]
                          URL

Erzeugt eine GPX-Datei aus einem Google-Maps-Link der Routenplanung. Stopps
kommen aus dem Link, die Strecke folgt OpenStreetMap-Straßen (OSRM).

positional arguments:
  URL               Google-Maps-Routenlink (auch maps.app.goo.gl)

options:
  -h, --help        show this help message and exit
  -o DATEI          Zieldatei oder Ordner
  --waypoints-only  keine Straßenführung, nur Stopps als Track verbinden
  --router URL      OSRM-Basis-URL (Standard: https://router.project-osrm.org)
```

Ohne `-o` entsteht `{Start}-to-{Ziel}.gpx` im aktuellen Verzeichnis. Die
erzeugte GPX kann anschließend wie jede andere Trackdatei importiert werden.

## Länderkatalog

Bereiste Länder wählt man auf der **Projektseite** aus einem eingebetteten Katalog
(ISO-3166-1 alpha-2, deutscher Name, Flagge, Umriss). Die App speichert ISO-Codes
in `trips.countries`. Die Reiseübersicht zeigt Umriss, Namen in Versalien und eine
kleine Flagge hinter dem Namen.

Die Assets liegen versioniert unter `packages/travelcore/src/travelcore/geo/data/`
(kein Download zur Laufzeit). Quellen und Lizenzen: [docs/dependencies.md](docs/dependencies.md),
`travelcore/geo/data/NOTICE.txt`. Neu erzeugen nur nach Katalog-Änderung:

```powershell
.\.venv\Scripts\python.exe scripts\build_country_catalog.py
```

Cache: `build/country-catalog-cache/` (nicht versioniert). Die Frozen-EXE nimmt
`geo/data` mit (`packaging/traveljournal.spec`).

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
- [Fitness-Datenbank](packages/fitnesscore/README.md) — CLI `fitnessdb` / `python -m fitnesscore`

## Datenschutz

Alle Analysen laufen standardmäßig lokal. Fotos, GPS-Tracks und Reisedaten
werden nicht automatisch an externe Dienste übertragen. Ausnahme: **Maps-Link…**
auf der Timeline-Ausgangslinie und das CLI `scripts/maps_url_to_gpx.py` lösen
Google-Maps-Links auf, holen fehlende Ortsnamen von Nominatim (OpenStreetMap)
und die Straßenführung von OSRM.

Originaldateien werden niemals verändert.
