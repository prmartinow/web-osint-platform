# Local Inference

The Web OSINT Platform uses local CPU inference for retrieval enrichment on the RPC node. The initial model set is intentionally high-accuracy bf16 safetensors on the data disk, not quantized GGUF/AWQ/INT8 variants.

## Models

| Role | Model | Local directory |
| --- | --- | --- |
| Default text embeddings | `Qwen/Qwen3-Embedding-8B` | `/mnt/data/web-osint-platform/models/Qwen3-Embedding-8B` |
| Reranking | `Qwen/Qwen3-Reranker-8B` | `/mnt/data/web-osint-platform/models/Qwen3-Reranker-8B` |
| Experimental multimodal embeddings | `Qwen/Qwen3-VL-Embedding-8B` | `/mnt/data/web-osint-platform/models/Qwen3-VL-Embedding-8B` |
| Generative VL chat / hCaptcha | `Qwen/Qwen3-VL-8B-Instruct` | `/mnt/data/web-osint-platform/models/Qwen3-VL-8B-Instruct` |
| reCAPTCHA tile classification | `DannyLuna/recaptcha-classification-57k` YOLOv8n ONNX | `/mnt/data/web-osint-platform/models/recaptcha-yolov8n/recaptcha_classification_57k.onnx` |
| Text OCR / slider-gap helper | `ddddocr` bundled ONNX | Python wheel cache in the inference venv |
| OCR/layout extraction | `PaddleOCR` 3.7 line | `/mnt/data/web-osint-platform/paddleocr` |

`Qwen3-Embedding-8B` is the default dense text embedder. Pair it with BM25/keyword/metadata filters from Typesense and with `Qwen3-Reranker-8B` for second-stage reranking.

`Qwen3-VL-Embedding-8B` is reserved for screenshots, charts, UI captures, benchmark tables, and other images where OCR may miss layout or visual context.

`PaddleOCR` is the OCR/layout source of truth for media artifacts. The media
enrichment installer pins the OCR stack to the 3.7 line:
`paddleocr>=3.7.0,<3.8.0`, `paddlex>=3.7.0,<3.8.0`, and
`paddlepaddle>=3.3.0,<3.4.0`. The live worker exposes its active runtime under
`GET /stats` on `127.0.0.1:18212`.

The ddddocr lanes are narrower Rebrowser helper routes, not the media OCR
source of truth. They are served from the inference API for distorted text and
slider matching. The helper runtime deps are pinned in
`workers/qwen-inference/requirements.txt`: `ultralytics`, `onnxruntime`,
`opencv-python-headless`, and `ddddocr`.

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

The download service is resumable. It creates an isolated downloader venv on
`/mnt/data`, installs `huggingface_hub[hf_xet]` when needed, downloads the four
Qwen checkpoints, and fetches the reCAPTCHA ONNX artifact. ddddocr models come
from the installed wheel, not the Hugging Face downloader.

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
| `web-osint-qwen-inference.service` | `127.0.0.1:18200` | FastAPI API for text embeddings, reranking, VL embeddings/chat, and specialized helper routes |
| `web-osint-embedding-worker.service` | `127.0.0.1:18201` | Redpanda observed-event consumer that embeds evidence text and upserts named vectors into Qdrant |

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
GET  /metrics
POST /warmup
POST /embed
POST /v1/embeddings
POST /rerank
POST /v1/chat/completions
POST /classify_recaptcha
POST /ocr
POST /slide_gap
```

The service enforces CPU-friendly guardrails at the API boundary:

| Operation | Default policy |
| --- | --- |
| Offline/chunk embedding | concurrency `1`, queue `64`, no queue timeout |
| Batch embedding | concurrency `1`, queue `1`, no queue timeout |
| Query embedding | concurrency `1`, queue `4`, no queue timeout |
| Rerank | concurrency `1`, queue `2`, no queue timeout, max `5` candidates |
| VL embedding | concurrency `1`, queue `16`, no queue timeout |
| Generative VL chat | concurrency `1`, queue `4`, no queue timeout |
| reCAPTCHA classifier | concurrency `2`, queue `8`, timeout `60s` |
| OCR | concurrency `2`, queue `8`, timeout `60s` |
| slide gap | concurrency `2`, queue `8`, timeout `60s` |

Slow transformer routes expose active/waiting state through `/healthz` and
duration/queue metrics through `/metrics`. Do not treat slow model work as a
timeout failure; inspect guardrail state to see whether the model is active,
waiting, idle, or failing.

Part A2 route smoke used synthetic fixtures only: `/classify_recaptcha`
classified a synthetic traffic-light tile at 90.6% in about 302 ms, `/ocr`
recognized text in about 20 ms, and `/slide_gap` returned the correct slider
offset in about 81 ms. Treat these as route smoke checks, not as production
benchmarks.

CPU-heavy user services also run through `scripts/run_with_cpu_thread_guard.sh`. By default, `WEB_OSINT_CPU_RESERVED_THREADS=2`, so the wrapper detects host logical threads with `nproc --all`, clamps Torch/OpenMP/MKL/OpenBLAS/Paddle thread pools to at most host logical threads minus the reserve, and, when `taskset` is available, runs the process with a CPU affinity mask that leaves the last two logical CPUs outside the Web OSINT worker affinity. The Qwen systemd unit intentionally leaves `QWEN_INFERENCE_TORCH_THREADS`, `OMP_NUM_THREADS`, and `MKL_NUM_THREADS` unset so the wrapper can derive the correct effective pool from the current host. Override `WEB_OSINT_CPU_RESERVED_THREADS` only if the RPC node's service mix changes. The Qwen `/healthz` response includes `cpu_thread_guard` so operators can verify the effective thread cap.

Rerank is intentionally a precision path, not a broad recall path. Feed it small candidate sets after keyword/vector/metadata retrieval. Oversized queries, candidate lists, and candidate texts are rejected with `413` rather than silently truncated.

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
curl -fsS http://127.0.0.1:18200/metrics
curl -fsS http://127.0.0.1:18201/stats
curl -fsS http://127.0.0.1:18212/stats
```

Existing ClickHouse evidence can be backfilled into Qdrant after the model service is healthy:

```bash
systemctl --user start web-osint-qdrant-embedding-backfill.service
journalctl --user -fu web-osint-qdrant-embedding-backfill.service -o cat
```

The backfill service is idempotent because Qdrant point IDs are deterministic from evidence IDs and source-specific prefixes.
