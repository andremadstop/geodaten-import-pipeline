"""Holt den ALKIS-Ausschnitt der Konfiguration kachelweise wie die Pipeline und zählt Gebäude, die der
Dienst in mehreren Kacheln liefert.

Aufruf aus dem Repository: python beispielberichte/kachelgrenzen/zaehlen.py ergebnis.json
"""
import json
import sys
from pathlib import Path

import yaml
from lxml import etree

WURZEL = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WURZEL))
from pipeline import quellen  # noqa: E402

GML = "http://www.opengis.net/gml/3.2"
WFS = "http://www.opengis.net/wfs/2.0"

konfig = yaml.safe_load((WURZEL / "config/quellen.yaml").read_text(encoding="utf-8"))
cfg = konfig["quellen"]["alkis_gebaeude_thb"]
prot = quellen.Protokoll()
basis = {"SERVICE": "WFS", "REQUEST": "GetFeature", "VERSION": "2.0.0", "TYPENAMES": cfg["typename"],
         "SRSNAME": cfg["crs"]}
treffer: dict[str, list[int]] = {}
geoms: dict[str, list] = {}
kacheln = []
for k in quellen._kacheln(cfg["bbox"], cfg["kachel_m"]):
    kacheln.append(k)
    params = dict(basis, COUNT=10000, BBOX=",".join(map(str, k)) + "," + cfg["crs"])
    root = quellen.xml_lesen(quellen.abrufen(cfg["url"], params, cfg, prot))
    for m in root.iter(f"{{{WFS}}}member"):
        oid, ringe = None, []
        for el in m[0]:
            name = etree.QName(el).localname
            if name == cfg["id_feld"]:
                oid = (el.text or "").strip()
            if name == cfg["geometrie_feld"]:
                for pl in el.iter(f"{{{GML}}}posList"):
                    v = [float(x) for x in pl.text.split()]
                    ringe.append(list(zip(v[0::2], v[1::2], strict=False)))
        treffer.setdefault(oid, []).append(len(kacheln) - 1)
        geoms[oid] = ringe

mehrfach = {o: t for o, t in treffer.items() if len(t) > 1}
ergebnis = {"kacheln": kacheln, "bbox": cfg["bbox"], "geoms": geoms, "mehrfach": mehrfach,
            "abrufe": sum(len(t) for t in treffer.values())}
Path(sys.argv[1]).write_text(json.dumps(ergebnis), encoding="utf-8")
print(f"Kacheln {len(kacheln)}, Gebäude {len(treffer)}, geliefert {ergebnis['abrufe']}, "
      f"in mehreren Kacheln {len(mehrfach)}")
