# agent_pipeline: a space captured on video (or with RTAB-Map) → a Blender scene → the web

An automatic pipeline with an **agent in the loop**. Scripts do the deterministic work: reconstruction, alignment,
fusion, building, rendering, comparison, baking and export. An agent (Claude Code or similar) does the judgement
calls: measuring the room, deciding what is in it, choosing texture crops, matching the look. All decisions are
written to tracked files, so any new session can resume.

```
 video ──► LingBot-Map ──┐                     ┌─► T1 survey ─► T2 textures ─┐
                         ├─► canonical scene ─►│  (agent writes scene.yaml)  │
 map.db ─► rtabmap-export┘   frames/ align     └─────────────────────────────┘
             (metric)        fuse  analyze                    │
                                                              ▼
       web viewer ◄── export_web ◄── bake ◄── renders ◄── T3 lookdev loop ◄── build (Blender) ─► compare
       (three.js)                                         (agent edits scene.yaml until renders match video)
```

| Start here | For |
|---|---|
| [`AGENTS.md`](AGENTS.md) | Agents: the loop, state, rules, front-ends |
| [`docs/setup.md`](docs/setup.md) | A new machine: Docker/devcontainer, Blender, MCP, config |
| [`docs/scene_spec.md`](docs/scene_spec.md) | The `scene.yaml` format |
| [`tasks/`](tasks) | The four agent playbooks with acceptance criteria |
| [`scenes/home_living/`](scenes/home_living) | The worked example (spec + decisions log) |
| [`docs/lessons_home_living.md`](docs/lessons_home_living.md), [`docs/what_matters.md`](docs/what_matters.md) | Background: what was learned, what drives quality |
| [`tests/`](tests) | RTAB-Map front-end test with a simulated export |

```bash
python3 agent_pipeline/pipeline.py init my_room --video data/videos/my_room.mp4   # or --rtabmap /path/map.db
python3 agent_pipeline/pipeline.py run my_room      # runs until an agent task is due, says which
python3 agent_pipeline/pipeline.py status my_room
python3 agent_pipeline/pipeline.py web              # http://localhost:8081/?scene=my_room
```

## Layout

```
agent_pipeline/
  pipeline.py          orchestrator (host, stdlib): status derived from files; drives container + Blender
  lib/scene_io.py      canonical scene format (frames, poses, align) shared by all stages
  stages/              container stages: ingest_lingbot, ingest_rtabmap, align, fuse, analyze, probe,
                       textures, compare, export_web
  blender/             build_scene.py (scene.json -> .blend, review renders, PBR glb), assets.py (object
                       library), helpers.py, bake.py (Cycles GI -> unlit glb)
  web_viewer/          three.js viewer + static server
  tasks/               T1_survey, T2_textures, T3_lookdev, T4_qa
  scenes/<scene>/      TRACKED per-scene memory: scene.yaml (+ checkpoints, locked world frame), notes.md
  docs/ tests/
data/scenes/<scene>/   NOT tracked: frames/, align.json, mesh.ply, poses.npy, analysis/, textures/,
                       blender/, review/, export/
```
