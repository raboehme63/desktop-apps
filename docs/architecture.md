# Architektur

Produktanforderungen: [pflichtenheft.md](pflichtenheft.md). Leitkonzept: [konzept.md](konzept.md). Tests: [testdokumentation.md](testdokumentation.md).

Stand: **Phase 7** (Timeline und Tagebuch).

## Prinzip

`travelcore` enthält die gesamte Analyse- und Persistenzlogik und hat **keine**
Abhängigkeit zu Qt/PySide6. `traveljournal` ist eine dünne Desktop-Schicht
(Views, ViewModels, Worker). Später kann `PhotoInspector` dieselbe Bibliothek
nutzen.

```
apps/traveljournal  ──uses──►  packages/travelcore
apps/photoinspector ─uses──►  packages/travelcore   (geplant)
```

## Schichten

| Schicht | Ort | Aufgabe |
| --- | --- | --- |
| UI | `apps/traveljournal/.../ui`, `views`, `widgets` | Darstellung, keine Geschäftslogik |
| Services | `apps/traveljournal/.../services` | Qt-Threads, Dialoge, Fortschritt, Workspace |
| Domain | `travelcore.trip` | Reise, Tag, Ort, Ereignis (Pydantic) |
| Use Cases | `travelcore.media`, `gps`, `timeline`, `geolocation`, `maps`, `export` | Import, Zuordnung, Timeline, Karte, Export |
| Persistenz | `travelcore.database` | SQLAlchemy-Modelle, Alembic, Projektordner |

## Module in travelcore (Phase 7)

| Paket | Inhalt |
| --- | --- |
| `media` | Scan, SHA-256, Indexer, Thumbnails, Galerie |
| `metadata` | Pillow, HEIC-Container, optional ExifTool, Merge |
| `gps` | GPX-Parse, Ingest, zeitliche Interpolation |
| `geolocation` | Aufenthaltscluster (Haversine, Radius 150 m) |
| `timeline` | Tage aus Aufnahmezeit, Ortsvorschläge, manuelle Edits |
| `maps` | `MapScene` + Folium/Leaflet-Backend |
| `export` | Vertrag `Exporter`; HTML/PDF/LaTeX/CEWE noch Platzhalter |
| `image_analysis` / `similarity` | Verträge für Phase 9/10, ohne Engines |

Lange Aufgaben (Indexierung, Thumbnails) laufen im GUI-Prozess über
`QThreadPool`/`QRunnable`. `travelcore` selbst kennt keine Qt-Threads und
bietet synchrone Funktionen plus optionale Progress-Callbacks. CPU-Arbeit
(Hash, Metadaten, Thumbnails) läuft intern in einem `ProcessPool`
(`spawn`, ein Kern bleibt für die Oberfläche). Worker liefern nur DTOs;
SQLite schreibt seriell. ExifTool nutzt Stay-Open oder eine Argfile-Liste,
nicht einen Prozess pro Datei.

## Projektordner

Ein Reiseprojekt ist ein Verzeichnis, keine einzelne Datei:

```
meine_reise/
    project.sqlite
    settings.toml
    thumbnails/
    cache/          # u. a. map.html
    exports/
    logs/
```

Die Datenbank speichert nur Referenzen auf Originaldateien. Originale werden
nicht kopiert, sofern der Benutzer das nicht ausdrücklich wünscht.

`settings.toml` hält Projekteinstellungen: Quellwurzel, Standard-Exportformat,
GPS-Zeitfenster, Standardzeitzone, Kartenanbieter (`leaflet` / `offline`).
Ändert sich die Quellwurzel, werden Index-Pfade umgeschrieben, die
Originaldateien nicht.

Zuletzt geöffnete Projekte stehen unter
`%LOCALAPPDATA%\TravelJournal\recent.json` (max. 10). Die Oberfläche listet
sie in Phase 7 noch nicht.

## Timeline und Tagebuch

Nach dem Import ruft die App `sync_timeline` auf. Die Bibliothek:

1. legt eine `Trip`-Zeile an, falls fehlend
2. erzeugt oder aktualisiert `TripDay`-Zeilen je Kalendertag der Aufnahmezeit
3. legt ein automatisches Ereignis pro Tag an (Medienzähler)
4. schlägt Orte vor, wenn der Tag noch keine Orte hat
5. löscht leere Auto-Tage ohne manuelle Texte, Orte oder Übernachtungen

Manuelle Titel, Notizen, bestätigte Orte, Übernachtungen und Foto-Flags
(`used_in_journal`, `is_cover`, `is_favorite`) tragen `origin=manual` und
werden beim Re-Sync nicht überschrieben. Fotos gehören über `captured_at`
zu einem Tag; das Tagebuch-Häkchen ändert die Zugehörigkeit nicht.

Die UI teilt die Arbeit: Timeline bestätigt/löscht Orte, Tagebuch schreibt
Texte und Übernachtungen. Beide lesen denselben Snapshot. Änderungen
aktualisieren Timeline, Tagebuch, Karte und Galerie.

## Karte

`build_map_scene` sammelt GPX-Tracks (ausgedünnt, max. 2500 Punkte, Endpunkte
bleiben), IGC-Flugtracks (max. 1200 Punkte, Linie ab Zoom 10, Start- und
Lande-Marker immer sichtbar, Popup mit Pilot und DHV-Leonardo-Link), geotaggte
Fotos/Videos, Orte und Übernachtungen. Folium schreibt `cache/map.html`.
Foto- und Track-Marker zeigen das Datum, keinen Ortsnamen; Klick auf ein Foto
zeigt Datum, Dateiname und Thumbnail.
`map_provider=offline` setzt `tiles=None` (keine OSM-Kacheln). Qt WebEngine
zeigt die Datei; fehlt das Add-on, bleibt der Pfad sichtbar.

## Austauschbare Schnittstellen

Bereits in Phase 1 angelegt, schrittweise gefüllt:

- `MetadataProvider` – Pillow für JPEG/TIFF/WebP/PNG; HEIC: eingebettetes EXIF-TIFF,
  QuickTime/ISO-6709 und Apple-`data`-Boxen; optional ExifTool für HEIC/RAW
- GPX- und IGC-Ingest in `travelcore.gps` – Tracks/Punkte in SQLite; Medien ohne EXIF-GPS
  in der Reihenfolge Foto → GPX → IGC (`photo_*`, `gpx_*`, `igc_*`);
  GPX-SourceFile mit Mittelwert der ersten Punkte und Startzeit (`gpx_track`);
  IGC mit Pilot (`igc_track`) und optionalem DHV-Leonardo-Link
- Thumbnails in `travelcore.media.thumbnails` – JPEG-Cache unter `thumbnails/`,
  HEIC über Windows-Shell/WIC oder eingebettetes JPEG, Originale nur gelesen
- `VideoMetadataProvider` – ffprobe-Adapter (noch nicht aktiv)
- `Exporter` – HTML, PDF, LaTeX, CEWE (Implementierung ab Phase 8)
- `MapBackend` – Folium/Leaflet, GPX-Tracks als Polylinie, IGC-Flugtracks ab Zoom 10
  (Start/Landung immer sichtbar), Fotos/Videos als Marker (Cluster je Tag),
  Übernachtungen und Orte
- Timeline in `travelcore.timeline` – Tage aus dem Aufnahmedatum, manuelle Texte; keine Ortsnamen an Foto-/Trackpositionen
- `RankingStrategy` / `QualityAnalyzer` – Verträge für Phase 9/10

## Persistenz

SQLAlchemy 2, Alembic, eine SQLite-Datei je Projekt. Migrationen:

- `001_initial` – Kernschema inkl. Reise, Analysen, Ähnlichkeit, Export
- `002_captured_source` – `captured_at_source` am Dateiindex

## Phasen

1. Projektstruktur und travelcore
2. Dateiimport und SQLite
3. Metadaten
4. GPX und GPS-Zuordnung
5. Thumbnail-Galerie
6. Karte
7. Timeline und manuelle Bearbeitung  ← aktueller Stand
8. HTML-Export
9. Qualitätsanalyse
10. Dublettenerkennung
