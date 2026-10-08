#!/usr/bin/env python
"""Browser 3D viewer (viser) for offline point clouds.

    python tools/view_ply.py data/outputs/walk/walk.ply [more.ply ...] [--port 8080]

Open http://localhost:8080. Each file gets a visibility toggle; point size and
display budget are adjustable live. A sibling `<name>_trajectory.ply` (written by
npz_to_ply.py) is drawn as the camera path. Also opens .pcd/.xyz/.glb via open3d/trimesh.
"""
import argparse
import time
from pathlib import Path

import numpy as np
import viser


def load_points(path):
    path = Path(path)
    if path.suffix.lower() in {".glb", ".gltf", ".obj"}:
        import trimesh
        scene = trimesh.load(path)
        geoms = scene.geometry.values() if isinstance(scene, trimesh.Scene) else [scene]
        pcs = [g for g in geoms if isinstance(g, trimesh.PointCloud)]
        xyz = np.concatenate([g.vertices for g in pcs])
        rgb = np.concatenate([np.asarray(g.colors)[:, :3] if len(g.colors) else
                              np.full((len(g.vertices), 3), 200) for g in pcs])
        return xyz.astype(np.float32), rgb.astype(np.uint8)
    import open3d as o3d
    pc = o3d.io.read_point_cloud(str(path))
    xyz = np.asarray(pc.points, dtype=np.float32)
    rgb = (np.asarray(pc.colors) * 255).astype(np.uint8) if pc.has_colors() else np.full((len(xyz), 3), 200, np.uint8)
    return xyz, rgb


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("files", nargs="+")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--point_size", type=float, default=0.005)
    p.add_argument("--max_points", type=int, default=3_000_000,
                   help="initial per-file display budget (adjustable in the UI)")
    args = p.parse_args()

    server = viser.ViserServer(host="0.0.0.0", port=args.port)
    server.scene.set_up_direction("-y")  # OpenCV camera convention used by the model

    clouds = {}
    for f in args.files:
        if f.endswith("_trajectory.ply"):
            continue
        xyz, rgb = load_points(f)
        perm = np.random.default_rng(0).permutation(len(xyz))
        clouds[Path(f).stem] = (xyz[perm], rgb[perm])
        print(f"{f}: {len(xyz):,} points")

    allpts = np.concatenate([c[0][:200_000] for c in clouds.values()])
    center = np.median(allpts, axis=0)

    gui_size = server.gui.add_slider("Point size", 0.0005, 0.05, 0.0005, args.point_size)
    gui_budget = server.gui.add_slider("Max points / file (M)", 0.1, 20.0, 0.1,
                                       min(20.0, args.max_points / 1e6))
    handles, toggles = {}, {}

    def draw():
        n = int(gui_budget.value * 1e6)
        for name, (xyz, rgb) in clouds.items():
            handles[name] = server.scene.add_point_cloud(
                f"/clouds/{name}", points=xyz[:n] - center, colors=rgb[:n],
                point_size=gui_size.value, point_shape="rounded",
                visible=toggles[name].value if name in toggles else True)

    for name in clouds:
        toggles[name] = server.gui.add_checkbox(name, True)
        toggles[name].on_update(lambda _, n=name: setattr(handles[n], "visible", toggles[n].value))
    draw()
    gui_size.on_update(lambda _: [setattr(h, "point_size", gui_size.value) for h in handles.values()])
    gui_budget.on_update(lambda _: draw())

    for f in args.files:
        traj = Path(f) if f.endswith("_trajectory.ply") else Path(f).with_name(Path(f).stem + "_trajectory.ply")
        if traj.exists():
            t, _ = load_points(traj)
            if len(t) > 1:
                server.scene.add_spline_catmull_rom(f"/trajectory/{traj.stem}", t - center,
                                                    color=(255, 80, 40), line_width=3.0)

    print(f"Viewer running at http://localhost:{args.port}  (Ctrl+C to stop)")
    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
