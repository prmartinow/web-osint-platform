#!/usr/bin/env python3
from __future__ import annotations

import os
import threading
import time
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import torch
from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field


DATA_ROOT = Path(os.environ.get("WEB_OSINT_DATA_ROOT", "/mnt/data/web-osint-platform"))
TEXT_MODEL_DIR = Path(os.environ.get("QWEN_TEXT_EMBEDDING_MODEL_DIR", DATA_ROOT / "models/Qwen3-Embedding-8B"))
RERANKER_MODEL_DIR = Path(os.environ.get("QWEN_RERANKER_MODEL_DIR", DATA_ROOT / "models/Qwen3-Reranker-8B"))
VL_MODEL_DIR = Path(os.environ.get("QWEN_VL_EMBEDDING_MODEL_DIR", DATA_ROOT / "models/Qwen3-VL-Embedding-8B"))
# The Qwen3-VL-Embedding-8B checkpoint is architecturally Qwen3VLForConditionalGeneration
# (generative-capable). The generative route loads it as a vision-to-text model, separate
# from the SentenceTransformer embedding path above. Defaults to the same weights on disk.
VL_GENERATIVE_MODEL_DIR = Path(
    os.environ.get("QWEN_VL_GENERATIVE_MODEL_DIR", DATA_ROOT / "models/Qwen3-VL-Embedding-8B")
)

DEFAULT_BATCH_SIZE = int(os.environ.get("QWEN_INFERENCE_BATCH_SIZE", "1"))
DEFAULT_MAX_LENGTH = int(os.environ.get("QWEN_INFERENCE_MAX_LENGTH", "8192"))
DEVICE = os.environ.get("QWEN_INFERENCE_DEVICE", "cpu")


def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def cpu_thread_guard() -> dict[str, int]:
    total = env_int("WEB_OSINT_CPU_TOTAL_THREADS", os.cpu_count() or 1)
    total = max(1, total)
    reserved = max(0, env_int("WEB_OSINT_CPU_RESERVED_THREADS", 2))
    if reserved >= total:
        reserved = total - 1 if total > 1 else 0
    effective = max(1, total - reserved)
    requested = max(1, env_int("QWEN_INFERENCE_TORCH_THREADS", effective))
    torch_threads = min(requested, effective)
    return {
        "total_threads": total,
        "reserved_threads": reserved,
        "effective_threads": effective,
        "requested_torch_threads": requested,
        "torch_threads": torch_threads,
    }


CPU_THREAD_GUARD = cpu_thread_guard()
torch.set_num_threads(CPU_THREAD_GUARD["torch_threads"])


def env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except ValueError:
        return default


EMBED_CONCURRENCY = env_int("QWEN_EMBED_CONCURRENCY", 1)
EMBED_QUEUE_LIMIT = env_int("QWEN_EMBED_QUEUE_LIMIT", 64)
EMBED_QUEUE_TIMEOUT = env_float("QWEN_EMBED_QUEUE_TIMEOUT_SECONDS", 300)
BATCH_EMBED_QUEUE_LIMIT = env_int("QWEN_BATCH_EMBED_QUEUE_LIMIT", 1)
QUERY_EMBED_QUEUE_LIMIT = env_int("QWEN_QUERY_EMBED_QUEUE_LIMIT", 4)
QUERY_EMBED_QUEUE_TIMEOUT = env_float("QWEN_QUERY_EMBED_QUEUE_TIMEOUT_SECONDS", 60)
RERANK_CONCURRENCY = env_int("QWEN_RERANK_CONCURRENCY", 1)
RERANK_QUEUE_LIMIT = env_int("QWEN_RERANK_QUEUE_LIMIT", 2)
RERANK_QUEUE_TIMEOUT = env_float("QWEN_RERANK_QUEUE_TIMEOUT_SECONDS", 240)
VL_CONCURRENCY = env_int("QWEN_VL_CONCURRENCY", 1)
VL_QUEUE_LIMIT = env_int("QWEN_VL_QUEUE_LIMIT", 16)
VL_QUEUE_TIMEOUT = env_float("QWEN_VL_QUEUE_TIMEOUT_SECONDS", 300)
# Generative VL route runs on CPU; expect tens of seconds per image+prompt.
# Single-flight with a small queue and generous timeout.
CHAT_CONCURRENCY = env_int("QWEN_CHAT_CONCURRENCY", 1)
CHAT_QUEUE_LIMIT = env_int("QWEN_CHAT_QUEUE_LIMIT", 4)
CHAT_QUEUE_TIMEOUT = env_float("QWEN_CHAT_QUEUE_TIMEOUT_SECONDS", 600)
# Specialized solvers (reCAPTCHA classifier, OCR, slider gap). Small ONNX models,
# CPU-fast (~50-300ms), so they can run at higher concurrency than the big
# transformer routes above. Two dedicated guards so a slow VLM/rerank call never
# blocks a quick classifier call.
RECAPTCHA_CONCURRENCY = env_int("QWEN_RECAPTCHA_CONCURRENCY", 2)
RECAPTCHA_QUEUE_LIMIT = env_int("QWEN_RECAPTCHA_QUEUE_LIMIT", 8)
RECAPTCHA_QUEUE_TIMEOUT = env_float("QWEN_RECAPTCHA_QUEUE_TIMEOUT_SECONDS", 60)
OCR_CONCURRENCY = env_int("QWEN_OCR_CONCURRENCY", 2)
OCR_QUEUE_LIMIT = env_int("QWEN_OCR_QUEUE_LIMIT", 8)
OCR_QUEUE_TIMEOUT = env_float("QWEN_OCR_QUEUE_TIMEOUT_SECONDS", 60)
SLIDE_CONCURRENCY = env_int("QWEN_SLIDE_CONCURRENCY", 2)
SLIDE_QUEUE_LIMIT = env_int("QWEN_SLIDE_QUEUE_LIMIT", 8)
SLIDE_QUEUE_TIMEOUT = env_float("QWEN_SLIDE_QUEUE_TIMEOUT_SECONDS", 60)

EMBED_MAX_INPUT_CHARS = env_int("QWEN_EMBED_MAX_INPUT_CHARS", 12000)
RERANK_MAX_QUERY_CHARS = env_int("QWEN_RERANK_MAX_QUERY_CHARS", 1500)
RERANK_MAX_CANDIDATES = env_int("QWEN_RERANK_MAX_CANDIDATES", 5)
RERANK_MAX_CANDIDATE_CHARS = env_int("QWEN_RERANK_MAX_CANDIDATE_CHARS", 2500)
RERANK_MAX_TOTAL_CANDIDATE_CHARS = env_int("QWEN_RERANK_MAX_TOTAL_CANDIDATE_CHARS", 12000)
CHAT_MAX_INPUT_CHARS = env_int("QWEN_CHAT_MAX_INPUT_CHARS", 6000)
CHAT_MAX_NEW_TOKENS = env_int("QWEN_CHAT_MAX_NEW_TOKENS", 64)
# Specialized solver model path (YOLOv8n classifier fine-tuned on the 14
# reCAPTCHA classes; ddddocr ships its own bundled ONNX in the wheel, no dir).
RECAPTCHA_MODEL_PATH = Path(
    os.environ.get(
        "QWEN_RECAPTCHA_MODEL_PATH",
        DATA_ROOT / "models/recaptcha-yolov8n/recaptcha_classification_57k.onnx",
    )
)
RECAPTCHA_CONFIDENCE_THRESHOLD = env_float("QWEN_RECAPTCHA_CONFIDENCE_THRESHOLD", 0.40)


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


class ChatCompletionRequest(BaseModel):
    # OpenAI-shaped request. `image_path` is a server-side file path read by the
    # server (same-host convention used by the existing /embed VL path), not base64.
    model: str = "vl"
    messages: list[dict[str, Any]]
    image_path: str | None = None
    max_tokens: int | None = None
    temperature: float | None = None


class ClassifyRecaptchaRequest(BaseModel):
    # One or more tile image paths. The classifier returns a label + confidence
    # per tile. `target` optionally filters results to only that class.
    image_paths: list[str]
    target: str | None = None
    confidence_threshold: float | None = None


class OcrRequest(BaseModel):
    image_path: str


class SlideGapRequest(BaseModel):
    # Two server-side image paths: the full background and the slider piece.
    bg_path: str
    slider_path: str
    # simple=True is faster but slightly less accurate; matches ddddocr's API.
    simple: bool = True


@dataclass
class LoadedModel:
    name: str
    loaded_at: float
    model: Any


class InferenceMetrics:
    def __init__(self) -> None:
        self.started_at = time.time()
        self._lock = threading.Lock()
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
        self._observations: dict[tuple[str, tuple[tuple[str, str], ...]], dict[str, float]] = defaultdict(
            lambda: {"count": 0.0, "sum": 0.0, "max": 0.0}
        )

    def _labels(self, labels: dict[str, Any] | None = None) -> tuple[tuple[str, str], ...]:
        return tuple(sorted((str(key), str(value)) for key, value in (labels or {}).items()))

    def inc(self, name: str, labels: dict[str, Any] | None = None, amount: float = 1.0) -> None:
        with self._lock:
            self._counters[(name, self._labels(labels))] += amount

    def observe(self, name: str, value: float, labels: dict[str, Any] | None = None) -> None:
        with self._lock:
            item = self._observations[(name, self._labels(labels))]
            item["count"] += 1
            item["sum"] += float(value)
            item["max"] = max(item["max"], float(value))

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "started_at": self.started_at,
                "counters": [
                    {"name": name, "labels": dict(labels), "value": value}
                    for (name, labels), value in sorted(self._counters.items())
                ],
                "observations": [
                    {"name": name, "labels": dict(labels), **values}
                    for (name, labels), values in sorted(self._observations.items())
                ],
            }

    def prometheus(self, guards: dict[str, "Guardrail"]) -> str:
        lines = [
            "# HELP web_osint_qwen_requests_total Qwen inference requests by operation and status.",
            "# TYPE web_osint_qwen_requests_total counter",
        ]
        with self._lock:
            for (name, labels), value in sorted(self._counters.items()):
                lines.append(f"{name}{format_labels(dict(labels))} {value}")
            for (name, labels), values in sorted(self._observations.items()):
                label_text = format_labels(dict(labels))
                lines.append(f"{name}_count{label_text} {values['count']}")
                lines.append(f"{name}_sum{label_text} {values['sum']}")
                lines.append(f"{name}_max{label_text} {values['max']}")
        lines.extend(
            [
                "# HELP web_osint_qwen_guardrail_active Active requests inside each Qwen guardrail.",
                "# TYPE web_osint_qwen_guardrail_active gauge",
            ]
        )
        for name, guard in sorted(guards.items()):
            snapshot = guard.snapshot()
            label = format_labels({"operation": name})
            lines.append(f"web_osint_qwen_guardrail_active{label} {snapshot['active']}")
            lines.append(f"web_osint_qwen_guardrail_waiting{label} {snapshot['waiting']}")
            lines.append(f"web_osint_qwen_guardrail_concurrency{label} {snapshot['concurrency']}")
            lines.append(f"web_osint_qwen_guardrail_queue_limit{label} {snapshot['queue_limit']}")
        return "\n".join(lines) + "\n"


class Guardrail:
    def __init__(self, name: str, concurrency: int, queue_limit: int, queue_timeout: float | None) -> None:
        self.name = name
        self.concurrency = max(1, concurrency)
        self.queue_limit = max(0, queue_limit)
        self.queue_timeout = None if queue_timeout is None else max(0.0, queue_timeout)
        self._semaphore = threading.BoundedSemaphore(self.concurrency)
        self._lock = threading.Lock()
        self._waiting = 0
        self._active = 0

    @contextmanager
    def slot(self):
        queued_at = time.time()
        with self._lock:
            if self._waiting >= self.queue_limit:
                raise HTTPException(status_code=429, detail=f"{self.name} queue is full")
            self._waiting += 1
        if self.queue_timeout is None:
            acquired = self._semaphore.acquire()
        else:
            acquired = self._semaphore.acquire(timeout=self.queue_timeout)
        wait_seconds = time.time() - queued_at
        with self._lock:
            self._waiting -= 1
            if acquired:
                self._active += 1
        if not acquired:
            raise HTTPException(status_code=503, detail=f"{self.name} queue wait timed out")
        try:
            yield wait_seconds
        finally:
            with self._lock:
                self._active -= 1
            self._semaphore.release()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "concurrency": self.concurrency,
                "queue_limit": self.queue_limit,
                "queue_timeout_seconds": self.queue_timeout,
                "waiting": self._waiting,
                "active": self._active,
            }


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

    def get_vl_generative(self):
        # Returns (model, processor). Stored together under one LoadedModel entry.
        with self._lock:
            item = self._models.get("vl_generative")
            if item is not None:
                model, processor = item.model
                return model, processor
            if not VL_GENERATIVE_MODEL_DIR.exists():
                raise RuntimeError(f"model path does not exist: {VL_GENERATIVE_MODEL_DIR}")

            from transformers import AutoModelForImageTextToText, AutoProcessor

            model = AutoModelForImageTextToText.from_pretrained(
                str(VL_GENERATIVE_MODEL_DIR),
                device_map=DEVICE,
                torch_dtype=torch.bfloat16,
                trust_remote_code=True,
            )
            processor = AutoProcessor.from_pretrained(
                str(VL_GENERATIVE_MODEL_DIR),
                trust_remote_code=True,
            )
            self._models["vl_generative"] = LoadedModel(
                name="vl_generative",
                loaded_at=time.time(),
                model=(model, processor),
            )
            return model, processor

    def get_recaptcha_classifier(self):
        # YOLOv8n classifier (ONNX). Cached as a single ultralytics.YOLO instance.
        with self._lock:
            item = self._models.get("recaptcha_classifier")
            if item is not None:
                return item.model
            if not RECAPTCHA_MODEL_PATH.exists():
                raise RuntimeError(f"model path does not exist: {RECAPTCHA_MODEL_PATH}")

            from ultralytics import YOLO

            model = YOLO(str(RECAPTCHA_MODEL_PATH), task="classify")
            self._models["recaptcha_classifier"] = LoadedModel(
                name="recaptcha_classifier",
                loaded_at=time.time(),
                model=model,
            )
            return model

    def get_ocr(self):
        # ddddocr ships its own bundled ONNX in the wheel. Three separate
        # instances because ddddocr configures them with different flags.
        with self._lock:
            item = self._models.get("ocr")
            if item is not None:
                return item.model
            import ddddocr

            bundle = {
                "ocr": ddddocr.DdddOcr(show_ad=False),
                "slide": ddddocr.DdddOcr(ocr=False, det=False, show_ad=False),
            }
            self._models["ocr"] = LoadedModel(
                name="ocr",
                loaded_at=time.time(),
                model=bundle,
            )
            return bundle


registry = ModelRegistry()
metrics = InferenceMetrics()
guardrails = {
    "embed": Guardrail("embed", EMBED_CONCURRENCY, EMBED_QUEUE_LIMIT, EMBED_QUEUE_TIMEOUT),
    "batch_embed": Guardrail("batch_embed", EMBED_CONCURRENCY, BATCH_EMBED_QUEUE_LIMIT, None),
    "query_embed": Guardrail("query_embed", EMBED_CONCURRENCY, QUERY_EMBED_QUEUE_LIMIT, QUERY_EMBED_QUEUE_TIMEOUT),
    "rerank": Guardrail("rerank", RERANK_CONCURRENCY, RERANK_QUEUE_LIMIT, RERANK_QUEUE_TIMEOUT),
    "vl": Guardrail("vl", VL_CONCURRENCY, VL_QUEUE_LIMIT, VL_QUEUE_TIMEOUT),
    "chat": Guardrail("chat", CHAT_CONCURRENCY, CHAT_QUEUE_LIMIT, CHAT_QUEUE_TIMEOUT),
    "recaptcha": Guardrail("recaptcha", RECAPTCHA_CONCURRENCY, RECAPTCHA_QUEUE_LIMIT, RECAPTCHA_QUEUE_TIMEOUT),
    "ocr": Guardrail("ocr", OCR_CONCURRENCY, OCR_QUEUE_LIMIT, OCR_QUEUE_TIMEOUT),
    "slide": Guardrail("slide", SLIDE_CONCURRENCY, SLIDE_QUEUE_LIMIT, SLIDE_QUEUE_TIMEOUT),
}
app = FastAPI(title="Web OSINT Qwen Inference", version="0.1.0")


def _as_list(input_value: str | list[str]) -> list[str]:
    if isinstance(input_value, str):
        return [input_value]
    return input_value


def format_labels(labels: dict[str, Any]) -> str:
    if not labels:
        return ""
    parts = []
    for key, value in sorted(labels.items()):
        safe_value = str(value).replace("\\", "\\\\").replace('"', '\\"')
        parts.append(f'{key}="{safe_value}"')
    return "{" + ",".join(parts) + "}"


def caller_from(request: Request | None) -> str:
    if request is None:
        return "internal"
    return request.headers.get("x-caller") or request.headers.get("user-agent", "unknown").split(" ", 1)[0][:60]


def is_batch_embedding_request(request: Request | None) -> bool:
    if request is None:
        return False
    workload = (request.headers.get("x-workload") or request.headers.get("x-qwen-workload") or "").strip().lower()
    return workload in {"batch", "offline", "backfill"}


def input_char_count(inputs: list[str | dict[str, Any]]) -> int:
    total = 0
    for item in inputs:
        if isinstance(item, str):
            total += len(item)
        else:
            total += len(json_dumps_compact(item))
    return total


def json_dumps_compact(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def validate_embedding_inputs(inputs: list[str | dict[str, Any]]) -> None:
    for idx, item in enumerate(inputs):
        text = item if isinstance(item, str) else json_dumps_compact(item)
        if len(text) > EMBED_MAX_INPUT_CHARS:
            raise HTTPException(
                status_code=413,
                detail=f"embedding input {idx} is {len(text)} chars; max is {EMBED_MAX_INPUT_CHARS}",
            )


def validate_rerank_request(request: RerankRequest) -> None:
    if len(request.query) > RERANK_MAX_QUERY_CHARS:
        raise HTTPException(
            status_code=413,
            detail=f"rerank query is {len(request.query)} chars; max is {RERANK_MAX_QUERY_CHARS}",
        )
    if len(request.documents) > RERANK_MAX_CANDIDATES:
        raise HTTPException(
            status_code=413,
            detail=f"rerank documents has {len(request.documents)} candidates; max is {RERANK_MAX_CANDIDATES}",
        )
    total = 0
    for idx, doc in enumerate(request.documents):
        if len(doc) > RERANK_MAX_CANDIDATE_CHARS:
            raise HTTPException(
                status_code=413,
                detail=f"rerank document {idx} is {len(doc)} chars; max is {RERANK_MAX_CANDIDATE_CHARS}",
            )
        total += len(doc)
    if total > RERANK_MAX_TOTAL_CANDIDATE_CHARS:
        raise HTTPException(
            status_code=413,
            detail=f"rerank documents total {total} chars; max is {RERANK_MAX_TOTAL_CANDIDATE_CHARS}",
        )


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


def run_with_guard(
    operation: str,
    model: str,
    caller: str,
    input_chars: int,
    batch_size: int,
    candidate_count: int,
    fn,
) -> Any:
    labels = {"operation": operation, "model": model, "caller": caller}
    started = time.time()
    try:
        with guardrails[operation].slot() as wait_seconds:
            metrics.observe("web_osint_qwen_queue_wait_seconds", wait_seconds, labels)
            result = fn()
        metrics.inc("web_osint_qwen_requests_total", {**labels, "status": "ok"})
        return result
    except HTTPException as exc:
        metrics.inc("web_osint_qwen_requests_total", {**labels, "status": str(exc.status_code)})
        raise
    except Exception:
        metrics.inc("web_osint_qwen_requests_total", {**labels, "status": "error"})
        raise
    finally:
        elapsed = time.time() - started
        metrics.observe("web_osint_qwen_request_duration_seconds", elapsed, labels)
        metrics.observe("web_osint_qwen_input_chars", input_chars, labels)
        metrics.observe("web_osint_qwen_batch_size", batch_size, labels)
        if candidate_count:
            metrics.observe("web_osint_qwen_rerank_candidates", candidate_count, labels)


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {
        "ok": True,
        "device": DEVICE,
        "torch_threads": torch.get_num_threads(),
        "cpu_thread_guard": CPU_THREAD_GUARD,
        "model_paths": {
            "text": str(TEXT_MODEL_DIR),
            "reranker": str(RERANKER_MODEL_DIR),
            "vl": str(VL_MODEL_DIR),
            "vl_generative": str(VL_GENERATIVE_MODEL_DIR),
            "recaptcha_classifier": str(RECAPTCHA_MODEL_PATH),
        },
        "model_path_exists": {
            "text": TEXT_MODEL_DIR.exists(),
            "reranker": RERANKER_MODEL_DIR.exists(),
            "vl": VL_MODEL_DIR.exists(),
            "vl_generative": VL_GENERATIVE_MODEL_DIR.exists(),
            "recaptcha_classifier": RECAPTCHA_MODEL_PATH.exists(),
        },
        "loaded": registry.loaded(),
        "guardrails": {name: guard.snapshot() for name, guard in guardrails.items()},
        "metrics": metrics.snapshot(),
    }


@app.post("/warmup")
def warmup(request: WarmupRequest, http_request: Request) -> dict[str, Any]:
    warmed = []
    for name in request.models:
        selector = name.lower()
        if selector in {"text", "embedding"}:
            def do_text():
                model = registry.get_sentence_transformer("text", TEXT_MODEL_DIR)
                model.encode(["web osint warmup"], batch_size=1, normalize_embeddings=True)

            run_with_guard("embed", "Qwen3-Embedding-8B", caller_from(http_request), 16, 1, 0, do_text)
            warmed.append("text")
        elif selector in {"reranker", "rank"}:
            def do_rerank():
                model = registry.get_cross_encoder()
                model.predict([("web osint query", "web osint document")])

            run_with_guard("rerank", "Qwen3-Reranker-8B", caller_from(http_request), 33, 1, 1, do_rerank)
            warmed.append("reranker")
        elif selector in {"vl", "vl-image"}:
            def do_vl():
                model = registry.get_sentence_transformer("vl", VL_MODEL_DIR)
                model.encode(["web osint visual warmup"], batch_size=1, normalize_embeddings=True)

            run_with_guard("vl", "Qwen3-VL-Embedding-8B", caller_from(http_request), 24, 1, 0, do_vl)
            warmed.append("vl")
        elif selector in {"chat", "vl-generative", "vl-generate"}:
            def do_chat():
                model, processor = registry.get_vl_generative()
                # Tiny text-only generation to load weights + processor without
                # requiring an image file during warmup.
                prompt = processor.apply_chat_template(
                    [{"role": "user", "content": "Reply with the single word: OK"}],
                    add_generation_prompt=True,
                    tokenize=False,
                )
                inputs = processor(text=[prompt], return_tensors="pt").to(model.device)
                with torch.no_grad():
                    out = model.generate(**inputs, max_new_tokens=4, do_sample=False)
                processor.batch_decode(out, skip_special_tokens=True)

            run_with_guard("chat", "Qwen3-VL-Generative", caller_from(http_request), 48, 1, 0, do_chat)
            warmed.append("chat")
        elif selector in {"recaptcha", "recaptcha-classifier", "yolo"}:
            def do_recaptcha():
                model = registry.get_recaptcha_classifier()
                # Probe on a 1x1 transparent PNG generated in-memory so warmup
                # never depends on a real tile file being present.
                from PIL import Image

                probe = "/tmp/wop_recaptcha_warmup.png"
                Image.new("RGB", (64, 64), "gray").save(probe)
                model(probe, verbose=False)

            run_with_guard("recaptcha", "recaptcha-yolov8n-57k", caller_from(http_request), 8, 1, 0, do_recaptcha)
            warmed.append("recaptcha")
        elif selector in {"ocr", "ddddocr"}:
            def do_ocr():
                bundle = registry.get_ocr()
                # A tiny synthetic image with a couple of characters exercises
                # the CRNN path without depending on a real CAPTCHA file.
                from PIL import Image, ImageDraw

                img = Image.new("RGB", (80, 30), "white")
                ImageDraw.Draw(img).text((8, 6), "OK", fill="black")
                probe = "/tmp/wop_ocr_warmup.png"
                img.save(probe)
                bundle["ocr"].classification(open(probe, "rb").read())

            run_with_guard("ocr", "ddddocr", caller_from(http_request), 8, 1, 0, do_ocr)
            warmed.append("ocr")
        elif selector in {"slide", "slide-gap", "slider"}:
            def do_slide():
                bundle = registry.get_ocr()
                # Just instantiate the slide model; slide_match needs real input
                # images to be meaningful, so warmup only confirms it loaded.
                _ = bundle["slide"]

            run_with_guard("slide", "ddddocr-slide", caller_from(http_request), 8, 1, 0, do_slide)
            warmed.append("slide")
        else:
            raise HTTPException(status_code=400, detail=f"unknown warmup model: {name}")
    return {"ok": True, "warmed": warmed, "loaded": registry.loaded()}


@app.post("/embed")
def embed(request: EmbeddingRequest, http_request: Request) -> dict[str, Any]:
    if not request.inputs:
        raise HTTPException(status_code=400, detail="inputs must not be empty")
    validate_embedding_inputs(request.inputs)
    model, served_name = _embedding_model(request.model)
    batch_size = request.batch_size or DEFAULT_BATCH_SIZE
    operation = "vl" if served_name == "Qwen3-VL-Embedding-8B" else "embed"
    if request.prompt or request.prompt_name:
        operation = "vl" if operation == "vl" else "query_embed"
    elif operation == "embed" and is_batch_embedding_request(http_request):
        operation = "batch_embed"

    def run_encode() -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "batch_size": batch_size,
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

    return run_with_guard(
        operation,
        served_name,
        caller_from(http_request),
        input_char_count(request.inputs),
        batch_size,
        0,
        run_encode,
    )


@app.post("/v1/embeddings")
def openai_embeddings(request: OpenAIEmbeddingRequest, http_request: Request) -> dict[str, Any]:
    inputs = _as_list(request.input)
    response = embed(EmbeddingRequest(inputs=inputs, model=request.model or "text"), http_request)
    return {
        "object": "list",
        "model": response["model"],
        "data": [
            {"object": "embedding", "index": item["index"], "embedding": item["embedding"]}
            for item in response["data"]
        ],
        "usage": {"prompt_tokens": 0, "total_tokens": 0},
    }


@app.post("/v1/chat/completions")
def openai_chat_completions(request: ChatCompletionRequest, http_request: Request) -> dict[str, Any]:
    if not request.messages:
        raise HTTPException(status_code=400, detail="messages must not be empty")
    messages_text = sum(len(json_dumps_compact(m)) for m in request.messages)
    if messages_text > CHAT_MAX_INPUT_CHARS:
        raise HTTPException(
            status_code=413,
            detail=f"chat input is {messages_text} chars; max is {CHAT_MAX_INPUT_CHARS}",
        )
    image_path = request.image_path.strip() if request.image_path else None
    if image_path:
        image_path_obj = Path(image_path)
        if not image_path_obj.is_absolute():
            raise HTTPException(
                status_code=400,
                detail="image_path must be an absolute server-side filesystem path",
            )
        if not image_path_obj.exists():
            raise HTTPException(status_code=400, detail=f"image_path does not exist: {image_path}")
    max_new_tokens = min(request.max_tokens or CHAT_MAX_NEW_TOKENS, CHAT_MAX_NEW_TOKENS)

    def run_generate() -> dict[str, Any]:
        from PIL import Image

        model, processor = registry.get_vl_generative()
        content = []
        if image_path:
            content.append({"type": "image", "image": Image.open(image_path)})
        last_user_text = ""
        for msg in request.messages:
            if isinstance(msg.get("content"), str):
                last_user_text = msg["content"]
        if last_user_text and image_path:
            # Replace the last user message with a multimodal content block list.
            patched = []
            for msg in request.messages:
                if msg.get("role") == "user" and isinstance(msg.get("content"), str):
                    patched.append({**msg, "content": [*content, {"type": "text", "text": msg["content"]}]})
                else:
                    patched.append(msg)
            chat_messages = patched
        else:
            chat_messages = request.messages
        prompt = processor.apply_chat_template(
            chat_messages,
            add_generation_prompt=True,
            tokenize=False,
        )
        proc_kwargs: dict[str, Any] = {"text": [prompt], "return_tensors": "pt"}
        if image_path:
            proc_kwargs["images"] = Image.open(image_path)
        inputs = processor(**proc_kwargs).to(model.device)
        gen_kwargs: dict[str, Any] = {
            "max_new_tokens": max_new_tokens,
            "do_sample": False,
        }
        if request.temperature is not None:
            gen_kwargs["do_sample"] = True
            gen_kwargs["temperature"] = float(request.temperature)
        started = time.time()
        with torch.no_grad():
            out = model.generate(**inputs, **gen_kwargs)
        elapsed_ms = round((time.time() - started) * 1000, 2)
        # Trim prompt tokens so decoded text is only the model's response.
        input_len = inputs["input_ids"].shape[1]
        new_tokens = out[0, input_len:]
        text = processor.decode(new_tokens, skip_special_tokens=True).strip()
        completion_tokens = int(new_tokens.shape[0])
        return {
            "object": "chat.completion",
            "model": "Qwen3-VL-Generative",
            "elapsed_ms": elapsed_ms,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": int(input_len),
                "completion_tokens": completion_tokens,
                "total_tokens": int(input_len) + completion_tokens,
            },
        }

    caller = caller_from(http_request)
    return run_with_guard(
        "chat",
        "Qwen3-VL-Generative",
        caller,
        messages_text,
        1,
        0,
        run_generate,
    )


@app.post("/classify_recaptcha")
def classify_recaptcha(request: ClassifyRecaptchaRequest, http_request: Request) -> dict[str, Any]:
    if not request.image_paths:
        raise HTTPException(status_code=400, detail="image_paths must not be empty")
    for path in request.image_paths:
        p = Path(path)
        if not p.is_absolute():
            raise HTTPException(status_code=400, detail="image_paths must be absolute server-side paths")
        if not p.exists():
            raise HTTPException(status_code=400, detail=f"image_path does not exist: {path}")
    threshold = (
        request.confidence_threshold
        if request.confidence_threshold is not None
        else RECAPTCHA_CONFIDENCE_THRESHOLD
    )
    target = request.target.strip().lower() if request.target else None

    def run_classify() -> dict[str, Any]:
        model = registry.get_recaptcha_classifier()
        started = time.time()
        tiles = []
        for idx, path in enumerate(request.image_paths):
            results = model(path, verbose=False)
            probs = results[0].probs
            top1_idx = int(probs.top1)
            label = model.names[top1_idx]
            conf = float(probs.top1conf)
            is_other = label.lower() == "other"
            matches_target = (target is None) or (label.lower() == target)
            tiles.append(
                {
                    "index": idx,
                    "image_path": path,
                    "label": label,
                    "confidence": round(conf, 4),
                    "is_match": (not is_other) and matches_target and conf >= threshold,
                }
            )
        elapsed_ms = round((time.time() - started) * 1000, 2)
        return {
            "model": "recaptcha-yolov8n-57k",
            "target": target,
            "confidence_threshold": threshold,
            "elapsed_ms": elapsed_ms,
            "tiles": tiles,
            "matching_indexes": [t["index"] for t in tiles if t["is_match"]],
        }

    caller = caller_from(http_request)
    return run_with_guard(
        "recaptcha",
        "recaptcha-yolov8n-57k",
        caller,
        len(request.image_paths) * 32,
        len(request.image_paths),
        0,
        run_classify,
    )


@app.post("/ocr")
def ocr(request: OcrRequest, http_request: Request) -> dict[str, Any]:
    p = Path(request.image_path)
    if not p.is_absolute():
        raise HTTPException(status_code=400, detail="image_path must be an absolute server-side path")
    if not p.exists():
        raise HTTPException(status_code=400, detail=f"image_path does not exist: {request.image_path}")

    def run_ocr() -> dict[str, Any]:
        bundle = registry.get_ocr()
        docr = bundle["ocr"]
        with open(request.image_path, "rb") as fh:
            image_bytes = fh.read()
        started = time.time()
        text = docr.classification(image_bytes)
        elapsed_ms = round((time.time() - started) * 1000, 2)
        return {"model": "ddddocr", "text": text, "elapsed_ms": elapsed_ms}

    return run_with_guard(
        "ocr",
        "ddddocr",
        caller_from(http_request),
        32,
        1,
        0,
        run_ocr,
    )


@app.post("/slide_gap")
def slide_gap(request: SlideGapRequest, http_request: Request) -> dict[str, Any]:
    for label, path in (("bg_path", request.bg_path), ("slider_path", request.slider_path)):
        p = Path(path)
        if not p.is_absolute():
            raise HTTPException(status_code=400, detail=f"{label} must be an absolute server-side path")
        if not p.exists():
            raise HTTPException(status_code=400, detail=f"{label} does not exist: {path}")

    def run_slide() -> dict[str, Any]:
        bundle = registry.get_ocr()
        dslide = bundle["slide"]
        with open(request.bg_path, "rb") as fh:
            bg_bytes = fh.read()
        with open(request.slider_path, "rb") as fh:
            slider_bytes = fh.read()
        started = time.time()
        res = dslide.slide_match(slider_bytes, bg_bytes, simple_target=request.simple)
        elapsed_ms = round((time.time() - started) * 1000, 2)
        # ddddocr returns {"target_y": ..., "target": [x1, y1, x2, y2]} on success.
        target = res.get("target") if isinstance(res, dict) else None
        x = int(target[0]) if target and len(target) >= 2 else None
        y = int(target[1]) if target and len(target) >= 2 else None
        return {
            "model": "ddddocr-slide",
            "x": x,
            "y": y,
            "target_box": target,
            "elapsed_ms": elapsed_ms,
        }

    return run_with_guard(
        "slide",
        "ddddocr-slide",
        caller_from(http_request),
        32,
        1,
        0,
        run_slide,
    )


@app.post("/rerank")
def rerank(request: RerankRequest, http_request: Request) -> dict[str, Any]:
    if not request.query:
        raise HTTPException(status_code=400, detail="query must not be empty")
    if not request.documents:
        raise HTTPException(status_code=400, detail="documents must not be empty")
    caller = caller_from(http_request)
    input_chars = len(request.query) + sum(len(doc) for doc in request.documents)
    try:
        validate_rerank_request(request)
    except HTTPException as exc:
        labels = {"operation": "rerank", "model": "Qwen3-Reranker-8B", "caller": caller}
        metrics.inc("web_osint_qwen_requests_total", {**labels, "status": str(exc.status_code)})
        metrics.observe("web_osint_qwen_request_duration_seconds", 0.0, labels)
        metrics.observe("web_osint_qwen_input_chars", input_chars, labels)
        metrics.observe("web_osint_qwen_batch_size", len(request.documents), labels)
        metrics.observe("web_osint_qwen_rerank_candidates", len(request.documents), labels)
        raise

    def run_predict() -> dict[str, Any]:
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

    return run_with_guard(
        "rerank",
        "Qwen3-Reranker-8B",
        caller,
        input_chars,
        len(request.documents),
        len(request.documents),
        run_predict,
    )


@app.get("/metrics")
def prometheus_metrics() -> Response:
    return Response(metrics.prometheus(guardrails), media_type="text/plain; version=0.0.4")
