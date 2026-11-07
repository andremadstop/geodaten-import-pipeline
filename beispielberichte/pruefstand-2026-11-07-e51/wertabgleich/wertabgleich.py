"""Wertabgleich INKAR je Zeile: Quelle gegen Zieltabelle (Prüfstand nach E51, Befund W4).

Der Vollumfangslauf nach E50 belegte nur Zeilenzahlen je Indikatorname (`abgleich.py` im Prüfstand nach E50).
Dieses Skript prüft jede einzelne Zeile: Für jede Zeile der INKAR-Gesamtdatei, die die Lieferkonfiguration
übernehmen soll (Raumbezug Gemeinden, achtstellige Kennziffer, alle Indikatoren, alle Jahre, Wert und
Zeitbezug vorhanden), sucht es in der Ausfuhr der Zieltabelle `dashboard_data_de` nach Lauf 1 den
Zielschlüssel (Kennziffer, Indikator, Zeitbezug) und vergleicht den Wert. Gezählt werden fehlende Zeilen (in
der Quelle, nicht in der Datenbank), überzählige (in der Datenbank, nicht in der Quelle) und abweichende
Werte; erwartet ist 0/0/0.

Unabhängig vom geprüften Code: Es importiert nichts aus `pipeline/` und liest keine YAML-Konfiguration. Die
Lesart der CSV und die Regeln sind hier eigens nachgebaut, nach den Angaben in `config/quellen.yaml` und in
`docs/entscheidungen.md` (E40: Indikatorname), nicht nach dem Code der Pipeline. Nur Standardbibliothek.

Eingaben:
- die INKAR-Gesamtdatei (ZIP). `zipfile` dient nur zum Prüfen des Inhaltsverzeichnisses: Die CSV im ZIP ist
  mit Deflate64 gepackt (Methode 9), das `zipfile` nicht entpacken kann; gelesen wird sie deshalb als
  Datenstrom über `unzip -p`, wie in `soll_zaehlen.py` des Prüfstands nach E50.
- die Ausfuhr der Zieltabelle nach Lauf 1 (`werte-nach-lauf1.csv.gz` von `beleg.sh` mit `WERTE_EXPORT=1`:
  Kennziffer, Indikator, Zeitbezug, Wert als Text, CSV ohne Kopf, nur `source = 'INKAR'` und
  `granularity = 'Gemeindeebene'`).

Aufruf (vom Repository aus; der Arbeitsordner nimmt die Zwischendateien auf und muss außerhalb des Repositorys
liegen, weil sie echte Quelldaten enthalten):
    python3 -I beispielberichte/pruefstand-2026-11-07-e51/wertabgleich/wertabgleich.py \\
        cache/inkar_2025.zip <Ausgabeordner>/werte-nach-lauf1.csv.gz <Arbeitsordner>
Für die Prüfkonfiguration (Gegenprobe mit kleiner Menge) zusätzlich:
        --kennziffer-beginnt 12 --kuerzel xbev,q_bev_fl,e5_bev,q_pendlersaldo,alo

Ausgegeben werden nur Zählungen und höchstens zehn Schlüssel je Fehlerart, keine Werte (Antwort 69: Quelldaten
werden nicht mit dem Code veröffentlicht). Rückgabe 0 bei 0/0/0 ohne Doppel, sonst 1."""
import argparse
import csv
import gzip
import hashlib
import os
import subprocess
import sys
import time
import zipfile
from collections import Counter
from decimal import Decimal, InvalidOperation

# Regel aus E40 (in der Konfiguration `ziel.zusatz: {spalte: indikator, feld: bereich, ausser: [ZOM]}`):
# Indikatorname = Langtext, außerhalb des Bereichs ZOM mit „ (Bereich)“ dahinter. Hier fest nachgebaut statt
# aus der Konfiguration gelesen, weil die Standardbibliothek kein YAML liest und die Gegenprobe nicht vom
# geprüften Code abhängen soll.
OHNE_ZUSATZ = {"ZOM"}
# Name der CSV im ZIP und die Spalten, die der Abgleich braucht (Kopfzeile der Datei 2025).
CSV_NAME = "inkar_2025.csv"
SPALTEN = ("Bereich", "Kuerzel", "Indikator", "Raumbezug", "Kennziffer", "Zeitbezug", "Wert")
# Höchstens so viele Schlüssel je Fehlerart im Protokoll; die Zählung umfasst immer alle.
BEISPIELE = 10


def name_e40(bereich: str, indikator: str) -> str:
    """Indikatorname in dashboard_data_de nach E40.

    Args:
        bereich: Spalte Bereich der INKAR-Zeile (ZOM, LRB, EU, …).
        indikator: Langtext aus der Spalte Indikator.

    Returns:
        Den Langtext, außerhalb von ZOM mit „ (Bereich)“ dahinter."""
    return indikator if bereich in OHNE_ZUSATZ else f"{indikator} ({bereich})"


def wert_quelle(text: str) -> Decimal | None:
    """Wert der INKAR-Datei als Dezimalzahl.

    Die Datei schreibt Dezimalkomma ohne Tausendertrenner („6,20“). Gewandelt wird exakt über Decimal, nie
    über Gleitkomma, damit der Vergleich mit NUMERIC in der Datenbank keine Rundung einführt.

    Args:
        text: Feld Wert, schon ohne Rand.

    Returns:
        Die Zahl, oder None, wenn das Feld keine Zahl in dieser Schreibweise ist (dann als „nicht lesbar“
        gezählt)."""
    if "." in text:
        return None                      # Punkt wäre ein Tausendertrenner oder eine fremde Schreibweise
    try:
        return Decimal(text.replace(",", "."))
    except InvalidOperation:
        return None


def wert_datenbank(text: str) -> Decimal | None:
    """Wert aus der Ausfuhr der Datenbank (NUMERIC als Text, Dezimalpunkt) als Dezimalzahl.

    Args:
        text: Feld wert der Ausfuhr; leer bei NULL.

    Returns:
        Die Zahl, oder None bei NULL oder nicht lesbarem Text."""
    if text == "":
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def land(kennziffer: str) -> str:
    """Teilungsschlüssel für die Zwischendateien: die ersten beiden Stellen der Kennziffer (Land).

    Args:
        kennziffer: Kennziffer, wie sie in Quelle oder Datenbank steht.

    Returns:
        Zwei Zeichen; kürzere oder nicht numerische Kennziffern landen gemeinsam unter „xx“."""
    k = kennziffer[:2]
    return k if len(k) == 2 and k.isdigit() else "xx"


class Teiler:
    """Schreibt Zeilen nach Land getrennt in gzip-Dateien eines Arbeitsordners.

    Warum geteilt: Ein Wörterbuch mit allen 33,5 Mio. Schlüsseln bräuchte mehrere GB Speicher. Je Land sind es
    höchstens einige Millionen; verglichen wird später Land für Land."""

    def __init__(self, ordner: str, seite: str) -> None:
        """Legt den Teiler für eine Seite an.

        Args:
            ordner: Arbeitsordner (außerhalb des Repositorys).
            seite: „quelle“ oder „db“, Teil des Dateinamens."""
        self.ordner, self.seite = ordner, seite
        self.dateien: dict[str, tuple] = {}

    def schreiben(self, schluessel_land: str, zeile: list[str]) -> None:
        """Hängt eine Zeile an die Datei des Landes an (öffnet sie beim ersten Mal).

        Args:
            schluessel_land: Ergebnis von land().
            zeile: Felder der Zwischenzeile.

        Seiteneffekte: schreibt in <ordner>/<seite>-<land>.csv.gz."""
        if schluessel_land not in self.dateien:
            # Bleibt über viele Aufrufe offen (eine Datei je Land), deshalb kein with; schliessen() schließt
            # sie am Ende
            pfad = os.path.join(self.ordner, f"{self.seite}-{schluessel_land}.csv.gz")
            f = gzip.open(pfad, "wt", encoding="utf-8", newline="", compresslevel=1)  # noqa: SIM115
            self.dateien[schluessel_land] = (f, csv.writer(f))
        self.dateien[schluessel_land][1].writerow(zeile)

    def schliessen(self) -> list[str]:
        """Schließt alle Dateien.

        Returns:
            Die Länder, für die es eine Datei gibt."""
        for f, _ in self.dateien.values():
            f.close()
        return sorted(self.dateien)


def lesen(ordner: str, seite: str, schluessel_land: str):
    """Liest die Zwischendatei eines Landes; fehlt sie, gibt es keine Zeilen.

    Args:
        ordner: Arbeitsordner.
        seite: „quelle“ oder „db“.
        schluessel_land: Land.

    Yields:
        Die Felder je Zeile."""
    pfad = os.path.join(ordner, f"{seite}-{schluessel_land}.csv.gz")
    if not os.path.exists(pfad):
        return
    with gzip.open(pfad, "rt", encoding="utf-8", newline="") as f:
        yield from csv.reader(f)


def quelle_teilen(zip_pfad: str, ordner: str, beginnt: str, kuerzel: set[str] | None,
                  z: Counter) -> list[str]:
    """Liest die INKAR-CSV einmal und schreibt die übernommenen Zeilen nach Land geteilt in den Arbeitsordner.

    Eigene Lesart der Datei: Trennzeichen „;“, UTF-8, erste Zeile Kopf; eine Zeile mit anderer Feldzahl als
    der Kopf wird gezählt und nicht verwendet. Felder werden am Rand von Leerraum befreit. Übernommen wird,
    was die Lieferkonfiguration verlangt: Raumbezug genau „Gemeinden“ (`raumbezug: Gemeinden`), Kennziffer aus
    genau acht Ziffern (`kennziffer_stellen: 8`), die mit `beginnt` anfängt (`kennziffer_beginnt: ""`), Kürzel
    beliebig (`indikatoren: alle`) oder aus `kuerzel`, jedes Jahr (`zeitbezug: alle`), Wert und Zeitbezug
    nicht leer (`pflicht: [wert, zeitbezug]`). Jeder Ausschluss wird je Grund gezählt.

    Args:
        zip_pfad: INKAR-Gesamtdatei.
        ordner: Arbeitsordner für die Zwischendateien.
        beginnt: geforderter Anfang der Kennziffer ("" = alle Länder).
        kuerzel: erlaubte Kürzel oder None für alle.
        z: Zähler, wird ergänzt.

    Returns:
        Die Länder mit Zwischendatei.

    Seiteneffekte: startet `unzip -p` als Kindprozess, schreibt Zwischendateien."""
    # Feste Argumentliste ohne Shell; unzip, weil zipfile Deflate64 nicht entpackt (Modul-Docstring)
    proc = subprocess.Popen(["unzip", "-p", zip_pfad, CSV_NAME], stdout=subprocess.PIPE)  # noqa: S603, S607
    # Zeilenweise dekodiert; ein Anführungszeichen oder Zeilenumbruch in einem Feld würde hier als Zeile mit
    # falscher Feldzahl auffallen (gezählt unter quelle_feldzahl_falsch)
    leser = csv.reader((b.decode("utf-8") for b in proc.stdout), delimiter=";")
    kopf = next(leser)
    sp = {n: kopf.index(n) for n in SPALTEN}
    t = Teiler(ordner, "quelle")
    for f in leser:
        z["quelle_zeilen"] += 1
        if len(f) != len(kopf):
            z["quelle_feldzahl_falsch"] += 1
            continue
        if f[sp["Raumbezug"]].strip() != "Gemeinden":
            continue
        z["quelle_gemeinden"] += 1
        kz = f[sp["Kennziffer"]].strip()
        if len(kz) != 8 or not kz.isdigit():
            z["ausgeschlossen_kennziffer_nicht_achtstellig"] += 1
            continue
        if not kz.startswith(beginnt):
            z["ausgeschlossen_kennziffer_anderes_land"] += 1
            continue
        if kuerzel is not None and f[sp["Kuerzel"]].strip() not in kuerzel:
            z["ausgeschlossen_kuerzel_nicht_ausgewaehlt"] += 1
            continue
        w, zb = f[sp["Wert"]].strip(), f[sp["Zeitbezug"]].strip()
        if not w or not zb:
            z["ausgeschlossen_ohne_wert_oder_zeitbezug"] += 1
            continue
        z["quelle_soll"] += 1
        name = name_e40(f[sp["Bereich"]].strip(), f[sp["Indikator"]].strip())
        t.schreiben(land(kz), [kz, name, zb, w])
    proc.wait()
    z["unzip_rueckgabe"] = proc.returncode
    return t.schliessen()


def db_teilen(export_pfad: str, ordner: str, z: Counter) -> list[str]:
    """Liest die Ausfuhr der Zieltabelle und schreibt sie nach Land geteilt in den Arbeitsordner.

    Args:
        export_pfad: werte-nach-lauf1.csv.gz (Kennziffer, Indikator, Zeitbezug, Wert; CSV ohne Kopf).
        ordner: Arbeitsordner.
        z: Zähler, wird ergänzt.

    Returns:
        Die Länder mit Zwischendatei.

    Seiteneffekte: schreibt Zwischendateien."""
    t = Teiler(ordner, "db")
    with gzip.open(export_pfad, "rt", encoding="utf-8", newline="") as f:
        for zeile in csv.reader(f):
            z["db_zeilen"] += 1
            if len(zeile) != 4:
                z["db_feldzahl_falsch"] += 1
                continue
            t.schreiben(land(zeile[0]), zeile)
    return t.schliessen()


def vergleichen(ordner: str, laender: list[str], z: Counter, beispiele: dict[str, list]) -> None:
    """Vergleicht Land für Land jede Zeile der Quelle mit der Datenbank.

    Schlüssel ist (Kennziffer, Indikator, Zeitbezug) wie `ziel.schluessel`. Der Zeitbezug wird auf beiden
    Seiten als ganze Zahl verglichen (Spalte `zeitbezug` ist INTEGER), Kennziffer und Indikator als Text,
    genau so, wie sie stehen. Werte: zuerst als Text (Quelle mit Punkt statt Komma), dann als Decimal;
    „zahlgleich, andere Schreibweise“ heißt gleiche Zahl bei anderem Text; getrennt gezählt wird, ob nur
    nachgestellte Nullen der Nachkommastellen fehlen oder etwas anderes abweicht. Abweichend heißt: als Zahl
    verschieden (jede Rundung zählt also als Abweichung).

    Args:
        ordner: Arbeitsordner mit den Zwischendateien beider Seiten.
        laender: alle Länder, die auf einer der beiden Seiten vorkommen.
        z: Zähler, wird ergänzt.
        beispiele: Fehlerart -> Liste von Schlüsseln (höchstens BEISPIELE je Art), wird ergänzt.

    Seiteneffekte: keine außer den beiden Sammlungen."""
    def merken(art: str, schluessel: tuple) -> None:
        """Merkt einen Schlüssel als Beispiel einer Fehlerart."""
        if len(beispiele.setdefault(art, [])) < BEISPIELE:
            beispiele[art].append(schluessel)

    for lnd in laender:
        soll: dict[tuple, str] = {}
        for kz, name, zb, w in lesen(ordner, "quelle", lnd):
            k = (kz, name, int(zb) if zb.isdigit() else zb)
            if k in soll:
                # Zwei Quellzeilen mit demselben Zielschlüssel: die Datenbank könnte nur eine halten
                z["quelle_doppelter_zielschluessel"] += 1
                merken("quelle_doppelter_zielschluessel", k)
                continue
            soll[k] = w
        z[f"soll_land_{lnd}"] = len(soll)
        gesehen = set()
        for zeile in lesen(ordner, "db", lnd):
            kz, name, zb, w_db = zeile
            k = (kz, name, int(zb) if zb.isdigit() else zb)
            if k in gesehen:
                z["db_doppelter_zielschluessel"] += 1
                merken("db_doppelter_zielschluessel", k)
                continue
            gesehen.add(k)
            w_q = soll.get(k)
            if w_q is None:
                z["ueberzaehlig"] += 1
                merken("ueberzaehlig", k)
                continue
            z["verglichen"] += 1
            dq, dd = wert_quelle(w_q), wert_datenbank(w_db)
            if dq is None:
                z["wert_quelle_nicht_lesbar"] += 1
                merken("wert_quelle_nicht_lesbar", k)
            elif dd is None:
                z["wert_db_leer_oder_nicht_lesbar"] += 1
                merken("wert_db_leer_oder_nicht_lesbar", k)
            elif w_q.replace(",", ".") == w_db:
                z["wert_textgleich"] += 1
            elif dq == dd:
                z["wert_zahlgleich_andere_schreibweise"] += 1
                # Art des Unterschieds: nur nachgestellte Nullen der Nachkommastellen (und ein dann leeres
                # Komma) weggefallen, etwa „6,20“ -> 6.2, oder etwas anderes (etwa Exponentschreibweise)
                q = w_q.replace(",", ".")
                if "." in q and q.rstrip("0").rstrip(".") == w_db:
                    z["davon_nur_nachgestellte_nullen"] += 1
                else:
                    z["davon_andere_schreibweise"] += 1
                    merken("wert_zahlgleich_andere_schreibweise", k)
            else:
                z["wert_abweichend"] += 1
                merken("wert_abweichend", k)
        fehlend = [k for k in soll if k not in gesehen]
        z["fehlend"] += len(fehlend)
        for k in fehlend[:BEISPIELE]:
            merken("fehlend", k)


def main() -> int:
    """Führt den Abgleich aus und gibt das Protokoll auf stdout aus.

    Returns:
        0, wenn nichts fehlt, nichts überzählig ist, kein Wert abweicht und kein Schlüssel doppelt ist;
        sonst 1.

    Seiteneffekte: Zwischendateien im Arbeitsordner (bleiben dort, damit sich ein Befund nachsehen lässt),
    Kindprozess unzip."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("zip")
    ap.add_argument("export")
    ap.add_argument("arbeitsordner")
    ap.add_argument("--kennziffer-beginnt", default="")
    ap.add_argument("--kuerzel", default=None, help="Kürzel mit Komma getrennt; ohne Angabe alle")
    a = ap.parse_args()
    os.makedirs(a.arbeitsordner, exist_ok=True)
    kuerzel = set(a.kuerzel.split(",")) if a.kuerzel else None
    z: Counter = Counter()
    beispiele: dict[str, list] = {}
    t0 = time.monotonic()

    # Inhaltsverzeichnis des ZIP mit zipfile: Name, Größe und Packmethode der CSV (9 = Deflate64)
    with zipfile.ZipFile(a.zip) as zf:
        info = zf.getinfo(CSV_NAME)
    with open(a.export, "rb") as f:
        export_sha = hashlib.file_digest(f, "sha256").hexdigest()

    laender = sorted(set(quelle_teilen(a.zip, a.arbeitsordner, a.kennziffer_beginnt, kuerzel, z))
                     | set(db_teilen(a.export, a.arbeitsordner, z)))
    t_teilen = time.monotonic() - t0
    vergleichen(a.arbeitsordner, laender, z, beispiele)

    # Protokoll: nur Dateinamen, keine Pfade; nur Zählungen und Schlüssel, keine Werte
    print(f"# Wertabgleich INKAR je Zeile (wertabgleich.py), Quelle {os.path.basename(a.zip)} "
          f"({CSV_NAME}: {info.file_size} Bytes entpackt, Packmethode {info.compress_type}), Zieltabelle aus "
          f"{os.path.basename(a.export)} (sha256 der gzip-Datei {export_sha})")
    print(f"# Auswahl: Raumbezug Gemeinden, Kennziffer 8 Ziffern, beginnt mit \"{a.kennziffer_beginnt}\", "
          f"Kürzel {'alle' if kuerzel is None else ','.join(sorted(kuerzel))}, alle Jahre, Wert und "
          f"Zeitbezug nicht leer; Indikatorname nach E40; Schlüssel (Kennziffer, Indikator, Zeitbezug)")
    print(f"# Laufzeit {time.monotonic() - t0:.0f} s (davon Lesen und Teilen {t_teilen:.0f} s), "
          f"unzip rc={z['unzip_rueckgabe']}")
    print("\n## Quelle")
    for k in ("quelle_zeilen", "quelle_feldzahl_falsch", "quelle_gemeinden",
              "ausgeschlossen_kennziffer_nicht_achtstellig", "ausgeschlossen_kennziffer_anderes_land",
              "ausgeschlossen_kuerzel_nicht_ausgewaehlt", "ausgeschlossen_ohne_wert_oder_zeitbezug",
              "quelle_soll", "quelle_doppelter_zielschluessel"):
        print(f"{k}: {z[k]}")
    print("\n## Zieltabelle (dashboard_data_de, source INKAR, Gemeindeebene, nach Lauf 1)")
    for k in ("db_zeilen", "db_feldzahl_falsch", "db_doppelter_zielschluessel"):
        print(f"{k}: {z[k]}")
    print("\n## Abgleich je Zeile")
    for k in ("verglichen", "fehlend", "ueberzaehlig", "wert_abweichend", "wert_textgleich",
              "wert_zahlgleich_andere_schreibweise", "davon_nur_nachgestellte_nullen",
              "davon_andere_schreibweise", "wert_quelle_nicht_lesbar",
              "wert_db_leer_oder_nicht_lesbar"):
        print(f"{k}: {z[k]}")
    print("\n## Soll-Zeilen je Land (erste zwei Stellen der Kennziffer)")
    print(" ".join(f"{lnd}:{z[f'soll_land_{lnd}']}" for lnd in laender))
    if beispiele:
        print(f"\n## Beispiele (höchstens {BEISPIELE} Schlüssel je Art, keine Werte)")
        for art, liste in sorted(beispiele.items()):
            for k in liste:
                print(f"{art}: {k}")
    fehler = (z["fehlend"] + z["ueberzaehlig"] + z["wert_abweichend"] + z["wert_quelle_nicht_lesbar"]
              + z["wert_db_leer_oder_nicht_lesbar"] + z["quelle_doppelter_zielschluessel"]
              + z["db_doppelter_zielschluessel"] + z["quelle_feldzahl_falsch"] + z["db_feldzahl_falsch"])
    ergebnis = "0/0/0" if fehler == 0 else "ABWEICHUNG"
    print(f"\nErgebnis: fehlend {z['fehlend']}, überzählig {z['ueberzaehlig']}, abweichend "
          f"{z['wert_abweichend']} ({ergebnis}); Quellzeilen = verglichen + fehlend: "
          f"{z['quelle_soll'] - z['quelle_doppelter_zielschluessel']} = {z['verglichen'] + z['fehlend']}")
    return 0 if fehler == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
