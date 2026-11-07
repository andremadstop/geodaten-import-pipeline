"""Tests gegen eine echte PostgreSQL/PostGIS-Datenbank mit den Bestandstabellen von MOSIDI
(sql/mosidi/001_bestand.sql). Sie sichern den letzten Schritt des Ablaufs laden → quellen → ziel ab: was
pipeline.laden mit den Objekten der Adapter in der Datenbank tut, und welche Rollen und Rechte
pipeline.einrichten setzt. Abgesichert sind vor allem:

- Vergleich und Abgleich je Zeile mit Bestandsregister; fremde Zeilen und von MOSIDI selbst gefüllte
  Spalten bleiben, übernommene Zeilen zählen fachlich (E3, E22, E23, E46);
- Löschsperre bei unvollständigem Abruf, Rückgang-Schutz, Rollback nur der fehlerhaften Quelle
  (E4, E7, E23, E32);
- unlesbare, ungültige oder nicht in den Zieltyp umwandelbare Geometrien je Objekt (E33, E38, E46);
- zu lange Texte werden zurückgehalten statt gekürzt, zu lange Schlüssel halten die Quelle an (E32, E47);
- Kennzahlen in dashboard_data_de, stabiler INKAR-Schlüssel, Zählung nach dem Quellschlüssel (E27, E40,
  E42), table_metadata je Tabelle oder Indikator, auch gleichnamige Indikatoren verschiedener Quellen
  (E38, E46);
- Rhythmus und Wiederholung nach einer Lücke, Protokoll in pipeline_meta, Abriss der Verbindung,
  Katalog-View und datenbankweite Sperre (E24, E34, E38, E44, E45, E46);
- Rollen nach geringsten Rechten, Sollstand der Schreibrechte, zu weite vorhandene Rollen
  (E10, E35, E39, E46, E47);
- Statistische Berichte des Amts für Statistik als XLSX über die mitgelieferte Konfiguration (E48);
- der Nachweis, dass das Schema der Bestandstabellen unverändert bleibt.

Laufen nur, wenn DATENBANK_TEST=1 gesetzt ist und die Datenbank aus docker-compose.yml läuft
(in der CI ein eigener Job, lokal z. B. mit PG_PORT=55433):

    PG_PORT=55433 docker compose up -d db
    set -a; . ./.env; set +a
    DATENBANK_TEST=1 PGHOST=127.0.0.1 PGPORT=55433 PGDATABASE=geodaten \\
      uv run … python -m pytest tests/test_datenbank.py

Die Tests richten Rollen und Rechte selbst ein (pipeline.einrichten, als Administrator aus
POSTGRES_USER/POSTGRES_PASSWORD). Jeder Test nutzt eigene Quellnamen und Schlüssel (zufällige Endungen
aus uuid4), die Tests stören sich also nicht gegenseitig. Alle Eingabedaten sind erfunden und entstehen
im tmp_path des Tests (Antwort 69: keine Quelldaten im Repository).
"""
import json
import os
import time
import uuid
from datetime import UTC
from decimal import Decimal
from pathlib import Path

import pytest

# Ohne DATENBANK_TEST=1 wird das ganze Modul übersprungen; `pytest` läuft so auch ohne Datenbank.
pytestmark = pytest.mark.skipif(os.environ.get("DATENBANK_TEST") != "1",
                                reason="nur mit DATENBANK_TEST=1 und laufender Datenbank")

# psycopg und PyYAML braucht nur dieser Testblock: fehlen sie, wird übersprungen statt abgebrochen.
psycopg = pytest.importorskip("psycopg")
yaml = pytest.importorskip("yaml")

# Erst nach importorskip: pipeline.einrichten importiert psycopg auf Modulebene.
from pipeline import betrieb, einrichten, laden, ziel  # noqa: E402

KONFIG = Path(__file__).resolve().parent.parent / "config" / "quellen.yaml"


def _admin():
    """Verbindung als Administrator (POSTGRES_USER/POSTGRES_PASSWORD) mit autocommit, für Vorbereitung,
    Aufräumen und Abfragen am Testende; Rechner, Port und Datenbank kommen wie bei libpq aus PGHOST, PGPORT
    und PGDATABASE."""
    return psycopg.connect("", user=os.environ.get("POSTGRES_USER", "admin"),
                           password=os.environ["POSTGRES_PASSWORD"], autocommit=True)


def _als(rolle: str, umgebung: str):
    """Verbindung als Rolle `rolle` mit dem Passwort aus der Umgebungsvariablen `umgebung`, ohne autocommit;
    für die Prüfung, was diese Rolle darf."""
    return psycopg.connect("", user=rolle, password=os.environ[umgebung])


# Ziele, wie sie in config/quellen.yaml stehen könnten; die Tests nutzen Bestandstabellen von
# MOSIDI, die im Betrieb niemand aus dieser Pipeline füllt ("Baume") oder die die Pipeline füllt
GEBAEUDE = {"tabelle": "Gebäude (ALKIS)", "schluessel": ["oid"], "geometrie": "geom",
            "spalten": {"oid": "_id", "name": "name"}, "metadaten": {"je": "tabelle"}}
BAEUME = {"tabelle": "Baume", "schluessel": ["species"], "geometrie": "geom",
          "spalten": {"species": "_id", "leaf_type": "name"}, "metadaten": {"je": "tabelle"}}
GEMEINDEN = "Kommunale Gebiete Brandenburg (InNoWest)"


def _kennzahlen(source: str) -> dict:
    """Ziel dashboard_data_de für eine Kennzahlquelle im Breitformat: Spalte bev wird zum Indikator
    „Bevölkerung <source>“, abgegrenzt über `source`, die Gemeinde hängt über den AGS an GEMEINDEN (Antwort
    28), table_metadata je Indikator."""
    return {"tabelle": "dashboard_data_de", "schluessel": ["kennziffer", "indikator", "zeitbezug"],
            "spalten": {"indikator": "_indikator", "kennziffer": "_gebiet", "wert": "_wert",
                        "zeitbezug": "_jahr"},
            "fest": {"source": source, "granularity": "Gemeinden"},
            "je_wert": {"bev": f"Bevölkerung {source}"},
            "gebiet": {"tabelle": GEMEINDEN, "spalte": "nationalco", "zielspalte": "kennziffer",
                       "geometrie": "geom"},
            "metadaten": {"je": "indikator"}}


def _statistik_csv() -> dict:
    """Statistiktabelle im CSV-Aufbau mit Kopf- und Fußblock (Stichtag im Kopf, Spalten nach Position, drei
    Werte je Gemeinde). So war bis E47 die Quelle bevoelkerung_gemeinden konfiguriert (Regionaldatenbank);
    seit E48 liest sie das XLSX des Amts für Statistik, die Prüfungen des CSV-Typs (E42, E47) gelten weiter
    und werden mit dieser Konfiguration geprüft. Ziel wie in config/quellen.yaml, mit drei Indikatoren."""
    z = yaml.safe_load(KONFIG.read_text(encoding="utf-8"))["quellen"]["bevoelkerung_gemeinden"]["ziel"]
    z = {**z, "je_wert": {"bevoelkerung": "Bevölkerung insgesamt (Stichtag 31.12.)",
                          "bevoelkerung_m": "Bevölkerung männlich (Stichtag 31.12.)",
                          "bevoelkerung_w": "Bevölkerung weiblich (Stichtag 31.12.)"}}
    return {"typ": "csv", "encoding": "latin-1", "trenner": ";", "zeilen_muster": r"^12\d{6};",
            "schluessel_form": r"^(DG|\d+)$",
            "spalten_namen": ["ags", "name", "insgesamt", "maennlich", "weiblich"],
            "id_spalte": "ags",
            "spalten": {"name": "name", "insgesamt": "bevoelkerung", "maennlich": "bevoelkerung_m",
                        "weiblich": "bevoelkerung_w"},
            "zahl_felder": ["bevoelkerung", "bevoelkerung_m", "bevoelkerung_w"],
            "zeitbezug": {"zeile": 7, "spalte": 3},
            "kopf_pruefen": {"zeile": 8, "erwartet": ["", "", "Insgesamt", "männlich", "weiblich"]},
            "leere_auslassen": True, "gebiet": {"schluessel_spalte": "ags"}, "lizenz": "Testdaten",
            "ziel": z}


def _voll() -> dict:
    """Mitgelieferte Konfiguration plus die Ziele der Tests. Seit E46 setzt einrichten die Schreibrechte auf
    den Sollstand der übergebenen Konfiguration zurück; jedes einrichten in den Tests nutzt deshalb diese
    Gesamtheit, sonst verlören die übrigen Tests ihre Rechte."""
    cfg = yaml.safe_load(KONFIG.read_text(encoding="utf-8"))
    for i, z in enumerate([GEBAEUDE, BAEUME, _kennzahlen("x")]):
        cfg["quellen"][f"_test_{i}"] = {"typ": "csv", "ziel": z}
    return cfg


@pytest.fixture(scope="module", autouse=True)
def eingerichtet():
    """Einmal je Modul: richtet als Administrator Rollen und Rechte für die Ziele der Tests und der
    mitgelieferten Konfiguration ein (_voll). Seiteneffekt: legt pipeline_import und mosidi_lesen an oder
    setzt sie auf den Sollstand, schreibt pipeline_meta."""
    cfg = _voll()
    with _admin() as c:
        einrichten.einrichten(c, cfg)
        # Der zweite Aufruf belegt, dass einrichten wiederholbar ist und dabei nicht abbricht
        einrichten.einrichten(c, cfg)  # beliebig oft ausführbar


@pytest.fixture
def als_import(monkeypatch):
    """Die Pipeline läuft wie im Betrieb mit der Importrolle: PGUSER/PGPASSWORD auf pipeline_import, nur für
    die Dauer des Tests (monkeypatch)."""
    monkeypatch.setenv("PGUSER", "pipeline_import")
    monkeypatch.setenv("PGPASSWORD", os.environ["IMPORT_PASSWORD"])
    # laden verbindet mit DATABASE_URL, wenn gesetzt; eine Adresse aus der Umgebung könnte Benutzer und
    # Passwort mitbringen und die Importrolle aushebeln
    monkeypatch.delenv("DATABASE_URL", raising=False)


def _punkte(pfad: Path, zeilen: list[tuple[str, str, float, float]]) -> None:
    """Schreibt eine Punkt-CSV (id, name, lat, lon). Leere Koordinaten ergeben eine Zeile ohne gültige
    Geometrie; die Tests machen so einen Abruf unvollständig."""
    pfad.write_text("id,name,lat,lon\n" + "".join(f"{i},{n},{la},{lo}\n" for i, n, la, lo in zeilen),
                    encoding="utf-8")


def _flaechen(pfad: Path, zeilen: list[tuple[str, str, float, float]]) -> None:
    """Schreibt eine Flächen-CSV (id, name, wkt): je Zeile ein Quadrat von 0,001 Grad Kantenlänge, dessen
    südwestliche Ecke im Punkt (lat, lon) liegt."""
    pfad.write_text("id,name,wkt\n" + "".join(
        f'{i},{n},"POLYGON(({x} {y},{x + .001} {y},{x + .001} {y + .001},{x} {y + .001},{x} {y}))"\n'
        for i, n, y, x in zeilen), encoding="utf-8")


def _config(tmp: Path, quellen: dict) -> Path:
    """Schreibt eine eigene quellen.yaml in `tmp` mit den übergebenen Quellen und dem Berichtsordner
    tmp/berichte; Rückgabe ist der Pfad der Datei."""
    datei = tmp / "quellen.yaml"
    datei.write_text(yaml.safe_dump({"berichte": str(tmp / "berichte"), "quellen": quellen},
                                    allow_unicode=True), encoding="utf-8")
    return datei


def _punkt_quelle(pfad: Path, ziel: dict = BAEUME, **kw) -> dict:
    """CSV-Punktquelle in WGS84 (x = lon, y = lat) mit Ziel `ziel` (Standard BAEUME); kw ergänzt oder ersetzt
    Schlüssel der Quelle."""
    return {"typ": "csv", "pfad": str(pfad), "id_spalte": "id", "x_spalte": "lon", "y_spalte": "lat",
            "srid": 4326, "spalten": {"name": "name"}, "lizenz": "Testdaten", "ziel": ziel, **kw}


def _flaechen_quelle(pfad: Path, **kw) -> dict:
    """CSV-Flächenquelle mit WKT in WGS84 und Ziel GEBAEUDE; kw ergänzt oder ersetzt Schlüssel der Quelle,
    auch `ziel`."""
    return {"typ": "csv", "pfad": str(pfad), "id_spalte": "id", "wkt_spalte": "wkt", "srid": 4326,
            "spalten": {"name": "name"}, "lizenz": "Testdaten", "ziel": GEBAEUDE, **kw}


def _lauf(config: Path, **kw) -> dict:
    """Ein Lauf über laden.lauf mit der Konfiguration `config` (Schreiben in die Datenbank, Berichte in deren
    Berichtsordner); kw wie dort (nur, probelauf, alle). Rückgabe: der Bericht."""
    time.sleep(1.1)  # Lauf-IDs sind sekundengenau
    return laden.lauf(str(config), **kw)


def _quelle(bericht: dict, name: str) -> dict:
    """Eintrag der Quelle `name` im Bericht eines Laufs (StopIteration, wenn er fehlt)."""
    return next(q for q in bericht["quellen"] if q["quelle"] == name)


def _zahlen(bericht: dict, name: str) -> tuple:
    """Zähler der Quelle `name` als (neu, geaendert, geloescht, unveraendert)."""
    z = _quelle(bericht, name)["zaehler"]
    return z["neu"], z["geaendert"], z["geloescht"], z["unveraendert"]


def _abfrage(text: str, *werte):
    """Führt `text` mit den Parametern `werte` als Administrator aus und gibt alle Zeilen zurück; `text` darf
    auch ein Baustein aus psycopg.sql sein."""
    with _admin() as c:
        return c.execute(text, werte).fetchall()


def test_vergleichen_und_abgleichen(tmp_path, als_import):
    """Abgleich über die Objekt-ID (E3, E23): Der Erstlauf legt alles neu an, ein Folgelauf ohne Änderung
    zählt nur unverändert, Umbenennung, Wegfall und Zugang werden als geändert, gelöscht und neu geschrieben
    und je Lauf, Quelle und Änderung in pipeline_meta protokolliert."""
    name, p = f"test_{uuid.uuid4().hex[:8]}", uuid.uuid4().hex[:6]
    daten = tmp_path / "daten.csv"
    cfg = _config(tmp_path, {name: _punkt_quelle(daten)})
    _punkte(daten, [(f"{p}a", "Alpha", 52.41, 12.54), (f"{p}b", "Beta", 52.40, 12.53),
                    (f"{p}c", "Gamma", 52.39, 12.52)])
    assert _zahlen(_lauf(cfg), name) == (3, 0, 0, 0)
    assert _zahlen(_lauf(cfg), name) == (0, 0, 0, 3)

    # b umbenannt, c entfällt, d kommt dazu
    _punkte(daten, [(f"{p}a", "Alpha", 52.41, 12.54), (f"{p}b", "Beta neu", 52.40, 12.53),
                    (f"{p}d", "Delta", 52.38, 12.51)])
    b = _lauf(cfg)
    assert _zahlen(b, name) == (1, 1, 1, 1)
    zeilen = _abfrage('SELECT species, leaf_type, ST_SRID(geom) FROM "Baume" WHERE species LIKE %s '
                      "ORDER BY species", f"{p}%")
    assert zeilen == [(f"{p}a", "Alpha", 4326), (f"{p}b", "Beta neu", 4326), (f"{p}d", "Delta", 4326)]
    # Protokoll je Lauf und Quelle, und je Änderung
    assert _abfrage("SELECT neu, geaendert, entfernt, unveraendert, status FROM pipeline_meta.quellenlauf "
                    "WHERE lauf_id = %s AND quelle = %s", b["lauf_id"], name) == [(1, 1, 1, 1, "ok")]
    arten = _abfrage("SELECT art, schluessel ->> 0 FROM pipeline_meta.aenderung WHERE lauf_id = %s "
                     "AND quelle = %s ORDER BY 1", b["lauf_id"], name)
    assert arten == [("entfernt", f"{p}c"), ("geaendert", f"{p}b"), ("neu", f"{p}d")]
    assert _abfrage("SELECT quellen FROM pipeline_meta.lauf WHERE lauf_id = %s", b["lauf_id"]) == [(1,)]


def test_fremde_zeilen_und_mosidi_spalten_bleiben(tmp_path, als_import):
    """Zeilen, die nicht von der Pipeline stammen, bleiben; eine schon vorhandene Zeile mit gleichem
    Schlüssel wird übernommen, nicht verdoppelt; Spalten, die MOSIDI selbst füllt, bleiben stehen.
    Übernommene Zeilen zählen fachlich (Antwort 62, Prüfbericht 05.11., F3, E46): a mit anderem Namen
    als geändert, g mit gleichen Werten als unverändert, beide zusätzlich als übernommen. Bis E45 zählte
    a nur als übernommen, die Änderung „alt“ → „Haus A“ fehlte unter geändert."""
    name, p = f"test_{uuid.uuid4().hex[:8]}", uuid.uuid4().hex[:6]
    daten = tmp_path / "gebaeude.csv"
    _flaechen(daten, [(f"{p}g", "Haus G", 52.38, 12.51)])
    wkt_g = daten.read_text(encoding="utf-8").splitlines()[1].split(",", 2)[2].strip('"')
    with _admin() as c:
        c.execute("""INSERT INTO "Gebäude (ALKIS)" (oid, name, flood_risk, geom) VALUES
                     (%s, 'fremd', 'hoch', ST_Multi(ST_GeomFromText(
                         'POLYGON((12 52,12.001 52,12.001 52.001,12 52))', 4326))),
                     (%s, 'alt', 'mittel', NULL),
                     (%s, 'Haus G', 'gering', ST_Multi(ST_GeomFromText(%s, 4326)))""",
                  (f"{p}fremd", f"{p}a", f"{p}g", wkt_g))
    cfg = _config(tmp_path, {name: _flaechen_quelle(daten)})
    _flaechen(daten, [(f"{p}a", "Haus A", 52.41, 12.54), (f"{p}b", "Haus B", 52.40, 12.53),
                      (f"{p}g", "Haus G", 52.38, 12.51)])
    b = _lauf(cfg)
    q = _quelle(b, name)
    assert _zahlen(b, name) == (1, 1, 0, 1)
    assert (q["zaehler"]["uebernommen"], q["zaehler"]["uebernommen_geaendert"]) == (2, 1)
    assert any("2 Zeilen gab es" in h and "1 mit abweichenden Werten" in h and "1 unverändert" in h
               for h in q["hinweise"])
    assert _abfrage("SELECT art, schluessel ->> 0 FROM pipeline_meta.aenderung WHERE lauf_id = %s "
                    "AND quelle = %s ORDER BY 2", b["lauf_id"], name) == [
        ("uebernommen_geaendert", f"{p}a"), ("neu", f"{p}b"), ("uebernommen", f"{p}g")]
    assert _abfrage("SELECT neu, geaendert, unveraendert, uebernommen FROM pipeline_meta.quellenlauf "
                    "WHERE lauf_id = %s AND quelle = %s", b["lauf_id"], name) == [(1, 1, 1, 2)]
    zeilen = _abfrage('SELECT oid, name, flood_risk, GeometryType(geom) FROM "Gebäude (ALKIS)" '
                      "WHERE oid LIKE %s ORDER BY oid", f"{p}%")
    assert zeilen == [(f"{p}a", "Haus A", "mittel", "MULTIPOLYGON"),
                      (f"{p}b", "Haus B", None, "MULTIPOLYGON"),
                      (f"{p}fremd", "fremd", "hoch", "MULTIPOLYGON"),
                      (f"{p}g", "Haus G", "gering", "MULTIPOLYGON")]

    # a entfällt in der Quelle: a war übernommen, gehört jetzt zur Quelle und wird gelöscht; fremd bleibt
    _flaechen(daten, [(f"{p}b", "Haus B", 52.40, 12.53), (f"{p}c", "Haus C", 52.39, 12.52),
                      (f"{p}g", "Haus G", 52.38, 12.51)])
    assert _zahlen(_lauf(cfg), name) == (1, 0, 1, 2)
    assert [r[0] for r in _abfrage('SELECT oid FROM "Gebäude (ALKIS)" WHERE oid LIKE %s ORDER BY oid',
                                   f"{p}%")] == [f"{p}b", f"{p}c", f"{p}fremd", f"{p}g"]


def test_unvollstaendiger_abruf_loescht_nicht(tmp_path, als_import):
    """Antwort 52, E23, E32: Gelöscht wird nur bei vollständigem, fehlerfreiem Abruf. Fehlt ein Objekt in
    einem lückenhaften Abruf (hier eine Zeile ohne gültige Geometrie), bleibt es stehen und wird als
    zurückgehalten protokolliert; letzter_erfolg rückt nicht vor, und Datenbank wie Quellenverzeichnis führen
    den Lauf als unvollständig. Erst der nächste vollständige Abruf löscht und zählt als Erfolg."""
    name, p = f"test_{uuid.uuid4().hex[:8]}", uuid.uuid4().hex[:6]
    daten = tmp_path / "daten.csv"
    cfg = _config(tmp_path, {name: _punkt_quelle(daten)})
    _punkte(daten, [(f"{p}{i}", f"P{i}", 52.4 + i / 1000, 12.5) for i in range(4)])
    erster = _lauf(cfg)
    # p3 fehlt, und eine Zeile hat keine gültige Geometrie: der Abruf ist unvollständig
    _punkte(daten, [(f"{p}{i}", f"P{i}", 52.4 + i / 1000, 12.5) for i in range(3)] + [(f"{p}x", "X", "", "")])
    erfolg = _abfrage("SELECT letzter_erfolg FROM pipeline_meta.quellenstand WHERE quelle = %s", name)
    b = _lauf(cfg)
    q = _quelle(b, name)
    assert q["status"] == "ok" and q["unvollstaendig"] and b["unvollstaendig"] == [name]
    assert (q["zaehler"]["geloescht"], q["zaehler"]["zurueckgehalten"]) == (0, 1)
    # Kein Erfolg: der Rhythmus darf die Quelle nicht bis zum nächsten Termin auf diesem Stand halten
    assert _abfrage("SELECT letzter_erfolg FROM pipeline_meta.quellenstand WHERE quelle = %s",
                    name) == erfolg
    # Codex-Prüfung 05.11., B3: Datenbank (Stand und Laufprotokoll) und Quellenverzeichnis sagen dasselbe
    assert _abfrage("SELECT status FROM pipeline_meta.quellenlauf WHERE lauf_id = %s AND quelle = %s",
                    b["lauf_id"], name) == [("unvollstaendig",)]
    vz = json.loads((tmp_path / "berichte" / "quellenverzeichnis.json").read_text(encoding="utf-8"))[name]
    assert (vz["ergebnis"], vz["letzter_erfolg"], vz["letzter_lauf"]) == (
        "unvollstaendig", erster["lauf_id"], b["lauf_id"])
    assert erfolg[0][0].astimezone(UTC).strftime("%Y%m%dT%H%M%SZ") == erster["lauf_id"]
    assert _abfrage('SELECT count(*) FROM "Baume" WHERE species LIKE %s', f"{p}%") == [(4,)]
    assert _abfrage("SELECT art FROM pipeline_meta.aenderung WHERE quelle = %s AND art <> 'neu'", name) \
        == [("zurueckgehalten",)]
    # Vollständiger Abruf: jetzt wird gelöscht, und beide Seiten führen ihn als Erfolg
    _punkte(daten, [(f"{p}{i}", f"P{i}", 52.4 + i / 1000, 12.5) for i in range(3)])
    c = _lauf(cfg)
    assert _zahlen(c, name) == (0, 0, 1, 3)
    vz = json.loads((tmp_path / "berichte" / "quellenverzeichnis.json").read_text(encoding="utf-8"))[name]
    ((neu_erfolg,),) = _abfrage("SELECT letzter_erfolg FROM pipeline_meta.quellenstand WHERE quelle = %s",
                                name)
    assert (vz["ergebnis"], vz["letzter_erfolg"]) == ("ok", c["lauf_id"])
    assert neu_erfolg.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ") == c["lauf_id"]
    assert _abfrage("SELECT status FROM pipeline_meta.quellenlauf WHERE lauf_id = %s AND quelle = %s",
                    c["lauf_id"], name) == [("ok",)]


def test_rueckgang_schutz_haelt_alten_stand(tmp_path, als_import):
    """Rückgang-Schutz (E4): Liefert die Quelle über 50 % weniger Objekte als bisher (1 statt 10), wird sie
    angehalten, und der alte Stand bleibt vollständig."""
    name, p = f"test_{uuid.uuid4().hex[:8]}", uuid.uuid4().hex[:6]
    daten = tmp_path / "daten.csv"
    cfg = _config(tmp_path, {name: _punkt_quelle(daten)})
    _punkte(daten, [(f"{p}{i}", f"Punkt {i}", 52.4 + i / 1000, 12.5) for i in range(10)])
    _lauf(cfg)
    _punkte(daten, [(f"{p}0", "Punkt 0", 52.4, 12.5)])  # 1 statt 10: über 50 % weniger
    b = _lauf(cfg)
    assert _quelle(b, name)["status"] == "angehalten" and name in b["angehalten"]
    assert _abfrage('SELECT count(*) FROM "Baume" WHERE species LIKE %s', f"{p}%") == [(10,)]


def test_fehler_in_einer_quelle_rollt_nur_sie_zurueck(tmp_path, als_import):
    """Ein echter Quellfehler mitten im Schreiben: Die Quelle liefert für ein neues Objekt eine id, die
    in der Tabelle schon vergeben ist (Primärschlüssel). Das UPDATE des geänderten Objekts ist da schon
    gelaufen, das INSERT scheitert; zurückgerollt wird die ganze Quelle, die andere läuft weiter.
    (Bis E38 stand hier unlesbares WKT; das lässt die Pipeline seitdem je Objekt aus.)"""
    gut, kaputt, p = f"test_{uuid.uuid4().hex[:8]}", f"test_{uuid.uuid4().hex[:8]}", uuid.uuid4().hex[:6]
    # id ist Primärschlüssel der Gemeindetabelle: Nummern je Testlauf, damit Wiederholungen des Tests
    # nicht mit Resten früherer Läufe kollidieren
    nr = 900_000_000 + uuid.uuid4().int % 10**8
    d_gut, d_kaputt = tmp_path / "gut.csv", tmp_path / "kaputt.csv"
    gemeinden = {"tabelle": GEMEINDEN, "schluessel": ["nationalco"], "geometrie": "geom",
                 "spalten": {"id": "nr", "nationalco": "_id", "name": "name"}, "nur_einfuegen": ["id"]}
    cfg = _config(tmp_path, {kaputt: _flaechen_quelle(d_kaputt, ziel=gemeinden,
                                                      spalten={"name": "name", "nr": "nr"}),
                             gut: _punkt_quelle(d_gut)})

    def flaechen(zeilen):
        """Schreibt d_kaputt mit einer Zeile je (id, nr, name), alle mit demselben Dreieck als Geometrie."""
        d_kaputt.write_text("id,nr,name,wkt\n" + "".join(
            f'{i},{n},{name},"POLYGON((12 52,12.01 52,12.01 52.01,12 52))"\n' for i, n, name in zeilen),
            encoding="utf-8")

    _punkte(d_gut, [(f"{p}a", "Alpha", 52.41, 12.54)])
    flaechen([(f"{p}x", nr, "Erstes"), (f"{p}y", nr + 1, "Zweites")])
    assert _quelle(_lauf(cfg), kaputt)["status"] == "ok"
    flaechen([(f"{p}x", nr, "Erstes neu"), (f"{p}y", nr + 1, "Zweites"), (f"{p}z", nr, "Drittes")])
    _punkte(d_gut, [(f"{p}a", "Alpha", 52.41, 12.54), (f"{p}b", "Beta", 52.40, 12.53)])
    b = _lauf(cfg)
    q = _quelle(b, kaputt)
    assert q["status"] == "fehler" and "UniqueViolation" in q["fehler"] and _quelle(b, gut)["status"] == "ok"
    zeilen = _abfrage(f'SELECT nationalco, name FROM "{GEMEINDEN}" WHERE nationalco LIKE %s ORDER BY 1',
                      f"{p}%")
    assert zeilen == [(f"{p}x", "Erstes"), (f"{p}y", "Zweites")]  # alter Stand vollständig erhalten, auch x
    assert _abfrage('SELECT count(*) FROM "Baume" WHERE species LIKE %s', f"{p}%") == [(2,)]
    assert _abfrage("SELECT status FROM pipeline_meta.quellenlauf WHERE lauf_id = %s AND quelle = %s",
                    b["lauf_id"], kaputt) == [("fehler",)]


def test_unlesbare_geometrie_wird_je_objekt_ausgelassen(tmp_path, als_import):
    """Codex B3 / Antwort 63: Geometrien, die PostGIS nicht lesen kann, lassen nur ihr Objekt aus, mit
    Objekt-ID und Ursache im Bericht. Der Abruf ist unvollständig: nichts wird gelöscht, der alte Stand
    der ausgelassenen Objekte bleibt; der Rest der Quelle wird übernommen."""
    name, p = f"test_{uuid.uuid4().hex[:8]}", uuid.uuid4().hex[:6]
    daten = tmp_path / "gebaeude.csv"
    cfg = _config(tmp_path, {name: _flaechen_quelle(daten)})
    _flaechen(daten, [(f"{p}{i}", f"Haus {i}", 52.40 + i / 100, 12.5) for i in range(8)])
    _lauf(cfg)
    gut = [(f"{p}{i}", f"Haus {i}", 52.40 + i / 100, 12.5) for i in range(3, 7)]
    _flaechen(daten, [(f"{p}0", "Haus 0 neu", 52.40, 12.5), *gut])   # dieselben Quadrate wie zuvor
    daten.write_text(daten.read_text(encoding="utf-8")
                     + f'{p}1,Kaputt,"POLYGON(kaputt)"\n'                        # Syntax
                     + f'{p}2,Kurz,"POLYGON((12.5 52.42,12.6 52.42,12.5 52.42))"\n',  # Ring mit 3 Punkten
                     encoding="utf-8")                                          # p7 fehlt
    b = _lauf(cfg)
    q = _quelle(b, name)
    assert q["status"] == "ok" and q["unvollstaendig"] and b["unvollstaendig"] == [name]
    warnung = next(w for w in q["warnungen"] if "nicht lesbar" in w)
    assert warnung.startswith("2 Geometrien nicht lesbar") and f"{p}1" in warnung and f"{p}2" in warnung
    assert "erster Fehler:" in warnung and q["info"]["geometrie_unlesbar"] == 2
    z = q["zaehler"]
    assert (z["geaendert"], z["geloescht"], z["zurueckgehalten"]) == (1, 0, 3)
    assert _abfrage('SELECT oid, name FROM "Gebäude (ALKIS)" WHERE oid LIKE %s ORDER BY oid', f"{p}%") == [
        (f"{p}{i}", n) for i, n in enumerate(["Haus 0 neu", "Haus 1", "Haus 2", "Haus 3", "Haus 4", "Haus 5",
                                               "Haus 6", "Haus 7"])]
    # Geometrien wieder lesbar, Abruf vollständig: jetzt wird gelöscht, was fehlt (p7)
    _flaechen(daten, [(f"{p}{i}", f"Haus {i}", 52.40 + i / 100, 12.5) for i in range(1, 7)])
    q = _quelle(_lauf(cfg), name)
    assert q["status"] == "ok" and not q["unvollstaendig"] and q["zaehler"]["geloescht"] == 2   # p0 und p7


def test_unlesbares_gml_und_geojson_je_objekt_ausgelassen(tmp_path, als_import, monkeypatch):
    """Prüfung zu E38: wie bei WKT auch für die Eingabearten GML (WFS) und GeoJSON (OGC API,
    GeoJSON-Datei). Der Adapter ist ersetzt, damit kein Dienst nötig ist; geprüft wird der Weg ab
    eingang, wie ihn die echten Adapter beliefern."""
    name, p = f"test_{uuid.uuid4().hex[:8]}", uuid.uuid4().hex[:6]

    def gml(x, y, zu=True):
        """GML-3.2-Polygon (Quadrat wie in _flaechen) als Text; zu=False lässt den Ring offen, PostGIS kann
        ihn dann nicht lesen."""
        ring = f"{x} {y} {x + .001} {y} {x + .001} {y + .001} {x} {y + .001}" + (f" {x} {y}" if zu else "")
        return ('<gml:Polygon xmlns:gml="http://www.opengis.net/gml/3.2" srsName="EPSG:4326"><gml:exterior>'
                f"<gml:LinearRing><gml:posList>{ring}</gml:posList></gml:LinearRing></gml:exterior></gml:Polygon>")

    def gj(x, y):
        """GeoJSON-Polygon (Quadrat wie in _flaechen) als Text."""
        return json.dumps({"type": "Polygon", "coordinates": [[[x, y], [x + .001, y], [x + .001, y + .001],
                                                               [x, y + .001], [x, y]]]})

    objekte = [{"objekt_id": f"{p}g", "geom": ("gml", gml(12.5, 52.40)), "werte": {"name": "GML gut"}},
               {"objekt_id": f"{p}j", "geom": ("geojson", gj(12.5, 52.41)), "werte": {"name": "GeoJSON gut"}},
               {"objekt_id": f"{p}G", "geom": ("gml", gml(12.5, 52.42, zu=False)),
                "werte": {"name": "offen"}},
               {"objekt_id": f"{p}J", "geom": ("geojson", '{"type": "Polygon", "coordinates": "kaputt"}'),
                "werte": {"name": "kaputt"}}]
    monkeypatch.setitem(laden.ADAPTER, "geojson", lambda cfg, prot: iter(objekte))
    cfg = _config(tmp_path, {name: {"typ": "geojson", "url": "https://example.invalid/test.geojson",
                                    "id_feld": "id", "spalten": {"name": "name"}, "lizenz": "Testdaten",
                                    "ziel": GEBAEUDE}})
    q = _quelle(_lauf(cfg), name)
    assert q["status"] == "ok" and q["unvollstaendig"] and q["info"]["geometrie_unlesbar"] == 2
    warnung = next(w for w in q["warnungen"] if "nicht lesbar" in w)
    assert f"{p}G" in warnung and f"{p}J" in warnung
    assert _abfrage('SELECT oid, name, round(ST_X(ST_Centroid(geom))::numeric, 4) FROM "Gebäude (ALKIS)" '
                    "WHERE oid LIKE %s ORDER BY oid", f"{p}%") == [
        (f"{p}g", "GML gut", Decimal("12.5005")), (f"{p}j", "GeoJSON gut", Decimal("12.5005"))]


def test_kennzahlen_je_quelle_in_dashboard_data_de(tmp_path, als_import):
    """Zwei Quellen schreiben in dieselbe Tabelle, getrennt über source (Antwort 27); die Gemeinde
    hängt über den AGS, nicht über einen Fremdschlüssel (Antwort 28); table_metadata je Indikator
    wie im MOSIDI-Skript."""
    k = uuid.uuid4().hex[:6]
    a, b = f"test_{k}_a", f"test_{k}_b"
    # Erfundener Gebietsschlüssel mit zufälliger Endung; er dient zugleich als id (Primärschlüssel) der
    # Gemeindetabelle
    ags = f"99{uuid.uuid4().int % 10**6:06d}"
    with _admin() as c:
        c.execute(f"""INSERT INTO "{GEMEINDEN}" (id, nationalco, name, geom) VALUES
                      (%s, %s, 'Testgemeinde', ST_Multi(ST_GeomFromText(
                       'POLYGON((12 52,12.01 52,12.01 52.01,12 52))', 4326)))""", (int(ags), ags))
    d_a, d_b = tmp_path / "a.csv", tmp_path / "b.csv"
    # 98000000 gibt es in der Gemeindetabelle nicht: die Zeile wird geladen, hat aber keine Fläche
    for d, wert in ((d_a, "100"), (d_b, "200")):
        d.write_text(f"ags;bev\n{ags};{wert}\n98000000;5\n", encoding="utf-8")

    def quelle(pfad, source):
        """CSV-Kennzahlquelle mit einem Wert je Gebietsschlüssel (Spalte bev), Rhythmus monatlich, Ziel
        _kennzahlen(source)."""
        return {"typ": "csv", "pfad": str(pfad), "trenner": ";", "id_spalte": "ags",
                "spalten": {"bev": "bev"},
                "zahl_felder": ["bev"], "zeitbezug": "2025-12-31", "gebiet": {"schluessel_spalte": "ags"},
                "lizenz": "Testdaten", "rhythmus": "monatlich", "ziel": _kennzahlen(source)}

    cfg = _config(tmp_path, {a: quelle(d_a, a), b: quelle(d_b, b)})
    bericht = _lauf(cfg)
    assert _zahlen(bericht, a) == (2, 0, 0, 0)
    assert any("1 von 2 Gebietsschlüsseln haben eine Fläche" in h for h in _quelle(bericht, a)["hinweise"])
    rows = _abfrage("SELECT source, kennziffer, indikator, wert, zeitbezug, granularity "
                    "FROM dashboard_data_de "
                    "WHERE source IN (%s, %s) AND kennziffer = %s ORDER BY source", a, b, ags)
    assert rows == [(a, ags, f"Bevölkerung {a}", 100, 2025, "Gemeinden"),
                    (b, ags, f"Bevölkerung {b}", 200, 2025, "Gemeinden")]
    meta = _abfrage("SELECT dct_catalog_publisher, dcatde_politicalgeocodingleveluri, dct_type, "
                    "extract(year FROM dct_temporal_startdata), dct_accrualperiodicity, imported IS NOT NULL "
                    "FROM table_metadata WHERE table_name = %s", f"Bevölkerung {a}")
    assert meta == [(a, "Gemeinden", "indikator", 2025,
                     "http://publications.europa.eu/resource/authority/frequency/MONTHLY", True)]

    # Quelle a verliert eine Zeile: nur a ändert sich, b bleibt unberührt
    d_a.write_text(f"ags;bev\n{ags};101\n", encoding="utf-8")
    bericht = _lauf(cfg, alle=True)
    assert _zahlen(bericht, a) == (0, 1, 1, 0) and _zahlen(bericht, b) == (0, 0, 0, 2)
    assert _abfrage("SELECT source, wert FROM dashboard_data_de WHERE source IN (%s, %s) ORDER BY 1, 2",
                    a, b) == [(a, 101), (b, 5), (b, 200)]

    # Rhythmus monatlich: der nächste Lauf ohne --alle lädt nicht
    bericht = _lauf(cfg)
    assert _quelle(bericht, a)["status"] == "nicht_faellig"
    assert _abfrage("SELECT status FROM pipeline_meta.quellenlauf WHERE lauf_id = %s AND quelle = %s",
                    bericht["lauf_id"], a) == [("nicht_faellig",)]


def test_metadaten_je_tabelle(tmp_path, als_import):
    """Mit metadaten je Tabelle legt ein Lauf genau eine Zeile in table_metadata für die Zieltabelle an, mit
    Titel, Beschreibung, Herausgeber, Lizenz, Adresse und Name der Quelle, Geometrietyp, Umriss und
    Importzeit."""
    name, p = f"test_{uuid.uuid4().hex[:8]}", uuid.uuid4().hex[:6]
    daten = tmp_path / "daten.csv"
    q = {**_punkt_quelle(daten), "titel": "Teststandorte", "beschreibung": "Drei Punkte",
         "kontakt": {"anbieter": "Testamt", "email": "test@example.org"}}
    cfg = _config(tmp_path, {name: q})
    _punkte(daten, [(f"{p}a", "Alpha", 52.41, 12.54), (f"{p}b", "Beta", 52.40, 12.53)])
    _lauf(cfg)
    zeile = _abfrage("""SELECT dct_title, dct_description, dct_catalog_publisher, dct_license, dct_accessurl,
                               dct_identifier, geometry_type, GeometryType(dct_bbox), imported IS NOT NULL,
                               (SELECT count(*) FROM table_metadata WHERE table_name = 'Baume')
                        FROM table_metadata WHERE table_name = 'Baume'""")
    assert zeile == [("Teststandorte", "Drei Punkte", "Testamt", "Testdaten", str(daten), name, "Point",
                      "POLYGON", True, 1)]


def test_probelauf_schreibt_nichts(tmp_path, als_import):
    """Ein Probelauf zählt wie ein echter Lauf, schreibt aber weder in die Zieltabelle noch in Laufprotokoll
    oder Bestandsregister."""
    name, p = f"test_{uuid.uuid4().hex[:8]}", uuid.uuid4().hex[:6]
    daten = tmp_path / "daten.csv"
    cfg = _config(tmp_path, {name: _punkt_quelle(daten)})
    _punkte(daten, [(f"{p}a", "Alpha", 52.41, 12.54)])
    assert _zahlen(_lauf(cfg, probelauf=True), name) == (1, 0, 0, 0)
    assert _abfrage('SELECT count(*) FROM "Baume" WHERE species LIKE %s', f"{p}%") == [(0,)]
    assert _abfrage("SELECT count(*) FROM pipeline_meta.quellenlauf WHERE quelle = %s", name) == [(0,)]
    assert _abfrage("SELECT count(*) FROM pipeline_meta.bestand WHERE quelle = %s", name) == [(0,)]


def test_rollen_nach_geringsten_rechten():
    """Geringste Rechte (E10): Die Importrolle darf keine Tabellen anlegen oder ändern, keine von MOSIDI
    gefüllten Spalten schreiben, nichts leeren, in Tabellen ohne Ziel nicht löschen und keine Tabelle in
    pipeline_meta entfernen; die Leserolle liest Kennzahlen und Protokoll, darf aber in table_metadata nicht
    löschen. Jeder verbotene Befehl endet mit InsufficientPrivilege."""
    with _als("pipeline_import", "IMPORT_PASSWORD") as c:
        for befehl in ("CREATE TABLE fremd (x int)",
                       'ALTER TABLE "Gebäude (ALKIS)" ADD COLUMN x int',
                       'UPDATE "Gebäude (ALKIS)" SET flood_risk = NULL',   # füllt MOSIDI selbst
                       'TRUNCATE "Gebäude (ALKIS)"',
                       'DELETE FROM "Schule"',                              # kein Ziel
                       "DROP TABLE pipeline_meta.bestand"):
            # Eigener Transaktionsblock je Befehl, nach dem erwarteten Fehler zurückgerollt: Sonst scheiterte
            # der nächste Befehl schon an der abgebrochenen Transaktion, nicht am fehlenden Recht
            with pytest.raises(psycopg.errors.InsufficientPrivilege), c.transaction():
                c.execute(befehl)
    with _als("mosidi_lesen", "LESE_PASSWORD") as c:
        assert c.execute("SELECT count(*) >= 0 FROM dashboard_data_de").fetchone()[0]
        assert c.execute("SELECT count(*) >= 0 FROM pipeline_meta.quellenlauf").fetchone()[0]
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("DELETE FROM table_metadata")


def test_passwoerter_als_scram_hash_und_plpgsql_geprueft():
    """Prüfung zu E38: einrichten sendet nur den SCRAM-Hash (die Anmeldungen der übrigen Tests
    belegen, dass er gilt), und es warnt, wenn die Importrolle plpgsql nicht nutzen darf (gehärtete
    Datenbank ohne USAGE für PUBLIC); dann scheiterte jede Geometriequelle an pg_temp.geom_lesen."""
    assert _abfrage("SELECT rolname, rolpassword LIKE 'SCRAM-SHA-256$%%' FROM pg_authid "
                    "WHERE rolname IN ('pipeline_import', 'mosidi_lesen') ORDER BY 1") == [
        ("mosidi_lesen", True), ("pipeline_import", True)]
    cfg = _voll()
    with _admin() as c:
        assert not any("plpgsql" in z for z in einrichten.einrichten(c, cfg))
        c.execute("REVOKE USAGE ON LANGUAGE plpgsql FROM PUBLIC")
        try:
            with _als("pipeline_import", "IMPORT_PASSWORD") as imp, \
                    pytest.raises(psycopg.errors.InsufficientPrivilege, match="plpgsql"):
                imp.execute(ziel.GEOM_LESEN)
            assert any("GRANT USAGE ON LANGUAGE plpgsql TO pipeline_import" in z
                       for z in einrichten.einrichten(c, cfg))
        finally:
            # Ausgangszustand wiederherstellen, sonst scheiterten alle folgenden Geometrietests
            c.execute("GRANT USAGE ON LANGUAGE plpgsql TO PUBLIC")
    with _als("pipeline_import", "IMPORT_PASSWORD") as imp:
        imp.execute(ziel.GEOM_LESEN)


def _schema_stand() -> list:
    """Spalten, Typen und Constraints aller Tabellen in public (ohne pipeline_meta), sortiert; Spaltenzeilen
    haben sieben Felder, Constraintzeilen drei. Grundlage des Vorher-nachher-Vergleichs."""
    return _abfrage("""SELECT c.table_name, c.column_name, c.data_type, c.udt_name, c.is_nullable,
                              c.column_default, c.character_maximum_length
                       FROM information_schema.columns c
                       JOIN information_schema.tables t USING (table_schema, table_name)
                       WHERE c.table_schema = 'public' AND t.table_type = 'BASE TABLE'
                       ORDER BY 1, 2""") + _abfrage(
        """SELECT conrelid::regclass::text, conname, pg_get_constraintdef(oid) FROM pg_constraint
           WHERE connamespace = 'public'::regnamespace ORDER BY 1, 2""")


def test_schema_der_bestandstabellen_bleibt_unveraendert(tmp_path, als_import):
    """Antworten 27 und 47: das Schema der Bestandstabellen (sql/mosidi/001_bestand.sql) darf nicht
    verändert werden. Vor und nach Einrichten und Lauf sind Tabellen, Spalten, Typen und Constraints in
    public dieselben."""
    vorher = _schema_stand()
    cfg = _voll()
    with _admin() as c:
        einrichten.einrichten(c, cfg)
    name, p = f"test_{uuid.uuid4().hex[:8]}", uuid.uuid4().hex[:6]
    daten = tmp_path / "daten.csv"
    _flaechen(daten, [(f"{p}a", "Haus", 52.41, 12.54)])
    _lauf(_config(tmp_path, {name: _flaechen_quelle(daten)}))
    assert _schema_stand() == vorher
    assert len([r for r in vorher if len(r) == 7]) > 300  # die Bestandstabellen sind wirklich da


def test_zwei_quellen_im_selben_bereich_ohne_aktuelle_statistik(tmp_path, als_import, monkeypatch):
    """E31: Zwei Quellen mit denselben festen Werten schreiben nacheinander in dashboard_data_de,
    danach ein Folgelauf, bevor autovacuum die Tabelle analysiert hat. Die Importrolle darf die
    Tabelle nicht analysieren; ohne Statistik schätzt der Planer den Bereich auf eine Zeile. Auf
    einer frischen Datenbank (wie in der CI) dauerte der Abgleich der zweiten Quelle mit 40 000
    Zeilen so 89 s, ohne verschachtelte Schleife rund 2 s. Die Zeitgrenze macht aus einem Hänger einen
    Fehler. Hat die Tabelle schon eine Statistik, plant PostgreSQL auch ohne Abhilfe oft richtig;
    deshalb prüft der Test zusätzlich die Einstellung in der Transaktion des Abgleichs."""
    monkeypatch.setenv("PGOPTIONS", "-c statement_timeout=30000")
    from pipeline import ziel
    gesehen, vergleichen = [], ziel.vergleichen

    def vergleichen_mit_blick(cur, *a):
        """Hält vor jedem Abgleich fest, ob verschachtelte Schleifen in der Transaktion abgeschaltet sind
        (SHOW enable_nestloop), und ruft dann das echte ziel.vergleichen auf."""
        gesehen.append(cur.execute("SHOW enable_nestloop").fetchone()[0])
        return vergleichen(cur, *a)
    monkeypatch.setattr(ziel, "vergleichen", vergleichen_mit_blick)
    k = uuid.uuid4().hex[:6]
    quellen = {}
    for q in ("a", "b"):
        d = tmp_path / f"{q}.csv"
        d.write_text("ags;w\n" + "".join(f"{k}{i:07d};{i}\n" for i in range(40000)), encoding="utf-8")
        # Beide Quellen mit demselben source: derselbe Bereich in dashboard_data_de, wie im Befund zu E31.
        # Ohne Gebietsbezug, die erfundenen Schlüssel haben keine Gemeinde
        z = {**_kennzahlen(f"test_{k}"), "je_wert": {"w": f"Wert {q} {k}"}}
        del z["gebiet"]
        quellen[f"test_{k}_{q}"] = {"typ": "csv", "pfad": str(d), "trenner": ";", "id_spalte": "ags",
                                    "spalten": {"w": "w"}, "zahl_felder": ["w"],
                                    "zeitbezug": "2025-12-31", "gebiet": {"schluessel_spalte": "ags"},
                                    "lizenz": "Testdaten", "ziel": z}
    cfg = _config(tmp_path, quellen)
    b = _lauf(cfg)
    assert [(q["status"], q["zaehler"]["neu"]) for q in b["quellen"]] == [("ok", 40000), ("ok", 40000)]
    b = _lauf(cfg, alle=True)
    assert [(q["status"], q["zaehler"]["unveraendert"]) for q in b["quellen"]] == [("ok", 40000),
                                                                                   ("ok", 40000)]
    assert gesehen == ["off"] * 4


def test_zu_lange_texte_werden_zurueckgehalten(tmp_path, als_import):
    """Texte, die länger sind als eine varchar(n)-Spalte, kürzt PostgreSQL beim Umwandeln ohne Fehler. Bis
    E46 lud die Pipeline sie gekürzt und warnte (E31). Seit E47 (Prüfbericht 05.11. abends, Befund 3) wird
    nichts mehr gekürzt: Die Zeile wird zurückgehalten, ein neues Objekt nicht angelegt, ein vorhandenes
    behält seinen bisherigen Stand und wird nicht gelöscht; der Bericht zählt und warnt."""
    name, p = f"test_{uuid.uuid4().hex[:8]}", uuid.uuid4().hex[:6]
    daten = tmp_path / "gebaeude.csv"
    lang = "Haus " + "x" * 300                     # name ist varchar(254)
    cfg = _config(tmp_path, {name: _flaechen_quelle(daten)})
    _flaechen(daten, [(f"{p}a", lang, 52.41, 12.54), (f"{p}b", "Haus B", 52.40, 12.53)])
    q = _quelle(_lauf(cfg), name)
    assert q["status"] == "ok" and not q["unvollstaendig"]
    assert q["info"]["zu_lang"] == {"name": 1} and "gekuerzt" not in q["info"]
    texte = " ".join(q["warnungen"])
    assert (f"1 Objekt mit name länger als 254 Zeichen (bis 305), nicht übernommen, sein bisheriger Stand "
            f"bleibt: {p}a") in texte
    assert lang not in texte
    assert _abfrage('SELECT oid, length(name) FROM "Gebäude (ALKIS)" WHERE oid LIKE %s ORDER BY oid',
                    f"{p}%") == [(f"{p}b", 6)]
    # Vorhandenes Objekt: bisheriger Wert bleibt ungekürzt stehen, nichts wird gelöscht
    _flaechen(daten, [(f"{p}a", "Haus A", 52.41, 12.54), (f"{p}b", "Haus B", 52.40, 12.53)])
    assert _zahlen(_lauf(cfg), name) == (1, 0, 0, 1)
    _flaechen(daten, [(f"{p}a", lang, 52.41, 12.54), (f"{p}b", "Haus B", 52.40, 12.53)])
    q = _quelle(_lauf(cfg), name)
    assert q["zaehler"]["geloescht"] == 0 and q["zaehler"]["geaendert"] == 0
    assert _abfrage('SELECT oid, name FROM "Gebäude (ALKIS)" WHERE oid LIKE %s ORDER BY oid',
                    f"{p}%") == [(f"{p}a", "Haus A"), (f"{p}b", "Haus B")]


def test_zu_langer_schluessel_haelt_die_quelle_an(tmp_path, als_import):
    """Gekürzte Schlüssel könnten verschiedene Objekte zusammenlegen: die Quelle wird angehalten,
    nichts geschrieben (Codex-Prüfung 04.11., F3)."""
    name, p = f"test_{uuid.uuid4().hex[:8]}", uuid.uuid4().hex[:6]
    daten = tmp_path / "gebaeude.csv"
    oid_lang = f"{p}-0123456789abcdef"            # oid ist varchar(18), Schlüssel
    _flaechen(daten, [(f"{p}b", "Haus B", 52.40, 12.53), (oid_lang, "Haus C", 52.39, 12.52)])
    b = _lauf(_config(tmp_path, {name: _flaechen_quelle(daten)}))
    q = _quelle(b, name)
    assert q["status"] == "angehalten" and name in b["angehalten"]
    texte = " ".join(q["warnungen"])
    assert "nicht geladen" in texte and "Schlüsselspalte" in texte and oid_lang in texte
    assert _abfrage('SELECT count(*) FROM "Gebäude (ALKIS)" WHERE oid LIKE %s', f"{p}%") == [(0,)]


def test_ungueltige_geometrien_werden_korrigiert_oder_ausgelassen(tmp_path, als_import):
    """Antwort 63: ungültige Geometrien mit ST_MakeValid korrigieren, sonst auslassen; beides mit
    Warnung im Bericht. Ausgelassene Objekte machen den Abruf unvollständig (kein Löschen)."""
    name, p = f"test_{uuid.uuid4().hex[:8]}", uuid.uuid4().hex[:6]
    daten = tmp_path / "gebaeude.csv"
    x, y = 12.54, 52.41
    schleife = f"POLYGON(({x} {y},{x + .001} {y + .001},{x + .001} {y},{x} {y + .001},{x} {y}))"  # Fliege
    flach = f"POLYGON(({x} {y},{x + .001} {y + .001},{x} {y},{x} {y}))"                       # keine Fläche
    daten.write_text("id,name,wkt\n"
                     f'{p}gut,Haus,"POLYGON(({x} {y},{x + .001} {y},{x + .001} {y + .001},{x} {y}))"\n'
                     f'{p}fliege,Fliege,"{schleife}"\n'
                     f'{p}flach,Flach,"{flach}"\n', encoding="utf-8")
    q = _quelle(_lauf(_config(tmp_path, {name: _flaechen_quelle(daten)})), name)
    texte = " ".join(q["warnungen"])
    assert q["status"] == "ok" and q["unvollstaendig"]
    assert "mit ST_MakeValid korrigiert" in texte and f"{p}fliege" in texte
    assert "unbrauchbar, ausgelassen" in texte and f"{p}flach" in texte
    assert _abfrage('SELECT oid, ST_IsValid(geom), GeometryType(geom) FROM "Gebäude (ALKIS)" '
                    "WHERE oid LIKE %s ORDER BY oid", f"{p}%") == [(f"{p}fliege", True, "MULTIPOLYGON"),
                                                                   (f"{p}gut", True, "MULTIPOLYGON")]


def test_flaechenpruefung_als_regel_je_quelle(tmp_path, als_import):
    """Prüfregel aus der Konfiguration (gebiet.flaeche_pruefen): gemeldete Fläche gegen die Fläche der
    verknüpften Geometrie (km², Ellipsoid). Ein Gebiet über der Toleranz ergibt eine Warnung mit seinem
    Schlüssel, das Gebiet innerhalb der Toleranz wird dort nicht genannt; die Quelle wird trotzdem geladen.
    (Liegen alle Gebiete innerhalb der Toleranz, gibt es statt der Warnung einen Hinweis; das prüft dieser
    Test nicht.)"""
    k = uuid.uuid4().hex[:6]
    name = f"test_{k}_flaeche"
    ags_gut, ags_weit = (f"97{uuid.uuid4().int % 10**6:06d}" for _ in range(2))
    with _admin() as c:
        for ags, x in ((ags_gut, 12.0), (ags_weit, 12.1)):
            c.execute(f"""INSERT INTO "{GEMEINDEN}" (id, nationalco, name, geom) VALUES
                          (%s, %s, 'Testgemeinde', ST_Multi(ST_GeomFromText(
                           'POLYGON(({x} 52,{x + .01} 52,{x + .01} 52.01,{x} 52.01,{x} 52))', 4326)))""",
                      (int(ags), ags))
        flaeche = c.execute(f"""SELECT ST_Area(CAST(geom AS geography)) / 1e6 FROM "{GEMEINDEN}"
                                WHERE nationalco = %s""", (ags_gut,)).fetchone()[0]
    daten = tmp_path / "flaeche.csv"
    # Beide Quadrate sind gleich groß: gemeldet 0,1 % (innerhalb 0,5 %) und 5 % (darüber) mehr als berechnet
    daten.write_text(f"ags;fl\n{ags_gut};{flaeche * 1.001:.6f}\n{ags_weit};{flaeche * 1.05:.6f}\n",
                     encoding="utf-8")
    ziel = _kennzahlen(name)
    ziel["je_wert"] = {"fl": f"Fläche {name}"}
    ziel["gebiet"] = dict(ziel["gebiet"], flaeche_pruefen={"wert": "wert", "toleranz_prozent": 0.5})
    quelle = {"typ": "csv", "pfad": str(daten), "trenner": ";", "id_spalte": "ags", "spalten": {"fl": "fl"},
              "zahl_felder": ["fl"], "zeitbezug": "2025-12-31", "gebiet": {"schluessel_spalte": "ags"},
              "lizenz": "Testdaten", "ziel": ziel}
    q = _quelle(_lauf(_config(tmp_path, {name: quelle})), name)
    assert q["status"] == "ok" and q["zaehler"]["neu"] == 2
    pr = q["info"]["flaechenpruefung"]
    assert pr["geprueft"] == 2 and pr["ueber_toleranz"] == 1 and 4.9 < pr["max_prozent"] < 5.1
    assert any("Flächenprüfung: 1 von 2 Gebieten" in w and ags_weit in w and ags_gut not in w
               for w in q["warnungen"])


def test_raumdaten_werden_nicht_geloescht(tmp_path, als_import):
    """Antwort 74: gelöscht werden nur Attribute, Raumdaten bleiben, weil andere Quellen über den
    Schlüssel daran hängen. Mit loeschen: false bleibt ein entfallenes Objekt stehen und wird gemeldet."""
    name, p = f"test_{uuid.uuid4().hex[:8]}", uuid.uuid4().hex[:6]
    daten = tmp_path / "gebaeude.csv"
    cfg = _config(tmp_path, {name: _flaechen_quelle(daten, ziel=dict(GEBAEUDE, loeschen=False))})
    _flaechen(daten, [(f"{p}a", "Haus A", 52.41, 12.54), (f"{p}b", "Haus B", 52.40, 12.53)])
    _lauf(cfg)
    _flaechen(daten, [(f"{p}b", "Haus B", 52.40, 12.53)])
    q = _quelle(_lauf(cfg), name)
    assert q["status"] == "ok" and (q["zaehler"]["geloescht"], q["zaehler"]["zurueckgehalten"]) == (0, 1)
    assert any("bleiben stehen" in h for h in q["hinweise"])
    assert [r[0] for r in _abfrage('SELECT oid FROM "Gebäude (ALKIS)" WHERE oid LIKE %s ORDER BY oid',
                                   f"{p}%")] == [f"{p}a", f"{p}b"]


def test_kein_loeschrecht_auf_raumdaten_mit_loeschen_false():
    """Geringste Rechte: Liefern alle Quellen einer Tabelle mit loeschen: false (Raumdaten, Antwort 74),
    bekommt die Importrolle dort kein DELETE, auch nicht aus einem früheren Einrichten."""
    nur_raum = {"quellen": {"_raum": {"typ": "csv", "ziel": dict(BAEUME, loeschen=False)}}}
    voll = _voll()
    recht = "SELECT has_table_privilege('pipeline_import', '\"Baume\"', 'DELETE')"
    try:
        with _admin() as c:
            einrichten.einrichten(c, nur_raum)
            assert c.execute(recht).fetchone()[0] is False
    finally:
        with _admin() as c:
            einrichten.einrichten(c, voll)
            assert c.execute(recht).fetchone()[0] is True


def _kennzahl_quelle(pfad: Path, source: str, **ziel_extra) -> dict:
    """CSV-Quelle in Langform wie INKAR (kennziffer, bereich, indikator, zeitbezug, wert; Objekt-ID aus
    Spalte id, Geometrie als WKT) mit Ziel dashboard_data_de, abgegrenzt über `source`; ziel_extra ergänzt
    oder ersetzt Schlüssel des Ziels (etwa pflicht)."""
    ziel = {"tabelle": "dashboard_data_de", "schluessel": ["kennziffer", "indikator", "zeitbezug"],
            "spalten": {"indikator": "indikator", "kennziffer": "kennziffer", "wert": "wert",
                        "zeitbezug": "zeitbezug"},
            "fest": {"source": source, "granularity": "Gemeinden"}, **ziel_extra}
    return {"typ": "csv", "pfad": str(pfad), "trenner": ";", "id_spalte": "id", "wkt_spalte": "wkt",
            "srid": 4326,
            "spalten": {"kennziffer": "kennziffer", "bereich": "bereich", "indikator": "indikator",
                        "zeitbezug": "zeitbezug", "wert": "wert"},
            "zahl_felder": ["wert"], "lizenz": "Testdaten", "ziel": ziel}


def _kennzahlen_csv(pfad: Path, zeilen):
    """Schreibt die Langform-CSV zu _kennzahl_quelle; zeilen: (id, kennziffer, bereich, indikator, zeitbezug,
    wert), Geometrie fest POINT(12.5 52.4)."""
    pfad.write_text("id;kennziffer;bereich;indikator;zeitbezug;wert;wkt\n" + "".join(
        f"{i};{k};{b};{ind};{j};{w};POINT(12.5 52.4)\n" for i, k, b, ind, j, w in zeilen), encoding="utf-8")


# --- E40: stabiler INKAR-Schlüssel, mit dem Ziel aus config/quellen.yaml ---------------------------

INKAR_KOPF = "Bereich;ID;Kuerzel;Indikator;Raumbezug;Kennziffer;Name;Zeitbezug;Wert\n"


def _inkar_quelle(tmp: Path, name: str, zeilen: list[tuple], **ziel_extra) -> dict:
    """Die Quelle inkar_gemeinden aus config/quellen.yaml, wie ausgeliefert; geändert sind nur Adresse
    und Ablage (Testdatei statt BBSR), der Rhythmus (keiner, damit jeder Lauf lädt) und source (jeder Test
    hat eigene Zeilen in dashboard_data_de). ziel_extra ergänzt oder ersetzt Schlüssel des Ziels.
    zeilen: (Bereich, Kürzel, Indikator, Kennziffer, Jahr, Wert). Die Tests ersetzen
    quellen.datei_abrufen, damit die Zip-Datei aus der Ablage gelesen und nichts abgerufen wird. Die
    Ersatzadresse liegt nicht auf www.bbr-server.de: Diesen Rechner führt die robots-Sperrliste
    (ROBOTS_GESPERRT), die Quelle bräche dann vor dem Lesen der Ablage ab (E48). Seiteneffekt: schreibt
    tmp/cache-<name>/inkar_2025.zip."""
    import zipfile
    cfg = yaml.safe_load(KONFIG.read_text(encoding="utf-8"))["quellen"]["inkar_gemeinden"]
    ablage = tmp / f"cache-{name}"
    ablage.mkdir(exist_ok=True)
    text = INKAR_KOPF + "".join(f"{b};1;{k};{i};Gemeinden;{kz};Ort;{j};{w}\n" for b, k, i, kz, j, w in zeilen)
    with zipfile.ZipFile(ablage / "inkar_2025.zip", "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("inkar_2025.csv", text)
    cfg.update(url="https://bbr.example/inkar_2025.zip", cache=str(ablage), rhythmus=None)
    cfg["ziel"] = {**cfg["ziel"], "fest": {**cfg["ziel"]["fest"], "source": name}, **ziel_extra}
    return cfg


def _fuellung(k: str, kz: str) -> list[tuple]:
    """Je eine ZOM-Zeile für die Kürzel der Konfiguration, die ein Test nicht braucht (q_bev_fl, e5_bev,
    q_pendlersaldo; Indikatornamen mit der Endung `k`, Kennziffer `kz`): Fehlt ein konfiguriertes Kürzel
    ganz, hält die Quelle an (Feldlisten-Vergleich, E4)."""
    return [("ZOM", "q_bev_fl", f"Dichte {k}", kz, 2023, "1"), ("ZOM", "e5_bev", f"E5 {k}", kz, 2023, "2"),
            ("ZOM", "q_pendlersaldo", f"Pendlersaldo {k}", kz, 2023, "3")]


def _dashboard(name: str) -> list[tuple]:
    """Zeilen der Quelle `name` in dashboard_data_de als (indikator, kennziffer, zeitbezug, wert, data_type),
    sortiert."""
    return _abfrage("SELECT indikator, kennziffer, zeitbezug, wert, data_type FROM dashboard_data_de "
                    "WHERE source = %s ORDER BY 1, 2, 3", name)


def test_inkar_schluessel_stabil_bei_gleich_verschieden_und_wegfall(tmp_path, als_import, monkeypatch):
    """Codex-Prüfung 05.11., B1 (Antworten 31/62): Der fünfteilige Quellschlüssel bestimmt die Zählung,
    die Abbildung auf dashboard_data_de hängt nicht von Messwerten ab. Übergänge gleich → verschieden,
    verschieden → gleich und Wegfall eines Bereichs ändern genau die betroffenen Zeilen; ein Folgelauf
    ohne Änderung zählt 0 Änderungen. Vorher (E37): wertgleiche Bereiche zusammengeführt, verschiedene
    umbenannt, beim Übergang also Löschung plus zwei Neuanlagen statt einer Änderung."""
    from pipeline import quellen
    monkeypatch.setattr(quellen, "datei_abrufen", lambda *a, **k: False)
    k = uuid.uuid4().hex[:6]
    name, kz = f"test_{k}_inkar", f"12{uuid.uuid4().int % 10**6:06d}"
    bev, dichte = f"Bevölkerung {k}", f"Einwohnerdichte {k}"

    def stand(bev_lrb, dichte_lrb, mit_lrb=True):
        """Konfiguration mit fünf ZOM-Zeilen und, wenn mit_lrb, zwei LRB-Zeilen mit den Werten bev_lrb
        (Bevölkerung) und dichte_lrb (Einwohnerdichte)."""
        zeilen = [("ZOM", "xbev", bev, kz, 2023, "100"), ("ZOM", "q_bev_fl", dichte, kz, 2023, "50"),
                  ("ZOM", "alo", f"Arbeitslose {k}", kz, 2023, "7"),
                  ("ZOM", "e5_bev", f"E5 {k}", kz, 2023, "1"),
                  ("ZOM", "q_pendlersaldo", f"Pendlersaldo {k}", kz, 2023, "3")]
        if mit_lrb:
            zeilen += [("LRB", "xbev", bev, kz, 2023, bev_lrb),
                       ("LRB", "q_bev_fl", dichte, kz, 2023, dichte_lrb)]
        return {name: _inkar_quelle(tmp_path, name, zeilen)}

    cfg = _config(tmp_path, stand("100", "60"))      # Bevölkerung gleich, Einwohnerdichte verschieden
    q = _quelle(_lauf(cfg), name)
    assert q["status"] == "ok" and _zahlen({"quellen": [q]}, name) == (7, 0, 0, 0)
    assert not q["warnungen"] and not any("zusammengeführt" in h for h in q["hinweise"])
    namen = [r[0] for r in _dashboard(name)]
    assert namen == sorted([bev, f"{bev} (LRB)", dichte, f"{dichte} (LRB)", f"Arbeitslose {k}",
                            f"E5 {k}", f"Pendlersaldo {k}"])
    assert {r[4] for r in _dashboard(name)} == {"indikator"}                       # B11: data_type
    # Register und Protokoll führen den vollständigen Quellschlüssel
    assert _abfrage("SELECT quellschluessel FROM pipeline_meta.bestand WHERE quelle = %s AND "
                    "schluessel ->> 1 = %s", name, f"{bev} (LRB)") == [(f"{kz}|LRB|xbev|{bev}|2023",)]

    b = _lauf(cfg, alle=True)                                                       # ohne Änderung
    assert _zahlen(b, name) == (0, 0, 0, 7)
    assert _abfrage("SELECT count(*) FROM pipeline_meta.aenderung WHERE lauf_id = %s AND quelle = %s",
                    b["lauf_id"], name) == [(0,)]

    _config(tmp_path, stand("120", "60"))                                           # gleich → verschieden
    b = _lauf(cfg, alle=True)
    assert _zahlen(b, name) == (0, 1, 0, 6)
    assert _abfrage("SELECT art, quellschluessel FROM pipeline_meta.aenderung WHERE lauf_id = %s "
                    "AND quelle = %s", b["lauf_id"], name) == [("geaendert", f"{kz}|LRB|xbev|{bev}|2023")]
    assert [r[0] for r in _dashboard(name)] == namen                               # keine Umbenennung

    _config(tmp_path, stand("120", "50"))                                           # verschieden → gleich
    assert _zahlen(_lauf(cfg, alle=True), name) == (0, 1, 0, 6)
    assert [r[0] for r in _dashboard(name)] == namen

    _config(tmp_path, stand(None, None, mit_lrb=False))                             # Bereich LRB fällt weg
    b = _lauf(cfg, alle=True)
    assert _zahlen(b, name) == (0, 0, 2, 5)            # 2 von 7 Zeilen: unter dem Rückgang-Schutz (50 %)
    assert sorted(r[1] for r in _abfrage(
        "SELECT art, quellschluessel FROM pipeline_meta.aenderung WHERE lauf_id = %s AND quelle = %s",
        b["lauf_id"], name)) == [f"{kz}|LRB|q_bev_fl|{dichte}|2023", f"{kz}|LRB|xbev|{bev}|2023"]
    assert [r[0] for r in _dashboard(name)] == [n for n in namen if not n.endswith("(LRB)")]
    assert _zahlen(_lauf(cfg, alle=True), name) == (0, 0, 0, 5)


def test_inkar_verschiedene_kuerzel_und_mehrdeutige_abbildung(tmp_path, als_import, monkeypatch):
    """B1, unterschiedliche Kürzel: Gleicher Langtext in verschiedenen Bereichen mit verschiedenen Kürzeln
    trennt die Regel über den Bereich. Gleicher Langtext im selben Bereich mit zwei Kürzeln ergäbe denselben
    Zielschlüssel: Die Quelle wird angehalten, der alte Stand bleibt, nichts wird zusammengeführt oder
    verworfen (in INKAR 2025 kommt das nicht vor, beispielberichte/inkar-schluessel/). Mit Bereich und
    Kürzel in ziel.zusatz lädt sie wieder; dann tragen alle Reihen ihr Kürzel, auch die aus ZOM (E42)."""
    from pipeline import quellen
    monkeypatch.setattr(quellen, "datei_abrufen", lambda *a, **k: False)
    k = uuid.uuid4().hex[:6]
    name, kz = f"test_{k}_kuerzel", f"12{uuid.uuid4().int % 10**6:06d}"
    alo = f"Arbeitslosigkeit {k}"
    basis = [("ZOM", "alo", alo, kz, 2023, "5,1"), ("LRB", "xbev", alo, kz, 2023, "6,4"), *_fuellung(k, kz)]

    def alo_zeilen():
        """Zeilen dieser Quelle in dashboard_data_de, deren Indikator mit dem Langtext alo beginnt."""
        return [r for r in _dashboard(name) if r[0].startswith(alo)]
    cfg = _config(tmp_path, {name: _inkar_quelle(tmp_path, name, basis)})
    q = _quelle(_lauf(cfg), name)
    assert q["status"] == "ok" and q["zaehler"]["neu"] == 5
    assert [r[:4] for r in alo_zeilen()] == [(alo, kz, 2023, Decimal("5.1")),
                                             (f"{alo} (LRB)", kz, 2023, Decimal("6.4"))]
    # dazu im Bereich LRB derselbe Langtext unter einem zweiten Kürzel
    _config(tmp_path, {name: _inkar_quelle(tmp_path, name, [*basis, ("LRB", "e5_bev", alo, kz, 2023, "9")])})
    q = _quelle(_lauf(cfg, alle=True), name)
    assert q["status"] == "angehalten"
    w = " ".join(q["warnungen"])
    assert "1 Zielschlüssel aus mehr als einem Quellschlüssel (2 Zeilen)" in w
    assert f"{kz}|LRB|e5_bev|{alo}|2023" in w and f"{kz}|LRB|xbev|{alo}|2023" in w
    assert [r[3] for r in alo_zeilen()] == [Decimal("5.1"), Decimal("6.4")]          # alter Stand
    # Regel um das Kürzel erweitert: jede Reihe hat ihren Namen. Seit E42 trägt auch jede ZOM-Reihe ihr
    # Kürzel (`ausser` nimmt nur den Bereich weg), alle 5 Namen ändern sich: 6 neu, 5 gelöscht
    _config(tmp_path, {name: _inkar_quelle(tmp_path, name, [*basis, ("LRB", "e5_bev", alo, kz, 2023, "9")],
                                           zusatz={"spalte": "indikator", "feld": ["bereich", "kuerzel"],
                                                   "ausser": ["ZOM"]})})
    q = _quelle(_lauf(cfg, alle=True), name)
    assert q["status"] == "ok" and _zahlen({"quellen": [q]}, name) == (6, 0, 5, 0)
    assert {r[0] for r in alo_zeilen()} == {f"{alo} (LRB, e5_bev)", f"{alo} (LRB, xbev)", f"{alo} (alo)"}


def test_doppelter_quellschluessel_gleich_einmal_verschieden_ausgelassen(tmp_path, als_import):
    """E40: Liefert eine Quelle denselben Schlüssel zweimal, zählt nicht mehr „die erste“. Gleiche Werte:
    einmal übernommen. Verschiedene Werte: ausgelassen, der bisherige Stand bleibt, Warnung."""
    k = uuid.uuid4().hex[:6]
    name, kz = f"test_{k}_doppelt", f"94{uuid.uuid4().int % 10**6:06d}"
    daten = tmp_path / "werte.csv"
    cfg = _config(tmp_path, {name: _kennzahl_quelle(daten, name)})
    zeilen = [(f"{k}{i}", kz, "A", f"W{i}", 2023, str(i)) for i in range(1, 5)]
    _kennzahlen_csv(daten, zeilen)
    _lauf(cfg)
    _kennzahlen_csv(daten, [*zeilen, zeilen[0], (f"{k}2", kz, "A", "W2", 2023, "22")])
    q = _quelle(_lauf(cfg, alle=True), name)
    assert q["status"] == "ok" and (q["zaehler"]["geloescht"], q["zaehler"]["zurueckgehalten"]) == (0, 1)
    assert any("1 Zeilen doppelt mit gleichem Schlüssel und gleichen Werten" in h for h in q["hinweise"])
    assert any("1 Schlüssel mehrfach mit verschiedenen Werten geliefert, ausgelassen" in w
               for w in q["warnungen"])
    assert _abfrage("SELECT indikator, wert FROM dashboard_data_de WHERE source = %s ORDER BY 1", name) == [
        ("W1", 1), ("W2", 2), ("W3", 3), ("W4", 4)]
    # Prüfung nach E48 (Pre-existing seit E42): Ein Widerspruch der Quelle sperrt auch das Löschen. Fehlt
    # W3, weil sein Schlüssel als zweites W2 kam (Schaden beim Anbieter), darf W3 nicht gelöscht werden
    assert q["unvollstaendig"], q
    _kennzahlen_csv(daten, [zeilen[0], zeilen[1], (f"{k}2", kz, "A", "W2", 2023, "3"), zeilen[3]])
    q = _quelle(_lauf(cfg, alle=True), name)
    assert q["unvollstaendig"] and q["zaehler"]["geloescht"] == 0, q
    assert _abfrage("SELECT indikator, wert FROM dashboard_data_de WHERE source = %s ORDER BY 1", name) == [
        ("W1", 1), ("W2", 2), ("W3", 3), ("W4", 4)]


def test_csv_leere_zeilen_mit_leere_auslassen_behalten_den_wert(tmp_path, als_import):
    """Codex-Prüfung 05.11., B2, über den Konfigurationspfad der Statistiktabelle im CSV-Aufbau
    (_statistik_csv; leere_auslassen: true, Kopf- und Fußblock, je_wert): Eine Gemeinde nur mit „-“ wird mit
    Schlüssel ausgelassen, ihre bisherigen Werte bleiben, der Bericht warnt. Das gilt auch ohne ziel.pflicht.
    Vorher verschwand die Zeile schon im Adapter und ihre Werte wurden gelöscht. Zweiter Teil: Lässt sich
    der Schlüssel einer leeren Zeile nicht rekonstruieren, ist der Abruf unvollständig, nichts wird
    gelöscht."""
    for mit_pflicht in (True, False):
        k = uuid.uuid4().hex[:6]
        name = f"test_{k}_leer"
        kz = [f"12{uuid.uuid4().int % 10**6:06d}" for _ in range(4)]
        cfg_q = _statistik_csv()
        datei = tmp_path / f"{name}.csv"
        cfg_q.update(pfad=str(datei), rhythmus=None)
        cfg_q["ziel"] = {**cfg_q["ziel"], "fest": {**cfg_q["ziel"]["fest"], "source": name}}
        # Ohne table_metadata: Die Indikatornamen der Konfiguration sind fest, und jeder Test hat ein eigenes
        # source; seit E46 hielte der schon belegte Name die Quelle an (Metadaten sind hier nicht Thema)
        del cfg_q["ziel"]["metadaten"]
        if not mit_pflicht:
            del cfg_q["ziel"]["pflicht"]

        def schreiben(zeilen, datei=datei):
            """Schreibt die Statistiktabelle (latin-1) mit Kopf zum Stichtag 31.12.2025, einer Zeile je
            (Schlüssel, „insgesamt;männlich;weiblich“) und einer Fußnote."""
            kopf = ("\nTabelle: 12411-01-01-5-B\nBevölkerung;;;;\nEbenen;;;;\nFortschreibung;;;;\n"
                    ";;Stichtag;Stichtag;Stichtag\n;;31.12.2025;31.12.2025;31.12.2025\n"
                    ";;Insgesamt;männlich;weiblich\n")
            datei.write_text(kopf + "".join(f"{a};Ort;{w}\n" for a, w in zeilen) + "Fußnote;;;;\n",
                             encoding="latin-1")

        cfg = _config(tmp_path, {name: cfg_q})
        schreiben([(a, f"{100 + i};{50 + i};{50}") for i, a in enumerate(kz)])
        q = _quelle(_lauf(cfg), name)
        assert q["status"] == "ok" and q["zaehler"]["neu"] == 12
        schreiben([(a, f"{100 + i};{50 + i};{50}") for i, a in enumerate(kz[:3])] + [(kz[3], "-;-;-")])
        q = _quelle(_lauf(cfg, alle=True), name)
        assert q["status"] == "ok" and not q["unvollstaendig"]
        assert (q["zaehler"]["geloescht"], q["zaehler"]["zurueckgehalten"], q["zaehler"]["unveraendert"]) == \
            (0, 3, 9), mit_pflicht
        assert any(f"3 Zeilen ohne jeden Wert ausgelassen (leere_auslassen), ihr bisheriger Stand "
                   f"bleibt: {kz[3]}|" in w for w in q["warnungen"]), q["warnungen"]
        assert not any("ohne jeden Wert" in h for h in q["hinweise"])
        assert _abfrage("SELECT count(*), sum(wert) FROM dashboard_data_de WHERE source = %s "
                        "AND kennziffer = %s", name, kz[3]) == [(3, Decimal(103 + 53 + 50))]

    # Schlüssel nicht rekonstruierbar: Zeile ohne Gebietsschlüssel und ohne Wert; eine andere Gemeinde fehlt
    # ganz. Ohne Schlüssel lässt sich nicht sagen, ob die fehlende genau diese ist: nichts wird gelöscht
    k = uuid.uuid4().hex[:6]
    name, kz = f"test_{k}_leer_ohne", [f"93{uuid.uuid4().int % 10**6:06d}" for _ in range(4)]
    datei = tmp_path / f"{name}.csv"
    quelle = {"typ": "csv", "pfad": str(datei), "trenner": ";", "id_spalte": "ags",
              "spalten": {"bev": "bev"}, "zahl_felder": ["bev"], "zeitbezug": "2025-12-31",
              "leere_auslassen": True, "gebiet": {"schluessel_spalte": "ags"}, "lizenz": "Testdaten",
              "ziel": {**_kennzahlen(name), "je_wert": {"bev": "Bevölkerung"}}}
    del quelle["ziel"]["gebiet"]
    cfg = _config(tmp_path, {name: quelle})
    datei.write_text("ags;bev\n" + "".join(f"{a};{i}\n" for i, a in enumerate(kz)), encoding="utf-8")
    _lauf(cfg)
    datei.write_text("ags;bev\n" + "".join(f"{a};{i}\n" for i, a in enumerate(kz[:3])) + ";-\n",
                     encoding="utf-8")
    q = _quelle(_lauf(cfg, alle=True), name)
    assert q["unvollstaendig"] and (q["zaehler"]["geloescht"], q["zaehler"]["zurueckgehalten"]) == (0, 1)
    assert _abfrage("SELECT count(*) FROM dashboard_data_de WHERE source = %s", name) == [(4,)]


def test_data_type_auch_in_vorhandenen_zeilen_ohne_doppelte(tmp_path, als_import, monkeypatch):
    """Codex-Prüfung 05.11., B11: data_type ist ein konstanter Wert (ziel.konstant), keine Abgrenzung
    (ziel.fest). Zeilen, die vorher ohne data_type geschrieben wurden, werden einmal als geändert
    nachgezogen, nicht als fremd übergangen und doppelt angelegt."""
    from pipeline import quellen
    monkeypatch.setattr(quellen, "datei_abrufen", lambda *a, **k: False)
    k = uuid.uuid4().hex[:6]
    name, kz = f"test_{k}_typ", f"12{uuid.uuid4().int % 10**6:06d}"
    zeilen = [("ZOM", "xbev", f"Bevölkerung {k}", kz, j, str(j)) for j in (2021, 2022, 2023)]
    zeilen += [("ZOM", "alo", f"Arbeitslose {k}", kz, 2023, "4"), *_fuellung(k, kz)]
    ohne = _inkar_quelle(tmp_path, name, zeilen)
    del ohne["ziel"]["konstant"]
    cfg = _config(tmp_path, {name: ohne})
    _lauf(cfg)
    assert {r[4] for r in _dashboard(name)} == {None}
    cfg = _config(tmp_path, {name: _inkar_quelle(tmp_path, name, zeilen)})
    assert _zahlen(_lauf(cfg, alle=True), name) == (0, 7, 0, 0)
    assert [r[4] for r in _dashboard(name)] == ["indikator"] * 7
    assert _zahlen(_lauf(cfg, alle=True), name) == (0, 0, 0, 7)


def test_pflichtfeld_fehlt_zeile_ausgelassen_alter_wert_bleibt(tmp_path, als_import):
    """Antwort 63 / Codex B2: ohne Wert in einem Pflichtfeld wird die Zeile mit Warnung ausgelassen;
    ihr bisheriger Stand wird nicht gelöscht, der Rest der Quelle normal abgeglichen."""
    k = uuid.uuid4().hex[:6]
    name, kz = f"test_{k}_pflicht", f"95{uuid.uuid4().int % 10**6:06d}"
    daten = tmp_path / "werte.csv"
    cfg = _config(tmp_path, {name: _kennzahl_quelle(daten, name, pflicht=["wert", "zeitbezug"])})
    # sechs Zeilen, damit der Rückgang-Schutz (über 50 % weniger) nicht greift
    weitere = [(f"{k}{i}", kz, "A", f"W{i}", 2023, str(i)) for i in range(4, 7)]
    _kennzahlen_csv(daten, [(f"{k}1", kz, "A", "X", 2023, "1"), (f"{k}2", kz, "A", "Y", 2023, "2"),
                            (f"{k}3", kz, "A", "Z", 2023, "3"), *weitere])
    _lauf(cfg)
    _kennzahlen_csv(daten, [(f"{k}1", kz, "A", "X", 2023, "1"), (f"{k}2", kz, "A", "Y", 2023, "k.A."),
                            *weitere])
    q = _quelle(_lauf(cfg, alle=True), name)
    warnungen = " ".join(q["warnungen"])
    assert "1 Zeilen ohne Wert in einem Pflichtfeld (wert, zeitbezug) ausgelassen" in warnungen
    assert (q["zaehler"]["geloescht"], q["zaehler"]["zurueckgehalten"]) == (1, 1)   # Z weg, Y bleibt
    assert _abfrage("SELECT indikator, wert FROM dashboard_data_de WHERE source = %s ORDER BY 1", name) == [
        ("W4", Decimal("4")), ("W5", Decimal("5")), ("W6", Decimal("6")), ("X", Decimal("1")),
        ("Y", Decimal("2"))]


def test_metadaten_gleichnamiger_indikatoren_verschiedener_quellen(tmp_path, als_import, monkeypatch):
    """Codex B5: table_metadata kennt einen Indikator über Name, Raumebene und Herausgeber (source).
    Liefert eine zweite Quelle einen gleichnamigen Indikator auf derselben Raumebene, überschreibt sie
    die Zeile der ersten nicht. Im öffentlichen Schema ist table_name der Primärschlüssel; dann kann
    die zweite Quelle keine Zeile anlegen. Bis E45 wurden ihre Kennzahlen trotzdem geladen (mit Warnung);
    seit E46 (Prüfbericht 05.11., F2) wird sie vor dem Schreiben angehalten: keine Fachdaten ohne
    Metadatensatz, kein Meldungsentwurf an den Anbieter (der Konflikt liegt im eigenen Katalog)."""
    k = uuid.uuid4().hex[:6]
    a, b = f"test_{k}_a", f"test_{k}_b"
    indikator = f"Bevölkerung {k}"
    quellen = {}
    for name, jahr, wert in ((a, "2024-12-31", 100), (b, "2025-12-31", 200)):
        d = tmp_path / f"{name}.csv"
        d.write_text(f"ags;bev\n{k}01;{wert}\n", encoding="utf-8")
        z = {**_kennzahlen(name), "je_wert": {"bev": indikator}}
        del z["gebiet"]
        quellen[name] = {"typ": "csv", "pfad": str(d), "trenner": ";", "id_spalte": "ags",
                         "spalten": {"bev": "bev"}, "zahl_felder": ["bev"], "zeitbezug": jahr,
                         "gebiet": {"schluessel_spalte": "ags"}, "lizenz": "Testdaten", "ziel": z}
    cfg = _config(tmp_path, quellen)
    meta = ("SELECT dct_catalog_publisher, extract(year FROM dct_temporal_startdata)::int "
            "FROM table_metadata WHERE table_name = %s ORDER BY 1")
    bericht = _lauf(cfg)
    qa, qb = _quelle(bericht, a), _quelle(bericht, b)
    assert qa["status"] == "ok" and qa["info"]["metadaten"] == 1
    assert qb["status"] == "angehalten" and qb["info"]["metadaten_belegt"] == [indikator]
    assert any("table_metadata: 1 Zeile nicht anlegbar" in w and indikator in w and "angehalten" in w
               for w in qb["warnungen"])
    assert "meldung" not in qb
    assert _abfrage(meta, indikator) == [(a, 2024)]                  # nicht von b überschrieben
    assert _abfrage("SELECT source, wert FROM dashboard_data_de WHERE indikator = %s ORDER BY 1",
                    indikator) == [(a, 100)]                           # b nicht ohne Metadatensatz geladen
    assert _abfrage("SELECT count(*) FROM pipeline_meta.bestand WHERE quelle = %s", b) == [(0,)]
    stempel = ("SELECT imported, dct_modified FROM table_metadata WHERE table_name = %s "
               "AND dct_catalog_publisher = %s")
    vorher = _abfrage(stempel, indikator, a)
    # Wiederholung von b ändert die Zeile von a weiterhin nicht; a selbst pflegt sie weiter: das UPDATE
    # über Name, Raumebene und Herausgeber trifft ihre Zeile, sie fällt nicht in den Zweig „belegt“
    (tmp_path / f"{a}.csv").write_text(f"ags;bev\n{k}01;101\n", encoding="utf-8")
    bericht = _lauf(cfg, alle=True)
    qa, qb = _quelle(bericht, a), _quelle(bericht, b)
    assert qa["status"] == "ok" and qa["zaehler"]["geaendert"] == 1 and qa["info"]["metadaten"] == 1
    assert not any("nicht anlegbar" in w for w in qa["warnungen"])
    assert qb["status"] == "angehalten" and any("nicht anlegbar" in w for w in qb["warnungen"])
    assert _abfrage(meta, indikator) == [(a, 2024)]
    ((imported, geaendert),) = _abfrage(stempel, indikator, a)
    assert imported > vorher[0][0] and geaendert > vorher[0][1]   # von a neu gestempelt
    # Sicherheitsnetz: Entsteht die fremde Zeile erst nach der Prüfung (hier: Prüfung übergangen), scheitert
    # das Anlegen, und die ganze Quelle wird zurückgerollt, statt ihre Kennzahlen ohne Metadaten zu laden
    monkeypatch.setattr(ziel, "metadaten_belegt", lambda *a, **kw: [])
    qb = _quelle(_lauf(cfg, nur=b), b)
    assert qb["status"] == "fehler" and qb["fehler"].startswith("MetadatenBelegt")
    # Auch hier kein Meldungsentwurf an den Anbieter (Nachprüfung zu E46: bis dahin entstand einer)
    assert qb["info"]["metadaten_belegt"] == [indikator] and "meldung" not in qb
    assert not list((tmp_path / "berichte").glob(f"*-meldung-{b}.txt"))
    assert _abfrage("SELECT source FROM dashboard_data_de WHERE indikator = %s", indikator) == [(a,)]


def test_wiederholung_nach_erzwungenem_unvollstaendigem_lauf(tmp_path, als_import):
    """Codex B6: Ein erzwungener Lauf (--alle) kurz nach einem Erfolg ist unvollständig. Der nächste
    reguläre Lauf darf die monatliche Quelle nicht als „nicht fällig“ überspringen, sonst bliebe der
    lückenhafte Stand bis zum nächsten Termin stehen. Nach einem vollständigen Lauf gilt der Rhythmus
    wieder."""
    name, p = f"test_{uuid.uuid4().hex[:8]}", uuid.uuid4().hex[:6]
    daten = tmp_path / "daten.csv"
    cfg = _config(tmp_path, {name: _punkt_quelle(daten, rhythmus="monatlich")})
    voll = [(f"{p}{i}", f"P{i}", 52.4 + i / 1000, 12.5) for i in range(4)]
    _punkte(daten, voll)
    assert _quelle(_lauf(cfg), name)["status"] == "ok"
    assert _quelle(_lauf(cfg), name)["status"] == "nicht_faellig"
    _punkte(daten, voll + [(f"{p}x", "X", "", "")])                      # unvollständig
    assert _quelle(_lauf(cfg, alle=True), name)["unvollstaendig"]
    _punkte(daten, voll)
    q = _quelle(_lauf(cfg), name)                                        # regulär, ohne --alle
    assert q["status"] == "ok" and not q["unvollstaendig"]
    assert any(h.startswith("Wiederholung:") for h in q["hinweise"])
    assert _quelle(_lauf(cfg), name)["status"] == "nicht_faellig"


# --- Prüfung 05.11., Runde 2 (E42) ---------------------------------------------------------------------

def _aenderungen(b: dict, name: str) -> list[tuple]:
    """Änderungen eines Laufs für die Quelle `name` als (art, quellschluessel), sortiert."""
    return _abfrage("SELECT art, quellschluessel FROM pipeline_meta.aenderung WHERE lauf_id = %s "
                    "AND quelle = %s ORDER BY 1, 2", b["lauf_id"], name)


def test_kuerzelwechsel_zaehlt_als_geloescht_und_neu(tmp_path, als_import, monkeypatch):
    """Antwort 62: Schlüssel ist Kennziffer, Bereich, Kürzel, Indikator, Zeitbezug. Benennt die Quelle ein
    Kürzel um und Bereich und Langtext bleiben, fällt die Reihe auf denselben Zielschlüssel. Nach Antwort 62
    ist der alte Quellschlüssel gelöscht und der neue neu, auch bei gleichem Wert; vorher (E40) zählte das
    als „geändert“, und der alte Quellschlüssel fehlte im Protokoll. Die Zeile wird aktualisiert, nicht
    gelöscht und neu angelegt; ein unvollständiger Abruf ändert die Zählung nicht. Dazu: Indikatorzeilen in
    table_metadata ohne Daten meldet der Bericht als verwaist."""
    from pipeline import quellen
    monkeypatch.setattr(quellen, "datei_abrufen", lambda *a, **k: False)
    k = uuid.uuid4().hex[:6]
    name, kz = f"test_{k}_kw", f"12{uuid.uuid4().int % 10**6:06d}"
    lang = f"Langtext {k}"
    basis = [("ZOM", "xbev", f"Bev {k}", kz, 2023, "100"), ("ZOM", "alo", f"Alo {k}", kz, 2023, "7"),
             *_fuellung(k, kz)]
    q = {kue: f"{kz}|LRB|{kue}|{lang}|2023" for kue in ("xbev", "q_bev_fl")}

    def stand(kuerzel, wert, extra=(), langtext=lang):
        """Konfiguration aus der Basis, einer LRB-Zeile mit `kuerzel`, `wert` und `langtext` und den
        Zusatzzeilen `extra`."""
        lrb = ("LRB", kuerzel, langtext, kz, 2023, wert)
        return {name: _inkar_quelle(tmp_path, name, [*basis, lrb, *extra])}

    def zeile():
        """Zeilen dieser Quelle mit dem Langtext lang als (indikator, kennziffer, zeitbezug, wert)."""
        return [r[:4] for r in _dashboard(name) if r[0].startswith(lang)]
    cfg = _config(tmp_path, stand("xbev", "6"))
    assert _zahlen(_lauf(cfg), name) == (6, 0, 0, 0)
    erster = _abfrage("SELECT erster_lauf FROM pipeline_meta.bestand WHERE quelle = %s "
                      "AND quellschluessel = %s", name, q["xbev"])
    # gleicher Wert unter neuem Kürzel
    _config(tmp_path, stand("q_bev_fl", "6"))
    b = _lauf(cfg, alle=True)
    qb = _quelle(b, name)
    assert qb["status"] == "ok" and _zahlen(b, name) == (1, 0, 1, 5)
    assert _aenderungen(b, name) == [("entfernt", q["xbev"]), ("neu", q["q_bev_fl"])]
    assert any("1 Zeilen kommen aus einem anderen Quellschlüssel" in h for h in qb["hinweise"])
    assert zeile() == [(f"{lang} (LRB)", kz, 2023, Decimal("6"))]                    # dieselbe Zeile
    assert _abfrage("SELECT quellschluessel, erster_lauf = %s FROM pipeline_meta.bestand WHERE quelle = %s "
                    "AND schluessel ->> 1 = %s", b["lauf_id"], name, f"{lang} (LRB)") == [
        (q["q_bev_fl"], True)]
    assert erster and erster[0][0] != b["lauf_id"]
    assert _zahlen(_lauf(cfg, alle=True), name) == (0, 0, 0, 6)                      # danach ruhig
    # zurück, mit anderem Wert: wieder gelöscht + neu, nicht „geändert“
    _config(tmp_path, stand("xbev", "7"))
    b = _lauf(cfg, alle=True)
    assert _zahlen(b, name) == (1, 0, 1, 5) and zeile() == [(f"{lang} (LRB)", kz, 2023, Decimal("7"))]
    assert _aenderungen(b, name) == [("entfernt", q["q_bev_fl"]), ("neu", q["xbev"])]
    # unvollständiger Abruf (eine Zeile ohne Bereich): die Zeile wird trotzdem überschrieben, also gezählt
    _config(tmp_path, stand("q_bev_fl", "7", extra=[("", "xbev", f"Ohne {k}", kz, 2023, "1")]))
    qb = _quelle(_lauf(cfg, alle=True), name)
    assert qb["unvollstaendig"] and _zahlen({"quellen": [qb]}, name) == (1, 0, 1, 5)
    assert qb["zaehler"]["zurueckgehalten"] == 0
    # Langtext geändert: anderer Zielschlüssel, gelöscht + neu; der alte Name bleibt in table_metadata
    # stehen (die Importrolle löscht dort nicht) und wird als verwaist gemeldet
    _config(tmp_path, stand("q_bev_fl", "7", langtext=f"{lang} neu"))
    qb = _quelle(_lauf(cfg, alle=True), name)
    assert _zahlen({"quellen": [qb]}, name) == (1, 0, 1, 5)
    assert any("1 Indikatorzeile dieser Quelle" in w and "verwaist" in w and f"{lang} (LRB)" in w
               for w in qb["warnungen"]), qb["warnungen"]
    assert _abfrage("SELECT count(*) FROM table_metadata WHERE dct_catalog_publisher = %s", name) == [(7,)]


def test_mehrdeutige_abbildung_haengt_nicht_an_leeren_werten(tmp_path, als_import, monkeypatch):
    """Vorher liefen Leerzeilen- und Pflichtfeld-Filter vor der Eindeutigkeitsprüfung: War eine von zwei
    kollidierenden Reihen ohne Wert, lief die Quelle durch, und die andere Reihe füllte still die Zielzeile
    (auch mit einem Wechsel des Quellschlüssels). Jetzt hält sie in jedem Fall an, der alte Stand bleibt."""
    from pipeline import quellen
    monkeypatch.setattr(quellen, "datei_abrufen", lambda *a, **k: False)
    k = uuid.uuid4().hex[:6]
    name, kz = f"test_{k}_wa", f"12{uuid.uuid4().int % 10**6:06d}"
    lang = f"Langtext {k}"
    basis = [("ZOM", "xbev", f"Bev {k}", kz, 2023, "100"), ("ZOM", "alo", f"Alo {k}", kz, 2023, "7"),
             *_fuellung(k, kz)]

    def stand(*lrb):
        """Konfiguration aus der Basis und den übergebenen LRB-Zeilen."""
        return {name: _inkar_quelle(tmp_path, name, [*basis, *lrb])}
    cfg = _config(tmp_path, stand(("LRB", "xbev", lang, kz, 2023, "6")))
    assert _zahlen(_lauf(cfg), name) == (6, 0, 0, 0)
    for xbev, e5 in (("6", ""), ("", "9"), ("6", "9")):
        _config(tmp_path, stand(("LRB", "xbev", lang, kz, 2023, xbev), ("LRB", "e5_bev", lang, kz, 2023, e5)))
        b = _lauf(cfg, alle=True)
        q = _quelle(b, name)
        assert q["status"] == "angehalten", (xbev, e5, q)
        assert "1 Zielschlüssel aus mehr als einem Quellschlüssel (2 Zeilen)" in " ".join(q["warnungen"])
        assert [r[3] for r in _dashboard(name) if r[0] == f"{lang} (LRB)"] == [Decimal("6")]
        assert _abfrage("SELECT quellschluessel FROM pipeline_meta.bestand WHERE quelle = %s AND "
                        "schluessel ->> 1 = %s", name, f"{lang} (LRB)") == [(f"{kz}|LRB|xbev|{lang}|2023",)]


def test_doppelter_quellschluessel_leer_und_mit_wert_ist_widerspruch(tmp_path, als_import):
    """Kommt derselbe Schlüssel einmal ohne Wert (Pflichtfeld) und einmal mit Wert, entfernte der
    Pflichtfeld-Filter vorher die leere Zeile, und die andere ging still durch. Jetzt ist es ein Widerspruch
    der Quelle: ausgelassen, alter Stand bleibt, Warnung."""
    k = uuid.uuid4().hex[:6]
    name, kz = f"test_{k}_dl", f"96{uuid.uuid4().int % 10**6:06d}"
    daten = tmp_path / "werte.csv"
    cfg = _config(tmp_path, {name: _kennzahl_quelle(daten, name, pflicht=["wert", "zeitbezug"])})
    zeilen = [(f"{k}{i}", kz, "A", f"W{i}", 2023, str(i)) for i in range(1, 5)]
    _kennzahlen_csv(daten, zeilen)
    _lauf(cfg)
    _kennzahlen_csv(daten, [*zeilen, (f"{k}2", kz, "A", "W2", 2023, "-")])
    q = _quelle(_lauf(cfg, alle=True), name)
    assert any("1 Schlüssel mehrfach mit verschiedenen Werten geliefert, ausgelassen" in w
               for w in q["warnungen"])
    assert not any("Pflichtfeld" in w for w in q["warnungen"])
    z = q["zaehler"]
    assert (z["geloescht"], z["zurueckgehalten"], z["unveraendert"]) == (0, 1, 3)
    assert _abfrage("SELECT indikator, wert FROM dashboard_data_de WHERE source = %s ORDER BY 1", name) == [
        ("W1", 1), ("W2", 2), ("W3", 3), ("W4", 4)]


def test_zom_kollision_mit_bereich_und_kuerzel_aufloesbar(tmp_path, als_import, monkeypatch):
    """`ausser: [ZOM]` nahm einer ZOM-Zeile auch das Kürzel; mit feld: [bereich, kuerzel] blieb ein Langtext
    mit zwei Kürzeln in ZOM mehrdeutig, die Quelle hielt an. Jetzt bekommt jede ZOM-Reihe ihr Kürzel."""
    from pipeline import quellen
    monkeypatch.setattr(quellen, "datei_abrufen", lambda *a, **k: False)
    k = uuid.uuid4().hex[:6]
    name, kz = f"test_{k}_zom", f"12{uuid.uuid4().int % 10**6:06d}"
    bev = f"Bev {k}"
    zeilen = [("ZOM", "xbev", bev, kz, 2023, "100"), ("ZOM", "e5_bev", bev, kz, 2023, "9"),
              ("ZOM", "alo", f"Alo {k}", kz, 2023, "7"), *_fuellung(k, kz)]
    cfg = _config(tmp_path, {name: _inkar_quelle(tmp_path, name, zeilen, zusatz={
        "spalte": "indikator", "feld": ["bereich", "kuerzel"], "ausser": ["ZOM"]})})
    q = _quelle(_lauf(cfg), name)
    assert q["status"] == "ok" and q["zaehler"]["neu"] == 6
    assert [r[0] for r in _dashboard(name) if r[0].startswith(bev)] == [f"{bev} (e5_bev)", f"{bev} (xbev)"]


def _statistik(datei: Path, stichtag: str, zeilen: list[tuple[str, str]]) -> None:
    """Schreibt die Statistiktabelle im CSV-Aufbau (_statistik_csv) nach `datei` (latin-1): Kopf wie bei der
    Tabelle 12411-01-01-5-B mit `stichtag` in Zeile 7, eine Zeile je (Schlüssel, „insgesamt;männlich;
    weiblich“), darunter eine Fußnote."""
    kopf = ("\nTabelle: 12411-01-01-5-B\nBevölkerung;;;;\nEbenen;;;;\nFortschreibung;;;;\n"
            f";;Stichtag;Stichtag;Stichtag\n;;{stichtag};{stichtag};{stichtag}\n"
            ";;Insgesamt;männlich;weiblich\n")
    rumpf = "".join(f"{a};Ort;{w}\n" for a, w in zeilen)
    datei.write_text(kopf + rumpf + "Fußnote;;;;\n", encoding="latin-1")


def test_stichtagwechsel_ausgelassene_zeile_behaelt_vorjahr(tmp_path, als_import):
    """Rückt der Stichtag vor, hat eine ausgelassene Zeile (ohne jeden Wert, oder ohne Wert in einem
    Pflichtfeld) einen neuen Zielschlüssel. Vorher wurde ihr Vorjahreswert regulär gelöscht, obwohl der
    Bericht „bisheriger Stand bleibt“ sagte. Jetzt hält auch der Quellschlüssel (Gemeinde und Feld, ohne Jahr)
    den Eintrag zurück: Die Gemeinde behält den Wert des Vorjahrs, bis die Quelle wieder einen liefert."""
    for zeile, behalten in (("-;-;-", 3), ("120;.;55", 1)):
        k = uuid.uuid4().hex[:6]
        name = f"test_{k}_st"
        kz = [f"12{uuid.uuid4().int % 10**6:06d}" for _ in range(4)]
        cfg_q = _statistik_csv()
        datei = tmp_path / f"{name}.csv"
        cfg_q.update(pfad=str(datei), rhythmus=None)
        cfg_q["ziel"] = {**cfg_q["ziel"], "fest": {**cfg_q["ziel"]["fest"], "source": name}}
        # Ohne table_metadata: Die Indikatornamen der Konfiguration sind fest, und jeder Test hat ein eigenes
        # source; seit E46 hielte der schon belegte Name die Quelle an (Metadaten sind hier nicht Thema)
        del cfg_q["ziel"]["metadaten"]
        cfg = _config(tmp_path, {name: cfg_q})
        _statistik(datei, "31.12.2024", [(a, f"{100 + i};{50 + i};50") for i, a in enumerate(kz)])
        assert _zahlen(_lauf(cfg), name) == (12, 0, 0, 0)
        _statistik(datei, "31.12.2025", [(a, f"{110 + i};{55 + i};55") for i, a in enumerate(kz[:3])]
                   + [(kz[3], zeile)])
        q = _quelle(_lauf(cfg, alle=True), name)
        assert q["status"] == "ok" and not q["unvollstaendig"], q
        z = q["zaehler"]
        assert (z["neu"], z["geloescht"], z["zurueckgehalten"]) == (12 - behalten, 12 - behalten, behalten), z
        werte = _abfrage("SELECT zeitbezug, count(*) FROM dashboard_data_de WHERE source = %s "
                         "AND kennziffer = %s GROUP BY 1 ORDER BY 1", name, kz[3])
        assert werte == ([(2024, 3)] if behalten == 3 else [(2024, 1), (2025, 2)]), werte
        assert _abfrage("SELECT count(*) FROM pipeline_meta.aenderung WHERE quelle = %s "
                        "AND art = 'zurueckgehalten'", name) == [(behalten,)]


def test_gebiet_ohne_flaeche_auslassen_behaelt_den_stand(tmp_path, als_import):
    """gebiet.ohne_flaeche: auslassen nahm Zeilen ohne Fläche aus dem neuen Stand, ohne sie als ausgelassen zu
    führen: Ihr bisheriger Wert wurde gelöscht, der Bericht sagte „ausgelassen“. Jetzt bleibt er."""
    k = uuid.uuid4().hex[:6]
    name = f"test_{k}_gf"
    ags = [f"97{uuid.uuid4().int % 10**6:06d}" for _ in range(4)]
    with _admin() as c:
        for a in ags:
            c.execute(f"""INSERT INTO "{GEMEINDEN}" (id, nationalco, name, geom) VALUES
                          (%s, %s, 'Testgemeinde', ST_Multi(ST_GeomFromText(
                           'POLYGON((12 52,12.01 52,12.01 52.01,12 52))', 4326)))""", (int(a), a))
    daten = tmp_path / "gf.csv"
    daten.write_text("ags;bev\n" + "".join(f"{a};{i + 1}\n" for i, a in enumerate(ags)), encoding="utf-8")
    ziel_ = _kennzahlen(name)
    ziel_["gebiet"] = {**ziel_["gebiet"], "ohne_flaeche": "auslassen"}
    quelle = {"typ": "csv", "pfad": str(daten), "trenner": ";", "id_spalte": "ags", "spalten": {"bev": "bev"},
              "zahl_felder": ["bev"], "zeitbezug": "2025-12-31", "gebiet": {"schluessel_spalte": "ags"},
              "lizenz": "Testdaten", "ziel": ziel_}
    cfg = _config(tmp_path, {name: quelle})
    assert _zahlen(_lauf(cfg), name) == (4, 0, 0, 0)
    with _admin() as c:
        c.execute(f'DELETE FROM "{GEMEINDEN}" WHERE nationalco = %s', (ags[3],))
    q = _quelle(_lauf(cfg, alle=True), name)
    assert q["status"] == "ok" and (q["zaehler"]["geloescht"], q["zaehler"]["zurueckgehalten"]) == (0, 1)
    assert any("1 Zeilen ohne Fläche ausgelassen, ihr bisheriger Stand bleibt" in w for w in q["warnungen"])
    assert _abfrage("SELECT count(*) FROM dashboard_data_de WHERE source = %s", name) == [(4,)]


def test_laufprotokoll_fuehrt_unvollstaendige_quellen(tmp_path, als_import):
    """E44 („unvollständig“ überall): pipeline_meta.lauf hatte nur fehler und angehalten; ein lückenhafter
    Lauf sah dort sauber aus. Jetzt zählt die Spalte unvollstaendig die lückenhaften Quellen eines Laufs
    (hier eine Zeile ohne Gebietsschlüssel: 0 Fehler, 0 angehalten, 1 unvollständig)."""
    k = uuid.uuid4().hex[:6]
    name = f"test_{k}_lp"
    daten = tmp_path / "lp.csv"
    daten.write_text(f"ags;bev\n91{uuid.uuid4().int % 10**6:06d};1\n;2\n", encoding="utf-8")
    quelle = {"typ": "csv", "pfad": str(daten), "trenner": ";", "id_spalte": "ags", "spalten": {"bev": "bev"},
              "zahl_felder": ["bev"], "zeitbezug": "2025-12-31", "gebiet": {"schluessel_spalte": "ags"},
              "lizenz": "Testdaten", "ziel": {**_kennzahlen(name)}}
    del quelle["ziel"]["gebiet"]
    b = _lauf(_config(tmp_path, {name: quelle}))
    assert _quelle(b, name)["unvollstaendig"]
    assert _abfrage("SELECT fehler, angehalten, unvollstaendig FROM pipeline_meta.lauf WHERE lauf_id = %s",
                    b["lauf_id"]) == [(0, 0, 1)]


# --- Code-Review 05.11. nach E43 (E44) ------------------------------------------------------------------

def test_ziel_und_gebiet_in_eigenem_schema(tmp_path, als_import):
    """F3: einrichten gab USAGE nur auf public und pipeline_meta. Ein Ziel oder eine Gebietstabelle in
    einem anderen Schema (`ziel.schema`, `gebiet.schema`) bekam zwar Tabellenrechte, war für die Rollen
    aber nicht erreichbar; die Quelle scheiterte erst im Lauf. Schemanamen mit Sonderzeichen werden
    als Bezeichner gequotet."""
    from psycopg import sql
    k = uuid.uuid4().hex[:6]
    s_ziel, s_gebiet, name = f"E44 Ziel {k}", f"e44-gebiet-{k}", f"test_{k}_schema"
    daten = tmp_path / "orte.csv"
    daten.write_text("ags;name\n12054000;Potsdam\n12051000;Brandenburg an der Havel\n", encoding="utf-8")
    quelle = {"typ": "csv", "pfad": str(daten), "trenner": ";", "id_spalte": "ags",
              "spalten": {"name": "name"}, "gebiet": {"schluessel_spalte": "ags"}, "lizenz": "Testdaten",
              "ziel": {"schema": s_ziel, "tabelle": "orte", "schluessel": ["kennziffer"],
                       "spalten": {"kennziffer": "_gebiet", "name": "name"},
                       "gebiet": {"schema": s_gebiet, "tabelle": "gebiete", "spalte": "ags",
                                  "zielspalte": "kennziffer"}}}
    voll = _voll()
    zs, gs = sql.Identifier(s_ziel), sql.Identifier(s_gebiet)
    try:
        with _admin() as c:
            c.execute(sql.SQL("CREATE SCHEMA {}; CREATE TABLE {}.orte (kennziffer text, name text); "
                              "CREATE SCHEMA {}; CREATE TABLE {}.gebiete (ags text); "
                              "INSERT INTO {}.gebiete VALUES ('12054000')").format(zs, zs, gs, gs, gs))
            einrichten.einrichten(c, {"quellen": {**voll["quellen"], name: quelle}})
            for rolle in ("pipeline_import", "mosidi_lesen"):
                for s in (s_ziel, s_gebiet):
                    recht = c.execute("SELECT has_schema_privilege(%s, %s, 'USAGE')", (rolle, s))
                    assert recht.fetchone()[0], (rolle, s)
        q = _quelle(_lauf(_config(tmp_path, {name: quelle})), name)
        assert q["status"] == "ok", q.get("fehler")
        assert q["zaehler"]["neu"] == 2 and q["info"]["gebiete"]["mit_flaeche"] == 1
        assert _abfrage(sql.SQL("SELECT kennziffer, name FROM {}.orte ORDER BY 1").format(zs)) == [
            ("12051000", "Brandenburg an der Havel"), ("12054000", "Potsdam")]
    finally:
        with _admin() as c:
            c.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE; DROP SCHEMA IF EXISTS {} CASCADE")
                      .format(zs, gs))
            einrichten.einrichten(c, voll)


def test_abgerissene_verbindung_bricht_den_lauf_nicht_ab(tmp_path, als_import, monkeypatch):
    """F5: Reißt die Verbindung während einer Quelle ab (hier vom Server beendet), lief protokollieren()
    auf der toten Verbindung und beendete den ganzen Lauf ohne regulären Bericht. Jetzt baut der Lauf
    die Verbindung neu auf: die Quelle ist fehlgeschlagen und protokolliert, die nächste läuft."""
    k, p = uuid.uuid4().hex[:6], uuid.uuid4().hex[:6]
    a, b = f"test_{k}_a", f"test_{k}_b"
    d_a, d_b = tmp_path / "a.csv", tmp_path / "b.csv"
    _punkte(d_a, [(f"{p}a", "Alpha", 52.41, 12.54)])
    _punkte(d_b, [(f"{p}b", "Beta", 52.40, 12.53)])
    cfg = _config(tmp_path, {a: _punkt_quelle(d_a), b: _punkt_quelle(d_b)})
    original = laden.quelle_laden

    def quelle(conn, name, *args, **kw):
        """Beendet vor dem Laden der Quelle a die Sitzung der Pipeline vom Server aus (pg_terminate_backend)
        und lädt dann wie gewohnt."""
        if name == a:
            with _admin() as c:
                c.execute("SELECT pg_terminate_backend(%s)", (conn.info.backend_pid,))
        return original(conn, name, *args, **kw)

    monkeypatch.setattr(laden, "quelle_laden", quelle)
    bericht = _lauf(cfg)
    qa, qb = _quelle(bericht, a), _quelle(bericht, b)
    assert qa["status"] == "fehler" and "AdminShutdown" in qa["fehler"]   # Unterklasse von OperationalError
    assert qb["status"] == "ok" and _zahlen(bericht, b)[0] == 1
    assert (Path(tmp_path / "berichte") / f"{bericht['lauf_id']}.json").exists() and "abbruch" not in bericht
    assert _abfrage("SELECT quelle, status FROM pipeline_meta.quellenlauf WHERE lauf_id = %s ORDER BY 1",
                    bericht["lauf_id"]) == [(a, "fehler"), (b, "ok")]
    assert _abfrage("SELECT fehler FROM pipeline_meta.lauf WHERE lauf_id = %s", bericht["lauf_id"]) == [(1,)]


def test_verbindung_im_leerlauf_beendet_naechste_quelle_bleibt_ok(tmp_path, als_import, monkeypatch):
    """E45: Beendet der Server die Sitzung zwischen zwei Quellen (Leerlauf, etwa ein Neustart während eines
    langen Downloads), sieht psycopg das erst beim nächsten Zugriff. Ohne Lebenstest scheiterte daran die
    Fälligkeit der nächsten Quelle, die selbst in Ordnung war. Ohne --alle, damit die Fälligkeit läuft."""
    k, p = uuid.uuid4().hex[:6], uuid.uuid4().hex[:6]
    a, b = f"test_{k}_a", f"test_{k}_b"
    d_a, d_b = tmp_path / "a.csv", tmp_path / "b.csv"
    _punkte(d_a, [(f"{p}a", "Alpha", 52.41, 12.54)])
    _punkte(d_b, [(f"{p}b", "Beta", 52.40, 12.53)])
    cfg = _config(tmp_path, {a: _punkt_quelle(d_a), b: _punkt_quelle(d_b)})
    original = laden.protokollieren

    def protokoll(conn, lauf_id, eintrag):
        """Protokolliert wie gewohnt und beendet danach, nur nach der Quelle a, die Sitzung der Pipeline vom
        Server aus."""
        original(conn, lauf_id, eintrag)
        if eintrag["quelle"] == a:   # nach dem Protokoll von a, vor der Fälligkeit von b
            with _admin() as c:
                c.execute("SELECT pg_terminate_backend(%s)", (conn.info.backend_pid,))

    monkeypatch.setattr(laden, "protokollieren", protokoll)
    bericht = _lauf(cfg)
    qa, qb = _quelle(bericht, a), _quelle(bericht, b)
    assert qa["status"] == "ok" and qb["status"] == "ok", (qa.get("fehler"), qb.get("fehler"))
    assert not qa["warnungen"] and not qb["warnungen"] and "abbruch" not in bericht
    assert _zahlen(bericht, a)[0] == 1 and _zahlen(bericht, b)[0] == 1
    assert _abfrage("SELECT quelle, status FROM pipeline_meta.quellenlauf WHERE lauf_id = %s ORDER BY 1",
                    bericht["lauf_id"]) == [(a, "ok"), (b, "ok")]
    assert _abfrage("SELECT fehler FROM pipeline_meta.lauf WHERE lauf_id = %s", bericht["lauf_id"]) == [(0,)]


# --- E46: Prüfbericht 05.11. (F2, F4, F10) ------------------------------------------------------------

def test_reparatur_mit_anderem_typ_gegen_single_zielfeld(tmp_path, als_import):
    """Prüfbericht 05.11., F4: ST_MakeValid, Transformation und Cast auf den Zieltyp liefen bis E45 in einer
    Abfrage über alle Objekte. Eine Fliege (Polygon, das sich selbst schneidet) wird zu einem MULTIPOLYGON
    repariert; gegen eine Spalte geometry(Polygon) brach der Cast die ganze Quelle ab (Status fehler, auch
    a nicht geladen). Jetzt je Objekt: b mit Warnung ausgelassen, Abruf unvollständig, b behält den
    bisherigen Stand (nichts gelöscht), a wird normal abgeglichen. Die MOSIDI-Tabellen haben keine
    Polygon-Spalte ohne Multi; deshalb eine eigene Tabelle in einem eigenen Schema."""
    from psycopg import sql
    k, p = uuid.uuid4().hex[:6], uuid.uuid4().hex[:6]
    schema, name = f"e46 polygon {k}", f"test_{k}_polygon"
    s = sql.Identifier(schema)
    daten = tmp_path / "flaechen.csv"
    quelle = {"typ": "csv", "pfad": str(daten), "id_spalte": "id", "wkt_spalte": "wkt", "srid": 4326,
              "spalten": {"name": "name"}, "lizenz": "Testdaten",
              "ziel": {"schema": schema, "tabelle": "flaechen", "schluessel": ["oid"], "geometrie": "geom",
                       "spalten": {"oid": "_id", "name": "name"}}}
    try:
        with _admin() as c:
            c.execute(sql.SQL("CREATE SCHEMA {}; CREATE TABLE {}.flaechen "
                              "(oid text, name text, geom geometry(Polygon, 4326))").format(s, s))
            einrichten.einrichten(c, {"quellen": {**_voll()["quellen"], name: quelle}})
        cfg = _config(tmp_path, {name: quelle})
        _flaechen(daten, [(f"{p}a", "A", 52.41, 12.54), (f"{p}b", "B", 52.40, 12.53)])
        assert _zahlen(_lauf(cfg), name) == (2, 0, 0, 0)
        x, y = 12.53, 52.40
        fliege = f"POLYGON(({x} {y},{x + .001} {y + .001},{x + .001} {y},{x} {y + .001},{x} {y}))"
        daten.write_text("id,name,wkt\n" + daten.read_text(encoding="utf-8").splitlines()[1] + "\n"
                         f'{p}b,B neu,"{fliege}"\n', encoding="utf-8")
        q = _quelle(_lauf(cfg), name)
        assert q["status"] == "ok", q.get("fehler")
        assert q["unvollstaendig"] and q["info"]["geometrie_nicht_umwandelbar"] == 1
        texte = " ".join(q["warnungen"])
        assert "nicht in den Typ der Zielspalte geom" in texte and f"{p}b" in texte
        z = q["zaehler"]
        assert (z["unveraendert"], z["geloescht"], z["zurueckgehalten"]) == (1, 0, 1)
        stand = sql.SQL("SELECT oid, name, GeometryType(geom) FROM {}.flaechen ORDER BY 1").format(s)
        assert _abfrage(stand) == [(f"{p}a", "A", "POLYGON"), (f"{p}b", "B", "POLYGON")]
    finally:
        with _admin() as c:
            c.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(s))
            einrichten.einrichten(c, _voll())


def test_katalog_view_wird_nach_dem_lauf_aktualisiert(tmp_path, als_import):
    """Antwort 75, Prüfbericht 05.11., F2: Neue Indikatoren erscheinen im Katalog von MOSIDI erst, wenn auch
    die Materialized View source_granularities aktualisiert ist. Die Importrolle darf das nicht selbst
    (REFRESH nur für den Eigentümer); sie ruft pipeline_meta.katalog_aktualisieren() auf (SECURITY DEFINER).
    Ohne Änderung kein Aufruf; ohne View ein Hinweis, kein Fehler. Die View steht nicht im mitgelieferten
    MOSIDI-Schema (sql/mosidi/); der Test legt eine mit derselben Rolle an wie das Schema."""
    k = uuid.uuid4().hex[:6]
    name, kz = f"test_{k}_katalog", f"96{uuid.uuid4().int % 10**6:06d}"
    daten = tmp_path / "werte.csv"
    cfg = _config(tmp_path, {name: _kennzahl_quelle(daten, name)})
    _kennzahlen_csv(daten, [(f"{k}1", kz, "A", "X", 2023, "1")])
    view = "SELECT granularity FROM source_granularities WHERE source = %s"
    try:
        with _admin() as c:
            c.execute("DELETE FROM pipeline_meta.katalog_offen")   # Reste anderer Tests (Abbrüche)
            c.execute("CREATE MATERIALIZED VIEW public.source_granularities AS "
                      "SELECT DISTINCT source, granularity FROM dashboard_data_de")
        with _als("pipeline_import", "IMPORT_PASSWORD") as imp, \
                pytest.raises(psycopg.errors.InsufficientPrivilege):
            imp.execute("REFRESH MATERIALIZED VIEW public.source_granularities")
        assert _abfrage(view, name) == []
        b = _lauf(cfg)
        assert _quelle(b, name)["status"] == "ok"
        assert b["katalog"] == {"view": "public.source_granularities", "ergebnis": "aktualisiert"}
        assert _abfrage(view, name) == [("Gemeinden",)]
        assert "katalog" not in _lauf(cfg, alle=True)        # Folgelauf ohne Änderung
    finally:
        with _admin() as c:
            c.execute("DROP MATERIALIZED VIEW IF EXISTS public.source_granularities")
    _kennzahlen_csv(daten, [(f"{k}1", kz, "A", "X", 2023, "2")])
    b = _lauf(cfg, alle=True)
    assert _quelle(b, name)["status"] == "ok" and b["katalog"]["ergebnis"] == "fehlt"
    assert "gibt es in dieser Datenbank nicht" in (tmp_path / "berichte" / f"{b['lauf_id']}.txt").read_text()


def test_katalogfunktion_nur_fuer_die_importrolle():
    """E46, F2: pipeline_meta.katalog_aktualisieren() läuft mit den Rechten ihres Eigentümers (SECURITY
    DEFINER; Eigentümer ist, wer einrichten zuerst ausgeführt hat). Deshalb fester search_path, kein Recht
    für PUBLIC, ausführen darf nur pipeline_import; die Leserolle scheitert mit InsufficientPrivilege."""
    # public: proacl NULL hieße Standardrechte, also EXECUTE für PUBLIC; grantee 0 ist PUBLIC in aclexplode
    ((definer, pfad, public, imp, lese),) = _abfrage(
        """SELECT p.prosecdef, 'search_path=pg_catalog, pg_temp' = ANY (p.proconfig),
                  p.proacl IS NULL OR EXISTS (SELECT 1 FROM aclexplode(p.proacl) x WHERE x.grantee = 0),
                  has_function_privilege('pipeline_import', p.oid, 'EXECUTE'),
                  has_function_privilege('mosidi_lesen', p.oid, 'EXECUTE')
           FROM pg_proc p WHERE p.oid = to_regprocedure('pipeline_meta.katalog_aktualisieren()')""")
    assert (definer, pfad, public, imp, lese) == (True, True, False, True, False)
    with _als("mosidi_lesen", "LESE_PASSWORD") as c, pytest.raises(psycopg.errors.InsufficientPrivilege):
        c.execute("SELECT pipeline_meta.katalog_aktualisieren()")


def test_datenbankweite_sperre_auch_aus_anderem_berichtsordner(tmp_path, als_import, monkeypatch):
    """Prüfbericht 05.11., F10: Die Startsperre galt je Berichtsordner; ein zweiter Lauf mit anderem Ordner
    (anderes Volume, anderer Rechner) konnte dieselbe Datenbank parallel bearbeiten. Jetzt hält jeder Lauf
    zusätzlich eine Sperre in der Datenbank (pg_advisory_lock). Hält sie ein anderer, bricht der Start ab:
    kein Bericht, nichts geschrieben. Während des Ladens hält die Verbindung der Pipeline die Sperre."""
    name, p = f"test_{uuid.uuid4().hex[:8]}", uuid.uuid4().hex[:6]
    daten = tmp_path / "daten.csv"
    _punkte(daten, [(f"{p}a", "Alpha", 52.41, 12.54)])
    cfg = _config(tmp_path, {name: _punkt_quelle(daten)})
    with _admin() as c:
        c.execute("SELECT pg_advisory_lock(%s)", (laden.DB_SPERRE,))
        try:
            # Neutral, mit der Sitzung, die die Sperre hält (Nachprüfung zu E46): Jede Rolle mit Zugang
            # zur Datenbank kann den Schlüssel nehmen, hier der Administrator
            with pytest.raises(laden.LaufLaeuftNoch,
                               match=f"derselben Datenbank .* hält Sitzung {c.info.backend_pid}:"):
                _lauf(cfg)
        finally:
            c.execute("SELECT pg_advisory_unlock(%s)", (laden.DB_SPERRE,))
    assert not list((tmp_path / "berichte").glob("2*"))    # Berichte heißen nach der Lauf-ID (20…T…Z)
    assert _abfrage('SELECT count(*) FROM "Baume" WHERE species LIKE %s', f"{p}%") == [(0,)]
    gehalten, original = [], laden.quelle_laden

    def quelle(conn, *a, **kw):
        """Zählt vor dem Laden der Quelle die gewährten Advisory-Sperren der Pipeline-Sitzung und lädt dann
        wie gewohnt."""
        with _admin() as c:
            gehalten.append(c.execute("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' "
                                      "AND granted AND pid = %s", (conn.info.backend_pid,)).fetchone()[0])
        return original(conn, *a, **kw)

    monkeypatch.setattr(laden, "quelle_laden", quelle)
    assert _zahlen(_lauf(cfg), name) == (1, 0, 0, 0) and gehalten == [1]


def test_einrichten_entzieht_ueberzaehlige_schreibrechte():
    """Prüfbericht 05.11., F10: einrichten ergänzte Rechte, entzog aber keine überholten. Jetzt stehen die
    Schreibrechte der Importrolle nach jedem Einrichten auf dem Sollstand der Konfiguration: überzählige
    Spalten (flood_risk füllt MOSIDI selbst), Tabellen ohne Ziel (Schule) und Rechte auf Tabellenebene, wo
    nur Spalten vorgesehen sind (table_metadata), werden entzogen; das Sollrecht bleibt."""
    def rechte(c):
        """Die sechs geprüften Rechte der Importrolle: UPDATE auf flood_risk, Schreiben in Schule, UPDATE auf
        table_metadata als Tabelle und auf dct_title, UPDATE auf name in Gebäude (ALKIS), DELETE auf Baume."""
        return c.execute("""
            SELECT has_column_privilege('pipeline_import', '"Gebäude (ALKIS)"', 'flood_risk', 'UPDATE'),
                   has_table_privilege('pipeline_import', '"Schule"', 'INSERT, UPDATE, DELETE'),
                   has_table_privilege('pipeline_import', 'table_metadata', 'UPDATE'),
                   has_column_privilege('pipeline_import', 'table_metadata', 'dct_title', 'UPDATE'),
                   has_column_privilege('pipeline_import', '"Gebäude (ALKIS)"', 'name', 'UPDATE'),
                   has_table_privilege('pipeline_import', '"Baume"', 'DELETE')""").fetchone()
    with _admin() as c:
        try:
            c.execute('GRANT UPDATE (flood_risk) ON "Gebäude (ALKIS)" TO pipeline_import')
            c.execute('GRANT INSERT, UPDATE, DELETE ON "Schule" TO pipeline_import')
            c.execute("GRANT UPDATE ON table_metadata TO pipeline_import")
            assert rechte(c) == (True, True, True, True, True, True)
            protokoll = einrichten.einrichten(c, _voll())
            assert rechte(c) == (False, False, False, True, True, True)
            assert any(z.startswith('REVOKE INSERT, UPDATE, DELETE ON "Schule"') for z in protokoll)
        finally:
            c.execute('REVOKE UPDATE (flood_risk) ON "Gebäude (ALKIS)" FROM pipeline_import')
            c.execute('REVOKE ALL ON "Schule" FROM pipeline_import')
            einrichten.einrichten(c, _voll())


# --- Nachprüfung zu E46 -------------------------------------------------------------------------------

def test_einrichten_meldet_fremd_vergebene_schreibrechte_statt_abzubrechen():
    """Nachprüfung zu E46 (Sollstand der Rechte, F10):
    (a) Ein REVOKE, das scheitert (Administrator ohne Superuser-Rechte, der auf der Tabelle selbst kein Recht
        hat: permission denied), rollte bis dahin das ganze einrichten zurück. Jetzt läuft jedes REVOKE in
        einem eigenen Sicherungspunkt; das Recht bleibt stehen, mit Warnung, die Transaktion lebt weiter.
    (b) Ein Recht, das eine andere Rolle vergeben hat, entzieht auch der Superuser nicht (er handelt als
        Eigentümer); einrichten zeigte trotzdem nur die REVOKE-Zeile. Jetzt liest es die Rechte danach neu
        und warnt mit dem, der sie vergeben hat.
    Dazu Sequenzen: USAGE auf eine Sequenz, die zu keinem Ziel mehr gehört, blieb stehen (nextval)."""
    k = uuid.uuid4().hex[:6]
    schema, fremd, admin_b = f"e46_r_{k}", f"e46_g_{k}", f"e46_a_{k}"
    t, seq = f"{schema}.t", f"{schema}.s"   # so, wie regclass sie ausgibt (ohne Anführungszeichen)
    with _admin() as c:
        try:
            c.execute(f"CREATE SCHEMA {schema}")
            c.execute(f"CREATE TABLE {t} (id int)")
            c.execute(f"CREATE SEQUENCE {seq}")
            for r in (fremd, admin_b):
                c.execute(f'CREATE ROLE "{r}" NOLOGIN NOSUPERUSER')
            c.execute(f'GRANT USAGE ON SCHEMA {schema} TO "{fremd}"')
            c.execute(f'GRANT INSERT ON {t} TO "{fremd}" WITH GRANT OPTION')
            c.execute(f"GRANT DELETE ON {t} TO pipeline_import")                 # vom Eigentümer
            c.execute(f"GRANT USAGE ON SEQUENCE {seq} TO pipeline_import")       # vom Eigentümer
            c.execute(f'SET ROLE "{fremd}"')
            c.execute(f"GRANT INSERT ON {t} TO pipeline_import")                 # von einer anderen Rolle
            c.execute("RESET ROLE")

            protokoll = einrichten.einrichten(c, _voll())
            ((loeschen, einfuegen, nutzen),) = c.execute(
                "SELECT has_table_privilege('pipeline_import', %s, 'DELETE'), "
                "has_table_privilege('pipeline_import', %s, 'INSERT'), "
                "has_sequence_privilege('pipeline_import', %s, 'USAGE')", (t, t, seq)).fetchall()
            assert (loeschen, einfuegen, nutzen) == (False, True, False)
            assert f'REVOKE USAGE, UPDATE ON SEQUENCE {seq} FROM "pipeline_import"' in protokoll
            (warnung,) = [z for z in protokoll if z.startswith("-- Warnung") and t in z]
            assert f"INSERT von {fremd}" in warnung and "nicht entziehen" in warnung

            # (a) als Administrator ohne Superuser-Rechte und ohne Recht auf das Schema
            with c.transaction(force_rollback=True), c.cursor() as cur:
                cur.execute(f'SET LOCAL ROLE "{admin_b}"')
                zeilen: list[str] = []
                warnungen = einrichten._entziehen(cur, zeilen)
                cur.execute("SELECT 1")                         # Transaktion nicht abgebrochen
                assert any(t in w and "gescheitert" in w and "permission denied" in w for w in warnungen)
                assert not any(t in z for z in zeilen)          # nur ausgeführte REVOKE im Protokoll
        finally:
            c.execute("RESET ROLE")
            c.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
            for r in (fremd, admin_b):
                c.execute(f'DROP ROLE IF EXISTS "{r}"')


def test_katalogpruefung_nach_dem_eigentuemer_der_funktion():
    """Nachprüfung zu E46: Wem katalog_aktualisieren() gehört, legt das erste einrichten fest; CREATE OR
    REPLACE ändert den Eigentümer nicht. Die Prüfung sah auf current_user: Ein Superuser, der einrichten
    „erneut“ ausführte, bekam keine Warnung, obwohl die Funktion (Eigentümer ohne Recht auf die View) an
    „must be owner“ scheiterte. Jetzt prüft einrichten den Eigentümer der Funktion und nennt die Abhilfe."""
    rolle, admin = f"e46_f_{uuid.uuid4().hex[:6]}", os.environ.get("POSTGRES_USER", "admin")
    with _admin() as c:
        try:
            c.execute("CREATE MATERIALIZED VIEW public.source_granularities AS "
                      "SELECT DISTINCT source, granularity FROM dashboard_data_de")
            c.execute(f'CREATE ROLE "{rolle}" NOLOGIN NOSUPERUSER')
            c.execute(f'ALTER FUNCTION pipeline_meta.katalog_aktualisieren() OWNER TO "{rolle}"')
            protokoll = einrichten.einrichten(c, _voll())    # als Superuser erneut ausgeführt
            eigentuemer = c.execute("SELECT pg_get_userbyid(proowner) FROM pg_proc WHERE oid = "
                                    "to_regprocedure('pipeline_meta.katalog_aktualisieren()')").fetchone()
            assert eigentuemer == (rolle,)
            (warnung,) = [z for z in protokoll if "katalog_aktualisieren() gehört" in z]
            assert f"gehört {rolle}," in warnung and f"Eigentümer der View: {admin}" in warnung
            assert f'ALTER FUNCTION pipeline_meta.katalog_aktualisieren() OWNER TO "{admin}"' in warnung
            with _als("pipeline_import", "IMPORT_PASSWORD") as imp, \
                    pytest.raises(psycopg.errors.InsufficientPrivilege,
                                  match="must be owner|permission denied"):   # 16 | ab 17 (MAINTAIN)
                imp.execute("SELECT pipeline_meta.katalog_aktualisieren()")
            if c.info.server_version >= 170000:   # ab 17 genügt MAINTAIN: Warnung nennt es, Prüfung kennt es
                assert f'GRANT MAINTAIN ON public.source_granularities TO "{rolle}"' in warnung
                c.execute(f'GRANT MAINTAIN ON public.source_granularities TO "{rolle}"')
                protokoll = einrichten.einrichten(c, _voll())
                assert not any("katalog_aktualisieren() gehört" in z for z in protokoll)
                with _als("pipeline_import", "IMPORT_PASSWORD") as imp:
                    ergebnis = imp.execute("SELECT pipeline_meta.katalog_aktualisieren()").fetchone()
                    assert ergebnis == ("aktualisiert",)
                c.execute(f'REVOKE MAINTAIN ON public.source_granularities FROM "{rolle}"')
            # Die genannte Abhilfe
            c.execute(f'ALTER FUNCTION pipeline_meta.katalog_aktualisieren() OWNER TO "{admin}"')
            assert not any("katalog_aktualisieren() gehört" in z for z in einrichten.einrichten(c, _voll()))
            with _als("pipeline_import", "IMPORT_PASSWORD") as imp:
                ergebnis = imp.execute("SELECT pipeline_meta.katalog_aktualisieren()").fetchone()
                assert ergebnis == ("aktualisiert",)
        finally:
            c.execute(f'ALTER FUNCTION pipeline_meta.katalog_aktualisieren() OWNER TO "{admin}"')
            c.execute("DROP MATERIALIZED VIEW IF EXISTS public.source_granularities")
            c.execute(f'DROP ROLE IF EXISTS "{rolle}"')


def test_katalog_wird_nach_gescheitertem_aufruf_nachgeholt(tmp_path, als_import, monkeypatch):
    """Nachprüfung zu E46: Scheiterte REFRESH (hier: Wartegrenze, weil ein Leser die View hält), stand die
    Warnung nur im Bericht dieses Laufs; der nächste Lauf ohne Änderung rief den Katalog nicht auf, --status
    sprang auf OK, der Katalog blieb alt. Jetzt merkt sich pipeline_meta.katalog_offen die offene
    Aktualisierung (mit den Daten geschrieben), und der nächste Lauf holt sie nach. Der Fehlertext steht auf
    einer Zeile (aus PL/pgSQL kommt er mit einer Zeile CONTEXT)."""
    k = uuid.uuid4().hex[:6]
    name, kz = f"test_{k}_nachholen", f"95{uuid.uuid4().int % 10**6:06d}"
    daten = tmp_path / "werte.csv"
    cfg = _config(tmp_path, {name: _kennzahl_quelle(daten, name)})
    _kennzahlen_csv(daten, [(f"{k}1", kz, "A", "X", 2023, "1")])
    view = "SELECT granularity FROM source_granularities WHERE source = %s"
    offen = "SELECT lauf_id FROM pipeline_meta.katalog_offen ORDER BY 1"
    # Kurze Wartegrenze für REFRESH: Der Leser unten hält die View, der Aufruf soll schnell scheitern
    monkeypatch.setattr(laden, "KATALOG_WARTEN", "300ms")
    leser = None
    try:
        with _admin() as c:
            c.execute("DELETE FROM pipeline_meta.katalog_offen")
            c.execute("CREATE MATERIALIZED VIEW public.source_granularities AS "
                      "SELECT DISTINCT source, granularity FROM dashboard_data_de")
        leser = psycopg.connect("", user=os.environ.get("POSTGRES_USER", "admin"),
                                password=os.environ["POSTGRES_PASSWORD"])
        # Ohne autocommit bleibt die Transaktion offen; ihr ACCESS SHARE blockiert das ACCESS EXCLUSIVE von
        # REFRESH, bis leser.rollback() sie beendet
        leser.execute("SELECT count(*) FROM public.source_granularities")   # hält die Sperre bis rollback
        b1 = _lauf(cfg)
        assert _quelle(b1, name)["status"] == "ok" and b1["katalog"]["ergebnis"] == "fehler"
        fehler = b1["katalog"]["fehler"]
        assert "lock timeout" in fehler and "CONTEXT" in fehler and "\n" not in fehler
        assert _abfrage(offen) == [(b1["lauf_id"],)]
        code, zeile = betrieb.status(tmp_path / "berichte", 26)
        assert code == betrieb.WARNUNG and "\n" not in zeile
        leser.rollback()
        b2 = _lauf(cfg, alle=True)                                          # ohne Änderung
        assert _zahlen(b2, name) == (0, 0, 0, 1)
        assert b2["katalog"] == {"view": "public.source_granularities", "ergebnis": "aktualisiert",
                                 "nachgeholt": [b1["lauf_id"]]}
        assert _abfrage(view, name) == [("Gemeinden",)] and _abfrage(offen) == []
        assert betrieb.status(tmp_path / "berichte", 26)[0] == betrieb.OK
        assert "katalog" not in _lauf(cfg, alle=True)                       # nichts mehr offen
    finally:
        if leser is not None:
            leser.close()
        with _admin() as c:
            c.execute("DROP MATERIALIZED VIEW IF EXISTS public.source_granularities")


def test_partieller_eindeutiger_index_belegt_keinen_metadatensatz(tmp_path, als_import):
    """Nachprüfung zu E46: metadaten_belegt las alle eindeutigen Indizes von table_metadata, auch partielle
    (mit WHERE), und hielt eine Quelle an, deren Zeile gar nicht unter die Bedingung fällt. Der Test legt
    einen solchen Index an (und entfernt ihn wieder): zwei Quellen mit verschiedenen Indikatoren auf
    derselben Raumebene, der Index nur über die Raumebene für eine Art, die keine der Zeilen hat."""
    k = uuid.uuid4().hex[:6]
    a, b = f"test_{k}_ta", f"test_{k}_tb"
    quellen = {}
    for name in (a, b):
        d = tmp_path / f"{name}.csv"
        d.write_text(f"ags;bev\n{k}01;1\n", encoding="utf-8")
        z = {**_kennzahlen(name), "je_wert": {"bev": f"Bevölkerung {k} {name}"}}
        del z["gebiet"]
        quellen[name] = {"typ": "csv", "pfad": str(d), "trenner": ";", "id_spalte": "ags",
                         "spalten": {"bev": "bev"}, "zahl_felder": ["bev"], "zeitbezug": "2024-12-31",
                         "gebiet": {"schluessel_spalte": "ags"}, "lizenz": "Testdaten", "ziel": z}
    cfg = _config(tmp_path, quellen)
    index = f"e46_teil_{k}"
    try:
        with _admin() as c:
            c.execute(f'CREATE UNIQUE INDEX "{index}" ON table_metadata (dcatde_politicalgeocodingleveluri) '
                      f"WHERE dct_type = '{index}'")
        bericht = _lauf(cfg)
        for name in (a, b):
            q = _quelle(bericht, name)
            assert q["status"] == "ok" and q["info"]["metadaten"] == 1, (name, q.get("warnungen"))
            assert not q["info"].get("metadaten_belegt")
    finally:
        with _admin() as c:
            c.execute(f'DROP INDEX IF EXISTS public."{index}"')


# --- E47: Prüfbericht vom 05.11.2026 abends -------------------------------------------------------------

def test_csv_beschaedigte_datenzeile_im_vorfilter_sperrt_das_loeschen(tmp_path, als_import):
    """Befund 1: Über die Statistiktabelle im CSV-Aufbau (_statistik_csv, zeilen_muster '^12\\d{6};'). Eine
    Gemeinde, deren Schlüssel in der Datei beschädigt ist, fiel vor jeder Prüfung aus dem Vorfilter; ihre
    Werte wurden gelöscht (bis E46: 3 gelöscht). Jetzt ist der Abruf unvollständig, nichts wird gelöscht."""
    k = uuid.uuid4().hex[:6]
    name = f"test_{k}_vorfilter"
    kz = [f"12{uuid.uuid4().int % 10**6:06d}" for _ in range(4)]
    cfg_q = _statistik_csv()
    datei = tmp_path / f"{name}.csv"
    cfg_q.update(pfad=str(datei), rhythmus=None)
    cfg_q["ziel"] = {**cfg_q["ziel"], "fest": {**cfg_q["ziel"]["fest"], "source": name}}
    del cfg_q["ziel"]["metadaten"]   # feste Indikatornamen, wie in test_csv_leere_zeilen_…

    def schreiben(zeilen):
        """Schreibt die Statistiktabelle (latin-1) mit Kopf zum Stichtag 31.12.2025 und einer Zeile je
        Schlüssel (Werte 100, 50, 50); die erste Datenzeile ist Zeile 9 der Datei."""
        kopf = ("Tabelle: 12411-01-01-5-B\nBevölkerung;;;;\nEbenen;;;;\nFortschreibung;;;;\nBestand;;;;\n"
                ";;Stichtag;Stichtag;Stichtag\n;;31.12.2025;31.12.2025;31.12.2025\n"
                ";;Insgesamt;männlich;weiblich\n")
        datei.write_text(kopf + "".join(f"{a};Ort;100;50;50\n" for a in zeilen) + "Fußnote;;;;\n",
                         encoding="latin-1")

    cfg = _config(tmp_path, {name: cfg_q})
    schreiben(kz)
    q = _quelle(_lauf(cfg), name)
    assert q["status"] == "ok" and q["zaehler"]["neu"] == 12
    beschaedigt = kz[3][:4] + "O" + kz[3][5:]      # eine Ziffer als Buchstabe O
    schreiben([kz[0], beschaedigt, kz[1], kz[2]])
    q = _quelle(_lauf(cfg, alle=True), name)
    assert q["status"] == "ok" and q["unvollstaendig"], q["warnungen"]
    assert (q["zaehler"]["geloescht"], q["zaehler"]["zurueckgehalten"]) == (0, 3)
    assert any("1 Datenzeilen ohne gültigen Gebietsschlüssel übergangen (Zeilen 10)" in w
               for w in q["warnungen"]), q["warnungen"]
    assert _abfrage("SELECT count(*) FROM dashboard_data_de WHERE source = %s AND kennziffer = %s",
                    name, kz[3]) == [(3,)]


def test_datum_mit_zeitzone_z_wird_ohne_kennung_uebernommen(tmp_path, als_import):
    """Befund 3: aktualit (varchar(10)) kam vom ALKIS-WFS der LGB als JJJJ-MM-TTZ (882 von 882 Gebäuden des
    Ausschnitts, Abruf 05.11.2026) und wurde auf zehn Zeichen gekürzt. Jetzt gilt nur genau diese Form als
    verlustfrei normalisierbar (Kennzeichen Z weg, der Tag bleibt); jede andere zu lange Form wird
    zurückgehalten, nicht gekürzt."""
    name, p = f"test_{uuid.uuid4().hex[:8]}", uuid.uuid4().hex[:6]
    daten = tmp_path / "gebaeude.csv"
    zeilen = [(f"{p}a", "2020-09-03Z"), (f"{p}b", "2020-09-03+01:00"), (f"{p}c", "2015-10-15")]
    daten.write_text("id,name,wkt,aktualit\n" + "".join(
        f'{i},Haus,"POLYGON((12.5 52.4,12.501 52.4,12.501 52.401,12.5 52.401,12.5 52.4))",{a}\n'
        for i, a in zeilen), encoding="utf-8")
    quelle = _flaechen_quelle(daten, spalten={"name": "name", "aktualit": "aktualit"},
                              ziel={**GEBAEUDE, "spalten": {**GEBAEUDE["spalten"], "aktualit": "aktualit"}})
    q = _quelle(_lauf(_config(tmp_path, {name: quelle})), name)
    assert q["status"] == "ok"
    assert q["info"]["normalisiert"] == {"aktualit": 1} and q["info"]["zu_lang"] == {"aktualit": 1}
    assert any("1 Werte in aktualit als Datum ohne Zeitzonenkennung Z übernommen" in h for h in q["hinweise"])
    assert any("1 Objekt mit aktualit länger als 10 Zeichen (bis 16), nicht übernommen" in w
               for w in q["warnungen"]), q["warnungen"]
    assert _abfrage('SELECT oid, aktualit FROM "Gebäude (ALKIS)" WHERE oid LIKE %s ORDER BY oid',
                    f"{p}%") == [(f"{p}a", "2020-09-03"), (f"{p}c", "2015-10-15")]


def test_einrichten_bricht_ab_bei_zu_weiter_vorhandener_rolle():
    """Befund 11: Eine vorhandene Import- oder Leserolle mit CREATEDB oder einer Rollenmitgliedschaft
    (hier pg_read_all_data) behielt diese Rechte, einrichten setzte nur das Passwort. Jetzt bricht einrichten
    ab, bevor es etwas ändert, und nennt die Abhilfe."""
    with _admin() as c:
        try:
            c.execute("ALTER ROLE pipeline_import CREATEDB")
            with pytest.raises(einrichten.RolleZuWeit, match="pipeline_import.*CREATEDB.*NOCREATEDB"):
                einrichten.einrichten(c, _voll())
            c.execute("ALTER ROLE pipeline_import NOCREATEDB")
            c.execute("GRANT pg_read_all_data TO mosidi_lesen")
            with pytest.raises(einrichten.RolleZuWeit, match="REVOKE pg_read_all_data FROM mosidi_lesen"):
                einrichten.einrichten(c, _voll())
        finally:
            c.execute("ALTER ROLE pipeline_import NOCREATEDB")
            c.execute("REVOKE pg_read_all_data FROM mosidi_lesen")
            einrichten.einrichten(c, _voll())


# --- Nachprüfung zu E47 (05.11.2026 spät) ---------------------------------------------------------------

@pytest.mark.parametrize("vorhanden", [False, True], ids=["neu", "vorhanden"])
@pytest.mark.parametrize("reihenfolge", ["fehlwert_zuerst", "zu_lang_zuerst"])
def test_doppelter_schluessel_fehlwert_und_zu_lang_gilt_als_widerspruch(tmp_path, als_import, vorhanden,
                                                                       reihenfolge):
    """Nachprüfung zu E47 (Befund 1 der Prüfer): In `neu` steht ein zu langer Wert als NULL. Kam derselbe
    Schlüssel zweimal, einmal mit Fehlwert ('-' wird None), einmal mit zu langem Text, galten beide Zeilen
    als gleich; je nach Reihenfolge fiel die Zeile mit dem Merkmal `_zu_lang` weg und NULL wurde geladen
    (vorhandenes Objekt: „Haus A“ durch NULL überschrieben). Jetzt gehört `_zu_lang` zur Gleichheit: Das
    Paar ist ein Widerspruch, der Schlüssel wird ausgelassen, sein bisheriger Stand bleibt."""
    name, p = f"test_{uuid.uuid4().hex[:8]}", uuid.uuid4().hex[:6]
    daten = tmp_path / "gebaeude.csv"
    lang = "Haus " + "x" * 300                     # name ist varchar(254)
    cfg = _config(tmp_path, {name: _flaechen_quelle(daten)})
    b = (f"{p}b", "Haus B", 52.40, 12.53)          # damit die Quelle nicht leer ist
    if vorhanden:
        _flaechen(daten, [(f"{p}a", "Haus A", 52.41, 12.54), b])
        assert _zahlen(_lauf(cfg), name) == (2, 0, 0, 0)
    paar = [(f"{p}a", "-", 52.41, 12.54), (f"{p}a", lang, 52.41, 12.54)]
    _flaechen(daten, (paar if reihenfolge == "fehlwert_zuerst" else paar[::-1]) + [b])
    q = _quelle(_lauf(cfg), name)
    assert q["status"] == "ok", q
    assert (q["zaehler"]["neu"], q["zaehler"]["geaendert"], q["zaehler"]["geloescht"]) == \
        (0 if vorhanden else 1, 0, 0), q
    assert any("1 Schlüssel mehrfach mit verschiedenen Werten geliefert, ausgelassen" in w
               for w in q["warnungen"]), q["warnungen"]
    assert not any("gleichen Werten" in h for h in q["hinweise"]), q["hinweise"]
    erwartet = ([(f"{p}a", "Haus A")] if vorhanden else []) + [(f"{p}b", "Haus B")]
    assert _abfrage('SELECT oid, name FROM "Gebäude (ALKIS)" WHERE oid LIKE %s ORDER BY oid',
                    f"{p}%") == erwartet


@pytest.mark.parametrize("schaden", [" {}", "{} ", '"{}"', "\t{}"],
                         ids=["leer_vorn", "leer_hinten", "anfuehrungszeichen", "tab"])
def test_csv_schluessel_mit_rand_im_vorfilter_sperrt_das_loeschen(tmp_path, als_import, schaden):
    """Nachprüfung zu E47 (Befunde 2 und 4 der Prüfer), Statistiktabelle im CSV-Aufbau (_statistik_csv): Ein
    Brandenburger Schlüssel mit Leerzeichen am Rand, in Anführungszeichen oder mit Tab davor passte nicht zu
    `zeilen_muster`, galt nach strip() aber als gültiger Schlüssel eines anderen Gebiets. Die Gemeinde
    verschwand still, ihre drei Werte wurden gelöscht. Jetzt unvollständig, nichts gelöscht."""
    k = uuid.uuid4().hex[:6]
    name = f"test_{k}_rand"
    kz = [f"12{uuid.uuid4().int % 10**6:06d}" for _ in range(4)]
    cfg_q = _statistik_csv()
    datei = tmp_path / f"{name}.csv"
    cfg_q.update(pfad=str(datei), rhythmus=None)
    cfg_q["ziel"] = {**cfg_q["ziel"], "fest": {**cfg_q["ziel"]["fest"], "source": name}}
    del cfg_q["ziel"]["metadaten"]

    def schreiben(zeilen):
        """Schreibt die Statistiktabelle (latin-1) mit Kopf zum Stichtag 31.12.2025 und einer Zeile je
        Schlüssel (Werte 100, 50, 50); die erste Datenzeile ist Zeile 9 der Datei."""
        kopf = ("Tabelle: 12411-01-01-5-B\nBevölkerung;;;;\nEbenen;;;;\nFortschreibung;;;;\nBestand;;;;\n"
                ";;Stichtag;Stichtag;Stichtag\n;;31.12.2025;31.12.2025;31.12.2025\n"
                ";;Insgesamt;männlich;weiblich\n")
        datei.write_text(kopf + "".join(f"{a};Ort;100;50;50\n" for a in zeilen) + "Fußnote;;;;\n",
                         encoding="latin-1")

    cfg = _config(tmp_path, {name: cfg_q})
    schreiben(kz)
    assert _quelle(_lauf(cfg), name)["zaehler"]["neu"] == 12
    schreiben([kz[0], schaden.format(kz[3]), kz[1], kz[2]])
    q = _quelle(_lauf(cfg, alle=True), name)
    assert q["status"] == "ok" and q["unvollstaendig"], q["warnungen"]
    assert q["zaehler"]["geloescht"] == 0, q["zaehler"]
    assert any("(Zeilen 10)" in w for w in q["warnungen"]), q["warnungen"]
    assert _abfrage("SELECT count(*) FROM dashboard_data_de WHERE source = %s AND kennziffer = %s",
                    name, kz[3]) == [(3,)]


def test_einrichten_bricht_ab_wenn_der_importrolle_eine_tabelle_gehoert():
    """Nachprüfung zu E47 (Befund 7 der Prüfer): Die Rollenprüfung sah kein Eigentum. Gehört der Importrolle
    eine Tabelle, hat sie dort alle Rechte (auch DDL und TRUNCATE), unabhängig von den GRANTs, die einrichten
    zurücksetzt. Jetzt bricht einrichten ab, bevor es etwas ändert; temporäre Objekte zählen nicht."""
    tabelle = f"test_eigen_{uuid.uuid4().hex[:6]}"
    with _admin() as c:
        try:
            c.execute(f'CREATE TABLE public."{tabelle}" (id int)')
            c.execute(f'ALTER TABLE public."{tabelle}" OWNER TO pipeline_import')
            with pytest.raises(einrichten.RolleZuWeit,
                               match=f"pipeline_import.*Eigentümerin von Tabelle .*{tabelle}.*"
                                     "REASSIGN OWNED"):
                einrichten.einrichten(c, _voll())
        finally:
            c.execute(f'DROP TABLE IF EXISTS public."{tabelle}"')
            einrichten.einrichten(c, _voll())
    # Temporäre Tabellen und Funktionen einer offenen Sitzung der Importrolle (wie neu_bilden und GEOM_LESEN
    # während eines Laufs) sperren einrichten nicht; festgeschrieben, sonst sähe die andere Sitzung sie nicht
    with _als("pipeline_import", "IMPORT_PASSWORD") as imp, _admin() as c:
        imp.execute("CREATE TEMP TABLE neu_probe (id int)")
        imp.execute("CREATE FUNCTION pg_temp.probe() RETURNS int LANGUAGE sql AS 'SELECT 1'")
        imp.commit()
        assert c.execute("SELECT count(*) FROM pg_class WHERE relname = 'neu_probe' AND relowner = "
                         "to_regrole('pipeline_import')").fetchone() == (1,)
        einrichten.einrichten(c, _voll())


# --- E48: Statistischer Bericht des Amts für Statistik als XLSX, Konfiguration aus config/quellen.yaml ---

def _afs_quelle(name: str, quelle: str, datei: Path) -> dict:
    """Die Quelle aus config/quellen.yaml, wie ausgeliefert; geändert sind nur die Bezugsart (abgelegte Datei
    statt Seite, Antwort 33), source und der Rhythmus. Ohne table_metadata wie in test_csv_leere_zeilen_…"""
    q = yaml.safe_load(KONFIG.read_text(encoding="utf-8"))["quellen"][quelle]
    for k in ("seite", "datei_muster", "link_rechner"):
        q.pop(k)
    q.update(pfad=str(datei), rhythmus=None)
    q["ziel"] = {**q["ziel"], "fest": {**q["ziel"]["fest"], "source": name}}
    del q["ziel"]["metadaten"]
    return q


def test_xlsx_bevoelkerung_auswahl_loeschsperre_blatt_und_stichtag(tmp_path, als_import):
    """bevoelkerung_gemeinden über den Konfigurationspfad (E48): geladen werden kreisangehörige Gemeinden und
    kreisfreie Städte (28 + 4 = 32), keine Kreis- und Landessummen; ein beschädigter Schlüssel und ein
    fehlendes Blatt löschen nichts; der Stichtag des nächsten Berichts kommt aus dem Blatttitel der Datei."""
    from conftest import afs_bericht, gemeinden_je_kreis

    name = f"test_{uuid.uuid4().hex[:6]}_afs"
    datei = tmp_path / "bericht.xlsx"
    cfg = _config(tmp_path, {name: _afs_quelle(name, "bevoelkerung_gemeinden", datei)})
    kreise = gemeinden_je_kreis()
    afs_bericht(datei, kreise=kreise)
    q = _quelle(_lauf(cfg), name)
    assert q["status"] == "ok" and not q["unvollstaendig"] and q["zaehler"]["neu"] == 32, q
    zeilen = _abfrage("SELECT kennziffer, zeitbezug, wert FROM dashboard_data_de WHERE source = %s", name)
    kz = {k for k, _, _ in zeilen}
    assert {"12051000", "12054000", "12060001", "12073002"} <= kz and len(kz) == 32
    assert not {"12060000", "12073000", "12000000"} & kz
    assert {z for _, z, _ in zeilen} == {2025}
    assert ("12054000", 2025, Decimal(180000)) in zeilen

    # Beschädigter Schlüssel (Buchstabe O): Zeile übergangen, Abruf unvollständig, der Wert bleibt
    schaden = {**kreise, "3.1": [("12O60001", 1001, 10.51), *kreise["3.1"][1:]]}
    afs_bericht(datei, kreise=schaden)
    q = _quelle(_lauf(cfg, alle=True), name)
    assert q["status"] == "ok" and q["unvollstaendig"], q["warnungen"]
    assert (q["zaehler"]["geloescht"], q["zaehler"]["zurueckgehalten"]) == (0, 1), q["zaehler"]
    assert any("Blatt 3.1, Zeile 7" in w for w in q["warnungen"]), q["warnungen"]
    assert _abfrage("SELECT count(*) FROM dashboard_data_de WHERE source = %s AND kennziffer = '12060001'",
                    name) == [(1,)]

    # Fehlendes Blatt: ein Landkreis weniger (2 von 32 Zeilen) bliebe unter der Schwelle des
    # Rückgang-Schutzes; die Quelle hält trotzdem an, weil die Konfiguration jedes Blatt einzeln verlangt
    # (blaetter) und der Adapter das fehlende als fehlendes Feld meldet
    afs_bericht(datei, kreise=kreise, ohne_blatt="3.7")
    q = _quelle(_lauf(cfg, alle=True), name)
    assert q["status"] == "angehalten", q
    assert _abfrage("SELECT count(*) FROM dashboard_data_de WHERE source = %s", name) == [(32,)]

    # Nächster Bericht: Stichtag 31.12.2026 aus dem Titel, kein fester Wert in der Konfiguration
    afs_bericht(datei, kreise=kreise, jahr=2026)
    q = _quelle(_lauf(cfg, alle=True), name)
    assert q["status"] == "ok" and not q["unvollstaendig"], q["warnungen"]
    assert (q["zaehler"]["neu"], q["zaehler"]["geloescht"]) == (32, 32), q["zaehler"]
    assert _abfrage("SELECT DISTINCT zeitbezug FROM dashboard_data_de WHERE source = %s", name) == [(2026,)]


@pytest.mark.parametrize("neu", ["12060002", "12061009"], ids=["vorhanden", "fremder_kreis"])
def test_xlsx_geaenderter_schluessel_loescht_nichts(tmp_path, als_import, neu):
    """Prüfung nach E48: Wird 12060001 in beiden Schlüsselspalten zu einem anderen gültigen Schlüssel, stimmen
    Spalten-Gegenprobe und Landessumme. Vorhanden (12060002): Schlüssel mehrfach. In einem fremden Kreis
    (12061009): keine Teilsumme des Blatts. Beides sperrt das Löschen; 12060001 bleibt."""
    from conftest import afs_bericht, gemeinden_je_kreis

    name = f"test_{uuid.uuid4().hex[:6]}_afs_dop"
    datei = tmp_path / "bericht.xlsx"
    cfg = _config(tmp_path, {name: _afs_quelle(name, "bevoelkerung_gemeinden", datei)})
    kreise = gemeinden_je_kreis()
    afs_bericht(datei, kreise=kreise)
    assert _quelle(_lauf(cfg), name)["zaehler"]["neu"] == 32
    afs_bericht(datei, kreise={**kreise, "3.1": [(neu, 1001, 10.51), *kreise["3.1"][1:]]})
    q = _quelle(_lauf(cfg, alle=True), name)
    assert q["unvollstaendig"] and q["zaehler"]["geloescht"] == 0, q
    assert _abfrage("SELECT wert FROM dashboard_data_de WHERE source = %s AND kennziffer = '12060001'",
                    name) == [(Decimal(1001),)]


def test_xlsx_flaeche_mit_stand_der_fussnote(tmp_path, als_import):
    """flaeche_gemeinden über den Konfigurationspfad: Zeitbezug aus der Fußnote (Stand 31.12.2024), nicht aus
    dem Berichtsjahr 2025."""
    from conftest import afs_bericht

    name = f"test_{uuid.uuid4().hex[:6]}_afs_fl"
    datei = tmp_path / "bericht.xlsx"
    cfg = _config(tmp_path, {name: _afs_quelle(name, "flaeche_gemeinden", datei)})
    # Bestand wie bis E47 mit Zeitbezug 2025 (Regionaldatenbank, Stichtag 31.12.2025); das AfS liefert den
    # Stand 31.12.2024. zeitbezug gehört zum Zielschlüssel: alle Zeilen neu, die alten gelöscht, gleich viele,
    # der Rückgang-Schutz greift nicht (Prüfung nach E48, Befund zu docs/betrieb.md)
    afs_bericht(datei, flaeche_stand="31.12.2025")
    q = _quelle(_lauf(cfg), name)
    assert q["status"] == "ok" and q["zaehler"]["neu"] == 32, q
    afs_bericht(datei, flaeche_stand="31.12.2024")
    q = _quelle(_lauf(cfg, alle=True), name)
    assert q["status"] == "ok" and not q["unvollstaendig"], q
    assert (q["zaehler"]["neu"], q["zaehler"]["geloescht"]) == (32, 32), q["zaehler"]
    assert _abfrage("SELECT DISTINCT zeitbezug, indikator FROM dashboard_data_de WHERE source = %s",
                    name) == [(2024, "Gebietsfläche in km² (Stichtag 31.12.)")]
    assert _abfrage("SELECT wert FROM dashboard_data_de WHERE source = %s AND kennziffer = '12051000'",
                    name) == [(Decimal("229.73"),)]


# --- E50: Prüfbericht vom 06.11.2026, 13:26 (W6, W7, Kartensortierung) -------------------------------------

def test_zeitbudget_rollt_nur_diese_quelle_zurueck(tmp_path, als_import):
    """E50, Befund W6: Überschreitet eine Quelle ihr Zeitbudget (zeitbudget_min, hier wenige Mikrosekunden),
    wird ihre Transaktion zurückgerollt: kein neuer Datensatz, der alte Stand bleibt. Der Bericht führt sie
    als fehlgeschlagen mit dem Grund „Zeitbudget“, ohne Meldungsentwurf an den Anbieter, und die nächste
    Quelle lädt normal."""
    langsam, schnell, p = f"test_{uuid.uuid4().hex[:8]}", f"test_{uuid.uuid4().hex[:8]}", uuid.uuid4().hex[:6]
    d1, d2 = tmp_path / "a.csv", tmp_path / "b.csv"
    _punkte(d1, [(f"{p}a{i}", f"A{i}", 52.4 + i / 1000, 12.5) for i in range(3)])
    _punkte(d2, [(f"{p}b{i}", f"B{i}", 52.4 + i / 1000, 12.6) for i in range(2)])
    cfg = _config(tmp_path, {langsam: _punkt_quelle(d1), schnell: _punkt_quelle(d2)})
    _lauf(cfg)
    _punkte(d1, [(f"{p}a{i}", f"A{i} neu", 52.4 + i / 1000, 12.5) for i in range(5)])
    _punkte(d2, [(f"{p}b{i}", f"B{i}", 52.4 + i / 1000, 12.6) for i in range(3)])
    cfg = _config(tmp_path, {langsam: _punkt_quelle(d1, zeitbudget_min=0.000001), schnell: _punkt_quelle(d2)})
    b = _lauf(cfg)
    q = _quelle(b, langsam)
    assert q["status"] == "fehler" and q["fehler"].startswith("ZeitbudgetUeberschritten: Zeitbudget")
    assert "meldung" not in q and _quelle(b, schnell)["status"] == "ok"
    assert _abfrage('SELECT species, leaf_type FROM "Baume" WHERE species LIKE %s ORDER BY 1', f"{p}a%") == [
        (f"{p}a{i}", f"A{i}") for i in range(3)]
    assert _abfrage('SELECT count(*) FROM "Baume" WHERE species LIKE %s', f"{p}b%") == [(3,)]
    assert _abfrage("SELECT status FROM pipeline_meta.quellenlauf WHERE lauf_id = %s AND quelle = %s",
                    b["lauf_id"], langsam) == [("fehler",)]


def test_bestaetigte_leerlieferung_loescht_nur_mit_freigabe(tmp_path, als_import):
    """E50, Befund W7: Null Objekte halten die Quelle an (Standard, auch ohne Rückgang-Schutz). Mit
    --leerlieferung (laden.lauf(leer=…)) für genau diesen Lauf gilt die Leerlieferung als bestätigt: Status
    ok, alle bisherigen Zeilen gelöscht, die Freigabe mit Grund im Bericht. Nicht bei unvollständigem Abruf:
    Dann hält die Quelle trotz Freigabe an."""
    name, p = f"test_{uuid.uuid4().hex[:8]}", uuid.uuid4().hex[:6]
    daten = tmp_path / "daten.csv"
    cfg = _config(tmp_path, {name: _punkt_quelle(daten, max_rueckgang=None)})
    _punkte(daten, [(f"{p}{i}", f"P{i}", 52.4 + i / 1000, 12.5) for i in range(3)])
    _lauf(cfg)
    _punkte(daten, [])
    assert _quelle(_lauf(cfg), name)["status"] == "angehalten"
    _punkte(daten, [(f"{p}x", "X", "", "")])   # 0 Objekte und unvollständig
    q = _quelle(_lauf(cfg, leer={name: "Anbieter bestätigt Leerung (Test)"}), name)
    assert q["status"] == "angehalten" and q["unvollstaendig"]
    assert _abfrage('SELECT count(*) FROM "Baume" WHERE species LIKE %s', f"{p}%") == [(3,)]
    _punkte(daten, [])
    b = _lauf(cfg, leer={name: "Anbieter bestätigt Leerung (Test)"})
    q = _quelle(b, name)
    assert q["status"] == "ok" and _zahlen(b, name) == (0, 0, 3, 0)
    assert q["leerlieferung"] == "Anbieter bestätigt Leerung (Test)"
    assert any("Leerlieferung" in w and "Anbieter bestätigt" in w for w in q["warnungen"])
    assert _abfrage('SELECT count(*) FROM "Baume" WHERE species LIKE %s', f"{p}%") == [(0,)]


def test_karte_zeigt_unter_der_grenze_zuerst_aenderungen(tmp_path, als_import, monkeypatch):
    """E50, Codefehler aus E49 (ziel.karte_sql): Die Grenze karte_max_objekte schneidet zuerst ab, was die
    Karte als unverändert zeigt. Sortiert wurde aber nach der Spalte art: Zurückgehaltene Zeilen (angezeigt
    als unverändert) sortierten wie Änderungen und drängten die echte Änderung aus der Karte. Jetzt nach dem
    angezeigten Status."""
    name, p = f"test_{uuid.uuid4().hex[:8]}", uuid.uuid4().hex[:6]
    daten = tmp_path / "daten.csv"
    cfg = _config(tmp_path, {name: _punkt_quelle(daten, karte_max_objekte=1)})
    _punkte(daten, [(f"{p}{k}", k.upper(), 52.4, 12.5 + i / 1000) for i, k in enumerate("abcz")])
    _lauf(cfg)
    erfasst = {}
    monkeypatch.setattr(laden.karte, "schreiben", lambda datei, b, objekte, grund: erfasst.update(objekte))
    # a und b fehlen in einem unvollständigen Abruf (zurückgehalten), z ist geändert, c unverändert
    _punkte(daten, [(f"{p}c", "C", 52.4, 12.502), (f"{p}z", "Z neu", 52.4, 12.503), (f"{p}x", "X", "", "")])
    b = _lauf(cfg)
    assert _quelle(b, name)["zaehler"]["zurueckgehalten"] == 2
    assert [(o["properties"]["id"], o["properties"]["status"]) for o in erfasst[name]] == [
        (f"{p}z", "geaendert")]


# --- E51: Prüfbericht vom 07.11.2026, 03:13 (K1 Zeitgrenzen der Datenbank, K2 Fußzeilen) --------------------

@pytest.mark.parametrize("modus", ["ACCESS EXCLUSIVE", "SHARE"])
def test_gesperrte_zieltabelle_bricht_die_quelle_nach_der_grenze_ab(tmp_path, als_import, modus):
    """E51, Befund K1 (LB 4.3): Hält eine andere Sitzung eine Sperre auf der Zieltabelle, wartete die Quelle
    bis zum Abbruch des ganzen Laufs; das Zeitbudget prüfte nur zwischen den Anweisungen. Jetzt gelten je
    Quelle lock_timeout (hier db_sperre_max_s: 1) und statement_timeout (Rest des Zeitbudgets): Die Quelle
    bricht nach der Grenze ab, ihre Transaktion wird zurückgerollt (alter Stand bleibt), der Bericht nennt
    „Zeitbudget/Datenbank-Zeitgrenze“ ohne Meldungsentwurf an den Anbieter, und die nächste Quelle (andere
    Zieltabelle) wird geladen. Die sperrende Sitzung endet nach 20 s von selbst
    (idle_in_transaction_session_timeout); am Stand vor E51 wartete die Quelle so lange und lud dann.
    Belegt ist nur das: An welchen Stellen die Grenzen gesetzt werden, legt dieser Test nicht fest (das
    lock_timeout aus dem ersten Setzen gilt bis zum Ende der Transaktion); das prüft
    test_zeitgrenzen_vor_jedem_schreibschritt_mit_dem_aktuellen_rest in test_laden.py (Nachprüfung zu E51)."""
    import contextlib
    blockiert, frei, p = f"test_{uuid.uuid4().hex[:8]}", f"test_{uuid.uuid4().hex[:8]}", uuid.uuid4().hex[:6]
    d1, d2 = tmp_path / "a.csv", tmp_path / "b.csv"
    _punkte(d1, [(f"{p}a{i}", f"A{i}", 52.4 + i / 1000, 12.5) for i in range(3)])
    _flaechen(d2, [(f"{p}b{i}", f"B{i}", 52.4 + i / 1000, 12.6) for i in range(2)])
    cfg = _config(tmp_path, {blockiert: _punkt_quelle(d1, db_sperre_max_s=1), frei: _flaechen_quelle(d2)})
    _lauf(cfg)
    _punkte(d1, [(f"{p}a{i}", f"A{i} neu", 52.4 + i / 1000, 12.5) for i in range(4)])
    _flaechen(d2, [(f"{p}b{i}", f"B{i}", 52.4 + i / 1000, 12.6) for i in range(3)])
    sperre = _admin()
    try:
        sperre.execute("SET idle_in_transaction_session_timeout = '20s'")
        sperre.execute("BEGIN")
        sperre.execute(f'LOCK TABLE "Baume" IN {modus} MODE')
        t0 = time.monotonic()
        b = _lauf(cfg, alle=True)
        dauer = time.monotonic() - t0
    finally:
        with contextlib.suppress(Exception):
            sperre.execute("ROLLBACK")
        with contextlib.suppress(Exception):
            sperre.close()
    q = _quelle(b, blockiert)
    assert q["status"] == "fehler", q
    assert q["fehler"].startswith("ZeitbudgetUeberschritten: Zeitbudget/Datenbank-Zeitgrenze"), q["fehler"]
    assert "lock_timeout" in q["fehler"] and "meldung" not in q
    assert _quelle(b, frei)["status"] == "ok" and dauer < 15, dauer
    assert _abfrage('SELECT species, leaf_type FROM "Baume" WHERE species LIKE %s ORDER BY 1', f"{p}a%") == [
        (f"{p}a{i}", f"A{i}") for i in range(3)]
    assert _abfrage('SELECT count(*) FROM "Gebäude (ALKIS)" WHERE oid LIKE %s', f"{p}b%") == [(3,)]


def test_langsame_anweisung_bricht_am_statement_timeout_ab(tmp_path, als_import, monkeypatch):
    """Nachprüfung zu E51 (Befund K1, Grenze „statement_timeout nur über die Unit-Tests belegt“): Eine
    Anweisung, die über das Zeitbudget hinaus rechnet, bricht PostgreSQL selbst ab. Hier schläft vor dem
    Schreiben (ziel.anwenden) eine Anweisung 30 s (pg_sleep) bei einem Budget von 6 s (zeitbudget_min 0,1).
    statement_timeout ist der Rest am Prüfpunkt davor: Die Quelle endet nach wenigen Sekunden als
    „Zeitbudget/Datenbank-Zeitgrenze (statement_timeout …)“ ohne Meldungsentwurf, ihr alter Stand bleibt. Am
    Stand nach E50 lief die Anweisung die vollen 30 s und erst der nächste Prüfpunkt brach ab. Erkannt wird
    der Abbruch seit der Nachprüfung am Rest des Budgets, nicht am Text der Servermeldung."""
    name, p = f"test_{uuid.uuid4().hex[:8]}", uuid.uuid4().hex[:6]
    daten = tmp_path / "a.csv"
    _punkte(daten, [(f"{p}a{i}", f"A{i}", 52.4 + i / 1000, 12.5) for i in range(3)])
    assert _quelle(_lauf(_config(tmp_path, {name: _punkt_quelle(daten)})), name)["status"] == "ok"
    _punkte(daten, [(f"{p}a{i}", f"A{i} neu", 52.4 + i / 1000, 12.5) for i in range(3)])
    cfg = _config(tmp_path, {name: _punkt_quelle(daten, zeitbudget_min=0.1)})
    original = laden.ziel.anwenden

    def langsam(cur, *a, **kw):
        """ziel.anwenden mit einer Anweisung davor, die länger rechnet als das ganze Budget."""
        cur.execute("SELECT pg_sleep(30)")
        return original(cur, *a, **kw)

    monkeypatch.setattr(laden.ziel, "anwenden", langsam)
    t0 = time.monotonic()
    q = _quelle(_lauf(cfg, alle=True), name)
    dauer = time.monotonic() - t0
    assert q["status"] == "fehler", q
    assert q["fehler"].startswith("ZeitbudgetUeberschritten: Zeitbudget/Datenbank-Zeitgrenze"), q["fehler"]
    assert "statement_timeout" in q["fehler"] and "meldung" not in q
    assert dauer < 15, dauer
    assert _abfrage('SELECT species, leaf_type FROM "Baume" WHERE species LIKE %s ORDER BY 1', f"{p}a%") == [
        (f"{p}a{i}", f"A{i}") for i in range(3)]


def test_beschaedigte_letzte_csv_zeile_loescht_nichts(tmp_path, als_import):
    """E51, Befund K2 (Antwort 52), Statistiktabelle im CSV-Aufbau (_statistik_csv): Die letzte Datenzeile
    verliert ihren Schlüssel. Bis E50 galt sie als Fußzeile, der Abruf als vollständig, und die drei Werte der
    Gemeinde wurden gelöscht (3 statt bisher 4 Gemeinden, unter der Grenze des Rückgang-Schutzes). Jetzt ist
    die Zeile keine erlaubte Fußzeile: Abruf unvollständig, nichts gelöscht, die Werte bleiben."""
    k = uuid.uuid4().hex[:6]
    name = f"test_{k}_fuss"
    kz = sorted(f"12{uuid.uuid4().int % 10**6:06d}" for _ in range(4))
    cfg_q = _statistik_csv()
    datei = tmp_path / f"{name}.csv"
    cfg_q.update(pfad=str(datei), rhythmus=None)
    cfg_q["ziel"] = {**cfg_q["ziel"], "fest": {**cfg_q["ziel"]["fest"], "source": name}}
    del cfg_q["ziel"]["metadaten"]

    def schreiben(zeilen):
        """Statistiktabelle (latin-1) mit Kopf zum Stichtag 31.12.2025, je Schlüssel eine Zeile (Werte 100,
        50, 50; die erste Datenzeile ist Zeile 9) und Fußzeilen wie in der Regionaldatenbank."""
        kopf = ("Tabelle: 12411-01-01-5-B\nBevölkerung;;;;\nEbenen;;;;\nFortschreibung;;;;\nBestand;;;;\n"
                ";;Stichtag;Stichtag;Stichtag\n;;31.12.2025;31.12.2025;31.12.2025\n"
                ";;Insgesamt;männlich;weiblich\n")
        datei.write_text(kopf + "".join(f"{a};Ort;100;50;50\n" for a in zeilen)
                         + "Fußnote;;;;\n© Testamt\n", encoding="latin-1")

    cfg = _config(tmp_path, {name: cfg_q})
    schreiben(kz)
    q = _quelle(_lauf(cfg), name)
    assert q["status"] == "ok" and q["zaehler"]["neu"] == 12 and not q["unvollstaendig"], q["warnungen"]
    schreiben(kz[:3] + [""])                     # letzte Datenzeile ohne Schlüssel: ";Ort;100;50;50"
    q = _quelle(_lauf(cfg, alle=True), name)
    assert q["status"] == "ok" and q["unvollstaendig"], q["warnungen"]
    assert (q["zaehler"]["geloescht"], q["zaehler"]["zurueckgehalten"]) == (0, 3), q["zaehler"]
    assert any("nach dem Datenbereich" in w and "(Zeilen 12)" in w for w in q["warnungen"]), q["warnungen"]
    assert _abfrage("SELECT count(*) FROM dashboard_data_de WHERE source = %s AND kennziffer = %s",
                    name, kz[3]) == [(3,)]
