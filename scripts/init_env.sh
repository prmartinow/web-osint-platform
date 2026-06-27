#!/usr/bin/env bash
set -euo pipefail

CODE_ROOT="${CODE_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
ENV_FILE="$CODE_ROOT/.env"

if [[ -f "$ENV_FILE" ]]; then
  chmod 600 "$ENV_FILE"
  echo ".env already exists; left it unchanged"
  exit 0
fi

umask 077
typesense_key="$(openssl rand -hex 32)"
clickhouse_password="$(openssl rand -hex 32)"
data_root="${WEB_OSINT_DATA_ROOT:-${DATA_ROOT:-}}"

if [[ -z "$data_root" ]]; then
  echo "Set WEB_OSINT_DATA_ROOT or DATA_ROOT before running init_env.sh" >&2
  exit 2
fi

cat > "$ENV_FILE" <<EOF
TYPESENSE_API_KEY=$typesense_key
CLICKHOUSE_PASSWORD=$clickhouse_password
QDRANT_TEXT_VECTOR_SIZE=1536
WEB_OSINT_DATA_ROOT=$data_root
EOF

chmod 600 "$ENV_FILE"
echo "Created $ENV_FILE with generated local service secrets"
