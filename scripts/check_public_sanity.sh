#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

slash='/'
local_host='local''host'
ops_user='ops''@'
model_root='WEB_OSINT_MODEL''_ROOT'
legacy_qwen='QWEN_INFERENCE''_URL'
legacy_collection='x''_research'
forbidden_pattern="(${slash}mnt${slash}data|${slash}home${slash}ops|192[.]168[.]|${local_host}:[0-9]+|127[.]0[.]0[.]1:[0-9]+|${ops_user}|${model_root}|${legacy_qwen}|${legacy_collection})"
if git grep -n -E "$forbidden_pattern" -- . ':(exclude)docs/DEVELOPMENT_HISTORY.md' ':(exclude).env' ':(exclude).env.*'; then
  echo "forbidden local environment reference found" >&2
  exit 1
fi

runtime_path_pattern='(^|/)(outbox|logs|tmp|cache|models|model-cache|qdrant/storage|clickhouse/(data|logs)|redpanda|pebble|media|ocr)(/|$)|\.(db|sqlite|sqlite3|log|jsonl|parquet|bin|safetensors)$'
if git ls-files | grep -E "$runtime_path_pattern"; then
  echo "tracked runtime/generated data artifact found" >&2
  exit 1
fi

mapfile -t python_files < <(git ls-files '*.py')
if ((${#python_files[@]})); then
  python3 -m py_compile "${python_files[@]}"
fi

while IFS= read -r shell_file; do
  bash -n "$shell_file"
done < <(git ls-files '*.sh')

if command -v node >/dev/null 2>&1; then
  while IFS= read -r js_file; do
    node --check "$js_file"
  done < <(git ls-files '*.js' '*.mjs')
else
  echo "node not found; skipping JavaScript syntax checks" >&2
fi

if command -v go >/dev/null 2>&1; then
  (cd workers/normalizer && go test ./...)
  (cd connect && go test ./...)
else
  echo "go not found; skipping Go tests" >&2
fi

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  cleanup_env=false
  if [[ ! -f .env ]]; then
    cp .env.example .env
    cleanup_env=true
  fi
  if [[ "$cleanup_env" == true ]]; then
    trap 'rm -f .env' EXIT
  fi
  docker compose --env-file .env.example -f compose/docker-compose.yml config >/dev/null
else
  echo "docker compose not found; skipping compose render check" >&2
fi
