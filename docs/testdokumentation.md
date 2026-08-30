# Testdokumentation — Reisetagebuch

| Feld | Inhalt |
| --- | --- |
| Version | 2.2 |
| Stand | 30. August 2026 |
| Bezugsversion Software | Phase 7, Software **R2.2.0** |
| Bezug | [pflichtenheft.md](pflichtenheft.md), [konzept.md](konzept.md), [packaging/README.md](../packaging/README.md) |

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
| Unit | `packages/travelcore/tests/` | pytest | Typen, Hash, Zeit, GPS, Provider, HEIC-Container, GPX/IGC/KML, Interpolation, ExifTool-JSON, Thumbnails, Orientierung, Timeline, Abschnitte, History-Snapshots |
| Integration | `packages/travelcore/tests/test_indexer.py`, `test_database.py`, `test_timeline.py`; `tests/integration/`; `tests/test_edit_history.py` | pytest | Projektordner, Schema, Index → SQLite, Timeline-Sync, Re-Open, Workspace-Undo |
| GUI-Rauch | `tests/test_gui_smoke.py` | pytest + Qt offscreen | Hauptfenster, sechs Seiten, Menü **Bearbeiten**, Inspektor, Register, Titel mit Version, Timeline-Speichern nur bei Abschnitten/Texten/Reisetitel/YouTube |
| Paketierung | `packaging/` | manuell nach `build.ps1` | Frozen-EXE startet, Alembic/Karte, kein Python nötig (MT-22) |
| Manuell | dieses Dokument, Abschnitt 7 | Windows-Desktop | Import echter HEIC/JPEG, Liste, Timeline, Abschnitte, Karte, Inspektor, Undo/Redo |
| Statisch | Repository-Wurzel | Ruff, später pyright | Stil, Imports, grundlegende Typen |

Nicht eingeführt (geplant): pytest-qt für Interaktion, visuelle Galerie-/Kartentests, Lasttest mit zehntausenden Dateien.

---

## 3. Umgebung und Ausführung

### 3.1 Voraussetzungen

- Windows 10/11
- Python 3.12 im Projekt-venv (nicht eine fremde `python.exe` auf dem PATH)
- Installierte Editables: `travelcore`, `traveljournal`
- pytest (und ruff für die statische Prüfung)

MT-22 (Windows-Paket) braucht zusätzlich das Ergebnis von `packaging/build.ps1`, nicht das venv.

ExifTool ist **kein** Testdependency. HEIC- und Provider-Tests müssen ohne das Binary bestehen. ExifTool wird nur über fest verdrahtete JSON-Fixtures geprüft.

### 3.2 Befehle

```powershell
cd D:\20-GITWorkspace\desktop-apps
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m pytest packages/travelcore/tests/test_timeline.py -q
.\.venv\Scripts\python.exe -m ruff check packages apps tests
.\.venv\Scripts\python.exe -m ruff format --check packages apps tests
```

Konfiguration: `[tool.pytest.ini_options]` in der Repository-`pyproject.toml` (`testpaths`, `pythonpath`).

GUI-Rauchtest setzt `QT_QPA_PLATFORM=offscreen`, falls nicht gesetzt.

### 3.3 Hilfsprogramm JSON → GPX

`scripts/json_routes_to_gpx.py` wandelt Polar-Trainings-JSON mit nichtleerer
`routes`-Sektion in eine GPX-Datei neben der JSON-Datei. Aufruf und Kurzhilfe:
[README.md](../README.md) (Abschnitt *JSON nach GPX*). Tests:
`tests/test_json_routes_to_gpx.py`.

```powershell
.\.venv\Scripts\python.exe scripts\json_routes_to_gpx.py -h
.\.venv\Scripts\python.exe scripts\json_routes_to_gpx.py -f D:\tracks\session.json
.\.venv\Scripts\python.exe scripts\json_routes_to_gpx.py -d D:\tracks -r
```

```
usage: json_routes_to_gpx.py [-h] [-f DATEI] [-d VERZEICHNIS] [-r]

Erzeugt GPX-Tracks aus JSON-Dateien mit nichtleerer Routes-Sektion.

  -f DATEI        einzelne JSON-Datei
  -d VERZEICHNIS  Ordner mit JSON-Dateien
  -r              mit -d auch Unterverzeichnisse einbeziehen
```


### 3.4 Testdatenregel

| Erlaubt | Verboten |
| --- | --- |
| Von Pillow erzeugte Mini-JPEGs | Originale aus dem Urlaub |
| Synthetische HEIC-*Bytes* (kein echtes Bild nötig) | Dateien mit echten Personen/GPS aus Produktivimporten |
| Feste Beispielkoordinaten in Tests (z. B. 46.5 °N, 11.35 °E) | Kopieren von `project.sqlite` mit Nutzerdaten ins Repo |
| Minimal-JPEG (`FF D8 … FF D9`) | Große Videos als Fixtures |

Hilfsmodul: `packages/travelcore/tests/jpeg_fixtures.py`. GPX-Hilfen: `gpx_fixtures.py`.

---

## 4. Abbildungsmatrix Pflichtenheft → automatisierte Tests

Stand nach `pytest --collect-only`: **355 Tests** (28. August 2026). Neue Tests sind ergänzend zu führen, nicht still zu löschen.

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

### 4.2 Index, Hash, Fehler — FA-020 bis FA-026, FA-095

| Test | Datei | Prüft |
| --- | --- | --- |
| `test_sha256_of_known_content` | `test_hashing.py` | bekannte Prüfsumme |
| `test_identical_files_share_hash` | `test_hashing.py` | gleiche Bytes → gleicher Hash |
| `test_different_files_differ` | `test_hashing.py` | unterschiedliche Bytes |
| `test_indexer_writes_source_files` | `test_indexer.py` | Foto+GPX im Index, SHA-256, Dateisystemzeit als Fallback |
| `test_indexer_skips_unchanged_files` | `test_indexer.py` | zweiter Lauf zählt `skipped_unchanged` |
| `test_plan_source_sync_counts_new_and_missing` | `test_indexer.py` | Diff neue vs. fehlende Dateien |
| `test_indexer_keeps_missing_files_without_sync_flag` | `test_indexer.py` | Analyse löscht keine fehlenden Dateien |
| `test_indexer_sync_removes_missing_photo_from_journal` | `test_indexer.py` | Sync: Index, Mitgliedschaft, Cover, Fehler, Thumb weg; Neue im Pool |
| `test_indexer_sync_deletes_gps_track_for_missing_gpx` | `test_indexer.py` | fehlende GPX löscht Track und Punkte |
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
| `test_schema_contains_core_tables` | `test_database.py` | Kern-Tabellen inkl. `source_files`, `trips`, `trip_sections`, `photo_analyses`; Spalten `rotation_degrees`, `sort_status`, Cover- und URL-Felder |
| `test_folder_name_from_project_name_strips_invalid_chars` | `test_database.py` | ungültige Ordnerzeichen entfernt |
| `test_create_under_uses_name_as_subdirectory` | `test_database.py` | Anlegen unter Stammordner |
| `test_create_under_sanitizes_folder_but_keeps_display_name` | `test_database.py` | Anzeigename bleibt, Ordnername bereinigt |
| `test_create_under_rejects_existing_project` | `test_database.py` | bestehendes Projekt nicht überschreiben |
| `test_create_under_rejects_empty_name` | `test_database.py` | leerer Name abgelehnt |
| `test_sqlite_waits_when_busy` | `test_database.py` | Busy-Timeout statt sofortigem Fehler |
| `test_new_project_writes_settings_file` | `test_project_settings.py` | Default-`settings.toml` |
| `test_normalize_stay_link_color_accepts_hex_and_falls_back` | `test_project_settings.py` | Linienfarbe Hex / Fallback weiß |
| `test_settings_roundtrip_preserves_values` | `test_project_settings.py` | Exportformat, Wurzel, Zeitzone, CPU-Worker, Kartenzahnrad |
| `test_corrupt_settings_raise` | `test_project_settings.py` | unlesbares TOML → `ProjectError` |
| `test_ensure_fills_source_root_from_database` | `test_project_settings.py` | fehlende Wurzel aus der DB nachziehen |
| `test_rebase_rewrites_indexed_paths` | `test_project_settings.py` | Pfad-Rebase ohne Original-Move |
| `test_project_survives_close_and_reopen` | `tests/integration/test_project_lifecycle.py` | Index überlebt Re-Open |
| `test_exporters_share_interface` | `test_interfaces.py` | HTML/PDF/LaTeX/CEWE sind `Exporter` |
| `test_protocols_are_importable` | `test_interfaces.py` | `MetadataProvider`, `RankingStrategy`, `MapBackend` |
| `test_main_window_starts` | `tests/test_gui_smoke.py` | Titel mit Version R2.2.0, Menü **Bearbeiten** mit Strg+Z/Strg+Y, Pipeline mit Symbolen, eingeklappt nur Icons, ausgeklappt inhaltsbreit, Medienregister, Import **Synchronisieren** |

### 4.7 GPX und zeitliche Zuordnung — FA-040 bis FA-042

| Test | Datei | Prüft |
| --- | --- | --- |
| `test_parse_gpx_track_and_segment` | `test_gpx_parse.py` | Punkte, Höhe, UTC-Zeit, Segment-ID |
| `test_convert_file_writes_sibling_gpx` | `tests/test_json_routes_to_gpx.py` | Polar-JSON Routes → GPX neben der Datei (Hilfsskript) |
| `test_directory_mode_prints_dots_and_counts` | `tests/test_json_routes_to_gpx.py` | `-d` / `-r`, Punkte und Zähler `JSON n, GPX m` |
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
| `test_ensure_thumbnail_skips_huge_png` | `test_thumbnails.py` | PNG über der Pixelgrenze ohne Thumb |
| `test_ensure_thumbnail_drafts_huge_jpeg` | `test_thumbnails.py` | JPEG über der Pixelgrenze per Draft |
| `test_corrupt_jpeg_returns_none` | `test_thumbnails.py` | kein Absturz, keine Zieldatei |
| `test_heic_uses_embedded_jpeg_preview` | `test_thumbnails.py` | Fake-HEIC mit JPEG-Payload |
| `test_heic_jpeg_item_becomes_thumbnail` | `test_thumbnails.py` | HEIF-`jpeg`-Item über `iinf`/`iloc` |
| `test_windows_heic_helper_handles_garbage` | `test_thumbnails.py` | defekte Bytes → `None`, kein Absturz |
| `test_extract_largest_embedded_jpeg` | `test_thumbnails.py` | größtes eingebettetes JPEG |
| `test_cached_thumbnail_path_uses_hash` | `test_thumbnails.py` | Cache-Dateiname enthält SHA-256 |
| `test_cached_thumbnail_path_includes_rotation` | `test_thumbnails.py` | `_r90` im Cachepfad bei Drehung |
| `test_ensure_thumbnail_applies_display_rotation` | `test_thumbnails.py` | 90°-Drehung ändert Pixel, Original unverändert |
| `test_gpx_thumbnail_is_red_track_on_map` | `test_thumbnails.py` | GPX-Vorschau: rote Spur |
| `test_igc_thumbnail_is_red_track_on_map` | `test_thumbnails.py` | IGC-Vorschau: rote Spur |
| `test_empty_gpx_does_not_write_thumbnail` | `test_thumbnails.py` | leere GPX ohne Thumb |
| `test_kml_thumbnail_is_red_track_on_map` | `test_thumbnails.py` | KML-Vorschau |
| `test_geojson_thumbnail_is_red_track_on_map` | `test_thumbnails.py` | GeoJSON-Vorschau |
| `test_gpx_thumbnail_falls_back_to_black_without_map_tiles` | `test_thumbnails.py` | ohne OSM-Kacheln schwarzer Hintergrund |
| `test_raw_uses_embedded_jpeg_preview` | `test_thumbnails.py` | RAW-Vorschau aus eingebettetem JPEG |
| `test_video_uses_embedded_jpeg_preview` | `test_thumbnails.py` | Video-Vorschau aus eingebettetem JPEG |
| `test_video_without_preview_writes_placeholder` | `test_thumbnails.py` | Platzhalter ohne Preview |
| `test_indexer_writes_thumbnail_and_photo_row` | `test_indexer.py` | Cache + `photos`-Zeile |
| `test_indexer_writes_igc_and_gpx_thumbnails` | `test_indexer.py` | Track-Thumbs beim Import |
| `test_indexer_writes_video_thumbnail` | `test_indexer.py` | Video-Thumb beim Import |
| `test_indexer_does_not_regenerate_thumbnails_on_reimport` | `test_indexer.py` | Re-Import schreibt vorhandene Thumbs nicht neu |
| `test_indexer_does_not_count_thumbnails_when_source_is_project` | `test_indexer.py` | Projektordner als Quelle zählt Thumbs nicht als Fotos |
| `test_indexer_drops_previously_indexed_thumbnails` | `test_indexer.py` | bereits indexierte Thumbs werden entfernt |
| `test_indexer_can_defer_thumbnails` | `test_indexer.py` | Index ohne Thumbs, danach `build_previews` |
| `test_indexer_writes_thumbnails_in_parallel` | `test_indexer.py` | vier Vorschaubilder per ProcessPool |
| `test_effective_sort_status_prefers_stored_value` | `test_gallery.py` | gespeicherter `sort_status` vor Favoriten-Flag |
| `test_effective_sort_status_falls_back_to_favorite_flag` | `test_gallery.py` | leerer Status plus Favorit gilt als Favorit |

### 4.9 Karte — FA-050 bis FA-053

| Test | Datei | Prüft |
| --- | --- | --- |
| `test_downsample_keeps_endpoints` | `test_maps.py` | Trackpunkte werden ausgedünnt, Start/Ende bleiben |
| `test_map_scene_has_track_and_photo` | `test_maps.py` | Übersicht ein Cover, Detail: Polylinie + Fotomarker |
| `test_map_scene_includes_place` | `test_maps.py` | Ort im Detail des Tags |
| `test_folium_overview_cover_uses_expand_url` | `test_maps.py` | rundes Cover, Expand-Bridge, Zoom-Halt, Popup-Skript (Blättern, `centerBrowseView` vor `openPopup`, `lockPopupImageBox`, Fit-Reise, Cover-Aktivierung), Aufenthaltslinien, Layer-Menü Straßenkarte/Topo/Satellit, Zahnrad, Symbol-Spiegelung in eigenem Wrapper |
| `test_overview_offline_omits_satellite` | `test_maps.py` | ohne Kacheln kein Layer-Umschalter, Zahnrad bleibt |
| `test_timeline_js_cards_uses_relative_cover` | `test_maps.py` | Timeline-Karten relative Cover-Pfade |
| `test_leaflet_payload_includes_source_file_id` | `test_maps.py` | Detail-Payload: `source_file_id` an Marker und Track, Thumbnail-Popup, Blickrichtung |
| `test_detail_stacks_nearby_photos_until_zoom_17` | `test_maps.py` | Stapel bis Zoom 16, Anzahl, ab 17 einzeln mit Spreizung und Linie; Orte ungestapelt |
| `test_pick_cover_item_skips_rejected` | `test_maps.py` | Aussortierte Cover fallen raus |
| `test_pick_cover_item_uses_display_position` | `test_maps.py` | Cover nutzt Journal-Anzeigeposition |
| `test_position_for_cover_prefers_display_over_original` | `test_maps.py` | Overlay vor Original-GPS |
| `test_map_detail_follows_section_members_after_move` | `test_maps.py` | Detail und Cover folgen dem Abschnitt, nicht der Aufnahme |
| `test_count_card_media_splits_reserve_and_skips_rejected` | `test_maps.py` | Reserve getrennt, Aussortierte nie; IGC separat von GPX |
| `test_photo_fov_degrees_from_35mm` | `test_maps.py` | Kegelwinkel aus 35-mm-Brennweite |
| `test_map_detail_omits_rejected_photo` | `test_maps.py` | Aussortierte Fotos nicht im Detail; Heading/FOV am Marker |
| `test_folium_backend_writes_html` | `test_maps.py` | Leaflet-HTML, `MapBackend` |
| `test_offline_backend_omits_osm_tiles` | `test_maps.py` | `tiles=None` ohne OSM-URL |
| `test_map_scene_includes_igc_flight` | `test_maps.py` | IGC-Polylinie, Pilot, DHV-Link, Zoom-Skript |
| `test_map_cache_reuses_html_when_inputs_unchanged` | `test_maps.py` | Disk-Cache ohne Rebuild |
| `test_map_cache_rebuilds_when_provider_or_force_changes` | `test_maps.py` | Cache-Invalidierung |
| `test_map_cache_rebuilds_when_link_color_changes` | `test_maps.py` | Cache neu bei geänderter Linienfarbe |
| `test_pick_cover_item_uses_first_photo` | `test_maps.py` | ohne Titelbild erstes Foto |
| `test_pick_cover_item_uses_first_track_without_photo` | `test_maps.py` | ohne Foto erster Track |
| `test_pick_cover_youtube_uses_first_link` | `test_maps.py` | YouTube-Cover-URL |
| `test_youtube_only_section_uses_youtube_cover` | `test_maps.py` | Abschnitt nur mit YouTube als Cover |
| `test_parse_group_key_accepts_section_day_and_loose` | `test_maps.py` | `section:` / `day:` / `loose:` |
| `test_build_map_timeline_cards_from_section` | `test_maps.py` | Leistenkarten aus Abschnitt inkl. Text und YouTube; `map_group_key_for_source` |
| `test_unplaced_section_gets_pin_cover` | `test_maps.py` | leerer Abschnitt ohne GPS, Pin wird Cover |
| `test_stay_links_connect_days_and_stays_in_timeline_order` | `test_maps.py` | Linien zwischen Tag- und Aufenthaltskreisen in Timeline-Reihenfolge |
| `test_stay_links_connect_leftover_days` | `test_maps.py` | Tage mit GPS werden verbunden |
| `test_build_map_overview_links_leftover_days` | `test_maps.py` | Übersicht verbindet Tage mit GPS |
| `test_stay_links_skip_transfer_as_endpoint` | `test_maps.py` | Transfer-Kreis ist kein Linienende; Hub und `transfer_key` für Symbolsteg |
| `test_stay_links_mark_transfer_between_stays` | `test_maps.py` | Transfer zwischen Endpunkten setzt `via_transfer` |
| `test_save_and_reorder_transfer_links` | `test_transfer_links.py` | Kindtabelle, Reihenfolge, Mode-Cache |
| `test_park_media_clears_track_choice` | `test_transfer_links.py` | Spurwahl wird geleert, Geometrie bleibt Track |
| `test_gap_filler_between_cover_and_track` | `test_transfer_links.py` | gepunktete Stummel Cover↔Spur |
| `test_stay_links_use_first_transfer_segments` | `test_transfer_links.py` | erster Transfer liefert Segmente |
| `test_transfer_link_row_keeps_dashed` | `tests/test_gui_smoke.py` | Transfer-Zeile behält gestrichelt; Verkehrsmittel mit Symbol vor dem Namen |
| `test_stay_links_use_left_outbound_when_next_is_not_transfer` | `test_maps.py` | Tag/Aufenthalt-Ausgangslinie ohne Transfer dazwischen; Punkte vom linken zum rechten Cover |
| `test_stay_links_omit_when_left_outbound_is_hidden` | `test_maps.py` | Keine Linie: keine StayLink-Kante |
| `test_normalize_outbound_treats_straight_solid_as_empty` | `test_timeline_sections.py` | Standard = keine gespeicherten outbound-Felder; `none` bleibt `none` |
| `test_kind_change_copies_outbound_to_transfer_and_back` | `test_timeline_sections.py` | Typwechsel übernimmt Linie/Bogen |
| `test_kind_change_hidden_outbound_does_not_seed_transfer` | `test_timeline_sections.py` | Keine Linie wird nicht zur Transfer-Liste |
| `test_stay_links_skip_stays_without_gps` | `test_maps.py` | Aufenthalt ohne GPS ist kein Linienende |
| `test_stay_link_hidden_when_covers_overlap` | `test_maps.py` | Linie unsichtbar, wenn Kreise sich überdecken |
| `test_transport_symbols_cover_movement_modes` | `test_symbols.py` | Katalog-Keys = `MOVEMENT_MODES` |
| `test_symbol_badge_is_white_on_black` | `test_symbols.py` | Badge ohne Rotation außer Flugzeug; Camper/Van im Katalog nach rechts gespiegelt |
| `test_stay_symbol_svg_js_lists_every_key` | `test_symbols.py` | Leaflet-Helfer enthält jeden Katalog-Key |
| `test_build_map_overview_links_consecutive_stays` | `test_maps.py` | Übersicht verbindet zwei Aufenthalte über einen Transfer |
| `test_parse_map_bridge_url_reads_group_key` | `tests/test_gui_smoke.py` | Expand-URL, Konsolen-Bridge, Platzieren-Konsole, Zoom/Ausschnitt nach Platzieren |
| `test_map_view_refresh_uses_disk_cache_without_rebuild` | `tests/test_gui_smoke.py` | MapView zeigt Cache; Leiste unter dem WebView |
| `test_publish_map_display_writes_unique_file` | `tests/test_gui_smoke.py` | WebEngine lädt eine neue HTML-Kopie nach Rebuild |
| `test_map_view_applies_prepared_result_when_shown` | `tests/test_gui_smoke.py` | Hintergrund-Karte wird beim Öffnen der Seite übernommen |
| `test_map_timeline_strip_centers_first_card` | `tests/test_gui_smoke.py` | Leiste zentriert; Transfer-Sechseck; Zähler; Plus; Rechtsklick Platzieren/Verschieben/Zentrieren; Cursor folgt der Karte |
| `test_strip_click_closes_detail_and_zooms_cover` | `tests/test_gui_smoke.py` | andere Leistenkarte schließt Detail und `ZoomToCover`; dieselbe Karte bleibt im Detail |
| `test_inspector_map_opens_thumbnail_then_original_on_double_click` | `tests/test_gui_smoke.py` | Inspektor: Vorschau, Doppelklick Original |

### 4.10 Timeline — FA-014, FA-060 bis FA-063, FA-080 bis FA-082

| Test | Datei | Prüft |
| --- | --- | --- |
| `test_cluster_stays_joins_nearby_points` | `test_timeline.py` | GPS-Punkte im Radius bilden einen Cluster |
| `test_cluster_stays_splits_distant_points` | `test_timeline.py` | entfernte Punkte bleiben getrennt |
| `test_sync_timeline_creates_one_day_per_date` | `test_timeline.py` | zwei Aufnahmedaten → zwei Tage, Auto-Ereignis „1 Medien“ |
| `test_manual_day_text_survives_resync` | `test_timeline.py` | Titel/Text `origin=manual` bleibt nach Sync |
| `test_manual_trip_title_survives_resync` | `test_timeline.py` | Reisetitel `origin=manual` bleibt nach Sync |
| `test_place_suggestion_not_auto_assigned_to_gps_media` | `test_timeline.py` | Import vergibt keinen Ortsnamen; opt-in-Vorschlag und Bestätigen |
| `test_journal_flags_and_cover` | `test_timeline.py` | `used_in_journal`, Titelbild |
| `test_youtube_urls_roundtrip_on_day` | `test_timeline.py` | YouTube-URLs am Tag |
| `test_leonardo_urls_roundtrip_on_day` | `test_timeline.py` | DHV-Leonardo-URLs am Tag |
| `test_sync_prefills_title_and_notes_from_imported_text` | `test_timeline.py` | TXT/MD füllt leeren Tag |
| `test_imported_text_does_not_overwrite_manual_day` | `test_timeline.py` | manueller Text bleibt |
| `test_text_only_note_creates_a_day` | `test_timeline.py` | Nur-Text erzeugt einen Tag |
| `test_photo_sort_status_keeps_favorite_in_sync` | `test_timeline.py` | `sort_status` und `is_favorite` |
| `test_source_rotation_is_stored_and_used_for_thumbs` | `test_timeline.py` | `rotation_degrees` steuert Cache |
| `test_indexer_preserves_rotation_on_reingest` | `test_indexer.py` | Re-Import überschreibt Nutzerdrehung nicht |
| `test_parse_markdown_heading` | `test_timeline_texts.py` | `# Titel` |
| `test_parse_first_line_as_title` | `test_timeline_texts.py` | erste Zeile als Titel |
| `test_parse_falls_back_to_filename_when_first_line_is_long` | `test_timeline_texts.py` | langer Text → Dateiname |
| `test_date_and_title_from_filename` | `test_timeline_texts.py` | Datum im Dateinamen |
| `test_combine_imported_texts_uses_first_title` | `test_timeline_texts.py` | mehrere Texte, erster Titel |

### 4.11 Reiseabschnitte, Pool und Journal-Zeit — FA-064 bis FA-067, FA-083, FA-084

| Test | Datei | Prüft |
| --- | --- | --- |
| `test_expand_range_selection_fills_between_first_and_last` | `test_timeline_sections.py` | Bereich zwischen erstem und letztem Klick |
| `test_parse_and_serialize_transfer_modes` | `test_timeline_sections.py` | Verkehrsmittel-Liste |
| `test_format_section_span_uses_object_dates` | `test_timeline_sections.py` | `am …` / `von … bis …` |
| `test_format_card_dates_omits_am_von_bis` | `test_timeline_sections.py` | Kartenkopf: `12.12.2026` bzw. `11.11.2026 - 21.11.2026` |
| `test_format_scroll_date_is_compact` | `test_timeline_sections.py` | kompaktes Datum am Timeline-Schieber |
| `test_insert_dates_between_uses_open_gap` | `test_timeline_sections.py` | Datum der Lücke zwischen zwei Karten |
| `test_create_section_same_day_is_am` | `test_timeline_sections.py` | Aufenthalt am selben Kalendertag |
| `test_dissolve_section_returns_files_to_day_sections` | `test_timeline_sections.py` | Auflösen → Tage nach Journal-Zeit |
| `test_create_empty_section_uses_manual_date` | `test_timeline_sections.py` | leerer Abschnitt mit manuellem Datum |
| `test_span_for_manual_dates_tag_and_range` | `test_timeline_sections.py` | Tag am, Aufenthalt/Transfer von–bis, Ende vor Start abgelehnt |
| `test_create_empty_stay_keeps_von_bis_span` | `test_timeline_sections.py` | leerer Aufenthalt mit von–bis |
| `test_empty_stays_sort_by_span_not_creation` | `test_timeline_sections.py` | leere Aufenthalte nach Spanne, `set_section_span` sortiert neu |
| `test_set_section_span_snaps_tag_members` | `test_timeline_sections.py` | Tag-Datum ändert Journal-Tag der Medien |
| `test_delete_section_parks_members_in_pool` | `test_timeline_sections.py` | Löschen legt Medien in den Pool |
| `test_apply_pending_empty_section_keeps_manual_date` | `test_timeline_sections.py` | leere Pending-Vorschau mit Datum |
| `test_apply_pending_empty_stay_keeps_range` | `test_timeline_sections.py` | leere Pending-Vorschau mit von–bis |
| `test_set_journal_at_moves_clip_to_other_day` | `test_timeline_sections.py` | Journal-Zeit über Mitternacht wechselt den Tag |
| `test_reset_journal_restores_original_day` | `test_timeline_sections.py` | Originalzeit stellt Aufnahmezeit und Tag wieder her |
| `test_dissolve_after_journal_move_uses_journal_date` | `test_timeline_sections.py` | Auflösen nach Verschieben folgt Journal-Tag |
| `test_resync_keeps_existing_journal_at` | `test_timeline_sections.py` | Re-Sync überschreibt Journal-Zeit nicht |
| `test_tag_without_gps_inherits_cover_position` | `test_timeline_sections.py` | Tag ohne GPS erbt Cover-Pin |
| `test_stay_without_gps_inherits_place` | `test_timeline_sections.py` | Aufenthalt ohne GPS erbt Ort live |
| `test_transfer_without_gps_inherits_track_time` | `test_timeline_sections.py` | Transfer ohne GPS liegt auf dem Track |
| `test_scattered_positions_do_not_coincide` | `test_timeline_sections.py` | Marker um Abschnittsposition versetzt |
| `test_move_members_keeps_original_gps_on_map` | `test_timeline_sections.py` | GPS behalten zeigt Originalposition |
| `test_move_members_adopts_section_position_and_scatters` | `test_timeline_sections.py` | ohne GPS-Behalten: Abschnitt, nicht übereinander |
| `test_snap_clock_to_section_clamps_into_span` | `test_timeline_sections.py` | Journal-Datum in die Abschnitts-Spanne |
| `test_move_members_adopts_target_section_date` | `test_timeline_sections.py` | Verschieben übernimmt das Zieldatum |
| `test_sort_members_by_journal_does_not_change_clock` | `test_timeline_sections.py` | Spur-Sortierung ändert die Uhr nicht |
| `test_section_cards_follow_calendar_not_creation_order` | `test_timeline_sections.py` | Abschnittskarten nach Kalendertag, nicht nach Anlage |
| `test_section_card_items_follow_journal_time` | `test_timeline_sections.py` | Medien auf der Karte nach Journal-Zeit |
| `test_day_section_sits_between_stays` | `test_timeline_sections.py` | Tag zwischen Abschnitten |
| `test_create_movement_section_from_last_day_files` | `test_timeline_sections.py` | Transfer aus Dateien |
| `test_transfer_mode_is_optional_and_can_be_multiple` | `test_timeline_sections.py` | mehrere Verkehrsmittel |
| `test_update_section_kind_switches_stay_and_transfer` | `test_timeline_sections.py` | Typ Aufenthalt ↔ Transfer |
| `test_apply_pending_sections_is_preview_only` | `test_timeline_sections.py` | Overlay schreibt nicht |
| `test_timeline_save_button_only_when_dirty` | `tests/test_gui_smoke.py` | Speichern nur bei Abschnitten, Reisetitel, Text, YouTube |
| `test_timeline_leave_without_prompt_when_only_text_dirty` | `tests/test_gui_smoke.py` | Seitenwechsel ohne Rückfrage bei nur dirty Text |
| `test_set_entry_cover_on_day_and_section` | `test_timeline_sections.py` | Foto als Eintrags-Titelbild |
| `test_set_entry_cover_accepts_gps_track` | `test_timeline_sections.py` | Track als Eintrags-Titelbild |
| `test_sync_assigns_media_to_day_sections` | `test_timeline_sections.py` | Import legt Auto-Tage mit Mitgliedern an |
| `test_parked_media_stay_out_of_days_on_resync` | `test_timeline_sections.py` | Pool-Medien bleiben außerhalb der Tage |
| `test_move_members_assigns_parked_file_to_section` | `test_timeline_sections.py` | Drop aus dem Pool auf einen Abschnitt |
| `test_move_to_other_day_keeps_captured_at` | `test_timeline_sections.py` | Verschieben ändert nur die Journal-Zeit |
| `test_dissolve_multi_day_stay_splits_by_original_date` | `test_timeline_sections.py` | Auflösen eines mehrtägigen Aufenthalts |
| `test_update_section_kind_rejects_multi_day_stay_to_tag` | `test_timeline_sections.py` | mehrtägiger Aufenthalt wird nicht zum Tag |

### 4.12 Links — FA-068, FA-069

| Test | Datei | Prüft |
| --- | --- | --- |
| `test_parse_and_serialize_youtube_urls` | `test_timeline_links.py` | YouTube-Liste |
| `test_normalize_youtube_url_rejects_other_hosts` | `test_timeline_links.py` | nur YouTube-Hosts |
| `test_parse_and_serialize_leonardo_urls` | `test_timeline_links.py` | DHV-Leonardo-Liste |
| `test_normalize_leonardo_url_requires_http` | `test_timeline_links.py` | kein `javascript:` |
| `test_is_igc_filename` | `test_timeline_links.py` | IGC-Erkennung |
| `test_youtube_video_id_and_thumbnail_url` | `test_timeline_links.py` | Vorschaubild-URL |

### 4.13 KML, GeoJSON, statische Karte — FA-043, FA-104

| Test | Datei | Prüft |
| --- | --- | --- |
| `test_parse_kml_linestring` | `test_kml_geojson.py` | KML-LineString |
| `test_parse_kml_gx_track` | `test_kml_geojson.py` | gx:Track |
| `test_parse_geojson_linestring` | `test_kml_geojson.py` | GeoJSON-LineString |
| `test_latlon_to_world_px_origin_at_zoom_zero` | `test_maps_static.py` | Weltpixel bei Zoom 0 |
| `test_leaflet_excerpt_paints_red_track_on_stub_tiles` | `test_maps_static.py` | rote Spur auf Stub-Kacheln |
| `test_leaflet_excerpt_falls_back_to_black_without_tiles` | `test_maps_static.py` | Fallback schwarz |
| `test_leaflet_provider_creates_tile_cache_dir` | `test_maps_static.py` | `cache/map_tiles/osmde` |
| `test_offline_provider_skips_osm_tiles` | `test_maps_static.py` | `offline` lädt keine Kacheln |

### 4.14 Anzeigedrehung — FA-022, FA-102

| Test | Datei | Prüft |
| --- | --- | --- |
| `test_normalize_rotation_degrees_snaps_to_right_angles` | `test_orientation.py` | 0/90/180/270 |
| `test_apply_display_rotation_clockwise_moves_top_left` | `test_orientation.py` | Pixelverschiebung |
| `test_orient_image_applies_exif_then_user_rotation` | `test_orientation.py` | EXIF zuerst, dann Nutzer |
| `test_can_rotate_photos_and_videos_not_tracks` | `test_orientation.py` | Tracks nicht drehbar |

### 4.15 GUI-Rauch — FA-064, FA-082, FA-085, FA-090, FA-092, FA-102, FA-103, FA-105

| Test | Datei | Prüft |
| --- | --- | --- |
| `test_app_window_title_includes_version` | `tests/test_gui_smoke.py` | `Reisetagebuch R2.2.0` |
| `test_source_sync_dialog_defaults_to_timeline` | `tests/test_gui_smoke.py` | Sync-Dialog: Timeline vorausgewählt, Pool wählbar |
| `test_source_sync_dialog_hides_destination_without_new_files` | `tests/test_gui_smoke.py` | ohne neue Dateien keine Timeline/Pool-Wahl |
| `test_entry_widget_separates_tracks_from_media` | `tests/test_gui_smoke.py` | getrennte Galerien |
| `test_entry_widget_track_can_be_cover` | `tests/test_gui_smoke.py` | T-Chip auf Track |
| `test_entry_widget_shows_cover_in_heading` | `tests/test_gui_smoke.py` | Titelbild 168 px im Kartenkopf |
| `test_entry_widget_falls_back_to_first_photo` | `tests/test_gui_smoke.py` | ohne T-Chip erstes Foto im Kartenkopf |
| `test_entry_widget_header_is_compact` | `tests/test_gui_smoke.py` | Titel oben, darunter Typ/Datum, danach Verbindungslinien |
| `test_entry_widget_section_has_to_map_button` | `tests/test_gui_smoke.py` | Zur Karte an Abschnitt und Tag |
| `test_entry_widget_thumbnail_opens_section_detail_on_map` | `tests/test_gui_smoke.py` | Rechtsklick Thumbnail → Zur Karte… öffnet Abschnittsdetail |
| `test_map_view_focus_group_media_keeps_pending_until_shown` | `tests/test_gui_smoke.py` | Foto-Fokus merkt Abschnitt und Medium bis die Karte sichtbar ist |
| `test_cascade_inspector_offsets_second_window` | `tests/test_gui_smoke.py` | mehrere Original-Fenster versetzt |
| `test_focus_group_media_last_press_wins_strip` | `tests/test_gui_smoke.py` | letzter Zur-Karte-Klick gewinnt Leiste und Foto |
| `test_focus_group_media_centers_image_section_and_keeps_detail` | `tests/test_gui_smoke.py` | Zur Karte: Abschnittskarte des Bildes, Detail bleibt |
| `test_focus_group_media_opens_section_detail_and_photo` | `tests/test_gui_smoke.py` | Zur Karte: Detailmodus und Foto nach Leistenfokus |
| `test_refresh_reuses_live_map_without_rebuild` | `tests/test_gui_smoke.py` | Zur Karte bei geladener Karte ohne HTML-Neuaufbau |
| `test_section_detail_payload_is_cached` | `tests/test_gui_smoke.py` | Abschnittsdetail nur einmal aus der Datenbank |
| `test_strip_set_cards_can_keep_requested_section` | `tests/test_gui_smoke.py` | Leiste zentriert gewünschte Karte ohne Folgefokus |
| `test_map_view_focus_group_centers_section_card` | `tests/test_gui_smoke.py` | MapView fokussiert die Abschnittskarte; Tagebuchtext rechts, YouTube-Thumbs unten rechts auf der Karte |
| `test_map_notes_edit_shows_save_cancel_discard` | `tests/test_gui_smoke.py` | Nach Edit Speichern, Abbrechen, Verwerfen |
| `test_map_notes_switch_card_opens_save_dialog` | `tests/test_gui_smoke.py` | Fokuswechsel bei ungespeichertem Tagebuchtext: Dialog Speichern/Abbrechen/Verwerfen |
| `test_entry_widget_media_tab_filters_favorites` | `tests/test_gui_smoke.py` | Register filtert Favoriten; Aussortierte nur unter Aussortiert |
| `test_matches_rating_hides_rejected_from_all` | `tests/test_gui_smoke.py` | Alle blendet Aussortierte aus |
| `test_timeline_pool_pane_lists_parked_media` | `tests/test_gui_smoke.py` | Pool-Spalte unabhängig von Abschnitten, eigenes Bewertungsregister |
| `test_timeline_pool_restores_width_after_collapse` | `tests/test_gui_smoke.py` | Einklappen merkt die Breite, Ausklappen stellt sie wieder her |
| `test_photos_view_pool_collapse_matches_timeline` | `tests/test_gui_smoke.py` | Medien: gleicher Pfeil, Breite bleibt |
| `test_photos_view_media_tab_filters_favorites` | `tests/test_gui_smoke.py` | linkes Register filtert Favoriten; Aussortierte nur unter Aussortiert; Pool-Favoriten bleiben rechts |
| `test_photos_rating_applies_to_timeline_gallery` | `tests/test_gui_smoke.py` | Medien-Bewertung erscheint in der Timeline |
| `test_media_tabs_change_only_on_click` | `tests/test_gui_smoke.py` | Mausrad wechselt keinen Reiter |
| `test_timeline_global_register_applies_to_all_days` | `tests/test_gui_smoke.py` | globales Register |
| `test_timeline_save_button_only_when_dirty` | `tests/test_gui_smoke.py` | Speichern aktiv bei Reisetitel, Text, YouTube, Pending-Abschnitt; sonst inaktiv |
| `test_timeline_leave_without_prompt_when_only_text_dirty` | `tests/test_gui_smoke.py` | `confirm_leave` ohne Dialog bei nur dirty Text |
| `test_scroll_offset_to_widget_top_uses_host_not_page_chrome` | `tests/test_gui_smoke.py` | Reveal ignoriert Reisetitel über der Liste |
| `test_timeline_join_is_wide_downward_connector` | `tests/test_gui_smoke.py` | schlanke Verbindungslinie mit Plus zwischen Timeline-Karten |
| `test_entry_span_dates_feeds_join_insert` | `tests/test_gui_smoke.py` | Lückendatum aus den Karten davor/danach |
| `test_settings_dialog_has_scrollbar` | `tests/test_gui_smoke.py` | Einstellungen-Dialog hat vertikalen Schieber |
| `test_span_index_at_mid_contains_then_nearest` | `tests/test_gui_smoke.py` | mittlerer Abschnitt für den Schieber |
| `test_timeline_scroll_date_follows_handle` | `tests/test_gui_smoke.py` | Datum klebt am Timeline-Schieber |
| `test_pool_scroll_date_follows_handle` | `tests/test_gui_smoke.py` | Datum klebt am Pool-Schieber |
| `test_reveal_group_puts_section_top_at_list_top` | `tests/test_gui_smoke.py` | Karten-Sprung setzt die Karten-Oberkante an die Viewport-Oberkante (nicht die Mitte); nachwachsen der vorherigen Karte bleibt bündig |
| `test_gallery_rating_hotspots` | `tests/test_gui_smoke.py` | Bewertungs-Chips |
| `test_pool_source_id_payload_roundtrip` | `tests/test_gui_smoke.py` | Pool-Drag MIME |
| `test_gallery_wraps_to_multiple_columns_when_wide` | `tests/test_gui_smoke.py` | Galerie mehrspaltig |
| `test_timeline_drop_pool_on_section_moves_members` | `tests/test_gui_smoke.py` | Drop aus dem Pool auf Abschnitt |
| `test_timeline_drop_on_same_section_is_noop` | `tests/test_gui_smoke.py` | Drop auf die eigene Karte ändert nichts |
| `test_timeline_drop_section_on_pool_parks_media` | `tests/test_gui_smoke.py` | Drop von der Karte in den Pool |
| `test_timeline_autoscroll_step_near_edges` | `tests/test_gui_smoke.py` | Auto-Scroll-Schritt am Rand |
| `test_timeline_drag_autoscroll_timer` | `tests/test_gui_smoke.py` | Timer startet und stoppt mit dem Drag |
| `test_timeline_map_anchor_uses_ordered_items_not_entry_attr` | `tests/test_gui_smoke.py` | GPS-Rückfrage ohne `entry`-Attribut |
| `test_photos_view_multi_select_and_pool_drag` | `tests/test_gui_smoke.py` | Medien: Bereichsauswahl, Ziehen in den Pool und zurück |
| `test_media_inspector_shows_original_and_ratings` | `tests/test_gui_smoke.py` | Inspektor mit Chips |
| `test_media_inspector_shows_ratings_for_tracks` | `tests/test_gui_smoke.py` | Track-Bewertung im Inspektor |
| `test_entry_widget_track_tab_filters_and_reactivates` | `tests/test_gui_smoke.py` | Track-Reiter wie Medien-Register |
| `test_thumb_zoom_slider_marks_default` | `tests/test_gui_smoke.py` | Thumbnail-Schieber 50–200 %, Marke 100 % |
| `test_media_inspector_parks_and_unparks_from_pool_button` | `tests/test_gui_smoke.py` | Inspektor: In den Pool / Zurückholen |
| `test_media_inspector_opens_current_item_on_map` | `tests/test_gui_smoke.py` | Inspektor: Zur Karte sendet Abschnitt und Medium |
| `test_media_inspector_rotates_display_without_writing_original` | `tests/test_gui_smoke.py` | Drehen, Original-mtime gleich |
| `test_media_inspector_browses_section_sequence` | `tests/test_gui_smoke.py` | Blättern in der Sequenz |
| `test_media_inspector_rating_advances_to_next_photo` | `tests/test_gui_smoke.py` | Bewertung im Inspektor springt zum nächsten Foto, letztes bleibt |
| `test_media_inspector_pool_advances_to_next_photo` | `tests/test_gui_smoke.py` | In den Pool im Inspektor springt zum nächsten Foto |
| `test_inspector_keeps_photo_aspect_on_resize` | `tests/test_gui_smoke.py` | Eckgriff proportional |
| `test_inspector_allows_free_window_resize` | `tests/test_gui_smoke.py` | Ränder frei |
| `test_media_inspector_zoom_arrows_and_fit` | `tests/test_gui_smoke.py` | Zoom und Einpassen |
| `test_youtube_links_dialog_add_and_delete` | `tests/test_gui_smoke.py` | YouTube-Dialog |
| `test_empty_section_dialog_shows_am_or_von_bis` | `tests/test_gui_smoke.py` | leerer Abschnitt: Tag Am, Aufenthalt von–bis |
| `test_section_span_dialog_tag_vs_range` | `tests/test_gui_smoke.py` | Datum… / Zeitraum… ohne überlagerte Felder, Dialog breit genug |
| `test_parse_map_bridge_url_reads_group_key` | `tests/test_gui_smoke.py` | Karten-Expand-Bridge, Zoom/Ausschnitt nach Platzieren |
| `test_map_view_refresh_uses_disk_cache_without_rebuild` | `tests/test_gui_smoke.py` | Karten-Cache; Leiste unter dem WebView |
| `test_publish_map_display_writes_unique_file` | `tests/test_gui_smoke.py` | WebEngine lädt eine neue HTML-Kopie nach Rebuild |
| `test_map_view_applies_prepared_result_when_shown` | `tests/test_gui_smoke.py` | Hintergrund-Karte wird beim Öffnen der Seite übernommen |
| `test_map_timeline_strip_centers_first_card` | `tests/test_gui_smoke.py` | Timeline-Leiste zentriert; Zähler Fotos/Tracks/IGC/YouTube, Reserve-Schalter, Plus zwischen Karten |
| `test_strip_click_closes_detail_and_zooms_cover` | `tests/test_gui_smoke.py` | andere Leistenkarte schließt Detail und zoomt; dieselbe bleibt |
| `test_inspector_map_opens_thumbnail_then_original_on_double_click` | `tests/test_gui_smoke.py` | Vorschau, dann Original |
| `test_thumb_zoom_persists` | `tests/test_workspace.py` | `timeline_thumb_zoom` und `map_thumb_zoom` in `config.json` |
| `test_normalize_timeline_media_tab` | `tests/test_workspace.py` | gültige Tab-Namen |
| `test_timeline_media_tab_persists` | `tests/test_workspace.py` | `config.json` hält das Register |
| `test_sidebar_collapsed_persists` | `tests/test_workspace.py` | `config.json` hält die eingeklappte Navigation |
| `test_timeline_pool_visible_persists` | `tests/test_workspace.py` | `config.json` hält die Pool-Spalte |
| `test_pool_width_persists` | `tests/test_workspace.py` | `config.json` hält die Pool-Breite |
| `test_inspector_geometry_persists` | `tests/test_workspace.py` | `config.json` hält die Inspektor-Größe |
| `test_inspector_remembers_window_size` | `tests/test_gui_smoke.py` | nächstes Öffnen mit derselben Fenstergröße |
| `test_pool_media_tab_persists` | `tests/test_workspace.py` | `config.json` hält das Pool-Bewertungsregister |
| `test_show_rejected_in_all_persists` | `tests/test_workspace.py` | `config.json` hält „Aussortierte anzeigen“ |
| `test_map_display_flags_persist_in_project` | `tests/test_workspace.py` | Zahnrad-Optionen in `settings.toml` |

### 4.16 Rückgängig und Wiederherstellen — FA-085

| Test | Datei | Prüft |
| --- | --- | --- |
| `test_restore_park_brings_back_auto_day` | `test_timeline_history.py` | Parken rückgängig stellt den Auto-Tag wieder her |
| `test_restore_move_members_returns_file` | `test_timeline_history.py` | Zuordnen rückgängig legt das Medium zurück |
| `test_restore_section_kind_and_span` | `test_timeline_history.py` | Typ und Spanne wiederherstellen |
| `test_restore_pin_and_title` | `test_timeline_history.py` | Kartenposition und Titel wiederherstellen |
| `test_restore_deleted_section` | `test_timeline_history.py` | gelöschten Abschnitt inkl. Mitglieder wiederherstellen |
| `test_restore_after_create_removes_new_section` | `test_timeline_history.py` | neu angelegten Abschnitt entfernen |
| `test_restore_dissolved_section` | `test_timeline_history.py` | aufgelösten Abschnitt wiederherstellen |
| `test_photo_sort_status_roundtrip` | `test_timeline_history.py` | Sortierstatus lesen und schreiben |
| `test_workspace_undo_rating_and_park` | `tests/test_edit_history.py` | Workspace: Bewertung und Pool undo/redo |
| `test_workspace_undo_create_and_delete_section` | `tests/test_edit_history.py` | Workspace: Abschnitt anlegen und löschen undo/redo |
| `test_workspace_undo_dissolve_journal_notes_cover_rotation` | `tests/test_edit_history.py` | Workspace: Auflösen, Journal-Zeit, Texte, Reisetitel, Titelbild, Drehung |
| `test_main_window_starts` | `tests/test_gui_smoke.py` | Menü **Bearbeiten**, Standard-Shortcuts Undo/Redo |

---

## 5. Abdeckung gegen das Pflichtenheft

### 5.1 Gut abgedeckt (Phase 7, R2.2.0)

- Dateiklassifikation und rekursiver Scan
- SHA-256 und Skip unveränderter Dateien
- EXIF-Zeitpriorität und Zeitzonenflag
- JPEG-GPS und Kamera
- HEIC-GPS/Kamera ohne ExifTool (ISO 6709, eingebettetes TIFF, Apple-Boxen)
- GPX-Parsing inkl. zeitloser und leerer Tracks, Interpolation, keine Überschreibung von EXIF-GPS
- Hilfsskript Polar-JSON `routes` → Sibling-GPX (`tests/test_json_routes_to_gpx.py`)
- IGC-Parsing, Pilot, DHV-Leonardo-Link überlebt Re-Import
- KML/GeoJSON-Parser für Track-Vorschauen (kein Ingest)
- JPEG-Thumbnails (große JPEGs per Decoder-Draft), HEIC-Vorschau (Windows-Shell/WIC oder eingebettetes JPEG), Originale unverändert
- Track-Thumbs (rote Spur, OSM-Ausschnitt oder schwarz offline)
- Importliste während des Einlesens und nach GPS-Abgleich, bevor Thumbnails erzeugt werden
- Quell-Sync: fehlende Dateien vollständig entfernen; neue Medien Timeline oder Pool
- Sortierstatus Favorit/Reserve/Aussortiert inkl. Fallback auf Favoriten-Flag
- Import bricht bei einer defekten Datei (JPEG oder GPX) nicht ab
- Projekt anlegen, Schema (Abschnitte, Mitglieder, Journal-Zeit, Pool `parked`, URLs, Cover, Drehung), Wiederöffnen, `settings.toml` und Pfad-Rebase
- Karte: Titelbild-Kreise je Tag/Transfer/Aufenthalt (Cover-Fallback Foto/Track/YouTube), Verbindungslinien (Transfer-Liste oder Ausgangslinie, Symbol in Fahrtrichtung), Transfer-Kreis per dünner Linie am Verkehrssymbol, Layer-Menü Straßenkarte/Topo/Satellit, Fit-Reise, Zahnrad (Fotokegel, Reserve, Ortsnamen und Straßen auf Satellit), Leiste darunter mit **+**, Tagebuchtext rechts, YouTube-Thumbs unten rechts auf der Karte, Cover-Zoom und Überlappungsgruppe, Detail mit Tracklinie und Fotomarkern (Stapel naher Fotos bis Zoom 16), Foto-Popup (Vorab-Zentrierung, Blättern, Schieber-Zoom, Bewertung), offline ohne OSM
- Verkehrsmittelsymbole: Katalog = `MOVEMENT_MODES`, Hilfe und Combos, Camper/Van nach rechts, Karten-Spiegelung in eigenem Wrapper
- Timeline: Tage als Abschnitte mit Mitgliedern, Medienpool, Journal-Zeit, Drag & Drop Karte↔Karte und Pool inkl. Auto-Scroll, manuelle Texte bleiben, Ortsvorschläge, `used_in_journal`; Speichern-Button nur bei Abschnitten, Texten, Reisetitel, YouTube; Rückgängig/Wiederherstellen (Snapshots in `travelcore`, Stack im Workspace)
- Reiseabschnitte, Pending-Vorschau, Eintrags-Titelbild (Foto und Track, YouTube-Fallback)
- YouTube- und DHV-Leonardo-URL-Normalisierung
- Anzeigedrehung (Index, Cachepfad, Re-Import, Inspektor ohne Originalschreiben)
- GUI-Rauch: Fenstertitel mit Version R2.2.0, Menü **Bearbeiten** (Strg+Z/Strg+Y), Pipeline Import→Medien→Timeline, Pool-Spalte, getrennte Medien/Tracks, Register nur per Klick (auch Tracks), Inspektor Blättern/Zoom/Drehen/Pool/Zur Karte (letzter Klick, geladene Karte ohne Neuaufbau), Thumbnail-Schieber
- Export- und Provider-*Verträge* existieren

### 5.2 Bewusst noch ohne Automatisierung

| Lücke | FA | Grund / nächste Phase |
| --- | --- | --- |
| Visuelle Marker-Vorschau / Bedienung in Qt | FA-050–FA-053 | Szene und Bridge in `test_maps.py` / `test_gui_smoke.py`; visuell MT-12 |
| Timeline-Bedienung | FA-060–FA-069, FA-080, FA-084, FA-085 | Logik in `test_timeline*.py` und `test_edit_history.py`; Speichern-Button, Schieber-Datum und Menü Bearbeiten `test_gui_smoke.py`; visuell MT-13, MT-18–MT-21, MT-24, MT-25 |
| Windows-Endnutzerpaket | FA-140–FA-144 | kein pytest; manuell MT-22 nach `packaging/build.ps1` |
| Galeriefilter in der UI | FA-101 | Logik der Liste automatisiert; Filter nur MT-09 |
| Zuletzt verwendete Projekte in der UI | FA-091 | `recent.json` ohne Oberfläche; manuell nicht zwingend |
| HTML-/PDF-/LaTeX-Ausgabe | FA-121–FA-123 | Phase 8 |
| Qualitätskennzahlen | FA-070 | Phase 9 |
| pHash/dHash, Dublettengruppen | FA-071 | Phase 10 |
| Importliste „alle Dateien“ (kein 250er-Limit) | FA-025 | nur manuell / GUI, kein Unit-Test der Qt-Tabelle |
| Originale unverändert | FA-023 | implizit (nur Lese-APIs); Thumbnail- und Inspektor-Tests prüfen mtime |
| IPTC | FA-030 | ausstehend |
| Video-Metadaten live mit ffprobe | FA-038 | Adapter + optionales Binary |
| pytest-qt Bedienung Import-Button | FA-092 | geplant |
| KML/GeoJSON auf der interaktiven Karte | FA-013, FA-043 | bewusst nicht; Parser + Thumbs automatisiert |

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

## 7. Manuelle Testfälle (Phase 3 bis 7, Software R2.2.0, inkl. Windows-Paket und Undo/Redo)

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

### MT-23 Quellverzeichnis synchronisieren

| Schritt | Erwartung |
| --- | --- |
| JPEG aus dem Quellordner löschen, **Synchronisieren** | Datei verschwindet aus Importliste, Timeline, Galerie und Pool; Vorschaubild im Projektcache weg; Originalordner unverändert (die Datei bleibt gelöscht) |
| Neues JPEG in den Quellordner legen, **Synchronisieren**, **In den Medienpool** | erscheint rechts im Pool, nicht als Tag-Mitglied |
| Neues JPEG, **Synchronisieren**, **In die Timeline** | erscheint im Auto-Tag des Aufnahmedatums |
| **Dateien analysieren** nach Löschen einer Datei im Ordner | Indexzeile bleibt (additiv, keine Löschung) |

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
| Kein Netzmonitor nötig; es dürfen keine Upload-Versuche sichtbar sein | erfüllt im Standardbetrieb (OSM-, optionale OpenTopoMap-, Esri- und Carto-Kacheln sind Abrufe, kein Upload) |

### MT-08 Projekteinstellungen

| Schritt | Erwartung |
| --- | --- |
| Projekt → Einstellungen: GPS-Zeitfenster, Standardzeitzone, Kartenanbieter, Verbindungslinien-Farbe | Werte in `settings.toml`; Originale unverändert; Standardfarbe der Linien weiß; Dialog hat einen vertikalen Schieber, Speichern/Abbrechen bleiben unten |
| Wurzelverzeichnis auf einen verschobenen Ordner setzen | Index-Pfade umgeschrieben, Dateien selbst nicht bewegt |
| Kartenanbieter `offline` | Karte ohne OSM-, Topo- und Satellitenkacheln, Track und Marker bleiben |

### MT-09 Galeriefilter und Favoriten

| Schritt | Erwartung |
| --- | --- |
| Seite **Medien**: Filter Jahr / Mit Ort / JPEG / Register Favoriten / Nicht im Tagebuch | sichtbare Menge ändert sich; Zähler „N von M Medien“ |
| Favorit umschalten, Projekt schließen und öffnen | Favorit bleibt |
| Bewertung (Favorit/Reserve/Aussortiert) auf **Medien**, dann Seite **Timeline** | dieselbe Bewertung am gleichen Medium; Register Favoriten zeigt es |
| Doppelklick | Medieninspektor mit Zeit, GPS, Kamera; Originale unverändert |

### MT-10 Foto ohne GPS, GPX im selben Ordner

| Schritt | Erwartung |
| --- | --- |
| JPEG ohne Koordinaten, Aufnahmezeit bekannt; GPX mit Punkten ±10 s um diese Zeit (UTC bzw. Offset am Foto) | GPS-Spalte zeigt Koordinaten und `(gpx_interpolated)` oder `(gpx_nearest)`; Zähler „mit Ort“ steigt; EXIF-Fotos unverändert |

### MT-11 Galerie

| Schritt | Erwartung |
| --- | --- |
| Nach Import Seite **Medien** öffnen | links Reise-Medien, rechts Medienpool (Pfeil rechts außen klappt ein/aus wie in der Timeline); jeweils Reiter Alle/Favoriten/Reserve/Aussortiert; kein Reiter Pool; Doppelklick öffnet den Medieninspektor |
| Pool-Schieber ziehen | links am Griff das Aufnahmedatum des Mediums in der Bildmitte (wie in der Timeline) |
| Medien: erstes und letztes Objekt anklicken | alles dazwischen ist markiert; Strg+Klick nimmt einzelne wieder raus |
| Medien: Auswahl auf den Pool ziehen oder **In den Pool** | Medien liegen rechts im Pool; **Zurück in die Galerie** oder Ziehen nach links holt sie zurück |
| Medium als Aussortiert markieren | verschwindet aus Alle (Checkbox aus), Favoriten und Reserve; nur noch unter Aussortiert |
| Register Alle: Checkbox **Aussortierte anzeigen** | nur bei Alle sichtbar; an: Aussortierte in Alle; Standard aus; bleibt in `config.json` |
| HEIC ohne eingebettetes JPEG (HEIF Image Extensions installiert) | echtes Vorschaubild, kein Absturz |
| HEIC ohne Codec/Erweiterung | Platzhalter, kein Absturz |

### MT-12 Karte

| Schritt | Erwartung |
| --- | --- |
| Nach Import mit GPX und Fotos (mit oder ohne EXIF-GPS) Seite **Karte** öffnen | ein runder Kreis je Tag, Transfer oder Aufenthalt; zwischen **Tag- und Aufenthaltskreisen** in Timeline-Reihenfolge eine Verbindungslinie mit Richtungsmarker; Transfer-Kreis mit dünner Linie am Verkehrssymbol; Layer-Symbol oben rechts mit Straßenkarte / Topo / Satellit; **Ganze Reise** zwischen Zoom und Zahnrad; Zahnrad unter den Zoom-Buttons; ohne gesetztes Titelbild das erste Foto, sonst das erste Track-Thumbnail, sonst das erste YouTube-Vorschaubild; darunter die Timeline-Leiste mit denselben Einträgen und **+** zwischen den Karten; **Übersicht aller Kreise** im Ausschnitt |
| **+** zwischen zwei Leistenkarten | Dialog **Neuer Reiseabschnitt** mit Datum der Lücke; nach OK erscheint der Abschnitt in der Timeline (**Speichern**) |
| Layer-Symbol: **Straßenkarte**, **Topo**, **Satellit** | wechselt OSM, OpenTopoMap und Esri World Imagery; Kreise und Linien bleiben; Quellenangabe je Anbieter; mit Ortsnamen-Option zusätzlich CARTO; `offline` ohne Symbol |
| Zahnrad: **Fotokegel anzeigen** | ab Zoom 17 ein Kegel an Fotos mit Blickrichtung und Brennweite (am Stapel und am Ursprung nach der Auswahl); im Fächer keine Kegel; bleibt nach Projekt-Neuöffnen |
| Zahnrad: **Reserve-Elemente anzeigen** aus | Reserve-Medien unsichtbar; Aussortierte nie auf der Karte; bleibt nach Projekt-Neuöffnen |
| Zahnrad: **Ortsnamen auf Satellit**, Layer **Satellit** | Ortsnamen über dem Luftbild (Carto/OSM, in Europa meist Latein); auf Straßenkarte/Topo ohne Extra-Overlay; bleibt nach Projekt-Neuöffnen; Standard aus |
| Zahnrad: **Straßen auf Satellit**, Layer **Satellit** | Straßennetz über dem Luftbild (Esri World Transportation); unabhängig von Ortsnamen; Standard aus |
| Nach Änderungen in der Timeline Seite **Karte** öffnen | Karte erscheint ohne extra **Karte aktualisieren**, Übersicht aller Kreise |
| **Karte aktualisieren** | Karte lädt neu und zeigt wieder die Übersicht aller Kreise |
| Leiste: Tag-Karte | Kalendersymbol oben rechts |
| Leiste: Transfer-Karte | liegendes Sechseck, gleiche Größe wie Rechteckkarten; Schrift etwas kleiner |
| Leiste: Fokus | nur die zentrierte Karte in voller Größe, die anderen etwas kleiner |
| Leiste: Abschnitt ohne Position | roter Rand |
| Rechtsklick auf eine gespeicherte Abschnittskarte ohne Ort, **Platzieren**, Klick in die Karte | Fadenkreuz-Cursor; der Ort liegt am Abschnitt; roter Rand verschwindet, Kreis erscheint; Zoom und Ausschnitt bleiben |
| Rechtsklick, **Verschieben**, Klick in die Karte | Fadenkreuz; der Kreis liegt an der neuen Position; Zoom, Ausschnitt und Fokus der Leistenkarte bleiben |
| Rechtsklick, **Zentrieren** | Karte schwenkt und zoomt auf den Kreis |
| Leiste: Titelbild | füllt die Kartenfläche ohne sichtbare Ränder |
| Leiste: Zähler oben | Fotos, GPX-Tracks, IGC (Gleitschirm), YouTube-Logo als Symbol+Zahl; Reserve nur bei Zahnrad-Option |
| Einfachklick auf eine Leistenkarte (Übersicht) | Karte zentriert, Zoom bleibt; der Mauszeiger folgt der Karte zur Mitte; rechts der Tagebucheintrag, nach Edit Speichern/Abbrechen/Verwerfen; YouTube-Thumbs unten rechts auf der Karte übereinander (erster Link unten) |
| Doppelklick auf eine Leistenkarte | Seite **Timeline**, Oberkante der Zielkarte bündig mit der Unterkante von Reisetitel/Werkzeugleiste (nicht die Kartenmitte zentriert); der vorherige Abschnitt schaut nicht heraus |
| Leiste nach links/rechts ziehen oder Mausrad | Karten verschieben sich horizontal; Klick trifft die Karte, nicht die OSM-Kacheln |
| Hineinzoomen, dann eine Leistenkarte anklicken | die Karte schwenkt auf diesen Eintrag, **Zoom bleibt** |
| Zwei nahe Tag-/Aufenthaltskreise, weit herausgezoomt | Verbindungslinie unsichtbar, sobald sich die Kreise überdecken |
| Zwei entfernte Tag- oder Aufenthaltskreise, Ausgangslinie Bogen gestrichelt mit Auto | Bogenlinie gestrichelt mit Autosymbol (Nase zum Folgekreis), kein Transfer-Stiel |
| Dieselbe Strecke mit Camper oder Camper Van | Fahrzeug zeigt in dieselbe Fahrtrichtung wie Auto (nicht entgegengesetzt) |
| Zwei entfernte Tag- oder Aufenthaltskreise, Ausgangslinie **Keine Linie** | keine Verbindung zwischen den Kreisen |
| Zwei entfernte Tag- oder Aufenthaltskreise mit Transfer dazwischen | Linie des Transfers (nicht die Ausgangslinie des linken Tags); dünne Linie vom Transfer-Kreis zum Symbol; in der Detailansicht keine Linie |
| Doppelklick in die freie (nicht belegte) Kartenfläche | Übersicht: alle Kreise im Ausschnitt |
| **Ganze Reise** | alle Cover-Kreise im Ausschnitt, ohne Zoomanimation |
| Mehrere Cover-Kreise überlappen sich (weit herausgezoomt), erster Klick auf die Gruppe | die Gruppe wird eingepasst; noch kein Detail |
| Zweiter Klick auf einen einzelnen Kreis der Gruppe | Zoom auf diesen Kreis (mindestens 14), ohne Zoomanimation |
| Noch ein Klick auf denselben Kreis | Detailansicht: Fotos, Videos und Tracks dieses Eintrags, Ausschnitt angepasst; **Reiseabschnitt schließen** rechts neben dem Zoom-Plus stellt Zoom und Ausschnitt der Übersicht wieder her |
| Klick auf das Verkehrssymbol eines Transfers | dieselbe Detailansicht wie der zweite Klick auf den Transfer-Kreis |
| Freie Karte: offene Hand (Verschieben); über einem Kreis: Zeiger (Auswahl) | der Kreis-Klick zoomt bzw. öffnet das Detail, startet kein Mausrad-Zoomen |
| In der Detailansicht eine **andere** Leistenkarte anklicken | Detail schließt; Zoom auf den Cover-Kreis dieses Abschnitts; der Mauszeiger steht über der Kartenmitte |
| In der Detailansicht die **aktuelle** Leistenkarte anklicken | Detail bleibt (wie nach **Zur Karte**) |
| Klick auf ein einzelnes viereckiges Foto-Symbol im Detail | Thumbnail-Popup nur an der zentrierten Stelle (großes Bild + kleines Kartenbild + Datum); nicht zuerst am alten Marker |
| Thumbnail-Schieber der Kartenseite | nur die große Popup-Vorschau wächst/schrumpft (50–200 %); Cover-Kreise und kleine Marker bleiben |
| Pfeile am Popup oder Pfeiltasten | nächstes/vorheriges Foto, Wrap-around; Thumbnail-Modus bleibt; Klick in die freie Karte beendet ihn |
| Popup-Bewertung (★ / R / ×) | speichert sofort wie in der Timeline; gilt auch am Track-Linien-Popup |
| Mehrere Fotos fast am selben Ort, Zoom unter 17 | ein Stapel-Marker mit der Anzahl; Blättern im Popup bleibt möglich |
| Hineinzoomen auf Zoom 17 oder höher | Stapel löst sich auf; Bilder liegen übereinander, Fotokegel bleiben sichtbar |
| Klick auf den Bilderstapel | runder Fächer ohne Fotokegel; der Fächer bleibt stehen |
| Klick auf ein Bild im Fächer | die anderen verschwinden, Bild und Kegel stehen an der Originalposition |
| Weiterer Klick auf dieses Bild | Thumbnail-Popup an der zentrierten Gruppe |
| Klick in die freie Karte | Stapel wieder wie zu Beginn |
| Doppelklick auf das Thumbnail (oder das Foto-Symbol) | Medieninspektor mit dem **Original**, Blättern/Zoom/Drehen wie in der Timeline |
| Bestätigter Ort | erscheint im Detail des Tags |

### MT-13 Timeline

| Schritt | Erwartung |
| --- | --- |
| Nach Import Seite **Timeline** öffnen bzw. **Timeline aktualisieren** | ein Tag je Aufnahmedatum, Karten von früh nach spät; Kartenkopf: Titelbild, rechts Titel, darunter Typ/Datum (`14.05.2025` bzw. `01.08.2025 - 10.08.2025`), danach Verbindungslinien; darunter Tagebucheintrag; zwischen den Karten Abstand und schlanke Linie mit **+** in einem Ring; Fotos auf der Karte nach Journal-Zeit; Auto-Ereignis mit Medienzähler |
| **+** auf der Linie zwischen zwei Karten | Dialog **Neuer Reiseabschnitt**; Tag **Am** = erster offener Tag der Lücke; Aufenthalt/Transfer **Von**/**Bis** = offene Tage; ohne Lücke das Datum der vorherigen Karte |
| Vertikalen Schieber ziehen | links am Griff das Datum des Abschnitts in der Bildmitte (`14.05.2025` bzw. `01.–10.08.2025`) |
| Pool-Schieber ziehen | links am Griff das Aufnahmedatum des Mediums in der Bildmitte |
| Timeline ohne ungespeicherte Abschnitte, Texte, Reisetitel oder YouTube | **Speichern** ist inaktiv |
| Reisetitel, Titel, Tagebuchtext oder YouTube ändern bzw. neuen Abschnitt anlegen | **Speichern** wird aktiv; Rücknahme der Änderung macht ihn wieder inaktiv |
| Bewertung (Foto oder Track), Titelbild oder DHV-Leonardo an einem **gespeicherten** Eintrag | sofort in der DB; **Speichern** bleibt inaktiv |
| Timeline: Track-Reiter Favoriten | nur bewertete Tracks; dasselbe Register wie bei Medien |
| Reisetitel oben ändern, **Speichern**, Projekt schließen und öffnen | Titel noch da; erneuter Timeline-Abgleich überschreibt ihn nicht |
| GPS-Fotos am selben Ort | kein automatischer Ortsname; Tag zeigt das Datum |
| Ort löschen, erneut abgleichen | kein neuer Auto-Ortsname |
| Timeline: Titel und Text speichern, Projekt schließen und öffnen | Text noch da, `origin=manual`; erneuter Timeline-Abgleich überschreibt den Text nicht |
| Timeline: Typ **Aufenthalt** bzw. **Transfer** an einem gespeicherten Tag | die Karte bleibt derselbe Abschnitt, nur der Typ wechselt (sofort, ohne **Speichern**); zurück auf **Tag** ist ebenfalls ein Typwechsel, kein Auflösen |
| Timeline: mehrere Fotos markieren, **Neuen Reiseabschnitt erstellen** (Aufenthalt) | Abschnitt erscheint; die bisherigen Tage bleiben; **Speichern** aktiv; ohne Speichern und Verlassen: Dialog Speichern/Verwerfen/Abbrechen |
| ⋯ **Journal-Zeit…** an einem Medium, Uhr über Mitternacht | Clip liegt auf dem anderen Tag; `captured_at` unverändert |
| **Originalzeit** | Journal-Zeit wieder wie die Aufnahme; Clip auf dem ursprünglichen Tag |
| Timeline ohne Auswahl, **Neuen Reiseabschnitt erstellen**, Tag **Am** bzw. Aufenthalt/Transfer **Von Datum** / **Bis Datum** | leerer Abschnitt erscheint an der passenden Timeline-Stelle; **Speichern** aktiv |
| ⋯ **Datum…** (Tag) bzw. **Zeitraum…** (Aufenthalt/Transfer) | Dialog übernimmt die bisherigen Daten; nach OK rutscht die Karte an die neue Stelle; bei ungespeichertem Abschnitt **Speichern** nötig |
| ⋯ **Löschen** an einem gespeicherten Abschnitt | Abschnitt weg; Medien im Pool; Pool-Spalte öffnet sich |
| Transfer-Verbindungslinie: **durchgezogen** / **gestrichelt** | nach Speichern auf der Karte dieselbe Strichart |
| Transfer mit mehreren Verkehrsmitteln, **Speichern**, ⊟ auflösen | Dateien wieder auf Tagen |
| Tag oder Aufenthalt, nächster Eintrag kein Transfer: **Verbindung zum nächsten Abschnitt** | Gerade/Bogenlinie, durchgezogen/gestrichelt, ein Verkehrsmittel (Symbol vor dem Namen, Nase nach rechts in der Liste); leer = Richtungspfeil auf der Geraden; **Keine Linie** zeichnet nichts zum Folgekreis; Track und Route fehlen; Symbolspitze zur nächsten Tag-/Aufenthaltsposition |
| Letzter Eintrag oder nächster Eintrag ist Transfer | keine Ausgangslinie-Zeile; gespeicherte Werte bleiben |
| YouTube im ⋯-Menü, Dialog-OK | **Speichern** wird aktiv; ohne Speichern die Timeline verlassen: Dialog Verwerfen/Abbrechen; nach Verwerfen YouTube nicht in der DB |
| Nur Titel oder Tagebuchtext ändern und die Timeline verlassen | keine Rückfrage; die Edits bleiben in der Timeline, bis **Speichern**; Schließen des Fensters verwirft sie |
| **Timeline aktualisieren** bei geändertem Titel/Text | Texte werden mitgeschrieben; **Speichern** bleibt aktiv, wenn Abschnitte oder YouTube noch ungespeichert sind |
| DHV-Leonardo extra an gespeichertem Tag, Dialog-OK | sofort in der DB; nie als „DAV“ bezeichnet |
| Chip **T** auf Foto und auf Track | Cover in der Kartenüberschrift; Video hat kein T |
| Ohne Chip T | Fallback: erstes Foto, sonst erstes Track-Thumbnail, sonst erstes YouTube-Vorschaubild |
| **Zur Karte** an einem gespeicherten Reiseabschnitt oder Tag | Seite **Karte**, passende Leistenkarte fokussiert |
| Rechtsklick auf ein Thumbnail, **Zur Karte…** | Seite **Karte**, Detailansicht, Foto an der Position, Leistenkarte des Bildes mittig (nur mit Kartenposition, gespeicherter Eintrag) |
| Original-Ansicht: **Zur Karte** | wie der Thumbnail-Menüpunkt; ohne Ort oder im Pool deaktiviert; mehrere Fenster möglich, letzter Klick gewinnt (Detail, Foto, Leistenkarte mittig). Ist die Karte schon geladen, kein Neuaufbau — Detail und Foto sofort |
| **In den Pool** auf markierten Medien | Medien verschwinden aus Tag/Transfer/Aufenthalt; die rechte **Pool**-Spalte öffnet sich und zeigt sie |
| Pool-Spalte: Auswahl, **Zurück in die Timeline** | Medien liegen wieder auf einem Tag nach Journal-/Aufnahmezeit |
| Pfeil rechts außen in der Timeline oder auf **Medien** | klappt die Pool-Spalte ein und aus, wie die Navigation; keine Abschnittskarte |
| Pool breiter ziehen, einklappen, ausklappen | dieselbe Breite wie vor dem Einklappen |
| Pool-Spalte breiter ziehen | Vorschaubilder mehrspaltig |
| Pool-Medium auf einen gespeicherten Tag/Transfer/Aufenthalt ziehen | Rückfrage **GPS behalten** / **Abschnittsposition**, wenn das Medium GPS hat und der Abschnitt eine Kartenposition; Originale unverändert; mehrere Medien ohne GPS-Behalten leicht versetzt auf der Karte; Journal-Zeit übernimmt das Datum des Zielabschnitts |
| Medium einer Karte auf eine andere gespeicherte Karte ziehen | ohne Umweg über den Pool; Journal-Datum des Ziels; dieselbe GPS-Rückfrage; Originale unverändert |
| Thumbnail an den oberen oder unteren Fensterrand ziehen | die Timeline scrollt in diese Richtung, bis das Ziel sichtbar ist; Loslassen legt das Medium dort ab |
| Medium einer Karte auf den Pool ziehen | Medium liegt im Pool; Pool-Spalte öffnet sich |
| Strg+Z / Strg+Y nach Zuordnen, Bewerten, Abschnitt anlegen oder löschen | siehe MT-24 |
| Pool-Spalte: Reiter Favoriten | nur geparkte Favoriten; unbewertete Pool-Medien verschwinden aus der Ansicht, nicht aus dem Pool |
| Medien: Favorit im Pool, Reiter Favoriten links | erscheint nicht links, sondern rechts im Pool unter Favoriten |

### MT-18 Medieninspektor

| Schritt | Erwartung |
| --- | --- |
| Timeline: Doppelklick auf ein Foto in einem Tag mit mehreren Bildern | eigenes Fenster; Titel `datei.jpg · 2 von N` |
| Pfeiltasten oder Klick in den linken/rechten Rand | nächstes/vorheriges Bild derselben Sequenz; weiße Pfeile beim Überfahren der Ränder |
| Bewertung (Favorit / Reserve / Aussortiert) an Foto oder Track | speichert sofort und zeigt den nächsten Eintrag; der letzte bleibt |
| **In den Pool** | Medium im Pool, nächstes Foto; letztes bleibt; Button wird **Zurückholen** |
| Mausrad über dem Foto | Zoom um den Cursor; Ziehen verschiebt bei Zoom |
| Doppelklick in die Bildmitte | Einpassen |
| Ecke unten rechts ziehen | Fenster wächst proportional zum Foto |
| Fensterrand ziehen | frei breiter oder höher; nächstes Öffnen hat dieselbe Größe |
| Inspektor schließen und denselben oder ein anderes Foto öffnen | Fenster so groß wie zuletzt |
| Maximieren oder F11 | Foto eingepasst, schwarze Ränder, Zoom zurückgesetzt |
| Seite **Medien**: Doppelklick | dieselbe Sequenz wie die aktuelle Galerie |
| **In den Pool** im Inspektor (Timeline, Medien oder Karte) | Medium liegt im Pool; nächstes Foto (letztes bleibt); Button wird **Zurückholen**; Originale unverändert |
| **Zurückholen** im Inspektor | Medium wieder in Timeline und Galerie |
| **Zur Karte** bei einem Medium mit Ort | Seite **Karte**, Detailansicht, Foto-Popup, zugehörige Leistenkarte mittig; ohne Ort oder im Pool deaktiviert |
| Zweites Original-Fenster, **Zur Karte** im zweiten | versetzt; letzter Klick gewinnt Detail, Foto und Leistenkarte |
| **Zur Karte**, Karte war in der Sitzung schon offen | sofort Detail und Foto, kein langes Neuzeichnen |

### MT-19 Anzeigedrehung

| Schritt | Erwartung |
| --- | --- |
| Inspektor: ↺ oder ↻ (Tasten L/R oder `[`/`]`) | Bild dreht sich 90°; Original-mtime/Größe unverändert |
| Projekt schließen, öffnen, Galerie und Inspektor | Drehung bleibt; Vorschau folgt `rotation_degrees` |
| Erneut importieren | Nutzerdrehung bleibt |

### MT-20 Medienregister nur per Klick

| Schritt | Erwartung |
| --- | --- |
| Timeline: Mausrad über einer Karte mit Register Alle/Favoriten/… | Tag scrollt, Reiter bleibt |
| Klick auf **Favoriten** oben neben „Neuen Reiseabschnitt erstellen“ oder auf der Medienseite | alle Karten bzw. die Galerie filtern; nach Verlassen der Seite und Zurückkehren bleibt Favoriten |

### MT-21 Fenstertitel

| Schritt | Erwartung |
| --- | --- |
| App ohne Projekt | Titelleiste `Reisetagebuch R2.2.0` |
| Projekt öffnen | `Reisetagebuch R2.2.0 - {Projekttitel}` |

### MT-22 Windows-Paket (FA-140–FA-144)

Voraussetzung: `packaging/build.ps1` erfolgreich; optional Inno Setup 6 für die Setup-EXE.

| Schritt | Erwartung |
| --- | --- |
| `dist/Reisetagebuch/Reisetagebuch.exe` starten (ohne venv, ohne `python` auf dem PATH) | Fenster `Reisetagebuch R2.2.0`; kein Python-Fehlerdialog |
| Neues Projekt anlegen, JPEG-Ordner importieren | Index und Thumbnails wie in der Entwicklungsumgebung; Originale unverändert |
| Seite **Karte** | WebEngine zeigt die Karte (nicht nur den HTML-Pfad) |
| `%LOCALAPPDATA%\TravelJournal` | `config.json` / `recent.json` wie bisher, nicht im Programmordner |
| `_internal/NOTICE.txt` und `_internal/LICENSE` | vorhanden |
| Optional: Setup-EXE, Installation ohne Admin | Programm unter `%LOCALAPPDATA%\Programs\Reisetagebuch`, Startmenüeintrag |
| SmartScreen beim ersten Start | dokumentiertes Verhalten ohne Signatur (FA-142); „Trotzdem ausführen“ erlaubt den Start |

### MT-24 Rückgängig und Wiederherstellen (FA-085)

Voraussetzung: Projekt mit Timeline (mindestens ein Tag mit Foto, ein gespeicherter Aufenthalt).

| Schritt | Erwartung |
| --- | --- |
| Menüleiste | **Bearbeiten** mit **Rückgängig** (Strg+Z) und **Wiederherstellen** (Strg+Y); ohne vorherige Aktion sind beide inaktiv |
| Foto bewerten, dann Strg+Z | Bewertung weg; Strg+Y setzt sie wieder |
| Foto in den Pool, Strg+Z | Foto wieder auf dem Tag; Pool leer für dieses Medium |
| Neuen Abschnitt anlegen (auch ohne Speichern), Strg+Z | Abschnitt verschwindet; Strg+Y bringt ihn zurück (weiterhin ungespeichert, **Speichern** aktiv) |
| Gespeicherten Abschnitt löschen, Strg+Z | Abschnitt und Mitglieder wieder da |
| Aufenthalt auflösen, Strg+Z | Aufenthalt wieder da, Medien nicht mehr auf den Auto-Tagen |
| Typ oder Datum ändern, Strg+Z | vorheriger Typ bzw. vorherige Spanne; Karte an der alten Stelle |
| Kartenposition setzen oder verschieben, Strg+Z | Pin wieder am vorherigen Ort bzw. ohne Pin |
| Journal-Zeit über Mitternacht, dann Originalzeit, jeweils Strg+Z | Clip wechselt den Tag zurück; Originalzeit-Schritt ebenfalls invertierbar |
| Titel oder Tagebuchtext **Speichern**, Strg+Z | gespeicherter Text wieder der vorherige; im fokussierten Feld vor dem Speichern gilt zuerst die Zeichen-Historie des Widgets |
| Reisetitel **Speichern**, Strg+Z | vorheriger Reisetitel |
| Eintrags-Titelbild setzen, 90° drehen, jeweils Strg+Z | Cover weg bzw. Drehung zurück; Original unverändert |
| Import, Synchronisieren, Timeline aktualisieren oder Projekt schließen | Stack leer; Strg+Z ändert nichts mehr an den vorherigen Journal-Edits |
| YouTube oder DHV-Leonardo ändern | Strg+Z nimmt das nicht zurück (nicht auf dem Stack) |

### MT-25 Verkehrsmittelsymbole (Hilfe und Katalog)

| Schritt | Erwartung |
| --- | --- |
| Menü **Hilfe → Verkehrsmittelsymbole…** (oder F1) | Dialog listet alle Modi; weißes Piktogramm auf schwarzem Kreis; Nase nach rechts |
| Camper Van und Camper in der Hilfe | zeigen nach rechts wie Auto, Bus und Bahn (nicht nach links) |
| Transfer-Zeile und Ausgangslinie: Combobox Verkehrsmittel | dasselbe Badge vor dem Namen; „Pfeil“ zeigt das Richtungssymbol |
| Karte: Linie nach Osten mit Auto, dann Camper | beide Nasen zur Folgeposition; nach Westen Räder/Kiel unten, Nase weiter in Fahrtrichtung |

---

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
| Timeline / Abschnitte | `test_timeline.py`, `test_timeline_sections.py`, `tests/test_gui_smoke.py` (Speichern-Button), manuell MT-13 |
| Undo / Redo | `test_timeline_history.py`, `tests/test_edit_history.py`, Menü in `tests/test_gui_smoke.py`, manuell MT-24 |
| Hilfsskript JSON → GPX | `tests/test_json_routes_to_gpx.py`; Aufruf im README |
| Karte / Leiste / Kreis-Detail | `test_maps.py`, `tests/test_gui_smoke.py` (Map-Fälle), manuell MT-12 |
| Verbindungslinien / Symbole | `test_transfer_links.py`, `test_symbols.py`, `test_maps.py` (outbound), `tests/test_gui_smoke.py` (Transfer-Zeile), manuell MT-12, MT-13, MT-25 |
| Inspektor / Drehung / Register / Zur Karte | `test_orientation.py`, `tests/test_gui_smoke.py`, manuell MT-18–MT-21 |
| Windows-Paket (`packaging/`) | manuell MT-22 (kein pytest) |
| UI-Importliste | MT-04, MT-23 |
| Vor Phasenabschluss | pytest grün + manuelle Fälle der Phase + Ruff |

Ein Phasenabschluss ohne grüne Automatisierung gilt als nicht abgenommen.

---

## 10. Nachweis der letzten Automatisierungsfahrt

| Datum | Kommando | Ergebnis |
| --- | --- | --- |
| 30.08.2026 | `python -m pytest` im Projekt-venv | 415 bestanden (R2.2.0; Zur Karte letzter Klick, Detail+Foto, geladene Karte ohne Neuaufbau) |
| 30.08.2026 | `python -m pytest` im Projekt-venv | 400 bestanden (R2.1.1; Cover-Zoom, Foto-Popup, Track-Bewertung, Thumbnail-Schieber) |
| 29.08.2026 | `python -m pytest` im Projekt-venv | 393 bestanden (R2.1.0; Verbindungslinien, Ausgangslinie, Verkehrssymbole) |
| 29.08.2026 | `python -m pytest` (`test_timeline_history`, `test_edit_history`, `test_main_window_starts`) im Projekt-venv | 12 bestanden; damals 375 Tests (R2.0.0, inkl. Undo/Redo) |
| 28.08.2026 | `python -m pytest` im Projekt-venv | 364 bestanden (R2.0.0) |
| 27.08.2026 | `python -m pytest` im Projekt-venv | 264 bestanden |
| 26.08.2026 | `python -m pytest` im Projekt-venv | 222 bestanden |
| 18.08.2026 | `python -m pytest` im Projekt-venv | 98 bestanden |

Diese Zeile bei der nächsten vollständigen Fahrt fortschreiben.
