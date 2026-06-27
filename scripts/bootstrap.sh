#!/usr/bin/env bash
set -euo pipefail

CODE_ROOT="${CODE_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

"$CODE_ROOT/scripts/start_stack.sh"

set -a
source "$CODE_ROOT/.env"
set +a

: "${PANDAPROXY_URL:?set PANDAPROXY_URL}"
: "${QDRANT_URL:?set QDRANT_URL}"
: "${CLICKHOUSE_URL:?set CLICKHOUSE_URL}"

echo "Waiting for services..."
for _ in $(seq 1 60); do
  if curl -fsS "${PANDAPROXY_URL%/}/brokers" >/dev/null 2>&1 \
    && curl -fsS "${QDRANT_URL%/}/healthz" >/dev/null 2>&1 \
    && curl -fsS "${CLICKHOUSE_URL%/}/ping" >/dev/null 2>&1; then
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
