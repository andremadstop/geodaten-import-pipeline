# Prüfstand 06.11.2026, Abgabestand nach E49 (Tests, Läufe gegen die echten Dienste, Lauf im Compose von MOSIDI)

> **Abgelöst durch [`../pruefstand-2026-11-06-e50/`](../pruefstand-2026-11-06-e50/)** (06.11.2026): Abgabestand ist jetzt
> der Stand nach E50 (Code geändert, `docs/entscheidungen.md`, E50). Tests, Läufe gegen die echten Dienste und der Lauf im
> Compose von MOSIDI sind dort am Stand nach E50 wiederholt, dazu ein Lauf im INKAR-Vollumfang. Dieser Prüfstand bleibt als
> Beleg des Stands nach E49; seine Teilbäume `pipeline`, `tests` und `config` gelten nur für jenen Stand. `beleg.sh` und
> `mosidi-compose/lauf.sh` sind mit `git mv` nach e50 und weiter nach e51 verschoben (heute [`../pruefstand-2026-11-07-e51/`](../pruefstand-2026-11-07-e51/), Abgabestand nach E51) und dort angepasst; was sich gegenüber der hier
> benutzten Fassung geändert hat, nennt der Kopf beider Skripte (Imagename, Projektname, Namensauflösung im Container,
> eigene Prüfkonfiguration). „Abgabestand“ im Text unten heißt der Stand nach E49.

Das ist der Prüfstand des Abgabestands (Tag `angebot-va-2026-536`, E43): Stand nach E49. Am Code ist das der Stand
nach E48 (Statistik des Amts für Statistik als XLSX, robots.txt je Rechner, Sperrliste im Code) bis auf die
Namensnennung von basemap.de in `pipeline/karte.py` (Attributionstext; im `nur-kommentare.log` als „AUSSERHALB E49“
geführt); E49 hat nur Kommentare und Docstrings ergänzt. Dass E49 am Code nichts geändert hat, belegt
[`nur-kommentare.py`](nur-kommentare.py) mit dem Protokoll [`nur-kommentare.log`](nur-kommentare.log) (unten, „Stand“).

Alles in diesem Ordner ist am selben Code-Stand entstanden (Teilbäume unten, in den Kopfzeilen der Protokolle und in
jeder `ablauf.txt`): die Tests, die Belegläufe `config/quellen.yaml` und `config/deutschland.yaml` gegen die echten
Dienste und die Wiederholung des Laufs im Compose-Setup von MOSIDI mit der Katalogaktualisierung gegen die View
`source_granularities` in der Fassung aus dem MOSIDI-Repository. Er löst
[`../pruefstand-2026-11-05-e47/`](../pruefstand-2026-11-05-e47/) (letzte Läufe vor E48) und die Testprotokolle in
[`../pruefstand-2026-11-06-e48/`](../pruefstand-2026-11-06-e48/) ab; die Läufe, die nach E48 noch fehlten, sind hier
nachgeholt.

**Gegenüber dem Prüfstand nach E47:** Alle Läufe enden mit Rückgabe 0 (nach E47 endeten die Brandenburg- und
Compose-Läufe mit 1 wegen der Flächentabelle der Regionaldatenbank; dieser Befund ist mit E48 gegenstandslos).
Bevölkerung und Fläche kommen aus dem XLSX-Bericht des Amts für Statistik: 413 + 413 = 826 Werte statt 1 239 + 413.
INKAR kommt nur aus der abgelegten Datei; kein Lauf hat `www.bbr-server.de` oder `www.regionalstatistik.de`
abgerufen. Geometrien, INKAR und alle Deutschland-Zahlen sind dieselben wie nach E47.

## robots.txt je Rechner

Vor den Läufen ist für jeden Rechner, den ein Lauf, der Bau des Images oder der Klon von MOSIDI abruft, einmal die
`robots.txt` abgerufen worden (06.11.2026, 10:52 UTC, 11:52 MEZ; je eine Anfrage, `curl`). Die Regeln sind gegen die
tatsächlich abgerufenen Pfade geprüft (Platzhalter `*` und `$` wie in RFC 9309, längste passende Regel gewinnt).
Antwortet ein Rechner auf `/robots.txt` mit einem Status 4xx, gilt die Datei nach RFC 9309 (Abschnitt 2.3.1.3) als
nicht vorhanden; dann gibt es keine Einschränkung.

| Rechner | Wofür | `robots.txt` | Ergebnis |
|---|---|---|---|
| `isk.geobasis-bb.de` | WFS der LGB: Gebäude, Gemeinden, Kreise (`quellen.yaml`) | 404 | erlaubt (RFC 9309: keine Datei, keine Einschränkung) |
| `www.statistik-berlin-brandenburg.de` | Seite des Statistischen Berichts A I 4 / A V 2 (`quellen.yaml`, `seite`) | `Disallow: /scrivito/` | `/a-i-4-a-v-2-j/` erlaubt |
| `download.statistik-berlin-brandenburg.de` | XLSX-Datei des Berichts (`link_rechner`) | 403 des Speichers | erlaubt (RFC 9309: Status 4xx heißt „nicht verfügbar“, kein Verbot) |
| `sgx.geodatenzentrum.de` | VG250-WFS des BKG (`deutschland.yaml`) | `Disallow: /gdz_geoviewserver/`, `/gdz_geoviewserv/` | `/wfs_vg250` erlaubt |
| `www.bbr-server.de` | INKAR (`quellen.yaml`, `deutschland.yaml`) | `Disallow: /` | **gesperrt, nicht abgerufen** (nur die `robots.txt`). INKAR kommt aus `cache/inkar_2025.zip` per `PIPELINE_INKAR_DATEI` (schreibgeschützt eingehängt); der Rechner steht in `ROBOTS_GESPERRT` im Code und löst im Container auf `0.0.0.0` auf. In den Berichten steht seine Adresse nur als konfigurierte `adresse` im Quellenverzeichnis, nie als `letzte_abfrage` |
| `www.regionalstatistik.de` | nirgends konfiguriert (bis E47 Bevölkerung und Fläche) | `Disallow: /` (Prüfung zu E48) | **gesperrt, nicht abgerufen**, auch nicht die `robots.txt`; im Code gesperrt (`ROBOTS_GESPERRT`), im Container auf `0.0.0.0` |
| `pypi.org` | Paketindex: Bau des Images (`pip install --require-hashes`), `pruefen.sh` (uv, uvx, pip-audit) | `Disallow: /simple/`, `/packages/`, `/pypi/*/json` u. a. | genutzt als dokumentierte Paketschnittstelle für Installer (E49, „PyPI und robots.txt“): Die Acceptable Use Policy von PyPI sagt „Scraping does not refer to the collection of information through our API“, die Terms of Service nennen `robots.txt` nicht, `docs.pypi.org/api` nennt die Index-API als Weg für Installer; `robots.txt` richtet sich an Crawler |
| `files.pythonhosted.org` | Paketdateien (Bau des Images, `pruefen.sh`) | 404 | erlaubt (RFC 9309) |
| `deb.debian.org` | `apt-get` im Bau des Images (`unzip`; `debian` und `debian-security`) | 404 | erlaubt (RFC 9309) |
| `github.com` | Klon von MOSIDI-ORG/MOSIDI (`git clone --depth 1`) | viele Regeln, darunter `Disallow: /*.git$`; Gruppe `*` und Gruppe `ClaudeBot` | erlaubt: Klon über `https://github.com/MOSIDI-ORG/MOSIDI` ohne `.git`; abgerufen wurden nur `GET /MOSIDI-ORG/MOSIDI/info/refs?service=git-upload-pack` (1) und `POST /MOSIDI-ORG/MOSIDI/git-upload-pack` (2), beide in keiner Gruppe gesperrt (Mitschnitt mit `GIT_TRACE_CURL`, nur die Anfragezeilen ausgewertet) |

Nicht abgerufen: Docker Hub. Das Basisimage (`python:3.12-slim`, per Digest) und beide PostGIS-Images lagen lokal;
`build.log` enthält kein `Pulling`. Der Lauf hat keinen anderen gesperrten Pfad abgerufen: Die `letzte_abfrage` aller
Berichte nennt nur `isk.geobasis-bb.de` (WFS-Pfade `/ows/…`), `download.statistik-berlin-brandenburg.de` (XLSX) und
`sgx.geodatenzentrum.de` (`/wfs_vg250`).

## Prüfkette

| Prüfung | Ergebnis | Protokoll |
|---|---|---|
| `./pruefen.sh` (ruff, bandit, pip-audit gegen PyPI, Tests ohne Datenbank, Secret-Scan, Stückliste) am Endstand nach dem letzten Stagen; Zeitpunkt und Teilbäume in der Kopfzeile | ohne Befund, 264 Tests bestanden (die 63 Datenbanktests dort übersprungen, sie laufen getrennt); bandit gibt nur eine Warnung aus, dass ein `nosec` in `pipeline/quellen.py` keinen Treffer mehr unterdrückt; uv und pip-audit mit PyPI wie in `pruefen.sh` (keine Abweichung, anders als nach E48) | [`pruefen.log`](pruefen.log) |
| `tests/test_datenbank.py` gegen eine echte PostGIS-Datenbank mit den MOSIDI-Tabellen, `postgis/postgis:16-3.6` (festgeschrieben); Teilbäume in der Kopfzeile | PostgreSQL 16.15: 63 von 63 (06.11.2026, 12:27 bis 12:31 MEZ) | [`datenbanktests.log`](datenbanktests.log) |
| dieselben Tests, `postgis/postgis:latest` | PostgreSQL 18.6: 63 von 63 (12:31 bis 12:35 MEZ, nach PostgreSQL 16) | [`datenbanktests.log`](datenbanktests.log) |
| `nur-kommentare.py`: Vergleich Stand vor E49 gegen Stand nach E49, Datei für Datei | jede Datei OK oder BEABSICHTIGT, keine ABWEICHUNG; Selbsttest 30 Fälle | [`nur-kommentare.log`](nur-kommentare.log) |

Die Datenbanktests liefen je Version nacheinander in einem frischen Wegwerf-Compose-Projekt aus der
`docker-compose.yml` dieses Repositorys mit zufälligen Passwörtern; Container und Volumes sind danach entfernt. Die
Projektnamen `gip-e42-pg16-…` und `gip-e42-pg18-…` sind nur ein Präfix aus dem Aufruf; maßgeblich sind die
Teilbäume in der Kopfzeile.

## Belegläufe gegen die echten Dienste

**Rahmen.** Alle Läufe liefen auf einem Entwicklungsrechner (Linux, Docker, 16 Kerne), der währenddessen auch für
andere Arbeit genutzt wurde. Vor dem Start war die 1-Minuten-Last 1,65 (`/proc/loadavg`, Schwelle für einen Start
8). Während der Läufe lag sie zwischen 1,55 und 4,52 (`quellen` 1,63 bis 4,52, der Höchstwert direkt nach dem Bau des
Images; `deutschland` 1,59 bis 2,87; Compose von MOSIDI 1,55 bis 3,49). Die Last vor und nach jedem Lauf steht in
`*/ablauf.txt`. Es gibt eine Reihe; die Laufzeiten sind Größenordnungen, keine Messung auf einem ruhigen Rechner.
Sie liegen in der Größenordnung der Prüfstände nach E46 und E47; ein Geschwindigkeitsunterschied zwischen den Ständen
ist damit nicht belegt.

Die Datenbank war jeweils frisch, in einem Wegwerf-Compose-Projekt aus der `docker-compose.yml` dieses Repositorys
(PostgreSQL 16.15, PostGIS 3.6.4, Schema der MOSIDI-Tabellen aus `sql/mosidi/`). Die Zugangsdaten wurden zufällig
erzeugt und danach gelöscht, Container und Volumes sind entfernt. Die Pipeline lief als Container aus dem Image dieses
Stands (`geodaten-import-pipeline:e49-beleg`, je Konfiguration neu gebaut, beide Male dieselbe Image-ID
`sha256:464072e6709f…`) mit `mem_limit: 1g` wie in der Compose-Datei. Ablauf: `beleg.sh` (seit E50 in e50, seit E51 in [`../pruefstand-2026-11-07-e51/beleg.sh`](../pruefstand-2026-11-07-e51/beleg.sh); die Vorlage
aus dem Prüfstand nach E48, mit `git mv` übernommen; geändert sind nur Kopf, Kommentare und Imagename), aufgerufen als
`beleg.sh quellen <Ordner> --alle -- --alle -- .` und `beleg.sh deutschland <Ordner> --alle -- --alle`, nacheinander.
Für `quellen` gibt es wie nach E47 einen dritten Lauf ohne `--alle` (nur fällige Quellen).

Laufzeiten auf eine Nachkommastelle gerundet (kaufmännisch; die Rohwerte stehen in den Berichten, etwa 112,94 s
→ 112,9 s und 262,75 s → 262,8 s).

| | `config/quellen.yaml` (Brandenburg) | `config/deutschland.yaml` |
|---|---|---|
| Läufe | [`quellen/`](quellen/): `20261106T105848Z` `--alle`, `20261106T110045Z` `--alle`, `20261106T110243Z` ohne `--alle` | [`deutschland/`](deutschland/): `20261106T110337Z` `--alle`, `20261106T110835Z` `--alle` |
| Zeit (MEZ) | 06.11., 11:57 bis 12:03 | 06.11., 12:03 bis 12:13 |
| Rückgabe | 0; 0; 0 | 0; 0 |
| Laufzeit laut Bericht | **Erstlauf 112,9 s, Folgelauf 113,7 s**, dritter Lauf 0,02 s (alle sechs Quellen „nicht fällig“) | **Erstlauf 294,4 s, Folgelauf 262,8 s** |
| Wandzeit mit Containerstart | 116,1 s; 116,7 s; 2,5 s | 297,1 s; 265,1 s |
| davon INKAR laut Laufprotokoll | 95,1 s; 96,4 s | 244,2 s; 215,3 s (VG250: 50,2 s; 47,4 s) |
| Rechnerlast 1/5/15 min vor dem Lauf | 4,52/3,80/3,37; 1,76/3,03/3,14; 1,68/2,63/2,98 | 2,87/2,78/3,01; 1,61/2,06/2,64 |
| Rechnerlast 1/5/15 min nach dem Lauf | 1,76/3,03/3,14; 1,68/2,63/2,98; 1,63/2,60/2,97 | 1,61/2,06/2,64; 1,59/1,77/2,36 |
| Geometrien | 882 Gebäude, 413 Gemeinden, 18 Kreise | 11 103 Gemeindeflächen (VG250-WFS des BKG) |
| Amt für Statistik (E48) | 413 Bevölkerungs- und 413 Flächenwerte, zusammen 826 Zeilen, 2 Indikatoren, 413 Gemeinden; Zeitbezug Bevölkerung 31.12.2025, Fläche 31.12.2024 (Kennzahlen 2024 bis 2025); im zweiten Lauf 413 + 413 unverändert; `data_type = indikator` | – |
| XLSX des Amts | Datei laut Seite `SB_A01-04_00_2025j01_BB.xlsx` (410 KiB) auf `download.statistik-berlin-brandenburg.de`; im Erstlauf neu geladen, danach „unverändert seit dem letzten Abruf“ (bedingter Abruf); sie liegt im Zwischenspeicher `cache/` (nicht in git) und nicht in diesem Ordner | – |
| INKAR nach `dashboard_data_de` | 62 929 Zeilen neu, im zweiten Lauf 62 929 unverändert; Zeitbezug 1995 bis 2023; Hinweis „Abgelegte Datei, kein Abruf: inkar_2025.zip“ | 1 640 420 Zeilen neu, im zweiten Lauf 1 640 420 unverändert; Zeitbezug 1995 bis 2023; ebenso aus der abgelegten Datei |
| INKAR-Indikatornamen (Regel aus E40) | 9, davon 5 mit Bereich „(LRB)“ (51 477 der 62 929 Zeilen) | dieselben 9 (1 345 471 der 1 640 420 Zeilen mit Bereich) |
| Zeilen verworfen, zurückgehalten oder zusammengeführt | 0 (keine Quelle angehalten oder unvollständig; INKAR gelesen = neu = 62 929; `zurueckgehalten` überall 0) | 0 (gelesen = neu = 1 640 420) |
| Doppelte Zielschlüssel in `dashboard_data_de` | 0 | 0 |
| Übernommene Zeilen | 0 in allen Quellen und Läufen (frische Datenbank) | 0 |
| Register `pipeline_meta.bestand` | INKAR 62 929 Zeilen, 62 929 mit Quellschlüssel, alle verschieden; Bevölkerung und Fläche je 413, alle verschieden | INKAR 1 640 420, alle mit Quellschlüssel, alle verschieden; VG250 11 103 |
| `table_metadata` | 14 Zeilen (9 INKAR, 2 Amt für Statistik, 3 LGB) | 10 Zeilen (9 INKAR, 1 BKG) |
| Gebietsschlüssel mit Fläche | 413 von 413 | 10 946 von 10 978; die 32 übrigen haben keine Fläche in der VG250 (wie nach E47; als Ursache ist der Gebietsstand 2023 von INKAR zu prüfen) |
| Flächenprüfung | 413 Gemeinden, Median 0,005 %, höchstens 0,398 % (Toleranz 0,5 %); nach E47 0,161 % mit der Fläche der Regionaldatenbank, jetzt Fläche des Amts Stand 31.12.2024 | – |
| `aktualit` (E47) | Hinweis „882 Werte in aktualit als Datum ohne Zeitzonenkennung Z übernommen“ in beiden vollen Läufen (`info.normalisiert.aktualit = 882`) | – |
| Warnungen | keine (auch keine Zeilen ohne Wert mehr; die 7 Gemeinden mit „-“ betrafen die Tabellen der Regionaldatenbank) | keine |
| Katalog (E46) | Erstlauf: Hinweis „`public.source_granularities` gibt es in dieser Datenbank nicht“, `katalog.ergebnis = fehlt`; Folgeläufe ohne Änderung ohne Aufruf | ebenso |
| höchste Probe von `docker stats` | 135,1 MiB (56 Proben); 125,1 MiB (56 Proben); dritter Lauf keine Probe (Container nach 2,5 s beendet, bevor die Probenschleife ihn sah) | 94,4 MiB (144 Proben); 94,0 MiB (129 Proben) |
| `memory.peak` der cgroup (Bytes → MiB) | 613 957 632 → 585,5 MiB; 186 540 032 → 177,9 MiB; dritter Lauf 35 880 960 → 34,2 MiB | 102 653 952 → 97,9 MiB; 103 428 096 → 98,6 MiB |
| Datenbank danach | 73 MB | 1 132 MB (`pipeline_meta.bestand` 564 MB, `pipeline_meta.aenderung` 307 MB, `dashboard_data_de` 209 MB, `"Kommunale Gebiete Deutschland"` 35 MB) |

Alle Zahlen sind aus den Rohdateien in diesem Ordner nachgerechnet: Laufzeiten aus den Berichten (`*.txt`, `*.json`)
und `ablauf.txt`, Zählungen aus `datenbank-auszug.txt` und den Zählern in den Berichten, Speicher aus
`speicher-lauf<n>.txt` (höchster Wert der Spalte `MemUsage`) und der Zeile `cgroup memory.peak` in
`konsole-lauf<n>.txt`.

**Deutschland gegenüber E47:** Die Abschnitte „Kennzahlen“, „Indikatornamen“, „Doppelte Zielschlüssel“, „Register“,
„Beispiele“ und „table_metadata“ in `deutschland/datenbank-auszug.txt` sind zeilengleich mit dem Prüfstand nach E47
(11 103 Gemeindeflächen, 1 640 420 INKAR-Zeilen, 10 Zeilen `table_metadata`). E48 ändert für Deutschland nur, woher
die INKAR-Datei kommt (abgelegt statt beim BBSR-Server auf Änderung abgefragt); die Hinweise im Bericht lauten
entsprechend „Abgelegte Datei, kein Abruf“.

**Speicher, Messverfahren** wie nach E46 und E47: `docker stats --no-stream` in einer Schleife mit 1 s Pause (Median
des Probenabstands je Lauf 2,03 s; `docker stats` zeigt den Speicher der cgroup ohne inaktiven Seitencache) und am Ende
jedes Laufs `/sys/fs/cgroup/memory.peak` (Höchststand des Kernels einschließlich Seitencache; für die Grenze von 1 GB
zählt dieser Wert). Der höchste ist 585,5 MiB (`quellen`, Erstlauf; nach E47 599,3 MiB), in Deutschland 98,6 MiB.
Seitencache am Ende (`file` in `memory.stat`): `quellen` 416,3, 8,6 und 0,2 MiB, Deutschland je 0,2 MiB.
`memory.peak` bleibt in allen Läufen unter 60 % der Grenze.

## Lauf im Compose-Setup von MOSIDI (Wiederholung der Läufe vom 03.11. und nach E46 und E47)

Ordner [`mosidi-compose/`](mosidi-compose/), Ablauf `mosidi-compose/lauf.sh` (seit E50 in e50, seit E51 in [`../pruefstand-2026-11-07-e51/mosidi-compose/lauf.sh`](../pruefstand-2026-11-07-e51/mosidi-compose/lauf.sh); die Vorlage
aus dem Prüfstand nach E48, mit `git mv` übernommen; geändert sind nur Kopf, Kommentare, Imagename und Projektname),
06.11.2026, 12:13 bis 12:19 MEZ. MOSIDI-ORG/MOSIDI wurde für diesen Lauf um 11:57 frisch und öffentlich geklont
(`git clone --depth 1 https://github.com/MOSIDI-ORG/MOSIDI`): Commit `26cadbba3d6223c84872987104fc737359bf8bfc` vom
02.11.2026, derselbe wie am 03. und 05./06.11. Benutzt sind die unveränderte `docker-compose.yml` von MOSIDI und das
Overlay [`deploy/mosidi/docker-compose.pipeline.yml`](../../deploy/mosidi/docker-compose.pipeline.yml), so wie
[`deploy/mosidi/README.md`](../../deploy/mosidi/README.md) es beschreibt, mit eigenem Compose-Projektnamen
(`gip-mosidi-e49-<pid>`), zufälligen Passwörtern und danach `down -v` (keine Container, Volumes oder `.env` übrig,
nachgesehen nach dem Lauf).

Abweichungen vom unveränderten Compose, alle im Test-Override von `lauf.sh`, wie nach E46 und E47:

- `brandenburg_db`: Volume unter `/var/lib/postgresql` statt `/var/lib/postgresql/data` (sonst startet PostgreSQL 18
  nicht, unten), keine Freigabe von Port 5432 nach außen, eigener Containername statt des festen `brandenburg_db`.
- Pipeline-Dienste: Image `geodaten-import-pipeline:e49-beleg` (ID in `mosidi-compose/ablauf.txt`, dasselbe wie in
  den Belegläufen) statt des Tags `:lokal` aus dem Overlay; Berichtsordner im Ausgabeordner statt im Repository; INKAR
  aus `cache/inkar_2025.zip` per `PIPELINE_INKAR_DATEI`, die beiden gesperrten Rechner im Container auf `0.0.0.0`.
- `.env` von MOSIDI: `POSTGRES_DB=brandenburg`, `POSTGRES_USER=admin`, die Passwörter zufällig; `pg_tileserv.env`
  leer. Compose warnt deshalb, dass `GEOSERVER_ADMIN` und `GEOSERVER_PASSWORD` nicht gesetzt sind (in
  `konsole-lauf<n>.err.txt` und `einrichten.log`; nur die Namen, keine Werte); GeoServer startet nicht mit.
- Datenbank: PostgreSQL 18.6, PostGIS 3.6.4 (`postgis/postgis` ohne Tag, wie in MOSIDI).
- Testaufbau: Schema der Bestandstabellen aus `sql/mosidi/001_bestand.sql` (unverändert), danach als Administrator
  die Materialized View `source_granularities` mit ihren beiden Indizes, wörtlich aus MOSIDI
  `services/backend/src/db_table_metadata/script.py`, Zeilen 262 bis 272 (sha256 `7eec19e3…` in `ablauf.txt`,
  derselbe Ausschnitt wie nach E47).

Ergebnis:

| | |
|---|---|
| Unverändertes `brandenburg_db` auf frischem Volume | startet nicht: nach 30 s Status `restarting`, 9 Neustarts, Meldung „in 18+, these Docker images are configured to store database data in a format which is compatible with pg_ctlcluster …“ ([`befund-postgresql18.txt`](mosidi-compose/befund-postgresql18.txt)), wie am 03.11. und nach E46 und E47 |
| `pipeline-einrichten` | Rückgabe 0; Rollen `pipeline_import` und `mosidi_lesen` ohne Superuser-, CREATEDB- oder CREATEROLE-Recht; Spaltenrechte in [`einrichten.log`](mosidi-compose/einrichten.log); Eigentümer von View und Funktion ist `admin`, `SECURITY DEFINER` |
| Lauf 1 `--alle` (`20261106T111443Z`) | **Rückgabe 0**, 111,9 s laut Bericht (Wandzeit 114,4 s, 1-Minuten-Last davor 3,49, danach 1,83), INKAR 94,8 s; 882 Gebäude, 413 Gemeinden, 18 Kreise, 413 + 413 Werte des Amts für Statistik, 62 929 INKAR-Werte; **„Katalog: public.source_granularities aktualisiert“**, die View hatte vorher 0 Zeilen, danach 11 (9 INKAR, 2 Amt für Statistik, Gemeindeebene; nach E47 13 mit 4 Indikatoren der Regionaldatenbank) |
| Lauf 2 `--alle` (`20261106T111638Z`) | **Rückgabe 0**, 114,4 s laut Bericht (Wandzeit 116,9 s, Last danach 1,55), INKAR 97,3 s; alles unverändert, kein Aufruf des Katalogs, `pipeline_meta.katalog_offen` leer, View weiter 11 Zeilen |
| Datenbank danach | 0 doppelte Zielschlüssel, `table_metadata` 14 Zeilen, in `public` 39 Tabellen, 2 Views, 1 Materialized View, 25 Sequenzen ([`datenbank-auszug.txt`](mosidi-compose/datenbank-auszug.txt)) |
| Bestandsschema `public` (Antworten 27, 29) | `pg_dump --schema-only --schema=public --no-privileges --no-owner` vor `einrichten` und nach Lauf 2 gleich (2 527 Zeilen, sha256 `2a70acee…` in `ablauf.txt`, derselbe Wert wie nach E46 und E47; die Dumps liegen nicht bei). Die Rechte in `public` ändert `einrichten` wie vorgesehen (`einrichten.log`); sie sind in diesem Vergleich ausgenommen |

Der Abschnitt „Schreibrechte“ im Datenbankauszug zählt nur Rechte auf ganze Tabellen (SELECT auf 5, DELETE auf
`dashboard_data_de`); INSERT und UPDATE vergibt `einrichten` spaltenweise, sie stehen in `einrichten.log`.

## Was nicht geprüft ist

- Der Download der INKAR-Datei: Er ist per robots.txt gesperrt und wird nicht ausgeführt; alle Läufe lesen
  `cache/inkar_2025.zip` (434 MB, Stand 13.08.2025). Die Klärung mit TH und BBSR ist offen (E48).
- Alle 264 INKAR-Kürzel: Beide Konfigurationen laden fünf (Gesamtanalyse ohne Datenbanklauf in
  [`../inkar-schluessel/`](../inkar-schluessel/)).
- Ein Änderungslauf mit echten Änderungen, eine Übernahme vorhandener Zeilen und die Umstellung einer bestehenden
  Datenbank von der Regionaldatenbank auf das Amt für Statistik (E48, „Bestehende Datenbanken“): Die Folgeläufe hier
  sind „alles unverändert“, die Datenbanken frisch. Neu, geändert, gelöscht, Übernahme, Kürzel- und Stichtagwechsel
  prüfen die Datenbanktests.
- Die Fehlerpfade aus E44 bis E48 (Abriss der Datenbank, Metadatenkonflikt, gescheiterte Katalogaktualisierung,
  datenbankweite Sperre, fremd vergebene Rechte, Geometrie mit anderem Typ, WFS mit Seitenlimit, Kachel ohne
  Gesamtzahl, zu lange Texte, Folge-Links der OGC API, vorhandene Rolle mit zu weiten Rechten, beschädigte oder
  umgebaute XLSX, gesperrte Pfade): In diesen Läufen trat keiner auf; sie prüfen die Tests.
- Die Codefehler, die beim Kommentieren auffielen (E49, „Prüfung der Kommentare“): nicht behoben, nicht Gegenstand
  dieser Läufe.
- `SORTBY` in Kachelabfragen gegen die echten Dienste (wie nach E47: die Dienste der LGB melden `ImplementsSorting`
  nur unter Filter_Capabilities).
- Im Compose von MOSIDI: Speicher (nicht gemessen), `--haerten`, die übrigen Dienste von MOSIDI (Backend, Frontend,
  GeoServer, nicht gestartet), eine bestehende Datenbank der TH mit Daten und eigenen Rechten, und ob dort der
  Eigentümer der Funktion die echte View aktualisieren darf.
- Die Laufzeit auf einem ruhigen oder dem Zielrechner.
- Dass jeder Kommentar stimmt: `nur-kommentare.py` belegt nur, dass sich der Code nicht geändert hat (E49, „Grenzen“).

## Dateien

**Abweichungen der Dateien hier von den Ausgaben der Skripte** (wie nach E47): `lauf<n>.out` heißt hier
`konsole-lauf<n>.txt`, `lauf<n>.err` (stderr des Aufrufs, hier nur Meldungen von Compose) heißt
`konsole-lauf<n>.err.txt`. Berichte und Quellenverzeichnis liegen direkt im jeweiligen Ordner statt unter `berichte/`.
`speicher-lauf3.txt` in `quellen/` hat nur die Kopfzeile (keine Probe, siehe Tabelle). Nicht beigelegt sind
`build.log` (Bauprotokoll des Images), `schema-public-vorher.txt` und `schema-public-nachher.txt` (Compose-Lauf,
sha256 in `ablauf.txt`), die Sperrdatei des Berichtsordners und der Mitschnitt des Klons. Alle beigelegten Rohdateien
(49: `quellen` 20, `deutschland` 15, Compose 14) sind byte-gleich mit den Rohausgaben (byteweise verglichen am
06.11.2026).

**Die Kartenseiten liegen nicht bei**, ebenso wenig die XLSX des Amts und die INKAR-Datei. Sie enthalten die
importierten Datensätze; Quelldaten werden nicht mit dem Code veröffentlicht (Antwort 69). Die Datenbankauszüge
nennen Zählungen und Beispiele des Registers nur als Schlüssel, ohne Werte.

## Stand

- **Teilbäume** (`git write-tree` des Index, vor den Läufen, nach dem letzten Stagen und in allen Protokollen gleich):
  `pipeline` `5298b848911a3df46d278f9c3959070ab9e6bb81`, `config` `b0ec40745f2fd1fd9104e30c28a31317bfe7ab7c`, `sql`
  `acacc89bd5167e671bcfb27b511620734f1f55f6`, `tests` `7bfdf8ccc64742729ba1ed39855db878e9ca7f64`, `Dockerfile`
  `6788a7afeb4041d3c71b517b184d557c44c99762`, `requirements.txt` `3edf4ee3e318de51d0094b6ad08cbc7ddeed8191`.
  Dieselben stehen in den Kopfzeilen von `pruefen.log` und `datenbanktests.log` und, von den Skripten über eine Kopie
  des Index aus dem Arbeitsstand berechnet, aus dem das Image gebaut wurde, in allen drei `*/ablauf.txt`. Es sind die
  Teilbäume aus E49 („Prüfung“).
- **`nur-kommentare.log`** entstand vor diesen Belegen am Baum `dccf98bf4a71bad6df96195a88c69d48919fe96c`. Dessen
  Teilbäume `pipeline`, `tests`, `config`, `sql`, `Dockerfile` und `requirements.txt` sind dieselben wie oben; danach
  kamen nur dieser Prüfstand und Dokumentation dazu. Das Skript ist für diesen Prüfstand nicht erneut gelaufen: Es
  würde die mit `git mv` übernommenen Skripte und die nachgezogene Dokumentation als nicht aufgeführte Änderungen
  melden. Dass der Code am Endstand derselbe ist, belegen die gleichen Teilbäume.
- **Overlay für MOSIDI:** `mosidi-compose/ablauf.txt` nennt zusätzlich den Teilbaum `deploy` zur Zeit des Laufs
  (`63e09d5fa41bf01a2177e4f238d781f422c5c7ff`). Er ändert sich danach nur durch Dokumentation
  (`deploy/mosidi/README.md`); die benutzte Datei `deploy/mosidi/docker-compose.pipeline.yml` ist unverändert, Blob
  `d332d886e1a29780e3df520b41bacfbc6323f30a` (nachprüfbar mit
  `git rev-parse angebot-va-2026-536:deploy/mosidi/docker-compose.pipeline.yml`).
- **Nachprüfbar** nach dem Taggen mit `git rev-parse angebot-va-2026-536:pipeline` usw. Unmittelbar vor dem Taggen
  sind die Teilbäume mit `git write-tree` neu zu berechnen; weichen sie ab, gelten diese Belege nicht für den Tag
  (E45, P14).
- **Reihenfolge** (06.11.2026, MEZ): robots.txt 11:52, Läufe `quellen` 11:57 bis 12:03 (währenddessen um
  11:57 der Klon von MOSIDI), `deutschland` 12:03 bis 12:13, Compose-Lauf 12:13 bis 12:19; danach Dokumentation, Stagen, `pruefen.sh` (12:26 bis 12:27, ohne Befund), Datenbanktests PostgreSQL 16 von 12:27 bis 12:31 und 18 von 12:31 bis 12:35; danach nur `datenbanktests.log`, diese README und `pruefen.log`; `pruefen.sh` lief nach dem letzten Stagen erneut (`pruefen.log`, Endzeit in der Kopfzeile).
