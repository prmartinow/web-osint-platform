#!/usr/bin/env bash
set -euo pipefail

CODE_ROOT="${CODE_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
source "$CODE_ROOT/.env"

SQL_FILE="$CODE_ROOT/sql/clickhouse_init.sql"
export CLICKHOUSE_URL="http://127.0.0.1:18123/?database=default"
export CLICKHOUSE_USER="web_osint"

python3 - "$SQL_FILE" <<'PY'
import os
import base64
import sys
import urllib.error
import urllib.request

sql_path = sys.argv[1]
url = os.environ["CLICKHOUSE_URL"]
user = os.environ["CLICKHOUSE_USER"]
password = os.environ["CLICKHOUSE_PASSWORD"]
sql = open(sql_path, encoding="utf-8").read()

statements = [part.strip() for part in sql.split(";") if part.strip()]
for index, statement in enumerate(statements, start=1):
    req = urllib.request.Request(url, data=statement.encode("utf-8"), method="POST")
    req.add_header("Authorization", "Basic " + base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii"))
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"ClickHouse statement {index} failed: {body}") from exc
PY
echo "Initialized ClickHouse web_osint schema"
