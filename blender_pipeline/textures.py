#!/usr/bin/env python
"""Build the texture set for the Blender rebuild of home_living.

Rectified crops from the video (paintings, TV screen, night view through the window) and a
procedural herringbone parquet whose plank colours are sampled from the real floor.

    python blender_pipeline/textures.py data/outputs/home_living/home_living_frames data/blender/textures
"""
import sys
from pathlib import Path

import cv2
import numpy as np

frames, out = Path(sys.argv[1]), Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)


def frame(i):
    return cv2.imread(str(frames / f"frame_{i:06d}.png"))


def rectify(i, quad, size, name, gain=1.0):
    W, H = size
    M = cv2.getPerspectiveTransform(np.float32(quad), np.float32([[0, 0], [W, 0], [W, H], [0, H]]))
    img = cv2.warpPerspective(frame(i), M, (W, H), flags=cv2.INTER_CUBIC)
    img = np.clip(img.astype(np.float32) * gain, 0, 255).astype(np.uint8)
    cv2.imwrite(str(out / name), img)


# Paintings / screen / window view (corner order TL, TR, BR, BL in frame pixels)
rectify(342, [(352, 150), (558, 184), (551, 400), (344, 443)], (800, 640), "painting_goldengate.jpg", 1.15)
rectify(500, [(412, 82), (722, 109), (704, 229), (404, 215)], (1200, 500), "painting_colorful.jpg", 1.35)
rectify(287, [(36, 252), (398, 266), (398, 476), (36, 476)], (1280, 600), "tv_screen.jpg", 1.0)
rectify(185, [(152, 100), (500, 100), (500, 470), (152, 470)], (700, 740), "window_night.jpg", 1.3)

# --- Herringbone parquet -------------------------------------------------------------
# Sample plank colours from the real floor (frame 372, lower-left floor area, skipping glare).
f = frame(372)[150:470, 0:420].reshape(-1, 3).astype(np.float32)
lum = f.mean(1)
wood = f[(lum > np.percentile(lum, 15)) & (lum < np.percentile(lum, 70))]
rng = np.random.default_rng(7)

# Herringbone lattice for planks of 1 x N widths (N=5): consecutive vertical planks step by
# (1, -1), rows repeat by (-7, -3), each horizontal plank sits at (-5, 0) from its vertical
# one. The pattern repeats every 10 widths in x and y, so the tile is seamless.
N, W = 5, 100                      # plank = W x N*W px; tile = 20*W px = 1.44 m at 7.2 cm planks
PX = 20 * W
tex = np.zeros((PX, PX, 3), np.float32); rtex = np.zeros((PX, PX), np.float32)


def plank(h, w):
    base = wood[rng.integers(len(wood))] * rng.uniform(0.86, 1.10)
    long_ax = 0 if h > w else 1
    g = cv2.GaussianBlur(rng.normal(0, 1, (h, w)).astype(np.float32), (0, 0),
                         sigmaX=12 if long_ax == 1 else 0.8, sigmaY=12 if long_ax == 0 else 0.8)
    g /= g.std() + 1e-6
    p = base[None, None, :] * (1 + 0.07 * g[..., None])
    r = np.clip(0.24 + 0.04 * g, 0.12, 0.4)
    e = 2                                                   # dark bevelled joints
    p[:e] *= 0.45; p[-e:] *= 0.45; p[:, :e] *= 0.45; p[:, -e:] *= 0.45
    r[:e] = r[-e:] = 0.7; r[:, :e] = r[:, -e:] = 0.7
    return p, r


def stamp(x0, y0, p, r):
    h, w = r.shape
    ys = (np.arange(y0, y0 + h) % PX)[:, None]; xs = (np.arange(x0, x0 + w) % PX)[None, :]
    tex[ys, xs] = p; rtex[ys, xs] = r


for i in range(20):                 # a 20W tile holds 40 V+H plank pairs
  for j in range(2):
    a, b = (i - 7 * j) * W, (-i - 3 * j) * W
    stamp(a, b, *plank(N * W, W))                       # vertical
    stamp(a - N * W, b, *plank(W, N * W))               # horizontal
cv2.imwrite(str(out / "parquet_diffuse.jpg"), np.clip(tex, 0, 255).astype(np.uint8), [cv2.IMWRITE_JPEG_QUALITY, 92])
cv2.imwrite(str(out / "parquet_rough.png"), np.clip(rtex * 255, 0, 255).astype(np.uint8))
print("done", sorted(p.name for p in out.iterdir()))
