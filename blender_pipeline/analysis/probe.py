#!/usr/bin/env python
"""Back-project pixels to 3D in the aligned metric frame (Z up, floor z=0).

    python blender_pipeline/analysis/probe.py data/outputs/<name> 117:70:25:lamp_shade 134:410:170:table_top ...

Each probe is frame:u:v:label with (u, v) in prediction pixels (see frame_grid.py). Depth is the
median of a 5x5 window, scaled by align.json; poses are the ICP-refined ones from fuse.py.
Noise is a few centimetres; probe an object from 2-3 frames and average.
"""
import json
import sys
from pathlib import Path

import numpy as np

out = Path(sys.argv[1]); name = out.name
s = json.load(open(out / f"{name}_align.json"))["scale"]
poses = np.load(out / f"{name}_mesh_icp.poses.npy")
for spec in sys.argv[2:]:
    f, u, v, lab = spec.split(":"); f, u, v = int(f), int(u), int(v)
    z = np.load(out / name / f"frame_{f:06d}.npz")
    D = z["depth"][..., 0] * s; K = z["intrinsic"]
    d = float(np.median(D[max(v - 2, 0):v + 3, max(u - 2, 0):u + 3]))
    w = poses[f] @ np.array([(u - K[0, 2]) * d / K[0, 0], (v - K[1, 2]) * d / K[1, 1], d, 1.0])
    print(f"{lab:22s} f{f:<4d}({u},{v}) d={d:4.2f}  ->  x={w[0]:+.2f} y={w[1]:+.2f} z={w[2]:+.2f}")
