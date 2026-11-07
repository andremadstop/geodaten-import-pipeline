#!/bin/bash
# Belegläufe gegen die echten Dienste in einem Wegwerf-Compose-Projekt, Stand nach E52 (08.11.2026). Kopie aus
# dem Prüfstand nach E51 (beispielberichte/pruefstand-2026-11-07-e51/beleg.sh); geändert sind nur dieser Kopf und
# der Imagename (e52-beleg). Weiterhin: Warten auf eine niedrige Rechnerlast vor jedem Lauf, Ausfuhr der INKAR-Zeilen
# nach Lauf 1 für den Wertabgleich (WERTE_EXPORT=1, unten; Befund W4).
#
# Aufruf (vom Repository aus, Ausgabeordner außerhalb des Repositorys):
#   WERTE_EXPORT=1 beispielberichte/pruefstand-2026-11-08-e52/beleg.sh quellen <Ausgabeordner> --alle -- --alle -- .
#   beispielberichte/pruefstand-2026-11-08-e52/beleg.sh pruefkonfiguration <Ausgabeordner> --alle
#   beispielberichte/pruefstand-2026-11-08-e52/beleg.sh deutschland <Ausgabeordner> --alle -- --alle
# $1 = quellen | pruefkonfiguration | deutschland (Name der Konfiguration unter config/) oder der Pfad einer
# .yaml-Datei (eigene Prüfkonfiguration, nur lesbar eingehängt unter /app/pruefkonfig/), $2 = Ausgabeordner,
# Rest: die Läufe als Liste von Argumentgruppen für pipeline.laden, getrennt durch "--"; "." steht für einen
# Lauf ohne Argumente (nur fällige Quellen).
#
# Seit E51 ist `quellen` die Lieferkonfiguration mit INKAR im Vollumfang (ganz Deutschland, alle Indikatoren
# und Jahre; Stunden je Lauf, Datenbank bis rund 53 GB während des Laufs; Nachtrag nach den Läufen vom 07.11.2026:
# mindestens 66 GB, README dieses Prüfstands). Die Brandenburg-Läufe der
# Prüfstände bis E50 entsprechen `pruefkonfiguration` (config/pruefkonfiguration.yaml, der Inhalt von
# config/quellen.yaml bis E50).
#
# Ausgaben im Ausgabeordner: lauf<n>.out (stdout des Containers), lauf<n>.err (stderr: Protokoll der Pipeline
# und Meldungen von Compose), speicher-lauf<n>.txt (Proben von docker stats), build.log (Bau des Images),
# einrichten.log (Rollen und Rechte), ablauf.txt (Teilbäume, Versionen, Namensauflösung im Container, Rückgabe,
# Wandzeit, Rechnerlast, Wartezeit), datenbank-auszug.txt (Zählungen nach dem letzten Lauf), berichte/
# (Laufberichte, Quellenverzeichnis, Karten); mit WERTE_EXPORT=1 zusätzlich werte-nach-lauf1.csv.gz (INKAR-Zeilen
# der Zieltabelle nach Lauf 1, echte Quelldaten: bleibt außerhalb des Repositorys, Antwort 69).
#
# Was das Skript nicht tut: Es ändert nichts am Repository (der Index bleibt unberührt, die Teilbäume kommen aus
# einer Kopie des Index), es legt keine Zugangsdaten im Repository ab, und es lässt keine Container oder Volumes
# zurück (down -v beim Beenden, auch nach einem Fehler).
set -u

# INKAR (E48, E50, E51): www.bbr-server.de schließt per robots.txt automatische Abrufe aus (Disallow: /). Seit E50
# trägt die ausgelieferte Konfiguration für INKAR eine benannte Freigabe (robots_freigabe, Regelbetrieb der TH);
# unsere Läufe rufen den Rechner trotzdem nie ab (docs/betrieb.md): Sie lesen INKAR nur aus der abgelegten Datei
# cache/inkar_2025.zip (PIPELINE_INKAR_DATEI, schreibgeschützt eingehängt), die Vorrang vor der Freigabe hat;
# der Bericht vermerkt dann „robots_freigabe konfiguriert, nicht genutzt“. Zusätzlich lösen www.bbr-server.de
# und www.regionalstatistik.de im Container auf 0.0.0.0 auf, ein Abruf scheiterte also schon an der Verbindung;
# das Skript hält die Auflösung im Container in ablauf.txt fest. Fehlt die Datei, startet kein Lauf.
CFG=$1; OUT=$2; shift 2
REPO=$(cd "$(dirname "$0")/../.." && pwd)
INKAR=$REPO/cache/inkar_2025.zip
[ -s "$INKAR" ] || { echo "cache/inkar_2025.zip fehlt; INKAR wird nicht abgerufen (robots.txt), Datei ablegen"; exit 1; }
# Konfiguration: ein Name unter config/ (wie bisher) oder eine eigene Prüfkonfiguration als .yaml-Datei. Die
# eigene Datei wird nur lesbar unter /app/pruefkonfig/ eingehängt und nicht nach config/ kopiert, damit der
# Teilbaum config (Teil des Abgabestands) unverändert bleibt. NAME steht im Projektnamen und in ablauf.txt.
case $CFG in
  *.yaml) [ -s "$CFG" ] || { echo "Prüfkonfiguration $CFG fehlt"; exit 1; }
          KONF=$(cd "$(dirname "$CFG")" && pwd)/$(basename "$CFG"); NAME=$(basename "$CFG" .yaml)
          KPFAD=/app/pruefkonfig/$NAME.yaml; KMOUNT="      - $KONF:$KPFAD:ro" ;;
  *)      NAME=$CFG; KPFAD=/app/config/$CFG.yaml; KMOUNT="" ;;
esac

# Eigenes Wegwerf-Verzeichnis nur für die Zugangsdaten (Rechte 600) und die Compose-Ergänzung.
S=$(mktemp -d)
# Der Berichtsordner muss für den Benutzer pipeline (UID 1000 im Image) beschreibbar sein.
mkdir -p "$OUT/berichte"; chmod 777 "$OUT/berichte"
# Projektname mit der PID, damit kein fremdes Compose-Projekt getroffen wird; Port nur für den Start der
# Datenbank (die Pipeline erreicht sie im Compose-Netz über den Dienstnamen).
P=gip-beleg-$NAME-$$; E=$S/$P.env; PORT=$((55900 + $$ % 90)); O=$S/$P.override.yml
# Zufällige Passwörter je Lauf, nur in der Datei mit Rechten 600; sie werden nirgends ausgegeben.
( umask 077; : > "$E"; for n in POSTGRES_PASSWORD IMPORT_PASSWORD LESE_PASSWORD; do echo "$n=$(openssl rand -hex 24)" >> "$E"; done )
# Einhängepunkt der eigenen Prüfkonfiguration auch für einrichten (es liest die Zieltabellen aus der
# Konfiguration); dort werden die Volumes der Compose-Datei ergänzt, nicht ersetzt. Ohne eigene Datei bleibt
# der Block leer, weil eine leere Liste unter volumes für Compose ungültig ist.
EVOL=""; [ -n "$KMOUNT" ] && EVOL=$(printf '    volumes:\n%s' "$KMOUNT")

# Compose-Ergänzung zur docker-compose.yml des Repositorys:
# - einrichten: Image dieses Stands, die gewählte Konfiguration, --haerten (wie im Betrieb vorgesehen);
# - pipeline: Konfiguration und Beispiele nur lesbar, Berichte in den Ausgabeordner, cache/ des Repositorys als
#   Zwischenspeicher (nicht in git, .gitignore), die INKAR-Datei schreibgeschützt und per PIPELINE_INKAR_DATEI,
#   gegebenenfalls die eigene Prüfkonfiguration nur lesbar;
# - extra_hosts sperrt die beiden Rechner mit Disallow: / im Container.
# Im Heredoc selbst stehen keine Kommentare, damit die erzeugte Datei genau das enthält, was Compose liest.
cat > "$O" <<YML
services:
  einrichten:
    image: geodaten-import-pipeline:e52-beleg
    command: ["--config", "$KPFAD", "--haerten"]
$EVOL
  pipeline:
    image: geodaten-import-pipeline:e52-beleg
    volumes: !override
      - $REPO/config:/app/config:ro
      - $REPO/beispiele:/app/beispiele:ro
      - $OUT/berichte:/app/berichte
      - $REPO/cache:/app/cache
      - $INKAR:/app/inkar/inkar_2025.zip:ro
$KMOUNT
    environment:
      PIPELINE_INKAR_DATEI: /app/inkar/inkar_2025.zip
    extra_hosts:
      - "www.bbr-server.de:0.0.0.0"
      - "www.regionalstatistik.de:0.0.0.0"
YML

# dc: docker compose mit der Compose-Datei des Repositorys, der Ergänzung, eigenem Projektnamen und den
# Wegwerf-Zugangsdaten.
dc() { docker compose -f "$REPO/docker-compose.yml" -f "$O" -p "$P" --env-file "$E" "$@"; }
# Beim Beenden (auch nach Fehlern): Container und Volumes entfernen, Zugangsdaten und Ergänzung löschen.
aufraeumen() { dc --profile einrichten down -v >/dev/null 2>&1; rm -f "$E" "$O"; rmdir "$S"; }
trap aufraeumen EXIT
cd "$REPO"
# Vorgaben aus der Umgebung nicht übernehmen: Die Datenbank ist das festgeschriebene postgis/postgis:16-3.6.
unset POSTGIS_IMAGE PGDATA_MOUNT

# Teilbäume des Arbeitsstands, aus dem das Image gebaut wird: über eine Kopie des Index, der eigentliche Index
# bleibt unberührt. Sie stehen als Kopfzeilen in ablauf.txt und sind mit git write-tree vergleichbar.
# Seit E51 auch deploy (systemd-Units mit TimeoutStartSec, Overlay für MOSIDI), weil der Code-Stand dort mitzählt.
cp "$(git rev-parse --git-dir)/index" "$S/index"; GIT_INDEX_FILE="$S/index" git add -A pipeline config sql tests Dockerfile deploy
T=$(GIT_INDEX_FILE="$S/index" git write-tree); rm -f "$S/index"
for d in pipeline config sql tests Dockerfile deploy; do echo "# $d $(git rev-parse "$T:$d")"; done > "$OUT/ablauf.txt"

# Image bauen (Basisimage per Digest festgeschrieben, Pakete aus requirements.txt mit Prüfsummen), Datenbank
# starten und auf ihre Gesundheitsprüfung warten, Versionen festhalten, Rollen einrichten.
dc build pipeline >"$OUT/build.log" 2>&1 || { echo "Build fehlgeschlagen"; exit 1; }
PG_PORT=$PORT dc up -d --wait db >/dev/null 2>&1 || { echo "Start fehlgeschlagen"; exit 1; }
dc exec -T db psql -U admin -d geodaten -tAc "SELECT version()" >> "$OUT/ablauf.txt"
dc exec -T db psql -U admin -d geodaten -tAc "SELECT postgis_full_version()" >> "$OUT/ablauf.txt"
dc --profile einrichten run --rm einrichten > "$OUT/einrichten.log" 2>&1; echo "einrichten rc=$?" >> "$OUT/ablauf.txt"
# Konfiguration des Laufs; bei einer eigenen Prüfkonfiguration mit sha256, damit sich die beigelegte Datei
# dem Lauf zuordnen lässt (sie liegt außerhalb der Teilbäume oben).
echo "Konfiguration $KPFAD${KMOUNT:+, sha256 $(sha256sum < "$KONF" | cut -c1-64)}" >> "$OUT/ablauf.txt"
# Namensauflösung im Container (E50): Beleg, dass ein Abruf der beiden gesperrten Rechner nicht einmal eine
# Verbindung erreichen könnte. Gefragt wird im selben Dienst wie die Läufe (gleiche extra_hosts), ohne die
# Pipeline zu starten; getent liest dieselbe Auflösung wie Python (nsswitch, /etc/hosts zuerst).
for h in www.bbr-server.de www.regionalstatistik.de; do
  echo "Namensauflösung im Container: $h -> $(dc run --rm --no-deps --entrypoint getent pipeline ahostsv4 "$h" 2>/dev/null | awk 'NR==1{print $1}')" >> "$OUT/ablauf.txt"
done

# Ein Lauf: Container mit festem Namen starten, daneben den Speicher mit docker stats proben (etwa alle 2 s),
# Rechnerlast davor und danach, Rückgabe und Wandzeit (einschließlich Containerstart) nach ablauf.txt.
# Im Container gibt eine kleine Hülle nach pipeline.laden memory.peak und memory.stat der cgroup aus (der
# Höchststand des Kernels einschließlich Seitencache, für die Grenze von 1 GiB maßgeblich) und reicht die
# Rückgabe von pipeline.laden durch.
n=0; args=()
lauf() {
  n=$((n+1)); C=$P-lauf$n; RAW="$OUT/speicher-lauf$n.txt"
  echo "# docker stats --no-stream etwa alle 2 s (1 s Pause plus Dauer des Aufrufs), Container $C; Spalten: Unix-Zeit;Name;MemUsage;MemPerc;CPUPerc" > "$RAW"
  # Probenschleife im Hintergrund: wartet, bis es den Container gibt, und probt, solange er läuft.
  ( while ! docker inspect "$C" >/dev/null 2>&1; do sleep 0.2; done
    while docker inspect -f '{{.State.Running}}' "$C" 2>/dev/null | grep -q true; do
      z=$(docker stats --no-stream --format '{{.Name}};{{.MemUsage}};{{.MemPerc}};{{.CPUPerc}}' "$C" 2>/dev/null) && [ -n "$z" ] && echo "$(date +%s.%N);$z" >> "$RAW"
      sleep 1
    done ) &
  SP=$!
  # Rechnerlast (E51): Liegt die 1-Minuten-Last über 8, wartet der Lauf in Schritten von 30 s, bis sie darunter
  # fällt, höchstens 20 min; danach startet er trotzdem. Die Wartezeit steht in ablauf.txt, damit ein Lauf auf
  # einem belasteten Rechner erkennbar bleibt. Hier im Skript statt nur vor dem Aufruf, weil die Läufe 2 und 3
  # ohne Pause auf Lauf 1 folgen.
  w=0
  while [ "$(awk '{print ($1 > 8)}' /proc/loadavg)" = 1 ] && [ $w -lt 1200 ]; do sleep 30; w=$((w+30)); done
  echo "lauf$((n)): Wartezeit wegen Rechnerlast über 8: $w s" >> "$OUT/ablauf.txt"
  echo "lauf$((n)): Rechnerlast davor (1/5/15 min): $(cut -d' ' -f1-3 /proc/loadavg)" >> "$OUT/ablauf.txt"
  t0=$(date +%s.%N)
  dc run --rm --name "$C" --entrypoint sh pipeline -c \
    'python -m pipeline.laden "$@"; rc=$?; echo "cgroup memory.peak (Bytes): $(cat /sys/fs/cgroup/memory.peak 2>/dev/null || echo nicht lesbar)"; echo "cgroup memory.stat am Ende (Bytes): $(grep -E "^(anon|file|file_mapped|shmem) " /sys/fs/cgroup/memory.stat 2>/dev/null | tr "\n" " ")"; exit $rc' \
    sh --config "$KPFAD" "$@" > "$OUT/lauf$n.out" 2> "$OUT/lauf$n.err"
  rc=$?; t1=$(date +%s.%N)
  wait $SP 2>/dev/null
  echo "lauf$n: Argumente '$*', Rückgabe $rc, Wandzeit $(echo "$t1 - $t0" | bc) s (einschließlich Containerstart), Rechnerlast danach (1/5/15 min): $(cut -d' ' -f1-3 /proc/loadavg), $(nproc) Kerne" >> "$OUT/ablauf.txt"
  # Wertabgleich (E51, Befund W4): Mit WERTE_EXPORT=1 werden nach Lauf 1, bevor Lauf 2 startet, alle
  # INKAR-Zeilen der Zieltabelle als CSV ausgeführt (Kennziffer, Indikator, Zeitbezug, Wert als Text, damit
  # NUMERIC ohne Umweg über Gleitkomma ankommt). Ein unabhängiges Skript (wertabgleich.py in diesem Prüfstand)
  # vergleicht sie danach Zeile für Zeile mit der INKAR-Datei. Die Datei enthält echte Quelldaten; sie liegt nur
  # im Ausgabeordner, ablauf.txt nennt Zeilenzahl und sha256. FORMAT csv, weil Indikatornamen Kommas enthalten.
  if [ "$n" = 1 ] && [ "${WERTE_EXPORT:-}" = 1 ]; then
    dc exec -T db psql -X -v ON_ERROR_STOP=1 -U admin -d geodaten -c "\copy (SELECT kennziffer, indikator, zeitbezug, wert::text FROM dashboard_data_de WHERE source = 'INKAR' AND granularity = 'Gemeindeebene') TO STDOUT (FORMAT csv)" \
      | gzip -1 > "$OUT/werte-nach-lauf1.csv.gz"
    xrc=${PIPESTATUS[0]}
    echo "lauf1: Ausfuhr für den Wertabgleich (Rückgabe psql $xrc): $(zcat "$OUT/werte-nach-lauf1.csv.gz" | wc -l) Zeilen, sha256 der entpackten CSV $(zcat "$OUT/werte-nach-lauf1.csv.gz" | sha256sum | cut -c1-64)" >> "$OUT/ablauf.txt"
  fi
}
# Argumentgruppen zerlegen: "--" beendet eine Gruppe, "." ist ein Lauf ohne Argumente.
for a in "$@"; do
  if [ "$a" = "--" ]; then lauf "${args[@]}"; args=(); elif [ "$a" != "." ]; then args+=("$a"); fi
done
lauf "${args[@]}"

# Datenbankauszug nach dem letzten Lauf: Zählungen, doppelte Zielschlüssel, Register nur mit Schlüsseln (keine
# Werte), table_metadata, Laufprotokoll und Größen. Die Abfragen stehen im Heredoc ohne Kommentare; die
# \echo-Zeilen sind die Überschriften im Auszug.
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
