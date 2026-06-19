#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from produce_research_documents import post_event  # noqa: E402


DEFAULT_DATA_ROOT_CANDIDATES = ("/mnt/data/x-research", "/mnt/data/web-osint-platform")
DEFAULT_PANDAPROXY_URL = "http://127.0.0.1:18082"
DEFAULT_CLICKHOUSE_URL = "http://127.0.0.1:18123"
CAPTURE_TOPIC = "evidence.capture.events.v1"
SHADOW_OBSERVED_TOPIC = "evidence.capture.shadow.observed.v1"
SHADOW_MEDIA_REQUEST_TOPIC = "osint.media.enrichment.shadow.requested.v1"


class ParityError(RuntimeError):
    pass


@dataclass
class StepResult:
    name: str
    ok: bool
    duration_ms: int
    detail: dict[str, Any] = field(default_factory=dict)
    error_class: str = ""
    error_message: str = ""


@dataclass
class ParityState:
    run_id: str
    started_at: str
    status: str = "running"
    finished_at: str = ""
    collector_run_id: str = ""
    token: str = ""
    expected: dict[str, dict[str, str]] = field(default_factory=dict)
    matched_source_kinds: list[str] = field(default_factory=list)
    shadow_observed_events: int = 0
    shadow_media_request_events: int = 0
    parity_ok: bool = False
    media_request_ok: bool = False
    result_path: str = ""
    errors: list[str] = field(default_factory=list)
    steps: list[StepResult] = field(default_factory=list)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def canonical_sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def go_stable_hash(*parts: str) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(str(part).encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()


def sql_string(value: Any) -> str:
    text = str(value)
    return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'").strip('"')
    return values


def env_value(name: str, default: str, env_file: dict[str, str]) -> str:
    return os.environ.get(name) or env_file.get(name) or default


def choose_data_root(raw: str | None) -> Path:
    candidates = [raw] if raw else list(DEFAULT_DATA_ROOT_CANDIDATES)
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate).expanduser()
        if path.exists():
            return path.resolve()
    return Path(candidates[0] or DEFAULT_DATA_ROOT_CANDIDATES[0]).expanduser().resolve()


def deployment_defaults(data_root: Path) -> dict[str, str]:
    if data_root.name == "x-research":
        return {"clickhouse_database": "x_research", "clickhouse_user": "x_research"}
    return {"clickhouse_database": "web_osint", "clickhouse_user": "web_osint"}


def request_json(
    url: str,
    *,
    method: str = "GET",
    body: Any | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 20,
    auth: tuple[str, str] | None = None,
) -> Any:
    req_headers = dict(headers or {})
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req_headers.setdefault("Content-Type", "application/json")
    if auth:
        token = base64.b64encode(f"{auth[0]}:{auth[1]}".encode("utf-8")).decode("ascii")
        req_headers["Authorization"] = f"Basic {token}"
    request = urllib.request.Request(url, data=data, method=method, headers=req_headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:2000]
        raise ParityError(f"{method} {url} returned HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise ParityError(f"{method} {url} failed: {exc}") from exc


def ch_query(clickhouse_url: str, database: str, user: str, password: str, query: str) -> list[dict[str, Any]]:
    params = {
        "database": database,
        "query": query,
        "default_format": "JSON",
        "date_time_output_format": "iso",
        "date_time_input_format": "best_effort",
    }
    data = request_json(
        f"{clickhouse_url.rstrip('/')}/?{urllib.parse.urlencode(params)}",
        method="POST",
        timeout=30,
        auth=(user, password) if password else None,
    )
    return data.get("data", [])


class PandaProxyConsumer:
    def __init__(self, pandaproxy_url: str, group: str, topic: str):
        self.pandaproxy_url = pandaproxy_url.rstrip("/")
        self.group = group
        self.topic = topic
        self.base_uri = ""

    def __enter__(self) -> "PandaProxyConsumer":
        headers = {
            "Accept": "application/vnd.kafka.v2+json",
            "Content-Type": "application/vnd.kafka.v2+json",
        }
        payload = {"format": "binary", "auto.offset.reset": "earliest"}
        response = request_json(
            f"{self.pandaproxy_url}/consumers/{urllib.parse.quote(self.group)}",
            method="POST",
            body=payload,
            headers=headers,
            timeout=15,
        )
        self.base_uri = str(response.get("base_uri") or "")
        if not self.base_uri:
            raise ParityError("Pandaproxy consumer response did not include base_uri")
        request_json(
            f"{self.base_uri}/subscription",
            method="POST",
            body={"topics": [self.topic]},
            headers=headers,
            timeout=15,
        )
        return self

    def records(self, timeout_ms: int = 1000) -> list[dict[str, Any]]:
        if not self.base_uri:
            return []
        params = urllib.parse.urlencode({"timeout": timeout_ms, "max_bytes": 1048576})
        records = request_json(
            f"{self.base_uri}/records?{params}",
            headers={"Accept": "application/vnd.kafka.binary.v2+json"},
            timeout=max(3, timeout_ms / 1000 + 2),
        )
        out = []
        for record in records:
            value = record.get("value")
            if isinstance(value, str):
                with contextlib.suppress(Exception):
                    decoded = base64.b64decode(value).decode("utf-8")
                    record = {**record, "value": json.loads(decoded)}
            out.append(record)
        return out

    def __exit__(self, exc_type, exc, tb) -> None:
        if not self.base_uri:
            return
        with contextlib.suppress(Exception):
            request = urllib.request.Request(self.base_uri, method="DELETE")
            urllib.request.urlopen(request, timeout=5).read()


def run_step(state: ParityState, name: str, fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    started = time.time()
    try:
        detail = fn() or {}
        state.steps.append(StepResult(name=name, ok=True, duration_ms=int((time.time() - started) * 1000), detail=detail))
        return detail
    except Exception as exc:
        state.steps.append(
            StepResult(
                name=name,
                ok=False,
                duration_ms=int((time.time() - started) * 1000),
                error_class=exc.__class__.__name__,
                error_message=str(exc)[:2000],
            )
        )
        state.errors.append(f"{name}: {exc}")
        raise


def poll_until(deadline: float, fn: Callable[[], Any], *, interval: float = 1.0) -> Any:
    last = None
    while time.time() < deadline:
        last = fn()
        if last:
            return last
        time.sleep(interval)
    return last


def build_capture(run_id: str, collector_run_id: str, token: str, data_root: Path) -> tuple[dict[str, Any], dict[str, dict[str, str]]]:
    query = f"web osint shadow parity {token}"
    search_url = f"https://example.com/web-osint-shadow-parity/{run_id}"
    search_id = go_stable_hash(query, search_url, "0")
    web_id = f"shadow-parity-web-{run_id}"
    input_id = f"shadow-parity-user-{run_id}"
    media_id = f"shadow-parity-media-{run_id}"
    media_sha = hashlib.sha256(f"{run_id}:{token}:media".encode("utf-8")).hexdigest()
    storage_path = str(data_root / "canaries" / "connect-shadow" / "input" / f"{run_id}-shadow-media.png")
    captured_at = utc_now()
    event = {
        "schema_version": "v1",
        "collector_run_id": collector_run_id,
        "event_index": 0,
        "source_project": "canary",
        "capture_method": "connect_shadow_parity",
        "captured_at": captured_at,
        "context": {"query": query, "engine": "google", "token": token},
        "search_results": [
            {
                "rank": 1,
                "url": search_url,
                "title": f"Shadow parity search result {token}",
                "snippet": "Synthetic search result for Redpanda Connect shadow parity.",
            }
        ],
        "web_documents": [
            {
                "document_id": web_id,
                "canonical_url": search_url,
                "title": f"Shadow parity web document {token}",
                "text": f"Synthetic web document for Connect shadow parity. Token {token}.",
                "document_kind": "canary_fixture",
                "topics": ["connect-shadow", "web-osint"],
            }
        ],
        "media": [
            {
                "media_id": media_id,
                "media_kind": "screenshot",
                "storage_path": storage_path,
                "sha256": media_sha,
                "mime_type": "image/png",
                "width": 2,
                "height": 3,
                "byte_size": 67,
                "caption": f"Synthetic shadow media request fixture {token}",
                "topics": ["connect-shadow", "media"],
            }
        ],
        "user_inputs": [
            {
                "input_id": input_id,
                "input_kind": "research_note",
                "author": "canary",
                "title": f"Shadow parity user input {token}",
                "text": f"Synthetic user input for Connect shadow parity. Token {token}.",
                "topics": ["connect-shadow", "user-input"],
            }
        ],
        "quality": {"partial": False, "challenge": False},
    }
    expected = {
        "user_input": {"source_kind": "user_input", "evidence_id": f"user_input/{input_id}"},
        "web_page": {"source_kind": "web_page", "evidence_id": f"web_document/{web_id}"},
        "media": {"source_kind": "media", "evidence_id": media_id, "sha256": media_sha, "storage_path": storage_path},
        "search_result": {"source_kind": "search_result", "evidence_id": search_id},
    }
    return event, expected


def parse_raw_json(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("raw_json") or "{}"
    if isinstance(raw, dict):
        return raw
    return json.loads(str(raw))


def write_result(path: Path, state: ParityState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state.result_path = str(path)
    path.write_text(
        json.dumps(
            {**{k: v for k, v in state.__dict__.items() if k != "steps"}, "steps": [step.__dict__ for step in state.steps]},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Redpanda Connect shadow projection parity checks.")
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--data-root")
    parser.add_argument("--run-id")
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--pandaproxy-url", default="")
    parser.add_argument("--clickhouse-url", default="")
    parser.add_argument("--clickhouse-database", default="")
    parser.add_argument("--clickhouse-user", default="")
    parser.add_argument("--shadow-observed-topic", default=SHADOW_OBSERVED_TOPIC)
    parser.add_argument("--shadow-media-request-topic", default=SHADOW_MEDIA_REQUEST_TOPIC)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    env_file = load_env(args.env_file)
    data_root = choose_data_root(args.data_root or env_value("OSINT_DATA_ROOT", "", env_file))
    defaults = deployment_defaults(data_root)
    pandaproxy_url = args.pandaproxy_url or env_value("REDPANDA_PROXY_URL", DEFAULT_PANDAPROXY_URL, env_file)
    clickhouse_url = args.clickhouse_url or env_value("CLICKHOUSE_URL", DEFAULT_CLICKHOUSE_URL, env_file)
    clickhouse_db = args.clickhouse_database or env_value("CLICKHOUSE_DATABASE", defaults["clickhouse_database"], env_file)
    clickhouse_user = args.clickhouse_user or env_value("CLICKHOUSE_USER", defaults["clickhouse_user"], env_file)
    clickhouse_password = env_value("CLICKHOUSE_PASSWORD", "", env_file)
    run_id = args.run_id or f"connect_shadow_parity_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}_{secrets.token_hex(3)}"
    collector_run_id = f"connect_shadow_parity_{run_id}"
    token = "CONNECT_SHADOW_" + hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:12].upper()
    state = ParityState(run_id=run_id, started_at=utc_now(), collector_run_id=collector_run_id, token=token)
    result_path = data_root / "canaries" / "connect-shadow" / "runs" / f"{run_id}.json"
    deadline = time.time() + args.timeout_seconds
    exit_code = 1

    try:
        event, expected = build_capture(run_id, collector_run_id, token, data_root)
        state.expected = expected
        consumer_group = f"web-osint-connect-shadow-parity-{run_id}"
        observed_records: list[dict[str, Any]] = []
        request_records: list[dict[str, Any]] = []
        with PandaProxyConsumer(pandaproxy_url, consumer_group + "-observed", args.shadow_observed_topic) as observed_consumer, PandaProxyConsumer(
            pandaproxy_url, consumer_group + "-media-request", args.shadow_media_request_topic
        ) as request_consumer:
            def publish() -> dict[str, Any]:
                raw = post_event(pandaproxy_url, CAPTURE_TOPIC, event)
                return {"topic": CAPTURE_TOPIC, "collector_run_id": collector_run_id, "response": json.loads(raw) if raw else {}}

            run_step(state, "publish_shadow_parity_capture", publish)

            def clickhouse_rows() -> dict[str, Any] | None:
                ids = [item["evidence_id"] for item in expected.values()]
                rows = ch_query(
                    clickhouse_url,
                    clickhouse_db,
                    clickhouse_user,
                    clickhouse_password,
                    f"""
                    SELECT evidence_id, source_kind, raw_json
                    FROM evidence_events
                    WHERE collector_run_id = {sql_string(collector_run_id)}
                      AND evidence_id IN ({",".join(sql_string(v) for v in ids)})
                    ORDER BY source_kind, evidence_id
                    """,
                )
                if len(rows) < len(expected):
                    return None
                return {"rows": rows}

            rows_detail = poll_until(deadline, clickhouse_rows)
            if not rows_detail:
                raise ParityError("ClickHouse did not materialize all parity rows before timeout")
            run_step(state, "poll_clickhouse_normalizer_rows", lambda: rows_detail)
            normalizer_by_id = {str(row["evidence_id"]): parse_raw_json(row) for row in rows_detail["rows"]}

            def shadow_observed() -> dict[str, Any] | None:
                for record in observed_consumer.records(timeout_ms=1200):
                    value = record.get("value") or {}
                    if isinstance(value, dict):
                        observed_records.append(value)
                matched = [
                    item
                    for item in observed_records
                    if str(item.get("collector_run_id")) == collector_run_id
                    and str(item.get("evidence_id")) in {v["evidence_id"] for v in expected.values()}
                ]
                state.shadow_observed_events = len(matched)
                if len(matched) >= len(expected):
                    return {"matched": matched}
                return None

            shadow_detail = poll_until(deadline, shadow_observed)
            if not shadow_detail:
                raise ParityError("Connect shadow observed topic did not emit all parity records before timeout")

            comparisons = []
            matched_kinds = []
            for item in shadow_detail["matched"]:
                evidence_id = str(item["evidence_id"])
                source_kind = str(item["source_kind"])
                shadow_payload = item.get("observed") or {}
                normalizer_payload = normalizer_by_id.get(evidence_id)
                if normalizer_payload is None:
                    raise ParityError(f"missing normalizer payload for {evidence_id}")
                shadow_sha = canonical_sha(shadow_payload)
                normalizer_sha = canonical_sha(normalizer_payload)
                ok = shadow_sha == normalizer_sha
                comparisons.append(
                    {
                        "source_kind": source_kind,
                        "evidence_id": evidence_id,
                        "shadow_sha256": shadow_sha,
                        "normalizer_sha256": normalizer_sha,
                        "matches": ok,
                    }
                )
                if ok:
                    matched_kinds.append(source_kind)
            if not all(item["matches"] for item in comparisons):
                raise ParityError(f"shadow observed parity mismatch: {comparisons}")
            state.matched_source_kinds = sorted(set(matched_kinds))
            state.parity_ok = True
            run_step(state, "compare_shadow_observed_to_normalizer_raw_json", lambda: {"comparisons": comparisons})

            def media_request() -> dict[str, Any] | None:
                for record in request_consumer.records(timeout_ms=1200):
                    value = record.get("value") or {}
                    if isinstance(value, dict):
                        request_records.append(value)
                matched = [
                    item
                    for item in request_records
                    if str((item.get("request") or {}).get("collector_run_id")) == collector_run_id
                ]
                state.shadow_media_request_events = len(matched)
                if matched:
                    return {"matched": matched}
                return None

            request_detail = poll_until(deadline, media_request)
            if not request_detail:
                raise ParityError("Connect shadow media request topic did not emit a media request before timeout")
            request = request_detail["matched"][0]["request"]
            media_expected = expected["media"]
            checks = {
                "shadow_only": request.get("shadow_only") is True,
                "evidence_id": request.get("evidence_id") == media_expected["evidence_id"],
                "artifact_sha256": request.get("artifact_sha256") == media_expected["sha256"],
                "storage_path": request.get("storage_path") == media_expected["storage_path"],
                "producer_name": request.get("producer_name") == "media_enrichment_request_builder",
            }
            if not all(checks.values()):
                raise ParityError(f"shadow media request mismatch: {checks}")
            state.media_request_ok = True
            run_step(state, "check_shadow_media_request_builder", lambda: {"checks": checks, "request": request})

        state.status = "passed"
        exit_code = 0
    except Exception as exc:
        state.status = "failed"
        state.errors.append(str(exc))
        exit_code = 1
    finally:
        state.finished_at = utc_now()
        write_result(result_path, state)
        print(
            json.dumps(
                {
                    "ok": exit_code == 0,
                    "status": state.status,
                    "run_id": state.run_id,
                    "result_path": state.result_path,
                    "matched_source_kinds": state.matched_source_kinds,
                    "shadow_observed_events": state.shadow_observed_events,
                    "shadow_media_request_events": state.shadow_media_request_events,
                    "parity_ok": state.parity_ok,
                    "media_request_ok": state.media_request_ok,
                    "errors": state.errors,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
