#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_TOPIC = "evidence.capture.events.v1"
DEFAULT_PANDAPROXY_URL = "http://127.0.0.1:18082"
DEFAULT_CHUNK_CHARS = 3600
SUPPORTED_SUFFIXES = {".md", ".markdown", ".txt"}
URL_RE = re.compile(r"https?://[^\s)>\]\"']+")


def now_slug() -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def stable_hash(value: bytes | str) -> str:
    data = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(data).hexdigest()


def slug(value: str) -> str:
    out = []
    prev = False
    for ch in value.lower():
        if ch.isalnum():
            out.append(ch)
            prev = False
        elif not prev:
            out.append("-")
            prev = True
    return "".join(out).strip("-") or "document"


def unique(values: list[str]) -> list[str]:
    seen = set()
    out = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def title_from_markdown(text: str, path: Path) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            if title:
                return title
    return path.stem.replace("_", " ").replace("-", " ").strip() or path.name


def discover_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            for child in sorted(path.rglob("*")):
                if child.is_file() and child.suffix.lower() in SUPPORTED_SUFFIXES:
                    files.append(child)
        elif path.is_file():
            files.append(path)
        else:
            raise FileNotFoundError(path)
    return sorted(dict.fromkeys(files))


def split_paragraphs(text: str) -> list[str]:
    paragraphs = re.split(r"\n\s*\n", text.strip())
    return [p.strip() for p in paragraphs if p.strip()]


def chunk_text(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text.strip()] if text.strip() else []

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for para in split_paragraphs(text):
        para_len = len(para) + 2
        if para_len > max_chars:
            prefix = "\n\n".join(current).strip()
            current = []
            current_len = 0
            first = True
            for idx in range(0, len(para), max_chars):
                part = para[idx : idx + max_chars].strip()
                if prefix and first:
                    available = max_chars - len(prefix) - 2
                    part = f"{prefix}\n\n{para[idx : idx + max(0, available)].strip()}".strip()
                    if available > 0:
                        next_idx = idx + available
                        remainder = para[next_idx : idx + max_chars].strip()
                        if remainder:
                            chunks.append(part)
                            part = remainder
                        else:
                            chunks.append(part)
                            part = ""
                    first = False
                if part:
                    chunks.append(part)
            continue
        if current and current_len + para_len > max_chars:
            chunks.append("\n\n".join(current).strip())
            current = []
            current_len = 0
        current.append(para)
        current_len += para_len
    if current:
        chunks.append("\n\n".join(current).strip())
    return merge_tiny_chunks(chunks, max_chars)


def merge_tiny_chunks(chunks: list[str], max_chars: int) -> list[str]:
    if len(chunks) < 2:
        return chunks
    merged: list[str] = []
    carry = ""
    for chunk in chunks:
        if carry:
            candidate = f"{carry}\n\n{chunk}"
            if len(candidate) <= max_chars:
                chunk = candidate
                carry = ""
            else:
                merged.append(carry)
                carry = ""
        if len(chunk) < 240:
            carry = chunk
            continue
        merged.append(chunk)
    if carry:
        if merged and len(merged[-1]) + len(carry) + 2 <= max_chars:
            merged[-1] = f"{merged[-1]}\n\n{carry}"
        else:
            merged.append(carry)
    return merged


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")


def relative_path(path: Path, root: Path | None) -> str:
    if root:
        try:
            return str(path.resolve().relative_to(root.resolve()))
        except ValueError:
            pass
    return path.name


def build_event(
    files: list[Path],
    *,
    source_root: Path | None,
    source_project: str,
    capture_method: str,
    collector_run_id: str,
    captured_at: str,
    chunk_chars: int,
    topics: list[str],
    entities: list[str],
) -> dict[str, Any]:
    user_inputs: list[dict[str, Any]] = []
    all_links: list[str] = []

    for path in files:
        text = read_text(path)
        raw = text.encode("utf-8", errors="replace")
        doc_hash = stable_hash(raw)
        rel = relative_path(path, source_root)
        title = title_from_markdown(text, path)
        links = unique(URL_RE.findall(text))
        all_links.extend(links)
        chunks = chunk_text(text, chunk_chars)
        stat = path.stat()
        document_id = f"research-doc-{slug(source_project)}-{doc_hash[:20]}"

        for idx, chunk in enumerate(chunks):
            chunk_hash = stable_hash(chunk)
            input_id = f"{document_id}-chunk-{idx + 1:04d}"
            chunk_title = title if len(chunks) == 1 else f"{title} ({idx + 1}/{len(chunks)})"
            user_inputs.append(
                {
                    "input_id": input_id,
                    "input_kind": "research_document_chunk",
                    "author": "user",
                    "title": chunk_title,
                    "text": chunk,
                    "canonical_url": f"local://research-documents/{source_project}/{rel}",
                    "links": links,
                    "topics": topics,
                    "entities": entities,
                    "context": {
                        "document_id": document_id,
                        "chunk_index": idx,
                        "chunk_count": len(chunks),
                        "source_relpath": rel,
                        "source_name": path.name,
                        "source_suffix": path.suffix.lower(),
                        "source_sha256": doc_hash,
                        "chunk_sha256": chunk_hash,
                        "source_size_bytes": stat.st_size,
                        "source_mtime_unix": int(stat.st_mtime),
                        "chunk_chars": len(chunk),
                    },
                    "quality": {
                        "user_supplied": True,
                        "manual_research_document": True,
                        "chunked": len(chunks) > 1,
                    },
                }
            )

    return {
        "schema_version": "v1",
        "collector_run_id": collector_run_id,
        "event_index": 0,
        "source_project": source_project,
        "capture_method": capture_method,
        "captured_at": captured_at,
        "page_url": f"local://research-documents/{source_project}",
        "page_title": f"Manual research documents: {source_project}",
        "context": {
            "source_root": str(source_root) if source_root else "",
            "document_count": len(files),
            "chunk_count": len(user_inputs),
            "chunk_chars": chunk_chars,
        },
        "posts": [],
        "accounts": [],
        "media": [],
        "search_results": [],
        "web_documents": [],
        "user_inputs": user_inputs,
        "links": unique(all_links),
        "quality": {
            "challenge": False,
            "login_prompt_visible": False,
            "partial": False,
            "user_supplied": True,
        },
    }


def post_event(pandaproxy_url: str, topic: str, event: dict[str, Any]) -> str:
    body = {"records": [{"key": f"{event['collector_run_id']}:{event['event_index']}", "value": event}]}
    req = urllib.request.Request(
        f"{pandaproxy_url.rstrip('/')}/topics/{topic}",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/vnd.kafka.json.v2+json",
            "Accept": "application/vnd.kafka.v2+json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return response.read().decode("utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Publish local research documents as Web OSINT user-input evidence.")
    parser.add_argument("paths", nargs="+", type=Path, help="Markdown/text files or directories to ingest.")
    parser.add_argument("--source-root", type=Path, help="Root used for stable relative paths.")
    parser.add_argument("--source-project", default="manual-research", help="Source project label.")
    parser.add_argument("--capture-method", default="manual_research_document_import")
    parser.add_argument("--collector-run-id", help="Defaults to research_docs_<source_project>_<timestamp>.")
    parser.add_argument("--captured-at", default=now_iso())
    parser.add_argument("--chunk-chars", type=int, default=DEFAULT_CHUNK_CHARS)
    parser.add_argument("--topic", default=DEFAULT_TOPIC)
    parser.add_argument("--pandaproxy-url", default=DEFAULT_PANDAPROXY_URL)
    parser.add_argument("--topic-label", action="append", default=[], help="Topic label to attach to every chunk.")
    parser.add_argument("--entity", action="append", default=[], help="Entity label to attach to every chunk.")
    parser.add_argument("--dry-run", action="store_true", help="Print the capture event instead of publishing.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.chunk_chars < 500:
        raise SystemExit("--chunk-chars must be at least 500")
    files = discover_files(args.paths)
    if not files:
        raise SystemExit("No supported research documents found.")
    run_id = args.collector_run_id or f"research_docs_{slug(args.source_project)}_{now_slug()}"
    event = build_event(
        files,
        source_root=args.source_root,
        source_project=args.source_project,
        capture_method=args.capture_method,
        collector_run_id=run_id,
        captured_at=args.captured_at,
        chunk_chars=args.chunk_chars,
        topics=args.topic_label,
        entities=args.entity,
    )
    if args.dry_run:
        print(json.dumps(event, ensure_ascii=False, indent=2))
        return 0
    response = post_event(args.pandaproxy_url, args.topic, event)
    print(
        json.dumps(
            {
                "ok": True,
                "collector_run_id": event["collector_run_id"],
                "documents": event["context"]["document_count"],
                "chunks": event["context"]["chunk_count"],
                "pandaproxy_response": json.loads(response) if response else {},
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
