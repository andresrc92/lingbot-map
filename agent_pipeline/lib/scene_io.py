"""Canonical scene format shared by every stage (container side: numpy, cv2, open3d).

All front-ends (LingBot video, RTAB-Map .db) write the same layout under data/scenes/<name>/,
so every later stage is source-agnostic:

    source.json              {"source": "lingbot"|"rtabmap", "input": ..., "metric": bool, ...}
    frames/rgb/000123.jpg    colour frame, same resolution as depth and K
    frames/depth/000123.npy  float16 depth in SOURCE units (metres if metric, model units if not); 0 = invalid
    frames/conf/000123.npy   optional float16 per-pixel confidence (higher = better)
    frames/K.npy             (N,3,3) intrinsics at rgb/depth resolution
    frames/poses_raw.npy     (N,4,4) camera-to-world, OpenCV camera axes (x right, y down, z forward),
                             in the source's world frame and units
    frames/meta.json         {"ids": [...source frame ids...], "hires": {"dir": ..., "scale": [sx, sy]} | null}
    align.json               similarity source->world: world = s * R @ p + t  (Z up, floor z=0, metres)
    poses.npy                (N,4,4) refined camera-to-world in the WORLD frame (written by fuse.py)
    mesh.ply / cloud.ply     fused mesh / point cloud in the world frame
    analysis/ textures/ blender/ review/ export/   later stages

World frame convention everywhere downstream: Z up, floor at z=0, metres, walls roughly along X/Y.
"""
import json
from pathlib import Path

import cv2
import numpy as np

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "data" / "scenes"
PIPE = REPO / "agent_pipeline"


def scene_dir(name):
    return DATA / name


def spec_dir(name):
    """Tracked, per-scene agent artefacts (scene.yaml, notes.md)."""
    return PIPE / "scenes" / name


class Scene:
    def __init__(self, name):
        self.name = name
        self.root = scene_dir(name)
        self.frames = self.root / "frames"
        if not (self.frames / "poses_raw.npy").exists():
            raise FileNotFoundError(f"{self.frames}/poses_raw.npy missing: run the ingest stage first")
        self.source = json.load(open(self.root / "source.json"))
        self.meta = json.load(open(self.frames / "meta.json"))
        self.K_all = np.load(self.frames / "K.npy")
        self.raw = np.load(self.frames / "poses_raw.npy")
        self.n = len(self.raw)
        self.align = json.load(open(self.root / "align.json")) if (self.root / "align.json").exists() else None
        p = self.root / "poses.npy"
        self.refined = np.load(p) if p.exists() else None

    # ---- frame data ----------------------------------------------------------------------
    def rgb(self, i):
        return cv2.cvtColor(cv2.imread(str(self.frames / "rgb" / f"{i:06d}.jpg")), cv2.COLOR_BGR2RGB)

    def depth(self, i, metric=True):
        """Depth in metres (world scale) when aligned; source units otherwise."""
        d = np.load(self.frames / "depth" / f"{i:06d}.npy").astype(np.float32)
        return d * self.scale if (metric and self.align) else d

    def conf(self, i):
        p = self.frames / "conf" / f"{i:06d}.npy"
        return np.load(p).astype(np.float32) if p.exists() else None

    def K(self, i):
        return self.K_all[i]

    def hires(self, i):
        """(image RGB, (sx, sy)) at the best available resolution for texture crops."""
        h = self.meta.get("hires")         # {"files": [...one path per frame...], "scale": [sx, sy]}
        if h:
            p = REPO / h["files"][i]
            if p.exists():
                return cv2.cvtColor(cv2.imread(str(p)), cv2.COLOR_BGR2RGB), tuple(h["scale"])
        return self.rgb(i), (1.0, 1.0)

    # ---- geometry --------------------------------------------------------------------------
    @property
    def scale(self):
        return float(self.align["scale"]) if self.align else 1.0

    @property
    def T(self):
        """4x4 similarity source->world (rotation block already multiplied by scale)."""
        return np.array(self.align["transform"]) if self.align else np.eye(4)

    def pose(self, i):
        """Camera-to-world in the world frame (refined if fuse.py has run)."""
        if self.refined is not None:
            return self.refined[i]
        return world_pose(self.raw[i], self.T, self.scale)

    def poses(self):
        return np.stack([self.pose(i) for i in range(self.n)])

    def backproject(self, i, stride=1, mask=None):
        """World-frame points + colours for frame i (metric depth, current pose)."""
        D = self.depth(i)
        H, W = D.shape
        v, u = np.mgrid[0:H:stride, 0:W:stride]
        d = D[::stride, ::stride]
        m = d > 0
        if mask is not None:
            m &= mask[::stride, ::stride]
        K = self.K(i)
        pc = np.stack([(u[m] - K[0, 2]) * d[m] / K[0, 0], (v[m] - K[1, 2]) * d[m] / K[1, 1], d[m]], 1)
        P = self.pose(i)
        return pc @ P[:3, :3].T + P[:3, 3], self.rgb(i)[::stride, ::stride][m]


def world_pose(raw_c2w, T, s):
    """Apply the similarity T (rotation block scaled by s) to a camera-to-world pose."""
    P = np.eye(4)
    P[:3, :3] = (T[:3, :3] / s) @ raw_c2w[:3, :3]
    P[:3, 3] = T[:3, :3] @ raw_c2w[:3, 3] + T[:3, 3]
    return P


def write_frames(root, rgbs, depths, Ks, poses, confs=None, ids=None, hires=None, source=None):
    """Write the canonical frames/ layout. rgbs: iterable of RGB uint8; depths: float arrays."""
    root = Path(root)
    fr = root / "frames"
    for sub in ("rgb", "depth") + (("conf",) if confs is not None else ()):
        (fr / sub).mkdir(parents=True, exist_ok=True)
    n = 0
    for i, (im, d) in enumerate(zip(rgbs, depths)):
        cv2.imwrite(str(fr / "rgb" / f"{i:06d}.jpg"), cv2.cvtColor(im, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 95])
        np.save(fr / "depth" / f"{i:06d}.npy", np.asarray(d, np.float16))
        if confs is not None:
            np.save(fr / "conf" / f"{i:06d}.npy", np.asarray(confs[i], np.float16))
        n += 1
    np.save(fr / "K.npy", np.asarray(Ks, np.float64))
    np.save(fr / "poses_raw.npy", np.asarray(poses, np.float64))
    h0, w0 = cv2.imread(str(fr / "rgb" / "000000.jpg")).shape[:2]
    json.dump({"ids": [int(x) if isinstance(x, (int, np.integer)) else x for x in (ids if ids is not None else range(n))],
               "size": [w0, h0], "hires": hires},
              open(fr / "meta.json", "w"), indent=1)
    if source is not None:
        json.dump(source, open(root / "source.json", "w"), indent=1)
    return n


def write_ply_points(path, xyz, rgb):
    v = np.empty(len(xyz), dtype=[("x", "<f4"), ("y", "<f4"), ("z", "<f4"),
                                  ("red", "u1"), ("green", "u1"), ("blue", "u1")])
    v["x"], v["y"], v["z"] = np.asarray(xyz, np.float32).T
    v["red"], v["green"], v["blue"] = np.asarray(rgb, np.uint8).T
    with open(path, "wb") as f:
        f.write((f"ply\nformat binary_little_endian 1.0\nelement vertex {len(v)}\n"
                 "property float x\nproperty float y\nproperty float z\n"
                 "property uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n").encode())
        f.write(v.tobytes())
