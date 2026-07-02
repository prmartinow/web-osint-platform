#!/usr/bin/env python3
"""Local Research UI launch bridge for an operator-owned Rebrowser lane."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


TOPIC = "evidence.capture.events.v1"


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def require_env(name: str) -> str:
    """Read a required env var; fail fast if absent (repo sanitation convention:
    no committed loopback/deployment-path defaults for runtime endpoints)."""
    value = env(name)
    if not value:
        raise RuntimeError(f"Missing required {name}")
    return value


def now_compact() -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())


def json_response(handler: BaseHTTPRequestHandler, status: int, body: dict[str, Any]) -> None:
    data = json.dumps(body, sort_keys=True).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def cdp_json(cdp_url: str, path: str, method: str = "GET", timeout: float = 2.0) -> Any:
    request = urllib.request.Request(cdp_url.rstrip("/") + path, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        text = response.read().decode("utf-8", errors="replace")
    return json.loads(text) if text else {}


def cdp_ready(cdp_url: str) -> bool:
    try:
        cdp_json(cdp_url, "/json/version")
        return True
    except Exception:
        return False


def cdp_port(cdp_url: str) -> str:
    parsed = urllib.parse.urlparse(cdp_url)
    if not parsed.hostname or not parsed.port:
        raise ValueError("REBROWSER_CDP_URL must include host and port")
    if parsed.hostname not in ("127.0.0.1", "localhost"):
        raise ValueError("REBROWSER_CDP_URL must point at a local CDP listener")
    return str(parsed.port)


def wait_for_cdp(cdp_url: str, seconds: float = 15.0) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if cdp_ready(cdp_url):
            return
        time.sleep(0.25)
    raise RuntimeError(f"CDP listener did not become ready at {cdp_url}")


def ensure_browser(seed_url: str = "about:blank") -> None:
    cdp_url = require_env("REBROWSER_CDP_URL")
    if cdp_ready(cdp_url):
        return

    chrome = require_env("REBROWSER_CHROME_BIN")
    profile = Path(env("REBROWSER_PROFILE_DIR", str(Path.home() / "browser-sessions" / "rebrowser-screen-96-profile")))
    display = env("REBROWSER_DISPLAY", ":96")
    log_dir = Path(env("REBROWSER_LOG_DIR", str(Path.home() / "browser-sessions" / "logs")))
    profile.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "rebrowser-screen-96.log"

    args = [
        chrome,
        f"--user-data-dir={profile}",
        "--remote-debugging-address=127.0.0.1",
        f"--remote-debugging-port={cdp_port(cdp_url)}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-dev-shm-usage",
        "--window-position=0,0",
        "--window-size=1920,1080",
        "--no-sandbox",
        seed_url if seed_url.startswith(("http://", "https://")) else "about:blank",
    ]
    child_env = os.environ.copy()
    child_env["DISPLAY"] = display
    with log_path.open("ab") as log:
        subprocess.Popen(args, env=child_env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    wait_for_cdp(cdp_url)


def open_tab(url: str) -> dict[str, Any]:
    cdp_url = require_env("REBROWSER_CDP_URL")
    encoded = urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=%")
    return cdp_json(cdp_url, f"/json/new?{encoded}", method="PUT", timeout=5.0)


def validate_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("seed_url must be an http or https URL")
    return url


def run_rendered_capture(payload: dict[str, Any], session_id: str) -> dict[str, Any]:
    repo = Path(env("WEB_OSINT_REPO_ROOT", str(Path(__file__).resolve().parents[1])))
    data_root = Path(env("WEB_OSINT_DATA_ROOT"))
    pandaproxy = env("PANDAPROXY_URL") or env("REDPANDA_PROXY_URL")
    if not data_root:
        raise RuntimeError("WEB_OSINT_DATA_ROOT is required for rendered capture mode")
    if not pandaproxy:
        raise RuntimeError("PANDAPROXY_URL or REDPANDA_PROXY_URL is required for rendered capture mode")

    seed_url = validate_url(str(payload.get("seed_url") or payload.get("url") or ""))
    project_id = str(payload.get("project_id") or payload.get("project") or "rendered-web").strip() or "rendered-web"
    collector_run_id = f"rebrowser_launch_{now_compact()}_{session_id}"
    output_dir = data_root / "web" / "rebrowser-launch-helper" / time.strftime("%Y%m%d", time.gmtime()) / collector_run_id
    context = {
        "launch_session_id": session_id,
        "return_route": payload.get("return_route") or "",
        "requested_source_id": payload.get("source_id") or "",
        "requested_at": payload.get("requested_at") or "",
    }
    command = [
        "node",
        "collectors/rebrowser-rendered-web/rebrowser_rendered_capture.mjs",
        "--url",
        seed_url,
        "--source-project",
        project_id,
        "--collector-run-id",
        collector_run_id,
        "--cdp-url",
        require_env("REBROWSER_CDP_URL"),
        "--settle-ms",
        env("REBROWSER_LAUNCH_SETTLE_MS", "2500"),
        "--timeout-ms",
        env("REBROWSER_LAUNCH_NAV_TIMEOUT_MS", "60000"),
        "--context-json",
        json.dumps(context, sort_keys=True),
        "--output-dir",
        str(output_dir),
        "--keep-tab",
    ]
    if env("REBROWSER_LAUNCH_ALLOW_X", "false").lower() in ("1", "true", "yes"):
        command.append("--allow-x")

    child_env = os.environ.copy()
    child_env.setdefault("PLAYWRIGHT_MODULE", require_env("PLAYWRIGHT_MODULE"))
    result = subprocess.run(command, cwd=repo, env=child_env, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[-4000:]
        raise RuntimeError(f"rendered capture failed with {result.returncode}: {detail}")
    report = json.loads(result.stdout)
    event = report.get("capture_event")
    if not isinstance(event, dict):
        raise RuntimeError("rendered collector did not return a capture_event")
    event.setdefault("quality", {})["published"] = True
    event.setdefault("context", {})["launch_session_id"] = session_id
    document = (event.get("web_documents") or [{}])[0]
    document_id = str(document.get("document_id") or report.get("document_id") or "")
    key = f"{event.get('collector_run_id')}:{event.get('event_index', 0)}"
    body = json.dumps({"records": [{"key": key, "value": event}]}).encode("utf-8")
    request = urllib.request.Request(
        pandaproxy.rstrip("/") + "/topics/" + TOPIC,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/vnd.kafka.json.v2+json",
            "Accept": "application/vnd.kafka.v2+json",
        },
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        publish_body = response.read().decode("utf-8", errors="replace")
    return {
        "collector_run_id": str(event.get("collector_run_id") or ""),
        "capture_event_id": key,
        "capture_id": key,
        "document_id": document_id,
        "source_evidence_id": f"web_document/{document_id}" if document_id else "",
        "publish_response": json.loads(publish_body) if publish_body else {},
        "artifact_root": str(output_dir),
        "title": str(report.get("title") or document.get("title") or ""),
        "canonical_url": str(report.get("canonical_url") or document.get("canonical_url") or ""),
    }


# In-memory session-state store for async captures. Keyed by session_id; one
# entry per /launch, mutated by the worker thread, read by /status. Bounded to
# the last 100 sessions to avoid unbounded growth in a long-running helper.
SESSIONS: dict[str, dict[str, Any]] = {}


def _prune_sessions() -> None:
    if len(SESSIONS) <= 100:
        return
    # Drop the oldest entries by started_at (preserves the most recent 100).
    for key in sorted(SESSIONS, key=lambda k: SESSIONS[k].get("started_at", ""))[: len(SESSIONS) - 100]:
        SESSIONS.pop(key, None)


def _run_capture_session(session_id: str, payload: dict[str, Any], seed_url: str) -> None:
    """Background worker: open the tab, run the collector, publish. Updates
    SESSIONS[session_id] at each phase so /status can report progress."""
    state = SESSIONS.get(session_id)
    if not state:
        return
    try:
        state["phase"] = "opening"
        ensure_browser(seed_url or "about:blank")
        target = open_tab(seed_url) if seed_url else {}
        state["target_url"] = target.get("url") or seed_url
        mode = env("REBROWSER_LAUNCH_CAPTURE_MODE", "rendered-web").lower()
        if mode in ("rendered-web", "capture", "publish"):
            state["phase"] = "capturing"
            capture = run_rendered_capture(payload, session_id)
            state.update({
                "phase": "publishing",
                "capture_event_id": capture.get("capture_event_id", ""),
                "source_evidence_id": capture.get("source_evidence_id", ""),
                "title": capture.get("title", ""),
                "canonical_url": capture.get("canonical_url", ""),
            })
            state["status"] = "committed"
            state["phase"] = "done"
        else:
            state["status"] = "launched"
            state["phase"] = "done"
    except Exception as exc:
        state["status"] = "failed"
        state["phase"] = "failed"
        state["error"] = str(exc)[:1000]
    finally:
        _prune_sessions()


class Handler(BaseHTTPRequestHandler):
    server_version = "WebOsintRebrowserLaunchHelper/1"

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in ("/healthz", "/ready"):
            ready = cdp_ready(require_env("REBROWSER_CDP_URL"))
            json_response(self, 200, {"ok": True, "cdp_ready": ready})
            return
        # /status?session_id=<id> -- poll an in-flight or finished capture.
        # Lets the launcher return immediately from /launch and lets the caller
        # (research-ui) poll for state instead of holding a long request open.
        if parsed.path == "/status":
            params = urllib.parse.parse_qs(parsed.query)
            session_id = (params.get("session_id", [""])[0] or "").strip()
            if not session_id:
                json_response(self, 400, {"error": "session_id is required"})
                return
            state = SESSIONS.get(session_id)
            if not state:
                json_response(self, 404, {"error": "unknown session_id"})
                return
            json_response(self, 200, dict(state))
            return
        json_response(self, 404, {"error": "not found"})

    def do_POST(self) -> None:
        if urllib.parse.urlparse(self.path).path != "/launch":
            json_response(self, 404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length") or "0")
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            seed_url = str(payload.get("seed_url") or payload.get("url") or "").strip()
            if not seed_url and not payload.get("source_id"):
                raise ValueError("seed_url or source_id is required")
            if seed_url:
                validate_url(seed_url)
            session_id = f"screen96-{now_compact()}"
            # Register the session immediately so /status can report it, then
            # run the actual capture asynchronously. /launch returns at once
            # with status "working"; the caller polls /status.
            SESSIONS[session_id] = {
                "session_id": session_id,
                "status": "working",
                "phase": "opening",
                "seed_url": seed_url,
                "started_at": now_compact(),
                "capture_event_id": "",
                "source_evidence_id": "",
                "title": "",
                "canonical_url": "",
                "error": "",
            }
            threading.Thread(
                target=_run_capture_session,
                args=(session_id, payload, seed_url),
                daemon=True,
            ).start()
            json_response(self, 200, {
                "session_id": session_id,
                "status": "working",
                "phase": "opening",
                "poll_url": f"/status?session_id={urllib.parse.quote(session_id)}",
                # No open_url: the legacy behavior opened a separate VNC/view
                # tab, which leaked a placeholder URL into the research UI. The
                # user is already on the research UI; capture progress is
                # reported via /status polling.
            })
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:1000]
            json_response(self, 502, {"error": f"upstream HTTP {exc.code}", "detail": detail})
        except Exception as exc:
            json_response(self, 500, {"error": str(exc)})

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("%s - %s\n" % (self.log_date_time_string(), fmt % args))


def main() -> int:
    bind = env("REBROWSER_LAUNCH_HELPER_BIND", "127.0.0.1")
    port = int(env("REBROWSER_LAUNCH_HELPER_PORT", "18231"))
    with ThreadingHTTPServer((bind, port), Handler) as server:
        socket.setdefaulttimeout(30)
        server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
