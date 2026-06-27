# Redpanda-Native Advisor Implementation Status

Source target: `docs/advisor/redpanda-native-implementation-target.md`

Last checked: 2026-06-19

## P0 Status

| Advisor recommendation | Status | Implementation |
|---|---:|---|
| Save the advisor implementation recommendation locally. | Done | `docs/advisor/redpanda-native-implementation-target.md` |
| Add Redpanda-native architecture docs. | Done | `docs/REDPANDA_NATIVE_ARCHITECTURE.md` |
| Add a topic catalog with owners, retention, schema, and consumers. | Done | `docs/TOPIC_CATALOG.md` |
| Update AGENTS guidance to stop treating Kafka naming as architecture. | Done | `AGENTS.md` |
| Add a Redpanda Connect custom distribution skeleton. | Done | `connect/cmd/web-osint-connect`, `connect/Dockerfile` |
| Add a compiled Go validation plugin. | Done | `connect/plugins/capturevalidate` |
| Add a shadow validation pipeline. | Done | `connect/pipelines/capture-shadow-validate.yaml` |
| Add shadow topics. | Done | `scripts/create_topics.sh` |
| Extend the E2E canary to verify shadow output. | Done | `scripts/run_e2e_canary.py --expect-shadow` |
| Prove live P0 shadow parity. | Done | `docs/advisor/redpanda-native-parity-proof-20260618.md` |
| Keep production materialization in the existing Go normalizer/materializer. | Done | Production routing is cut over to Connect; the Go service still materializes raw captures and can resume observed-topic emission as fallback. |

## Implementation Notes

This pinned Connect build uses `kafka_franz` as the stream input/output
component against Redpanda brokers. That is consistent with the advisor's
guidance: Redpanda's data plane is Kafka-compatible, and the Kafka-compatible
client/protocol name is an implementation detail.

`public/components/redpanda` is imported for Redpanda Data Transform support in
the custom Connect binary, but in this version it does not register stream
input/output components.

Live P0 parity was proven on 2026-06-18 with strict canary run
`e2e_canary_20260618T025352Z_1a6fb8`. The published capture event and the
Connect shadow-validated event produced identical canonical JSON SHA256 hashes,
the production ClickHouse row used the exact expected `user_input/...` evidence
ID, Qwen embedding produced a 4096-dimensional `text_dense` vector in Qdrant,
and dashboard exact search returned the canary at rank 1. See
`docs/advisor/redpanda-native-parity-proof-20260618.md`.

## P1/P2 Routing Cutover

The sanitized repo now includes compiled plugin packages for:

- `source_kind_router`
- `observed_event_projector`
- `media_enrichment_request_builder`
- `dlq_error_enricher`

The shadow pipeline remains non-serving. It emits the original validated
capture event to `evidence.capture.shadow.validated.v1`, observed projection
wrappers to `evidence.capture.shadow.observed.v1`, and shadow-only media
request wrappers to `osint.media.enrichment.shadow.requested.v1`.

Production routing is now handled by
`connect/pipelines/capture-production-observed.yaml`, which starts at the latest
offset for a fresh production group and emits observed-topic records plus media
request fan-out. The Go normalizer/materializer remains deployed as the
materializer and runs with `WEB_OSINT_EMIT_OBSERVED_TOPICS=false` during the
cutover. Rollback is to stop production Connect, restart the normalizer with
`WEB_OSINT_EMIT_OBSERVED_TOPICS=true`, and restart the legacy media router.

Focused canary added:

```bash
python3 scripts/run_connect_shadow_parity.py
```

It publishes one synthetic capture with `user_input`, `web_document`, `media`,
and `search_result` records, compares shadow observed wrapper payloads against
the Go normalizer/materializer `raw_json` rows in ClickHouse, and verifies that
media request building stays on the shadow topic.

## P1/P2 Shadow Proof - 2026-06-19

Live test container:

```text
container: x-research-connect-shadow-p1p2
image:     web-osint-connect-shadow:p1p2-test
group:     web-osint-connect-shadow-p1p2-v1
ready:     ${REDPANDA_CONNECT_SHADOW_P1P2_URL}/ready
lag:       0 after canaries
```

Focused P1/P2 parity canary:

```text
run_id:                       connect_shadow_parity_20260619T001008Z_bef2a0
result:                       ${WEB_OSINT_DATA_ROOT}/canaries/connect-shadow/runs/connect_shadow_parity_20260619T001008Z_bef2a0.json
matched_source_kinds:          media, search_result, user_input, web_page
shadow_observed_events:        4
shadow_media_request_events:   1
parity_ok:                     true
media_request_ok:              true
```

Existing P0/E2E canary still passes with the P1/P2 sidecar running:

```text
run_id:                                e2e_canary_20260619T001037Z_4beadb
result:                                ${WEB_OSINT_DATA_ROOT}/canaries/runs/e2e_canary_20260619T001037Z_4beadb.json
status:                                passed
shadow_matches_published_capture:      true
production_observed_matches_capture:   true
qdrant_points_found:                   1
dashboard_exact_rank:                  1
```

This proves shadow plugin parity for the canary records only. It does not
authorize production cutover. Repeat parity over replay and representative
captures before proposing routing cutover.

## Guarded Production Routing Cutover - 2026-06-19

Live production router:

```text
container: x-research-connect-production
image:     x-research-connect-production:p1p2-cutover
group:     web-osint-connect-production-v1
ready:     ${REDPANDA_CONNECT_PRODUCTION_URL}/ready
lag:       0 after canaries
```

Fallback state:

```text
normalizer:       running with emit_observed_topics=false
media router:     web-osint-media-router.service inactive but enabled
shadow P0:        x-research-connect-shadow ready on ${REDPANDA_CONNECT_SHADOW_URL}
shadow P1/P2:     x-research-connect-shadow-p1p2 ready on ${REDPANDA_CONNECT_SHADOW_P1P2_URL}
```

Post-cutover E2E canary:

```text
run_id:                              e2e_canary_20260619T003321Z_b86372
result:                              ${WEB_OSINT_DATA_ROOT}/canaries/runs/e2e_canary_20260619T003321Z_b86372.json
status:                              passed
production_observed_matches_capture: true
shadow_matches_published_capture:    true
qdrant_points_found:                 1
dashboard_exact_rank:                1
```

Post-cutover focused P1/P2 shadow parity:

```text
run_id:                       connect_shadow_parity_20260619T003435Z_704ec0
result:                       ${WEB_OSINT_DATA_ROOT}/canaries/connect-shadow/runs/connect_shadow_parity_20260619T003435Z_704ec0.json
matched_source_kinds:          media, search_result, user_input, web_page
shadow_observed_events:        4
shadow_media_request_events:   1
parity_ok:                     true
media_request_ok:              true
```

This is a routing cutover only. Do not delete the old Go observed-topic path or
legacy media router until repeatable production parity over representative
replay is reviewed.
