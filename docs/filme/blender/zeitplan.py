# Gemeinsamer Zeitplan fuer Blender-Szene und 2D-Overlay.
# Alle Zeiten in Sekunden Film, FPS 30. Kamera orthografisch, Ursprung = Campusmitte (332600, 5809900).
import math

FPS = 30
W, H = 1920, 1080

# Echte Laufzeiten je Quelle, Bericht 20261107T043632Z (JSON laufzeit_s)
LZ = {"alkis_gebaeude_thb": 4.38, "gemeinden_lgb": 5.13, "kreise_lgb": 1.99,
      "bevoelkerung_gemeinden": 1.47, "flaeche_gemeinden": 4.60, "inkar_gemeinden": 127.78}

# Phasen (Sekunden Film)
K0 = 1.2;  K1 = K0 + LZ["kreise_lgb"]          # Kreise zeichnen sich, Echtzeit
G0 = 3.6;  G1 = G0 + LZ["gemeinden_lgb"]       # Gemeinden fuellen sich, Echtzeit
I0 = 9.4;  I1 = 13.4                           # INKAR, Zeitraffer 127,78 s -> 4 s
Z0 = 13.8; Z1 = 18.6                           # Fahrt hinunter
T0_TILT = 16.4
A0 = 18.9; A1 = A0 + LZ["alkis_gebaeude_thb"]  # Gebaeude, Echtzeit
F0 = 25.6; F1 = 28.2                           # Folgelauf: Abtastung Campus
P0 = 28.2; P1 = 31.4                           # Fahrt hinauf
S0_SCAN = 29.6; S1_SCAN = 31.8                 # Abtastung Land
E0 = 33.7; ENDE = 39.1                         # Schlussbild (Ergebnis des Folgelaufs steht ab S1_SCAN gut 1,5 s)
N = int(round(ENDE * FPS))

GROW = 0.5      # s, Wachsen eines Gebaeudes
FADE_ROT = 0.7  # s, rot (neu) -> Endfarbe

# Brandenburg-Rahmen (lokal), aus kreise.json bbox: E 250152..483778, N 5690475..5935134
BB_CX = (250152 + 483778) / 2 - 332600
BB_CY = (5690475 + 5935134) / 2 - 5809900
S_STATE = 1920 * 252.0            # m Bildbreite: 245 km Land in ~970 px Hoehe
STATE_SX = 640                    # Bild-x der Landesmitte
T_STATE = (BB_CX + (W / 2 - STATE_SX) * S_STATE / W, BB_CY - 6 * S_STATE / W)
S_CAMPUS = 2500.0
CAMPUS_SX = 0.36                  # Campusmitte bei 40 % der Bildbreite
TILT_CAMPUS = 54.0
AZ_CAMPUS = 14.0


def clamp(x, a=0.0, b=1.0):
    return a if x < a else b if x > b else x


def ease(x):
    x = clamp(x)
    return x * x * (3 - 2 * x)


def ease2(x):  # sanfter, fuer Kamera
    x = clamp(x)
    return x * x * x * (x * (6 * x - 15) + 10)


def seg(t, a, b):
    return clamp((t - a) / (b - a)) if b > a else float(t >= a)


def lerp(a, b, x):
    return a + (b - a) * x


def _ziel(px, py, s, az):
    a = math.radians(az)
    return (-(px * s) * math.cos(a) - (py * s) * math.sin(a), (px * s) * math.sin(a) - (py * s) * math.cos(a))


def kamera(t):
    """(Tx, Ty, S, tilt_deg, az_deg) — Zielpunkt am Boden, Bildbreite in m, Neigung, Blickrichtung."""
    s_a = S_STATE * 1.0
    s_b = S_STATE * 0.965
    if t < Z0:
        s = lerp(s_a, s_b, t / Z0)
        return (T_STATE[0], T_STATE[1], s, 0.0, 0.0)
    if t < P0:
        if t < Z1:
            x = ease2(seg(t, Z0, Z1))
            s = math.exp(lerp(math.log(s_b), math.log(S_CAMPUS), x))
            p0 = ((0 - T_STATE[0]) / s_b, (0 - T_STATE[1]) / s_b)
            p1 = (CAMPUS_SX - 0.5, 0.0)
            # Campus wandert in Bildposition, Zoom zieht exponentiell
            y = ease2(seg(t, Z0, Z1 - 0.6))
            px, py = lerp(p0[0], p1[0], y), lerp(p0[1], p1[1], y)
            tilt = TILT_CAMPUS * ease2(seg(t, T0_TILT, Z1 + 0.3))
            az = AZ_CAMPUS * ease2(seg(t, T0_TILT, Z1 + 0.3))
            return (*_ziel(px, py, s, az), s, tilt, az)
        # Halten mit leichter Drehung
        x = seg(t, Z1, P0)
        tilt = TILT_CAMPUS * ease2(seg(t, T0_TILT, Z1 + 0.3))
        az = AZ_CAMPUS * ease2(seg(t, T0_TILT, Z1 + 0.3))
        if t > Z1 + 0.3:
            az = lerp(AZ_CAMPUS, AZ_CAMPUS + 9.0, seg(t, Z1 + 0.3, P0))
        s = lerp(S_CAMPUS, S_CAMPUS * 0.92, seg(t, Z1, P0))
        p1 = (CAMPUS_SX - 0.5, 0.0)
        return (*_ziel(p1[0], p1[1], s, az), s, tilt, az)
    # Fahrt hinauf und Schluss
    s_c = S_CAMPUS * 0.92
    x = ease2(seg(t, P0, P1))
    s = math.exp(lerp(math.log(s_c), math.log(S_STATE), x))
    p1 = (CAMPUS_SX - 0.5, 0.0)
    pS = ((0 - T_STATE[0]) / S_STATE, (0 - T_STATE[1]) / S_STATE)
    y = ease2(seg(t, P0 + 0.4, P1))
    px, py = lerp(p1[0], pS[0], y), lerp(p1[1], pS[1], y)
    tilt = TILT_CAMPUS * (1 - ease2(seg(t, P0, P0 + 1.8)))
    az = (AZ_CAMPUS + 9.0) * (1 - ease2(seg(t, P0, P0 + 1.8)))
    return (*_ziel(px, py, s, az), s, tilt, az)


def achsen(tilt, az):
    """right, up, forward als 3er-Tupel (Welt)."""
    th, ph = math.radians(tilt), math.radians(az)
    f = (math.sin(th) * math.sin(ph), math.sin(th) * math.cos(ph), -math.cos(th))
    r = (math.cos(ph), -math.sin(ph), 0.0)
    u = (r[1] * f[2] - r[2] * f[1], r[2] * f[0] - r[0] * f[2], r[0] * f[1] - r[1] * f[0])
    return r, u, f


def projektion(t):
    """Funktion (x,y,z) -> (px,py) fuer das Overlay, exakt wie die Blender-Kamera."""
    Tx, Ty, S, tilt, az = kamera(t)
    r, u, f = achsen(tilt, az)
    k = W / S

    def p(x, y, z=0.0):
        dx, dy, dz = x - Tx, y - Ty, z
        xc = dx * r[0] + dy * r[1] + dz * r[2]
        yc = dx * u[0] + dy * u[1] + dz * u[2]
        return (W / 2 + xc * k, H / 2 - yc * k)
    return p, S, tilt


def sonne(t):
    """Hoehe (Grad), Azimut (Grad, Richtung AUS der das Licht kommt, 0=N, 90=O), Staerke, Farbe linear."""
    x = ease(seg(t, Z0 + 1.0, A0)) * (1 - ease(seg(t, P0 + 0.5, P1)))
    elev = lerp(38.0, 20.0, x)
    stark = lerp(3.06, 4.9, x)
    farbe = (1.0, lerp(0.98, 0.86, x), lerp(0.95, 0.70, x))
    emit = lerp(0.20, 0.08, x)
    return elev, 235.0, stark, farbe, emit


def boden(t):
    """0 = Gemeinden in Klassenfarbe, 1 = zurueckgenommen auf Papier (Campus)."""
    if t < P0:
        return 0.82 * ease(seg(t, Z0 + 2.2, Z1 - 0.4))
    return 0.82 * (1 - ease(seg(t, P0 + 0.6, P1 - 0.4)))


def scan_x(t):
    """Abtaststrahl (Welt-x) und Breite; ausserhalb: weit weg."""
    if F0 <= t <= F1:
        return lerp(-900.0, 900.0, ease(seg(t, F0 + 0.2, F1 - 0.1))), 30.0
    if S0_SCAN <= t <= S1_SCAN:
        return lerp(-95000.0, 170000.0, ease(seg(t, S0_SCAN, S1_SCAN))), 9000.0
    return 1e9, 1.0
