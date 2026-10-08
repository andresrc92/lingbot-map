"""Parametric object library for scene.yaml `objects:` entries (runs inside Blender).

Convention for furniture: `pos` is the footprint centre [x, y] (or [x, y, z] where noted),
`facing` is the direction a person using it looks, in degrees (0 = +X / east, 90 = +Y / north).
Internally each piece is built in a local frame whose front is +X, width along Y, back at -X,
then parented to an Empty rotated by `facing`. Every type is documented in docs/scene_spec.md.

Add a new type: write `def t_<type>(s, cx)` returning nothing, register it in TYPES, document it
in docs/scene_spec.md. Keep geometry simple and bevelled: realism comes from materials + light.
"""
import math
import random

from mathutils import Vector

from helpers import box, cylinder, group, image_plane, light, parent_all, shade_smooth

import bmesh
import bpy


class Ctx:
    def __init__(self, M, coll, lights, ceiling):
        self.M, self.coll, self.lights, self.H = M, coll, lights, ceiling

    def mat(self, s, key="material", default=None):
        n = s.get(key, default)
        if n not in self.M:
            raise KeyError(f"object {s.get('name', s['type'])!r}: unknown material {n!r}")
        return self.M[n]


def _name(s, default):
    return s.get("name", default)


def _light(cx, s, name, loc, kind="POINT", **kw):
    if not s:
        return None
    return light(name, kind, loc, s.get("power", 60), tuple(s.get("color", (1.0, 0.75, 0.5))), cx.lights,
                 size=s.get("size", kw.get("size", 0.05)), rot=kw.get("rot", (0, 0, 0)), spot_deg=kw.get("spot_deg"))


# ---- generic -------------------------------------------------------------------------------
def t_box(s, cx):
    o = box(_name(s, "Box"), s["min"], s["max"], cx.mat(s), cx.coll, bevel=s.get("bevel", 0.0), segments=s.get("segments", 3))
    if s.get("rotate"):
        o.rotation_euler = tuple(math.radians(a) for a in s["rotate"])


def t_cylinder(s, cx):
    o = cylinder(_name(s, "Cylinder"), s["pos"], s["radius"], s["height"], cx.mat(s), cx.coll,
                 verts=s.get("verts", 32), r2=s.get("radius_top"), cap=s.get("cap", True))
    if s.get("rotate"):
        o.rotation_euler = tuple(math.radians(a) for a in s["rotate"])
    if s.get("solidify"):
        o.modifiers.new("Solid", "SOLIDIFY").thickness = s["solidify"]


def t_image_plane(s, cx):
    image_plane(_name(s, "Image"), s["pos"], s["size"], s["facing"], cx.mat(s), cx.coll)


def t_painting(s, cx):
    """Framed picture on a wall. pos = centre [x,y,z] ON the wall face, facing = +X/-X/+Y/-Y (into the room)."""
    w, h = s["size"]
    d, b = s.get("depth", 0.03), s.get("border", 0.025)
    x, y, z = s["pos"]
    ax = s["facing"]
    sign = 1 if ax[0] == "+" else -1
    if ax[1] == "X":
        mn, mx = (x + (0 if sign > 0 else -d), y - w / 2 - b, z - h / 2 - b), (x + (d if sign > 0 else 0), y + w / 2 + b, z + h / 2 + b)
        front = (x + sign * (d + 0.001), y, z)
    else:
        mn, mx = (x - w / 2 - b, y + (0 if sign > 0 else -d), z - h / 2 - b), (x + w / 2 + b, y + (d if sign > 0 else 0), z + h / 2 + b)
        front = (x, y + sign * (d + 0.001), z)
    box(_name(s, "Painting") + " frame", mn, mx, cx.mat(s, "frame_material"), cx.coll, bevel=0.004)
    image_plane(_name(s, "Painting"), front, (w, h), ax, cx.mat(s), cx.coll)


# ---- seating -------------------------------------------------------------------------------
def t_sofa(s, cx):
    """Sofa, optionally L-shaped. length (along the back), depth, chaise: {side: left|right,
    width, extra} (extra = how far the chaise sticks out beyond the seat front),
    arms: [left, right] booleans (left/right as seen by the sitter), seat_cushions, back_cushions."""
    L, Dp = s["length"], s.get("depth", 0.93)
    g = group(_name(s, "Sofa"), cx.coll, (*s["pos"], 0), s.get("facing", 0))
    M, legm = cx.mat(s), cx.mat(s, "leg_material", "darkwood")
    x0, x1 = -Dp / 2, Dp / 2              # local: front at +X, back at -X
    y0, y1 = -L / 2, L / 2                # sitter's right at -Y, left at +Y
    parts = [box("Sofa base", (x0, y0, 0.10), (x1, y1, 0.30), M, cx.coll, bevel=0.02)]
    arm_w = 0.21
    arms = s.get("arms", [True, True])
    ya, yb = y0 + (arm_w if arms[1] else 0), y1 - (arm_w if arms[0] else 0)
    ch = s.get("chaise")
    if ch:
        cw, ce = ch.get("width", Dp), ch.get("extra", 0.7)
        cy0, cy1 = (y0, y0 + cw) if ch["side"] == "right" else (y1 - cw, y1)
        parts.append(box("Chaise base", (x1 - 0.02, cy0, 0.10), (x1 + ce, cy1, 0.30), M, cx.coll, bevel=0.02))
        parts.append(box("Chaise seat", (x0 + 0.22, cy0 + 0.01, 0.30), (x1 + ce - 0.01, cy1 - 0.01, 0.47), M, cx.coll, bevel=0.05, segments=5))
        if ch["side"] == "right":
            ya = cy1
        else:
            yb = cy0
        for ly in (cy0 + 0.06, cy1 - 0.06):
            parts.append(cylinder("Chaise leg", (x1 + ce - 0.06, ly, 0.05), 0.02, 0.10, legm, cx.coll, verts=12))
    n = s.get("seat_cushions", 3)
    for i in range(n):
        a, b = ya + i * (yb - ya) / n, ya + (i + 1) * (yb - ya) / n
        parts.append(box(f"Sofa seat {i}", (x0 + 0.22, a + 0.005, 0.30), (x1 - 0.01, b - 0.005, 0.47), M, cx.coll, bevel=0.05, segments=5))
    parts.append(box("Sofa back", (x0, y0, 0.30), (x0 + 0.22, y1, 0.72), M, cx.coll, bevel=0.04, segments=4))
    nb = s.get("back_cushions", 4)
    by0, by1 = y0 + (arm_w if arms[1] else 0), y1 - (arm_w if arms[0] else 0)
    for i in range(nb):
        a, b = by0 + i * (by1 - by0) / nb, by0 + (i + 1) * (by1 - by0) / nb
        c = box(f"Sofa back cushion {i}", (x0 + 0.20, a + 0.01, 0.44), (x0 + 0.40, b - 0.01, 0.90), M, cx.coll, bevel=0.07, segments=6)
        c.rotation_euler = (0, math.radians(10), 0)
        parts.append(c)
    for side, (a, b) in ((0, (y1 - arm_w, y1)), (1, (y0, y0 + arm_w))):
        if arms[side]:
            parts.append(box("Sofa arm", (x0, a, 0.10), (x1, b, 0.62), M, cx.coll, bevel=0.06, segments=5))
    for lx in (x0 + 0.06, x1 - 0.06):
        for ly in (y0 + 0.06, y1 - 0.06):
            parts.append(cylinder("Sofa leg", (lx, ly, 0.05), 0.02, 0.10, legm, cx.coll, verts=12))
    parent_all(g, parts)


def t_armchair(s, cx):
    g = group(_name(s, "Armchair"), cx.coll, (*s["pos"], 0), s.get("facing", 0))
    M, legm = cx.mat(s), cx.mat(s, "leg_material", "darkwood")
    parts = [
        box("Armchair base", (-0.40, -0.40, 0.12), (0.40, 0.40, 0.30), M, cx.coll, bevel=0.03),
        box("Armchair seat", (-0.33, -0.28, 0.30), (0.30, 0.28, 0.45), M, cx.coll, bevel=0.05, segments=5),
        box("Armchair back", (-0.42, -0.40, 0.30), (-0.24, 0.40, 0.82), M, cx.coll, bevel=0.06, segments=5),
        box("Armchair arm L", (-0.42, 0.27, 0.12), (0.40, 0.42, 0.62), M, cx.coll, bevel=0.05, segments=5),
        box("Armchair arm R", (-0.42, -0.42, 0.12), (0.40, -0.27, 0.62), M, cx.coll, bevel=0.05, segments=5),
        box("Armchair cushion", (-0.26, -0.22, 0.45), (-0.12, 0.22, 0.78), M, cx.coll, bevel=0.06, segments=5),
    ]
    for (x, y) in [(-0.34, -0.34), (-0.34, 0.34), (0.34, -0.34), (0.34, 0.34)]:
        parts.append(cylinder("Armchair leg", (x, y, 0.06), 0.018, 0.12, legm, cx.coll, verts=10))
    parent_all(g, parts)


def t_chair(s, cx):
    g = group(_name(s, "Chair"), cx.coll, (*s["pos"], 0), s.get("facing", 0))
    M = cx.mat(s)
    parts = [box("Chair seat", (-0.21, -0.21, 0.44), (0.21, 0.21, 0.48), M, cx.coll, bevel=0.005),
             box("Chair back", (-0.23, -0.21, 0.48), (-0.20, 0.21, 0.92), M, cx.coll, bevel=0.005)]
    for (lx, ly) in [(-0.19, -0.19), (0.19, -0.19), (-0.19, 0.19), (0.19, 0.19)]:
        parts.append(box("Chair leg", (lx - 0.015, ly - 0.015, 0), (lx + 0.015, ly + 0.015, 0.44), M, cx.coll))
    parent_all(g, parts)


# ---- tables / media ------------------------------------------------------------------------
def t_table(s, cx):
    """Table from min/max footprint [x, y], height, top thickness, optional low shelf, square legs."""
    (x0, y0), (x1, y1) = s["min"], s["max"]
    h, th, M = s.get("height", 0.75), s.get("top", 0.04), cx.mat(s)
    n = _name(s, "Table")
    box(n + " top", (x0, y0, h - th), (x1, y1, h), M, cx.coll, bevel=0.005)
    if s.get("shelf"):
        box(n + " shelf", (x0 + 0.04, y0 + 0.04, 0.10), (x1 - 0.04, y1 - 0.04, 0.12), M, cx.coll, bevel=0.004)
    lw = s.get("leg", 0.04) / 2
    for (x, y) in [(x0 + 0.03, y0 + 0.03), (x1 - 0.03, y0 + 0.03), (x0 + 0.03, y1 - 0.03), (x1 - 0.03, y1 - 0.03)]:
        box(n + " leg", (x - lw, y - lw, 0), (x + lw, y + lw, h - th), M, cx.coll)


def t_tv(s, cx):
    """Flat TV on a stand. pos = screen centre [x, y, z]; facing in degrees; width/height of the panel."""
    x, y, z = s["pos"]
    W, H = s.get("width", 1.23), s.get("height", 0.71)
    g = group(_name(s, "TV"), cx.coll, (x, y, 0), s.get("facing", 0))
    body = cx.mat(s, "body_material", "black")
    parts = [box("TV body", (-0.02, -W / 2, z - H / 2), (0.02, W / 2, z + H / 2), body, cx.coll, bevel=0.004)]
    if s.get("stand", True):
        base_z = s.get("stand_z", z - H / 2 - 0.10)
        parts.append(box("TV stand", (-0.06, -0.15, base_z), (0.10, 0.15, base_z + 0.02), body, cx.coll, bevel=0.004))
        parts.append(box("TV neck", (-0.01, -0.04, base_z + 0.02), (0.01, 0.04, z - H / 2), body, cx.coll))
    scr = image_plane(_name(s, "TV") + " screen", (0.021, 0, z), (W - 0.02, H - 0.02), "+X", cx.mat(s, "screen_material"), cx.coll)
    parts.append(scr)
    parent_all(g, parts)
    if s.get("glow"):
        import math as _m
        a = _m.radians(s.get("facing", 0))
        _light(cx, s["glow"], _name(s, "TV") + " glow", (x + 0.2 * _m.cos(a), y + 0.2 * _m.sin(a), z), kind="AREA",
               size=1.0, rot=(0, _m.radians(90), a))


# ---- lamps / fixtures ----------------------------------------------------------------------
def t_floor_lamp(s, cx):
    """Pole lamp with a drum shade. base [x, y]; shade [x, y, z] (centre); light {power, color}."""
    bx, by = s["base"]
    sx, sy, sz = s["shade"]
    n = _name(s, "Floor lamp")
    top = sz + s.get("shade_height", 0.26) / 2 + 0.01
    cylinder(n + " base", (bx, by, 0.012), 0.15, 0.024, cx.mat(s, "base_material", "black"), cx.coll)
    cylinder(n + " pole", (bx, by, top / 2), 0.011, top, cx.mat(s, "pole_material", "brass"), cx.coll, verts=12)
    dist = math.dist((bx, by), (sx, sy))
    if dist > 0.01:
        arm = cylinder(n + " arm", ((bx + sx) / 2, (by + sy) / 2, top), 0.009, dist, cx.mat(s, "pole_material", "brass"), cx.coll, verts=10)
        arm.rotation_euler = (0, math.pi / 2, math.atan2(sy - by, sx - bx))
    sh = cylinder(n + " shade", (sx, sy, sz), s.get("shade_radius", 0.21), s.get("shade_height", 0.26),
                  cx.mat(s, "shade_material", "shade"), cx.coll, verts=48, cap=False)
    sh.modifiers.new("Solid", "SOLIDIFY").thickness = 0.004
    _light(cx, s.get("light"), n + " bulb", (sx, sy, sz + 0.01))


def t_glow_cylinder(s, cx):
    """Emissive cylinder lamp (e.g. a red lava/tube lamp). pos [x, y], height, radius, light {...}."""
    x, y = s["pos"]
    h, r = s.get("height", 0.6), s.get("radius", 0.075)
    n = _name(s, "Glow lamp")
    cylinder(n, (x, y, h / 2), r, h, cx.mat(s), cx.coll, verts=24)
    _light(cx, s.get("light"), n + " light", (x, y, h * 0.6), size=r)


def t_ceiling_spots(s, cx):
    """Round base with N tilted spot cans. pos [x, y]; light {power, color, cone} per spot."""
    x, y = s["pos"]
    H = s.get("ceiling", cx.H)
    n, r, tilt = s.get("count", 3), s.get("radius", 0.13), math.radians(s.get("tilt", 35))
    nm = _name(s, "Ceiling spots")
    cylinder(nm + " base", (x, y, H - 0.03), 0.09, 0.05, cx.mat(s), cx.coll)
    for i in range(n):
        a = 2 * math.pi * i / n + 0.4
        p = Vector((x + r * math.cos(a), y + r * math.sin(a), H - 0.14))
        rot = (tilt * math.sin(a), -tilt * math.cos(a), 0)
        can = cylinder(f"{nm} can {i}", p, 0.045, 0.11, cx.mat(s), cx.coll)
        can.rotation_euler = rot
        cylinder(f"{nm} bulb {i}", p - Vector((0, 0, 0.05)), 0.03, 0.005, cx.mat(s, "bulb_material", "bulb"), cx.coll)
        L = s.get("light")
        if L:
            _light(cx, L, f"{nm} spot {i}", (p.x, p.y, H - 0.2), kind="SPOT", rot=rot, spot_deg=L.get("cone", 80), size=0.03)


def t_dome_light(s, cx):
    x, y = s["pos"]
    H = s.get("ceiling", cx.H)
    n = _name(s, "Dome light")
    cylinder(n, (x, y, H - 0.04), s.get("radius", 0.17), 0.08, cx.mat(s, "material", "bulb"), cx.coll, r2=s.get("radius", 0.17) * 0.7)
    _light(cx, s.get("light"), n + " light", (x, y, H - 0.12), size=0.12)


def t_pendant(s, cx):
    x, y = s["pos"]
    H = s.get("ceiling", cx.H)
    drop = s.get("drop", 0.84)
    n = _name(s, "Pendant")
    cylinder(n + " cord", (x, y, H - drop / 2 + 0.05), 0.004, drop - 0.1, cx.mat(s, "cord_material", "black"), cx.coll, verts=6)
    cylinder(n + " shade", (x, y, H - drop + 0.08), 0.03, 0.14, cx.mat(s), cx.coll, r2=0.13)
    cylinder(n + " bulb", (x, y, H - drop), 0.035, 0.04, cx.mat(s, "bulb_material", "bulb"), cx.coll)
    _light(cx, s.get("light"), n + " light", (x, y, H - drop - 0.02), size=0.04)


# ---- soft furnishings / decor --------------------------------------------------------------
def t_curtain(s, cx):
    """Wavy sheer curtain. axis: 'x' (hangs along X at y=at) or 'y'; span [a, b]; z [z0, z1]."""
    a0, a1 = s["span"]
    z0, z1 = s.get("z", [0.01, 2.07])
    at, axis = s["at"], s.get("axis", "x")
    waves, amp = s.get("waves", 9), s.get("amp", 0.04)
    me = bpy.data.meshes.new(_name(s, "Curtain"))
    bm = bmesh.new()
    nx, nz = 48, 2
    grid = []
    for i in range(nx + 1):
        t = i / nx
        u = a0 + (a1 - a0) * t
        dv = amp * math.sin(t * waves * 2 * math.pi)
        row = []
        for k in range(nz + 1):
            z = z0 + (z1 - z0) * k / nz
            row.append(bm.verts.new((u, at + dv, z) if axis == "x" else (at + dv, u, z)))
        grid.append(row)
    for i in range(nx):
        for k in range(nz):
            bm.faces.new((grid[i][k], grid[i + 1][k], grid[i + 1][k + 1], grid[i][k + 1]))
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(_name(s, "Curtain"), me)
    cx.coll.objects.link(o)
    me.materials.append(cx.mat(s))
    shade_smooth(o)


def t_plant(s, cx):
    """Palm-like plant in a pot. pos [x, y], pot_height, fronds, seed."""
    x, y = s["pos"]
    z0 = s.get("pot_height", 0.26)
    rnd = random.Random(s.get("seed", 3))
    n = _name(s, "Plant")
    cylinder(n + " pot", (x, y, z0 / 2), 0.16, z0, cx.mat(s, "pot_material", "basket"), cx.coll, r2=0.19)
    cylinder(n + " soil", (x, y, z0 - 0.01), 0.17, 0.01, cx.mat(s, "soil_material", "darkwood"), cx.coll)
    me = bpy.data.meshes.new(n + " fronds")
    bm = bmesh.new()
    scale = s.get("size", 1.0)
    for f in range(s.get("fronds", 8)):
        yaw = 2 * math.pi * f / s.get("fronds", 8) + rnd.uniform(-0.3, 0.3)
        tilt = rnd.uniform(0.25, 0.75)
        L = rnd.uniform(0.45, 0.75) * scale
        d = Vector((math.cos(yaw), math.sin(yaw), 0))
        side = Vector((-math.sin(yaw), math.cos(yaw), 0))
        pts = [Vector((x, y, z0)) + d * (L * t * math.sin(tilt + 0.6 * t)) + Vector((0, 0, L * t * math.cos(tilt + 1.1 * t) + 0.12))
               for t in (i / 12 for i in range(13))]
        for i in range(2, 12):
            ll = 0.16 * scale * math.sin(math.pi * i / 12)
            for sgn in (-1, 1):
                tip = pts[i] + side * sgn * ll + d * 0.05 - Vector((0, 0, 0.04))
                bm.faces.new((bm.verts.new(pts[i]), bm.verts.new(pts[i + 1]), bm.verts.new(tip)))
        for i in range(12):
            a, b = bm.verts.new(pts[i]), bm.verts.new(pts[i + 1])
            bm.faces.new((a, b, bm.verts.new(pts[i + 1] + side * 0.006), bm.verts.new(pts[i] + side * 0.006)))
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(n + " fronds", me)
    cx.coll.objects.link(o)
    me.materials.append(cx.mat(s, "leaf_material", "leaf"))
    shade_smooth(o)


def t_branches(s, cx):
    """Dry decorative branches fanning up from pos [x, y, z]."""
    x, y, z = s["pos"]
    rr = random.Random(s.get("seed", 5))
    lo, hi = s.get("length", [0.45, 0.75])
    for i in range(s.get("count", 9)):
        yaw, tilt = rr.uniform(0, 2 * math.pi), rr.uniform(0.05, 0.35)
        L = rr.uniform(lo, hi)
        d = Vector((math.sin(tilt) * math.cos(yaw), math.sin(tilt) * math.sin(yaw), math.cos(tilt)))
        t = cylinder(f"{_name(s, 'Branch')} {i}", Vector((x, y, z)) + d * L / 2, 0.004, L, cx.mat(s), cx.coll, verts=6)
        t.rotation_euler = Vector((0, 0, 1)).rotation_difference(d).to_euler()


def t_pet_bed(s, cx):
    """Rectangular plush pet bed with rims. pos [x, y], facing, size [length, width]."""
    l, w = s.get("size", [0.72, 0.60])
    g = group(_name(s, "Pet bed"), cx.coll, (*s["pos"], 0), s.get("facing", 0))
    M, a, b = cx.mat(s), l / 2, w / 2
    parts = [box("Pet bed base", (-a, -b, 0), (a, b, 0.07), M, cx.coll, bevel=0.03),
             box("Pet bed cushion", (-a + 0.11, -b + 0.11, 0.05), (a - 0.11, b - 0.11, 0.12), M, cx.coll, bevel=0.04, segments=5)]
    for nm, (x0, x1, y0, y1) in (("N", (-a, a, b - 0.13, b)), ("S", (-a, a, -b, -b + 0.13)),
                                 ("E", (a - 0.13, a, -b, b)), ("W", (-a, -a + 0.13, -b, b))):
        parts.append(box(f"Pet bed rim {nm}", (x0, y0, 0.03), (x1, y1, 0.21), M, cx.coll, bevel=0.06, segments=6))
    parent_all(g, parts)


TYPES = {k[2:]: v for k, v in dict(globals()).items() if k.startswith("t_")}


def build(spec, cx):
    t = spec["type"]
    if t not in TYPES:
        raise KeyError(f"unknown object type {t!r}; known: {sorted(TYPES)}")
    TYPES[t](spec, cx)
