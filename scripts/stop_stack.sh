#!/usr/bin/env bash
set -euo pipefail

CODE_ROOT="${CODE_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

cd "$CODE_ROOT/compose"
docker compose --env-file "$CODE_ROOT/.env" down

echo "Stopped web-osint stack"
