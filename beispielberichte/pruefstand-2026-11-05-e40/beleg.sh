#!/bin/bash
# Belegläufe gegen die echten Dienste in einem Wegwerf-Compose-Projekt (so am 05.11.2026 ausgeführt; allgemein
# gefasst sind nur die Pfade und die Zeile mit dem Git-Stand). Aufruf: beispielberichte/pruefstand-2026-11-05-e40/beleg.sh quellen <Ausgabeordner> --alle -- --alle -- .
# $1 = quellen | deutschland, $2 = Ausgabeordner,
# Rest: Läufe als Liste von Argumentgruppen, getrennt durch "--", z. B. "--alle -- --alle -- ."
# Abgelöst, nicht mehr ausführen (Nachprüfung zu E50, 06.11.2026): Das Skript baut den aktuellen Stand und
# hängt das aktuelle config/ ein, ohne PIPELINE_INKAR_DATEI. Seit E50 trägt die ausgelieferte Konfiguration
# die Freigabe für den INKAR-Abruf per URL; ein erneuter Start riefe www.bbr-server.de ab (HEAD-Suche und
# rund 430 MB), gegen unsere Regel, diesen Rechner nie selbst abzurufen. Der Rest darunter ist unverändert
# der Stand, mit dem die Belege entstanden sind. Belegläufe am aktuellen Stand:
# beispielberichte/pruefstand-2026-11-07-e51/ (INKAR aus der abgelegten Datei; bis E51 pruefstand-2026-11-06-e50/).
echo "Abgelöst (Nachprüfung zu E50): nicht ausführen, INKAR würde per URL abgerufen" >&2; exit 1
set -u
CFG=$1; OUT=$2; shift 2
REPO=$(cd "$(dirname "$0")/../.." && pwd)
S=$(mktemp -d)   # nur für die Wegwerf-Zugangsdaten (Rechte 600) und die Compose-Ergänzung
mkdir -p "$OUT/berichte"; chmod 777 "$OUT/berichte"
P=gip-beleg-$CFG-$$; E=$S/$P.env; PORT=$((55900 + $$ % 90)); O=$S/$P.override.yml
( umask 077; : > "$E"; for n in POSTGRES_PASSWORD IMPORT_PASSWORD LESE_PASSWORD; do echo "$n=$(openssl rand -hex 24)" >> "$E"; done )
cat > "$O" <<YML
services:
  einrichten:
    image: geodaten-import-pipeline:e40-beleg
    command: ["--config", "/app/config/$CFG.yaml", "--haerten"]
  pipeline:
    image: geodaten-import-pipeline:e40-beleg
    volumes: !override
      - $REPO/config:/app/config:ro
      - $REPO/beispiele:/app/beispiele:ro
      - $OUT/berichte:/app/berichte
      - $REPO/cache:/app/cache
YML
dc() { docker compose -f "$REPO/docker-compose.yml" -f "$O" -p "$P" --env-file "$E" "$@"; }
aufraeumen() { dc --profile einrichten down -v >/dev/null 2>&1; rm -f "$E" "$O"; rmdir "$S"; }
trap aufraeumen EXIT
cd "$REPO"
unset POSTGIS_IMAGE PGDATA_MOUNT
# Teilbäume des Arbeitsstands, aus dem das Image gebaut wird (über einen eigenen Index, der Index bleibt unberührt).
# Am 05.11.2026 stand hier `git write-tree`; das nannte den Index vor dem Stagen und wurde im Beleg ersetzt.
cp "$(git rev-parse --git-dir)/index" "$S/index"; GIT_INDEX_FILE="$S/index" git add -A pipeline config sql tests Dockerfile
T=$(GIT_INDEX_FILE="$S/index" git write-tree); rm -f "$S/index"
for d in pipeline config sql tests Dockerfile; do echo "# $d $(git rev-parse "$T:$d")"; done > "$OUT/ablauf.txt"
dc build pipeline >"$OUT/build.log" 2>&1 || { echo "Build fehlgeschlagen"; exit 1; }
PG_PORT=$PORT dc up -d --wait db >/dev/null 2>&1 || { echo "Start fehlgeschlagen"; exit 1; }
dc exec -T db psql -U admin -d geodaten -tAc "SELECT version()" >> "$OUT/ablauf.txt"
dc exec -T db psql -U admin -d geodaten -tAc "SELECT postgis_full_version()" >> "$OUT/ablauf.txt"
dc --profile einrichten run --rm einrichten > "$OUT/einrichten.log" 2>&1; echo "einrichten rc=$?" >> "$OUT/ablauf.txt"
n=0; args=()
lauf() {
  n=$((n+1)); C=$P-lauf$n; RAW="$OUT/speicher-lauf$n.txt"
  echo "# docker stats --no-stream je Sekunde, Container $C; Spalten: Unix-Zeit;Name;MemUsage;MemPerc;CPUPerc" > "$RAW"
  ( while ! docker inspect "$C" >/dev/null 2>&1; do sleep 0.2; done
    while docker inspect -f '{{.State.Running}}' "$C" 2>/dev/null | grep -q true; do
      z=$(docker stats --no-stream --format '{{.Name}};{{.MemUsage}};{{.MemPerc}};{{.CPUPerc}}' "$C" 2>/dev/null) && [ -n "$z" ] && echo "$(date +%s.%N);$z" >> "$RAW"
      sleep 1
    done ) &
  SP=$!
  t0=$(date +%s.%N)
  dc run --rm --name "$C" --entrypoint sh pipeline -c \
    'python -m pipeline.laden "$@"; rc=$?; echo "cgroup memory.peak (Bytes): $(cat /sys/fs/cgroup/memory.peak 2>/dev/null || echo nicht lesbar)"; exit $rc' \
    sh --config /app/config/$CFG.yaml "$@" > "$OUT/lauf$n.out" 2> "$OUT/lauf$n.err"
  rc=$?; t1=$(date +%s.%N)
  wait $SP 2>/dev/null
  echo "lauf$n: Argumente '$*', Rückgabe $rc, Wandzeit $(echo "$t1 - $t0" | bc) s (einschließlich Containerstart)" >> "$OUT/ablauf.txt"
}
for a in "$@"; do
  if [ "$a" = "--" ]; then lauf "${args[@]}"; args=(); elif [ "$a" != "." ]; then args+=("$a"); fi
done
lauf "${args[@]}"
dc exec -T db psql -U admin -d geodaten -P pager=off > "$OUT/datenbank-auszug.txt" 2>&1 <<'SQL'
\echo '== Version'
SELECT split_part(version(), ',', 1);
\echo '== Kennzahlen je Herausgeber (dashboard_data_de)'
SELECT source, granularity, data_type, count(*) AS zeilen, count(DISTINCT indikator) AS indikatoren,
       count(DISTINCT kennziffer) AS kennziffern, min(zeitbezug), max(zeitbezug) FROM dashboard_data_de GROUP BY 1, 2, 3 ORDER BY 1;
\echo '== Indikatornamen INKAR (E40: Langtext, außer ZOM mit Bereich)'
SELECT indikator, count(*) AS zeilen FROM dashboard_data_de WHERE source = 'INKAR' GROUP BY 1 ORDER BY 1;
\echo '== Doppelte Zielschlüssel in dashboard_data_de (muss 0 sein)'
SELECT count(*) FROM (SELECT 1 FROM dashboard_data_de GROUP BY source, granularity, kennziffer, indikator, zeitbezug HAVING count(*) > 1) d;
\echo '== Register: Zeilen und Quellschlüssel je Quelle'
SELECT quelle, tabelle, count(*) AS zeilen, count(quellschluessel) AS mit_quellschluessel, count(DISTINCT quellschluessel) AS verschiedene FROM pipeline_meta.bestand GROUP BY 1, 2 ORDER BY 1;
\echo '== Beispiele Register INKAR (Quellschlüssel -> Zielschlüssel), nur Schlüssel, keine Werte'
SELECT quellschluessel, schluessel FROM pipeline_meta.bestand WHERE quelle LIKE 'inkar%' AND schluessel ->> 1 LIKE 'Einwohnerdichte%' ORDER BY 1 LIMIT 4;
\echo '== table_metadata'
SELECT dct_catalog_publisher, dct_type, count(*) FROM table_metadata GROUP BY 1, 2 ORDER BY 1, 2;
\echo '== Laufprotokoll'
SELECT lauf_id, quelle, status, gelesen, neu, geaendert, entfernt, unveraendert, uebernommen, zurueckgehalten, dauer_s FROM pipeline_meta.quellenlauf ORDER BY 1, 2;
\echo '== Größen'
SELECT pg_size_pretty(pg_database_size(current_database())) AS datenbank;
SELECT relname, pg_size_pretty(pg_total_relation_size(c.oid)) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE relkind = 'r' AND (nspname = 'pipeline_meta' OR relname IN ('dashboard_data_de', 'Kommunale Gebiete Deutschland', 'Kommunale Gebiete Brandenburg (InNoWest)', 'Gebäude (ALKIS)', 'table_metadata'))
 ORDER BY pg_total_relation_size(c.oid) DESC;
SQL
echo fertig >> "$OUT/ablauf.txt"
