#!/usr/bin/env python
"""Export browser assets for the three.js viewer, all in glTF axes (Y up, metres).

    python blender_pipeline/export_web.py data/outputs/<name> data/blender/export

Writes <name>_scan.glb (decimated fused mesh, vertex colours), <name>_points.ply (aligned,
voxel-downsampled point cloud) and <name>_trajectory.json (camera path). The Blender
rebuild is exported separately from Blender (glTF exporter converts Z-up to Y-up the same way).
"""
import json
import sys
from pathlib import Path

import numpy as np
import open3d as o3d
import trimesh

ZUP_TO_YUP = np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], dtype=np.float64)   # (x,y,z) -> (x,z,-y)


def main():
    out_dir, dst = Path(sys.argv[1]), Path(sys.argv[2])
    target_tris = int(sys.argv[3]) if len(sys.argv) > 3 else 400_000
    name = out_dir.name
    dst.mkdir(parents=True, exist_ok=True)
    A = json.load(open(out_dir / f"{name}_align.json"))
    T = np.array(A["transform"])

    # Scan mesh (already in the aligned Z-up frame) -> decimated GLB
    mesh = o3d.io.read_triangle_mesh(str(out_dir / f"{name}_mesh_icp.ply"))
    mesh = mesh.simplify_quadric_decimation(target_tris)
    mesh.remove_degenerate_triangles(); mesh.remove_unreferenced_vertices()
    V = np.asarray(mesh.vertices) @ ZUP_TO_YUP.T
    Cc = (np.clip(np.asarray(mesh.vertex_colors), 0, 1) * 255).astype(np.uint8)
    tm = trimesh.Trimesh(V, np.asarray(mesh.triangles), vertex_colors=np.c_[Cc, np.full(len(Cc), 255, np.uint8)], process=False)
    tm.export(dst / f"{name}_scan.glb")
    print("scan:", len(tm.faces), "tris")

    # Point cloud: model frame -> aligned Z-up -> Y-up, voxel downsample
    pc = o3d.io.read_point_cloud(str(out_dir / f"{name}.ply"))
    pc.transform(T)
    pc = pc.voxel_down_sample(0.008)
    P = np.asarray(pc.points) @ ZUP_TO_YUP.T
    C = (np.clip(np.asarray(pc.colors), 0, 1) * 255).astype(np.uint8)
    if len(P) > 2_500_000:
        idx = np.random.default_rng(0).choice(len(P), 2_500_000, replace=False); P, C = P[idx], C[idx]
    vert = np.empty(len(P), dtype=[("x", "<f4"), ("y", "<f4"), ("z", "<f4"), ("red", "u1"), ("green", "u1"), ("blue", "u1")])
    vert["x"], vert["y"], vert["z"] = P.T
    vert["red"], vert["green"], vert["blue"] = C.T
    with open(dst / f"{name}_points.ply", "wb") as f:
        f.write((f"ply\nformat binary_little_endian 1.0\nelement vertex {len(P)}\n"
                 "property float x\nproperty float y\nproperty float z\n"
                 "property uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n").encode())
        f.write(vert.tobytes())
    print("points:", len(P))

    # Camera trajectory (refined poses from fuse.py, aligned frame)
    poses = np.load(out_dir / f"{name}_mesh_icp.poses.npy")
    cams = []
    for Pz in poses[::2]:
        pos = ZUP_TO_YUP @ Pz[:3, 3]
        fwd = ZUP_TO_YUP @ Pz[:3, 2]          # OpenCV camera looks along +z
        cams.append({"p": pos.round(4).tolist(), "f": fwd.round(4).tolist()})
    json.dump({"frames": cams, "stride": 2}, open(dst / f"{name}_trajectory.json", "w"))
    print("trajectory:", len(cams), "poses")


if __name__ == "__main__":
    main()
