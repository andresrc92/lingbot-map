#!/usr/bin/env python
"""Visual aids the agent reads to survey a scene (all written to data/scenes/<scene>/analysis/).

    python agent_pipeline/stages/analyze.py <scene>                     # plan.png + overview.jpg + summary.json
    python agent_pipeline/stages/analyze.py <scene> grid 117,134,185    # grid_<frames>.jpg  (probe pixels)
    python agent_pipeline/stages/analyze.py <scene> hires 342,500       # hires_<frames>.jpg (texture corners)

plan.png      wall-height (0.9-1.7 m) and furniture-height (0.08-0.9 m) slices of the fused mesh,
              0.5 m grid, camera path with frame indices. Read walls/openings/furniture off it.
overview.jpg  ~30 evenly spaced frames with their indices: the inventory of what is in the scene.
grid_*.jpg    frames at model/depth resolution with a 50 px grid: pick (u, v) for probe.py.
hires_*.jpg   full-resolution frames with a 25 px grid: pick 4 corners for texture crops.
"""
import json
import sys
from pathlib import Path

import matplotlib
import numpy as np
import open3d as o3d
from PIL import Image, ImageDraw

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
from scene_io import Scene  # noqa: E402


def gridded(img, step, scale=1, label=None):
    I = Image.fromarray(img)
    if scale != 1:
        I = I.resize((I.width * scale, I.height * scale))
    d = ImageDraw.Draw(I)
    for x in range(0, img.shape[1], step):
        major = x % (step * 4) == 0
        d.line([(x * scale, 0), (x * scale, I.height)], fill=(0, 255, 0) if major else (0, 120, 0))
        if major or step >= 50:
            d.text((x * scale + 2, 2), str(x), fill=(255, 255, 0))
    for y in range(0, img.shape[0], step):
        major = y % (step * 4) == 0
        d.line([(0, y * scale), (I.width, y * scale)], fill=(0, 255, 0) if major else (0, 120, 0))
        if major or step >= 50:
            d.text((2, y * scale + 2), str(y), fill=(255, 255, 0))
    if label:
        d.text((I.width - 60, 6), label, fill=(255, 0, 255))
    return I


def tile(images, cols=2):
    W, H = images[0].size
    S = Image.new("RGB", (W * cols, H * ((len(images) + cols - 1) // cols)))
    for k, t in enumerate(images):
        S.paste(t.resize((W, H)), ((k % cols) * W, (k // cols) * H))
    return S


def plan(sc, out):
    mesh = o3d.io.read_triangle_mesh(str(sc.root / "mesh.ply"))
    P, C = np.asarray(mesh.vertices), np.asarray(mesh.vertex_colors)
    poses = sc.poses()
    lo = np.percentile(P[:, :2], 1, 0) - 0.5
    hi = np.percentile(P[:, :2], 99, 0) + 0.5
    span = hi - lo
    fig, ax = plt.subplots(1, 2, figsize=(2 * 13, 13 * span[1] / span[0] if span[0] > 0 else 13))
    for a, (z0, z1, t) in zip(ax, [(0.9, 1.7, "walls 0.9-1.7 m"), (0.08, 0.9, "furniture 0.08-0.9 m")]):
        s = np.where((P[:, 2] > z0) & (P[:, 2] < z1))[0]
        s = np.random.default_rng(0).choice(s, min(len(s), 400_000), replace=False)
        a.scatter(P[s, 0], P[s, 1], c=C[s], s=0.5)
        a.plot(poses[:, 0, 3], poses[:, 1, 3], "b-", lw=0.8)
        for i in range(0, len(poses), max(1, len(poses) // 12)):
            a.annotate(str(i), poses[i, :2, 3], color="blue", fontsize=9)
        a.set_xticks(np.arange(np.floor(lo[0] * 2) / 2, hi[0], 0.5))
        a.set_yticks(np.arange(np.floor(lo[1] * 2) / 2, hi[1], 0.5))
        a.tick_params(labelsize=7)
        a.set_xlim(lo[0], hi[0]); a.set_ylim(lo[1], hi[1]); a.set_aspect("equal"); a.grid(alpha=.4); a.set_title(t)
    plt.tight_layout()
    plt.savefig(out / "plan.png", dpi=55)
    plt.close()


def main():
    sc = Scene(sys.argv[1])
    out = sc.root / "analysis"
    out.mkdir(exist_ok=True)
    cmd = sys.argv[2] if len(sys.argv) > 2 else "all"
    if cmd == "grid":
        fr = [int(x) for x in sys.argv[3].split(",")]
        p = out / f"grid_{'-'.join(map(str, fr))}.jpg"
        tile([gridded(sc.rgb(i), 50, 2, f"#{i}") for i in fr]).save(p, quality=85)
        print("wrote", p)
        return
    if cmd == "hires":
        fr = [int(x) for x in sys.argv[3].split(",")]
        p = out / f"hires_{'-'.join(map(str, fr))}.jpg"
        tile([gridded(sc.hires(i)[0], 25, 1, f"#{i}") for i in fr]).save(p, quality=90)
        print("wrote", p, "(pixel coords are in hires frame pixels)")
        return

    plan(sc, out)
    idx = np.linspace(0, sc.n - 1, min(30, sc.n)).astype(int)
    thumbs = []
    for i in idx:
        I = Image.fromarray(sc.rgb(i)).resize((300, int(300 * sc.rgb(0).shape[0] / sc.rgb(0).shape[1])))
        ImageDraw.Draw(I).text((5, 5), str(i), fill=(255, 255, 0))
        thumbs.append(I)
    tile(thumbs, cols=6).save(out / "overview.jpg", quality=85)
    A = sc.align or {}
    summary = {"frames": sc.n, "source": sc.source,
               "align": {k: A.get(k) for k in ("scale", "ceiling_height_m", "camera_height_m", "floor_sharpness", "bounds_m")},
               "overview_frames": idx.tolist()}
    json.dump(summary, open(out / "summary.json", "w"), indent=1)
    print("wrote", out / "plan.png", out / "overview.jpg", out / "summary.json")


if __name__ == "__main__":
    main()
