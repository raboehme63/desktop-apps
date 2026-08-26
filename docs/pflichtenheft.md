# Pflichtenheft — Reisetagebuch

| Feld | Inhalt |
| --- | --- |
| Produkt | Reisetagebuch (Windows-Desktop) |
| Version | 1.0 (Software **R1.0.0**) |
| Stand | 26. August 2026 |
| Status | verbindlich für die Umsetzung; Phase 7 erweitert, Software R1.0.0 |
| Bezug | Auftraggeber-Prompt „Reise-Tagebuch-Anwendung für Windows“ |
| Begleitdokumente | [konzept.md](konzept.md), [architecture.md](architecture.md), [testdokumentation.md](testdokumentation.md), [dependencies.md](dependencies.md) |

Dieses Pflichtenheft beschreibt **was** das System leisten muss. Das **wie** steht im Konzept und in der Architektur.

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

Punkt 5 ist für **manuelle Reiseabschnitte** (Aufenthalt / Transfer) in der Timeline umgesetzt. Automatische Abschnittsvorschläge und Abschnitte auf der Karte fehlen noch. Punkte 8 und 10 bleiben Phase 9–10 bzw. 8.

### 1.2 Wunschkriterien

- Automatische Erkennung von Übernachtungsorten
- Ortsnamen-Auflösung (Reverse-Geocoding) — nur lokal oder nach ausdrücklicher Freigabe
- KI-Embeddings (z. B. CLIP) für Ähnlichkeit
- Videoinhaltsanalyse über reine Metadaten und Vorschaubilder hinaus
- Interaktive Karte mit Marker-Clustern und Fotovorschau
- Kompakte Timeline-Karten (Titelbild + Titel + Zeitraum)

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
| Plattform | Windows 10/11 |
| Laufzeit | Python 3.12, lokale Installation |
| Netz | nicht erforderlich; Standardbetrieb speichert alles lokal. OSM-Kacheln (Karte und Track-Vorschauen) und YouTube-Vorschaubilder werden nur geladen, wenn der jeweilige Anbieter aktiv ist bzw. Links angezeigt werden. Es gibt keinen Upload von Fotos, GPS oder Reisedaten. |
| Hardware | handelsüblicher PC; Import großer Fotoarchive darf die GUI nicht blockieren |
| Rechte | Lesezugriff auf das Quellverzeichnis; Schreibzugriff nur auf den Projektordner und `%LOCALAPPDATA%\TravelJournal` |

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

Oberflächen-Einstellungen (zuletzt verwendeter Projekte-Ordner, Timeline-Medienregister) liegen unter `%LOCALAPPDATA%\TravelJournal\config.json`. Zuletzt geöffnete Projekte stehen in `recent.json` (max. 10); die Oberfläche listet sie noch nicht.

---

## 4. Funktionale Anforderungen

### 4.1 Quellverzeichnis und Dateitypen

| ID | Prio | Anforderung | Stand |
| --- | --- | --- | --- |
| FA-010 | Muss | Der Benutzer wählt ein Quellverzeichnis. Der Scan ist rekursiv. | umgesetzt |
| FA-011 | Muss | Fotos: JPG, JPEG, PNG, WebP, TIFF, HEIC/HEIF sofern technisch möglich; RAW zunächst nur Metadaten/Vorschau. | teilweise (Index ja; RAW-Metadaten nur mit ExifTool; RAW-Vorschau über Windows-Shell/WIC oder eingebettetes JPEG, sonst Typ-Platzhalter) |
| FA-012 | Muss | Videos: MP4, MOV, AVI, MKV. Erste Version: Metadaten und Vorschaubilder, keine Inhaltsanalyse. | teilweise (Index ja; Vorschaubild über Windows-Shell/WIC oder eingebettetes JPEG in den ersten 8 MB, sonst Platzhalter; Video-Metadaten über ffprobe geplant) |
| FA-013 | Muss | GPS: GPX vollständig in der ersten Version; IGC (Gleitschirm-Fluglogs) mit Pilot und DHV-Leonardo-Link; KML und GeoJSON erkannt. | teilweise (GPX und IGC vollständig ingestiert und auf der Karte; KML/GeoJSON indexiert und für Track-Vorschauen geparst, **nicht** in `gps_tracks` übernommen und **nicht** für Foto-Zuordnung genutzt) |
| FA-014 | Soll | Texte: TXT, Markdown; optional JSON mit Reiseinformationen. | teilweise (Index ja; TXT/MD füllen Titel und Tagesetext, sofern der Tag noch nicht manuell ist; JSON-Auswertung geplant) |
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
| FA-041 | Muss | Fotos ohne GPS: zuerst zeitnahe Fotos mit GPS, sonst GPX, sonst IGC; Interpolation zwischen benachbarten Punkten. | umgesetzt |
| FA-042 | Muss | Abgeleitete Position speichert Quelle, Vertrauenswert, Zeitdifferenz und ob EXIF oder Track. | umgesetzt |
| FA-043 | Soll | KML (LineString / gx:Track) und GeoJSON (LineString) werden für Track-Vorschauen geparst. Sie fließen nicht in die GPS-Zuordnung und nicht in die interaktive Karte. | umgesetzt (Parser + Thumbnail; kein Ingest) |

### 4.5 Karte

| ID | Prio | Anforderung | Stand |
| --- | --- | --- | --- |
| FA-050 | Muss | Interaktive Karte: Track als Linie, Fotos als Marker, Übernachtungen, Abschnitte, Tagesgruppen. | teilweise (Track, IGC-Flugtracks ab Zoom 10 mit Start/Landung, Fotos/Videos, Orte, Übernachtungen, Cluster je Tag; **keine Reiseabschnitte**) |
| FA-051 | Soll | Klick auf Fotomarker zeigt Vorschau; nahe Marker können clustern. | umgesetzt |
| FA-052 | Muss | Kartenbackend hinter `MapBackend` austauschbar; erste Version Folium/Leaflet. | umgesetzt |

### 4.6 Timeline, Orte, Übernachtungen

| ID | Prio | Anforderung | Stand |
| --- | --- | --- | --- |
| FA-060 | Muss | Automatische chronologische Timeline (Tag → Ereignisse). | umgesetzt |
| FA-061 | Muss | Ebenen: Reise, Reisetag, Abschnitt, Ort/Aufenthalt, Ereignis, Medienobjekt, Textnotiz. | teilweise (Reise/Tag/Abschnitt/Ort/Ereignis/Medien/Text; Abschnitte manuell in der Timeline; das Tagebuch bleibt tageszentriert) |
| FA-062 | Soll | Aufenthalte aus GPS: konfigurierbarer Radius und Mindestdauer; nur als Vorschlag. | teilweise (Funktion vorhanden, Import erzeugt keine Ortsnamen an Foto-/Video-/Trackpositionen; Datum reicht) |
| FA-063 | Muss | Benutzer bestätigt, ändert oder löscht vorgeschlagene Orte. | umgesetzt |
| FA-064 | Muss | Übernachtungen manuell markierbar (Datum, Ort, GPS, Name, Beschreibung, Fotos). | teilweise (Datum, Ort, GPS, Name, Beschreibung; Fotos an der Übernachtung später) |

### 4.6a Reiseabschnitte, Links, Resttage

| ID | Prio | Anforderung | Stand |
| --- | --- | --- | --- |
| FA-065 | Muss | Der Benutzer erzeugt Reiseabschnitte aus einer Mehrfachauswahl: **Aufenthalt** (`stay`) oder **Transfer** (`movement`). Transfer darf mehrere Verkehrsmittel haben (Bus, Bahn, Flug, zu Fuß, Auto, Rad, Boot, sonstiges). Die Zeitspanne folgt den Objekten (`am …` bzw. `von … bis …`). | umgesetzt |
| FA-066 | Muss | Medien, die keinem Abschnitt gehören, bleiben als **Resttage** sichtbar. Timeline mischt Abschnitte und Resttage chronologisch. Auflösen (⊟) gibt die Dateien an die Resttage zurück. | umgesetzt |
| FA-067 | Muss | Neu angelegte Abschnitte existieren nur im Speicher (`PendingSectionSpec`, negative `local_id`), bis **Speichern**. Verlassen der Timeline ohne Speichern fragt nach. Overlay `apply_pending_sections` ist Vorschau, kein Schreiben. | umgesetzt |
| FA-068 | Muss | YouTube-Links gehören zu Tag oder Abschnitt. Sie werden **nur** mit Timeline-**Speichern** (bzw. Speichern im Tagebuch) persistiert, nie still beim Dialog-OK. Nur YouTube-Hosts; Duplikate entfallen. | umgesetzt |
| FA-069 | Muss | DHV-Leonardo-Links: am IGC-Track sofort speicherbar (Import-Doppelklick und Timeline-Menü). Zusätzliche Links an gespeichertem Tag/Abschnitt ebenfalls sofort beim Dialog-OK; an ungespeicherten Abschnitten erst mit Timeline-Speichern. Nie als „DAV“ bezeichnen. | umgesetzt |

Auswahlmodell in der Timeline: erster und letzter Klick füllen den Bereich dazwischen; Strg+Klick entfernt Löcher. Das Menü **⋯** (YouTube, DHV-Leonardo) gilt auch für noch nicht gespeicherte Abschnitte (`entity_id != 0`).

### 4.7 Fotoqualität, Dubletten, Ranking

| ID | Prio | Anforderung | Stand |
| --- | --- | --- | --- |
| FA-070 | Soll | Technische Qualität: Auflösung, Seitenverhältnis, Helligkeit, Kontrast, Schärfe, Über-/Unterbelichtung. Nur Empfehlung, nie automatisches Löschen. | geplant (Phase 9) |
| FA-071 | Soll | Komponente `photo_similarity`: exakte Dubletten (SHA-256), visuelle Ähnlichkeit (dHash/pHash); später Embeddings. | geplant (Phase 10) |
| FA-072 | Muss | Kein automatisches Löschen von Originalfotos. | umgesetzt (kein Löschpfad) |
| FA-073 | Soll | Ranking je Ereignis/Ort über austauschbare `RankingStrategy`. | teilweise (Schnittstelle) |

### 4.8 Manuelle Bearbeitung

| ID | Prio | Anforderung | Stand |
| --- | --- | --- | --- |
| FA-080 | Muss | Tagebuch vollständig bearbeitbar: Tage, Orte, GPS, Ereignisse, Texte, Fotos, Reihenfolge, Übernachtungen, Titelbilder, Abschnitte. | teilweise (Tage, Titel/Text, Fotos zu/ab über `used_in_journal`, Orte bestätigen/löschen, Übernachtungen, Reise-Titelbild `is_cover`, Abschnitte in der Timeline; kein Umsortieren von Fotos auf andere Tage, keine Ereignis-Reihenfolge, keine Abschnitte im Tagebuch) |
| FA-081 | Muss | Automatisch erzeugte und manuelle Daten sind unterscheidbar (`origin=auto\|manual`). | umgesetzt |
| FA-082 | Muss | Jedes Foto trägt einen Sortierstatus `favorite` / `reserve` / `rejected` (oder leer). `is_favorite` bleibt synchron. Leerer Status plus altes Favoriten-Flag gilt als Favorit (`effective_sort_status`). Klick auf den aktiven Status hebt ihn auf. Abgelehnte Vorschaubilder sind abgedunkelt. Speichern sofort. | umgesetzt |
| FA-083 | Muss | Zwei Titelbilder: (1) **Reise-Titelbild** `Photo.is_cover` im Tagebuch („Als Titelbild“); (2) **Eintrags-Titelbild** `cover_source_file_id` an Tag oder Abschnitt, Chip **T** auf Foto- **und Track**-Thumbs, 72-px-Vorschau in der Timeline-Kartenüberschrift. Videos sind keine Titelbilder. An gespeicherten Einträgen sofort; an ungespeicherten Abschnitten erst mit Speichern. | umgesetzt |

### 4.9 Benutzeroberfläche

| ID | Prio | Anforderung | Stand |
| --- | --- | --- | --- |
| FA-090 | Muss | Moderne Windows-UI mit PySide6, Navigation links. Fenstertitel: `Reisetagebuch R{Version}` bzw. `Reisetagebuch R{Version} - {Projekttitel}`. | umgesetzt (Rahmen; Version **R1.0.0**) |
| FA-091 | Muss | Bereich Projekt: neu, öffnen, speichern; Menü **Projekt → Einstellungen**. | teilweise (neu/öffnen/speichern/Einstellungen; zuletzt verwendete Projekte intern in `recent.json`, noch ohne UI-Liste; Projekte-Stammordner in `config.json`) |
| FA-092 | Muss | Bereich Import: Ordner, Analyse, Fortschritt, Dateiliste mit Zeit/GPS/Kamera. Klick/Mouseover zeigt Vorschau und Metadaten. Die Liste wird während des Einlesens periodisch aktualisiert, erneut nach GPS-Abgleich, und vor den Vorschaubildern. | umgesetzt (Kamera/Pilot; DHV-Leonardo per Doppelklick auf IGC; Vorschau auch für Video/Track) |
| FA-093 | Muss | Bereiche Timeline, Karte, Fotos, Tagebuch, Export. | teilweise (Timeline, Karte, Fotos, Tagebuch umgesetzt; Export Platzhalter bis Phase 8) |
| FA-094 | Muss | Lange Aufgaben laufen über `QThreadPool`/`QRunnable`; die GUI bleibt bedienbar. | umgesetzt (Import) |
| FA-095 | Muss | Eine defekte Datei bricht den Import nicht ab; Fehler sind geloggt, in der DB und in der UI sichtbar. | umgesetzt |

### 4.10 Galerie, Register, Inspektor

| ID | Prio | Anforderung | Stand |
| --- | --- | --- | --- |
| FA-100 | Muss | Performante Übersicht über gecachte Thumbnails, nicht über Originale. HEIC-Vorschauen über Windows-Shell/WIC oder eingebettetes JPEG. | umgesetzt (Fotos, RAW, Video, GPX/IGC/KML/GeoJSON; Texte ohne Thumbnail) |
| FA-101 | Soll | Filter: Datum, Ort, Typ, Bewertung, Dubletten, Qualität, Favoriten, im Tagebuch verwendet / nicht verwendet. | teilweise (Dateiname, Jahr, mit/ohne Ort, JPEG/HEIC/PNG/RAW/Video/Tracks, Favoriten, nicht im Tagebuch; Qualität/Dubletten später) |
| FA-102 | Muss | Doppelklick auf ein Vorschaubild öffnet den **Medieninspektor**: eigenes nicht-modales Fenster mit Original bzw. bester Vorschau (EXIF-Orientierung plus Anzeigedrehung). Bewertungs-Chips; GPS-Tracks ohne Bewertung. Blättern durch die Bilder des Tags/Abschnitts (Pfeiltasten, Klick in den linken/rechten Rand, weiße Hover-Pfeile). Mausrad zoomt; Doppelklick in die Bildmitte setzt auf fensterfüllend (Einpassen). Ecke unten rechts: proportionales Vergrößern; Fensterränder: frei breiter/höher. Vollbild/Maximieren passt das Foto ein (schwarze Ränder). Drehen 90° (↺/↻, Tasten L/R oder `[`/`]`) speichert `rotation_degrees` sofort, Originale unverändert. Ein zweites Panel (`extra_host`) bleibt für spätere Dublettenarbeit reserviert. | umgesetzt |
| FA-103 | Muss | In Timeline und Tagebuch liegen **Medien** (Fotos, Videos) und **Tracks** (GPX/IGC/KML/GeoJSON) in getrennten Galerien. Die Abschnitt-Auswahl umfasst beide. GPS-Dateien gehören nicht zu den Foto-Häkchen und nicht zu „Alle ins Tagebuch“. | umgesetzt |
| FA-104 | Soll | Track-Vorschauen zeigen die Spur rot auf einem OSM-/Leaflet-Kartenausschnitt (`cache/map_tiles`). `map_provider=offline` lädt keine Kacheln (schwarzer Hintergrund, rote Spur). Fehlgeschlagene Abrufe ebenso. | umgesetzt |
| FA-105 | Soll | Globales Timeline-Register **Alle / Favoriten / Reserve / Aussortiert** neben „Neuen Reiseabschnitt erstellen“ gilt für alle Karten und bleibt in `config.json` als `timeline_media_tab` (auch beim Verlassen der Seite). Karten-Register bleiben synchron. Reiter wechseln **nur per Klick**, nicht durch Mausrad oder Mouseover beim Scrollen. | umgesetzt |

### 4.11 Persistenz und Projekt

| ID | Prio | Anforderung | Stand |
| --- | --- | --- | --- |
| FA-110 | Muss | SQLite + SQLAlchemy 2 + Alembic-Migrationen. | umgesetzt |
| FA-111 | Muss | Tabellen u. a. für Projekte, Quelldateien, Fotos, Videos, Tracks, Punkte, Reise, Tage, Orte, Ereignisse, Übernachtungen, Texte, Analysen, Ähnlichkeitsgruppen, Exportkonfiguration. | teilweise (Schema inkl. `trip_sections`, `section_members`, URL- und Cover-Spalten, `photos.sort_status`, `source_files.rotation_degrees`; Alembic 001–011; Analysen/Ähnlichkeit/Exportzeilen ungenutzt bis Phase 8–10) |
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

---

## 5. Nichtfunktionale Anforderungen

| ID | Prio | Anforderung | Stand |
| --- | --- | --- | --- |
| NFA-010 | Muss | Standardbetrieb lokal; keine automatische Übertragung von Fotos, GPS oder Reisedaten. | umgesetzt (OSM-Kacheln und YouTube-Vorschaubilder sind Abrufe fremder Kacheln/Bilder, kein Upload der Reise) |
| NFA-011 | Muss | Spätere Cloud-/KI-Dienste nur nach ausdrücklicher Aktivierung. | umgesetzt (keine solchen Dienste) |
| NFA-020 | Muss | Python Type Hints, kleine Einheiten, Dependency Injection, keine Geschäftslogik in Widgets. | umgesetzt (Leitlinie) |
| NFA-021 | Muss | Öffentliche APIs mit Docstrings; eigene Exceptions; kein globaler App-Zustand in `travelcore`. | umgesetzt |
| NFA-022 | Muss | Ruff für Lint und Format; pyright/mypy vorgesehen. | teilweise (Ruff aktiv) |
| NFA-030 | Muss | Bevorzugte Lizenzen: MIT, BSD, Apache-2.0, LGPL bei Einhaltung der Bedingungen. | umgesetzt, siehe dependencies.md |
| NFA-031 | Muss | Jede direkte Abhängigkeit ist mit Version, Lizenz und Zweck dokumentiert. | umgesetzt |
| NFA-040 | Muss | Logging über das Standardmodul `logging`; Importfehler zusätzlich in `file_errors`. | umgesetzt |
| NFA-050 | Muss | `.gitignore` schließt Originale, DBs, Thumbnails, Cache, Exporte, Logs, venv aus. Keine persönlichen GPS-Testdaten im Repo. | umgesetzt |
| NFA-060 | Soll | Import von mehreren tausend Dateien bleibt in der UI nachvollziehbar (Fortschritt, Abbruch später). | teilweise (Fortschritt ja) |

---

## 6. Produktdaten (logisch)

Mindestens zu speichernde Informationen — Details im Datenbankschema:

- **Projekt:** Name, Zeitstempel, Quellwurzel, optionale Standardzeitzone; Datei `settings.toml` (Exportformat, Pfade, Kartenanbieter, Platzhalter)
- **Quelldatei:** technische und Aufnahme-Metadaten, Positionsherkunft, Anzeigedrehung (`rotation_degrees`)
- **Datei-Fehler:** Pfad, Phase, Meldung
- **Foto / Video:** Favorit, Sortierstatus, Tagebuch-Nutzung (`used_in_journal`), Reise-Titelbild (`is_cover`), Herkunft auto/manual; die Tageszugehörigkeit folgt der Aufnahmezeit, nicht dem Häkchen
- **Track / Trackpunkt:** Geometrie und Zeit (GPX/IGC); IGC zusätzlich Pilot und optionaler DHV-Leonardo-Link
- **Reise / Tag / Abschnitt / Abschnittmitglied / Ort / Ereignis / Notiz / Übernachtung**
- **Tag und Abschnitt:** YouTube-URLs, DHV-Leonardo-URLs, Eintrags-Titelbild (`cover_source_file_id`)
- **Fotoanalyse / Ähnlichkeitsgruppe / Exportkonfiguration**

---

## 7. Benutzeroberfläche — Muss-Inhalte je Bereich

| Bereich | Phase 7 erweitert | Erste vollständige Version |
| --- | --- | --- |
| Projekt | Name, Ordnerpfad, Anlegen, Öffnen, Speichern, Einstellungen (`settings.toml`); Fenstertitel mit Version R1.0.0 | plus zuletzt verwendete Projekte in der UI |
| Import | Pfadwahl, Analyse, Fortschritt, Zähler, vollständige Dateitabelle, Vorschau aller Galerie-Typen außer Text | unverändert |
| Timeline | Resttage und Abschnitte gemischt, Mehrfachauswahl, Anlegen/Auflösen, Medien vs. Tracks, Register nur per Klick, Bewertungen, T-Titelbild (Foto und Track), ⋯-Menü YouTube/DHV-Leonardo, Medieninspektor (Blättern, Zoom, Drehen) | plus kompakte Karten, Ereignis-Reihenfolge |
| Karte | Track, Fotos/Videos, Orte, Übernachtungen, Cluster je Tag, offline ohne OSM | plus Reiseabschnitte |
| Fotos | Galerie, Filter (Jahr/Ort/Typ inkl. Video/Tracks/Favorit/nicht im Tagebuch), Bewertungen, Inspektor | plus Qualität, Dubletten |
| Tagebuch | Titel, Text, Fotos zu/ab, Reise-Titelbild, Übernachtungen, Tracks getrennt, YouTube/DHV-Leonardo | plus Abschnitte, Bildunterschriften |
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

**Aktueller Abnahmestand (Phase 7 erweitert, Software R1.0.0):** Punkte 1–16 plus manuelle Reiseabschnitte, Bewertungen, Eintrags-Titelbild (Foto und Track), Medieninspektor mit Blättern/Zoom/Drehen, Track-Vorschauen, Fenstertitel mit Version. Punkt 17 folgt in Phase 8.

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
| 7 | Timeline und manuelle Bearbeitung, erweitert um Abschnitte, Bewertungen, Inspektor (Blättern, Zoom, Drehen), Track-Vorschauen, Titelbild auch für Tracks | erledigt (HTML-Export nicht enthalten; Software R1.0.0) |
| 8 | HTML-Export | offen |
| 9 | Qualitätsanalyse | offen |
| 10 | Dublettenerkennung | offen |

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
| OP-07 | Foto einem anderen Tag zuordnen | Aufnahmezeit bleibt maßgeblich; explizite Korrektur nicht spezifiziert |
| OP-08 | KML/GeoJSON-Ingest | Parser und Thumbnails da; Zuordnung und Kartenlinie bewusst nicht |
| OP-09 | Reiseabschnitte auf der Karte | Timeline ja, Folium-Szene nein |
| OP-10 | Kompakte Timeline-Karten | Cover + Titel + Zeit als verdichtete Ansicht später |
| OP-11 | Abschnitte im Tagebuch | Redaktion der Abschnitte liegt in der Timeline |
