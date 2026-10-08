# T3 · Look development: make the renders match the video

**Goal:** renders from the video's own camera poses look like the video frames: layout lines up, materials
and colors read the same, lighting mood matches. Then `checkpoints.lookdev: done`.

## The loop

1. `pipeline.py run <scene>` rebuilds what changed. scene.yaml edits trigger **build**: Blender renders
   `review.frames` at 64 spp, 50% resolution, from the exact video poses. Then **compare** runs.
2. Open `data/scenes/<scene>/review/compare.jpg`. Each row is video | render | difference, with
   `ssim / luma / dE` printed. `review/metrics_history.jsonl` keeps the means of every iteration.
3. Fix the **largest** discrepancy first, edit scene.yaml, repeat. Typical order:
   1. **Geometry** (edges in the diff, SSIM): wrong wall/opening positions or misplaced objects.
      Re-probe and check `plan.png`.
   2. **Exposure / light levels** (`luma_ratio`, aim ~0.8–1.25): light `power`, `render.exposure`, emissive
      strengths (keep lamp shades dim, ~0.35, or they clip white).
   3. **Materials and colors** (`chroma_dE`): sRGB colors in `materials:`; roughness (matte paint ~0.9,
      varnished floor ~0.25 + `coat`).
   4. **Missing objects** you only notice in the comparison.
4. For an interactive look, open `data/scenes/<scene>/blender/<scene>.blend` in Blender with the MCP. Use
   `look` (camera, angles, rendered shading) and `get_scene_info`. Don't edit the .blend by hand: it's rebuilt
   from scene.yaml every time.

## Known pitfalls (already handled, but recognise them)

- **Washed-out colors** mean colors were treated as linear. scene.yaml colors are sRGB; the builder converts.
- **Glass with lens-like blobs** means a smooth-shaded thin box. The builder keeps unbevelled boxes flat.
- **Black or void areas through doors** mean an unmodelled room: close the door or add a stub room.
- **Emissive surfaces clipping to white** mean the emission strength is too high. Light comes from the real
  `light:` entries.

## Acceptance criteria

- `compare.jpg`: all review frames line up within ~10 cm visually (edges coincide). No missing major objects.
  Lighting mood and dominant colors match.
- The metrics improved over the first iteration, recorded in notes.md.
- Final stills: run `pipeline.py run` until `renders` is done, and look at `blender/renders/*.png`.
