# Prüfstand 05.11.2026, Stand nach E42 (Belegläufe gegen die echten Dienste)

> **Abgelöst durch [`../pruefstand-2026-11-05-e45/`](../pruefstand-2026-11-05-e45/)** (Stand nach E45: Tests
> und Belegläufe gegen die echten Dienste, zwei Reihen am selben Tag), dieser seit 05.11. abgelöst durch
> [`../pruefstand-2026-11-05-e46/`](../pruefstand-2026-11-05-e46/) (Stand nach E46) und zuletzt durch
> [`../pruefstand-2026-11-05-e47/`](../pruefstand-2026-11-05-e47/) (Stand nach E47, Tests und letzte Läufe; Abgabestand ist der Stand nach E48). Die Läufe hier sind am Stand nach E42; die
> Zählungen der Läufe am Stand nach E45 sind identisch (Datenbankauszüge bis auf das Laufprotokoll gleich), Laufzeiten
> und Speicherwerte gelten nur für diesen Stand und diese Rechnerlast. Der Text unten ist der Stand vor diesem
> Vermerk: „die jüngsten, die es gibt“ und „nicht wiederholt“ gelten nicht mehr. Dieser Ordner bleibt als Beleg des
> Stands nach E42.

Das sind die Belegläufe gegen die echten Dienste am Stand nach E42, die jüngsten, die es gibt. Der Abgabestand (zu
taggen als `angebot-va-2026-536`, E43) ist das nicht mehr: Mit dem Code-Review (E44) und der zweiten Prüfrunde dazu
(E45) haben sich `pipeline/` und `tests/` noch einmal geändert. Die Läufe hier sind dafür nicht wiederholt
(Begründung in E45, P7); die Tests am Abgabestand nach E45 belegt
[`../pruefstand-2026-11-05-e45/`](../pruefstand-2026-11-05-e45/). Dieser Prüfstand löst
[`../pruefstand-2026-11-05-e40/`](../pruefstand-2026-11-05-e40/) ab. E42 ist die zweite Prüfrunde zu E40 und E41.
Sie bringt die Zählung nach dem Quellschlüssel, die Prüfung auf Eindeutigkeit vor den Filtern für leere Werte und
Pflichtfelder, den Schutz ausgelassener Zeilen beim Stichtagwechsel, Warnungen zu verwaisten Metadatenzeilen und
atomar geschriebene Berichte. Einzelheiten stehen in [`docs/entscheidungen.md`](../../docs/entscheidungen.md).

**Rahmen.** Alle Läufe liefen auf einem Entwicklungsrechner (Linux, Docker, 16 Kerne), der währenddessen für andere
Arbeit genutzt wurde. Die Rechnerlast steht vor und nach jedem Lauf in `*/ablauf.txt`; die 1-Minuten-Last lag
zwischen 2,5 und 13,2. **Die Laufzeiten sind deshalb Größenordnungen, keine Messung auf einem ruhigen Rechner.**
Die Datenbank war jeweils frisch, in einem Wegwerf-Compose-Projekt aus der `docker-compose.yml` dieses Repositorys
(PostgreSQL 16.15, PostGIS 3.6.4, Schema der MOSIDI-Tabellen aus `sql/mosidi/`). Die Zugangsdaten wurden je
Lauf zufällig erzeugt und danach gelöscht, Container und Volumes sind entfernt. Die Pipeline lief als Container aus
dem Image dieses Stands, mit `mem_limit: 1g` wie in der Compose-Datei. Ablauf: [`beleg.sh`](beleg.sh).

## Belegläufe gegen die echten Dienste

| | Brandenburg (`config/quellen.yaml`) | Deutschland (`config/deutschland.yaml`) |
|---|---|---|
| Läufe | `20261105T105608Z` `--alle`, `20261105T105800Z` `--alle`, `20261105T105955Z` ohne `--alle` | `20261105T110018Z` `--alle`, `20261105T110539Z` `--alle` |
| Laufzeit laut Bericht | 109,1 s; 112,5 s; 0,02 s (alle sechs Quellen „nicht fällig“) | 318,8 s; 288,9 s |
| Wandzeit mit Containerstart | 111,0 s; 114,9 s; 1,8 s | 320,6 s; 290,9 s |
| davon INKAR laut Laufprotokoll | 93,6 s; 95,0 s | 257,1 s; 234,6 s (VG250: 61,7 s; 54,3 s) |
| Rechnerlast 1/5/15 min vor dem Lauf | 13,21/12,91/13,93; 4,54/9,79/12,68; 2,61/7,37/11,46 | 3,95/7,31/11,33; 4,95/6,60/9,97 |
| Rechnerlast 1/5/15 min nach dem Lauf | 4,54/9,79/12,68; 2,61/7,37/11,46; 2,48/7,27/11,40 | 4,95/6,60/9,97; 5,90/6,83/9,18 |
| Geometrien | 882 Gebäude, 413 Gemeinden, 18 Kreise | 11 103 Gemeindeflächen (VG250-WFS des BKG) |
| INKAR nach `dashboard_data_de` | 62 929 Zeilen neu, im zweiten Lauf 62 929 unverändert; Zeitbezug 1995 bis 2023 | 1 640 420 Zeilen neu, im zweiten Lauf 1 640 420 unverändert; Zeitbezug 1995 bis 2023 |
| INKAR-Indikatornamen (Regel aus E40) | 9: Bevölkerung, Bevölkerungsentwicklung, Einwohnerdichte, Pendlersaldo (ZOM, ohne Zusatz) und Arbeitslose, Bevölkerung gesamt, Bevölkerungsentwicklung (5 Jahre), Einwohnerdichte, Pendlersaldo mit „(LRB)“, also 5 der 9 Namen mit Bereich (51 477 der 62 929 Zeilen) | dieselben 9 |
| Zeilen verworfen oder zusammengeführt wegen gleichen Zielschlüssels | 0 | 0 |
| Doppelte Zielschlüssel in `dashboard_data_de` | 0 | 0 |
| Register `pipeline_meta.bestand`, INKAR | 62 929 Zeilen, 62 929 mit Quellschlüssel, alle verschieden | 1 640 420 Zeilen, 1 640 420 mit Quellschlüssel, alle verschieden |
| Amt für Statistik | 1 239 Bevölkerungs- und 413 Flächenwerte (zusammen 1 652 Zeilen, 4 Indikatoren, Stichtag 2025), `data_type = indikator` | – |
| `table_metadata` | 16 Zeilen (9 INKAR, 4 Amt für Statistik, 3 LGB) | 10 Zeilen (9 INKAR, 1 BKG) |
| Gebietsschlüssel mit Fläche | 413 von 413 | 10 946 von 10 978; die 32 übrigen sind Gemeinden im INKAR-Gebietsstand 2023, die VG250 nicht mehr führt (der Bericht nennt die ersten zehn) |
| Flächenprüfung | 413 Gemeinden, Median 0,005 %, höchstens 0,161 % (gerundet 0,16 %), Toleranz 0,5 % | – |
| höchste Probe von `docker stats` | 118,7 MiB (54 Proben); 119,7 MiB (56 Proben) | 94,4 MiB (157 Proben); 96,8 MiB (142 Proben) |
| `memory.peak` der cgroup (Bytes → MiB) | 373 702 656 → 356,4 MiB; 184 250 368 → 175,7 MiB; dritter Lauf 36 380 672 → 34,7 MiB | 514 404 352 → 490,6 MiB; 448 290 816 → 427,5 MiB |
| Datenbank danach | 74 MB | 1 132 MB (`pipeline_meta.bestand` 564 MB, `pipeline_meta.aenderung` 307 MB, `dashboard_data_de` 209 MB, `"Kommunale Gebiete Deutschland"` 35 MB) |

Alle Läufe endeten mit Rückgabe 0. Alle Zahlen sind aus den Rohdateien in diesem Ordner nachgerechnet: Laufzeiten aus
den Berichten (`*.txt`, `*.json`) und `ablauf.txt`, Zählungen aus `datenbank-auszug.txt`, Speicher aus
`speicher-lauf<n>.txt` und der Zeile `cgroup memory.peak` in `konsole-lauf<n>.txt`.

**Warnungen und Hinweise** (in jedem der beiden vollen Brandenburg-Läufe gleich, in den Deutschland-Läufen keine
Warnung):

- `bevoelkerung_gemeinden`: 21 Zeilen ohne jeden Wert ausgelassen, `flaeche_gemeinden`: 7. Das sind 7 aufgelöste
  Gemeinden, die die Regionaldatenbank weiter mit „-“ führt (je 3 Bevölkerungswerte und 1 Fläche). Ihr bisheriger
  Stand bleibt (E41, E42); im Laufprotokoll stehen sie bei „gelesen“ (420), nicht bei „neu“.
- `alkis_gebaeude_thb`: 882 Objekte mit `aktualit` länger als 10 Zeichen (11), gekürzt gespeichert. Das ist ein
  Befund am Schema: Die Spalte ist in MOSIDI `varchar(10)`, der Dienst liefert 11 Zeichen. Geklärt wird er in
  Arbeitspaket 1 mit dem DDL der TH.
- Hinweise: Die WFS der LGB melden `ImplementsResultPaging=FALSE`, Abruf per Kachelung; der VG250-WFS meldet
  `ImplementsSorting=FALSE`; die INKAR-Datei war unverändert seit dem letzten Abruf.

**Speicher, Messverfahren.** Gemessen wurde auf zwei Wegen:

- `docker stats --no-stream` auf den Pipeline-Container in einer Schleife mit 1 s Pause. Weil der Aufruf selbst rund
  1 s braucht, liegen die Proben etwa 2 s auseinander (Median des Abstands 2,03 s). `docker stats` zeigt den Speicher
  der cgroup ohne inaktiven Seitencache. Der dritte Brandenburg-Lauf war kürzer als ein Probenabstand; seine
  Probendatei enthielt nur die Kopfzeile und liegt nicht bei.
- Am Ende jedes Laufs liest der Container `/sys/fs/cgroup/memory.peak` aus. Das ist der Höchststand des Kernels,
  einschließlich Seitencache und kurzer Spitzen zwischen den Proben. Für die Grenze von 1 GB zählt dieser Wert;
  der höchste hier ist 490,6 MiB.

Die Differenz zwischen `memory.peak` und höchster Probe ist nicht aufgeschlüsselt. Dazu gibt jeder Lauf
`memory.stat` aus, allerdings erst nach dem Ende des Python-Prozesses; `anon` (rund 0,4 MiB) sagt deshalb nichts
über den Höchststand. Beobachtet ist nur der Seitencache (`file`) am Ende: nach dem ersten Brandenburg-Lauf 172,0 MiB,
nach dem zweiten 9,8 MiB, nach den Deutschland-Läufen 0,9 und 2,4 MiB. Im Prüfstand nach E40 lag `memory.peak`
für Deutschland bei 97,1 MiB, hier bei 490,6 und 427,5 MiB, bei ähnlicher höchster Probe; eine Ursache ist nicht
belegt.

**Was diese Läufe nicht prüfen:**

- Den Download der INKAR-Datei: In allen Läufen lag sie schon im Zwischenspeicher (`cache/inkar_2025.zip`, 434 MB,
  Stand 13.08.2025). Das BBSR meldete sie als unverändert; der Download ist nicht mitgemessen.
- Den Lauf im Compose von MOSIDI gegen `brandenburg_db`: Er ist vom 03.11., vor der Schlüsselumstellung E40, und ist
  nicht wiederholt ([`../mosidi-compose/`](../mosidi-compose/)). Die aktuellen Zahlen stammen aus der Testdatenbank
  dieses Repositorys mit demselben Schema.
- Alle 264 INKAR-Kürzel: Beide Konfigurationen laden fünf. Für alle Kürzel gibt es die Gesamtanalyse der Schlüssel
  in [`../inkar-schluessel/`](../inkar-schluessel/), ohne Datenbanklauf.
- Ein Änderungslauf mit echten Änderungen: Die Folgeläufe hier sind „alles unverändert“. Neu, geändert, gelöscht,
  Kürzelwechsel und Stichtagwechsel prüfen die Datenbanktests.

**Abweichungen der Dateien hier von den Ausgaben von `beleg.sh`:** `lauf<n>.out` heißt hier `konsole-lauf<n>.txt`,
`lauf<n>.err` (stderr des Aufrufs, hier nur die Meldungen von Compose) heißt `konsole-lauf<n>.err.txt`. Berichte und
Quellenverzeichnis liegen direkt im Ordner statt unter `berichte/`. Nicht beigelegt sind `build.log`,
`einrichten.log` und `speicher-lauf3.txt` (nur Kopfzeile). Alle beigelegten Dateien sind byte-gleich mit den
Rohausgaben (byteweise verglichen am 05.11.2026).

**Die Kartenseiten liegen nicht bei.** Sie enthalten die importierten Datensätze; Quelldaten werden nicht mit dem Code
veröffentlicht (Antwort 69). Das gilt auch für die Seiten der Deutschland-Läufe, die wegen `karte: false` je Quelle
ohne Objekte geschrieben werden (173 KB). Der Datenbankauszug nennt Zählungen und Beispiele des Registers nur als
Schlüssel, ohne Werte.

## Prüfkette

| Datei | Was | Ergebnis |
|---|---|---|
| `pruefen.log`, `pruefen-abgabestand.log` | `./pruefen.sh`: ruff, bandit, pip-audit, pytest, Secret-Scan, Stückliste (das zweite am gestagten Stand nach E42, siehe „Stand“) | je ohne Befund, 133 Tests bestanden (35 Datenbanktests hier übersprungen, sie laufen getrennt); bandit gibt nur eine Warnung aus, dass ein `nosec` in `pipeline/quellen.py` keinen Treffer mehr unterdrückt |
| `datenbanktests.log` | `tests/test_datenbank.py` gegen eine echte PostGIS-Datenbank mit den MOSIDI-Tabellen: `postgis/postgis:16-3.6` (festgeschrieben) und `postgis/postgis:latest` | PostgreSQL 16.15: 35 von 35, PostgreSQL 18.6: 35 von 35 |

Weitere Belege vom selben Tag, gegen die echten Dienste der LGB:

- [`../kachelgrenzen/pruefausgabe-2026-11-05.txt`](../kachelgrenzen/pruefausgabe-2026-11-05.txt): 9 Kacheln, 940
  geliefert, 882 Gebäude, 53 in mehreren Kacheln.
- [`../wfs-1.1.0/pruefausgabe-2026-11-05.txt`](../wfs-1.1.0/pruefausgabe-2026-11-05.txt): je 18 Kreise über WFS 2.0.0
  und 1.1.0, gleiche IDs, 18 von 18 mit gleichen Sachdaten, 18 von 18 mit identischen Koordinaten.

## Stand

- **Belegläufe:** `beleg.sh` schreibt die Teilbäume des Arbeitsstands, aus dem das Image gebaut wird, in
  `*/ablauf.txt` (über eine Kopie des Index, der Index selbst bleibt unberührt): `pipeline`
  `e32fdbf5fae98cf5ee24c8503b2792a7b5439799`, `config` `1987b73793d04804acc7b6f4a0e2b89fbe043889`, `sql`
  `15e2b3f2414d0c053c72af5479dd5c159dc4967d`, `tests` `8e341f8b42852dc13dabc260e079efec76a2e4e0`, `Dockerfile`
  `2953066ba034c0772b8647fcb89c9a710cb5028a`.
- **Gegen den damaligen Abgabestand geprüft:** Nach dem Stagen des Stands nach E42 ergab `git write-tree` für alle
  fünf dieselben Hashes (05.11.2026). Seit E44 und E45 (`docs/entscheidungen.md`) weichen `pipeline` und `tests` des
  zu taggenden Abgabestands davon ab; `config`, `sql` und `Dockerfile` sind gleich. Die Belegläufe hier sind nicht
  wiederholt; die Teilbäume des Stands nach E47 stehen in [`../pruefstand-2026-11-05-e47/`](../pruefstand-2026-11-05-e47/),
  die des Abgabestands nach E48 in `docs/entscheidungen.md` (E48) und in [`../pruefstand-2026-11-06-e48/`](../pruefstand-2026-11-06-e48/).
- **Datenbanktests:** am selben Arbeitsstand. Ein Baum ist für sie nicht mitgeschrieben; die letzte Änderung an
  `pipeline/`, `sql/` und `tests/` war um 11:31 MEZ, die Datenbanktests endeten um 11:55 und 12:13 MEZ.
- **`pruefen.log`:** Zeitpunkt und Baum dieses Laufs sind nicht mitgeschrieben; die Zahlen (133 bestanden, 35
  Datenbanktests übersprungen) entsprechen dem Testbestand nach E42. Belegt am gestagten Stand nach E42 ist
  [`pruefen-abgabestand.log`](pruefen-abgabestand.log): `./pruefen.sh` nach dem Stagen dieses Stands, mit den
  Teilbäumen in der Kopfzeile, ohne Befund, 133 Tests bestanden.
- Danach kamen bis E43 nur Dokumentation und diese Belege dazu; mit E44 und E45 Änderungen an `pipeline/` und
  `tests/`. Deren Tests (154 ohne Datenbank, je 38 von 38 mit Datenbank) sind mit Protokoll und Teilbäumen in
  [`../pruefstand-2026-11-05-e45/`](../pruefstand-2026-11-05-e45/) belegt.
