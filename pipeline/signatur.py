"""Signatur für --version: Brandenburg als Zeichen, dazu eine Notiz aus der Geschichte der Vermessung.

Der Umriss ist einmal aus der Quelle gemeinden_lgb berechnet (PostGIS, 413 Gemeindeflächen der LGB,
Lauf vom 02.11.2026, damals noch über die Sicht der Vorstufe): 46 × 24 Zellen, je Zelle rund
5 × 10 km, „:“ heißt, die Zellmitte liegt in Brandenburg, „o“ ist die TH Brandenburg. Das Loch ist
Berlin. Mit dem Schema von MOSIDI sinngemäß:

    WITH bb AS (SELECT ST_Transform(ST_Union(geom), 25833) g
                FROM "Kommunale Gebiete Brandenburg (InNoWest)") ...  -- Zellmitten, ST_Contains

Die Notizen sind belegt (abgerufen 02.11.2026), Unsicheres steht mit „um“ oder Doppeljahr da:
Neue Deutsche Biographie (Meydenbauer NDB 17, Helmert NDB 8, Baeyer NDB 1, deutsche-biographie.de),
Geschichte des GFZ (gfz.de/en/about-us/organisation/history, Helmertturm: gfz.de/en/press/news/
details/helmert-turm), Philipps-Universität Marburg (Messbildverfahren, uni-marburg.de/fotomarburg),
A. Grimm, „The Origin of the Term Photogrammetry“ (isprs.org).

Stellung im Ablauf: keine. `laden.main` gibt den Text nur bei --version aus und beendet sich dann,
ohne Konfiguration, Netz oder Datenbank. Umriss und Notizen stehen fest im Code; zur Laufzeit wird
nichts berechnet oder abgerufen.
"""
from __future__ import annotations

import textwrap
from datetime import date

# 24 Zeilen zu 46 Zellen, Zeichen wie oben im Moduldocstring erklärt; die Leerzeilen am Anfang und Ende
# entfernt `text`
UMRISS = r"""
                                 :
                               ::::::
         ::::::               :::::::::
    ::::::::::::::::    : ::::::::::::::::
:::::::::::::::::::::::::::::::::::::::::
     ::::::::::::::::::::::::::::::::::::
       :::::::::::::::::::::::::::::::
             :::::::::::::::::::::::::
            :::::::::::::::::::::::::::
            ::::::::::::::::::::::::::::::
           :::::::::::::     :::::::::::::::
             :::::::::::       :::::::::::::
             :::o::::::: :  :   :::::::::::
            :::::::::::::::::::::::::::::::
            :::::::::::::::::::::::::::::::::
            :::::::::::::::::::::::::::::::::
              ::::::::::::::::::::::::::::::::
                    :::::::::::::::::::::::::
                        ::::::::::::::::::::
                        ::::::::::::::::::::
                        ::::::::::::::::::::::
                        ::::::::::::::::::::::
                         ::::::::::::
                             :::::::
"""

# Je Sprache dieselben Notizen in derselben Reihenfolge, damit an einem Tag in jeder Sprache dieselbe
# erscheint
NOTIZEN = {
    "de": [
        "Friedrich Robert Helmert (1843–1917) weihte 1892 das Geodätische Institut auf dem "
        "Telegrafenberg in Potsdam ein. Nach ihm heißt die Helmert-Transformation, mit der man "
        "Koordinaten zwischen Bezugssystemen umrechnet.",
        "Albrecht Meydenbauer (1834–1921) wäre um 1858 am Wetzlarer Dom beinahe abgestürzt. "
        "Danach wollte er das Messen von Hand durch das Foto ersetzen: das Messbild.",
        "Das Wort „Photogrammetrie“ erschien 1867 zuerst gedruckt, im Wochenblatt des "
        "Architektenvereins zu Berlin; es geht auf Meydenbauer zurück, den Namen schlug Otto Kersten vor.",
        "1885 gründete Meydenbauer in Berlin die Königlich Preußische Messbildanstalt und leitete "
        "sie bis 1909.",
        "Johann Jacob Baeyer (1794–1885) regte 1861 die Mitteleuropäische Gradmessung an; "
        "1870 nahm in Berlin das Geodätische Institut die Arbeit auf.",
        "Der Helmertturm auf dem Telegrafenberg, 1892/93 gebaut, war Bezugspunkt der "
        "preußischen Landesvermessung.",
    ],
    "en": [
        "Friedrich Robert Helmert (1843–1917) inaugurated the Geodetic Institute on the "
        "Telegrafenberg in Potsdam in 1892. The Helmert transformation, used to convert "
        "coordinates between reference systems, is named after him.",
        "Albrecht Meydenbauer (1834–1921) nearly fell from Wetzlar Cathedral around 1858. "
        "Afterwards he set out to replace measuring by hand with the photograph.",
        "The word 'photogrammetry' first appeared in print in 1867, in the weekly of the Berlin "
        "architects' association; it goes back to Meydenbauer, the name was suggested by Otto Kersten.",
        "In 1885 Meydenbauer founded the Royal Prussian Photogrammetric Institute "
        "(Messbildanstalt) in Berlin and led it until 1909.",
        "Johann Jacob Baeyer (1794–1885) proposed the Central European Arc Measurement in 1861; "
        "the Geodetic Institute started work in Berlin in 1870.",
        "The Helmert Tower on the Telegrafenberg, built 1892/93, was a reference point of the "
        "Prussian survey.",
    ],
}

KOPF = {
    "de": "geodaten-import-pipeline · Apache-2.0 · Stiebitz Souverain Systems UG, Potsdam",
    "en": "geodaten-import-pipeline · Apache-2.0 · Stiebitz Souverain Systems UG, Potsdam",
}


def text(sprache: str = "de", heute: date | None = None) -> str:
    """Umriss, Kopfzeile und die Notiz des Tages (wechselt täglich, ohne Zufall).

    Die Notiz ergibt sich aus der Tageszahl des Datums modulo der Anzahl der Notizen: am selben Tag
    immer dieselbe, über die Tage reihum alle.

    Args:
        sprache: Sprachcode; unbekannte Sprachen bekommen die deutschen Texte.
        heute: Datum für die Wahl der Notiz, None = heute (für Tests einstellbar).

    Returns:
        Mehrzeiliger Text, Notiz auf 72 Zeichen umbrochen, mit Zeilenumbruch am Ende.
    """
    notizen = NOTIZEN.get(sprache, NOTIZEN["de"])
    notiz = notizen[(heute or date.today()).toordinal() % len(notizen)]
    return (f"{UMRISS.strip(chr(10))}\n\n{KOPF.get(sprache, KOPF['de'])}\n\n"
            f"{textwrap.fill(notiz, 72)}\n")
