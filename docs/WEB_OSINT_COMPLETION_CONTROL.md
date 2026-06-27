# Web OSINT Completion Control

Status date: 2026-06-27

This document is the control checklist for finishing the current Web OSINT platform work. Each implementation pass should compare live code and deployment behavior against this file, update the status table, then continue with the highest-priority incomplete item.

## Non-Negotiable Architecture

- Canonical Web OSINT repo: `prmartinow/web-osint-platform`
- Upstream: `prmartinow/web-osint-platform`
- Future target: one canonical Web OSINT repository and one upstream-maintained codebase.
- No permanent Web OSINT source/live fork. Any legacy live deployment tree is a migration artifact, not the future source of truth.
- Sensitive and deployment-specific values must come from environment variables, `.env` files outside Git, secret managers, or local runtime mounts.
- Do not commit captured data, browser/session material, `.env` files, logs, database files, vector stores, model weights, model caches, or local-only runtime state.
- Complete model ownership is outside Web OSINT. Web OSINT calls the local intelligence/local-inference API through `LOCAL_INFERENCE_URL` or equivalent env-configured endpoints; it must not own model serving, model downloads, model caches, model runtime dependencies, or model maintenance.

## Progress Loop

Every implementation pass must follow this loop:

1. Read this document and identify the first incomplete item with the highest priority.
2. Inspect the current source repo and live deployment before editing.
3. Make the smallest useful implementation change in `web-osint-platform`.
4. Verify with the strongest realistic signal: syntax checks, targeted endpoint probes, service logs, browser screenshots when available, and deploy checks when a live service changes.
5. Update this document with the new status, evidence, and next action.
6. Repeat until every required item is `Done`.

## Current State

The Research UI route scaffolding for the interrupted audit stream has landed:

- Timeline read model and page: implemented.
- Compare read model and page: implemented.
- Topic Detail read model and page: implemented.
- Benchmark Detail read model and page: implemented.
- Draft Editor read model and page: implemented.
- Publication Review detail page: implemented.
- Publication snapshot/release persistence: implemented first cut.
- Rebrowser launch bridge: implemented first cut through `REBROWSER_LAUNCH_URL`.

The remaining work is production depth, visual QA, and Web OSINT repo consolidation.

## Remaining Work

| ID | Area | Status | Acceptance Gate | Next Action |
| --- | --- | --- | --- | --- |
| RUI-01 | Browser/UI design audit QA | Done | Desktop and mobile screenshots of Home, Projects, Timeline, Compare, Draft, Publishing, Publication Detail, Source Workbench show no broken layout, overlap, unreadable controls, missing primary actions, or desktop content capped to a narrow slice of the available window. | Keep the screenshot audit in the verification loop when later UI phases change layout. |
| RUI-02 | Timeline controls | Done | Timeline supports date range, lane, date type, confidence, review state, source kind, and saved view controls without fabricating precise dates. | Keep timeline filters in the regression loop while moving to compare evidence workflow. |
| RUI-03 | Compare evidence workflow | Done | Every non-empty comparison cell exposes exact supporting evidence and opens a source/evidence drawer; missing/NA/vendor/independent/reproduced/disputed/stale/incomparable states are derived honestly. | Keep the drawer in regression checks and reverify with populated compare data when available. |
| RUI-04 | Draft Editor persistence | Partial | Drafts persist revisions, object-linked citations, citation insertion, unsupported-paragraph checks, stale citation warnings, and proposed AI diffs without storing free-floating source URLs as citations. | Add draft table/event model and write APIs. |
| RUI-05 | Benchmark Detail persistence | Partial | Benchmark methodology fields and result groups persist; incompatible configs are excluded from default ranking; missing methodology blocks publication. | Add benchmark methodology storage and edit UI. |
| RUI-06 | Topic Detail deep links | Partial | Taxonomy/topic rows and topic mentions open Topic Detail directly, preserving project scope. | Wire taxonomy and relevant topic chips to `#topic-detail`. |
| RUI-07 | Publication handoff/export | Partial | Approved snapshot can create explicit handoff/export artifacts with manifest hash, frozen object IDs, public config, and no private runtime values. | Add handoff/export writer and visible artifact list. |
| RUI-08 | Rebrowser LaunchCapture final wiring | Partial | `REBROWSER_LAUNCH_URL` points to the real launch helper; UI opens/records returned session; committed capture events link back to requested project/source/route. | Configure bridge and verify a real capture session. |
| REPO-01 | Single canonical Web OSINT repo | Partial | Runtime/deployment can be launched from `web-osint-platform` without relying on a separate editable live source tree. | Migrate remaining services/deploy commands from the legacy live tree to the canonical repo and retire the legacy tree as editable source. |
| REPO-02 | Environment-only deployment config | Partial | All sensitive/local deployment values are supplied by env vars or ignored local files; repo contains `.env.example` and documented variable names only. | Compare active `.env` shape against tracked examples without copying secrets; add missing public variable names only. |
| REPO-03 | Deployment data separation | Todo | Durable state remains under external data roots supplied by env vars; repo contains no durable data or generated runtime state. | Audit compose, scripts, and worker defaults for data-root assumptions. |
| REPO-04 | Live tree retirement plan | Todo | The legacy live tree becomes either a deployment symlink/worktree/check-out of the canonical repo or is retired after migration. | Choose implementation: direct repo deployment, worktree, or symlinked deployment root. |
| REPO-05 | CI/sanity checks for public upstream | Todo | Public upstream has checks for syntax, sanitization, docs, and basic service smoke where feasible. | Add lightweight scripts/checks that do not require secrets or live data. |

## Single-Repo Implementation Plan

Target end state:

```text
$WEB_OSINT_REPO_ROOT
  compose/
  collectors/
  connect/
  dashboard/
  docs/
  research-ui/
  schemas/
  scripts/
  workers/
  .env.example
```

The repo is the source of truth for Web OSINT code, docs, schemas, compose definitions, collectors, workers, dashboards, and Research UI. Live deployment values are injected by environment variables and local ignored files.

Current temporary state:

```text
source repo:        $WEB_OSINT_REPO_ROOT
legacy live tree:   $WEB_OSINT_LEGACY_LIVE_ROOT
data root:          $WEB_OSINT_DATA_ROOT
model API endpoint: $LOCAL_INFERENCE_URL
```

Migration steps:

1. Inventory differences between the canonical repo and live tree.
2. Classify every live-only item as source code, deployment config, generated runtime state, captured data, logs, or local secret material.
3. Move source-code deltas into `web-osint-platform`.
4. Move sensitive/local deployment values into ignored env files and document names in `.env.example`.
5. Keep durable data under external data roots.
6. Deploy from the canonical repo.
7. Retire the legacy live tree as an editable source tree.

## Progress Updates

- 2026-06-27: Created an ignored local `.env` at the canonical repo root from the existing deployment env without committing or printing values; rebuilt Research UI from the canonical repo compose path; health and timeline endpoint probes returned OK.
- 2026-06-27: Live-vs-canonical inventory found that the tracked repo already has the newer local-inference boundary for model ownership; stale model-serving/download variables from the legacy deployment example must not be reintroduced.
- 2026-06-27: Added missing public environment variable names to `.env.example` for container naming, ClickHouse database/user selection, Research UI bind selection, and observed-topic emission. Model root, model name, model download, and model-serving variables remain intentionally excluded.
- 2026-06-27: Completed the first browser/UI design audit pass. Fixed desktop page-width overflow, removed the desktop main-surface width cap so the workspace fills wide windows, replaced the mobile full-height rail with a compact top icon strip, forced mobile home panels back into one column, wrapped long page-header text, and kept benchmark tables scrolling inside their panel.
- 2026-06-27: Added timeline saved views and filters for date range, date type, lane, confidence state, review state, and source kind. Server filters use existing event, source, or capture dates and omit undated rows only when a date range is active.
- 2026-06-27: Added Compare evidence drawer support. Compare cells now carry selected assertion evidence, all matching assertion summaries, source IDs, evidence counts, and state reasons; state derivation covers missing, not-applicable, vendor-reported, independently measured, reproduced, disputed, stale, and incomparable outcomes from claim status, relation, source kind, qualifier metadata, and competing values.

## Verification Record

Latest verified state:

- Commit `9aa3c24` implemented the first-cut Research UI synthesis and publication workflows.
- Research UI health: `GET /healthz` returned OK in the active deployment.
- Live endpoint probes returned expected versions for Timeline, Compare, Draft Editor, Benchmark Detail, Publishing, and Publication Detail.
- `python3 -m py_compile research-ui/server.py` passed.
- `node --check research-ui/static/app.js` passed.
- Browser/CDP screenshot audit captured desktop and mobile views for Home, Projects, Timeline, Compare, Draft, Publishing, Publication Detail, Source Workbench, Topic Detail, and Benchmark Detail.
- Final route check found no page-level horizontal scroll, load error text, loading-stuck text, or browser console/page errors across those desktop and mobile views; a wide-viewport screenshot verified that the main workspace fills the available browser width.
- Timeline endpoint probes covered default loading, lane/date-range/confidence filters, source-kind/review-state filters, saved-view filters, and a nonmatching source-date range. Browser/CDP checks verified desktop and mobile timeline controls plus saved-view hash updates.
- Compare endpoint probe returned the expected state legend and an empty matrix for the active project. Synthetic classifier coverage exercised the major compare states, and browser/CDP desktop and mobile checks verified the evidence drawer, no page-level horizontal scroll, no stuck loading/error text, and no browser console/page errors.

## Next Checkpoint

Continue with `RUI-04`: add Draft Editor persistence for revisions, object-linked citations, citation insertion, unsupported-paragraph checks, stale citation warnings, and proposed AI diffs.
