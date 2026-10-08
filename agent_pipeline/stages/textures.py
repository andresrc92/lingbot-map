#!/usr/bin/env python
"""Build the scene's textures from the `textures:` section of agent_pipeline/scenes/<scene>/scene.yaml.

    python agent_pipeline/stages/textures.py <scene>

Entries (output file name -> recipe), written to data/scenes/<scene>/textures/:

  painting.jpg:          # perspective-rectified crop of a frame (paintings, screens, window views)
    crop: {frame: 342, quad: [[x,y] TL, TR, BR, BL], size: [800, 640], gain: 1.15}
                         # quad in HIRES frame pixels (analyze.py <scene> hires <frames>)
  parquet_diffuse.jpg:   # seamless herringbone; also writes `roughness` (non-colour)
    herringbone: {sample: {frame: 372, box: [x0, y0, x1, y1]}, plank_w_m: 0.072, ratio: 5,
                  tile_widths: 20, px_per_width: 100, roughness: parquet_rough.png, seed: 7}

Herringbone lattice (found by brute force; hand-derived versions overlapped): for 1 x N planks,
vertical planks step by (1, -1) widths, rows repeat by (-7, -3), each horizontal plank sits at
(-N, 0) from its vertical one; period 10 widths. The tile in metres is tile_widths * plank_w_m
(use that as the material's uv.scale). Sample plank colours from a glare-free floor patch.
"""
import sys
from pathlib import Path

import cv2
import numpy as np
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
from scene_io import Scene, spec_dir  # noqa: E402


def rectify(sc, r, dst):
    img, _ = sc.hires(r["frame"])
    W, H = r["size"]
    M = cv2.getPerspectiveTransform(np.float32(r["quad"]), np.float32([[0, 0], [W, 0], [W, H], [0, H]]))
    out = cv2.warpPerspective(img, M, (W, H), flags=cv2.INTER_CUBIC).astype(np.float32) * r.get("gain", 1.0)
    cv2.imwrite(str(dst), cv2.cvtColor(np.clip(out, 0, 255).astype(np.uint8), cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 92])


def herringbone(sc, r, dst):
    img, _ = sc.hires(r["sample"]["frame"])
    x0, y0, x1, y1 = r["sample"]["box"]
    f = img[y0:y1, x0:x1].reshape(-1, 3).astype(np.float32)[:, ::-1]      # -> BGR for cv2 output
    lum = f.mean(1)
    wood = f[(lum > np.percentile(lum, 15)) & (lum < np.percentile(lum, 70))]
    rng = np.random.default_rng(r.get("seed", 7))
    N, W = r.get("ratio", 5), r.get("px_per_width", 100)
    tw = r.get("tile_widths", 20)
    PX = tw * W
    tex = np.zeros((PX, PX, 3), np.float32)
    rough = np.zeros((PX, PX), np.float32)

    def plank(h, w):
        base = wood[rng.integers(len(wood))] * rng.uniform(0.86, 1.10)
        along_y = h > w
        g = cv2.GaussianBlur(rng.normal(0, 1, (h, w)).astype(np.float32), (0, 0),
                             sigmaX=0.8 if along_y else 12, sigmaY=12 if along_y else 0.8)
        g /= g.std() + 1e-6
        p = base[None, None, :] * (1 + 0.07 * g[..., None])
        rr = np.clip(0.24 + 0.04 * g, 0.12, 0.4)
        e = 2
        p[:e] *= 0.45; p[-e:] *= 0.45; p[:, :e] *= 0.45; p[:, -e:] *= 0.45
        rr[:e] = rr[-e:] = 0.7; rr[:, :e] = rr[:, -e:] = 0.7
        return p, rr

    def stamp(xa, ya, p, rr):
        h, w = rr.shape
        ys = (np.arange(ya, ya + h) % PX)[:, None]
        xs = (np.arange(xa, xa + w) % PX)[None, :]
        tex[ys, xs] = p
        rough[ys, xs] = rr

    if tw % 10:
        raise ValueError("tile_widths must be a multiple of 10 (lattice period)")
    for i in range(tw):
        for j in range(tw // 10):
            a, b = (i - 7 * j) * W, (-i - 3 * j) * W
            stamp(a, b, *plank(N * W, W))
            stamp(a - N * W, b, *plank(W, N * W))
    cv2.imwrite(str(dst), np.clip(tex, 0, 255).astype(np.uint8), [cv2.IMWRITE_JPEG_QUALITY, 92])
    if r.get("roughness"):
        cv2.imwrite(str(dst.parent / r["roughness"]), np.clip(rough * 255, 0, 255).astype(np.uint8))


def main():
    name = sys.argv[1]
    spec = yaml.safe_load(open(spec_dir(name) / "scene.yaml"))
    sc = Scene(name)
    out = sc.root / "textures"
    out.mkdir(parents=True, exist_ok=True)
    for fname, recipe in (spec.get("textures") or {}).items():
        if "crop" in recipe:
            rectify(sc, recipe["crop"], out / fname)
        elif "herringbone" in recipe:
            herringbone(sc, recipe["herringbone"], out / fname)
        else:
            sys.exit(f"unknown texture recipe for {fname}: {list(recipe)}")
        print("wrote", out / fname)


if __name__ == "__main__":
    main()
