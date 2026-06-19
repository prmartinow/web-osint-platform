# Redpanda Connect Shadow And Production Routing

Redpanda Connect now has two capture-event paths:

- shadow validation/projection for parity checks;
- guarded production routing for observed topics and media requests.

The Go service remains the production materializer. It still consumes raw
captures and writes Pebble, ClickHouse, Typesense, Qdrant, state topics, and
semantic labels. During Connect production routing, run it with
`WEB_OSINT_EMIT_OBSERVED_TOPICS=false` so it does not duplicate observed-topic
messages.

## Target

```text
evidence.capture.events.v1
  -> capture_envelope_validate compiled Go plugin
  -> source_kind_router compiled Go plugin
  -> observed_event_projector compiled Go plugin
  -> media_enrichment_request_builder compiled Go plugin
  -> evidence.capture.shadow.validated.v1
  -> evidence.capture.shadow.observed.v1
  -> osint.media.enrichment.shadow.requested.v1

processor/output failures
  -> dlq_error_enricher compiled Go plugin
  -> evidence.capture.shadow.errors.v1
```

The observed and media request outputs are shadow wrappers. They are not input
to the production materializer, OCR worker, or VL worker.

## Production Routing Target

```text
evidence.capture.events.v1
  -> capture_envelope_validate compiled Go plugin
  -> source_kind_router compiled Go plugin
  -> observed_event_projector(mode=production)
  -> media_enrichment_request_builder(mode=production)
  -> evidence.*.observed.v1
  -> osint.media.enrichment.requested.v1
  -> osint.media.ocr.requested.v1
  -> osint.media.vl_embedding.requested.v1

processor/output failures
  -> dlq_error_enricher compiled Go plugin
  -> evidence.index.errors.v1
```

This is a routing cutover only, not a materializer rewrite.
The production pipeline starts from the latest offset for a fresh consumer group
to avoid replaying historical captures into production observed topics.

## Run Locally Against The Stack

Implementation note: this pinned Redpanda Connect build uses `kafka_franz` for
topic input/output because Redpanda's data plane is Kafka-compatible. The
pipeline still targets Redpanda topics and remains under Redpanda Connect; do
not describe this as a separate Kafka cluster.

The service is behind the `shadow` Compose profile:

```bash
docker compose --env-file .env -f compose/docker-compose.yml --profile shadow up -d --build redpanda-connect-shadow
```

Check lag and output:

```bash
docker exec web-osint-redpanda rpk topic consume evidence.capture.shadow.validated.v1 --brokers 127.0.0.1:9092 -n 1
docker exec web-osint-redpanda rpk topic consume evidence.capture.shadow.errors.v1 --brokers 127.0.0.1:9092 -n 1
```

Run the existing E2E canary with shadow verification once the shadow service is
running:

```bash
python3 scripts/run_e2e_canary.py --expect-shadow
```

Run the P1/P2 shadow projection parity canary:

```bash
python3 scripts/run_connect_shadow_parity.py \
  --env-file .env \
  --pandaproxy-url http://127.0.0.1:18082 \
  --clickhouse-url http://127.0.0.1:18123
```

This publishes a synthetic capture containing `user_input`, `web_document`,
`media`, and `search_result` records. It compares
`evidence.capture.shadow.observed.v1` wrapper payloads against the current Go
normalizer/materializer rows in ClickHouse, and verifies that the media request
builder emits only to `osint.media.enrichment.shadow.requested.v1`.

## Production Routing Cutover

Start the production router and normalizer together so observed-topic ownership
is unambiguous:

```bash
WEB_OSINT_EMIT_OBSERVED_TOPICS=false \
  docker compose --env-file .env -f compose/docker-compose.yml --profile production-routing up -d --build normalizer redpanda-connect-production
```

Stop the legacy media router while production Connect owns media request
fan-out:

```bash
systemctl --user stop web-osint-media-router.service
```

Rollback:

```bash
docker rm -f web-osint-connect-production
WEB_OSINT_EMIT_OBSERVED_TOPICS=true \
  docker compose --env-file .env -f compose/docker-compose.yml up -d --build normalizer
systemctl --user start web-osint-media-router.service
```

## Guardrails

- Keep the Go service as the production materializer.
- Keep the old observed-topic emission path available through
  `WEB_OSINT_EMIT_OBSERVED_TOPICS=true`.
- Keep the legacy media router service installed as fallback.
- Shadow output must continue matching stable fields for canary events after
  production routing changes.
- Connect YAML is wiring only; custom deterministic logic belongs in compiled Go
  plugins.
