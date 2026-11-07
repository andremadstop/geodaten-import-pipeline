"""Zuordnung Quelle -> Zieltabelle und Rhythmus je Quelle, ohne Datenbank.

pipeline.ziel ist die letzte Stufe von laden → quellen → ziel: Es bildet aus den Datensätzen der
Adapter die Zeilen der Bestandstabellen von MOSIDI (E22). Die Tests hier prüfen nur den Teil ohne
Datenbank: die Zuordnung aus der Konfiguration (alle mitgelieferten Dateien), das Umformen breiter
Tabellen, die Höchstlängen der Textspalten (E31, E47), die feste Regel für den INKAR-Zielschlüssel (E40,
E42) und den Rhythmus je Quelle (E24). Abgleich, Löschen und Metadaten prüfen die Datenbanktests.
"""
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from pipeline import einrichten, laden, waechter, ziel

KONFIGURATION = Path(__file__).resolve().parent.parent / "config"


def test_alle_konfigurationen_haben_gueltige_ziele():
    """Jede Quelle in jeder mitgelieferten Konfiguration hat ein Ziel mit zugeordnetem Schlüssel."""
    for datei in KONFIGURATION.glob("*.yaml"):
        cfg = yaml.safe_load(datei.read_text(encoding="utf-8"))
        for name, q in cfg["quellen"].items():
            z = ziel.aus_konfiguration(name, q)
            assert z.schluessel and set(z.schluessel) <= set(z.spalten) | set(z.fest), (datei, name)
            if q.get("rhythmus"):
                assert laden.naechster_termin(q["rhythmus"], datetime.now(UTC)) is not None


def test_mosidi_zuordnung_steht_in_der_konfiguration():
    """Die mitgelieferte config/quellen.yaml schreibt in genau die vier Bestandstabellen von MOSIDI (E22),
    INKAR mit den festen Werten source und granularity (E28), der Zusatzregel und data_type (E40) und dem
    Quellschlüssel aus fünf Feldern."""
    cfg = yaml.safe_load((KONFIGURATION / "quellen.yaml").read_text(encoding="utf-8"))
    tabellen = {z.tabelle for z in einrichten.ziele(cfg)}
    assert tabellen == {"Gebäude (ALKIS)", "Kommunale Gebiete Brandenburg (InNoWest)", "Landkreis",
                        "dashboard_data_de"}
    inkar = ziel.aus_konfiguration("inkar_gemeinden", cfg["quellen"]["inkar_gemeinden"])
    assert inkar.fest == {"source": "INKAR", "granularity": "Gemeindeebene"}
    assert inkar.zusatz == {"spalte": "indikator", "feld": "bereich", "ausser": ["ZOM"]}
    assert inkar.konstant == {"data_type": "indikator"} and "data_type" in inkar.spalten_aendern()
    assert cfg["quellen"]["inkar_gemeinden"]["schluessel"] == ["Kennziffer", "Bereich", "Kuerzel",
                                                               "Indikator", "Zeitbezug"]


def test_ohne_ziel_oder_schluessel_klare_meldung():
    """Eine Quelle ohne ziel.tabelle oder mit einer Schlüsselspalte ohne Zuordnung bricht schon beim Lesen der
    Konfiguration mit ZielFehler und verständlicher Meldung ab."""
    with pytest.raises(ziel.ZielFehler, match="kein Ziel"):
        ziel.aus_konfiguration("q", {"typ": "csv"})
    with pytest.raises(ziel.ZielFehler, match="ohne Zuordnung"):
        ziel.aus_konfiguration("q", {"ziel": {"tabelle": "t", "schluessel": ["k"], "spalten": {"x": "y"}}})


def test_breite_tabelle_wird_zu_zeilen_je_wert():
    """`je_wert` formt eine breite Zeile in eine Zeile je Wert um: Indikator aus der Zuordnung, Jahr aus dem
    Stichtag, ganze Zahl als int, Quellschlüssel `_q` aus Objekt-ID und Feld, Gebietsschlüssel statt
    Geometrie (E22)."""
    z = ziel.aus_konfiguration("afs", {"ziel": {
        "tabelle": "dashboard_data_de", "schluessel": ["kennziffer", "indikator", "zeitbezug"],
        "spalten": {"indikator": "_indikator", "kennziffer": "_gebiet", "wert": "_wert",
                    "zeitbezug": "_jahr"},
        "je_wert": {"bev": "Bevölkerung", "flaeche": "Fläche"}}})
    ds = {"objekt_id": "12051000", "geom": ("gebiet", "12051000"),
          "werte": {"name": "Brandenburg", "bev": 50000.0, "flaeche": 229.7},
          "zeit": {"bev": "2025-12-31", "flaeche": "2025-12-31"}}
    zeilen = list(ziel.zeilen(ds, z))
    assert [w for w, _, _ in zeilen] == [
        {"indikator": "Bevölkerung", "kennziffer": "12051000", "wert": 50000, "zeitbezug": "2025",
         "_q": "12051000|bev"},
        {"indikator": "Fläche", "kennziffer": "12051000", "wert": 229.7, "zeitbezug": "2025",
         "_q": "12051000|flaeche"}]
    assert all(g is None and gebiet == "12051000" for _, g, gebiet in zeilen)


def test_geometriezeile_mit_objekt_id():
    """Eine Quelle mit Geometrie ergibt genau eine Zeile mit der Objekt-ID in der Schlüsselspalte und
    unveränderter Geometrie; aktualisiert werden nur Spalten außerhalb des Schlüssels."""
    z = ziel.aus_konfiguration("g", {"ziel": {"tabelle": "Gebäude (ALKIS)", "schluessel": ["oid"],
                                              "geometrie": "geom",
                                              "spalten": {"oid": "_id", "anzahlgs": "anzahlgs"}}})
    ((werte, geom, gebiet),) = ziel.zeilen({"objekt_id": "DEBBAL0001", "geom": ("gml", "<gml/>"),
                                            "werte": {"anzahlgs": "3"}}, z)
    assert werte == {"oid": "DEBBAL0001", "anzahlgs": "3"} and geom == ("gml", "<gml/>") and gebiet is None
    assert z.spalten_aendern() == ["anzahlgs"]


def test_rhythmus_naechster_termin():
    """naechster_termin (E24): ohne Rhythmus oder ohne bisherigen Erfolg None (bei jedem Lauf laden), sonst
    Takt minus eine Stunde Spielraum; fehlt der Tag im Zielmonat, gilt dessen letzter Tag; ein unbekannter
    Rhythmus ergibt ValueError."""
    t = datetime(2026, 1, 31, 3, 0, tzinfo=UTC)
    assert laden.naechster_termin(None, t) is None
    assert laden.naechster_termin("monatlich", None) is None
    assert laden.naechster_termin("taeglich", t) == datetime(2026, 2, 1, 2, 0, tzinfo=UTC)
    # Monatsende: 31.01. + 1 Monat = 28.02., eine Stunde Spielraum für den Zeitgeber
    assert laden.naechster_termin("monatlich", t) == datetime(2026, 2, 28, 2, 0, tzinfo=UTC)
    schalt = laden.naechster_termin("jaehrlich", datetime(2024, 2, 29, tzinfo=UTC))
    assert schalt.date().isoformat() == "2025-02-27"
    with pytest.raises(ValueError, match="Unbekannter Rhythmus"):
        laden.naechster_termin("stuendlich", t)


def test_letzter_bericht_ueberspringt_nicht_faellige(tmp_path):
    """letzter_bericht nimmt je Quelle den letzten Bericht, in dem sie wirklich geladen wurde: ein jüngerer
    Eintrag „nicht fällig“ verdeckt den älteren Stand mit Feldliste nicht."""
    import json
    (tmp_path / "20261101T000000Z.json").write_text(json.dumps({"quellen": [
        {"quelle": "inkar", "status": "ok", "info": {"felder": ["a"]}}]}), encoding="utf-8")
    (tmp_path / "20261102T000000Z.json").write_text(json.dumps({"quellen": [
        {"quelle": "inkar", "status": "nicht_faellig"}, {"quelle": "wfs", "status": "ok"}]}),
        encoding="utf-8")
    vorher = waechter.letzter_bericht(tmp_path, "20261103T000000Z")
    assert vorher["inkar"]["info"]["felder"] == ["a"] and vorher["wfs"]["status"] == "ok"


def test_nicht_faellig_im_bericht_und_in_der_ueberwachung(tmp_path):
    """Eine nicht fällige Quelle steht im Textbericht als „nicht fällig“, ist für --status keine Störung und
    löst keinen Meldungsentwurf aus (E24)."""
    import json

    from pipeline import betrieb
    b = {"lauf_id": "20261103T120000Z", "laufzeit_s": 1, "quellen": [
        {"quelle": "inkar", "status": "nicht_faellig", "rhythmus": "monatlich",
         "naechster_termin": "2026-12-01T02:00:00+00:00"},
        {"quelle": "wfs", "status": "ok", "zaehler": {"neu": 1, "geaendert": 0, "geloescht": 0,
                                                     "unveraendert": 0}}]}
    assert "nicht fällig" in laden.zusammenfassung(b)
    (tmp_path / "20261103T120000Z.json").write_text(json.dumps(b), encoding="utf-8")
    code, zeile = betrieb.status(tmp_path, 26, datetime(2026, 11, 3, 13, tzinfo=UTC))
    assert code == betrieb.OK, zeile
    assert not waechter.meldung_noetig(b["quellen"][0])


def test_textspalten_mit_hoechstlaenge():
    """E31: Spalten, deren Inhalt PostgreSQL beim Umwandeln still kürzen würde."""
    z = ziel.aus_konfiguration("lau", {"ziel": {
        "tabelle": "Kommunale Gebiete Deutschland", "schluessel": ["objid"],
        "spalten": {"objid": "_id", "name": "name", "beschreibung": "text", "anzahl": "n"},
        "fest": {"quelle": "GISCO"}}})
    z.typen = {"objid": "character varying(16)", "name": "character varying(60)", "beschreibung": "text",
               "anzahl": "integer", "quelle": "character(3)", "frei": "character varying"}
    assert ziel.laengen(z) == {"objid": 16, "name": 60, "quelle": 3}


def test_zu_langer_fester_wert_haelt_die_quelle_an():
    """Bis E46 wurde ein zu langer fester Wert gekürzt gespeichert. Seit E47 kürzt die Pipeline nichts mehr:
    Ein fester Wert gilt für alle Zeilen, die Quelle wird angehalten (Konfiguration anpassen)."""
    from pipeline.quellen import Protokoll
    z = ziel.aus_konfiguration("q", {"ziel": {"tabelle": "dashboard_data_de", "schluessel": ["kennziffer"],
                                              "spalten": {"kennziffer": "_gebiet"},
                                              "fest": {"granularity": "Gemeindeebene  "}}})
    z.typen = {"kennziffer": "text", "granularity": "character varying(13)"}
    prot = Protokoll()
    assert ziel.laengen_pruefen(None, z, prot) is None   # nur folgende Leerzeichen: kein Verlust
    assert not prot.warnungen
    z.typen["granularity"] = "character varying(5)"
    grund = ziel.laengen_pruefen(None, z, prot)
    assert "Fester Wert für granularity länger als 5 Zeichen" in grund and "nicht gekürzt" in grund
    assert prot.info["zu_lang"] == {"granularity": 1}


def test_datum_mit_zeitzone_z_nur_genau_diese_form():
    """E47: Ein Datum mit Zeitzonenkennung Z (xs:date in UTC, so liefert der ALKIS-WFS der LGB `aktualit`)
    darf in eine zu kurze Spalte ohne die Kennung; jede andere Form nicht."""
    m = ziel.DATUM_Z
    assert m.fullmatch("2020-09-03Z")
    for anders in ("2020-09-03", "2020-09-03+01:00", "2020-09-03z", "2020-9-03Z", "2020-09-03ZZ",
                   " 2020-09-03Z", "2020-09-03 Z", "20200903Z"):
        assert not m.fullmatch(anders), anders


# --- E40: feste Regel für den INKAR-Schlüssel ------------------------------------------------------

INKAR_ZIEL = {"tabelle": "dashboard_data_de", "schluessel": ["kennziffer", "indikator", "zeitbezug"],
              "spalten": {"indikator": "indikator", "kennziffer": "kennziffer", "wert": "wert",
                          "zeitbezug": "zeitbezug"},
              "fest": {"source": "INKAR", "granularity": "Gemeindeebene"},
              "zusatz": {"spalte": "indikator", "feld": "bereich", "ausser": ["ZOM"]}}


def _inkar_ds(bereich, kuerzel, indikator, wert, jahr=2023, kz="12051000"):
    """INKAR-Datensatz in Langform: Objekt-ID aus Kennziffer, Bereich, Kürzel, Indikator und Jahr,
    Gebietsschlüssel statt Geometrie."""
    werte = {"bereich": bereich, "kuerzel": kuerzel, "indikator": indikator, "kennziffer": kz,
             "zeitbezug": jahr, "wert": wert}
    return {"objekt_id": f"{kz}|{bereich}|{kuerzel}|{indikator}|{jahr}", "geom": ("gebiet", kz),
            "werte": werte}


def _zielschluessel(ds, z):
    """Werte der Schlüsselspalten der einen Zeile, die ziel.zeilen aus dem Datensatz bildet."""
    ((w, _, _),) = ziel.zeilen(ds, z)
    return tuple(w[s] for s in z.schluessel)


def test_zusatz_haengt_nur_vom_schluessel_der_zeile_ab():
    """Codex-Prüfung 05.11., B1: Der Zielschlüssel einer Zeile ist eine Funktion ihres Quellschlüssels,
    gleich ob es eine zweite Zeile mit demselben Langtext gibt und welche Werte beide haben."""
    z = ziel.aus_konfiguration("inkar", {"ziel": INKAR_ZIEL})
    zom = _zielschluessel(_inkar_ds("ZOM", "q_bev_fl", "Einwohnerdichte", 100.0), z)
    lrb = _zielschluessel(_inkar_ds("LRB", "q_bev_fl", "Einwohnerdichte", 100.0), z)
    assert zom == ("12051000", "Einwohnerdichte", 2023)
    assert lrb == ("12051000", "Einwohnerdichte (LRB)", 2023)
    # anderer Wert, andere Nachbarn: derselbe Zielschlüssel
    assert _zielschluessel(_inkar_ds("LRB", "q_bev_fl", "Einwohnerdichte", 999.0), z) == lrb
    assert _zielschluessel(_inkar_ds("LRB", "q_bev_fl", "Einwohnerdichte", None), z) == lrb
    # anderes Kürzel im selben Bereich: dieselbe Regel, der Lauf erkennt die Mehrdeutigkeit (DB-Test)
    assert _zielschluessel(_inkar_ds("LRB", "a_bb_4G", "Einwohnerdichte", 1.0), z) == lrb
    # mehrere Felder: Bereich und Kürzel
    z2 = ziel.aus_konfiguration("inkar", {"ziel": {**INKAR_ZIEL, "zusatz": {
        "spalte": "indikator", "feld": ["bereich", "kuerzel"], "ausser": ["ZOM"]}}})
    assert _zielschluessel(_inkar_ds("LRB", "a_bb_4G", "Einwohnerdichte", 1.0), z2) == (
        "12051000", "Einwohnerdichte (LRB, a_bb_4G)", 2023)
    # fehlt ein Teil des Quellschlüssels, wird der Zielschlüssel nicht geraten
    assert _zielschluessel(_inkar_ds("", "q_bev_fl", "Einwohnerdichte", 1.0), z)[1] is None


def test_zusatz_ausser_gilt_nur_fuer_den_bereich():
    """Prüfung 05.11., Runde 2 (E42): `ausser` nahm einer ZOM-Zeile den ganzen Zusatz, auch das Kürzel; mit
    feld: [bereich, kuerzel] blieben zwei Kürzel mit gleichem Langtext in ZOM mehrdeutig. Jetzt entfällt nur
    der Bereich. Die ausgelieferte Regel (feld ist ein Wort) ergibt dieselben Namen wie bisher."""
    konfig = Path(__file__).resolve().parent.parent / "config"
    for datei, quelle in (("quellen.yaml", "inkar_gemeinden"), ("deutschland.yaml", "inkar_gemeinden_de")):
        ausgeliefert = yaml.safe_load((konfig / datei).read_text(encoding="utf-8"))["quellen"][quelle]
        assert ausgeliefert["ziel"]["zusatz"] == INKAR_ZIEL["zusatz"], datei
    z = ziel.aus_konfiguration("inkar", {"ziel": INKAR_ZIEL})
    assert _zielschluessel(_inkar_ds("ZOM", "xbev", "Bevölkerung", 1.0), z)[1] == "Bevölkerung"
    assert _zielschluessel(_inkar_ds("LRB", "xbev", "Bevölkerung", 1.0), z)[1] == "Bevölkerung (LRB)"
    z2 = ziel.aus_konfiguration("inkar", {"ziel": {**INKAR_ZIEL, "zusatz": {
        "spalte": "indikator", "feld": ["bereich", "kuerzel"], "ausser": ["ZOM"]}}})
    namen = {_zielschluessel(_inkar_ds("ZOM", k, "Bevölkerung", 1.0), z2)[1] for k in ("xbev", "e5_bev")}
    assert namen == {"Bevölkerung (xbev)", "Bevölkerung (e5_bev)"}
    assert _zielschluessel(_inkar_ds("LRB", "xbev", "Bevölkerung", 1.0), z2)[1] == "Bevölkerung (LRB, xbev)"


def test_alte_unterscheiden_regel_wird_abgelehnt():
    """Die vor E40 gültige Einstellung `unterscheiden`, ein `zusatz` auf eine nicht zugeordnete Spalte und ein
    `konstant`, das eine Spalte aus `fest` doppelt belegt, werden mit ZielFehler abgelehnt."""
    with pytest.raises(ziel.ZielFehler, match="seit E40"):
        ziel.aus_konfiguration("q", {"ziel": {**INKAR_ZIEL, "unterscheiden": {"spalte": "indikator",
                                                                             "feld": "bereich"}}})
    with pytest.raises(ziel.ZielFehler, match="zusatz braucht"):
        ziel.aus_konfiguration("q", {"ziel": {**INKAR_ZIEL, "zusatz": {"spalte": "wert_x", "feld": "b"}}})
    with pytest.raises(ziel.ZielFehler, match="konstant und zugeordnet"):
        ziel.aus_konfiguration("q", {"ziel": {**INKAR_ZIEL, "konstant": {"source": "x"}}})


def test_konstant_wird_gesetzt_und_verglichen_grenzt_aber_nicht_ab():
    """B11: data_type als konstanter Wert: in INSERT und UPDATE, im Vergleich, nicht in der Abgrenzung
    der Zeilen einer Quelle (die bilden nur `fest`), damit vorhandene Zeilen ohne data_type nicht als
    fremd gelten und doppelt angelegt werden."""
    z = ziel.aus_konfiguration("q", {"ziel": {**INKAR_ZIEL, "konstant": {"data_type": "indikator"}}})
    assert z.spalten_neu() == ["indikator", "kennziffer", "wert", "zeitbezug", "source", "granularity",
                               "data_type"]
    assert z.spalten_aendern() == ["wert", "data_type"]
    z.typen = {s: "text" for s in z.spalten_neu()}
    from psycopg import sql
    assert "data_type" not in sql.SQL("").join([ziel._bereich("t", z)]).as_string(None)


def test_metadaten_update_nur_vorhandene_spalten(monkeypatch):
    """E50, Codefehler aus E49 (ziel.metadaten_schreiben): Das UPDATE setzte imported, dct_bbox, dct_centroid
    und dct_modified ungefiltert und scheiterte an einer table_metadata ohne diese Spalten (das INSERT nahm
    schon nur vorhandene). Jetzt gilt dieselbe Auswahl für beide. Cursor als Attrappe: Die Anweisungen werden
    mitgeschrieben, rowcount 1 heißt „vorhandene Zeile aktualisiert“."""
    z = ziel.aus_konfiguration("q", {"ziel": {"tabelle": "t", "schluessel": ["oid"], "geometrie": "geom",
                                              "spalten": {"oid": "_id"}, "metadaten": {"je": "tabelle"}}})
    z.metadaten["_spalten"] = {"table_name", "dct_title"}
    monkeypatch.setattr(ziel, "_metadaten_zeilen",
                        lambda *a: [({"table_name": "t", "dct_title": "T"}, ["table_name"], "geom")])

    class Cursor:
        """Schreibt jede Anweisung als Text mit."""
        rowcount = 1

        def __init__(self):
            self.texte = []

        def execute(self, anweisung, *a):
            self.texte.append(anweisung.as_string(None))

    cur = Cursor()
    ziel.metadaten_schreiben(cur, "q", {}, z, None, datetime(2026, 11, 6, tzinfo=UTC), True)
    (update,) = [t for t in cur.texte if t.startswith("UPDATE")]
    assert '"dct_title" =' in update
    for spalte in ("imported", "dct_bbox", "dct_centroid", "dct_modified"):
        assert f'"{spalte}"' not in update, spalte


def test_dcat_ap_id_nur_aus_der_formel_nie_aus_felder():
    """E52 (Codex-Prüfung, Muss 1): dcat_ap_id kommt nur aus der Formel von MOSIDI (Indikator_Raumebene_
    Herausgeber aus den festen Werten), nie aus `metadaten.felder`. Bis zur Prüfung blieb ein Wert aus
    `felder` stehen, wo die Formel nicht griff (Geometriezeilen, Indikatorquelle ohne festen Wert für die
    Raumebene), und COALESCE hätte ihn danach nie mehr ersetzt. Cursor als Attrappe: liefert einen Indikator
    mit Zeitraum."""
    class Cursor:
        """Beantwortet die Abfrage des Zeitraums je Indikator."""
        def execute(self, *a):
            pass

        def fetchall(self):
            return [("Ind", 2020, 2021)]

    class Prot:
        """Protokoll ohne Angaben des Dienstes."""
        info: dict = {}

    def zeilen(fest: dict, je: str) -> list[dict]:
        """Werte der Metadatenzeilen für ein Ziel mit `fest` und `je`, Spalte und Recht für dcat_ap_id da."""
        z = ziel.aus_konfiguration("q", {"ziel": {
            "tabelle": "t", "schluessel": ["k"], "spalten": {"k": "_id"}, "fest": fest,
            "geometrie": None if je == "indikator" else "geom",
            "metadaten": {"je": je, "felder": {"dcat_ap_id": "FREMD", "dct_license": "L"}}}})
        z.metadaten["_spalten"] = set(ziel.META_SPALTEN) | {ziel.DCAT_AP_ID}
        z.metadaten["_dcat_ap_id"] = True
        return [w for w, _, _ in ziel._metadaten_zeilen(Cursor(), "q", {}, z, Prot())]

    (w,) = zeilen({"source": "S", "granularity": "Gemeinden"}, "indikator")
    assert w["dcat_ap_id"] == "Ind_Gemeinden_S" and w["dct_license"] == "L"
    (w,) = zeilen({"source": "S"}, "indikator")   # Raumebene fehlt: keine Kennung, auch nicht FREMD
    assert "dcat_ap_id" not in w
    (w,) = zeilen({}, "tabelle")                               # Geometriezeile: nie eine Kennung
    assert "dcat_ap_id" not in w
