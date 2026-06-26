# Local Model Service Architecture

## Direction

Model execution belongs in a shared local model-serving layer on the RPC node.
Application services and batch jobs should call that layer through an API; they
should not own model weights, loading, concurrency, or CPU thread policy.

## Current State

`web-osint-qwen-inference.service` already acts as an API service for several
clients, including embedding workers, dashboard search, and repo-analysis. It is
still too coupled to Web OSINT naming and it loads multiple model families inside
one Python process:

- Qwen text embeddings.
- Qwen reranker.
- Qwen VL embedding.
- Qwen VL generative chat.
- Small specialized solver models for CAPTCHA/OCR helpers.

## Target Split

Use this service boundary:

```text
model runtime services
  load model weights
  run inference
  expose health, metrics, active/waiting state, and model inventory

model API / gateway
  stable HTTP surface for embedding, rerank, VL, OCR, and future models
  routes requests to the correct runtime
  exposes per-operation state checks

client services
  repo-analysis
  Web OSINT embedding worker
  dashboard/research search coordinator
  media enrichment workers
  batch backfills and evaluations
```

Clients may validate input size and choose when to call a model, but model work
must not be considered failed merely because it is slow. Slow transformer lanes
should use active/waiting state and metrics instead of queue timeouts or client
retries.

## Operational Rules

- Slow transformer lanes have no queue timeout: text embedding, query embedding,
  batch embedding, rerank, VL embedding, and VL chat.
- Keep queue limits and concurrency limits as backpressure.
- Expose `/healthz` guardrail state so operators can see whether work is active,
  waiting, idle, or blocked.
- Expose `/metrics` counters and durations by operation, model, and caller.
- Avoid client-side HTTP timeouts for slow model calls.
- Do not retry a model request while the model may still be working on it.

## Migration Path

1. Keep the existing Qwen API stable while removing timeout/retry behavior.
2. Add richer model inventory and operation-state endpoints.
3. Rename or wrap the Web OSINT-branded Qwen service behind a generic local model
   API.
4. Split heavyweight model families into separate runtime processes when memory,
   fault isolation, or scheduling requires it.
5. Keep repo-analysis and Web OSINT workers as clients of the model API.
