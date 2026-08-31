# travelcore

GUI-freie Python-Bibliothek für Dateiindexierung, Metadaten, GPS-Zuordnung,
Timeline, Karte, Bildanalyse, Länderkatalog (`travelcore.geo`) und Reise-Persistenz.

Diese Bibliothek darf **keine** Abhängigkeit zu PySide6 oder anderem GUI-Code
haben. Sie wird von `traveljournal` und später von `PhotoInspector` genutzt.

Der Länderkatalog (ISO-2, Name DE/EN, Flaggen- und Umriss-SVG) liegt unter
`src/travelcore/geo/data/`. Rebuild: `scripts/build_country_catalog.py` im
Repository-Wurzelverzeichnis.
