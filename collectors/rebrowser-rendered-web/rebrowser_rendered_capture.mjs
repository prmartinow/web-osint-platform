#!/usr/bin/env node
import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { spawnSync } from "node:child_process";

const PRODUCER_NAME = "rebrowser-rendered-web-capture";
const PRODUCER_VERSION = "v1";
const MAX_EVENT_TEXT_CHARS = 120_000;
const MAX_BLOCKS = 600;
const MAX_ASSETS = 300;
const DEFAULT_CDP_URL = process.env.REBROWSER_CDP_URL || "";
const DEFAULT_RPC_HOST = process.env.WEB_OSINT_RPC_SSH_HOST || "";
const DEFAULT_RPC_PORT = process.env.WEB_OSINT_RPC_SSH_PORT || "";
const DEFAULT_RPC_DATA_ROOT = process.env.WEB_OSINT_RPC_DATA_ROOT || process.env.WEB_OSINT_DATA_ROOT || "";
const DEFAULT_REMOTE_PANDAPROXY = process.env.WEB_OSINT_REMOTE_PANDAPROXY_URL || process.env.PANDAPROXY_URL || process.env.REDPANDA_PROXY_URL || "";
const TOPIC = "evidence.capture.events.v1";

function usage() {
  console.log(`Usage:
  node collectors/rebrowser-rendered-web/rebrowser_rendered_capture.mjs --url URL [options]

Options:
  --url URL                         Page URL to capture.
  --source-project NAME             Source project label. Default: rendered-web
  --collector-run-id ID             Collector run id. Default generated.
  --event-index N                   Capture event index. Default: 0
  --topic-label LABEL               Repeatable topic label.
  --context-json JSON               Optional context object JSON.
  --cdp-url URL                     Rebrowser CDP URL. Default: REBROWSER_CDP_URL.
  --settle-ms N                     Post-load wait. Default: 2500
  --timeout-ms N                    Navigation timeout. Default: 60000
  --scroll / --no-scroll            Slow-scroll page before capture. Default: --scroll
  --publish                         Upload artifacts and publish to RPC Redpanda.
  --rpc-host HOST                   SSH host. Default: WEB_OSINT_RPC_SSH_HOST.
  --rpc-port PORT                   SSH port. Default: WEB_OSINT_RPC_SSH_PORT.
  --rpc-data-root PATH              RPC data root. Default: WEB_OSINT_RPC_DATA_ROOT or WEB_OSINT_DATA_ROOT.
  --remote-pandaproxy URL           RPC-local Pandaproxy URL. Default: WEB_OSINT_REMOTE_PANDAPROXY_URL, PANDAPROXY_URL, or REDPANDA_PROXY_URL.
  --output-dir PATH                 Local artifact dir. Default: temp dir.
  --keep-tab                        Leave the task-owned browser tab open.
  --allow-x                         Allow x.com/twitter.com URLs.
  --help                            Show this help.
`);
}

function parseArgs(argv) {
  const args = {
    sourceProject: "rendered-web",
    topicLabels: [],
    eventIndex: 0,
    cdpUrl: DEFAULT_CDP_URL,
    settleMs: 2500,
    timeoutMs: 60_000,
    scroll: true,
    publish: false,
    rpcHost: DEFAULT_RPC_HOST,
    rpcPort: DEFAULT_RPC_PORT,
    rpcDataRoot: DEFAULT_RPC_DATA_ROOT,
    remotePandaproxy: DEFAULT_REMOTE_PANDAPROXY,
    keepTab: false,
    allowX: false,
  };
  for (let i = 0; i < argv.length; i += 1) {
    const item = argv[i];
    const next = () => {
      i += 1;
      if (i >= argv.length) throw new Error(`${item} requires a value`);
      return argv[i];
    };
    if (item === "--help" || item === "-h") args.help = true;
    else if (item === "--url") args.url = next();
    else if (item === "--source-project") args.sourceProject = next();
    else if (item === "--collector-run-id") args.collectorRunId = next();
    else if (item === "--event-index") args.eventIndex = Number.parseInt(next(), 10);
    else if (item === "--topic-label") args.topicLabels.push(next());
    else if (item === "--context-json") args.contextJson = next();
    else if (item === "--cdp-url") args.cdpUrl = next();
    else if (item === "--settle-ms") args.settleMs = Number.parseInt(next(), 10);
    else if (item === "--timeout-ms") args.timeoutMs = Number.parseInt(next(), 10);
    else if (item === "--scroll") args.scroll = true;
    else if (item === "--no-scroll") args.scroll = false;
    else if (item === "--publish") args.publish = true;
    else if (item === "--rpc-host") args.rpcHost = next();
    else if (item === "--rpc-port") args.rpcPort = next();
    else if (item === "--rpc-data-root") args.rpcDataRoot = next();
    else if (item === "--remote-pandaproxy") args.remotePandaproxy = next();
    else if (item === "--output-dir") args.outputDir = next();
    else if (item === "--keep-tab") args.keepTab = true;
    else if (item === "--allow-x") args.allowX = true;
    else throw new Error(`Unknown argument: ${item}`);
  }
  return args;
}

function requireArg(value, flag, envName) {
  if (!value) {
    throw new Error(`${flag} is required; pass ${flag} or set ${envName}`);
  }
  return value;
}

function validateArgs(args) {
  if (!args.url) throw new Error("Missing --url");
  requireArg(args.cdpUrl, "--cdp-url", "REBROWSER_CDP_URL");
  if (args.publish) {
    requireArg(args.rpcHost, "--rpc-host", "WEB_OSINT_RPC_SSH_HOST");
    requireArg(args.rpcPort, "--rpc-port", "WEB_OSINT_RPC_SSH_PORT");
    requireArg(args.rpcDataRoot, "--rpc-data-root", "WEB_OSINT_RPC_DATA_ROOT or WEB_OSINT_DATA_ROOT");
    requireArg(args.remotePandaproxy, "--remote-pandaproxy", "WEB_OSINT_REMOTE_PANDAPROXY_URL, PANDAPROXY_URL, or REDPANDA_PROXY_URL");
  }
}

function sha256Text(value) {
  return crypto.createHash("sha256").update(value || "", "utf8").digest("hex");
}

function sha256Bytes(value) {
  return crypto.createHash("sha256").update(value).digest("hex");
}

function stableJson(value) {
  return JSON.stringify(sortKeys(value));
}

function sortKeys(value) {
  if (Array.isArray(value)) return value.map(sortKeys);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(Object.keys(value).sort().map((key) => [key, sortKeys(value[key])]));
}

function stableHash(...parts) {
  return sha256Text(parts.map((part) => typeof part === "string" ? part : stableJson(part)).join("\n"));
}

function nowIso() {
  return new Date().toISOString();
}

function compactDate() {
  return new Date().toISOString().slice(0, 10).replaceAll("-", "");
}

function slug(value) {
  return String(value || "capture").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 80) || "capture";
}

function cleanWs(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function truncate(value, limit = MAX_EVENT_TEXT_CHARS) {
  const text = String(value || "");
  return text.length > limit ? text.slice(0, limit) : text;
}

function splitBlocks(text) {
  return String(text || "")
    .split(/\n{2,}/)
    .map(cleanWs)
    .filter(Boolean)
    .slice(0, MAX_BLOCKS);
}

function domainOf(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}

function parseJsonObject(raw, fallback = {}) {
  if (!raw) return fallback;
  const parsed = JSON.parse(raw);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("JSON argument must be an object");
  }
  return parsed;
}

async function loadPlaywright() {
  const candidates = [
    process.env.PLAYWRIGHT_MODULE,
    path.join(process.cwd(), "node_modules", "playwright", "index.mjs"),
    path.join(os.homedir(), ".codex", "x-cdp-rebrowser-playwright", "node_modules", "playwright", "index.mjs"),
  ].filter(Boolean);
  let lastError = null;
  for (const candidate of candidates) {
    try {
      if (candidate === "playwright") return await import("playwright");
      if (fs.existsSync(candidate)) return await import(pathToFileURL(candidate).href);
    } catch (error) {
      lastError = error;
    }
  }
  try {
    return await import("playwright");
  } catch (error) {
    lastError = error;
  }
  throw new Error(`Unable to load Playwright. Set PLAYWRIGHT_MODULE or run from a project with playwright installed. Last error: ${lastError?.message || lastError}`);
}

function assertUrlAllowed(url, allowX) {
  const parsed = new URL(url);
  if (!["http:", "https:"].includes(parsed.protocol)) {
    throw new Error("Only http/https URLs are supported");
  }
  const host = parsed.hostname.toLowerCase();
  if (!allowX && (host === "x.com" || host.endsWith(".x.com") || host === "twitter.com" || host.endsWith(".twitter.com"))) {
    throw new Error("X/Twitter URLs require the X-specific collector/subskill. Use --allow-x only for an explicit exception.");
  }
}

async function slowScroll(page) {
  await page.evaluate(async () => {
    const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
    const maxScroll = Math.max(document.body?.scrollHeight || 0, document.documentElement?.scrollHeight || 0);
    const viewport = window.innerHeight || 900;
    let y = 0;
    while (y + viewport < maxScroll) {
      y = Math.min(y + Math.round(viewport * 0.72), maxScroll);
      window.scrollTo({ top: y, behavior: "smooth" });
      await sleep(350 + Math.round(Math.random() * 250));
    }
    await sleep(400);
    window.scrollTo({ top: 0, behavior: "smooth" });
    await sleep(500);
  });
}

async function captureRenderedPage(args) {
  const { chromium } = await loadPlaywright();
  const browser = await chromium.connectOverCDP(args.cdpUrl);
  const context = browser.contexts()[0] || await browser.newContext();
  const page = await context.newPage();
  let result;
  try {
    await page.setViewportSize({ width: 1440, height: 1100 });
    await page.goto(args.url, { waitUntil: "domcontentloaded", timeout: args.timeoutMs });
    await page.waitForLoadState("networkidle", { timeout: 12_000 }).catch(() => {});
    await page.waitForTimeout(args.settleMs);
    if (args.scroll) {
      await slowScroll(page).catch(async () => {
        await page.waitForLoadState("domcontentloaded", { timeout: 8_000 }).catch(() => {});
        await page.waitForTimeout(1_000);
      });
    }
    await page.waitForTimeout(600);
    result = await page.evaluate(() => {
      const clean = (value) => String(value || "").replace(/\s+/g, " ").trim();
      const abs = (value) => {
        try { return new URL(value, location.href).href; } catch { return ""; }
      };
      const domPath = (node) => {
        const parts = [];
        let current = node;
        while (current && current.nodeType === Node.ELEMENT_NODE && parts.length < 12) {
          let selector = current.nodeName.toLowerCase();
          if (current.id) {
            selector += `#${CSS.escape(current.id)}`;
            parts.unshift(selector);
            break;
          }
          const parent = current.parentElement;
          if (parent) {
            const siblings = Array.from(parent.children).filter((child) => child.nodeName === current.nodeName);
            if (siblings.length > 1) selector += `:nth-of-type(${siblings.indexOf(current) + 1})`;
          }
          parts.unshift(selector);
          current = parent;
        }
        return parts.join(" > ");
      };
      const metaBy = (...names) => {
        for (const name of names) {
          const selector = `meta[name="${CSS.escape(name)}"], meta[property="${CSS.escape(name)}"]`;
          const content = document.querySelector(selector)?.getAttribute("content");
          if (content) return clean(content);
        }
        return "";
      };
      const canonical = abs(document.querySelector('link[rel~="canonical"]')?.getAttribute("href") || location.href);
      const title = clean(metaBy("og:title", "twitter:title") || document.title || document.querySelector("h1")?.innerText || "");
      const description = clean(metaBy("description", "og:description", "twitter:description"));
      const publishedAt = clean(metaBy("article:published_time", "date", "pubdate", "publishdate") || document.querySelector("time[datetime]")?.getAttribute("datetime") || "");
      const root = document.querySelector("article") || document.querySelector("main") || document.body;
      const text = (root?.innerText || document.body?.innerText || "").replace(/\n{3,}/g, "\n\n").trim();
      const bodyText = (document.body?.innerText || "").replace(/\n{3,}/g, "\n\n").trim();
      const html = document.documentElement?.outerHTML || "";
      const headings = Array.from(document.querySelectorAll("h1,h2,h3,h4,h5,h6")).slice(0, 240).map((el, index) => ({
        index,
        level: el.tagName.toLowerCase(),
        text: clean(el.innerText),
        dom_path: domPath(el),
      })).filter((item) => item.text);
      const links = Array.from(document.querySelectorAll("a[href]")).slice(0, 600).map((el, index) => ({
        index,
        url: abs(el.getAttribute("href")),
        text: clean(el.innerText || el.getAttribute("aria-label") || el.getAttribute("title") || ""),
        dom_path: domPath(el),
      })).filter((item) => item.url);
      const images = Array.from(document.querySelectorAll("img, picture img")).slice(0, 300).map((el, index) => ({
        index,
        url: abs(el.currentSrc || el.src || el.getAttribute("src") || ""),
        alt: clean(el.getAttribute("alt") || ""),
        title: clean(el.getAttribute("title") || ""),
        width: Number(el.naturalWidth || el.width || 0),
        height: Number(el.naturalHeight || el.height || 0),
        dom_path: domPath(el),
      })).filter((item) => item.url);
      const tables = Array.from(document.querySelectorAll("table")).slice(0, 80).map((table, tableIndex) => {
        const rows = Array.from(table.querySelectorAll("tr")).slice(0, 200).map((tr) => (
          Array.from(tr.querySelectorAll("th,td")).map((cell) => clean(cell.innerText))
        )).filter((row) => row.some(Boolean));
        return {
          table_index: tableIndex,
          caption: clean(table.querySelector("caption")?.innerText || ""),
          row_count: rows.length,
          column_count: rows.reduce((max, row) => Math.max(max, row.length), 0),
          dom_path: domPath(table),
          rows,
        };
      }).filter((table) => table.rows.length);
      const tableLike = Array.from(document.querySelectorAll('[role="table"], [role="grid"], .table, [class*="table"], [class*="benchmark"]')).slice(0, 80).map((el, index) => ({
        index,
        text: clean(el.innerText).slice(0, 5000),
        dom_path: domPath(el),
      })).filter((item) => item.text.length > 40);
      const blocks = Array.from((root || document.body).querySelectorAll("h1,h2,h3,h4,h5,h6,p,li,blockquote,figcaption,pre,code")).slice(0, 900).map((el, index) => ({
        index,
        type: el.tagName.toLowerCase(),
        text: clean(el.innerText),
        dom_path: domPath(el),
      })).filter((item) => item.text);
      const jsonLd = Array.from(document.querySelectorAll('script[type="application/ld+json"]')).slice(0, 50).map((el) => el.textContent || "");
      const toc = Array.from(document.querySelectorAll('nav a[href], aside a[href], [class*="toc"] a[href], [id*="toc"] a[href]')).slice(0, 200).map((el, index) => ({
        index,
        text: clean(el.innerText),
        url: abs(el.getAttribute("href")),
        dom_path: domPath(el),
      })).filter((item) => item.text || item.url);
      return {
        url: location.href,
        canonical_url: canonical,
        title,
        description,
        published_at: publishedAt,
        text,
        body_text: bodyText,
        html,
        headings,
        links,
        images,
        tables,
        table_like: tableLike,
        blocks,
        json_ld: jsonLd,
        toc,
        viewport: { width: window.innerWidth, height: window.innerHeight },
        document_size: {
          scroll_width: Math.max(document.body?.scrollWidth || 0, document.documentElement?.scrollWidth || 0),
          scroll_height: Math.max(document.body?.scrollHeight || 0, document.documentElement?.scrollHeight || 0),
        },
      };
    });
    try {
      result.screenshotBuffer = await page.screenshot({ fullPage: true, type: "png", timeout: 15_000 });
      result.screenshot_mode = "full_page";
    } catch {
      result.screenshotBuffer = await page.screenshot({ fullPage: false, type: "png", timeout: 10_000 });
      result.screenshot_mode = "viewport_fallback";
    }
  } finally {
    if (!args.keepTab) await page.close().catch(() => {});
    // For connectOverCDP, Playwright marks the browser so close() closes only
    // this client connection, not the preserved Rebrowser process.
    await browser.close().catch(() => {});
  }
  return result;
}

function markdownFromExtracted(extracted) {
  const lines = [];
  if (extracted.title) lines.push(`# ${extracted.title}`, "");
  if (extracted.description) lines.push(extracted.description, "");
  for (const block of (extracted.blocks || []).slice(0, MAX_BLOCKS)) {
    const text = cleanWs(block.text);
    if (!text) continue;
    if (/^h[1-6]$/.test(block.type)) {
      const level = Number(block.type.slice(1));
      lines.push(`${"#".repeat(Math.min(level, 6))} ${text}`, "");
    } else if (block.type === "li") {
      lines.push(`- ${text}`);
    } else {
      lines.push(text, "");
    }
  }
  return lines.join("\n").replace(/\n{3,}/g, "\n\n").trim() + "\n";
}

function textAnchor(text, index, source, domPath = "") {
  return {
    selector_type: "text_quote",
    source,
    index,
    exact: cleanWs(text).slice(0, 320),
    prefix: "",
    suffix: "",
    dom_path: domPath,
  };
}

function orderAnchor(index, source, domPath = "") {
  return { selector_type: "extracted_order", source, index, dom_path: domPath };
}

function buildEvidenceDocument({ documentId, extracted, capturedAt, collectorRunId, eventIndex, artifactPaths, topics, context, htmlSha, textSha, screenshotSha }) {
  const blocks = [];
  if (extracted.title) {
    blocks.push({
      block_id: `${documentId}:title:0`,
      type: "title",
      text: extracted.title,
      anchor: orderAnchor(0, "metadata_title"),
      metadata: { role: "document_title" },
    });
  }
  if (extracted.description) {
    blocks.push({
      block_id: `${documentId}:description:0`,
      type: "summary",
      text: extracted.description,
      anchor: orderAnchor(0, "metadata_description"),
      metadata: { role: "meta_description" },
    });
  }
  for (const heading of (extracted.headings || []).slice(0, 200)) {
    blocks.push({
      block_id: `${documentId}:heading:${heading.index}`,
      type: "heading",
      text: heading.text,
      level: heading.level,
      anchor: textAnchor(heading.text, heading.index, "rendered_dom_heading", heading.dom_path),
      metadata: {},
    });
  }
  const blockSource = (extracted.blocks || []).length ? extracted.blocks : splitBlocks(extracted.text).map((text, index) => ({ index, type: "p", text, dom_path: "" }));
  for (const block of blockSource.slice(0, MAX_BLOCKS)) {
    const text = cleanWs(block.text);
    if (!text) continue;
    blocks.push({
      block_id: `${documentId}:text:${block.index}`,
      type: /^h[1-6]$/.test(block.type) ? "heading" : block.type === "li" ? "list_item" : "paragraph",
      text,
      anchor: textAnchor(text, block.index, "rendered_dom_text", block.dom_path),
      metadata: { source_representation: "rebrowser_rendered_dom", dom_tag: block.type },
    });
  }
  for (const table of (extracted.tables || []).slice(0, 80)) {
    blocks.push({
      block_id: `${documentId}:table:${table.table_index}`,
      type: "table",
      text: table.caption || `Table ${table.table_index + 1}`,
      rows: table.rows || [],
      anchor: orderAnchor(table.table_index, "rendered_dom_table", table.dom_path),
      metadata: {
        caption: table.caption || "",
        row_count: table.row_count || 0,
        column_count: table.column_count || 0,
      },
    });
  }

  const assets = (extracted.images || []).slice(0, MAX_ASSETS).map((image) => ({
    asset_id: `${documentId}:image:${image.index}`,
    type: "image",
    url: image.url,
    alt: image.alt || "",
    title: image.title || "",
    width: image.width || 0,
    height: image.height || 0,
    anchor: orderAnchor(image.index, "rendered_dom_image", image.dom_path),
    metadata: {},
  }));
  const screenshotPath = artifactPaths.find((item) => item.includes("/screenshots/")) || "";
  if (screenshotPath) {
    assets.unshift({
      asset_id: `${documentId}:screenshot:0`,
      type: "screenshot",
      path: screenshotPath,
      sha256: screenshotSha,
      anchor: orderAnchor(0, "rendered_full_page_screenshot"),
      metadata: extracted.document_size || {},
    });
  }

  const omitted = [];
  if ((extracted.text || "").length > MAX_EVENT_TEXT_CHARS) {
    omitted.push({
      kind: "text_tail",
      reason: "capture_event_text_truncated",
      available_in_artifact: "text",
      omitted_chars: extracted.text.length - MAX_EVENT_TEXT_CHARS,
    });
  }

  return {
    schema_version: "v1",
    document_id: documentId,
    created_at: capturedAt,
    source: {
      source_kind: "web_page",
      source_url: extracted.source_url,
      final_url: extracted.url,
      canonical_url: extracted.canonical_url,
      domain: domainOf(extracted.canonical_url || extracted.url),
      title: extracted.title,
      description: extracted.description,
      published_at: extracted.published_at || null,
      topics,
    },
    captures: [{
      capture_id: `${collectorRunId}:${eventIndex}`,
      collector_run_id: collectorRunId,
      event_index: eventIndex,
      capture_method: PRODUCER_NAME,
      captured_at: capturedAt,
      content_type: "text/html; rendered=rebrowser",
      html_sha256: htmlSha,
      text_sha256: textSha,
      screenshot_sha256: screenshotSha,
      artifacts: artifactPaths,
      context: context || {},
    }],
    revision: {
      revision_id: stableHash(documentId, textSha, screenshotSha, PRODUCER_NAME, PRODUCER_VERSION).slice(0, 24),
      producer: { name: PRODUCER_NAME, version: PRODUCER_VERSION },
      generated_at: capturedAt,
      extraction_methods: ["rebrowser_cdp", "rendered_dom", "inner_text", "full_page_screenshot"],
      quality: {
        text_chars: (extracted.text || "").length,
        body_text_chars: (extracted.body_text || "").length,
        block_count: blocks.length,
        asset_count: assets.length,
        table_count: (extracted.tables || []).length,
        table_like_count: (extracted.table_like || []).length,
        link_count: (extracted.links || []).length,
        image_count: (extracted.images || []).length,
        toc_count: (extracted.toc || []).length,
        json_ld_count: (extracted.json_ld || []).length,
        needs_rebrowser_rendered_capture: false,
      },
    },
    blocks: blocks.slice(0, MAX_BLOCKS),
    assets,
    omitted_content: omitted,
    projections: {
      rendered_html: artifactPaths.find((item) => item.includes("/html/")) || "",
      text: artifactPaths.find((item) => item.includes("/text/")) || "",
      markdown: artifactPaths.find((item) => item.includes("/markdown/")) || "",
      tables_json: artifactPaths.find((item) => item.includes("/tables/")) || "",
      metadata_json: artifactPaths.find((item) => item.includes("/metadata/")) || "",
      screenshot: screenshotPath,
    },
  };
}

function writeFileSyncMkdir(filePath, content) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, content);
}

function localArtifactPaths(localRoot) {
  const results = [];
  const visit = (dir) => {
    for (const name of fs.readdirSync(dir)) {
      const item = path.join(dir, name);
      const stat = fs.statSync(item);
      if (stat.isDirectory()) visit(item);
      else results.push(item);
    }
  };
  visit(localRoot);
  return results;
}

function remotePathFor(localPath, localRoot, remoteRoot) {
  const rel = path.relative(localRoot, localPath).split(path.sep).join("/");
  return `${remoteRoot.replace(/\/$/, "")}/${rel}`;
}

function runChecked(command, args, options = {}) {
  const result = spawnSync(command, args, { encoding: options.encoding || "utf8", input: options.input, stdio: options.stdio || "pipe" });
  if (result.status !== 0) {
    throw new Error(`${command} ${args.join(" ")} failed with ${result.status}: ${(result.stderr || result.stdout || "").trim()}`);
  }
  return result;
}

function ssh(args, remoteCommand, input) {
  return runChecked("ssh", ["-p", args.rpcPort, args.rpcHost, remoteCommand], { input });
}

function uploadArtifacts(args, localRoot, remoteRoot) {
  ssh(args, `mkdir -p ${JSON.stringify(remoteRoot)}`);
  const sshArg = `ssh -p ${args.rpcPort}`;
  runChecked("rsync", ["-az", "-e", sshArg, `${localRoot.replace(/\/$/, "")}/`, `${args.rpcHost}:${remoteRoot.replace(/\/$/, "")}/`]);
}

function publishCaptureEvent(args, event) {
  const key = `${event.collector_run_id}:${event.event_index}`;
  const body = JSON.stringify({ records: [{ key, value: event }] });
  const command = [
    "tmp=$(mktemp /tmp/web-osint-rendered-capture.XXXXXX.json)",
    "cat > \"$tmp\"",
    `curl -fsS -X POST -H 'Content-Type: application/vnd.kafka.json.v2+json' -H 'Accept: application/vnd.kafka.v2+json' --data-binary @"$tmp" ${JSON.stringify(args.remotePandaproxy.replace(/\/$/, "") + "/topics/" + TOPIC)}`,
    "status=$?",
    "rm -f \"$tmp\"",
    "exit $status",
  ].join("; ");
  return ssh(args, command, body + "\n").stdout.trim();
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    usage();
    return;
  }
  validateArgs(args);
  assertUrlAllowed(args.url, args.allowX);
  const capturedAt = nowIso();
  const context = parseJsonObject(args.contextJson, {});
  const collectorRunId = args.collectorRunId || `rebrowser_rendered_${new Date().toISOString().replace(/[-:]/g, "").replace(/\..+/, "Z")}_${stableHash(args.url).slice(0, 8)}`;
  const extracted = await captureRenderedPage(args);
  extracted.source_url = args.url;
  const canonicalUrl = extracted.canonical_url || extracted.url || args.url;
  const text = extracted.text || extracted.body_text || "";
  const html = extracted.html || "";
  const markdown = markdownFromExtracted(extracted);
  const htmlSha = sha256Text(html);
  const textSha = sha256Text(text);
  const screenshotSha = sha256Bytes(extracted.screenshotBuffer);
  const documentId = stableHash(canonicalUrl, textSha, screenshotSha).slice(0, 24);
  const localRoot = args.outputDir
    ? path.resolve(args.outputDir)
    : path.join(os.tmpdir(), "web-osint-rebrowser-rendered", collectorRunId, documentId);
  fs.rmSync(localRoot, { recursive: true, force: true });
  fs.mkdirSync(localRoot, { recursive: true });
  const localFiles = {
    html: path.join(localRoot, "html", `${htmlSha}.html`),
    text: path.join(localRoot, "text", `${textSha}.txt`),
    markdown: path.join(localRoot, "markdown", `${textSha}.md`),
    tables: path.join(localRoot, "tables", `${textSha}.json`),
    metadata: path.join(localRoot, "metadata", `${textSha}.json`),
    screenshot: path.join(localRoot, "screenshots", `${screenshotSha}.png`),
    evidenceDocument: path.join(localRoot, "evidence_document", `${documentId}.json`),
  };
  writeFileSyncMkdir(localFiles.html, html);
  writeFileSyncMkdir(localFiles.text, text);
  writeFileSyncMkdir(localFiles.markdown, markdown);
  writeFileSyncMkdir(localFiles.tables, JSON.stringify(extracted.tables || [], null, 2));
  writeFileSyncMkdir(localFiles.metadata, JSON.stringify({
    url: args.url,
    final_url: extracted.url,
    canonical_url: canonicalUrl,
    title: extracted.title,
    description: extracted.description,
    published_at: extracted.published_at || null,
    headings: extracted.headings || [],
    links: extracted.links || [],
    images: extracted.images || [],
    toc: extracted.toc || [],
    table_like: extracted.table_like || [],
    json_ld: extracted.json_ld || [],
      viewport: extracted.viewport || {},
      document_size: extracted.document_size || {},
      screenshot_mode: extracted.screenshot_mode || "",
      producer: { name: PRODUCER_NAME, version: PRODUCER_VERSION },
    captured_at: capturedAt,
  }, null, 2));
  writeFileSyncMkdir(localFiles.screenshot, extracted.screenshotBuffer);

  const remoteRoot = `${args.rpcDataRoot.replace(/\/$/, "")}/web/rebrowser-rendered/${compactDate()}/${collectorRunId}/${documentId}`;
  const localArtifactList = localArtifactPaths(localRoot);
  const artifactPaths = args.publish
    ? localArtifactList.map((item) => remotePathFor(item, localRoot, remoteRoot))
    : localArtifactList;
  const evidenceDocument = buildEvidenceDocument({
    documentId,
    extracted,
    capturedAt,
    collectorRunId,
    eventIndex: args.eventIndex,
    artifactPaths,
    topics: args.topicLabels,
    context,
    htmlSha,
    textSha,
    screenshotSha,
  });
  writeFileSyncMkdir(localFiles.evidenceDocument, JSON.stringify(evidenceDocument, null, 2));
  const refreshedLocalArtifacts = localArtifactPaths(localRoot);
  const refreshedArtifactPaths = args.publish
    ? refreshedLocalArtifacts.map((item) => remotePathFor(item, localRoot, remoteRoot))
    : refreshedLocalArtifacts;
  evidenceDocument.captures[0].artifacts = refreshedArtifactPaths;
  evidenceDocument.projections.evidence_document = args.publish
    ? remotePathFor(localFiles.evidenceDocument, localRoot, remoteRoot)
    : localFiles.evidenceDocument;
  writeFileSyncMkdir(localFiles.evidenceDocument, JSON.stringify(evidenceDocument, null, 2));

  const remoteArtifactPaths = args.publish
    ? localArtifactPaths(localRoot).map((item) => remotePathFor(item, localRoot, remoteRoot))
    : localArtifactPaths(localRoot);
  const evidenceDocumentPath = args.publish
    ? remotePathFor(localFiles.evidenceDocument, localRoot, remoteRoot)
    : localFiles.evidenceDocument;
  const document = {
    schema_version: "v1",
    document_id: documentId,
    evidence_document_id: documentId,
    evidence_document_path: evidenceDocumentPath,
    canonical_url: canonicalUrl,
    domain: domainOf(canonicalUrl),
    title: extracted.title || "",
    text: truncate(text),
    markdown: truncate(markdown),
    text_hash: textSha,
    content_type: "text/html; rendered=rebrowser",
    document_kind: "web_page",
    published_at: extracted.published_at || null,
    retrieved_at: capturedAt,
    extracted_at: capturedAt,
    links: (extracted.links || []).map((item) => item.url).filter(Boolean),
    media: extracted.images || [],
    media_ids: [],
    topics: args.topicLabels,
    entities: [],
    artifact_paths: remoteArtifactPaths,
    tables: extracted.tables || [],
    quality: evidenceDocument.revision.quality,
    raw: {
      source_url: args.url,
      final_url: extracted.url,
      description: extracted.description,
      headings: extracted.headings || [],
      images: extracted.images || [],
      toc: extracted.toc || [],
      table_like: extracted.table_like || [],
      viewport: extracted.viewport || {},
      document_size: extracted.document_size || {},
      screenshot_sha256: screenshotSha,
    },
    content_representations: {
      canonical_evidence_document: evidenceDocumentPath,
      rendered_html: remoteArtifactPaths.find((item) => item.includes("/html/")) || "",
      text: remoteArtifactPaths.find((item) => item.includes("/text/")) || "",
      markdown: remoteArtifactPaths.find((item) => item.includes("/markdown/")) || "",
      tables_json: remoteArtifactPaths.find((item) => item.includes("/tables/")) || "",
      metadata_json: remoteArtifactPaths.find((item) => item.includes("/metadata/")) || "",
      screenshot: remoteArtifactPaths.find((item) => item.includes("/screenshots/")) || "",
    },
    capture_bundle: {
      source_url: args.url,
      final_url: extracted.url,
      capture_method: PRODUCER_NAME,
      rendered_browser_surface: "rebrowser",
      static_extraction_method: "",
      rendered_capture_required: true,
      rendered_capture_completed: true,
    },
  };
  const captureEvent = {
    schema_version: "v1",
    collector_run_id: collectorRunId,
    event_index: args.eventIndex,
    source_project: args.sourceProject,
    capture_method: PRODUCER_NAME,
    captured_at: capturedAt,
    page_url: args.url,
    page_title: extracted.title || "",
    context,
    posts: [],
    accounts: [],
    media: [],
    web_documents: [document],
    user_inputs: [],
    links: document.links,
    quality: {
      rendered_capture: true,
      text_chars: text.length,
      html_chars: html.length,
      artifact_count: remoteArtifactPaths.length,
      published: args.publish,
    },
  };

  let publishResponse = null;
  if (args.publish) {
    uploadArtifacts(args, localRoot, remoteRoot);
    publishResponse = publishCaptureEvent(args, captureEvent);
  }
  console.log(JSON.stringify({
    collector_run_id: collectorRunId,
    event_index: args.eventIndex,
    published: args.publish,
    publish_response: publishResponse,
    local_artifact_root: localRoot,
    remote_artifact_root: args.publish ? remoteRoot : null,
    document_id: documentId,
    evidence_document_path: evidenceDocumentPath,
    canonical_url: canonicalUrl,
    title: extracted.title || "",
    text_chars: text.length,
    html_chars: html.length,
    artifact_paths: remoteArtifactPaths,
    capture_event: args.publish ? undefined : captureEvent,
  }, null, 2));
}

main().catch((error) => {
  console.error(error.stack || error.message || String(error));
  process.exit(1);
});
