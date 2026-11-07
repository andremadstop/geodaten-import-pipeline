# ruff: noqa: F403, F405, E501
# Szenenskript für Manim: Sternimport ist dort üblich, Zeilen folgen dem Bildaufbau.
"""Erklärfilm „Was bei jedem Lauf passiert“ (Geodaten-Import-Pipeline, VA-2026-536).

Bildsprache: Zeichenblatt mit Schriftfeld, Plotterlinien, Fernschreiber-Bericht.
Alle Zahlen und Berichtszeilen werden beim Rendern aus den Belegdateien des Repos gelesen
(nur lesen); `belege()` prüft sie gegen die erwarteten Werte und schreibt sie nach zahlen.json im
Datenordner. Die Grenzen der Gemeinden und Kreise kommen aus `geo_vereinfacht.json` im Datenordner
(erzeugt von geometrie.py); Geodaten liegen nie im Repo.

Pfade: Repo-Wurzel = drei Ebenen über dieser Datei (docs/filme/manim/), sonst PIPELINE_REPO.
Datenordner = FILM_DATEN (relativ zum Arbeitsverzeichnis), sonst cache/filme in der Repo-Wurzel.
Rendern aus der Repo-Wurzel (Einzelheiten in README.md):
    FILM_DATEN=cache/filme uv run --no-project --with manim==0.22.1 manim -qh --frame_rate 30 \
        --media_dir cache/filme/media docs/filme/manim/film.py Lauf
"""
import json
import os
import re
from pathlib import Path

from manim import *

# ---------------------------------------------------------------------------
# Belege
HIER = Path(__file__).resolve().parent
REPO = Path(os.environ.get("PIPELINE_REPO") or HIER.parents[2])
DATEN = Path(os.environ.get("FILM_DATEN") or REPO / "cache" / "filme")
if not DATEN.is_absolute():
    DATEN = Path.cwd() / DATEN
BB = REPO / "beispielberichte"
E51 = BB / "pruefstand-2026-11-07-e51"


def de(n):
    return f"{n:,}".replace(",", ".")


def pruefe(bedingung, was):
    if not bedingung:
        raise SystemExit(f"Beleg weicht ab: {was}")


def belege():
    q = {}
    l1 = json.loads((E51 / "mosidi-compose/20261107T043632Z.json").read_text())
    l2 = json.loads((E51 / "mosidi-compose/20261107T043901Z.json").read_text())
    z1 = {s["quelle"]: s["zaehler"] for s in l1["quellen"]}
    z2 = {s["quelle"]: s["zaehler"] for s in l2["quellen"]}
    q["gem_neu_l1"] = z1["gemeinden_lgb"]["neu"]
    q["gem_unv_l2"] = z2["gemeinden_lgb"]["unveraendert"]
    q["gem_l2_rest"] = [z2["gemeinden_lgb"][k] for k in ("neu", "geaendert", "geloescht")]
    q["kreise_neu_l1"] = z1["kreise_lgb"]["neu"]
    q["l1_txt"] = (E51 / "mosidi-compose/20261107T043632Z.txt").read_text().splitlines()
    q["fehler_txt"] = (BB / "20261030T074610Z.txt").read_text().splitlines()
    fj = json.loads((BB / "20261030T074610Z.json").read_text())
    q["fehler_fehlgeschlagen"] = fj["fehlgeschlagen"]
    q["fehler_ok"] = [s["quelle"] for s in fj["quellen"] if s["status"] == "ok"]
    w = {}
    for z in (E51 / "wertabgleich/ergebnis-vollumfang.txt").read_text().splitlines():
        m = re.match(r"^(\w+): (\d+)$", z)
        if m:
            w[m.group(1)] = int(m.group(2))
    q["inkar_werte"] = w["verglichen"]
    q["fehlend"], q["ueberzaehlig"], q["abweichend"] = w["fehlend"], w["ueberzaehlig"], w["wert_abweichend"]
    v1 = json.loads((E51 / "quellen/20261107T044222Z.json").read_text())
    q["inkar_neu_voll"] = next(s for s in v1["quellen"] if s["quelle"] == "inkar_gemeinden")["zaehler"]["neu"]
    q["voll_lauf"] = (E51 / "quellen/20261107T044222Z.txt").read_text().split()[1]
    inkar_zeile = re.search(r"^ INKAR +\| Gemeindeebene \| indikator \| +(\d+) \| +(\d+) \| +(\d+) \|",
                            (E51 / "quellen/datenbank-auszug.txt").read_text(), re.MULTILINE)
    q["voll_gemeinden"] = int(inkar_zeile.group(3))
    log = (E51 / "datenbanktests.log").read_text()
    q["pg"] = re.findall(r"^PostgreSQL (\d+\.\d+) ", log, re.MULTILINE)
    q["dbtests"] = [int(x) for x in re.findall(r"^(\d+) passed in", log, re.MULTILINE)]
    p = re.search(r"^(\d+) passed, (\d+) skipped", (E51 / "pruefen.log").read_text(), re.MULTILINE)
    q["pruefen"] = int(p.group(1))
    # Erwartete Werte: bricht ab, wenn eine Datei etwas anderes sagt
    pruefe(q["gem_neu_l1"] == 413 and q["gem_unv_l2"] == 413 and q["gem_l2_rest"] == [0, 0, 0], "Gemeinden")
    pruefe(q["kreise_neu_l1"] == 18, "Kreise")
    pruefe(all(z1["gemeinden_lgb"][k] == 0 for k in ("geaendert", "geloescht", "unveraendert")), "Erstlauf")
    pruefe(q["inkar_werte"] == 33547606 == q["inkar_neu_voll"] == int(inkar_zeile.group(1)), "INKAR-Werte")
    pruefe(q["voll_lauf"] == "20261107T044222Z" and q["voll_gemeinden"] == 10978, "Lieferkonfiguration")
    pruefe((q["fehlend"], q["ueberzaehlig"], q["abweichend"]) == (0, 0, 0), "Wertabgleich")
    pruefe(q["pg"] == ["16.15", "18.6"] and q["dbtests"] == [70, 70], "Datenbanktests")
    pruefe(q["pruefen"] == 424, "pruefen.log")
    pruefe(q["fehler_fehlgeschlagen"] == ["kaputte_quelle"], "Fehlerfall")
    return q


B = belege()
(DATEN / "zahlen.json").write_text(json.dumps({k: v for k, v in B.items() if not k.endswith("_txt")},
                                              ensure_ascii=False, indent=1))
GEO = json.loads((DATEN / "geo_vereinfacht.json").read_text())
pruefe(len(GEO["gemeinden_lgb"]) == B["gem_neu_l1"] and len(GEO["kreise_lgb"]) == B["kreise_neu_l1"], "Geometrie")

# ---------------------------------------------------------------------------
# Farbwelt: Zeichenpapier, Tusche, Petrol
PAPIER = "#ece6d7"
RASTER_FEIN = "#e0d8c4"
RASTER_GROB = "#d3c9b0"
TUSCHE = "#1c2a2f"
LEISE = "#6b6a5f"
PETROL = "#2a5d6b"
PETROL_HELL = "#9cbcc2"
PETROL_FLAECHE = "#cfdcd9"
ZIEGEL = "#9b3a36"
SANS = "Fira Sans"
SCHMAL = "Fira Sans Condensed"
MONO = "Hack"

config.background_color = PAPIER


def T(s, size=24, font=SANS, color=TUSCHE, weight=NORMAL, **kw):
    return Text(s, font=font, font_size=size, color=color, weight=weight, **kw)


def M(s, size=18, color=TUSCHE, **kw):
    return Text(s, font=MONO, font_size=size, color=color, **kw)


def einruecken(streifen, zeilen, size):
    """Text verwirft führende Leerzeichen; die Einrückung der Berichtszeilen wird nachgestellt."""
    cw = (M("0" * 21, size).width - M("0", size).width) / 20
    for mob, z in zip(streifen, zeilen, strict=True):
        mob.shift(RIGHT * cw * (len(z) - len(z.lstrip(" "))))


def ringe_zu_vm(ringe, sx, sy, ox, oy, farbe, breite, fuellung=None):
    g = VGroup()
    for r in ringe:
        pts = [np.array([ox + (x * sx), oy + (y * sy), 0.0]) for x, y in r]
        vm = VMobject(stroke_color=farbe, stroke_width=breite)
        vm.set_points_as_corners(pts)
        if fuellung:
            vm.set_fill(fuellung, opacity=1)
        g.add(vm)
    return g


def karte(name, hoehe, farbe, breite, mitte=ORIGIN, fuellung=None, bbox_von=None):
    feats = GEO[name]
    ref = GEO[bbox_von or name]
    xs = [p[0] for f in ref for r in f for p in r]
    ys = [p[1] for f in ref for r in f for p in r]
    s = hoehe / (max(ys) - min(ys))
    cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    g = VGroup(*[ringe_zu_vm(f, s, s, -cx * s, -cy * s, farbe, breite, fuellung) for f in feats])
    g.shift(mitte)
    return g


class Lauf(Scene):
    # -------------------------------------------------------------- Rahmen
    def zeichenblatt(self):
        fein, grob = VGroup(), VGroup()
        w, h = config.frame_width / 2, config.frame_height / 2
        x = -w
        i = 0
        while x <= w + 1e-6:
            (grob if i % 4 == 0 else fein).add(Line([x, -h, 0], [x, h, 0]))
            x += 0.25
            i += 1
        y, i = -h, 0
        while y <= h + 1e-6:
            (grob if i % 4 == 0 else fein).add(Line([-w, y, 0], [w, y, 0]))
            y += 0.25
            i += 1
        fein.set_stroke(RASTER_FEIN, 0.6)
        grob.set_stroke(RASTER_GROB, 0.9)
        rand = Rectangle(width=2 * w - 0.5, height=2 * h - 0.5).set_stroke(TUSCHE, 1.6)
        # Randmarken wie auf einem Zeichenblatt
        marken = VGroup()
        for k in range(1, 8):
            xx = -w + 0.25 + k * (2 * w - 0.5) / 8
            marken.add(Line([xx, h - 0.25, 0], [xx, h - 0.4, 0]), Line([xx, -h + 0.25, 0], [xx, -h + 0.4, 0]))
        for k in range(1, 4):
            yy = -h + 0.25 + k * (2 * h - 0.5) / 4
            marken.add(Line([-w + 0.25, yy, 0], [-w + 0.4, yy, 0]), Line([w - 0.25, yy, 0], [w - 0.4, yy, 0]))
        marken.set_stroke(TUSCHE, 1.2)
        return VGroup(fein, grob), VGroup(rand, marken)

    def schriftfeld(self, blatt, titel):
        w, h = config.frame_width / 2, config.frame_height / 2
        box = Rectangle(width=4.6, height=0.62).set_stroke(TUSCHE, 1.4)
        box.move_to([w - 0.25 - 2.3, -h + 0.25 + 0.31, 0])
        trenn = Line(box.get_top() + RIGHT * 1.25, box.get_bottom() + RIGHT * 1.25).set_stroke(TUSCHE, 1.0)
        kopf = T("GEODATEN-IMPORT-PIPELINE · VA-2026-536", 11, SCHMAL, LEISE, weight="MEDIUM")
        kopf.move_to(box.get_left() + RIGHT * (3.35 / 2 + 0.0) + UP * 0.14)
        kopf.align_to(box.get_left() + RIGHT * 0.12, LEFT)
        tit = T(titel, 15, SCHMAL, TUSCHE, weight="SEMIBOLD")
        tit.next_to(kopf, DOWN, buff=0.06).align_to(kopf, LEFT)
        bl = T(f"BLATT {blatt}/5", 15, SCHMAL, PETROL, weight="BOLD")
        bl.move_to([trenn.get_x() + (box.get_right()[0] - trenn.get_x()) / 2, box.get_y(), 0])
        return VGroup(box, trenn, kopf, tit, bl)

    def blattwechsel(self, n, titel):
        neu = self.schriftfeld(n, titel)
        self.play(*[ReplacementTransform(self.sf[i], neu[i]) for i in (2, 3, 4)], run_time=0.6)
        self.sf = VGroup(self.sf[0], self.sf[1], neu[2], neu[3], neu[4])

    def ueberschrift(self, nummer, text):
        n = T(nummer, 16, MONO, PETROL)
        t = T(text, 40, SCHMAL, TUSCHE, weight="SEMIBOLD")
        g = VGroup(n, t).arrange(RIGHT, buff=0.3, aligned_edge=DOWN)
        g.to_corner(UL, buff=0.6)
        strich = Line(g.get_left(), g.get_left() + RIGHT * 1.2).set_stroke(PETROL, 3)
        strich.next_to(g, DOWN, buff=0.14).align_to(g, LEFT)
        return VGroup(g, strich)

    def raeumen(self, behalten=(), zeit=0.6):
        fest = set(self.sf.get_family())
        weg = [m for m in self.mobjects if m not in (self.raster, self.rand, *behalten)
               and not (set(m.get_family()) & fest)]
        if weg:
            self.play(*[FadeOut(m) for m in weg], run_time=zeit)

    # -------------------------------------------------------------- Ablauf
    def construct(self):
        self.raster, self.rand = self.zeichenblatt()
        self.sf = self.schriftfeld(1, "Quellen und Ziel")
        self.add(self.raster)
        self.play(Create(self.rand), FadeIn(self.sf), run_time=1.0)
        self.blatt1()
        self.blatt2()
        self.blatt3()
        self.blatt4()
        self.blatt5()

    # 1 ----------------------------------------------------------------------
    def blatt1(self):
        titel = VGroup(T("Was bei jedem", 76, SCHMAL, TUSCHE, weight="SEMIBOLD"),
                       T("Lauf passiert", 76, SCHMAL, TUSCHE, weight="SEMIBOLD")).arrange(DOWN, aligned_edge=LEFT, buff=0.12)
        unter = VGroup(T("Geodaten-Import-Pipeline für MOSIDI", 24, SANS, LEISE, weight="LIGHT"),
                       T("TH Brandenburg · VA-2026-536", 24, SANS, LEISE, weight="LIGHT")).arrange(DOWN, aligned_edge=LEFT, buff=0.08)
        kopf = VGroup(titel, unter).arrange(DOWN, aligned_edge=LEFT, buff=0.35)
        kopf.move_to([0, 0.2, 0]).to_edge(LEFT, buff=1.0)
        strich = Line(ORIGIN, RIGHT * 1.6).set_stroke(PETROL, 4).next_to(kopf, UP, buff=0.3).align_to(kopf, LEFT)

        gem = karte("gemeinden_lgb", 5.6, PETROL, 0.7, mitte=[3.75, 0.3, 0])
        kr = karte("kreise_lgb", 5.6, TUSCHE, 1.7, mitte=[3.75, 0.3, 0], bbox_von="gemeinden_lgb")
        quelle = T(f"{B['gem_neu_l1']} Gemeinden, {B['kreise_neu_l1']} Kreise · © GeoBasis-DE/LGB, dl-de/by-2-0", 12, SANS, LEISE)
        quelle.next_to(gem, DOWN, buff=0.12).align_to(gem, RIGHT)

        # Namensnennung steht, bevor die erste Linie der Karte gezeichnet wird
        self.play(Create(strich), FadeIn(kopf, shift=UP * 0.15), FadeIn(quelle), run_time=1.0)
        self.play(LaggedStart(*[Create(g) for g in gem], lag_ratio=0.008), run_time=3.2)
        self.play(LaggedStart(*[Create(k) for k in kr], lag_ratio=0.05), run_time=1.4)
        self.wait(1.0)
        if getattr(self, "nur_titel", False):
            return

        # Drei Anbieter links, Ziel rechts
        ueb = self.ueberschrift("01", "Drei Anbieter, ein Ziel")
        daumen = VGroup(gem, kr).copy().scale(0.25).move_to([-5.55, 2.0, 0])
        lgb_t = VGroup(T("WFS der LGB", 22, SCHMAL, TUSCHE, weight="SEMIBOLD"),
                       T("Gebäude, Gemeinden, Kreise", 15, SANS, LEISE),
                       T("© GeoBasis-DE/LGB, dl-de/by-2-0", 11, SANS, LEISE)).arrange(DOWN, aligned_edge=LEFT, buff=0.07)
        lgb_t.next_to(daumen, RIGHT, buff=0.3)
        # Namensnennung bleibt durchgehend sichtbar: lgb_t kommt im selben Schritt, in dem quelle geht
        # Titel ganz weg, bevor Blatt 1 aufbaut; die Karte trägt quelle, bis lgb_t steht
        self.play(FadeOut(kopf), FadeOut(strich), run_time=0.5)
        self.play(VGroup(gem, kr).animate.scale(0.25).move_to([-5.55, 2.0, 0]),
                  quelle.animate.scale(0.8).next_to([-5.55, 2.0 - 0.7, 0], DOWN, buff=0.05).align_to([-6.5, 0, 0], LEFT),
                  FadeIn(ueb), run_time=1.0)
        self.play(FadeOut(quelle), FadeIn(lgb_t), run_time=0.4)

        # XLSX: Tabellenblatt als Raster
        xl = VGroup(*[Rectangle(width=0.32, height=0.17) for _ in range(20)]).arrange_in_grid(5, 4, buff=0)
        xl.set_stroke(TUSCHE, 1.0)
        for i in range(4):
            xl[i].set_fill(PETROL_FLAECHE, 1)
        xl.move_to([-5.55, 0.05, 0])
        xl_t = VGroup(T("Statistischer Bericht, XLSX", 22, SCHMAL, TUSCHE, weight="SEMIBOLD"),
                      T("SB_A01-04_00_2025j01_BB.xlsx", 14, MONO, LEISE),
                      T("Amt für Statistik Berlin-Brandenburg, CC BY 3.0 DE", 11, SANS, LEISE)
                      ).arrange(DOWN, aligned_edge=LEFT, buff=0.07)
        xl_t.next_to(xl, RIGHT, buff=0.3).align_to(lgb_t, LEFT)

        # ZIP: Mappe mit Reißverschluss
        mappe = Rectangle(width=1.0, height=0.8).set_stroke(TUSCHE, 1.2)
        zahn = VGroup(*[Line(LEFT * 0.06, RIGHT * 0.06).shift(DOWN * 0.08 * k) for k in range(8)]).set_stroke(TUSCHE, 1.2)
        zahn.move_to(mappe).align_to(mappe, UP).shift(DOWN * 0.06)
        zip_ = VGroup(mappe, zahn).move_to([-5.55, -1.85, 0])
        zip_t = VGroup(T("INKAR, ZIP", 22, SCHMAL, TUSCHE, weight="SEMIBOLD"),
                       T("inkar_2025.zip, abgelegte Datei", 14, MONO, LEISE),
                       T("INKAR, © BBSR Bonn 2025, dl-de/by-2-0", 11, SANS, LEISE)
                       ).arrange(DOWN, aligned_edge=LEFT, buff=0.07)
        zip_t.next_to(zip_, RIGHT, buff=0.3).align_to(lgb_t, LEFT)

        self.play(LaggedStart(Create(xl), FadeIn(xl_t, shift=RIGHT * 0.1),
                              Create(zip_), FadeIn(zip_t, shift=RIGHT * 0.1), lag_ratio=0.25), run_time=2.2)

        # Ziel: MOSIDI als Datenbank-Zylinder
        zx, zy = 4.3, 0.05
        zr = 1.35
        oben = Ellipse(width=2 * zr, height=0.5).move_to([zx, zy + 1.6, 0])
        unten = Arc(radius=zr, start_angle=PI, angle=PI).stretch(0.25 / zr, 1).move_to([zx, zy - 1.6 - 0.125, 0])
        seiten = VGroup(Line([zx - zr, zy + 1.6, 0], [zx - zr, zy - 1.6, 0]),
                        Line([zx + zr, zy + 1.6, 0], [zx + zr, zy - 1.6, 0]))
        zyl = VGroup(oben, unten, seiten).set_stroke(TUSCHE, 1.6)
        zyl_t = T("MOSIDI", 26, SCHMAL, TUSCHE, weight="BOLD").move_to([zx, zy + 1.05, 0])
        tabellen = VGroup(*[M(s, 12) for s in ("Gebäude (ALKIS)", "Kommunale Gebiete", "Brandenburg (InNoWest)",
                                                 "Landkreis", "dashboard_data_de")]).arrange(DOWN, buff=0.13)
        tabellen[2].shift(UP * 0.08)
        tabellen.move_to([zx, zy - 0.25, 0])
        unv = T("Bestandstabellen, Schema unverändert", 14, SANS, PETROL, weight="MEDIUM")
        unv.next_to(zyl, DOWN, buff=0.18)

        pip = RoundedRectangle(corner_radius=0.08, width=1.8, height=1.0).set_stroke(PETROL, 2, opacity=1)
        pip.set_fill(PAPIER, 1).move_to([1.15, zy, 0])
        pip_t = T("Pipeline", 22, SCHMAL, PETROL, weight="SEMIBOLD").move_to(pip)
        pfeile = VGroup()
        for quell in (lgb_t, xl_t, zip_t):
            start = [lgb_t.get_right()[0] + 0.25 if quell is not lgb_t else quell.get_right()[0] + 0.25, quell.get_y(), 0]
            start = [max(lgb_t.get_right()[0], xl_t.get_right()[0], zip_t.get_right()[0]) + 0.2, quell[0].get_y(), 0]
            pfeile.add(CubicBezier(np.array(start), np.array(start) + RIGHT * 0.9,
                                   pip.get_left() + LEFT * 0.9, pip.get_left()).set_stroke(TUSCHE, 1.3))
        ziel_pfeil = Arrow(pip.get_right(), [zx - zr, zy, 0], buff=0.08, stroke_width=2.5,
                           max_tip_length_to_length_ratio=0.12, color=PETROL)
        self.play(Create(zyl), FadeIn(zyl_t), run_time=1.0)
        self.play(LaggedStart(*[FadeIn(t, shift=UP * 0.05) for t in tabellen], lag_ratio=0.15), FadeIn(unv), run_time=1.2)
        self.play(LaggedStart(*[Create(p) for p in pfeile], lag_ratio=0.2), FadeIn(pip), FadeIn(pip_t), run_time=1.3)
        schem1 = T("Darstellung schematisch", 11, SANS, LEISE).move_to([5.45, -2.75, 0])
        self.play(GrowArrow(ziel_pfeil), FadeIn(schem1), run_time=0.6)
        self.wait(1.8)

    # 2 ----------------------------------------------------------------------
    def blatt2(self):
        self.raeumen()
        self.blattwechsel(2, "Vier Schritte je Quelle")
        ueb = self.ueberschrift("02", "Vier Schritte je Quelle")
        self.play(FadeIn(ueb), run_time=0.5)

        xs = [-5.0, -1.65, 1.7, 5.05]
        y0 = 1.55
        bahn = Line([-6.3, y0, 0], [6.3, y0, 0]).set_stroke(TUSCHE, 1.4)
        namen = ["Abrufen", "Prüfen", "Vergleichen", "Abgleichen"]
        stationen = VGroup()
        for i, (x, n) in enumerate(zip(xs, namen, strict=True)):
            kreis = Circle(radius=0.3).set_stroke(TUSCHE, 1.6).set_fill(PAPIER, 1).move_to([x, y0, 0])
            nr = T(f"{i + 1:02d}", 15, MONO, TUSCHE).move_to(kreis)
            name = T(n, 26, SCHMAL, TUSCHE, weight="SEMIBOLD").move_to([x, y0 + 0.62, 0])
            stationen.add(VGroup(kreis, nr, name))
        schem = T("Ablauf schematisch", 11, SANS, LEISE).move_to([5.45, -2.75, 0])
        self.play(Create(bahn), LaggedStart(*[FadeIn(s, shift=DOWN * 0.1) for s in stationen], lag_ratio=0.15),
                  FadeIn(schem), run_time=1.3)

        marke = VGroup(RoundedRectangle(corner_radius=0.05, width=1.55, height=0.36).set_stroke(PETROL, 1.5).set_fill(PETROL, 1),
                       M("gemeinden_lgb", 13, PAPIER))
        marke[1].move_to(marke[0])
        marke.move_to([-6.6, y0 - 0.55, 0])

        def aktiv(i):
            return stationen[i][0].animate.set_fill(PETROL_FLAECHE, 1).set_stroke(PETROL, 2.2)

        def block(zeilen, x, oben=y0 - 0.95):
            g = VGroup(*zeilen).arrange(DOWN, aligned_edge=LEFT, buff=0.12)
            g.move_to([x, 0, 0]).align_to([0, oben, 0], UP)
            return g

        # 01 Abrufen
        b1 = block([T("je Quelle:", 16, SANS, LEISE),
                    M("WFS-Abfrage", 15), M("XLSX-Datei", 15), M("INKAR-ZIP", 15)], xs[0])
        self.play(FadeIn(marke), marke.animate.move_to([xs[0], y0 - 0.55, 0]), aktiv(0), run_time=0.9)
        self.play(FadeIn(b1, shift=DOWN * 0.1), marke.animate.shift(UP * 0.0), run_time=0.6)
        self.wait(0.6)

        # 02 Prüfen
        def haken():
            return T("✓", 16, SANS, PETROL, weight="BOLD")
        z = [T("Quellen-Wächter", 18, SCHMAL, PETROL, weight="SEMIBOLD")]
        for s in ("konfigurierte Felder da", "Anzahl größer 0", "Rückgang höchstens", "die Hälfte"):
            z.append(T(s, 15, SANS, TUSCHE))
        b2 = block(z, xs[1])
        ticks = VGroup(*[haken().next_to(b2[i], LEFT, buff=0.12) for i in (1, 2, 3)])
        self.play(marke.animate.move_to([xs[1], y0 - 0.55, 0]), aktiv(1), run_time=0.8)
        self.play(FadeIn(b2, shift=DOWN * 0.1), run_time=0.5)
        self.play(LaggedStart(*[FadeIn(t, scale=1.4) for t in ticks], lag_ratio=0.3), run_time=0.9)

        # 03 Vergleichen
        z3 = [T("fachlicher Schlüssel", 18, SCHMAL, PETROL, weight="SEMIBOLD"),
              M("nationalco", 15),
              T("gegen pipeline_meta.bestand", 14, SANS, LEISE)]
        b3 = block(z3, xs[2])
        self.play(marke.animate.move_to([xs[2], y0 - 0.55, 0]), aktiv(2), run_time=0.8)
        self.play(FadeIn(b3, shift=DOWN * 0.1), run_time=0.5)
        # vier Fächer mit den echten Zählern von gemeinden_lgb
        faecher = ["neu", "geändert", "gelöscht", "unverändert"]
        werte_l1 = [B["gem_neu_l1"], 0, 0, 0]
        werte_l2 = [*B["gem_l2_rest"], B["gem_unv_l2"]]
        tab = VGroup()
        for i, f in enumerate(faecher):
            kopf = T(f, 14, SANS, LEISE)
            wert = M(str(werte_l1[i]), 22, PETROL if werte_l1[i] else TUSCHE)
            tab.add(VGroup(kopf, wert).arrange(DOWN, buff=0.08))
        tab.arrange(RIGHT, buff=0.32).move_to([xs[2] - 0.6, -1.75, 0])
        # Köpfe auf eine Grundlinie, Zahlen auf eine Mittellinie (Umlaute verschieben sonst die Mitte)
        for g in tab:
            g[0].align_to(tab[0][0], DOWN)
            g[1].set_y(tab[0][1].get_y())
        rahmen = SurroundingRectangle(tab, buff=0.16, corner_radius=0.04).set_stroke(TUSCHE, 1.0)
        etikett = T("Erstlauf 07.11.2026, MOSIDI-Compose", 12, SANS, LEISE).next_to(rahmen, UP, buff=0.08).align_to(rahmen, LEFT)
        self.play(Create(rahmen), FadeIn(tab), FadeIn(etikett), run_time=0.8)
        self.wait(0.6)
        tab2 = VGroup()
        for i, f in enumerate(faecher):
            kopf = T(f, 14, SANS, LEISE)
            wert = M(str(werte_l2[i]), 22, PETROL if werte_l2[i] else TUSCHE)
            tab2.add(VGroup(kopf, wert).arrange(DOWN, buff=0.08))
        for i in range(4):
            tab2[i][1].move_to(tab[i][1])
        etikett2 = T("Folgelauf direkt danach", 12, SANS, LEISE).move_to(etikett).align_to(etikett, LEFT)
        self.play(*[Transform(tab[i][1], tab2[i][1]) for i in range(4)], Transform(etikett, etikett2), run_time=0.8)
        self.wait(0.6)

        # 04 Abgleichen: eine Transaktion je Quelle
        self.play(marke.animate.move_to([xs[3], y0 - 0.55, 0]), aktiv(3), run_time=0.8)
        tx_z = ["BEGIN", "  einfügen", "  ändern", "  löschen*", "COMMIT"]
        tx = VGroup(M(tx_z[0], 15, PETROL),
                    M(tx_z[1], 14), M(tx_z[2], 14), M(tx_z[3], 14, LEISE),
                    M(tx_z[4], 15, PETROL)).arrange(DOWN, aligned_edge=LEFT, buff=0.1)
        einruecken(tx, tx_z, 14)
        tx.move_to([xs[3], 0, 0]).align_to([0, y0 - 0.95, 0], UP)
        klammer = VGroup(Line(tx.get_corner(UL) + LEFT * 0.15, tx.get_corner(DL) + LEFT * 0.15),
                         Line(tx.get_corner(UL) + LEFT * 0.15, tx.get_corner(UL) + LEFT * 0.02),
                         Line(tx.get_corner(DL) + LEFT * 0.15, tx.get_corner(DL) + LEFT * 0.02)).set_stroke(PETROL, 2)
        tx_t = T("eine Transaktion je Quelle", 15, SANS, TUSCHE, weight="MEDIUM").next_to(tx, DOWN, buff=0.22)
        self.play(Create(klammer), AddTextLetterByLetter(tx, time_per_char=0.02), run_time=1.0)
        fuss = VGroup(T("* nur nach vollständigem Abruf,", 11, SANS, LEISE),
                      T("nie bei Raumdaten mit loeschen: false", 11, SANS, LEISE)).arrange(DOWN, aligned_edge=LEFT, buff=0.04)
        fuss.next_to(tx_t, DOWN, buff=0.15)
        self.play(FadeIn(tx_t, shift=UP * 0.05), FadeIn(fuss), run_time=0.5)
        self.wait(1.8)

    # 3 ----------------------------------------------------------------------
    def blatt3(self):
        self.raeumen()
        self.blattwechsel(3, "Was den Bestand schützt")
        ueb = self.ueberschrift("03", "Was den Bestand schützt")
        self.play(FadeIn(ueb), run_time=0.5)

        def karte_feld(titel, zeilen, piktogramm, pos):
            rahmen = Rectangle(width=6.35, height=1.75).set_stroke(TUSCHE, 1.2).set_fill(PAPIER, 1).move_to(pos)
            piktogramm.move_to(rahmen.get_left() + RIGHT * 0.75)
            t = T(titel, 22, SCHMAL, TUSCHE, weight="SEMIBOLD")
            zz = VGroup(*[T(z, 13.5, SANS, TUSCHE) for z in zeilen]).arrange(DOWN, aligned_edge=LEFT, buff=0.06)
            txt = VGroup(t, zz).arrange(DOWN, aligned_edge=LEFT, buff=0.1)
            txt.scale_to_fit_width(min(txt.width, rahmen.width - 1.8))
            txt.next_to(rahmen.get_left(), RIGHT, buff=1.5)
            return VGroup(rahmen, piktogramm, txt)

        # Piktogramme in Tusche
        schloss = VGroup(Rectangle(width=0.55, height=0.42).set_stroke(PETROL, 2).set_fill(PETROL_FLAECHE, 1),
                         Arc(radius=0.18, start_angle=0, angle=PI).set_stroke(PETROL, 2))
        schloss[1].next_to(schloss[0], UP, buff=0)
        balken = VGroup(Rectangle(width=0.22, height=0.8).set_stroke(TUSCHE, 1.2).set_fill(PETROL_FLAECHE, 1),
                        Rectangle(width=0.22, height=0.28).set_stroke(ZIEGEL, 1.4)).arrange(RIGHT, buff=0.15, aligned_edge=DOWN)
        halb = DashedLine(balken.get_corner(DL) + UP * 0.4 + LEFT * 0.1, balken.get_corner(DR) + UP * 0.4 + RIGHT * 0.1,
                          dash_length=0.05).set_stroke(TUSCHE, 1)
        balken = VGroup(balken, halb)
        # eine echte Gemeinde (die mit den meisten Stützpunkten im vereinfachten Datensatz) als Raumdatum
        gem = GEO["gemeinden_lgb"]
        idx = max(range(len(gem)), key=lambda i: sum(len(r) for r in gem[i]))
        GEO["_eine"] = [gem[idx]]
        raum = karte("_eine", 0.85, PETROL, 1.4, fuellung=PETROL_FLAECHE)
        zeilen = VGroup(*[Line(LEFT * 0.35, RIGHT * 0.35).set_stroke(TUSCHE if i != 3 else ZIEGEL, 2.2 if i != 3 else 3)
                          for i in range(5)]).arrange(DOWN, buff=0.12)

        k1 = karte_feld("Löschsperre", ["Abruf unvollständig (Objekte ohne ID oder Geometrie,",
                                        "weniger als gemeldet): es wird nichts gelöscht."],
                        schloss, [-3.3, 0.85, 0])
        k2 = karte_feld("Rückgang-Schutz", ["0 Objekte oder mehr als die Hälfte weniger als bisher,",
                                             "oder konfigurierte Felder fehlen: der alte Stand bleibt."],
                        balken, [3.3, 0.85, 0])
        k3 = karte_feld("Raumdaten bleiben", ["Gebäude, Gemeinden, Kreise (loeschen: false):",
                                               "entfallene Objekte bleiben, der Bericht nennt sie."],
                        raum, [-3.3, -1.1, 0])
        k4 = karte_feld("Eine Quelle fällt aus", ["Nur ihre Transaktion wird zurückgerollt, ihr alter Stand bleibt,",
                                                   "die nächste Quelle läuft. Dazu ein Meldungsentwurf",
                                                   "an den Anbieter."],
                        zeilen, [3.3, -1.1, 0])
        lgb = T("Gemeindefläche: © GeoBasis-DE/LGB, dl-de/by-2-0", 10, SANS, LEISE).next_to(k3[0], DOWN, buff=0.06).align_to(k3[0], LEFT)
        schem3 = T("Piktogramme schematisch", 10, SANS, LEISE).next_to(k4[0], DOWN, buff=0.06).align_to(k4[0], RIGHT)
        for k in (k1, k2, k3, k4):
            self.play(Create(k[0]), FadeIn(k[1]), FadeIn(k[2], shift=RIGHT * 0.08),
                      *([FadeIn(lgb)] if k is k3 else []), *([FadeIn(schem3)] if k is k1 else []), run_time=0.7)
            self.wait(1.1)
        self.wait(0.6)

        # Beleg zum Ausfall: Fernschreiber-Auszug aus dem Prototyp-Lauf vom 30.10.2026
        self.play(FadeOut(VGroup(k1, k2, k3, lgb, schem3)), k4.animate.move_to([0, 1.25, 0]).scale(0.92), run_time=0.8)
        roh = B["fehler_txt"]
        auszug = [roh[0]]
        for z in roh[1:]:
            if z.startswith(("      Hinweis", "      Warnung")):
                continue
            if "FEHLER" in z:
                z = z[: z.index("(host='wfs.example.invalid', port=443)") + len("(host='wfs.example.invalid', port=443)")] + " …"
            auszug.append(z)
        streifen = VGroup(*[M(z, 13, ZIEGEL if ("FEHLER" in z or "Meldungsentwurf" in z) else TUSCHE)
                            for z in auszug]).arrange(DOWN, aligned_edge=LEFT, buff=0.09)
        einruecken(streifen, auszug, 13)
        streifen.scale_to_fit_width(min(streifen.width, 12.2)).move_to([0, -1.25, 0])
        papier = Rectangle(width=streifen.width + 0.5, height=streifen.height + 0.4).set_stroke(TUSCHE, 1.0).set_fill("#f5f1e6", 1)
        papier.move_to(streifen)
        lochrand = VGroup(*[Circle(radius=0.035).set_stroke(RASTER_GROB, 1).move_to([x, papier.get_top()[1] - 0.1, 0])
                            for x in np.arange(papier.get_left()[0] + 0.15, papier.get_right()[0] - 0.1, 0.25)])
        lochrand2 = lochrand.copy().shift(DOWN * (papier.height - 0.2))
        etikett = T("Prototyp, Lauf vom 30.10.2026 mit absichtlich unerreichbarer Quelle (Bericht, Auszug)", 12, SANS, LEISE)
        etikett.next_to(papier, UP, buff=0.08).align_to(papier, LEFT)
        self.play(FadeIn(papier), FadeIn(lochrand), FadeIn(lochrand2), FadeIn(etikett), run_time=0.5)
        for zeile in streifen:
            self.play(AddTextLetterByLetter(zeile, time_per_char=0.006), run_time=max(0.25, min(0.6, len(zeile) * 0.006)))
        self.wait(2.4)

    # 4 ----------------------------------------------------------------------
    def blatt4(self):
        self.raeumen()
        self.blattwechsel(4, "Belege aus echten Läufen")
        ueb = self.ueberschrift("04", "Belege aus echten Läufen")
        self.play(FadeIn(ueb), run_time=0.5)

        trenner = VGroup(Line([-2.35, 1.9, 0], [-2.35, -2.3, 0]), Line([2.35, 1.9, 0], [2.35, -2.3, 0])).set_stroke(RASTER_GROB, 1.4)
        self.play(Create(trenner), run_time=0.4)

        # A: 413 / 413
        a_zahl = VGroup(T(str(B["gem_neu_l1"]), 84, SCHMAL, PETROL, weight="SEMIBOLD"),
                        T("/", 60, SCHMAL, LEISE, weight="LIGHT"),
                        T(str(B["gem_unv_l2"]), 84, SCHMAL, TUSCHE, weight="SEMIBOLD")).arrange(RIGHT, buff=0.2, aligned_edge=DOWN)
        a_zahl.move_to([-4.7, 0.75, 0])
        a_t = VGroup(T("Gemeinden der LGB", 20, SCHMAL, TUSCHE, weight="SEMIBOLD"),
                     T("Erstlauf: neu 413", 15, SANS, PETROL),
                     T("Folgelauf: unverändert 413", 15, SANS, TUSCHE),
                     T("Lauf im Compose-Setup von MOSIDI,", 12, SANS, LEISE),
                     T("Prüfkonfiguration Brandenburg, 07.11.2026", 12, SANS, LEISE)).arrange(DOWN, aligned_edge=LEFT, buff=0.08)
        a_t.next_to(a_zahl, DOWN, buff=0.35).align_to(a_zahl, LEFT)
        self.play(FadeIn(a_zahl[0], shift=UP * 0.2), run_time=0.6)
        self.play(FadeIn(a_zahl[1]), FadeIn(a_zahl[2], shift=UP * 0.2), FadeIn(a_t), run_time=0.8)
        self.wait(0.5)

        # B: 33.547.606 Werte, Wertabgleich 0/0/0
        # nur der belegte Endwert, kein Hochzählen über Zwischenwerte, die in keiner Datei stehen
        zahl = T(de(B["inkar_werte"]), 66, SCHMAL, PETROL, weight="SEMIBOLD").move_to([0, 0.95, 0])
        b_t = VGroup(T("INKAR-Werte im Vollumfang", 20, SCHMAL, TUSCHE, weight="SEMIBOLD"),
                     T(f"bundesweit, {de(B['voll_gemeinden'])} Gemeinden, Lieferkonfiguration", 14, SANS, TUSCHE)
                     ).arrange(DOWN, buff=0.08).next_to([0, 0.95, 0], DOWN, buff=0.55)
        self.play(FadeIn(zahl, scale=0.92), FadeIn(b_t), run_time=1.2)
        self.wait(0.8)
        nullen = VGroup()
        for name, w in (("fehlend", B["fehlend"]), ("überzählig", B["ueberzaehlig"]), ("abweichend", B["abweichend"])):
            nullen.add(VGroup(T(str(w), 48, SCHMAL, TUSCHE, weight="SEMIBOLD"), T(name, 14, SANS, LEISE)).arrange(DOWN, buff=0.05))
        # gleiche Abstände der Mitten, Beschriftungen an einer Oberkante (alle drei haben Oberlängen)
        oben_n = b_t.get_bottom()[1] - 0.4
        for x, n in zip((-1.45, 0.0, 1.45), nullen, strict=True):
            n[0].move_to([x, 0, 0]).align_to([0, oben_n, 0], UP)
            n[1].move_to([x, 0, 0]).align_to([0, oben_n - n[0].height - 0.08, 0], UP)
        n_t = VGroup(T("Wertabgleich jeder Zeile gegen die Datenbank", 12, SANS, LEISE),
                     T(f"Lauf {B['voll_lauf']}, Prüfstand 07.11.2026", 12, SANS, LEISE),
                     T("INKAR: © BBSR Bonn 2025, dl-de/by-2-0", 11, SANS, LEISE)).arrange(DOWN, buff=0.04).next_to(nullen, DOWN, buff=0.2)
        self.play(LaggedStart(*[FadeIn(n, shift=UP * 0.15) for n in nullen], lag_ratio=0.25), FadeIn(n_t), run_time=1.1)
        self.wait(0.5)

        # C: 70 von 70 auf PostgreSQL 16.15 und 18.6
        spalten = VGroup()
        for ver, n in zip(B["pg"], B["dbtests"], strict=True):
            felder = VGroup(*[Square(0.17).set_stroke(TUSCHE, 0.8) for _ in range(70)]).arrange_in_grid(7, 10, buff=0.04)
            kopf = T(f"PostgreSQL {ver}", 16, MONO, TUSCHE)
            zahl_t = T(f"{n} von 70", 22, SCHMAL, PETROL, weight="SEMIBOLD")
            spalten.add(VGroup(kopf, felder, zahl_t).arrange(DOWN, buff=0.14))
        spalten.arrange(DOWN, buff=0.28).move_to([4.7, 0.05, 0])
        c_t = VGroup(T("Datenbanktests mit den MOSIDI-Tabellen", 12, SANS, LEISE),
                     T(f"dazu {B['pruefen']} Tests in pruefen.sh", 12, SANS, LEISE)).arrange(DOWN, buff=0.04)
        c_t.next_to(spalten, DOWN, buff=0.15)
        self.play(FadeIn(spalten[0][0]), FadeIn(spalten[1][0]), *[Create(f) for s in spalten for f in s[1]], run_time=0.6)
        fuellen = []
        for s in spalten:
            fuellen.append(LaggedStart(*[f.animate.set_fill(PETROL, 1).set_stroke(PETROL, 0.8) for f in s[1]], lag_ratio=0.03))
        self.play(*fuellen, run_time=1.6)
        self.play(FadeIn(spalten[0][2]), FadeIn(spalten[1][2]), FadeIn(c_t), run_time=0.5)
        self.wait(2.6)

    # 5 ----------------------------------------------------------------------
    def blatt5(self):
        self.raeumen()
        self.blattwechsel(5, "Bericht und Protokoll")
        ueb = self.ueberschrift("05", "Bericht je Lauf, Protokoll in der Datenbank")
        self.play(FadeIn(ueb), run_time=0.5)

        roh = B["l1_txt"]
        auszug = [z for z in roh if not z.startswith("      ")]
        streifen = VGroup(*[M(z, 13, TUSCHE) for z in auszug]).arrange(DOWN, aligned_edge=LEFT, buff=0.09)
        einruecken(streifen, auszug, 13)
        streifen[0].set_color(PETROL)
        streifen.scale_to_fit_width(min(streifen.width, 8.0)).move_to([-2.35, 0.05, 0])
        papier = Rectangle(width=streifen.width + 0.5, height=streifen.height + 0.5).set_stroke(TUSCHE, 1.0).set_fill("#f5f1e6", 1)
        papier.move_to(streifen)
        etikett = T("Laufbericht 20261107T043632Z, Erstlauf im Compose-Setup von MOSIDI, Prüfkonfiguration Brandenburg"
                    " (ohne Hinweiszeilen)", 12, SANS, LEISE)
        etikett.next_to(papier, UP, buff=0.08).align_to(papier, LEFT)
        self.play(FadeIn(papier), FadeIn(etikett), run_time=0.4)
        for zeile in streifen:
            self.play(AddTextLetterByLetter(zeile, time_per_char=0.005), run_time=max(0.22, min(0.45, len(zeile) * 0.005)))

        meta = VGroup(T("pipeline_meta", 22, MONO, PETROL),
                      *[M("  ." + t, 15) for t in ("lauf", "quellenlauf", "aenderung", "bestand", "quellenstand", "katalog_offen")]
                      ).arrange(DOWN, aligned_edge=LEFT, buff=0.12)
        meta_t = VGroup(T("eigenes Schema: Steuerung und", 13, SANS, LEISE),
                        T("Protokoll, nie Fachdaten", 13, SANS, LEISE)).arrange(DOWN, aligned_edge=LEFT, buff=0.04)
        VGroup(meta, meta_t).arrange(DOWN, aligned_edge=LEFT, buff=0.25).move_to([4.75, 0.35, 0])
        self.play(LaggedStart(*[FadeIn(m, shift=LEFT * 0.1) for m in meta], lag_ratio=0.12), FadeIn(meta_t), run_time=1.3)
        self.wait(1.4)

        # Schluss
        link = T("github.com/andremadstop/geodaten-import-pipeline", 24, MONO, PETROL)
        name = T("André Stiebitz · Stiebitz Souverain Systems UG (haftungsbeschränkt)", 15, SANS, LEISE)
        schluss = VGroup(link, name).arrange(DOWN, buff=0.15).move_to([0, -2.35, 0])
        linie = Line(schluss.get_corner(UL) + UP * 0.15, schluss.get_corner(UR) + UP * 0.15).set_stroke(TUSCHE, 1)
        self.play(Create(linie), FadeIn(link, shift=UP * 0.08), run_time=0.8)
        self.play(FadeIn(name), run_time=0.5)
        self.wait(3.5)


class Standbild(Lauf):
    """Endzustand von Blatt 4 (Belege) verlustfrei als PNG: manim -s ... film.py Standbild"""

    def construct(self):
        self.raster, self.rand = self.zeichenblatt()
        self.sf = self.schriftfeld(4, "Belege aus echten Läufen")
        self.add(self.raster, self.rand, self.sf)
        self.blatt4()


class StandbildTitel(Lauf):
    """Titelbild (Blatt 1 nach dem Zeichnen der Karte): manim -s ... film.py StandbildTitel"""

    def construct(self):
        self.raster, self.rand = self.zeichenblatt()
        self.sf = self.schriftfeld(1, "Quellen und Ziel")
        self.add(self.raster, self.rand, self.sf)
        self.nur_titel = True
        self.blatt1()
