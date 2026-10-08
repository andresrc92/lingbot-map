#!/usr/bin/env python
"""Contact sheet of model-resolution frames with a 50 px grid, for picking pixels to probe.

    python blender_pipeline/analysis/frame_grid.py data/outputs/<name> 117,134,185 [-o grid.jpg]

Pixel coordinates read off these grids are in the predictions' resolution (e.g. 518x294),
which is what probe.py expects.
"""
import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ap = argparse.ArgumentParser()
ap.add_argument("outdir"); ap.add_argument("frames"); ap.add_argument("-o", "--output", default=None)
a = ap.parse_args()
out = Path(a.outdir); name = out.name
tiles = []
for i in [int(x) for x in a.frames.split(",")]:
    im = np.load(out / name / f"frame_{i:06d}.npz")["images"]
    if im.dtype != np.uint8:
        im = (im.transpose(1, 2, 0) * 255).clip(0, 255).astype(np.uint8)
    I = Image.fromarray(im).resize((im.shape[1] * 2, im.shape[0] * 2)); d = ImageDraw.Draw(I)
    for x in range(0, im.shape[1], 50):
        d.line([(2 * x, 0), (2 * x, I.height)], fill=(0, 255, 0)); d.text((2 * x + 2, 2), str(x), fill=(0, 255, 0))
    for y in range(0, im.shape[0], 50):
        d.line([(0, 2 * y), (I.width, 2 * y)], fill=(0, 255, 0)); d.text((2, 2 * y + 2), str(y), fill=(0, 255, 0))
    d.text((I.width - 60, 5), f"#{i}", fill=(255, 255, 0)); tiles.append(I)
W, H = tiles[0].size
S = Image.new("RGB", (W * 2, H * ((len(tiles) + 1) // 2)))
for k, t in enumerate(tiles):
    S.paste(t, ((k % 2) * W, (k // 2) * H))
dst = a.output or str(out / f"{name}_grid.jpg")
S.save(dst, quality=85)
print("wrote", dst)
