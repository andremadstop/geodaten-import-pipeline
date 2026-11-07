# Prüfstand 07.11.2026, Abgabestand nach E51 (Tests, Lieferkonfiguration im Vollumfang, Wertabgleich je Zeile, Läufe gegen die echten Dienste, Lauf im Compose von MOSIDI)

> **Nachtrag 08.11.2026:** Als Abgabestand abgelöst durch den Stand nach E52, Prüfstand
> [`../pruefstand-2026-11-08-e52/`](../pruefstand-2026-11-08-e52/) (Tests, Prüfkonfiguration, Compose von MOSIDI). Der
> Vollumfang, der Wertabgleich und `deutschland` sind bis auf Weiteres hier belegt (Verhalten vor E52). Sonst ist diese
> Datei unverändert.
>
> **Nachtrag 09.11.2026:** Vollumfang und Wertabgleich sind jetzt auch am Stand nach E52 belegt
> ([`../pruefstand-2026-11-08-e52/`](../pruefstand-2026-11-08-e52/), Abschnitt „Vollumfang“; dort überspringt der
> Folgelauf die unveränderte INKAR-Datei). Hier bleiben belegt: `deutschland` und der Folgelauf mit vollem Vergleich im
> Vollumfang (159,7 min). Sonst ist diese Datei weiter unverändert.

Das ist der Prüfstand des Abgabestands (Tag `angebot-va-2026-536`, E43): Stand nach E51 einschließlich der
Nachprüfung zu E51 ([`docs/entscheidungen.md`](../../docs/entscheidungen.md), E51). Der Code ist eingefroren; während
dieses Prüfstands hat sich an `pipeline`, `tests`, `config`, `sql`, `Dockerfile`, `deploy` und `requirements.txt` nichts
geändert (Teilbäume unten, vor den Läufen und nach dem letzten Stagen gleich).

Alles in diesem Ordner ist am selben Code-Stand entstanden: die Tests, die Lieferkonfiguration `config/quellen.yaml`
(seit E51 mit INKAR im Vollumfang) in drei Läufen, ein Wertabgleich jeder INKAR-Zeile gegen die Datenbank (Befund W4),
die Prüfkonfiguration `config/pruefkonfiguration.yaml` (der Inhalt von `config/quellen.yaml` bis E50) zum Vergleich mit
den Prüfständen bis E50, `config/deutschland.yaml` und der Lauf im Compose-Setup von MOSIDI mit der
Katalogaktualisierung. Er löst [`../pruefstand-2026-11-06-e50/`](../pruefstand-2026-11-06-e50/) ab; dort stehen die
Läufe am Stand nach E50.

**Kurz:** Alle Läufe enden mit Rückgabe 0, ohne Warnung, mit 0 doppelten Zielschlüsseln. Die Lieferkonfiguration im
Vollumfang lädt 33 547 606 INKAR-Zeilen (355 Indikatornamen, 10 978 Gemeinden, 1995 bis 2024) im Erstlauf in 129,7 min,
der Folgelauf findet alles unverändert in 159,7 min; beide bleiben unter dem Zeitbudget von 240 min, kein Budget griff.
Der Wertabgleich findet für jede der 33 547 606 Zeilen der Quelle denselben Schlüssel und denselben Wert in der
Datenbank: 0 fehlend, 0 überzählig, 0 abweichend. Prüfkonfiguration, Deutschland und Compose von MOSIDI liefern
dieselben Zählungen wie nach E50 (882/413/18, 826, 62 929; 11 103 und 1 640 420). INKAR kommt in allen Läufen aus der
abgelegten Datei; kein Lauf hat `www.bbr-server.de` abgerufen.

## robots.txt je Rechner

Vor den Läufen ist für jeden Rechner, den ein Lauf, der Bau des Images, `pruefen.sh` oder der Klon von MOSIDI abrufen
kann, einmal die `robots.txt` abgerufen worden (07.11.2026, 04:17 UTC, 05:17 MEZ; je eine Anfrage, `curl`). Die Regeln
sind gegen die tatsächlich abgerufenen Pfade geprüft (Platzhalter `*` und `$` wie in RFC 9309, längste passende Regel
gewinnt). Antwortet ein Rechner auf `/robots.txt` mit einem Status 4xx, gilt die Datei nach RFC 9309 (Abschnitt
2.3.1.3) als nicht vorhanden; dann gibt es keine Einschränkung. Die Antworten sind dieselben wie am 06.11.2026 (e50).

| Rechner | Wofür | `robots.txt` | Ergebnis |
|---|---|---|---|
| `isk.geobasis-bb.de` | WFS der LGB: Gebäude, Gemeinden, Kreise (`quellen.yaml`, `pruefkonfiguration.yaml`) | 404 | erlaubt (RFC 9309: keine Datei, keine Einschränkung) |
| `www.statistik-berlin-brandenburg.de` | Seite des Statistischen Berichts A I 4 / A V 2 (`seite`) | `Disallow: /scrivito/` | `/a-i-4-a-v-2-j/` erlaubt |
| `download.statistik-berlin-brandenburg.de` | XLSX-Datei des Berichts (`link_rechner`) | 403 des Speichers | erlaubt (RFC 9309: Status 4xx heißt „nicht verfügbar“, kein Verbot) |
| `sgx.geodatenzentrum.de` | VG250-WFS des BKG (`deutschland.yaml`) | `Disallow: /gdz_geoviewserver/`, `/gdz_geoviewserv/` | `/wfs_vg250` erlaubt |
| `www.bbr-server.de` | INKAR (alle drei Konfigurationen, mit `robots_freigabe`) | **nicht abgerufen, auch nicht die `robots.txt`**; Stand der letzten Prüfung (06.11.2026, 10:52 UTC, Prüfstand nach E49): `Disallow: /` | **gesperrt, nicht abgerufen.** Unsere Läufe rufen den Rechner nie ab. INKAR kommt aus `cache/inkar_2025.zip` per `PIPELINE_INKAR_DATEI` (schreibgeschützt eingehängt), der Rechner löst im Container auf `0.0.0.0` auf |
| `www.regionalstatistik.de` | nirgends konfiguriert (bis E47 Bevölkerung und Fläche) | `Disallow: /` (Prüfung zu E48) | **gesperrt, nicht abgerufen**, auch nicht die `robots.txt`; im Code gesperrt (`ROBOTS_GESPERRT`), im Container auf `0.0.0.0` |
| `pypi.org` | Paketindex: `pruefen.sh` (uv, uvx, pip-audit) und die Datenbanktests (uv); der Bau des Images kam aus dem Zwischenspeicher von Docker (unten) | `Disallow: /simple/`, `/packages/`, `/pypi/*/json` u. a. | genutzt als dokumentierte Paketschnittstelle für Installer (E49, „PyPI und robots.txt“), wie nach E49 und E50 |
| `files.pythonhosted.org` | Paketdateien (`pruefen.sh`, Datenbanktests) | 404 | erlaubt (RFC 9309) |
| `deb.debian.org` | `apt-get` im Bau des Images | 404 | erlaubt (RFC 9309); nicht abgerufen, der Schritt kam aus dem Zwischenspeicher |
| `github.com` | Klon von MOSIDI-ORG/MOSIDI (`git clone --depth 1`) | viele Regeln, darunter `Disallow: /*.git$`; Gruppe `*` und Gruppe `ClaudeBot` | erlaubt: Klon über `https://github.com/MOSIDI-ORG/MOSIDI` ohne `.git`; abgerufen wurden nur `GET /MOSIDI-ORG/MOSIDI/info/refs?service=git-upload-pack` (1) und `POST /MOSIDI-ORG/MOSIDI/git-upload-pack` (2), in keiner Gruppe gesperrt (Mitschnitt mit `GIT_TRACE_CURL`, nur die Anfragezeilen ausgewertet) |

Nicht abgerufen: Docker Hub und `deb.debian.org`. Das Basisimage (`python:3.12-slim`, per Digest) und beide
PostGIS-Images lagen lokal; der Bau des Images nahm `apt-get` und `pip install` aus dem Zwischenspeicher von Docker
(„Using cache“, kein `Pulling`). Netz brauchten nur die Belegläufe selbst; die Auswertungen danach (Wertabgleich,
Nachrechnen) liefen ohne Netz. Die `letzte_abfrage` aller Berichte nennt nur `isk.geobasis-bb.de` (WFS-Pfade `/ows/…`),
`download.statistik-berlin-brandenburg.de` (XLSX) und `sgx.geodatenzentrum.de` (`/wfs_vg250`).

## Kein Abruf von `www.bbr-server.de`

Alle drei Konfigurationen tragen für INKAR `robots_freigabe` (Regelbetrieb der TH, Antwort 33). Für unsere Läufe gilt
die Regel aus `docs/betrieb.md`: Jeder eigene Lauf setzt `PIPELINE_INKAR_DATEI`, die abgelegte Datei hat Vorrang vor der
Freigabe. Belegt in jedem Lauf, der INKAR geladen hat (sieben; der dritte `quellen`-Lauf lud keine Quelle):

| Beleg | Wo | Ergebnis |
|---|---|---|
| Hinweis der Pipeline | Text- und JSON-Bericht jeder INKAR-Quelle | „Abgelegte Datei, kein Abruf: inkar_2025.zip“ und „robots_freigabe konfiguriert, nicht genutzt (abgelegte Datei)“, in allen sieben Läufen |
| Keine genutzte Freigabe | JSON-Berichte | kein `info.robots_freigabe`, keine Warnung „abgerufen mit der Freigabe“, `warnungen` aller INKAR-Quellen leer |
| `letzte_abfrage` | JSON-Berichte | bei INKAR leer; `bbr-server` kommt in keinem Laufbericht vor (`grep -c` über alle `2026*.json` und `2026*.txt`: 0), nur im Quellenverzeichnis als konfigurierte `adresse` |
| Namensauflösung im Container | `ablauf.txt` jedes Ordners, Zeilen „Namensauflösung im Container“ | `www.bbr-server.de -> 0.0.0.0`, `www.regionalstatistik.de -> 0.0.0.0` (`getent ahostsv4` im Dienst `pipeline` mit denselben `extra_hosts` wie die Läufe), in allen vier Ordnern |

## Prüfkette

| Prüfung | Ergebnis | Protokoll |
|---|---|---|
| `./pruefen.sh` (ruff, bandit, pip-audit gegen PyPI, Tests ohne Datenbank, Secret-Scan, Stückliste) am Endstand nach dem letzten Stagen; Zeitpunkt und Teilbäume in der Kopfzeile | ohne Befund, 424 Tests bestanden (die 70 Datenbanktests dort übersprungen, sie laufen getrennt); bandit gibt nur die Warnung aus, dass ein `nosec` in `pipeline/quellen.py` keinen Treffer mehr unterdrückt (wie nach E49 und E50); uv und pip-audit mit PyPI wie in `pruefen.sh` | [`pruefen.log`](pruefen.log) |
| `tests/test_datenbank.py` gegen eine echte PostGIS-Datenbank mit den MOSIDI-Tabellen, `postgis/postgis:16-3.6` (festgeschrieben); Teilbäume in der Kopfzeile | PostgreSQL 16.15: 70 von 70 (07.11.2026, 10:48 bis 10:52 MEZ) | [`datenbanktests.log`](datenbanktests.log) |
| dieselben Tests, `postgis/postgis:latest` | PostgreSQL 18.6: 70 von 70 (10:52 bis 10:57 MEZ, nach PostgreSQL 16) | [`datenbanktests.log`](datenbanktests.log) |

Zusammen 494 Tests (424 ohne, 70 mit Datenbank), dieselben Zahlen wie in E51 („Tests am gestagten Stand nach der Nachprüfung zu E51“). Die Datenbanktests liefen je Version nacheinander in einem frischen Wegwerf-Compose-Projekt aus der `docker-compose.yml`
dieses Repositorys mit zufälligen Passwörtern; Container und Volumes sind danach entfernt. Die Projektnamen
`gip-e42-pg16-…` und `gip-e42-pg18-…` sind nur ein Präfix aus dem Aufruf; maßgeblich sind die Teilbäume in der
Kopfzeile. Sie liefen nach allen Läufen und nach dem Wertabgleich, nicht parallel zu ihnen.

## Rahmen der Läufe

Alle Läufe liefen auf einem Entwicklungsrechner (Linux, Docker, 16 Kerne, 62 GB Arbeitsspeicher), der währenddessen
auch für andere Arbeit genutzt wurde. Vor jedem Lauf prüften die Skripte die 1-Minuten-Last (Schwelle 8, sonst bis zu
20 min warten; neu in `beleg.sh` und `lauf.sh`): Kein Lauf musste warten (Zeilen „Wartezeit“ in `ablauf.txt`, je 0 s).
Vor den Läufen lag die Last zwischen 1,65 und 6,04, nach ihnen zwischen 1,45 und 7,08. **Während der beiden langen
Läufe stieg sie zeitweise deutlich:** Die eigenen Proben alle 5 min
([`quellen/proben-platte-last.txt`](quellen/proben-platte-last.txt)) zeigen in Lauf 1 bis 26,97 (06:36 MEZ) und in
Lauf 2 bis 32,18 (09:21 MEZ). Die Prüfung im Skript regelt nur den Start eines Laufs. Die Laufzeiten sind
Größenordnungen auf einem belasteten Rechner, keine Messung auf einem ruhigen oder dem Zielrechner.

Die Datenbank war jeweils frisch, in einem Wegwerf-Compose-Projekt aus der `docker-compose.yml` dieses Repositorys
(PostgreSQL 16.15, PostGIS 3.6.4, Schema der MOSIDI-Tabellen aus `sql/mosidi/`). Die Zugangsdaten wurden zufällig
erzeugt und danach gelöscht, Container und Volumes sind entfernt. Die Pipeline lief als Container aus dem Image dieses
Stands (`geodaten-import-pipeline:e51-beleg`, je Konfiguration neu gebaut, in allen Bauten dieselbe Image-ID
`sha256:a16c14674574…`) mit `mem_limit: 1g` (1 GiB) wie in der Compose-Datei.

Ablauf: [`beleg.sh`](beleg.sh), die Fassung aus dem Prüfstand nach E50, mit `git mv` übernommen. Geändert sind Kopf,
Kommentare, Imagename, der Teilbaum `deploy` in `ablauf.txt`, das Warten auf die Rechnerlast und die Ausfuhr der
INKAR-Zeilen nach Lauf 1 (`WERTE_EXPORT=1`). Aufrufe, nacheinander:

    WERTE_EXPORT=1 beleg.sh pruefkonfiguration <Ordner> --alle
    beleg.sh deutschland <Ordner> --alle -- --alle
    mosidi-compose/lauf.sh <MOSIDI-Klon> <Ordner>
    WERTE_EXPORT=1 beleg.sh quellen <Ordner> --alle -- --alle -- .

Laufzeiten auf eine Nachkommastelle gerundet (kaufmännisch; die Rohwerte stehen in den Berichten). Minuten sind aus
Sekunden gerechnet (÷ 60).

## Lieferkonfiguration `config/quellen.yaml` im Vollumfang (Befunde W2 und W4)

Seit E51 ist der Vollumfang der Lieferstandard: INKAR mit allen Indikatoren aller Gemeinden Deutschlands, alle Jahre
(`indikatoren: alle`, `kennziffer_beginnt: ""`, `zeitbezug: alle`, `zeitbudget_min: 240`), daneben die fünf übrigen
Quellen (LGB-WFS und XLSX des Amts für Statistik) wie bisher. Drei Läufe wie in den Prüfständen bis E50: `--alle`,
noch einmal `--alle` (Folgelauf, alles unverändert) und ohne Argumente (nur fällige Quellen).

| | Lauf 1 `--alle` | Lauf 2 `--alle` (Folgelauf) | Lauf 3 ohne Argumente |
|---|---|---|---|
| Bericht | [`20261107T044222Z`](quellen/20261107T044222Z.txt) | [`20261107T065227Z`](quellen/20261107T065227Z.txt) | [`20261107T093214Z`](quellen/20261107T093214Z.txt) |
| Zeit (MEZ) | 05:42 bis 07:52 | 07:52 bis 10:32 | 10:32 |
| Rückgabe | 0 | 0 | 0 |
| Laufzeit laut Bericht | **7 783,1 s (129,7 min)** | **9 582,8 s (159,7 min)** | 0,1 s (alle sechs Quellen „nicht fällig“) |
| Wandzeit mit Containerstart | 7 787,1 s | 9 587,8 s | 2,9 s |
| davon INKAR laut Laufprotokoll (`dauer_s`) | 7 765,5 s (129,4 min, 54 % des Budgets von 240 min) | 9 493,0 s (158,2 min, 66 % des Budgets) | – |
| übrige fünf Quellen zusammen | 17,5 s | 89,7 s | – |
| Rechnerlast 1/5/15 min davor | 2,13/1,87/1,85 | 3,84/5,90/6,17 | 6,04/5,93/8,26 |
| Rechnerlast 1/5/15 min danach | 3,70/6,03/6,21 | 6,04/5,93/8,26 | 7,08/6,15/8,32 |
| höchste 1-Minuten-Last während des Laufs (Proben alle 5 min) | 26,97 | 32,18 | – |
| INKAR | 33 547 606 gelesen = neu; geändert, gelöscht, übernommen, zurückgehalten 0 | 33 547 606 gelesen = unverändert; sonst 0 | nicht fällig (Rhythmus monatlich) |
| übrige Quellen | 882 Gebäude, 413 Gemeinden, 18 Kreise, 413 + 413 Werte des Amts für Statistik neu | alle unverändert | nicht fällig |
| höchste Probe von `docker stats` | 112,7 MiB (3 746 Proben, Median-Abstand 2,06 s) | 122,6 MiB (4 599 Proben, 2,07 s) | 44,8 MiB (1 Probe) |
| `memory.peak` der cgroup (Bytes → MiB) | 131 358 720 → 125,3 MiB (Seitencache am Ende 25,9 MiB) | 479 735 808 → 457,5 MiB (26,1 MiB) | 61 145 088 → 58,3 MiB (23,1 MiB) |
| Datenbank, Proben alle 5 min | bis mindestens 65 GB (07:51) | bis mindestens 66 GB (10:12 bis 10:32) | – |
| Warnungen | keine | keine | – |

**Hält die Zeitgrenze aus E51?** Ja, in diesem Prüfstand. INKAR blieb in beiden Läufen unter `zeitbudget_min: 240`
(höchstens 158,2 min, 66 %), der ganze Lauf unter `TimeoutStartSec=7h` (höchstens 159,7 von 420 min); keine Quelle
wurde wegen des Budgets oder einer Datenbank-Zeitgrenze zurückgerollt (kein „Zeitbudget“ in Berichten und Protokollen).
Der Folgelauf dauert aber **länger als der Erstlauf und länger als die 146,5 min aus dem Prüfstand nach E50**
(Abschnitt „Abweichungen“). Der Abstand zum Budget beträgt im Folgelauf rund 82 min; der Download per URL (rund 430 MB)
ist weiter nicht gemessen und käme im Regelbetrieb hinzu. Am Code ist nichts geändert.

Nach dem letzten Lauf ([`quellen/datenbank-auszug.txt`](quellen/datenbank-auszug.txt)): INKAR 33 547 606 Zeilen,
`granularity = Gemeindeebene`, 355 Indikatornamen, 10 978 Kennziffern, Zeitbezug 1995 bis 2024; dazu 826 Zeilen des
Amts für Statistik; 0 doppelte Zielschlüssel; Register `pipeline_meta.bestand` für INKAR 33 547 606 Zeilen, alle mit
Quellschlüssel, alle verschieden; `table_metadata` 360 Zeilen (355 INKAR, 2 Amt für Statistik, 3 LGB); Datenbank 24 GB
(`pipeline_meta.bestand` 12 GB, `pipeline_meta.aenderung` 7 037 MB, `dashboard_data_de` 4 683 MB). Die Zählungen je
Indikatorname im Auszug sind dieselben wie im Vollumfangslauf nach E50 (355 von 355, mit `diff` verglichen); der
Katalog meldet wie dort, dass es `public.source_granularities` in dieser Datenbank nicht gibt.

### Wertabgleich je Zeile (Befund W4)

Nach E50 war der Vollumfang nur je Indikatorname belegt (Zeilenzahlen; `abgleich.py` im Prüfstand nach E50 vergleicht
keine Werte). Hier ist jede Zeile geprüft:

- **Ausfuhr:** `beleg.sh` mit `WERTE_EXPORT=1` führt nach Lauf 1, bevor Lauf 2 startet, alle INKAR-Zeilen von
  `dashboard_data_de` aus (Kennziffer, Indikator, Zeitbezug, Wert als Text; `\copy … (FORMAT csv)`): 33 547 606 Zeilen,
  sha256 der entpackten CSV in [`quellen/ablauf.txt`](quellen/ablauf.txt). Die Datei enthält echte Quelldaten und liegt
  nicht bei (Antwort 69).
- **Skript:** [`wertabgleich/wertabgleich.py`](wertabgleich/wertabgleich.py), nur Standardbibliothek (`csv`,
  `zipfile`, `gzip`, `decimal`), ohne Code und Konfiguration der Pipeline. Eigene Lesart der INKAR-CSV: Trennzeichen
  `;`, Kopfzeile, Felder ohne Rand; übernommen werden wie in der Lieferkonfiguration Raumbezug genau „Gemeinden“,
  Kennziffer aus acht Ziffern, alle Länder, alle Kürzel, alle Jahre, Wert und Zeitbezug nicht leer; Indikatorname nach
  E40 (Langtext, außerhalb von ZOM mit dem Bereich in Klammern) im Skript nachgebaut. `zipfile` liest nur das
  Inhaltsverzeichnis: Die CSV im ZIP ist mit Deflate64 gepackt (Methode 9), das `zipfile` nicht entpacken kann; gelesen
  wird sie als Datenstrom über `unzip -p`. Verglichen wird Land für Land (erste zwei Stellen der Kennziffer), damit nicht
  alle 33,5 Mio. Schlüssel gleichzeitig im Speicher liegen.
- **Schlüssel und Typ:** Schlüssel (Kennziffer, Indikator, Zeitbezug) wie `ziel.schluessel`; Kennziffer und Indikator
  als Text, genau wie sie stehen (die Kennziffer also achtstellig mit führender Null), Zeitbezug als ganze Zahl
  (Spalte `INTEGER`). Werte: Die Quelle schreibt Dezimalkomma ohne Tausendertrenner, die Zielspalte ist `NUMERIC`;
  beide Seiten werden exakt als `Decimal` verglichen, nie über Gleitkomma. Jede Rundung zählte also als Abweichung.
- **Ergebnis** ([`wertabgleich/ergebnis-vollumfang.txt`](wertabgleich/ergebnis-vollumfang.txt), 346 s, höchster
  Speicher des Prozesses 4,5 GiB): 63 426 864 Zeilen der Datei, keine mit falscher Feldzahl; 33 547 606 im Raumbezug
  Gemeinden, alle übernommen (kein Ausschluss nach Kennziffer, Wert oder Zeitbezug), kein Zielschlüssel doppelt;
  in der Datenbank 33 547 606 Zeilen, kein Schlüssel doppelt. **Verglichen 33 547 606, fehlend 0, überzählig 0,
  abweichend 0.** Davon textgleich (Komma durch Punkt ersetzt) 20 909 838, als Zahl gleich bei anderer Schreibweise
  12 637 768, und zwar alle nur durch weggefallene nachgestellte Nullen der Nachkommastellen (`NUMERIC` speichert „6,20“
  als `6.2`); eine andere Schreibweise kommt nicht vor. Je Land nachgerechnet: Die 16 Teilsummen ergeben 33 547 606.
- **Gegenprobe** mit der Prüfkonfiguration (`--kennziffer-beginnt 12 --kuerzel …`, Ausfuhr aus dem Lauf
  `pruefkonfiguration/`): 62 929 verglichen, 0/0/0, 29 759 nur mit weggefallenen Nullen
  ([`wertabgleich/ergebnis-pruefkonfiguration.txt`](wertabgleich/ergebnis-pruefkonfiguration.txt)). Beide Protokolle
  stammen von der endgültigen Fassung des Skripts.

Grenzen: Der Abgleich prüft die Zieltabelle nach Lauf 1, nicht das Register und nicht die Metadaten. Er prüft die Regeln
so, wie sie in der Konfiguration und in E40 beschrieben sind; ein gemeinsamer Irrtum in dieser Beschreibung fiele nicht
auf. Ob die TH die Kennziffer achtstellig erwartet (ihr Import legt sie bei 77 % der Zeilen siebenstellig ab, E51),
beantwortet er nicht.

## Prüfkonfiguration, Deutschland, Compose von MOSIDI (Vergleich mit E50)

| | Prüfkonfiguration `config/pruefkonfiguration.yaml` (Brandenburg) | `config/deutschland.yaml` | Compose von MOSIDI (Prüfkonfiguration) |
|---|---|---|---|
| Läufe | [`pruefkonfiguration/`](pruefkonfiguration/): `20261107T041848Z` `--alle` | [`deutschland/`](deutschland/): `20261107T042423Z`, `20261107T042951Z`, je `--alle` | [`mosidi-compose/`](mosidi-compose/): `20261107T043632Z`, `20261107T043901Z`, je `--alle` |
| Zeit (MEZ) | 05:18 bis 05:21 (mit Bau des Images) | 05:23 bis 05:35 | 05:35 bis 05:41 |
| Rückgabe | 0 | 0; 0 | `pipeline-einrichten` 0; Läufe 0; 0 |
| Laufzeit laut Bericht | 146,8 s (nach E50: 145,0 s) | 325,6 s; 290,2 s (nach E50: 334,9 s; 306,6 s) | 145,4 s; 141,8 s (nach E50: 145,6 s; 142,4 s) |
| Wandzeit mit Containerstart | 150,0 s | 328,5 s; 292,7 s | 148,0 s; 144,3 s |
| davon INKAR laut Laufprotokoll | 128,5 s (nach E50: 126,5 s) | 277,7 s; 241,9 s (VG250: 47,9 s; 48,3 s) | 127,8 s; 124,9 s |
| Rechnerlast 1/5/15 min davor | 3,49/2,32/1,98 | 2,69/2,09/1,95; 1,79/1,76/1,84 | 2,96/2,05/1,91; 1,65/1,81/1,84 |
| Rechnerlast 1/5/15 min danach | 1,66/1,97/1,90 | 1,79/1,76/1,84; 1,71/1,78/1,83 | 1,65/1,81/1,84; 1,45/1,71/1,80 |
| Zählungen | 882 Gebäude, 413 Gemeinden, 18 Kreise; 413 + 413 Werte des Amts für Statistik (826 Zeilen, 2024 bis 2025); 62 929 INKAR-Werte (9 Indikatornamen, 413 Gemeinden, 1995 bis 2023) | 11 103 Gemeindeflächen (VG250); 1 640 420 INKAR-Werte (9 Namen, 10 978 Kennziffern); im zweiten Lauf alles unverändert | wie Prüfkonfiguration; im zweiten Lauf alles unverändert |
| Vergleich mit E50 | Abschnitte „Kennzahlen“ bis „table_metadata“ von `datenbank-auszug.txt` zeilengleich mit `pruefstand-2026-11-06-e50/quellen/` (`diff`) | zeilengleich mit `pruefstand-2026-11-06-e50/deutschland/` | zeilengleich mit `pruefstand-2026-11-06-e50/mosidi-compose/` |
| Doppelte Zielschlüssel | 0 | 0 | 0 |
| `table_metadata` | 14 Zeilen | 10 Zeilen | 14 Zeilen |
| Gebietsschlüssel mit Fläche | 413 von 413; Flächenprüfung Median 0,005 %, höchstens 0,398 % | 10 946 von 10 978 (wie nach E47 bis E50) | 413 von 413 |
| `aktualit` (E47) | 882 Werte umgewandelt | – | 882 je Lauf |
| XLSX des Amts | „unverändert seit dem letzten Abruf“ (bedingter Abruf, die Datei lag in `cache/`), wie nach E50 | – | ebenso |
| höchste Probe von `docker stats` | 123,0 MiB (73 Proben, 2,03 s) | 95,2 MiB (160 Proben); 96,3 MiB (143 Proben) | nicht gemessen (wie bisher) |
| `memory.peak` der cgroup | 447 930 368 → 427,2 MiB (Seitencache am Ende 258,5 MiB) | 103 186 432 → 98,4 MiB; 106 090 496 → 101,2 MiB | nicht gemessen |
| Datenbank danach | 73 MB | 1 132 MB | – |
| Katalog (E46) | Hinweis „`public.source_granularities` gibt es in dieser Datenbank nicht“ | ebenso | **„Katalog: public.source_granularities aktualisiert“**, View 0 → 11 Zeilen (9 INKAR, 2 Amt für Statistik); Lauf 2 ohne Aufruf, `katalog_offen` 0 |
| Warnungen | keine | keine | keine |

**Compose von MOSIDI** ([`mosidi-compose/lauf.sh`](mosidi-compose/lauf.sh), die Fassung aus dem Prüfstand nach E50 mit
`git mv` übernommen; geändert sind Kopf, Kommentare, Imagename, Projektname `gip-mosidi-e51-<pid>`, das Warten auf die
Rechnerlast und die Konfiguration der Läufe). MOSIDI-ORG/MOSIDI wurde um 05:17 MEZ frisch und öffentlich geklont
(`git clone --depth 1 https://github.com/MOSIDI-ORG/MOSIDI`): **Commit `26cadbba3d6223c84872987104fc737359bf8bfc` vom
02.11.2026**, derselbe wie am 03., 05. und 06.11. Benutzt sind die unveränderte `docker-compose.yml` von MOSIDI und das
Overlay [`deploy/mosidi/docker-compose.pipeline.yml`](../../deploy/mosidi/docker-compose.pipeline.yml), mit eigenem
Projektnamen, zufälligen Passwörtern und danach `down -v` (keine Container, Volumes oder `.env` übrig, nachgesehen).
Abweichungen vom unveränderten Compose stehen wie nach E46 bis E50 nur im Test-Override (Volume unter
`/var/lib/postgresql`, keine Portfreigabe, eigener Containername, Image dieses Stands, Berichtsordner außerhalb des
Repositorys, INKAR aus der abgelegten Datei, die beiden gesperrten Rechner auf `0.0.0.0`). **Neu und anders als nach
E50:** Die beiden Läufe rufen `--config /app/config/pruefkonfiguration.yaml` auf, nicht den Standard des Overlays
(`config/quellen.yaml`, seit E51 der Vollumfang). Damit bleibt der Lauf mit den Compose-Läufen bis E50 vergleichbar;
ein Vollumfang im Compose von MOSIDI ist nicht gemessen. `pipeline-einrichten` lief mit dem Standard des Overlays
(beide Konfigurationen haben dieselben Zieltabellen).

| | |
|---|---|
| Unverändertes `brandenburg_db` auf frischem Volume | startet nicht: nach 30 s Status `restarting`, 9 Neustarts, PostgreSQL 18.6, Meldung „in 18+, these Docker images are configured to store database data in a format which is compatible with pg_ctlcluster …“ ([`befund-postgresql18.txt`](mosidi-compose/befund-postgresql18.txt)), wie seit dem 03.11. |
| Datenbank im Test-Override | PostgreSQL 18.6, PostGIS 3.6.4; Bestandsschema aus `sql/mosidi/001_bestand.sql` (unverändert) Rückgabe 0; View `source_granularities` wörtlich aus MOSIDI `services/backend/src/db_table_metadata/script.py`, Zeilen 262 bis 272, sha256 `7eec19e3…` (derselbe Ausschnitt wie nach E47 bis E50) |
| `pipeline-einrichten` | Rückgabe 0; Rollen `pipeline_import` und `mosidi_lesen` ohne Superuser-, CREATEDB- oder CREATEROLE-Recht; Eigentümer von View und Funktion `admin`, `SECURITY DEFINER` |
| Bestandsschema `public` (Antworten 27, 29) | `pg_dump --schema-only --schema=public --no-privileges --no-owner` vor `einrichten` und nach Lauf 2 gleich: 2 527 Zeilen, sha256 `2a70acee…` (derselbe Wert wie nach E46 bis E50); in `public` 39 Tabellen, 2 Views, 1 Materialized View, 25 Sequenzen |

## Abweichungen von der Erwartung

Erwartet war: alle Rückgaben 0; Vollumfang 33 547 606 Zeilen, Folgelauf unverändert, kein Budgetabbruch; Wertabgleich
0/0/0; Prüfkonfiguration, Deutschland und Compose mit den Zählungen nach E50; 0 doppelte Zielschlüssel. **Alle
Zählungen, Rückgaben und der Wertabgleich treffen ein.** Abweichungen:

1. **Folgelauf im Vollumfang länger als der Erstlauf:** 159,7 min (INKAR 158,2 min) gegen 129,7 min (INKAR 129,4 min),
   und länger als die 146,5 min des Vollumfangslaufs nach E50. Im Budget (66 %), aber über dem gemessenen Wert, auf dem
   die 240 min beruhen. Die Last war in Lauf 2 höher (davor 3,84 statt 2,13, Spitze 32,18 statt 26,97); auch die
   kleinen Quellen brauchten in Lauf 2 länger (89,7 statt 17,5 s), was eher für Last als für den Folgelauf selbst
   spricht. Getrennt gemessen ist die Ursache nicht (eigene Stichprobe von `pg_stat_activity` um 10:22 MEZ: der
   Vergleich der neuen Zeilen mit `dashboard_data_de` lief seit rund 6 min). Am Code ist nichts geändert.
2. **Erstlauf schneller als nach E50** (129,7 statt 146,5 min) bei sonst gleicher INKAR-Menge; die Messungen sind
   Größenordnungen auf einem parallel genutzten Rechner. Daraus folgt kein kleineres Budget.
3. **Platte über dem dokumentierten Wert:** Die Datenbank wuchs während der Läufe auf mindestens 65 GB (Lauf 1) und
   66 GB (Lauf 2), gemessen nur alle 5 min, also eine Untergrenze; dokumentiert waren nach E50 „bis rund 53 GB“ (dort
   aus eigenen Stichproben im Lauf mit INKAR allein). Nach dem Lauf 24 GB. Freier Platz auf dem Rechner sank auf 112 GB (von 197 GB).
   Nachgezogen in E51, `docs/betrieb.md`, README, README.en und als datierter Nachtrag in den Kopfkommentaren von
   `beleg.sh` und `mosidi-compose/lauf.sh`; `config/quellen.yaml` (Kommentar) und `deploy/mosidi/README.md` nannten bis zum
   Prüfbericht vom 07.11., 12:48, noch 53 GB; seither nachgezogen (Abschnitt Stand, „Nach dem Prüfbericht vom 07.11. 12:48“).
4. **Compose von MOSIDI mit der Prüfkonfiguration** statt mit dem Standard des Overlays (oben). Nach E50 war die
   Lieferkonfiguration noch die reduzierte Fassung; seit E51 ist ein Lauf im Compose mit der Lieferkonfiguration ein
   Vollumfang von Stunden, und er ist nicht gemessen.
5. **`memory.peak` der Prüfkonfiguration 427,2 statt 581,0 MiB**, Folgelauf im Vollumfang 457,5 MiB: Der Unterschied
   ist Seitencache; die höchsten Proben von `docker stats` (bis 123,0 MiB) liegen wie bisher weit unter 1 GiB.
6. **XLSX des Amts schon im Erstlauf „unverändert“** wie nach E50 (304 auf den bedingten Abruf, Datei aus `cache/`).

Kein Lauf hat `www.bbr-server.de` abgerufen; ein Abbruch deswegen war nicht nötig.

## Soll-/Ist-Tabelle (Stand nach E51)

Soll laut Antworten 32 und 33, dazu 42 und 49, und den Skripten der TH (MOSIDI-Commit `26cadbb`,
`services/backend/src/inkar_import`, Herleitung im Prüfstand nach E50); Ist nur, was in diesem Prüfstand belegt ist.

| Bereich | Soll | Ist (belegt) | Zu Projektbeginn anzupassen |
|---|---|---|---|
| INKAR, Indikatoren | alle (keine Auswahl im Import der TH): 264 Kürzel, 355 Reihen | **Lieferstandard seit E51:** `config/quellen.yaml` lädt alle 355 Reihen, 33 547 606 Zeilen; je Zeile Schlüssel und Wert gleich der Quelle (Wertabgleich 0/0/0). Prüfkonfiguration: 5 Kürzel (9 Namen) | – |
| INKAR, Raumebenen | nur Gemeinden (fest im Code der TH); die Datei hat 45 Raumbezüge | Gemeinden, `granularity = Gemeindeebene` | nur wenn die TH weitere Raumebenen will: je Raumbezug eine Quelle mit eigener `granularity`, Kennzifferlänge und Geometrietabelle |
| INKAR, Gebiet | ganz Deutschland | Lieferkonfiguration: 10 978 Gemeinden aus allen 16 Ländern; Prüfkonfiguration Brandenburg (413) | – |
| INKAR, Jahre | alle | 1995 bis 2024 | – |
| INKAR, Spalten und Schlüssel | `config.xml`: Kennziffer als `integer` (führende Null geht verloren), Indikator als Langtext ohne Bereich | Kennziffer achtstellig als Text (im Wertabgleich auch die Länder 01 bis 09 mit führender Null), Indikatorname nach E40; 0 doppelte Zielschlüssel | Form der Kennziffer und Namensregel mit der TH abstimmen (E51, Nachprüfung) |
| INKAR, Werte | wie in der Datei | `NUMERIC`, als Zahl gleich in allen 33 547 606 Zeilen; nachgestellte Nullen fallen weg (12 637 768 Zeilen) | – |
| INKAR, Metadaten | Blatt ZOM nach `dashboard_data_metadata` | **nicht umgesetzt**: je Indikatorname ein Satz in `table_metadata` (355) | bauen oder mit der TH klären, dass `table_metadata` genügt |
| INKAR, Abruf | automatisch per URL (Antwort 33) | per URL nur mit Attrappen getestet; alle Läufe aus der abgelegten Datei | Erlaubnis des BBSR schriftlich (AP 1); erster Abruf per URL im Abnahmelauf (AP 8, eigene Umgebung, Antwort 53) |
| INKAR, Laufzeit | – (nicht vorgegeben) | Erstlauf 129,7 min, Folgelauf 159,7 min (INKAR 129,4 und 158,2 min) gegen `zeitbudget_min: 240` und `TimeoutStartSec=7h`; kein Budgetabbruch; belasteter Entwicklungsrechner | auf dem Zielrechner messen (TH, nach der Übergabe, Antwort 53); Download per URL kommt hinzu |
| INKAR, Platte | – | Datenbank 24 GB nach den Läufen, während der Läufe mindestens 66 GB | Platz auf dem Datenbankrechner der TH prüfen (mit Reserve über 66 GB) |
| WFS, Dienste und Objektarten (Antwort 32) | Geobasis Brandenburg und weitere Dienste, Objektarten in AP 1; ganzes Land; skalierbar für Deutschland | LGB: Gemeinden (413) und Kreise (18) landesweit, ALKIS-Gebäude nur Campus (882); BKG: VG250 ganz Deutschland (11 103) | Dienste und Objektarten benennen; ALKIS-Gebäude landesweit vor einer Zusage messen |
| Statistik (Antwort 33, LB 4.1) | Abruf per URL, ersatzweise Datei; Tabellen zu Projektbeginn; „CSV-Daten“ (Antworten 42, 49) | XLSX des Berichts A I 4 / A V 2 per URL über die Berichtsseite: 413 + 413 Werte | Tabellen benennen; das AfS bietet diese Gemeindetabellen nicht als CSV an (E48) |

## Was nicht geprüft ist

- Der Abruf von INKAR per URL (Regelbetrieb, mit `robots_freigabe`): nur mit Attrappen getestet. Alle Läufe lesen
  `cache/inkar_2025.zip` (434 MB, Stand 13.08.2025); die schriftliche Erlaubnis des BBSR ist offen (AP 1).
- Ein Änderungslauf mit echten Änderungen im Vollumfang, eine Übernahme vorhandener Zeilen, die Umstellung einer
  bestehenden Datenbank; die Folgeläufe hier sind „alles unverändert“. Diese Fälle prüfen die Datenbanktests.
- Der Vollumfang im Compose von MOSIDI und gegen PostgreSQL 18; der Speicher im Compose von MOSIDI.
- Die Katalogaktualisierung (`REFRESH` von `source_granularities`) nach einem Vollumfang: In `beleg.sh` gibt es die
  View nicht, im Compose-Lauf lief nur die Prüfkonfiguration.
- Die Fehlerpfade aus E44 bis E51 (Zeitbudget, Datenbank-Zeitgrenzen, Fußzeilen, `gml:id` u. a.): In diesen Läufen trat
  keiner auf; sie prüfen die Tests.
- Landesweite WFS-Objektarten über die Verwaltungsgrenzen hinaus, `SORTBY` gegen die echten Dienste, `@gml:id` gegen
  einen echten Dienst.
- Die Laufzeit auf einem ruhigen oder dem Zielrechner.

## Dateien

**Abweichungen der Dateien hier von den Ausgaben der Skripte** (wie nach E47 bis E50): `lauf<n>.out` heißt hier
`konsole-lauf<n>.txt`, `lauf<n>.err` (stderr, hier nur Meldungen von Compose) heißt `konsole-lauf<n>.err.txt`.
Berichte und Quellenverzeichnis liegen direkt im jeweiligen Ordner statt unter `berichte/`. `speicher-lauf3.txt` in
`quellen/` hat eine Probe. Nicht beigelegt sind `build.log`, `schema-public-vorher.txt` und
`schema-public-nachher.txt` (Compose-Lauf, sha256 in `ablauf.txt`), die Ausfuhren `werte-nach-lauf1.csv.gz` und die
Zwischendateien des Wertabgleichs (echte Quelldaten), die robots.txt-Antworten und der Mitschnitt des Klons. Die
Rohdateien sind unverändert aus den Ausgabeordnern kopiert (`cp -p`). In `beleg.sh` und `mosidi-compose/lauf.sh` ist nach
den Läufen nur eine Kommentarzeile im Kopf nachgetragen (Platte mindestens 66 GB); der Code der Skripte ist der, mit dem
die Läufe entstanden sind. Eigene Auswertungen, keine Ausgaben von
`beleg.sh` oder `lauf.sh`: `quellen/proben-platte-last.txt` (Proben von Platte, Last und Datenbankgröße mit einer
Kopfzeile), `wertabgleich/ergebnis-*.txt` (Ausgaben von `wertabgleich.py`, unverändert).

**Die Kartenseiten liegen nicht bei**, ebenso wenig die XLSX des Amts und die INKAR-Datei. Sie enthalten die
importierten Datensätze; Quelldaten werden nicht mit dem Code veröffentlicht (Antwort 69). Die Datenbankauszüge nennen
Zählungen, Indikatornamen und Beispiele des Registers nur als Schlüssel, die Protokolle des Wertabgleichs Zählungen und
höchstens zehn Schlüssel je Fehlerart, keine Werte.

## Stand

- **Teilbäume** (`git write-tree` des Index, vor den Läufen, nach dem letzten Stagen vor den Doku-Änderungen vom 07.11.
  nachmittags und abends, und in allen Protokollen gleich):
  `pipeline` `34175c77b6918e1253e93c1a5ae6eb0b66843b50`, `config` `99237d43e77e50e9fc5764d22afd8dd21bd98144`, `sql`
  `acacc89bd5167e671bcfb27b511620734f1f55f6`, `tests` `a0630aa744ec8bf57127fa89ad712ffc7baab474`, `Dockerfile`
  `6788a7afeb4041d3c71b517b184d557c44c99762`, `deploy` `81041b9892c335ad271544f60e228fca6de4781e`, `requirements.txt`
  `3edf4ee3e318de51d0094b6ad08cbc7ddeed8191`. Dieselben stehen in den Kopfzeilen von `pruefen.log` und
  `datenbanktests.log` und, von den Skripten über eine Kopie des Index aus dem Arbeitsstand berechnet, aus dem das Image
  gebaut wurde, in allen vier `*/ablauf.txt`. Es sind die finalen Teilbäume aus E51 („Nachprüfung zu E51“). `sql`
  (Bestandsschema von MOSIDI byte-gleich), `Dockerfile` und `requirements.txt` sind seit E49 unverändert.
- **Code eingefroren:** Während dieses Prüfstands ist an `pipeline`, `tests`, `config`, `sql`, `Dockerfile`, `deploy` und
  `requirements.txt` nichts geändert; dazugekommen sind dieser Prüfstand, die mit `git mv` übernommenen und angepassten
  Skripte und Dokumentation (README, README.en, `beispielberichte/README.md`, `docs/entscheidungen.md`, `docs/betrieb.md`,
  `docs/rundgang.md`, das README des Prüfstands nach E50 und Kommentarzeilen der abgelösten Belegskripte bis E47).
- **Nach dem Prüfbericht vom 07.11., 12:48 (nur Doku, Verhalten gleich):** Nach den Läufen dieses Prüfstands sind in
  `config/quellen.yaml` nur Kommentare geändert (Messstand e51 statt 146,5 min / 53 GB, Folgelauf jetzt gemessen,
  Umgang mit einem Widerspruch des BBSR wie in der Risikotabelle des Angebots) und in `deploy/` nur Doku und
  Kommentare (`deploy/mosidi/README.md`: Messstand e51, Lauf vom 07.11., Datenbanktests 70 von 70, Gebietsprüfung
  „bei konfigurierter Gebietstabelle“, Restarbeit Katalog-Zeitlimit; Kommentarzeilen der beiden Units: gemessene
  Laufzeiten). `yaml.safe_load` von `config/quellen.yaml` ist vorher und nachher gleich (sha256 des sortierten JSON
  `4165126e…`), die Direktiven beider Units sind unverändert, das Overlay-Blob bleibt `79beb89f…`. Teilbäume nach dieser
  Änderung: `config` `ed88e5c91942fdcc8da82acf05af62e52a7700b6`, `deploy` `113ab1cc3b617e0f26d1743f3f5e59a93a52d86b`;
  `pipeline`, `tests`, `sql`, `Dockerfile` und `requirements.txt` unverändert (oben). Die Kopfzeilen von `pruefen.log`, `datenbanktests.log` und `*/ablauf.txt`
  nennen die Teilbäume vor dieser Doku-Änderung (`config` `99237d43…`, `deploy` `81041b98…`); das Verhalten der Läufe
  ist davon nicht berührt. Dazu README und README.en (Gebietsprüfung „bei konfigurierter Gebietstabelle“,
  INKAR-Lizenzzeile „Vollumfang“ statt „Auszug Brandenburg“) und dieser Absatz; `./pruefen.sh` danach erneut grün.
- **Nachtrag 07.11. abends (nur Doku und Kommentare, Verhalten gleich):** `config/pruefkonfiguration.yaml` trägt zur
  `robots_freigabe` denselben Kommentar wie `config/quellen.yaml` (bis dahin „Entfernen, sobald das BBSR widerspricht“);
  die Kommentarzeile beider Units nennt die Laufzeit der fünf kleinen Quellen als Summe („zusammen 17,5 bzw. 89,7 s“);
  `docs/sicherheit.md` und `docs/entscheidungen.md` nachgezogen (Freigabe bei Widerspruch, nicht erfasste Rechte bei
  `einrichten`). `yaml.safe_load` der Prüfkonfiguration ist vorher und nachher gleich, die Direktiven beider Units sind
  gleich, das Overlay-Blob bleibt `79beb89f…`. Teilbäume seither: `config` `812638b33371f5a9cfd08bb2c71674220798ed68`,
  `deploy` `eace70b2b1071dc3644eec588f2c1f51a2b3b7a4`; `pipeline`, `tests`, `sql`, `Dockerfile` und `requirements.txt`
  unverändert; `./pruefen.sh` danach erneut grün.
- **Image:** `geodaten-import-pipeline:e51-beleg`, ID `sha256:a16c14674574…` in allen Bauten (`build.log`,
  `mosidi-compose/ablauf.txt`). Nach allen Läufen und Datenbanktests waren keine Container und Volumes der Projekte
  `gip-beleg-…`, `gip-mosidi-e51-…` und `gip-e42-…` übrig (nachgesehen am 07.11.2026).
- **Nachprüfbar** nach dem Taggen mit `git rev-parse angebot-va-2026-536:pipeline` usw. Unmittelbar vor dem Taggen
  sind die Teilbäume mit `git write-tree` neu zu berechnen; weichen sie ab, gelten diese Belege nicht für den Tag
  (E45, P14), es sei denn, die Abweichung ist nur die in den beiden Absätzen oben belegte Doku-Änderung (`config`
  `812638b3…`, `deploy` `eace70b2…`, übrige Teilbäume gleich).
- **Reihenfolge** (MEZ, 07.11.2026): Rechnerlast 05:18 (2,74), robots.txt 05:17, Klon von MOSIDI 05:17, Prüfkonfiguration
  05:18 bis 05:21 (mit Bau des Images), Deutschland 05:23 bis 05:35, Compose-Lauf 05:35 bis 05:41, Lieferkonfiguration
  05:41 bis 10:38 (Lauf 1 bis 07:52, Ausfuhr, Lauf 2 bis 10:32, Lauf 3, Datenbankauszug), Gegenprobe des
  Wertabgleichs 10:39, Wertabgleich des Vollumfangs 10:41 bis 10:47, Stagen, Datenbanktests PostgreSQL 16 und 18 ab
  10:48 (Zeiten in `datenbanktests.log`); danach nur Dokumentation und `pruefen.log`; `pruefen.sh` lief nach dem
  letzten Stagen (Zeitpunkt in der Kopfzeile).
- **Nachtrag 07.11.2026 (nach `pruefen.log`):** In der Soll-/Ist-Tabelle sind die Zeilen „INKAR, Abruf“ und „INKAR,
  Laufzeit“ im Wortlaut an Antwort 53 angeglichen (erster Abruf per URL im Abnahmelauf in eigener Umgebung, Nachmessung
  auf dem Zielrechner durch die TH). Nur diese Datei; die Code-Teilbäume oben sind unverändert.
