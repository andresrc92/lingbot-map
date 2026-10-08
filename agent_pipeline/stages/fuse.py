#!/usr/bin/env python
"""Fuse all depth maps into a coloured mesh (TSDF) in the world frame; optionally refine poses.

    python agent_pipeline/stages/fuse.py <scene> [--icp] [--voxel 0.015]

--icp: each frame is aligned point-to-plane to the cloud fused so far (re-extracted every 10
frames), corrections capped at 25 cm / 8 deg. On LingBot input it fixed ~60% of frames and
visibly sharpened edges (windowed inference leaves surfaces doubled 8-16 cm apart). On RTAB-Map
input poses are already globally optimised: ICP is optional (skip it if it corrects few frames).

Writes mesh.ply and poses.npy (refined camera-to-world, world frame), used by every later stage.
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import open3d as o3d

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
from scene_io import Scene  # noqa: E402


def frame_cloud(D, rgb, K, stride=4):
    H, W = D.shape
    v, u = np.mgrid[0:H:stride, 0:W:stride]
    d = D[::stride, ::stride]
    m = d > 0
    pc = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(
        np.stack([(u[m] - K[0, 2]) * d[m] / K[0, 0], (v[m] - K[1, 2]) * d[m] / K[1, 1], d[m]], 1)))
    pc.colors = o3d.utility.Vector3dVector(rgb[::stride, ::stride][m] / 255.0)
    return pc


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scene")
    ap.add_argument("--voxel", type=float, default=0.015)
    ap.add_argument("--trunc", type=float, default=0.06)
    ap.add_argument("--max_depth", type=float, default=5.0)
    ap.add_argument("--conf_pct", type=float, default=30, help="drop the lowest N%% confidence pixels per frame")
    ap.add_argument("--icp", action="store_true")
    ap.add_argument("--max_corr_t", type=float, default=0.25)
    ap.add_argument("--max_corr_r", type=float, default=8.0)
    args = ap.parse_args()

    sc = Scene(args.scene)
    if sc.align is None:
        sys.exit("align.json missing: run align first")
    sc.refined = None                     # start from aligned raw poses
    vol = o3d.pipelines.integration.ScalableTSDFVolume(
        voxel_length=args.voxel, sdf_trunc=args.trunc,
        color_type=o3d.pipelines.integration.TSDFVolumeColorType.RGB8)
    model, poses, fixed = None, [], 0
    for i in range(sc.n):
        D = sc.depth(i)
        rgb = sc.rgb(i)
        mask = (D > 0) & (D < args.max_depth)
        c = sc.conf(i)
        if c is not None:
            mask &= c >= np.percentile(c, args.conf_pct)
        D = np.where(mask, D, 0).astype(np.float32)
        P = sc.pose(i)
        if args.icp and model is not None:
            src = frame_cloud(D, rgb, sc.K(i))
            if len(src.points) > 500:
                src.transform(P)
                reg = o3d.pipelines.registration.registration_icp(
                    src, model, 0.05, np.eye(4),
                    o3d.pipelines.registration.TransformationEstimationPointToPlane(),
                    o3d.pipelines.registration.ICPConvergenceCriteria(max_iteration=30))
                dT = reg.transformation
                ang = np.degrees(np.arccos(np.clip((np.trace(dT[:3, :3]) - 1) / 2, -1, 1)))
                if reg.fitness > 0.3 and np.linalg.norm(dT[:3, 3]) < args.max_corr_t and ang < args.max_corr_r:
                    P = dT @ P
                    fixed += 1
        poses.append(P)
        H, W = D.shape
        K = sc.K(i)
        rgbd = o3d.geometry.RGBDImage.create_from_color_and_depth(
            o3d.geometry.Image(np.ascontiguousarray(rgb)), o3d.geometry.Image(D),
            depth_scale=1.0, depth_trunc=args.max_depth, convert_rgb_to_intensity=False)
        vol.integrate(rgbd, o3d.camera.PinholeCameraIntrinsic(W, H, K[0, 0], K[1, 1], K[0, 2], K[1, 2]), np.linalg.inv(P))
        if args.icp and (i % 10 == 9 or model is None):
            model = vol.extract_point_cloud().voxel_down_sample(0.02)
            model.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=0.08, max_nn=30))
        if i % 100 == 0:
            print(f"frame {i}/{sc.n}  icp-corrected {fixed}", flush=True)

    mesh = vol.extract_triangle_mesh()
    cl, nt, _ = mesh.cluster_connected_triangles()
    cl, nt = np.asarray(cl), np.asarray(nt)
    mesh.remove_triangles_by_mask(nt[cl] < 500)
    mesh.remove_unreferenced_vertices()
    mesh.compute_vertex_normals()
    o3d.io.write_triangle_mesh(str(sc.root / "mesh.ply"), mesh)
    np.save(sc.root / "poses.npy", np.stack(poses))
    print(f"wrote mesh.ply ({len(mesh.triangles):,} tris) and poses.npy; ICP corrected {fixed}/{sc.n} frames")


if __name__ == "__main__":
    main()
