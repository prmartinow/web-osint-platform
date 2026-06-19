# Research UI And Extraction Direction

This platform has two distinct user surfaces:

- **Metrics dashboard:** infrastructure health, flow, lag, store status, workers, model services, and stage data.
- **Research workbench:** human-led inspection, search, comparison, curation, and publication of normalized evidence.

The research workbench is case-centric. It should help the operator move from capture to evidence to claims without hiding the original source.

## Rebrowser Requirement

Rebrowser remains the required rendered-browser collection and escalation surface for Google, X, and dynamic webpages. Generic browser automation advice should be translated into the preserved Rebrowser/CDP profile and its site-specific pacing rules.

Static HTTP extraction is allowed for ordinary pages, but it is not the final answer when the content is dynamic, missing, gated behind interaction, or visibly richer in the browser. In those cases the collector should capture rendered DOM and visual artifacts through Rebrowser, then publish the result through the same capture envelope.

## Capture-First Extraction

The webpage extraction path should preserve multiple representations:

- Raw HTML and headers.
- Rendered DOM or page text when Rebrowser is needed.
- Readable text and Markdown projections.
- Tables, headings, links, metadata, images, JSON-LD, and source artifacts.
- OCR/VL outputs for screenshots, videos, diagrams, tables, charts, and UI captures.

Do not make Markdown, cleaned HTML, screenshots, or extractor output the canonical source of truth. They are useful projections over immutable capture artifacts.

## EvidenceDocument

The canonical normalized page representation is a versioned `EvidenceDocument`.

```text
Source
-> Capture(s)
-> EvidenceDocument revision
-> Blocks + assets + anchors
-> Evidence, claims, entities, relations, review tasks, publications
```

An `EvidenceDocument` contains:

- Source metadata: URL, canonical URL, domain, title, published time, topics.
- Capture metadata: collector run, capture method, time, status, hashes, artifact paths.
- Blocks: title, summary, headings, paragraphs, tables, lists, code, quotes, or other typed content.
- Assets: images, screenshots, videos, diagrams, PDFs, source bundles, and OCR/VL artifacts.
- Anchors: text quotes, extracted order, DOM paths when available, visual bounding boxes when available, and artifact references.
- Omitted-content records when the compact event hides content that still exists in artifacts.

The current v1 worker writes `evidence_document` JSON artifacts for static webpage extraction. Rebrowser-rendered captures should write the same shape when that path is implemented.

## Research Workbench

The research workbench should organize around the operator workflow:

```text
Capture
-> Triage
-> Inspect
-> Extract evidence
-> Resolve entities
-> Form claims
-> Compare
-> Review
-> Publish
```

Core objects:

- `Source`: external page, post, account, repo, paper, video, or manual file.
- `Capture`: immutable collection event with method, time, run, and raw artifacts.
- `EvidenceDocument`: normalized block-and-asset model.
- `Evidence`: anchored passage, table cell, image region, OCR block, or source span.
- `Entity`: account, person, lab, model, repo, paper, benchmark, hardware, or topic.
- `Claim`: contestable statement with source support, contradiction, and review state.
- `Relation`: typed connection between entities, claims, sources, and topics.
- `Publication`: reviewed release or website-ready output with source backlinks.

## UI Principles

- Keep metrics and research work separated.
- Show source and normalized content side by side when possible.
- Preserve raw artifacts and make omissions inspectable.
- Treat evidence as anchored, claims as contestable, and entities as projections.
- Make graph views secondary to inspection, comparison, and curation.
- Keep v1 human-led; autonomous research loops are deferred.
