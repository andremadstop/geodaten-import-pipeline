# Prüfstand 05.11.2026, Nachprüfung zu E38 (E39)

> Abgelöst durch [`../pruefstand-2026-11-05-e40/`](../pruefstand-2026-11-05-e40/) (Stand nach E40/E41), [`../pruefstand-2026-11-05-e42/`](../pruefstand-2026-11-05-e42/) (Stand nach E42) und zuletzt durch [`../pruefstand-2026-11-05-e45/`](../pruefstand-2026-11-05-e45/) (Stand nach E45, Tests und Läufe gegen die echten Dienste), dieser seit 05.11. abgelöst durch [`../pruefstand-2026-11-05-e46/`](../pruefstand-2026-11-05-e46/) (Abgabestand nach E46). Dieser Ordner bleibt als Beleg des Stands nach E39.

Stand nach Entscheidung E39: Befunde einer zweiten unabhängigen Prüfung zu E38 behoben (Einzelheiten in
[`docs/entscheidungen.md`](../../docs/entscheidungen.md), E39). Alles auf einem Entwicklungsrechner (Linux, Docker),
Datenbanken jeweils frisch in einem Wegwerf-Compose-Projekt aus der `docker-compose.yml` dieses Repositorys (Schema
der MOSIDI-Tabellen aus `sql/mosidi/`), Zugangsdaten je Lauf zufällig erzeugt und danach gelöscht, Container und
Volumes danach entfernt.

| Datei | Was | Ergebnis |
|---|---|---|
| `pruefen.log` | `./pruefen.sh`: ruff, bandit, pip-audit, pytest, Secret-Scan, Stückliste | ohne Befund, 119 Tests bestanden (24 Datenbanktests hier übersprungen, sie laufen getrennt) |
| `datenbanktests.log` | `tests/test_datenbank.py` gegen `postgis/postgis:16-3.6` (festgeschrieben) und `postgis/postgis:latest` | PostgreSQL 16.15: 24 von 24, PostgreSQL 18.6: 24 von 24 |
| `geos-probe.txt` | Gibt es Geometrien, die PostGIS liest, bei denen aber `ST_IsValid` einen Fehler wirft statt `false`? (Begründung in E38) | Mit PostGIS 3.6.4 und GEOS 3.14.1 auf beiden Versionen nein: offene Ringe, Ringe mit drei Punkten, NaN und Unendlich ergeben `false` |

**Nicht wiederholt:** die Läufe gegen die echten Dienste (LGB, Regionaldatenbank, INKAR). Sie stehen in
[`../pruefstand-2026-11-05/`](../pruefstand-2026-11-05/) und liefen am Stand nach E38 (Git-Baum `a9a568bb…`). Seitdem
geändert, was diese Läufe berühren: Kartenseite (Lizenztext von Leaflet als Kommentar, Datenblöcke ohne `<`, `>`,
`&`), `einrichten` (Passwort als SCRAM-Hash, Prüfung auf plpgsql), Hinweis „Wiederholung“ nur, wenn die Quelle sonst
nicht fällig wäre, Kartenabfrage bei `karte: false` übersprungen, Abbruchbericht vor der Sperre ohne Nachtrag in
fremde Berichte. Abruf, Abgleich und Schreiben der Quellen sind unverändert; alle diese Änderungen sind von den Tests
oben abgedeckt, das Einrichten mit SCRAM-Hash von jedem Datenbanktest (jede Anmeldung der Importrolle nutzt es).

Die Protokolle nennen den Git-Baum, an dem sie liefen (`150b99fe…`, der gestagte Stand vor diesen Belegen). Danach
kamen nur Dokumentation und diese Belege dazu; `pipeline/`, `tests/` und `config/` sind unverändert. Teilbäume dieses
Stands: `pipeline` `d783b6fd92e6c5cafccc5323b6a761a73ad14da1`, `tests` `5aa9a72df709224f19cd3bc8a54cf52147728b9e`,
`config` `5f28abda1df243751f6631771719779716e6e8c6`. Seit E40 bis E42 sind sie geändert; dieser Stand ist nie als
eigener Commit veröffentlicht (E43), der veröffentlichte Stand ist in
[`../pruefstand-2026-11-05-e47/`](../pruefstand-2026-11-05-e47/) belegt.
