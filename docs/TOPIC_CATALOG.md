# Topic Catalog

This catalog names each Redpanda topic's responsibility, owner, expected
producers/consumers, cleanup policy, and DLQ/canary coverage. It is the
operator-facing map for replay, parity checks, and future Connect migration.

## Capture And Observed Evidence

| Topic | Owner | Producer | Consumers | Policy | Schema | DLQ | Canary |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `evidence.capture.events.v1` | collection | Mac/RPC producers, canaries | normalizer/materializer, shadow Connect, production Connect router | delete | `schemas/capture_event.schema.json` | `evidence.index.errors.v1`, `evidence.capture.shadow.errors.v1` | E2E, media |
| `evidence.posts.observed.v1` | normalization | production Connect router; normalizer fallback | embedding worker, materializer/search | delete | `schemas/post_observed.schema.json` | `osint.semantic.deadletter.v1` | E2E |
| `evidence.accounts.observed.v1` | normalization | production Connect router; normalizer fallback | embedding worker, materializer/search | delete | current payload contract | `osint.semantic.deadletter.v1` | E2E |
| `evidence.media.observed.v1` | normalization | production Connect router; normalizer fallback | embedding worker, media request route | delete | current payload contract | `osint.semantic.deadletter.v1` | media |
| `evidence.search.results.v1` | normalization | production Connect router; normalizer fallback | embedding worker, materializer/search | delete | `schemas/search_result.schema.json` | `osint.semantic.deadletter.v1` | E2E |
| `evidence.web.documents.observed.v1` | normalization | production Connect router; normalizer fallback | embedding worker, materializer/search | delete | `schemas/web_document.schema.json` | `osint.semantic.deadletter.v1` | E2E |
| `evidence.user.inputs.observed.v1` | normalization | production Connect router; normalizer fallback | embedding worker, materializer/search | delete | `schemas/user_input.schema.json` | `osint.semantic.deadletter.v1` | E2E |

## Compacted State Topics

| Topic | Owner | Producer | Consumers | Policy | Key |
| --- | --- | --- | --- | --- | --- |
| `evidence.posts.state.v1` | materializer | normalizer/materializer | state rebuild/admin | compact | post ID |
| `evidence.accounts.state.v1` | materializer | normalizer/materializer | state rebuild/admin | compact | normalized handle |
| `evidence.media.state.v1` | materializer | normalizer/materializer | state rebuild/admin | compact | media ID / SHA |
| `evidence.web.documents.state.v1` | materializer | normalizer/materializer | state rebuild/admin | compact | document ID |
| `evidence.user.inputs.state.v1` | materializer | normalizer/materializer | state rebuild/admin | compact | input ID |

## Meaning And Enrichment Topics

| Topic | Owner | Producer | Consumers | Policy | Canary |
| --- | --- | --- | --- | --- | --- |
| `osint.semantic.embedded.v1` | embedding | embedding worker | canary, dashboard/admin, analytics | delete | E2E |
| `osint.semantic.deadletter.v1` | embedding | embedding worker | operators | delete | E2E failure paths |
| `osint.label.proposed.v1` | meaning | deterministic labeler | planner, analytics | delete | E2E |
| `osint.state.current_labels_by_target.v1` | meaning | deterministic labeler | state rebuild/admin | compact | E2E |
| `osint.research_signal.detected.v1` | planner | research planner | downstream agents/later loops | delete | planner |
| `osint.research_question.proposed.v1` | planner | research planner | downstream agents/later loops | delete | planner |
| `osint.research_task.created.v1` | planner | research planner | humans/future agents | delete | planner |

## Media Enrichment Topics

| Topic | Owner | Producer | Consumers | Policy | DLQ/Failure |
| --- | --- | --- | --- | --- | --- |
| `osint.media.enrichment.requested.v1` | media router | production Connect router; media router fallback | OCR/VL routers | delete | failed lane topics |
| `osint.media.ocr.requested.v1` | OCR | production Connect router; media router fallback | OCR worker | delete | `osint.media.ocr.failed.v1` |
| `osint.media.ocr.completed.v1` | OCR | OCR worker | canary, analytics | delete | n/a |
| `osint.media.ocr.failed.v1` | OCR | OCR worker | operators, dashboard | delete | n/a |
| `osint.media.vl_embedding.requested.v1` | VL | production Connect router; media router fallback | VL worker | delete | `osint.media.vl_embedding.failed.v1` |
| `osint.media.vl_embedding.completed.v1` | VL | VL worker | canary, analytics | delete | n/a |
| `osint.media.vl_embedding.failed.v1` | VL | VL worker | operators, dashboard | delete | n/a |

## Review And Curation Topics

| Topic | Owner | Producer | Consumers | Policy | Schema | Purpose |
| --- | --- | --- | --- | --- | --- | --- |
| `research.review.events.v1` | research UI | Source Workbench / review API | review materializer, ClickHouse projections | delete | `schemas/research_review_event.schema.json` | Append-only user and reviewer actions: evidence selections, annotations, proposed facts, entity links, claim stubs, and review-state changes |

## Shadow Connect Topics

These topics are not production-serving. They exist to prove Redpanda Connect
compiled plugins match the materialized output and stay healthy after cutover.

| Topic | Owner | Producer | Consumers | Policy | Purpose |
| --- | --- | --- | --- | --- | --- |
| `evidence.capture.shadow.validated.v1` | Connect shadow | `web-osint-connect` | canary/parity checks | delete | capture envelope validated by compiled plugin |
| `evidence.capture.shadow.errors.v1` | Connect shadow | `web-osint-connect` | operators/canary | delete | validation or pipeline errors with original offset metadata |
| `evidence.capture.shadow.observed.v1` | Connect shadow | `observed_event_projector` | canary/parity checks | delete | shadow observed-event wrappers for normalizer parity checks |
| `osint.media.enrichment.shadow.requested.v1` | Connect shadow | `media_enrichment_request_builder` | canary/parity checks | delete | shadow-only media request wrappers; never consumed by OCR/VL workers |

## Catalog Rules

- Additive fields may stay in a `.v1` topic. Breaking payload changes require a
  `.v2` topic.
- Every new production topic needs an owner, producer, consumer group, cleanup
  policy, and failure route before deployment.
- Shadow topics must never become serving-store input until parity canaries pass
  and rollback is documented.
- DLQ payloads must include original topic, partition, offset, key, payload hash,
  schema version, error class, processor/plugin name and version, and trace ID
  when available.
