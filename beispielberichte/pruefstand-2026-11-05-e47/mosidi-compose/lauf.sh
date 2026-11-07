#!/bin/bash
# Lauf im Compose-Setup von MOSIDI, Stand nach E47 (so am 05.11.2026 ausgeführt): Wiederholung des Laufs vom
# 03.11.2026 (beispielberichte/mosidi-compose/) mit der docker-compose.yml aus MOSIDI-ORG/MOSIDI und dem Overlay
# deploy/mosidi/docker-compose.pipeline.yml, dazu die Katalogaktualisierung aus E46 gegen die View
# source_granularities in der Fassung aus MOSIDI (services/backend/src/db_table_metadata/script.py).
# Aufruf: beispielberichte/pruefstand-2026-11-05-e47/mosidi-compose/lauf.sh <MOSIDI-Verzeichnis> <Ausgabeordner>
# Das MOSIDI-Verzeichnis ist ein Klon ohne .env und pg_tileserv.env; beide legt das Skript mit zufälligen
# Passwörtern an und löscht sie am Ende wieder, ebenso Container und Volumes (down -v).
# Abweichungen vom unveränderten Compose stehen nur im Test-Override unten (wie am 03.11.): Volume unter
# /var/lib/postgresql, keine Portfreigabe, eigener Containername; dazu das Image dieses Stands und der
# Berichtsordner im Ausgabeordner statt im Repository.
# Ausgaben: ablauf.txt, befund-postgresql18.txt, einrichten.log, lauf<n>.out, lauf<n>.err, datenbank-auszug.txt,
# schema-public-vorher.txt, schema-public-nachher.txt, berichte/.
# Abgelöst, nicht mehr ausführen (Nachprüfung zu E50, 06.11.2026): Das Skript baut den aktuellen Stand und
# hängt das aktuelle config/ ein, ohne PIPELINE_INKAR_DATEI. Seit E50 trägt die ausgelieferte Konfiguration
# die Freigabe für den INKAR-Abruf per URL; ein erneuter Start riefe www.bbr-server.de ab (HEAD-Suche und
# rund 430 MB), gegen unsere Regel, diesen Rechner nie selbst abzurufen. Der Rest darunter ist unverändert
# der Stand, mit dem die Belege entstanden sind. Belegläufe am aktuellen Stand:
# beispielberichte/pruefstand-2026-11-07-e51/ (INKAR aus der abgelegten Datei; bis E51 pruefstand-2026-11-06-e50/).
echo "Abgelöst (Nachprüfung zu E50): nicht ausführen, INKAR würde per URL abgerufen" >&2; exit 1
set -u
M=$(cd "$1" && pwd); mkdir -p "$2"; OUT=$(cd "$2" && pwd)
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
IMG=geodaten-import-pipeline:e47-beleg
P=gip-mosidi-e47-$$
S=$(mktemp -d)   # nur für die Compose-Ergänzungen
B=$S/befund.override.yml; O=$S/test.override.yml
mkdir -p "$OUT/berichte"; chmod 777 "$OUT/berichte"
if [ -e "$M/.env" ] || [ -e "$M/pg_tileserv.env" ]; then echo ".env oder pg_tileserv.env schon vorhanden"; exit 1; fi
( umask 077; { echo POSTGRES_DB=brandenburg; echo POSTGRES_USER=admin
  for n in POSTGRES_PASSWORD IMPORT_PASSWORD LESE_PASSWORD; do echo "$n=$(openssl rand -hex 24)"; done; } > "$M/.env"
  : > "$M/pg_tileserv.env" )
export PIPELINE_DIR=$REPO
cat > "$B" <<YML
services:
  brandenburg_db:
    container_name: $P-befund-db
    ports: !reset []
YML
cat > "$O" <<YML
services:
  brandenburg_db:
    container_name: $P-db
    ports: !reset []
    volumes: !override
      - brandenburg_db:/var/lib/postgresql
  pipeline-einrichten:
    image: $IMG
  pipeline:
    image: $IMG
    volumes: !override
      - $REPO/config:/app/config:ro
      - $OUT/berichte:/app/berichte
      - $REPO/cache:/app/cache
YML
dcb() { docker compose -f "$M/docker-compose.yml" -f "$B" -p "$P-befund" "$@"; }
dcp() { docker compose -f "$M/docker-compose.yml" -f "$REPO/deploy/mosidi/docker-compose.pipeline.yml" -f "$O" -p "$P" "$@"; }
aufraeumen() {
  dcb down -v >/dev/null 2>&1; dcp --profile pipeline down -v >/dev/null 2>&1
  rm -f "$M/.env" "$M/pg_tileserv.env" "$B" "$O"; rmdir "$S"
}
trap aufraeumen EXIT
cd "$M"
sql() { dcp exec -T brandenburg_db psql -X -v ON_ERROR_STOP=1 -U admin -d brandenburg "$@"; }
{
  echo "# MOSIDI $(git -C "$M" log -1 --format='%H %ci')"
  T=$(cd "$REPO" && cp "$(git rev-parse --git-dir)/index" "$S/index" && GIT_INDEX_FILE="$S/index" git add -A pipeline config sql tests Dockerfile deploy \
      && GIT_INDEX_FILE="$S/index" git write-tree); rm -f "$S/index"
  for d in pipeline config sql tests Dockerfile deploy; do echo "# $d $(cd "$REPO" && git rev-parse "$T:$d")"; done
  echo "# Image $IMG $(docker image inspect -f '{{.Id}}' "$IMG")"
} > "$OUT/ablauf.txt"

# 1. Unverändertes brandenburg_db (nur ohne Portfreigabe und mit eigenem Containernamen) auf frischem Volume
dcb up -d brandenburg_db >/dev/null 2>&1
for i in $(seq 1 30); do sleep 1; done
C=$P-befund-db
echo "befund: Image $(docker inspect -f '{{.Config.Image}}' "$C"), Status $(docker inspect -f '{{.State.Status}}' "$C"), Neustarts nach 30 s $(docker inspect -f '{{.RestartCount}}' "$C"), $(docker run --rm --entrypoint postgres "$(docker inspect -f '{{.Image}}' "$C")" --version)" >> "$OUT/ablauf.txt"
docker logs "$C" 2>&1 | grep -m1 -A24 '^Error: in 18+' > "$OUT/befund-postgresql18.txt"
dcb down -v >/dev/null 2>&1

# 2. Mit Volume unter /var/lib/postgresql: Bestandsschema, View aus MOSIDI, einrichten, zwei Läufe
dcp up -d brandenburg_db >/dev/null 2>&1 || { echo "Start fehlgeschlagen"; exit 1; }
for i in $(seq 1 120); do
  docker logs "$P-db" 2>&1 | grep -q 'PostgreSQL init process complete' && sql -tAc 'SELECT 1' >/dev/null 2>&1 && break; sleep 1
done
sql -tAc "SELECT version()" >> "$OUT/ablauf.txt"
sql -tAc "SELECT postgis_lib_version()" | sed 's/^/PostGIS /' >> "$OUT/ablauf.txt"
sql -q < "$REPO/sql/mosidi/001_bestand.sql" > "$S/bestand.log" 2>&1; echo "Bestandsschema sql/mosidi/001_bestand.sql rc=$?" >> "$OUT/ablauf.txt"
V=services/backend/src/db_table_metadata/script.py
sed -n '/^DROP MATERIALIZED VIEW IF EXISTS source_granularities;/,/ON source_granularities(indikator);/p' "$M/$V" > "$S/view.sql"
echo "View source_granularities aus MOSIDI $V, Zeilen $(grep -n '^DROP MATERIALIZED VIEW IF EXISTS source_granularities;' "$M/$V" | cut -d: -f1) bis $(grep -n 'ON source_granularities(indikator);' "$M/$V" | cut -d: -f1), sha256 $(sha256sum < "$S/view.sql" | cut -c1-64)" >> "$OUT/ablauf.txt"
sql -q < "$S/view.sql" >> "$S/bestand.log" 2>&1; echo "View angelegt (als admin) rc=$?" >> "$OUT/ablauf.txt"
rm -f "$S/bestand.log" "$S/view.sql"
schema() { dcp exec -T brandenburg_db pg_dump -U admin -d brandenburg --schema-only --schema=public --no-privileges --no-owner \
             | grep -v -E '^\\(un)?restrict ' ; }
schema > "$OUT/schema-public-vorher.txt"
zeilen() { echo "$1: source_granularities $(sql -tAc 'SELECT count(*) FROM public.source_granularities') Zeilen" >> "$OUT/ablauf.txt"; }
zeilen "vor einrichten"
dcp --profile pipeline run --rm pipeline-einrichten > "$OUT/einrichten.log" 2>&1; echo "einrichten rc=$?" >> "$OUT/ablauf.txt"
for n in 1 2; do
  echo "lauf$n: Rechnerlast davor (1/5/15 min): $(cut -d' ' -f1-3 /proc/loadavg)" >> "$OUT/ablauf.txt"
  t0=$(date +%s.%N)
  dcp --profile pipeline run --rm pipeline --alle > "$OUT/lauf$n.out" 2> "$OUT/lauf$n.err"
  rc=$?; t1=$(date +%s.%N)
  echo "lauf$n: Argumente '--alle', Rückgabe $rc, Wandzeit $(echo "$t1 - $t0" | bc) s (einschließlich Containerstart), Rechnerlast danach (1/5/15 min): $(cut -d' ' -f1-3 /proc/loadavg), $(nproc) Kerne" >> "$OUT/ablauf.txt"
  zeilen "nach lauf$n"
done
schema > "$OUT/schema-public-nachher.txt"
if cmp -s "$OUT/schema-public-vorher.txt" "$OUT/schema-public-nachher.txt"; then
  echo "Schema public (pg_dump --schema-only --no-privileges --no-owner) vorher und nachher gleich, $(wc -l < "$OUT/schema-public-vorher.txt") Zeilen, sha256 $(sha256sum < "$OUT/schema-public-vorher.txt" | cut -c1-64)" >> "$OUT/ablauf.txt"
else
  echo "Schema public vorher und nachher VERSCHIEDEN" >> "$OUT/ablauf.txt"
fi
sql -P pager=off > "$OUT/datenbank-auszug.txt" 2>&1 <<'SQL'
\echo '== Version'
SELECT split_part(version(), ',', 1) AS version, postgis_lib_version();
\echo '== Laufprotokoll'
SELECT lauf_id, quelle, tabelle, status, gelesen, neu, geaendert, entfernt, unveraendert, uebernommen, zurueckgehalten, dauer_s FROM pipeline_meta.quellenlauf ORDER BY 1, 2;
\echo '== Kennzahlen je Herausgeber (dashboard_data_de)'
SELECT source, granularity, data_type, count(*) AS zeilen, count(DISTINCT indikator) AS indikatoren, count(DISTINCT kennziffer) AS kennziffern, min(zeitbezug), max(zeitbezug) FROM dashboard_data_de GROUP BY 1, 2, 3 ORDER BY 1;
\echo '== Doppelte Zielschlüssel in dashboard_data_de (muss 0 sein)'
SELECT count(*) FROM (SELECT 1 FROM dashboard_data_de GROUP BY source, granularity, kennziffer, indikator, zeitbezug HAVING count(*) > 1) d;
\echo '== Zeilen der Geometrietabellen'
SELECT 'Gebäude (ALKIS)' AS tabelle, count(*) FROM "Gebäude (ALKIS)" UNION ALL SELECT 'Kommunale Gebiete Brandenburg (InNoWest)', count(*) FROM "Kommunale Gebiete Brandenburg (InNoWest)" UNION ALL SELECT 'Landkreis', count(*) FROM "Landkreis";
\echo '== table_metadata'
SELECT dct_catalog_publisher, dct_type, count(*) FROM table_metadata GROUP BY 1, 2 ORDER BY 1, 2;
\echo '== Katalog: source_granularities (Zeilen je Herausgeber und Raumebene) und offene Aktualisierungen'
SELECT source, granularity, count(*) AS zeilen FROM public.source_granularities GROUP BY 1, 2 ORDER BY 1, 2;
SELECT (SELECT count(*) FROM pipeline_meta.katalog_offen) AS katalog_offen;
\echo '== Eigentümer: View source_granularities und Funktion pipeline_meta.katalog_aktualisieren()'
SELECT (SELECT relowner::regrole FROM pg_class WHERE oid = 'public.source_granularities'::regclass) AS view,
       (SELECT proowner::regrole FROM pg_proc WHERE oid = 'pipeline_meta.katalog_aktualisieren()'::regprocedure) AS funktion,
       (SELECT prosecdef FROM pg_proc WHERE oid = 'pipeline_meta.katalog_aktualisieren()'::regprocedure) AS security_definer;
\echo '== Objekte in public'
SELECT relkind, count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE nspname = 'public' AND relkind IN ('r', 'v', 'm', 'S') GROUP BY 1 ORDER BY 1;
\echo '== Rollen der Pipeline'
SELECT rolname, rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname IN ('pipeline_import', 'mosidi_lesen') ORDER BY 1;
\echo '== Schreibrechte von pipeline_import in public (Tabellen)'
SELECT privilege_type, count(DISTINCT table_name) AS tabellen FROM information_schema.role_table_grants WHERE grantee = 'pipeline_import' AND table_schema = 'public' GROUP BY 1 ORDER BY 1;
SQL
echo fertig >> "$OUT/ablauf.txt"
