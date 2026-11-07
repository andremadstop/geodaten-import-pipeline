# Deutschland-Lauf (03.11.2026)

> **Historischer Stand vor E40.** Dieser Lauf hat 142 678 INKAR-Zeilen wegen gleichen Zielschlüssels übersprungen (damals „die erste zählt“, E27); seine Zahlen belegen die Skalierung, nicht die heutige Schlüsselbehandlung. Die Speicherwerte unten sind Eigenmessungen mit `docker stats`-Abtastung, die Rohdaten sind nicht aufbewahrt. Maßgeblich sind die Läufe am Abgabestand (Prüfstand nach E46, 05.11.2026, mit Rohdaten und `memory.peak`): [`../pruefstand-2026-11-05-e46/`](../pruefstand-2026-11-05-e46/) (1 640 420 INKAR-Zeilen, keine übersprungen, Erstlauf 272,6 s, Folgelauf 260,4 s auf einem parallel genutzten Rechner, höchste Probe von `docker stats` 129,5 und 365,9 MiB, `memory.peak` bis 366,6 MiB, Datenbank 1 132 MB; am Stand nach E45 in zwei Reihen 364,6 bis 432,7 s und 259,9 bis 369,0 s, [`../pruefstand-2026-11-05-e45/`](../pruefstand-2026-11-05-e45/)).

Skalierungsbeleg zu Antwort 32 der TH („… sollte auch für ganz Deutschland funktionieren“). Es ist dieselbe Pipeline wie für Brandenburg, nur mit anderer Konfiguration: `config/deutschland.yaml`.

- Testdatenbank aus `docker-compose.yml` (PostgreSQL 16.15, PostGIS 3.6.4) mit dem MOSIDI-Schema, leeres Volume.
- Danach `einrichten` und zweimal `pipeline --config /app/config/deutschland.yaml --alle`.
- Den Speicher hat `docker stats` während des Laufs fortlaufend abgetastet (113 bis 131 Stichproben je Lauf).

| | Erstlauf `20261103T122149Z` | Folgelauf `20261103T122623Z` |
|---|---|---|
| Gemeinden (VG250-WFS des BKG) nach `"Kommunale Gebiete Deutschland"` | 11 103 neu, 41 s | 11 103 unverändert |
| INKAR, Gemeinden bundesweit, nach `dashboard_data_de` | 1 640 420 Zeilen gelesen, 1 497 742 neu | 1 497 742 unverändert |
| Laufzeit gesamt | 261 s | 226 s |
| höchster abgetasteter Speicher des Pipeline-Containers | 94,2 MiB | 95,4 MiB |
| Größe der Datenbank danach | 861 MB | 861 MB |

**Einzelheiten**

- **Gemeinden:** Die 11 103 Objekte decken 10 949 verschiedene Gemeindeschlüssel aus allen 16 Ländern ab. Ein Schlüssel kann in der VG250 mehrfach vorkommen, weil Land- und Wasserflächen getrennt geführt werden. Gefüllt sind alle Spalten der Tabelle außer `id`.
- **INKAR:** 5 Kürzel ergeben 7 Indikator-Langtexte für die Jahre 1995 bis 2023.
  - 142 678 Zeilen stehen mit schon vorhandenem Zielschlüssel in der Datei; sie werden mit Warnung übersprungen (E27).
  - 10 946 von 10 978 Kennziffern haben eine Fläche. Die übrigen 32 sind Gemeinden, die es im INKAR-Gebietsstand 31.12.2023 gibt, in der aktuellen VG250 aber nicht mehr (z. B. 07232089).
- **`table_metadata`:** 8 Zeilen, eine für die Gemeindetabelle und eine je Indikator mit `granularity = 'Gemeindeebene'` (E28).
- **Größen** (`datenbank-auszug.txt`):
  - `dashboard_data_de` 167 MB
  - `"Kommunale Gebiete Deutschland"` 35 MB
  - Bestandsregister `pipeline_meta.bestand` 432 MB
  - Änderungsprotokoll `pipeline_meta.aenderung` 211 MB, das sind die 1,5 Mio. „neu“-Einträge des Erstlaufs

**Vorherige Fassung des Codes** (`datenbank-auszug-vor-E29.txt`, Läufe `20261103T110542Z` und `20261103T121535Z`):

- Hier setzte jeder Lauf das Register für alle Zeilen neu. Nach dem Folgelauf war die Datenbank 1 321 MB groß, das Register allein 896 MB mit 1 508 845 toten Zeilen.
- Seit E29 berührt ein Lauf ohne Änderung das Register nicht mehr; die Datenbank bleibt nach dem Folgelauf gleich groß.
- Zahlen und Laufzeiten der Quellen waren dieselben (Erstlauf 253 s, Folgelauf 265 s, Speicher höchstens 96,7 MiB).

Die Änderungskarte ist in `deutschland.yaml` abgeschaltet (`karte: false`), weil 11 000 Gemeindeflächen die Seite zu groß machen würden.
