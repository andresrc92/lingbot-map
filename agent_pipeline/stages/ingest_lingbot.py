#!/usr/bin/env python
"""Ingest a LingBot-Map run (`./run_video.sh render <video>`) into the canonical scene format.

    python agent_pipeline/stages/ingest_lingbot.py <scene> data/outputs/<run>

Reads <run>/<run>/frame_*.npz (depth, confidence, poses, intrinsics, images at model resolution,
e.g. 518x294) and links the full-resolution extracted frames <run>/<run>_frames/ as "hires" for
texture crops. Depth and poses are in the model's arbitrary units (metric=false): align.py
fixes scale from an assumed ceiling height.
"""
import importlib.util
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
from scene_io import REPO, scene_dir, write_frames  # noqa: E402


def load_predictions(path):
    spec = importlib.util.spec_from_file_location(
        "lingbot_loader", REPO / "demo_render" / "rgbd_render" / "data" / "loader.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.load_npz_data(str(path))


def main():
    name, run = sys.argv[1], Path(sys.argv[2]).resolve()
    pred = run / run.name
    d = load_predictions(pred)
    imgs, depth, K, c2w, conf = d["images"], d["depth"], d["K"], d["c2w"], d["confidence"]
    S, H, W = depth.shape[:3]

    hires = None
    hdir = run / f"{run.name}_frames"
    files = sorted(hdir.glob("*.png")) + sorted(hdir.glob("*.jpg"))
    if len(files) == S:
        h0 = cv2.imread(str(files[0]))
        # LingBot's "crop" preprocessing resizes to width 518 and snaps height to a multiple of 14,
        # so model pixels map to the originals by a pure per-axis scale.
        hires = {"files": [str(f.relative_to(REPO)) for f in files], "scale": [h0.shape[1] / W, h0.shape[0] / H]}

    root = scene_dir(name)
    n = write_frames(root, imgs, depth, K, c2w, confs=conf, hires=hires, source={
        "source": "lingbot", "input": str(run.relative_to(REPO)), "metric": False,
        "note": "model units; scale comes from align.py --ceiling (assumed ceiling height)"})
    print(f"ingested {n} frames ({W}x{H}) into {root}; hires: {bool(hires)}")


if __name__ == "__main__":
    main()
