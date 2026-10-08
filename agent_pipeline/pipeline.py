#!/usr/bin/env python3
"""Agent-in-the-loop orchestrator: video or RTAB-Map .db -> metric scene -> Blender rebuild -> web viewer.

Run from the repo root on the HOST (it drives the devcontainer and Blender itself):

    python3 agent_pipeline/pipeline.py init   <scene> --video data/videos/x.mp4      # LingBot front-end
    python3 agent_pipeline/pipeline.py init   <scene> --rtabmap path/to/map.db        # RTAB-Map front-end
    python3 agent_pipeline/pipeline.py status <scene>      # what is done / stale / next
    python3 agent_pipeline/pipeline.py run    <scene>      # run automatic stages until an agent task is due
    python3 agent_pipeline/pipeline.py stage  <scene> <stage> [extra args...]   # one stage, e.g. probe / analyze grid
    python3 agent_pipeline/pipeline.py web                 # three.js viewer on :8081

Status is DERIVED FROM FILES (data/scenes/<scene>/...) and from `checkpoints:` in the tracked
agent_pipeline/scenes/<scene>/scene.yaml, so any new session/agent can pick up where the last stopped.
Agent tasks are described in agent_pipeline/tasks/*.md; read agent_pipeline/AGENTS.md first.

Only the standard library is required (PyYAML is used when available, otherwise the container converts).
Machine-specific settings go in agent_pipeline/config.local.json (gitignored), e.g.
    {"blender": "/opt/blender-5.1.2/blender", "use_devcontainer": true, "rtabmap_export": "docker"}
"""
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PIPE = REPO / "agent_pipeline"
DATA = REPO / "data" / "scenes"
CFG_PATH = PIPE / "config.local.json"
CFG = json.load(open(CFG_PATH)) if CFG_PATH.exists() else {}
IN_CONTAINER = Path("/.dockerenv").exists() or os.environ.get("REMOTE_CONTAINERS") or os.environ.get("DEVCONTAINER")


# ---- execution helpers ---------------------------------------------------------------------
def sh(cmd, **kw):
    print("$", " ".join(map(str, cmd)), flush=True)
    r = subprocess.run(list(map(str, cmd)), cwd=REPO, **kw)
    if r.returncode:
        sys.exit(f"command failed ({r.returncode})")


def container(cmd):
    """Run in the GPU/python environment: directly if we are inside the devcontainer, else via the CLI."""
    if IN_CONTAINER or not CFG.get("use_devcontainer", True):
        return sh(cmd)
    dc = shutil.which("devcontainer")
    if not dc:
        sys.exit("devcontainer CLI not found: install it (npm i -g @devcontainers/cli) or set use_devcontainer=false")
    sh([dc, "up", "--workspace-folder", REPO], stdout=subprocess.DEVNULL)
    sh([dc, "exec", "--workspace-folder", REPO] + list(cmd))


def blender_bin():
    cands = [CFG.get("blender"), os.environ.get("BLENDER"), shutil.which("blender")] + sorted(glob.glob("/opt/blender*/blender"), reverse=True)
    for c in cands:
        if c and Path(c).exists():
            return c
    sys.exit("Blender not found: install Blender >= 4.2 (tested 5.1) and set \"blender\" in agent_pipeline/config.local.json")


def blender(args):
    if IN_CONTAINER:
        sys.exit("Blender stages run on the host (no Blender in the container): run pipeline.py on the host")
    # --factory-startup: ignore user add-ons/prefs (reproducible across machines); --python-exit-code: fail on errors
    sh([blender_bin(), "-b", "--factory-startup", "--python-exit-code", "1"] + list(args))


def load_yaml(path):
    try:
        import yaml
        return yaml.safe_load(open(path))
    except ImportError:
        out = subprocess.run(["python", "-c", f"import yaml,json,sys;print(json.dumps(yaml.safe_load(open('{path}'))))"],
                             capture_output=True, text=True, cwd=REPO)
        return json.loads(out.stdout)


# ---- scene paths ---------------------------------------------------------------------------
class S:
    def __init__(self, name):
        self.name = name
        self.spec_dir = PIPE / "scenes" / name
        self.yaml = self.spec_dir / "scene.yaml"
        self.root = DATA / name

    def spec(self):
        return load_yaml(self.yaml) if self.yaml.exists() else {}

    def f(self, rel):
        return self.root / rel

    def mtime(self, rel):
        p = self.f(rel) if not str(rel).startswith("/") else Path(rel)
        return p.stat().st_mtime if p.exists() else 0

    def write_json(self):
        self.root.mkdir(parents=True, exist_ok=True)
        json.dump(self.spec(), open(self.f("scene.json"), "w"), indent=1)


def checkpoint(s, key):
    return (s.spec().get("checkpoints") or {}).get(key) == "done"


def src(s):
    return (s.spec().get("source") or {})


# ---- stages ---------------------------------------------------------------------------------
# Each stage: (name, kind, is_done(s), run(s, extra)). kind: auto | agent | host. Order matters.
def st_reconstruct(s, extra):
    v = src(s)
    if v.get("type") == "rtabmap":
        db = Path(v["db"]).resolve()
        out = s.f("rtabmap_export")
        out.mkdir(parents=True, exist_ok=True)
        args = ["--images_id", "--poses_camera", "--poses_format", "11", "--opt", "2", "--map", "--cloud",
                "--voxel", "0.01", "--max_range", "6", "--output_dir"]
        mode = CFG.get("rtabmap_export", "auto")
        local = shutil.which("rtabmap-export")
        if local and mode in ("auto", "local"):
            sh([local] + args + [out, db])
        else:
            img = CFG.get("rtabmap_image", "introlab3it/rtabmap:latest")
            sh(["docker", "run", "--rm", "--user", f"{os.getuid()}:{os.getgid()}", "-v", f"{db.parent}:/in:ro",
                "-v", f"{out}:/out", img, "rtabmap-export"] + args + ["/out", f"/in/{db.name}"])
    else:
        args = v.get("render_args", ["--config", "demo_render/config/indoor.yaml"])
        container(["./run_video.sh", "render", v["video"]] + list(args))


def done_reconstruct(s):
    v = src(s)
    if v.get("type") == "rtabmap":
        return bool(glob.glob(str(s.f("rtabmap_export") / "*_camera_poses.txt")))
    run = Path(v.get("run", f"data/outputs/{Path(v.get('video', s.name)).stem}"))
    return (REPO / run / run.name / "frame_000000.npz").exists()


def st_ingest(s, extra):
    v = src(s)
    if v.get("type") == "rtabmap":
        container(["python", "agent_pipeline/stages/ingest_rtabmap.py", s.name, s.f("rtabmap_export").relative_to(REPO)]
                  + v.get("ingest_args", []) + list(extra))
    else:
        run = v.get("run", f"data/outputs/{Path(v['video']).stem}")
        container(["python", "agent_pipeline/stages/ingest_lingbot.py", s.name, run])


def py(script, *a):
    return lambda s, extra: container(["python", f"agent_pipeline/stages/{script}", s.name] + list(a) + list(extra))


def st_align(s, extra):
    c = (s.spec().get("defaults") or {}).get("ceiling_height")
    container(["python", "agent_pipeline/stages/align.py", s.name] + (["--ceiling", c] if c else []) + list(extra))


def align_done(s):
    if s.mtime("align.json") <= s.mtime("frames/poses_raw.npy"):
        return False
    wf = s.spec().get("world_frame")
    if not wf:
        return True
    cur = json.load(open(s.f("align.json")))
    return cur.get("locked_by_scene_yaml") and all(abs(a - b) < 1e-6 for ra, rb in zip(cur["transform"], wf["transform"]) for a, b in zip(ra, rb))


def st_fuse(s, extra):
    icp = (s.spec().get("pipeline") or {}).get("icp", src(s).get("type") != "rtabmap")
    container(["python", "agent_pipeline/stages/fuse.py", s.name] + (["--icp"] if icp else []) + list(extra))


def textures_hash(s):
    import hashlib
    return hashlib.sha1(json.dumps(s.spec().get("textures") or {}, sort_keys=True).encode()).hexdigest()


def textures_done(s):
    """Up to date when every recipe's output exists and the recipes haven't changed since the last build."""
    tex = s.spec().get("textures") or {}
    stamp = s.f("textures/.recipes.sha1")
    return all(s.f(f"textures/{k}").exists() for k in tex) and (not tex or (stamp.exists() and stamp.read_text() == textures_hash(s)))


def st_textures(s, extra):
    container(["python", "agent_pipeline/stages/textures.py", s.name] + list(extra))
    s.f("textures/.recipes.sha1").write_text(textures_hash(s))


def newest(s, rel):
    files = glob.glob(str(s.f(rel) / "*"))
    return max((os.path.getmtime(f) for f in files), default=0)


def st_build(s, extra):
    s.write_json()
    blender(["-P", PIPE / "blender" / "build_scene.py", "--", "--scene", s.name, "--render", "review"] + list(extra))


def build_done(s):
    return s.mtime(f"blender/{s.name}.blend") > max(s.mtime(s.yaml), s.mtime("poses.npy"))


def st_bake(s, extra):
    s.write_json()
    blender([s.f(f"blender/{s.name}.blend"), "-P", PIPE / "blender" / "bake.py", "--", "--scene", s.name] + list(extra))


def st_renders(s, extra):
    s.write_json()
    blender(["-P", PIPE / "blender" / "build_scene.py", "--", "--scene", s.name, "--render", "cameras",
             "--samples", "256", "--percent", "100"] + list(extra))


STAGES = [
    ("reconstruct", "auto", done_reconstruct, st_reconstruct,
     "LingBot: ./run_video.sh render <video> | RTAB-Map: rtabmap-export of the .db"),
    ("ingest", "auto", lambda s: s.f("frames/poses_raw.npy").exists(), st_ingest, "-> canonical frames/ (stages/ingest_*.py)"),
    ("align", "auto", align_done, st_align, "level/scale/centre -> align.json (or the frame locked in scene.yaml)"),
    ("fuse", "auto", lambda s: s.mtime("mesh.ply") > s.mtime("align.json"), st_fuse, "TSDF mesh + refined poses"),
    ("analyze", "auto", lambda s: s.mtime("analysis/plan.png") > s.mtime("mesh.ply"), py("analyze.py"), "plan.png, overview.jpg"),
    ("survey", "agent", lambda s: checkpoint(s, "survey"), None, "tasks/T1_survey.md: layout + inventory -> scene.yaml"),
    ("textures_spec", "agent", lambda s: checkpoint(s, "textures"), None, "tasks/T2_textures.md: crop recipes in scene.yaml"),
    ("textures", "auto", textures_done, st_textures, "build textures from scene.yaml recipes"),
    ("build", "host", build_done, st_build, "Blender: build .blend + review renders + PBR glb"),
    ("compare", "auto", lambda s: s.mtime("review/compare.jpg") > s.mtime(f"blender/{s.name}.blend"), py("compare.py"), "video vs render sheet + metrics"),
    ("lookdev", "agent", lambda s: checkpoint(s, "lookdev"), None, "tasks/T3_lookdev.md: iterate scene.yaml until renders match"),
    ("renders", "host", lambda s: newest(s, "blender/renders") > s.mtime(f"blender/{s.name}.blend"), st_renders, "final stills from named cameras"),
    ("bake", "host", lambda s: s.mtime(f"export/{s.name}_baked.glb") > max(1, s.mtime(f"blender/{s.name}.blend") - 1), st_bake, "Cycles GI -> 8K atlas -> baked glb"),
    ("export_web", "auto", lambda s: s.mtime(f"export/{s.name}_scan.glb") > s.mtime("mesh.ply"), py("export_web.py"), "scan glb, points, trajectory"),
    ("qa", "agent", lambda s: checkpoint(s, "qa"), None, "tasks/T4_qa.md: check in the web viewer, write notes"),
]
EXTRA = {"probe": py("probe.py"), "grid": py("analyze.py", "grid"), "hires": py("analyze.py", "hires")}


def status(s, verbose=True):
    if not s.yaml.exists():
        sys.exit(f"{s.yaml} missing: run `pipeline.py init {s.name} --video ... | --rtabmap ...`")
    nxt = None
    rows = []
    for name, kind, done, _, desc in STAGES:
        ok = bool(done(s))
        if not ok and nxt is None:
            nxt = (name, kind, desc)
        rows.append((("done" if ok else "TODO"), name, kind, desc))
    if verbose:
        print(f"scene {s.name}  (spec {s.yaml.relative_to(REPO)}, data {s.root.relative_to(REPO)})")
        for r in rows:
            print(f"  [{r[0]:4s}] {r[1]:14s} {r[2]:6s} {r[3]}")
        print("next:", f"{nxt[0]} ({nxt[1]}) - {nxt[2]}" if nxt else "nothing: scene complete")
    return nxt


def run(s, upto=None):
    while True:
        nxt = status(s, verbose=False)
        if not nxt:
            print("scene complete")
            return
        name, kind, desc = nxt
        if kind == "agent":
            print(f"\nAGENT TASK DUE: {name}\n  read agent_pipeline/{desc.split(':')[0]} and agent_pipeline/AGENTS.md;"
                  f" when its acceptance criteria hold, set checkpoints.{name.replace('_spec', '')}: done in {s.yaml.relative_to(REPO)}"
                  f" and re-run `pipeline.py run {s.name}`.")
            return
        print(f"\n=== stage {name} ({kind}) ===")
        stage = {n: (f, d) for n, _, d, f, _ in STAGES}[name]
        stage[0](s, [])
        if not stage[1](s):
            sys.exit(f"stage {name} ran but its outputs are still missing/stale: inspect the log above")
        if upto == name:
            return


TEMPLATE = """# {name}: scene spec (see agent_pipeline/docs/scene_spec.md and tasks/T1_survey.md).
name: {name}
source: {source}

checkpoints: {{survey: pending, textures: pending, lookdev: pending, qa: pending}}

defaults:
  wall_thickness: 0.15
  ceiling_height: 2.70          # assumed for non-metric sources (align.py --ceiling); measured for RTAB-Map
  baseboard: {{height: 0.09, material: trim}}

render: {{samples: 256, exposure: 1.0, view_transform: AgX, world_color: [0.05, 0.05, 0.06], resolution: [1600, 900]}}
review: {{frames: []}}          # T1: pick 4-8 frames covering the space

textures: {{}}                  # T2
materials: {{}}                 # T1/T3: at least wall, ceiling, trim, floor
rooms: []                       # T1
walls: []                       # T1
objects: []                     # T1
lights: []
cameras: []
"""


def init(name, video=None, rtabmap=None, ceiling=None):
    s = S(name)
    if s.yaml.exists():
        sys.exit(f"{s.yaml} exists; edit it instead")
    s.spec_dir.mkdir(parents=True, exist_ok=True)
    if video:
        source = json.dumps({"type": "lingbot", "video": video, "run": f"data/outputs/{Path(video).stem}"})
    else:
        source = json.dumps({"type": "rtabmap", "db": rtabmap})
    s.yaml.write_text(TEMPLATE.format(name=name, source=source))
    (s.spec_dir / "notes.md").write_text(f"# {name}: decisions log\n\nAppend dated entries: what you measured, what you decided and why, open doubts.\n")
    print(f"created {s.yaml} and notes.md; next: python3 agent_pipeline/pipeline.py run {name}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init"); p.add_argument("scene"); g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--video"); g.add_argument("--rtabmap")
    p = sub.add_parser("status"); p.add_argument("scene")
    p = sub.add_parser("run"); p.add_argument("scene"); p.add_argument("--upto")
    p = sub.add_parser("stage"); p.add_argument("scene"); p.add_argument("stage"); p.add_argument("extra", nargs=argparse.REMAINDER)
    p = sub.add_parser("json"); p.add_argument("scene")
    p = sub.add_parser("web"); p.add_argument("--port", default="8081")
    a = ap.parse_args()
    if a.cmd == "init":
        return init(a.scene, a.video, a.rtabmap)
    if a.cmd == "web":
        return sh([sys.executable, PIPE / "web_viewer" / "serve.py", "--port", a.port])
    s = S(a.scene)
    if a.cmd == "status":
        status(s)
    elif a.cmd == "run":
        run(s, a.upto)
    elif a.cmd == "json":
        s.write_json(); print("wrote", s.f("scene.json"))
    elif a.cmd == "stage":
        fns = {n: f for n, _, _, f, _ in STAGES if f} | EXTRA
        if a.stage not in fns:
            sys.exit(f"unknown stage {a.stage}; choose from {sorted(fns)}")
        fns[a.stage](s, a.extra)


if __name__ == "__main__":
    main()
