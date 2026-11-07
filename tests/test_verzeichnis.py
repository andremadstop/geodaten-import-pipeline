"""Tests des Quellenverzeichnisses: Erfolg aktualisiert, Fehler behält den letzten guten Stand.

pipeline.verzeichnis schreibt nach jedem Lauf quellenverzeichnis.json und .md (Typ, Anbieter, Kontakt,
Lizenz, letzter Erfolg, Objekte, Ergebnis). Abgesichert wird: ein Fehler oder ein unvollständiger Abruf
überschreibt den letzten Erfolg nicht (E32, Prüfung vom 05.11.). Dazu zwei Tests zu anderen Modulen:
waechter.letzter_bericht wählt keinen Probelauf als Vergleichsstand, und karte.schreiben setzt
Quelldaten nur als Text in die Seite.
"""
from pipeline import verzeichnis, waechter

CFG = {"quellen": {"q": {"url": "https://dienst.example/ows", "lizenz": "dl-de/by-2-0"}}}


def bericht(lauf_id, status, objekte=None, unvollstaendig=False):
    """Minimaler Laufbericht mit der einen WFS-Quelle q, so aufgebaut wie der Bericht aus laden; `objekte`
    fehlt im Info-Teil, wenn None übergeben wird."""
    info = {"kontakt": {"anbieter": "Amt", "email": "service@amt.example"}}
    if objekte is not None:
        info["objekte"] = objekte
    return {"lauf_id": lauf_id, "quellen": [{"quelle": "q", "typ": "wfs", "status": status, "info": info,
                                             "unvollstaendig": unvollstaendig}]}


def test_fehler_behaelt_letzten_erfolg(tmp_path):
    """Nach einem Fehler bleiben letzter Erfolg und Objektzahl des Vorlaufs stehen, nur das Ergebnis wechselt
    auf „fehler“; die Markdown-Zeile nennt Typ, Anbieter, Kontakt, Lizenz, Zeit in UTC und Objektzahl."""
    verzeichnis.aktualisieren(tmp_path, bericht("20261030T070000Z", "ok", 48), CFG)
    stand = verzeichnis.aktualisieren(tmp_path, bericht("20261031T070000Z", "fehler"), CFG)
    e = stand["q"]
    assert (e["letzter_erfolg"], e["objekte"], e["ergebnis"]) == ("20261030T070000Z", 48, "fehler")
    md = (tmp_path / "quellenverzeichnis.md").read_text(encoding="utf-8")
    assert "| q | wfs | Amt | service@amt.example | dl-de/by-2-0 | 30.10.2026 07:00 UTC | 48 |" in md


def test_unvollstaendiger_abruf_ist_kein_erfolg(tmp_path):
    """Codex-Prüfung 05.11., B3: Status ok mit Lücke (unvollstaendig) ist im Verzeichnis kein Erfolg,
    wie in pipeline_meta.quellenstand (letzter_erfolg bleibt, E32); erst der vollständige Lauf zählt."""
    verzeichnis.aktualisieren(tmp_path, bericht("20261030T070000Z", "ok", 48), CFG)
    stand = verzeichnis.aktualisieren(tmp_path, bericht("20261031T070000Z", "ok", 47, unvollstaendig=True),
                                      CFG)
    e = stand["q"]
    assert (e["letzter_erfolg"], e["objekte"], e["ergebnis"]) == ("20261030T070000Z", 48, "unvollstaendig")
    md = (tmp_path / "quellenverzeichnis.md").read_text(encoding="utf-8")
    assert "| 30.10.2026 07:00 UTC | 48 | unvollständig (nichts gelöscht, wird wiederholt), 31.10.2026" in md
    e = verzeichnis.aktualisieren(tmp_path, bericht("20261101T070000Z", "ok", 48), CFG)["q"]
    assert (e["letzter_erfolg"], e["objekte"], e["ergebnis"]) == ("20261101T070000Z", 48, "ok")


def test_probelauf_zaehlt_nicht_als_vergleichsstand(tmp_path):
    """waechter.letzter_bericht übergeht Probelauf-Berichte (Endung -probelauf) und das Quellenverzeichnis:
    Vergleichsstand bleibt der letzte reguläre Lauf, auch wenn der Probelauf jünger ist."""
    (tmp_path / "20261030T070000Z.json").write_text('{"quellen": [{"quelle": "q", "n": 1}]}')
    (tmp_path / "20261030T080000Z-probelauf.json").write_text('{"quellen": [{"quelle": "q", "n": 2}]}')
    (tmp_path / "quellenverzeichnis.json").write_text("{}")
    assert waechter.letzter_bericht(tmp_path, "20261030T090000Z")["q"]["n"] == 1


def test_karte_setzt_quelldaten_nur_als_text(tmp_path):
    """Attribute aus der Quelle dürfen die Seite nicht verlassen: kein </script> im Datenblock."""
    from pipeline import karte
    feature = {"type": "Feature", "geometry": {"type": "Point", "coordinates": [12.5, 52.4]},
               "properties": {"id": "x", "status": "neu",
                              "werte": {"name": "</script><script>alert(1)</script>"}}}
    bericht = {"lauf_id": "20261030T070000Z", "quellen": [{"quelle": "q", "status": "ok"}]}
    datei = tmp_path / "k.html"
    karte.schreiben(datei, bericht, {"q": [feature]})
    html = datei.read_text(encoding="utf-8")
    daten = html.split('<script id="daten" type="application/json">')[1].split("</script>")[0]
    assert "</" not in daten and "alert(1)" in daten  # nur ein schließendes Tag beendet den Block
