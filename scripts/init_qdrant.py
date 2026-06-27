#!/usr/bin/env python3
import json
import os
import urllib.error
import urllib.request
from pathlib import Path


CODE_ROOT = Path(os.environ.get("CODE_ROOT", Path(__file__).resolve().parents[1]))
BASE_URL = ""
DEFAULT_TEXT_VECTOR_SIZE = 4096
DEFAULT_VL_VECTOR_SIZE = 4096


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


def env_bool(env: dict[str, str], key: str, default: bool = False) -> bool:
    raw = os.environ.get(key) or env.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_int(env: dict[str, str], key: str, default: int) -> int:
    return int(os.environ.get(key) or env.get(key, str(default)))


def require_env_value(env: dict[str, str], key: str) -> str:
    value = os.environ.get(key) or env.get(key, "")
    if not value:
        raise SystemExit(f"Missing {key}")
    return value


def vector_specs(env: dict[str, str]) -> dict[str, dict[str, object]]:
    text_size = env_int(env, "QDRANT_TEXT_VECTOR_SIZE", DEFAULT_TEXT_VECTOR_SIZE)
    vl_size = env_int(env, "QDRANT_VL_VECTOR_SIZE", DEFAULT_VL_VECTOR_SIZE)
    return {
        "text_dense": {"size": text_size, "distance": "Cosine"},
        "ocr_dense": {"size": text_size, "distance": "Cosine"},
        "caption_dense": {"size": text_size, "distance": "Cosine"},
        "account_dense": {"size": text_size, "distance": "Cosine"},
        "vl_image_dense": {"size": vl_size, "distance": "Cosine"},
    }


def existing_vectors(collection_payload: dict) -> dict[str, dict[str, object]]:
    result = collection_payload.get("result", {})
    config = result.get("config", {})
    params = config.get("params", {})
    vectors = params.get("vectors", {})
    return vectors if isinstance(vectors, dict) else {}


def create_collection(collection: str, vectors: dict[str, dict[str, object]]) -> None:
    request(
        "PUT",
        f"/collections/{collection}",
        {
            "vectors": vectors,
            "on_disk_payload": True,
        },
    )
    print(f"Created Qdrant collection: {collection}")


def ensure_vector_schema(collection: str, desired_vectors: dict[str, dict[str, object]], env: dict[str, str]) -> None:
    current = request("GET", f"/collections/{collection}")
    current_vectors = existing_vectors(current)
    mismatches = []
    missing = {}

    for name, desired in desired_vectors.items():
        current_spec = current_vectors.get(name)
        if current_spec is None:
            missing[name] = desired
            continue
        current_size = int(current_spec.get("size", 0))
        current_distance = current_spec.get("distance")
        if current_size != desired["size"] or current_distance != desired["distance"]:
            mismatches.append((name, current_spec, desired))

    if mismatches:
        points_count = int(current.get("result", {}).get("points_count") or 0)
        if points_count == 0 and env_bool(env, "QDRANT_RECREATE_EMPTY_ON_VECTOR_MISMATCH"):
            print(f"Recreating empty Qdrant collection {collection} because vector schema changed: {mismatches}")
            request("DELETE", f"/collections/{collection}")
            create_collection(collection, desired_vectors)
            return
        details = "; ".join(
            f"{name}: current={current_spec} desired={desired}"
            for name, current_spec, desired in mismatches
        )
        raise SystemExit(
            "Qdrant vector schema mismatch. "
            "Set QDRANT_RECREATE_EMPTY_ON_VECTOR_MISMATCH=true only if the collection is empty, "
            f"or create a migration/backfill plan. Details: {details}"
        )

    if missing:
        request("PATCH", f"/collections/{collection}", {"vectors": missing})
        print(f"Added Qdrant named vectors to {collection}: {', '.join(sorted(missing))}")
    else:
        print(f"Qdrant vector schema is current: {collection}")


def main() -> None:
    global BASE_URL
    env = load_env(CODE_ROOT / ".env")
    BASE_URL = require_env_value(env, "QDRANT_URL").rstrip("/")
    collection = os.environ.get("QDRANT_COLLECTION", "web_osint_evidence_v1")
    desired_vectors = vector_specs(env)

    try:
        ensure_vector_schema(collection, desired_vectors, env)
        print(f"Qdrant collection exists: {collection}")
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
        create_collection(collection, desired_vectors)

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
        ("embedding_model", "keyword"),
        ("embedding_vector_names", "keyword"),
        ("point_kind", "keyword"),
        ("artifact_id", "keyword"),
        ("artifact_sha256", "keyword"),
        ("artifact_role", "keyword"),
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
