"""Tests der Sprachdateien: Englisch, Rückfall auf Deutsch, neue Sprache ohne Code.

Textbericht, Meldungsentwurf, Quellenverzeichnis und Änderungskarte holen ihre Texte aus
pipeline/sprachen/*.json (E21). Abgesichert wird: Englisch wirkt in allen vier Ausgaben, fehlende Texte
fallen auf Deutsch zurück, PIPELINE_SPRACHE geht vor der Konfiguration, ungültige Codes ergeben Deutsch,
und alle Sprachdateien haben dieselben Platzhalter wie de.json.
"""
import json
import shutil

import pytest

from pipeline import karte, laden, sprache, verzeichnis, waechter

BERICHT = {"lauf_id": "20261030T074334Z", "laufzeit_s": 5.5, "karte": "k.html", "quellen": [
    {"quelle": "kreise_bkg", "status": "ok",
     "zaehler": {"neu": 48, "geaendert": 0, "geloescht": 0, "unveraendert": 0}, "warnungen": [],
     "hinweise": ["Dienst meldet ImplementsSorting=FALSE"]},
    {"quelle": "kaputt", "status": "fehler", "fehler": "ConnectionError: x", "meldung": "m.txt"}]}
EINTRAG = {"status": "angehalten", "warnungen": ["Quelle lieferte 10 statt bisher 882 Objekte"],
           "letzte_abfrage": "https://dienst.example/ows?REQUEST=GetFeature",
           "info": {"kontakt": {"anbieter": "Amt", "email": "service@amt.example"}}}


@pytest.fixture(autouse=True)
def frisch(monkeypatch):
    """Setzt vor und nach jedem Test die Sprachwahl zurück (PIPELINE_SPRACHE entfernt, Zwischenspeicher von
    sprache.texte geleert), damit kein Test die Sprache eines anderen bestimmt."""
    monkeypatch.delenv("PIPELINE_SPRACHE", raising=False)
    sprache.texte.cache_clear()
    yield
    sprache.texte.cache_clear()


def test_textbericht_englisch():
    """Mit `sprache: en` steht der Textbericht auf Englisch (Kopf, Zähler, Fehler, Verweise auf
    Meldungsentwurf und Karte); Hinweise aus dem Lauf bleiben im Wortlaut, in dem sie entstanden sind."""
    text = laden.zusammenfassung({**BERICHT, "sprache": "en"})
    assert text.startswith("Import run 20261030T074334Z · 5.5 s\n")
    assert "ok     new    48  changed     0  deleted     0  unchanged     0" in text
    assert "ERROR ConnectionError: x" in text and "Draft report to the provider: m.txt" in text
    assert "      Note: Dienst meldet ImplementsSorting=FALSE" in text  # Hinweis selbst bleibt deutsch
    assert "Change map: k.html" in text


def test_textbericht_ohne_sprache_bleibt_deutsch():
    """Ohne Angabe einer Sprache ist der Textbericht deutsch."""
    text = laden.zusammenfassung(BERICHT)
    assert "ok     neu    48  geändert     0  gelöscht     0  unverändert     0" in text
    assert "FEHLER ConnectionError: x" in text


def test_meldung_englisch():
    """Der englische Meldungsentwurf beginnt mit dem Hinweis, dass nichts automatisch versandt wird, und nennt
    Empfänger, Zeit im ISO-Format und die Abfrage-URL."""
    text = waechter.meldung_text("q", {"typename": "x:y"}, EINTRAG, "20261030T074334Z", "en")
    assert text.startswith("DRAFT, not sent automatically.")
    assert "To: service@amt.example" in text and "2026-10-30, 07:43 UTC" in text
    assert "Dear Sir or Madam" in text and "https://dienst.example/ows?REQUEST=GetFeature" in text


def test_verzeichnis_englisch_mit_rueckfall_fuer_fehlenden_text():
    """Das Quellenverzeichnis auf Englisch; ein Text, den en.json nicht hat (hier der Strich für leere
    Felder), kommt aus de.json."""
    stand = {"q": {"typ": "wfs", "anbieter": None, "email": None, "lizenz": None, "letzter_erfolg": None,
                   "objekte": None, "ergebnis": "angehalten", "letzter_lauf": "20261030T070000Z"}}
    md = verzeichnis.als_markdown(stand, "en")
    assert md.startswith("# Source register\n")
    # en.json hat keinen Eintrag „leer“: es gilt der deutsche Strich
    assert "| q | wfs | – | – | – | never | – | stopped, 2026-10-30 07:00 UTC |" in md


def test_karte_englisch(tmp_path):
    """Die Änderungskarte auf Englisch: lang-Attribut, Titel, Texte im Datenblock und Beschriftung der
    Hintergrundkarten."""
    datei = tmp_path / "k.html"
    karte.schreiben(datei, {**BERICHT, "sprache": "en"}, {}, ["basemap", "luftbild"])
    html = datei.read_text(encoding="utf-8")
    assert '<html lang="en">' in html and "<title>Import run 2026-10-30, 07:43 UTC</title>" in html
    texte = json.loads(html.split('<script id="texte" type="application/json">')[1].split("</script>")[0])
    assert texte["aenderung"]["geaendert"] == "changed" and texte["grundkarte"] == "Base map:"
    assert texte["ohne_grund"].startswith("No background map")
    grund = html.split('<script id="grundkarten" type="application/json">')[1].split("</script>")[0]
    grund = json.loads(grund)
    assert [g["text"] for g in grund] == ["Map", "Aerial"]


def test_neue_sprache_ist_nur_eine_datei(tmp_path, monkeypatch):
    """Eine neue Sprache braucht nur eine JSON-Datei im Sprachordner, keinen Code; was sie nicht übersetzt,
    fällt auf Deutsch zurück."""
    ordner = tmp_path / "sprachen"
    shutil.copytree(sprache.ORDNER, ordner)
    (ordner / "nl.json").write_text(json.dumps({"bericht": {"art_import": "Importrun"}}), encoding="utf-8")
    monkeypatch.setattr(sprache, "ORDNER", ordner)
    text = laden.zusammenfassung({**BERICHT, "sprache": "nl"})
    assert text.startswith("Importrun ")
    assert "geändert" in text  # alles Übrige fällt auf Deutsch zurück


def test_wahl_umgebung_vor_konfiguration_und_ungueltiges_wird_deutsch(monkeypatch):
    """PIPELINE_SPRACHE geht vor `sprache:` aus der Konfiguration, die Schreibweise zählt nicht, und ein
    ungültiger Code (etwa ein Pfad) ergibt Deutsch, sodass aus der Umgebung kein Dateipfad entstehen kann."""
    assert sprache.wahl({}) == "de"
    assert sprache.wahl({"sprache": "EN"}) == "en"
    monkeypatch.setenv("PIPELINE_SPRACHE", "en")
    assert sprache.wahl({"sprache": "de"}) == "en"
    monkeypatch.setenv("PIPELINE_SPRACHE", "../../etc/passwd")
    assert sprache.wahl({}) == "de"


def test_unbekannte_sprache_faellt_auf_deutsch_zurueck():
    """Für einen Sprachcode ohne Datei liefert sprache.texte die deutschen Texte."""
    assert sprache.texte("xx") == sprache.texte("de")


def test_sprachdateien_haben_dieselben_platzhalter():
    """Ein vergessener oder vertippter Platzhalter fiele erst im Betrieb auf."""
    import string

    def felder(d, pfad=""):
        """Liefert je Text den Schlüsselpfad (a.b.c) und die Menge seiner Platzhalter im Format von
        str.format."""
        for k, v in d.items():
            if isinstance(v, dict):
                yield from felder(v, f"{pfad}{k}.")
            elif isinstance(v, str):
                yield f"{pfad}{k}", {f[1] for f in string.Formatter().parse(v) if f[1]}
    de = dict(felder(sprache.texte("de")))
    for code in [p.stem for p in sprache.ORDNER.glob("*.json") if p.stem != "de"]:
        eigen = dict(felder(json.loads((sprache.ORDNER / f"{code}.json").read_text(encoding="utf-8"))))
        for schluessel, platz in eigen.items():
            assert schluessel in de, f"{code}: {schluessel} gibt es auf Deutsch nicht"
            assert platz == de[schluessel], f"{code}: {schluessel} hat andere Platzhalter"
