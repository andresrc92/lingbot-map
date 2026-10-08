# T2 · Textures: recipes for everything recognisable

**Goal:** `textures:` in scene.yaml has a recipe for every image-like surface:
- paintings and posters
- screens
- the view through windows
- the floor pattern

The materials reference those files. Then `checkpoints.textures: done`.

## Steps

1. **Pick one frame per item** where it is most frontal, sharp and fully in view. Browse candidates with
   `pipeline.py stage <scene> grid a,b,c`, then render full-resolution grids of the chosen ones with
   `pipeline.py stage <scene> hires 342,500` (writes `analysis/hires_342-500.jpg`, 25 px grid, hires pixel
   coordinates).
2. **Crops.** Write the four corners **TL, TR, BR, BL** (hires pixels) as a `crop` recipe:
   - set `size` to the real aspect ratio, from your probes: e.g. a 0.80 × 0.64 m painting → `[800, 640]`
   - use `gain` 1.1–1.4 for dark night frames
3. **Floor.**
   - Herringbone parquet: use the `herringbone` recipe and sample plank colors from a glare-free patch
     (`sample.box` in hires pixels).
   - Other floors (tiles, carpet, plain boards): a large rectified crop of the floor seen from above can be
     a usable tiling texture. Otherwise use a flat color with roughness.
4. **Wire them in.** Point materials at the files (`texture:`, `roughness_texture:`; `texture_emits: true`
   for screens and window views). For floors set `uv: {scale: <tile metres>, rotate: <deg>}`; herringbone
   tile metres = `tile_widths × plank_w_m`.
5. **Build and check:** run `pipeline.py run <scene>`. The textures stage runs automatically when recipes
   change. Look at `data/scenes/<scene>/textures/` and fix any crop that is skewed, cut off or shows wall.

## Acceptance criteria

- Every texture file referenced by a material exists and looks right: no skew, no wall margins, readable.
- Notes record which frame and corners were used, and why.
