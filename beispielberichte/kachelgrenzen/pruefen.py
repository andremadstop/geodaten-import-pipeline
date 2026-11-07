"""Ruft zaehlen.py auf und schreibt nur die Zählungen mit Zeitpunkt und Abfrage (ohne Geometrien,
Antwort 69). Aufruf aus dem Repository: python beispielberichte/kachelgrenzen/pruefen.py"""
import json
import runpy
import sys
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ORDNER = Path(__file__).resolve().parent
with tempfile.TemporaryDirectory() as tmp:
    datei = Path(tmp) / "ergebnis.json"
    sys.argv = ["zaehlen.py", str(datei)]
    print(f"Abruf {datetime.now(UTC):%Y-%m-%d %H:%M} UTC")
    runpy.run_path(str(ORDNER / "zaehlen.py"), run_name="__main__")
    e = json.loads(datei.read_text(encoding="utf-8"))
verteilung = Counter(len(t) for t in e["mehrfach"].values())
print(f"Kachel-BBOX (EPSG:25833) je Abfrage: {e['kacheln']}")
print(f"Gebäude je Zahl der Kacheln, in denen sie geliefert wurden: {dict(sorted(verteilung.items()))}")
print(f"in drei oder vier Kacheln: {sum(n for k, n in verteilung.items() if k >= 3)}")
