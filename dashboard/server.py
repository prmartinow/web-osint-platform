#!/usr/bin/env python3
import base64
import json
import mimetypes
import os
import posixpath
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
DATA_ROOT = Path(os.environ.get("WEB_OSINT_DATA_ROOT", str(APP_DIR / "data"))).resolve()
MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", str(DATA_ROOT / "media"))).resolve()
OCR_ROOT = Path(os.environ.get("OCR_ROOT", str(DATA_ROOT / "ocr"))).resolve()
WEB_ROOT = Path(os.environ.get("WEB_ROOT", str(MEDIA_ROOT.parent / "web"))).resolve()

CLICKHOUSE_URL = os.environ.get("CLICKHOUSE_URL", "http://web-osint-clickhouse:8123").rstrip("/")
CLICKHOUSE_DB = os.environ.get("CLICKHOUSE_DATABASE", "web_osint")
CLICKHOUSE_USER = os.environ.get("CLICKHOUSE_USER", "web_osint")
CLICKHOUSE_PASSWORD = os.environ.get("CLICKHOUSE_PASSWORD", "")
TYPESENSE_URL = os.environ.get("TYPESENSE_URL", "http://web-osint-typesense:8108").rstrip("/")
TYPESENSE_KEY = os.environ.get("TYPESENSE_API_KEY", "")
NORMALIZER_URL = os.environ.get("NORMALIZER_URL", "http://web-osint-normalizer:8090").rstrip("/")
RESEARCH_PLANNER_URL = os.environ.get("RESEARCH_PLANNER_URL", "http://web-osint-research-planner:8092").rstrip("/")
QDRANT_URL = os.environ.get("QDRANT_URL", "http://web-osint-qdrant:6333").rstrip("/")
QDRANT_COLLECTION = os.environ.get("QDRANT_COLLECTION", "web_osint_evidence_v1")
REDPANDA_PROXY_URL = os.environ.get("REDPANDA_PROXY_URL", "http://web-osint-redpanda:8082").rstrip("/")
REDPANDA_ADMIN_URL = os.environ.get("REDPANDA_ADMIN_URL", "http://web-osint-redpanda:9644").rstrip("/")
LOCAL_INFERENCE_URL = os.environ.get(
    "LOCAL_INFERENCE_URL",
    "http://127.0.0.1:18200",
).rstrip("/")
EMBEDDING_WORKER_URL = os.environ.get("EMBEDDING_WORKER_URL", "http://127.0.0.1:18201").rstrip("/")
MEDIA_ROUTER_URL = os.environ.get("MEDIA_ROUTER_URL", "http://127.0.0.1:18211").rstrip("/")
MEDIA_OCR_WORKER_URL = os.environ.get("MEDIA_OCR_WORKER_URL", "http://127.0.0.1:18212").rstrip("/")
MEDIA_VL_WORKER_URL = os.environ.get("MEDIA_VL_WORKER_URL", "http://127.0.0.1:18213").rstrip("/")
MEDIA_ROUTER_OPTIONAL = os.environ.get("MEDIA_ROUTER_OPTIONAL", "true").lower() in {"1", "true", "yes", "on"}
RESEARCH_SEARCH_TIMEOUT_SECONDS = int(os.environ.get("RESEARCH_SEARCH_TIMEOUT_SECONDS", "300"))
RESEARCH_QUERY_EMBEDDING_PROMPT = os.environ.get(
    "RESEARCH_QUERY_EMBEDDING_PROMPT",
    "Instruct: Given a web research query, retrieve relevant evidence passages that answer the query.\nQuery: ",
)

MAX_LIMIT = 500
MAX_FILE_PREVIEW_BYTES = 1_000_000
RESEARCH_SEARCH_MAX_LIMIT = 100
RESEARCH_BRANCH_LIMIT = 80
RESEARCH_RERANK_LIMIT = int(os.environ.get("RESEARCH_RERANK_LIMIT", "3"))
RRF_K = 60
RRF_BRANCH_WEIGHTS = {
    "exact": 4.0,
    "keyword": 1.2,
    "text_dense": 1.0,
    "ocr_dense": 0.95,
    "vl_image_dense": 0.85,
    "caption_dense": 0.75,
    "account_dense": 0.6,
    "rerank": 2.0,
}
PROM_SAMPLE_RE = re.compile(r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{([^}]*)\})?\s+(-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)$")
SAFE_SQL_PREFIXES = ("select", "with", "show", "describe", "desc", "exists")
BLOCKED_SQL_WORDS = {
    "alter", "attach", "create", "delete", "detach", "drop", "insert", "kill", "optimize",
    "rename", "replace", "restart", "set", "truncate", "update", "use",
}


class DashboardError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, indent=2, default=str).encode("utf-8")


def sql_string(value):
    text = str(value)
    return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"


def sql_int(value, default, min_value=0, max_value=MAX_LIMIT):
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = default
    return max(min_value, min(max_value, n))


def parse_boolish(value):
    if value is None or value == "":
        return None
    return str(value).lower() in {"1", "true", "yes", "on"}


def ch_query(query):
    params = {
        "database": CLICKHOUSE_DB,
        "query": query,
        "default_format": "JSON",
        "date_time_output_format": "iso",
    }
    url = CLICKHOUSE_URL + "/?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, method="POST")
    if CLICKHOUSE_PASSWORD:
        token = base64.b64encode(f"{CLICKHOUSE_USER}:{CLICKHOUSE_PASSWORD}".encode()).decode()
        request.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:2000]
        raise DashboardError(502, f"ClickHouse error {exc.code}: {detail}")
    except Exception as exc:
        raise DashboardError(502, f"ClickHouse request failed: {exc}")


def http_json(url, headers=None, timeout=10):
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        raise DashboardError(exc.code, detail or str(exc))
    except Exception as exc:
        raise DashboardError(502, str(exc))


def http_json_post(url, body, headers=None, timeout=10):
    payload = json.dumps(body).encode("utf-8")
    request_headers = {"Content-Type": "application/json"}
    request_headers.update(headers or {})
    request = urllib.request.Request(url, data=payload, method="POST", headers=request_headers)
    try:
        open_kwargs = {} if timeout is None else {"timeout": timeout}
        with urllib.request.urlopen(request, **open_kwargs) as response:
            raw = response.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:2000]
        raise DashboardError(exc.code, detail or str(exc))
    except Exception as exc:
        raise DashboardError(502, str(exc))


def http_text(url, headers=None, timeout=10):
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        raise DashboardError(exc.code, detail or str(exc))
    except Exception as exc:
        raise DashboardError(502, str(exc))


def ch_data(query):
    return ch_query(query).get("data", [])


def optional_ch_data(query, fallback=None):
    try:
        return ch_data(query)
    except DashboardError:
        return [] if fallback is None else fallback


def safe_order(value, allowed, default):
    return value if value in allowed else default


def timeframe(params):
    raw = params.get("frame", ["24h"])[0]
    frames = {
        "15m": ("15 MINUTE", 1),
        "1h": ("1 HOUR", 2),
        "6h": ("6 HOUR", 10),
        "24h": ("24 HOUR", 30),
        "7d": ("7 DAY", 240),
        "30d": ("30 DAY", 1440),
    }
    return raw if raw in frames else "24h", frames.get(raw, frames["24h"])


def activity_rows(frame="24h", kind_filter="", project_filter=""):
    _, (window, bucket_minutes) = timeframe({"frame": [frame]})
    clauses = [f"ingested_at >= now64() - INTERVAL {window}"]
    if kind_filter:
        clauses.append(f"source_kind = {sql_string(kind_filter)}")
    if project_filter:
        clauses.append(f"source_project = {sql_string(project_filter)}")
    where = " AND ".join(clauses)
    return ch_data(
        f"""
        SELECT
          toStartOfInterval(ingested_at, INTERVAL {bucket_minutes} MINUTE) AS bucket,
          count() AS rows,
          uniqExact(evidence_id) AS unique_evidence
        FROM evidence_events
        WHERE {where}
        GROUP BY bucket
        ORDER BY bucket ASC
        """
    )


def activity_by_kind(frame="24h"):
    _, (window, bucket_minutes) = timeframe({"frame": [frame]})
    return ch_data(
        f"""
        SELECT
          toStartOfInterval(ingested_at, INTERVAL {bucket_minutes} MINUTE) AS bucket,
          source_kind,
          count() AS rows
        FROM evidence_events
        WHERE ingested_at >= now64() - INTERVAL {window}
        GROUP BY bucket, source_kind
        ORDER BY bucket ASC, source_kind ASC
        LIMIT 1000
        """
    )


def parse_prometheus(text, prefixes=()):
    samples = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = PROM_SAMPLE_RE.match(line)
        if not match:
            continue
        name, raw_labels, raw_value = match.groups()
        if prefixes and not any(name.startswith(prefix) for prefix in prefixes):
            continue
        labels = {}
        if raw_labels:
            for part in re.finditer(r'([a-zA-Z_][a-zA-Z0-9_]*)="((?:[^"\\]|\\.)*)"', raw_labels):
                labels[part.group(1)] = part.group(2).replace(r'\"', '"')
        try:
            value = float(raw_value)
        except ValueError:
            continue
        samples.append({"name": name, "labels": labels, "value": value})
    return samples


def prom_sum(samples, name, label_key=None):
    totals = {}
    for sample in samples:
        if sample.get("name") != name:
            continue
        key = sample.get("labels", {}).get(label_key, "total") if label_key else "total"
        totals[key] = totals.get(key, 0) + sample.get("value", 0)
    return [{"key": key, "value": value} for key, value in sorted(totals.items())]


def service_json(name, fn):
    try:
        return {"ok": True, "data": fn()}
    except DashboardError as exc:
        return {"ok": False, "error": exc.message}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def build_where(params):
    clauses = []
    exact_fields = ["source_project", "source_kind", "capture_method", "collector_run_id", "domain", "author_handle"]
    for field in exact_fields:
        value = params.get(field, [""])[0].strip()
        if value:
            clauses.append(f"{field} = {sql_string(value)}")
    has_media = parse_boolish(params.get("has_media", [""])[0])
    if has_media is not None:
        clauses.append(f"has_media = {1 if has_media else 0}")
    has_ocr = parse_boolish(params.get("has_ocr", [""])[0])
    if has_ocr is not None:
        clauses.append(f"has_ocr = {1 if has_ocr else 0}")
    q = params.get("q", [""])[0].strip()
    if q:
        haystack = "concat(title, ' ', text, ' ', canonical_url, ' ', author_handle, ' ', domain, ' ', arrayStringConcat(topics, ' '), ' ', arrayStringConcat(entities, ' '))"
        clauses.append(f"positionCaseInsensitive({haystack}, {sql_string(q)}) > 0")
    date_from = params.get("date_from", [""])[0].strip()
    if date_from:
        clauses.append(f"captured_at >= parseDateTimeBestEffort({sql_string(date_from)})")
    date_to = params.get("date_to", [""])[0].strip()
    if date_to:
        clauses.append(f"captured_at <= parseDateTimeBestEffort({sql_string(date_to)})")
    return " AND ".join(clauses) if clauses else "1"


def overview():
    totals = ch_data(
        """
        SELECT
          count() AS evidence_rows,
          uniqExact(collector_run_id) AS collector_runs,
          uniqExact(evidence_id) AS unique_evidence,
          min(captured_at) AS first_capture,
          max(captured_at) AS last_capture,
          sum(has_media) AS media_marked_rows,
          sum(has_ocr) AS ocr_marked_rows
        FROM evidence_events
        """
    )[0]
    by_project_kind = ch_data(
        """
        SELECT source_project, source_kind, count() AS rows, uniqExact(evidence_id) AS unique_evidence
        FROM evidence_events
        GROUP BY source_project, source_kind
        ORDER BY source_project ASC, rows DESC
        """
    )
    latest_runs = ch_data(
        """
        SELECT
          collector_run_id,
          anyLast(source_project) AS source_project,
          anyLast(capture_method) AS capture_method,
          min(started_at) AS started_at,
          max(updated_at) AS updated_at,
          sum(records_seen) AS records_seen,
          sum(records_emitted) AS records_emitted,
          max(challenge) AS challenge,
          max(partial) AS partial,
          count() AS run_rows
        FROM collector_runs
        GROUP BY collector_run_id
        ORDER BY started_at DESC
        LIMIT 100
        """
    )
    daily = ch_data(
        """
        SELECT toDate(captured_at) AS day, source_project, source_kind, count() AS rows
        FROM evidence_events
        GROUP BY day, source_project, source_kind
        ORDER BY day DESC, source_project ASC, rows DESC
        LIMIT 500
        """
    )
    normalizer = {}
    planner = {}
    typesense = {}
    qdrant = {}
    redpanda = {}
    try:
        normalizer = http_json(f"{NORMALIZER_URL}/stats")
    except DashboardError as exc:
        normalizer = {"error": exc.message}
    try:
        planner = http_json(f"{RESEARCH_PLANNER_URL}/stats")
    except DashboardError as exc:
        planner = {"error": exc.message}
    try:
        typesense = http_json(
            f"{TYPESENSE_URL}/collections/evidence_posts",
            headers={"X-TYPESENSE-API-KEY": TYPESENSE_KEY},
        )
    except DashboardError as exc:
        typesense = {"error": exc.message}
    try:
        qdrant = http_json(f"{QDRANT_URL}/collections/{QDRANT_COLLECTION}")
    except DashboardError as exc:
        qdrant = {"error": exc.message}
    try:
        redpanda = http_json(f"{REDPANDA_PROXY_URL}/brokers")
    except DashboardError as exc:
        redpanda = {"error": exc.message}
    return {
        "totals": totals,
        "by_project_kind": by_project_kind,
        "latest_runs": latest_runs,
        "daily": daily,
        "services": {
            "normalizer": normalizer,
            "research_planner": planner,
            "typesense": {
                "num_documents": typesense.get("num_documents"),
                "name": typesense.get("name"),
                "error": typesense.get("error"),
            },
            "qdrant": qdrant.get("result", qdrant),
            "redpanda": redpanda,
        },
    }


def live_dashboard(params):
    frame = params.get("frame", ["24h"])[0]
    totals = ch_data(
        """
        SELECT
          count() AS evidence_rows,
          uniqExact(evidence_id) AS unique_evidence,
          uniqExact(collector_run_id) AS collector_runs,
          max(ingested_at) AS last_ingested_at,
          max(captured_at) AS last_captured_at,
          dateDiff('second', max(ingested_at), now64()) AS ingest_age_seconds,
          sum(has_media) AS media_marked_rows,
          sum(has_ocr) AS ocr_marked_rows
        FROM evidence_events
        """
    )[0]
    by_kind = ch_data(
        """
        SELECT source_kind, count() AS rows, max(ingested_at) AS last_ingested_at
        FROM evidence_events
        GROUP BY source_kind
        ORDER BY rows DESC
        """
    )
    latest_runs = ch_data(
        """
        SELECT collector_run_id, source_project, capture_method, started_at, updated_at,
               records_seen, records_emitted, challenge, partial
        FROM collector_runs
        ORDER BY updated_at DESC
        LIMIT 12
        """
    )
    return {
        "generated_at": ch_data("SELECT now64() AS now")[0]["now"],
        "totals": totals,
        "stage_rows": by_kind,
        "histogram": activity_rows(frame),
        "histogram_by_kind": activity_by_kind(frame),
        "latest_runs": latest_runs,
        "services": {
            "redpanda": service_json("redpanda", lambda: http_json(f"{REDPANDA_PROXY_URL}/brokers")),
            "normalizer": service_json("normalizer", lambda: http_json(f"{NORMALIZER_URL}/stats")),
            "research_planner": service_json("research_planner", lambda: http_json(f"{RESEARCH_PLANNER_URL}/stats")),
            "qwen": service_json("qwen", lambda: http_json(f"{LOCAL_INFERENCE_URL}/healthz")),
            "typesense": service_json("typesense", lambda: http_json(
                f"{TYPESENSE_URL}/collections/evidence_posts",
                headers={"X-TYPESENSE-API-KEY": TYPESENSE_KEY},
            )),
            "qdrant": service_json("qdrant", lambda: http_json(f"{QDRANT_URL}/collections/{QDRANT_COLLECTION}")),
            "clickhouse": service_json("clickhouse", lambda: ch_data("SELECT 1 AS ok")[0]),
            "filesystem": service_json("filesystem", lambda: filesystem_metrics(frame, shallow=True)),
        },
    }


def collector_stage(params):
    frame = params.get("frame", ["24h"])[0]
    runs = ch_data(
        """
        SELECT collector_run_id, source_project, capture_method,
               min(started_at) AS started_at, max(updated_at) AS updated_at,
               sum(records_seen) AS records_seen, sum(records_emitted) AS records_emitted,
               max(challenge) AS challenge, max(partial) AS partial, count() AS observations
        FROM collector_runs
        GROUP BY collector_run_id, source_project, capture_method
        ORDER BY updated_at DESC
        LIMIT 300
        """
    )
    by_method = ch_data(
        """
        SELECT source_project, capture_method, count() AS run_rows,
               sum(records_seen) AS records_seen, sum(records_emitted) AS records_emitted,
               max(updated_at) AS last_seen
        FROM collector_runs
        GROUP BY source_project, capture_method
        ORDER BY last_seen DESC
        """
    )
    return {
        "runs": runs,
        "by_method": by_method,
        "histogram": activity_rows(frame),
    }


def facets():
    return {
        "source_project": ch_data("SELECT source_project AS value, count() AS rows FROM evidence_events GROUP BY source_project ORDER BY rows DESC, value ASC"),
        "source_kind": ch_data("SELECT source_kind AS value, count() AS rows FROM evidence_events GROUP BY source_kind ORDER BY rows DESC, value ASC"),
        "capture_method": ch_data("SELECT capture_method AS value, count() AS rows FROM evidence_events GROUP BY capture_method ORDER BY rows DESC, value ASC LIMIT 200"),
        "domain": ch_data("SELECT domain AS value, count() AS rows FROM evidence_events WHERE domain != '' GROUP BY domain ORDER BY rows DESC, value ASC LIMIT 200"),
        "author_handle": ch_data("SELECT author_handle AS value, count() AS rows FROM evidence_events WHERE author_handle != '' GROUP BY author_handle ORDER BY rows DESC, value ASC LIMIT 200"),
    }


def events(params):
    limit = sql_int(params.get("limit", ["100"])[0], 100, 1, MAX_LIMIT)
    offset = sql_int(params.get("offset", ["0"])[0], 0, 0, 1_000_000)
    sort = safe_order(params.get("sort", ["captured_at"])[0], {
        "captured_at", "ingested_at", "source_project", "source_kind", "capture_method", "collector_run_id",
        "evidence_id", "domain", "author_handle", "title",
    }, "captured_at")
    direction = "ASC" if params.get("direction", ["DESC"])[0].upper() == "ASC" else "DESC"
    where = build_where(params)
    query = f"""
      SELECT
        event_id,
        collector_run_id,
        source_project,
        capture_method,
        source_kind,
        evidence_id,
        canonical_url,
        author_handle,
        domain,
        title,
        substring(text, 1, 1600) AS text,
        topics,
        entities,
        links,
        has_media,
        has_ocr,
        posted_at,
        captured_at,
        ingested_at
      FROM evidence_events
      WHERE {where}
      ORDER BY {sort} {direction}, event_id ASC
      LIMIT {limit}
      OFFSET {offset}
    """
    count_query = f"SELECT count() AS rows FROM evidence_events WHERE {where}"
    return {"rows": ch_data(query), "total": ch_data(count_query)[0]["rows"], "limit": limit, "offset": offset}


def raw_event(params):
    event_id = params.get("event_id", [""])[0].strip()
    if not event_id:
        raise DashboardError(400, "event_id is required")
    rows = ch_data(
        f"""
        SELECT *
        FROM evidence_events
        WHERE event_id = {sql_string(event_id)}
        ORDER BY ingested_at DESC
        LIMIT 1
        """
    )
    if not rows:
        raise DashboardError(404, "event not found")
    row = rows[0]
    parsed = None
    try:
        parsed = json.loads(row.get("raw_json") or "{}")
    except json.JSONDecodeError:
        parsed = row.get("raw_json")
    return {"row": row, "raw": parsed}


def run_trace(params):
    run_id = params.get("collector_run_id", [""])[0].strip()
    if not run_id:
        raise DashboardError(400, "collector_run_id is required")
    rows = ch_data(
        f"""
        SELECT
          event_id, source_project, capture_method, source_kind, evidence_id, canonical_url,
          author_handle, domain, title, substring(text, 1, 1200) AS text, topics, entities,
          has_media, has_ocr, captured_at, ingested_at
        FROM evidence_events
        WHERE collector_run_id = {sql_string(run_id)}
        ORDER BY captured_at ASC, source_kind ASC, event_id ASC
        LIMIT 1000
        """
    )
    return {"collector_run_id": run_id, "rows": rows}


def type_search(params):
    q = params.get("q", ["*"])[0].strip() or "*"
    per_page = sql_int(params.get("per_page", ["25"])[0], 25, 1, 100)
    page = sql_int(params.get("page", ["1"])[0], 1, 1, 10000)
    filter_by = params.get("filter_by", [""])[0].strip()
    query = {
        "q": q,
        "query_by": "text,canonical_url,author_handle,author_name,entities,topics,links",
        "per_page": str(per_page),
        "page": str(page),
    }
    if filter_by:
        query["filter_by"] = filter_by
    url = f"{TYPESENSE_URL}/collections/evidence_posts/documents/search?{urllib.parse.urlencode(query)}"
    return http_json(url, headers={"X-TYPESENSE-API-KEY": TYPESENSE_KEY})


def lookup(params):
    key = params.get("key", [""])[0].strip()
    if not key:
        raise DashboardError(400, "key is required")
    return http_json(f"{NORMALIZER_URL}/lookup?{urllib.parse.urlencode({'key': key})}")


def media_path_from_row(row):
    raw = row.get("raw_json") or "{}"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {}
    for key in ("storage_path", "local_path", "path"):
        value = parsed.get(key)
        if value:
            return value
    raw_obj = parsed.get("raw") if isinstance(parsed.get("raw"), dict) else {}
    for key in ("storage_path", "local_path", "path"):
        value = raw_obj.get(key)
        if value:
            return value
    return ""


def safe_media_path(raw_path):
    if not raw_path:
        raise DashboardError(404, "media path not found")
    candidate = Path(raw_path).resolve()
    try:
        candidate.relative_to(MEDIA_ROOT)
    except ValueError:
        raise DashboardError(403, "media path outside allowed root")
    if not candidate.is_file():
        raise DashboardError(404, "media file not found on disk")
    return candidate


def media_response(params):
    media_id = params.get("id", [""])[0].strip()
    raw_path = params.get("path", [""])[0].strip()
    if media_id and not raw_path:
        rows = ch_data(
            f"""
            SELECT evidence_id, raw_json
            FROM evidence_events
            WHERE source_kind = 'media' AND evidence_id = {sql_string(media_id)}
            ORDER BY ingested_at DESC
            LIMIT 1
            """
        )
        if not rows:
            raise DashboardError(404, "media row not found")
        raw_path = media_path_from_row(rows[0])
    path = safe_media_path(raw_path)
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return path, content_type


def media_index(params):
    limit = sql_int(params.get("limit", ["100"])[0], 100, 1, MAX_LIMIT)
    where = build_where(params)
    rows = ch_data(
        f"""
        SELECT event_id, evidence_id, title, canonical_url, substring(text, 1, 500) AS text,
               captured_at, raw_json
        FROM evidence_events
        WHERE source_kind = 'media' AND {where}
        ORDER BY captured_at DESC
        LIMIT {limit}
        """
    )
    out = []
    for row in rows:
        media_path = media_path_from_row(row)
        out.append({
            "event_id": row.get("event_id"),
            "evidence_id": row.get("evidence_id"),
            "title": row.get("title"),
            "text": row.get("text"),
            "captured_at": row.get("captured_at"),
            "path": media_path,
            "url": f"/api/media?id={urllib.parse.quote(row.get('evidence_id', ''))}" if media_path else "",
        })
    return {"rows": out}


def parsed_raw_json(row):
    raw = row.get("raw_json") or "{}"
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return {}


def inspector_path_url(raw_path):
    if not raw_path:
        return ""
    candidate = Path(str(raw_path)).resolve()
    for root in allowed_fs_roots():
        try:
            candidate.relative_to(root)
            return f"/api/stage/fs-file?{urllib.parse.urlencode({'path': str(candidate)})}"
        except ValueError:
            continue
    return ""


def artifact_paths_from_raw(raw):
    paths = []

    def add(value):
        if isinstance(value, str) and inspector_path_url(value) and value not in paths:
            paths.append(value)

    def walk(value, depth=0):
        if depth > 4:
            return
        if isinstance(value, dict):
            for key in ("artifact_paths", "ocr_artifact_paths", "local_paths", "paths"):
                raw_paths = value.get(key)
                if isinstance(raw_paths, list):
                    for item in raw_paths:
                        add(item)
                else:
                    add(raw_paths)
            for key in ("local_path", "storage_path", "path", "json_artifact_path", "text_artifact_path"):
                add(value.get(key))
            for key in ("context", "raw", "quality"):
                walk(value.get(key), depth + 1)
        elif isinstance(value, list):
            for item in value[:100]:
                walk(item, depth + 1)

    walk(raw)
    return paths


def evidence_inspector(params):
    query = params.get("q", [""])[0].strip()
    if not query:
        raise DashboardError(400, "q is required")
    query = query[:500]
    q_sql = sql_string(query)
    raw_q_sql = sql_string(query)
    clauses = [
        f"evidence_id = {q_sql}",
        f"collector_run_id = {q_sql}",
        f"canonical_url = {q_sql}",
        f"has(links, {q_sql})",
        f"positionCaseInsensitive(raw_json, {raw_q_sql}) > 0",
    ]
    status = re.search(r"(?:x|twitter)\.com/[^/\s]+/status/(\d+)", query)
    if status:
        post_id = status.group(1)
        post_sql = sql_string(post_id)
        status_path_sql = sql_string(f"/status/{post_id}")
        clauses.extend([
            f"evidence_id = {post_sql}",
            f"position(canonical_url, {status_path_sql}) > 0",
            f"position(raw_json, {post_sql}) > 0",
        ])
    if re.fullmatch(r"\d{12,25}", query):
        clauses.append(f"evidence_id = {q_sql}")
        clauses.append(f"position(raw_json, {q_sql}) > 0")

    seed_rows = ch_data(
        f"""
        SELECT *
        FROM evidence_events
        WHERE {" OR ".join(f"({clause})" for clause in clauses)}
        ORDER BY ingested_at DESC
        LIMIT 80
        """
    )
    run_ids = []
    for row in seed_rows:
        run_id = row.get("collector_run_id")
        if run_id and run_id not in run_ids:
            run_ids.append(run_id)

    related_rows = []
    if run_ids:
        quoted_runs = ", ".join(sql_string(run_id) for run_id in run_ids[:20])
        related_rows = ch_data(
            f"""
            SELECT *
            FROM evidence_events
            WHERE collector_run_id IN ({quoted_runs})
            ORDER BY captured_at ASC, source_kind ASC, event_id ASC
            LIMIT 300
            """
        )

    by_event = {}
    for row in [*seed_rows, *related_rows]:
        key = row.get("event_id") or f"{row.get('collector_run_id')}:{row.get('evidence_id')}"
        if key not in by_event:
            by_event[key] = row
    rows = list(by_event.values())
    rows.sort(key=lambda row: (row.get("collector_run_id") or "", row.get("source_kind") or "", row.get("captured_at") or ""))

    evidence_ids = [row.get("evidence_id") for row in rows if row.get("evidence_id")]
    quoted_ids = ", ".join(sql_string(eid) for eid in evidence_ids[:300])
    annotations = []
    ocr_rows = []
    vl_rows = []
    if quoted_ids:
        annotations = optional_ch_data(
            f"""
            SELECT evidence_id, annotation_family, label_id, status, confidence, span_text,
                   value_json, producer_name, producer_version, created_at
            FROM semantic_annotations
            WHERE evidence_id IN ({quoted_ids})
            ORDER BY created_at DESC
            LIMIT 300
            """
        )
        ocr_rows = optional_ch_data(
            f"""
            SELECT evidence_id, source_artifact_id, source_sha256, artifact_role, engine,
                   engine_version, status, text_chars, block_count, mean_confidence,
                   text_artifact_path, json_artifact_path, error_message, created_at
            FROM media_ocr_results
            WHERE evidence_id IN ({quoted_ids})
            ORDER BY created_at DESC
            LIMIT 300
            """
        )
        vl_rows = optional_ch_data(
            f"""
            SELECT evidence_id, source_artifact_id, source_sha256, model, model_version,
                   vector_name, status, qdrant_point_id, image_width, image_height,
                   error_message, created_at
            FROM media_vl_embeddings
            WHERE evidence_id IN ({quoted_ids})
            ORDER BY created_at DESC
            LIMIT 300
            """
        )

    ocr_by_evidence = {}
    for row in ocr_rows:
        ocr_by_evidence.setdefault(row.get("evidence_id"), []).append(row)
    vl_by_evidence = {}
    for row in vl_rows:
        vl_by_evidence.setdefault(row.get("evidence_id"), []).append(row)

    out_rows = []
    media = []
    artifacts = []
    for row in rows:
        raw = parsed_raw_json(row)
        text = row.get("text") or ""
        item = {k: v for k, v in row.items() if k != "raw_json"}
        item["text_len"] = len(text)
        item["text_preview"] = text[:1200]
        item["raw_url"] = f"/api/raw?{urllib.parse.urlencode({'event_id': row.get('event_id', '')})}"
        item["quality"] = raw.get("quality") or (raw.get("raw", {}) if isinstance(raw.get("raw"), dict) else {}).get("quality") or {}
        out_rows.append(item)

        for artifact_path in artifact_paths_from_raw(raw):
            artifacts.append({
                "source_evidence_id": row.get("evidence_id"),
                "source_kind": row.get("source_kind"),
                "path": artifact_path,
                "kind": human_kind(Path(artifact_path)),
                "url": inspector_path_url(artifact_path),
            })

        if row.get("source_kind") == "media":
            media_path = media_path_from_row(row)
            media.append({
                **item,
                "path": media_path,
                "url": f"/api/media?id={urllib.parse.quote(row.get('evidence_id', ''))}" if media_path else "",
                "ocr": ocr_by_evidence.get(row.get("evidence_id"), []),
                "vl": vl_by_evidence.get(row.get("evidence_id"), []),
            })

    def longest(kind):
        candidates = [row for row in out_rows if row.get("source_kind") == kind]
        return max(candidates, key=lambda row: row.get("text_len") or 0, default=None)

    by_kind = {}
    for row in out_rows:
        key = row.get("source_kind") or "unknown"
        by_kind[key] = by_kind.get(key, 0) + 1

    web_doc = longest("web_page")
    post = longest("x_post")
    account = longest("x_account")
    capture = longest("x_page") or longest("web_page")
    artifact_seen = set()
    unique_artifacts = []
    for artifact in artifacts:
        path_key = artifact.get("path")
        if path_key in artifact_seen:
            continue
        artifact_seen.add(path_key)
        unique_artifacts.append(artifact)

    return {
        "query": query,
        "generated_at": ch_data("SELECT now64() AS now")[0]["now"],
        "run_ids": run_ids,
        "cards": {
            "rows": len(out_rows),
            "runs": len(run_ids),
            "media": len(media),
            "artifacts": len(unique_artifacts),
            "annotations": len(annotations),
            "ocr_rows": len(ocr_rows),
            "vl_rows": len(vl_rows),
            "web_text_chars": (web_doc or {}).get("text_len", 0),
            "post_text_chars": (post or {}).get("text_len", 0),
        },
        "by_kind": [{"source_kind": key, "rows": value} for key, value in sorted(by_kind.items())],
        "primary": {
            "capture": capture,
            "web_document": web_doc,
            "x_post": post,
            "x_account": account,
        },
        "rows": out_rows,
        "media": media,
        "artifacts": unique_artifacts,
        "annotations": annotations,
        "ocr": ocr_rows,
        "vl": vl_rows,
    }


def allowed_fs_roots():
    return [MEDIA_ROOT, OCR_ROOT, WEB_ROOT]


def safe_fs_path(raw_path=""):
    if raw_path:
        candidate = Path(raw_path).resolve()
    else:
        candidate = MEDIA_ROOT
    for root in allowed_fs_roots():
        try:
            candidate.relative_to(root)
            return candidate
        except ValueError:
            continue
    raise DashboardError(403, "path outside allowed filesystem roots")


def human_kind(path):
    suffix = path.suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        return "image"
    if suffix in {".json", ".jsonl"}:
        return "json"
    if suffix in {".txt", ".md", ".csv", ".log"}:
        return "text"
    return suffix.lstrip(".") or "file"


def filesystem_metrics(frame="24h", shallow=False):
    roots = allowed_fs_roots()
    total_files = 0
    total_bytes = 0
    by_root = []
    by_kind = {}
    recent = []
    hist = {}
    now = ch_data("SELECT now64() AS now")[0]["now"]
    _, (window, bucket_minutes) = timeframe({"frame": [frame]})
    cutoff_rows = ch_data(f"SELECT now() - INTERVAL {window} AS cutoff")
    cutoff = cutoff_rows[0]["cutoff"] if cutoff_rows else ""

    for root in roots:
        root_files = 0
        root_bytes = 0
        if not root.exists():
            by_root.append({"root": str(root), "files": 0, "bytes": 0, "exists": False})
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            if shallow and Path(dirpath).relative_to(root).parts and len(Path(dirpath).relative_to(root).parts) > 2:
                dirnames[:] = []
                continue
            for filename in filenames:
                path = Path(dirpath) / filename
                try:
                    stat = path.stat()
                except OSError:
                    continue
                kind = human_kind(path)
                root_files += 1
                root_bytes += stat.st_size
                total_files += 1
                total_bytes += stat.st_size
                by_kind[kind] = by_kind.get(kind, {"kind": kind, "files": 0, "bytes": 0})
                by_kind[kind]["files"] += 1
                by_kind[kind]["bytes"] += stat.st_size
                mtime = stat.st_mtime
                recent.append({
                    "path": str(path),
                    "name": path.name,
                    "kind": kind,
                    "bytes": stat.st_size,
                    "modified_at": mtime,
                })
                bucket = int(mtime // (bucket_minutes * 60)) * bucket_minutes * 60
                hist[bucket] = hist.get(bucket, {"bucket_epoch": bucket, "files": 0, "bytes": 0})
                hist[bucket]["files"] += 1
                hist[bucket]["bytes"] += stat.st_size
        by_root.append({"root": str(root), "files": root_files, "bytes": root_bytes, "exists": True})
    recent.sort(key=lambda row: row["modified_at"], reverse=True)
    for row in recent[:200]:
        row["modified_at"] = datetime_from_epoch(row["modified_at"])
    histogram = sorted(hist.values(), key=lambda row: row["bucket_epoch"])
    for row in histogram:
        row["bucket"] = datetime_from_epoch(row["bucket_epoch"])
    return {
        "generated_at": now,
        "cutoff": cutoff,
        "roots": by_root,
        "total_files": total_files,
        "total_bytes": total_bytes,
        "by_kind": sorted(by_kind.values(), key=lambda row: row["bytes"], reverse=True),
        "recent": recent[:80],
        "histogram": histogram[-240:],
    }


def datetime_from_epoch(value):
    import datetime
    return datetime.datetime.fromtimestamp(value, datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def filesystem_tree(params):
    root = safe_fs_path(params.get("path", [""])[0].strip())
    if not root.exists():
        raise DashboardError(404, "path not found")
    if root.is_file():
        root = root.parent
    entries = []
    try:
        children = sorted(root.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    except OSError as exc:
        raise DashboardError(403, str(exc))
    for child in children[:500]:
        try:
            stat = child.stat()
        except OSError:
            continue
        entries.append({
            "name": child.name,
            "path": str(child),
            "type": "dir" if child.is_dir() else "file",
            "kind": human_kind(child) if child.is_file() else "dir",
            "bytes": stat.st_size if child.is_file() else None,
            "modified_at": datetime_from_epoch(stat.st_mtime),
        })
    return {"root": str(root), "parent": str(root.parent) if root != root.anchor else "", "entries": entries}


def filesystem_file(params):
    path = safe_fs_path(params.get("path", [""])[0].strip())
    if not path.is_file():
        raise DashboardError(404, "file not found")
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if content_type.startswith("image/"):
        return {"mode": "binary", "path": path, "content_type": content_type}
    size = path.stat().st_size
    if size > MAX_FILE_PREVIEW_BYTES:
        return {
            "mode": "preview",
            "path": str(path),
            "content_type": content_type,
            "bytes": size,
            "text": path.read_bytes()[:MAX_FILE_PREVIEW_BYTES].decode("utf-8", errors="replace"),
            "truncated": True,
        }
    return {
        "mode": "preview",
        "path": str(path),
        "content_type": content_type,
        "bytes": size,
        "text": path.read_text(encoding="utf-8", errors="replace"),
        "truncated": False,
    }


def qdrant_status():
    return http_json(f"{QDRANT_URL}/collections/{QDRANT_COLLECTION}")


def pebble_stage():
    return http_json(f"{NORMALIZER_URL}/pebble?limit=200")


def typesense_stage(params):
    frame = params.get("frame", ["24h"])[0]
    collection = http_json(
        f"{TYPESENSE_URL}/collections/evidence_posts",
        headers={"X-TYPESENSE-API-KEY": TYPESENSE_KEY},
    )
    stats = http_json(
        f"{TYPESENSE_URL}/stats.json",
        headers={"X-TYPESENSE-API-KEY": TYPESENSE_KEY},
    )
    try:
        metrics_text = http_text(
            f"{TYPESENSE_URL}/metrics.json",
            headers={"X-TYPESENSE-API-KEY": TYPESENSE_KEY},
        )
    except DashboardError as exc:
        metrics_text = json.dumps({"error": exc.message})
    by_project = ch_data(
        """
        SELECT source_project, count() AS rows, uniqExact(evidence_id) AS unique_evidence
        FROM evidence_events
        GROUP BY source_project
        ORDER BY rows DESC
        """
    )
    return {
        "health": http_json(f"{TYPESENSE_URL}/health", headers={"X-TYPESENSE-API-KEY": TYPESENSE_KEY}),
        "collection": collection,
        "stats": stats,
        "metrics_text": metrics_text[:12000],
        "by_project": by_project,
        "histogram": activity_rows(frame),
    }


def qdrant_stage(params):
    frame = params.get("frame", ["24h"])[0]
    collection = qdrant_status()
    try:
        metrics = parse_prometheus(http_text(f"{QDRANT_URL}/metrics"), (
            "app_info",
            "collections_total",
            "collection_vectors",
            "collection_points",
            "collection_running_optimizations",
            "rest_responses_total",
            "grpc_responses_total",
        ))
    except DashboardError as exc:
        metrics = [{"error": exc.message}]
    return {
        "collection": collection,
        "metrics": metrics,
        "histogram": activity_rows(frame),
    }


def host_cpu_info():
    info = {
        "model_name": "",
        "sockets": None,
        "physical_cores": None,
        "threads_per_core": None,
        "logical_threads": os.cpu_count(),
        "dashboard_affinity_threads": None,
    }
    try:
        info["dashboard_affinity_threads"] = len(os.sched_getaffinity(0))
    except Exception:
        pass
    try:
        text = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace")
        processors = len(re.findall(r"^processor\s*:", text, flags=re.MULTILINE))
        model_match = re.search(r"^model name\s*:\s*(.+)$", text, flags=re.MULTILINE)
        physical_ids = set()
        core_pairs = set()
        current = {}
        for block in text.strip().split("\n\n"):
            current = {}
            for line in block.splitlines():
                if ":" not in line:
                    continue
                key, value = [part.strip() for part in line.split(":", 1)]
                current[key] = value
            physical_id = current.get("physical id", "0")
            core_id = current.get("core id")
            physical_ids.add(physical_id)
            if core_id is not None:
                core_pairs.add((physical_id, core_id))
        if processors:
            info["logical_threads"] = processors
        if model_match:
            info["model_name"] = model_match.group(1)
        if physical_ids:
            info["sockets"] = len(physical_ids)
        if core_pairs:
            info["physical_cores"] = len(core_pairs)
        if info["physical_cores"] and info["logical_threads"]:
            info["threads_per_core"] = round(info["logical_threads"] / info["physical_cores"], 2)
    except Exception:
        pass
    return info


def qwen_request_rows(qwen_health):
    metrics = (qwen_health or {}).get("metrics") or {}
    rows = {}
    for counter in metrics.get("counters", []):
        if counter.get("name") != "web_osint_qwen_requests_total":
            continue
        labels = counter.get("labels") or {}
        key = (labels.get("model", ""), labels.get("operation", ""), labels.get("status", ""))
        row = rows.setdefault(key, {
            "model": key[0],
            "operation": key[1],
            "status": key[2],
            "requests": 0,
            "avg_duration_seconds": None,
            "max_duration_seconds": None,
            "avg_queue_wait_seconds": None,
            "max_queue_wait_seconds": None,
            "avg_batch_size": None,
            "max_batch_size": None,
        })
        row["requests"] += counter.get("value", 0)
    obs_by_key = {}
    for obs in metrics.get("observations", []):
        labels = obs.get("labels") or {}
        key = (labels.get("model", ""), labels.get("operation", ""))
        obs_by_key.setdefault(key, {})[obs.get("name", "")] = obs
    for row in rows.values():
        obs = obs_by_key.get((row["model"], row["operation"]), {})
        duration = obs.get("web_osint_qwen_request_duration_seconds") or {}
        queue = obs.get("web_osint_qwen_queue_wait_seconds") or {}
        batch = obs.get("web_osint_qwen_batch_size") or {}
        if duration.get("count"):
            row["avg_duration_seconds"] = duration.get("sum", 0) / duration.get("count", 1)
            row["max_duration_seconds"] = duration.get("max")
        if queue.get("count"):
            row["avg_queue_wait_seconds"] = queue.get("sum", 0) / queue.get("count", 1)
            row["max_queue_wait_seconds"] = queue.get("max")
        if batch.get("count"):
            row["avg_batch_size"] = batch.get("sum", 0) / batch.get("count", 1)
            row["max_batch_size"] = batch.get("max")
    return sorted(rows.values(), key=lambda r: (r["model"], r["operation"], r["status"]))


def qwen_request_totals(request_metrics):
    totals = {}
    for row in request_metrics:
        key = (row.get("model", ""), row.get("operation", ""))
        current = totals.setdefault(key, {
            "requests": 0,
            "avg_duration_seconds": None,
            "max_duration_seconds": None,
            "avg_queue_wait_seconds": None,
        })
        current["requests"] += row.get("requests", 0)
        for field in ("avg_duration_seconds", "avg_queue_wait_seconds"):
            if row.get(field) is not None:
                current[field] = row.get(field)
        if row.get("max_duration_seconds") is not None:
            current["max_duration_seconds"] = max(current["max_duration_seconds"] or 0, row.get("max_duration_seconds"))
    return totals


def output_count_maps(output_counts):
    totals = {}
    latest = {}
    for row in output_counts:
        output = row.get("output", "")
        totals[output] = totals.get(output, 0) + int(row.get("rows") or 0)
        last = row.get("last_created_at") or ""
        if last and last > latest.get(output, ""):
            latest[output] = last
    return totals, latest


def model_status_counts(inventory):
    counts = {}
    for row in inventory:
        status = row.get("status") or "unknown"
        counts[status] = counts.get(status, 0) + 1
    usable = sum(counts.get(status, 0) for status in ("loaded", "available", "ready"))
    return {**counts, "usable": usable}


def model_inventory(qwen_health):
    paths = (qwen_health or {}).get("model_paths") or {}
    exists = (qwen_health or {}).get("model_path_exists") or {}
    loaded = (qwen_health or {}).get("loaded") or {}
    model_specs = [
        {
            "id": "text",
            "name": "Qwen3-Embedding-8B",
            "repo": "Qwen/Qwen3-Embedding-8B",
            "role": "default text embedding",
            "modality": "text",
            "precision": "bf16 safetensors",
            "dimension": 4096,
            "vector_name": "text_dense",
            "endpoint": "POST /embed model=text",
            "worker": "web-osint-embedding-worker",
            "output": "Qdrant text_dense + osint.semantic.embedded.v1",
        },
        {
            "id": "reranker",
            "name": "Qwen3-Reranker-8B",
            "repo": "Qwen/Qwen3-Reranker-8B",
            "role": "precision reranking",
            "modality": "text pairs",
            "precision": "bf16 safetensors",
            "dimension": "",
            "vector_name": "",
            "endpoint": "POST /rerank",
            "worker": "research search coordinator",
            "output": "reranked research-search results",
        },
        {
            "id": "vl",
            "name": "Qwen3-VL-Embedding-8B",
            "repo": "Qwen/Qwen3-VL-Embedding-8B",
            "role": "image/screenshot embedding",
            "modality": "image + text",
            "precision": "bf16 safetensors",
            "dimension": 4096,
            "vector_name": "vl_image_dense",
            "endpoint": "POST /embed model=vl",
            "worker": "web-osint-media-vl-worker",
            "output": "Qdrant vl_image_dense + media_vl_embeddings",
        },
    ]
    inventory = []
    for spec in model_specs:
        path = paths.get(spec["id"], "")
        if spec["id"] in loaded:
            status = "loaded"
        elif exists.get(spec["id"]):
            status = "available"
        else:
            status = "missing"
        inventory.append({
            **spec,
            "status": status,
            "path": path,
            "path_exists": bool(exists.get(spec["id"])),
            "size_bytes": None,
            "files": None,
            "loaded_for_seconds": (loaded.get(spec["id"]) or {}).get("loaded_for_seconds"),
        })
    paddle_loaded = next((value for key, value in loaded.items() if str(key).startswith("paddleocr")), None)
    inventory.append({
        "id": "paddleocr",
        "name": "PaddleOCR",
        "repo": "paddlepaddle/PaddleOCR",
        "role": "OCR text extraction",
        "modality": "image -> text",
        "precision": "CPU runtime",
        "dimension": "",
        "vector_name": "ocr_dense downstream",
        "endpoint": "POST /media/ocr",
        "worker": "local-inference",
        "output": "media_ocr_results + OCR artifacts",
        "status": "loaded" if paddle_loaded else ("available" if exists.get("paddleocr_home") else "missing"),
        "path": paths.get("paddleocr_home", ""),
        "path_exists": bool(exists.get("paddleocr_home")),
        "size_bytes": None,
        "files": None,
        "loaded_for_seconds": (paddle_loaded or {}).get("loaded_for_seconds"),
    })
    return inventory


def model_stage(params):
    frame = params.get("frame", ["24h"])[0]
    qwen_status = service_json("qwen", lambda: http_json(f"{LOCAL_INFERENCE_URL}/healthz", timeout=8))
    embedding_status = service_json("embedding_worker", lambda: http_json(f"{EMBEDDING_WORKER_URL}/stats", timeout=8))
    router_status = service_json("media_router", lambda: http_json(f"{MEDIA_ROUTER_URL}/stats", timeout=8))
    if MEDIA_ROUTER_OPTIONAL and not router_status.get("ok"):
        router_status = {
            "ok": True,
            "data": {
                "ok": True,
                "optional": True,
                "role": "legacy-router",
                "last_error": "",
                "note": "Legacy Python media router is disabled; Redpanda Connect production routing emits OCR/VL requests.",
            },
        }
    ocr_status = service_json("media_ocr", lambda: http_json(f"{MEDIA_OCR_WORKER_URL}/stats", timeout=8))
    vl_status = service_json("media_vl", lambda: http_json(f"{MEDIA_VL_WORKER_URL}/stats", timeout=8))

    qwen_health = qwen_status.get("data") if qwen_status.get("ok") else {}
    guardrails = []
    for operation, cfg in (qwen_health.get("guardrails") or {}).items():
        guardrails.append({"operation": operation, **(cfg or {})})
    inventory = model_inventory(qwen_health)
    request_metrics = qwen_request_rows(qwen_health)
    request_totals = qwen_request_totals(request_metrics)

    worker_statuses = [
        ("local-inference", "model API", qwen_status),
        ("embedding-worker", "text embedding", embedding_status),
        ("media-router", "legacy media routing", router_status),
        ("media-ocr-worker", "OCR", ocr_status),
        ("media-vl-worker", "VL embedding", vl_status),
    ]
    workers = []
    for name, role, status in worker_statuses:
        data = status.get("data") or {}
        current_alert = (not status.get("ok")) or bool(data.get("last_error") or status.get("error"))
        try:
            historical_failures = int(data.get("failed") or 0)
        except (TypeError, ValueError):
            historical_failures = 0
        workers.append({
            "name": name,
            "role": role,
            "ok": status.get("ok"),
            "current_alert": current_alert,
            "historical_failures": historical_failures,
            "started_at": data.get("started_at") or data.get("metrics", {}).get("started_at", ""),
            "consumed": data.get("consumed", ""),
            "completed": data.get("completed", ""),
            "embedded": data.get("embedded", ""),
            "failed": data.get("failed", ""),
            "queued_ocr": data.get("queued_ocr", ""),
            "queued_vl": data.get("queued_vl", ""),
            "last_error": data.get("last_error") or status.get("error", ""),
            "note": data.get("note", ""),
        })

    output_counts = []
    output_counts.extend(optional_ch_data(
        """
        SELECT 'media_ocr_results' AS output, status, count() AS rows, max(created_at) AS last_created_at
        FROM media_ocr_results
        GROUP BY status
        ORDER BY output, status
        """
    ))
    output_counts.extend(optional_ch_data(
        """
        SELECT 'media_vl_embeddings' AS output, status, count() AS rows, max(created_at) AS last_created_at
        FROM media_vl_embeddings
        GROUP BY status
        ORDER BY output, status
        """
    ))
    recent_outputs = []
    recent_outputs.extend(optional_ch_data(
        """
        SELECT 'ocr' AS lane, created_at, evidence_id, engine AS model, status,
               concat(toString(text_chars), ' chars / ', toString(block_count), ' blocks') AS detail,
               json_artifact_path AS artifact
        FROM media_ocr_results
        ORDER BY created_at DESC
        LIMIT 50
        """
    ))
    recent_outputs.extend(optional_ch_data(
        """
        SELECT 'vl' AS lane, created_at, evidence_id, model, status,
               concat(vector_name, ' / ', toString(image_width), 'x', toString(image_height)) AS detail,
               qdrant_point_id AS artifact
        FROM media_vl_embeddings
        ORDER BY created_at DESC
        LIMIT 50
        """
    ))
    recent_outputs.sort(key=lambda row: row.get("created_at") or "", reverse=True)
    output_totals, output_latest = output_count_maps(output_counts)

    qdrant_collection = service_json("qdrant", lambda: http_json(f"{QDRANT_URL}/collections/{QDRANT_COLLECTION}", timeout=8))
    lineage = [
        {"source": "evidence.*.observed.v1", "model": "Qwen3-Embedding-8B", "worker": "embedding-worker", "output": "Qdrant text_dense", "audit": "osint.semantic.embedded.v1"},
        {"source": "research query", "model": "Qwen3-Embedding-8B", "worker": "dashboard coordinator", "output": "Qdrant candidate search", "audit": "request metrics"},
        {"source": "research candidates", "model": "Qwen3-Reranker-8B", "worker": "dashboard coordinator", "output": "precision reranked results", "audit": "request metrics"},
        {"source": "media artifacts", "model": "PaddleOCR", "worker": "media-ocr-worker", "output": "media_ocr_results + OCR files", "audit": "ClickHouse"},
        {"source": "media artifacts", "model": "Qwen3-VL-Embedding-8B", "worker": "media-vl-worker", "output": "Qdrant vl_image_dense", "audit": "media_vl_embeddings"},
    ]

    status_counts = model_status_counts(inventory)
    active_requests = sum(int((row.get("active") or 0)) for row in guardrails)
    waiting_requests = sum(int((row.get("waiting") or 0)) for row in guardrails)
    current_worker_alerts = sum(1 for row in workers if row.get("current_alert"))
    historical_worker_failures = sum(int(row.get("historical_failures") or 0) for row in workers)
    host_cpu = host_cpu_info()
    cpu_guard = qwen_health.get("cpu_thread_guard") or {}

    def qwen_activity(model, operation, lane, completed="", failed="", outputs="", last_output=""):
        totals = request_totals.get((model, operation), {})
        return {
            "model": model,
            "lane": lane,
            "operation": operation,
            "requests": totals.get("requests", 0),
            "completed": completed,
            "failed": failed,
            "outputs": outputs,
            "avg_duration_seconds": totals.get("avg_duration_seconds"),
            "max_duration_seconds": totals.get("max_duration_seconds"),
            "last_output": last_output,
        }

    vl_worker = next((row for row in workers if row["name"] == "media-vl-worker"), {})
    ocr_worker = next((row for row in workers if row["name"] == "media-ocr-worker"), {})
    model_activity = [
        qwen_activity("Qwen3-Embedding-8B", "embed", "background text vectors"),
        qwen_activity("Qwen3-Embedding-8B", "query_embed", "research query vectors"),
        qwen_activity("Qwen3-Reranker-8B", "rerank", "precision rerank"),
        qwen_activity(
            "Qwen3-VL-Embedding-8B",
            "vl",
            "image/screenshot vectors",
            completed=vl_worker.get("completed", ""),
            failed=vl_worker.get("failed", ""),
            outputs=output_totals.get("media_vl_embeddings", 0),
            last_output=output_latest.get("media_vl_embeddings", ""),
        ),
        {
            "model": "PaddleOCR",
            "lane": "OCR extraction",
            "operation": "ocr",
            "requests": ocr_worker.get("consumed", 0),
            "completed": ocr_worker.get("completed", 0),
            "failed": ocr_worker.get("failed", 0),
            "outputs": output_totals.get("media_ocr_results", 0),
            "avg_duration_seconds": None,
            "max_duration_seconds": None,
            "last_output": output_latest.get("media_ocr_results", ""),
        },
    ]

    return {
        "generated_at": ch_data("SELECT now64() AS now")[0]["now"],
        "frame": frame,
        "cards": {
            "models": len(inventory),
            "model_status": status_counts,
            "active_requests": active_requests,
            "waiting_requests": waiting_requests,
            "current_worker_alerts": current_worker_alerts,
            "historical_worker_failures": historical_worker_failures,
            "requests_total": sum(row.get("requests", 0) for row in request_metrics),
            "qwen_torch_threads": cpu_guard.get("torch_threads"),
        },
        "inventory": inventory,
        "lineage": lineage,
        "guardrails": guardrails,
        "request_metrics": request_metrics,
        "model_activity": model_activity,
        "workers": workers,
        "output_counts": output_counts,
        "recent_outputs": recent_outputs[:80],
        "qwen": qwen_status,
        "embedding_worker": embedding_status,
        "media_router": router_status,
        "media_ocr": ocr_status,
        "media_vl": vl_status,
        "qdrant": qdrant_collection,
        "histogram": activity_rows(frame),
        "cpu_thread_guard": cpu_guard,
        "host_cpu": host_cpu,
        "model_root": "local-inference:/healthz",
    }


def clickhouse_stage(params):
    frame = params.get("frame", ["24h"])[0]
    totals = ch_data(
        """
        SELECT count() AS evidence_rows, uniqExact(evidence_id) AS unique_evidence,
               uniqExact(collector_run_id) AS collector_runs,
               max(ingested_at) AS last_ingested_at
        FROM evidence_events
        """
    )[0]
    tables = ch_data(
        """
        SELECT name, total_rows, total_bytes
        FROM system.tables
        WHERE database = currentDatabase()
        ORDER BY total_bytes DESC
        """
    )
    metrics = ch_data(
        """
        SELECT metric AS name, value
        FROM system.metrics
        WHERE metric IN ('Query', 'Merge', 'ReadonlyReplica', 'MemoryTracking', 'HTTPConnection', 'TCPConnection')
        ORDER BY name
        """
    )
    async_metrics = ch_data(
        """
        SELECT metric AS name, value
        FROM system.asynchronous_metrics
        WHERE metric IN ('Uptime', 'FilesystemMainAvailableSpace', 'FilesystemMainTotalSpace', 'MaxPartCountForPartition', 'NumberOfDatabases', 'NumberOfTables')
        ORDER BY name
        """
    )
    query_log = []
    try:
        query_log = ch_data(
            """
            SELECT event_time, query_duration_ms, read_rows, read_bytes, result_rows,
                   substring(query, 1, 240) AS query
            FROM system.query_log
            WHERE type = 'QueryFinish'
            ORDER BY event_time DESC
            LIMIT 50
            """
        )
    except DashboardError:
        query_log = []
    return {
        "totals": totals,
        "tables": tables,
        "metrics": metrics,
        "asynchronous_metrics": async_metrics,
        "query_log": query_log,
        "histogram": activity_rows(frame),
        "histogram_by_kind": activity_by_kind(frame),
        "builtin_interfaces": [
            {"name": "ClickHouse Play", "path": "/clickhouse/play"},
            {"name": "ClickHouse Dashboard", "path": "/clickhouse/dashboard"},
            {"name": "ClickStack", "path": "/clickhouse/clickstack"},
        ],
    }


def meaning_stage(params):
    frame = params.get("frame", ["24h"])[0]
    _, (window, bucket_minutes) = timeframe({"frame": [frame]})
    totals = optional_ch_data(
        """
        SELECT
          count() AS annotations,
          uniqExact(evidence_id) AS annotated_evidence,
          uniqExact(label_id) AS unique_labels,
          countIf(status = 'accepted') AS accepted,
          countIf(status = 'proposed') AS proposed,
          avg(confidence) AS avg_confidence,
          max(created_at) AS last_annotation_at
        FROM semantic_annotations
        """,
        [{
            "annotations": 0,
            "annotated_evidence": 0,
            "unique_labels": 0,
            "accepted": 0,
            "proposed": 0,
            "avg_confidence": 0,
            "last_annotation_at": "",
        }],
    )[0]
    histogram = optional_ch_data(
        f"""
        SELECT
          toStartOfInterval(created_at, INTERVAL {bucket_minutes} MINUTE) AS bucket,
          count() AS rows,
          uniqExact(evidence_id) AS unique_evidence
        FROM semantic_annotations
        WHERE created_at >= now64() - INTERVAL {window}
        GROUP BY bucket
        ORDER BY bucket ASC
        """
    )
    by_family = optional_ch_data(
        """
        SELECT
          annotation_family,
          count() AS annotations,
          uniqExact(label_id) AS labels,
          uniqExact(evidence_id) AS evidence,
          round(avg(confidence), 3) AS avg_confidence,
          max(created_at) AS last_seen
        FROM semantic_annotations
        GROUP BY annotation_family
        ORDER BY annotations DESC, annotation_family ASC
        LIMIT 200
        """
    )
    top_labels = optional_ch_data(
        """
        SELECT
          annotation_family,
          label_id,
          status,
          count() AS annotations,
          uniqExact(evidence_id) AS evidence,
          round(avg(confidence), 3) AS avg_confidence,
          max(created_at) AS last_seen
        FROM semantic_annotations
        GROUP BY annotation_family, label_id, status
        ORDER BY annotations DESC, annotation_family ASC, label_id ASC
        LIMIT 300
        """
    )
    recent = optional_ch_data(
        """
        SELECT
          annotation_id,
          created_at,
          annotation_family,
          label_id,
          status,
          confidence,
          evidence_id,
          target_type,
          selector_type,
          substring(value_json, 1, 1200) AS value_json
        FROM semantic_annotations
        ORDER BY created_at DESC
        LIMIT 200
        """
    )
    research_signals = optional_ch_data(
        """
        SELECT
          created_at,
          signal_type,
          primary_entity_id,
          topic_label_id,
          signal_summary,
          novelty_score,
          uncertainty_score,
          impact_score
        FROM research_signals
        ORDER BY created_at DESC
        LIMIT 100
        """
    )
    research_questions = optional_ch_data(
        """
        SELECT
          created_at,
          status,
          priority,
          question_type,
          question_id,
          question_text,
          rationale
        FROM research_questions
        ORDER BY status ASC, priority DESC, created_at DESC
        LIMIT 100
        """
    )
    autonomous_tasks = optional_ch_data(
        """
        SELECT
          created_at,
          updated_at,
          status,
          priority,
          task_type,
          task_id,
          question_id,
          dedupe_key,
          rationale
        FROM autonomous_tasks
        ORDER BY status ASC, priority DESC, created_at DESC
        LIMIT 100
        """
    )
    return {
        "totals": totals,
        "histogram": histogram,
        "by_family": by_family,
        "top_labels": top_labels,
        "recent": recent,
        "research_signals": research_signals,
        "research_questions": research_questions,
        "autonomous_tasks": autonomous_tasks,
    }


def clamp_int(value, default, min_value, max_value):
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = default
    return max(min_value, min(max_value, n))


def as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        items = value
    elif isinstance(value, tuple):
        items = list(value)
    else:
        items = [value]
    out = []
    for item in items:
        if item is None:
            continue
        text = str(item).strip()
        if text:
            out.append(text)
    return out


def normalize_search_filters(raw):
    raw = raw or {}
    aliases = {
        "source_projects": ("source_projects", "source_project", "projects", "project"),
        "source_kinds": ("source_kinds", "source_kind", "kinds", "kind"),
        "author_handles": ("author_handles", "author_handle", "handles", "handle"),
        "domains": ("domains", "domain"),
        "topics": ("topics", "topic"),
        "entities": ("entities", "entity"),
    }
    filters = {}
    for canonical, names in aliases.items():
        values = []
        for name in names:
            if name in raw:
                values.extend(as_list(raw.get(name)))
        if values:
            seen = set()
            filters[canonical] = [v for v in values if not (v in seen or seen.add(v))]
    for key in ("has_media", "has_ocr"):
        if key in raw and raw.get(key) not in ("", None):
            filters[key] = bool(parse_boolish(raw.get(key)))
    for key in ("date_from", "date_to"):
        value = str(raw.get(key, "") or "").strip()
        if value:
            filters[key] = value
    return filters


def params_to_search_body(params):
    filters = {}
    for key in ("source_project", "source_kind", "author_handle", "domain", "date_from", "date_to", "has_media", "has_ocr"):
        value = params.get(key, [""])[0].strip()
        if value:
            filters[key] = value
    return {
        "query": params.get("q", [""])[0],
        "mode": params.get("mode", ["hybrid"])[0],
        "limit": params.get("limit", ["20"])[0],
        "rerank": params.get("rerank", ["sync"])[0],
        "filters": filters,
        "include": as_list(params.get("include", [])),
    }


def ch_filter_where(filters):
    clauses = []
    exact_map = {
        "source_projects": "source_project",
        "source_kinds": "source_kind",
        "domains": "domain",
        "topics": "topics",
        "entities": "entities",
    }
    for key, column in exact_map.items():
        values = filters.get(key) or []
        if not values:
            continue
        if column in {"topics", "entities"}:
            quoted = ", ".join(sql_string(v) for v in values)
            clauses.append(f"hasAny({column}, [{quoted}])")
        else:
            quoted = ", ".join(sql_string(v) for v in values)
            clauses.append(f"{column} IN ({quoted})")
    handles = filters.get("author_handles") or []
    if handles:
        quoted = ", ".join(sql_string(v.lower().lstrip("@")) for v in handles)
        clauses.append(f"lower(author_handle) IN ({quoted})")
    if "has_media" in filters:
        clauses.append(f"has_media = {1 if filters['has_media'] else 0}")
    if "has_ocr" in filters:
        clauses.append(f"has_ocr = {1 if filters['has_ocr'] else 0}")
    if filters.get("date_from"):
        clauses.append(f"captured_at >= parseDateTimeBestEffort({sql_string(filters['date_from'])})")
    if filters.get("date_to"):
        clauses.append(f"captured_at <= parseDateTimeBestEffort({sql_string(filters['date_to'])})")
    return " AND ".join(clauses) if clauses else "1"


def typesense_string(value):
    text = str(value).replace("\\", "\\\\").replace("`", "\\`")
    return f"`{text}`"


def typesense_filter_by(filters):
    clauses = []
    list_map = {
        "source_projects": "source_projects",
        "source_kinds": "source_kind",
        "author_handles": "author_handle",
        "domains": "link_hosts",
        "topics": "topics",
        "entities": "entities",
    }
    for key, field in list_map.items():
        values = filters.get(key) or []
        if not values:
            continue
        if key == "author_handles":
            values = [v.lstrip("@") for v in values]
        clauses.append(f"{field}:=[{','.join(typesense_string(v) for v in values)}]")
    for key in ("has_ocr",):
        if key in filters:
            clauses.append(f"{key}:={str(bool(filters[key])).lower()}")
    if "has_media" in filters:
        clauses.append(f"has_screenshot:={str(bool(filters['has_media'])).lower()}")
    if filters.get("date_from"):
        epoch = date_to_epoch(filters["date_from"], start=True)
        if epoch is not None:
            clauses.append(f"captured_at:>={epoch}")
    if filters.get("date_to"):
        epoch = date_to_epoch(filters["date_to"], start=False)
        if epoch is not None:
            clauses.append(f"captured_at:<={epoch}")
    return " && ".join(clauses)


def date_to_epoch(value, start=True):
    import datetime
    text = str(value).strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            dt = datetime.datetime.fromisoformat(text)
            if not start:
                dt = dt.replace(hour=23, minute=59, second=59)
        else:
            dt = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return int(dt.timestamp())
    except ValueError:
        return None


def elapsed_ms(started):
    return round((time.perf_counter() - started) * 1000, 2)


def structured_warning(stage, reason, severity="warn", detail=None):
    item = {"stage": stage, "reason": reason, "severity": severity}
    if detail not in (None, ""):
        item["detail"] = detail
    return item


def structured_branch_error(branch, error, reason="branch_error", severity="warn", detail=None):
    item = structured_warning(branch, reason, severity, detail if detail is not None else error)
    item["branch"] = branch
    item["error"] = str(error)
    return item


def qdrant_filter(filters):
    must = []
    list_map = {
        "source_projects": "source_project",
        "source_kinds": "source_kind",
        "domains": "domain",
        "author_handles": "author_handle",
        "topics": "topics",
        "entities": "entities",
    }
    for key, field in list_map.items():
        values = filters.get(key) or []
        if not values:
            continue
        if key == "author_handles":
            values = [v.lstrip("@") for v in values]
        if len(values) == 1:
            must.append({"key": field, "match": {"value": values[0]}})
        else:
            must.append({"key": field, "match": {"any": values}})
    if "has_media" in filters:
        must.append({"key": "has_media", "match": {"value": bool(filters["has_media"])}})
    date_from = filters.get("date_from")
    date_to = filters.get("date_to")
    if date_from and date_from == date_to and re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_from):
        must.append({"key": "captured_at_day", "match": {"value": date_from}})
    return {"must": must} if must else None


def derive_lookup_keys(query):
    q = query.strip()
    if not q:
        return []
    keys = []
    if re.match(r"^(post|account|media|search|capture|user_input|web_document)/", q):
        keys.append(q)
    status = re.search(r"(?:x|twitter)\.com/[^/\s]+/status/(\d+)", q)
    if status:
        keys.append(f"post/{status.group(1)}")
    if re.fullmatch(r"\d{12,25}", q):
        keys.append(f"post/{q}")
    if re.fullmatch(r"@?[A-Za-z0-9_]{1,30}", q):
        keys.append(f"account/{q.lower().lstrip('@')}")
    seen = set()
    return [key for key in keys if not (key in seen or seen.add(key))]


def new_candidate(evidence_id):
    return {
        "evidence_id": evidence_id,
        "branch_ranks": {},
        "branch_scores": {},
        "sources": {},
        "rrf_score": 0.0,
        "final_score": 0.0,
    }


def add_candidate(candidates, evidence_id, branch, rank, score=None, payload=None):
    if not evidence_id:
        return
    candidate = candidates.setdefault(evidence_id, new_candidate(evidence_id))
    existing = candidate["branch_ranks"].get(branch)
    if existing is None or rank < existing:
        candidate["branch_ranks"][branch] = rank
        if score is not None:
            candidate["branch_scores"][branch] = score
        if payload is not None:
            candidate["sources"][branch] = payload


def exact_candidates(query, filters, branch_limit):
    rows = []
    candidates = []
    errors = []
    lookup_keys = derive_lookup_keys(query)
    for key in lookup_keys[:5]:
        try:
            value = http_json(f"{NORMALIZER_URL}/lookup?{urllib.parse.urlencode({'key': key})}", timeout=10)
            evidence_id = value.get("id") or value.get("value", {}).get("evidence_id")
            if evidence_id:
                candidates.append({"evidence_id": evidence_id, "lookup_key": key, "lookup": value})
        except DashboardError as exc:
            errors.append({"branch": "exact", "key": key, "error": exc.message})
    if query:
        where = ch_filter_where(filters)
        q_sql = sql_string(query)
        handle_sql = sql_string(query.lower().lstrip("@"))
        rows = optional_ch_data(
            f"""
            SELECT evidence_id, event_id, source_kind, source_project, canonical_url, author_handle,
                   title, substring(text, 1, 1200) AS text, captured_at, ingested_at
            FROM evidence_events
            WHERE ({where}) AND (
              evidence_id = {q_sql}
              OR canonical_url = {q_sql}
              OR lower(author_handle) = {handle_sql}
            )
            ORDER BY ingested_at DESC
            LIMIT {branch_limit}
            """
        )
    for row in rows:
        candidates.append({"evidence_id": row.get("evidence_id"), "row": row})
    return candidates, errors


def typesense_candidates(query, filters, branch_limit):
    q = query.strip() or "*"
    search = {
        "q": q,
        "query_by": "text,canonical_url,author_handle,author_name,entities,topics,links",
        "per_page": str(min(branch_limit, 100)),
        "page": "1",
        "prioritize_exact_match": "true",
        "exhaustive_search": "true",
    }
    filter_by = typesense_filter_by(filters)
    if filter_by:
        search["filter_by"] = filter_by
    url = f"{TYPESENSE_URL}/collections/evidence_posts/documents/search?{urllib.parse.urlencode(search)}"
    data = http_json(url, headers={"X-TYPESENSE-API-KEY": TYPESENSE_KEY}, timeout=20)
    return data.get("hits", []), data


def embed_search_query(query, model="text"):
    body = {
        "inputs": [query],
        "model": model,
        "prompt": RESEARCH_QUERY_EMBEDDING_PROMPT,
        "normalize": True,
        "batch_size": 1,
    }
    data = http_json_post(
        f"{LOCAL_INFERENCE_URL}/embed",
        body,
        headers={"X-Caller": "web-osint-dashboard-search"},
        timeout=None,
    )
    rows = data.get("data") or []
    if not rows:
        raise DashboardError(502, "local-inference embedding service returned no vectors")
    return rows[0].get("embedding"), data


def qdrant_vector_candidates(vector, vector_name, filters, branch_limit):
    body = {
        "vector": {"name": vector_name, "vector": vector},
        "limit": branch_limit,
        "with_payload": True,
        "with_vector": False,
    }
    qfilter = qdrant_filter(filters)
    if qfilter:
        body["filter"] = qfilter
    data = http_json_post(
        f"{QDRANT_URL}/collections/{QDRANT_COLLECTION}/points/search",
        body,
        timeout=RESEARCH_SEARCH_TIMEOUT_SECONDS,
    )
    return data.get("result", []), data


def hydrate_evidence(evidence_ids):
    if not evidence_ids:
        return {}
    chunks = []
    for idx in range(0, len(evidence_ids), 80):
        ids = evidence_ids[idx:idx + 80]
        quoted = ", ".join(sql_string(eid) for eid in ids)
        chunks.extend(optional_ch_data(
            f"""
            SELECT
              evidence_id,
              argMax(event_id, ingested_at) AS event_id,
              argMax(collector_run_id, ingested_at) AS collector_run_id,
              argMax(source_project, ingested_at) AS source_project,
              argMax(capture_method, ingested_at) AS capture_method,
              argMax(source_kind, ingested_at) AS source_kind,
              argMax(canonical_url, ingested_at) AS canonical_url,
              argMax(author_handle, ingested_at) AS author_handle,
              argMax(domain, ingested_at) AS domain,
              argMax(title, ingested_at) AS title,
              argMax(text, ingested_at) AS text,
              argMax(topics, ingested_at) AS topics,
              argMax(entities, ingested_at) AS entities,
              argMax(links, ingested_at) AS links,
              argMax(has_media, ingested_at) AS has_media,
              argMax(has_ocr, ingested_at) AS has_ocr,
              argMax(posted_at, ingested_at) AS posted_at,
              max(captured_at) AS latest_captured_at,
              max(ingested_at) AS latest_ingested_at
            FROM evidence_events
            WHERE evidence_id IN ({quoted})
            GROUP BY evidence_id
            """
        ))
    return {row.get("evidence_id"): row for row in chunks}


def document_for_rerank(hit):
    parts = [
        hit.get("title") or "",
        hit.get("snippet") or "",
        hit.get("canonical_url") or "",
        " ".join(hit.get("topics") or []),
        " ".join(hit.get("entities") or []),
    ]
    return "\n".join(part for part in parts if part)[:2200]


def apply_rerank(query, hits, rerank_limit):
    if not query or not hits or rerank_limit <= 0:
        return {"enabled": False, "elapsed_ms": 0, "model": "", "results": []}
    slice_hits = hits[:rerank_limit]
    documents = [document_for_rerank(hit) for hit in slice_hits]
    data = http_json_post(
        f"{LOCAL_INFERENCE_URL}/rerank",
        {"query": query, "documents": documents, "normalize": False},
        headers={"X-Caller": "web-osint-dashboard-search"},
        timeout=None,
    )
    for rank, item in enumerate(data.get("results", []), start=1):
        idx = item.get("index")
        if idx is None or idx >= len(slice_hits):
            continue
        hit = slice_hits[idx]
        hit["scores"]["rerank"] = item.get("score")
        hit["scores"]["branches"]["rerank"] = item.get("score")
        hit["scores"]["branch_ranks"]["rerank"] = rank
        hit["scores"]["fused"] += RRF_BRANCH_WEIGHTS["rerank"] / (RRF_K + rank)
        hit["scores"]["final"] = hit["scores"]["fused"]
    hits.sort(key=lambda row: row["scores"]["final"], reverse=True)
    return {
        "enabled": True,
        "elapsed_ms": data.get("elapsed_ms", 0),
        "model": data.get("model", ""),
        "results": [
            {
                "evidence_id": slice_hits[item.get("index", 0)].get("evidence_id"),
                "rank": rank,
                "score": item.get("score"),
            }
            for rank, item in enumerate(data.get("results", []), start=1)
            if item.get("index") is not None and item.get("index") < len(slice_hits)
        ],
    }


def research_search(body):
    total_started = time.perf_counter()
    trace_id = str(body.get("trace_id") or uuid.uuid4())
    query = str(body.get("query", "") or "").strip()
    if not query:
        raise DashboardError(400, "query is required")
    mode = str(body.get("mode") or "hybrid").strip().lower()
    if mode not in {"hybrid", "keyword", "semantic", "visual", "precision"}:
        mode = "hybrid"
    limit = clamp_int(body.get("limit"), 20, 1, RESEARCH_SEARCH_MAX_LIMIT)
    branch_limit = min(RESEARCH_BRANCH_LIMIT, max(limit * 4, 20))
    filters = normalize_search_filters(body.get("filters") or {})
    rerank_mode = str(body.get("rerank") or ("sync" if mode == "precision" else "off")).lower()
    if mode == "precision":
        rerank_mode = "sync"
    include = set(as_list(body.get("include")))

    candidates = {}
    branch_counts = {}
    branch_errors = []
    warnings = []
    timings_ms = {}
    trace = []
    embedding_meta = None

    started = time.perf_counter()
    exact_rows, errors = exact_candidates(query, filters, branch_limit)
    timings_ms["exact"] = elapsed_ms(started)
    branch_errors.extend(
        structured_branch_error(err.get("branch", "exact"), err.get("error", ""), reason="lookup_error", detail=err)
        for err in errors
    )
    branch_counts["exact"] = len(exact_rows)
    for rank, row in enumerate(exact_rows, start=1):
        add_candidate(candidates, row.get("evidence_id"), "exact", rank, 1.0, row)

    if mode in {"hybrid", "keyword", "precision"}:
        started = time.perf_counter()
        try:
            hits, metadata = typesense_candidates(query, filters, branch_limit)
            branch_counts["keyword"] = len(hits)
            timings_ms["keyword"] = elapsed_ms(started)
            trace.append({"branch": "keyword", "found": metadata.get("found"), "search_time_ms": metadata.get("search_time_ms")})
            if not hits:
                warnings.append(structured_warning("keyword", "no_points", "info", "Typesense returned no keyword candidates"))
            for rank, hit in enumerate(hits, start=1):
                doc = hit.get("document") or {}
                add_candidate(candidates, doc.get("id"), "keyword", rank, hit.get("text_match"), hit)
        except DashboardError as exc:
            timings_ms["keyword"] = elapsed_ms(started)
            branch_errors.append(structured_branch_error("keyword", exc.message, reason="branch_unavailable"))

    if mode in {"hybrid", "semantic", "visual", "precision"}:
        try:
            vector_model = "vl" if mode == "visual" else "text"
            started = time.perf_counter()
            vector, embedding_meta = embed_search_query(query, vector_model)
            timings_ms["query_embedding"] = elapsed_ms(started)
            vector_branches = ["text_dense", "ocr_dense", "caption_dense", "account_dense"]
            if mode == "visual":
                vector_branches = ["vl_image_dense", "caption_dense", "ocr_dense", "text_dense"]
            for branch in vector_branches:
                started = time.perf_counter()
                try:
                    rows, metadata = qdrant_vector_candidates(vector, branch, filters, branch_limit)
                    branch_counts[branch] = len(rows)
                    timings_ms[f"qdrant_{branch}"] = elapsed_ms(started)
                    trace.append({"branch": branch, "time": metadata.get("time"), "rows": len(rows)})
                    if not rows:
                        warnings.append(structured_warning(f"qdrant_{branch}", "no_points", "info", f"{branch} returned no candidates"))
                    for rank, row in enumerate(rows, start=1):
                        payload = row.get("payload") or {}
                        add_candidate(candidates, payload.get("evidence_id"), branch, rank, row.get("score"), row)
                except DashboardError as exc:
                    timings_ms[f"qdrant_{branch}"] = elapsed_ms(started)
                    branch_errors.append(structured_branch_error(branch, exc.message, reason="branch_unavailable"))
        except DashboardError as exc:
            timings_ms.setdefault("query_embedding", 0)
            branch_errors.append(structured_branch_error("embedding", exc.message, reason="embedding_unavailable"))

    started = time.perf_counter()
    for candidate in candidates.values():
        total = 0.0
        for branch, rank in candidate["branch_ranks"].items():
            total += RRF_BRANCH_WEIGHTS.get(branch, 1.0) / (RRF_K + rank)
        candidate["rrf_score"] = total
        candidate["final_score"] = total
    timings_ms["fusion"] = elapsed_ms(started)

    ranked = sorted(candidates.values(), key=lambda row: row["final_score"], reverse=True)
    started = time.perf_counter()
    hydrated = hydrate_evidence([row["evidence_id"] for row in ranked[: max(limit, RESEARCH_RERANK_LIMIT)]])
    timings_ms["hydration"] = elapsed_ms(started)
    expected_hydration = len(ranked[: max(limit, RESEARCH_RERANK_LIMIT)])
    if expected_hydration and len(hydrated) < expected_hydration:
        warnings.append(
            structured_warning(
                "hydration",
                "hydration_partial",
                "warn",
                {"expected": expected_hydration, "hydrated": len(hydrated)},
            )
        )
    hits = []
    for candidate in ranked:
        row = hydrated.get(candidate["evidence_id"], {})
        if not row:
            for source in candidate["sources"].values():
                doc = source.get("document") if isinstance(source, dict) else None
                payload = source.get("payload") if isinstance(source, dict) else None
                if doc:
                    row = {
                        "evidence_id": doc.get("id"),
                        "source_kind": doc.get("source_kind"),
                        "source_project": ", ".join(doc.get("source_projects") or []),
                        "canonical_url": doc.get("canonical_url"),
                        "author_handle": doc.get("author_handle"),
                        "title": doc.get("title") or "",
                        "text": doc.get("text") or "",
                        "topics": doc.get("topics") or [],
                        "entities": doc.get("entities") or [],
                        "captured_at": doc.get("captured_at"),
                    }
                    break
                if payload:
                    row = payload
                    break
        text = row.get("text") or ""
        snippet = text[:900] + ("..." if len(text) > 900 else "")
        hit = {
            "evidence_id": candidate["evidence_id"],
            "source_kind": row.get("source_kind", ""),
            "source_project": row.get("source_project", ""),
            "title": row.get("title", ""),
            "canonical_url": row.get("canonical_url", ""),
            "author_handle": row.get("author_handle", ""),
            "domain": row.get("domain", ""),
            "snippet": snippet,
            "topics": row.get("topics") or [],
            "entities": row.get("entities") or [],
            "links": row.get("links") or [],
            "has_media": bool(row.get("has_media")) if row.get("has_media") is not None else None,
            "has_ocr": bool(row.get("has_ocr")) if row.get("has_ocr") is not None else None,
            "posted_at": row.get("posted_at"),
            "captured_at": row.get("captured_at") or row.get("latest_captured_at"),
            "ingested_at": row.get("ingested_at") or row.get("latest_ingested_at"),
            "scores": {
                "final": candidate["final_score"],
                "fused": candidate["rrf_score"],
                "branches": candidate["branch_scores"],
                "branch_ranks": candidate["branch_ranks"],
            },
        }
        if "ranking_trace" in include:
            hit["ranking_trace"] = candidate["sources"]
        hits.append(hit)

    rerank = {"enabled": False}
    if rerank_mode in {"sync", "true", "1", "yes"} and hits:
        started = time.perf_counter()
        try:
            rerank = apply_rerank(query, hits, min(RESEARCH_RERANK_LIMIT, limit, len(hits)))
            timings_ms["rerank"] = elapsed_ms(started)
        except DashboardError as exc:
            timings_ms["rerank"] = elapsed_ms(started)
            rerank = {"enabled": False, "error": exc.message}
            branch_errors.append(structured_branch_error("rerank", exc.message, reason="rerank_unavailable"))
    else:
        timings_ms["rerank"] = 0

    timings_ms["total"] = elapsed_ms(total_started)
    degraded = any((err.get("severity") or "warn") != "info" for err in branch_errors)

    return {
        "trace_id": trace_id,
        "query": query,
        "mode": mode,
        "filters": filters,
        "filters_applied": filters,
        "limit": limit,
        "returned": len(hits[:limit]),
        "candidate_count": len(candidates),
        "degraded": degraded,
        "warnings": warnings,
        "branch_counts": branch_counts,
        "branch_errors": branch_errors,
        "timings_ms": timings_ms,
        "embedding": {
            "model": embedding_meta.get("model") if embedding_meta else "",
            "dimension": embedding_meta.get("dimension") if embedding_meta else 0,
            "elapsed_ms": embedding_meta.get("elapsed_ms") if embedding_meta else 0,
        },
        "rerank": rerank,
        "rerank_used": bool(rerank.get("enabled")),
        "trace": trace if "ranking_trace" in include else [],
        "hits": hits[:limit],
    }


def safe_clickhouse_query(raw):
    query = (raw or "").strip()
    if not query:
        raise DashboardError(400, "query is required")
    if ";" in query.rstrip(";"):
        raise DashboardError(400, "only one statement is allowed")
    query = query.rstrip(";").strip()
    lower = re.sub(r"\s+", " ", query.lower())
    first = lower.split(" ", 1)[0]
    if not lower.startswith(SAFE_SQL_PREFIXES):
        raise DashboardError(400, "only read-only SELECT/WITH/SHOW/DESCRIBE/EXISTS queries are allowed")
    tokens = set(re.findall(r"[a-z_]+", lower))
    if tokens & BLOCKED_SQL_WORDS:
        raise DashboardError(400, "query contains a blocked keyword")
    if first in {"select", "with"} and " limit " not in f" {lower} ":
        query += "\nLIMIT 200"
    return ch_query(query)


def clickhouse_proxy(path, query=""):
    ch_path = path.removeprefix("/clickhouse") or "/"
    url = CLICKHOUSE_URL + ch_path
    if query:
        url += "?" + query
    request = urllib.request.Request(url)
    if CLICKHOUSE_PASSWORD:
        token = base64.b64encode(f"{CLICKHOUSE_USER}:{CLICKHOUSE_PASSWORD}".encode()).decode()
        request.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = response.read()
            content_type = response.headers.get("Content-Type") or mimetypes.guess_type(ch_path)[0] or "application/octet-stream"
            content_encoding = response.headers.get("Content-Encoding")
            return payload, content_type, content_encoding
    except urllib.error.HTTPError as exc:
        detail = exc.read()[:2000]
        raise DashboardError(exc.code, detail.decode("utf-8", errors="replace"))
    except Exception as exc:
        raise DashboardError(502, f"ClickHouse proxy failed: {exc}")


def redpanda_status():
    try:
        topics = http_json(f"{REDPANDA_PROXY_URL}/topics")
    except DashboardError as exc:
        topics = {"error": exc.message}
    try:
        partitions = http_json(f"{REDPANDA_ADMIN_URL}/v1/partitions")
    except DashboardError as exc:
        partitions = [{"error": exc.message}]
    try:
        brokers = http_json(f"{REDPANDA_ADMIN_URL}/v1/brokers")
    except DashboardError as exc:
        brokers = [{"error": exc.message}]

    topic_set = set(topics if isinstance(topics, list) else [])
    topic_rows = {}
    for topic in topic_set:
        topic_rows[topic] = {
            "topic": topic,
            "namespace": "kafka",
            "partitions": 0,
            "leaders": [],
            "cores": [],
            "materialized_partitions": 0,
            "internal": topic.startswith("__"),
        }
    for part in partitions if isinstance(partitions, list) else []:
        topic = part.get("topic")
        if not topic:
            continue
        row = topic_rows.setdefault(topic, {
            "topic": topic,
            "namespace": part.get("ns", ""),
            "partitions": 0,
            "leaders": [],
            "cores": [],
            "materialized_partitions": 0,
            "internal": topic.startswith("__") or part.get("ns") != "kafka",
        })
        row["namespace"] = part.get("ns", row.get("namespace", ""))
        row["partitions"] += 1
        leader = part.get("leader")
        core = part.get("core")
        if leader is not None and leader not in row["leaders"]:
            row["leaders"].append(leader)
        if core is not None and core not in row["cores"]:
            row["cores"].append(core)
        if part.get("materialized"):
            row["materialized_partitions"] += 1
    rows = sorted(topic_rows.values(), key=lambda r: (r["internal"], r["topic"]))
    for row in rows:
        row["leaders"] = ",".join(str(x) for x in sorted(row["leaders"]))
        row["cores"] = ",".join(str(x) for x in sorted(row["cores"]))
    try:
        metrics_text = http_text(f"{REDPANDA_ADMIN_URL}/public_metrics", timeout=10)
        metrics = parse_prometheus(metrics_text, (
            "redpanda_application_uptime",
            "redpanda_kafka_consumer_group",
            "redpanda_kafka_partitions",
            "redpanda_kafka_request_bytes_total",
        ))
    except DashboardError as exc:
        metrics = [{"error": exc.message}]
    return {
        "topics": rows,
        "brokers": brokers,
        "partitions": partitions,
        "metrics": metrics,
        "bytes_by_topic": prom_sum(metrics if isinstance(metrics, list) else [], "redpanda_kafka_request_bytes_total", "redpanda_topic"),
        "activity": activity_rows("24h"),
        "normalizer": service_json("normalizer", lambda: http_json(f"{NORMALIZER_URL}/stats")),
        "research_planner": service_json("research_planner", lambda: http_json(f"{RESEARCH_PLANNER_URL}/stats")),
        "pebble": service_json("pebble", lambda: http_json(f"{NORMALIZER_URL}/pebble?limit=80")),
    }


def latest_runs():
    return ch_data(
        """
        SELECT collector_run_id, anyLast(source_project) AS source_project, anyLast(capture_method) AS capture_method,
               min(started_at) AS started_at, max(updated_at) AS updated_at, sum(records_seen) AS records_seen,
               sum(records_emitted) AS records_emitted, max(challenge) AS challenge, max(partial) AS partial
        FROM collector_runs
        GROUP BY collector_run_id
        ORDER BY started_at DESC
        LIMIT 300
        """
    )


class Handler(BaseHTTPRequestHandler):
    server_version = "WebOSINTDashboard/0.1"

    def log_message(self, fmt, *args):
        print("%s - - [%s] %s" % (self.client_address[0], self.log_date_time_string(), fmt % args))

    def send_json(self, value, status=200):
        payload = json_bytes(value)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def send_static(self, route):
        if route == "/":
            route = "/index.html"
        normalized = posixpath.normpath(urllib.parse.unquote(route)).lstrip("/")
        path = (STATIC_DIR / normalized).resolve()
        try:
            path.relative_to(STATIC_DIR.resolve())
        except ValueError:
            raise DashboardError(403, "invalid static path")
        if not path.is_file():
            raise DashboardError(404, "not found")
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        payload = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        try:
            if parsed.path == "/api/health":
                return self.send_json({"ok": True})
            if parsed.path == "/api/live":
                return self.send_json(live_dashboard(params))
            if parsed.path == "/api/overview":
                return self.send_json(overview())
            if parsed.path == "/api/stage/collectors":
                return self.send_json(collector_stage(params))
            if parsed.path == "/api/stage/redpanda":
                return self.send_json(redpanda_status())
            if parsed.path == "/api/stage/filesystem":
                return self.send_json(filesystem_metrics(params.get("frame", ["24h"])[0]))
            if parsed.path == "/api/stage/fs-tree":
                return self.send_json(filesystem_tree(params))
            if parsed.path == "/api/stage/fs-file":
                result = filesystem_file(params)
                if result.get("mode") == "binary":
                    file_path = result["path"]
                    payload = file_path.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", result["content_type"])
                    self.send_header("Cache-Control", "private, max-age=300")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                return self.send_json(result)
            if parsed.path == "/api/stage/pebble":
                return self.send_json(pebble_stage())
            if parsed.path == "/api/stage/typesense":
                return self.send_json(typesense_stage(params))
            if parsed.path == "/api/stage/models":
                return self.send_json(model_stage(params))
            if parsed.path == "/api/stage/qdrant":
                return self.send_json(qdrant_stage(params))
            if parsed.path == "/api/stage/clickhouse":
                return self.send_json(clickhouse_stage(params))
            if parsed.path == "/api/stage/meaning":
                return self.send_json(meaning_stage(params))
            if parsed.path == "/api/facets":
                return self.send_json(facets())
            if parsed.path == "/api/events":
                return self.send_json(events(params))
            if parsed.path == "/api/raw":
                return self.send_json(raw_event(params))
            if parsed.path == "/api/run":
                return self.send_json(run_trace(params))
            if parsed.path == "/api/runs":
                return self.send_json({"rows": latest_runs()})
            if parsed.path == "/api/search":
                return self.send_json(type_search(params))
            if parsed.path == "/api/research/search":
                return self.send_json(research_search(params_to_search_body(params)))
            if parsed.path == "/api/evidence/inspect":
                return self.send_json(evidence_inspector(params))
            if parsed.path == "/api/lookup":
                return self.send_json(lookup(params))
            if parsed.path == "/api/media-index":
                return self.send_json(media_index(params))
            if parsed.path == "/api/media":
                file_path, content_type = media_response(params)
                payload = file_path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", "private, max-age=300")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            if parsed.path == "/api/qdrant":
                return self.send_json(qdrant_status())
            if parsed.path == "/api/redpanda":
                return self.send_json(redpanda_status())
            if parsed.path.startswith("/clickhouse"):
                payload, content_type, content_encoding = clickhouse_proxy(parsed.path, parsed.query)
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                if content_encoding:
                    self.send_header("Content-Encoding", content_encoding)
                self.send_header("Cache-Control", "private, max-age=60")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            return self.send_static(parsed.path)
        except DashboardError as exc:
            return self.send_json({"error": exc.message}, exc.status)
        except Exception as exc:
            return self.send_json({"error": str(exc)}, 500)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        try:
            length = min(int(self.headers.get("Content-Length", "0") or "0"), 100_000)
            payload = self.rfile.read(length)
            try:
                body = json.loads(payload.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                raise DashboardError(400, "invalid JSON body")
            if parsed.path == "/api/clickhouse/query":
                return self.send_json(safe_clickhouse_query(body.get("query", "")))
            if parsed.path == "/api/research/search":
                return self.send_json(research_search(body))
            raise DashboardError(404, "not found")
        except DashboardError as exc:
            return self.send_json({"error": exc.message}, exc.status)
        except Exception as exc:
            return self.send_json({"error": str(exc)}, 500)


def main():
    host = os.environ.get("DASHBOARD_HOST", "0.0.0.0")
    port = int(os.environ.get("DASHBOARD_PORT", "8091"))
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"web osint dashboard listening on {host}:{port}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
