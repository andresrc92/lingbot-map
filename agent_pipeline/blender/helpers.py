"""Geometry and material primitives for the scene builder (runs inside Blender).

Hard-won rules baked in here:
- Colours in scene.yaml are sRGB (as picked from video frames); Blender sockets are linear -> lin().
- Unbevelled boxes stay FLAT shaded: smooth-shading a thin box makes glass act as a lens.
- Bevelled boxes get a WeightedNormal modifier so large faces stay flat.
"""
import math
import os

import bmesh
import bpy
from mathutils import Vector


def lin(c):
    return tuple(x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c)


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


def bsdf_of(m):
    return next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")


def material(name, spec, tex_dir):
    """spec keys: color, roughness, metallic, transmission, sheen, coat, alpha, emission
    ({color, strength}), texture, texture_emits (bool, strength = emission.strength or 1),
    roughness_texture. uv (scale/rotate) is applied per object by the builder."""
    m = bpy.data.materials.get(name)
    if m:
        bpy.data.materials.remove(m)
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    b = bsdf_of(m)
    b.inputs["Base Color"].default_value = (*lin(spec.get("color", (0.8, 0.8, 0.8))), 1)
    b.inputs["Roughness"].default_value = spec.get("roughness", 0.5)
    b.inputs["Metallic"].default_value = spec.get("metallic", 0.0)
    if spec.get("transmission"):
        b.inputs["Transmission Weight"].default_value = spec["transmission"]
    if spec.get("sheen"):
        b.inputs["Sheen Weight"].default_value = spec["sheen"]
    if spec.get("coat"):
        b.inputs["Coat Weight"].default_value = spec["coat"]
        b.inputs["Coat Roughness"].default_value = 0.08
    em = spec.get("emission")
    if em:
        b.inputs["Emission Color"].default_value = (*lin(em.get("color", (1, 1, 1))), 1)
        b.inputs["Emission Strength"].default_value = em.get("strength", 1.0)
    if spec.get("alpha", 1.0) < 1:
        b.inputs["Alpha"].default_value = spec["alpha"]
        m.surface_render_method = "BLENDED"
    if spec.get("texture"):
        t = nt.nodes.new("ShaderNodeTexImage")
        t.image = bpy.data.images.load(os.path.join(tex_dir, spec["texture"]), check_existing=True)
        nt.links.new(t.outputs["Color"], b.inputs["Base Color"])
        if spec.get("texture_emits"):
            nt.links.new(t.outputs["Color"], b.inputs["Emission Color"])
            b.inputs["Emission Strength"].default_value = (em or {}).get("strength", 1.0)
    if spec.get("roughness_texture"):
        r = nt.nodes.new("ShaderNodeTexImage")
        r.image = bpy.data.images.load(os.path.join(tex_dir, spec["roughness_texture"]), check_existing=True)
        r.image.colorspace_settings.name = "Non-Color"
        nt.links.new(r.outputs["Color"], b.inputs["Roughness"])
    m["uv"] = spec.get("uv") or {}
    return m


def shade_smooth(o):
    for p in o.data.polygons:
        p.use_smooth = True


def box(name, mn, mx, mat, coll, bevel=0.0, segments=3):
    """Axis-aligned box from min/max corners (world), origin at its centre."""
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    sx, sy, sz = (mx[0] - mn[0]), (mx[1] - mn[1]), (mx[2] - mn[2])
    for v in bm.verts:
        v.co = Vector((v.co.x * sx, v.co.y * sy, v.co.z * sz))
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    coll.objects.link(o)
    o.location = ((mn[0] + mx[0]) / 2, (mn[1] + mx[1]) / 2, (mn[2] + mx[2]) / 2)
    me.materials.append(mat)
    if bevel:
        md = o.modifiers.new("Bevel", "BEVEL")
        md.width = bevel
        md.segments = segments
        md.limit_method = "ANGLE"
        o.modifiers.new("WeightedNormal", "WEIGHTED_NORMAL").keep_sharp = True
        shade_smooth(o)
    return o


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


FACING = {"+X": (math.pi / 2, 0, math.pi / 2), "-X": (math.pi / 2, 0, -math.pi / 2),
          "+Y": (math.pi / 2, 0, math.pi), "-Y": (math.pi / 2, 0, 0)}


def image_plane(name, center, size, facing, mat, coll):
    """Plane with 0..1 UVs whose front faces +X/-X/+Y/-Y (e.g. a painting or screen)."""
    w, h = size
    me = bpy.data.meshes.new(name)
    me.from_pydata([(-w / 2, -h / 2, 0), (w / 2, -h / 2, 0), (w / 2, h / 2, 0), (-w / 2, h / 2, 0)], [], [(0, 1, 2, 3)])
    uv = me.uv_layers.new(name="UVMap")
    for i, c in enumerate([(0, 0), (1, 0), (1, 1), (0, 1)]):
        uv.data[i].uv = c
    o = bpy.data.objects.new(name, me)
    coll.objects.link(o)
    o.location = center
    o.rotation_euler = FACING[facing]
    me.materials.append(mat)
    return o


def planar_uv(o, scale, rot_deg=0.0, axes="xy"):
    """World-space planar UVs (metres / scale), rotated: for tiling textures (floors)."""
    me = o.data
    uv = me.uv_layers.get("UVMap") or me.uv_layers.new(name="UVMap")
    c, s = math.cos(math.radians(rot_deg)), math.sin(math.radians(rot_deg))
    bpy.context.view_layer.update()
    mw = o.matrix_world
    for poly in me.polygons:
        for li in poly.loop_indices:
            p = mw @ me.vertices[me.loops[li].vertex_index].co
            a, b = {"xy": (p.x, p.y), "xz": (p.x, p.z), "yz": (p.y, p.z)}[axes]
            uv.data[li].uv = ((a * c - b * s) / scale, (a * s + b * c) / scale)


def group(name, coll, loc=(0, 0, 0), facing_deg=0.0):
    """Empty used as a local frame: children are built in local coords (front = +X)."""
    e = bpy.data.objects.new(name, None)
    coll.objects.link(e)
    e.location = loc
    e.rotation_euler = (0, 0, math.radians(facing_deg))
    return e


def parent_all(parent, objs):
    for o in objs:
        o.parent = parent


def light(name, kind, loc, power, color, coll, size=0.05, rot=(0, 0, 0), spot_deg=None):
    ld = bpy.data.lights.new(name, kind)
    ld.energy = power
    ld.color = color
    if kind in ("POINT", "SPOT"):
        ld.shadow_soft_size = size
    if kind == "AREA":
        ld.size = size
    if spot_deg:
        ld.spot_size = math.radians(spot_deg)
        ld.spot_blend = 0.6
    o = bpy.data.objects.new(name, ld)
    coll.objects.link(o)
    o.location = loc
    o.rotation_euler = rot
    return o


def look_at_euler(loc, target):
    return (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
