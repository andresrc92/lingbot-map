#!/usr/bin/env python
"""Level, scale and centre a scene: source frame -> world (Z up, floor z=0, metres, walls on X/Y).

    python agent_pipeline/stages/align.py <scene> [--ceiling 2.70] [--force_ceiling]

1. Back-project a subset of frames into one cloud (source frame).
2. Up = mean camera "up" (-y of each camera-to-world), refined by the largest RANSAC plane within 20
   degrees of it (on handheld video the two agreed to 0.998).
3. Floor / ceiling = lowest / highest prominent peaks of the height histogram along up.
   (Splitting at the median picked furniture tops as "ceiling" once; don't.)
4. Scale: metric sources (RTAB-Map) keep s=1. Non-metric sources (LingBot) get
   s = --ceiling / (ceiling - floor). --force_ceiling rescales a metric source too.
5. Yaw: the largest wall plane becomes +X. Then recentre XY on the cloud and put the floor at z=0.

Writes align.json (transform + diagnostics) and cloud.ply (world frame, 1 cm voxels).
CHECK: camera_height_m (handheld 1.3-1.6 m, robot = its camera mount height), floor_sharpness
(>=0.35 good; low values mean doubled surfaces), ceiling found (ceiling_h - floor_h plausible).
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import open3d as o3d
from scipy.ndimage import gaussian_filter1d
from scipy.signal import find_peaks

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
from scene_io import Scene, spec_dir, write_ply_points  # noqa: E402


def unit(v):
    return v / np.linalg.norm(v)


def planes(pc, n, dist):
    out, rest = [], pc
    for _ in range(n):
        if len(rest.points) < 1000:
            break
        m, idx = rest.segment_plane(dist, 3, 2000)
        out.append((unit(np.array(m[:3])), m[3] / np.linalg.norm(m[:3]), len(idx)))
        rest = rest.select_by_index(idx, invert=True)
    return out


def floor_ceiling(h, bw):
    lo, hi = np.percentile(h, [0.2, 99.8])
    hist, edges = np.histogram(h, bins=np.arange(lo, hi + bw, bw))
    sm = gaussian_filter1d(hist.astype(float), 1.5)
    idx, _ = find_peaks(sm, prominence=0.10 * sm.max())
    centers = edges[idx] + bw / 2

    def sharp(c):
        near = np.abs(h - c)
        return float((near < 0.02 * (hi - lo)).sum() / max((near < 0.10 * (hi - lo)).sum(), 1))
    f, c = float(centers[0]), float(centers[-1])
    return f, c, sharp(f), sharp(c), centers.round(3).tolist()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scene")
    ap.add_argument("--ceiling", type=float, default=2.70, help="assumed floor-to-ceiling height (m) for non-metric sources")
    ap.add_argument("--force_ceiling", action="store_true", help="rescale even a metric source to --ceiling")
    ap.add_argument("--frames", type=int, default=120, help="frames back-projected for the estimate")
    args = ap.parse_args()

    sc = Scene(args.scene)
    import yaml
    spec_p = spec_dir(args.scene) / "scene.yaml"
    locked = (yaml.safe_load(open(spec_p)) or {}).get("world_frame") if spec_p.exists() else None
    sc.align = None                       # estimate from raw (source frame)
    sc.refined = None
    metric = bool(sc.source.get("metric"))
    idx = np.linspace(0, sc.n - 1, min(args.frames, sc.n)).astype(int)
    pts, cols = [], []
    for i in idx:
        c = sc.conf(i)
        m = c >= np.percentile(c, 30) if c is not None else None
        p, col = sc.backproject(i, stride=3, mask=m)
        pts.append(p); cols.append(col)
    P = np.concatenate(pts); C = np.concatenate(cols)
    pc = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(P))
    pc.colors = o3d.utility.Vector3dVector(C / 255.0)
    extent = np.percentile(P, 98, 0) - np.percentile(P, 2, 0)
    unit_len = float(np.median(extent)) / 5.0        # rough "1 m" in source units (metric: ~1)
    vox = 0.015 * (1 if metric else unit_len)
    pc = pc.voxel_down_sample(vox)
    pc, _ = pc.remove_statistical_outlier(20, 2.0)
    Pd = np.asarray(pc.points)

    cam_up = unit((-sc.raw[:, :3, 1]).mean(0))
    found = planes(pc, 12, vox * 0.8)
    horiz = [p for p in found if abs(p[0] @ cam_up) > np.cos(np.radians(20))]
    up = unit(max(horiz, key=lambda p: p[2])[0]) if horiz else cam_up
    up = up if up @ cam_up > 0 else -up

    h = Pd @ up
    floor_h, ceil_h, fs, cs, peaks = floor_ceiling(h, vox * 0.7)
    if metric and not args.force_ceiling:
        s = 1.0
    else:
        s = args.ceiling / (ceil_h - floor_h)

    if locked:                            # frame frozen by the survey: keep it, only report diagnostics
        T = np.array(locked["transform"], float)
        s = float(locked["scale"])
        R = T[:3, :3] / s
        up = R[2]
        h = Pd @ up
        floor_h, ceil_h, fs, cs, peaks = floor_ceiling(h, vox * 0.7)
        W = Pd @ T[:3, :3].T + T[:3, 3]
        walls = [p for p in found if abs(p[0] @ up) < np.sin(np.radians(15))]
        return finish(sc, args, T, s, R, up, cam_up, floor_h, ceil_h, fs, cs, peaks, W, walls, pc, metric, True)
    walls = [p for p in found if abs(p[0] @ up) < np.sin(np.radians(15))]
    if walls:
        w = max(walls, key=lambda p: p[2])[0]
        x = unit(w - (w @ up) * up)
    else:
        x = unit(np.cross(up, [0, 0, 1]) if abs(up[2]) < 0.9 else np.cross(up, [1, 0, 0]))
    y = np.cross(up, x)
    R = np.stack([x, y, up])
    T = np.eye(4)
    T[:3, :3] = s * R
    W = (Pd @ R.T) * s
    cxy = np.percentile(W[:, :2], [2, 98], axis=0).mean(0)
    T[:3, 3] = [-cxy[0], -cxy[1], -s * floor_h]
    W = W + T[:3, 3]
    finish(sc, args, T, s, R, up, cam_up, floor_h, ceil_h, fs, cs, peaks, W, walls, pc, metric, False)


def finish(sc, args, T, s, R, up, cam_up, floor_h, ceil_h, fs, cs, peaks, W, walls, pc, metric, locked):
    info = {
        "locked_by_scene_yaml": locked,
        "transform": T.tolist(), "scale": s, "metric_source": metric,
        "assumed_ceiling_m": None if (metric and not args.force_ceiling) else args.ceiling,
        "up_source": up.tolist(), "cam_up_source": cam_up.tolist(),
        "floor_h_source": floor_h, "ceiling_h_source": ceil_h, "height_peaks_source": peaks,
        "ceiling_height_m": (ceil_h - floor_h) * s,
        "floor_sharpness": fs, "ceiling_sharpness": cs,
        "camera_height_m": float(np.median((sc.raw[:, :3, 3] @ up - floor_h) * s)),
        "bounds_m": {"min": np.percentile(W, 1, 0).round(3).tolist(), "max": np.percentile(W, 99, 0).round(3).tolist()},
        "walls": [{"normal_world": (R @ p[0]).round(3).tolist(), "inliers": p[2]} for p in walls],
    }
    json.dump(info, open(sc.root / "align.json", "w"), indent=1)
    keep = ("scale", "metric_source", "ceiling_height_m", "camera_height_m", "floor_sharpness", "ceiling_sharpness", "bounds_m")
    print(json.dumps({k: info[k] for k in keep}, indent=1))
    write_ply_points(sc.root / "cloud.ply", W, (np.asarray(pc.colors) * 255).astype(np.uint8))
    print(f"wrote {sc.root / 'align.json'} and cloud.ply ({len(W):,} pts)")


if __name__ == "__main__":
    main()
