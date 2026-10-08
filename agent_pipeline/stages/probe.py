#!/usr/bin/env python
"""Back-project pixels to world coordinates (Z up, floor z=0, metres).

    python agent_pipeline/stages/probe.py <scene> 117:70:25:lamp_shade 134:410:170:table_top ...

Each probe is frame:u:v:label, (u, v) in model/depth-resolution pixels (read them off
`analyze.py <scene> grid ...`). Depth = median of a 5x5 window; pose = refined world pose.
Results are also appended to analysis/probes.tsv so later agents can reuse them.
Noise: LingBot ~5-10 cm, RTAB-Map RGB-D ~1-3 cm at <3 m. Probe each object from 2-3 frames.
A probe on a pixel with no depth (glass, black, out of range) reports d=0: pick another pixel.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
from scene_io import Scene  # noqa: E402

sc = Scene(sys.argv[1])
log = sc.root / "analysis" / "probes.tsv"
log.parent.mkdir(exist_ok=True)
new = not log.exists()
with open(log, "a") as f:
    if new:
        f.write("label\tframe\tu\tv\tdepth_m\tx\ty\tz\n")
    for spec in sys.argv[2:]:
        fr, u, v, lab = spec.split(":", 3)
        fr, u, v = int(fr), int(u), int(v)
        D, K = sc.depth(fr), sc.K(fr)
        win = D[max(v - 2, 0):v + 3, max(u - 2, 0):u + 3]
        win = win[win > 0]
        d = float(np.median(win)) if win.size else 0.0
        w = sc.pose(fr) @ np.array([(u - K[0, 2]) * d / K[0, 0], (v - K[1, 2]) * d / K[1, 1], d, 1.0])
        print(f"{lab:24s} f{fr:<5d}({u},{v}) d={d:4.2f}  ->  x={w[0]:+.2f} y={w[1]:+.2f} z={w[2]:+.2f}")
        f.write(f"{lab}\t{fr}\t{u}\t{v}\t{d:.3f}\t{w[0]:.3f}\t{w[1]:.3f}\t{w[2]:.3f}\n")
