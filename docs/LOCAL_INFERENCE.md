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

The service is verbose and resumable. It creates an isolated downloader venv on `/mnt/data`, installs `huggingface_hub[hf_xet]`, and downloads the three public model repos sequentially.

If `/home/ops/dev/huggingface.md` exists, the service extracts the first `hf_...` token from that file and exports it as `HF_TOKEN`. The token is never passed as a command-line argument.

Check progress:

```bash
systemctl --user status web-osint-qwen-model-downloads.service --no-pager
journalctl --user -fu web-osint-qwen-model-downloads.service -o cat
tail -F /mnt/data/web-osint-platform/logs/model-downloads/latest.log
watch -n 10 'du -sh /mnt/data/web-osint-platform/models/* 2>/dev/null; find /mnt/data/web-osint-platform/models -name "*.incomplete" -printf "%TY-%Tm-%Td %TH:%TM %s %p\n" 2>/dev/null | sort | tail -12'
```

Re-run or restart safely if the network drops:

```bash
systemctl --user restart web-osint-qwen-model-downloads.service
```

The Hugging Face downloader resumes already-present files instead of starting over.
