# Testdokumentation — Reisetagebuch

| Feld | Inhalt |
| --- | --- |
| Version | 1.0 |
| Stand | 27. August 2026 |
| Bezugsversion Software | Phase 7 erweitert, Software **R1.0.0** |
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
| Unit | `packages/travelcore/tests/` | pytest | Typen, Hash, Zeit, GPS, Provider, HEIC-Container, GPX/IGC/KML, Interpolation, ExifTool-JSON, Thumbnails, Orientierung, Timeline, Abschnitte |
| Integration | `packages/travelcore/tests/test_indexer.py`, `test_database.py`, `test_timeline.py`; `tests/integration/` | pytest | Projektordner, Schema, Index → SQLite, Timeline-Sync, Re-Open |
| GUI-Rauch | `tests/test_gui_smoke.py` | pytest + Qt offscreen | Hauptfenster, sechs Seiten, Inspektor, Register, Titel mit Version |
| Paketierung | `packaging/` | manuell nach `build.ps1` | Frozen-EXE startet, Alembic/Karte, kein Python nötig (MT-22) |
| Manuell | dieses Dokument, Abschnitt 7 | Windows-Desktop | Import echter HEIC/JPEG, Liste, Timeline, Abschnitte, Karte, Inspektor |
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

Stand nach `pytest --collect-only`: **252 Tests** (27. August 2026). Neue Tests sind ergänzend zu führen, nicht still zu löschen.

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
| `test_main_window_starts` | `tests/test_gui_smoke.py` | Titel mit Version R1.0.0, Pipeline mit Symbolen, eingeklappt nur Icons, ausgeklappt inhaltsbreit, Medienregister |

### 4.7 GPX und zeitliche Zuordnung — FA-040 bis FA-042

| Test | Datei | Prüft |
| --- | --- | --- |
| `test_parse_gpx_track_and_segment` | `test_gpx_parse.py` | Punkte, Höhe, UTC-Zeit, Segment-ID |
| `test_convert_file_writes_sibling_gpx` | `tests/test_json_routes_to_gpx.py` | Polar-JSON Routes → GPX neben der Datei |
| `test_directory_mode_prints_dots_and_counts` | `tests/test_json_routes_to_gpx.py` | `-d` / `-r`, Punkte und Zähler |
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
| `test_folium_overview_cover_uses_expand_url` | `test_maps.py` | rundes Cover, Expand-Bridge, Zoom-Halt, Popup-Skript, Aufenthaltslinien, Layer-Menü Straßenkarte/Topo/Satellit, Zahnrad |
| `test_overview_offline_omits_satellite` | `test_maps.py` | ohne Kacheln kein Layer-Umschalter, Zahnrad bleibt |
| `test_timeline_js_cards_uses_relative_cover` | `test_maps.py` | Timeline-Karten relative Cover-Pfade |
| `test_leaflet_payload_includes_source_file_id` | `test_maps.py` | Detail-Payload: `source_file_id`, Thumbnail-Popup, Blickrichtung |
| `test_detail_stacks_nearby_photos_until_zoom_17` | `test_maps.py` | Stapel bis Zoom 16, Anzahl, ab 17 einzeln mit Rotation; Orte ungestapelt |
| `test_pick_cover_item_skips_rejected` | `test_maps.py` | Aussortierte Cover fallen raus |
| `test_count_card_media_splits_reserve_and_skips_rejected` | `test_maps.py` | Reserve getrennt, Aussortierte nie; IGC separat von GPX |
| `test_photo_fov_degrees_from_35mm` | `test_maps.py` | Kegelwinkel aus 35-mm-Brennweite |
| `test_map_detail_omits_rejected_photo` | `test_maps.py` | Aussortierte Fotos nicht im Detail; Heading/FOV am Marker |
| `test_folium_backend_writes_html` | `test_maps.py` | Leaflet-HTML, `MapBackend` |
| `test_offline_backend_omits_osm_tiles` | `test_maps.py` | `tiles=None` ohne OSM-URL |
| `test_map_scene_includes_igc_flight` | `test_maps.py` | IGC-Polylinie, Pilot, DHV-Link, Zoom-Skript |
| `test_map_cache_reuses_html_when_inputs_unchanged` | `test_maps.py` | Disk-Cache ohne Rebuild |
| `test_map_cache_rebuilds_when_provider_or_force_changes` | `test_maps.py` | Cache-Invalidierung |
| `test_map_cache_rebuilds_when_link_color_changes` | `test_maps.py` | Cache neu bei geänderter Linienfarbe |
| `test_pick_cover_item_uses_first_gps_photo` | `test_maps.py` | ohne Titelbild erstes Foto mit GPS |
| `test_pick_cover_item_uses_first_gps_track_without_photo_fix` | `test_maps.py` | ohne GPS-Foto erster GPS-Track |
| `test_parse_group_key_accepts_section_day_and_loose` | `test_maps.py` | `section:` / `day:` / `loose:` |
| `test_build_map_timeline_cards_from_section` | `test_maps.py` | Leistenkarten aus Abschnitt inkl. Text und YouTube |
| `test_stay_links_connect_days_and_stays_in_timeline_order` | `test_maps.py` | Linien zwischen Tag- und Aufenthaltskreisen in Timeline-Reihenfolge |
| `test_stay_links_connect_leftover_days` | `test_maps.py` | Resttage mit GPS werden verbunden |
| `test_stay_links_skip_transfer_as_endpoint` | `test_maps.py` | Transfer-Kreis ist kein Linienende |
| `test_stay_links_mark_transfer_between_stays` | `test_maps.py` | Transfer zwischen Endpunkten setzt `via_transfer` |
| `test_stay_links_skip_stays_without_gps` | `test_maps.py` | Aufenthalt ohne GPS ist kein Linienende |
| `test_stay_link_hidden_when_covers_overlap` | `test_maps.py` | Linie unsichtbar, wenn Kreise sich überdecken |
| `test_build_map_overview_links_consecutive_stays` | `test_maps.py` | Übersicht verbindet zwei Aufenthalte über einen Transfer |
| `test_build_map_overview_links_leftover_days` | `test_maps.py` | Übersicht verbindet Resttage mit GPS |
| `test_parse_map_bridge_url_reads_group_key` | `tests/test_gui_smoke.py` | Expand-URL und Konsolen-Bridge |
| `test_map_view_refresh_uses_disk_cache_without_rebuild` | `tests/test_gui_smoke.py` | MapView zeigt Cache; Leiste unter dem WebView |
| `test_publish_map_display_writes_unique_file` | `tests/test_gui_smoke.py` | WebEngine lädt eine neue HTML-Kopie nach Rebuild |
| `test_map_view_applies_prepared_result_when_shown` | `tests/test_gui_smoke.py` | Hintergrund-Karte wird beim Öffnen der Seite übernommen |
| `test_map_timeline_strip_centers_first_card` | `tests/test_gui_smoke.py` | Leiste zentriert; Transfer-Sechseck; Zähler Fotos/Tracks/IGC/YouTube |
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

### 4.11 Reiseabschnitte und Titelbild — FA-065 bis FA-067, FA-083

| Test | Datei | Prüft |
| --- | --- | --- |
| `test_expand_range_selection_fills_between_first_and_last` | `test_timeline_sections.py` | Bereich zwischen erstem und letztem Klick |
| `test_parse_and_serialize_transfer_modes` | `test_timeline_sections.py` | Verkehrsmittel-Liste |
| `test_format_section_span_uses_object_dates` | `test_timeline_sections.py` | `am …` / `von … bis …` |
| `test_create_section_same_day_is_am` | `test_timeline_sections.py` | Aufenthalt am selben Kalendertag |
| `test_dissolve_section_returns_files_to_leftover_days` | `test_timeline_sections.py` | Auflösen → Resttage |
| `test_leftover_day_sits_between_sections` | `test_timeline_sections.py` | Resttag zwischen Abschnitten |
| `test_create_movement_section_from_last_day_files` | `test_timeline_sections.py` | Transfer aus Dateien |
| `test_transfer_mode_is_optional_and_can_be_multiple` | `test_timeline_sections.py` | mehrere Verkehrsmittel |
| `test_update_section_kind_switches_stay_and_transfer` | `test_timeline_sections.py` | Typ Aufenthalt ↔ Transfer |
| `test_apply_pending_sections_is_preview_only` | `test_timeline_sections.py` | Overlay schreibt nicht |
| `test_set_entry_cover_on_day_and_section` | `test_timeline_sections.py` | Foto als Eintrags-Titelbild |
| `test_set_entry_cover_accepts_gps_track` | `test_timeline_sections.py` | Track als Eintrags-Titelbild |

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

### 4.15 GUI-Rauch — FA-082, FA-090, FA-102, FA-103, FA-105

| Test | Datei | Prüft |
| --- | --- | --- |
| `test_app_window_title_includes_version` | `tests/test_gui_smoke.py` | `Reisetagebuch R1.0.0` |
| `test_entry_widget_separates_tracks_from_media` | `tests/test_gui_smoke.py` | getrennte Galerien |
| `test_entry_widget_track_can_be_cover` | `tests/test_gui_smoke.py` | T-Chip auf Track |
| `test_entry_widget_shows_cover_in_heading` | `tests/test_gui_smoke.py` | 72-px-Cover in der Karte |
| `test_entry_widget_section_has_to_map_button` | `tests/test_gui_smoke.py` | Zur Karte an Abschnitt und Tag |
| `test_map_view_focus_group_centers_section_card` | `tests/test_gui_smoke.py` | MapView fokussiert die Abschnittskarte; Tagebuchtext und YouTube-Thumbs rechts |
| `test_map_notes_edit_shows_save_cancel_discard` | `tests/test_gui_smoke.py` | Nach Edit Speichern, Abbrechen, Verwerfen |
| `test_map_notes_switch_card_opens_save_dialog` | `tests/test_gui_smoke.py` | Fokuswechsel bei ungespeichertem Tagebuchtext: Dialog Speichern/Abbrechen/Verwerfen |
| `test_entry_widget_media_tab_filters_favorites` | `tests/test_gui_smoke.py` | Register filtert Favoriten |
| `test_photos_view_media_tab_filters_favorites` | `tests/test_gui_smoke.py` | Medien-Register filtert Favoriten |
| `test_photos_rating_applies_to_timeline_gallery` | `tests/test_gui_smoke.py` | Medien-Bewertung erscheint in der Timeline |
| `test_media_tabs_change_only_on_click` | `tests/test_gui_smoke.py` | Mausrad wechselt keinen Reiter |
| `test_timeline_global_register_applies_to_all_days` | `tests/test_gui_smoke.py` | globales Register |
| `test_scroll_offset_to_widget_top_uses_host_not_page_chrome` | `tests/test_gui_smoke.py` | Reveal ignoriert Reisetitel über der Liste |
| `test_reveal_group_puts_section_top_at_list_top` | `tests/test_gui_smoke.py` | Doppelklick scrollt Abschnittskopf an den Listenanfang |
| `test_gallery_rating_hotspots` | `tests/test_gui_smoke.py` | Bewertungs-Chips |
| `test_media_inspector_shows_original_and_ratings` | `tests/test_gui_smoke.py` | Inspektor mit Chips |
| `test_media_inspector_rotates_display_without_writing_original` | `tests/test_gui_smoke.py` | Drehen, Original-mtime gleich |
| `test_media_inspector_browses_section_sequence` | `tests/test_gui_smoke.py` | Blättern in der Sequenz |
| `test_inspector_keeps_photo_aspect_on_resize` | `tests/test_gui_smoke.py` | Eckgriff proportional |
| `test_inspector_allows_free_window_resize` | `tests/test_gui_smoke.py` | Ränder frei |
| `test_media_inspector_zoom_arrows_and_fit` | `tests/test_gui_smoke.py` | Zoom und Einpassen |
| `test_youtube_links_dialog_add_and_delete` | `tests/test_gui_smoke.py` | YouTube-Dialog |
| `test_parse_map_bridge_url_reads_group_key` | `tests/test_gui_smoke.py` | Karten-Expand-Bridge |
| `test_map_view_refresh_uses_disk_cache_without_rebuild` | `tests/test_gui_smoke.py` | Karten-Cache; Leiste unter dem WebView |
| `test_publish_map_display_writes_unique_file` | `tests/test_gui_smoke.py` | WebEngine lädt eine neue HTML-Kopie nach Rebuild |
| `test_map_view_applies_prepared_result_when_shown` | `tests/test_gui_smoke.py` | Hintergrund-Karte wird beim Öffnen der Seite übernommen |
| `test_map_timeline_strip_centers_first_card` | `tests/test_gui_smoke.py` | Timeline-Leiste zentriert; Zähler Fotos/Tracks/IGC/YouTube, Reserve-Schalter |
| `test_inspector_map_opens_thumbnail_then_original_on_double_click` | `tests/test_gui_smoke.py` | Vorschau, dann Original |
| `test_normalize_timeline_media_tab` | `tests/test_workspace.py` | gültige Tab-Namen |
| `test_timeline_media_tab_persists` | `tests/test_workspace.py` | `config.json` hält das Register |
| `test_sidebar_collapsed_persists` | `tests/test_workspace.py` | `config.json` hält die eingeklappte Navigation |
| `test_map_display_flags_persist_in_project` | `tests/test_workspace.py` | Zahnrad-Optionen in `settings.toml` |

---

## 5. Abdeckung gegen das Pflichtenheft

### 5.1 Gut abgedeckt (Phase 7 erweitert, R1.0.0)

- Dateiklassifikation und rekursiver Scan
- SHA-256 und Skip unveränderter Dateien
- EXIF-Zeitpriorität und Zeitzonenflag
- JPEG-GPS und Kamera
- HEIC-GPS/Kamera ohne ExifTool (ISO 6709, eingebettetes TIFF, Apple-Boxen)
- GPX-Parsing inkl. zeitloser und leerer Tracks, Interpolation, keine Überschreibung von EXIF-GPS
- IGC-Parsing, Pilot, DHV-Leonardo-Link überlebt Re-Import
- KML/GeoJSON-Parser für Track-Vorschauen (kein Ingest)
- JPEG-Thumbnails, HEIC-Vorschau (Windows-Shell/WIC oder eingebettetes JPEG), Originale unverändert
- Track-Thumbs (rote Spur, OSM-Ausschnitt oder schwarz offline)
- Importliste während des Einlesens und nach GPS-Abgleich, bevor Thumbnails erzeugt werden
- Sortierstatus Favorit/Reserve/Aussortiert inkl. Fallback auf Favoriten-Flag
- Import bricht bei einer defekten Datei (JPEG oder GPX) nicht ab
- Projekt anlegen, Schema (Abschnitte, URLs, Cover, Drehung), Wiederöffnen, `settings.toml` und Pfad-Rebase
- Karte: Titelbild-Kreise je Abschnitt/Resttag, Verbindungslinien zwischen Tag- und Aufenthaltskreisen, Layer-Menü Straßenkarte/Topo/Satellit, Zahnrad (Fotokegel, Reserve), Leiste darunter, Tagebuchtext und YouTube rechts, Detail mit Tracklinie und Fotomarkern (Stapel naher Fotos bis Zoom 16), Foto-Popup, offline ohne OSM
- Timeline: Tage aus Aufnahmezeit, manuelle Texte bleiben, Ortsvorschläge, `used_in_journal`
- Reiseabschnitte, Resttage, Pending-Vorschau, Eintrags-Titelbild (Foto und Track)
- YouTube- und DHV-Leonardo-URL-Normalisierung
- Anzeigedrehung (Index, Cachepfad, Re-Import, Inspektor ohne Originalschreiben)
- GUI-Rauch: Fenstertitel mit Version, Pipeline Import→Medien→Timeline, getrennte Medien/Tracks, Register nur per Klick, Inspektor Blättern/Zoom/Drehen
- Export- und Provider-*Verträge* existieren

### 5.2 Bewusst noch ohne Automatisierung

| Lücke | FA | Grund / nächste Phase |
| --- | --- | --- |
| Visuelle Marker-Vorschau / Bedienung in Qt | FA-050–FA-053 | Szene und Bridge in `test_maps.py` / `test_gui_smoke.py`; visuell MT-12 |
| Timeline-Bedienung | FA-060–FA-069, FA-080 | Logik in `test_timeline*.py`; visuell MT-13, MT-18–MT-21 |
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

## 7. Manuelle Testfälle (Phase 3 bis 7, Software R1.0.0, inkl. Windows-Paket)

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
| Kein Netzmonitor nötig; es dürfen keine Upload-Versuche sichtbar sein | erfüllt im Standardbetrieb (OSM-, optionale OpenTopoMap- und Esri-Kacheln sind Abrufe, kein Upload) |

### MT-08 Projekteinstellungen

| Schritt | Erwartung |
| --- | --- |
| Projekt → Einstellungen: GPS-Zeitfenster, Standardzeitzone, Kartenanbieter, Verbindungslinien-Farbe | Werte in `settings.toml`; Originale unverändert; Standardfarbe der Linien weiß |
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
| Nach Import Seite **Medien** öffnen | Vorschaubilder, chronologisch; Doppelklick öffnet den Medieninspektor; Reiter Alle/Favoriten/Reserve/Aussortiert |
| HEIC ohne eingebettetes JPEG (HEIF Image Extensions installiert) | echtes Vorschaubild, kein Absturz |
| HEIC ohne Codec/Erweiterung | Platzhalter, kein Absturz |

### MT-12 Karte

| Schritt | Erwartung |
| --- | --- |
| Nach Import mit GPX und Fotos (mit oder ohne EXIF-GPS) Seite **Karte** öffnen | ein runder Kreis je Tag, Transfer oder Aufenthalt; zwischen **Tag- und Aufenthaltskreisen** in Timeline-Reihenfolge eine Verbindungslinie mit Richtungsmarker; Layer-Symbol oben rechts mit Straßenkarte / Topo / Satellit; Zahnrad unter den Zoom-Buttons; ohne gesetztes Titelbild das erste Foto mit GPS, sonst der erste GPS-Track; darunter die Timeline-Leiste mit denselben Einträgen; **Übersicht aller Kreise** im Ausschnitt |
| Layer-Symbol: **Straßenkarte**, **Topo**, **Satellit** | wechselt OSM, OpenTopoMap und Esri World Imagery; Kreise und Linien bleiben; Quellenangabe je Anbieter; `offline` ohne Symbol |
| Zahnrad: **Fotokegel anzeigen** | ab Zoom 17 ein Kegel an Fotos mit Blickrichtung und Brennweite; Mouseover über ein Foto blendet die anderen Fotos und Kegel aus; bleibt nach Projekt-Neuöffnen |
| Zahnrad: **Reserve-Elemente anzeigen** aus | Reserve-Medien unsichtbar; Aussortierte nie auf der Karte; bleibt nach Projekt-Neuöffnen |
| Nach Änderungen in der Timeline Seite **Karte** öffnen | Karte erscheint ohne extra **Karte aktualisieren**, Übersicht aller Kreise |
| **Karte aktualisieren** | Karte lädt neu und zeigt wieder die Übersicht aller Kreise |
| Leiste: Tag-Karte | Kalendersymbol oben rechts |
| Leiste: Transfer-Karte | liegendes Sechseck, gleiche Größe wie Rechteckkarten; Schrift etwas kleiner |
| Leiste: Fokus | nur die zentrierte Karte in voller Größe, die anderen etwas kleiner |
| Leiste: Titelbild | füllt die Kartenfläche ohne sichtbare Ränder |
| Leiste: Zähler oben | Fotos, GPX-Tracks, IGC (Gleitschirm), YouTube-Logo als Symbol+Zahl; Reserve nur bei Zahnrad-Option |
| Einfachklick auf eine Leistenkarte | Karte zentriert, Zoom bleibt; rechts der Tagebucheintrag, nach Edit Speichern/Abbrechen/Verwerfen, darunter YouTube-Thumbs (zwei nebeneinander) falls vorhanden |
| Doppelklick auf eine Leistenkarte | Seite **Timeline**, derselbe Eintrag mit Kopfzeile oben in der Liste (unter Reisetitel und Werkzeugleiste) |
| Leiste nach links/rechts ziehen oder Mausrad | Karten verschieben sich horizontal; Klick trifft die Karte, nicht die OSM-Kacheln |
| Hineinzoomen, dann eine Leistenkarte anklicken | die Karte schwenkt auf diesen Eintrag, **Zoom bleibt** |
| Zwei nahe Tag-/Aufenthaltskreise, weit herausgezoomt | Verbindungslinie unsichtbar, sobald sich die Kreise überdecken |
| Zwei entfernte Tag- oder Aufenthaltskreise | Linie mit Pfeil in Timeline-Richtung; in der Detailansicht keine Linie |
| Doppelklick in die freie (nicht belegte) Kartenfläche | Übersicht: alle Kreise im Ausschnitt |
| Klick auf einen Kreis | Detailansicht: Fotos, Videos und Tracks dieses Eintrags, Ausschnitt angepasst; **Reiseabschnitt schließen** rechts neben dem Zoom-Plus stellt Zoom und Ausschnitt der Übersicht wieder her |
| Freie Karte: offene Hand (Verschieben); über einem Kreis: Zeiger (Auswahl) | der Kreis-Klick öffnet das Detail, startet kein Zoomen |
| Klick auf ein viereckiges Foto-Symbol im Detail | kleines Thumbnail-Popup auf der Karte (nicht sofort der Inspektor) |
| Mehrere Fotos fast am selben Ort, Zoom unter 17 | ein Stapel-Marker mit der Anzahl |
| Hineinzoomen auf Zoom 17 oder höher | Stapel löst sich auf; liegen Marker noch übereinander, rotiert der Stapel (Datum bündig unter dem Bild); Mouseover auf das gewünschte Foto blendet die anderen aus |
| Doppelklick auf das Thumbnail (oder das Foto-Symbol) | Medieninspektor mit dem **Original**, Blättern/Zoom/Drehen wie in der Timeline |
| Bestätigter Ort | erscheint im Detail des Tags |

### MT-13 Timeline

| Schritt | Erwartung |
| --- | --- |
| Nach Import Seite **Timeline** öffnen bzw. **Timeline aktualisieren** | ein Tag je Aufnahmedatum; Fotos am Kalendertag der Aufnahmezeit; Auto-Ereignis mit Medienzähler |
| Reisetitel oben ändern, **Speichern**, Projekt schließen und öffnen | Titel noch da; erneuter Timeline-Abgleich überschreibt ihn nicht |
| GPS-Fotos am selben Ort | kein automatischer Ortsname; Tag zeigt das Datum |
| Ort löschen, erneut abgleichen | kein neuer Auto-Ortsname |
| Timeline: Titel und Text speichern, Projekt schließen und öffnen | Text noch da, `origin=manual`; erneuter Timeline-Abgleich überschreibt den Text nicht |
| Timeline: Typ **Aufenthalt** bzw. **Transfer** an einem Tag | Abschnitt erscheint; Speichern nötig; Typ **Tag** löst wieder auf |
| Timeline: mehrere Fotos markieren, **Neuen Reiseabschnitt erstellen** (Aufenthalt) | Abschnitt erscheint; Tage bleiben; ohne Speichern und Verlassen fragt nach |
| Transfer mit mehreren Verkehrsmitteln, **Speichern**, ⊟ auflösen | Dateien wieder auf Tagen |
| YouTube im ⋯-Menü, Dialog-OK, **ohne** Speichern die Timeline verlassen und verwerfen | YouTube nicht in der DB |
| DHV-Leonardo extra an gespeichertem Tag, Dialog-OK | sofort in der DB; nie als „DAV“ bezeichnet |
| Chip **T** auf Foto und auf Track | Cover in der Kartenüberschrift; Video hat kein T |
| **Zur Karte** an einem gespeicherten Reiseabschnitt oder Tag | Seite **Karte**, passende Leistenkarte fokussiert |

### MT-18 Medieninspektor

| Schritt | Erwartung |
| --- | --- |
| Timeline: Doppelklick auf ein Foto in einem Tag mit mehreren Bildern | eigenes Fenster; Titel `datei.jpg · 2 von N` |
| Pfeiltasten oder Klick in den linken/rechten Rand | nächstes/vorheriges Bild derselben Sequenz; weiße Pfeile beim Überfahren der Ränder |
| Mausrad über dem Foto | Zoom um den Cursor; Ziehen verschiebt bei Zoom |
| Doppelklick in die Bildmitte | Einpassen |
| Ecke unten rechts ziehen | Fenster wächst proportional zum Foto |
| Fensterrand ziehen | frei breiter oder höher |
| Maximieren oder F11 | Foto eingepasst, schwarze Ränder, Zoom zurückgesetzt |
| Seite **Medien**: Doppelklick | dieselbe Sequenz wie die aktuelle Galerie |

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
| App ohne Projekt | Titelleiste `Reisetagebuch R1.0.0` |
| Projekt öffnen | `Reisetagebuch R1.0.0 - {Projekttitel}` |

### MT-22 Windows-Paket (FA-140–FA-144)

Voraussetzung: `packaging/build.ps1` erfolgreich; optional Inno Setup 6 für die Setup-EXE.

| Schritt | Erwartung |
| --- | --- |
| `dist/Reisetagebuch/Reisetagebuch.exe` starten (ohne venv, ohne `python` auf dem PATH) | Fenster `Reisetagebuch R1.0.0`; kein Python-Fehlerdialog |
| Neues Projekt anlegen, JPEG-Ordner importieren | Index und Thumbnails wie in der Entwicklungsumgebung; Originale unverändert |
| Seite **Karte** | WebEngine zeigt die Karte (nicht nur den HTML-Pfad) |
| `%LOCALAPPDATA%\TravelJournal` | `config.json` / `recent.json` wie bisher, nicht im Programmordner |
| `_internal/NOTICE.txt` und `_internal/LICENSE` | vorhanden |
| Optional: Setup-EXE, Installation ohne Admin | Programm unter `%LOCALAPPDATA%\Programs\Reisetagebuch`, Startmenüeintrag |
| SmartScreen beim ersten Start | dokumentiertes Verhalten ohne Signatur (FA-142); „Trotzdem ausführen“ erlaubt den Start |

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
| Timeline / Abschnitte | `test_timeline.py`, `test_timeline_sections.py`, manuell MT-13 |
| Karte / Leiste / Kreis-Detail | `test_maps.py`, `tests/test_gui_smoke.py` (Map-Fälle), manuell MT-12 |
| Inspektor / Drehung / Register | `test_orientation.py`, `tests/test_gui_smoke.py`, manuell MT-18–MT-21 |
| Windows-Paket (`packaging/`) | manuell MT-22 (kein pytest) |
| UI-Importliste | MT-04 |
| Vor Phasenabschluss | pytest grün + manuelle Fälle der Phase + Ruff |

Ein Phasenabschluss ohne grüne Automatisierung gilt als nicht abgenommen.

---

## 10. Nachweis der letzten Automatisierungsfahrt

| Datum | Kommando | Ergebnis |
| --- | --- | --- |
| 27.08.2026 | `python -m pytest` im Projekt-venv | 264 bestanden |
| 26.08.2026 | `python -m pytest` im Projekt-venv | 222 bestanden |
| 18.08.2026 | `python -m pytest` im Projekt-venv | 98 bestanden |

Diese Zeile bei der nächsten vollständigen Fahrt fortschreiben.
