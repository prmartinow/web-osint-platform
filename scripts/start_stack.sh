#!/usr/bin/env bash
set -euo pipefail

CODE_ROOT="${CODE_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

"$CODE_ROOT/scripts/init_dirs.sh"
"$CODE_ROOT/scripts/init_env.sh"

cd "$CODE_ROOT/compose"
docker compose --env-file "$CODE_ROOT/.env" up -d --build

echo "Started web-osint stack"
