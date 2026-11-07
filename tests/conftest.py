"""Gemeinsame Hilfen der Tests: ein Statistischer Bericht als XLSX im Aufbau der Berichte des Amts für
Statistik Berlin-Brandenburg (A I 4 / A V 2), mit erfundenen Zahlen (E48, Antwort 69: keine Quelldaten im
Repository). Aufbau wie dort: Blatt „2.“ mit den kreisfreien Städten, den Kreisen und dem Land, Blätter
„3.1“ bis „3.14“ je Landkreis mit seinen Gemeinden und der Kreissumme, Titelzeile, zweizeiliger Kopf,
Schlüssel in der zweiten und in der letzten Spalte, Fußnoten unter einem Strich.

Genutzt vom Quelltyp xlsx (pipeline/quellen.py) in tests/test_xlsx.py ohne Datenbank (Fixture `bericht`)
und in tests/test_datenbank.py über den ganzen Ablauf bis in dashboard_data_de (Import aus conftest).
Die Parameter von afs_bericht bauen gezielt Abweichungen ein (fehlendes Blatt, umgestellte Spalten,
abweichende Landessumme, beschädigte Werte), an denen die Tests prüfen, dass der Adapter Spalten nach der
Beschriftung liest und Lücken erkennt, statt still Werte zu löschen."""
from pathlib import Path

import pytest
import requests


@pytest.fixture(autouse=True)
def _kein_netz(monkeypatch):
    """Für jeden Test: requests erreicht kein Netz (E50). Seit E50 erlaubt die ausgelieferte Konfiguration den
    INKAR-Abruf von www.bbr-server.de mit benannter Freigabe; ein vergessener Ersatz für requests.get oder
    requests.head würde sonst eine echte Anfrage stellen. Gesperrt wird die unterste Stufe von requests
    (HTTPAdapter.send); Tests, die requests.get oder requests.head selbst ersetzen, sind davon nicht berührt.
    tests/test_datenbank.py nutzt kein HTTP. tests/test_ende_zu_ende.py (E52) startet die Pipeline als eigenen
    Prozess, für den diese Sperre nicht gilt; er bekommt nur Adressen eines Testservers auf 127.0.0.1, was der
    Test vor dem ersten Lauf mit --ziele prüft. Der Testprozess selbst bleibt auch dort ohne Netz."""
    def gesperrt(self, anfrage, *a, **k):
        raise AssertionError(f"Netzabruf im Test: {anfrage.method} {anfrage.url}")
    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", gesperrt)

KOPF = ["Amtlicher \nGemeinde-\nschlüssel", "Kreisfreie Stadt\nLandkreis", "Bevölkerung\nam\nJahresanfang",
        "Natürliche Bevölkerungsbewegung² ", "Bevölkerung\nam\nJahresende", "Fläche⁴\nin km²",
        "Bevölkerung\nje km²", "Amtlicher \nGemeinde-\nschlüssel"]
UNTERKOPF = [None, None, None, "Lebend-\ngeborene", None, None, None, None]
FUSS = ["_____", "1 Bevölkerungsfortschreibung (Testdaten, erfunden)", "2 Testfußnote", "3 Testfußnote"]


def gemeinden_je_kreis(n: int = 2) -> dict[str, list[tuple]]:
    """Je Landkreis 3.1 bis 3.14 n Gemeinden, erfundene Schlüssel 12060… bis 12073…, keiner endet auf 000."""
    return {f"3.{i}": [(f"12{60 + i - 1:03d}{j:03d}", 1000 * i + j, round(10.5 * i + j / 100, 2))
                       for j in range(1, n + 1)] for i in range(1, 15)}


KREISFREIE = [("12051000", 70000, 229.73), ("12052000", 90000, 165.61), ("12053000", 50000, 147.85),
              ("12054000", 180000, 188.24)]


def afs_bericht(pfad: Path, kreise: dict | None = None, kreisfreie: list | None = None, jahr: int = 2025,
                flaeche_stand: str = "31.12.2024", land: tuple | None = None, ohne_blatt: str | None = None,
                spalten: list[int] | None = None, nachher=None) -> Path:
    """Schreibt den Bericht nach `pfad` und gibt den Pfad zurück.

    kreise: Blattname → Gemeinden, Gemeinde = (Schlüssel, Bevölkerung, Fläche[, Schlüssel der letzten
    Spalte]); jeder Wert darf jeden Typ haben (beschädigte Zeilen). Standard gemeinden_je_kreis().
    kreisfreie: Zeilen der kreisfreien Städte auf Blatt „2.“, Standard KREISFREIE.
    jahr: Berichtsjahr im Titel; flaeche_stand: Datum in der Fußnote 4 („Stand …“).
    land: (Bevölkerung, Fläche) der Zeile 12000000, sonst die Summe. ohne_blatt: dieses Blatt fehlt.
    spalten: Reihenfolge der Kopfspalten (Umstellung beim Anbieter). nachher(wb): letzte Änderungen am
    Arbeitsblatt vor dem Speichern. Kreissummen werden aus den Gemeinden gebildet, Nichtzahlen zählen 0."""
    import openpyxl

    kreise = gemeinden_je_kreis() if kreise is None else kreise
    kreisfreie = KREISFREIE if kreisfreie is None else kreisfreie
    folge = spalten or list(range(len(KOPF)))
    wb = openpyxl.Workbook()
    # Titelblatt wie im Bericht; config/quellen.yaml nennt nur die Blätter 2. und 3.1 bis 3.14 (blaetter),
    # dieses Blatt liest die Pipeline also nicht
    wb.active.title = "Titel"
    wb["Titel"]["B7"] = f"Bevölkerungsentwicklung und \nFlächen der Gemeinden (Testdaten)\n{jahr}"

    def zeile(g) -> list:
        """Datenzeile aus einer Gemeinde oder Summe g: Spalte A bleibt leer, danach die acht Werte in der
        Reihenfolge `folge`; Lebendgeborene fest 1, Dichte leer."""
        ags, bev, fl = g[0], g[1], g[2]
        letzte = g[3] if len(g) > 3 else ags
        werte = [ags, "Ort", bev, 1, bev, fl, None, letzte]
        return [None] + [werte[i] for i in folge]

    def blatt(name: str, titel: list[str], daten: list[list], kopfzeile: int) -> None:
        """Legt das Blatt `name` an: Titelzeilen ab Zeile 1, Kopf und Unterkopf ab `kopfzeile`, nach einer
        freien Zeile die Daten (None = Leerzeile), direkt darunter die Fußnoten samt Flächenstand."""
        ws = wb.create_sheet(name)
        for i, t in enumerate(titel, 1):
            ws.cell(i, 2, t)
        for r, inhalt in ((kopfzeile, KOPF), (kopfzeile + 1, UNTERKOPF)):
            for c, i in enumerate(folge, 2):
                ws.cell(r, c, inhalt[i])
        # Zwischen Unterkopf und erster Datenzeile bleibt eine Zeile frei; auf den Kreisblättern (Kopf in
        # Zeile 4) beginnen die Daten so in Zeile 7 (Fundstelle „Blatt 3.1, Zeile 7“ in test_datenbank)
        r = kopfzeile + 3
        for d in daten:
            if d is None:
                r += 1
                continue
            for c, v in enumerate(d, 1):
                ws.cell(r, c, v)
            r += 1
        for t in [*FUSS, f"4 Stand {flaeche_stand}"]:
            ws.cell(r, 2, t)
            r += 1

    def zahl(v):
        """v, wenn es eine Zahl ist (bool zählt nicht), sonst 0; so lassen sich Summen auch über absichtlich
        beschädigte Zeilen bilden."""
        return v if isinstance(v, (int, float)) and not isinstance(v, bool) else 0

    summen = {}
    for name, gem in kreise.items():
        k = f"12{59 + int(name.split('.')[1]):03d}000"     # Kreissumme, aus dem Blatt, nicht aus den Zeilen
        summen[name] = (k, sum(zahl(g[1]) for g in gem), round(sum(zahl(g[2]) for g in gem), 2))
    titel = f"Bevölkerungsentwicklung und Bevölkerung¹ im Jahr {jahr} sowie Bevölkerungsdichte"
    bev = sum(zahl(g[1]) for g in kreisfreie) + sum(s[1] for s in summen.values())
    fl = round(sum(zahl(g[2]) for g in kreisfreie) + sum(s[2] for s in summen.values()), 2)
    # Ohne Vorgabe ist die Landeszeile die Summe; ein abweichendes `land` ergibt eine Landessumme, die
    # nicht zu den Zeilen passt
    land = land or (bev, fl)
    if ohne_blatt != "2.":
        blatt("2.", [f"2  {titel} \n    im Land nach Verwaltungsbezirken"],
              [zeile(g) for g in kreisfreie] + [None] + [zeile(s) for s in summen.values()]
              + [zeile(("12000000", land[0], land[1]))], kopfzeile=3)
    for name, gem in kreise.items():
        if name != ohne_blatt:
            blatt(name, [f"3   {titel}", f"{name}  Landkreis Test"],
                  [zeile(g) for g in gem] + [None, zeile(summen[name])], kopfzeile=4)
    if nachher:
        nachher(wb)
    wb.save(pfad)
    return pfad


@pytest.fixture
def bericht(tmp_path):
    """Fixture: Funktion bericht(**kw) -> Pfad, die afs_bericht(**kw) in den tmp_path des Tests schreibt,
    je Aufruf unter einem neuen Dateinamen (bericht-0.xlsx, bericht-1.xlsx, …)."""
    # Eigene Datei je Aufruf, damit ein Test mehrere Fassungen nebeneinander schreiben kann
    zaehler = iter(range(1000))

    def schreiben(**kw):
        """Schreibt einen Bericht mit afs_bericht(**kw) unter einem neuen Dateinamen in tmp_path."""
        return afs_bericht(tmp_path / f"bericht-{next(zaehler)}.xlsx", **kw)
    return schreiben
