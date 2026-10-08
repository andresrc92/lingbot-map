#!/usr/bin/env bash
# Run LingBot-Map on your own video (inside the devcontainer).
#
#   ./run_video.sh view   data/videos/my.mp4 [extra demo.py flags]
#       -> interactive point cloud viewer at http://localhost:8080
#   ./run_video.sh render data/videos/my.mp4 [extra batch_demo.py flags]
#       -> headless flythrough MP4, NPZ predictions and <name>.ply point cloud
#          in data/outputs/<name>/
#   ./run_video.sh view-ply data/outputs/<name>/<name>.ply [more.ply ...]
#       -> browser viewer for offline point clouds at http://localhost:8080
#   ./run_video.sh web
#       -> three.js viewer (Blender rebuild, scan mesh, point cloud, any dropped
#          .ply/.glb) at http://localhost:8081
#
# Defaults: --num_scale_frames 2, CPU offload, windowed mode + keyframe interval 2
# for render; GPUs under 12 GB get the low-VRAM profile below. Override any flag
# by appending it.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
REPO="$ROOT"
CKPT="${CKPT:-$ROOT/checkpoints/lingbot-map.pt}"
FPS="${FPS:-10}"
export PYTORCH_CUDA_ALLOC_CONF="${PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:True}"

usage() { sed -n 2,16p "$0"; exit 1; }
[ "${1:-}" = web ] && { shift; exec python "$ROOT/agent_pipeline/web_viewer/serve.py" "$@"; }
[ $# -ge 2 ] || usage
if [ "$1" = view-ply ]; then shift; exec python "$ROOT/tools/view_ply.py" "$@"; fi
cmd="$1"; video="$(realpath -s "$2")"; shift 2
name="$(basename "${video%.*}")"
out="$ROOT/data/outputs/$name"
mkdir -p "$out"

# Memory profile. The KV cache costs ~76 MB per cached frame at 518x294, and
# FlashInfer pre-allocates its whole page pool (~8 GB with the default 64-frame
# sliding window). On small GPUs use SDPA (allocates on demand) with a 16-frame
# window instead. LOWVRAM=0/1 forces either profile.
vram_mb=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1 || echo 0)
LOWVRAM="${LOWVRAM:-$([ "${vram_mb:-0}" -lt 12000 ] && echo 1 || echo 0)}"
if [ "$LOWVRAM" = 1 ]; then
  mem=(--use_sdpa --kv_cache_sliding_window 12); win=32
else
  mem=(); win=64
  python -c "import flashinfer" 2>/dev/null || mem=(--use_sdpa)
fi

case "$cmd" in
  view)
    cd "$ROOT/checkpoints"   # demo.py looks for skyseg.onnx in the CWD
    exec python "$REPO/demo.py" \
      --model_path "$CKPT" --video_path "$video" --fps "$FPS" \
      --num_scale_frames 2 --offload_to_cpu \
      --sky_model "$ROOT/checkpoints/skyseg.onnx" \
      "${mem[@]}" "$@"
    ;;
  render)
    # --config may be given on the command line; pull it out so it can be adapted.
    config="demo_render/config/default.yaml"; args=()
    while [ $# -gt 0 ]; do
      if [ "$1" = --config ]; then config="$2"; shift 2; else args+=("$1"); shift; fi
    done
    # batch_demo.py reuses extracted frames; drop them when the FPS changes.
    if [ "$(cat "$out/.fps" 2>/dev/null)" != "$FPS" ]; then rm -rf "$out/${name}_frames"; fi
    echo "$FPS" > "$out/.fps"
    cd "$REPO"
    common=(--output_folder "$out"
            --skyseg_model_path "$ROOT/checkpoints/skyseg_batch.onnx"
            --sky_mask_dir "$out/sky_masks")

    # 1) Inference -> per-frame predictions in $out/$name/
    python demo_render/batch_demo.py \
      --model_path "$CKPT" --video_path "$video" --fps "$FPS" \
      --config "$config" "${common[@]}" \
      --mode windowed --window_size "$win" --keyframe_interval 2 --overlap_keyframes 8 \
      --num_scale_frames 2 --kv_cache_scale_frames 2 \
      --save_predictions --no_render \
      "${mem[@]}" ${args[@]+"${args[@]}"}

    # 2) Point cloud
    python "$ROOT/tools/npz_to_ply.py" "$out/$name" -o "$out/$name.ply"

    # 3) Flythrough video, as a separate pass so the model is no longer on the GPU.
    #    Small GPUs: fewer render workers (each holds a CUDA context), capped memory, 720p.
    if [ "$LOWVRAM" = 1 ]; then
      python - "$config" "$out/render_config.yaml" <<'PY'
import sys, yaml
c = yaml.safe_load(open(sys.argv[1])) or {}
c.setdefault("pipeline", {})["num_workers"] = 2
c.setdefault("gpu", {})["memory_limit_gb"] = 1.5
c.setdefault("render", {}).update(width=1280, height=720)
yaml.safe_dump(c, open(sys.argv[2], "w"), sort_keys=False)
PY
      config="$out/render_config.yaml"
    fi
    python demo_render/batch_demo.py --load_predictions "$out/$name" \
      --config "$config" "${common[@]}" \
      --camera_vis default --frame_tag ${args[@]+"${args[@]}"} \
      || echo "WARNING: video render failed; predictions and point cloud are still in $out"

    echo "Point cloud: $out/$name.ply"
    echo "View it:     ./run_video.sh view-ply $out/$name.ply"
    ;;
  *) usage ;;
esac
