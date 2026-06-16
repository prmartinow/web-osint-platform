# Local Inference

The Web OSINT Platform uses local CPU inference for retrieval enrichment on the RPC node. The initial model set is intentionally high-accuracy bf16 safetensors on the data disk, not quantized GGUF/AWQ/INT8 variants.

## Models

| Role | Model | Local directory |
| --- | --- | --- |
| Default text embeddings | `Qwen/Qwen3-Embedding-8B` | `/mnt/data/web-osint-platform/models/Qwen3-Embedding-8B` |
| Reranking | `Qwen/Qwen3-Reranker-8B` | `/mnt/data/web-osint-platform/models/Qwen3-Reranker-8B` |
| Experimental multimodal embeddings | `Qwen/Qwen3-VL-Embedding-8B` | `/mnt/data/web-osint-platform/models/Qwen3-VL-Embedding-8B` |

`Qwen3-Embedding-8B` is the default dense text embedder. Pair it with BM25/keyword/metadata filters from Typesense and with `Qwen3-Reranker-8B` for second-stage reranking.

`Qwen3-VL-Embedding-8B` is reserved for screenshots, charts, UI captures, benchmark tables, and other images where OCR may miss layout or visual context.

## Qdrant Vector Layout

The Qdrant evidence collection should use 4096-dimensional named vectors:

| Named vector | Source |
| --- | --- |
| `text_dense` | post text, web documents, search results, user notes |
| `ocr_dense` | OCR text from media artifacts |
| `caption_dense` | image/video captions and descriptions |
| `account_dense` | account bios/profile text |
| `vl_image_dense` | experimental VL embeddings for screenshots/images |

The initializer refuses unsafe vector-size changes unless the existing collection is empty and `QDRANT_RECREATE_EMPTY_ON_VECTOR_MISMATCH=true` is set.

## Download Service

Install the user service on the RPC node:

```bash
sudo chown -R ops:ops /mnt/data/web-osint-platform
mkdir -p ~/.config/systemd/user
cp systemd/user/web-osint-qwen-model-downloads.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now web-osint-qwen-model-downloads.service
```

The download service is resumable. It creates an isolated downloader venv on `/mnt/data`, installs `huggingface_hub[hf_xet]` when needed, and downloads the three public model repos sequentially.

Install the companion progress service if you want live elapsed-time and transfer-rate logging:

```bash
cp systemd/user/web-osint-qwen-model-download-progress.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now web-osint-qwen-model-download-progress.service
```

If `/home/ops/dev/huggingface.md` exists, the service extracts the first `hf_...` token from that file and exports it as `HF_TOKEN`. The token is never passed as a command-line argument.

Check progress:

```bash
systemctl --user status web-osint-qwen-model-downloads.service --no-pager
systemctl --user status web-osint-qwen-model-download-progress.service --no-pager
tail -F /mnt/data/web-osint-platform/logs/model-downloads/latest-progress.log
```

`latest-progress.log` is the preferred operator view. It emits timer and transfer-rate lines such as `service_elapsed=00:42:10`, `window_rate=18.32MiB/s`, `avg_rate=15.71MiB/s`, active model, socket count, per-model directory sizes, and the largest active `.incomplete` files. `latest.log` remains the raw Hugging Face CLI log and can include startup/install details or non-tail-friendly progress-bar output.

Re-run or restart safely if the network drops:

```bash
systemctl --user restart web-osint-qwen-model-downloads.service
```

The Hugging Face downloader resumes already-present files instead of starting over.

## Inference And Embedding Services

The RPC node runs local CPU inference as user services:

| Service | Port | Role |
| --- | ---: | --- |
| `web-osint-qwen-inference.service` | `127.0.0.1:18200` | FastAPI API for text embeddings, reranking, and experimental VL embeddings |
| `web-osint-embedding-worker.service` | `127.0.0.1:18201` | Kafka observed-event consumer that embeds evidence text and upserts named vectors into Qdrant |

Install/start:

```bash
cp systemd/user/web-osint-qwen-inference.service ~/.config/systemd/user/
cp systemd/user/web-osint-embedding-worker.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now web-osint-qwen-inference.service
systemctl --user enable --now web-osint-embedding-worker.service
```

The inference service creates its Python environment under `/mnt/data/web-osint-platform/.venv-qwen-inference`, then serves:

```text
GET  /healthz
POST /warmup
POST /embed
POST /v1/embeddings
POST /rerank
```

The embedding worker consumes these observed topics:

```text
evidence.posts.observed.v1
evidence.accounts.observed.v1
evidence.media.observed.v1
evidence.search.results.v1
evidence.web.documents.observed.v1
evidence.user.inputs.observed.v1
```

It writes vector data to Qdrant collection `web_osint_evidence_v1` using named vectors `text_dense`, `account_dense`, `ocr_dense`, and `caption_dense`, and emits vector metadata to `osint.semantic.embedded.v1`. Evidence text is capped before embedding by default so oversized pages do not monopolize CPU inference; tune `EMBEDDING_WORKER_MAX_TEXT_CHARS` and `BACKFILL_MAX_TEXT_CHARS` if a backfill needs deeper context. The ClickHouse backfill processes shorter evidence first to produce useful Qdrant coverage quickly.

Operational checks:

```bash
systemctl --user status web-osint-qwen-inference.service --no-pager
systemctl --user status web-osint-embedding-worker.service --no-pager
curl -fsS http://127.0.0.1:18200/healthz
curl -fsS http://127.0.0.1:18201/stats
```

Existing ClickHouse evidence can be backfilled into Qdrant after the model service is healthy:

```bash
systemctl --user start web-osint-qdrant-embedding-backfill.service
journalctl --user -fu web-osint-qdrant-embedding-backfill.service -o cat
```

The backfill service is idempotent because Qdrant point IDs are deterministic from evidence IDs and source-specific prefixes.
