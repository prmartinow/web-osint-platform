# Web OSINT Platform

Web OSINT Platform is a local-first infrastructure stack for collecting, normalizing, indexing, and serving evidence gathered from the open web.

It is designed for automated research workflows where browser or API collectors capture evidence once, publish it to an event stream, and make it available to downstream agents, reports, dashboards, and human research tools without repeatedly re-touching fragile upstream sources.

## What It Provides

- Collector-facing producer and local outbox pattern.
- Redpanda event streaming for durable capture history.
- A Go normalizer/materializer worker.
- Pebble exact lookup for stable IDs such as posts, accounts, media, and captures.
- Typesense keyword, faceted, and filterable search.
- Qdrant semantic/vector retrieval with named vectors.
- ClickHouse analytics tables for rollups, trend analysis, and report data marts.
- Filesystem-backed media and OCR artifact storage.
- Deterministic research-planning worker that promotes labels into research signals, questions, and autonomous task seeds.

## Architecture

```text
Collectors
  -> local outbox
  -> Redpanda topics
  -> normalizer/materializer
  -> Pebble exact lookup
  -> Typesense search
  -> Qdrant vectors
  -> ClickHouse analytics
  -> filesystem media/OCR artifacts
  -> research planner
  -> agents, reports, dashboards, and research tools
```

## Quick Start

Copy the environment template and edit secrets:

```bash
cp .env.example .env
```

Start the stack:

```bash
scripts/bootstrap.sh
```

Check health:

```bash
scripts/health.sh
```

Produce a synthetic sample event:

```bash
producer/web_osint_producer.py spool \
  --topic evidence.capture.events.v1 \
  --value-file samples/capture_event_full_smoke.json

producer/web_osint_producer.py flush
```

Look up the sample post:

```bash
curl 'http://127.0.0.1:18090/lookup?key=post/1234567890'
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Operations](docs/OPERATING.md)
- [Local Inference](docs/LOCAL_INFERENCE.md)
- [Sanitization](docs/SANITIZATION.md)

## Status

This is an early infrastructure baseline. The current implementation includes the streaming backbone, materializer, exact lookup, search, vector-store initialization, local Qwen inference, Qdrant embedding enrichment, analytics schema, deterministic labeling, research-planning seed generation, dashboard research search, and an end-to-end ingestion canary. Real collectors and richer media/OCR/VL enrichment workers should be added on top of the existing event schemas.
