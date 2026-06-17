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

from PIL import Image, ImageDraw, ImageFont

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from osint_paths import require_mnt_data_root  # noqa: E402
from produce_research_documents import post_event, stable_hash  # noqa: E402


DEFAULT_DATA_ROOT_CANDIDATES = ("/mnt/data/x-research", "/mnt/data/web-osint-platform")
DEFAULT_PANDAPROXY_URL = "http://127.0.0.1:18082"
DEFAULT_CLICKHOUSE_URL = "http://127.0.0.1:18123"
DEFAULT_QDRANT_URL = "http://127.0.0.1:16333"
DEFAULT_DASHBOARD_URLS = ("http://127.0.0.1:18191", "http://192.168.1.16:18191")
CAPTURE_TOPIC = "evidence.capture.events.v1"
VECTOR_NAME = "vl_image_dense"


class CanaryError(RuntimeError):
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
class MediaCanaryState:
    run_id: str
    started_at: str
    status: str = "running"
    finished_at: str = ""
    token: str = ""
    input_image_path: str = ""
    input_sha256: str = ""
    evidence_id: str = ""
    artifact_id: str = ""
    ocr_requested: bool = False
    ocr_completed: bool = False
    ocr_id: str = ""
    ocr_text_artifact_path: str = ""
    ocr_json_artifact_path: str = ""
    ocr_text_contains_token: bool = False
    ocr_text_chars: int = 0
    ocr_block_count: int = 0
    ocr_mean_confidence: float = 0.0
    ocr_qdrant_point_found: bool = False
    vl_requested: bool = False
    vl_completed: bool = False
    vl_embedding_id: str = ""
    qdrant_vl_point_found: bool = False
    dashboard_ocr_search_rank: int | None = None
    duration_ms: int = 0
    errors: list[str] = field(default_factory=list)
    steps: list[StepResult] = field(default_factory=list)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


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
            return require_mnt_data_root(path)
    return require_mnt_data_root(candidates[0] or DEFAULT_DATA_ROOT_CANDIDATES[0])


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


def request_json(url: str, *, method: str = "GET", body: Any | None = None, timeout: float = 30, auth: tuple[str, str] | None = None) -> Any:
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if auth:
        token = base64.b64encode(f"{auth[0]}:{auth[1]}".encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"Basic {token}"
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:2000]
        raise CanaryError(f"{method} {url} returned HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise CanaryError(f"{method} {url} failed: {exc}") from exc


def sql_string(value: Any) -> str:
    text = str(value)
    return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"


def ch_query(clickhouse_url: str, database: str, user: str, password: str, query: str, timeout: float = 30) -> list[dict[str, Any]]:
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
        timeout=timeout,
        auth=(user, password) if password else None,
    )
    return data.get("data", [])


def write_result(path: Path, state: MediaCanaryState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({**{k: v for k, v in state.__dict__.items() if k != "steps"}, "steps": [s.__dict__ for s in state.steps]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_prometheus(path: Path, state: MediaCanaryState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok = 1 if state.status == "passed" else 0
    labels = f'run_id="{state.run_id}",status="{state.status}"'
    lines = [
        "# HELP web_osint_media_canary_pass Last Web OSINT media canary pass status.",
        "# TYPE web_osint_media_canary_pass gauge",
        f"web_osint_media_canary_pass{{{labels}}} {ok}",
        "# HELP web_osint_media_canary_duration_ms Last Web OSINT media canary duration.",
        "# TYPE web_osint_media_canary_duration_ms gauge",
        f"web_osint_media_canary_duration_ms{{{labels}}} {state.duration_ms}",
        "# HELP web_osint_media_canary_stage Last Web OSINT media canary stage booleans.",
        "# TYPE web_osint_media_canary_stage gauge",
        f'web_osint_media_canary_stage{{stage="ocr_completed"}} {1 if state.ocr_completed else 0}',
        f'web_osint_media_canary_stage{{stage="ocr_qdrant_point"}} {1 if state.ocr_qdrant_point_found else 0}',
        f'web_osint_media_canary_stage{{stage="vl_completed"}} {1 if state.vl_completed else 0}',
        f'web_osint_media_canary_stage{{stage="vl_qdrant_point"}} {1 if state.qdrant_vl_point_found else 0}',
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_step(state: MediaCanaryState, name: str, fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
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


def poll_until(deadline: float, fn: Callable[[], Any], *, interval: float = 2.0) -> Any:
    last_value = None
    while time.time() < deadline:
        last_value = fn()
        if last_value:
            return last_value
        time.sleep(interval)
    return last_value


def draw_canary(path: Path, token: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (1100, 520), "#ffffff")
    draw = ImageDraw.Draw(image)
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    ]
    font = None
    for candidate in font_paths:
        with contextlib.suppress(Exception):
            font = ImageFont.truetype(candidate, 54)
            break
    font = font or ImageFont.load_default()
    lines = [
        "WEB OSINT MEDIA CANARY",
        token,
        "CanaryVisionModel",
        "CanaryOCR score 88.8",
    ]
    y = 64
    for line in lines:
        draw.text((70, y), line, fill="#111111", font=font)
        y += 88
    image.save(path)


def qdrant_scroll(qdrant_url: str, collection: str, must: list[dict[str, Any]]) -> list[dict[str, Any]]:
    body = {"limit": 16, "with_payload": True, "with_vector": False, "filter": {"must": must}}
    data = request_json(f"{qdrant_url.rstrip('/')}/collections/{collection}/points/scroll", method="POST", body=body, timeout=30)
    return data.get("result", {}).get("points", [])


def dashboard_search(dashboard_urls: list[str], query: str, timeout: float) -> tuple[str, dict[str, Any]]:
    body = {"query": query, "mode": "hybrid", "limit": 10, "filters": {"source_project": "canary"}, "rerank": "off"}
    errors = []
    for base in dashboard_urls:
        try:
            return base, request_json(f"{base.rstrip('/')}/api/research/search", method="POST", body=body, timeout=timeout)
        except Exception as exc:
            errors.append(f"{base}: {exc}")
    raise CanaryError("; ".join(errors))


def normalized_token(value: str) -> str:
    return "".join(ch for ch in value.upper() if ch.isalnum())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a Web OSINT media OCR/VL canary.")
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--data-root")
    parser.add_argument("--run-id")
    parser.add_argument("--timeout-seconds", type=int, default=1200)
    parser.add_argument("--pandaproxy-url", default="")
    parser.add_argument("--clickhouse-url", default="")
    parser.add_argument("--clickhouse-database", default="")
    parser.add_argument("--clickhouse-user", default="")
    parser.add_argument("--qdrant-url", default="")
    parser.add_argument("--qdrant-collection", default="")
    parser.add_argument("--dashboard-url", action="append", default=[])
    parser.add_argument("--skip-dashboard", action="store_true")
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
    qdrant_url = args.qdrant_url or env_value("QDRANT_URL", DEFAULT_QDRANT_URL, env_file)
    qdrant_collection = args.qdrant_collection or env_value("QDRANT_COLLECTION", defaults["qdrant_collection"], env_file)
    dashboard_urls = args.dashboard_url or list(DEFAULT_DASHBOARD_URLS)
    run_id = args.run_id or f"media_canary_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}_{secrets.token_hex(3)}"
    token = "MEDIA_CANARY_" + hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:12].upper()
    state = MediaCanaryState(run_id=run_id, started_at=utc_now(), token=token)
    started_at = time.time()
    deadline = started_at + args.timeout_seconds
    result_path = data_root / "canaries" / "media" / "runs" / f"{run_id}.json"
    prom_path = data_root / "metrics" / "media_canary.prom"
    exit_code = 1

    try:
        def create_image() -> dict[str, Any]:
            path = data_root / "canaries" / "media" / "input" / f"{run_id}.png"
            draw_canary(path, token)
            sha = hashlib.sha256(path.read_bytes()).hexdigest()
            state.input_image_path = str(path)
            state.input_sha256 = sha
            state.evidence_id = sha
            state.artifact_id = sha
            return {"path": str(path), "sha256": sha, "token": token}

        run_step(state, "create_synthetic_canary_image", create_image)

        def publish_capture() -> dict[str, Any]:
            event = {
                "schema_version": "v1",
                "collector_run_id": f"media_canary_{run_id}",
                "event_index": 0,
                "source_project": "canary",
                "capture_method": "media_enrichment_canary",
                "captured_at": utc_now(),
                "media": [
                    {
                        "media_id": state.artifact_id,
                        "media_kind": "screenshot",
                        "kind": "screenshot",
                        "local_path": state.input_image_path,
                        "storage_path": state.input_image_path,
                        "mime_type": "image/png",
                        "sha256": state.input_sha256,
                        "caption": f"Media enrichment canary image {token}",
                        "topics": ["media-canary", "web-osint"],
                    }
                ],
                "context": {"canary_run_id": run_id, "token": token},
            }
            raw = post_event(pandaproxy_url, CAPTURE_TOPIC, event)
            return {"topic": CAPTURE_TOPIC, "pandaproxy_response": json.loads(raw) if raw else {}}

        run_step(state, "publish_media_capture_event", publish_capture)

        def media_observed() -> dict[str, Any] | None:
            rows = ch_query(
                clickhouse_url,
                clickhouse_db,
                clickhouse_user,
                clickhouse_password,
                f"""
                SELECT evidence_id, has_media, has_ocr
                FROM evidence_events
                WHERE source_kind = 'media'
                  AND evidence_id = {sql_string(state.evidence_id)}
                ORDER BY ingested_at DESC
                LIMIT 1
                """,
            )
            return {"rows": rows} if rows else None

        observed = poll_until(deadline, media_observed)
        if not observed:
            raise CanaryError("ClickHouse did not observe synthetic media evidence")
        state.steps.append(StepResult("poll_clickhouse_media_observed", True, 0, observed))

        def ocr_completed() -> dict[str, Any] | None:
            req = ch_query(
                clickhouse_url,
                clickhouse_db,
                clickhouse_user,
                clickhouse_password,
                f"SELECT count() AS rows FROM media_ocr_results WHERE source_sha256 = {sql_string(state.input_sha256)}",
            )
            state.ocr_requested = bool(req and int(req[0].get("rows") or 0) > 0)
            rows = ch_query(
                clickhouse_url,
                clickhouse_db,
                clickhouse_user,
                clickhouse_password,
                f"""
                SELECT *
                FROM media_ocr_results
                WHERE source_sha256 = {sql_string(state.input_sha256)}
                  AND status = 'completed'
                ORDER BY created_at DESC
                LIMIT 1
                """,
            )
            if not rows:
                return None
            row = rows[0]
            state.ocr_completed = True
            state.ocr_id = row.get("ocr_id", "")
            state.ocr_text_artifact_path = row.get("text_artifact_path", "")
            state.ocr_json_artifact_path = row.get("json_artifact_path", "")
            state.ocr_text_chars = int(row.get("text_chars") or 0)
            state.ocr_block_count = int(row.get("block_count") or 0)
            state.ocr_mean_confidence = float(row.get("mean_confidence") or 0.0)
            text = Path(state.ocr_text_artifact_path).read_text(encoding="utf-8", errors="replace") if state.ocr_text_artifact_path else ""
            state.ocr_text_contains_token = normalized_token(token) in normalized_token(text)
            return {"row": row, "contains_token": state.ocr_text_contains_token, "text_sample": text[:500]}

        ocr = poll_until(deadline, ocr_completed, interval=3.0)
        if not ocr:
            raise CanaryError("media OCR did not complete before timeout")
        if not state.ocr_text_contains_token:
            raise CanaryError("OCR completed but did not contain the canary token")
        state.steps.append(StepResult("poll_media_ocr_completed", True, 0, ocr))

        def ocr_vector() -> dict[str, Any] | None:
            points = qdrant_scroll(
                qdrant_url,
                qdrant_collection,
                [
                    {"key": "evidence_id", "match": {"value": state.evidence_id}},
                    {"key": "embedding_vector_names", "match": {"any": ["ocr_dense"]}},
                ],
            )
            state.ocr_qdrant_point_found = bool(points)
            return {"points": points[:3]} if points else None

        ocr_qdrant = poll_until(deadline, ocr_vector, interval=3.0)
        if not ocr_qdrant:
            raise CanaryError("Qdrant did not contain OCR vector for media canary")
        state.steps.append(StepResult("poll_qdrant_ocr_dense_point", True, 0, ocr_qdrant))

        def vl_completed() -> dict[str, Any] | None:
            req = ch_query(
                clickhouse_url,
                clickhouse_db,
                clickhouse_user,
                clickhouse_password,
                f"SELECT count() AS rows FROM media_vl_embeddings WHERE source_sha256 = {sql_string(state.input_sha256)}",
            )
            state.vl_requested = bool(req and int(req[0].get("rows") or 0) > 0)
            rows = ch_query(
                clickhouse_url,
                clickhouse_db,
                clickhouse_user,
                clickhouse_password,
                f"""
                SELECT *
                FROM media_vl_embeddings
                WHERE source_sha256 = {sql_string(state.input_sha256)}
                  AND status = 'completed'
                ORDER BY created_at DESC
                LIMIT 1
                """,
            )
            if not rows:
                return None
            row = rows[0]
            state.vl_completed = True
            state.vl_embedding_id = row.get("vl_embedding_id", "")
            return {"row": row}

        vl = poll_until(deadline, vl_completed, interval=3.0)
        if not vl:
            raise CanaryError("media VL embedding did not complete before timeout")
        state.steps.append(StepResult("poll_media_vl_completed", True, 0, vl))

        def vl_vector() -> dict[str, Any] | None:
            points = qdrant_scroll(
                qdrant_url,
                qdrant_collection,
                [
                    {"key": "artifact_sha256", "match": {"value": state.input_sha256}},
                    {"key": "embedding_vector_names", "match": {"any": [VECTOR_NAME]}},
                ],
            )
            state.qdrant_vl_point_found = bool(points)
            return {"points": points[:3]} if points else None

        vl_qdrant = poll_until(deadline, vl_vector, interval=3.0)
        if not vl_qdrant:
            raise CanaryError("Qdrant did not contain VL image vector for media canary")
        state.steps.append(StepResult("poll_qdrant_vl_image_dense_point", True, 0, vl_qdrant))

        if not args.skip_dashboard:
            def dashboard_check() -> dict[str, Any]:
                base, response = dashboard_search(dashboard_urls, token, timeout=180)
                hits = response.get("hits") or response.get("results") or []
                for idx, hit in enumerate(hits, start=1):
                    if str(hit.get("evidence_id")) == state.evidence_id:
                        state.dashboard_ocr_search_rank = idx
                        return {"dashboard_url": base, "rank": idx, "returned": len(hits), "warnings": response.get("warnings", [])}
                raise CanaryError("dashboard OCR search did not return the media canary")

            run_step(state, "dashboard_ocr_search", dashboard_check)

        state.status = "passed"
        exit_code = 0
    except Exception as exc:
        state.status = "failed"
        state.errors.append(str(exc))
        exit_code = 1
    finally:
        state.finished_at = utc_now()
        state.duration_ms = int((time.time() - started_at) * 1000)
        write_result(result_path, state)
        write_prometheus(prom_path, state)
        print(json.dumps({"status": state.status, "run_id": state.run_id, "result_path": str(result_path), "errors": state.errors}, ensure_ascii=False))

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
