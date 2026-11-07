#!/usr/bin/env python3
"""Der Lauf im Terminal: Film aus den echten Berichten der Geodaten-Import-Pipeline.

Alle Texte und Zahlen im Bild werden zur Renderzeit aus den Berichten unter beispielberichte/
gelesen (nur lesen). Geodaten braucht der Film nicht.

Aufruf (aus der Repo-Wurzel):
  python3 docs/filme/terminal/film.py                      # film.mp4 neben dem Skript
  python3 docs/filme/terminal/film.py --still 9.5,30       # Probebilder probe-<t>.png
  python3 docs/filme/terminal/film.py --standbild          # standbild.png
  python3 docs/filme/terminal/film.py --gif                # film.gif aus film.mp4
  python3 docs/filme/terminal/film.py --manifest           # jede Zahl mit Quelle als JSON
Optionen: --berichte <ordner> (Standard: beispielberichte/ der Repo-Wurzel), --jobs <n>.
"""
import json, math, os, re, subprocess, sys, argparse

import cairo
import numpy as np
from PIL import Image, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
_ap0 = argparse.ArgumentParser(add_help=False)
_ap0.add_argument("--berichte", default=os.path.join(HERE, "..", "..", "..", "beispielberichte"))
BB = os.path.normpath(_ap0.parse_known_args()[0].berichte)
E51 = f"{BB}/pruefstand-2026-11-07-e51"
MC = f"{E51}/mosidi-compose"

W, H, FPS = 1920, 1080, 30
FONT = "Noto Sans Mono"   # Terminal und Zahlen
UI = "Noto Sans"          # Beschriftungen in Kopf- und Fußzeile
FS = 20.5          # Terminalschrift
LH = 27.5          # Zeilenhoehe
KOPF_H = 64        # Höhe der Kopfleiste
TX0 = 72           # linker Rand Terminaltext
TY0 = 100          # erste Grundlinie
TROWS = 26         # sichtbare Terminalzeilen (letzte Grundlinie bei y 787,5)
# Mindestgrößen der Beschriftung bei 1920×1080
GR_KOPF, GR_NOTIZ, GR_QUELLE, GR_DATEN = 19, 17, 16, 17
COLS = 140         # Umbruchbreite in Zeichen

# Farben (RGB 0..1)
def hx(s):
    s = s.lstrip("#"); return tuple(int(s[i:i + 2], 16) / 255 for i in (0, 2, 4))
C = dict(
    bg_in=hx("#10191b"), bg_out=hx("#050909"),
    txt=hx("#f2bd5c"), dim=hx("#9a7a3e"), faint=hx("#5f4c2a"), bright=hx("#ffe3a6"),
    name=hx("#ffd88a"), num=hx("#fff1cf"), ok=hx("#9fd3c7"), err=hx("#ff5d4a"),
    warn=hx("#ff9a3d"), petrol=hx("#2a5d6b"), petrol_l=hx("#6fb0bf"), cream=hx("#f3ead6"),
    ink=hx("#2a2620"), paper=hx("#f1e8d2"), paper_line=hx("#d9e6e2"),
)

# ---------------------------------------------------------------- Daten aus dem Repo
def lies(p):
    with open(p, encoding="utf-8") as f:
        return f.read()

def bericht(txt, js):
    zeilen = lies(txt).rstrip("\n").split("\n")
    d = json.loads(lies(js))
    zeit = {q["quelle"]: q["laufzeit_s"] for q in d["quellen"]}
    kopf = zeilen[0]
    quellen, fuss, akt = [], [], None
    for z in zeilen[1:]:
        m = re.match(r"^  (\S+)\s+(ok|FEHLER)\b", z)
        if m:
            akt = dict(name=m.group(1), zeilen=[z], dauer=zeit[m.group(1)]); quellen.append(akt)
        elif z.startswith("      ") and akt is not None:
            akt["zeilen"].append(z)
        else:
            akt = None; fuss.append(z)
    assert [q["name"] for q in quellen] == [q["quelle"] for q in d["quellen"]]
    return dict(kopf=kopf, quellen=quellen, fuss=fuss, gesamt=d["laufzeit_s"], id=d["lauf_id"],
                start=d["start"], json=d)

def docker_zeilen(p):
    return [z.rstrip() for z in lies(p).split("\n") if z.startswith(" Container ")]

R1 = bericht(f"{MC}/20261107T043632Z.txt", f"{MC}/20261107T043632Z.json")
R2 = bericht(f"{MC}/20261107T043901Z.txt", f"{MC}/20261107T043901Z.json")
RF = bericht(f"{BB}/20261030T074610Z.txt", f"{BB}/20261030T074610Z.json")
assert lies(f"{MC}/konsole-lauf1.txt") == lies(f"{MC}/20261107T043632Z.txt")
assert lies(f"{MC}/konsole-lauf2.txt") == lies(f"{MC}/20261107T043901Z.txt")
D1 = docker_zeilen(f"{MC}/konsole-lauf1.err.txt")
D2 = docker_zeilen(f"{MC}/konsole-lauf2.err.txt")
MELDUNG = lies(f"{BB}/20261030T074610Z-meldung-kaputte_quelle.txt").rstrip("\n").split("\n")

# Befehl: wie in lauf.sh (dcp mit MOSIDI-Compose und Overlay), Argumente laut ablauf.txt
ablauf = lies(f"{MC}/ablauf.txt")
m = re.search(r"lauf1: Argumente '([^']+)'", ablauf); ARGS1 = m.group(1)
m = re.search(r"lauf2: Argumente '([^']+)'", ablauf); ARGS2 = m.group(1)
assert "dcp --profile pipeline run --rm pipeline --config \"$KONF\" --alle" in lies(f"{MC}/lauf.sh")
CMD1 = f"dcp --profile pipeline run --rm pipeline {ARGS1}"
CMD2 = f"dcp --profile pipeline run --rm pipeline {ARGS2}"

# Vollumfang (eigener Pruefstand, nicht im MOSIDI-Compose)
Q1 = lies(f"{E51}/quellen/20261107T044222Z.txt").split("\n")
Q2 = lies(f"{E51}/quellen/20261107T065227Z.txt").split("\n")
V1 = [Q1[0], next(z for z in Q1 if z.startswith("  inkar_gemeinden"))]
V2 = [Q2[0], next(z for z in Q2 if z.startswith("  inkar_gemeinden"))]
V_SEK1 = float(re.search(r"· ([\d.]+) s", Q1[0]).group(1))
V_SEK2 = float(re.search(r"· ([\d.]+) s", Q2[0]).group(1))
V_N = int(re.search(r"neu (\d+)", V1[1]).group(1))
assert V_N == int(re.search(r"unverändert (\d+)", V2[1]).group(1))
wa = lies(f"{E51}/wertabgleich/ergebnis-vollumfang.txt")
WA = {k: int(re.search(rf"^{k}: (\d+)$", wa, re.M).group(1)) for k in ("verglichen", "fehlend", "ueberzaehlig", "wert_abweichend")}
assert WA["verglichen"] == V_N
LAENDER = len(re.findall(r"\b(\d\d):\d+", wa.split("## Soll-Zeilen je Land")[1].split("\n\n")[0]))
assert LAENDER == 16
TESTS = int(re.search(r"^(\d+) passed", lies(f"{E51}/pruefen.log"), re.M).group(1))
dbt = lies(f"{E51}/datenbanktests.log")
DBT = re.findall(r"^(\d+) passed", dbt, re.M)
PGV = re.findall(r"^PostgreSQL ([\d.]+) ", dbt, re.M)
assert len(DBT) == 2 and len(PGV) == 2
def lizenzen(verz, namen):
    """Spalte Lizenz des Quellenverzeichnisses, nur für die im Lauf gezeigten Quellen;
    ohne Beispieldaten und ohne Quellen ohne Lizenz (–)."""
    liz, gesehen = [], set()
    for z in lies(verz).split("\n"):
        t = [c.strip() for c in z.split("|")]
        if len(t) > 6 and t[1] in namen:
            gesehen.add(t[1])
            if t[5] not in ("–", "-", "", "Beispieldaten") and t[5] not in liz: liz.append(t[5])
    assert gesehen == set(namen), (verz, set(namen) - gesehen)
    return liz
LIZ_L1 = lizenzen(f"{MC}/quellenverzeichnis.md", [q["name"] for q in R1["quellen"]])
LIZ_L2 = lizenzen(f"{MC}/quellenverzeichnis.md", [q["name"] for q in R2["quellen"]])
LIZ_F = lizenzen(f"{BB}/quellenverzeichnis.md", [q["name"] for q in RF["quellen"]])
LIZ_V = lizenzen(f"{E51}/quellen/quellenverzeichnis.md", ["inkar_gemeinden"])
LIZ = dict(lauf1=LIZ_L1, lauf2=LIZ_L2, fehler=LIZ_F, schluss=LIZ_V)
# Rechnerlast vor den beiden Läufen im Vollumfang (1/5/15 min)
_ab = lies(f"{E51}/quellen/ablauf.txt")
LAST = [re.search(rf"^lauf{k}: Rechnerlast davor \(1/5/15 min\): ([\d.]+) ([\d.]+) ([\d.]+)$", _ab, re.M).groups()
        for k in (1, 2)]

def de(x, n=1):
    return f"{x:.{n}f}".replace(".", ",")

def tausend(n):
    return f"{n:,}".replace(",", " ")

# ---------------------------------------------------------------- Zeilen mit Stil je Zeichen
class Z:
    def __init__(self, text, stil="txt"):
        self.t = text; self.s = [stil] * len(text)
    def mal(self, a, b, stil):
        for i in range(max(0, a), min(len(self.t), b)): self.s[i] = stil
        return self

def stil_bericht(z, lauf2=False):
    L = Z(z, "txt")
    if z.startswith("Importlauf"):
        return L.mal(0, len(z), "bright")
    m = re.match(r"^  (\S+)(\s+)(ok|FEHLER)\b", z)
    if m:
        L.mal(0, len(z), "dim")
        L.mal(m.start(1), m.end(1), "name")
        L.mal(m.start(3), m.end(3), "ok" if m.group(3) == "ok" else "errb")
        if m.group(3) == "FEHLER":
            L.mal(m.end(3), len(z), "err")
        for mm in re.finditer(r"(neu|geändert|gelöscht|unverändert)(\s+)(\d+)", z):
            L.mal(mm.start(1), mm.end(1), "dim")
            L.mal(mm.start(3), mm.end(3), "num" if mm.group(3) != "0" else "faint")
        return L
    m = re.match(r"^(\s+)(Hinweis:|Warnung:|Meldungsentwurf an den Anbieter:)", z)
    if m:
        L.mal(m.start(2), m.end(2), {"Hinweis:": "dim", "Warnung:": "warn"}.get(m.group(2), "errb"))
        if m.group(2) == "Warnung:": L.mal(m.end(2), len(z), "warn")
        if m.group(2).startswith("Meldung"): L.mal(m.end(2), len(z), "err")
        return L
    m = re.match(r"^  (Katalog:|Änderungskarte:)", z)
    if m:
        L.mal(m.start(1), m.end(1), "dim")
    return L

def umbruch(L, breite=None, einzug_sonst=4):
    """Umbrechen statt abschneiden; Folgezeilen haengen unter dem Text nach dem Etikett."""
    breite = breite or COLS
    t = L.t
    if len(t) <= breite: return [L]
    m = re.match(r"^(\s+(?:Hinweis:|Warnung:|Meldungsentwurf an den Anbieter:|Befund:|Abfrage:)\s+)", t) \
        or re.match(r"^(  \S+\s+FEHLER )", t)
    einzug = len(m.group(1)) if m else einzug_sonst
    if einzug > breite // 2:
        einzug = 2 * einzug_sonst
    rows, pos, erst = [], 0, True
    while pos < len(t):
        w = breite if erst else breite - einzug
        if not erst:
            # ein einzelnes Wort (z. B. Dateiname), das unter dem Etikett nicht passt: weniger Einzug
            nxt = t.find(" ", pos); nxt = len(t) if nxt < 0 else nxt
            if nxt - pos > w and nxt - pos <= breite - 2 * einzug_sonst:
                einzug = 2 * einzug_sonst; w = breite - einzug
        if len(t) - pos <= w:
            ende = len(t)
        else:
            ende = pos + w
            for c in range(pos + w, pos + w // 3, -1):
                if t[c] == " " or t[c - 1] in "/?&=,(" or t[c] in "&?":
                    ende = c; break
        stueck = Z(""); stueck.t = t[pos:ende]; stueck.s = L.s[pos:ende]
        if not erst:
            pre = Z(" " * einzug); stueck.t = pre.t + stueck.t; stueck.s = pre.s + stueck.s
        rows.append(stueck)
        pos = ende
        while pos < len(t) and t[pos] == " ": pos += 1
        erst = False
    return rows

# ---------------------------------------------------------------- Drehbuch
T_TITEL = 2.2
TYPE1, TYPE2 = 1.5, 0.7
F1, F1_INKAR, F2, FF = 14, 40, 48, 1

def quelle_sek(R):
    """Gesamtsekunden genau mit den Stellen aus dem Berichtskopf (141.8 bleibt 141,8)."""
    s = re.search(r"· ([\d.]+) s$", R["kopf"]).group(1)
    assert abs(float(s) - R["gesamt"]) < 1e-9
    return s.replace(".", ",")

def kopf_ohne_sek(R):
    return re.sub(r" · [\d.]+ s$", "", R["kopf"])

def lauf_szene(R, phasen, cmd, docker, typ):
    """phasen: [(Echtzeit-Beginn in s, Zeitraffer-Faktor), ...]; die Uhr folgt immer laufzeit_s."""
    t_bericht = (typ + 0.55) if cmd else 0.35
    grenzen = [p[0] for p in phasen[1:]] + [R["gesamt"]]
    film = [(g - p[0]) / p[1] for p, g in zip(phasen, grenzen)]
    return dict(R=R, phasen=phasen, grenzen=grenzen, film=film, cmd=cmd, docker=docker, typ=typ,
                t0=t_bericht, lauf=sum(film))

def r_von(S, x):
    """Echtzeit des Laufs nach x Filmsekunden ab Berichtsbeginn; dazu der gerade gültige Faktor."""
    x = max(0.0, x); a = 0.0
    for (r0, f), g, fl in zip(S["phasen"], S["grenzen"], S["film"]):
        if x < a + fl: return r0 + (x - a) * f, f
        a += fl
    return S["R"]["gesamt"], S["phasen"][-1][1]

def vor_quelle(R, name):
    s = 0.0
    for q in R["quellen"]:
        if q["name"] == name: return s
        s += q["dauer"]
    raise KeyError(name)

S1 = lauf_szene(R1, [(0.0, F1), (vor_quelle(R1, "inkar_gemeinden"), F1_INKAR)], CMD1, D1, TYPE1); S1["halt"] = 2.2
S2 = lauf_szene(R2, [(0.0, F2)], CMD2, D2, TYPE2); S2["halt"] = 1.3
SF = lauf_szene(RF, [(0.0, FF)], None, [], 0);     SF["halt"] = 1.4
PAPIER_DRUCK, PAPIER_HALT = 2.0, 5.7
T_SCHLUSS = 7.5

def dauer(S): return S["t0"] + S["lauf"] + S["halt"]
SZENEN = [("titel", T_TITEL), ("lauf1", dauer(S1)), ("lauf2", dauer(S2)),
          ("fehler", dauer(SF) + PAPIER_DRUCK + PAPIER_HALT), ("schluss", T_SCHLUSS)]
GESAMT = sum(d for _, d in SZENEN)
NFRAMES = int(round(GESAMT * FPS))

def szene_bei(t):
    a = 0.0
    for n, d in SZENEN:
        if t < a + d: return n, t - a, d
        a += d
    return SZENEN[-1][0], SZENEN[-1][1], SZENEN[-1][1]

SPIN = "|/-\\"

def terminal_zeilen(S, lt, takt=True):
    """Zeilen des Terminals zur lokalen Zeit lt; dazu die Echtzeit r des Laufs."""
    R = S["R"]; rows = []
    cur = (int(lt * 2.2) % 2 == 0)
    if S["cmd"]:
        n = len(S["cmd"])
        k = n if lt >= S["typ"] else int(n * min(1, lt / S["typ"]))
        p = Z("$ ", "ok"); p.t += S["cmd"][:k]; p.s += ["bright"] * k
        rows.append((p, lt < S["typ"] + 0.2 and cur))
        for i, d in enumerate(S["docker"]):
            if lt >= S["typ"] + 0.15 + 0.1 * i: rows.append((Z(d, "faint"), False))
    if lt < S["t0"]:
        return rows, 0.0, False
    fertig = (lt - S["t0"]) >= S["lauf"]
    r = R["gesamt"] if fertig else r_von(S, lt - S["t0"])[0]
    # Kopf ohne Sekunden, bis der Lauf fertig ist; dann wörtlich aus der Datei
    kopf = R["kopf"] if fertig else kopf_ohne_sek(R)
    rows.append((stil_bericht(kopf), False))
    c = 0.0
    for q in R["quellen"]:
        if r >= c + q["dauer"] or fertig:
            for z in q["zeilen"]: rows.append((stil_bericht(z), False))
        elif r >= c:
            el = r - c
            sp = SPIN[int(lt * 14) % 4]
            live = Z(f"  {q['name']:<24} {sp} läuft  {el:6.2f} s", "dim")
            live.mal(2, 2 + len(q["name"]), "name").mal(27, 28, "bright")
            rows.append((live, False)); break
        else:
            break
        c += q["dauer"]
    if fertig:
        for z in R["fuss"]: rows.append((stil_bericht(z), False))
        p = Z("$ ", "ok") if S["cmd"] else None
        if p: rows.append((p, cur))
    return rows, r, fertig

# ---------------------------------------------------------------- Zeichnen
def font(cr, gewicht="normal", size=FS, fam=FONT):
    cr.select_font_face(fam, cairo.FONT_SLANT_NORMAL,
                        cairo.FONT_WEIGHT_BOLD if gewicht == "bold" else cairo.FONT_WEIGHT_NORMAL)
    cr.set_font_size(size)

STILE = {"txt": ("txt", "normal"), "dim": ("dim", "normal"), "faint": ("faint", "normal"),
         "bright": ("bright", "bold"), "name": ("name", "bold"), "num": ("num", "bold"),
         "ok": ("ok", "bold"), "err": ("err", "normal"), "errb": ("err", "bold"), "warn": ("warn", "normal")}

def zeile_malen(cr, L, x, y, cw, cursor=False, alpha=1.0):
    i = 0; t = L.t
    while i < len(t):
        j = i
        while j < len(t) and L.s[j] == L.s[i]: j += 1
        farbe, gew = STILE[L.s[i]]
        font(cr, gew); cr.set_source_rgba(*C[farbe], alpha)
        cr.move_to(x + i * cw, y); cr.show_text(t[i:j])
        i = j
    if cursor:
        cr.set_source_rgba(*C["txt"], alpha)
        cr.rectangle(x + len(t) * cw + 2, y - FS * 0.82, cw - 2, FS * 1.05); cr.fill()

def fopts():
    fo = cairo.FontOptions(); fo.set_antialias(cairo.ANTIALIAS_GRAY); fo.set_hint_style(cairo.HINT_STYLE_SLIGHT)
    fo.set_hint_metrics(cairo.HINT_METRICS_OFF); return fo

def zeichen_breite():
    s = cairo.ImageSurface(cairo.FORMAT_ARGB32, 10, 10); cr = cairo.Context(s); cr.set_font_options(fopts()); font(cr)
    return cr.text_extents("M" * 100).x_advance / 100
CW = zeichen_breite()
COLS = int((W - TX0 - 56) / CW)
FEHLER_COLS = int((1110 - 44 - TX0) / CW)

def verblasst(L):
    """Verlauf eines früheren Laufs im selben Terminal: gleiche Zeichen, gedämpft."""
    n = Z(L.t, "faint"); return n

def terminal_malen(cr, rows, alpha=1.0, breite=None):
    flach = []
    for L, cur in rows:
        teile = umbruch(L, breite)
        for k, tl in enumerate(teile): flach.append((tl, cur and k == len(teile) - 1))
    sichtbar = flach[-TROWS:]
    for n, (L, cur) in enumerate(sichtbar):
        zeile_malen(cr, L, TX0, TY0 + n * LH, CW, cur, alpha)
    return len(flach)

BOXEN = []   # (Kontext, x0, y0, x1, y1, Text) fuer --check

def text(cr, s, x, y, size, farbe, gewicht="normal", alpha=1.0, anker="l", fam=FONT):
    font(cr, gewicht, size, fam)
    w = cr.text_extents(s).x_advance
    if anker == "r": x -= w
    elif anker == "c": x -= w / 2
    cr.set_source_rgba(*farbe, alpha); cr.move_to(x, y); cr.show_text(s)
    if s.strip():
        e = cr.text_extents(s)
        BOXEN.append((id(cr), x, y + e.y_bearing, x + max(w, e.x_bearing + e.width), y + e.y_bearing + e.height, s))
    return w

def absatz(cr, s, x, y_letzte, size, farbe, breite, lh, gewicht="normal", alpha=1.0, fam=UI):
    """Text auf breite umbrechen; die LETZTE Zeile steht auf y_letzte (wächst nach oben)."""
    font(cr, gewicht, size, fam)
    zeilen, akt = [], ""
    for wort in s.split(" "):
        probe = (akt + " " + wort).strip()
        if akt and cr.text_extents(probe).x_advance > breite:
            zeilen.append(akt); akt = wort
        else:
            akt = probe
    if akt: zeilen.append(akt)
    y0 = y_letzte - (len(zeilen) - 1) * lh
    for k, z in enumerate(zeilen):
        text(cr, z, x, y0 + k * lh, size, farbe, gewicht, alpha, fam=fam)
    return y0

def rrect(cr, x, y, w, h, r):
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0); cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi); cr.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
    cr.close_path()

def kopfleiste(cr, links, mitte, faktor_txt, uhr_txt, alpha=1.0, blitz=0.0):
    cr.set_source_rgba(*C["petrol"], 0.92 * alpha); cr.rectangle(0, 0, W, KOPF_H); cr.fill()
    cr.set_source_rgba(*C["petrol_l"], 0.6 * alpha); cr.rectangle(0, KOPF_H, W, 1.5); cr.fill()
    yb = 41
    lw = text(cr, links, 32, yb, GR_KOPF + 1, C["cream"], "bold", alpha, fam=UI)
    if mitte: text(cr, mitte, 32 + lw + 44, yb, GR_KOPF - 1, C["cream"], "normal", 0.92 * alpha, fam=UI)
    if faktor_txt:
        font(cr, "bold", GR_KOPF, UI); w = cr.text_extents(faktor_txt).x_advance + 28
        x = W - 32 - w
        if uhr_txt:
            uw = text(cr, uhr_txt, W - 32, yb, GR_KOPF, C["cream"], "normal", alpha, "r", fam=UI)
            x = W - 32 - uw - 20 - w
        if blitz > 0:   # Umschalten des Zeitraffers: Plakette blitzt auf
            g = 6 + 10 * blitz
            cr.set_source_rgba(*C["bright"], 0.55 * blitz * alpha); rrect(cr, x - g, 15 - g, w + 2 * g, 34 + 2 * g, 4 + g); cr.fill()
        bgc = tuple(C["cream"][k] * (1 - blitz) + C["warn"][k] * blitz for k in range(3))
        cr.set_source_rgba(*bgc, alpha); rrect(cr, x, 15, w, 34, 4); cr.fill()
        text(cr, faktor_txt, x + 14, yb, GR_KOPF, C["petrol"], "bold", alpha, fam=UI)

def zeitleiste(cr, R, r, titel, alpha=1.0):
    x0, x1, y = 72, W - 72, ZL_Y
    tot = sum(q["dauer"] for q in R["quellen"])
    tw = text(cr, titel, x0, y - 13, 16, C["petrol_l"], "bold", alpha, fam=UI)
    cx, mittel = x0, []
    for i, q in enumerate(R["quellen"]):
        w = (x1 - x0) * q["dauer"] / tot
        cr.set_source_rgba(*C["petrol"], 0.55 * alpha); cr.rectangle(cx, y, max(w - 2, 1), 14); cr.fill()
        anteil = max(0.0, min(1.0, (r - (cx - x0) / (x1 - x0) * tot) / q["dauer"]))
        farbe = C["err"] if q["zeilen"][0].split()[1] == "FEHLER" else C["txt"]
        if anteil > 0:
            cr.set_source_rgba(*farbe, 0.95 * alpha); cr.rectangle(cx, y, max((w - 2) * anteil, 1), 14); cr.fill()
        mittel.append((cx + max(w - 2, 1) / 2, q, w))
        cx += w
    # Große Segmente: Etikett mittig über dem Segment. Kleine: darunter in Segmentfolge,
    # ohne Führungslinien, ohne Überlappung, am rechten Rand gestaut.
    klein = []
    for mx, q, w in mittel:
        lab = f"{q['name']}  {de(q['dauer'], 2)} s"
        if w >= 300:
            font(cr, "bold", 17); lw = cr.text_extents(lab).x_advance
            lx = min(max(mx - lw / 2, x0 + tw + 36), x1 - lw)
            text(cr, lab, lx, y - 12, 17, C["txt"], "bold", alpha)
        else:
            font(cr, "normal", 16); lw = cr.text_extents(lab).x_advance
            klein.append([mx - (w - 2) / 2, lw, lab])
    for k in range(len(klein)):
        if k: klein[k][0] = max(klein[k][0], klein[k - 1][0] + klein[k - 1][1] + 28)
        klein[k][0] = max(klein[k][0], x0)
    for k in range(len(klein) - 1, -1, -1):
        grenze = x1 if k == len(klein) - 1 else klein[k + 1][0] - 28
        klein[k][0] = min(klein[k][0], grenze - klein[k][1])
    for lx, lw, lab in klein:
        text(cr, lab, lx, y + 38, 16, C["txt"], "normal", 0.9 * alpha)
    # Spielkopf
    px = x0 + (x1 - x0) * min(r / tot, 1.0) if tot else x0
    cr.set_source_rgba(*C["bright"], alpha); cr.rectangle(px - 1, y - 6, 2, 26); cr.fill()

def fuss(cr, notiz, quelle, liz, alpha=1.0):
    if notiz:
        absatz(cr, notiz, 72, 990, GR_NOTIZ, C["petrol_l"], W - 144, 22, alpha=0.95 * alpha)
    cr.set_source_rgba(*C["petrol"], 0.6 * alpha); cr.rectangle(72, 1004, W - 144, 1); cr.fill()
    if quelle: text(cr, quelle, 72, 1027, GR_QUELLE, C["dim"], "normal", alpha, fam=UI)
    if liz: text(cr, "Daten: " + " · ".join(liz), 72, 1055, GR_DATEN, C["txt"], "normal", 0.95 * alpha, fam=UI)

ZL_Y = 890          # Balken der Zeitleiste
NOTIZ_DCP_Y = 846   # letzte Zeile der dcp-Erklärung

def dcp_notiz(cr):
    absatz(cr, DCP_NOTIZ, 72, NOTIZ_DCP_Y, GR_NOTIZ, C["petrol_l"], W - 144, 22)

DCP_NOTIZ = ("dcp = docker compose mit der docker-compose.yml von MOSIDI und dem Overlay deploy/mosidi/docker-compose.pipeline.yml "
             "(Alias wie in deploy/mosidi/README.md; im Prüfstand zusätzlich ein Test-Override, lauf.sh)")
NOTIZ_TAKT = ("schematisch: Die Zeilen erscheinen im Takt der gemessenen Laufzeit je Quelle (laufzeit_s im JSON-Bericht); "
              "der echte Lauf gibt den Bericht am Ende gesammelt aus.")

def papier(cr, lt):
    """Meldungsentwurf als Endlospapier, das Zeile fuer Zeile aus dem Drucker kommt."""
    lh, fs = 21.0, 14.0
    px = PAPIER_X; pw = W - 72 - px
    font(cr, "normal", fs); cwp = cr.text_extents("M" * 100).x_advance / 100
    spalten = int((pw - 100) / cwp)
    zeilen, kern = [], []
    for z in MELDUNG:
        teile = [L.t for L in umbruch(Z(z), spalten, 0)]
        wichtig = bool(re.match(r"^\s+(Befund|Zeitpunkt|Abfrage):", z))
        zeilen += teile; kern += [wichtig] * len(teile)
    n = len(zeilen)
    k = n if lt >= PAPIER_DRUCK else int(n * lt / PAPIER_DRUCK)
    kante = PAPIER_KANTE             # Druckkopf-Kante: Papier kommt hier heraus
    marker = max(0.0, min(1.0, (lt - PAPIER_DRUCK - 0.5) / 0.5))
    ph_voll = 70 + n * lh
    sichtbar_h = 70 + k * lh + (lh * ((lt * n / PAPIER_DRUCK) % 1) if lt < PAPIER_DRUCK else 0)
    top = kante - sichtbar_h
    # Schatten
    cr.save(); cr.rectangle(0, KOPF_H + 2, W, kante - KOPF_H - 2); cr.clip()
    cr.set_source_rgba(0, 0, 0, 0.45); cr.rectangle(px + 10, top + 12, pw, sichtbar_h); cr.fill()
    cr.set_source_rgb(*C["paper"]); cr.rectangle(px, top, pw, sichtbar_h + 2); cr.fill()
    # Lochrand
    for side in (px + 18, px + pw - 18):
        yy = top + 14
        while yy < top + sichtbar_h:
            cr.set_source_rgb(*C["bg_out"]); cr.arc(side, yy, 6, 0, 2 * math.pi); cr.fill(); yy += 28
    cr.set_source_rgba(*C["petrol"], 0.35); cr.set_line_width(1)
    for sx in (px + 36, px + pw - 36):
        cr.move_to(sx, top); cr.line_to(sx, top + sichtbar_h); cr.stroke()
    # gruene Zebrastreifen wie Listenpapier, in Petrol
    for i in range(0, k + 2, 2):
        cr.set_source_rgba(*C["petrol"], 0.07); cr.rectangle(px + 37, top + 52 + i * lh - lh * 0.75, pw - 74, lh); cr.fill()
    text(cr, "20261030T074610Z-meldung-kaputte_quelle.txt", px + 50, top + 34, 13, C["petrol"], "bold")
    for i in range(k):
        if kern[i] and marker > 0:   # Leuchtmarker auf Befund / Zeitpunkt / Abfrage
            cr.set_source_rgba(*C["txt"], 0.55 * marker)
            cr.rectangle(px + 44, top + 64 + i * lh - lh * 0.78, pw - 88, lh); cr.fill()
        text(cr, zeilen[i], px + 50, top + 64 + i * lh, fs, C["ink"], "bold" if (i == 0 or (kern[i] and marker > 0.5)) else "normal")
    cr.restore()
    druckerschlitz(cr)
    return n

PAPIER_X = 1110       # Papier rechts, Terminal links (Ursache und Folge gleichzeitig sichtbar)
PAPIER_KANTE = 838

def druckerschlitz(cr, beschriftet=False):
    px = PAPIER_X; pw = W - 72 - px; kante = PAPIER_KANTE
    cr.set_source_rgb(*C["bg_out"]); cr.rectangle(px - 24, kante, pw + 48, 10); cr.fill()
    cr.set_source_rgba(*C["petrol_l"], 0.7); cr.rectangle(px - 24, kante, pw + 48, 2); cr.fill()
    if beschriftet:
        text(cr, "Meldungsentwürfe an den Anbieter", px - 24, kante - 14, GR_NOTIZ, C["petrol_l"], "normal", 0.9, fam=UI)

# ---------------------------------------------------------------- Bildaufbau
_STATIC = {}
def statik(clean):
    if clean in _STATIC: return _STATIC[clean]
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    d = np.sqrt(((xx - W / 2) / (W * 0.62)) ** 2 + ((yy - H / 2) / (H * 0.62)) ** 2)
    v = np.clip(d, 0, 1) ** 1.6
    bg = (np.array(C["bg_in"], np.float32)[None, None] * (1 - v[..., None]) +
          np.array(C["bg_out"], np.float32)[None, None] * v[..., None])
    vign = (1 - 0.35 * np.clip(d - 0.55, 0, 1) ** 1.2)[..., None]
    scan = np.ones((H, 1, 1), np.float32)
    if not clean:
        scan[2::3] = 0.86
    rng = np.random.default_rng(7)
    # eine feste Koernung: bewegtes Rauschen blaeht das Video auf (Web)
    grain = [] if clean else [rng.normal(0, 0.012, (H, W, 1)).astype(np.float32)]
    _STATIC[clean] = (bg, vign, scan, grain)
    return _STATIC[clean]

def surf_np(s):
    a = np.ndarray((H, W, 4), np.uint8, s.get_data()).astype(np.float32) / 255
    return a[..., [2, 1, 0]], a[..., 3:4]  # vormultipliziert

def blur(rgb, r):
    im = Image.fromarray((np.clip(rgb, 0, 1) * 255).astype(np.uint8))
    im = im.resize((W // 2, H // 2), Image.BILINEAR).filter(ImageFilter.GaussianBlur(r / 2)).resize((W, H), Image.BILINEAR)
    return np.asarray(im).astype(np.float32) / 255

def frame(i, clean=False):
    t = i / FPS
    name, lt, sd = szene_bei(t)
    term = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H); ct = cairo.Context(term)
    ui = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H); cu = cairo.Context(ui)
    for c in (ct, cu): c.set_antialias(cairo.ANTIALIAS_GRAY)
    fo = fopts()
    ct.set_font_options(fo); cu.set_font_options(fo)
    hell = 1.0

    if name == "titel":
        on = min(1.0, lt / 0.35)
        s = "Der Lauf im Terminal"
        k = min(len(s), int(len(s) * max(0, lt - 0.3) / 0.7))
        text(ct, s[:k], 160, 470, 76, C["bright"], "bold")
        if (int(lt * 3) % 2 == 0) or k < len(s):
            font(ct, "bold", 76); w = ct.text_extents(s[:k]).x_advance
            ct.set_source_rgba(*C["txt"], 1); ct.rectangle(166 + w, 410, 40, 70); ct.fill()
        if lt > 0.7:
            a = min(1, (lt - 0.7) / 0.3)
            text(ct, "Geodaten-Import-Pipeline für MOSIDI. Echte Läufe vom 07.11.2026, Fehlerfall vom 30.10.2026.",
                 164, 545, 24, C["txt"], "normal", a)
            text(cu, "André Stiebitz · Angebot VA-2026-536", 164, 600, 20, C["petrol_l"], "bold", a)
        # Einschalten: Leuchtstrich, der aufgeht
        if on < 1:
            hell = on
        fuss(cu, None, None, None, 1.0)

    elif name in ("lauf1", "lauf2", "fehler"):
        S = {"lauf1": S1, "lauf2": S2, "fehler": SF}[name]
        rows, r, fertig = terminal_zeilen(S, min(lt, dauer(S)))
        if name == "lauf2":
            # selbes Terminal: Lauf 1 steht noch darüber und rollt nach oben weg
            vorher = terminal_zeilen(S1, dauer(S1))[0][:-1]
            rows = [(verblasst(L), False) for L, _ in vorher] + rows
        R = S["R"]
        x = lt - S["t0"]
        f_jetzt = r_von(S, x)[1] if not fertig else S["phasen"][-1][1]
        uhr = f"Laufzeit {de(r, 2)} s von {quelle_sek(R)} s" if not fertig else f"Laufzeit {quelle_sek(R)} s"
        if name == "lauf1":
            terminal_malen(ct, rows)
            ws = S["film"][0]
            blitz = max(0.0, 1 - (x - ws) / 0.6) if ws <= x < ws + 0.6 else 0.0
            ftxt = f"Zeitraffer {f_jetzt}×" if x < ws or not fertig else f"Zeitraffer {F1}× / {F1_INKAR}×"
            kopfleiste(cu, "Der Lauf im Terminal", "Lauf 1 · MOSIDI-Compose, PostgreSQL 18.6 · 07.11.2026, 04:36 UTC · Prüfkonfiguration, Erstlauf",
                       ftxt, uhr, blitz=blitz)
            zeitleiste(cu, R, r, "Laufzeit je Quelle (laufzeit_s), maßstäblich")
            dcp_notiz(cu)
            fuss(cu, NOTIZ_TAKT + f" Ab inkar_gemeinden Zeitraffer {F1_INKAR}× statt {F1}×.",
                 "Quelle: pruefstand-2026-11-07-e51/mosidi-compose/konsole-lauf1.txt, konsole-lauf1.err.txt, 20261107T043632Z.json, ablauf.txt, lauf.sh", LIZ_L1)
        elif name == "lauf2":
            terminal_malen(ct, rows)
            kopfleiste(cu, "Der Lauf im Terminal", "Lauf 2 · direkt danach, 04:39 UTC · dieselbe Konfiguration, nichts geändert",
                       f"Zeitraffer {F2}×", uhr)
            zeitleiste(cu, R, r, "Laufzeit je Quelle (laufzeit_s), maßstäblich")
            dcp_notiz(cu)
            fuss(cu, NOTIZ_TAKT + " Lauf 1 darüber gedämpft.",
                 "Quelle: pruefstand-2026-11-07-e51/mosidi-compose/konsole-lauf2.txt, konsole-lauf2.err.txt, 20261107T043901Z.json, ablauf.txt", LIZ_L2)
        else:
            terminal_malen(ct, rows, breite=FEHLER_COLS)
            kopfleiste(cu, "Der Lauf im Terminal", "Prototyp · 30.10.2026, 07:46 UTC · Quelle absichtlich unerreichbar (wfs.example.invalid)",
                       "Echtzeit 1×", uhr)
            zeitleiste(cu, R, r, "Laufzeit je Quelle (laufzeit_s), maßstäblich")
            lp = lt - dauer(SF)
            notiz = NOTIZ_TAKT + " Lange Zeilen umbrochen." if lp < 0 else ("schematisch: Meldungsentwurf als Ausdruck dargestellt, Markierung nachträglich; "
                                               "Text unverändert aus der Datei, er wird nicht automatisch versendet.")
            fuss(cu, notiz, "Quelle: beispielberichte/20261030T074610Z.txt, .json, 20261030T074610Z-meldung-kaputte_quelle.txt, quellenverzeichnis.md", LIZ_F)
            if lp >= 0:
                papier(cu, lp)
            else:
                druckerschlitz(cu, beschriftet=True)
        # kurzer Bildwechsel wie beim Loeschen des Schirms
        if lt < 0.12 and name == "fehler": hell = 0.35 + lt / 0.12 * 0.65

    elif name == "schluss":
        kopfleiste(cu, "Der Lauf im Terminal", "Vollumfang INKAR · eigener Prüfstand 07.11.2026, nicht im MOSIDI-Compose gemessen",
                   None, None)
        def ein(t0, d=0.4): return max(0.0, min(1.0, (lt - t0) / d))
        fs2 = 24; cw2 = CW * fs2 / FS
        text(ct, "Auszug aus den Berichten im Vollumfang (nur die Zeile inkar_gemeinden):", TX0, 118, 22, C["dim"])
        # Berichtszeilen vom ersten Bild an wörtlich (kein Zwischenwert in der Zeile)
        zeilen = [(V1[0], 170), (V1[1], 203)]
        if lt > 0.3:
            zeilen += [(V2[0], 255), (V2[1], 288)]
        for z, y in zeilen:
            L = stil_bericht(z)
            i = 0
            while i < len(L.t):   # wie zeile_malen, nur größer
                j = i
                while j < len(L.t) and L.s[j] == L.s[i]: j += 1
                farbe, gew = STILE[L.s[i]]
                font(ct, gew, fs2); ct.set_source_rgba(*C[farbe], 1); ct.move_to(TX0 + i * cw2, y); ct.show_text(L.t[i:j])
                i = j
        if lt > 0.8:
            # nur die große Zahl zählt hoch (schematisch), Endwert exakt ab 2,3 s
            u = min(1.0, (lt - 0.8) / 1.5)
            zahl = V_N if u >= 1 else int(V_N * (1 - (1 - u) ** 3))
            a = ein(0.8, 0.3)
            text(cu, tausend(zahl), 66, 500, 168, C["cream"], "bold", a)
            text(cu, f"INKAR-Werte auf Gemeindeebene, {LAENDER} Länder", 74, 556, 34, C["petrol_l"], "normal", a, fam=UI)
        if lt > 2.5:
            a = ein(2.5)
            xr = 1190
            text(cu, f"{WA['fehlend']} / {WA['ueberzaehlig']} / {WA['wert_abweichend']}", xr, 500, 120, C["txt"], "bold", a)
            text(cu, "Wertabgleich je Zeile:", xr + 4, 544, 26, C["dim"], "normal", a, fam=UI)
            text(cu, "fehlend / überzählig / abweichend", xr + 4, 578, 26, C["dim"], "normal", a, fam=UI)
        if lt > 3.1:
            a = ein(3.1)
            sp = [(f"{de(V_SEK1 / 60, 1)} min", f"Erstlauf, {de(V_SEK1, 2)} s"),
                  (f"{de(V_SEK2 / 60, 1)} min", f"Folgelauf, alles unverändert, {de(V_SEK2, 2)} s"),
                  (f"{TESTS}", "Tests in pruefen.sh")]
            for j, (gross, klein) in enumerate(sp):
                xx = 72 + j * 600
                text(cu, gross, xx, 730, 84, C["txt"], "bold", a)
                text(cu, klein, xx + 4, 774, 26, C["dim"], "normal", a, fam=UI)
            l1, l2 = (" / ".join(x.replace(".", ",") for x in L) for L in LAST)
            text(cu, f"Rechnerlast davor (1/5/15 min, 16 Kerne): Erstlauf {l1}, Folgelauf {l2}",
                 76, 818, 24, C["dim"], "normal", a, fam=UI)
        if lt > 3.9:
            a = ein(3.9)
            text(cu, f"Datenbanktests {DBT[0]} von {DBT[0]} auf PostgreSQL {PGV[0]} und {DBT[1]} von {DBT[1]} auf PostgreSQL {PGV[1]}",
                 72, 880, 32, C["cream"], "normal", a, fam=UI)
        if lt > 4.5:
            a = ein(4.5)
            text(cu, "André Stiebitz · Geodaten-Import-Pipeline · Angebot VA-2026-536", 72, 934, 30, C["petrol_l"], "bold", a, fam=UI)
        fuss(cu, "schematisch: Die große Zahl zählt hoch. Endwert und alle übrigen Zahlen wörtlich aus den Dateien; "
                 "Minuten aus den Sekunden der Berichtsköpfe umgerechnet.",
             "Quelle: pruefstand-2026-11-07-e51/quellen/ (Berichte, ablauf.txt), wertabgleich/ergebnis-vollumfang.txt, pruefen.log, datenbanktests.log", LIZ_V)
        # kein Ausblenden: der Film endet auf dem fertigen Schlussbild

    term.flush(); ui.flush()
    bg, vign, scan, grain = statik(clean)
    trgb, ta = surf_np(term)
    urgb, ua = surf_np(ui)
    img = bg * (1 - ta) + trgb
    if not clean:
        img = img + 0.55 * blur(trgb, 9) + 0.25 * blur(trgb, 26)
    else:
        img = img + 0.35 * blur(trgb, 9)
    img = img * scan
    if grain: img = img + grain[i % len(grain)]
    img = img * vign
    img = img * (1 - ua) + urgb          # Bedienleiste gestochen scharf, ohne Leuchten
    if name == "titel" and hell < 1:
        # Einschalten: heller Strich in der Mitte, der sich öffnet
        h = int(H * hell / 2)
        maske = np.zeros((H, 1, 1), np.float32); maske[H // 2 - h:H // 2 + h + 2] = 1
        img = img * maske; img[H // 2 - 1:H // 2 + 2] += (1 - hell) * 0.8
    elif hell < 1:
        img = img * hell
    return (np.clip(img, 0, 1) * 255).astype(np.uint8)

def _f(args):
    i, clean = args
    return frame(i, clean).tobytes()

def szene_start(n):
    a = 0.0
    for name, d in SZENEN:
        if name == n: return a
        a += d
    raise KeyError(n)

T_STANDBILD = szene_start("lauf2") - 0.5      # Ende von Lauf 1: Bericht komplett, Zeitleiste voll

def pruefe_layout():
    """Beschriftung: nichts über den rechten Rand, keine Überlappung (je Ebene), Mindestgröße."""
    fehler = 0
    for n, d in SZENEN:
        t0 = szene_start(n)
        for t in (t0 + 0.05, t0 + d / 2, t0 + d - 0.05):
            BOXEN.clear(); frame(int(t * FPS), True)
            for k, (c, x0, y0, x1, y1, s) in enumerate(BOXEN):
                if x1 > W - 30 or x0 < 0:
                    print(f"{n} t={t:.2f}: über den Rand: {s[:60]!r} ({x1:.0f})"); fehler += 1
                for c2, a0, b0, a1, b1, s2 in BOXEN[k + 1:]:
                    if c2 == c and x0 < a1 - 1 and a0 < x1 - 1 and y0 < b1 - 1 and b0 < y1 - 1:
                        print(f"{n} t={t:.2f}: Überlappung {s[:40]!r} / {s2[:40]!r}"); fehler += 1
    print("Layout ok" if not fehler else f"{fehler} Befunde")
    return fehler

def render_video(out, jobs, clean):
    print(f"Dauer {GESAMT:.2f} s, {NFRAMES} Bilder", file=sys.stderr)
    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                           "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "slow", "-crf", "20", "-pix_fmt", "yuv420p",
                           "-profile:v", "high", "-level", "4.1", "-r", str(FPS), "-movflags", "+faststart", out],
                          stdin=subprocess.PIPE)
    auftraege = [(i, clean) for i in range(NFRAMES)]
    bilder = None
    if jobs > 1:
        try:
            from multiprocessing import Pool
            pool = Pool(jobs)
            bilder = pool.imap(_f, auftraege, chunksize=4)
        except (OSError, PermissionError) as e:
            print(f"kein Multiprocessing ({e}), rechne seriell", file=sys.stderr)
    if bilder is None:
        bilder = map(_f, auftraege)
    for k, b in enumerate(bilder):
        ff.stdin.write(b)
        if k % 150 == 0: print(k, file=sys.stderr)
    ff.stdin.close(); ff.wait()
    if ff.returncode: sys.exit(ff.returncode)

def render_gif(mp4, out, fps=10, breite=960):
    """GIF für die README: 960 px breit, 10 fps, eigene Palette (Ziel unter 6 MB)."""
    vf = (f"fps={fps},scale={breite}:-1:flags=lanczos,split[a][b];"
          "[a]palettegen=max_colors=64:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", mp4, "-vf", vf, "-loop", "0", out], check=True)
    print(f"{out}: {os.path.getsize(out) / 1e6:.2f} MB", file=sys.stderr)

def main():
    ap = argparse.ArgumentParser(description="Film „Der Lauf im Terminal“ aus den Beispielberichten bauen")
    ap.add_argument("--berichte", default=BB, help="Ordner beispielberichte/ (Standard: Repo-Wurzel relativ zum Skript)")
    ap.add_argument("--clean", action="store_true", help="ohne Rasterzeilen und Körnung")
    ap.add_argument("--still", default="", help="Probebilder zu Zeitpunkten in s, Komma-getrennt")
    ap.add_argument("--standbild", action="store_true", help="standbild.png (Ende von Lauf 1)")
    ap.add_argument("--gif", action="store_true", help="film.gif aus film.mp4 erzeugen")
    ap.add_argument("--check", action="store_true", help="Layout der Beschriftung prüfen")
    ap.add_argument("--out", default=os.path.join(HERE, "film.mp4"))
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 1)
    ap.add_argument("--manifest", action="store_true")
    a = ap.parse_args()
    if a.manifest:
        return manifest()
    if a.check:
        sys.exit(1 if pruefe_layout() else 0)
    if a.still:
        for s in a.still.split(","):
            i = int(round(float(s) * FPS))
            Image.fromarray(frame(i, a.clean)).save(os.path.join(HERE, f"probe-{s}.png"))
        return
    if a.standbild:
        Image.fromarray(frame(int(round(T_STANDBILD * FPS)), a.clean)).save(os.path.join(HERE, "standbild.png"), optimize=True)
        return
    if a.gif:
        return render_gif(a.out, os.path.join(HERE, "film.gif"))
    render_video(a.out, a.jobs, a.clean)

def manifest():
    """Jede sichtbare Zahl mit Quelle (fuer die Rueckmeldung)."""
    t0 = 0.0; zeiten = {}
    for n, d in SZENEN: zeiten[n] = (round(t0, 2), round(t0 + d, 2)); t0 += d
    out = dict(gesamt_s=round(NFRAMES / FPS, 2), frames=NFRAMES, rechnerlast_davor=dict(erstlauf=LAST[0], folgelauf=LAST[1]), szenen=zeiten, befehl1=CMD1, befehl2=CMD2,
               lauf1=dict(kopf=R1["kopf"], quellen={q["name"]: q["dauer"] for q in R1["quellen"]}),
               lauf2=dict(kopf=R2["kopf"], quellen={q["name"]: q["dauer"] for q in R2["quellen"]}),
               fehler=dict(kopf=RF["kopf"], quellen={q["name"]: q["dauer"] for q in RF["quellen"]}),
               vollumfang=dict(n=V_N, erst_s=V_SEK1, folge_s=V_SEK2, wertabgleich=WA),
               tests=TESTS, dbtests=DBT, pg=PGV, lizenzen=LIZ)
    print(json.dumps(out, ensure_ascii=False, indent=1))

if __name__ == "__main__":
    main()
