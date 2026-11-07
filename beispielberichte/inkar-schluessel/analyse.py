"""Gesamtanalyse der INKAR-Schlüssel (E27, E37, E40): Wie oft fällt der fünfteilige Quellschlüssel
(Kennziffer, Bereich, Kürzel, Indikator, Zeitbezug, Antworten 31 und 62) auf denselben Schlüssel von
dashboard_data_de (kennziffer, indikator, zeitbezug) zusammen, und mit welchen Werten?

Aufruf (nur Standardbibliothek, liest die Gesamtdatei als Datenstrom über `unzip -p`):
    python3 -I beispielberichte/inkar-schluessel/analyse.py cache/inkar_2025.zip > ergebnis.txt

Ausgegeben werden nur Zählungen, Kürzel, Bereiche und Indikatornamen, keine Werte je Gebiet
(Antwort 69: Quelldaten werden nicht mit dem Code veröffentlicht)."""
import csv
import subprocess
import sys
import time
from collections import Counter, defaultdict

FUENF = ["xbev", "q_bev_fl", "e5_bev", "q_pendlersaldo", "alo"]   # Kürzel in config/quellen.yaml


OHNE_ZUSATZ = {"ZOM"}   # config/quellen.yaml, ziel.zusatz.ausser


def name_e40(bereich: str, kuerzel: str, indikator: str) -> str:
    """Regel aus E40 (ziel.zusatz in config/quellen.yaml): Langtext; außer im Bereich ZOM, dessen
    Indikatorenübersicht MOSIDI als Metadaten liest, mit dem Bereich in Klammern dahinter."""
    return indikator if bereich in OHNE_ZUSATZ else f"{indikator} ({bereich})"


def gruppen(zeilen):
    """zeilen: Liste (kz, bereich, kuerzel, indikator, zeit, wert). Zählt Kollisionen."""
    alt = defaultdict(list)        # alter Zielschlüssel (kz, Indikator, Zeit)
    voll = Counter()               # fünfteiliger Quellschlüssel
    neu = defaultdict(set)         # Zielschlüssel nach E40 -> Quellschlüssel
    for kz, b, k, i, z, w in zeilen:
        alt[(kz, i, z)].append((b, k, w))
        voll[(kz, b, k, i, z)] += 1
        neu[(kz, name_e40(b, k, i), z)].add((b, k, i))
    mehrfach = {s: w for s, w in alt.items() if len(w) > 1}
    verschieden_je, verschieden_reihen = Counter(), Counter()
    for (_kz, i, _z), w in mehrfach.items():
        if len({x[2] for x in w}) > 1:
            verschieden_je[i] += 1
            verschieden_reihen[f"{i}: " + " / ".join(sorted(f"{b}/{k}" for b, k, _ in w))] += 1
    verschieden = sum(1 for w in mehrfach.values() if len({x[2] for x in w}) > 1)
    return {
        "zeilen": len(zeilen),
        "quellschluessel_eindeutig": len(voll),
        "quellschluessel_doppelt": sum(1 for n in voll.values() if n > 1),
        "alter_zielschluessel": len(alt),
        "alter_zielschluessel_mehrfach": len(mehrfach),
        "davon_gleicher_wert": len(mehrfach) - verschieden,
        "davon_verschiedener_wert": verschieden,
        "zeilen_ueber_der_ersten": sum(len(w) - 1 for w in mehrfach.values()),
        "zielschluessel_e40": len(neu),
        "zielschluessel_e40_mit_mehr_als_einer_quellreihe": sum(1 for v in neu.values() if len(v) > 1),
        "verschiedener_wert_je_langtext": dict(verschieden_je.most_common()),
        "verschiedener_wert_je_reihenpaar": dict(verschieden_reihen.most_common()),
        "verschiedener_wert_gemeinden": len({kz for (kz, _i, _z), w in mehrfach.items()
                                             if len({x[2] for x in w}) > 1}),
        "verschiedener_wert_jahre": sorted({z for (_kz, _i, z), w in mehrfach.items()
                                            if len({x[2] for x in w}) > 1}),
    }


def main(pfad: str) -> None:
    t0 = time.monotonic()
    # feste Argumentliste, kein Shell; unzip wie in der Pipeline (Deflate64)
    proc = subprocess.Popen(["unzip", "-p", pfad, "inkar_2025.csv"],  # noqa: S603, S607
                            stdout=subprocess.PIPE)
    text = (zeile.decode("utf-8") for zeile in proc.stdout)
    leser = csv.reader(text, delimiter=";")
    kopf = next(leser)
    sp = {n: kopf.index(n) for n in kopf}
    reihen_de = Counter()          # (Bereich, Kürzel, Indikator) -> Zeilen, alle Gemeinden
    bb, de5 = [], []
    for f in leser:
        if len(f) < len(kopf) or f[sp["Raumbezug"]] != "Gemeinden":
            continue
        kz = f[sp["Kennziffer"]].strip()
        if len(kz) != 8:
            continue
        b, k, i = f[sp["Bereich"]].strip(), f[sp["Kuerzel"]].strip(), f[sp["Indikator"]].strip()
        reihen_de[(b, k, i)] += 1
        z, w = f[sp["Zeitbezug"]].strip(), f[sp["Wert"]].strip()
        if kz.startswith("12"):
            bb.append((kz, b, k, i, z, w))
        if k in FUENF:
            de5.append((kz, b, k, i, z, w))
    proc.wait()

    print(f"# INKAR-Schlüsselanalyse, Datei {pfad.rsplit('/', 1)[-1]}, Raumbezug Gemeinden, "
          "Kennziffer 8-stellig")
    print(f"# Laufzeit {time.monotonic() - t0:.0f} s\n")
    print("## Katalog: Reihen (Bereich, Kürzel, Indikator) über alle Gemeinden Deutschlands")
    lang = defaultdict(set)
    kuerzel_bereiche = defaultdict(set)
    kuerzel_namen = defaultdict(set)
    for (b, k, i) in reihen_de:
        lang[i].add((b, k))
        kuerzel_bereiche[k].add(b)
        kuerzel_namen[k].add(i)
    print(f"Reihen: {len(reihen_de)}; Bereiche: {len({b for b, _, _ in reihen_de})} "
          f"({', '.join(sorted({b for b, _, _ in reihen_de}))}); Kürzel: {len(kuerzel_bereiche)}; "
          f"Langtexte: {len(lang)}")
    print(f"Langtexte mit mehr als einer Reihe: {sum(1 for v in lang.values() if len(v) > 1)}")
    print(f"Kürzel in mehr als einem Bereich: {sum(1 for v in kuerzel_bereiche.values() if len(v) > 1)}")
    print(f"Kürzel mit mehr als einem Langtext: {sum(1 for v in kuerzel_namen.values() if len(v) > 1)}")
    paar = defaultdict(set)
    for (b, k, i) in reihen_de:
        paar[(k, i)].add(b)
    print(f"(Kürzel, Langtext) in mehr als einem Bereich: {sum(1 for v in paar.values() if len(v) > 1)}")
    je_bereich = defaultdict(set)
    for (b, k, i) in reihen_de:
        je_bereich[(b, i)].add(k)
    print(f"Langtexte mit mehr als einem Kürzel im selben Bereich: "
          f"{sum(1 for v in je_bereich.values() if len(v) > 1)}")
    namen = defaultdict(set)
    for (b, k, i) in reihen_de:
        namen[name_e40(b, k, i)].add((b, k, i))
    doppelt = {n: v for n, v in namen.items() if len(v) > 1}
    print(f"Namen nach der Regel aus E40 (Langtext, außer ZOM mit „ (Bereich)“): {len(namen)} für "
          f"{len(reihen_de)} Reihen; Namen für mehr als eine Reihe: {len(doppelt)}")
    for n, v in sorted(doppelt.items()):
        print(f"  {n}: {', '.join(f'{b}/{k}' for b, k, _ in sorted(v))}")
    print("\nBeispiele für Langtexte mit mehreren Reihen (Bereich/Kürzel):")
    for i in sorted(i for i, v in lang.items() if len(v) > 1):
        print(f"  {i}: {', '.join(f'{b}/{k}' for b, k in sorted(lang[i]))}")
    for titel, zeilen in (("Brandenburg, alle Kürzel (Kennziffer beginnt mit 12)", bb),
                          (f"Deutschland, die fünf Kürzel der Konfiguration ({', '.join(FUENF)})", de5),
                          ("Brandenburg, die fünf Kürzel der Konfiguration",
                           [z for z in bb if z[2] in FUENF])):
        print(f"\n## {titel}")
        g = gruppen(zeilen)
        print(f"Kürzel: {len({z[2] for z in zeilen})}, Reihen: {len({z[1:4] for z in zeilen})}")
        for k, v in g.items():
            print(f"{k}: {v}")


if __name__ == "__main__":
    main(sys.argv[1])
