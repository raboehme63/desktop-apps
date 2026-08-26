# Architektur

Produktanforderungen: [pflichtenheft.md](pflichtenheft.md). Leitkonzept: [konzept.md](konzept.md). Tests: [testdokumentation.md](testdokumentation.md).

Stand: **Phase 7 erweitert**, Software **R1.0.0**.

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

## Module in travelcore (Phase 7 erweitert)

| Paket | Inhalt |
| --- | --- |
| `media` | Scan, SHA-256, Indexer, Thumbnails, Galerie, Anzeigedrehung (`orientation`) |
| `metadata` | Pillow, HEIC-Container, optional ExifTool, Merge |
| `gps` | GPX/IGC-Parse und Ingest, KML/GeoJSON nur für Vorschauen, zeitliche Interpolation |
| `geolocation` | Aufenthaltscluster (Haversine, Radius 150 m) |
| `timeline` | Tage, Resttage, Reiseabschnitte, Links, Cover, manuelle Edits |
| `maps` | `MapScene` + Folium/Leaflet; statische OSM-Ausschnitte für Track-Thumbs |
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
sie in Phase 7 noch nicht. Der Fenstertitel lautet `Reisetagebuch R{Version}`
bzw. `Reisetagebuch R{Version} - {Projekttitel}`. Das Timeline-Medienregister
steht in `%LOCALAPPDATA%\TravelJournal\config.json` (`timeline_media_tab`).

## Timeline und Tagebuch

Nach dem Import ruft die App `sync_timeline` auf. Die Bibliothek:

1. legt eine `Trip`-Zeile an, falls fehlend
2. erzeugt oder aktualisiert `TripDay`-Zeilen je Kalendertag der Aufnahmezeit
3. legt ein automatisches Ereignis pro Tag an (Medienzähler)
4. schlägt Orte vor, wenn der Tag noch keine Orte hat
5. löscht leere Auto-Tage ohne manuelle Texte, Orte oder Übernachtungen

Die Timeline-UI mischt **Reiseabschnitte** (`trip_sections` / `section_members`)
und **Resttage**. Neu angelegte Abschnitte sind `PendingSectionSpec` (negative
`local_id`) bis Speichern. Overlay `apply_pending_sections` ist Vorschau.

Manuelle Titel, Notizen, bestätigte Orte, Übernachtungen, Foto-Flags
(`used_in_journal`, `is_cover`, `is_favorite`, `sort_status`), YouTube-URLs,
Eintrags-Titelbilder (`cover_source_file_id`, Foto oder GPS-Track) und
Anzeigedrehung (`rotation_degrees`) überleben Re-Sync bzw. Re-Import.
Fotos gehören über `captured_at` zu einem Tag; das Tagebuch-Häkchen ändert
die Zugehörigkeit nicht.

YouTube-URLs werden nur mit Timeline- bzw. Tagebuch-Speichern persistiert.
DHV-Leonardo-URLs am IGC-Track und an gespeicherten Tagen/Abschnitten
schreiben beim Dialog-OK. Das Flugportal heißt ausschließlich DHV-Leonardo,
nie DAV.

Die UI teilt die Arbeit: Timeline legt Abschnitte an, setzt Bewertungen und
Eintrags-Titelbilder, öffnet den Medieninspektor; das Tagebuch schreibt Texte
und Übernachtungen. Beide lesen denselben Snapshot. Änderungen aktualisieren
Timeline, Tagebuch, Karte und Galerie.

Der Medieninspektor blättert in der Sequenz des Tags/Abschnitts (bzw. der
Fotoseite), zoomt mit dem Mausrad, dreht die Anzeige in 90°-Schritten und
ändert Originale nicht. Reiter Alle/Favoriten/Reserve/Aussortiert wechseln
nur per Klick, nicht durch Mausrad.

## Karte

`build_map_scene` baut die Übersicht: ein Titelbild je Reiseabschnitt oder Resttag
(gespeichertes `cover_source_file_id`, sonst das erste Listenelement mit GPS).
Position ist die Cover-GPS, sonst der Schwerpunkt der geotaggten Mitglieder.
Folium schreibt `cache/map.html`; ein Klick auf das runde Titelbild zeigt
Fotos, Videos, Tracks, Übernachtungen und Orte dieses Eintrags.
Online-Kacheln kommen von `tile.openstreetmap.de` (deutsche Namen, sonst
lateinische Umschrift statt Landesschrift). `map_provider=offline` setzt
`tiles=None` (keine OSM-Kacheln). Qt WebEngine zeigt die Datei; fehlt das
Add-on, bleibt der Pfad sichtbar.

## Austauschbare Schnittstellen

Bereits in Phase 1 angelegt, schrittweise gefüllt:

- `MetadataProvider` – Pillow für JPEG/TIFF/WebP/PNG; HEIC: eingebettetes EXIF-TIFF,
  QuickTime/ISO-6709 und Apple-`data`-Boxen; optional ExifTool für HEIC/RAW
- GPX- und IGC-Ingest in `travelcore.gps` – Tracks/Punkte in SQLite; Medien ohne EXIF-GPS
  in der Reihenfolge Foto → GPX → IGC (`photo_*`, `gpx_*`, `igc_*`);
  GPX-SourceFile mit Mittelwert der ersten Punkte und Startzeit (`gpx_track`);
  IGC mit Pilot (`igc_track`) und optionalem DHV-Leonardo-Link
- Thumbnails in `travelcore.media.thumbnails` – JPEG-Cache unter `thumbnails/`,
  HEIC über Windows-Shell/WIC oder eingebettetes JPEG, Originale nur gelesen;
  Track-Thumbs über `maps.static` (rote Spur, OSM-Kacheln in `cache/map_tiles`)
- Anzeigedrehung in `travelcore.media.orientation` – nach EXIF-Transpose,
  Cachepfad enthält `_r90` bei nicht-null `rotation_degrees`
- `VideoMetadataProvider` – ffprobe-Adapter (noch nicht aktiv)
- `Exporter` – HTML, PDF, LaTeX, CEWE (Implementierung ab Phase 8)
- `MapBackend` – Folium/Leaflet, Übersicht als Titelbilder je Abschnitt/Resttag,
  Detail mit GPX-Polylinien, IGC-Flugtracks ab Zoom 10 (Start/Landung immer sichtbar),
  Fotos/Videos, Übernachtungen und Orte
- Timeline in `travelcore.timeline` – Tage, Abschnitte, Resttage, Cover, Links;
  keine Ortsnamen an Foto-/Trackpositionen
- KML/GeoJSON in `travelcore.gps` – Parser für Vorschauen, kein Ingest in `gps_tracks`
- `RankingStrategy` / `QualityAnalyzer` – Verträge für Phase 9/10

## Persistenz

SQLAlchemy 2, Alembic, eine SQLite-Datei je Projekt. Migrationen:

- `001_initial` – Kernschema inkl. Reise, Analysen, Ähnlichkeit, Export
- `002_captured_source` – `captured_at_source` am Dateiindex
- `003_igc_tracks` – IGC-Format, Pilot, externer DHV-Leonardo-Link
- `004_heading_35mm` – Blickrichtung und 35-mm-Brennweite
- `005_trip_sections` – `trip_sections`, `section_members`
- `006_section_modes` – Transfer-Verkehrsmittel
- `007_youtube_urls` – YouTube-URLs an Tag und Abschnitt
- `008_leonardo_urls` – zusätzliche DHV-Leonardo-URLs an Tag und Abschnitt
- `009_photo_sort_status` – `photos.sort_status`
- `010_entry_cover` – `cover_source_file_id` an Tag und Abschnitt
- `011_rotation_degrees` – `source_files.rotation_degrees` (Anzeigedrehung)

## Phasen

1. Projektstruktur und travelcore
2. Dateiimport und SQLite
3. Metadaten
4. GPX und GPS-Zuordnung
5. Thumbnail-Galerie
6. Karte
7. Timeline und manuelle Bearbeitung  ← aktueller Stand, Software R1.0.0
   (Abschnitte, Bewertungen, Inspektor, Track-Vorschauen, Anzeigedrehung)
8. HTML-Export
9. Qualitätsanalyse
10. Dublettenerkennung
