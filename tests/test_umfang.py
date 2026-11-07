"""Tests ohne Datenbank für die Sperre bei Umfangsänderung einer Quelle (E52, pipeline/umfang.py).

Abgesichert werden: welche Schlüssel zum Umfang gehören (alles außer Beschreibung, Rhythmus, Zeit- und
Größengrenzen, Schutzschwellen, Karte und Schalter; auch unbekannte), dass Reihenfolge und Code der Pipeline
nicht zählen, die Namen geänderter Schlüssel, die reine Entscheidung (anhalten, merken) in allen Fällen, die
Freigabe per Aufruf oder Kennung, die Prüfung der Konfiguration vor dem Lauf, dass eine angehaltene Quelle
keinen Meldungsentwurf an den Anbieter bekommt, dass --umfang-bestaetigen bis quelle_laden durchgereicht und
eine nicht angekommene Bestätigung im Bericht genannt wird. Das Zusammenspiel mit der Datenbank prüfen
test_datenbank.py::test_umfang_*.
"""
import contextlib
import json

import pytest

from pipeline import laden, umfang, waechter

WFS = {"typ": "wfs", "url": "https://dienst.example/ows", "typename": "x:o", "id_feld": "oid",
       "geometrie_feld": "geom", "bbox": [0, 0, 10, 10], "kachel_m": 500, "titel": "Gebäude",
       "rhythmus": "woechentlich",
       "ziel": {"tabelle": "baeume", "schluessel": ["oid"], "spalten": {"oid": "_id"},
                "metadaten": {"je": "tabelle"}}}


def _abdruck(q: dict) -> str:
    """Fingerabdruck des Umfangs einer Quelle."""
    return umfang.fingerabdruck(umfang.teile(q))


def test_unerhebliche_schluessel_aendern_den_umfang_nicht():
    """Beschreibung, Rhythmus, Zeit- und Größengrenzen, Schutzschwellen, Karte, Schalter von E52, die
    Freigabe selbst und der Metadatensatz des Ziels gehören nicht zum Umfang; die Reihenfolge der Schlüssel
    auch nicht."""
    basis = _abdruck(WFS)
    for schluessel, wert in (("titel", "anders"), ("beschreibung", "x"), ("lizenz", "y"), ("kontakt", {}),
                             ("rhythmus", "taeglich"), ("aktiv", False), ("zeitbudget_min", 5),
                             ("db_sperre_max_s", 3), ("pause_s", 1), ("seitengroesse", 10),
                             ("max_je_kachel", 5), ("max_mb", 1), ("max_rueckgang", None), ("karte", False),
                             ("karte_max_objekte", 1), ("robots_freigabe", "x"),
                             ("umfang_bestaetigt", "a" * 12),
                             ("unveraendert_ueberspringen", True), ("vollabgleich_tage", 3)):
        assert _abdruck({**WFS, schluessel: wert}) == basis, schluessel
    assert _abdruck({**WFS, "ziel": {**WFS["ziel"], "metadaten": {"je": "indikator"}}}) == basis
    assert _abdruck(dict(reversed(list(WFS.items())))) == basis


@pytest.mark.parametrize("schluessel, wert", [
    ("url", "https://anders.example/ows"), ("typename", "x:p"), ("bbox", [0, 0, 5, 10]), ("kachel_m", 250),
    ("id_feld", "gml_id"), ("crs", "EPSG:4326"), ("filter", "x > 1"), ("indikatoren", ["a"]),
    ("zeilen_auswahl", {"schluessel": "^12"}), ("unbekannt_kuenftig", 1)])
def test_bedeutsame_und_unbekannte_schluessel_aendern_den_umfang(schluessel, wert):
    """Adresse, Feature-Typ, BBOX, Kacheln, Schlüssel, Koordinatensystem, Filter und Auswahl ändern den
    Umfang, ebenso ein Schlüssel, den niemand vorhergesehen hat (konservativ)."""
    neu = {**WFS, schluessel: wert}
    assert _abdruck(neu) != _abdruck(WFS)
    assert umfang.geaendert(umfang.teile(WFS), umfang.teile(neu)) == [schluessel]


@pytest.mark.parametrize("schluessel, wert", [
    ("tabelle", "andere"), ("schluessel", ["oid", "x"]), ("spalten", {"oid": "_id", "n": "name"}),
    ("fest", {"granularity": "Kreisebene"}), ("loeschen", False), ("je_wert", {"a": "b"})])
def test_ziel_schluessel_aendern_den_umfang_mit_namen(schluessel, wert):
    """Zieltabelle, Schlüssel, Spaltenzuordnung, Raumebene (fest.granularity) und je_wert gehören zum Umfang;
    der Bericht nennt sie als ziel.<name>."""
    neu = {**WFS, "ziel": {**WFS["ziel"], schluessel: wert}}
    assert umfang.geaendert(umfang.teile(WFS), umfang.teile(neu)) == [f"ziel.{schluessel}"]


def test_typen_bleiben_verschieden_und_kein_code():
    """1 und "1" sind verschieden (wie im Fingerabdruck von unveraendert); der Code der Pipeline geht nicht
    ein, ein Update der Pipeline ändert den Umfang also nicht."""
    a = {**WFS, "ziel": {**WFS["ziel"], "je_wert": {1: "x"}}}
    b = {**WFS, "ziel": {**WFS["ziel"], "je_wert": {"1": "x"}}}
    assert _abdruck(a) != _abdruck(b)
    assert "code" not in json.dumps(umfang.teile(WFS))
    # Keine Adresse im Klartext in dem, was gespeichert wird
    assert "dienst.example" not in json.dumps(umfang.teile(WFS))


INKAR = {"typ": "inkar", "url": "https://inkar.example/inkar_2025.zip", "raumbezug": "Gemeinden",
         "form": "lang", "ziel": {"tabelle": "dashboard_data_de", "schluessel": ["kennziffer"]}}


def test_inkar_datei_aus_der_umgebung_gehoert_zum_umfang(monkeypatch):
    """Gesamtprüfung E52 durch Codex, Muss 1: PIPELINE_INKAR_DATEI hat beim INKAR-Adapter Vorrang vor
    `datei` und `url`. Ein Wechsel der Datei über die Umgebung ist eine Umfangsänderung (Teil
    `PIPELINE_INKAR_DATEI`); solange sie gesetzt ist, zählt `datei` der Konfiguration nicht (sie wird nicht
    gelesen). Leer gilt wie im Adapter als nicht gesetzt. Andere Quelltypen lesen die Variable nicht."""
    monkeypatch.delenv("PIPELINE_INKAR_DATEI", raising=False)
    ohne = umfang.teile(INKAR)
    monkeypatch.setenv("PIPELINE_INKAR_DATEI", "")
    assert umfang.teile(INKAR) == ohne
    monkeypatch.setenv("PIPELINE_INKAR_DATEI", "/app/inkar/voll.zip")
    voll = umfang.teile(INKAR)
    assert umfang.geaendert(ohne, voll) == ["PIPELINE_INKAR_DATEI"]
    assert "/app/inkar" not in json.dumps(voll)                     # nur die Prüfsumme, kein Pfad
    monkeypatch.setenv("PIPELINE_INKAR_DATEI", "/app/inkar/teil.zip")
    assert umfang.geaendert(voll, umfang.teile(INKAR)) == ["PIPELINE_INKAR_DATEI"]
    # Mit gesetzter Variable ist `datei` der Konfiguration ohne Wirkung und zählt nicht
    assert umfang.teile({**INKAR, "datei": "/srv/andere.zip"}) == umfang.teile(INKAR)
    # Ohne Variable zählt `datei` wie jeder andere Schlüssel
    monkeypatch.delenv("PIPELINE_INKAR_DATEI")
    assert umfang.geaendert(ohne, umfang.teile({**INKAR, "datei": "/srv/andere.zip"})) == ["datei"]
    # Andere Quelltypen: Variable ohne Bedeutung
    monkeypatch.setenv("PIPELINE_INKAR_DATEI", "/app/inkar/voll.zip")
    assert "PIPELINE_INKAR_DATEI" not in umfang.teile(WFS)


def test_entscheiden_alle_faelle():
    """umfang.entscheiden: (anhalten, merken) je Fall."""
    alt, neu = {"bbox": "1"}, {"bbox": "2"}
    # noch nie gemerkt oder gleich: weiter, merken
    assert umfang.entscheiden(None, neu, 5, True, None) == (False, True)
    assert umfang.entscheiden(None, neu, 5, False, None) == (False, True)
    assert umfang.entscheiden(neu, neu, 5, True, None) == (False, True)
    # geändert mit Löschungen ohne Bestätigung: anhalten, nichts merken
    assert umfang.entscheiden(alt, neu, 1, True, None) == (True, False)
    assert umfang.entscheiden(alt, neu, 1, False, None) == (True, False)    # ersetzte Schlüssel bei Lücke
    # geändert mit Löschungen und Bestätigung: weiter, merken (nur vollständig)
    assert umfang.entscheiden(alt, neu, 3, True, "--umfang-bestaetigen") == (False, True)
    assert umfang.entscheiden(alt, neu, 3, False, "--umfang-bestaetigen") == (False, False)
    # reine Zusätze: weiter; gemerkt nur nach vollständigem Abruf, sonst bleibt der alte
    assert umfang.entscheiden(alt, neu, 0, True, None) == (False, True)
    assert umfang.entscheiden(alt, neu, 0, False, None) == (False, False)
    assert umfang.entscheiden(alt, neu, 0, False, "--umfang-bestaetigen") == (False, False)


def test_bestaetigung_per_aufruf_oder_passender_kennung():
    """Bestätigt ist ein Umfang per Aufruf oder mit `umfang_bestaetigt` = Anfang seines Fingerabdrucks; eine
    Kennung eines anderen Umfangs wirkt nicht (eine spätere Änderung sperrt wieder)."""
    abdruck = _abdruck(WFS)
    assert umfang.bestaetigung(WFS, abdruck, True) == "--umfang-bestaetigen"
    assert umfang.bestaetigung(WFS, abdruck, False) is None
    passend = {**WFS, "umfang_bestaetigt": umfang.kennung(abdruck)}
    assert umfang.bestaetigung(passend, abdruck, False) == "Konfiguration (umfang_bestaetigt)"
    assert umfang.bestaetigung({**WFS, "umfang_bestaetigt": abdruck}, abdruck, False) is not None
    fremd = {**WFS, "umfang_bestaetigt": "0" * 12}
    assert umfang.bestaetigung(fremd, abdruck, False) is None
    # Nach einer weiteren Änderung passt die alte Kennung nicht mehr
    weiter = {**passend, "bbox": [1, 1, 2, 2]}
    assert umfang.bestaetigung(weiter, _abdruck(weiter), False) is None


@pytest.mark.parametrize("wert", [True, "ja",
                                  "ABCDEF123456",  # pragma: allowlist secret
                                  "abc", "g" * 12, 123456789012, "a" * 65])
def test_falsche_freigabe_bricht_vor_dem_laden_ab(tmp_path, monkeypatch, wert):
    """`umfang_bestaetigt` ist nur eine Kennung aus dem Bericht (12 bis 64 Zeichen 0-9, a-f); true oder ein
    Text wären eine Dauerfreigabe. Geprüft vor der Verbindung, auch bei abgeschalteten Quellen."""
    monkeypatch.setattr(laden, "verbinden",
                        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("verbunden")))
    zeile = f"  a: {{typ: csv, pfad: x.csv, aktiv: false, umfang_bestaetigt: {json.dumps(wert)}}}\n"
    cfg = tmp_path / "q.yaml"
    cfg.write_text(f"berichte: {tmp_path / 'berichte'}\nquellen:\n{zeile}", encoding="utf-8")
    with pytest.raises(laden.KonfigFehler, match="umfang_bestaetigt"):
        laden.lauf(str(cfg), alle=True)


def test_aufruf_nur_fuer_aktive_quellen(tmp_path, monkeypatch):
    """--umfang-bestaetigen nennt eine aktive Quelle; ein Tippfehler bricht vor der Verbindung ab."""
    monkeypatch.setattr(laden, "verbinden",
                        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("verbunden")))
    cfg = tmp_path / "q.yaml"
    cfg.write_text(f"berichte: {tmp_path / 'berichte'}\nquellen:\n  a: {{typ: csv, pfad: x.csv}}\n"
                   "  b: {typ: csv, pfad: y.csv, aktiv: false}\n", encoding="utf-8")
    for falsch in ("gibtsnicht", "b"):
        with pytest.raises(laden.KonfigFehler, match=f"--umfang-bestaetigen {falsch}: keine aktive Quelle"):
            laden.lauf(str(cfg), alle=True, umfang_bestaetigen={falsch})
    assert umfang.konfig_fehler({"quellen": {"a": {"umfang_bestaetigt": "a" * 12}}}) == []


def test_angehaltene_quelle_ohne_meldungsentwurf():
    """Eine Quelle, die wegen geänderten Umfangs wartet, liegt an der eigenen Konfiguration: kein Entwurf an
    den Anbieter (wie beim Metadatenkonflikt, E46). Andere angehaltene Quellen behalten ihren Entwurf."""
    assert not waechter.meldung_noetig({"status": "angehalten", "info": {"umfang": {"angehalten": True}}})
    assert waechter.meldung_noetig({"status": "angehalten", "info": {"umfang": {"angehalten": False}}})
    assert waechter.meldung_noetig({"status": "angehalten", "info": {}})


def test_aufruf_wird_durchgereicht_und_ungenutzt_gemeldet(tmp_path, monkeypatch):
    """main reicht --umfang-bestaetigen an lauf weiter; _lauf gibt quelle_laden je Quelle umfang_bestaetigen,
    und eine Bestätigung, die nicht ankam (Quelle nicht fällig), steht als `umfang_ungenutzt` im Bericht und
    im Textbericht."""
    from tests.test_laden import _main, _Verbindung
    aufrufe = {}

    def quelle_laden(conn, name, qcfg, *a, umfang_bestaetigen=False, **kw):
        aufrufe[name] = umfang_bestaetigen
        return {"status": "ok", "zaehler": {k: 0 for k in ("gelesen", "neu", "geaendert", "unveraendert",
                                                           "geloescht", "uebernommen", "zurueckgehalten")}}

    monkeypatch.setattr(laden, "verbinden", lambda *a, **kw: contextlib.nullcontext(_Verbindung()))
    monkeypatch.setattr(laden, "quelle_laden", quelle_laden)
    monkeypatch.setattr(laden, "faelligkeit", lambda conn, name, qcfg, jetzt: (
        (laden.datetime(2999, 1, 1, tzinfo=laden.UTC), False) if name == "b" else (None, False)))
    cfg = tmp_path / "q.yaml"
    cfg.write_text(f"berichte: {tmp_path / 'berichte'}\nquellen:\n  a: {{typ: csv, pfad: x.csv}}\n"
                   "  b: {typ: csv, pfad: y.csv, rhythmus: jaehrlich}\n", encoding="utf-8")
    assert _main(monkeypatch, "--config", str(cfg), "--umfang-bestaetigen", "a",
                 "--umfang-bestaetigen", "b") == 0
    assert aufrufe == {"a": True}
    (datei,) = (tmp_path / "berichte").glob("2*[0-9]Z.json")
    b = json.loads(datei.read_text())
    assert [u["quelle"] for u in b["umfang_ungenutzt"]] == ["b"]
    assert "nicht fällig" in b["umfang_ungenutzt"][0]["warum"]
    assert "Bestätigung des Umfangs für b nicht genutzt" in laden.zusammenfassung(b)
