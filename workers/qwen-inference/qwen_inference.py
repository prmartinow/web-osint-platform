#!/usr/bin/env python3
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import torch
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


DATA_ROOT = Path(os.environ.get("WEB_OSINT_DATA_ROOT", "/mnt/data/web-osint-platform"))
TEXT_MODEL_DIR = Path(os.environ.get("QWEN_TEXT_EMBEDDING_MODEL_DIR", DATA_ROOT / "models/Qwen3-Embedding-8B"))
RERANKER_MODEL_DIR = Path(os.environ.get("QWEN_RERANKER_MODEL_DIR", DATA_ROOT / "models/Qwen3-Reranker-8B"))
VL_MODEL_DIR = Path(os.environ.get("QWEN_VL_EMBEDDING_MODEL_DIR", DATA_ROOT / "models/Qwen3-VL-Embedding-8B"))

DEFAULT_BATCH_SIZE = int(os.environ.get("QWEN_INFERENCE_BATCH_SIZE", "1"))
DEFAULT_MAX_LENGTH = int(os.environ.get("QWEN_INFERENCE_MAX_LENGTH", "8192"))
DEVICE = os.environ.get("QWEN_INFERENCE_DEVICE", "cpu")

torch.set_num_threads(int(os.environ.get("QWEN_INFERENCE_TORCH_THREADS", "32")))


class EmbeddingRequest(BaseModel):
    inputs: list[str | dict[str, Any]] = Field(default_factory=list)
    model: str = "text"
    prompt: str | None = None
    prompt_name: str | None = None
    batch_size: int | None = None
    normalize: bool = True


class OpenAIEmbeddingRequest(BaseModel):
    input: str | list[str]
    model: str | None = None
    encoding_format: str | None = None


class RerankRequest(BaseModel):
    query: str
    documents: list[str]
    instruction: str | None = None
    normalize: bool = False


class WarmupRequest(BaseModel):
    models: list[str] = Field(default_factory=lambda: ["text"])


@dataclass
class LoadedModel:
    name: str
    loaded_at: float
    model: Any


class ModelRegistry:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._models: dict[str, LoadedModel] = {}

    def loaded(self) -> dict[str, Any]:
        with self._lock:
            return {
                name: {
                    "loaded_at": item.loaded_at,
                    "loaded_for_seconds": round(time.time() - item.loaded_at, 2),
                }
                for name, item in self._models.items()
            }

    def get_sentence_transformer(self, name: str, path: Path):
        with self._lock:
            item = self._models.get(name)
            if item is not None:
                return item.model
            if not path.exists():
                raise RuntimeError(f"model path does not exist: {path}")

            from sentence_transformers import SentenceTransformer

            model = SentenceTransformer(
                str(path),
                device=DEVICE,
                trust_remote_code=True,
                model_kwargs={"torch_dtype": torch.bfloat16},
                tokenizer_kwargs={"padding_side": "left"},
            )
            if hasattr(model, "max_seq_length"):
                model.max_seq_length = DEFAULT_MAX_LENGTH
            self._models[name] = LoadedModel(name=name, loaded_at=time.time(), model=model)
            return model

    def get_cross_encoder(self):
        with self._lock:
            item = self._models.get("reranker")
            if item is not None:
                return item.model
            if not RERANKER_MODEL_DIR.exists():
                raise RuntimeError(f"model path does not exist: {RERANKER_MODEL_DIR}")

            from sentence_transformers import CrossEncoder

            model = CrossEncoder(
                str(RERANKER_MODEL_DIR),
                device=DEVICE,
                automodel_args={"torch_dtype": torch.bfloat16},
                tokenizer_args={"padding_side": "left"},
                trust_remote_code=True,
                max_length=DEFAULT_MAX_LENGTH,
            )
            self._models["reranker"] = LoadedModel(name="reranker", loaded_at=time.time(), model=model)
            return model


registry = ModelRegistry()
app = FastAPI(title="Web OSINT Qwen Inference", version="0.1.0")


def _as_list(input_value: str | list[str]) -> list[str]:
    if isinstance(input_value, str):
        return [input_value]
    return input_value


def _embedding_model(model_name: str):
    normalized = model_name.lower().replace("_", "-")
    if normalized in {"text", "qwen3-embedding-8b", "qwen/qwen3-embedding-8b"}:
        return registry.get_sentence_transformer("text", TEXT_MODEL_DIR), "Qwen3-Embedding-8B"
    if normalized in {"vl", "vl-image", "qwen3-vl-embedding-8b", "qwen/qwen3-vl-embedding-8b"}:
        return registry.get_sentence_transformer("vl", VL_MODEL_DIR), "Qwen3-VL-Embedding-8B"
    raise HTTPException(status_code=400, detail=f"unknown embedding model selector: {model_name}")


def _to_python_vectors(vectors: Any) -> list[list[float]]:
    arr = np.asarray(vectors, dtype=np.float32)
    if arr.ndim == 1:
        arr = arr.reshape(1, -1)
    return arr.tolist()


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {
        "ok": True,
        "device": DEVICE,
        "torch_threads": torch.get_num_threads(),
        "model_paths": {
            "text": str(TEXT_MODEL_DIR),
            "reranker": str(RERANKER_MODEL_DIR),
            "vl": str(VL_MODEL_DIR),
        },
        "model_path_exists": {
            "text": TEXT_MODEL_DIR.exists(),
            "reranker": RERANKER_MODEL_DIR.exists(),
            "vl": VL_MODEL_DIR.exists(),
        },
        "loaded": registry.loaded(),
    }


@app.post("/warmup")
def warmup(request: WarmupRequest) -> dict[str, Any]:
    warmed = []
    for name in request.models:
        selector = name.lower()
        if selector in {"text", "embedding"}:
            model = registry.get_sentence_transformer("text", TEXT_MODEL_DIR)
            model.encode(["web osint warmup"], batch_size=1, normalize_embeddings=True)
            warmed.append("text")
        elif selector in {"reranker", "rank"}:
            model = registry.get_cross_encoder()
            model.predict([("web osint query", "web osint document")])
            warmed.append("reranker")
        elif selector in {"vl", "vl-image"}:
            model = registry.get_sentence_transformer("vl", VL_MODEL_DIR)
            model.encode(["web osint visual warmup"], batch_size=1, normalize_embeddings=True)
            warmed.append("vl")
        else:
            raise HTTPException(status_code=400, detail=f"unknown warmup model: {name}")
    return {"ok": True, "warmed": warmed, "loaded": registry.loaded()}


@app.post("/embed")
def embed(request: EmbeddingRequest) -> dict[str, Any]:
    if not request.inputs:
        raise HTTPException(status_code=400, detail="inputs must not be empty")
    model, served_name = _embedding_model(request.model)
    kwargs: dict[str, Any] = {
        "batch_size": request.batch_size or DEFAULT_BATCH_SIZE,
        "normalize_embeddings": request.normalize,
        "convert_to_numpy": True,
        "show_progress_bar": False,
    }
    if request.prompt is not None:
        kwargs["prompt"] = request.prompt
    if request.prompt_name is not None:
        kwargs["prompt_name"] = request.prompt_name
    started = time.time()
    vectors = model.encode(request.inputs, **kwargs)
    elapsed_ms = round((time.time() - started) * 1000, 2)
    py_vectors = _to_python_vectors(vectors)
    return {
        "model": served_name,
        "dimension": len(py_vectors[0]) if py_vectors else 0,
        "count": len(py_vectors),
        "elapsed_ms": elapsed_ms,
        "data": [{"index": idx, "embedding": vector} for idx, vector in enumerate(py_vectors)],
    }


@app.post("/v1/embeddings")
def openai_embeddings(request: OpenAIEmbeddingRequest) -> dict[str, Any]:
    inputs = _as_list(request.input)
    response = embed(EmbeddingRequest(inputs=inputs, model=request.model or "text"))
    return {
        "object": "list",
        "model": response["model"],
        "data": [
            {"object": "embedding", "index": item["index"], "embedding": item["embedding"]}
            for item in response["data"]
        ],
        "usage": {"prompt_tokens": 0, "total_tokens": 0},
    }


@app.post("/rerank")
def rerank(request: RerankRequest) -> dict[str, Any]:
    if not request.query:
        raise HTTPException(status_code=400, detail="query must not be empty")
    if not request.documents:
        raise HTTPException(status_code=400, detail="documents must not be empty")
    model = registry.get_cross_encoder()
    pairs = [(request.query, doc) for doc in request.documents]
    started = time.time()
    kwargs: dict[str, Any] = {}
    if request.normalize:
        kwargs["activation_fn"] = torch.nn.Sigmoid()
    scores = model.predict(pairs, **kwargs)
    elapsed_ms = round((time.time() - started) * 1000, 2)
    raw_scores = np.asarray(scores, dtype=np.float32).reshape(-1).tolist()
    ranked = sorted(
        [
            {"index": idx, "score": float(score), "document": request.documents[idx]}
            for idx, score in enumerate(raw_scores)
        ],
        key=lambda item: item["score"],
        reverse=True,
    )
    return {"model": "Qwen3-Reranker-8B", "elapsed_ms": elapsed_ms, "results": ranked}
