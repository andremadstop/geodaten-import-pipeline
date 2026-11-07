"""Änderungskarte ohne Drittverbindungen (Codex-Prüfung B11, E38): Leaflet eingebettet und gegen die
veröffentlichten Prüfsummen geprüft, Hintergrundkarten nur ausdrücklich, `karte: false` ohne Datei.

pipeline.karte schreibt nach dem Abgleich (ziel) je Lauf eine einzelne HTML-Seite. Abgesichert wird
außerdem, dass Werte aus den Quellen die Datenblöcke der Seite nicht verlassen können (Parser-Falle mit
"<!--<script", E39) und dass die Lizenzbedingungen von Leaflet in jeder einzelnen Seite stehen.
"""
import base64
import hashlib
import json
import re

import pytest

from pipeline import karte

BERICHT = {"lauf_id": "20261105T070000Z", "quellen": [{"quelle": "q", "status": "ok",
                                                         "zaehler": {"neu": 1, "geaendert": 0,
                                                                     "geloescht": 0, "unveraendert": 0}}]}
OBJEKT = {"type": "Feature", "geometry": {"type": "Point", "coordinates": [12.5, 52.4]},
          "properties": {"id": "x", "status": "neu", "werte": {"name": "Beispiel"}}}
DRITTE = ("unpkg.com", "geodatenzentrum.de", "geobasis-bb.de")


def test_leaflet_im_repository_entspricht_der_veroeffentlichten_fassung():
    """Die eingebetteten Leaflet-Dateien haben die in karte.LEAFLET_SHA256 hinterlegten Prüfsummen (SHA-256,
    Base64), und der BSD-2-Clause-Lizenztext liegt im Ordner."""
    for datei, soll in karte.LEAFLET_SHA256.items():
        ist = base64.b64encode(hashlib.sha256((karte.LEAFLET / datei).read_bytes()).digest()).decode()
        assert ist == soll, datei
    assert "BSD 2-Clause" in (karte.LEAFLET / "LICENSE").read_text(encoding="utf-8")


def _nachladen(html: str) -> list[str]:
    """Alles, was der Browser beim Öffnen von außen holen würde: src/href in Tags, url() in CSS."""
    tags = re.findall(r"<(?:script|link|img|iframe)\b[^>]*\b(?:src|href)\s*=\s*[\"']?([^\"' >]+)", html, re.I)
    css = [u for u in re.findall(r"url\(\s*[\"']?([^\"')]+)", html) if re.match(r"(?i)(https?:)?//", u)]
    return tags + css


def test_standard_ohne_hintergrund_laedt_nichts_nach(tmp_path):
    """Ohne Einstellung enthält die Seite keinen Verweis nach außen (kein src/href, kein url() mit Rechner)
    und keinen Rechner Dritter; Leaflet steht eingebettet mit Lizenzangabe darin, die Liste der
    Hintergrundkarten ist leer."""
    datei = tmp_path / "k.html"
    karte.schreiben(datei, BERICHT, {"q": [OBJEKT]}, karte.hintergruende({}))
    html = datei.read_text(encoding="utf-8")
    assert _nachladen(html) == []
    assert not any(d in html for d in DRITTE)
    assert "Leaflet 1.9.4" in html and "BSD-2-Clause" in html
    assert '<script id="grundkarten" type="application/json">[]</script>' in html


def test_hintergrund_nur_wenn_ausdruecklich_eingestellt(tmp_path):
    """Ausdrücklich eingestellte Hintergrundkarten stehen mit ihren Adressen als Daten in der Seite, werden
    aber nicht als Tag geladen; unpkg.com kommt nicht mehr vor."""
    datei = tmp_path / "k.html"
    cfg = {"karte": {"hintergrund": ["basemap", "luftbild"]}}
    karte.schreiben(datei, BERICHT, {"q": [OBJEKT]}, karte.hintergruende(cfg))
    html = datei.read_text(encoding="utf-8")
    assert "sgx.geodatenzentrum.de" in html and "isk.geobasis-bb.de" in html
    assert "unpkg.com" not in html and _nachladen(html) == []   # Kacheln holt erst Leaflet, nach Wahl


def test_karte_false_und_falsche_hintergruende():
    """Nur `karte: false` schaltet die Karte ab; eine einzelne Hintergrundkarte als Text wird zur Liste,
    `karte: true` heißt ohne Hintergrund, und ein unbekannter Name bricht mit ValueError ab."""
    assert karte.aktiv({}) and karte.aktiv({"karte": {"hintergrund": "basemap"}})
    assert not karte.aktiv({"karte": False})
    assert karte.hintergruende({"karte": {"hintergrund": "basemap"}}) == ["basemap"]
    assert karte.hintergruende({"karte": True}) == []
    with pytest.raises(ValueError, match="unbekannt osm"):
        karte.hintergruende({"karte": {"hintergrund": ["osm"]}})


def _bloecke(html: str) -> dict[str, str]:
    """Alle JSON-Datenblöcke der Seite als Zuordnung id → Inhalt."""
    return dict(re.findall(r'<script id="(\w+)" type="application/json">(.*?)</script>', html, re.S))


def test_werte_aus_der_quelle_koennen_die_seite_nicht_brechen(tmp_path):
    """Pre-existing (vor E38): "<!--<script" in einem Attributwert versetzte den HTML-Parser im
    Datenblock in "script data double escaped"; das </script> des Blocks beendete ihn nicht mehr,
    der Block schluckte das Anwendungsskript, die Karte blieb leer. Jetzt steht in den Datenblöcken
    kein "<", ">" oder "&" mehr, JSON.parse liest dieselben Werte."""
    boese = "Haus <!--<script>alert(1)</script> & </SCRIPT >"
    objekt = {**OBJEKT, "properties": {**OBJEKT["properties"], "id": boese, "werte": {"name": boese}}}
    bericht = {**BERICHT, "quellen": [{**BERICHT["quellen"][0], "quelle": boese, "warnungen": [boese]}]}
    datei = tmp_path / "k.html"
    karte.schreiben(datei, bericht, {boese: [objekt]})
    html = datei.read_text(encoding="utf-8")
    bloecke = _bloecke(html)
    assert set(bloecke) == {"texte", "grundkarten", "daten"}
    for inhalt in bloecke.values():
        assert not any(z in inhalt for z in "<>&")
    q = json.loads(bloecke["daten"])["quellen"][0]
    assert q["name"] == q["warnungen"][0] == boese
    assert q["objekte"]["features"][0]["properties"]["werte"]["name"] == boese
    # das Anwendungsskript steht weiterhin als eigener Block hinter den Daten
    assert html.index('<script id="daten"') < html.rindex("JSON.parse(document.getElementById(\"daten\")")


def test_lizenzbedingungen_von_leaflet_stehen_in_der_seite(tmp_path):
    """BSD-2-Clause, Klausel 2: Bedingungen und Haftungsausschluss reisen mit der einzelnen Seite."""
    datei = tmp_path / "k.html"
    karte.schreiben(datei, BERICHT, {"q": [OBJEKT]})
    html = datei.read_text(encoding="utf-8")
    anfang = html.index("<!--")
    ende = html.index("-->", anfang)
    kommentar = html[anfang:ende]
    for satz in ("Copyright (c) 2010-2023, Volodymyr Agafonkin",
                 "Redistributions in binary form must reproduce",
                 "THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS",
                 "EVEN IF ADVISED OF THE POSSIBILITY"):
        assert satz in kommentar, satz
    assert "@@" not in html   # keine Marke übrig
