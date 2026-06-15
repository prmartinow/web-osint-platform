# Operating Guide

## Start

```bash
scripts/bootstrap.sh
```

The stack binds service ports to `127.0.0.1` on the RPC node:

- Redpanda Kafka: `127.0.0.1:19092`
- Redpanda Pandaproxy: `127.0.0.1:18082`
- Redpanda Schema Registry: `127.0.0.1:18081`
- Redpanda Admin: `127.0.0.1:19644`
- Typesense: `127.0.0.1:18108`
- Qdrant: `127.0.0.1:16333`
- ClickHouse HTTP: `127.0.0.1:18123`
- ClickHouse native: `127.0.0.1:19000`
- Normalizer lookup API: `127.0.0.1:18090`
- Research planner API: `127.0.0.1:18091`

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

## Data Ownership

Redpanda topics are durable replay source. Pebble state, Typesense, Qdrant, and ClickHouse are rebuildable views. Media and OCR artifacts live under the configured data root.

The normalizer consumes `evidence.capture.events.v1`, emits observed/state topics, writes materialized records to Pebble, inserts analytics rows into ClickHouse, upserts evidence text into Typesense, emits deterministic semantic annotations, and passes Qdrant named vectors through when a collector or enrichment worker includes them.

Collector events may include `web_documents` for opened pages, articles, documentation, PDFs, leaderboards, and table captures. They may include `user_inputs` for user notes, pasted research, corrections, attachments, or research seeds. These records use the same replay, search, analytics, and labeling path as X and Google evidence.

The research planner reads recent `semantic_annotations` plus `evidence_events`, creates stable/deduped research signals, questions, and task seeds, inserts them into ClickHouse, and publishes replay events to `osint.research_signal.detected.v1`, `osint.research_question.proposed.v1`, and `osint.research_task.created.v1`. Run it once for a smoke pass with:

```bash
docker compose --env-file .env -f compose/docker-compose.yml run --rm research-planner --once
```

The dashboard includes a `Meaning` tab backed by `/api/stage/meaning`. It is read-only and surfaces annotation activity, label families, recent annotations, research questions, autonomous tasks, and research signals from ClickHouse. Empty tables are treated as an empty Meaning Layer so the dashboard can run before the new schema is initialized.
