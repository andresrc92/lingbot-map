# Setting up a new machine

What you need to run the pipeline from a fresh clone, on a different machine or account. Tested on Ubuntu with an
RTX 4050 Laptop (6 GB), Docker 29, Blender 5.1.2.

## 1. Host prerequisites

| Need | Why | How |
|---|---|---|
| NVIDIA GPU + driver | LingBot inference, Cycles | ≥ 6 GB VRAM works (low-VRAM profile is automatic); 12 GB+ enables FlashInfer and larger windows |
| Docker + NVIDIA Container Toolkit | the devcontainer (CUDA 12.8, torch 2.8, open3d…) | `nvidia-ctk runtime configure --runtime=docker && systemctl restart docker`; check `docker run --rm --gpus all nvidia/cuda:12.8.1-base-ubuntu22.04 nvidia-smi` |
| devcontainer CLI (or VS Code Dev Containers) | `pipeline.py` drives container stages | `npm i -g @devcontainers/cli` |
| Python 3 + PyYAML on the host | `pipeline.py` | `sudo apt install python3-yaml` (without it `pipeline.py` falls back to the container) |
| Blender ≥ 4.2 (tested 5.1.2) | build / renders / bake run headless on the host | Download the Linux tarball from blender.org, extract to `/opt/blender-<ver>/`; `pipeline.py` finds `/opt/blender*/blender`, `$BLENDER`, or `blender` on PATH |
| ~25 GB disk | image (~15 GB), weights (4.6 GB), data | |
| Optional: Docker image `introlab3it/rtabmap` or a local `rtabmap-export` | RTAB-Map front-end | `docker pull introlab3it/rtabmap:latest` |

## 2. Clone and build the environment

```bash
git clone https://github.com/andresrc92/lingbot-map && cd lingbot-map     # private: needs access
git remote add upstream https://github.com/Robbyant/lingbot-map             # optional
devcontainer up --workspace-folder .        # first time: builds the image, then post-create installs the
                                            # package, compiles render CUDA extensions, downloads checkpoints/
```

## 3. Machine config (gitignored)

Create `agent_pipeline/config.local.json` only if the defaults don't fit:

```json
{
  "blender": "/opt/blender-5.1.2/blender",
  "use_devcontainer": true,
  "rtabmap_export": "auto",
  "rtabmap_image": "introlab3it/rtabmap:latest"
}
```

- `use_devcontainer: false` means you are already in a Python environment with the container's packages.
- `rtabmap_export` is one of `auto` (local binary if present, else Docker), `local` or `docker`.

## 4. Agent tooling (Claude Code or any agent)

- **Entry points.** `CLAUDE.md` at the repo root is auto-loaded by Claude Code and points to
  `agent_pipeline/AGENTS.md`. Other agents: start at `AGENTS.md`.
- **MCP servers.** `.mcp.json` at the repo root declares two MCP servers; Claude Code asks to approve them on first
  use. Neither is required by the pipeline itself.
  - **Blender** (`uvx --python 3.11 blender-mcp`) for interactive inspection. It needs `uv` (`pip install uv` or the
    astral installer), plus the Blender add-on:
    1. Get `addon.py` from https://github.com/ahujasid/blender-mcp.
    2. In Blender: Preferences → Add-ons → Install from disk → enable it.
    3. In the 3D view sidebar → BlenderMCP → Connect.
  - **Playwright** (`npx @playwright/mcp@latest`) for screenshotting the web viewer during QA.
- **Headless stages need no MCP.** Build, renders and bake run as `blender -b` from `pipeline.py`. The MCP can't
  run in background Blender (it needs a GUI session; `xvfb-run -a blender` works on servers).

## 5. Inputs

The data folder is not in git. Copy each scene's input to the path recorded in its
`agent_pipeline/scenes/<scene>/scene.yaml: source`:
- videos: `data/videos/<name>.mp4`
- RTAB-Map: any path; set `source.db`

Everything else regenerates.

## 6. Smoke test

```bash
python3 agent_pipeline/pipeline.py status home_living   # needs data/videos/home_living.mp4 to regenerate
python3 agent_pipeline/pipeline.py run home_living       # reconstruct ~5 min, fuse ~3 min, build ~2 min on a 4050
```

A new scene: `python3 agent_pipeline/pipeline.py init <scene> --video data/videos/<scene>.mp4`, then `run`.
