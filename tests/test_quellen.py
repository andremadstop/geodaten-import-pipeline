"""Tests der Adapter ohne Netz und ohne Datenbank: Abruf-Regeln, XML-Härtung, CSV.

Alles hier gehört zur Stufe quellen (laden → quellen → ziel); requests.get bzw. quellen.abrufen sind
durch Stellvertreter ersetzt, es geht keine Anfrage ins Netz. Abgesichert werden:
- Abrufregeln: nur https (http nur ausdrücklich), keine Weiterleitungen, Größengrenze, Kennung gegenüber
  dem Anbieter (E9), nachstellbare Abfrage für den Meldungsentwurf (E8);
- XML-Härtung gegen Entitäten und externe Dateien, Fehlerberichte des Dienstes als Ausnahme;
- WFS: Paging und Kachelung (E6), Belege für die Vollständigkeit je Seite und Kachel (E46, E47), WFS
  1.1.0, Pause zwischen Abrufen (E36), Feldprüfung ohne Schema;
- CSV und Statistiktabellen (E19, E47): Datenbereich, Stichtag aus dem Kopf, Kopfprüfung, leere Zeilen
  (E41, E42) und beschädigte Schlüssel, die das Löschen sperren (E23, E32).
Die Statistiktabelle ist ein Auszug mit erfundenen Zahlen in tests/daten/ (keine echten Quelldaten im
Repository, E38). Seit E50: Sperre auf dem gesendeten Pfad, OWS 1.0, engere Zahlenregel, Ablehnung beim
Schema, Kachelgröße, Inhaltsvergleich doppelter WFS-IDs, Zeilennummern der CSV und Zeitbudget je Anfrage.
"""
from pathlib import Path

import pytest
from lxml import etree

from pipeline import quellen
from pipeline.quellen import Protokoll, QuellenFehler


class Antwort:
    """Ersatz für requests.Response mit dem, was abrufen() benutzt."""

    def __init__(self, inhalt=b"", status=200, kopf=None, weiterleitung=False):
        self.inhalt, self.status_code = inhalt, status
        self.headers = kopf or {}
        self.is_redirect = weiterleitung
        self.url = "https://dienst.example/ows"

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def iter_content(self, n):
        for i in range(0, len(self.inhalt), n):
            yield self.inhalt[i:i + n]


@pytest.fixture
def antwort(monkeypatch):
    """Fixture: ersetzt requests.get so, dass jeder Abruf die mit den Schlüsselwörtern beschriebene Antwort
    liefert; aufgerufen als antwort(inhalt=…, status=…, kopf=…, weiterleitung=…)."""
    def setzen(**kw):
        monkeypatch.setattr(quellen.requests, "get", lambda *a, **k: Antwort(**kw))
    return setzen


def test_nur_https(antwort):
    """Eine http-Adresse ohne Freigabe wird mit QuellenFehler abgelehnt. Ob vorher eine Verbindung versucht
    wurde, prüft der Test nicht (der Ersatz für requests.get würde erfolgreich antworten)."""
    antwort(inhalt=b"<a/>")
    with pytest.raises(QuellenFehler, match="https"):
        quellen.abrufen("http://dienst.example/ows", None, {}, Protokoll())


def test_http_nur_mit_ausdruecklicher_freigabe(antwort):
    """Mit `erlaube_http: true` in der Quelle ist http erlaubt, und abrufen liefert den Inhalt."""
    antwort(inhalt=b"<a/>")
    assert quellen.abrufen("http://dienst.example/ows", None, {"erlaube_http": True}, Protokoll()) == b"<a/>"


def test_weiterleitung_wird_nicht_verfolgt(antwort):
    """Eine Weiterleitung wird nicht verfolgt; der Fehler nennt das Weiterleitungsziel, damit die URL in der
    Konfiguration berichtigt werden kann."""
    antwort(weiterleitung=True, kopf={"Location": "https://anderswo.example/"})
    with pytest.raises(QuellenFehler, match="anderswo"):
        quellen.abrufen("https://dienst.example/ows", None, {}, Protokoll())


def test_abruf_nennt_sich_gegenueber_dem_anbieter(monkeypatch):
    """Jeder Abruf sendet einen User-Agent, standardmäßig die Kennung der Pipeline, mit PIPELINE_KENNUNG die
    des Betreibers (E9)."""
    gesendet = {}

    def get(*a, **k):
        gesendet.update(k.get("headers") or {})
        return Antwort(inhalt=b"<a/>")
    monkeypatch.setattr(quellen.requests, "get", get)
    quellen.abrufen("https://dienst.example/ows", None, {}, Protokoll())
    assert gesendet["User-Agent"].startswith("geodaten-import-pipeline")
    monkeypatch.setenv("PIPELINE_KENNUNG", "MOSIDI-Import (mosidi@hochschule.example)")
    quellen.abrufen("https://dienst.example/ows", None, {}, Protokoll())
    assert gesendet["User-Agent"] == "MOSIDI-Import (mosidi@hochschule.example)"


def test_groessenlimit_greift_auch_ohne_content_length(antwort):
    """Kündigt der Dienst keine Größe an, bricht abrufen beim Mitzählen ab, sobald die Antwort max_mb
    überschreitet."""
    antwort(inhalt=b"x" * (2 * 1024 * 1024))
    with pytest.raises(QuellenFehler, match="größer"):
        quellen.abrufen("https://dienst.example/ows", None, {"max_mb": 1}, Protokoll())


def test_abfrage_wird_vor_dem_senden_festgehalten(monkeypatch):
    """Die vollständige Abfrage-URL steht schon vor dem Senden im Protokoll, damit auch ein gescheiterter
    Abruf für die Meldung nachstellbar bleibt (E8)."""
    def scheitern(*a, **k):
        raise ConnectionError("weg")
    monkeypatch.setattr(quellen.requests, "get", scheitern)
    prot = Protokoll()
    with pytest.raises(ConnectionError):
        quellen.abrufen("https://dienst.example/ows", {"REQUEST": "GetCapabilities"}, {}, prot)
    assert prot.letzte_abfrage == "https://dienst.example/ows?REQUEST=GetCapabilities"


def test_xml_entitaeten_werden_nicht_aufgeloest():
    """Verschachtelte Entitäten („Billion Laughs“) werden nicht aufgelöst: Die aufgeblähte Zeichenkette
    erscheint nicht im Text. Den Speicher misst der Test nicht."""
    bombe = b"""<?xml version="1.0"?>
<!DOCTYPE b [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">
<!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;"><!ENTITY d "&c;&c;&c;&c;&c;&c;&c;&c;&c;&c;">]>
<wurzel>&d;</wurzel>"""
    root = quellen.xml_lesen(bombe)
    assert "aaaa" not in "".join(root.itertext())


def test_xml_externe_entitaet_liest_keine_datei():
    """Eine externe Entität (XXE) liest keine lokale Datei in die Antwort."""
    xxe = b"""<?xml version="1.0"?>
<!DOCTYPE w [<!ENTITY geheim SYSTEM "file:///etc/passwd">]><w>&geheim;</w>"""
    root = quellen.xml_lesen(xxe)
    assert "root:" not in "".join(root.itertext())


def test_wfs_fehlerbericht_wird_zur_ausnahme():
    """Ein ows:ExceptionReport des Dienstes wird zur Ausnahme mit dem Fehlertext des Dienstes, statt als leere
    Antwort durchzugehen."""
    fehler = b"""<ows:ExceptionReport xmlns:ows="http://www.opengis.net/ows/1.1">
<ows:Exception><ows:ExceptionText>Unbekannter Typ</ows:ExceptionText></ows:Exception></ows:ExceptionReport>"""
    with pytest.raises(RuntimeError, match="Unbekannter Typ"):
        quellen.xml_lesen(fehler)


def test_capabilities_kontakt_und_paging():
    """capabilities_lesen liest Anbieter, Kontakt, updateSequence, Paging und Sortierung; CountDefault zählt
    nur, wenn der Dienst es nennt."""
    cap = b"""<wfs:WFS_Capabilities xmlns:wfs="http://www.opengis.net/wfs/2.0"
 xmlns:ows="http://www.opengis.net/ows/1.1" updateSequence="42">
<ows:ServiceProvider><ows:ProviderName>Amt</ows:ProviderName><ows:ServiceContact><ows:ContactInfo>
<ows:Address><ows:ElectronicMailAddress>service@amt.example</ows:ElectronicMailAddress></ows:Address>
</ows:ContactInfo></ows:ServiceContact></ows:ServiceProvider>
<ows:OperationsMetadata><ows:Constraint name="ImplementsResultPaging"><ows:NoValues/>
<ows:DefaultValue>TRUE</ows:DefaultValue></ows:Constraint></ows:OperationsMetadata></wfs:WFS_Capabilities>"""
    info = quellen.capabilities_lesen(etree.fromstring(cap))
    assert info == {"titel": None, "beschreibung": None, "anbieter": "Amt", "email": "service@amt.example",
                    "update_sequence": "42", "paging": True, "sortierung": False, "count_default": None}
    # CountDefault (WFS 2.0): Höchstzahl des Dienstes je Antwort, Beleg für die Vollständigkeit einer Kachel
    mit = cap.replace(b"</ows:OperationsMetadata>", b'<ows:Constraint name="CountDefault"><ows:NoValues/>'
                      b"<ows:DefaultValue>100000</ows:DefaultValue></ows:Constraint></ows:OperationsMetadata>")
    assert quellen.capabilities_lesen(etree.fromstring(mit))["count_default"] == 100000


def _gml_seite(ids):
    """GetFeature-Antwort (WFS 2.0, GML 3.2) mit je einem Punktobjekt je ID und numberReturned, aber ohne
    numberMatched."""
    teile = "".join(
        f'<wfs:member><x:o><x:oid>{i}</x:oid><x:geom><gml:Point><gml:pos>1 2</gml:pos>'
        f'</gml:Point></x:geom></x:o></wfs:member>' for i in ids)
    return (f'<wfs:FeatureCollection xmlns:wfs="http://www.opengis.net/wfs/2.0" '
            f'xmlns:gml="http://www.opengis.net/gml/3.2" xmlns:x="urn:x" '
            f'numberReturned="{len(ids)}">{teile}</wfs:FeatureCollection>').encode()


def test_wfs_holt_mehrere_seiten_sortiert(monkeypatch):
    """Paging über mehrere Seiten: STARTINDEX zählt weiter, bis eine Seite leer ist (ohne numberMatched
    beweist eine kürzere Seite das Ende nicht, E46); SORTBY nach der Objekt-ID, weil der Dienst
    Sortierung meldet; doppelte IDs fallen raus."""
    cap = b"""<wfs:WFS_Capabilities xmlns:wfs="http://www.opengis.net/wfs/2.0"
 xmlns:ows="http://www.opengis.net/ows/1.1"><ows:OperationsMetadata>
<ows:Constraint name="ImplementsResultPaging"><ows:NoValues/>
<ows:DefaultValue>TRUE</ows:DefaultValue></ows:Constraint>
<ows:Constraint name="ImplementsSorting"><ows:NoValues/>
<ows:DefaultValue>TRUE</ows:DefaultValue></ows:Constraint>
</ows:OperationsMetadata></wfs:WFS_Capabilities>"""
    seiten = {0: ["a", "b"], 2: ["c", "c"], 4: ["e"], 5: []}
    anfragen = []

    def abrufen(url, params, cfg, prot):
        if params["REQUEST"] == "GetCapabilities":
            return cap
        if params["REQUEST"] == "DescribeFeatureType":
            raise RuntimeError("kein Schema im Test")
        anfragen.append(params)
        return _gml_seite(seiten[params["STARTINDEX"]])

    monkeypatch.setattr(quellen, "abrufen", abrufen)
    cfg = {"url": "https://dienst.example/ows", "typename": "x:o", "id_feld": "oid",
           "geometrie_feld": "geom", "bbox": [0, 0, 1, 1], "seitengroesse": 2}
    prot = Protokoll()
    objekte = list(quellen.wfs(cfg, prot))
    assert [o["objekt_id"] for o in objekte] == ["a", "b", "c", "e"]
    assert [a["STARTINDEX"] for a in anfragen] == [0, 2, 4, 5]
    assert all(a["SORTBY"] == "oid ASC" for a in anfragen)
    assert prot.info["seiten"] == 4 and not prot.unvollstaendig
    assert not [w for w in prot.warnungen if w.startswith("Nur ")]


def test_wfs_warnt_wenn_seiten_objekte_verlieren(monkeypatch):
    """Ohne Sortierung kann ein Objekt zwischen zwei Seiten rutschen: weniger als gemeldet = Warnung."""
    cap = b"""<wfs:WFS_Capabilities xmlns:wfs="http://www.opengis.net/wfs/2.0"
 xmlns:ows="http://www.opengis.net/ows/1.1"><ows:OperationsMetadata>
<ows:Constraint name="ImplementsResultPaging"><ows:NoValues/>
<ows:DefaultValue>TRUE</ows:DefaultValue></ows:Constraint>
</ows:OperationsMetadata></wfs:WFS_Capabilities>"""
    seiten = {0: ["a", "b"], 2: ["b", "d"], 4: []}

    def abrufen(url, params, cfg, prot):
        if params["REQUEST"] == "GetCapabilities":
            return cap
        if params["REQUEST"] == "DescribeFeatureType":
            raise RuntimeError("kein Schema im Test")
        assert "SORTBY" not in params
        seite = _gml_seite(seiten[params["STARTINDEX"]])
        return seite.replace(b"numberReturned", b'numberMatched="5" numberReturned')

    monkeypatch.setattr(quellen, "abrufen", abrufen)
    cfg = {"url": "https://dienst.example/ows", "typename": "x:o", "id_feld": "oid",
           "geometrie_feld": "geom", "bbox": [0, 0, 1, 1], "seitengroesse": 2}
    prot = Protokoll()
    assert [o["objekt_id"] for o in quellen.wfs(cfg, prot)] == ["a", "b", "d"]
    assert "ImplementsSorting=FALSE" in prot.hinweise[-1]
    assert any("Nur 3 von 5" in w for w in prot.warnungen)


def test_wfs_paging_ohne_gesamtzahl_und_sortierung_prueft_doppelte(monkeypatch):
    """Nachprüfung zu E47 (zu Befund 9, gleiche Lücke im Blätterzweig): Ohne numberMatched und ohne
    Sortierung belegte die leere Seite das Ende, auch wenn ein Objekt zwischen zwei Seiten gerutscht war (es
    gab nur einen Hinweis). Weniger verschiedene Objekte als gezählt: unvollständig."""
    cap = b"""<wfs:WFS_Capabilities xmlns:wfs="http://www.opengis.net/wfs/2.0"
 xmlns:ows="http://www.opengis.net/ows/1.1"><ows:OperationsMetadata>
<ows:Constraint name="ImplementsResultPaging"><ows:NoValues/>
<ows:DefaultValue>TRUE</ows:DefaultValue></ows:Constraint>
</ows:OperationsMetadata></wfs:WFS_Capabilities>"""
    seiten = {0: ["a", "b"], 2: ["b", "d"], 4: []}

    def abrufen(url, params, cfg, prot):
        if params["REQUEST"] == "GetCapabilities":
            return cap
        if params["REQUEST"] == "DescribeFeatureType":
            raise RuntimeError("kein Schema im Test")
        return _gml_seite(seiten[params["STARTINDEX"]])

    monkeypatch.setattr(quellen, "abrufen", abrufen)
    cfg = {"url": "https://dienst.example/ows", "typename": "x:o", "id_feld": "oid",
           "geometrie_feld": "geom", "bbox": [0, 0, 1, 1], "seitengroesse": 2}
    prot = Protokoll()
    assert [o["objekt_id"] for o in quellen.wfs(cfg, prot)] == ["a", "b", "d"]
    assert prot.unvollstaendig
    assert any("3 verschiedene Objekte bei 4 gezählten" in w for w in prot.warnungen), prot.warnungen


_CAP_PAGING = b"""<wfs:WFS_Capabilities xmlns:wfs="http://www.opengis.net/wfs/2.0"
 xmlns:ows="http://www.opengis.net/ows/1.1"><ows:OperationsMetadata>
<ows:Constraint name="ImplementsResultPaging"><ows:NoValues/>
<ows:DefaultValue>TRUE</ows:DefaultValue></ows:Constraint>
</ows:OperationsMetadata></wfs:WFS_Capabilities>"""


def _dienst_mit_limit(objekte: list[str], limit: int, anfragen: list, startindex_beachten: bool = True):
    """WFS ohne numberMatched, der höchstens `limit` Objekte je Seite liefert, gleich wie viele verlangt."""
    def abrufen(url, params, cfg, prot):
        if params["REQUEST"] == "GetCapabilities":
            return _CAP_PAGING
        if params["REQUEST"] == "DescribeFeatureType":
            raise RuntimeError("kein Schema im Test")
        anfragen.append(params["STARTINDEX"])
        start = params["STARTINDEX"] if startindex_beachten else 0
        return _gml_seite(objekte[start:start + min(limit, params["COUNT"])])
    return abrufen


def test_wfs_kuerzere_seite_ohne_gesamtzahl_beweist_kein_ende(monkeypatch):
    """Prüfbericht 05.11., F5 (E46): Ohne numberMatched beendete eine kürzere Seite den Abruf. Ein Dienst
    mit kleinerem Seitenlimit (hier 3 statt 5) galt so nach der ersten Seite als vollständig; die übrigen
    Objekte fehlten, und das Löschen war frei. Jetzt fragt die Pipeline am nächsten startIndex weiter,
    erst eine leere Antwort beweist das Ende."""
    anfragen = []
    objekte = [f"o{i}" for i in range(8)]
    monkeypatch.setattr(quellen, "abrufen", _dienst_mit_limit(objekte, 3, anfragen))
    cfg = {"url": "https://dienst.example/ows", "typename": "x:o", "id_feld": "oid",
           "geometrie_feld": "geom", "bbox": [0, 0, 1, 1], "seitengroesse": 5}
    prot = Protokoll()
    assert [o["objekt_id"] for o in quellen.wfs(cfg, prot)] == objekte
    assert anfragen == [0, 3, 6, 8] and not prot.unvollstaendig


def test_wfs_dienst_uebergeht_startindex_endet_unvollstaendig(monkeypatch):
    """Weiterblättern bis zur leeren Seite darf nicht endlos laufen, wenn ein Dienst STARTINDEX übergeht und
    immer dieselbe Seite liefert: Eine Seite ohne neues Objekt beendet den Abruf als unvollständig (E46)."""
    anfragen = []
    monkeypatch.setattr(quellen, "abrufen", _dienst_mit_limit(["a", "b", "c"], 2, anfragen, False))
    cfg = {"url": "https://dienst.example/ows", "typename": "x:o", "id_feld": "oid",
           "geometrie_feld": "geom", "bbox": [0, 0, 1, 1], "seitengroesse": 5}
    prot = Protokoll()
    assert [o["objekt_id"] for o in quellen.wfs(cfg, prot)] == ["a", "b"]
    assert anfragen == [0, 2] and prot.unvollstaendig
    assert any("kein neues Objekt" in w for w in prot.warnungen)


def test_wfs_geometrie_hinter_kommentar_und_leere_felder(monkeypatch):
    """deegree (Verwaltungsgrenzen der LGB) setzt einen Kommentar vor die Geometrie; leere Felder
    (nur Zeilenumbruch) werden null statt leerer Text."""
    cap = b"""<wfs:WFS_Capabilities xmlns:wfs="http://www.opengis.net/wfs/2.0"
 xmlns:ows="http://www.opengis.net/ows/1.1"/>"""
    seite = b"""<wfs:FeatureCollection xmlns:wfs="http://www.opengis.net/wfs/2.0"
 xmlns:gml="http://www.opengis.net/gml/3.2" xmlns:app="urn:app" numberReturned="1"><wfs:member>
<app:krs gml:id="krs_1"><!-- Kommentar --><app:krss>12051</app:krss><app:krs_regspr_name>
</app:krs_regspr_name><app:geom><!--Inlined geometry 'krs_1_APP_GEOM'--><gml:Point><gml:pos>1 2</gml:pos>
</gml:Point></app:geom></app:krs></wfs:member></wfs:FeatureCollection>"""

    def abrufen(url, params, cfg, prot):
        if params["REQUEST"] == "GetCapabilities":
            return cap
        if params["REQUEST"] == "DescribeFeatureType":
            raise RuntimeError("kein Schema im Test")
        return seite

    monkeypatch.setattr(quellen, "abrufen", abrufen)
    cfg = {"url": "https://dienst.example/ows", "typename": "app:krs", "id_feld": "krss",
           "geometrie_feld": "geom", "bbox": [0, 0, 1, 1], "kachel_m": 10}
    ((o,),) = [list(quellen.wfs(cfg, Protokoll()))]
    assert o["objekt_id"] == "12051" and o["geom"][1].startswith("<gml:Point")
    assert o["werte"] == {"krs_regspr_name": None}


def test_schema_felder_nur_der_angefragten_objektart():
    """Liefert DescribeFeatureType mehrere Objektarten, zählen nur die Felder der angefragten (eingebetteter
    oder benannter Typ); ohne Objektart alle Felder."""
    xsd = b"""<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:gml="http://www.opengis.net/gml/3.2">
<xs:element name="krs" substitutionGroup="gml:AbstractFeature"><xs:complexType><xs:sequence>
<xs:element name="krss" type="string"/><xs:element name="geom" type="x"/></xs:sequence></xs:complexType>
</xs:element>
<xs:element name="gem" substitutionGroup="gml:AbstractFeature"><xs:complexType><xs:sequence>
<xs:element name="ags" type="string"/></xs:sequence></xs:complexType></xs:element>
<xs:element name="Gebaeude" substitutionGroup="gml:AbstractFeature" type="ave:GebaeudeType"/>
<xs:complexType name="GebaeudeType"><xs:sequence><xs:element name="oid" type="string"/>
</xs:sequence></xs:complexType></xs:schema>"""
    root = etree.fromstring(xsd)
    assert quellen.schema_felder(root, "app:krs") == ["geom", "krss"]
    assert quellen.schema_felder(root, "ave:Gebaeude") == ["oid"]
    assert quellen.schema_felder(root) == ["ags", "geom", "krss", "oid"]


def test_kacheln_decken_bbox_ab():
    """Zahl der Kacheln für das Suchrechteck (3 × 2), und die letzte endet am Rand des Rechtecks statt darüber
    hinauszuragen. Geprüft werden nur diese beiden Angaben, nicht jede Kachel einzeln."""
    kacheln = list(quellen._kacheln([0, 0, 1000, 500], 400))
    assert len(kacheln) == 6
    assert kacheln[-1] == [800, 400, 1000, 500]


def test_csv_gebietsschluessel_mit_fuehrender_null(tmp_path):
    """Der Gebietsschlüssel bekommt führende Nullen bis schluessel_laenge; eine Zeile ohne Schlüssel wird
    übersprungen und gemeldet."""
    datei = tmp_path / "t.csv"
    datei.write_text("kreis;wert\n12051;1\n;2\n", encoding="utf-8")
    cfg = {"pfad": str(datei), "trenner": ";", "id_spalte": "kreis",
           "gebiet": {"schluessel_spalte": "kreis", "schluessel_laenge": 8}}
    prot = Protokoll()
    zeilen = list(quellen.csv_quelle(cfg, prot))
    assert [z["geom"] for z in zeilen] == [("gebiet", "00012051")]
    assert "ohne Gebietsschlüssel" in prot.warnungen[0]


def test_csv_meldet_fehlende_spalte(tmp_path):
    """Fehlt die konfigurierte x-Spalte (hier lon), steht sie unter fehlende_felder. Weil keine Zeile eine
    Geometrie ergibt, kommt hier kein Datensatz; der Adapter selbst liest nach felder_pruefen weiter,
    angehalten wird die Quelle erst in laden (E4)."""
    datei = tmp_path / "t.csv"
    datei.write_text("id,lat\na,52\n", encoding="utf-8")
    cfg = {"pfad": str(datei), "id_spalte": "id", "x_spalte": "lon", "y_spalte": "lat", "srid": 4326}
    prot = Protokoll()
    assert list(quellen.csv_quelle(cfg, prot)) == []
    assert prot.info["fehlende_felder"] == ["lon"]


# Statistiktabelle als CSV im Aufbau der Tabelle 12411-01-01-5-B der Regionaldatenbank: Latin-1, Kopf ohne
# Spaltenzeile, Stichtag im Kopf, Fußnoten- und Lizenzblock, aufgelöste Gemeinde mit „-“, eine Zeile aus einem
# anderen Land. Die Zahlen sind erfunden (Antwort 69; E38). Seit E48 lädt keine mitgelieferte Konfiguration
# mehr aus der Regionaldatenbank (robots.txt: Disallow: /); die Tests sichern den CSV-Typ für
# Statistiktabellen.
AUSZUG_12411 = Path(__file__).parent / "daten" / "statistiktabelle-csv-auszug.csv"


def _statistik_cfg(**extra):
    """Konfiguration für den Auszug im Aufbau einer Statistiktabelle (E19): Datenzeilen per Muster,
    Spaltennamen nach Position, Stichtag aus Zeile 7, Prüfung der Kopfzeile 8; Schlüsselwörter ergänzen
    oder ersetzen Einträge."""
    return {"typ": "csv", "pfad": str(AUSZUG_12411), "encoding": "latin-1", "trenner": ";",
            "zeilen_muster": r"^12\d{6};", "spalten_namen": ["ags", "name", "insgesamt", "m", "w"],
            "id_spalte": "ags", "spalten": {"ags": "ags", "name": "name", "insgesamt": "bevoelkerung"},
            "zahl_felder": ["bevoelkerung"], "zeitbezug": {"zeile": 7, "spalte": 3},
            "leere_auslassen": True,
            "kopf_pruefen": {"zeile": 8, "erwartet": ["", "", "Insgesamt", "männlich", "weiblich"]},
            "gebiet": {"schluessel_spalte": "ags", "geometrie_quelle": "gemeinden_lgb",
                       "schluessel_feld": "ags"}, **extra}


def test_statistiktabelle_mit_kopf_fussblock_und_stichtag():
    """Aus der Statistiktabelle kommen nur die Brandenburger Gemeinden mit Stichtag als Zeit-Referenz der
    Messwerte; eine Zeile ohne jeden Wert kommt als `leer` mit Schlüssel, damit ihr bisheriger Wert stehen
    bleibt."""
    prot = Protokoll()
    ds = {d["objekt_id"]: d for d in quellen.csv_quelle(_statistik_cfg(), prot)}
    # nur Brandenburg; die aufgelöste Gemeinde (nur „-“) kommt mit Schlüssel und Merkmal `leer`, damit
    # das Zielschreiben sie auslässt, statt ihren bisherigen Wert zu löschen (Codex-Prüfung 05.11., B2)
    assert set(ds) == {"12051000", "12060005", "12060012", "12060096"}
    assert [k for k, d in ds.items() if d["leer"]] == ["12060096"]
    assert ds["12060096"]["geom"] == ("gebiet", "12060096")
    assert ds["12060096"]["zeit"] == {"bevoelkerung": "2025-12-31"}   # Schlüsselteil Zeitbezug bleibt
    # Zellen der ausgelassenen Zeile zählen nicht als „als null abgelegt“
    assert not any("als null abgelegt" in h for h in prot.hinweise)
    brb = ds["12051000"]
    assert brb["werte"] == {"ags": "12051000", "name": "Brandenburg an der Havel, kreisfreie Stadt",
                            "bevoelkerung": 50000.0}
    assert brb["zeit"] == {"bevoelkerung": "2025-12-31"}  # nur Messwerte, nicht Name oder Schlüssel
    assert brb["geom"] == ("gebiet", "12051000")
    assert prot.info["zeitbezug"] == "2025-12-31"
    assert not prot.info.get("fehlende_felder") and not prot.unvollstaendig


def test_statistiktabelle_fehlwerte_werden_null_ohne_auslassen():
    """Ohne leere_auslassen werden statistische Zeichen zu null, und der Hinweis zählt nur Zellen zugeordneter
    Spalten."""
    prot = Protokoll()
    ds = {d["objekt_id"]: d for d in quellen.csv_quelle(_statistik_cfg(leere_auslassen=False), prot)}
    assert ds["12060096"]["werte"]["bevoelkerung"] is None and not ds["12060096"]["leer"]
    assert "1 Zellen ohne Wert" in " ".join(prot.hinweise)   # nur die zugeordnete Spalte zählt


def test_leere_zeile_ohne_schluessel_macht_den_abruf_unvollstaendig(tmp_path):
    """Codex-Prüfung 05.11., B2: Ist bei einer Zeile ohne jeden Wert auch der Schlüssel nicht lesbar,
    lässt sich nicht sagen, welcher bisherige Wert stehen bleiben muss: Abruf unvollständig, also
    löscht der Abgleich nichts."""
    datei = tmp_path / "werte.csv"
    datei.write_text("ags;wert\n12051000;5\n;-\n12060005;-\n", encoding="utf-8")
    prot = Protokoll()
    cfg = {"typ": "csv", "pfad": str(datei), "trenner": ";", "id_spalte": "ags", "spalten": {"wert": "wert"},
           "zahl_felder": ["wert"], "leere_auslassen": True, "gebiet": {"schluessel_spalte": "ags"}}
    ds = list(quellen.csv_quelle(cfg, prot))
    assert [(d["objekt_id"], d["leer"]) for d in ds] == [("12051000", False), ("12060005", True)]
    assert prot.unvollstaendig and any("ohne Gebietsschlüssel" in w for w in prot.warnungen)


def test_statistiktabelle_ohne_stichtag_im_kopf_bricht_ab():
    """Steht an der angegebenen Stelle im Kopf kein Stichtag, bricht die Quelle mit QuellenFehler ab."""
    with pytest.raises(quellen.QuellenFehler):
        list(quellen.csv_quelle(_statistik_cfg(zeitbezug={"zeile": 1, "spalte": 9}), Protokoll()))


def test_statistiktabelle_umgestellter_kopf_haelt_an(tmp_path):
    """Schiebt der Anbieter eine Spalte ein, landen die Werte nicht still im falschen Feld."""
    text = AUSZUG_12411.read_text(encoding="latin-1").replace(";;Insgesamt;männlich;weiblich",
                                                              ";;männlich;Insgesamt;weiblich")
    datei = tmp_path / "umgestellt.csv"
    datei.write_text(text, encoding="latin-1")
    prot = Protokoll()
    assert list(quellen.csv_quelle(_statistik_cfg(pfad=str(datei)), prot)) == []
    assert prot.info.get("fehlende_felder")
    assert any("Kopfzeile 8 weicht ab" in w for w in prot.warnungen)


def test_csv_vorfilter_beschaedigte_datenzeile_sperrt_loeschen(tmp_path):
    """Prüfbericht 05.11. abends, Befund 1 (E47): zeilen_muster wählte das Gebiet und war zugleich der einzige
    Filter für Kopf und Fuß. Eine Datenzeile mit fehlendem oder beschädigtem Schlüssel verschwand so vor jeder
    Prüfung, nur `uebergangene_zeilen` stieg, und der Abgleich durfte löschen. Jetzt ist alles nach dem Kopf
    mit der Spaltenzahl der Datenzeilen Datenbereich: Ein Schlüssel ohne gültige Form macht den Abruf
    unvollständig; gültige Schlüssel anderer Gebiete und Ebenen (Flensburg, DG, Kreis) bleiben stumm."""
    zeilen = AUSZUG_12411.read_text(encoding="latin-1").splitlines()
    zeilen[10:10] = [";Ort ohne Schlüssel;1;1;1", "12O60005;Ort mit Buchstabe O;1;1;1",
                     "DG;Deutschland;9;9;9", "12060;Barnim, Landkreis;5;2;3", "12060099;Ort;7;3"]
    datei = tmp_path / "beschaedigt.csv"
    datei.write_text("\n".join(zeilen) + "\n", encoding="latin-1")
    prot = Protokoll()
    ds = {d["objekt_id"] for d in quellen.csv_quelle(
        _statistik_cfg(pfad=str(datei), schluessel_form=r"^(DG|\d+)$"), prot)}
    assert ds == {"12051000", "12060005", "12060012", "12060096"}
    assert prot.unvollstaendig
    assert any(w.startswith("2 Datenzeilen ohne gültigen Gebietsschlüssel übergangen (Zeilen 11, 12)")
               for w in prot.warnungen), prot.warnungen
    assert any(w.startswith("1 Datenzeilen mit 4 statt 5 Spalten übergangen (Zeilen 15)")
               for w in prot.warnungen), prot.warnungen
    assert len(prot.warnungen) == 2

    # Ohne schluessel_form gelten nur Ziffern als Schlüssel: DG fällt dann ebenfalls auf (sichere Richtung)
    prot = Protokoll()
    list(quellen.csv_quelle(_statistik_cfg(pfad=str(datei)), prot))
    assert any(w.startswith("3 Datenzeilen ohne gültigen Gebietsschlüssel übergangen (Zeilen 11, 12, 13)")
               for w in prot.warnungen), prot.warnungen


@pytest.mark.parametrize("ziel", ["12060005", "12060096"])   # mitten im Gebiet, letzte Datenzeile der Datei
@pytest.mark.parametrize("schaden", [" {}", "{} ", '"{}"', "\t{}"])
def test_csv_vorfilter_schluessel_mit_rand_oder_anfuehrungszeichen_sperrt_loeschen(tmp_path, ziel, schaden):
    """Nachprüfung zu E47 (Befunde 2 und 4): Das Gebiet wählt `zeilen_muster` an der Rohzeile, gültig war ein
    Schlüssel nach strip(). Leerzeichen am Rand, Anführungszeichen oder ein Tab vor dem Schlüssel ließen eine
    Brandenburger Gemeinde aus dem Gebiet fallen, ohne Meldung; der Abruf galt als vollständig. Jetzt gilt der
    rohe Schlüssel, und eine Zeile, die erst bereinigt ins Gebiet fiele, wird gemeldet, auch als letzte
    Datenzeile vor dem Fuß."""
    zeilen = AUSZUG_12411.read_text(encoding="latin-1").splitlines()
    nr = next(i for i, z in enumerate(zeilen) if z.startswith(ziel + ";"))
    zeilen[nr] = schaden.format(ziel) + zeilen[nr][len(ziel):]
    datei = tmp_path / "rand.csv"
    datei.write_text("\n".join(zeilen) + "\n", encoding="latin-1")
    prot = Protokoll()
    ds = {d["objekt_id"] for d in quellen.csv_quelle(
        _statistik_cfg(pfad=str(datei), schluessel_form=r"^(DG|\d+)$"), prot)}
    assert ziel not in ds and prot.unvollstaendig, (ds, prot.warnungen)
    assert any(f"(Zeilen {nr + 1})" in w and "nichts wird gelöscht" in w
               for w in prot.warnungen), prot.warnungen


def test_csv_vorfilter_spaltenzahl_gegen_die_kopfzeile(tmp_path):
    """Nachprüfung zu E47: Maßstab für die Spaltenzahl war die Mehrheit der gewählten Zeilen. Fehlte allen
    dieselbe Spalte, kamen sie ohne Warnung durch (DictReader füllt mit None). Jetzt wird es gemeldet, wenn
    die Mehrheit von der Kopfzeile (kopf_pruefen.zeile) abweicht."""
    zeilen = AUSZUG_12411.read_text(encoding="latin-1").splitlines()
    zeilen = [z.rsplit(";", 1)[0] if z.startswith("12") else z for z in zeilen]   # weiblich fehlt überall
    datei = tmp_path / "schmal.csv"
    datei.write_text("\n".join(zeilen) + "\n", encoding="latin-1")
    prot = Protokoll()
    list(quellen.csv_quelle(_statistik_cfg(pfad=str(datei), schluessel_form=r"^(DG|\d+)$"), prot))
    assert prot.unvollstaendig
    assert any("4 Spalten" in w and "Kopfzeile 8" in w and "5" in w for w in prot.warnungen), prot.warnungen
    # Der unveränderte Auszug bleibt ohne Meldung
    prot = Protokoll()
    assert len(list(quellen.csv_quelle(_statistik_cfg(schluessel_form=r"^(DG|\d+)$"), prot))) == 4
    assert not prot.unvollstaendig and not prot.warnungen


def test_csv_zeilen_muster_braucht_das_ende_des_kopfs(tmp_path):
    """Wo der Datenbereich beginnt, sagt kopf_pruefen oder zeitbezug aus dem Kopf; Kopfzeilen haben oft
    dieselbe Spaltenzahl wie Datenzeilen (;;Insgesamt;männlich;weiblich). Ohne beides lehnt der Adapter ab
    (E47)."""
    cfg = _statistik_cfg(zeitbezug="2025-12-31")
    del cfg["kopf_pruefen"]
    with pytest.raises(QuellenFehler, match="zeilen_muster braucht kopf_pruefen oder zeitbezug"):
        list(quellen.csv_quelle(cfg, Protokoll()))


def test_statistiktabelle_verrutschter_stichtag_bricht_ab():
    """Steht an der Stelle des Stichtags etwas anderes als ein Datum oder Jahr (verrutschter Kopf), bricht die
    Quelle ab, statt den Text als Zeit-Referenz zu übernehmen."""
    with pytest.raises(quellen.QuellenFehler, match="kein Datum"):
        list(quellen.csv_quelle(_statistik_cfg(zeitbezug={"zeile": 8, "spalte": 3}), Protokoll()))


def test_wfs_kachel_an_der_grenze_ohne_gesamtzahl_ist_unvollstaendig(monkeypatch):
    """Nennt der Dienst keine Gesamtzahl und liefert eine Kachel genau die Höchstzahl, lässt sich
    nicht zeigen, dass nichts fehlt: der Abruf gilt als unvollständig (Codex-Prüfung 04.11., F3)."""
    cap = b"""<wfs:WFS_Capabilities xmlns:wfs="http://www.opengis.net/wfs/2.0"
 xmlns:ows="http://www.opengis.net/ows/1.1"/>"""

    def abrufen(url, params, cfg, prot):
        if params["REQUEST"] == "GetCapabilities":
            return cap
        if params["REQUEST"] == "DescribeFeatureType":
            raise RuntimeError("kein Schema im Test")
        return _gml_seite(["a", "b"])

    monkeypatch.setattr(quellen, "abrufen", abrufen)
    cfg = {"url": "https://dienst.example/ows", "typename": "x:o", "id_feld": "oid",
           "geometrie_feld": "geom", "bbox": [0, 0, 1, 1], "kachel_m": 10_000_000, "max_je_kachel": 2}
    prot = Protokoll()
    list(quellen.wfs(cfg, prot))
    assert prot.unvollstaendig and any("keine Gesamtzahl" in w for w in prot.warnungen)
    # Bis E46 galt die Kachel mit 2 von angefragten 3 Objekten als vollständig; der Dienst kann aber selbst
    # niedriger begrenzen (Prüfbericht 05.11. abends, Befund 2, E47). Dieser Dienst übergeht STARTINDEX, die
    # Folgeseite bringt nichts Neues: kein Beleg, also unvollständig
    prot = Protokoll()
    list(quellen.wfs(dict(cfg, max_je_kachel=3), prot))
    assert prot.unvollstaendig and any("Vollständigkeit nicht belegt" in w for w in prot.warnungen)


def _kachel_dienst(objekte: list[str], limit: int, anfragen: list, cap: bytes = b"",
                   startindex: str = "beachten"):
    """WFS 2.0 ohne Paging und ohne numberMatched, der höchstens `limit` Objekte je Antwort liefert.
    startindex: beachten | uebergehen | fehler (ExceptionReport, so kann ein Dienst ohne Paging antworten)."""
    cap = cap or b"""<wfs:WFS_Capabilities xmlns:wfs="http://www.opengis.net/wfs/2.0"
 xmlns:ows="http://www.opengis.net/ows/1.1"/>"""

    def abrufen(url, params, cfg, prot):
        if params["REQUEST"] == "GetCapabilities":
            return cap
        if params["REQUEST"] == "DescribeFeatureType":
            raise RuntimeError("kein Schema im Test")
        start = params.get("STARTINDEX")
        anfragen.append(start)
        if start is not None and startindex == "fehler":
            return b"""<ows:ExceptionReport xmlns:ows="http://www.opengis.net/ows/1.1"><ows:Exception>
<ows:ExceptionText>STARTINDEX not supported</ows:ExceptionText></ows:Exception></ows:ExceptionReport>"""
        s = start if start is not None and startindex == "beachten" else 0
        return _gml_seite(objekte[s:s + min(limit, params["COUNT"])])
    return abrufen


_KACHEL = {"url": "https://dienst.example/ows", "typename": "x:o", "id_feld": "oid", "geometrie_feld": "geom",
           "bbox": [0, 0, 1, 1], "kachel_m": 10_000_000, "max_je_kachel": 3}


def test_wfs_kachel_unter_dem_limit_ohne_gesamtzahl_braucht_einen_beleg(monkeypatch):
    """Prüfbericht 05.11. abends, Befund 2 (E47): Ohne numberMatched bewies eine Kachel unter dem angefragten
    Limit das Ende nicht, ein Dienst kann selbst niedriger begrenzen. Wie beim Paging (F5, E46) fragt die
    Pipeline in der Kachel am nächsten STARTINDEX weiter; erst eine leere Seite belegt das Ende."""
    # Dienst begrenzt still auf 2, angefragt sind 3: die Folgeseiten holen den Rest
    anfragen = []
    monkeypatch.setattr(quellen, "abrufen", _kachel_dienst(["a", "b", "c", "d", "e"], 2, anfragen))
    prot = Protokoll()
    assert [o["objekt_id"] for o in quellen.wfs(_KACHEL, prot)] == ["a", "b", "c", "d", "e"]
    assert anfragen == [None, 2, 4, 5] and not prot.unvollstaendig

    # Weniger Objekte als das Limit, leere Folgeseite: vollständig
    anfragen = []
    monkeypatch.setattr(quellen, "abrufen", _kachel_dienst(["a", "b"], 3, anfragen))
    prot = Protokoll()
    assert [o["objekt_id"] for o in quellen.wfs(_KACHEL, prot)] == ["a", "b"]
    assert anfragen == [None, 2] and not prot.unvollstaendig

    # Folgeseite ohne neues Objekt (Dienst übergeht STARTINDEX) oder mit Fehlerbericht: unvollständig, die
    # Quelle bricht nicht ab
    for verhalten in ("uebergehen", "fehler"):
        anfragen = []
        monkeypatch.setattr(quellen, "abrufen", _kachel_dienst(["a", "b"], 3, anfragen, startindex=verhalten))
        prot = Protokoll()
        assert [o["objekt_id"] for o in quellen.wfs(_KACHEL, prot)] == ["a", "b"]
        assert anfragen == [None, 2] and prot.unvollstaendig, verhalten
        assert any("Vollständigkeit nicht belegt" in w for w in prot.warnungen), prot.warnungen


def test_wfs_kachel_mit_count_default_braucht_keine_folgeseite(monkeypatch):
    """Nennt der Dienst seine Höchstzahl (CountDefault), belegt eine Kachel unter min(max_je_kachel,
    CountDefault) das Ende; erreicht sie diese Zahl, wird weitergefragt (E47)."""
    cap = b"""<wfs:WFS_Capabilities xmlns:wfs="http://www.opengis.net/wfs/2.0"
 xmlns:ows="http://www.opengis.net/ows/1.1"><ows:OperationsMetadata><ows:Constraint name="CountDefault">
<ows:NoValues/><ows:DefaultValue>2</ows:DefaultValue></ows:Constraint></ows:OperationsMetadata>
</wfs:WFS_Capabilities>"""
    anfragen = []
    monkeypatch.setattr(quellen, "abrufen", _kachel_dienst(["a"], 2, anfragen, cap))
    prot = Protokoll()
    assert [o["objekt_id"] for o in quellen.wfs(_KACHEL, prot)] == ["a"]
    assert anfragen == [None] and not prot.unvollstaendig
    # Zwei Objekte = CountDefault: nicht belegt, also Folgeseite
    anfragen = []
    monkeypatch.setattr(quellen, "abrufen", _kachel_dienst(["a", "b", "c"], 2, anfragen, cap))
    prot = Protokoll()
    assert [o["objekt_id"] for o in quellen.wfs(_KACHEL, prot)] == ["a", "b", "c"]
    assert anfragen == [None, 2, 3] and not prot.unvollstaendig


_CAP_SORTIERT = b"""<wfs:WFS_Capabilities xmlns:wfs="http://www.opengis.net/wfs/2.0"
 xmlns:ows="http://www.opengis.net/ows/1.1"><ows:OperationsMetadata>
<ows:Constraint name="ImplementsSorting"><ows:NoValues/><ows:DefaultValue>TRUE</ows:DefaultValue>
</ows:Constraint>
</ows:OperationsMetadata></wfs:WFS_Capabilities>"""


def test_wfs_kachel_folgeseiten_sortiert_und_ohne_doppelte(monkeypatch):
    """Nachprüfung zu E47 (Befund 9): Folgeseiten einer Kachel liefen ohne SORTBY. Ohne feste Reihenfolge
    kann ein Objekt zwischen zwei Seiten rutschen; die leere Seite am Ende beweist dann nichts. Jetzt: SORTBY
    in jeder Abfrage der Kachel, wenn der Dienst Sortierung meldet; ohne Sortierung gilt die Kachel nur als
    vollständig, wenn die Seiten bis zur leeren Seite so viele verschiedene Objekte brachten, wie sie
    zählten."""
    abfragen = []
    dienst = _kachel_dienst(["a", "b", "c", "d", "e"], 2, [], _CAP_SORTIERT)

    def abrufen(url, params, cfg, prot):
        if params["REQUEST"] == "GetFeature":
            abfragen.append(params)
        return dienst(url, params, cfg, prot)

    monkeypatch.setattr(quellen, "abrufen", abrufen)
    prot = Protokoll()
    assert [o["objekt_id"] for o in quellen.wfs(_KACHEL, prot)] == ["a", "b", "c", "d", "e"]
    assert [a.get("SORTBY") for a in abfragen] == ["oid ASC"] * 4 and not prot.unvollstaendig

    # Ohne Sortierung: die zweite Seite wiederholt b, c rutscht durch; leere Seite am Ende
    seiten = {None: ["a", "b"], 2: ["b", "d"], 4: ["e"], 5: []}

    def unsortiert(url, params, cfg, prot):
        if params["REQUEST"] == "GetCapabilities":
            return b'<wfs:WFS_Capabilities xmlns:wfs="http://www.opengis.net/wfs/2.0"/>'
        if params["REQUEST"] == "DescribeFeatureType":
            raise RuntimeError("kein Schema im Test")
        assert "SORTBY" not in params
        return _gml_seite(seiten[params.get("STARTINDEX")])

    monkeypatch.setattr(quellen, "abrufen", unsortiert)
    prot = Protokoll()
    assert [o["objekt_id"] for o in quellen.wfs(_KACHEL, prot)] == ["a", "b", "d", "e"]
    assert prot.unvollstaendig
    assert any("4 verschiedene Objekte bei 5 gezählten" in w for w in prot.warnungen), prot.warnungen


def test_wfs_kachel_dienst_ohne_startindex_nennt_keine_falsche_abhilfe(monkeypatch):
    """Nachprüfung zu E47 (Befund 9): Übergeht ein Dienst ohne Paging STARTINDEX, hilft kleineres kachel_m
    nicht; die Meldung nennt jetzt, womit sich Vollständigkeit belegen lässt."""
    monkeypatch.setattr(quellen, "abrufen", _kachel_dienst(["a", "b"], 3, [], startindex="uebergehen"))
    prot = Protokoll()
    list(quellen.wfs(_KACHEL, prot))
    text = " ".join(prot.warnungen)
    assert prot.unvollstaendig and "kachel_m verkleinern" not in text
    assert "numberMatched" in text and "CountDefault" in text, text


def test_wfs_kachel_mit_gesamtzahl_wie_bisher(monkeypatch):
    """Mit numberMatched entscheidet die Gesamtzahl, keine Folgeseite (so antworten die Dienste der LGB)."""
    anfragen = []

    def abrufen(url, params, cfg, prot):
        if params["REQUEST"] == "GetCapabilities":
            return b'<wfs:WFS_Capabilities xmlns:wfs="http://www.opengis.net/wfs/2.0"/>'
        if params["REQUEST"] == "DescribeFeatureType":
            raise RuntimeError("kein Schema im Test")
        anfragen.append(params.get("STARTINDEX"))
        return _gml_seite(["a", "b"]).replace(b"numberReturned", b'numberMatched="2" numberReturned')

    monkeypatch.setattr(quellen, "abrufen", abrufen)
    prot = Protokoll()
    assert [o["objekt_id"] for o in quellen.wfs(_KACHEL, prot)] == ["a", "b"]
    assert anfragen == [None] and not prot.unvollstaendig


def test_unlesbare_zahlen_und_kurze_zeilen_landen_im_bericht():
    """Unlesbare Zahlen werden null und am Ende mit Anzahl und Beispielen gewarnt; zu kurze Zeilen machen den
    Abruf unvollständig."""
    prot = Protokoll()
    assert quellen._zahl("12,5", prot) == 12.5 and quellen._zahl("", prot) is None
    assert quellen._zahl("k.A.", prot) is None and quellen._zahl("k.A.", prot) is None
    prot.info["zeilen_zu_kurz"] = 3
    quellen.zahlen_bilanz(prot)
    assert "2 Werte sind keine Zahl" in prot.warnungen[0] and "'k.A.'" in prot.warnungen[0]
    assert prot.unvollstaendig and "3 Zeilen mit zu wenigen Spalten" in prot.warnungen[1]


def test_unzip_fehler_bricht_die_quelle_ab(tmp_path, monkeypatch):
    """Deflate64 liest nur unzip. Endet unzip mit Fehler, ist das Archiv kaputt, auch wenn bis dahin
    Zeilen kamen; die Quelle darf nicht wie nach einem vollständigen Lesen weiterlaufen."""
    import zipfile
    pfad = tmp_path / "daten.zip"
    with zipfile.ZipFile(pfad, "w", zipfile.ZIP_STORED) as z:
        z.writestr("daten.csv", "a;b\n1;2\n")
    roh = bytearray(pfad.read_bytes())
    # Kompressionsverfahren auf 9 (Deflate64) setzen: lokaler Kopf Byte 8, Zentralverzeichnis Byte 10
    roh[8] = 9
    zentral = roh.find(b"PK\x01\x02")
    roh[zentral + 10] = 9
    pfad.write_bytes(bytes(roh))
    falsch = tmp_path / "unzip"
    falsch.write_text("#!/bin/sh\nprintf 'a;b\\n'\necho 'invalid compressed data' >&2\nexit 2\n")
    falsch.chmod(0o755)
    monkeypatch.setattr(quellen.shutil, "which", lambda name: str(falsch))
    gelesen = []
    with pytest.raises(QuellenFehler, match="Rückgabewert 2: invalid compressed data"):
        for zeile in quellen.zip_zeilen(pfad, None, {}, Protokoll()):
            gelesen.append(zeile)
    assert gelesen == ["a;b\n"]


def test_wfs_1_1_0_mit_featuremember_und_eigenen_parametern(monkeypatch):
    """WFS 1.1.0 (Antwort 67): TYPENAME und MAXFEATURES statt TYPENAMES und COUNT, Objekte in
    gml:featureMember bzw. gml:featureMembers, kein Paging (immer Kachelung)."""
    cap = b"""<wfs:WFS_Capabilities xmlns:wfs="http://www.opengis.net/wfs" version="1.1.0"/>"""
    seite = b"""<wfs:FeatureCollection xmlns:wfs="http://www.opengis.net/wfs"
 xmlns:gml="http://www.opengis.net/gml" xmlns:x="urn:x" numberOfFeatures="3">
<gml:featureMember><!-- k --><x:o><x:oid>a</x:oid>
<x:geom><gml:Point><gml:pos>1 2</gml:pos></gml:Point></x:geom></x:o></gml:featureMember>
<gml:featureMembers><x:o><x:oid>b</x:oid><x:geom><gml:Point><gml:pos>3 4</gml:pos></gml:Point></x:geom></x:o>
<x:o><x:oid>c</x:oid><x:geom><gml:Point><gml:pos>5 6</gml:pos></gml:Point></x:geom></x:o></gml:featureMembers>
</wfs:FeatureCollection>"""
    anfragen = []
    treffer = [b'<wfs:FeatureCollection xmlns:wfs="http://www.opengis.net/wfs" numberOfFeatures="3"/>']

    def abrufen(url, params, cfg, prot):
        if params["REQUEST"] == "GetCapabilities":
            return cap
        if params["REQUEST"] == "DescribeFeatureType":
            assert "TYPENAME" in params and "TYPENAMES" not in params
            raise RuntimeError("kein Schema im Test")
        anfragen.append(params)
        if params.get("RESULTTYPE") == "hits":
            if isinstance(treffer[0], Exception):
                raise treffer[0]
            return treffer[0]
        return seite

    monkeypatch.setattr(quellen, "abrufen", abrufen)
    cfg = {"url": "https://dienst.example/ows", "version": "1.1.0", "typename": "x:o", "id_feld": "oid",
           "geometrie_feld": "geom", "bbox": [0, 0, 1, 1], "kachel_m": 10_000_000}
    prot = Protokoll()
    objekte = list(quellen.wfs(cfg, prot))
    assert [o["objekt_id"] for o in objekte] == ["a", "b", "c"]
    assert objekte[0]["geom"][1].startswith("<gml:Point") and 'opengis.net/gml"' in objekte[0]["geom"][1]
    # WFS 1.1.0 kennt weder STARTINDEX noch CountDefault: Die Vollständigkeit der Kachel belegt eine Abfrage
    # mit RESULTTYPE=hits (Zahl der Treffer, ohne Objekte; E47)
    p, h = anfragen
    assert p["VERSION"] == "1.1.0" and p["TYPENAME"] == "x:o" and "MAXFEATURES" in p
    assert "COUNT" not in p and "STARTINDEX" not in p and "TYPENAMES" not in p and "RESULTTYPE" not in p
    assert h["RESULTTYPE"] == "hits" and h["BBOX"] == p["BBOX"] and "MAXFEATURES" not in h
    assert not prot.unvollstaendig
    # Mehr Treffer als geliefert, oder keine lesbare Trefferzahl: unvollständig
    leer = b'<wfs:FeatureCollection xmlns:wfs="http://www.opengis.net/wfs"/>'
    fuenf = leer.replace(b"/>", b' numberOfFeatures="5"/>')
    for antwort, text in ((fuenf, "3 von 5"), (leer, "nicht belegt"),
                          (RuntimeError("hits nicht unterstützt"), "nicht belegt")):
        treffer[0] = antwort
        prot = Protokoll()
        assert len(list(quellen.wfs(cfg, prot))) == 3
        assert prot.unvollstaendig and any(text in w for w in prot.warnungen), prot.warnungen


def test_wfs_pause_zwischen_abrufen(monkeypatch):
    """pause_s: zwischen zwei Abrufen desselben Dienstes wird gewartet (Antwort 69), vor dem ersten nicht.
    Mit CountDefault, damit keine Folgeseite je Kachel dazukommt (E47)."""
    cap = b"""<wfs:WFS_Capabilities xmlns:wfs="http://www.opengis.net/wfs/2.0"
 xmlns:ows="http://www.opengis.net/ows/1.1"><ows:OperationsMetadata><ows:Constraint name="CountDefault">
<ows:NoValues/><ows:DefaultValue>1000</ows:DefaultValue></ows:Constraint></ows:OperationsMetadata>
</wfs:WFS_Capabilities>"""
    pausen = []

    def abrufen(url, params, cfg, prot):
        if params["REQUEST"] == "GetCapabilities":
            return cap
        if params["REQUEST"] == "DescribeFeatureType":
            raise RuntimeError("kein Schema im Test")
        return _gml_seite(["a"])

    monkeypatch.setattr(quellen, "abrufen", abrufen)
    monkeypatch.setattr(quellen.time, "sleep", pausen.append)
    cfg = {"url": "https://dienst.example/ows", "typename": "x:o", "id_feld": "oid", "geometrie_feld": "geom",
           "bbox": [0, 0, 2000, 1000], "kachel_m": 1000, "pause_s": 1.5}
    list(quellen.wfs(cfg, Protokoll()))
    assert pausen == [1.5] * 3   # Capabilities, Schema, Kachel 1, Kachel 2: drei Pausen dazwischen


def test_wfs_ohne_schema_prueft_felder_an_den_objekten(monkeypatch):
    """Codex B4: Liefert der Dienst kein Schema, prüft die Pipeline die konfigurierten Felder an den
    gelieferten Objekten; fehlt eines überall, gilt es als fehlend (die Quelle wird angehalten)."""
    cap = b"""<wfs:WFS_Capabilities xmlns:wfs="http://www.opengis.net/wfs/2.0"/>"""

    def abrufen(url, params, cfg, prot):
        if params["REQUEST"] == "GetCapabilities":
            return cap
        if params["REQUEST"] == "DescribeFeatureType":
            raise RuntimeError("Dienst liefert kein Schema")
        return _gml_seite(["a", "b"])

    monkeypatch.setattr(quellen, "abrufen", abrufen)
    cfg = {"url": "https://dienst.example/ows", "typename": "x:o", "id_feld": "oid", "geometrie_feld": "geom",
           "bbox": [0, 0, 1, 1], "kachel_m": 10_000_000, "felder": {"name": "name"}}
    prot = Protokoll()
    list(quellen.wfs(cfg, prot))
    assert prot.info["fehlende_felder"] == ["name"]
    prot = Protokoll()
    list(quellen.wfs(dict(cfg, felder=None), prot))
    assert "fehlende_felder" not in prot.info


def test_leere_auslassen_ohne_zahl_felder_wird_abgelehnt(tmp_path):
    """Prüfung 05.11., Runde 2 (E42): Ohne zahl_felder ist keine Zeile „leer“; der Schalter wäre wirkungslos
    und leere Zellen überschrieben Werte mit null. Die Quelle bricht mit klarer Meldung ab."""
    datei = tmp_path / "werte.csv"
    datei.write_text("ags;bev\n12054000;-\n", encoding="utf-8")
    cfg = {"typ": "csv", "pfad": str(datei), "trenner": ";", "id_spalte": "ags", "leere_auslassen": True,
           "gebiet": {"schluessel_spalte": "ags"}}
    with pytest.raises(quellen.QuellenFehler, match="leere_auslassen braucht zahl_felder"):
        list(quellen.csv_quelle(cfg, quellen.Protokoll()))


# --- E50: Codefehler aus E49 und Befunde W5, W6 des Prüfberichts vom 06.11.2026 ---------------------------

@pytest.mark.parametrize("pfad", ["/a/../scrivito/x.xlsx", "/a/%2e%2e/scrivito/x.xlsx", "/./scrivito/x.xlsx",
                                  "//scrivito/x.xlsx", "/a/..%2fscrivito/x.xlsx", "/a/..%5Cscrivito/x.xlsx",
                                  "/a/b/../../scrivito/", "/scrivito/."])
def test_robots_sperre_auf_dem_gesendeten_pfad(monkeypatch, pfad):
    """E50, Codefehler aus E49 (robots_gesperrt): Punktsegmente löst requests (urllib3) beim Senden auf, auch
    prozentkodiert (/a/%2e%2e/ wird /), und viele Server legen doppelte Schrägstriche zusammen oder lesen
    %2F und den Rückstrich als Trenner. Geprüft wird jetzt der Pfad, den requests tatsächlich sendet, nach
    Dekodierung, ohne Punktsegmente und mit einfachen Schrägstrichen. Bis E49 rutschten diese Schreibweisen
    durch den Vergleich. Kein Abruf (requests.get als Attrappe, die jeden Aufruf ablehnt)."""
    monkeypatch.setattr(quellen.requests, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError(a)))
    url = "https://www.statistik-berlin-brandenburg.de" + pfad
    assert quellen.robots_gesperrt(url) == "/scrivito/"
    with pytest.raises(QuellenFehler, match="robots.txt"):
        quellen.abrufen(url, None, {}, Protokoll())


def test_robots_gegenprobe_erlaubte_pfade():
    """E50, Gegenprobe: Pfade, die die Sperre nicht treffen, bleiben erlaubt (auch nach der
    Normalisierung)."""
    for url in ("https://www.statistik-berlin-brandenburg.de/a-i-4-a-v-2-j/",
                "https://www.statistik-berlin-brandenburg.de/a/scrivito/",
                "https://www.statistik-berlin-brandenburg.de/scrivito",
                "https://sgx.geodatenzentrum.de/wfs_vg250?SERVICE=WFS",
                "https://isk.geobasis-bb.de/ows/alkis_vereinf_wfs"):
        assert quellen.robots_gesperrt(url) is None, url


def test_capabilities_auch_mit_ows_1_0():
    """E50, Codefehler aus E49 (capabilities_lesen, _text): WFS 1.1.0 nutzt OWS 1.0
    (http://www.opengis.net/ows). Titel, Beschreibung, Anbieter und E-Mail werden jetzt auch dort gelesen; bis
    E49 kamen sie als None zurück."""
    cap = b"""<wfs:WFS_Capabilities xmlns:wfs="http://www.opengis.net/wfs" xmlns:ows="http://www.opengis.net/ows"
 version="1.1.0" updateSequence="7"><ows:ServiceIdentification><ows:Title>Gemeinden</ows:Title>
<ows:Abstract>Testdienst</ows:Abstract></ows:ServiceIdentification><ows:ServiceProvider>
<ows:ProviderName>Amt</ows:ProviderName><ows:ServiceContact><ows:ContactInfo><ows:Address>
<ows:ElectronicMailAddress>dienst@amt.example</ows:ElectronicMailAddress></ows:Address></ows:ContactInfo>
</ows:ServiceContact></ows:ServiceProvider></wfs:WFS_Capabilities>"""
    info = quellen.capabilities_lesen(etree.fromstring(cap))
    assert (info["titel"], info["beschreibung"], info["anbieter"], info["email"],
            info["update_sequence"]) == (
        "Gemeinden", "Testdienst", "Amt", "dienst@amt.example", "7")


@pytest.mark.parametrize("text", ["nan", "NaN", "inf", "-inf", "Infinity", "1E999", "1e999", "1_000",
                                  "0x10", "1,2,3", "١٢"])
def test_zahl_nimmt_keine_unendlichen_oder_python_schreibweisen(text):
    """E50, Codefehler aus E49 (_zahl): float() nimmt nan, inf, 1E999 (unendlich) und 1_000 an; das sind keine
    Messwerte einer Statistik. Sie werden jetzt wie jede andere Nichtzahl leer übernommen und gezählt. Am
    echten INKAR-Bestand (63 426 864 Zeilen, Ausgabe 2025) ändert das keinen Wert (Gegenprobe,
    docs/entscheidungen.md, E50)."""
    prot = Protokoll()
    assert quellen._zahl(text, prot) is None
    assert prot.info["zahlen_unlesbar"]["anzahl"] == 1


def test_zahl_gegenprobe_gueltige_schreibweisen():
    """E50, Gegenprobe: Dezimalkomma, Dezimalpunkt, Vorzeichen, Exponent und Leerzeichen am Rand bleiben
    Zahlen."""
    for text, wert in (("184290,00", 184290.0), ("-3,5", -3.5), ("+2", 2.0), ("1.5", 1.5), ("1e3", 1000.0),
                       (" 7 ", 7.0), (",5", 0.5)):
        assert quellen._zahl(text) == wert, text


def test_wfs_ablehnung_beim_schema_bricht_die_quelle_ab(monkeypatch):
    """E50, Codefehler aus E49: Eine Ablehnung (QuellenFehler: Weiterleitung, Größenlimit, robots.txt) beim
    DescribeFeatureType bricht die Quelle ab wie bei jeder anderen Abfrage. Bis E49 stufte die
    Fehlerbehandlung sie zur Warnung „Schema nicht lesbar“ herab. Andere Fehler des Schemas bleiben eine
    Warnung."""
    cap = b"""<wfs:WFS_Capabilities xmlns:wfs="http://www.opengis.net/wfs/2.0"/>"""

    def abrufen(url, params, cfg, prot):
        if params["REQUEST"] == "GetCapabilities":
            return cap
        if params["REQUEST"] == "DescribeFeatureType":
            raise QuellenFehler("Antwort größer als 200 MB")
        return _gml_seite(["a"])

    monkeypatch.setattr(quellen, "abrufen", abrufen)
    with pytest.raises(QuellenFehler, match="größer"):
        list(quellen.wfs(dict(_KACHEL, max_je_kachel=10), Protokoll()))


@pytest.mark.parametrize("kachel_m", [0, -500, float("nan"), float("inf"), "500", True])
def test_kachelgroesse_muss_positiv_sein(kachel_m):
    """E50, Codefehler aus E49 (_kacheln): kachel_m 0 oder negativ lief endlos (x wächst nie), NaN lieferte
    eine unsinnige Kachel. Jetzt QuellenFehler vor der ersten Kachel. islice begrenzt den Test am alten Stand,
    damit er scheitert statt zu hängen."""
    import itertools
    with pytest.raises(QuellenFehler, match="kachel_m"):
        list(itertools.islice(quellen._kacheln([0, 0, 1000, 1000], kachel_m), 1000))


def _kachelseite(objekte):
    """GetFeature-Antwort (WFS 2.0) mit je einem Objekt je (ID, Name, gml:id der Geometrie, x)."""
    teile = "".join(
        f'<wfs:member><x:o gml:id="o_{i}"><x:oid>{i}</x:oid><x:name>{n}</x:name><x:geom>'
        f'<gml:Point gml:id="{g}" srsName="urn:ogc:def:crs:EPSG::25833"><gml:pos>{x} 2</gml:pos></gml:Point>'
        f'</x:geom></x:o></wfs:member>' for i, n, g, x in objekte)
    return (f'<wfs:FeatureCollection xmlns:wfs="http://www.opengis.net/wfs/2.0" '
            f'xmlns:gml="http://www.opengis.net/gml/3.2" xmlns:x="urn:x" '
            f'numberReturned="{len(objekte)}">{teile}</wfs:FeatureCollection>').encode()


@pytest.mark.parametrize("zweite, unvollstaendig", [
    (("a", "Haus", "g_2", 1), False),        # nur gml:id anders: dasselbe Objekt
    (("a", "Haus Nord", "g_1", 1), True),    # anderer Name
    (("a", "Haus", "g_1", 5), True),         # andere Geometrie
], ids=["gleich", "name", "geometrie"])
def test_wfs_doppelte_id_vergleicht_den_inhalt(monkeypatch, zweite, unvollstaendig):
    """E50, Befund W5: Liefern zwei Kacheln dieselbe Objekt-ID, vergleicht der Adapter den Inhalt (Werte und
    Geometrie in kanonischer Form, ohne gml:id, die viele Dienste je Antwort neu vergeben). Gleich: einmal
    übernommen, ohne Warnung. Abweichend: Warnung, Abruf unvollständig (nichts wird gelöscht), und beide
    Fassungen gehen an das Zielschreiben, das den Schlüssel wie jeden widersprüchlichen auslässt (E42).
    Bis E49 galt ungeprüft „das erste zählt“."""
    cap = b"""<wfs:WFS_Capabilities xmlns:wfs="http://www.opengis.net/wfs/2.0"
 xmlns:ows="http://www.opengis.net/ows/1.1"><ows:OperationsMetadata><ows:Constraint name="CountDefault">
<ows:NoValues/><ows:DefaultValue>1000</ows:DefaultValue></ows:Constraint></ows:OperationsMetadata>
</wfs:WFS_Capabilities>"""

    def abrufen(url, params, cfg, prot):
        if params["REQUEST"] == "GetCapabilities":
            return cap
        if params["REQUEST"] == "DescribeFeatureType":
            raise RuntimeError("kein Schema im Test")
        links = params["BBOX"].startswith("0,")
        return _kachelseite([("a", "Haus", "g_1", 1), ("b", "Hof", "g_3", 2)] if links else [zweite])

    monkeypatch.setattr(quellen, "abrufen", abrufen)
    cfg = {"url": "https://dienst.example/ows", "typename": "x:o", "id_feld": "oid", "geometrie_feld": "geom",
           "bbox": [0, 0, 2000, 1000], "kachel_m": 1000, "felder": {"name": "name"}}
    prot = Protokoll()
    ids = [o["objekt_id"] for o in quellen.wfs(cfg, prot)]
    assert prot.unvollstaendig is unvollstaendig
    if unvollstaendig:
        assert ids == ["a", "b", "a"]
        assert any("a" in w and "abweichend" in w and "nichts wird gelöscht" in w for w in prot.warnungen)
    else:
        assert ids == ["a", "b"] and not [w for w in prot.warnungen if "abweichend" in w]


def test_csv_zeilennummer_der_datei_auch_mit_zeilen_muster(tmp_path):
    """E50, Codefehler aus E49 (_csv_lesen): Meldungen nennen die Zeile der Datei. Mit zeilen_muster zählte
    die Nummer bis E49 die gewählten Zeilen ab 2, ohne Kopfzeile die physischen Zeilen falsch, sobald ein Feld
    einen Zeilenumbruch enthielt."""
    datei = tmp_path / "punkte.csv"
    datei.write_text("Titel\nStand 2025\nid;x;y\nP1;1;2\n\nP2;abc;2\nQuelle: Test\n", encoding="utf-8")
    cfg = {"pfad": str(datei), "trenner": ";", "zeilen_muster": r"^P", "schluessel_form": r"^P\d+$",
           "spalten_namen": ["id", "x", "y"], "kopf_pruefen": {"zeile": 3, "erwartet": ["id", "x", "y"]},
           "id_spalte": "id", "x_spalte": "x", "y_spalte": "y"}
    prot = Protokoll()
    assert [d["objekt_id"] for d in quellen.csv_quelle(cfg, prot)] == ["P1"]
    assert any(w.startswith("Zeile 6:") for w in prot.warnungen), prot.warnungen
    datei.write_text('id,name,x,y\nA,"zwei\nZeilen",1,2\nB,b,abc,2\n', encoding="utf-8")
    prot = Protokoll()
    list(quellen.csv_quelle({"pfad": str(datei), "id_spalte": "id", "x_spalte": "x", "y_spalte": "y"}, prot))
    assert any(w.startswith("Zeile 4:") for w in prot.warnungen), prot.warnungen


def test_zeitbudget_vor_jeder_anfrage_und_je_block(tmp_path, monkeypatch):
    """E50, Befund W6: Das Zeitbudget der Quelle wird vor jeder Anfrage und je gelesenem Block eines Downloads
    geprüft. Überschritten: ZeitbudgetUeberschritten, keine weitere Anfrage, keine halbe Datei im Cache. Die
    Uhr ist eine Attrappe (keine Wartezeit im Test)."""
    anfragen = []

    class Lang:
        """Antwort mit drei Blöcken; die Uhr springt nach dem ersten über die Frist."""
        status_code, headers, is_redirect = 200, {}, False

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def raise_for_status(self):
            pass

        def iter_content(self, n):
            for _ in range(3):
                zeit[0] += 100
                yield b"x" * 10

    monkeypatch.setattr(quellen.requests, "get", lambda url, **k: anfragen.append(url) or Lang())
    zeit = [0]
    prot = Protokoll()
    prot.frist_setzen(1, uhr=lambda: zeit[0])
    with pytest.raises(quellen.ZeitbudgetUeberschritten, match="Zeitbudget von 1 min"):
        quellen.datei_abrufen("https://dienst.example/gross.zip", tmp_path / "gross.zip", {}, prot)
    assert anfragen == ["https://dienst.example/gross.zip"]
    assert not (tmp_path / "gross.zip").exists() and not (tmp_path / "gross.zip.teil").exists()
    # Schon abgelaufen: keine Anfrage mehr
    with pytest.raises(quellen.ZeitbudgetUeberschritten):
        quellen.abrufen("https://dienst.example/ows", None, {}, prot)
    assert len(anfragen) == 1
    # Die Ausnahme ist kein QuellenFehler und kein RuntimeError: Die Fehlerbehandlung der Adapter, die
    # Lücken als Warnung festhält (WFS, OGC API), darf sie nicht abfangen
    assert not issubclass(quellen.ZeitbudgetUeberschritten, RuntimeError)


# --- E50, Nachprüfung (Prüfer zu E50, 06.11.2026) -------------------------------------------------------

def test_robots_sperre_auf_dem_rechner_den_requests_anwaehlt():
    """Nachprüfung zu E50 (Gegenprobe mit Mutation): Ohne die zweite Fassung in robots_gesperrt (die Adresse,
    wie requests sie sendet) blieben alle bisherigen robots-Tests grün; die Zusage „geprüft wird, was requests
    tatsächlich sendet“ war nicht eigens getestet. Bei dieser Adresse liest urlsplit foo.example, requests
    verbindet aber zu www.regionalstatistik.de (gesperrt mit `/`). Kein Abruf."""
    assert quellen.robots_gesperrt("https://www.regionalstatistik.de\\@foo.example/x") == "/"


def test_kachelgroesse_wird_vor_dem_ersten_abruf_geprueft(monkeypatch):
    """Nachprüfung zu E50 (_kacheln): Die Prüfung von kachel_m steckte im Generator und griff erst bei der
    ersten Kachel, nach GetCapabilities und DescribeFeatureType. Ein Tippfehler löste so zwei Netzabrufe aus,
    bevor er gemeldet wurde. Jetzt prüft wfs den Wert vor dem ersten Abruf."""
    anfragen = []
    monkeypatch.setattr(quellen, "abrufen", lambda url, params, cfg, prot: anfragen.append(params) or b"")
    cfg = {"url": "https://dienst.example/ows", "typename": "x:o", "id_feld": "oid", "geometrie_feld": "geom",
           "bbox": [0, 0, 2000, 1000], "kachel_m": 0}
    with pytest.raises(QuellenFehler, match="kachel_m"):
        list(quellen.wfs(cfg, Protokoll()))
    assert anfragen == []


def test_wfs_doppelte_id_merkt_je_objekt_eine_kurze_pruefsumme():
    """Nachprüfung zu E50, Befund W5 (Speicher): Je Objekt-ID merkt sich der Adapter eine kurze Prüfsumme
    (16 Bytes) als bytes, ein set erst, wenn eine abweichende Fassung kommt. Das set mit einem SHA-256-Digest
    je ID brauchte rund 380 B je ID statt 103 B für das frühere set[str] (tracemalloc, Prüfer zu E50)."""
    gesehen: dict = {}
    a1, a2 = quellen._inhalt({"n": "Haus"}, None), quellen._inhalt({"n": "Haus Nord"}, None)
    assert len(a1) == 16 and a1 != a2
    assert quellen._fassung_merken(gesehen, "a", a1) == "neu" and gesehen["a"] == a1
    assert quellen._fassung_merken(gesehen, "a", a1) == "gleich" and gesehen["a"] == a1
    assert quellen._fassung_merken(gesehen, "a", a2) == "abweichend" and gesehen["a"] == {a1, a2}
    assert quellen._fassung_merken(gesehen, "a", a2) == "gleich"
    assert quellen._fassung_merken(gesehen, "a", a1) == "gleich"


# --- E51: Prüfbericht vom 07.11.2026, 03:13 (K2 Fußzeilen, W3 Kennung aus gml:id) --------------------------

@pytest.mark.parametrize("letzte", [
    ";Hohensaaten;10;5;5",              # Schlüssel fehlt, Zeile in Datenbreite
    "12O60096;Hohensaaten;10;5;5",      # Buchstabe O statt Ziffer 0 im Schlüssel
    '"12060096;Hohensaaten;10;5;5',     # öffnendes Anführungszeichen: ein Feld, beginnt mit dem Schlüssel
    "12060096",                         # abgeschnitten, nur der Schlüssel
    ";Hohensaaten;;;",                  # nur der Name, nicht in der ersten Spalte
], ids=["ohne_schluessel", "buchstabe", "anfuehrungszeichen", "abgeschnitten", "nur_name"])
def test_csv_beschaedigte_letzte_datenzeile_ist_keine_fusszeile(tmp_path, letzte):
    """E51, Befund K2 (Antwort 52): Der Datenbereich endete an der letzten Zeile in Form einer Datenzeile;
    alles danach galt ohne Prüfung als Fuß. Eine beschädigte letzte Datenzeile verschwand so still, und der
    Abgleich durfte ihren bisherigen Wert löschen. Jetzt muss jede Zeile nach dem Datenbereich eindeutig eine
    erlaubte Fußzeile sein (leer, oder Standard: genau ein Feld in der ersten Spalte, ohne Schlüsselform);
    sonst ist der Abruf unvollständig, mit Zeilennummer, und nichts wird gelöscht."""
    zeilen = AUSZUG_12411.read_text(encoding="latin-1").splitlines()
    assert zeilen[12].startswith("12060096;")       # Zeile 13: letzte Datenzeile des Auszugs
    zeilen[12] = letzte
    datei = tmp_path / "beschaedigt.csv"
    datei.write_text("\n".join(zeilen) + "\n", encoding="latin-1")
    prot = Protokoll()
    ds = {d["objekt_id"] for d in quellen.csv_quelle(_statistik_cfg(pfad=str(datei)), prot)}
    assert ds == {"12051000", "12060005", "12060012"} and prot.unvollstaendig, prot.warnungen
    (w,) = [w for w in prot.warnungen if "nach dem Datenbereich" in w]
    assert "(Zeilen 13)" in w and "nichts wird gelöscht" in w


def test_csv_fussblock_des_auszugs_bleibt_erlaubt_und_fuss_muster_je_quelle(tmp_path):
    """E51, Gegenprobe zu K2: Der Fußblock des Auszugs (Quellenangabe, Lizenz über mehrere Zeilen, Stand) und
    Fußzeilen mit Semikolons dahinter („Fußnote;;;;“) bleiben erlaubt. Eine Fußzeile mit mehreren Feldern
    braucht ein Muster der Quelle (fuss_muster).

    Nachprüfung zu E51: Ein erstes Feld in Schlüsselform („2014 Gebietsreform“, „12060100 Testort“) ist ohne
    Muster oder mit einem Muster, das nicht passt, zweifelhaft; ein passendes Muster erlaubt es (bis dahin
    blieb die Quelle auch mit passendem Muster dauerhaft unvollständig, obwohl E51 diese Abhilfe nannte).
    Hart auch mit dem weitesten Muster '.*': eine Zahl, ein Fehlwert oder ein Schlüssel nach dem ersten Feld.
    Die beiden letzten Fälle decken die Regeln einzeln ab; ohne Muster fing sie schon die Regel „genau ein
    Feld“ ab (Gegenproben des Prüfers: ohne `x in fehlwerte` bzw. mit _schluesselartig nur im ersten Feld
    bestanden alle Tests)."""
    prot = Protokoll()
    assert len(list(quellen.csv_quelle(_statistik_cfg(), prot))) == 4
    assert not prot.unvollstaendig and not prot.warnungen, prot.warnungen
    zeilen = AUSZUG_12411.read_text(encoding="latin-1").splitlines()
    datei = tmp_path / "fuss.csv"
    for fuss, muster, erlaubt in (("Fußnote;;;;", None, True), ("Quelle:;Testamt;;;", None, False),
                                  ("Quelle:;Testamt;;;", r"^Quelle:;", True),
                                  ("12060100 Testort;;;;", None, False),
                                  ("12060100 Testort;;;;", r"^Quelle:;", False),
                                  ("2014 Gebietsreform", None, False),
                                  ("2014 Gebietsreform", r"^2014 Gebietsreform", True),
                                  ("2014 Gebietsreform;;;;", r"^2014 ", True),
                                  ("2014 Gebietsreform;12;;;", r".*", False),
                                  ("Quelle:;Testamt;1;2;3", r".*", False),
                                  ("Quelle:;-;;;", r".*", False),
                                  ("Quelle:;12060100 Ort;;;", r".*", False)):
        datei.write_text("\n".join([*zeilen[:13], fuss, *zeilen[13:]]) + "\n", encoding="latin-1")
        prot = Protokoll()
        extra = {"fuss_muster": muster} if muster else {}
        assert len(list(quellen.csv_quelle(_statistik_cfg(pfad=str(datei), **extra), prot))) == 4
        assert prot.unvollstaendig is not erlaubt, (fuss, muster, prot.warnungen)


def _seite_nur_gml_id(ids, gml: str = "http://www.opengis.net/gml/3.2"):
    """GetFeature-Antwort (WFS 2.0) ohne numberMatched, je Objekt nur die Kennung im Attribut gml:id des
    Features, kein eigenes ID-Element."""
    teile = "".join(
        f'<wfs:member><x:o gml:id="o.{i}"><x:name>N{i}</x:name><x:geom><gml:Point><gml:pos>1 2</gml:pos>'
        f'</gml:Point></x:geom></x:o></wfs:member>' for i in ids)
    return (f'<wfs:FeatureCollection xmlns:wfs="http://www.opengis.net/wfs/2.0" xmlns:gml="{gml}" '
            f'xmlns:x="urn:x" numberReturned="{len(ids)}">{teile}</wfs:FeatureCollection>').encode()


_SCHEMA_OHNE_ID = b"""<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"><xs:element name="o"
 substitutionGroup="gml:AbstractFeature"><xs:complexType><xs:sequence><xs:element name="name"/>
<xs:element name="geom"/></xs:sequence></xs:complexType></xs:element></xs:schema>"""


@pytest.mark.parametrize("schema", [True, False], ids=["mit_schema", "ohne_schema"])
def test_wfs_kennung_aus_dem_attribut_gml_id(monkeypatch, schema):
    """E51, Befund W3 (LB 4.1, Antwort 64): Mit id_feld "@gml:id" kommt die Objekt-ID aus dem Attribut gml:id
    des Features; die Testobjekte haben kein eigenes ID-Element. Durch die Kachelung mit Folgeseiten (Dienst
    begrenzt still auf 2, ohne Gesamtzahl), damit auch der Fortschritt je Kachel über diese Kennung zählt.
    Das Schema hat kein Feld für die Kennung; die Quelle hält deshalb nicht an. SORTBY entfällt (eine
    Sortierung nach gml:id kann der Dienst nicht zusagen), die Seiten gelten als ungeordnet."""
    objekte, anfragen = ["a", "b", "c", "d", "e"], []

    def abrufen(url, params, cfg, prot):
        if params["REQUEST"] == "GetCapabilities":
            return _CAP_SORTIERT
        if params["REQUEST"] == "DescribeFeatureType":
            if schema:
                return _SCHEMA_OHNE_ID
            raise RuntimeError("kein Schema im Test")
        anfragen.append(params)
        s = params.get("STARTINDEX") or 0
        return _seite_nur_gml_id(objekte[s:s + min(2, params["COUNT"])])

    monkeypatch.setattr(quellen, "abrufen", abrufen)
    prot = Protokoll()
    ds = list(quellen.wfs({**_KACHEL, "id_feld": "@gml:id", "felder": {"name": "name"}}, prot))
    assert [d["objekt_id"] for d in ds] == ["o.a", "o.b", "o.c", "o.d", "o.e"]
    assert ds[0]["werte"] == {"name": "Na"}
    assert not prot.unvollstaendig and "fehlende_felder" not in prot.info, prot.warnungen
    assert [a.get("STARTINDEX") for a in anfragen] == [None, 2, 4, 5]
    assert not any("SORTBY" in a for a in anfragen)


def test_wfs_kennung_gml_id_auch_in_gml_31_und_nur_dieses_attribut(monkeypatch):
    """E51, W3: gml:id gilt auch im Namensraum von GML 3.1 (WFS 1.1.0 liefert GML 3.1.1). Andere Attribute
    nach „@“ lehnt die Pipeline vor dem ersten Abruf ab (QuellenFehler), statt still ohne Kennung zu lesen."""
    dienst = _kachel_dienst([], 3, [])

    def abrufen(url, params, cfg, prot):
        if params["REQUEST"] == "GetFeature":
            return _seite_nur_gml_id(["a"], gml="http://www.opengis.net/gml")
        return dienst(url, params, cfg, prot)

    monkeypatch.setattr(quellen, "abrufen", abrufen)
    prot = Protokoll()
    assert [d["objekt_id"] for d in quellen.wfs({**_KACHEL, "id_feld": "@gml:id"}, prot)] == ["o.a"]

    def nie(*a, **k):
        raise AssertionError("abgerufen")
    monkeypatch.setattr(quellen, "abrufen", nie)
    for falsch in ("@fid", "@gml:identifier", "@"):
        with pytest.raises(QuellenFehler, match="id_feld"):
            list(quellen.wfs({**_KACHEL, "id_feld": falsch}, Protokoll()))
