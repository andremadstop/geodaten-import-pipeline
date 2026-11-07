# Lauf im Compose-Setup von MOSIDI (03.11.2026)

> **Stand vor E40.** Die INKAR-Zahl (57 259) stammt aus der Zeit, als wertgleiche Reihen noch zusammengeführt wurden. Seit E40 schreibt dieselbe Konfiguration 62 929 INKAR-Zeilen. **Am Abgabestand nach E46 wiederholt** (05.11.2026, mit Katalogaktualisierung und nachvollziehbarem Ablauf `lauf.sh`): [`../pruefstand-2026-11-05-e46/mosidi-compose/`](../pruefstand-2026-11-05-e46/mosidi-compose/), maßgeblich für den Abgabestand.

`docker-compose.yml` aus MOSIDI-ORG/MOSIDI (Commit 26cadbb, 02.11.2026) mit dem Overlay
`deploy/mosidi/docker-compose.pipeline.yml`; Ablauf in `deploy/mosidi/README.md`.

- `befund-postgresql18.txt`: Das unveränderte `brandenburg_db` (Image `postgis/postgis` ohne Tag, am
  03.11.2026 PostgreSQL 18.6 mit PostGIS 3.6.4) startet auf einem frischen Volume nicht, weil das Volume
  unter `/var/lib/postgresql/data` hängt (Neustart-Schleife, Entscheidung E26).
- Mit dem Volume unter `/var/lib/postgresql` (einzige Abweichung, dazu keine Portfreigabe nach außen):
  `pipeline-einrichten`, dann `pipeline --alle`. `20261103T104447Z.txt`: dieselben Zahlen wie in
  `../mosidi-schema/` (882, 413, 18, 1 239, 413, 57 259), 115 s.
- `datenbank-auszug.txt`: Protokoll in `pipeline_meta` der MOSIDI-Datenbank, 39 Tabellen in `public`
  wie vorher, beide Rollen ohne Superuser-, CREATEDB- oder CREATEROLE-Recht.
