#!/usr/bin/env python
"""Estimate a metric, gravity-aligned frame for a LingBot-Map reconstruction.

    python blender_pipeline/align.py data/outputs/<name>/<name>.ply [--ceiling 2.7] [-o align.json]

The model's output lives in the first camera's OpenCV frame with an arbitrary scale.
This finds: up (camera up vectors, refined by the dominant horizontal plane), floor and
ceiling heights (height-histogram peaks), the dominant wall direction (yaw), and a scale
that puts the ceiling at --ceiling metres. Writes a 4x4 model->world transform
(Z up, floor at z=0, walls along X/Y, metres) plus diagnostics to JSON.
"""
import argparse
import importlib.util
import json
from pathlib import Path

import numpy as np
import open3d as o3d

REPO = Path(__file__).resolve().parents[1]


def load_predictions(path):
    spec = importlib.util.spec_from_file_location(
        "lingbot_loader", REPO / "demo_render" / "rgbd_render" / "data" / "loader.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.load_npz_data(str(path))


def unit(v):
    return v / np.linalg.norm(v)


def planes(pc, n, dist):
    out, rest = [], pc
    for _ in range(n):
        if len(rest.points) < 1000:
            break
        m, idx = rest.segment_plane(dist, 3, 2000)
        out.append((unit(np.array(m[:3])), m[3] / np.linalg.norm(m[:3]), len(idx)))
        rest = rest.select_by_index(idx, invert=True)
    return out


def floor_ceiling(h, bw=0.01):
    """Lowest and highest prominent peaks of the height histogram (floor, ceiling)."""
    from scipy.ndimage import gaussian_filter1d
    from scipy.signal import find_peaks
    lo, hi = np.percentile(h, [0.2, 99.8])
    hist, edges = np.histogram(h, bins=np.arange(lo, hi + bw, bw))
    sm = gaussian_filter1d(hist.astype(float), 1.5)
    idx, _ = find_peaks(sm, prominence=0.10 * sm.max())
    centers = edges[idx] + bw / 2

    def sharp(c):
        near = np.abs(h - c)
        return float((near < 0.02 * (hi - lo)).sum() / max((near < 0.10 * (hi - lo)).sum(), 1))
    f, c = float(centers[0]), float(centers[-1])
    return f, c, sharp(f), sharp(c), centers.round(3).tolist()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ply")
    ap.add_argument("--predictions", default=None, help="predictions dir (default: <ply stem>/ next to it)")
    ap.add_argument("--ceiling", type=float, default=2.70, help="assumed floor-to-ceiling height in metres")
    ap.add_argument("-o", "--output", default=None)
    args = ap.parse_args()

    ply = Path(args.ply)
    pred = Path(args.predictions) if args.predictions else ply.with_suffix("")
    out = Path(args.output) if args.output else ply.with_name(ply.stem + "_align.json")

    c2w = load_predictions(pred)["c2w"]
    cam_up = unit((-c2w[:, :3, 1]).mean(0))

    pc = o3d.io.read_point_cloud(str(ply)).voxel_down_sample(0.015)
    pc, _ = pc.remove_statistical_outlier(20, 2.0)
    P = np.asarray(pc.points)
    found = planes(pc, 12, 0.012)

    # up: largest plane whose normal is within 20 deg of the camera up
    horiz = [p for p in found if abs(p[0] @ cam_up) > np.cos(np.radians(20))]
    up = unit(max(horiz, key=lambda p: p[2])[0]) if horiz else cam_up
    up = up if up @ cam_up > 0 else -up

    h = P @ up
    floor_h, ceil_h, floor_sharp, ceil_sharp, peaks = floor_ceiling(h)
    scale = args.ceiling / (ceil_h - floor_h)

    # yaw: dominant wall normal (perpendicular to up), weighted by inliers
    walls = [p for p in found if abs(p[0] @ up) < np.sin(np.radians(15))]
    if walls:
        w = max(walls, key=lambda p: p[2])[0]
        x = unit(w - (w @ up) * up)
    else:
        x = unit(np.cross(up, [0, 0, 1]))
    y = np.cross(up, x)
    R = np.stack([x, y, up])          # rows: world axes expressed in model coords

    T = np.eye(4)
    T[:3, :3] = scale * R
    T[:3, 3] = [0, 0, -scale * floor_h]
    # recentre XY on the point cloud
    W = (P @ R.T) * scale
    cxy = np.percentile(W[:, :2], [2, 98], axis=0).mean(0)
    T[:2, 3] -= cxy
    W = W - np.r_[cxy, scale * floor_h]

    info = {
        "transform": T.tolist(),
        "scale": scale, "assumed_ceiling_m": args.ceiling,
        "up_model": up.tolist(), "cam_up_model": cam_up.tolist(),
        "floor_h_model": floor_h, "ceiling_h_model": ceil_h,
        "height_peaks_model": peaks,
        "floor_sharpness": floor_sharp, "ceiling_sharpness": ceil_sharp,
        "camera_height_m": float(np.median((c2w[:, :3, 3] @ up - floor_h) * scale)),
        "bounds_m": {"min": np.percentile(W, 1, 0).round(3).tolist(), "max": np.percentile(W, 99, 0).round(3).tolist()},
        "walls": [{"normal_world": (R @ p[0]).round(3).tolist(), "offset_m": float(-p[1] * scale), "inliers": p[2]} for p in walls],
    }
    json.dump(info, open(out, "w"), indent=2)
    print(json.dumps({k: v for k, v in info.items() if k not in ("transform", "walls")}, indent=1))
    print(f"{len(walls)} wall planes; wrote {out}")


if __name__ == "__main__":
    main()
