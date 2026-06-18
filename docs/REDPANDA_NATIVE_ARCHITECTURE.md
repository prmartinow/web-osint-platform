# Redpanda-Native Architecture

This platform is Redpanda-first. Redpanda owns durable event contracts,
routing boundaries, replay, DLQs, lag/offset visibility, and stream
observability. Kafka-compatible producer and consumer APIs remain an
implementation detail of Redpanda's data plane, not the architecture name.

## Operating Language

Use these terms:

- Redpanda Streaming topics
- Redpanda topic producers and consumers
- Kafka-compatible client API, only when discussing the wire protocol or a
  concrete client library
- Redpanda Connect pipeline
- Redpanda Connect compiled Go plugin
- Redpanda Connect dynamic gRPC plugin
- Redpanda Data Transform

Avoid these terms for architecture docs:

- Kafka cluster
- Kafka wiring
- Kafka architecture
- Benthos YAML as business logic

## Component Split

```text
Redpanda Streaming topics
  durable event backbone, replay, consumer groups, append/state topics

Redpanda Data Transforms
  tiny broker-local, single-record, stateless transforms only

Redpanda Connect
  stream plumbing and plugin host

Compiled Go Connect plugins
  hot deterministic validation/projection/routing logic

Dynamic gRPC Connect plugins
  isolated lightweight non-Go processors, not model inference

Custom services
  stateful materialization, model inference, OCR/VL, retrieval, dashboards
```

## Direct Redpanda Topic Clients

Direct clients are acceptable when they consume or produce Redpanda topics
through the Kafka-compatible data-plane API. They are preferred for:

- Mac collectors and local outbox flushers;
- the stateful Go materializer;
- embedding, OCR, and VL workers;
- dashboard/admin tools that inspect audit topics;
- long-running workers with their own queues, CPU budgets, local files, or
  idempotent external writes.

When a direct client is used, code and docs should still describe it as a
Redpanda topic client. Mention the Kafka-compatible API only where the exact
library or protocol matters.

## Data Transforms

Data Transforms are broker-local and should remain cheap:

- capture-envelope shape validation;
- source-kind routing hints;
- field redaction/scrubbing;
- minimal route metadata stamping;
- malformed test event routing.

Do not use Data Transforms for Pebble, ClickHouse, Typesense, Qdrant, OCR,
Qwen, filesystem writes, joins, aggregation, or any network/disk side effect.

## Redpanda Connect

Connect YAML is wiring, not business logic. Keep YAML focused on:

- topic input/output wiring;
- DLQ routing;
- status/log/metrics configuration;
- invoking compiled plugins;
- small audit sinks.

Business logic should live in compiled Go plugins or custom services.

## Compiled Go Plugin Candidates

P0/P1 plugin candidates:

- `capture_envelope_validate`
- `source_kind_router`
- `stable_id_compute`
- `artifact_ref_validate`
- `content_hash_validate`
- `observed_event_projector`
- `media_enrichment_request_builder`
- `semantic_annotation_router`
- `dlq_error_enricher`
- `clickhouse_row_projector` for simple append-only audit rows

## Dynamic gRPC Plugin Candidates

Dynamic plugins are useful for isolated, batch-friendly processors that need
non-Go libraries:

- lightweight document-type sniffers;
- small Python metadata classifiers;
- optional local file metadata inspection;
- experiments that should deploy independently.

Do not wrap Qwen, PaddleOCR, or Qwen3-VL as gRPC plugins in v1. They need
warm model state, bounded queues, CPU guardrails, long timeouts, and independent
health checks.

## Normalizer / Materializer Split

The existing Go normalizer/materializer should not be replaced wholesale.

Target split:

```text
Redpanda Connect custom distribution
  capture validation
  source-kind projection
  observed-topic emission
  media enrichment request routing
  DLQ enrichment

Go materializer service
  consumes observed topics
  writes Pebble exact lookup
  inserts ClickHouse rows
  indexes Typesense
  coordinates Qdrant metadata/state
```

The production materializer remains custom because cross-store state,
idempotency, and external writes need explicit control.

## Migration Phases

1. **Document and reframe.** Replace Kafka-first wording, add the topic
   catalog, and preserve the working pipeline.
2. **Shadow Connect.** Run Connect in shadow mode:
   `evidence.capture.events.v1 -> capture_envelope_validate ->
   evidence.capture.shadow.validated.v1`; failures go to
   `evidence.capture.shadow.errors.v1`.
3. **Compare parity.** Extend canaries to verify shadow output and compare
   stable fields against the current Go normalizer output.
4. **Move stateless routing.** Add source-kind routing, observed-event
   projection, media request building, and DLQ enrichment as compiled plugins.
5. **Cut over routing only.** After parity is stable, Connect emits observed
   topics and the Go materializer consumes observed topics only.
6. **Keep rollback.** The Go normalizer can resume observed-topic production
   until the cutover is proven over replay and canary runs.

## Semantics

Assume at-least-once delivery everywhere. Sinks must be idempotent:

- Pebble keys are deterministic;
- ClickHouse rows carry unique IDs or are queried through dedupe views;
- Typesense document IDs are deterministic;
- Qdrant point IDs are deterministic;
- artifact paths are content-addressed.

Do not put persistent pre-output dedupe state inside Connect pipelines. A crash
after marking a message processed but before output succeeds can violate the
expected at-least-once behavior.

## Current Target Spec

The local CB advisor target for this migration is preserved at:

```text
docs/advisor/redpanda-native-implementation-target.md
```

Implementation passes should check their work against that target and update
status in PR/commit notes.

## Local Reference Source

Keep Redpanda and Redpanda Connect source checkouts outside this repository so
component names and config fields can be checked against code before changing
pipelines:

```text
/mnt/data/web-osint-platform/reference-src/
  redpanda-connect/          current upstream main
  redpanda-connect-v4.46.0/  exact Connect tag used by connect/go.mod
  redpanda/                  current upstream dev
  redpanda-v26.1.10/         exact live broker version observed 2026-06-18
```

There is a convenience symlink at `/home/ops/dev/reference-src` on the RPC
node. Do not vendor these checkouts into the sanitized repo.
