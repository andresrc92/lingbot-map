# T4 · QA: web viewer check and hand-off

**Goal:** the web exports load and look right, the scene's notes are complete, and the tracked files are
committed. Then `checkpoints.qa: done`.

## Steps

1. `python3 agent_pipeline/pipeline.py web` (or `./run_video.sh web` in the container), then open
   `http://localhost:8081/?scene=<scene>`. With a browser tool (e.g. Playwright MCP), screenshot:
   - **Baked layer, default viewpoint:** should look like the Cycles renders. Speckle means the bake had too few
     samples; the bake stage defaults to 256.
   - **Live PBR layer:** reasonable brightness. If it isn't, adjust `LIGHT_SCALE` in `web_viewer/main.js`;
     exported glTF light intensities are ~100× too bright.
   - **Scan + rebuild together:** the quickest placement QA. The scan should hug the rebuilt walls and furniture.
   - **Point cloud and "Play video path".**
2. Check the console has no errors (missing files show as "missing" in the layer list).
3. Append to `notes.md`:
   - final metrics
   - known deviations from reality: assumed scale, guessed hidden geometry, simplified objects
   - ideas for the next iteration
4. Commit `agent_pipeline/scenes/<scene>/` (and any pipeline code you improved), with a message explaining
   what changed. Never commit `data/`.

## Acceptance criteria

- All five layers load (baked, PBR, scan, points, path) and the viewpoints list the scene's cameras.
- notes.md lets a new agent understand every decision without this conversation.
