#!/usr/bin/env python3
import json
import os
import urllib.error
import urllib.request
from pathlib import Path


CODE_ROOT = Path(os.environ.get("CODE_ROOT", Path(__file__).resolve().parents[1]))
BASE_URL = os.environ.get("QDRANT_URL", "http://127.0.0.1:16333")


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


def request(method: str, path: str, body: object | None = None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        raw = response.read()
        return json.loads(raw.decode("utf-8")) if raw else None


def main() -> None:
    env = load_env(CODE_ROOT / ".env")
    size = int(os.environ.get("QDRANT_TEXT_VECTOR_SIZE") or env.get("QDRANT_TEXT_VECTOR_SIZE", "1536"))
    collection = os.environ.get("QDRANT_COLLECTION", "web_osint_evidence_v1")

    try:
        request("GET", f"/collections/{collection}")
        print(f"Qdrant collection exists: {collection}")
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
        payload = {
            "vectors": {
                "text_dense": {"size": size, "distance": "Cosine"},
                "ocr_dense": {"size": size, "distance": "Cosine"},
                "caption_dense": {"size": size, "distance": "Cosine"},
                "account_dense": {"size": size, "distance": "Cosine"},
            },
            "on_disk_payload": True,
        }
        request("PUT", f"/collections/{collection}", payload)
        print(f"Created Qdrant collection: {collection}")

    indexes = [
        ("evidence_id", "keyword"),
        ("source_kind", "keyword"),
        ("source_project", "keyword"),
        ("author_handle", "keyword"),
        ("domain", "keyword"),
        ("has_media", "bool"),
        ("posted_at_day", "keyword"),
        ("captured_at_day", "keyword"),
        ("topics", "keyword"),
        ("entities", "keyword"),
    ]
    for field_name, field_type in indexes:
        try:
            request(
                "PUT",
                f"/collections/{collection}/index",
                {"field_name": field_name, "field_schema": field_type},
            )
            print(f"Ensured Qdrant payload index: {field_name}")
        except urllib.error.HTTPError as exc:
            if exc.code not in (400, 409):
                raise
            print(f"Qdrant payload index already present or rejected as duplicate: {field_name}")


if __name__ == "__main__":
    main()
