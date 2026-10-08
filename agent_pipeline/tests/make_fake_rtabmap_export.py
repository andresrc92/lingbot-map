#!/usr/bin/env python
"""Fabricate an `rtabmap-export` output folder from an existing scene, to test the RTAB-Map front-end
without a real database.

    python agent_pipeline/tests/make_fake_rtabmap_export.py <existing_scene> <out_dir> [--every 4]

Writes exactly what `rtabmap-export --images_id --poses_camera --poses_format 11` produces
(see tools/Export/main.cpp in introlab/rtabmap): fake_rgb/<id>.jpg (full-res frames), fake_depth/<id>.png
(uint16 mm at a LOWER resolution, like many RGB-D sensors), fake_calib/<id>.yaml (OpenCV FileStorage,
ROS camera_matrix), fake_camera_poses.txt ("#timestamp x y z qx qy qz qw id", camera optical frame, metres).
Poses are the source scene's world poses, re-expressed in a Z-up "map" frame that is yawed and shifted
(RTAB-Map maps are Z-up but not aligned to your walls), so align.py has real work to do.
"""
import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
from scene_io import Scene  # noqa: E402


def R_to_q(R):
    w = np.sqrt(max(0, 1 + R[0, 0] + R[1, 1] + R[2, 2])) / 2
    x = np.sqrt(max(0, 1 + R[0, 0] - R[1, 1] - R[2, 2])) / 2
    y = np.sqrt(max(0, 1 - R[0, 0] + R[1, 1] - R[2, 2])) / 2
    z = np.sqrt(max(0, 1 - R[0, 0] - R[1, 1] + R[2, 2])) / 2
    x = np.copysign(x, R[2, 1] - R[1, 2]); y = np.copysign(y, R[0, 2] - R[2, 0]); z = np.copysign(z, R[1, 0] - R[0, 1])
    return x, y, z, w


ap = argparse.ArgumentParser()
ap.add_argument("scene"); ap.add_argument("out"); ap.add_argument("--every", type=int, default=4)
a = ap.parse_args()
sc = Scene(a.scene)
out = Path(a.out)
for d in ("fake_rgb", "fake_depth", "fake_calib"):
    (out / d).mkdir(parents=True, exist_ok=True)
yaw = np.radians(33)
M = np.eye(4)
M[:2, :2] = [[np.cos(yaw), -np.sin(yaw)], [np.sin(yaw), np.cos(yaw)]]
M[:3, 3] = [1.7, -0.6, 0.0]
lines = ["#timestamp x y z qx qy qz qw id"]
for k, i in enumerate(range(0, sc.n, a.every)):
    nid = 100 + k
    hi, (sx, sy) = sc.hires(i)
    cv2.imwrite(str(out / "fake_rgb" / f"{nid}.jpg"), cv2.cvtColor(hi, cv2.COLOR_RGB2BGR))
    D = sc.depth(i)                                         # metric, model resolution
    cv2.imwrite(str(out / "fake_depth" / f"{nid}.png"), np.clip(D * 1000, 0, 65535).astype(np.uint16))
    K = sc.K(i).copy()
    K[0] *= sx; K[1] *= sy                                  # calibration is at rgb resolution
    fs = cv2.FileStorage(str(out / "fake_calib" / f"{nid}.yaml"), cv2.FILE_STORAGE_WRITE)
    fs.write("camera_name", str(nid)); fs.write("image_width", hi.shape[1]); fs.write("image_height", hi.shape[0])
    fs.startWriteStruct("camera_matrix", cv2.FileNode_MAP)
    fs.write("rows", 3); fs.write("cols", 3)
    fs.startWriteStruct("data", cv2.FileNode_SEQ)
    for v in K.flatten():
        fs.write("", float(v))
    fs.endWriteStruct(); fs.endWriteStruct(); fs.release()
    P = M @ sc.pose(i)
    qx, qy, qz, qw = R_to_q(P[:3, :3])
    lines.append(f"{1700000000 + k * 0.2:.6f} {P[0,3]:.6f} {P[1,3]:.6f} {P[2,3]:.6f} {qx:.8f} {qy:.8f} {qz:.8f} {qw:.8f} {nid}")
(out / "fake_camera_poses.txt").write_text("\n".join(lines) + "\n")
print(f"wrote {len(lines) - 1} nodes to {out}")
