# Auf den Schultern von …

*English: [ACKNOWLEDGEMENTS.md](ACKNOWLEDGEMENTS.md)*

Diese Pipeline ist klein. Was sie kann, verdankt sie fast ganz anderen: Leuten, die über Jahre Datenbanken, Bibliotheken, Prüfwerkzeuge und Kartendienste gebaut und offen weitergegeben haben, und Ämtern, die ihre Daten frei nutzbar machen. Hier steht, wer das ist, wofür wir es brauchen und unter welcher Lizenz. `./pruefen.sh` erzeugt eine maschinenlesbare Stückliste der Python-Abhängigkeiten als `sbom.cdx.json` (mit Versionen und Prüfsummen aus `requirements.txt`); Betriebssystempakete des Containers, Leaflet, Datenbank und Prüfwerkzeuge stehen nicht darin, sondern in den Tabellen hier.

## Was beim Import läuft

| Werkzeug | Wofür | Lizenz |
|---|---|---|
| [Python](https://www.python.org/) 3.12 | Sprache der Pipeline | PSF-2.0 |
| [PostgreSQL](https://www.postgresql.org/) | Datenbank | PostgreSQL License |
| [PostGIS](https://postgis.net/) | Geometrien, Koordinatentransformation, Flächen | GPL-2.0-or-later |
| [psycopg](https://www.psycopg.org/) 3 | Verbindung Python ↔ PostgreSQL | LGPL-3.0 |
| [lxml](https://lxml.de/) | GML und Capabilities lesen, gehärtet | BSD-3-Clause |
| [PyYAML](https://pyyaml.org/) | Konfiguration | MIT |
| [requests](https://requests.readthedocs.io/) | Abruf der Dienste | Apache-2.0 |
| [openpyxl](https://openpyxl.readthedocs.io/) | Statistische Berichte als XLSX lesen (E48) | MIT |
| [defusedxml](https://github.com/tiran/defusedxml) | XML-Parser von openpyxl gehärtet (keine Entitäten) | PSF-2.0 |
| [Info-ZIP unzip](https://infozip.sourceforge.net/) | INKAR-Gesamtdatei im Container | Info-ZIP License |
| [Debian](https://www.debian.org/) (Python-Image) | Grundlage des Containers | DFSG-freie Lizenzen |

Mitgezogen von requests, psycopg und openpyxl (indirekte Abhängigkeiten, festgeschrieben in `requirements.txt`):

| Paket | Wofür | Lizenz |
|---|---|---|
| [urllib3](https://urllib3.readthedocs.io/) | HTTP-Verbindungen unter requests | MIT |
| [certifi](https://github.com/certifi/python-certifi) | Wurzelzertifikate für https | MPL-2.0 |
| [idna](https://github.com/kjd/idna) | internationale Rechnernamen | BSD-3-Clause |
| [charset-normalizer](https://github.com/jawah/charset_normalizer) | Zeichensatz von Antworten erkennen | MIT |
| [typing-extensions](https://github.com/python/typing_extensions) | Typangaben für psycopg | PSF-2.0 |
| [et-xmlfile](https://foss.heptapod.net/openpyxl/et_xmlfile) | XML-Schreiber unter openpyxl | MIT |
| psycopg-binary (enthält libpq und OpenSSL) | Datenbanktreiber als fertiges Paket | LGPL-3.0; libpq PostgreSQL License, OpenSSL Apache-2.0 |

Alle sind mit Apache-2.0 der Pipeline vereinbar; keines ist in den Code der Pipeline kopiert. Die Stückliste aus `pruefen.sh` (`sbom.cdx.json`, CycloneDX) enthält die Python-Pakete, nicht die Pakete des Debian-Images (etwa `unzip`) und nicht Leaflet.

## Was man in der Änderungskarte sieht

| Werkzeug oder Daten | Wofür | Lizenz |
|---|---|---|
| [Leaflet](https://leafletjs.com/) 1.9.4, © 2010–2023 Volodymyr Agafonkin, © 2010–2011 CloudMade | Kartenansicht im Browser; als Kopie im Repository (`pipeline/vendor/leaflet-1.9.4/`, mit Lizenztext) und eingebettet in jede Kartenseite | BSD-2-Clause |
| [basemap.de](https://basemap.de/) Web Raster grau | Grundkarte, nur mit `karte.hintergrund: [basemap]` | © GeoBasis-DE / BKG (2026), dl-de/by-2-0 (Link auf https://www.bkg.bund.de) |
| Digitale Orthophotos DOP20 der LGB | Luftbild, nur mit `karte.hintergrund: [luftbild]` | © GeoBasis-DE/LGB, dl-de/by-2-0 |

## Womit geprüft und gebaut wird

| Werkzeug | Wofür | Lizenz |
|---|---|---|
| [uv](https://docs.astral.sh/uv/) | Umgebung, festgeschriebene Abhängigkeiten mit Prüfsummen | MIT / Apache-2.0 |
| [Ruff](https://docs.astral.sh/ruff/) | Stil und typische Fehler | MIT |
| [Bandit](https://bandit.readthedocs.io/) | Sicherheitsprüfung des Codes | Apache-2.0 |
| [pip-audit](https://github.com/pypa/pip-audit) | bekannte Lücken in Abhängigkeiten | Apache-2.0 |
| [pytest](https://pytest.org/) | Tests | MIT |
| [detect-secrets](https://github.com/Yelp/detect-secrets) / [gitleaks](https://github.com/gitleaks/gitleaks) | keine Zugangsdaten im Repository | Apache-2.0 / MIT |
| [CycloneDX](https://cyclonedx.org/) | Stückliste der Abhängigkeiten | Apache-2.0 |
| [Docker](https://www.docker.com/) Engine und Compose | Container | Apache-2.0 |
| [CodeCharta](https://codecharta.com/) | Code-Karte in `docs/codekarte/` | BSD-3-Clause |

## Woher die Daten kommen

| Daten | Anbieter | Lizenz |
|---|---|---|
| ALKIS vereinfacht (WFS), Gemeinden (OGC API – Features) | Landesvermessung und Geobasisinformation Brandenburg (LGB) | © GeoBasis-DE/LGB, dl-de/by-2-0 |
| Verwaltungsgebiete VG250 (WFS) | Bundesamt für Kartographie und Geodäsie (BKG) | © BKG (2026), dl-de/by-2-0 |
| INKAR | Bundesinstitut für Bau-, Stadt- und Raumforschung (BBSR) | © BBSR Bonn 2025, dl-de/by-2-0 |
| Bevölkerung und Gebietsfläche je Gemeinde (Statistischer Bericht A I 4 / A V 2, XLSX; seit E48, vorher Regionaldatenbank) | Amt für Statistik Berlin-Brandenburg | Amt für Statistik Berlin-Brandenburg, CC BY 3.0 DE |
| Gemeinden (LAU 2024) mit Bevölkerung und Fläche, nur Probelauf Europa (GeoJSON, CSV) | Eurostat GISCO | © EuroGeographics bezüglich der Verwaltungsgrenzen; laut Download-Regeln keine kommerzielle Nutzung |

## Womit Angebot, Grafiken und Dokumentation entstanden sind

| Werkzeug | Wofür | Lizenz |
|---|---|---|
| [Markdown](https://python-markdown.github.io/) und [WeasyPrint](https://weasyprint.org/) | Text in Markdown, gesetzt als PDF | BSD-3-Clause |
| [Newsreader](https://github.com/productiontype/Newsreader) und [Inter Tight](https://github.com/rsms/inter) | Schriften | SIL Open Font License 1.1 |
| PostGIS und ein kleines eigenes Skript | Karten aus den Daten der Pipeline, direkt als SVG | siehe oben |
| [librsvg](https://gitlab.gnome.org/GNOME/librsvg) | SVG in Bilder umrechnen | LGPL-2.1-or-later |
| [Git](https://git-scm.com/) | Versionen, jede Änderung signiert | GPL-2.0 |
| Claude (Anthropic) | Hilfe beim Schreiben von Code und Text | nicht offen, deshalb hier eigens genannt |

Zur letzten Zeile: Ich baue mit KI. Was davon ins Repository kommt, prüfe ich: Der Code läuft gegen echte Dienste und vor jedem Commit durch `pruefen.sh`, jede Zahl im Angebot steht in einem Laufbericht unter `beispielberichte/`. Wie wir damit umgehen, steht in Entscheidung E13 in [docs/entscheidungen.md](docs/entscheidungen.md).

## Kolophon

Gebaut in Potsdam, ein paar Kilometer vom Telegrafenberg. Dort weihte Friedrich Robert Helmert (1843–1917) 1892 das Geodätische Institut ein; nach ihm heißt die Helmert-Transformation, mit der man Koordinaten zwischen Bezugssystemen umrechnet, und der Helmertturm von 1892/93 war Bezugspunkt der preußischen Landesvermessung. Das Messbild, mit dem ich als Fotograf arbeite, geht auf Albrecht Meydenbauer (1834–1921) zurück: Nach einem Beinahe-Absturz am Wetzlarer Dom um 1858 wollte er das Messen von Hand durch das Foto ersetzen, 1885 gründete er in Berlin die Königlich Preußische Messbildanstalt. Diese Pipeline steht in der Tradition, Messung und Bild offen nachprüfbar zu machen, nur mit kleineren Werkzeugen.

`docker compose run --rm --no-deps pipeline --version` zeigt Brandenburg, berechnet aus den 413 Gemeindeflächen der LGB, und jeden Tag eine andere Notiz aus dieser Geschichte.

Quellen: Neue Deutsche Biographie (Helmert, Bd. 8; Meydenbauer, Bd. 17; Baeyer, Bd. 1), [GFZ, Geschichte des Telegrafenbergs](https://www.gfz.de/en/about-us/organisation/history), [Philipps-Universität Marburg, Messbildverfahren](https://www.uni-marburg.de/de/fotomarburg/histfoto/gliederung/messbilder/messbildverfahren), A. Grimm, [The Origin of the Term Photogrammetry](https://www.isprs.org/society/history/Grimm-The-Origin-of-the-Term-Photogrammetry.pdf).

André Stiebitz, Potsdam, November 2026
