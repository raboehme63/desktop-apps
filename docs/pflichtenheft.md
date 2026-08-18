# Pflichtenheft — Reisetagebuch

| Feld | Inhalt |
| --- | --- |
| Produkt | Reisetagebuch (Windows-Desktop) |
| Version | 0.8 |
| Stand | 18. August 2026 |
| Status | verbindlich für die Umsetzung; Phase 7 fortgeschrieben |
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

### 1.2 Wunschkriterien

- Automatische Erkennung von Übernachtungsorten
- Ortsnamen-Auflösung (Reverse-Geocoding) — nur lokal oder nach ausdrücklicher Freigabe
- KI-Embeddings (z. B. CLIP) für Ähnlichkeit
- Videoinhaltsanalyse über reine Metadaten und Vorschaubilder hinaus
- Interaktive Karte mit Marker-Clustern und Fotovorschau

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
| Netz | nicht erforderlich; Standardbetrieb ist vollständig lokal |
| Hardware | handelsüblicher PC; Import großer Fotoarchive darf die GUI nicht blockieren |
| Rechte | Lesezugriff auf das Quellverzeichnis; Schreibzugriff nur auf den Projektordner |

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
    cache/
    exports/
    logs/
```

Die Datenbank speichert nur **Referenzen** auf Originaldateien. Originale werden nicht kopiert, sofern der Benutzer das nicht ausdrücklich wünscht.

---

## 4. Funktionale Anforderungen

### 4.1 Quellverzeichnis und Dateitypen

| ID | Prio | Anforderung | Stand |
| --- | --- | --- | --- |
| FA-010 | Muss | Der Benutzer wählt ein Quellverzeichnis. Der Scan ist rekursiv. | umgesetzt |
| FA-011 | Muss | Fotos: JPG, JPEG, PNG, WebP, TIFF, HEIC/HEIF sofern technisch möglich; RAW zunächst nur Metadaten/Vorschau. | teilweise (Index ja; RAW-Metadaten nur mit ExifTool) |
| FA-012 | Muss | Videos: MP4, MOV, AVI, MKV. Erste Version: Metadaten und Vorschaubilder, keine Inhaltsanalyse. | teilweise (Index ja; Video-Metadaten geplant) |
| FA-013 | Muss | GPS: GPX vollständig in der ersten Version; IGC (Gleitschirm-Fluglogs) mit Pilot und DHV-Leonardo-Link; KML und GeoJSON erkannt. | teilweise (GPX und IGC vollständig; KML/GeoJSON nur Index) |
| FA-014 | Soll | Texte: TXT, Markdown; optional JSON mit Reiseinformationen. | teilweise (Index ja; Auswertung geplant) |
| FA-015 | Muss | Versteckte Dateien und nicht unterstützte Typen werden übersprungen. | umgesetzt |
| FA-016 | Muss | Spätere Formate müssen über die Typklassifikation ergänzbar sein. | umgesetzt (Extension-Map) |

### 4.2 Dateiindex

| ID | Prio | Anforderung | Stand |
| --- | --- | --- | --- |
| FA-020 | Muss | Zentraler Dateiindex in SQLite je Projekt. | umgesetzt |
| FA-021 | Muss | Pro Datei: Pfad, Name, Typ, MIME, Größe, FS-Erstellung, FS-Änderung, SHA-256, Importzeit. | umgesetzt |
| FA-022 | Muss | Für Medien zusätzlich: Aufnahmezeit, Zeitzone, GPS, Kamera, Objektiv, Brennweite, ISO, Belichtung, Blende, Orientierung, Breite, Höhe. | umgesetzt (soweit in Metadaten vorhanden) |
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
| FA-035 | Muss | Kamera und Aufnahmeparameter werden gelesen, sofern vorhanden. | umgesetzt |
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

### 4.5 Karte

| ID | Prio | Anforderung | Stand |
| --- | --- | --- | --- |
| FA-050 | Muss | Interaktive Karte: Track als Linie, Fotos als Marker, Übernachtungen, Abschnitte, Tagesgruppen. | teilweise (Track, IGC-Flugtracks ab Zoom 10 mit Start/Landung, Fotos/Videos, Orte, Übernachtungen, Cluster je Tag; keine Reiseabschnitte) |
| FA-051 | Soll | Klick auf Fotomarker zeigt Vorschau; nahe Marker können clustern. | umgesetzt |
| FA-052 | Muss | Kartenbackend hinter `MapBackend` austauschbar; erste Version Folium/Leaflet. | umgesetzt |

### 4.6 Timeline, Orte, Übernachtungen

| ID | Prio | Anforderung | Stand |
| --- | --- | --- | --- |
| FA-060 | Muss | Automatische chronologische Timeline (Tag → Ereignisse). | umgesetzt |
| FA-061 | Muss | Ebenen: Reise, Reisetag, Abschnitt, Ort/Aufenthalt, Ereignis, Medienobjekt, Textnotiz. | teilweise (Reise/Tag/Ort/Ereignis/Medien/Text; Abschnitte später) |
| FA-062 | Soll | Aufenthalte aus GPS: konfigurierbarer Radius und Mindestdauer; nur als Vorschlag. | teilweise (Funktion vorhanden, Import erzeugt keine Ortsnamen an Foto-/Video-/Trackpositionen; Datum reicht) |
| FA-063 | Muss | Benutzer bestätigt, ändert oder löscht vorgeschlagene Orte. | umgesetzt |
| FA-064 | Muss | Übernachtungen manuell markierbar (Datum, Ort, GPS, Name, Beschreibung, Fotos). | teilweise (Datum, Ort, GPS, Name, Beschreibung; Fotos an der Übernachtung später) |

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
| FA-080 | Muss | Tagebuch vollständig bearbeitbar: Tage, Orte, GPS, Ereignisse, Texte, Fotos, Reihenfolge, Übernachtungen, Titelbilder, Abschnitte. | teilweise (Tage, Titel/Text, Fotos zu/ab über `used_in_journal`, Orte bestätigen/löschen, Übernachtungen, Titelbild; kein Umsortieren von Fotos auf andere Tage, keine Abschnitte, keine Ereignis-Reihenfolge) |
| FA-081 | Muss | Automatisch erzeugte und manuelle Daten sind unterscheidbar (`origin=auto\|manual`). | umgesetzt |

### 4.9 Benutzeroberfläche

| ID | Prio | Anforderung | Stand |
| --- | --- | --- | --- |
| FA-090 | Muss | Moderne Windows-UI mit PySide6, Navigation links. | umgesetzt (Rahmen) |
| FA-091 | Muss | Bereich Projekt: neu, öffnen, speichern; Menü **Projekt → Einstellungen**. | teilweise (neu/öffnen/speichern/Einstellungen; zuletzt verwendete Projekte intern in `recent.json`, noch ohne UI-Liste) |
| FA-092 | Muss | Bereich Import: Ordner, Analyse, Fortschritt, Dateiliste mit Zeit/GPS/Kamera. Die Liste wird während des Einlesens periodisch aktualisiert, erneut nach GPS-Abgleich, und vor den Vorschaubildern. | umgesetzt (Kamera/Pilot, DHV-Leonardo-Spalte für IGC) |
| FA-093 | Muss | Bereiche Timeline, Karte, Fotos, Tagebuch, Export. | teilweise (Timeline, Karte, Fotos, Tagebuch umgesetzt; Export Platzhalter bis Phase 8) |
| FA-094 | Muss | Lange Aufgaben laufen über `QThreadPool`/`QRunnable`; die GUI bleibt bedienbar. | umgesetzt (Import) |
| FA-095 | Muss | Eine defekte Datei bricht den Import nicht ab; Fehler sind geloggt, in der DB und in der UI sichtbar. | umgesetzt |

### 4.10 Galerie

| ID | Prio | Anforderung | Stand |
| --- | --- | --- | --- |
| FA-100 | Muss | Performante Übersicht über gecachte Thumbnails, nicht über Originale. HEIC-Vorschauen über Windows-Shell/WIC oder eingebettetes JPEG. | umgesetzt |
| FA-101 | Soll | Filter: Datum, Ort, Typ, Bewertung, Dubletten, Qualität, Favoriten, im Tagebuch verwendet / nicht verwendet. | teilweise (Dateiname, Jahr, mit/ohne Ort, JPEG/HEIC/PNG/RAW, Favoriten, nicht im Tagebuch; Bewertung/Qualität/Dubletten später) |

### 4.11 Persistenz und Projekt

| ID | Prio | Anforderung | Stand |
| --- | --- | --- | --- |
| FA-110 | Muss | SQLite + SQLAlchemy 2 + Alembic-Migrationen. | umgesetzt |
| FA-111 | Muss | Tabellen u. a. für Projekte, Quelldateien, Fotos, Videos, Tracks, Punkte, Reise, Tage, Orte, Ereignisse, Übernachtungen, Texte, Analysen, Ähnlichkeitsgruppen, Exportkonfiguration. | teilweise (Schema vollständig; Analysen/Ähnlichkeit/Exportzeilen ungenutzt bis Phase 8–10) |
| FA-112 | Muss | Projektordner mit `project.sqlite`, `settings.toml`, `thumbnails/`, `cache/`, `exports/`, `logs/`. | umgesetzt |
| FA-113 | Muss | Projekt schließen und wieder öffnen erhält Index und Einstellungen. | umgesetzt |
| FA-114 | Muss | Cache: Thumbnails, Metadaten, Analysen, Hashes; keine Vollanalyse unveränderter Dateien. | teilweise (Hash/mtime/Thumbnails; Analysen Phase 9) |

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
| NFA-010 | Muss | Standardbetrieb lokal; keine automatische Übertragung von Fotos, GPS oder Reisedaten. | umgesetzt |
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

- **Projekt:** Name, Zeitstempel, Quellwurzel, optionale Standardzeitzone; Datei `settings.toml` (Exportformat, Pfade, Platzhalter)
- **Quelldatei:** technische und Aufnahme-Metadaten, Positionsherkunft
- **Datei-Fehler:** Pfad, Phase, Meldung
- **Foto / Video:** Favorit, Tagebuch-Nutzung (`used_in_journal`), Titelbild, Herkunft auto/manual; die Tageszugehörigkeit folgt der Aufnahmezeit, nicht dem Häkchen
- **Track / Trackpunkt:** Geometrie und Zeit
- **Reise / Tag / Abschnitt / Ort / Ereignis / Notiz / Übernachtung**
- **Fotoanalyse / Ähnlichkeitsgruppe / Exportkonfiguration**

---

## 7. Benutzeroberfläche — Muss-Inhalte je Bereich

| Bereich | Phase 7 | Erste vollständige Version |
| --- | --- | --- |
| Projekt | Name, Ordnerpfad, Anlegen, Öffnen, Speichern, Einstellungen (`settings.toml`) | plus zuletzt verwendete Projekte in der UI |
| Import | Pfadwahl, Analyse, Fortschritt, Zähler, vollständige Dateitabelle | unverändert |
| Timeline | Tage aus Aufnahmezeit, Auto-Ereignis, Orte bestätigen/löschen, Übernachtungen anzeigen | plus Abschnitte, Ereignis-Reihenfolge |
| Karte | Track, Fotos/Videos, Orte, Übernachtungen, Cluster je Tag, offline ohne OSM | plus Reiseabschnitte |
| Fotos | Galerie, Filter (Jahr/Ort/Typ/Favorit/nicht im Tagebuch), Favorit umschalten | plus Qualität, Dubletten |
| Tagebuch | Titel, Text, Fotos zu/ab, Titelbild, Übernachtungen anlegen/löschen | plus Abschnitte, Bildunterschriften |
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

**Aktueller Abnahmestand (Phase 7):** Punkte 1–16. Punkt 17 folgt in Phase 8.

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
| 7 | Timeline und manuelle Bearbeitung | erledigt |
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
