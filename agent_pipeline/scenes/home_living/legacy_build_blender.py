"""Rebuild the home_living scan as a clean, realistic Blender scene.

Run inside Blender (e.g. through the Blender MCP or `blender -P`):

    exec(open("<repo>/blender_pipeline/build_blender.py").read())

Dimensions come from the aligned LingBot-Map reconstruction (blender_pipeline/align.py: Z up,
floor at z=0, metres; ceiling assumed 2.70 m) and from back-projected pixel probes on the
video frames. Textures come from blender_pipeline/textures.py. Everything is rebuilt from
scratch in the "Rebuild" collection; the fused scan mesh (blender_pipeline/fuse.py) goes in "Scan".
"""
import math
import os

import bmesh
import bpy
from mathutils import Euler, Vector

REPO = os.environ.get("LINGBOT_REPO", "/home/andres/focus/IAC/lingbot/lingbot-map")
DATA = os.path.join(REPO, "data")
TEX = os.path.join(DATA, "blender", "textures")
SCAN = os.path.join(DATA, "outputs", "home_living", "home_living_mesh_icp.ply")

# ---- Layout (metres) ---------------------------------------------------------------------
H = 2.70                      # ceiling height
T = 0.15                      # wall thickness
RX0, RX1 = -0.35, 2.85        # living room inner faces, west / east
RY0, RY1 = -2.72, 2.45        # living room inner faces, south (window) / north (arch)
HX0 = -3.70                   # hallway west end
HY0, HY1 = -0.55, 0.40        # hallway inner faces
DINING_Y1 = 5.40              # dining room north wall (only glimpsed through the arch)
DOOR_H = 2.08


# ---- Helpers ------------------------------------------------------------------------------
def collection(name, parent=None):
    c = bpy.data.collections.get(name) or bpy.data.collections.new(name)
    p = parent or bpy.context.scene.collection
    if c.name not in [x.name for x in p.children]:
        p.children.link(c)
    return c


def clear_collection(c):
    for o in list(c.all_objects):
        bpy.data.objects.remove(o, do_unlink=True)
    for ch in list(c.children):
        clear_collection(ch)
        bpy.data.collections.remove(ch)


def link(o, coll):
    for c in o.users_collection:
        c.objects.unlink(o)
    coll.objects.link(o)
    return o


def lin(c):
    """sRGB (as picked from the video) -> linear, which Blender's colour sockets expect."""
    return tuple(x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c)


def bsdf_of(m):
    return next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")


def material(name, color=(0.8, 0.8, 0.8), rough=0.5, metal=0.0, emit=None, emit_strength=0.0,
             alpha=1.0, transmission=0.0, sheen=0.0, image=None, image_emit=False, rough_image=None,
             uv_scale=None, coat=0.0):
    m = bpy.data.materials.get(name)
    if m:
        bpy.data.materials.remove(m)
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    b = bsdf_of(m)
    b.inputs["Base Color"].default_value = (*lin(color), 1)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    if transmission:
        b.inputs["Transmission Weight"].default_value = transmission
    if sheen:
        b.inputs["Sheen Weight"].default_value = sheen
    if coat:
        b.inputs["Coat Weight"].default_value = coat
        b.inputs["Coat Roughness"].default_value = 0.08
    if emit is not None:
        b.inputs["Emission Color"].default_value = (*lin(emit), 1)
        b.inputs["Emission Strength"].default_value = emit_strength
    if alpha < 1:
        b.inputs["Alpha"].default_value = alpha
        m.surface_render_method = "BLENDED"
    if image:
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = bpy.data.images.load(os.path.join(TEX, image), check_existing=True)
        nt.links.new(tex.outputs["Color"], b.inputs["Base Color"])
        if image_emit:
            nt.links.new(tex.outputs["Color"], b.inputs["Emission Color"])
            b.inputs["Emission Strength"].default_value = emit_strength or 1.0
        if rough_image:
            rt = nt.nodes.new("ShaderNodeTexImage")
            rt.image = bpy.data.images.load(os.path.join(TEX, rough_image), check_existing=True)
            rt.image.colorspace_settings.name = "Non-Color"
            nt.links.new(rt.outputs["Color"], b.inputs["Roughness"])
    return m


def box(name, x0, x1, y0, y1, z0, z1, mat, coll, bevel=0.0, segments=3):
    """Axis-aligned box from min/max corners, origin at its centre."""
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    coll.objects.link(o)
    o.location = ((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2)
    o.scale = (x1 - x0, y1 - y0, z1 - z0)
    bpy.context.view_layer.update()
    apply_scale(o)
    me.materials.append(mat)
    if bevel:
        md = o.modifiers.new("Bevel", "BEVEL")
        md.width = bevel
        md.segments = segments
        md.limit_method = "ANGLE"
        o.modifiers.new("WeightedNormal", "WEIGHTED_NORMAL").keep_sharp = True
        shade_smooth(o)            # flat boxes stay flat-shaded (thin glass would act as a lens)
    return o


def apply_scale(o):
    me = o.data
    s = o.scale.copy()
    for v in me.vertices:
        v.co = Vector((v.co.x * s.x, v.co.y * s.y, v.co.z * s.z))
    o.scale = (1, 1, 1)


def shade_smooth(o):
    for p in o.data.polygons:
        p.use_smooth = True


def cylinder(name, loc, r, h, mat, coll, verts=32, r2=None, cap=True):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=cap, cap_tris=False, segments=verts,
                          radius1=r, radius2=r if r2 is None else r2, depth=h)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    coll.objects.link(o)
    o.location = loc
    me.materials.append(mat)
    shade_smooth(o)
    return o


def image_plane(name, center, size, normal_axis, mat, coll):
    """Plane with 0..1 UVs facing +X/-X/+Y/-Y (normal_axis), e.g. a painting front."""
    w, h = size
    me = bpy.data.meshes.new(name)
    rot = {"+X": (math.pi / 2, 0, math.pi / 2), "-X": (math.pi / 2, 0, -math.pi / 2),
           "+Y": (math.pi / 2, 0, math.pi), "-Y": (math.pi / 2, 0, 0)}[normal_axis]
    verts = [(-w / 2, -h / 2, 0), (w / 2, -h / 2, 0), (w / 2, h / 2, 0), (-w / 2, h / 2, 0)]
    me.from_pydata(verts, [], [(0, 1, 2, 3)])
    uv = me.uv_layers.new(name="UVMap")
    for i, c in enumerate([(0, 0), (1, 0), (1, 1), (0, 1)]):
        uv.data[i].uv = c
    o = bpy.data.objects.new(name, me)
    coll.objects.link(o)
    o.location = center
    o.rotation_euler = rot
    me.materials.append(mat)
    return o


def planar_uv(o, scale, rot_deg=0.0, axes="xy"):
    """World-space planar UVs (metres / scale), rotated; for tiling textures."""
    me = o.data
    uv = me.uv_layers.get("UVMap") or me.uv_layers.new(name="UVMap")
    c, s = math.cos(math.radians(rot_deg)), math.sin(math.radians(rot_deg))
    mw = o.matrix_world
    for poly in me.polygons:
        for li in poly.loop_indices:
            p = mw @ me.vertices[me.loops[li].vertex_index].co
            a, b = {"xy": (p.x, p.y), "xz": (p.x, p.z), "yz": (p.y, p.z)}[axes]
            uv.data[li].uv = ((a * c - b * s) / scale, (a * s + b * c) / scale)


def wall_x(name, x_face, inward, y0, y1, openings, mat, coll, z1=H):
    """Wall whose inner face is at x=x_face (inward = +1 if the room is at larger x).
    openings: list of (ya, yb, z_top)."""
    xa, xb = (x_face - T, x_face) if inward > 0 else (x_face, x_face + T)
    _wall(name, lambda a, b, za, zb: box(f"{name}", xa, xb, a, b, za, zb, mat, coll), y0, y1, openings, z1)


def wall_y(name, y_face, inward, x0, x1, openings, mat, coll, z1=H):
    ya, yb = (y_face - T, y_face) if inward > 0 else (y_face, y_face + T)
    _wall(name, lambda a, b, za, zb: box(f"{name}", a, b, ya, yb, za, zb, mat, coll), x0, x1, openings, z1)


def _wall(name, make, a0, a1, openings, z1):
    cur = a0
    for (oa, ob, ztop) in sorted(openings):
        if oa > cur:
            make(cur, oa, 0, z1)
        if ztop < z1:
            make(oa, ob, ztop, z1)                 # lintel
        cur = ob
    if cur < a1:
        make(cur, a1, 0, z1)


# ---- Scene reset --------------------------------------------------------------------------
scene = bpy.context.scene
root = collection("Rebuild")
clear_collection(root)
C_STRUCT = collection("Structure", root)
C_OPEN = collection("Openings", root)
C_FURN = collection("Furniture", root)
C_DECOR = collection("Decor", root)
C_LIGHT = collection("Lights", root)
for name in ("InspectCam", "TopCam"):
    o = bpy.data.objects.get(name)
    if o:
        bpy.data.objects.remove(o, do_unlink=True)

# ---- Materials ----------------------------------------------------------------------------
M = {}
M["parquet"] = material("Parquet", rough=0.25, image="parquet_diffuse.jpg", rough_image="parquet_rough.png", coat=0.6)
M["wall"] = material("Wall paint", (0.88, 0.86, 0.82), rough=0.88)
M["ceiling"] = material("Ceiling paint", (0.91, 0.90, 0.87), rough=0.92)
M["trim"] = material("White satin trim", (0.88, 0.87, 0.84), rough=0.35)
M["darkwood"] = material("Dark wood", (0.045, 0.028, 0.018), rough=0.4, coat=0.3)
M["archwood"] = material("Arch wood", (0.12, 0.055, 0.025), rough=0.35, coat=0.4)
M["alu"] = material("White aluminium", (0.85, 0.85, 0.84), rough=0.3, metal=0.3)
M["glass"] = material("Glass", (0.9, 0.95, 0.95), rough=0.02, transmission=1.0)
M["night"] = material("Night view", rough=1.0, image="window_night.jpg", image_emit=True, emit_strength=0.6)
M["sheer"] = material("Sheer curtain", (0.86, 0.84, 0.78), rough=0.95, alpha=0.55, sheen=0.5)
M["sofa"] = material("Sofa fabric", (0.33, 0.28, 0.23), rough=0.95, sheen=0.6)
M["cream"] = material("Cream fabric", (0.80, 0.76, 0.68), rough=0.9, sheen=0.6)
M["plush"] = material("Plush", (0.74, 0.70, 0.60), rough=1.0, sheen=1.0)
M["throw"] = material("Orange throw", (0.75, 0.38, 0.08), rough=0.95, sheen=0.6)
M["rug"] = material("Navy rug", (0.025, 0.045, 0.13), rough=1.0, sheen=0.4)
M["black"] = material("Black plastic", (0.01, 0.01, 0.01), rough=0.25)
M["screen"] = material("TV screen", rough=0.15, image="tv_screen.jpg", image_emit=True, emit_strength=1.2)
M["gg"] = material("Painting Golden Gate", rough=0.7, image="painting_goldengate.jpg")
M["colorful"] = material("Painting colorful", rough=0.6, image="painting_colorful.jpg")
M["brass"] = material("Brass", (0.80, 0.62, 0.34), rough=0.28, metal=1.0)
M["shade"] = material("Lamp shade", (0.93, 0.86, 0.70), rough=0.9, emit=(1.0, 0.80, 0.55), emit_strength=0.35)
M["redglow"] = material("Red lamp glow", (0.9, 0.15, 0.03), rough=0.5, emit=(1.0, 0.22, 0.04), emit_strength=2.5)
M["twig"] = material("Twig", (0.08, 0.06, 0.04), rough=0.8)
M["basket"] = material("Woven basket", (0.55, 0.45, 0.31), rough=0.95)
M["leaf"] = material("Palm leaf", (0.10, 0.22, 0.06), rough=0.6, sheen=0.2)
M["ceramic"] = material("Ceramic", (0.85, 0.83, 0.78), rough=0.2)
M["bulb"] = material("Warm bulb", (1, 0.9, 0.7), emit=(1.0, 0.85, 0.6), emit_strength=20.0)
M["steel"] = material("Brushed steel", (0.6, 0.6, 0.6), rough=0.35, metal=1.0)

# ---- Floors & ceilings --------------------------------------------------------------------
floor = box("Floor living", RX0, RX1, RY0, RY1, -0.02, 0.0, M["parquet"], C_STRUCT)
hall_floor = box("Floor hallway", HX0, RX0, HY0, HY1, -0.02, 0.0, M["parquet"], C_STRUCT)
din_floor = box("Floor dining", RX0, RX1, RY1, DINING_Y1, -0.02, 0.0, M["parquet"], C_STRUCT)
for f in (floor, hall_floor, din_floor):
    planar_uv(f, 1.44, rot_deg=45)
box("Ceiling living", RX0, RX1, RY0, RY1, H, H + 0.05, M["ceiling"], C_STRUCT)
box("Ceiling hallway", HX0, RX0, HY0, HY1, H, H + 0.05, M["ceiling"], C_STRUCT)
box("Ceiling dining", RX0, RX1, RY1, DINING_Y1, H, H + 0.05, M["ceiling"], C_STRUCT)
# beam / soffit running along the window wall
box("Ceiling beam", RX0, RX1, RY0, RY0 + 0.38, H - 0.26, H, M["ceiling"], C_STRUCT, bevel=0.01)

# ---- Walls --------------------------------------------------------------------------------
WIN_X0, WIN_X1, WIN_TOP = 0.55, 2.15, 2.05
ARCH_X0, ARCH_X1, ARCH_SPRING = 0.95, 2.25, 1.80
NDOOR_X0, NDOOR_X1 = -0.22, 0.56
wall_y("Wall south", RY0, +1, RX0 - T, RX1 + T, [(WIN_X0, WIN_X1, WIN_TOP)], M["wall"], C_STRUCT)
wall_x("Wall east", RX1, -1, RY0, DINING_Y1, [], M["wall"], C_STRUCT)
wall_x("Wall west", RX0, +1, RY0, RY1, [(HY0, HY1, DOOR_H)], M["wall"], C_STRUCT)
wall_x("Wall west dining", RX0, +1, RY1, DINING_Y1, [], M["wall"], C_STRUCT)
wall_y("Wall north dining", DINING_Y1, -1, RX0 - T, RX1 + T, [], M["wall"], C_STRUCT)
# hallway walls with doors
wall_y("Wall hall south", HY0, +1, HX0 - T, RX0 - T, [(-3.15, -2.35, DOOR_H), (-1.75, -0.95, DOOR_H)], M["wall"], C_STRUCT)
wall_y("Wall hall north", HY1, -1, HX0 - T, RX0 - T, [(-2.85, -2.05, DOOR_H)], M["wall"], C_STRUCT)
wall_x("Wall hall end", HX0, +1, HY0, HY1, [], M["wall"], C_STRUCT)

# North wall (living | dining) with a door near the west corner and the arch.
north = wall_y("Wall north", RY1, -1, RX0 - T, RX1 + T,
               [(NDOOR_X0, NDOOR_X1, DOOR_H), (ARCH_X0, ARCH_X1, ARCH_SPRING)], M["wall"], C_STRUCT)
# Arch: round the lintel by cutting a half-cylinder out of it.
lintel = [o for o in C_STRUCT.objects if o.name.startswith("Wall north")
          and abs(o.location.x - (ARCH_X0 + ARCH_X1) / 2) < 0.01][0]
ar = (ARCH_X1 - ARCH_X0) / 2
cut = cylinder("Arch cutter", ((ARCH_X0 + ARCH_X1) / 2, RY1 + T / 2, ARCH_SPRING), ar, T * 3, M["wall"], C_STRUCT, verts=64)
cut.rotation_euler = (math.pi / 2, 0, 0)
cut.hide_render = True
cut.display_type = "WIRE"
bo = lintel.modifiers.new("Arch", "BOOLEAN")
bo.object = cut
bo.operation = "DIFFERENCE"
bo.solver = "EXACT"
bpy.context.view_layer.objects.active = lintel
bpy.ops.object.modifier_apply(modifier="Arch")
bpy.data.objects.remove(cut, do_unlink=True)

# Arch trim: dark wood band following the arch and jambs.
def arch_trim():
    me = bpy.data.meshes.new("Arch trim")
    bm = bmesh.new()
    cx, w = (ARCH_X0 + ARCH_X1) / 2, 0.06
    pts = [(ARCH_X0, 0.0), (ARCH_X0, ARCH_SPRING)]
    for i in range(1, 32):
        a = math.pi - math.pi * i / 32
        pts.append((cx + ar * math.cos(a), ARCH_SPRING + ar * math.sin(a)))
    pts += [(ARCH_X1, ARCH_SPRING), (ARCH_X1, 0.0)]
    # inner band (reveal) + front face lip on both sides
    rings = []
    for (x, z) in pts:
        n = Vector((x - cx, 0, z - ARCH_SPRING)) if z > ARCH_SPRING else Vector((1 if x > cx else -1, 0, 0))
        n.normalize()
        inner = Vector((x, 0, z)) - n * 0.0
        outer = Vector((x, 0, z)) + n * w
        rings.append((inner, outer))
    for y in (RY1 - 0.01, RY1 + T + 0.01):
        prev = None
        for inner, outer in rings:
            a = bm.verts.new((inner.x, y, inner.z)); b = bm.verts.new((outer.x, y, outer.z))
            if prev:
                bm.faces.new((prev[0], prev[1], b, a))
            prev = (a, b)
    prev = None
    for inner, _ in rings:
        a = bm.verts.new((inner.x, RY1 - 0.01, inner.z)); b = bm.verts.new((inner.x, RY1 + T + 0.01, inner.z))
        if prev:
            bm.faces.new((prev[0], prev[1], b, a))
        prev = (a, b)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new("Arch trim", me)
    C_OPEN.objects.link(o)
    me.materials.append(M["archwood"])
    o.modifiers.new("Solid", "SOLIDIFY").thickness = 0.015
    shade_smooth(o)
arch_trim()
box("Arch threshold", ARCH_X0, ARCH_X1, RY1 - 0.01, RY1 + T + 0.01, 0.0, 0.012, M["archwood"], C_OPEN, bevel=0.004)

# ---- Baseboards ---------------------------------------------------------------------------
BB = 0.09
box("Baseboard south W", RX0, WIN_X0, RY0, RY0 + 0.012, 0, BB, M["trim"], C_STRUCT)
box("Baseboard south E", WIN_X1, RX1, RY0, RY0 + 0.012, 0, BB, M["trim"], C_STRUCT)
box("Baseboard east", RX1 - 0.012, RX1, RY0, RY1, 0, BB, M["trim"], C_STRUCT)
box("Baseboard west S", RX0, RX0 + 0.012, RY0, HY0, 0, BB, M["trim"], C_STRUCT)
box("Baseboard west N", RX0, RX0 + 0.012, HY1, RY1, 0, BB, M["trim"], C_STRUCT)
box("Baseboard north W", NDOOR_X1, ARCH_X0, RY1 - 0.012, RY1, 0, BB, M["trim"], C_STRUCT)
box("Baseboard north E", ARCH_X1, RX1, RY1 - 0.012, RY1, 0, BB, M["trim"], C_STRUCT)
box("Baseboard hall S", HX0, RX0, HY0, HY0 + 0.012, 0, BB, M["trim"], C_STRUCT)
box("Baseboard hall N", HX0, RX0, HY1 - 0.012, HY1, 0, BB, M["trim"], C_STRUCT)
# crown moulding (living)
for nm, a in (("S", (RX0, RX1, RY0 + 0.38, RY0 + 0.42)), ("E", (RX1 - 0.04, RX1, RY0, RY1)),
              ("W", (RX0, RX0 + 0.04, RY0, RY1)), ("N", (RX0, RX1, RY1 - 0.04, RY1))):
    box(f"Crown {nm}", a[0], a[1], a[2], a[3], H - 0.05, H, M["ceiling"], C_STRUCT, bevel=0.015)

# ---- Doors & door trims -------------------------------------------------------------------
def door_trim_y(name, x0, x1, y_face, side):
    """Casing around a door in a wall of constant y (side=+1 casing on +y face)."""
    yy = (y_face, y_face + 0.02 * side)
    ya, yb = min(yy), max(yy)
    box(name + " L", x0 - 0.07, x0, ya, yb, 0, DOOR_H + 0.07, M["trim"], C_OPEN, bevel=0.005)
    box(name + " R", x1, x1 + 0.07, ya, yb, 0, DOOR_H + 0.07, M["trim"], C_OPEN, bevel=0.005)
    box(name + " T", x0 - 0.07, x1 + 0.07, ya, yb, DOOR_H, DOOR_H + 0.07, M["trim"], C_OPEN, bevel=0.005)


def door_trim_x(name, y0, y1, x_face, side):
    xx = (x_face, x_face + 0.02 * side)
    xa, xb = min(xx), max(xx)
    box(name + " L", xa, xb, y0 - 0.07, y0, 0, DOOR_H + 0.07, M["trim"], C_OPEN, bevel=0.005)
    box(name + " R", xa, xb, y1, y1 + 0.07, 0, DOOR_H + 0.07, M["trim"], C_OPEN, bevel=0.005)
    box(name + " T", xa, xb, y0 - 0.07, y1 + 0.07, DOOR_H, DOOR_H + 0.07, M["trim"], C_OPEN, bevel=0.005)


def panel_door(name, hinge, width, wall_axis, open_deg, glass=True):
    """White panel door; hinge=(x,y) at floor, leaf extends along +wall_axis before rotation."""
    leaf = bpy.data.objects.new(name, None)
    C_OPEN.objects.link(leaf)
    leaf.location = (hinge[0], hinge[1], 0)
    parts = [box(name + " leaf", 0, width, -0.02, 0.02, 0.0, DOOR_H - 0.01, M["trim"], C_OPEN, bevel=0.004)]
    # raised panels / glass
    if glass:
        g = box(name + " glass", 0.12, width - 0.12, -0.025, 0.025, 1.05, 1.90, M["glass"], C_OPEN)
        parts.append(g)
    parts.append(box(name + " panel", 0.12, width - 0.12, -0.026, 0.026, 0.18, 0.92, M["trim"], C_OPEN, bevel=0.01))
    parts.append(box(name + " handle", width - 0.10, width - 0.04, -0.07, 0.07, 1.0, 1.03, M["brass"], C_OPEN, bevel=0.01))
    for p in parts:
        p.parent = leaf
    leaf.rotation_euler = (0, 0, (0 if wall_axis == "x" else math.pi / 2) + math.radians(open_deg))
    return leaf


door_trim_x("Hall opening casing", HY0, HY1, RX0, +1)
door_trim_y("North door casing", NDOOR_X0, NDOOR_X1, RY1, -1)
panel_door("North door", (NDOOR_X0, RY1 + T - 0.03), NDOOR_X1 - NDOOR_X0, "x", 75)
for i, (a, b) in enumerate([(-3.15, -2.35), (-1.75, -0.95)]):
    door_trim_y(f"Hall S door {i} casing", a, b, HY0, +1)
    panel_door(f"Hall S door {i}", (a, HY0 - T + 0.03), b - a, "x", 0)      # closed: rooms beyond are not modelled
door_trim_y("Hall N door casing", -2.85, -2.05, HY1, -1)
panel_door("Hall N door", (-2.85, HY1 + T - 0.03), 0.80, "x", 0)

# ---- Window: sliding glass door, valance, outside view ------------------------------------
yw = RY0 - T / 2
fw = 0.05
box("Window frame bottom", WIN_X0, WIN_X1, yw - 0.06, yw + 0.06, 0.0, 0.05, M["alu"], C_OPEN, bevel=0.004)
box("Window frame top", WIN_X0, WIN_X1, yw - 0.06, yw + 0.06, WIN_TOP - 0.05, WIN_TOP, M["alu"], C_OPEN, bevel=0.004)
box("Window frame L", WIN_X0, WIN_X0 + fw, yw - 0.06, yw + 0.06, 0, WIN_TOP, M["alu"], C_OPEN, bevel=0.004)
box("Window frame R", WIN_X1 - fw, WIN_X1, yw - 0.06, yw + 0.06, 0, WIN_TOP, M["alu"], C_OPEN, bevel=0.004)
pw = (WIN_X1 - WIN_X0) / 2
for i, off in enumerate((-0.025, 0.025)):
    x0 = WIN_X0 + i * (pw - 0.04)
    x1 = x0 + pw + 0.04
    y = yw + off
    box(f"Sash {i} stile L", x0, x0 + 0.045, y - 0.015, y + 0.015, 0.05, WIN_TOP - 0.05, M["alu"], C_OPEN, bevel=0.003)
    box(f"Sash {i} stile R", x1 - 0.045, x1, y - 0.015, y + 0.015, 0.05, WIN_TOP - 0.05, M["alu"], C_OPEN, bevel=0.003)
    box(f"Sash {i} rail B", x0, x1, y - 0.015, y + 0.015, 0.05, 0.12, M["alu"], C_OPEN, bevel=0.003)
    box(f"Sash {i} rail T", x0, x1, y - 0.015, y + 0.015, WIN_TOP - 0.11, WIN_TOP - 0.05, M["alu"], C_OPEN, bevel=0.003)
    box(f"Sash {i} rail M", x0, x1, y - 0.012, y + 0.012, 0.95, 0.99, M["alu"], C_OPEN, bevel=0.003)
    box(f"Sash {i} glass", x0 + 0.045, x1 - 0.045, y - 0.004, y + 0.004, 0.12, WIN_TOP - 0.11, M["glass"], C_OPEN)
# roller-blind box (valance) just under the ceiling beam
box("Blind box", WIN_X0 - 0.25, WIN_X1 + 0.25, RY0, RY0 + 0.17, WIN_TOP, WIN_TOP + 0.24, M["trim"], C_OPEN, bevel=0.01)
# balcony & night view behind the glass
box("Balcony floor", WIN_X0 - 0.6, WIN_X1 + 0.6, RY0 - 1.3, RY0 - T, -0.03, 0.0, M["darkwood"], C_OPEN)
box("Balcony rail", WIN_X0 - 0.6, WIN_X1 + 0.6, RY0 - 1.32, RY0 - 1.28, 0.95, 1.0, M["black"], C_OPEN)
image_plane("Night view", ((WIN_X0 + WIN_X1) / 2, RY0 - 3.0, 1.3), (3.6, 3.8), "+Y", M["night"], C_OPEN)

print("structure ok:", len(C_STRUCT.objects), "structure objects,", len(C_OPEN.objects), "opening objects")


# ==== Furniture ============================================================================
def legs(prefix, xs, ys, z1, r, mat, coll):
    for i, x in enumerate(xs):
        for j, y in enumerate(ys):
            cylinder(f"{prefix} leg {i}{j}", (x, y, z1 / 2), r, z1, mat, coll, verts=12)


# -- L-sectional sofa, back against the east wall, chaise projecting west at the north end
SX0, SX1 = 1.90, RX1 - 0.02          # main section depth
SY0, SY1 = -2.62, -0.05              # main section length (south arm .. north end)
CX0, CY0 = 1.20, -0.98               # chaise front x, chaise south edge y
F = C_FURN
box("Sofa base main", SX0, SX1, SY0, SY1, 0.10, 0.30, M["sofa"], F, bevel=0.02)
box("Sofa base chaise", CX0, SX0 + 0.02, CY0, SY1, 0.10, 0.30, M["sofa"], F, bevel=0.02)
legs("Sofa", (SX0 + 0.06, SX1 - 0.06), (SY0 + 0.06, SY1 - 0.06), 0.10, 0.02, M["darkwood"], F)
legs("Chaise", (CX0 + 0.06,), (CY0 + 0.06, SY1 - 0.06), 0.10, 0.02, M["darkwood"], F)
# seat cushions
for i in range(3):
    y0 = SY0 + 0.21 + i * (CY0 - SY0 - 0.21) / 3
    y1 = SY0 + 0.21 + (i + 1) * (CY0 - SY0 - 0.21) / 3
    box(f"Sofa seat {i}", SX0 + 0.01, SX1 - 0.22, y0 + 0.005, y1 - 0.005, 0.30, 0.47, M["sofa"], F, bevel=0.05, segments=5)
box("Chaise seat", CX0 + 0.01, SX1 - 0.22, CY0 + 0.01, SY1 - 0.01, 0.30, 0.47, M["sofa"], F, bevel=0.05, segments=5)
# back frame + back cushions
box("Sofa back", SX1 - 0.22, SX1, SY0, SY1, 0.30, 0.72, M["sofa"], F, bevel=0.04, segments=4)
nb = 4
for i in range(nb):
    y0 = SY0 + 0.21 + i * (SY1 - SY0 - 0.21) / nb
    y1 = SY0 + 0.21 + (i + 1) * (SY1 - SY0 - 0.21) / nb
    c = box(f"Sofa back cushion {i}", SX1 - 0.40, SX1 - 0.20, y0 + 0.01, y1 - 0.01, 0.44, 0.90, M["sofa"], F, bevel=0.07, segments=6)
    c.rotation_euler = (0, math.radians(-10), 0)
box("Sofa arm south", SX0, SX1, SY0, SY0 + 0.21, 0.10, 0.62, M["sofa"], F, bevel=0.06, segments=5)
# throw folded on the south arm, pillows at the chaise corner
box("Orange throw", SX0 + 0.10, SX1 - 0.25, SY0 + 0.01, SY0 + 0.20, 0.62, 0.68, M["throw"], F, bevel=0.025)
for i, (x, y, rz) in enumerate([(2.30, -0.30, 15), (2.25, -2.18, -20)]):
    p = box(f"Pillow {i}", x - 0.08, x + 0.08, y - 0.22, y + 0.22, 0.46, 0.88, M["sofa"], F, bevel=0.07, segments=6)
    p.rotation_euler = (0, math.radians(-18), math.radians(rz))

# -- Armchair (cream), against the east wall north of the floor lamp, facing west
def armchair(cx, cy, rot):
    a = bpy.data.objects.new("Armchair", None)
    F.objects.link(a)
    a.location = (cx, cy, 0)
    a.rotation_euler = (0, 0, math.radians(rot))
    parts = [
        box("Armchair base", -0.40, 0.40, -0.40, 0.40, 0.12, 0.30, M["cream"], F, bevel=0.03),
        box("Armchair seat", -0.30, 0.33, -0.28, 0.28, 0.30, 0.45, M["cream"], F, bevel=0.05, segments=5),
        box("Armchair back", 0.24, 0.42, -0.40, 0.40, 0.30, 0.82, M["cream"], F, bevel=0.06, segments=5),
        box("Armchair arm L", -0.40, 0.42, -0.42, -0.27, 0.12, 0.62, M["cream"], F, bevel=0.05, segments=5),
        box("Armchair arm R", -0.40, 0.42, 0.27, 0.42, 0.12, 0.62, M["cream"], F, bevel=0.05, segments=5),
        box("Armchair cushion", 0.12, 0.26, -0.22, 0.22, 0.45, 0.78, M["cream"], F, bevel=0.06, segments=5),
    ]
    for (x, y) in [(-0.34, -0.34), (-0.34, 0.34), (0.34, -0.34), (0.34, 0.34)]:
        parts.append(cylinder("Armchair leg", (x, y, 0.06), 0.018, 0.12, M["darkwood"], F, verts=10))
    for p in parts:
        p.parent = a
armchair(2.33, 1.85, 0)

# -- Coffee table, rug
box("Rug", 0.55, 1.86, -2.62, -0.92, 0.0, 0.012, M["rug"], F, bevel=0.004)
box("Coffee table top", 0.98, 1.76, -2.55, -1.93, 0.37, 0.41, M["darkwood"], F, bevel=0.006)
box("Coffee table shelf", 1.02, 1.72, -2.51, -1.97, 0.10, 0.12, M["darkwood"], F, bevel=0.004)
for (x, y) in [(1.01, -2.52), (1.73, -2.52), (1.01, -1.96), (1.73, -1.96)]:
    box("Coffee table leg", x - 0.02, x + 0.02, y - 0.02, y + 0.02, 0.0, 0.37, M["darkwood"], F)
bowl = cylinder("Bowl", (1.50, -2.35, 0.445), 0.13, 0.07, M["ceramic"], F, r2=0.16, cap=True)
cylinder("Glass", (1.33, -2.12, 0.47), 0.035, 0.12, M["glass"], F, verts=20)
box("Remote", 1.20, 1.36, -2.30, -2.26, 0.41, 0.425, M["black"], F, bevel=0.005)

# -- TV unit + TV on the west wall
box("TV unit", RX0 + 0.01, RX0 + 0.41, -2.45, -0.95, 0.08, 0.46, M["darkwood"], F, bevel=0.008)
for (x, y) in [(RX0 + 0.06, -2.40), (RX0 + 0.36, -2.40), (RX0 + 0.06, -1.00), (RX0 + 0.36, -1.00)]:
    cylinder("TV unit leg", (x, y, 0.04), 0.015, 0.08, M["darkwood"], F, verts=10)
TVY, TVZ, TVW, TVH = -1.70, 0.86, 1.23, 0.71
box("TV body", RX0 + 0.14, RX0 + 0.18, TVY - TVW / 2, TVY + TVW / 2, TVZ - TVH / 2, TVZ + TVH / 2, M["black"], F, bevel=0.004)
box("TV stand", RX0 + 0.10, RX0 + 0.26, TVY - 0.15, TVY + 0.15, 0.46, 0.48, M["black"], F, bevel=0.004)
box("TV neck", RX0 + 0.15, RX0 + 0.17, TVY - 0.04, TVY + 0.04, 0.48, TVZ - TVH / 2, M["black"], F)
image_plane("TV screen", (RX0 + 0.181, TVY, TVZ), (TVW - 0.02, TVH - 0.02), "+X", M["screen"], F)

# ==== Decor ===============================================================================
D = C_DECOR
# Paintings
def painting(name, center, size, normal, img_mat, frame_mat, depth=0.03, border=0.025):
    cx, cy, cz = center
    w, h = size
    if normal in ("+X", "-X"):
        s = 1 if normal == "+X" else -1
        box(name + " frame", cx - depth / 2, cx + depth / 2, cy - w / 2 - border, cy + w / 2 + border,
            cz - h / 2 - border, cz + h / 2 + border, frame_mat, D, bevel=0.004)
        image_plane(name, (cx + s * (depth / 2 + 0.001), cy, cz), (w, h), normal, img_mat, D)
painting("Painting Golden Gate", (RX0 + 0.016, 0.95, 1.36), (0.80, 0.64), "+X", M["gg"], M["darkwood"])
painting("Painting colorful", (RX1 - 0.016, -1.25, 1.55), (1.15, 0.48), "-X", M["colorful"], M["trim"], border=0.05)

# Sheer curtains: wavy vertical sheets on both sides of the window
def curtain(name, x0, x1, y, z0, z1, waves=9, amp=0.04):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    nx, nz = 48, 2
    grid = []
    for i in range(nx + 1):
        t = i / nx
        x = x0 + (x1 - x0) * t
        dy = amp * math.sin(t * waves * 2 * math.pi)
        grid.append([bm.verts.new((x, y + dy, z0 + (z1 - z0) * k / nz)) for k in range(nz + 1)])
    for i in range(nx):
        for k in range(nz):
            bm.faces.new((grid[i][k], grid[i + 1][k], grid[i + 1][k + 1], grid[i][k + 1]))
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    D.objects.link(o)
    me.materials.append(M["sheer"])
    shade_smooth(o)
    return o
curtain("Curtain left", WIN_X1 - 0.35, WIN_X1 + 0.30, RY0 + 0.12, 0.01, WIN_TOP + 0.02)
curtain("Curtain right", WIN_X0 - 0.30, WIN_X0 + 0.35, RY0 + 0.12, 0.01, WIN_TOP + 0.02)
box("Curtain rod", WIN_X0 - 0.35, WIN_X1 + 0.35, RY0 + 0.115, RY0 + 0.13, WIN_TOP + 0.02, WIN_TOP + 0.035, M["alu"], D)

# Floor lamp (brass pole, cream drum shade) next to the sofa's north end
LX, LY = 2.56, 0.86
cylinder("Floor lamp base", (LX, LY, 0.012), 0.15, 0.024, M["black"], D)
cylinder("Floor lamp pole", (LX, LY, 0.80), 0.011, 1.58, M["brass"], D, verts=12)
arm = cylinder("Floor lamp arm", ((LX + 2.38) / 2, (LY + 0.76) / 2, 1.59), 0.009,
               math.dist((LX, LY), (2.38, 0.76)), M["brass"], D, verts=10)
arm.rotation_euler = (0, math.pi / 2, math.atan2(0.76 - LY, 2.38 - LX))
cylinder("Floor lamp shade", (2.38, 0.76, 1.46), 0.21, 0.26, M["shade"], D, verts=48, cap=False).modifiers.new("Solid", "SOLIDIFY").thickness = 0.004

# Palm in a woven basket
def palm(cx, cy, z0, fronds=8, seed=3):
    import random
    rnd = random.Random(seed)
    cylinder("Plant basket", (cx, cy, z0 / 2), 0.16, z0, M["basket"], D, r2=0.19)
    cylinder("Plant soil", (cx, cy, z0 - 0.01), 0.17, 0.01, M["darkwood"], D)
    me = bpy.data.meshes.new("Palm fronds")
    bm = bmesh.new()
    for f in range(fronds):
        yaw = 2 * math.pi * f / fronds + rnd.uniform(-0.3, 0.3)
        tilt = rnd.uniform(0.25, 0.75)
        L = rnd.uniform(0.45, 0.75)
        d = Vector((math.cos(yaw), math.sin(yaw), 0))
        side = Vector((-math.sin(yaw), math.cos(yaw), 0))
        pts = []
        for i in range(13):
            t = i / 12
            # stem arcs up then droops
            pts.append(Vector((cx, cy, z0)) + d * (L * t * math.sin(tilt + 0.6 * t)) +
                       Vector((0, 0, L * t * math.cos(tilt + 1.1 * t) + 0.12)))
        for i in range(2, 12):
            p = pts[i]
            ll = 0.16 * math.sin(math.pi * i / 12)
            for sgn in (-1, 1):
                tip = p + side * sgn * ll + d * 0.05 - Vector((0, 0, 0.04))
                a = bm.verts.new(p); b = bm.verts.new(pts[i + 1]); c = bm.verts.new(tip)
                bm.faces.new((a, b, c))
        for i in range(12):                     # stem as thin strip
            a = bm.verts.new(pts[i]); b = bm.verts.new(pts[i + 1])
            c = bm.verts.new(pts[i + 1] + side * 0.006); e = bm.verts.new(pts[i] + side * 0.006)
            bm.faces.new((a, b, c, e))
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new("Palm fronds", me)
    D.objects.link(o)
    me.materials.append(M["leaf"])
    shade_smooth(o)
palm(2.33, 0.40, 0.26)

# Red cylinder lamp with dry branches (SW corner, next to the TV)
cylinder("Red lamp", (0.20, -2.50, 0.30), 0.075, 0.60, M["redglow"], D, verts=24)
import random as _r
rr = _r.Random(5)
for i in range(9):
    yaw, tilt = rr.uniform(0, 2 * math.pi), rr.uniform(0.05, 0.35)
    L = rr.uniform(0.45, 0.75)
    t = cylinder(f"Branch {i}", (0, 0, 0), 0.004, L, M["twig"], D, verts=6)
    t.location = (0.20 + math.sin(tilt) * math.cos(yaw) * L / 2, -2.50 + math.sin(tilt) * math.sin(yaw) * L / 2, 0.60 + math.cos(tilt) * L / 2)
    t.rotation_euler = Euler((0, tilt, yaw), "XYZ")
    t.rotation_euler = (Vector((0, 0, 1)).rotation_difference(Vector((math.sin(tilt) * math.cos(yaw), math.sin(tilt) * math.sin(yaw), math.cos(tilt))))).to_euler()

# Dog bed (cream plush) below the Golden Gate painting
def dog_bed(cx, cy, rot):
    b = bpy.data.objects.new("Dog bed", None)
    D.objects.link(b)
    b.location = (cx, cy, 0)
    b.rotation_euler = (0, 0, math.radians(rot))
    parts = [box("Dog bed base", -0.36, 0.36, -0.30, 0.30, 0.0, 0.07, M["plush"], D, bevel=0.03),
             box("Dog bed cushion", -0.25, 0.25, -0.19, 0.19, 0.05, 0.12, M["plush"], D, bevel=0.04, segments=5)]
    for nm, a in (("N", (-0.36, 0.36, 0.17, 0.30)), ("S", (-0.36, 0.36, -0.30, -0.17)),
                  ("E", (0.23, 0.36, -0.30, 0.30)), ("W", (-0.36, -0.23, -0.30, 0.30))):
        parts.append(box(f"Dog bed rim {nm}", a[0], a[1], a[2], a[3], 0.03, 0.21, M["plush"], D, bevel=0.06, segments=6))
    for p in parts:
        p.parent = b
dog_bed(0.20, 1.05, 12)

# Ceiling fixture: 3 spot cans on a round base
FX, FY = 0.95, 0.35
cylinder("Ceiling fixture base", (FX, FY, H - 0.03), 0.09, 0.05, M["ceramic"], D)
for i in range(3):
    a = 2 * math.pi * i / 3 + 0.4
    p = Vector((FX + 0.13 * math.cos(a), FY + 0.13 * math.sin(a), H - 0.14))
    can = cylinder(f"Spot can {i}", p, 0.045, 0.11, M["ceramic"], D)
    can.rotation_euler = (math.radians(35) * math.sin(a), -math.radians(35) * math.cos(a), 0)
    cylinder(f"Spot bulb {i}", p - Vector((0, 0, 0.05)), 0.03, 0.005, M["bulb"], D)
# Hallway dome light
dome = cylinder("Hall dome", (-2.05, -0.07, H - 0.04), 0.17, 0.08, M["ceramic"], D, r2=0.12)
dome.data.materials[0] = M["bulb"]

# ==== Dining room glimpse (through the arch) ===============================================
box("Dining table top", 0.85, 2.10, 3.45, 4.35, 0.72, 0.76, M["darkwood"], D, bevel=0.005)
for (x, y) in [(0.90, 3.50), (2.05, 3.50), (0.90, 4.30), (2.05, 4.30)]:
    box("Dining table leg", x - 0.025, x + 0.025, y - 0.025, y + 0.025, 0, 0.72, M["darkwood"], D)
for i, (x, y, rz) in enumerate([(1.15, 3.20, 0), (1.80, 3.20, 0), (1.15, 4.60, 180), (1.80, 4.60, 180)]):
    ch = bpy.data.objects.new(f"Dining chair {i}", None)
    D.objects.link(ch)
    ch.location = (x, y, 0)
    ch.rotation_euler = (0, 0, math.radians(rz))
    parts = [box("Chair seat", -0.21, 0.21, -0.21, 0.21, 0.44, 0.48, M["darkwood"], D, bevel=0.005),
             box("Chair back", -0.21, 0.21, -0.23, -0.20, 0.48, 0.92, M["darkwood"], D, bevel=0.005)]
    for (lx, ly) in [(-0.19, -0.19), (0.19, -0.19), (-0.19, 0.19), (0.19, 0.19)]:
        parts.append(box("Chair leg", lx - 0.015, lx + 0.015, ly - 0.015, ly + 0.015, 0, 0.44, M["darkwood"], D))
    for p in parts:
        p.parent = ch
box("Washing machine", 0.05, 0.65, DINING_Y1 - 0.62, DINING_Y1 - 0.02, 0.0, 0.85, M["ceramic"], D, bevel=0.015)
wm = cylinder("Washing machine door", (0.35, DINING_Y1 - 0.625, 0.50), 0.17, 0.02, M["glass"], D)
wm.rotation_euler = (math.pi / 2, 0, 0)
cylinder("Pendant cord", (1.47, 3.90, H - 0.35), 0.004, 0.70, M["black"], D, verts=6)
cylinder("Pendant shade", (1.47, 3.90, H - 0.76), 0.03, 0.14, M["steel"], D, r2=0.13)
cylinder("Pendant bulb", (1.47, 3.90, H - 0.84), 0.035, 0.04, M["bulb"], D)

# ==== Lights ==============================================================================
def light(name, kind, loc, power, color, size=0.05, rot=(0, 0, 0), spot=None):
    ld = bpy.data.lights.new(name, kind)
    ld.energy = power
    ld.color = color
    if kind in ("POINT", "SPOT"):
        ld.shadow_soft_size = size
    if kind == "AREA":
        ld.size = size
    if spot:
        ld.spot_size = math.radians(spot)
        ld.spot_blend = 0.6
    o = bpy.data.objects.new(name, ld)
    C_LIGHT.objects.link(o)
    o.location = loc
    o.rotation_euler = rot
    return o
WARM, NEUTRAL = (1.0, 0.70, 0.42), (1.0, 0.82, 0.62)
light("Floor lamp bulb", "POINT", (2.38, 0.76, 1.47), 70, WARM, 0.06)
for i in range(3):
    a = 2 * math.pi * i / 3 + 0.4
    light(f"Ceiling spot {i}", "SPOT", (FX + 0.13 * math.cos(a), FY + 0.13 * math.sin(a), H - 0.2), 120, NEUTRAL, 0.03,
          rot=(math.radians(35) * math.sin(a), -math.radians(35) * math.cos(a), 0), spot=80)
light("Hall dome", "POINT", (-2.05, -0.07, H - 0.12), 60, NEUTRAL, 0.12)
light("Dining pendant", "POINT", (1.47, 3.90, H - 0.86), 60, WARM, 0.04)
light("Dining ceiling", "POINT", (1.0, 4.6, H - 0.2), 40, NEUTRAL, 0.1)
light("Red lamp", "POINT", (0.20, -2.50, 0.35), 12, (1.0, 0.18, 0.04), 0.07)
light("TV glow", "AREA", (RX0 + 0.35, TVY, TVZ), 6, (0.55, 0.65, 1.0), 1.0, rot=(0, math.radians(90), 0))

# ==== World, render, cameras ===============================================================
world = scene.world or bpy.data.worlds.new("World")
scene.world = world
world.use_nodes = True
bg = next(n for n in world.node_tree.nodes if n.type == "BACKGROUND")
bg.inputs["Color"].default_value = (0.004, 0.006, 0.012, 1)
bg.inputs["Strength"].default_value = 1.0

scene.render.engine = "CYCLES"
scene.cycles.samples = 256
scene.cycles.use_denoising = True
scene.view_settings.view_transform = "AgX"
scene.view_settings.exposure = 1.0
try:
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "OPTIX"
    prefs.get_devices()
    for d in prefs.devices:
        d.use = True
    scene.cycles.device = "GPU"
except Exception as e:  # CPU fallback
    print("GPU setup failed:", e)

C_CAM = collection("Cameras", root)
def camera(name, loc, look, lens=18):
    cd = bpy.data.cameras.new(name)
    cd.lens = lens
    cd.clip_start = 0.05
    o = bpy.data.objects.new(name, cd)
    C_CAM.objects.link(o)
    o.location = loc
    o.rotation_euler = (Vector(look) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    return o
cams = [camera("Cam from hallway", (-1.2, -0.05, 1.55), (2.4, -0.6, 0.9)),
        camera("Cam sofa to window", (0.4, 1.6, 1.5), (1.4, -2.7, 0.9)),
        camera("Cam window to arch", (1.0, -2.0, 1.5), (1.4, 2.6, 1.1)),
        camera("Cam TV wall", (2.0, 0.6, 1.4), (-0.35, -1.9, 1.0)),
        camera("Cam hallway", (-3.4, -0.07, 1.55), (0.5, -0.07, 1.0))]
scene.camera = cams[0]
scene.render.resolution_x, scene.render.resolution_y = 1600, 900
print("rebuild ok:", sum(len(c.objects) for c in (C_STRUCT, C_OPEN, C_FURN, C_DECOR, C_LIGHT, C_CAM)), "objects")

# ==== Scan (fused TSDF mesh with vertex colours), for side-by-side comparison ==============
C_SCAN = collection("Scan")
clear_collection(C_SCAN)
old = bpy.data.objects.get("home_living_mesh_icp")
if old:
    bpy.data.objects.remove(old, do_unlink=True)
if os.path.exists(SCAN):
    bpy.ops.wm.ply_import(filepath=SCAN)
    s = bpy.context.selected_objects[0]
    s.name = "Scan mesh"
    link(s, C_SCAN)
    sm = material("Scan vertex colour", rough=0.8)
    vc = sm.node_tree.nodes.new("ShaderNodeVertexColor")
    vc.layer_name = s.data.color_attributes[0].name
    sm.node_tree.links.new(vc.outputs["Color"], bsdf_of(sm).inputs["Base Color"])
    s.data.materials.clear()
    s.data.materials.append(sm)
    s.hide_render = True
    s.hide_viewport = True
print("scan:", "loaded" if os.path.exists(SCAN) else "missing", SCAN)
