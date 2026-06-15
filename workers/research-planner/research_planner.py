#!/usr/bin/env python3
import argparse
import base64
import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


GENERATOR_NAME = "deterministic_research_planner"
GENERATOR_VERSION = "0.1.0"

SIGNAL_TOPIC = "osint.research_signal.detected.v1"
QUESTION_TOPIC = "osint.research_question.proposed.v1"
TASK_TOPIC = "osint.research_task.created.v1"


class Config:
    def __init__(self) -> None:
        self.clickhouse_url = os.environ.get("CLICKHOUSE_URL", "http://127.0.0.1:18123").rstrip("/")
        self.clickhouse_db = os.environ.get("CLICKHOUSE_DATABASE", "web_osint")
        self.clickhouse_user = os.environ.get("CLICKHOUSE_USER", "web_osint")
        self.clickhouse_password = os.environ.get("CLICKHOUSE_PASSWORD", "")
        self.redpanda_proxy_url = os.environ.get("REDPANDA_PROXY_URL", "http://127.0.0.1:18082").rstrip("/")
        self.http_addr = os.environ.get("HTTP_ADDR", ":8092")
        self.interval_seconds = int(os.environ.get("RESEARCH_PLANNER_INTERVAL_SECONDS", "300"))
        self.lookback_hours = int(os.environ.get("RESEARCH_PLANNER_LOOKBACK_HOURS", "24"))
        self.candidate_limit = int(os.environ.get("RESEARCH_PLANNER_CANDIDATE_LIMIT", "250"))


class Stats:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.data: dict[str, Any] = {
            "runs": 0,
            "failed": 0,
            "signals_created": 0,
            "questions_created": 0,
            "tasks_created": 0,
            "candidates_seen": 0,
            "last_run_at": None,
            "last_error": "",
        }

    def update(self, **values: Any) -> None:
        with self.lock:
            for key, value in values.items():
                if isinstance(value, int) and isinstance(self.data.get(key), int):
                    self.data[key] += value
                else:
                    self.data[key] = value

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return dict(self.data)


def stable_hash(*parts: str) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(str(part).encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()


def short_id(prefix: str, *parts: str) -> str:
    return f"{prefix}_{stable_hash(*parts)[:24]}"


def slug(value: str) -> str:
    out = []
    last = False
    for ch in value.lower().strip():
        if ch.isalnum():
            out.append(ch)
            last = False
        elif not last:
            out.append("_")
            last = True
    return "".join(out).strip("_")


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def sql_string(value: str) -> str:
    return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"


def ch_request(cfg: Config, query: str, body: bytes | None = None) -> dict[str, Any]:
    params = {
        "database": cfg.clickhouse_db,
        "query": query,
        "default_format": "JSON",
        "date_time_input_format": "best_effort",
        "date_time_output_format": "iso",
        "input_format_null_as_default": "1",
    }
    url = cfg.clickhouse_url + "/?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, data=body or b"", method="POST")
    if cfg.clickhouse_password:
        token = base64.b64encode(f"{cfg.clickhouse_user}:{cfg.clickhouse_password}".encode()).decode()
        req.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:2000]
        raise RuntimeError(f"ClickHouse HTTP {exc.code}: {detail}") from exc
    return json.loads(raw.decode("utf-8")) if raw else {}


def ch_data(cfg: Config, query: str) -> list[dict[str, Any]]:
    return ch_request(cfg, query).get("data", [])


def ch_insert(cfg: Config, table: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    payload = "\n".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in rows).encode("utf-8") + b"\n"
    ch_request(cfg, f"INSERT INTO {table} FORMAT JSONEachRow", payload)


def existing_ids(cfg: Config, table: str, column: str, ids: list[str]) -> set[str]:
    if not ids:
        return set()
    values = ", ".join(sql_string(i) for i in ids)
    rows = ch_data(cfg, f"SELECT {column} AS id FROM {table} WHERE {column} IN ({values})")
    return {str(row["id"]) for row in rows}


def post_redpanda(cfg: Config, topic: str, key: str, value: dict[str, Any]) -> None:
    body = {"records": [{"key": key, "value": value}]}
    req = urllib.request.Request(
        f"{cfg.redpanda_proxy_url}/topics/{topic}",
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/vnd.kafka.json.v2+json",
            "Accept": "application/vnd.kafka.v2+json",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        response.read()


def recent_evidence(cfg: Config) -> list[dict[str, Any]]:
    return ch_data(
        cfg,
        f"""
        SELECT
          evidence_id,
          any(source_project) AS source_project,
          any(source_kind) AS source_kind,
          any(canonical_url) AS canonical_url,
          any(author_handle) AS author_handle,
          any(domain) AS domain,
          any(title) AS title,
          substring(any(text), 1, 800) AS text_preview,
          arrayDistinct(arrayFlatten(groupArray(topics))) AS topics,
          arrayDistinct(arrayFlatten(groupArray(entities))) AS entities,
          max(captured_at) AS captured_at,
          max(ingested_at) AS last_ingested_at
        FROM evidence_events
        WHERE ingested_at >= now64() - INTERVAL {cfg.lookback_hours} HOUR
        GROUP BY evidence_id
        ORDER BY last_ingested_at DESC
        LIMIT {cfg.candidate_limit}
        """,
    )


def recent_annotations(cfg: Config) -> dict[str, list[dict[str, Any]]]:
    rows = ch_data(
        cfg,
        f"""
        SELECT
          evidence_id,
          annotation_id,
          annotation_family,
          label_id,
          status,
          confidence,
          value_json,
          created_at
        FROM semantic_annotations
        WHERE created_at >= now64() - INTERVAL {cfg.lookback_hours} HOUR
        ORDER BY created_at DESC
        LIMIT {cfg.candidate_limit * 30}
        """,
    )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["evidence_id"]), []).append(row)
    return grouped


def choose_topic(labels: list[str], topics: list[str]) -> str:
    for label in labels:
        if label.startswith("topic."):
            return label
    for topic in topics:
        s = slug(topic)
        if s:
            return "topic." + s
    return "topic.uncategorized"


def primary_entity(entities: list[str]) -> str:
    if not entities:
        return ""
    s = slug(str(entities[0]))
    return "entity." + s if s else ""


def descriptor(evidence: dict[str, Any], topic_label_id: str) -> str:
    for key in ["title", "text_preview", "canonical_url", "evidence_id"]:
        value = str(evidence.get(key) or "").strip()
        if value:
            return value[:140]
    return topic_label_id


def classify_candidate(evidence: dict[str, Any], annotations: list[dict[str, Any]]) -> dict[str, Any] | None:
    labels = [str(a.get("label_id") or "") for a in annotations]
    if not labels:
        return None
    topics = [str(t) for t in evidence.get("topics") or [] if str(t).strip()]
    topic_label_id = choose_topic(labels, topics)
    entity_id = primary_entity([str(e) for e in evidence.get("entities") or [] if str(e).strip()])
    evidence_id = str(evidence.get("evidence_id") or "")
    text = descriptor(evidence, topic_label_id)

    signal_type = ""
    question_type = ""
    task_type = ""
    question = ""
    rationale = ""
    priority = 0.55
    expected_value = 0.55
    uncertainty = 0.45
    novelty = 0.45
    impact = 0.5
    user_interest = 0.35

    if "quality.user_supplied" in labels:
        signal_type = "user_seed"
        question_type = "research_direction"
        task_type = "expand_user_seed"
        question = f"What research direction should be opened from this user-supplied seed: {text}?"
        rationale = "User-supplied evidence should be turned into explicit research directions before it disappears into the general corpus."
        priority = 0.82
        expected_value = 0.78
        uncertainty = 0.55
        novelty = 0.65
        impact = 0.72
        user_interest = 0.95
    elif "action.compare" in labels:
        signal_type = "comparison_opportunity"
        question_type = "comparison"
        task_type = "collect_comparison_evidence"
        question = f"How does the system, claim, or benchmark in {text} compare across primary and independent sources?"
        rationale = "The evidence carries comparison or benchmark signals and should be connected to competing systems, metrics, or claims."
        priority = 0.74
        expected_value = 0.72
        uncertainty = 0.48
        novelty = 0.55
        impact = 0.7
    elif "action.verify" in labels:
        signal_type = "verification_needed"
        question_type = "verification"
        task_type = "verify_primary_sources"
        question = f"What primary-source evidence verifies the release, availability, or documentation claims in {text}?"
        rationale = "The evidence contains launch, release, model-card, or availability cues that should be verified against primary sources."
        priority = 0.68
        expected_value = 0.67
        uncertainty = 0.5
        novelty = 0.48
        impact = 0.62
    elif "action.collect_more" in labels:
        signal_type = "source_expansion"
        question_type = "source_discovery"
        task_type = "collect_related_sources"
        question = f"What additional primary sources, launch posts, docs, benchmarks, or discussions connect to {text}?"
        rationale = "The evidence points outward through links, search results, or source references and can seed more collection."
        priority = 0.58
        expected_value = 0.6
        uncertainty = 0.52
        novelty = 0.42
        impact = 0.52
    else:
        return None

    dedupe = f"{GENERATOR_NAME}:{GENERATOR_VERSION}:{signal_type}:{evidence_id}"
    signal_id = short_id("sig", dedupe)
    question_id = short_id("q", dedupe)
    task_id = short_id("task", dedupe)
    created_at = now_iso()
    annotation_ids = [str(a.get("annotation_id") or "") for a in annotations if a.get("annotation_id")]
    seed_label_ids = sorted({label for label in labels if label})
    seed_entities = [entity_id] if entity_id else []

    signal = {
        "signal_id": signal_id,
        "signal_type": signal_type,
        "primary_entity_id": entity_id,
        "topic_label_id": topic_label_id,
        "evidence_ids": [evidence_id],
        "annotation_ids": annotation_ids,
        "signal_summary": question,
        "rationale": rationale,
        "novelty_score": novelty,
        "uncertainty_score": uncertainty,
        "impact_score": impact,
        "source_strength_score": source_strength(evidence.get("source_kind"), labels),
        "user_interest_score": user_interest,
        "created_at": created_at,
    }
    research_question = {
        "question_id": question_id,
        "question_text": question,
        "question_type": question_type,
        "trigger_signal_ids": [signal_id],
        "seed_evidence_ids": [evidence_id],
        "seed_entity_ids": seed_entities,
        "seed_label_ids": seed_label_ids,
        "rationale": rationale,
        "priority": priority,
        "expected_value": expected_value,
        "uncertainty": uncertainty,
        "status": "open",
        "generated_by_activity_id": short_id("act", dedupe),
        "generator_name": GENERATOR_NAME,
        "generator_version": GENERATOR_VERSION,
        "created_at": created_at,
        "updated_at": created_at,
    }
    task_payload = {
        "seed_evidence_ids": [evidence_id],
        "topic_label_id": topic_label_id,
        "suggested_actions": suggested_actions(signal_type, evidence),
        "canonical_url": evidence.get("canonical_url") or "",
    }
    task = {
        "task_id": task_id,
        "question_id": question_id,
        "task_type": task_type,
        "task_payload_json": json.dumps(task_payload, ensure_ascii=False, sort_keys=True),
        "seed_evidence_ids": [evidence_id],
        "seed_entity_ids": seed_entities,
        "priority": priority,
        "budget_json": json.dumps({"max_collector_steps": 6, "max_runtime_minutes": 20}, sort_keys=True),
        "dedupe_key": dedupe,
        "ttl_until": None,
        "status": "open",
        "rationale": rationale,
        "created_at": created_at,
        "updated_at": created_at,
    }
    return {"signal": signal, "question": research_question, "task": task}


def source_strength(source_kind: Any, labels: list[str]) -> float:
    kind = str(source_kind or "")
    if "quality.direct_web_capture" in labels or kind in {"web_page", "x_post", "x_account"}:
        return 0.75
    if kind == "search_result":
        return 0.45
    if "quality.user_supplied" in labels:
        return 0.65
    return 0.55


def suggested_actions(signal_type: str, evidence: dict[str, Any]) -> list[str]:
    actions = {
        "user_seed": ["search_web", "search_x_recent", "open_seed_links", "summarize_findings"],
        "comparison_opportunity": ["search_benchmarks", "open_primary_sources", "extract_metrics", "compare_claims"],
        "verification_needed": ["open_primary_sources", "search_release_posts", "check_docs_or_model_card"],
        "source_expansion": ["open_seed_links", "search_web", "search_x_recent"],
    }
    out = list(actions.get(signal_type, ["review_evidence"]))
    if evidence.get("source_kind") == "search_result":
        out.insert(0, "open_search_result")
    return out


def build_outputs(evidence_rows: list[dict[str, Any]], annotations_by_evidence: dict[str, list[dict[str, Any]]]) -> list[dict[str, dict[str, Any]]]:
    outputs = []
    for evidence in evidence_rows:
        evidence_id = str(evidence.get("evidence_id") or "")
        candidate = classify_candidate(evidence, annotations_by_evidence.get(evidence_id, []))
        if candidate:
            outputs.append(candidate)
    return outputs


def run_once(cfg: Config, stats: Stats) -> dict[str, int]:
    evidence_rows = recent_evidence(cfg)
    annotations = recent_annotations(cfg)
    outputs = build_outputs(evidence_rows, annotations)

    signal_rows = [item["signal"] for item in outputs]
    question_rows = [item["question"] for item in outputs]
    task_rows = [item["task"] for item in outputs]

    existing_signals = existing_ids(cfg, "research_signals", "signal_id", [row["signal_id"] for row in signal_rows])
    existing_questions = existing_ids(cfg, "research_questions", "question_id", [row["question_id"] for row in question_rows])
    existing_tasks = existing_ids(cfg, "autonomous_tasks", "task_id", [row["task_id"] for row in task_rows])

    new_signals = [row for row in signal_rows if row["signal_id"] not in existing_signals]
    new_questions = [row for row in question_rows if row["question_id"] not in existing_questions]
    new_tasks = [row for row in task_rows if row["task_id"] not in existing_tasks]

    for row in new_signals:
        post_redpanda(cfg, SIGNAL_TOPIC, row["signal_id"], {"schema_version": "v1", **row})
    for row in new_questions:
        post_redpanda(cfg, QUESTION_TOPIC, row["question_id"], {"schema_version": "v1", **row})
    for row in new_tasks:
        post_redpanda(cfg, TASK_TOPIC, row["task_id"], {"schema_version": "v1", **row})

    ch_insert(cfg, "research_signals", new_signals)
    ch_insert(cfg, "research_questions", new_questions)
    ch_insert(cfg, "autonomous_tasks", new_tasks)

    result = {
        "candidates_seen": len(outputs),
        "signals_created": len(new_signals),
        "questions_created": len(new_questions),
        "tasks_created": len(new_tasks),
    }
    stats.update(
        runs=1,
        last_run_at=now_iso(),
        last_error="",
        **result,
    )
    return result


def serve_http(addr: str, stats: Stats) -> None:
    host, _, raw_port = addr.rpartition(":")
    if not raw_port:
        host, raw_port = "0.0.0.0", addr
    host = host or "0.0.0.0"
    port = int(raw_port)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/healthz":
                self.send_json({"ok": True})
                return
            if self.path == "/stats":
                self.send_json(stats.snapshot())
                return
            self.send_error(404)

        def send_json(self, value: dict[str, Any]) -> None:
            payload = json.dumps(value, indent=2).encode("utf-8") + b"\n"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, fmt: str, *args: Any) -> None:
            return

    ThreadingHTTPServer((host, port), Handler).serve_forever()


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Web OSINT research signals, questions, and tasks from semantic annotations.")
    parser.add_argument("--once", action="store_true", help="Run one planner pass and exit.")
    args = parser.parse_args()

    cfg = Config()
    stats = Stats()
    if not args.once:
        thread = threading.Thread(target=serve_http, args=(cfg.http_addr, stats), daemon=True)
        thread.start()

    while True:
        try:
            result = run_once(cfg, stats)
            print(json.dumps({"ok": True, **result}, sort_keys=True), flush=True)
        except Exception as exc:
            stats.update(failed=1, last_error=str(exc), last_run_at=now_iso())
            print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True), flush=True)
            if args.once:
                return 1
        if args.once:
            return 0
        time.sleep(max(5, cfg.interval_seconds))


if __name__ == "__main__":
    raise SystemExit(main())
