"""Soll-Zählung für den INKAR-Vollumfang (Prüfstand nach E50, Befund W1 „Mengennachweis“).

Zählt in der INKAR-Gesamtdatei, was der Import der TH (MOSIDI, `services/backend/src/inkar_import`)
übernehmen würde, unabhängig von der Pipeline: alle Raumbezüge der Datei (zur Einordnung) und für den
Raumbezug Gemeinden, den `inkar_db_import.py` fest auswählt, Zeilen, Kennziffern, Reihen und die Zeilen je
Indikatorname nach der Regel aus E40. Der Lauf `inkar-vollumfang/` muss für die Gemeinden genau diese Zahlen
in die Datenbank bringen; die Zählung ist die Gegenprobe dazu, ohne Datenbank und ohne Code der Pipeline.

Aufruf (nur Standardbibliothek, liest die CSV als Datenstrom über `unzip -p`, wie
`inkar-schluessel/analyse.py`), vom Repository aus:
    python3 -I beispielberichte/pruefstand-2026-11-06-e50/inkar-vollumfang/soll_zaehlen.py \\
        cache/inkar_2025.zip

Ausgegeben werden nur Zählungen, Raumbezüge, Bereiche und Indikatornamen, keine Werte je Gebiet
(Antwort 69: Quelldaten werden nicht mit dem Code veröffentlicht)."""
import csv
import subprocess
import sys
import time
from collections import Counter, defaultdict

# Regel aus E40 (ziel.zusatz der Konfiguration): Langtext, außer im Bereich ZOM mit dem Bereich in Klammern.
# Hier nachgebaut statt aus pipeline/ importiert, damit die Gegenprobe nicht vom geprüften Code abhängt.
OHNE_ZUSATZ = {"ZOM"}


def name_e40(bereich: str, indikator: str) -> str:
    """Indikatorname in dashboard_data_de nach E40.

    Args:
        bereich: Spalte Bereich der INKAR-Zeile (ZOM, LRB, …).
        indikator: Langtext aus der Spalte Indikator.

    Returns:
        Den Langtext, außerhalb von ZOM mit „ (Bereich)“ dahinter."""
    return indikator if bereich in OHNE_ZUSATZ else f"{indikator} ({bereich})"


def main(pfad: str) -> None:
    """Liest die Gesamtdatei einmal und gibt die Zählungen auf stdout aus.

    Args:
        pfad: Pfad der INKAR-ZIP-Datei (enthält inkar_2025.csv).

    Seiteneffekte: startet `unzip -p` als Kindprozess; schreibt nichts außer stdout."""
    t0 = time.monotonic()
    # Feste Argumentliste ohne Shell; unzip wie in der Pipeline, weil das ZIP Deflate64 nutzt, das zipfile
    # der Standardbibliothek nicht lesen kann
    proc = subprocess.Popen(["unzip", "-p", pfad, "inkar_2025.csv"],  # noqa: S603, S607
                            stdout=subprocess.PIPE)
    # Zeilenweise dekodiert; die Gesamtdatei 2025 hat kein Anführungszeichen und keinen Umbruch in einem Feld
    # (E50, K1), eine Zeile der Datei ist also ein Datensatz
    text = (zeile.decode("utf-8") for zeile in proc.stdout)
    leser = csv.reader(text, delimiter=";")
    kopf = next(leser)
    sp = {n: kopf.index(n) for n in kopf}
    alle = 0
    kaputt = 0                       # Zeilen mit anderer Spaltenzahl als der Kopf
    je_raumbezug = Counter()
    kuerzel_je_raumbezug = defaultdict(set)
    gem = Counter()                  # Kennzahlen zum Raumbezug Gemeinden
    kennziffern = set()
    reihen = set()                   # (Bereich, Kürzel, Indikator)
    je_name = Counter()              # Indikatorname nach E40 -> Zeilen
    je_bereich = Counter()
    jahre = set()
    for f in leser:
        alle += 1
        if len(f) != len(kopf):
            kaputt += 1
            continue
        rb = f[sp["Raumbezug"]]
        je_raumbezug[rb] += 1
        kuerzel_je_raumbezug[rb].add(f[sp["Kuerzel"]])
        if rb != "Gemeinden":
            continue
        gem["zeilen"] += 1
        kz = f[sp["Kennziffer"]].strip()
        # Achtstellig wie kennziffer_stellen: 8 der Konfiguration; der Import der TH filtert nicht nach der
        # Länge, darum beide Zahlen
        if len(kz) != 8 or not kz.isdigit():
            gem["kennziffer_nicht_achtstellig"] += 1
            continue
        gem["achtstellig"] += 1
        b, k, i = f[sp["Bereich"]].strip(), f[sp["Kuerzel"]].strip(), f[sp["Indikator"]].strip()
        z, w = f[sp["Zeitbezug"]].strip(), f[sp["Wert"]].strip()
        if not w:
            gem["ohne_wert"] += 1
        if not z:
            gem["ohne_zeitbezug"] += 1
        if w and z:
            gem["mit_wert_und_zeitbezug"] += 1
        kennziffern.add(kz)
        reihen.add((b, k, i))
        je_name[name_e40(b, i)] += 1
        je_bereich[b] += 1
        if z:
            jahre.add(z)
    proc.wait()

    print(f"# Soll-Zählung INKAR-Vollumfang, Datei {pfad.rsplit('/', 1)[-1]}, Laufzeit "
          f"{time.monotonic() - t0:.0f} s, unzip rc={proc.returncode}")
    print(f"Zeilen der Datei (ohne Kopf): {alle}; mit anderer Spaltenzahl als der Kopf: {kaputt}")
    print(f"\n## Raumbezüge der Datei ({len(je_raumbezug)}): Zeilen, Kürzel")
    for rb, n in sorted(je_raumbezug.items(), key=lambda x: -x[1]):
        print(f"{rb}: {n} Zeilen, {len(kuerzel_je_raumbezug[rb])} Kürzel")
    print("\n## Raumbezug Gemeinden (Auswahl in inkar_db_import.py, Z. 107)")
    for k in ("zeilen", "kennziffer_nicht_achtstellig", "achtstellig", "ohne_wert", "ohne_zeitbezug",
              "mit_wert_und_zeitbezug"):
        print(f"{k}: {gem[k]}")
    print(f"Kennziffern (achtstellig, verschieden): {len(kennziffern)}")
    print(f"Reihen (Bereich, Kürzel, Indikator): {len(reihen)}; Kürzel: {len({r[1] for r in reihen})}; "
          f"Indikatornamen nach E40: {len(je_name)}")
    print(f"Zeitbezug: {min(jahre)} bis {max(jahre)} ({len(jahre)} Jahre)")
    print("\n## Zeilen je Bereich")
    for b, n in sorted(je_bereich.items()):
        print(f"{b}: {n}")
    print(f"\n## Zeilen je Indikatorname nach E40 ({len(je_name)} Namen, Summe {sum(je_name.values())})")
    for name, n in sorted(je_name.items()):
        print(f"{n}\t{name}")


if __name__ == "__main__":
    main(sys.argv[1])
