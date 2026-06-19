# Architecture

Web OSINT Platform is a streaming evidence infrastructure stack for automated internet research.

## Layers

```text
Collection
  Rebrowser is the first-choice rendered-browser collection surface for Google,
  X, and web pages that matter as research evidence. Browser/API collectors
  extract complete evidence records. Website pages, search results, social
  posts, media, and user notes share the same capture envelope.

Ingress
  A local outbox and producer publish records to Redpanda.

Event Log
  Redpanda Streaming stores append-only capture history and compacted state
  topics. Kafka-compatible client APIs are a data-plane detail, not the
  architecture name.

Stream Plumbing
  Redpanda Connect hosts compiled Go plugins for stateless validation,
  projection, routing, and DLQ enrichment. Shadow pipelines keep proving parity;
  the guarded production router owns observed-topic and media request fan-out.

Processing
  The normalizer/materializer keeps raw-capture materialization and owns
  stateful Pebble/ClickHouse/Typesense/Qdrant writes. In production routing mode
  it runs with observed-topic emission disabled, and can resume that emission as
  fallback.
  The webpage extraction worker is an auxiliary parser/enrichment path for URLs,
  launch blogs, docs pages, model cards, and research result pages that need
  HTML/text/Markdown/table artifacts. Rebrowser capture remains the preferred
  browser evidence path; static extraction should complement it, not displace it.
  The embedding worker enriches observed evidence with local Qwen vectors and
  upserts them into Qdrant.
  The research planner derives research signals, questions, and task seeds
  from recent semantic annotations and evidence.

Serving Stores
  Pebble: exact lookup
  Typesense: keyword and facet search
  Qwen inference: CPU text embeddings, reranking, and experimental VL embeddings
  Qdrant: semantic/vector retrieval
  ClickHouse: analytics and rollups
  Filesystem: media and OCR artifacts

Meaning Layer
  Versioned annotations, entities, claims, relations, benchmark facts,
  release signals, research signals, questions, tasks, and wiki projections.

Consumption
  The metrics dashboard, separate Research UI service, agents, research reports,
  and websites query the serving stores.
```

## Topic Families

Append-only observation topics:

```text
evidence.capture.events.v1
evidence.posts.observed.v1
evidence.accounts.observed.v1
evidence.media.observed.v1
evidence.search.results.v1
evidence.web.documents.observed.v1
evidence.user.inputs.observed.v1
```

Compacted state topics:

```text
evidence.posts.state.v1
evidence.accounts.state.v1
evidence.media.state.v1
evidence.web.documents.state.v1
evidence.user.inputs.state.v1
```

Error topic:

```text
evidence.index.errors.v1
```

Meaning Layer append-only topics:

```text
osint.semantic.segmented.v1
osint.semantic.embedded.v1
osint.label.proposed.v1
osint.label.feedback.v1
osint.label.resolved.v1
osint.entity.mentioned.v1
osint.entity.resolved.v1
osint.claim.extracted.v1
osint.relation.extracted.v1
osint.benchmark_fact.extracted.v1
osint.release_signal.detected.v1
osint.research_signal.detected.v1
osint.research_question.proposed.v1
osint.research_task.created.v1
osint.wiki.page_materialized.v1
osint.web.extraction.requested.v1
osint.web.extraction.failed.v1
osint.semantic.deadletter.v1
```

Meaning Layer compacted state topics:

```text
osint.state.current_labels_by_target.v1
osint.state.entity_by_alias.v1
osint.state.entity_current.v1
osint.state.claim_current.v1
osint.state.open_tasks_by_dedupe_key.v1
osint.state.wiki_page_current.v1
```

## Store Responsibilities

Redpanda Streaming is the durable replay source. It is not the query database.
Redpanda Connect is the preferred future host for stateless validation and
routing plugins. Redpanda Data Transforms are reserved for tiny broker-local
single-record transforms only.

Pebble is a rebuildable exact-lookup view for stable IDs such as `post/<post_id>`, `account/<handle>`, `media/<media_id>`, `web_document/<document_id>`, `user_input/<input_id>`, and `capture/<collector_run_id>:<event_index>`.

Typesense is the interactive lexical and faceted search layer.

Qdrant is the semantic retrieval layer. The default local inference plan uses `Qwen/Qwen3-Embedding-8B` for text embeddings and `Qwen/Qwen3-Reranker-8B` for cross-encoder reranking, with BM25/keyword/metadata filters still handled by Typesense and payload indexes. Qwen3-Embedding-8B emits native 4096-dimensional vectors, so the Qdrant collection uses 4096-dimensional named vectors for `text_dense`, `ocr_dense`, `caption_dense`, and `account_dense`.

For screenshots, charts, UI captures, benchmark tables, and images where OCR may miss layout or visual context, the platform reserves an experimental multimodal vector path backed by `Qwen/Qwen3-VL-Embedding-8B`. The `vl_image_dense` named vector is also 4096-dimensional and is intended for screenshot/image-level evidence rather than ordinary text chunks.

ClickHouse is the analytics layer for evidence events, entities, claims, labels, source activity, timelines, and collector health.

Large media and OCR artifacts should live on the filesystem with content-addressed paths. Store paths and hashes in event/state records.

## Evidence Inputs

Collectors should emit one `capture_event` to `evidence.capture.events.v1` for each coherent browser/API collection step. A capture event can include:

- `posts`: social posts/statuses, usually from X.
- `accounts`: social account/profile observations.
- `media`: images, videos, screenshots, OCR artifacts, or other media objects.
- `search_results`: search result rows from Google or another search engine.
- `web_documents`: opened pages, articles, blog posts, documentation pages, model cards, leaderboards, PDFs, and table snapshots.
- `user_inputs`: user-supplied notes, corrections, pasted research, attachments, seeds, and instructions that should become queryable evidence.

The normalizer materializes all of these into shared serving stores while preserving source-specific fields inside the raw JSON. Website content and user input are not side channels; they are first-class evidence with provenance and Meaning Layer annotations.

Rebrowser-rendered capture is the primary capture path for opened research pages. The `collectors/rebrowser-rendered-web` collector preserves the visible browser state, interaction context, dynamic DOM, screenshots/media, and source provenance the user actually inspected, then publishes the page as a standard `web_documents` capture event. Generic Playwright/Chrome collection advice should be translated into the preserved Rebrowser profile and site-specific pacing rules.

The webpage extraction worker is a companion parser/enrichment bridge, not the primary browser capture path. It fetches HTML, extracts readable article text, Markdown, tables, metadata, links, headings, images, canonical URLs, filesystem artifact paths, and a versioned `EvidenceDocument` block/asset artifact, then publishes the result as a standard `web_documents` capture event. Use it when HTTP extraction is explicitly appropriate, for batch parsing, or to enrich a Rebrowser-captured source with additional normalized projections.

## Evidence Document Model

The canonical normalized page representation is a versioned `EvidenceDocument`; Markdown, cleaned HTML, screenshots, and readable text are projections over immutable source artifacts.

```text
Source
-> Capture(s)
-> EvidenceDocument revision
-> Blocks + assets + anchors
-> Evidence, claims, entities, relations, review tasks, publications
```

An `EvidenceDocument` contains source metadata, capture metadata, content blocks, media/assets, source anchors, omitted-content records, and links to raw artifacts. Anchors can target exact text quotes, extracted order, DOM paths when available, visual bounding boxes when available, table rows/cells, OCR blocks, or artifact paths. Rebrowser-rendered captures should write the same shape as the static webpage extraction worker.

## Research UI Product Boundary

The Research UI is a separate app/service, not a metrics-dashboard tab. The metrics dashboard remains dedicated to infrastructure health, pipeline stages, stores, workers, and model services. The Research UI starts with an Inbox and handles human source triage, source inspection, evidence extraction, normalized-content editing, entity and claim work, comparison, review, and publication preparation.

The Research UI workflow is:

```text
Inbox -> Source workbench -> Extract evidence -> Resolve entities
-> Form claims -> Compare -> Review -> Publish
```

Core objects are `Source`, `Capture`, `EvidenceDocument`, `Evidence`, `Entity`, `Claim`, `Relation`, `Annotation`, `Review task`, and `Publication release`. The first v1 validation case is the Datalab Chandra 2.1 X post and blog. Source viewer priority is X first, then web/blog. V1 editing includes evidence selection, normalized extraction correction, entity links, claims, annotations, review state, comparison rows, and publication drafts. Autonomous research loops are deferred.

## Meaning Layer

The Meaning Layer turns raw captures into agent-usable research memory. It is event-sourced and append-only: labels, entity mentions, claims, relationships, benchmark facts, release signals, research signals, questions, tasks, and generated wiki pages are stored as derived objects with provenance.

The core rule is:

```text
labels are annotations, not document fields
```

An annotation can target a whole evidence item, a text span, a table row or cell, an image region, an OCR block, a video/audio segment, a URL, or a user-note span. Current labels and wiki pages are projections over the annotation ledger, so older captures can be relabeled when taxonomy versions or extractors improve.

Stable label families:

```text
source
modality
content_form
topic
entity
semantic_act
claim_type
relation
stance
sentiment
evidence_quality
novelty_signal
actionability
quality
```

The labels inside each family are versioned concepts in `label_concepts`. Unknown content should become an emerging topic, taxonomy gap, or review action rather than a permanent `misc` bucket.

High-value extracted objects are promoted from the generic annotation ledger into typed ClickHouse tables such as `claim_assertions`, `relation_assertions`, `benchmark_facts`, `release_signals`, `research_signals`, `research_questions`, and `autonomous_tasks`. Generated wiki pages are derived projections and must keep backlinks to source evidence and annotation IDs.

The initial research planner is deliberately deterministic. It scans recent evidence and annotations, identifies actionable signals such as user-supplied seeds, comparison opportunities, verification needs, and source-expansion leads, then writes deduped rows to `research_signals`, `research_questions`, and `autonomous_tasks` while also publishing replay events to the matching `osint.*` topics. Later LLM or human feedback loops can replace or augment this planner without changing the storage contract.

## Redpanda-Native Migration

The target migration is:

```text
v1.1:
  Redpanda Connect runs shadow validation/projection topics
  canaries compare shadow output against materialized output

v1.2:
  Redpanda Connect emits observed topics and media requests for proven stateless routing
  Go normalizer/materializer keeps stateful store writes from raw captures
  Go observed-topic emission and legacy media router remain fallback paths
  Python Qwen/OCR/VL services keep direct Redpanda topic consumers
```

See [Redpanda Native Architecture](REDPANDA_NATIVE_ARCHITECTURE.md) and
[Topic Catalog](TOPIC_CATALOG.md). See
[Research UI Product Spec](RESEARCH_UI_PRODUCT_SPEC.md) for the separate
Research UI service, Inbox-first flow, and source workbench product contract.
