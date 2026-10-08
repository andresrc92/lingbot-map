# blender_pipeline: from a phone video to a Blender room and a web viewer

This pipeline turns a LingBot-Map reconstruction (`./run_video.sh render <video>`) into three things:

1. A metric, gravity-aligned **scan**: a fused, colored mesh plus a point cloud.
2. A clean, realistic **Blender rebuild** of the room (`.blend`, Cycles renders, PBR and baked-lighting `.glb`).
3. A **three.js viewer** that shows the rebuild, the scan, the point cloud and the video's camera path together. You can
   also drop any `.ply`/`.glb` onto it.

It was developed on `home_living.mp4`: 51 s, 848×478 at 60 fps, a handheld night walk from a hallway into a living room.
Everything below states what was learned on that clip, so the next run on new data starts from there.

For which inputs matter most to the Blender result, and how much the LingBot stage contributes, see
[`WHAT_MATTERS.md`](WHAT_MATTERS.md).

```
blender_pipeline/
  align.py           model frame -> metric Z-up frame (up vector, floor/ceiling, wall yaw, scale)   [container]
  fuse.py            TSDF fusion of all depth maps (+ optional ICP pose refinement)                 [container]
  textures.py        rectified crops from video frames + procedural herringbone parquet             [container]
  export_web.py      scan GLB, web point cloud, camera-path JSON, in glTF axes                      [container]
  build_blender.py   the room rebuilt in Blender (scene-specific layout; template for new rooms)    [Blender]
  export_blender.py  Rebuild collection -> PBR GLB with lights + cameras                            [Blender]
  bake_blender.py    Cycles GI baked into an 8K atlas -> unlit GLB                                  [Blender]
  analysis/          plan_views.py, frame_grid.py, probe.py: the measuring tools used for layout   [container]
  web_viewer/        index.html, main.js, serve.py: three.js viewer                                 [anywhere]
```

**Where things run:**
- **[container]:** inside the devcontainer, which has open3d, cv2 and torch.
- **[Blender]:** Blender 5.x on the host, via the Blender MCP (`execute_blender_code`) or `blender -b file.blend -P script.py`.
  The scripts default to `LINGBOT_REPO=/home/andres/focus/IAC/lingbot/lingbot-map`; set that env var on another machine.

All large outputs go to `data/` (gitignored): `data/outputs/<name>/`, `data/blender/{textures,renders,export}/` and
`data/blender/home_living.blend`.

---

## Run order

```bash
# 0. Reconstruction (container). Windowed mode, low-VRAM profile on <12 GB GPUs.
./run_video.sh render data/videos/<name>.mp4 --config demo_render/config/indoor.yaml

# 1. Metric frame + fused mesh (container)
python blender_pipeline/align.py data/outputs/<name>/<name>.ply            # -> <name>_align.json
python blender_pipeline/fuse.py  data/outputs/<name> --icp                 # -> <name>_mesh_icp.ply (+ .poses.npy)

# 2. Measure the room (container), then read the outputs
python blender_pipeline/analysis/plan_views.py data/outputs/<name>         # plan slices + camera path
python blender_pipeline/analysis/frame_grid.py data/outputs/<name> 100,200,300
python blender_pipeline/analysis/probe.py data/outputs/<name> 117:70:25:lamp 134:410:170:table ...

# 3. Textures (container). Edit the crop corners in textures.py first.
python blender_pipeline/textures.py data/outputs/<name>/<name>_frames data/blender/textures

# 4. Blender (host): edit build_blender.py's layout for the new room, then
#    exec(open("blender_pipeline/build_blender.py").read())
#    exec(open("blender_pipeline/export_blender.py").read())
#    exec(open("blender_pipeline/bake_blender.py").read())        # ~10 min at 8K/256 spp on an RTX 4050 laptop
#    then save: bpy.ops.wm.save_as_mainfile(filepath="data/blender/<name>.blend")

# 5. Web assets + viewer
python blender_pipeline/export_web.py data/outputs/<name> data/blender/export
./run_video.sh web            # or python3 blender_pipeline/web_viewer/serve.py  -> http://localhost:8081
```

Note: `export_blender.py`, `bake_blender.py`, `export_web.py` and the viewer currently use the asset name `home_living`
(the viewer takes `?scene=<name>`). Rename the outputs, or the `home_living_*` strings, for a new scene.

---

## Thought process and findings, stage by stage

### 1. Understand what the model gives you

- **Coordinate frame:** the output is in the **first camera's OpenCV frame** (x right, y down, z forward), with an
  **arbitrary scale**. There is no gravity and no metric units.
- **Windowed inference** (required for >~320 frames, and the only thing that fits on 6 GB) stitches windows with an
  estimated scale and transform. Stitching is imperfect, so the **same surface appears 2–4 times**, offset by a few cm.
  RANSAC found 3 parallel "walls" 8–16 cm apart, and the floor histogram had two peaks 14 cm apart.
- **Things tried to reduce that ghosting**, measured by how sharp the floor peak in the height histogram is:
  - streaming mode: worse. The floor smeared over ~25 cm (model units) and the ceiling was barely visible.
  - `lingbot-map-long.pt`: no better (sharpness 0.32 vs 0.40), and it added step artifacts.
  - **ICP refinement during fusion** (`fuse.py --icp`): a modest but visible gain. It corrected 326 of 508 frames, and
    edges came out crisper.
  - Conclusion: **use the default checkpoint, windowed, plus `fuse.py --icp`**. Treat the scan as a measuring reference
    and a "photogrammetry" layer, not as final geometry. Realism comes from the rebuild.

### 2. Make it metric and upright (`align.py`)

- **Up vector:** start from the mean camera "up" (−y axis of each camera-to-world matrix). Handheld video is mostly
  upright, and on `home_living` it matched the dominant horizontal plane to 0.998. Then refine it with the largest
  RANSAC plane within 20° of that.
- **Floor and ceiling:** take the **lowest and highest prominent peaks** of the height histogram (scipy `find_peaks`).
  An earlier version split the histogram at the median, which picked the sofa or table tops as the "ceiling" and gave a
  3.5 m camera height. Always sanity-check `camera_height_m` in the JSON: 1.3–1.6 m is plausible for handheld video.
- **Scale:** there is no metric cue, so **assume a ceiling height** (`--ceiling`, default 2.70 m). On `home_living`
  that gave scale 1.71, a 1.48 m camera height, a 3.2 × 5.2 m living room and a 0.95 m hallway, all believable. If you
  know a real dimension (a door is ~2.0–2.1 m, a counter ~0.9 m), adjust `--ceiling` until it matches.
- **Yaw:** align the largest wall plane with +X so the room is axis-aligned. That makes modelling in Blender much easier.
- **Output:** `<name>_align.json` holds a 4×4 transform from the model frame to the aligned frame (Z up, floor z=0,
  metres), plus diagnostics.

### 3. Fuse (`fuse.py`)

- **Depth filtering:** depth is scaled to metres, and the lowest 30% of confidence per frame plus anything beyond 5 m is
  dropped.
- **Fusion:** TSDF with a 1.5 cm voxel and 6 cm truncation, colors from the model-resolution frames (518×294).
- **ICP (`--icp`):** each frame is aligned point-to-plane against the cloud fused so far, which is re-extracted every 10
  frames. Corrections are capped at 25 cm / 8°, so a bad match can't throw a frame away.
- **Output:** a ~2.2 M-triangle colored mesh, and the refined poses (`.poses.npy`), which every later step uses.

### 4. Measure the room (`analysis/`)

- **Plan slices (`plan_views.py`):** wall-height and furniture-height slices give the room outline and the furniture
  footprints. Read wall positions off the 0.5 m grid.
- **Probing (`frame_grid.py` + `probe.py`):** pick pixels on recognisable points (lamp base, painting corners, TV
  corners, table top, window frame, arch apex) and back-project them through depth and the refined pose. Probe each
  object from **2–3 frames** and average; noise is ~5–10 cm.
- **Lesson:** the same object seen from two sides can look like two objects. On `home_living`, "floor lamp + plant" next
  to the sofa and "floor lamp + plant" next to the armchair were **one** lamp. Cross-check probes against the plan before
  modelling duplicates.
- **Layout found for `home_living`** (aligned frame, metres):

  | Element | Position |
  |---|---|
  | Living room inner faces | x −0.35 → 2.85, y −2.72 (window wall) → 2.45 (arch wall); ceiling 2.70 |
  | Hallway | x −3.70 → −0.35, y −0.55 → 0.40; doors at x −3.15/−2.35 and −1.75/−0.95 (south), −2.85/−2.05 (north) |
  | Sliding window | x 0.55 → 2.15, top 2.05; blind box above; ceiling beam along the window wall |
  | Arch | x 0.95 → 2.25, springs at 1.80. North door x −0.22 → 0.56. Dining room behind, to y 5.4 |
  | L-sofa | back on the east wall; seat x 1.90 → 2.85, y −2.62 → −0.05; chaise at the north end out to x 1.20 |
  | Coffee table / rug | table x 0.98 → 1.76, y −2.55 → −1.93; rug x 0.55 → 1.86, y −2.62 → −0.92 |
  | TV | 55" TV on a low unit against the west wall, centre y −1.70, z 0.86 |
  | Lamps, plant | red lamp (0.20, −2.50); floor lamp pole (2.56, 0.86), shade (2.38, 0.76, 1.46); palm (2.33, 0.40) |
  | Armchair, dog bed | armchair (2.33, 1.85) facing west; dog bed (0.20, 1.05) |
  | Paintings | Golden Gate on the west wall, centre y 0.95, z 1.36; colorful on the east wall, y −1.25, z 1.55 |
  | Ceiling light | 3-spot fixture at (0.95, 0.35) |

### 5. Textures from the video (`textures.py`)

- **Crops:** paintings, the TV screen and the view through the window are **perspective-rectified crops** of the original
  848×478 frames. You give 4 corners (TL, TR, BR, BL) per crop. To find them:
  - Pick the frame where the object is most frontal and fully visible (Golden Gate: 342, colorful painting: 500, TV: 287,
    window: 185).
  - Read the corners off a 25 px grid of the original frame.
  - Add a gain for underexposed night frames.
- **Parquet:** procedural herringbone, with plank colors sampled from the real floor (frame 372, avoiding glare).
  - **Lattice:** for 1×5 planks, vertical planks step by (1, −1) plank-widths, rows repeat by (−7, −3), and each
    horizontal plank sits at (−5, 0) from its vertical one. This was found by brute-force search, because hand-derived
    versions overlapped. The pattern repeats every 10 widths, so it tiles seamlessly.
  - **Tile:** 20 widths = 1.44 m for variety; Blender maps it rotated 45°.
  - **Roughness:** a map with 0.24 on planks and 0.7 in the joints, plus clear-coat, gives the glossy varnished look.

### 6. Blender rebuild (`build_blender.py`)

- **Structure:** fully procedural and idempotent. It clears and rebuilds the `Rebuild` collection, with sub-collections
  `Structure`, `Openings`, `Furniture`, `Decor`, `Lights` and `Cameras`, and re-imports the scan into `Scan`.
- **Walls:** built as boxes split around openings (`wall_x`/`wall_y` with `(start, end, top)` openings). The arch is an
  exact boolean of a cylinder out of its lintel.
- **Gotchas found (keep these):**
  - **Colors:** colors picked from video are sRGB; Blender sockets are linear. `material()` converts them with `lin()`.
    Without it, everything renders washed out (the taupe sofa came out cream).
  - **Glass shading:** smooth-shading a thin box makes glass act as a **lens**, which produced blue blobs in the window.
    Only bevelled boxes are smooth-shaded.
  - **Unmodelled rooms:** open doors into rooms that aren't modelled show the void. Close them, or model a stub room
    (the dining room exists only to be seen through the arch).
  - **Lighting balance:** at night the practical lights are everything. Final values: floor lamp 70 W at 2700 K-ish, three
    120 W spots, red lamp 12 W, a dim TV area light, and a near-black world. Exposure is 1.0 with AgX. Keep emissive
    shades dim (strength 0.35) or they clip to white.
- **Renders:** five cameras that match viewpoints in the video. Cycles GPU (OptiX) renders 1600×900 at 256 spp in about
  30 s per camera on the RTX 4050.

### 7. Web export

- **`export_blender.py`:** writes the PBR GLB, with `KHR_materials_clearcoat`/`transmission`/`sheen`, punctual lights and
  cameras. Area lights are not supported by glTF (the viewer adds a stand-in for the TV glow).
- **`bake_blender.py`:** makes realism portable.
  1. Duplicate and join every opaque mesh (modifiers applied).
  2. **Delete faces that can't be seen**: those whose normal leads outside the room volume. That's about 25% of the faces
     (wall outsides, floor undersides), and otherwise they waste atlas space on night-sky navy.
  3. Smart-UV-project a `Lightmap` atlas.
  4. **Hide the originals while baking.** Coplanar duplicates shadow each other.
  5. Bake COMBINED (diffuse direct + indirect + color + emission; no glossy) at 8192 px and 256 spp.
  6. Save it through the scene's view transform, so the unlit atlas matches the Cycles renders.
  7. Export with a single material. Glass and sheer curtains stay live PBR objects.
- **`export_web.py`:** writes the decimated scan (400 k triangles), the point cloud (8 mm voxels, ≤2.5 M points) and the
  camera path, all converted to glTF axes, Y up: `(x, y, z) → (x, z, −y)`.

### 8. Viewer (`web_viewer/`)

- **Stack:** three.js 0.170 from jsdelivr, so the browser needs internet. `serve.py` serves the repo root on 8081
  (published by the devcontainer).
- **Fixes the viewer applies to imports (needed):**
  - **Baked layer:** its material is swapped for `MeshBasicMaterial` with `toneMapped: false` (the atlas is already
    tone-mapped). Exposure is applied as a color multiplier.
  - **Lights:** Blender's exporter turns W into cd (W·683/4π), so a 70 W lamp becomes ~3800 cd. The viewer scales lights
    by `LIGHT_SCALE = 0.01`.
  - **Sheen:** Blender exports a white full-strength sheen, which turns fabrics white in three.js. The viewer tints the
    sheen with the base color.
  - **Vertex colors:** colors in the scan, PLYs and dropped files are sRGB; three.js treats them as linear. They are
    converted on load.
- **Features:** layers to toggle, viewpoints (the Blender cameras), walk mode (WASD, Shift to run, Q/E down/up), playback
  of the original camera path (2× speed, smoothed), dollhouse clip at 2.5 m, and drag-and-drop with an up-axis selector
  ("−Y" for raw `run_video.sh` outputs in OpenCV axes).

---

## Practical notes for the next run

- **GPU sharing:** run inference **before** opening Blender. Blender holds ~200 MB of VRAM, and the 6 GB inference
  profile has ~0.4 GiB of headroom. The low-VRAM KV window (12 frames) was chosen to survive this.
- **Blender MCP:** calls longer than 120 s are moved to the background. Renders and bakes still finish; wait for the
  notification before the next call. If the addon reports "outdated", code execution still works.
- **Iteration loop:** render previews at 50% resolution and 48–64 spp from the scene cameras and compare them
  side by side with the matching video frames. Most fixes came from that comparison: colors, glass shading, lamp
  brightness, door states.
- **Scene-specific vs. reusable:**
  - `build_blender.py` (layout, furniture, light placement) and the crop corners in `textures.py` are **scene-specific**.
  - `align`, `fuse`, `export_web`, `bake_blender`, `export_blender`, the analysis tools and the viewer are **generic**.
- **Checklist for new data:**
  1. `render` → `align.py`. Check `camera_height_m` and `floor_sharpness`; ≥0.35 is good.
  2. `fuse.py --icp` → `plan_views.py`. Trace walls and openings on the grid.
  3. `frame_grid.py` + `probe.py` on 10–20 landmarks, each from 2+ frames. Dedupe objects seen twice.
  4. Pick frontal frames for art, screens and windows; set the corners in `textures.py`. Sample floor colors from a
     glare-free patch.
  5. Copy `build_blender.py`, replace the layout constants and the furniture section, iterate with preview renders.
  6. Export, bake, run `export_web.py`, check in the viewer. Toggle the scan layer over the rebuild to spot placement
     errors; that's the quickest QA.
