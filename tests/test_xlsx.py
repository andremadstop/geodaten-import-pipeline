"""Quellenart xlsx (E48): Statistische Berichte als Excel-Datei, ohne Netz und ohne Datenbank. Alle Berichte
entstehen im Test (tests/conftest.py, erfundene Zahlen); kein Test ruft einen Rechner ab.

Der Adapter gehört zur Stufe quellen (laden → quellen → ziel) und liefert Kennzahlen je Gemeinde für
dashboard_data_de. Abgesichert werden:
- Lesen nach Beschriftung statt Position, Auswahl der Gemeinden, Stichtag aus Titel bzw. Fußnote;
- Anhalten der Quelle bei fehlendem Blatt oder fehlender bzw. doppelter Beschriftung (E4);
- unvollständiger Abruf, also kein Löschen (E23, E32), bei beschädigten oder doppelten Schlüsseln,
  beschädigten Werten und Summen, die nicht zur Landes- oder Kreissumme passen;
- Bezug über die Berichtsseite: nur die Seite wird abgerufen, gewählt wird nur ein Link auf erlaubten
  Rechnern, mit https, Port 443 und nicht auf einem per robots.txt gesperrten Pfad;
- Härtung der Datei vor openpyxl (DTD und Entitäten, nur UTF-8, ZIP-Bombe, Größe, alle Teile gleich
  welcher Endung) und openpyxl selbst nur mit defusedxml;
- die Sperrliste aus robots.txt gilt für jede Art von Abruf (GET, Dateiabruf, HEAD-Suche).
"""
import copy
import zipfile
from pathlib import Path

import pytest
import yaml
from conftest import KREISFREIE, gemeinden_je_kreis

from pipeline import laden, quellen
from pipeline.quellen import Protokoll, QuellenFehler

KONFIG = Path(__file__).resolve().parent.parent / "config" / "quellen.yaml"


@pytest.fixture(autouse=True)
def kein_netz(monkeypatch):
    """Sperrt für jeden Test dieser Datei requests.get und requests.head: Ein Netzabruf endet mit
    AssertionError, statt einen Rechner zu erreichen."""
    def gesperrt(*a, **k):
        raise AssertionError(f"Netzabruf im Test: {a}")
    monkeypatch.setattr(quellen.requests, "get", gesperrt)
    monkeypatch.setattr(quellen.requests, "head", gesperrt)


def _cfg(name: str, pfad: Path) -> dict:
    """Die Quelle aus config/quellen.yaml, wie ausgeliefert, nur mit abgelegter Datei statt Seite."""
    q = copy.deepcopy(yaml.safe_load(KONFIG.read_text(encoding="utf-8"))["quellen"][name])
    for k in ("seite", "datei_muster", "link_rechner"):
        q.pop(k)
    q["pfad"] = str(pfad)
    return q


def _lesen(cfg: dict) -> tuple[list[dict], Protokoll]:
    """Liest die Quelle mit dem Adapter xlsx und gibt Datensätze und Protokoll zurück."""
    prot = Protokoll()
    return list(quellen.ADAPTER["xlsx"](cfg, prot)), prot


def test_konfiguration_bevoelkerung_gemeinden_waehlt_gemeinden_und_kreisfreie(bericht):
    """Konfigurationspfad von bevoelkerung_gemeinden: 28 kreisangehörige Gemeinden aus 3.1 bis 3.14 und die
    4 kreisfreien Städte aus Blatt 2.; Kreissummen (1206x000 …) und Landessumme 12000000 fallen heraus."""
    ds, prot = _lesen(_cfg("bevoelkerung_gemeinden", bericht()))
    schluessel = [d["objekt_id"] for d in ds]
    assert len(ds) == 32 and len(set(schluessel)) == 32, schluessel
    assert {"12051000", "12052000", "12053000", "12054000"} <= set(schluessel)
    assert not any(s.endswith("000") and not s.startswith("1205") for s in schluessel)
    potsdam = next(d for d in ds if d["objekt_id"] == "12054000")
    assert potsdam["geom"] == ("gebiet", "12054000")
    assert potsdam["werte"] == {"bevoelkerung": 180000} and potsdam["zeit"] == {"bevoelkerung": "2025-12-31"}
    assert not prot.unvollstaendig and not prot.warnungen, prot.warnungen
    assert prot.info["zeitbezug"] == {"bevoelkerung": "2025-12-31"}


def test_konfiguration_flaeche_mit_stand_aus_der_fussnote(bericht):
    """Die Fläche gilt laut Fußnote zum Stand des Vorjahres, nicht zum Jahresende des Berichts."""
    ds, prot = _lesen(_cfg("flaeche_gemeinden", bericht(flaeche_stand="31.12.2024")))
    assert len(ds) == 32 and not prot.warnungen, prot.warnungen
    brb = next(d for d in ds if d["objekt_id"] == "12051000")
    assert brb["werte"] == {"flaeche_km2": 229.73} and brb["zeit"] == {"flaeche_km2": "2024-12-31"}


def test_spalten_per_beschriftung_nicht_per_position(bericht):
    """Stellt der Anbieter Spalten um, folgt die Pipeline der Beschriftung; Zeilenumbrüche, Leerzeichen und
    Fußnotenzeichen (Fläche⁴) zählen nicht."""
    umgestellt = bericht(spalten=[7, 5, 4, 1, 3, 2, 6, 0])
    ds, prot = _lesen(_cfg("flaeche_gemeinden", umgestellt))
    assert len(ds) == 32 and not prot.warnungen, prot.warnungen
    assert next(d for d in ds if d["objekt_id"] == "12051000")["werte"] == {"flaeche_km2": 229.73}


def test_kopf_ohne_beschriftung_haelt_die_quelle_an(bericht):
    """Fehlt in einem Blatt die konfigurierte Wertbeschriftung (hier „Fläche in ha“ statt „in km²“), liefert
    der Adapter nichts und meldet Blatt und erwartete Beschriftung; laden hält die Quelle an (E4)."""
    def umbenennen(wb):
        wb["3.4"]["G4"] = "Fläche\nin ha"
    ds, prot = _lesen(_cfg("flaeche_gemeinden", bericht(nachher=umbenennen)))
    assert ds == [] and prot.info["fehlende_felder"], prot.info
    assert any("3.4" in w and "Fläche in km²" in w for w in prot.warnungen), prot.warnungen


def test_fehlendes_blatt_haelt_die_quelle_an(bericht):
    """Fehlte ein Landkreis, fielen rund 7 % der Gemeinden weg, unter dem Rückgang-Schutz von 50 %: Ihre
    Werte würden gelöscht. Ein genanntes Blatt muss es geben."""
    ds, prot = _lesen(_cfg("bevoelkerung_gemeinden", bericht(ohne_blatt="3.7")))
    assert ds == [] and prot.info["fehlende_felder"]
    assert any("3.7" in w for w in prot.warnungen), prot.warnungen


def test_blatt_muster_ohne_treffer_haelt_an(bericht):
    """Statt fester Blattnamen geht auch blatt_muster: Trifft es kein Blatt, wird die Quelle angehalten,
    trifft es die richtigen, liest sie wie mit `blaetter`."""
    cfg = _cfg("bevoelkerung_gemeinden", bericht())
    del cfg["blaetter"]
    cfg["blatt_muster"] = r"^4\.\d+$"
    ds, prot = _lesen(cfg)
    assert ds == [] and prot.info["fehlende_felder"]
    cfg["blatt_muster"] = r"^(2\.|3\.\d+)$"
    ds, prot = _lesen(cfg)
    assert len(ds) == 32 and not prot.warnungen


def test_doppelte_wertbeschriftung_haelt_an(bericht):
    """Steht die Wertbeschriftung in einem Blatt zweimal, ist die Spalte nicht eindeutig, und die Quelle wird
    angehalten."""
    def doppelt(wb):
        wb["3.2"]["H4"] = "Bevölkerung\nam\nJahresende"
    ds, prot = _lesen(_cfg("bevoelkerung_gemeinden", bericht(nachher=doppelt)))
    assert ds == [] and any("mehrfach" in w for w in prot.warnungen), prot.warnungen


@pytest.mark.parametrize("schaden", ["12O60001", " 12060001", "12060001 ", "1206001", "", None, True],
                         ids=["buchstabe", "leer_vorn", "leer_hinten", "sieben_stellen", "leer", "ohne",
                              "wahrheitswert"])
def test_beschaedigter_schluessel_sperrt_das_loeschen(bericht, schaden):
    """E47 sinngemäß: Eine Datenzeile (mit Wert) ohne gültigen Schlüssel wird nicht übernommen, und der Abruf
    gilt als unvollständig, damit der bisherige Wert der Gemeinde nicht gelöscht wird. Als Zahl gespeicherte
    Schlüssel sind gültig, als Text nur ohne Rand."""
    kreise = gemeinden_je_kreis()
    kreise["3.1"][0] = (schaden, 1001, 10.51, schaden)
    ds, prot = _lesen(_cfg("bevoelkerung_gemeinden", bericht(kreise=kreise)))
    assert prot.unvollstaendig, prot.warnungen
    assert "12060001" not in {d["objekt_id"] for d in ds}
    assert any("Blatt 3.1, Zeile 7" in w for w in prot.warnungen), prot.warnungen


def test_schluessel_als_zahl_oder_text_gleich(bericht):
    """Ein Schlüssel als Zahl (auch 12060001.0) und als Text ohne Rand ergibt dieselbe Objekt-ID, ohne
    Warnung."""
    kreise = gemeinden_je_kreis()
    kreise["3.1"][0] = (12060001, 1001, 10.51, 12060001.0)
    kreise["3.1"][1] = ("12060002", 1002, 10.52, "12060002")
    ds, prot = _lesen(_cfg("bevoelkerung_gemeinden", bericht(kreise=kreise)))
    assert len(ds) == 32 and not prot.warnungen, prot.warnungen
    assert {"12060001", "12060002"} <= {d["objekt_id"] for d in ds}


def test_schluessel_der_beiden_spalten_verschieden_sperrt_das_loeschen(bericht):
    """Stimmen die beiden Schlüsselspalten einer Zeile nicht überein, wird die Zeile nicht übernommen, und der
    Abruf ist unvollständig, mit Fundstelle in der Warnung."""
    kreise = gemeinden_je_kreis()
    kreise["3.1"][0] = ("12060001", 1001, 10.51, "12060011")
    ds, prot = _lesen(_cfg("bevoelkerung_gemeinden", bericht(kreise=kreise)))
    assert prot.unvollstaendig and "12060001" not in {d["objekt_id"] for d in ds}
    assert any("verschieden" in w and "Zeile 7" in w for w in prot.warnungen), prot.warnungen


@pytest.mark.parametrize("schaden", ["abc", "1.234", True, "12 345"],
                         ids=["text", "punkt", "bool", "leerzeichen"])
def test_beschaedigter_wert_sperrt_das_loeschen(bericht, schaden):
    """Ein Wert, der weder Zahl noch statistisches Zeichen ist, wird nicht als Zahl geraten (1.234 wäre im
    deutschen Format 1234, als Dezimalzahl 1,234): Wert leer (pflicht hält die Zeile zurück), Abruf
    unvollständig, nichts wird gelöscht."""
    kreise = gemeinden_je_kreis()
    kreise["3.3"][1] = ("12062002", schaden, 31.52)
    ds, prot = _lesen(_cfg("bevoelkerung_gemeinden", bericht(kreise=kreise)))
    assert prot.unvollstaendig, prot.warnungen
    zeile = next(d for d in ds if d["objekt_id"] == "12062002")
    assert zeile["werte"] == {"bevoelkerung": None}
    assert any("Blatt 3.3, Zeile 8" in w and "keine Zahl" in w for w in prot.warnungen), prot.warnungen


@pytest.mark.parametrize("zeichen", ["–", "-", ".", "x", "…", "/", "•"])
def test_statistische_zeichen_sind_kein_wert(bericht, zeichen):
    """„–“ heißt beim AfS „nichts vorhanden oder genau null“; für Bevölkerung und Fläche einer Gemeinde ist
    das kein Messwert. Leer, ohne Unvollständigkeit; die Zeile hat keinen Wert und behält ihren bisherigen
    Stand (leer, pflicht)."""
    kreise = gemeinden_je_kreis()
    kreise["3.5"][0] = ("12064001", zeichen, 52.51)
    ds, prot = _lesen(_cfg("bevoelkerung_gemeinden", bericht(kreise=kreise)))
    zeile = next(d for d in ds if d["objekt_id"] == "12064001")
    assert zeile["werte"] == {"bevoelkerung": None} and zeile["leer"] is True
    assert not any("keine Zahl" in w for w in prot.warnungen)


def test_fussnoten_und_leerzeilen_bleiben_stumm(bericht):
    """Fußnoten (auch mit einer Zahl wie einem Schlüssel im Text) und Zeilen ohne Schlüssel und ohne Wert
    unter den Daten erzeugen keine Warnung."""
    def fuss(wb):
        wb["3.6"]["B40"] = "5 Fußnote mit 12060001 im Text"
        wb["3.6"]["C41"] = "Name ohne Schlüssel und ohne Wert"
    ds, prot = _lesen(_cfg("bevoelkerung_gemeinden", bericht(nachher=fuss)))
    assert len(ds) == 32 and not prot.warnungen, prot.warnungen


def test_summe_gegen_die_landeszeile(bericht):
    """Gegenprobe: Fehlt eine Gemeinde in ihrem Blatt (oder kommt eine doppelt), stimmt die Summe nicht mehr
    mit der Landeszeile 12000000; der Abruf ist unvollständig, nichts wird gelöscht."""
    kreise = gemeinden_je_kreis()
    pfad = bericht(kreise=kreise)
    ds, prot = _lesen(_cfg("bevoelkerung_gemeinden", pfad))
    assert not prot.unvollstaendig
    ganz = sum(d["werte"]["bevoelkerung"] for d in ds)
    ds, prot = _lesen(_cfg("bevoelkerung_gemeinden", bericht(kreise=kreise, land=(ganz + 1, 0))))
    assert prot.unvollstaendig
    assert any("Summe" in w and str(ganz) in w and str(ganz + 1) in w for w in prot.warnungen), prot.warnungen
    # Fläche: innerhalb der Toleranz (Rundung der Gemeindeflächen) stumm, darüber unvollständig
    cfg = _cfg("flaeche_gemeinden", pfad)
    ds, prot = _lesen(cfg)
    fl = round(sum(d["werte"]["flaeche_km2"] for d in ds), 2)
    for land, unvollstaendig in ((fl - 0.05, False), (fl + 3, True)):
        _, prot = _lesen(_cfg("flaeche_gemeinden", bericht(kreise=kreise, land=(1, land))))
        assert prot.unvollstaendig is unvollstaendig, (land, prot.warnungen)


def test_summe_ohne_landeszeile_ist_unvollstaendig(bericht):
    """Fehlt die Landeszeile 12000000, ist die Gegenprobe nicht möglich: Die Datensätze kommen, der Abruf gilt
    aber als unvollständig."""
    def ohne_land(wb):
        ws = wb["2."]
        for zeile in ws.iter_rows():
            if zeile[1].value == "12000000":
                for zelle in zeile:
                    zelle.value = None
    ds, prot = _lesen(_cfg("bevoelkerung_gemeinden", bericht(nachher=ohne_land)))
    assert len(ds) == 32 and prot.unvollstaendig
    assert any("12000000" in w for w in prot.warnungen), prot.warnungen


def test_zeitbezug_fehlt_oder_mehrdeutig_bricht_ab(bericht):
    """Nennen die Blätter verschiedene Jahre, ist der Zeitbezug mehrdeutig; fehlt die Fußnote mit dem Stand
    der Fläche, ist er nicht zu finden; beides bricht die Quelle ab."""
    def zweites_jahr(wb):
        wb["3.9"]["B1"] = "3   Bevölkerungsentwicklung im Jahr 2024"
    with pytest.raises(QuellenFehler, match="mehrdeutig.*2024-12-31.*2025-12-31"):
        _lesen(_cfg("bevoelkerung_gemeinden", bericht(nachher=zweites_jahr)))

    def ohne_fussnote(wb):
        for ws in wb.worksheets:
            for zeile in ws.iter_rows():
                for zelle in zeile:
                    if isinstance(zelle.value, str) and "Stand" in zelle.value:
                        zelle.value = None
    with pytest.raises(QuellenFehler, match="Zeitbezug.*nicht gefunden"):
        _lesen(_cfg("flaeche_gemeinden", bericht(nachher=ohne_fussnote)))


def test_zeitbezug_folgt_dem_neuen_bericht(bericht):
    """Nächstes Jahr: kein fester Stichtag in der Konfiguration, er kommt aus der Datei."""
    pfad = bericht(jahr=2026, flaeche_stand="31.12.2025")
    assert _lesen(_cfg("bevoelkerung_gemeinden", pfad))[1].info["zeitbezug"] == {"bevoelkerung": "2026-12-31"}
    assert _lesen(_cfg("flaeche_gemeinden", pfad))[1].info["zeitbezug"] == {"flaeche_km2": "2025-12-31"}


# --- Abruf: Seite, Link, Datei --------------------------------------------------------------------

SEITE = "https://www.statistik.example/bericht-a-i-4"


def _seite(links: list[str]) -> bytes:
    """HTML einer Berichtsseite mit je einem Link für jeden Eintrag in `links`."""
    return ("<html><head><title>Bericht</title></head><body>"
            + "".join(f'<p><a href="{h}">Download</a></p>' for h in links) + "</body></html>").encode()


def _link_cfg() -> dict:
    """Konfiguration für link_ermitteln: Berichtsseite, Muster des Dateinamens mit Jahr, erlaubter
    Download-Rechner."""
    return {"seite": SEITE, "datei_muster": r"^SB_A01-04[_-]00_(?P<jahr>\d{4})j01_BB\.xlsx$",
            "link_rechner": ["download.statistik.example"]}


def _link(monkeypatch, links: list[str], cfg: dict | None = None) -> str:
    """Ruft link_ermitteln mit einer Seite aus `links` auf, prüft, dass nur die Seite selbst abgerufen wird
    und keiner ihrer Links, und gibt den gewählten Link zurück."""
    abgerufen = []

    def abrufen(url, params, cfg, prot):
        abgerufen.append(url)
        return _seite(links)
    monkeypatch.setattr(quellen, "abrufen", abrufen)
    url = quellen.link_ermitteln(cfg or _link_cfg(), Protokoll())
    assert abgerufen == [SEITE]   # nur die Seite, keinen Link
    return url


def test_link_der_juengsten_ausgabe(monkeypatch):
    """Von mehreren passenden Links gewinnt die jüngste Ausgabe; PDF, Kontaktseite und mailto passen nicht zum
    Muster."""
    links = ["https://download.statistik.example/8d8e/6a9d/SB_A01-04-00_2024j01_BB.xlsx",
             "https://download.statistik.example/c2fa/a46a/SB_A01-04_00_2025j01_BB.xlsx",
             "https://download.statistik.example/722c/b897/SB_A01-04_00_2025j01_BB.pdf",
             "/kontakt", "mailto:info@statistik.example"]
    assert _link(monkeypatch, links) == links[1]


def test_link_auf_derselben_seite_relativ(monkeypatch):
    """Ein relativer Link wird gegen die Adresse der Seite aufgelöst und gilt als Link auf deren Rechner."""
    assert _link(monkeypatch, ["/dateien/SB_A01-04_00_2025j01_BB.xlsx"]) == \
        "https://www.statistik.example/dateien/SB_A01-04_00_2025j01_BB.xlsx"


def test_fremde_links_werden_nie_gewaehlt(monkeypatch):
    """Ein passender Dateiname auf einem fremden Rechner, über http oder einem anderen Port zählt nicht,
    auch wenn er jünger ist."""
    gut = "https://download.statistik.example/a/b/SB_A01-04_00_2025j01_BB.xlsx"
    fremd = ["https://boese.example/SB_A01-04_00_2026j01_BB.xlsx",
             "https://download.statistik.example.boese.example/SB_A01-04_00_2026j01_BB.xlsx",
             "http://download.statistik.example/SB_A01-04_00_2026j01_BB.xlsx",
             "https://download.statistik.example:8443/SB_A01-04_00_2026j01_BB.xlsx",
             "https://nutzer@boese.example/SB_A01-04_00_2026j01_BB.xlsx"]
    assert _link(monkeypatch, [*fremd, gut]) == gut
    with pytest.raises(QuellenFehler, match="Kein Link.*5 passende Links auf anderen Rechnern"):
        _link(monkeypatch, fremd)


def test_mehrdeutiger_oder_fehlender_link_bricht_ab(monkeypatch):
    """Zwei Links für dieselbe Ausgabe oder gar kein passender Link brechen die Quelle ab, statt einen zu
    raten."""
    with pytest.raises(QuellenFehler, match="mehrere Links"):
        _link(monkeypatch, ["https://download.statistik.example/a/SB_A01-04_00_2025j01_BB.xlsx",
                            "https://download.statistik.example/b/SB_A01-04_00_2025j01_BB.xlsx"])
    with pytest.raises(QuellenFehler, match="Kein Link"):
        _link(monkeypatch, ["/kontakt"])


def test_genau_eine_bezugsart(tmp_path):
    """Eine Quelle braucht genau eines von `pfad` und `seite`; beides zugleich oder keines bricht ab."""
    for cfg in ({"pfad": "a.xlsx", "seite": SEITE}, {}):
        with pytest.raises(QuellenFehler, match="genau eines"):
            quellen.xlsx_datei(cfg, Protokoll())


def test_abruf_ueber_die_seite_in_den_zwischenspeicher(monkeypatch, tmp_path, bericht):
    """Seite → Link → Datei nach cache/; beide Abrufe mit den Regeln von abrufen() bzw. datei_abrufen()."""
    inhalt = bericht().read_bytes()
    link = "https://download.statistik.example/c2fa/a46a/SB_A01-04_00_2025j01_BB.xlsx"
    abrufe = []

    class Antwort:
        """Ersatz für requests.Response mit festem Inhalt und Content-Length, ohne Weiterleitung."""
        def __init__(self, daten):
            self.daten, self.status_code, self.is_redirect = daten, 200, False
            self.headers = {"Content-Length": str(len(daten))}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def raise_for_status(self):
            pass

        def iter_content(self, n):
            yield self.daten

    def get(url, **kw):
        abrufe.append(url)
        assert kw["allow_redirects"] is False
        return Antwort(_seite([link]) if url == SEITE else inhalt)
    monkeypatch.setattr(quellen.requests, "get", get)
    cfg = {**_cfg("bevoelkerung_gemeinden", Path("x")), **_link_cfg(), "cache": str(tmp_path / "cache")}
    del cfg["pfad"]
    ds, prot = _lesen(cfg)
    assert abrufe == [SEITE, link] and len(ds) == 32, prot.warnungen
    assert (tmp_path / "cache" / "SB_A01-04_00_2025j01_BB.xlsx").exists()
    assert prot.info["datei"]["url"] == link


def test_ziele_nennen_seite_und_link_rechner():
    """--ziele nennt für die mitgelieferte Konfiguration den Rechner der Berichtsseite und den
    Download-Rechner, aber nicht die Regionaldatenbank (E48)."""
    cfg = yaml.safe_load(KONFIG.read_text(encoding="utf-8"))
    z = laden.ziele(cfg)
    assert "www.statistik-berlin-brandenburg.de:443" in z
    assert "download.statistik-berlin-brandenburg.de:443" in z
    assert not any("regionalstatistik" in r for r in z)


def test_keine_regionaldatenbank_in_der_konfiguration():
    """E48: www.regionalstatistik.de sperrt per robots.txt alles (Disallow: /); keine Konfiguration ruft sie
    ab."""
    for datei in KONFIG.parent.glob("*.yaml"):
        assert "regionalstatistik" not in datei.read_text(encoding="utf-8").lower(), datei
    q = yaml.safe_load(KONFIG.read_text(encoding="utf-8"))["quellen"]
    for name in ("bevoelkerung_gemeinden", "flaeche_gemeinden"):
        assert q[name]["typ"] == "xlsx"
        assert q[name]["lizenz"] == "Amt für Statistik Berlin-Brandenburg, CC BY 3.0 DE"
        assert q[name]["ziel"]["fest"]["source"] == "Amt für Statistik Berlin-Brandenburg"


# --- Härtung der Datei -----------------------------------------------------------------------------

def _umpacken(quelle: Path, ziel: Path, ersetzen: dict[str, bytes] | None = None,
              dazu: dict[str, bytes] | None = None, verfahren=zipfile.ZIP_DEFLATED) -> Path:
    """Kopiert eine XLSX Teil für Teil in ein neues ZIP: `ersetzen` tauscht Teile aus (neue Bytes oder
    Funktion des alten Inhalts), `dazu` fügt Teile hinzu."""
    with zipfile.ZipFile(quelle) as alt, zipfile.ZipFile(ziel, "w", verfahren) as neu:
        for info in alt.infolist():
            daten = alt.read(info)
            if ersetzen and info.filename in ersetzen:
                daten = ersetzen[info.filename](daten) if callable(ersetzen[info.filename]) \
                    else ersetzen[info.filename]
            neu.writestr(info.filename, daten)
        for name, daten in (dazu or {}).items():
            neu.writestr(name, daten)
    return ziel


@pytest.mark.parametrize("teil", ["xl/sharedStrings.xml", "xl/worksheets/sheet3.xml"])
def test_dtd_und_entitaeten_werden_abgelehnt(bericht, tmp_path, teil):
    """Externe Entitäten (Datei lesen, Netz) und Entitäts-Bomben: Jede DTD in einem XML-Teil lehnt die
    Pipeline ab, bevor openpyxl liest; zusätzlich liest openpyxl über defusedxml. openpyxl schreibt Texte ohne
    sharedStrings.xml; der Teil wird hier ergänzt, wie ihn Excel schreibt."""
    sst = (b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<sst xmlns="http://schemas.openxmlformats'
           b'.org/spreadsheetml/2006/main" count="1" uniqueCount="1"><si><t>&e;</t></si></sst>')
    def mit_dtd(daten: bytes) -> bytes:
        dtd = b'<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]>'
        if daten.startswith(b"<?xml"):
            kopf, rest = daten.split(b"?>", 1)
            return kopf + b"?>" + dtd + rest
        return dtd + daten
    quelle = _umpacken(bericht(), tmp_path / "mit-sst.xlsx", dazu={"xl/sharedStrings.xml": sst}) \
        if teil == "xl/sharedStrings.xml" else bericht()
    boese = _umpacken(quelle, tmp_path / "dtd.xlsx", {teil: mit_dtd})
    with pytest.raises(QuellenFehler, match="DTD oder Entität"):
        _lesen(_cfg("bevoelkerung_gemeinden", boese))


def test_auch_openpyxl_liest_keine_entitaeten(bericht, tmp_path, monkeypatch):
    """Zweite Schicht: Ohne die Vorprüfung lehnt openpyxl über defusedxml die Entität selbst ab."""
    from defusedxml import DefusedXmlException

    def mit_dtd(daten: bytes) -> bytes:
        kopf, rest = daten.split(b"?>", 1) if daten.startswith(b"<?xml") else (b"", daten)
        dtd = b'<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]>'
        return (kopf + b"?>" if kopf else b"") + dtd + rest
    boese = _umpacken(bericht(), tmp_path / "dtd.xlsx", {"xl/worksheets/sheet3.xml": mit_dtd})
    monkeypatch.setattr(quellen, "xlsx_pruefen", lambda *a: None)
    with pytest.raises((QuellenFehler, DefusedXmlException)) as fehler:
        _lesen(_cfg("bevoelkerung_gemeinden", boese))
    kette, e = [], fehler.value
    while e is not None:
        kette.append(e)
        e = e.__cause__ or e.__context__
    assert any(isinstance(e, DefusedXmlException) for e in kette), kette


def test_nur_utf8(bericht, tmp_path):
    """Ein Blatt in UTF-16 wird vor dem Lesen abgelehnt."""
    def utf16(daten: bytes) -> bytes:
        return daten.decode("utf-8").replace('encoding="UTF-8"', 'encoding="UTF-16"').encode("utf-16")

    boese = _umpacken(bericht(), tmp_path / "u16.xlsx", {"xl/worksheets/sheet2.xml": utf16})
    with pytest.raises(QuellenFehler, match="UTF-8"):
        _lesen(_cfg("bevoelkerung_gemeinden", boese))


def test_zip_bombe_und_groesse(bericht, tmp_path):
    """Ein Teil über 1 MB mit hoher Packrate (ZIP-Bombe) und eine entpackte Gesamtgröße über max_entpackt_mb
    brechen ab; das gilt für jeden Teil, auch ein Bild, während ein schwer packbares Bild nur zur Größe
    zählt."""
    bombe = b"<a>" + b" " * (3 << 20) + b"</a>"
    gross = _umpacken(bericht(), tmp_path / "gross.xlsx", dazu={"xl/bombe.xml": bombe})
    cfg = _cfg("bevoelkerung_gemeinden", gross)
    with pytest.raises(QuellenFehler, match="Packrate"):
        _lesen(cfg)
    cfg.update(max_packrate=100000, max_entpackt_mb=2)
    with pytest.raises(QuellenFehler, match="entpackt.*max_entpackt_mb"):
        _lesen(cfg)
    # Jeder Teil zählt, auch ein Bild: openpyxl liest Blätter über rels, gleich welche Endung (Prüfung nach
    # E48). Ein Bild aus Nullen ist eine ZIP-Bombe wie jede andere; ein Bild mit echter Packrate zählt zur
    # Größe
    bild = _umpacken(bericht(), tmp_path / "bild.xlsx", dazu={"xl/media/image1.emf": b"\0" * (3 << 20)})
    with pytest.raises(QuellenFehler, match="image1.emf: Packrate"):
        _lesen(_cfg("bevoelkerung_gemeinden", bild))
    import os
    zufall = os.urandom(3 << 20)
    bild = _umpacken(bericht(), tmp_path / "bild2.xlsx", dazu={"xl/media/image1.emf": zufall})
    assert len(_lesen(_cfg("bevoelkerung_gemeinden", bild))[0]) == 32
    with pytest.raises(QuellenFehler, match="entpackt.*max_entpackt_mb"):
        _lesen({**_cfg("bevoelkerung_gemeinden", bild), "max_entpackt_mb": 2})


def test_falsche_blattgroesse_kuerzt_nichts(bericht, tmp_path):
    """openpyxl liest im Nur-Lese-Modus sonst nur bis zur Größe, die ein Blatt angibt (<dimension>)."""
    import re as regex

    def klein(daten: bytes) -> bytes:
        return regex.sub(rb'<dimension ref="[^"]*"', b'<dimension ref="A1:B5"', daten)
    teile = {f"xl/worksheets/sheet{i}.xml": klein for i in range(2, 17)}
    falsch = _umpacken(bericht(), tmp_path / "dim.xlsx", teile)
    with zipfile.ZipFile(falsch) as z:
        assert b'<dimension ref="A1:B5"' in z.read("xl/worksheets/sheet3.xml")
    ds, prot = _lesen(_cfg("bevoelkerung_gemeinden", falsch))
    assert len(ds) == 32 and not prot.warnungen, prot.warnungen


def test_keine_xlsx_datei(tmp_path):
    """Eine Datei, die kein lesbares ZIP ist, wird mit QuellenFehler abgelehnt."""
    kaputt = tmp_path / "kaputt.xlsx"
    kaputt.write_bytes(b"PK\x03\x04 kein zip")
    with pytest.raises(QuellenFehler, match="keine lesbare XLSX"):
        _lesen(_cfg("bevoelkerung_gemeinden", kaputt))


def test_ohne_defusedxml_kein_lesen(bericht, monkeypatch):
    """Liest openpyxl ohne defusedxml, liest die Pipeline die Datei nicht."""
    import openpyxl
    monkeypatch.setattr(openpyxl, "DEFUSEDXML", False)
    with pytest.raises(QuellenFehler, match="defusedxml"):
        _lesen(_cfg("bevoelkerung_gemeinden", bericht()))


def test_kreisfreie_staedte_kommen_nur_aus_blatt_2(bericht):
    """Gegenprobe zur Auswahl: Ohne die Ausnahme fielen die kreisfreien Städte als „Summen“ heraus."""
    cfg = _cfg("bevoelkerung_gemeinden", bericht())
    del cfg["zeilen_auswahl"]["ohne_ausser"]
    cfg.pop("summe")
    ds, _ = _lesen(cfg)
    assert len(ds) == 28 and not ({k[0] for k in KREISFREIE} & {d["objekt_id"] for d in ds})


# --- Prüfung nach E48 (06.11.2026) ---------------------------------------------------------------

def test_doppelter_schluessel_sperrt_das_loeschen(bericht):
    """Ändert sich ein Schlüssel in beiden Schlüsselspalten gleich in einen anderen vorhandenen (12060001 wird
    12060002), greift die Gegenprobe der Spalten nicht, und die Summen stimmen. Ein zweiter Treffer desselben
    Schlüssels macht den Abruf unvollständig, mit beiden Fundstellen; sonst würde 12060001 gelöscht."""
    kreise = gemeinden_je_kreis()
    kreise["3.1"][0] = ("12060002", 1001, 10.51)
    ds, prot = _lesen(_cfg("bevoelkerung_gemeinden", bericht(kreise=kreise)))
    assert prot.unvollstaendig, prot.warnungen
    assert any("mehrfach" in w and "12060002" in w and "Blatt 3.1, Zeile 7" in w and "Zeile 8" in w
               for w in prot.warnungen), prot.warnungen
    assert not any("Summe" in w for w in prot.warnungen), prot.warnungen   # die Summen sehen es nicht


def test_schluessel_in_fremdem_kreis_sperrt_das_loeschen(bericht):
    """Teilsummen (summe.teilsummen): Ein Gemeindeschlüssel, der in beiden Spalten in einen anderen Kreis
    wechselt (12060001 wird 12061009 im Blatt des Kreises 12060), gehört zu keiner Kreissumme seines
    Blatts."""
    kreise = gemeinden_je_kreis()
    kreise["3.1"][0] = ("12061009", 1001, 10.51)
    ds, prot = _lesen(_cfg("bevoelkerung_gemeinden", bericht(kreise=kreise)))
    assert prot.unvollstaendig, prot.warnungen
    assert any("12061009" in w and "Blatt 3.1, Zeile 7" in w and "Teilsumme" in w
               for w in prot.warnungen), prot.warnungen


def test_teilsumme_je_kreis(bericht):
    """Gleicht sich ein Fehler über das Land aus (ein Wert zu hoch in 3.1, einer zu niedrig in 3.2), sieht die
    Landessumme nichts; die Summe des Kreises im Blatt sieht es."""
    def verschieben(wb):
        for blatt, alt, neu in (("3.1", 1001, 1006), ("3.2", 2001, 1996)):
            for zeile in wb[blatt].iter_rows():
                if zeile[5].value == alt:
                    zeile[5].value = neu
    ds, prot = _lesen(_cfg("bevoelkerung_gemeinden", bericht(nachher=verschieben)))
    assert prot.unvollstaendig, prot.warnungen
    assert any("Teilsumme" in w and "12060000" in w and "12061000" in w for w in prot.warnungen), \
        prot.warnungen
    assert not any(w.startswith("Summe") for w in prot.warnungen), prot.warnungen
    # Ohne Fehler und mit der Rundung der Flächen innerhalb der Toleranz bleibt es stumm
    for name in ("bevoelkerung_gemeinden", "flaeche_gemeinden"):
        ds, prot = _lesen(_cfg(name, bericht()))
        assert len(ds) == 32 and not prot.warnungen, (name, prot.warnungen)


def test_nicht_endliche_zahl_ist_kein_wert(bericht, tmp_path):
    """1E999 liest openpyxl als unendlich; ein Paar +inf/-inf ergäbe als Summe NaN, und NaN > Toleranz ist
    falsch. Nicht endliche Zahlen sind kein Wert (keine Zahl, unvollständig, mit Blatt und Zeile)."""
    def unendlich(daten: bytes) -> bytes:
        return daten.replace(b"<v>1001</v>", b"<v>1E999</v>").replace(b"<v>1002</v>", b"<v>-1E999</v>")
    boese = _umpacken(bericht(), tmp_path / "inf.xlsx", {"xl/worksheets/sheet3.xml": unendlich})
    with zipfile.ZipFile(boese) as z:
        assert b"<v>1E999</v>" in z.read("xl/worksheets/sheet3.xml")
    ds, prot = _lesen(_cfg("bevoelkerung_gemeinden", boese))
    assert prot.unvollstaendig, prot.warnungen
    assert any("keine Zahl" in w and "Blatt 3.1, Zeile 7" in w for w in prot.warnungen), prot.warnungen
    assert next(d for d in ds if d["objekt_id"] == "12060001")["werte"] == {"bevoelkerung": None}


def test_summenzeile_nicht_endlich_und_unlesbare_zahl(bericht, tmp_path):
    """Eine Summenzeile, die nicht endlich ist, besteht die Probe nicht. „NaN“ als Zahlzelle kann openpyxl
    nicht lesen (ValueError beim Lesen der Zeilen); das ist ein Quellenbefund, kein technischer Abbruch."""
    land = str(sum(g[1] for g in KREISFREIE) + sum(g[1] for k in gemeinden_je_kreis().values()
                                                   for g in k)).encode()

    def setzen(text: bytes):
        def ersetzen(daten: bytes) -> bytes:
            assert b"<v>" + land + b"</v>" in daten
            return daten.replace(b"<v>" + land + b"</v>", b"<v>" + text + b"</v>")
        return ersetzen
    boese = _umpacken(bericht(), tmp_path / "inf.xlsx", {"xl/worksheets/sheet2.xml": setzen(b"1E999")})
    ds, prot = _lesen(_cfg("bevoelkerung_gemeinden", boese))
    assert prot.unvollstaendig and any("12000000" in w for w in prot.warnungen), prot.warnungen
    boese = _umpacken(bericht(), tmp_path / "nan.xlsx", {"xl/worksheets/sheet2.xml": setzen(b"NaN")})
    with pytest.raises(QuellenFehler, match="Blatt 2.*nicht lesbar"):
        _lesen(_cfg("bevoelkerung_gemeinden", boese))


def test_formel_ohne_zwischenwert(bericht):
    """data_only=True: openpyxl liefert den zwischengespeicherten Wert einer Formel; ohne ihn (Datei nicht in
    Excel berechnet) None. Schlüssel als Formel ohne Wert: Datenzeile ohne gültigen Schlüssel, unvollständig.
    Wert als Formel ohne Wert: kein Wert, die Summen fallen ab, unvollständig."""
    def schluessel_formel(wb):
        wb["3.1"]["B7"] = wb["3.1"]["I7"] = "=12060000+1"
    ds, prot = _lesen(_cfg("bevoelkerung_gemeinden", bericht(nachher=schluessel_formel)))
    assert prot.unvollstaendig and "12060001" not in {d["objekt_id"] for d in ds}
    assert any("ohne gültigen Schlüssel" in w and "Blatt 3.1, Zeile 7" in w for w in prot.warnungen)

    def wert_formel(wb):
        wb["3.1"]["F7"] = "=1000+1"
    ds, prot = _lesen(_cfg("bevoelkerung_gemeinden", bericht(nachher=wert_formel)))
    assert next(d for d in ds if d["objekt_id"] == "12060001")["werte"] == {"bevoelkerung": None}
    assert prot.unvollstaendig and any("Summe" in w for w in prot.warnungen), prot.warnungen


def test_externe_verknuepfung_wird_nicht_geladen(bericht, tmp_path):
    """keep_links=False: Externe Verknüpfungen (xl/externalLinks) liest openpyxl nicht. Gegenprobe: Mit
    keep_links=True scheitert dieselbe Datei an der kaputten Verknüpfung."""
    import openpyxl
    rel = (b'<Relationship Id="rIdExt1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
           b'relationships/externalLink" Target="externalLinks/externalLink1.xml"/></Relationships>')
    typ = (b'<Override PartName="/xl/externalLinks/externalLink1.xml" '
           b'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.externalLink+xml"/>'
           b'</Types>')
    ref = (b'<externalReferences><externalReference xmlns:r="http://schemas.openxmlformats.org/officeDocument/'
           b'2006/relationships" r:id="rIdExt1"/></externalReferences><calcPr')
    datei = _umpacken(bericht(), tmp_path / "extern.xlsx", {
        "xl/_rels/workbook.xml.rels": lambda d: d.replace(b"</Relationships>", rel),
        "[Content_Types].xml": lambda d: d.replace(b"</Types>", typ),
        "xl/workbook.xml": lambda d: d.replace(b"<calcPr", ref, 1)},
        dazu={"xl/externalLinks/externalLink1.xml": b"<externalLink><kaputt>"})
    with zipfile.ZipFile(datei) as z:
        assert b"externalReference " in z.read("xl/workbook.xml")
    with pytest.raises(Exception):  # noqa: B017 - jede Ausnahme genügt als Gegenprobe
        openpyxl.load_workbook(datei, read_only=True, data_only=True, keep_links=True)
    ds, prot = _lesen(_cfg("bevoelkerung_gemeinden", datei))
    assert len(ds) == 32 and not prot.warnungen, prot.warnungen


def _blatt_umbenennen(quelle: Path, ziel: Path, alt: str, neu: str, ersetzen=None) -> Path:
    """Blatt-Teil unter einem anderen Namen (Endung ohne .xml), mit angepassten rels und [Content_Types]."""
    with zipfile.ZipFile(quelle) as a, zipfile.ZipFile(ziel, "w", zipfile.ZIP_DEFLATED) as n:
        for info in a.infolist():
            daten = a.read(info)
            if info.filename == alt and ersetzen:
                daten = ersetzen(daten)
            if info.filename.endswith((".rels", ".xml")):
                daten = daten.replace(alt.removeprefix("xl/").encode(), neu.removeprefix("xl/").encode())
            n.writestr(neu if info.filename == alt else info.filename, daten)
    return ziel


def test_blatt_ohne_xml_endung_wird_geprueft(bericht, tmp_path):
    """openpyxl liest ein Blatt über rels und [Content_Types], gleich welche Endung der Teil hat. Größe,
    Packrate und DTD gelten deshalb für alle Teile, nicht nur für .xml und .rels."""
    import openpyxl
    teil, neu = "xl/worksheets/sheet3.xml", "xl/worksheets/sheet3.dat"
    umbenannt = _blatt_umbenennen(bericht(), tmp_path / "dat.xlsx", teil, neu)
    assert neu in zipfile.ZipFile(umbenannt).namelist()
    assert "3.1" in openpyxl.load_workbook(umbenannt, read_only=True).sheetnames
    assert len(_lesen(_cfg("bevoelkerung_gemeinden", umbenannt))[0]) == 32   # liest wie vorher

    def aufblasen(daten: bytes) -> bytes:
        return daten.replace(b"</sheetData>", b"</sheetData>" + b" " * (3 << 20), 1) \
            if b"</sheetData>" in daten else daten
    gross = _blatt_umbenennen(bericht(), tmp_path / "gross.xlsx", teil, neu, aufblasen)
    with pytest.raises(QuellenFehler, match="Packrate"):
        _lesen(_cfg("bevoelkerung_gemeinden", gross))
    cfg = {**_cfg("bevoelkerung_gemeinden", gross), "max_packrate": 100000, "max_entpackt_mb": 2}
    with pytest.raises(QuellenFehler, match="entpackt.*max_entpackt_mb"):
        _lesen(cfg)

    def mit_dtd(daten: bytes) -> bytes:   # openpyxl schreibt Blätter ohne XML-Deklaration
        return b'<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]>' + daten
    dtd = _blatt_umbenennen(bericht(), tmp_path / "dtd.xlsx", teil, neu, mit_dtd)
    with pytest.raises(QuellenFehler, match="DTD oder Entität"):
        _lesen(_cfg("bevoelkerung_gemeinden", dtd))


@pytest.mark.parametrize("kodierung", ["ISO-8859-1", "us-ascii", "windows-1252"])
def test_nur_utf8_auch_laut_deklaration(bericht, tmp_path, kodierung):
    """Eine ASCII-verträgliche Kodierung in der XML-Deklaration wird abgelehnt; zugelassen ist nur UTF-8
    (oder keine Angabe)."""
    def anders(daten: bytes) -> bytes:   # openpyxl schreibt Blätter ohne XML-Deklaration
        assert not daten.startswith(b"<?xml")
        return f'<?xml version="1.0" encoding="{kodierung}" standalone="yes"?>\n'.encode() + daten
    boese = _umpacken(bericht(), tmp_path / "latin.xlsx", {"xl/worksheets/sheet2.xml": anders})
    with zipfile.ZipFile(boese) as z:
        assert f'encoding="{kodierung}"'.encode() in z.read("xl/worksheets/sheet2.xml")
    with pytest.raises(QuellenFehler, match="UTF-8"):
        _lesen(_cfg("bevoelkerung_gemeinden", boese))
    # UTF-8 in der Deklaration (auch klein geschrieben) liest wie vorher
    gut = _umpacken(bericht(), tmp_path / "utf8.xlsx", {"xl/worksheets/sheet2.xml": lambda d: (
        b'<?xml version="1.0" encoding="utf-8"?>\n' + d)})
    assert len(_lesen(_cfg("bevoelkerung_gemeinden", gut))[0]) == 32
    # Bilder, Druckeinstellungen und eingebettete Dateien sind kein XML und werden nicht als XML geprüft
    teile = {"xl/media/image7.emf": b"\x01\x00\x00\x00" + bytes(range(256)) * 64,
             "xl/printerSettings/printerSettings1.bin": "PDF-Drucker".encode("utf-16-le"),
             "xl/media/image1.svg": b'<svg xmlns="http://www.w3.org/2000/svg"/>'}
    gut = _umpacken(bericht(), tmp_path / "medien.xlsx", dazu=teile)
    assert len(_lesen(_cfg("bevoelkerung_gemeinden", gut))[0]) == 32


def test_gesperrter_pfad_auf_dem_rechner_der_seite_wird_nie_gewaehlt(monkeypatch):
    """robots.txt von www.statistik-berlin-brandenburg.de sperrt /scrivito/. Ein Link dorthin zählt wie ein
    fremder, auch auf dem Rechner der Seite und auch prozentkodiert."""
    seite = "https://www.statistik-berlin-brandenburg.de/a-i-4-a-v-2-j/"
    cfg = {**_link_cfg(), "seite": seite, "link_rechner": ["download.statistik-berlin-brandenburg.de"]}
    abgerufen = []

    def abrufen(url, params, cfg, prot):
        abgerufen.append(url)
        return _seite(links)
    monkeypatch.setattr(quellen, "abrufen", abrufen)
    gut = "https://download.statistik-berlin-brandenburg.de/a/b/SB_A01-04_00_2025j01_BB.xlsx"
    links = ["/scrivito/blob/SB_A01-04_00_2026j01_BB.xlsx", "/%73crivito/x/SB_A01-04_00_2026j01_BB.xlsx", gut]
    assert quellen.link_ermitteln(cfg, Protokoll()) == gut
    links = links[:2]
    with pytest.raises(QuellenFehler, match="Kein Link.*2 passende Links"):
        quellen.link_ermitteln(cfg, Protokoll())
    assert abgerufen == [seite, seite]


def test_link_mit_kaputtem_port_zaehlt_als_fremd(monkeypatch):
    """Ein Link mit nicht numerischem Port zählt wie ein fremder: Er wird übergangen und in der Meldung
    mitgezählt, statt die Quelle mit ValueError scheitern zu lassen."""
    gut = "https://download.statistik.example/a/b/SB_A01-04_00_2025j01_BB.xlsx"
    kaputt = "https://download.statistik.example:abc/SB_A01-04_00_2026j01_BB.xlsx"
    assert _link(monkeypatch, [kaputt, gut]) == gut
    with pytest.raises(QuellenFehler, match="Kein Link.*1 passende Links"):
        _link(monkeypatch, [kaputt])


@pytest.mark.parametrize("url", ["https://www.regionalstatistik.de/genesis/online",
                                 "https://www.bbr-server.de/imagemap/inkar/download/inkar_2025.zip",
                                 "https://WWW.BBR-SERVER.DE./x",
                                 "https://www.statistik-berlin-brandenburg.de/scrivito/blob/a.xlsx",
                                 "https://www.statistik-berlin-brandenburg.de/%73crivito/blob/a.xlsx",
                                 "https://sgx.geodatenzentrum.de/gdz_geoviewserver/x"])
def test_robots_gesperrte_pfade_werden_nie_abgerufen(tmp_path, url):
    """Andrés Regel: per robots.txt gesperrte Pfade nie abrufen. Vor jeder Verbindung (GET, Dateiabruf,
    HEAD-Suche) prüft die Pipeline die Sperren; der Test sperrt das Netz (kein_netz): Käme ein Abruf vor der
    Sperre zustande, endete er mit AssertionError statt QuellenFehler, und der Test schlüge fehl."""
    for aufruf in (lambda: quellen.abrufen(url, None, {}, Protokoll()),
                   lambda: quellen.datei_abrufen(url, tmp_path / "a.zip", {}, Protokoll()),
                   lambda: quellen.neueste_url(url + "{jahr}", {}, Protokoll())):
        with pytest.raises(QuellenFehler, match="robots.txt"):
            aufruf()
    erlaubt = "https://www.statistik-berlin-brandenburg.de/a-i-4-a-v-2-j/"
    assert quellen.robots_gesperrt(erlaubt) is None
    assert quellen.robots_gesperrt("https://sgx.geodatenzentrum.de/wfs_vg250") is None


# --- E50: Codefehler aus E49 ----------------------------------------------------------------------------

@pytest.mark.parametrize("kopf", [" \x00<\x00?\x00x\x00", "\n\x00\t\x00<\x00a\x00", "\x00 \x00<\x00a",
                                  "\x00\x00\x00<\x00\x00\x00a", "<\x00\x00\x00a\x00\x00\x00",
                                  "\x00\x00\x00 \x00\x00\x00<"],
                         ids=["utf16le_leerraum", "utf16le_umbruch", "utf16be_leerraum", "utf32be", "utf32le",
                              "utf32be_leerraum"])
def test_xml_in_utf16_oder_utf32_ohne_bom_wird_abgelehnt(tmp_path, kopf):
    """E50, Codefehler aus E49 (_xlsx_teil_pruefen): Ein XML-Parser erkennt UTF-16 und UTF-32 auch ohne BOM am
    ersten „<“, auch nach Leerraum. Bis E49 sah die Prüfung nur „<“ direkt am Anfang neben einem Nullbyte;
    UTF-32BE (00 00 00 3C) und UTF-16 mit Leerraum davor gingen als Nicht-XML durch, und die Suche nach
    <!DOCTYPE in UTF-8-Bytes übersah sie."""
    datei = tmp_path / "teil.zip"
    with zipfile.ZipFile(datei, "w") as z:
        z.writestr("xl/worksheets/sheet9.bin", kopf.encode("latin-1") + b"\x00" * 8)
    with zipfile.ZipFile(datei) as z, pytest.raises(QuellenFehler, match="UTF-8"):
        quellen._xlsx_teil_pruefen(z, z.infolist()[0])


def test_nicht_xml_teile_bleiben_erlaubt(tmp_path):
    """E50, Gegenprobe: Bilder (EMF beginnt mit 01 00 00 00, PNG), Druckeinstellungen in UTF-16 ohne „<“ und
    UTF-8-XML ohne Deklaration bleiben erlaubt; der echte Bericht des Amts (EMF mit 7,6 MB) besteht weiter
    (nachgerechnet an der lokalen Kopie, E50)."""
    datei = tmp_path / "teile.zip"
    teile = {"xl/media/image1.emf": b"\x01\x00\x00\x00" + bytes(range(256)),
             "xl/media/image2.png": b"\x89PNG\r\n\x1a\n" + b"\x00" * 16,
             "xl/printerSettings/p.bin": "PDF-Drucker".encode("utf-16-le"),
             "xl/worksheets/sheet1.xml": b"  <worksheet/>"}
    with zipfile.ZipFile(datei, "w") as z:
        for n, d in teile.items():
            z.writestr(n, d)
    with zipfile.ZipFile(datei) as z:
        for i in z.infolist():
            quellen._xlsx_teil_pruefen(z, i)


def test_juengste_ausgabe_nach_zahl_nicht_nach_text(monkeypatch):
    """E50, Codefehler aus E49 (link_ermitteln): Die Gruppe `jahr` wurde als Text verglichen; „999“ lag dann
    hinter „2025“. Jetzt zählt der Zahlenwert (bei vierstelligen Jahren wie bisher)."""
    cfg = {"seite": SEITE, "datei_muster": r"^bericht_(?P<jahr>\d+)\.xlsx$",
           "link_rechner": ["download.statistik.example"]}
    neu = "https://download.statistik.example/bericht_2025.xlsx"
    assert _link(monkeypatch, ["https://download.statistik.example/bericht_999.xlsx", neu], cfg) == neu
    assert _link(monkeypatch, [neu, "https://download.statistik.example/bericht_10000.xlsx"], cfg) \
        .endswith("_10000.xlsx")


# --- E51: Prüfbericht vom 07.11.2026, 03:13 (K2: zweifelhafte Restzeilen) -----------------------------------

@pytest.mark.parametrize("schluessel", ["12O60003", "1206003", 12060003.5],
                         ids=["buchstabe", "zu_kurz", "kommazahl"])
def test_xlsx_beschaedigter_schluessel_ohne_wert_ist_nicht_stumm(bericht, schluessel):
    """E51, Befund K2 sinngemäß für XLSX: Eine Zeile ohne gültigen Schlüssel und ohne Wert galt als Leer-,
    Titel- oder Fußnotenzeile und blieb stumm. Steht in der Schlüsselspalte aber etwas in Schlüsselform
    (Ziffern mit höchstens einem anderen Zeichen, ohne Leerraum) oder ein Wert, der kein Text ist, war es
    vermutlich eine Datenzeile; ihr bisheriger Wert konnte gelöscht werden, und die Summen merken das nicht,
    wenn die Zeile keinen Wert mehr trägt. Jetzt ist der Abruf unvollständig, nichts wird gelöscht.
    Fußnoten wie „1 Bevölkerungsfortschreibung …“ und „4 Stand 31.12.2024“ bleiben stumm (Gegenprobe in
    test_konfiguration_bevoelkerung_gemeinden_waehlt_gemeinden_und_kreisfreie)."""
    kreise = gemeinden_je_kreis()
    kreise["3.1"] = [*kreise["3.1"], (schluessel, None, None)]
    ds, prot = _lesen(_cfg("bevoelkerung_gemeinden", bericht(kreise=kreise)))
    assert len(ds) == 32 and prot.unvollstaendig, prot.warnungen
    (w,) = [w for w in prot.warnungen if "ohne gültigen Schlüssel" in w]
    assert "Blatt 3.1, Zeile 9" in w and "nichts wird gelöscht" in w
