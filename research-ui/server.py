#!/usr/bin/env python3
import base64
from datetime import datetime, timezone
import json
import mimetypes
import os
import posixpath
import uuid
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"

CLICKHOUSE_URL = os.environ.get("CLICKHOUSE_URL", "http://127.0.0.1:18123").rstrip("/")
CLICKHOUSE_DB = os.environ.get("CLICKHOUSE_DATABASE", "web_osint")
CLICKHOUSE_USER = os.environ.get("CLICKHOUSE_USER", "web_osint")
CLICKHOUSE_PASSWORD = os.environ.get("CLICKHOUSE_PASSWORD", "")
DATA_ROOT = Path(os.environ.get("WEB_OSINT_DATA_ROOT", "/mnt/data/web-osint-platform")).resolve()
MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", str(DATA_ROOT / "media"))).resolve()
OCR_ROOT = Path(os.environ.get("OCR_ROOT", str(DATA_ROOT / "ocr"))).resolve()
WEB_ROOT = Path(os.environ.get("WEB_ROOT", str(DATA_ROOT / "web"))).resolve()
DERIVED_ROOT = Path(os.environ.get("DERIVED_ROOT", str(DATA_ROOT / "derived"))).resolve()
REVIEW_ROOT = Path(os.environ.get("REVIEW_ROOT", str(DATA_ROOT / "review"))).resolve()
REVIEW_ACTOR = os.environ.get("REVIEW_ACTOR", "web-osint-user")

MAX_LIMIT = 200
MAX_JSON_BODY_BYTES = 1_000_000
MAX_ARTIFACT_PREVIEW_BYTES = 2_000_000
SAFE_SQL_PREFIXES = ("select", "with", "show", "describe", "desc")


class ResearchUiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, indent=2, default=str).encode("utf-8")


def sql_string(value):
    return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"


def sql_int(value, default, min_value=1, max_value=MAX_LIMIT):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(min_value, min(max_value, parsed))


def ch_request(query, body=None, default_format="JSON", timeout=25):
    params = {
        "database": CLICKHOUSE_DB,
        "query": query,
        "date_time_output_format": "iso",
    }
    if default_format:
        params["default_format"] = default_format
    data = body.encode("utf-8") if isinstance(body, str) else body
    request = urllib.request.Request(
        CLICKHOUSE_URL + "/?" + urllib.parse.urlencode(params),
        data=data,
        method="POST",
    )
    if CLICKHOUSE_PASSWORD:
        token = base64.b64encode(f"{CLICKHOUSE_USER}:{CLICKHOUSE_PASSWORD}".encode()).decode()
        request.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:2000]
        raise ResearchUiError(502, f"ClickHouse error {exc.code}: {detail}")
    except Exception as exc:
        raise ResearchUiError(502, f"ClickHouse request failed: {exc}")


def ch_query(query):
    compact = " ".join(query.strip().split())
    if not compact.lower().startswith(SAFE_SQL_PREFIXES):
        raise ResearchUiError(400, "Only read-only ClickHouse queries are allowed")
    return json.loads(ch_request(query))


def ch_execute(query):
    return ch_request(query, default_format=None, timeout=30)


def ch_insert_json_each_row(table, rows):
    if not rows:
        return
    body = "\n".join(json.dumps(row, ensure_ascii=False, default=str) for row in rows) + "\n"
    ch_request(f"INSERT INTO {table} FORMAT JSONEachRow", body=body, default_format=None, timeout=30)


def ch_data(query, fallback=None):
    try:
        return ch_query(query).get("data", [])
    except ResearchUiError:
        if fallback is None:
            raise
        return fallback


def parse_raw_json(value):
    if not value:
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {"value": parsed}
    except Exception:
        return {"_parse_error": True, "raw": value[:5000]}


def extract_paths(raw):
    paths = []
    if not isinstance(raw, dict):
        return paths
    keys = (
        "local_path",
        "screenshot_path",
        "json_artifact_path",
        "text_artifact_path",
        "html_artifact_path",
        "markdown_artifact_path",
        "rendered_dom_path",
    )
    for key in keys:
        value = raw.get(key)
        if isinstance(value, str) and value:
            paths.append(value)
    for key in ("ocr_artifact_paths", "artifact_paths", "asset_paths", "paths"):
        value = raw.get(key)
        if isinstance(value, list):
            paths.extend([item for item in value if isinstance(item, str) and item])
    nested = raw.get("raw")
    if isinstance(nested, dict):
        for path in extract_paths(nested):
            if path not in paths:
                paths.append(path)
    return paths


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def make_id(prefix):
    return f"{prefix}/{uuid.uuid4().hex}"


def json_text(value):
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True, default=str)


def compact_text(value, limit=20000):
    text = str(value or "").strip()
    return text[:limit]


def artifact_url(path):
    return "/api/artifact?" + urllib.parse.urlencode({"path": path})


def ensure_review_tables():
    ddl = [
        """
        CREATE TABLE IF NOT EXISTS research_review_events
        (
            event_id String,
            schema_version LowCardinality(String),
            event_type LowCardinality(String),
            project String,
            source_evidence_id String,
            subject_type LowCardinality(String),
            subject_id String,
            actor String,
            created_at DateTime64(3, 'UTC'),
            payload_json String,
            source_anchor_json String,
            idempotency_key String,
            inserted_at DateTime64(3, 'UTC') DEFAULT now64(3)
        )
        ENGINE = MergeTree
        PARTITION BY toYYYYMM(created_at)
        ORDER BY (source_evidence_id, created_at, event_id)
        """,
        """
        CREATE TABLE IF NOT EXISTS evidence_selections
        (
            selection_id String,
            source_evidence_id String,
            document_id String,
            block_id String,
            selection_kind LowCardinality(String),
            quote String,
            context_before String,
            context_after String,
            source_anchor_json String,
            note String,
            status LowCardinality(String),
            actor String,
            created_at DateTime64(3, 'UTC'),
            updated_at DateTime64(3, 'UTC')
        )
        ENGINE = ReplacingMergeTree(updated_at)
        PARTITION BY toYYYYMM(created_at)
        ORDER BY (source_evidence_id, selection_id)
        """,
        """
        CREATE TABLE IF NOT EXISTS review_annotations
        (
            annotation_id String,
            source_evidence_id String,
            evidence_selection_id String,
            annotation_type LowCardinality(String),
            body String,
            status LowCardinality(String),
            source_anchor_json String,
            actor String,
            created_at DateTime64(3, 'UTC'),
            updated_at DateTime64(3, 'UTC')
        )
        ENGINE = ReplacingMergeTree(updated_at)
        PARTITION BY toYYYYMM(created_at)
        ORDER BY (source_evidence_id, annotation_id)
        """,
        """
        CREATE TABLE IF NOT EXISTS proposed_facts
        (
            proposed_fact_id String,
            source_evidence_id String,
            evidence_selection_id String,
            fact_type LowCardinality(String),
            field_path String,
            raw_value String,
            normalized_value String,
            unit String,
            entities_json String,
            evidence_quote String,
            source_anchor_json String,
            status LowCardinality(String),
            note String,
            actor String,
            created_at DateTime64(3, 'UTC'),
            updated_at DateTime64(3, 'UTC')
        )
        ENGINE = ReplacingMergeTree(updated_at)
        PARTITION BY toYYYYMM(created_at)
        ORDER BY (source_evidence_id, proposed_fact_id)
        """,
    ]
    for query in ddl:
        ch_execute(query)


def source_kind_label(kind):
    labels = {
        "x_post": "X post",
        "x_account": "X account",
        "x_page": "X page",
        "web_page": "Web/blog",
        "search_result": "Search result",
        "google_search_page": "Google SERP",
        "media": "Media",
        "user_input": "Manual doc",
        "capture": "Capture",
    }
    return labels.get(kind or "", kind or "unknown")


def inbox(params):
    limit = sql_int(params.get("limit", ["80"])[0], 80)
    q = (params.get("q", [""])[0] or "").strip()
    kind = (params.get("kind", [""])[0] or "").strip()
    project = (params.get("project", [""])[0] or "").strip()
    queue = (params.get("queue", ["all"])[0] or "all").strip()

    clauses = ["1 = 1"]
    if q:
        like = sql_string(q)
        clauses.append(
            "("
            f"positionCaseInsensitive(evidence_events.title, {like}) > 0 OR "
            f"positionCaseInsensitive(evidence_events.text, {like}) > 0 OR "
            f"positionCaseInsensitive(evidence_events.canonical_url, {like}) > 0 OR "
            f"positionCaseInsensitive(evidence_events.author_handle, {like}) > 0 OR "
            f"positionCaseInsensitive(evidence_events.domain, {like}) > 0 OR "
            f"positionCaseInsensitive(evidence_events.evidence_id, {like}) > 0"
            ")"
        )
    if kind:
        clauses.append(f"evidence_events.source_kind = {sql_string(kind)}")
    if project:
        clauses.append(f"evidence_events.source_project = {sql_string(project)}")
    if queue == "needs_review":
        clauses.append("(evidence_events.has_ocr = 0 OR length(evidence_events.text) < 120 OR evidence_events.source_kind IN ('media', 'capture'))")
    elif queue == "x_sources":
        clauses.append("evidence_events.source_kind IN ('x_post', 'x_account', 'x_page', 'media')")
    elif queue == "web_sources":
        clauses.append("evidence_events.source_kind IN ('web_page', 'search_result', 'google_search_page')")
    elif queue == "manual_docs":
        clauses.append("evidence_events.source_kind = 'user_input'")

    where = " AND ".join(clauses)
    rows = ch_data(
        f"""
        SELECT
          evidence_id,
          argMax(source_kind, ingested_at) AS source_kind,
          argMax(source_project, ingested_at) AS source_project,
          argMax(capture_method, ingested_at) AS capture_method,
          argMax(canonical_url, ingested_at) AS canonical_url,
          argMax(author_handle, ingested_at) AS author_handle,
          argMax(domain, ingested_at) AS domain,
          argMax(title, ingested_at) AS title,
          substring(argMax(text, ingested_at), 1, 600) AS snippet,
          length(argMax(text, ingested_at)) AS text_chars,
          argMax(topics, ingested_at) AS topics,
          argMax(entities, ingested_at) AS entities,
          max(has_media) AS has_media,
          max(has_ocr) AS has_ocr,
          min(captured_at) AS first_captured_at,
          max(captured_at) AS last_captured_at,
          max(ingested_at) AS last_ingested_at,
          count() AS observations
        FROM evidence_events
        WHERE {where}
        GROUP BY evidence_id
        ORDER BY last_ingested_at DESC
        LIMIT {limit}
        """
    )
    for row in rows:
        row["source_label"] = source_kind_label(row.get("source_kind"))
        row["review_hint"] = review_hint(row)
    return {"rows": rows, "limit": limit, "queue": queue}


def review_hint(row):
    if row.get("source_kind") == "media" and not row.get("has_ocr"):
        return "Needs OCR/VL review"
    if int(row.get("text_chars") or 0) == 0:
        return "Extraction empty"
    if int(row.get("observations") or 0) > 1:
        return "Multiple captures"
    if row.get("source_kind") in ("x_post", "web_page", "user_input"):
        return "Ready for evidence selection"
    return "Triage"


def facets():
    source_kinds = ch_data(
        """
        SELECT source_kind, count() AS rows, max(ingested_at) AS last_seen
        FROM evidence_events
        GROUP BY source_kind
        ORDER BY rows DESC, source_kind ASC
        """
    )
    projects = ch_data(
        """
        SELECT source_project, count() AS rows, max(ingested_at) AS last_seen
        FROM evidence_events
        GROUP BY source_project
        ORDER BY rows DESC, source_project ASC
        LIMIT 100
        """
    )
    domains = ch_data(
        """
        SELECT domain, count() AS rows, max(ingested_at) AS last_seen
        FROM evidence_events
        WHERE domain != ''
        GROUP BY domain
        ORDER BY rows DESC, domain ASC
        LIMIT 100
        """
    )
    totals = ch_data(
        """
        SELECT
          count() AS evidence_rows,
          uniqExact(evidence_id) AS unique_evidence,
          countIf(source_kind = 'x_post') AS x_posts,
          countIf(source_kind = 'x_account') AS x_accounts,
          countIf(source_kind = 'web_page') AS web_pages,
          countIf(source_kind = 'media') AS media_rows,
          max(ingested_at) AS last_ingested_at
        FROM evidence_events
        """
    )[0]
    queues = [
        {"id": "all", "label": "All inbox"},
        {"id": "needs_review", "label": "Needs review"},
        {"id": "x_sources", "label": "X sources"},
        {"id": "web_sources", "label": "Web/blog"},
        {"id": "manual_docs", "label": "Manual docs"},
    ]
    return {"totals": totals, "source_kinds": source_kinds, "projects": projects, "domains": domains, "queues": queues}


def review_state_for_source(evidence_id):
    quoted = sql_string(evidence_id)
    selections = ch_data(
        f"""
        SELECT
          selection_id, source_evidence_id, document_id, block_id, selection_kind,
          quote, context_before, context_after, source_anchor_json, note, status,
          actor, created_at, updated_at
        FROM evidence_selections FINAL
        WHERE source_evidence_id = {quoted}
        ORDER BY updated_at DESC, created_at DESC
        LIMIT 200
        """,
        fallback=[],
    )
    annotations = ch_data(
        f"""
        SELECT
          annotation_id, source_evidence_id, evidence_selection_id, annotation_type,
          body, status, source_anchor_json, actor, created_at, updated_at
        FROM review_annotations FINAL
        WHERE source_evidence_id = {quoted}
        ORDER BY updated_at DESC, created_at DESC
        LIMIT 200
        """,
        fallback=[],
    )
    proposed_facts = ch_data(
        f"""
        SELECT
          proposed_fact_id, source_evidence_id, evidence_selection_id, fact_type,
          field_path, raw_value, normalized_value, unit, entities_json, evidence_quote,
          source_anchor_json, status, note, actor, created_at, updated_at
        FROM proposed_facts FINAL
        WHERE source_evidence_id = {quoted}
        ORDER BY updated_at DESC, created_at DESC
        LIMIT 200
        """,
        fallback=[],
    )
    events = ch_data(
        f"""
        SELECT
          event_id, event_type, project, source_evidence_id, subject_type, subject_id,
          actor, created_at, payload_json, source_anchor_json, idempotency_key
        FROM research_review_events
        WHERE source_evidence_id = {quoted}
        ORDER BY created_at DESC
        LIMIT 200
        """,
        fallback=[],
    )
    return {
        "selections": selections,
        "annotations": annotations,
        "proposed_facts": proposed_facts,
        "events": events,
        "counts": {
            "selections": len(selections),
            "annotations": len(annotations),
            "proposed_facts": len(proposed_facts),
            "events": len(events),
        },
    }


def source_detail(params):
    evidence_id = (params.get("id", [""])[0] or "").strip()
    if not evidence_id:
        raise ResearchUiError(400, "Missing source id")
    quoted = sql_string(evidence_id)
    observations = ch_data(
        f"""
        SELECT
          event_id, schema_version, collector_run_id, source_project, capture_method,
          source_kind, evidence_id, canonical_url, author_handle, domain, title, text,
          topics, entities, links, has_media, has_ocr, posted_at, captured_at, ingested_at,
          raw_json
        FROM evidence_events
        WHERE evidence_id = {quoted}
        ORDER BY ingested_at DESC
        LIMIT 20
        """
    )
    if not observations:
        raise ResearchUiError(404, "Source not found")
    latest = observations[0]
    raw = parse_raw_json(latest.get("raw_json", ""))
    latest["raw"] = raw
    latest["artifact_paths"] = [{"path": path, "url": artifact_url(path)} for path in extract_paths(raw)]

    related_clauses = []
    if latest.get("canonical_url"):
        related_clauses.append(f"canonical_url = {sql_string(latest['canonical_url'])}")
    if latest.get("author_handle"):
        related_clauses.append(f"author_handle = {sql_string(latest['author_handle'])}")
    if latest.get("domain"):
        related_clauses.append(f"domain = {sql_string(latest['domain'])}")
    related = []
    if related_clauses:
        related = ch_data(
            f"""
            SELECT
              evidence_id,
              argMax(source_kind, ingested_at) AS source_kind,
              argMax(title, ingested_at) AS title,
              argMax(canonical_url, ingested_at) AS canonical_url,
              argMax(author_handle, ingested_at) AS author_handle,
              argMax(domain, ingested_at) AS domain,
              length(argMax(text, ingested_at)) AS text_chars,
              max(ingested_at) AS last_ingested_at
            FROM evidence_events
            WHERE evidence_id != {quoted} AND ({" OR ".join(related_clauses)})
            GROUP BY evidence_id
            ORDER BY last_ingested_at DESC
            LIMIT 50
            """,
            fallback=[],
        )
        for row in related:
            row["source_label"] = source_kind_label(row.get("source_kind"))

    annotations = ch_data(
        f"""
        SELECT
          annotation_id, annotation_family, label_id, status, confidence,
          span_text, substring(value_json, 1, 2000) AS value_json, created_at
        FROM semantic_annotations
        WHERE evidence_id = {quoted}
        ORDER BY created_at DESC
        LIMIT 100
        """,
        fallback=[],
    )
    ocr = ch_data(
        f"""
        SELECT
          ocr_id, status, engine, engine_version, artifact_role, text_chars,
          block_count, mean_confidence, json_artifact_path, text_artifact_path, created_at
        FROM media_ocr_results
        WHERE evidence_id = {quoted}
        ORDER BY created_at DESC
        LIMIT 50
        """,
        fallback=[],
    )
    for row in ocr:
        for key in ("json_artifact_path", "text_artifact_path"):
            if row.get(key):
                row[key + "_url"] = artifact_url(row[key])
    vl = ch_data(
        f"""
        SELECT
          vl_embedding_id, status, model, model_version, vector_name,
          qdrant_collection, qdrant_point_id, image_width, image_height, created_at
        FROM media_vl_embeddings
        WHERE evidence_id = {quoted}
        ORDER BY created_at DESC
        LIMIT 50
        """,
        fallback=[],
    )
    return {
        "latest": latest,
        "observations": observations,
        "related": related,
        "annotations": annotations,
        "ocr": ocr,
        "vl": vl,
        "review": review_state_for_source(evidence_id),
    }


def append_review_jsonl(event):
    day = event["created_at"][:10].replace("-", "")
    directory = REVIEW_ROOT / "events"
    path = directory / f"{day}.jsonl"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True, default=str) + "\n")
        return {"ok": True, "path": str(path)}
    except Exception as exc:
        print(f"review jsonl append failed: {exc}", flush=True)
        return {"ok": False, "error": str(exc), "path": str(path)}


def build_review_event(event_type, payload):
    source_evidence_id = compact_text(payload.get("source_evidence_id"), 1000)
    if not source_evidence_id:
        raise ResearchUiError(400, "source_evidence_id is required")
    created_at = now_iso()
    subject_type = compact_text(payload.get("subject_type") or event_type.split(".")[0], 80)
    subject_id = compact_text(payload.get("subject_id") or payload.get("selection_id") or payload.get("annotation_id") or payload.get("proposed_fact_id"), 300)
    source_anchor = payload.get("source_anchor") or {}
    event = {
        "event_id": make_id("review_event"),
        "schema_version": "research_review_event.v1",
        "event_type": event_type,
        "project": compact_text(payload.get("project") or payload.get("source_project") or "", 200),
        "source_evidence_id": source_evidence_id,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "actor": compact_text(payload.get("actor") or REVIEW_ACTOR, 200),
        "created_at": created_at,
        "payload": payload,
        "source_anchor": source_anchor,
        "payload_json": json_text(payload),
        "source_anchor_json": json_text(source_anchor),
        "idempotency_key": compact_text(payload.get("idempotency_key") or "", 500),
    }
    return event


def persist_review_event(event):
    ch_insert_json_each_row("research_review_events", [{
        "event_id": event["event_id"],
        "schema_version": event["schema_version"],
        "event_type": event["event_type"],
        "project": event["project"],
        "source_evidence_id": event["source_evidence_id"],
        "subject_type": event["subject_type"],
        "subject_id": event["subject_id"],
        "actor": event["actor"],
        "created_at": event["created_at"],
        "payload_json": event["payload_json"],
        "source_anchor_json": event["source_anchor_json"],
        "idempotency_key": event["idempotency_key"],
    }])
    event["jsonl"] = append_review_jsonl(event)
    return event


def create_evidence_selection(payload):
    selection_id = compact_text(payload.get("selection_id"), 300) or make_id("selection")
    now = now_iso()
    normalized = {
        **payload,
        "selection_id": selection_id,
        "subject_type": "evidence_selection",
        "subject_id": selection_id,
        "selection_kind": compact_text(payload.get("selection_kind") or "text", 80),
        "status": compact_text(payload.get("status") or "selected", 80),
        "quote": compact_text(payload.get("quote"), 50000),
        "context_before": compact_text(payload.get("context_before"), 10000),
        "context_after": compact_text(payload.get("context_after"), 10000),
        "note": compact_text(payload.get("note"), 20000),
        "created_at": payload.get("created_at") or now,
        "updated_at": now,
    }
    event = persist_review_event(build_review_event("evidence_selection.created", normalized))
    ch_insert_json_each_row("evidence_selections", [{
        "selection_id": selection_id,
        "source_evidence_id": normalized["source_evidence_id"],
        "document_id": compact_text(normalized.get("document_id"), 500),
        "block_id": compact_text(normalized.get("block_id"), 500),
        "selection_kind": normalized["selection_kind"],
        "quote": normalized["quote"],
        "context_before": normalized["context_before"],
        "context_after": normalized["context_after"],
        "source_anchor_json": json_text(normalized.get("source_anchor")),
        "note": normalized["note"],
        "status": normalized["status"],
        "actor": compact_text(normalized.get("actor") or REVIEW_ACTOR, 200),
        "created_at": normalized["created_at"],
        "updated_at": normalized["updated_at"],
    }])
    return {"event": event, "selection": normalized}


def create_review_annotation(payload):
    annotation_id = compact_text(payload.get("annotation_id"), 300) or make_id("annotation")
    body = compact_text(payload.get("body"), 50000)
    if not body:
        raise ResearchUiError(400, "body is required")
    now = now_iso()
    normalized = {
        **payload,
        "annotation_id": annotation_id,
        "subject_type": "annotation",
        "subject_id": annotation_id,
        "annotation_type": compact_text(payload.get("annotation_type") or "note", 80),
        "status": compact_text(payload.get("status") or "open", 80),
        "body": body,
        "created_at": payload.get("created_at") or now,
        "updated_at": now,
    }
    event = persist_review_event(build_review_event("annotation.created", normalized))
    ch_insert_json_each_row("review_annotations", [{
        "annotation_id": annotation_id,
        "source_evidence_id": normalized["source_evidence_id"],
        "evidence_selection_id": compact_text(normalized.get("evidence_selection_id"), 300),
        "annotation_type": normalized["annotation_type"],
        "body": normalized["body"],
        "status": normalized["status"],
        "source_anchor_json": json_text(normalized.get("source_anchor")),
        "actor": compact_text(normalized.get("actor") or REVIEW_ACTOR, 200),
        "created_at": normalized["created_at"],
        "updated_at": normalized["updated_at"],
    }])
    return {"event": event, "annotation": normalized}


def create_proposed_fact(payload):
    proposed_fact_id = compact_text(payload.get("proposed_fact_id"), 300) or make_id("proposed_fact")
    fact_type = compact_text(payload.get("fact_type") or "general", 120)
    raw_value = compact_text(payload.get("raw_value"), 50000)
    normalized_value = compact_text(payload.get("normalized_value"), 50000)
    if not raw_value and not normalized_value:
        raise ResearchUiError(400, "raw_value or normalized_value is required")
    now = now_iso()
    normalized = {
        **payload,
        "proposed_fact_id": proposed_fact_id,
        "subject_type": "proposed_fact",
        "subject_id": proposed_fact_id,
        "fact_type": fact_type,
        "field_path": compact_text(payload.get("field_path"), 500),
        "raw_value": raw_value,
        "normalized_value": normalized_value,
        "unit": compact_text(payload.get("unit"), 120),
        "evidence_quote": compact_text(payload.get("evidence_quote") or payload.get("quote"), 50000),
        "status": compact_text(payload.get("status") or "proposed", 80),
        "note": compact_text(payload.get("note"), 20000),
        "created_at": payload.get("created_at") or now,
        "updated_at": now,
    }
    event = persist_review_event(build_review_event("proposed_fact.created", normalized))
    ch_insert_json_each_row("proposed_facts", [{
        "proposed_fact_id": proposed_fact_id,
        "source_evidence_id": normalized["source_evidence_id"],
        "evidence_selection_id": compact_text(normalized.get("evidence_selection_id"), 300),
        "fact_type": normalized["fact_type"],
        "field_path": normalized["field_path"],
        "raw_value": normalized["raw_value"],
        "normalized_value": normalized["normalized_value"],
        "unit": normalized["unit"],
        "entities_json": json_text(normalized.get("entities") or []),
        "evidence_quote": normalized["evidence_quote"],
        "source_anchor_json": json_text(normalized.get("source_anchor")),
        "status": normalized["status"],
        "note": normalized["note"],
        "actor": compact_text(normalized.get("actor") or REVIEW_ACTOR, 200),
        "created_at": normalized["created_at"],
        "updated_at": normalized["updated_at"],
    }])
    return {"event": event, "proposed_fact": normalized}


def create_generic_review_event(payload):
    event_type = compact_text(payload.get("event_type"), 160)
    if not event_type:
        raise ResearchUiError(400, "event_type is required")
    event = persist_review_event(build_review_event(event_type, payload))
    return {"event": event}


def safe_artifact(path_value):
    if not path_value:
        raise ResearchUiError(400, "Missing artifact path")
    path = Path(path_value).expanduser().resolve()
    allowed_roots = [DATA_ROOT, MEDIA_ROOT, OCR_ROOT, WEB_ROOT, DERIVED_ROOT]
    if not any(path == root or root in path.parents for root in allowed_roots):
        raise ResearchUiError(403, "Artifact path is outside Web OSINT data roots")
    if not path.exists() or not path.is_file():
        raise ResearchUiError(404, "Artifact not found")
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if content_type.startswith("image/"):
        return {"mode": "binary", "path": path, "content_type": content_type}
    data = path.read_bytes()[:MAX_ARTIFACT_PREVIEW_BYTES]
    return {
        "mode": "text",
        "path": str(path),
        "content_type": "text/plain; charset=utf-8",
        "body": data.decode("utf-8", errors="replace"),
        "truncated": path.stat().st_size > len(data),
    }


class ResearchUiHandler(BaseHTTPRequestHandler):
    server_version = "WebOSINTResearchUI/0.1"

    def log_message(self, fmt, *args):
        print(f"{self.address_string()} - {fmt % args}", flush=True)

    def send_json(self, value, status=200):
        body = json_bytes(value)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_text(self, text, content_type="text/plain; charset=utf-8", status=200):
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_static(self, rel_path):
        clean = posixpath.normpath(urllib.parse.unquote(rel_path)).lstrip("/")
        path = STATIC_DIR / clean
        if not path.exists() or not path.is_file():
            raise ResearchUiError(404, "Static file not found")
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_artifact(self, artifact):
        if artifact["mode"] == "binary":
            data = artifact["path"].read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", artifact["content_type"])
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_text(artifact["body"], artifact["content_type"])

    def read_json_body(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ResearchUiError(400, "Invalid Content-Length")
        if length <= 0:
            raise ResearchUiError(400, "Missing JSON body")
        if length > MAX_JSON_BODY_BYTES:
            raise ResearchUiError(413, "JSON body is too large")
        raw = self.rfile.read(length).decode("utf-8")
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ResearchUiError(400, f"Invalid JSON: {exc}")
        if not isinstance(value, dict):
            raise ResearchUiError(400, "JSON body must be an object")
        return value

    def do_HEAD(self):
        if urllib.parse.urlparse(self.path).path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            return
        self.send_response(404)
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        try:
            if parsed.path == "/":
                return self.send_static("index.html")
            if parsed.path == "/healthz":
                return self.send_json({"ok": True, "service": "research-ui"})
            if parsed.path == "/api/facets":
                return self.send_json(facets())
            if parsed.path == "/api/inbox":
                return self.send_json(inbox(params))
            if parsed.path == "/api/source":
                return self.send_json(source_detail(params))
            if parsed.path == "/api/source/review":
                evidence_id = (params.get("id", [""])[0] or "").strip()
                if not evidence_id:
                    raise ResearchUiError(400, "Missing source id")
                return self.send_json(review_state_for_source(evidence_id))
            if parsed.path == "/api/artifact":
                return self.send_artifact(safe_artifact(params.get("path", [""])[0]))
            if parsed.path.startswith("/static/"):
                return self.send_static(parsed.path.removeprefix("/static/"))
            if parsed.path in ("/styles.css", "/app.js"):
                return self.send_static(parsed.path.lstrip("/"))
            raise ResearchUiError(404, "Not found")
        except ResearchUiError as exc:
            self.send_json({"error": exc.message}, status=exc.status)
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=500)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        try:
            ensure_review_tables()
            payload = self.read_json_body()
            if parsed.path == "/api/review/events":
                return self.send_json(create_generic_review_event(payload), status=201)
            if parsed.path == "/api/evidence/selections":
                return self.send_json(create_evidence_selection(payload), status=201)
            if parsed.path == "/api/annotations":
                return self.send_json(create_review_annotation(payload), status=201)
            if parsed.path == "/api/proposed-facts":
                return self.send_json(create_proposed_fact(payload), status=201)
            raise ResearchUiError(404, "Not found")
        except ResearchUiError as exc:
            self.send_json({"error": exc.message}, status=exc.status)
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=500)


def main():
    host = os.environ.get("RESEARCH_UI_HOST", "127.0.0.1")
    port = int(os.environ.get("RESEARCH_UI_PORT", "18192"))
    try:
        ensure_review_tables()
    except Exception as exc:
        print(f"Review table initialization warning: {exc}", flush=True)
    server = ThreadingHTTPServer((host, port), ResearchUiHandler)
    print(f"Web OSINT Research UI listening on http://{host}:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
