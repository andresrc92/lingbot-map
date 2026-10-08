"""Bake the Rebuild collection's Cycles lighting into one texture atlas for the web.

Run inside Blender after build_blender.py:

    exec(open("<repo>/blender_pipeline/bake_blender.py").read())

All opaque meshes are duplicated, modifiers applied, joined into "Baked" with a fresh
"Lightmap" UV atlas, and their full diffuse appearance (albedo x direct + indirect light,
plus emission) is baked into one image. The result is exported as an unlit GLB together
with the transparent pieces (glass, sheer curtains), which keep their PBR materials.
"""
import os
import time

import bpy

REPO = os.environ.get("LINGBOT_REPO", "/home/andres/focus/IAC/lingbot/lingbot-map")
OUT = os.path.join(REPO, "data", "blender", "export")
RES = int(os.environ.get("BAKE_RES", 8192))
SAMPLES = int(os.environ.get("BAKE_SAMPLES", 256))
TRANSPARENT = ("Glass", "Sheer curtain")          # materials kept live (not baked)

scene = bpy.context.scene
src = [o for o in bpy.data.collections["Rebuild"].all_objects
       if o.type == "MESH" and not o.hide_render]

bake_coll = bpy.data.collections.get("Baked") or bpy.data.collections.new("Baked")
if bake_coll.name not in scene.collection.children:
    scene.collection.children.link(bake_coll)
bake_coll.hide_viewport = bake_coll.hide_render = False
for o in list(bake_coll.objects):
    bpy.data.objects.remove(o, do_unlink=True)

# Duplicate with modifiers applied (evaluated mesh), world transform baked in.
deps = bpy.context.evaluated_depsgraph_get()
opaque, live = [], []
for o in src:
    me = bpy.data.meshes.new_from_object(o.evaluated_get(deps))
    me.transform(o.matrix_world)
    d = bpy.data.objects.new(o.name + " (bake)", me)
    bake_coll.objects.link(d)
    mats = [m.name for m in me.materials if m]
    (live if mats and all(m in TRANSPARENT for m in mats) else opaque).append(d)

# Join the opaque pieces.
bpy.ops.object.select_all(action="DESELECT")
for d in opaque:
    d.select_set(True)
bpy.context.view_layer.objects.active = opaque[0]
bpy.ops.object.join()
baked = bpy.context.view_layer.objects.active
baked.name = "Baked"
print("joined", len(opaque), "objects ->", len(baked.data.polygons), "faces;", len(live), "live (transparent)")

# Drop faces nobody can see: those whose outward normal leads outside the interior volume
# (union of the room floors' footprints up to the ceiling, plus the balcony / night view).
import bmesh
from mathutils import Vector
def bounds(name, pad=0.0):
    o = bpy.data.objects[name]
    pts = [o.matrix_world @ Vector(c) for c in o.bound_box]
    return (min(p.x for p in pts) - pad, max(p.x for p in pts) + pad, min(p.y for p in pts) - pad, max(p.y for p in pts) + pad)
ceil_z = min((bpy.data.objects["Ceiling living"].matrix_world @ Vector(c)).z for c in bpy.data.objects["Ceiling living"].bound_box)
rooms = [bounds(n) for n in ("Floor living", "Floor hallway", "Floor dining")]
bx = bounds("Balcony floor")
nv = bounds("Night view", 0.3)
outside = [(bx[0], bx[1], nv[2], bx[3])]
def inside(p):
    if 0.0 <= p.z <= ceil_z and any(r[0] <= p.x <= r[1] and r[2] <= p.y <= r[3] for r in rooms):
        return True
    return any(r[0] <= p.x <= r[1] and r[2] <= p.y <= r[3] for r in outside) and -0.1 <= p.z <= 4.0
bm = bmesh.new()
bm.from_mesh(baked.data)
dead = [f for f in bm.faces if not inside(f.calc_center_median() + f.normal * 0.02)]
bmesh.ops.delete(bm, geom=dead, context="FACES")
bm.to_mesh(baked.data)
bm.free()
print("removed", len(dead), "hidden faces ->", len(baked.data.polygons))

# Lightmap UVs.
uv = baked.data.uv_layers.new(name="Lightmap")
baked.data.uv_layers.active = uv
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.select_all(action="SELECT")
bpy.ops.uv.smart_project(angle_limit=1.15, island_margin=0.0015, area_weight=0.0, scale_to_bounds=True)
bpy.ops.object.mode_set(mode="OBJECT")

# Target image; every material gets an active image node that uses the Lightmap UVs.
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
for o in src:                                  # the joined copy replaces them (no coplanar doubles)
    o.hide_render = True
t0 = time.time()
try:
    bpy.ops.object.bake(type="COMBINED", use_clear=True)
finally:
    for o in src:
        o.hide_render = False
print(f"baked {RES}px x {SAMPLES} spp in {time.time() - t0:.0f}s")
for m in baked.data.materials:                 # these materials are shared with the originals
    for n in [n for n in m.node_tree.nodes if n.name in ("BakeTarget", "BakeUV")]:
        m.node_tree.nodes.remove(n)

# Save: raw EXR (scene-linear) and a display-referred PNG through the scene's view transform
# (AgX + exposure), so the unlit web version matches the Cycles renders.
img.filepath_raw = os.path.join(OUT, "baked_raw.exr")
img.file_format = "OPEN_EXR"
img.save()
ldr = os.path.join(OUT, "baked_lighting.png")
img.save_render(ldr, scene=scene)
print("saved", ldr)

# Single material using the atlas on the Lightmap UVs; drop the original UVs.
mat = bpy.data.materials.get("Baked lighting") or bpy.data.materials.new("Baked lighting")
mat.use_nodes = True
nt = mat.node_tree
for n in list(nt.nodes):
    if n.type not in ("BSDF_PRINCIPLED", "OUTPUT_MATERIAL"):
        nt.nodes.remove(n)
bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
tex = nt.nodes.new("ShaderNodeTexImage")
tex.image = bpy.data.images.load(ldr, check_existing=False)
tex.image.name = "baked_lighting"
nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
nt.links.new(tex.outputs["Color"], bsdf.inputs["Emission Color"])
bsdf.inputs["Emission Strength"].default_value = 1.0
bsdf.inputs["Roughness"].default_value = 1.0
baked.data.materials.clear()
baked.data.materials.append(mat)
for layer in [l for l in baked.data.uv_layers if l.name != "Lightmap"]:
    baked.data.uv_layers.remove(layer)

# Export Baked + the live transparent pieces.
bpy.ops.object.select_all(action="DESELECT")
for o in [baked] + live:
    o.select_set(True)
bpy.ops.export_scene.gltf(filepath=os.path.join(OUT, "home_living_baked.glb"), export_format="GLB",
                          use_selection=True, export_apply=True, export_yup=True,
                          export_image_format="JPEG", export_jpeg_quality=92)
bake_coll.hide_render = True
bake_coll.hide_viewport = True
print("exported", os.path.join(OUT, "home_living_baked.glb"))
