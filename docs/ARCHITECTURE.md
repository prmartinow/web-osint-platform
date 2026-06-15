# Architecture

Web OSINT Platform is a streaming evidence infrastructure stack for automated internet research.

## Layers

```text
Collection
  Browser/API collectors extract complete evidence records.

Ingress
  A local outbox and producer publish records to Redpanda.

Event Log
  Redpanda stores append-only capture history and compacted state topics.

Processing
  The normalizer/materializer validates, normalizes, and fans records out.

Serving Stores
  Pebble: exact lookup
  Typesense: keyword and facet search
  Qdrant: semantic/vector retrieval
  ClickHouse: analytics and rollups
  Filesystem: media and OCR artifacts

Meaning Layer
  Versioned annotations, entities, claims, relations, benchmark facts,
  release signals, research signals, questions, tasks, and wiki projections.

Consumption
  Agents, dashboards, research reports, and websites query the serving stores.
```

## Topic Families

Append-only observation topics:

```text
evidence.capture.events.v1
evidence.posts.observed.v1
evidence.accounts.observed.v1
evidence.media.observed.v1
evidence.search.results.v1
```

Compacted state topics:

```text
evidence.posts.state.v1
evidence.accounts.state.v1
evidence.media.state.v1
```

Error topic:

```text
evidence.index.errors.v1
```

Meaning Layer append-only topics:

```text
osint.semantic.segmented.v1
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

Redpanda is the durable replay source. It is not the query database.

Pebble is a rebuildable exact-lookup view for stable IDs such as `post/<post_id>`, `account/<handle>`, `media/<media_id>`, and `capture/<collector_run_id>:<event_index>`.

Typesense is the interactive lexical and faceted search layer.

Qdrant is the semantic retrieval layer. The initial collection uses named vectors for `text_dense`, `ocr_dense`, `caption_dense`, and `account_dense`.

ClickHouse is the analytics layer for evidence events, entities, claims, labels, source activity, timelines, and collector health.

Large media and OCR artifacts should live on the filesystem with content-addressed paths. Store paths and hashes in event/state records.

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
