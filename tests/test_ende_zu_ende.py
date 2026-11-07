"""Ende-zu-Ende über die Kommandozeile und Wiederherstellungsprobe (E52), gegen eine echte PostgreSQL/PostGIS-
Datenbank wie tests/test_datenbank.py und gegen einen lokalen Testserver statt fremder Dienste.

Die übrigen Tests prüfen Adapter (mit ersetztem Abruf) und Zielschreiben (mit ersetztem Adapter) getrennt.
Hier läuft der ganze Weg so, wie ihn der Betrieb aufruft: `python -m pipeline.einrichten`, dann zweimal
`python -m pipeline.laden` als eigener Prozess, mit echten HTTP-Abrufen (requests), echtem Zielschreiben,
Berichten im Berichtsordner und Protokoll in pipeline_meta. Die Antworten kommen von einem kleinen Server
im Testprozess (http.server, nur 127.0.0.1, freier Port vom Betriebssystem):

- ein WFS 2.0 wie die Verwaltungsgrenzen der LGB (deegree: kein Paging, Kommentar vor der Geometrie,
  Gemeinden als MultiSurface in EPSG:25833), mit drei erfundenen Gemeinden; Konfiguration wie
  `gemeinden_lgb` in config/quellen.yaml, nur mit anderer Adresse;
- die Statistiktabelle als CSV aus tests/daten/ (erfundene Zahlen), Konfiguration wie _statistik_csv in
  tests/test_datenbank.py, die Gebietsschlüssel durch die der erfundenen Gemeinden ersetzt;
- ein Statistischer Bericht als XLSX aus tests/conftest.py (afs_bericht, erfundene Zahlen), Konfiguration
  wie `bevoelkerung_gemeinden`, mit fester Adresse statt Berichtsseite. Der Server beantwortet
  If-Modified-Since wie ein Webserver (304).

Keine Quelldaten der LGB oder der Statistikämter (Antwort 69), keine Anfrage an einen fremden Rechner: Der
Testprozess selbst bleibt durch _kein_netz (conftest.py) ohne Netz, der Pipeline-Prozess bekommt nur
Adressen auf 127.0.0.1; das prüft `--ziele` vor dem ersten Lauf. robots.txt liest die Pipeline zur Laufzeit
nicht: Die Sperren stehen fest in quellen.ROBOTS_GESPERRT (E48), 127.0.0.1 steht nicht darin. Der Test
prüft deshalb, dass jede Anfrage an den Server eine erwartete war (keine 404, kein /robots.txt) und dass
weder eine Sperre noch eine Freigabe im Bericht steht.

Die Wiederherstellungsprobe sichert die ganze Datenbank nach einem Lauf mit pg_dump, spielt sie mit
pg_restore in eine leere Datenbank zurück, richtet ein und lässt die Pipeline gegen die Rücksicherung laufen:
Sie muss alles als unverändert melden, die Dateiquellen anhand des Vergleichsstands in pipeline_meta
überspringen und keine Zeile als übernommen zählen. Das Gegenstück ohne pipeline_meta zeigt, warum das
Schema zur Sicherung gehört (docs/betrieb.md, Sicherung und Wiederherstellung). pg_dump und pg_restore
laufen im Container der Datenbank (`docker compose exec`), also immer in der Version des Servers; auf dem
Runner der CI liegt sonst nur ein Client einer Hauptversion, der einen neueren Server nicht sichert.

Laufen wie die Datenbanktests nur mit DATENBANK_TEST=1 und der Datenbank aus docker-compose.yml, in der CI
im Job `datenbank`. Die Wiederherstellungsprobe braucht zusätzlich `docker compose` im Wurzelverzeichnis;
für ein eigenes Compose-Projekt COMPOSE_PROJECT_NAME setzen (wie `-p`). Jeder Test nutzt eigene Quellnamen,
Indikatornamen und Gebietsschlüssel (zufällige Endungen aus uuid4), die Tests stören sich also nicht
gegenseitig und laufen auch auf einer schon benutzten Testdatenbank. `einrichten` bekommt wie im Betrieb
alle Konfigurationen derselben Datenbank (config/quellen.yaml und die des Tests, E46).
"""
import email.utils
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import pytest

# Ohne DATENBANK_TEST=1 wird das ganze Modul übersprungen, wie tests/test_datenbank.py
pytestmark = pytest.mark.skipif(os.environ.get("DATENBANK_TEST") != "1",
                                reason="nur mit DATENBANK_TEST=1 und laufender Datenbank")

# psycopg und PyYAML braucht nur dieser Testblock: fehlen sie, wird übersprungen statt abgebrochen
psycopg = pytest.importorskip("psycopg")
yaml = pytest.importorskip("yaml")

# Erst nach importorskip: test_datenbank importiert psycopg über pipeline.einrichten. Übernommen werden nur
# Namen und Bausteine (Konfiguration der Statistiktabelle, Katalog-View wie bei MOSIDI), nicht die Fixtures
# des Moduls
from conftest import afs_bericht  # noqa: E402
from test_datenbank import GEMEINDEN, SG_INDEX, SG_VIEW, _statistik_csv  # noqa: E402

WURZEL = Path(__file__).resolve().parent.parent
KONFIG = WURZEL / "config" / "quellen.yaml"
AUSZUG = Path(__file__).resolve().parent / "daten" / "statistiktabelle-csv-auszug.csv"
# Gebietsschlüssel der Statistiktabelle in tests/daten/, die der Test durch erfundene ersetzt (der letzte ist
# die aufgelöste Gemeinde mit „-“, ohne Fläche im WFS)
AUSZUG_AGS = ("12051000", "12060005", "12060012", "12060096")
# Fester Stand aller Antworten des Servers (Last-Modified): Der Test hängt nicht an der Uhrzeit, und
# If-Modified-Since im Folgelauf trifft genau diesen Stand
STAND = "Sat, 31 Oct 2026 12:00:00 GMT"
# Bericht eines regulären Laufs im Berichtsordner (nicht quellenverzeichnis.json, nicht der Probelauf)
LAUFBERICHT = re.compile(r"\d{8}T\d{6}Z\.json")
# Umgebungsvariablen, die den Pipeline-Prozess an andere Ziele, Dateien oder Texte binden würden
FREMDE_UMGEBUNG = ("DATABASE_URL", "PIPELINE_CONFIG", "PIPELINE_INKAR_DATEI", "PIPELINE_KENNUNG",
                   "PIPELINE_SPRACHE", "PIPELINE_CACHE", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
                   "http_proxy", "https_proxy", "all_proxy")
# Koordinatensystem von gemeinden_lgb (SRSNAME der Abfragen, srsName der Geometrien) und Namensraum der
# Objektart app:gem wie bei deegree
CRS = "urn:ogc:def:crs:EPSG::25833"
APP = "http://www.deegree.org/app"


# --- Testserver -----------------------------------------------------------------------------------------

class _Dienst(ThreadingHTTPServer):
    """HTTP-Server auf 127.0.0.1 mit freiem Port, der aufgezeichnete Antworten ausliefert.

    inhalte: (Pfad, REQUEST-Parameter oder "") → (Inhalt, Content-Type); Dateien haben REQUEST "", die
    Abfragen des WFS ihren REQUEST (GetCapabilities, DescribeFeatureType, GetFeature). anfragen: jede
    Anfrage mit Pfad, REQUEST, allen Parametern (Namen groß geschrieben), If-Modified-Since, User-Agent und
    dem gesendeten Status, in der Reihenfolge des Eingangs."""
    # Anfragen in eigenen Threads, die beim Beenden des Servers nicht gewartet werden müssen
    daemon_threads = True

    def __init__(self) -> None:
        """Bindet an 127.0.0.1, Port 0 (das Betriebssystem wählt einen freien)."""
        super().__init__(("127.0.0.1", 0), _Anfrage)
        self.inhalte: dict[tuple[str, str], tuple[bytes, str]] = {}
        self.anfragen: list[dict] = []
        self.sperre = threading.Lock()

    @property
    def basis(self) -> str:
        """Adresse des Servers ohne Pfad, etwa http://127.0.0.1:40123."""
        return f"http://127.0.0.1:{self.server_address[1]}"

    def ablegen(self, pfad: str, inhalt: bytes, typ: str, request: str = "") -> str:
        """Antwort `inhalt` (Content-Type `typ`) unter `pfad` und `request` ablegen; Rückgabe: volle Adresse
        des Pfads."""
        self.inhalte[(pfad, request)] = (inhalt, typ)
        return self.basis + pfad

    def unter(self, praefix: str) -> list[dict]:
        """Die bisher eingegangenen Anfragen auf Pfaden, die mit `praefix` beginnen (eine Kopie)."""
        with self.sperre:
            return [a for a in self.anfragen if a["pfad"].startswith(praefix)]


def _zeit(text: str | None) -> float | None:
    """HTTP-Datum als Zeitstempel, None bei fehlender oder unlesbarer Angabe."""
    try:
        return email.utils.parsedate_to_datetime(text).timestamp() if text else None
    except (TypeError, ValueError):
        return None


class _Anfrage(BaseHTTPRequestHandler):
    """Beantwortet GET aus _Dienst.inhalte: 200 mit Last-Modified STAND, 304, wenn If-Modified-Since nicht
    älter als STAND ist, 404 für alles andere (auch /robots.txt). Kein Weiterleiten, kein Protokoll auf
    stderr."""

    def do_GET(self) -> None:  # Name von BaseHTTPRequestHandler vorgegeben
        """Antwort auf eine GET-Anfrage; zeichnet sie in server.anfragen auf."""
        teile = urlsplit(self.path)
        # WFS-Parameter sind ohne Groß- und Kleinschreibung (OGC); die Pipeline sendet sie groß
        params = {k.upper(): v for k, v in parse_qsl(teile.query, keep_blank_values=True)}
        eintrag = self.server.inhalte.get((teile.path, params.get("REQUEST", "")))
        seit = self.headers.get("If-Modified-Since")
        if eintrag is None:
            status = 404
        elif _zeit(seit) is not None and _zeit(seit) >= _zeit(STAND):
            status = 304
        else:
            status = 200
        with self.server.sperre:
            self.server.anfragen.append({"pfad": teile.path, "request": params.get("REQUEST", ""),
                                         "params": params, "seit": seit, "status": status,
                                         "kennung": self.headers.get("User-Agent", "")})
        inhalt, typ = eintrag if status == 200 else (b"", "text/plain")
        self.send_response(status)
        self.send_header("Content-Type", typ)
        self.send_header("Content-Length", str(len(inhalt)))
        self.send_header("Last-Modified", STAND)
        self.end_headers()
        self.wfile.write(inhalt)

    def log_message(self, *_args) -> None:
        """Kein Zugriffsprotokoll auf stderr; die Anfragen stehen in server.anfragen."""


@pytest.fixture(scope="module")
def dienst():
    """Einmal je Modul: der Testserver in einem Hintergrund-Thread; danach beendet und geschlossen."""
    server = _Dienst()
    faden = threading.Thread(target=server.serve_forever, daemon=True)
    faden.start()
    yield server
    server.shutdown()
    server.server_close()
    faden.join(timeout=10)


# --- Aufgezeichnete Antworten ---------------------------------------------------------------------------

def _capabilities() -> bytes:
    """GetCapabilities wie bei den Verwaltungsgrenzen der LGB (deegree, WFS 2.0): Titel, Anbieter, Kontakt,
    ohne Paging und ohne Sortierung (Antwort 69: dort Abruf in einer Kachel). Anbieter und Adresse sind
    erfunden."""
    ows = "http://www.opengis.net/ows/1.1"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<wfs:WFS_Capabilities xmlns:wfs="http://www.opengis.net/wfs/2.0" xmlns:ows="{ows}" version="2.0.0"
 updateSequence="2026-10-31T12:00:00Z">
<ows:ServiceIdentification><ows:Title>Verwaltungsgrenzen (Testdienst)</ows:Title>
<ows:Abstract>Erfundene Gemeinden für den Ende-zu-Ende-Test</ows:Abstract></ows:ServiceIdentification>
<ows:ServiceProvider><ows:ProviderName>Testanbieter (erfunden)</ows:ProviderName><ows:ServiceContact>
<ows:ContactInfo><ows:Address><ows:ElectronicMailAddress>dienst@anbieter.example</ows:ElectronicMailAddress>
</ows:Address></ows:ContactInfo></ows:ServiceContact></ows:ServiceProvider>
<ows:OperationsMetadata>
<ows:Constraint name="ImplementsResultPaging"><ows:NoValues/><ows:DefaultValue>FALSE</ows:DefaultValue>
</ows:Constraint>
<ows:Constraint name="ImplementsSorting"><ows:NoValues/><ows:DefaultValue>FALSE</ows:DefaultValue>
</ows:Constraint>
</ows:OperationsMetadata></wfs:WFS_Capabilities>""".encode()


def _schema() -> bytes:
    """DescribeFeatureType für app:gem mit den Feldern, die gemeinden_lgb liest (ags, gem_name, krss,
    gem_aktualitaet, geom); so prüft die Pipeline die Feldliste am Schema (E4), ohne Warnung."""
    felder = "".join(f'<xs:element name="{f}" type="xs:string" minOccurs="0"/>'
                     for f in ("ags", "gem_name", "krss", "gem_aktualitaet"))
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:gml="http://www.opengis.net/gml/3.2"
 xmlns:app="{APP}" targetNamespace="{APP}" elementFormDefault="qualified">
<xs:element name="gem" substitutionGroup="gml:AbstractFeature"><xs:complexType><xs:complexContent>
<xs:extension base="gml:AbstractFeatureType"><xs:sequence>{felder}
<xs:element name="geom" type="gml:MultiSurfacePropertyType" minOccurs="0"/>
</xs:sequence></xs:extension></xs:complexContent></xs:complexType></xs:element></xs:schema>""".encode()


def _gemeinden_gml(gemeinden: list[tuple[str, str, int, int]]) -> bytes:
    """GetFeature (WFS 2.0, GML 3.2) wie bei deegree: je Gemeinde (AGS, Name, Rechtswert, Hochwert) ein
    app:gem mit einem Quadrat von 1 km Kantenlänge als MultiSurface in EPSG:25833, südwestliche Ecke im
    angegebenen Punkt, Kommentar vor der Geometrie; numberMatched gleich numberReturned (eine Kachel)."""
    teile = []
    for ags, name, x, y in gemeinden:
        ring = " ".join(f"{a} {b}" for a, b in ((x, y), (x + 1000, y), (x + 1000, y + 1000), (x, y + 1000),
                                                 (x, y)))
        teile.append(
            f'<wfs:member><app:gem gml:id="gem_{ags}"><app:ags>{ags}</app:ags>'
            f"<app:gem_name>{name}</app:gem_name><app:krss>{ags[:5]}</app:krss>"
            f"<app:gem_aktualitaet>2026-01-01</app:gem_aktualitaet><app:geom>"
            f"<!--Inlined geometry 'gem_{ags}_APP_GEOM'-->"
            f'<gml:MultiSurface gml:id="gem_{ags}_APP_GEOM" srsName="{CRS}"><gml:surfaceMember>'
            f'<gml:Polygon gml:id="gem_{ags}_P"><gml:exterior><gml:LinearRing><gml:posList>{ring}'
            f"</gml:posList></gml:LinearRing></gml:exterior></gml:Polygon></gml:surfaceMember>"
            f"</gml:MultiSurface></app:geom></app:gem></wfs:member>")
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n<wfs:FeatureCollection '
            f'xmlns:wfs="http://www.opengis.net/wfs/2.0" xmlns:gml="http://www.opengis.net/gml/3.2" '
            f'xmlns:app="{APP}" timeStamp="2026-10-31T12:00:00Z" numberMatched="{len(gemeinden)}" '
            f'numberReturned="{len(gemeinden)}">{"".join(teile)}</wfs:FeatureCollection>').encode()


def _aufbauen(tmp: Path, dienst: _Dienst) -> dict:
    """Legt die Antworten eines Tests auf dem Server ab und schreibt seine Konfiguration nach
    tmp/quellen.yaml. Alles trägt eine eigene Kennung k (Pfade, Quellnamen, `source`, Indikatornamen) und
    eigene Gebietsschlüssel 129xxxxx (Kreis 129 gibt es in Brandenburg nicht).

    Rückgabe: dict mit config (Pfad), k, wfs/csv/xlsx (Quellnamen), ags (vier Schlüssel; die ersten drei
    sind Gemeinden im WFS), csv_sha/xlsx_sha (SHA-256 der ausgelieferten Dateien), indikatoren (je Quelle
    die Liste der Indikatornamen)."""
    k = uuid.uuid4().hex[:8]
    basis = uuid.uuid4().int % 10**5
    ags = [f"129{(basis + i) % 10**5:05d}" for i in range(4)]
    gemeinden = [(a, f"Testgemeinde {i + 1}", 330000 + 2000 * i, 5800000) for i, a in enumerate(ags[:3])]

    # WFS: drei Abfragen unter einer Adresse, unterschieden nach REQUEST
    wfs_pfad = f"/{k}/ows/vg_wfs"
    for request, inhalt in (("GetCapabilities", _capabilities()), ("DescribeFeatureType", _schema()),
                            ("GetFeature", _gemeinden_gml(gemeinden))):
        dienst.ablegen(wfs_pfad, inhalt, "text/xml; charset=UTF-8", request)

    # CSV: die Statistiktabelle aus tests/daten/ (latin-1) mit den Schlüsseln dieses Tests
    text = AUSZUG.read_bytes().decode("latin-1")
    for alt, neu in zip(AUSZUG_AGS, ags, strict=True):
        text = text.replace(alt, neu)
    csv = text.encode("latin-1")
    csv_url = dienst.ablegen(f"/{k}/statistiktabelle.csv", csv, "text/csv; charset=ISO-8859-1")

    # XLSX: Statistischer Bericht mit erfundenen Zahlen (32 Gemeinden), einmal geschrieben, also in beiden
    # Läufen byte-gleich
    xlsx = afs_bericht(tmp / "bericht-quelle.xlsx").read_bytes()
    xlsx_url = dienst.ablegen(f"/{k}/SB_test_2025j01_BB.xlsx", xlsx,
                              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    namen = {"wfs": f"e2e_{k}_gemeinden", "csv": f"e2e_{k}_statistik", "xlsx": f"e2e_{k}_bericht"}
    ausgeliefert = yaml.safe_load(KONFIG.read_text(encoding="utf-8"))["quellen"]

    # Wie gemeinden_lgb, nur mit der Adresse des Testservers (http nur mit erlaube_http, E41)
    wfs = {**ausgeliefert["gemeinden_lgb"], "url": dienst.basis + wfs_pfad, "erlaube_http": True}

    # Wie _statistik_csv in test_datenbank; eigene source und eigene Indikatornamen (mit dem Quellnamen), weil
    # table_metadata je Indikator einen Namen nur einmal vergibt (Primärschlüssel table_name, E46); CSV und
    # XLSX hießen sonst beide „Bevölkerung insgesamt (Stichtag 31.12.)“
    statistik = _statistik_csv()
    statistik.update(pfad=csv_url, erlaube_http=True, unveraendert_ueberspringen=True)
    statistik["ziel"] = {**statistik["ziel"], "fest": {**statistik["ziel"]["fest"], "source": namen["csv"]},
                         "je_wert": {f: f"{t} ({namen['csv']})"
                                     for f, t in statistik["ziel"]["je_wert"].items()}}

    # Wie bevoelkerung_gemeinden, mit fester Adresse statt Berichtsseite (seite verlangt https auf Port 443)
    bericht = {s: w for s, w in ausgeliefert["bevoelkerung_gemeinden"].items()
               if s not in ("seite", "datei_muster", "link_rechner")}
    bericht.update(pfad=xlsx_url, erlaube_http=True, unveraendert_ueberspringen=True)
    bericht["ziel"] = {**bericht["ziel"], "fest": {**bericht["ziel"]["fest"], "source": namen["xlsx"]},
                       "je_wert": {f: f"{t} ({namen['xlsx']})"
                                   for f, t in bericht["ziel"]["je_wert"].items()}}

    config = tmp / "quellen.yaml"
    config.write_text(yaml.safe_dump(
        {"berichte": str(tmp / "berichte"), "sprache": "de",
         "quellen": {namen["wfs"]: wfs, namen["csv"]: statistik, namen["xlsx"]: bericht}},
        allow_unicode=True, sort_keys=False), encoding="utf-8")
    return {"config": config, "k": k, **namen, "ags": ags,
            "csv_sha": hashlib.sha256(csv).hexdigest(), "xlsx_sha": hashlib.sha256(xlsx).hexdigest(),
            "indikatoren": {namen["csv"]: sorted(statistik["ziel"]["je_wert"].values()),
                            namen["xlsx"]: sorted(bericht["ziel"]["je_wert"].values())}}


# --- Pipeline als eigener Prozess -------------------------------------------------------------------------

def _umgebung(tmp: Path, admin: bool = False, datenbank: str | None = None) -> dict:
    """Umgebung für den Pipeline-Prozess: Verbindung wie bei libpq aus PGHOST/PGPORT/PGDATABASE (oder
    `datenbank`), als Importrolle oder (admin) als Administrator für einrichten; Cache in tmp/cache; ohne
    Proxy und ohne die Variablen in FREMDE_UMGEBUNG."""
    env = {s: w for s, w in os.environ.items() if s not in FREMDE_UMGEBUNG}
    env.update(PIPELINE_CACHE=str(tmp / "cache"), NO_PROXY="127.0.0.1,localhost",
               no_proxy="127.0.0.1,localhost", PYTHONDONTWRITEBYTECODE="1")
    if datenbank:
        env["PGDATABASE"] = datenbank
    if admin:
        env.update(PGUSER=os.environ.get("POSTGRES_USER", "admin"),
                   PGPASSWORD=os.environ["POSTGRES_PASSWORD"])
    else:
        env.update(PGUSER="pipeline_import", PGPASSWORD=os.environ["IMPORT_PASSWORD"])
    return env


def _pipeline(modul: str, *argumente: str, env: dict) -> subprocess.CompletedProcess:
    """`python -m pipeline.<modul> <argumente>` im Wurzelverzeichnis des Repositorys, mit dem Interpreter
    dieses Tests; Ausgabe als Text, höchstens 10 min."""
    # Fester Befehl aus dem eigenen Interpreter und dem eigenen Modul; Argumente aus dem Test selbst
    return subprocess.run([sys.executable, "-m", f"pipeline.{modul}", *argumente],  # noqa: S603
                          cwd=WURZEL, env=env, capture_output=True, text=True, timeout=600, check=False)


def _einrichten(a: dict, tmp: Path, datenbank: str | None = None) -> None:
    """`pipeline.einrichten` mit der ausgelieferten und der Konfiguration des Tests (wie im Betrieb alle
    Konfigurationen derselben Datenbank, E46), als Administrator; muss mit 0 enden."""
    r = _pipeline("einrichten", "--config", str(KONFIG), "--config", str(a["config"]),
                  env=_umgebung(tmp, admin=True, datenbank=datenbank))
    assert r.returncode == 0, (r.stdout, r.stderr)


def _lauf(a: dict, tmp: Path, *argumente: str, datenbank: str | None = None) -> tuple[int, dict, str]:
    """Ein Lauf `pipeline.laden --config <Test> <argumente>` als Importrolle. Rückgabe: Rückgabewert, der
    JSON-Bericht dieses Laufs und die Ausgabe auf stdout (der Textbericht). Der Bericht muss neu sein und als
    einziger dazugekommen."""
    # Laufkennungen sind sekundengenau und in pipeline_meta.lauf datenbankweit eindeutig; startzeit()
    # weicht nur Berichten im eigenen Ordner aus, nicht denen anderer Tests derselben Sekunde
    time.sleep(1.1)
    ordner = tmp / "berichte"
    vorher = set(ordner.glob("*.json")) if ordner.exists() else set()
    r = _pipeline("laden", "--config", str(a["config"]), *argumente, env=_umgebung(tmp, datenbank=datenbank))
    neu = [p for p in ordner.glob("*.json") if p not in vorher and LAUFBERICHT.fullmatch(p.name)]
    assert len(neu) == 1, (r.returncode, r.stdout, r.stderr)
    return r.returncode, json.loads(neu[0].read_text(encoding="utf-8")), r.stdout


def _quelle(bericht: dict, name: str) -> dict:
    """Eintrag der Quelle `name` im Bericht."""
    return next(q for q in bericht["quellen"] if q["quelle"] == name)


def _zahlen(bericht: dict, name: str) -> tuple:
    """Zähler der Quelle `name` als (neu, geaendert, geloescht, unveraendert, uebernommen)."""
    z = _quelle(bericht, name)["zaehler"]
    return z["neu"], z["geaendert"], z["geloescht"], z["unveraendert"], z["uebernommen"]


def _abfrage(text: str, *werte, datenbank: str | None = None) -> list[tuple]:
    """`text` mit den Parametern `werte` als Administrator in PGDATABASE oder `datenbank`; alle Zeilen."""
    kw = {"dbname": datenbank} if datenbank else {}
    with psycopg.connect("", user=os.environ.get("POSTGRES_USER", "admin"),
                         password=os.environ["POSTGRES_PASSWORD"], autocommit=True, **kw) as c:
        return c.execute(text, werte).fetchall()


def _ausfuehren(*befehle: str) -> None:
    """Befehle ohne Ergebnis (DDL, DELETE) als Administrator in PGDATABASE, jeder für sich (autocommit)."""
    with psycopg.connect("", user=os.environ.get("POSTGRES_USER", "admin"),
                         password=os.environ["POSTGRES_PASSWORD"], autocommit=True) as c:
        for befehl in befehle:
            c.execute(befehl)


@pytest.fixture
def katalog():
    """Für einen Test: die Materialized View source_granularities mit eindeutigem Index, wie sie das Skript
    von MOSIDI anlegt (SG_VIEW, SG_INDEX aus test_datenbank; im mitgelieferten Schema sql/mosidi/ fehlt sie,
    test_datenbank legt sie je Test an und entfernt sie wieder). Vorher entfernt: offene Katalogarbeit
    anderer Tests (pipeline_meta.katalog_offen), sonst holte der Folgelauf sie nach; danach die View. Auf
    einer frischen Datenbank gibt es pipeline_meta erst nach einrichten (Modul allein aufgerufen, ohne
    test_datenbank davor), dann ist nichts offen."""
    _ausfuehren("DO $$ BEGIN IF to_regclass('pipeline_meta.katalog_offen') IS NOT NULL THEN "
                "DELETE FROM pipeline_meta.katalog_offen; END IF; END $$",
                "DROP MATERIALIZED VIEW IF EXISTS public.source_granularities", SG_VIEW, SG_INDEX)
    yield
    _ausfuehren("DROP MATERIALIZED VIEW IF EXISTS public.source_granularities")


def _protokoll(lauf_id: str, datenbank: str | None = None) -> dict:
    """pipeline_meta für einen Lauf: Kopfzeile (quellen, fehler, angehalten, unvollstaendig, bericht), je
    Quelle (status, neu, geaendert, entfernt, unveraendert, uebernommen) und die Änderungen als
    {(quelle, art): Anzahl}."""
    kopf = _abfrage("SELECT quellen, fehler, angehalten, unvollstaendig, bericht FROM pipeline_meta.lauf "
                    "WHERE lauf_id = %s", lauf_id, datenbank=datenbank)
    quellen = {q: tuple(rest) for q, *rest in _abfrage(
        "SELECT quelle, status, neu, geaendert, entfernt, unveraendert, uebernommen "
        "FROM pipeline_meta.quellenlauf WHERE lauf_id = %s", lauf_id, datenbank=datenbank)}
    aenderungen = {(q, art): n for q, art, n in _abfrage(
        "SELECT quelle, art, count(*) FROM pipeline_meta.aenderung WHERE lauf_id = %s GROUP BY 1, 2",
        lauf_id, datenbank=datenbank)}
    return {"kopf": kopf, "quellen": quellen, "aenderungen": aenderungen}


def _unveraendert_pruefen(a: dict, rc: int, b: dict, text: str, datenbank: str | None = None) -> None:
    """Folgelauf ohne Änderung: Rückgabe 0; der WFS eingelesen und verglichen, alle drei Gemeinden
    unverändert, nichts übernommen; CSV und XLSX als byte-gleich übersprungen (mit der SHA-256 der
    ausgelieferten Datei); kein Eintrag in pipeline_meta.aenderung, alle Quellen ok."""
    assert rc == 0, text
    assert (b["fehlgeschlagen"], b["angehalten"], b["unvollstaendig"]) == ([], [], []), b
    assert _zahlen(b, a["wfs"]) == (0, 0, 0, 3, 0), _quelle(b, a["wfs"])
    for name, sha in ((a["csv"], a["csv_sha"]), (a["xlsx"], a["xlsx_sha"])):
        q = _quelle(b, name)
        assert q["status"] == "ok" and q["uebersprungen"]["sha256"] == sha, q
        assert any(h.startswith(f"unverändert (Datei byte-gleich, sha256 {sha[:16]}…)")
                   for h in q["hinweise"]), q["hinweise"]
    assert re.search(rf"{a['wfs']}\s+ok\s+neu\s+0\s+geändert\s+0\s+gelöscht\s+0\s+unverändert\s+3\b",
                     text), text
    p = _protokoll(b["lauf_id"], datenbank)
    assert p["kopf"] == [(3, 0, 0, 0, f"{b['lauf_id']}.json")], p
    assert p["quellen"][a["wfs"]] == ("ok", 0, 0, 0, 3, 0), p
    assert {q: s[0] for q, s in p["quellen"].items()} == dict.fromkeys((a["wfs"], a["csv"], a["xlsx"]), "ok")
    assert p["aenderungen"] == {}, p
    # Ohne Änderung und ohne offene Katalogarbeit kein Aufruf des Katalogs (E46)
    assert "katalog" not in b, b["katalog"]


def _erwartete_anfragen(praefix: str, xlsx_status: int) -> list[tuple[str, str, int]]:
    """Die Anfragen eines Laufs beim Server als (Pfad, REQUEST, Status), in der Reihenfolge der Quellen in
    der Konfiguration: GetCapabilities, DescribeFeatureType und GetFeature des WFS, die CSV (immer 200: die
    Prüfsumme braucht die Bytes) und das XLSX mit `xlsx_status` (304 im Folgelauf: unverändert seit dem
    Abruf in den Cache)."""
    wfs = praefix + "ows/vg_wfs"
    return [(wfs, "GetCapabilities", 200), (wfs, "DescribeFeatureType", 200), (wfs, "GetFeature", 200),
            (praefix + "statistiktabelle.csv", "", 200),
            (praefix + "SB_test_2025j01_BB.xlsx", "", xlsx_status)]


# --- Tests --------------------------------------------------------------------------------------------------

def test_ende_zu_ende_einrichten_erstlauf_folgelauf_unveraendert(tmp_path, dienst, katalog):
    """Der ganze Weg über die Kommandozeile gegen den Testserver: einrichten, Lauf 1 lädt alles neu (drei
    Gemeinden aus dem WFS, neun Kennzahlen aus der CSV, 32 aus dem XLSX), Lauf 2 mit --alle meldet alles
    unverändert (WFS verglichen, CSV und XLSX als byte-gleich übersprungen, das XLSX per If-Modified-Since
    mit 304 gar nicht erst neu geladen) und endet mit 0. Geprüft werden JSON- und Textbericht, das
    Protokoll in pipeline_meta, die Zieltabellen und jede Anfrage, die beim Server ankam."""
    a = _aufbauen(tmp_path, dienst)
    praefix = f"/{a['k']}/"

    # Vor dem ersten Abruf: Die Pipeline erreicht laut --ziele nur den Testserver (die Netzsperre aus
    # conftest gilt nur im Testprozess, nicht im Pipeline-Prozess)
    r = _pipeline("laden", "--config", str(a["config"]), "--ziele", env=_umgebung(tmp_path))
    assert r.returncode == 0 and r.stdout.split() == [dienst.basis.removeprefix("http://")], \
        (r.stdout, r.stderr)
    _einrichten(a, tmp_path)

    # Lauf 1: alles neu
    rc, b, text = _lauf(a, tmp_path)
    assert rc == 0, text
    assert (b["fehlgeschlagen"], b["angehalten"], b["unvollstaendig"]) == ([], [], []), b
    assert _zahlen(b, a["wfs"]) == (3, 0, 0, 0, 0), _quelle(b, a["wfs"])
    assert _zahlen(b, a["csv"]) == (9, 0, 0, 0, 0), _quelle(b, a["csv"])
    assert _zahlen(b, a["xlsx"]) == (32, 0, 0, 0, 0), _quelle(b, a["xlsx"])
    for name in (a["wfs"], a["csv"], a["xlsx"]):
        q = _quelle(b, name)
        assert q["status"] == "ok" and not q["unvollstaendig"] and "uebersprungen" not in q, q
        # robots.txt: weder Sperre noch Freigabe (127.0.0.1 steht nicht in ROBOTS_GESPERRT)
        assert "robots_freigabe" not in q["info"] and not any("robots" in w for w in q["warnungen"]), q
    wfs = _quelle(b, a["wfs"])
    # Was der Dienst über sich sagt, steht im Bericht; Felder am Schema geprüft, ohne Warnung
    assert wfs["info"]["kontakt"] == {"anbieter": "Testanbieter (erfunden)",
                                      "email": "dienst@anbieter.example"}
    assert wfs["warnungen"] == [] and "schema_ungeprueft" not in wfs["info"], wfs
    assert "Dienst meldet ImplementsResultPaging=FALSE, Abruf per Kachelung" in wfs["hinweise"]
    # Die Kennzahlen der CSV hängen über den AGS an den eben geladenen Gemeinden (Antwort 28); die aufgelöste
    # Gemeinde mit „-“ ist ausgelassen (leere_auslassen) und hat keine Fläche
    csv = _quelle(b, a["csv"])
    assert csv["info"]["gebiete"] == {"schluessel": 3, "mit_flaeche": 3, "tabelle": GEMEINDEN}, csv["info"]
    assert any(f"ihr bisheriger Stand bleibt: {a['ags'][3]}|" in w for w in csv["warnungen"]), \
        csv["warnungen"]
    # Katalog von MOSIDI nach dem Lauf, gleichzeitig dank eindeutigem Index (E52); die neuen Indikatoren
    # stehen in der View
    assert b["katalog"] == {"view": "public.source_granularities", "ergebnis": "aktualisiert",
                            "verfahren": "gleichzeitig"}, b["katalog"]
    assert _abfrage("SELECT count(*) FROM public.source_granularities WHERE source = ANY(%s)",
                    [a["csv"], a["xlsx"]]) == [(4,)]
    # Textbericht: Datei gleich der Ausgabe auf stdout, je Quelle eine Ergebniszeile
    assert (tmp_path / "berichte" / f"{b['lauf_id']}.txt").read_text(encoding="utf-8") == text
    for name, neu in ((a["wfs"], 3), (a["csv"], 9), (a["xlsx"], 32)):
        assert re.search(rf"{name}\s+ok\s+neu\s+{neu}\s+geändert\s+0\s+gelöscht\s+0\s+unverändert\s+0\b",
                         text), text

    # pipeline_meta: Lauf, je Quelle, jede neue Zeile im Änderungsprotokoll, Register und Vergleichsstand
    p = _protokoll(b["lauf_id"])
    assert p["kopf"] == [(3, 0, 0, 0, f"{b['lauf_id']}.json")], p
    assert p["quellen"] == {a["wfs"]: ("ok", 3, 0, 0, 0, 0), a["csv"]: ("ok", 9, 0, 0, 0, 0),
                            a["xlsx"]: ("ok", 32, 0, 0, 0, 0)}, p
    assert p["aenderungen"] == {(a["wfs"], "neu"): 3, (a["csv"], "neu"): 9, (a["xlsx"], "neu"): 32}, p
    assert dict(_abfrage("SELECT quelle, count(*) FROM pipeline_meta.bestand WHERE quelle = ANY(%s) "
                         "GROUP BY 1", [a["wfs"], a["csv"], a["xlsx"]])) == {a["wfs"]: 3, a["csv"]: 9,
                                                                             a["xlsx"]: 32}
    assert dict(_abfrage("SELECT quelle, datei_sha256 FROM pipeline_meta.quellenstand WHERE quelle = ANY(%s)",
                         [a["wfs"], a["csv"], a["xlsx"]])) == {a["wfs"]: None, a["csv"]: a["csv_sha"],
                                                               a["xlsx"]: a["xlsx_sha"]}

    # Zieltabellen: Gemeinden mit AGS als id und nationalco, in EPSG:4326 als MULTIPOLYGON, je 1 km² (das
    # Quadrat aus EPSG:25833, auf dem Ellipsoid gerechnet: die Umrechnung stimmt)
    assert _abfrage(f'SELECT id, nationalco, name, ST_SRID(geom), GeometryType(geom), ST_IsValid(geom), '
                    f'round(CAST(ST_Area(CAST(geom AS geography)) / 1e6 AS numeric), 2) FROM "{GEMEINDEN}" '
                    f"WHERE nationalco = ANY(%s) ORDER BY nationalco", a["ags"]) == [
        (Decimal(g), g, f"Testgemeinde {i + 1}", 4326, "MULTIPOLYGON", True, Decimal("1.00"))
        for i, g in enumerate(a["ags"][:3])]
    zeilen = _abfrage("SELECT kennziffer, indikator, zeitbezug, wert FROM dashboard_data_de "
                      "WHERE source = %s", a["csv"])
    insgesamt, maennlich, weiblich = a["indikatoren"][a["csv"]]
    assert len(zeilen) == 9 and {z[0] for z in zeilen} == set(a["ags"][:3]), zeilen
    assert (a["ags"][0], insgesamt, 2025, Decimal(50000)) in zeilen
    assert (a["ags"][2], weiblich, 2025, Decimal(260)) in zeilen
    assert _abfrage("SELECT count(*), min(zeitbezug), max(zeitbezug) FROM dashboard_data_de "
                    "WHERE source = %s", a["xlsx"]) == [(32, 2025, 2025)]
    assert _abfrage("SELECT wert FROM dashboard_data_de WHERE source = %s AND kennziffer = '12054000'",
                    a["xlsx"]) == [(Decimal(180000),)]
    # table_metadata: je Indikator eine Zeile mit Herausgeber (source), Raumebene und Zeitraum, die Gemeinden
    # je Tabelle (dcat_ap_id gibt es im mitgelieferten Schema nicht, erst das Skript von MOSIDI legt sie an)
    indikatoren = a["indikatoren"][a["csv"]] + a["indikatoren"][a["xlsx"]]
    assert _abfrage("SELECT table_name, dct_catalog_publisher, dcatde_politicalgeocodingleveluri, "
                    "dct_type, extract(year FROM dct_temporal_startdata) FROM table_metadata "
                    "WHERE table_name = ANY(%s) ORDER BY 1", indikatoren) == sorted(
        (i, src, "Gemeindeebene", "indikator", Decimal(2025))
        for src in (a["csv"], a["xlsx"]) for i in a["indikatoren"][src])
    assert _abfrage("SELECT dct_identifier, dct_accessurl FROM table_metadata WHERE table_name = %s",
                    GEMEINDEN) == [(a["wfs"], dienst.basis + praefix + "ows/vg_wfs")]

    # Lauf 2 mit --alle (der Rhythmus der ausgelieferten Konfiguration wäre noch nicht abgelaufen)
    rc, b2, text2 = _lauf(a, tmp_path, "--alle")
    _unveraendert_pruefen(a, rc, b2, text2)
    assert "unverändert (Datei byte-gleich" in (tmp_path / "berichte" / f"{b2['lauf_id']}.txt").read_text(
        encoding="utf-8")

    # Jede Anfrage beim Server war eine erwartete: je Lauf die drei Abfragen des WFS und je eine für CSV und
    # XLSX; das XLSX im zweiten Lauf mit If-Modified-Since und 304. Kein /robots.txt, keine 404
    anfragen = dienst.unter(praefix)
    assert [(x["pfad"], x["request"], x["status"]) for x in anfragen] == \
        _erwartete_anfragen(praefix, 200) + _erwartete_anfragen(praefix, 304), anfragen
    assert not [x for x in dienst.unter("/") if x["status"] == 404 or x["pfad"] == "/robots.txt"]
    holen = [x["params"] for x in anfragen if x["request"] == "GetFeature"]
    assert len(holen) == 2 and all(
        (h["TYPENAMES"], h["SRSNAME"], h["BBOX"]) == ("app:gem", CRS, f"250000,5690000,480000,5940000,{CRS}")
        for h in holen), holen
    xlsx = [x for x in anfragen if x["pfad"].endswith(".xlsx")]
    assert [(x["seit"], x["status"]) for x in xlsx] == [(None, 200), (STAND, 304)], xlsx
    assert all(x["kennung"].startswith("geodaten-import-pipeline") for x in anfragen), anfragen


# --- Wiederherstellungsprobe ------------------------------------------------------------------------------

def _compose(befehl: str, eingabe: bytes | None = None, timeout: int = 300) -> subprocess.CompletedProcess:
    """`docker compose exec -T db sh -c <befehl>` im Wurzelverzeichnis (Projekt aus COMPOSE_PROJECT_NAME,
    sonst wie in der CI das Verzeichnis), mit `eingabe` auf stdin; Ausgabe als Bytes. Die Shell im Container
    setzt $POSTGRES_USER und $POSTGRES_DB ein, wie in den Befehlen von docs/betrieb.md."""
    docker = shutil.which("docker")
    assert docker, "docker nicht gefunden"
    # Fester Befehl aus diesem Test; docker über den vollen Pfad (shutil.which)
    return subprocess.run([docker, "compose", "exec", "-T", "db", "sh", "-c", befehl],  # noqa: S603
                          cwd=WURZEL, input=eingabe, capture_output=True, timeout=timeout, check=False)


@pytest.fixture
def container():
    """Der Datenbank-Container aus docker-compose.yml, der zu PGHOST/PGPORT gehört: Beide melden denselben
    system_identifier des Servers. Ohne docker oder Container wird übersprungen, in der CI (CI gesetzt)
    scheitert der Test stattdessen, damit die Probe dort nie still entfällt. Ein Container eines anderen
    Servers bricht immer ab (COMPOSE_PROJECT_NAME prüfen)."""
    fehlt = pytest.fail if os.environ.get("CI") else pytest.skip
    if not shutil.which("docker"):
        fehlt("Wiederherstellungsprobe braucht docker compose (Container db aus docker-compose.yml)")
    r = _compose('psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc '
                 '"SELECT system_identifier FROM pg_control_system()"', timeout=60)
    if r.returncode != 0:
        fehlt(f"Container db nicht erreichbar: {r.stderr.decode(errors='replace')[:300]}")
    ((kennung,),) = _abfrage("SELECT system_identifier FROM pg_control_system()")
    assert r.stdout.decode().strip() == str(kennung), (
        "Container db gehört zu einem anderen Server als PGHOST/PGPORT; COMPOSE_PROJECT_NAME setzen")


def test_wiederherstellung_aus_pg_dump_meldet_alles_unveraendert(tmp_path, dienst, katalog, container):
    """Sicherung und Wiederherstellung wie in docs/betrieb.md: nach einem Lauf die ganze Datenbank mit pg_dump
    (Format custom) sichern, in eine leere Datenbank (createdb -T template0) mit pg_restore --exit-on-error
    zurückspielen, einrichten, dann ein Lauf gegen die Rücksicherung. Er meldet alles unverändert, nichts
    übernommen, die Dateiquellen werden anhand des Vergleichsstands in pipeline_meta übersprungen, und sein
    Protokoll landet in der Rücksicherung, nicht im Original. Gegenstück: dieselbe Sicherung ohne
    pipeline_meta (pg_restore -N) zählt alle Zeilen als übernommen und vergleicht die Dateien voll, wie
    betrieb.md sagt („sonst gelten nach einer Rücksicherung alle Zeilen als fremd“).

    Rollen gehören zum Server und stehen nicht in der Sicherung; hier gibt es sie schon (derselbe Server).
    Auf einem neuen Server legt einrichten sie vor dem Zurückspielen an (docs/betrieb.md)."""
    a = _aufbauen(tmp_path, dienst)
    _einrichten(a, tmp_path)
    rc, b, text = _lauf(a, tmp_path)
    assert rc == 0 and b["katalog"]["ergebnis"] == "aktualisiert", text

    # Sicherung mit dem Befehl aus docs/betrieb.md (zeitlich nach dem Lauf); Format custom beginnt mit PGDMP
    r = _compose('pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"')
    assert r.returncode == 0 and r.stdout.startswith(b"PGDMP"), r.stderr
    sicherung = tmp_path / "sicherung.dump"
    sicherung.write_bytes(r.stdout)

    voll, ohne_meta = f"probe_{a['k']}", f"probe_{a['k']}_ohne_meta"
    try:
        for db, auswahl in ((voll, ""), (ohne_meta, " -N pipeline_meta")):
            # Leere Datenbank aus template0 (ohne PostGIS und ohne die Bestandstabellen), dann zurückspielen;
            # jeder Fehler bricht ab, nichts wird überdeckt
            r = _compose(f'createdb -U "$POSTGRES_USER" -T template0 {db}')
            assert r.returncode == 0, r.stderr
            r = _compose(f'pg_restore -U "$POSTGRES_USER" -d {db} --exit-on-error{auswahl}',
                         eingabe=sicherung.read_bytes())
            assert r.returncode == 0, r.stderr.decode(errors="replace")
            _einrichten(a, tmp_path, datenbank=db)

        # Mit pipeline_meta: alles unverändert wie ein Folgelauf auf dem Original
        rc, b2, text2 = _lauf(a, tmp_path, "--alle", datenbank=voll)
        _unveraendert_pruefen(a, rc, b2, text2, datenbank=voll)
        # Die Rücksicherung kennt den Lauf vor der Sicherung und den neuen; das Original nur den alten
        assert _abfrage("SELECT lauf_id FROM pipeline_meta.lauf WHERE lauf_id = ANY(%s) ORDER BY 1",
                        [b["lauf_id"], b2["lauf_id"]], datenbank=voll) == [(b["lauf_id"],), (b2["lauf_id"],)]
        assert _abfrage("SELECT count(*) FROM pipeline_meta.lauf WHERE lauf_id = %s", b2["lauf_id"]) == [(0,)]
        # Raumdaten, Kennzahlen und Register sind dieselben wie im Original
        zaehlung = (f'SELECT (SELECT count(*) FROM "{GEMEINDEN}" WHERE nationalco = ANY(%s)), '
                    "(SELECT count(*) FROM dashboard_data_de WHERE source = ANY(%s)), "
                    "(SELECT count(*) FROM pipeline_meta.bestand WHERE quelle = ANY(%s))")
        werte = (a["ags"], [a["csv"], a["xlsx"]], [a["wfs"], a["csv"], a["xlsx"]])
        assert _abfrage(zaehlung, *werte, datenbank=voll) == _abfrage(zaehlung, *werte) == [(3, 41, 44)]

        # Ohne pipeline_meta: dieselben Zeilen, aber kein Register und kein Vergleichsstand. Alles gilt als
        # fremd und wird übernommen, die Dateien werden voll gelesen und verglichen
        rc, b3, text3 = _lauf(a, tmp_path, "--alle", datenbank=ohne_meta)
        assert rc == 0, text3
        for name, n in ((a["wfs"], 3), (a["csv"], 9), (a["xlsx"], 32)):
            assert _zahlen(b3, name) == (0, 0, 0, n, n), _quelle(b3, name)
            assert "uebersprungen" not in _quelle(b3, name)
    finally:
        # Beide Probedatenbanken entfernen, auch wenn der Test vorher scheiterte (FORCE trennt offene
        # Verbindungen); das Original bleibt
        _ausfuehren(*(f'DROP DATABASE IF EXISTS "{db}" WITH (FORCE)' for db in (voll, ohne_meta)))
