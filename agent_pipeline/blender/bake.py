"""Bake the scene's Cycles lighting into one texture atlas -> unlit GLB for the web viewer.

Headless (pipeline.py runs this after build_scene.py saved the .blend):
    blender -b data/scenes/<scene>/blender/<scene>.blend -P agent_pipeline/blender/bake.py -- --scene <scene> [--res 8192] [--samples 256]

Steps (each one fixed a real failure on the first scene):
1. Duplicate + join every opaque mesh of the Rebuild collection (modifiers applied, world transform baked).
   Glass / alpha materials stay separate "live" objects (baking them is meaningless).
2. Delete faces nobody can see: those whose normal leads outside the interior volume (rooms from
   scene.json + the bounds of the "Outside" collection, e.g. balcony / window backdrop). ~25% of faces;
   otherwise they waste atlas space on night-sky colour.
3. Smart-UV-project a "Lightmap" atlas.
4. HIDE THE ORIGINALS while baking: coplanar duplicates shadow each other.
5. Bake COMBINED (diffuse direct+indirect+colour + emission, no glossy) -> save through the scene's
   view transform (AgX + exposure) so the unlit atlas matches the Cycles renders.
6. Export Baked + live pieces as data/scenes/<scene>/export/<scene>_baked.glb.
Time: 8192 px x 256 spp took ~10 min on an RTX 4050 laptop (6 GB). Use --res 2048 --samples 16 to test.
"""
import json
import os
import sys
import time

import bmesh
import bpy
from mathutils import Vector

a = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
opt = dict(zip(a[::2], a[1::2]))
NAME = opt.get("--scene") or os.environ.get("SCENE")
RES = int(opt.get("--res", os.environ.get("BAKE_RES", 8192)))
SAMPLES = int(opt.get("--samples", os.environ.get("BAKE_SAMPLES", 256)))
if "__file__" in globals():
    REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
else:
    REPO = os.environ["LINGBOT_REPO"]
ROOT = os.path.join(REPO, "data", "scenes", NAME)
OUT = os.path.join(ROOT, "export")
os.makedirs(OUT, exist_ok=True)
SPEC = json.load(open(os.path.join(ROOT, "scene.json")))

scene = bpy.context.scene
src = [o for o in bpy.data.collections["Rebuild"].all_objects if o.type == "MESH" and not o.hide_render]
bake_coll = bpy.data.collections.get("Baked") or bpy.data.collections.new("Baked")
if bake_coll.name not in scene.collection.children:
    scene.collection.children.link(bake_coll)
bake_coll.hide_viewport = bake_coll.hide_render = False
for lc in bpy.context.view_layer.layer_collection.children:
    if lc.name == "Baked":
        lc.hide_viewport = lc.exclude = False
for o in list(bake_coll.objects):
    bpy.data.objects.remove(o, do_unlink=True)


def is_live(mats):
    def transparent(m):
        b = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None) if m.use_nodes else None
        return b is not None and (b.inputs["Transmission Weight"].default_value > 0.5 or b.inputs["Alpha"].default_value < 1)
    return bool(mats) and all(transparent(m) for m in mats)


deps = bpy.context.evaluated_depsgraph_get()
opaque, live = [], []
for o in src:
    me = bpy.data.meshes.new_from_object(o.evaluated_get(deps))
    me.transform(o.matrix_world)
    d = bpy.data.objects.new(o.name + " (bake)", me)
    bake_coll.objects.link(d)
    (live if is_live([m for m in me.materials if m]) else opaque).append(d)

bpy.ops.object.select_all(action="DESELECT")
for d in opaque:
    d.select_set(True)
bpy.context.view_layer.objects.active = opaque[0]
bpy.ops.object.join()
baked = bpy.context.view_layer.objects.active
baked.name = "Baked"
print(f"[bake] joined {len(opaque)} objects -> {len(baked.data.polygons)} faces; {len(live)} live")

# interior volume: rooms (z 0..height) + Outside collection bounds
D = SPEC.get("defaults", {})
rooms = [(r["x"][0], r["x"][1], r["y"][0], r["y"][1], r.get("height", D.get("ceiling_height", 2.7))) for r in SPEC.get("rooms", [])]
outside = []
if "Outside" in bpy.data.collections:
    for o in bpy.data.collections["Outside"].all_objects:
        pts = [o.matrix_world @ Vector(c) for c in o.bound_box]
        outside.append((min(p.x for p in pts) - 0.3, max(p.x for p in pts) + 0.3,
                        min(p.y for p in pts) - 0.3, max(p.y for p in pts) + 0.3))


def inside(p):
    if any(r[0] <= p.x <= r[1] and r[2] <= p.y <= r[3] and 0.0 <= p.z <= r[4] for r in rooms):
        return True
    return any(r[0] <= p.x <= r[1] and r[2] <= p.y <= r[3] for r in outside) and -0.1 <= p.z <= 4.0


bm = bmesh.new()
bm.from_mesh(baked.data)
dead = [f for f in bm.faces if not inside(f.calc_center_median() + f.normal * 0.02)]
bmesh.ops.delete(bm, geom=dead, context="FACES")
bm.to_mesh(baked.data)
bm.free()
print(f"[bake] removed {len(dead)} hidden faces -> {len(baked.data.polygons)}")

uv = baked.data.uv_layers.new(name="Lightmap")
baked.data.uv_layers.active = uv
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.select_all(action="SELECT")
bpy.ops.uv.smart_project(angle_limit=1.15, island_margin=0.0015, area_weight=0.0, scale_to_bounds=True)
bpy.ops.object.mode_set(mode="OBJECT")

img = bpy.data.images.get("Baked lighting") or bpy.data.images.new("Baked lighting", RES, RES, float_buffer=True)
if tuple(img.size) != (RES, RES):
    img.scale(RES, RES)
for m in baked.data.materials:
    nt = m.node_tree
    for n in [n for n in nt.nodes if n.name in ("BakeTarget", "BakeUV")]:
        nt.nodes.remove(n)
    t = nt.nodes.new("ShaderNodeTexImage"); t.name = "BakeTarget"; t.image = img
    u = nt.nodes.new("ShaderNodeUVMap"); u.name = "BakeUV"; u.uv_map = "Lightmap"
    nt.links.new(u.outputs["UV"], t.inputs["Vector"])
    nt.nodes.active = t

scene.render.engine = "CYCLES"
scene.cycles.samples = SAMPLES
scene.cycles.use_denoising = False
bk = scene.render.bake
bk.margin = 6
bk.use_pass_direct = bk.use_pass_indirect = True
bk.use_pass_diffuse = bk.use_pass_emit = True
bk.use_pass_glossy = bk.use_pass_transmission = False
bpy.ops.object.select_all(action="DESELECT")
baked.select_set(True)
bpy.context.view_layer.objects.active = baked
for o in src:
    o.hide_render = True
t0 = time.time()
try:
    bpy.ops.object.bake(type="COMBINED", use_clear=True)
finally:
    for o in src:
        o.hide_render = False
print(f"[bake] {RES}px x {SAMPLES} spp in {time.time() - t0:.0f}s")
for m in baked.data.materials:
    for n in [n for n in m.node_tree.nodes if n.name in ("BakeTarget", "BakeUV")]:
        m.node_tree.nodes.remove(n)

ldr = os.path.join(OUT, "baked_lighting.png")
img.save_render(ldr, scene=scene)
mat = bpy.data.materials.get("Baked lighting") or bpy.data.materials.new("Baked lighting")
mat.use_nodes = True
nt = mat.node_tree
for n in list(nt.nodes):
    if n.type not in ("BSDF_PRINCIPLED", "OUTPUT_MATERIAL"):
        nt.nodes.remove(n)
b = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
tex = nt.nodes.new("ShaderNodeTexImage")
tex.image = bpy.data.images.load(ldr, check_existing=False)
tex.image.name = "baked_lighting"
nt.links.new(tex.outputs["Color"], b.inputs["Base Color"])
nt.links.new(tex.outputs["Color"], b.inputs["Emission Color"])
b.inputs["Emission Strength"].default_value = 1.0
b.inputs["Roughness"].default_value = 1.0
baked.data.materials.clear()
baked.data.materials.append(mat)
for layer in [l for l in baked.data.uv_layers if l.name != "Lightmap"]:
    baked.data.uv_layers.remove(layer)

bpy.ops.object.select_all(action="DESELECT")
for o in [baked] + live:
    o.select_set(True)
out = os.path.join(OUT, f"{NAME}_baked.glb")
bpy.ops.export_scene.gltf(filepath=out, export_format="GLB", use_selection=True, export_apply=True, export_yup=True,
                          export_image_format="JPEG", export_jpeg_quality=92)
bake_coll.hide_render = True
# The .blend is NOT re-saved: its timestamp drives pipeline staleness (build -> compare -> bake).
print("[bake] exported", out)
