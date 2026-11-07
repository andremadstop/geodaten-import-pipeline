# Prüfstand 05.11.2026, Stand nach E40 und E41

> **Abgelöst durch [`../pruefstand-2026-11-05-e42/`](../pruefstand-2026-11-05-e42/)** (Stand nach E42, zweite Prüfrunde vom
> 05.11.2026) und zuletzt durch [`../pruefstand-2026-11-05-e45/`](../pruefstand-2026-11-05-e45/) (Stand nach E45, Tests und Läufe gegen die echten Dienste), dieser seit 05.11. abgelöst durch [`../pruefstand-2026-11-05-e46/`](../pruefstand-2026-11-05-e46/) (Stand nach E46) und zuletzt durch [`../pruefstand-2026-11-05-e47/`](../pruefstand-2026-11-05-e47/) (Abgabestand nach E47). Die Dateien hier bleiben unverändert; korrigiert sind in diesem README nur die Erklärung zum Speicher und
> die Angaben zum Ablauf (E42), der Abschnitt „Stand“ (E43) und die Verweise auf den Abgabestand (E45). Die Zahlen unten sind die des Stands nach E40/E41,
> nicht die des Abgabestands.

Hier liegen die Belege zur Prüfung vom 05.11.2026, 08:15 (Codex, Lauf 4). E40 bringt den stabilen INKAR-Schlüssel und
setzt `data_type`. E41 behandelt leere CSV-Zeilen, den gleichen Erfolgsstatus in Datenbank und Verzeichnis, das
URL-Schema vor jeder Verbindung und genauere Angaben zum Betrieb. Einzelheiten stehen in
[`docs/entscheidungen.md`](../../docs/entscheidungen.md).

Alle Läufe liefen auf einem Entwicklungsrechner (Linux, Docker). Abweichungen der veröffentlichten Dateien von den
Ausgaben von `beleg.sh` (Nachtrag E42): `lauf<n>.out` ist als `konsole-lauf<n>.txt` umbenannt; `lauf<n>.err` (stderr
des Aufrufs), `build.log` und `einrichten.log` liegen nicht bei; `ablauf.txt` ist von Hand zusammengestellt (anderer
Aufbau als die Ausgabe von `beleg.sh`), die Teilbäume darin stammen aus einer zur Bauzeit gespeicherten Liste;
`aufraeumen` weicht um ein `rmdir` vom ausgeführten Skript ab. Inhaltlich sind die Dateien unverändert (Prüfung vom
05.11.2026, zweite Runde: byte-gleich mit den Rohausgaben). Die Datenbank war jeweils frisch, in einem
Wegwerf-Compose-Projekt aus der `docker-compose.yml` dieses Repositorys (PostgreSQL 16.15, PostGIS 3.6.4, Schema der
MOSIDI-Tabellen aus `sql/mosidi/`). Die Zugangsdaten wurden je Lauf zufällig erzeugt und danach gelöscht; Container
und Volumes sind entfernt. Die Pipeline lief als Container aus dem Image dieses Stands, mit `mem_limit: 1g` wie in der
Compose-Datei. Ablauf: [`beleg.sh`](beleg.sh).

## Belegläufe gegen die echten Dienste

| | Brandenburg (`config/quellen.yaml`) | Deutschland (`config/deutschland.yaml`) |
|---|---|---|
| Läufe | `20261105T092255Z` `--alle`, `20261105T092501Z` `--alle`, `20261105T092707Z` ohne `--alle` | `20261105T092801Z` `--alle`, `20261105T093301Z` `--alle` |
| Laufzeit laut Bericht | 122,2 s; 122,2 s; 0,03 s (alle sechs Quellen „nicht fällig“) | 297,5 s; 252,1 s |
| Wandzeit mit Containerstart | 125,1 s; 125,1 s; 2,6 s | 300,0 s; 254,0 s |
| Geometrien | 882 Gebäude, 413 Gemeinden, 18 Kreise | 11 103 Gemeindeflächen (VG250) |
| INKAR nach `dashboard_data_de` | 62 929 Zeilen neu, im zweiten Lauf 62 929 unverändert | 1 640 420 Zeilen neu, im zweiten Lauf 1 640 420 unverändert |
| INKAR-Indikatornamen (Regel aus E40) | 9: Bevölkerung, Einwohnerdichte, Bevölkerungsentwicklung, Pendlersaldo (ZOM) und Arbeitslose, Bevölkerung gesamt, Bevölkerungsentwicklung (5 Jahre), Einwohnerdichte, Pendlersaldo mit „(LRB)“ | dieselben 9 |
| Zeilen verworfen oder zusammengeführt wegen gleichen Zielschlüssels | 0 (vorher 5 670 zusammengeführt) | 0 (vorher 142 678 übersprungen, Lauf vom 03.11.) |
| Doppelte Zielschlüssel in `dashboard_data_de` | 0 | 0 |
| Register mit Quellschlüssel | 62 929 von 62 929, alle verschieden | 1 640 420 von 1 640 420, alle verschieden |
| Amt für Statistik | 1 239 + 413 Werte. Ausgelassen mit Warnung, alter Stand bliebe (E41): 21 + 7 Zeilen ohne jeden Wert, das sind 7 aufgelöste Gemeinden | – |
| Flächenprüfung | 413 Gemeinden, Median 0,005 %, höchstens 0,161 % (gerundet 0,16 %) | – |
| `table_metadata` | 16 Zeilen (9 INKAR, 4 Amt für Statistik, 3 LGB) | 10 Zeilen (9 INKAR, 1 BKG) |
| Gebietsschlüssel mit Fläche | 413 von 413 | 10 946 von 10 978 |
| höchster abgetasteter Speicher des Pipeline-Containers | 132,6 MiB; 121,7 MiB | 97,0 MiB; 92,2 MiB |
| `memory.peak` der cgroup des Containers | 409,0 MiB; 175,2 MiB | 97,1 MiB; 96,7 MiB |
| Datenbank danach | 74 MB | 1 132 MB (`dashboard_data_de` 209 MB, `pipeline_meta.bestand` 564 MB, `pipeline_meta.aenderung` 307 MB) |

Was die Läufe nicht prüfen: In beiden lag die INKAR-Datei schon im Zwischenspeicher (`cache/inkar_2025.zip`, Stand
13.08.2025). Das BBSR meldete sie auf `If-Modified-Since` als unverändert; der Download von 434 MB ist nicht
mitgemessen. In `deutschland.yaml` ist die Änderungskarte je Quelle abgeschaltet (`karte: false`). Beide Konfigurationen
laden fünf INKAR-Kürzel. Für alle 264 Kürzel Brandenburgs gibt es die Gesamtanalyse der Schlüssel in
[`../inkar-schluessel/`](../inkar-schluessel/) (ohne Datenbanklauf).

**Speicher, Messverfahren:** Die Rohdaten liegen in `*/speicher-lauf<n>.txt`. Gemessen wurde auf zwei Wegen:

- `docker stats --no-stream` auf den Pipeline-Container in einer Schleife mit 1 s Pause. Weil der Aufruf selbst rund
  1 s braucht, liegen die Proben etwa 2 s auseinander: Brandenburg 60 und 61 Proben, Deutschland 146 und 124. `docker
  stats` zeigt den Speicher der cgroup ohne inaktiven Seitencache, wie es auch die frühere Angabe (95,4 MiB) tat.
- Am Ende jedes Laufs liest der Container `/sys/fs/cgroup/memory.peak` aus (Zeile in `konsole-lauf<n>.txt`). Das ist
  der Höchststand des Kernels, einschließlich Seitencache und kurzer Spitzen zwischen den Proben.

Im ersten Brandenburg-Lauf liegt `memory.peak` (409 MiB) deutlich über der höchsten Probe (132,6 MiB). Die Differenz
ist nicht aufgeschlüsselt. Seitencache der INKAR-Datei erklärt sie nicht allein: Deutschland liest dieselbe Datei, dort
liegen `memory.peak` und höchste Probe gleich (97,1 und 97,0 MiB). Die Kartenseite allein auch nicht: Der zweite
Brandenburg-Lauf schreibt dieselbe 8,9-MB-Seite und hat `memory.peak` 175 MiB. (Hier stand bis E42, in Deutschland sei
die Karte aus; tatsächlich schreiben beide Deutschland-Läufe eine Kartenseite, wegen `karte: false` je Quelle ohne
Objekte, 173 KB.) Für die Grenze von 1 GB zählt `memory.peak`. Der Prüfstand nach E42 gibt am Ende jedes Laufs
zusätzlich `memory.stat` aus.

Die Kartenseiten der Läufe liegen hier nicht bei: Sie enthalten die importierten Datensätze (Antwort 69). Der
Datenbankauszug nennt Zählungen und Beispiele des Registers nur als Schlüssel, ohne Werte.

## Prüfkette

| Datei | Was | Ergebnis |
|---|---|---|
| `pruefen.log` | `./pruefen.sh`: ruff, bandit, pip-audit, pytest, Secret-Scan, Stückliste | ohne Befund, 128 Tests bestanden (28 Datenbanktests hier übersprungen, sie laufen getrennt) |
| `datenbanktests.log` | `tests/test_datenbank.py` gegen `postgis/postgis:16-3.6` (festgeschrieben) und `postgis/postgis:latest` | PostgreSQL 16.15: 28 von 28, PostgreSQL 18.6: 28 von 28 |

Weitere Belege vom selben Tag, gegen die echten Dienste der LGB:

- [`../kachelgrenzen/pruefausgabe-2026-11-05.txt`](../kachelgrenzen/pruefausgabe-2026-11-05.txt): 9 Kacheln, 882
  Gebäude, 940 geliefert, 53 in mehreren Kacheln, 3 davon in drei oder vier.
- [`../wfs-1.1.0/pruefausgabe-2026-11-05.txt`](../wfs-1.1.0/pruefausgabe-2026-11-05.txt): je 18 Kreise über WFS 2.0.0
  und 1.1.0, gleiche IDs, 18 von 18 mit gleichen Sachdaten, 18 von 18 mit identischen Koordinaten.

## Stand

- **Belegläufe** (Brandenburg, Deutschland): am Arbeitsstand vor dem Stagen. Dessen Teilbäume stehen in
  `*/ablauf.txt`: `pipeline` `823bc1ae…`, `config` `1987b737…`, `sql` `afedd6fb…`, `tests` `8ff11e8c…`.
- **Danach geändert:** nur `pipeline/betrieb.py` (die Zusammenfassung `--kennzahlen` zählt unvollständige Abrufe
  eigens, E41) und der Test dazu in `tests/test_betrieb.py`. Die Läufe rufen `--kennzahlen` nicht auf.
- **Datenbanktests und `pruefen.sh`:** am damals gestagten Stand nach E40/E41, nach dieser Änderung wiederholt.
  Dessen Teilbäume (aus dem Index, `git write-tree`): `pipeline` `7539beb31428ebae46842c0b383151e0a36ac211`, `config`
  `1987b73793d04804acc7b6f4a0e2b89fbe043889` (wie in den Läufen), `sql` `afedd6fb63416087121312df9793f615d1151850`
  (wie in den Läufen), `tests` `8efaf31a47e75942c9ff55a5f227980cdc4e0802`.
- **Nicht der Abgabestand:** Mit E42 sind `pipeline/`, `sql/` und `tests/` danach noch einmal geändert worden. Dieser
  Stand ist nie als eigener Commit veröffentlicht; der zu veröffentlichende Commit (Tag `angebot-va-2026-536`, E43)
  wird die Teilbäume aus [`../pruefstand-2026-11-05-e47/`](../pruefstand-2026-11-05-e47/) (nach E44 bis E47; dort liegen auch
  die Belegläufe gegen die echten Dienste an diesem Stand) enthalten.
