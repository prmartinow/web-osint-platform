<!--
Source: CB advisor answer extracted from the RPC ChatGPT lane on 2026-06-18.
Use this as the implementation target for the Redpanda-native migration.
-->

Core recommendation

Do not try to remove Kafka-compatible clients entirely. Redpanda’s main data plane is intentionally Kafka-compatible: Redpanda documents compatibility with Apache Kafka 0.11+ clients, and validates common Java/C/C++/Go/Python clients. The practical reframing is:

Redpanda-first architecture using Redpanda Streaming topics, Redpanda Connect, Data Transforms, Console/Schema Registry, and rpk — with Kafka-compatible producer/consumer APIs as the wire protocol where required.

That means stop describing the platform as “Kafka wiring,” but do not churn working producers/consumers just because the client library uses Kafka protocol names.
Redpanda Documentation

1. What can and cannot be replaced
Can realistically become Redpanda-native
Current thing	Redpanda-first replacement
Ad hoc topic routing	Redpanda Connect pipelines or Redpanda Data Transforms for simple stateless routing.
Lightweight validation/fanout	Data Transforms or Redpanda Connect compiled Go processors.
YAML-only Connect pipelines	Use YAML only as wiring; put custom logic in compiled Go plugins.
Media enrichment request routing	Redpanda Connect pipeline + compiled Go plugin.
DLQ/error routing	Redpanda Connect try/catch style handling into error topics.
Simple ClickHouse insert sinks	Redpanda Connect SQL output may be acceptable for ops/audit rows.
Status/log fanout	Redpanda Connect supports status/log topics through Redpanda configuration.
Redpanda Documentation

Some normalizer stateless steps	Compiled Go plugins inside a custom Redpanda Connect distribution.
Should not be replaced wholesale now
Current thing	Keep as-is for now
Redpanda producer/consumer APIs	Redpanda’s data plane is Kafka-compatible by design. Keep franz-go/Python clients where they are already stable.
Pebble exact lookup materialization	Stateful, idempotent, app-specific. Keep custom service code.
ClickHouse/Typesense/Qdrant multi-sink materialization	Keep custom service until routing and idempotency are fully proven.
Qwen embedding/rerank/VL workers	Keep as long-running Python services behind guardrails.
PaddleOCR worker	Keep as a long-running Python service.
Dashboard retrieval coordinator	Keep custom service code; Connect is not the right abstraction for interactive search.
2. Reframe the architecture

Use this terminology:

Redpanda Streaming = durable event backbone
Redpanda topics = source of replayable truth
Redpanda Connect = managed stream plumbing and plugin host
Redpanda Data Transforms = broker-local stateless transforms
Custom services = stateful materialization, inference, OCR, retrieval
Kafka-compatible clients = implementation detail of Redpanda data plane

Preferred docs phrasing:

“Consume from Redpanda topic evidence.capture.events.v1”

“Produce to Redpanda topic evidence.media.observed.v1”

“Use franz-go against Redpanda’s Kafka-compatible API”

“Redpanda Connect pipeline”

“Redpanda Data Transform”

Avoid:

“Kafka cluster”

“Kafka wiring”

“Kafka as architecture”

“Benthos YAML as core logic”

3. Where each Redpanda component fits
Redpanda Streaming topics directly

Use topics directly for durable, inspectable event boundaries:

evidence.capture.events.v1

evidence.*.observed.v1

evidence.*.state.v1

osint.semantic.embedded.v1

osint.media.*.requested.v1

osint.media.*.completed.v1

osint.media.*.failed.v1

DLQ topics

canary/audit topics

Use direct clients for:

Mac collectors;

long-running materializer;

embedding worker;

OCR/VL workers;

dashboard/admin tools when reading audit events.

Redpanda Data Transforms

Use only for stateless, broker-local, single-record transforms:

envelope validation;

source-kind fanout;

field redaction/scrubbing if needed;

converting collector capture events into minimal routing topics;

dropping obviously malformed synthetic test events into DLQ;

stamping simple route metadata.

Do not use Data Transforms for:

Pebble lookup;

ClickHouse inserts;

Typesense/Qdrant writes;

OCR/Qwen calls;

filesystem artifact writes;

joins/aggregations;

anything needing network/disk access.

Reason: Data Transforms run as Wasm inside the broker, map input topics to output topics, have no external disk/network access, are single-record transforms, and are at-least-once.
Redpanda Documentation
+1

Redpanda Connect declarative pipelines

Use YAML as thin orchestration:

topic → processor plugin → output topic;

topic → DLQ;

topic → SQL audit insert;

media observed → enrichment request topics;

canary topic checks;

mirror/copy/decode/validate paths;

ops metrics/log/status topics.

Do not put complex research logic in Bloblang/YAML. Redpanda Connect is suitable for high-performance pipelines and has many connectors, but your custom semantics should live in plugins/services.
Redpanda Documentation

Redpanda Connect compiled Go plugins

Use for hot, deterministic, CPU-light logic:

capture_envelope_validate

capture_route_by_source_kind

stable_id_compute

artifact_ref_validate

content_hash_validate

observed_event_projector

media_enrichment_request_builder

semantic_annotation_router

dlq_error_enricher

clickhouse_row_projector for simple append-only audit rows

Compiled plugins are built into the Connect binary and are the right choice for maximum performance in critical workloads.
Redpanda Documentation

Redpanda Connect dynamic gRPC plugins

Use sparingly for logic that needs non-Go libraries but is still batch-friendly:

small Python metadata classifiers;

light document-type sniffers;

optional local file metadata inspection;

experimental processors that should be deployed independently.

Dynamic plugins run as separate gRPC-connected processes over Unix sockets, support non-Go languages, and provide process isolation, but they add serialization/IPC overhead.
Redpanda Documentation
+1

Do not use dynamic plugins as the main wrapper for Qwen/PaddleOCR yet.

Custom long-running services/workers

Keep for:

Go materializer writing Pebble/ClickHouse/Typesense;

dashboard retrieval API;

Qwen inference guardrail service;

embedding worker;

PaddleOCR worker;

Qwen3-VL worker;

filesystem artifact manager;

research planner/task seed generator.

These services own state, queues, CPU budgeting, local files, and idempotent writes.

4. Should the Go normalizer/materializer become a Redpanda Connect custom distribution?
Recommendation

Partially, not wholesale.

Do not replace the entire Go normalizer/materializer in one step. Split it into two conceptual services:

Normalizer/router:
  stateless-ish event validation, projection, fanout, enrichment request creation

Materializer:
  Pebble exact lookup, ClickHouse inserts, Typesense indexing, Qdrant metadata checks, idempotent state

Move the normalizer/router portion toward Redpanda Connect compiled Go plugins. Keep the materializer as custom Go service.

Good candidates for Connect compiled plugins

parse capture event;

validate required fields;

normalize envelope fields;

compute deterministic IDs;

project source-specific records into observed-event payloads;

emit observed topics;

build media enrichment requests;

enrich DLQ messages with error metadata.

Keep custom Go service code

Pebble exact lookup writes;

ClickHouse batch inserts where ordering/idempotency matters;

Typesense indexing;

Qdrant write coordination;

cross-store hydration assumptions;

stateful dedupe;

dashboard-adjacent APIs.

Reason: Redpanda Connect guarantees at-least-once delivery, but external persistent state inside a pipeline can create loss risks if used for pre-output dedupe. Downstream stores should be idempotent instead of relying on Connect-side persistent dedupe.
Redpanda Documentation

5. Should Python workers become Redpanda Connect gRPC plugins?
Recommendation

No for v1.1. Keep CPU-heavy Qwen/OCR/VL as separate services.

Use Redpanda topics as the durable queue:

osint.media.ocr.requested.v1
  -> media-ocr-worker
  -> osint.media.ocr.completed.v1 / failed.v1

osint.media.vl_embedding.requested.v1
  -> media-vl-worker
  -> osint.media.vl_embedding.completed.v1 / failed.v1

Use Connect only to route requests into those topics.

Why:

Qwen/OCR/VL need long-lived model/process state.

They need independent concurrency limits, queue depth, warmup, CPU protection, and self-tests.

Large images should be passed by filesystem artifact path, not serialized through gRPC plugin messages.

Dynamic plugins add IPC/serialization overhead; Redpanda docs explicitly recommend compiled plugins for maximum performance.
Redpanda Documentation

Later, small Python gRPC plugins are reasonable for lightweight sniffers, not heavy inference.

6. Migration plan without breaking the pipeline
Phase 0 — Rename and document

Immediate:

Replace “Kafka wiring” language with “Redpanda Streaming topics.”

Add docs/REDPANDA_NATIVE_ARCHITECTURE.md.

Add a topic catalog with owners, source of truth, retention, compaction, schema, and consumer groups.

Keep existing clients and working canaries.

Phase 1 — Add Redpanda Connect as a sidecar layer

Create:

connect/
  pipelines/
  plugins/
  cmd/web-osint-connect/

Add a custom Connect distribution skeleton with compiled Go plugins, but run it in shadow mode.

Shadow pipeline example:

evidence.capture.events.v1
  -> Connect validate/project
  -> evidence.capture.shadow.observed.v1

Compare output against current Go normalizer. Do not switch production yet.

Phase 2 — Move stateless routing first

Move only these into Connect/plugin path:

capture envelope validation;

source-kind routing;

media enrichment request building;

DLQ enrichment;

optional simple ClickHouse ops/audit insert.

Keep current Go materializer writing Pebble/ClickHouse/Typesense.

Phase 3 — Introduce Data Transforms only for tiny stateless paths

Evaluate transforms for:

capture event validity flag;

route topic generation;

redaction/scrubbing;

canary routing.

Do not use transforms for media, model, OCR, or materialization. They have no external disk/network access and process only new records after deployment.
Redpanda Documentation
+1

Phase 4 — Production cutover for routing

When shadow parity is good:

Connect custom distro produces evidence.*.observed.v1
Go materializer consumes evidence.*.observed.v1

The Go materializer no longer consumes raw capture events except as fallback.

Phase 5 — Expand carefully

Only after canary parity:

add Connect pipelines for media routing;

add Connect status/log topics;

add Redpanda Console visibility;

gradually retire duplicated code in Go normalizer.

7. Pitfalls
At-least-once semantics

Assume duplicates. All sinks must be idempotent:

Pebble keys deterministic;

ClickHouse append rows with unique IDs or dedupe views;

Qdrant deterministic point IDs;

Typesense deterministic document IDs;

artifact paths content-addressed.

Redpanda Connect and Data Transforms are both at-least-once, so do not design for exactly-once cross-store writes.
Redpanda Documentation
+1

External state in Connect

Avoid persistent dedupe inside Connect before outputs. Redpanda’s docs explicitly warn that persistent external state can violate at-least-once guarantees if a pipeline crashes after marking a message processed but before output succeeds.
Redpanda Documentation

Backpressure

Connect slow outputs throttle inputs. Use bounded buffers only to smooth spikes, not to hide slow sinks. Redpanda Connect docs note buffers are fixed-capacity and block input when full.
Redpanda Documentation

Plugin deployment

Compiled plugins require rebuilding the Connect binary. Dynamic plugins can deploy independently, but add process/socket/version complexity. Treat plugin version as part of every output event.

Data Transform resource risk

Transforms run inside broker-controlled Wasm environments. Keep them cheap. Do not put expensive validation, JSON parsing of huge records, image work, or network calls in transforms.

DLQs

Every pipeline should have a DLQ topic with:

original topic;

original partition/offset/key;

payload hash;

schema version;

error class;

error message;

processor/plugin name;

plugin version;

trace ID.

Schema evolution

Use versioned topics for breaking changes:

evidence.media.observed.v1
evidence.media.observed.v2

Use additive fields only inside v1. Keep event envelope stable.

Observability

Add:

Connect status topic;

Connect logs topic;

plugin metrics;

per-plugin latency;

per-plugin error count;

DLQ count;

lag per consumer group;

canary status.

Redpanda Connect’s Redpanda component supports logs and status topics through its configuration service.
Redpanda Documentation

8. Target architecture
v1.1 target
Mac collectors
  -> Redpanda topic evidence.capture.events.v1

Redpanda Connect sidecar, shadow mode
  -> validates/projects capture events
  -> writes evidence.capture.shadow.observed.v1
  -> writes DLQ on failures

Current Go normalizer/materializer
  -> still production path
  -> observed/state topics
  -> Pebble
  -> ClickHouse
  -> Typesense
  -> enrichment request topics

Python workers
  -> consume request topics directly
  -> produce completed/failed topics

Dashboard
  -> custom retrieval coordinator

v1.1 goal: prove Connect plugins can match normalizer output for selected source kinds.

v1.2 target
Mac collectors
  -> Redpanda Streaming topics

Redpanda Data Transforms
  -> optional tiny broker-local validation/routing only

Redpanda Connect custom distribution
  -> capture validation
  -> source-kind projection
  -> observed topic emission
  -> media enrichment request routing
  -> DLQ enrichment
  -> ops/audit sink

Go materializer service
  -> consumes observed topics only
  -> Pebble/ClickHouse/Typesense/Qdrant coordination

Python inference/media services
  -> consume request topics directly
  -> write result topics and derived artifacts

Dashboard
  -> exact + Typesense + Qdrant + ClickHouse retrieval

v1.2 goal: normalizer routing is Redpanda Connect-native; stateful materialization remains custom and reliable.

9. Prioritized implementation checklist
P0 — Architecture/documentation

Add docs/REDPANDA_NATIVE_ARCHITECTURE.md.

Update docs to say “Redpanda Streaming topics” instead of “Kafka topics” except when explicitly discussing Kafka-compatible APIs.

Add docs/TOPIC_CATALOG.md with:

topic name;

owner;

producer;

consumers;

retention/compaction;

schema;

DLQ;

canary coverage.

Update AGENTS.md to say:

Redpanda-first terminology;

Kafka-compatible APIs are allowed as Redpanda data-plane clients;

do not replace working direct clients without parity canary;

Connect YAML is wiring, not business logic.

P0 — Connect skeleton

Add connect/ directory:

connect/pipelines/

connect/plugins/

cmd/web-osint-connect/

Build custom Redpanda Connect distribution with one compiled plugin:

capture_envelope_validate.

Add one shadow pipeline:

input: evidence.capture.events.v1

processor: capture_envelope_validate

output: evidence.capture.shadow.validated.v1

DLQ: evidence.capture.shadow.errors.v1.

P0 — Parity canary

Extend existing e2e canary to check shadow output exists.

Add parity diff:

current Go normalizer observed event;

Connect shadow observed event;

compare stable IDs, source kind, evidence ID, title/path/hash, core payload.

P1 — Move stateless routing

Add compiled plugins:

source_kind_router

observed_event_projector

media_request_builder

dlq_enricher

Run shadow for:

user_input

media

web_document

Keep Go materializer as production.

P1 — Media routing via Connect

Move only media enrichment request building to Connect after parity.

Keep PaddleOCR/Qwen workers consuming request topics directly.

Add DLQ metrics and request topic lag metrics.

P1 — Optional Data Transform trial

Add one tiny Data Transform only if useful:

e.g. capture_event_minimal_validate

input: evidence.capture.events.v1

output: evidence.capture.validated.v1 or evidence.capture.invalid.v1

Do not put any stateful or external I/O in it.

P2 — Production cutover

Switch observed-topic production from Go normalizer to Connect only after:

canary passes;

shadow parity passes;

DLQ rate acceptable;

replay/backfill story documented.

Reduce Go normalizer to materializer-only.

Keep rollback path: Go normalizer can resume observed-topic production.

Bottom line

Use Redpanda Connect + compiled Go plugins to own deterministic stream routing and validation. Use Data Transforms only for tiny broker-local stateless transformations. Keep custom services for stateful materialization, search coordination, OCR, and Qwen inference. Do not chase “no Kafka API” purity; Redpanda’s data plane is Kafka-compatible by design. The Redpanda-native win is architectural ownership by Redpanda Streaming/Connect/Transforms, not renaming every client library.
