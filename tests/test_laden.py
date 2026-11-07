"""Hilfsfunktionen des Laufs, ohne Datenbank.

pipeline.laden ist der Anfang von laden → quellen → ziel: Es liest die Konfiguration, nimmt die Sperren,
ruft je Quelle Adapter und Zielschreiben auf und schreibt Bericht, Karte, Verzeichnis und Meldungsentwürfe.
Die Tests ersetzen Datenbank (_Verbindung, _Cursor) und Quellen (_ok, _neu, …) durch Stellvertreter.
Abgesichert werden:
- --ziele für die Firewall und eindeutige Laufkennungen;
- ein technischer Abbruch hinterlässt einen Bericht, den --status sieht, soweit der Berichtsordner
  bekannt und beschreibbar ist (E34, E38), ohne den Bericht eines anderen Laufs anzufassen; ein zweiter
  Start bei belegter Sperre und eine unlesbare Konfiguration schreiben bewusst keinen;
- Rhythmus vorab prüfen (E24, E44) und Wiederholung nach einem unvollständigen Lauf (E38);
- Fehler einer Quelle, ihres Protokolls, Archivs oder Meldungsentwurfs treffen nur diese Quelle;
  eine abgerissene Verbindung wird einmal neu aufgebaut, ist die Datenbank ganz weg, endet der Lauf
  als technischer Abbruch (E44, E45);
- datenbankweite Sperre und Aktualisierung des Katalogs nach Läufen mit Änderungen (E46);
- `karte: false` und Hintergrundkarten, die Anzeige „unvollständig“ in Text und Karte und ein Hilfetext,
  der nicht mehr verspricht als der Code;
- seit E50: Freigabe gesperrter Rechner in Bericht, Protokoll und --ziele, Pflichtbericht vor den optionalen
  Ausgaben und bei jedem Abbruch mit den bisherigen Quellen, Zeitbudget und Leerlieferung in der Konfiguration
  bzw. auf der Kommandozeile.
"""
import contextlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from pipeline import betrieb, laden
from pipeline.laden import ziele


def test_ziele_fuer_die_firewall():
    """--ziele nennt je aktiver Quelle Rechner und Port (443 bei https ohne Angabe), sortiert; lokale Dateien
    und abgeschaltete Quellen brauchen keine Freigabe."""
    cfg = {"quellen": {
        "wfs": {"typ": "wfs", "url": "https://isk.geobasis-bb.de/ows/alkis_vereinf_wfs"},
        "csv_url": {"typ": "csv", "pfad": "https://example.org:8443/daten.csv"},
        "csv_lokal": {"typ": "csv", "pfad": "/app/beispiele/standorte.csv"},
        "aus": {"typ": "wfs", "url": "https://abgeschaltet.example", "aktiv": False}}}
    assert ziele(cfg) == ["example.org:8443", "isk.geobasis-bb.de:443"]


def test_zweiter_lauf_wartet_nicht_sondern_bricht_ab(tmp_path):
    """Timer und Handstart gleichzeitig: der zweite Start bricht mit klarer Meldung ab."""
    with laden.sperre(tmp_path), pytest.raises(laden.LaufLaeuftNoch), laden.sperre(tmp_path):
        pass
    with laden.sperre(tmp_path):  # danach wieder frei
        pass


def test_startzeit_vergibt_keine_kennung_doppelt(tmp_path):
    """Gibt es für die laufende Sekunde schon einen Bericht, vergibt startzeit eine spätere Kennung, statt den
    Bericht zu überschreiben."""
    belegt = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    (tmp_path / f"{belegt}.json").write_text("{}")
    assert laden.startzeit(tmp_path).strftime("%Y%m%dT%H%M%SZ") != belegt


def test_technischer_abbruch_hinterlaesst_bericht(tmp_path, monkeypatch):
    """Scheitert der Lauf technisch (hier keine Datenbank), entsteht trotzdem ein Bericht mit `abbruch`, und
    die Ausnahme geht weiter an den Aufrufer (E34)."""
    cfg = tmp_path / "quellen.yaml"
    cfg.write_text(f"berichte: {tmp_path / 'berichte'}\nquellen: {{}}\n", encoding="utf-8")

    def kaputt(*a, **kw):
        raise ConnectionError("Datenbank nicht erreichbar")

    monkeypatch.setattr(laden, "_lauf", kaputt)
    with pytest.raises(ConnectionError):
        laden.lauf(str(cfg))
    (datei,) = (tmp_path / "berichte").glob("2*.json")
    assert json.loads(datei.read_text())["abbruch"] == "ConnectionError: Datenbank nicht erreichbar"


# --- Technischer Abbruch und Wiederholung (Codex-Prüfung B6, E38) --------------------------------

class _Cursor:
    """Ersatz für einen psycopg-Cursor auf _Verbindung: merkt sich jede Anweisung und beantwortet die
    Abfragen, die ein Lauf ohne Quellen stellt (Metaschema und seine Spalten, offene Katalogaktualisierung,
    datenbankweite Sperre, Katalog), aus den Einstellungen der Verbindung."""
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, text, *a):
        self.conn.befehle.append(text)

    def fetchone(self):
        letzter = str(self.conn.befehle[-1])
        if "FROM pipeline_meta.katalog_offen" in letzter:
            return (self.conn.offen,)
        if "string_agg(pid" in letzter:
            return ("4711",)
        if "quellschluessel" in letzter:
            return (None if self.conn.meta_aktuell else ["aenderung.quellschluessel", "lauf.unvollstaendig"],)
        if "pg_try_advisory_lock" in letzter:
            return (self.conn.sperre_frei,)
        if letzter == "SELECT pipeline_meta.katalog_aktualisieren()":
            return (self.conn.katalog,)
        return (self.conn.meta,)


class _Verbindung:
    """Ersatz für die Datenbank: genug für einen Lauf ohne Quellen."""

    def __init__(self, meta=True, meta_aktuell=True, sperre_frei=True, katalog="fehlt", offen=None):
        self.meta, self.meta_aktuell, self.befehle = meta, meta_aktuell, []
        self.sperre_frei, self.katalog, self.offen = sperre_frei, katalog, offen

    def cursor(self):
        return _Cursor(self)

    def rollback(self):
        pass

    @contextlib.contextmanager
    def transaction(self):
        yield


def _cfg(tmp_path, zusatz="") -> str:
    """Schreibt eine Konfiguration ohne Quellen mit Berichtsordner in tmp_path, ergänzt um `zusatz` (YAML),
    und gibt ihren Pfad zurück."""
    datei = tmp_path / "quellen.yaml"
    datei.write_text(f"berichte: {tmp_path / 'berichte'}\nquellen: {{}}\n{zusatz}", encoding="utf-8")
    return str(datei)


def _main(monkeypatch, *argumente) -> int:
    """Ruft laden.main mit den Argumenten auf, ohne Signal-Handler im Testprozess zu hinterlassen, und gibt
    den Rückgabewert zurück."""
    monkeypatch.setattr(sys, "argv", ["pipeline.laden", *argumente])
    monkeypatch.setattr(laden.signal, "signal", lambda *a: None)   # Handler nicht im Testprozess lassen
    return laden.main()


def _status(tmp_path):
    """--status über den Berichtsordner des Tests, mit einer Grenze von 26 h."""
    return betrieb.status(tmp_path / "berichte", 26)


def test_fehlendes_metaschema_hinterlaesst_bericht(tmp_path, monkeypatch, capsys):
    """Vorher SystemExit ohne Bericht; --status meldete weiter den letzten guten Lauf."""
    monkeypatch.setattr(laden, "verbinden", lambda *a, **kw: contextlib.nullcontext(_Verbindung(meta=False)))
    assert _main(monkeypatch, "--config", _cfg(tmp_path)) == laden.ABBRUCH
    assert "pipeline_meta fehlt" in capsys.readouterr().err
    code, zeile = _status(tmp_path)
    assert code == betrieb.KRITISCH and "MetaFehlt" in zeile


def test_altes_metaschema_ohne_quellschluessel_klare_meldung(tmp_path, monkeypatch, capsys):
    """E40: Register und Änderungsprotokoll führen den Quellschlüssel. Ist pipeline_meta älter (einrichten
    seit dem Update nicht ausgeführt), bricht der Lauf mit klarer Meldung und Bericht ab, statt je Quelle
    an einer fehlenden Spalte zu scheitern."""
    monkeypatch.setattr(laden, "verbinden",
                        lambda *a, **kw: contextlib.nullcontext(_Verbindung(meta_aktuell=False)))
    assert _main(monkeypatch, "--config", _cfg(tmp_path)) == laden.ABBRUCH
    assert "Spalten fehlen: aenderung.quellschluessel, lauf.unvollstaendig" in capsys.readouterr().err
    code, zeile = _status(tmp_path)
    assert code == betrieb.KRITISCH and "MetaFehlt" in zeile


def test_sperrdatei_nicht_anlegbar_hinterlaesst_bericht(tmp_path, monkeypatch):
    """Lässt sich die Sperrdatei nicht anlegen, endet der Lauf mit der Ausnahme, hinterlässt aber einen
    Abbruchbericht, den --status als CRITICAL meldet (E34)."""
    @contextlib.contextmanager
    def gesperrt(ordner):
        raise PermissionError(f"{ordner}/.lauf.sperre: Permission denied")
        yield

    monkeypatch.setattr(laden, "sperre", gesperrt)
    with pytest.raises(PermissionError):
        laden.lauf(_cfg(tmp_path))
    code, zeile = _status(tmp_path)
    assert code == betrieb.KRITISCH and "PermissionError" in zeile


def test_signal_hinterlaesst_bericht(tmp_path, monkeypatch):
    """SIGTERM (etwa Timeout von systemd) kommt als Beendet, keine Exception: die Fehlerbehandlung
    je Quelle fängt es nicht ab, der Lauf schreibt den Abbruch und endet."""
    def beendet(*a, **kw):
        laden._beenden(laden.signal.SIGTERM, None)

    monkeypatch.setattr(laden, "_lauf", beendet)
    assert not issubclass(laden.Beendet, Exception)
    assert _main(monkeypatch, "--config", _cfg(tmp_path)) == laden.ABBRUCH
    code, zeile = _status(tmp_path)
    assert code == betrieb.KRITISCH and "durch Signal SIGTERM beendet" in zeile


def test_abbruch_nach_dem_bericht_wird_nachgetragen(tmp_path):
    """Bricht der Lauf erst nach seinem Bericht ab (etwa beim Quellenverzeichnis), meldete --status
    sonst OK."""
    ordner = tmp_path / "berichte"
    ordner.mkdir()
    jetzt = datetime(2026, 11, 5, 7, 0, tzinfo=UTC)
    (ordner / "20261105T070000Z.json").write_text(json.dumps({"lauf_id": "20261105T070000Z", "quellen": [
        {"quelle": "q", "status": "ok"}]}), encoding="utf-8")
    assert laden.abbruch_melden(ordner, jetzt, False, OSError("Platte voll"))
    b = json.loads((ordner / "20261105T070000Z.json").read_text(encoding="utf-8"))
    assert b["abbruch"] == "OSError: Platte voll" and b["quellen"][0]["quelle"] == "q"


def test_abbruch_vor_der_sperre_laesst_fremden_bericht_unberuehrt(tmp_path, monkeypatch):
    """Vor der Sperre ist die Startzeit nicht eindeutig (startzeit() lief noch nicht oder schlief
    gerade): ein Bericht derselben Sekunde gehört einem anderen, eben beendeten Lauf und bekommt
    keinen Abbruch nachgetragen (Prüfung zu E38)."""
    @contextlib.contextmanager
    def gesperrt(ordner):
        raise PermissionError(f"{ordner}/.lauf.sperre: Permission denied")
        yield

    ordner = tmp_path / "berichte"
    ordner.mkdir()
    jetzt = datetime.now(UTC)
    fremd = {}
    for s in range(-1, 4):   # diese Sekunde und die nächsten, falls der Test über eine Grenze läuft
        lid = datetime.fromtimestamp(int(jetzt.timestamp()) + s, UTC).strftime("%Y%m%dT%H%M%SZ")
        datei = ordner / f"{lid}.json"
        datei.write_text(json.dumps({"lauf_id": lid, "quellen": [{"quelle": "q", "status": "ok"}]}),
                         encoding="utf-8")
        fremd[datei] = datei.read_bytes()
    monkeypatch.setattr(laden, "sperre", gesperrt)
    with pytest.raises(PermissionError):
        laden.lauf(_cfg(tmp_path))
    for datei, inhalt in fremd.items():
        assert datei.read_bytes() == inhalt, datei.name
    assert sorted(ordner.glob("2*.json")) == sorted(fremd)
    # ohne fremden Bericht in dieser Sekunde schreibt derselbe Abbruch weiterhin seinen eigenen
    for datei in fremd:
        datei.unlink()
    with pytest.raises(PermissionError):
        laden.lauf(_cfg(tmp_path))
    code, zeile = _status(tmp_path)
    assert code == betrieb.KRITISCH and "PermissionError" in zeile


def test_abbruch_nachtragen_nur_auf_wunsch(tmp_path):
    """Mit nachtragen=False bleibt ein vorhandener Bericht derselben Kennung unberührt (Rückgabe None); ein
    Probelauf schreibt in seine eigene Datei und ist davon nicht betroffen."""
    jetzt = datetime(2026, 11, 5, 7, 0, tzinfo=UTC)
    datei = tmp_path / "20261105T070000Z.json"
    datei.write_text('{"lauf_id": "20261105T070000Z", "quellen": []}', encoding="utf-8")
    assert laden.abbruch_melden(tmp_path, jetzt, False, OSError("x"), nachtragen=False) is None
    assert "abbruch" not in json.loads(datei.read_text(encoding="utf-8"))
    assert laden.abbruch_melden(tmp_path, jetzt, True, OSError("x"), nachtragen=False)   # Probelauf: frei


def test_kaputte_konfiguration_klare_meldung_ohne_bericht(tmp_path, monkeypatch, capsys):
    """Ohne lesbare Konfiguration ist der Berichtsordner unbekannt: Meldung auf stderr, Rückgabe 2."""
    datei = tmp_path / "quellen.yaml"
    datei.write_text("quellen: [\n", encoding="utf-8")
    assert _main(monkeypatch, "--config", str(datei)) == laden.ABBRUCH
    assert "nicht lesbar" in capsys.readouterr().err
    assert _main(monkeypatch, "--config", str(tmp_path / "fehlt.yaml")) == laden.ABBRUCH
    assert _main(monkeypatch, "--config", str(tmp_path / "fehlt.yaml"), "--status") == betrieb.UNBEKANNT


def test_berichtsordner_nicht_anlegbar_klare_meldung(tmp_path, monkeypatch, capsys):
    """Ist der Berichtsordner nicht anlegbar (eine Datei steht im Weg), endet main mit Rückgabe 2 und einer
    Meldung, die den Berichtsordner nennt."""
    (tmp_path / "berichte").write_text("eine Datei, kein Ordner", encoding="utf-8")
    assert _main(monkeypatch, "--config", _cfg(tmp_path)) == laden.ABBRUCH
    assert "Berichtsordner" in capsys.readouterr().err


def test_zweiter_start_schreibt_keinen_abbruchbericht(tmp_path):
    """Der laufende Lauf schreibt seinen Bericht selbst; ein jüngerer Abbruchbericht des zweiten
    Starts würde ihn in --status verdecken."""
    (tmp_path / "berichte").mkdir()
    with laden.sperre(tmp_path / "berichte"), pytest.raises(laden.LaufLaeuftNoch):
        laden.lauf(_cfg(tmp_path))
    assert not list((tmp_path / "berichte").glob("2*.json"))


def test_karte_false_schreibt_keine_karte(tmp_path, monkeypatch):
    """Mit `karte: false` entsteht keine Kartendatei und kein Verweis im Bericht; ohne die Einstellung liegt
    die Karte neben dem Bericht."""
    monkeypatch.setattr(laden, "verbinden", lambda *a, **kw: contextlib.nullcontext(_Verbindung()))
    b = laden.lauf(_cfg(tmp_path, "karte: false\n"))
    assert "karte" not in b and not list((tmp_path / "berichte").glob("*-karte.html"))
    b = laden.lauf(_cfg(tmp_path))
    assert (tmp_path / "berichte" / b["karte"]).exists()


def test_karte_false_liest_keine_kartenobjekte(tmp_path, monkeypatch):
    """`karte: false` oben: die Kartenabfrage (bis zu 20 000 Objekte als GeoJSON) läuft gar nicht
    erst, statt gelesen und danach verworfen zu werden (Prüfung zu E38)."""
    uebergeben = []

    def laden_ersatz(conn, name, qcfg, lauf_id, jetzt, prot, vorher, probelauf, kartenobjekte, **kw):
        """Ersatz für quelle_laden: merkt sich, was als kartenobjekte übergeben wurde, und meldet die Quelle
        ohne Änderung als ok."""
        uebergeben.append(kartenobjekte)
        zaehler = ("gelesen", "neu", "geaendert", "unveraendert", "geloescht", "uebernommen",
                   "zurueckgehalten")
        return {"status": "ok", "zaehler": dict.fromkeys(zaehler, 0)}

    monkeypatch.setattr(laden, "verbinden", lambda *a, **kw: contextlib.nullcontext(_Verbindung()))
    monkeypatch.setattr(laden, "quelle_laden", laden_ersatz)
    quelle = "quellen: {q: {typ: csv, pfad: x.csv}}\n"
    for zusatz, erwartet in (("karte: false\n", None), ("", {})):
        datei = tmp_path / "quellen.yaml"
        datei.write_text(f"berichte: {tmp_path / 'berichte'}\n{quelle}{zusatz}", encoding="utf-8")
        uebergeben.clear()
        laden.lauf(str(datei), alle=True, probelauf=True)
        assert uebergeben == [erwartet]


def test_falscher_hintergrund_bricht_vor_dem_laden_ab(tmp_path, monkeypatch):
    """Eine unbekannte Hintergrundkarte bricht den Lauf mit ValueError ab, die Meldung nennt
    karte.hintergrund."""
    monkeypatch.setattr(laden, "verbinden", lambda *a, **kw: contextlib.nullcontext(_Verbindung()))
    with pytest.raises(ValueError, match="karte.hintergrund"):
        laden.lauf(_cfg(tmp_path, "karte: {hintergrund: [osm]}\n"))


def test_wiederholung_nach_unvollstaendigem_lauf():
    """Ein erzwungener, unvollständiger Lauf nach einem jungen Erfolg: die Quelle ist sofort wieder
    fällig, statt bis zum nächsten Termin auf dem lückenhaften Stand zu bleiben."""
    erfolg = datetime(2026, 11, 1, 7, 0, 0, 512000, tzinfo=UTC)
    assert laden.rhythmus_basis(erfolg, "20261101T070000Z") == erfolg       # derselbe Lauf
    assert laden.rhythmus_basis(erfolg, "20261105T080000Z") is None         # später, unvollständig
    assert laden.rhythmus_basis(None, "20261105T080000Z") is None
    assert laden.rhythmus_basis(erfolg, None) == erfolg
    assert laden.naechster_termin("monatlich", laden.rhythmus_basis(erfolg, "20261105T080000Z")) is None


def test_hinweis_wiederholung_nur_wenn_sonst_nicht_faellig():
    """Der Hinweis „Wiederholung“ nur, wenn die Quelle ohne ihn „nicht fällig“ gewesen wäre: nicht
    ohne Rhythmus und nicht, wenn ihr Termin ohnehin abgelaufen ist (Prüfung zu E38)."""
    jetzt = datetime(2026, 11, 5, 8, 0, tzinfo=UTC)
    vorgestern = datetime(2026, 11, 3, 8, 0, tzinfo=UTC)
    assert laden.nur_wegen_wiederholung("monatlich", None, vorgestern, jetzt)
    assert not laden.nur_wegen_wiederholung("taeglich", None, vorgestern, jetzt)   # ohnehin fällig
    assert not laden.nur_wegen_wiederholung(None, None, vorgestern, jetzt)          # ohne Rhythmus
    assert not laden.nur_wegen_wiederholung("monatlich", vorgestern, vorgestern, jetzt)  # vollständig
    assert not laden.nur_wegen_wiederholung("monatlich", None, None, jetzt)         # nie erfolgreich
    assert not laden.nur_wegen_wiederholung("unbekannt", None, vorgestern, jetzt)


# --- Code-Review 05.11. nach E43 (E44) ----------------------------------------------------------------

def _quellen_cfg(tmp_path, quellen: str) -> str:
    """Schreibt eine Konfiguration mit Berichtsordner und den Quellen aus `quellen` (YAML, eingerückt unter
    quellen:) und gibt ihren Pfad zurück."""
    datei = tmp_path / "quellen.yaml"
    datei.write_text(f"berichte: {tmp_path / 'berichte'}\nquellen:\n{quellen}", encoding="utf-8")
    return str(datei)


def _ok(*a, **kw):
    """Ersatz für quelle_laden: Quelle ok, alle Zähler 0 (keine Änderung)."""
    zaehler = ("gelesen", "neu", "geaendert", "unveraendert", "geloescht", "uebernommen", "zurueckgehalten")
    return {"status": "ok", "zaehler": dict.fromkeys(zaehler, 0)}


def test_unbekannter_rhythmus_bricht_vor_dem_laden_ab(tmp_path, monkeypatch):
    """F1: Ein Tippfehler im Rhythmus fiel erst nach dem ersten Erfolg der Quelle auf, dann aber als
    Abbruch des ganzen Laufs. Jetzt prüft der Lauf alle Quellen vorab, auch abgeschaltete, und bricht
    mit klarer Meldung und Abbruchbericht ab, bevor er die Datenbank anspricht."""
    def nicht_verbinden(*a, **kw):
        raise AssertionError("Datenbank darf nicht angesprochen werden")

    monkeypatch.setattr(laden, "verbinden", nicht_verbinden)
    for quellen in ("  a: {typ: csv, pfad: x.csv, rhythmus: monatlch}\n  b: {typ: csv, pfad: y.csv}\n",
                    "  a: {typ: csv, pfad: x.csv}\n"
                    "  b: {typ: csv, pfad: y.csv, aktiv: false, rhythmus: 7}\n"):
        cfg = _quellen_cfg(tmp_path, quellen)
        with pytest.raises(laden.KonfigFehler, match=r"Unbekannter Rhythmus .* \((a|b)\)"):
            laden.lauf(cfg, nur="a")
    bericht = json.loads(sorted((tmp_path / "berichte").glob("2*.json"))[-1].read_text())
    assert "KonfigFehler" in bericht["abbruch"] and "erlaubt: taeglich" in bericht["abbruch"]
    # Rückgabe 2 und CRITICAL über den bestehenden Abbruchpfad, hier ausdrücklich geprüft (E45)
    assert _main(monkeypatch, "--config", cfg) == laden.ABBRUCH
    code, zeile = _status(tmp_path)
    assert code == betrieb.KRITISCH and "Unbekannter Rhythmus" in zeile


@pytest.mark.parametrize("wert", ["false", "0", "''", "[]", "{}", "1", "true", "[monatlich]"])
def test_rhythmus_falsche_werte_auch_wenn_leer_gelesen(wert):
    """Pre-existing (E45): Werte, die Python als falsch liest (false, 0, '', []), kamen ohne Meldung
    durch und hießen wie ein fehlender Rhythmus „bei jedem Lauf“. Nur ein fehlender oder leerer Eintrag
    (None) ist erlaubt."""
    import yaml
    cfg = {"quellen": {"a": yaml.safe_load(f"{{typ: csv, pfad: x.csv, rhythmus: {wert}}}")}}
    with pytest.raises(laden.KonfigFehler, match=r"Unbekannter Rhythmus '.*' \(a\)"):
        laden.rhythmen_pruefen(cfg)


def test_rhythmus_fehlend_oder_leer_ist_erlaubt():
    """Ohne Rhythmus, mit leerem Eintrag (None) oder mit gültigem Rhythmus besteht die Vorabprüfung ohne
    Ausnahme."""
    laden.rhythmen_pruefen({"quellen": {"a": {"typ": "csv"}, "b": {"typ": "csv", "rhythmus": None},
                                        "c": {"typ": "csv", "rhythmus": "monatlich"}}})


def test_faelligkeit_je_quelle_abgefangen(tmp_path, monkeypatch):
    """F1/F5: Scheitert die Fälligkeitsprüfung einer Quelle (etwa beim Lesen von quellenstand), ist nur
    diese Quelle fehlgeschlagen; die anderen laufen, und der reguläre Bericht entsteht."""
    def erfolg(conn, name):
        if name == "a":
            raise RuntimeError("quellenstand nicht lesbar")
        return None, None

    monkeypatch.setattr(laden, "verbinden", lambda *a, **kw: contextlib.nullcontext(_Verbindung()))
    monkeypatch.setattr(laden, "letzter_erfolg", erfolg)
    monkeypatch.setattr(laden, "quelle_laden", _ok)
    b = laden.lauf(_quellen_cfg(tmp_path, "  a: {typ: csv, pfad: x.csv, rhythmus: monatlich}\n"
                                          "  b: {typ: csv, pfad: y.csv, rhythmus: monatlich}\n"))
    a, bq = b["quellen"]
    assert a["status"] == "fehler" and "quellenstand nicht lesbar" in a["fehler"] and bq["status"] == "ok"
    assert b["fehlgeschlagen"] == ["a"] and (tmp_path / "berichte" / f"{b['lauf_id']}.json").exists()


class _Getrennt(RuntimeError):
    """Ersatz für psycopg.OperationalError bei abgerissener Verbindung."""


def test_abgerissene_verbindung_wird_neu_aufgebaut(tmp_path, monkeypatch):
    """F5: Reißt beim Fehler einer Quelle die Datenbankverbindung ab, liefen protokollieren() und der
    Rest des Laufs auf der toten Verbindung: Abbruch ohne regulären Bericht. Jetzt baut der Lauf die
    Verbindung neu auf, führt die Quelle als fehlgeschlagen und schreibt den Bericht."""
    verbindungen = []

    class Verbindung(_Verbindung):
        closed = broken = False

        def cursor(self):
            if self.closed:
                raise _Getrennt("the connection is closed")
            return super().cursor()

    def verbinden(*a, **kw):
        verbindungen.append(Verbindung())
        return contextlib.nullcontext(verbindungen[-1])

    def quelle(conn, name, *a, **kw):
        if name == "a":
            conn.closed = conn.broken = True
            raise _Getrennt("server closed the connection unexpectedly")
        return _ok()

    monkeypatch.setattr(laden, "verbinden", verbinden)
    monkeypatch.setattr(laden, "quelle_laden", quelle)
    b = laden.lauf(_quellen_cfg(tmp_path, "  a: {typ: csv, pfad: x.csv}\n  b: {typ: csv, pfad: y.csv}\n"),
                   alle=True)
    a, bq = b["quellen"]
    assert a["status"] == "fehler" and "server closed" in a["fehler"] and bq["status"] == "ok"
    assert len(verbindungen) == 2 and (tmp_path / "berichte" / f"{b['lauf_id']}.json").exists()
    neu = " ".join(map(str, verbindungen[1].befehle))
    assert neu.count("pipeline_meta.quellenlauf") == 2 and "pipeline_meta.lauf " in neu


def test_protokoll_nicht_schreibbar_wird_warnung(tmp_path, monkeypatch):
    """F5: Scheitert nur das Protokoll einer erfolgreichen Quelle, sind ihre Daten schon übernommen;
    sie bleibt ok (wie in quellenstand und Zieltabelle) und bekommt eine Warnung."""
    def protokoll(conn, lauf_id, eintrag):
        if eintrag["quelle"] == "a":
            raise RuntimeError("quellenlauf gesperrt")

    monkeypatch.setattr(laden, "verbinden", lambda *a, **kw: contextlib.nullcontext(_Verbindung()))
    monkeypatch.setattr(laden, "quelle_laden", _ok)
    monkeypatch.setattr(laden, "protokollieren", protokoll)
    b = laden.lauf(_quellen_cfg(tmp_path, "  a: {typ: csv, pfad: x.csv}\n  b: {typ: csv, pfad: y.csv}\n"),
                   alle=True)
    a, bq = b["quellen"]
    assert a["status"] == "ok" and any("quellenlauf gesperrt" in w for w in a["warnungen"])
    assert bq["status"] == "ok" and not bq["warnungen"]


def test_unvollstaendig_in_text_und_karte(tmp_path):
    """F4: Eine unvollständige Quelle stand in Textbericht, Konsole und Karte als „ok“, während
    Verzeichnis, pipeline_meta, --status und --kennzahlen „unvollständig“ zeigten. Der JSON-Bericht
    bleibt (status ok, unvollstaendig true), auch ältere Berichte lesen sich so."""
    from pipeline import karte, sprache
    z = {"neu": 1, "geaendert": 2, "geloescht": 0, "unveraendert": 3}
    b = {"lauf_id": "20261105T120000Z", "laufzeit_s": 1.0, "quellen": [
        {"quelle": "voll", "status": "ok", "zaehler": z, "unvollstaendig": False},
        {"quelle": "luecke", "status": "ok", "zaehler": z, "unvollstaendig": True}]}
    sprache.texte.cache_clear()
    de, en = laden.zusammenfassung(b), laden.zusammenfassung({**b, "sprache": "en"})
    assert "voll                     ok     neu     1" in de
    assert "luecke                   UNVOLLSTÄNDIG neu     1" in de and "wird wiederholt" in de
    assert "luecke                   INCOMPLETE new     1" in en
    datei = tmp_path / "k.html"
    karte.schreiben(datei, b, {})
    html = datei.read_text(encoding="utf-8")
    daten = json.loads(html.split('<script id="daten" type="application/json">')[1].split("</script>")[0])
    assert [q["status"] for q in daten["quellen"]] == ["ok", "unvollstaendig"]
    texte = json.loads(html.split('<script id="texte" type="application/json">')[1].split("</script>")[0])
    assert texte["status"]["unvollstaendig"] == "unvollständig"
    assert 'q.status === "ok" || q.status === "unvollstaendig"' in html


def test_laufzeile_nicht_schreibbar_bericht_mit_allen_quellen(tmp_path, monkeypatch):
    """F5: Scheitert die Zeile in pipeline_meta.lauf, schrieb der Lauf bisher nur einen leeren
    Abbruchbericht. Jetzt steht der Bericht mit allen Quellen, `abbruch` ist nachgetragen."""
    class Verbindung(_Verbindung):
        def cursor(self):
            cur = super().cursor()
            ausfuehren = cur.execute

            def execute(text, *a):
                if "pipeline_meta.lauf " in str(text):
                    raise RuntimeError("pipeline_meta.lauf gesperrt")
                return ausfuehren(text, *a)

            cur.execute = execute
            return cur

    monkeypatch.setattr(laden, "verbinden", lambda *a, **kw: contextlib.nullcontext(Verbindung()))
    monkeypatch.setattr(laden, "quelle_laden", _ok)
    with pytest.raises(RuntimeError, match="gesperrt"):
        laden.lauf(_quellen_cfg(tmp_path, "  a: {typ: csv, pfad: x.csv}\n  b: {typ: csv, pfad: y.csv}\n"),
                   alle=True)
    (datei,) = (tmp_path / "berichte").glob("2*.json")
    b = json.loads(datei.read_text())
    assert [q["quelle"] for q in b["quellen"]] == ["a", "b"] and "gesperrt" in b["abbruch"]
    # Textbericht und Karte zeigen den Abbruch wie das JSON (E45); vorher stand dort ein normaler Lauf
    text = datei.with_suffix(".txt").read_text()
    seite = (datei.parent / f"{datei.stem}-karte.html").read_text()
    assert "TECHNISCH ABGEBROCHEN: RuntimeError: pipeline_meta.lauf gesperrt" in text
    assert "Lauf technisch abgebrochen: RuntimeError" in seite


# --- Zweite Prüfrunde zum Code-Review (E45) -------------------------------------------------------

def _geaendert(*a, **kw):
    """Ersatz für quelle_laden: Quelle ok mit einem neuen Objekt, also mit Änderungen (Archiv und Katalog
    werden fällig)."""
    b = _ok()
    b["zaehler"]["neu"] = 1
    return b


def test_archiv_nicht_schreibbar_bericht_mit_allen_quellen(tmp_path, monkeypatch):
    """Stand-Archiv und Meldungsentwurf standen außerhalb der Fehlerbehandlung je Quelle: Scheiterte das
    Archiv einer erfolgreichen Quelle (Platte voll), endete der Lauf mit einem Abbruchbericht ohne Quellen,
    und die übrigen liefen nicht. Jetzt bleibt sie ok mit Warnung (auch im Protokoll), die nächste läuft."""
    protokolle = []

    def archiv(conn, ordner, lauf_id, name, z):
        raise OSError("Platte voll")

    monkeypatch.setattr(laden, "verbinden", lambda *a, **kw: contextlib.nullcontext(_Verbindung()))
    monkeypatch.setattr(laden, "quelle_laden", _geaendert)
    monkeypatch.setattr(laden.betrieb, "archiv_schreiben", archiv)
    monkeypatch.setattr(laden.ziel, "aus_konfiguration", lambda name, q: None)
    monkeypatch.setattr(laden, "protokollieren", lambda conn, lid, e: protokolle.append(json.dumps(e)))
    cfg = _quellen_cfg(tmp_path, "  a: {typ: csv, pfad: x.csv}\n  b: {typ: csv, pfad: y.csv}\n")
    Path(cfg).write_text(Path(cfg).read_text() + "archiv: true\n")
    b = laden.lauf(cfg, alle=True)
    assert [(q["quelle"], q["status"]) for q in b["quellen"]] == [("a", "ok"), ("b", "ok")]
    assert all(any("Stand-Archiv nicht geschrieben: OSError: Platte voll" in w for w in q["warnungen"])
               for q in b["quellen"])
    assert "abbruch" not in b and all("Platte voll" in p for p in protokolle) and len(protokolle) == 2


def test_meldungsentwurf_nicht_schreibbar_wird_warnung(tmp_path, monkeypatch):
    """Lässt sich der Meldungsentwurf einer fehlgeschlagenen Quelle nicht schreiben, bekommt sie eine Warnung
    statt eines Verweises, und die nächste Quelle läuft weiter (E45)."""
    def quelle(conn, name, *a, **kw):
        if name == "a":
            raise RuntimeError("Dienst antwortet nicht")
        return _ok()

    echt = laden.verzeichnis.schreiben

    def schreiben(datei, text):
        if "-meldung-" in datei.name:
            raise OSError("Platte voll")
        return echt(datei, text)

    monkeypatch.setattr(laden, "verbinden", lambda *a, **kw: contextlib.nullcontext(_Verbindung()))
    monkeypatch.setattr(laden, "quelle_laden", quelle)
    monkeypatch.setattr(laden.verzeichnis, "schreiben", schreiben)
    b = laden.lauf(_quellen_cfg(tmp_path, "  a: {typ: csv, pfad: x.csv}\n  b: {typ: csv, pfad: y.csv}\n"),
                   alle=True)
    a, bq = b["quellen"]
    assert a["status"] == "fehler" and "meldung" not in a and bq["status"] == "ok"
    assert any("Meldungsentwurf nicht geschrieben: OSError" in w for w in a["warnungen"])


def test_datenbank_ganz_weg_bricht_ab_mit_bisherigen_quellen(tmp_path, monkeypatch):
    """Ist die Datenbank ganz weg und scheitert auch der Neuaufbau, lief der Lauf alle übrigen Quellen
    durch: alle „fehler“, auch eine nicht fällige, je ein Meldungsentwurf an den Anbieter, Verzeichnis
    überschrieben. Jetzt endet er als technischer Abbruch: Bericht mit den Quellen bis dahin plus
    `abbruch`, ein einziger Versuch des Neuaufbaus, keine Meldungsentwürfe für b und c, beide unberührt
    im Verzeichnis."""
    versuche = []

    class Verbindung(_Verbindung):
        closed = broken = False

    def verbinden(*a, **kw):
        versuche.append(kw)
        if len(versuche) > 1:
            raise ConnectionRefusedError("connection refused")
        return contextlib.nullcontext(Verbindung())

    def quelle(conn, name, *a, **kw):
        conn.closed = conn.broken = True
        raise _Getrennt("server closed the connection unexpectedly")

    monkeypatch.setattr(laden, "verbinden", verbinden)
    monkeypatch.setattr(laden, "quelle_laden", quelle)
    monkeypatch.setattr(laden, "letzter_erfolg", lambda conn, name: (None, None))
    cfg = _quellen_cfg(tmp_path, "  a: {typ: csv, pfad: x.csv}\n"
                                 "  b: {typ: csv, pfad: y.csv, rhythmus: monatlich}\n"
                                 "  c: {typ: csv, pfad: z.csv}\n")
    assert _main(monkeypatch, "--config", cfg) == laden.ABBRUCH
    assert len(versuche) == 2 and versuche[1]["connect_timeout"] == laden.VERBINDUNG_TIMEOUT_S
    ordner = tmp_path / "berichte"
    (datei,) = ordner.glob("2*[0-9]Z.json")
    b = json.loads(datei.read_text())
    assert [(q["quelle"], q["status"]) for q in b["quellen"]] == [("a", "fehler")]
    assert b["abbruch"].startswith("DatenbankWeg: Datenbankverbindung abgerissen, Neuaufbau gescheitert")
    assert any("quellenlauf nicht geschrieben: DatenbankWeg" in w for w in b["quellen"][0]["warnungen"])
    # Meldungsentwurf nur für a, die wirklich fehlgeschlagen ist (wie bei jedem Fehler einer Quelle)
    assert [p.name for p in ordner.glob("*-meldung-*")] == [f"{b['lauf_id']}-meldung-a.txt"]
    assert "TECHNISCH ABGEBROCHEN" in datei.with_suffix(".txt").read_text()
    assert set(json.loads((ordner / "quellenverzeichnis.json").read_text())) == {"a"}
    assert _status(tmp_path)[0] == betrieb.KRITISCH


@pytest.mark.parametrize("wo", ["faelligkeit", "laufzeile"])
def test_verbindung_im_leerlauf_gestorben(tmp_path, monkeypatch, wo):
    """`closed`/`broken` setzt psycopg erst nach einem gescheiterten Zugriff. Starb die Verbindung im
    Leerlauf, scheiterte die nächste Quelle an ihrer Fälligkeit (fehler, Meldungsentwurf), obwohl sie in
    Ordnung war, bzw. die Laufzeile. Jetzt findet der Lebenstest das vorher und baut neu auf (E45).
    Ohne --alle, damit die Fälligkeit wirklich geprüft wird."""
    verbindungen = []

    class Verbindung(_Verbindung):
        closed = broken = False
        tot = False

        def cursor(self):
            if self.tot:   # wie psycopg: erst der Zugriff merkt es, danach ist sie geschlossen
                self.closed = True
                raise _Getrennt("terminating connection due to administrator command")
            return super().cursor()

    def verbinden(*a, **kw):
        verbindungen.append(Verbindung())
        return contextlib.nullcontext(verbindungen[-1])

    def protokoll(conn, lauf_id, eintrag):
        conn.befehle.append(f"pipeline_meta.quellenlauf {eintrag['quelle']}")
        if eintrag["quelle"] == ("a" if wo == "faelligkeit" else "b"):
            conn.tot = True   # stirbt danach im Leerlauf

    monkeypatch.setattr(laden, "verbinden", verbinden)
    monkeypatch.setattr(laden, "quelle_laden", _ok)
    monkeypatch.setattr(laden, "letzter_erfolg", lambda conn, name: (None, None))
    monkeypatch.setattr(laden, "protokollieren", protokoll)
    b = laden.lauf(_quellen_cfg(tmp_path, "  a: {typ: csv, pfad: x.csv, rhythmus: monatlich}\n"
                                          "  b: {typ: csv, pfad: y.csv, rhythmus: monatlich}\n"))
    assert [(q["quelle"], q["status"]) for q in b["quellen"]] == [("a", "ok"), ("b", "ok")]
    assert not any(q.get("warnungen") for q in b["quellen"]) and "abbruch" not in b
    assert len(verbindungen) == 2 and not list((tmp_path / "berichte").glob("*-meldung-*"))
    assert any("pipeline_meta.lauf " in str(x) for x in verbindungen[1].befehle)


# --- E46: datenbankweite Sperre und Katalog -----------------------------------------------------------

def test_datenbankweite_sperre_belegt_kein_bericht(tmp_path, monkeypatch, capsys):
    """Prüfbericht 05.11., F10 (E46): Die Dateisperre gilt je Berichtsordner; zwei Ordner konnten dieselbe
    Datenbank parallel bearbeiten. Jetzt nimmt jeder Lauf zusätzlich eine Sperre in der Datenbank. Hält sie
    ein anderer Lauf, bricht dieser Start ab wie bei der Dateisperre: Rückgabe 1, kein Bericht, der den
    laufenden in --status verdeckte, keine Quelle angefasst."""
    gestartet = []
    monkeypatch.setattr(laden, "verbinden",
                        lambda *a, **kw: contextlib.nullcontext(_Verbindung(sperre_frei=False)))
    monkeypatch.setattr(laden, "quelle_laden", lambda *a, **kw: gestartet.append(a) or _ok())
    assert _main(monkeypatch, "--config", _quellen_cfg(tmp_path, "  a: {typ: csv, pfad: x.csv}\n")) == 1
    fehler = capsys.readouterr().err
    assert "derselben Datenbank" in fehler and "hält Sitzung 4711" in fehler   # neutral, mit der Sitzung
    assert not gestartet and not list((tmp_path / "berichte").glob("2*"))


def test_sperre_nach_neuaufbau_belegt_bricht_ab(tmp_path, monkeypatch):
    """Die datenbankweite Sperre endet mit der Verbindung. Nach einem Neuaufbau nimmt der Lauf sie wieder;
    hat sie inzwischen ein anderer Lauf, endet dieser als technischer Abbruch (DatenbankWeg), statt neben
    ihm weiterzuschreiben."""
    verbindungen = []

    class Verbindung(_Verbindung):
        closed = broken = False

    def verbinden(*a, **kw):
        verbindungen.append(Verbindung(sperre_frei=not verbindungen))
        return contextlib.nullcontext(verbindungen[-1])

    def quelle(conn, name, *a, **kw):
        conn.closed = conn.broken = True
        raise _Getrennt("server closed the connection unexpectedly")

    monkeypatch.setattr(laden, "verbinden", verbinden)
    monkeypatch.setattr(laden, "quelle_laden", quelle)
    with pytest.raises(laden.DatenbankWeg, match="derselben Datenbank .* hält Sitzung 4711"):
        laden.lauf(_quellen_cfg(tmp_path, "  a: {typ: csv, pfad: x.csv}\n  b: {typ: csv, pfad: y.csv}\n"),
                   alle=True)
    assert len(verbindungen) == 2


def _neu(*a, **kw):
    """Ersatz für quelle_laden: Quelle ok mit einem neuen Objekt; nach dem Lauf wird der Katalog aktualisiert.
    """
    b = _ok()
    b["zaehler"]["neu"] = 1
    return b


@pytest.mark.parametrize("katalog, code", [("aktualisiert", 0), ("fehlt", 0), (None, 1)])
def test_katalog_nach_lauf_mit_aenderungen(tmp_path, monkeypatch, katalog, code):
    """Antwort 75, Prüfbericht 05.11., F2 (E46): Nach einem Lauf mit Änderungen ruft die Pipeline
    pipeline_meta.katalog_aktualisieren() auf (eigene Transaktion, Wartegrenze für die Sperre). Fehlt die
    View, ist das ein Hinweis; scheitert der Aufruf, eine Warnung mit Rückgabe 1 und --status WARNING.
    Ohne Änderung kein Aufruf."""
    class Verbindung(_Verbindung):
        def cursor(self):
            cur = super().cursor()
            ausfuehren = cur.execute

            def execute(text, *a):
                ausfuehren(text, *a)
                if katalog is None and str(text) == "SELECT pipeline_meta.katalog_aktualisieren()":
                    # Fehler aus PL/pgSQL tragen eine zweite Zeile CONTEXT (Nachprüfung zu E46)
                    raise RuntimeError("must be owner of materialized view source_granularities\n"
                                       "CONTEXT:  SQL statement \"REFRESH MATERIALIZED VIEW …\"")

            cur.execute = execute
            return cur

    verbindungen = []

    def verbinden(*a, **kw):
        verbindungen.append(Verbindung(katalog=katalog))
        return contextlib.nullcontext(verbindungen[-1])

    monkeypatch.setattr(laden, "verbinden", verbinden)
    monkeypatch.setattr(laden, "quelle_laden", _neu)
    cfg = _quellen_cfg(tmp_path, "  a: {typ: csv, pfad: x.csv}\n")
    assert _main(monkeypatch, "--config", cfg, "--alle") == code
    (datei,) = (tmp_path / "berichte").glob("2*[0-9]Z.json")
    b = json.loads(datei.read_text())
    befehle = [str(x) for x in verbindungen[0].befehle]
    assert "SELECT set_config('lock_timeout', %s, true)" in befehle and laden.KATALOG_WARTEN == "10s"
    text = datei.with_suffix(".txt").read_text()
    if katalog == "aktualisiert":
        assert b["katalog"] == {"view": "public.source_granularities", "ergebnis": "aktualisiert"}
        assert "Katalog: public.source_granularities aktualisiert" in text
        assert _status(tmp_path)[0] == betrieb.OK
    elif katalog == "fehlt":
        assert b["katalog"]["ergebnis"] == "fehlt" and "gibt es in dieser Datenbank nicht" in text
        assert _status(tmp_path)[0] == betrieb.OK
    else:
        assert b["katalog"]["ergebnis"] == "fehler" and "must be owner" in b["katalog"]["fehler"]
        fehler = b["katalog"]["fehler"]
        assert "\n" not in fehler and "source_granularities CONTEXT: SQL" in fehler   # eine Zeile
        assert "WARNUNG: Katalog public.source_granularities nicht aktualisiert" in text
        code_s, zeile = _status(tmp_path)
        assert code_s == betrieb.WARNUNG and "Katalog nicht aktualisiert" in zeile
        assert "\n" not in zeile and " | quellen_ok=1 " in zeile   # Perfdata auf derselben Zeile
    # Ohne Änderung: kein Aufruf, kein Eintrag
    verbindungen.clear()
    monkeypatch.setattr(laden, "quelle_laden", _ok)
    assert _main(monkeypatch, "--config", cfg, "--alle") == 0
    assert not any("katalog_aktualisieren()" in str(x) and "SELECT pipeline" in str(x)
                   for x in verbindungen[0].befehle)


def test_probelauf_ruft_den_katalog_nicht_auf(tmp_path, monkeypatch):
    """Ein Probelauf ruft katalog_aktualisieren auch nach Änderungen nicht auf, und der Bericht hat keinen
    Eintrag `katalog` (E46)."""
    verbindungen = []

    def verbinden(*a, **kw):
        verbindungen.append(_Verbindung(katalog="aktualisiert"))
        return contextlib.nullcontext(verbindungen[-1])

    monkeypatch.setattr(laden, "verbinden", verbinden)
    monkeypatch.setattr(laden, "quelle_laden", _neu)
    b = laden.lauf(_quellen_cfg(tmp_path, "  a: {typ: csv, pfad: x.csv}\n"), probelauf=True, alle=True)
    assert "katalog" not in b
    assert not any(str(x) == "SELECT pipeline_meta.katalog_aktualisieren()" for x in verbindungen[0].befehle)


def test_metaschema_ohne_katalogfunktion_klare_meldung(tmp_path, monkeypatch, capsys):
    """Ein pipeline_meta von vor E46 hat die Funktion für den Katalog nicht: klare Meldung wie bei fehlenden
    Spalten (einrichten erneut ausführen), statt erst nach dem Lauf zu scheitern."""
    class Cursor(_Cursor):
        def fetchone(self):
            if "to_regprocedure" in str(self.conn.befehle[-1]):
                return (False,)
            return super().fetchone()

    class Verbindung(_Verbindung):
        def cursor(self):
            return Cursor(self)

    monkeypatch.setattr(laden, "verbinden", lambda *a, **kw: contextlib.nullcontext(Verbindung()))
    assert _main(monkeypatch, "--config", _cfg(tmp_path)) == laden.ABBRUCH
    assert "Funktion katalog_aktualisieren() oder Tabelle katalog_offen fehlt" in capsys.readouterr().err


# --- Nachprüfung zu E46 -------------------------------------------------------------------------------

@pytest.mark.parametrize("katalog", ["aktualisiert", None])
def test_katalog_offen_wird_ohne_aenderung_nachgeholt(tmp_path, monkeypatch, katalog):
    """Nachprüfung zu E46: Scheiterte die Aktualisierung des Katalogs, rief erst der nächste Lauf mit
    Änderungen sie wieder auf; ein Lauf ohne Änderung ließ den Katalog alt, und --status sprang auf OK. Jetzt
    steht die offene Aktualisierung in pipeline_meta.katalog_offen (mit den Daten geschrieben), und jeder
    Lauf holt sie nach, bis sie gelingt: dann wird die Liste geleert, sonst bleibt --status auf WARNING."""
    class Verbindung(_Verbindung):
        def cursor(self):
            cur = super().cursor()
            ausfuehren = cur.execute

            def execute(text, *a):
                ausfuehren(text, *a)
                if katalog is None and str(text) == "SELECT pipeline_meta.katalog_aktualisieren()":
                    raise RuntimeError("canceling statement due to lock timeout")

            cur.execute = execute
            return cur

    verbindungen = []

    def verbinden(*a, **kw):
        verbindungen.append(Verbindung(katalog=katalog, offen=["20261104T030000Z"]))
        return contextlib.nullcontext(verbindungen[-1])

    monkeypatch.setattr(laden, "verbinden", verbinden)
    monkeypatch.setattr(laden, "quelle_laden", _ok)                    # dieser Lauf ändert nichts
    cfg = _quellen_cfg(tmp_path, "  a: {typ: csv, pfad: x.csv}\n")
    assert _main(monkeypatch, "--config", cfg, "--alle") == (0 if katalog else 1)
    (datei,) = (tmp_path / "berichte").glob("2*[0-9]Z.json")
    b = json.loads(datei.read_text())
    befehle = [str(x) for x in verbindungen[0].befehle]
    assert b["katalog"]["nachgeholt"] == ["20261104T030000Z"]
    if katalog:
        assert b["katalog"]["ergebnis"] == "aktualisiert" and _status(tmp_path)[0] == betrieb.OK
        assert "DELETE FROM pipeline_meta.katalog_offen" in befehle
    else:
        assert b["katalog"]["ergebnis"] == "fehler" and _status(tmp_path)[0] == betrieb.WARNUNG
        # Die Löschung stünde in derselben, zurückgerollten Transaktion; hier gar nicht erst erreicht
        assert "DELETE FROM pipeline_meta.katalog_offen" not in befehle


def test_probelauf_hilfe_verspricht_nicht_mehr_als_der_code(monkeypatch, capsys):
    """Prüfbericht 05.11., F13, Rest (Nachprüfung zu E46): Der Hilfetext von --probelauf und der Kommentar in
    config/beispiel-paging.yaml versprachen weiter „nichts schreiben“; ein Probelauf schreibt Prüfberichte
    und gegebenenfalls den Cache."""
    with pytest.raises(SystemExit):
        _main(monkeypatch, "--help")
    hilfe = " ".join(capsys.readouterr().out.split())
    assert "ohne dauerhafte Änderungen an den Fachdaten; Prüfbericht und Cache werden geschrieben" in hilfe
    assert "nichts in die Datenbank schreiben" not in hilfe
    config = Path(laden.__file__).resolve().parent.parent / "config"
    for datei in config.glob("*.yaml"):
        assert "schreibt nichts" not in datei.read_text(encoding="utf-8"), datei.name


# --- E50: Prüfbericht vom 06.11.2026, 13:26 (A1, K2, W6, W7) ------------------------------------------------

_INKAR_FREI = ("  inkar:\n    typ: inkar\n    url: https://www.bbr-server.de/imagemap/inkar/download/inkar_{jahr}.zip\n"
               "    robots_freigabe: \"Vorgabe des Auftraggebers, Antwort 33 (Test)\"\n")


def test_freigabe_in_bericht_text_und_protokoll(tmp_path, monkeypatch):
    """E50, Befund A1: Ruft eine Quelle einen per robots.txt gesperrten Rechner mit ihrer Freigabe ab, steht
    die Freigabe im JSON-Bericht (info.robots_freigabe und Warnung), im Textbericht und im Protokoll je Lauf
    (pipeline_meta.quellenlauf.warnungen). Die Quelle ist eine Attrappe, die nur die Abrufregel durchläuft."""
    protokolle = []

    def quelle(conn, name, qcfg, lauf_id, jetzt, prot, *a, **kw):
        """Ersatz für quelle_laden: prüft die Adresse wie vor einem echten Abruf und meldet ok."""
        laden.quellen.schema_pruefen(qcfg["url"].format(jahr=2025), qcfg, prot)
        return _ok()

    monkeypatch.setattr(laden, "verbinden", lambda *a, **kw: contextlib.nullcontext(_Verbindung()))
    monkeypatch.setattr(laden, "quelle_laden", quelle)
    monkeypatch.setattr(laden, "protokollieren", lambda conn, lid, e: protokolle.append(e["warnungen"]))
    b = laden.lauf(_quellen_cfg(tmp_path, _INKAR_FREI), alle=True)
    (q,) = b["quellen"]
    assert q["info"]["robots_freigabe"] == {"rechner": "www.bbr-server.de", "gesperrt": "/",
                                            "grund": "Vorgabe des Auftraggebers, Antwort 33 (Test)"}
    (datei,) = (tmp_path / "berichte").glob("2*[0-9]Z.txt")
    assert "robots_freigabe" in datei.read_text() and "Antwort 33 (Test)" in datei.read_text()
    assert any("Antwort 33 (Test)" in w for w in protokolle[0])


def test_ziele_nennt_freigegebenen_rechner_mit_freigabe(tmp_path, monkeypatch, capsys):
    """E50, Befund A1: --ziele nennt einen gesperrten Rechner, den eine Quelle mit Freigabe abruft (die
    Firewall muss ihn durchlassen), und zeigt die Freigabe als Kommentarzeile (#) unter der Liste; die Liste
    selbst bleibt host:port je Zeile. Ohne Freigabe fehlt der Rechner wie bisher."""
    cfg = {"quellen": {"inkar": {"typ": "inkar", "robots_freigabe": "Antwort 33",
                                 "url": "https://www.bbr-server.de/x/inkar_{jahr}.zip"}}}
    assert laden.ziele(cfg) == ["www.bbr-server.de:443"]
    assert laden.freigaben(cfg) == ["# robots.txt-Freigabe: www.bbr-server.de (Quelle inkar): Antwort 33"]
    del cfg["quellen"]["inkar"]["robots_freigabe"]
    assert laden.ziele(cfg) == [] and laden.freigaben(cfg) == []
    assert _main(monkeypatch, "--config", _quellen_cfg(tmp_path, _INKAR_FREI), "--ziele") == 0
    aus = capsys.readouterr().out.splitlines()
    assert aus[0] == "www.bbr-server.de:443" and aus[1].startswith("# robots.txt-Freigabe: www.bbr-server.de")


def test_karte_scheitert_pflichtbericht_bleibt_vollstaendig(tmp_path, monkeypatch, capsys):
    """E50, Befund K2: Pflichtbericht zuerst, optionale Ausgaben danach mit eigenem Fehlerpfad. Scheitert die
    Karte, stehen JSON- und Textbericht mit allen Quellen; der Fehler steht in `ausgaben_fehler`, der Bericht
    verweist auf keine Karte, --status meldet WARNING und die Rückgabe ist 1. Bis E49 endete der Lauf hier als
    technischer Abbruch mit einem Bericht ohne Quellen."""
    def karte_kaputt(*a, **kw):
        raise OSError("Platte voll (Karte)")

    monkeypatch.setattr(laden, "verbinden", lambda *a, **kw: contextlib.nullcontext(_Verbindung()))
    monkeypatch.setattr(laden, "quelle_laden", _ok)
    monkeypatch.setattr(laden.karte, "schreiben", karte_kaputt)
    cfg = _quellen_cfg(tmp_path, "  a: {typ: csv, pfad: x.csv}\n  b: {typ: csv, pfad: y.csv}\n")
    assert _main(monkeypatch, "--config", cfg, "--alle") == 1
    (datei,) = (tmp_path / "berichte").glob("2*[0-9]Z.json")
    b = json.loads(datei.read_text())
    assert [q["quelle"] for q in b["quellen"]] == ["a", "b"] and "abbruch" not in b and "karte" not in b
    assert any("Karte" in f and "Platte voll" in f for f in b["ausgaben_fehler"])
    assert "Platte voll (Karte)" in datei.with_suffix(".txt").read_text()
    assert _status(tmp_path)[0] == betrieb.WARNUNG


def test_aufraeumen_scheitert_pflichtbericht_bleibt_vollstaendig(tmp_path, monkeypatch):
    """E50, Befund K2: Scheitert das Aufräumen alter Laufdateien, bleibt der Bericht mit allen Quellen, die
    Karte entsteht trotzdem, und der Fehler steht in `ausgaben_fehler`."""
    def kaputt(*a, **kw):
        raise PermissionError("keine Rechte (Aufräumen)")

    monkeypatch.setattr(laden, "verbinden", lambda *a, **kw: contextlib.nullcontext(_Verbindung()))
    monkeypatch.setattr(laden, "quelle_laden", _ok)
    monkeypatch.setattr(laden.betrieb, "aufraeumen", kaputt)
    cfg = _quellen_cfg(tmp_path, "  a: {typ: csv, pfad: x.csv}\n")
    Path(cfg).write_text(Path(cfg).read_text() + "aufbewahrung_tage: 30\n")
    b = laden.lauf(cfg, alle=True)
    assert [q["quelle"] for q in b["quellen"]] == ["a"] and (tmp_path / "berichte" / b["karte"]).exists()
    gespeichert = json.loads((tmp_path / "berichte" / f"{b['lauf_id']}.json").read_text())
    assert gespeichert["quellen"][0]["quelle"] == "a" and gespeichert["karte"] == b["karte"]
    assert any("Aufräumen" in f and "keine Rechte" in f for f in gespeichert["ausgaben_fehler"])


def test_abbruch_mitten_im_lauf_bericht_mit_bisherigen_quellen(tmp_path, monkeypatch):
    """E50, Befund K2: Wird der Lauf mitten in einer Quelle beendet (SIGTERM, Strg+C), enthält der
    Abbruchbericht (JSON und Text) die Ergebnisse der schon bearbeiteten Quellen und die abgebrochene Quelle
    als fehlgeschlagen (ihre Transaktion ist zurückgerollt). Bis E49 stand dort `quellen: []`."""
    def quelle(conn, name, *a, **kw):
        if name == "b":
            laden._beenden(laden.signal.SIGTERM, None)
        return _ok()

    monkeypatch.setattr(laden, "verbinden", lambda *a, **kw: contextlib.nullcontext(_Verbindung()))
    monkeypatch.setattr(laden, "quelle_laden", quelle)
    cfg = _quellen_cfg(tmp_path, "  a: {typ: csv, pfad: x.csv}\n  b: {typ: csv, pfad: y.csv}\n"
                                 "  c: {typ: csv, pfad: z.csv}\n")
    assert _main(monkeypatch, "--config", cfg, "--alle") == laden.ABBRUCH
    (datei,) = (tmp_path / "berichte").glob("2*[0-9]Z.json")
    b = json.loads(datei.read_text())
    assert [(q["quelle"], q["status"]) for q in b["quellen"]] == [("a", "ok"), ("b", "fehler")]
    assert "Beendet" in b["quellen"][1]["fehler"] and "SIGTERM" in b["abbruch"]
    text = datei.with_suffix(".txt").read_text()
    assert "TECHNISCH ABGEBROCHEN" in text
    assert any(z.split()[:2] == ["a", "ok"] for z in text.splitlines())
    assert any(z.split()[:2] == ["b", "FEHLER"] for z in text.splitlines())


@pytest.mark.parametrize("wert", ["30", 0, -1, True, float("nan"), [5]])
def test_zeitbudget_falsche_werte_brechen_vor_dem_laden_ab(tmp_path, monkeypatch, wert):
    """E50, Befund W6: zeitbudget_min (je Quelle oder für alle oben in der Konfiguration) muss eine positive
    Zahl in Minuten sein; sonst bricht der Lauf vor dem ersten Abruf ab, wie bei einem unbekannten
    Rhythmus."""
    monkeypatch.setattr(laden, "verbinden",
                        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("verbunden")))
    for zeile in (f"  a: {{typ: csv, pfad: x.csv, zeitbudget_min: {json.dumps(wert)}}}\n",):
        with pytest.raises(laden.KonfigFehler, match="zeitbudget_min"):
            laden.lauf(_quellen_cfg(tmp_path, zeile), alle=True)
    cfg = _quellen_cfg(tmp_path, "  a: {typ: csv, pfad: x.csv}\n")
    Path(cfg).write_text(Path(cfg).read_text() + f"zeitbudget_min: {json.dumps(wert)}\n")
    with pytest.raises(laden.KonfigFehler, match="zeitbudget_min"):
        laden.lauf(cfg, alle=True)


def test_zeitbudget_standard_und_vorrang():
    """E50, Befund W6: Standard 30 min; ein Wert oben in der Konfiguration gilt für alle Quellen, einer in der
    Quelle geht vor."""
    assert laden.zeitbudget({}, {}) == laden.ZEITBUDGET_STANDARD_MIN == 30
    assert laden.zeitbudget({"zeitbudget_min": 90}, {}) == 90
    assert laden.zeitbudget({"zeitbudget_min": 90}, {"zeitbudget_min": 5}) == 5


def test_leerlieferung_freigabe_auf_der_kommandozeile(tmp_path, monkeypatch, capsys):
    """E50, Befund W7: --leerlieferung QUELLE GRUND gibt für genau diesen Lauf eine bestätigte Leerlieferung
    frei. Unbekannte oder abgeschaltete Quelle und leerer Grund brechen vor dem Laden ab (Rückgabe 2); die
    Freigabe kommt mit ihrem Grund bei quelle_laden an."""
    erhalten = {}

    def quelle(conn, name, *a, leer_grund=None, **kw):
        erhalten[name] = leer_grund
        return _ok()

    monkeypatch.setattr(laden, "verbinden", lambda *a, **kw: contextlib.nullcontext(_Verbindung()))
    monkeypatch.setattr(laden, "quelle_laden", quelle)
    cfg = _quellen_cfg(tmp_path, "  a: {typ: csv, pfad: x.csv}\n  b: {typ: csv, pfad: y.csv}\n"
                                 "  aus: {typ: csv, pfad: z.csv, aktiv: false}\n")
    for falsch in (["fehlt", "Grund"], ["aus", "Grund"], ["a", "  "]):
        assert _main(monkeypatch, "--config", cfg, "--alle", "--leerlieferung", *falsch) == laden.ABBRUCH
        assert "leerlieferung" in capsys.readouterr().err
    assert erhalten == {}
    assert _main(monkeypatch, "--config", cfg, "--alle", "--leerlieferung", "a", "Anbieter bestätigt") == 0
    assert erhalten == {"a": "Anbieter bestätigt", "b": None}


# --- E50, Nachprüfung (Prüfer zu E50, 06.11.2026) -------------------------------------------------------

def test_abbruch_mitten_in_der_quelle_behaelt_ihr_protokoll(tmp_path, monkeypatch):
    """Nachprüfung zu E50, Befund zu K2: Wird der Lauf mitten in einer Quelle beendet (SIGTERM nach
    TimeoutStartSec, Strg+C), stand die Quelle im Abbruchbericht nur mit status und fehler. Eine schon
    genutzte robots_freigabe (ein tatsächlicher Abruf eines gesperrten Rechners) fehlte damit in Bericht und
    Text. Jetzt übernimmt der Abbruchpfad Warnungen, Hinweise, info, letzte Abfrage und Laufzeit der Quelle
    wie der reguläre Pfad. Eine Protokollzeile in pipeline_meta schreibt der Abbruch bewusst nicht
    (docs/betrieb.md)."""
    protokolle = []

    def quelle(conn, name, qcfg, lauf_id, jetzt, prot, *a, **kw):
        """Ersatz für quelle_laden: prüft die Adresse wie vor dem Download (Freigabe genutzt), hält eine
        Abfrage fest, dann kommt SIGTERM."""
        url = qcfg["url"].format(jahr=2025)
        laden.quellen.schema_pruefen(url, qcfg, prot)
        prot.letzte_abfrage = url
        prot.hinweise.append("Download begonnen")
        laden._beenden(laden.signal.SIGTERM, None)

    monkeypatch.setattr(laden, "verbinden", lambda *a, **kw: contextlib.nullcontext(_Verbindung()))
    monkeypatch.setattr(laden, "quelle_laden", quelle)
    monkeypatch.setattr(laden, "protokollieren", lambda conn, lid, e: protokolle.append(e))
    assert _main(monkeypatch, "--config", _quellen_cfg(tmp_path, _INKAR_FREI), "--alle") == laden.ABBRUCH
    (datei,) = (tmp_path / "berichte").glob("2*[0-9]Z.json")
    (q,) = json.loads(datei.read_text())["quellen"]
    assert q["status"] == "fehler" and "Beendet" in q["fehler"]
    assert q["info"]["robots_freigabe"]["rechner"] == "www.bbr-server.de"
    assert any("robots_freigabe" in w and "Antwort 33 (Test)" in w for w in q["warnungen"])
    assert q["letzte_abfrage"].startswith("https://www.bbr-server.de/")
    assert "Download begonnen" in q["hinweise"]
    assert "laufzeit_s" in q
    text = datei.with_suffix(".txt").read_text()
    assert "robots_freigabe" in text and "Antwort 33 (Test)" in text
    assert protokolle == []


def test_fehlgeschlagene_quelle_erscheint_nicht_in_der_karte(tmp_path, monkeypatch):
    """Nachprüfung zu E50, Pre-existing: quelle_laden füllt die Kartenobjekte, bevor es schreibt. Scheitert
    die Quelle danach (Zeitbudget, anwenden, Metadaten), wird ihre Transaktion zurückgerollt, die Karte
    zeichnete die Änderungen aber trotzdem. Jetzt verwirft _lauf die Kartenobjekte einer Quelle mit Status
    fehler."""
    gezeichnet = {}

    def quelle(conn, name, qcfg, lauf_id, jetzt, prot, vorher, probelauf, kartenobjekte, **kw):
        """Ersatz für quelle_laden: legt Kartenobjekte ab; Quelle b scheitert danach."""
        kartenobjekte[name] = [{"art": "neu"}]
        if name == "b":
            raise laden.quellen.ZeitbudgetUeberschritten("Zeitbudget von 1 min überschritten")
        return _ok()

    monkeypatch.setattr(laden, "verbinden", lambda *a, **kw: contextlib.nullcontext(_Verbindung()))
    monkeypatch.setattr(laden, "quelle_laden", quelle)
    monkeypatch.setattr(laden.karte, "schreiben", lambda datei, b, objekte, h: gezeichnet.update(objekte))
    b = laden.lauf(_quellen_cfg(tmp_path, "  a: {typ: csv, pfad: x.csv}\n  b: {typ: csv, pfad: y.csv}\n"),
                   alle=True)
    assert [q["status"] for q in b["quellen"]] == ["ok", "fehler"]
    assert set(gezeichnet) == {"a"}


def test_ungenutzte_leerlieferung_steht_im_bericht(tmp_path, monkeypatch):
    """Nachprüfung zu E50, Befund W7: Wird eine Quelle mit --leerlieferung in diesem Lauf nicht geladen (--nur
    für eine andere Quelle, oder nicht fällig nach Rhythmus), verfiel die Freigabe, ohne dass der Bericht es
    sagte. Jetzt nennt der Bericht (JSON und Text) jede ungenutzte Freigabe mit Quelle, Grund und warum."""
    monkeypatch.setattr(laden, "verbinden", lambda *a, **kw: contextlib.nullcontext(_Verbindung()))
    monkeypatch.setattr(laden, "quelle_laden", _ok)
    cfg = _quellen_cfg(tmp_path, "  a: {typ: csv, pfad: x.csv, rhythmus: monatlich}\n"
                                 "  b: {typ: csv, pfad: y.csv, rhythmus: monatlich}\n")
    assert _main(monkeypatch, "--config", cfg, "--nur", "b",
                 "--leerlieferung", "a", "Anbieter bestätigt") == 0
    (datei,) = (tmp_path / "berichte").glob("2*[0-9]Z.json")
    (u,) = json.loads(datei.read_text())["leerlieferung_ungenutzt"]
    assert u["quelle"] == "a" and u["grund"] == "Anbieter bestätigt" and "--nur b" in u["warum"]
    assert "Anbieter bestätigt" in datei.with_suffix(".txt").read_text()
    # Nicht fällig nach Rhythmus: ebenso ungenutzt, mit dem nächsten Termin
    termin = datetime(2099, 1, 1, tzinfo=UTC)
    monkeypatch.setattr(laden, "faelligkeit", lambda conn, name, qcfg, jetzt: (termin, False))
    b = laden.lauf(cfg, leer={"b": "Anbieter bestätigt"})
    (u,) = b["leerlieferung_ungenutzt"]
    assert u["quelle"] == "b" and "nicht fällig" in u["warum"] and "2099-01-01" in u["warum"]
    assert "leerlieferung_ungenutzt" not in laden.lauf(cfg, alle=True, leer={"a": "x"})


@pytest.mark.parametrize("text", ["Grund\nevil.example:443", "Grund\revil.example:443", "Grund x",
                                  "Grund\x00"])
def test_freigabe_mit_zeilenumbruch_bricht_vor_dem_lauf_ab(tmp_path, monkeypatch, capsys, text):
    """Nachprüfung zu E50: Ein Freigabetext mit Zeilenumbruch ergab in --ziele eine zweite Zeile ohne „#“, die
    ein Skript, das die Kommentarzeilen überspringt, als Ziel für die Firewall läse. Jetzt sind Steuerzeichen
    und Zeilentrenner in robots_freigabe ein Konfigurationsfehler, vor dem Lauf und vor --ziele."""
    quelle = {"typ": "inkar", "url": "https://www.bbr-server.de/x/inkar_{jahr}.zip", "robots_freigabe": text}
    cfg = tmp_path / "quellen.yaml"
    cfg.write_text(json.dumps({"berichte": str(tmp_path / "berichte"), "quellen": {"inkar": quelle}}),
                   encoding="utf-8")
    monkeypatch.setattr(laden, "verbinden",
                        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("verbunden")))
    with pytest.raises(laden.KonfigFehler, match="robots_freigabe"):
        laden.lauf(str(cfg), alle=True)
    assert _main(monkeypatch, "--config", str(cfg), "--ziele") == laden.ABBRUCH
    aus = capsys.readouterr()
    assert "evil.example" not in aus.out and "robots_freigabe" in aus.err
    with pytest.raises(laden.quellen.QuellenFehler, match="robots_freigabe"):
        laden.quellen.robots_freigabe(quelle)


# --- E51: Prüfbericht vom 07.11.2026, 03:13 (K1: Zeitgrenzen der Datenbank je Quelle) -----------------------

class _Merkcursor:
    """Cursor-Stellvertreter, der Anweisungen und Parameter sammelt."""

    def __init__(self):
        self.befehle = []

    def execute(self, text, werte=None):
        self.befehle.append((text, werte))


def test_datenbank_zeitgrenzen_aus_dem_rest_des_zeitbudgets():
    """E51, Befund K1: Vor jedem Schreibschritt setzt die Pipeline statement_timeout auf den Rest des
    Zeitbudgets und lock_timeout auf den kleineren Wert aus Rest und eigener Wartegrenze (db_sperre_max_s),
    nur für die Transaktion der Quelle (set_config mit true, wie SET LOCAL). Nie 0: 0 hieße in PostgreSQL
    „ohne Grenze“. Ist das Budget schon um, endet die Quelle vorher mit ZeitbudgetUeberschritten."""
    uhr = [0.0]
    prot = laden.Protokoll()
    prot.frist_setzen(10, uhr=lambda: uhr[0])      # 600 s
    cur = _Merkcursor()
    assert laden.db_grenzen(cur, prot, 300) == (600_000, 300_000)
    text, werte = cur.befehle[-1]
    assert "set_config('statement_timeout', %s, true)" in text
    assert "set_config('lock_timeout', %s, true)" in text
    assert werte == ("600000ms", "300000ms")
    uhr[0] = 599.9996                                # 0,4 ms Rest: aufgerundet auf 1 ms, nicht 0
    assert laden.db_grenzen(cur, prot, 300) == (1, 1)
    uhr[0] = 601
    n = len(cur.befehle)
    with pytest.raises(laden.quellen.ZeitbudgetUeberschritten):
        laden.db_grenzen(cur, prot, 300)
    assert len(cur.befehle) == n


def test_datenbank_zeitgrenze_wird_als_zeitbudget_gemeldet():
    """E51, K1: Bricht PostgreSQL eine Anweisung wegen lock_timeout oder statement_timeout ab, meldet die
    Quelle „Zeitbudget/Datenbank-Zeitgrenze“ als ZeitbudgetUeberschritten (ohne Meldungsentwurf an den
    Anbieter, waechter.meldung_noetig). Ein Abbruch aus anderem Grund (pg_cancel_backend, „user request“)
    bleibt, was er ist."""
    from psycopg import errors
    for fehler, art in ((errors.LockNotAvailable("canceling statement due to lock timeout"), "lock_timeout"),
                        (errors.QueryCanceled("canceling statement due to statement timeout"),
                         "statement_timeout")):
        with pytest.raises(laden.quellen.ZeitbudgetUeberschritten) as e, laden.db_zeitgrenze_melden(300):
            raise fehler
        assert str(e.value).startswith("Zeitbudget/Datenbank-Zeitgrenze") and art in str(e.value)
        assert e.value.__cause__ is fehler
    from pipeline import waechter
    assert not waechter.meldung_noetig({"status": "fehler", "fehler": f"ZeitbudgetUeberschritten: {e.value}"})
    with pytest.raises(errors.QueryCanceled), laden.db_zeitgrenze_melden(300):
        raise errors.QueryCanceled("canceling statement due to user request")


def test_statement_timeout_nach_der_zeit_erkannt_nicht_nach_dem_text():
    """Nachprüfung zu E51 (zweimal gemeldet): Ob ein QueryCanceled vom statement_timeout kommt, entschied
    allein der englische Text der Servermeldung. Der folgt lc_messages des Servers, und die Importrolle darf
    lc_messages nicht setzen. Auf einem Server mit deutscher Locale lief ein echter Abbruch am Budget als
    gewöhnlicher Fehler hinaus, mit Meldungsentwurf an den Anbieter. Jetzt entscheidet der Rest des Budgets:
    praktisch aufgebraucht (unter 1 s) heißt statement_timeout, gleich in welcher Sprache. Ein Abbruch von
    Hand mitten im Budget bleibt QueryCanceled, auch auf Deutsch; der englische Text gilt weiter als Rückfall.
    Ohne Budget (rest_s None) setzt db_grenzen statement_timeout 0, dann entscheidet nur der Text."""
    from psycopg import errors
    uhr = [0.0]
    prot = laden.Protokoll()
    prot.frist_setzen(10, uhr=lambda: uhr[0])      # 600 s
    deutsch = "storniere Anfrage wegen Zeitüberschreitung der Anweisung"
    uhr[0] = 600.2                                   # Budget um: Rest 0
    with pytest.raises(laden.quellen.ZeitbudgetUeberschritten, match="statement_timeout"), \
            laden.db_zeitgrenze_melden(300, prot):
        raise errors.QueryCanceled(deutsch)
    uhr[0] = 599.5                                   # Rest 0,5 s: unter der Schwelle
    with pytest.raises(laden.quellen.ZeitbudgetUeberschritten), laden.db_zeitgrenze_melden(300, prot):
        raise errors.QueryCanceled(deutsch)
    uhr[0] = 300                                     # Rest 300 s: Abbruch von Hand, gleich welche Sprache
    for text in ("storniere Anfrage wegen Benutzeranforderung", "canceling statement due to user request"):
        with pytest.raises(errors.QueryCanceled), laden.db_zeitgrenze_melden(300, prot):
            raise errors.QueryCanceled(text)
    with pytest.raises(laden.quellen.ZeitbudgetUeberschritten), laden.db_zeitgrenze_melden(300, prot):
        raise errors.QueryCanceled("canceling statement due to statement timeout")
    ohne_budget = laden.Protokoll()
    with pytest.raises(errors.QueryCanceled), laden.db_zeitgrenze_melden(300, ohne_budget):
        raise errors.QueryCanceled(deutsch)


@pytest.mark.parametrize("schluessel, zu_gross, hoechst", [
    ("zeitbudget_min", 35_792, 35_791), ("zeitbudget_min", 40_000, 35_791), ("zeitbudget_min", 1e306, 35_791),
    ("db_sperre_max_s", 2_147_484, 2_147_483), ("db_sperre_max_s", 1e306, 2_147_483)])
def test_zeitgrenzen_ueber_dem_hoechstwert_von_postgresql_brechen_vor_dem_laden_ab(schluessel, zu_gross,
                                                                                   hoechst):
    """Nachprüfung zu E51 (zweimal gemeldet): PostgreSQL nimmt für statement_timeout und lock_timeout
    höchstens 2^31 - 1 ms an (rund 35 791 min bzw. 2 147 483 s). zeitbudget_pruefen nahm jede endliche Zahl
    über 0 an; mit zeitbudget_min 40 000 lehnte set_config den Wert erst zu Beginn der Quelle ab
    (InvalidParameterValue, nachgestellt auf PG 16), und _nachlauf schrieb einen Meldungsentwurf an den
    Anbieter. Bei 1e306 brach math.ceil mit OverflowError ab. Jetzt ein Konfigurationsfehler vor dem Lauf,
    oben und je Quelle; der Höchstwert selbst ist erlaubt."""
    for oben in (True, False):
        cfg = {"quellen": {"a": {"typ": "csv"}}}
        ort = cfg if oben else cfg["quellen"]["a"]
        ort[schluessel] = zu_gross
        with pytest.raises(laden.KonfigFehler, match=rf"{schluessel} .*höchstens {hoechst} "):
            laden.zeitbudget_pruefen(cfg)
        ort[schluessel] = hoechst
        laden.zeitbudget_pruefen(cfg)


def test_zeitgrenze_40000_min_bricht_den_lauf_vor_der_verbindung_ab(tmp_path, monkeypatch):
    """Nachprüfung zu E51, der nachgestellte Fall aus der Prüfung (zeitbudget_min: 40000 in der Datei): Der
    Lauf bricht vor der ersten Verbindung ab, nicht erst die Quelle an set_config."""
    monkeypatch.setattr(laden, "verbinden",
                        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("verbunden")))
    with pytest.raises(laden.KonfigFehler, match="zeitbudget_min"):
        laden.lauf(_quellen_cfg(tmp_path, "  a: {typ: csv, pfad: x.csv, zeitbudget_min: 40000}\n"), alle=True)


def test_datenbank_zeitgrenzen_nie_ueber_dem_hoechstwert_von_postgresql():
    """Nachprüfung zu E51: db_grenzen kappt beide Werte auf 2^31 - 1 ms, auch bei einem Budget, das am
    Höchstwert liegt und aufgerundet darüber käme, und bei einem direkten Aufruf mit einem sehr großen Budget
    (ohne OverflowError)."""
    for budget_min, sperre_s, erwartet in ((35_791.3946, 300, (laden.PG_ZEITGRENZE_MAX_MS, 300_000)),
                                           (1e306, 1e306, (laden.PG_ZEITGRENZE_MAX_MS,) * 2)):
        prot = laden.Protokoll()
        prot.frist_setzen(budget_min, uhr=lambda: 0.0)
        assert laden.db_grenzen(_Merkcursor(), prot, sperre_s) == erwartet


class _Schrittcursor:
    """Cursor-Stellvertreter für quelle_laden ohne Datenbank: merkt set_config mit dem Rest auf der gestellten
    Uhr als ("grenze", statement_timeout_ms, lock_timeout_ms, rest_s), andere Anweisungen nur mit ihrem
    ersten Wort; count(*) liefert 1."""

    def __init__(self, log, uhr, prot):
        self.log, self.uhr, self.prot = log, uhr, prot

    def execute(self, text, werte=None):
        if "set_config('statement_timeout'" in text:
            self.log.append(("grenze", int(werte[0][:-2]), int(werte[1][:-2]), self.prot.rest_s()))
        else:
            self.log.append(("sql", text.split()[0]))

    def fetchone(self):
        return (1,)


class _Schrittverbindung:
    """Verbindungs-Stellvertreter: transaction() und cursor() als Kontext; das Ende der Transaktion steht als
    ("abschluss",) im Protokoll."""

    def __init__(self, cur, log):
        self.cur, self.log = cur, log

    @contextlib.contextmanager
    def transaction(self, force_rollback=False):
        yield
        self.log.append(("abschluss",))

    @contextlib.contextmanager
    def cursor(self):
        yield self.cur


def test_zeitgrenzen_vor_jedem_schreibschritt_mit_dem_aktuellen_rest(monkeypatch):
    """Nachprüfung zu E51, Befund des Prüfers: Die Tests legten nicht fest, an welchen Stellen quelle_laden
    die Zeitgrenzen setzt. Zwei kaputte Fassungen bestanden alle Tests und den Sperrtest auf PG 16: ohne den
    ersten Aufruf zu Beginn der Transaktion (mutA), und mit nur diesem ersten Aufruf, die Prüfpunkte danach
    wieder nur Protokoll.zeit_pruefen (mutB, statement_timeout bliebe beim vollen Budget). Grund: Das
    lock_timeout aus dem ersten Setzen gilt bis zum Ende der Transaktion.

    Hier läuft quelle_laden mit Attrappen für Verbindung, Cursor, Adapter und die Schritte aus ziel; jeder
    Schritt stellt die gestellte Uhr 10 s weiter. Geprüft: set_config steht als erste Anweisung der
    Transaktion (vor ziel.pruefen und dem Einlesen) und unmittelbar vor neu_bilden, vergleichen, anwenden,
    metadaten_schreiben und dem Abschluss, jedes Mal mit dem aktuellen Rest (statement_timeout = Rest,
    lock_timeout = kleinerer Wert aus Rest und db_sperre_max_s), also kleiner werdend."""
    from types import SimpleNamespace

    from pipeline import waechter
    log, uhr = [], [0.0]
    prot = laden.Protokoll()
    frist = prot.frist_setzen
    # quelle_laden setzt die Frist selbst, mit time.monotonic als Standard (bei der Definition gebunden);
    # hier auf die gestellte Uhr umgelenkt
    monkeypatch.setattr(prot, "frist_setzen", lambda minuten: frist(minuten, uhr=lambda: uhr[0]))

    def schritt(name, ergebnis=None):
        """Attrappe eines Schritts aus ziel: ins Protokoll, Uhr 10 s weiter."""
        def f(*a, **kw):
            log.append(("schritt", name))
            uhr[0] += 10
            return ergebnis
        return f

    @contextlib.contextmanager
    def eingang_kopie(cur):
        log.append(("schritt", "einlesen"))
        uhr[0] += 10
        yield None

    def adapter(cfg, prot):
        yield {"objekt_id": "1"}

    monkeypatch.setitem(laden.ADAPTER, "attrappe", adapter)
    for name, ergebnis in (("planer_einstellen", None), ("pruefen", None), ("neu_bilden", None),
                           ("gebiet_pruefen", None), ("flaeche_pruefen", None), ("bisher", 1),
                           ("metadaten_belegt", []), ("vergleichen", {"neu": 1}), ("doppelte_im_ziel", 0),
                           ("zurueckhalten", None), ("anwenden", None), ("metadaten_schreiben", {})):
        monkeypatch.setattr(laden.ziel, name, schritt(name, ergebnis))
    monkeypatch.setattr(laden.ziel, "aus_konfiguration",
                        lambda name, cfg: SimpleNamespace(name="ziel_attrappe", loeschen=True))
    monkeypatch.setattr(laden.ziel, "eingang_kopie", eingang_kopie)
    monkeypatch.setattr(laden.ziel, "zeilen", lambda ds, z: iter([({}, None, None)]))
    monkeypatch.setattr(laden.ziel, "eingang_zeile", lambda *a: None)
    monkeypatch.setattr(waechter, "schema_vergleichen", lambda vorher, info: [])
    cur = _Schrittcursor(log, uhr, prot)
    e = laden.quelle_laden(_Schrittverbindung(cur, log), "q", {"typ": "attrappe"}, "20261107T000000Z",
                           datetime(2026, 11, 7, tzinfo=UTC), prot, budget_min=10, sperre_max_s=300)
    assert e["status"] == "ok", e
    assert log[0][0] == "grenze", log
    assert log.index(("schritt", "pruefen")) < log.index(("schritt", "einlesen"))
    for ziel_schritt in (("schritt", "neu_bilden"), ("schritt", "vergleichen"), ("schritt", "anwenden"),
                         ("schritt", "metadaten_schreiben"), ("abschluss",)):
        davor = log[log.index(ziel_schritt) - 1]
        assert davor[0] == "grenze", (ziel_schritt, log)
    grenzen = [g for g in log if g[0] == "grenze"]
    assert len(grenzen) == 6, grenzen
    for _, anweisung_ms, sperre_ms, rest in grenzen:
        assert anweisung_ms == round(rest * 1000) and sperre_ms == min(anweisung_ms, 300_000), grenzen
    werte = [g[1] for g in grenzen]
    assert werte == sorted(werte, reverse=True) and len(set(werte)) == len(werte), werte
    assert werte[0] == 600_000 and werte[-1] < 600_000 - 10_000 * 5, werte


@pytest.mark.parametrize("wert", ["300", 0, -1, True, float("nan")])
def test_db_sperre_max_falsche_werte_brechen_vor_dem_laden_ab(tmp_path, monkeypatch, wert):
    """E51, K1: db_sperre_max_s (je Quelle oder oben) muss eine positive Zahl in Sekunden sein, wie
    zeitbudget_min; Standard 300 s, die Quelle geht vor."""
    monkeypatch.setattr(laden, "verbinden",
                        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("verbunden")))
    zeile = f"  a: {{typ: csv, pfad: x.csv, db_sperre_max_s: {json.dumps(wert)}}}\n"
    with pytest.raises(laden.KonfigFehler, match="db_sperre_max_s"):
        laden.lauf(_quellen_cfg(tmp_path, zeile), alle=True)
    assert laden.db_sperre_max({}, {}) == laden.DB_SPERRE_STANDARD_S == 300
    assert laden.db_sperre_max({"db_sperre_max_s": 60}, {"db_sperre_max_s": 5}) == 5
