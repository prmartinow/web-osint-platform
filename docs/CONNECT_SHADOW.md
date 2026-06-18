# Redpanda Connect Shadow Pipeline

The first Redpanda Connect integration is a shadow-only validation pipeline.
It must not replace the production Go normalizer/materializer until parity is
proven.

## Target

```text
evidence.capture.events.v1
  -> capture_envelope_validate compiled Go plugin
  -> evidence.capture.shadow.validated.v1

processor/output failures
  -> evidence.capture.shadow.errors.v1
```

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

## Cutover Guardrails

- Keep the Go normalizer/materializer as the production path.
- Shadow output must match stable fields for canary events before any cutover.
- Production cutover is allowed only after replay/parity checks pass and rollback
  is documented.
- Connect YAML is wiring only; custom deterministic logic belongs in compiled Go
  plugins.
