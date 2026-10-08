#!/usr/bin/env python
"""Convert LingBot-Map predictions (from `batch_demo.py --save_predictions`) to a PLY point cloud.

    python tools/npz_to_ply.py data/outputs/walk/<name>_predictions  -o data/outputs/walk/walk.ply

Writes a binary little-endian PLY (x,y,z float32 + red,green,blue uint8) plus a
`<out>_trajectory.ply` with one vertex per camera center (picked up by view_ply.py).
Runs on CPU; no GPU needed.
"""
import argparse
import glob
import importlib.util
import os
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]


def _load_npz_data(path):
    # Import the repo's loader directly (avoids pulling in the CUDA render extensions).
    spec = importlib.util.spec_from_file_location(
        "lingbot_loader", REPO / "demo_render" / "rgbd_render" / "data" / "loader.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.load_npz_data(path)


def write_ply(path, xyz, rgb):
    vertex = np.empty(len(xyz), dtype=[("x", "<f4"), ("y", "<f4"), ("z", "<f4"),
                                       ("red", "u1"), ("green", "u1"), ("blue", "u1")])
    vertex["x"], vertex["y"], vertex["z"] = xyz.T.astype(np.float32)
    vertex["red"], vertex["green"], vertex["blue"] = rgb.T
    header = ("ply\nformat binary_little_endian 1.0\n"
              f"element vertex {len(xyz)}\n"
              "property float x\nproperty float y\nproperty float z\n"
              "property uchar red\nproperty uchar green\nproperty uchar blue\n"
              "end_header\n")
    with open(path, "wb") as f:
        f.write(header.encode())
        f.write(vertex.tobytes())


def unproject(depth, image, K, c2w, ds):
    d = depth[::ds, ::ds]
    H, W = depth.shape
    u, v = np.meshgrid(np.arange(0, W, ds, dtype=np.float32), np.arange(0, H, ds, dtype=np.float32))
    pts_cam = np.stack([(u - K[0, 2]) * d / K[0, 0], (v - K[1, 2]) * d / K[1, 1], d], -1)
    pts = pts_cam.reshape(-1, 3) @ c2w[:3, :3].T + c2w[:3, 3]
    return pts, image[::ds, ::ds].reshape(-1, 3), d.reshape(-1)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("input", help="predictions dir (frame_*.npz) or a single .npz; "
                                 "an output folder from run_video.sh render also works")
    p.add_argument("-o", "--output", default=None, help="output .ply (default: next to input)")
    p.add_argument("--conf_threshold", type=float, default=1.5,
                   help="drop points with depth confidence below this (0 = keep all)")
    p.add_argument("--max_depth", type=float, default=100.0)
    p.add_argument("--downsample", type=int, default=2, help="pixel stride when unprojecting")
    p.add_argument("--frame_stride", type=int, default=1, help="use every N-th frame")
    p.add_argument("--keyframes_only", action="store_true")
    p.add_argument("--max_points", type=int, default=10_000_000, help="random subsample above this")
    args = p.parse_args()

    src = Path(args.input)
    if src.is_dir() and not glob.glob(str(src / "frame_*.npz")):
        # An output folder: find the predictions dir inside it.
        cands = [Path(m).parent for m in glob.glob(str(src / "**" / "frame_000000.npz"), recursive=True)]
        if len(cands) != 1:
            sys.exit(f"Expected exactly one predictions dir under {src}, found: {cands}")
        src = cands[0]
    out = Path(args.output) if args.output else src.with_suffix("").with_name(src.name.removesuffix(".npz") + ".ply")

    print(f"Loading {src} ...")
    data = _load_npz_data(str(src))
    images, depth, c2w, K, conf = data["images"], data["depth"], data["c2w"], data["K"], data["confidence"]
    kf = data.get("is_keyframe")
    S = len(images)

    frames = range(0, S, args.frame_stride)
    if args.keyframes_only and kf is not None:
        frames = [i for i in frames if kf[i]]

    all_xyz, all_rgb = [], []
    for i in frames:
        xyz, rgb, d = unproject(depth[i], images[i], K[i], c2w[i], args.downsample)
        keep = (d > 0) & (d < args.max_depth)
        if conf is not None and args.conf_threshold > 0:
            keep &= conf[i][::args.downsample, ::args.downsample].reshape(-1) >= args.conf_threshold
        all_xyz.append(xyz[keep].astype(np.float32))
        all_rgb.append(rgb[keep])
    xyz, rgb = np.concatenate(all_xyz), np.concatenate(all_rgb)

    if len(xyz) > args.max_points:
        idx = np.sort(np.random.default_rng(0).choice(len(xyz), args.max_points, replace=False))
        xyz, rgb = xyz[idx], rgb[idx]

    out.parent.mkdir(parents=True, exist_ok=True)
    write_ply(out, xyz, rgb)
    traj = out.with_name(out.stem + "_trajectory.ply")
    centers = c2w[:, :3, 3]
    ramp = np.linspace(0, 255, S).astype(np.uint8)
    write_ply(traj, centers, np.stack([ramp, 64 * np.ones_like(ramp), 255 - ramp], 1))
    print(f"Wrote {out} ({len(xyz):,} points from {len(frames)} frames, "
          f"{os.path.getsize(out) / 1e6:.1f} MB) and {traj.name}")


if __name__ == "__main__":
    main()
