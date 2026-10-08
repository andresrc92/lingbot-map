# LingBot-Map dev environment: CUDA 12.8 devel (nvcc for FlashInfer JIT + render ext; cuDNN ships with torch wheels)
# Python 3.10, PyTorch 2.8.0+cu128, FlashInfer, Kaolin, open3d.
FROM nvcr.io/nvidia/cuda:12.8.1-devel-ubuntu22.04

ARG USERNAME=dev
ARG USER_UID=1000
ARG USER_GID=1000

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    TORCH_CUDA_ARCH_LIST="8.0;8.6;8.9;9.0" \
    HF_HOME=/home/dev/.cache/huggingface

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.10 python3.10-venv python3.10-dev python3-pip \
        git git-lfs wget curl ca-certificates sudo ninja-build build-essential \
        ffmpeg libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 libgomp1 libegl1 \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid $USER_GID $USERNAME \
    && useradd --uid $USER_UID --gid $USER_GID -m -s /bin/bash $USERNAME \
    && echo "$USERNAME ALL=(root) NOPASSWD:ALL" > /etc/sudoers.d/$USERNAME \
    && python3.10 -m venv /opt/venv && chown -R $USERNAME:$USERNAME /opt/venv

USER $USERNAME

RUN pip install --upgrade pip setuptools wheel \
    && pip install torch==2.8.0 torchvision==0.23.0 --index-url https://download.pytorch.org/whl/cu128

# Core + vis + render deps (lingbot-map itself is installed editable in post-create).
# onnxruntime-gpu replaces the CPU onnxruntime from the [vis] extra; numpy<2 for open3d.
RUN pip install \
        numpy==1.26.4 Pillow huggingface_hub einops safetensors opencv-python tqdm scipy \
        "viser>=0.2.23" trimesh matplotlib requests \
        onnxruntime-gpu==1.23.2 open3d==0.19.0 pyyaml ninja \
        flashinfer-python \
    && pip install kaolin -f https://nvidia-kaolin.s3.us-east-2.amazonaws.com/torch-2.8.0_cu128.html \
    && pip install numpy==1.26.4

RUN mkdir -p /home/$USERNAME/.cache
WORKDIR /workspace
