# Web OSINT Platform Agent Rules

This repository is the sanitized control plane for the local Web OSINT evidence platform. Current scope is deterministic ingestion, enrichment, annotations, search, research signals, research questions, and task seeds. The autonomous agent execution loop is deferred.

## Safety

- Do not ask for, print, commit, or exfiltrate secrets, browser cookies, private captured evidence, auth tokens, credentials, or private source material.
- Tests and canaries must use synthetic data unless the user explicitly authorizes a real evidence sample.
- Keep captured evidence, media, OCR outputs, vector artifacts, model caches, Redpanda logs, Pebble state, Qdrant/Typesense/ClickHouse data, and local outboxes out of git.

## Storage

- Code/control belongs under `/home/ops/dev`.
- Durable evidence/data belongs under `/mnt/data/x-research` in the live deployment.
- Model/inference files belong under `/mnt/data/web-osint-platform`.
- Sanitized defaults may use `web_osint` names, but code must keep live database, collection, and root paths environment-configurable.
- New workers that write durable files must validate resolved paths at startup and fail closed unless an explicit test override is set.

## Live Names

- Live ClickHouse database: `x_research`.
- Live Qdrant collection: `x_research_evidence_v1`.
- Sanitized defaults: `web_osint` and `web_osint_evidence_v1`.
- Do not create a second production database or Qdrant collection to paper over a config mismatch.

## Inference

- Use the guarded Qwen inference service for embeddings and reranking.
- Do not bypass queue/concurrency limits.
- Default dashboard search must not synchronously rerank.
- Rerank is explicit precision mode only, with a hard cap of 5 candidates. Broad rerank requests should reject, not silently truncate.
- PaddleOCR is the OCR/layout source of truth. Qwen3-VL-Embedding is for visual embeddings, not OCR.

## Redpanda

- Describe the stream layer as Redpanda Streaming topics, not a Kafka cluster.
- Kafka-compatible APIs and client libraries are allowed as Redpanda data-plane clients. Do not replace working direct clients without a parity canary.
- Prefer `REDPANDA_BROKERS` and `REDPANDA_GROUP_ID` for new configuration. Existing `KAFKA_*` names are compatibility fallbacks only.
- Redpanda Connect YAML is wiring, not business logic. Put deterministic hot-path logic in compiled Go plugins.
- Use Redpanda Connect dynamic gRPC plugins only for lightweight isolated processors. Do not wrap Qwen, PaddleOCR, Qwen3-VL, Pebble materialization, or dashboard retrieval as gRPC plugins in v1.
- Run Connect routing in shadow mode before production cutover, and keep the Go normalizer/materializer rollback path until parity is proven.

## Provenance

- Normal ingestion flows through Redpanda.
- Every evidence item needs a source kind, evidence ID, source project, capture method, timestamps, and hashes/provenance where available.
- Derived outputs need producer name, producer version, input artifact hash, params hash, status/confidence, and timestamp.

## Canaries

- Run the E2E ingestion canary after changes to ingestion, normalizer, embedding worker, Qdrant, dashboard search, or ClickHouse hydration.
- Run the media enrichment canary after changes to OCR, VL, media workers, media topics, or media tables.
- When the Connect shadow service is running, run the E2E canary with `--expect-shadow` before changing routing behavior.

## Deferred

- Do not implement the autonomous agent execution loop yet.
- Do not add cloud OCR.
- Do not replace Redpanda, Pebble, Typesense, Qdrant, ClickHouse, or filesystem storage without an explicit migration request.
