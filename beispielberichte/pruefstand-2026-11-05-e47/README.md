# Prüfstand 05./06.11.2026, Stand nach E47 (Tests, Läufe gegen die echten Dienste, Lauf im Compose von MOSIDI)

> **Abgelöst durch [`../pruefstand-2026-11-06-e49/`](../pruefstand-2026-11-06-e49/) und weiter durch [`../pruefstand-2026-11-06-e50/`](../pruefstand-2026-11-06-e50/) (Stand nach E50) und [`../pruefstand-2026-11-07-e51/`](../pruefstand-2026-11-07-e51/) (Abgabestand nach E51)** (06./07.11.2026): Tests, Läufe gegen die
> echten Dienste und der Lauf im Compose von MOSIDI sind am Stand nach E49, am Stand nach E50 und am Abgabestand nach E51 wiederholt, alle mit Rückgabe 0.
> Dieser Prüfstand bleibt als Beleg des Stands nach E47; seine Zahlen zur Statistik stammen aus der
> Regionaldatenbank, seine Teilbäume gelten nur für jenen Stand. „Die Läufe sind nach E48 nicht wiederholt“ im
> folgenden Absatz ist überholt.

Das ist der Prüfstand des Stands nach E47 mit den letzten Läufen gegen die echten Dienste. Abgabestand (Tag
`angebot-va-2026-536`, E43) ist der Stand nach E48; dessen Testprotokolle liegen in
[`../pruefstand-2026-11-06-e48/`](../pruefstand-2026-11-06-e48/), die Läufe sind nach E48 nicht wiederholt.
Der Stand nach E47 entstand nach den Code-Befunden
des unabhängigen Prüfberichts vom 05.11.2026 abends und der Nachprüfung dazu (E47 in
[`docs/entscheidungen.md`](../../docs/entscheidungen.md)): Datenbereich und Gebietsauswahl der Statistiktabellen
getrennt (eine Datenzeile ohne gültigen Schlüssel sperrt das Löschen), Beleg je WFS-Kachel (`CountDefault`,
Folgeseiten, bei WFS 1.1.0 Trefferzahl), keine Kürzung zu langer Texte (ein Datum `JJJJ-MM-TTZ` wird ohne das Z
übernommen, jeder andere zu lange Wert hält seine Zeile zurück), Folge-Links der OGC API ohne Fortschritt beenden den
Abruf als unvollständig, `einrichten` bricht bei einer vorhandenen Rolle mit zu weiten Rechten oder Eigentum ab; aus
der Nachprüfung die Entdopplung zu langer Werte, Schlüssel mit Rand oder Anführungszeichen, die Spaltenzahl gegen die
Kopfzeile, `SORTBY` auch in Kachelabfragen und die Eigentumsprüfung.

Alles in diesem Ordner ist am selben Stand entstanden (Teilbäume unten, in den Kopfzeilen der Protokolle und in jeder
`ablauf.txt`): die Tests, die Belegläufe Brandenburg und Deutschland gegen die echten Dienste und die Wiederholung des
Laufs im Compose-Setup von MOSIDI mit der Katalogaktualisierung gegen die View `source_granularities` in der Fassung
aus dem MOSIDI-Repository. Dieser Prüfstand löst [`../pruefstand-2026-11-05-e46/`](../pruefstand-2026-11-05-e46/)
ab; alle Zählungen der Läufe sind dieselben wie dort. **Neu gegenüber E46:** Alle Brandenburg- und Compose-Läufe
enden mit Rückgabe 1, weil die Datenbereichsprüfung aus E47 bei der Flächentabelle der Regionaldatenbank anschlägt
(unten, „Befund am Dateiaufbau“); statt der Kürzung von `aktualit` steht im Bericht ein Hinweis auf 882 übernommene
Datumswerte.

## Prüfkette

| Prüfung | Ergebnis | Protokoll |
|---|---|---|
| `pruefen.sh` (ruff, bandit, pip-audit, Tests ohne Datenbank, Secret-Scan, Stückliste); Zeitpunkt und Teilbäume in der Kopfzeile | ohne Befund, 190 Tests bestanden (die 59 Datenbanktests dort übersprungen, sie laufen getrennt); bandit gibt nur eine Warnung aus, dass ein `nosec` in `pipeline/quellen.py` keinen Treffer mehr unterdrückt | [`pruefen.log`](pruefen.log) |
| `tests/test_datenbank.py` gegen eine echte PostGIS-Datenbank mit den MOSIDI-Tabellen, `postgis/postgis:16-3.6` (festgeschrieben); Teilbäume in der Kopfzeile | PostgreSQL 16.15: 59 von 59 (im zweiten Anlauf; der erste scheiterte vor dem ersten Test an `docker compose up --wait`, steht so im Protokoll) | [`datenbanktests.log`](datenbanktests.log) |
| dieselben Tests, `postgis/postgis:latest` | PostgreSQL 18.6: 59 von 59 | [`datenbanktests.log`](datenbanktests.log) |

Die Datenbanktests liefen je Version in einem frischen Wegwerf-Compose-Projekt aus der `docker-compose.yml` dieses
Repositorys mit zufälligen Passwörtern (05.11.2026, 23:44 bis 23:50 MEZ); Container und Volumes sind danach entfernt.
Die Projektnamen `gip-e42-pg16-…` und `gip-e42-pg18-…` in `datenbanktests.log` sind nur ein Präfix aus dem Aufruf und
sagen nichts über den geprüften Stand; maßgeblich sind die Teilbäume in der Kopfzeile. `pruefen.log` stammt aus dem
Lauf nach dem Stagen dieses Ordners und der Dokumentation (06.11.2026, Endzeit in der Kopfzeile); ein Lauf am selben
Baum am 05.11. um 23:35 MEZ hatte dasselbe Ergebnis.

## Belegläufe gegen die echten Dienste

**Rahmen.** Alle Läufe liefen auf einem Entwicklungsrechner (Linux, Docker, 16 Kerne), der währenddessen auch für
andere Arbeit genutzt wurde. Vor dem Start war die 1-Minuten-Last 2,33. Während der Läufe Brandenburg und Deutschland
lag sie zwischen 1,63 und 3,67 (Brandenburg 1,63 bis 3,67, Deutschland 1,71 bis 2,65), im Compose-Lauf von MOSIDI
zwischen 1,97 und 4,27. Die Last vor und nach jedem Lauf steht in `*/ablauf.txt`. Es gibt eine Reihe; die Laufzeiten
sind Größenordnungen, keine Messung auf einem ruhigen Rechner. Sie liegen in der Größenordnung des Prüfstands nach
E46 (Brandenburg 112,6 und 112,3 s, Deutschland 272,6 und 260,4 s) und unter den beiden Reihen nach E45 bei höherer
Last; ein Geschwindigkeitsunterschied zwischen den Ständen ist damit nicht belegt.

Die Datenbank war jeweils frisch, in einem Wegwerf-Compose-Projekt aus der `docker-compose.yml` dieses Repositorys
(PostgreSQL 16.15, PostGIS 3.6.4, Schema der MOSIDI-Tabellen aus `sql/mosidi/`). Die Zugangsdaten wurden zufällig
erzeugt und danach gelöscht, Container und Volumes sind entfernt. Die Pipeline lief als Container aus dem Image dieses
Stands (`geodaten-import-pipeline:e47-beleg`, je Konfiguration neu gebaut, beide Male dieselbe Image-ID
`sha256:e42e5b4aef2b…`) mit `mem_limit: 1g` wie in der Compose-Datei. Ablauf: [`beleg.sh`](beleg.sh) (die Fassung aus
dem Prüfstand nach E46, nur Kopf und Imagename angepasst), aufgerufen als `beleg.sh quellen <Ordner> --alle -- --alle
-- .` und `beleg.sh deutschland <Ordner> --alle -- --alle`, nacheinander.

Laufzeiten auf eine Nachkommastelle gerundet (kaufmännisch; die Rohwerte stehen in den Berichten, etwa 115,32 s
→ 115,3 s und 4,83 s → 4,8 s).

| | Brandenburg (`config/quellen.yaml`) | Deutschland (`config/deutschland.yaml`) |
|---|---|---|
| Läufe | [`brandenburg/`](brandenburg/): `20261105T225145Z` `--alle`, `20261105T225344Z` `--alle`, `20261105T225539Z` ohne `--alle` | [`deutschland/`](deutschland/): `20261105T225629Z` `--alle`, `20261105T230136Z` `--alle` |
| Zeit (MEZ) | 05.11., 23:51 bis 23:56 | 05.11., 23:56 bis 06.11., 00:06 |
| Rückgabe | 1; 1; 1 (Flächentabelle unvollständig, unten) | 0; 0 |
| Laufzeit laut Bericht | **Erstlauf 115,3 s, Folgelauf 111,8 s**, dritter Lauf 4,8 s (fünf Quellen „nicht fällig“, die Flächentabelle erneut geholt) | **Erstlauf 303,6 s, Folgelauf 259,6 s** |
| Wandzeit mit Containerstart | 118,5 s; 114,7 s; 6,9 s | 305,3 s; 262,1 s |
| davon INKAR laut Laufprotokoll | 96,9 s; 94,5 s | 255,3 s; 209,9 s (VG250: 48,2 s; 49,7 s) |
| Rechnerlast 1/5/15 min vor dem Lauf | 3,67/2,86/2,48; 2,23/2,59/2,43; 1,65/2,24/2,31 | 2,65/2,43/2,37; 1,71/1,93/2,16 |
| Rechnerlast 1/5/15 min nach dem Lauf | 2,23/2,59/2,43; 1,65/2,24/2,31; 1,63/2,21/2,30 | 1,71/1,93/2,16; 1,86/1,75/2,01 |
| Geometrien | 882 Gebäude, 413 Gemeinden, 18 Kreise | 11 103 Gemeindeflächen (VG250-WFS des BKG) |
| INKAR nach `dashboard_data_de` | 62 929 Zeilen neu, im zweiten Lauf 62 929 unverändert; Zeitbezug 1995 bis 2023 | 1 640 420 Zeilen neu, im zweiten Lauf 1 640 420 unverändert; Zeitbezug 1995 bis 2023 |
| INKAR-Indikatornamen (Regel aus E40) | 9, davon 5 mit Bereich „(LRB)“ (51 477 der 62 929 Zeilen) | dieselben 9 (1 345 471 der 1 640 420 Zeilen mit Bereich) |
| Zeilen verworfen, zurückgehalten oder zusammengeführt | 0 (keine Quelle angehalten; INKAR gelesen = neu = 62 929; `zurueckgehalten` überall 0) | 0 (gelesen = neu = 1 640 420) |
| Doppelte Zielschlüssel in `dashboard_data_de` | 0 | 0 |
| Übernommene Zeilen (E46: fachlich gezählt) | 0 in allen Quellen und Läufen (frische Datenbank) | 0 |
| Register `pipeline_meta.bestand`, INKAR | 62 929 Zeilen, 62 929 mit Quellschlüssel, alle verschieden | 1 640 420 Zeilen, 1 640 420 mit Quellschlüssel, alle verschieden |
| Amt für Statistik | 1 239 Bevölkerungs- und 413 Flächenwerte (zusammen 1 652 Zeilen, 4 Indikatoren, Stichtag 2025), `data_type = indikator` | – |
| `table_metadata` | 16 Zeilen (9 INKAR, 4 Amt für Statistik, 3 LGB) | 10 Zeilen (9 INKAR, 1 BKG) |
| Gebietsschlüssel mit Fläche | 413 von 413 | 10 946 von 10 978; die 32 übrigen haben keine Fläche in der VG250; als Ursache ist der Gebietsstand 2023 von INKAR zu prüfen (der Bericht nennt die ersten zehn) |
| Flächenprüfung | 413 Gemeinden, Median 0,005 %, höchstens 0,161 % (gerundet 0,16 %), Toleranz 0,5 % | – |
| `aktualit` (E47) | Hinweis „882 Werte in aktualit als Datum ohne Zeitzonenkennung Z übernommen“ in beiden vollen Läufen (`info.normalisiert.aktualit = 882`); keine Kürzung mehr, nichts zurückgehalten | – |
| Katalog (E46) | Erstlauf: Hinweis „`public.source_granularities` gibt es in dieser Datenbank nicht“ (das Schema aus `sql/mosidi/` enthält die View nicht), Bericht `katalog.ergebnis = fehlt`; Folgeläufe ohne Änderung ohne Aufruf | ebenso |
| höchste Probe von `docker stats` | 119,0 MiB (57 Proben); 110,9 MiB (55 Proben); dritter Lauf 43,6 MiB (3 Proben) | 93,9 MiB (149 Proben); 94,3 MiB (128 Proben) |
| `memory.peak` der cgroup (Bytes → MiB) | 628 453 376 → 599,3 MiB; 182 661 120 → 174,2 MiB; dritter Lauf 67 440 640 → 64,3 MiB | 102 588 416 → 97,8 MiB; 101 986 304 → 97,3 MiB |
| Datenbank danach | 74 MB | 1 132 MB (`pipeline_meta.bestand` 564 MB, `pipeline_meta.aenderung` 307 MB, `dashboard_data_de` 209 MB, `"Kommunale Gebiete Deutschland"` 35 MB) |

Alle Zahlen sind aus den Rohdateien in diesem Ordner nachgerechnet: Laufzeiten aus den Berichten (`*.txt`, `*.json`)
und `ablauf.txt`, Zählungen aus `datenbank-auszug.txt` und den Zählern in den Berichten, Speicher aus
`speicher-lauf<n>.txt` (höchster Wert der Spalte `MemUsage`) und der Zeile `cgroup memory.peak` in
`konsole-lauf<n>.txt`. Die Datenbankauszüge sind bis auf das Laufprotokoll (Laufkennungen, Status und Dauer je Quelle)
zeilengleich mit denen des Prüfstands nach E46.

**Befund am Dateiaufbau der Regionaldatenbank (Rückgabe 1 in allen Brandenburg- und Compose-Läufen).** Die
Flächentabelle `11111-01-01-5-B` (`flaeche_gemeinden`) hat nach dem konfigurierten Kopfende (`kopf_pruefen: zeile 6`,
Spaltenbeschriftung `;;Gebietsfläche`; `zeitbezug` aus Zeile 5) in Zeile 7 eine Zeile mit der Spaltenzahl der
Datenzeilen (3), deren erstes Feld nicht auf `schluessel_form` `^(DG|\d+)$` passt. Die Datenbereichsprüfung aus E47
wertet sie als beschädigte Datenzeile: Warnung „1 Datenzeilen ohne gültigen Gebietsschlüssel übergangen (Zeilen 7);
Abruf unvollständig, nichts wird gelöscht“, Quelle `UNVOLLSTÄNDIG`, die 413 Flächen werden geladen (im zweiten Lauf
413 unverändert), nichts wird gelöscht, die Quelle bekommt keinen `letzter_erfolg` und wird bei jedem Lauf erneut
abgerufen (deshalb 4,8 s statt 0,03 s im dritten Lauf; `--status` bleibt WARNING). Die Bevölkerungstabelle
`12411-01-01-5-B` (eigene Quelle `bevoelkerung_gemeinden`, Kopfende Zeile 8 = Spaltenbeschriftung) ist nicht
betroffen. **Der Inhalt der Zeile 7 ist nicht gesichtet:** Die Datei liegt nicht in diesem Ordner und nicht im
Zwischenspeicher (Quelldaten werden nicht veröffentlicht, Antwort 69), und `robots.txt` der Regionaldatenbank
(`Disallow: /` für alle) spricht gegen einen Abruf außerhalb des Betriebs der Pipeline. Nach ihrer Form (3 Felder,
erstes Feld kein Schlüssel) ist sie voraussichtlich eine weitere Kopf- oder Einheitenzeile; das ist Vermutung. Die
Behebung (Kopfende in `config/quellen.yaml` eine Zeile tiefer setzen) setzt die Sichtung der Zeile voraus; wäre sie
eine echte Datenzeile mit beschädigtem Schlüssel, würde ein tieferes Kopfende gerade den Schutz aus E47 umgehen.
Die Konfiguration ist deshalb hier nicht geändert; eine Änderung ändert den Teilbaum `config` und verlangt die
Wiederholung von Tests und Läufen. Damit verfehlt dieser Prüfstand das Abnahmekriterium aus E47 („der erste Lauf nach
E47 muss ohne neue Warnung zu Datenzeilen enden“) in diesem einen Punkt; die Warnung ist die erwartete Reaktion auf
eine unerwartete Zeile, und der Bestand ist dabei geschützt.

**Warnungen und Hinweise** sonst wie nach E46 (in beiden vollen Brandenburg-Läufen gleich, in den Deutschland-Läufen
keine Warnung): `bevoelkerung_gemeinden` 21 und `flaeche_gemeinden` 7 Zeilen ohne jeden Wert ausgelassen
(7 Gemeindeschlüssel, die die Regionaldatenbank nur mit „-“ führt, Ursache je Schlüssel zu prüfen; ihr bisheriger
Stand bleibt, im Laufprotokoll unter „gelesen“ 420). Hinweise: WFS der LGB `ImplementsResultPaging=FALSE`
(Kachelung), VG250-WFS `ImplementsSorting=FALSE`, INKAR-Datei unverändert seit dem letzten Abruf, Katalog-View fehlt
in der Testdatenbank. Weggefallen ist die Warnung „882 Objekte mit aktualit länger als 10 Zeichen, gekürzt
gespeichert“ aus dem Prüfstand nach E46; an ihrer Stelle steht der Hinweis zu `aktualit` (Tabelle oben). Neu ist die
Warnung zur Flächentabelle.

**`SORTBY` in Kachelabfragen, nicht gelaufen.** Die beiden Dienste der LGB nennen `ImplementsSorting` nur als
`fes:Constraint` im Abschnitt Filter_Capabilities ihrer Capabilities (dort `TRUE`; `ImplementsResultPaging` `FALSE`
und `CountDefault` 100 000 bzw. 300 000 stehen als `ows:Constraint` in den OperationsMetadata; Abruf der
Capabilities am 06.11.2026, 01:02 MEZ, nicht beigelegt). `capabilities_lesen` liest Constraints nur aus
`ows:Constraint` und wertet die Dienste deshalb als ohne Sortierung; die Kachelabfragen dieser Läufe trugen kein
`SORTBY`, und der Weg aus der Nachprüfung zu E47 ist gegen die echten Dienste nicht gelaufen (er ist mit Tests
belegt). Für die Vollständigkeit der Kacheln spielt das keine Rolle: Die Dienste liefern `numberMatched`, und die
Zählungen sind in allen Läufen dieselben wie nach E45 und E46. Vermerk in E47 („Grenzen“).

**Speicher, Messverfahren** wie nach E46: `docker stats --no-stream` in einer Schleife mit 1 s Pause (Median des
Probenabstands je Lauf 2,03 s; `docker stats` zeigt den Speicher der cgroup ohne inaktiven Seitencache) und am Ende
jedes Laufs `/sys/fs/cgroup/memory.peak` (Höchststand des Kernels einschließlich Seitencache; für die Grenze von 1 GB
zählt dieser Wert). Der höchste ist 599,3 MiB (Brandenburg, Erstlauf; nach E46 583,3 MiB), in Deutschland 97,8 MiB.
Seitencache am Ende (`file` in `memory.stat`, nach dem Ende des Python-Prozesses gelesen): Brandenburg 415,9, 8,6 und
2,0 MiB, Deutschland je 0,2 MiB. Der Ausreißer des Prüfstands nach E46 (365,9 MiB höchste Probe im Deutschland-Folgelauf)
trat nicht wieder auf (hier 94,3 MiB); seine Ursache bleibt nicht belegt. `memory.peak` bleibt in allen Läufen unter
60 % der Grenze.

## Lauf im Compose-Setup von MOSIDI (Wiederholung des Laufs vom 03.11. und vom 05.11. nach E46)

Ordner [`mosidi-compose/`](mosidi-compose/), Ablauf [`mosidi-compose/lauf.sh`](mosidi-compose/lauf.sh) (die Fassung
aus dem Prüfstand nach E46, nur Kopf, Imagename und Projektname angepasst), 06.11.2026, 00:06 bis 00:11 MEZ.
MOSIDI-ORG/MOSIDI wurde öffentlich geklont (`git clone --depth 1`): Commit
`26cadbba3d6223c84872987104fc737359bf8bfc` vom 02.11.2026, derselbe wie am 03. und 05.11. Benutzt sind die unveränderte
`docker-compose.yml` von MOSIDI und das Overlay
[`deploy/mosidi/docker-compose.pipeline.yml`](../../deploy/mosidi/docker-compose.pipeline.yml), so wie
[`deploy/mosidi/README.md`](../../deploy/mosidi/README.md) es beschreibt, mit eigenem Compose-Projektnamen
(`gip-mosidi-e47-<pid>`), zufälligen Passwörtern und danach `down -v` (keine Container, Volumes oder `.env` übrig).

Abweichungen vom unveränderten Compose, alle im Test-Override von `lauf.sh`, wie nach E46:

- `brandenburg_db`: Volume unter `/var/lib/postgresql` statt `/var/lib/postgresql/data` (sonst startet PostgreSQL 18
  nicht, siehe unten), keine Freigabe von Port 5432 nach außen, eigener Containername statt des festen
  `brandenburg_db` (damit nichts Fremdes getroffen wird; der Dienstname bleibt `brandenburg_db`).
- Pipeline-Dienste: Image `geodaten-import-pipeline:e47-beleg` (ID in `mosidi-compose/ablauf.txt`, dasselbe wie in
  den Belegläufen) statt des Tags `:lokal` aus dem Overlay; Berichtsordner im Ausgabeordner statt im Repository (die
  Kartenseiten liegen nicht bei).
- `.env` von MOSIDI: `POSTGRES_DB=brandenburg` (wie in der MOSIDI-README), `POSTGRES_USER=admin`, die Passwörter
  zufällig; `pg_tileserv.env` leer. Compose warnt deshalb, dass `GEOSERVER_ADMIN` und `GEOSERVER_PASSWORD` nicht
  gesetzt sind (in `konsole-lauf<n>.err.txt` und `einrichten.log`; nur die Namen, keine Werte); GeoServer startet
  nicht mit.
- Datenbank: PostgreSQL 18.6, PostGIS 3.6.4 (`postgis/postgis` ohne Tag, wie in MOSIDI), anders als in den
  Belegläufen oben (16.15).
- Testaufbau der Datenbank: Schema der Bestandstabellen aus `sql/mosidi/001_bestand.sql`, danach als Administrator
  die Materialized View `source_granularities` mit ihren beiden Indizes, wörtlich aus MOSIDI
  `services/backend/src/db_table_metadata/script.py`, Zeilen 262 bis 272 (sha256 des Ausschnitts in `ablauf.txt`).
  So legt sie auch das Backend von MOSIDI an. Sie steht nicht in `sql/mosidi/` und ist dort nicht nachgetragen.

Ergebnis:

| | |
|---|---|
| Unverändertes `brandenburg_db` auf frischem Volume | startet nicht: nach 30 s Status `restarting`, 9 Neustarts, Meldung „in 18+, these Docker images are configured to store database data in a format which is compatible with pg_ctlcluster …“ ([`befund-postgresql18.txt`](mosidi-compose/befund-postgresql18.txt), die erste Meldung und der Anfang der Wiederholung), wie am 03. und 05.11. |
| `pipeline-einrichten` | Rückgabe 0; Rollen `pipeline_import` und `mosidi_lesen` ohne Superuser-, CREATEDB- oder CREATEROLE-Recht; Spaltenrechte in [`einrichten.log`](mosidi-compose/einrichten.log); keine Warnung zur Katalogfunktion (Eigentümer von View und Funktion ist `admin`, `SECURITY DEFINER`); die Rollenprüfung aus E47 fand nichts (frische Datenbank, Rollen neu angelegt) |
| Lauf 1 `--alle` (`20261105T230726Z`) | **Rückgabe 1** (Flächentabelle unvollständig, Befund oben), 112,3 s laut Bericht (Wandzeit 114,8 s, 1-Minuten-Last davor 4,27, danach 1,97), INKAR 94,6 s; 882 Gebäude, 413 Gemeinden, 18 Kreise, 1 239 + 413 Werte des Amts für Statistik, 62 929 INKAR-Werte; **„Katalog: public.source_granularities aktualisiert“**, die View hatte vorher 0 Zeilen, danach 13 (9 INKAR, 4 Amt für Statistik, Gemeindeebene); die Katalogaktualisierung lief trotz der unvollständigen Quelle |
| Lauf 2 `--alle` (`20261105T230921Z`) | **Rückgabe 1** (ebenso), 112,3 s laut Bericht (Wandzeit 114,8 s, Last danach 2,11), INKAR 95,2 s; alles unverändert, kein Aufruf des Katalogs, `pipeline_meta.katalog_offen` leer, View weiter 13 Zeilen |
| Datenbank danach | 0 doppelte Zielschlüssel, `table_metadata` 16 Zeilen, in `public` 39 Tabellen, 2 Views, 1 Materialized View, 25 Sequenzen ([`datenbank-auszug.txt`](mosidi-compose/datenbank-auszug.txt)) |
| Bestandsschema `public` (Antworten 27, 29) | `pg_dump --schema-only --schema=public --no-privileges --no-owner` vor `einrichten` und nach Lauf 2 gleich (2 527 Zeilen, sha256 `2a70acee…` in `ablauf.txt`, derselbe Wert wie nach E46; die beiden Dumps liegen nicht bei, sie enthalten das Schema aus `sql/mosidi/` und die View). Die Rechte in `public` ändert `einrichten` wie vorgesehen (Grants an die beiden Rollen, `einrichten.log`); sie sind in diesem Vergleich ausgenommen |

Der Abschnitt „Schreibrechte“ im Datenbankauszug zählt nur Rechte auf ganze Tabellen (SELECT auf 5, DELETE auf
`dashboard_data_de`); INSERT und UPDATE vergibt `einrichten` spaltenweise, sie stehen in `einrichten.log`. Gegenüber
dem Lauf nach E46 ([`../pruefstand-2026-11-05-e46/mosidi-compose/`](../pruefstand-2026-11-05-e46/mosidi-compose/)):
dieselben Zählungen, dazu der Hinweis zu `aktualit` statt der Kürzungswarnung und die Warnung zur Flächentabelle mit
Rückgabe 1.

## Was nicht geprüft ist

- Der Inhalt der Zeile 7 der Flächentabelle (oben): nicht gesichtet, die Behebung über das Kopfende ist deshalb noch
  nicht ausgeführt.
- Der Download der INKAR-Datei: In allen Läufen lag sie im Zwischenspeicher (`cache/inkar_2025.zip`, 434 MB, Stand
  13.08.2025), das BBSR meldete sie als unverändert.
- Alle 264 INKAR-Kürzel: Beide Konfigurationen laden fünf (Gesamtanalyse ohne Datenbanklauf in
  [`../inkar-schluessel/`](../inkar-schluessel/)).
- Ein Änderungslauf mit echten Änderungen und eine Übernahme vorhandener Zeilen: Die Folgeläufe hier sind „alles
  unverändert“, die Datenbanken frisch. Neu, geändert, gelöscht, Übernahme, Kürzel- und Stichtagwechsel prüfen die
  Datenbanktests.
- Die Fehlerpfade aus E44 bis E47 (Abriss der Datenbank, Metadatenkonflikt, gescheiterte Katalogaktualisierung,
  datenbankweite Sperre, fremd vergebene Rechte, Geometrie mit anderem Typ, WFS mit Seitenlimit, Kachel ohne
  Gesamtzahl, zu lange Texte, Folge-Links der OGC API, vorhandene Rolle mit zu weiten Rechten): In diesen Läufen trat
  keiner auf; sie prüfen die Tests.
- `SORTBY` in Kachelabfragen gegen die echten Dienste (oben).
- Im Compose von MOSIDI: Speicher (nicht gemessen), `--haerten`, die übrigen Dienste von MOSIDI (Backend, Frontend,
  GeoServer, nicht gestartet), eine bestehende Datenbank der TH mit Daten und eigenen Rechten, und ob dort der
  Eigentümer der Funktion die echte View aktualisieren darf (hier legte derselbe Administrator beide an).
- Die Laufzeit auf einem ruhigen oder dem Zielrechner.

## Dateien

**Abweichungen der Dateien hier von den Ausgaben der Skripte:** `lauf<n>.out` heißt hier `konsole-lauf<n>.txt`,
`lauf<n>.err` (stderr des Aufrufs, hier nur Meldungen von Compose) heißt `konsole-lauf<n>.err.txt`. Berichte und
Quellenverzeichnis liegen direkt im jeweiligen Ordner statt unter `berichte/`. Anders als nach E46 liegt
`einrichten.log` auch für die Belegläufe bei (Spaltenrechte der Importrolle, Hinweis zur fehlenden View) und
`speicher-lauf3.txt` (Brandenburg, diesmal drei Proben). Nicht beigelegt sind `build.log` (Bauprotokoll des Images),
`schema-public-vorher.txt` und `schema-public-nachher.txt` (Compose-Lauf, sha256 in `ablauf.txt`) und die Sperrdatei
des Berichtsordners. Alle beigelegten Rohdateien (49: Brandenburg 20, Deutschland 15, Compose 14) sind byte-gleich
mit den Rohausgaben (byteweise verglichen am 06.11.2026).

**Die Kartenseiten liegen nicht bei.** Sie enthalten die importierten Datensätze; Quelldaten werden nicht mit dem Code
veröffentlicht (Antwort 69). Die Datenbankauszüge nennen Zählungen und Beispiele des Registers nur als Schlüssel,
ohne Werte.

## Stand

- **Teilbäume** (`git write-tree` des Index nach dem Stagen, vor und nach dieser Dokumentation gleich): `pipeline`
  `74458df1aabeaff70640812fec569e1ab2f71fb2`, `config` `fc6f74c4c393c3da3d4ab481c69dd1d5e73d3c40`, `sql`
  `c7062db0702a61378d36debc27207f3244556ab4`, `tests` `331bf7d09b1255ff40a5fa069a081a56cd4fca59`, `Dockerfile`
  `2953066ba034c0772b8647fcb89c9a710cb5028a`. Dieselben stehen in den Kopfzeilen von `pruefen.log` und
  `datenbanktests.log` und, von den Skripten über eine Kopie des Index aus dem Arbeitsstand berechnet, aus dem das
  Image gebaut wurde, in allen drei `*/ablauf.txt`. Gegenüber dem Prüfstand nach E46 sind `pipeline`, `config`
  (`schluessel_form` in beiden Tabellen der Regionaldatenbank, Kommentar in `europa.yaml`) und `tests` neu, `sql` und
  `Dockerfile` sind gleich.
- **Overlay für MOSIDI:** `mosidi-compose/ablauf.txt` nennt zusätzlich den Teilbaum `deploy` zur Zeit des Laufs
  (`77fa1146b7370655a03c1e1750f7c7095f486822`). Er ändert sich danach nur durch Dokumentation
  (`deploy/mosidi/README.md`, dieser Prüfstand); die benutzte Datei `deploy/mosidi/docker-compose.pipeline.yml` ist
  unverändert, Blob `89dd61692c53fc0b39269dc1bcf1e3645be6ecea` (derselbe wie nach E46; nachprüfbar mit
  `git rev-parse angebot-va-2026-536:deploy/mosidi/docker-compose.pipeline.yml`).
- **Nachprüfbar** nach dem Taggen mit `git rev-parse angebot-va-2026-536:pipeline` usw. Unmittelbar vor dem Taggen
  sind die Teilbäume mit `git write-tree` neu zu berechnen; weichen sie ab, gelten diese Belege nicht für den Tag
  (E45, P14).
- **Reihenfolge:** 05.11.2026 `pruefen.sh` 23:35 MEZ, Datenbanktests 23:44 bis 23:50, Belegläufe Brandenburg 23:51
  bis 23:56 und Deutschland 23:56 bis 06.11. 00:06, Compose-Lauf von MOSIDI 00:06 bis 00:11. Danach kamen nur
  Dokumentation und diese Belege dazu; `pruefen.sh` lief danach erneut nach dem letzten Stagen (`pruefen.log`, Endzeit
  in der Kopfzeile, gleiches Ergebnis wie um 23:35).
