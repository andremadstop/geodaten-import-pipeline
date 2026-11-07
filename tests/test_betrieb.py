"""Überwachung, Kennzahlen und Aufbewahrung, nur auf Berichtsdateien.

pipeline.betrieb liegt neben der Kette laden → quellen → ziel und liest nur die Laufberichte in
berichte/, ohne Datenbank. Abgesichert werden: die Zustände von --status nach der Konvention von
Nagios/Icinga (ein unvollständiger Abruf ist WARNING, nie allein CRITICAL: E32, E42, E44), die Zählung
von --kennzahlen nach demselben Ergebnis wie im Quellenverzeichnis, die Aufbewahrung mit Schutz des
Vergleichsstands (E18), das Überspringen unlesbarer und das atomare Ersetzen von Berichten (E42) und eine
Statuszeile, die auch bei mehrzeiligen Fehlertexten einzeilig bleibt (E46).
"""
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from pipeline import betrieb


def _bericht(ordner, lauf_id, quellen, probelauf=False):
    """Legt einen Laufbericht (JSON) und die zugehörige Kartenseite im Ordner ab; mit probelauf=True unter der
    Endung -probelauf wie bei laden."""
    stamm = f"{lauf_id}-probelauf" if probelauf else lauf_id
    (ordner / f"{stamm}.json").write_text(json.dumps({"lauf_id": lauf_id, "quellen": quellen}))
    (ordner / f"{stamm}-karte.html").write_text("<html></html>")


def _q(name, status="ok", neu=0, geaendert=0, geloescht=0, objekte=10, meldung=None, unvollstaendig=False):
    """Eintrag einer Quelle im Laufbericht: Status, Zähler, Objektzahl, Meldungsentwurf und Merker für einen
    unvollständigen Abruf."""
    return {"quelle": name, "typ": "wfs", "status": status, "meldung": meldung,
            "unvollstaendig": unvollstaendig,
            "zaehler": {"neu": neu, "geaendert": geaendert, "geloescht": geloescht},
            "info": {"objekte": objekte}}


JETZT = datetime(2026, 11, 20, 8, 0, tzinfo=UTC)


def test_status_ok_warnung_kritisch(tmp_path):
    """--status: ohne Bericht CRITICAL, alle Quellen ok ergibt OK, eine angehaltene oder unvollständige Quelle
    WARNING, ein Lauf älter als die Grenze (hier 2 h) CRITICAL."""
    assert betrieb.status(tmp_path, 26, JETZT)[0] == betrieb.KRITISCH  # noch kein Bericht
    _bericht(tmp_path, "20261120T031500Z", [_q("a"), _q("b")])
    code, zeile = betrieb.status(tmp_path, 26, JETZT)
    assert code == betrieb.OK and zeile.startswith("GEODATEN OK") and "quellen_ok=2" in zeile
    _bericht(tmp_path, "20261120T041500Z", [_q("a"), _q("b", status="angehalten")])
    code, zeile = betrieb.status(tmp_path, 26, JETZT)
    assert code == betrieb.WARNUNG and "angehalten: b" in zeile
    _bericht(tmp_path, "20261120T051500Z", [_q("a"), {**_q("b"), "unvollstaendig": True}])
    code, zeile = betrieb.status(tmp_path, 26, JETZT)
    assert code == betrieb.WARNUNG and "unvollständig: b" in zeile
    assert betrieb.status(tmp_path, 2, JETZT)[0] == betrieb.KRITISCH  # zu alt


def test_status_ignoriert_probelauf(tmp_path):
    """Ein jüngerer Probelauf mit Fehler ändert den Status nicht; ausgewertet wird nur der jüngste reguläre
    Bericht."""
    _bericht(tmp_path, "20261120T031500Z", [_q("a")])
    _bericht(tmp_path, "20261120T050000Z", [_q("a", status="fehler")], probelauf=True)
    assert betrieb.status(tmp_path, 26, JETZT)[0] == betrieb.OK


def test_kennzahlen_ueber_zeitraum(tmp_path):
    """--kennzahlen zählt nur Läufe ab `von`, summiert die übernommenen Änderungen, nimmt die Objektzahl je
    Quelle aus ihrem letzten vollständigen Lauf und zählt Störungen und Meldungsentwürfe."""
    _bericht(tmp_path, "20261001T031500Z", [_q("a", neu=10, objekte=10)])
    _bericht(tmp_path, "20261102T031500Z", [_q("a", neu=2, geloescht=1, objekte=11),
                                            _q("b", status="fehler", meldung="m.txt")])
    _bericht(tmp_path, "20261103T031500Z", [_q("a", geaendert=3, objekte=11), _q("b", objekte=48)])
    text = betrieb.kennzahlen(tmp_path, von=datetime(2026, 11, 1, tzinfo=UTC))
    assert "- Läufe: 2" in text
    assert "2 neu, 3 geändert, 1 gelöscht" in text
    assert "Objekte im Bestand nach dem letzten erfolgreichen Lauf je Quelle: 59" in text
    assert "Störungen abgefangen (Quelle fehlgeschlagen oder angehalten, alter Stand blieb): 1" in text
    assert "Meldungsentwürfe an Anbieter: 1" in text


def test_kennzahlen_unvollstaendiger_abruf_ist_kein_erfolg(tmp_path):
    """Codex-Prüfung 05.11., B3: auch die Kennzahlen für Berichte zählen einen Lauf mit Lücke nicht als
    „ok“ (wie Quellenverzeichnis und pipeline_meta); übernommene Änderungen zählen, der Bestand nicht."""
    _bericht(tmp_path, "20261101T031500Z", [_q("a", neu=10, objekte=10)])
    _bericht(tmp_path, "20261102T031500Z", [_q("a", neu=1, objekte=9, unvollstaendig=True)])
    text = betrieb.kennzahlen(tmp_path)
    assert "| a | wfs | 1 | 1 | 0 | 0 | 10 | 11 | 0 | 0 |" in text
    assert "Unvollständige Abrufe (übernommen, nichts gelöscht, beim nächsten Lauf wiederholt): 1" in text


def test_aufraeumen_behaelt_juengsten_bericht_und_verzeichnis(tmp_path):
    """Aufbewahrung (E18): alte Berichte, Probeläufe und Archivordner werden gelöscht; der jüngste reguläre
    Bericht mit allen Dateien seiner Laufkennung und das Quellenverzeichnis bleiben, auch wenn sie älter
    als die Frist sind."""
    _bericht(tmp_path, "20260101T031500Z", [_q("a")])
    _bericht(tmp_path, "20260102T031500Z", [_q("a")])
    _bericht(tmp_path, "20260103T031500Z", [_q("a")], probelauf=True)
    (tmp_path / "20260102T031500Z-meldung-a.txt").write_text("x")
    archiv = tmp_path / "archiv" / "20260101T031500Z"
    archiv.mkdir(parents=True)
    (archiv / "a.geojson.gz").write_bytes(b"x")
    (tmp_path / "quellenverzeichnis.md").write_text("x")
    weg = betrieb.aufraeumen(tmp_path, 180, JETZT)  # alles ist älter als 180 Tage
    rest = sorted(p.name for p in tmp_path.iterdir())
    # Der jüngste reguläre Bericht ist der Vergleichsstand für den nächsten Lauf und bleibt
    assert "20260102T031500Z.json" in rest and "20260102T031500Z-karte.html" in rest
    assert "20260102T031500Z-meldung-a.txt" in rest and "quellenverzeichnis.md" in rest
    assert "20260101T031500Z.json" not in rest and "20260103T031500Z-probelauf.json" not in rest
    assert not archiv.exists() and "20260101T031500Z" in weg


def test_aufraeumen_laesst_junges_stehen(tmp_path):
    """Liegen alle Läufe innerhalb der Frist, löscht aufraeumen nichts."""
    _bericht(tmp_path, "20261110T031500Z", [_q("a")])
    _bericht(tmp_path, "20261119T031500Z", [_q("a")])
    assert betrieb.aufraeumen(tmp_path, 30, JETZT) == []


def test_status_meldet_technischen_abbruch(tmp_path):
    """Ein Bericht mit `abbruch` (technischer Abbruch des Laufs, E34) ergibt CRITICAL mit dem Hinweis
    „technisch abgebrochen“."""
    (tmp_path / "20261120T071500Z.json").write_text(json.dumps(
        {"lauf_id": "20261120T071500Z", "quellen": [], "abbruch": "OperationalError: keine Verbindung"}))
    code, zeile = betrieb.status(tmp_path, 26, JETZT)
    assert code == betrieb.KRITISCH and "technisch abgebrochen" in zeile


def test_status_unvollstaendig_ist_kein_erfolg(tmp_path):
    """Prüfung 05.11., Runde 2 (E42): --status rechnet wie Quellenverzeichnis und pipeline_meta. Der Messwert
    quellen_ok zählt nur vollständige Abrufe; sind alle geladenen Quellen unvollständig, ist keine ok."""
    _bericht(tmp_path, "20261120T051500Z", [_q("a"), _q("b", unvollstaendig=True)])
    code, zeile = betrieb.status(tmp_path, 26, JETZT)
    assert code == betrieb.WARNUNG and "quellen_ok=1 " in zeile and "unvollstaendig=1 " in zeile
    # Seit E44 (Code-Review, F2): Auch wenn alle geladenen Quellen unvollständig sind, ist das WARNING. Mit
    # Rhythmen lädt ein Lauf oft nur eine Quelle; eine Lücke dort ist kein Ausfall der Pipeline.
    _bericht(tmp_path, "20261120T061500Z", [_q("a", unvollstaendig=True), _q("b", unvollstaendig=True),
                                            _q("c", status="nicht_faellig")])
    code, zeile = betrieb.status(tmp_path, 26, JETZT)
    assert code == betrieb.WARNUNG and "unvollständig: a, b" in zeile
    assert "quellen_ok=0 " in zeile


def test_status_kritisch_nur_ohne_ok_und_ohne_unvollstaendig(tmp_path):
    """E44, F2: CRITICAL, wenn keine geladene Quelle ok oder unvollständig ist (alle fehlgeschlagen oder
    angehalten); eine unvollständige neben einer fehlgeschlagenen bleibt WARNING."""
    _bericht(tmp_path, "20261120T051500Z", [_q("a", status="fehler"), _q("b", status="angehalten"),
                                            _q("c", status="nicht_faellig")])
    code, zeile = betrieb.status(tmp_path, 26, JETZT)
    assert code == betrieb.KRITISCH and "keine Quelle ok oder unvollständig" in zeile
    assert "fehlgeschlagen: a" in zeile and "angehalten: b" in zeile
    _bericht(tmp_path, "20261120T061500Z", [_q("a", status="fehler"), _q("b", unvollstaendig=True)])
    code, zeile = betrieb.status(tmp_path, 26, JETZT)
    assert code == betrieb.WARNUNG and "fehlgeschlagen: a; unvollständig: b" in zeile
    _bericht(tmp_path, "20261120T071500Z", [_q("c", status="nicht_faellig")])   # nichts fällig
    assert betrieb.status(tmp_path, 26, JETZT)[0] == betrieb.OK


def test_abgeschnittener_bericht_blockiert_nichts(tmp_path):
    """E42: Ein abgeschnittener Bericht (SIGKILL oder volle Platte beim Schreiben, vor dem atomaren Ersetzen)
    hielt jeden späteren Lauf an (letzter_bericht), dazu --status und --kennzahlen. Jetzt wird er
    übersprungen; ist er der jüngste, meldet --status CRITICAL mit Grund statt einer Ausnahme."""
    from pipeline import waechter
    _bericht(tmp_path, "20261120T031500Z", [_q("a", neu=2)])
    (tmp_path / "20261120T041500Z.json").write_text('{"lauf_id": "20261120T041500Z", "quellen": [{"que')
    assert waechter.letzter_bericht(tmp_path, "20261120T051500Z")["a"]["zaehler"]["neu"] == 2
    code, zeile = betrieb.status(tmp_path, 26, JETZT)
    assert code == betrieb.KRITISCH and "20261120T041500Z.json nicht lesbar" in zeile
    text = betrieb.kennzahlen(tmp_path)
    assert "- Läufe: 1" in text and "nicht lesbar, übersprungen: 1 (20261120T041500Z.json)" in text
    _bericht(tmp_path, "20261120T051500Z", [_q("a")])
    assert betrieb.status(tmp_path, 26, JETZT)[0] == betrieb.OK


def test_berichte_werden_atomar_ersetzt(tmp_path, monkeypatch):
    """E42: Schlägt das Schreiben fehl, bleibt die alte Fassung ganz stehen, keine Restdatei."""
    from pipeline import verzeichnis
    datei = tmp_path / "20261120T031500Z.json"
    verzeichnis.schreiben(datei, '{"alt": 1}')

    echt = type(datei).write_text

    def kaputt(self, text, encoding=None):
        """Schreibt nur den Anfang und meldet dann eine volle Platte, wie ein Abbruch mitten im Schreiben."""
        echt(self, text[:3], encoding=encoding)
        raise OSError("No space left on device")
    monkeypatch.setattr(type(datei), "write_text", kaputt)
    with pytest.raises(OSError, match="No space"):
        verzeichnis.schreiben(datei, '{"neu": 2}')
    monkeypatch.undo()
    assert datei.read_text() == '{"alt": 1}'
    assert [p.name for p in tmp_path.iterdir()] == [datei.name]


def test_status_bleibt_eine_zeile_bei_mehrzeiligem_fehler(tmp_path):
    """Nachprüfung zu E46: Ein Fehler aus PL/pgSQL trägt eine Zeile CONTEXT, psycopg trennt Teile mit
    Zeilenumbruch. Die Perfdata standen dann auf Zeile 2, die die Überwachung nicht liest."""
    b = {"lauf_id": "20261120T031500Z", "quellen": [_q("a")],
         "katalog": {"view": "public.source_granularities", "ergebnis": "fehler",
                     "fehler": "DivisionByZero: division by zero\nCONTEXT:  SQL statement \"REFRESH …\""}}
    (tmp_path / "20261120T031500Z.json").write_text(json.dumps(b))
    code, zeile = betrieb.status(tmp_path, 26, JETZT)
    assert code == betrieb.WARNUNG and "\n" not in zeile
    assert "division by zero CONTEXT: SQL" in zeile and zeile.endswith("alter_h=4.8;;26")
    b["abbruch"] = "OperationalError: server closed the connection unexpectedly\n\tThis probably means …"
    (tmp_path / "20261120T031500Z.json").write_text(json.dumps(b))
    code, zeile = betrieb.status(tmp_path, 26, JETZT)
    assert code == betrieb.KRITISCH and " | quellen_ok=1 " in zeile
    assert "\n" not in zeile and "\t" not in zeile


# --- E50: Schnellstart und Aussagen der README (Befunde W8, W9, G2) ----------------------------------------

_WURZEL = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("datei, dienst", [("docker-compose.yml", "pipeline"),
                                           ("deploy/mosidi/docker-compose.pipeline.yml", "pipeline")])
def test_compose_reicht_die_abgelegte_inkar_datei_durch(datei, dienst):
    """E50, Befund W8: Beide Compose-Dateien reichen PIPELINE_INKAR_DATEI an den Dienst pipeline durch (leer =
    Abruf per URL mit Freigabe). Bis E49 genügte ein Eintrag in .env nicht, die Variable kam im Container
    nicht an."""
    import yaml
    cfg = yaml.safe_load((_WURZEL / datei).read_text(encoding="utf-8"))
    assert cfg["services"][dienst]["environment"]["PIPELINE_INKAR_DATEI"] == "${PIPELINE_INKAR_DATEI:-}"


def test_readme_schnellstart_regelbetrieb_und_prueflauf():
    """E50, Befund W8: Der Schnellstart der README (de, en) erklärt den Regelbetrieb (INKAR automatisch per
    URL mit robots_freigabe) und den Prüflauf mit abgelegter Datei (PIPELINE_INKAR_DATEI)."""
    for name, kopf in (("README.md", "\n## Start"), ("README.en.md", "\n## Getting started")):
        text = (_WURZEL / name).read_text(encoding="utf-8")
        start = text.split(kopf, 1)[1].split("\n## ", 1)[0]
        assert "robots_freigabe" in start and "PIPELINE_INKAR_DATEI" in start, name


def test_readme_ohne_absolute_zusagen_und_mit_einheitlicher_einheit():
    """E50, Befunde W9 und G2: Die README sagt nicht mehr „ohne Handimport“ und keinen pauschalen Schutz vor
    Bestandsbeschädigung zu, „Quellen der TH schon angebunden“ ist auf das Belegte zurückgenommen, und die
    Speichergrenze heißt überall 1 GiB (mem_limit: 1g ist binär), auch in docs/betrieb.md."""
    de = (_WURZEL / "README.md").read_text(encoding="utf-8")
    en = (_WURZEL / "README.en.md").read_text(encoding="utf-8")
    for falsch in ("ohne Handimport", "den Bestand nicht beschädigt", "Quellen der TH schon angebunden"):
        assert falsch not in de, falsch
    for falsch in ("without manual import", "cannot damage", "already connected"):
        assert falsch not in en, falsch
    for name in ("README.md", "README.en.md", "docs/betrieb.md"):
        assert "1 GB" not in (_WURZEL / name).read_text(encoding="utf-8"), name


# --- E50, Nachprüfung (Prüfer zu E50, 06.11.2026) -------------------------------------------------------

def test_beleg_skripte_rufen_inkar_nie_per_url_ab():
    """Nachprüfung zu E50: Seit E50 trägt die ausgelieferte Konfiguration die Freigabe für den INKAR-Abruf per
    URL. Ein archiviertes Belegskript, das das aktuelle config/ einhängt und PIPELINE_INKAR_DATEI nicht setzt,
    riefe beim erneuten Start www.bbr-server.de ab (HEAD-Suche und rund 430 MB), gegen unsere Regel, den
    Rechner nie selbst abzurufen. Jedes Skript unter beispielberichte/ und deploy/ setzt deshalb
    PIPELINE_INKAR_DATEI oder bricht als abgelöst ab, bevor es Docker aufruft."""
    skripte = sorted([*(_WURZEL / "beispielberichte").rglob("*.sh"), *(_WURZEL / "deploy").rglob("*.sh")])
    assert len(skripte) >= 9
    for skript in skripte:
        zeilen = skript.read_text(encoding="utf-8").splitlines()
        if any("PIPELINE_INKAR_DATEI:" in z for z in zeilen):
            continue
        befehle = [z.strip() for z in zeilen if z.strip() and not z.lstrip().startswith("#")]
        erster = next(i for i, z in enumerate(befehle) if "exit" in z or "docker" in z or "dc " in z)
        assert "Abgelöst" in befehle[erster] and "exit 1" in befehle[erster], skript


def test_doku_ohne_absolute_zusagen_und_mit_einheitlicher_einheit():
    """Nachprüfung zu E50, Befunde W9 und G2: Der Test aus E50 prüfte nur README.md, README.en.md und
    docs/betrieb.md, und nur auf die alten Wortlaute; gleichbedeutende neue Sätze („ohne Handarbeit“, „without
    manual work“) und docs/rundgang.md und docs/sicherheit.md blieben ungeprüft. Jetzt alle fünf, mit den
    neuen Wortlauten."""
    namen = ("README.md", "README.en.md", "docs/betrieb.md", "docs/rundgang.md", "docs/sicherheit.md")
    texte = {n: (_WURZEL / n).read_text(encoding="utf-8") for n in namen}
    for name, text in texte.items():
        assert "1 GB" not in text, name
        for falsch in ("ohne Handimport", "ohne Handarbeit", "den Bestand nicht beschädigt",
                       "Bestand nicht beschädigen", "Quellen der TH schon angebunden",
                       "without manual import",
                       "without manual work", "cannot damage", "already connected"):
            assert falsch not in text, (name, falsch)
    assert "könnte keine Tabellen löschen und kein Schema ändern" not in texte["docs/rundgang.md"]


# --- E51: Prüfbericht vom 07.11.2026, 03:13 (W2 Gesamtabbruch, G2 Prüfwerkzeuge) ----------------------------

@pytest.mark.parametrize("unit", ["deploy/systemd/geodaten-import.service",
                                  "deploy/mosidi/geodaten-import-mosidi.service"])
def test_gesamtabbruch_liegt_ueber_den_zeitbudgets_der_lieferkonfiguration(unit):
    """E51, Befund W2: Der Abbruch des ganzen Laufs (TimeoutStartSec der systemd-Units) muss über der Summe
    der Zeitbudgets aller aktiven Quellen der Lieferkonfiguration liegen, mit Reserve für Verbindung, Katalog
    und Berichte; sonst beendet systemd den Lauf, bevor das Zeitbudget einer Quelle greift und die nächste
    Quelle laufen kann. Bis E50: 2 h gegen 146,5 min gemessenen INKAR-Vollumfang."""
    import re

    import yaml

    from pipeline import laden
    cfg = yaml.safe_load((_WURZEL / "config" / "quellen.yaml").read_text(encoding="utf-8"))
    summe = sum(laden.zeitbudget(cfg, q) for q in cfg["quellen"].values() if q.get("aktiv", True))
    (wert,) = re.findall(r"^TimeoutStartSec=(\d+)h$", (_WURZEL / unit).read_text(encoding="utf-8"), re.M)
    assert int(wert) * 60 >= summe + 30, (wert, summe)


def test_pruefwerkzeuge_mit_fester_version():
    """E51, Befund G2: Jedes Prüfwerkzeug in pruefen.sh und im Datenbank-Job der CI läuft in einer festen
    Version (uvx werkzeug@version, --from paket==version, --with pytest==version), damit ein Prüflauf später
    dieselben Werkzeuge nutzt. Deren eigene Abhängigkeiten sind nicht festgeschrieben (docs/sicherheit.md)."""
    import re
    for datei in ("pruefen.sh", ".github/workflows/pruefen.yml"):
        text = (_WURZEL / datei).read_text(encoding="utf-8")
        befehle = [z.split("#")[0] for z in text.splitlines() if re.search(r"\buvx\b|--with pytest", z)
                   and not z.lstrip().startswith("#")]
        for z in befehle:
            if "--from" in z:
                assert re.search(r"--from [\w-]+==\d", z), (datei, z)
            elif re.search(r"\buvx\b", z):
                assert re.search(r"\buvx (?:-q )?[\w-]+@\d", z), (datei, z)
            if "--with pytest" in z:
                assert re.search(r"--with pytest==\d", z), (datei, z)
