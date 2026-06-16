#!/usr/bin/env bash
set -Eeuo pipefail

DATA_ROOT="${WEB_OSINT_DATA_ROOT:-/mnt/data/web-osint-platform}"
VENV="${WEB_OSINT_QWEN_INFERENCE_VENV:-$DATA_ROOT/.venv-qwen-inference}"

mkdir -p "$DATA_ROOT"

if [[ ! -x "$VENV/bin/python" ]]; then
  echo "[$(date -Is)] creating Qwen inference venv: $VENV"
  python3 -m venv "$VENV"
fi

echo "[$(date -Is)] upgrading pip"
"$VENV/bin/python" -m pip install -U pip setuptools wheel

echo "[$(date -Is)] installing CPU PyTorch runtime on data disk"
"$VENV/bin/python" -m pip install \
  --index-url https://download.pytorch.org/whl/cpu \
  "torch==2.8.0" "torchvision==0.23.0"

echo "[$(date -Is)] installing Qwen inference and worker dependencies"
"$VENV/bin/python" -m pip install \
  "fastapi>=0.115.0" \
  "uvicorn[standard]>=0.32.0" \
  "sentence-transformers>=5.1.0" \
  "transformers>=4.57.0" \
  "accelerate>=1.0.0" \
  "safetensors>=0.4.5" \
  "qwen-vl-utils>=0.0.14" \
  "pillow>=10.4.0" \
  "requests>=2.32.0" \
  "confluent-kafka>=2.6.0" \
  "numpy>=1.26.0"

echo "[$(date -Is)] Qwen inference venv ready"
"$VENV/bin/python" - <<'PY'
import importlib.metadata as md

for package in ["torch", "transformers", "sentence-transformers", "fastapi", "uvicorn", "confluent-kafka"]:
    print(f"{package}={md.version(package)}")
PY
