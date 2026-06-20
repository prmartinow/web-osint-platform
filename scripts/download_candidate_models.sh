#!/usr/bin/env bash
set -Eeuo pipefail

DATA_ROOT="${WEB_OSINT_DATA_ROOT:-/mnt/data/web-osint-platform}"
MODELS_DIR="${WEB_OSINT_MODELS_DIR:-$DATA_ROOT/models}"
HF_VENV="${WEB_OSINT_HF_VENV:-$DATA_ROOT/.venv-hf}"
LOG_DIR="${WEB_OSINT_MODEL_LOG_DIR:-$DATA_ROOT/logs/candidate-model-downloads}"
HF_HOME="${HF_HOME:-$DATA_ROOT/huggingface}"
HF_HUB_CACHE="${HF_HUB_CACHE:-$HF_HOME/hub}"
HF_XET_CACHE="${HF_XET_CACHE:-$HF_HOME/xet}"
HF_TOKEN_FILE="${HF_TOKEN_FILE:-/home/ops/dev/huggingface.md}"
MODEL_MANIFEST="${WEB_OSINT_CANDIDATE_MODEL_MANIFEST:-$DATA_ROOT/model-download-manifests/candidate-models.tsv}"
MAX_PARALLEL="${WEB_OSINT_CANDIDATE_DOWNLOAD_JOBS:-4}"

mkdir -p "$MODELS_DIR" "$LOG_DIR/jobs" "$HF_HOME" "$HF_HUB_CACHE" "$HF_XET_CACHE" "$(dirname "$MODEL_MANIFEST")"
LOG_FILE="$LOG_DIR/candidate-model-downloads-$(date -u +%Y%m%dT%H%M%SZ).log"
ln -sfn "$LOG_FILE" "$LOG_DIR/latest.log"
exec > >(tee -a "$LOG_FILE") 2>&1

export HF_HOME HF_HUB_CACHE HF_XET_CACHE HF_HUB_VERBOSITY="${HF_HUB_VERBOSITY:-info}"
export PIP_DISABLE_PIP_VERSION_CHECK=1

if [[ -z "${HF_TOKEN:-}" && -r "$HF_TOKEN_FILE" ]]; then
  HF_TOKEN="$(
    python3 - "$HF_TOKEN_FILE" <<'PY'
import re
import sys
from pathlib import Path

text = Path(sys.argv[1]).read_text(errors="replace")
match = re.search(r"hf_[A-Za-z0-9_-]{10,}", text)
if match:
    print(match.group(0))
PY
  )"
  if [[ -n "$HF_TOKEN" ]]; then
    export HF_TOKEN
    echo "[$(date -Is)] loaded Hugging Face token from $HF_TOKEN_FILE"
  fi
fi

if [[ ! -s "$MODEL_MANIFEST" ]]; then
  cat > "$MODEL_MANIFEST" <<'EOF'
# repo_id<TAB>local_subdir<TAB>purpose
datalab-to/lift	datalab-to/lift	structured document extraction candidate
datalab-to/chandra-ocr-2	datalab-to/chandra-ocr-2	document OCR/layout fallback candidate
PaddlePaddle/PaddleOCR-VL-1.6	PaddlePaddle/PaddleOCR-VL-1.6	hard-case document OCR/VLM fallback
lightonai/LightOnOCR-2-1B	lightonai/LightOnOCR-2-1B	compact visual OCR/layout fallback
BAAI/bge-m3	BAAI/bge-m3	neural sparse and multilingual retrieval candidate
naver/splade-v3	naver/splade-v3	neural sparse retrieval candidate
colbert-ir/colbertv2.0	colbert-ir/colbertv2.0	late-interaction retrieval baseline
jinaai/jina-colbert-v2	jinaai/jina-colbert-v2	late-interaction retrieval candidate
vidore/colqwen2.5-v0.2	vidore/colqwen2.5-v0.2	visual document retrieval candidate
vidore/colpali-v1.3-hf	vidore/colpali-v1.3-hf	visual document retrieval candidate
urchade/gliner_large-v2.1	urchade/gliner_large-v2.1	entity span extraction candidate
fastino/gliner2-large-v1	fastino/gliner2-large-v1	entity span extraction candidate
knowledgator/gliclass-base-v3.0	knowledgator/gliclass-base-v3.0	flexible evidence classifier candidate
jackboyla/glirel-large-v0	jackboyla/glirel-large-v0	relation extraction candidate
numind/NuExtract-1.5-tiny	numind/NuExtract-1.5-tiny	CPU-friendly structured extraction candidate
numind/NuExtract-2.0-8B	numind/NuExtract-2.0-8B	accuracy-oriented structured extraction candidate
numind/NuExtract3	numind/NuExtract3	multimodal structured extraction candidate
cross-encoder/nli-deberta-v3-large	cross-encoder/nli-deberta-v3-large	NLI support-refute-insufficient candidate
lytang/MiniCheck-Flan-T5-Large	lytang/MiniCheck-Flan-T5-Large	grounded factuality candidate
bespokelabs/Bespoke-MiniCheck-7B	bespokelabs/Bespoke-MiniCheck-7B	high-value grounded factuality candidate
answerdotai/ModernBERT-large	answerdotai/ModernBERT-large	encoder classifier candidate
ahmed-masry/chartgemma	ahmed-masry/chartgemma	chart/table VLM candidate
EOF
fi

echo "[$(date -Is)] Web OSINT candidate model download service starting"
echo "data_root=$DATA_ROOT"
echo "models_dir=$MODELS_DIR"
echo "model_manifest=$MODEL_MANIFEST"
echo "max_parallel=$MAX_PARALLEL"
echo "hf_venv=$HF_VENV"
echo "hf_home=$HF_HOME"
if [[ -n "${HF_TOKEN:-}" ]]; then
  echo "hf_token_loaded=yes"
else
  echo "hf_token_loaded=no"
fi

if [[ ! -x "$HF_VENV/bin/python" ]]; then
  echo "[$(date -Is)] creating isolated Hugging Face downloader venv"
  python3 -m venv "$HF_VENV"
fi

if "$HF_VENV/bin/python" - <<'PY' >/dev/null 2>&1
import huggingface_hub
import hf_xet
PY
then
  echo "[$(date -Is)] Hugging Face downloader already available in isolated venv"
else
  echo "[$(date -Is)] installing/updating huggingface_hub downloader in isolated venv"
  "$HF_VENV/bin/python" -m pip install -q -U pip "huggingface_hub[hf_xet]"
fi

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
  local local_subdir="$2"
  local purpose="${3:-candidate model}"
  local target_dir="$MODELS_DIR/$local_subdir"
  local safe_name job_log
  safe_name="$(printf "%s" "$repo_id" | tr '/:' '__')"
  job_log="$LOG_DIR/jobs/${safe_name}.log"
  mkdir -p "$target_dir"
  {
    echo "[$(date -Is)] starting download: $repo_id -> $target_dir"
    echo "purpose=$purpose"
    "${HF_CLI[@]}" "$repo_id" \
      --local-dir "$target_dir"
    echo "[$(date -Is)] finished download command: $repo_id"
  } > >(sed -u "s|^|[$repo_id] |" | tee -a "$job_log") 2>&1
}

declare -a pids=()
failures=0

wait_for_slot() {
  if ! wait -n; then
    failures=$((failures + 1))
  fi
  local live=()
  local pid
  for pid in "${pids[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
      live+=("$pid")
    fi
  done
  pids=("${live[@]}")
}

wait_for_remaining() {
  while (( ${#pids[@]} > 0 )); do
    wait_for_slot
  done
}

launch_model() {
  local repo_id="$1"
  local local_subdir="$2"
  local purpose="$3"
  download_model "$repo_id" "$local_subdir" "$purpose" &
  pids+=("$!")
}

while IFS=$'\t' read -r repo_id local_subdir purpose; do
  [[ -n "${repo_id:-}" ]] || continue
  [[ "$repo_id" =~ ^# ]] && continue
  local_subdir="${local_subdir:-$repo_id}"
  purpose="${purpose:-candidate model}"
  if (( ${#pids[@]} >= MAX_PARALLEL )); then
    wait_for_slot
  fi
  echo "[$(date -Is)] queueing parallel download: $repo_id"
  launch_model "$repo_id" "$local_subdir" "$purpose"
done < "$MODEL_MANIFEST"

wait_for_remaining

echo
echo "[$(date -Is)] final candidate model directory sizes"
du -sh "$MODELS_DIR"/* 2>/dev/null || true
if (( failures > 0 )); then
  echo "[$(date -Is)] Web OSINT candidate model download service completed with failures=$failures" >&2
  exit 1
fi
echo "[$(date -Is)] Web OSINT candidate model download service completed"
