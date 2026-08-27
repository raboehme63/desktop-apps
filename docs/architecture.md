# Architektur

Produktanforderungen: [pflichtenheft.md](pflichtenheft.md). Leitkonzept: [konzept.md](konzept.md). Tests: [testdokumentation.md](testdokumentation.md). Windows-Paket: [packaging/README.md](../packaging/README.md).

Stand: **Phase 7 erweitert**, Software **R1.0.0** (27. August 2026).

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
| `timeline` | Tage, Transfers, Aufenthalte, Links, Cover, manuelle Edits |
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
GPS-Zeitfenster, Standardzeitzone, Kartenanbieter (`leaflet` / `offline`),
Farbe der Verbindungslinien auf der Karte (`map_link_color`, Standard `#ffffff`).
Ändert sich die Quellwurzel, werden Index-Pfade umgeschrieben, die
Originaldateien nicht.

Zuletzt geöffnete Projekte stehen unter
`%LOCALAPPDATA%\TravelJournal\recent.json` (max. 10). Die Oberfläche listet
sie in Phase 7 noch nicht. Der Fenstertitel lautet `Reisetagebuch R{Version}`
bzw. `Reisetagebuch R{Version} - {Projekttitel}`. Das Medienregister
(Timeline und Medienseite) steht in `%LOCALAPPDATA%\TravelJournal\config.json` (`timeline_media_tab`).

## Timeline

Nach dem Import ruft die App `sync_timeline` auf. Die Bibliothek:

1. legt eine `Trip`-Zeile an, falls fehlend
2. erzeugt oder aktualisiert `TripDay`-Zeilen je Kalendertag der Aufnahmezeit
3. legt ein automatisches Ereignis pro Tag an (Medienzähler)
4. schlägt Orte vor, wenn der Tag noch keine Orte hat
5. löscht leere Auto-Tage ohne manuelle Texte oder Orte

Die Timeline-UI mischt **Reiseabschnitte** (`trip_sections` / `section_members`)
und **Tage** (früher Resttage). Der Typ ist in der Oberfläche **Tag**, **Transfer**
oder **Aufenthalt**; gespeichert bleiben `stay` und `movement`, Tage ohne Abschnitt.
Neu angelegte Abschnitte sind `PendingSectionSpec` (negative `local_id`) bis
Speichern. Overlay `apply_pending_sections` ist Vorschau.

Manuelle Titel, Notizen, bestätigte Orte, Foto-Flags
(`used_in_journal`, `is_cover`, `is_favorite`, `sort_status`), YouTube-URLs,
Eintrags-Titelbilder (`cover_source_file_id`, Foto oder GPS-Track) und
Anzeigedrehung (`rotation_degrees`) überleben Re-Sync bzw. Re-Import.
Der Reisetitel (`trips.title`) folgt zuerst dem Projektnamen; nach manueller
Eingabe in der Timeline (`origin=manual`) überschreibt der Abgleich ihn nicht.
Fotos gehören über `captured_at` zu einem Tag; das Flag `used_in_journal`
ändert die Zugehörigkeit nicht.

YouTube-URLs werden nur mit Timeline-Speichern persistiert.
DHV-Leonardo-URLs am IGC-Track und an gespeicherten Tagen/Abschnitten
schreiben beim Dialog-OK. Das Flugportal heißt ausschließlich DHV-Leonardo,
nie DAV.

Die Timeline legt Abschnitte an, schreibt den Reisetitel sowie Titel und Texte, setzt Bewertungen
und Eintrags-Titelbilder und öffnet den Medieninspektor. Bewertungen auf der Medienseite
gelten in der Timeline; Änderungen aktualisieren Timeline, Karte und Galerie.

Der Medieninspektor blättert in der Sequenz des Tags/Abschnitts (bzw. der
Medienseite), zoomt mit dem Mausrad, dreht die Anzeige in 90°-Schritten und
ändert Originale nicht. Reiter Alle/Favoriten/Reserve/Aussortiert (Timeline und
Medienseite) wechseln nur per Klick, nicht durch Mausrad.

## Karte

`build_map_scene` (delegiert an `build_map_overview`) und `build_map_timeline`
in `travelcore.maps.groups` bauen die Übersicht: ein Titelbild je gespeichertem
Tag, Transfer oder Aufenthalt
(`cover_source_file_id`, sonst das erste Foto mit GPS, sonst der erste GPS-Track). Position ist
die Cover-GPS, sonst der Schwerpunkt der geotaggten Mitglieder. Unsaved
Pending-Abschnitte erscheinen nicht auf der Karte. Zwischen **Tag- und Aufenthaltskreisen**
in Timeline-Reihenfolge liegen `StayLink`-Polylinien mit Richtungsmarker (gleiche
Positionen wie die runden Cover). Transfer-Kreise sind keine Endpunkte. Bei
überdeckenden Kreisen (Pixelabstand ≤ Cover-Durchmesser) blendet das Leaflet-Skript
die Linie aus. Ein Transfer dazwischen setzt `via_transfer` (Linienbild später:
gerade, gebogen, Trackspur). In der Detailansicht sind die Linien ausgeblendet.

Folium schreibt `cache/map.html` (`MAP_CACHE_VERSION` im Stamp). Qt WebEngine
zeigt die Datei; die kompakte Leiste (`MapTimelineStrip`) sitzt **unter** dem
WebView, nicht als Overlay über Chromium — sonst verschluckt die Karte Klicks.
Klick auf eine Leistenkarte ruft `traveljournalFocusCover` auf: Schwenken bei
**unverändertem Zoom**. Doppelklick auf eine Leistenkarte öffnet denselben Eintrag
in der Timeline. Klick auf einen Kreis (`group_key`) öffnet die
Detailansicht (`traveljournalShowDetail`): Fotos, Videos, GPX-Linien,
IGC-Flugtracks ab Zoom 10 (Start/Landung immer sichtbar) und Orte.
`resolve_map_group` liest nur den angeklickten Eintrag, nicht die ganze
Timeline. Klick auf ein Foto im Detail öffnet ein Leaflet-Popup mit Thumbnail;
Doppelklick öffnet den Medieninspektor mit dem Original (wie Timeline).
Nahe Foto-, Video- und Track-Marker werden bis Zoom 16 gestapelt
(`PHOTO_STACK_DISABLE_ZOOM` = 17); der Stapel-Marker zeigt die Anzahl.
Ab Zoom 17 liegen sie einzeln, auch übereinander; überlappende Marker rotieren, Mouseover blendet die übrigen Fotos aus. Orte bleiben ungestapelt.
Übersichtstitelbilder clustern nicht.

Online-Kacheln kommen von `tile.openstreetmap.de` (deutsche Namen, sonst
lateinische Umschrift statt Landesschrift). Ein Layer-Symbol oben rechts öffnet
Straßenkarte (OSM), Topo (OpenTopoMap) und Satellit (Esri World Imagery); die Wahl
bleibt in `localStorage`. Ein Zahnrad unter den Zoom-Buttons schaltet Fotokegel
(ab Zoom 17, aus `heading_degrees` und 35-mm-Brennweite; Mouseover über ein Foto
blendet die übrigen Fotos und Kegel aus) und Reserve-Medien;
Aussortierte Medien kommen nicht auf die Karte. `map_provider=offline` setzt
`tiles=None` (keine OSM-, OpenTopoMap- oder Satellitenkacheln, kein Umschalter). Fehlt Qt WebEngine, bleibt der Pfad sichtbar.

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
- `MapBackend` – Folium/Leaflet, Übersicht als Titelbild-Kreise je Tag/Transfer/Aufenthalt, Layer-Menü Straßenkarte/Topo/Satellit, Zahnrad für Fotokegel (Mouseover blendet fremde Fotos und Kegel aus, überlappende Stapel rotieren ab Zoom 17) und Reserve,
  Verbindungslinien zwischen Tag- und Aufenthaltskreisen (Richtungsmarker, Zoom-Überdeckung),
  Qt-Leiste unter der Karte (Tag mit Kalender, Transfer als liegendes Sechseck), Detail mit GPX-Polylinien, IGC-Flugtracks ab Zoom 10
  (Start/Landung immer sichtbar), Foto-Popup und Inspektor, Orte
- Timeline in `travelcore.timeline` – Tage, Transfers, Aufenthalte, Cover, Links;
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

## Windows-Paketierung

Die Anwendung unter `apps/` und `packages/` bleibt unverändert. Build-Skripte
liegen in `packaging/`. Ergebnis ist ein **onedir**-Ordner
`dist/Reisetagebuch/` (plus Zip; optional Inno-Setup-EXE). `dist/` und `build/`
sind gitignored.

| Datei | Rolle |
| --- | --- |
| `packaging/entry.py` | Frozen-Einstieg: `multiprocessing.freeze_support`, dann `traveljournal.main` |
| `packaging/traveljournal.spec` | PyInstaller: Qt-WebEngine-Hooks, Folium/Alembic-Daten, Migrationen als Dateien |
| `packaging/build.ps1` | pip-installiert PyInstaller ins venv, friert ein, schreibt Zip, ruft optional ISCC auf |
| `packaging/installer.iss` | Inno Setup 6, Installation nach `%LOCALAPPDATA%\Programs\Reisetagebuch` |
| `packaging/NOTICE.txt` | LGPL-Hinweis PySide6/Qt im Paket |

Alembic braucht die Migrationsdateien **auf der Platte** (`Path(__file__).parent / "migrations"`).
PyInstaller legt sie nach `_internal/travelcore/database/migrations/`. Qt WebEngine
liegt als `QtWebEngineProcess.exe` unter `_internal/PySide6/`.

Drei Pfade bleiben getrennt:

| Ort | Inhalt |
| --- | --- |
| Installationsordner bzw. entpacktes Zip | Programm, Qt, Python-Laufzeit |
| `%LOCALAPPDATA%\TravelJournal` | `config.json`, `recent.json` |
| Benutzer-Projektordner | `project.sqlite`, Thumbnails, Cache — Originale bleiben in der Quellwurzel |

ProcessPool nutzt `spawn`. Ohne `freeze_support` im Frozen-Hauptmodul würden Worker
die EXE erneut als GUI starten. Deshalb der Extra-Einstieg, nicht eine Änderung
an `traveljournal.main`.

macOS ist kein Ziel (WIC-Vorschauen, AppData-Pfade).

## Phasen

1. Projektstruktur und travelcore
2. Dateiimport und SQLite
3. Metadaten
4. GPX und GPS-Zuordnung
5. Thumbnail-Galerie
6. Karte
7. Timeline und manuelle Bearbeitung  ← aktueller Stand, Software R1.0.0
   (Abschnitte, Bewertungen, Inspektor, Track-Vorschauen, Anzeigedrehung)
   Windows-Endnutzerpaket: `packaging/` (keine eigene Fachphase)
8. HTML-Export
9. Qualitätsanalyse
10. Dublettenerkennung
