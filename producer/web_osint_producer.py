#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_OUTBOX_ROOT = os.environ.get("WEB_OSINT_OUTBOX_ROOT", "")
if not DEFAULT_OUTBOX_ROOT and os.environ.get("WEB_OSINT_DATA_ROOT"):
    DEFAULT_OUTBOX_ROOT = str(Path(os.environ["WEB_OSINT_DATA_ROOT"]) / "outbox")
DEFAULT_PANDAPROXY = (
    os.environ.get("PANDAPROXY_URL")
    or os.environ.get("REDPANDA_PROXY_URL")
    or os.environ.get("WEB_OSINT_PANDAPROXY", "")
)


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def infer_key(topic: str, value: dict[str, Any]) -> str:
    if topic == "evidence.capture.events.v1":
        return f"{value.get('collector_run_id', 'unknown')}:{value.get('event_index', 0)}"
    if topic == "evidence.posts.observed.v1":
        return f"{value.get('post_id', 'unknown')}:{value.get('observation_id', sha256_text(stable_json(value))[:16])}"
    if topic == "evidence.accounts.observed.v1":
        handle = value.get("normalized_handle") or value.get("handle") or "unknown"
        return f"{str(handle).lower()}:{value.get('observation_id', sha256_text(stable_json(value))[:16])}"
    if topic == "evidence.media.observed.v1":
        media_id = value.get("media_id") or value.get("sha256") or sha256_text(stable_json(value))
        return f"{media_id}:{value.get('observation_id', sha256_text(stable_json(value))[:16])}"
    if topic == "evidence.search.results.v1":
        key_material = f"{value.get('query', '')}\n{value.get('url', '')}\n{value.get('searched_at', '')}"
        return sha256_text(key_material)
    if topic == "evidence.web.documents.observed.v1":
        key_material = value.get("evidence_id") or value.get("document_id") or value.get("canonical_url") or stable_json(value)
        return str(key_material)
    if topic == "evidence.user.inputs.observed.v1":
        key_material = value.get("evidence_id") or value.get("input_id") or value.get("note_id") or stable_json(value)
        return str(key_material)
    if topic.endswith(".state.v1"):
        return str(value.get("post_id") or value.get("normalized_handle") or value.get("media_id") or value.get("document_id") or value.get("input_id") or value.get("sha256"))
    return sha256_text(stable_json(value))


def resolve_outbox_root(value: str) -> Path:
    if not value:
        raise SystemExit("Missing WEB_OSINT_OUTBOX_ROOT, WEB_OSINT_DATA_ROOT, or --outbox-root")
    return Path(value).expanduser().resolve()


def spool(topic: str, value: dict[str, Any], key: str | None, outbox_root: Path) -> Path:
    pending = outbox_root / "pending"
    pending.mkdir(parents=True, exist_ok=True)
    key = key or infer_key(topic, value)
    record = {
        "topic": topic,
        "key": key,
        "value": value,
        "spooled_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    filename = f"{int(time.time() * 1000)}_{topic}_{sha256_text(key)[:16]}.json"
    path = pending / filename
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    return path


def post_record(pandaproxy: str, record: dict[str, Any]) -> None:
    topic = record["topic"]
    body = {"records": [{"key": record["key"], "value": record["value"]}]}
    req = urllib.request.Request(
        f"{pandaproxy.rstrip('/')}/topics/{topic}",
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/vnd.kafka.json.v2+json",
            "Accept": "application/vnd.kafka.v2+json",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        response.read()


def flush(pandaproxy: str, limit: int | None, outbox_root: Path) -> int:
    pending = outbox_root / "pending"
    acked = outbox_root / "acked"
    failed = outbox_root / "failed"
    acked.mkdir(parents=True, exist_ok=True)
    failed.mkdir(parents=True, exist_ok=True)
    count = 0
    for path in sorted(pending.glob("*.json")):
        if limit is not None and count >= limit:
            break
        record = load_json(path)
        try:
            post_record(pandaproxy, record)
            path.rename(acked / path.name)
            count += 1
        except Exception as exc:
            failure_path = failed / path.name
            record["flush_error"] = str(exc)
            failure_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
            path.unlink()
            raise
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description="Spool and flush Web OSINT events through Redpanda Pandaproxy.")
    sub = parser.add_subparsers(dest="command", required=True)

    spool_cmd = sub.add_parser("spool")
    spool_cmd.add_argument("--topic", required=True)
    spool_cmd.add_argument("--key")
    spool_cmd.add_argument("--value-file", required=True)
    spool_cmd.add_argument("--outbox-root", default=DEFAULT_OUTBOX_ROOT)

    flush_cmd = sub.add_parser("flush")
    flush_cmd.add_argument("--pandaproxy", default=DEFAULT_PANDAPROXY)
    flush_cmd.add_argument("--outbox-root", default=DEFAULT_OUTBOX_ROOT)
    flush_cmd.add_argument("--limit", type=int)

    args = parser.parse_args()

    if args.command == "spool":
        value = load_json(Path(args.value_file))
        if not isinstance(value, dict):
            raise SystemExit("value-file must contain a JSON object")
        path = spool(args.topic, value, args.key, resolve_outbox_root(args.outbox_root))
        print(path)
        return 0

    if args.command == "flush":
        if not args.pandaproxy:
            raise SystemExit("Missing PANDAPROXY_URL, REDPANDA_PROXY_URL, WEB_OSINT_PANDAPROXY, or --pandaproxy")
        try:
            count = flush(args.pandaproxy, args.limit, resolve_outbox_root(args.outbox_root))
        except urllib.error.URLError as exc:
            print(f"flush failed: {exc}", file=sys.stderr)
            return 2
        print(f"flushed {count} event(s)")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
