# Prüfstand 05.11.2026, Stand nach E45 (Tests und Läufe gegen die echten Dienste)

> **Abgelöst durch [`../pruefstand-2026-11-05-e46/`](../pruefstand-2026-11-05-e46/)** (Stand nach E46) **und zuletzt
> durch [`../pruefstand-2026-11-05-e47/`](../pruefstand-2026-11-05-e47/)** (Stand nach E47, letzte Läufe,
> `docs/entscheidungen.md` E47; Abgabestand ist der Stand nach E48): Tests, Belegläufe Brandenburg und Deutschland und der Lauf im Compose von MOSIDI sind
> dort am Stand nach E47 wiederholt, mit denselben Zählungen. Dieser Ordner bleibt als Beleg des Stands nach E45;
> seine Laufzeiten und Speicherwerte gelten nur für diesen Stand. „Abgabestand“ meint in diesem Ordner den Stand nach
> E45.

Das ist der Prüfstand des Abgabestands, des zu taggenden Stands `angebot-va-2026-536` (E43): die Tests
(`pruefen.sh`, Datenbanktests auf PostgreSQL 16 und 18) und die Belegläufe Brandenburg und Deutschland gegen die
echten Dienste, alle am selben Stand nach E45 (Teilbäume unten). Der Stand enthält die Änderungen aus dem Code-Review
nach E43 (E44) und aus der zweiten Prüfrunde dazu (E45): Fehlerpfade (Rhythmus, Abriss und Ausfall der Datenbank,
Archiv und Meldungsentwurf je Quelle), Rechte auf andere Schemas und die Anzeige unvollständiger Quellen und
technischer Abbrüche. Einzelheiten stehen in [`docs/entscheidungen.md`](../../docs/entscheidungen.md), E44 und E45.
Dieser Prüfstand löst [`../pruefstand-2026-11-05-e42/`](../pruefstand-2026-11-05-e42/) ab; alle Zählungen der Läufe
sind dieselben wie dort.

**Rahmen.** Alle Läufe liefen auf einem Entwicklungsrechner (Linux, Docker, 16 Kerne), der währenddessen für andere
Arbeit genutzt wurde. Es gibt zwei Reihen mit demselben Ablauf am selben Stand: Während Reihe A (14:02 bis 14:21 MEZ)
lief parallel eine andere rechenintensive Arbeit, die 1-Minuten-Last lag zwischen 2,8 und 43,7. Reihe B (15:55 bis
16:12 MEZ) ist dieselbe Wiederholung bei geringerer Last, 1-Minuten-Last zwischen 3,0 und 13,7. Beide liegen bei,
keine ist ausgewählt oder verworfen. Die Rechnerlast steht vor und nach jedem Lauf in `*/ablauf.txt`. **Die Laufzeiten
sind deshalb Größenordnungen, keine Messung auf einem ruhigen Rechner;** sie hängen sichtbar von der Last ab (INKAR
Deutschland am selben Code zwischen 210,6 und 363,9 s), und auch Reihe B ist nicht durchweg schneller (Folgelauf
Deutschland 369,0 s gegen 259,9 s in Reihe A). Für Angaben im Angebot gilt die Spanne über beide Reihen.

Die Datenbank war jeweils frisch, in einem Wegwerf-Compose-Projekt aus der `docker-compose.yml` dieses Repositorys
(PostgreSQL 16.15, PostGIS 3.6.4, Schema der MOSIDI-Tabellen aus `sql/mosidi/`). Die Zugangsdaten wurden je Lauf
zufällig erzeugt und danach gelöscht, Container und Volumes sind entfernt. Die Pipeline lief als Container aus dem
Image dieses Stands, je Reihe und Konfiguration neu gebaut, mit `mem_limit: 1g` wie in der Compose-Datei. Ablauf:
[`beleg.sh`](beleg.sh), aufgerufen je Reihe als `beleg.sh quellen <Ordner> --alle -- --alle -- .` und
`beleg.sh deutschland <Ordner> --alle -- --alle`.

## Belegläufe gegen die echten Dienste

Laufzeiten auf eine Nachkommastelle gerundet (kaufmännisch; die Rohwerte stehen in den Berichten, etwa 118,95 s
→ 119,0 s und 49,25 s → 49,3 s).

| | Brandenburg (`config/quellen.yaml`) | Deutschland (`config/deutschland.yaml`) |
|---|---|---|
| Läufe Reihe A | [`reihe-a/brandenburg/`](reihe-a/brandenburg/): `20261105T130311Z` `--alle`, `20261105T130547Z` `--alle`, `20261105T130910Z` ohne `--alle` | [`reihe-a/deutschland/`](reihe-a/deutschland/): `20261105T130948Z` `--alle`, `20261105T131705Z` `--alle` |
| Läufe Reihe B | [`reihe-b/brandenburg/`](reihe-b/brandenburg/): `20261105T145549Z` `--alle`, `20261105T145752Z` `--alle`, `20261105T145953Z` ohne `--alle` | [`reihe-b/deutschland/`](reihe-b/deutschland/): `20261105T150011Z` `--alle`, `20261105T150620Z` `--alle` |
| Laufzeit laut Bericht, Reihe A | 152,8 s; 198,1 s; 0,08 s (alle sechs Quellen „nicht fällig“) | 432,7 s; 259,9 s |
| Laufzeit laut Bericht, Reihe B | 119,0 s; 118,6 s; 0,03 s (alle sechs Quellen „nicht fällig“) | 364,6 s; 369,0 s |
| **Spanne über beide Reihen** | **Erstlauf 119,0 bis 152,8 s, Folgelauf 118,6 bis 198,1 s**, dritter Lauf 0,03 bis 0,08 s | **Erstlauf 364,6 bis 432,7 s, Folgelauf 259,9 bis 369,0 s** |
| Wandzeit mit Containerstart, Reihe A | 155,5 s; 201,8 s; 3,9 s | 436,7 s; 264,0 s |
| Wandzeit mit Containerstart, Reihe B | 120,9 s; 121,4 s; 1,8 s | 367,0 s; 372,1 s |
| davon INKAR laut Laufprotokoll, Reihe A | 126,1 s; 183,2 s | 363,9 s; 210,6 s (VG250: 68,8 s; 49,3 s) |
| davon INKAR laut Laufprotokoll, Reihe B | 101,3 s; 99,0 s | 298,1 s; 310,2 s (VG250: 66,5 s; 58,7 s) |
| Rechnerlast 1/5/15 min vor dem Lauf, Reihe A | 7,52/5,05/4,32; 12,67/8,97/5,99; 38,53/19,45/10,38 | 43,68/22,97/11,90; 7,61/21,54/16,91 |
| Rechnerlast 1/5/15 min nach dem Lauf, Reihe A | 12,67/8,97/5,99; 38,53/19,45/10,38; 38,53/19,45/10,38 | 7,61/21,54/16,91; 2,81/10,59/13,44 |
| Rechnerlast 1/5/15 min vor dem Lauf, Reihe B | 4,16/2,42/1,72; 2,96/2,44/1,81; 6,78/4,10/2,50 | 7,41/4,39/2,63; 9,89/8,85/5,25 |
| Rechnerlast 1/5/15 min nach dem Lauf, Reihe B | 2,96/2,44/1,81; 6,78/4,10/2,50; 6,56/4,10/2,51 | 9,89/8,85/5,25; 13,72/14,23/9,05 |
| Geometrien | 882 Gebäude, 413 Gemeinden, 18 Kreise | 11 103 Gemeindeflächen (VG250-WFS des BKG) |
| INKAR nach `dashboard_data_de` | 62 929 Zeilen neu, im zweiten Lauf 62 929 unverändert; Zeitbezug 1995 bis 2023 | 1 640 420 Zeilen neu, im zweiten Lauf 1 640 420 unverändert; Zeitbezug 1995 bis 2023 |
| INKAR-Indikatornamen (Regel aus E40) | 9: Bevölkerung, Bevölkerungsentwicklung, Einwohnerdichte, Pendlersaldo (ZOM, ohne Zusatz) und Arbeitslose, Bevölkerung gesamt, Bevölkerungsentwicklung (5 Jahre), Einwohnerdichte, Pendlersaldo mit „(LRB)“, also 5 der 9 Namen mit Bereich (51 477 der 62 929 Zeilen) | dieselben 9 (1 345 471 der 1 640 420 Zeilen mit Bereich) |
| Zeilen verworfen oder zusammengeführt wegen gleichen Zielschlüssels | 0 (keine Quelle angehalten; INKAR gelesen = neu = 62 929) | 0 (gelesen = neu = 1 640 420) |
| Doppelte Zielschlüssel in `dashboard_data_de` | 0 | 0 |
| Register `pipeline_meta.bestand`, INKAR | 62 929 Zeilen, 62 929 mit Quellschlüssel, alle verschieden | 1 640 420 Zeilen, 1 640 420 mit Quellschlüssel, alle verschieden |
| Amt für Statistik | 1 239 Bevölkerungs- und 413 Flächenwerte (zusammen 1 652 Zeilen, 4 Indikatoren, Stichtag 2025), `data_type = indikator` | – |
| `table_metadata` | 16 Zeilen (9 INKAR, 4 Amt für Statistik, 3 LGB) | 10 Zeilen (9 INKAR, 1 BKG) |
| Gebietsschlüssel mit Fläche | 413 von 413 | 10 946 von 10 978; die 32 übrigen sind Gemeinden im INKAR-Gebietsstand 2023, die VG250 nicht mehr führt (der Bericht nennt die ersten zehn) |
| Flächenprüfung | 413 Gemeinden, Median 0,005 %, höchstens 0,161 % (gerundet 0,16 %), Toleranz 0,5 % | – |
| höchste Probe von `docker stats`, Reihe A | 120,9 MiB (74 Proben); 123,4 MiB (94 Proben); dritter Lauf 24,0 MiB (1 Probe) | 94,2 MiB (207 Proben); 94,0 MiB (128 Proben) |
| höchste Probe von `docker stats`, Reihe B | 119,7 MiB (59 Proben); 123,9 MiB (59 Proben); dritter Lauf ohne Probe | 94,4 MiB (177 Proben); 97,6 MiB (178 Proben) |
| `memory.peak` der cgroup (Bytes → MiB), Reihe A | 592 666 624 → 565,2 MiB; 175 403 008 → 167,3 MiB; dritter Lauf 67 465 216 → 64,3 MiB | 197 566 464 → 188,4 MiB; 472 809 472 → 450,9 MiB |
| `memory.peak` der cgroup (Bytes → MiB), Reihe B | 564 346 880 → 538,2 MiB; 463 982 592 → 442,5 MiB; dritter Lauf 58 552 320 → 55,8 MiB | 515 538 944 → 491,7 MiB; 199 086 080 → 189,9 MiB |
| Datenbank danach | 74 MB | 1 132 MB (`pipeline_meta.bestand` 564 MB, `pipeline_meta.aenderung` 307 MB, `dashboard_data_de` 209 MB, `"Kommunale Gebiete Deutschland"` 35 MB) |

Alle zehn Läufe endeten mit Rückgabe 0, ohne fehlgeschlagene, angehaltene oder unvollständige Quelle. Alle Zahlen sind
aus den Rohdateien in diesem Ordner nachgerechnet: Laufzeiten aus den Berichten (`*.txt`, `*.json`) und `ablauf.txt`,
Zählungen aus `datenbank-auszug.txt` und den Zählern in den Berichten, Speicher aus `speicher-lauf<n>.txt` und der
Zeile `cgroup memory.peak` in `konsole-lauf<n>.txt`. Die Datenbankauszüge beider Reihen sind bis auf das
Laufprotokoll (Laufkennungen und Dauer je Quelle) gleich, und gleich denen im Prüfstand nach E42.

**Warnungen und Hinweise** (in jedem der vier vollen Brandenburg-Läufe gleich, in den Deutschland-Läufen keine
Warnung):

- `bevoelkerung_gemeinden`: 21 Zeilen ohne jeden Wert ausgelassen, `flaeche_gemeinden`: 7. Das sind 7 aufgelöste
  Gemeinden, die die Regionaldatenbank weiter mit „-“ führt (je 3 Bevölkerungswerte und 1 Fläche). Ihr bisheriger
  Stand bleibt (E41, E42); im Laufprotokoll stehen sie bei „gelesen“ (420), nicht bei „neu“.
- `alkis_gebaeude_thb`: 882 Objekte mit `aktualit` länger als 10 Zeichen (11), gekürzt gespeichert. Das ist ein
  Befund am Schema: Die Spalte ist in MOSIDI `varchar(10)`, der Dienst liefert 11 Zeichen. Geklärt wird er in
  Arbeitspaket 1 mit dem DDL der TH.
- Hinweise: Die WFS der LGB melden `ImplementsResultPaging=FALSE`, Abruf per Kachelung; der VG250-WFS meldet
  `ImplementsSorting=FALSE`; die INKAR-Datei war unverändert seit dem letzten Abruf.

**Speicher, Messverfahren.** Gemessen wurde auf zwei Wegen, wie im Prüfstand nach E42:

- `docker stats --no-stream` auf den Pipeline-Container in einer Schleife mit 1 s Pause. Weil der Aufruf selbst rund
  1 s braucht, liegen die Proben etwa 2 s auseinander (Median des Abstands je Lauf 2,03 bis 2,15 s). `docker stats`
  zeigt den Speicher der cgroup ohne inaktiven Seitencache. Der dritte Brandenburg-Lauf ist kürzer als ein
  Probenabstand: In Reihe A fiel eine Probe hinein (24,0 MiB, liegt bei), in Reihe B keine; diese Probendatei enthielt
  nur die Kopfzeile und liegt nicht bei.
- Am Ende jedes Laufs liest der Container `/sys/fs/cgroup/memory.peak` aus. Das ist der Höchststand des Kernels,
  einschließlich Seitencache und kurzer Spitzen zwischen den Proben. Für die Grenze von 1 GB zählt dieser Wert;
  der höchste hier ist 565,2 MiB (Brandenburg, Erstlauf Reihe A), in Deutschland 491,7 MiB.

Die Differenz zwischen `memory.peak` und höchster Probe ist nicht aufgeschlüsselt. Dazu gibt jeder Lauf
`memory.stat` aus, allerdings erst nach dem Ende des Python-Prozesses; `anon` (rund 0,4 MiB) sagt deshalb nichts
über den Höchststand. Beobachtet ist nur der Seitencache (`file`) am Ende: Brandenburg 397,2, 36,7 und 31,5 MiB
(Reihe A) und 353,0, 285,5 und 21,6 MiB (Reihe B), Deutschland 76,0 und 373,7 MiB (Reihe A) und 18,8 und 18,9 MiB
(Reihe B). `memory.peak` schwankt am selben Code und bei gleicher höchster Probe zwischen den Läufen stark
(Brandenburg Folgelauf 167,3 und 442,5 MiB, Deutschland Erstlauf 188,4 und 491,7 MiB); im Prüfstand nach E42 lag er
für Brandenburg bei 356,4 und 175,7 MiB. Eine Ursache ist nicht belegt; gemessen ist nur, dass der Seitencache einen
großen Teil davon ausmachen kann.

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
- Die neuen Fehlerpfade aus E44 und E45 (Abriss und Ausfall der Datenbank, nicht schreibbares Archiv): In diesen
  Läufen trat keiner auf; sie prüfen die Tests unten.

**Abweichungen der Dateien hier von den Ausgaben von `beleg.sh`:** `lauf<n>.out` heißt hier `konsole-lauf<n>.txt`,
`lauf<n>.err` (stderr des Aufrufs, hier nur die Meldungen von Compose) heißt `konsole-lauf<n>.err.txt`. Berichte und
Quellenverzeichnis liegen direkt im Ordner statt unter `berichte/`. Nicht beigelegt sind `build.log`,
`einrichten.log` und in Reihe B `speicher-lauf3.txt` (nur Kopfzeile). Alle beigelegten Dateien (65) sind byte-gleich
mit den Rohausgaben (byteweise verglichen am 05.11.2026).

**Die Kartenseiten liegen nicht bei.** Sie enthalten die importierten Datensätze; Quelldaten werden nicht mit dem Code
veröffentlicht (Antwort 69). Das gilt auch für die Seiten der Deutschland-Läufe, die wegen `karte: false` je Quelle
ohne Objekte geschrieben werden (173 KB). Der Datenbankauszug nennt Zählungen und Beispiele des Registers nur als
Schlüssel, ohne Werte.

## Prüfkette

| Datei | Was | Ergebnis |
|---|---|---|
| [`pruefen.log`](pruefen.log) | `./pruefen.sh`: ruff, bandit, pip-audit, pytest, Secret-Scan, Stückliste; Zeitpunkt und Teilbäume in der Kopfzeile | ohne Befund, 154 Tests bestanden (38 Datenbanktests hier übersprungen, sie laufen getrennt); bandit gibt nur eine Warnung aus, dass ein `nosec` in `pipeline/quellen.py` keinen Treffer mehr unterdrückt |
| [`datenbanktests.log`](datenbanktests.log) | `tests/test_datenbank.py` gegen eine echte PostGIS-Datenbank mit den MOSIDI-Tabellen: `postgis/postgis:16-3.6` (festgeschrieben) und `postgis/postgis:latest`; Teilbäume in der Kopfzeile | PostgreSQL 16.15: 38 von 38, PostgreSQL 18.6: 38 von 38 |

Die Projektnamen `gip-e42-pg16-…` und `gip-e42-pg18-…` in `datenbanktests.log` sind nur ein Präfix aus dem Aufruf
und sagen nichts über den geprüften Stand; maßgeblich sind die Teilbäume in der Kopfzeile.

## Stand

- **Teilbäume** (`git write-tree` nach dem Stagen): `pipeline` `6f27d7567c258cc8313db525e99837ce408660af`, `tests`
  `041bd6cd5bc49d4b2797bfec498281fcedb19b44`, `config` `1987b73793d04804acc7b6f4a0e2b89fbe043889`, `sql`
  `15e2b3f2414d0c053c72af5479dd5c159dc4967d`, `Dockerfile` `2953066ba034c0772b8647fcb89c9a710cb5028a`. Dieselben
  stehen in den Kopfzeilen von `pruefen.log` und `datenbanktests.log` und, von `beleg.sh` über eine Kopie des Index
  aus dem Arbeitsstand berechnet, aus dem das Image gebaut wurde, in allen vier `*/ablauf.txt`. `config`, `sql` und
  `Dockerfile` sind dieselben wie im Prüfstand nach E42, `pipeline` und `tests` nicht.
- **Nachprüfbar** nach dem Taggen mit `git rev-parse angebot-va-2026-536:pipeline` usw. Unmittelbar vor dem Taggen
  sind die Teilbäume mit `git write-tree` neu zu berechnen; weichen sie ab, gelten diese Belege nicht für den Tag
  (E45, P14).
- **Reihenfolge am 05.11.2026:** `pruefen.sh` und Datenbanktests 13:53 bis 13:56 MEZ, Reihe A 14:02 bis 14:21 MEZ,
  Reihe B 15:55 bis 16:12 MEZ. Danach kamen nur Dokumentation und diese Belege dazu.
- **Datenbanktests:** je Version ein frisches Wegwerf-Compose-Projekt aus der `docker-compose.yml` dieses Repositorys
  mit zufälligen Passwörtern, beide gleichzeitig gestartet; Container und Volumes sind danach entfernt.
