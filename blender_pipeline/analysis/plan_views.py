#!/usr/bin/env python
"""Floor-plan slices of the fused mesh with the camera path, for reading wall / furniture positions.

    python blender_pipeline/analysis/plan_views.py data/outputs/<name> [-o plan.png]

Left: points at wall height (0.9-1.7 m). Right: furniture height (0.08-0.9 m). Grid every 0.5 m,
camera path in blue with frame indices every 40 frames (aligned frame: Z up, metres).
"""
import argparse
from pathlib import Path

import matplotlib
import numpy as np
import open3d as o3d

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("outdir")
ap.add_argument("-o", "--output", default=None)
a = ap.parse_args()
out = Path(a.outdir); name = out.name
mesh = o3d.io.read_triangle_mesh(str(out / f"{name}_mesh_icp.ply"))
P, C = np.asarray(mesh.vertices), np.asarray(mesh.vertex_colors)
poses = np.load(out / f"{name}_mesh_icp.poses.npy")
lo, hi = np.percentile(P[:, :2], 1, 0) - 0.5, np.percentile(P[:, :2], 99, 0) + 0.5
fig, ax = plt.subplots(1, 2, figsize=(26, 13))
for axis, (z0, z1, title) in zip(ax, [(0.9, 1.7, "walls 0.9-1.7 m"), (0.08, 0.9, "furniture 0.08-0.9 m")]):
    s = np.where((P[:, 2] > z0) & (P[:, 2] < z1))[0]
    s = np.random.default_rng(0).choice(s, min(len(s), 400_000), replace=False)
    axis.scatter(P[s, 0], P[s, 1], c=C[s], s=0.5)
    axis.plot(poses[:, 0, 3], poses[:, 1, 3], "b-", lw=0.8)
    for i in range(0, len(poses), 40):
        axis.annotate(str(i), poses[i, :2, 3], color="blue", fontsize=9)
    axis.set_xticks(np.arange(np.floor(lo[0]), hi[0], 0.5)); axis.set_yticks(np.arange(np.floor(lo[1]), hi[1], 0.5))
    axis.set_xlim(lo[0], hi[0]); axis.set_ylim(lo[1], hi[1]); axis.set_aspect("equal"); axis.grid(alpha=.4); axis.set_title(title)
plt.tight_layout()
dst = a.output or str(out / f"{name}_plan.png")
plt.savefig(dst, dpi=55)
print("wrote", dst)
