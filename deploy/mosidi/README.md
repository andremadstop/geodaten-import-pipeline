# Pipeline im Compose-Setup von MOSIDI

Die TH will die Pipeline als zusätzlichen Dienst im bestehenden Compose von MOSIDI (Antworten 36 und
53): gleiche Datenbank `brandenburg_db`, Bestandstabellen unverändert, Steuerung und Protokoll im
eigenen Schema `pipeline_meta`. Dafür ist `docker-compose.pipeline.yml` da; MOSIDIs eigene
`docker-compose.yml` bleibt unverändert.

## Einrichten

Im MOSIDI-Verzeichnis, in dessen `.env` zusätzlich `IMPORT_PASSWORD` und `LESE_PASSWORD` stehen:

    export PIPELINE_DIR=/opt/geodaten-import-pipeline
    alias dcp='docker compose -f docker-compose.yml -f "$PIPELINE_DIR/deploy/mosidi/docker-compose.pipeline.yml"'
    dcp run --rm pipeline-einrichten        # pipeline_meta, Rollen, Rechte nach config/quellen.yaml
    dcp run --rm pipeline --probelauf       # alles lesen und vergleichen, keine dauerhaften Datenänderungen (Prüfbericht, Cache)
    dcp run --rm pipeline                   # Lauf; Quellen laden nach ihrem Rhythmus

Die ausgelieferte `config/quellen.yaml` lädt INKAR seit E51 im Vollumfang wie der Import der TH (alle
Indikatoren aller Gemeinden Deutschlands, Antwort 33; abweichend ist die Form der Kennziffer, Abschnitt
„Verhältnis zum INKAR-Import der TH“). Messstand 07.11.2026 (Prüfstand `beispielberichte/pruefstand-2026-11-07-e51/quellen/`,
INKAR aus der abgelegten Datei, parallel genutzter Entwicklungsrechner): Erstlauf 129,7 min, unveränderter Folgelauf
159,7 min (INKAR allein 129,4 und 158,2 min), Datenbank danach 24 GB, während der Läufe beobachteter Spitzenbedarf
mindestens 66 GB (Proben alle 5 min); vorher den Platz auf dem Rechner von `brandenburg_db` prüfen und zusätzliche
Speicherreserve darüber vorsehen. Auch der
`--probelauf` oben läuft im Vollumfang. Für eine schnelle erste Prüfung (rund 2,5 min, INKAR mit fünf Kürzeln in
Brandenburg) die Prüfkonfiguration als Probelauf:
`dcp run --rm pipeline --config /app/config/pruefkonfiguration.yaml --probelauf --alle`. Nur als Probelauf: Sie trägt
dieselben Quellnamen wie die Lieferkonfiguration, ein regulärer Lauf gegen `brandenburg_db` würde INKAR auf fünf
Kürzel setzen und den Rhythmus der Quelle neu starten oder, hält `brandenburg_db` INKAR schon im Vollumfang, am
Rückgang-Schutz anhalten (mit Meldungsentwurf an den Anbieter).

`pipeline-einrichten` meldet sich als Administrator aus der MOSIDI-`.env` an und entzieht keine
Rechte anderer Dienste (ohne `--haerten`); nur überzählige Schreibrechte der eigenen Importrolle setzt es auf den
Sollstand zurück (E46). Es legt `pipeline_meta.katalog_aktualisieren()` an, mit der die Pipeline nach einem Lauf
mit Änderungen die View `source_granularities` aktualisiert (Antwort 75); dafür beim ersten Mal als Eigentümer dieser
View oder als Superuser ausführen (der erste Aufruf legt den Eigentümer der Funktion fest, `docs/betrieb.md`).
Die Pipeline selbst läuft als `pipeline_import`. Diese Rolle ist
nicht Eigentümerin der MOSIDI-Tabellen und darf sie deshalb nicht analysieren (`ANALYZE` wird mit einer Warnung
übersprungen); die Pipeline braucht das auch nicht, weil sie ohne verschachtelte Schleifen abgleicht (E31).

## Getestet am 03.11.2026

Die Läufe dieses Abschnitts nutzten die damalige `config/quellen.yaml`, mit der Statistik aus der Regionaldatenbank
(erst E48 stellte am 06.11. auf XLSX um).

Mit der `docker-compose.yml` aus MOSIDI-ORG/MOSIDI (Commit 26cadbb), nur `brandenburg_db` gestartet
(die anderen Dienste braucht die Pipeline nicht), Schema aus `sql/mosidi/001_bestand.sql` eingespielt.
Belege in `beispielberichte/mosidi-compose/`.

1. **Unverändertes Compose:** `brandenburg_db` startet nicht. Das Image `postgis/postgis` ohne Tag war
   an diesem Tag PostgreSQL 18.6 mit PostGIS 3.6.4; ab 18 erwarten die Images das Volume unter
   `/var/lib/postgresql`, MOSIDI hängt es unter `/var/lib/postgresql/data` ein. Der Container läuft in
   eine Neustart-Schleife (Meldung „in 18+, these Docker images are configured to store database data
   in a format which is compatible with pg_ctlcluster …“). Das betrifft MOSIDI unabhängig von der
   Pipeline, auch eine bestehende Datenbank nach dem nächsten `docker compose pull`.
2. **Mit Volume unter `/var/lib/postgresql`** (Test-Override, außerdem keine Freigabe von Port 5432
   nach außen): `pipeline-einrichten` und `pipeline --alle` laufen durch, 882 Gebäude, 413 Gemeinden,
   18 Kreise, 1 652 Statistikwerte (damals aus der Regionaldatenbank), 57 259 INKAR-Werte, 115 s (Lauf vom 03.11., vor E40; seit E40
   schreibt dieselbe Konfiguration 62 929 INKAR-Werte, weil wertgleiche Reihen nicht mehr zusammenfallen).

## Wiederholt am 07.11.2026 am Abgabestand nach E51

Derselbe Ablauf als Skript: `beispielberichte/pruefstand-2026-11-07-e51/mosidi-compose/lauf.sh` (MOSIDI frisch
geklont, Commit 26cadbb; unveränderte `docker-compose.yml` mit diesem Overlay; Image `e51-beleg`; beide Läufe mit der
Prüfkonfiguration `--config /app/config/pruefkonfiguration.yaml`, damit sie mit den Läufen bis E50 vergleichbar
bleiben). Ergebnis (07.11.2026, 05:35 bis 05:41 MEZ): Das unveränderte `brandenburg_db` startet weiter nicht
(PostgreSQL 18.6, 9 Neustarts). Mit dem Volume unter `/var/lib/postgresql`: `pipeline-einrichten` mit Rückgabewert 0,
Lauf 1 mit 882 Gebäuden, 413 Gemeinden, 18 Kreisen, 413 + 413 Werten des Amts für Statistik und 62 929 INKAR-Werten
(abgelegte Datei, Freigabe nicht genutzt) in 145,4 s, „Katalog: public.source_granularities aktualisiert“ (0 → 11
Zeilen); Lauf 2 in 141,8 s alles unverändert; beide Rückgabewert 0; Schema `public` vorher und nachher gleich. Nicht
gemessen sind dort der Speicher und ein Lauf mit der Lieferkonfiguration im Vollumfang (Abnahmelauf, AP 8). Belege:
`beispielberichte/pruefstand-2026-11-07-e51/` (README, Abschnitt Compose von MOSIDI).

## Wiederholt am 06.11.2026 am Stand nach E50 (davor am 06.11. am Stand nach E49, am 05./06.11. am Stand nach E47 und am 05.11. am Stand nach E46)

Derselbe Ablauf, als Skript nachvollziehbar: `beispielberichte/pruefstand-2026-11-06-e50/mosidi-compose/lauf.sh`
(nach E47: `beispielberichte/pruefstand-2026-11-05-e47/mosidi-compose/lauf.sh`; MOSIDI jeweils frisch geklont, Commit 26cadbb wie am 03.11.; unveränderte `docker-compose.yml` mit diesem Overlay;
eigener Projektname, zufällige Passwörter in einer `.env`, danach `down -v`). Die Abweichungen stehen nur im
Test-Override des Skripts: Volume unter `/var/lib/postgresql`, keine Portfreigabe, eigener Containername, Image
dieses Stands, Berichtsordner außerhalb des Repositorys. Dazu als Testaufbau die Materialized View
`source_granularities` wörtlich aus MOSIDI (`services/backend/src/db_table_metadata/script.py`), damit die
Katalogaktualisierung aus E46 gegen die echte Definition läuft.

Konfiguration (Nachtrag zu E51, an die richtige Stelle verschoben in der Nachprüfung zu E51): Der Lauf am Abgabestand
nach E50 nutzte die damalige `config/quellen.yaml`, seit E51 unverändert als `config/pruefkonfiguration.yaml` (INKAR
mit fünf Kürzeln in Brandenburg, Statistik als XLSX); mit der Lieferkonfiguration im Vollumfang ist im Compose von
MOSIDI kein Lauf gemessen.

Ergebnis am Abgabestand nach E50 (06.11.2026, 22:43 bis 22:50 MEZ; Code nach E50 einschließlich der Nachprüfung): Das
unveränderte `brandenburg_db` startet weiter nicht (PostgreSQL 18.6, 9 Neustarts in 30 s). Mit dem Volume unter
`/var/lib/postgresql`: `pipeline-einrichten` mit Rückgabewert 0, `pipeline --alle` mit 882 Gebäuden, 413 Gemeinden,
18 Kreisen, 413 + 413 Werten des Amts für Statistik und 62 929 INKAR-Werten (aus der abgelegten Datei per
`PIPELINE_INKAR_DATEI`, die Vorrang vor der seit E50 konfigurierten `robots_freigabe` hat; `www.bbr-server.de` nicht
abgerufen, im Container auf `0.0.0.0`) in 145,6 s, Rückgabewert 0, „Katalog: public.source_granularities aktualisiert“
(0 → 11 Zeilen); ein zweiter Lauf (142,4 s, Rückgabewert 0) alles unverändert, ohne Katalogaufruf. Das Schema `public`
ist vor `pipeline-einrichten` und danach gleich (sha256 wie nach E46, E47 und E49). Der INKAR-Schritt dauert länger als
nach E49 (126,7 statt 94,8 s; Prüfstand, Abschnitt „Abweichungen“). Belege und Einzelheiten:
`beispielberichte/pruefstand-2026-11-06-e50/` (README, Abschnitt Compose von MOSIDI).

Ergebnis am Stand nach E49 (06.11.2026, 12:13 bis 12:19 MEZ; Code wie nach E48 (dazu nur die Namensnennung von basemap.de in `pipeline/karte.py`, außerhalb E49)): Das unveränderte `brandenburg_db`
startet weiter nicht (PostgreSQL 18.6, Neustart-Schleife wie oben). Mit dem Volume unter `/var/lib/postgresql`:
`pipeline-einrichten` ohne Warnung, `pipeline --alle` mit 882 Gebäuden, 413 Gemeinden, 18 Kreisen, 413 + 413 Werten
des Amts für Statistik (XLSX, E48) und 62 929 INKAR-Werten (aus der abgelegten Datei `cache/inkar_2025.zip`) in
111,9 s, Rückgabewert 0, „Katalog: public.source_granularities aktualisiert“ (0 → 11 Zeilen: 9 INKAR, 2 Amt für
Statistik); ein zweiter Lauf (114,4 s, Rückgabewert 0) alles unverändert, ohne Katalogaufruf. Das Schema `public` ist
vor `pipeline-einrichten` und danach gleich (sha256 wie nach E46 und E47). Belege und Einzelheiten:
`beispielberichte/pruefstand-2026-11-06-e49/` (README, Abschnitt Compose von MOSIDI; das Skript liegt seit E50 in e50).

Ergebnis am Stand nach E47 (06.11.2026, 00:06 bis 00:11 MEZ): Das unveränderte `brandenburg_db` startet weiter
nicht (PostgreSQL 18.6, Neustart-Schleife wie oben). Mit dem Volume unter `/var/lib/postgresql`: `pipeline-einrichten`
ohne Warnung, `pipeline --alle` mit 882 Gebäuden, 413 Gemeinden, 18 Kreisen, 1 652 Werten des Amts für Statistik und
62 929 INKAR-Werten in 112,3 s, „Katalog: public.source_granularities aktualisiert“ (0 → 13 Zeilen); ein zweiter
Lauf (112,3 s) alles unverändert, ohne Katalogaufruf. Beide Läufe enden mit Rückgabewert 1, weil die
Datenbereichsprüfung aus E47 bei der Flächentabelle der Regionaldatenbank anschlägt (Zeile 7 ohne gültigen
Gebietsschlüssel; Quelle unvollständig, 413 Flächen geladen, nichts gelöscht; die Katalogaktualisierung lief
trotzdem; Befund und Behebung im README des Prüfstands). Seit E48 liest die Konfiguration Bevölkerung und Fläche
aus dem XLSX-Bericht des Amts für Statistik (die Regionaldatenbank sperrt Abrufe per robots.txt); der Befund zur
Zeile 7 ist damit gegenstandslos, statt 1 652 sind 826 Werte zu erwarten (413 + 413). Am Stand nach E49 und am Abgabestand nach E50 ist der Lauf
wiederholt (oben). Das Schema `public` ist vor `pipeline-einrichten` und
danach gleich (ohne die Rechte, die `pipeline-einrichten` wie vorgesehen an die beiden Rollen vergibt). Belege und
Einzelheiten: `beispielberichte/pruefstand-2026-11-05-e47/` (README, Abschnitt Compose von MOSIDI). Der Lauf am
Stand nach E46 vom 05.11. (110 s, Rückgabewert 0, dort noch mit Kürzung von `aktualit`) liegt in
`beispielberichte/pruefstand-2026-11-05-e46/`.

Empfehlung für die TH: `brandenburg_db` auf eine Hauptversion festlegen (z. B. `postgis/postgis:17-3.5`
oder die bisher genutzte) oder auf den neuen Einhängepunkt umstellen und die Daten mit `pg_upgrade`
überführen. Die Datenbanktests der Pipeline liefen am 03.11.2026 lokal gegen PostgreSQL 16.15 (festgeschrieben in
der eigenen Testumgebung) und 18.6 (`postgis/postgis:latest`), je 10 von 10 (am Stand nach E42 vom 05.11.2026 je 35 von 35, Protokoll in `beispielberichte/pruefstand-2026-11-05-e42/`; am Stand nach E45 je 38 von 38, Protokoll in `beispielberichte/pruefstand-2026-11-05-e45/`; am Stand nach E46 je 47 von 47, Protokoll in `beispielberichte/pruefstand-2026-11-05-e46/`; am Stand nach E47 je 59 von 59, Protokoll in `beispielberichte/pruefstand-2026-11-05-e47/`; am Stand nach E48 je 63 von 63, Protokoll in `beispielberichte/pruefstand-2026-11-06-e48/`; am Stand nach E49 je 63 von 63, Protokoll in `beispielberichte/pruefstand-2026-11-06-e49/`; am Stand nach E50 je 66 von 66, Protokoll in `beispielberichte/pruefstand-2026-11-06-e50/`; am Abgabestand nach E51 je 70 von 70, Protokoll in `beispielberichte/pruefstand-2026-11-07-e51/`); der CI-Job `datenbank` ist
für beide Versionen eingerichtet.

## Verhältnis zum INKAR-Import der TH

Der öffentliche Import unter `services/backend/src/inkar_import` löscht `dashboard_data_de` mit
`DROP TABLE` und legt sie ohne `source` und `granularity` neu an. Laufen beide, verschwinden die Zeilen
der Pipeline (sie legt sie beim nächsten Lauf als „neu“ wieder an), und die INKAR-Zeilen der TH ohne
`source` stehen neben denen der Pipeline. Die INKAR-Quelle der Pipeline ersetzt diesen Import. Seit E50 lädt
sie wie gefordert automatisch per URL (Antwort 33): robots.txt von `www.bbr-server.de` sperrt automatische
Abrufe, die ausgelieferte `config/quellen.yaml` trägt dafür eine benannte Freigabe (`robots_freigabe`, im
Bericht und im Protokoll je Lauf ausgewiesen; Erlaubnis des BBSR in AP 1). Für einen Prüflauf ohne Netzabruf
die Gesamtdatei unter `cache/` des Pipeline-Verzeichnisses ablegen (im Dienst `pipeline` als `/app/cache`
eingehängt) und `PIPELINE_INKAR_DATEI=/app/cache/inkar_2025.zip` in die `.env` von MOSIDI schreiben; das
Overlay reicht die Variable seit E50 an den Dienst durch (bis dahin kam sie dort nicht an). Welche
Werte `source` und `granularity` in den Daten der TH tragen, klären wir in Arbeitspaket 1, damit die
Pipeline vorhandene Zeilen übernimmt statt sie zu verdoppeln.

Form der Kennziffer (offen seit E28, mit dem Vollumfang wirksam; Nachprüfung zu E51): Der Import der TH wandelt die
Kennziffer in eine Zahl (`config.xml`: `integer`, `inkar_db_import.py`: `convert_or_na`), danach in Text; Gemeinden
mit führender Null stehen dort siebenstellig. Die Pipeline schreibt sie achtstellig wie in der INKAR-Datei. Bis E50
(nur Brandenburg, `12…`) war das folgenlos; im Vollumfang betrifft es 25 972 031 von 33 547 606 Zeilen (77 %), 8 526
von 10 978 Gemeinden (gezählt am 07.11.2026 aus der abgelegten Datei, ohne Netz). Welche Form die Plattform erwartet,
legt die TH fest; das ist vor dem Regelbetrieb zu klären. Bis dahin bleibt der Code unverändert.

## Hinweise

- Relative Pfade gelten bei mehreren `-f` relativ zur ersten Datei, deshalb `PIPELINE_DIR` (absolut).
- `docker compose config` braucht alle `env_file`-Dateien des MOSIDI-Compose (`.env`, `pg_tileserv.env`),
  auch wenn nur `brandenburg_db` startet.
- `brandenburg_db` hat keinen Healthcheck; die Pipeline wartet beim Verbinden bis zu 30 s
  (`pipeline-einrichten` bis zu 60 s). Unmittelbar nach dem ersten Start, während die Datenbank noch
  eingerichtet wird, kann ein Aufruf trotzdem zu früh kommen; dann wiederholen.

## Frontend (nicht getestet)

Das MOSIDI-Frontend zeichnet Kennzahlen aus `dashboard_data_de` auf Gemeindeflächen, die es als
Vektorkacheln vom GeoServer lädt (Ebene `brandenburg:Gemeindeebene`, `services/frontend/src/components/
IndicatorUI.vue` und `MainMap.vue`). Arbeitsbereich, Datenspeicher und Ebenen des GeoServers liegen im
Volume `geoserver_data`, nicht im Repository; dazu kommen die Umgebungsvariablen `VUE_APP_BASE_URI` und
`VUE_APP_GEOSERVER_URL`, die ebenfalls nicht im Repository stehen. Ohne diese Konfiguration zeigt das
Frontend keine Karte. Deshalb gibt es für die importierten Daten keinen Screenshot aus dem Frontend; die
Verknüpfung prüft die Pipeline selbst (bei konfigurierter Gebietstabelle `ziel.gebiet`: Gebietsschlüssel mit Fläche
je Lauf; die Lieferkonfiguration setzt sie für INKAR nicht, weil die Gemeindeflächen in MOSIDI nur Brandenburg
decken) und zeigt sie in der Änderungskarte.

## Zeitsteuerung im Betrieb

`geodaten-import-mosidi.service` ist die systemd-Unit für den Betrieb bei der TH: Sie startet
`brandenburg_db`, falls nötig, und dann einen Lauf mit diesem Overlay, aus dem MOSIDI-Verzeichnis
heraus. Timer und Fehlermeldung sind dieselben wie in `deploy/systemd/` (täglicher Lauf, fällige
Quellen nach Rhythmus, Journalzeile mit Priorität err bei Exit-Code ungleich 0). Die Unit in
`deploy/systemd/geodaten-import.service` bleibt für die eigene Testumgebung mit dem Dienst `db`.
Pfade und Uhrzeit stimmen wir in Arbeitspaket 1 mit dem Rechenzentrum ab.

Laufzeitgrenzen (E51): Je Quelle gilt ihr Zeitbudget, auch für die Datenbank (`statement_timeout` = Rest des
Budgets, `lock_timeout` höchstens `db_sperre_max_s`, Standard 300 s); ist die Zieltabelle in `brandenburg_db`
länger gesperrt, wird nur diese Quelle zurückgerollt und die nächste läuft. Für den ganzen Lauf gilt
`TimeoutStartSec=7h` der Unit, über der Summe der Zeitbudgets der Lieferkonfiguration (5 × 30 min + 240 min
INKAR = 390 min, dazu 30 min Reserve für Verbindung, Katalog und Berichte). Nicht gemessen: die Katalogaktualisierung
(`REFRESH` von `source_granularities`) nach einem Vollumfang; sie läuft nach den Quellen ohne eigene Laufzeitgrenze
und zählt zur Reserve. Reicht die Reserve nicht, sind die Daten schon übernommen, und der nächste Lauf holt die
Aktualisierung nach (`pipeline_meta.katalog_offen`). Compose selbst setzt keine Laufzeitgrenze. Restarbeit laut
Angebot (AP 7, bis zur Übergabe): Der Importbericht wird vor der Katalogaktualisierung gesichert, und für sie gilt ein
eigenes Zeitlimit; bei Überschreitung bleibt sie in `katalog_offen` zur Wiederholung vorgemerkt (im Prototyp läuft sie
vor dem Bericht und ohne eigenes Limit).
