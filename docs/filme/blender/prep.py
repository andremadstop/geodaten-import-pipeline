# Vorbereitung der Geometrie für den Film (ausserhalb von Blender).
# Liest <daten>/*.geojson, schreibt <aus>/*.json (beides per Parameter, Standard unter berichte/, nicht versioniert).
# Koordinaten: EPSG:25833, Ursprung verschoben auf Campusmitte (332600, 5809900), Meter.
import json, os
import numpy as np
from shapely.geometry import shape, box
from shapely.ops import unary_union
import mapbox_earcut as earcut

import argparse

_ap = argparse.ArgumentParser(description="Geometrie für den Blender-Film vorbereiten")
_ap.add_argument("--daten", default="berichte/film-blender/daten",
                 help="Ordner mit gebaeude.geojson, gemeinden.geojson, kreise.geojson (EPSG:25833)")
_ap.add_argument("--aus", default="berichte/film-blender/prep", help="Zielordner für die JSON-Dateien")
_args = _ap.parse_args()
DATEN = _args.daten
AUS = _args.aus
os.makedirs(AUS, exist_ok=True)
OX, OY = 332600.0, 5809900.0
TOL = 60.0  # m, Vereinfachung Gemeinden/Kreise fuer Uebersicht


def lade(n):
    return json.load(open(os.path.join(DATEN, n + ".geojson")))


def polys_of(geom):
    if geom.geom_type == "Polygon":
        return [geom]
    return list(geom.geoms)


def ringe(poly):
    return [list(poly.exterior.coords)[:-1]] + [list(r.coords)[:-1] for r in poly.interiors]


def tri(poly, z=0.0):
    rs = ringe(poly)
    verts = []
    ends = []
    for r in rs:
        verts.extend(r)
        ends.append(len(verts))
    v = np.array(verts, dtype=np.float64)
    idx = earcut.triangulate_float64(v, np.array(ends, dtype=np.uint32))
    return v, idx.reshape(-1, 3)


def lokal(rs):
    return [[[round(x - OX, 2), round(y - OY, 2)] for x, y in r] for r in rs]


# --- Gemeinden ---
gem = lade("gemeinden")
klassen = [25, 50, 100, 250]  # Einwohner je km2, Klassengrenzen (gesetzt, nicht aus Daten)
out_gem = []
for i, f in enumerate(gem["features"]):
    p = f["properties"]
    g = shape(f["geometry"]).simplify(TOL, preserve_topology=True)
    dichte = p["bevoelkerung"] / p["flaeche_km2"]
    k = sum(dichte >= b for b in klassen)
    tris_v, tris_f = [], []
    rs_all = []
    off = 0
    for poly in polys_of(g):
        if poly.is_empty:
            continue
        v, t = tri(poly)
        tris_v.extend([[round(x - OX, 2), round(y - OY, 2)] for x, y in v])
        tris_f.extend((t + off).tolist())
        off += len(v)
        rs_all.extend(lokal(ringe(poly)))
    c = shape(f["geometry"]).representative_point()
    out_gem.append({
        "i": i, "ags": p["ags"], "name": p["name"], "bev": p["bevoelkerung"],
        "fl": p["flaeche_km2"], "dichte": dichte, "klasse": k,
        "c": [c.x - OX, c.y - OY], "v": tris_v, "f": tris_f, "ringe": rs_all,
    })
json.dump(out_gem, open(os.path.join(AUS, "gemeinden.json"), "w"))
kz = [sum(1 for g in out_gem if g["klasse"] == k) for k in range(5)]
print("Gemeinden", len(out_gem), "Klassen", kz,
      "Ecken", sum(len(g["v"]) for g in out_gem),
      "Summe Bev", sum(g["bev"] for g in out_gem), "Flaeche", round(sum(g["fl"] for g in out_gem), 2))

# --- Kreise (nur Linien) ---
kr = lade("kreise")
out_kr = []
for f in kr["features"]:
    g = shape(f["geometry"]).simplify(TOL, preserve_topology=True)
    rs = []
    for poly in polys_of(g):
        rs.extend(lokal(ringe(poly)))
    out_kr.append({"name": f["properties"]["name"], "art": f["properties"].get("art"), "ringe": rs})
json.dump(out_kr, open(os.path.join(AUS, "kreise.json"), "w"))
# Landesumriss
land = unary_union([shape(f["geometry"]) for f in kr["features"]]).simplify(TOL)
lr = []
for poly in polys_of(land):
    lr.append(lokal([list(poly.exterior.coords)[:-1]])[0])
print("Kreise", len(out_kr), "Land bbox", [round(b) for b in land.bounds])

# --- Gebaeude ---
geb = lade("gebaeude")
# 9 Kacheln in Abrufreihenfolge (abruf-protokoll.json): Zeilen von Sued nach Nord, je West nach Ost
xs = [332000, 332400, 332800, 333200]
ys = [5809400, 5809800, 5810200, 5810400]
kacheln = []
for r in range(3):
    for c in range(3):
        kacheln.append((xs[c], ys[r], xs[c + 1], ys[r + 1]))
out_geb = []
for i, f in enumerate(geb["features"]):
    p = f["properties"]
    g = shape(f["geometry"])
    kach = next(k for k, b in enumerate(kacheln) if box(*b).intersects(g))
    gs = p.get("anzahlgs")
    v, t = tri(g)
    out_geb.append({
        "i": i, "kachel": kach, "gs": int(gs) if gs else None,
        "funktion": p.get("funktion"),
        "ringe": lokal(ringe(g)),
        "v": [[round(x - OX, 2), round(y - OY, 2)] for x, y in v], "f": t.tolist(),
    })
json.dump(out_geb, open(os.path.join(AUS, "gebaeude.json"), "w"))
ks = [k["kachel"] for k in out_geb]
mono = all(ks[i] <= ks[i + 1] for i in range(len(ks) - 1))
print("Gebaeude", len(out_geb), "je Kachel", [ks.count(k) for k in range(9)], "Dateireihenfolge kachelweise:", mono,
      "mit Geschosszahl", sum(1 for g in out_geb if g["gs"]))
json.dump({"kacheln": [[a - OX, b - OY, c - OX, d - OY] for a, b, c, d in kacheln],
           "land": lr, "klassen": klassen, "klassen_anzahl": kz,
           "summe_bev": sum(g["bev"] for g in out_gem),
           "summe_fl": round(sum(g["fl"] for g in out_gem), 2)},
          open(os.path.join(AUS, "meta.json"), "w"))
