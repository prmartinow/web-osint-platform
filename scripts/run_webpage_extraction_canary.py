#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from osint_paths import ensure_dir, require_mnt_data_root  # noqa: E402


DEFAULT_URLS = [
    "https://www.boson.ai/blog/higgs-audio-v3-tts",
    "https://www.lmsys.org/blog/2026-06-04-higgs-audio-v3-tts/",
    "https://www.liquid.ai/blog/introducing-lfm2-5-the-next-generation-of-on-device-ai",
]
DEFAULT_DATA_ROOT_CANDIDATES = ("/mnt/data/x-research", "/mnt/data/web-osint-platform")
DEFAULT_DASHBOARD_URLS = ("http://192.168.1.16:18191", "http://127.0.0.1:18191")


@dataclass
class Step:
    name: str
    ok: bool
    duration_ms: int
    detail: dict[str, Any] = field(default_factory=dict)
    error: str = ""


def now_iso() -> str:
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
        raise RuntimeError(f"{method} {url} returned HTTP {exc.code}: {detail}") from exc


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


def run_step(steps: list[Step], name: str, fn):
    started = time.time()
    try:
        detail = fn() or {}
        steps.append(Step(name=name, ok=True, duration_ms=int((time.time() - started) * 1000), detail=detail))
        return detail
    except Exception as exc:
        steps.append(Step(name=name, ok=False, duration_ms=int((time.time() - started) * 1000), error=str(exc)))
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a Web OSINT webpage extraction canary with launch blog URLs.")
    parser.add_argument("--env-file", default=str(ROOT / ".env"))
    parser.add_argument("--url", action="append", default=[])
    parser.add_argument("--data-root")
    parser.add_argument("--pandaproxy-url")
    parser.add_argument("--clickhouse-url")
    parser.add_argument("--clickhouse-database")
    parser.add_argument("--clickhouse-user")
    parser.add_argument("--clickhouse-password")
    parser.add_argument("--dashboard-url", action="append", default=[])
    parser.add_argument("--venv-python")
    parser.add_argument("--timeout-seconds", type=float, default=180)
    args = parser.parse_args()

    env_file = load_env(Path(args.env_file))
    data_root = choose_data_root(args.data_root or env_value("OSINT_DATA_ROOT", "", env_file))
    defaults = deployment_defaults(data_root)
    pandaproxy_url = args.pandaproxy_url or env_value("PANDAPROXY_URL", "http://127.0.0.1:18082", env_file)
    clickhouse_url = args.clickhouse_url or env_value("CLICKHOUSE_URL", "http://127.0.0.1:18123", env_file)
    clickhouse_database = args.clickhouse_database or env_value("CLICKHOUSE_DATABASE", defaults["clickhouse_database"], env_file)
    clickhouse_user = args.clickhouse_user or env_value("CLICKHOUSE_USER", defaults["clickhouse_user"], env_file)
    clickhouse_password = args.clickhouse_password or env_value("CLICKHOUSE_PASSWORD", "", env_file)
    venv_python = args.venv_python or env_value(
        "WEB_OSINT_WEBPAGE_EXTRACTION_PYTHON",
        str(Path(env_value("WEB_OSINT_MODEL_ROOT", "/mnt/data/web-osint-platform", env_file)) / ".venv-webpage-extraction/bin/python"),
        env_file,
    )
    urls = args.url or DEFAULT_URLS
    dashboard_urls = args.dashboard_url or list(DEFAULT_DASHBOARD_URLS)
    run_id = f"webpage_extract_canary_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    started_at = now_iso()
    steps: list[Step] = []
    output_root = ensure_dir(data_root / "canaries" / "webpage_extraction")
    result_path = output_root / f"{run_id}.json"

    env = os.environ.copy()
    env["OSINT_DATA_ROOT"] = str(data_root)
    env["PANDAPROXY_URL"] = pandaproxy_url

    def extract_and_publish() -> dict[str, Any]:
        cmd = [
            venv_python,
            str(ROOT / "workers/webpage-extraction/webpage_extraction_worker.py"),
            "extract-url",
            "--source-project",
            "webpage-extraction-canary",
            "--collector-run-id",
            run_id,
            "--topic-label",
            "launch-blog",
            "--topic-label",
            "webpage-extraction",
            "--pandaproxy-url",
            pandaproxy_url,
            "--publish",
            "--canary",
        ]
        for url in urls:
            cmd.extend(["--url", url])
        proc = subprocess.run(cmd, cwd=str(ROOT), env=env, text=True, capture_output=True, timeout=args.timeout_seconds)
        if proc.returncode != 0:
            raise RuntimeError(f"extract-url failed: {proc.stderr[-2000:] or proc.stdout[-2000:]}")
        payload = json.loads(proc.stdout)
        return {"collector_run_id": payload["collector_run_id"], "results": payload["results"]}

    extraction = run_step(steps, "extract_launch_blog_pages", extract_and_publish)

    deadline = time.time() + args.timeout_seconds

    def clickhouse_seen() -> dict[str, Any] | None:
        rows = ch_query(
            clickhouse_url,
            clickhouse_database,
            clickhouse_user,
            clickhouse_password,
            f"""
            SELECT evidence_id, title, domain, length(text) AS text_len
            FROM evidence_events
            WHERE collector_run_id = {sql_string(run_id)}
              AND source_kind = 'web_page'
            ORDER BY captured_at
            """,
            timeout=20,
        )
        if len(rows) >= min(1, len(urls)):
            return {"rows": rows}
        return None

    def poll_clickhouse() -> dict[str, Any]:
        while time.time() < deadline:
            found = clickhouse_seen()
            if found:
                return found
            time.sleep(2)
        raise RuntimeError("ClickHouse did not observe extracted webpage evidence before timeout")

    clickhouse = run_step(steps, "poll_clickhouse_web_pages", poll_clickhouse)

    def dashboard_search() -> dict[str, Any]:
        body = {"query": "Higgs Audio TTS launch benchmark", "mode": "hybrid", "limit": 5}
        errors = []
        for dashboard_url in dashboard_urls:
            try:
                data = request_json(f"{dashboard_url.rstrip('/')}/api/research/search", method="POST", body=body, timeout=60)
                return {
                    "dashboard_url": dashboard_url,
                    "returned": data.get("returned"),
                    "degraded": data.get("degraded"),
                    "top_hit": (data.get("hits") or [{}])[0],
                }
            except Exception as exc:
                errors.append(f"{dashboard_url}: {exc}")
        raise RuntimeError("; ".join(errors))

    dashboard = run_step(steps, "dashboard_search_smoke", dashboard_search)

    result = {
        "run_id": run_id,
        "status": "passed",
        "started_at": started_at,
        "finished_at": now_iso(),
        "urls": urls,
        "extraction": extraction,
        "clickhouse": clickhouse,
        "dashboard": dashboard,
        "steps": [step.__dict__ for step in steps],
    }
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "run_id": run_id, "result_path": str(result_path), "clickhouse_rows": len(clickhouse["rows"])}, indent=2))


if __name__ == "__main__":
    main()
