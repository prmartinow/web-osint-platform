#!/usr/bin/env python3
import base64
from datetime import datetime, timezone
import hashlib
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

def require_env(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"Missing {name}")
    return value


CLICKHOUSE_URL = require_env("CLICKHOUSE_URL").rstrip("/")
CLICKHOUSE_DB = os.environ.get("CLICKHOUSE_DATABASE", "web_osint")
CLICKHOUSE_USER = os.environ.get("CLICKHOUSE_USER", "web_osint")
CLICKHOUSE_PASSWORD = os.environ.get("CLICKHOUSE_PASSWORD", "")
DATA_ROOT = Path(os.environ.get("WEB_OSINT_DATA_ROOT", str(APP_DIR / "data"))).resolve()
MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", str(DATA_ROOT / "media"))).resolve()
OCR_ROOT = Path(os.environ.get("OCR_ROOT", str(DATA_ROOT / "ocr"))).resolve()
WEB_ROOT = Path(os.environ.get("WEB_ROOT", str(DATA_ROOT / "web"))).resolve()
DERIVED_ROOT = Path(os.environ.get("DERIVED_ROOT", str(DATA_ROOT / "derived"))).resolve()
REVIEW_ROOT = Path(os.environ.get("REVIEW_ROOT", str(DATA_ROOT / "review"))).resolve()
PROJECT_BRIEF_ROOT = REVIEW_ROOT / "project_briefs"
REVIEW_ACTOR = os.environ.get("REVIEW_ACTOR", "web-osint-user")
REBROWSER_LAUNCH_URL = os.environ.get("REBROWSER_LAUNCH_URL", "").strip()

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


def cursor_page(rows, total, limit, order_key=""):
    """CursorPage<T> (spec §28): {items, next_cursor?, total_estimate}.

    next_cursor is an opaque keyset token (limit + sort key of the last emitted
    item); absent on the final page so the UI knows when to stop fetching.
    total_estimate is a bounded count of the full result set. A present
    next_cursor means more rows match on the server (spec §7: no silent trunc).
    """
    items = list(rows[:limit])
    next_cursor = None
    # next_cursor is present iff the server holds more matching rows than we
    # emitted on this page (total_estimate > items length). Deciding from the
    # total — not len(rows) — keeps the helper correct whether or not the
    # caller pre-sliced `rows` to the page.
    if items and int(total or 0) > len(items):
        anchor_value = ""
        if order_key and isinstance(items[-1], dict):
            anchor_value = str(items[-1].get(order_key) or "")
        token = {"l": int(limit), "k": anchor_value}
        padded = json.dumps(token, separators=(",", ":")).encode("utf-8")
        next_cursor = base64.urlsafe_b64encode(padded).decode("ascii").rstrip("=")
    return {
        "items": items,
        "next_cursor": next_cursor,
        "total_estimate": int(total or 0),
    }


def read_envelope(data, version, generated_at, stale, permissions, **extra):
    """ReadEnvelope<T> (spec §28), stamped onto a flat page read-model dict.

    Envelope fields live at top level — the shape app.js reads today — rather
    than nesting under `data`, so this is a non-breaking contract change.
    """
    result = dict(data) if isinstance(data, dict) else {"data": data}
    result["version"] = version
    result["generated_at"] = generated_at
    result["stale"] = bool(stale)
    result["permissions"] = list(permissions or [])
    result.update(extra)
    return result


def json_text(value):
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True, default=str)


def compact_text(value, limit=20000):
    text = str(value or "").strip()
    return text[:limit]


def brief_storage_key(project_id):
    raw = project_id if project_id else "__unassigned__"
    return base64.urlsafe_b64encode(str(raw).encode("utf-8")).decode("ascii").rstrip("=")


def project_source_evidence_id(project_id):
    return f"project:{project_id or '__unassigned__'}"


def project_brief_path(project_id):
    return PROJECT_BRIEF_ROOT / f"{brief_storage_key(project_id)}.json"


def normalize_brief_list(items, key="text", limit=5000):
    if isinstance(items, str):
        items = [{"id": make_id("brief_item"), key: line.strip(), "status": "active"} for line in items.splitlines() if line.strip()]
    normalized = []
    for item in items if isinstance(items, list) else []:
        if isinstance(item, str):
            text = compact_text(item, limit)
            if text:
                normalized.append({"id": make_id("brief_item"), key: text, "status": "active"})
            continue
        if isinstance(item, dict):
            text = compact_text(item.get(key) or item.get("text") or item.get("question") or item.get("definition"), limit)
            if not text:
                continue
            normalized.append({
                **item,
                "id": compact_text(item.get("id"), 200) or make_id("brief_item"),
                key: text,
                "status": compact_text(item.get("status") or item.get("state") or "active", 80),
            })
    return normalized


def normalize_working_definitions(items):
    normalized = []
    for item in items if isinstance(items, list) else []:
        if isinstance(item, str):
            if ":" in item:
                term, definition = item.split(":", 1)
            elif " - " in item:
                term, definition = item.split(" - ", 1)
            else:
                term, definition = item, ""
            item = {"term": term, "definition": definition}
        if not isinstance(item, dict):
            continue
        term = compact_text(item.get("term"), 240)
        definition = compact_text(item.get("definition"), 10000)
        if not term and not definition:
            continue
        normalized.append({
            "id": compact_text(item.get("id"), 200) or make_id("brief_definition"),
            "term": term or "Untitled term",
            "definition": definition,
            "status": compact_text(item.get("status") or "active", 80),
        })
    return normalized


def default_project_brief(project_id, project_name, row=None):
    row = row or {}
    now = now_iso()
    return {
        "id": f"project_brief/{brief_storage_key(project_id)}",
        "project_id": project_id,
        "project_name": project_name or project_id or "(unassigned)",
        "version": "1",
        "version_counter": 1,
        "review_state": "draft",
        "research_question": row.get("question") or "Collect and validate source-linked evidence",
        "decision_supported": "Decide what is evidence-backed enough to compare, cite, curate, or publish.",
        "scope": {
            "time_window": "Current captured corpus",
            "geography": "Global",
            "population": "AI research, models, tooling, benchmarks, and infrastructure sources",
            "evidence_policy": "Prefer primary sources. Keep machine output as observations until reviewed.",
            "tags": ["web-osint", "source-linked", "human-led"],
        },
        "inclusion_criteria": [
            {"id": "include-primary-sources", "text": "Primary source posts, lab pages, docs, papers, repos, benchmark pages, and captured media.", "status": "active"},
            {"id": "include-manual-research", "text": "User-supplied research documents when they contain useful source trails or synthesized context.", "status": "active"},
            {"id": "include-discovery-provenance", "text": "Google SERPs and X discovery paths as provenance; opened pages become substantive evidence.", "status": "active"},
        ],
        "exclusion_criteria": [
            {"id": "exclude-uncited-claims", "text": "Uncited commentary that cannot be linked back to a captured source.", "status": "active"},
            {"id": "exclude-live-only", "text": "Live web state that has not been captured into the platform.", "status": "active"},
        ],
        "open_questions": [
            {"id": "question-evidence-quality", "text": "Which proposed evidence should be accepted, corrected, rejected, or linked to claims?", "status": "open", "owner": REVIEW_ACTOR},
            {"id": "question-source-diversity", "text": "Where does the project need independent corroboration or better source diversity?", "status": "open", "owner": REVIEW_ACTOR},
            {"id": "question-publication", "text": "Which claims are publication-ready, and which remain exploratory?", "status": "open", "owner": REVIEW_ACTOR},
        ],
        "working_definitions": [
            {"id": "def-capture", "term": "Capture", "definition": "An immutable observation of a source at a specific time.", "status": "active"},
            {"id": "def-observation", "term": "Observation", "definition": "Machine or parser output such as OCR, entity candidates, or proposed facts.", "status": "active"},
            {"id": "def-claim", "term": "Claim", "definition": "A human-reviewable assertion backed by one or more evidence anchors.", "status": "active"},
        ],
        "accepted_finding_ids": [],
        "limitations": [
            {"id": "limit-review-layer", "text": "Accepted findings are projections from reviewed claims, not freeform text on this brief.", "status": "active"},
            {"id": "limit-source-coverage", "text": "Coverage reflects currently captured data and may miss uncaptured source updates.", "status": "active"},
        ],
        "material_changes_since_review": 0,
        "created_at": now,
        "updated_at": now,
        "last_review_requested_at": "",
    }


def read_project_brief(project_id, project_name="", row=None):
    default = default_project_brief(project_id, project_name, row)
    path = project_brief_path(project_id)
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as handle:
            stored = json.load(handle)
    except Exception:
        return {**default, "load_warning": "stored brief could not be parsed"}
    brief = {**default, **stored}
    scope = default["scope"]
    if isinstance(stored.get("scope"), dict):
        scope = {**scope, **stored["scope"]}
    brief["scope"] = scope
    brief["inclusion_criteria"] = normalize_brief_list(brief.get("inclusion_criteria"))
    brief["exclusion_criteria"] = normalize_brief_list(brief.get("exclusion_criteria"))
    brief["open_questions"] = normalize_brief_list(brief.get("open_questions"))
    brief["working_definitions"] = normalize_working_definitions(brief.get("working_definitions"))
    brief["limitations"] = normalize_brief_list(brief.get("limitations"))
    return brief


def write_project_brief(brief):
    PROJECT_BRIEF_ROOT.mkdir(parents=True, exist_ok=True)
    path = project_brief_path(brief.get("project_id") or "")
    tmp_path = path.with_suffix(".json.tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(brief, handle, ensure_ascii=False, indent=2, sort_keys=True, default=str)
        handle.write("\n")
    tmp_path.replace(path)
    return path


def append_project_brief_audit(event):
    directory = PROJECT_BRIEF_ROOT / "audit"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{event['created_at'][:10].replace('-', '')}.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True, default=str) + "\n")
    return str(path)


def project_brief_activity(project_id, limit=8):
    events = []
    audit_dir = PROJECT_BRIEF_ROOT / "audit"
    if audit_dir.exists():
        for path in sorted(audit_dir.glob("*.jsonl"), reverse=True)[:10]:
            try:
                with path.open("r", encoding="utf-8") as handle:
                    for line in handle:
                        item = json.loads(line)
                        if item.get("project_id") == project_id:
                            events.append(item)
            except Exception:
                continue
    review_rows = ch_data(
        f"""
        SELECT event_id, event_type, actor, created_at, subject_type, subject_id
        FROM research_review_events
        WHERE source_evidence_id = {sql_string(project_source_evidence_id(project_id))}
        ORDER BY created_at DESC
        LIMIT {sql_int(limit, 8)}
        """,
        fallback=[],
    )
    for row in review_rows:
        events.append({
            "event_id": row.get("event_id"),
            "event_type": row.get("event_type"),
            "actor": row.get("actor"),
            "created_at": row.get("created_at"),
            "subject_type": row.get("subject_type"),
            "review_event": True,
        })
    events.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return events[:limit]


def normalize_brief_payload(payload, current):
    scope_payload = payload.get("scope") if isinstance(payload.get("scope"), dict) else {}
    scope = {
        **current.get("scope", {}),
        "time_window": compact_text(scope_payload.get("time_window"), 2000),
        "geography": compact_text(scope_payload.get("geography"), 2000),
        "population": compact_text(scope_payload.get("population"), 3000),
        "evidence_policy": compact_text(scope_payload.get("evidence_policy"), 5000),
        "tags": [compact_text(tag, 120) for tag in scope_payload.get("tags", []) if compact_text(tag, 120)],
    }
    return {
        **current,
        "research_question": compact_text(payload.get("research_question") or current.get("research_question"), 10000),
        "decision_supported": compact_text(payload.get("decision_supported") or current.get("decision_supported"), 10000),
        "scope": scope,
        "inclusion_criteria": normalize_brief_list(payload.get("inclusion_criteria", current.get("inclusion_criteria", []))),
        "exclusion_criteria": normalize_brief_list(payload.get("exclusion_criteria", current.get("exclusion_criteria", []))),
        "open_questions": normalize_brief_list(payload.get("open_questions", current.get("open_questions", []))),
        "working_definitions": normalize_working_definitions(payload.get("working_definitions", current.get("working_definitions", []))),
        "limitations": normalize_brief_list(payload.get("limitations", current.get("limitations", []))),
    }


def update_project_brief(payload, review_request=False):
    project_id = compact_text(payload.get("project_id"), 300)
    project_name = compact_text(payload.get("project_name"), 500) or project_id or "(unassigned)"
    current = read_project_brief(project_id, project_name)
    expected = compact_text(payload.get("expected_version"), 120)
    if expected and expected != current.get("version"):
        raise ResearchUiError(409, "Project brief changed since it was loaded")
    brief = normalize_brief_payload(payload, current)
    counter = int(brief.get("version_counter") or 1) + 1
    brief["version_counter"] = counter
    brief["version"] = str(counter)
    brief["updated_at"] = now_iso()
    brief["project_id"] = project_id
    brief["project_name"] = project_name
    if review_request:
        brief["review_state"] = "ready_for_review"
        brief["material_changes_since_review"] = 0
        brief["last_review_requested_at"] = brief["updated_at"]
    else:
        if brief.get("review_state") in ("ready_for_review", "approved"):
            brief["review_state"] = "changes_requested"
        brief["material_changes_since_review"] = int(brief.get("material_changes_since_review") or 0) + 1
    write_project_brief(brief)
    audit_event = {
        "event_id": make_id("project_brief_audit"),
        "event_type": "project_brief.review_requested" if review_request else "project_brief.updated",
        "project_id": project_id,
        "project_name": project_name,
        "brief_id": brief["id"],
        "brief_version": brief["version"],
        "actor": compact_text(payload.get("actor") or REVIEW_ACTOR, 200),
        "idempotency_key": compact_text(payload.get("idempotency_key"), 500),
        "created_at": brief["updated_at"],
    }
    audit_event["jsonl_path"] = append_project_brief_audit(audit_event)
    review_event = None
    if review_request:
        review_event = persist_review_event(build_review_event("project_brief.review_requested", {
            "source_evidence_id": project_source_evidence_id(project_id),
            "project": project_id,
            "project_name": project_name,
            "subject_type": "project_brief",
            "subject_id": brief["id"],
            "brief_version": brief["version"],
            "actor": audit_event["actor"],
            "idempotency_key": audit_event["idempotency_key"],
            "source_anchor": {"kind": "project_brief", "project_id": project_id, "version": brief["version"]},
        }))
    return {"brief": brief, "audit_event": audit_event, "review_event": review_event}


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
        """
        CREATE TABLE IF NOT EXISTS normalized_corrections
        (
            correction_id String,
            source_evidence_id String,
            document_id String,
            block_id String,
            correction_kind LowCardinality(String),
            original_text String,
            corrected_text String,
            source_anchor_json String,
            status LowCardinality(String),
            note String,
            actor String,
            created_at DateTime64(3, 'UTC'),
            updated_at DateTime64(3, 'UTC')
        )
        ENGINE = ReplacingMergeTree(updated_at)
        PARTITION BY toYYYYMM(created_at)
        ORDER BY (source_evidence_id, correction_id)
        """,
        """
        CREATE TABLE IF NOT EXISTS entity_links
        (
            entity_link_id String,
            source_evidence_id String,
            evidence_selection_id String,
            mention_text String,
            entity_type LowCardinality(String),
            canonical_entity_id String,
            canonical_name String,
            source_anchor_json String,
            status LowCardinality(String),
            note String,
            actor String,
            created_at DateTime64(3, 'UTC'),
            updated_at DateTime64(3, 'UTC')
        )
        ENGINE = ReplacingMergeTree(updated_at)
        PARTITION BY toYYYYMM(created_at)
        ORDER BY (source_evidence_id, entity_link_id)
        """,
        """
        CREATE TABLE IF NOT EXISTS claim_records
        (
            claim_id String,
            source_evidence_id String,
            evidence_selection_id String,
            claim_text String,
            claim_type LowCardinality(String),
            evidence_relation LowCardinality(String),
            qualifier_json String,
            source_anchor_json String,
            status LowCardinality(String),
            note String,
            actor String,
            created_at DateTime64(3, 'UTC'),
            updated_at DateTime64(3, 'UTC')
        )
        ENGINE = ReplacingMergeTree(updated_at)
        PARTITION BY toYYYYMM(created_at)
        ORDER BY (source_evidence_id, claim_id)
        """,
        """
        CREATE TABLE IF NOT EXISTS draft_revisions
        (
            revision_id String,
            draft_id String,
            project String,
            revision_number UInt32,
            title String,
            paragraphs_json String,
            status LowCardinality(String),
            actor String,
            created_at DateTime64(3, 'UTC'),
            updated_at DateTime64(3, 'UTC')
        )
        ENGINE = ReplacingMergeTree(updated_at)
        PARTITION BY toYYYYMM(created_at)
        ORDER BY (project, draft_id, revision_id)
        """,
        """
        CREATE TABLE IF NOT EXISTS draft_citations
        (
            citation_id String,
            draft_id String,
            project String,
            paragraph_id String,
            object_type LowCardinality(String),
            object_id String,
            object_version String,
            source_evidence_id String,
            source_version String,
            citation_text String,
            status LowCardinality(String),
            actor String,
            created_at DateTime64(3, 'UTC'),
            updated_at DateTime64(3, 'UTC')
        )
        ENGINE = ReplacingMergeTree(updated_at)
        PARTITION BY toYYYYMM(created_at)
        ORDER BY (project, draft_id, paragraph_id, citation_id)
        """,
        """
        CREATE TABLE IF NOT EXISTS draft_proposed_diffs
        (
            diff_id String,
            draft_id String,
            project String,
            paragraph_id String,
            diff_kind LowCardinality(String),
            before_text String,
            after_text String,
            rationale String,
            status LowCardinality(String),
            actor String,
            created_at DateTime64(3, 'UTC'),
            updated_at DateTime64(3, 'UTC')
        )
        ENGINE = ReplacingMergeTree(updated_at)
        PARTITION BY toYYYYMM(created_at)
        ORDER BY (project, draft_id, paragraph_id, diff_id)
        """,
        """
        CREATE TABLE IF NOT EXISTS benchmark_methodologies
        (
            methodology_id String,
            benchmark_id String,
            project String,
            dataset String,
            prompting String,
            harness String,
            scoring String,
            hardware String,
            notes String,
            source_evidence_id String,
            source_version String,
            status LowCardinality(String),
            actor String,
            created_at DateTime64(3, 'UTC'),
            updated_at DateTime64(3, 'UTC')
        )
        ENGINE = ReplacingMergeTree(updated_at)
        PARTITION BY toYYYYMM(created_at)
        ORDER BY (project, benchmark_id, methodology_id)
        """,
        """
        CREATE TABLE IF NOT EXISTS benchmark_result_groups
        (
            group_id String,
            benchmark_id String,
            project String,
            config_key String,
            group_label String,
            config_json String,
            compatible UInt8,
            default_ranked UInt8,
            source_evidence_id String,
            status LowCardinality(String),
            actor String,
            created_at DateTime64(3, 'UTC'),
            updated_at DateTime64(3, 'UTC')
        )
        ENGINE = ReplacingMergeTree(updated_at)
        PARTITION BY toYYYYMM(created_at)
        ORDER BY (project, benchmark_id, config_key, group_id)
        """,
        """
        CREATE TABLE IF NOT EXISTS publication_snapshots
        (
            snapshot_id String,
            bundle_id String,
            project String,
            package_type LowCardinality(String),
            snapshot_state LowCardinality(String),
            review_state LowCardinality(String),
            release_state LowCardinality(String),
            manifest_hash String,
            manifest_json String,
            checks_json String,
            actor String,
            note String,
            created_at DateTime64(3, 'UTC'),
            updated_at DateTime64(3, 'UTC')
        )
        ENGINE = ReplacingMergeTree(updated_at)
        PARTITION BY toYYYYMM(created_at)
        ORDER BY (bundle_id, snapshot_id)
        """,
        """
        CREATE TABLE IF NOT EXISTS publication_releases
        (
            release_id String,
            snapshot_id String,
            bundle_id String,
            project String,
            release_state LowCardinality(String),
            manifest_hash String,
            supersedes_release_id String,
            actor String,
            note String,
            created_at DateTime64(3, 'UTC'),
            updated_at DateTime64(3, 'UTC')
        )
        ENGINE = ReplacingMergeTree(updated_at)
        PARTITION BY toYYYYMM(created_at)
        ORDER BY (bundle_id, release_id)
        """,
        """
        CREATE TABLE IF NOT EXISTS publication_handoffs
        (
            handoff_id String,
            snapshot_id String,
            bundle_id String,
            project String,
            artifact_kind LowCardinality(String),
            manifest_hash String,
            object_ids_json String,
            public_config_json String,
            artifact_json String,
            status LowCardinality(String),
            actor String,
            note String,
            created_at DateTime64(3, 'UTC'),
            updated_at DateTime64(3, 'UTC')
        )
        ENGINE = ReplacingMergeTree(updated_at)
        PARTITION BY toYYYYMM(created_at)
        ORDER BY (project, bundle_id, snapshot_id, handoff_id)
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


TASK_QUEUE_LABELS = [
    ("all", "All tasks"),
    ("source_triage", "Source triage"),
    ("extraction_review", "Extraction review"),
    ("media_review", "Media/OCR/VL"),
    ("evidence_selection", "Evidence selection"),
    ("version_review", "Versions"),
    ("entity_resolution", "Entities"),
    ("claim_review", "Claims"),
    ("fact_review", "Facts"),
    ("correction_review", "Corrections"),
    ("selection_review", "Suggested evidence"),
    ("annotation_followup", "Annotations"),
    ("needs_review", "Needs review"),
    ("x_sources", "X sources"),
    ("web_sources", "Web/blog"),
    ("manual_docs", "Manual docs"),
]

TASK_TYPE_LABELS = dict(TASK_QUEUE_LABELS)
SOURCE_QUEUE_FILTERS = {
    "x_sources": "evidence_events.source_kind IN ('x_post', 'x_account', 'x_page', 'media')",
    "web_sources": "evidence_events.source_kind IN ('web_page', 'search_result', 'google_search_page')",
    "manual_docs": "evidence_events.source_kind = 'user_input'",
}
HIGH_REVIEW_TASKS = {"extraction_review", "media_review", "version_review", "entity_resolution", "claim_review", "fact_review", "correction_review"}
REVIEW_TASK_TYPES = {queue_id for queue_id, _ in TASK_QUEUE_LABELS} - {"all", "needs_review", "x_sources", "web_sources", "manual_docs"}


def latest_source_rows(where, limit):
    return ch_data(
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
        """,
        fallback=[],
    )


def hydrate_source_rows(source_ids):
    unique_ids = []
    seen = set()
    for source_id in source_ids:
        if source_id and source_id not in seen:
            unique_ids.append(source_id)
            seen.add(source_id)
    if not unique_ids:
        return {}
    # Hydrate in chunks of 500 rather than truncating at 500. The old behavior
    # silently dropped hydration for any source beyond the 500th, which made
    # ledgers show blank source blocks with no error or indication.
    hydrated = {}
    for start in range(0, len(unique_ids), 500):
        batch = unique_ids[start:start + 500]
        quoted = ", ".join(sql_string(source_id) for source_id in batch)
        rows = latest_source_rows(f"evidence_events.evidence_id IN ({quoted})", len(batch))
        for row in rows:
            decorate_source_row(row)
        for row in rows:
            hydrated[row.get("evidence_id")] = row
    return hydrated


def decorate_source_row(row):
    row["source_label"] = source_kind_label(row.get("source_kind"))
    row["review_hint"] = review_hint(row)
    return row


def task_priority(task_type, source_row=None):
    if task_type in ("extraction_review", "media_review"):
        if source_row and int(source_row.get("text_chars") or 0) == 0:
            return "blocking"
        return "high"
    if task_type in ("entity_resolution", "claim_review", "fact_review", "correction_review"):
        return "high"
    if task_type == "version_review":
        return "normal"
    return "normal"


def task_priority_rank(priority):
    return {"blocking": 3, "high": 2, "normal": 1}.get(priority or "normal", 0)


def make_task(source_row, task_type, task_label, task_reason, object_type="source", object_id=None, object_text="", status="open", updated_at=None):
    source_id = source_row.get("evidence_id") or source_row.get("source_evidence_id") or ""
    object_id = object_id or source_id
    updated_at = updated_at or source_row.get("last_ingested_at") or source_row.get("updated_at") or source_row.get("captured_at") or ""
    task = {
        **source_row,
        "row_kind": "review_task",
        "task_id": f"{task_type}/{object_id}",
        "task_type": task_type,
        "task_label": task_label,
        "task_reason": task_reason,
        "task_state": status or "open",
        "task_priority": task_priority(task_type, source_row),
        "task_updated_at": updated_at,
        "object_type": object_type,
        "object_id": object_id,
        "object_text": object_text,
        "source_evidence_id": source_id,
        "evidence_id": source_id,
    }
    task.setdefault("source_label", source_kind_label(task.get("source_kind")))
    task.setdefault("review_hint", review_hint(task))
    return task


def source_tasks_for_row(row):
    text_chars = int(row.get("text_chars") or 0)
    observations = int(row.get("observations") or 0)
    tasks = [
        make_task(
            row,
            "source_triage",
            "Triage source",
            "Decide whether this captured source belongs in the active research set.",
        )
    ]
    if text_chars < 120 or row.get("source_kind") in ("media", "capture"):
        tasks.append(make_task(
            row,
            "extraction_review",
            "Review extraction",
            "Normalized text is empty, sparse, or capture-like and needs a human extraction check.",
        ))
    if row.get("has_media") and not row.get("has_ocr"):
        tasks.append(make_task(
            row,
            "media_review",
            "Review media/OCR/VL",
            "This source has media but no OCR flag yet; inspect image, video, OCR, or VL outputs.",
        ))
    if row.get("source_kind") in ("x_post", "web_page", "user_input") and text_chars > 0:
        tasks.append(make_task(
            row,
            "evidence_selection",
            "Select evidence",
            "Promote useful quotes, table cells, media regions, or whole-source anchors into review evidence.",
        ))
    if observations > 1:
        tasks.append(make_task(
            row,
            "version_review",
            "Review source versions",
            "Multiple captures exist; compare versions before relying on the normalized content.",
        ))
    return tasks


TERMINAL_REVIEW_TASK_DECISIONS = {"accepted", "rejected", "archived", "completed", "cancelled"}


def latest_review_task_decisions():
    rows = ch_data(
        """
        SELECT
          subject_id,
          argMax(JSONExtractString(payload_json, 'decision'), created_at) AS decision,
          argMax(JSONExtractString(payload_json, 'note'), created_at) AS note,
          max(created_at) AS decided_at
        FROM research_review_events
        WHERE event_type = 'review_task.decision.recorded'
          AND subject_type = 'review_task'
          AND subject_id != ''
        GROUP BY subject_id
        """,
        fallback=[],
    )
    return {row.get("subject_id"): row for row in rows if row.get("subject_id")}


def apply_review_task_decisions(tasks):
    decisions = latest_review_task_decisions()
    if not decisions:
        return tasks
    visible = []
    for task in tasks:
        decision_row = decisions.get(task.get("task_id"))
        if not decision_row:
            visible.append(task)
            continue
        decision = (decision_row.get("decision") or "").lower()
        if decision in TERMINAL_REVIEW_TASK_DECISIONS:
            continue
        if decision:
            task = {**task}
            task["task_state"] = decision
            task["task_updated_at"] = decision_row.get("decided_at") or task.get("task_updated_at")
            task["review_decision_note"] = decision_row.get("note") or ""
        visible.append(task)
    return visible


def review_object_rows(project=""):
    # When a project filter is supplied, scope each query at the SQL level via
    # the evidence_events lookup so ClickHouse does the filtering instead of
    # fetching up to 200 rows per table and filtering in Python. Falls back to
    # the original unscoped query when no project is given (e.g. global inbox).
    project_clause = ""
    if project:
        project_clause = (
            f" AND source_evidence_id IN "
            f"(SELECT evidence_id FROM evidence_events FINAL WHERE source_project = {sql_string(project)})"
        )
    configs = [
        {
            "task_type": "fact_review",
            "object_type": "proposed_fact",
            "id_column": "proposed_fact_id",
            "source_column": "source_evidence_id",
            "label": "Validate proposed fact",
            "reason": "A structured fact needs value, unit, qualifier, and source-anchor review.",
            "query": """
                SELECT
                  proposed_fact_id AS object_id, source_evidence_id,
                  fact_type AS object_kind,
                  concat(field_path, ' ', raw_value, ' ', normalized_value) AS object_text,
                  source_anchor_json, note, actor, created_at, status, updated_at
                FROM proposed_facts FINAL
                WHERE lower(status) NOT IN ('accepted', 'approved', 'rejected', 'superseded', 'published')
                ORDER BY updated_at DESC
                LIMIT 200
            """,
        },
        {
            "task_type": "correction_review",
            "object_type": "normalized_correction",
            "id_column": "correction_id",
            "source_column": "source_evidence_id",
            "label": "Review normalized correction",
            "reason": "A correction overlay needs acceptance, rejection, or more evidence.",
            "query": """
                SELECT
                  correction_id AS object_id, source_evidence_id,
                  correction_kind AS object_kind,
                  concat(original_text, ' -> ', corrected_text) AS object_text,
                  source_anchor_json, note, actor, created_at, status, updated_at
                FROM normalized_corrections FINAL
                WHERE lower(status) NOT IN ('accepted', 'approved', 'rejected', 'superseded', 'published')
                ORDER BY updated_at DESC
                LIMIT 200
            """,
        },
        {
            "task_type": "entity_resolution",
            "object_type": "entity_link",
            "id_column": "entity_link_id",
            "source_column": "source_evidence_id",
            "label": "Resolve entity link",
            "reason": "A mention or canonical entity candidate needs merge/identity review.",
            "query": """
                SELECT
                  entity_link_id AS object_id, source_evidence_id,
                  entity_type AS object_kind,
                  concat(mention_text, ' ', canonical_name, ' ', canonical_entity_id) AS object_text,
                  source_anchor_json, note, actor, created_at, status, updated_at
                FROM entity_links FINAL
                WHERE lower(status) NOT IN ('accepted', 'approved', 'resolved', 'merged', 'rejected', 'superseded', 'published')
                ORDER BY updated_at DESC
                LIMIT 200
            """,
        },
        {
            "task_type": "claim_review",
            "object_type": "claim_stub",
            "id_column": "claim_id",
            "source_column": "source_evidence_id",
            "label": "Review claim",
            "reason": "A claim needs wording, evidence relation, and publication readiness review.",
            "query": """
                SELECT
                  claim_id AS object_id, source_evidence_id,
                  claim_type AS object_kind,
                  claim_text AS object_text,
                  source_anchor_json, note, actor, created_at, status, updated_at
                FROM claim_records FINAL
                WHERE lower(status) NOT IN ('accepted', 'approved', 'rejected', 'superseded', 'published')
                ORDER BY updated_at DESC
                LIMIT 200
            """,
        },
        {
            "task_type": "selection_review",
            "object_type": "evidence_selection",
            "id_column": "selection_id",
            "source_column": "source_evidence_id",
            "label": "Review selected evidence",
            "reason": "A selected quote or anchor needs review before it supports claims or publication.",
            "query": """
                SELECT
                  selection_id AS object_id, source_evidence_id,
                  selection_kind AS object_kind,
                  quote AS object_text,
                  source_anchor_json, note, actor, created_at, status, updated_at
                FROM evidence_selections FINAL
                WHERE lower(status) NOT IN ('accepted', 'approved', 'rejected', 'archived', 'superseded', 'published')
                ORDER BY updated_at DESC
                LIMIT 200
            """,
        },
        {
            "task_type": "annotation_followup",
            "object_type": "annotation",
            "id_column": "annotation_id",
            "source_column": "source_evidence_id",
            "label": "Follow up annotation",
            "reason": "An open annotation may need an evidence selection, entity link, claim, or correction.",
            "query": """
                SELECT
                  annotation_id AS object_id, source_evidence_id,
                  annotation_type AS object_kind,
                  body AS object_text,
                  source_anchor_json, '' AS note, actor, created_at, status, updated_at
                FROM review_annotations FINAL
                WHERE lower(status) NOT IN ('closed', 'accepted', 'approved', 'rejected', 'archived', 'superseded', 'published')
                ORDER BY updated_at DESC
                LIMIT 200
            """,
        },
    ]
    object_rows = []
    for config in configs:
        query = config["query"]
        if project_clause:
            # Insert the project scope right before ORDER BY so it applies
            # alongside the existing status filter.
            query = query.replace(" ORDER BY ", f"{project_clause} ORDER BY ", 1)
        for row in ch_data(query, fallback=[]):
            row["task_type"] = config["task_type"]
            row["object_type"] = config["object_type"]
            row["label"] = config["label"]
            row["reason"] = config["reason"]
            object_rows.append(row)
    return object_rows


def task_matches_filters(task, q, kind, project, queue):
    if kind and task.get("source_kind") != kind:
        return False
    if project and task.get("source_project") != project:
        return False
    if queue in REVIEW_TASK_TYPES and task.get("task_type") != queue:
        return False
    if queue == "needs_review" and task.get("task_type") not in HIGH_REVIEW_TASKS and task.get("task_priority") not in ("high", "blocking"):
        return False
    if queue == "x_sources" and task.get("source_kind") not in ("x_post", "x_account", "x_page", "media"):
        return False
    if queue == "web_sources" and task.get("source_kind") not in ("web_page", "search_result", "google_search_page"):
        return False
    if queue == "manual_docs" and task.get("source_kind") != "user_input":
        return False
    if q:
        haystack = " ".join(str(task.get(key) or "") for key in (
            "task_label", "task_reason", "object_text", "title", "snippet",
            "canonical_url", "author_handle", "domain", "evidence_id", "source_evidence_id",
        ))
        if q.lower() not in haystack.lower():
            return False
    return True


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
    if queue in SOURCE_QUEUE_FILTERS:
        clauses.append(SOURCE_QUEUE_FILTERS[queue])

    where = " AND ".join(clauses)
    rows = [decorate_source_row(row) for row in latest_source_rows(where, max(limit * 4, limit))]

    tasks = []
    for row in rows:
        tasks.extend(source_tasks_for_row(row))

    object_rows = review_object_rows(project)
    source_map = hydrate_source_rows([row.get("source_evidence_id") for row in object_rows])
    for object_row in object_rows:
        source_id = object_row.get("source_evidence_id") or ""
        source_row = source_map.get(source_id)
        if not source_row:
            continue
        object_kind = object_row.get("object_kind") or object_row.get("object_type") or ""
        label = object_row.get("label") or TASK_TYPE_LABELS.get(object_row.get("task_type"), "Review task")
        if object_kind:
            label = f"{label}: {object_kind}"
        tasks.append(make_task(
            source_row,
            object_row["task_type"],
            label,
            object_row.get("reason") or "Review this derived object before relying on it.",
            object_type=object_row.get("object_type") or "review_object",
            object_id=object_row.get("object_id") or "",
            object_text=object_row.get("object_text") or "",
            status=object_row.get("status") or "open",
            updated_at=object_row.get("updated_at") or source_row.get("last_ingested_at"),
        ))

    tasks = apply_review_task_decisions(tasks)
    filtered = [task for task in tasks if task_matches_filters(task, q, kind, project, queue)]
    filtered.sort(key=lambda task: (task_priority_rank(task.get("task_priority")), str(task.get("task_updated_at") or task.get("last_ingested_at") or "")), reverse=True)
    visible = filtered[:limit]
    return {
        "rows": visible,
        "results": cursor_page(visible, len(filtered), limit),
        "limit": limit,
        "queue": queue,
        "row_kind": "review_task",
        "generated_at": now_iso(),
        "stale": False,
        "permissions": ["triage", "assign", "decide"],
        "version": "inbox.v1",
    }


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
          countIf(source_kind = 'user_input') AS manual_docs,
          max(ingested_at) AS last_ingested_at
        FROM evidence_events
        """
    )[0]
    version_candidates = ch_data(
        """
        SELECT count() AS rows
        FROM
        (
          SELECT evidence_id, count() AS observations
          FROM evidence_events
          GROUP BY evidence_id
          HAVING observations > 1
        )
        """,
        fallback=[{"rows": 0}],
    )[0]
    review = hydratable_review_counts()
    queue_counts = {
        "all": int(totals.get("unique_evidence") or 0) + sum(int(review.get(key) or 0) for key in ("selections", "annotations", "proposed_facts", "normalized_corrections", "entity_links", "claim_records")),
        "source_triage": int(totals.get("unique_evidence") or 0),
        "extraction_review": int(totals.get("media_rows") or 0),
        "media_review": int(totals.get("media_rows") or 0),
        "evidence_selection": int(totals.get("x_posts") or 0) + int(totals.get("web_pages") or 0),
        "version_review": int(version_candidates.get("rows") or 0),
        "entity_resolution": int(review.get("entity_links") or 0),
        "claim_review": int(review.get("claim_records") or 0),
        "fact_review": int(review.get("proposed_facts") or 0),
        "correction_review": int(review.get("normalized_corrections") or 0),
        "selection_review": int(review.get("selections") or 0),
        "annotation_followup": int(review.get("annotations") or 0),
        "needs_review": int(totals.get("media_rows") or 0) + sum(int(review.get(key) or 0) for key in ("proposed_facts", "normalized_corrections", "entity_links", "claim_records")),
        "x_sources": int(totals.get("x_posts") or 0) + int(totals.get("x_accounts") or 0),
        "web_sources": int(totals.get("web_pages") or 0),
        "manual_docs": int(totals.get("manual_docs") or 0),
    }
    queues = [{"id": queue_id, "label": label, "count": queue_counts.get(queue_id, 0)} for queue_id, label in TASK_QUEUE_LABELS]
    return {"totals": totals, "source_kinds": source_kinds, "projects": projects, "domains": domains, "queues": queues}


def review_counts():
    return ch_data(
        """
        SELECT
          (SELECT count() FROM evidence_selections FINAL) AS selections,
          (SELECT count() FROM review_annotations FINAL) AS annotations,
          (SELECT count() FROM proposed_facts FINAL) AS proposed_facts,
          (SELECT count() FROM normalized_corrections FINAL) AS normalized_corrections,
          (SELECT count() FROM entity_links FINAL) AS entity_links,
          (SELECT count() FROM claim_records FINAL) AS claim_records,
          (SELECT count() FROM research_review_events) AS review_events
        """,
        fallback=[{}],
    )[0]


def hydratable_review_counts():
    return ch_data(
        """
        SELECT
          (SELECT count() FROM evidence_selections FINAL WHERE source_evidence_id IN (SELECT DISTINCT evidence_id FROM evidence_events)) AS selections,
          (SELECT count() FROM review_annotations FINAL WHERE source_evidence_id IN (SELECT DISTINCT evidence_id FROM evidence_events)) AS annotations,
          (SELECT count() FROM proposed_facts FINAL WHERE source_evidence_id IN (SELECT DISTINCT evidence_id FROM evidence_events)) AS proposed_facts,
          (SELECT count() FROM normalized_corrections FINAL WHERE source_evidence_id IN (SELECT DISTINCT evidence_id FROM evidence_events)) AS normalized_corrections,
          (SELECT count() FROM entity_links FINAL WHERE source_evidence_id IN (SELECT DISTINCT evidence_id FROM evidence_events)) AS entity_links,
          (SELECT count() FROM claim_records FINAL WHERE source_evidence_id IN (SELECT DISTINCT evidence_id FROM evidence_events)) AS claim_records
        """,
        fallback=[{}],
    )[0]


def project_source_targets(row):
    x_sources = int(row.get("x_sources") or 0)
    web_sources = int(row.get("web_sources") or 0)
    media_sources = int(row.get("media_sources") or 0)
    manual_sources = int(row.get("manual_sources") or 0)
    return [
        {"label": "X / social", "current": x_sources, "target": max(2, min(8, x_sources + 1)), "route": "library"},
        {"label": "Web / blog", "current": web_sources, "target": max(2, min(8, web_sources + 1)), "route": "library"},
        {"label": "Media / OCR", "current": int(row.get("ocr_rows") or 0), "target": max(1, media_sources), "route": "evidence"},
        {"label": "Manual docs", "current": manual_sources, "target": max(1, manual_sources), "route": "library"},
    ]


def project_coverage_targets(row):
    accepted_evidence = int(row.get("accepted_evidence") or 0)
    accepted_claims = int(row.get("accepted_claims") or 0)
    source_classes = int(row.get("source_classes") or 0)
    extracted_rows = int(row.get("extracted_rows") or 0)
    sources = int(row.get("sources") or 0)
    return [
        {
            "label": "Independent source classes",
            "current": source_classes,
            "target": 3,
            "status": "pass" if source_classes >= 3 else "needs_work",
            "rule": "At least three source classes before publication review.",
        },
        {
            "label": "Normalized source text",
            "current": extracted_rows,
            "target": max(1, sources),
            "status": "pass" if extracted_rows >= sources else "needs_work",
            "rule": "Captured sources should have inspectable normalized text or an explicit extraction failure.",
        },
        {
            "label": "Accepted evidence",
            "current": accepted_evidence,
            "target": max(1, min(5, sources)),
            "status": "pass" if accepted_evidence >= max(1, min(5, sources)) else "needs_work",
            "rule": "Key findings must cite accepted evidence anchors.",
        },
        {
            "label": "Accepted claims",
            "current": accepted_claims,
            "target": max(1, min(3, accepted_evidence or sources)),
            "status": "pass" if accepted_claims >= max(1, min(3, accepted_evidence or sources)) else "needs_work",
            "rule": "Publication drafts should be driven by reviewed claims.",
        },
    ]


def project_blockers(row):
    blockers = []
    sparse_rows = int(row.get("sparse_rows") or 0)
    media_without_ocr = max(0, int(row.get("media_sources") or 0) - int(row.get("ocr_rows") or 0))
    if sparse_rows:
        blockers.append({
            "label": "Sparse normalized extraction",
            "count": sparse_rows,
            "severity": "warn",
            "route": "inbox",
            "detail": "Rows have little extracted text and need source workbench inspection.",
        })
    if media_without_ocr:
        blockers.append({
            "label": "Media without OCR/VL review",
            "count": media_without_ocr,
            "severity": "warn",
            "route": "evidence",
            "detail": "Media captures should expose OCR, transcript, or visual observations before claims rely on them.",
        })
    if int(row.get("source_classes") or 0) < 3:
        blockers.append({
            "label": "Source diversity below target",
            "count": max(1, 3 - int(row.get("source_classes") or 0)),
            "severity": "danger",
            "route": "library",
            "detail": "Add or review more source classes before treating this project as publication-ready.",
        })
    if int(row.get("open_claims") or 0):
        blockers.append({
            "label": "Open claim review",
            "count": int(row.get("open_claims") or 0),
            "severity": "warn",
            "route": "claims",
            "detail": "Claim assertions need review before they can appear as accepted findings.",
        })
    return blockers


def project_saved_views(row):
    project_id = row.get("project_id") or ""
    return [
        {"label": "Project inbox", "route": "inbox", "query": {"project": project_id}, "description": "Open review tasks scoped to this project."},
        {"label": "Source library", "route": "library", "query": {"project": project_id}, "description": "Captured source records and normalized snippets."},
        {"label": "Evidence ledger", "route": "evidence", "query": {"project": project_id}, "description": "Selections, corrections, proposed facts, and high-value sources."},
        {"label": "Claims ledger", "route": "claims", "query": {"project": project_id}, "description": "Claim records and status by source anchor."},
        {"label": "Publishing checks", "route": "publishing", "query": {"project": project_id}, "description": "Snapshot readiness and unresolved blockers."},
    ]


def project_rows(params=None):
    params = params or {}
    q = (params.get("q", [""])[0] or "").strip()
    project = (params.get("project", [""])[0] or "").strip()
    clauses = ["1 = 1"]
    if project:
        clauses.append(f"source_project = {sql_string(project)}")
    if q:
        like = sql_string(q)
        clauses.append(
            "("
            f"positionCaseInsensitive(source_project, {like}) > 0 OR "
            f"positionCaseInsensitive(title, {like}) > 0 OR "
            f"positionCaseInsensitive(canonical_url, {like}) > 0 OR "
            f"positionCaseInsensitive(domain, {like}) > 0 OR "
            f"positionCaseInsensitive(text, {like}) > 0"
            ")"
        )
    where = " AND ".join(clauses)
    rows = ch_data(
        f"""
        SELECT
          source_project AS project_id,
          if(source_project = '', '(unassigned)', source_project) AS name,
          uniqExact(evidence_id) AS sources,
          count() AS evidence_rows,
          countIf(source_kind IN ('x_post', 'x_account', 'x_page')) AS x_sources,
          countIf(source_kind IN ('web_page', 'search_result', 'google_search_page')) AS web_sources,
          countIf(source_kind = 'media') AS media_sources,
          countIf(source_kind = 'user_input') AS manual_sources,
          countIf(has_ocr = 1) AS ocr_rows,
          countIf(length(text) >= 120) AS extracted_rows,
          countIf(length(text) < 120) AS sparse_rows,
          min(captured_at) AS first_capture,
          max(ingested_at) AS last_activity
        FROM evidence_events
        WHERE {where}
        GROUP BY source_project
        ORDER BY last_activity DESC, sources DESC
        LIMIT 100
        """,
        fallback=[],
    )
    evidence_reviews = ch_data(
        """
        SELECT
          source_project AS project_id,
          countIf(status = 'accepted') AS accepted_evidence,
          count() AS proposed_evidence
        FROM evidence_selections FINAL
        INNER JOIN
        (
          SELECT evidence_id, argMax(source_project, ingested_at) AS source_project
          FROM evidence_events
          GROUP BY evidence_id
        ) latest_sources
        ON evidence_selections.source_evidence_id = latest_sources.evidence_id
        GROUP BY source_project
        """,
        fallback=[],
    )
    claims = ch_data(
        """
        SELECT
          source_project AS project_id,
          countIf(status IN ('under_review', 'proposed')) AS open_claims,
          countIf(status = 'accepted') AS accepted_claims
        FROM claim_records FINAL
        INNER JOIN
        (
          SELECT evidence_id, argMax(source_project, ingested_at) AS source_project
          FROM evidence_events
          GROUP BY evidence_id
        ) latest_sources
        ON claim_records.source_evidence_id = latest_sources.evidence_id
        GROUP BY source_project
        """,
        fallback=[],
    )
    evidence_by_project = {row.get("project_id", ""): row for row in evidence_reviews}
    claims_by_project = {row.get("project_id", ""): row for row in claims}
    for row in rows:
        source_classes = sum(1 for key in ("x_sources", "web_sources", "media_sources", "manual_sources") if int(row.get(key) or 0) > 0)
        sparse_rows = int(row.get("sparse_rows") or 0)
        media_without_ocr = max(0, int(row.get("media_sources") or 0) - int(row.get("ocr_rows") or 0))
        diversity_gaps = max(0, 3 - source_classes)
        review_blockers = sparse_rows + media_without_ocr
        evidence_review = evidence_by_project.get(row.get("project_id", ""), {})
        claim_review = claims_by_project.get(row.get("project_id", ""), {})
        completion_percent = percent(row.get("extracted_rows"), row.get("evidence_rows"))
        row["phase"] = "evidence review" if int(row.get("sources") or 0) else "setup"
        if completion_percent >= 75:
            row["phase"] = "publication prep"
        elif int(row.get("extracted_rows") or 0) < max(1, int(row.get("evidence_rows") or 0) // 3):
            row["phase"] = "capture triage"
        row["owner"] = REVIEW_ACTOR
        row["visibility"] = "internal"
        # Surface the real brief question/scope per project instead of the same
        # fixed string for every project. The brief is read on the next line.
        brief_for_row = read_project_brief(row.get("project_id") or "", row.get("name") or "", row)
        row["question"] = brief_for_row.get("research_question") or "Collect and validate source-linked evidence"
        scope_obj = brief_for_row.get("scope") or {}
        row["scope"] = "; ".join(part for part in (
            scope_obj.get("time_window"),
            scope_obj.get("geography"),
            scope_obj.get("population"),
        ) if part) or "Captured sources, normalized artifacts, and review queues."
        row["accepted_evidence"] = int(evidence_review.get("accepted_evidence") or 0)
        row["proposed_evidence"] = int(evidence_review.get("proposed_evidence") or 0)
        row["accepted_claims"] = int(claim_review.get("accepted_claims") or 0)
        row["open_claims"] = int(claim_review.get("open_claims") or 0)
        row["contributors"] = [REVIEW_ACTOR]
        row["due_at"] = ""
        row["next_review_at"] = ""
        row["unresolved_conflicts"] = 0
        row["review_blockers"] = review_blockers
        row["publication_blockers"] = diversity_gaps + review_blockers
        row["source_classes"] = source_classes
        row["completion_percent"] = completion_percent
        row["brief"] = brief_for_row
        row["source_targets"] = project_source_targets(row)
        row["coverage_targets"] = project_coverage_targets(row)
        row["blockers"] = project_blockers(row)
        row["saved_views"] = project_saved_views(row)
        row["activity"] = project_brief_activity(row.get("project_id") or "")
    return {
        "rows": rows,
        "object_states": {
            "project": ["active", "paused", "archived"],
            "capture": ["pending", "capturing", "complete", "partial", "failed", "superseded"],
            "evidence": ["draft", "proposed", "accepted", "rejected", "superseded"],
            "claim": ["proposed", "under_review", "accepted", "disputed", "rejected", "superseded"],
        },
        "generated_at": now_iso(),
        "stale": False,
        "permissions": ["navigate", "brief", "review"],
        "version": "projects.v1",
    }


def sql_in_list(values):
    quoted = [sql_string(value) for value in values if value]
    return "(" + ", ".join(quoted) + ")" if quoted else "('')"


def library_count_map(ids, table, column="source_evidence_id", final=True):
    if not ids:
        return {}
    final_sql = " FINAL" if final else ""
    rows = ch_data(
        f"""
        SELECT {column} AS evidence_id, count() AS rows
        FROM {table}{final_sql}
        WHERE {column} IN {sql_in_list(ids)}
        GROUP BY {column}
        """,
        fallback=[],
    )
    return {row.get("evidence_id"): int(row.get("rows") or 0) for row in rows}


def library_annotation_counts(ids):
    if not ids:
        return {}
    rows = ch_data(
        f"""
        SELECT evidence_id, count() AS rows
        FROM semantic_annotations
        WHERE evidence_id IN {sql_in_list(ids)}
        GROUP BY evidence_id
        """,
        fallback=[],
    )
    return {row.get("evidence_id"): int(row.get("rows") or 0) for row in rows}


def library_latest_actions(ids):
    if not ids:
        return {}
    rows = ch_data(
        f"""
        SELECT
          source_evidence_id,
          argMax(JSONExtractString(payload_json, 'action'), created_at) AS action,
          argMax(JSONExtractString(payload_json, 'target_project'), created_at) AS target_project,
          argMax(actor, created_at) AS actor,
          max(created_at) AS created_at
        FROM research_review_events
        WHERE event_type = 'library.source_action.recorded'
          AND source_evidence_id IN {sql_in_list(ids)}
        GROUP BY source_evidence_id
        """,
        fallback=[],
    )
    return {row.get("source_evidence_id"): row for row in rows}


def library_facets_for_where(where):
    base = f"""
      FROM
      (
        SELECT
          evidence_id,
          argMax(source_kind, ingested_at) AS source_kind,
          argMax(source_project, ingested_at) AS source_project,
          argMax(domain, ingested_at) AS domain,
          argMax(author_handle, ingested_at) AS author_handle,
          length(argMax(text, ingested_at)) AS text_chars,
          max(has_media) AS has_media,
          max(has_ocr) AS has_ocr,
          count() AS capture_count,
          max(ingested_at) AS last_ingested_at
        FROM evidence_events
        WHERE {where}
        GROUP BY evidence_id
      )
    """
    source_types = ch_data(
        f"""
        SELECT source_kind AS id, count() AS count
        {base}
        GROUP BY source_kind
        ORDER BY count DESC, id ASC
        LIMIT 40
        """,
        fallback=[],
    )
    projects = ch_data(
        f"""
        SELECT source_project AS id, count() AS count
        {base}
        GROUP BY source_project
        ORDER BY count DESC, id ASC
        LIMIT 40
        """,
        fallback=[],
    )
    domains = ch_data(
        f"""
        SELECT if(domain != '', domain, author_handle) AS id, count() AS count
        {base}
        WHERE domain != '' OR author_handle != ''
        GROUP BY id
        ORDER BY count DESC, id ASC
        LIMIT 60
        """,
        fallback=[],
    )
    processing = [
        {"id": "normalized", "label": "Normalized text", "count": sum(1 for row in ch_data(f"SELECT text_chars {base}", fallback=[]) if int(row.get("text_chars") or 0) >= 120)},
        {"id": "media", "label": "Media present", "count": sum(1 for row in ch_data(f"SELECT has_media {base}", fallback=[]) if int(row.get("has_media") or 0))},
        {"id": "ocr", "label": "OCR present", "count": sum(1 for row in ch_data(f"SELECT has_ocr {base}", fallback=[]) if int(row.get("has_ocr") or 0))},
        {"id": "versions", "label": "Multiple captures", "count": sum(1 for row in ch_data(f"SELECT capture_count {base}", fallback=[]) if int(row.get("capture_count") or 0) > 1)},
    ]
    return [
        {"id": "source_type", "label": "Source type", "items": [{"id": row.get("id") or "unknown", "label": source_kind_label(row.get("id")), "count": int(row.get("count") or 0)} for row in source_types]},
        {"id": "project", "label": "Project", "items": [{"id": row.get("id") or "", "label": row.get("id") or "(unassigned)", "count": int(row.get("count") or 0)} for row in projects]},
        {"id": "publisher", "label": "Publisher / account", "items": [{"id": row.get("id") or "", "label": row.get("id") or "(unknown)", "count": int(row.get("count") or 0)} for row in domains]},
        {"id": "processing", "label": "Processing state", "items": processing},
    ]


def library_summary_for_where(where):
    rows = ch_data(
        f"""
        SELECT
          count() AS source_records,
          sum(capture_count) AS captures,
          countIf(text_chars >= 120) AS normalized_captures,
          countIf(capture_count > 1) AS duplicate_clusters,
          countIf(last_ingested_at >= now() - INTERVAL 1 DAY) AS new_since_view
        FROM
        (
          SELECT
            evidence_id,
            length(argMax(text, ingested_at)) AS text_chars,
            count() AS capture_count,
            max(ingested_at) AS last_ingested_at
          FROM evidence_events
          WHERE {where}
          GROUP BY evidence_id
        )
        """,
        fallback=[{}],
    )
    row = rows[0] if rows else {}
    return {
        "source_records": int(row.get("source_records") or 0),
        "captures": int(row.get("captures") or 0),
        "normalized_captures": int(row.get("normalized_captures") or 0),
        "duplicate_clusters": int(row.get("duplicate_clusters") or 0),
        "new_since_view": int(row.get("new_since_view") or 0),
    }


def library_query_explanation(q, mode):
    if not q:
        return "Showing recent captured source records in the selected scope."
    if mode == "exact":
        return "Exact search across titles, URLs, handles, domains, captured text, normalized text, OCR/transcript text, and evidence identifiers."
    if mode == "semantic":
        return "Semantic mode is presented as concept matching; explanations should name matched concepts and source locations rather than raw vector scores."
    return "Hybrid search combines exact matched fragments with semantic reason categories and source/review state."


def source_layer_label(kind):
    if kind in ("search_result", "google_search_page"):
        return "discovery provenance"
    if kind in ("x_post", "x_account", "x_page"):
        return "social source"
    if kind == "web_page":
        return "substantive web source"
    if kind == "media":
        return "media artifact"
    if kind == "user_input":
        return "manual research document"
    return "source record"


def library_preview(selected_id):
    if not selected_id:
        return None
    try:
        detail = source_detail({"id": [selected_id]})
    except ResearchUiError:
        return None
    latest = detail.get("latest") or {}
    review = detail.get("review") or {}
    return {
        "source": latest,
        "captures": detail.get("observations") or [],
        "artifacts": latest.get("artifact_paths") or [],
        "ocr": detail.get("ocr") or [],
        "vl": detail.get("vl") or [],
        "annotations": detail.get("annotations") or [],
        "related": detail.get("related") or [],
        "review": review,
        "counts": {
            "captures": len(detail.get("observations") or []),
            "artifacts": len(latest.get("artifact_paths") or []),
            "ocr": len(detail.get("ocr") or []),
            "vl": len(detail.get("vl") or []),
            "evidence": len(review.get("evidence_selections") or []),
            "claims": len(review.get("claim_records") or []),
            "entities": len(review.get("entity_links") or []),
            "annotations": len(review.get("annotations") or []),
        },
    }


def library_search(params):
    limit = sql_int(params.get("limit", ["80"])[0], 80)
    q = (params.get("q", [""])[0] or "").strip()
    kind = (params.get("type", params.get("kind", [""]))[0] or "").strip()
    project = (params.get("project", [""])[0] or "").strip()
    mode = (params.get("mode", ["hybrid"])[0] or "hybrid").strip()
    scope = (params.get("scope", ["corpus"])[0] or "corpus").strip()
    sort = (params.get("sort", ["relevance"])[0] or "relevance").strip()
    inspect = (params.get("inspect", params.get("id", [""]))[0] or "").strip()
    date_from = (params.get("date_from", [""])[0] or "").strip()
    date_to = (params.get("date_to", [""])[0] or "").strip()
    include_archived = (params.get("include_archived", ["0"])[0] or "").strip() in ("1", "true", "yes")
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
            f"positionCaseInsensitive(evidence_events.source_project, {like}) > 0 OR "
            f"positionCaseInsensitive(evidence_events.evidence_id, {like}) > 0"
            ")"
        )
    if kind:
        clauses.append(f"evidence_events.source_kind = {sql_string(kind)}")
    if project:
        clauses.append(f"evidence_events.source_project = {sql_string(project)}")
    if date_from:
        clauses.append(f"toDate(ifNull(evidence_events.captured_at, evidence_events.ingested_at)) >= toDate({sql_string(date_from)})")
    if date_to:
        clauses.append(f"toDate(ifNull(evidence_events.captured_at, evidence_events.ingested_at)) <= toDate({sql_string(date_to)})")
    where = " AND ".join(clauses)
    order_by = "last_ingested_at DESC"
    if sort == "captured_desc":
        order_by = "captured_at DESC, last_ingested_at DESC"
    elif sort == "published_desc":
        order_by = "posted_at DESC, captured_at DESC"
    elif sort == "freshness":
        order_by = "has_media DESC, has_ocr DESC, observations DESC, last_ingested_at DESC"
    rows = ch_data(
        f"""
        SELECT
          evidence_id,
          argMax(source_kind, ingested_at) AS source_kind,
          argMax(source_project, ingested_at) AS source_project,
          argMax(canonical_url, ingested_at) AS canonical_url,
          argMax(author_handle, ingested_at) AS author_handle,
          argMax(domain, ingested_at) AS domain,
          argMax(title, ingested_at) AS title,
          argMax(raw_json, ingested_at) AS raw_json,
          substring(argMax(text, ingested_at), 1, 500) AS snippet,
          length(argMax(text, ingested_at)) AS text_chars,
          max(has_media) AS has_media,
          max(has_ocr) AS has_ocr,
          max(posted_at) AS posted_at,
          max(captured_at) AS captured_at,
          max(ingested_at) AS last_ingested_at,
          count() AS observations
        FROM evidence_events
        WHERE {where}
        GROUP BY evidence_id
        ORDER BY {order_by}
        LIMIT {max(limit, 1) * 2}
        """,
        fallback=[],
    )
    ids = [row.get("evidence_id") for row in rows if row.get("evidence_id")]
    evidence_counts = library_count_map(ids, "evidence_selections")
    claim_counts = library_count_map(ids, "claim_records")
    fact_counts = library_count_map(ids, "proposed_facts")
    correction_counts = library_count_map(ids, "normalized_corrections")
    entity_counts = library_count_map(ids, "entity_links")
    annotation_counts = library_annotation_counts(ids)
    ocr_counts = library_count_map(ids, "media_ocr_results", "evidence_id", final=False)
    vl_counts = library_count_map(ids, "media_vl_embeddings", "evidence_id", final=False)
    latest_actions = library_latest_actions(ids)
    visible_rows = []
    for row in rows:
        evidence_id = row.get("evidence_id") or ""
        action_state = latest_actions.get(evidence_id) or {}
        if action_state.get("action") == "archive" and not include_archived:
            continue
        raw = parse_raw_json(row.get("raw_json", ""))
        artifact_paths = extract_paths(raw)
        row.pop("raw_json", None)
        row["source_label"] = source_kind_label(row.get("source_kind"))
        row["source_layer"] = source_layer_label(row.get("source_kind"))
        row["review_hint"] = review_hint(row)
        row["match_explanation"] = library_query_explanation(q, mode) if q else "Recent captured source in the selected scope."
        row["extraction_state"] = "complete" if int(row.get("text_chars") or 0) >= 120 else "partial"
        row["capture_state"] = "complete" if row.get("captured_at") else "pending"
        row["artifact_count"] = len(artifact_paths)
        row["artifact_available"] = bool(artifact_paths or int(row.get("has_media") or 0) or int(row.get("has_ocr") or 0))
        row["evidence_count"] = evidence_counts.get(evidence_id, 0)
        row["claim_count"] = claim_counts.get(evidence_id, 0)
        row["fact_count"] = fact_counts.get(evidence_id, 0)
        row["correction_count"] = correction_counts.get(evidence_id, 0)
        row["entity_count"] = entity_counts.get(evidence_id, 0)
        row["annotation_count"] = annotation_counts.get(evidence_id, 0)
        row["ocr_count"] = ocr_counts.get(evidence_id, 0)
        row["vl_count"] = vl_counts.get(evidence_id, 0)
        row["latest_library_action"] = action_state.get("action") or ""
        row["latest_library_action_at"] = action_state.get("created_at") or ""
        row["review_state"] = "archived" if action_state.get("action") == "archive" else ("review-linked" if row["evidence_count"] or row["claim_count"] or row["fact_count"] else "unreviewed")
        row["duplicate_state"] = "candidate_duplicate" if int(row.get("observations") or 0) > 1 else "single"
        row["permitted_actions"] = ["add_to_project", "assign_review", "merge_cluster", "archive", "open_workbench"]
        visible_rows.append(row)
        if len(visible_rows) >= limit:
            break
    selected_id = inspect or (visible_rows[0].get("evidence_id") if visible_rows else "")
    if selected_id.startswith("source:"):
        selected_id = selected_id.removeprefix("source:")
    return {
        "scope": {
            "kind": "project" if project else scope,
            "project_ids": [project] if project else [],
            "label": project or ("Entire corpus" if scope == "corpus" else scope),
        },
        "query": {
            "text": q,
            "mode": mode,
            "row_mode": "source",
            "sort": sort,
            "filters": {
                "source_kind": kind,
                "project": project,
                "date_from": date_from,
                "date_to": date_to,
                "include_archived": include_archived,
            },
            "explanation": library_query_explanation(q, mode),
        },
        "summary": library_summary_for_where(where),
        "saved_views": [
            {"id": "recent", "label": "Recent captures", "description": "Latest captured source records"},
            {"id": "needs-extraction", "label": "Needs extraction review", "description": "Sparse normalized text, media, OCR, and VL work"},
            {"id": "versions", "label": "Version candidates", "description": "Sources with multiple immutable captures"},
            {"id": "google-provenance", "label": "Google discovery provenance", "description": "SERP records separate from opened pages"},
        ],
        "facets": library_facets_for_where(where),
        "results": cursor_page(visible_rows, len(rows), limit),
        "rows": visible_rows,
        "preview": library_preview(selected_id),
        "selection": {
            "selected_source_ids": [selected_id] if selected_id else [],
            "capabilities": {
                "add_to_project": True,
                "assign_review": True,
                "archive": True,
                "merge_cluster": True,
                "open_workbench": True,
            },
        },
        "permissions": ["read", "review_event_write"],
        "generated_at": now_iso(),
        "stale": False,
        "version": "source_library.v1",
        "mode": mode,
    }


def create_library_action(payload):
    action = compact_text(payload.get("action"), 80)
    source_ids = payload.get("source_ids")
    if not isinstance(source_ids, list):
        source_ids = [payload.get("source_evidence_id") or payload.get("source_id")]
    source_ids = [compact_text(item, 1000) for item in source_ids if compact_text(item, 1000)]
    if not action:
        raise ResearchUiError(400, "action is required")
    if not source_ids:
        raise ResearchUiError(400, "source_ids are required")
    allowed = {"add_to_project", "assign_review", "archive", "merge_cluster", "dismiss_duplicate", "restore"}
    if action not in allowed:
        raise ResearchUiError(400, f"Unsupported library action: {action}")
    outcomes = []
    for source_id in source_ids:
        event_payload = {
            **payload,
            "source_evidence_id": source_id,
            "subject_type": "source_record",
            "subject_id": source_id,
            "action": action,
            "status": action,
            "source_anchor": {
                "kind": "source_record",
                "source_evidence_id": source_id,
                "library_action": action,
            },
            "idempotency_key": compact_text(payload.get("idempotency_key"), 500) or f"library:{action}:{source_id}:{now_iso()}",
        }
        event = persist_review_event(build_review_event("library.source_action.recorded", event_payload))
        outcomes.append({"source_evidence_id": source_id, "action": action, "event_id": event.get("event_id"), "ok": True})
    return {"action": action, "outcomes": outcomes, "created_at": now_iso()}


def first_nonempty(*values):
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def group_rows(rows, key_name):
    grouped = {}
    for row in rows:
        key = row.get(key_name) or ""
        if key:
            grouped.setdefault(key, []).append(row)
    return grouped


def anchor_type_for(row, anchor):
    text = " ".join(str(row.get(key) or "") for key in ("selection_kind", "correction_kind", "block_id", "field_path")).lower()
    if isinstance(anchor, dict):
        keys = " ".join(str(key).lower() for key in anchor.keys())
        values = " ".join(str(value).lower() for value in anchor.values() if not isinstance(value, (dict, list)))
        text = f"{text} {keys} {values}"
    if "timecode" in text or "video" in text:
        return "video_timecode"
    if "bbox" in text or "image" in text or "media" in text or "region" in text:
        return "image_region"
    if "table" in text or "cell" in text or "row" in text:
        return "table_cell"
    if "line" in text or "repo" in text or "path" in text:
        return "repo_line"
    if row.get("block_id") or row.get("document_id"):
        return "document_block"
    return "source_record"


def anchor_label_for(row, anchor):
    if isinstance(anchor, dict):
        label = first_nonempty(anchor.get("label"), anchor.get("selector"), anchor.get("dom_path"), anchor.get("artifact_path"))
        if label:
            return compact_text(label, 180)
    parts = [row.get("document_id"), row.get("block_id"), row.get("field_path")]
    return compact_text(" / ".join(str(part) for part in parts if part), 180)


def source_for_ledger_row(source_map, source_id):
    source = source_map.get(source_id or "") or {}
    return {
        "evidence_id": source_id or source.get("evidence_id") or "",
        "source_kind": source.get("source_kind") or "",
        "source_label": source.get("source_label") or source_kind_label(source.get("source_kind")),
        "source_project": source.get("source_project") or "",
        "canonical_url": source.get("canonical_url") or "",
        "title": source.get("title") or source.get("canonical_url") or source_id or "",
        "snippet": source.get("snippet") or "",
        "author_handle": source.get("author_handle") or "",
        "domain": source.get("domain") or "",
        "captured_at": source.get("last_captured_at") or source.get("captured_at") or "",
        "last_ingested_at": source.get("last_ingested_at") or "",
        "has_media": bool(source.get("has_media")),
        "has_ocr": bool(source.get("has_ocr")),
        "observations": source.get("observations") or 0,
        "text_chars": source.get("text_chars") or 0,
    }


def evidence_search_explanation(row, mode, q):
    mode_label = {"exact": "Exact", "semantic": "Semantic", "hybrid": "Hybrid"}.get(mode or "hybrid", "Hybrid")
    if q:
        return f"{mode_label} match over evidence text, source metadata, anchors, and linked review objects."
    return f"{mode_label} ledger view ordered by review activity and source freshness."


def make_evidence_row(row, object_type, object_id, source_map, facts_by_selection, facts_by_source, claims_by_selection, claims_by_source, corrections_by_source, annotations_by_selection, annotations_by_source, mode, q):
    source_id = row.get("source_evidence_id") or row.get("evidence_id") or ""
    source = source_for_ledger_row(source_map, source_id)
    anchor = parse_raw_json(row.get("source_anchor_json", ""))
    selection_id = row.get("selection_id") or row.get("evidence_selection_id") or ""
    linked_facts = facts_by_selection.get(selection_id, []) + facts_by_source.get(source_id, [])
    linked_claims = claims_by_selection.get(selection_id, []) + claims_by_source.get(source_id, [])
    linked_corrections = corrections_by_source.get(source_id, [])
    linked_annotations = annotations_by_selection.get(selection_id, []) + annotations_by_source.get(source_id, [])
    status = row.get("status") or ("candidate" if object_type == "evidence_candidate" else "open")
    evidence_type = first_nonempty(
        row.get("selection_kind"),
        row.get("fact_type"),
        row.get("correction_kind"),
        row.get("annotation_type"),
        row.get("claim_type"),
        "source_candidate" if object_type == "evidence_candidate" else object_type,
    )
    quote = first_nonempty(
        row.get("quote"),
        row.get("evidence_quote"),
        row.get("body"),
        row.get("claim_text"),
        row.get("corrected_text"),
        row.get("normalized_value"),
        row.get("raw_value"),
        row.get("snippet"),
        source.get("snippet"),
    )
    normalized_observation = first_nonempty(
        row.get("corrected_text"),
        row.get("normalized_value"),
        row.get("body"),
        row.get("claim_text"),
        row.get("quote"),
    )
    proposed_fact = first_nonempty(
        row.get("normalized_value"),
        row.get("raw_value"),
        linked_facts[0].get("normalized_value") if linked_facts else "",
        linked_facts[0].get("raw_value") if linked_facts else "",
    )
    conflict_claims = [claim for claim in linked_claims if str(claim.get("status") or "").lower() in ("disputed", "contradicted", "rejected", "needs_more_evidence")]
    ledger_id = f"{object_type}:{object_id or source_id}"
    result = {
        **source,
        "ledger_id": ledger_id,
        "object_type": object_type,
        "object_id": object_id or source_id,
        "review_state": status,
        "evidence_type": evidence_type,
        "anchor_type": anchor_type_for(row, anchor),
        "anchor_label": anchor_label_for(row, anchor),
        "quote": compact_text(quote, 2000),
        "normalized_observation": compact_text(normalized_observation, 2000),
        "proposed_fact": compact_text(proposed_fact, 1200),
        "note": row.get("note") or "",
        "actor": row.get("actor") or "",
        "created_at": row.get("created_at") or source.get("captured_at"),
        "updated_at": row.get("updated_at") or source.get("last_ingested_at"),
        "fact_count": len({fact.get("proposed_fact_id") for fact in linked_facts if fact.get("proposed_fact_id")}),
        "claim_count": len({claim.get("claim_id") for claim in linked_claims if claim.get("claim_id")}),
        "correction_count": len({correction.get("correction_id") for correction in linked_corrections if correction.get("correction_id")}),
        "annotation_count": len({annotation.get("annotation_id") for annotation in linked_annotations if annotation.get("annotation_id")}),
        "claim_conflict": bool(conflict_claims),
        "claim_conflict_label": "possible conflict" if conflict_claims else ("linked claims" if linked_claims else "no linked claim"),
        "capture_ref": first_nonempty(source.get("last_ingested_at"), source.get("captured_at"), source_id),
        "capture_hash": "not recorded",
        "match_explanation": evidence_search_explanation(row, mode, q),
        "immutable_note": "Review state applies only to this object; source captures remain immutable.",
        "can_update_review_state": object_type in REVIEW_OBJECT_CONFIGS,
    }
    return result


EVIDENCE_QUEUE_LABELS = [
    ("all", "All evidence"),
    ("review_objects", "Review objects"),
    ("source_candidates", "Source candidates"),
    ("claim_conflicts", "Claim conflicts"),
    ("unlinked_evidence", "Unlinked evidence"),
    ("structured_facts", "Structured facts"),
    ("claim_ready", "Claim-linked"),
]


def evidence_queue_match(row, queue):
    if not queue or queue == "all":
        return True
    if queue == "review_objects":
        return row.get("object_type") != "evidence_candidate"
    if queue == "source_candidates":
        return row.get("object_type") == "evidence_candidate"
    if queue == "claim_conflicts":
        return bool(row.get("claim_conflict"))
    if queue == "unlinked_evidence":
        return int(row.get("claim_count") or 0) == 0 and row.get("object_type") in ("evidence_selection", "evidence_candidate")
    if queue == "structured_facts":
        return row.get("object_type") == "proposed_fact" or int(row.get("fact_count") or 0) > 0
    if queue == "claim_ready":
        return int(row.get("claim_count") or 0) > 0
    return True


def evidence_queue_counts(rows):
    return [
        {"id": queue_id, "label": label, "count": sum(1 for row in rows if evidence_queue_match(row, queue_id))}
        for queue_id, label in EVIDENCE_QUEUE_LABELS
    ]


def evidence_row_matches(row, q, queue, evidence_type, review_state, source_kind, anchor_type, project):
    if not evidence_queue_match(row, queue):
        return False
    if evidence_type and evidence_type not in (row.get("evidence_type"), row.get("object_type"), row.get("anchor_type")):
        return False
    if review_state and review_state != row.get("review_state"):
        return False
    if source_kind and source_kind != row.get("source_kind"):
        return False
    if anchor_type and anchor_type != row.get("anchor_type"):
        return False
    if project and project != row.get("source_project"):
        return False
    if q:
        haystack = " ".join(str(row.get(key) or "") for key in (
            "ledger_id", "object_type", "object_id", "review_state", "evidence_type",
            "anchor_type", "anchor_label", "quote", "normalized_observation",
            "proposed_fact", "note", "title", "canonical_url", "snippet",
            "author_handle", "domain", "source_project",
        ))
        if q.lower() not in haystack.lower():
            return False
    return True


def evidence_facet_counts(rows, field):
    counts = {}
    for row in rows:
        value = row.get(field) or "unknown"
        counts[value] = counts.get(value, 0) + 1
    return [{"id": key, "label": title_case_label(key), "count": counts[key]} for key in sorted(counts, key=lambda item: (-counts[item], item))]


def title_case_label(value):
    return str(value or "unknown").replace("_", " ").title()


def evidence_preview(row, source_map, facts_by_selection, facts_by_source, claims_by_selection, claims_by_source, corrections_by_source, annotations_by_selection, annotations_by_source):
    if not row:
        return {}
    source_id = row.get("source_evidence_id") or ""
    object_id = row.get("object_id") or ""
    selection_id = object_id if row.get("object_type") == "evidence_selection" else ""
    linked_facts = facts_by_selection.get(selection_id, []) + facts_by_source.get(source_id, [])
    linked_claims = claims_by_selection.get(selection_id, []) + claims_by_source.get(source_id, [])
    linked_corrections = corrections_by_source.get(source_id, [])
    linked_annotations = annotations_by_selection.get(selection_id, []) + annotations_by_source.get(source_id, [])
    source = source_for_ledger_row(source_map, source_id)
    return {
        "row": row,
        "source": source,
        "linked_facts": linked_facts[:20],
        "linked_claims": linked_claims[:20],
        "linked_corrections": linked_corrections[:20],
        "linked_annotations": linked_annotations[:20],
        "provenance": [
            {"label": "Source capture", "value": source.get("canonical_url") or source_id, "meta": source.get("captured_at") or ""},
            {"label": "Normalized source row", "value": source_id, "meta": source.get("last_ingested_at") or ""},
            {"label": "Ledger object", "value": row.get("ledger_id") or "", "meta": row.get("updated_at") or ""},
            {"label": "Anchor", "value": row.get("anchor_label") or row.get("anchor_type") or "source record", "meta": row.get("anchor_type") or ""},
            {"label": "Review state", "value": row.get("review_state") or "", "meta": "object-specific state only"},
        ],
    }


def evidence_ledger(params):
    limit = sql_int(params.get("limit", ["120"])[0], 120)
    fetch_limit = max(limit * 3, 150)
    q = (params.get("q", [""])[0] or "").strip()
    mode = (params.get("mode", ["hybrid"])[0] or "hybrid").strip()
    queue = (params.get("queue", ["all"])[0] or "all").strip()
    evidence_type = (params.get("type", [""])[0] or params.get("kind", [""])[0] or "").strip()
    review_state = (params.get("review_state", [""])[0] or "").strip()
    source_kind = (params.get("source_kind", [""])[0] or "").strip()
    anchor_type = (params.get("anchor_type", [""])[0] or "").strip()
    project = (params.get("project", [""])[0] or "").strip()
    inspect = (params.get("inspect", [""])[0] or "").strip()
    if inspect.startswith("evidence:"):
        inspect = inspect.removeprefix("evidence:")

    # When a project filter is supplied, scope each review-table query at the
    # SQL level via the evidence_events lookup, so ClickHouse filters instead of
    # fetching fetch_limit rows per table and filtering in Python afterwards.
    project_filter = ""
    if project:
        project_filter = (
            f" WHERE source_evidence_id IN "
            f"(SELECT evidence_id FROM evidence_events FINAL WHERE source_project = {sql_string(project)})"
        )
    selections = ch_data(
        f"""
        SELECT
          selection_id, source_evidence_id, document_id, block_id, selection_kind,
          quote, context_before, context_after, source_anchor_json, status, note,
          actor, created_at, updated_at
        FROM evidence_selections FINAL
        {project_filter}
        ORDER BY updated_at DESC
        LIMIT {fetch_limit}
        """,
        fallback=[],
    )
    proposed = ch_data(
        f"""
        SELECT
          proposed_fact_id, source_evidence_id, evidence_selection_id, fact_type,
          field_path, raw_value, normalized_value, unit, entities_json,
          evidence_quote, source_anchor_json, status, note, actor, created_at,
          updated_at
        FROM proposed_facts FINAL
        {project_filter}
        ORDER BY updated_at DESC
        LIMIT {fetch_limit}
        """,
        fallback=[],
    )
    corrections = ch_data(
        f"""
        SELECT
          correction_id, source_evidence_id, document_id, block_id, correction_kind,
          original_text, corrected_text, source_anchor_json, status, note,
          actor, created_at, updated_at
        FROM normalized_corrections FINAL
        {project_filter}
        ORDER BY updated_at DESC
        LIMIT {fetch_limit}
        """,
        fallback=[],
    )
    annotations = ch_data(
        f"""
        SELECT
          annotation_id, source_evidence_id, evidence_selection_id, annotation_type,
          body, status, source_anchor_json, actor, created_at, updated_at
        FROM review_annotations FINAL
        {project_filter}
        ORDER BY updated_at DESC
        LIMIT {fetch_limit}
        """,
        fallback=[],
    )
    claims = ch_data(
        f"""
        SELECT
          claim_id, source_evidence_id, evidence_selection_id, claim_text,
          claim_type, evidence_relation, qualifier_json, source_anchor_json,
          status, note, actor, created_at, updated_at
        FROM claim_records FINAL
        {project_filter}
        ORDER BY updated_at DESC
        LIMIT {fetch_limit}
        """,
        fallback=[],
    )
    recent_where = f"evidence_events.source_project = {sql_string(project)}" if project else "1 = 1"
    recent = [decorate_source_row(row) for row in latest_source_rows(recent_where, fetch_limit)]

    source_ids = []
    for rows, key in (
        (selections, "source_evidence_id"),
        (proposed, "source_evidence_id"),
        (corrections, "source_evidence_id"),
        (annotations, "source_evidence_id"),
        (claims, "source_evidence_id"),
        (recent, "evidence_id"),
    ):
        source_ids.extend(row.get(key) for row in rows)
    source_map = hydrate_source_rows(source_ids)
    for row in recent:
        source_map.setdefault(row.get("evidence_id"), row)

    facts_by_selection = group_rows(proposed, "evidence_selection_id")
    facts_by_source = group_rows(proposed, "source_evidence_id")
    claims_by_selection = group_rows(claims, "evidence_selection_id")
    claims_by_source = group_rows(claims, "source_evidence_id")
    corrections_by_source = group_rows(corrections, "source_evidence_id")
    annotations_by_selection = group_rows(annotations, "evidence_selection_id")
    annotations_by_source = group_rows(annotations, "source_evidence_id")

    all_rows = []
    for row in selections:
        all_rows.append(make_evidence_row(row, "evidence_selection", row.get("selection_id"), source_map, facts_by_selection, facts_by_source, claims_by_selection, claims_by_source, corrections_by_source, annotations_by_selection, annotations_by_source, mode, q))
    for row in proposed:
        all_rows.append(make_evidence_row(row, "proposed_fact", row.get("proposed_fact_id"), source_map, facts_by_selection, facts_by_source, claims_by_selection, claims_by_source, corrections_by_source, annotations_by_selection, annotations_by_source, mode, q))
    for row in corrections:
        all_rows.append(make_evidence_row(row, "normalized_correction", row.get("correction_id"), source_map, facts_by_selection, facts_by_source, claims_by_selection, claims_by_source, corrections_by_source, annotations_by_selection, annotations_by_source, mode, q))
    for row in annotations:
        all_rows.append(make_evidence_row(row, "annotation", row.get("annotation_id"), source_map, facts_by_selection, facts_by_source, claims_by_selection, claims_by_source, corrections_by_source, annotations_by_selection, annotations_by_source, mode, q))
    for row in claims:
        all_rows.append(make_evidence_row(row, "claim_stub", row.get("claim_id"), source_map, facts_by_selection, facts_by_source, claims_by_selection, claims_by_source, corrections_by_source, annotations_by_selection, annotations_by_source, mode, q))
    for row in recent[:limit]:
        candidate = {
            **row,
            "source_evidence_id": row.get("evidence_id"),
            "status": "candidate",
            "snippet": row.get("snippet") or "",
            "updated_at": row.get("last_ingested_at") or "",
        }
        all_rows.append(make_evidence_row(candidate, "evidence_candidate", row.get("evidence_id"), source_map, facts_by_selection, facts_by_source, claims_by_selection, claims_by_source, corrections_by_source, annotations_by_selection, annotations_by_source, mode, q))

    all_rows.sort(key=lambda item: str(item.get("updated_at") or item.get("last_ingested_at") or ""), reverse=True)
    filtered = [row for row in all_rows if evidence_row_matches(row, q, queue, evidence_type, review_state, source_kind, anchor_type, project)]
    rows = filtered[:limit]
    selected = next((row for row in rows if row.get("ledger_id") == inspect), None) or (rows[0] if rows else None)
    return {
        "scope": {
            "mode": mode,
            "queue": queue,
            "q": q,
            "type": evidence_type,
            "review_state": review_state,
            "source_kind": source_kind,
            "anchor_type": anchor_type,
            "project": project,
            "limit": limit,
        },
        "summary": {
            "objects": len(all_rows),
            "visible": len(filtered),
            "selections": len(selections),
            "proposed_facts": len(proposed),
            "normalized_corrections": len(corrections),
            "annotations": len(annotations),
            "claims": len(claims),
            "source_candidates": sum(1 for row in all_rows if row.get("object_type") == "evidence_candidate"),
            "claim_conflicts": sum(1 for row in all_rows if row.get("claim_conflict")),
        },
        "facets": {
            "queues": evidence_queue_counts(all_rows),
            "evidence_types": evidence_facet_counts(all_rows, "evidence_type"),
            "object_types": evidence_facet_counts(all_rows, "object_type"),
            "review_states": evidence_facet_counts(all_rows, "review_state"),
            "source_kinds": evidence_facet_counts(all_rows, "source_kind"),
            "projects": evidence_facet_counts(all_rows, "source_project"),
            "anchor_types": evidence_facet_counts(all_rows, "anchor_type"),
        },
        "results": cursor_page(rows, len(filtered), limit),
        "rows": rows,
        "selected_id": selected.get("ledger_id") if selected else "",
        "preview": evidence_preview(selected, source_map, facts_by_selection, facts_by_source, claims_by_selection, claims_by_source, corrections_by_source, annotations_by_selection, annotations_by_source),
        "generated_at": now_iso(),
        "stale": False,
        "permissions": ["review", "anchor", "annotate", "accept", "reject"],
        "version": "evidence-ledger.v2",
    }


ENTITY_QUEUE_LABELS = [
    ("all", "All entities"),
    ("unresolved", "Unresolved candidates"),
    ("canonical", "Canonical identities"),
    ("merge_clusters", "Merge clusters"),
    ("pending_relations", "Pending relations"),
    ("extracted", "Extracted only"),
]


def entity_identity_key(row):
    return first_nonempty(row.get("canonical_entity_id"), row.get("canonical_name"), row.get("mention_text"), row.get("entity")).lower()


def entity_source_ids(row):
    ids = row.get("sample_source_ids")
    if isinstance(ids, list):
        return [item for item in ids if item]
    source_id = row.get("source_evidence_id") or row.get("evidence_id") or ""
    return [source_id] if source_id else []


def entity_queue_match(row, queue):
    if not queue or queue == "all":
        return True
    if queue == "unresolved":
        return row.get("row_kind") == "entity_candidate" and row.get("review_state") not in ("matched", "created", "merged", "rejected")
    if queue == "canonical":
        return row.get("row_kind") == "canonical_entity"
    if queue == "merge_clusters":
        return row.get("row_kind") == "merge_cluster" or int(row.get("alias_count") or 0) > 1
    if queue == "pending_relations":
        return int(row.get("pending_relation_count") or 0) > 0
    if queue == "extracted":
        return row.get("row_kind") == "extracted_entity"
    return True


def entity_queue_counts(rows):
    return [
        {"id": queue_id, "label": label, "count": sum(1 for row in rows if entity_queue_match(row, queue_id))}
        for queue_id, label in ENTITY_QUEUE_LABELS
    ]


def make_entity_link_row(row, source_map, claim_counts):
    source_id = row.get("source_evidence_id") or ""
    source = source_for_ledger_row(source_map, source_id)
    canonical = first_nonempty(row.get("canonical_name"), row.get("canonical_entity_id"))
    review_state = row.get("status") or "proposed"
    return {
        **source,
        "entity_row_id": f"entity_link:{row.get('entity_link_id')}",
        "row_kind": "entity_candidate",
        "object_type": "entity_link",
        "object_id": row.get("entity_link_id") or "",
        "entity_name": first_nonempty(canonical, row.get("mention_text"), "(unnamed entity)"),
        "mention_text": row.get("mention_text") or "",
        "entity_type": row.get("entity_type") or "unknown",
        "canonical_entity_id": row.get("canonical_entity_id") or "",
        "canonical_name": row.get("canonical_name") or "",
        "review_state": review_state,
        "match_reason": "Human/model candidate from source-anchored mention; identity resolution only.",
        "match_confidence": "review",
        "mention_count": 1,
        "source_count": 1 if source_id else 0,
        "alias_count": 1 if canonical and canonical.lower() != (row.get("mention_text") or "").lower() else 0,
        "pending_relation_count": int(claim_counts.get(source_id) or 0),
        "updated_at": row.get("updated_at") or source.get("last_ingested_at"),
        "created_at": row.get("created_at") or source.get("captured_at"),
        "note": row.get("note") or "",
        "actor": row.get("actor") or "",
        "can_update_review_state": True,
    }


def make_extracted_entity_row(row, source_map, claim_counts):
    source_ids = entity_source_ids(row)
    sample_source = source_for_ledger_row(source_map, source_ids[0] if source_ids else "")
    pending = sum(int(claim_counts.get(source_id) or 0) for source_id in source_ids)
    return {
        **sample_source,
        "entity_row_id": f"extracted_entity:{row.get('entity')}",
        "row_kind": "extracted_entity",
        "object_type": "extracted_entity",
        "object_id": row.get("entity") or "",
        "entity_name": row.get("entity") or "(unnamed entity)",
        "mention_text": row.get("entity") or "",
        "entity_type": "unknown",
        "canonical_entity_id": "",
        "canonical_name": "",
        "review_state": "candidate",
        "match_reason": "Extracted entity string from normalized source metadata; needs canonical identity review.",
        "match_confidence": "unreviewed",
        "mention_count": int(row.get("mentions") or 0),
        "source_count": int(row.get("sources") or 0),
        "alias_count": 0,
        "pending_relation_count": pending,
        "sample_source_ids": source_ids,
        "updated_at": row.get("last_seen") or sample_source.get("last_ingested_at"),
        "created_at": row.get("last_seen") or sample_source.get("captured_at"),
        "note": "",
        "actor": "",
        "can_update_review_state": False,
    }


def make_canonical_entity_rows(entity_links, source_map, claim_counts):
    groups = {}
    for row in entity_links:
        key = entity_identity_key(row)
        if not key or not first_nonempty(row.get("canonical_name"), row.get("canonical_entity_id")):
            continue
        groups.setdefault(key, []).append(row)
    rows = []
    for key, group in groups.items():
        source_ids = sorted({row.get("source_evidence_id") for row in group if row.get("source_evidence_id")})
        names = sorted({name for row in group for name in (row.get("mention_text"), row.get("canonical_name")) if name})
        sample = group[0]
        source = source_for_ledger_row(source_map, source_ids[0] if source_ids else "")
        canonical_name = first_nonempty(sample.get("canonical_name"), sample.get("canonical_entity_id"), names[0] if names else key)
        row_kind = "merge_cluster" if len(names) > 1 or len(group) > 1 else "canonical_entity"
        rows.append({
            **source,
            "entity_row_id": f"{row_kind}:{key}",
            "row_kind": row_kind,
            "object_type": row_kind,
            "object_id": key,
            "entity_name": canonical_name,
            "mention_text": ", ".join(names[:6]),
            "entity_type": sample.get("entity_type") or "unknown",
            "canonical_entity_id": sample.get("canonical_entity_id") or key,
            "canonical_name": canonical_name,
            "review_state": "canonical" if row_kind == "canonical_entity" else "merge_review",
            "match_reason": "Canonical group built from reviewed entity links and aliases.",
            "match_confidence": "curated",
            "mention_count": len(group),
            "source_count": len(source_ids),
            "alias_count": len(names),
            "pending_relation_count": sum(int(claim_counts.get(source_id) or 0) for source_id in source_ids),
            "sample_source_ids": source_ids,
            "updated_at": max(str(row.get("updated_at") or "") for row in group),
            "created_at": min(str(row.get("created_at") or "") for row in group),
            "note": "Identity row; aliases, facts, claims, and relationships remain separately reviewable.",
            "actor": "",
            "can_update_review_state": False,
        })
    return rows


def entity_row_matches(row, q, queue, entity_type, review_state, source_kind, project):
    if not entity_queue_match(row, queue):
        return False
    if entity_type and entity_type != row.get("entity_type"):
        return False
    if review_state and review_state != row.get("review_state"):
        return False
    if source_kind and source_kind != row.get("source_kind"):
        return False
    if project and project != row.get("source_project"):
        return False
    if q:
        haystack = " ".join(str(row.get(key) or "") for key in (
            "entity_row_id", "row_kind", "object_id", "entity_name", "mention_text",
            "canonical_entity_id", "canonical_name", "entity_type", "review_state",
            "match_reason", "title", "canonical_url", "domain", "author_handle",
        ))
        if q.lower() not in haystack.lower():
            return False
    return True


def entity_preview(row, entity_links, claims, source_map):
    if not row:
        return {}
    name = (row.get("entity_name") or row.get("mention_text") or "").lower()
    object_id = row.get("object_id") or ""
    source_ids = set(row.get("sample_source_ids") or [])
    if row.get("source_evidence_id"):
        source_ids.add(row.get("source_evidence_id"))
    mentions = []
    for link in entity_links:
        link_name = first_nonempty(link.get("canonical_name"), link.get("mention_text")).lower()
        if link.get("entity_link_id") == object_id or (name and name in link_name) or (link.get("source_evidence_id") in source_ids):
            source = source_for_ledger_row(source_map, link.get("source_evidence_id") or "")
            mentions.append({**link, "source_title": source.get("title"), "source_kind": source.get("source_kind"), "canonical_url": source.get("canonical_url")})
    relationship_claims = []
    for claim in claims:
        claim_text = (claim.get("claim_text") or "").lower()
        if claim.get("source_evidence_id") in source_ids or (name and name in claim_text):
            relationship_claims.append(claim)
    matches = []
    canonical = first_nonempty(row.get("canonical_name"), row.get("canonical_entity_id"))
    if canonical:
        matches.append({
            "candidate": canonical,
            "reason": row.get("match_reason") or "Existing canonical candidate.",
            "state": row.get("review_state") or "",
        })
    if row.get("mention_text") and row.get("mention_text") != canonical:
        matches.append({
            "candidate": row.get("mention_text"),
            "reason": "Mention text is preserved as an alias candidate.",
            "state": "alias_candidate",
        })
    source = source_for_ledger_row(source_map, row.get("source_evidence_id") or (next(iter(source_ids), "")))
    return {
        "row": row,
        "source": source,
        "mentions": mentions[:30],
        "proposed_matches": matches[:12],
        "relationship_proposals": relationship_claims[:20],
        "provenance": [
            {"label": "Identity candidate", "value": row.get("entity_name") or "", "meta": row.get("row_kind") or ""},
            {"label": "Source mentions", "value": f"{row.get('mention_count') or len(mentions)} mention(s)", "meta": f"{row.get('source_count') or len(source_ids)} source(s)"},
            {"label": "Canonical match", "value": canonical or "not selected", "meta": "identity only"},
            {"label": "Relations", "value": f"{len(relationship_claims)} relationship/claim candidate(s)", "meta": "separate review object"},
            {"label": "Updated", "value": row.get("updated_at") or "", "meta": row.get("actor") or ""},
        ],
    }


def conflict_cluster(params):
    """ConflictClusterReadModel (spec section 18) for one cluster id.

    clusterId is the parsed subject claims are grouped by (see
    claim_subject_value). Projects the assertion cards, resolution options, and
    prior reviewer decisions for that subject.
    """
    import urllib.parse
    raw = (params.get("cluster_id", [""])[0] or "").strip()
    cluster_id = urllib.parse.unquote(raw)
    claims = ch_data(
        f"""
        SELECT claim_id, source_evidence_id, evidence_selection_id, claim_text,
               claim_type, evidence_relation, qualifier_json, status, note,
               actor, created_at, updated_at
        FROM claim_records FINAL
        ORDER BY updated_at DESC
        LIMIT 1000
        """,
        fallback=[],
    )
    members = []
    for claim in claims:
        parsed = claim_subject_value(claim)
        subject = parsed.get("subject") or ""
        # Match by exact subject, or by claim_id when the cluster id is a single
        # claim anchor (so a disputed claim resolves to its own cluster).
        if subject and subject.lower() == cluster_id.lower():
            members.append(claim)
        elif claim.get("claim_id") == cluster_id:
            members.append(claim)
    source_ids = {c.get("source_evidence_id") for c in members if c.get("source_evidence_id")}
    source_map = hydrate_source_rows(list(source_ids))
    assertions = []
    for c in members:
        parsed = claim_subject_value(c)
        relation = (c.get("evidence_relation") or "").lower()
        status = c.get("status") or "under_review"
        source = source_for_ledger_row(source_map, c.get("source_evidence_id") or "")
        assertions.append({
            "claim_id": c.get("claim_id"),
            "value": parsed.get("value") or c.get("claim_text") or "",
            "qualifiers": parse_raw_json(c.get("qualifier_json") or "{}"),
            "effective_date": (c.get("updated_at") or "")[:10],
            "source_evidence_id": c.get("source_evidence_id") or "",
            "source_title": source.get("title") or "",
            "source_kind": source.get("source_kind") or "",
            "evidence_relation": c.get("evidence_relation") or "",
            "review_state": status,
            "contradiction_state": claim_contradiction_state(c, len(members)),
        })
    assertions.sort(key=lambda a: str(a.get("effective_date") or ""), reverse=True)
    body = {
        "cluster_id": cluster_id,
        "subject": cluster_id,
        "assertion_count": len(assertions),
        "assertions": assertions,
        "resolution_options": [
            "genuine_contradiction", "different_scope", "different_version",
            "superseded", "duplicate_assertion", "insufficient_evidence",
            "leave_unresolved", "request_additional_evidence",
        ],
        "reason_codes": [
            "newer_evidence", "stronger_source", "broader_scope", "methodology_flaw",
            "source_bias", "temporal_change", "unresolved",
        ],
        "prior_decisions": [
            {"claim_id": a["claim_id"], "review_state": a["review_state"],
             "contradiction_state": a["contradiction_state"], "actor": ""}
            for a in assertions if a["review_state"] in ("accepted", "rejected", "disputed", "superseded")
        ],
    }
    return read_envelope(
        body,
        version="conflict-cluster.v1",
        generated_at=now_iso(),
        stale=False,
        permissions=["resolve", "reopen", "request_evidence"],
        scope={"cluster_id": cluster_id},
    )


def resolve_conflict(payload):
    """Conflicts.Resolve (spec section 29): record a conflict resolution.

    Honors spec section 18 ("No assertion is deleted by resolving a conflict"):
    the resolution is a review event capturing the preferred assertion + reason;
    claims are NOT mutated to a terminal state by this call. If a preference is
    expressed, the preferred claim is promoted via the human review path
    (update_review_state with a human actor) and the others are annotated.
    """
    cluster_id = compact_text(payload.get("cluster_id"), 300)
    resolution = compact_text(payload.get("resolution"), 80)
    reason_code = compact_text(payload.get("reason_code"), 80)
    preferred_claim_id = compact_text(payload.get("preferred_claim_id"), 300)
    reviewer_note = compact_text(payload.get("note"), 20000)
    actor = compact_text(payload.get("actor") or REVIEW_ACTOR, 200)
    if not cluster_id:
        raise ResearchUiError(400, "cluster_id is required")
    if not resolution:
        raise ResearchUiError(400, "resolution is required")
    allowed_resolutions = {
        "genuine_contradiction", "different_scope", "different_version",
        "superseded", "duplicate_assertion", "insufficient_evidence",
        "leave_unresolved", "request_additional_evidence",
    }
    if resolution not in allowed_resolutions:
        raise ResearchUiError(400, f"resolution {resolution!r} is not valid; allowed: {sorted(allowed_resolutions)}")
    # If a preferred assertion is named and the resolution implies promoting it,
    # route through the human review path (Phase 2 guards apply: terminal-state,
    # machine-origin). This keeps the epistemic rule intact.
    promoted = None
    if preferred_claim_id and resolution in ("superseded", "duplicate_assertion", "different_version"):
        try:
            promoted = update_review_state({
                "subject_type": "claim_stub",
                "subject_id": preferred_claim_id,
                "status": "accepted",
                "actor": actor if actor_kind(actor) == "human" else REVIEW_ACTOR,
                "note": f"conflict resolution: {resolution} ({reason_code or 'no reason'}) {reviewer_note}".strip(),
                "expected_version": compact_text(payload.get("expected_version"), 120),
            })
        except ResearchUiError:
            promoted = None  # preferred claim may be terminal already; resolution still records
    event_payload = {
        # Cluster-level events have no single source; synthesize a stable id so
        # build_review_event's source_evidence_id requirement is satisfied.
        "source_evidence_id": f"conflict:{cluster_id}",
        "subject_type": "conflict_cluster",
        "subject_id": cluster_id,
        "cluster_id": cluster_id,
        "resolution": resolution,
        "reason_code": reason_code,
        "preferred_claim_id": preferred_claim_id,
        "note": reviewer_note,
        "actor": actor,
    }
    event = persist_review_event(build_review_event("conflict.resolved", event_payload))
    return {"event": event, "resolution": resolution, "reason_code": reason_code, "preferred_claim_id": preferred_claim_id, "promoted": promoted}


def entity_detail(params):
    """EntityDetailReadModel (spec section 16) for one entity.

    Projects entity_links + claim_records + evidence_events for a single
    canonical_entity_id / entity_row_id into the section-16 fact-ledger shape.
    """
    raw_id = (params.get("entity_id", [""])[0] or "").strip()
    if raw_id.startswith("entity:"):
        raw_id = raw_id.removeprefix("entity:")
    # The directory mints composite ids (canonical_entity:<name>,
    # entity_link:<id>, extracted_entity:<name>, merge_cluster:<name>). Resolve
    # the canonical name + the underlying link rows for whichever id shape this is.
    canonical_name = ""
    link_filter_ids = []  # entity_link_id values to include
    if raw_id.startswith("canonical_entity:"):
        canonical_name = raw_id.removeprefix("canonical_entity:")
    elif raw_id.startswith("entity_link:"):
        link_filter_ids = [raw_id.removeprefix("entity_link:")]
    elif raw_id.startswith("extracted_entity:") or raw_id.startswith("merge_cluster:"):
        canonical_name = raw_id.split(":", 1)[1] if ":" in raw_id else raw_id
    else:
        # Bare id: treat as either a canonical name or a link id.
        canonical_name = raw_id

    curated = ch_data(
        f"""
        SELECT entity_link_id, source_evidence_id, evidence_selection_id, mention_text,
               entity_type, canonical_entity_id, canonical_name, source_anchor_json,
               status, note, actor, created_at, updated_at
        FROM entity_links FINAL
        ORDER BY updated_at DESC
        LIMIT 500
        """,
        fallback=[],
    )
    # Resolve the canonical identity: prefer an explicit canonical_name match;
    # fall back to the link rows whose ids were requested.
    name_lower = canonical_name.lower()
    identity_links = []
    if link_filter_ids:
        identity_links = [row for row in curated if row.get("entity_link_id") in link_filter_ids]
    if not identity_links and name_lower:
        identity_links = [
            row for row in curated
            if (row.get("canonical_name") or "").lower() == name_lower
            or (row.get("mention_text") or "").lower() == name_lower
        ]
    if not identity_links and link_filter_ids:
        identity_links = [row for row in curated if row.get("entity_link_id") in set(link_filter_ids)]

    canonical_entity_id = next((row.get("canonical_entity_id") for row in identity_links if row.get("canonical_entity_id")), "")
    canonical_name_resolved = next(
        (first_nonempty(row.get("canonical_name"), row.get("mention_text")) for row in identity_links),
        canonical_name,
    )
    entity_type = next((row.get("entity_type") for row in identity_links if row.get("entity_type")), "")
    aliases = sorted({
        first_nonempty(row.get("mention_text"), row.get("canonical_name"))
        for row in identity_links
        if first_nonempty(row.get("mention_text"), row.get("canonical_name"))
    } - {canonical_name_resolved})
    source_ids = {row.get("source_evidence_id") for row in identity_links if row.get("source_evidence_id")}
    review_state = next((row.get("status") for row in identity_links if row.get("status")), "unresolved")

    # Fact ledger: claims whose source or text touches this entity.
    claims = ch_data(
        f"""
        SELECT claim_id, source_evidence_id, evidence_selection_id, claim_text,
               claim_type, evidence_relation, qualifier_json, status, actor, updated_at
        FROM claim_records FINAL
        ORDER BY updated_at DESC
        LIMIT 800
        """,
        fallback=[],
    )
    name_tokens = [token for token in canonical_name_resolved.lower().split() if len(token) > 2]
    fact_rows = []
    for claim in claims:
        text_lower = (claim.get("claim_text") or "").lower()
        touches = claim.get("source_evidence_id") in source_ids or any(tok in text_lower for tok in name_tokens)
        if not touches:
            continue
        relation = (claim.get("evidence_relation") or "").lower()
        status = claim.get("status") or "under_review"
        fact_rows.append({
            "claim_id": claim.get("claim_id"),
            "property": claim.get("claim_type") or "claim",
            "value": claim.get("claim_text") or "",
            "qualifiers": parse_raw_json(claim.get("qualifier_json") or ""),
            "evidence_relation": claim.get("evidence_relation") or "",
            "supporting": relation in ("supports", "supporting", "supports_claim") and status in ("accepted", "published"),
            "refuting": relation in ("refutes", "contradicts") or status == "disputed",
            "review_state": status,
            "conflict_status": "disputed" if status == "disputed" else ("supported" if status in ("accepted", "published") else "under_review"),
            "source_evidence_id": claim.get("source_evidence_id") or "",
            "updated_at": claim.get("updated_at") or "",
        })
    fact_rows.sort(key=lambda r: str(r.get("updated_at") or ""), reverse=True)

    source_map = hydrate_source_rows(list(source_ids) + [r.get("source_evidence_id") for r in fact_rows])
    supporting_count = sum(1 for r in fact_rows if r["supporting"])
    refuting_count = sum(1 for r in fact_rows if r["refuting"])
    conflict_count = sum(1 for r in fact_rows if r["conflict_status"] == "disputed")
    source_count = len(source_ids)

    header = {
        "entity_row_id": raw_id,
        "canonical_name": canonical_name_resolved,
        "canonical_entity_id": canonical_entity_id,
        "entity_type": entity_type or "topic",
        "aliases": aliases[:30],
        "review_state": review_state,
        "source_count": source_count,
        "claim_count": len(fact_rows),
        "supporting_count": supporting_count,
        "refuting_count": refuting_count,
        "conflict_count": conflict_count,
    }
    mentions = [
        {
            "mention_text": row.get("mention_text"),
            "canonical_name": row.get("canonical_name"),
            "source_evidence_id": row.get("source_evidence_id"),
            "source_title": source_for_ledger_row(source_map, row.get("source_evidence_id") or "").get("title"),
            "status": row.get("status"),
            "updated_at": row.get("updated_at"),
        }
        for row in identity_links[:60]
    ]
    body = {
        "header": header,
        "fact_ledger": fact_rows[:200],
        "mentions": mentions,
        "sources": [
            {"source_evidence_id": sid, **{k: v for k, v in source_for_ledger_row(source_map, sid).items() if k in ("title", "source_kind", "canonical_url", "domain")}}
            for sid in sorted(source_ids)
        ][:80],
        "tabs": ["overview", "claims", "sources", "relationships", "timeline", "artifacts", "notes", "audit"],
    }
    return read_envelope(
        body,
        version="entity-detail.v1",
        generated_at=now_iso(),
        stale=False,
        permissions=["review", "merge", "split", "alias", "reject", "add_claim", "add_source"],
        scope={"entity_id": raw_id},
    )


def entity_directory(params):
    limit = sql_int(params.get("limit", ["120"])[0], 120)
    fetch_limit = max(limit * 3, 180)
    q = (params.get("q", [""])[0] or "").strip()
    queue = (params.get("queue", ["all"])[0] or "all").strip()
    entity_type = (params.get("entity_type", [""])[0] or "").strip()
    review_state = (params.get("review_state", [""])[0] or "").strip()
    source_kind = (params.get("source_kind", [""])[0] or "").strip()
    project = (params.get("project", [""])[0] or "").strip()
    inspect = (params.get("inspect", [""])[0] or "").strip()
    if inspect.startswith("entity:"):
        inspect = inspect.removeprefix("entity:")

    curated = ch_data(
        f"""
        SELECT
          entity_link_id, source_evidence_id, evidence_selection_id, mention_text,
          entity_type, canonical_entity_id, canonical_name, source_anchor_json,
          status, note, actor, created_at, updated_at
        FROM entity_links FINAL
        ORDER BY updated_at DESC
        LIMIT {fetch_limit}
        """,
        fallback=[],
    )
    extracted = ch_data(
        f"""
        SELECT
          entity,
          count() AS mentions,
          uniqExact(evidence_id) AS sources,
          groupArray(12)(evidence_id) AS sample_source_ids,
          max(ingested_at) AS last_seen
        FROM
        (
          SELECT arrayJoin(entities) AS entity, evidence_id, ingested_at
          FROM evidence_events
        )
        WHERE entity != ''
        GROUP BY entity
        ORDER BY mentions DESC, last_seen DESC
        LIMIT {fetch_limit}
        """,
        fallback=[],
    )
    claims = ch_data(
        f"""
        SELECT
          claim_id, source_evidence_id, evidence_selection_id, claim_text,
          claim_type, evidence_relation, status, updated_at
        FROM claim_records FINAL
        ORDER BY updated_at DESC
        LIMIT {fetch_limit}
        """,
        fallback=[],
    )
    source_ids = []
    source_ids.extend(row.get("source_evidence_id") for row in curated)
    source_ids.extend(row.get("source_evidence_id") for row in claims)
    for row in extracted:
        source_ids.extend(entity_source_ids(row))
    source_map = hydrate_source_rows(source_ids)
    claim_counts = {}
    for claim in claims:
        source_id = claim.get("source_evidence_id") or ""
        if source_id:
            claim_counts[source_id] = claim_counts.get(source_id, 0) + 1

    rows = []
    rows.extend(make_canonical_entity_rows(curated, source_map, claim_counts))
    rows.extend(make_entity_link_row(row, source_map, claim_counts) for row in curated)
    rows.extend(make_extracted_entity_row(row, source_map, claim_counts) for row in extracted)
    rows.sort(key=lambda row: str(row.get("updated_at") or ""), reverse=True)
    filtered = [row for row in rows if entity_row_matches(row, q, queue, entity_type, review_state, source_kind, project)]
    visible = filtered[:limit]
    selected = next((row for row in visible if row.get("entity_row_id") == inspect), None) or (visible[0] if visible else None)
    return {
        "scope": {
            "q": q,
            "queue": queue,
            "entity_type": entity_type,
            "review_state": review_state,
            "source_kind": source_kind,
            "project": project,
            "limit": limit,
        },
        "summary": {
            "entities": len(rows),
            "visible": len(filtered),
            "canonical": sum(1 for row in rows if row.get("row_kind") == "canonical_entity"),
            "candidates": sum(1 for row in rows if row.get("row_kind") in ("entity_candidate", "extracted_entity")),
            "merge_clusters": sum(1 for row in rows if row.get("row_kind") == "merge_cluster"),
            "pending_relations": sum(1 for row in rows if int(row.get("pending_relation_count") or 0) > 0),
        },
        "facets": {
            "queues": entity_queue_counts(rows),
            "entity_types": evidence_facet_counts(rows, "entity_type"),
            "review_states": evidence_facet_counts(rows, "review_state"),
            "row_kinds": evidence_facet_counts(rows, "row_kind"),
            "source_kinds": evidence_facet_counts(rows, "source_kind"),
            "projects": evidence_facet_counts(rows, "source_project"),
        },
        "results": cursor_page(visible, len(filtered), limit),
        "rows": visible,
        "selected_id": selected.get("entity_row_id") if selected else "",
        "preview": entity_preview(selected, curated, claims, source_map),
        "generated_at": now_iso(),
        "stale": False,
        "permissions": ["review", "merge", "split", "alias", "reject"],
        "version": "entity-directory.v2",
    }


CLAIM_QUEUE_LABELS = [
    ("all", "All claims"),
    ("accepted", "Accepted"),
    ("under_review", "Under review"),
    ("proposed_unsupported", "Proposed / unsupported"),
    ("disputed", "Disputed"),
    ("conflict_clusters", "Conflict clusters"),
    ("duplicates", "Duplicates / merge"),
    ("rejected_superseded", "Rejected / superseded"),
]


def claim_subject_value(row):
    text = compact_text(row.get("claim_text"), 2000)
    claim_type = row.get("claim_type") or "general"
    subject = ""
    value = text
    scoped = False
    if ":" in text:
        left, right = text.split(":", 1)
        subject = left.strip()
        value = right.strip()
        scoped = bool(subject)
    elif " is " in text.lower():
        parts = text.split(" is ", 1)
        if len(parts) == 2:
            subject = parts[0].strip()
            value = parts[1].strip()
            scoped = bool(subject)
    return {
        # Only claims with an explicitly parsed subject participate in conflict
        # clustering. Falling back to source_project/"Unscoped subject" for
        # free-text claims collapses unrelated claims in the same project into
        # one subject and manufactures false contradictions.
        "subject": subject if scoped else "",
        "subject_scoped": scoped,
        "property": claim_type,
        "value": value or text,
    }


def claim_contradiction_state(row, cluster_size=1):
    status = str(row.get("status") or "").lower()
    relation = str(row.get("evidence_relation") or "").lower()
    if status in ("disputed", "rejected") or relation in ("refutes", "contradicts"):
        return "disputed"
    if cluster_size > 1:
        return "conflict"
    if status in ("accepted", "published") and relation in ("supports", "supporting", "supports_claim"):
        return "supported"
    if not relation or relation in ("context", "related"):
        return "contextual"
    return "under_review"


def claim_queue_match(row, queue):
    if not queue or queue == "all":
        return True
    status = str(row.get("review_state") or "").lower()
    contradiction = str(row.get("contradiction_state") or "").lower()
    if queue == "accepted":
        return status in ("accepted", "published")
    if queue == "under_review":
        return status in ("under_review", "draft", "proposed") and contradiction not in ("disputed", "conflict")
    if queue == "proposed_unsupported":
        return status in ("draft", "proposed") and int(row.get("support_count") or 0) == 0
    if queue == "disputed":
        return status == "disputed" or contradiction == "disputed"
    if queue == "conflict_clusters":
        return row.get("row_kind") == "conflict_cluster" or contradiction == "conflict"
    if queue == "duplicates":
        return row.get("row_kind") == "duplicate_cluster" or int(row.get("duplicate_count") or 0) > 1
    if queue == "rejected_superseded":
        return status in ("rejected", "superseded")
    return True


def claim_queue_counts(rows):
    return [
        {"id": queue_id, "label": label, "count": sum(1 for row in rows if claim_queue_match(row, queue_id))}
        for queue_id, label in CLAIM_QUEUE_LABELS
    ]


def claim_proposition_key(parts):
    return "|".join([
        str(parts.get("subject") or "").lower(),
        str(parts.get("property") or "").lower(),
    ])


def make_claim_row(row, source_map, proposition_counts, text_counts, evidence_by_source, facts_by_source, entities_by_source):
    source_id = row.get("source_evidence_id") or ""
    source = source_for_ledger_row(source_map, source_id)
    parts = claim_subject_value({**row, **source})
    qualifier = parse_raw_json(row.get("qualifier_json", ""))
    relation = row.get("evidence_relation") or ""
    # Unscoped claims must not be looked up under the empty-subject key (which
    # would collapse them); they are counted under a unique key in claims_ledger.
    if parts.get("subject_scoped"):
        cluster_size = int(proposition_counts.get(claim_proposition_key(parts)) or 1)
    else:
        cluster_size = 1
    duplicate_count = int(text_counts.get((row.get("claim_text") or "").lower()) or 1)
    contradiction = claim_contradiction_state(row, cluster_size)
    # Aggregate support/refute/context from the linked evidence selections and
    # proposed facts for this claim's source, instead of a per-row 0/1 constant.
    linked_selections = evidence_by_source.get(source_id, [])
    linked_facts = facts_by_source.get(source_id, [])
    relation_lower = relation.lower()
    support_count = sum(1 for sel in linked_selections if str(sel.get("selection_kind") or "").lower() in ("quote", "text", "support", "supports")) + (1 if relation_lower in ("supports", "supporting", "supports_claim") else 0)
    refute_count = sum(1 for sel in linked_selections if str(sel.get("selection_kind") or "").lower() in ("refute", "refutes", "contradict")) + (1 if relation_lower in ("refutes", "contradicts") or contradiction == "disputed" else 0)
    context_count = sum(1 for sel in linked_selections if str(sel.get("selection_kind") or "").lower() in ("context", "related")) + (1 if relation_lower in ("context", "related") else 0)
    evidence_count = support_count + refute_count + context_count + len(linked_facts)
    return {
        **source,
        "claim_row_id": f"claim:{row.get('claim_id')}",
        "row_kind": "claim",
        "object_type": "claim_stub",
        "object_id": row.get("claim_id") or "",
        "claim_text": row.get("claim_text") or "",
        "subject": parts["subject"] if parts.get("subject_scoped") else "(unscoped)",
        "subject_scoped": bool(parts.get("subject_scoped")),
        "property": parts["property"],
        "value": parts["value"],
        "qualifier": qualifier,
        "claim_type": row.get("claim_type") or "general",
        "evidence_relation": relation,
        "review_state": row.get("status") or "draft",
        "contradiction_state": contradiction,
        "preferred_assertion": row.get("claim_text") or "",
        "assertion_count": cluster_size,
        "support_count": support_count,
        "refute_count": refute_count,
        "context_count": context_count,
        "evidence_count": evidence_count,
        "source_diversity": 1 if source_id else 0,
        "conflict_state": contradiction,
        "duplicate_count": duplicate_count,
        "publication_blockers": sum(1 for value in (contradiction == "disputed", support_count == 0, status_is_terminal_rejected(row.get("status"))) if value),
        "linked_entity_count": len(entities_by_source.get(source_id, [])),
        "linked_fact_count": len(facts_by_source.get(source_id, [])),
        "note": row.get("note") or "",
        "actor": row.get("actor") or "",
        "created_at": row.get("created_at") or source.get("captured_at"),
        "updated_at": row.get("updated_at") or source.get("last_ingested_at"),
        "can_update_review_state": True,
    }


def status_is_terminal_rejected(status):
    return str(status or "").lower() in ("rejected", "superseded")


def make_claim_cluster_rows(claim_rows):
    by_proposition = {}
    by_text = {}
    for row in claim_rows:
        # Only scoped claims (explicit subject) can form a conflict cluster.
        # Unscoped free-text claims are excluded so unrelated assertions do not
        # get manufactured into contradictions.
        if not row.get("subject_scoped"):
            continue
        proposition_key = "|".join([
            str(row.get("subject") or "").lower(),
            str(row.get("property") or row.get("claim_type") or "general").lower(),
        ])
        by_proposition.setdefault(proposition_key, []).append(row)
        by_text.setdefault((row.get("claim_text") or "").lower(), []).append(row)
    clusters = []
    for proposition_key, rows in by_proposition.items():
        distinct_values = {str(row.get("value") or row.get("claim_text") or "").lower() for row in rows}
        if len(rows) <= 1 or len(distinct_values) <= 1:
            continue
        claim_type = rows[0].get("claim_type") or "general"
        subject = rows[0].get("subject") or "Claim cluster"
        safe_key = hashlib.sha1(proposition_key.encode("utf-8")).hexdigest()[:16]
        clusters.append({
            **rows[0],
            "claim_row_id": f"conflict_cluster:{safe_key}",
            "row_kind": "conflict_cluster",
            "object_type": "claim_cluster",
            "object_id": proposition_key,
            "claim_text": f"{subject}: {len(rows)} competing assertions",
            "subject": subject,
            "property": claim_type,
            "value": f"{len(rows)} assertions",
            "review_state": "under_review",
            "contradiction_state": "conflict",
            "preferred_assertion": first_nonempty(*(row.get("claim_text") for row in rows)),
            "assertion_count": len(rows),
            "support_count": sum(int(row.get("support_count") or 0) for row in rows),
            "refute_count": sum(int(row.get("refute_count") or 0) for row in rows),
            "context_count": sum(int(row.get("context_count") or 0) for row in rows),
            "evidence_count": sum(int(row.get("evidence_count") or 0) for row in rows),
            "source_diversity": len({row.get("source_evidence_id") for row in rows if row.get("source_evidence_id")}),
            "publication_blockers": len(rows),
            "can_update_review_state": False,
        })
    for text, rows in by_text.items():
        if text and len(rows) > 1:
            clusters.append({
                **rows[0],
                "claim_row_id": f"duplicate_cluster:{text[:120]}",
                "row_kind": "duplicate_cluster",
                "object_type": "claim_cluster",
                "object_id": text[:300],
                "claim_text": rows[0].get("claim_text") or "Duplicate claim",
                "review_state": "merge_review",
                "contradiction_state": "duplicate",
                "duplicate_count": len(rows),
                "assertion_count": len(rows),
                "publication_blockers": len(rows),
                "can_update_review_state": False,
            })
    return clusters


def claim_row_matches(row, q, queue, claim_type, review_state, contradiction_state, source_kind, project):
    if not claim_queue_match(row, queue):
        return False
    if claim_type and claim_type != row.get("claim_type"):
        return False
    if review_state and review_state != row.get("review_state"):
        return False
    if contradiction_state and contradiction_state != row.get("contradiction_state"):
        return False
    if source_kind and source_kind != row.get("source_kind"):
        return False
    if project and project != row.get("source_project"):
        return False
    if q:
        haystack = " ".join(str(row.get(key) or "") for key in (
            "claim_row_id", "row_kind", "object_id", "claim_text", "subject",
            "property", "value", "claim_type", "review_state",
            "contradiction_state", "title", "canonical_url", "domain",
            "author_handle",
        ))
        if q.lower() not in haystack.lower():
            return False
    return True


def claim_preview(row, claim_records, evidence_by_source, facts_by_source, entities_by_source, events_by_subject, source_map):
    if not row:
        return {}
    source_id = row.get("source_evidence_id") or ""
    claim_type = row.get("claim_type") or ""
    related_claims = [claim for claim in claim_records if claim.get("claim_type") == claim_type or claim.get("claim_id") == row.get("object_id")]
    evidence = evidence_by_source.get(source_id, [])
    facts = facts_by_source.get(source_id, [])
    entities = entities_by_source.get(source_id, [])
    events = events_by_subject.get(row.get("object_id"), []) + events_by_subject.get(source_id, [])
    source = source_for_ledger_row(source_map, source_id)
    return {
        "row": row,
        "source": source,
        "assertions": related_claims[:30],
        "evidence": evidence[:30],
        "facts": facts[:30],
        "entities": entities[:30],
        "events": events[:30],
        "provenance": [
            {"label": "Observation", "value": source.get("title") or source_id, "meta": source.get("last_ingested_at") or ""},
            {"label": "Evidence relation", "value": row.get("evidence_relation") or "not set", "meta": f"{row.get('support_count')} support / {row.get('refute_count')} refute"},
            {"label": "Assertion", "value": row.get("preferred_assertion") or row.get("claim_text") or "", "meta": f"{row.get('assertion_count')} assertion(s)"},
            {"label": "Claim review", "value": row.get("review_state") or "", "meta": row.get("actor") or ""},
            {"label": "Publication", "value": "blocked" if int(row.get("publication_blockers") or 0) else "eligible for draft review", "meta": "snapshot is separate"},
        ],
    }


def claims_ledger(params):
    limit = sql_int(params.get("limit", ["120"])[0], 120)
    fetch_limit = max(limit * 4, 200)
    q = (params.get("q", [""])[0] or "").strip()
    queue = (params.get("queue", ["all"])[0] or "all").strip()
    claim_type = (params.get("claim_type", [""])[0] or "").strip()
    review_state = (params.get("review_state", [""])[0] or "").strip()
    contradiction_state = (params.get("contradiction_state", [""])[0] or "").strip()
    source_kind = (params.get("source_kind", [""])[0] or "").strip()
    project = (params.get("project", [""])[0] or "").strip()
    inspect = (params.get("inspect", [""])[0] or "").strip()
    if inspect.startswith("claim:"):
        inspect = inspect.removeprefix("claim:")

    claims = ch_data(
        f"""
        SELECT
          claim_id, source_evidence_id, evidence_selection_id, claim_text,
          claim_type, evidence_relation, qualifier_json, source_anchor_json,
          status, note, actor, created_at, updated_at
        FROM claim_records FINAL
        ORDER BY updated_at DESC
        LIMIT {fetch_limit}
        """,
        fallback=[],
    )
    selections = ch_data(
        f"""
        SELECT selection_id, source_evidence_id, selection_kind, quote, status, updated_at
        FROM evidence_selections FINAL
        ORDER BY updated_at DESC
        LIMIT {fetch_limit}
        """,
        fallback=[],
    )
    facts = ch_data(
        f"""
        SELECT proposed_fact_id, source_evidence_id, fact_type, field_path, raw_value,
          normalized_value, unit, evidence_quote, status, updated_at
        FROM proposed_facts FINAL
        ORDER BY updated_at DESC
        LIMIT {fetch_limit}
        """,
        fallback=[],
    )
    entities = ch_data(
        f"""
        SELECT entity_link_id, source_evidence_id, mention_text, entity_type,
          canonical_entity_id, canonical_name, status, updated_at
        FROM entity_links FINAL
        ORDER BY updated_at DESC
        LIMIT {fetch_limit}
        """,
        fallback=[],
    )
    events = ch_data(
        f"""
        SELECT event_id, event_type, source_evidence_id, subject_type, subject_id,
          actor, created_at, payload_json
        FROM research_review_events
        WHERE subject_type IN ('claim_stub', 'claim_cluster', 'source_record', 'review_task')
        ORDER BY created_at DESC
        LIMIT {fetch_limit}
        """,
        fallback=[],
    )
    source_ids = []
    for rows in (claims, selections, facts, entities, events):
        source_ids.extend(row.get("source_evidence_id") for row in rows)
    source_map = hydrate_source_rows(source_ids)
    proposition_groups = {}
    text_counts = {}
    for claim in claims:
        source = source_for_ledger_row(source_map, claim.get("source_evidence_id") or "")
        parts = claim_subject_value({**claim, **source})
        # Only scoped claims (explicit "subject: value" or "subject is value")
        # participate in conflict clustering. Unscoped free-text claims get a
        # unique key so they never collapse into false conflicts.
        if parts.get("subject_scoped"):
            proposition_key = claim_proposition_key(parts)
        else:
            proposition_key = f"__unscoped__{claim.get('claim_id') or id(claim)}"
        text_key = (claim.get("claim_text") or "").lower()
        proposition_groups.setdefault(proposition_key, []).append({**claim, **parts})
        text_counts[text_key] = text_counts.get(text_key, 0) + 1
    proposition_counts = {}
    for key, rows in proposition_groups.items():
        values = {str(row.get("value") or row.get("claim_text") or "").lower() for row in rows}
        proposition_counts[key] = len(rows) if len(values) > 1 else 1
    evidence_by_source = group_rows(selections, "source_evidence_id")
    facts_by_source = group_rows(facts, "source_evidence_id")
    entities_by_source = group_rows(entities, "source_evidence_id")
    events_by_subject = {}
    for event in events:
        if event.get("subject_id"):
            events_by_subject.setdefault(event.get("subject_id"), []).append(event)
        if event.get("source_evidence_id"):
            events_by_subject.setdefault(event.get("source_evidence_id"), []).append(event)

    claim_rows = [make_claim_row(row, source_map, proposition_counts, text_counts, evidence_by_source, facts_by_source, entities_by_source) for row in claims]
    rows = make_claim_cluster_rows(claim_rows) + claim_rows
    rows.sort(key=lambda row: str(row.get("updated_at") or ""), reverse=True)
    filtered = [row for row in rows if claim_row_matches(row, q, queue, claim_type, review_state, contradiction_state, source_kind, project)]
    visible = filtered[:limit]
    selected = next((row for row in visible if row.get("claim_row_id") == inspect), None) or (visible[0] if visible else None)
    return {
        "project": {"id": project or "all", "label": project or "All projects"},
        "query": {
            "q": q,
            "queue": queue,
            "claim_type": claim_type,
            "review_state": review_state,
            "contradiction_state": contradiction_state,
            "source_kind": source_kind,
            "limit": limit,
        },
        "summary": {
            "claims": len(rows),
            "visible": len(filtered),
            "accepted": sum(1 for row in rows if row.get("review_state") == "accepted"),
            "disputed": sum(1 for row in rows if row.get("contradiction_state") == "disputed"),
            "conflicts": sum(1 for row in rows if row.get("row_kind") == "conflict_cluster"),
            "publication_blockers": sum(int(row.get("publication_blockers") or 0) for row in rows),
        },
        "saved_views": [],
        "facets": {
            "queues": claim_queue_counts(rows),
            "claim_types": evidence_facet_counts(rows, "claim_type"),
            "review_states": evidence_facet_counts(rows, "review_state"),
            "contradiction_states": evidence_facet_counts(rows, "contradiction_state"),
            "source_kinds": evidence_facet_counts(rows, "source_kind"),
            "projects": evidence_facet_counts(rows, "source_project"),
        },
        "results": cursor_page(visible, len(filtered), limit),
        "rows": visible,
        "preview": claim_preview(selected, claims, evidence_by_source, facts_by_source, entities_by_source, events_by_subject, source_map),
        "selection": {"selected_id": selected.get("claim_row_id") if selected else "", "selected_ids": []},
        "permissions": ["review", "revise", "merge", "split", "publish_draft"],
        "generated_at": now_iso(),
        "stale": False,
        "version": "claims-ledger.v2",
    }


REVIEW_QUEUE_LABELS = [
    ("all", "All review tasks"),
    ("assigned_to_me", "Assigned to me"),
    ("open", "Open"),
    ("in_progress", "In progress"),
    ("changes_requested", "Changes requested"),
    ("deferred", "Deferred"),
    ("blocked", "Blocked"),
    ("publication_blockers", "Publication blockers"),
    ("returned_work", "Returned work"),
    ("evidence", "Evidence"),
    ("facts", "Facts"),
    ("corrections", "Corrections"),
    ("entities", "Entities"),
    ("claims", "Claims"),
    ("annotations", "Annotations"),
    ("publication", "Publication"),
]


def review_decision_state(status):
    value = str(status or "").lower()
    if value in ("assigned", "in_progress", "approved", "rejected", "changes_requested", "deferred", "blocked", "open"):
        return value
    if value in ("accepted", "resolved", "matched", "created", "merged", "published"):
        return "approved"
    if value in ("draft", "proposed", "candidate", "smoke_test", "merge_review", "under_review", ""):
        return "open"
    return value


def review_object_group(object_type):
    return {
        "evidence_selection": "evidence",
        "proposed_fact": "facts",
        "normalized_correction": "corrections",
        "entity_link": "entities",
        "claim_stub": "claims",
        "annotation": "annotations",
        "publication_readiness_check": "publication",
        "publication_snapshot": "publication",
    }.get(object_type or "", "evidence")


def review_epistemic_layer(object_type):
    return {
        "evidence_selection": "curated_object",
        "annotation": "curated_object",
        "normalized_correction": "machine_observation",
        "proposed_fact": "machine_observation",
        "entity_link": "curated_object",
        "claim_stub": "curated_object",
        "publication_readiness_check": "publication_snapshot",
        "publication_snapshot": "publication_snapshot",
    }.get(object_type or "", "derived_observation")


def review_priority_for(row):
    state = review_decision_state(row.get("status"))
    object_type = row.get("object_type") or ""
    text = str(row.get("object_text") or "")
    if state == "blocked":
        return "blocking"
    if object_type in ("claim_stub", "proposed_fact", "publication_readiness_check"):
        return "high"
    if object_type == "normalized_correction" and len(text) > 240:
        return "high"
    return "normal"


def review_anchor_summary(row, source):
    anchor = parse_raw_json(row.get("source_anchor_json", ""))
    if isinstance(anchor, dict):
        label = first_nonempty(anchor.get("label"), anchor.get("selector"), anchor.get("dom_path"), anchor.get("artifact_path"), anchor.get("kind"))
        if label:
            return compact_text(label, 180)
    return compact_text(first_nonempty(row.get("object_text"), source.get("title"), row.get("source_evidence_id")), 180)


def review_task_id(row):
    return f"review:{row.get('object_type')}:{row.get('object_id')}"


def make_review_task_row(row, source_map):
    source = source_for_ledger_row(source_map, row.get("source_evidence_id") or "")
    state = review_decision_state(row.get("status"))
    priority = review_priority_for(row)
    object_type = row.get("object_type") or ""
    group = review_object_group(object_type)
    blockers = int(priority == "blocking") + int(group in ("claims", "facts", "publication") and state not in ("approved", "deferred"))
    permitted = ["approve", "reject", "request_changes", "defer", "assign", "edit_proposal", "open_source", "history"]
    if state in ("approved", "rejected", "deferred", "changes_requested", "blocked"):
        permitted.append("reopen")
    return {
        **source,
        "task_id": review_task_id(row),
        "row_kind": "formal_review_task",
        "object_type": object_type,
        "object_id": row.get("object_id") or "",
        "object_kind": row.get("object_kind") or object_type,
        "object_text": row.get("object_text") or "",
        "object_version": compact_text(first_nonempty(row.get("updated_at"), row.get("created_at"), row.get("object_id")), 120),
        "epistemic_layer": review_epistemic_layer(object_type),
        "source_anchor_summary": review_anchor_summary(row, source),
        "decision_state": state,
        "raw_status": row.get("status") or "",
        "assignment": row.get("actor") or REVIEW_ACTOR,
        "assignee": row.get("actor") or REVIEW_ACTOR,
        "priority": priority,
        "reason_codes": [row.get("task_type") or group, row.get("object_kind") or object_type],
        "review_reason": row.get("reason") or "Formal decision required before this object can move downstream.",
        "blocker_count": blockers,
        "linked_conflicts": int(group == "claims" and state not in ("approved", "deferred")),
        "publication_impact": "blocks publication" if blockers else "no immediate publication block",
        "permitted_actions": permitted,
        "optimistic_version": compact_text(first_nonempty(row.get("updated_at"), row.get("created_at"), row.get("object_id")), 120),
        "created_at": row.get("created_at") or "",
        "updated_at": row.get("updated_at") or "",
        "note": row.get("note") or "",
        "source_anchor": parse_raw_json(row.get("source_anchor_json", "")),
    }


def make_publication_review_rows(checks):
    rows = []
    now = now_iso()
    for check in checks:
        state = "approved" if check.get("state") == "pass" else ("blocked" if check.get("state") == "blocked" else "open")
        rows.append({
            "task_type": "publication",
            "object_type": "publication_readiness_check",
            "object_id": check.get("id") or make_id("publication_check"),
            "object_kind": check.get("state") or "readiness",
            "object_text": check.get("label") or "",
            "source_evidence_id": "",
            "source_anchor_json": json_text({"kind": "publication_check", "check_id": check.get("id")}),
            "note": check.get("label") or "",
            "actor": REVIEW_ACTOR,
            "created_at": now,
            "updated_at": now,
            "status": state,
            "label": "Review publication readiness",
            "reason": "A publication gate needs a formal decision before snapshot/export.",
        })
    return rows


def review_queue_match(row, queue):
    if not queue or queue == "all":
        return True
    state = row.get("decision_state") or "open"
    group = review_object_group(row.get("object_type"))
    if queue == "assigned_to_me":
        return row.get("assignee") in (REVIEW_ACTOR, "", None)
    if queue in ("open", "in_progress", "changes_requested", "deferred", "blocked"):
        return state == queue
    if queue == "publication_blockers":
        return int(row.get("blocker_count") or 0) > 0
    if queue == "returned_work":
        return state in ("changes_requested", "rejected")
    if queue in ("evidence", "facts", "corrections", "entities", "claims", "annotations", "publication"):
        return group == queue
    return True


def review_queue_counts(rows):
    return [
        {"id": queue_id, "label": label, "count": sum(1 for row in rows if review_queue_match(row, queue_id))}
        for queue_id, label in REVIEW_QUEUE_LABELS
    ]


def review_row_matches(row, q, queue, type_filter, decision_state, priority, layer, project):
    if not review_queue_match(row, queue):
        return False
    if type_filter and type_filter != row.get("object_type"):
        return False
    if decision_state and decision_state != row.get("decision_state"):
        return False
    if priority and priority != row.get("priority"):
        return False
    if layer and layer != row.get("epistemic_layer"):
        return False
    if project and project != row.get("source_project"):
        return False
    if q:
        haystack = " ".join(str(row.get(key) or "") for key in (
            "task_id", "object_type", "object_kind", "object_text", "source_anchor_summary",
            "decision_state", "priority", "assignee", "review_reason", "title", "canonical_url",
            "author_handle", "domain", "publication_impact",
        ))
        if q.lower() not in haystack.lower():
            return False
    return True


def review_preview(row, events_by_subject, source_map):
    if not row:
        return {}
    source = source_for_ledger_row(source_map, row.get("source_evidence_id") or row.get("evidence_id") or "")
    events = events_by_subject.get(row.get("object_id"), []) + events_by_subject.get(row.get("task_id"), [])
    before_after = {
        "before": compact_text(row.get("raw_status") or "not reviewed", 240),
        "after": compact_text(row.get("decision_state") or "open", 240),
        "proposal": compact_text(row.get("object_text") or "", 1200),
    }
    return {
        "row": row,
        "source": source,
        "checklist": [
            {"label": "Object version checked", "state": "required", "detail": row.get("object_version") or ""},
            {"label": "Exact source anchor checked", "state": "required", "detail": row.get("source_anchor_summary") or ""},
            {"label": "Adjacent objects remain separate", "state": "required", "detail": "Decision applies only to this object/version."},
            {"label": "Publication impact checked", "state": "required", "detail": row.get("publication_impact") or ""},
        ],
        "source_anchor": row.get("source_anchor") or {},
        "artifact_manifest": [
            {"label": "Source", "value": source.get("title") or row.get("source_evidence_id") or "No source", "meta": source.get("source_label") or ""},
            {"label": "Anchor", "value": row.get("source_anchor_summary") or "", "meta": "exact anchor summary"},
            {"label": "Capture", "value": source.get("captured_at") or source.get("last_ingested_at") or "", "meta": source.get("evidence_id") or ""},
        ],
        "proposed_change": before_after,
        "adjacent_objects": [
            {"label": "Evidence", "detail": "Approving a proposed fact does not approve selected evidence."},
            {"label": "Claim", "detail": "Approving evidence does not approve linked claims."},
            {"label": "Publication", "detail": "No live decision mutates a frozen snapshot."},
        ],
        "provenance": [
            {"label": "Immutable capture", "value": source.get("title") or row.get("source_evidence_id") or "No source", "meta": source.get("captured_at") or ""},
            {"label": "Derived observation", "value": row.get("object_kind") or row.get("object_type") or "", "meta": row.get("epistemic_layer") or ""},
            {"label": "Curated object", "value": row.get("object_text") or "", "meta": row.get("object_version") or ""},
            {"label": "Review decision", "value": row.get("decision_state") or "", "meta": row.get("assignee") or ""},
        ],
        "history": events[:40],
    }


def publication_check_rows(project=""):
    """Lightweight publication-readiness checks for a single project.

    Computes the same checks as publishing_read_model().get("checks") without
    building the full bundle model or fanning out into home_summary() +
    project_rows(). Used by reviews_read_model so /api/reviews does not pay the
    publishing/home/projects cost on every call.
    """
    counts = review_counts()
    coverage = {"gaps": 0}
    # One cheap project row (no full project_rows fanout) for the check inputs.
    project_row = {
        "project_id": project or "",
        "source_classes": 0,
        "accepted_evidence": int(counts.get("selections") or 0),
        "accepted_claims": int(counts.get("claim_records") or 0),
        "publication_blockers": 0,
    }
    if project:
        single = ch_data(
            f"""
            SELECT
              source_project AS project_id,
              uniqExact(evidence_id) AS sources,
              countIf(source_kind IN ('x_post','x_account','x_page')) AS x_sources,
              countIf(source_kind IN ('web_page','search_result','google_search_page')) AS web_sources,
              countIf(source_kind = 'media') AS media_sources,
              countIf(source_kind = 'user_input') AS manual_sources
            FROM evidence_events
            WHERE source_project = {sql_string(project)}
            GROUP BY source_project
            LIMIT 1
            """,
            fallback=[],
        )
        if single:
            r = single[0]
            project_row["source_classes"] = sum(1 for key in ("x_sources", "web_sources", "media_sources", "manual_sources") if int(r.get(key) or 0) > 0)
    return publishing_checks_for_project(project_row, counts, coverage)


def reviews_read_model(params):
    limit = sql_int(params.get("limit", ["120"])[0], 120)
    q = (params.get("q", [""])[0] or "").strip()
    queue = (params.get("queue", ["all"])[0] or "all").strip()
    type_filter = (params.get("type", [""])[0] or "").strip()
    decision_state = (params.get("decision_state", [""])[0] or "").strip()
    priority = (params.get("priority", [""])[0] or "").strip()
    layer = (params.get("layer", [""])[0] or "").strip()
    project = (params.get("project", [""])[0] or "").strip()
    inspect = (params.get("inspect", [""])[0] or "").strip()
    if inspect.startswith("review:"):
        inspect = inspect.removeprefix("review:")

    # Compute publication readiness checks directly rather than calling
    # publishing_read_model({}), which would build the full bundle model and
    # fan out into home_summary() + project_rows() on every /api/reviews call.
    publication_checks = publication_check_rows(project)
    raw_rows = review_object_rows(project) + make_publication_review_rows(publication_checks)
    source_ids = [row.get("source_evidence_id") for row in raw_rows]
    source_map = hydrate_source_rows(source_ids)
    rows = [make_review_task_row(row, source_map) for row in raw_rows]
    rows.sort(key=lambda row: str(row.get("updated_at") or row.get("created_at") or ""), reverse=True)

    events = ch_data(
        f"""
        SELECT
          event_id, event_type, project, source_evidence_id, subject_type,
          subject_id, actor, created_at, payload_json, source_anchor_json
        FROM research_review_events
        ORDER BY created_at DESC
        LIMIT {max(limit * 4, 200)}
        """,
        fallback=[],
    )
    events_by_subject = {}
    for event in events:
        if event.get("subject_id"):
            events_by_subject.setdefault(event.get("subject_id"), []).append(event)
        if event.get("source_evidence_id"):
            events_by_subject.setdefault(event.get("source_evidence_id"), []).append(event)

    filtered = [row for row in rows if review_row_matches(row, q, queue, type_filter, decision_state, priority, layer, project)]
    visible = filtered[:limit]
    selected = next((row for row in visible if row.get("task_id") == inspect), None) or (visible[0] if visible else None)
    return {
        "scope": {"project": project or "all", "actor": REVIEW_ACTOR, "surface": "formal_reviews"},
        "query": {
            "q": q,
            "queue": queue,
            "type": type_filter,
            "decision_state": decision_state,
            "priority": priority,
            "layer": layer,
            "project": project,
            "limit": limit,
        },
        "summary": {
            "tasks": len(rows),
            "visible": len(filtered),
            "open": sum(1 for row in rows if row.get("decision_state") == "open"),
            "assigned": sum(1 for row in rows if row.get("decision_state") == "assigned"),
            "blockers": sum(int(row.get("blocker_count") or 0) for row in rows),
            "publication": sum(1 for row in rows if review_object_group(row.get("object_type")) == "publication"),
        },
        "queues": review_queue_counts(rows),
        "facets": {
            "object_types": evidence_facet_counts(rows, "object_type"),
            "decision_states": evidence_facet_counts(rows, "decision_state"),
            "priorities": evidence_facet_counts(rows, "priority"),
            "epistemic_layers": evidence_facet_counts(rows, "epistemic_layer"),
            "projects": evidence_facet_counts(rows, "source_project"),
        },
        "results": cursor_page(visible, len(filtered), limit),
        "rows": visible,
        "preview": review_preview(selected, events_by_subject, source_map),
        "selection": {
            "selected_task_id": selected.get("task_id") if selected else "",
            "selected_task_ids": [],
            "compatible_bulk_actions": ["approve", "reject", "request_changes", "defer", "assign"],
        },
        "permissions": ["review", "assign", "request_changes", "reopen", "open_source"],
        "generated_at": now_iso(),
        "stale": False,
        "version": "reviews-page.v2",
    }


def publication_package_id(project_id, package_type="research_page"):
    raw = f"{project_id or '__unassigned__'}:{package_type}"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
    return f"PUB-{digest}"


def publication_state_for(blockers, checks_passed, checks_total, published=False):
    if published:
        return "published"
    if blockers:
        return "checks_failed"
    if checks_passed >= checks_total and checks_total:
        return "ready_for_snapshot"
    return "assembling"


def publishing_checks_for_project(row, counts, coverage):
    selections = int(counts.get("selections") or 0)
    claim_records = int(counts.get("claim_records") or 0)
    proposed_facts = int(counts.get("proposed_facts") or 0)
    gaps = int(coverage.get("gaps") or 0)
    source_classes = int(row.get("source_classes") or 0)
    accepted_evidence = int(row.get("accepted_evidence") or 0)
    accepted_claims = int(row.get("accepted_claims") or 0)
    return [
        {
            "id": "source_anchors",
            "label": "Exact source anchors resolve",
            "state": "pass" if selections or accepted_evidence else "blocked",
            "detail": f"{selections or accepted_evidence} reviewed evidence anchor(s) available.",
        },
        {
            "id": "claims_reviewed",
            "label": "Accepted claims are version-pinned",
            "state": "pass" if accepted_claims or claim_records else "needs_work",
            "detail": f"{accepted_claims or claim_records} claim record(s) can be pinned to a snapshot.",
        },
        {
            "id": "facts_visible",
            "label": "Proposed facts are visible before publication",
            "state": "pass" if proposed_facts else "needs_work",
            "detail": f"{proposed_facts} proposed fact row(s) remain separately reviewable.",
        },
        {
            "id": "source_diversity",
            "label": "Coverage gaps reviewed",
            "state": "pass" if source_classes >= 3 and gaps == 0 else "needs_work",
            "detail": f"{source_classes} source class(es); {gaps} coverage gap(s).",
        },
        {
            "id": "snapshot",
            "label": "Frozen publication snapshot exists",
            "state": "needs_work",
            "detail": "Create and approve a frozen snapshot before publication.",
        },
    ]


def package_type_label(package_type):
    return {
        "research_page": "Research page",
        "comparison_table": "Comparison table",
        "benchmark_brief": "Benchmark brief",
        "entity_profile": "Entity profile",
        "timeline_page": "Timeline page",
        "editorial_package": "Editorial package",
        "export_bundle": "Export / reuse bundle",
    }.get(package_type or "", "Research page")


def make_publication_bundle_row(row, counts, coverage, package_type="research_page"):
    project_id = row.get("project_id") or ""
    package_id = publication_package_id(project_id, package_type)
    checks = publishing_checks_for_project(row, counts, coverage)
    checks_passed = sum(1 for check in checks if check.get("state") == "pass")
    blockers = sum(1 for check in checks if check.get("state") == "blocked") + int(row.get("publication_blockers") or 0)
    state = publication_state_for(blockers, checks_passed, len(checks))
    evidence_count = int(row.get("accepted_evidence") or row.get("proposed_evidence") or 0)
    claim_count = int(row.get("accepted_claims") or row.get("open_claims") or 0)
    source_count = int(row.get("sources") or 0)
    readiness = percent(checks_passed, len(checks))
    digest = hashlib.sha1(json_text({"project": project_id, "package_type": package_type, "sources": source_count, "claims": claim_count}).encode("utf-8")).hexdigest()
    target = "Public research website" if package_type == "research_page" else "Editorial / data reuse"
    return {
        "bundle_id": package_id,
        "package_type": package_type,
        "package_type_label": package_type_label(package_type),
        "project": project_id,
        "title": f"{row.get('name') or 'Unassigned research'} — {package_type_label(package_type).lower()}",
        "target": target,
        "draft_revision": f"DRF-{digest[:6]} v{max(1, source_count + claim_count)}",
        "manifest_version": f"PKG-{digest[6:12]} v{max(1, source_count)}",
        "manifest_hash": digest,
        "section_count": max(1, min(9, int(row.get("source_classes") or 1) + 2)),
        "claim_count": claim_count,
        "evidence_count": evidence_count,
        "citation_count": max(source_count, evidence_count + claim_count),
        "capture_count": source_count,
        "media_count": int(row.get("media_sources") or 0),
        "checks_passed": checks_passed,
        "checks_total": len(checks),
        "blocker_count": blockers,
        "readiness_percent": readiness,
        "display_state": state,
        "snapshot_state": "stale" if blockers else ("ready" if state == "ready_for_snapshot" else "none"),
        "review_state": "changes_requested" if blockers else ("approved" if state == "ready_for_snapshot" else "draft"),
        "release_state": "unpublished",
        "owner": REVIEW_ACTOR,
        "due_at": "",
        "updated_at": row.get("last_activity") or now_iso(),
        # Publication is a preview: the readiness checks are derived heuristics
        # (row counts, not real gating), and there is no snapshot/approval table
        # yet, so create_snapshot/publish_snapshot only log review events. The
        # view-only and blocker-focus actions are safe; the mutating snapshot
        # actions are disabled until a snapshot store exists.
        "implementation_state": "preview",
        "permitted_actions": ["open_package", "run_checks", "focus_blockers"],
        "disabled_actions": ["create_snapshot", "request_review", "create_handoff", "publish_snapshot", "supersede_release"],
        "optimistic_version": digest[:16],
        "checks": checks,
        "history": [
            {"event_type": "package.derived", "actor": "research-ui", "created_at": row.get("last_activity") or now_iso(), "detail": "Derived from reviewed objects and project coverage."},
            {"event_type": "readiness.checks.computed", "actor": "research-ui", "created_at": now_iso(), "detail": f"{checks_passed}/{len(checks)} checks pass."},
        ],
    }


def publication_queue_counts(rows):
    queues = [
        ("owned_by_me", "Owned by me"),
        ("blocking_checks", "Blocking checks"),
        ("ready_for_snapshot", "Ready for snapshot"),
        ("awaiting_review", "Awaiting review"),
        ("published", "Published releases"),
    ]
    return [
        {
            "id": queue_id,
            "label": label,
            "count": sum(
                1
                for row in rows
                if (
                    queue_id == "owned_by_me"
                    or (queue_id == "blocking_checks" and int(row.get("blocker_count") or 0) > 0)
                    or (queue_id == "ready_for_snapshot" and row.get("display_state") == "ready_for_snapshot")
                    or (queue_id == "awaiting_review" and row.get("review_state") in ("ready_for_review", "snapshot_in_review", "changes_requested"))
                    or (queue_id == "published" and row.get("release_state") == "published")
                )
            ),
        }
        for queue_id, label in queues
    ]


def publishing_preview(row):
    if not row:
        return {}
    sections = [
        {"label": "Overview", "detail": f"{row.get('claim_count')} claims · {row.get('evidence_count')} evidence objects · {row.get('citation_count')} citations"},
        {"label": "Evidence and claims", "detail": "Only reviewed object references are eligible for a frozen snapshot."},
        {"label": "Citation manifest", "detail": f"{row.get('capture_count')} immutable capture(s) pinned."},
        {"label": "Public handoff", "detail": row.get("target") or ""},
    ]
    return {
        "row": row,
        "checks": row.get("checks") or [],
        "contents": sections,
        "citations": [
            {"label": "Exact anchors", "state": "pass" if row.get("citation_count") else "blocked", "detail": f"{row.get('citation_count')} citation candidate(s)."},
            {"label": "Live URL leakage", "state": "pass", "detail": "Handoff must use capture/artifact IDs, not mutable live URLs."},
            {"label": "Visibility rules", "state": "pass", "detail": "Private notes and restricted artifacts remain excluded."},
        ],
        "snapshot": {
            "state": row.get("snapshot_state"),
            "manifest_hash": row.get("manifest_hash"),
            "draft_revision": row.get("draft_revision"),
            "manifest_version": row.get("manifest_version"),
            "note": "Snapshot creation freezes draft, claims, evidence, entities, taxonomy, captures, citation anchors, assets, target config, and check results.",
        },
        "handoff": [
            {"label": "Public website", "detail": "Structured page payload, citation manifest, and public source trail."},
            {"label": "Editorial package", "detail": "Markdown, assets, provenance report, and review summary."},
            {"label": "Data export", "detail": "JSON claim/evidence bundle with stable identifiers."},
            {"label": "Research archive", "detail": "Snapshot manifest, checks, audit, and source references."},
        ],
        "handoff_artifacts": row.get("handoffs") or [],
        "history": row.get("history") or [],
    }


def parse_json_list(value):
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except Exception:
        return []
    return parsed if isinstance(parsed, list) else []


def parse_json_dict(value):
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def decorate_publication_snapshot(row):
    row = dict(row or {})
    row["manifest"] = parse_json_dict(row.get("manifest_json", ""))
    row["checks"] = parse_json_list(row.get("checks_json", ""))
    return row


def latest_publication_snapshots(bundle_ids):
    bundle_ids = [bundle_id for bundle_id in dict.fromkeys(bundle_ids or []) if bundle_id]
    if not bundle_ids:
        return {}
    quoted = ", ".join(sql_string(bundle_id) for bundle_id in bundle_ids)
    rows = ch_data(
        f"""
        SELECT snapshot_id, bundle_id, project, package_type, snapshot_state,
          review_state, release_state, manifest_hash, manifest_json, checks_json,
          actor, note, created_at, updated_at
        FROM publication_snapshots FINAL
        WHERE bundle_id IN ({quoted})
        ORDER BY updated_at DESC
        """,
        fallback=[],
    )
    latest = {}
    for row in rows:
        bundle_id = row.get("bundle_id") or ""
        if bundle_id and bundle_id not in latest:
            latest[bundle_id] = decorate_publication_snapshot(row)
    return latest


def latest_publication_releases(bundle_ids):
    bundle_ids = [bundle_id for bundle_id in dict.fromkeys(bundle_ids or []) if bundle_id]
    if not bundle_ids:
        return {}
    quoted = ", ".join(sql_string(bundle_id) for bundle_id in bundle_ids)
    rows = ch_data(
        f"""
        SELECT release_id, snapshot_id, bundle_id, project, release_state,
          manifest_hash, supersedes_release_id, actor, note, created_at, updated_at
        FROM publication_releases FINAL
        WHERE bundle_id IN ({quoted})
        ORDER BY updated_at DESC
        """,
        fallback=[],
    )
    latest = {}
    for row in rows:
        bundle_id = row.get("bundle_id") or ""
        if bundle_id and bundle_id not in latest:
            latest[bundle_id] = row
    return latest


def decorate_publication_handoff(row):
    row = dict(row or {})
    row["object_ids"] = parse_json_dict(row.get("object_ids_json", ""))
    row["public_config"] = parse_json_dict(row.get("public_config_json", ""))
    row["artifact"] = parse_json_dict(row.get("artifact_json", ""))
    row["object_counts"] = {
        key: len(value) if isinstance(value, list) else 0
        for key, value in row["object_ids"].items()
    }
    return row


def publication_handoff_rows(bundle_ids=None, snapshot_id=""):
    bundle_ids = [bundle_id for bundle_id in dict.fromkeys(bundle_ids or []) if bundle_id]
    clauses = []
    if bundle_ids:
        clauses.append("bundle_id IN (" + ", ".join(sql_string(bundle_id) for bundle_id in bundle_ids) + ")")
    snapshot_id = compact_text(snapshot_id, 200)
    if snapshot_id:
        clauses.append(f"snapshot_id = {sql_string(snapshot_id)}")
    if not clauses:
        return []
    rows = ch_data(
        f"""
        SELECT handoff_id, snapshot_id, bundle_id, project, artifact_kind,
          manifest_hash, object_ids_json, public_config_json, artifact_json,
          status, actor, note, created_at, updated_at
        FROM publication_handoffs FINAL
        WHERE {' AND '.join(clauses)}
        ORDER BY updated_at DESC
        LIMIT 120
        """,
        fallback=[],
    )
    return [decorate_publication_handoff(row) for row in rows]


def publication_handoffs_by_bundle(bundle_ids):
    grouped = {bundle_id: [] for bundle_id in dict.fromkeys(bundle_ids or []) if bundle_id}
    for row in publication_handoff_rows(list(grouped.keys())):
        bundle_id = row.get("bundle_id") or ""
        if bundle_id in grouped:
            grouped[bundle_id].append(row)
    return grouped


def snapshot_check(snapshot):
    if not snapshot:
        return {
            "id": "snapshot",
            "label": "Frozen publication snapshot exists",
            "state": "needs_work",
            "detail": "No frozen snapshot exists yet; create one before review or release.",
        }
    review_state = snapshot.get("review_state") or "draft"
    release_state = snapshot.get("release_state") or "unpublished"
    state = "pass" if review_state == "approved" or release_state == "published" else "needs_work"
    return {
        "id": "snapshot",
        "label": "Frozen publication snapshot exists",
        "state": state,
        "detail": f"{snapshot.get('snapshot_id')} is {review_state}; manifest {snapshot.get('manifest_hash') or 'unhashed'}.",
    }


def apply_publication_persistence(row, snapshot=None, release=None, handoffs=None):
    row = dict(row)
    handoffs = handoffs or []
    original_blocked_checks = sum(1 for check in row.get("checks") or [] if check.get("state") == "blocked")
    base_blockers = max(0, int(row.get("blocker_count") or 0) - original_blocked_checks)
    checks = []
    for check in row.get("checks") or []:
        checks.append(snapshot_check(snapshot) if check.get("id") == "snapshot" else check)
    if not any(check.get("id") == "snapshot" for check in checks):
        checks.append(snapshot_check(snapshot))
    checks_passed = sum(1 for check in checks if check.get("state") == "pass")
    checks_total = len(checks)
    row["checks"] = checks
    row["checks_passed"] = checks_passed
    row["checks_total"] = checks_total
    row["readiness_percent"] = percent(checks_passed, checks_total)
    row["implementation_state"] = "active"
    row["permitted_actions"] = ["open_package", "run_checks", "focus_blockers", "create_snapshot"]
    row["disabled_actions"] = []
    if snapshot:
        row["latest_snapshot_id"] = snapshot.get("snapshot_id") or ""
        row["snapshot_state"] = snapshot.get("snapshot_state") or "frozen"
        row["review_state"] = snapshot.get("review_state") or "draft"
        row["release_state"] = (release or {}).get("release_state") or snapshot.get("release_state") or "unpublished"
        row["manifest_hash"] = snapshot.get("manifest_hash") or row.get("manifest_hash") or ""
        row["snapshot_created_at"] = snapshot.get("created_at") or ""
        row["snapshot_updated_at"] = snapshot.get("updated_at") or ""
        row["permitted_actions"].append("request_review")
        if row["review_state"] == "approved":
            row["permitted_actions"].extend(["create_handoff", "publish_snapshot"])
        else:
            row["disabled_actions"].extend(["create_handoff", "publish_snapshot"])
        if row["release_state"] == "published":
            row["display_state"] = "published"
            row["permitted_actions"].append("supersede_release")
        else:
            row["disabled_actions"].append("supersede_release")
            if row["review_state"] == "approved":
                row["display_state"] = "ready_to_publish"
            elif row["review_state"] in ("snapshot_in_review", "ready_for_review"):
                row["display_state"] = "awaiting_review"
            elif row["review_state"] == "changes_requested":
                row["display_state"] = "changes_requested"
            else:
                row["display_state"] = "snapshot_created"
        row["history"] = (row.get("history") or []) + [{
            "event_type": "publication.snapshot.loaded",
            "actor": snapshot.get("actor") or "research-ui",
            "created_at": snapshot.get("updated_at") or snapshot.get("created_at") or now_iso(),
            "detail": f"{snapshot.get('snapshot_id')} / {snapshot.get('review_state') or 'draft'}",
        }]
        if handoffs:
            row["history"] = row["history"] + [{
                "event_type": "publication.handoff.loaded",
                "actor": handoffs[0].get("actor") or "research-ui",
                "created_at": handoffs[0].get("updated_at") or handoffs[0].get("created_at") or now_iso(),
                "detail": f"{handoffs[0].get('artifact_kind') or 'handoff'} / {handoffs[0].get('handoff_id') or ''}",
            }]
    else:
        row["latest_snapshot_id"] = ""
        row["snapshot_state"] = "none"
        row["review_state"] = "draft"
        row["release_state"] = "unpublished"
        row["disabled_actions"] = ["request_review", "create_handoff", "publish_snapshot", "supersede_release"]
    row["handoff_count"] = len(handoffs)
    row["latest_handoff_id"] = handoffs[0].get("handoff_id") if handoffs else ""
    row["handoffs"] = handoffs[:6]
    row["blocker_count"] = base_blockers + sum(1 for check in checks if check.get("state") == "blocked")
    row["optimistic_version"] = compact_text(first_nonempty(row.get("snapshot_updated_at"), row.get("updated_at"), row.get("manifest_hash")), 120)
    return row


def publishing_read_model(params):
    limit = sql_int(params.get("limit", ["120"])[0], 120)
    q = (params.get("q", [""])[0] or "").strip()
    project = (params.get("project", [""])[0] or "").strip()
    counts = review_counts()
    coverage = home_summary().get("coverage", {})
    projects_model = project_rows({"project": [project]} if project else {})
    projects = projects_model.get("rows", []) if isinstance(projects_model, dict) else []
    if not projects:
        active = home_summary().get("active_project", {})
        projects = [{
            "project_id": project or "open-model-evidence",
            "name": active.get("name") or "Open model evidence",
            "sources": 0,
            "source_classes": 0,
            "accepted_evidence": int(counts.get("selections") or 0),
            "proposed_evidence": int(counts.get("selections") or 0),
            "accepted_claims": int(counts.get("claim_records") or 0),
            "open_claims": int(counts.get("claim_records") or 0),
            "publication_blockers": int(coverage.get("gaps") or 0),
            "last_activity": now_iso(),
        }]
    rows = []
    for row in projects:
        rows.append(make_publication_bundle_row(row, counts, coverage, "research_page"))
        if int(row.get("accepted_claims") or row.get("open_claims") or 0):
            rows.append(make_publication_bundle_row(row, counts, coverage, "comparison_table"))
        if int(row.get("proposed_evidence") or 0):
            rows.append(make_publication_bundle_row(row, counts, coverage, "export_bundle"))
    snapshots = latest_publication_snapshots([row.get("bundle_id") for row in rows])
    releases = latest_publication_releases([row.get("bundle_id") for row in rows])
    handoffs = publication_handoffs_by_bundle([row.get("bundle_id") for row in rows])
    rows = [
        apply_publication_persistence(
            row,
            snapshots.get(row.get("bundle_id")),
            releases.get(row.get("bundle_id")),
            handoffs.get(row.get("bundle_id")),
        )
        for row in rows
    ]
    if q:
        lowered = q.lower()
        rows = [row for row in rows if lowered in " ".join(str(row.get(key) or "") for key in ("title", "project", "package_type_label", "target", "display_state")).lower()]
    rows.sort(key=lambda row: (int(row.get("blocker_count") or 0), str(row.get("updated_at") or "")), reverse=True)
    visible = rows[:limit]
    selected = visible[0] if visible else None
    all_checks = []
    for row in rows:
        all_checks.extend(row.get("checks") or [])
    return {
        "scope": {"project": project or "all", "actor": REVIEW_ACTOR, "surface": "publishing"},
        "query": {"q": q, "project": project, "limit": limit},
        "summary": {
            "bundles": len(rows),
            "visible": len(visible),
            "checks": len(all_checks),
            "blocked": sum(1 for row in rows if int(row.get("blocker_count") or 0) > 0),
            "ready": sum(1 for row in rows if row.get("display_state") == "ready_for_snapshot"),
        },
        "queues": publication_queue_counts(rows),
        "facets": {
            "package_types": evidence_facet_counts(rows, "package_type"),
            "displayed_states": evidence_facet_counts(rows, "display_state"),
            "targets": evidence_facet_counts(rows, "target"),
        },
        "results": cursor_page(visible, len(rows), limit),
        "bundles": visible,
        "checks": all_checks,
        "preview": publishing_preview(selected),
        "selection": {"selected_bundle_ids": [], "compatible_bulk_actions": ["run_checks", "create_snapshot", "request_review", "create_handoff"]},
        "permissions": ["prepare", "run_checks", "create_snapshot", "request_review", "handoff"],
        "snapshot_policy": "Publishing must consume an approved frozen snapshot, not mutable live records.",
        "generated_at": now_iso(),
        "stale": False,
        "version": "publishing-page.v2",
    }


def resolve_project_id(project=""):
    project = compact_text(project, 300)
    if project and project != "__active__":
        return project
    rows = project_rows({}).get("rows", [])
    return (rows[0].get("project_id") if rows else "") or ""


def evidence_project_where(project, table="evidence_events"):
    if not project:
        return "1 = 1"
    return f"{table}.source_project = {sql_string(project)}"


def review_project_where(project, column="source_evidence_id"):
    if not project:
        return "1 = 1"
    return f"{column} IN (SELECT evidence_id FROM evidence_events WHERE source_project = {sql_string(project)})"


def source_rows_for_project(project, limit=120, q=""):
    clauses = [evidence_project_where(project)]
    if q:
        like = sql_string(q)
        clauses.append(
            "("
            f"positionCaseInsensitive(title, {like}) > 0 OR "
            f"positionCaseInsensitive(text, {like}) > 0 OR "
            f"positionCaseInsensitive(canonical_url, {like}) > 0 OR "
            f"positionCaseInsensitive(domain, {like}) > 0 OR "
            f"positionCaseInsensitive(arrayStringConcat(topics, ' '), {like}) > 0"
            ")"
        )
    return [decorate_source_row(row) for row in latest_source_rows(" AND ".join(clauses), limit)]


def scoped_claim_rows(project="", limit=200, q=""):
    clauses = [review_project_where(project)]
    if q:
        like = sql_string(q)
        clauses.append(
            "("
            f"positionCaseInsensitive(claim_text, {like}) > 0 OR "
            f"positionCaseInsensitive(claim_type, {like}) > 0 OR "
            f"positionCaseInsensitive(note, {like}) > 0"
            ")"
        )
    rows = ch_data(
        f"""
        SELECT claim_id, source_evidence_id, evidence_selection_id, claim_text,
          claim_type, evidence_relation, qualifier_json, source_anchor_json,
          status, note, actor, created_at, updated_at
        FROM claim_records FINAL
        WHERE {" AND ".join(clauses)}
        ORDER BY updated_at DESC
        LIMIT {limit}
        """,
        fallback=[],
    )
    source_map = hydrate_source_rows([row.get("source_evidence_id") for row in rows])
    proposition_counts = {}
    for row in rows:
        source = source_for_ledger_row(source_map, row.get("source_evidence_id") or "")
        parts = claim_subject_value({**row, **source})
        if not parts.get("subject_scoped"):
            continue
        key = claim_proposition_key(parts)
        proposition_counts.setdefault(key, set()).add(str(parts.get("value") or "").lower())
    decorated = []
    for row in rows:
        source = source_for_ledger_row(source_map, row.get("source_evidence_id") or "")
        parts = claim_subject_value({**row, **source})
        cluster_size = len(proposition_counts.get(claim_proposition_key(parts), [])) if parts.get("subject_scoped") else 1
        decorated.append({
            **row,
            **source,
            **parts,
            "qualifier": parse_raw_json(row.get("qualifier_json", "")),
            "review_state": row.get("status") or "draft",
            "contradiction_state": claim_contradiction_state(row, cluster_size),
            "source": source,
        })
    return decorated


def date_precision(value):
    if not value:
        return "unknown"
    text = str(value)
    if "T" in text:
        return "datetime"
    if len(text) >= 10:
        return "day"
    if len(text) >= 7:
        return "month"
    if len(text) >= 4:
        return "year"
    return "unknown"


def timeline_item_from_source(row):
    date_value = first_nonempty(row.get("last_captured_at"), row.get("first_captured_at"), row.get("last_ingested_at"))
    return {
        "item_id": f"capture:{row.get('evidence_id')}",
        "lane": "captures",
        "event_type": "source_capture",
        "summary": row.get("title") or row.get("canonical_url") or row.get("evidence_id"),
        "date": date_value,
        "date_range": {"start": row.get("first_captured_at") or date_value, "end": row.get("last_captured_at") or date_value},
        "date_precision": date_precision(date_value),
        "source_date": row.get("first_captured_at") or "",
        "capture_date": row.get("last_captured_at") or row.get("last_ingested_at") or "",
        "entities": row.get("entities") or [],
        "topics": row.get("topics") or [],
        "evidence_count": 1,
        "source_ids": [row.get("evidence_id")],
        "review_state": "captured",
        "conflict_state": "none",
        "confidence_state": "source_linked",
        "source_kind": row.get("source_kind") or "",
        "source_label": row.get("source_label") or source_kind_label(row.get("source_kind")),
        "source": source_for_ledger_row({row.get("evidence_id"): row}, row.get("evidence_id")),
    }


def timeline_item_from_claim(row):
    date_value = first_nonempty(row.get("updated_at"), row.get("created_at"), row.get("captured_at"))
    return {
        "item_id": f"claim:{row.get('claim_id')}",
        "lane": "claims",
        "event_type": row.get("claim_type") or "claim",
        "summary": row.get("claim_text") or row.get("value") or row.get("claim_id"),
        "date": date_value,
        "date_range": {"start": date_value, "end": date_value},
        "date_precision": date_precision(date_value),
        "source_date": row.get("captured_at") or "",
        "capture_date": row.get("updated_at") or "",
        "entities": [row.get("subject")] if row.get("subject_scoped") else [],
        "topics": [row.get("claim_type")] if row.get("claim_type") else [],
        "evidence_count": 1 if row.get("source_evidence_id") else 0,
        "source_ids": [row.get("source_evidence_id")] if row.get("source_evidence_id") else [],
        "review_state": row.get("review_state") or "draft",
        "conflict_state": row.get("contradiction_state") or "under_review",
        "confidence_state": "disputed" if row.get("contradiction_state") in ("conflict", "disputed") else ("source_linked" if row.get("source_evidence_id") else "needs_evidence"),
        "source_kind": row.get("source_kind") or "",
        "source_label": row.get("source_label") or source_kind_label(row.get("source_kind")),
        "source": row.get("source") or {},
    }


def timeline_param(params, name, default=""):
    value = params.get(name, [default])
    if isinstance(value, list):
        return (value[0] if value else default) or default
    return value or default


def timeline_selected_date(item, date_type):
    if date_type == "source":
        return item.get("source_date") or ""
    if date_type == "capture":
        return item.get("capture_date") or ""
    return item.get("date") or ""


def timeline_date_matches(item, date_type, date_from, date_to):
    if not date_from and not date_to:
        return True
    date_value = timeline_selected_date(item, date_type)
    if not date_value:
        return False
    date_key = str(date_value)[:10]
    if date_from and date_key < date_from:
        return False
    if date_to and date_key > date_to:
        return False
    return True


def timeline_facet(items, key, *, label_fn=None):
    counts = {}
    for item in items:
        value = item.get(key) or ""
        if not value:
            continue
        counts[value] = counts.get(value, 0) + 1
    return [
        {"id": value, "label": label_fn(value) if label_fn else title_case_label(value), "count": count}
        for value, count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
    ]


def apply_timeline_saved_view(saved_view, filters):
    saved_views = {
        "recent_captures": {"lane": "captures", "date_type": "capture"},
        "date_conflicts": {"confidence": "disputed"},
        "accepted_claims": {"lane": "claims", "review_state": "accepted", "date_type": "event"},
        "needs_evidence": {"confidence": "needs_evidence"},
    }
    for key, value in saved_views.get(saved_view, {}).items():
        filters[key] = value


def project_timeline(params):
    project = resolve_project_id(params.get("project_id", params.get("project", [""]))[0] if isinstance(params.get("project_id", params.get("project", [""])), list) else "")
    q = (params.get("q", [""])[0] or "").strip()
    limit = sql_int(params.get("limit", ["120"])[0], 120)
    filters = {
        "lane": timeline_param(params, "lane").strip(),
        "date_type": timeline_param(params, "date_type", "event").strip() or "event",
        "date_from": timeline_param(params, "date_from").strip(),
        "date_to": timeline_param(params, "date_to").strip(),
        "confidence": timeline_param(params, "confidence").strip(),
        "review_state": timeline_param(params, "review_state").strip(),
        "source_kind": timeline_param(params, "source_kind").strip(),
        "saved_view": timeline_param(params, "saved_view").strip(),
    }
    apply_timeline_saved_view(filters["saved_view"], filters)
    if filters["date_type"] not in ("event", "source", "capture"):
        filters["date_type"] = "event"
    sources = source_rows_for_project(project, max(limit, 120), q)
    claims = scoped_claim_rows(project, max(limit, 120), q)
    all_items = [timeline_item_from_source(row) for row in sources] + [timeline_item_from_claim(row) for row in claims]
    items = list(all_items)
    if q:
        lowered = q.lower()
        items = [item for item in items if lowered in " ".join(str(item.get(key) or "") for key in ("summary", "event_type", "review_state", "conflict_state")).lower()]
    if filters["lane"]:
        items = [item for item in items if item.get("lane") == filters["lane"]]
    if filters["confidence"]:
        items = [item for item in items if item.get("confidence_state") == filters["confidence"]]
    if filters["review_state"]:
        items = [item for item in items if item.get("review_state") == filters["review_state"]]
    if filters["source_kind"]:
        items = [item for item in items if item.get("source_kind") == filters["source_kind"]]
    items = [item for item in items if timeline_date_matches(item, filters["date_type"], filters["date_from"], filters["date_to"])]
    for item in items:
        item["selected_date"] = timeline_selected_date(item, filters["date_type"])
        item["selected_date_type"] = filters["date_type"]
    items.sort(key=lambda item: (item.get("selected_date") or item.get("date") or "9999", item.get("item_id") or ""))
    visible = items[:limit]
    return read_envelope({
        "scope": {"project": project or "all", "surface": "timeline"},
        "query": {"q": q, "limit": limit, **filters},
        "summary": {
            "items": len(items),
            "captures": sum(1 for item in items if item.get("lane") == "captures"),
            "claims": sum(1 for item in items if item.get("lane") == "claims"),
            "conflicts": sum(1 for item in items if item.get("conflict_state") in ("conflict", "disputed")),
            "all_items": len(all_items),
        },
        "lanes": [
            {"id": "captures", "label": "Captures", "count": sum(1 for item in items if item.get("lane") == "captures")},
            {"id": "claims", "label": "Claims", "count": sum(1 for item in items if item.get("lane") == "claims")},
            {"id": "reviews", "label": "Reviews", "count": sum(1 for item in items if item.get("review_state") not in ("captured", "accepted", "published"))},
        ],
        "date_types": [
            {"id": "event", "label": "Event date", "description": "Best available event date from captured or reviewed object timestamps."},
            {"id": "source", "label": "Source date", "description": "Original source/capture timestamp when present."},
            {"id": "capture", "label": "Capture/update date", "description": "Collection or review-update timestamp when present."},
        ],
        "facets": {
            "lanes": timeline_facet(all_items, "lane"),
            "confidence": timeline_facet(all_items, "confidence_state"),
            "review_states": timeline_facet(all_items, "review_state"),
            "source_kinds": timeline_facet(all_items, "source_kind", label_fn=source_kind_label),
        },
        "saved_views": [
            {"id": "recent_captures", "label": "Recent captures", "filters": {"lane": "captures", "date_type": "capture"}},
            {"id": "date_conflicts", "label": "Date and claim conflicts", "filters": {"confidence": "disputed"}},
            {"id": "accepted_claims", "label": "Accepted claim chronology", "filters": {"lane": "claims", "review_state": "accepted", "date_type": "event"}},
            {"id": "needs_evidence", "label": "Needs evidence", "filters": {"confidence": "needs_evidence"}},
        ],
        "results": cursor_page(visible, len(items), limit),
        "items": visible,
    }, "project-timeline.v1", now_iso(), False, ["navigate", "review", "open_source"])


def topic_detail(params):
    topic_id = ((params.get("topic_id", [""])[0] or "") or (params.get("id", [""])[0] or "")).strip()
    project = resolve_project_id((params.get("project", [""])[0] or "").strip())
    taxonomy = taxonomy_read_model({"queue": ["all"], "vocabulary": ["topics"], "limit": ["200"]})
    topics = taxonomy.get("rows") or []
    topic = next((row for row in topics if row.get("stable_id") == topic_id or row.get("record_id") == topic_id or row.get("term") == topic_id), None)
    term = (topic or {}).get("term") or topic_id or "topic"
    like = sql_string(term)
    clauses = [
        evidence_project_where(project),
        "("
        f"positionCaseInsensitive(arrayStringConcat(topics, ' '), {like}) > 0 OR "
        f"positionCaseInsensitive(title, {like}) > 0 OR "
        f"positionCaseInsensitive(text, {like}) > 0"
        ")",
    ]
    sources = [decorate_source_row(row) for row in latest_source_rows(" AND ".join(clauses), 120)]
    source_ids = [row.get("evidence_id") for row in sources]
    source_id_sql = ", ".join(sql_string(source_id) for source_id in source_ids if source_id) or "''"
    claims = scoped_claim_rows(project, 120, term)
    if source_ids:
        claims = [row for row in claims if row.get("source_evidence_id") in source_ids or term.lower() in str(row.get("claim_text") or "").lower()]
    entities = sorted({entity for row in sources for entity in (row.get("entities") or []) if entity})[:50]
    selections = ch_data(
        f"""
        SELECT selection_id, source_evidence_id, selection_kind, quote, status, updated_at
        FROM evidence_selections FINAL
        WHERE source_evidence_id IN ({source_id_sql})
        ORDER BY updated_at DESC
        LIMIT 120
        """,
        fallback=[],
    ) if source_ids else []
    timeline_items = [timeline_item_from_source(row) for row in sources] + [timeline_item_from_claim(row) for row in claims]
    timeline_items.sort(key=lambda item: item.get("date") or "9999")
    header = {
        "topic_id": topic_id or (topic or {}).get("stable_id") or taxonomy_term_id("topics", term),
        "label": term,
        "definition": (topic or {}).get("definition") or "Topic derived from captured source labels and reviewed claims.",
        "project": project,
        "review_state": (topic or {}).get("review_state") or "observed",
        "source_count": len(sources),
        "claim_count": len(claims),
        "entity_count": len(entities),
        "evidence_count": len(selections),
    }
    return read_envelope({
        "header": header,
        "tabs": ["overview", "evidence", "claims", "entities", "timeline", "notes"],
        "coverage": {
            "sources": evidence_facet_counts(sources, "source_kind"),
            "projects": evidence_facet_counts(sources, "source_project"),
            "review_states": evidence_facet_counts(claims, "review_state"),
        },
        "sources": sources[:60],
        "evidence": selections,
        "claims": claims[:80],
        "entities": entities,
        "timeline": timeline_items[:80],
        "notes": (topic or {}).get("policy") or {},
    }, "topic-detail.v1", now_iso(), False, ["navigate", "review", "open_source"])


COMPARE_STATES = ["Missing", "NA", "Vendor-reported", "Independently-measured", "Reproduced", "Disputed", "Stale", "Incomparable"]
COMPARE_VENDOR_SOURCE_KINDS = {"x_post", "x_account", "x_page"}
COMPARE_INDEPENDENT_SOURCE_KINDS = {"media", "search_result", "google_search_page"}


def qualifier_search_text(qualifier):
    if not qualifier:
        return ""
    if isinstance(qualifier, (dict, list)):
        return json_text(qualifier).lower()
    return str(qualifier).lower()


def qualifier_has_any(qualifier, tokens):
    text = qualifier_search_text(qualifier)
    return any(token in text for token in tokens)


def compare_claim_rank(row):
    status = str(row.get("review_state") or row.get("status") or "").lower()
    if status in ("accepted", "published"):
        return 0
    if status in ("under_review", "draft", "proposed"):
        return 1
    if status in ("disputed", "changes_requested"):
        return 2
    if status in ("rejected", "superseded"):
        return 3
    return 4


def compare_select_claim(matches):
    if not matches:
        return None
    return sorted(matches, key=compare_claim_rank)[0]


def compare_cell_decision(claim, matches, peer_values):
    if not claim:
        return {"state": "Missing", "reason": "No scoped claim exists for this property and entity."}
    statuses = {str(row.get("review_state") or row.get("status") or "").lower() for row in matches}
    relations = {str(row.get("evidence_relation") or "").lower() for row in matches}
    contradictions = {str(row.get("contradiction_state") or "").lower() for row in matches}
    qualifiers = [row.get("qualifier") for row in matches]
    if statuses and statuses <= {"rejected", "superseded"}:
        return {"state": "NA", "reason": "All matching assertions are rejected or superseded."}
    if any(qualifier_has_any(value, ("not_applicable", "not applicable", "n/a", '"na"', "no_result")) for value in qualifiers):
        return {"state": "NA", "reason": "The linked assertion marks this comparison as not applicable."}
    if any(qualifier_has_any(value, ("incompatible", "different_setup", "different setup", "different_metric", "not_comparable", "not comparable")) for value in qualifiers):
        return {"state": "Incomparable", "reason": "Qualifier metadata marks the assertion as incompatible with the comparison set."}
    if any(qualifier_has_any(value, ("stale", "outdated", "superseded_by", "superseded by")) for value in qualifiers):
        return {"state": "Stale", "reason": "Qualifier metadata marks the assertion as stale or superseded by newer evidence."}
    if (
        relations & {"refutes", "contradicts"}
        or statuses & {"disputed"}
        or contradictions & {"disputed", "conflict"}
        or len(peer_values) > 1
    ):
        return {"state": "Disputed", "reason": "Competing values or refuting evidence are attached to this property."}
    if any(qualifier_has_any(value, ("reproduced", "replicated", "rerun", "repeatable")) for value in qualifiers) or relations & {"reproduced", "replicated"}:
        return {"state": "Reproduced", "reason": "Qualifier or evidence relation explicitly marks this result as reproduced."}
    source_kind = str(claim.get("source_kind") or "").lower()
    if statuses & {"accepted", "published"} and (
        source_kind in COMPARE_INDEPENDENT_SOURCE_KINDS
        or any(qualifier_has_any(value, ("independent", "third_party", "third party", "measured")) for value in qualifiers)
    ):
        return {"state": "Independently-measured", "reason": "Accepted evidence is marked as independent or comes from an independent source kind."}
    if claim.get("source_evidence_id"):
        source_reason = "Source-linked assertion without independent or reproduced metadata."
        if source_kind in COMPARE_VENDOR_SOURCE_KINDS or any(qualifier_has_any(value, ("vendor", "official", "first_party", "first party")) for value in qualifiers):
            source_reason = "The assertion is source-linked to vendor or official reporting."
        return {"state": "Vendor-reported", "reason": source_reason}
    return {"state": "Incomparable", "reason": "The assertion has no linked source evidence."}


def compare_support_maps(claims):
    selection_ids = sorted({row.get("evidence_selection_id") for row in claims if row.get("evidence_selection_id")})
    source_ids = sorted({row.get("source_evidence_id") for row in claims if row.get("source_evidence_id")})
    selection_map = {}
    facts_by_selection = {}
    facts_by_source = {}
    if selection_ids:
        quoted = ", ".join(sql_string(value) for value in selection_ids)
        selections = ch_data(
            f"""
            SELECT selection_id, source_evidence_id, selection_kind, quote,
              context_before, context_after, source_anchor_json, status, updated_at
            FROM evidence_selections FINAL
            WHERE selection_id IN ({quoted})
            ORDER BY updated_at DESC
            LIMIT {len(selection_ids)}
            """,
            fallback=[],
        )
        selection_map = {row.get("selection_id"): row for row in selections}
    if selection_ids or source_ids:
        clauses = []
        if selection_ids:
            clauses.append(f"evidence_selection_id IN ({', '.join(sql_string(value) for value in selection_ids)})")
        if source_ids:
            clauses.append(f"source_evidence_id IN ({', '.join(sql_string(value) for value in source_ids)})")
        facts = ch_data(
            f"""
            SELECT proposed_fact_id, source_evidence_id, evidence_selection_id,
              fact_type, field_path, raw_value, normalized_value, unit,
              evidence_quote, source_anchor_json, status, updated_at
            FROM proposed_facts FINAL
            WHERE {" OR ".join(clauses)}
            ORDER BY updated_at DESC
            LIMIT 240
            """,
            fallback=[],
        )
        facts_by_selection = group_rows(facts, "evidence_selection_id")
        facts_by_source = group_rows(facts, "source_evidence_id")
    return selection_map, facts_by_selection, facts_by_source


def compare_fact_matches_claim(fact, claim):
    value = str(claim.get("value") or claim.get("claim_text") or "").strip().lower()
    if not value:
        return False
    fact_text = " ".join(str(fact.get(key) or "") for key in ("raw_value", "normalized_value", "evidence_quote")).lower()
    return value in fact_text or any(part and part in value for part in (str(fact.get("raw_value") or "").lower(), str(fact.get("normalized_value") or "").lower()))


def compare_evidence_item(kind, object_id, label, detail="", status="", source_evidence_id="", source_anchor=None, **extra):
    anchor = source_anchor if isinstance(source_anchor, dict) else {}
    item = {
        "kind": kind,
        "object_id": object_id or "",
        "label": label or title_case_label(kind),
        "detail": compact_text(detail, 1200),
        "status": status or "",
        "source_evidence_id": source_evidence_id or "",
        "anchor_type": anchor_type_for(extra, anchor),
        "anchor_label": anchor_label_for(extra, anchor),
    }
    item.update(extra)
    return item


def compare_claim_evidence(claim, selection_map, facts_by_selection, facts_by_source):
    if not claim:
        return []
    source_id = claim.get("source_evidence_id") or ""
    selection_id = claim.get("evidence_selection_id") or ""
    evidence = []
    if source_id:
        evidence.append(compare_evidence_item(
            "source_record",
            source_id,
            claim.get("source_label") or claim.get("source_kind") or "Source",
            claim.get("snippet") or claim.get("title") or claim.get("canonical_url") or source_id,
            "captured",
            source_id,
            title=claim.get("title") or "",
            canonical_url=claim.get("canonical_url") or "",
            captured_at=claim.get("captured_at") or "",
        ))
    claim_anchor = parse_raw_json(claim.get("source_anchor_json", ""))
    evidence.append(compare_evidence_item(
        "claim_stub",
        claim.get("claim_id") or "",
        "Claim assertion",
        claim.get("claim_text") or claim.get("value") or "",
        claim.get("review_state") or claim.get("status") or "",
        source_id,
        claim_anchor,
        evidence_relation=claim.get("evidence_relation") or "",
        updated_at=claim.get("updated_at") or "",
    ))
    selection = selection_map.get(selection_id)
    if selection:
        selection_anchor = parse_raw_json(selection.get("source_anchor_json", ""))
        evidence.append(compare_evidence_item(
            "evidence_selection",
            selection.get("selection_id") or "",
            title_case_label(selection.get("selection_kind") or "evidence selection"),
            first_nonempty(selection.get("quote"), selection.get("context_before"), selection.get("context_after")),
            selection.get("status") or "",
            selection.get("source_evidence_id") or source_id,
            selection_anchor,
            selection_kind=selection.get("selection_kind") or "",
            updated_at=selection.get("updated_at") or "",
        ))
    facts = list(facts_by_selection.get(selection_id, []))
    if not facts and source_id:
        facts = [fact for fact in facts_by_source.get(source_id, []) if compare_fact_matches_claim(fact, claim)]
    for fact in facts[:3]:
        fact_anchor = parse_raw_json(fact.get("source_anchor_json", ""))
        fact_value = first_nonempty(fact.get("normalized_value"), fact.get("raw_value"), fact.get("evidence_quote"))
        evidence.append(compare_evidence_item(
            "proposed_fact",
            fact.get("proposed_fact_id") or "",
            fact.get("fact_type") or "Proposed fact",
            fact_value,
            fact.get("status") or "",
            fact.get("source_evidence_id") or source_id,
            fact_anchor,
            field_path=fact.get("field_path") or "",
            unit=fact.get("unit") or "",
            updated_at=fact.get("updated_at") or "",
        ))
    return evidence


def compare_claim_summary(row, selection_map, facts_by_selection, facts_by_source):
    evidence = compare_claim_evidence(row, selection_map, facts_by_selection, facts_by_source)
    return {
        "claim_id": row.get("claim_id") or "",
        "claim_text": row.get("claim_text") or "",
        "value": row.get("value") or "",
        "review_state": row.get("review_state") or "",
        "contradiction_state": row.get("contradiction_state") or "",
        "evidence_relation": row.get("evidence_relation") or "",
        "source_evidence_id": row.get("source_evidence_id") or "",
        "source_label": row.get("source_label") or source_kind_label(row.get("source_kind")),
        "source_title": row.get("title") or "",
        "evidence_selection_id": row.get("evidence_selection_id") or "",
        "updated_at": row.get("updated_at") or "",
        "qualifier": row.get("qualifier") or {},
        "evidence": evidence,
    }


def compare_view(params):
    project = resolve_project_id((params.get("project_id", params.get("project", [""]))[0] or "").strip())
    view_id = (params.get("view_id", [""])[0] or "claims").strip()
    claims = [row for row in scoped_claim_rows(project, 240) if row.get("subject_scoped")]
    selection_map, facts_by_selection, facts_by_source = compare_support_maps(claims)
    subjects = []
    for row in claims:
        subject = row.get("subject") or ""
        if subject and subject not in subjects:
            subjects.append(subject)
    subjects = subjects[:10]
    properties = []
    for row in claims:
        prop = row.get("property") or row.get("claim_type") or "general"
        if prop not in properties:
            properties.append(prop)
    rows = []
    for prop in properties[:40]:
        cells = []
        for subject in subjects:
            matches = [row for row in claims if row.get("subject") == subject and (row.get("property") or row.get("claim_type") or "general") == prop]
            values = {str(row.get("value") or row.get("claim_text") or "").lower() for row in matches}
            selected = compare_select_claim(matches)
            decision = compare_cell_decision(selected, matches, values)
            assertions = [compare_claim_summary(row, selection_map, facts_by_selection, facts_by_source) for row in matches[:8]]
            evidence = compare_claim_evidence(selected, selection_map, facts_by_selection, facts_by_source) if selected else []
            source_ids = sorted({row.get("source_evidence_id") for row in matches if row.get("source_evidence_id")})
            cells.append({
                "entity": subject,
                "state": decision["state"],
                "state_reason": decision["reason"],
                "value": selected.get("value") if selected else "",
                "claim_id": selected.get("claim_id") if selected else "",
                "source_evidence_id": selected.get("source_evidence_id") if selected else "",
                "source_ids": source_ids,
                "evidence_count": len(evidence),
                "assertion_count": len(matches),
                "assertions": assertions,
                "evidence": evidence,
                "qualifier": selected.get("qualifier") if selected else {},
            })
        rows.append({"property": prop, "cells": cells})
    return read_envelope({
        "scope": {"project": project or "all", "view_id": view_id, "surface": "compare"},
        "columns": [{"id": subject, "label": subject} for subject in subjects],
        "rows": rows,
        "legend": COMPARE_STATES,
        "summary": {
            "entities": len(subjects),
            "properties": len(rows),
            "cells": sum(len(row.get("cells") or []) for row in rows),
            "disputed": sum(1 for row in rows for cell in row.get("cells") or [] if cell.get("state") == "Disputed"),
        },
    }, "compare-view.v1", now_iso(), False, ["navigate", "open_source", "review"])


def benchmark_methodology_row(project, benchmark_id):
    rows = ch_data(
        f"""
        SELECT methodology_id, benchmark_id, project, dataset, prompting,
          harness, scoring, hardware, notes, source_evidence_id, source_version,
          status, actor, created_at, updated_at
        FROM benchmark_methodologies FINAL
        WHERE project = {sql_string(project)}
          AND benchmark_id = {sql_string(benchmark_id)}
          AND status != 'removed'
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        fallback=[],
    )
    return rows[0] if rows else {}


def benchmark_group_rows(project, benchmark_id):
    rows = ch_data(
        f"""
        SELECT group_id, benchmark_id, project, config_key, group_label,
          config_json, compatible, default_ranked, source_evidence_id,
          status, actor, created_at, updated_at
        FROM benchmark_result_groups FINAL
        WHERE project = {sql_string(project)}
          AND benchmark_id = {sql_string(benchmark_id)}
          AND status != 'removed'
        ORDER BY updated_at DESC
        LIMIT 240
        """,
        fallback=[],
    )
    latest = {}
    for row in rows:
        latest.setdefault(row.get("config_key") or "", row)
    return latest


def benchmark_config_key(qualifier):
    return hashlib.sha1(json_text(qualifier).encode("utf-8")).hexdigest()[:12]


def benchmark_methodology_complete(row):
    required = ("dataset", "prompting", "harness", "scoring", "source_evidence_id")
    return all(compact_text(row.get(key), 2000) for key in required)


def benchmark_detail(params):
    benchmark_id = ((params.get("benchmark_id", [""])[0] or "") or (params.get("id", [""])[0] or "") or "benchmark").strip()
    project = resolve_project_id((params.get("project", [""])[0] or "").strip())
    claims = [
        row for row in scoped_claim_rows(project, 240, benchmark_id if benchmark_id != "benchmark" else "benchmark")
        if "benchmark" in str(row.get("claim_type") or row.get("claim_text") or "").lower()
    ]
    methodology = benchmark_methodology_row(project, benchmark_id)
    groups = benchmark_group_rows(project, benchmark_id)
    results = []
    for row in claims:
        qualifier = row.get("qualifier") or {}
        config_key = benchmark_config_key(qualifier)
        persisted_group = groups.get(config_key) or {}
        incompatible = bool(qualifier.get("incompatible") or qualifier.get("different_setup"))
        compatible = bool(int(persisted_group.get("compatible") or 0)) if persisted_group else not incompatible
        default_ranked = bool(int(persisted_group.get("default_ranked") or 0)) if persisted_group else not incompatible
        if not compatible:
            default_ranked = False
        results.append({
            "result_id": row.get("claim_id"),
            "model": row.get("subject") if row.get("subject_scoped") else row.get("title") or row.get("source_evidence_id"),
            "metric": row.get("property") or row.get("claim_type") or "benchmark_result",
            "value": row.get("value") or row.get("claim_text"),
            "config": qualifier,
            "config_key": config_key,
            "group_id": persisted_group.get("group_id") or "",
            "group_label": persisted_group.get("group_label") or title_case_label(row.get("claim_type") or "default"),
            "compatible": compatible,
            "default_ranked": default_ranked,
            "review_state": row.get("review_state"),
            "source_evidence_id": row.get("source_evidence_id"),
        })
    methodology_missing = not benchmark_methodology_complete(methodology)
    return read_envelope({
        "header": {
            "benchmark_id": benchmark_id,
            "label": title_case_label(benchmark_id),
            "project": project,
            "methodology_state": "source_linked" if not methodology_missing else "missing",
            "publication_blocked": methodology_missing,
        },
        "methodology": {
            "methodology_id": methodology.get("methodology_id") or "",
            "dataset": methodology.get("dataset") or "",
            "prompting": methodology.get("prompting") or "",
            "harness": methodology.get("harness") or "",
            "scoring": methodology.get("scoring") or "",
            "hardware": methodology.get("hardware") or "",
            "notes": methodology.get("notes") or "Methodology fields must be filled from source-linked evidence before leaderboard publication.",
            "source_evidence_id": methodology.get("source_evidence_id") or "",
            "source_version": methodology.get("source_version") or "",
            "status": methodology.get("status") or "draft",
            "updated_at": methodology.get("updated_at") or "",
        },
        "result_groups": list(groups.values()),
        "results": results,
        "excluded_from_default_ranking": [row for row in results if not row.get("default_ranked")],
        "checks": [
            {"id": "methodology", "state": "blocked" if methodology_missing else "pass", "label": "Methodology fields are source-linked"},
            {"id": "compatible_configs", "state": "pass" if all(row.get("compatible") or not row.get("default_ranked") for row in results) else "blocked", "label": "Incompatible configs excluded from default ranking"},
            {"id": "source_links", "state": "pass" if results and all(row.get("source_evidence_id") for row in results) else "needs_work", "label": "Every result exposes source evidence"},
        ],
    }, "benchmark-detail.v2", now_iso(), methodology_missing, ["navigate", "review", "open_source"])


def benchmark_params_from_payload(payload):
    project = resolve_project_id(compact_text(payload.get("project") or payload.get("project_id"), 300))
    benchmark_id = compact_text(payload.get("benchmark_id") or "benchmark", 300)
    if not project:
        raise ResearchUiError(400, "project is required")
    return project, benchmark_id


def save_benchmark_methodology(payload):
    project, benchmark_id = benchmark_params_from_payload(payload)
    source_id = compact_text(payload.get("source_evidence_id"), 1000)
    if source_id.lower().startswith(("http://", "https://")):
        raise ResearchUiError(400, "Methodology source must be a platform source ID")
    source_map = hydrate_source_rows([source_id])
    source_version = compact_text(payload.get("source_version"), 500)
    if source_id and not source_version:
        source_version = draft_source_version(source_for_ledger_row(source_map, source_id))
    actor = compact_text(payload.get("actor") or REVIEW_ACTOR, 200)
    now = now_iso()
    methodology_id = compact_text(payload.get("methodology_id"), 300) or f"benchmark_methodology/{hashlib.sha1((project + '|' + benchmark_id).encode('utf-8')).hexdigest()[:24]}"
    row = {
        "methodology_id": methodology_id,
        "benchmark_id": benchmark_id,
        "project": project,
        "dataset": compact_text(payload.get("dataset"), 20000),
        "prompting": compact_text(payload.get("prompting"), 20000),
        "harness": compact_text(payload.get("harness"), 20000),
        "scoring": compact_text(payload.get("scoring"), 20000),
        "hardware": compact_text(payload.get("hardware"), 20000),
        "notes": compact_text(payload.get("notes"), 20000),
        "source_evidence_id": source_id,
        "source_version": source_version,
        "status": compact_text(payload.get("status") or "active", 80),
        "actor": actor,
        "created_at": payload.get("created_at") or now,
        "updated_at": now,
    }
    ch_insert_json_each_row("benchmark_methodologies", [row])
    event = persist_review_event(build_review_event("benchmark.methodology.saved", {
        "source_evidence_id": project_source_evidence_id(project),
        "project": project,
        "subject_type": "benchmark_methodology",
        "subject_id": methodology_id,
        "benchmark_id": benchmark_id,
        "actor": actor,
        "idempotency_key": compact_text(payload.get("idempotency_key"), 500),
        "source_anchor": {"kind": "benchmark_methodology", "benchmark_id": benchmark_id},
    }))
    return {"event": event, "benchmark": benchmark_detail({"project": [project], "benchmark_id": [benchmark_id]})}


def save_benchmark_result_group(payload):
    project, benchmark_id = benchmark_params_from_payload(payload)
    config_key = compact_text(payload.get("config_key"), 120)
    if not config_key:
        raise ResearchUiError(400, "config_key is required")
    actor = compact_text(payload.get("actor") or REVIEW_ACTOR, 200)
    now = now_iso()
    group_id = compact_text(payload.get("group_id"), 300) or f"benchmark_group/{hashlib.sha1((project + '|' + benchmark_id + '|' + config_key).encode('utf-8')).hexdigest()[:24]}"
    compatible = 1 if bool(payload.get("compatible")) else 0
    default_ranked = 1 if bool(payload.get("default_ranked")) and compatible else 0
    row = {
        "group_id": group_id,
        "benchmark_id": benchmark_id,
        "project": project,
        "config_key": config_key,
        "group_label": compact_text(payload.get("group_label") or config_key, 500),
        "config_json": json_text(payload.get("config") if isinstance(payload.get("config"), dict) else {}),
        "compatible": compatible,
        "default_ranked": default_ranked,
        "source_evidence_id": compact_text(payload.get("source_evidence_id"), 1000),
        "status": compact_text(payload.get("status") or "active", 80),
        "actor": actor,
        "created_at": payload.get("created_at") or now,
        "updated_at": now,
    }
    ch_insert_json_each_row("benchmark_result_groups", [row])
    event = persist_review_event(build_review_event("benchmark.result_group.saved", {
        "source_evidence_id": project_source_evidence_id(project),
        "project": project,
        "subject_type": "benchmark_result_group",
        "subject_id": group_id,
        "benchmark_id": benchmark_id,
        "config_key": config_key,
        "compatible": compatible,
        "default_ranked": default_ranked,
        "actor": actor,
        "idempotency_key": compact_text(payload.get("idempotency_key"), 500),
        "source_anchor": {"kind": "benchmark_result_group", "benchmark_id": benchmark_id, "config_key": config_key},
    }))
    return {"event": event, "benchmark": benchmark_detail({"project": [project], "benchmark_id": [benchmark_id]})}


ALLOWED_DRAFT_OBJECT_TYPES = {"claim_stub", "source_record", "evidence_selection", "proposed_fact", "entity_link", "taxonomy_term"}


def parse_json_list(value):
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except Exception:
        return []
    return parsed if isinstance(parsed, list) else []


def draft_source_version(source):
    return first_nonempty(source.get("last_ingested_at"), source.get("last_captured_at"), source.get("captured_at"))


def stable_draft_citation_id(draft_id, paragraph_id, object_type, object_id, source_evidence_id):
    raw = "|".join(str(value or "") for value in (draft_id, paragraph_id, object_type, object_id, source_evidence_id))
    return "draft_citation/" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]


def validate_draft_reference(ref):
    object_type = compact_text(ref.get("object_type"), 80)
    object_id = compact_text(ref.get("object_id"), 1000)
    source_id = compact_text(ref.get("source_evidence_id"), 1000)
    if object_type not in ALLOWED_DRAFT_OBJECT_TYPES:
        raise ResearchUiError(400, "Draft citations must reference platform object IDs")
    if not object_id:
        raise ResearchUiError(400, "Draft citation object_id is required")
    citation_text = compact_text(ref.get("citation_text") or ref.get("source_title") or object_id, 2000)
    if citation_text.lower().startswith(("http://", "https://")):
        citation_text = object_id
    forbidden = (object_id, source_id)
    if any(str(value).lower().startswith(("http://", "https://")) for value in forbidden if value):
        raise ResearchUiError(400, "Draft citations cannot store free-floating URLs")
    return {
        "object_type": object_type,
        "object_id": object_id,
        "object_version": compact_text(ref.get("object_version"), 500),
        "source_evidence_id": source_id,
        "source_version": compact_text(ref.get("source_version"), 500),
        "citation_text": citation_text,
        "status": compact_text(ref.get("status") or "active", 80),
    }


def latest_draft_revision(project, draft_id):
    rows = ch_data(
        f"""
        SELECT revision_id, draft_id, project, revision_number, title,
          paragraphs_json, status, actor, created_at, updated_at
        FROM draft_revisions FINAL
        WHERE project = {sql_string(project)} AND draft_id = {sql_string(draft_id)}
        ORDER BY revision_number DESC, updated_at DESC
        LIMIT 1
        """,
        fallback=[],
    )
    if not rows:
        return None
    row = rows[0]
    row["paragraphs"] = parse_json_list(row.get("paragraphs_json"))
    return row


def draft_citation_rows(project, draft_id):
    return ch_data(
        f"""
        SELECT citation_id, draft_id, project, paragraph_id, object_type,
          object_id, object_version, source_evidence_id, source_version,
          citation_text, status, actor, created_at, updated_at
        FROM draft_citations FINAL
        WHERE project = {sql_string(project)}
          AND draft_id = {sql_string(draft_id)}
          AND status != 'removed'
        ORDER BY updated_at ASC
        LIMIT 500
        """,
        fallback=[],
    )


def draft_diff_rows(project, draft_id):
    return ch_data(
        f"""
        SELECT diff_id, draft_id, project, paragraph_id, diff_kind,
          before_text, after_text, rationale, status, actor, created_at, updated_at
        FROM draft_proposed_diffs FINAL
        WHERE project = {sql_string(project)}
          AND draft_id = {sql_string(draft_id)}
          AND status != 'dismissed'
        ORDER BY updated_at DESC
        LIMIT 120
        """,
        fallback=[],
    )


def derived_draft_paragraphs(brief, claims, sources):
    paragraphs = []
    if brief.get("research_question"):
        paragraphs.append({
            "paragraph_id": "draft-paragraph/question",
            "section_id": "summary",
            "text": brief.get("research_question"),
            "references": [],
            "support_state": "context",
        })
    for claim in claims[:20]:
        source = source_for_ledger_row(sources, claim.get("source_evidence_id") or "")
        paragraphs.append({
            "paragraph_id": f"draft-paragraph/{claim.get('claim_id')}",
            "section_id": "evidence",
            "text": claim.get("claim_text") or claim.get("value") or "",
            "references": [{
                "object_type": "claim_stub",
                "object_id": claim.get("claim_id"),
                "object_version": claim.get("updated_at") or "",
                "source_evidence_id": claim.get("source_evidence_id") or "",
                "source_version": draft_source_version(source),
                "source_title": source.get("title") or "",
                "citation_text": source.get("title") or claim.get("claim_id") or "",
                "status": "derived",
            }],
            "support_state": "supported" if claim.get("source_evidence_id") else "unsupported",
        })
    for question in brief.get("open_questions") or []:
        paragraphs.append({
            "paragraph_id": f"draft-paragraph/{question.get('id')}",
            "section_id": "open_questions",
            "text": question.get("text") or "",
            "references": [],
            "support_state": "open_question",
        })
    return paragraphs


def decorate_draft_reference(ref, source_map):
    normalized = dict(ref)
    source_id = normalized.get("source_evidence_id") or ""
    source = source_for_ledger_row(source_map, source_id) if source_id else {}
    current_source_version = draft_source_version(source)
    stale = bool(source_id and normalized.get("source_version") and current_source_version and normalized.get("source_version") != current_source_version)
    normalized["citation_id"] = normalized.get("citation_id") or stable_draft_citation_id(
        normalized.get("draft_id") or "",
        normalized.get("paragraph_id") or "",
        normalized.get("object_type") or "",
        normalized.get("object_id") or "",
        source_id,
    )
    normalized["source_title"] = normalized.get("source_title") or source.get("title") or ""
    normalized["current_source_version"] = current_source_version
    normalized["stale"] = stale
    normalized["stale_reason"] = "Source capture changed since citation insertion." if stale else ""
    return normalized


def attach_draft_references(paragraphs, citations, source_map, project, draft_id):
    by_paragraph = group_rows(citations, "paragraph_id")
    decorated = []
    for paragraph in paragraphs:
        paragraph = dict(paragraph)
        paragraph_id = compact_text(paragraph.get("paragraph_id"), 300)
        refs = []
        seen = set()
        for ref in list(paragraph.get("references") or []) + by_paragraph.get(paragraph_id, []):
            try:
                normalized = validate_draft_reference(ref)
            except ResearchUiError:
                continue
            normalized["draft_id"] = draft_id
            normalized["project"] = project
            normalized["paragraph_id"] = paragraph_id
            normalized["citation_id"] = ref.get("citation_id") or stable_draft_citation_id(
                draft_id,
                paragraph_id,
                normalized["object_type"],
                normalized["object_id"],
                normalized["source_evidence_id"],
            )
            key = (normalized["object_type"], normalized["object_id"], normalized["source_evidence_id"])
            if key in seen:
                continue
            seen.add(key)
            refs.append(decorate_draft_reference(normalized, source_map))
        paragraph["references"] = refs
        if refs:
            paragraph["support_state"] = "supported"
        elif paragraph.get("support_state") not in ("context", "open_question"):
            paragraph["support_state"] = "unsupported"
        decorated.append(paragraph)
    return decorated


def draft_outline(paragraphs):
    labels = {
        "summary": "Summary",
        "evidence": "Evidence base",
        "open_questions": "Open questions",
        "limitations": "Limitations",
    }
    rows = []
    for section_id, label in labels.items():
        section_rows = [row for row in paragraphs if row.get("section_id") == section_id]
        unsupported = [row for row in section_rows if row.get("support_state") == "unsupported"]
        rows.append({
            "id": section_id,
            "label": label,
            "status": "blocked" if unsupported else ("draft" if section_rows else "empty"),
            "count": len(section_rows),
        })
    return rows


def draft_editor(params):
    project = resolve_project_id((params.get("project_id", params.get("project", [""]))[0] or "").strip())
    draft_id = (params.get("draft_id", [""])[0] or "working-draft").strip()
    brief = read_project_brief(project, project)
    claims = [row for row in scoped_claim_rows(project, 160) if row.get("review_state") in ("accepted", "published", "under_review", "draft", "proposed")]
    source_ids = [row.get("source_evidence_id") for row in claims]
    citations = draft_citation_rows(project, draft_id)
    source_ids.extend(row.get("source_evidence_id") for row in citations)
    sources = hydrate_source_rows(source_ids)
    revision = latest_draft_revision(project, draft_id)
    paragraphs = revision.get("paragraphs") if revision else derived_draft_paragraphs(brief, claims, sources)
    paragraphs = attach_draft_references(paragraphs, citations, sources, project, draft_id)
    references = [ref for paragraph in paragraphs for ref in paragraph.get("references") or []]
    unsupported = [row for row in paragraphs if not row.get("references") and row.get("support_state") not in ("context", "open_question")]
    stale_refs = [ref for ref in references if ref.get("stale")]
    diffs = draft_diff_rows(project, draft_id)
    evidence_rail = list(sources.values())[:80]
    revision_number = int((revision or {}).get("revision_number") or brief.get("version") or 1)
    title = (revision or {}).get("title") or f"{brief.get('project_name') or project} draft"
    return read_envelope({
        "header": {
            "draft_id": draft_id,
            "project": project,
            "title": title,
            "revision": revision_number,
            "revision_id": (revision or {}).get("revision_id") or "",
            "status": (revision or {}).get("status") or "draft",
            "updated_at": (revision or {}).get("updated_at") or brief.get("updated_at") or "",
        },
        "layout": {"outline_px": 260, "evidence_rail_px": 380},
        "outline": draft_outline(paragraphs),
        "paragraphs": paragraphs,
        "references": references,
        "evidence_rail": evidence_rail,
        "proposed_diffs": diffs,
        "checks": [
            {"id": "object_linked_refs", "state": "pass" if references and all(ref.get("object_type") in ALLOWED_DRAFT_OBJECT_TYPES for ref in references) else "needs_work", "label": "Citations are object references"},
            {"id": "unsupported_paragraphs", "state": "pass" if not unsupported else "blocked", "label": "Unsupported paragraphs are visible", "count": len(unsupported)},
            {"id": "source_version_stale", "state": "pass" if not stale_refs else "blocked", "label": "Citation staleness check uses source capture versions", "count": len(stale_refs)},
            {"id": "proposed_diffs", "state": "pass" if diffs else "needs_work", "label": "Proposed diffs are persisted", "count": len(diffs)},
        ],
        "unsupported_paragraphs": unsupported,
        "stale_citations": stale_refs,
    }, "draft-editor.v2", now_iso(), bool(stale_refs), ["navigate", "edit_draft", "insert_citation", "review"])


def draft_params_from_payload(payload):
    project = resolve_project_id(compact_text(payload.get("project") or payload.get("project_id"), 300))
    draft_id = compact_text(payload.get("draft_id") or "working-draft", 300)
    if not project:
        raise ResearchUiError(400, "project is required")
    return project, draft_id


def normalize_draft_paragraph_payload(payload):
    rows = payload.get("paragraphs")
    if not isinstance(rows, list):
        raise ResearchUiError(400, "paragraphs must be a list")
    normalized = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        paragraph_id = compact_text(row.get("paragraph_id") or f"draft-paragraph/{index + 1}", 300)
        references = []
        for ref in row.get("references") or []:
            if not isinstance(ref, dict):
                continue
            reference = validate_draft_reference(ref)
            reference["paragraph_id"] = paragraph_id
            reference["citation_id"] = ref.get("citation_id") or stable_draft_citation_id(
                compact_text(payload.get("draft_id") or "working-draft", 300),
                paragraph_id,
                reference["object_type"],
                reference["object_id"],
                reference["source_evidence_id"],
            )
            references.append(reference)
        support_state = compact_text(row.get("support_state") or ("supported" if references else "unsupported"), 80)
        normalized.append({
            "paragraph_id": paragraph_id,
            "section_id": compact_text(row.get("section_id") or "evidence", 120),
            "text": compact_text(row.get("text"), 50000),
            "references": references,
            "support_state": support_state,
        })
    return normalized


def draft_citation_insert_rows(project, draft_id, paragraphs_or_refs, actor):
    refs = []
    if isinstance(paragraphs_or_refs, list):
        for item in paragraphs_or_refs:
            if not isinstance(item, dict):
                continue
            if item.get("paragraph_id") and item.get("object_type"):
                refs.append(item)
            else:
                paragraph_id = compact_text(item.get("paragraph_id"), 300)
                for ref in item.get("references") or []:
                    if isinstance(ref, dict):
                        refs.append({**ref, "paragraph_id": paragraph_id})
    source_map = hydrate_source_rows([ref.get("source_evidence_id") for ref in refs])
    now = now_iso()
    rows = []
    seen = set()
    for ref in refs:
        normalized = validate_draft_reference(ref)
        paragraph_id = compact_text(ref.get("paragraph_id"), 300)
        source_id = normalized["source_evidence_id"]
        source = source_for_ledger_row(source_map, source_id) if source_id else {}
        source_version = normalized["source_version"] or draft_source_version(source)
        citation_id = compact_text(ref.get("citation_id"), 300) or stable_draft_citation_id(
            draft_id,
            paragraph_id,
            normalized["object_type"],
            normalized["object_id"],
            source_id,
        )
        if citation_id in seen:
            continue
        seen.add(citation_id)
        rows.append({
            "citation_id": citation_id,
            "draft_id": draft_id,
            "project": project,
            "paragraph_id": paragraph_id,
            "object_type": normalized["object_type"],
            "object_id": normalized["object_id"],
            "object_version": normalized["object_version"],
            "source_evidence_id": source_id,
            "source_version": source_version,
            "citation_text": normalized["citation_text"],
            "status": normalized["status"],
            "actor": actor,
            "created_at": ref.get("created_at") or now,
            "updated_at": now,
        })
    return rows


def create_draft_revision(payload):
    project, draft_id = draft_params_from_payload(payload)
    actor = compact_text(payload.get("actor") or REVIEW_ACTOR, 200)
    paragraphs = normalize_draft_paragraph_payload({**payload, "draft_id": draft_id})
    latest = latest_draft_revision(project, draft_id)
    revision_number = int((latest or {}).get("revision_number") or 0) + 1
    now = now_iso()
    revision_id = compact_text(payload.get("revision_id"), 300) or make_id("draft_revision")
    title = compact_text(payload.get("title") or f"{project} draft", 500)
    ch_insert_json_each_row("draft_revisions", [{
        "revision_id": revision_id,
        "draft_id": draft_id,
        "project": project,
        "revision_number": revision_number,
        "title": title,
        "paragraphs_json": json_text(paragraphs),
        "status": compact_text(payload.get("status") or "draft", 80),
        "actor": actor,
        "created_at": now,
        "updated_at": now,
    }])
    citation_rows = draft_citation_insert_rows(project, draft_id, paragraphs, actor)
    ch_insert_json_each_row("draft_citations", citation_rows)
    event = persist_review_event(build_review_event("draft.revision.saved", {
        "source_evidence_id": project_source_evidence_id(project),
        "project": project,
        "subject_type": "draft_revision",
        "subject_id": revision_id,
        "draft_id": draft_id,
        "revision_number": revision_number,
        "actor": actor,
        "idempotency_key": compact_text(payload.get("idempotency_key"), 500),
        "source_anchor": {"kind": "draft_revision", "draft_id": draft_id, "revision_id": revision_id},
    }))
    params = {"project_id": [project], "draft_id": [draft_id]}
    return {"event": event, "draft": draft_editor(params)}


def insert_draft_citation(payload):
    project, draft_id = draft_params_from_payload(payload)
    actor = compact_text(payload.get("actor") or REVIEW_ACTOR, 200)
    paragraph_id = compact_text(payload.get("paragraph_id"), 300)
    if not paragraph_id:
        raise ResearchUiError(400, "paragraph_id is required")
    object_type = compact_text(payload.get("object_type") or "source_record", 80)
    source_id = compact_text(payload.get("source_evidence_id") or (payload.get("object_id") if object_type == "source_record" else ""), 1000)
    ref = {
        "paragraph_id": paragraph_id,
        "citation_id": compact_text(payload.get("citation_id"), 300),
        "object_type": object_type,
        "object_id": compact_text(payload.get("object_id") or source_id, 1000),
        "object_version": compact_text(payload.get("object_version"), 500),
        "source_evidence_id": source_id,
        "source_version": compact_text(payload.get("source_version"), 500),
        "citation_text": compact_text(payload.get("citation_text") or payload.get("source_title") or payload.get("object_id") or source_id, 2000),
        "status": compact_text(payload.get("status") or "active", 80),
    }
    citation_rows = draft_citation_insert_rows(project, draft_id, [ref], actor)
    ch_insert_json_each_row("draft_citations", citation_rows)
    event = persist_review_event(build_review_event("draft.citation.inserted", {
        "source_evidence_id": project_source_evidence_id(project),
        "project": project,
        "subject_type": "draft_citation",
        "subject_id": citation_rows[0]["citation_id"] if citation_rows else "",
        "draft_id": draft_id,
        "paragraph_id": paragraph_id,
        "object_type": ref["object_type"],
        "object_id": ref["object_id"],
        "actor": actor,
        "idempotency_key": compact_text(payload.get("idempotency_key"), 500),
        "source_anchor": {"kind": "draft_citation", "draft_id": draft_id, "paragraph_id": paragraph_id},
    }))
    return {"event": event, "draft": draft_editor({"project_id": [project], "draft_id": [draft_id]})}


def create_draft_proposed_diff(payload):
    project, draft_id = draft_params_from_payload(payload)
    paragraph_id = compact_text(payload.get("paragraph_id"), 300)
    if not paragraph_id:
        raise ResearchUiError(400, "paragraph_id is required")
    actor = compact_text(payload.get("actor") or REVIEW_ACTOR, 200)
    now = now_iso()
    diff_id = compact_text(payload.get("diff_id"), 300) or make_id("draft_diff")
    row = {
        "diff_id": diff_id,
        "draft_id": draft_id,
        "project": project,
        "paragraph_id": paragraph_id,
        "diff_kind": compact_text(payload.get("diff_kind") or "support_gap", 80),
        "before_text": compact_text(payload.get("before_text"), 50000),
        "after_text": compact_text(payload.get("after_text"), 50000),
        "rationale": compact_text(payload.get("rationale") or "Needs an object-linked citation before publication.", 20000),
        "status": compact_text(payload.get("status") or "proposed", 80),
        "actor": actor,
        "created_at": payload.get("created_at") or now,
        "updated_at": now,
    }
    ch_insert_json_each_row("draft_proposed_diffs", [row])
    event = persist_review_event(build_review_event("draft.diff.proposed", {
        "source_evidence_id": project_source_evidence_id(project),
        "project": project,
        "subject_type": "draft_proposed_diff",
        "subject_id": diff_id,
        "draft_id": draft_id,
        "paragraph_id": paragraph_id,
        "actor": actor,
        "idempotency_key": compact_text(payload.get("idempotency_key"), 500),
        "source_anchor": {"kind": "draft_proposed_diff", "draft_id": draft_id, "paragraph_id": paragraph_id},
    }))
    return {"event": event, "draft": draft_editor({"project_id": [project], "draft_id": [draft_id]})}


def frozen_publication_manifest(bundle):
    project = bundle.get("project") or ""
    sources = source_rows_for_project(project, 200)
    source_ids = [row.get("evidence_id") for row in sources if row.get("evidence_id")]
    project_clause = review_project_where(project)
    claims = scoped_claim_rows(project, 200)
    selections = ch_data(
        f"""
        SELECT selection_id, source_evidence_id, document_id, block_id, selection_kind,
          quote, source_anchor_json, status, actor, created_at, updated_at
        FROM evidence_selections FINAL
        WHERE {project_clause}
        ORDER BY updated_at DESC
        LIMIT 200
        """,
        fallback=[],
    )
    entities = ch_data(
        f"""
        SELECT entity_link_id, source_evidence_id, mention_text, entity_type,
          canonical_entity_id, canonical_name, status, actor, created_at, updated_at
        FROM entity_links FINAL
        WHERE {project_clause}
        ORDER BY updated_at DESC
        LIMIT 200
        """,
        fallback=[],
    )
    taxonomy_terms = taxonomy_read_model({"queue": ["all"], "limit": ["200"]}).get("rows", [])
    brief = read_project_brief(project, project)
    manifest = {
        "bundle": {key: bundle.get(key) for key in ("bundle_id", "package_type", "project", "title", "target", "draft_revision", "manifest_version")},
        "draft": {"project_brief_id": brief.get("id"), "revision": brief.get("version"), "updated_at": brief.get("updated_at")},
        "claim_ids": [row.get("claim_id") for row in claims if row.get("claim_id")],
        "evidence_selection_ids": [row.get("selection_id") for row in selections if row.get("selection_id")],
        "source_capture_ids": source_ids,
        "entity_link_ids": [row.get("entity_link_id") for row in entities if row.get("entity_link_id")],
        "taxonomy_term_ids": [row.get("stable_id") for row in taxonomy_terms if row.get("usage_total") or row.get("review_state") == "accepted"],
        "public_config": {"target": bundle.get("target") or "", "package_type": bundle.get("package_type") or "", "visibility": "internal_until_release"},
        "claims": claims,
        "evidence": selections,
        "sources": sources,
        "entities": entities,
        "checks": bundle.get("checks") or [],
        "generated_at": now_iso(),
    }
    manifest_hash = hashlib.sha256(json_text(manifest).encode("utf-8")).hexdigest()
    manifest["manifest_hash"] = manifest_hash
    return manifest, manifest_hash


def publication_manifest_object_ids(manifest):
    keys = (
        "source_capture_ids",
        "claim_ids",
        "evidence_selection_ids",
        "entity_link_ids",
        "taxonomy_term_ids",
    )
    object_ids = {}
    for key in keys:
        values = manifest.get(key) or []
        if not isinstance(values, list):
            values = []
        object_ids[key] = [compact_text(value, 1000) for value in values if compact_text(value, 1000)]
    return object_ids


def publication_public_config(manifest, bundle=None):
    bundle = bundle or {}
    manifest_bundle = manifest.get("bundle") if isinstance(manifest.get("bundle"), dict) else {}
    manifest_config = manifest.get("public_config") if isinstance(manifest.get("public_config"), dict) else {}
    return {
        "target": compact_text(first_nonempty(manifest_config.get("target"), manifest_bundle.get("target"), bundle.get("target")), 300),
        "package_type": compact_text(first_nonempty(manifest_config.get("package_type"), manifest_bundle.get("package_type"), bundle.get("package_type")), 120),
        "visibility": compact_text(manifest_config.get("visibility") or "internal_until_release", 120),
        "draft_revision": compact_text(first_nonempty(manifest_bundle.get("draft_revision"), bundle.get("draft_revision")), 120),
        "manifest_version": compact_text(first_nonempty(manifest_bundle.get("manifest_version"), bundle.get("manifest_version")), 120),
    }


def publication_handoff_artifact(snapshot, bundle, handoff_id, artifact_kind, created_at):
    manifest = snapshot.get("manifest") if isinstance(snapshot.get("manifest"), dict) else {}
    manifest_bundle = manifest.get("bundle") if isinstance(manifest.get("bundle"), dict) else {}
    object_ids = publication_manifest_object_ids(manifest)
    public_config = publication_public_config(manifest, bundle)
    object_counts = {
        key: len(values) if isinstance(values, list) else 0
        for key, values in object_ids.items()
    }
    manifest_hash = snapshot.get("manifest_hash") or manifest.get("manifest_hash") or ""
    return {
        "schema_version": "publication_handoff.v1",
        "handoff_id": handoff_id,
        "artifact_kind": artifact_kind,
        "status": "ready",
        "created_at": created_at,
        "snapshot": {
            "snapshot_id": snapshot.get("snapshot_id") or "",
            "bundle_id": snapshot.get("bundle_id") or "",
            "project": snapshot.get("project") or "",
            "snapshot_state": snapshot.get("snapshot_state") or "",
            "review_state": snapshot.get("review_state") or "",
            "manifest_hash": manifest_hash,
        },
        "bundle": {
            "bundle_id": manifest_bundle.get("bundle_id") or snapshot.get("bundle_id") or "",
            "title": manifest_bundle.get("title") or bundle.get("title") or "",
            "package_type": public_config.get("package_type") or "",
            "target": public_config.get("target") or "",
        },
        "manifest_hash": manifest_hash,
        "object_ids": object_ids,
        "object_counts": object_counts,
        "public_config": public_config,
        "checks": [
            {key: check.get(key) for key in ("id", "label", "state", "detail")}
            for check in (snapshot.get("checks") or manifest.get("checks") or [])
            if isinstance(check, dict)
        ],
    }


def publication_bundle_by_id(bundle_id):
    model = publishing_read_model({"limit": ["200"]})
    for row in model.get("bundles") or []:
        if row.get("bundle_id") == bundle_id:
            return row
    raise ResearchUiError(404, f"Publication bundle not found: {bundle_id}")


def publication_detail_checks(bundle, snapshot, manifest):
    sources = manifest.get("sources") or []
    claims = manifest.get("claims") or []
    evidence = manifest.get("evidence") or []
    disputed = [row for row in claims if row.get("contradiction_state") in ("conflict", "disputed") or row.get("review_state") == "disputed"]
    checks = [
        {"id": "source_anchors", "label": "Exact source anchors resolve", "state": "pass" if evidence or sources else "blocked", "detail": f"{len(evidence)} evidence selections; {len(sources)} source captures."},
        {"id": "claim_review", "label": "Claims reviewed or explicitly marked draft", "state": "pass" if claims else "needs_work", "detail": f"{len(claims)} claim object(s) included."},
        {"id": "contradictions", "label": "Unresolved contradictions are excluded or visible", "state": "blocked" if disputed else "pass", "detail": f"{len(disputed)} disputed claim(s)."},
        {"id": "source_diversity", "label": "Source diversity is visible", "state": "pass" if len({row.get('source_kind') for row in sources if row.get('source_kind')}) >= 2 else "needs_work", "detail": "Diversity is computed from pinned source captures."},
        {"id": "media_ocr", "label": "Media/OCR coverage checked", "state": "pass" if not any(row.get("has_media") and not row.get("has_ocr") for row in sources) else "needs_work", "detail": "Media sources without OCR stay visible as blockers."},
        {"id": "citation_refs", "label": "Citations are object references", "state": "pass", "detail": "Snapshot pins claim, evidence, source, entity, and taxonomy IDs."},
        {"id": "taxonomy", "label": "Taxonomy IDs are frozen", "state": "pass" if manifest.get("taxonomy_term_ids") else "needs_work", "detail": f"{len(manifest.get('taxonomy_term_ids') or [])} taxonomy IDs."},
        {"id": "private_data", "label": "Private config is excluded", "state": "pass", "detail": "Manifest stores IDs and public config, not environment secrets."},
        {"id": "public_config", "label": "Public target config exists", "state": "pass" if manifest.get("public_config") else "blocked", "detail": bundle.get("target") or "No target."},
        {"id": "snapshot", "label": "Frozen snapshot exists", "state": "pass" if snapshot else "needs_work", "detail": (snapshot or {}).get("snapshot_id") or "No snapshot yet."},
        {"id": "approval", "label": "Approved snapshot gates publish", "state": "pass" if snapshot and snapshot.get("review_state") == "approved" else "needs_work", "detail": (snapshot or {}).get("review_state") or "Not reviewed."},
    ]
    return checks


def publication_detail(params):
    bundle_id = (params.get("bundle_id", [""])[0] or "").strip()
    if not bundle_id:
        raise ResearchUiError(400, "bundle_id is required")
    bundle = publication_bundle_by_id(bundle_id)
    snapshot = latest_publication_snapshots([bundle_id]).get(bundle_id)
    release = latest_publication_releases([bundle_id]).get(bundle_id)
    handoffs = publication_handoff_rows([bundle_id])
    if snapshot and snapshot.get("manifest"):
        manifest = snapshot.get("manifest") or {}
        manifest_hash = snapshot.get("manifest_hash") or manifest.get("manifest_hash") or ""
    else:
        manifest, manifest_hash = frozen_publication_manifest(bundle)
    checks = publication_detail_checks(bundle, snapshot, manifest)
    changed_content = [
        {"label": "Draft revision", "before": bundle.get("draft_revision") or "", "after": manifest.get("draft", {}).get("revision") or "", "state": "tracked"},
        {"label": "Manifest hash", "before": bundle.get("manifest_hash") or "", "after": manifest_hash, "state": "tracked"},
    ]
    return read_envelope({
        "bundle": bundle,
        "snapshot": snapshot or {},
        "release": release or {},
        "manifest_hash": manifest_hash,
        "manifest_summary": {
            "claims": len(manifest.get("claims") or []),
            "evidence": len(manifest.get("evidence") or []),
            "sources": len(manifest.get("sources") or []),
            "entities": len(manifest.get("entities") or []),
            "taxonomy_terms": len(manifest.get("taxonomy_term_ids") or []),
            "handoffs": len(handoffs),
        },
        "tabs": ["overview", "changed_content", "claims", "evidence", "contradictions", "checks", "handoff", "discussion", "public_preview"],
        "checks": checks,
        "changed_content": changed_content,
        "claims": (manifest.get("claims") or [])[:120],
        "evidence": (manifest.get("evidence") or [])[:120],
        "sources": (manifest.get("sources") or [])[:120],
        "entities": (manifest.get("entities") or [])[:120],
        "handoffs": handoffs,
        "contradictions": [row for row in manifest.get("claims") or [] if row.get("contradiction_state") in ("conflict", "disputed") or row.get("review_state") == "disputed"],
        "discussion": ch_data(
            f"""
            SELECT event_id, event_type, actor, created_at, payload_json
            FROM research_review_events
            WHERE subject_type IN ('publication_bundle', 'publication_snapshot')
              AND (subject_id = {sql_string(bundle_id)} OR JSONExtractString(payload_json, 'bundle_id') = {sql_string(bundle_id)})
            ORDER BY created_at DESC
            LIMIT 80
            """,
            fallback=[],
        ),
        "public_preview": {
            "title": bundle.get("title"),
            "target": bundle.get("target"),
            "claim_count": len(manifest.get("claims") or []),
            "citation_count": len(manifest.get("source_capture_ids") or []),
        },
        "actions": apply_publication_persistence(bundle, snapshot, release, handoffs).get("permitted_actions") or [],
    }, "publication-detail.v1", now_iso(), False, ["navigate", "create_snapshot", "review", "publish"])


def insert_publication_snapshot_row(row):
    ch_insert_json_each_row("publication_snapshots", [{
        "snapshot_id": row["snapshot_id"],
        "bundle_id": row["bundle_id"],
        "project": row.get("project") or "",
        "package_type": row.get("package_type") or "",
        "snapshot_state": row.get("snapshot_state") or "frozen",
        "review_state": row.get("review_state") or "draft",
        "release_state": row.get("release_state") or "unpublished",
        "manifest_hash": row.get("manifest_hash") or "",
        "manifest_json": json_text(row.get("manifest") or {}),
        "checks_json": json_text(row.get("checks") or []),
        "actor": row.get("actor") or REVIEW_ACTOR,
        "note": row.get("note") or "",
        "created_at": row.get("created_at") or now_iso(),
        "updated_at": row.get("updated_at") or now_iso(),
    }])


def create_publication_snapshot(payload):
    bundle_id = compact_text(payload.get("bundle_id"), 120)
    if not bundle_id:
        raise ResearchUiError(400, "bundle_id is required")
    bundle = publication_bundle_by_id(bundle_id)
    manifest, manifest_hash = frozen_publication_manifest(bundle)
    now = now_iso()
    snapshot = {
        "snapshot_id": compact_text(payload.get("snapshot_id"), 200) or make_id("publication_snapshot"),
        "bundle_id": bundle_id,
        "project": bundle.get("project") or "",
        "package_type": bundle.get("package_type") or "",
        "snapshot_state": "frozen",
        "review_state": "draft",
        "release_state": "unpublished",
        "manifest_hash": manifest_hash,
        "manifest": manifest,
        "checks": publication_detail_checks(bundle, None, manifest),
        "actor": compact_text(payload.get("actor") or REVIEW_ACTOR, 200),
        "note": compact_text(payload.get("note"), 20000),
        "created_at": now,
        "updated_at": now,
    }
    insert_publication_snapshot_row(snapshot)
    event = persist_review_event(build_review_event("publication.snapshot.created", {
        **payload,
        "source_evidence_id": project_source_evidence_id(snapshot["project"]),
        "project": snapshot["project"],
        "subject_type": "publication_snapshot",
        "subject_id": snapshot["snapshot_id"],
        "bundle_id": bundle_id,
        "snapshot_id": snapshot["snapshot_id"],
        "manifest_hash": manifest_hash,
        "source_anchor": {"kind": "publication_snapshot", "bundle_id": bundle_id, "snapshot_id": snapshot["snapshot_id"], "manifest_hash": manifest_hash},
    }))
    return {"snapshot": snapshot, "event": event, "detail": publication_detail({"bundle_id": [bundle_id]})}


def latest_snapshot_for_update(payload):
    bundle_id = compact_text(payload.get("bundle_id"), 120)
    if not bundle_id:
        raise ResearchUiError(400, "bundle_id is required")
    snapshot = latest_publication_snapshots([bundle_id]).get(bundle_id)
    if not snapshot:
        raise ResearchUiError(409, "Create a snapshot before requesting review, approving, or publishing")
    snapshot_id = compact_text(payload.get("snapshot_id"), 200)
    if snapshot_id and snapshot.get("snapshot_id") != snapshot_id:
        raise ResearchUiError(409, "A newer snapshot exists for this bundle")
    expected = compact_text(payload.get("expected_version"), 120)
    if expected and expected != (snapshot.get("updated_at") or ""):
        raise ResearchUiError(409, "Publication snapshot changed since it was loaded")
    return bundle_id, snapshot


def insert_publication_handoff_row(row):
    ch_insert_json_each_row("publication_handoffs", [{
        "handoff_id": row["handoff_id"],
        "snapshot_id": row.get("snapshot_id") or "",
        "bundle_id": row.get("bundle_id") or "",
        "project": row.get("project") or "",
        "artifact_kind": row.get("artifact_kind") or "public_export_manifest",
        "manifest_hash": row.get("manifest_hash") or "",
        "object_ids_json": json_text(row.get("object_ids") or {}),
        "public_config_json": json_text(row.get("public_config") or {}),
        "artifact_json": json_text(row.get("artifact") or {}),
        "status": row.get("status") or "ready",
        "actor": row.get("actor") or REVIEW_ACTOR,
        "note": row.get("note") or "",
        "created_at": row.get("created_at") or now_iso(),
        "updated_at": row.get("updated_at") or now_iso(),
    }])


def create_publication_handoff(payload):
    bundle_id, snapshot = latest_snapshot_for_update(payload)
    if snapshot.get("review_state") != "approved":
        raise ResearchUiError(409, "Snapshot must be approved before creating a handoff artifact")
    bundle = publication_bundle_by_id(bundle_id)
    now = now_iso()
    artifact_kind = compact_text(payload.get("artifact_kind") or "public_export_manifest", 120)
    handoff_id = compact_text(payload.get("handoff_id"), 200) or make_id("publication_handoff")
    artifact = publication_handoff_artifact(snapshot, bundle, handoff_id, artifact_kind, now)
    row = {
        "handoff_id": handoff_id,
        "snapshot_id": snapshot.get("snapshot_id") or "",
        "bundle_id": bundle_id,
        "project": snapshot.get("project") or "",
        "artifact_kind": artifact_kind,
        "manifest_hash": snapshot.get("manifest_hash") or artifact.get("manifest_hash") or "",
        "object_ids": artifact.get("object_ids") or {},
        "public_config": artifact.get("public_config") or {},
        "artifact": artifact,
        "status": "ready",
        "actor": compact_text(payload.get("actor") or REVIEW_ACTOR, 200),
        "note": compact_text(payload.get("note"), 20000),
        "created_at": now,
        "updated_at": now,
    }
    insert_publication_handoff_row(row)
    event = persist_review_event(build_review_event("publication.handoff.created", {
        **payload,
        "source_evidence_id": project_source_evidence_id(row["project"]),
        "project": row["project"],
        "subject_type": "publication_handoff",
        "subject_id": handoff_id,
        "bundle_id": bundle_id,
        "snapshot_id": row["snapshot_id"],
        "handoff_id": handoff_id,
        "artifact_kind": artifact_kind,
        "manifest_hash": row["manifest_hash"],
        "source_anchor": {
            "kind": "publication_handoff",
            "bundle_id": bundle_id,
            "snapshot_id": row["snapshot_id"],
            "handoff_id": handoff_id,
            "manifest_hash": row["manifest_hash"],
        },
    }))
    return {
        "handoff": decorate_publication_handoff({
            **row,
            "object_ids_json": json_text(row.get("object_ids") or {}),
            "public_config_json": json_text(row.get("public_config") or {}),
            "artifact_json": json_text(row.get("artifact") or {}),
        }),
        "event": event,
        "detail": publication_detail({"bundle_id": [bundle_id]}),
    }


def update_publication_snapshot(payload, *, snapshot_state, review_state, release_state=None, event_type):
    bundle_id, snapshot = latest_snapshot_for_update(payload)
    now = now_iso()
    updated = {
        **snapshot,
        "snapshot_state": snapshot_state,
        "review_state": review_state,
        "release_state": release_state or snapshot.get("release_state") or "unpublished",
        "actor": compact_text(payload.get("actor") or REVIEW_ACTOR, 200),
        "note": compact_text(payload.get("note"), 20000),
        "updated_at": now,
    }
    insert_publication_snapshot_row(updated)
    event = persist_review_event(build_review_event(event_type, {
        **payload,
        "source_evidence_id": project_source_evidence_id(updated.get("project") or ""),
        "project": updated.get("project") or "",
        "subject_type": "publication_snapshot",
        "subject_id": updated.get("snapshot_id") or "",
        "bundle_id": bundle_id,
        "snapshot_id": updated.get("snapshot_id") or "",
        "manifest_hash": updated.get("manifest_hash") or "",
        "source_anchor": {"kind": "publication_snapshot", "bundle_id": bundle_id, "snapshot_id": updated.get("snapshot_id"), "manifest_hash": updated.get("manifest_hash")},
    }))
    return {"snapshot": updated, "event": event, "detail": publication_detail({"bundle_id": [bundle_id]})}


def request_publication_review(payload):
    return update_publication_snapshot(payload, snapshot_state="in_review", review_state="snapshot_in_review", event_type="publication.snapshot.review_requested")


def approve_publication_snapshot(payload):
    return update_publication_snapshot(payload, snapshot_state="approved", review_state="approved", event_type="publication.snapshot.approved")


def request_publication_changes(payload):
    return update_publication_snapshot(payload, snapshot_state="changes_requested", review_state="changes_requested", event_type="publication.snapshot.changes_requested")


def publish_publication_snapshot(payload):
    bundle_id, snapshot = latest_snapshot_for_update(payload)
    if snapshot.get("review_state") != "approved":
        raise ResearchUiError(409, "Snapshot must be approved before publishing")
    result = update_publication_snapshot(payload, snapshot_state="published", review_state="approved", release_state="published", event_type="publication.snapshot.published")
    now = now_iso()
    release = {
        "release_id": compact_text(payload.get("release_id"), 200) or make_id("publication_release"),
        "snapshot_id": snapshot.get("snapshot_id") or "",
        "bundle_id": bundle_id,
        "project": snapshot.get("project") or "",
        "release_state": "published",
        "manifest_hash": snapshot.get("manifest_hash") or "",
        "supersedes_release_id": "",
        "actor": compact_text(payload.get("actor") or REVIEW_ACTOR, 200),
        "note": compact_text(payload.get("note"), 20000),
        "created_at": now,
        "updated_at": now,
    }
    ch_insert_json_each_row("publication_releases", [release])
    result["release"] = release
    return result


def supersede_publication_release(payload):
    bundle_id, snapshot = latest_snapshot_for_update(payload)
    latest_release = latest_publication_releases([bundle_id]).get(bundle_id)
    result = update_publication_snapshot(payload, snapshot_state="superseded", review_state=snapshot.get("review_state") or "approved", release_state="superseded", event_type="publication.release.superseded")
    now = now_iso()
    release = {
        "release_id": compact_text(payload.get("release_id"), 200) or (latest_release or {}).get("release_id") or make_id("publication_release"),
        "snapshot_id": snapshot.get("snapshot_id") or "",
        "bundle_id": bundle_id,
        "project": snapshot.get("project") or "",
        "release_state": "superseded",
        "manifest_hash": snapshot.get("manifest_hash") or "",
        "supersedes_release_id": (latest_release or {}).get("release_id") or "",
        "actor": compact_text(payload.get("actor") or REVIEW_ACTOR, 200),
        "note": compact_text(payload.get("note"), 20000),
        "created_at": (latest_release or {}).get("created_at") or now,
        "updated_at": now,
    }
    ch_insert_json_each_row("publication_releases", [release])
    result["release"] = release
    return result


def nested_value(data, *paths):
    for path in paths:
        current = data
        found = True
        for part in str(path).split("."):
            if isinstance(current, dict) and part in current:
                current = current.get(part)
            else:
                found = False
                break
        if found and current not in (None, ""):
            return current
    return ""


def normalize_rebrowser_launch_response(body):
    body = body if isinstance(body, dict) else {}
    session_id = compact_text(nested_value(
        body,
        "session_id",
        "rebrowser_session_id",
        "session.id",
        "session.session_id",
        "launch.session_id",
        "capture.rebrowser_session_id",
    ), 300)
    open_url = compact_text(nested_value(
        body,
        "open_url",
        "session_url",
        "rebrowser_url",
        "launch_url",
        "url",
        "session.url",
        "launch.url",
    ), 2000)
    capture_event_id = compact_text(nested_value(
        body,
        "capture_event_id",
        "capture.event_id",
        "capture.capture_event_id",
        "event.event_id",
    ), 300)
    capture_id = compact_text(nested_value(
        body,
        "capture_id",
        "capture.id",
        "capture.capture_id",
    ), 300)
    source_evidence_id = compact_text(nested_value(
        body,
        "source_evidence_id",
        "source_id",
        "capture.source_evidence_id",
        "capture.source_id",
    ), 1000)
    collector_run_id = compact_text(nested_value(
        body,
        "collector_run_id",
        "capture.collector_run_id",
        "run.collector_run_id",
    ), 300)
    status = compact_text(nested_value(
        body,
        "status",
        "capture_status",
        "session.status",
        "capture.status",
    ) or "launched", 80)
    committed = bool(capture_event_id or capture_id or status in ("committed", "complete", "captured", "published"))
    return {
        "session_id": session_id,
        "open_url": open_url,
        "capture_status": "committed" if committed else status,
        "capture_event_id": capture_event_id,
        "capture_id": capture_id,
        "source_evidence_id": source_evidence_id,
        "collector_run_id": collector_run_id,
        "committed": committed,
    }


def launch_rebrowser_capture(payload):
    project = compact_text(payload.get("project_id") or payload.get("project") or "", 300)
    seed_url = compact_text(payload.get("seed_url") or payload.get("url") or "", 2000)
    source_id = compact_text(payload.get("source_id") or payload.get("source_evidence_id") or "", 1000)
    if not seed_url and not source_id:
        raise ResearchUiError(400, "seed_url or source_id is required")
    source_evidence_id = source_id or project_source_evidence_id(project)
    launch_payload = {
        "project_id": project,
        "seed_url": seed_url,
        "source_id": source_id,
        "return_route": compact_text(payload.get("return_route") or "#inbox", 500),
        "requested_at": now_iso(),
        "actor": compact_text(payload.get("actor") or REVIEW_ACTOR, 200),
    }
    event = persist_review_event(build_review_event("rebrowser.capture.launch_requested", {
        **payload,
        "project": project,
        "source_evidence_id": source_evidence_id,
        "subject_type": "rebrowser_capture_intent",
        "subject_id": source_id or seed_url,
        "source_anchor": {"kind": "rebrowser_launch", "source_id": source_id, "seed_url": seed_url, "return_route": launch_payload["return_route"]},
    }))
    response_body = {}
    normalized = {}
    result_event = {}
    status = "queued"
    configured = bool(REBROWSER_LAUNCH_URL)
    if configured:
        request = urllib.request.Request(
            REBROWSER_LAUNCH_URL,
            data=json_bytes(launch_payload),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                text = response.read().decode("utf-8", errors="replace")
                try:
                    response_body = json.loads(text) if text else {}
                except Exception:
                    response_body = {"body": text[:2000]}
                status = "launched"
                normalized = normalize_rebrowser_launch_response(response_body)
                result_event_type = "rebrowser.capture.committed" if normalized.get("committed") else "rebrowser.capture.launch_result"
                result_event = persist_review_event(build_review_event(result_event_type, {
                    "project": project,
                    "source_evidence_id": source_evidence_id,
                    "subject_type": "rebrowser_capture_session",
                    "subject_id": normalized.get("session_id") or normalized.get("capture_id") or source_id or seed_url,
                    "seed_url": seed_url,
                    "source_id": source_id,
                    "returned_source_evidence_id": normalized.get("source_evidence_id") or "",
                    "return_route": launch_payload["return_route"],
                    "session": normalized,
                    "actor": launch_payload["actor"],
                    "source_anchor": {
                        "kind": "rebrowser_launch_result",
                        "source_id": source_id,
                        "source_evidence_id": source_evidence_id,
                        "returned_source_evidence_id": normalized.get("source_evidence_id") or "",
                        "seed_url": seed_url,
                        "return_route": launch_payload["return_route"],
                        "session_id": normalized.get("session_id") or "",
                        "capture_event_id": normalized.get("capture_event_id") or "",
                        "collector_run_id": normalized.get("collector_run_id") or "",
                    },
                }))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:1000]
            raise ResearchUiError(502, f"Rebrowser launch failed ({exc.code}): {detail}")
        except Exception as exc:
            raise ResearchUiError(502, f"Rebrowser launch failed: {exc}")
    return {
        "configured": configured,
        "status": status,
        "launch": response_body,
        "session": normalized,
        "open_url": normalized.get("open_url") if normalized else "",
        "event_id": event.get("event_id"),
        "event_ids": [item for item in (event.get("event_id"), result_event.get("event_id")) if item],
        "message": "Capture launch recorded" if not configured else ("Capture committed" if normalized.get("committed") else "Capture session opened"),
    }


def taxonomy_term_id(vocabulary, term):
    cleaned = "".join(char.lower() if char.isalnum() else "_" for char in str(term or "")).strip("_")
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return f"{vocabulary}.{cleaned or 'term'}"


def taxonomy_usage_count(rows, term):
    lowered = str(term or "").lower()
    for row in rows:
        if str(row.get("term") or "").lower() == lowered:
            return int(row.get("usage") or 0)
    return 0


def taxonomy_row(
    *,
    term,
    vocabulary,
    vocabulary_label,
    definition,
    path,
    review_state="accepted",
    row_kind="accepted_term",
    aliases=None,
    usage=None,
    owner="PR",
    priority="normal",
    updated_at=None,
    mapping_candidates=None,
    impacts=None,
    anchors=None,
    policy=None,
    stable_id=None,
):
    usage = usage or {}
    stable_id = stable_id or taxonomy_term_id(vocabulary, term)
    usage_total = sum(int(value or 0) for value in usage.values())
    lifecycle = {
        "accepted": "accepted",
        "proposed": "draft",
        "under_review": "under_review",
        "mapping_conflict": "under_review",
        "deprecated": "deprecated",
    }.get(review_state, review_state)
    return {
        "record_id": stable_id,
        "stable_id": stable_id,
        "term": term,
        "label": term,
        "definition": definition,
        "vocabulary": vocabulary,
        "vocabulary_label": vocabulary_label,
        "hierarchy_path": path,
        "review_state": review_state,
        "lifecycle_state": lifecycle,
        "row_kind": row_kind,
        "aliases": aliases or [],
        "usage": {
            "observations": int(usage.get("observations") or 0),
            "evidence": int(usage.get("evidence") or 0),
            "claims": int(usage.get("claims") or 0),
            "projects": int(usage.get("projects") or 0),
            "packages": int(usage.get("packages") or 0),
        },
        "usage_total": usage_total,
        "owner": owner,
        "priority": priority,
        "updated_at": updated_at or now_iso(),
        "mapping_candidates": mapping_candidates or [],
        "publication_impacts": impacts or [],
        "anchors": anchors or [],
        "policy": policy or {},
        "history": [
            {"event_type": "taxonomy.term.loaded", "actor": "research-ui", "created_at": updated_at or now_iso(), "detail": "Rendered from controlled vocabulary read model."},
        ],
        "permitted_actions": ["promote", "map", "merge", "add_alias", "deprecate", "assign_review", "export", "open_usage"],
    }


def taxonomy_preview(row):
    if not row:
        return {}
    usage = row.get("usage") or {}
    return {
        "row": row,
        "usage_stats": [
            {"label": "Observations", "value": usage.get("observations", 0), "hint": "Raw and model-derived labels"},
            {"label": "Evidence", "value": usage.get("evidence", 0), "hint": "Reviewed evidence anchors"},
            {"label": "Claims", "value": usage.get("claims", 0), "hint": "Structured claim records"},
            {"label": "Packages", "value": usage.get("packages", 0), "hint": "Publication impact"},
        ],
        "mapping_candidates": row.get("mapping_candidates") or [],
        "publication_impacts": row.get("publication_impacts") or [],
        "anchors": row.get("anchors") or [],
        "policy": row.get("policy") or {},
        "history": row.get("history") or [],
    }


def taxonomy_row_matches(row, q, queue, vocabulary, review_state):
    if queue and queue != "all":
        if queue == "proposed_terms" and row.get("review_state") != "proposed":
            return False
        if queue == "mapping_conflicts" and row.get("review_state") != "mapping_conflict":
            return False
        if queue == "awaiting_review" and row.get("review_state") not in ("under_review", "mapping_conflict", "proposed"):
            return False
        if queue == "publication_impact" and not row.get("publication_impacts"):
            return False
        if queue == "deprecated" and row.get("review_state") != "deprecated":
            return False
        if queue == "accepted_terms" and row.get("review_state") != "accepted":
            return False
    if vocabulary and row.get("vocabulary") != vocabulary:
        return False
    if review_state and row.get("review_state") != review_state:
        return False
    if q:
        haystack = " ".join(
            str(value or "")
            for value in (
                row.get("term"),
                row.get("stable_id"),
                row.get("definition"),
                row.get("vocabulary_label"),
                row.get("hierarchy_path"),
                " ".join(row.get("aliases") or []),
            )
        ).lower()
        if q.lower() not in haystack:
            return False
    return True


def taxonomy_read_model(params):
    limit = sql_int(params.get("limit", ["120"])[0], 120)
    q = (params.get("q", [""])[0] or "").strip()
    queue = (params.get("queue", ["proposed_terms"])[0] or "proposed_terms").strip()
    vocabulary = (params.get("vocabulary", [""])[0] or "").strip()
    review_state = (params.get("review_state", [""])[0] or "").strip()
    mode = (params.get("mode", ["hybrid"])[0] or "hybrid").strip()
    project = (params.get("project", [""])[0] or "").strip()
    inspect = (params.get("inspect", [""])[0] or "").strip()
    if inspect.startswith("taxonomy:"):
        inspect = inspect.removeprefix("taxonomy:")

    source_kinds = ch_data(
        """
        SELECT source_kind AS term, count() AS usage
        FROM evidence_events
        GROUP BY source_kind
        ORDER BY usage DESC
        """,
        fallback=[],
    )
    entity_types = ch_data(
        """
        SELECT entity_type AS term, count() AS usage
        FROM entity_links FINAL
        GROUP BY entity_type
        ORDER BY usage DESC
        """,
        fallback=[],
    )
    claim_types = ch_data(
        """
        SELECT claim_type AS term, count() AS usage
        FROM claim_records FINAL
        GROUP BY claim_type
        ORDER BY usage DESC
        """,
        fallback=[],
    )
    evidence_types = ch_data(
        """
        SELECT selection_kind AS term, count() AS usage
        FROM evidence_selections FINAL
        GROUP BY selection_kind
        ORDER BY usage DESC
        """,
        fallback=[],
    )

    core = {
        "entity_types": ["account", "person", "lab", "company", "model", "repository", "paper", "benchmark", "hardware", "tool", "topic"],
        "claim_properties": ["release_claim", "benchmark_result", "capability", "license", "architecture", "hardware_cost", "workflow", "context_window", "evaluation_harness"],
        "evidence_types": ["source_quote", "table_cell", "image_region", "video_timecode", "repo_line", "manual_note"],
        "review_reason_codes": ["needs_source", "needs_entity_resolution", "contradiction", "stale", "unsupported", "publication_blocker"],
        "source_categories": ["x_post", "web_page", "search_result", "google_search_page", "media", "user_input"],
    }

    rows = [
        taxonomy_row(
            term="long-context capability",
            vocabulary="model_facets",
            vocabulary_label="Model facets",
            definition="Machine-suggested label for sources describing unusually large context windows; may be a qualitative topic rather than a measurable property.",
            path="Model facets / Capabilities / Context and memory",
            review_state="proposed",
            row_kind="illustrative",
            aliases=["long context", "extended context", "large-context support", "1M-token capability"],
            usage={},
            owner=REVIEW_ACTOR,
            priority="normal",
            stable_id="TAX-PROP-4092",
            policy={"publication_safe": False, "required_qualifier": "model/provider version", "decision_rule": "Map to context_window if numeric tokens are present; otherwise keep as topic/capability."},
        ),
        taxonomy_row(
            term="frontier model",
            vocabulary="topics",
            vocabulary_label="Topic hierarchy",
            definition="Ambiguous industry term used for capability-leading models, closed flagship models, and models above a compute or benchmark threshold.",
            path="Topics / Model positioning",
            review_state="proposed",
            row_kind="illustrative",
            aliases=["frontier AI model", "state-of-the-art model", "flagship model"],
            usage={},
            owner=REVIEW_ACTOR,
            priority="normal",
            stable_id="topic.model.frontier",
        ),
        taxonomy_row(
            term="vendor-reported",
            vocabulary="benchmark_facets",
            vocabulary_label="Benchmark facets",
            definition="Benchmark result reported by the vendor or model author without independent reproduction by this research workspace.",
            path="Benchmark facets / Result provenance",
            review_state="proposed",
            row_kind="illustrative",
            aliases=["vendor reported", "author reported"],
            usage={},
            stable_id="benchmark.result.vendor_reported",
            policy={"replacement": "benchmark.result.author_reported", "publication_safe": False},
        ),
    ]

    for term in core["entity_types"]:
        rows.append(taxonomy_row(
            term=term,
            vocabulary="entity_types",
            vocabulary_label="Entity categories",
            definition=f"Canonical entity type for {title_case_label(term)} objects in captured evidence.",
            path="Entity categories",
            usage={"observations": taxonomy_usage_count(entity_types, term), "evidence": taxonomy_usage_count(entity_types, term)},
        ))
    for term in core["claim_properties"]:
        rows.append(taxonomy_row(
            term=term,
            vocabulary="claim_properties",
            vocabulary_label="Claim properties",
            definition=f"Structured claim property used when normalizing {title_case_label(term)} assertions.",
            path="Claim properties",
            aliases=[title_case_label(term), term.replace("_", " ")],
            usage={"claims": taxonomy_usage_count(claim_types, term), "evidence": max(0, taxonomy_usage_count(claim_types, term) * 2)},
        ))
    for term in core["evidence_types"]:
        rows.append(taxonomy_row(
            term=term,
            vocabulary="evidence_types",
            vocabulary_label="Evidence types",
            definition=f"Evidence anchor type for {title_case_label(term)} selections.",
            path="Evidence types",
            usage={"evidence": taxonomy_usage_count(evidence_types, term), "observations": taxonomy_usage_count(evidence_types, term)},
        ))
    for term in core["review_reason_codes"]:
        rows.append(taxonomy_row(
            term=term,
            vocabulary="review_reason_codes",
            vocabulary_label="Review reason codes",
            definition=f"Human review reason for {title_case_label(term)} work items.",
            path="Review reason codes",
            usage={"observations": 0},
        ))
    for item in source_kinds:
        term = item.get("term") or "unknown"
        rows.append(taxonomy_row(
            term=term,
            vocabulary="source_categories",
            vocabulary_label="Source categories",
            definition=f"Captured source category observed in the evidence event stream: {term}.",
            path="Source categories",
            review_state="accepted" if term in core["source_categories"] else "proposed",
            row_kind="observed_source_category",
            usage={"observations": int(item.get("usage") or 0), "evidence": int(item.get("usage") or 0)},
            stable_id=taxonomy_term_id("source_categories", term),
        ))

    priority_rank = {"high": 0, "blocking": 0, "normal": 1, "low": 2}
    rows.sort(key=lambda row: (
        0 if row.get("review_state") == "proposed" else 1 if row.get("review_state") == "mapping_conflict" else 2,
        priority_rank.get(row.get("priority") or "normal", 1),
        -int(row.get("usage_total") or 0),
        str(row.get("term") or ""),
    ))
    filtered = [row for row in rows if taxonomy_row_matches(row, q, queue, vocabulary, review_state)]
    visible = filtered[:limit]
    selected = next((row for row in visible if row.get("stable_id") == inspect or row.get("record_id") == inspect), None) or (visible[0] if visible else None)

    vocabularies = [
        {"id": "topics", "label": "Topic hierarchy", "count": sum(1 for row in rows if row.get("vocabulary") == "topics")},
        {"id": "entity_types", "label": "Entity categories", "count": sum(1 for row in rows if row.get("vocabulary") == "entity_types")},
        {"id": "source_categories", "label": "Source categories", "count": sum(1 for row in rows if row.get("vocabulary") == "source_categories")},
        {"id": "evidence_types", "label": "Evidence types", "count": sum(1 for row in rows if row.get("vocabulary") == "evidence_types")},
        {"id": "claim_properties", "label": "Claim properties", "count": sum(1 for row in rows if row.get("vocabulary") == "claim_properties")},
        {"id": "benchmark_facets", "label": "Benchmark facets", "count": sum(1 for row in rows if row.get("vocabulary") == "benchmark_facets")},
        {"id": "model_facets", "label": "Model facets", "count": sum(1 for row in rows if row.get("vocabulary") == "model_facets")},
        {"id": "review_reason_codes", "label": "Review reason codes", "count": sum(1 for row in rows if row.get("vocabulary") == "review_reason_codes")},
    ]
    queues = [
        {"id": "all", "label": "All terms", "count": len(rows)},
        {"id": "proposed_terms", "label": "Proposed terms", "count": sum(1 for row in rows if row.get("review_state") == "proposed")},
        {"id": "mapping_conflicts", "label": "Mapping conflicts", "count": sum(1 for row in rows if row.get("review_state") == "mapping_conflict")},
        {"id": "awaiting_review", "label": "Awaiting review", "count": sum(1 for row in rows if row.get("review_state") in ("under_review", "mapping_conflict", "proposed"))},
        {"id": "publication_impact", "label": "Publication impact", "count": sum(1 for row in rows if row.get("publication_impacts"))},
        {"id": "deprecated", "label": "Deprecated", "count": sum(1 for row in rows if row.get("review_state") == "deprecated")},
        {"id": "accepted_terms", "label": "Accepted terms", "count": sum(1 for row in rows if row.get("review_state") == "accepted")},
    ]
    return {
        "core": core,
        "usage": {"source_kinds": source_kinds, "entity_types": entity_types, "claim_types": claim_types, "evidence_types": evidence_types},
        "scope": {"project": project or "all", "actor": REVIEW_ACTOR, "surface": "taxonomy"},
        "query": {"q": q, "queue": queue, "vocabulary": vocabulary, "review_state": review_state, "mode": mode, "limit": limit},
        "summary": {
            "terms": len(rows),
            "visible": len(visible),
            "accepted": sum(1 for row in rows if row.get("review_state") == "accepted"),
            "proposals": sum(1 for row in rows if row.get("review_state") == "proposed"),
            "conflicts": sum(1 for row in rows if row.get("review_state") == "mapping_conflict"),
            "deprecated": sum(1 for row in rows if row.get("review_state") == "deprecated"),
            "publication_impacts": sum(1 for row in rows if row.get("publication_impacts")),
        },
        "queues": queues,
        "vocabularies": vocabularies,
        "hierarchy": [
            {"id": "model_facets", "label": "Model facets", "depth": 0, "count": 2},
            {"id": "model_facets.capabilities", "label": "Capabilities", "depth": 1, "count": 2},
            {"id": "model_facets.context_memory", "label": "Context and memory", "depth": 2, "count": 0},
            {"id": "claim_properties.context_window", "label": "Context window", "depth": 3, "count": taxonomy_usage_count(claim_types, "context_window"), "leaf": True},
            {"id": "TAX-PROP-4092", "label": "Long-context capability", "depth": 3, "count": 0, "leaf": True},
            {"id": "benchmark_facets", "label": "Benchmark facets", "depth": 0, "count": 0},
            {"id": "entity_types", "label": "Entity categories", "depth": 0, "count": len(core["entity_types"])},
        ],
        "facets": {
            "vocabularies": vocabularies,
            "review_states": evidence_facet_counts(rows, "review_state"),
            "row_kinds": evidence_facet_counts(rows, "row_kind"),
        },
        "results": cursor_page(visible, len(filtered), limit),
        "rows": visible,
        "preview": taxonomy_preview(selected),
        "selection": {"selected_record_ids": [], "compatible_actions": ["promote", "map", "merge", "add_alias", "deprecate", "assign_review", "export"]},
        # No taxonomy-version table exists yet; report honestly that there is
        # no published or draft release rather than fabricating version numbers.
        "active_release": {"id": "", "label": "No active release", "state": "none", "published_at": ""},
        "draft_release": {"id": "", "label": "No draft", "state": "none", "changed_terms": 0},
        "permissions": ["review", "promote", "map", "merge", "deprecate", "export"],
        "generated_at": now_iso(),
        "stale": False,
        "version": "taxonomy-page.v2",
    }


def percent(part, total):
    try:
        part = float(part or 0)
        total = float(total or 0)
    except (TypeError, ValueError):
        return 0
    if total <= 0:
        return 0
    return max(0, min(100, round((part / total) * 100)))


def home_summary(params=None):
    params = params or {}
    requested_project = (params.get("project", [""])[0] or "").strip()
    totals = ch_data(
        """
        SELECT
          count() AS evidence_rows,
          uniqExact(evidence_id) AS unique_evidence,
          countIf(source_kind IN ('x_post', 'x_account', 'x_page')) AS x_rows,
          countIf(source_kind IN ('web_page', 'search_result', 'google_search_page')) AS web_rows,
          countIf(source_kind = 'user_input') AS manual_rows,
          countIf(source_kind = 'media') AS media_rows,
          countIf(has_ocr = 1) AS ocr_rows,
          countIf(length(text) >= 120) AS extracted_rows,
          max(ingested_at) AS last_ingested_at
        FROM evidence_events
        """,
        fallback=[{}],
    )[0]
    review_counts = ch_data(
        """
        SELECT
          (SELECT count() FROM evidence_selections FINAL) AS selections,
          (SELECT count() FROM review_annotations FINAL) AS annotations,
          (SELECT count() FROM proposed_facts FINAL) AS proposed_facts,
          (SELECT count() FROM normalized_corrections FINAL) AS normalized_corrections,
          (SELECT count() FROM entity_links FINAL) AS entity_links,
          (SELECT count() FROM claim_records FINAL) AS claim_records,
          (SELECT count() FROM research_review_events) AS review_events
        """,
        fallback=[{}],
    )[0]
    recent = ch_data(
        """
        SELECT
          evidence_id,
          argMax(source_kind, ingested_at) AS source_kind,
          argMax(source_project, ingested_at) AS source_project,
          argMax(canonical_url, ingested_at) AS canonical_url,
          argMax(author_handle, ingested_at) AS author_handle,
          argMax(domain, ingested_at) AS domain,
          argMax(title, ingested_at) AS title,
          substring(argMax(text, ingested_at), 1, 240) AS snippet,
          length(argMax(text, ingested_at)) AS text_chars,
          max(has_media) AS has_media,
          max(has_ocr) AS has_ocr,
          count() AS observations,
          max(ingested_at) AS last_ingested_at
        FROM evidence_events
        GROUP BY evidence_id
        ORDER BY
          (has_media + has_ocr + least(observations, 3)) DESC,
          last_ingested_at DESC
        LIMIT 12
        """,
        fallback=[],
    )
    for row in recent:
        row["source_label"] = source_kind_label(row.get("source_kind"))
        row["review_hint"] = review_hint(row)

    source_counts = ch_data(
        """
        SELECT source_kind, uniqExact(evidence_id) AS sources
        FROM evidence_events
        GROUP BY source_kind
        """,
        fallback=[],
    )
    source_map = {row.get("source_kind"): int(row.get("sources") or 0) for row in source_counts}
    review_total = sum(int(review_counts.get(key) or 0) for key in ("selections", "annotations", "proposed_facts", "normalized_corrections", "entity_links", "claim_records"))
    unique = int(totals.get("unique_evidence") or 0)
    extracted = int(totals.get("extracted_rows") or 0)
    ocr_rows = int(totals.get("ocr_rows") or 0)
    media_rows = int(totals.get("media_rows") or 0)
    capture_score = percent(extracted, int(totals.get("evidence_rows") or 0))
    review_score = percent(review_total, max(unique, 1))
    coverage_rows = [
        {"topic": "Release claims", "x": source_map.get("x_post", 0), "web": source_map.get("web_page", 0), "papers": source_map.get("user_input", 0), "media": media_rows},
        {"topic": "Benchmarks", "x": source_map.get("x_post", 0), "web": source_map.get("search_result", 0) + source_map.get("web_page", 0), "papers": source_map.get("user_input", 0), "media": ocr_rows},
        {"topic": "Licensing", "x": source_map.get("x_account", 0), "web": source_map.get("web_page", 0), "papers": source_map.get("user_input", 0), "media": 0},
        {"topic": "Hardware & cost", "x": source_map.get("x_post", 0), "web": source_map.get("web_page", 0), "papers": source_map.get("user_input", 0), "media": media_rows},
    ]
    gaps = sum(1 for row in coverage_rows for key in ("x", "web", "papers", "media") if int(row.get(key) or 0) == 0)
    proposed_facts = int(review_counts.get("proposed_facts") or 0)
    normalized_corrections = int(review_counts.get("normalized_corrections") or 0)
    claim_records = int(review_counts.get("claim_records") or 0)
    blockers = max(0, gaps // 3)
    queue = [
        {"label": "New captures", "count": unique, "hint": "triage evidence"},
        {"label": "Entity matches", "count": int(review_counts.get("entity_links") or 0), "hint": "resolve names"},
        {"label": "Contradictions", "count": claim_records, "hint": "claim checks"},
        {"label": "Assigned reviews", "count": int(review_counts.get("review_events") or 0), "hint": "decision work"},
    ]
    # Resolve the active project from real data: the requested project if the
    # caller named one, else the project with the most recent activity. Source
    # the brief fields (name, question, scope, open questions) from the real,
    # file-backed project brief instead of hardcoding them.
    project_data = project_rows({"project": [requested_project]} if requested_project else {})
    project_list = project_data.get("rows", [])
    active_row = None
    if requested_project:
        active_row = next((r for r in project_list if (r.get("project_id") or "") == requested_project), None)
    if active_row is None:
        active_row = project_list[0] if project_list else None
    active_brief = (active_row or {}).get("brief") or {}
    project_id = (active_row or {}).get("project_id") or ""
    project_name = (active_row or {}).get("name") or "(no project)"
    project_description = (active_row or {}).get("scope") or active_brief.get("decision_supported") or ""
    project_completion = int((active_row or {}).get("completion_percent") or 0)
    project_updated = (active_row or {}).get("last_activity") or totals.get("last_ingested_at") or ""
    research_question = active_brief.get("research_question") or "Collect and validate source-linked evidence"
    scope_obj = active_brief.get("scope") or {}
    scope_text = "; ".join(part for part in (
        scope_obj.get("time_window"),
        scope_obj.get("geography"),
        scope_obj.get("population"),
    ) if part) or "Captured sources, normalized artifacts, and review queues."
    open_questions = [
        {
            "text": item.get("text") or "",
            "owner": item.get("owner") or "unassigned",
            "blocked": item.get("status") in ("blocked", "stuck"),
        }
        for item in (active_brief.get("open_questions") or [])
    ]
    # Contradiction candidates: real claim rows grouped by subject that carry
    # more than one distinct value. Returns [] honestly when there are none
    # (today: the corpus has a single smoke claim), instead of a fixed [] that
    # would hide the contract gap.
    contradictions = []
    if claim_records:
        contradictions = ch_data(
            f"""
            SELECT
              subject AS subject,
              groupUniqArray(value) AS values,
              count() AS assertion_count
            FROM
            (
              SELECT
                claim_text,
                multiIf(positionCaseInsensitive(claim_text, ' is ') > 0, substring(claim_text, 1, positionCaseInsensitive(claim_text, ' is ') - 1),
                        positionCaseInsensitive(claim_text, ':') > 0, substring(claim_text, 1, positionCaseInsensitive(claim_text, ':') - 1),
                        '') AS subject,
                claim_text AS value
              FROM claim_records FINAL
              WHERE subject != ''
            )
            GROUP BY subject
            HAVING length(values) > 1
            ORDER BY assertion_count DESC
            LIMIT 5
            """,
            fallback=[],
        )
    return {
        "active_project": {
            "project_id": project_id,
            "name": project_name,
            "description": project_description,
            "completion_percent": project_completion,
            "updated_at": project_updated,
        },
        "brief": {
            "question": research_question,
            "scope": scope_text,
            "stats": [
                {"label": "sources", "value": unique, "route": "library"},
                {"label": "review records", "value": review_total, "route": "reviews"},
                {"label": "proposed facts", "value": proposed_facts, "route": "evidence"},
                {"label": "claim stubs", "value": claim_records, "route": "claims"},
            ],
            "workflow": [
                {"label": "Capture", "percent": capture_score, "route": "library"},
                {"label": "Triage", "percent": percent(unique, max(unique + gaps, 1)), "route": "inbox"},
                {"label": "Claims", "percent": percent(claim_records, max(claim_records + blockers + 1, 1)), "route": "claims"},
                {"label": "Review", "percent": review_score, "route": "reviews"},
            ],
        },
        "queue": queue,
        "recent_evidence": recent,
        "contradictions": contradictions,
        "coverage": {"rows": coverage_rows, "gaps": gaps},
        "publication": {
            "checks_passed": max(0, review_total - blockers),
            "checks_total": max(review_total + gaps, 1),
            "blockers": blockers,
        },
        "open_questions": open_questions,
        "generated_at": now_iso(),
        "stale": False,
        "permissions": ["navigate", "capture", "review"],
        "version": "home.v1",
    }


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
    normalized_corrections = ch_data(
        f"""
        SELECT
          correction_id, source_evidence_id, document_id, block_id, correction_kind,
          original_text, corrected_text, source_anchor_json, status, note,
          actor, created_at, updated_at
        FROM normalized_corrections FINAL
        WHERE source_evidence_id = {quoted}
        ORDER BY updated_at DESC, created_at DESC
        LIMIT 200
        """,
        fallback=[],
    )
    entity_links = ch_data(
        f"""
        SELECT
          entity_link_id, source_evidence_id, evidence_selection_id, mention_text,
          entity_type, canonical_entity_id, canonical_name, source_anchor_json,
          status, note, actor, created_at, updated_at
        FROM entity_links FINAL
        WHERE source_evidence_id = {quoted}
        ORDER BY updated_at DESC, created_at DESC
        LIMIT 200
        """,
        fallback=[],
    )
    claim_records = ch_data(
        f"""
        SELECT
          claim_id, source_evidence_id, evidence_selection_id, claim_text,
          claim_type, evidence_relation, qualifier_json, source_anchor_json,
          status, note, actor, created_at, updated_at
        FROM claim_records FINAL
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
        "normalized_corrections": normalized_corrections,
        "entity_links": entity_links,
        "claim_records": claim_records,
        "events": events,
        "counts": {
            "selections": len(selections),
            "annotations": len(annotations),
            "proposed_facts": len(proposed_facts),
            "normalized_corrections": len(normalized_corrections),
            "entity_links": len(entity_links),
            "claim_records": len(claim_records),
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
    subject_id = compact_text(
        payload.get("subject_id")
        or payload.get("selection_id")
        or payload.get("annotation_id")
        or payload.get("proposed_fact_id")
        or payload.get("entity_link_id")
        or payload.get("claim_id"),
        300,
    )
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
        "status": validate_status("evidence_selection", compact_text(payload.get("status") or "selected", 80), actor=compact_text(payload.get("actor") or REVIEW_ACTOR, 200), is_create=True),
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
        "status": validate_status("annotation", compact_text(payload.get("status") or "open", 80), actor=compact_text(payload.get("actor") or REVIEW_ACTOR, 200), is_create=True),
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
        "status": validate_status("proposed_fact", compact_text(payload.get("status") or "proposed", 80), actor=compact_text(payload.get("actor") or REVIEW_ACTOR, 200), is_create=True),
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


def create_normalized_correction(payload):
    correction_id = compact_text(payload.get("correction_id"), 300) or make_id("normalized_correction")
    original_text = compact_text(payload.get("original_text") or payload.get("quote"), 50000)
    corrected_text = compact_text(payload.get("corrected_text"), 50000)
    if not original_text:
        raise ResearchUiError(400, "original_text is required")
    if not corrected_text:
        raise ResearchUiError(400, "corrected_text is required")
    now = now_iso()
    normalized = {
        **payload,
        "correction_id": correction_id,
        "subject_type": "normalized_correction",
        "subject_id": correction_id,
        "correction_kind": compact_text(payload.get("correction_kind") or "normalized_text", 120),
        "original_text": original_text,
        "corrected_text": corrected_text,
        "status": validate_status("normalized_correction", compact_text(payload.get("status") or "proposed", 80), actor=compact_text(payload.get("actor") or REVIEW_ACTOR, 200), is_create=True),
        "note": compact_text(payload.get("note"), 20000),
        "created_at": payload.get("created_at") or now,
        "updated_at": now,
    }
    event = persist_review_event(build_review_event("normalized_correction.created", normalized))
    ch_insert_json_each_row("normalized_corrections", [{
        "correction_id": correction_id,
        "source_evidence_id": normalized["source_evidence_id"],
        "document_id": compact_text(normalized.get("document_id"), 500),
        "block_id": compact_text(normalized.get("block_id"), 500),
        "correction_kind": normalized["correction_kind"],
        "original_text": normalized["original_text"],
        "corrected_text": normalized["corrected_text"],
        "source_anchor_json": json_text(normalized.get("source_anchor")),
        "status": normalized["status"],
        "note": normalized["note"],
        "actor": compact_text(normalized.get("actor") or REVIEW_ACTOR, 200),
        "created_at": normalized["created_at"],
        "updated_at": normalized["updated_at"],
    }])
    return {"event": event, "normalized_correction": normalized}


def create_entity_link(payload):
    entity_link_id = compact_text(payload.get("entity_link_id"), 300) or make_id("entity_link")
    mention_text = compact_text(payload.get("mention_text") or payload.get("quote"), 20000)
    canonical_name = compact_text(payload.get("canonical_name"), 500)
    canonical_entity_id = compact_text(payload.get("canonical_entity_id"), 500)
    if not mention_text and not canonical_name and not canonical_entity_id:
        raise ResearchUiError(400, "mention_text, canonical_name, or canonical_entity_id is required")
    now = now_iso()
    normalized = {
        **payload,
        "entity_link_id": entity_link_id,
        "subject_type": "entity_link",
        "subject_id": entity_link_id,
        "mention_text": mention_text,
        "entity_type": compact_text(payload.get("entity_type") or "topic", 120),
        "canonical_entity_id": canonical_entity_id,
        "canonical_name": canonical_name,
        "status": validate_status("entity_link", compact_text(payload.get("status") or "proposed", 80), actor=compact_text(payload.get("actor") or REVIEW_ACTOR, 200), is_create=True),
        "note": compact_text(payload.get("note"), 20000),
        "created_at": payload.get("created_at") or now,
        "updated_at": now,
    }
    event = persist_review_event(build_review_event("entity_link.created", normalized))
    ch_insert_json_each_row("entity_links", [{
        "entity_link_id": entity_link_id,
        "source_evidence_id": normalized["source_evidence_id"],
        "evidence_selection_id": compact_text(normalized.get("evidence_selection_id"), 300),
        "mention_text": normalized["mention_text"],
        "entity_type": normalized["entity_type"],
        "canonical_entity_id": normalized["canonical_entity_id"],
        "canonical_name": normalized["canonical_name"],
        "source_anchor_json": json_text(normalized.get("source_anchor")),
        "status": normalized["status"],
        "note": normalized["note"],
        "actor": compact_text(normalized.get("actor") or REVIEW_ACTOR, 200),
        "created_at": normalized["created_at"],
        "updated_at": normalized["updated_at"],
    }])
    return {"event": event, "entity_link": normalized}


def create_claim_record(payload):
    claim_id = compact_text(payload.get("claim_id"), 300) or make_id("claim")
    claim_text = compact_text(payload.get("claim_text") or payload.get("quote"), 50000)
    if not claim_text:
        raise ResearchUiError(400, "claim_text is required")
    now = now_iso()
    normalized = {
        **payload,
        "claim_id": claim_id,
        "subject_type": "claim_stub",
        "subject_id": claim_id,
        "claim_text": claim_text,
        "claim_type": compact_text(payload.get("claim_type") or "general", 120),
        "evidence_relation": compact_text(payload.get("evidence_relation") or "supports", 80),
        "qualifier": payload.get("qualifier") if isinstance(payload.get("qualifier"), dict) else {},
        "status": validate_status("claim_stub", compact_text(payload.get("status") or "draft", 80), actor=compact_text(payload.get("actor") or REVIEW_ACTOR, 200), is_create=True),
        "note": compact_text(payload.get("note"), 20000),
        "created_at": payload.get("created_at") or now,
        "updated_at": now,
    }
    event = persist_review_event(build_review_event("claim_stub.created", normalized))
    ch_insert_json_each_row("claim_records", [{
        "claim_id": claim_id,
        "source_evidence_id": normalized["source_evidence_id"],
        "evidence_selection_id": compact_text(normalized.get("evidence_selection_id"), 300),
        "claim_text": normalized["claim_text"],
        "claim_type": normalized["claim_type"],
        "evidence_relation": normalized["evidence_relation"],
        "qualifier_json": json_text(normalized["qualifier"]),
        "source_anchor_json": json_text(normalized.get("source_anchor")),
        "status": normalized["status"],
        "note": normalized["note"],
        "actor": compact_text(normalized.get("actor") or REVIEW_ACTOR, 200),
        "created_at": normalized["created_at"],
        "updated_at": normalized["updated_at"],
    }])
    return {"event": event, "claim_record": normalized}


# Actor kind follows the spec §28 `actor: "human" | "model_run" | "unknown"`
# discriminated union. We classify by string prefix so the existing string column
# carries provenance without a schema change:
#   "human:..."  -> human   |  "model:..." / "worker:..."  -> model_run  |  else unknown
MODEL_ACTOR_PREFIXES = ("model:", "worker:")

# Object-lifecycle terminals: the human-curated end-states of the epistemic layer.
# Per spec §14/§18/§25 and ARCHITECTURE.md, these are append-only — once an object
# reaches one, it cannot be re-transitioned by a state mutation; reopening requires
# a NEW review task/snapshot rather than rewriting history. Review-task decision
# states (approved/changes_requested/deferred/assigned/open/...) are NOT terminals
# — they are inherently revisable queue states.
TERMINAL_STATUSES = {"accepted", "rejected", "superseded", "published"}

# Human-curated terminals a model/worker actor may NOT create an observation in.
# Spec §1: "a model observation cannot directly set a claim to accepted or canonical";
# SOURCE_WORKBENCH impl plan: workers "must not bypass human review". Machine
# observations must be born proposed/draft/open and reach a terminal only via a
# human review event on /api/review-state.
HUMAN_ONLY_STATUSES = {"accepted", "canonical", "matched", "published", "merged", "created"}

# Observation-type objects: machine output that must pass human review before it
# can become a curated assertion. (annotations are human-authored, so excluded.)
MACHINE_OBSERVATION_TYPES = {"proposed_fact", "entity_link", "normalized_correction", "claim_stub"}


def actor_kind(actor):
    """Classify an actor string into the spec §28 union: human | model_run | unknown."""
    if not actor:
        return "unknown"
    value = str(actor).strip().lower()
    if value.startswith("human:"):
        return "human"
    if value.startswith(MODEL_ACTOR_PREFIXES):
        return "model_run"
    # Unprefixed actors (incl. the default REVIEW_ACTOR "web-osint-user") are
    # treated as human — the historical convention before provenance prefixes.
    return "human"


def validate_status(subject_type, status, *, actor=None, is_create=False):
    """Enforce the per-type status allow-list, the terminal-state guard
    (update path), and the machine-origin guard (create path).

    Raises ResearchUiError on any violation. Returns the validated status.
    """
    config = REVIEW_OBJECT_CONFIGS.get(subject_type)
    if not config:
        raise ResearchUiError(400, f"Unsupported subject_type: {subject_type}")
    allowed = config.get("statuses")
    if allowed and status not in allowed:
        raise ResearchUiError(
            400,
            f"status {status!r} is not valid for {subject_type}; allowed: {sorted(allowed)}",
        )
    if is_create and subject_type in MACHINE_OBSERVATION_TYPES:
        # spec §1: a model observation cannot be born in a human-curated terminal.
        if status in HUMAN_ONLY_STATUSES and actor_kind(actor) == "model_run":
            raise ResearchUiError(
                403,
                f"a model observation cannot be created as {status!r}; model output "
                f"must be born proposed/draft/open and reach {status!r} only via a "
                f"human review event (spec §1 epistemic layers)",
            )
    return status


def assert_not_terminal_transition(subject_type, previous_status, next_status):
    """Append-only history guard (update path). A terminal status cannot be left
    by a state mutation; reopening requires a new task/snapshot rather than
    rewriting history (spec §14/§18/§25)."""
    if previous_status in TERMINAL_STATUSES and next_status != previous_status:
        raise ResearchUiError(
            409,
            f"{subject_type} is in terminal state {previous_status!r} and cannot be "
            f"re-transitioned to {next_status!r}; reopen it via a new review task "
            f"or snapshot (history is append-only)",
        )


REVIEW_OBJECT_CONFIGS = {
    "evidence_selection": {
        "table": "evidence_selections",
        "id_column": "selection_id",
        "columns": ["selection_id", "source_evidence_id", "document_id", "block_id", "selection_kind", "quote", "context_before", "context_after", "source_anchor_json", "note", "status", "actor", "created_at", "updated_at"],
        "statuses": {"selected", "accepted", "rejected", "needs_more_evidence", "superseded", "open", "review_linked", "archived", "approved", "changes_requested", "deferred", "assigned"},
    },
    "annotation": {
        "table": "review_annotations",
        "id_column": "annotation_id",
        "columns": ["annotation_id", "source_evidence_id", "evidence_selection_id", "annotation_type", "body", "status", "source_anchor_json", "actor", "created_at", "updated_at"],
        "statuses": {"open", "accepted", "resolved", "rejected", "superseded", "approved", "changes_requested", "deferred", "assigned"},
    },
    "proposed_fact": {
        "table": "proposed_facts",
        "id_column": "proposed_fact_id",
        "columns": ["proposed_fact_id", "source_evidence_id", "evidence_selection_id", "fact_type", "field_path", "raw_value", "normalized_value", "unit", "entities_json", "evidence_quote", "source_anchor_json", "status", "note", "actor", "created_at", "updated_at"],
        "statuses": {"proposed", "accepted", "rejected", "needs_more_evidence", "superseded", "open", "approved", "changes_requested", "deferred", "assigned", "under_review"},
    },
    "normalized_correction": {
        "table": "normalized_corrections",
        "id_column": "correction_id",
        "columns": ["correction_id", "source_evidence_id", "document_id", "block_id", "correction_kind", "original_text", "corrected_text", "source_anchor_json", "status", "note", "actor", "created_at", "updated_at"],
        "statuses": {"proposed", "accepted", "rejected", "needs_more_evidence", "superseded", "open", "approved", "changes_requested", "deferred", "assigned", "under_review"},
    },
    "entity_link": {
        "table": "entity_links",
        "id_column": "entity_link_id",
        "columns": ["entity_link_id", "source_evidence_id", "evidence_selection_id", "mention_text", "entity_type", "canonical_entity_id", "canonical_name", "source_anchor_json", "status", "note", "actor", "created_at", "updated_at"],
        "statuses": {"proposed", "matched", "created", "rejected", "merged", "canonical", "merge_review", "superseded", "open", "approved", "changes_requested", "deferred", "assigned", "under_review", "candidate"},
    },
    "claim_stub": {
        "table": "claim_records",
        "id_column": "claim_id",
        "columns": ["claim_id", "source_evidence_id", "evidence_selection_id", "claim_text", "claim_type", "evidence_relation", "qualifier_json", "source_anchor_json", "status", "note", "actor", "created_at", "updated_at"],
        "statuses": {"draft", "proposed", "under_review", "accepted", "disputed", "rejected", "published", "superseded", "smoke_test", "open", "approved", "changes_requested", "deferred", "assigned", "needs_more_evidence"},
    },
}


def fetch_review_object(subject_type, subject_id):
    config = REVIEW_OBJECT_CONFIGS.get(subject_type)
    if not config:
        raise ResearchUiError(400, f"Unsupported subject_type: {subject_type}")
    rows = ch_data(
        f"""
        SELECT {", ".join(config["columns"])}
        FROM {config["table"]} FINAL
        WHERE {config["id_column"]} = {sql_string(subject_id)}
        LIMIT 1
        """,
        fallback=[],
    )
    if not rows:
        raise ResearchUiError(404, f"Review object not found: {subject_type}/{subject_id}")
    return config, rows[0]


def update_review_state(payload):
    subject_type = compact_text(payload.get("subject_type"), 80)
    subject_id = compact_text(payload.get("subject_id"), 300)
    status = compact_text(payload.get("status"), 80)
    if not subject_type or not subject_id:
        raise ResearchUiError(400, "subject_type and subject_id are required")
    if not status:
        raise ResearchUiError(400, "status is required")
    config, current = fetch_review_object(subject_type, subject_id)
    previous_status = current.get("status") or ""
    current_version = current.get("updated_at") or ""
    # Optimistic concurrency (spec §31): if the client holds an expected_version
    # that no longer matches the object's updated_at, another decision landed in
    # between — surface a 409 with the before/after so the UI can open a diff
    # instead of silently overwriting the newer version.
    expected_version = compact_text(payload.get("expected_version"), 120)
    if expected_version and expected_version != current_version:
        raise ResearchUiError(
            409,
            f"{subject_type} changed since it was loaded",
        )
    actor_value = compact_text(payload.get("actor") or REVIEW_ACTOR, 200)
    validate_status(subject_type, status, actor=actor_value, is_create=False)
    assert_not_terminal_transition(subject_type, previous_status, status)
    now = now_iso()
    updated = {column: current.get(column, "") for column in config["columns"]}
    updated["status"] = status
    updated["updated_at"] = now
    updated["actor"] = actor_value
    note = compact_text(payload.get("note"), 20000)
    if note and "note" in updated:
        updated["note"] = note
    source_anchor = parse_raw_json(current.get("source_anchor_json", ""))
    event_payload = {
        **payload,
        "source_evidence_id": compact_text(payload.get("source_evidence_id") or current.get("source_evidence_id"), 1000),
        "subject_type": subject_type,
        "subject_id": subject_id,
        "before_status": previous_status,
        "after_status": status,
        "status": status,
        "note": note,
        "source_anchor": source_anchor,
    }
    event = persist_review_event(build_review_event("review_state.changed", event_payload))
    ch_insert_json_each_row(config["table"], [updated])
    return {
        "event": event,
        "object": updated,
        "version": updated.get("updated_at") or now,
        "expected_version": expected_version,
        "before_status": previous_status,
        "after_status": status,
    }


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
        path = (STATIC_DIR / clean).resolve()
        # Containment check: the resolved path must stay inside STATIC_DIR.
        # normpath collapses ".." but does not prevent escaping the static root,
        # so an encoded request like /static/%2e%2e%2f%2e%2e%2fetc%2fhostname
        # would otherwise resolve outside STATIC_DIR and read arbitrary files.
        try:
            path.relative_to(STATIC_DIR.resolve())
        except ValueError:
            raise ResearchUiError(404, "Static file not found")
        if not path.is_file():
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
        path = urllib.parse.urlparse(self.path).path
        if path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            return
        if path == "/favicon.ico":
            self.send_response(204)
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
            if parsed.path == "/favicon.ico":
                self.send_response(204)
                self.end_headers()
                return
            if parsed.path == "/healthz":
                return self.send_json({"ok": True, "service": "research-ui"})
            if parsed.path == "/api/home":
                return self.send_json(home_summary(params))
            if parsed.path == "/api/facets":
                return self.send_json(facets())
            if parsed.path == "/api/inbox":
                return self.send_json(inbox(params))
            if parsed.path == "/api/projects":
                return self.send_json(project_rows(params))
            if parsed.path.startswith("/api/project/") and parsed.path.endswith("/timeline"):
                tail = parsed.path[len("/api/project/"):-len("/timeline")]
                params["project_id"] = [urllib.parse.unquote(tail)]
                return self.send_json(project_timeline(params))
            if parsed.path.startswith("/api/project/") and "/compare" in parsed.path:
                tail = parsed.path[len("/api/project/"):]
                parts = tail.split("/")
                params["project_id"] = [urllib.parse.unquote(parts[0])]
                if len(parts) > 2:
                    params["view_id"] = [urllib.parse.unquote(parts[2])]
                return self.send_json(compare_view(params))
            if parsed.path.startswith("/api/project/") and "/draft/" in parsed.path:
                tail = parsed.path[len("/api/project/"):]
                project_id, draft_id = tail.split("/draft/", 1)
                params["project_id"] = [urllib.parse.unquote(project_id)]
                params["draft_id"] = [urllib.parse.unquote(draft_id)]
                return self.send_json(draft_editor(params))
            if parsed.path == "/api/library":
                return self.send_json(library_search(params))
            if parsed.path == "/api/evidence":
                return self.send_json(evidence_ledger(params))
            if parsed.path == "/api/entities":
                return self.send_json(entity_directory(params))
            if parsed.path.startswith("/api/entity/"):
                # The id carries ':' and '/' (e.g. entity_link:entity_link/<uuid>),
                # which the browser URL-encodes; decode before resolving.
                tail = parsed.path[len("/api/entity/"):]
                entity_id = urllib.parse.unquote(tail)
                params["entity_id"] = [entity_id]
                return self.send_json(entity_detail(params))
            if parsed.path.startswith("/api/conflicts/"):
                tail = parsed.path[len("/api/conflicts/"):]
                params["cluster_id"] = [urllib.parse.unquote(tail)]
                return self.send_json(conflict_cluster(params))
            if parsed.path == "/api/claims":
                return self.send_json(claims_ledger(params))
            if parsed.path == "/api/reviews":
                return self.send_json(reviews_read_model(params))
            if parsed.path == "/api/publishing":
                return self.send_json(publishing_read_model(params))
            if parsed.path.startswith("/api/publishing/"):
                params["bundle_id"] = [urllib.parse.unquote(parsed.path[len("/api/publishing/"):])]
                return self.send_json(publication_detail(params))
            if parsed.path.startswith("/api/topic/"):
                params["topic_id"] = [urllib.parse.unquote(parsed.path[len("/api/topic/"):])]
                return self.send_json(topic_detail(params))
            if parsed.path.startswith("/api/benchmark/"):
                params["benchmark_id"] = [urllib.parse.unquote(parsed.path[len("/api/benchmark/"):])]
                return self.send_json(benchmark_detail(params))
            if parsed.path == "/api/taxonomy":
                return self.send_json(taxonomy_read_model(params))
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
            # Review tables are ensured once at startup (see main()). Running 7
            # CREATE TABLE IF NOT EXISTS statements on every POST was pure
            # overhead on the write path. If a table is missing, the insert
            # surfaces a clean ClickHouse error (502) rather than silently
            # re-creating here.
            payload = self.read_json_body()
            if parsed.path == "/api/review/events":
                return self.send_json(create_generic_review_event(payload), status=201)
            if parsed.path == "/api/rebrowser/launch-capture":
                return self.send_json(launch_rebrowser_capture(payload), status=201)
            if parsed.path == "/api/publishing/snapshot":
                return self.send_json(create_publication_snapshot(payload), status=201)
            if parsed.path == "/api/publishing/request-review":
                return self.send_json(request_publication_review(payload), status=201)
            if parsed.path == "/api/publishing/approve":
                return self.send_json(approve_publication_snapshot(payload), status=201)
            if parsed.path == "/api/publishing/request-changes":
                return self.send_json(request_publication_changes(payload), status=201)
            if parsed.path == "/api/publishing/handoff":
                return self.send_json(create_publication_handoff(payload), status=201)
            if parsed.path == "/api/publishing/publish":
                return self.send_json(publish_publication_snapshot(payload), status=201)
            if parsed.path == "/api/publishing/supersede":
                return self.send_json(supersede_publication_release(payload), status=201)
            if parsed.path == "/api/conflicts/resolve":
                return self.send_json(resolve_conflict(payload), status=201)
            if parsed.path == "/api/project-brief":
                return self.send_json(update_project_brief(payload), status=201)
            if parsed.path == "/api/project-brief/review":
                return self.send_json(update_project_brief(payload, review_request=True), status=201)
            if parsed.path == "/api/drafts/save":
                return self.send_json(create_draft_revision(payload), status=201)
            if parsed.path == "/api/drafts/citation":
                return self.send_json(insert_draft_citation(payload), status=201)
            if parsed.path == "/api/drafts/proposed-diff":
                return self.send_json(create_draft_proposed_diff(payload), status=201)
            if parsed.path == "/api/benchmark/methodology":
                return self.send_json(save_benchmark_methodology(payload), status=201)
            if parsed.path == "/api/benchmark/result-group":
                return self.send_json(save_benchmark_result_group(payload), status=201)
            if parsed.path == "/api/library/actions":
                return self.send_json(create_library_action(payload), status=201)
            if parsed.path == "/api/evidence/selections":
                return self.send_json(create_evidence_selection(payload), status=201)
            if parsed.path == "/api/annotations":
                return self.send_json(create_review_annotation(payload), status=201)
            if parsed.path == "/api/proposed-facts":
                return self.send_json(create_proposed_fact(payload), status=201)
            if parsed.path == "/api/normalized-corrections":
                return self.send_json(create_normalized_correction(payload), status=201)
            if parsed.path == "/api/entity-links":
                return self.send_json(create_entity_link(payload), status=201)
            if parsed.path == "/api/claim-records":
                return self.send_json(create_claim_record(payload), status=201)
            if parsed.path == "/api/review-state":
                return self.send_json(update_review_state(payload), status=201)
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
