#!/usr/bin/env bash
set -euo pipefail

CODE_ROOT="${CODE_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
source "$CODE_ROOT/.env"

echo "Redpanda Pandaproxy:"
curl -fsS http://127.0.0.1:18082/brokers
echo

echo "Qdrant:"
curl -fsS http://127.0.0.1:16333/healthz
echo

echo "Typesense:"
curl -fsS -H "X-TYPESENSE-API-KEY: ${TYPESENSE_API_KEY}" http://127.0.0.1:18108/health
echo

echo "ClickHouse:"
curl -fsS -u "web_osint:${CLICKHOUSE_PASSWORD}" "http://127.0.0.1:18123/ping"
echo

echo "Normalizer:"
curl -fsS http://127.0.0.1:18090/healthz
echo

echo "Research planner:"
curl -fsS http://127.0.0.1:18091/healthz
echo

echo "Containers:"
docker ps --filter 'name=web-osint' --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
