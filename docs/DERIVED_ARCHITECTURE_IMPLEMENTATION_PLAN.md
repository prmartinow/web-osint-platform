# Web OSINT Derived Architecture And Implementation Plan

Date: 2026-06-19

This plan folds the 21 completed research-agent jobs into the Web OSINT implementation roadmap. It is the implementation-facing companion to `RESEARCH_UI_PRODUCT_SPEC.md`, `ARCHITECTURE.md`, and `SOURCE_WORKBENCH_IMPLEMENTATION_PLAN.md`.

## Source Base

Primary synthesis:

```text
/Users/user/Documents/Ops/research/web_osint_research_agent_synthesis_20260619.md
```

Raw research-agent transcripts:

```text
/Users/user/Documents/Ops/research/cb_scheduled_research_20260619/transcripts/
```

The 21 jobs covered web/HTML extraction, research UI design, retrieval model categories, extraction/factuality/OCR/VLM model categories, metrics design for Redpanda/Pebble/Typesense/Qdrant/ClickHouse, and overall platform architecture.

## Architecture Decision

The platform should be a provenance-first, human-led Web OSINT research workbench.

It is not:

- a chatbot with hidden source state
- an autonomous research agent loop in v1
- a generic document repository
- a metrics dashboard with research features bolted on
- a vector database application with source capture as an afterthought

The core v1 loop is:

```text
collect evidence
-> normalize it into reviewable source documents
-> enrich it with model/deterministic observations
-> let the user inspect, select, correct, annotate, compare, and curate
-> publish or reuse frozen reviewed outputs
```

The core data rule remains:

```text
captured evidence
-> derived observations
-> curated assertions
-> published claims
```

Do not collapse these layers. OCR text, VLM descriptions, entity matches, relation candidates, structured JSON, classifier labels, and factuality scores are observations or suggestions until validated against source anchors and review state.

## Derived Reference Architecture

The target system has one canonical write path and many rebuildable projections.

```text
Rebrowser / source-native adapters / manual docs
-> CaptureEnvelope + immutable artifacts
-> Redpanda topics and Redpanda Connect routing
-> normalizer and materializers
-> EvidenceDocument revisions and artifact catalog
-> observation workers
-> projections: Pebble, Typesense, Qdrant, ClickHouse, graph later
-> Research UI review and curation
-> PublicationSnapshot/export/public website
```

Rebrowser is the live collection surface for visible web evidence. The Research UI is the inspection and curation surface over captured evidence. Do not make the Research UI depend on live upstream websites for ordinary review.

### Canonical Layers

| Layer | Purpose | Mutability | Examples |
|---|---|---|---|
| Capture | Preserve what was observed | Immutable | X post capture, web page raw/rendered bundle, GitHub commit view, manual document ingest |
| Artifact | Store bytes and media | Immutable/content-addressed | HTML, rendered DOM, screenshot, video, image crop, OCR JSON, transcript, source bundle |
| EvidenceDocument | Versioned normalized view over a capture | Append revisions, never overwrite capture | Blocks, tables, assets, anchors, omitted content, extraction metadata |
| Observation | Machine or deterministic derived output | Append-only, reviewable | entity mention, OCR block, classifier label, proposed relation, vector metadata |
| Review/Curation | Human decisions and corrected state | Event-sourced | evidence selection, annotation, entity link, accepted proposed fact, claim review |
| Projection | Query-optimized rebuildable state | Rebuildable | Pebble exact lookup, Typesense search, Qdrant vectors, ClickHouse marts |
| Publication | Frozen approved output | Immutable release snapshots | Neural Node page update, static report, benchmark table, citation bundle |

### Core Objects

The implementation should converge on these objects:

- `SourceLocator`: URL, platform ID, query, repo path, paper ID, or manual document ID.
- `Capture`: immutable observation with timestamps, headers/redirects where relevant, collector run, source identity, hashes, and interaction recipe.
- `Artifact`: content-addressed file or media item with type, hash, path, derived-from links, and access policy.
- `ContentVersion` / `EvidenceDocument`: normalized source representation with blocks, assets, omitted content, anchors, and extraction run metadata.
- `Segment`: text span, table cell, image region, OCR block, video time range, repo line range, or other reviewable source fragment.
- `Run`: collector/extractor/model execution record with inputs, model/tool version, config, timing, failures, and output artifact IDs.
- `Observation`: model or deterministic output anchored to a source segment.
- `EntityMention`: source-linked mention span or deterministic ID occurrence.
- `Entity`: reviewed canonical thing such as lab, model, repo, benchmark, paper, hardware, person, account, or topic.
- `Assertion`: accepted or contested human-curated statement derived from evidence.
- `EvidenceLink`: support, refute, mention, context, or uncertainty link between assertion/entity and segment.
- `Assessment`: verifier or reviewer judgment with dimensions, not one truth score.
- `Workspace` / `Case` / `Collection`: human research scope and queue context.
- `PublicationSnapshot`: frozen release bundle with citations and provenance.
- `PolicyMarking`: source sensitivity, visibility, public-export eligibility, and redaction state.

### Time Model

The platform must keep multiple time dimensions:

- source published time
- source updated time
- capture time
- ingestion time
- extraction/enrichment time
- review time
- publication time

Do not infer one from another unless explicitly recorded.

## Capture And Web Extraction Architecture

The web extraction research converged on a capture-first, multi-representation model.

Implementation direction:

- Use source-native adapters first for GitHub, Hugging Face, arXiv, benchmark APIs, model registries, and other structured authoritative sources.
- Use static extraction for suitable web pages and batch parsing: Trafilatura, Mozilla Readability, direct DOM segmentation, metadata extraction, table/link/image extraction, and optional rs-trafilatura/Resiliparse bakeoffs.
- Use Rebrowser-rendered capture when the user inspected a visible page, dynamic content matters, page state matters, X/Google pacing matters, static extraction misses important blocks, or screenshots/media/layout are evidence.
- Store immutable capture bundles: requested URL, final URL, redirects, headers, raw bytes, decoded HTML, rendered DOM when used, screenshots/crops, network JSON/CSV when relevant, hashes, timestamps, interaction recipe, and collector metadata.
- Preserve omitted/chrome blocks as inspectable omitted-content records. Do not permanently delete content just because an extractor marks it as boilerplate.
- Treat WARC/WACZ as promotion for pinned, volatile, public, or replay-critical sources, not mandatory for every routine capture.

Canonical page output is a versioned `EvidenceDocument`. Markdown, clean HTML, readable text, screenshots, and parser output are projections.

## Research UI Architecture

The Research UI is separate from the metrics dashboard.

Primary workflow:

```text
Inbox
-> Source Workbench
-> Evidence extraction
-> Entity resolution
-> Claim/proposed fact review
-> Compare/benchmark views
-> Review
-> Publication draft
```

The Inbox unit is a review task, not just a source row. One source can produce multiple tasks: extraction review, OCR review, entity merge candidate, contradiction candidate, publication blocker, or stale claim.

The Source Workbench should be the central screen:

```text
header: source identity, capture/version, integrity, project/review status
left:   source/artifact navigator
center: original, normalized, or side-by-side viewer
right:  evidence, annotations, entities, claims, observations, provenance, review actions
```

Evidence creation must work from selected text, table cells, image regions, OCR blocks, video timestamps, screenshots, repository lines, and whole-source references.

Entity pages are evidence-backed fact ledgers, not freeform profiles. Comparison tables and benchmark views must keep method, benchmark version, dataset/version, metric units, run configuration, source type, evidence count, and review status.

## Metrics Dashboard Architecture

The metrics dashboard remains an operations surface. It should not host research UI product screens.

Shared stage metrics:

- events by stage/source/status
- stage latency p50/p95/p99
- queue age and lag
- retry/DLQ counts and error classes
- artifact bytes by type
- external request latency
- model inference latency, queue depth, and failures
- store write/search latency and freshness

Per-tool direction:

- Redpanda: Prometheus/Grafana plus Redpanda Console drilldown; show topic throughput, consumer lag, DLQ, Connect pipeline status, partition health, queue freshness, and transform/connect health.
- Pebble: app-owned metrics endpoints over `DB.Metrics()`, key counts by namespace, materializer lag, freshness, compaction/LSM health, read/write smoke, snapshot/backup status.
- Typesense: native `/health`, `/debug`, `/metrics`; app query/import metrics; parse per-document import failures even when import HTTP status is 200; log query/no-hit/facet/filter behavior.
- Qdrant: native `/metrics`, readiness, telemetry, collection/vector counts by named vector, branch freshness, upsert failures, optimizer backlog, strict/recovery mode status, snapshot state.
- ClickHouse: native `/dashboard`, `/ping`, Prometheus, `system.*` tables, query logs, ingest rows/bytes, freshness, parts/merges/mutations, disk pressure, error logs, active queries, Web OSINT ops marts.

## Retrieval Architecture

Baseline remains hybrid retrieval:

```text
metadata filters
-> Typesense keyword/facet candidates
-> Qdrant dense semantic candidates
-> fusion
-> Qwen rerank on bounded candidate sets
-> hydrate from Pebble/ClickHouse/artifacts
```

Accuracy is prioritized over latency, but expensive rerankers and late-interaction models must run on small candidate sets with visible branch scores.

Planned retrieval lanes:

- Exact/keyword lane: Typesense plus deterministic exact sidecars for handles, URLs, model names, version strings, benchmark names, repo IDs, arXiv IDs, hardware SKUs, and metric units.
- Dense semantic lane: Qwen3 text embeddings in Qdrant named vectors.
- Rerank lane: Qwen3-Reranker as explicit precision pass after candidate retrieval.
- Neural sparse lane: evaluate as an additional candidate branch, not a BM25 replacement.
- Late-interaction text lane: evaluate only for high-value precision rerank over small candidate sets.
- Visual retrieval lane: Qwen3-VL image/page/screenshot embeddings first, then visual late-interaction/rerank experiments only after private eval.

Required eval gate:

- Build private Web OSINT retrieval sets before adopting neural sparse, late interaction, or visual reranker upgrades.
- Evaluate citation correctness, source-anchor recovery, exact-name recall, filtered retrieval quality, and accepted-evidence-per-review-minute, not only benchmark score.

## Extraction And Enrichment Architecture

Use a grounded cascade:

```text
deterministic extraction
-> model-generated candidate observations
-> schema/source-anchor validation
-> human review
-> curated assertion or rejected suggestion
```

### Entity Extraction

V1 begins with deterministic extractors for URLs, X handles, GitHub repos, Hugging Face model IDs, arXiv IDs, DOIs, semantic versions, model sizes, hardware/SKU strings, and metrics/units.

Then add GLiNER-family entity mention extraction and canonical candidate generation. No entity enters the graph without a source-linked mention span, deterministic ID, or reviewer-created record.

### Relation And Event Extraction

Run relation/event extraction only after entity mentions exist. GLiNER-Relex, GLiDRE, and GLiREL are candidate families. Outputs are relation/event candidates with evidence IDs, source spans/cells/bboxes, extractor versions, scores, and review status.

### Structured Extraction

Structured extractors create `proposed_fact` rows, not canonical facts.

```text
EvidenceDocument/table/OCR
-> schema-specific extractor
-> JSON Schema validation
-> source-span/table-cell/bbox validation
-> proposed_fact
-> review
```

Candidates include deterministic table extraction, NuExtract-family models, and constrained JSON decoding with local instruction models. JSON validity alone is insufficient.

### Factuality And Entailment

The factuality lane checks a specific claim against a specific source passage. It does not decide global truth.

Candidate roles:

- DeBERTa/mDeBERTa NLI for support/refute/insufficient.
- MiniCheck/HHEM-style grounded support scoring.
- LettuceDetect-style unsupported-span detection for summaries and publication drafts.

Store verifier outputs as assessments tied to source anchors and claim IDs.

### OCR, Layout, Tables, Charts, And Visual Documents

Use deterministic layout/OCR first, then VLM/document parsers for hard cases.

Baseline:

- PaddleOCR 3.x and PP-StructureV3-style artifact contract.
- Blocks, polygons/bboxes, reading order, confidence, tables/forms/formulas/charts, model/runtime metadata, and artifact paths.

Hard-case/review lanes:

- PaddleOCR-VL, Docling/SmolDocling/Granite Docling, olmOCR, Surya/LightOnOCR-style models, Qwen3-VL, chart/table-specialist models.

Never publish chart/table-derived benchmark facts without visible region provenance and human review.

## Parallel Execution Plan

The implementation can now run as six coordinated tracks. Each track should
keep its own tests and artifacts, but all tracks must preserve the core
evidence rule:

```text
captures are immutable
observations are suggestions
review events curate state
projections are rebuildable
publication snapshots are frozen
```

| Track | Owner Boundary | Can Run In Parallel With | Main Shared Contract |
|---|---|---|---|
| Source Workbench | Research UI screens, review APIs, entity links, claims, review-task Inbox | capture, extractor, metrics, eval | `research_review_event.v1` and review tables |
| Capture/EvidenceDocument | capture bundles, EvidenceDocument v2, source-native adapters, omitted-content records | UI, extractors, metrics | capture envelope, artifact manifest, block/anchor schema |
| Deterministic Extraction | URL/handle/repo/HF/arXiv/version/hardware/metric extractors | UI, capture, eval | observation/proposed-fact output into review layer |
| Model Preparation | async model downloads, isolated venvs, service wrappers, smoke tests | docs, UI, metrics, eval | no canonical writes until review/eval gates exist |
| Private Evaluation | retrieval, structured extraction, entity, OCR/chart/table, visual eval sets | all tracks | promotion gates for neural/model lanes |
| Metrics Maturity | Redpanda/Pebble/Typesense/Qdrant/ClickHouse/model panels | all tracks | ops dashboard only; no research UI coupling |

Recommended order of execution:

1. Keep the Source Workbench track as the critical path.
2. Run Capture/EvidenceDocument hardening beside it so UI blocks have stronger
   anchors and artifact provenance.
3. Start deterministic extractors early because they are low-risk and feed the
   same review layer.
4. Download and smoke-test candidate models asynchronously under `/mnt/data`,
   but wire them into production only after private evals and review targets
   exist.
5. Build private eval corpora before neural sparse, late-interaction, visual
   reranking, or schema-extraction model adoption.
6. Improve metrics independently in the operations dashboard.

## Implementation Roadmap

### P0A - Durable Review Foundation

Status: first cut implemented.

Implemented:

- separate Research UI service
- review event envelope
- `research_review_events`, `evidence_selections`, `review_annotations`, and `proposed_facts`
- Research UI review APIs
- EvidenceDocument block selection
- durable annotation, evidence selection, and proposed fact creation
- first-cut entity links, claim stubs, normalized correction overlays, generic review-state transitions, and derived review-task Inbox rows
- JSONL mirror under `/mnt/data/x-research/review/events/`
- Datalab smoke validation

Remaining:

- move direct ClickHouse/JSONL writes behind `research.review.events.v1` and a review materializer when UX stabilizes
- add richer source/artifact navigation, persisted task lifecycle/assignment, comparison rows, and publication draft objects

### P0B - Source Workbench Product Shape

Build the real workbench layout:

- source/artifact navigator
- original, normalized, and side-by-side views
- synchronized source anchors where possible
- right-panel review state for selections, annotations, proposed facts, entities, claims, observations, and provenance
- X-first viewer for post/thread/account/media
- web/blog viewer for EvidenceDocument pages
- persisted review-task lifecycle/assignment beyond the current derived Inbox rows

### P0C - Capture And EvidenceDocument Hardening

Implement the missing capture architecture:

- capture bundle manifest
- interaction recipe field for Rebrowser captures
- omitted-content records
- raw/rendered/static extraction provenance
- source-native adapter interface
- GitHub, Hugging Face, and arXiv initial adapters
- WARC/WACZ promotion flag, not always-on archival
- EvidenceDocument v2 contract with blocks, assets, anchors, omitted content, extractor votes, and artifact links

### P1 - Entity, Fact, Claim, And Review Intelligence

Implement the first intelligence workers into the review layer:

- deterministic entity/ID extractors
- entity mention suggestions
- entity link UI and merge/review workflow
- structured proposed-fact worker
- claim stub UI
- claim-to-evidence support/refute/mention links
- NLI/factuality assessment worker after claim IDs are stable

DataLab `lift` should be tracked here as a structured extraction candidate for
PDFs/images/page artifacts. It is a schema-driven vision model that emits JSON
matching a provided JSON Schema. In this architecture, `lift` output must land
as `proposed_fact` rows or extraction observations with source/page/region
provenance, not as canonical facts. Pair it with PaddleOCR/layout artifacts or
other visible anchors so fields can be reviewed before promotion. Treat it as
complementary to OCR/layout and not as an OCR replacement.

### P2 - Visual And Document Evidence

Make screenshots, videos, papers, charts, and tables first-class:

- PaddleOCR/PP-StructureV3 artifact contract
- region/crop objects
- overlay viewer for OCR/layout/VL regions
- video frame/timecode anchors
- chart/table schema validation
- Qwen3-VL visual branch over screenshots/page images
- hard-case document parser queue

### P3 - Retrieval Upgrades Behind Private Evaluation

Do not add retrieval model complexity without private eval.

Build:

- private Web OSINT retrieval/evidence benchmark sets
- exact-name/ID recall suite
- filtered semantic search suite
- visual evidence retrieval suite
- neural sparse bakeoff
- late-interaction text bakeoff
- visual reranker bakeoff
- branch-score explanations in search results

### P4 - Metrics Maturity

Upgrade the metrics dashboard using the per-tool research:

- Redpanda/Connect topic and pipeline health
- Pebble app-owned DB metrics
- Typesense query/import/facet/no-hit metrics
- Qdrant branch freshness and vector coverage
- ClickHouse ops marts over ingest, freshness, queries, parts, errors, and report readiness
- end-to-end freshness: capture to searchable, searchable to reviewed, reviewed to publication-ready

### P5 - Publication And Reuse

Implement frozen output workflows:

- publication draft bundles
- checks for unsupported claims, missing anchors, unresolved contradictions, stale evidence, sensitive-source exposure, broken links, unreviewed AI suggestions
- `PublicationSnapshot` releases
- export to Neural Node/public site projections
- source-linked comparison tables and reports

## Coverage Audit Of The 21 Research Jobs

| Job | Area | Current coverage | Gap now in roadmap |
|---|---|---|---|
| 01 | HTML/web extraction | webpage extraction and Rebrowser rendered capture exist | source-native adapters, extraction ensemble, capture bundles, omitted-content records, WARC/WACZ promotion policy |
| 02 | Research UI design | separate Research UI, Inbox, Source page, Review tab, entity links, and claim stubs exist | review-task Inbox, full source workbench layout, compare, and publishing flows |
| 03 | Neural sparse retrieval | not implemented | private eval, neural sparse lane as candidate branch only |
| 04 | Late-interaction retrieval | not implemented | high-value rerank lane after fusion and private eval |
| 05 | Visual document retrieval | Qwen3-VL path structurally exists | visual retrieval branch, artifact/page/frame indexing, visual eval |
| 06 | LLM/listwise reranking | Qwen reranker exists | model-neutral rerank interface, bounded candidate policy, private rerank eval |
| 07 | Encoder-only classifiers | not implemented | layered classifier/taxonomy workers and disagreement policies |
| 08 | NER/entity extraction | manual entity-link plan only | deterministic extractors, GLiNER suggestions, canonical entity registry |
| 09 | Relation/event extraction | not implemented | relation/event candidate workers after entity mentions |
| 10 | Structured extraction | proposed facts table/UI exists | schema extractors, validation, review promotion |
| 11 | NLI/entailment | not implemented | claim-passage verifier assessments |
| 12 | Document VLMs | Qwen3-VL/PaddleOCR services exist | hard-case document parser queue and model-run provenance |
| 13 | Chart/table VLMs | table blocks partially represented | grounded chart/table extraction with visible region provenance |
| 14 | Visual OCR/layout OCR | PaddleOCR path exists | PP-StructureV3-style artifact contract and overlay UI |
| 15 | Visual retrievers/rerankers | Qwen3-VL embedding path exists | visual reranker and late-interaction experiments behind eval |
| 16 | Redpanda metrics | metrics dashboard exists | topic/consumer/Connect/DLQ drilldowns and semantic app metrics |
| 17 | Pebble metrics | Pebble in stack | app-owned Pebble metrics/read-write smoke/key counts/compaction panels |
| 18 | Typesense metrics | health/search exists | import failure parsing, query logs, no-hit/facet/filter metrics |
| 19 | Qdrant metrics | Qdrant in dashboard | branch freshness, named-vector coverage, upsert failures, telemetry panels |
| 20 | ClickHouse metrics | ClickHouse backing metrics/dashboard | ops marts and system-table panels for freshness, query load, parts, merges, errors |
| 21 | Platform architecture | architecture doc exists | canonical objects, state machines, provenance model, publication snapshots now formalized here |

## Next Implementation Checkpoint

The next implementation checkpoint should not start with another model. It should complete the human-led workbench landing zone:

1. Convert Inbox rows toward review tasks. First-cut derived task rows are implemented; persist task lifecycle/assignment later if needed.
2. Add source/artifact navigator and side-by-side original/normalized source workbench.
3. Add capture bundle manifest and EvidenceDocument v2 fields.
4. Add deterministic entity/ID extractors that write reviewable suggestions.
5. Add private eval scaffolding before retrieval/model lane expansion.
