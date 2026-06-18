# Web OSINT Redpanda Connect

This directory contains the Redpanda Connect shadow path. It is additive and
must not replace the production Go normalizer/materializer until parity canaries
prove the output is equivalent for the selected source kinds.

## Layout

```text
connect/
  cmd/web-osint-connect/       custom Redpanda Connect binary entrypoint
  plugins/                     compiled Go plugins
  pipelines/                   thin YAML wiring
```

## Current Shadow Pipeline

`pipelines/capture-shadow-validate.yaml` consumes
`evidence.capture.events.v1`, runs the compiled
`capture_envelope_validate` processor, writes valid messages to
`evidence.capture.shadow.validated.v1`, and writes validation failures to
`evidence.capture.shadow.errors.v1`.

The pinned Redpanda Connect version exposes stream I/O through the
`kafka_franz` component, pointed at Redpanda brokers. Treat that component name
as a wire-protocol detail: this is still Redpanda Connect reading and writing
Redpanda topics. The `redpanda` component package is also imported so later
Data Transform processors can be enabled without changing the binary skeleton.

Run through Compose:

```bash
docker compose --env-file .env -f compose/docker-compose.yml --profile shadow up -d --build redpanda-connect-shadow
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
