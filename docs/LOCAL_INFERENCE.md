# Local Inference Interface

Web OSINT is a client of the shared local model API. It does not own model
weights, model downloads, inference runtime dependencies, model service units,
or Hugging Face cache setup.

Model serving lives in:

```text
/home/ops/dev/prmartinow/local-inference
https://github.com/prmartinow/local-inference
```

The Web OSINT interface is the HTTP API URL:

```text
LOCAL_INFERENCE_URL=http://127.0.0.1:18200
```

Do not add `QWEN_INFERENCE_URL` compatibility paths back into Web OSINT. Older
Qwen-branded service names are migration history only.

## Client Responsibilities

Web OSINT may:

- choose when evidence should be embedded, reranked, or visually embedded;
- validate request sizes before sending work to the model API;
- write model outputs into Qdrant, ClickHouse, review objects, artifacts, and audit topics;
- display `/healthz` and `/metrics` from local-inference in operations views.

Web OSINT must not:

- download model weights;
- install or own model-serving Python environments;
- mount model directories into application containers;
- start `web-osint-qwen-*` model service units;
- install PaddleOCR/PaddleX/PaddlePaddle in Web OSINT worker venvs;
- read model files directly to infer availability.

## Local Inference Routes Used

```text
GET  /healthz
GET  /metrics
POST /embed
POST /rerank
POST /v1/chat/completions
POST /classify_recaptcha
POST /ocr
POST /media/ocr
POST /slide_gap
```

See the local-inference repo for model inventory, downloader services,
guardrails, slow-model no-timeout semantics, and candidate model manifests.

## Web OSINT Client Services

| Service | Port | Role |
| --- | ---: | --- |
| `web-osint-embedding-worker.service` | `127.0.0.1:18201` | Consumes observed evidence, calls `POST /embed`, and upserts named vectors into Qdrant |
| `web-osint-media-ocr-worker.service` | `127.0.0.1:18212` | Consumes OCR requests, calls `POST /media/ocr`, and writes OCR artifacts/projections |
| `web-osint-media-vl-worker.service` | `127.0.0.1:18213` | Calls `POST /embed model=vl` for media artifacts |
| `web-osint-qdrant-embedding-backfill.service` | n/a | One-shot ClickHouse-to-Qdrant backfill through `POST /embed` |
| Dashboard search coordinator | dashboard process | Calls `POST /embed` and optional `POST /rerank` for interactive search |

The embedding and media workers use Web OSINT client venvs, not the
local-inference service venv. These venvs contain pipeline dependencies such as
Kafka/HTTP/Qdrant/ClickHouse clients and image IO helpers; they must not contain
model runtimes such as PaddleOCR or transformer stacks:

```bash
scripts/init_embedding_worker_venv.sh
scripts/init_media_enrichment_venv.sh
```

## Vector Layout

The Qdrant evidence collection should use 4096-dimensional named vectors:

| Named vector | Source |
| --- | --- |
| `text_dense` | post text, web documents, search results, user notes |
| `ocr_dense` | OCR text from media artifacts |
| `caption_dense` | image/video captions and descriptions |
| `account_dense` | account bios/profile text |
| `vl_image_dense` | image/screenshot embeddings returned by local-inference |

The initializer refuses unsafe vector-size changes unless the existing
collection is empty and `QDRANT_RECREATE_EMPTY_ON_VECTOR_MISMATCH=true` is set.

## Operational Checks

Check the model API from the local-inference side:

```bash
systemctl --user status local-inference.service --no-pager
curl -fsS "${LOCAL_INFERENCE_URL:-http://127.0.0.1:18200}/healthz"
curl -fsS "${LOCAL_INFERENCE_URL:-http://127.0.0.1:18200}/metrics"
```

Check Web OSINT client workers:

```bash
systemctl --user status web-osint-embedding-worker.service --no-pager
systemctl --user status web-osint-media-ocr-worker.service --no-pager
systemctl --user status web-osint-media-vl-worker.service --no-pager
curl -fsS http://127.0.0.1:18201/stats
curl -fsS http://127.0.0.1:18212/stats
curl -fsS http://127.0.0.1:18213/stats
```

Existing ClickHouse evidence can be backfilled into Qdrant after
`local-inference.service` is healthy:

```bash
systemctl --user start web-osint-qdrant-embedding-backfill.service
journalctl --user -fu web-osint-qdrant-embedding-backfill.service -o cat
```

The backfill service is idempotent because Qdrant point IDs are deterministic
from evidence IDs and source-specific prefixes.

Embedding, VL embedding, rerank, and embedding backfill requests do not set HTTP
timeouts. Slow model state must be inspected through local-inference
`/healthz` guardrails and `/metrics`; Web OSINT clients should not retry while
the model may still be actively working. Backfill requests include
`X-Workload: batch` so local-inference routes them through the batch guardrail.
