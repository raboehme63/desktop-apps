# fitnesscore

GUI-freie Python-Bibliothek und CLI für eine lokale Fitness-SQLite-Datenbank
(Polar-JSON, Garmin/Polar-FIT, IGC). Keine Abhängigkeit zu Qt oder `travelcore`.

Aufruf und Parameter stehen ausführlich im Wurzel-[README](../../README.md)
(Abschnitt *Fitness-Datenbank*). Kurzform hier.

## Aufruf

Nach `pip install -e packages/fitnesscore` aus der Repository-Wurzel:

```powershell
.\.venv\Scripts\python.exe -m fitnesscore -h
.\.venv\Scripts\fitnessdb.exe -h
```

`--db` steht vor dem Unterbefehl.

```powershell
.\.venv\Scripts\python.exe -m fitnesscore --db D:\Fitness init
.\.venv\Scripts\python.exe -m fitnesscore --db D:\Fitness import -d D:\tracks
.\.venv\Scripts\python.exe -m fitnesscore --db D:\Fitness import -d D:\tracks -r
.\.venv\Scripts\python.exe -m fitnesscore --db D:\Fitness import -d D:\tracks --r
.\.venv\Scripts\python.exe -m fitnesscore --db D:\Fitness import -d D:\tracks --recursive
.\.venv\Scripts\python.exe -m fitnesscore --db D:\Fitness import -f D:\tracks\fahrt.FIT
.\.venv\Scripts\python.exe -m fitnesscore --db D:\Fitness import -f D:\flights\flug.igc
.\.venv\Scripts\python.exe -m fitnesscore --db D:\Fitness export-igc --sports paragliding --from 2025-05-01 --to 2025-05-31 --out D:\out
.\.venv\Scripts\python.exe -m fitnesscore --db D:\Fitness sports
.\.venv\Scripts\python.exe -m fitnesscore --db D:\Fitness export-gpx --from 2026-08-01 --to 2026-09-02 --out D:\out
.\.venv\Scripts\python.exe -m fitnesscore --db D:\Fitness export-gpx --sports kitesurfing --from 2026-08-01 --to 2026-09-02 --out D:\out
```

## Parameter

| Parameter | Pflicht | Bedeutung |
| --- | --- | --- |
| `--db ORDNER` | nein | Store-Ordner (`fitness.sqlite` darin) oder `.sqlite`-Datei. Standard: `./fitness`. |
| `init [target]` | nein | Leeren Store anlegen. Existierende Datenbank ist ein Fehler. |
| `import -f DATEI` | eine von `-f`/`-d` | Eine `.json`-, `.fit`- oder `.igc`-Datei. |
| `import -d VERZEICHNIS` | eine von `-f`/`-d` | Ordner, nur `.json`, `.fit` und `.igc`. Erneuter Lauf = Update (neue SHA-256). |
| `import -r` / `--r` / `--recursive` | nein | Nur mit `-d`: Unterverzeichnisse. |
| `export-gpx --from` / `--to` | ja | UTC-Tage, einschließlich. Nur Polar/FIT, keine IGC. |
| `export-gpx --out ORDNER` | ja | Zielordner für die GPX-Dateien. |
| `export-igc --from` / `--to` | ja | UTC-Tage, einschließlich. Nur IGC-Flüge. |
| `export-igc --out ORDNER` | ja | Zielordner; Originaldatei, keine GPX. |
| `export-gpx` / `export-igc --sports` | nein | Filter; ohne Flag alle Treffer im Zeitraum. Alias `--sport`. |
| `sports` | — | Slugs mit Track-Anzahl. |

Unterhilfen: `python -m fitnesscore init -h`, `import -h`, `export-gpx -h`, `export-igc -h`.

## Kommandoübersicht (`-h`)

```
usage: fitnessdb [-h] [--db ORDNER] {init,import,export-gpx,export-igc,sports} ...

  init         Store-Ordner und leere Datenbank anlegen
  import       JSON-, FIT- und IGC-Dateien importieren (alles, nicht nur Routen)
  export-gpx   GPX (Polar/FIT) nach optionaler Sportart und Datumsbereich
  export-igc   Original-IGC nach optionaler Sportart und Datumsbereich
  sports       Sportarten auflisten, für die eine Route vorliegt
  --db ORDNER  Store-Ordner oder fitness.sqlite (Standard: ./fitness)
```

```
usage: fitnessdb import [-h] (-f DATEI | -d VERZEICHNIS) [-r]

  -r, --recursive  mit -d Unterverzeichnisse

usage: fitnessdb export-gpx [-h] [--sports SPORT [SPORT ...]] --from DATUM
                            --to DATUM --out ORDNER
usage: fitnessdb export-igc [-h] [--sports SPORT [SPORT ...]] --from DATUM
                            --to DATUM --out ORDNER
```
