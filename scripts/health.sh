#!/usr/bin/env bash
set -euo pipefail

CODE_ROOT="${CODE_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
source "$CODE_ROOT/.env"

CLICKHOUSE_USER="${CLICKHOUSE_USER:-web_osint}"

: "${PANDAPROXY_URL:?set PANDAPROXY_URL}"
: "${QDRANT_URL:?set QDRANT_URL}"
: "${TYPESENSE_URL:?set TYPESENSE_URL}"
: "${TYPESENSE_API_KEY:?set TYPESENSE_API_KEY}"
: "${CLICKHOUSE_URL:?set CLICKHOUSE_URL}"
: "${CLICKHOUSE_PASSWORD:?set CLICKHOUSE_PASSWORD}"
: "${NORMALIZER_URL:?set NORMALIZER_URL}"
: "${RESEARCH_PLANNER_URL:?set RESEARCH_PLANNER_URL}"
: "${LOCAL_INFERENCE_URL:?set LOCAL_INFERENCE_URL}"
: "${EMBEDDING_WORKER_URL:?set EMBEDDING_WORKER_URL}"

echo "Redpanda Pandaproxy:"
curl -fsS "${PANDAPROXY_URL%/}/brokers"
echo

echo "Qdrant:"
curl -fsS "${QDRANT_URL%/}/healthz"
echo

echo "Typesense:"
curl -fsS -H "X-TYPESENSE-API-KEY: ${TYPESENSE_API_KEY}" "${TYPESENSE_URL%/}/health"
echo

echo "ClickHouse:"
curl -fsS -u "${CLICKHOUSE_USER}:${CLICKHOUSE_PASSWORD}" "${CLICKHOUSE_URL%/}/ping"
echo

echo "Normalizer:"
curl -fsS "${NORMALIZER_URL%/}/healthz"
echo

echo "Research planner:"
curl -fsS "${RESEARCH_PLANNER_URL%/}/healthz"
echo

echo "Local inference:"
curl -fsS "${LOCAL_INFERENCE_URL%/}/healthz"
echo

echo "Embedding worker:"
curl -fsS "${EMBEDDING_WORKER_URL%/}/healthz"
echo

echo "Containers:"
docker ps --filter 'name=web-osint' --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
