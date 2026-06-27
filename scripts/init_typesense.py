#!/usr/bin/env python3
import json
import os
import urllib.error
import urllib.request
from pathlib import Path


CODE_ROOT = Path(os.environ.get("CODE_ROOT", Path(__file__).resolve().parents[1]))
BASE_URL = ""


def load_env(path: Path) -> dict[str, str]:
    result = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            result[key] = value
    return result


def request(method: str, path: str, api_key: str, body: object | None = None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=data,
        method=method,
        headers={
            "X-TYPESENSE-API-KEY": api_key,
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        raw = response.read()
        return json.loads(raw.decode("utf-8")) if raw else None


def require_env_value(env: dict[str, str], key: str) -> str:
    value = os.environ.get(key) or env.get(key, "")
    if not value:
        raise SystemExit(f"Missing {key}")
    return value


def main() -> None:
    global BASE_URL
    env = load_env(CODE_ROOT / ".env")
    BASE_URL = require_env_value(env, "TYPESENSE_URL").rstrip("/")
    api_key = os.environ.get("TYPESENSE_API_KEY") or env.get("TYPESENSE_API_KEY")
    if not api_key:
        raise SystemExit("Missing TYPESENSE_API_KEY")

    schema = json.loads((CODE_ROOT / "typesense" / "evidence_posts.schema.json").read_text())
    collection_name = schema["name"]

    try:
        request("GET", f"/collections/{collection_name}", api_key)
        print(f"Typesense collection exists: {collection_name}")
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
        request("POST", "/collections", api_key, schema)
        print(f"Created Typesense collection: {collection_name}")


if __name__ == "__main__":
    main()
