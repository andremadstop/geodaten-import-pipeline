# Prüfstand 06.11.2026, Abgabestand nach E50 (Tests, Läufe gegen die echten Dienste, Lauf im Compose von MOSIDI, INKAR-Vollumfang)

> **Abgelöst durch [`../pruefstand-2026-11-07-e51/`](../pruefstand-2026-11-07-e51/)** (07.11.2026): Abgabestand ist jetzt
> der Stand nach E51 (Code geändert, `docs/entscheidungen.md`, E51). Tests, Läufe gegen die echten Dienste und der Lauf im
> Compose von MOSIDI sind dort am Stand nach E51 wiederholt, dazu die Lieferkonfiguration im Vollumfang (Erst- und
> Folgelauf) und ein Wertabgleich je Zeile. Dieser Prüfstand bleibt als Beleg des Stands nach E50; seine Teilbäume
> `pipeline`, `tests`, `config` und `deploy` gelten nur für jenen Stand. `beleg.sh` und `mosidi-compose/lauf.sh` sind mit
> `git mv` nach e51 verschoben und dort angepasst; was sich gegenüber der hier benutzten Fassung geändert hat, nennt der
> Kopf beider Skripte (Imagename, Projektname, Teilbaum `deploy`, Warten auf die Rechnerlast, Ausfuhr für den
> Wertabgleich, Konfiguration des Compose-Laufs). Der Abgleich [`inkar-vollumfang/abgleich.py`](inkar-vollumfang/abgleich.py)
> unten vergleicht nur Zeilenzahlen je Indikatorname, keine Werte; den Abgleich je Zeile und Wert enthält erst e51.
> „Abgabestand“ im Text unten heißt der Stand nach E50.

> **Nachtrag 07.11.2026 (E51):** Seit E51 ist dieser Prüfstand nicht mehr am Endstand des Codes. E51 (Prüfbericht vom
> 07.11.2026, 03:13; [`docs/entscheidungen.md`](../../docs/entscheidungen.md), E51) ändert `pipeline`, `tests`, `config`
> und `deploy`: Zeitgrenzen der Datenbank je Quelle (K1), erlaubte Fußzeilen bzw. zweifelhafte Restzeilen in CSV, XLSX
> und INKAR (K2), WFS-Kennung aus `gml:id` (W3), INKAR im Vollumfang als Lieferkonfiguration `config/quellen.yaml` mit
> `zeitbudget_min: 240` und `TimeoutStartSec=7h` (W2), Prüfwerkzeuge in fester Version (G2). Die bisherige reduzierte
> `config/quellen.yaml` heißt seitdem unverändert `config/pruefkonfiguration.yaml`; die Belegläufe „quellen“ unten
> liefen mit genau diesem Inhalt. Die Läufe hier sind nicht wiederholt. Am echten Bestand nachgeprüft (ohne Netz, aus
> den abgelegten Dateien): Der XLSX-Adapter liefert mit den neuen Regeln weiter 413 + 413 Werte ohne Warnung, und die
> INKAR-Gesamtdatei 2025 hat keine Zeile mit falscher Spaltenzahl (alle 63 426 864 Zeilen mit 9 Feldern), die neue
> INKAR-Regel ändert die Zählungen also nicht. Die Messungen und Teilbäume unten gelten für den Stand nach E50; Einträge
> mit „seit E51“ in der Soll-/Ist-Tabelle sind nachgetragen. Zum Nachstellen der Läufe „quellen“ heute
> `beleg.sh pruefkonfiguration` aufrufen; `beleg.sh quellen` lädt die heutige Lieferkonfiguration im Vollumfang
> (Stunden, bis rund 53 GB).

Das ist der Prüfstand des Abgabestands (Tag `angebot-va-2026-536`, E43): Stand nach E50 einschließlich der Nachprüfung
zu E50 ([`docs/entscheidungen.md`](../../docs/entscheidungen.md), E50). Der Code ist eingefroren; seit den Prüfungen
in E50 hat sich an `pipeline`, `tests`, `config`, `sql`, `Dockerfile` und `requirements.txt` nichts geändert (Teilbäume
unten, vor den Läufen und nach dem letzten Stagen gleich).

Alles in diesem Ordner ist am selben Code-Stand entstanden (Teilbäume unten, in den Kopfzeilen der Protokolle und in
jeder `ablauf.txt`): die Tests, die Belegläufe `config/quellen.yaml` und `config/deutschland.yaml` gegen die echten
Dienste, die Wiederholung des Laufs im Compose-Setup von MOSIDI mit der Katalogaktualisierung und, neu, ein Lauf im
INKAR-Vollumfang mit einer eigenen Prüfkonfiguration (Befund W1 „Mengennachweis“ des Prüfberichts vom 06.11.2026,
13:26). Er löst [`../pruefstand-2026-11-06-e49/`](../pruefstand-2026-11-06-e49/) ab; dort stehen die Läufe am Stand
nach E49, an dem der Code noch nicht geändert war.

**Gegenüber dem Prüfstand nach E49:** Alle Läufe enden wieder mit Rückgabe 0, mit denselben Zählungen (882 Gebäude,
413 Gemeinden, 18 Kreise, 413 + 413 Werte des Amts für Statistik, 62 929 INKAR-Werte in Brandenburg; 11 103
Gemeindeflächen und 1 640 420 INKAR-Werte in Deutschland), keiner Warnung und 0 doppelten Zielschlüsseln. Der
INKAR-Schritt dauert länger als nach E49 (Brandenburg 126,5 statt 95,1 s, Deutschland 284,8 statt 244,2 s; unten,
„Abweichungen“). INKAR kommt in allen Läufen aus der abgelegten Datei; obwohl die ausgelieferte Konfiguration seit E50
eine Freigabe für `www.bbr-server.de` trägt, hat kein Lauf diesen Rechner abgerufen (Belege unten, „Kein Abruf von
`www.bbr-server.de`“).

## robots.txt je Rechner

Vor den Läufen ist für jeden Rechner, den ein Lauf, der Bau des Images, `pruefen.sh` oder der Klon von MOSIDI abrufen
kann, einmal die `robots.txt` abgerufen worden (06.11.2026, 21:15 UTC, 22:15 MEZ; je eine Anfrage, `curl`). Die Regeln
sind gegen die tatsächlich abgerufenen Pfade geprüft (Platzhalter `*` und `$` wie in RFC 9309, längste passende Regel
gewinnt). Antwortet ein Rechner auf `/robots.txt` mit einem Status 4xx, gilt die Datei nach RFC 9309 (Abschnitt
2.3.1.3) als nicht vorhanden; dann gibt es keine Einschränkung.

| Rechner | Wofür | `robots.txt` | Ergebnis |
|---|---|---|---|
| `isk.geobasis-bb.de` | WFS der LGB: Gebäude, Gemeinden, Kreise (`quellen.yaml`) | 404 | erlaubt (RFC 9309: keine Datei, keine Einschränkung) |
| `www.statistik-berlin-brandenburg.de` | Seite des Statistischen Berichts A I 4 / A V 2 (`quellen.yaml`, `seite`) | `Disallow: /scrivito/` | `/a-i-4-a-v-2-j/` erlaubt |
| `download.statistik-berlin-brandenburg.de` | XLSX-Datei des Berichts (`link_rechner`) | 403 des Speichers | erlaubt (RFC 9309: Status 4xx heißt „nicht verfügbar“, kein Verbot) |
| `sgx.geodatenzentrum.de` | VG250-WFS des BKG (`deutschland.yaml`) | `Disallow: /gdz_geoviewserver/`, `/gdz_geoviewserv/` | `/wfs_vg250` erlaubt |
| `www.bbr-server.de` | INKAR (`quellen.yaml`, `deutschland.yaml`; seit E50 mit `robots_freigabe`) | **nicht abgerufen, auch nicht die `robots.txt`**; Stand der letzten Prüfung (06.11.2026, 10:52 UTC, Prüfstand nach E49): `Disallow: /` | **gesperrt, nicht abgerufen.** Anders als nach E49 ist hier auch die `robots.txt` nicht abgefragt: Unsere Läufe rufen den Rechner nie ab, also gibt es keinen Abruf, vor dem sie zu prüfen wäre. INKAR kommt aus `cache/inkar_2025.zip` per `PIPELINE_INKAR_DATEI` (schreibgeschützt eingehängt), der Rechner löst im Container auf `0.0.0.0` auf |
| `www.regionalstatistik.de` | nirgends konfiguriert (bis E47 Bevölkerung und Fläche) | `Disallow: /` (Prüfung zu E48) | **gesperrt, nicht abgerufen**, auch nicht die `robots.txt`; im Code gesperrt (`ROBOTS_GESPERRT`), im Container auf `0.0.0.0` |
| `pypi.org` | Paketindex: `pruefen.sh` (uv, uvx, pip-audit); der Bau des Images kam aus dem Zwischenspeicher von Docker (unten) | `Disallow: /simple/`, `/packages/`, `/pypi/*/json` u. a. | genutzt als dokumentierte Paketschnittstelle für Installer (E49, „PyPI und robots.txt“), wie nach E49 |
| `files.pythonhosted.org` | Paketdateien (`pruefen.sh`) | 404 | erlaubt (RFC 9309) |
| `deb.debian.org` | `apt-get` im Bau des Images | 404 | erlaubt (RFC 9309); nicht abgerufen, der Schritt kam aus dem Zwischenspeicher |
| `github.com` | Klon von MOSIDI-ORG/MOSIDI (`git clone --depth 1`) | viele Regeln, darunter `Disallow: /*.git$`; Gruppe `*` und Gruppe `ClaudeBot` | erlaubt: Klon über `https://github.com/MOSIDI-ORG/MOSIDI` ohne `.git`; abgerufen wurden nur `GET /MOSIDI-ORG/MOSIDI/info/refs?service=git-upload-pack` (1) und `POST /MOSIDI-ORG/MOSIDI/git-upload-pack` (2), beide in keiner Gruppe gesperrt (Mitschnitt mit `GIT_TRACE_CURL`, nur die Anfragezeilen ausgewertet) |

Nicht abgerufen: Docker Hub und `deb.debian.org`. Das Basisimage (`python:3.12-slim`, per Digest) und beide
PostGIS-Images lagen lokal; der Bau des Images nahm die Schritte `apt-get` und `pip install` aus dem Zwischenspeicher
von Docker (`build.log`: „Using cache“, kein `Pulling`). Die `letzte_abfrage` aller Berichte nennt nur
`isk.geobasis-bb.de` (WFS-Pfade `/ows/…`), `download.statistik-berlin-brandenburg.de` (XLSX) und
`sgx.geodatenzentrum.de` (`/wfs_vg250`).

## Kein Abruf von `www.bbr-server.de`

Seit E50 trägt die ausgelieferte Konfiguration für INKAR `robots_freigabe` (Regelbetrieb der TH, Antwort 33). Für
unsere Läufe gilt die Regel aus `docs/betrieb.md`: Jeder eigene Lauf setzt `PIPELINE_INKAR_DATEI`. Die abgelegte Datei
hat Vorrang vor der Freigabe. Belegt ist das in jedem Lauf, der INKAR geladen hat (je zwei Läufe `quellen`,
`deutschland` und Compose von MOSIDI; der dritte `quellen`-Lauf lud keine Quelle), viermal, im Vollumfang dreimal:

| Beleg | Wo | Ergebnis |
|---|---|---|
| Hinweis der Pipeline | Text- und JSON-Bericht jeder INKAR-Quelle | „Abgelegte Datei, kein Abruf: inkar_2025.zip“ und „robots_freigabe konfiguriert, nicht genutzt (abgelegte Datei)“; im Vollumfang nur der erste (seine Prüfkonfiguration hat keine Freigabe) |
| Keine genutzte Freigabe | JSON-Berichte | kein `info.robots_freigabe`, keine Warnung „abgerufen mit der Freigabe“, `warnungen` aller INKAR-Quellen leer |
| `letzte_abfrage` | JSON-Berichte | bei INKAR leer; `bbr-server` kommt in keinem Laufbericht vor (`grep -c` über alle `2026*.json` und `2026*.txt`: 0), nur im Quellenverzeichnis als konfigurierte `adresse` |
| Namensauflösung im Container | `ablauf.txt` jedes Ordners, Zeilen „Namensauflösung im Container“ | `www.bbr-server.de -> 0.0.0.0`, `www.regionalstatistik.de -> 0.0.0.0` (`getent ahostsv4` im Dienst `pipeline` mit denselben `extra_hosts` wie die Läufe) |

Ein Abruf hätte also nicht einmal eine Verbindung erreicht; er wäre als Fehler der Quelle im Bericht erschienen. Das
ist in keinem Lauf geschehen.

## Prüfkette

| Prüfung | Ergebnis | Protokoll |
|---|---|---|
| `./pruefen.sh` (ruff, bandit, pip-audit gegen PyPI, Tests ohne Datenbank, Secret-Scan, Stückliste) am Endstand nach dem letzten Stagen; Zeitpunkt und Teilbäume in der Kopfzeile | ohne Befund, 386 Tests bestanden (die 66 Datenbanktests dort übersprungen, sie laufen getrennt); bandit gibt nur die Warnung aus, dass ein `nosec` in `pipeline/quellen.py` keinen Treffer mehr unterdrückt (wie nach E49); uv und pip-audit mit PyPI wie in `pruefen.sh` | [`pruefen.log`](pruefen.log) |
| `tests/test_datenbank.py` gegen eine echte PostGIS-Datenbank mit den MOSIDI-Tabellen, `postgis/postgis:16-3.6` (festgeschrieben); Teilbäume in der Kopfzeile | PostgreSQL 16.15: 66 von 66 (07.11.2026, 01:52 bis 01:57 MEZ) | [`datenbanktests.log`](datenbanktests.log) |
| dieselben Tests, `postgis/postgis:latest` | PostgreSQL 18.6: 66 von 66 (01:57 bis 02:01 MEZ, nach PostgreSQL 16) | [`datenbanktests.log`](datenbanktests.log) |

Zusammen 452 Tests (386 ohne, 66 mit Datenbank), dieselben Zahlen wie in E50 („Prüfung nach der Nachprüfung“). Die
Datenbanktests liefen je Version nacheinander in einem frischen Wegwerf-Compose-Projekt aus der
`docker-compose.yml` dieses Repositorys mit zufälligen Passwörtern; Container und Volumes sind danach entfernt. Die
Projektnamen `gip-e42-pg16-…` und `gip-e42-pg18-…` sind nur ein Präfix aus dem Aufruf; maßgeblich sind die
Teilbäume in der Kopfzeile. Sie liefen nach allen Läufen, nicht parallel zu ihnen.

## Belegläufe gegen die echten Dienste

**Rahmen.** Alle Läufe liefen auf einem Entwicklungsrechner (Linux, Docker, 16 Kerne), der währenddessen auch für
andere Arbeit genutzt wurde. Vor dem Start der ersten Prüfung war die 1-Minuten-Last 2,91 (`uptime`, Schwelle für
einen Start 8); vor jedem Lauf lag sie zwischen 2,0 und 5,1, nach jedem Lauf zwischen 2,0 und 2,6 (je Lauf in
`*/ablauf.txt`). Es gibt eine Reihe; die Laufzeiten sind Größenordnungen, keine Messung auf einem ruhigen Rechner.

Die Datenbank war jeweils frisch, in einem Wegwerf-Compose-Projekt aus der `docker-compose.yml` dieses Repositorys
(PostgreSQL 16.15, PostGIS 3.6.4, Schema der MOSIDI-Tabellen aus `sql/mosidi/`). Die Zugangsdaten wurden zufällig
erzeugt und danach gelöscht, Container und Volumes sind entfernt. Die Pipeline lief als Container aus dem Image dieses
Stands (`geodaten-import-pipeline:e50-beleg`, je Konfiguration neu gebaut, in allen drei Bauten (`quellen`, `deutschland`,
Vollumfang) dieselbe Image-ID `sha256:7a209d15d80c…`) mit `mem_limit: 1g` (1 GiB) wie in der Compose-Datei. Ablauf: `beleg.sh` (seit E51 in [`../pruefstand-2026-11-07-e51/beleg.sh`](../pruefstand-2026-11-07-e51/beleg.sh); die
Fassung aus dem Prüfstand nach E49, mit `git mv` übernommen; geändert sind Kopf, Kommentare, Imagename, die Zeilen zur
Namensauflösung im Container und der Aufruf mit einer eigenen Prüfkonfiguration), aufgerufen als
`beleg.sh quellen <Ordner> --alle -- --alle -- .` und `beleg.sh deutschland <Ordner> --alle -- --alle`, nacheinander.
Für `quellen` gibt es wie nach E49 einen dritten Lauf ohne `--alle` (nur fällige Quellen).

Laufzeiten auf eine Nachkommastelle gerundet (kaufmännisch; die Rohwerte stehen in den Berichten).

| | `config/quellen.yaml` (Brandenburg) | `config/deutschland.yaml` |
|---|---|---|
| Läufe | [`quellen/`](quellen/): `20261106T212612Z` `--alle`, `20261106T212840Z` `--alle`, `20261106T213108Z` ohne `--alle` | [`deutschland/`](deutschland/): `20261106T213217Z` `--alle`, `20261106T213756Z` `--alle` |
| Zeit (MEZ) | 06.11., 22:25 bis 22:31 (mit Bau des Images) | 06.11., 22:31 bis 22:43 |
| Rückgabe | 0; 0; 0 | 0; 0 |
| Laufzeit laut Bericht | **Erstlauf 145,0 s, Folgelauf 144,2 s**, dritter Lauf 0,03 s (alle sechs Quellen „nicht fällig“) | **Erstlauf 334,9 s, Folgelauf 306,6 s** |
| Wandzeit mit Containerstart | 148,4 s; 147,4 s; 1,8 s | 338,0 s; 310,0 s |
| davon INKAR laut Laufprotokoll | 126,5 s; 126,6 s (nach E49: 95,1 s; 96,4 s) | 284,8 s; 256,9 s (VG250: 50,1 s; 49,6 s; nach E49 INKAR 244,2 s; 215,3 s) |
| Rechnerlast 1/5/15 min vor dem Lauf | 4,51/3,40/3,23; 2,47/3,08/3,15; 1,99/2,67/2,98 | 3,57/2,95/3,05; 2,64/2,49/2,79 |
| Rechnerlast 1/5/15 min nach dem Lauf | 2,47/3,08/3,15; 1,99/2,67/2,98; 1,99/2,67/2,98 | 2,64/2,49/2,79; 2,16/2,29/2,62 |
| Geometrien | 882 Gebäude, 413 Gemeinden, 18 Kreise | 11 103 Gemeindeflächen (VG250-WFS des BKG) |
| Amt für Statistik (E48) | 413 Bevölkerungs- und 413 Flächenwerte, zusammen 826 Zeilen, 2 Indikatoren, 413 Gemeinden; Zeitbezug 2024 bis 2025; im zweiten Lauf unverändert | – |
| XLSX des Amts | Datei laut Seite `SB_A01-04_00_2025j01_BB.xlsx`; schon im Erstlauf „unverändert seit dem letzten Abruf“ (bedingter Abruf, Antwort 304: die Datei lag aus den Läufen nach E49 im Zwischenspeicher `cache/`, nicht in git, nicht in diesem Ordner) | – |
| INKAR nach `dashboard_data_de` | 62 929 Zeilen neu, im zweiten Lauf 62 929 unverändert; Zeitbezug 1995 bis 2023; Hinweise „Abgelegte Datei, kein Abruf“ und „robots_freigabe konfiguriert, nicht genutzt“ | 1 640 420 Zeilen neu, im zweiten Lauf 1 640 420 unverändert; Zeitbezug 1995 bis 2023; dieselben Hinweise |
| INKAR-Indikatornamen (Regel aus E40) | 9, davon 5 mit Bereich „(LRB)“ (51 477 der 62 929 Zeilen) | dieselben 9 (1 345 471 der 1 640 420 Zeilen mit Bereich) |
| Zeilen verworfen, zurückgehalten oder zusammengeführt | 0 (keine Quelle angehalten oder unvollständig; INKAR gelesen = neu = 62 929; `zurueckgehalten` überall 0) | 0 (gelesen = neu = 1 640 420) |
| Doppelte Zielschlüssel in `dashboard_data_de` | 0 | 0 |
| Register `pipeline_meta.bestand` | INKAR 62 929 Zeilen, alle mit Quellschlüssel, alle verschieden; Bevölkerung und Fläche je 413 | INKAR 1 640 420, alle mit Quellschlüssel, alle verschieden; VG250 11 103 |
| `table_metadata` | 14 Zeilen (9 INKAR, 2 Amt für Statistik, 3 LGB) | 10 Zeilen (9 INKAR, 1 BKG) |
| Gebietsschlüssel mit Fläche | 413 von 413 | 10 946 von 10 978 (wie nach E47 und E49) |
| Flächenprüfung | 413 Gemeinden, Median 0,005 %, höchstens 0,398 % (Toleranz 0,5 %) | – |
| `aktualit` (E47) | Hinweis „882 Werte in aktualit als Datum ohne Zeitzonenkennung Z übernommen“ in beiden vollen Läufen | – |
| Warnungen | keine | keine |
| Katalog (E46) | Erstlauf: Hinweis „`public.source_granularities` gibt es in dieser Datenbank nicht“; Folgeläufe ohne Änderung ohne Aufruf | ebenso |
| höchste Probe von `docker stats` | 134,0 MiB (72 Proben); 123,7 MiB (72 Proben); dritter Lauf keine Probe (Container nach 1,8 s beendet, bevor die Probenschleife ihn sah) | 90,5 MiB (164 Proben); 96,2 MiB (150 Proben) |
| `memory.peak` der cgroup (Bytes → MiB) | 609 202 176 → 581,0 MiB; 190 083 072 → 181,3 MiB; dritter Lauf 42 721 280 → 40,7 MiB | 102 019 072 → 97,3 MiB; 351 899 648 → 335,6 MiB |
| Datenbank danach | 73 MB | 1 132 MB (`pipeline_meta.bestand` 564 MB, `pipeline_meta.aenderung` 307 MB, `dashboard_data_de` 209 MB, `"Kommunale Gebiete Deutschland"` 35 MB) |

Alle Zahlen sind aus den Rohdateien in diesem Ordner nachgerechnet: Laufzeiten aus den Berichten (`*.txt`, `*.json`)
und `ablauf.txt`, Zählungen aus `datenbank-auszug.txt` und den Zählern in den Berichten, Speicher aus
`speicher-lauf<n>.txt` (höchster Wert der Spalte `MemUsage`) und der Zeile `cgroup memory.peak` in
`konsole-lauf<n>.txt`.

**Gegenüber E49:** Die Abschnitte „Kennzahlen“, „Indikatornamen“, „Doppelte Zielschlüssel“, „Register“,
„Beispiele“ und „table_metadata“ in `quellen/datenbank-auszug.txt` und `deutschland/datenbank-auszug.txt` sind
zeilengleich mit dem Prüfstand nach E49 (mit `diff` verglichen). Die Zählungen haben sich durch die Änderungen in
E50 (K1, W4 bis W7) nicht geändert.

**Speicher, Messverfahren** wie nach E46 bis E49: `docker stats --no-stream` in einer Schleife mit 1 s Pause (Median
des Probenabstands je Lauf 2,03 s; `docker stats` zeigt den Speicher der cgroup ohne inaktiven Seitencache) und am
Ende jedes Laufs `/sys/fs/cgroup/memory.peak` (Höchststand des Kernels einschließlich Seitencache; für die Grenze von
1 GiB zählt dieser Wert). Seitencache am Ende (`file` in `memory.stat`): `quellen` 416,8, 15,7 und 7,8 MiB,
Deutschland 1,9 und 241,0 MiB. Der Deutschland-Folgelauf hat damit einen höheren `memory.peak` als nach E49 (335,6
statt 98,6 MiB), ohne höhere Probe von `docker stats` (96,2 MiB); der Unterschied ist Seitencache. Nach E46 war im
Deutschland-Folgelauf auch die Probe von `docker stats` einmal hoch (365,9 MiB, Ursache nicht belegt); das trat hier
nicht auf. `memory.peak` bleibt in allen Läufen unter 60 %
der Grenze.

## Lauf im Compose-Setup von MOSIDI (Wiederholung der Läufe vom 03.11. und nach E46, E47 und E49)

Ordner [`mosidi-compose/`](mosidi-compose/), Ablauf `mosidi-compose/lauf.sh` (seit E51 in [`../pruefstand-2026-11-07-e51/mosidi-compose/lauf.sh`](../pruefstand-2026-11-07-e51/mosidi-compose/lauf.sh); die Fassung
aus dem Prüfstand nach E49, mit `git mv` übernommen; geändert sind Kopf, Kommentare, Imagename, Projektname und die
Zeilen zur Namensauflösung im Container), 06.11.2026, 22:43 bis 22:50 MEZ. MOSIDI-ORG/MOSIDI wurde für diesen
Prüfstand um 22:15 MEZ frisch und öffentlich geklont (`git clone --depth 1 https://github.com/MOSIDI-ORG/MOSIDI`):
Commit `26cadbba3d6223c84872987104fc737359bf8bfc` vom 02.11.2026, derselbe wie am 03., 05. und 06.11. Benutzt sind die
unveränderte `docker-compose.yml` von MOSIDI und das Overlay
[`deploy/mosidi/docker-compose.pipeline.yml`](../../deploy/mosidi/docker-compose.pipeline.yml), so wie
[`deploy/mosidi/README.md`](../../deploy/mosidi/README.md) es beschreibt, mit eigenem Compose-Projektnamen
(`gip-mosidi-e50-<pid>`), zufälligen Passwörtern und danach `down -v` (keine Container, Volumes oder `.env` übrig,
nachgesehen nach dem Lauf).

Abweichungen vom unveränderten Compose, alle im Test-Override von `lauf.sh`, wie nach E46 bis E49:

- `brandenburg_db`: Volume unter `/var/lib/postgresql` statt `/var/lib/postgresql/data` (sonst startet PostgreSQL 18
  nicht, unten), keine Freigabe von Port 5432 nach außen, eigener Containername statt des festen `brandenburg_db`.
- Pipeline-Dienste: Image `geodaten-import-pipeline:e50-beleg` (ID in `mosidi-compose/ablauf.txt`, dasselbe wie in
  den Belegläufen) statt des Tags `:lokal` aus dem Overlay; Berichtsordner im Ausgabeordner statt im Repository; INKAR
  aus `cache/inkar_2025.zip` per `PIPELINE_INKAR_DATEI`, die beiden gesperrten Rechner im Container auf `0.0.0.0`.
- `.env` von MOSIDI: `POSTGRES_DB=brandenburg`, `POSTGRES_USER=admin`, die Passwörter zufällig; `pg_tileserv.env`
  leer. Compose warnt deshalb, dass `GEOSERVER_ADMIN` und `GEOSERVER_PASSWORD` nicht gesetzt sind (in
  `konsole-lauf<n>.err.txt`; nur die Namen, keine Werte); GeoServer startet nicht mit.
- Datenbank: PostgreSQL 18.6, PostGIS 3.6.4 (`postgis/postgis` ohne Tag, wie in MOSIDI).
- Testaufbau: Schema der Bestandstabellen aus `sql/mosidi/001_bestand.sql` (unverändert), danach als Administrator
  die Materialized View `source_granularities` mit ihren beiden Indizes, wörtlich aus MOSIDI
  `services/backend/src/db_table_metadata/script.py`, Zeilen 262 bis 272 (sha256 `7eec19e3…` in `ablauf.txt`,
  derselbe Ausschnitt wie nach E47 und E49).

Ergebnis:

| | |
|---|---|
| Unverändertes `brandenburg_db` auf frischem Volume | startet nicht: nach 30 s Status `restarting`, 9 Neustarts, Meldung „in 18+, these Docker images are configured to store database data in a format which is compatible with pg_ctlcluster …“ ([`befund-postgresql18.txt`](mosidi-compose/befund-postgresql18.txt)), wie am 03.11. und nach E46, E47 und E49 |
| `pipeline-einrichten` | Rückgabe 0; Rollen `pipeline_import` und `mosidi_lesen` ohne Superuser-, CREATEDB- oder CREATEROLE-Recht; Spaltenrechte in [`einrichten.log`](mosidi-compose/einrichten.log); Eigentümer von View und Funktion ist `admin`, `SECURITY DEFINER` |
| Lauf 1 `--alle` (`20261106T214503Z`) | **Rückgabe 0**, 145,6 s laut Bericht (Wandzeit 149,1 s, 1-Minuten-Last davor 5,14, danach 2,16), INKAR 126,7 s; 882 Gebäude, 413 Gemeinden, 18 Kreise, 413 + 413 Werte des Amts für Statistik, 62 929 INKAR-Werte; **„Katalog: public.source_granularities aktualisiert“**, die View hatte vorher 0 Zeilen, danach 11 (9 INKAR, 2 Amt für Statistik, Gemeindeebene), wie nach E49 |
| Lauf 2 `--alle` (`20261106T214732Z`) | **Rückgabe 0**, 142,4 s laut Bericht (Wandzeit 145,5 s, Last danach 1,98), INKAR 125,4 s; alles unverändert, kein Aufruf des Katalogs, `pipeline_meta.katalog_offen` leer, View weiter 11 Zeilen |
| Datenbank danach | 0 doppelte Zielschlüssel, `table_metadata` 14 Zeilen, in `public` 39 Tabellen, 2 Views, 1 Materialized View, 25 Sequenzen ([`datenbank-auszug.txt`](mosidi-compose/datenbank-auszug.txt)) |
| Bestandsschema `public` (Antworten 27, 29) | `pg_dump --schema-only --schema=public --no-privileges --no-owner` vor `einrichten` und nach Lauf 2 gleich (2 527 Zeilen, sha256 `2a70acee…` in `ablauf.txt`, derselbe Wert wie nach E46, E47 und E49; die Dumps liegen nicht bei). Die Rechte in `public` ändert `einrichten` wie vorgesehen (`einrichten.log`); sie sind in diesem Vergleich ausgenommen |

Der Abschnitt „Schreibrechte“ im Datenbankauszug zählt nur Rechte auf ganze Tabellen (SELECT auf 5, DELETE auf
`dashboard_data_de`); INSERT und UPDATE vergibt `einrichten` spaltenweise, sie stehen in `einrichten.log`.

## INKAR-Vollumfang (Befund W1 „Mengennachweis“)

**Frage.** Antwort 33: „Umfang und Raumebenen der INKAR-Daten ergeben sich aus den bestehenden Skripten und deren
Konfiguration (inkar_import/config.xml), die als Ausgangsbasis dienen.“ Die Belegläufe oben laden fünf INKAR-Kürzel.
Dieser Lauf lädt den ganzen Umfang, den der Import der TH vorgibt, mit der Pipeline dieses Stands, und zählt nach.

**Was der Import der TH vorgibt** (MOSIDI-ORG/MOSIDI, frischer Klon vom 06.11.2026, 22:15 MEZ, Commit
`26cadbba3d6223c84872987104fc737359bf8bfc` vom 02.11.2026, `services/backend/src/inkar_import`):

- `config.xml` enthält nur Spaltenzuordnungen: Abschnitt `indicator` (ab Z. 2) mit den CSV-Spalten Bereich, ID,
  Indikator, Raumbezug, Kennziffer (SQL-Typ `integer`, Z. 36), Name, Zeitbezug, Wert, und Abschnitt `metadata`
  (ab Z. 62) mit neun Spalten der Indikatorenübersicht. Sie nennt keinen Indikator, keine Raumebene und kein Land.
- Den Umfang legt `inkar_db_import.py` fest: nur Zeilen mit `Raumbezug == 'Gemeinden'` (Z. 107, mit dem Kommentar,
  das könne entfallen, sobald Geometrien anderer Raumeinheiten vorliegen); keine Auswahl nach Indikator, Kürzel,
  Kennziffer oder Jahr, also alle Indikatoren aller Gemeinden Deutschlands und alle Jahre. Dazu liest es das Blatt ZOM
  der Indikatorenübersicht nach `dashboard_data_metadata` (Z. 160, Tabelle Z. 187). Die Auswahl der Projektregion
  (`InProjectRegionOnly`, zehn Landkreise) steht nur im Versionsvergleich `inkar_version_comparison.py`, nicht im Import.

**Soll-Zählung ohne Pipeline.** [`inkar-vollumfang/soll_zaehlen.py`](inkar-vollumfang/soll_zaehlen.py) (nur
Standardbibliothek) liest `cache/inkar_2025.zip` als Datenstrom und zählt, was dieser Import übernähme; Ergebnis
[`inkar-vollumfang/soll-zaehlung.txt`](inkar-vollumfang/soll-zaehlung.txt) (07.11.2026, 01:44 MEZ, 114 s, mit der
endgültigen Fassung des Skripts; dasselbe Ergebnis wie ein erster Aufruf am 06.11. um 22:20 MEZ vor dem Lauf; die letzten
beiden Zeilen stammen vom Aufrufskript, das nicht beiliegt). Die Datei hat 63 426 864 Zeilen in 45 Raumbezügen; davon
**33 547 606 Zeilen mit Raumbezug Gemeinden**, alle mit achtstelliger Kennziffer, Wert und Zeitbezug; 10 978
Gemeinden, 264 Kürzel in 355 Reihen (Bereich, Kürzel, Indikator), 355 Indikatornamen nach der Regel aus E40, Zeitbezug
1995 bis 2024.

**Lauf.** Prüfkonfiguration [`inkar-vollumfang/vollumfang.yaml`](inkar-vollumfang/vollumfang.yaml) (nicht unter
`config/`, nur lesbar eingehängt; sha256 in `ablauf.txt`): eine INKAR-Quelle mit `raumbezug: Gemeinden`,
`indikatoren: alle`, `kennziffer_beginnt: ""`, `zeitbezug: alle`, Ziel und Schlüssel wie in `config/deutschland.yaml`.
Abweichend davon: keine VG250-Quelle und kein `ziel.gebiet` (gemessen wird nur INKAR), `karte: false` und
`zeitbudget_min: 240` statt 90, damit der Lauf die Menge misst und nicht am Budget abbricht. Aufruf
`beleg.sh beispielberichte/pruefstand-2026-11-06-e50/inkar-vollumfang/vollumfang.yaml <Ordner> --alle`, frische
Datenbank wie oben, Grenze 1 GiB unverändert.

| | Ergebnis ([`inkar-vollumfang/`](inkar-vollumfang/)) |
|---|---|
| Lauf | `20261106T215119Z`, 06.11.2026 22:51 bis 07.11.2026 01:18 MEZ (Datenbankauszug bis 01:23) |
| Rückgabe | 0; Status `ok`, keine Warnung, nicht unvollständig, nichts angehalten |
| Laufzeit laut Bericht | **8 792,7 s (146,5 min)**; Wandzeit 8 796,2 s; 1-Minuten-Last davor 3,88, danach 2,60 |
| Zeilen | gelesen = neu = **33 547 606**; geändert, gelöscht, zurückgehalten, übernommen 0 |
| Raumebene | eine: `granularity = Gemeindeebene`, 33 547 606 Zeilen, 10 978 Kennziffern, Zeitbezug 1995 bis 2024 |
| Indikatoren | 355 Indikatornamen (E40), je Name die Zeilenzahl im Datenbankauszug |
| Soll-/Ist je Indikatorname | [`inkar-vollumfang/abgleich.py`](inkar-vollumfang/abgleich.py) gegen die Soll-Zählung: 355 von 355 Namen mit gleicher Zeilenzahl, keiner fehlt, keiner zusätzlich ([`abgleich.txt`](inkar-vollumfang/abgleich.txt)) |
| Doppelte Zielschlüssel | 0 |
| Register `pipeline_meta.bestand` | 33 547 606 Zeilen, alle mit Quellschlüssel, alle verschieden |
| `table_metadata` | 355 Zeilen (eine je Indikatorname) |
| Speicher | höchste Probe von `docker stats` **37,1 MiB** (4 205 Proben, Median-Abstand 2,12 s); `memory.peak` der cgroup 198 602 752 Bytes = **189,4 MiB** (Seitencache am Ende 18,7 MiB) |
| Datenbank danach | **25 GB** (`pipeline_meta.bestand` 13 GB, `pipeline_meta.aenderung` 7 380 MB, `dashboard_data_de` 4 683 MB); während des Laufs nach eigenen Stichproben von `pg_database_size` bis rund 53 GB (Zwischentabellen der Transaktion) |
| Kein Abruf | Hinweis „Abgelegte Datei, kein Abruf: inkar_2025.zip“, `letzte_abfrage` leer, Namensauflösung im Container wie oben (`0.0.0.0`); die Prüfkonfiguration hat keine `robots_freigabe`, darum fehlt der Hinweis „nicht genutzt“ |

**Wo die Zeit bleibt** (eigene Stichproben von `pg_stat_activity` während des Laufs, nicht beigelegt, Minuten
gerundet): Lesen der Datei und `COPY` in die Eingangstabelle rund 10 min, Bilden und Vergleichen der neuen Zeilen
rund 33 min, Schreiben nach `dashboard_data_de` wenige Minuten, Register `pipeline_meta.bestand` rund 83 min
(Datenbank wartet überwiegend auf Lesen von Datenseiten, PostgreSQL mit Standardeinstellungen, `shared_buffers`
128 MB), Änderungsprotokoll `pipeline_meta.aenderung` rund 16 min. Der Speicher der Pipeline bleibt klein, weil sie
streamt; die Last liegt in der Datenbank.

**Soll-/Ist-Tabelle** (Soll laut Antworten 32 und 33, dazu 42 und 49, und den Skripten der TH; Ist nur, was in diesem Prüfstand
belegt ist):

| Bereich | Soll | Ist (belegt) | Zu Projektbeginn anzupassen |
|---|---|---|---|
| INKAR, Indikatoren | alle (keine Auswahl im Import der TH): 264 Kürzel, 355 Reihen | Vollumfang: alle 355 Reihen, 33 547 606 Zeilen, Abgleich je Name gleich. Ausgelieferte Konfiguration: 5 Kürzel (9 Namen) | **seit E51 umgesetzt:** Die Lieferkonfiguration `config/quellen.yaml` lädt INKAR im Vollumfang (`indikatoren: alle`, ganz Deutschland, alle Jahre) als Standard; die reduzierte Fassung ist die benannte Prüfkonfiguration `config/pruefkonfiguration.yaml` |
| INKAR, Raumebenen | nur Gemeinden (fest im Code, Z. 107); die Datei hat 45 Raumbezüge | Gemeinden, `granularity = Gemeindeebene`. Je Raumbezug ist eine eigene Quelle nötig; andere Raumbezüge sind nicht gelaufen | nur wenn die TH weitere Raumebenen will: je Raumbezug eine Quelle mit eigener `granularity`, Kennzifferlänge und Geometrietabelle (die es in MOSIDI bisher nicht gibt) |
| INKAR, Gebiet | ganz Deutschland (kein Filter) | Vollumfang und `deutschland.yaml`: 10 978 Gemeinden. `quellen.yaml`: nur Brandenburg (413) | **seit E51:** Lieferkonfiguration ganz Deutschland wie der Import der TH (`kennziffer_beginnt: ""`); Brandenburg nur noch in der Prüfkonfiguration |
| INKAR, Jahre | alle | 1995 bis 2024 (Vollumfang); die fünf Kürzel der Belegläufe reichen bis 2023 | – |
| INKAR, Spalten und Schlüssel | `config.xml`: Kennziffer als `integer` (führende Null geht verloren), Indikator als Langtext ohne Bereich; danach entfernt der Import ID, Raumbezug, Bereich und Name | Kennziffer achtstellig als Text, Indikatorname nach E40 (Langtext, außer ZOM mit Bereich in Klammern), `source`, `granularity`, `data_type`; 0 doppelte Zielschlüssel | Form der Kennziffer und Namensregel mit der TH abstimmen (Klärungspunkte im Datenmodell) |
| INKAR, Metadaten | Blatt ZOM der Indikatorenübersicht nach `dashboard_data_metadata` (Z. 160, 187) | **nicht umgesetzt**: Die Pipeline schreibt `dashboard_data_metadata` nicht; sie schreibt je Indikatorname einen Satz in `table_metadata` (355) | Übernahme des Blatts ZOM nach `dashboard_data_metadata` bauen oder mit der TH klären, dass `table_metadata` genügt |
| INKAR, Abruf | automatisch per URL (Antwort 33) | per URL nur mit Attrappen getestet (E50); alle Läufe aus der abgelegten Datei | Erlaubnis des BBSR schriftlich (AP 1); erster Abruf per URL im Betrieb der TH |
| INKAR, Laufzeit | – (nicht vorgegeben) | Vollumfang 146,5 min auf einem parallel genutzten Entwicklungsrechner; ausgeliefert ist `zeitbudget_min: 90` | Im vollen Umfang reicht das ausgelieferte Zeitbudget von 90 min nicht (die Quelle würde zurückgerollt), und der Lauf überschreitet auch den Abbruch des ganzen Laufs nach 2 h (`TimeoutStartSec=2h` in den systemd-Units unter `deploy/systemd/` und `deploy/mosidi/`). Budget und Abbruchzeit anheben oder das Schreiben des Registers beschleunigen (etwa Einstellungen der Datenbank, die die Pipeline bewusst nicht setzt); vorher auf dem Zielrechner messen . **Seit E51:** `zeitbudget_min: 240` (146,5 min plus Download, rund 60 % Zuschlag) und `TimeoutStartSec=7h` in beiden Units (über der Summe der Zeitbudgets der Lieferkonfiguration, 390 min); Folgelauf im Vollumfang und Zielrechner weiter nicht gemessen |
| INKAR, Platte | – | Datenbank 25 GB nach dem Lauf, während des Laufs bis rund 53 GB | Platz auf dem Datenbankrechner der TH prüfen |
| WFS, Dienste und Objektarten (Antwort 32) | Geobasis Brandenburg und weitere Dienste, Objektarten in AP 1 abzustimmen; ganzes Land Brandenburg; skalierbar für Deutschland | LGB: Gemeinden (413) und Kreise (18) landesweit, ALKIS-Gebäude nur Campus (882); BKG: VG250-Gemeinden ganz Deutschland (11 103) als zweiter Standard-WFS | Dienste und Objektarten benennen; ALKIS-Gebäude landesweit ist nicht gelaufen, Menge, Speicher (Inhaltsvergleich doppelter IDs, W5) und Laufzeit vor einer Zusage messen |
| Statistik (Antwort 33, LB 4.1) | Abruf per URL, ersatzweise abgelegte Datei; Tabellen zu Projektbeginn benannt; „CSV-Daten“ (Antworten 42, 49) | XLSX des Statistischen Berichts A I 4 / A V 2 per URL über die Berichtsseite: Bevölkerung und Fläche je Gemeinde, 413 + 413 Werte; `pfad` für eine abgelegte Datei | Tabellen benennen; je Tabelle einen Konfigurationsblock (Blätter, Spaltenköpfe, Summenprüfung); das AfS bietet diese Gemeindetabellen nicht als CSV an (E48) |

**Grenzen.** Ein Lauf auf einem parallel genutzten Entwicklungsrechner; die Laufzeit ist eine Größenordnung. Ein
Folgelauf im Vollumfang (alles unverändert) ist nicht gelaufen. Die Prüfkonfiguration ist keine Lieferung; die
ausgelieferten Konfigurationen sind unverändert (Stand nach E50; seit E51 entspricht die Lieferkonfiguration im
INKAR-Umfang dieser Prüfkonfiguration, die begründeten Unterschiede stehen in `config/quellen.yaml`).

## Abweichungen von der Erwartung

Erwartet war: alle Rückgaben 0; 882 Gebäude, 413 Gemeinden, 18 Kreise; 826 Werte des Amts für Statistik; 62 929
INKAR-Werte; Deutschland 11 103 Gemeindeflächen und 1 640 420 INKAR-Werte; Folgeläufe unverändert; 0 doppelte
Zielschlüssel; 882 Werte `aktualit` umgewandelt. **Alle Zählungen und Rückgaben treffen ein**, im Compose von MOSIDI
ebenso. Abweichungen gibt es nur bei Zeit und Speicher:

1. **INKAR-Schritt langsamer als nach E49** (Laufprotokoll `dauer_s`): Brandenburg 126,5 und 126,6 s statt 95,1 und
   96,4 s (+33 %), Compose von MOSIDI 126,7 und 125,4 s statt 94,8 und 97,3 s, Deutschland 284,8 und 256,9 s statt
   244,2 und 215,3 s (+17 bis 19 %). Die Last war ähnlich (1-Minuten-Last vor den Läufen 2,0 bis 5,1, nach E49 1,6 bis
   4,5). **Ursache, soweit geklärt:** E50 hat für K1 den Vorfilter auf den Rohtext `;Gemeinden;` entfernt; seitdem
   liest der CSV-Parser alle 63 426 864 Zeilen der Datei und prüft jede Zeile vor jedem Filter. Gemessen mit
   [`adapter-zeit/adapter_zeit.py`](adapter-zeit/adapter_zeit.py) (nur der Adapter, ohne Datenbank und ohne Netz,
   Stand nach E49 und nach E50 abwechselnd je zweimal auf demselben Rechner bei 1-Minuten-Last unter 2):
   nach E49 75,3 und 73,1 s, nach E50 90,0 und 90,8 s, also rund 16 s (22 %) mehr ([`adapter-zeit/ergebnis-2026-11-07.txt`](adapter-zeit/ergebnis-2026-11-07.txt)). Das erklärt etwa die Hälfte der rund 31 s Unterschied in Brandenburg; der Rest ist nicht getrennt gemessen (Schreibweg
   mit den Prüfpunkten des Zeitbudgets, W6, oder Last). Am Code ist nichts geändert. Die Laufzeit bleibt im Rahmen der
   Konfiguration (`zeitbudget_min: 90` für INKAR, Brandenburg rund 2 min, Deutschland rund 5 min).
2. **`memory.peak` im Deutschland-Folgelauf 335,6 statt 98,6 MiB**, bei unveränderter höchster Probe von `docker
   stats` (96,2 MiB). Der Unterschied ist Seitencache (`file` am Ende 241,0 MiB), nicht Speicher der Pipeline. Weit unter
   der Grenze von 1 GiB.
3. **INKAR-Vollumfang über dem ausgelieferten Zeitbudget:** 146,5 min gegen `zeitbudget_min: 90` der ausgelieferten
   INKAR-Quellen und gegen `TimeoutStartSec=2h` der systemd-Units. Mit der ausgelieferten Einstellung würde ein
   Vollumfang zurückgerollt. Das ist kein Fehler der Läufe, sondern eine Anpassung vor einem Betrieb im vollen Umfang
   (Soll-/Ist-Tabelle oben; seit E51 vorgenommen: 240 min und 7 h, Nachtrag oben). Die Zählungen des Vollumfangs treffen das Soll genau.
4. **XLSX des Amts schon im Erstlauf „unverändert“:** Die Datei lag aus den Läufen nach E49 im gemeinsamen
   Zwischenspeicher `cache/`; der bedingte Abruf (If-Modified-Since) bekam 304. Nach E49 war der Erstlauf der erste
   Abruf. Die 413 + 413 Werte sind dieselben.

Kein Lauf hat `www.bbr-server.de` abgerufen (Abschnitt oben); ein Abbruch deswegen war nicht nötig.

## Was nicht geprüft ist

- Der Abruf von INKAR per URL (Regelbetrieb seit E50, mit `robots_freigabe`): Er ist nur mit Attrappen getestet. Alle
  Läufe hier lesen `cache/inkar_2025.zip` (434 MB, Stand 13.08.2025); `www.bbr-server.de` haben wir nicht abgerufen.
  Die schriftliche Erlaubnis des BBSR ist offen (AP 1).
- Ein Änderungslauf mit echten Änderungen, eine Übernahme vorhandener Zeilen und die Umstellung einer bestehenden
  Datenbank: Die Folgeläufe hier sind „alles unverändert“, die Datenbanken frisch. Neu, geändert, gelöscht, Übernahme,
  Kürzel- und Stichtagwechsel, Zeitbudget und bestätigte Leerlieferung prüfen die Datenbanktests.
- Die Fehlerpfade aus E44 bis E50 (Abbruch mitten in einer Quelle, scheiternde Karte oder Aufräumen, unlesbare
  INKAR-Zeilen, doppelte WFS-IDs mit abweichendem Inhalt, Zeitbudget, gesperrte Pfade und Rechner, Metadatenkonflikt,
  datenbankweite Sperre u. a.): In diesen Läufen trat keiner auf; sie prüfen die Tests.
- Landesweite WFS-Objektarten über die Verwaltungsgrenzen hinaus (Antwort 32), insbesondere die ALKIS-Gebäude für ganz
  Brandenburg: nicht gelaufen; Speicher und Laufzeit des Inhaltsvergleichs doppelter IDs (W5) sind nur für den Campus
  belegt (Soll-/Ist-Tabelle oben).
- `SORTBY` in Kachelabfragen gegen die echten Dienste (wie nach E47 und E49).
- Im Compose von MOSIDI: Speicher (nicht gemessen), `--haerten`, die übrigen Dienste von MOSIDI (Backend, Frontend,
  GeoServer, nicht gestartet), eine bestehende Datenbank der TH mit Daten und eigenen Rechten.
- Die Laufzeit auf einem ruhigen oder dem Zielrechner.

## Dateien

**Abweichungen der Dateien hier von den Ausgaben der Skripte** (wie nach E47 und E49): `lauf<n>.out` heißt hier
`konsole-lauf<n>.txt`, `lauf<n>.err` (stderr des Aufrufs, hier nur Meldungen von Compose) heißt
`konsole-lauf<n>.err.txt`. Berichte und Quellenverzeichnis liegen direkt im jeweiligen Ordner statt unter `berichte/`.
`speicher-lauf3.txt` in `quellen/` hat nur die Kopfzeile (keine Probe, siehe Tabelle). Nicht beigelegt sind
`build.log` (Bauprotokoll des Images), `schema-public-vorher.txt` und `schema-public-nachher.txt` (Compose-Lauf,
sha256 in `ablauf.txt`), die Sperrdatei des Berichtsordners, die robots.txt-Antworten und der Mitschnitt des Klons.
Alle beigelegten Rohdateien (59: `quellen` 20, `deutschland` 15,
Compose 14, Vollumfang 10) sind byte-gleich mit den Rohausgaben (byteweise verglichen am 07.11.2026). Eigene
Auswertungen, keine Rohausgaben der Skripte: `inkar-vollumfang/soll-zaehlung.txt` (Ausgabe von `soll_zaehlen.py`,
die letzten beiden Zeilen vom Aufrufskript), `inkar-vollumfang/abgleich.txt` (Ausgabe von `abgleich.py`) und
`adapter-zeit/ergebnis-2026-11-07.txt` (Ausgabe von `adapter_zeit.py` mit Kopfzeilen des Aufrufs).

**Die Kartenseiten liegen nicht bei**, ebenso wenig die XLSX des Amts und die INKAR-Datei. Sie enthalten die
importierten Datensätze; Quelldaten werden nicht mit dem Code veröffentlicht (Antwort 69). Die Datenbankauszüge
nennen Zählungen, Indikatornamen und Beispiele des Registers nur als Schlüssel, ohne Werte.

## Stand

- **Teilbäume** (`git write-tree` des Index, vor den Läufen, nach dem letzten Stagen und in allen Protokollen gleich):
  `pipeline` `0ab429565e82cc9995c08ccab8f05ec231dcc88f`, `config` `c6b781315000369f38d5d4c9f67388a6984fb497`, `sql`
  `acacc89bd5167e671bcfb27b511620734f1f55f6`, `tests` `a7f801bebed5cbfb4970f3baed9ecc18a2bf441e`, `Dockerfile`
  `6788a7afeb4041d3c71b517b184d557c44c99762`, `requirements.txt` `3edf4ee3e318de51d0094b6ad08cbc7ddeed8191`.
  Dieselben stehen in den Kopfzeilen von `pruefen.log` und `datenbanktests.log` und, von den Skripten über eine Kopie
  des Index aus dem Arbeitsstand berechnet, aus dem das Image gebaut wurde, in allen vier `*/ablauf.txt`. Es sind die
  Teilbäume aus E50 („Prüfung nach der Nachprüfung“); `sql` (Bestandsschema von MOSIDI byte-gleich), `Dockerfile` und
  `requirements.txt` sind seit E49 unverändert. Die Teilbäume `pipeline`, `tests` und `config` aus E49 gelten nicht
  mehr.
- **Code eingefroren:** Seit den Prüfungen in E50 ist an `pipeline`, `tests`, `config`, `sql`, `Dockerfile` und
  `requirements.txt` nichts geändert; dazugekommen sind dieser Prüfstand, die mit `git mv` übernommenen und angepassten
  Skripte und Dokumentation (README, README.en, `beispielberichte/README.md`, `docs/entscheidungen.md`, `docs/betrieb.md`,
  `deploy/mosidi/README.md`, die READMEs der Prüfstände nach E47 bis E49 und Kommentarzeilen der abgelösten
  Belegskripte bis E47).
- **Overlay für MOSIDI:** `mosidi-compose/ablauf.txt` nennt zusätzlich den Teilbaum `deploy` zur Zeit des Laufs
  (`a10c3b89065cbe11b6a2490669a1a707740e65e4`). Er ändert sich danach nur durch Dokumentation
  (`deploy/mosidi/README.md`); die benutzte Datei `deploy/mosidi/docker-compose.pipeline.yml` ist unverändert, Blob
  `79beb89fd15d5e84d8d2e6f5552009996471a47f` (seit E50, W8, mit `PIPELINE_INKAR_DATEI`; nach E49 war es
  `d332d886…`; nachprüfbar mit `git rev-parse angebot-va-2026-536:deploy/mosidi/docker-compose.pipeline.yml`).
- **Image:** `geodaten-import-pipeline:e50-beleg`, ID `sha256:7a209d15d80c…` in allen Läufen (`build.log` aller drei
  Bauten, `mosidi-compose/ablauf.txt`). Nach allen Läufen und Datenbanktests waren keine Container und Volumes der
  Projekte `gip-beleg-…`, `gip-mosidi-e50-…` und `gip-e42-…` übrig (nachgesehen am 07.11.2026).
- **Nachprüfbar** nach dem Taggen mit `git rev-parse angebot-va-2026-536:pipeline` usw. Unmittelbar vor dem Taggen
  sind die Teilbäume mit `git write-tree` neu zu berechnen; weichen sie ab, gelten diese Belege nicht für den Tag
  (E45, P14).
- **Reihenfolge** (MEZ): Rechnerlast 06.11. 22:14 (2,91), robots.txt 22:15, Klon von MOSIDI 22:15, erste
  Soll-Zählung 22:20, Läufe `quellen` 22:25 bis 22:31 (mit Bau des Images), `deutschland` 22:31 bis 22:43, Compose-Lauf
  22:43 bis 22:50, INKAR-Vollumfang 22:50 bis 07.11. 01:23; danach Dokumentation, Messung des Adapters (01:32 und, mit
  der endgültigen Fassung des Skripts, 01:46), endgültige Soll-Zählung 01:44, Stagen, Datenbanktests PostgreSQL 16 von
  01:52 bis 01:57 und 18 von 01:57 bis 02:01; danach nur diese README und `pruefen.log`; `pruefen.sh` lief nach dem
  letzten Stagen (`pruefen.log`, Zeitpunkt in der Kopfzeile).
