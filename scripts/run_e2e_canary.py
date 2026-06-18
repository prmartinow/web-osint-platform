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

from produce_research_documents import build_event, now_iso, post_event, slug, stable_hash  # noqa: E402


DEFAULT_DATA_ROOT_CANDIDATES = ("/mnt/data/x-research", "/mnt/data/web-osint-platform")
DEFAULT_PANDAPROXY_URL = "http://127.0.0.1:18082"
DEFAULT_CLICKHOUSE_URL = "http://127.0.0.1:18123"
DEFAULT_QDRANT_URL = "http://127.0.0.1:16333"
DEFAULT_DASHBOARD_URLS = ("http://127.0.0.1:18191", "http://192.168.1.16:18191")
CAPTURE_TOPIC = "evidence.capture.events.v1"
AUDIT_TOPIC = "osint.semantic.embedded.v1"
SHADOW_VALIDATED_TOPIC = "evidence.capture.shadow.validated.v1"


class CanaryConfigError(RuntimeError):
    pass


class CanaryDependencyError(RuntimeError):
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
class CanaryState:
    run_id: str
    started_at: str
    finished_at: str = ""
    status: str = "running"
    token: str = ""
    source_project: str = "canary"
    collector_run_id: str = ""
    input_path: str = ""
    input_sha256: str = ""
    evidence_ids: list[str] = field(default_factory=list)
    expected_chunks: int = 0
    observed_chunks: int = 0
    embedded_chunks: int = 0
    qdrant_points_found: int = 0
    shadow_validated_events: int = 0
    dashboard_exact_rank: int | None = None
    dashboard_semantic_rank: int | None = None
    hydration_ok: bool = False
    errors: list[str] = field(default_factory=list)
    steps: list[StepResult] = field(default_factory=list)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def ch_time(value: str) -> str:
    return value.replace("T", " ").replace("Z", "")


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip("'").strip('"')
        values[key.strip()] = value
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


def require_data_root(path: Path, allow_non_data_root: bool) -> None:
    resolved = path.resolve()
    if allow_non_data_root:
        return
    if not str(resolved).startswith("/mnt/data/"):
        raise CanaryConfigError(f"data root must be under /mnt/data, got {resolved}")


def deployment_defaults(data_root: Path) -> dict[str, str]:
    if data_root.name == "x-research":
        return {
            "clickhouse_database": "x_research",
            "clickhouse_user": "x_research",
            "qdrant_collection": "x_research_evidence_v1",
        }
    return {
        "clickhouse_database": "web_osint",
        "clickhouse_user": "web_osint",
        "qdrant_collection": "web_osint_evidence_v1",
    }


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
            if not raw:
                return {}
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:2000]
        raise CanaryDependencyError(f"{method} {url} returned HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise CanaryDependencyError(f"{method} {url} failed: {exc}") from exc


def ch_query(
    clickhouse_url: str,
    database: str,
    user: str,
    password: str,
    query: str,
    *,
    timeout: float = 30,
) -> dict[str, Any]:
    params = {
        "database": database,
        "query": query,
        "default_format": "JSON",
        "date_time_output_format": "iso",
        "date_time_input_format": "best_effort",
    }
    url = f"{clickhouse_url.rstrip('/')}/?{urllib.parse.urlencode(params)}"
    return request_json(url, method="POST", timeout=timeout, auth=(user, password) if password else None)


def ch_execute(
    clickhouse_url: str,
    database: str,
    user: str,
    password: str,
    query: str,
    *,
    timeout: float = 30,
) -> None:
    params = {
        "database": database,
        "query": query,
        "date_time_input_format": "best_effort",
    }
    url = f"{clickhouse_url.rstrip('/')}/?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, method="POST")
    if password:
        token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
        request.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:2000]
        raise CanaryDependencyError(f"ClickHouse execute failed HTTP {exc.code}: {detail}") from exc


def ch_insert_json_each_row(
    clickhouse_url: str,
    database: str,
    user: str,
    password: str,
    table: str,
    rows: list[dict[str, Any]],
    *,
    timeout: float = 30,
) -> None:
    if not rows:
        return
    body = "\n".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in rows).encode("utf-8")
    params = {
        "database": database,
        "query": f"INSERT INTO {table} FORMAT JSONEachRow",
        "date_time_input_format": "best_effort",
    }
    url = f"{clickhouse_url.rstrip('/')}/?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, data=body, method="POST")
    if password:
        token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
        request.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:2000]
        raise CanaryDependencyError(f"ClickHouse insert into {table} failed HTTP {exc.code}: {detail}") from exc


def ensure_ops_tables(clickhouse_url: str, database: str, user: str, password: str) -> None:
    ch_execute(
        clickhouse_url,
        database,
        user,
        password,
        """
        CREATE TABLE IF NOT EXISTS ops_canary_runs
        (
            run_id String,
            status LowCardinality(String),
            started_at DateTime64(3, 'UTC'),
            finished_at DateTime64(3, 'UTC'),
            duration_ms UInt64,
            canary_token String,
            source_project LowCardinality(String),
            collector_run_id String,
            input_path String,
            input_sha256 String,
            evidence_ids Array(String),
            expected_chunks UInt32,
            observed_chunks UInt32,
            embedded_chunks UInt32,
            qdrant_points_found UInt32,
            shadow_validated_events UInt32 DEFAULT 0,
            dashboard_exact_rank Nullable(UInt32),
            dashboard_semantic_rank Nullable(UInt32),
            hydration_ok UInt8,
            result_path String,
            errors Array(String),
            details_json String,
            created_at DateTime64(3, 'UTC') DEFAULT now64(3)
        )
        ENGINE = MergeTree
        PARTITION BY toYYYYMM(started_at)
        ORDER BY (started_at, run_id)
        """,
    )
    ch_execute(
        clickhouse_url,
        database,
        user,
        password,
        "ALTER TABLE ops_canary_runs ADD COLUMN IF NOT EXISTS shadow_validated_events UInt32 DEFAULT 0 AFTER qdrant_points_found",
    )
    ch_execute(
        clickhouse_url,
        database,
        user,
        password,
        """
        CREATE TABLE IF NOT EXISTS ops_canary_steps
        (
            run_id String,
            step_name LowCardinality(String),
            ok UInt8,
            duration_ms UInt64,
            detail_json String,
            error_class LowCardinality(String),
            error_message String,
            created_at DateTime64(3, 'UTC') DEFAULT now64(3)
        )
        ENGINE = MergeTree
        PARTITION BY toYYYYMM(created_at)
        ORDER BY (run_id, created_at, step_name)
        """,
    )


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
            raise CanaryDependencyError("Pandaproxy consumer response did not include base_uri")
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
        normalized = []
        for record in records:
            value = record.get("value")
            if isinstance(value, str):
                with contextlib.suppress(Exception):
                    decoded = base64.b64decode(value).decode("utf-8")
                    record = {**record, "value": json.loads(decoded)}
            normalized.append(record)
        return normalized

    def __exit__(self, exc_type, exc, tb) -> None:
        if not self.base_uri:
            return
        with contextlib.suppress(Exception):
            request = urllib.request.Request(self.base_uri, method="DELETE")
            urllib.request.urlopen(request, timeout=5).read()


def write_prometheus(path: Path, state: CanaryState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    labels = f'run_id="{state.run_id}",status="{state.status}"'
    ok_value = 1 if state.status == "passed" else 0
    duration_ms = 0
    if state.finished_at:
        started = datetime.fromisoformat(state.started_at.replace("Z", "+00:00"))
        finished = datetime.fromisoformat(state.finished_at.replace("Z", "+00:00"))
        duration_ms = int((finished - started).total_seconds() * 1000)
    lines = [
        "# HELP web_osint_e2e_canary_pass Last Web OSINT end-to-end canary pass status.",
        "# TYPE web_osint_e2e_canary_pass gauge",
        f"web_osint_e2e_canary_pass{{{labels}}} {ok_value}",
        "# HELP web_osint_e2e_canary_duration_ms Last Web OSINT end-to-end canary duration.",
        "# TYPE web_osint_e2e_canary_duration_ms gauge",
        f"web_osint_e2e_canary_duration_ms{{{labels}}} {duration_ms}",
        "# HELP web_osint_e2e_canary_stage_count Last Web OSINT end-to-end canary stage counts.",
        "# TYPE web_osint_e2e_canary_stage_count gauge",
        f'web_osint_e2e_canary_stage_count{{stage="expected_chunks"}} {state.expected_chunks}',
        f'web_osint_e2e_canary_stage_count{{stage="observed_chunks"}} {state.observed_chunks}',
        f'web_osint_e2e_canary_stage_count{{stage="embedded_chunks"}} {state.embedded_chunks}',
        f'web_osint_e2e_canary_stage_count{{stage="qdrant_points"}} {state.qdrant_points_found}',
        f'web_osint_e2e_canary_stage_count{{stage="shadow_validated_events"}} {state.shadow_validated_events}',
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_result(path: Path, state: CanaryState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                **{k: v for k, v in state.__dict__.items() if k != "steps"},
                "steps": [step.__dict__ for step in state.steps],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def qdrant_scroll(qdrant_url: str, collection: str, evidence_id: str) -> list[dict[str, Any]]:
    body = {
        "limit": 16,
        "with_payload": True,
        "with_vector": False,
        "filter": {"must": [{"key": "evidence_id", "match": {"value": evidence_id}}]},
    }
    response = request_json(
        f"{qdrant_url.rstrip('/')}/collections/{collection}/points/scroll",
        method="POST",
        body=body,
        timeout=20,
    )
    return response.get("result", {}).get("points", [])


def dashboard_search(dashboard_urls: list[str], query: str, source_project: str, timeout: float) -> tuple[str, dict[str, Any]]:
    body = {
        "query": query,
        "mode": "hybrid",
        "limit": 8,
        "filters": {"source_project": source_project},
        "rerank": False,
    }
    errors = []
    for base in dashboard_urls:
        try:
            response = request_json(f"{base.rstrip('/')}/api/research/search", method="POST", body=body, timeout=timeout)
            return base, response
        except Exception as exc:
            errors.append(f"{base}: {exc}")
    raise CanaryDependencyError("; ".join(errors))


def run_step(state: CanaryState, name: str, fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    started = time.time()
    try:
        detail = fn() or {}
        result = StepResult(name=name, ok=True, duration_ms=int((time.time() - started) * 1000), detail=detail)
        state.steps.append(result)
        return detail
    except Exception as exc:
        result = StepResult(
            name=name,
            ok=False,
            duration_ms=int((time.time() - started) * 1000),
            error_class=exc.__class__.__name__,
            error_message=str(exc)[:2000],
        )
        state.steps.append(result)
        state.errors.append(f"{name}: {exc}")
        raise


def poll_until(deadline: float, fn: Callable[[], Any], *, interval: float = 1.5) -> Any:
    last_value = None
    while time.time() < deadline:
        last_value = fn()
        if last_value:
            return last_value
        time.sleep(interval)
    return last_value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a Web OSINT end-to-end ingestion/search canary.")
    parser.add_argument("--env-file", type=Path, default=Path(".env"), help="Optional repo .env file.")
    parser.add_argument("--data-root", help="Durable data root. Defaults to existing /mnt/data/x-research.")
    parser.add_argument("--allow-non-data-root", action="store_true", help="Allow data roots outside /mnt/data for tests.")
    parser.add_argument("--run-id", help="Explicit run id.")
    parser.add_argument("--timeout-seconds", type=int, default=420)
    parser.add_argument("--pandaproxy-url", help="Pandaproxy URL.")
    parser.add_argument("--clickhouse-url", help="ClickHouse HTTP URL.")
    parser.add_argument("--clickhouse-database", help="ClickHouse database.")
    parser.add_argument("--clickhouse-user", help="ClickHouse user.")
    parser.add_argument("--qdrant-url", help="Qdrant HTTP URL.")
    parser.add_argument("--qdrant-collection", help="Qdrant collection.")
    parser.add_argument("--dashboard-url", action="append", default=[], help="Dashboard base URL. Can repeat.")
    parser.add_argument("--skip-dashboard", action="store_true")
    parser.add_argument("--skip-audit-topic", action="store_true")
    parser.add_argument(
        "--expect-shadow",
        action="store_true",
        help="Require a matching Redpanda Connect shadow validation event. Use only when the shadow service is running.",
    )
    parser.add_argument("--shadow-topic", default=SHADOW_VALIDATED_TOPIC)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    env_file = load_env(args.env_file)
    data_root = choose_data_root(args.data_root or env_value("OSINT_DATA_ROOT", "", env_file))
    try:
        require_data_root(data_root, args.allow_non_data_root)
    except CanaryConfigError as exc:
        print(json.dumps({"ok": False, "exit_code": 2, "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2

    pandaproxy_url = args.pandaproxy_url or env_value("REDPANDA_PROXY_URL", DEFAULT_PANDAPROXY_URL, env_file)
    clickhouse_url = args.clickhouse_url or env_value("CLICKHOUSE_URL", DEFAULT_CLICKHOUSE_URL, env_file)
    defaults = deployment_defaults(data_root)
    clickhouse_db = args.clickhouse_database or env_value(
        "CLICKHOUSE_DATABASE", defaults["clickhouse_database"], env_file
    )
    clickhouse_user = args.clickhouse_user or env_value("CLICKHOUSE_USER", defaults["clickhouse_user"], env_file)
    clickhouse_password = env_value("CLICKHOUSE_PASSWORD", "", env_file)
    qdrant_url = args.qdrant_url or env_value("QDRANT_URL", DEFAULT_QDRANT_URL, env_file)
    qdrant_collection = args.qdrant_collection or env_value(
        "QDRANT_COLLECTION", defaults["qdrant_collection"], env_file
    )
    dashboard_urls = args.dashboard_url or [url for url in DEFAULT_DASHBOARD_URLS]

    run_id = args.run_id or f"e2e_canary_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}_{secrets.token_hex(3)}"
    source_project = "canary"
    collector_run_id = f"canary_{run_id}"
    token = "WEBOSINTCANARY_" + hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:16].upper()
    state = CanaryState(
        run_id=run_id,
        started_at=utc_now(),
        token=token,
        source_project=source_project,
        collector_run_id=collector_run_id,
    )

    input_dir = data_root / "canaries" / "input"
    result_path = data_root / "canaries" / "runs" / f"{run_id}.json"
    prom_path = data_root / "metrics" / "e2e_canary.prom"
    deadline = time.time() + args.timeout_seconds
    exit_code = 1

    try:
        def create_document() -> dict[str, Any]:
            input_dir.mkdir(parents=True, exist_ok=True)
            path = input_dir / f"{run_id}.md"
            text = f"""# Web OSINT Pipeline Canary {run_id}

This synthetic research document proves the live ingestion path for the Web OSINT platform.

Unique retrieval token: {token}

The canary should flow from a manual research document capture event through Redpanda,
normalization, ClickHouse, Typesense, Qdrant, the embedding audit topic, and the dashboard
research search endpoint.

Signal topic: end-to-end ingestion canary.
Entity: Web OSINT Platform.
"""
            path.write_text(text, encoding="utf-8")
            state.input_path = str(path)
            state.input_sha256 = stable_hash(text)
            return {"input_path": state.input_path, "input_sha256": state.input_sha256, "token": token}

        run_step(state, "create_synthetic_research_document", create_document)

        def ensure_tables() -> dict[str, Any]:
            ensure_ops_tables(clickhouse_url, clickhouse_db, clickhouse_user, clickhouse_password)
            return {"database": clickhouse_db, "tables": ["ops_canary_runs", "ops_canary_steps"]}

        run_step(state, "ensure_clickhouse_ops_tables", ensure_tables)

        audit_records: list[dict[str, Any]] = []
        consumer_group = f"web-osint-e2e-canary-{run_id}"
        consumer_cm: Any = contextlib.nullcontext(None)
        if not args.skip_audit_topic:
            consumer_cm = PandaProxyConsumer(pandaproxy_url, consumer_group, AUDIT_TOPIC)
        shadow_records: list[dict[str, Any]] = []
        shadow_cm: Any = contextlib.nullcontext(None)
        if args.expect_shadow:
            shadow_cm = PandaProxyConsumer(pandaproxy_url, f"{consumer_group}-shadow", args.shadow_topic)

        with consumer_cm as audit_consumer, shadow_cm as shadow_consumer:
            def publish_capture() -> dict[str, Any]:
                path = Path(state.input_path)
                event = build_event(
                    [path],
                    source_root=path.parent,
                    source_project=source_project,
                    capture_method="e2e_canary_manual_research_document",
                    collector_run_id=collector_run_id,
                    captured_at=now_iso(),
                    chunk_chars=3600,
                    topics=["pipeline-canary", "web-osint"],
                    entities=["Web OSINT Platform"],
                )
                state.expected_chunks = int(event.get("context", {}).get("chunk_count") or 0)
                state.evidence_ids = [item["input_id"] for item in event.get("user_inputs", [])]
                response_raw = post_event(pandaproxy_url, CAPTURE_TOPIC, event)
                response = json.loads(response_raw) if response_raw else {}
                return {
                    "topic": CAPTURE_TOPIC,
                    "collector_run_id": collector_run_id,
                    "expected_chunks": state.expected_chunks,
                    "evidence_ids": state.evidence_ids,
                    "pandaproxy_offsets": response,
                }

            run_step(state, "publish_capture_event_to_redpanda", publish_capture)

            if shadow_consumer is not None:
                def poll_shadow_topic() -> dict[str, Any] | None:
                    for record in shadow_consumer.records(timeout_ms=1200):
                        value = record.get("value") or {}
                        if isinstance(value, dict):
                            shadow_records.append(value)
                    matched = [
                        item
                        for item in shadow_records
                        if str(item.get("collector_run_id")) == collector_run_id
                    ]
                    state.shadow_validated_events = len(matched)
                    if matched:
                        return {
                            "topic": args.shadow_topic,
                            "matched_events": len(matched),
                            "collector_run_id": collector_run_id,
                        }
                    return None

                shadow = poll_until(deadline, poll_shadow_topic, interval=1.0)
                if not shadow:
                    raise RuntimeError(f"shadow Connect topic {args.shadow_topic} did not validate {collector_run_id} before timeout")
                state.steps.append(StepResult("poll_redpanda_connect_shadow_validated_topic", True, 0, shadow))

            def poll_observed_rows() -> dict[str, Any] | None:
                rows = ch_query(
                    clickhouse_url,
                    clickhouse_db,
                    clickhouse_user,
                    clickhouse_password,
                    f"""
                    SELECT evidence_id, source_kind, title, length(text) AS text_len
                    FROM evidence_events
                    WHERE collector_run_id = {sql_quote(collector_run_id)}
                      AND source_kind = 'user_input'
                    ORDER BY evidence_id
                    """,
                    timeout=20,
                ).get("data", [])
                state.observed_chunks = len(rows)
                if len(rows) >= state.expected_chunks:
                    state.evidence_ids = [str(row.get("evidence_id")) for row in rows if row.get("evidence_id")]
                    return {"rows": rows, "observed_chunks": state.observed_chunks}
                return None

            observed = poll_until(deadline, poll_observed_rows)
            if not observed:
                raise RuntimeError(f"normalizer/ClickHouse did not observe {state.expected_chunks} chunks before timeout")
            state.steps.append(StepResult("poll_clickhouse_observed_rows", True, 0, observed))

            if audit_consumer is not None:
                def poll_audit_topic() -> dict[str, Any] | None:
                    for record in audit_consumer.records(timeout_ms=1200):
                        value = record.get("value") or {}
                        if isinstance(value, dict):
                            audit_records.append(value)
                    matched = [
                        item for item in audit_records if str(item.get("evidence_id")) in set(state.evidence_ids)
                    ]
                    state.embedded_chunks = len({str(item.get("evidence_id")) for item in matched})
                    if state.embedded_chunks >= state.expected_chunks:
                        return {"matched_audit_records": matched[-state.expected_chunks :], "embedded_chunks": state.embedded_chunks}
                    return None

                started = time.time()
                embedded = poll_until(deadline, poll_audit_topic, interval=1.0)
                if not embedded:
                    raise RuntimeError(f"embedding audit topic did not report {state.expected_chunks} chunks before timeout")
                state.steps.append(
                    StepResult(
                        "poll_redpanda_embedding_audit_topic",
                        True,
                        int((time.time() - started) * 1000),
                        embedded,
                    )
                )

        def poll_qdrant_points() -> dict[str, Any] | None:
            found = []
            for evidence_id in state.evidence_ids:
                points = qdrant_scroll(qdrant_url, qdrant_collection, evidence_id)
                found.extend(points)
            state.qdrant_points_found = len(found)
            if state.qdrant_points_found >= state.expected_chunks:
                return {
                    "collection": qdrant_collection,
                    "points_found": state.qdrant_points_found,
                    "payloads": [point.get("payload", {}) for point in found],
                }
            return None

        started = time.time()
        qdrant_result = poll_until(deadline, poll_qdrant_points, interval=2.0)
        if not qdrant_result:
            raise RuntimeError(f"Qdrant did not contain {state.expected_chunks} canary points before timeout")
        state.steps.append(StepResult("poll_qdrant_points", True, int((time.time() - started) * 1000), qdrant_result))

        if not args.skip_dashboard:
            def dashboard_check() -> dict[str, Any]:
                base, response = dashboard_search(dashboard_urls, token, source_project, timeout=180)
                hits = response.get("results") or response.get("hits") or []
                for idx, hit in enumerate(hits, start=1):
                    evidence_id = str(hit.get("evidence_id") or hit.get("id") or "")
                    if evidence_id in state.evidence_ids:
                        state.dashboard_exact_rank = idx
                        state.hydration_ok = bool(hit.get("text") or hit.get("title") or hit.get("canonical_url"))
                        break
                if state.dashboard_exact_rank is None:
                    raise RuntimeError("dashboard search did not return the canary evidence")
                return {
                    "dashboard_url": base,
                    "rank": state.dashboard_exact_rank,
                    "hydration_ok": state.hydration_ok,
                    "result_count": len(hits),
                    "timings": response.get("timings_ms") or response.get("debug", {}).get("timings_ms", {}),
                    "warnings": response.get("warnings", []),
                }

            run_step(state, "dashboard_exact_search_and_hydration", dashboard_check)

        state.status = "passed"
        exit_code = 0
    except CanaryConfigError as exc:
        state.status = "config_error"
        state.errors.append(str(exc))
        exit_code = 2
    except CanaryDependencyError as exc:
        state.status = "dependency_unavailable"
        state.errors.append(str(exc))
        exit_code = 3
    except Exception as exc:
        state.status = "failed"
        state.errors.append(str(exc))
        exit_code = 1
    finally:
        state.finished_at = utc_now()
        write_result(result_path, state)
        write_prometheus(prom_path, state)
        with contextlib.suppress(Exception):
            started = datetime.fromisoformat(state.started_at.replace("Z", "+00:00"))
            finished = datetime.fromisoformat(state.finished_at.replace("Z", "+00:00"))
            duration_ms = int((finished - started).total_seconds() * 1000)
            ch_insert_json_each_row(
                clickhouse_url,
                clickhouse_db,
                clickhouse_user,
                clickhouse_password,
                "ops_canary_runs",
                [
                    {
                        "run_id": state.run_id,
                        "status": state.status,
                        "started_at": ch_time(state.started_at),
                        "finished_at": ch_time(state.finished_at),
                        "duration_ms": duration_ms,
                        "canary_token": state.token,
                        "source_project": state.source_project,
                        "collector_run_id": state.collector_run_id,
                        "input_path": state.input_path,
                        "input_sha256": state.input_sha256,
                        "evidence_ids": state.evidence_ids,
                        "expected_chunks": state.expected_chunks,
                        "observed_chunks": state.observed_chunks,
                        "embedded_chunks": state.embedded_chunks,
                        "qdrant_points_found": state.qdrant_points_found,
                        "shadow_validated_events": state.shadow_validated_events,
                        "dashboard_exact_rank": state.dashboard_exact_rank,
                        "dashboard_semantic_rank": state.dashboard_semantic_rank,
                        "hydration_ok": 1 if state.hydration_ok else 0,
                        "result_path": str(result_path),
                        "errors": state.errors,
                        "details_json": json.dumps({"steps": [step.__dict__ for step in state.steps]}, ensure_ascii=False),
                    }
                ],
            )
            ch_insert_json_each_row(
                clickhouse_url,
                clickhouse_db,
                clickhouse_user,
                clickhouse_password,
                "ops_canary_steps",
                [
                    {
                        "run_id": state.run_id,
                        "step_name": step.name,
                        "ok": 1 if step.ok else 0,
                        "duration_ms": step.duration_ms,
                        "detail_json": json.dumps(step.detail, ensure_ascii=False),
                        "error_class": step.error_class,
                        "error_message": step.error_message,
                    }
                    for step in state.steps
                ],
            )

        print(
            json.dumps(
                {
                    "ok": exit_code == 0,
                    "exit_code": exit_code,
                    "status": state.status,
                    "run_id": state.run_id,
                    "result_path": str(result_path),
                    "prometheus_textfile": str(prom_path),
                    "expected_chunks": state.expected_chunks,
                    "observed_chunks": state.observed_chunks,
                    "embedded_chunks": state.embedded_chunks,
                    "qdrant_points_found": state.qdrant_points_found,
                    "shadow_validated_events": state.shadow_validated_events,
                    "dashboard_exact_rank": state.dashboard_exact_rank,
                    "errors": state.errors,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    return exit_code


def sql_quote(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


if __name__ == "__main__":
    raise SystemExit(main())
