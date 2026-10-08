# LingBot-Map devcontainer

Private mirror of [Robbyant/lingbot-map](https://github.com/Robbyant/lingbot-map) (remote `upstream`) with a GPU devcontainer, a low-VRAM loading fix and tools to run it on your own videos and get PLY point clouds.

```
.devcontainer/     CUDA 12.8 + Python 3.10 + torch 2.8.0 + FlashInfer + Kaolin + open3d
checkpoints/       lingbot-map.pt, skyseg.onnx, skyseg_batch.onnx (downloaded on first create)
data/videos/       put your videos here
data/outputs/      results land here
run_video.sh       one-command runner
tools/             npz_to_ply.py (predictions -> PLY), view_ply.py (browser PLY viewer)
```

`checkpoints/` and `data/` are gitignored.

## Open it

```bash
git clone https://github.com/andresrc92/lingbot-map && cd lingbot-map
git remote add upstream https://github.com/Robbyant/lingbot-map   # to pull upstream updates
```

Host requirements: NVIDIA driver + Docker + NVIDIA Container Toolkit (all already present here).

- **VS Code**: open this folder, then run *Dev Containers: Reopen in Container*.
- **CLI**:
  ```bash
  devcontainer up --workspace-folder .
  devcontainer exec --workspace-folder . bash
  ```

The first create runs `.devcontainer/post-create.sh`. It installs `lingbot-map` in editable mode, builds the render CUDA extensions, and downloads the checkpoint (~4.6 GB). The checkpoint goes into `checkpoints/`, so later creates skip the download. HF, FlashInfer JIT and torch caches live in the `lingbot-cache` Docker volume.

## Run on your own video

```bash
cp ~/Videos/walk.mp4 data/videos/

# Interactive 3D viewer -> http://localhost:8080 (port is forwarded)
./run_video.sh view data/videos/walk.mp4

# Headless flythrough video + per-frame predictions + walk.ply -> data/outputs/walk/
./run_video.sh render data/videos/walk.mp4

# Browse the offline point cloud(s) in the browser -> http://localhost:8080
./run_video.sh view-ply data/outputs/walk/walk.ply
```

Any extra flags are passed straight through to `demo.py` / `demo_render/batch_demo.py`. Useful ones:

| Flag | Effect |
|---|---|
| `--mask_sky` | Remove sky points (outdoor footage) |
| `--first_k 200` | Only use the first N frames (`view`) |
| `--stride 2` / `--image_stride 2` | Subsample frames (`view` / `render`) |
| `--mode windowed` | `view` mode, for long clips (>~300 extracted frames) |
| `--config demo_render/config/indoor.yaml` | `render` preset: `indoor.yaml`, `outdoor_drive.yaml` |
| `--rotate_clockwise_90` | Portrait phone videos (`view`) |
| `--camera_num_iterations 1` | Faster, slightly less accurate poses |

`FPS=5 ./run_video.sh ...` sets the frame-extraction rate (default 10). `CKPT=checkpoints/lingbot-map-long.pt` selects a different checkpoint.

### GPU memory (RTX 4050, 6 GB)

The model is 2.8 GB on the GPU (bf16 trunk + fp32 heads), and the KV cache costs about 76 MB per cached frame at 518×294.
FlashInfer pre-allocates its whole page pool (about 8 GB with the default 64-frame window), so on GPUs under 12 GB
`run_video.sh` switches to the **low-VRAM profile**: SDPA attention with a 12-frame KV sliding window, 32-keyframe
render windows, and for the video pass 2 render workers, a 1.5 GB budget and 720p output. Force either profile with `LOWVRAM=0|1`.

Measured on `home_living.mp4` (51 s, 508 frames at 10 fps): inference took 190 s (about 2.7 FPS). In `view` mode the peak was about 5.6 GB.

The low-VRAM loading fix is committed in `demo.py` and `demo_render/demo.py`. It loads the checkpoint on the
CPU and casts the trunk to bf16 *before* moving it to the GPU. Upstream maps the 4.6 GB fp32 checkpoint straight to the GPU,
which runs out of memory on 6 GB cards. To pull upstream changes: `git fetch upstream && git merge upstream/main`.

### Outputs of `render` (in `data/outputs/<name>/`)

| File | |
|---|---|
| `<name>.ply`, `<name>_trajectory.ply` | point cloud + camera path |
| `<name>/frame_*.npz` | per-frame depth, confidence, camera poses, intrinsics |
| `<name>_pointcloud.mp4`, `_rgb.mp4`, `_combined.mp4` | flythrough, input frames, side-by-side |
| `<name>_frames/` | extracted input frames |

## Point clouds (PLY)

`render` ends by running `tools/npz_to_ply.py`, which turns the saved predictions into
`data/outputs/<name>/<name>.ply` (binary, xyz + rgb) plus `<name>_trajectory.ply` (camera centers).
Re-export with other settings without re-running the model:

```bash
python tools/npz_to_ply.py data/outputs/walk -o data/outputs/walk/walk_dense.ply \
    --downsample 1 --conf_threshold 3 --keyframes_only
```

`tools/view_ply.py` is a viser web viewer for any `.ply`/`.pcd`/`.glb` file. You can load several files at once,
toggle each one, adjust point size and display budget live, and the camera trajectory is drawn automatically.
The `.ply` files also open in MeshLab or CloudCompare.
