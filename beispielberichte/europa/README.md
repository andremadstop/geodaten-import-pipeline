# Probelauf Europa (03.11.2026)

Frage: Trägt dieselbe Pipeline über Brandenburg und Deutschland hinaus? Probe mit allen Gemeinden (LAU, Local Administrative Units) der Gemeindegrenzen von Eurostat GISCO, Stand LAU 2024, dazu Bevölkerung, Bevölkerungsdichte und Fläche je LAU. Konfiguration: `config/europa.yaml`. Neu dafür ist nur der Quelltyp `geojson` (Entscheidung E30), alles andere ist Konfiguration.

- Testdatenbank aus `docker-compose.yml` (PostgreSQL 16.15, PostGIS 3.6.4) mit dem MOSIDI-Schema, eigenes Compose-Projekt, leeres Volume.
- Danach `einrichten --config /app/config/europa.yaml` und zweimal `pipeline --config /app/config/europa.yaml --alle`.
- Den Speicher hat `docker stats` während des Laufs fortlaufend abgetastet (28 bzw. 23 Stichproben, etwa alle 2 s).
- Die Zählwerte in `datenbank-auszug.txt` stammen aus der Datenbank nach dem Folgelauf.

| | Erstlauf `20261103T171337Z` | Folgelauf `20261103T171446Z` |
|---|---|---|
| Gemeinden (LAU, GeoJSON von GISCO) nach `"Kommunale Gebiete Deutschland"` | 97 987 neu, 32 s | 97 987 unverändert, 28 s |
| Kennzahlen (CSV von GISCO) nach `dashboard_data_de` | 293 961 neu (3 je LAU), 24 s | 293 961 unverändert, 18 s |
| Laufzeit gesamt | 55 s | 46 s |
| höchster abgetasteter Speicher des Pipeline-Containers (Eigenmessung, `docker stats`-Abtastung, Rohdaten nicht aufbewahrt) | 58,2 MiB | 60,0 MiB |
| Größe der Datenbank danach | 283 MB | 283 MB |

**Einzelheiten**

- **Gemeinden:** 97 987 LAU aus 34 Ländern: die 27 EU-Staaten sowie CH, NO, IS, LI, AL, MK und RS. Nicht enthalten, weil GISCO sie in LAU 2024 nicht führt: unter anderem das Vereinigte Königreich, die Ukraine, die Türkei, Bosnien und Herzegowina, Montenegro, Kosovo und Moldau. Es ist also „die EU und sieben weitere Staaten“, nicht ganz Europa.
  - Alle Geometrien gültig (`ST_IsValid`), alle als MultiPolygon in EPSG:4326. Die Ausdehnung reicht bis in die französischen Überseegebiete (Länge −63 bis 56, Breite −21 bis 71).
  - Gegenprobe Deutschland: 10 978 LAU, genau so viele Gemeindekennziffern, wie INKAR im Deutschland-Lauf hatte.
  - Gefüllt sind `objid` (= `GISCO_ID`, z. B. `DE_12054000`, höchstens 16 Zeichen wie die Spalte), `name` und `geom`.
- **Kennzahlen:** je LAU drei Zeilen, `source = 'Eurostat GISCO'`, `granularity = 'LAU'`, `zeitbezug = 2024`, `kennziffer` = `GISCO_ID`. Alle 97 987 Schlüssel haben eine Fläche in der Gemeindetabelle.

| Indikator | Zeilen | mit Zahl | null |
|---|---|---|---|
| Bevölkerung (LAU, Eurostat) | 97 987 | 54 128 | 43 859 |
| Bevölkerungsdichte je km² (LAU, Eurostat) | 97 987 | 54 128 | 43 859 |
| Fläche in km² (LAU, Eurostat) | 97 987 | 97 987 | 0 |

- **`table_metadata`:** 4 Zeilen, eine für die Gemeindetabelle und eine je Indikator, Rhythmus jährlich (`ANNUAL`).
- **Größen** (`datenbank-auszug.txt`): Register `pipeline_meta.bestand` 108 MB, Gemeindetabelle 65 MB, Änderungsprotokoll 56 MB, `dashboard_data_de` 38 MB.
- **Die übrigen Prüfungen:** `./pruefen.sh` ohne Befund (84 Tests bestanden, darunter 11 neue für den Quelltyp `geojson`), die 10 Datenbanktests (`tests/test_datenbank.py`) gegen dieselbe Testdatenbank bestanden.

## Was nicht oder nur eingeschränkt geklappt hat

1. **Keine Bevölkerungszahl für FR, ES, AL, IS und RS.** Eurostat liefert dort durchgehend 0, ebenso für einzelne LAU in CY (220), CH (44), EL (16), CZ (4), SK (1) und DE (203). Die Konfiguration liest 0 als „kein Wert“ (null), damit nicht 43 000 falsche Nullen in der Tabelle stehen. Dadurch sind auch echte Nullen null, etwa die 203 gemeindefreien Gebiete in Deutschland. Die Fläche ist überall gefüllt.
2. **Zwölf Namen gekürzt.** `name` ist in MOSIDI `varchar(60)`; zwölf LAU-Namen sind länger (61 bis 76 Zeichen: CY_3311 und elf Gemeinden in Portugal, Schlüssel in `datenbank-auszug.txt`). PostgreSQL kürzt beim Typwechsel ohne Fehlermeldung. **Behoben (E31):** Die Pipeline meldet das seither als Warnung mit Anzahl, größter Länge und Schlüsseln; Gegenprobe `--nur gemeinden_lau` am 03.11.2026 (`20261103T175006Z.txt`): „12 Objekte mit name länger als 60 Zeichen (bis 76)“. **Seit E47 anders:** Die Pipeline kürzt nicht mehr, die zwölf Zeilen werden zurückgehalten. In einer frischen Datenbank entstehen diese zwölf LAU also nicht, ein vorhandener Eintrag behält seinen bisherigen (hier: gekürzten) Namen; `kennzahlen_lau` meldet sie bei der Gebietsprüfung ohne Fläche. Die Läufe oben sind am Stand vor E47 entstanden und nicht wiederholt.
3. **Keine passende Tabelle in MOSIDI.** Die LAU stehen in `"Kommunale Gebiete Deutschland"`, weil es dort keine Tabelle für europäische Gemeinden gibt. Das ist eine Testzuordnung (E30); `config/europa.yaml` gehört nicht in dieselbe Datenbank wie `config/deutschland.yaml`.
4. **Abfrageplan ohne Statistik** (`abgebrochen-20261103T170214Z.txt`). Im ersten Versuch schrieben zwei Quellen (Bevölkerung mit Dichte, dann Fläche) nacheinander in `dashboard_data_de`. Die zweite Quelle hing über acht Minuten im Vergleich und wurde abgebrochen.
   - Ursache: Die Datenbank plante den Vergleich, bevor sie für die eben mit 108 256 Zeilen gefüllte Tabelle eine Statistik hatte. Sie schätzte eine Zeile und wählte eine verschachtelte Schleife, also rund 98 000 × 108 000 Vergleiche. Nachgestellt mit einer Kopie der Tabelle ohne Statistik: Nested Loop; mit Statistik: Hash Join.
   - Abhilfe hier: Bevölkerung, Dichte und Fläche als eine Quelle.
   - **Behoben (E31):** Jede Quelle gleicht jetzt ohne verschachtelte Schleifen ab (`SET LOCAL enable_nestloop = off`), ohne zusätzliche Rechte. Nachgestellt auf frischer Datenbank (`befund-planer-E31.txt`): Betroffen sind große Quellen mit denselben festen Werten (`source`, `granularity`) im selben Lauf und ein Folgelauf derselben Quelle, bevor autovacuum die Tabelle analysiert hat; zwei Quellen mit verschiedenem `source` hingen nicht. Zweite Quelle mit 40 000 Zeilen vorher 89 s, nachher 2,2 s; mit 100 000 Zeilen vorher Abbruch nach über 60 s, nachher 4,8 s.
5. **Nicht gemessen:** der Download der GeoJSON-Datei (150 MB) im Container. Sie war bei beiden Läufen schon im Cache (`cache/`, geladen am 03.11.2026 beim Test des Adapters: Download und Lesen aller 97 987 Objekte zusammen 9 s, 105 MiB Spitzenspeicher außerhalb des Containers). Die CSV (5,6 MB) holt jede Quelle bei jedem Lauf neu.
6. **Weggelassen:** eine Kennzahl auf NUTS-3-Ebene über die Eurostat-API.

## Quellen, Nutzungsbedingungen, Abruf

- **Gemeindegrenzen und Kennzahlen:** Eurostat GISCO, LAU 2024 (Stand 01.01.2024, veröffentlicht 30.06.2025, Korrektur norwegischer Codes 18.02.2026):
  - `https://gisco-services.ec.europa.eu/distribution/v2/lau/geojson/LAU_RG_01M_2024_4326.geojson`
  - `https://gisco-services.ec.europa.eu/distribution/v2/lau/csv/LAU_RG_01M_2024_4326.csv`
- **Vermerk:** „© EuroGeographics bezüglich der Verwaltungsgrenzen“.
- **Nutzungsbedingungen** (Download-Regeln auf der GISCO-Seite „Statistical units“, gelesen am 03.11.2026):
  - Quellenangabe ist Pflicht, der Vermerk muss in Karten und Veröffentlichungen sichtbar sein.
  - **Keine kommerzielle Nutzung.** Dafür verweist Eurostat auf eine Lizenz über EuroGeographics.
  - Der Probelauf lief deshalb nur in einer eigenen Testdatenbank. Hier liegen nur Zählwerte und Schlüssel, keine Namen oder Geometrien. Eine Nutzung über einen technischen Probelauf hinaus ist vorher zu klären (Nutzung durch die Hochschule oder Lizenz über EuroGeographics).
  - Ob für die Bevölkerungszahlen in derselben Datei andere Bedingungen gelten (Weiterverwendung von Eurostat-Statistik), ist nicht geprüft.
- **robots.txt** von `gisco-services.ec.europa.eu` am 03.11.2026: `User-agent: * / Allow: /`.
- **Abruf:** Die GeoJSON-Datei wurde einmal geholt, danach nur mit `If-Modified-Since` nachgefragt (auch bei der Gegenprobe zu E31, `--nur gemeinden_lau`). Die CSV kam einmal zur Vorab-Prüfung und dann einmal je Quelle und Lauf (insgesamt fünfmal 5,6 MB, der abgebrochene Versuch eingeschlossen), dazu zwei kleine Teilabrufe der Dateianfänge. Abgerufen wurde mit der Kennung der Pipeline als User-Agent; Rhythmus in der Konfiguration: jährlich.
