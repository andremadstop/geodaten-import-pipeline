"""Gegenprobe WFS 2.0.0 gegen 1.1.0 am selben Dienst (Antwort 67), mit dem Adapter der Pipeline.

Holt die Quelle `kreise_lgb` aus config/quellen.yaml zweimal, einmal je Version, und vergleicht
Objekt-IDs, Sachdaten und die Koordinaten der Geometrien (alle Zahlen aus gml:posList, gml:pos und
gml:coordinates in Reihenfolge). Ausgegeben werden nur Zählungen, keine Datensätze (Antwort 69).

Aufruf aus dem Repository (fragt den Dienst der LGB live ab, je Version wenige Abfragen):
    python beispielberichte/wfs-1.1.0/vergleichen.py
"""
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml
from lxml import etree

WURZEL = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WURZEL))
from pipeline import quellen  # noqa: E402


def koordinaten(gml: str) -> list[float]:
    root = etree.fromstring(gml.encode(), quellen._XML)
    zahlen = []
    for el in root.iter():
        if etree.QName(el).localname in ("posList", "pos", "coordinates") and el.text:
            zahlen += [float(x) for x in re.split(r"[\s,]+", el.text.strip()) if x]
    return zahlen


def holen(version: str) -> tuple[dict, quellen.Protokoll, str]:
    cfg = dict(yaml.safe_load((WURZEL / "config/quellen.yaml").read_text(encoding="utf-8"))
               ["quellen"]["kreise_lgb"], version=version)
    prot = quellen.Protokoll()
    objekte = {d["objekt_id"]: d for d in quellen.wfs(cfg, prot)}
    art = {etree.QName(etree.fromstring(d["geom"][1].encode(), quellen._XML)).localname
           for d in objekte.values()}
    return objekte, prot, ", ".join(sorted(art))


print(f"Abruf {datetime.now(UTC):%Y-%m-%d %H:%M} UTC, Quelle kreise_lgb (config/quellen.yaml)")
a, pa, art_a = holen("2.0.0")
b, pb, art_b = holen("1.1.0")
print(f"WFS 2.0.0: {len(a)} Objekte, Geometrie {art_a}, unvollständig: {pa.unvollstaendig}, "
      f"letzte Abfrage: {pa.letzte_abfrage}")
print(f"WFS 1.1.0: {len(b)} Objekte, Geometrie {art_b}, unvollständig: {pb.unvollstaendig}, "
      f"letzte Abfrage: {pb.letzte_abfrage}")
print(f"gleiche Objekt-IDs: {set(a) == set(b)}")
print(f"gleiche Sachdaten: {sum(a[k]['werte'] == b[k]['werte'] for k in set(a) & set(b))} von {len(a)}")
gleich = [k for k in set(a) & set(b) if koordinaten(a[k]["geom"][1]) == koordinaten(b[k]["geom"][1])]
n = sum(len(koordinaten(a[k]["geom"][1])) // 2 for k in a)
print(f"Geometrien mit identischen Koordinaten (Reihenfolge und Wert): {len(gleich)} von {len(a)} "
      f"({n} Punkte in 2.0.0)")
