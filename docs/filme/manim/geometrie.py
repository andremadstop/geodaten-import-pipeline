"""Vereinfacht die Gemeinde- und Kreisgrenzen der LGB für den Film (Vorstufe zu film.py).

Erwartet im Datenordner `gemeinden.geojson` (413 Objekte) und `kreise.geojson` (18 Objekte) in EPSG:25833,
abgerufen vom WFS der LGB mit den Adaptern der Pipeline (Quellen `gemeinden_lgb`, `kreise_lgb` aus
`config/pruefkonfiguration.yaml`). Schreibt `geo_vereinfacht.json` in denselben Ordner.
Die Geodaten gehören nicht ins Repo (Antwort 69 der TH).

Aufruf aus der Repo-Wurzel:
    FILM_DATEN=cache/filme uv run --no-project --with shapely==2.2.0 python docs/filme/manim/geometrie.py
"""
import json
import os
from pathlib import Path

from shapely.geometry import shape

REPO = Path(os.environ.get("PIPELINE_REPO") or Path(__file__).resolve().parents[3])
DATEN = Path(os.environ.get("FILM_DATEN") or REPO / "cache" / "filme")
if not DATEN.is_absolute():
    DATEN = Path.cwd() / DATEN

# Toleranz in Metern (EPSG:25833); reicht für eine Karte von gut 5 Bildeinheiten Höhe
TOLERANZ = {"gemeinden_lgb": ("gemeinden.geojson", 300.0), "kreise_lgb": ("kreise.geojson", 220.0)}


def ringe(geometrie, toleranz):
    s = shape(geometrie).simplify(toleranz, preserve_topology=True)
    aus = []
    for p in getattr(s, "geoms", [s]):
        if p.is_empty:
            continue
        r = [(round(x, 1), round(y, 1)) for x, y in p.exterior.coords]
        if len(r) >= 4:
            aus.append(r)
    return aus


ergebnis = {}
for name, (datei, tol) in TOLERANZ.items():
    fc = json.loads((DATEN / datei).read_text())
    crs = fc.get("crs", {}).get("properties", {}).get("name", "")
    if not crs.endswith("25833"):
        raise SystemExit(f"{datei}: EPSG:25833 erwartet, gefunden {crs!r}")
    ergebnis[name] = [ringe(f["geometry"], tol) for f in fc["features"]]
    punkte = sum(len(r) for f in ergebnis[name] for r in f)
    print(name, len(ergebnis[name]), "Objekte,", punkte, "Stützpunkte")
(DATEN / "geo_vereinfacht.json").write_text(json.dumps(ergebnis))
