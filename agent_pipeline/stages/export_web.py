#!/usr/bin/env python
"""Web assets for the three.js viewer, in glTF axes (Y up, metres): (x, y, z) -> (x, z, -y).

    python agent_pipeline/stages/export_web.py <scene> [--tris 400000] [--max_points 2500000]

Writes data/scenes/<scene>/export/<scene>_scan.glb (decimated fused mesh, sRGB vertex colours:
the viewer converts them), <scene>_points.ply (all frames back-projected, 8 mm voxels) and
<scene>_trajectory.json (camera path). The Blender stages add <scene>_rebuild.glb / _baked.glb.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import open3d as o3d
import trimesh

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
from scene_io import Scene, write_ply_points  # noqa: E402

ZUP_TO_YUP = np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], dtype=np.float64)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scene")
    ap.add_argument("--tris", type=int, default=400_000)
    ap.add_argument("--max_points", type=int, default=2_500_000)
    args = ap.parse_args()
    sc = Scene(args.scene)
    dst = sc.root / "export"
    dst.mkdir(exist_ok=True)

    mesh = o3d.io.read_triangle_mesh(str(sc.root / "mesh.ply"))
    mesh = mesh.simplify_quadric_decimation(args.tris)
    mesh.remove_degenerate_triangles()
    mesh.remove_unreferenced_vertices()
    V = np.asarray(mesh.vertices) @ ZUP_TO_YUP.T
    C = (np.clip(np.asarray(mesh.vertex_colors), 0, 1) * 255).astype(np.uint8)
    trimesh.Trimesh(V, np.asarray(mesh.triangles), vertex_colors=np.c_[C, np.full(len(C), 255, np.uint8)],
                    process=False).export(dst / f"{sc.name}_scan.glb")
    print("scan:", len(mesh.triangles), "tris")

    pts, cols = [], []
    for i in range(sc.n):
        c = sc.conf(i)
        p, col = sc.backproject(i, stride=2, mask=(c >= np.percentile(c, 30)) if c is not None else None)
        keep = np.linalg.norm(p - sc.pose(i)[:3, 3], axis=1) < 5.0
        pts.append(p[keep]); cols.append(col[keep])
    pc = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(np.concatenate(pts)))
    pc.colors = o3d.utility.Vector3dVector(np.concatenate(cols) / 255.0)
    pc = pc.voxel_down_sample(0.008)
    P = np.asarray(pc.points) @ ZUP_TO_YUP.T
    Cp = (np.asarray(pc.colors) * 255).astype(np.uint8)
    if len(P) > args.max_points:
        k = np.random.default_rng(0).choice(len(P), args.max_points, replace=False)
        P, Cp = P[k], Cp[k]
    write_ply_points(dst / f"{sc.name}_points.ply", P, Cp)
    print("points:", len(P))

    frames = []
    for Pz in sc.poses()[::2]:
        frames.append({"p": (ZUP_TO_YUP @ Pz[:3, 3]).round(4).tolist(), "f": (ZUP_TO_YUP @ Pz[:3, 2]).round(4).tolist()})
    json.dump({"frames": frames, "stride": 2}, open(dst / f"{sc.name}_trajectory.json", "w"))
    print("trajectory:", len(frames), "poses")


if __name__ == "__main__":
    main()
