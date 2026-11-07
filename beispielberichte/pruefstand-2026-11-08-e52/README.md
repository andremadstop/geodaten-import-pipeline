# Prüfstand 08.11.2026, Abgabestand nach E52 (Tests, Datenbanktests mit Ende-zu-Ende-Test, Prüfkonfiguration gegen die echten Dienste, Lauf im Compose von MOSIDI, Lieferkonfiguration im Vollumfang mit Wertabgleich je Zeile)

Das ist der Prüfstand des Abgabestands (Tag `angebot-va-2026-536`): Stand nach E52 ([`docs/entscheidungen.md`](../../docs/entscheidungen.md), E52: unveränderte
Lieferung überspringen, Katalog nach der Art von MOSIDI, Gesamtzahl vor und nach dem Paging, Umfangsänderung sperren,
Ende-zu-Ende-Test mit Wiederherstellungsprobe, Abnahmekriterien, Aufräumen des E52-Codes). Der Code ist eingefroren;
während dieses Prüfstands hat sich an `pipeline`, `tests`, `config`, `sql`, `Dockerfile`, `deploy` und
`requirements.txt` nichts geändert (Teilbäume unten).

Alles in diesem Ordner ist am selben Code-Stand entstanden: die Tests ohne Datenbank, die Datenbanktests auf
PostgreSQL 16 und 18 (einschließlich des Ende-zu-Ende-Tests und der Wiederherstellungsprobe aus E52), zwei Läufe der
Prüfkonfiguration `config/pruefkonfiguration.yaml` gegen die echten Dienste und zwei Läufe im Compose-Setup von MOSIDI
mit der Katalogaktualisierung, dazu drei Läufe der Lieferkonfiguration `config/quellen.yaml` im Vollumfang und der
Wertabgleich je Zeile (Abschnitt „Vollumfang“, fertig am 09.11.2026). Für `config/deutschland.yaml` gibt es an diesem
Stand keinen Lauf; dafür gilt der Prüfstand nach E51, [`../pruefstand-2026-11-07-e51/`](../pruefstand-2026-11-07-e51/).

**Kurz:** `pruefen.sh` meldet „Alles in Ordnung.“ (529 Tests bestanden, 83 übersprungen), die Datenbanktests bestehen
83 von 83 auf PostgreSQL 16.15 und 83 von 83 auf PostgreSQL 18.6. Alle vier Läufe enden mit Rückgabe 0, ohne Warnung,
mit 0 doppelten Zielschlüsseln, und liefern dieselben Zählungen wie nach E51 (882/413/18, 413 + 413, 62 929). Die drei
Läufe im Vollumfang enden ebenso mit Rückgabe 0 und ohne Warnung, mit den Zählungen nach E51 (33 547 606 INKAR-Zeilen);
der Wertabgleich je Zeile ergibt 0 fehlend, 0 überzählig, 0 abweichend. Der Folgelauf ohne Änderung überspringt INKAR
(E52) und dauert 2,9 min statt 159,7 min nach E51. Im
Compose von MOSIDI aktualisiert die Pipeline den Katalog jetzt **gleichzeitig** (`REFRESH MATERIALIZED VIEW
CONCURRENTLY`, Leser nicht blockiert; nach E51 exklusiv). INKAR kommt in allen Läufen aus der abgelegten Datei; kein
Lauf hat `www.bbr-server.de` abgerufen.

## Prüfkette

| Prüfung | Ergebnis | Protokoll |
|---|---|---|
| `./pruefen.sh` (ruff, bandit, pip-audit gegen PyPI, Tests ohne Datenbank, Secret-Scan, Stückliste) | „Alles in Ordnung.“: 529 Tests bestanden, 83 übersprungen (die Datenbanktests, sie laufen getrennt); bandit gibt nur die bekannte Warnung aus, dass ein `nosec` in `pipeline/quellen.py` keinen Treffer mehr unterdrückt (wie nach E49 bis E51) | [`pruefen.log`](pruefen.log) |
| `tests/test_datenbank.py` und `tests/test_ende_zu_ende.py` gegen eine echte PostGIS-Datenbank mit den MOSIDI-Tabellen, `postgis/postgis:16-3.6` | PostgreSQL 16.15, PostGIS 3.6.4: 83 von 83 (379,8 s) | [`datenbanktests.log`](datenbanktests.log) |
| dieselben Tests, `postgis/postgis:latest` | PostgreSQL 18.6, PostGIS 3.6.4: 83 von 83 (349,0 s) | [`datenbanktests.log`](datenbanktests.log) |

Zusammen 612 Testfälle (529 ohne, 83 mit Datenbank), dieselben Zahlen wie in E52 („Prüfkette danach“ beim Aufräumen
des E52-Codes). Die 83 Datenbanktests schließen den Ende-zu-Ende-Test (Kommandozeile gegen einen Testserver auf
127.0.0.1 bis in die Datenbank) und die Wiederherstellungsprobe aus `pg_dump` ein. Die Versionszeile jeder Datenbank
steht im Log. Anders als nach E51 tragen `pruefen.log` und `datenbanktests.log` keine Kopfzeile mit Teilbäumen und
Uhrzeit; die Teilbäume dieses Stands stehen in den beiden `ablauf.txt` (unten).

## Kein Abruf von `www.bbr-server.de`

Beide Konfigurationen tragen für INKAR `robots_freigabe` (Regelbetrieb der TH, Antwort 33). Für unsere Läufe gilt die
Regel aus `docs/betrieb.md`: Jeder eigene Lauf setzt `PIPELINE_INKAR_DATEI`, die abgelegte Datei hat Vorrang vor der
Freigabe. Belegt in allen vier Läufen und in den ersten beiden Läufen im Vollumfang (der dritte ruft nichts ab, alle
Quellen `nicht_faellig`):

| Beleg | Wo | Ergebnis |
|---|---|---|
| Hinweis der Pipeline | Text- und JSON-Bericht von `inkar_gemeinden` | „Abgelegte Datei, kein Abruf: inkar_2025.zip“ und „robots_freigabe konfiguriert, nicht genutzt (abgelegte Datei)“ |
| `letzte_abfrage` | JSON-Berichte | nur `isk.geobasis-bb.de` und `download.statistik-berlin-brandenburg.de`; `bbr-server` kommt in keinem Laufbericht vor (`grep -c` über alle `2026*.json` und `2026*.txt`: 0) |
| Namensauflösung im Container | `ablauf.txt` aller drei Ordner | `www.bbr-server.de -> 0.0.0.0`, `www.regionalstatistik.de -> 0.0.0.0` |

Für diesen Prüfstand ist keine eigene robots.txt-Abfrage abgelegt. Die Läufe rufen dieselben Rechner mit denselben
Pfaden ab wie nach E51; dort steht die Prüfung je Rechner (07.11.2026, Abschnitt „robots.txt je Rechner“ in
[`../pruefstand-2026-11-07-e51/README.md`](../pruefstand-2026-11-07-e51/README.md)).

## Rahmen der Läufe

Wie nach E51: Entwicklungsrechner (Linux, Docker, 16 Kerne), parallel für andere Arbeit genutzt; vor jedem Lauf prüfen
die Skripte die 1-Minuten-Last (Schwelle 8). Kein Lauf musste warten (Zeilen „Wartezeit“ in `ablauf.txt`, je 0 s); vor
den Läufen der Prüfkonfiguration und im Compose lag die Last zwischen 1,92 und 4,11, nach ihnen zwischen 1,55 und 2,59;
vor den drei Läufen im Vollumfang 4,86, 2,76 und 2,37, nach ihnen 2,62, 2,37 und 2,50
([`quellen/ablauf.txt`](quellen/ablauf.txt)). Die Laufzeiten sind Größenordnungen,
keine Messung auf einem ruhigen oder dem Zielrechner. Frische Datenbank je Ordner in einem Wegwerf-Compose-Projekt,
zufällige Passwörter, Container und Volumes danach entfernt; Pipeline als Container mit `mem_limit: 1g` (1 GiB).

Ablauf: [`beleg.sh`](beleg.sh) und [`mosidi-compose/lauf.sh`](mosidi-compose/lauf.sh), Kopien der Fassungen aus dem
Prüfstand nach E51; geändert sind nur Kopf, Imagename (`geodaten-import-pipeline:e52-beleg`) und beim Compose-Lauf der
Projektname (`gip-mosidi-e52-<pid>`). Aufrufe:

    beleg.sh pruefkonfiguration <Ordner> --alle -- --alle
    mosidi-compose/lauf.sh <MOSIDI-Klon> <Ordner>
    WERTE_EXPORT=1 beleg.sh quellen <Ordner> --alle -- --alle -- .     # Vollumfang

Laufzeiten auf eine Nachkommastelle gerundet; die Rohwerte stehen in den Berichten.

## Prüfkonfiguration und Compose von MOSIDI (Vergleich mit E51)

| | Prüfkonfiguration `config/pruefkonfiguration.yaml` (Brandenburg) | Compose von MOSIDI (Prüfkonfiguration) |
|---|---|---|
| Läufe | [`pruefkonfiguration/`](pruefkonfiguration/): [`20261108T221635Z`](pruefkonfiguration/20261108T221635Z.txt), [`20261108T221904Z`](pruefkonfiguration/20261108T221904Z.txt), je `--alle` | [`mosidi-compose/`](mosidi-compose/): [`20261108T222252Z`](mosidi-compose/20261108T222252Z.txt), [`20261108T222520Z`](mosidi-compose/20261108T222520Z.txt), je `--alle` |
| Zeit (MEZ) | 23:16 bis 23:22 | 23:22 bis 23:28 |
| Rückgabe | 0; 0 | `pipeline-einrichten` 0; Läufe 0; 0 |
| Laufzeit laut Bericht | 145,3 s; 145,5 s (nach E51: 146,8 s, ein Lauf) | 145,8 s; 153,5 s (nach E51: 145,4 s; 141,8 s) |
| Wandzeit mit Containerstart | 148,7 s; 148,3 s | 148,5 s; 155,6 s |
| davon INKAR laut Laufprotokoll | 127,6 s; 126,4 s | 125,8 s; 125,8 s |
| Rechnerlast 1/5/15 min davor | 4,11/3,24/2,64; 1,92/2,73/2,54 | 3,44/3,05/2,72; 2,59/2,97/2,75 |
| Rechnerlast 1/5/15 min danach | 1,92/2,73/2,54; 2,58/2,90/2,65 | 2,59/2,97/2,75; 1,55/2,41/2,58 |
| Lauf 1 | alles neu: 882 Gebäude, 413 Gemeinden, 18 Kreise, 413 + 413 Werte des Amts für Statistik, 62 929 INKAR-Werte | ebenso |
| Lauf 2 | alles unverändert (0 neu, 0 geändert, 0 gelöscht) | ebenso |
| Vergleich mit E51 | Abschnitte „Kennzahlen“ bis „table_metadata“ von `datenbank-auszug.txt` zeilengleich mit `pruefstand-2026-11-07-e51/pruefkonfiguration/` (`diff`); verschieden nur die Tabelle der Läufe (hier zwei) und Tabellengrößen in `pipeline_meta` | zeilengleich mit `pruefstand-2026-11-07-e51/mosidi-compose/` bis auf die Zeilen der Läufe |
| Doppelte Zielschlüssel | 0 | 0 |
| `table_metadata` | 14 Zeilen (9 INKAR, 2 Amt für Statistik, 3 LGB) | 14 Zeilen |
| Gebietsschlüssel mit Fläche | 413 von 413; Flächenprüfung Median 0,005 %, höchstens 0,398 % | ebenso |
| höchste Probe von `docker stats` | 300,9 MiB; 534,2 MiB (je 72 Proben, Median-Abstand 2,03 s) | nicht gemessen (wie bisher) |
| `memory.peak` der cgroup (Bytes → MiB) | 616 046 592 → 587,5 MiB; 610 725 888 → 582,4 MiB (Seitencache am Ende je 416,1 bzw. 416,3 MiB) | nicht gemessen |
| Katalog | Lauf 1: Hinweis „`public.source_granularities` gibt es in dieser Datenbank nicht“ (`ergebnis: fehlt`); Lauf 2 ohne Aufruf | **Lauf 1: „Katalog: public.source_granularities aktualisiert (gleichzeitig, Leser nicht blockiert)“**, im JSON `ergebnis: aktualisiert`, `verfahren: gleichzeitig`; View 0 → 11 Zeilen (9 INKAR, 2 Amt für Statistik); Lauf 2 ohne Aufruf, `katalog_offen` 0 |
| Warnungen | keine | keine |

**Überspringen unveränderter Dateien (E52) nicht im Spiel:** Der Schalter `unveraendert_ueberspringen` ist ausgeliefert
nur für `inkar_gemeinden` in `config/quellen.yaml` eingeschaltet, nicht in der Prüfkonfiguration. Lauf 2 beider Ordner
vergleicht deshalb voll (INKAR wieder rund 126 s); ein übersprungener Lauf ist hier nicht belegt, das zeigt der
Vollumfang (Lauf 2, Abschnitt „Vollumfang“).

**Compose von MOSIDI** ([`mosidi-compose/ablauf.txt`](mosidi-compose/ablauf.txt)): Klon von MOSIDI-ORG/MOSIDI,
**Commit `26cadbba3d6223c84872987104fc737359bf8bfc` vom 02.11.2026**, derselbe wie nach E46 bis E51. Benutzt sind die
unveränderte `docker-compose.yml` von MOSIDI und das Overlay
[`deploy/mosidi/docker-compose.pipeline.yml`](../../deploy/mosidi/docker-compose.pipeline.yml); die Läufe rufen wie
nach E51 `--config /app/config/pruefkonfiguration.yaml` auf, `pipeline-einrichten` den Standard des Overlays. Image
`geodaten-import-pipeline:e52-beleg`, `sha256:621d1f3f2de4…`.

| | |
|---|---|
| Unverändertes `brandenburg_db` auf frischem Volume | startet nicht: nach 30 s Status `restarting`, 9 Neustarts, PostgreSQL 18.6, Meldung „in 18+, these Docker images are configured to store database data in a format which is compatible with pg_ctlcluster …“ ([`befund-postgresql18.txt`](mosidi-compose/befund-postgresql18.txt)), wie seit dem 03.11. |
| Datenbank im Test-Override | PostgreSQL 18.6, PostGIS 3.6.4; Bestandsschema aus `sql/mosidi/001_bestand.sql` Rückgabe 0; View `source_granularities` wörtlich aus MOSIDI `services/backend/src/db_table_metadata/script.py`, Zeilen 262 bis 272, sha256 `7eec19e3…` (derselbe Ausschnitt wie nach E47 bis E51) |
| `pipeline-einrichten` | Rückgabe 0; Rollen `pipeline_import` und `mosidi_lesen` ohne Superuser-, CREATEDB- oder CREATEROLE-Recht; Eigentümer von View und Funktion `admin`, `SECURITY DEFINER` |
| Bestandsschema `public` (Antworten 27, 29) | `pg_dump --schema-only --no-privileges --no-owner` vor `einrichten` und nach Lauf 2 gleich: 2 527 Zeilen, sha256 `2a70acee…` (derselbe Wert wie nach E46 bis E51); in `public` 39 Tabellen, 2 Views, 1 Materialized View, 25 Sequenzen |

## Vollumfang `config/quellen.yaml`

Gestartet am 08.11.2026 um 23:44 MEZ, fertig am 09.11.2026 um 02:00 MEZ: drei Läufe wie nach E51, danach der
Wertabgleich je Zeile ([`quellen/`](quellen/), [`wertabgleich/ergebnis-vollumfang.txt`](wertabgleich/ergebnis-vollumfang.txt);
Skript unverändert aus [`../pruefstand-2026-11-07-e51/wertabgleich/`](../pruefstand-2026-11-07-e51/wertabgleich/)).
Teilbäume in [`quellen/ablauf.txt`](quellen/ablauf.txt) wie oben.

| | nach E52 (08./09.11.) | nach E51 (07.11.) |
|---|---|---|
| Lauf 1, Erstlauf (Bericht / Wandzeit) | 7 651,3 s (127,5 min) / 7 655,2 s, INKAR 7 631,7 s | 129,7 min, INKAR 7 765,5 s |
| Lauf 2, Folgelauf ohne Änderung | **172,7 s (2,9 min) / 177,4 s, INKAR 111,6 s, übersprungen** | 159,7 min, INKAR 9 493,0 s |
| Lauf 3, sofort danach | alle Quellen `nicht_faellig`, 0,05 s / 4,5 s | `nicht_faellig`, 0,1 s |
| Zählungen Lauf 1 | 882 / 413 / 18 / 413 / 413 / 33 547 606 neu, gleich wie nach E51 (`diff` der Berichtszeilen leer) | dieselben |
| Zählungen Lauf 2 | alles unverändert, 0 neu, 0 geändert, 0 gelöscht | dieselben |
| Wertabgleich je Zeile | **fehlend 0, überzählig 0, abweichend 0**; 33 547 606 verglichen, 0 doppelte Zielschlüssel; Ausgabe bis auf Zeitangaben gleich wie nach E51 | 0/0/0 |
| Speicher (`memory.peak`) | 549 MiB (Lauf 1), 596 MiB (Lauf 2) | 125 MiB, 458 MiB |
| Rückgaben | 0, 0, 0 | 0, 0, 0 |

Lauf 2 meldet für `inkar_gemeinden`: „unverändert (Datei byte-gleich, sha256 82f6923a4bdce8f3…): Quelle übersprungen,
nicht eingelesen und nicht verglichen, keine Schreibvorgänge in dashboard_data_de, Register und table_metadata“. Die
111,6 s sind Prüfsumme über die 434 MB große ZIP-Datei und die Zählprüfung des Registers (33 547 606 Zeilen). Die
übrigen fünf Quellen vergleicht Lauf 2 wie bisher voll.

**Speicher:** Der Anstieg sitzt in beiden Läufen genau in der Zeit, in der die Pipeline die Prüfsumme über die INKAR-Datei
bildet (Lauf 1: Proben 11 bis 34, rund 50 s, danach wieder rund 127 MiB). `pipeline/quellen.py` liest die Datei dafür in
Blöcken; am Ende von Lauf 2 stehen in `memory.stat` 0,4 MiB `anon` und 446 MiB `file`. Es ist also der Seitencache des
Betriebssystems für die gelesene Datei, den der Kernel bei Bedarf freigibt, kein Speicher der Pipeline. Dasselbe erklärt
Abweichung 1 unten (die Prüfkonfiguration liest dieselbe ZIP-Datei). Unter der Grenze von 1 GiB.

## Abweichungen von der Erwartung

Erwartet war: alle Rückgaben 0, Zählungen wie nach E51, Lauf 2 unverändert, 0 doppelte Zielschlüssel, im Compose der
Katalog gleichzeitig. **Das trifft ein.** Abweichungen:

1. **Speicher der Prüfkonfiguration höher als nach E51:** höchste Probe von `docker stats` 300,9 MiB (Lauf 1) und
   534,2 MiB (Lauf 2) gegen 123,0 MiB nach E51; `memory.peak` 587,5 und 582,4 MiB gegen 427,2 MiB, davon am Ende je rund
   416 MiB Seitencache. Die Proben steigen in beiden Läufen über mehrere Sekunden
   gleichmäßig an, es ist keine einzelne Spitze. Alles unter der Grenze von 1 GiB. Ursache nach dem Vollumfang
   eingegrenzt: Seitencache beim Bilden der Prüfsumme über die INKAR-Datei (Abschnitt Vollumfang).
2. **Compose, Lauf 2 länger:** 153,5 s statt 141,8 s nach E51; `gemeinden_lgb` brauchte 16,0 s statt rund 5 s (Tabelle
   der Läufe in `mosidi-compose/datenbank-auszug.txt`), die übrigen Quellen wie in Lauf 1. Ursache nicht gemessen.
3. **Kein Lauf von `config/deutschland.yaml`** an diesem Stand; Deutschland ist am Stand nach E51 belegt.

Kein Lauf hat `www.bbr-server.de` abgerufen.

## Was nicht geprüft ist

- Alles, was nach E51 nicht geprüft war (Abschnitt „Was nicht geprüft ist“ in
  [`../pruefstand-2026-11-07-e51/README.md`](../pruefstand-2026-11-07-e51/README.md)), soweit es dieser Prüfstand nicht
  ausdrücklich zeigt.
- Das Überspringen nach Ablauf von `vollabgleich_tage` und mit `--vollabgleich` gegen die echte INKAR-Datei; das
  prüfen die Tests, der Vollumfang hier zeigt nur das Überspringen innerhalb der Frist.
- Ein Folgelauf mit vollem Vergleich im Vollumfang (so läuft INKAR im monatlichen Rhythmus regulär, `docs/betrieb.md`,
  „Unveränderte Lieferung überspringen“): Lauf 2 hier hat INKAR übersprungen. Gemessen ist er nur nach E51 (159,7 min,
  INKAR 158,2 min gegen `zeitbudget_min: 240`).
- Die gleichzeitige Katalogaktualisierung nach einem Vollumfang (rund 33,5 Mio. Zeilen) und ihre Dauer; hier nur nach
  der Prüfkonfiguration (62 929 INKAR-Zeilen). Der Vollumfang lief wie nach E51 in einer Datenbank ohne
  `public.source_granularities` (Lauf 1: „Katalog nicht aktualisiert“).
- Der Plattenbedarf während der Läufe im Vollumfang; hier keine Plattenproben, nur die Größe danach (24 GB, wie nach E51,
  `quellen/datenbank-auszug.txt`).
- Gesamtzahl vor und nach dem Paging und Umfangssperre gegen einen echten Dienst, der sich während des Abrufs ändert;
  die Läufe hier hatten keinen solchen Fall, beides prüfen die Tests.

## Dateien

Wie nach E51: `lauf<n>.out` heißt hier `konsole-lauf<n>.txt`, `lauf<n>.err` (stderr, hier nur Meldungen von Compose)
`konsole-lauf<n>.err.txt`; Berichte und Quellenverzeichnis liegen direkt im jeweiligen Ordner statt unter
`berichte/`. Nicht beigelegt sind `build.log`, `schema-public-vorher.txt` und `schema-public-nachher.txt` (sha256 in
`mosidi-compose/ablauf.txt`). In `wertabgleich/` liegt nur das Ergebnis des Vollumfangs; das Skript `wertabgleich.py`
liegt unverändert im Prüfstand nach E51, die Ausfuhr der Zieltabelle (`werte-nach-lauf1.csv.gz`, sha256 in der Kopfzeile
des Ergebnisses) enthält Werte und liegt nicht bei.

**Die Änderungskarten (`*-karte.html`) liegen nicht bei**, ebenso wenig die XLSX des Amts und die INKAR-Datei. Sie
enthalten die importierten Geodaten und Datensätze; Quelldaten werden nicht mit dem Code veröffentlicht (Antwort 69).
Die Berichte nennen die Karte nur mit Namen. Die Datenbankauszüge nennen Zählungen, Indikatornamen und Schlüssel, keine
Werte.

## Stand

- **Teilbäume** (in den drei `ablauf.txt`, von den Skripten aus einer Kopie des Index berechnet; nach den Läufen mit
  `git write-tree` des Index gegengeprüft, gleich): `pipeline` `57345c03f9dbfdba04bb2af364417e41c4b307f1`, `config`
  `14a2c8cadf76296bfedcd65591ddb932f2cfa3e4`, `sql` `12f6a2f9ddc7ea7fc3019f8dc6fd2a04ffe18748`, `tests`
  `48bce8345fc2a2f72cc1c89793225b38e4f2358c`, `Dockerfile` `6788a7afeb4041d3c71b517b184d557c44c99762`, `deploy`
  `d91e6a887a2f02e76d5135f13fe09b7156daec1d`. `requirements.txt` steht nicht in `ablauf.txt`; sein Blob im Index ist
  `3edf4ee3e318de51d0094b6ad08cbc7ddeed8191`, unverändert seit E49. `Dockerfile` ebenso unverändert seit E49.
- **Code eingefroren:** Während dieses Prüfstands ist an `pipeline`, `tests`, `config`, `sql`, `Dockerfile`, `deploy` und
  `requirements.txt` nichts geändert; dazugekommen sind dieser Prüfstand und Dokumentation (README, README.en,
  `docs/anforderungen.md`, `docs/belege.md`, `docs/belege.en.md`, `docs/entscheidungen.md`, `docs/betrieb.md`,
  `docs/rundgang.md`, `docs/codekarte/README.md`, `beispielberichte/README.md` und ein Hinweis am Anfang des READMEs
  des Prüfstands nach E51).
- **Reihenfolge** (MEZ, 08.11.2026): Prüfkonfiguration 23:16 bis 23:22, Compose-Lauf 23:22 bis 23:28, Vollumfang 23:44 bis
  02:00 (09.11.), Wertabgleich danach. Die Zeitpunkte von `pruefen.sh` und den Datenbanktests sind in den Protokollen nicht festgehalten.
- **Nachprüfbar** nach dem Taggen mit `git rev-parse <tag>:pipeline` usw.; weichen die Teilbäume ab, gelten diese
  Belege nicht für den Tag (E45, P14).
