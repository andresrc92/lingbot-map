# home_living: decisions log

The first scene through the pipeline. It's a 51 s handheld phone video at night (848×478, 60 fps): a hallway into a
living room, with a dining room glimpsed through an arch. Input: `data/videos/home_living.mp4` (not in git; copy it
there to regenerate). Front-end: LingBot.

## 2026-10-07: reconstruction and survey (first, hand-driven run; see docs/lessons_home_living.md)

**Reconstruction choices:**
- `./run_video.sh render` with `--config demo_render/config/indoor.yaml`, windowed, at 10 fps, giving 508 frames.
  This used the low-VRAM profile: SDPA, 12-frame KV window, 32-keyframe windows.
- Tried and rejected:
  - streaming mode: floor smeared ~25 cm
  - `lingbot-map-long.pt`: floor sharpness 0.32 vs 0.40, with step artifacts

  The default checkpoint in windowed mode with `fuse --icp` was best: ICP corrected 323/508 frames.
- Doubled surfaces (8–16 cm apart) remain on some walls. Where walls doubled, I took the layer consistent with
  floor and corner probes.

**World frame:** locked in scene.yaml. Up = mean camera up, refined by RANSAC (agreement 0.998). Floor and ceiling
are the lowest and highest height-histogram peaks. **Scale 1.709 assumes a 2.70 m ceiling** (no metric cue in the
video). Camera height came out 1.48 m, which is plausible handheld. If a real dimension becomes known, rescale
`world_frame` and every coordinate together.

**Layout** (from `analysis/plan.png` + probes; world frame, metres):
- Living room inner faces x −0.35 → 2.85, y −2.72 → 2.45. Hallway x −3.70 → −0.35, y −0.55 → 0.40.
  Dining room y 2.45 → 5.40 (only glimpsed).
- South wall: sliding window x 0.55 → 2.15, top 2.05; white blind box; a ceiling beam along this wall (from frames
  202/219).
- North wall: a door near the west corner (x −0.22 → 0.56) and an arch (x 0.95 → 2.25, springing at 1.80). The arch
  top probe read z ≈ 2.11, consistent with a 1.80 spring plus the semicircle above it.
- Hallway: two doors on the south side and one on the north; all **closed** because the rooms behind them aren't
  modelled (open ones showed the void).

**Objects:**
- **Inventory:** from frames 100–507.
- **Probes:** the key ones are below. Positions are averages of 2–3 frames.
  - floor lamp shade (2.59, 0.48, 1.36)@117 and (2.32, 1.00, 1.51)@423, so **one** lamp at about (2.4, 0.75).
    It looked like two lamps, each next to a plant.
  - coffee table top (1.88, −2.59, 0.39)@134 and edge (1.44, −2.50)@134
  - TV corners: x ≈ −0.3, y −2.2 → −1.2, z 0.47 → 1.1 (@253, @287). Modelled as a 55" TV (1.23 m) on a low unit.
  - Golden Gate painting: west wall, y 0.52 → 1.29, z 1.2 → 1.66 (@338)
  - colorful painting: east wall, about (2.84, −1.17, 1.61) (@117)
  - armchair (2.16, 1.86)@423 and seat (1.92, 1.71)@440; dog bed (0.27, 0.87)@355 and (0.37, 1.07)@440
  - red lamp glow (0.19, −2.58)@253; ceiling fixture about (0.84, 0.51)@474
- **L-sofa:** back on the east wall, chaise at the north end (frames 100/117/504). Modelled as `sofa` facing 180,
  chaise on the sitter's right, arm on the south end only.

**Textures** (corners in hires pixels):

| Texture | Frame | Notes |
|---|---|---|
| Golden Gate painting | 342 | |
| Colorful painting | 500 | gain 1.35; it sits in a dim area |
| TV screen | 287 | |
| Night view | 185 | through the glass |
| Parquet | — | procedural herringbone, plank colors sampled at frame 372 |

**Look:**
- **Practical lights:**

  | Light | Power | Color |
  |---|---|---|
  | Floor lamp | 70 W | warm |
  | Three ceiling spots | 120 W each | neutral |
  | Red lamp | 12 W | red |
  | TV glow | 6 W | bluish |
  | Hall dome | 60 W | neutral |
  | Dining pendant | 60 W | warm |

- **Settings:** near-black world, AgX, exposure 1.0.
- **Fixes on the first run:** sRGB→linear colors, flat-shaded glass, dim lamp shades (emission 0.35).

## 2026-10-08: port to agent_pipeline

- **The port.** The layout was moved verbatim from `legacy_build_blender.py` into `scene.yaml`, and the generic
  builder reproduces it.
- **Two pipeline bugs found while porting:**
  - Headless Blender's default startup Cube (2 m, top at z = 1) sat in the room and rendered as a white slab. The
    builder now starts from an empty factory scene.
  - Blender exits 0 on script errors. Fixed with `--python-exit-code 1` and per-stage output checks.
- **First compare** (`review/compare.jpg`, frames 100/134/185/287/342/423): geometry lines up well with the video
  poses. Mean **SSIM 0.69**, but renders are **~1.4× brighter** than the video (luma_ratio 1.29–1.71) and
  chroma dE is ~7.
- **Next agent (T3 lookdev), suggested order:**
  1. Lower `render.exposure` to ~0.7, or reduce the spot power. The video is dim, warm and noisy.
  2. Re-check the palm and armchair positions in frame 100: in the video the lamp stands between the plant and
     the sofa.
  3. The rug under the coffee table looks too large in frame 134.
- **Status:** `lookdev`, `renders`, `bake` and `qa` are pending.
- **Old outputs:** results from the first run are still in `data/blender/` (old layout, not used by the pipeline).
  They include an 8K bake, final renders and the `.blend`.
