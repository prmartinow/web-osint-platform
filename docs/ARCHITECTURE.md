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

## Store Responsibilities

Redpanda is the durable replay source. It is not the query database.

Pebble is a rebuildable exact-lookup view for stable IDs such as `post/<post_id>`, `account/<handle>`, `media/<media_id>`, and `capture/<collector_run_id>:<event_index>`.

Typesense is the interactive lexical and faceted search layer.

Qdrant is the semantic retrieval layer. The initial collection uses named vectors for `text_dense`, `ocr_dense`, `caption_dense`, and `account_dense`.

ClickHouse is the analytics layer for evidence events, entities, claims, labels, source activity, timelines, and collector health.

Large media and OCR artifacts should live on the filesystem with content-addressed paths. Store paths and hashes in event/state records.
