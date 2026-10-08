"""Export the Rebuild collection as a PBR GLB (lights + cameras) for the three.js viewer.

Run inside Blender after build_blender.py:

    exec(open("<repo>/blender_pipeline/export_blender.py").read())
"""
import os

import bpy

REPO = os.environ.get("LINGBOT_REPO", "/home/andres/focus/IAC/lingbot/lingbot-map")
out = os.path.join(REPO, "data", "blender", "export", "home_living_rebuild.glb")
os.makedirs(os.path.dirname(out), exist_ok=True)
bpy.context.view_layer.active_layer_collection = bpy.context.view_layer.layer_collection.children["Rebuild"]
bpy.ops.export_scene.gltf(filepath=out, export_format="GLB", use_active_collection=True,
                          use_active_collection_with_nested=True, export_apply=True,
                          export_lights=True, export_cameras=True, export_yup=True,
                          export_image_format="JPEG", export_jpeg_quality=90)
print("exported", out, round(os.path.getsize(out) / 1e6, 1), "MB")
