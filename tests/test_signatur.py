"""Signatur für --version: Umriss, Kopfzeile, Notiz des Tages in beiden Sprachen.

pipeline.signatur gehört nicht zum Ablauf laden → quellen → ziel, laden.main gibt den Text nur bei
`--version` aus. Abgesichert wird, dass die Ausgabe allein vom Datum abhängt (kein Zufall, also
nachstellbar) und ein unbekannter Sprachcode wie bei den Sprachdateien auf Deutsch zurückfällt (E21).
"""
from datetime import date

from pipeline import signatur


def _flach(t: str) -> str:
    """Fasst allen Leerraum zu einzelnen Leerzeichen zusammen, damit die mit textwrap umbrochene Notiz wieder
    als ein Satz mit dem Eintrag in NOTIZEN vergleichbar ist."""
    return " ".join(t.split())


def test_umriss_und_notiz_des_tages():
    """Die deutsche Signatur enthält den Umriss mit der Marke „o“ für die TH, den Lizenzhinweis Apache-2.0 und
    eine der deutschen Notizen."""
    text = signatur.text("de", date(2026, 11, 2))
    assert "o" in signatur.UMRISS and "Apache-2.0" in text
    assert any(n in _flach(text) for n in signatur.NOTIZEN["de"])


def test_notiz_wechselt_taeglich_ohne_zufall():
    """Dasselbe Datum ergibt zweimal dieselbe Signatur, der Folgetag eine andere: Die Notiz hängt nur am
    Datum, nicht am Zufall."""
    a = signatur.text("de", date(2026, 11, 2))
    assert a == signatur.text("de", date(2026, 11, 2))
    assert a != signatur.text("de", date(2026, 11, 3))


def test_englisch_und_rueckfall():
    """Englisch liefert eine englische Notiz, ein unbekannter Sprachcode fällt auf die deutschen Notizen
    zurück, und beide Sprachen haben gleich viele Notizen."""
    assert any(n in _flach(signatur.text("en")) for n in signatur.NOTIZEN["en"])
    assert any(n in _flach(signatur.text("xx")) for n in signatur.NOTIZEN["de"])
    assert len(signatur.NOTIZEN["de"]) == len(signatur.NOTIZEN["en"])
