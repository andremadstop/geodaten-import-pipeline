# Prüfstand nach E48 (06.11.2026): Tests ausgeführt, Belegläufe gegen die Dienste als Vorlage

> **Vermerk E49:** Abgabestand ist jetzt der Stand nach E49 (am Code gleich, nur Kommentare); Tests und Läufe dieses
> Stands liegen in [`../pruefstand-2026-11-06-e49/`](../pruefstand-2026-11-06-e49/).
>
> **Vermerk E50:** Abgabestand ist jetzt der Stand nach E50 (Code geändert); Tests und Läufe dieses Stands liegen in
> [`../pruefstand-2026-11-06-e50/`](../pruefstand-2026-11-06-e50/), dorthin sind auch `beleg.sh` und
> `mosidi-compose/lauf.sh` weiter verschoben.
>
> **Vermerk E51:** Abgabestand ist jetzt der Stand nach E51 (Code geändert); Tests und Läufe dieses Stands liegen in
> [`../pruefstand-2026-11-07-e51/`](../pruefstand-2026-11-07-e51/), dorthin sind `beleg.sh` und `mosidi-compose/lauf.sh`
> weiter verschoben.

Abgabestand (Tag `angebot-va-2026-536`, E43) ist der Stand nach E48 mit der Prüfung dazu
([`docs/entscheidungen.md`](../../docs/entscheidungen.md), E48). Dieser Ordner enthält die Testprotokolle dieses
Stands, je mit Zeitpunkt und Teilbäumen (`git write-tree`) in der Kopfzeile; sie stimmen mit den Teilbäumen unter
„Folgen“ in E48 überein.

## Prüfkette

| Prüfung | Ergebnis | Protokoll |
|---|---|---|
| Schritte von `pruefen.sh` (ruff, bandit, pip-audit, Tests ohne Datenbank, Secret-Scan, Stückliste), 06.11.2026 | ohne Befund, 264 Tests bestanden (die 63 Datenbanktests dort übersprungen); bandit gibt nur eine Warnung aus, dass ein `nosec` in `pipeline/quellen.py` keinen Treffer mehr unterdrückt. Abweichung: uv offline aus dem Zwischenspeicher und pip-audit gegen OSV statt gegen die PyPI-JSON-API, weil die robots.txt von PyPI diese Pfade sperrt (Grund in der Kopfzeile, Entscheidung offen, E48) (überholt, siehe E49: PyPI wird als Index-API für Installer normal genutzt) | [`pruefen.log`](pruefen.log) |
| `tests/test_datenbank.py` gegen eine echte PostGIS-Datenbank mit den MOSIDI-Tabellen, `postgis/postgis:16-3.6` (festgeschrieben) | PostgreSQL 16.15: 63 von 63 | [`datenbanktests.log`](datenbanktests.log) |
| dieselben Tests, `postgis/postgis:latest` | PostgreSQL 18.6: 63 von 63 | [`datenbanktests.log`](datenbanktests.log) |

## Läufe gegen die echten Dienste: nicht wiederholt (Läufe in e49 nachgeholt)

> **Vermerk E49 (06.11.2026): Läufe in e49 nachgeholt.** Tests, Belegläufe `quellen` und `deutschland` und der Lauf im
> Compose von MOSIDI sind am Abgabestand nach E49 ausgeführt (Code wie nach E48 (dazu nur die Namensnennung von basemap.de in `pipeline/karte.py`, außerhalb E49), E49 nur Kommentare), alle mit
> Rückgabe 0, in [`../pruefstand-2026-11-06-e49/`](../pruefstand-2026-11-06-e49/). `beleg.sh` und
> `mosidi-compose/lauf.sh` sind mit `git mv` dorthin verschoben und liegen nicht mehr in diesem Ordner. Der Text
> unten ist der Stand vor E49.

Läufe gegen die echten Dienste und im Compose von MOSIDI sind nach E48 nicht wiederholt; die letzten stehen in
[`../pruefstand-2026-11-05-e47/`](../pruefstand-2026-11-05-e47/) (Stand nach E47; ihre Zahlen zur Statistik
stammen aus der Regionaldatenbank, ihre Teilbäume gelten für jenen Stand). `beleg.sh` und `mosidi-compose/lauf.sh`
sind die Vorlagen für eine Wiederholung am Stand nach E48, noch nicht ausgeführt. Sie lesen INKAR nur aus
`cache/inkar_2025.zip` (per `PIPELINE_INKAR_DATEI`, schreibgeschützt eingehängt); `www.bbr-server.de` und
`www.regionalstatistik.de` sind im Container gesperrt. Nicht durch Kopien aus e46/e47 ersetzen.

robots.txt: `www.bbr-server.de` ist gesperrt und wird nicht abgerufen. Das ist kein Abbruchgrund, weil INKAR aus der
abgelegten Datei kommt; den Abruf per URL sieht die TH in Antwort 33 vor (Adresse in ihrer `config.xml`), die
Klärung mit TH und BBSR ist offen (Arbeitspaket 1).
