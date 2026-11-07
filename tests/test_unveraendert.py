"""Tests ohne Datenbank zu E52: unveränderte Lieferung erkennen und überspringen (pipeline/unveraendert.py,
quellen.Protokoll.datei_bereit, die Aufrufe in den Adaptern csv, xlsx und inkar, die Prüfung der
Konfiguration vor dem Lauf und der Schalter --vollabgleich). Den ganzen Ablauf mit Quellenstand, Zählprüfung
und Überspringen in der Datenbank prüft tests/test_datenbank.py (test_unveraendert_…).

Alle Daten sind erfunden und entstehen im tmp_path des Tests."""
import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from pipeline import laden, quellen, unveraendert, waechter
from pipeline.quellen import DateiUnveraendert, Protokoll


def _sha(daten: bytes) -> str:
    """SHA-256 als Hexadezimaltext, wie datei_bereit sie bildet."""
    return hashlib.sha256(daten).hexdigest()


# --- Fingerabdruck der Konfiguration ---------------------------------------------------------------

QUELLE = {"typ": "csv", "pfad": "daten.csv", "id_spalte": "id", "spalten": {"name": "name", "wert": "wert"},
          "ziel": {"tabelle": "t", "schluessel": ["id"], "fest": {"source": "x"}}, "rhythmus": "monatlich",
          "zeitbudget_min": 30, "unveraendert_ueberspringen": True}


def test_fingerabdruck_unabhaengig_von_der_reihenfolge_und_den_steuerschluesseln():
    """Der Fingerabdruck hängt nicht an der Reihenfolge der Schlüssel (YAML) und nicht an den Schlüsseln, die
    nur den Lauf steuern (UNERHEBLICH: Zeitgrenzen, Schalter, vollabgleich_tage, Karte, aktiv). Der Rhythmus
    gehört seit der Nachprüfung durch Codex nicht mehr dazu (steht in table_metadata, Test unten)."""
    a = unveraendert.fingerabdruck(QUELLE)
    umgestellt = dict(reversed(list(QUELLE.items())))
    umgestellt["spalten"] = dict(reversed(list(QUELLE["spalten"].items())))
    assert unveraendert.fingerabdruck(umgestellt) == a
    gesteuert = {**QUELLE, "zeitbudget_min": 90, "db_sperre_max_s": 5, "vollabgleich_tage": 2,
                 "karte": False, "karte_max_objekte": 3, "aktiv": True}
    assert unveraendert.fingerabdruck(gesteuert) == a
    assert "rhythmus" not in unveraendert.UNERHEBLICH
    # Gemischte Schlüsseltypen (YAML erlaubt Zahlen als Schlüssel) brechen die Sortierung nicht
    assert unveraendert.fingerabdruck({**QUELLE, "indikatoren": {1: "a", "b": "c"}})


def test_fingerabdruck_unterscheidet_zahl_und_text_als_schluessel():
    """Nachprüfung durch Codex: ziel.je_wert mit {1: …, "2": …} und mit {"1": …, "2": …} schreibt
    Verschiedenes (eine bzw. zwei Zielzeilen), also muss auch der Fingerabdruck verschieden sein. Bis dahin
    wurden beide Schlüssel zu "1" und ergaben denselben Fingerabdruck; das Überspringen hätte die zusätzliche
    Zeile behalten. Gleiche Schlüssel in anderer Reihenfolge bleiben gleich."""
    def mit(je_wert):
        """QUELLE mit ziel.je_wert `je_wert`."""
        return {**QUELLE, "ziel": {**QUELLE["ziel"], "je_wert": je_wert}}
    text = unveraendert.fingerabdruck(mit({"1": "Indikator 1", "2": "Indikator 2"}))
    gemischt = unveraendert.fingerabdruck(mit({1: "Indikator 1", "2": "Indikator 2"}))
    assert text != gemischt
    assert unveraendert.fingerabdruck(mit({"2": "Indikator 2", 1: "Indikator 1"})) == gemischt
    # Auch ein Wahrheitswert als Schlüssel (YAML: yes/no) ist etwas anderes als der Text
    assert unveraendert.fingerabdruck(mit({True: "a"})) != unveraendert.fingerabdruck(mit({"True": "a"}))


@pytest.mark.parametrize("aenderung", [
    {"pfad": "andere.csv"},
    {"spalten": {"name": "name"}},
    {"ziel": {**QUELLE["ziel"], "fest": {"source": "y"}}},
    {"zeilen_muster": "^12"},
    {"lizenz": "neu"},
    {"rhythmus": "woechentlich"},
    {"rhythmus": None},
    {"unbekannter_schluessel": 1},
], ids=["pfad", "spalten", "ziel", "filter", "lizenz", "rhythmus", "ohne_rhythmus", "unbekannt"])
def test_fingerabdruck_aendert_sich_mit_jedem_bedeutsamen_schluessel(aenderung):
    """Jeder andere Schlüssel geht ein, auch unbekannte (konservativ: im Zweifel ein Vollabgleich zu viel),
    und der Rhythmus: Er steht als dct_accrualperiodicity in table_metadata (Nachprüfung durch Codex)."""
    assert unveraendert.fingerabdruck({**QUELLE, **aenderung}) != unveraendert.fingerabdruck(QUELLE)


def test_fingerabdruck_aendert_sich_mit_dem_code(monkeypatch):
    """Ein Update der Pipeline (anderer Code) ändert den Fingerabdruck: Dieselbe Datei wird dann neu gelesen,
    statt bis zum nächsten Vollabgleich den Stand des alten Codes zu behalten."""
    a = unveraendert.fingerabdruck(QUELLE)
    assert len(unveraendert.code_fingerabdruck()) == 64
    monkeypatch.setattr(unveraendert, "code_fingerabdruck", lambda: "0" * 64)
    assert unveraendert.fingerabdruck(QUELLE) != a


# --- Entscheidung ohne Zählung -------------------------------------------------------------------

JETZT = datetime(2026, 11, 8, 6, 0, tzinfo=UTC)


def _stand(**kw) -> dict:
    """Vergleichsstand wie aus dem Quellenstand gelesen: gleicher Fingerabdruck, Vollabgleich vor 2 Tagen."""
    return {"datei_sha256": "a" * 64, "konfig_sha256": "f", "vollabgleich": JETZT - timedelta(days=2),
            "register_zeilen": 3, "ziel_zeilen": 3, **kw}


@pytest.mark.parametrize(("stand", "kw", "grund"), [
    (_stand(), {"vollabgleich": True}, "--vollabgleich"),
    (_stand(), {"leer_grund": "Gebiet aufgelöst"}, "Leerlieferung"),
    (_stand(), {"abhaengig": True}, "ohne_flaeche"),
    (None, {}, "kein Vergleichsstand"),
    (_stand(datei_sha256=None), {}, "kein Vergleichsstand"),
    (_stand(konfig_sha256="anders"), {}, "Konfiguration"),
    (_stand(vollabgleich=None), {}, "Zeitpunkt"),
    (_stand(vollabgleich=JETZT + timedelta(hours=1)), {}, "Zeitpunkt"),
    (_stand(vollabgleich=JETZT - timedelta(days=7)), {}, "fällig"),
    (_stand(vollabgleich=JETZT - timedelta(days=3)), {"max_tage": 2.5}, "fällig"),
], ids=["erzwungen", "leerlieferung", "abhaengig", "nie", "geleert", "konfiguration", "ohne_zeit",
        "zukunft", "sieben_tage", "eigene_tage"])
def test_entscheiden_jeder_grund_fuer_den_vollabgleich(stand, kw, grund):
    """Jede Bedingung allein verhindert das Überspringen und nennt ihren Grund; 7 Tage nach dem Vollabgleich
    ist er fällig (Grenze eingeschlossen)."""
    args = {"max_tage": 7, "vollabgleich": False, "leer_grund": None, "abhaengig": False, **kw}
    text = unveraendert.entscheiden(stand, "f", JETZT, args["max_tage"], args["vollabgleich"],
                                    args["leer_grund"], args["abhaengig"])
    assert text and grund in text, text


def test_entscheiden_ohne_einwand():
    """Gleicher Fingerabdruck, Vollabgleich jünger als vollabgleich_tage: kein Einwand (die Zählung folgt)."""
    assert unveraendert.entscheiden(_stand(vollabgleich=JETZT - timedelta(days=6, hours=23)), "f", JETZT, 7,
                                    False, None, False) is None


class _Cursor:
    """Cursor-Ersatz für vorpruefen: liefert den Vergleichsstand und danach die Zählungen."""

    def __init__(self, antworten):
        self.antworten, self.anweisungen = list(antworten), []

    def execute(self, text, werte=None):
        self.anweisungen.append(str(text))

    def fetchone(self):
        return self.antworten.pop(0)


def test_vorpruefen_zaehlt_nur_ohne_einwand_und_vergleicht_die_zaehlung(monkeypatch):
    """vorpruefen zählt erst, wenn sonst nichts gegen das Überspringen spricht (Zählung kostet bei INKAR zwei
    count(*) über je rund 33,5 Mio. Zeilen), und überspringt nur bei gleicher Zählung."""
    from types import SimpleNamespace
    z = SimpleNamespace(name="t", gebiet=None)
    abdruck = unveraendert.fingerabdruck(QUELLE)
    zeile = ("a" * 64, abdruck, JETZT - timedelta(days=1), 3, 5)
    gezaehlt = []
    monkeypatch.setattr(unveraendert, "zaehlen", lambda cur, name, z: gezaehlt.append(name) or (3, 5))
    assert unveraendert.vorpruefen(_Cursor([zeile]), "q", z, QUELLE, JETZT, False, None) == ("a" * 64, None)
    monkeypatch.setattr(unveraendert, "zaehlen", lambda cur, name, z: (3, 4))
    sha, grund = unveraendert.vorpruefen(_Cursor([zeile]), "q", z, QUELLE, JETZT, False, None)
    assert sha is None and "Zählprüfung" in grund and "4" in grund and "5" in grund
    # Mit Einwand wird nicht gezählt
    monkeypatch.setattr(unveraendert, "zaehlen", lambda *a: pytest.fail("gezählt trotz Einwand"))
    sha, grund = unveraendert.vorpruefen(_Cursor([zeile]), "q", z, QUELLE, JETZT, True, None)
    assert sha is None and "--vollabgleich" in grund
    z_ab = SimpleNamespace(name="t", gebiet={"ohne_flaeche": "auslassen"})
    assert unveraendert.vorpruefen(_Cursor([zeile]), "q", z_ab, QUELLE, JETZT, False, None)[0] is None
    assert unveraendert.vorpruefen(_Cursor([None]), "q", z, QUELLE, JETZT, False, None)[0] is None
    assert gezaehlt == ["q"]


# --- Konfiguration vor dem Lauf --------------------------------------------------------------------

def _quellen_cfg(tmp_path, quellen_yaml: str) -> str:
    """Konfiguration mit Berichtsordner und den Quellen aus `quellen_yaml` (eingerückt unter quellen:)."""
    datei = tmp_path / "quellen.yaml"
    datei.write_text(f"berichte: {tmp_path / 'berichte'}\nquellen:\n{quellen_yaml}", encoding="utf-8")
    return str(datei)


@pytest.mark.parametrize("zeile", [
    "  a: {typ: csv, pfad: x.csv, unveraendert_ueberspringen: ja}\n",
    "  a: {typ: wfs, url: 'https://x.example/wfs', unveraendert_ueberspringen: true}\n",
    "  a: {typ: geojson, url: 'https://x.example/a.geojson', unveraendert_ueberspringen: true}\n",
    "  a: {typ: csv, pfad: x.csv, unveraendert_ueberspringen: true, vollabgleich_tage: 0}\n",
    "  a: {typ: csv, pfad: x.csv, unveraendert_ueberspringen: true, vollabgleich_tage: true}\n",
    "  a: {typ: csv, pfad: x.csv, unveraendert_ueberspringen: true, vollabgleich_tage: '7'}\n",
    "  a: {typ: csv, pfad: x.csv, unveraendert_ueberspringen: true, vollabgleich_tage: .nan}\n",
    "  a: {typ: csv, pfad: x.csv, unveraendert_ueberspringen: true, vollabgleich_tage: 1.0e+20}\n",
    "  a: {typ: csv, pfad: x.csv, unveraendert_ueberspringen: true, vollabgleich_tage: 36501}\n",
    "  a: {typ: csv, pfad: x.csv, vollabgleich_tage: 7}\n",
    "  a: {typ: csv, pfad: x.csv, aktiv: false, unveraendert_ueberspringen: true, vollabgleich_tage: -1}\n",
], ids=["kein_wahrheitswert", "wfs", "geojson", "null_tage", "tage_bool", "tage_text", "tage_nan",
        "tage_ueberlauf", "tage_zu_gross", "tage_ohne_schalter", "abgeschaltet"])
def test_falsche_angaben_brechen_vor_dem_laden_ab(tmp_path, monkeypatch, zeile):
    """Wie zeitbudget_min: Ein Tippfehler bei Schalter oder vollabgleich_tage bricht den Lauf ab, bevor eine
    Verbindung aufgebaut wird, auch bei abgeschalteten Quellen. Über TAGE_HOECHST (36 500) ließe der Wert
    timedelta überlaufen (Nachprüfung durch Codex: 1e20 wurde angenommen und endete im OverflowError)."""
    monkeypatch.setattr(laden, "verbinden", lambda *a, **kw: pytest.fail("verbunden"))
    with pytest.raises(laden.KonfigFehler, match="Unveränderte Lieferung"):
        laden.lauf(_quellen_cfg(tmp_path, zeile), alle=True)


def test_gueltige_angaben_und_standard():
    """Gültig: Schalter true oder false, vollabgleich_tage eine Zahl über 0 (auch Bruchteile); Standard 7."""
    cfg = {"quellen": {"a": {"typ": "inkar", "unveraendert_ueberspringen": True, "vollabgleich_tage": 0.5},
                       "b": {"typ": "xlsx", "unveraendert_ueberspringen": False},
                       "c": {"typ": "wfs", "unveraendert_ueberspringen": False}}}
    assert unveraendert.konfig_fehler(cfg) == []
    # Die Obergrenze selbst ist gültig und rechnet ohne Überlauf
    hoechst = unveraendert.TAGE_HOECHST
    q = {"typ": "csv", "unveraendert_ueberspringen": True, "vollabgleich_tage": hoechst}
    assert unveraendert.konfig_fehler({"quellen": {"a": q}}) == []
    stand = {"datei_sha256": "a", "konfig_sha256": "f", "vollabgleich": JETZT}
    assert unveraendert.entscheiden(stand, "f", JETZT, hoechst, False, None, False) is None
    assert unveraendert.tage({}) == unveraendert.VOLLABGLEICH_STANDARD_TAGE == 7
    assert unveraendert.aktiv(cfg["quellen"]["a"]) and not unveraendert.aktiv(cfg["quellen"]["b"])
    assert not unveraendert.aktiv({"typ": "wfs", "unveraendert_ueberspringen": True})


def test_ausgelieferte_konfiguration_nur_inkar_mit_schalter():
    """E52: In config/quellen.yaml ist das Überspringen nur für INKAR eingeschaltet (der Fall mit 159,7 min im
    unveränderten Folgelauf), mit dem Standard von 7 Tagen; alle mitgelieferten Konfigurationen sind
    gültig."""
    import yaml
    ordner = Path(__file__).resolve().parent.parent / "config"
    cfg = yaml.safe_load((ordner / "quellen.yaml").read_text(encoding="utf-8"))
    an = [n for n, q in cfg["quellen"].items() if q.get("unveraendert_ueberspringen")]
    assert an == ["inkar_gemeinden"] and "vollabgleich_tage" not in cfg["quellen"]["inkar_gemeinden"]
    for datei in sorted(ordner.glob("*.yaml")):
        assert unveraendert.konfig_fehler(yaml.safe_load(datei.read_text(encoding="utf-8"))) == [], datei


# --- Prüfsumme im Protokoll und in den Adaptern ------------------------------------------------------

def test_datei_bereit_ohne_schalter_tut_nichts(tmp_path):
    """Ohne datei_pruefen (Quelle ohne Schalter) keine Prüfsumme, kein Lesen der Datei: Verhalten wie vor
    E52."""
    prot = Protokoll()
    prot.datei_bereit(pfad=tmp_path / "gibt-es-nicht")
    prot.datei_bereit(daten=b"x")
    assert prot.datei_sha256 is None and "datei_sha256" not in prot.info and not prot.datei_noch_gleich()


def test_datei_bereit_pruefsumme_ueberspringen_und_ersetzte_datei(tmp_path):
    """Bytes und Datei mit gleichem Inhalt ergeben dieselbe SHA-256; bei der erwarteten Prüfsumme folgt
    DateiUnveraendert; eine nach der Prüfsumme ersetzte Datei ist nicht mehr „noch gleich“."""
    daten = b"id,name\n1,a\n" * 100_000          # über einem Block (PRUEFSUMME_BLOCK)
    datei = tmp_path / "d.csv"
    datei.write_bytes(daten)
    a, b = Protokoll(), Protokoll()
    a.datei_pruefen = b.datei_pruefen = True
    a.datei_bereit(daten=daten)
    b.datei_bereit(pfad=datei)
    assert a.datei_sha256 == b.datei_sha256 == _sha(daten) == b.info["datei_sha256"]
    assert a.datei_noch_gleich() and b.datei_noch_gleich()
    datei.write_bytes(daten + b"2,b\n")
    assert not b.datei_noch_gleich()
    datei.unlink()
    assert not b.datei_noch_gleich()
    c = Protokoll()
    c.datei_pruefen, c.datei_erwartet = True, _sha(daten)
    with pytest.raises(DateiUnveraendert) as e:
        c.datei_bereit(daten=daten)
    assert e.value.sha256 == _sha(daten) and not isinstance(e.value, RuntimeError)
    c.datei_erwartet = "0" * 64
    c.datei_bereit(daten=daten)              # andere Prüfsumme: weiter, nur gemerkt


@pytest.mark.parametrize("wann", ["waehrend", "vor_dem_oeffnen"])
def test_datei_bereit_austausch_waehrend_der_pruefsumme_ueberspringt_nicht(tmp_path, monkeypatch, wann):
    """Nachprüfung durch Codex: Wird die Datei während der Prüfsumme atomar ersetzt (os.replace, wie ein
    Download, der fertig umbenannt wird), liest der offene Deskriptor noch die alte Datei A, der Pfad nennt
    schon die neue B. Die Prüfsumme ist dann die von A und gleich der erwarteten; übersprungen werden darf
    trotzdem nicht, sonst bliebe B unberücksichtigt und letzter_erfolg rückte vor. Ebenso, wenn der Austausch
    zwischen den Kennwerten und dem Öffnen liegt (dann liest der Deskriptor schon B). Erwartet: kein
    DateiUnveraendert, ein Hinweis, datei_noch_gleich False (also auch kein Vergleichsstand)."""
    alt = b"A" * (quellen.PRUEFSUMME_BLOCK + 10)       # zwei Blöcke: der Austausch liegt mitten im Lesen
    datei, neu = tmp_path / "inkar.zip", tmp_path / "inkar.zip.neu"
    datei.write_bytes(alt)
    neu.write_bytes(b"B" * len(alt))
    prot = _geschaltet(_sha(alt))
    getauscht = []

    def tauschen():
        """Ersetzt die Datei einmal atomar durch die neue."""
        if not getauscht:
            getauscht.append(True)
            neu.replace(datei)
    if wann == "waehrend":
        # zeit_pruefen läuft je Block, also nach dem Öffnen und vor dem Ende der Prüfsumme
        monkeypatch.setattr(prot, "zeit_pruefen", tauschen)
    else:
        # Austausch direkt nach den ersten Kennwerten, vor open()
        echt = Protokoll._kennwerte

        def kennwerte(pfad):
            """Erste Kennwerte wie immer, danach Austausch."""
            werte = echt(pfad)
            tauschen()
            return werte
        monkeypatch.setattr(Protokoll, "_kennwerte", staticmethod(kennwerte))
    prot.datei_bereit(pfad=datei)                       # kein DateiUnveraendert
    assert getauscht
    if wann == "waehrend":
        assert prot.datei_sha256 == _sha(alt)           # der Deskriptor las A, die Prüfsumme passte
    assert not prot.datei_noch_gleich()
    assert any("während der Prüfsumme geändert oder ersetzt" in h for h in prot.hinweise), prot.hinweise


def test_datei_bereit_prueft_das_zeitbudget(tmp_path):
    """Die Prüfsumme einer großen Datei zählt zum Zeitbudget (je Block ein Prüfpunkt)."""
    datei = tmp_path / "gross.zip"
    datei.write_bytes(b"\0" * (quellen.PRUEFSUMME_BLOCK + 1))
    prot = Protokoll()
    prot.datei_pruefen = True
    prot.frist_setzen(1, uhr=iter([0.0, 1e9, 1e9]).__next__)
    with pytest.raises(quellen.ZeitbudgetUeberschritten):
        prot.datei_bereit(pfad=datei)


def _geschaltet(erwartet: str | None = None) -> Protokoll:
    """Protokoll mit eingeschalteter Prüfsumme und der erwarteten Prüfsumme `erwartet`."""
    prot = Protokoll()
    prot.datei_pruefen, prot.datei_erwartet = True, erwartet
    return prot


CSV = "kreis;wert\r\n12051000;1\r\n12052000;2\r\n"


@pytest.mark.parametrize("art", ["abgelegt", "url"])
def test_csv_ueberspringt_vor_dem_lesen_und_liest_sonst_wie_bisher(tmp_path, monkeypatch, art):
    """CSV: Prüfsumme der Bytes, die gleich gelesen würden (abgelegt und per URL). Bei gleicher Prüfsumme kein
    Datensatz; sonst dieselben Datensätze wie ohne Schalter, auch mit \\r\\n als Zeilenende (seit E52 liest
    der Adapter Bytes statt Text)."""
    daten = CSV.encode("utf-8")
    if art == "abgelegt":
        (tmp_path / "t.csv").write_bytes(daten)
        pfad = str(tmp_path / "t.csv")
    else:
        pfad = "https://daten.example/t.csv"
        monkeypatch.setattr(quellen, "abrufen", lambda url, params, cfg, prot: daten)
    cfg = {"pfad": pfad, "trenner": ";", "id_spalte": "kreis", "gebiet": {"schluessel_spalte": "kreis"}}
    with pytest.raises(DateiUnveraendert):
        list(quellen.csv_quelle(cfg, _geschaltet(_sha(daten))))
    ohne = list(quellen.csv_quelle(cfg, Protokoll()))
    prot = _geschaltet("0" * 64)
    mit = list(quellen.csv_quelle(cfg, prot))
    assert ohne == mit and [d["objekt_id"] for d in mit] == ["12051000", "12052000"]
    assert prot.datei_sha256 == _sha(daten)


def test_xlsx_ueberspringt_vor_pruefung_und_openpyxl(tmp_path, monkeypatch, bericht):
    """XLSX: Prüfsumme der Datei vor xlsx_pruefen und openpyxl; bei gleicher Prüfsumme wird die Datei nicht
    geöffnet. Zwei Dateien mit gleichem Inhalt, aber neu geschrieben, haben andere Bytes (Zeitstempel im
    Dokument): Das führt zum Vollabgleich, nicht zum Überspringen (sichere Richtung)."""
    import openpyxl
    import yaml
    datei = bericht()
    q = yaml.safe_load((Path(__file__).resolve().parent.parent / "config" / "quellen.yaml").read_text(
        encoding="utf-8"))["quellen"]["bevoelkerung_gemeinden"]
    for k in ("seite", "datei_muster", "link_rechner"):
        q.pop(k)
    q["pfad"] = str(datei)
    prot = _geschaltet()
    assert len(list(quellen.xlsx(q, prot))) == 32 and prot.datei_sha256 == _sha(datei.read_bytes())
    monkeypatch.setattr(quellen, "xlsx_pruefen", lambda *a: pytest.fail("geprüft"))
    monkeypatch.setattr(openpyxl, "load_workbook", lambda *a, **kw: pytest.fail("geöffnet"))
    with pytest.raises(DateiUnveraendert):
        list(quellen.xlsx(q, _geschaltet(prot.datei_sha256)))


def test_inkar_ueberspringt_vor_dem_entpacken(tmp_path, monkeypatch):
    """INKAR: Prüfsumme des abgelegten ZIP, bevor unzip es liest; bei gleicher Prüfsumme wird nicht
    entpackt."""
    from test_neue_quellen import ZEILEN, _inkar_cfg, _inkar_zip
    ablage = _inkar_zip(tmp_path, ZEILEN)
    cfg = _inkar_cfg(tmp_path / "cache2", datei=str(ablage / "inkar_2025.zip"))
    prot = _geschaltet()
    assert list(quellen.inkar(cfg, prot))
    assert prot.datei_sha256 == _sha((ablage / "inkar_2025.zip").read_bytes())
    monkeypatch.setattr(quellen, "zip_zeilen", lambda *a: pytest.fail("entpackt"))
    with pytest.raises(DateiUnveraendert):
        list(quellen.inkar(cfg, _geschaltet(prot.datei_sha256)))


# --- Bericht und Aufruf --------------------------------------------------------------------------

def test_uebersprungene_quelle_ist_kein_vergleichsstand_fuer_die_feldliste(tmp_path):
    """Eine übersprungene Quelle wurde nicht gelesen, ihr Eintrag hat keine Feldliste; der Schemavergleich des
    nächsten Laufs nimmt den Eintrag davor (waechter.letzter_bericht)."""
    ordner = tmp_path / "berichte"
    ordner.mkdir()
    for lauf_id, eintrag in (("20261101T000000Z", {"status": "ok", "info": {"felder": ["a", "b"]}}),
                             ("20261102T000000Z", {"status": "ok", "info": {},
                                                   "uebersprungen": {"sha256": "a" * 64}})):
        (ordner / f"{lauf_id}.json").write_text(json.dumps(
            {"lauf_id": lauf_id, "quellen": [{"quelle": "q", **eintrag}]}), encoding="utf-8")
    assert waechter.letzter_bericht(ordner, "20261103T000000Z")["q"]["info"]["felder"] == ["a", "b"]


def test_schalter_vollabgleich_wird_weitergereicht(tmp_path, monkeypatch):
    """--vollabgleich kommt als vollabgleich=True bei lauf an, ohne den Schalter als False."""
    gesehen = []

    def lauf(*a, **kw):
        gesehen.append(kw.get("vollabgleich"))
        return {"lauf_id": "x", "laufzeit_s": 0, "quellen": [], "fehlgeschlagen": [], "angehalten": [],
                "unvollstaendig": []}
    monkeypatch.setattr(laden, "lauf", lauf)
    monkeypatch.setattr(laden.signal, "signal", lambda *a: None)
    for argumente, erwartet in ((["--vollabgleich"], True), ([], False)):
        monkeypatch.setattr(sys, "argv", ["pipeline.laden", "--config", str(tmp_path / "q.yaml"), *argumente])
        assert laden.main() == 0
        assert gesehen[-1] is erwartet
