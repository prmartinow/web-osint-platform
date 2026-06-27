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
- Rebrowser launch bridge: normalized launch/result path implemented through `REBROWSER_LAUNCH_URL`; real live helper configuration remains pending in ignored deployment env.

The remaining work is production depth, visual QA, and Web OSINT repo consolidation.

## Remaining Work

| ID | Area | Status | Acceptance Gate | Next Action |
| --- | --- | --- | --- | --- |
| RUI-01 | Browser/UI design audit QA | Done | Desktop and mobile screenshots of Home, Projects, Timeline, Compare, Draft, Publishing, Publication Detail, Source Workbench show no broken layout, overlap, unreadable controls, missing primary actions, or desktop content capped to a narrow slice of the available window. | Keep the screenshot audit in the verification loop when later UI phases change layout. |
| RUI-02 | Timeline controls | Done | Timeline supports date range, lane, date type, confidence, review state, source kind, and saved view controls without fabricating precise dates. | Keep timeline filters in the regression loop while moving to compare evidence workflow. |
| RUI-03 | Compare evidence workflow | Done | Every non-empty comparison cell exposes exact supporting evidence and opens a source/evidence drawer; missing/NA/vendor/independent/reproduced/disputed/stale/incomparable states are derived honestly. | Keep the drawer in regression checks and reverify with populated compare data when available. |
| RUI-04 | Draft Editor persistence | Done | Drafts persist revisions, object-linked citations, citation insertion, unsupported-paragraph checks, stale citation warnings, and proposed AI diffs without storing free-floating source URLs as citations. | Keep draft save/citation/diff smoke tests in the regression loop while moving to benchmark persistence. |
| RUI-05 | Benchmark Detail persistence | Done | Benchmark methodology fields and result groups persist; incompatible configs are excluded from default ranking; missing methodology blocks publication. | Reverify result-row group controls when populated benchmark claims exist. |
| RUI-06 | Topic Detail deep links | Done | Taxonomy/topic rows and topic mentions open Topic Detail directly, preserving project scope. | Keep taxonomy-to-topic and timeline-topic chip checks in UI regression. |
| RUI-07 | Publication handoff/export | Done | Approved snapshot can create explicit handoff/export artifacts with manifest hash, frozen object IDs, public config, and no private runtime values. | Keep handoff export in the publishing regression loop while wiring Rebrowser LaunchCapture. |
| RUI-08 | Rebrowser LaunchCapture final wiring | Partial | `REBROWSER_LAUNCH_URL` points to the real launch helper; UI opens/records returned session; committed capture events link back to requested project/source/route; Research UI fills the active browser viewport in screenshots. | Set the real launch helper endpoint in ignored deployment env and verify a real capture session. |
| REPO-01 | Single canonical Web OSINT repo | Partial | Runtime/deployment can be launched from `web-osint-platform` without relying on a separate editable live source tree. | Continue live-vs-canonical comparison for dashboard, docs, and scripts after the X notifications collector migration. |
| REPO-02 | Environment-only deployment config | Partial | All sensitive/local deployment values are supplied by env vars or ignored local files; repo contains `.env.example` and documented variable names only. | Continue replacing tracked service templates/docs that still expose local data roots or loopback service ports. |
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
- 2026-06-27: Added Draft Editor persistence with draft revision, draft citation, and draft proposed-diff tables plus save, citation insertion, and proposed-diff APIs. The UI now edits paragraph text, saves revisions, inserts source-record citations by platform object ID, shows unsupported and stale-citation checks, and displays persisted proposed diffs.
- 2026-06-27: Added Benchmark Detail persistence with methodology and result-group tables plus save APIs. The UI now edits source-linked methodology fields and can persist result-group compatibility/default-ranking settings; incompatible groups cannot remain default-ranked.
- 2026-06-27: Wired Topic Detail deep links from taxonomy topic rows, taxonomy preview actions, and timeline topic chips. Topic navigation preserves the active project scope in the route hash.
- 2026-06-27: Added publication handoff/export persistence with sanitized handoff artifacts. Approved snapshots can now create `public_export_manifest` rows that store manifest hash, frozen object IDs, object counts, public target config, and a narrow artifact envelope without private runtime paths or endpoint values; Publishing and Publication Detail now show generated artifact lists.
- 2026-06-27: Normalized Rebrowser LaunchCapture responses, recorded returned launch sessions as review events tied to the requested project/source/route, opened returned session URLs from the UI, replaced launch alerts with inline status, added the public `REBROWSER_LAUNCH_URL` example name, and tightened viewport sizing so the Research UI fills the browser window instead of rendering as a partial-width/partial-height shell.
- 2026-06-27: Migrated the Rebrowser X notifications collector into the canonical repo shape and sanitized it for upstream: CDP URL, helper path, RPC SSH target, RPC data root, Pandaproxy endpoint, and expected X account now come from CLI flags or env vars rather than hardcoded local deployment values.
- 2026-06-27: Removed the remaining stale model-root env usage from Web OSINT scripts/templates, moved webpage extraction venv selection to `WEB_OSINT_WEBPAGE_EXTRACTION_VENV` plus `WEB_OSINT_DATA_ROOT`, and changed local-inference docs plus `.env.example` to use env placeholders rather than tracked local endpoints.
- 2026-06-27: Made the dashboard tolerate a disabled legacy media router when Redpanda Connect owns OCR/VL request routing, and added longer Kafka max-poll intervals plus provenance fields for embedding/media enrichment workers.
- 2026-06-27: Added an opt-in normalizer Pebble maintenance delete endpoint for cleanup work, guarded by `WEB_OSINT_ENABLE_MAINTENANCE_DELETE=false` by default and wired through compose as an env variable.
- 2026-06-27: Converted embedding, media OCR, media VL, media router, Qdrant backfill, and webpage extraction user-service templates away from legacy live-tree paths and local endpoints; templates now resolve repo roots, venv roots, data roots, brokers, ClickHouse, Qdrant, local-inference, and bind addresses from an ignored env file.
- 2026-06-27: Converted `scripts/health.sh` to read service URLs from the ignored env file instead of hardcoded loopback ports, and added the matching public variable names to `.env.example`.
- 2026-06-27: Converted the ingestion, media enrichment, Connect shadow parity, and webpage extraction canary scripts away from tracked live data-root, dashboard, and service endpoint defaults. Canary data roots, Pandaproxy, ClickHouse, Qdrant, and dashboard URLs now come from CLI arguments, process env, or ignored env files; `.env.example` documents only public placeholder variable names.
- 2026-06-27: Converted the Rebrowser rendered-web collector away from tracked CDP, SSH, data-root, and Pandaproxy defaults. The collector now uses env/CLI settings for capture and publish configuration, and `--publish` validates required deployment values before opening a browser tab or uploading artifacts.
- 2026-06-27: Removed remaining tracked durable data-root defaults from Compose, setup scripts, shared data-root helpers, and dashboard media/OCR defaults. Durable roots must now be supplied through `WEB_OSINT_DATA_ROOT`, `OSINT_DATA_ROOT`, or explicit worker/service env; dashboard artifact links are filtered against configured safe roots rather than one fixed mount prefix.
- 2026-06-27: Sanitized the operating guide away from live deployment paths and local endpoints. Operator examples now use env-configured endpoint/data-root variables, and `.env.example` documents the public placeholder names for Research UI, dashboard, Redpanda Connect, Redpanda admin, and reference-source roots.
- 2026-06-27: Converted standalone operator scripts away from baked loopback service defaults. Topic bootstrap, stack bootstrap probes, ClickHouse init, Qdrant/Typesense init, manual-document publishing, smoke publishing, and semantic/Qdrant backfills now use env or ignored `.env` settings and fail before network writes when required endpoints are missing.
- 2026-06-27: Converted Python worker endpoint defaults away from baked loopback service URLs. Embedding, webpage extraction, media enrichment, and research planner workers now take brokers, Pandaproxy, ClickHouse, Qdrant, and local-inference endpoints from env, with generic bind-address defaults for their stats servers.
- 2026-06-27: Converted dashboard and Research UI service endpoints away from baked loopback defaults. The servers now require configured ClickHouse/search/vector/worker/local-inference/Redpanda endpoint env as applicable, and compose passes the documented env names into the host-network dashboard and Research UI services.
- 2026-06-27: Converted the normalizer worker away from baked loopback broker/search/vector/ClickHouse defaults. The normalizer now fails during config load when required broker and service endpoint env is absent, before opening Pebble or Kafka resources.
- 2026-06-27: Converted the producer outbox and flush path away from repo-local state and baked Pandaproxy defaults. Producer spooling now requires `WEB_OSINT_OUTBOX_ROOT`, `WEB_OSINT_DATA_ROOT`, or `--outbox-root`; flushing requires env/CLI Pandaproxy config, and README examples use the documented env names.
- 2026-06-27: Converted the RPC tunnel helper away from baked remote loopback targets and local user examples. Tunnel target host/ports now come from ignored config env, and real `config/*.env` files are ignored while checked-in examples remain allowed.
- 2026-06-27: Parameterized Compose host binds, host-side ports, and Redpanda external advertise hosts. The checked-in Compose file no longer fixes loopback host:port bindings; `.env.example` carries the public variable names and valid example values.
- 2026-06-27: Sanitized agent rules and Connect test fixtures away from local deployment paths and live model-owner wording. Tests now use generic synthetic fixture paths, and repository agent guidance states that model files/downloads/caches/serving remain outside Web OSINT.
- 2026-06-27: Removed old live database/collection fallback names from canary scripts. Canary defaults now remain sanitized; production database/user/collection values must come from env or CLI config.

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
- Draft Editor write/readback smoke saved a revision, inserted an object-linked source citation, persisted a proposed diff, and returned passing checks for object-linked citations, unsupported paragraphs, source-version staleness, and proposed diffs. Browser/CDP desktop and mobile checks verified editable paragraphs, citation chips, proposed diff display, insert buttons, save action, no page-level horizontal scroll, and no browser console/page errors.
- Benchmark Detail write/readback smoke saved source-linked methodology and an incompatible result group; readback showed methodology no longer blocks publication and the incompatible group is not default-ranked. Browser/CDP desktop and mobile checks verified methodology fields, save action, responsive layout, no page-level horizontal scroll, and no browser console/page errors. The active project has no populated benchmark result claims, so row-level group buttons remain to be rechecked on populated data.
- Topic link browser check opened Topic Detail from a taxonomy topic control and verified the resulting hash preserved `project=x-notifications`; the Topic Detail page rendered without page-level horizontal scroll, stuck loading/error text, or browser console/page errors.
- Publication handoff API smoke created a frozen snapshot, approved it, created a `public_export_manifest` handoff, read it back from Publication Detail, and scanned the returned artifact for local path/private endpoint/token patterns. Browser/CDP checks verified desktop Publication Detail fills the full viewport width, the handoff artifact list renders, mobile has no page-level or card-level horizontal overflow, long hashes/config text wrap inside the card, and the status badge stays intact.
- Rebrowser LaunchCapture endpoint smoke verified URL-only launches record a queued event when `REBROWSER_LAUNCH_URL` is not configured. A temporary local launch helper verified the configured path returns a normalized committed session, open URL, and two event ids without adding deployment values to Git. Browser/CDP checks verified the UI reports `Capture committed`, opens the returned session route, live desktop fills a 1920x1080 viewport, and live mobile has no page-level horizontal overflow. The active live env still requires a real helper URL before RUI-08 can be marked `Done`.
- Rebrowser X notifications collector migration checks: `node --check collectors/rebrowser-x-notifications/x_notifications_capture.mjs` passed; `--help` renders without requiring live env; missing required config fails before browser/publish side effects; targeted sanitizer found no collector hardcoded loopback endpoints, home-network addresses, deployment data roots, SSH account targets, or expected account handles.
- Local-inference/model-root cleanup checks: `bash -n scripts/init_webpage_extraction_venv.sh`, `python3 -m py_compile scripts/run_webpage_extraction_canary.py scripts/osint_paths.py`, and `systemd-analyze verify --user systemd/user/web-osint-webpage-extraction-worker.service` passed. A repository search found no remaining stale model-root env/helper references.
- Worker/dashboard cleanup checks: `python3 -m py_compile dashboard/server.py workers/embedding-worker/embedding_worker.py workers/media-enrichment/media_enrichment_worker.py` passed.
- Normalizer maintenance-delete checks: `gofmt -w workers/normalizer/main.go` and `go test ./...` under `workers/normalizer` passed; additions-only sanitizer found no new local paths, local endpoints, secrets, or model-owner variables.
- Service-template cleanup checks: `systemd-analyze verify --user systemd/user/*.service` passed, and additions-only sanitizer found no new local paths, local endpoints, secrets, or model-owner variables in the template/env-example diff.
- Health-script cleanup checks: `bash -n scripts/health.sh` passed; additions-only sanitizer found no new local paths, local endpoints, secrets, or model-owner variables.
- Canary-default cleanup checks: `python3 -m py_compile scripts/run_e2e_canary.py scripts/run_connect_shadow_parity.py scripts/run_media_enrichment_canary.py scripts/run_webpage_extraction_canary.py` passed; missing required canary config now returns a clear config error before network or data writes; additions-only sanitizer found no new local paths, local endpoints, secrets, or model-owner variables.
- Rendered-web collector cleanup checks: `node --check collectors/rebrowser-rendered-web/rebrowser_rendered_capture.mjs` passed; `--help` renders without printing configured endpoint values; missing `REBROWSER_CDP_URL` fails before browser or publish side effects; additions-only sanitizer found no new local paths, local endpoints, secrets, or model-owner variables.
- Data-root cleanup checks: `bash -n scripts/init_dirs.sh scripts/init_env.sh scripts/init_embedding_worker_venv.sh scripts/init_media_enrichment_venv.sh`, `python3 -m py_compile scripts/osint_paths.py scripts/run_e2e_canary.py dashboard/server.py`, and `docker compose --env-file .env.example -f compose/docker-compose.yml config` passed; missing setup data-root config now fails before directory or env-file writes; additions-only sanitizer found no new local paths, local endpoints, secrets, or model-owner variables.
- Operating-guide cleanup checks: targeted pattern scan of `docs/OPERATING.md` and `.env.example` found no live data-root paths, local source paths, home-network addresses, loopback host:port endpoints, or SSH account targets; additions-only sanitizer found no new local paths, local endpoints, secrets, or model-owner variables.
- Operator-script endpoint cleanup checks: `python3 -m py_compile scripts/init_qdrant.py scripts/init_typesense.py scripts/produce_research_documents.py scripts/smoke_produce_event.py scripts/backfill_qdrant_embeddings.py scripts/backfill_semantic_annotations.py` and `bash -n scripts/init_clickhouse.sh scripts/create_topics.sh scripts/bootstrap.sh` passed; missing endpoint/broker config probes returned before network side effects; additions-only sanitizer found no new local paths, local endpoints, secrets, or model-owner variables.
- Python-worker endpoint cleanup checks: `python3 -m py_compile workers/embedding-worker/embedding_worker.py workers/webpage-extraction/webpage_extraction_worker.py workers/media-enrichment/media_enrichment_worker.py workers/research-planner/research_planner.py` passed; research planner missing-config probe returned before network side effects. Direct startup probes for embedding/media/webpage workers require their worker venv dependencies, which were not installed in this shell.
- Dashboard/Research UI endpoint cleanup checks: `python3 -m py_compile dashboard/server.py research-ui/server.py` and `docker compose --env-file .env.example -f compose/docker-compose.yml config` passed; missing endpoint config probes for both servers returned before startup; additions-only sanitizer found no new local paths, local endpoints, secrets, or model-owner variables.
- Normalizer endpoint cleanup checks: `gofmt -w main.go`, `go test ./...`, and `go build -o /tmp/web-osint-normalizer-config-check .` under `workers/normalizer` passed; an empty-env binary startup probe exited with `configuration: missing REDPANDA_BROKERS or KAFKA_BROKERS`; targeted scan found no normalizer hardcoded loopback endpoints or local deployment paths.
- Producer outbox cleanup checks: `python3 -m py_compile producer/web_osint_producer.py` passed; missing Pandaproxy and missing outbox config probes failed before network writes; explicit temp-outbox spool smoke wrote only under `/tmp` and the temp artifact was removed; additions-only sanitizer found no new local paths, local endpoints, secrets, or model-owner variables.
- RPC tunnel cleanup checks: `bash -n scripts/open_rpc_tunnel.sh` passed; a temp-config missing `REMOTE_TUNNEL_HOST` failed before SSH execution; targeted scan found no hardcoded local endpoints, local deployment paths, or local SSH user examples in the tunnel script/config diff.
- Compose bind cleanup checks: `docker compose --env-file .env.example -f compose/docker-compose.yml config` passed; targeted scan found no tracked compose loopback host:port bindings, hardcoded Redpanda external loopback advertise endpoints, local deployment paths, or model-owner variables.
- Agent/test fixture cleanup checks: `gofmt -w connect/internal/webosint/projector_test.go connect/plugins/mediarequestbuilder/media_enrichment_request_builder_test.go` and `go test ./...` under `connect` passed; targeted scan found no local deployment paths, local endpoints, stale live collection names, or model-owner variables in `AGENTS.md` and the sanitized Connect fixtures.
- Canary live-name cleanup checks: `python3 -m py_compile scripts/run_media_enrichment_canary.py scripts/run_e2e_canary.py scripts/run_connect_shadow_parity.py scripts/run_webpage_extraction_canary.py` passed; targeted scan found no stale live database/collection names, local deployment paths, local endpoints, or model-owner variables in those canary scripts.

## Next Checkpoint

Continue with repo consolidation while RUI-08 waits on the real launch helper URL: compare remaining legacy live-tree docs/scripts differences, migrate source-code deltas only, move local deployment values to env, and choose the live-tree retirement shape.
