#!/usr/bin/env python
"""Side-by-side review: each video frame next to the Blender render from the same camera pose.

    python agent_pipeline/stages/compare.py <scene>

Reads blender/review/frame_NNNNNN.png (written by build_scene.py for scene.yaml `review.frames`)
and writes review/compare.jpg (rows: video | render | difference) plus review/metrics.json:
  ssim        structural similarity of grey, blurred images (layout/geometry agreement), 0..1
  luma_ratio  mean brightness render / video (exposure & light levels; aim 0.8-1.25)
  chroma_dE   mean colour difference of blurred images in Lab (materials/white balance; lower is better)
These are rough, comparative numbers: use them to see whether an edit helped, not as absolute truth.
Night video is noisy and auto-exposed, so trust your eyes on compare.jpg first.
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
from scene_io import Scene  # noqa: E402


def ssim(a, b):
    a, b = a.astype(np.float64), b.astype(np.float64)
    C1, C2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    mu_a, mu_b = cv2.GaussianBlur(a, (11, 11), 1.5), cv2.GaussianBlur(b, (11, 11), 1.5)
    sa = cv2.GaussianBlur(a * a, (11, 11), 1.5) - mu_a ** 2
    sb = cv2.GaussianBlur(b * b, (11, 11), 1.5) - mu_b ** 2
    sab = cv2.GaussianBlur(a * b, (11, 11), 1.5) - mu_a * mu_b
    return float((((2 * mu_a * mu_b + C1) * (2 * sab + C2)) / ((mu_a ** 2 + mu_b ** 2 + C1) * (sa + sb + C2))).mean())


def main():
    sc = Scene(sys.argv[1])
    rdir = sc.root / "blender" / "review"
    renders = sorted(rdir.glob("frame_*.png"))
    if not renders:
        sys.exit(f"no renders in {rdir}: run the build stage with review frames")
    out = sc.root / "review"
    out.mkdir(exist_ok=True)
    rows, metrics = [], {}
    for p in renders:
        i = int(p.stem.split("_")[1])
        vid, _ = sc.hires(i)
        ren = cv2.cvtColor(cv2.imread(str(p)), cv2.COLOR_BGR2RGB)
        W = 640
        H = int(W * vid.shape[0] / vid.shape[1])
        v, r = cv2.resize(vid, (W, H), interpolation=cv2.INTER_AREA), cv2.resize(ren, (W, H), interpolation=cv2.INTER_AREA)
        gv = cv2.GaussianBlur(cv2.cvtColor(v, cv2.COLOR_RGB2GRAY), (0, 0), 2)
        gr = cv2.GaussianBlur(cv2.cvtColor(r, cv2.COLOR_RGB2GRAY), (0, 0), 2)
        lv = cv2.cvtColor(cv2.GaussianBlur(v, (0, 0), 6), cv2.COLOR_RGB2LAB).astype(np.float32)
        lr = cv2.cvtColor(cv2.GaussianBlur(r, (0, 0), 6), cv2.COLOR_RGB2LAB).astype(np.float32)
        m = {"ssim": round(ssim(gv, gr), 3), "luma_ratio": round(float(gr.mean() / max(gv.mean(), 1)), 2),
             "chroma_dE": round(float(np.linalg.norm(lv[..., 1:] - lr[..., 1:], axis=2).mean()), 1)}
        metrics[i] = m
        diff = cv2.applyColorMap(cv2.absdiff(gv, gr), cv2.COLORMAP_INFERNO)[..., ::-1]
        row = np.concatenate([v, r, diff], 1)
        cv2.putText(row, f"#{i} video", (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
        cv2.putText(row, f"render  ssim {m['ssim']}  luma x{m['luma_ratio']}  dE {m['chroma_dE']}", (W + 8, 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
        rows.append(row)
    cv2.imwrite(str(out / "compare.jpg"), cv2.cvtColor(np.concatenate(rows, 0), cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 85])
    mean = {k: round(float(np.mean([m[k] for m in metrics.values()])), 3) for k in ("ssim", "luma_ratio", "chroma_dE")}
    json.dump({"mean": mean, "frames": metrics}, open(out / "metrics.json", "w"), indent=1)
    hist = out / "metrics_history.jsonl"
    with open(hist, "a") as f:
        f.write(json.dumps(mean) + "\n")
    print("wrote", out / "compare.jpg", "| mean:", mean)


if __name__ == "__main__":
    main()
