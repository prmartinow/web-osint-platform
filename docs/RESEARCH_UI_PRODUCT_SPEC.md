# Research UI Product Spec

The Research UI is a separate human research product surface for Web OSINT evidence work. It must not live inside the infrastructure metrics dashboard.

This spec is the product surface for the broader architecture in
[Derived Architecture Implementation Plan](DERIVED_ARCHITECTURE_IMPLEMENTATION_PLAN.md).
That plan keeps capture, observations, curation, projections, and publication
snapshots separate so the UI can show exactly which facts are source evidence,
which are model suggestions, which are human-reviewed, and which are approved
for publication.

## Product Boundary

The platform has two separate user surfaces:

- **Metrics dashboard:** service health, stage metrics, store inspection, worker status, model/inference health, and operational troubleshooting.
- **Research UI:** inbox-driven source triage, source inspection, evidence extraction, normalized-content editing, entity/claim work, comparison, review, and publishing preparation.

The metrics dashboard remains on the existing dashboard service. The Research UI should be a separate app/service with its own port and deployment unit.

Current target:

```text
metrics dashboard: ${DASHBOARD_URL}
research UI:       ${RESEARCH_UI_URL}
```

Do not expose the Research UI publicly in v1. Keep it LAN/WireGuard scoped unless there is a separate exposure review.

## V1 Decisions

- First screen: **Inbox**.
- First validation case: **Datalab Chandra 2.1**.
- First source viewer: **X post/thread/account/media**.
- Second source viewer: **web/blog page**.
- Editing scope: full v1 editing, including evidence selection, normalized extraction corrections, entity links, claims, annotations, review state, comparison rows, and publication drafts.
- Later-stage closed-loop research automation is outside the v1 Research UI page
  scope. Page-specific research-agent prompts should not ask for that topic;
  keep them focused on human-led collection, inspection, review, curation, and
  publication-prep workflows.

Test case sources:

```text
blog: https://www.datalab.to/blog/chandra-2.1-release
X:    https://x.com/datalabto/status/2066597525432213782
```

## Core Workflow

The Research UI should be a case-centric evidence workbench, not a dashboard, document dump, graph canvas, or chatbot.

```text
Inbox
-> Source workbench
-> Evidence extraction
-> Entity resolution
-> Claim editing
-> Compare / benchmark views
-> Review
-> Publication draft
```

The user must always be able to jump from a published or curated fact back to the exact original captured evidence: X post, account snapshot, media frame, screenshot region, webpage block, PDF page, transcript timestamp, repository line, or manual document block.

## Object Model

| Object | Meaning | UI rule |
|---|---|---|
| Source | Logical external or user-provided source: X thread, article, paper, repo, video, screenshot, manual doc | Can have multiple captures/versions |
| Capture | Immutable observation of a source at a specific time | Original content is never edited |
| Normalized extraction | Parsed text, OCR, transcript, VL output, metadata, tables, and machine structure | Versioned by model/run; corrections are layered |
| EvidenceDocument | Versioned block/asset/anchor model for normalized source inspection | Canonical normalized source representation |
| Evidence | Selected source fragment used in research | Must point to exact source anchor |
| Entity | Account, person, lab, model, repo, paper, benchmark, hardware, tool, topic | Entity pages are projections of claims |
| Claim | Contestable proposition derived from evidence | Has qualifiers, support, contradictions, review state |
| Relation | Claim whose value is another entity | Every meaningful graph edge exposes evidence |
| Annotation | Highlight, note, question, correction, reviewer comment | Does not become accepted evidence automatically |
| Review task | Human action item | Separate from source lifecycle |
| Publication release | Frozen approved claims/narrative/page changes | Reviewable and reproducible |

## Navigation

Global navigation:

```text
Inbox
Projects
Library
Knowledge
Reviews
Publishing
Taxonomy
```

Persistent top bar:

- Global search.
- Current project switcher.
- Add/capture source.
- Command palette.
- Assigned review tasks.
- User/visibility context.

Project navigation:

```text
Brief
Sources
Evidence
Claims
Entities
Timeline
Compare
Drafts
```

Graph exploration is a contextual analysis view launched from an entity, topic, claim set, or selected evidence. It is not the home screen.

## Inbox

The Inbox is the first v1 screen.

Use a dense three-pane layout:

```text
left:   saved queues and facets
center: work-item list
right:  preview and actions
```

The Inbox row unit is a **review task**, not just a source. One source can create multiple tasks: extraction review, entity resolution, contradiction review, publication blocker, etc.

Default queues:

- New captures.
- Unassigned sources.
- Extraction/OCR/VL failures.
- Duplicate and version candidates.
- Entity-resolution candidates.
- Suggested evidence.
- Suggested claims.
- Contradiction candidates.
- Missing-source or broken-link warnings.
- Stale claims.
- Publication blockers.

Row fields:

- Source title and type.
- Author/account/domain/repository.
- Published, observed, and captured timestamps.
- Why the item entered the queue.
- Project/topic.
- Owner and priority.
- Processing state.
- Duplicate/version cluster.
- Evidence/claim suggestion counts.
- Source-access or sensitivity marking.

Core actions:

- Keep, reject, archive, or defer.
- Assign project or owner.
- Merge duplicate/version.
- Open in source workbench.
- Accept/reject suggestion.
- Save and next.
- Bulk assign, label, or archive.

## Source Workbench

The source workbench is the central screen after Inbox.

Layout:

```text
header: source identity, capture/version, integrity, project status
left:   source-native navigator
center: original or normalized viewer
right:  extraction/evidence/entities/claims/annotations/review/provenance panel
```

Viewer modes:

- Original.
- Normalized.
- Side-by-side.

Side-by-side requirements:

- Synchronized scrolling where possible.
- Selecting normalized text highlights original location where possible.
- OCR/transcript uncertainty overlays.
- Original-vs-corrected text diffs.
- Toggleable OCR/VL/layout bounding boxes.
- Parser/model/run metadata.
- Explicit unreadable or missing segments.

Evidence creation should work from selected text, regions, timestamps, table cells, screenshots, video frames, or repository lines. The form should capture excerpt, context, evidence type, entities, labels, claim support/refutation/mention state, analyst note, visibility, and verification state.

## Source Viewers

V1 source order:

1. X post/thread/account/media.
2. Web/blog page.

Later source viewers can use the same shell.

| Source | Native viewer behavior | Stable anchor |
|---|---|---|
| X post/thread | Chronological thread, conversation tree, quoted/replied-to context, media gallery, account snapshot | Platform post ID, text range, media region, capture ID |
| X account | Stable platform ID, handle history, profile captures, relevant posts/media | Account ID plus profile capture version |
| Web/blog | Captured rendering, clean text, headings, links, DOM/block structure, prior captures | Capture ID, text/block anchor, optional pixel region |
| Google SERP | Query, locale, time, rank, snippet, result list | SERP capture, query, rank/result position |
| Manual document | Editable analyst document with version history | Document version and block/range ID |
| Paper/PDF | PDF pages, extracted text, figures, tables, references, source bundle | File hash, page, text offsets, bounding boxes |
| GitHub | README/model card, file tree, releases, commits, diffs, rendered/raw view | Repo, commit SHA, path, line range |
| Video | Player with transcript, chapters, frames, OCR/VL overlays | Media hash, start/end timestamp, transcript tokens, frame |
| Screenshot/image | Zoomable image with OCR/VL region overlays | Image hash and bounding polygon |

Rules:

- Google SERPs are discovery provenance by default; the opened result is the evidentiary source.
- X engagement values need observed-at timestamps.
- Repository evidence must be revision-pinned.
- Manual documents must be visibly analyst-authored and not primary-source equivalent.

## Editing Scope

V1 should support all editing modes needed for a human-led research loop:

- Select evidence from original or normalized views.
- Correct normalized extraction text while preserving original capture.
- Edit OCR/transcript/layout corrections as versioned overlays.
- Create/edit entity links and aliases.
- Create/edit claims with qualifiers and evidence links.
- Mark support/refutation/mention/uncertain status.
- Create annotations, notes, questions, and reviewer comments.
- Resolve duplicate/version/entity candidates.
- Review contradiction candidates.
- Build comparison rows and benchmark facts.
- Draft publication bundles.

Machine suggestions must be accepted, edited, or rejected explicitly. No AI output should remain trapped in chat history; accepted output becomes evidence, claim, annotation, entity link, comparison row, or draft content.

## Search And Library

Global search spans:

- Sources.
- Evidence.
- Claims.
- Entities.
- Annotations.
- Projects.
- Published pages.

Results should be grouped by object type. Search controls should stay human-readable: exact, semantic, hybrid, current project, selected sources, whole corpus. Do not expose raw Typesense/Qdrant/reranker scores as the main explanation; show matched fragment, source location, object type, and review state.

## Entity Pages

Entity pages are evidence-backed fact ledgers, not freeform profiles.

Tabs:

```text
Overview
Claims
Sources
Relationships
Timeline
Artifacts
Notes
Audit
```

Claim rows should show property, value, qualifiers, evidence count, source diversity, contradiction state, review state, last verified timestamp, and preferred value for a defined scope. Competing assertions remain visible.

## Comparison And Benchmark Views

Comparison tables use entities as columns and canonical properties/claims as rows. Every cell exposes value, qualifiers, source type/date, verification state, evidence count, and a direct evidence jump.

Cell states:

- Missing.
- Not applicable.
- Vendor-reported.
- Independently measured.
- Reproduced.
- Disputed.
- Stale.
- Incomparable.

Benchmark pages must emphasize methodology, not just leaderboard order: benchmark version, maintainer, task, metrics, dataset versions, harness, model/provider/configuration, run date, score variance, source type, and review status.

## Review And Publishing

Publishing should behave like a research pull request.

Publication bundle contents:

- Narrative changes.
- Entity-page changes.
- Claim additions/removals.
- Comparison-table changes.
- Benchmark-result changes.
- Taxonomy changes.
- Source/citation changes.

Review tabs:

```text
Overview
Changed content
Claims
Evidence
Contradictions
Checks
Discussion
Public preview
```

Checks:

- Unsupported claims.
- Missing source anchors.
- Unresolved contradictions.
- Stale/inaccessible sources.
- Duplicate entities.
- Invalid taxonomy usage.
- Sensitive-source exposure.
- Broken public links.
- Unreviewed AI suggestions.
- Changed evidence since last approval.

Workflow:

```text
Draft -> Ready for review -> Changes requested -> Approved -> Published -> Superseded
```

The public research site is a projection of an approved release, not a live rendering of mutable internal records.

## V1 Build Plan

1. Create a separate `research-ui` service and route surface on `${RESEARCH_UI_URL}`.
2. Build Inbox as the first page with review-task rows, not only source rows.
3. Build the X source workbench using the Datalab X post as the first test case.
4. Build the web/blog source workbench using the Datalab blog as the second test case.
5. Add evidence selection, normalized-content correction, entity linking, claim editing, annotations, and review state.
6. Add publication draft bundle scaffolding.

## Acceptance Criteria

- The metrics dashboard contains no research UI navigation or product screens.
- The Research UI opens as a separate app/service.
- Inbox is the default first screen.
- A user can process a queue without returning repeatedly to a list page.
- The Datalab X post and blog can be opened from Inbox into native source workbenches.
- Original captures are immutable.
- Corrections to OCR, transcripts, or normalization are versioned and diffable.
- Every evidence item has an exact source anchor.
- Every claim can show supporting/refuting evidence.
- Conflicting claims remain visible after a preferred value is selected.
- Machine suggestions require accept/edit/reject.
- Public output resolves to a frozen reviewed release.
