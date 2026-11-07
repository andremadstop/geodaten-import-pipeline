# Prüfstand 04.11.2026

> Abgelöst durch [`../pruefstand-2026-11-05/`](../pruefstand-2026-11-05/) (Stand nach E38) und [`../pruefstand-2026-11-05-e39/`](../pruefstand-2026-11-05-e39/) (Stand nach E39). Dieser Ordner bleibt als Beleg des Angebotsstands vom 04.11. Maßgeblich für den Abgabestand ist [`../pruefstand-2026-11-05-e46/`](../pruefstand-2026-11-05-e46/) (Tests und Läufe gegen die echten Dienste).

Stand des Angebots zur Vergabe VA-2026-536. Alles auf einem Entwicklungsrechner (Linux, Docker), Datenbanken jeweils frisch
in einem Wegwerf-Compose-Projekt aus der `docker-compose.yml` dieses Repositorys (Schema der MOSIDI-Tabellen
aus `sql/mosidi/`), Zugangsdaten je Lauf zufällig erzeugt und danach gelöscht.

| Datei | Was | Ergebnis |
|---|---|---|
| `pruefen.log` | `./pruefen.sh`: ruff, bandit, pip-audit, pytest, Secret-Scan, Stückliste | ohne Befund, 97 Tests bestanden (Datenbanktests hier übersprungen, sie laufen getrennt) |
| `datenbanktests.log` | `tests/test_datenbank.py` gegen `postgis/postgis:16-3.6` (festgeschrieben) und `postgis/postgis:latest` | PostgreSQL 16.15: 19 von 19, PostgreSQL 18.6: 19 von 19 |
| `20261104T150500Z.txt`, `.json` | `einrichten`, dann `pipeline --alle` mit `config/quellen.yaml` gegen die echten Dienste | 882 Gebäude, 413 Gemeinden, 18 Kreise, 1 239 + 413 Statistikwerte, 57 259 INKAR-Werte in 119 s (5 670 wertgleiche Doppelzeilen zusammengeführt); Flächenprüfung 413 Gemeinden, Median 0,005 %, höchstens 0,161 % |
| `20261104T150702Z.txt`, `.json` | derselbe Befehl direkt danach | alles unverändert, 115 s |

Die Warnung zu `aktualit`
(882 Gebäude, 11 statt 10 Zeichen) ist ein Befund am Schema: Die Spalte ist in MOSIDI `varchar(10)`, der
Dienst liefert 11 Zeichen; die Pipeline meldet das, statt still zu kürzen, geklärt wird es in Arbeitspaket 1
mit dem DDL der TH.

Die Protokolle nennen den Git-Baum des Stands, an dem sie liefen (`181d9596…`). Das war der Stand des
Angebots am 04.11.2026; er wurde nie als eigener Commit veröffentlicht, der Baum liegt nur im lokalen
Repository. Seit E38 und E39 (05.11.) sind `pipeline/`, `tests/` und `config/` geändert; die Belege dazu,
mit den Hashes der Teilbäume, stehen in [`../pruefstand-2026-11-05/`](../pruefstand-2026-11-05/) und
[`../pruefstand-2026-11-05-e39/`](../pruefstand-2026-11-05-e39/).
