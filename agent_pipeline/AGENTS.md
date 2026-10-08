# AGENTS.md: running the room-reconstruction pipeline as an agent

You are picking up a pipeline that turns **a phone video** (via LingBot-Map) **or an RTAB-Map `.db`** into
**a realistic Blender rebuild of the space** plus **a three.js web viewer**. It is designed to run with an
agent in the loop: scripts do everything deterministic; you do the parts that need eyes and judgement
(measuring the room, choosing what is in it, matching the look). Everything you need is in this repo.
Nothing depends on a previous conversation.

Read in this order:
1. This file (orientation, rules, how state works).
2. `docs/setup.md` if the machine isn't set up yet (devcontainer, Blender, MCP, config.local.json).
3. The task playbook that `pipeline.py status` says is next: `tasks/T1_survey.md` … `tasks/T4_qa.md`.
4. `docs/scene_spec.md` whenever you edit a `scene.yaml`.
5. `scenes/home_living/` as the worked example: `scene.yaml` (finished spec), `notes.md` (the reasoning).
6. `docs/lessons_home_living.md` and `docs/what_matters.md` for the background and pitfalls.

## The loop

```bash
python3 agent_pipeline/pipeline.py status <scene>   # what's done, stale, next
python3 agent_pipeline/pipeline.py run <scene>      # runs automatic stages, stops when an agent task is due
# ... do the agent task (edit agent_pipeline/scenes/<scene>/scene.yaml, append notes.md), then:
#     set checkpoints.<task>: done in scene.yaml once its acceptance criteria hold
python3 agent_pipeline/pipeline.py run <scene>      # continue
```

Stages (in order). `auto` = container, `host` = Blender on the host, `agent` = you:

| Stage | Kind | Output (under `data/scenes/<scene>/`) |
|---|---|---|
| reconstruct | auto | LingBot: `data/outputs/<run>/` from `run_video.sh render`. RTAB-Map: `rtabmap_export/` from `rtabmap-export` |
| ingest | auto | `frames/` canonical: rgb, depth, K, raw poses, hires frame list |
| align | auto | `align.json`: source → world (Z up, floor z=0, metres). Uses `world_frame` from scene.yaml when locked |
| fuse | auto | `mesh.ply` (TSDF) + `poses.npy` (refined world poses) |
| analyze | auto | `analysis/plan.png`, `overview.jpg`, `summary.json` |
| **survey** | agent | T1: layout, inventory, materials, lights, cameras, review frames → `scene.yaml`. **Lock `world_frame`.** |
| **textures_spec** | agent | T2: crop recipes (paintings, screens, window views, floor) in `scene.yaml` |
| textures | auto | `textures/*` |
| build | host | `blender/<scene>.blend`, `blender/review/frame_*.png`, `export/<scene>_rebuild.glb` |
| compare | auto | `review/compare.jpg` (video \| render \| diff), `review/metrics.json` |
| **lookdev** | agent | T3: iterate scene.yaml → build → compare until renders match the video |
| renders | host | `blender/renders/<camera>.png` (final stills, 256 spp) |
| bake | host | `export/<scene>_baked.glb` (Cycles GI in an 8K atlas) |
| export_web | auto | `export/<scene>_scan.glb`, `_points.ply`, `_trajectory.json` |
| **qa** | agent | T4: check the viewer, finish `notes.md`, commit |

Run any single stage with `pipeline.py stage <scene> <stage> [args]`. The helper stages are `probe`, `grid`
and `hires`; see the playbooks.

## Where state lives (and what gets committed)

- **Tracked in git (the scene's memory):** `agent_pipeline/scenes/<scene>/scene.yaml` (the spec + checkpoints
  + locked world frame) and `notes.md` (your decisions log). Keep them complete enough that another agent on
  another machine can continue from them alone. Commit them at the end of each task.
- **Not in git (regenerable, large):** `data/` (videos, LingBot outputs, `data/scenes/<scene>/...`) and
  `checkpoints/` (model weights). A new machine needs the **input** (video or `.db`) copied to the same
  relative path recorded in `scene.yaml: source`. Every other file regenerates with `pipeline.py run`.
- Status is computed from those files on every call. There is no hidden state.

## Rules that save hours (each came from a real failure)

1. **Lock the world frame before measuring.** All coordinates in scene.yaml live in the frame from `align.json`.
   Re-estimating it later (new run, other parameters) silently shifts and rescales everything. T1 copies
   `transform`/`scale` from `align.json` into `scene.yaml: world_frame`. After that, align reuses it.
2. **Scale.** LingBot output has no scale; it comes from the assumed `defaults.ceiling_height` (2.70 m). If you
   know any real dimension, use it. A 10% scale error is invisible in renders but wrong in reality.
   RTAB-Map RGB-D is metric: never rescale it.
3. **Probe from 2–3 frames and dedupe.** One object seen from two sides looks like two objects (it happened
   with a floor lamp). Check probes against `plan.png` before adding objects.
4. **Colours are sRGB in scene.yaml** (picked from frames); the builder converts them to linear. Don't
   pre-linearise them.
5. **Close doors into rooms you didn't model.** Open doors show the void.
6. **GPU sharing (6 GB card here):** run LingBot inference before opening a GUI Blender; Blender holds VRAM.
   Headless Blender (build/bake) and inference must not run at the same time.
7. **Blender MCP calls over 120 s go to the background.** Prefer headless stages through `pipeline.py`; use the
   MCP (`look`, `get_scene_info`, `execute_blender_code`) for interactive inspection of `blender/<scene>.blend`.
8. **Don't trust metrics over eyes.** Night video is noisy and auto-exposed. `compare.jpg` is the truth;
   `metrics.json` only tells you whether an edit helped.
9. Blender exits 0 even when a script throws. `pipeline.py` passes `--python-exit-code 1` and checks every
   stage's outputs. If you call Blender yourself, do the same.
10. Never commit `data/`, `checkpoints/` or `agent_pipeline/config.local.json`.

## Front-ends

- **LingBot (video):** `pipeline.py init <scene> --video data/videos/<file>.mp4`. Low-VRAM defaults live in
  `run_video.sh`. Expect doubled surfaces 8–16 cm apart from windowed stitching; `fuse.py --icp` (on by default for
  this source) reduces them. Depth/pose noise is ~5–10 cm.
- **RTAB-Map (`.db`):** `pipeline.py init <scene> --rtabmap path/to/map.db`. The reconstruct stage runs
  `rtabmap-export` (local binary, or the `introlab3it/rtabmap` Docker image). Exports are optimised camera poses
  in the optical frame, registered depth (mm), calibration, the occupancy grid (`source/rtabmap.pgm/.yaml`, a
  free floor plan) and the cloud. Metric: align keeps scale 1. ICP is off by default (poses are already
  optimised). Limits:
  - **Stereo-only databases** (no depth images) aren't supported yet. Add a disparity step in `ingest_rtabmap.py`.
  - **Glass, black and out-of-range surfaces** have no sensor depth; probe nearby pixels instead.
  - **A separate higher-resolution video** isn't handled. It would need registering to the map, e.g. LingBot
    on that video plus a sim(3) ICP onto the RTAB-Map cloud.
  - **Untested on a real database.** The ingest was written against the `rtabmap-export` source (tools/Export) and
    validated on a simulated export. Check the first real run carefully and record findings in `docs/`.

## Extending

- New object type: add `t_<type>` in `blender/assets.py`, document it in `docs/scene_spec.md`.
- New opening fill: extend `build_scene.py` (`door_leaf`, `arch`, `sliding_window` are the patterns).
- Keep scripts deterministic and file-driven. Anything an agent decides goes in scene.yaml/notes.md.
