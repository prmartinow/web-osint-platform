# Redpanda Connect Shadow Parity Proof - 2026-06-18

This note records the live P0 parity proof for the Redpanda Connect shadow
validator path. It is intentionally scoped to capture-envelope validation and
shadow preservation of the published event. Production routing still goes
through the existing Go normalizer/materializer.

## Scope

Proved:

- The custom Redpanda Connect binary starts as a live shadow sidecar.
- The compiled `capture_envelope_validate` plugin accepts a valid capture event.
- The event emitted to `evidence.capture.shadow.validated.v1` is canonically
  identical to the capture event published to `evidence.capture.events.v1`.
- The production normalizer materializes the expected `user_input/...` evidence
  ID from the same capture event.
- The rest of the current live path continues through ClickHouse, local Qwen
  embedding, Qdrant, and dashboard hydration.

Not proved yet:

- Source-kind router parity.
- Observed-event projector parity.
- Media request builder parity.
- DLQ enricher parity.
- Any production cutover from the Go normalizer/materializer to Connect.

## Live Shadow Service

Container:

```text
x-research-connect-shadow
image: web-osint-connect-shadow:69aa8d3
port: 127.0.0.1:14195 -> 4195
restart policy: unless-stopped
network: x-research_default
```

Readiness check:

```json
{"statuses":[{"label":"capture_events","path":"input","connected":true},{"label":"","path":"output","connected":true}]}
```

Consumer group:

```text
GROUP      web-osint-connect-shadow-v1
STATE      Stable
MEMBERS    1
TOTAL-LAG  0
```

Topic watermarks after the proof run:

```text
evidence.capture.shadow.validated.v1 high-watermark: 8
evidence.capture.shadow.errors.v1    high-watermark: 0
```

## Strict Canary Run

Command:

```bash
cd /home/ops/dev/x-research
python3 scripts/run_e2e_canary.py \
  --env-file .env \
  --pandaproxy-url http://127.0.0.1:18082 \
  --clickhouse-url http://127.0.0.1:18123 \
  --qdrant-url http://127.0.0.1:16333 \
  --dashboard-url http://192.168.1.16:18191 \
  --expect-shadow \
  --timeout-seconds 900
```

Result artifact:

```text
/mnt/data/x-research/canaries/runs/e2e_canary_20260618T025352Z_1a6fb8.json
```

Summary:

```text
status: passed
expected_chunks: 1
observed_chunks: 1
embedded_chunks: 1
qdrant_points_found: 1
dashboard_exact_rank: 1
shadow_validated_events: 1
shadow_matches_published_capture: true
production_observed_matches_capture: true
errors: []
```

Hash equality:

```text
published_capture_sha256: 56d3ceefe8d585456218d1cca0380680d9ce26320334459ae045ea5c9152a6b6
shadow_capture_sha256:    56d3ceefe8d585456218d1cca0380680d9ce26320334459ae045ea5c9152a6b6
```

Evidence ID equality:

```text
captured_evidence_ids:
  user_input/research-doc-canary-ce95d1e8d50ce3fb1d1c-chunk-0001

observed_evidence_ids:
  user_input/research-doc-canary-ce95d1e8d50ce3fb1d1c-chunk-0001
```

Embedding and retrieval:

```text
embedding_model: Qwen3-Embedding-8B
embedding_dimension: 4096
vector_names: text_dense
qdrant_collection: x_research_evidence_v1
dashboard hydration: ok
```

## Interpretation

This proves the current P0 boundary: the Connect shadow validator preserves the
published capture envelope exactly, and the unchanged production path
materializes the expected evidence from that event while the downstream pipeline
still reaches Qdrant and the dashboard.

This is not yet evidence that Connect can replace production routing or
projection. Those are separate P1/P2 parity checks after the router/projector
plugins exist.
