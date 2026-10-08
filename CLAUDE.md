# CLAUDE.md

This repo is a private mirror of [Robbyant/lingbot-map](https://github.com/Robbyant/lingbot-map) (a streaming 3D
reconstruction model) with two additions. Upstream code is mostly untouched; the only change to it is a low-VRAM
loading fix in `demo.py` / `demo_render/demo.py`.

1. **A GPU devcontainer and `run_video.sh`**: run LingBot-Map on your own videos. See `DEVCONTAINER.md`.
2. **`agent_pipeline/`**: an agent-in-the-loop pipeline. It takes a video (via LingBot) or an RTAB-Map `.db` and
   produces a metric scene, a realistic Blender rebuild, baked web exports and a three.js viewer.

**If you're asked to process a scene, reconstruct a room, or continue a pipeline run, read
`agent_pipeline/AGENTS.md` first.** It covers the stages, where state lives, the task playbooks and the rules.
Quick start:

```bash
python3 agent_pipeline/pipeline.py status <scene>     # derived from files; tells you what's next
python3 agent_pipeline/pipeline.py run <scene>        # automatic stages until an agent task is due
```

Ground rules:
- **Where things run.** `pipeline.py` runs on the HOST. It drives the devcontainer (Python/GPU stages) and
  headless Blender itself. Inside the container, Blender is unavailable.
- **What gets committed.** Commit `agent_pipeline/scenes/<scene>/{scene.yaml,notes.md}` and code. Never commit
  `data/`, `checkpoints/` or `agent_pipeline/config.local.json`.
- **GPU sharing.** The reference machine has 6 GB of VRAM, so don't run LingBot inference while Blender renders
  or bakes.
- **Machine setup** (Blender path, MCP add-on, RTAB-Map tools) is in `agent_pipeline/docs/setup.md`.
