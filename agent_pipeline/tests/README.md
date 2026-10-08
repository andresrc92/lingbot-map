# Tests

## RTAB-Map front-end without a real database

`make_fake_rtabmap_export.py` turns an existing scene into a folder that mimics `rtabmap-export --images_id
--poses_camera --poses_format 11`. It imitates the file names, formats and resolutions, and moves the scene into a
rotated and shifted Z-up map frame. Use it to check the ingest, align and fuse path:

```bash
devcontainer exec --workspace-folder . python agent_pipeline/tests/make_fake_rtabmap_export.py home_living data/scenes/rtab_test/rtabmap_export
python3 agent_pipeline/pipeline.py init rtab_test --rtabmap data/fake_map.db   # .db is never read: export already present
python3 agent_pipeline/pipeline.py run rtab_test                               # should stop at the survey task
rm -rf agent_pipeline/scenes/rtab_test data/scenes/rtab_test                   # don't commit the test scene
```

**Expected** (as of 2026-10-08):
- align keeps `scale: 1.0` (metric source)
- `camera_height_m` ≈ 1.47 and `ceiling_height_m` ≈ 2.6
- `analysis/plan.png` shows axis-aligned walls (the fake 33° yaw is removed)
- fuse with ICP off corrects 0 frames

**Not covered:** the real `rtabmap-export` binary or Docker image, stereo databases, multi-camera rigs, and
depth stored as float. The first real `.db` run should be checked by hand, with findings recorded in `AGENTS.md`.
