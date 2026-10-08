"""Build a Blender scene from data/scenes/<scene>/scene.json (pipeline.py writes it from scene.yaml).

Headless (what pipeline.py does):
    blender -b -P agent_pipeline/blender/build_scene.py -- --scene <name> [--render review|cameras|all|none]
                 [--samples 64] [--percent 50] [--no-export]
Inside a live Blender (MCP execute_blender_code):
    import os; os.environ["SCENE"] = "<name>"; p = "<repo>/agent_pipeline/blender/build_scene.py"
    exec(open(p).read(), {"__file__": p, "__name__": "__main__"})

Outputs (data/scenes/<scene>/):
    blender/<scene>.blend          the scene (collections Rebuild/{Structure,Openings,Outside,Objects,Lights,Cameras}, Scan)
    blender/review/frame_NNNNNN.png renders from the VIDEO's own camera poses (compare.py pairs them with frames)
    blender/renders/<camera>.png   renders from the named cameras in scene.yaml
    export/<scene>_rebuild.glb     PBR glTF (lights + cameras) for the web viewer
"""
import json
import math
import os
import sys
import time

import bpy
from mathutils import Matrix, Vector

# Locate the repo without machine-specific paths: via __file__ (headless `-P`, or
# exec(open(p).read(), {"__file__": p}) from the MCP), else $LINGBOT_REPO.
if "__file__" in globals():
    HERE = os.path.dirname(os.path.abspath(__file__))
elif os.environ.get("LINGBOT_REPO"):
    HERE = os.path.join(os.environ["LINGBOT_REPO"], "agent_pipeline", "blender")
else:
    raise SystemExit('exec with {"__file__": path} or set LINGBOT_REPO')
sys.path.insert(0, HERE)
import importlib  # noqa: E402

import assets  # noqa: E402
import helpers  # noqa: E402
importlib.reload(helpers)
importlib.reload(assets)
from helpers import (box, clear_collection, collection, cylinder, image_plane, light, link, look_at_euler,  # noqa: E402
                     material, planar_uv, shade_smooth, bsdf_of)

REPO = os.path.dirname(os.path.dirname(HERE))


def args():
    a = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    opt = {"scene": os.environ.get("SCENE"), "render": os.environ.get("RENDER", "review"),
           "samples": int(os.environ.get("SAMPLES", 64)), "percent": int(os.environ.get("PERCENT", 50)),
           "export": True}
    i = 0
    while i < len(a):
        k = a[i]
        if k == "--no-export":
            opt["export"] = False
        else:
            opt[k.lstrip("-")] = a[i + 1]
            i += 1
        i += 1
    opt["samples"], opt["percent"] = int(opt["samples"]), int(opt["percent"])
    if not opt["scene"]:
        raise SystemExit("pass --scene <name> (or set SCENE)")
    return opt


OPT = args()
NAME = OPT["scene"]
ROOT = os.path.join(REPO, "data", "scenes", NAME)
SPEC = json.load(open(os.path.join(ROOT, "scene.json")))
TEX = os.path.join(ROOT, "textures")
D = SPEC.get("defaults", {})
T = D.get("wall_thickness", 0.15)
H = D.get("ceiling_height", 2.70)

# Headless `blender -b` without a .blend opens the factory scene: its default Cube (2 m, top at z=1),
# Light and Camera end up inside the room. Start empty; in a live session only drop those defaults.
if bpy.app.background:
    bpy.ops.wm.read_factory_settings(use_empty=True)
else:
    for n in ("Cube", "Light", "Camera"):
        if n in bpy.data.objects and not bpy.data.objects[n].users_collection[0].name.startswith(("Rebuild", "Scan")):
            bpy.data.objects.remove(bpy.data.objects[n], do_unlink=True)
scene = bpy.context.scene
root = collection("Rebuild")
clear_collection(root)
C = {k: collection(k, root) for k in ("Structure", "Openings", "Outside", "Objects", "Lights", "Cameras")}

# ---- materials ------------------------------------------------------------------------------
M = {k: material(v.get("label", k), v, TEX) for k, v in SPEC["materials"].items()}
for need in ("bulb", "black", "darkwood", "glass"):
    if need not in M:
        M[need] = material(need, {"bulb": {"color": [1, .9, .7], "emission": {"color": [1, .85, .6], "strength": 20}},
                                  "black": {"color": [.01, .01, .01], "roughness": .25},
                                  "darkwood": {"color": [.045, .028, .018], "roughness": .4},
                                  "glass": {"color": [.9, .95, .95], "roughness": .02, "transmission": 1}}[need], TEX)


def floor_uv(o, mat_key):
    uv = SPEC["materials"].get(mat_key, {}).get("uv")
    if uv:
        planar_uv(o, uv.get("scale", 1.0), uv.get("rotate", 0.0))


# ---- rooms: floor + ceiling slabs (+ crown moulding) ----------------------------------------
for r in SPEC.get("rooms", []):
    (x0, x1), (y0, y1) = r["x"], r["y"]
    h = r.get("height", H)
    f = box(f"Floor {r['name']}", (x0, y0, -0.02), (x1, y1, 0.0), M[r.get("floor", "floor")], C["Structure"])
    floor_uv(f, r.get("floor", "floor"))
    box(f"Ceiling {r['name']}", (x0, y0, h), (x1, y1, h + 0.05), M[r.get("ceiling", "ceiling")], C["Structure"])
    cr = r.get("crown")
    if cr:
        s, cm = cr.get("size", 0.05), M[cr.get("material", r.get("ceiling", "ceiling"))]
        for nm, a in (("S", (x0, x1, y0, y0 + s * 0.8)), ("N", (x0, x1, y1 - s * 0.8, y1)),
                      ("W", (x0, x0 + s * 0.8, y0, y1)), ("E", (x1 - s * 0.8, x1, y0, y1))):
            box(f"Crown {r['name']} {nm}", (a[0], a[2], h - s), (a[1], a[3], h), cm, C["Structure"], bevel=0.015)


# ---- walls ----------------------------------------------------------------------------------
class Wall:
    """Local frame: u along the wall axis, n across (0 = inner face, + into the room, -T = outer face)."""

    def __init__(self, w):
        self.w, self.axis, self.f, self.s = w, w["axis"], w["face"], w.get("room_side", 1)
        self.t = w.get("thickness", T)

    def p(self, u, n, z=0.0):
        return (u, self.f + self.s * n, z) if self.axis == "y" else (self.f + self.s * n, u, z)

    def box(self, name, u0, u1, n0, n1, z0, z1, mat, coll, **kw):
        a, b = self.p(u0, n0, z0), self.p(u1, n1, z1)
        return box(name, tuple(map(min, a, b)), tuple(map(max, a, b)), mat, coll, **kw)

    def facing_room(self):
        return ("+" if self.s > 0 else "-") + ("Y" if self.axis == "y" else "X")


def door_leaf(W, name, u0, width, open_deg, glass, top):
    hinge = W.p(u0, -(W.t - 0.03))
    leaf = bpy.data.objects.new(name, None)
    C["Openings"].objects.link(leaf)
    leaf.location = hinge
    parts = [box(name + " leaf", (0, -0.02, 0), (width, 0.02, top - 0.01), M["trim"], C["Openings"], bevel=0.004),
             box(name + " panel", (0.12, -0.026, 0.18), (width - 0.12, 0.026, 0.92), M["trim"], C["Openings"], bevel=0.01),
             box(name + " handle", (width - 0.10, -0.07, 1.0), (width - 0.04, 0.07, 1.03), M.get("brass", M["trim"]), C["Openings"], bevel=0.01)]
    if glass:
        parts.append(box(name + " glass", (0.12, -0.025, 1.05), (width - 0.12, 0.025, 1.90), M["glass"], C["Openings"]))
    for p in parts:
        p.parent = leaf
    th = math.radians(open_deg)       # > 0 swings away from the room
    leaf.rotation_euler = (0, 0, -W.s * th) if W.axis == "y" else (0, 0, math.pi / 2 + W.s * th)


def casing(W, name, u0, u1, top):
    for nm, a, b, z0, z1 in ((" L", u0 - 0.07, u0, 0, top + 0.07), (" R", u1, u1 + 0.07, 0, top + 0.07),
                             (" T", u0 - 0.07, u1 + 0.07, top, top + 0.07)):
        W.box(name + nm, a, b, 0, 0.02, z0, z1, M["trim"], C["Openings"], bevel=0.005)


def arch(W, name, u0, u1, spring, lintel, trim_mat, threshold):
    r = (u1 - u0) / 2
    cu = (u0 + u1) / 2
    cut = cylinder(name + " cutter", W.p(cu, -W.t / 2, spring), r, W.t * 3, M["trim"], C["Structure"], verts=64)
    cut.rotation_euler = (math.pi / 2, 0, 0) if W.axis == "y" else (math.pi / 2, 0, math.pi / 2)
    bo = lintel.modifiers.new("Arch", "BOOLEAN")
    bo.object, bo.operation, bo.solver = cut, "DIFFERENCE", "EXACT"
    bpy.context.view_layer.objects.active = lintel
    with bpy.context.temp_override(object=lintel, active_object=lintel):
        bpy.ops.object.modifier_apply(modifier="Arch")
    bpy.data.objects.remove(cut, do_unlink=True)
    if trim_mat:
        import bmesh
        me = bpy.data.meshes.new(name + " trim")
        bm = bmesh.new()
        pts = [(u0, 0.0), (u0, spring)] + [(cu + r * math.cos(math.pi - math.pi * i / 32), spring + r * math.sin(math.pi - math.pi * i / 32)) for i in range(1, 32)] + [(u1, spring), (u1, 0.0)]
        rings = []
        for (u, z) in pts:
            nrm = Vector((u - cu, 0, z - spring)) if z > spring else Vector((1 if u > cu else -1, 0, 0))
            nrm.normalize()
            rings.append(((u, z), (u + nrm.x * 0.06, z + nrm.z * 0.06)))
        for n in (0.01, -W.t - 0.01):
            prev = None
            for (iu, iz), (ou, oz) in rings:
                a, b = bm.verts.new(W.p(iu, n, iz)), bm.verts.new(W.p(ou, n, oz))
                if prev:
                    bm.faces.new((prev[0], prev[1], b, a))
                prev = (a, b)
        prev = None
        for (iu, iz), _ in rings:
            a, b = bm.verts.new(W.p(iu, 0.01, iz)), bm.verts.new(W.p(iu, -W.t - 0.01, iz))
            if prev:
                bm.faces.new((prev[0], prev[1], b, a))
            prev = (a, b)
        bm.to_mesh(me)
        bm.free()
        o = bpy.data.objects.new(name + " trim", me)
        C["Openings"].objects.link(o)
        me.materials.append(M[trim_mat])
        o.modifiers.new("Solid", "SOLIDIFY").thickness = 0.015
        shade_smooth(o)
    if threshold:
        W.box(name + " threshold", u0, u1, 0.01, -W.t - 0.01, 0.0, 0.012, M[trim_mat or "trim"], C["Openings"], bevel=0.004)


def sliding_window(W, name, u0, u1, top, f):
    alu, glass = M[f.get("frame_material", "alu")], M["glass"]
    c = -W.t / 2
    W.box(name + " frame bottom", u0, u1, c - 0.06, c + 0.06, 0.0, 0.05, alu, C["Openings"], bevel=0.004)
    W.box(name + " frame top", u0, u1, c - 0.06, c + 0.06, top - 0.05, top, alu, C["Openings"], bevel=0.004)
    W.box(name + " frame L", u0, u0 + 0.05, c - 0.06, c + 0.06, 0, top, alu, C["Openings"], bevel=0.004)
    W.box(name + " frame R", u1 - 0.05, u1, c - 0.06, c + 0.06, 0, top, alu, C["Openings"], bevel=0.004)
    n = f.get("panels", 2)
    pw = (u1 - u0) / n
    for i in range(n):
        a = u0 + i * (pw - 0.04 / max(n - 1, 1))
        b = a + pw + 0.04
        o = c + (-0.025 if i % 2 == 0 else 0.025)
        for nm, (ua, ub, za, zb, d) in {"stile L": (a, a + 0.045, 0.05, top - 0.05, 0.015), "stile R": (b - 0.045, b, 0.05, top - 0.05, 0.015),
                                        "rail B": (a, b, 0.05, 0.12, 0.015), "rail T": (a, b, top - 0.11, top - 0.05, 0.015),
                                        "rail M": (a, b, 0.95, 0.99, 0.012)}.items():
            W.box(f"{name} sash {i} {nm}", ua, ub, o - d, o + d, za, zb, alu, C["Openings"], bevel=0.003)
        W.box(f"{name} sash {i} glass", a + 0.045, b - 0.045, o - 0.004, o + 0.004, 0.12, top - 0.11, glass, C["Openings"])
    if f.get("blind_box", True):
        W.box(name + " blind box", u0 - 0.25, u1 + 0.25, 0, 0.17, top, top + 0.24, M["trim"], C["Openings"], bevel=0.01)
    out = f.get("outside") or {}
    if out.get("balcony_depth"):
        bd = out["balcony_depth"]
        W.box(name + " balcony floor", u0 - 0.6, u1 + 0.6, -W.t, -bd, -0.03, 0.0, M[out.get("balcony_material", "darkwood")], C["Outside"])
        W.box(name + " balcony rail", u0 - 0.6, u1 + 0.6, -bd - 0.02, -bd + 0.02, 0.95, 1.0, M["black"], C["Outside"])
    bd = out.get("backdrop")
    if bd:
        image_plane(name + " view", W.p((u0 + u1) / 2, -bd.get("distance", 3.0), bd.get("z", 1.3)), bd.get("size", [3.6, 3.8]),
                    W.facing_room(), M[bd["material"]], C["Outside"])


for w in SPEC.get("walls", []):
    W = Wall(w)
    nm = f"Wall {w['name']}"
    top_z = w.get("height", H)
    a0, a1 = w["span"]
    ops = sorted(w.get("openings", []), key=lambda o: o["span"][0])
    cur, lintels = a0, {}
    for k, o in enumerate(ops):
        oa, ob = o["span"]
        if oa > cur:
            W.box(nm, cur, oa, -W.t, 0, 0, top_z, M[w.get("material", "wall")], C["Structure"])
        if o.get("bottom", 0) > 0:
            W.box(nm + " sill", oa, ob, -W.t, 0, 0, o["bottom"], M[w.get("material", "wall")], C["Structure"])
        if o["top"] < top_z:
            lintels[k] = W.box(nm + " lintel", oa, ob, -W.t, 0, o["top"], top_z, M[w.get("material", "wall")], C["Structure"])
        cur = ob
    if cur < a1:
        W.box(nm, cur, a1, -W.t, 0, 0, top_z, M[w.get("material", "wall")], C["Structure"])
    # baseboards on the room side, interrupted by openings that reach the floor
    bb = w.get("baseboard", D.get("baseboard"))
    if bb:
        cuts = [o["span"] for o in ops if o.get("bottom", 0) == 0]
        cur = a0
        for (oa, ob) in cuts + [(a1, a1)]:
            if oa > cur:
                W.box(nm + " baseboard", cur, oa, 0, 0.012, 0, bb.get("height", 0.09), M[bb.get("material", "trim")], C["Structure"])
            cur = max(cur, ob)
    for k, o in enumerate(ops):
        f = o.get("fill") or {"type": "none"}
        oa, ob = o["span"]
        on = f"{nm} {f.get('name', f['type'])} {k}"
        if f.get("casing", f["type"] in ("door", "none")):
            casing(W, on + " casing", oa, ob, o["top"])
        if f["type"] == "door":
            door_leaf(W, on, oa, ob - oa, f.get("open_deg", 0), f.get("glass", True), o["top"])
        elif f["type"] == "arch":
            arch(W, on, oa, ob, o["top"], lintels[k], f.get("trim_material"), f.get("threshold", True))
        elif f["type"] == "sliding_window":
            sliding_window(W, on, oa, ob, o["top"], f)

# ---- objects / lights -----------------------------------------------------------------------
cx = assets.Ctx(M, C["Objects"], C["Lights"], H)
for o in SPEC.get("objects", []):
    assets.build(o, cx)
for L in SPEC.get("lights", []):
    light(L["name"], L.get("type", "POINT").upper(), L["pos"], L.get("power", 60), tuple(L.get("color", (1, .8, .6))),
          C["Lights"], size=L.get("size", 0.05), rot=tuple(math.radians(a) for a in L.get("rotate", (0, 0, 0))),
          spot_deg=L.get("cone"))

# ---- world / render -------------------------------------------------------------------------
R = SPEC.get("render", {})
world = scene.world or bpy.data.worlds.new("World")
scene.world = world
world.use_nodes = True
bg = next(n for n in world.node_tree.nodes if n.type == "BACKGROUND")
bg.inputs["Color"].default_value = (*helpers.lin(R.get("world_color", [0.05, 0.05, 0.06])), 1)
scene.render.engine = "CYCLES"
scene.cycles.samples = R.get("samples", 256)
scene.cycles.use_denoising = True
scene.view_settings.view_transform = R.get("view_transform", "AgX")
scene.view_settings.exposure = R.get("exposure", 1.0)
scene.render.resolution_x, scene.render.resolution_y = R.get("resolution", [1600, 900])
try:
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "OPTIX"
    prefs.get_devices()
    for d in prefs.devices:
        d.use = True
    scene.cycles.device = "GPU"
except Exception as e:  # noqa: BLE001
    print("GPU setup failed, using CPU:", e)

# ---- cameras: named views + the video's own poses -------------------------------------------
cams = []
for c in SPEC.get("cameras", []):
    cd = bpy.data.cameras.new(c["name"])
    cd.lens, cd.clip_start = c.get("lens", 18), 0.05
    o = bpy.data.objects.new(c["name"], cd)
    C["Cameras"].objects.link(o)
    o.location = c["pos"]
    o.rotation_euler = look_at_euler(c["pos"], c["look_at"])
    cams.append(o)
review_cams = []
rv = SPEC.get("review", {})
if rv.get("frames"):
    import numpy as np
    poses = np.load(os.path.join(ROOT, "poses.npy"))
    Ks = np.load(os.path.join(ROOT, "frames", "K.npy"))
    w, h = json.load(open(os.path.join(ROOT, "frames", "meta.json")))["size"]
for fi in rv.get("frames", []):
    P, K = poses[fi], Ks[fi]
    cd = bpy.data.cameras.new(f"Frame {fi:06d}")
    cd.sensor_fit, cd.sensor_width = "HORIZONTAL", 36.0
    cd.lens = K[0, 0] * 36.0 / w
    cd.shift_x, cd.shift_y = -(K[0, 2] - w / 2) / w, (K[1, 2] - h / 2) / w
    cd.clip_start = 0.05
    o = bpy.data.objects.new(f"Frame {fi:06d}", cd)
    C["Cameras"].objects.link(o)
    o.matrix_world = Matrix(P.tolist()) @ Matrix.Diagonal((1, -1, -1, 1))     # OpenCV -> Blender camera axes
    o["frame"], o["res"] = int(fi), [w, h]
    review_cams.append(o)
if cams:
    scene.camera = cams[0]

# ---- scan reference -------------------------------------------------------------------------
CS = collection("Scan")
clear_collection(CS)
scan = os.path.join(ROOT, "mesh.ply")
if os.path.exists(scan):
    bpy.ops.wm.ply_import(filepath=scan)
    s = bpy.context.selected_objects[0]
    s.name = "Scan mesh"
    link(s, CS)
    sm = material("Scan vertex colour", {"roughness": 0.8}, TEX)
    vc = sm.node_tree.nodes.new("ShaderNodeVertexColor")
    vc.layer_name = s.data.color_attributes[0].name
    sm.node_tree.links.new(vc.outputs["Color"], bsdf_of(sm).inputs["Base Color"])
    s.data.materials.clear()
    s.data.materials.append(sm)
    s.hide_render = s.hide_viewport = True

n_obj = sum(len(c.objects) for c in C.values())
print(f"[build] {NAME}: {n_obj} objects, {len(M)} materials, {len(cams)} cameras, {len(review_cams)} review cameras")

# ---- save / render / export -----------------------------------------------------------------
os.makedirs(os.path.join(ROOT, "blender"), exist_ok=True)
blend = os.path.join(ROOT, "blender", f"{NAME}.blend")
if bpy.app.background or OPT.get("save"):
    bpy.ops.wm.save_as_mainfile(filepath=blend)
    print("[build] saved", blend)


def render_to(cam, path, res=None):
    scene.camera = cam
    if res:
        scene.render.resolution_x, scene.render.resolution_y = res
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)


mode = OPT["render"]
if mode != "none":
    scene.cycles.samples = OPT["samples"]
    scene.render.resolution_percentage = OPT["percent"]
    t0 = time.time()
    base_res = R.get("resolution", [1600, 900])
    if mode in ("review", "all"):
        for o in review_cams:
            w, h = o["res"]
            k = max(1, round(base_res[0] / w))           # render review frames at ~base width
            render_to(o, os.path.join(ROOT, "blender", "review", f"frame_{o['frame']:06d}.png"), (w * k, h * k))
    if mode in ("cameras", "all"):
        for o in cams:
            render_to(o, os.path.join(ROOT, "blender", "renders", o.name.replace(" ", "_") + ".png"), base_res)
    scene.render.resolution_x, scene.render.resolution_y = base_res
    scene.render.resolution_percentage = 100
    scene.cycles.samples = R.get("samples", 256)
    if cams:
        scene.camera = cams[0]
    print(f"[build] rendered ({mode}) in {time.time() - t0:.0f}s")

if OPT["export"]:
    os.makedirs(os.path.join(ROOT, "export"), exist_ok=True)
    out = os.path.join(ROOT, "export", f"{NAME}_rebuild.glb")
    for c in bpy.context.view_layer.layer_collection.children:
        if c.name == "Rebuild":
            bpy.context.view_layer.active_layer_collection = c
    bpy.ops.export_scene.gltf(filepath=out, export_format="GLB", use_active_collection=True,
                              use_active_collection_with_nested=True, export_apply=True, export_lights=True,
                              export_cameras=True, export_yup=True, export_image_format="JPEG", export_jpeg_quality=90)
    print("[build] exported", out)
