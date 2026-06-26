#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

import requests
from confluent_kafka import Consumer, KafkaError, Producer


DEFAULT_TOPICS = [
    "evidence.posts.observed.v1",
    "evidence.accounts.observed.v1",
    "evidence.media.observed.v1",
    "evidence.search.results.v1",
    "evidence.web.documents.observed.v1",
    "evidence.user.inputs.observed.v1",
]


def env(name: str, default: str) -> str:
    return os.environ.get(name, default)


REDPANDA_BROKERS = env("REDPANDA_BROKERS", env("KAFKA_BROKERS", "127.0.0.1:19092"))
REDPANDA_GROUP_ID = env("REDPANDA_GROUP_ID", env("KAFKA_GROUP_ID", "web-osint-embedding-worker-v1"))
TOPICS = [part.strip() for part in env("EMBEDDING_WORKER_TOPICS", ",".join(DEFAULT_TOPICS)).split(",") if part.strip()]
AUDIT_TOPIC = env("EMBEDDING_AUDIT_TOPIC", "osint.semantic.embedded.v1")
DEADLETTER_TOPIC = env("EMBEDDING_DEADLETTER_TOPIC", "osint.semantic.deadletter.v1")
INFERENCE_URL = env("LOCAL_INFERENCE_URL", env("QWEN_INFERENCE_URL", "http://127.0.0.1:18200")).rstrip("/")
QDRANT_URL = env("QDRANT_URL", "http://127.0.0.1:16333").rstrip("/")
QDRANT_COLLECTION = env("QDRANT_COLLECTION", "web_osint_evidence_v1")
HTTP_ADDR = env("HTTP_ADDR", "127.0.0.1:18201")
REQUEST_TIMEOUT = float(env("EMBEDDING_WORKER_REQUEST_TIMEOUT", "600"))
POLL_TIMEOUT = float(env("EMBEDDING_WORKER_POLL_TIMEOUT", "1.0"))
MAX_TEXT_CHARS = int(env("EMBEDDING_WORKER_MAX_TEXT_CHARS", "4000"))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class WorkerStats:
    started_at: str = field(default_factory=now_iso)
    consumed: int = 0
    embedded: int = 0
    skipped: int = 0
    failed: int = 0
    qdrant_upserts: int = 0
    audit_events: int = 0
    last_event: dict[str, Any] | None = None
    last_error: str | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "started_at": self.started_at,
                "consumed": self.consumed,
                "embedded": self.embedded,
                "skipped": self.skipped,
                "failed": self.failed,
                "qdrant_upserts": self.qdrant_upserts,
                "audit_events": self.audit_events,
                "last_event": self.last_event,
                "last_error": self.last_error,
                "topics": TOPICS,
                "inference_url": INFERENCE_URL,
                "qdrant_url": QDRANT_URL,
                "qdrant_collection": QDRANT_COLLECTION,
            }

    def incr(self, name: str, amount: int = 1) -> None:
        with self.lock:
            setattr(self, name, getattr(self, name) + amount)

    def event(self, value: dict[str, Any]) -> None:
        with self.lock:
            self.last_event = value

    def error(self, message: str | None) -> None:
        with self.lock:
            self.last_error = message


stats = WorkerStats()


def stable_hash(*parts: str) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def uuid_from(value: str) -> str:
    digest = stable_hash(value)
    return f"{digest[0:8]}-{digest[8:12]}-{digest[12:16]}-{digest[16:20]}-{digest[20:32]}"


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if len(text) > MAX_TEXT_CHARS:
        return text[:MAX_TEXT_CHARS]
    return text


def day_string(value: Any) -> str:
    text = clean_text(value)
    if len(text) >= 10:
        return text[:10]
    return ""


def host_of(url: Any) -> str:
    raw = clean_text(url)
    if not raw:
        return ""
    try:
        return urlparse(raw).hostname or ""
    except Exception:
        return ""


def as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    return [value]


@dataclass
class VectorInput:
    vector_name: str
    text: str


@dataclass
class EvidenceTask:
    evidence_id: str
    point_key: str
    source_kind: str
    payload: dict[str, Any]
    vector_inputs: list[VectorInput]


def task_from_message(topic: str, key: str, event: dict[str, Any]) -> EvidenceTask | None:
    source_project = clean_text(event.get("source_project"))
    captured_at = clean_text(event.get("captured_at") or event.get("searched_at"))
    common_payload = {
        "source_project": source_project,
        "captured_at_day": day_string(captured_at),
        "topics": as_list(event.get("topics")),
        "entities": as_list(event.get("entities")),
    }

    if topic == "evidence.posts.observed.v1":
        evidence_id = clean_text(event.get("post_id") or key)
        text = clean_text(event.get("text"))
        return EvidenceTask(
            evidence_id=evidence_id,
            point_key=evidence_id,
            source_kind="x_post",
            payload={
                **common_payload,
                "evidence_id": evidence_id,
                "source_kind": "x_post",
                "author_handle": clean_text(event.get("author_handle")),
                "canonical_url": clean_text(event.get("canonical_url")),
                "posted_at_day": day_string(event.get("posted_at")),
                "has_media": bool(event.get("media_ids")),
            },
            vector_inputs=[VectorInput("text_dense", text)] if text else [],
        )

    if topic == "evidence.accounts.observed.v1":
        handle = clean_text(event.get("normalized_handle") or key)
        text = clean_text(event.get("bio") or event.get("description"))
        return EvidenceTask(
            evidence_id=handle,
            point_key=f"account/{handle}",
            source_kind="x_account",
            payload={
                **common_payload,
                "evidence_id": handle,
                "source_kind": "x_account",
                "author_handle": handle,
                "canonical_url": clean_text(event.get("profile_url")),
            },
            vector_inputs=[VectorInput("account_dense", text)] if text else [],
        )

    if topic == "evidence.media.observed.v1":
        media_id = clean_text(event.get("media_id") or key)
        inputs = []
        ocr_text = clean_text(event.get("ocr_text"))
        caption = clean_text(event.get("caption"))
        if ocr_text:
            inputs.append(VectorInput("ocr_dense", ocr_text))
        if caption and caption != ocr_text:
            inputs.append(VectorInput("caption_dense", caption))
        return EvidenceTask(
            evidence_id=media_id,
            point_key=f"media/{media_id}",
            source_kind="media",
            payload={
                **common_payload,
                "evidence_id": media_id,
                "source_kind": "media",
                "canonical_url": clean_text(event.get("url")),
                "media_kind": clean_text(event.get("media_kind")),
                "has_media": True,
                "has_ocr": bool(ocr_text),
            },
            vector_inputs=inputs,
        )

    if topic == "evidence.search.results.v1":
        evidence_id = clean_text(key)
        text = clean_text(" ".join(str(part) for part in [event.get("title"), event.get("snippet")] if part))
        url = clean_text(event.get("url"))
        return EvidenceTask(
            evidence_id=evidence_id,
            point_key=evidence_id,
            source_kind="search_result",
            payload={
                **common_payload,
                "evidence_id": evidence_id,
                "source_kind": "search_result",
                "canonical_url": url,
                "domain": host_of(url),
                "query": clean_text(event.get("query")),
                "rank": event.get("rank"),
            },
            vector_inputs=[VectorInput("text_dense", text)] if text else [],
        )

    if topic == "evidence.web.documents.observed.v1":
        evidence_id = clean_text(event.get("evidence_id") or key)
        text = clean_text(event.get("text") or event.get("summary"))
        url = clean_text(event.get("canonical_url"))
        return EvidenceTask(
            evidence_id=evidence_id,
            point_key=evidence_id,
            source_kind="web_page",
            payload={
                **common_payload,
                "evidence_id": evidence_id,
                "source_kind": "web_page",
                "canonical_url": url,
                "domain": clean_text(event.get("domain")) or host_of(url),
                "has_media": bool(event.get("media_ids")),
            },
            vector_inputs=[VectorInput("text_dense", text)] if text else [],
        )

    if topic == "evidence.user.inputs.observed.v1":
        evidence_id = clean_text(event.get("evidence_id") or key)
        text = clean_text(event.get("text"))
        return EvidenceTask(
            evidence_id=evidence_id,
            point_key=evidence_id,
            source_kind="user_input",
            payload={
                **common_payload,
                "evidence_id": evidence_id,
                "source_kind": "user_input",
                "canonical_url": clean_text(event.get("canonical_url") or event.get("url")),
                "has_media": bool(event.get("attachments")),
            },
            vector_inputs=[VectorInput("text_dense", text)] if text else [],
        )

    return None


def embed_texts(texts: list[str]) -> list[list[float]]:
    # Slow model API call: do not set an HTTP timeout. Progress/state comes from
    # local-inference /healthz guardrails and /metrics, not from client retries.
    response = requests.post(
        f"{INFERENCE_URL}/embed",
        json={"model": "text", "inputs": texts, "normalize": True},
        headers={"X-Caller": "web-osint-embedding-worker"},
    )
    response.raise_for_status()
    payload = response.json()
    return [item["embedding"] for item in payload["data"]]


def upsert_qdrant(task: EvidenceTask, vectors: dict[str, list[float]]) -> None:
    body = {
        "points": [
            {
                "id": uuid_from(task.point_key),
                "vector": vectors,
                "payload": {
                    **task.payload,
                    "embedded_at": now_iso(),
                    "embedding_model": "Qwen3-Embedding-8B",
                    "embedding_vector_names": sorted(vectors.keys()),
                },
            }
        ]
    }
    response = requests.put(
        f"{QDRANT_URL}/collections/{QDRANT_COLLECTION}/points?wait=true",
        json=body,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    stats.incr("qdrant_upserts")


def publish_json(producer: Producer, topic: str, key: str, payload: dict[str, Any]) -> None:
    producer.produce(topic, key=key.encode("utf-8"), value=json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    producer.poll(0)


def handle_message(producer: Producer, topic: str, key: str, value: bytes) -> bool:
    event = json.loads(value)
    task = task_from_message(topic, key, event)
    if task is None or not task.vector_inputs:
        stats.incr("skipped")
        return True

    vectors = embed_texts([item.text for item in task.vector_inputs])
    vector_map = {item.vector_name: vectors[idx] for idx, item in enumerate(task.vector_inputs)}
    upsert_qdrant(task, vector_map)
    audit = {
        "schema_version": "v1",
        "evidence_id": task.evidence_id,
        "point_id": uuid_from(task.point_key),
        "source_kind": task.source_kind,
        "vector_names": sorted(vector_map.keys()),
        "embedding_model": "Qwen3-Embedding-8B",
        "embedding_dimension": len(next(iter(vector_map.values()))) if vector_map else 0,
        "embedded_at": now_iso(),
    }
    publish_json(producer, AUDIT_TOPIC, task.evidence_id, audit)
    producer.flush(10)
    stats.incr("embedded")
    stats.incr("audit_events")
    stats.event(audit)
    return True


class StatsHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._write({"ok": True})
            return
        if self.path == "/stats":
            self._write(stats.snapshot())
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def _write(self, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def serve_http() -> None:
    host, port = HTTP_ADDR.rsplit(":", 1)
    server = ThreadingHTTPServer((host, int(port)), StatsHandler)
    server.serve_forever()


def publish_deadletter(producer: Producer, topic: str, key: str, message: str, raw_value: bytes) -> None:
    payload = {
        "schema_version": "v1",
        "source_topic": topic,
        "key": key,
        "error": message,
        "created_at": now_iso(),
        "raw": raw_value.decode("utf-8", errors="replace")[:10000],
    }
    publish_json(producer, DEADLETTER_TOPIC, key or stable_hash(payload["raw"])[:24], payload)
    producer.flush(10)


def main() -> None:
    threading.Thread(target=serve_http, daemon=True).start()
    consumer = Consumer(
        {
            "bootstrap.servers": REDPANDA_BROKERS,
            "group.id": REDPANDA_GROUP_ID,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
        }
    )
    producer = Producer({"bootstrap.servers": REDPANDA_BROKERS})
    consumer.subscribe(TOPICS)
    print(f"[{now_iso()}] embedding worker starting topics={','.join(TOPICS)} brokers={REDPANDA_BROKERS}", flush=True)
    try:
        while True:
            msg = consumer.poll(POLL_TIMEOUT)
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() != KafkaError._PARTITION_EOF:
                    stats.incr("failed")
                    stats.error(str(msg.error()))
                    print(f"[{now_iso()}] Redpanda consumer error: {msg.error()}", flush=True)
                continue
            stats.incr("consumed")
            topic = msg.topic()
            key = (msg.key() or b"").decode("utf-8", errors="replace")
            try:
                handle_message(producer, topic, key, msg.value())
                consumer.commit(msg)
                stats.error(None)
            except Exception as exc:
                stats.incr("failed")
                message = str(exc)
                stats.error(message)
                print(f"[{now_iso()}] failed topic={topic} key={key}: {message}", flush=True)
                try:
                    publish_deadletter(producer, topic, key, message, msg.value())
                    consumer.commit(msg)
                except Exception as deadletter_exc:
                    stats.error(f"{message}; deadletter failed: {deadletter_exc}")
                    time.sleep(5)
    finally:
        consumer.close()
        producer.flush(10)


if __name__ == "__main__":
    main()
