# Architektur

Produktanforderungen: [pflichtenheft.md](pflichtenheft.md). Leitkonzept: [konzept.md](konzept.md). Tests: [testdokumentation.md](testdokumentation.md). Windows-Paket: [packaging/README.md](../packaging/README.md).

Stand: **Phase 7**, Software **R2.1.1** (30. August 2026). Journal-Modell nach Design-Review; Verbindungslinien; Karten-Popup, Cover-Zoom und Track-Bewertung.

## Prinzip

`travelcore` enthält die gesamte Analyse- und Persistenzlogik und hat **keine**
Abhängigkeit zu Qt/PySide6. `traveljournal` ist eine dünne Desktop-Schicht
(Views, ViewModels, Worker). Später kann `PhotoInspector` dieselbe Bibliothek
nutzen.

```
apps/traveljournal  ──uses──►  packages/travelcore
apps/photoinspector ─uses──►  packages/travelcore   (geplant)
```

Polar-Trainings-JSON mit `routes` ingestiert die App nicht. Das Hilfsskript
`scripts/json_routes_to_gpx.py` schreibt eine Sibling-GPX (`route.wayPoints`,
nicht `transitionRoute`). Aufruf und Kurzhilfe: [README.md](../README.md).
Tests: `tests/test_json_routes_to_gpx.py`. Das Skript gehört nicht zur GUI
und ändert die JSON-Datei nicht.

## Schichten

| Schicht | Ort | Aufgabe |
| --- | --- | --- |
| UI | `apps/traveljournal/.../ui`, `views`, `widgets` | Darstellung, keine Geschäftslogik |
| Services | `apps/traveljournal/.../services` | Qt-Threads, Dialoge, Fortschritt, Workspace, Undo-Stack |
| Domain | `travelcore.trip` | Reise, Kalendertag, Journal-Eintrag (Tag / Aufenthalt / Transfer), Ort, Ereignis (Pydantic) |
| Use Cases | `travelcore.media`, `gps`, `timeline`, `geolocation`, `maps`, `export` | Import, Zuordnung, Timeline, Karte, Export |
| Persistenz | `travelcore.database` | SQLAlchemy-Modelle, Alembic, Projektordner |

## Module in travelcore (Phase 7, R2.1.1)

| Paket | Inhalt |
| --- | --- |
| `media` | Scan, SHA-256, Indexer, Thumbnails, Galerie, Anzeigedrehung (`orientation`) |
| `metadata` | Pillow, HEIC-Container, optional ExifTool, Merge |
| `gps` | GPX/IGC-Parse und Ingest, KML/GeoJSON nur für Vorschauen, zeitliche Interpolation |
| `geolocation` | Aufenthaltscluster (Haversine, Radius 150 m) |
| `timeline` | Tage, Transfers und Aufenthalte als Abschnitte, Mitglieder, Journal-Zeit, Pool (`parked`), Links, Cover, manuelle Edits, Snapshots zum Wiederherstellen (`history`) |
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

**Synchronisieren** (`remove_missing` im Indexer, `travelcore.media.purge`) löscht
Indexzeilen für Dateien, die nicht mehr im Quellbaum liegen, inklusive
`section_members`, Cover-FKs, GPS-Tracks/Punkte, `file_errors` und Thumbnail-Cache.
Neue Medien können vor `sync_timeline` geparkt werden (Pool) oder wie nach der
Analyse Auto-Tagen zugeordnet werden. „Dateien analysieren“ bleibt additiv.

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
Farbe der Verbindungslinien auf der Karte (`map_link_color`, Standard `#ffffff`),
Kartenzahnrad (`map_show_photo_cones`, `map_show_reserve`, `map_show_sat_labels`, `map_show_sat_streets`).
Ändert sich die Quellwurzel, werden Index-Pfade umgeschrieben, die
Originaldateien nicht.

Zuletzt geöffnete Projekte stehen unter
`%LOCALAPPDATA%\TravelJournal\recent.json` (max. 10). Die Oberfläche listet
sie in R2.1.1 noch nicht. Der Fenstertitel lautet `Reisetagebuch R{Version}`
bzw. `Reisetagebuch R{Version} - {Projekttitel}`. Das Medienregister
(Timeline und Medienseite) steht in `%LOCALAPPDATA%\TravelJournal\config.json` (`timeline_media_tab`),
ebenso die Thumbnail-Schieber (`timeline_thumb_zoom`, `map_thumb_zoom`), die
eingeklappte linke Navigation (`sidebar_collapsed`), der Medienpool
(`timeline_pool_visible`, `pool_width`, `inspector_width` / `inspector_height` / `inspector_maximized`).

## Timeline

Nach dem Import ruft die App `sync_timeline` auf. Die Bibliothek:

1. legt eine `Trip`-Zeile an, falls fehlend
2. erzeugt oder aktualisiert `TripDay`-Zeilen je Kalendertag der Aufnahmezeit
3. legt Tag-Abschnitte mit Mitgliedern für unzugeordnete, nicht geparkte Medien an
4. legt ein automatisches Ereignis pro Tag an (Medienzähler)
5. schlägt Orte vor, wenn der Tag noch keine Orte hat
6. löscht leere Auto-Tage und leere Auto-Tag-Abschnitte ohne Text

Die Timeline-UI zeigt **Tage**, **Transfers** und **Aufenthalte** als
`trip_sections` mit `section_members`. Der Kartenkopf ist kompakt: Titelbild
in Thumbnail-Größe (`168` px), rechts zuerst der Titel, darunter Typ und Datum
in einer Zeile (`format_card_dates`: `12.12.2026` bzw. `11.11.2026 - 21.11.2026`),
danach Verbindungslinien (Transfer) bzw. Ausgangslinie (Tag/Aufenthalt), darunter der Tagebucheintrag. Feldtitel sitzen auf der Kartenfarbe;
dunkle Flächen sind die editierbaren Felder. Beim Verschieben des vertikalen
Schiebers erscheint links am Griff das Datum des Abschnitts in der
Bildmitte (`format_scroll_date`). Am Schieber des Medienpools erscheint dasselbe Chip
mit dem Aufnahmedatum des Mediums in der Bildmitte. Zwischen den Karten liegt ein
`TimelineJoin` (schlanke Linie mit **+** als Ring, `map_link_color`). Klick auf **+** öffnet denselben Dialog wie **Neuen Reiseabschnitt
erstellen** und füllt das Datum der Lücke (`insert_dates_between`). Zwischen den
Leistenkarten auf der Karte sitzt dasselbe **+**. Beim Index-Abgleich werden unzugeordnete,
nicht geparkte Medien dem Auto-Tag ihres Aufnahmedatums zugeordnet. Geparkte
Medien liegen im Medienpool: in der Timeline und auf der Medienseite eine
einblendbare rechte Spalte über die volle Höhe (Pfeil rechts außen wie die
Navigation, keine Abschnittskarte). Einklappen merkt die Breite (`pool_width`
in `config.json`) und stellt sie beim Ausklappen wieder her; ein/aus ist
`timeline_pool_visible`. Unabhängig von Tag, Transfer und
Aufenthalt. Wird die Spalte breiter gezogen, liegen die Vorschaubilder mehrspaltig.
Drag & Drop aus dem Pool auf einen gespeicherten Tag, Transfer oder Aufenthalt
ordnet die Medien dort zu (`move_members`, `parked` wird aufgehoben).
Dasselbe gilt beim Ziehen von einer Karte auf eine andere, ohne Umweg über den Pool;
die Journal-Zeit übernimmt das Datum bzw. die Spanne des Ziels. Ziehen auf den Pool parkt.
Während des Ziehens scrollt die Timeline, wenn der Zeiger den oberen oder unteren
Fensterrand bzw. den Rand der Karten-Spalte erreicht (`autoscroll_step`).
Die Medienseite zeigt denselben Bestand als zwei Bereiche: links
Reise-Medien, rechts den Medienpool — jeweils mit Alle / Favoriten /
Reserve / Aussortiert. Mehrfachauswahl wie in der Timeline (erster und letzter
Klick füllen den Bereich, Strg+Klick nimmt Löcher raus). Ziehen legt Medien
in den Pool oder zurück in die Galerie. Bewertung und Zugehörigkeit
(Abschnitt vs. Pool) sind unabhängig.
Jede Mitgliedschaft
trägt eine **Journal-Zeit** (`section_members.journal_at`, initial die Aufnahmezeit
inkl. Zeitzonenname). Die Timeline sortiert und gruppiert nach dieser Uhr;
`captured_at` bleibt das Original. Verschieben setzt nur `journal_at`. Ein Tag
folgt magnetisch dem Kalendertag der Journal-Zeit. Leere manuelle Abschnitte
speichern `started_at`/`ended_at` aus den Datumsfeldern (`span_for_manual_dates`:
Tag ein Kalendertag, Aufenthalt/Transfer von–bis). `set_section_span` ändert die
Spanne später; bei Tags rasten die Mitglieder auf den neuen Kalendertag ein.
Die Kartenreihenfolge folgt `_entry_sort_key` (leere Karten über
`section.started_at`). Auflösen eines Aufenthalts
oder Transfers erzeugt Tage nach Journal-Zeit. **Originalzeit** kopiert
`captured_at` zurück. Medien ohne GPS erben eine Anzeigeposition: Aufenthalt
live vom Ort/Cover, Tag als Snapshot vom Cover-Pin, Transfer entlang des Tracks
bei Journal-Zeit. Beim Verschieben auf einen Abschnitt kann der Benutzer
Original-GPS auf der Karte behalten oder die Abschnittsposition übernehmen
(`journal_latitude`/`journal_longitude`, mehrere Medien versetzt). Originale
GPS-Felder werden dabei nicht geschrieben.

`TimelineView._has_unsaved_work` steuert den Speichern-Button: aktiv bei
`_pending`, dirty Reisetitel, dirty Titel/Notizen oder dirty YouTube
(`youtube_urls` ungleich DB bzw. `_pending_youtube`). Bewertungen,
Anzeigedrehung, DHV-Leonardo und Cover an gespeicherten Einträgen schreiben
sofort und zählen nicht. `confirm_leave` fragt bei `_pending`
(Speichern/Verwerfen/Abbrechen) und bei nur `_pending_youtube`
(Verwerfen/Abbrechen); dirty Texte allein erzeugen keine Rückfrage.
`refresh()` ruft `_commit_if_dirty()` auf, sodass **Timeline aktualisieren**
ungespeicherte Texte mitschreibt.

Rückgängig/Wiederherstellen liegt in der GUI-Schicht, nicht in der Bibliothek.
`travelcore.timeline.history` liefert Snapshots (`SectionSnapshot`,
`MemberPlacement`, `JournalEdit`) und `restore_journal_edit`.
`traveljournal.services.edit_history.EditHistory` wickelt `QUndoStack`
(Limit 80). Der Workspace schiebt nach der Mutation ein Command mit
Undo-/Redo-Lambdas; die erste `redo` des Commands ist leer, weil die Aktion
schon gelaufen ist. Ungespeicherte Abschnitte (`_pending`) invertieren
`TimelineView` im Speicher. Steht der Fokus in einem Textfeld, greift zuerst
die Widget-Historie (`undo_focused_text` / `redo_focused_text`). Der Stack
wird geleert bei Projekt anlegen/schließen, Einstellungen, Import/Sync
(`_after_import`) und `TimelineView.rebuild`. YouTube, DHV-Leonardo und Orte
stehen nicht auf dem Stack.

Manuelle Titel, Notizen, bestätigte Orte, Foto-Flags
(`used_in_journal`, `is_cover`, `is_favorite`, `sort_status`), YouTube-URLs,
Eintrags-Titelbilder (`cover_source_file_id`, Foto oder GPS-Track) und
Anzeigedrehung (`rotation_degrees`) überleben Re-Sync bzw. Re-Import.
Der Reisetitel (`trips.title`) folgt zuerst dem Projektnamen; nach manueller
Eingabe in der Timeline (`origin=manual`) überschreibt der Abgleich ihn nicht.
Fotos gehören über `journal_at` (Mitgliedschaft) zu einem Tag; `captured_at`
ändert die Zugehörigkeit nicht. Das Flag `used_in_journal` ebenfalls nicht.

YouTube-URLs werden nur mit Timeline-Speichern persistiert.
DHV-Leonardo-URLs am IGC-Track und an gespeicherten Tagen/Abschnitten
schreiben beim Dialog-OK. Das Flugportal heißt ausschließlich DHV-Leonardo,
nie DAV.

Die Timeline legt Abschnitte an, schreibt den Reisetitel sowie Titel und Texte
über **Speichern**, setzt Bewertungen und Eintrags-Titelbilder (sofort an
gespeicherten Einträgen) und öffnet den Medieninspektor. Bewertungen auf der
Medienseite gelten in der Timeline; Änderungen aktualisieren Timeline, Karte
und Galerie.

Der Medieninspektor blättert in der Sequenz des Tags/Abschnitts bzw. des
Medienpools (oder der Medienseite); ein Bewertungs-Chip speichert und zeigt das nächste Foto
(das letzte bleibt); **In den Pool** ebenso. Er zoomt mit dem Mausrad, dreht die Anzeige in 90°-Schritten,
legt das aktuelle Medium mit **In den Pool** / **Zurückholen** in den Medienpool bzw. holt es zurück und
ändert Originale nicht. Reiter Alle/Favoriten/Reserve/Aussortiert (Timeline-Abschnitte,
Medien-Galerie und Pool) wechseln nur per Klick, nicht durch Mausrad. Pool ist
kein Filterregister, sondern ein Mediencontainer: auf der Timeline und der
Medienseite die einblendbare rechte Spalte (Pfeil rechts außen wie die Navigation),
jeweils mit eigenem Bewertungsregister (`pool_media_tab`, unabhängig von
`timeline_media_tab`). Die Breite überlebt Einklappen und steht in `pool_width`.
Aussortierte Medien erscheinen nur unter Aussortiert, nicht in Favoriten oder Reserve.
Im Register Alle blendet die Checkbox **Aussortierte anzeigen** sie ein (Standard aus,
`show_rejected_in_all` in `config.json`).

## Karte

`build_map_scene` (delegiert an `build_map_overview`) und `build_map_timeline`
in `travelcore.maps.groups` bauen die Übersicht: ein Titelbild je gespeichertem
Tag, Transfer oder Aufenthalt
(`cover_source_file_id`, sonst das erste Foto, sonst das erste Track-Thumbnail, sonst das erste YouTube-Vorschaubild). Position ist
die Journal-Anzeigeposition des Covers (`display_latitude`, sonst Original-GPS), sonst der Schwerpunkt der
Mitglieder mit Anzeigeposition, sonst `pin_latitude`/`pin_longitude`. Detailmarker und -reihenfolge folgen `section_members` und `journal_at`. Abschnitte ohne Koordinate bleiben in der
Leiste mit rotem Rand. Rechtsklick **Platzieren** / **Verschieben** (Fadenkreuz, Zoom und Fokus bleiben) bzw. **Zentrieren** (schwenkt und zoomt auf den Kreis). Unsaved
Pending-Abschnitte erscheinen nicht auf der Karte. Zwischen **Tag- und Aufenthaltskreisen**
in Timeline-Reihenfolge liegen `StayLink`-Polylinien. Transfer-Kreise sind keine
Endpunkte. Der erste Transfer in der Lücke besitzt eine geordnete Liste
`transfer_links` (Linie, Track, Bogenlinie, Route als Platzhalter; solid/gestrichelt;
Symbol; optional GPX-Member). Fehlt der Transfer, gilt die eine Ausgangslinie des linken
Tag- oder Aufenthalts (`outbound_*` an `trip_sections`: gerade/Bogen, solid/gestrichelt,
Symbol, oder `none`). Alle `NULL` = Gerade mit Richtungspfeil. `none` = keine Linie.
Track und Route gibt es dort nicht.
Ohne Zeilen bleibt die bisherige Gerade mit Pfeil. Mehrere
Zeilen werden in Timeline-Reihenfolge gezeichnet; Lücken zwischen Linienenden
oder Linie und Cover füllt eine gepunktete Gerade. Das Symbol ersetzt den
Richtungsmarker der jeweiligen Nutzerkante. Ein Transfer-Kreis (kein Linienende)
hängt mit einer dünnen Linie am Verkehrssymbol; Klick auf Kreis oder Symbol
öffnet die Detailansicht des Transfers. Bei überdeckenden Kreisen
(Pixelabstand ≤ Cover-Durchmesser) blendet das Leaflet-Skript die Linie aus.
`via_transfer` ist gesetzt, sobald ein Transfer zwischen den Endpunkten liegt.
In der Detailansicht sind die Linien ausgeblendet.

Folium schreibt `cache/map.html` (`MAP_CACHE_VERSION` im Stamp). Qt WebEngine
zeigt die Datei; die kompakte Leiste (`MapTimelineStrip`) sitzt **unter** dem
WebView, nicht als Overlay über Chromium — sonst verschluckt die Karte Klicks.
Zwischen den Leistenkarten sitzt ein **+** (`MapSpine`); Klick öffnet denselben
Dialog wie in der Timeline und füllt das Datum der Lücke.
Klick auf eine Leistenkarte in der Übersicht ruft `traveljournalFocusCover` auf: Schwenken bei
**unverändertem Zoom**. In der Detailansicht schließt derselbe Klick das Detail
(`traveljournalCloseSection`) und zoomt auf den Cover-Kreis (`ZoomToCover`);
der Mauszeiger folgt der Karte zur Mitte. Oben auf den Leistenkarten stehen Zähler für Fotos, GPX-Tracks, IGC-Flüge und YouTube-Links; Reserve-Medien zählen nur, wenn **Reserve-Elemente anzeigen** im Zahnrad aktiv ist. Rechts neben der Karte stehen der Tagebucheintrag der
fokussierten Karte (nach Bearbeitung Speichern, Abbrechen oder Verwerfen; beim Kartenwechsel als Dialog). YouTube-Vorschaubilder liegen unten rechts auf der Karte übereinander. Doppelklick auf eine Leistenkarte öffnet denselben Eintrag
in der Timeline mit der Karten-Oberkante bündig unter der Werkzeugleiste (nicht zentriert). Der erste Klick auf einen Kreis (`group_key`) ruft `ZoomToCover` auf
(mindestens Zoom 14, ohne Zoomanimation). Überlappen mehrere Cover-Kreise,
passt `traveljournalFitCoverPack` zuerst die Gruppe ein; ein späterer Klick
zoomt auf einen Kreis. Der zweite Klick auf denselben Kreis öffnet die
Detailansicht (`traveljournalShowDetail`): Fotos, Videos, GPX-Linien,
IGC-Flugtracks ab Zoom 10 (Start/Landung immer sichtbar) und Orte.
Rechtsklick **Zur Karte…** auf einem Timeline-Thumbnail öffnet dieselbe Detailansicht
und zentriert auf dem Medium (`traveljournalFocusMedia`).
Klick auf einen Transfer-Kreis oder auf das Verkehrssymbol öffnet dieselbe
Detailansicht (`traveljournalExpand` mit `section:<id>`).
`resolve_map_group` liest nur den angeklickten Eintrag, nicht die ganze
Timeline. Klick auf ein einzelnes Foto im Detail öffnet ein Leaflet-Popup mit Thumbnail;
`centerBrowseView` setzt die Karte **vor** `openPopup` so, dass Popup, kleines
Karten-Thumb und Datums-Label gemeinsam vertikal zentriert sind. Das Bild
erscheint nur an dieser Stelle. Pfeile und Pfeiltasten blättern
(`traveljournalPopupStep`, Wrap-around) ohne den Thumbnail-Modus zu verlassen;
nur ein Klick in die freie Karte stellt den Stapel wieder her. Der Schieber
`traveljournalSetThumbZoom` ändert `--tj-popup-thumb` (50–200 %), nicht die
kleinen Marker. Foto- und Track-Popups haben dieselbe Bewertungsleiste.
Bei einem Stapel fächert der erste Klick die Bilder auf.
Doppelklick öffnet den Medieninspektor mit dem Original (wie Timeline).
Nahe Foto-, Video- und Track-Marker werden bis Zoom 16 gestapelt
(`PHOTO_STACK_DISABLE_ZOOM` = 17); der Stapel-Marker zeigt die Anzahl.
Ab Zoom 17 liegen sie einzeln, auch übereinander, mit sichtbaren Fotokegeln.
Klick auf den Stapel fächert die Bilder rund auseinander, ohne Fotokegel;
der Fächer bleibt. Klick auf ein Bild im Fächer blendet die übrigen aus und
setzt Bild und Kegel an den Ursprung; ein weiterer Klick öffnet das Thumbnail-Popup.
Blättern im Popup funktioniert auch unter Zoom 17 (`revealEntryMarker`).
Orte bleiben ungestapelt. Übersichtstitelbilder clustern nicht.
Zwischen Zoom-Plus und Zahnrad sitzt **Ganze Reise** (`tj-fit-trip`).

Online-Kacheln kommen von `tile.openstreetmap.de` (deutsche Namen, sonst
lateinische Umschrift statt Landesschrift). Ein Layer-Symbol oben rechts öffnet
Straßenkarte (OSM), Topo (OpenTopoMap) und Satellit (Esri World Imagery); die Wahl
bleibt in `localStorage`. Über dem Satelliten kann das Zahnrad **Ortsnamen auf Satellit**
(Carto Voyager Labels, OSM-Namen, in Europa meist Latein) und **Straßen auf Satellit**
(Esri World Transportation) legen; beide Standard aus. Ein Zahnrad unter den Zoom-Buttons
schaltet Fotokegel (ab Zoom 17, aus `heading_degrees` und 35-mm-Brennweite; am Stapel und
nach der Auswahl am Ursprung, nicht im Fächer), Reserve-Medien und die Satelliten-Overlays;
die Schalter stehen in `settings.toml`. Das Datums-Label am Foto sitzt bündig unter dem
Vorschaubild. Aussortierte Medien kommen nicht auf die Karte. `map_provider=offline` setzt
`tiles=None` (keine OSM-, OpenTopoMap-, Satelliten- oder Carto-Kacheln, kein Umschalter). Fehlt Qt WebEngine, bleibt der Pfad sichtbar.

## Verkehrsmittelsymbole

Katalog: `travelcore.timeline.symbols.TRANSPORT_SYMBOLS`. Die Keys müssen zu
`MOVEMENT_MODES` in `travelcore.timeline.sections` passen (`transfer_links.symbol`
ist `String(16)`). Hilfe, ModePicker und die Transfer-Combo iterieren denselben
Katalog. Eingebettete Pfade, keine Laufzeit-Downloads. Nach einer Änderung
`MAP_CACHE_VERSION` in `travelcore.maps.cache` hochzählen. Lizenzen und URLs
stehen auch in `packaging/NOTICE.txt`.

Auf der Karte folgt die Nase der Linie zum Folgekreis. Ab 90° Abweichung
von rechts spiegelt ein inneres `scaleX(-1)` zuerst, die äußere Drehung
nimmt nur die restliche Steigung — Räder und Kiel bleiben unten.

| Key | Label | Quelle |
| --- | --- | --- |
| `car` | Auto | Phosphor Bold `car-profile` (MIT), Seitenansicht nach rechts |
| `campervan` | Camper Van | [SVG Repo 480849/delivery-car](https://www.svgrepo.com/svg/480849/delivery-car), im Katalog gespiegelt (Nase nach rechts) |
| `camper` | Camper | [SVG Repo 480908/camper-2](https://www.svgrepo.com/svg/480908/camper-2), im Katalog gespiegelt (Nase nach rechts) |
| `climb` | Klettern | [SVG Repo 307723/climb-person-people-climber](https://www.svgrepo.com/svg/307723/climb-person-people-climber) |
| `plane` | Flugzeug | Phosphor Bold `airplane`, im Katalog 90° gedreht (Nase nach rechts) |
| `bus` | Bus | [SVG Repo 455207/bus-vehicle](https://www.svgrepo.com/svg/455207/bus-vehicle) |
| `train` | Bahn | [SVG Repo 382850/train-toy-baby](https://www.svgrepo.com/svg/382850/train-toy-baby) |
| `walk` | zu Fuß | [SVG Repo 489218/walk](https://www.svgrepo.com/svg/489218/walk) |
| `bike` | Fahrrad | [SVG Repo 488802/bike](https://www.svgrepo.com/svg/488802/bike) |
| `boat` | Schiff | [SVG Repo 271469/ship](https://www.svgrepo.com/svg/271469/ship) |
| `other` | Sonstiges | Phosphor Bold `arrow-right` (nur wenn gewählt; sonst Richtungspfeil ohne Kreis) |

Phosphor: https://github.com/phosphor-icons/core (MIT).

Neues Verkehrsmittel:

1. SVG wählen (Phosphor Bold MIT oder SVG Repo), URL in die Tabelle und in
   `packaging/NOTICE.txt` schreiben.
2. Key (höchstens 16 Zeichen) in `MOVEMENT_MODES` **vor** `other` eintragen.
3. `TransportSymbol` in `symbols.py` anlegen. Ziel-viewBox 256; Farbe über
   `::FILL::` / `::COLOR::`. Seitenansicht: `_fit(native, …)`; Quelle nach
   links: `_fit(..., flip_x=True)`. Kontur: `_stroke`. Frontansicht Phosphor:
   `_path(..., from_up=True)`, damit die Nase nach rechts zeigt. Kein
   verschachteltes `<svg>` (Qt SVG Tiny).
4. `MAP_CACHE_VERSION` erhöhen. Hilfe und Tests folgen dem Katalog.

## Austauschbare Schnittstellen

Bereits in Phase 1 angelegt, schrittweise gefüllt:

- `MetadataProvider` – Pillow für JPEG/TIFF/WebP/PNG; HEIC: eingebettetes EXIF-TIFF,
  QuickTime/ISO-6709 und Apple-`data`-Boxen; optional ExifTool für HEIC/RAW
- GPX- und IGC-Ingest in `travelcore.gps` – Tracks/Punkte in SQLite; Medien ohne EXIF-GPS
  in der Reihenfolge Foto → GPX → IGC (`photo_*`, `gpx_*`, `igc_*`);
  GPX-SourceFile mit Mittelwert der ersten Punkte und Startzeit (`gpx_track`);
  IGC mit Pilot (`igc_track`) und optionalem DHV-Leonardo-Link
- Thumbnails in `travelcore.media.thumbnails` – JPEG-Cache unter `thumbnails/`,
  große JPEGs per `Image.draft` statt Skip, HEIC über Windows-Shell/WIC oder eingebettetes JPEG, Originale nur gelesen;
  Track-Thumbs über `maps.static` (rote Spur, OSM-Kacheln in `cache/map_tiles`)
- Quellabgleich in `travelcore.media.purge` – fehlende Originale aus Index und Tagebuch entfernen; neue IDs für Pool vs. Timeline
- Anzeigedrehung in `travelcore.media.orientation` – nach EXIF-Transpose,
  Cachepfad enthält `_r90` bei nicht-null `rotation_degrees`
- `VideoMetadataProvider` – ffprobe-Adapter (noch nicht aktiv)
- `Exporter` – HTML, PDF, LaTeX, CEWE (Implementierung ab Phase 8)
- `MapBackend` – Folium/Leaflet, Übersicht als Titelbild-Kreise je Tag/Transfer/Aufenthalt, Layer-Menü Straßenkarte/Topo/Satellit, Fit-Reise, Zahnrad für Fotokegel, Reserve, Satelliten-Ortsnamen und Satelliten-Straßen (in `settings.toml`; Fotokegel am Stapel und nach der Auswahl, nicht im Fächer; überlappende Marker ab Zoom 17 per Klick zum Fächer, Klick in die Karte stellt den Stapel wieder her),
  Verbindungslinien zwischen Tag- und Aufenthaltskreisen (Richtungsmarker, Zoom-Überdeckung, Transfer-Kreis per dünner Linie am Symbol),
  Qt-Leiste unter der Karte (Tag mit Kalender, Transfer als liegendes Sechseck), Tagebucheintrag rechts, YouTube-Thumbs unten rechts auf der Karte, Detail mit GPX-Polylinien, IGC-Flugtracks ab Zoom 10
  (Start/Landung immer sichtbar), Foto-Popup (Vorab-Zentrierung, Blättern, Schieber-Zoom, Bewertung) und Inspektor, Orte
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
- `012_drop_overnight_stays` – Übernachtungen entfernt
- `013_day_sections_parked` – Tag als Abschnitt, `source_files.parked`
- `014_section_member_journal` – Journal-Zeit und geerbte Position an `section_members`
- `015_section_pin` – manuelle Kreisposition
- `016_transfer_links` – Transfer-Verbindungslinien
- `017_section_outbound` – Ausgangslinie an Tag/Aufenthalt

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
7. Timeline und manuelle Bearbeitung  ← aktueller Stand, Software R2.1.1
   (Tag/Aufenthalt/Transfer als Abschnitte, Medienpool, Journal-Zeit,
    Verbindungslinien und Verkehrssymbole, Design-Review-UI, Bewertungen
    inkl. Tracks, Inspektor, Track-Vorschauen, Cover-Zoom, Foto-Popup,
    Anzeigedrehung, Rückgängig/Wiederherstellen)
   Windows-Endnutzerpaket: `packaging/` (keine eigene Fachphase)
8. HTML-Export
9. Qualitätsanalyse
10. Dublettenerkennung
