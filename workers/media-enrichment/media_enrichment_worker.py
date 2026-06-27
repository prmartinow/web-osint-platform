#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import json
import mimetypes
import os
import statistics
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import requests
from confluent_kafka import Consumer, KafkaError, Producer
from PIL import Image, ImageDraw, ImageFont

SCRIPT_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from osint_paths import StorageRootError, ensure_dir, evidence_data_root, require_child_path  # noqa: E402


PRODUCER_NAME = "media-enrichment-worker"
PRODUCER_VERSION = "v1"
CAPTURE_TOPIC = "evidence.capture.events.v1"
ENRICHMENT_TOPIC = "osint.media.enrichment.requested.v1"
OCR_REQUEST_TOPIC = "osint.media.ocr.requested.v1"
OCR_COMPLETED_TOPIC = "osint.media.ocr.completed.v1"
OCR_FAILED_TOPIC = "osint.media.ocr.failed.v1"
VL_REQUEST_TOPIC = "osint.media.vl_embedding.requested.v1"
VL_COMPLETED_TOPIC = "osint.media.vl_embedding.completed.v1"
VL_FAILED_TOPIC = "osint.media.vl_embedding.failed.v1"
VECTOR_NAME = "vl_image_dense"


def env(name: str, default: str) -> str:
    return os.environ.get(name, default)


DATA_ROOT = evidence_data_root()
REDPANDA_BROKERS = env("REDPANDA_BROKERS", env("KAFKA_BROKERS", "127.0.0.1:19092"))
CLICKHOUSE_URL = env("CLICKHOUSE_URL", "http://127.0.0.1:18123").rstrip("/")
CLICKHOUSE_DATABASE = env("CLICKHOUSE_DATABASE", "web_osint")
CLICKHOUSE_USER = env("CLICKHOUSE_USER", "web_osint")
CLICKHOUSE_PASSWORD = env("CLICKHOUSE_PASSWORD", "")
LOCAL_INFERENCE_URL = env("LOCAL_INFERENCE_URL", "http://127.0.0.1:18200").rstrip("/")
QDRANT_URL = env("QDRANT_URL", "http://127.0.0.1:16333").rstrip("/")
QDRANT_COLLECTION = env("QDRANT_COLLECTION", "web_osint_evidence_v1")

ROUTER_INTERVAL = float(env("MEDIA_ROUTER_SCAN_INTERVAL_SECONDS", "60"))
ROUTER_BATCH_SIZE = int(env("MEDIA_ROUTER_BATCH_SIZE", "100"))
MAX_IMAGE_BYTES = int(env("MEDIA_MAX_IMAGE_BYTES", str(25 * 1024 * 1024)))
MAX_IMAGE_PIXELS = int(env("MEDIA_MAX_IMAGE_PIXELS", str(40_000_000)))
VL_MAX_SIDE = int(env("MEDIA_VL_MAX_SIDE", "1600"))
REQUEST_TIMEOUT = float(env("MEDIA_WORKER_REQUEST_TIMEOUT", "600"))
CONSUMER_MAX_POLL_INTERVAL_MS = int(env("MEDIA_CONSUMER_MAX_POLL_INTERVAL_MS", "1800000"))
OCR_SELFTEST_TOKEN = "SELFTESTALPHA123"
OCR_SELFTEST_EXPECTED = "TESTALPHA123"

DERIVED_ROOT = ensure_dir(DATA_ROOT / "derived")
OCR_ROOT = ensure_dir(DERIVED_ROOT / "ocr")
VL_ROOT = ensure_dir(DERIVED_ROOT / "vl")
METRICS_ROOT = ensure_dir(DATA_ROOT / "metrics")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def ch_time(value: str | None = None) -> str:
    return (value or now_iso()).replace("T", " ").replace("Z", "")


def stable_hash(*parts: str) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(str(part).encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()


def uuid_from(value: str) -> str:
    digest = stable_hash(value)
    return f"{digest[0:8]}-{digest[8:12]}-{digest[12:16]}-{digest[16:20]}-{digest[20:32]}"


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def sql_string(value: Any) -> str:
    text = str(value)
    return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"


def safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def request_json(url: str, *, method: str = "GET", body: Any | None = None, timeout: float = 30) -> Any:
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:2000]
        raise RuntimeError(f"{method} {url} HTTP {exc.code}: {detail}") from exc


def clickhouse_request(query: str, *, json_format: bool = True, body: bytes | None = None, timeout: float = 60) -> Any:
    params = {
        "database": CLICKHOUSE_DATABASE,
        "query": query,
        "date_time_input_format": "best_effort",
        "date_time_output_format": "iso",
    }
    if json_format:
        params["default_format"] = "JSON"
    url = CLICKHOUSE_URL + "/?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, data=body, method="POST")
    if CLICKHOUSE_PASSWORD:
        token = base64.b64encode(f"{CLICKHOUSE_USER}:{CLICKHOUSE_PASSWORD}".encode("utf-8")).decode("ascii")
        request.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            if not raw:
                return {}
            text = raw.decode("utf-8")
            return json.loads(text) if json_format else text
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:2000]
        raise RuntimeError(f"ClickHouse HTTP {exc.code}: {detail}") from exc


def ch_data(query: str) -> list[dict[str, Any]]:
    return clickhouse_request(query).get("data", [])


def ch_execute(query: str) -> None:
    clickhouse_request(query, json_format=False)


def ch_insert(table: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    body = "\n".join(compact_json(row) for row in rows).encode("utf-8")
    clickhouse_request(f"INSERT INTO {table} FORMAT JSONEachRow", json_format=False, body=body, timeout=120)


def ensure_media_tables() -> None:
    ch_execute(
        """
        CREATE TABLE IF NOT EXISTS media_ocr_results
        (
            ocr_id String,
            evidence_id String,
            source_artifact_id String,
            source_sha256 String,
            source_kind LowCardinality(String),
            artifact_role LowCardinality(String),
            engine LowCardinality(String),
            engine_version String,
            params_hash String,
            status LowCardinality(String),
            error_class LowCardinality(String),
            error_message String,
            runtime_json String,
            json_artifact_path String,
            text_artifact_path String,
            text_chars UInt64,
            block_count UInt64,
            mean_confidence Float32,
            min_confidence Float32,
            image_width UInt32,
            image_height UInt32,
            page_no Nullable(UInt32),
            created_at DateTime64(3, 'UTC')
        )
        ENGINE = MergeTree
        PARTITION BY toYYYYMM(created_at)
        ORDER BY (source_sha256, engine, params_hash, created_at, ocr_id)
        """
    )
    ch_execute("ALTER TABLE media_ocr_results ADD COLUMN IF NOT EXISTS runtime_json String AFTER error_message")
    ch_execute(
        """
        CREATE TABLE IF NOT EXISTS media_vl_embeddings
        (
            vl_embedding_id String,
            evidence_id String,
            source_artifact_id String,
            source_sha256 String,
            model LowCardinality(String),
            model_version String,
            params_hash String,
            qdrant_collection String,
            qdrant_point_id String,
            vector_name LowCardinality(String),
            status LowCardinality(String),
            error_class LowCardinality(String),
            error_message String,
            image_width UInt32,
            image_height UInt32,
            created_at DateTime64(3, 'UTC')
        )
        ENGINE = MergeTree
        PARTITION BY toYYYYMM(created_at)
        ORDER BY (source_sha256, model, params_hash, created_at, vl_embedding_id)
        """
    )


@dataclass
class WorkerStats:
    role: str
    started_at: str = field(default_factory=now_iso)
    scanned: int = 0
    queued_ocr: int = 0
    queued_vl: int = 0
    consumed: int = 0
    completed: int = 0
    failed: int = 0
    skipped: int = 0
    last_event: dict[str, Any] | None = None
    last_error: str = ""
    lock: threading.Lock = field(default_factory=threading.Lock)

    def incr(self, name: str, amount: int = 1) -> None:
        with self.lock:
            setattr(self, name, getattr(self, name) + amount)

    def event(self, payload: dict[str, Any]) -> None:
        with self.lock:
            self.last_event = payload

    def error(self, message: str) -> None:
        with self.lock:
            self.last_error = message

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            payload = {
                "ok": True,
                "role": self.role,
                "started_at": self.started_at,
                "scanned": self.scanned,
                "queued_ocr": self.queued_ocr,
                "queued_vl": self.queued_vl,
                "consumed": self.consumed,
                "completed": self.completed,
                "failed": self.failed,
                "skipped": self.skipped,
                "last_event": self.last_event,
                "last_error": self.last_error,
                "data_root": str(DATA_ROOT),
                "clickhouse_database": CLICKHOUSE_DATABASE,
                "qdrant_collection": QDRANT_COLLECTION,
            }
            if self.role == "ocr":
                payload["runtime"] = ocr_runtime_info()
            return payload


stats = WorkerStats(role=env("MEDIA_WORKER_ROLE", "unknown"))


class StatsHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path not in {"/healthz", "/stats"}:
            self.send_response(404)
            self.end_headers()
            return
        payload = stats.snapshot()
        raw = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, fmt: str, *args: Any) -> None:
        return


def serve_http(addr: str) -> None:
    host, port = addr.rsplit(":", 1)
    ThreadingHTTPServer((host, int(port)), StatsHandler).serve_forever()


def publish_json(producer: Producer, topic: str, key: str, payload: dict[str, Any]) -> None:
    producer.produce(topic, key=key.encode("utf-8"), value=compact_json(payload).encode("utf-8"))
    producer.poll(0)


def parse_raw_json(row: dict[str, Any]) -> dict[str, Any]:
    raw_text = row.get("raw_json") or row.get("raw") or "{}"
    if isinstance(raw_text, dict):
        return raw_text
    try:
        return json.loads(raw_text)
    except Exception:
        return {}


def extract_media_path(row: dict[str, Any], raw: dict[str, Any]) -> Path | None:
    nested = raw.get("raw") if isinstance(raw.get("raw"), dict) else {}
    for key in ("local_path", "storage_path", "path", "artifact_path"):
        value = raw.get(key) or nested.get(key)
        if value:
            path = Path(str(value)).expanduser()
            return path
    return None


def media_kind(raw: dict[str, Any]) -> str:
    nested = raw.get("raw") if isinstance(raw.get("raw"), dict) else {}
    return safe_text(raw.get("media_kind") or raw.get("kind") or nested.get("media_kind") or nested.get("kind") or "image")


def media_caption(raw: dict[str, Any], row: dict[str, Any]) -> str:
    nested = raw.get("raw") if isinstance(raw.get("raw"), dict) else {}
    return safe_text(raw.get("caption") or nested.get("caption") or row.get("title") or row.get("text"))


def media_topics(raw: dict[str, Any]) -> list[str]:
    nested = raw.get("raw") if isinstance(raw.get("raw"), dict) else {}
    value = raw.get("topics") or nested.get("topics") or []
    return value if isinstance(value, list) else []


def image_info(path: Path) -> dict[str, Any]:
    stat = path.stat()
    if stat.st_size > MAX_IMAGE_BYTES:
        raise ValueError(f"image is {stat.st_size} bytes; max is {MAX_IMAGE_BYTES}")
    with Image.open(path) as img:
        width, height = img.size
        fmt = img.format or ""
    if width * height > MAX_IMAGE_PIXELS:
        raise ValueError(f"image is {width}x{height} pixels; max pixels is {MAX_IMAGE_PIXELS}")
    return {"bytes": stat.st_size, "width": width, "height": height, "format": fmt}


def build_media_request(row: dict[str, Any]) -> dict[str, Any] | None:
    raw = parse_raw_json(row)
    path = extract_media_path(row, raw)
    if path is None:
        return None
    path = require_child_path(DATA_ROOT, path)
    if not path.exists() or not path.is_file():
        return None
    info = image_info(path)
    nested = raw.get("raw") if isinstance(raw.get("raw"), dict) else {}
    sha = safe_text(raw.get("sha256") or nested.get("sha256")) or sha256_file(path)
    mime = safe_text(raw.get("mime_type") or nested.get("mime_type")) or mimetypes.guess_type(path.name)[0] or "image/png"
    evidence_id = safe_text(row.get("evidence_id"))
    event_id = "media_req_" + stable_hash(evidence_id, sha, str(path))[:24]
    role = media_kind(raw)
    return {
        "schema_version": "v1",
        "event_id": event_id,
        "trace_id": event_id,
        "evidence_id": evidence_id,
        "artifact_id": safe_text(raw.get("media_id") or nested.get("media_id") or evidence_id),
        "artifact_sha256": sha,
        "source_kind": safe_text(row.get("source_kind") or "media"),
        "source_project": safe_text(raw.get("source_project") or row.get("source_project")),
        "capture_method": safe_text(raw.get("capture_method") or row.get("capture_method")),
        "collector_run_id": safe_text(raw.get("collector_run_id") or row.get("collector_run_id")),
        "artifact_role": "screenshot_full_page" if "screenshot" in role.lower() else role or "image",
        "media_type": mime,
        "storage_path": str(path),
        "source_uri": safe_text(row.get("canonical_url") or raw.get("url") or nested.get("url")),
        "caption": media_caption(raw, row),
        "topics": media_topics(raw),
        "width": info["width"],
        "height": info["height"],
        "byte_size": info["bytes"],
        "producer_name": PRODUCER_NAME,
        "producer_version": PRODUCER_VERSION,
        "params_hash": media_params_hash(),
        "requested_at": now_iso(),
    }


def media_params_hash() -> str:
    return stable_hash(
        "media-v1",
        f"max_bytes={MAX_IMAGE_BYTES}",
        f"max_pixels={MAX_IMAGE_PIXELS}",
        f"vl_max_side={VL_MAX_SIDE}",
    )[:16]


def completed_shas(table: str) -> set[str]:
    try:
        rows = ch_data(f"SELECT DISTINCT source_sha256 FROM {table} WHERE status = 'completed'")
        return {safe_text(row.get("source_sha256")) for row in rows if row.get("source_sha256")}
    except Exception:
        return set()


def router_scan_once(producer: Producer, queued_ocr: set[str], queued_vl: set[str]) -> None:
    ensure_media_tables()
    ocr_done = completed_shas("media_ocr_results")
    vl_done = completed_shas("media_vl_embeddings")
    rows = ch_data(
        f"""
        SELECT evidence_id, source_kind, source_project, capture_method, collector_run_id,
               canonical_url, title, text, raw_json, ingested_at
        FROM evidence_events
        WHERE source_kind = 'media'
        ORDER BY ingested_at DESC
        LIMIT {ROUTER_BATCH_SIZE}
        """
    )
    stats.incr("scanned", len(rows))
    for row in rows:
        try:
            request = build_media_request(row)
        except Exception as exc:
            stats.incr("skipped")
            stats.error(str(exc))
            continue
        if not request:
            stats.incr("skipped")
            continue
        sha = request["artifact_sha256"]
        key = request["artifact_id"]
        publish_json(producer, ENRICHMENT_TOPIC, key, request)
        if sha not in ocr_done and sha not in queued_ocr:
            publish_json(producer, OCR_REQUEST_TOPIC, key, request)
            queued_ocr.add(sha)
            stats.incr("queued_ocr")
        if sha not in vl_done and sha not in queued_vl:
            publish_json(producer, VL_REQUEST_TOPIC, key, request)
            queued_vl.add(sha)
            stats.incr("queued_vl")
        stats.event({"artifact_id": key, "sha256": sha, "path": request["storage_path"]})
    producer.flush(15)


def run_router() -> None:
    stats.role = "router"
    threading.Thread(target=serve_http, args=(env("MEDIA_ROUTER_HTTP_ADDR", "127.0.0.1:18211"),), daemon=True).start()
    producer = Producer({"bootstrap.servers": REDPANDA_BROKERS})
    queued_ocr: set[str] = set()
    queued_vl: set[str] = set()
    print(f"[{now_iso()}] media router starting data_root={DATA_ROOT} db={CLICKHOUSE_DATABASE}", flush=True)
    while True:
        try:
            router_scan_once(producer, queued_ocr, queued_vl)
            stats.error("")
        except Exception as exc:
            stats.incr("failed")
            stats.error(str(exc))
            print(f"[{now_iso()}] media router scan failed: {exc}", flush=True)
        time.sleep(ROUTER_INTERVAL)


def normalized_ocr_text(value: str) -> str:
    return "".join(ch for ch in value.upper() if ch.isalnum())


def ocr_runtime_info() -> dict[str, Any]:
    info: dict[str, Any] = {
        "engine_owner": "local-inference",
        "local_inference_url": LOCAL_INFERENCE_URL,
        "python_version": sys.version.split()[0],
    }
    with contextlib.suppress(Exception):
        health = request_json(f"{LOCAL_INFERENCE_URL}/healthz", timeout=3)
        info["local_inference_ok"] = bool(health.get("ok"))
        info["paddleocr_runtime"] = health.get("paddleocr_runtime") or {}
        info["paddleocr_guardrail"] = (health.get("guardrails") or {}).get("paddleocr") or {}
    return info


def call_media_ocr(path: Path) -> dict[str, Any]:
    # Slow model API call: do not set an HTTP timeout. Progress/state comes from
    # local-inference /healthz guardrails and /metrics, not from client retries.
    response = requests.post(
        f"{LOCAL_INFERENCE_URL}/media/ocr",
        json={"image_path": str(path), "lang": env("MEDIA_OCR_LANG", "en")},
        headers={"X-Caller": "web-osint-media-ocr-worker"},
    )
    if response.status_code >= 400:
        raise RuntimeError(f"local inference media OCR HTTP {response.status_code}: {response.text[:2000]}")
    return response.json()


def run_ocr_startup_selftest() -> None:
    test_path = ensure_dir(DATA_ROOT / "tmp") / "ocr-startup-selftest.png"
    image = Image.new("RGB", (1200, 260), "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 48)
    except Exception:
        font = ImageFont.load_default()
    draw.text((40, 88), OCR_SELFTEST_TOKEN, fill="black", font=font)
    image.save(test_path)
    result = call_media_ocr(test_path)
    blocks = result.get("blocks") or []
    text = safe_text(result.get("text")) or "\n".join(safe_text(block.get("text")) for block in blocks)
    if OCR_SELFTEST_EXPECTED not in normalized_ocr_text(text):
        raise RuntimeError(f"OCR startup self-test failed; expected {OCR_SELFTEST_EXPECTED}, got {text[:200]!r}")
    print(
        f"[{now_iso()}] OCR startup self-test passed blocks={len(blocks)} runtime={compact_json(ocr_runtime_info())}",
        flush=True,
    )


def ocr_completed_for(sha: str, params_hash: str) -> bool:
    rows = ch_data(
        f"""
        SELECT count() AS rows
        FROM media_ocr_results
        WHERE source_sha256 = {sql_string(sha)}
          AND params_hash = {sql_string(params_hash)}
          AND status = 'completed'
        """
    )
    return bool(rows and int(rows[0].get("rows") or 0) > 0)


def insert_ocr_row(event: dict[str, Any], status: str, **values: Any) -> None:
    ch_insert(
        "media_ocr_results",
        [
            {
                "ocr_id": values.get("ocr_id", ""),
                "evidence_id": event.get("evidence_id", ""),
                "source_artifact_id": event.get("artifact_id", ""),
                "source_sha256": event.get("artifact_sha256", ""),
                "source_kind": event.get("source_kind", ""),
                "artifact_role": event.get("artifact_role", ""),
                "engine": values.get("engine", "paddleocr"),
                "engine_version": values.get("engine_version", ""),
                "params_hash": event.get("params_hash", ""),
                "status": status,
                "error_class": values.get("error_class", ""),
                "error_message": values.get("error_message", ""),
                "runtime_json": compact_json(values.get("runtime") or ocr_runtime_info()),
                "json_artifact_path": values.get("json_artifact_path", ""),
                "text_artifact_path": values.get("text_artifact_path", ""),
                "text_chars": len(values.get("text", "")),
                "block_count": len(values.get("blocks", [])),
                "mean_confidence": float(values.get("mean_confidence", 0.0)),
                "min_confidence": float(values.get("min_confidence", 0.0)),
                "image_width": int(event.get("width") or 0),
                "image_height": int(event.get("height") or 0),
                "page_no": values.get("page_no"),
                "created_at": ch_time(),
            }
        ],
    )


def publish_ocr_capture(producer: Producer, event: dict[str, Any], ocr_id: str, text: str, json_path: Path, text_path: Path) -> None:
    captured_at = now_iso()
    capture = {
        "schema_version": "v1",
        "collector_run_id": f"media_ocr_{ocr_id}",
        "event_index": 0,
        "source_project": event.get("source_project") or "media-enrichment",
        "capture_method": "media_ocr_worker",
        "captured_at": captured_at,
        "media": [
            {
                "media_id": event.get("artifact_id") or event.get("evidence_id"),
                "media_kind": event.get("artifact_role") or "image",
                "url": event.get("source_uri") or "",
                "local_path": event.get("storage_path") or "",
                "sha256": event.get("artifact_sha256") or "",
                "ocr_text": text,
                "caption": event.get("caption") or "",
                "topics": event.get("topics") or [],
                "ocr_artifact_paths": [str(json_path), str(text_path)],
                "producer": {"name": PRODUCER_NAME, "version": PRODUCER_VERSION},
            }
        ],
        "context": {"derived_from_evidence_id": event.get("evidence_id"), "ocr_id": ocr_id},
    }
    publish_json(producer, CAPTURE_TOPIC, str(event.get("artifact_id") or ocr_id), capture)


def handle_ocr_event(producer: Producer, event: dict[str, Any]) -> None:
    path = require_child_path(DATA_ROOT, safe_text(event.get("storage_path")))
    image_info(path)
    sha = safe_text(event.get("artifact_sha256")) or sha256_file(path)
    event["artifact_sha256"] = sha
    params_hash = safe_text(event.get("params_hash")) or media_params_hash()
    event["params_hash"] = params_hash
    if ocr_completed_for(sha, params_hash):
        stats.incr("skipped")
        return
    ocr_id = "ocr_" + stable_hash(sha, "paddleocr", params_hash)[:24]
    out_dir = ensure_dir(OCR_ROOT / sha[:2])
    json_path = out_dir / f"{ocr_id}.json"
    text_path = out_dir / f"{ocr_id}.txt"
    ocr_result = call_media_ocr(path)
    blocks = ocr_result.get("blocks") or []
    engine_module = safe_text(ocr_result.get("engine_module"))
    text = safe_text(ocr_result.get("text")) or "\n".join(safe_text(block.get("text")) for block in blocks)
    confidences = [float(block.get("confidence") or 0.0) for block in blocks]
    mean_conf = float(ocr_result.get("mean_confidence") or (statistics.fmean(confidences) if confidences else 0.0))
    min_conf = float(ocr_result.get("min_confidence") or (min(confidences) if confidences else 0.0))
    engine_version = safe_text(ocr_result.get("engine_version"))
    runtime = ocr_result.get("runtime") or ocr_runtime_info()
    payload = {
        "ocr_id": ocr_id,
        "source_event": event,
        "text": text,
        "blocks": blocks,
        "engine": "paddleocr",
        "engine_module": engine_module,
        "engine_version": engine_version,
        "runtime": runtime,
        "params_hash": params_hash,
        "created_at": now_iso(),
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    text_path.write_text(text, encoding="utf-8")
    insert_ocr_row(
        event,
        "completed",
        ocr_id=ocr_id,
        engine_version=engine_version,
        json_artifact_path=str(json_path),
        text_artifact_path=str(text_path),
        text=text,
        runtime=payload["runtime"],
        blocks=blocks,
        mean_confidence=mean_conf,
        min_confidence=min_conf,
    )
    completed = {
        **event,
        "ocr_id": ocr_id,
        "text_artifact_path": str(text_path),
        "json_artifact_path": str(json_path),
        "text_chars": len(text),
        "block_count": len(blocks),
        "mean_confidence": mean_conf,
        "min_confidence": min_conf,
        "completed_at": now_iso(),
    }
    publish_json(producer, OCR_COMPLETED_TOPIC, safe_text(event.get("artifact_id") or ocr_id), completed)
    publish_ocr_capture(producer, event, ocr_id, text, json_path, text_path)
    stats.incr("completed")
    stats.event(completed)


def vl_completed_for(sha: str, params_hash: str) -> bool:
    rows = ch_data(
        f"""
        SELECT count() AS rows
        FROM media_vl_embeddings
        WHERE source_sha256 = {sql_string(sha)}
          AND params_hash = {sql_string(params_hash)}
          AND status = 'completed'
        """
    )
    return bool(rows and int(rows[0].get("rows") or 0) > 0)


def prepare_vl_image(path: Path, sha: str) -> Path:
    with Image.open(path) as image:
        width, height = image.size
        if max(width, height) <= VL_MAX_SIDE:
            return path
        image.thumbnail((VL_MAX_SIDE, VL_MAX_SIDE))
        out_dir = ensure_dir(VL_ROOT / sha[:2])
        out_path = out_dir / f"{sha[:24]}_vl_{VL_MAX_SIDE}.jpg"
        image.convert("RGB").save(out_path, quality=92)
        return out_path


def insert_vl_row(event: dict[str, Any], status: str, **values: Any) -> None:
    ch_insert(
        "media_vl_embeddings",
        [
            {
                "vl_embedding_id": values.get("vl_embedding_id", ""),
                "evidence_id": event.get("evidence_id", ""),
                "source_artifact_id": event.get("artifact_id", ""),
                "source_sha256": event.get("artifact_sha256", ""),
                "model": "Qwen3-VL-Embedding-8B",
                "model_version": values.get("model_version", "Qwen3-VL-Embedding-8B"),
                "params_hash": event.get("params_hash", ""),
                "qdrant_collection": QDRANT_COLLECTION,
                "qdrant_point_id": values.get("qdrant_point_id", ""),
                "vector_name": VECTOR_NAME,
                "status": status,
                "error_class": values.get("error_class", ""),
                "error_message": values.get("error_message", ""),
                "image_width": int(event.get("width") or 0),
                "image_height": int(event.get("height") or 0),
                "created_at": ch_time(),
            }
        ],
    )


def embed_vl_image(path: Path) -> dict[str, Any]:
    # Slow model API call: do not set an HTTP timeout. Progress/state comes from
    # local-inference /healthz guardrails and /metrics, not from client retries.
    response = requests.post(
        f"{LOCAL_INFERENCE_URL}/embed",
        json={"model": "vl", "inputs": [{"image": str(path)}], "normalize": True, "batch_size": 1},
        headers={"X-Caller": "web-osint-media-vl-worker"},
    )
    response.raise_for_status()
    data = response.json()
    rows = data.get("data") or []
    if not rows:
        raise RuntimeError("Qwen VL response contained no vectors")
    return {"vector": rows[0]["embedding"], "model": data.get("model", "Qwen3-VL-Embedding-8B"), "dimension": data.get("dimension", 0)}


def upsert_vl_qdrant(event: dict[str, Any], vector: list[float], vl_embedding_id: str) -> str:
    point_id = uuid_from("vl:" + vl_embedding_id)
    payload = {
        "point_kind": "media_vl_embedding",
        "embedding_model": "Qwen3-VL-Embedding-8B",
        "embedding_vector_names": [VECTOR_NAME],
        "evidence_id": event.get("evidence_id"),
        "artifact_id": event.get("artifact_id"),
        "source_kind": event.get("source_kind"),
        "source_project": event.get("source_project"),
        "artifact_role": event.get("artifact_role"),
        "source_uri": event.get("source_uri") or "",
        "artifact_uri": event.get("storage_path") or "",
        "canonical_url": event.get("source_uri") or "",
        "artifact_sha256": event.get("artifact_sha256"),
        "sha256": event.get("artifact_sha256"),
        "media_type": event.get("media_type"),
        "width": int(event.get("width") or 0),
        "height": int(event.get("height") or 0),
        "has_media": True,
        "has_ocr": bool(event.get("ocr_id")),
        "ocr_id": event.get("ocr_id") or "",
        "ocr_text_chars": int(event.get("ocr_text_chars") or event.get("text_chars") or 0),
        "topics": event.get("topics") or [],
        "author_handle": event.get("author_handle") or "",
        "domain": event.get("domain") or "",
        "created_at": now_iso(),
        "captured_at_day": now_iso()[:10],
        "producer_name": PRODUCER_NAME,
        "producer_version": PRODUCER_VERSION,
    }
    body = {"points": [{"id": point_id, "vector": {VECTOR_NAME: vector}, "payload": payload}]}
    response = requests.put(
        f"{QDRANT_URL}/collections/{QDRANT_COLLECTION}/points?wait=true",
        json=body,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return point_id


def handle_vl_event(producer: Producer, event: dict[str, Any]) -> None:
    path = require_child_path(DATA_ROOT, safe_text(event.get("storage_path")))
    image_info(path)
    sha = safe_text(event.get("artifact_sha256")) or sha256_file(path)
    event["artifact_sha256"] = sha
    params_hash = safe_text(event.get("params_hash")) or media_params_hash()
    event["params_hash"] = params_hash
    if vl_completed_for(sha, params_hash):
        stats.incr("skipped")
        return
    vl_embedding_id = "vl_" + stable_hash(sha, "qwen3-vl", params_hash)[:24]
    prepared = prepare_vl_image(path, sha)
    embedding = embed_vl_image(prepared)
    point_id = upsert_vl_qdrant(event, embedding["vector"], vl_embedding_id)
    manifest_path = ensure_dir(VL_ROOT / sha[:2]) / f"{vl_embedding_id}.json"
    manifest = {
        "vl_embedding_id": vl_embedding_id,
        "source_event": event,
        "prepared_image_path": str(prepared),
        "qdrant_collection": QDRANT_COLLECTION,
        "qdrant_point_id": point_id,
        "vector_name": VECTOR_NAME,
        "model": embedding["model"],
        "dimension": embedding["dimension"],
        "created_at": now_iso(),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    insert_vl_row(
        event,
        "completed",
        vl_embedding_id=vl_embedding_id,
        qdrant_point_id=point_id,
        model_version=embedding["model"],
    )
    completed = {
        **event,
        "vl_embedding_id": vl_embedding_id,
        "qdrant_collection": QDRANT_COLLECTION,
        "qdrant_point_id": point_id,
        "vector_name": VECTOR_NAME,
        "manifest_path": str(manifest_path),
        "completed_at": now_iso(),
    }
    publish_json(producer, VL_COMPLETED_TOPIC, safe_text(event.get("artifact_id") or vl_embedding_id), completed)
    stats.incr("completed")
    stats.event(completed)


def publish_failure(producer: Producer, topic: str, event: dict[str, Any], exc: Exception) -> None:
    failed = {
        **event,
        "status": "failed",
        "error_class": exc.__class__.__name__,
        "error_message": str(exc)[:2000],
        "failed_at": now_iso(),
    }
    publish_json(producer, topic, safe_text(event.get("artifact_id") or stable_hash(str(event))[:16]), failed)
    if topic == OCR_FAILED_TOPIC:
        with contextlib.suppress(Exception):
            insert_ocr_row(event, "failed", error_class=exc.__class__.__name__, error_message=str(exc)[:2000])
    if topic == VL_FAILED_TOPIC:
        with contextlib.suppress(Exception):
            insert_vl_row(event, "failed", error_class=exc.__class__.__name__, error_message=str(exc)[:2000])


def run_consumer(role: str, topic: str, group_id: str, http_addr: str) -> None:
    stats.role = role
    ensure_media_tables()
    if role == "ocr":
        run_ocr_startup_selftest()
    threading.Thread(target=serve_http, args=(http_addr,), daemon=True).start()
    producer = Producer({"bootstrap.servers": REDPANDA_BROKERS})
    consumer = Consumer(
        {
            "bootstrap.servers": REDPANDA_BROKERS,
            "group.id": group_id,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
            "max.poll.interval.ms": CONSUMER_MAX_POLL_INTERVAL_MS,
        }
    )
    consumer.subscribe([topic])
    print(f"[{now_iso()}] media {role} worker starting topic={topic} data_root={DATA_ROOT}", flush=True)
    try:
        while True:
            msg = consumer.poll(1.0)
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() != KafkaError._PARTITION_EOF:
                    stats.incr("failed")
                    stats.error(str(msg.error()))
                continue
            stats.incr("consumed")
            try:
                event = json.loads(msg.value().decode("utf-8"))
                if role == "ocr":
                    handle_ocr_event(producer, event)
                else:
                    handle_vl_event(producer, event)
                consumer.commit(msg)
                stats.error("")
            except Exception as exc:
                stats.incr("failed")
                stats.error(str(exc))
                print(f"[{now_iso()}] media {role} failed key={(msg.key() or b'').decode(errors='replace')}: {exc}", flush=True)
                with contextlib.suppress(Exception):
                    event = json.loads(msg.value().decode("utf-8"))
                    publish_failure(producer, OCR_FAILED_TOPIC if role == "ocr" else VL_FAILED_TOPIC, event, exc)
                    producer.flush(10)
                    consumer.commit(msg)
    finally:
        consumer.close()
        producer.flush(10)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Web OSINT media enrichment worker.")
    parser.add_argument("role", choices=["router", "ocr", "vl"])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.role == "router":
            run_router()
        elif args.role == "ocr":
            run_consumer(
                "ocr",
                OCR_REQUEST_TOPIC,
                env("MEDIA_OCR_GROUP_ID", "web-osint-media-ocr-worker-v1"),
                env("MEDIA_OCR_HTTP_ADDR", "127.0.0.1:18212"),
            )
        elif args.role == "vl":
            run_consumer(
                "vl",
                VL_REQUEST_TOPIC,
                env("MEDIA_VL_GROUP_ID", "web-osint-media-vl-worker-v1"),
                env("MEDIA_VL_HTTP_ADDR", "127.0.0.1:18213"),
            )
    except StorageRootError as exc:
        print(f"[{now_iso()}] unsafe storage root: {exc}", file=sys.stderr, flush=True)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
