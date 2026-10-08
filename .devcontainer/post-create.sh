#!/usr/bin/env bash
# Runs once after the container is created (workspace is bind-mounted by now).
set -euo pipefail
cd /workspace

sudo chown dev:dev /home/dev/.cache

# lingbot-map as editable package (deps already baked into the image).
pip install --no-deps -e .

# CUDA extensions for the offline renderer (demo_render/batch_demo.py).
(cd demo_render/render_cuda_ext && python setup.py build_ext --inplace)

mkdir -p data/videos data/outputs

# Model checkpoint + sky segmentation models (skipped if already present).
mkdir -p checkpoints
for f in lingbot-map.pt skyseg_batch.onnx; do
  [ -f "checkpoints/$f" ] || hf download robbyant/lingbot-map "$f" --local-dir checkpoints
done
[ -f checkpoints/skyseg.onnx ] || wget -q -O checkpoints/skyseg.onnx \
  https://huggingface.co/JianyuanWang/skyseg/resolve/main/skyseg.onnx

python -c "import torch, lingbot_map; print('torch', torch.__version__, 'cuda', torch.cuda.is_available())"
echo "Ready. Try: ./run_video.sh render data/videos/<your_video>.mp4"
