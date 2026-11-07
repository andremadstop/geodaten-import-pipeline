#!/bin/bash
# Lauf im Compose-Setup von MOSIDI, Stand nach E52: Wiederholung des Laufs vom 03.11.2026
# (beispielberichte/mosidi-compose/) mit der docker-compose.yml aus MOSIDI-ORG/MOSIDI und dem Overlay
# deploy/mosidi/docker-compose.pipeline.yml, dazu die Katalogaktualisierung aus E46 gegen die View
# source_granularities in der Fassung aus MOSIDI (services/backend/src/db_table_metadata/script.py).
# Kopie aus dem Prüfstand nach E51 (beispielberichte/pruefstand-2026-11-07-e51/mosidi-compose/lauf.sh); geändert
# sind nur dieser Kopf, der Imagename (e52-beleg) und der Projektname (gip-mosidi-e52-<pid>).
#
# Konfiguration (E51): Das Overlay setzt PIPELINE_CONFIG=/app/config/quellen.yaml, seit E51 die
# Lieferkonfiguration mit INKAR im Vollumfang (Stunden je Lauf, bis rund 53 GB; Nachtrag nach den Läufen vom
# 07.11.2026: mindestens 66 GB). Damit der Lauf mit den
# Compose-Läufen bis E50 vergleichbar bleibt (882/413/18, 413 + 413, 62 929), rufen die beiden Läufe hier die
# Prüfkonfiguration auf (--config /app/config/pruefkonfiguration.yaml, der Inhalt von config/quellen.yaml bis
# E50). pipeline-einrichten bleibt beim Standard des Overlays (config/quellen.yaml): Beide Konfigurationen haben
# dieselben Zieltabellen, die Rechte sind also dieselben. Ein Lauf im Vollumfang im Compose von MOSIDI ist damit
# nicht gemessen.
#
# Aufruf: beispielberichte/pruefstand-2026-11-08-e52/mosidi-compose/lauf.sh <MOSIDI-Verzeichnis> <Ausgabeordner>
# Das MOSIDI-Verzeichnis ist ein frischer Klon ohne .env und pg_tileserv.env; beide legt das Skript mit
# zufälligen Passwörtern an und löscht sie am Ende wieder, ebenso Container und Volumes (down -v). Das Image
# geodaten-import-pipeline:e52-beleg muss vorher gebaut sein (beleg.sh baut es).
#
# Abweichungen vom unveränderten Compose stehen nur im Test-Override unten (wie am 03.11.): Volume unter
# /var/lib/postgresql, keine Portfreigabe, eigener Containername; dazu das Image dieses Stands und der
# Berichtsordner im Ausgabeordner statt im Repository.
#
# Ausgaben: ablauf.txt, befund-postgresql18.txt, einrichten.log, lauf<n>.out, lauf<n>.err, datenbank-auszug.txt,
# schema-public-vorher.txt, schema-public-nachher.txt, berichte/.
set -u

# INKAR (E48, E50, E51): www.bbr-server.de schließt per robots.txt automatische Abrufe aus (Disallow: /). Seit E50
# trägt die ausgelieferte Konfiguration für INKAR eine benannte Freigabe (robots_freigabe, Regelbetrieb der TH);
# unsere Läufe rufen den Rechner trotzdem nie ab (docs/betrieb.md): Sie lesen INKAR nur aus der abgelegten Datei
# cache/inkar_2025.zip (PIPELINE_INKAR_DATEI, schreibgeschützt eingehängt), die Vorrang vor der Freigabe hat;
# zusätzlich lösen www.bbr-server.de und www.regionalstatistik.de im Container auf 0.0.0.0 auf (festgehalten in
# ablauf.txt). Fehlt die Datei, startet kein Lauf.
M=$(cd "$1" && pwd); mkdir -p "$2"; OUT=$(cd "$2" && pwd)
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
INKAR=$REPO/cache/inkar_2025.zip
[ -s "$INKAR" ] || { echo "cache/inkar_2025.zip fehlt; INKAR wird nicht abgerufen (robots.txt), Datei ablegen"; exit 1; }
IMG=geodaten-import-pipeline:e52-beleg
# Eigener Projektname mit der PID, damit kein fremdes Compose-Projekt und kein fester Containername von MOSIDI
# getroffen wird.
P=gip-mosidi-e52-$$
# Wegwerf-Verzeichnis nur für die beiden Compose-Ergänzungen.
S=$(mktemp -d)
B=$S/befund.override.yml; O=$S/test.override.yml
# Der Berichtsordner muss für den Benutzer pipeline (UID 1000 im Image) beschreibbar sein.
mkdir -p "$OUT/berichte"; chmod 777 "$OUT/berichte"
# Nie eine vorhandene .env von MOSIDI überschreiben.
if [ -e "$M/.env" ] || [ -e "$M/pg_tileserv.env" ]; then echo ".env oder pg_tileserv.env schon vorhanden"; exit 1; fi
# .env von MOSIDI: Datenbankname und Administrator wie in der MOSIDI-README, alle Passwörter zufällig (Rechte 600);
# pg_tileserv.env leer (pg_tileserv startet nicht mit).
( umask 077; { echo POSTGRES_DB=brandenburg; echo POSTGRES_USER=admin
  for n in POSTGRES_PASSWORD IMPORT_PASSWORD LESE_PASSWORD; do echo "$n=$(openssl rand -hex 24)"; done; } > "$M/.env"
  : > "$M/pg_tileserv.env" )
# Das Overlay sucht den Build-Kontext der Pipeline über PIPELINE_DIR.
export PIPELINE_DIR=$REPO

# Ergänzung für den Befund: das unveränderte brandenburg_db von MOSIDI, nur mit eigenem Containernamen und ohne
# Portfreigabe nach außen. Kommentare stehen hier und nicht im Heredoc.
cat > "$B" <<YML
services:
  brandenburg_db:
    container_name: $P-befund-db
    ports: !reset []
YML
# Test-Override für den eigentlichen Lauf: Volume unter /var/lib/postgresql (sonst startet PostgreSQL 18 nicht,
# Befund), keine Portfreigabe, eigener Containername; Pipeline-Dienste mit dem Image dieses Stands, Berichte im
# Ausgabeordner, INKAR aus der abgelegten Datei, die beiden gesperrten Rechner im Container auf 0.0.0.0.
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
      - $INKAR:/app/inkar/inkar_2025.zip:ro
    environment:
      PIPELINE_INKAR_DATEI: /app/inkar/inkar_2025.zip
    extra_hosts:
      - "www.bbr-server.de:0.0.0.0"
      - "www.regionalstatistik.de:0.0.0.0"
YML
# dcb: nur die Compose-Datei von MOSIDI mit der Befund-Ergänzung (eigenes Projekt "-befund").
dcb() { docker compose -f "$M/docker-compose.yml" -f "$B" -p "$P-befund" "$@"; }
# dcp: Compose von MOSIDI, Overlay der Pipeline aus deploy/mosidi/ und Test-Override.
dcp() { docker compose -f "$M/docker-compose.yml" -f "$REPO/deploy/mosidi/docker-compose.pipeline.yml" -f "$O" -p "$P" "$@"; }
# Beim Beenden (auch nach Fehlern): beide Projekte mit Volumes entfernen, .env und Ergänzungen löschen.
aufraeumen() {
  dcb down -v >/dev/null 2>&1; dcp --profile pipeline down -v >/dev/null 2>&1
  rm -f "$M/.env" "$M/pg_tileserv.env" "$B" "$O"; rmdir "$S"
}
trap aufraeumen EXIT
cd "$M"
# sql: psql als Administrator in brandenburg_db, Abbruch beim ersten Fehler.
sql() { dcp exec -T brandenburg_db psql -X -v ON_ERROR_STOP=1 -U admin -d brandenburg "$@"; }

# Kopf von ablauf.txt: Commit von MOSIDI, Teilbäume des Arbeitsstands (über eine Kopie des Index, der Index
# bleibt unberührt; zusätzlich deploy wegen des Overlays) und die ID des benutzten Images.
{
  echo "# MOSIDI $(git -C "$M" log -1 --format='%H %ci')"
  T=$(cd "$REPO" && cp "$(git rev-parse --git-dir)/index" "$S/index" && GIT_INDEX_FILE="$S/index" git add -A pipeline config sql tests Dockerfile deploy \
      && GIT_INDEX_FILE="$S/index" git write-tree); rm -f "$S/index"
  for d in pipeline config sql tests Dockerfile deploy; do echo "# $d $(cd "$REPO" && git rev-parse "$T:$d")"; done
  echo "# Image $IMG $(docker image inspect -f '{{.Id}}' "$IMG")"
} > "$OUT/ablauf.txt"

# 1. Befund: das unveränderte brandenburg_db (nur ohne Portfreigabe und mit eigenem Containernamen) auf frischem
#    Volume; nach 30 s Status und Zahl der Neustarts festhalten, dazu die erste Fehlermeldung von PostgreSQL 18.
dcb up -d brandenburg_db >/dev/null 2>&1
for i in $(seq 1 30); do sleep 1; done
C=$P-befund-db
echo "befund: Image $(docker inspect -f '{{.Config.Image}}' "$C"), Status $(docker inspect -f '{{.State.Status}}' "$C"), Neustarts nach 30 s $(docker inspect -f '{{.RestartCount}}' "$C"), $(docker run --rm --entrypoint postgres "$(docker inspect -f '{{.Image}}' "$C")" --version)" >> "$OUT/ablauf.txt"
docker logs "$C" 2>&1 | grep -m1 -A24 '^Error: in 18+' > "$OUT/befund-postgresql18.txt"
dcb down -v >/dev/null 2>&1

# 2. Mit Volume unter /var/lib/postgresql: Datenbank starten und auf das Ende der Ersteinrichtung warten.
dcp up -d brandenburg_db >/dev/null 2>&1 || { echo "Start fehlgeschlagen"; exit 1; }
for i in $(seq 1 120); do
  docker logs "$P-db" 2>&1 | grep -q 'PostgreSQL init process complete' && sql -tAc 'SELECT 1' >/dev/null 2>&1 && break; sleep 1
done
sql -tAc "SELECT version()" >> "$OUT/ablauf.txt"
sql -tAc "SELECT postgis_lib_version()" | sed 's/^/PostGIS /' >> "$OUT/ablauf.txt"
# Bestandsschema von MOSIDI aus sql/mosidi/001_bestand.sql (unverändert), danach als Administrator die
# Materialized View source_granularities mit ihren Indizes, wörtlich aus dem Backend von MOSIDI ausgeschnitten
# (Zeilennummern und sha256 des Ausschnitts in ablauf.txt).
sql -q < "$REPO/sql/mosidi/001_bestand.sql" > "$S/bestand.log" 2>&1; echo "Bestandsschema sql/mosidi/001_bestand.sql rc=$?" >> "$OUT/ablauf.txt"
V=services/backend/src/db_table_metadata/script.py
sed -n '/^DROP MATERIALIZED VIEW IF EXISTS source_granularities;/,/ON source_granularities(indikator);/p' "$M/$V" > "$S/view.sql"
echo "View source_granularities aus MOSIDI $V, Zeilen $(grep -n '^DROP MATERIALIZED VIEW IF EXISTS source_granularities;' "$M/$V" | cut -d: -f1) bis $(grep -n 'ON source_granularities(indikator);' "$M/$V" | cut -d: -f1), sha256 $(sha256sum < "$S/view.sql" | cut -c1-64)" >> "$OUT/ablauf.txt"
sql -q < "$S/view.sql" >> "$S/bestand.log" 2>&1; echo "View angelegt (als admin) rc=$?" >> "$OUT/ablauf.txt"
rm -f "$S/bestand.log" "$S/view.sql"
# Schema public vor einrichten und nach dem letzten Lauf als pg_dump ohne Rechte und Eigentümer; die Zeilen
# \restrict/\unrestrict (Zufallsschlüssel je Aufruf) fallen weg, damit gleiche Schemata gleich verglichen werden.
schema() { dcp exec -T brandenburg_db pg_dump -U admin -d brandenburg --schema-only --schema=public --no-privileges --no-owner \
             | grep -v -E '^\\(un)?restrict ' ; }
schema > "$OUT/schema-public-vorher.txt"
# zeilen: Zahl der Zeilen der View source_granularities nach ablauf.txt (Katalogaktualisierung, E46).
zeilen() { echo "$1: source_granularities $(sql -tAc 'SELECT count(*) FROM public.source_granularities') Zeilen" >> "$OUT/ablauf.txt"; }
zeilen "vor einrichten"
dcp --profile pipeline run --rm pipeline-einrichten > "$OUT/einrichten.log" 2>&1; echo "einrichten rc=$?" >> "$OUT/ablauf.txt"
# Namensauflösung im Container (E50): im Dienst pipeline mit denselben extra_hosts wie die Läufe, ohne die
# Pipeline zu starten; Beleg, dass ein Abruf der beiden gesperrten Rechner keine Verbindung erreichen könnte.
for h in www.bbr-server.de www.regionalstatistik.de; do
  echo "Namensauflösung im Container: $h -> $(dcp --profile pipeline run --rm --no-deps --entrypoint getent pipeline ahostsv4 "$h" 2>/dev/null | awk 'NR==1{print $1}')" >> "$OUT/ablauf.txt"
done
# Konfiguration der beiden Läufe (E51, Kopf): die Prüfkonfiguration, nicht der Standard des Overlays.
KONF=/app/config/pruefkonfiguration.yaml
echo "Konfiguration der Läufe: $KONF (pipeline-einrichten: Standard des Overlays)" >> "$OUT/ablauf.txt"
# Zwei Läufe mit --alle: der erste lädt alles neu, der zweite muss alles unverändert finden.
for n in 1 2; do
  # Rechnerlast (E51): über 8 in Schritten von 30 s warten, höchstens 20 min, dann trotzdem starten; die
  # Wartezeit steht in ablauf.txt.
  w=0
  while [ "$(awk '{print ($1 > 8)}' /proc/loadavg)" = 1 ] && [ $w -lt 1200 ]; do sleep 30; w=$((w+30)); done
  echo "lauf$n: Wartezeit wegen Rechnerlast über 8: $w s" >> "$OUT/ablauf.txt"
  echo "lauf$n: Rechnerlast davor (1/5/15 min): $(cut -d' ' -f1-3 /proc/loadavg)" >> "$OUT/ablauf.txt"
  t0=$(date +%s.%N)
  dcp --profile pipeline run --rm pipeline --config "$KONF" --alle > "$OUT/lauf$n.out" 2> "$OUT/lauf$n.err"
  rc=$?; t1=$(date +%s.%N)
  echo "lauf$n: Argumente '--config $KONF --alle', Rückgabe $rc, Wandzeit $(echo "$t1 - $t0" | bc) s (einschließlich Containerstart), Rechnerlast danach (1/5/15 min): $(cut -d' ' -f1-3 /proc/loadavg), $(nproc) Kerne" >> "$OUT/ablauf.txt"
  zeilen "nach lauf$n"
done
# Das Bestandsschema public muss vorher und nachher gleich sein (Antworten 27, 29); die Rechte sind im Vergleich
# ausgenommen, sie vergibt einrichten wie vorgesehen.
schema > "$OUT/schema-public-nachher.txt"
if cmp -s "$OUT/schema-public-vorher.txt" "$OUT/schema-public-nachher.txt"; then
  echo "Schema public (pg_dump --schema-only --no-privileges --no-owner) vorher und nachher gleich, $(wc -l < "$OUT/schema-public-vorher.txt") Zeilen, sha256 $(sha256sum < "$OUT/schema-public-vorher.txt" | cut -c1-64)" >> "$OUT/ablauf.txt"
else
  echo "Schema public vorher und nachher VERSCHIEDEN" >> "$OUT/ablauf.txt"
fi
# Datenbankauszug nach Lauf 2: Laufprotokoll, Zählungen, doppelte Zielschlüssel, Geometrietabellen,
# table_metadata, Katalog, Eigentümer von View und Funktion, Objekte in public, Rollen und Tabellenrechte.
# Die Abfragen stehen im Heredoc ohne Kommentare; die \echo-Zeilen sind die Überschriften im Auszug.
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
