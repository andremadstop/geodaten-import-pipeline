"""Soll-/Ist-Abgleich je Indikatorname für den INKAR-Vollumfang (Prüfstand nach E50, Befund W1).

Vergleicht die Zeilen je Indikatorname aus der Soll-Zählung (`soll-zaehlung.txt`, von `soll_zaehlen.py`
direkt aus der INKAR-Datei gezählt, ohne Code der Pipeline) mit dem Abschnitt „Indikatornamen INKAR“ in
`datenbank-auszug.txt` (gezählt in `dashboard_data_de` nach dem Lauf). Warum ein eigener Abgleich: Die Summe
allein (33 547 606) könnte übereinstimmen, obwohl einzelne Reihen fehlen und andere doppelt sind; erst der
Vergleich je Name zeigt, dass jede Reihe vollständig angekommen ist.

Aufruf (nur Standardbibliothek, liest nur die beiden Textdateien in diesem Ordner):
    python3 -I beispielberichte/pruefstand-2026-11-06-e50/inkar-vollumfang/abgleich.py \\
        beispielberichte/pruefstand-2026-11-06-e50/inkar-vollumfang/soll-zaehlung.txt \\
        beispielberichte/pruefstand-2026-11-06-e50/inkar-vollumfang/datenbank-auszug.txt"""
import sys


def soll_lesen(pfad: str) -> dict[str, int]:
    """Zeilen je Indikatorname aus der Soll-Zählung.

    Args:
        pfad: Ausgabe von soll_zaehlen.py.

    Returns:
        Name -> Zeilen, aus dem letzten Abschnitt („Zeilen je Indikatorname …“, je Zeile
        „<Zahl>\\t<Name>“)."""
    werte, drin = {}, False
    with open(pfad, encoding="utf-8") as f:
        for zeile in f:
            if zeile.startswith("## Zeilen je Indikatorname"):
                drin = True
                continue
            if drin and "\t" in zeile:
                n, name = zeile.rstrip("\n").split("\t", 1)
                werte[name] = int(n)
    return werte


def ist_lesen(pfad: str) -> dict[str, int]:
    """Zeilen je Indikatorname aus dem Datenbankauszug (psql-Tabelle „indikator | zeilen“).

    Args:
        pfad: datenbank-auszug.txt von beleg.sh.

    Returns:
        Name -> Zeilen aus dem Abschnitt „== Indikatornamen INKAR“. Getrennt wird am letzten „|“, weil ein
        Indikatorname selbst kein „|“ enthält, die Zahl aber immer rechts steht."""
    werte, drin = {}, False
    with open(pfad, encoding="utf-8") as f:
        for zeile in f:
            if zeile.startswith("== "):
                drin = zeile.startswith("== Indikatornamen INKAR")
                continue
            if not drin or "|" not in zeile or zeile.lstrip().startswith("indikator"):
                continue
            name, n = zeile.rsplit("|", 1)
            if n.strip().isdigit():
                werte[name.strip()] = int(n)
    return werte


def main(soll_pfad: str, ist_pfad: str) -> int:
    """Gibt den Abgleich aus und liefert 0 bei vollständiger Übereinstimmung, sonst 1.

    Args:
        soll_pfad: Soll-Zählung.
        ist_pfad: Datenbankauszug.

    Seiteneffekte: nur stdout."""
    soll, ist = soll_lesen(soll_pfad), ist_lesen(ist_pfad)
    nur_soll = sorted(set(soll) - set(ist))
    nur_ist = sorted(set(ist) - set(soll))
    anders = sorted(n for n in set(soll) & set(ist) if soll[n] != ist[n])
    print(f"Soll: {len(soll)} Indikatornamen, {sum(soll.values())} Zeilen")
    print(f"Ist:  {len(ist)} Indikatornamen, {sum(ist.values())} Zeilen")
    print(f"gleich: {len(set(soll) & set(ist)) - len(anders)}; nur im Soll: {len(nur_soll)}; nur im Ist: "
          f"{len(nur_ist)}; Zeilenzahl verschieden: {len(anders)}")
    for n in nur_soll:
        print(f"  nur im Soll: {n} ({soll[n]})")
    for n in nur_ist:
        print(f"  nur im Ist: {n} ({ist[n]})")
    for n in anders:
        print(f"  verschieden: {n}: Soll {soll[n]}, Ist {ist[n]}")
    return 0 if not (nur_soll or nur_ist or anders) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
