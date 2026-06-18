#!/usr/bin/env bash
set -Eeuo pipefail

MODEL_ROOT="${WEB_OSINT_MODEL_ROOT:-${WEB_OSINT_DATA_ROOT:-/mnt/data/web-osint-platform}}"
VENV="${WEB_OSINT_WEBPAGE_EXTRACTION_VENV:-$MODEL_ROOT/.venv-webpage-extraction}"

ts() {
  date -u '+%Y-%m-%dT%H:%M:%SZ'
}

mkdir -p "$MODEL_ROOT"

if [[ ! -x "$VENV/bin/python" ]]; then
  echo "[$(ts)] creating webpage extraction venv: $VENV"
  python3 -m venv "$VENV"
fi

echo "[$(ts)] upgrading pip"
"$VENV/bin/python" -m pip install -U pip setuptools wheel

echo "[$(ts)] installing webpage extraction dependencies"
"$VENV/bin/python" -m pip install \
  "beautifulsoup4>=4.12.0" \
  "lxml>=5.2.0" \
  "readability-lxml>=0.8.1" \
  "markdownify>=0.12.1" \
  "confluent-kafka>=2.6.0"

echo "[$(ts)] webpage extraction venv ready"
"$VENV/bin/python" - <<'PY'
import importlib.metadata as md

for package in ["beautifulsoup4", "lxml", "readability-lxml", "markdownify", "confluent-kafka"]:
    print(f"{package}={md.version(package)}")
PY
