# Belegläufe gegen das Schema von MOSIDI (03.11.2026)

> **Stand vor E40.** Die INKAR-Zahl (57 259) stammt aus der Zeit, als wertgleiche Reihen noch zusammengeführt wurden. Seit E40 schreibt dieselbe Konfiguration 62 929 INKAR-Zeilen und 16 Zeilen `table_metadata`. Maßgeblich für den Abgabestand: [`../pruefstand-2026-11-05-e46/`](../pruefstand-2026-11-05-e46/).

Testdatenbank aus `docker-compose.yml` (PostgreSQL 16.15, PostGIS 3.6.4) mit den Bestandstabellen
aus dem öffentlichen Repository MOSIDI-ORG/MOSIDI (`sql/mosidi/001_bestand.sql`), leeres Volume,
`docker compose run --rm einrichten`, dann die Läufe mit `config/quellen.yaml`.

| Lauf | Befehl | Ergebnis |
|---|---|---|
| `20261103T103625Z` | `pipeline --alle` | Erster Lauf, 113 s: 882 Gebäude (WFS ALKIS der LGB) in `"Gebäude (ALKIS)"`, 413 Gemeinden (WFS Verwaltungsgrenzen der LGB) in `"Kommunale Gebiete Brandenburg (InNoWest)"`, 18 Kreise in `"Landkreis"`, 1 239 Bevölkerungs- und 413 Flächenwerte des Amts für Statistik und 57 259 INKAR-Werte (5 Kürzel, Zeitbezug 1995 bis 2023) in `dashboard_data_de`. 413 von 413 Gebietsschlüsseln haben eine Fläche. Warnung: 5 670 INKAR-Zeilen mit schon vorhandenem Zielschlüssel (gleicher Indikator in mehreren Bereichen, Entscheidung E27) |
| `20261103T103833Z` | `pipeline --alle` | Zweiter Lauf: alles unverändert (882, 413, 18, 1 239, 413, 57 259) |
| `20261103T104029Z` | `pipeline` | Dritter Lauf ohne `--alle`: alle sechs Quellen „nicht fällig“ (Rhythmus wöchentlich bzw. monatlich), 0,02 s |

`datenbank-auszug.txt`: Protokoll in `pipeline_meta` (Lauf, Quelle, neu/geändert/entfernt/unverändert,
Dauer), Bestandsregister, Zeilen je Zieltabelle, `dashboard_data_de` je `source` und die 14 Zeilen in
`table_metadata` (3 je Geometrietabelle, 11 je Indikator wie im MOSIDI-Skript). Das Beispiel mit den
Kennzahlen einer Gemeinde ist seit 05.11.2026 entfernt (Einzeldatensätze, Antwort 69; E38).

Die Änderungskarte des ersten Laufs (`20261103T103625Z-karte.html`, 8,8 MB, Gebäude, Gemeinden, Kreise und
Kennzahlen je Gemeinde) ist seit 05.11.2026 entfernt: Sie enthielt die importierten Datensätze, darunter 882
Gebäude mit Geometrie und Attributen (Antwort 69; E38). Wie die Seite aussieht, zeigt
`../aenderungskarte/beispielkarte-synthetisch.html` mit erfundenen Daten.
