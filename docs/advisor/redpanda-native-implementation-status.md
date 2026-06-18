# Redpanda-Native Advisor Implementation Status

Source target: `docs/advisor/redpanda-native-implementation-target.md`

Last checked: 2026-06-18

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
| Keep production materialization in the existing Go normalizer/materializer. | Done | Connect service is behind the `shadow` Compose profile; production routing is unchanged. |

## Implementation Notes

This pinned Connect build uses `kafka_franz` as the stream input/output
component against Redpanda brokers. That is consistent with the advisor's
guidance: Redpanda's data plane is Kafka-compatible, and the Kafka-compatible
client/protocol name is an implementation detail.

`public/components/redpanda` is imported for Redpanda Data Transform support in
the custom Connect binary, but in this version it does not register stream
input/output components.

## Deferred P1/P2 Work

- Add source-kind router plugin.
- Add observed-event projector plugin.
- Add media request builder plugin.
- Add DLQ enricher plugin.
- Run shadow parity checks for user-input, media, web-document, and search-result
  source kinds before production cutover.
- Evaluate tiny Redpanda Data Transforms only after the shadow Connect path is
  stable.
