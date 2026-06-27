# Rebrowser Rendered Web Collector

Captures browser-rendered web/blog/document pages from the preserved Rebrowser
CDP session and publishes them as ordinary `web_documents` capture events.

This collector is for pages where the browser-rendered view is the evidence:
JavaScript pages, interactive launch blogs, pages with visual/layout context,
or any source where static HTTP extraction is sparse.

## Requirements

- Rebrowser CDP URL supplied through `REBROWSER_CDP_URL` or `--cdp-url`.
- Playwright available in either local `node_modules` or the standard Rebrowser
  workspace at `$HOME/.codex/x-cdp-rebrowser-playwright/node_modules`.
- SSH access to the RPC node when `--publish` is used.

## Capture And Publish

```bash
node collectors/rebrowser-rendered-web/rebrowser_rendered_capture.mjs \
  --url https://www.example.com/blog/model-launch \
  --source-project launch-blog-research \
  --topic-label launch-blog \
  --publish
```

Publishing requires these values in CLI args, process env, or an ignored env
file loaded by the shell:

```text
REBROWSER_CDP_URL
WEB_OSINT_RPC_SSH_HOST
WEB_OSINT_RPC_SSH_PORT
WEB_OSINT_RPC_DATA_ROOT
WEB_OSINT_REMOTE_PANDAPROXY_URL
```

Artifacts are written locally to a temporary directory, rsynced under
`$WEB_OSINT_RPC_DATA_ROOT/web/rebrowser-rendered/...`, and the capture event is
posted through the configured Pandaproxy URL by SSH. The result flows through
the normal pipeline:

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
