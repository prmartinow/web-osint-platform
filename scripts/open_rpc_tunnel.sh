#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG="${CONFIG:-$ROOT/config/rpc-tunnel.env}"

if [[ ! -f "$CONFIG" ]]; then
  CONFIG="$ROOT/config/rpc-tunnel.example.env"
fi

source "$CONFIG"

LOCAL_REDPANDA_BROKER_PORT="${LOCAL_REDPANDA_BROKER_PORT:-${LOCAL_KAFKA_PORT:-19092}}"

exec ssh -N \
  -p "$RPC_PORT" \
  -L "${LOCAL_REDPANDA_BROKER_PORT}:127.0.0.1:19092" \
  -L "${LOCAL_PANDAPROXY_PORT}:127.0.0.1:18082" \
  -L "${LOCAL_TYPESENSE_PORT}:127.0.0.1:18108" \
  -L "${LOCAL_QDRANT_PORT}:127.0.0.1:16333" \
  -L "${LOCAL_CLICKHOUSE_HTTP_PORT}:127.0.0.1:18123" \
  -L "${LOCAL_NORMALIZER_PORT}:127.0.0.1:18090" \
  "${RPC_USER}@${RPC_HOST}"
