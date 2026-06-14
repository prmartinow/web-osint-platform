#!/usr/bin/env python3
import json
import time
import urllib.request


topic = "evidence.capture.events.v1"
event = {
    "schema_version": "v1",
    "collector_run_id": "smoke_rpc_bootstrap",
    "event_index": 0,
    "source_project": "smoke",
    "capture_method": "manual_smoke",
    "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "page_url": "https://example.com/",
    "page_title": "Smoke Test",
    "context": {"query": "web-osint bootstrap"},
    "posts": [],
    "accounts": [],
    "media": [],
    "links": [],
    "quality": {"challenge": False, "login_prompt_visible": False, "partial": False},
}

body = {
    "records": [
        {
            "key": f"{event['collector_run_id']}:{event['event_index']}",
            "value": event,
        }
    ]
}
req = urllib.request.Request(
    f"http://127.0.0.1:18082/topics/{topic}",
    data=json.dumps(body).encode("utf-8"),
    method="POST",
    headers={
        "Content-Type": "application/vnd.kafka.json.v2+json",
        "Accept": "application/vnd.kafka.v2+json",
    },
)
with urllib.request.urlopen(req, timeout=10) as response:
    print(response.read().decode("utf-8"))

