# Windows-Paketierung

Baut ein Installationspaket für **Reisetagebuch** unter Windows 10/11. Die
Anwendung unter `apps/` und `packages/` wird dabei nicht geändert.
Anforderungen: FA-140–FA-144 im [Pflichtenheft](../docs/pflichtenheft.md).
Leitlinie: [Konzept § 7.1](../docs/konzept.md). Technik: [Architektur](../docs/architecture.md).
Prüfung: MT-22 in der [Testdokumentation](../docs/testdokumentation.md).

macOS ist kein Ziel: HEIC-/Video-Vorschauen nutzen die Windows-Shell, Einstellungen
liegen unter `%LOCALAPPDATA%\TravelJournal`.

## Ergebnis

| Artefakt | Pfad | Zweck |
| --- | --- | --- |
| Ordner | `dist/Reisetagebuch/` | Gestartete App (`Reisetagebuch.exe`) |
| Zip | `dist/Reisetagebuch-2.1.1-windows.zip` | Portable Weitergabe |
| Setup | `dist/Reisetagebuch-2.1.1-setup.exe` | Installer (Startmenü, optional Desktop), nur mit Inno Setup |

Die Installation erfolgt **pro Benutzer** nach `%LOCALAPPDATA%\Programs\Reisetagebuch`
(kein Administratorrecht). Projektdaten bleiben eigene Ordner; App-Einstellungen
weiterhin unter `%LOCALAPPDATA%\TravelJournal`.

## Voraussetzungen

1. Entwicklungsumgebung laut [README.md](../README.md) (Python 3.12, `.venv`,
   editierbare Installation von `travelcore` und `traveljournal`).
2. Optional: [Inno Setup 6](https://jrsoftware.org/isinfo.php), damit die Setup-EXE
   entsteht. Ohne Inno gibt es nur Ordner und Zip.

PyInstaller wird vom Skript ins venv installiert und ist keine Laufzeitabhängigkeit
der App.

## Bauen

Im Repository-Stamm:

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

Nur einfrieren, ohne Inno:

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -SkipInstaller
```

Dauer und Größe: Qt WebEngine (Karte) macht das Paket groß (oft mehrere hundert MB)
und den Build mehrere Minuten lang.

Windows Defender scannt die frisch erzeugte `Reisetagebuch.exe` oft unmittelbar.
Das Build-Skript kopiert sie in diesem Fall aus dem Arbeitsverzeichnis nach.

Beim **ersten Start** kann SmartScreen die unsignierte EXE blockieren
(„Windows hat den Computer geschützt“). Über **Weitere Informationen** und
**Trotzdem ausführen** lässt sie sich starten. Eine Code-Signatur wäre der
saubere Weg für die Weitergabe an andere Rechner.

## Was nicht mitgeliefert wird

Diese Werkzeuge bleiben optional, wie in der laufenden Entwicklung:

- **HEIF Image Extensions** (Microsoft Store) für HEIC ohne eingebettetes JPEG
- **ExifTool**, falls im PATH oder an den in `travelcore` hinterlegten Pfaden
- **FFmpeg / ffprobe** (Video-Metadaten, geplant)

## Hinweise

- Einstieg ist `packaging/entry.py` (`multiprocessing.freeze_support`), nicht
  `traveljournal.main`. So bleiben ProcessPool-Worker ohne extra GUI-Fenster,
  ohne die App-Quellen anzufassen.
- PySide6 unterliegt der LGPL-3.0. `NOTICE.txt` liegt im Paket; siehe auch
  [docs/dependencies.md](../docs/dependencies.md).
- Es wird **onedir** gebaut (Ordner mit EXE), nicht eine einzelne Datei. Das
  ist für Qt WebEngine und den ProcessPool zuverlässiger.
