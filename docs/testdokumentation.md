# Testdokumentation — Reisetagebuch

| Feld | Inhalt |
| --- | --- |
| Version | 0.8 |
| Stand | 18. August 2026 |
| Bezugsversion Software | Phase 7 (Timeline und Tagebuch) |
| Bezug | [pflichtenheft.md](pflichtenheft.md), [konzept.md](konzept.md) |

Diese Dokumentation beschreibt **Teststrategie, Automatisierung, manuelle Prüfung und Abdeckungslücken**. Sie ist die Testdoku zum Pflichtenheft, kein Ersatz für pytest-Ausgaben.

---

## 1. Ziele

- Fachregeln aus dem Pflichtenheft (Zeitpriorität, GPS, HEIC, GPX-Zuordnung, Timeline, Originale unangetastet, fehlerhafter Import) sind automatisiert nachvollziehbar.
- Jede Phase bleibt grün, bevor die nächste beginnt.
- Testdaten enthalten **keine persönlichen GPS-Spuren und keine echten Nutzerfotos**.
- Die GUI wird nur leicht angeraucht; Fachlogik wird in `travelcore` ohne Qt geprüft.

---

## 2. Teststufen

| Stufe | Ort | Werkzeug | Was |
| --- | --- | --- | --- |
| Unit | `packages/travelcore/tests/` | pytest | Typen, Hash, Zeit, GPS, Provider, HEIC-Container, GPX, Interpolation, ExifTool-JSON, Aufenthaltscluster |
| Integration | `packages/travelcore/tests/test_indexer.py`, `test_database.py`, `test_timeline.py`; `tests/integration/` | pytest | Projektordner, Schema, Index → SQLite, Timeline-Sync, Re-Open |
| GUI-Rauch | `tests/test_gui_smoke.py` | pytest + Qt offscreen | Hauptfenster startet, sieben Seiten |
| Manuell | dieses Dokument, Abschnitt 7 | Windows-Desktop | Import echter HEIC/JPEG, Liste, Timeline, Tagebuch, Karte |
| Statisch | Repository-Wurzel | Ruff, später pyright | Stil, Imports, grundlegende Typen |

Nicht eingeführt (geplant): pytest-qt für Interaktion, visuelle Galerie-/Kartentests, Lasttest mit zehntausenden Dateien.

---

## 3. Umgebung und Ausführung

### 3.1 Voraussetzungen

- Windows 10/11
- Python 3.12 im Projekt-venv (nicht eine fremde `python.exe` auf dem PATH)
- Installierte Editables: `travelcore`, `traveljournal`
- pytest (und ruff für die statische Prüfung)

ExifTool ist **kein** Testdependency. HEIC- und Provider-Tests müssen ohne das Binary bestehen. ExifTool wird nur über fest verdrahtete JSON-Fixtures geprüft.

### 3.2 Befehle

```powershell
cd D:\20-GITWorkspace\travel-journal
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m pytest packages/travelcore/tests/test_timeline.py -q
.\.venv\Scripts\python.exe -m ruff check packages apps tests
.\.venv\Scripts\python.exe -m ruff format --check packages apps tests
```

Konfiguration: `[tool.pytest.ini_options]` in der Repository-`pyproject.toml` (`testpaths`, `pythonpath`).

GUI-Rauchtest setzt `QT_QPA_PLATFORM=offscreen`, falls nicht gesetzt.

### 3.3 Testdatenregel

| Erlaubt | Verboten |
| --- | --- |
| Von Pillow erzeugte Mini-JPEGs | Originale aus dem Urlaub |
| Synthetische HEIC-*Bytes* (kein echtes Bild nötig) | Dateien mit echten Personen/GPS aus Produktivimporten |
| Feste Beispielkoordinaten in Tests (z. B. 46.5 °N, 11.35 °E) | Kopieren von `project.sqlite` mit Nutzerdaten ins Repo |
| Minimal-JPEG (`FF D8 … FF D9`) | Große Videos als Fixtures |

Hilfsmodul: `packages/travelcore/tests/jpeg_fixtures.py`. GPX-Hilfen: `gpx_fixtures.py`.

---

## 4. Abbildungsmatrix Pflichtenheft → automatisierte Tests

Stand nach `pytest --collect-only`: **98 Tests** (18. August 2026). Neue Tests sind ergänzend zu führen, nicht still zu löschen.

### 4.1 Dateitypen und Scan — FA-010 bis FA-016

| Test | Datei | Prüft |
| --- | --- | --- |
| `test_jpeg_is_photo` | `test_file_types.py` | JPG/JPEG → Foto |
| `test_gpx_is_gps` | `test_file_types.py` | GPX + MIME |
| `test_igc_is_gps` | `test_file_types.py` | IGC als GPS, MIME `application/x-igc` |
| `test_markdown_is_text` | `test_file_types.py` | Markdown |
| `test_unsupported_returns_none` | `test_file_types.py` | z. B. ZIP ignorieren |
| `test_raw_is_photo_for_metadata_later` | `test_file_types.py` | NEF als Foto klassifiziert |
| `test_scan_finds_supported_files_recursively` | `test_scanner.py` | Rekursion, JPEG-Groß/Kleinschreibung, GPX, MD, ZIP außen vor |
| `test_scan_finds_igc_flight_log` | `test_scanner.py` | IGC wird als GPS gefunden |
| `test_scan_skips_thumbnail_jpegs` | `test_scanner.py` | `thumbnails/` und `cache/` nicht als Fotos |

### 4.2 Index, Hash, Fehler — FA-020 bis FA-024, FA-095

| Test | Datei | Prüft |
| --- | --- | --- |
| `test_sha256_of_known_content` | `test_hashing.py` | bekannte Prüfsumme |
| `test_identical_files_share_hash` | `test_hashing.py` | gleiche Bytes → gleicher Hash |
| `test_different_files_differ` | `test_hashing.py` | unterschiedliche Bytes |
| `test_indexer_writes_source_files` | `test_indexer.py` | Foto+GPX im Index, SHA-256, Dateisystemzeit als Fallback |
| `test_indexer_skips_unchanged_files` | `test_indexer.py` | zweiter Lauf zählt `skipped_unchanged` |
| `test_corrupt_jpeg_does_not_abort_import` | `test_indexer.py` | kaputtes JPG erzeugt Fehlerzeile, gültiges JPG bleibt indexiert |
| `test_indexer_checkpoint_commits_partial_progress` | `test_indexer.py` | Zwischenstände sind in einer zweiten Session sichtbar |
| `test_extract_file_facts_hashes_and_reads_jpeg` | `test_extract.py` | Hash+EXIF ohne SQLite |
| `test_extract_many_pool_matches_sequential` | `test_extract.py` | ProcessPool liefert dieselben Hashes |
| `test_indexer_parallel_matches_sequential` | `test_indexer.py` | 1 Worker vs. 2 Worker, gleiche SHA-256 |

### 4.3 Zeit und Zeitzone — FA-031 bis FA-033

| Test | Datei | Prüft |
| --- | --- | --- |
| `test_datetime_original_beats_create_date` | `test_time.py` | Priorität DateTimeOriginal |
| `test_create_date_used_when_original_missing` | `test_time.py` | Fallback CreateDate |
| `test_missing_timezone_is_not_called_utc` | `test_time.py` | naive Zeit, `timezone_unknown` |
| `test_offset_makes_timezone_known` | `test_time.py` | Offset `+02:00` |
| `test_embedded_z_is_utc` | `test_time.py` | angehängtes Z → UTC |
| `test_invalid_value_returns_none` | `test_time.py` | Müllstring |
| `test_datetime_original_preferred_over_create_date` | `test_pillow_provider.py` | dieselbe Priorität am JPEG |
| `test_offset_marks_timezone_known` | `test_pillow_provider.py` | Offset aus EXIF |
| `test_plain_jpeg_has_no_capture_time` | `test_pillow_provider.py` | ohne EXIF keine Aufnahmezeit aus Pillow |
| `test_time_source_priority_has_exif_first` | `test_interfaces.py` | Konstante beginnt mit EXIF, endet mit Dateisystem |

### 4.4 GPS und Kamera — FA-034 bis FA-037

| Test | Datei | Prüft |
| --- | --- | --- |
| `test_dms_north_east` / `test_dms_south_west_is_negative` | `test_gps_exif.py` | DMS → Dezimalgrad |
| `test_signed_decimal_does_not_double_negate` | `test_gps_exif.py` | bereits negatives Gradmaß |
| `test_position_from_exif_sets_source_and_confidence` | `test_gps_exif.py` | Quelle `exif`, Konfidenz 1.0 |
| `test_incomplete_gps_returns_none` | `test_gps_exif.py` | Länge fehlt → keine Position |
| `test_iso6709_iphone_location` | `test_gps_exif.py` | `+lat+lon+alt/` |
| `test_gps_coordinates_decimal_pair` / `_dms_text` | `test_gps_exif.py` | alternative GPS-Texte |
| `test_gps_and_camera_from_exif` | `test_pillow_provider.py` | JPEG: Koordinaten + „Canon EOS R6“ |
| `test_heading_and_35mm_from_exif` | `test_pillow_provider.py` | Blickrichtung und 35-mm-Brennweite |
| `test_heading_prefers_img_direction` / `_falls_back_to_dest_bearing` | `test_gps_exif.py` | GPSImgDirection vor DestBearing |
| `test_indexer_reads_exif_time_and_gps` | `test_indexer.py` | End-to-End JPEG → SQLite inkl. Heading/35 mm |
| `test_exiftool_json_priority_and_signed_gps` | `test_exiftool_json.py` | JSON-Mapping, Vorzeichen |
| `test_exiftool_json_video_creation_time` | `test_exiftool_json.py` | Video-Zeitfeld |
| `test_exiftool_json_quicktime_gps_coordinates` | `test_exiftool_json.py` | QuickTime-Koordinaten |
| `test_exiftool_provider_read_uses_session` | `test_exiftool_json.py` | Stay-Open/Session statt Prozess pro Datei |
| `test_exiftool_provider_read_many_batches_paths` | `test_exiftool_json.py` | mehrere Pfade in einem Lauf |
| `test_merge_fills_missing_fields_only` | `test_metadata_merge.py` | Merge überschreibt vorhandene Werte nicht |

### 4.5 HEIC ohne ExifTool — FA-036

| Test | Datei | Prüft |
| --- | --- | --- |
| `test_heic_iso6709_is_read_without_exiftool` | `test_heic_gps.py` | ISO 6709 im Container |
| `test_default_provider_fills_heic_gps_without_exiftool` | `test_heic_gps.py` | DefaultProvider, kein ExifTool |
| `test_embedded_exif_tiff_from_jpeg_app1` | `test_heic_gps.py` | TIFF-Parser an JPEG-APP1 |
| `test_heic_embedded_exif_fills_gps_and_camera` | `test_heic_gps.py` | JPEG-EXIF in Fake-HEIC → GPS Quelle `exif`, Kamera Apple iPhone |
| `test_default_provider_fills_heic_camera_from_exif` | `test_heic_gps.py` | Provider-Weg Kamera+GPS |
| `test_heic_quicktime_data_boxes_provide_camera` | `test_heic_gps.py` | Apple-`data`-Boxen Make/Model |
| `test_indexer_reads_heic_quicktime_gps` | `test_indexer.py` | Index speichert QuickTime-GPS |
| `test_indexer_reads_heic_embedded_exif_camera_and_gps` | `test_indexer.py` | Index speichert Kamera und EXIF-GPS |

### 4.6 Projekt, Schema, Schnittstellen — FA-110 bis FA-113, FA-120, FA-090

| Test | Datei | Prüft |
| --- | --- | --- |
| `test_create_project_layout_and_row` | `test_database.py` | Ordnerlayout + Projektzeile + `settings.toml` |
| `test_open_existing_project` | `test_database.py` | Öffnen bestehender DB |
| `test_schema_contains_core_tables` | `test_database.py` | Kern-Tabellen inkl. `source_files`, `trips`, `photo_analyses` |
| `test_new_project_writes_settings_file` | `test_project_settings.py` | Default-`settings.toml` |
| `test_settings_roundtrip_preserves_values` | `test_project_settings.py` | Exportformat, Wurzel, Zeitzone, CPU-Worker |
| `test_corrupt_settings_raise` | `test_project_settings.py` | unlesbares TOML → `ProjectError` |
| `test_ensure_fills_source_root_from_database` | `test_project_settings.py` | fehlende Wurzel aus der DB nachziehen |
| `test_rebase_rewrites_indexed_paths` | `test_project_settings.py` | Pfad-Rebase ohne Original-Move |
| `test_project_survives_close_and_reopen` | `tests/integration/test_project_lifecycle.py` | Index überlebt Re-Open |
| `test_exporters_share_interface` | `test_interfaces.py` | HTML/PDF/LaTeX/CEWE sind `Exporter` |
| `test_protocols_are_importable` | `test_interfaces.py` | `MetadataProvider`, `RankingStrategy`, `MapBackend` |
| `test_main_window_starts` | `tests/test_gui_smoke.py` | Titel, 7 Seiten, Menü Projekt |

### 4.7 GPX und zeitliche Zuordnung — FA-040 bis FA-042

| Test | Datei | Prüft |
| --- | --- | --- |
| `test_parse_gpx_track_and_segment` | `test_gpx_parse.py` | Punkte, Höhe, UTC-Zeit, Segment-ID |
| `test_summarize_mean_of_first_points_and_start_time` | `test_gpx_parse.py` | Mittelwert der ersten Punkte, erste Trackzeit |
| `test_summarize_uses_first_timed_point_even_if_later` | `test_gpx_parse.py` | Startzeit ist der erste Punkt **mit** Zeit |
| `test_summarize_untimed_points_have_position_but_no_start` | `test_gpx_parse.py` | Position ohne `recorded_at` |
| `test_summarize_empty_gpx_has_no_fake_coordinates` | `test_gpx_parse.py` | leere GPX → keine Scheinkoordinaten |
| `test_empty_gpx_is_not_an_error` | `test_gpx_parse.py` | leere, wohlgeformte GPX-Datei |
| `test_corrupt_gpx_raises` | `test_gpx_parse.py` | `GpsError` ohne Absturz der Bibliothek |
| `test_interpolate_between_surrounding_points` | `test_gps_matching.py` | 14:32 zwischen 14:31:50 und 14:32:10 |
| `test_nearest_when_only_one_side_within_window` | `test_gps_matching.py` | nächster Punkt, Quelle `gpx_nearest` |
| `test_no_match_outside_max_delta` | `test_gps_matching.py` | außerhalb 120 s keine Position |
| `test_media_time_uses_project_offset_for_naive_capture` | `test_gps_matching.py` | Projekt-Offset `+02:00` |
| `test_aware_capture_is_converted_to_utc` | `test_gps_matching.py` | zeitbehaftete Aufnahme → UTC-Vergleich |
| `test_indexer_matches_photo_without_gps_to_gpx` | `test_indexer.py` | JPEG ohne GPS → SQLite `gpx_interpolated`; GPX-Zeile selbst `gpx_track` |
| `test_indexer_matches_photo_without_gps_to_nearby_photo` | `test_indexer.py` | JPEG ohne GPS übernimmt Position vom zeitnahen Foto |
| `test_indexer_prefers_photo_gps_over_gpx` | `test_indexer.py` | Foto vor GPX |
| `test_indexer_prefers_gpx_over_igc` | `test_indexer.py` | GPX vor IGC |
| `test_indexer_fills_gpx_source_file_position_and_time` | `test_indexer.py` | GPX-SourceFile: Mittelwert und Startzeit |
| `test_indexer_gpx_reingest_updates_source_file_metadata` | `test_indexer.py` | Re-Import aktualisiert Position und Zeit |
| `test_indexer_skips_unchanged_gpx_track_rewrite` | `test_indexer.py` | unveränderte GPX: keine neuen Punkt-IDs |
| `test_indexer_untimed_gpx_sets_position_without_date` | `test_indexer.py` | GPX ohne Zeiten: Position, keine Startzeit |
| `test_indexer_does_not_overwrite_exif_gps_with_gpx` | `test_indexer.py` | EXIF-GPS bleibt |
| `test_corrupt_gpx_does_not_abort_import` | `test_indexer.py` | defekte GPX als `file_errors.stage=gpx` |
| `test_empty_gpx_does_not_abort_import` | `test_indexer.py` | leere GPX kein Importabbruch |
| `test_parse_igc_pilot_and_points` | `test_igc_parse.py` | Pilot, UTC-Zeit, Bozen-Koordinaten |
| `test_parse_igc_skips_invalid_fix` | `test_igc_parse.py` | B-Record mit `V` wird ignoriert |
| `test_empty_igc_is_not_an_error` | `test_igc_parse.py` | Header ohne Fixes |
| `test_indexer_reads_igc_pilot_and_track` | `test_indexer.py` | Pilot in `camera`/`gps_tracks.pilot`, Quelle `igc_track` |
| `test_indexer_matches_photo_without_gps_to_igc` | `test_indexer.py` | Foto ohne GPS an IGC-Zeit |
| `test_indexer_preserves_igc_dhv_url_on_reingest` | `test_indexer.py` | DHV-Leonardo-Link überlebt Re-Import |
| `test_set_track_url_rejects_non_http` | `test_indexer.py` | kein `javascript:`-Link |

### 4.8 Thumbnails und Galerie — FA-100, FA-101

| Test | Datei | Prüft |
| --- | --- | --- |
| `test_ensure_thumbnail_writes_square_jpeg` | `test_thumbnails.py` | 32×32-JPEG, Original-mtime unverändert |
| `test_ensure_thumbnail_skips_existing` | `test_thumbnails.py` | Cache wird nicht überschrieben |
| `test_corrupt_jpeg_returns_none` | `test_thumbnails.py` | kein Absturz, keine Zieldatei |
| `test_heic_uses_embedded_jpeg_preview` | `test_thumbnails.py` | Fake-HEIC mit JPEG-Payload |
| `test_heic_jpeg_item_becomes_thumbnail` | `test_thumbnails.py` | HEIF-`jpeg`-Item über `iinf`/`iloc` |
| `test_windows_heic_helper_handles_garbage` | `test_thumbnails.py` | defekte Bytes → `None`, kein Absturz |
| `test_extract_largest_embedded_jpeg` | `test_thumbnails.py` | größtes eingebettetes JPEG |
| `test_cached_thumbnail_path_uses_hash` | `test_thumbnails.py` | Cache-Dateiname enthält SHA-256 |
| `test_indexer_writes_thumbnail_and_photo_row` | `test_indexer.py` | Cache + `photos`-Zeile |
| `test_indexer_does_not_regenerate_thumbnails_on_reimport` | `test_indexer.py` | Re-Import schreibt vorhandene Thumbs nicht neu |
| `test_indexer_does_not_count_thumbnails_when_source_is_project` | `test_indexer.py` | Projektordner als Quelle zählt Thumbs nicht als Fotos |
| `test_indexer_drops_previously_indexed_thumbnails` | `test_indexer.py` | bereits indexierte Thumbs werden entfernt |
| `test_indexer_can_defer_thumbnails` | `test_indexer.py` | Index ohne Thumbs, danach `build_previews` |
| `test_indexer_writes_thumbnails_in_parallel` | `test_indexer.py` | vier Vorschaubilder per ProcessPool |
| `test_gallery_lists_photos_in_capture_order` | `test_gallery.py` | chronologische Reihenfolge |

### 4.9 Karte — FA-050 bis FA-052

| Test | Datei | Prüft |
| --- | --- | --- |
| `test_downsample_keeps_endpoints` | `test_maps.py` | Trackpunkte werden ausgedünnt, Start/Ende bleiben |
| `test_map_scene_has_track_and_photo` | `test_maps.py` | Polylinie + Fotomarker mit Tagesgruppe |
| `test_map_scene_includes_overnight_and_place` | `test_maps.py` | Übernachtung und Ort |
| `test_folium_backend_writes_html` | `test_maps.py` | Leaflet-HTML, `MapBackend` |
| `test_offline_backend_omits_osm_tiles` | `test_maps.py` | `tiles=None` ohne OSM-URL |
| `test_map_scene_includes_igc_flight` | `test_maps.py` | IGC-Polylinie, Pilot, DHV-Link, Zoom-Skript |

### 4.10 Timeline und Tagebuch — FA-060 bis FA-064, FA-080, FA-081

| Test | Datei | Prüft |
| --- | --- | --- |
| `test_cluster_stays_joins_nearby_points` | `test_timeline.py` | GPS-Punkte im Radius bilden einen Cluster |
| `test_cluster_stays_splits_distant_points` | `test_timeline.py` | entfernte Punkte bleiben getrennt |
| `test_sync_timeline_creates_one_day_per_date` | `test_timeline.py` | zwei Aufnahmedaten → zwei Tage, Auto-Ereignis „1 Medien“ |
| `test_manual_day_text_survives_resync` | `test_timeline.py` | Titel/Text `origin=manual` bleibt nach Sync |
| `test_place_suggestion_not_auto_assigned_to_gps_media` | `test_timeline.py` | Import vergibt keinen Ortsnamen; opt-in-Vorschlag und Bestätigen |
| `test_overnight_and_journal_flags` | `test_timeline.py` | Übernachtung, `used_in_journal`, Titelbild |

---

## 5. Abdeckung gegen das Pflichtenheft

### 5.1 Gut abgedeckt (Phase 7)

- Dateiklassifikation und rekursiver Scan
- SHA-256 und Skip unveränderter Dateien
- EXIF-Zeitpriorität und Zeitzonenflag
- JPEG-GPS und Kamera
- HEIC-GPS/Kamera ohne ExifTool (ISO 6709, eingebettetes TIFF, Apple-Boxen)
- GPX-Parsing inkl. zeitloser und leerer Tracks, Interpolation, keine Überschreibung von EXIF-GPS
- JPEG-Thumbnails, HEIC-Vorschau (Windows-Shell/WIC oder eingebettetes JPEG), Originale unverändert
- Importliste während des Einlesens und nach GPS-Abgleich, bevor Thumbnails erzeugt werden
- Galerie-Reihenfolge nach Aufnahmezeit
- Import bricht bei einer defekten Datei (JPEG oder GPX) nicht ab
- Projekt anlegen, Schema, Wiederöffnen, `settings.toml` (inkl. defekter Datei) und Pfad-Rebase
- Karte: Tracklinie, Fotomarker, Cluster je Tag, Übernachtung/Ort, offline ohne OSM
- Timeline: Tage aus Aufnahmezeit, manuelle Texte bleiben, Ortsvorschläge, Übernachtungen, Tagebuch-Flags
- Export- und Provider-*Verträge* existieren

### 5.2 Bewusst noch ohne Automatisierung

| Lücke | FA | Grund / nächste Phase |
| --- | --- | --- |
| Visuelle Marker-Vorschau / Cluster in Qt | FA-050, FA-051 | Szene automatisiert in `test_maps.py`; visuell MT-12 |
| Timeline-/Tagebuch-Bedienung | FA-060–FA-064, FA-080 | Logik in `test_timeline.py`; visuell MT-13 |
| Galeriefilter in der UI | FA-101 | Logik der Liste automatisiert; Filter nur MT-09 |
| Zuletzt verwendete Projekte in der UI | FA-091 | `recent.json` ohne Oberfläche; manuell nicht zwingend |
| HTML-/PDF-/LaTeX-Ausgabe | FA-121–FA-123 | Phase 8 |
| Qualitätskennzahlen | FA-070 | Phase 9 |
| pHash/dHash, Dublettengruppen | FA-071 | Phase 10 |
| Importliste „alle Dateien“ (kein 250er-Limit) | FA-025 | nur manuell / GUI, kein Unit-Test der Qt-Tabelle |
| Originale unverändert | FA-023 | implizit (nur Lese-APIs); Thumbnail-Tests prüfen mtime |
| IPTC | FA-030 | ausstehend |
| Video-Metadaten live mit ffprobe | FA-038 | Adapter + optionales Binary |
| pytest-qt Bedienung Import-Button | FA-092 | geplant |

Qualität und perceptual hashing entstehen mit den Phasen 9–10; die Verträge `QualityAnalyzer` und `RankingStrategy` sind importierbar.

---

## 6. Bewertung und Fehlerklassen

| Ergebnis | Bedeutung |
| --- | --- |
| **Bestanden** | Asserts grün; bei manuellem Fall beobachtetes Soll |
| **Fehlgeschlagen** | Regression; Phase nicht abschließen |
| **Blockiert** | Umgebung (kein venv, Qt-Plugin fehlt) |
| **Nicht ausführbar** | Feature der Phase noch nicht gebaut |

Schweregrade für manuelle Funde:

| Klasse | Beispiel |
| --- | --- |
| Kritisch | Originale werden geschrieben; Import bricht komplett ab; Datenverlust in `project.sqlite` |
| Hoch | HEIC-GPS/Kamera leer trotz vorhandener Metadaten; Liste verkürzt; Zeitzone fälschlich UTC; manueller Text nach Timeline-Abgleich weg |
| Mittel | Fortschritt ungenau; Kamera-String unschön; Ortsvorschlag zu grob |
| Niedrig | Beschriftung, Abstände |

---

## 7. Manuelle Testfälle (Phase 3 bis 7)

Voraussetzung: App starten mit

```powershell
.\.venv\Scripts\python.exe -m traveljournal
```

Testdaten: **Kopie** eines Fotoordners, niemals das einzige Originalarchiv als Experimentierfläche für Explorer-Unfälle — die App selbst ändert Originale nicht, der Tester könnte es tun.

### MT-01 Projekt anlegen und wieder öffnen

| Schritt | Erwartung |
| --- | --- |
| Neues Projekt in leerem Ordner | `project.sqlite` plus `settings.toml` und Unterordner `thumbnails`, `cache`, `exports`, `logs` |
| App schließen, denselben Ordner öffnen | Name und späterer Importzustand erhalten |

### MT-02 JPEG mit EXIF

| Schritt | Erwartung |
| --- | --- |
| Ordner mit JPEG (Aufnahmezeit, GPS, Kamera) analysieren | Tabelle: Zeit nicht nur Dateisystem; GPS dezimal; Kamera gesetzt; Quelle nachvollziehbar |
| Datei im Explorer unverändert lassen, erneut analysieren | „unverändert“ > 0, Werte bleiben |

### MT-03 HEIC von iPhone (Regression)

| Schritt | Erwartung |
| --- | --- |
| Ordner mit HEIC (Ortungsdienste an) analysieren | GPS gesetzt (exif oder quicktime), Kamera z. B. Apple iPhone … |
| Nach Software-Update erneut analysieren, wenn GPS/Kamera vorher leer waren | Felder werden nachgezogen, Originale unverändert (mtime/Größe) |

Ohne ExifTool auf dem PATH muss dasselbe gelten.

### MT-04 Vollständige Liste

| Schritt | Erwartung |
| --- | --- |
| Quelle mit mehr als 250 unterstützten Dateien | Tabellenzeilen = indexierte Dateien; Zähler und Fußzeile („N Dateien in der Liste“) stimmen überein |
| Klick oder Mouseover auf eine Fotozeile | Rechts: Vorschaubild (nach Thumbnail-Lauf) und Metadaten inkl. GPS/Kamera |

### MT-05 Defekte Datei

| Schritt | Erwartung |
| --- | --- |
| Gültiges JPEG plus Datei `broken.jpg` mit Zufallsbytes | Import endet; Fehlerzähler ≥ 1; gültiges Foto in der Liste |

### MT-06 GUI blockiert nicht

| Schritt | Erwartung |
| --- | --- |
| Import mehrerer hundert HEIC | Fenster bleibt verschiebbar, Fortschritt zählt Dateien |

### MT-07 Datenschutz / Schreibverbot

| Schritt | Erwartung |
| --- | --- |
| Vorher/Nachher Hash oder mtime einer Quell-HEIC | unverändert |
| Kein Netzmonitor nötig; es dürfen keine Upload-Versuche sichtbar sein | erfüllt im Standardbetrieb |

### MT-08 Projekteinstellungen

| Schritt | Erwartung |
| --- | --- |
| Projekt → Einstellungen: GPS-Zeitfenster, Standardzeitzone, Kartenanbieter | Werte in `settings.toml`; Originale unverändert |
| Wurzelverzeichnis auf einen verschobenen Ordner setzen | Index-Pfade umgeschrieben, Dateien selbst nicht bewegt |
| Kartenanbieter `offline` | Karte ohne OSM-Kacheln, Track und Marker bleiben |

### MT-09 Galeriefilter und Favoriten

| Schritt | Erwartung |
| --- | --- |
| Seite **Fotos**: Filter Jahr / Mit Ort / JPEG / Favorit / Nicht im Tagebuch | sichtbare Menge ändert sich; Zähler „N von M Fotos“ |
| Favorit umschalten, Projekt schließen und öffnen | Favorit bleibt |
| Doppelklick | Vorschau mit Zeit, GPS, Kamera |

### MT-10 Foto ohne GPS, GPX im selben Ordner

| Schritt | Erwartung |
| --- | --- |
| JPEG ohne Koordinaten, Aufnahmezeit bekannt; GPX mit Punkten ±10 s um diese Zeit (UTC bzw. Offset am Foto) | GPS-Spalte zeigt Koordinaten und `(gpx_interpolated)` oder `(gpx_nearest)`; Zähler „mit Ort“ steigt; EXIF-Fotos unverändert |

### MT-11 Galerie

| Schritt | Erwartung |
| --- | --- |
| Nach Import Seite **Fotos** öffnen | Vorschaubilder, chronologisch; Doppelklick zeigt Metadaten |
| HEIC ohne eingebettetes JPEG (HEIF Image Extensions installiert) | echtes Vorschaubild, kein Absturz |
| HEIC ohne Codec/Erweiterung | Platzhalter, kein Absturz |

### MT-12 Karte

| Schritt | Erwartung |
| --- | --- |
| Nach Import mit GPX und Fotos (mit oder ohne EXIF-GPS) Seite **Karte** öffnen | Track als Linie mit Datum, Fotos als Marker mit Datum; Klick zeigt Datum und Dateiname sowie ggf. Vorschaubild |
| Nahe Marker | Cluster, aufklappbar; Tagesfarben unterscheidbar |
| Übernachtung im Tagebuch mit GPS anlegen | schwarzer Home-Marker auf der Karte |
| Bestätigter Ort | grauer Flag-Marker |

### MT-13 Timeline und Tagebuch

| Schritt | Erwartung |
| --- | --- |
| Nach Import Seite **Timeline** öffnen bzw. **Timeline aktualisieren** | ein Tag je Aufnahmedatum; Fotos am Kalendertag der Aufnahmezeit; Auto-Ereignis mit Medienzähler |
| GPS-Fotos am selben Ort | kein automatischer Ortsname; Tag zeigt das Datum. Orte nur manuell im Tagebuch |
| Ort löschen, erneut abgleichen | kein neuer Auto-Ortsname |
| Seite **Tagebuch**: Titel und Text speichern, Projekt schließen und öffnen | Text noch da, `origin=manual`; erneuter Timeline-Abgleich überschreibt den Text nicht |
| Foto-Häkchen und Titelbild | `used_in_journal` / `is_cover` bleiben nach erneutem Öffnen; Foto bleibt am Aufnahmetag |
| Alle ins Tagebuch / Alle entfernen | nur das Häkchen ändert sich, nicht der Tag |
| Übernachtung mit Name, Ort, optional GPS | erscheint in Timeline, Tagebuch und auf der Karte; Löschen entfernt sie überall |

## 8. Manuelle Fälle ab Phase 8 (Vorschau)

Diese Fälle werden mit der jeweiligen Phase verbindlich.

| ID | Phase | Kurzbeschreibung |
| --- | --- | --- |
| MT-14 | 8 | HTML-Export öffnet sich im Browser, lokale Bilder, kein Server |
| MT-15 | 8 | Export schreibt nach `exports/`, Originale unverändert |
| MT-16 | 9 | Qualitätswerte sind Empfehlung, kein Löschen |
| MT-17 | 10 | Dublettengruppe, Originale bleiben |

---

## 9. Wiederholstrategie

| Anlass | Pflicht |
| --- | --- |
| Jede Codeänderung an `travelcore.metadata` oder Import | `pytest` vollständig |
| HEIC-/GPS-Parser | zusätzlich `test_heic_gps.py`, `test_indexer.py`, manuell MT-03 |
| Timeline / Tagebuch | `test_timeline.py`, manuell MT-13 |
| UI-Importliste | MT-04 |
| Vor Phasenabschluss | pytest grün + manuelle Fälle der Phase + Ruff |

Ein Phasenabschluss ohne grüne Automatisierung gilt als nicht abgenommen.

---

## 10. Nachweis der letzten Automatisierungsfahrt

| Datum | Kommando | Ergebnis |
| --- | --- | --- |
| 18.08.2026 | `python -m pytest` im Projekt-venv | 98 bestanden |

Diese Zeile bei der nächsten vollständigen Fahrt fortschreiben.
