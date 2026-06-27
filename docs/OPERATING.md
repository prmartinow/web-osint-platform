# Operating Guide

## Start

```bash
scripts/bootstrap.sh
```

The stack binds service ports to `127.0.0.1` on the RPC node:

- Redpanda broker Kafka-compatible listener: `127.0.0.1:19092`
- Redpanda Pandaproxy: `127.0.0.1:18082`
- Redpanda Schema Registry: `127.0.0.1:18081`
- Redpanda Admin: `127.0.0.1:19644`
- Typesense: `127.0.0.1:18108`
- Qdrant: `127.0.0.1:16333`
- ClickHouse HTTP: `127.0.0.1:18123`
- ClickHouse native: `127.0.0.1:19000`
- Normalizer lookup API: `127.0.0.1:18090`
- Research planner API: `127.0.0.1:18091`
- Redpanda Connect production router: `127.0.0.1:14194`
- Redpanda Connect shadow router: `127.0.0.1:14195`

Use an SSH tunnel for remote collector publishing. Keep service ports private by default.

## Health

```bash
scripts/health.sh
```

The normalizer/materializer API:

```bash
curl http://127.0.0.1:18090/healthz
curl http://127.0.0.1:18090/stats
curl 'http://127.0.0.1:18090/lookup?key=post/<post_id>'
curl http://127.0.0.1:18091/stats
curl http://127.0.0.1:14194/ready
```

Exact lookup keys currently use these prefixes:

- `capture/<collector_run_id>:<event_index>`
- `post/<post_id>`
- `account/<normalized_handle>`
- `media/<media_id>`
- `search/<sha256>`
- `web_document/<document_id>`
- `user_input/<input_id>`
- `annotation/<evidence_id>/<label_id>/<annotation_id>`

## Topics

Observed event topics:

- `evidence.capture.events.v1`
- `evidence.posts.observed.v1`
- `evidence.accounts.observed.v1`
- `evidence.media.observed.v1`
- `evidence.search.results.v1`
- `evidence.web.documents.observed.v1`
- `evidence.user.inputs.observed.v1`

Compacted state topics:

- `evidence.posts.state.v1`
- `evidence.accounts.state.v1`
- `evidence.media.state.v1`
- `evidence.web.documents.state.v1`
- `evidence.user.inputs.state.v1`

Error topic:

- `evidence.index.errors.v1`

Shadow Connect topics:

- `evidence.capture.shadow.validated.v1`
- `evidence.capture.shadow.errors.v1`
- `evidence.capture.shadow.observed.v1`
- `osint.media.enrichment.shadow.requested.v1`

Meaning Layer topics:

- `osint.label.proposed.v1`
- `osint.state.current_labels_by_target.v1`
- `osint.entity.mentioned.v1`
- `osint.claim.extracted.v1`
- `osint.relation.extracted.v1`
- `osint.benchmark_fact.extracted.v1`
- `osint.release_signal.detected.v1`
- `osint.research_signal.detected.v1`
- `osint.research_question.proposed.v1`
- `osint.research_task.created.v1`
- `osint.wiki.page_materialized.v1`
- `osint.web.extraction.requested.v1`
- `osint.web.extraction.failed.v1`

## Data Ownership

Redpanda topics are durable replay source. Pebble state, Typesense, Qdrant, and ClickHouse are rebuildable views. Media and OCR artifacts live under the configured data root.

In guarded production-routing mode, Redpanda Connect consumes
`evidence.capture.events.v1` and emits observed topics plus media request
topics. The normalizer consumes the same raw capture stream, runs with
`WEB_OSINT_EMIT_OBSERVED_TOPICS=false`, emits state topics, writes materialized
records to Pebble, inserts analytics rows into ClickHouse, upserts evidence text
into Typesense, emits deterministic semantic annotations, and passes Qdrant
named vectors through when a collector or enrichment worker includes them.

Collector events may include `web_documents` for opened pages, articles, documentation, PDFs, leaderboards, and table captures. They may include `user_inputs` for user notes, pasted research, corrections, attachments, or research seeds. These records use the same replay, search, analytics, and labeling path as X and Google evidence.

### Webpage Extraction

Rebrowser is the preferred capture surface for web pages that matter as research evidence. The webpage extraction worker is a companion parser/enrichment path that turns URLs into `web_documents` capture events with HTML/text/Markdown/table artifacts. Use it for launch blog posts, documentation pages, model cards, benchmark pages, and opened search results when HTTP extraction is explicitly useful or when a Rebrowser-captured source needs normalized projections.

Capture a rendered page from the preserved Rebrowser session and publish it into the normal pipeline:

```bash
node collectors/rebrowser-rendered-web/rebrowser_rendered_capture.mjs \
  --url https://www.example.com/blog/model-launch \
  --source-project launch-blog-research \
  --topic-label launch-blog \
  --publish
```

The rendered collector opens a task-owned Rebrowser tab on `127.0.0.1:9225`, captures rendered DOM/text/links/images/tables, writes a full-page screenshot plus `EvidenceDocument`, uploads artifacts to `/mnt/data/x-research/web/rebrowser-rendered/...`, publishes through RPC-local Pandaproxy, and closes the task tab. It refuses X/Twitter URLs by default because those need the X-specific collector and pacing rules.

Install its isolated venv under the data root:

```bash
scripts/init_webpage_extraction_venv.sh
```

Run a one-off extraction without publishing:

```bash
/mnt/data/web-osint-platform/.venv-webpage-extraction/bin/python \
  workers/webpage-extraction/webpage_extraction_worker.py extract-url \
  --url https://www.example.com/blog/model-launch \
  --source-project launch-blog-research \
  --topic-label launch-blog
```

Publish extracted pages through Pandaproxy into the normal capture pipeline:

```bash
/mnt/data/web-osint-platform/.venv-webpage-extraction/bin/python \
  workers/webpage-extraction/webpage_extraction_worker.py extract-url \
  --url https://www.example.com/blog/model-launch \
  --source-project launch-blog-research \
  --topic-label launch-blog \
  --publish
```

Run the launch-blog canary from the live RPC tree:

```bash
python3 scripts/run_webpage_extraction_canary.py --env-file .env
```

The worker stores raw HTML, text, Markdown, tables, metadata, and an `evidence_document` JSON artifact below the configured data root before publishing a compact event containing text, provenance, quality signals, content representation paths, and artifact paths.

Do not treat static extraction as the default evidence capture path. For analyst-facing web research, capture the page through Rebrowser first, then use static extraction only as a companion parser when it adds useful normalized artifacts. If static extraction misses content, that confirms it is incomplete; it should not replace the Rebrowser-rendered capture.

The Research UI should consume those normalized artifacts from a separate app/service, not from a metrics-dashboard tab. Use the Research UI for Inbox triage, source workbench inspection, evidence extraction, normalized-content correction, entity/claim review, comparison, and publication preparation; use the pipeline dashboard only for service health and store monitoring.

Run the Research UI as a separate Compose service:

```bash
docker compose --env-file .env -f compose/docker-compose.yml up -d --build research-ui
curl http://127.0.0.1:18192/healthz
```

The service is intentionally read-oriented in v1. It queries ClickHouse evidence rows, related semantic/OCR/VL enrichment rows, and safe artifact files under the configured Web OSINT data root. The production deployment can bind it to a LAN-scoped host address while keeping direct data services on RPC localhost.

Run the continuous request-topic worker as a user service on the RPC node:

```bash
mkdir -p ~/.config/systemd/user
cp systemd/user/web-osint-webpage-extraction-worker.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now web-osint-webpage-extraction-worker.service
curl http://127.0.0.1:18221/healthz
```

### Manual Research Documents

User-added Markdown or text research files should be ingested as chunked `user_input` evidence. This keeps manually curated research in the same pipeline as Google, X, and opened web documents while preserving the source file path and content hash in each chunk's `context`.

Dry-run a folder:

```bash
python3 scripts/produce_research_documents.py \
  /mnt/data/x-research/user-documents/agent-tooling \
  --source-root /mnt/data/x-research/user-documents/agent-tooling \
  --source-project agent-harness \
  --topic-label agent-harness \
  --dry-run
```

Publish to Redpanda through Pandaproxy:

```bash
python3 scripts/produce_research_documents.py \
  /mnt/data/x-research/user-documents/agent-tooling \
  --source-root /mnt/data/x-research/user-documents/agent-tooling \
  --source-project agent-harness \
  --topic-label agent-harness
```

### Shadow Redpanda Connect

The Connect shadow service is disabled by default and runs only under the
`shadow` Compose profile. It validates capture envelopes, projects observed
events into shadow wrappers, builds shadow-only media request wrappers, and
does not feed serving stores.

```bash
docker compose --env-file .env -f compose/docker-compose.yml --profile shadow up -d --build redpanda-connect-shadow
python3 scripts/run_e2e_canary.py --expect-shadow
python3 scripts/run_connect_shadow_parity.py
```

See [Connect Shadow Pipeline](CONNECT_SHADOW.md).

### Production Redpanda Connect Routing

The production Connect router is disabled by default in Compose and runs under
the `production-routing` profile. Start it with the normalizer observed-topic
emission gate disabled:

```bash
WEB_OSINT_EMIT_OBSERVED_TOPICS=false \
  docker compose --env-file .env -f compose/docker-compose.yml --profile production-routing up -d --build normalizer redpanda-connect-production
curl http://127.0.0.1:14194/ready
curl http://127.0.0.1:18090/stats
```

While production Connect owns media request fan-out, stop the legacy router but
leave it installed:

```bash
systemctl --user stop web-osint-media-router.service
```

Fallback:

```bash
docker rm -f web-osint-connect-production
WEB_OSINT_EMIT_OBSERVED_TOPICS=true \
  docker compose --env-file .env -f compose/docker-compose.yml up -d --build normalizer
systemctl --user start web-osint-media-router.service
```

The script chunks long documents before publishing so embedding coverage favors accuracy over latency. Reusing the same document content gives stable `input_id` values; downstream stores should hydrate by `evidence_id` and tolerate repeated capture observations.

### Redpanda Reference Source Cache

Reference source checkouts live outside the repo on the RPC data disk:

```text
/mnt/data/web-osint-platform/reference-src/
/home/ops/dev/reference-src -> /mnt/data/web-osint-platform/reference-src
```

Use `redpanda-connect-v4.46.0` for exact behavior of the current custom Connect
binary, `redpanda-v26.1.10` for the live broker source observed on 2026-06-18,
and the unversioned `redpanda-connect` / `redpanda` checkouts for current
upstream changes.

Refresh only current-branch references by default:

```bash
cd /mnt/data/web-osint-platform/reference-src/redpanda-connect
git fetch --depth 1 origin main && git checkout -q FETCH_HEAD

cd /mnt/data/web-osint-platform/reference-src/redpanda
git fetch --depth 1 origin dev && git checkout -q FETCH_HEAD
```

Do not vendor these checkouts into the sanitized GitHub repo.

The research planner reads recent `semantic_annotations` plus `evidence_events`, creates stable/deduped research signals, questions, and task seeds, inserts them into ClickHouse, and publishes replay events to `osint.research_signal.detected.v1`, `osint.research_question.proposed.v1`, and `osint.research_task.created.v1`. Run it once for a smoke pass with:

```bash
docker compose --env-file .env -f compose/docker-compose.yml run --rm research-planner --once
```

The dashboard includes a `Meaning` tab backed by `/api/stage/meaning`. It is read-only and surfaces annotation activity, label families, recent annotations, research questions, autonomous tasks, and research signals from ClickHouse. Empty tables are treated as an empty Meaning Layer so the dashboard can run before the new schema is initialized.

## Local Inference Interface

Model serving, model downloads, model caches, and model-serving runtime
dependencies live in the separate `local-inference` repo. Web OSINT is a client
only and calls the API through `LOCAL_INFERENCE_URL`; real endpoint values
belong in ignored deployment env files.

Check model service state from the local-inference side:

```bash
systemctl --user status local-inference.service --no-pager
curl -fsS "${LOCAL_INFERENCE_URL:?set LOCAL_INFERENCE_URL}/healthz" | python3 -m json.tool
curl -fsS "${LOCAL_INFERENCE_URL:?set LOCAL_INFERENCE_URL}/metrics"
```

Web OSINT owns only the client workers that call the API:

```bash
systemctl --user status web-osint-embedding-worker.service --no-pager
systemctl --user status web-osint-media-ocr-worker.service --no-pager
systemctl --user status web-osint-media-vl-worker.service --no-pager
curl -fsS "${EMBEDDING_WORKER_URL:?set EMBEDDING_WORKER_URL}/stats"
curl -fsS "${MEDIA_OCR_WORKER_URL:?set MEDIA_OCR_WORKER_URL}/stats"
curl -fsS "${MEDIA_VL_WORKER_URL:?set MEDIA_VL_WORKER_URL}/stats"
```

PaddleOCR is served by local-inference through `POST /media/ocr`; the Web
OSINT media OCR worker only consumes OCR request topics and writes artifacts,
ClickHouse rows, and capture events. Do not install PaddleOCR/PaddleX/
PaddlePaddle or configure Paddle cache paths in Web OSINT worker venvs.

See `docs/LOCAL_INFERENCE.md` for the Web OSINT client contract and the
`prmartinow/local-inference` repo for model inventory, downloads, guardrails,
and candidate model manifests.

CPU-heavy Web OSINT user services should be launched through
`scripts/run_with_cpu_thread_guard.sh`. The default
`WEB_OSINT_CPU_RESERVED_THREADS=2` keeps at least two logical CPUs outside the
worker affinity mask for other RPC services while clamping common numeric
thread-pool variables for client workers.

## End-To-End Canary

Use the end-to-end canary after pipeline, inference, or dashboard changes. It creates a synthetic Markdown research document under `/mnt/data`, publishes it to Redpanda through the normal manual-document capture path, then waits for:

```text
capture_event -> observed user_input row -> embedding audit topic -> Qdrant point -> dashboard research search hit
```

Run it from the RPC live tree:

```bash
cd /home/ops/dev/x-research
python3 scripts/run_e2e_canary.py --env-file .env
```

Exit codes:

- `0`: pass.
- `1`: pipeline failed before all expected stages appeared.
- `2`: local configuration error.
- `3`: required dependency unavailable.

The canary writes durable operator artifacts:

```text
/mnt/data/x-research/canaries/runs/<run_id>.json
/mnt/data/x-research/metrics/e2e_canary.prom
ClickHouse: ops_canary_runs, ops_canary_steps
```

The JSON result is the detailed evidence trail. The Prometheus textfile is the lightweight health signal for dashboards or later scraping.
