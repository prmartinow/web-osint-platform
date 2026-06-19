# Rebrowser Rendered Web Collector

Captures browser-rendered web/blog/document pages from the preserved Rebrowser
CDP session and publishes them as ordinary `web_documents` capture events.

This collector is for pages where the browser-rendered view is the evidence:
JavaScript pages, interactive launch blogs, pages with visual/layout context,
or any source where static HTTP extraction is sparse.

## Requirements

- Rebrowser CDP on `127.0.0.1:9225`.
- Playwright available in either local `node_modules` or the standard Rebrowser
  workspace at `$HOME/.codex/x-cdp-rebrowser-playwright/node_modules`.
- SSH access to the RPC node.

## Capture And Publish

```bash
node collectors/rebrowser-rendered-web/rebrowser_rendered_capture.mjs \
  --url https://www.example.com/blog/model-launch \
  --source-project launch-blog-research \
  --topic-label launch-blog \
  --publish
```

By default, artifacts are written locally to a temporary directory, rsynced to:

```text
/mnt/data/x-research/web/rebrowser-rendered/<date>/<collector_run_id>/<document_id>/
```

Then the capture event is posted through RPC-local Pandaproxy by SSH. The
result flows through the normal pipeline:

```text
Rebrowser rendered capture
-> evidence.capture.events.v1
-> normalizer/materializer
-> evidence.web.documents.observed.v1
-> ClickHouse / Typesense / Pebble / Qdrant embedding worker
-> Research UI source workbench
```

## Notes

- The script opens a task-owned tab and closes it after capture by default.
- X/Twitter URLs are refused by default; use the X-specific collector/subskill
  for those sources.
- Static extraction remains useful as a companion parser, but rendered
  Rebrowser capture is the preferred path for analyst-facing evidence pages.
