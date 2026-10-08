# scene.yaml reference

`agent_pipeline/scenes/<scene>/scene.yaml` is the single source of truth for a scene's rebuild. `pipeline.py`
converts it to `data/scenes/<scene>/scene.json` for Blender (which has no YAML module); never edit the JSON.
The complete worked example is `agent_pipeline/scenes/home_living/scene.yaml`.

**Conventions:**
- **World frame:** Z up, floor z = 0, metres; walls roughly along X/Y. It's defined by `world_frame` / `align.json`.
- **Colors:** sRGB, 0–1, as seen in the video. The builder linearises them.
- **`facing`:** for furniture, the direction a person using it looks, in degrees (0 = +X / east, 90 = +Y / north).
  For flat things (`painting`, `image_plane`) it's one of `+X -X +Y -Y`: the side the picture faces.
- **`pos`:** the footprint centre `[x, y]`, unless a type says `[x, y, z]`.

## Top-level keys

| Key | Purpose |
|---|---|
| `name` | Scene name, the same as the folder name |
| `source` | `{type: lingbot, video, run, render_args?}` or `{type: rtabmap, db, ingest_args?}` |
| `world_frame` | `{scale, transform: 4×4}` copied from `align.json` when the survey starts. Locks the frame |
| `checkpoints` | `{survey, textures, lookdev, qa}`: `pending` or `done`. Agents set these |
| `pipeline` | Optional overrides, e.g. `{icp: false}` |
| `defaults` | `wall_thickness` (0.15), `ceiling_height` (2.70), `baseboard: {height, material}` |
| `render` | `samples`, `exposure`, `view_transform` (AgX), `world_color` (sRGB), `resolution` |
| `review` | `{frames: [...]}`: video frames to re-render from their own poses for `compare` |
| `textures` | Output file → recipe (`crop` or `herringbone`); see `stages/textures.py` |
| `materials` | key → material (below). Required keys: `trim`, plus whatever the floors, walls and objects reference |
| `rooms` | Floor and ceiling slabs |
| `walls` | Axis-aligned walls with openings |
| `objects` | Typed objects (below) |
| `lights` | Extra lights not attached to an object |
| `cameras` | Named views: `{name, pos: [x,y,z], look_at: [x,y,z], lens: 18}` |

## materials

```yaml
key: {label: "Name in Blender", color: [r,g,b], roughness: 0.5, metallic: 0, transmission: 0, sheen: 0,
      coat: 0, alpha: 1, emission: {color: [r,g,b], strength: 1},
      texture: file.jpg, texture_emits: false, roughness_texture: file.png,
      uv: {scale: 1.44, rotate: 45}}     # uv: planar world mapping for floors (tile size in metres)
```

Fallbacks are created automatically if missing: `bulb`, `black`, `darkwood`, `glass`.

**Proven values:**

| Surface | Settings |
|---|---|
| Matte paint | roughness 0.88–0.92 |
| Satin trim | roughness 0.35 |
| Varnished parquet | roughness 0.25 + `coat` 0.6 |
| Fabric | roughness 0.9–1.0, `sheen` 0.4–0.6 |
| Glass | `transmission: 1`, roughness 0.02 |
| Sheer curtain | `alpha` 0.55, `sheen` 0.5 |
| Lamp shade | emission ≤ 0.4 |
| Bulbs | emission ~20 |

## rooms

```yaml
- {name: living, x: [x0, x1], y: [y0, y1], height: 2.70, floor: parquet, ceiling: ceiling, crown: {size: 0.05, material: ceiling}}
```

`x`/`y` are the inner faces. The room boxes also define the "interior volume" used by the bake to drop
invisible faces, so include every space the camera can see, including spaces glimpsed through doors.

## walls

```yaml
- name: north
  axis: y            # "y": wall at constant y (runs along X); "x": constant x (runs along Y)
  face: 2.45         # coordinate of the face that looks into the room
  room_side: -1      # +1 if the room is on the larger-coordinate side of the face, -1 otherwise
  span: [-0.50, 3.00]    # along the wall; extend by the wall thickness past room corners to close them
  thickness: 0.15    # optional
  material: wall     # optional (default "wall")
  baseboard: {...} | false   # optional override
  openings:
    - {span: [a, b], top: 2.08, bottom: 0, fill: {...}}
```

**Opening `fill` types:**

| Type | Parameters | Notes |
|---|---|---|
| `none` | `casing` (default true) | A plain cased opening |
| `door` | `open_deg` (> 0 swings **away** from `room_side`), `glass: true` | Hinged at `span[0]`. **Use 0 (closed) for rooms you didn't model** |
| `arch` | `trim_material`, `threshold: true` | `top` is the **spring height**; the semicircle adds (b−a)/2 above it |
| `sliding_window` | `panels: 2`, `blind_box: true`, `frame_material: alu`, `outside: {balcony_depth, balcony_material, backdrop: {material, distance, size: [w,h], z}}` | `backdrop` is an emissive image plane outside: the view through the glass |

Openings with `bottom: 0` interrupt the baseboard. With `bottom > 0` (windows with a sill) a sill block is built.

## objects (`type:` → parameters)

| Type | Parameters |
|---|---|
| `box` | `min`, `max` ([x,y,z]), `material`, `bevel`, `segments`, `rotate` [deg x,y,z about the centre] |
| `cylinder` | `pos` [x,y,z] centre, `radius`, `height`, `radius_top`, `verts`, `cap`, `rotate`, `solidify`, `material` |
| `image_plane` | `pos` [x,y,z], `size` [w,h], `facing` ±X/±Y, `material` (textured) |
| `painting` | `pos` [x,y,z] **on the wall face**, `size` [w,h], `facing` ±X/±Y, `material` (image), `frame_material`, `border`, `depth` |
| `sofa` | `pos`, `facing`, `length`, `depth`, `arms: [left, right]` (as seen by the sitter), `chaise: {side: left\|right, width, extra}`, `seat_cushions`, `back_cushions`, `material`, `leg_material` |
| `armchair` | `pos`, `facing`, `material`, `leg_material` (0.84 × 0.84 m) |
| `chair` | `pos`, `facing`, `material` (simple dining chair) |
| `table` | `min`, `max` ([x,y] footprint), `height`, `top`, `leg`, `shelf`, `material` |
| `tv` | `pos` [x,y,z] screen centre, `facing`, `width`, `height`, `stand`, `stand_z`, `screen_material`, `body_material`, `glow: {power, color}` |
| `floor_lamp` | `base` [x,y], `shade` [x,y,z], `shade_radius`, `shade_height`, `light: {power, color, size}`, `pole_material`, `shade_material`, `base_material` |
| `glow_cylinder` | `pos`, `height`, `radius`, `material` (emissive), `light: {...}` |
| `ceiling_spots` | `pos`, `count`, `radius`, `tilt`, `ceiling`, `material`, `light: {power, color, cone}` |
| `dome_light` | `pos`, `radius`, `ceiling`, `material`, `light: {...}` |
| `pendant` | `pos`, `drop`, `ceiling`, `material`, `light: {...}` |
| `curtain` | `axis` (x: hangs along X at y=`at`), `at`, `span` [a,b], `z` [z0,z1], `waves`, `amp`, `material` |
| `plant` | `pos`, `pot_height`, `fronds`, `size`, `seed`, `pot_material`, `leaf_material` |
| `branches` | `pos` [x,y,z], `count`, `length` [min,max], `seed`, `material` |
| `pet_bed` | `pos`, `facing`, `size` [l,w], `material` |

**Lights** (`light:` on objects, or entries in `lights:`): `power` in Blender watts.

| Light | Power on home_living |
|---|---|
| Floor lamp | 70 |
| Ceiling spots | 120 each |
| Pendant | 60 |
| Glow lamp | 12 |

**Colors:** warm ≈ `[1.0, 0.70, 0.42]`, neutral ≈ `[1.0, 0.82, 0.62]`.

**Missing a type?** Add `t_<type>` to `blender/assets.py` (front = local +X, back = local −X, built around an
Empty rotated by `facing`) and document it here. For one-offs, compose `box`/`cylinder` entries.
