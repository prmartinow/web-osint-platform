#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html import unescape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

try:
    from bs4 import BeautifulSoup
    from markdownify import markdownify as markdownify_html
    from readability import Document
except ImportError as exc:  # pragma: no cover - exercised by operator setup
    raise SystemExit(
        "Missing webpage extraction dependencies. Run scripts/init_webpage_extraction_venv.sh "
        "and then use that venv's python."
    ) from exc

try:
    from confluent_kafka import Consumer, KafkaError
except ImportError:  # pragma: no cover - extract-url mode can run without consumer support
    Consumer = None
    KafkaError = None


SCRIPT_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from osint_paths import ensure_dir, evidence_data_root, require_child_path  # noqa: E402


PRODUCER_NAME = "webpage-extraction-worker"
PRODUCER_VERSION = "v1"
CAPTURE_TOPIC = "evidence.capture.events.v1"
REQUEST_TOPIC = "osint.web.extraction.requested.v1"
FAILED_TOPIC = "osint.web.extraction.failed.v1"


def env(name: str, default: str) -> str:
    return os.environ.get(name, default)


DATA_ROOT = evidence_data_root()
WEB_ROOT = ensure_dir(DATA_ROOT / "web")
KAFKA_BROKERS = env("KAFKA_BROKERS", env("REDPANDA_BROKERS", ""))
KAFKA_GROUP_ID = env("WEBPAGE_EXTRACTION_GROUP_ID", "web-osint-webpage-extraction-v1")
PANDAPROXY_URL = env("PANDAPROXY_URL", env("REDPANDA_PROXY_URL", "")).rstrip("/")
HTTP_ADDR = env("WEBPAGE_EXTRACTION_HTTP_ADDR", ":18221")
REQUEST_TIMEOUT = float(env("WEBPAGE_EXTRACTION_REQUEST_TIMEOUT", "45"))
MAX_HTML_BYTES = int(env("WEBPAGE_EXTRACTION_MAX_HTML_BYTES", str(8 * 1024 * 1024)))
MAX_TEXT_CHARS = int(env("WEBPAGE_EXTRACTION_MAX_TEXT_CHARS", "120000"))
MAX_LINKS = int(env("WEBPAGE_EXTRACTION_MAX_LINKS", "500"))
MAX_TABLES = int(env("WEBPAGE_EXTRACTION_MAX_TABLES", "40"))
MAX_TABLE_ROWS = int(env("WEBPAGE_EXTRACTION_MAX_TABLE_ROWS", "200"))
MAX_EVIDENCE_BLOCKS = int(env("WEBPAGE_EXTRACTION_MAX_EVIDENCE_BLOCKS", "800"))
USER_AGENT = env(
    "WEBPAGE_EXTRACTION_USER_AGENT",
    "Mozilla/5.0 (compatible; WebOSINTBot/1.0; +https://example.invalid/web-osint)",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def stable_hash(*parts: Any) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(str(part or "").encode("utf-8", errors="replace"))
        h.update(b"\x00")
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def clean_ws(text: Any) -> str:
    raw = unescape(str(text or ""))
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    raw = re.sub(r"[ \t\f\v]+", " ", raw)
    raw = re.sub(r"\n[ \t]+", "\n", raw)
    raw = re.sub(r"\n{3,}", "\n\n", raw)
    return raw.strip()


def truncate_text(text: str, limit: int = MAX_TEXT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip()


def normalize_url(url: str, base: str | None = None) -> str:
    joined = urllib.parse.urljoin(base or "", str(url or "").strip())
    if not joined:
        return ""
    parsed = urllib.parse.urlsplit(joined)
    scheme = parsed.scheme.lower() or "https"
    netloc = parsed.netloc.lower()
    path = parsed.path or "/"
    return urllib.parse.urlunsplit((scheme, netloc, path, parsed.query, ""))


def domain_of(url: str) -> str:
    try:
        return urllib.parse.urlsplit(url).hostname or ""
    except Exception:
        return ""


def artifact_path(kind: str, digest: str, suffix: str) -> Path:
    path = WEB_ROOT / kind / digest[:2] / digest[2:4] / f"{digest}.{suffix}"
    require_child_path(DATA_ROOT, path)
    ensure_dir(path.parent)
    return path


def write_text_artifact(kind: str, digest: str, suffix: str, text: str) -> str:
    path = artifact_path(kind, digest, suffix)
    path.write_text(text, encoding="utf-8")
    return str(path)


def write_bytes_artifact(kind: str, digest: str, suffix: str, data: bytes) -> str:
    path = artifact_path(kind, digest, suffix)
    path.write_bytes(data)
    return str(path)


def write_json_artifact(kind: str, digest: str, value: Any) -> str:
    return write_text_artifact(kind, digest, "json", json.dumps(value, ensure_ascii=False, indent=2, default=str))


def fetch_url(url: str, *, timeout: float = REQUEST_TIMEOUT, max_bytes: int = MAX_HTML_BYTES) -> tuple[str, bytes, dict[str, str], int]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise RuntimeError(f"response exceeded WEBPAGE_EXTRACTION_MAX_HTML_BYTES={max_bytes}")
            headers = {k.lower(): v for k, v in response.headers.items()}
            return response.geturl(), data, headers, int(getattr(response, "status", 200))
    except urllib.error.HTTPError as exc:
        body = exc.read(2000).decode("utf-8", errors="replace")
        raise RuntimeError(f"GET {url} returned HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"GET {url} failed: {exc}") from exc


def decode_html(raw: bytes, headers: dict[str, str]) -> tuple[str, str]:
    content_type = headers.get("content-type", "")
    charset = ""
    match = re.search(r"charset=([^;\s]+)", content_type, flags=re.I)
    if match:
        charset = match.group(1).strip("\"'")
    for candidate in [charset, "utf-8", "windows-1252"]:
        if not candidate:
            continue
        try:
            return raw.decode(candidate), candidate
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8-replace"


def meta_content(soup: BeautifulSoup, *keys: str) -> str:
    wanted = {k.lower() for k in keys}
    for tag in soup.find_all("meta"):
        name = str(tag.get("name") or tag.get("property") or tag.get("itemprop") or "").lower()
        if name in wanted:
            value = clean_ws(tag.get("content"))
            if value:
                return value
    return ""


def extract_json_ld(soup: BeautifulSoup) -> list[Any]:
    out: list[Any] = []
    for script in soup.find_all("script", {"type": re.compile(r"ld\+json", re.I)}):
        text = script.string or script.get_text(" ", strip=True)
        if not text:
            continue
        with contextlib.suppress(Exception):
            out.append(json.loads(text))
    return out[:20]


def extract_published_at(soup: BeautifulSoup, json_ld: list[Any]) -> str | None:
    direct = meta_content(
        soup,
        "article:published_time",
        "datePublished",
        "date",
        "pubdate",
        "publishdate",
        "sailthru.date",
    )
    if direct:
        return direct

    def walk(value: Any) -> str | None:
        if isinstance(value, dict):
            for key in ["datePublished", "dateCreated", "uploadDate"]:
                if value.get(key):
                    return str(value[key])
            for child in value.values():
                found = walk(child)
                if found:
                    return found
        if isinstance(value, list):
            for child in value:
                found = walk(child)
                if found:
                    return found
        return None

    return walk(json_ld)


def extract_links(soup: BeautifulSoup, base_url: str) -> list[str]:
    links: list[str] = []
    seen: set[str] = set()
    for tag in soup.find_all("a", href=True):
        href = normalize_url(tag.get("href", ""), base=base_url)
        if not href or href in seen:
            continue
        parsed = urllib.parse.urlsplit(href)
        if parsed.scheme not in {"http", "https"}:
            continue
        seen.add(href)
        links.append(href)
        if len(links) >= MAX_LINKS:
            break
    return links


def extract_images(soup: BeautifulSoup, base_url: str) -> list[dict[str, str]]:
    images: list[dict[str, str]] = []
    seen: set[str] = set()
    for tag in soup.find_all("img"):
        src = tag.get("src") or tag.get("data-src") or tag.get("data-original")
        url = normalize_url(src or "", base=base_url)
        if not url or url in seen:
            continue
        seen.add(url)
        images.append(
            {
                "url": url,
                "alt": clean_ws(tag.get("alt")),
                "title": clean_ws(tag.get("title")),
            }
        )
        if len(images) >= 200:
            break
    return images


def extract_headings(soup: BeautifulSoup) -> list[dict[str, str]]:
    headings: list[dict[str, str]] = []
    for tag in soup.find_all(re.compile(r"^h[1-6]$")):
        text = clean_ws(tag.get_text(" ", strip=True))
        if text:
            headings.append({"level": tag.name, "text": text})
        if len(headings) >= 200:
            break
    return headings


def extract_tables(soup: BeautifulSoup) -> list[dict[str, Any]]:
    tables: list[dict[str, Any]] = []
    for table_index, table in enumerate(soup.find_all("table")[:MAX_TABLES]):
        caption = clean_ws(table.caption.get_text(" ", strip=True)) if table.caption else ""
        rows: list[list[str]] = []
        for tr in table.find_all("tr")[:MAX_TABLE_ROWS]:
            cells = [clean_ws(cell.get_text(" ", strip=True)) for cell in tr.find_all(["th", "td"])]
            if any(cells):
                rows.append(cells)
        if rows:
            tables.append(
                {
                    "table_index": table_index,
                    "caption": caption,
                    "row_count": len(rows),
                    "column_count": max(len(r) for r in rows),
                    "rows": rows,
                }
            )
    return tables


def soup_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "svg", "template", "form"]):
        tag.decompose()
    return clean_ws(soup.get_text("\n", strip=True))


def extract_main(html: str) -> tuple[str, str, str]:
    try:
        doc = Document(html)
        summary_html = doc.summary(html_partial=True)
        title = clean_ws(doc.short_title())
        text = soup_text(summary_html)
        if len(text) >= 200:
            markdown = clean_ws(markdownify_html(summary_html, heading_style="ATX"))
            return text, markdown, title
    except Exception:
        pass

    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "svg", "template", "form"]):
        tag.decompose()
    main = soup.find("article") or soup.find("main") or soup.body or soup
    text = clean_ws(main.get_text("\n", strip=True))
    markdown = clean_ws(markdownify_html(str(main), heading_style="ATX"))
    return text, markdown, ""


def split_text_blocks(text: str) -> list[str]:
    pieces = [clean_ws(piece) for piece in re.split(r"\n\s*\n", text or "")]
    pieces = [piece for piece in pieces if piece]
    if len(pieces) <= 3:
        line_pieces = [clean_ws(line) for line in str(text or "").splitlines()]
        pieces = [piece for piece in line_pieces if piece]
    blocks: list[str] = []
    for piece in pieces:
        if len(piece) <= 1800:
            blocks.append(piece)
            continue
        for idx in range(0, len(piece), 1400):
            chunk = clean_ws(piece[idx:idx + 1400])
            if chunk:
                blocks.append(chunk)
    return blocks[:MAX_EVIDENCE_BLOCKS]


def text_anchor(text: str, index: int, source: str = "readability_text") -> dict[str, Any]:
    exact = clean_ws(text)[:320]
    return {
        "selector_type": "text_quote",
        "source": source,
        "index": index,
        "exact": exact,
        "prefix": "",
        "suffix": "",
    }


def order_anchor(index: int, source: str) -> dict[str, Any]:
    return {"selector_type": "extracted_order", "source": source, "index": index}


def build_evidence_document(
    *,
    document_id: str,
    source_url: str,
    final_url: str,
    canonical_url: str,
    title: str,
    description: str,
    domain: str,
    fetched_at: str,
    capture_method: str,
    collector_run_id: str,
    event_index: int,
    status: int,
    content_type: str,
    published_at: str | None,
    html_sha: str,
    text_sha: str,
    extracted_text: str,
    markdown: str,
    headings: list[dict[str, str]],
    tables: list[dict[str, Any]],
    images: list[dict[str, str]],
    artifact_paths: list[str],
    json_ld_count: int,
    topics: list[str],
    context: dict[str, Any] | None,
) -> dict[str, Any]:
    blocks: list[dict[str, Any]] = []
    if title:
        blocks.append({
            "block_id": f"{document_id}:title:0",
            "type": "title",
            "text": title,
            "anchor": order_anchor(0, "metadata_title"),
            "metadata": {"role": "document_title"},
        })
    if description:
        blocks.append({
            "block_id": f"{document_id}:description:0",
            "type": "summary",
            "text": description,
            "anchor": order_anchor(0, "metadata_description"),
            "metadata": {"role": "meta_description"},
        })
    for idx, heading in enumerate(headings[:200]):
        text = clean_ws(heading.get("text"))
        if not text:
            continue
        blocks.append({
            "block_id": f"{document_id}:heading:{idx}",
            "type": "heading",
            "text": text,
            "level": heading.get("level"),
            "anchor": text_anchor(text, idx, "dom_heading"),
            "metadata": {},
        })
    for idx, paragraph in enumerate(split_text_blocks(extracted_text)):
        blocks.append({
            "block_id": f"{document_id}:text:{idx}",
            "type": "paragraph",
            "text": paragraph,
            "anchor": text_anchor(paragraph, idx),
            "metadata": {"source_representation": "readability_or_dom_text"},
        })
    for table in tables:
        table_index = int(table.get("table_index") or 0)
        blocks.append({
            "block_id": f"{document_id}:table:{table_index}",
            "type": "table",
            "text": clean_ws(table.get("caption")) or f"Table {table_index + 1}",
            "rows": table.get("rows") or [],
            "anchor": order_anchor(table_index, "dom_table"),
            "metadata": {
                "caption": table.get("caption") or "",
                "row_count": table.get("row_count") or 0,
                "column_count": table.get("column_count") or 0,
            },
        })
    blocks = blocks[:MAX_EVIDENCE_BLOCKS]

    assets = []
    for idx, image in enumerate(images):
        assets.append({
            "asset_id": f"{document_id}:image:{idx}",
            "type": "image",
            "url": image.get("url") or "",
            "alt": image.get("alt") or "",
            "title": image.get("title") or "",
            "anchor": order_anchor(idx, "dom_image"),
            "metadata": {},
        })

    omitted = []
    if len(extracted_text) > MAX_TEXT_CHARS:
        omitted.append({
            "kind": "text_tail",
            "reason": "capture_event_text_truncated",
            "available_in_artifact": "text",
            "omitted_chars": len(extracted_text) - MAX_TEXT_CHARS,
        })
    if len(markdown) > MAX_TEXT_CHARS:
        omitted.append({
            "kind": "markdown_tail",
            "reason": "capture_event_markdown_truncated",
            "available_in_artifact": "markdown",
            "omitted_chars": len(markdown) - MAX_TEXT_CHARS,
        })

    return {
        "schema_version": "v1",
        "document_id": document_id,
        "created_at": fetched_at,
        "source": {
            "source_kind": "web_page",
            "source_url": source_url,
            "final_url": final_url,
            "canonical_url": canonical_url,
            "domain": domain,
            "title": title,
            "description": description,
            "published_at": published_at,
            "topics": topics,
        },
        "captures": [
            {
                "capture_id": f"{collector_run_id}:{event_index}",
                "collector_run_id": collector_run_id,
                "event_index": event_index,
                "capture_method": capture_method,
                "captured_at": fetched_at,
                "http_status": status,
                "content_type": content_type,
                "html_sha256": html_sha,
                "text_sha256": text_sha,
                "artifacts": artifact_paths,
                "context": context or {},
            }
        ],
        "revision": {
            "revision_id": stable_hash(document_id, text_sha, PRODUCER_NAME, PRODUCER_VERSION)[:24],
            "producer": {"name": PRODUCER_NAME, "version": PRODUCER_VERSION},
            "generated_at": fetched_at,
            "extraction_methods": ["http_fetch", "readability", "dom_fallback", "markdownify"],
            "quality": {
                "text_chars": len(extracted_text),
                "markdown_chars": len(markdown),
                "block_count": len(blocks),
                "asset_count": len(assets),
                "table_count": len(tables),
                "json_ld_count": json_ld_count,
                "needs_rebrowser_rendered_capture": len(clean_ws(extracted_text)) < 80,
            },
        },
        "blocks": blocks,
        "assets": assets,
        "omitted_content": omitted,
        "projections": {
            "raw_html": next((p for p in artifact_paths if "/html/" in p), ""),
            "text": next((p for p in artifact_paths if "/text/" in p), ""),
            "markdown": next((p for p in artifact_paths if "/markdown/" in p), ""),
            "tables_json": next((p for p in artifact_paths if "/tables/" in p), ""),
            "metadata_json": next((p for p in artifact_paths if "/metadata/" in p), ""),
        },
    }


@dataclass
class ExtractedPage:
    url: str
    final_url: str
    canonical_url: str
    title: str
    document_id: str
    text: str
    capture_event: dict[str, Any]
    artifact_paths: list[str]


def extract_page(
    url: str,
    *,
    source_project: str,
    collector_run_id: str,
    event_index: int,
    topics: list[str],
    capture_method: str = PRODUCER_NAME,
    context: dict[str, Any] | None = None,
) -> ExtractedPage:
    final_url, raw, headers, status = fetch_url(url)
    fetched_at = now_iso()
    html, encoding = decode_html(raw, headers)
    html_sha = sha256_bytes(raw)

    soup = BeautifulSoup(html, "lxml")
    json_ld = extract_json_ld(soup)
    canonical = ""
    canonical_tag = soup.find("link", rel=lambda value: value and "canonical" in [str(v).lower() for v in (value if isinstance(value, list) else [value])])
    if canonical_tag:
        canonical = normalize_url(canonical_tag.get("href", ""), base=final_url)
    canonical_url = canonical or normalize_url(final_url or url)

    extracted_text, markdown, readability_title = extract_main(html)
    title = (
        meta_content(soup, "og:title", "twitter:title")
        or readability_title
        or clean_ws(soup.title.string if soup.title else "")
        or clean_ws((soup.find("h1") or {}).get_text(" ", strip=True) if soup.find("h1") else "")
    )
    description = meta_content(soup, "description", "og:description", "twitter:description")
    headings = extract_headings(soup)
    links = extract_links(soup, canonical_url)
    images = extract_images(soup, canonical_url)
    tables = extract_tables(soup)
    text = truncate_text(extracted_text)
    markdown_for_event = truncate_text(markdown)
    text_sha = stable_hash(extracted_text)
    document_id = stable_hash(canonical_url, text_sha)[:24]

    artifact_paths = [
        write_bytes_artifact("html", html_sha, "html", raw),
        write_text_artifact("text", text_sha, "txt", extracted_text),
        write_text_artifact("markdown", text_sha, "md", markdown),
    ]
    tables_path = write_text_artifact("tables", text_sha, "json", json.dumps(tables, ensure_ascii=False, indent=2))
    meta = {
        "url": url,
        "final_url": final_url,
        "canonical_url": canonical_url,
        "status": status,
        "content_type": headers.get("content-type", ""),
        "encoding": encoding,
        "title": title,
        "description": description,
        "published_at": extract_published_at(soup, json_ld),
        "headings": headings,
        "images": images,
        "json_ld": json_ld,
        "producer": {"name": PRODUCER_NAME, "version": PRODUCER_VERSION},
    }
    meta_path = write_text_artifact("metadata", text_sha, "json", json.dumps(meta, ensure_ascii=False, indent=2))
    artifact_paths.extend([tables_path, meta_path])
    evidence_document = build_evidence_document(
        document_id=document_id,
        source_url=url,
        final_url=final_url,
        canonical_url=canonical_url,
        title=title,
        description=description,
        domain=domain_of(canonical_url),
        fetched_at=fetched_at,
        capture_method=capture_method,
        collector_run_id=collector_run_id,
        event_index=event_index,
        status=status,
        content_type=headers.get("content-type", ""),
        published_at=meta["published_at"],
        html_sha=html_sha,
        text_sha=text_sha,
        extracted_text=extracted_text,
        markdown=markdown,
        headings=headings,
        tables=tables,
        images=images,
        artifact_paths=artifact_paths,
        json_ld_count=len(json_ld),
        topics=topics,
        context=context,
    )
    evidence_document_path = write_json_artifact("evidence_document", text_sha, evidence_document)
    artifact_paths.append(evidence_document_path)
    evidence_document["captures"][0]["artifacts"] = artifact_paths
    evidence_document["projections"]["evidence_document"] = evidence_document_path
    write_json_artifact("evidence_document", text_sha, evidence_document)

    document = {
        "schema_version": "v1",
        "document_id": document_id,
        "evidence_document_id": evidence_document["document_id"],
        "evidence_document_path": evidence_document_path,
        "canonical_url": canonical_url,
        "domain": domain_of(canonical_url),
        "title": title,
        "text": text,
        "markdown": markdown_for_event,
        "text_hash": text_sha,
        "content_type": headers.get("content-type", ""),
        "document_kind": "web_page",
        "published_at": meta["published_at"],
        "retrieved_at": fetched_at,
        "extracted_at": fetched_at,
        "links": links,
        "media": images,
        "media_ids": [],
        "topics": topics,
        "entities": [],
        "artifact_paths": artifact_paths,
        "tables": tables,
        "quality": {
            "status_code": status,
            "html_sha256": html_sha,
            "text_sha256": text_sha,
            "text_chars": len(extracted_text),
            "event_text_chars": len(text),
            "markdown_chars": len(markdown),
            "event_markdown_chars": len(markdown_for_event),
            "evidence_document_blocks": len(evidence_document["blocks"]),
            "evidence_document_assets": len(evidence_document["assets"]),
            "needs_rebrowser_rendered_capture": evidence_document["revision"]["quality"]["needs_rebrowser_rendered_capture"],
            "link_count": len(links),
            "image_count": len(images),
            "table_count": len(tables),
            "heading_count": len(headings),
            "extraction_method": "readability_then_dom_fallback",
            "truncated": len(extracted_text) > len(text),
            "markdown_truncated": len(markdown) > len(markdown_for_event),
        },
        "raw": {
            "source_url": url,
            "final_url": final_url,
            "description": description,
            "headings": headings,
            "images": images,
            "json_ld_count": len(json_ld),
        },
        "content_representations": {
            "canonical_evidence_document": evidence_document_path,
            "raw_html": evidence_document["projections"]["raw_html"],
            "text": evidence_document["projections"]["text"],
            "markdown": evidence_document["projections"]["markdown"],
            "tables_json": evidence_document["projections"]["tables_json"],
            "metadata_json": evidence_document["projections"]["metadata_json"],
        },
        "capture_bundle": {
            "source_url": url,
            "final_url": final_url,
            "capture_method": capture_method,
            "rendered_browser_surface": "rebrowser",
            "static_extraction_method": "http_fetch_readability_dom",
            "rendered_capture_required": evidence_document["revision"]["quality"]["needs_rebrowser_rendered_capture"],
        },
    }
    capture_event = {
        "schema_version": "v1",
        "collector_run_id": collector_run_id,
        "event_index": event_index,
        "source_project": source_project,
        "capture_method": capture_method,
        "captured_at": fetched_at,
        "page_url": canonical_url,
        "page_title": title,
        "context": {
            **(context or {}),
            "requested_url": url,
            "final_url": final_url,
            "producer": {"name": PRODUCER_NAME, "version": PRODUCER_VERSION},
        },
        "posts": [],
        "accounts": [],
        "media": [],
        "web_documents": [document],
        "user_inputs": [],
        "links": links,
        "quality": {
            "challenge": False,
            "partial": False,
            "status_code": status,
            "content_type": headers.get("content-type", ""),
            "html_sha256": html_sha,
            "text_sha256": text_sha,
        },
    }
    return ExtractedPage(
        url=url,
        final_url=final_url,
        canonical_url=canonical_url,
        title=title,
        document_id=document_id,
        text=text,
        capture_event=capture_event,
        artifact_paths=artifact_paths,
    )


def post_json_record(topic: str, key: str, value: dict[str, Any], *, pandaproxy_url: str = PANDAPROXY_URL) -> str:
    body = {
        "records": [
            {
                "key": key,
                "value": value,
            }
        ]
    }
    request = urllib.request.Request(
        f"{pandaproxy_url}/topics/{topic}",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/vnd.kafka.json.v2+json",
            "Accept": "application/vnd.kafka.v2+json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:2000]
        raise RuntimeError(f"Pandaproxy publish failed HTTP {exc.code}: {detail}") from exc


def post_capture_event(event: dict[str, Any], *, topic: str = CAPTURE_TOPIC, pandaproxy_url: str = PANDAPROXY_URL) -> str:
    return post_json_record(
        topic,
        f"{event['collector_run_id']}:{event['event_index']}",
        event,
        pandaproxy_url=pandaproxy_url,
    )


def post_failure_event(request_payload: dict[str, Any], error: str, *, pandaproxy_url: str = PANDAPROXY_URL) -> None:
    key = stable_hash(request_payload.get("url"), request_payload.get("collector_run_id"), error, now_iso())[:24]
    failure = {
        "schema_version": "v1",
        "failed_at": now_iso(),
        "producer": {"name": PRODUCER_NAME, "version": PRODUCER_VERSION},
        "request": request_payload,
        "error": error,
    }
    post_json_record(FAILED_TOPIC, key, failure, pandaproxy_url=pandaproxy_url)


@dataclass
class WorkerStats:
    started_at: str = field(default_factory=now_iso)
    consumed: int = 0
    extracted: int = 0
    published: int = 0
    failed: int = 0
    last_event: dict[str, Any] | None = None
    last_error: str = ""
    lock: threading.Lock = field(default_factory=threading.Lock)

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "ok": True,
                "started_at": self.started_at,
                "consumed": self.consumed,
                "extracted": self.extracted,
                "published": self.published,
                "failed": self.failed,
                "last_event": self.last_event,
                "last_error": self.last_error,
                "request_topic": REQUEST_TOPIC,
                "capture_topic": CAPTURE_TOPIC,
                "data_root": str(DATA_ROOT),
                "web_root": str(WEB_ROOT),
            }

    def incr(self, field_name: str, amount: int = 1) -> None:
        with self.lock:
            setattr(self, field_name, getattr(self, field_name) + amount)

    def event(self, event: dict[str, Any]) -> None:
        with self.lock:
            self.last_event = event

    def error(self, message: str) -> None:
        with self.lock:
            self.last_error = message


stats = WorkerStats()


class StatsHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        if self.path not in {"/", "/healthz", "/stats"}:
            self.send_response(404)
            self.end_headers()
            return
        payload = stats.snapshot()
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start_stats_server(addr: str) -> ThreadingHTTPServer:
    host, port_text = addr.rsplit(":", 1)
    server = ThreadingHTTPServer((host, int(port_text)), StatsHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def request_to_page(message: dict[str, Any], fallback_index: int) -> ExtractedPage:
    url = str(message.get("url") or message.get("canonical_url") or "").strip()
    if not url:
        raise ValueError("web extraction request is missing url")
    collector_run_id = str(message.get("collector_run_id") or f"webpage_extraction_{stable_hash(url, now_iso())[:12]}")
    source_project = str(message.get("source_project") or "webpage-extraction")
    event_index = int(message.get("event_index") or fallback_index)
    topics = message.get("topics") if isinstance(message.get("topics"), list) else []
    return extract_page(
        url,
        source_project=source_project,
        collector_run_id=collector_run_id,
        event_index=event_index,
        topics=[str(t) for t in topics],
        capture_method=str(message.get("capture_method") or PRODUCER_NAME),
        context=message.get("context") if isinstance(message.get("context"), dict) else {},
    )


def run_consumer() -> None:
    if Consumer is None:
        raise SystemExit("confluent-kafka is required for run mode. Run scripts/init_webpage_extraction_venv.sh.")
    if not KAFKA_BROKERS:
        raise SystemExit("Missing KAFKA_BROKERS or REDPANDA_BROKERS")
    if not PANDAPROXY_URL:
        raise SystemExit("Missing PANDAPROXY_URL or REDPANDA_PROXY_URL")
    start_stats_server(HTTP_ADDR)
    consumer = Consumer(
        {
            "bootstrap.servers": KAFKA_BROKERS,
            "group.id": KAFKA_GROUP_ID,
            "enable.auto.commit": False,
            "auto.offset.reset": "earliest",
        }
    )
    consumer.subscribe([REQUEST_TOPIC])
    fallback_index = 0
    try:
        while True:
            msg = consumer.poll(1.0)
            if msg is None:
                continue
            if msg.error():
                if KafkaError is not None and msg.error().code() == KafkaError._PARTITION_EOF:
                    continue
                stats.incr("failed")
                stats.error(str(msg.error()))
                continue
            stats.incr("consumed")
            fallback_index += 1
            request_payload: dict[str, Any] = {}
            try:
                request_payload = json.loads(msg.value().decode("utf-8"))
                page = request_to_page(request_payload, fallback_index)
                stats.incr("extracted")
                response = post_capture_event(page.capture_event)
                stats.incr("published")
                stats.event(
                    {
                        "url": page.url,
                        "canonical_url": page.canonical_url,
                        "document_id": page.document_id,
                        "title": page.title,
                        "pandaproxy_response": response,
                    }
                )
                consumer.commit(msg)
            except Exception as exc:
                stats.incr("failed")
                stats.error(str(exc))
                with contextlib.suppress(Exception):
                    post_failure_event(request_payload, str(exc))
                print(f"[{now_iso()}] failed request: {exc}", file=sys.stderr, flush=True)
    finally:
        consumer.close()


def collect_urls(args: argparse.Namespace) -> list[str]:
    urls: list[str] = []
    for url in args.url or []:
        if url.strip():
            urls.append(url.strip())
    if args.urls_file:
        for raw in Path(args.urls_file).read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if line and not line.startswith("#"):
                urls.append(line)
    return urls


def cmd_extract_url(args: argparse.Namespace) -> None:
    urls = collect_urls(args)
    if not urls:
        raise SystemExit("provide at least one --url or --urls-file")
    if args.publish and not args.pandaproxy_url:
        raise SystemExit("Missing PANDAPROXY_URL, REDPANDA_PROXY_URL, or --pandaproxy-url")
    collector_run_id = args.collector_run_id or f"webpage_extract_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{stable_hash(*urls)[:8]}"
    results = []
    for offset, url in enumerate(urls):
        page = extract_page(
            url,
            source_project=args.source_project,
            collector_run_id=collector_run_id,
            event_index=args.event_index_start + offset,
            topics=args.topic_label or [],
            capture_method=args.capture_method,
            context={"canary": bool(args.canary), "operator": "manual_extract_url"},
        )
        item = {
            "url": page.url,
            "canonical_url": page.canonical_url,
            "document_id": page.document_id,
            "title": page.title,
            "text_chars": len(page.text),
            "artifact_paths": page.artifact_paths,
            "evidence_document_paths": [path for path in page.artifact_paths if "/evidence_document/" in path],
        }
        if args.publish:
            item["pandaproxy_response"] = post_capture_event(page.capture_event, pandaproxy_url=args.pandaproxy_url)
        else:
            item["capture_event"] = page.capture_event
        results.append(item)
    print(json.dumps({"collector_run_id": collector_run_id, "published": bool(args.publish), "results": results}, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract HTML webpages into Web OSINT capture events.")
    sub = parser.add_subparsers(dest="command", required=True)

    one = sub.add_parser("extract-url", help="Fetch/extract URL(s), optionally publishing capture events.")
    one.add_argument("--url", action="append", help="URL to extract. Repeatable.")
    one.add_argument("--urls-file", help="File containing one URL per line.")
    one.add_argument("--source-project", default="webpage-extraction")
    one.add_argument("--capture-method", default=PRODUCER_NAME)
    one.add_argument("--collector-run-id")
    one.add_argument("--event-index-start", type=int, default=0)
    one.add_argument("--topic-label", action="append", default=[])
    one.add_argument("--pandaproxy-url", default=PANDAPROXY_URL)
    one.add_argument("--publish", action="store_true", help="Publish capture events to Redpanda through Pandaproxy.")
    one.add_argument("--canary", action="store_true")
    one.set_defaults(func=cmd_extract_url)

    run = sub.add_parser("run", help="Run continuous request-topic consumer.")
    run.set_defaults(func=lambda _args: run_consumer())
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
