#!/usr/bin/env bash
set -Eeuo pipefail

MODEL_ROOT="${WEB_OSINT_MODEL_ROOT:-${WEB_OSINT_DATA_ROOT:-/mnt/data/web-osint-platform}}"
VENV="${WEB_OSINT_MEDIA_ENRICHMENT_VENV:-$MODEL_ROOT/.venv-media-enrichment}"
PADDLE_HOME="${PADDLEOCR_HOME:-$MODEL_ROOT/paddleocr}"
PADDLEX_CACHE_HOME="${PADDLE_PDX_CACHE_HOME:-$PADDLE_HOME/paddlex-cache}"

mkdir -p "$MODEL_ROOT" "$PADDLE_HOME" "$PADDLEX_CACHE_HOME"
export PADDLE_PDX_CACHE_HOME="$PADDLEX_CACHE_HOME"

if [[ ! -x "$VENV/bin/python" ]]; then
  echo "[$(date -Is)] creating media enrichment venv: $VENV"
  python3 -m venv "$VENV"
fi

echo "[$(date -Is)] upgrading pip"
"$VENV/bin/python" -m pip install -U pip setuptools wheel

echo "[$(date -Is)] installing media enrichment dependencies"
"$VENV/bin/python" -m pip install \
  "pillow>=10.4.0" \
  "requests>=2.32.0" \
  "confluent-kafka>=2.6.0" \
  "numpy>=1.26.0" \
  "paddlepaddle>=3.0.0" \
  "paddleocr>=3.0.0"

echo "[$(date -Is)] media enrichment venv ready"
echo "paddle_pdx_cache_home=$PADDLE_PDX_CACHE_HOME"
"$VENV/bin/python" - <<'PY'
import importlib.metadata as md

for package in ["pillow", "requests", "confluent-kafka", "numpy", "paddlepaddle", "paddleocr"]:
    print(f"{package}={md.version(package)}")
PY
