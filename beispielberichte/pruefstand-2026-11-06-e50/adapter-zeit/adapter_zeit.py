"""Laufzeit des INKAR-Adapters allein, Stand nach E49 gegen Stand nach E50 (Prüfstand nach E50).

Warum: Der INKAR-Schritt der Belegläufe dauert nach E50 länger als nach E49 (Brandenburg 126,5 statt
95,1 s). Der Schritt besteht aus Lesen der Gesamtdatei (Adapter `quellen.inkar`) und Schreiben in die
Datenbank. Dieses Skript misst nur den Adapter, ohne Datenbank und ohne Netz, damit sich der Anteil des
Lesens vom Rest trennen lässt. Es ändert keinen Code; es lädt die Pipeline aus einem Ordner, den
`git archive` aus den Teilbäumen eines Stands erzeugt.

Aufruf (vom Repository aus, je Stand ein Ordner mit `pipeline/` und `config/` aus den Teilbäumen):
    git archive <Teilbaum pipeline> --prefix=pipeline/ | tar -x -C <Ordner>
    git archive <Teilbaum config> --prefix=config/ | tar -x -C <Ordner>
    uv run -q --no-project --with-requirements requirements.txt python -I \\
        beispielberichte/pruefstand-2026-11-06-e50/adapter-zeit/adapter_zeit.py \\
        <Ordner> quellen.yaml inkar_gemeinden cache/inkar_2025.zip

Ausgabe: Datensätze, Laufzeit, ob der Abruf unvollständig ist, Warnungen. Keine Werte (Antwort 69)."""
import os
import sys
import time

repo, konfig, quelle, zipdatei = sys.argv[1:5]
# Die Pipeline des zu messenden Stands vor allen anderen Pfaden, damit nicht das Arbeitsverzeichnis
# geladen wird
sys.path.insert(0, repo)
# Abgelegte Datei wie in den Belegläufen; sie hat in beiden Ständen Vorrang vor jedem Abruf
os.environ["PIPELINE_INKAR_DATEI"] = zipdatei

import requests  # noqa: E402
import yaml  # noqa: E402


def gesperrt(*a, **k):
    """Ersatz für jeden Netzaufruf von requests: Die Messung darf nichts abrufen; ein Aufruf bricht sie ab."""
    raise AssertionError(f"Netzabruf: {a}")


# Auf allen Ebenen gesperrt, auch der untersten (HTTPAdapter.send), wie tests/conftest.py seit E50
requests.get = requests.head = gesperrt
requests.adapters.HTTPAdapter.send = gesperrt

from pipeline import quellen  # noqa: E402

quellen.requests.get = quellen.requests.head = gesperrt
with open(os.path.join(repo, "config", konfig), encoding="utf-8") as f:
    cfg = yaml.safe_load(f)["quellen"][quelle]
prot = quellen.Protokoll()
t0 = time.monotonic()
n = 0
# Nur zählen: Der Adapter liefert die Datensätze als Strom, wie quelle_laden sie bekäme
for _ds in quellen.inkar(cfg, prot):
    n += 1
dauer = time.monotonic() - t0
print(f"{konfig} {quelle}: {n} Datensätze, {dauer:.1f} s, unvollständig={prot.unvollstaendig}")
print("warnungen:", prot.warnungen)
