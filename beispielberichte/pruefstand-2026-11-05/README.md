# Prüfstand 05.11.2026

> Abgelöst durch [`../pruefstand-2026-11-05-e39/`](../pruefstand-2026-11-05-e39/) (Stand nach E39, Nachprüfung zu
> E38). Dieser Ordner bleibt als Beleg des Stands nach E38, einschließlich der Läufe gegen die echten Dienste.
> Maßgeblich für die letzten Läufe gegen die echten Dienste ist [`../pruefstand-2026-11-05-e47/`](../pruefstand-2026-11-05-e47/)
> (Stand nach E47); Abgabestand ist der Stand nach E48, Tests dazu in [`../pruefstand-2026-11-06-e48/`](../pruefstand-2026-11-06-e48/).

Stand nach Entscheidung E38 (Codex-Prüfung vom 04.11.2026, Befunde B3, B5, B6, B11, A1). Wie am 04.11.: alles auf
einem Entwicklungsrechner (Linux, Docker), Datenbanken jeweils frisch in einem Wegwerf-Compose-Projekt aus der `docker-compose.yml`
dieses Repositorys (Schema der MOSIDI-Tabellen aus `sql/mosidi/`), Zugangsdaten je Lauf zufällig erzeugt und danach
gelöscht, Container und Volumes danach entfernt.

| Datei | Was | Ergebnis |
|---|---|---|
| `pruefen.log` | `./pruefen.sh`: ruff, bandit, pip-audit, pytest, Secret-Scan, Stückliste | ohne Befund, 111 Tests bestanden (22 Datenbanktests hier übersprungen, sie laufen getrennt) |
| `datenbanktests.log` | `tests/test_datenbank.py` gegen `postgis/postgis:16-3.6` (festgeschrieben) und `postgis/postgis:latest` | PostgreSQL 16.15: 22 von 22, PostgreSQL 18.6: 22 von 22 |
| `20261105T075019Z.txt`, `.json` | `einrichten --haerten`, dann `pipeline --alle` mit `config/quellen.yaml` gegen die echten Dienste (INKAR-Datei aus dem Zwischenspeicher, vom BBSR als unverändert gemeldet) | 882 Gebäude, 413 Gemeinden, 18 Kreise, 1 239 + 413 Statistikwerte, 57 259 INKAR-Werte in 108 s (5 670 wertgleiche Doppelzeilen zusammengeführt); Flächenprüfung 413 Gemeinden, Median 0,005 %, höchstens 0,161 %; keine unlesbare Geometrie |
| `20261105T075211Z.txt`, `.json` | derselbe Befehl direkt danach | alles unverändert, 106 s |
| `20261105T075409Z.txt`, `.json` | `pipeline` ohne `--alle` | alle sechs Quellen „nicht fällig“ (Rhythmus), 0,03 s |
| `datenbank-auszug.txt` | Version, `table_metadata`, Zeilen je `source`, Laufprotokoll | 14 Zeilen in `table_metadata` mit 3 Herausgebern, 1 652 + 57 259 Kennzahlen |

Unterschied zu den Läufen vom 04.11. (119 s und 115 s): Geometrien werden seit E38 einmal je Zeile gelesen und dabei
geprüft, ob PostGIS sie lesen kann; die Laufzeit ist dadurch nicht gestiegen. Die Änderungskarten der Läufe liegen
hier nicht bei, weil sie die importierten Datensätze enthalten (Antwort 69); eine Karte mit erfundenen Daten liegt in
`../aenderungskarte/`. Die Warnung zu `aktualit` (882 Gebäude, 11 statt 10 Zeichen) ist wie am 04.11. ein Befund am
Schema, geklärt wird er in Arbeitspaket 1 mit dem DDL der TH.

Die Protokolle nennen den Git-Baum des Stands, an dem sie liefen (`a9a568bb…`, der gestagte Stand vor diesen
Belegen). Danach kamen bis zur Nachprüfung (E39) nur Dokumentation (einschließlich eines Kommentars in
`deploy/mosidi/geodaten-import-mosidi.service`) und diese Belege dazu; `pipeline/`, `tests/` und `config/` blieben
bis dahin unverändert. Seit E39 sind sie geändert, der Stand nach E38 ist deshalb nicht als eigener Commit
veröffentlicht. Seine Teilbäume (wie `git rev-parse <Baum>:pipeline` sie nennt): `pipeline`
`5435a98609dff36afa02517be1cc4c15d9bfb87f`, `tests` `595216478672caba155c669038d7485a7d89a672`, `config`
`5f28abda1df243751f6631771719779716e6e8c6`. Für den veröffentlichten Stand
(Tag `angebot-va-2026-536`, E43) gilt [`../pruefstand-2026-11-05-e47/`](../pruefstand-2026-11-05-e47/) (Tests, Läufe gegen die echten Dienste, Teilbäume).
