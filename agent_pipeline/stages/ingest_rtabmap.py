#!/usr/bin/env python
"""Ingest an RTAB-Map export into the canonical scene format (alternative to the LingBot stage).

    python agent_pipeline/stages/ingest_rtabmap.py <scene> <export_dir> [--every N] [--max_range 6]

<export_dir> is what `rtabmap-export` writes (pipeline.py runs it for you on the host):

    rtabmap-export --images_id --poses_camera --poses_format 11 --opt 2 --map --cloud \
                   --output_dir <export_dir> <map.db>

which produces <base>_rgb/<id>.jpg, <base>_depth/<id>.png (uint16 mm, registered to rgb),
<base>_calib/<id>.yaml (OpenCV FileStorage, ROS-style camera_matrix), <base>_camera_poses.txt
(format 11: "stamp x y z qx qy qz qw id", camera OPTICAL frame = OpenCV axes, metres, RTAB-Map
map frame with Z up), <base>.pgm/.yaml (2D occupancy grid) and <base>_cloud.ply.

Depth is metric (metric=true): align.py keeps scale=1 and only levels / centres the scene.
Stereo databases export left/right images without depth; not supported yet (see AGENTS.md).
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
from scene_io import REPO, scene_dir, write_frames  # noqa: E402


def quat_to_R(qx, qy, qz, qw):
    x, y, z, w = qx, qy, qz, qw
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def read_calib(path):
    fs = cv2.FileStorage(str(path), cv2.FILE_STORAGE_READ)
    node = fs.getNode("camera_matrix").getNode("data")
    K = np.array([node.at(i).real() for i in range(node.size())]).reshape(3, 3)
    w, h = int(fs.getNode("image_width").real()), int(fs.getNode("image_height").real())
    fs.release()
    return K, (w, h)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scene")
    ap.add_argument("export_dir")
    ap.add_argument("--every", type=int, default=1, help="keep every N-th node")
    ap.add_argument("--max_range", type=float, default=6.0, help="drop depth beyond this (m)")
    args = ap.parse_args()

    ex = Path(args.export_dir).resolve()
    posef = sorted(ex.glob("*_camera_poses.txt"))
    if not posef:
        sys.exit(f"no *_camera_poses.txt in {ex} (run rtabmap-export with --poses_camera)")
    base = posef[0].name[: -len("_camera_poses.txt")]
    rgb_dir, depth_dir, calib_dir = ex / f"{base}_rgb", ex / f"{base}_depth", ex / f"{base}_calib"
    if not depth_dir.exists():
        if (ex / f"{base}_left").exists():
            sys.exit("stereo database (left/right images, no depth): not supported yet; see AGENTS.md")
        sys.exit(f"{depth_dir} missing: export with --images_id from an RGB-D database")

    rows = []
    for line in open(posef[0]):
        if line.startswith("#") or not line.strip():
            continue
        stamp, x, y, z, qx, qy, qz, qw, nid = line.split()[:9]
        rows.append((float(stamp), int(float(nid)), np.array([x, y, z], float), [float(qx), float(qy), float(qz), float(qw)]))
    rows.sort(key=lambda r: r[0])
    rows = [r for r in rows if (rgb_dir / f"{r[1]}.jpg").exists() and (depth_dir / f"{r[1]}.png").exists()]
    rows = rows[:: args.every]
    if not rows:
        sys.exit("no node has rgb + depth + pose")

    rgbs, depths, Ks, poses, ids, files = [], [], [], [], [], []
    for stamp, nid, t, q in rows:
        im = cv2.cvtColor(cv2.imread(str(rgb_dir / f"{nid}.jpg")), cv2.COLOR_BGR2RGB)
        d = cv2.imread(str(depth_dir / f"{nid}.png"), cv2.IMREAD_UNCHANGED).astype(np.float32)
        d = d / 1000.0 if d.max() > 100 else d                  # uint16 mm -> m
        d[(d <= 0) | (d > args.max_range) | ~np.isfinite(d)] = 0
        K, (cw, ch) = read_calib(calib_dir / f"{nid}.yaml")
        # Work at depth resolution; keep the original rgb as "hires" for texture crops.
        dh, dw = d.shape
        K = K.copy()
        K[0] *= dw / im.shape[1]
        K[1] *= dh / im.shape[0]
        if im.shape[:2] != (dh, dw):
            im_small = cv2.resize(im, (dw, dh), interpolation=cv2.INTER_AREA)
        else:
            im_small = im
        P = np.eye(4)
        P[:3, :3] = quat_to_R(*q)
        P[:3, 3] = t
        rgbs.append(im_small); depths.append(d); Ks.append(K); poses.append(P); ids.append(nid)
        f = rgb_dir / f"{nid}.jpg"
        files.append(str(f.relative_to(REPO)) if f.is_relative_to(REPO) else str(f))
    sx = cv2.imread(str(rgb_dir / f"{rows[0][1]}.jpg")).shape[1] / depths[0].shape[1]
    sy = cv2.imread(str(rgb_dir / f"{rows[0][1]}.jpg")).shape[0] / depths[0].shape[0]

    root = scene_dir(args.scene)
    n = write_frames(root, rgbs, depths, Ks, poses, ids=ids, hires={"files": files, "scale": [sx, sy]}, source={
        "source": "rtabmap", "input": str(ex), "metric": True, "every": args.every,
        "note": "metric depth + globally optimised camera poses from RTAB-Map"})
    src = root / "source"
    src.mkdir(exist_ok=True)
    for f in [ex / f"{base}.pgm", ex / f"{base}.yaml", ex / f"{base}_cloud.ply"]:
        if f.exists():
            shutil.copy(f, src / f.name.replace(base, "rtabmap"))
    json.dump({"base": base, "nodes": len(rows)}, open(src / "export.json", "w"))
    print(f"ingested {n} RTAB-Map nodes ({depths[0].shape[1]}x{depths[0].shape[0]}) into {root}")


if __name__ == "__main__":
    main()
