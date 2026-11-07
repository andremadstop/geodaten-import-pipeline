# Blender-Szene "Der Campus waechst aus den Daten" (headless, Eevee).
# Aufruf: flatpak run org.blender.Blender -b --python <abs. Pfad>/szene.py -- --prep <prep> --aus <frames> [--zeiten 6,22.5] [--von F --bis F]
#   oder: python szene.py ... (Python-Modul bpy 5.1.2)
# Liest <prep>/*.json (siehe prep.py), schreibt <aus>/b_NNNN.png.
import sys, os, json, math, time, argparse
import bpy
from mathutils import Vector, Matrix

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HIER)
import zeitplan as Z

ap = argparse.ArgumentParser()
ap.add_argument("--zeiten", default="")
ap.add_argument("--pct", type=int, default=100)
ap.add_argument("--von", type=int, default=0)
ap.add_argument("--bis", type=int, default=Z.N - 1)
ap.add_argument("--samples", type=int, default=16)
ap.add_argument("--aus", default="berichte/film-blender/frames")
ap.add_argument("--prep", default="berichte/film-blender/prep")
args = ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:])

FPS = Z.FPS


def srgb(h):
    h = h.lstrip("#")
    c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return tuple((x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4) for x in c) + (1.0,)


PAPIER = srgb("#ebe6db")
ROT = srgb("#ad2a24")
HELL = srgb("#f7f4ec")
KLASSEN = [srgb(c) for c in ("#d5ddd7", "#aac3c1", "#78a1a6", "#4a7b85", "#2a5d6b")]
PUTZ = srgb("#ebe4d6")
SCHEMA = srgb("#b4cbcb")
KACHEL = srgb("#2a5d6b")

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.render.engine = "BLENDER_EEVEE"
sc.render.resolution_x, sc.render.resolution_y = Z.W, Z.H
sc.render.resolution_percentage = args.pct
sc.render.fps = FPS
sc.eevee.taa_render_samples = args.samples
try:
    sc.eevee.use_raytracing = False
except Exception:
    pass
try:
    sc.eevee.shadow_resolution_scale = 1.0
except Exception:
    pass
sc.view_settings.view_transform = "Standard"
sc.view_settings.look = "None"
sc.render.image_settings.file_format = "PNG"
sc.render.image_settings.color_mode = "RGB"
sc.render.film_transparent = False

# Welt: kuehles Umgebungslicht
world = bpy.data.worlds.new("Welt")
sc.world = world
world.use_nodes = True
bg = world.node_tree.nodes["Background"]
bg.inputs[0].default_value = (0.62, 0.74, 0.95, 1)
bg.inputs[1].default_value = 0.22

# ---------- Hilfen fuer Materialien ----------
WERTE = {}  # Name -> Liste von Value-Nodes (pro Frame gesetzt)


def wert(nt, name, x, y):
    n = nt.nodes.new("ShaderNodeValue")
    n.location = (x, y)
    n.label = name
    WERTE.setdefault(name, []).append(n)
    return n


def attr(nt, name, x, y):
    n = nt.nodes.new("ShaderNodeAttribute")
    n.attribute_name = name
    n.attribute_type = "GEOMETRY"
    n.location = (x, y)
    return n


def math_(nt, op, a, b=None, clamp=False):
    n = nt.nodes.new("ShaderNodeMath")
    n.operation = op
    n.use_clamp = clamp
    for i, v in enumerate((a, b)):
        if v is None:
            continue
        if isinstance(v, (int, float)):
            n.inputs[i].default_value = v
        else:
            nt.links.new(v, n.inputs[i])
    return n.outputs[0]


def mix(nt, fac, a, b):
    n = nt.nodes.new("ShaderNodeMix")
    n.data_type = "RGBA"
    for sock, v in ((n.inputs[0], fac), (n.inputs[6], a), (n.inputs[7], b)):
        if isinstance(v, (int, float)):
            sock.default_value = v
        elif isinstance(v, tuple):
            sock.default_value = v
        else:
            nt.links.new(v, sock)
    return n.outputs[2]


def band(nt):
    """Abtaststrahl: exp(-((x - sx)/w)^2)"""
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(geo.outputs["Position"], sep.inputs[0])
    sx = wert(nt, "scan_x", -600, -600).outputs[0]
    sw = wert(nt, "scan_w", -600, -700).outputs[0]
    d = math_(nt, "DIVIDE", math_(nt, "SUBTRACT", sep.outputs[0], sx), sw)
    return math_(nt, "EXPONENT", math_(nt, "MULTIPLY", math_(nt, "MULTIPLY", d, d), -1.0))


def ausgabe(nt, farbe, emit_faktor=1.0, emit_extra=None):
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    dif = nt.nodes.new("ShaderNodeBsdfDiffuse")
    dif.inputs["Roughness"].default_value = 1.0
    nt.links.new(farbe, dif.inputs["Color"])
    em = nt.nodes.new("ShaderNodeEmission")
    nt.links.new(farbe, em.inputs["Color"])
    k = wert(nt, "emit", -200, -400).outputs[0]
    ks = math_(nt, "MULTIPLY", k, emit_faktor)
    if emit_extra is not None:
        ks = math_(nt, "ADD", ks, emit_extra)
    nt.links.new(ks, em.inputs["Strength"])
    add = nt.nodes.new("ShaderNodeAddShader")
    nt.links.new(dif.outputs[0], add.inputs[0])
    nt.links.new(em.outputs[0], add.inputs[1])
    nt.links.new(add.outputs[0], out.inputs[0])


def mat_papier():
    m = bpy.data.materials.new("Papier")
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    rgb = nt.nodes.new("ShaderNodeRGB")
    rgb.outputs[0].default_value = PAPIER
    c = mix(nt, math_(nt, "MULTIPLY", band(nt), 0.55), rgb.outputs[0], HELL)
    ausgabe(nt, c)
    return m


def mat_gemeinden():
    m = bpy.data.materials.new("Gemeinden")
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    F = wert(nt, "frame", -900, 0).outputs[0]
    t0 = attr(nt, "t0", -900, 200).outputs["Fac"]
    kc = attr(nt, "kcol", -900, 400).outputs["Color"]
    x = math_(nt, "DIVIDE", math_(nt, "SUBTRACT", F, t0), Z.FADE_ROT * FPS, clamp=True)
    da = math_(nt, "GREATER_THAN", math_(nt, "SUBTRACT", F, t0), -0.001)
    c1 = mix(nt, x, ROT, kc)
    c2 = mix(nt, da, PAPIER, c1)
    c2b = mix(nt, wert(nt, "boden", -600, -300).outputs[0], c2, PAPIER)
    c3 = mix(nt, math_(nt, "MULTIPLY", band(nt), 0.6), c2b, HELL)
    ausgabe(nt, c3)
    return m


def mat_gebaeude():
    m = bpy.data.materials.new("Gebaeude")
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    F = wert(nt, "frame", -900, 0).outputs[0]
    t0 = attr(nt, "t0", -900, 200).outputs["Fac"]
    bek = attr(nt, "bek", -900, 400).outputs["Fac"]
    base = mix(nt, bek, SCHEMA, PUTZ)
    x = math_(nt, "DIVIDE", math_(nt, "SUBTRACT", F, math_(nt, "ADD", t0, Z.GROW * FPS)), Z.FADE_ROT * FPS, clamp=True)
    c1 = mix(nt, x, ROT, base)
    b = band(nt)
    c2 = mix(nt, math_(nt, "MULTIPLY", b, 0.85), c1, srgb("#dff0f0"))
    ausgabe(nt, c2, 0.6, math_(nt, "MULTIPLY", b, 0.8))
    return m


def mat_kachel():
    m = bpy.data.materials.new("Kachel")
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    rgb = nt.nodes.new("ShaderNodeRGB")
    rgb.outputs[0].default_value = KACHEL
    ausgabe(nt, rgb.outputs[0], 1.0, 0.25)
    return m


# ---------- Geometry Nodes: Wachsen ----------
def gn_wachsen(dur_frames):
    ng = bpy.data.node_groups.new("Wachsen", "GeometryNodeTree")
    ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    n = ng.nodes
    gi = n.new("NodeGroupInput")
    go = n.new("NodeGroupOutput")
    st = n.new("GeometryNodeInputSceneTime")
    na = n.new("GeometryNodeInputNamedAttribute")
    na.data_type = "FLOAT"
    na.inputs["Name"].default_value = "t0"
    pos = n.new("GeometryNodeInputPosition")
    sep = n.new("ShaderNodeSeparateXYZ")
    ng.links.new(pos.outputs[0], sep.inputs[0])

    def m(op, a, b=None, clamp=False):
        x = n.new("ShaderNodeMath")
        x.operation = op
        x.use_clamp = clamp
        for i, v in enumerate((a, b)):
            if v is None:
                continue
            if isinstance(v, (int, float)):
                x.inputs[i].default_value = v
            else:
                ng.links.new(v, x.inputs[i])
        return x.outputs[0]
    g = m("DIVIDE", m("SUBTRACT", st.outputs["Frame"], na.outputs["Attribute"]), float(dur_frames), clamp=True)
    e = m("MULTIPLY", m("MULTIPLY", g, g), m("SUBTRACT", 3.0, m("MULTIPLY", g, 2.0)))
    an = m("GREATER_THAN", m("SUBTRACT", st.outputs["Frame"], na.outputs["Attribute"]), 0.0)
    z = m("ADD", m("MULTIPLY", sep.outputs[2], e), m("MULTIPLY", m("SUBTRACT", 1.0, an), -30.0))
    comb = n.new("ShaderNodeCombineXYZ")
    ng.links.new(sep.outputs[0], comb.inputs[0])
    ng.links.new(sep.outputs[1], comb.inputs[1])
    ng.links.new(z, comb.inputs[2])
    sp = n.new("GeometryNodeSetPosition")
    ng.links.new(gi.outputs[0], sp.inputs["Geometry"])
    ng.links.new(comb.outputs[0], sp.inputs["Position"])
    ng.links.new(sp.outputs[0], go.inputs[0])
    return ng


def obj_aus_mesh(name, verts, faces, mat):
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.validate()
    ob = bpy.data.objects.new(name, me)
    sc.collection.objects.link(ob)
    me.materials.append(mat)
    return ob, me


def flaeche_vz(r):
    a = 0.0
    for i in range(len(r)):
        x1, y1 = r[i]
        x2, y2 = r[(i + 1) % len(r)]
        a += x1 * y2 - x2 * y1
    return a / 2


# ---------- Daten laden ----------
P = args.prep
gem = json.load(open(os.path.join(P, "gemeinden.json")))
geb = json.load(open(os.path.join(P, "gebaeude.json")))
meta = json.load(open(os.path.join(P, "meta.json")))

# Papier-Grund
obj_aus_mesh("Grund", [(-1.5e6, -1.5e6, 0), (1.5e6, -1.5e6, 0), (1.5e6, 1.5e6, 0), (-1.5e6, 1.5e6, 0)], [(0, 1, 2, 3)], mat_papier())

# Gemeinden: eine Mesh, Flaechenattribute t0 (Frame) und kcol
V, Fc, T0f, KC = [], [], [], []
for g in gem:
    off = len(V)
    V.extend([(x, y, 0.3) for x, y in g["v"]])
    t0 = (Z.G0 + g["i"] / len(gem) * Z.LZ["gemeinden_lgb"]) * FPS
    for a, b, c in g["f"]:
        Fc.append((a + off, b + off, c + off))
        T0f.append(t0)
        KC.append(KLASSEN[g["klasse"]])
ob_g, me_g = obj_aus_mesh("Gemeinden", V, Fc, mat_gemeinden())
# Dreiecke aufwaerts
for p in me_g.polygons:
    pass
a = me_g.attributes.new("t0", "FLOAT", "FACE")
a.data.foreach_set("value", T0f)
a = me_g.attributes.new("kcol", "FLOAT_COLOR", "FACE")
a.data.foreach_set("color", [c for col in KC for c in col])

# Gebaeude: eine Mesh, Punktattribute t0 (Frame Start Wachsen), bek
d = Z.LZ["alkis_gebaeude_thb"] / 9.0
pro_kachel = {}
for b in geb:
    pro_kachel.setdefault(b["kachel"], []).append(b)
V, Fc, T0v, BEK = [], [], [], []
for k, liste in pro_kachel.items():
    for m_i, b in enumerate(liste):
        t0 = (Z.A0 + k * d + (m_i / len(liste)) * d * 0.9) * FPS
        b["t0"] = t0
        h = (b["gs"] * 3.0 if b["gs"] else 3.0) + 0.3
        bek = 1.0 if b["gs"] else 0.0
        ringe = b["ringe"]
        # Dach: Dreiecke aus prep (Ecken in Ringreihenfolge)
        off = len(V)
        for x, y in b["v"]:
            V.append((x, y, h))
        for tri in b["f"]:
            p = [b["v"][i] for i in tri]
            nz = (p[1][0] - p[0][0]) * (p[2][1] - p[0][1]) - (p[1][1] - p[0][1]) * (p[2][0] - p[0][0])
            Fc.append(tuple(i + off for i in (tri if nz > 0 else tri[::-1])))
        # Waende
        for ri, r in enumerate(ringe):
            ccw = flaeche_vz(r) > 0
            aussen = ri == 0
            rr = r if (ccw == aussen) else r[::-1]
            o2 = len(V)
            for x, y in rr:
                V.append((x, y, 0.0))
                V.append((x, y, h))
            n = len(rr)
            for i in range(n):
                j = (i + 1) % n
                Fc.append((o2 + 2 * i, o2 + 2 * j, o2 + 2 * j + 1, o2 + 2 * i + 1))
        nv = len(V) - off
        T0v.extend([t0] * nv)
        BEK.extend([bek] * nv)
ob_b, me_b = obj_aus_mesh("Gebaeude", V, Fc, mat_gebaeude())
a = me_b.attributes.new("t0", "FLOAT", "POINT")
a.data.foreach_set("value", T0v)
a = me_b.attributes.new("bek", "FLOAT", "POINT")
a.data.foreach_set("value", BEK)
for p in me_b.polygons:
    p.use_smooth = False
wachsen_b = gn_wachsen(Z.GROW * FPS)
mod = ob_b.modifiers.new("Wachsen", "NODES")
mod.node_group = wachsen_b

# Kacheln: Rahmenstreifen 3 m, Hoehe 0.5 m ueber Gemeindeflaeche
V, Fc, T0v = [], [], []
B = 1.5
for k, (x0, y0, x1, y1) in enumerate(meta["kacheln"]):
    t0 = (Z.A0 + k * d) * FPS - 6
    for (ax, ay, bx, by) in ((x0, y0, x1, y0), (x1, y0, x1, y1), (x1, y1, x0, y1), (x0, y1, x0, y0)):
        if ax == bx:
            q = [(ax - B, min(ay, by) - B), (ax + B, min(ay, by) - B), (ax + B, max(ay, by) + B), (ax - B, max(ay, by) + B)]
        else:
            q = [(min(ax, bx) - B, ay - B), (max(ax, bx) + B, ay - B), (max(ax, bx) + B, ay + B), (min(ax, bx) - B, ay + B)]
        o = len(V)
        V.extend([(x, y, 0.8) for x, y in q])
        Fc.append((o, o + 1, o + 2, o + 3))
        T0v.extend([t0] * 4)
ob_k, me_k = obj_aus_mesh("Kacheln", V, Fc, mat_kachel())
a = me_k.attributes.new("t0", "FLOAT", "POINT")
a.data.foreach_set("value", T0v)
wk = gn_wachsen(4)
mod = ob_k.modifiers.new("Wachsen", "NODES")
mod.node_group = wk

# Kamera
cd = bpy.data.cameras.new("Kamera")
cd.type = "ORTHO"
cam = bpy.data.objects.new("Kamera", cd)
sc.collection.objects.link(cam)
sc.camera = cam
cd.clip_start = 50.0
DIST = 4000.0
cd.clip_end = DIST * 2.4

# Sonne
ld = bpy.data.lights.new("Sonne", "SUN")
ld.angle = 0.0
ld.use_shadow_jitter = False
ld.shadow_maximum_resolution = 0.01
try:
    ld.use_shadow = True
except Exception:
    pass
sun = bpy.data.objects.new("Sonne", ld)
sc.collection.objects.link(sun)


def setze(t):
    Tx, Ty, S, tilt, az = Z.kamera(t)
    r, u, f = Z.achsen(tilt, az)
    cam.location = Vector((Tx - f[0] * DIST, Ty - f[1] * DIST, 0.0 - f[2] * DIST))
    M = Matrix((r, u, (-f[0], -f[1], -f[2]))).transposed()
    cam.rotation_euler = M.to_euler("XYZ")
    cd.ortho_scale = S
    elev, saz, stark, farbe, emit = Z.sonne(t)
    e, a_ = math.radians(elev), math.radians(saz)
    von = Vector((math.sin(a_) * math.cos(e), math.cos(a_) * math.cos(e), math.sin(e)))
    sun.rotation_euler = (-von).to_track_quat("-Z", "Y").to_euler()
    ld.energy = stark
    ld.color = farbe
    sx, sw = Z.scan_x(t)
    for n in WERTE.get("scan_x", []):
        n.outputs[0].default_value = sx
    for n in WERTE.get("scan_w", []):
        n.outputs[0].default_value = sw
    for n in WERTE.get("emit", []):
        n.outputs[0].default_value = emit
    for n in WERTE.get("boden", []):
        n.outputs[0].default_value = Z.boden(t)
    for n in WERTE.get("frame", []):
        n.outputs[0].default_value = t * FPS


def render(frame, pfad):
    t = frame / FPS
    sc.frame_set(frame)
    setze(t)
    sc.render.filepath = pfad
    bpy.ops.render.render(write_still=True)


os.makedirs(args.aus, exist_ok=True)
t_start = time.time()
if args.zeiten:
    for s in args.zeiten.split(","):
        fr = int(round(float(s) * FPS))
        render(fr, os.path.join(args.aus, "b_%04d.png" % fr))
        print("FERTIG", s, round(time.time() - t_start, 1), flush=True)
else:
    STATISCH = int(round((Z.S1_SCAN + 0.1) * FPS))  # danach steht das Bild
    for fr in range(args.von, min(args.bis, STATISCH) + 1):
        pf = os.path.join(args.aus, "b_%04d.png" % fr)
        if os.path.exists(pf):
            continue
        render(fr, pf)
        if fr % 30 == 0:
            print("FRAME", fr, round(time.time() - t_start, 1), flush=True)
print("GESAMT", round(time.time() - t_start, 1))
