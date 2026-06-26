#!/usr/bin/env bash
set -Eeuo pipefail

DATA_ROOT="${WEB_OSINT_DATA_ROOT:-/mnt/data/web-osint-platform}"
VENV="${WEB_OSINT_MEDIA_ENRICHMENT_VENV:-$DATA_ROOT/.venv-media-enrichment}"

mkdir -p "$DATA_ROOT"

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
  "numpy>=1.26.0"

echo "[$(date -Is)] media enrichment venv ready"
"$VENV/bin/python" - <<'PY'
import importlib.metadata as md

for package in ["pillow", "requests", "confluent-kafka", "numpy"]:
    print(f"{package}={md.version(package)}")
PY
