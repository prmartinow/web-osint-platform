#!/usr/bin/env bash
set -euo pipefail

CODE_ROOT="${CODE_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

"$CODE_ROOT/scripts/init_dirs.sh"
"$CODE_ROOT/scripts/init_env.sh"

set -a
source "$CODE_ROOT/.env"
set +a

COMPOSE_PROJECT="${WEB_OSINT_COMPOSE_PROJECT:-${WEB_OSINT_CONTAINER_PREFIX:-web-osint-platform}}"

cd "$CODE_ROOT/compose"
docker compose -p "$COMPOSE_PROJECT" --env-file "$CODE_ROOT/.env" up -d --build

echo "Started web-osint stack"
