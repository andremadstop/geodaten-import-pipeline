# Prüfstand 05.11.2026, Stand nach E46 (Tests, Läufe gegen die echten Dienste, Lauf im Compose von MOSIDI)

> **Abgelöst durch [`../pruefstand-2026-11-05-e47/`](../pruefstand-2026-11-05-e47/)** (Stand nach E47, letzte Läufe,
> `docs/entscheidungen.md` E47; Abgabestand ist der Stand nach E48): Tests, Belegläufe Brandenburg und Deutschland und der Lauf im Compose von MOSIDI sind
> dort am Stand nach E47 wiederholt, mit denselben Zählungen (dort mit Rückgabe 1 wegen der Flächentabelle der
> Regionaldatenbank und ohne die Kürzung von `aktualit`). Dieser Ordner bleibt als Beleg des Stands nach E46; seine
> Laufzeiten, Speicherwerte und Teilbäume gelten nur für diesen Stand. „Abgabestand“ meint in diesem Ordner den Stand
> nach E46.

Das war der Prüfstand des damaligen Abgabestands, des zu taggenden Stands `angebot-va-2026-536` (E43), nach den Code-Befunden
des unabhängigen Prüfberichts vom 05.11.2026 und der Nachprüfung dazu (E46 in
[`docs/entscheidungen.md`](../../docs/entscheidungen.md)): Katalog `source_granularities` nach jedem Lauf mit
Änderungen, Metadatenkonflikt hält die Quelle vor dem Schreiben an, Übernahme vorhandener Zeilen fachlich gezählt,
Reparatur, Transformation und Zieltyp der Geometrie je Objekt, WFS ohne Gesamtzahl bis zur leeren Seite, Sperre auch
datenbankweit, Schreibrechte auf dem Sollstand; aus der Nachprüfung (N1 bis N12) das Nachholen einer gescheiterten
Katalogaktualisierung (`pipeline_meta.katalog_offen`), Warnung statt Abbruch bei fremd vergebenen Schreibrechten,
Sequenzrechte, Eigentümer der Katalogfunktion, einzeilige Fehlertexte für `--status`, Sperrmeldung mit der haltenden
Sitzung.

Alles in diesem Ordner ist am selben Stand entstanden (Teilbäume unten, in den Kopfzeilen der Protokolle und in jeder
`ablauf.txt`): die Tests, die Belegläufe Brandenburg und Deutschland gegen die echten Dienste und die Wiederholung des
Laufs im Compose-Setup von MOSIDI vom 03.11., diesmal mit der Katalogaktualisierung aus E46 gegen die View
`source_granularities` in der Fassung aus dem MOSIDI-Repository. Dieser Prüfstand löst
[`../pruefstand-2026-11-05-e45/`](../pruefstand-2026-11-05-e45/) ab; alle Zählungen der Läufe sind dieselben wie dort.

## Prüfkette

| Prüfung | Ergebnis | Protokoll |
|---|---|---|
| `pruefen.sh` (ruff, bandit, pip-audit, Tests ohne Datenbank, Secret-Scan, Stückliste); Zeitpunkt und Teilbäume in der Kopfzeile | ohne Befund, 168 Tests bestanden (die 47 Datenbanktests dort übersprungen, sie laufen getrennt); bandit gibt nur eine Warnung aus, dass ein `nosec` in `pipeline/quellen.py` keinen Treffer mehr unterdrückt | [`pruefen.log`](pruefen.log) |
| `tests/test_datenbank.py` gegen eine echte PostGIS-Datenbank mit den MOSIDI-Tabellen, `postgis/postgis:16-3.6` (festgeschrieben); Teilbäume in der Kopfzeile | PostgreSQL 16.15: 47 von 47 | [`datenbanktests.log`](datenbanktests.log) |
| dieselben Tests, `postgis/postgis:latest` | PostgreSQL 18.6: 47 von 47 | [`datenbanktests.log`](datenbanktests.log) |

Die Datenbanktests liefen je Version in einem frischen Wegwerf-Compose-Projekt aus der `docker-compose.yml` dieses
Repositorys mit zufälligen Passwörtern, beide gleichzeitig; Container und Volumes sind danach entfernt. Die
Projektnamen `gip-e42-pg16-…` und `gip-e42-pg18-…` in `datenbanktests.log` sind nur ein Präfix aus dem Aufruf und
sagen nichts über den geprüften Stand; maßgeblich sind die Teilbäume in der Kopfzeile. `pruefen.log` stammt aus dem
letzten Lauf nach dem Stagen dieses Ordners und der Dokumentation.

## Belegläufe gegen die echten Dienste

**Rahmen.** Alle Läufe liefen auf einem Entwicklungsrechner (Linux, Docker, 16 Kerne), der währenddessen auch für
andere Arbeit genutzt wurde. Vor dem Start war die 1-Minuten-Last 2,09 (Grenze für einen Start: 8; gewartet werden
musste nicht). Während der Läufe Brandenburg und Deutschland lag sie zwischen 2,76 und 6,71, im Compose-Lauf von
MOSIDI zwischen 4,58 und 13,16 (nach dessen zweitem Lauf). Die Last vor und nach jedem Lauf steht in `*/ablauf.txt`.
Es gibt eine Reihe; die Laufzeiten sind Größenordnungen, keine Messung auf einem ruhigen Rechner. Brandenburg liegt
unter der Spanne der beiden Reihen nach E45 (bei höherer Last), Deutschland im Erstlauf darunter, im Folgelauf
gleichauf (260,4 gegen 259,9 s in Reihe A); dass E46 schneller wäre, ist damit nicht belegt (E46 kostet je Objekt mit
Geometrie einen Sicherungspunkt mehr und bei WFS ohne Gesamtzahl eine Abfrage mehr).

Die Datenbank war jeweils frisch, in einem Wegwerf-Compose-Projekt aus der `docker-compose.yml` dieses Repositorys
(PostgreSQL 16.15, PostGIS 3.6.4, Schema der MOSIDI-Tabellen aus `sql/mosidi/`). Die Zugangsdaten wurden zufällig
erzeugt und danach gelöscht, Container und Volumes sind entfernt. Die Pipeline lief als Container aus dem Image dieses
Stands (`geodaten-import-pipeline:e46-beleg`, je Konfiguration neu gebaut, beide Male dieselbe Image-ID
`sha256:cdc6f2ce…`) mit `mem_limit: 1g` wie in der Compose-Datei. Ablauf: [`beleg.sh`](beleg.sh) (die Fassung aus
dem Prüfstand nach E45, nur Kopf und Imagename angepasst), aufgerufen als `beleg.sh quellen <Ordner> --alle -- --alle
-- .` und `beleg.sh deutschland <Ordner> --alle -- --alle`, nacheinander.

Laufzeiten auf eine Nachkommastelle gerundet (kaufmännisch; die Rohwerte stehen in den Berichten, etwa 112,25 s
→ 112,3 s und 46,35 s → 46,4 s).

| | Brandenburg (`config/quellen.yaml`) | Deutschland (`config/deutschland.yaml`) |
|---|---|---|
| Läufe | [`brandenburg/`](brandenburg/): `20261105T173642Z` `--alle`, `20261105T173837Z` `--alle`, `20261105T174032Z` ohne `--alle` | [`deutschland/`](deutschland/): `20261105T174054Z` `--alle`, `20261105T174529Z` `--alle` |
| Zeit (MEZ) | 18:36 bis 18:40 | 18:40 bis 18:50 |
| Laufzeit laut Bericht | **Erstlauf 112,6 s, Folgelauf 112,3 s**, dritter Lauf 0,03 s (alle sechs Quellen „nicht fällig“) | **Erstlauf 272,6 s, Folgelauf 260,4 s** |
| Wandzeit mit Containerstart | 114,8 s; 114,3 s; 1,6 s | 274,5 s; 262,1 s |
| davon INKAR laut Laufprotokoll | 95,0 s; 96,3 s | 227,8 s; 214,0 s (VG250: 44,8 s; 46,4 s) |
| Rechnerlast 1/5/15 min vor dem Lauf | 2,76/2,93/4,69; 3,32/3,09/4,54; 6,71/4,25/4,79 | 5,76/4,20/4,76; 4,06/3,87/4,47 |
| Rechnerlast 1/5/15 min nach dem Lauf | 3,32/3,09/4,54; 6,71/4,25/4,79; 6,71/4,25/4,79 | 4,06/3,87/4,47; 3,96/4,00/4,38 |
| Geometrien | 882 Gebäude, 413 Gemeinden, 18 Kreise | 11 103 Gemeindeflächen (VG250-WFS des BKG) |
| INKAR nach `dashboard_data_de` | 62 929 Zeilen neu, im zweiten Lauf 62 929 unverändert; Zeitbezug 1995 bis 2023 | 1 640 420 Zeilen neu, im zweiten Lauf 1 640 420 unverändert; Zeitbezug 1995 bis 2023 |
| INKAR-Indikatornamen (Regel aus E40) | 9, davon 5 mit Bereich „(LRB)“ (51 477 der 62 929 Zeilen) | dieselben 9 (1 345 471 der 1 640 420 Zeilen mit Bereich) |
| Zeilen verworfen oder zusammengeführt wegen gleichen Zielschlüssels | 0 (keine Quelle angehalten; INKAR gelesen = neu = 62 929) | 0 (gelesen = neu = 1 640 420) |
| Doppelte Zielschlüssel in `dashboard_data_de` | 0 | 0 |
| Übernommene Zeilen (E46: fachlich gezählt) | 0 in allen Quellen und Läufen (frische Datenbank) | 0 |
| Register `pipeline_meta.bestand`, INKAR | 62 929 Zeilen, 62 929 mit Quellschlüssel, alle verschieden | 1 640 420 Zeilen, 1 640 420 mit Quellschlüssel, alle verschieden |
| Amt für Statistik | 1 239 Bevölkerungs- und 413 Flächenwerte (zusammen 1 652 Zeilen, 4 Indikatoren, Stichtag 2025), `data_type = indikator` | – |
| `table_metadata` | 16 Zeilen (9 INKAR, 4 Amt für Statistik, 3 LGB) | 10 Zeilen (9 INKAR, 1 BKG) |
| Gebietsschlüssel mit Fläche | 413 von 413 | 10 946 von 10 978; die 32 übrigen haben keine Fläche in der VG250; als Ursache ist der Gebietsstand 2023 von INKAR zu prüfen (der Bericht nennt die ersten zehn) |
| Flächenprüfung | 413 Gemeinden, Median 0,005 %, höchstens 0,161 % (gerundet 0,16 %), Toleranz 0,5 % | – |
| Katalog (E46) | Erstlauf: Hinweis „`public.source_granularities` gibt es in dieser Datenbank nicht“ (das Schema aus `sql/mosidi/` enthält die View nicht), Bericht `katalog.ergebnis = fehlt`; Folgeläufe ohne Änderung ohne Aufruf | ebenso |
| höchste Probe von `docker stats` | 131,4 MiB (56 Proben); 130,9 MiB (56 Proben); dritter Lauf ohne Probe | 129,5 MiB (135 Proben); 365,9 MiB (129 Proben) |
| `memory.peak` der cgroup (Bytes → MiB) | 611 590 144 → 583,3 MiB; 182 562 816 → 174,1 MiB; dritter Lauf 36 024 320 → 34,4 MiB | 138 244 096 → 131,8 MiB; 384 405 504 → 366,6 MiB |
| Datenbank danach | 74 MB | 1 132 MB (`pipeline_meta.bestand` 564 MB, `pipeline_meta.aenderung` 307 MB, `dashboard_data_de` 209 MB, `"Kommunale Gebiete Deutschland"` 35 MB) |

Alle fünf Läufe endeten mit Rückgabe 0, ohne fehlgeschlagene, angehaltene oder unvollständige Quelle; kein
Metadatenkonflikt (keine Warnung „nicht angelegt“). Alle Zahlen sind aus den Rohdateien in diesem Ordner
nachgerechnet: Laufzeiten aus den Berichten (`*.txt`, `*.json`) und `ablauf.txt`, Zählungen aus
`datenbank-auszug.txt` und den Zählern in den Berichten, Speicher aus `speicher-lauf<n>.txt` und der Zeile
`cgroup memory.peak` in `konsole-lauf<n>.txt`. Die Datenbankauszüge sind bis auf das Laufprotokoll (Laufkennungen und
Dauer je Quelle) und die neue Tabelle `pipeline_meta.katalog_offen` (32 kB, Nachprüfung N5) unter „Größen“ gleich
denen in Reihe B des Prüfstands nach E45 (zeilenweise verglichen).

**Warnungen und Hinweise** wie nach E45 (in beiden vollen Brandenburg-Läufen gleich, in den Deutschland-Läufen keine
Warnung): `bevoelkerung_gemeinden` 21 und `flaeche_gemeinden` 7 Zeilen ohne jeden Wert ausgelassen (7 Gemeindeschlüssel,
die die Regionaldatenbank nur mit „-“ führt, Ursache je Schlüssel zu prüfen; ihr bisheriger Stand bleibt, im
Laufprotokoll unter „gelesen“ 420); `alkis_gebaeude_thb` 882 Objekte mit `aktualit` länger als 10 Zeichen (11), gekürzt
gespeichert (Befund am Schema `varchar(10)`, Arbeitspaket 1).
Hinweise: WFS der LGB `ImplementsResultPaging=FALSE` (Kachelung), VG250-WFS `ImplementsSorting=FALSE`, INKAR-Datei
unverändert seit dem letzten Abruf. Neu ist nur der Katalog-Hinweis oben.

**Speicher, Messverfahren** wie nach E45: `docker stats --no-stream` in einer Schleife mit 1 s Pause (Median des
Probenabstands je Lauf 2,03 s; `docker stats` zeigt den Speicher der cgroup ohne inaktiven Seitencache) und am Ende
jedes Laufs `/sys/fs/cgroup/memory.peak` (Höchststand des Kernels einschließlich Seitencache; für die Grenze von 1 GB
zählt dieser Wert). Der höchste ist 583,3 MiB (Brandenburg, Erstlauf; nach E45 565,2 MiB), in Deutschland 366,6 MiB.
Der dritte Brandenburg-Lauf ist kürzer als ein Probenabstand; seine Probendatei enthielt nur die Kopfzeile und liegt
nicht bei.

**Abweichung beim Speicher, Ursache nicht belegt.** Im Deutschland-Folgelauf steigt die höchste Probe von
`docker stats` auf 365,9 MiB (nach E45 94,0 und 97,6 MiB). Der Verlauf in `deutschland/speicher-lauf2.txt`: rund
80 bis 90 MiB während VG250, ab etwa 60 s (INKAR) Anstieg auf rund 363 MiB, dort bis zum Ende. `memory.peak` ist
366,6 MiB, am Ende stehen 283,7 MiB Seitencache (`file` in `memory.stat`, erst nach dem Ende des Python-Prozesses
gelesen). Seitencache am Ende erklärt die hohe Probe nicht allein: Im Prüfstand nach E45 hatte derselbe Lauf in Reihe
A 373,7 MiB `file` am Ende und trotzdem nur 94,0 MiB höchste Probe. Wie viel davon Speicher des Prozesses ist, zeigen
die Messungen nicht. Seitencache am Ende der übrigen Läufe: Brandenburg 415,9, 8,6 und 0,3 MiB, Deutschland 53,5 und
283,7 MiB. `memory.peak` bleibt in allen Läufen unter 60 % der Grenze.

## Lauf im Compose-Setup von MOSIDI (Wiederholung des Laufs vom 03.11.)

Ordner [`mosidi-compose/`](mosidi-compose/), Ablauf [`mosidi-compose/lauf.sh`](mosidi-compose/lauf.sh), 18:50 bis
18:55 MEZ. MOSIDI-ORG/MOSIDI lag lokal nicht vor (gesucht in den Arbeitsverzeichnissen), es wurde öffentlich geklont
(`git clone --depth 1`): Commit `26cadbba3d6223c84872987104fc737359bf8bfc` vom 02.11.2026, derselbe wie am 03.11.
Benutzt sind die unveränderte `docker-compose.yml` von MOSIDI und das Overlay
[`deploy/mosidi/docker-compose.pipeline.yml`](../../deploy/mosidi/docker-compose.pipeline.yml), so wie
[`deploy/mosidi/README.md`](../../deploy/mosidi/README.md) es beschreibt, mit eigenem Compose-Projektnamen
(`gip-mosidi-e46-<pid>`), zufälligen Passwörtern und danach `down -v` (keine Container, Volumes oder `.env` übrig).

Abweichungen vom unveränderten Compose, alle im Test-Override von `lauf.sh`:

- `brandenburg_db`: Volume unter `/var/lib/postgresql` statt `/var/lib/postgresql/data` (wie am 03.11., sonst startet
  PostgreSQL 18 nicht, siehe unten), keine Freigabe von Port 5432 nach außen (wie am 03.11.), eigener Containername
  statt des festen `brandenburg_db` (damit nichts Fremdes getroffen wird; der Dienstname bleibt `brandenburg_db`).
- Pipeline-Dienste: Image `geodaten-import-pipeline:e46-beleg` (ID in `mosidi-compose/ablauf.txt`, dasselbe wie in
  den Belegläufen) statt des Tags `:lokal` aus dem Overlay, der älter war als dieser Stand; Berichtsordner im
  Ausgabeordner statt im Repository (die Kartenseiten liegen nicht bei).
- `.env` von MOSIDI: `POSTGRES_DB=brandenburg` (wie in der MOSIDI-README), `POSTGRES_USER=admin`, die Passwörter
  zufällig; `pg_tileserv.env` leer. Compose warnt deshalb, dass `GEOSERVER_ADMIN` und `GEOSERVER_PASSWORD` nicht
  gesetzt sind (in `konsole-lauf<n>.err.txt` und `einrichten.log`; nur die Namen, keine Werte); GeoServer startet
  nicht mit.
- Datenbank: PostgreSQL 18.6, PostGIS 3.6.4 (`postgis/postgis` ohne Tag, wie in MOSIDI), anders als in den
  Belegläufen oben (16.15).
- Testaufbau der Datenbank: Schema der Bestandstabellen aus `sql/mosidi/001_bestand.sql` (wie am 03.11.), danach als
  Administrator die Materialized View `source_granularities` mit ihren beiden Indizes, wörtlich aus MOSIDI
  `services/backend/src/db_table_metadata/script.py`, Zeilen 262 bis 272 (sha256 des Ausschnitts in `ablauf.txt`).
  So legt sie auch das Backend von MOSIDI an. Sie steht nicht in `sql/mosidi/` und ist dort nicht nachgetragen.

Ergebnis:

| | |
|---|---|
| Unverändertes `brandenburg_db` auf frischem Volume | startet nicht: nach 30 s Status `restarting`, 9 Neustarts, Meldung „in 18+, these Docker images are configured to store database data in a format which is compatible with pg_ctlcluster …“ ([`befund-postgresql18.txt`](mosidi-compose/befund-postgresql18.txt), die erste Meldung und der Anfang der Wiederholung), wie am 03.11. |
| `pipeline-einrichten` | Rückgabe 0; Rollen `pipeline_import` und `mosidi_lesen` ohne Superuser-, CREATEDB- oder CREATEROLE-Recht; Spaltenrechte in [`einrichten.log`](mosidi-compose/einrichten.log); keine Warnung zur Katalogfunktion (Eigentümer von View und Funktion ist `admin`, `SECURITY DEFINER`) |
| Lauf 1 `--alle` (`20261105T175111Z`) | Rückgabe 0, 110,1 s laut Bericht (Wandzeit 111,7 s), INKAR 95,9 s; 882 Gebäude, 413 Gemeinden, 18 Kreise, 1 239 + 413 Werte des Amts für Statistik, 62 929 INKAR-Werte; **„Katalog: public.source_granularities aktualisiert“**, die View hatte vorher 0 Zeilen, danach 13 (9 INKAR, 4 Amt für Statistik, Gemeindeebene) |
| Lauf 2 `--alle` (`20261105T175303Z`) | Rückgabe 0, 131,9 s laut Bericht (Wandzeit 133,7 s; 1-Minuten-Last danach 13,16), INKAR 117,6 s; alles unverändert, kein Aufruf des Katalogs, `pipeline_meta.katalog_offen` leer, View weiter 13 Zeilen |
| Datenbank danach | 0 doppelte Zielschlüssel, `table_metadata` 16 Zeilen, in `public` 39 Tabellen, 2 Views, 1 Materialized View, 25 Sequenzen ([`datenbank-auszug.txt`](mosidi-compose/datenbank-auszug.txt)) |
| Bestandsschema `public` (Antworten 27, 29) | `pg_dump --schema-only --schema=public --no-privileges --no-owner` vor `einrichten` und nach Lauf 2 gleich (2 527 Zeilen, sha256 in `ablauf.txt`; die beiden Dumps liegen nicht bei, sie enthalten das Schema aus `sql/mosidi/` und die View). Die Rechte in `public` ändert `einrichten` wie vorgesehen (Grants an die beiden Rollen, `einrichten.log`); sie sind in diesem Vergleich ausgenommen |

Der Abschnitt „Schreibrechte“ im Datenbankauszug zählt nur Rechte auf ganze Tabellen (SELECT auf 5, DELETE auf
`dashboard_data_de`); INSERT und UPDATE vergibt `einrichten` spaltenweise, sie stehen in `einrichten.log`. Gegenüber
dem Lauf vom 03.11. ([`../mosidi-compose/`](../mosidi-compose/)): INKAR 62 929 statt 57 259 Zeilen (Schlüssel seit
E40), `table_metadata` 16 statt 14 Zeilen, dazu die Katalogaktualisierung; sonst dieselben Zählungen.

**Zur Definition der View.** E46 und die Datenbanktests gehen davon aus, dass die Definition von
`source_granularities` nicht bekannt ist, und nutzen eine Ersatz-View `SELECT DISTINCT source, granularity`. Die
öffentliche Fassung in MOSIDI (Zeilen oben) ist `SELECT DISTINCT source, indikator, granularity FROM
dashboard_data_de` mit einem eindeutigen Index auf allen drei Spalten; MOSIDI selbst aktualisiert sie mit
`REFRESH MATERIALIZED VIEW CONCURRENTLY`. Die Pipeline aktualisiert ohne `CONCURRENTLY` (Code unverändert); der Lauf
oben zeigt, dass das mit der echten Definition funktioniert. Vermerk in E46 („Belege am Endstand“, „Grenzen“).

## Was nicht geprüft ist

- Der Download der INKAR-Datei: In allen Läufen lag sie im Zwischenspeicher (`cache/inkar_2025.zip`, 434 MB, Stand
  13.08.2025), das BBSR meldete sie als unverändert.
- Alle 264 INKAR-Kürzel: Beide Konfigurationen laden fünf (Gesamtanalyse ohne Datenbanklauf in
  [`../inkar-schluessel/`](../inkar-schluessel/)).
- Ein Änderungslauf mit echten Änderungen und eine Übernahme vorhandener Zeilen: Die Folgeläufe hier sind „alles
  unverändert“, die Datenbanken frisch. Neu, geändert, gelöscht, Übernahme, Kürzel- und Stichtagwechsel prüfen die
  Datenbanktests.
- Die Fehlerpfade aus E44 bis E46 (Abriss der Datenbank, Metadatenkonflikt, gescheiterte Katalogaktualisierung,
  datenbankweite Sperre, fremd vergebene Rechte, Geometrie mit anderem Typ, WFS mit Seitenlimit): In diesen Läufen trat
  keiner auf; sie prüfen die Tests.
- Im Compose von MOSIDI: Speicher (nicht gemessen), `--haerten`, die übrigen Dienste von MOSIDI (Backend, Frontend,
  GeoServer, nicht gestartet), eine bestehende Datenbank der TH mit Daten und eigenen Rechten, und ob dort der
  Eigentümer der Funktion die echte View aktualisieren darf (hier legte derselbe Administrator beide an).
- Die Laufzeit auf einem ruhigen oder dem Zielrechner.

## Dateien

**Abweichungen der Dateien hier von den Ausgaben der Skripte:** `lauf<n>.out` heißt hier `konsole-lauf<n>.txt`,
`lauf<n>.err` (stderr des Aufrufs, hier nur Meldungen von Compose) heißt `konsole-lauf<n>.err.txt`. Berichte und
Quellenverzeichnis liegen direkt im jeweiligen Ordner statt unter `berichte/`. Nicht beigelegt sind `build.log`,
`einrichten.log` der Belegläufe, `speicher-lauf3.txt` (Brandenburg, nur Kopfzeile), `schema-public-vorher.txt` und
`schema-public-nachher.txt` (Compose-Lauf). Alle beigelegten Rohdateien (46: Brandenburg 18, Deutschland 14,
Compose 14) sind byte-gleich mit den Rohausgaben (byteweise verglichen am 05.11.2026).

**Die Kartenseiten liegen nicht bei.** Sie enthalten die importierten Datensätze; Quelldaten werden nicht mit dem Code
veröffentlicht (Antwort 69). Die Datenbankauszüge nennen Zählungen und Beispiele des Registers nur als Schlüssel,
ohne Werte.

## Stand

- **Teilbäume** (`git write-tree` des Index nach dem Stagen, vor und nach dieser Dokumentation gleich): `pipeline`
  `3506513c6d779d0a9f25539a90418b2376dfa85f`, `config` `6510e0fd75b97eb06e0d1a402e50a19fe34011c2`, `sql`
  `c7062db0702a61378d36debc27207f3244556ab4`, `tests` `6a83729739340314b33e4bd93e17b87bae2449eb`, `Dockerfile`
  `2953066ba034c0772b8647fcb89c9a710cb5028a`. Dieselben stehen in den Kopfzeilen von `pruefen.log` und
  `datenbanktests.log` und, von den Skripten über eine Kopie des Index aus dem Arbeitsstand berechnet, aus dem das
  Image gebaut wurde, in allen drei `*/ablauf.txt`. Gegenüber dem Prüfstand nach E45 sind `pipeline`, `config` (nur
  ein Kommentar in `beispiel-paging.yaml`, E46 N4), `sql` und `tests` neu, `Dockerfile` ist gleich.
- **Overlay für MOSIDI:** `mosidi-compose/ablauf.txt` nennt zusätzlich den Teilbaum `deploy` zur Zeit des Laufs
  (`4ed32ed9…`). Er ändert sich danach durch diese Dokumentation (`deploy/mosidi/README.md`); die benutzte Datei
  `deploy/mosidi/docker-compose.pipeline.yml` ist unverändert (Blob `89dd61692c53fc0b39269dc1bcf1e3645be6ecea`).
- **Nachprüfbar** nach dem Taggen mit `git rev-parse angebot-va-2026-536:pipeline` usw. Unmittelbar vor dem Taggen
  sind die Teilbäume mit `git write-tree` neu zu berechnen; weichen sie ab, gelten diese Belege nicht für den Tag
  (E45, P14).
- **Reihenfolge am 05.11.2026:** Datenbanktests 18:26 bis 18:29 MEZ, `pruefen.sh` bis 18:32, Belegläufe Brandenburg
  18:36 bis 18:40 und Deutschland 18:40 bis 18:50, Compose-Lauf von MOSIDI 18:50 bis 18:55. Danach kamen nur
  Dokumentation und diese Belege dazu; `pruefen.sh` lief danach erneut nach dem letzten Stagen (`pruefen.log`, Endzeit
  in der Kopfzeile, gleiches Ergebnis wie um 18:32).
