# Web OSINT Redpanda Connect

This directory contains the Redpanda Connect routing paths. The shadow pipeline
emits parity wrappers only. The production routing pipeline emits observed-topic
records and media enrichment requests, while the Go service remains the
materializer for Pebble, ClickHouse, Typesense, Qdrant, state topics, and labels.

## Layout

```text
connect/
  cmd/web-osint-connect/       custom Redpanda Connect binary entrypoint
  plugins/                     compiled Go plugins
  pipelines/                   thin YAML wiring
```

## Current Shadow Pipeline

`pipelines/capture-shadow-validate.yaml` consumes
`evidence.capture.events.v1`, runs compiled processors for validation,
source-kind routing, observed-event projection, media request building, and DLQ
enrichment, then writes only to shadow topics:

- `evidence.capture.shadow.validated.v1`
- `evidence.capture.shadow.observed.v1`
- `osint.media.enrichment.shadow.requested.v1`
- `evidence.capture.shadow.errors.v1`

The observed and media request topics contain wrappers for parity checks and are
not consumed by production workers.

## Production Routing Pipeline

`pipelines/capture-production-observed.yaml` consumes
`evidence.capture.events.v1`, runs the same compiled processors in production
mode, and writes real records to:

- `evidence.posts.observed.v1`
- `evidence.accounts.observed.v1`
- `evidence.media.observed.v1`
- `evidence.search.results.v1`
- `evidence.web.documents.observed.v1`
- `evidence.user.inputs.observed.v1`
- `osint.media.enrichment.requested.v1`
- `osint.media.ocr.requested.v1`
- `osint.media.vl_embedding.requested.v1`
- `evidence.index.errors.v1`

During production routing cutover, run the normalizer with
`WEB_OSINT_EMIT_OBSERVED_TOPICS=false` so it keeps materializing from raw
captures without duplicating observed-topic records. Roll back by stopping the
production Connect service, setting `WEB_OSINT_EMIT_OBSERVED_TOPICS=true`, and
restarting the legacy media router service.

The pinned Redpanda Connect version exposes stream I/O through the
`kafka_franz` component, pointed at Redpanda brokers. Treat that component name
as a wire-protocol detail: this is still Redpanda Connect reading and writing
Redpanda topics. The `redpanda` component package is also imported so later
Data Transform processors can be enabled without changing the binary skeleton.

Run through Compose:

```bash
docker compose --env-file .env -f compose/docker-compose.yml --profile shadow up -d --build redpanda-connect-shadow
```

Run the guarded production router through Compose:

```bash
WEB_OSINT_EMIT_OBSERVED_TOPICS=false \
  docker compose --env-file .env -f compose/docker-compose.yml --profile production-routing up -d --build normalizer redpanda-connect-production
```

Run the focused P1/P2 parity canary:

```bash
python3 scripts/run_connect_shadow_parity.py
```

Run the binary directly from this directory after building:

```bash
./web-osint-connect -c pipelines/capture-shadow-validate.yaml
```

## Rules

- YAML is orchestration, not business logic.
- Compiled Go plugins hold deterministic hot-path logic.
- Dynamic gRPC plugins are reserved for later lightweight non-Go processors.
- Qwen, PaddleOCR, Qwen3-VL, Pebble materialization, and dashboard retrieval stay
  custom services.
