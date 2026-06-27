#!/usr/bin/env bash
set -Eeuo pipefail

DATA_ROOT="${WEB_OSINT_DATA_ROOT:-${DATA_ROOT:-}}"
if [[ -z "$DATA_ROOT" ]]; then
  echo "Set WEB_OSINT_DATA_ROOT or DATA_ROOT before running init_embedding_worker_venv.sh" >&2
  exit 2
fi
VENV="${WEB_OSINT_EMBEDDING_WORKER_VENV:-$DATA_ROOT/.venv-embedding-worker}"

export PIP_DISABLE_PIP_VERSION_CHECK=1

if [[ ! -x "$VENV/bin/python" ]]; then
  echo "[$(date -Is)] creating embedding worker venv: $VENV"
  python3 -m venv "$VENV"
fi

"$VENV/bin/python" -m pip install -q -U pip
"$VENV/bin/python" -m pip install -q \
  "requests>=2.32.0" \
  "confluent-kafka>=2.6.0"

echo "[$(date -Is)] embedding worker venv ready"
