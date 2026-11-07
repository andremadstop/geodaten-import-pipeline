"""Geodaten für den Film holen, mit den Adaptern der Pipeline (nur lesen im Repo).

Aufruf aus der Repo-Wurzel (holt per Netz von isk.geobasis-bb.de und download.statistik-berlin-brandenburg.de):
  uv run --no-project --with-requirements requirements.txt python -I -B docs/filme/blender/holen.py [ZIELORDNER]
ZIELORDNER Standard: berichte/film-blender/daten (berichte/ ist nicht versioniert). Die Daten gehören nicht ins Repo.
"""
import copy
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

REPO = Path.cwd()  # Aufruf aus der Repo-Wurzel
DATEN = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "berichte" / "film-blender" / "daten"
ROH = DATEN / "roh"
ROH.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(REPO))
sys.dont_write_bytecode = True

import requests  # noqa: E402
import yaml  # noqa: E402
from lxml import etree  # noqa: E402

ERLAUBT = {"isk.geobasis-bb.de", "download.statistik-berlin-brandenburg.de"}
LOG: list[dict] = []
_get = requests.get


def get_bewacht(url, params=None, **kw):
    voll = requests.Request("GET", url, params=params).prepare().url
    rechner = requests.utils.urlparse(voll).hostname
    if rechner not in ERLAUBT:
        raise RuntimeError(f"Rechner nicht erlaubt: {rechner}")
    zeit = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    r = _get(url, params=params, **kw)
    LOG.append({"zeit": zeit, "url": voll, "status": r.status_code,
                "content_length": r.headers.get("Content-Length")})
    return r


requests.get = get_bewacht
from pipeline import quellen as Q  # noqa: E402

Q.requests.get = get_bewacht

cfg_all = yaml.safe_load((REPO / "config/pruefkonfiguration.yaml").read_text())
bericht = json.loads((REPO / "beispielberichte/pruefstand-2026-11-07-e51/mosidi-compose/"
                      "20261107T043632Z.json").read_text())
abfragen = {q["quelle"]: q.get("letzte_abfrage") for q in bericht["quellen"]}

GML = Q.GML


def ln(el):
    return etree.QName(el).localname


def koords(el):
    """posList/pos/coordinates eines Rings → [[x, y], ...]"""
    pl = next((e for e in el.iter() if isinstance(e.tag, str) and ln(e) == "posList"), None)
    if pl is not None:
        dim = int(pl.get("srsDimension") or el.get("srsDimension") or 2)
        z = [float(v) for v in pl.text.split()]
        return [[z[i], z[i + 1]] for i in range(0, len(z), dim)]
    ps = [e for e in el.iter() if isinstance(e.tag, str) and ln(e) == "pos"]
    if ps:
        return [[float(v) for v in p.text.split()[:2]] for p in ps]
    raise ValueError("Ring ohne Koordinaten")


def polygon(el):
    ringe = []
    for teil in el:
        if not isinstance(teil.tag, str):
            continue
        if ln(teil) in ("exterior", "outerBoundaryIs"):
            ringe.insert(0, koords(teil))
        elif ln(teil) in ("interior", "innerBoundaryIs"):
            ringe.append(koords(teil))
    return ringe


def gml_zu_geojson(text):
    el = etree.fromstring(text.encode(), Q._XML)
    polys = [e for e in el.iter() if isinstance(e.tag, str) and ln(e) in ("Polygon", "PolygonPatch")]
    if not polys:
        raise ValueError(f"keine Fläche: {ln(el)}")
    ps = [polygon(p) for p in polys]
    if len(ps) == 1:
        return {"type": "Polygon", "coordinates": ps[0]}, ln(el)
    return {"type": "MultiPolygon", "coordinates": ps}, ln(el)


def ring_flaeche(r):
    return 0.5 * sum(r[i][0] * r[i + 1][1] - r[i + 1][0] * r[i][1] for i in range(len(r) - 1))


def flaeche(g):
    polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
    return sum(abs(ring_flaeche(p[0])) - sum(abs(ring_flaeche(h)) for h in p[1:]) for p in polys)


def wfs_holen(name, alle_felder=False):
    cfg = copy.deepcopy(cfg_all["quellen"][name])
    if alle_felder:
        cfg["felder"] = None
    prot = Q.Protokoll()
    t0 = time.monotonic()
    vorher = len(LOG)
    roh = ROH / f"{name}.saetze.json"
    if roh.exists():
        raise SystemExit(f"{roh} liegt schon vor: nicht erneut abrufen, Umwandlung getrennt starten")
    saetze = list(Q.wfs(cfg, prot))
    dauer = time.monotonic() - t0
    roh.write_text(json.dumps({"saetze": saetze, "unvollstaendig": prot.unvollstaendig,
                               "warnungen": prot.warnungen, "hinweise": prot.hinweise,
                               "letzte_abfrage": prot.letzte_abfrage, "info": prot.info,
                               "abrufe": LOG[vorher:], "dauer_s": dauer}, ensure_ascii=False, default=str))
    feats, arten = [], {}
    for s in saetze:
        g, art = gml_zu_geojson(s["geom"][1])
        arten[art] = arten.get(art, 0) + 1
        feats.append({"type": "Feature", "id": s["objekt_id"],
                      "properties": {"objekt_id": s["objekt_id"], **s["werte"]}, "geometry": g})
    return cfg, prot, feats, {"dauer_s": round(dauer, 2), "abrufe": LOG[vorher:], "geom_arten": arten}


def schreiben(datei, feats):
    fc = {"type": "FeatureCollection", "name": datei.stem,
          "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::25833"}},
          "features": feats}
    datei.write_text(json.dumps(fc, ensure_ascii=False))


ergebnis = {"start": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "quellen": {}}

# 1) WFS
for name, alle in (("alkis_gebaeude_thb", True), ("gemeinden_lgb", False), ("kreise_lgb", False)):
    cfg, prot, feats, meta = wfs_holen(name, alle)
    ergebnis["quellen"][name] = {"anzahl": len(feats), "unvollstaendig": prot.unvollstaendig,
                                 "warnungen": prot.warnungen, "hinweise": prot.hinweise,
                                 "letzte_abfrage": prot.letzte_abfrage,
                                 "letzte_abfrage_bericht_0711": abfragen.get(name),
                                 "gleich_wie_bericht": prot.letzte_abfrage == abfragen.get(name),
                                 "felder_schema": prot.info.get("felder"), **meta}
    globals()[name] = feats
    print(name, len(feats), prot.unvollstaendig, prot.warnungen, prot.hinweise, flush=True)

# 2) XLSX: genau die URL aus letzte_abfrage des Berichts vom 07.11.
url_xlsx = abfragen["bevoelkerung_gemeinden"]
werte = {}
for name, feld in (("bevoelkerung_gemeinden", "bevoelkerung"), ("flaeche_gemeinden", "flaeche_km2")):
    cfg = copy.deepcopy(cfg_all["quellen"][name])
    cfg.pop("seite"), cfg.pop("datei_muster"), cfg.pop("link_rechner", None)
    lokal = ROH / url_xlsx.rsplit("/", 1)[-1]
    cfg["pfad"] = url_xlsx if not lokal.exists() else str(lokal)
    cfg["cache"] = str(ROH)
    prot = Q.Protokoll()
    vorher = len(LOG)
    saetze = list(Q.xlsx(cfg, prot))
    for s in saetze:
        werte.setdefault(s["objekt_id"], {})[feld] = s["werte"][feld]
        werte[s["objekt_id"]].setdefault("zeitbezug", {})[feld] = (s.get("zeit") or {}).get(feld)
    ergebnis["quellen"][name] = {"anzahl": len(saetze), "unvollstaendig": prot.unvollstaendig,
                                 "warnungen": prot.warnungen, "hinweise": prot.hinweise,
                                 "info": {k: v for k, v in prot.info.items() if k != "gebiete"},
                                 "abrufe": LOG[vorher:], "pfad": cfg["pfad"]}
    print(name, len(saetze), prot.unvollstaendig, prot.warnungen, prot.hinweise, flush=True)

# 3) Gemeinden mit Statistik verbinden, Flächen gegenprüfen
abw, ohne = [], []
for f in gemeinden_lgb:
    p = f["properties"]
    ags = f["id"]
    w = werte.get(ags)
    pf = flaeche(f["geometry"]) / 1e6
    p["ags"] = ags
    p["flaeche_polygon_km2"] = round(pf, 4)
    if w is None:
        ohne.append(ags)
        continue
    p["bevoelkerung"] = w.get("bevoelkerung")
    p["bevoelkerung_stichtag"] = w["zeitbezug"].get("bevoelkerung")
    p["flaeche_km2"] = w.get("flaeche_km2")
    p["flaeche_stichtag"] = w["zeitbezug"].get("flaeche_km2")
    if w.get("flaeche_km2"):
        abw.append(abs(pf - float(w["flaeche_km2"])) / float(w["flaeche_km2"]) * 100)
abw.sort()
ergebnis["abgleich"] = {
    "gemeinden_ohne_statistik": ohne,
    "statistik_ohne_gemeinde": sorted(set(werte) - {f["id"] for f in gemeinden_lgb}),
    "flaeche_median_prozent": round(abw[len(abw) // 2], 4) if abw else None,
    "flaeche_max_prozent": round(abw[-1], 4) if abw else None,
    "ueber_0_5_prozent": sum(a > 0.5 for a in abw), "verglichen": len(abw)}
print(ergebnis["abgleich"], flush=True)

# 4) Plausibilität Gebäude
xs = [c[0] for f in alkis_gebaeude_thb for c in f["geometry"]["coordinates"][0]] if all(
    f["geometry"]["type"] == "Polygon" for f in alkis_gebaeude_thb) else []
ergebnis["gebaeude"] = {
    "mit_anzahlgs": sum(1 for f in alkis_gebaeude_thb if f["properties"].get("anzahlgs") not in (None, "")),
    "anzahlgs_werte": sorted({f["properties"].get("anzahlgs") or "" for f in alkis_gebaeude_thb}),
    "attribute": sorted({k for f in alkis_gebaeude_thb for k in f["properties"]}),
    "x_min_max": [min(xs), max(xs)] if xs else None,
    "geom_typen": sorted({f["geometry"]["type"] for f in alkis_gebaeude_thb})}

schreiben(DATEN / "gebaeude.geojson", alkis_gebaeude_thb)
schreiben(DATEN / "gemeinden.geojson", gemeinden_lgb)
schreiben(DATEN / "kreise.geojson", kreise_lgb)
ergebnis["ende"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
ergebnis["netzabrufe"] = LOG
(DATEN / "abruf-protokoll.json").write_text(json.dumps(ergebnis, ensure_ascii=False, indent=1))
print(json.dumps(ergebnis["gebaeude"], ensure_ascii=False)[:1500])
print(len(LOG), "Abrufe")
