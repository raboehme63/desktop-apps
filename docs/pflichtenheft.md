# Pflichtenheft — Reisetagebuch

| Feld | Inhalt |
| --- | --- |
| Produkt | Reisetagebuch (Windows-Desktop) |
| Version | 3.0 (Software **R3.0.0**) |
| Stand | 30. August 2026 |
| Status | verbindlich für die Umsetzung; Phase 7 plus Medien-Pipeline, Software R3.0.0 |
| Bezug | Auftraggeber-Prompt „Reise-Tagebuch-Anwendung für Windows“ |
| Begleitdokumente | [konzept.md](konzept.md), [architecture.md](architecture.md), [testdokumentation.md](testdokumentation.md), [dependencies.md](dependencies.md), [packaging/README.md](../packaging/README.md) |

Dieses Pflichtenheft beschreibt **was** das System leisten muss. Das **wie** steht im Konzept und in der Architektur.

**R2.0.0** ist die Fassung nach dem Design-Review: drei gleichberechtigte Journal-Typen (**Tag**, **Aufenthalt**, **Transfer**) als Abschnitte mit Mitgliedern, ein **Medienpool** für nicht zugeordnete Dateien, eine **Journal-Zeit** je Clip neben der unveränderten Aufnahmezeit, und die überarbeitete Oberfläche (Pool-Spalte, Timeline-Verbindungen mit **+**, Drag & Drop mit Auto-Scroll, Kartenleiste mit **+**, Cover-Fallback, **Rückgängig / Wiederherstellen**).

**R2.1.0** ergänzt die geografische Erzählung: der Transfer besitzt eine geordnete Liste von Verbindungslinien (Linie, Track, Bogen; Route später; durchgezogen/gestrichelt; Verkehrsmittelsymbol). Ohne Transfer dazwischen steuert Tag oder Aufenthalt **eine** Ausgangslinie zum nächsten Nicht-Transfer (gerade/Bogen, **Keine Linie**, Symbol oder Richtungspfeil). Die Piktogramme zeigen in Fahrtrichtung (Katalognase nach rechts, auf der Karte Räder unten). Hilfe und Auswahllisten nutzen denselben Katalog. Auf dem Satelliten sind Ortsnamen und Straßen optional. HTML-Export bleibt Phase 8.

**R2.1.1** vertieft die Karten- und Medienbedienung: Tracks tragen dieselbe Bewertung wie Fotos (Register, Inspektor, Linien-Popup). Der Thumbnail-Schieber skaliert in der Timeline die Galerie und auf der Karte nur die große Popup-Vorschau. Cover-Kreise: erster Klick zoomt auf den Kreis (mindestens Zoom 14, ohne Zoomanimation); bei überlappenden Kreisen zuerst die Gruppe einpassen, danach ein Kreis. Zweiter Klick öffnet das Detail. Ein Fit-Reise-Button sitzt zwischen Zoom und Zahnrad. In der Detailansicht schließt ein Leistenklick das Detail, zoomt auf den Abschnitt und führt den Mauszeiger zur Kartenmitte. Foto-Popups blättern wie der Inspektor (Pfeile, Tasten, Wrap-around), bleiben im Thumbnail-Modus, erscheinen erst an der zentrierten Gruppe (großes Bild, kleines Karten-Thumb, Datum) und skalieren mit dem Schieber.

**R2.2.0** macht **Zur Karte** aus dem Medieninspektor und dem Thumbnail-Menü zur gleichen Sprungziel-Aktion: mehrere Original-Fenster gleichzeitig (versetzt), letzter Klick gewinnt. Die zugehörige Leistenkarte wandert in die Mitte, die Karte geht in den Detailmodus und zeigt das Medium (Popup an der Position). Ist die Karte in der Sitzung schon geladen, bleibt das HTML; Abschnittsdaten werden wiederverwendet. Ein Klick auf eine andere Leistenkarte schließt das Detail weiterhin und zoomt auf deren Cover.

**R3.0.0** ist die Medien-Vorauswahl: echte Dubletten (SHA-256) werden zu einem sofort akzeptierten **Stapel** mit einem Schlüsselfoto und Kennzeichen ×n. Ähnliche Fotos bildet **Ähnliche gruppieren** als vorgeschlagene Gruppe (Zeitfenster 30 s); **Auswahl gruppieren** bzw. Rechtsklick **Gruppieren** legt eine manuelle Gruppe ohne Schlüssel an. Schlüsselfotos setzt nur der Inspektor (**Schlüsselfoto** / Leertaste): Links/rechts durch Einzelbilder und alle Schlüssel, hoch/runter nur in der Gruppe. Vorgeschlagene Gruppen tragen keine Schlüssel. **Gruppe auflösen** entfernt die Gruppe, nicht die Fotos. Die Statistikleiste unten auf Medien zählt projektweit Importiert, Galerie, Aussortiert, Pool, Dubletten, Gruppen und Deaktiviert (Alembic `018_media_clusters`). Die Qualitätsampel (grün/gelb/rot) folgt in derselben Linie über **Qualität prüfen**. Unechte Dubletten (pHash) bleiben offen. Die Medien-Anzeigezeit (`media_at`) bleibt geplant.

Prioritäten:

- **Muss** — erforderlich für das MVP oder bereits in der aktuellen Phase
- **Soll** — vorgesehen, nicht MVP-blockierend
- **Kann** — später, nach bewusster Entscheidung
- **Abgrenzung** — wird nicht geliefert

Umsetzungsstand (Spalte *Stand*): **umgesetzt** | **teilweise** | **geplant**.

---

## 1. Zielbestimmung

### 1.1 Musskriterien

Das Produkt muss aus einem vom Benutzer gewählten Quellverzeichnis automatisch ein **zeitlich und geografisch strukturiertes Reisetagebuch** rekonstruieren und dieses anschließend **vollständig manuell** ergänzen, korrigieren, sortieren und verfeinern lassen.

Konkret muss das System:

1. Mediendateien und weitere Quelldaten rekursiv einlesen.
2. Metadaten analysieren (Aufnahmezeit, GPS, Kamera).
3. Dateien nach Datum und Ort gruppieren.
4. GPS-Tracks mit Fotos und Videos zeitlich abgleichen.
5. Reiseabschnitte und Aufenthaltsorte vorschlagen.
6. Bilder auf einer Karte darstellen.
7. Geeignete Fotos für das Tagebuch vorschlagen.
8. Dubletten und sehr ähnliche Fotos erkennen.
9. Eine bearbeitbare Reisechronik erzeugen.
10. Das Tagebuch in HTML, PDF, LaTeX und (später) CEWE exportieren.

Die Geschäftslogik muss in der GUI-freien Bibliothek `travelcore` liegen, damit dieselbe Analyse später von **PhotoInspector** wiederverwendet werden kann.

Punkt 5 ist für **manuelle Reiseabschnitte** (Tag / Aufenthalt / Transfer) in der Timeline und als Titelbilder auf der Karte umgesetzt. Automatische Abschnittsvorschläge (über die GPS-Ortscluster hinaus) fehlen noch. Punkt 8 ist in R3.0.0 teilweise (exakte Dubletten und Zeitszenen; keine pHash-Near-Duplicates). Punkt 10 bleibt Phase 8.

### 1.2 Wunschkriterien

- Ortsnamen-Auflösung (Reverse-Geocoding) — nur lokal oder nach ausdrücklicher Freigabe
- KI-Embeddings (z. B. CLIP) für Ähnlichkeit
- Videoinhaltsanalyse über reine Metadaten und Vorschaubilder hinaus

### 1.3 Abgrenzungskriterien

Nicht Bestandteil des Produkts und ausdrücklich **nicht** zu implementieren:

- KI-Modelle im MVP
- automatische semantische Bilderkennung / Gesichtserkennung
- Cloud-Dienste ohne explizite Aktivierung
- vollständiger CEWE-Export ohne vorherige Format- und Lizenzprüfung
- komplexes PDF-Layout in Version 1
- Videoinhaltsanalyse (Schnitt, Objekterkennung)
- automatisches Löschen von Originaldateien
- jede Änderung an Originaldateien
- macOS- oder Linux-Installer (Produktziel ist Windows 10/11)
- Übernachtungen als eigenes Datenobjekt

---

## 2. Produkteinsatz

### 2.1 Anwendungsbereiche

Lokale Nachbereitung privater oder beruflicher Reisen: Fotos, Videos, GPS-Tracks und Notizen werden zu einem bearbeitbaren digitalen Reisetagebuch zusammengeführt, vergleichbar dem Grundgedanken von Polarsteps, jedoch **offline und ohne Zwangskonto**.

### 2.2 Zielgruppen

| Gruppe | Nutzung |
| --- | --- |
| Reisende | Import eigener Medien, Korrektur der Chronik, Export als Bericht oder Fotobuch-Vorlage |
| Fotoarchivierende | später PhotoInspector: Dubletten, Unschärfe, Belichtung |
| Entwickler | Erweiterung über `travelcore`-Schnittstellen |

### 2.3 Betriebsbedingungen

| Merkmal | Anforderung |
| --- | --- |
| Plattform | Windows 10/11, 64-bit |
| Laufzeit | **Entwicklung:** Python 3.12 im Projekt-venv. **Endnutzer:** gebündelte `Reisetagebuch.exe` (kein separates Python). |
| Verteilung | Portable Zip bzw. Ordner `dist/Reisetagebuch/`; optional Inno-Setup-EXE (pro Benutzer nach `%LOCALAPPDATA%\Programs\Reisetagebuch`, ohne Administratorrecht). Siehe [packaging/README.md](../packaging/README.md). |
| Netz | nicht erforderlich; Standardbetrieb speichert alles lokal. OSM-Kacheln (Karte und Track-Vorschauen) und YouTube-Vorschaubilder werden nur geladen, wenn der jeweilige Anbieter aktiv ist bzw. Links angezeigt werden. Es gibt keinen Upload von Fotos, GPS oder Reisedaten. |
| Hardware | handelsüblicher PC; Import großer Fotoarchive darf die GUI nicht blockieren |
| Rechte | Lesezugriff auf das Quellverzeichnis; Schreibzugriff nur auf den Projektordner und `%LOCALAPPDATA%\TravelJournal`. Die optionale Setup-EXE schreibt zusätzlich nach `%LOCALAPPDATA%\Programs\Reisetagebuch`. |

---

## 3. Produktübersicht

Zwei Anwendungen teilen eine Bibliothek:

```
Quellmedien (unverändert)
        │
        ▼
   travelcore  ◄── traveljournal (PySide6)
        ▲
        └── photoinspector (geplant)
```

Ein Reiseprojekt ist ein **Ordner**, keine Einzeldatei:

```
meine_reise/
    project.sqlite
    settings.toml
    thumbnails/
    cache/          # map.html, map_tiles/
    exports/
    logs/
```

Die Datenbank speichert nur **Referenzen** auf Originaldateien. Originale werden nicht kopiert, sofern der Benutzer das nicht ausdrücklich wünscht.

Oberflächen-Einstellungen (zuletzt verwendeter Projekte-Ordner, Medienregister, Inspektor-Fenstergröße) liegen unter `%LOCALAPPDATA%\TravelJournal\config.json`. Zuletzt geöffnete Projekte stehen in `recent.json` (max. 10); die Oberfläche listet sie noch nicht.

---

## 4. Funktionale Anforderungen

### 4.1 Quellverzeichnis und Dateitypen

| ID | Prio | Anforderung | Stand |
| --- | --- | --- | --- |
| FA-010 | Muss | Der Benutzer wählt ein Quellverzeichnis. Der Scan ist rekursiv. | umgesetzt |
| FA-011 | Muss | Fotos: JPG, JPEG, PNG, WebP, TIFF, HEIC/HEIF sofern technisch möglich; RAW zunächst nur Metadaten/Vorschau. | teilweise (Index ja; RAW-Metadaten nur mit ExifTool; RAW-Vorschau über Windows-Shell/WIC oder eingebettetes JPEG, sonst Typ-Platzhalter) |
| FA-012 | Muss | Videos: MP4, MOV, AVI, MKV. Erste Version: Metadaten und Vorschaubilder, keine Inhaltsanalyse. | teilweise (Index ja; Vorschaubild über Windows-Shell/WIC oder eingebettetes JPEG in den ersten 8 MB, sonst Platzhalter; Video-Metadaten über ffprobe geplant) |
| FA-013 | Muss | GPS: GPX vollständig in der ersten Version; IGC (Gleitschirm-Fluglogs) mit Pilot und DHV-Leonardo-Link; KML und GeoJSON erkannt. | teilweise (GPX und IGC vollständig ingestiert und auf der Karte; KML/GeoJSON indexiert und für Track-Vorschauen geparst, **nicht** in `gps_tracks` übernommen und **nicht** für Foto-Zuordnung genutzt) |
| FA-014 | Soll | Texte: TXT, Markdown; optional JSON mit Reiseinformationen. | teilweise (Index ja; TXT/MD füllen Titel und Tagesetext, sofern der Tag noch nicht manuell ist; JSON-Auswertung geplant. Polar-Trainings-JSON mit `routes` wird nicht importiert; Hilfsskript `scripts/json_routes_to_gpx.py` erzeugt eine GPX neben der Datei, siehe README) |
| FA-015 | Muss | Versteckte Dateien und nicht unterstützte Typen werden übersprungen. | umgesetzt |
| FA-016 | Muss | Spätere Formate müssen über die Typklassifikation ergänzbar sein. | umgesetzt (Extension-Map) |

### 4.2 Dateiindex

| ID | Prio | Anforderung | Stand |
| --- | --- | --- | --- |
| FA-020 | Muss | Zentraler Dateiindex in SQLite je Projekt. | umgesetzt |
| FA-021 | Muss | Pro Datei: Pfad, Name, Typ, MIME, Größe, FS-Erstellung, FS-Änderung, SHA-256, Importzeit. | umgesetzt |
| FA-022 | Muss | Für Medien zusätzlich: Aufnahmezeit, Zeitzone, GPS, Blickrichtung (`GPSImgDirection` bzw. `GPSDestBearing`), Kamera, Objektiv, Brennweite, 35-mm-äquivalente Brennweite, ISO, Belichtung, Blende, EXIF-Orientierung, **Anzeigedrehung** `rotation_degrees` (0/90/180/270, Originale unverändert), Breite, Höhe. | umgesetzt (soweit in Metadaten vorhanden; Drehung manuell) |
| FA-023 | Muss | Originaldateien werden niemals verändert. | umgesetzt |
| FA-024 | Muss | Unveränderte Dateien (Größe, mtime, vorhandener Hash) werden beim Re-Import nicht neu gehasht; fehlende Metadaten dürfen nachgezogen werden. | umgesetzt |
| FA-025 | Muss | Die Importliste zeigt **alle** indexierten Dateien, nicht nur eine Teilmenge. | umgesetzt |
| FA-026 | Muss | **Synchronisieren** auf der Importseite gleicht das Quellverzeichnis mit dem Index ab: Dateien, die nicht mehr im Ordner liegen, werden vollständig aus dem Tagebuch entfernt (Index, Timeline-Mitgliedschaft, Titelbild-Referenz, GPS-Track, `file_errors`, Vorschaubilder). Neue Fotos, Videos und Tracks legt der Benutzer in die **Timeline** oder den **Medienpool**. Originale unverändert. „Dateien analysieren“ bleibt additiv (keine Löschung). | umgesetzt |

### 4.3 Metadatenanalyse

| ID | Prio | Anforderung | Stand |
| --- | --- | --- | --- |
| FA-030 | Muss | Analyse über EXIF, XMP, IPTC; Zugriff nur über `MetadataProvider`. | teilweise (EXIF/XMP über Pillow; IPTC geplant) |
| FA-031 | Muss | Zeitquellen-Priorität: DateTimeOriginal → CreateDate → XMP → Video → Dateisystem. | umgesetzt (Video noch Fallback) |
| FA-032 | Muss | Rohwert **und** normalisierter Zeitpunkt werden gespeichert; die Quelle ist nachvollziehbar. | umgesetzt |
| FA-033 | Muss | Fehlende Zeitzone darf nicht als UTC behauptet werden; Flag `timezone_unknown`. | umgesetzt |
| FA-034 | Muss | EXIF-GPS (Breite, Länge, Höhe) wird gelesen, sofern vorhanden. | umgesetzt |
| FA-034a | Soll | Blickrichtung aus `GPSImgDirection` (Fallback `GPSDestBearing`) inkl. True/Magnetic-Ref. | umgesetzt |
| FA-035 | Muss | Kamera und Aufnahmeparameter werden gelesen, sofern vorhanden, inkl. 35-mm-äquivalenter Brennweite. | umgesetzt |
| FA-036 | Muss | HEIC/HEIF: GPS und Kamera auch **ohne ExifTool**, aus eingebettetem EXIF-TIFF und/oder QuickTime ISO 6709 bzw. Apple-Metadatenboxen. | umgesetzt |
| FA-037 | Soll | ExifTool als optionaler Adapter für HEIC/RAW, nie direkt aus der GUI aufgerufen. | umgesetzt (Adapter; Binary optional) |
| FA-038 | Soll | Video-Zeit und -GPS über gekapselten ffprobe-Adapter. | geplant |

### 4.4 GPS-Tracks und Zuordnung

| ID | Prio | Anforderung | Stand |
| --- | --- | --- | --- |
| FA-040 | Muss | GPX einlesen; Trackpunkte mit Lat, Lon, Höhe, Zeit, Track-ID, Segment-ID. Die Trackdatei selbst erhält eine repräsentative Position (Mittelwert der ersten Punkte) und die Startzeit des ersten zeitbehafteten Punkts. | umgesetzt |
| FA-040a | Soll | IGC-Fluglogs einlesen (B-Records); Pilot aus dem Header; optionaler DHV-Leonardo-Link am Track, der beim Re-Import erhalten bleibt. | umgesetzt |
| FA-041 | Muss | Fotos ohne GPS: zuerst zeitnahe Fotos mit GPS, sonst GPX, sonst IGC; Interpolation zwischen benachbarten Punkten. Fehlt danach weiter eine Position, erbt das Medium die Anzeigeposition des Abschnitts (Aufenthalt: Ort/Cover; Tag: Cover-Pin; Transfer: Track bei Journal-Zeit), ohne Original-GPS zu schreiben. Beim Verschieben auf einen Abschnitt mit Kartenposition fragt die Timeline, ob vorhandenes GPS behalten werden soll; sonst gilt die Abschnittsposition (mehrere Medien leicht versetzt). | umgesetzt |
| FA-042 | Muss | Abgeleitete Position speichert Quelle, Vertrauenswert, Zeitdifferenz und ob EXIF oder Track. | umgesetzt |
| FA-043 | Soll | KML (LineString / gx:Track) und GeoJSON (LineString) werden für Track-Vorschauen geparst. Sie fließen nicht in die GPS-Zuordnung und nicht in die interaktive Karte. | umgesetzt (Parser + Thumbnail; kein Ingest) |

### 4.5 Karte

| ID | Prio | Anforderung | Stand |
| --- | --- | --- | --- |
| FA-050 | Muss | Interaktive Karte: Track als Linie, Fotos als Marker, Abschnitte, Tagesgruppen. | umgesetzt (Übersicht: ein runder Kreis je Tag/Transfer/Aufenthalt. Cover-Bild ohne gesetztes Titelbild: erstes Foto, sonst erstes Track-Thumbnail, sonst erstes YouTube-Vorschaubild. Kreisposition: Pin, sonst GPS des Covers/der Medien (`pin_latitude` / `pin_longitude`). Cover- und Detailposition folgen der Journal-Anzeige (`journal_at`, Overlay-GPS), nicht der unveränderten Aufnahme. Abschnitte ohne Position erscheinen in der Leiste mit **rotem Rand**. Rechtsklick auf eine gespeicherte Abschnittskarte: **Platzieren** (ohne Ort, Fadenkreuz, Zoom bleibt), **Verschieben** (mit Ort, Fadenkreuz setzt die neue Position; Zoom und Fokus der Leistenkarte bleiben), **Zentrieren** (schwenkt und zoomt auf den Kreis). Zwischen **Tag- und Aufenthaltskreisen** in Timeline-Reihenfolge eine Verbindungslinie mit Richtungsmarker an denselben Positionen; Linienfarbe in den Projekteinstellungen (`map_link_color`, Standard weiß). Umschalter über ein Layer-Symbol (Straßenkarte = OSM openstreetmap.de, Topo = OpenTopoMap, Satellit = Esri World Imagery); Zahnrad unter den Zoom-Buttons für **Fotokegel anzeigen** (ab Zoom 17, Blickrichtung und Brennweite) und **Reserve-Elemente anzeigen**; beide Schalter stehen in `settings.toml`. Das Datums-Label am Foto sitzt bündig unter dem Vorschaubild. Aussortierte Medien erscheinen nie auf der Karte. `offline` ohne Kacheln und ohne Layer-Umschalter, das Zahnrad bleibt. Transfer-Kreise sind keine Endpunkte; eine dünne Linie verbindet den Transfer-Kreis mit dem Verkehrssymbol. Klick auf den Transfer-Kreis oder auf das Symbol öffnet die Detailansicht. Überdecken sich die Kreise (abhängig vom Zoom), bleibt die Linie unsichtbar. Liegt ein Transfer dazwischen, bestimmt dessen Verbindungslinien-Liste das Linienbild (gerade, Bogen, Trackspur; Route später). Ohne Transfer gilt die Ausgangslinie des linken Tags oder Aufenthalts. Klick auf den Kreis öffnet die Detailansicht mit Fotos, Videos, Tracks und Orten dieses Eintrags und passt den Ausschnitt daran an; die Verbindungslinien sind dort ausgeblendet. IGC-Flugtracks im Detail ab Zoom 10 mit Start/Landung. **Reiseabschnitt schließen** (rechts neben dem Zoom-Plus) oder Doppelklick in die freie Karte stellt Übersicht, Zoom und Ausschnitt wieder her. Zwischen Zoom-Plus und Zahnrad sitzt **Ganze Reise** (passt alle Cover-Kreise ein, ohne Zoomanimation). Ein einfacher Klick auf einen Cover-Kreis zoomt auf diesen Kreis (mindestens Zoom 14, `ZoomToCover`, ohne Zoomanimation); überlappen mehrere Kreise, passt der erste Klick zuerst die Gruppe ein, ein späterer Klick zoomt auf einen Kreis. Der zweite Klick auf denselben Kreis öffnet das Detail. In der Detailansicht schließt ein Klick auf eine Leistenkarte das Detail, zoomt auf diesen Abschnitt und setzt den Mauszeiger auf die Kartenmitte) |
| FA-051 | Soll | Klick auf Fotomarker zeigt Vorschau; nahe Marker können clustern. | umgesetzt (im Detail: nahe Foto-, Video- und Track-Marker werden gestapelt; der Stapel-Marker zeigt die Anzahl. Ab Zoom 17 liegen die Marker einzeln, auch wenn sie sich überdecken. Mit **Fotokegel anzeigen** erscheint ab Zoom 17 ein Kegel aus Blickrichtung und 35-mm-Brennweite am Bild (nicht im Fächer). Überlappende Bilder bleiben gestapelt; Klick auf den Stapel fächert sie rund auseinander ohne Kegel. Der Fächer bleibt. Klick auf ein Bild im Fächer blendet die anderen aus und setzt Bild und Kegel an die Originalposition; ein weiterer Klick öffnet das Thumbnail-Popup. Klick in die Karte (nicht die Pfeiltasten) stellt den Stapel wieder her. Einzelne nicht gestapelte Marker öffnen das Popup direkt. Das Popup blättert durch die Fotos des Abschnitts (Hover-Pfeile, Pfeiltasten, Wrap-around) wie der Inspektor; Blättern funktioniert auch, wenn der Stapel bei Zoom unter 17 noch nicht aufgelöst ist. Die Karte zentriert **vor** dem Einblenden auf die Gruppe großes Thumbnail + kleines Kartenbild + Datum; das Bild erscheint nur an dieser Stelle, nicht zuerst am alten Marker. Der Thumbnail-Schieber der Kartenseite skaliert nur die große Popup-Vorschau (50–200 %), nicht die kleinen Marker oder Cover-Kreise. Foto- und Track-Popups haben dieselbe Bewertungsleiste wie der Inspektor. Doppelklick auf Thumbnail oder Foto-Symbol öffnet den Medieninspektor mit dem Original wie in der Timeline. Reserve-Medien nur bei gesetzter Option; Aussortierte nie. Orte und IGC-Start/Landung bleiben ungestapelt. Übersicht clustert nicht — ein Kreis je Eintrag) |
| FA-052 | Muss | Kartenbackend hinter `MapBackend` austauschbar; erste Version Folium/Leaflet. | umgesetzt |
| FA-053 | Muss | Unter der Karte eine horizontale Leiste mit kompakten Timeline-Karten (Titelbild, Titel, Zeitraum) in Reise-Reihenfolge. **Tag:** Kalendersymbol oben rechts. **Aufenthalt:** Rechteckkarte. **Transfer:** liegendes Sechseck (oben/unten flach, Spitzen links/rechts), gleiche Größe wie die anderen Karten; Beschriftung etwas kleiner. Titelbilder füllen die Karte ohne Ränder (Cover). Unfokussierte Karten etwas kleiner, die fokussierte in voller Größe. Ziehen und Mausrad blättern seitlich. Beim Öffnen der Karte (und nach **Karte aktualisieren**) Übersicht aller Titelbild-Kreise, wie nach Doppelklick in die freie Fläche. Einfachklick in der Leiste in der Übersicht zentriert den Eintrag **ohne Zoomänderung**. In der Detailansicht schließt derselbe Klick das Detail, zoomt auf den Cover-Kreis des Abschnitts (`ZoomToCover`) und führt den Mauszeiger zur Kartenmitte. Oben auf jeder Leistenkarte stehen Zähler für Fotos, GPX-Tracks, IGC-Flüge (Gleitschirmsymbol) und YouTube-Links (YouTube-Logo; Symbol + Zahl; Reserve nur bei **Reserve-Elemente anzeigen**). Rechts neben der Karte erscheint der **Tagebucheintrag** der fokussierten Leistenkarte (editierbar); nach einer Änderung **Speichern**, **Abbrechen** und **Verwerfen**; beim Fokuswechsel auf eine andere Leistenkarte derselbe Dialog; YouTube-Vorschaubilder liegen unten rechts auf der Karte übereinander, falls Links vorhanden sind. Doppelklick auf eine Abschnittskarte öffnet denselben Eintrag in der **Timeline**, Oberkante bündig unter Reisetitel und Werkzeugleiste (nicht die Kartenmitte). Doppelklick in die freie Karte zeigt alle Kreise. Nach Änderungen in der Timeline erscheint die Karte beim Öffnen ohne extra Aktualisieren. Abschnitte ohne Position haben einen **roten Rand**; Rechtsklick öffnet **Platzieren**, **Verschieben** oder **Zentrieren**. | umgesetzt (Qt-Leiste unter dem WebView, nicht als Overlay über den Kacheln) |

### 4.6 Timeline und Orte

| ID | Prio | Anforderung | Stand |
| --- | --- | --- | --- |
| FA-060 | Muss | Automatische chronologische Timeline (Tag → Ereignisse). | umgesetzt |
| FA-061 | Muss | Ebenen: Reise, Kalendertag (Gerüst für Orte und Ereignisse), Journal-Eintrag (**Tag** / **Aufenthalt** / **Transfer**), Ort, Ereignis, Medienobjekt, Textnotiz. | umgesetzt (alle drei Typen sind `trip_sections` mit `section_members`; ein Tag ist genau ein Kalendertag; Medien ohne Abschnitt liegen im **Medienpool**; Kalendertage `TripDay` bleiben für Orte, Auto-Ereignisse und Importtexte) |
| FA-062 | Soll | Aufenthalte aus GPS: konfigurierbarer Radius und Mindestdauer; nur als Vorschlag. | teilweise (Funktion vorhanden, Import erzeugt keine Ortsnamen an Foto-/Video-/Trackpositionen; Datum reicht) |
| FA-063 | Muss | Benutzer bestätigt, ändert oder löscht vorgeschlagene Orte. | umgesetzt |
| FA-064 | Muss | Der Timeline-Button **Speichern** ist nur aktiv, wenn es etwas gibt, das erst mit diesem Button in die Datenbank geht: ungespeicherte Abschnitte, geänderter Reisetitel, geänderter Titel oder Tagebuchtext, geänderte YouTube-Links. Bewertungen, Anzeigedrehung, DHV-Leonardo an gespeicherten Einträgen und Eintrags-Titelbild an gespeicherten Einträgen speichern sofort und aktivieren **Speichern** nicht. **Speichern** schreibt Abschnitte, Reisetitel, Texte und YouTube. **Timeline aktualisieren** schreibt geänderte Texte und den Reisetitel mit, persistiert aber keine Abschnitte und kein YouTube. Verlassen der Timeline (Seitenwechsel oder Fenster schließen) fragt bei ungespeicherten Abschnitten (Speichern / Verwerfen / Abbrechen) und bei nur ungespeicherten YouTube-Links (Verwerfen / Abbrechen). Nur geänderte Texte oder nur ein geänderter Reisetitel erzeugen keine Rückfrage; beim Schließen des Fensters gehen sie verloren. | umgesetzt |

### 4.6a Reiseabschnitte, Links, Tage

| ID | Prio | Anforderung | Stand |
| --- | --- | --- | --- |
| FA-065 | Muss | Der Benutzer erzeugt Reiseabschnitte aus einer Mehrfachauswahl: **Aufenthalt** (`stay`) oder **Transfer** (`movement`). Ohne Auswahl legt **Neuen Reiseabschnitt erstellen** einen leeren Abschnitt an (Tag, Aufenthalt oder Transfer): Tag mit **Am**, Aufenthalt/Transfer mit **Von Datum** / **Bis Datum**. Zwischen den Karten öffnet **+** auf der Verbindungslinie denselben Dialog und füllt das Datum der Lücke vor (Tag: erster Lückentag; Aufenthalt/Transfer: von–bis der offenen Tage). Auf der Karte öffnet **+** zwischen den Leistenkarten denselben Dialog. Später ändert ⋯ **Datum…** (Tag) bzw. **Zeitraum…** (Aufenthalt/Transfer) dieselbe Spanne. Der Typ jedes Eintrags ist in der Timeline änderbar: **Tag**, **Transfer**, **Aufenthalt**. Tag ist immer genau ein Kalendertag. Transfer hat eine geordnete Liste von Verbindungslinien (Linie, Track aus den GPX-Membern des Abschnitts, Bogenlinie; Route später). Die Zeilen sind auf der Timeline-Karte verschiebbar; pro Zeile durchgezogen/gestrichelt und ein Verkehrsmittel-Symbol. Tag und Aufenthalt haben **eine** Ausgangslinie zum nächsten Nicht-Transfer (gerade/Bogen, solid/gestrichelt, Symbol; leer = Richtungspfeil auf der Geraden; **Keine Linie** unterdrückt die Verbindung). Track und Route gibt es dort nicht. Lücken zwischen Linien oder Linie und Cover-Kreis füllt eine gepunktete Gerade. Die Zeitspanne folgt den Objekten (`am …` bzw. `von … bis …` intern, auf der Karte als `12.12.2026` bzw. `11.11.2026 - 21.11.2026`), bei leeren Abschnitten dem gewählten Datum bzw. Zeitraum; die Timeline sortiert danach. Der Kartenkopf zeigt Titelbild (Thumbnail-Größe), rechts zuerst den Titel, darunter Typ/Datum, danach die Verbindungslinien, darunter den Tagebucheintrag. **Löschen** im ⋯-Menü entfernt den Abschnitt und legt alle Medien in den **Medienpool**. An gespeicherten Abschnitten **Zur Karte** öffnet die Karte und fokussiert die passende Karte in der Leiste. Rechtsklick auf ein Thumbnail mit Kartenposition öffnet **Zur Karte…** und die Detailansicht des Abschnitts, zentriert auf diesem Medium. | umgesetzt |
| FA-066 | Muss | Medien, die keinem Abschnitt gehören, liegen im **Medienpool**. Pool ist ein Mediencontainer, kein Bewertungsfilter: in der Timeline und auf der Medienseite eine **rechte Spalte über die volle Höhe**, ein-/ausklappbar mit Pfeil rechts außen wie die Navigation. Die Breite bleibt beim Einklappen erhalten (`pool_width` in `config.json`). Beide Pool-Flächen haben dasselbe Bewertungsregister Alle/Favoriten/Reserve/Aussortiert, unabhängig vom Register der Abschnitte bzw. der linken Galerie. Auf der Medienseite gilt dieselbe Mehrfachauswahl wie in der Timeline; Ziehen legt Medien in den Pool oder zurück in die Galerie. In der Timeline ziehen Medien direkt von einer gespeicherten Karte auf eine andere (ohne Umweg über den Pool): die Journal-Zeit übernimmt das Datum bzw. die Spanne des Zielabschnitts, bei eigenem GPS dieselbe Rückfrage wie aus dem Pool; Ziehen auf den Pool parkt. Am oberen und unteren Fensterrand bzw. am Rand der Timeline-Spalte scrollt die Liste während des Ziehens, damit Medien auch auf weit entfernte Karten gelegt werden können. Timeline mischt **Tage**, Transfers und Aufenthalte chronologisch. Ein Tag ist genau ein Kalendertag und hat Mitglieder wie Aufenthalt/Transfer. Jedes Mitglied hat eine Journal-Zeit (initial Aufnahmezeit); Verschieben ändert nur diese Uhr. Auflösen (⊟) von Transfer/Aufenthalt erzeugt Tage nach Journal-Zeit. **Löschen** legt die Medien in den Pool statt auf Tage. Originalzeit setzt die Uhr zurück. | umgesetzt |
| FA-067 | Muss | Neu angelegte Abschnitte existieren nur im Speicher (`PendingSectionSpec`, negative `local_id`), bis Timeline-**Speichern**. Overlay `apply_pending_sections` ist Vorschau, kein Schreiben. | umgesetzt |
| FA-068 | Muss | YouTube-Links gehören zu Tag oder Abschnitt. Sie werden **nur** mit Timeline-**Speichern** persistiert, nie still beim Dialog-OK. Nur YouTube-Hosts; Duplikate entfallen. | umgesetzt |
| FA-069 | Muss | DHV-Leonardo-Links: am IGC-Track sofort speicherbar (Import-Doppelklick und Timeline-Menü). Zusätzliche Links an gespeichertem Tag/Abschnitt ebenfalls sofort beim Dialog-OK; an ungespeicherten Abschnitten erst mit Timeline-Speichern. Nie als „DAV“ bezeichnen. | umgesetzt |

Auswahlmodell in der Timeline und auf der Medienseite: erster und letzter Klick füllen den Bereich dazwischen; Strg+Klick entfernt Löcher. Das Menü **⋯** (YouTube, DHV-Leonardo) gilt auch für noch nicht gespeicherte Abschnitte (`entity_id != 0`).

### 4.7 Fotoqualität, Dubletten, Ranking

| ID | Prio | Anforderung | Stand |
| --- | --- | --- | --- |
| FA-070 | Soll | Technische Qualität: Auflösung, Seitenverhältnis, Helligkeit, Kontrast, Schärfe, Über-/Unterbelichtung. Nur Empfehlung, nie automatisches Löschen. | umgesetzt (Ampel aus `technical_quality`; Knopf **Qualität prüfen**; ändert weder `sort_status` noch Originale) |
| FA-071 | Soll | Komponente `photo_similarity`: exakte Dubletten (SHA-256), visuelle Ähnlichkeit (dHash/pHash); später Embeddings. | teilweise (SHA-256-Stapel und 30-s-Szenengruppen in `travelcore.similarity.clusters`; keine pHash/dHash/Embeddings) |
| FA-072 | Muss | Kein automatisches Löschen von Originalfotos. | umgesetzt (kein Löschpfad) |
| FA-073 | Soll | Ranking je Ereignis/Ort über austauschbare `RankingStrategy`. | teilweise (Schnittstelle) |

### 4.8 Manuelle Bearbeitung

| ID | Prio | Anforderung | Stand |
| --- | --- | --- | --- |
| FA-080 | Muss | Tagebuch vollständig bearbeitbar: Tage, Orte, GPS, Ereignisse, Texte, Fotos, Reihenfolge, Titelbilder, Abschnitte. | teilweise (Timeline: Reisetitel, Tage/Aufenthalte/Transfers, Titel/Text, Abschnitte, Eintrags-Titelbilder, Journal-Zeit und Originalzeit, Drag & Drop Karte↔Karte und Pool; Reisetitel, Titel, Texte und YouTube gemäß FA-064; Rückgängig/Wiederherstellen gemäß FA-085; `used_in_journal` und Reise-Titelbild `is_cover` in `travelcore`, ohne eigene UI; keine Ereignis-Reihenfolge) |
| FA-081 | Muss | Automatisch erzeugte und manuelle Daten sind unterscheidbar (`origin=auto\|manual`). | umgesetzt |
| FA-082 | Muss | Jedes Foto und jeder Track trägt einen Sortierstatus `favorite` / `reserve` / `rejected` (oder leer). `is_favorite` bleibt synchron. Leerer Status plus altes Favoriten-Flag gilt als Favorit (`effective_sort_status`). Klick auf den aktiven Status hebt ihn auf. Abgelehnte Vorschaubilder sind abgedunkelt. **Aussortierte** erscheinen nur im Register Aussortiert, nicht in Favoriten / Reserve. Im Register **Alle** blendet eine Checkbox **Aussortierte anzeigen** sie ein oder aus (Standard aus; `show_rejected_in_all` in `config.json`). Speichern sofort. Bewertung in **Medien** gilt auch in der Timeline (und umgekehrt); Tracks nutzen dieselben Reiter und denselben Inspektor. Auf der Karte gelten dieselben Chips im Foto- und Track-Popup. | umgesetzt |
| FA-083 | Muss | Zwei Titelbilder: (1) **Reise-Titelbild** `Photo.is_cover`; (2) **Eintrags-Titelbild** `cover_source_file_id` an Tag oder Abschnitt, Chip **T** auf Foto- **und Track**-Thumbs, 72-px-Vorschau in der Timeline-Kartenüberschrift. Videos sind keine Titelbilder. An gespeicherten Einträgen sofort; an ungespeicherten Abschnitten erst mit Speichern. | teilweise (Eintrags-Titelbild in der Timeline; Reise-Titelbild nur in `travelcore`, ohne UI) |
| FA-084 | Soll | Beim Bewegen des vertikalen Timeline-Schiebers erscheint am Schieber das Datum des Abschnitts in der Bildmitte (ein Kalendertag bzw. kompakt von–bis). Dasselbe Chip am Schieber des **Medienpools** (Aufnahmedatum des Mediums in der Bildmitte). | umgesetzt |
| FA-085 | Muss | Journal-Edits sind rückgängig und wiederholbar: Menü **Bearbeiten → Rückgängig / Wiederherstellen**, Tastatur **Strg+Z / Strg+Y**. Der Stack umfasst Zuordnen und Parken, Bewerten, Drehen, Abschnitt einfügen/löschen/auflösen (auch ungespeicherte), Typ und Datum, Kartenposition, Journal-Zeit und Originalzeit, Titel und Tagebucheintrag, Reisetitel, Eintrags-Titelbild, Transfer-Verbindungslinien und die Ausgangslinie. In einem Textfeld gilt zuerst die Widget-Historie. Import, Synchronisieren, Timeline aktualisieren, Projekt öffnen/schließen und Einstellungen leeren den Stack. YouTube, DHV-Leonardo, Orte und Projekteinstellungen gehören nicht dazu. | umgesetzt |

### 4.9 Benutzeroberfläche

| ID | Prio | Anforderung | Stand |
| --- | --- | --- | --- |
| FA-090 | Muss | Moderne Windows-UI mit PySide6, Navigation links. Fenstertitel: `Reisetagebuch R{Version}` bzw. `Reisetagebuch R{Version} - {Projekttitel}`. | umgesetzt (Rahmen; Version **R3.0.0**; linke Pipeline mit Symbolen, einklappbar nur Icons, ausgeklappt inhaltsbreit; Zustand in `config.json`) |
| FA-091 | Muss | Bereich Projekt: neu, öffnen, speichern; Menü **Projekt → Einstellungen** (Dialog mit vertikalem Schieber). | teilweise (neu/öffnen/speichern/Einstellungen; zuletzt verwendete Projekte intern in `recent.json`, noch ohne UI-Liste; Projekte-Stammordner in `config.json`) |
| FA-092 | Muss | Bereich Import: Ordner, Analyse, **Synchronisieren**, Fortschritt, Dateiliste mit Zeit/GPS/Kamera. Klick/Mouseover zeigt Vorschau und Metadaten. Die Liste wird während des Einlesens periodisch aktualisiert, erneut nach GPS-Abgleich, und vor den Vorschaubildern. | umgesetzt (Kamera/Pilot; DHV-Leonardo per Doppelklick auf IGC; Vorschau auch für Video/Track; Sync mit Timeline/Pool) |
| FA-093 | Muss | Bereiche Medien, Timeline, Karte, Export. | teilweise (Medien, Timeline, Karte umgesetzt; Export Platzhalter bis Phase 8) |
| FA-094 | Muss | Lange Aufgaben laufen über `QThreadPool`/`QRunnable`; die GUI bleibt bedienbar. | umgesetzt (Import) |
| FA-095 | Muss | Eine defekte Datei bricht den Import nicht ab; Fehler sind geloggt, in der DB und in der UI sichtbar. | umgesetzt |

### 4.10 Galerie, Register, Inspektor

| ID | Prio | Anforderung | Stand |
| --- | --- | --- | --- |
| FA-100 | Muss | Performante Übersicht über gecachte Thumbnails, nicht über Originale. HEIC-Vorschauen über Windows-Shell/WIC oder eingebettetes JPEG. | umgesetzt (Fotos, RAW, Video, GPX/IGC/KML/GeoJSON; Texte ohne Thumbnail; große JPEGs per Decoder-Draft statt Skip) |
| FA-101 | Soll | Filter: Datum, Ort, Typ, Bewertung, Dubletten, Qualität, Favoriten, im Tagebuch verwendet / nicht verwendet. | teilweise (Dateiname, Jahr, mit/ohne Ort, JPEG/HEIC/PNG/RAW/Video/Tracks, Register Alle/Favoriten/Reserve/Aussortiert, nicht im Tagebuch; Knopf **Filtern** mit Mehrfachauswahl Qualität/Bewertung und Zeitraum Von–Bis; Stapel/Gruppe, Statistik, Ampel; unechte Dubletten später) |
| FA-102 | Muss | Doppelklick auf ein Vorschaubild öffnet den **Medieninspektor**: eigenes nicht-modales Fenster mit Original bzw. bester Vorschau (EXIF-Orientierung plus Anzeigedrehung). Bewertungs-Chips für Fotos **und Tracks**; Klick speichert und springt zum nächsten Eintrag (letzter bleibt). **In den Pool** legt das Medium in den Pool und springt zum nächsten Foto (letztes bleibt); **Zurückholen** bleibt auf dem aktuellen. Blättern durch die Bilder des Tags/Abschnitts (Pfeiltasten links/rechts, Klick in den linken/rechten Rand, weiße Hover-Pfeile); Links/rechts durch Einzelbilder und alle Schlüsselfotos einer Gruppe; in einer Gruppe zusätzlich hoch/runter bzw. ▲▼ durch die Mitglieder zur Schlüsselfoto-Wahl; am Original das Gruppen-/Stapel-Kennzeichen oben rechts, groß und mit dunkler Platte; die Leertaste betätigt **Schlüsselfoto**. Checkbox **Aussortierte anzeigen** (in `config.json` als `inspector_show_rejected`, Standard aus) blendet Aussortierte beim Blättern ein. Mausrad zoomt; Doppelklick in die Bildmitte setzt auf fensterfüllend (Einpassen). Ecke unten rechts: proportionales Vergrößern; Fensterränder: frei breiter/höher. Die Fenstergröße (und Maximieren) bleibt in `config.json` (`inspector_width`, `inspector_height`, `inspector_maximized`). Vollbild/Maximieren passt das Foto ein (schwarze Ränder). Drehen 90° (↺/↻, Tasten L/R oder `[`/`]`) speichert `rotation_degrees` sofort, Originale unverändert. Ein zweites Panel (`extra_host`) bleibt für spätere Dublettenarbeit reserviert. Auf der **Karte** öffnet ein Klick auf ein Foto zuerst das Thumbnail-Popup; Doppelklick dort startet denselben Inspektor. Mehrere Inspektor-Fenster können gleichzeitig offen sein (versetzt). **Zur Karte** (nur mit Kartenposition, nicht geparkt) wechselt zur Kartenseite, öffnet das Detail des Abschnitts, zeigt das Medium und zentriert die zugehörige Leistenkarte; der letzte Klick gewinnt. Ist die Karte schon geladen, ohne HTML-Neuaufbau. | umgesetzt |
| FA-103 | Muss | In der Timeline liegen **Medien** (Fotos, Videos) und **Tracks** (GPX/IGC/KML/GeoJSON) in getrennten Galerien. Die Abschnitt-Auswahl umfasst beide. GPS-Dateien gehören nicht zu den Foto-Häkchen. | umgesetzt |
| FA-104 | Soll | Track-Vorschauen zeigen die Spur rot auf einem OSM-/Leaflet-Kartenausschnitt (`cache/map_tiles`). `map_provider=offline` lädt keine Kacheln (schwarzer Hintergrund, rote Spur). Fehlgeschlagene Abrufe ebenso. | umgesetzt |
| FA-105 | Soll | Globales Register **Alle / Favoriten / Reserve / Aussortiert** in der Timeline (neben „Neuen Reiseabschnitt erstellen“) und auf der Medienseite. Gilt für Medien- **und** Track-Galerien aller Timeline-Karten sowie die Galerie der Medienseite; bleibt in `config.json` als `timeline_media_tab` (auch beim Verlassen der Seite). Karten-Register bleiben synchron. Reiter wechseln **nur per Klick**, nicht durch Mausrad oder Mouseover beim Scrollen. Ein Thumbnail-Schieber (50–200 %) skaliert in der Timeline die Galerien, auf der Medienseite Galerie und Pool, auf Import die rechte Dateivorschau und auf der Karte nur die große Popup-Vorschau (`map_thumb_zoom` / `timeline_thumb_zoom` / `media_thumb_zoom` / `import_thumb_zoom` in `config.json`). Die Medienseite zeigt unten projektweit Importiert, Galerie, Aussortiert, Pool, Dubletten, Gruppen und Deaktiviert. | umgesetzt |

### 4.11 Persistenz und Projekt

| ID | Prio | Anforderung | Stand |
| --- | --- | --- | --- |
| FA-110 | Muss | SQLite + SQLAlchemy 2 + Alembic-Migrationen. | umgesetzt |
| FA-111 | Muss | Tabellen u. a. für Projekte, Quelldateien, Fotos, Videos, Tracks, Punkte, Reise, Tage, Orte, Ereignisse, Texte, Analysen, Ähnlichkeitsgruppen, Exportkonfiguration. | teilweise (Schema inkl. `trip_sections`, `section_members` mit `journal_at`, `source_files.parked` und `rotation_degrees`, URL- und Cover-Spalten, `photos.sort_status`, `transfer_links`, `outbound_*`; Alembic 001–018; `similarity_groups` mit `cluster_type`/`status`/`origin` und Mitglied `is_key` in Nutzung; Analysen/Exportzeilen ungenutzt bis Phase 8–9) |
| FA-112 | Muss | Projektordner mit `project.sqlite`, `settings.toml`, `thumbnails/`, `cache/`, `exports/`, `logs/`. | umgesetzt |
| FA-113 | Muss | Projekt schließen und wieder öffnen erhält Index und Einstellungen. | umgesetzt |
| FA-114 | Muss | Cache: Thumbnails, Metadaten, Analysen, Hashes; keine Vollanalyse unveränderter Dateien. | teilweise (Hash/mtime/Thumbnails/`cache/map_tiles`; Analysen Phase 9) |

### 4.12 Export

| ID | Prio | Anforderung | Stand |
| --- | --- | --- | --- |
| FA-120 | Muss | Gemeinsame Schnittstelle `Exporter`. | umgesetzt (Vertrag) |
| FA-121 | Muss | HTML-Export als erstes vollständiges Format: Titel, Zeitraum, Tage, Texte, Fotos, Bildunterschriften, Abschnitte; Templates HTML/CSS getrennt (Jinja2). | geplant (Phase 8) |
| FA-122 | Soll | PDF über austauschbares Backend (HTML→Druckengine oder LaTeX→PDF); **kein** PyMuPDF als Zwangsabhängigkeit. | geplant |
| FA-123 | Soll | LaTeX: kompilierbares `main.tex`, Kapitel, Bilderverzeichnis; PDF-Lauf optional. | geplant |
| FA-124 | Kann | CEWE nur als Platzhalter, bis das Zielformat geprüft ist. | teilweise (Platzhalter) |

### 4.13 PhotoInspector

| ID | Prio | Anforderung | Stand |
| --- | --- | --- | --- |
| FA-130 | Soll | Separate Windows-App für Dubletten, Ähnlichkeit, Unschärfe, Belichtung, Qualität, Auswahl. | geplant |
| FA-131 | Muss | Bildanalyse, Metadaten, Hashing, Similarity, Thumbnails, Qualität enthalten **kein** PySide6. | umgesetzt (Architekturregel) |

### 4.14 Verteilung (Windows)

Die Fachlogik unter `apps/` und `packages/` bleibt davon unberührt. Build-Skripte liegen unter `packaging/`.

| ID | Prio | Anforderung | Stand |
| --- | --- | --- | --- |
| FA-140 | Muss | Endnutzer starten Reisetagebuch unter Windows **ohne** eigene Python-Installation (gebündelte EXE). | umgesetzt (PyInstaller-onedir `dist/Reisetagebuch/`, Zip `dist/Reisetagebuch-{Version}-windows.zip`) |
| FA-141 | Soll | Ein optionales Setup (Inno Setup 6) installiert pro Benutzer nach `%LOCALAPPDATA%\Programs\Reisetagebuch`, legt einen Startmenüeintrag an und optional eine Desktop-Verknüpfung. Kein Administratorrecht. | teilweise (Skript `packaging/installer.iss`; Setup-EXE nur, wenn Inno Setup auf dem Build-Rechner installiert ist) |
| FA-142 | Kann | Authenticode-Signatur der EXE, damit SmartScreen die Weitergabe nicht blockiert. | geplant |
| FA-143 | Muss | ExifTool, HEIF Image Extensions und FFmpeg/ffprobe bleiben **optional** und sind **nicht** Bestandteil des Installationspakets. | umgesetzt (wie in der Entwicklungsumgebung) |
| FA-144 | Muss | Das Paket enthält LICENSE und einen LGPL-Hinweis zu PySide6/Qt (`NOTICE.txt`). | umgesetzt |

macOS ist **kein** Lieferziel: HEIC-/Video-Vorschauen nutzen die Windows-Shell/WIC, App-Einstellungen liegen unter `%LOCALAPPDATA%\TravelJournal`.

---

## 5. Nichtfunktionale Anforderungen

| ID | Prio | Anforderung | Stand |
| --- | --- | --- | --- |
| NFA-010 | Muss | Standardbetrieb lokal; keine automatische Übertragung von Fotos, GPS oder Reisedaten. | umgesetzt (OSM-Kacheln, optionale OpenTopoMap-, Esri-Satelliten- und Carto-Beschriftungskacheln und YouTube-Vorschaubilder sind Abrufe fremder Kacheln/Bilder, kein Upload der Reise) |
| NFA-011 | Muss | Spätere Cloud-/KI-Dienste nur nach ausdrücklicher Aktivierung. | umgesetzt (keine solchen Dienste) |
| NFA-020 | Muss | Python Type Hints, kleine Einheiten, Dependency Injection, keine Geschäftslogik in Widgets. | umgesetzt (Leitlinie) |
| NFA-021 | Muss | Öffentliche APIs mit Docstrings; eigene Exceptions; kein globaler App-Zustand in `travelcore`. | umgesetzt |
| NFA-022 | Muss | Ruff für Lint und Format; pyright/mypy vorgesehen. | teilweise (Ruff aktiv) |
| NFA-030 | Muss | Bevorzugte Lizenzen: MIT, BSD, Apache-2.0, LGPL bei Einhaltung der Bedingungen. | umgesetzt, siehe dependencies.md |
| NFA-031 | Muss | Jede direkte Abhängigkeit ist mit Version, Lizenz und Zweck dokumentiert. | umgesetzt |
| NFA-040 | Muss | Logging über das Standardmodul `logging`; Importfehler zusätzlich in `file_errors`. | umgesetzt |
| NFA-050 | Muss | `.gitignore` schließt Originale, DBs, Thumbnails, Cache, Exporte, Logs, venv, `dist/` und `build/` aus. Keine persönlichen GPS-Testdaten im Repo. | umgesetzt |
| NFA-060 | Soll | Import von mehreren tausend Dateien bleibt in der UI nachvollziehbar (Fortschritt, Abbruch später). | teilweise (Fortschritt ja) |
| NFA-070 | Muss | Windows-Paketierung ändert die Anwendung unter `apps/` und `packages/` nicht. Frozen-Einstieg ist `packaging/entry.py` (`multiprocessing.freeze_support` für den ProcessPool). | umgesetzt |
| NFA-071 | Soll | Das Frozen-Paket ist **onedir** (Ordner mit EXE), nicht eine einzelne Datei — zuverlässiger für Qt WebEngine und den ProcessPool. | umgesetzt |

---

## 6. Produktdaten (logisch)

Mindestens zu speichernde Informationen — Details im Datenbankschema:

- **Projekt:** Name, Zeitstempel, Quellwurzel, optionale Standardzeitzone; Datei `settings.toml` (Exportformat, Pfade, Kartenanbieter, Linienfarbe, Platzhalter)
- **Quelldatei:** technische und Aufnahme-Metadaten, Positionsherkunft, Anzeigedrehung (`rotation_degrees`), Pool-Flag (`parked`)
- **Datei-Fehler:** Pfad, Phase, Meldung
- **Foto / Video:** Favorit, Sortierstatus, Tagebuch-Nutzung (`used_in_journal`), Reise-Titelbild (`is_cover`), Herkunft auto/manual; die Abschnittszugehörigkeit folgt der Journal-Zeit der Mitgliedschaft, nicht dem Häkchen. Die Aufnahmezeit bleibt Original.
- **Track / Trackpunkt:** Geometrie und Zeit (GPX/IGC); IGC zusätzlich Pilot und optionaler DHV-Leonardo-Link
- **Reise / Kalendertag / Abschnitt / Abschnittmitglied / Ort / Ereignis / Notiz**
- **Abschnittmitglied:** Journal-Zeit (`journal_at`), optionale Anzeigeposition
- **Tag und Abschnitt:** YouTube-URLs, DHV-Leonardo-URLs, Eintrags-Titelbild (`cover_source_file_id`); Tag/Aufenthalt optional Ausgangslinie (`outbound_geometry`, `outbound_dash`, `outbound_symbol`)
- **Transfer-Verbindungslinie:** geordnete Kindzeile (`transfer_links`: Geometrie, Strich, Symbol, optionales Gelenk, optionaler GPX-Member)
- **Fotoanalyse / Ähnlichkeitsgruppe / Exportkonfiguration**

---

## 7. Benutzeroberfläche — Muss-Inhalte je Bereich

| Bereich | R3.0.0 (Phase 7 plus Medien-Pipeline) | Erste vollständige Version |
| --- | --- | --- |
| Projekt | Name, Ordnerpfad, Anlegen, Öffnen, Speichern, Einstellungen (`settings.toml`, Dialog mit Schieber); Fenstertitel mit Version R3.0.0 | plus zuletzt verwendete Projekte in der UI |
| Import | Pfadwahl, Analyse, Synchronisieren (fehlende entfernen, neue in Timeline oder Pool), Fortschritt, Zähler, vollständige Dateitabelle, Vorschau aller Galerie-Typen außer Text, Thumbnail-Schieber | unverändert |
| Medien | Galerie links, Medienpool rechts (ein-/ausklappbar), Register Alle/Favoriten/Reserve/Aussortiert je Bereich, Filter (Jahr/Ort/Typ inkl. Video/Tracks/nicht im Tagebuch), **Filtern** (Qualität, Zeitraum, Bewertung), Bewertungen, Inspektor, Drag in den Pool und zurück, **Dubletten stapeln** / **Ähnliche gruppieren** / **Auswahl gruppieren**, Kennzeichen G/×n, **Qualität prüfen** (Ampel), Statistikleiste | plus unechte Dubletten (pHash) |
| Timeline | Reisetitel oben, Tage/Transfers/Aufenthalte als Abschnitte mit Mitgliedern, Typ je Karte, Titel/Text, Mehrfachauswahl, Anlegen/Auflösen/Löschen (Löschen → Pool), schlanke Verbindung mit **+**, Drag & Drop Karte↔Karte und Pool (Auto-Scroll am Rand), Journal-Zeit/Originalzeit, Medien vs. Tracks, Register nur per Klick (auch für Tracks), Bewertungen für Fotos und Tracks, Thumbnail-Schieber, T-Titelbild (Foto und Track), Transfer-Verbindungslinien (Liste, Symbol vor dem Namen) und Ausgangslinie an Tag/Aufenthalt, ⋯-Menü YouTube/DHV-Leonardo, Hilfe Verkehrsmittelsymbole, **Speichern** nur bei ungespeicherten Abschnitten/Texten/Reisetitel/YouTube, Medieninspektor (Blättern, Zoom, Drehen, Pool, Track-Bewertung) | plus verdichtete Timeline-Karten auf der Timeline-Seite, Ereignis-Reihenfolge |
| Karte | Runde Titelbild-Kreise (Cover-Fallback: Foto, Track, YouTube), Verbindungslinien zwischen Tag- und Aufenthaltskreisen (Transfer-Liste oder Ausgangslinie, Verkehrssymbol in Fahrtrichtung bzw. Richtungspfeil, ausgeblendet bei überdeckenden Kreisen), Transfer-Kreis per dünner Linie am Verkehrssymbol, Layer-Menü Straßenkarte/Topo/Satellit, Zahnrad (Fotokegel, Reserve, Ortsnamen und Straßen auf Satellit), Fit-Reise zwischen Zoom und Zahnrad, Leiste darunter mit **+** zwischen den Karten, Tagebuchtext rechts, YouTube-Thumbs unten rechts auf der Karte, Einfachklick Leistenkarte → Übersicht ohne Zoomänderung / andere Karte im Detail schließt und zoomt auf den Abschnitt, Doppelklick → Timeline, Cover-Klick → ZoomToCover (Überlappung zuerst einpassen) bzw. Detail, Foto-Popup mit Blättern/Bewertung/Schieber-Zoom dann Inspektor, **Zur Karte** aus Inspektor/Thumbnail (letzter Klick: Detail, Foto, Leistenkarte; geladene Karte ohne Neuaufbau), Platzieren/Verschieben hält Zoom, offline ohne OSM | unverändert |
| Export | Platzhalter | HTML, PDF, LaTeX, CEWE (CEWE zunächst inaktiv) |

---

## 8. MVP — Abnahmekriterien der minimalen lauffähigen Version

Das MVP ist erfüllt, wenn alle folgenden Punkte demonstrabel sind:

1. Die PySide6-Anwendung startet unter Windows.
2. Ein Projektordner kann erzeugt werden.
3. Ein Quellverzeichnis kann gewählt werden.
4. JPG/JPEG werden rekursiv gefunden.
5. EXIF-Aufnahmezeit wird gelesen.
6. EXIF-GPS wird gelesen, sofern vorhanden.
7. GPX-Dateien werden erkannt und eingelesen.
8. Bilder ohne GPS: zuerst zeitnahes Foto mit GPS, sonst GPX, sonst IGC.
9. Die Importliste wird aktualisiert; anschließend werden Thumbnails erzeugt.
10. Fotos erscheinen chronologisch in einer Galerie.
11. Fotos mit GPS erscheinen auf einer Karte.
12. Eine einfache Tages-Timeline entsteht automatisch.
13. Der Benutzer kann Fotos einem Tag zuordnen oder entfernen.
14. Pro Tag kann ein Text eingegeben werden.
15. Das Projekt liegt in SQLite.
16. Das Projekt kann geschlossen und wieder geöffnet werden.
17. Ein einfacher HTML-Reisebericht kann exportiert werden.

**Aktueller Abnahmestand (Phase 7 plus Medien-Pipeline, Software R3.0.0):** Punkte 1–16 plus Journal-Modell nach Design-Review (Tag/Aufenthalt/Transfer als Abschnitte, Medienpool, Journal-Zeit), Bewertungen für Fotos und Tracks, Eintrags-Titelbild (Foto, Track, YouTube-Fallback), Medieninspektor mit Blättern/Zoom/Drehen, Schlüsselfotos und **Zur Karte** (letzter Klick: Detail, Foto, Leistenkarte; geladene Karte ohne Neuaufbau), Track-Vorschauen, Karten-Leiste und Kreis-Detail, Cover-Zoom und Fit-Reise, Foto-Popup mit Vorab-Zentrierung und Blättern, Verbindungslinien (Transfer-Liste und Ausgangslinie) mit Verkehrssymbolen, Drag & Drop mit Auto-Scroll, SHA-256-Stapel, Szenen- und manuelle Gruppen, Qualitätsampel, Statistikleiste Medien, Fenstertitel mit Version. Windows-Endnutzerpaket (onedir/Zip) ist baubar (FA-140); die Setup-EXE braucht Inno Setup 6 auf dem Build-Rechner (FA-141). Punkt 17 folgt in Phase 8.

---

## 9. Lieferphasen

Nach jeder Phase: Anwendung startbar, bestehende Tests grün, keine ungenutzten Platzhalter-Abhängigkeiten.

| Phase | Inhalt | Status |
| --- | --- | --- |
| 1 | Projektstruktur und travelcore | erledigt |
| 2 | Dateiimport und SQLite | erledigt |
| 3 | Metadaten (inkl. HEIC ohne ExifTool) | erledigt |
| 4 | GPX und GPS-Zuordnung | erledigt |
| 5 | Thumbnail-Galerie | erledigt |
| 6 | Karte | erledigt |
| 7 | Timeline und manuelle Bearbeitung: Tag/Aufenthalt/Transfer als Abschnitte, Medienpool, Journal-Zeit, Bewertungen, Inspektor, Track-Vorschauen, Karten-Leiste, Verbindungslinien und Verkehrssymbole, Design-Review-UI, Rückgängig/Wiederherstellen | erledigt (HTML-Export nicht enthalten) |
| 8 | HTML-Export | offen |
| 9 | Qualitätsanalyse | erledigt (Ampel; Ranking-Gewichte FA-073 weiter Schnittstelle) |
| 10 | Dublettenerkennung | teilweise (R3.0.0: SHA-256-Stapel, 30-s-Szenengruppen, manuelle Gruppen, Statistik; keine pHash/Embeddings) |

Windows-Paketierung (`packaging/`) ist **keine eigene Fachphase**. Sie liefert die aktuelle Software (R3.0.0) als EXE/Zip (und optional Setup) an Endnutzer, ohne die Phasenfolge zu ändern. Build-Anleitung: [packaging/README.md](../packaging/README.md).

---

## 10. Offene Punkte

| ID | Thema | Klärung |
| --- | --- | --- |
| OP-01 | Reverse-Geocoding | Nur offline (z. B. lokale DB) oder opt-in Online? |
| OP-02 | CEWE-Zielformat | Technische und lizenzrechtliche Prüfung vor Implementierung |
| OP-03 | PDF-Renderer | HTML-Druckengine vs. externer LaTeX-Lauf |
| OP-04 | PhotoInspector | Eigener Zeitplan nach Phase 10 |
| OP-05 | Abbruch laufender Imports | Noch nicht spezifiziert als UI-Muss |
| OP-06 | Zuletzt verwendete Projekte | `recent.json` existiert; UI-Liste offen |
| OP-07 | Foto einem anderen Tag zuordnen | umgesetzt (R2): Journal-Zeit und Drag & Drop; `captured_at` bleibt Original |
| OP-08 | KML/GeoJSON-Ingest | Parser und Thumbnails da; Zuordnung und Kartenlinie bewusst nicht |
| OP-09 | Reiseabschnitte auf der Karte | umgesetzt (Kreis-Übersicht, Detail per Klick, Leiste unter der Karte) |
| OP-10 | Kompakte Timeline-Karten | auf der **Karten**-Seite umgesetzt (Leiste); verdichtete Karten in der Timeline-Seite später |
| OP-11 | Eigene Tagebuch-Seite | entfällt; Titel, Text und Abschnitte liegen in der Timeline |
| OP-12 | Code-Signatur | FA-142; ohne Signatur kann SmartScreen die EXE beim ersten Start blockieren |
| OP-13 | Inno Setup auf CI/Build-Rechner | Setup-EXE entsteht nur, wenn ISCC.exe verfügbar ist; Zip reicht als portable Lieferung |
