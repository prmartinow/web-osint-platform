# Webpage Extraction Worker

Fetches HTML webpages, extracts article/main text, markdown, links, metadata,
tables, headings, images, JSON-LD, artifact files, and an `EvidenceDocument`
block/asset artifact, then publishes ordinary `web_documents` capture events to
`evidence.capture.events.v1`.

This worker is the static HTML parser/enrichment path. Rebrowser is the
first-choice rendered-browser capture surface for web pages that matter as
research evidence; use this worker when HTTP extraction is explicitly useful,
for batch parsing, or to add normalized projections to a Rebrowser-captured
source.

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
"${WEB_OSINT_WEBPAGE_EXTRACTION_PYTHON:-${WEB_OSINT_WEBPAGE_EXTRACTION_VENV:?set WEB_OSINT_WEBPAGE_EXTRACTION_VENV}/bin/python}" \
  workers/webpage-extraction/webpage_extraction_worker.py extract-url \
  --url https://example.com/ \
  --source-project smoke \
  --topic-label webpage-extraction
```

Add `--publish` to send the capture event through Pandaproxy.

Static extraction is not the default evidence capture path. For analyst-facing
web research, capture the page through Rebrowser first and preserve the same
artifact/EvidenceDocument contract. Treat a sparse static result as incomplete,
not as a reason to skip browser capture.

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

Stats are exposed through the configured `WEBPAGE_EXTRACTION_WORKER_URL`.
