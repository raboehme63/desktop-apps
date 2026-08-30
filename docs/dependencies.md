# Direkte Abhängigkeiten

Stand: Phase 7 plus Medien-Pipeline, Software R3.0.0. Es werden **keine** Platzhalter-Bibliotheken installiert,
die der aktuelle Code nicht verwendet.

Lizenzangaben stammen aus den veröffentlichten Projektdaten der jeweiligen
Pakete. Diese Datei trifft **keine** eigene Lizenzentscheidung für eine
spätere kommerzielle Veröffentlichung; sie dokumentiert nur, was eingebunden ist.

Installierte Versionen beziehen sich auf die aktuelle Entwicklungsumgebung
(Python 3.12.10).

## Laufzeit – travelcore

| Bibliothek | Version | Lizenz | Zweck |
| --- | --- | --- | --- |
| SQLAlchemy | 2.0.52 | MIT | ORM und SQLite-Zugriff |
| Alembic | 1.19.1 | MIT | Datenbankmigrationen |
| Pydantic | 2.13.4 | MIT | Domänenmodelle und Validierung |
| pydantic-settings | 2.15.0 | MIT | Anwendungskonfiguration |
| Pillow | 12.3.0 | HPND-sell-variant | EXIF/XMP, Bildgröße, JPEG-Thumbnails |
| gpxpy | 1.6.2 | Apache-2.0 | GPX-Parsing |
| Folium | 0.20.0 | MIT | Karten-HTML (Leaflet, MarkerCluster) |

Transitiv durch die oben genannten Pakete: `greenlet`, `Mako`, `MarkupSafe`,
`annotated-types`, `pydantic-core`, `typing-extensions`, `typing-inspection`,
`python-dotenv`, `branca` 0.8.2, `jinja2` 3.1.6, `xyzservices` 2026.3.0.

Jinja2 kommt derzeit transitiv mit Folium. Phase 8 nutzt es direkt für den HTML-Export.
Aufenthaltscluster (`travelcore.geolocation.stays`) rechnen Haversine in der
Standardbibliothek; geographiclib ist nicht installiert.

## Laufzeit – traveljournal

| Bibliothek | Version | Lizenz | Zweck |
| --- | --- | --- | --- |
| travelcore | 0.1.0 | MIT | Geschäfts- und Importlogik |
| PySide6-Essentials | 6.11.2 | LGPL-3.0 / kommerzielle Qt-Lizenz | Desktop-UI (Qt for Python) |
| PySide6-Addons | 6.11.2 | LGPL-3.0 / kommerzielle Qt-Lizenz | QWebEngineView für die Karte |
| shiboken6 | 6.11.2 | LGPL-3.0 / kommerzielle Qt-Lizenz | Bindings-Runtime für PySide6 |

PySide6 unterliegt der LGPL-3.0 (bzw. einer kommerziellen Qt-Lizenz). Für eine
spätere proprietäre Veröffentlichung müssen die LGPL-Bedingungen (u. a.
dynamisches Linken, Hinweispflicht) eingehalten oder eine Qt-Lizenz erworben
werden. Das ist keine Rechtsberatung.

## Entwicklung

| Bibliothek | Version | Lizenz | Zweck |
| --- | --- | --- | --- |
| pytest | 9.1.1 | MIT | Tests |
| ruff | 0.16.3 | MIT | Linting und Formatierung |

## Paketierung (nur Build, nicht Laufzeit der App)

Diese Werkzeuge installiert `packaging/build.ps1` bzw. der Build-Rechner. Sie
gehören **nicht** zu den pip-Abhängigkeiten von `traveljournal` / `travelcore`.

| Werkzeug | Version / Hinweis | Lizenz | Zweck |
| --- | --- | --- | --- |
| PyInstaller | ≥ 6.11, < 7 (ins venv beim Build) | GPL-2.0-or-later mit Ausnahme für das erzeugte Bundle | Frozen onedir `Reisetagebuch.exe` |
| Inno Setup 6 | optional, [jrsoftware.org](https://jrsoftware.org/isinfo.php) | Inno Setup License | Setup-EXE mit Startmenü |

Das erzeugte Paket enthält weiterhin PySide6 (LGPL-3.0, dynamisch gelinkt) plus
`LICENSE` und `packaging/NOTICE.txt`. Qt WebEngine macht das Bundle groß
(typisch mehrere hundert MB unkomprimiert).

## Bewusst noch nicht installiert

Diese Bibliotheken sind für spätere Phasen vorgesehen. Sie werden erst
hinzugefügt, wenn der zugehörige Code sie tatsächlich nutzt.

| Bibliothek | Geplante Phase | Typische Lizenz | Zweck |
| --- | --- | --- | --- |
| geographiclib / geopy | später | MIT | Geodäsie, falls lineare Interpolation nicht reicht |
| OpenCV (`opencv-python-headless`) | 9 | Apache-2.0 | Bildqualität |
| imagehash | 10 | BSD-2-Clause / BSD-3-Clause | pHash / dHash |
| NumPy | 9 / 10 | BSD-3-Clause | numerische Analyse |
| pytest-qt | GUI-Tests | MIT | Qt-Tests |

## Bewusst vermieden als Zwangsabhängigkeit

| Bibliothek | Grund |
| --- | --- |
| PyMuPDF | Dual AGPL / kommerziell – nur nach bewusster Lizenzentscheidung |
| GPL-only Bild- oder PDF-Engines | können eine proprietäre Veröffentlichung erschweren |

PDF-Export (Phase 8+) soll über HTML→Druckengine oder LaTeX→PDF erfolgen,
hinter einer austauschbaren `PdfRenderer`-Schnittstelle.

## Eingebettete Pictogramme (keine pip-Abhängigkeit)

Verkehrsmittelsymbole liegen als SVG-Pfade in
`travelcore.timeline.symbols`. Phosphor Icons Bold (MIT) und Seitenansichten
von SVG Repo. Tabelle, URLs und Schritte zum Ergänzen:
[architecture.md — Verkehrsmittelsymbole](architecture.md#verkehrsmittelsymbole).
Lizenzhinweis im Paket: `packaging/NOTICE.txt`.

## Externe Werkzeuge (optional, nicht per pip erzwungen)

| Werkzeug | Geplante Phase | Hinweis |
| --- | --- | --- |
| HEIF Image Extensions (Windows) | 5 | optional; Explorer-/WIC-Vorschau für HEIC ohne eingebettetes JPEG; **nicht** im Installer |
| FFmpeg / ffprobe | Video-Metadaten | über gekapselten Adapter, nicht im MVP; **nicht** im Installer |
| ExifTool | 3 | optional; füllt Lücken in HEIC/RAW, nie aus der GUI aufgerufen; **nicht** im Installer |
