"""Änderungskarte mit erfundenen Daten erzeugen (seit 05.11.2026, E38).

Die früheren Belegkarten enthielten die echten Datensätze ihrer Läufe (etwa 882 Gebäude der LGB).
Quelldaten werden nicht mit dem Code veröffentlicht (Antwort 69 der TH); diese Karte zeigt deshalb
dieselbe Seite mit erfundenen Objekten: Raster aus Quadraten und Punkten an einem beliebigen Ort, mit
allen vier Arten der Änderung. Erzeugt mit der Pipeline selbst (pipeline/karte.py), ohne Datenbank.

    python beispielberichte/aenderungskarte/synthetisch.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pipeline import karte  # noqa: E402

ARTEN = ["unveraendert", "unveraendert", "neu", "geaendert", "unveraendert", "geloescht"]


def quadrat(x: float, y: float, d: float = 0.0006) -> dict:
    return {"type": "Polygon", "coordinates": [[[x, y], [x + d, y], [x + d, y + d], [x, y + d], [x, y]]]}


def objekte() -> dict[str, list[dict]]:
    flaechen, punkte = [], []
    for i in range(6):
        for j in range(8):
            n = i * 8 + j
            art = ARTEN[(n * 5 + i) % len(ARTEN)]
            flaechen.append({"type": "Feature", "geometry": quadrat(12.50 + j * 0.001, 52.40 + i * 0.001),
                             "properties": {"id": f"haus-{n:02d}", "status": art,
                                            "werte": {"name": f"Beispielhaus {n}", "geschosse": 1 + n % 4}}})
    for k in range(10):
        art = ARTEN[k % len(ARTEN)]
        punkte.append({"type": "Feature",
                       "geometry": {"type": "Point", "coordinates": [12.5005 + k * 0.0008, 52.3985]},
                       "properties": {"id": f"punkt-{k}", "status": art, "werte": {"name": f"Standort {k}"}}})
    return {"beispiel_flaechen": flaechen, "beispiel_punkte": punkte}


def zaehler(liste: list[dict]) -> dict:
    z = {"neu": 0, "geaendert": 0, "geloescht": 0, "unveraendert": 0}
    for f in liste:
        z[f["properties"]["status"]] += 1
    return z


if __name__ == "__main__":
    obj = objekte()
    bericht = {"lauf_id": "20261105T090000Z", "quellen": [
        {"quelle": name, "status": "ok", "zaehler": zaehler(liste), "warnungen": ["Erfundene Beispieldaten"]}
        for name, liste in obj.items()]}
    ziel = Path(__file__).resolve().parent / "beispielkarte-synthetisch.html"
    karte.schreiben(ziel, bericht, obj)
    print(ziel, {q["quelle"]: q["zaehler"] for q in bericht["quellen"]})
