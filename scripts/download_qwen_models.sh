#!/usr/bin/env bash
set -Eeuo pipefail

DATA_ROOT="${WEB_OSINT_DATA_ROOT:-/mnt/data/web-osint-platform}"
MODELS_DIR="${WEB_OSINT_MODELS_DIR:-$DATA_ROOT/models}"
HF_VENV="${WEB_OSINT_HF_VENV:-$DATA_ROOT/.venv-hf}"
LOG_DIR="${WEB_OSINT_MODEL_LOG_DIR:-$DATA_ROOT/logs/model-downloads}"
HF_HOME="${HF_HOME:-$DATA_ROOT/huggingface}"
HF_HUB_CACHE="${HF_HUB_CACHE:-$HF_HOME/hub}"
HF_XET_CACHE="${HF_XET_CACHE:-$HF_HOME/xet}"

TEXT_MODEL="${WEB_OSINT_TEXT_EMBEDDING_MODEL:-Qwen/Qwen3-Embedding-8B}"
RERANKER_MODEL="${WEB_OSINT_RERANKER_MODEL:-Qwen/Qwen3-Reranker-8B}"
VL_MODEL="${WEB_OSINT_VL_EMBEDDING_MODEL:-Qwen/Qwen3-VL-Embedding-8B}"

mkdir -p "$MODELS_DIR" "$LOG_DIR" "$HF_HOME" "$HF_HUB_CACHE" "$HF_XET_CACHE"
LOG_FILE="$LOG_DIR/qwen-model-downloads-$(date -u +%Y%m%dT%H%M%SZ).log"
ln -sfn "$LOG_FILE" "$LOG_DIR/latest.log"
exec > >(tee -a "$LOG_FILE") 2>&1

export HF_HOME HF_HUB_CACHE HF_XET_CACHE HF_HUB_VERBOSITY="${HF_HUB_VERBOSITY:-debug}"
export PIP_DISABLE_PIP_VERSION_CHECK=1

echo "[$(date -Is)] Web OSINT Qwen model download service starting"
echo "data_root=$DATA_ROOT"
echo "models_dir=$MODELS_DIR"
echo "hf_venv=$HF_VENV"
echo "hf_home=$HF_HOME"
echo "models=$TEXT_MODEL | $RERANKER_MODEL | $VL_MODEL"

if [[ ! -x "$HF_VENV/bin/python" ]]; then
  echo "[$(date -Is)] creating isolated Hugging Face downloader venv"
  python3 -m venv "$HF_VENV"
fi

echo "[$(date -Is)] installing/updating huggingface_hub downloader in isolated venv"
"$HF_VENV/bin/python" -m pip install -U pip "huggingface_hub[hf_xet]"

if [[ -x "$HF_VENV/bin/hf" ]]; then
  HF_CLI=("$HF_VENV/bin/hf" download)
elif [[ -x "$HF_VENV/bin/huggingface-cli" ]]; then
  HF_CLI=("$HF_VENV/bin/huggingface-cli" download)
else
  echo "No Hugging Face download CLI found in $HF_VENV/bin" >&2
  exit 1
fi

download_model() {
  local repo_id="$1"
  local target_dir="$2"
  mkdir -p "$target_dir"
  echo
  echo "[$(date -Is)] starting download: $repo_id -> $target_dir"
  "${HF_CLI[@]}" "$repo_id" \
    --local-dir "$target_dir"
  echo "[$(date -Is)] finished download command: $repo_id"
}

download_model "$TEXT_MODEL" "$MODELS_DIR/Qwen3-Embedding-8B"
download_model "$RERANKER_MODEL" "$MODELS_DIR/Qwen3-Reranker-8B"
download_model "$VL_MODEL" "$MODELS_DIR/Qwen3-VL-Embedding-8B"

echo
echo "[$(date -Is)] final model directory sizes"
du -sh "$MODELS_DIR"/* 2>/dev/null || true
echo "[$(date -Is)] Web OSINT Qwen model download service completed"
