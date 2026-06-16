# Qwen Inference Worker

Local FastAPI service for the Web OSINT Platform's Qwen model set.

Endpoints:

- `GET /healthz`
- `POST /warmup`
- `POST /embed`
- `POST /v1/embeddings`
- `POST /rerank`

The service uses the completed model directories under `/mnt/data/web-osint-platform/models` and lazy-loads models on first use. The text embedding endpoint is the path used by the embedding worker for Qdrant indexing. The reranker and VL embedding endpoints are available for query-time and media workflows.
