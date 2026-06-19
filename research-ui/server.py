#!/usr/bin/env python3
import base64
import json
import mimetypes
import os
import posixpath
import re
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

MAX_LIMIT = 200
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


def ch_query(query):
    compact = " ".join(query.strip().split())
    if not compact.lower().startswith(SAFE_SQL_PREFIXES):
        raise ResearchUiError(400, "Only read-only ClickHouse queries are allowed")
    params = {
        "database": CLICKHOUSE_DB,
        "query": query,
        "default_format": "JSON",
        "date_time_output_format": "iso",
    }
    request = urllib.request.Request(CLICKHOUSE_URL + "/?" + urllib.parse.urlencode(params), method="POST")
    if CLICKHOUSE_PASSWORD:
        token = base64.b64encode(f"{CLICKHOUSE_USER}:{CLICKHOUSE_PASSWORD}".encode()).decode()
        request.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:2000]
        raise ResearchUiError(502, f"ClickHouse error {exc.code}: {detail}")
    except Exception as exc:
        raise ResearchUiError(502, f"ClickHouse request failed: {exc}")


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


def artifact_url(path):
    return "/api/artifact?" + urllib.parse.urlencode({"path": path})


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
    }


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


def main():
    host = os.environ.get("RESEARCH_UI_HOST", "127.0.0.1")
    port = int(os.environ.get("RESEARCH_UI_PORT", "18192"))
    server = ThreadingHTTPServer((host, port), ResearchUiHandler)
    print(f"Web OSINT Research UI listening on http://{host}:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
