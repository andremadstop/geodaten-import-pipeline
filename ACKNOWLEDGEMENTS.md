# Standing on the shoulders of …

*Deutsch: [DANK.md](DANK.md)*

This pipeline is small. Almost everything it can do it owes to others: people who spent years building databases, libraries, checking tools and map services and gave them away openly, and public agencies that make their data free to use. This is who they are, what we use their work for, and under which licence. `./pruefen.sh` produces a machine-readable bill of materials of the Python dependencies as `sbom.cdx.json` (with the versions and hashes from `requirements.txt`); operating-system packages of the container, Leaflet, the database and the checking tools are not in it but in the tables here.

## What runs during an import

| Tool | Used for | Licence |
|---|---|---|
| [Python](https://www.python.org/) 3.12 | language of the pipeline | PSF-2.0 |
| [PostgreSQL](https://www.postgresql.org/) | database | PostgreSQL License |
| [PostGIS](https://postgis.net/) | geometries, coordinate transformation, areas | GPL-2.0-or-later |
| [psycopg](https://www.psycopg.org/) 3 | connection Python ↔ PostgreSQL | LGPL-3.0 |
| [lxml](https://lxml.de/) | reading GML and capabilities, hardened | BSD-3-Clause |
| [PyYAML](https://pyyaml.org/) | configuration | MIT |
| [requests](https://requests.readthedocs.io/) | fetching from the services | Apache-2.0 |
| [openpyxl](https://openpyxl.readthedocs.io/) | reading statistical reports as XLSX (E48) | MIT |
| [defusedxml](https://github.com/tiran/defusedxml) | hardens the XML parser of openpyxl (no entities) | PSF-2.0 |
| [Info-ZIP unzip](https://infozip.sourceforge.net/) | INKAR archive inside the container | Info-ZIP License |
| [Debian](https://www.debian.org/) (Python image) | base of the container | DFSG-free licences |

Pulled in by requests, psycopg and openpyxl (indirect dependencies, pinned in `requirements.txt`):

| Package | Purpose | Licence |
|---|---|---|
| [urllib3](https://urllib3.readthedocs.io/) | HTTP connections under requests | MIT |
| [certifi](https://github.com/certifi/python-certifi) | root certificates for https | MPL-2.0 |
| [idna](https://github.com/kjd/idna) | internationalised host names | BSD-3-Clause |
| [charset-normalizer](https://github.com/jawah/charset_normalizer) | detect the character set of responses | MIT |
| [typing-extensions](https://github.com/python/typing_extensions) | type hints for psycopg | PSF-2.0 |
| [et-xmlfile](https://foss.heptapod.net/openpyxl/et_xmlfile) | XML writer under openpyxl | MIT |
| psycopg-binary (bundles libpq and OpenSSL) | database driver as a ready-made package | LGPL-3.0; libpq PostgreSQL License, OpenSSL Apache-2.0 |

All are compatible with the pipeline's Apache-2.0 licence; none is copied into the pipeline's code. The bill of materials from `pruefen.sh` (`sbom.cdx.json`, CycloneDX) covers the Python packages, not the packages of the Debian image (such as `unzip`) and not Leaflet.

## What you see in the change map

| Tool or data | Used for | Licence |
|---|---|---|
| [Leaflet](https://leafletjs.com/) 1.9.4, © 2010–2023 Volodymyr Agafonkin, © 2010–2011 CloudMade | map view in the browser; copied into the repository (`pipeline/vendor/leaflet-1.9.4/`, with licence text) and embedded in every map page | BSD-2-Clause |
| [basemap.de](https://basemap.de/) Web Raster grau | base map, only with `karte.hintergrund: [basemap]` | © GeoBasis-DE / BKG (2026), dl-de/by-2-0 (linked to https://www.bkg.bund.de) |
| Digital orthophotos DOP20 of the LGB | aerial image, only with `karte.hintergrund: [luftbild]` | © GeoBasis-DE/LGB, dl-de/by-2-0 |

## What we check and build with

| Tool | Used for | Licence |
|---|---|---|
| [uv](https://docs.astral.sh/uv/) | environment, pinned dependencies with hashes | MIT / Apache-2.0 |
| [Ruff](https://docs.astral.sh/ruff/) | style and common mistakes | MIT |
| [Bandit](https://bandit.readthedocs.io/) | security check of the code | Apache-2.0 |
| [pip-audit](https://github.com/pypa/pip-audit) | known vulnerabilities in dependencies | Apache-2.0 |
| [pytest](https://pytest.org/) | tests | MIT |
| [detect-secrets](https://github.com/Yelp/detect-secrets) / [gitleaks](https://github.com/gitleaks/gitleaks) | no credentials in the repository | Apache-2.0 / MIT |
| [CycloneDX](https://cyclonedx.org/) | bill of materials | Apache-2.0 |
| [Docker](https://www.docker.com/) Engine and Compose | containers | Apache-2.0 |
| [CodeCharta](https://codecharta.com/) | code map in `docs/codekarte/` | BSD-3-Clause |

## Where the data comes from

| Data | Provider | Licence |
|---|---|---|
| ALKIS vereinfacht (WFS), municipalities (OGC API – Features) | Landesvermessung und Geobasisinformation Brandenburg (LGB) | © GeoBasis-DE/LGB, dl-de/by-2-0 |
| Administrative areas VG250 (WFS) | Bundesamt für Kartographie und Geodäsie (BKG) | © BKG (2026), dl-de/by-2-0 |
| INKAR | Bundesinstitut für Bau-, Stadt- und Raumforschung (BBSR) | © BBSR Bonn 2025, dl-de/by-2-0 |
| Population and area per municipality (statistical report A I 4 / A V 2, XLSX; since E48, previously Regionaldatenbank) | Amt für Statistik Berlin-Brandenburg | Amt für Statistik Berlin-Brandenburg, CC BY 3.0 DE |
| Municipalities (LAU 2024) with population and area, Europe trial run only (GeoJSON, CSV) | Eurostat GISCO | © EuroGeographics for the administrative boundaries; no commercial use under the download rules |

## What the bid, graphics and documentation were made with

| Tool | Used for | Licence |
|---|---|---|
| [Markdown](https://python-markdown.github.io/) und [WeasyPrint](https://weasyprint.org/) | text in Markdown, typeset as PDF | BSD-3-Clause |
| [Newsreader](https://github.com/productiontype/Newsreader) und [Inter Tight](https://github.com/rsms/inter) | typefaces | SIL Open Font License 1.1 |
| PostGIS and a small script of our own | maps from the pipeline's data, directly as SVG | see above |
| [librsvg](https://gitlab.gnome.org/GNOME/librsvg) | converting SVG to images | LGPL-2.1-or-later |
| [Git](https://git-scm.com/) | versions, every change signed | GPL-2.0 |
| Claude (Anthropic) | help with writing code and text | not open, therefore named separately here |

About the last line: I build with AI. I check what goes into the repository: the code runs against real services and through `pruefen.sh` before every commit, and every figure in the bid is backed by a run report in `beispielberichte/`. How we handle this is decision E13 in [docs/entscheidungen.md](docs/entscheidungen.md) (German).

## Colophon

Built in Potsdam, a few kilometres from the Telegrafenberg. There Friedrich Robert Helmert (1843–1917) inaugurated the Geodetic Institute in 1892; the Helmert transformation, used to convert coordinates between reference systems, is named after him, and the Helmert Tower of 1892/93 was a reference point of the Prussian survey. The measured photograph I work with as a photographer goes back to Albrecht Meydenbauer (1834–1921): after nearly falling from Wetzlar Cathedral around 1858 he set out to replace measuring by hand with the photograph, and in 1885 he founded the Royal Prussian Photogrammetric Institute in Berlin. This pipeline stands in that tradition of making measurement and image openly verifiable, just with smaller tools.

`docker compose run --rm --no-deps pipeline --version` shows Brandenburg, computed from the 413 municipal areas of the LGB, and a different note from this history every day.

Sources: Neue Deutsche Biographie (Helmert, vol. 8; Meydenbauer, vol. 17; Baeyer, vol. 1), [GFZ, history of the Telegrafenberg](https://www.gfz.de/en/about-us/organisation/history), [Philipps-Universität Marburg, Messbildverfahren](https://www.uni-marburg.de/de/fotomarburg/histfoto/gliederung/messbilder/messbildverfahren), A. Grimm, [The Origin of the Term Photogrammetry](https://www.isprs.org/society/history/Grimm-The-Origin-of-the-Term-Photogrammetry.pdf).

André Stiebitz, Potsdam, November 2026
