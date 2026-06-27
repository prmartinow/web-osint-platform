#!/usr/bin/env python3
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


def require_env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise SystemExit(f"Missing {name}")
    return value


CLICKHOUSE_URL = require_env("CLICKHOUSE_URL").rstrip("/")
CLICKHOUSE_DATABASE = os.environ.get("CLICKHOUSE_DATABASE", "web_osint")
CLICKHOUSE_USER = os.environ.get("CLICKHOUSE_USER", "web_osint")
CLICKHOUSE_PASSWORD = os.environ.get("CLICKHOUSE_PASSWORD", "")
LIMIT = int(os.environ.get("SEMANTIC_BACKFILL_LIMIT", "0"))
PRODUCER_NAME = "deterministic_semantic_backfill"
PRODUCER_VERSION = "0.1.0"
TAXONOMY_VERSION = 1


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def stable_hash(*parts: str) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(str(part).encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()


def short_id(prefix: str, *parts: str) -> str:
    return f"{prefix}_{stable_hash(*parts)[:24]}"


def slug_label(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return value.strip("_")


def contains_any(value: str, *needles: str) -> bool:
    lower = value.lower()
    return any(needle.lower() in lower for needle in needles)


def as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value in (None, ""):
        return []
    return [str(value).strip()]


def json_string(value: Any) -> str:
    return json.dumps(value or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def ch_request(query: str, body: bytes | None = None) -> bytes:
    params = {
        "database": CLICKHOUSE_DATABASE,
        "query": query,
        "date_time_input_format": "best_effort",
        "input_format_null_as_default": "1",
    }
    url = CLICKHOUSE_URL + "/?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, data=body, method="POST" if body is not None else "GET")
    if CLICKHOUSE_PASSWORD:
        raw = f"{CLICKHOUSE_USER}:{CLICKHOUSE_PASSWORD}".encode("utf-8")
        req.add_header("Authorization", "Basic " + base64.b64encode(raw).decode("ascii"))
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:2000]
        raise RuntimeError(f"ClickHouse HTTP {exc.code}: {detail}") from exc


def ch_rows(query: str) -> list[dict[str, Any]]:
    raw = ch_request(query)
    rows = []
    for line in raw.decode("utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def load_evidence() -> list[dict[str, Any]]:
    limit = f"LIMIT {LIMIT}" if LIMIT > 0 else ""
    return ch_rows(
        f"""
SELECT
  evidence_id,
  argMax(event_id, evidence_captured_at) AS event_id,
  argMax(source_kind, evidence_captured_at) AS source_kind,
  argMax(source_project, evidence_captured_at) AS source_project,
  argMax(capture_method, evidence_captured_at) AS capture_method,
  argMax(canonical_url, evidence_captured_at) AS canonical_url,
  argMax(domain, evidence_captured_at) AS domain,
  argMax(title, evidence_captured_at) AS title,
  argMax(evidence_text, evidence_captured_at) AS text,
  argMax(topics, evidence_captured_at) AS topics,
  argMax(entities, evidence_captured_at) AS entities,
  argMax(links, evidence_captured_at) AS links,
  max(has_media) AS has_media,
  max(has_ocr) AS has_ocr,
  max(evidence_captured_at) AS captured_at,
  argMax(raw_json, evidence_captured_at) AS raw_json
FROM (
  SELECT *, text AS evidence_text, captured_at AS evidence_captured_at
  FROM evidence_events
)
GROUP BY evidence_id
ORDER BY captured_at ASC, evidence_id ASC
{limit}
FORMAT JSONEachRow
"""
    )


def source_label(source_kind: str) -> str:
    mapping = {
        "x_post": "source.x.post",
        "x_account": "source.x.profile",
        "x_page": "source.x.page",
        "google_search_page": "source.google.serp",
        "search_result": "source.search.result",
        "web_page": "source.web.page",
        "user_input": "source.user.input",
        "media": "source.media",
        "capture": "source.capture",
    }
    return mapping.get(source_kind, f"source.{slug_label(source_kind)}" if source_kind else "")


def modality_labels(row: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    haystack = " ".join(str(row.get(k) or "") for k in ["source_kind", "domain", "canonical_url", "title", "text"]).lower()
    if row.get("text") or row.get("title"):
        labels.append("modality.text")
    if int(row.get("has_media") or 0) or contains_any(haystack, ".png", ".jpg", ".jpeg", ".webp", ".gif", "image", "screenshot"):
        labels.append("modality.image")
    if contains_any(haystack, "video", ".mp4", ".mov", ".webm"):
        labels.append("modality.video")
    if contains_any(haystack, ".pdf", " pdf"):
        labels.append("modality.pdf")
    if contains_any(haystack, "table", "leaderboard", "rank", "score"):
        labels.append("modality.table")
    if contains_any(haystack, "github.com", ".go", ".py", ".js", "```"):
        labels.append("modality.code")
    return dedupe(labels)


def content_form(row: dict[str, Any]) -> tuple[str, float]:
    source_kind = str(row.get("source_kind") or "")
    mapping = {
        "x_post": ("form.social_post", 1.0),
        "x_account": ("form.social_profile", 1.0),
        "x_page": ("form.social_page", 0.95),
        "google_search_page": ("form.search_page", 0.95),
        "search_result": ("form.search_result", 1.0),
        "media": ("form.media_artifact", 0.95),
        "user_input": ("form.user_note", 1.0),
        "capture": ("form.capture", 0.9),
    }
    if source_kind in mapping:
        return mapping[source_kind]
    haystack = " ".join(str(row.get(k) or "") for k in ["source_kind", "domain", "canonical_url", "title", "text"]).lower()
    domain = str(row.get("domain") or "")
    if ".pdf" in haystack:
        return "form.pdf", 0.94
    if "github.com" in domain and contains_any(haystack, "/blob/", "/tree/"):
        return "form.github_file", 0.9
    if "github.com" in domain:
        return "form.github_repo", 0.84
    if contains_any(haystack, "leaderboard", "rank", "score", "benchmark"):
        return "form.leaderboard", 0.82
    if contains_any(haystack, "docs", "documentation", "api reference", "reference"):
        return "form.docs_page", 0.78
    if contains_any(haystack, "pricing", "price", "$/mo", "free plan", "enterprise plan"):
        return "form.pricing_page", 0.78
    if contains_any(haystack, "model card", "model-card"):
        return "form.model_card", 0.8
    if contains_any(haystack, "blog", "release notes", "announcing", "launching"):
        return "form.blog_post", 0.7
    return "form.web_page", 0.6


def quality_labels(row: dict[str, Any]) -> list[str]:
    labels = []
    if int(row.get("has_ocr") or 0):
        labels.append("quality.has_ocr")
    if row.get("canonical_url") and row.get("source_kind") == "web_page":
        labels.append("quality.direct_web_capture")
    if row.get("source_kind") == "user_input":
        labels.append("quality.user_supplied")
    return labels


def actionability_labels(row: dict[str, Any]) -> list[str]:
    topics = " ".join(as_list(row.get("topics")))
    haystack = " ".join(str(row.get(k) or "") for k in ["source_kind", "title", "text"]) + " " + topics
    labels = []
    if contains_any(haystack, "benchmark", "leaderboard", "score", "rank"):
        labels.append("action.compare")
    if contains_any(haystack, "launch", "release", "announcing", "available", "model card"):
        labels.append("action.verify")
    if row.get("source_kind") == "search_result" or as_list(row.get("links")):
        labels.append("action.collect_more")
    if row.get("source_kind") == "user_input":
        labels.append("action.review")
    return labels


def dedupe(values: list[str]) -> list[str]:
    seen = set()
    out = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def annotation(row: dict[str, Any], family: str, label_id: str, status: str, confidence: float, value: dict[str, Any], created_at: str) -> dict[str, Any]:
    evidence_id = str(row.get("evidence_id") or "")
    raw_json = str(row.get("raw_json") or "")
    input_hash = stable_hash(raw_json)
    activity_id = short_id("act", "semantic_backfill", str(row.get("event_id") or ""), evidence_id, input_hash)
    value_json = json_string(value)
    annotation_id = short_id("ann", evidence_id, family, label_id, value_json, input_hash)
    return {
        "annotation_id": annotation_id,
        "evidence_id": evidence_id,
        "artifact_id": "",
        "chunk_id": "",
        "target_type": "evidence",
        "target_id": evidence_id,
        "selector_type": "whole_document",
        "selector_json": json_string({"selector_type": "whole_document"}),
        "annotation_family": family,
        "label_id": label_id,
        "label_scheme": family,
        "taxonomy_version": TAXONOMY_VERSION,
        "value_json": value_json,
        "confidence": confidence,
        "score_components_json": json_string({"deterministic_signal_score": confidence}),
        "status": status,
        "span_text": "",
        "produced_by_activity_id": activity_id,
        "producer_name": PRODUCER_NAME,
        "producer_version": PRODUCER_VERSION,
        "input_hash": input_hash,
        "created_at": created_at,
    }


def annotations_for(row: dict[str, Any], created_at: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    def add(family: str, label_id: str, status: str, confidence: float, value: dict[str, Any]) -> None:
        if label_id:
            out.append(annotation(row, family, label_id, status, confidence, value, created_at))

    label = source_label(str(row.get("source_kind") or ""))
    add("source", label, "accepted", 1.0, {"source_kind": row.get("source_kind") or ""})

    for label in modality_labels(row):
        add("modality", label, "accepted", 0.95, {"source_kind": row.get("source_kind") or ""})

    label, confidence = content_form(row)
    add("content_form", label, "accepted" if confidence >= 0.95 else "proposed", confidence, {"source_kind": row.get("source_kind") or "", "domain": row.get("domain") or ""})

    for topic in as_list(row.get("topics")):
        topic_slug = slug_label(topic)
        if topic_slug:
            add("topic", f"topic.{topic_slug}", "proposed", 0.72, {"topic_text": topic})

    for entity in as_list(row.get("entities")):
        add("entity", "entity.mentioned", "proposed", 0.7, {"entity_text": entity})

    for label in quality_labels(row):
        add("evidence_quality", label, "accepted", 0.9, {"source_kind": row.get("source_kind") or ""})

    for label in actionability_labels(row):
        add("actionability", label, "proposed", 0.72, {"source_kind": row.get("source_kind") or ""})

    return out


def existing_annotation_ids(ids: list[str]) -> set[str]:
    if not ids:
        return set()
    out: set[str] = set()
    for idx in range(0, len(ids), 1000):
        chunk = ids[idx : idx + 1000]
        values = ", ".join("'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'" for value in chunk)
        rows = ch_rows(f"SELECT annotation_id FROM semantic_annotations WHERE annotation_id IN ({values}) FORMAT JSONEachRow")
        out.update(str(row["annotation_id"]) for row in rows)
    return out


def insert_annotations(rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    payload = ("\n".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in rows) + "\n").encode("utf-8")
    ch_request("INSERT INTO semantic_annotations FORMAT JSONEachRow", payload)


def main() -> int:
    print(f"[{now_iso()}] loading evidence database={CLICKHOUSE_DATABASE}", flush=True)
    evidence_rows = load_evidence()
    created_at = now_iso()
    candidates: list[dict[str, Any]] = []
    for row in evidence_rows:
        candidates.extend(annotations_for(row, created_at))
    existing = existing_annotation_ids([row["annotation_id"] for row in candidates])
    new_rows = [row for row in candidates if row["annotation_id"] not in existing]
    insert_annotations(new_rows)
    print(
        json.dumps(
            {
                "ok": True,
                "evidence_rows": len(evidence_rows),
                "candidate_annotations": len(candidates),
                "existing_annotations": len(existing),
                "inserted_annotations": len(new_rows),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
