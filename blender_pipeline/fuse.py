#!/usr/bin/env python
"""Fuse LingBot-Map depth + RGB into a colored triangle mesh (TSDF), in the aligned metric frame.

    python blender_pipeline/fuse.py data/outputs/<name> [--icp] [--voxel 0.015] [-o mesh.ply]

Uses <name>/ (per-frame predictions) and <name>_align.json (from align.py). With --icp,
each frame's pose is refined by point-to-plane ICP against the cloud fused so far
(corrections are capped), which pulls together surfaces that windowed inference left
slightly offset ("ghost" layers).
"""
import argparse
import json
from pathlib import Path

import numpy as np
import open3d as o3d

from align import load_predictions


def frame_cloud(depth, rgb, K, mask, stride=4):
    H, W = depth.shape
    v, u = np.mgrid[0:H:stride, 0:W:stride]
    d = depth[::stride, ::stride]; m = mask[::stride, ::stride] & (d > 0)
    x = (u[m] - K[0, 2]) * d[m] / K[0, 0]; y = (v[m] - K[1, 2]) * d[m] / K[1, 1]
    pc = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(np.stack([x, y, d[m]], 1)))
    pc.colors = o3d.utility.Vector3dVector(rgb[::stride, ::stride][m] / 255.0)
    return pc


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("outdir", help="data/outputs/<name>")
    ap.add_argument("--voxel", type=float, default=0.015, help="TSDF voxel size (m)")
    ap.add_argument("--trunc", type=float, default=0.06, help="TSDF truncation (m)")
    ap.add_argument("--max_depth", type=float, default=5.0, help="metres")
    ap.add_argument("--conf_pct", type=float, default=30, help="drop the lowest N%% confidence pixels per frame")
    ap.add_argument("--icp", action="store_true")
    ap.add_argument("--max_corr_t", type=float, default=0.25, help="max ICP translation correction (m)")
    ap.add_argument("--max_corr_r", type=float, default=8.0, help="max ICP rotation correction (deg)")
    ap.add_argument("-o", "--output", default=None)
    args = ap.parse_args()

    out = Path(args.outdir); name = out.name
    A = json.load(open(out / f"{name}_align.json"))
    T = np.array(A["transform"]); s = A["scale"]
    R0 = T[:3, :3] / s                       # rotation part
    d = load_predictions(out / name)
    imgs, depth, K, c2w, conf = d["images"], d["depth"], d["K"], d["c2w"], d["confidence"]
    S = len(imgs)

    vol = o3d.pipelines.integration.ScalableTSDFVolume(
        voxel_length=args.voxel, sdf_trunc=args.trunc,
        color_type=o3d.pipelines.integration.TSDFVolumeColorType.RGB8)
    model = None; poses = []; n_fixed = 0
    for i in range(S):
        D = depth[i] * s                                   # metric depth
        mask = (D > 0) & (D < args.max_depth)
        if conf is not None:
            mask &= conf[i] >= np.percentile(conf[i], args.conf_pct)
        Dm = np.where(mask, D, 0).astype(np.float32)
        # camera->world in the aligned metric frame
        P = np.eye(4); P[:3, :3] = R0 @ c2w[i][:3, :3]; P[:3, 3] = T[:3, :3] @ c2w[i][:3, 3] + T[:3, 3]

        if args.icp and model is not None and i % 1 == 0:
            src = frame_cloud(Dm, imgs[i], K[i], mask)
            if len(src.points) > 500:
                src.transform(P)
                reg = o3d.pipelines.registration.registration_icp(
                    src, model, 0.05, np.eye(4),
                    o3d.pipelines.registration.TransformationEstimationPointToPlane(),
                    o3d.pipelines.registration.ICPConvergenceCriteria(max_iteration=30))
                dT = reg.transformation
                ang = np.degrees(np.arccos(np.clip((np.trace(dT[:3, :3]) - 1) / 2, -1, 1)))
                if reg.fitness > 0.3 and np.linalg.norm(dT[:3, 3]) < args.max_corr_t and ang < args.max_corr_r:
                    P = dT @ P; n_fixed += 1
        poses.append(P)

        rgbd = o3d.geometry.RGBDImage.create_from_color_and_depth(
            o3d.geometry.Image(np.ascontiguousarray(imgs[i])), o3d.geometry.Image(Dm),
            depth_scale=1.0, depth_trunc=args.max_depth, convert_rgb_to_intensity=False)
        H, W = Dm.shape
        intr = o3d.camera.PinholeCameraIntrinsic(W, H, K[i][0, 0], K[i][1, 1], K[i][0, 2], K[i][1, 2])
        vol.integrate(rgbd, intr, np.linalg.inv(P))

        if args.icp and (i % 10 == 9 or model is None):
            model = vol.extract_point_cloud().voxel_down_sample(0.02)
            model.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=0.08, max_nn=30))
        if i % 50 == 0:
            print(f"frame {i}/{S}  icp-corrected {n_fixed}", flush=True)

    mesh = vol.extract_triangle_mesh()
    # drop small floating fragments
    tri_cl, n_tri, _ = mesh.cluster_connected_triangles()
    tri_cl = np.asarray(tri_cl); n_tri = np.asarray(n_tri)
    mesh.remove_triangles_by_mask(n_tri[tri_cl] < 500); mesh.remove_unreferenced_vertices()
    mesh.compute_vertex_normals()
    dst = Path(args.output) if args.output else out / f"{name}_mesh{'_icp' if args.icp else ''}.ply"
    o3d.io.write_triangle_mesh(str(dst), mesh)
    np.save(dst.with_suffix(".poses.npy"), np.stack(poses))
    print(f"Wrote {dst}: {len(mesh.vertices):,} verts, {len(mesh.triangles):,} tris; ICP corrected {n_fixed}/{S} frames")


if __name__ == "__main__":
    main()
