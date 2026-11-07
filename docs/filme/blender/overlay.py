# 2D-Overlay (pycairo) ueber die Blender-Frames: Planrahmen, Schriftfeld, Zaehler, Linien, Abspann.
# Aufruf: python3 overlay.py --prep <prep> --ein <frames> --aus <komp> [--frames 0-1127] [--jobs 1]
import os, sys, json, math, random, argparse
from multiprocessing import Pool
import cairo

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HIER)
import zeitplan as Z

FPS = Z.FPS
W, H = Z.W, Z.H

def hexrgb(h, a=1.0):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)) + (a,)

TUSCHE = "#1c2326"
PETROL = "#2a5d6b"
ROT = "#ad2a24"
PAPIER = "#ebe6db"
GRAU = "#6b7175"
KLASSEN = ["#d5ddd7", "#aac3c1", "#78a1a6", "#4a7b85", "#2a5d6b"]

F_LIGHT = "Fira Sans Condensed Light"
F_XL = "Fira Sans Condensed ExtraLight"
F_BOOK = "Fira Sans Condensed Book"
F_MED = "Fira Sans Condensed Medium"
F_SEMI = "Fira Sans Condensed SemiBold"
F_MONO = "Noto Sans Mono"

def _prep_ordner():
    """--prep aus der Befehlszeile (vor argparse gebraucht, weil die Daten beim Import geladen werden)."""
    a = sys.argv
    if "--prep" in a:
        return a[a.index("--prep") + 1]
    return os.environ.get("FILM_PREP", "berichte/film-blender/prep")


P = _prep_ordner()
GEM = json.load(open(os.path.join(P, "gemeinden.json")))
KR = json.load(open(os.path.join(P, "kreise.json")))
META = json.load(open(os.path.join(P, "meta.json")))
NG = len(GEM)

# Zahlen aus den Berichten (Quelle siehe README im Ordner)
QUELLEN = [  # Name, neu (Lauf 1), Laufzeit s (Lauf 1), unveraendert (Lauf 2)
    ("alkis_gebaeude_thb", 882, "4,38", 882),
    ("gemeinden_lgb", 413, "5,13", 413),
    ("kreise_lgb", 18, "1,99", 18),
    ("bevoelkerung_gemeinden", 413, "1,47", 413),
    ("flaeche_gemeinden", 413, "4,60", 413),
    ("inkar_gemeinden", 62929, "127,78", 62929),
]

# Kreise: Gesamtlaenge fuer Zeichnen
for k in KR:
    k["len"] = sum(math.dist(r[i], r[(i + 1) % len(r)]) for r in k["ringe"] for i in range(len(r)))

# INKAR-Partikel (schematisch): feste Saat
rnd = random.Random(20261107)
PARTIKEL = []
NP = 1600
for j in range(NP):
    g = GEM[rnd.randrange(NG)]
    t_ab = Z.I0 + 0.15 + (Z.I1 - Z.I0 - 1.1) * (j / NP) + rnd.uniform(-0.05, 0.05)
    PARTIKEL.append((t_ab, g["c"], rnd.uniform(-1, 1), rnd.uniform(0.75, 0.95)))


def de(n):
    return f"{n:,}".replace(",", ".")


def de_dez(x, stellen=2):
    return f"{x:,.{stellen}f}".replace(",", "_").replace(".", ",").replace("_", ".")


# ---------------- Text ----------------
def font(ctx, fam, size):
    ctx.select_font_face(fam, cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
    ctx.set_font_size(size)


def tw(ctx, s, track=0.0):
    w = 0.0
    for ch in s:
        w += ctx.text_extents(ch).x_advance + track
    return w - (track if s else 0)


def text(ctx, s, x, y, fam, size, col, align="l", track=0.0, alpha=1.0, tab=False):
    font(ctx, fam, size)
    ctx.set_source_rgba(*hexrgb(col, alpha))
    dw = ctx.text_extents("0").x_advance
    def adv(ch):
        if tab and ch.isdigit():
            return dw
        return ctx.text_extents(ch).x_advance
    w = sum(adv(c) + track for c in s) - (track if s else 0)
    if align == "r":
        x -= w
    elif align == "c":
        x -= w / 2
    if track == 0 and not tab:
        ctx.move_to(x, y)
        ctx.show_text(s)
        return w
    cx = x
    for ch in s:
        a = adv(ch)
        off = (a - ctx.text_extents(ch).x_advance) / 2 if (tab and ch.isdigit()) else 0
        ctx.move_to(cx + off, y)
        ctx.show_text(ch)
        cx += a + track
    return w


def linie(ctx, x1, y1, x2, y2, col, w=1.0, alpha=1.0):
    ctx.set_source_rgba(*hexrgb(col, alpha))
    ctx.set_line_width(w)
    ctx.move_to(x1, y1)
    ctx.line_to(x2, y2)
    ctx.stroke()


# ---------------- Layout ----------------
RA, RI = 20, 32               # Rahmen aussen/innen
PX = 1404                     # Schriftfeld links
PR = W - RI                   # Schriftfeld rechts
MAPR = PX                     # Kartenbereich rechts


def kapitel(t):
    if t < Z.I0 - 0.2:
        return "01", "Kreise und Gemeinden", "LGB · Amt für Statistik"
    if t < Z.Z0 + 0.6:
        return "02", "INKAR", "abgelegte Datei inkar_2025.zip"
    if t < Z.F0 - 0.2:
        return "03", "Gebäude am Campus der TH Brandenburg", "ALKIS vereinfacht · LGB"
    return "04", "Folgelauf", "derselbe Bestand, noch einmal"


def zaehler_gem(t):
    return sum(1 for g in GEM if t >= Z.G0 + g["i"] / NG * Z.LZ["gemeinden_lgb"])


def zaehler_kreise(t):
    d = Z.LZ["kreise_lgb"] / 18
    return int(Z.clamp((t - Z.K0) / d, 0, 18)) if t >= Z.K0 else 0


def zaehler_inkar(t):
    x = Z.seg(t, Z.I0 + 0.15, Z.I1 - 0.25)
    return int(round(62929 * x))


# Gebaeude-Startzeiten exakt wie in szene.py
GEB = json.load(open(os.path.join(P, "gebaeude.json")))
_d = Z.LZ["alkis_gebaeude_thb"] / 9.0
_pk = {}
for b in GEB:
    _pk.setdefault(b["kachel"], []).append(b)
GEB_T0 = []
for k, liste in _pk.items():
    for m_i, b in enumerate(liste):
        GEB_T0.append(Z.A0 + k * _d + (m_i / len(liste)) * _d * 0.9)
GEB_T0.sort()


def zaehler_geb(t):
    return sum(1 for x in GEB_T0 if x <= t)


def kachel_jetzt(t):
    if t < Z.A0:
        return 1
    return min(9, int((t - Z.A0) / _d) + 1)


def status(t):
    """je Quelle: (zustand, anzeige_neu). zustand: 0 offen, 1 laeuft, 2 fertig"""
    st = {}
    st["kreise_lgb"] = (0 if t < Z.K0 else 1 if t < Z.K1 else 2, zaehler_kreise(t))
    st["gemeinden_lgb"] = (0 if t < Z.G0 else 1 if t < Z.G1 else 2, zaehler_gem(t))
    for q in ("bevoelkerung_gemeinden", "flaeche_gemeinden"):
        st[q] = (0 if t < Z.G0 else 1 if t < Z.G1 else 2, zaehler_gem(t))
    st["inkar_gemeinden"] = (0 if t < Z.I0 else 1 if t < Z.I1 else 2, zaehler_inkar(t))
    st["alkis_gebaeude_thb"] = (0 if t < Z.A0 else 1 if t < Z.A1 else 2, zaehler_geb(t))
    return st


def scan_fortschritt(t):
    """0..1 ueber die 6 Quellen im Folgelauf: Zeile 1 (Gebaeude) mit dem Strahl ueber den Campus,
    Zeilen 2 bis 6 mit dem Strahl ueber das Land. Fertig (1.0) erst bei S1_SCAN."""
    if t < Z.P0:
        return Z.seg(t, Z.F0 + 0.2, Z.F1 - 0.1) / 6.0
    return (1.0 + 5.0 * Z.seg(t, Z.S0_SCAN, Z.S1_SCAN)) / 6.0


def folge_fertig(t):
    """Folgelauf vollstaendig abgeglichen: erst dann Ergebnis, Gesamtlaufzeit und Bericht zeigen."""
    return t >= Z.S1_SCAN


# ---------------- Zeichnen ----------------
def rahmen(ctx, t, proj, S, tilt):
    a_top = 1.0 - Z.clamp(tilt / 4.0)
    ctx.set_source_rgba(*hexrgb(TUSCHE))
    ctx.set_line_width(1.6)
    ctx.rectangle(RA, RA, W - 2 * RA, H - 2 * RA)
    ctx.stroke()
    ctx.set_line_width(0.7)
    ctx.rectangle(RI, RI, W - 2 * RI, H - 2 * RI)
    ctx.stroke()
    # Gitterbeschriftung (nur Draufsicht, exakt aus Kamera)
    if a_top > 0.01:
        mpp = S / W
        schritt = next(s for s in (100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000, 100000) if s / mpp >= 170)
        Tx, Ty, _, _, _ = Z.kamera(t)
        # Bild-x -> Welt-x (lokal) ; Rechtswert = lokal + 332600
        x_l = Tx - (W / 2 - RI) * mpp
        x_r = Tx + (MAPR - W / 2) * mpp
        e0 = math.ceil((x_l + 332600) / schritt) * schritt
        e = e0
        while e <= x_r + 332600:
            px, _ = proj(e - 332600, 0)
            if RI + 40 < px < MAPR - 30:
                linie(ctx, px, RI, px, RI + 9, TUSCHE, 0.8, a_top)
                linie(ctx, px, H - RI, px, H - RI - 9, TUSCHE, 0.8, a_top)
                text(ctx, f"{e:,.0f}".replace(",", " "), px + 4, RI + 19, F_MONO, 10.5, TUSCHE, alpha=0.85 * a_top)
            e += schritt
        y_b = Ty - (H / 2 - RI) * mpp
        y_t = Ty + (H / 2 - RI) * mpp
        n = math.ceil((y_b + 5809900) / schritt) * schritt
        while n <= y_t + 5809900:
            _, py = proj(0, n - 5809900)
            if RI + 50 < py < H - RI - 30:
                linie(ctx, RI, py, RI + 9, py, TUSCHE, 0.8, a_top)
                ctx.save()
                ctx.translate(RI + 19, py - 4)
                ctx.rotate(-math.pi / 2)
                text(ctx, f"{n:,.0f}".replace(",", " "), 0, 0, F_MONO, 10.5, TUSCHE, alpha=0.85 * a_top)
                ctx.restore()
            n += schritt
        # Massstabsleiste + Nordpfeil
        ziel = 160 * mpp
        lang = next(s for s in (50, 100, 200, 250, 500, 1000, 2000, 2500, 5000, 10000, 20000, 25000, 50000, 100000) if s >= ziel * 0.6)
        px_l = lang / mpp
        x0, y0 = 70, H - 70
        ctx.set_source_rgba(*hexrgb(TUSCHE, a_top))
        ctx.rectangle(x0, y0, px_l / 2, 5)
        ctx.fill()
        ctx.set_line_width(0.8)
        ctx.rectangle(x0, y0, px_l, 5)
        ctx.stroke()
        lab = f"{lang // 1000:,} km".replace(",", ".") if lang >= 1000 else f"{lang} m"
        text(ctx, "0", x0, y0 - 7, F_MONO, 10.5, TUSCHE, "c", alpha=a_top)
        text(ctx, lab, x0 + px_l, y0 - 7, F_MONO, 10.5, TUSCHE, "c", alpha=a_top)
        # Nordpfeil
        nx, ny = x0 + px_l + 60, y0 + 4
        ctx.set_source_rgba(*hexrgb(TUSCHE, a_top))
        ctx.move_to(nx, ny - 30); ctx.line_to(nx + 7, ny); ctx.line_to(nx, ny - 7); ctx.close_path(); ctx.fill()
        ctx.set_line_width(0.8)
        ctx.move_to(nx, ny - 30); ctx.line_to(nx - 7, ny); ctx.line_to(nx, ny - 7); ctx.close_path(); ctx.stroke()
        text(ctx, "N", nx, ny - 36, F_SEMI, 12, TUSCHE, "c", alpha=a_top)
        text(ctx, "ETRS89 / UTM 33N · EPSG:25833", x0, y0 + 26, F_BOOK, 11.5, GRAU, alpha=a_top)


def pfad_ring(ctx, proj, r):
    x, y = proj(*r[0])
    ctx.move_to(x, y)
    for p in r[1:]:
        ctx.line_to(*proj(*p))
    ctx.close_path()


def kreise(ctx, t, proj, S):
    a = Z.clamp((S - 25000) / 60000)
    if a <= 0 or t < Z.K0:
        return
    d = Z.LZ["kreise_lgb"] / 18
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    for i, k in enumerate(KR):
        x = Z.clamp((t - (Z.K0 + i * d)) / 0.45)
        if x <= 0:
            continue
        if x >= 1:
            for r in k["ringe"]:
                pfad_ring(ctx, proj, r)
        else:
            rest = k["len"] * Z.ease(x)
            for r in k["ringe"]:
                if rest <= 0:
                    break
                px, py = proj(*r[0])
                ctx.move_to(px, py)
                for j in range(1, len(r) + 1):
                    p0, p1 = r[j - 1], r[j % len(r)]
                    seg = math.dist(p0, p1)
                    if seg >= rest:
                        f = rest / seg
                        ctx.line_to(*proj(p0[0] + (p1[0] - p0[0]) * f, p0[1] + (p1[1] - p0[1]) * f))
                        rest = 0
                        break
                    ctx.line_to(*proj(*p1))
                    rest -= seg
        aktiv = t < Z.K0 + i * d + 0.45
        ctx.set_source_rgba(*hexrgb(ROT if aktiv else TUSCHE, a * (0.95 if aktiv else 0.8)))
        ctx.set_line_width(1.4 if aktiv else 0.9)
        ctx.stroke()


def gemeindegrenzen(ctx, t, proj, S):
    a = Z.clamp((S - 30000) / 80000) * (1 - Z.boden(t) / 0.82)
    if a <= 0 or t < Z.G0:
        return
    ctx.set_line_width(0.45)
    ctx.set_source_rgba(*hexrgb("#f4f1e8", 0.75 * a))
    for g in GEM:
        if t < Z.G0 + g["i"] / NG * Z.LZ["gemeinden_lgb"]:
            continue
        for r in g["ringe"]:
            pfad_ring(ctx, proj, r)
    ctx.stroke()


def inkar(ctx, t, proj, quelle_xy):
    if not (Z.I0 <= t <= Z.I1 + 0.8):
        return
    sx, sy = quelle_xy
    getroffen = {}
    for (t_ab, c, kr, dauer) in PARTIKEL:
        u = (t - t_ab) / dauer
        if u < 0:
            continue
        cx, cy = proj(*c)
        if u >= 1:
            if u < 1 + 0.5 / dauer:
                getroffen[(round(cx), round(cy))] = max(getroffen.get((round(cx), round(cy)), 0), 1 - (u - 1) * dauer / 0.5)
            continue
        # quadratische Bezierkurve, Kontrollpunkt oberhalb
        mx, my = (sx + cx) / 2 + kr * 120, min(sy, cy) - 160
        e = Z.ease(u) if False else u * u * (3 - 2 * u)
        x = (1 - e) ** 2 * sx + 2 * (1 - e) * e * mx + e * e * cx
        y = (1 - e) ** 2 * sy + 2 * (1 - e) * e * my + e * e * cy
        ctx.set_source_rgba(*hexrgb(PETROL, 0.55 + 0.4 * u))
        ctx.arc(x, y, 1.5, 0, 2 * math.pi)
        ctx.fill()
    ctx.set_line_width(0.8)
    for (cx, cy), a in getroffen.items():
        ctx.set_source_rgba(*hexrgb(TUSCHE, 0.6 * a))
        ctx.arc(cx, cy, 2 + (1 - a) * 7, 0, 2 * math.pi)
        ctx.stroke()


def campus_marke(ctx, t, proj):
    """BBOX des Campus: erst als Marke ueber dem Land, auf der Fahrt hinunter als projizierter Umriss,
    bis die ersten Kacheln stehen (sonst bleibt die Karte zwischen Gemeinden und Gebaeuden leer)."""
    a = Z.seg(t, Z.I1 - 0.4, Z.I1 + 0.2) * (1 - Z.seg(t, Z.A0 + 0.2, Z.A0 + 0.9))
    if a <= 0:
        return
    k = META["kacheln"]
    xa, ya, xb, yb = k[0][0], k[0][1], k[8][2], k[8][3]
    ecken = [proj(xa, ya), proj(xb, ya), proj(xb, yb), proj(xa, yb)]
    xs = [p[0] for p in ecken]
    ys = [p[1] for p in ecken]
    ausdehnung = max(max(xs) - min(xs), max(ys) - min(ys))
    ctx.set_source_rgba(*hexrgb(ROT, a))
    ctx.set_line_width(1.3)
    if ausdehnung < 30:
        cx, cy = sum(xs) / 4, sum(ys) / 4
        r = max(9, ausdehnung / 2 + 6)
        ctx.rectangle(cx - r, cy - r, 2 * r, 2 * r)
        ctx.stroke()
        ax, ay = cx + r, cy - r
    else:
        ctx.move_to(*ecken[0])
        for p in ecken[1:]:
            ctx.line_to(*p)
        ctx.close_path()
        ctx.stroke()
        ax, ay = max(ecken, key=lambda p: p[0] - p[1])  # Ecke oben rechts im Bild
    b = a * (1 - Z.seg(t, Z.Z0 + 1.6, Z.Z0 + 2.4))  # Beschriftung nur ueber dem Land
    b2 = a * Z.seg(t, Z.Z0 + 2.4, Z.Z0 + 3.0)       # danach kurze Beschriftung am Umriss
    if b > 0:
        ctx.set_source_rgba(*hexrgb(PAPIER, 0.85 * b))  # Hinterlegung, lesbar auch ueber dunklen Flaechen
        ctx.rectangle(ax + 40, ay - 62, 268, 44)
        ctx.fill()
        linie(ctx, ax, ay, ax + 40, ay - 40, ROT, 1.0, b)
        text(ctx, "Campus TH Brandenburg", ax + 46, ay - 44, F_MED, 15, TUSCHE, alpha=b)
        text(ctx, "BBOX 332000, 5809400, 333200, 5810400", ax + 46, ay - 26, F_MONO, 10.5, GRAU, alpha=b)
    if b2 > 0:
        lx = min(max(ax + 12, RI + 30), MAPR - 330)
        ly = min(max(ay - 14, RI + 140), H - RI - 60)
        text(ctx, "BBOX 332000, 5809400, 333200, 5810400", lx, ly, F_MONO, 12, TUSCHE, alpha=b2)


def scanlinie(ctx, t, proj):
    sx, sw = Z.scan_x(t)
    if sx > 1e8:
        return
    lo, hi = (-1400, 1400) if sw < 1000 else (-160000, 160000)
    x1, y1 = proj(sx, lo)
    x2, y2 = proj(sx, hi)
    linie(ctx, x1, y1, x2, y2, PETROL, 1.6, 0.95)
    # Beschriftung am Strahl, im Kartenbereich festgehalten
    lx = min(max((x1 + x2) / 2, 340), MAPR - 260)
    text(ctx, "Abgleich über den fachlichen Schlüssel", lx + 8, 96, F_MED, 14, PETROL)


def schriftfeld(ctx, t):
    ctx.set_source_rgba(*hexrgb(PAPIER, 0.96))
    ctx.rectangle(PX, RI, PR - PX, H - 2 * RI)
    ctx.fill()
    linie(ctx, PX, RI, PX, H - RI, TUSCHE, 0.9)
    x = PX + 26
    xr = PR - 24
    text(ctx, "GEODATEN-IMPORT-PIPELINE", x, 70, F_SEMI, 13, PETROL, track=2.2)
    text(ctx, "Der Campus wächst aus den Daten", x, 104, F_LIGHT, 30, TUSCHE)
    linie(ctx, PX, 126, PR, 126, TUSCHE, 0.6)
    folge = t >= Z.F0 - 0.2
    if not folge:
        text(ctx, "Importlauf 20261107T043632Z", x, 154, F_MONO, 13.5, TUSCHE)
        text(ctx, "MOSIDI-Compose · 07.11.2026 · erster Lauf", x, 176, F_BOOK, 13.5, GRAU)
    else:
        text(ctx, "Importlauf 20261107T043901Z", x, 154, F_MONO, 13.5, TUSCHE)
        text(ctx, "MOSIDI-Compose · 07.11.2026 · Folgelauf", x, 176, F_BOOK, 13.5, GRAU)
    # Tabelle
    y = 214
    text(ctx, "QUELLE", x, y, F_SEMI, 10.5, GRAU, track=1.5)
    text(ctx, "UNVERÄNDERT" if folge else "NEU", xr - 92, y, F_SEMI, 10.5, GRAU, "r", track=1.5)
    text(ctx, "NEU" if folge else "LAUFZEIT", xr, y, F_SEMI, 10.5, GRAU, "r", track=1.5)
    linie(ctx, x, y + 9, xr, y + 9, TUSCHE, 0.5, 0.5)
    st = status(t)
    sf = scan_fortschritt(t)
    for i, (q, neu, lz, unv) in enumerate(QUELLEN):
        yy = y + 36 + i * 30
        z, n = st[q]
        if folge:
            fertig = sf >= (i + 1) / 6.0
            z = 2 if fertig else (1 if sf > i / 6.0 else 0)
            n = unv if fertig else 0
        # Marke
        if z == 0:
            ctx.set_source_rgba(*hexrgb(TUSCHE, 0.5)); ctx.set_line_width(0.8)
            ctx.rectangle(x, yy - 9, 8, 8); ctx.stroke()
        else:
            ctx.set_source_rgba(*hexrgb((PETROL if folge else ROT) if z == 1 else TUSCHE))
            ctx.rectangle(x, yy - 9, 8, 8); ctx.fill()
        text(ctx, q, x + 18, yy, F_MONO, 13.5, TUSCHE, alpha=1.0 if z else 0.45)
        if z and not (folge and z == 1):  # im Folgelauf erst nach Abschluss der Zeile
            text(ctx, de(n), xr - 92, yy, F_MONO, 13.5, (PETROL if folge else ROT) if z == 1 else TUSCHE, "r")
        if z == 2:
            lz_txt = {"alkis_gebaeude_thb": "4,38", "gemeinden_lgb": "5,13", "kreise_lgb": "1,99",
                      "bevoelkerung_gemeinden": "1,47", "flaeche_gemeinden": "4,60", "inkar_gemeinden": "127,78"}
            if folge:
                lz_txt = {}
            if lz_txt:
                text(ctx, lz_txt[q] + " s", xr, yy, F_MONO, 13.5, TUSCHE, "r")
            else:
                text(ctx, "0", xr, yy, F_MONO, 13.5, PETROL, "r")
    yb = y + 36 + 6 * 30 - 6
    linie(ctx, x, yb, xr, yb, TUSCHE, 0.5, 0.5)
    if folge:
        if folge_fertig(t):
            text(ctx, "Folgelauf gesamt 141,8 s (Bericht 20261107T043901Z)", x, yb + 20, F_BOOK, 12, GRAU,
                 alpha=Z.seg(t, Z.S1_SCAN, Z.S1_SCAN + 0.5))
    else:
        text(ctx, "Zahlen und Laufzeiten aus dem Bericht 20261107T043632Z;", x, yb + 20, F_BOOK, 12, GRAU)
        text(ctx, "Reihenfolge im Film nach Bild, nicht nach Lauf.", x, yb + 36, F_BOOK, 12, GRAU)
    linie(ctx, PX, 488, PR, 488, TUSCHE, 0.6)
    grosszahl(ctx, t, x, xr)
    legende(ctx, t, x, xr)
    # Nachweis
    linie(ctx, PX, H - RI - 74, PR, H - RI - 74, TUSCHE, 0.6)
    text(ctx, "Geobasisdaten © GeoBasis-DE/LGB, dl-de/by-2-0", x, H - RI - 50, F_BOOK, 12, TUSCHE)
    text(ctx, "Statistik: Amt für Statistik Berlin-Brandenburg, CC BY 3.0 DE", x, H - RI - 32, F_BOOK, 12, TUSCHE)
    text(ctx, "INKAR: © BBSR Bonn 2025, dl-de/by-2-0", x, H - RI - 14, F_BOOK, 12, TUSCHE)


def grosszahl(ctx, t, x, xr):
    y = 520
    if t < Z.K0:
        return
    if t < Z.G0 - 0.15:
        lab, n, sub, col = "kreise_lgb · neu", zaehler_kreise(t), "Echtzeit: 1,99 s wie im Lauf, Takt schematisch", ROT
    elif t < Z.I0 - 0.2:
        lab, n, sub, col = "gemeinden_lgb · neu", zaehler_gem(t), "Echtzeit: 5,13 s wie im Lauf, Takt schematisch", ROT
    elif t < Z.Z0 + 0.6:
        lab, n, sub, col = "inkar_gemeinden · neu", zaehler_inkar(t), "Zeitraffer: 127,78 s in 4 s", ROT
    elif t < Z.A0 - 0.3:
        lab, n, sub, col = "alkis_gebaeude_thb", None, "9 Kacheln (kachel_m 400), je eine Abfrage", TUSCHE
    elif t < Z.F0 - 0.2:
        k = kachel_jetzt(t)
        lab, n, sub, col = "alkis_gebaeude_thb · neu", zaehler_geb(t), f"Kachel {k} von 9 · Echtzeit 4,38 s, Takt schematisch", ROT
    else:
        if not folge_fertig(t):
            k = min(5, max(0, math.ceil(scan_fortschritt(t) * 6 - 1e-9) - 1))  # Zeile, die gerade laeuft oder zuletzt fertig wurde
            text(ctx, "FOLGELAUF · ABGLEICH LÄUFT", x, y + 4, F_SEMI, 11, GRAU, track=1.5)
            text(ctx, QUELLEN[k][0], x, y + 66, F_MONO, 30, PETROL)
            text(ctx, f"Quelle {k + 1} von 6 · Abgleich über den fachlichen Schlüssel", x, y + 128, F_BOOK, 13.5, TUSCHE)
            return
        text(ctx, "FOLGELAUF · ERGEBNIS", x, y + 4, F_SEMI, 11, GRAU, track=1.5)
        a = Z.seg(t, Z.S1_SCAN, Z.S1_SCAN + 0.5)
        for j, (zahl, wort) in enumerate((("0", "neu"), ("0", "geändert"), ("0", "gelöscht"))):
            xx = x + j * 136
            text(ctx, zahl, xx, y + 102, F_XL, 92, PETROL, alpha=a, tab=True)
            text(ctx, wort, xx + 4, y + 128, F_MED, 16, TUSCHE, alpha=a)
        return
    text(ctx, lab.upper(), x, y + 4, F_SEMI, 11, GRAU, track=1.5)
    if n is not None:
        text(ctx, de(n), x - 4, y + 102, F_XL, 96, col if n < 10 ** 9 else TUSCHE, tab=True)
    text(ctx, sub, x, y + 128, F_BOOK, 13.5, TUSCHE)


def swatch(ctx, x, y, col, rand=None, w=22, h=12):
    ctx.set_source_rgba(*hexrgb(col))
    ctx.rectangle(x, y - h + 2, w, h)
    ctx.fill()
    if rand:
        ctx.set_source_rgba(*hexrgb(rand, 0.6)); ctx.set_line_width(0.6)
        ctx.rectangle(x, y - h + 2, w, h); ctx.stroke()


def legende(ctx, t, x, xr):
    y = 690
    if Z.G0 - 0.3 <= t < Z.Z0 + 2.0:
        a = Z.seg(t, Z.G0 - 0.3, Z.G0 + 0.3) * (1 - Z.seg(t, Z.Z0 + 1.4, Z.Z0 + 2.0))
        text(ctx, "EINWOHNER JE KM²", x, y, F_SEMI, 11, GRAU, track=1.5, alpha=a)
        labs = ["unter 25", "25 bis unter 50", "50 bis unter 100", "100 bis unter 250", "250 und mehr"]
        for i in range(5):
            yy = y + 26 + i * 22
            ctx.push_group()
            swatch(ctx, x, yy, KLASSEN[i], TUSCHE)
            text(ctx, labs[i], x + 32, yy, F_BOOK, 13.5, TUSCHE)
            text(ctx, f"{META['klassen_anzahl'][i]} Gemeinden", xr, yy, F_MONO, 12.5, GRAU, "r")
            ctx.pop_group_to_source(); ctx.paint_with_alpha(a)
        yy = y + 26 + 5 * 22 + 8
        text(ctx, "Bevölkerung 31.12.2025 je Fläche 31.12.2024", x, yy, F_BOOK, 12.5, GRAU, alpha=a)
        text(ctx, f"Summe {de(META['summe_bev'])} Einwohner · {de_dez(META['summe_fl'])} km²",
             x, yy + 18, F_BOOK, 12.5, GRAU, alpha=a)
        ctx.push_group()
        swatch(ctx, x, yy + 46, ROT)
        text(ctx, "rot: in diesem Lauf neu", x + 32, yy + 46, F_BOOK, 13.5, TUSCHE)
        ctx.pop_group_to_source(); ctx.paint_with_alpha(a)
    elif Z.A0 - 1.0 <= t < Z.F0 - 0.2:
        a = Z.seg(t, Z.A0 - 1.0, Z.A0 - 0.4)
        ctx.push_group()
        text(ctx, "HÖHE DER GEBÄUDE", x, y, F_SEMI, 11, GRAU, track=1.5)
        swatch(ctx, x, y + 26, "#f0eadd", TUSCHE)
        text(ctx, "150 mit Geschosszahl (anzahlgs)", x + 32, y + 26, F_BOOK, 13.5, TUSCHE)
        text(ctx, "Höhe = Geschosse × 3 m, angenommen", x + 32, y + 44, F_BOOK, 12.5, GRAU)
        swatch(ctx, x, y + 72, "#b4cbcb", TUSCHE)
        text(ctx, "732 ohne Angabe", x + 32, y + 72, F_BOOK, 13.5, TUSCHE)
        text(ctx, "Höhe schematisch, einheitlich 3 m", x + 32, y + 90, F_BOOK, 12.5, GRAU)
        swatch(ctx, x, y + 118, ROT)
        text(ctx, "rot: in diesem Lauf neu", x + 32, y + 118, F_BOOK, 13.5, TUSCHE)
        ctx.set_source_rgba(*hexrgb(PETROL)); ctx.set_line_width(2.2)
        ctx.rectangle(x + 2, y + 140, 18, 10); ctx.stroke()
        text(ctx, "Kachel (kachel_m 400), je eine GetFeature-Abfrage", x + 32, y + 150, F_BOOK, 13.5, TUSCHE)
        ctx.pop_group_to_source(); ctx.paint_with_alpha(a)
    elif t >= Z.F0 - 0.2:
        a = Z.seg(t, Z.F0, Z.F0 + 0.5)
        ctx.push_group()
        text(ctx, "BERICHT DES FOLGELAUFS", x, y, F_SEMI, 11, GRAU, track=1.5)
        text(ctx, "Importlauf 20261107T043901Z", x, y + 26, F_MONO, 12.5, PETROL)
        if folge_fertig(t):
            c = Z.seg(t, Z.S1_SCAN + 0.2, Z.S1_SCAN + 0.7)
            text(ctx, "Laufzeit 141,8 s · 6 Quellen ok · neu 0 · geändert 0 · gelöscht 0", x, y + 50, F_BOOK, 13.5, TUSCHE, alpha=c)
            text(ctx, "unverändert 882 · 413 · 18 · 413 · 413 · 62.929", x, y + 70, F_BOOK, 13.5, TUSCHE, alpha=c)
            text(ctx, "fehlgeschlagen: keine · unvollständig: keine", x, y + 90, F_BOOK, 13.5, GRAU, alpha=c)
        ctx.pop_group_to_source(); ctx.paint_with_alpha(a)


def kopf(ctx, t):
    nr, titel, unter = kapitel(t)
    # helle Hinterlegung, damit der Kopf auch ueber dunklen Gemeinden lesbar bleibt
    font(ctx, F_MED, 22)
    w1 = sum(ctx.text_extents(c).x_advance for c in titel)
    font(ctx, F_BOOK, 14)
    w2 = sum(ctx.text_extents(c).x_advance for c in unter)
    ctx.set_source_rgba(*hexrgb(PAPIER, 0.85))
    ctx.rectangle(52, 50, 128 + max(w1, w2) + 14 - 52, 64)
    ctx.fill()
    text(ctx, nr, 62, 98, F_XL, 52, PETROL, tab=True)
    text(ctx, titel, 128, 78, F_MED, 22, TUSCHE)
    text(ctx, unter, 128, 99, F_BOOK, 14, GRAU)


def schema_hinweis(ctx, t):
    s = None
    if Z.K0 <= t < Z.G0:
        s = "schematisch: Reihenfolge und Takt der Linien (geliefert wurde in einer Abfrage)"
    elif Z.G0 <= t < Z.I0:
        s = "schematisch: Reihenfolge und Takt der Füllung (geliefert wurde in einer Abfrage)"
    elif Z.I0 <= t < Z.Z0 + 0.6:
        s = "schematisch: die Punkte; der Zähler steht im Bericht, Werte je Gemeinde zeigt der Film nicht"
    elif Z.A0 - 0.5 <= t < Z.F0 - 0.2:
        s = "schematisch: Takt je Kachel, Höhe (732 von 882 ohne Geschosszahl), Licht"
    elif Z.F0 - 0.2 <= t < Z.E0:
        s = "schematisch: der Strahl; der Abgleich selbst läuft über den fachlichen Schlüssel"
    if s:
        text(ctx, s, MAPR - 18, H - RI - 14, F_BOOK, 12, GRAU, "r")


def abspann(ctx, t):
    a = Z.ease(Z.seg(t, Z.E0, Z.E0 + 0.9))
    if a <= 0:
        return
    ctx.set_source_rgba(*hexrgb(PAPIER, 0.88 * a))
    ctx.rectangle(RI, RI, W - 2 * RI, H - 2 * RI)
    ctx.fill()
    def zeile(dt, f):
        b = Z.ease(Z.seg(t, Z.E0 + dt, Z.E0 + dt + 0.6))
        ctx.save()
        ctx.translate(0, (1 - b) * 10)
        f(b)
        ctx.restore()
    x = 150
    zeile(0.3, lambda b: text(ctx, "GEODATEN-IMPORT-PIPELINE", x, 330, F_SEMI, 15, PETROL, track=3, alpha=b))
    zeile(0.4, lambda b: text(ctx, "geodaten-import-pipeline", x - 4, 430, F_XL, 104, TUSCHE, alpha=b))
    font(ctx, F_XL, 104)
    bw = sum(ctx.text_extents(c).x_advance for c in "geodaten-import-pipeline") - 4  # Linie so breit wie der Schriftzug
    zeile(0.8, lambda b: linie(ctx, x, 468, x + bw * b, 468, TUSCHE, 0.8, b))
    zeile(0.9, lambda b: text(ctx, "Erster Lauf 07.11.2026 · 145,36 s", x, 528, F_LIGHT, 40, TUSCHE, alpha=b))
    zeile(1.2, lambda b: text(ctx, "Folgelauf 141,8 s · 0 neu · 0 geändert · 0 gelöscht", x, 576, F_LIGHT, 28, GRAU, alpha=b))
    zeile(1.6, lambda b: text(ctx, "github.com/andremadstop/geodaten-import-pipeline", x, 668, F_MONO, 24, PETROL, alpha=b))
    zeile(1.9, lambda b: text(ctx, "Geobasisdaten © GeoBasis-DE/LGB, dl-de/by-2-0 · Statistik: Amt für Statistik Berlin-Brandenburg, CC BY 3.0 DE · INKAR: © BBSR Bonn 2025, dl-de/by-2-0",
                              x, 900, F_BOOK, 14, GRAU, alpha=b))
    zeile(1.9, lambda b: text(ctx, "Läufe im Compose von MOSIDI am 07.11.2026; schematisch sind Takt, Punkte, Strahl, Licht und alle Gebäudehöhen.",
                              x, 922, F_BOOK, 14, GRAU, alpha=b))


def frame(i, ein, aus, pct):
    t = i / FPS
    statisch = int(round((Z.S1_SCAN + 0.1) * FPS))
    src = os.path.join(ein, "b_%04d.png" % min(i, statisch))
    img = cairo.ImageSurface.create_from_png(src)
    surf = cairo.ImageSurface(cairo.FORMAT_RGB24, img.get_width(), img.get_height())
    ctx = cairo.Context(surf)
    ctx.set_source_surface(img, 0, 0)
    ctx.paint()
    ctx.scale(pct / 100, pct / 100)
    fo = cairo.FontOptions()
    fo.set_antialias(cairo.ANTIALIAS_GRAY)
    fo.set_hint_style(cairo.HINT_STYLE_NONE)
    fo.set_hint_metrics(cairo.HINT_METRICS_OFF)
    ctx.set_font_options(fo)
    proj, S, tilt = Z.projektion(t)
    # Passepartout: Rand ausserhalb des Innenrahmens papierfarben (die Karte laeuft sonst ueber den Rahmen)
    ctx.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
    ctx.rectangle(0, 0, W, H)
    ctx.rectangle(RI, RI, W - 2 * RI, H - 2 * RI)
    ctx.set_source_rgba(*hexrgb(PAPIER))
    ctx.fill()
    ctx.set_fill_rule(cairo.FILL_RULE_WINDING)
    # Einblendung am Anfang
    ctx.push_group()
    ctx.save()
    ctx.rectangle(RI, RI, MAPR - RI, H - 2 * RI)  # Kartenlinien nur im Kartenfeld
    ctx.clip()
    gemeindegrenzen(ctx, t, proj, S)
    kreise(ctx, t, proj, S)
    campus_marke(ctx, t, proj)
    scanlinie(ctx, t, proj)
    ctx.restore()
    inkar(ctx, t, proj, (PX - 6, 214 + 36 + 5 * 30 - 5))
    kopf(ctx, t)
    schema_hinweis(ctx, t)
    rahmen(ctx, t, proj, S, tilt)
    schriftfeld(ctx, t)
    abspann(ctx, t)
    ctx.pop_group_to_source()
    ctx.paint_with_alpha(Z.ease(Z.seg(t, 0.0, 0.8)))
    surf.write_to_png(os.path.join(aus, "o_%04d.png" % i))
    return i


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--ein", required=True)
    ap.add_argument("--aus", required=True)
    ap.add_argument("--frames", default=f"0-{Z.N - 1}")
    ap.add_argument("--zeiten", default="")
    ap.add_argument("--pct", type=int, default=100)
    ap.add_argument("--prep", default="berichte/film-blender/prep", help="Ordner mit den Ausgaben von prep.py")
    ap.add_argument("--jobs", type=int, default=1, help="Prozesse; 1 = seriell")
    a = ap.parse_args()
    os.makedirs(a.aus, exist_ok=True)
    if a.zeiten:
        fr = [int(round(float(s) * FPS)) for s in a.zeiten.split(",")]
    else:
        v, b = a.frames.split("-")
        fr = list(range(int(v), int(b) + 1))
    import functools
    f = functools.partial(frame, ein=a.ein, aus=a.aus, pct=a.pct)
    n = 0
    if a.jobs > 1:
        with Pool(a.jobs) as p:
            for _ in p.imap_unordered(f, fr, chunksize=4):
                n += 1
    else:
        for i in fr:
            f(i)
            n += 1
            if n % 100 == 0:
                print("OVERLAY", n, flush=True)
    print("OVERLAY", n)
