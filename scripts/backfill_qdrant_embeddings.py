#!/usr/bin/env python3
from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
import time
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import Any


def require_env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise SystemExit(f"Missing {name}")
    return value


CLICKHOUSE_URL = require_env("CLICKHOUSE_URL").rstrip("/")
CLICKHOUSE_DATABASE = os.environ.get("CLICKHOUSE_DATABASE", "web_osint")
CLICKHOUSE_USER = os.environ.get("CLICKHOUSE_USER", "web_osint")
CLICKHOUSE_PASSWORD = os.environ.get("CLICKHOUSE_PASSWORD", "")
LOCAL_INFERENCE_URL = require_env("LOCAL_INFERENCE_URL").rstrip("/")
QDRANT_URL = require_env("QDRANT_URL").rstrip("/")
QDRANT_COLLECTION = os.environ.get("QDRANT_COLLECTION", "web_osint_evidence_v1")
LIMIT = int(os.environ.get("BACKFILL_LIMIT", "0"))
OFFSET = int(os.environ.get("BACKFILL_OFFSET", "0"))
BATCH_SIZE = int(os.environ.get("BACKFILL_BATCH_SIZE", "1"))
MAX_TEXT_CHARS = int(os.environ.get("BACKFILL_MAX_TEXT_CHARS", "1000"))
REQUEST_TIMEOUT = float(os.environ.get("BACKFILL_REQUEST_TIMEOUT", "600"))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def stable_hash(*parts: str) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def uuid_from(value: str) -> str:
    digest = stable_hash(value)
    return f"{digest[0:8]}-{digest[8:12]}-{digest[12:16]}-{digest[16:20]}-{digest[20:32]}"


def day_string(value: Any) -> str:
    text = str(value or "")
    return text[:10] if len(text) >= 10 else ""


def clean_text(value: Any) -> str:
    text = str(value or "").strip()
    return text[:MAX_TEXT_CHARS]


def clickhouse_request(query: str) -> bytes:
    url = CLICKHOUSE_URL + "/?" + urllib.parse.urlencode({"database": CLICKHOUSE_DATABASE, "query": query})
    req = urllib.request.Request(url)
    if CLICKHOUSE_PASSWORD:
        raw = f"{CLICKHOUSE_USER}:{CLICKHOUSE_PASSWORD}".encode("utf-8")
        req.add_header("Authorization", "Basic " + base64.b64encode(raw).decode("ascii"))
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:2000]
        raise RuntimeError(f"ClickHouse HTTP {exc.code}: {body}") from exc


def load_rows() -> list[dict[str, Any]]:
    limit_clause = f"LIMIT {LIMIT}" if LIMIT > 0 else ""
    offset_clause = f"OFFSET {OFFSET}" if OFFSET > 0 else ""
    query = f"""
SELECT
  evidence_id,
  argMax(source_kind, evidence_captured_at) AS source_kind,
  argMax(source_project, evidence_captured_at) AS source_project,
  argMax(canonical_url, evidence_captured_at) AS canonical_url,
  argMax(author_handle, evidence_captured_at) AS author_handle,
  argMax(domain, evidence_captured_at) AS domain,
  argMax(title, evidence_captured_at) AS title,
  argMax(evidence_text, evidence_captured_at) AS text,
  argMax(length(evidence_text), evidence_captured_at) AS text_length,
  argMax(topics, evidence_captured_at) AS topics,
  argMax(entities, evidence_captured_at) AS entities,
  max(evidence_captured_at) AS captured_at,
  max(evidence_posted_at) AS posted_at,
  max(has_media) AS has_media,
  max(has_ocr) AS has_ocr
FROM (
  SELECT *, text AS evidence_text, captured_at AS evidence_captured_at, posted_at AS evidence_posted_at
  FROM evidence_events
  WHERE length(text) > 0
)
GROUP BY evidence_id
ORDER BY text_length ASC, captured_at ASC
{limit_clause}
{offset_clause}
FORMAT JSONEachRow
"""
    raw = clickhouse_request(query)
    rows = []
    for line in raw.decode("utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def point_key(row: dict[str, Any]) -> str:
    source_kind = str(row.get("source_kind") or "")
    evidence_id = str(row.get("evidence_id") or "")
    if source_kind == "x_account":
        handle = str(row.get("author_handle") or evidence_id)
        return f"account/{handle}"
    if source_kind == "media":
        return f"media/{evidence_id}"
    return evidence_id


def vector_name(row: dict[str, Any]) -> str:
    source_kind = str(row.get("source_kind") or "")
    if source_kind == "x_account":
        return "account_dense"
    if source_kind == "media":
        return "ocr_dense" if int(row.get("has_ocr") or 0) else "caption_dense"
    return "text_dense"


def embed(texts: list[str]) -> list[list[float]]:
    body = json.dumps({"model": "text", "inputs": texts, "normalize": True}).encode("utf-8")
    req = urllib.request.Request(
        LOCAL_INFERENCE_URL + "/embed",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Caller": "web-osint-qdrant-embedding-backfill",
            "X-Workload": "batch",
        },
    )
    with urllib.request.urlopen(req) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return [item["embedding"] for item in payload["data"]]


def upsert(rows: list[dict[str, Any]], vectors: list[list[float]]) -> None:
    points = []
    embedded_at = now_iso()
    for row, vector in zip(rows, vectors, strict=True):
        name = vector_name(row)
        points.append(
            {
                "id": uuid_from(point_key(row)),
                "vector": {name: vector},
                "payload": {
                    "evidence_id": row["evidence_id"],
                    "source_kind": row.get("source_kind") or "",
                    "source_project": row.get("source_project") or "",
                    "author_handle": row.get("author_handle") or "",
                    "canonical_url": row.get("canonical_url") or "",
                    "domain": row.get("domain") or "",
                    "topics": row.get("topics") or [],
                    "entities": row.get("entities") or [],
                    "has_media": bool(row.get("has_media")),
                    "posted_at_day": day_string(row.get("posted_at")),
                    "captured_at_day": day_string(row.get("captured_at")),
                    "embedding_model": "Qwen3-Embedding-8B",
                    "embedding_vector_names": [name],
                    "embedded_at": embedded_at,
                },
            }
        )

    body = json.dumps({"points": points}).encode("utf-8")
    req = urllib.request.Request(
        f"{QDRANT_URL}/collections/{QDRANT_COLLECTION}/points?wait=true",
        data=body,
        method="PUT",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as response:
        response.read()


def chunks(rows: list[dict[str, Any]], size: int):
    for idx in range(0, len(rows), size):
        yield rows[idx : idx + size]


def main() -> int:
    print(
        f"[{now_iso()}] loading ClickHouse evidence rows database={CLICKHOUSE_DATABASE} qdrant={QDRANT_COLLECTION}",
        flush=True,
    )
    rows = load_rows()
    total = len(rows)
    print(f"[{now_iso()}] rows_to_backfill={total} batch_size={BATCH_SIZE}", flush=True)
    completed = 0
    started = time.time()
    for batch in chunks(rows, max(1, BATCH_SIZE)):
        texts = [clean_text(row.get("text")) for row in batch]
        vectors = embed(texts)
        upsert(batch, vectors)
        completed += len(batch)
        elapsed = max(time.time() - started, 0.001)
        rate = completed / elapsed
        print(
            f"[{now_iso()}] backfilled={completed}/{total} rate={rate:.3f}/s last={batch[-1].get('source_kind')}:{batch[-1].get('evidence_id')}",
            flush=True,
        )
    print(f"[{now_iso()}] backfill complete rows={completed}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
