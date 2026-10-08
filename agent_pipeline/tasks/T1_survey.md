# T1 · Survey: measure the space and write the scene spec

**Goal:** `agent_pipeline/scenes/<scene>/scene.yaml` describes the space: world frame, rooms, walls and
openings, objects with positions, materials, lights, named cameras and review frames. Then
`checkpoints.survey: done`.

**Inputs** (after `pipeline.py run` stops here), all in `data/scenes/<scene>/`:
- `analysis/summary.json`: alignment diagnostics (scale, ceiling height, camera height, floor sharpness, bounds).
- `analysis/plan.png`: two plan slices with a 0.5 m grid and the camera path.
  - Left, wall height: walls and openings.
  - Right, furniture height: furniture footprints.
- `analysis/overview.jpg`: ~30 frames with their indices; this is the inventory.
- `source/rtabmap.pgm` + `.yaml` (RTAB-Map only): the occupancy grid. Its origin and resolution are in
  RTAB-Map's map frame, *before* `align.json`.

## Steps

1. **Sanity-check the alignment** (`summary.json`):
   - `camera_height_m` should be plausible: handheld 1.3–1.6 m; a robot's camera mount height.
   - `floor_sharpness` ≥ 0.35 is good. Below that, surfaces are doubled; expect ±10 cm on walls.
   - `ceiling_height_m`: assumed (LingBot) or measured (RTAB-Map).

   If the scale looks wrong and you know a real dimension, set `defaults.ceiling_height`, then run
   `pipeline.py stage <scene> align` (and `fuse`, `analyze`).
2. **Lock the world frame.** Copy `transform` and `scale` from `data/scenes/<scene>/align.json` into
   `scene.yaml` as `world_frame: {scale, transform}`; see `scenes/home_living/scene.yaml`. Do this before
   measuring anything.
3. **Inventory.** Look at `overview.jpg` (and more frames as needed:
   `pipeline.py stage <scene> grid 100,200,300` writes `analysis/grid_100-200-300.jpg`).
   - List the rooms, openings (doors, arches, windows) and every object worth modelling, with colors and
     materials as they look in the frames.
   - Note the lighting: what glows, its color temperature, night or day.
4. **Walls and rooms.** Read wall lines off `plan.png` (left).
   - Model rooms as axis-aligned rectangles and walls as axis-aligned segments with openings; see
     `docs/scene_spec.md`.
   - Where walls are doubled (ghosting), choose the layer that agrees with probes on the floor and wall corners.
   - Doors are ~2.0–2.1 m high and ~0.8 m wide.
5. **Probe positions.** Use `pipeline.py stage <scene> probe 117:70:25:lamp_base 134:410:170:table_top ...`.
   - (u, v) are pixels in the `grid_*.jpg` images.
   - Probe each object from 2–3 frames, using its base, corners and top.
   - Results go to `analysis/probes.tsv` (keep it; it's evidence for later agents).
   - A probe that returns `d=0` hit missing depth; pick another pixel.
6. **Write `scene.yaml`.** Fill in `rooms`, `walls`, `objects` (pick from the types in `docs/scene_spec.md`;
   use `box`/`cylinder` for anything else), `materials` (sRGB colors sampled from frames), lights (on lamp
   objects or in `lights:`), `cameras` (3–6 named views that show the space well) and `review.frames`
   (4–8 frames that together cover the main surfaces; prefer sharp, well-exposed ones).
7. **Append to `notes.md`:** what you measured, what you assumed, which probes back each object, doubts.

## Acceptance criteria (then set `checkpoints.survey: done`)

- `world_frame` is locked in scene.yaml.
- Every wall line in `plan.png` is covered by a wall entry. Every opening seen in the video is an opening,
  and doors into unmodelled rooms are closed.
- Every major object in `overview.jpg` exists, backed by probes (cite them in notes.md); no duplicates.
- `review.frames` and `cameras` are set.
- `pipeline.py json <scene>` succeeds. The build stage will validate the rest. If it fails, fix scene.yaml
  rather than the scripts, unless a type is genuinely missing.
