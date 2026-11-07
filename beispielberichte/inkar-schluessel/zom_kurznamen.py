"""Prüfausgabe zu E40/E42: Stimmen die Kurznamen im Blatt ZOM der INKAR-Indikatorenübersicht mit den
Langtexten der ZOM-Reihen in der INKAR-Gesamtdatei überein? Darauf beruht `ausser: [ZOM]` in
config/quellen.yaml: MOSIDI liest seine Metadaten nur aus diesem Blatt und findet sie im Backend über
`dashboard_data_metadata.kurzname = indikator`.

Beides liegt in der Gesamtdatei des BBSR (`inkar_2025.zip`: `Indikatorenübersicht (INKAR 2025).xlsx` und
`inkar_2025.csv`). Aufruf (nur Standardbibliothek; die CSV wird als Datenstrom über `unzip -p` gelesen):
    python3 -I beispielberichte/inkar-schluessel/zom_kurznamen.py cache/inkar_2025.zip \\
        > beispielberichte/inkar-schluessel/zom-kurznamen-<Datum>.txt

Ausgegeben werden nur Kürzel und Namen, keine Werte."""
import csv
import io
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile

FUENF = ["xbev", "q_bev_fl", "e5_bev", "q_pendlersaldo", "alo"]   # Kürzel in config/quellen.yaml
# ElementTree löst keine externen Entitäten auf, expat (ab 2.4.1) begrenzt Entitätsexpansion; gelesen wird nur
# die Indikatorenübersicht aus der Datei des BBSR (daher noqa: S314 unten)
M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def blatt(xlsx: bytes, name: str) -> list[list[str]]:
    """Zeilen eines Tabellenblatts als Text (Spaltenbuchstaben aufgelöst, leere Zellen als '')."""
    z = zipfile.ZipFile(io.BytesIO(xlsx))
    geteilt = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(f"{M}si"):  # noqa: S314
            geteilt.append("".join(t.text or "" for t in si.iter(f"{M}t")))
    wb = ET.fromstring(z.read("xl/workbook.xml"))  # noqa: S314
    rid = next(s.get(f"{R}id") for s in wb.iter(f"{M}sheet") if s.get("name") == name)
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))  # noqa: S314
    ziel = next(r.get("Target") for r in rels if r.get("Id") == rid).lstrip("/")
    ziel = ziel if ziel.startswith("xl/") else f"xl/{ziel}"
    zeilen = []
    for row in ET.fromstring(z.read(ziel)).iter(f"{M}row"):  # noqa: S314
        werte = {}
        for c in row.iter(f"{M}c"):
            spalte = "".join(ch for ch in c.get("r") if ch.isalpha())
            v = c.find(f"{M}v")
            if c.get("t") == "s" and v is not None:
                text = geteilt[int(v.text)]
            elif c.get("t") == "inlineStr":
                text = "".join(t.text or "" for t in c.iter(f"{M}t"))
            else:
                text = v.text if v is not None else ""
            werte[spalte] = (text or "").strip()
        if werte:
            n = max(sum((ord(ch) - 64) * 26 ** i for i, ch in enumerate(reversed(s))) for s in werte)
            zeilen.append([werte.get(_buchstabe(i), "") for i in range(1, n + 1)])
    return zeilen


def _buchstabe(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def main(inkar_zip: str) -> None:
    with zipfile.ZipFile(inkar_zip) as z:   # nur das Verzeichnis; entpackt wird mit unzip (Deflate64)
        namen = z.namelist()
    # Der Name enthält „ü“ in einer Kodierung, die zipfile und unzip verschieden lesen: Muster statt Name
    uebersicht = "Indikatoren*bersicht (INKAR *).xlsx"
    if sum(1 for n in namen if n.startswith("Indikatoren") and n.endswith(".xlsx")) != 1:
        sys.exit("Indikatorenübersicht nicht eindeutig in der Datei")
    tabelle = next(n for n in namen if n.endswith(".csv"))
    xlsx = subprocess.run(["unzip", "-p", inkar_zip, uebersicht], capture_output=True,  # noqa: S603, S607
                          check=True).stdout
    zeilen = blatt(xlsx, "ZOM")
    kopf_nr = next(i for i, z in enumerate(zeilen) if any(c.lower().startswith("kürzel") for c in z))
    kopf = [c.lower() for c in zeilen[kopf_nr]]
    k_sp = next(i for i, c in enumerate(kopf) if c.startswith("kürzel"))
    n_sp = next(i for i, c in enumerate(kopf) if c.startswith("kurzname"))
    kurzname = {z[k_sp]: z[n_sp] for z in zeilen[kopf_nr + 1:] if len(z) > n_sp and z[k_sp] in FUENF}

    langtexte: dict[str, set[str]] = {k: set() for k in FUENF}
    with subprocess.Popen(["unzip", "-p", inkar_zip, tabelle], stdout=subprocess.PIPE) as p:  # noqa: S603, S607
        leser = csv.reader((zeile.decode("utf-8-sig") for zeile in p.stdout), delimiter=";")
        kopf_csv = next(leser)
        sp = {n: kopf_csv.index(n) for n in ("Bereich", "Kuerzel", "Indikator", "Raumbezug")}
        for z in leser:
            if len(z) > sp["Raumbezug"] and z[sp["Bereich"]] == "ZOM" and z[sp["Raumbezug"]] == "Gemeinden" \
                    and z[sp["Kuerzel"]] in langtexte:
                langtexte[z[sp["Kuerzel"]]].add(z[sp["Indikator"]])

    print(f"# Blatt ZOM aus {inkar_zip.rsplit('/', 1)[-1]}:{uebersicht}, Kopfzeile {kopf_nr + 1}: Spalten "
          f"„{zeilen[kopf_nr][k_sp]}“ und „{zeilen[kopf_nr][n_sp]}“")
    print(f"# Langtexte der Reihen mit Bereich ZOM, Raumbezug Gemeinden, aus {tabelle}")
    print("Kürzel;Kurzname im Blatt ZOM;Langtext der ZOM-Reihen;gleich")
    for k in FUENF:
        lt = sorted(langtexte[k])
        kn = kurzname.get(k, "")
        gleich = "ja" if kn and lt == [kn] else ("keine ZOM-Reihe" if not lt and not kn else "nein")
        print(f"{k};{kn or '–'};{' | '.join(lt) or '–'};{gleich}")


if __name__ == "__main__":
    main(sys.argv[1])
