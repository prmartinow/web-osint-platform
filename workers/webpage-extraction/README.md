# Webpage Extraction Worker

Fetches HTML webpages, extracts article/main text, markdown, links, metadata,
tables, headings, images, JSON-LD, artifact files, and an `EvidenceDocument`
block/asset artifact, then publishes ordinary `web_documents` capture events to
`evidence.capture.events.v1`.

The normalizer already handles those events, so extracted pages flow through:

```text
webpage extraction
-> evidence.capture.events.v1
-> normalizer/materializer
-> evidence.web.documents.observed.v1
-> ClickHouse / Typesense / Pebble / Qdrant embedding worker
```

## Setup

```bash
scripts/init_webpage_extraction_venv.sh
```

## One-off extraction

```bash
WEB_OSINT_ALLOW_NON_DATA_ROOT=1 \
OSINT_DATA_ROOT=/tmp/web-osint-extract-test \
/mnt/data/web-osint-platform/.venv-webpage-extraction/bin/python \
  workers/webpage-extraction/webpage_extraction_worker.py extract-url \
  --url https://example.com/ \
  --source-project smoke \
  --topic-label webpage-extraction
```

Add `--publish` to send the capture event through Pandaproxy.

Static extraction is the first pass. If the page is dynamic, interaction-heavy,
or visibly richer in the browser than the static capture, escalate to Rebrowser
rendered-DOM capture and preserve the same artifact/EvidenceDocument contract.

## Continuous worker

The worker consumes `osint.web.extraction.requested.v1`. A request is:

```json
{
  "url": "https://example.com/launch-blog",
  "source_project": "model-launch-research",
  "collector_run_id": "optional-run-id",
  "event_index": 0,
  "topics": ["launch-blog", "model-release"],
  "context": {"reason": "launch blog extraction"}
}
```

Stats are exposed at `127.0.0.1:18221/stats` by default.
