#!/usr/bin/env bash
set -euo pipefail

CODE_ROOT="${CODE_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

"$CODE_ROOT/scripts/start_stack.sh"

echo "Waiting for services..."
for _ in $(seq 1 60); do
  if curl -fsS http://127.0.0.1:18082/brokers >/dev/null 2>&1 \
    && curl -fsS http://127.0.0.1:16333/healthz >/dev/null 2>&1 \
    && curl -fsS http://127.0.0.1:18123/ping >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

"$CODE_ROOT/scripts/create_topics.sh"
"$CODE_ROOT/scripts/init_typesense.py"
"$CODE_ROOT/scripts/init_qdrant.py"
"$CODE_ROOT/scripts/init_clickhouse.sh"
cd "$CODE_ROOT/compose"
docker compose --env-file "$CODE_ROOT/.env" restart normalizer >/dev/null
"$CODE_ROOT/scripts/health.sh"

echo "web-osint bootstrap complete"
