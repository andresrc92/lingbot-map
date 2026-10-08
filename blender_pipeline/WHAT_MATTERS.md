# What drives the quality of the Blender output

How much does the LingBot-Map stage matter to the final Blender scene, and which inputs to the Blender stage matter most?
This is an analysis based on the `home_living` run. Numbers are the ones measured during that run (see `README.md`).

## The short answer

LingBot-Map gives the Blender stage its **geometric skeleton**: which way is up, where the floor is, how the walls and
rooms connect, and where each object stands, all in consistent proportions. It does **not** provide what makes the
render look realistic. Materials, colors, textures, object shapes and lighting come from the **video frames** and from
modelling judgement.

So the LingBot stage decides whether the scene is **right** (layout and proportions match the real place). The frames
and the modelling decide whether it looks **real**. A perfect reconstruction with poor modelling looks fake. A poor
reconstruction with good modelling looks real but is in the wrong place or the wrong size.

## Inputs to the Blender stage, ranked

| # | Input | Where it comes from | Role from LingBot | Effect on the output | Sensitivity |
|---|---|---|---|---|---|
| 1 | **Metric scale** | `align.py`: assumed ceiling height (2.70 m) divided by the measured floor-ceiling distance | **None.** The model's scale is arbitrary; LingBot only supplies the floor-to-ceiling ratio. | Every dimension: room size, furniture size, camera height | **Highest.** A 10% error scales the whole scene by 10%. It's invisible in a standalone render but wrong against reality. |
| 2 | **Up vector + floor plane** | `align.py`: camera up vectors + RANSAC on LingBot points | **Full** | Whether the room is level | **Very high.** A few degrees of tilt is obvious in every render. It was robust here because it averages over thousands of points and 508 camera poses. |
| 3 | **Room layout** (walls, openings, how rooms connect) | Plan slices of the fused mesh (`analysis/plan_views.py`) | **Full** | Room shape, the hallway–room–dining relationship, window and arch positions | **High.** Ghosting left walls doubled 8–16 cm apart; I chose which layer was the wall. Wrong choices shift walls by about that much. |
| 4 | **Object identity and appearance** (what is in the room, colors, materials, shapes) | Looking at the **video frames** | **None** | Most of the perceived realism | **Highest for realism.** The sofa color alone (sRGB vs linear mistake) changed the render more than any geometric error. |
| 5 | **Textures** (paintings, TV screen, window view, floor colors) | Rectified crops of the **raw frames** (`textures.py`) | **None** | Recognisability: "it's that room" | **High.** These are the details people recognise. |
| 6 | **Lighting** (lamp types, positions, color, the night ambience) | Frames (what glows, color temperature) + light positions from LingBot probes | **Partial** (positions only) | Mood, contrast, realism | **High for realism**, low for geometry. |
| 7 | **Furniture positions** | Pixel probes back-projected through LingBot depth + poses (`analysis/probe.py`) | **Full** | Where things stand | **Medium.** Noise was 5–10 cm. One lamp was seen from two sides and looked like two objects. |
| 8 | **Camera poses** | LingBot (refined by ICP in `fuse.py`) | **Full** | Probing accuracy, the camera-path layer, choosing viewpoints that match the video | **Medium.** Pose drift becomes probe drift. |
| 9 | **Scan mesh / point cloud** | TSDF fusion of LingBot depth | **Full** | Reference/QA layer only; not part of the rebuild's geometry | **Low** for the rebuild, **total** for the scan layer. |

**Reading the table:**
- **Rows 1–3 and 7–8 are the LingBot-derived inputs.** They set geometric correctness.
- **Rows 4–6 come from the frames.** They set visual realism.
- **Row 1 is a special case.** It's the single most influential number for geometry, and LingBot can't provide it.

## Why the rebuild hides most of LingBot's errors

The Blender rebuild acts as a **denoiser with strong priors**:
- Walls are modelled as flat, vertical planes at right angles.
- Furniture is modelled as clean shapes at a single position.

So ghosting (doubled surfaces), depth noise and holes in the scan **disappear** from the output. They become, at most,
a position error of one wall offset (≤16 cm) or one probe's noise (5–10 cm). That's why a modest reconstruction
(floor-peak sharpness 0.40; streaming mode and the long checkpoint were worse) still produced a convincing scene.

The cost is that **a person had to make those choices**: which ghost layer is the real wall, which probes belong to the
same object, which floor peak is the floor. Better LingBot output would mostly save that manual work, rather than
change how the rebuild looks.

## Where better LingBot output would change the result

1. **Automation instead of manual measurement.** With clean, single-layer surfaces, walls and openings could be taken
   straight from RANSAC planes, and furniture footprints from clustering. Then `build_blender.py` could be generated
   rather than hand-written.
2. **The scan as a final asset.** With no ghosting, the fused mesh (with texture baked from the frames) could be shipped
   as a photogrammetric layer in its own right, not just as a QA reference.
3. **Larger spaces.** Drift grows with distance. In this video the hallway floor already tilted ~0.5 m over 3 m. For
   whole apartments, consistent poses across rooms matter far more than in one living room.

## What to improve, ordered by payoff

| Action | Improves | Why |
|---|---|---|
| Measure one real dimension (door height, a table) and set `--ceiling` from it | Scale (#1) | Removes the biggest single geometric uncertainty for free. |
| Capture better: slow, steady walk, lock exposure, keep lights on, overlap views, avoid pointing at the ceiling | Everything LingBot-derived + textures | Night footage with auto-exposure and fast pans hurt depth and colors. |
| Run inference with more GPU memory (FlashInfer, bigger windows, `keyframe_interval 1`) | Layout (#3), poses (#8), scan (#9) | Fewer windows means fewer stitching seams, which means less ghosting. The 6 GB profile forced 32-frame windows. |
| Take a few still photos of key objects (art, fabrics, floor) | Textures (#5), materials (#4) | Frame crops are low-res and blurry; stills give sharper, truer colors. |
| Probe each object from 2–3 frames and check against the plan | Furniture (#7) | Averages out noise and catches duplicates. |

## Rule of thumb

- **Geometry:** spend effort on **scale, then up/floor, then walls**. Furniture position errors under 10 cm are rarely
  noticeable.
- **Realism:** spend effort on **materials and colors, then textures from the frames, then lighting**. That's where the
  render goes from "CG model" to "that room".
- **LingBot quality:** it mostly decides **how much manual measuring** the Blender stage needs. It matters less for how
  good the final render can look.
