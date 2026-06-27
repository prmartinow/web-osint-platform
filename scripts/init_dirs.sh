#!/usr/bin/env bash
set -euo pipefail

CODE_ROOT="${CODE_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
DATA_ROOT="${WEB_OSINT_DATA_ROOT:-${DATA_ROOT:-}}"

if [[ -z "$DATA_ROOT" ]]; then
  echo "Set WEB_OSINT_DATA_ROOT or DATA_ROOT before running init_dirs.sh" >&2
  exit 2
fi

mkdir -p \
  "$CODE_ROOT"/{compose,scripts,schemas,typesense,qdrant,sql,docs,connect,workers} \
  "$DATA_ROOT"/{redpanda,state/pebble/posts,state/pebble/accounts,state/pebble/media,state/pebble/exact-indexes,typesense,media/screenshots,media/post-images,media/videos,media/profile-images,ocr/json,ocr/text,derived/ocr,derived/vl,derived/pdf-pages,canaries/media/input,canaries/media/runs,tmp,qdrant,clickhouse/data,clickhouse/logs,logs,metrics,review/events}

chmod 755 "$DATA_ROOT" 2>/dev/null || true
chmod 700 "$DATA_ROOT"/state 2>/dev/null || true
chmod 700 "$DATA_ROOT"/clickhouse 2>/dev/null || true
chmod 700 "$DATA_ROOT"/qdrant 2>/dev/null || true
chmod 700 "$DATA_ROOT"/typesense 2>/dev/null || true

echo "Initialized Web OSINT Platform directories under $CODE_ROOT and $DATA_ROOT"
