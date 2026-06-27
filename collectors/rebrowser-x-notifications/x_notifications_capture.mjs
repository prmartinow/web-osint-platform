#!/usr/bin/env node
import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { spawnSync } from "node:child_process";

const PRODUCER_NAME = "rebrowser-x-notifications-capture";
const PRODUCER_VERSION = "0.1.0";
const TOPIC = "evidence.capture.events.v1";
const DEFAULT_CDP_URL = process.env.REBROWSER_CDP_URL || "";
const DEFAULT_RPC_HOST = process.env.WEB_OSINT_RPC_SSH_HOST || "";
const DEFAULT_RPC_PORT = process.env.WEB_OSINT_RPC_SSH_PORT || "22";
const DEFAULT_RPC_DATA_ROOT = process.env.WEB_OSINT_RPC_DATA_ROOT || process.env.WEB_OSINT_DATA_ROOT || "";
const DEFAULT_REMOTE_PANDAPROXY = process.env.WEB_OSINT_REMOTE_PANDAPROXY_URL || "";
const DEFAULT_HELPER_PATH = process.env.REBROWSER_X_HELPERS || "";
const DEFAULT_EXPECTED_ACCOUNT = process.env.WEB_OSINT_X_EXPECTED_ACCOUNT || "";
const MAX_TEXT_CHARS = 50_000;

function usage() {
  console.log(`Usage:
  node collectors/rebrowser-x-notifications/x_notifications_capture.mjs [options]

Options:
  --source-project NAME             Source project label. Default: x-notifications
  --collector-run-id ID             Collector run id. Default generated.
  --event-index N                   Capture event index. Default: 0
  --expected-account HANDLE         Logged-in account expected for operator context.
  --max-items N                     Max visible notification rows. Default: 16
  --timeline-items N                Max visible post rows after grouped click. Default: 12
  --notification-scrolls N          Gentle notification-list scroll count before giving up on grouped rows. Default: 1
  --scrolls N                       Gentle timeline scroll count after grouped click. Default: 2
  --click-first-grouped             Open first grouped new-post notification. Default.
  --no-click-first-grouped          Do not open grouped notification.
  --cdp-url URL                     Rebrowser CDP URL. Default: REBROWSER_CDP_URL env.
  --helper-path PATH                Rebrowser slow X helper. Default: REBROWSER_X_HELPERS env.
  --publish                         Upload artifacts and publish to RPC Redpanda.
  --rpc-host HOST                   SSH host. Default: WEB_OSINT_RPC_SSH_HOST env.
  --rpc-port PORT                   SSH port. Default: WEB_OSINT_RPC_SSH_PORT env or 22.
  --rpc-data-root PATH              RPC data root. Default: WEB_OSINT_RPC_DATA_ROOT or WEB_OSINT_DATA_ROOT env.
  --remote-pandaproxy URL           RPC-local Pandaproxy URL. Default: WEB_OSINT_REMOTE_PANDAPROXY_URL env.
  --output-dir PATH                 Local artifact dir. Default: temp dir.
  --keep-tab                        Leave task-owned tab open.
  --help                            Show this help.
`);
}

function parseArgs(argv) {
  const args = {
    sourceProject: "x-notifications",
    eventIndex: 0,
    expectedAccount: cleanHandle(DEFAULT_EXPECTED_ACCOUNT),
    maxItems: 16,
    timelineItems: 12,
    notificationScrolls: 1,
    scrolls: 2,
    clickFirstGrouped: true,
    cdpUrl: DEFAULT_CDP_URL,
    helperPath: DEFAULT_HELPER_PATH,
    publish: false,
    rpcHost: DEFAULT_RPC_HOST,
    rpcPort: DEFAULT_RPC_PORT,
    rpcDataRoot: DEFAULT_RPC_DATA_ROOT,
    remotePandaproxy: DEFAULT_REMOTE_PANDAPROXY,
    keepTab: false,
  };
  for (let i = 0; i < argv.length; i += 1) {
    const item = argv[i];
    const next = () => {
      i += 1;
      if (i >= argv.length) throw new Error(`${item} requires a value`);
      return argv[i];
    };
    if (item === "--help" || item === "-h") args.help = true;
    else if (item === "--source-project") args.sourceProject = next();
    else if (item === "--collector-run-id") args.collectorRunId = next();
    else if (item === "--event-index") args.eventIndex = Number.parseInt(next(), 10);
    else if (item === "--expected-account") args.expectedAccount = cleanHandle(next());
    else if (item === "--max-items") args.maxItems = Number.parseInt(next(), 10);
    else if (item === "--timeline-items") args.timelineItems = Number.parseInt(next(), 10);
    else if (item === "--notification-scrolls") args.notificationScrolls = Number.parseInt(next(), 10);
    else if (item === "--scrolls") args.scrolls = Number.parseInt(next(), 10);
    else if (item === "--click-first-grouped") args.clickFirstGrouped = true;
    else if (item === "--no-click-first-grouped") args.clickFirstGrouped = false;
    else if (item === "--cdp-url") args.cdpUrl = next();
    else if (item === "--helper-path") args.helperPath = next();
    else if (item === "--publish") args.publish = true;
    else if (item === "--rpc-host") args.rpcHost = next();
    else if (item === "--rpc-port") args.rpcPort = next();
    else if (item === "--rpc-data-root") args.rpcDataRoot = next();
    else if (item === "--remote-pandaproxy") args.remotePandaproxy = next();
    else if (item === "--output-dir") args.outputDir = next();
    else if (item === "--keep-tab") args.keepTab = true;
    else throw new Error(`Unknown argument: ${item}`);
  }
  if (!Number.isFinite(args.eventIndex)) args.eventIndex = 0;
  if (!Number.isFinite(args.maxItems) || args.maxItems < 1) args.maxItems = 16;
  if (!Number.isFinite(args.timelineItems) || args.timelineItems < 1) args.timelineItems = 12;
  if (!Number.isFinite(args.notificationScrolls) || args.notificationScrolls < 0) args.notificationScrolls = 1;
  if (!Number.isFinite(args.scrolls) || args.scrolls < 0) args.scrolls = 2;
  return args;
}

function requireConfig(args) {
  if (!args.cdpUrl) throw new Error("--cdp-url or REBROWSER_CDP_URL is required");
  if (!args.helperPath) throw new Error("--helper-path or REBROWSER_X_HELPERS is required");
  if (!args.publish) return;
  if (!args.rpcHost) throw new Error("--rpc-host or WEB_OSINT_RPC_SSH_HOST is required when --publish is used");
  if (!args.rpcDataRoot) throw new Error("--rpc-data-root, WEB_OSINT_RPC_DATA_ROOT, or WEB_OSINT_DATA_ROOT is required when --publish is used");
  if (!args.remotePandaproxy) throw new Error("--remote-pandaproxy or WEB_OSINT_REMOTE_PANDAPROXY_URL is required when --publish is used");
}

function nowIso() {
  return new Date().toISOString();
}

function compactDate() {
  return new Date().toISOString().slice(0, 10).replaceAll("-", "");
}

function sha256Bytes(value) {
  return crypto.createHash("sha256").update(value).digest("hex");
}

function sha256Text(value) {
  return crypto.createHash("sha256").update(String(value || ""), "utf8").digest("hex");
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

function cleanHandle(value) {
  return String(value || "").replace(/^@+/, "").trim().toLowerCase();
}

function truncate(value, limit = MAX_TEXT_CHARS) {
  const text = String(value || "");
  return text.length > limit ? text.slice(0, limit) : text;
}

function remotePathFor(localPath, localRoot, remoteRoot) {
  if (!remoteRoot) return "";
  const rel = path.relative(localRoot, localPath).split(path.sep).join("/");
  return `${remoteRoot.replace(/\/$/, "")}/${rel}`;
}

function runChecked(command, args, options = {}) {
  const result = spawnSync(command, args, {
    encoding: options.encoding || "utf8",
    input: options.input,
    stdio: options.stdio || "pipe",
  });
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
  runChecked("rsync", ["-az", "-e", `ssh -p ${args.rpcPort}`, `${localRoot.replace(/\/$/, "")}/`, `${args.rpcHost}:${remoteRoot.replace(/\/$/, "")}/`]);
}

function publishCaptureEvent(args, event) {
  const key = `${event.collector_run_id}:${event.event_index}`;
  const body = JSON.stringify({ records: [{ key, value: event }] });
  const command = [
    "tmp=$(mktemp /tmp/web-osint-x-notifications.XXXXXX.json)",
    "cat > \"$tmp\"",
    `curl -fsS -X POST -H 'Content-Type: application/vnd.kafka.json.v2+json' -H 'Accept: application/vnd.kafka.v2+json' --data-binary @"$tmp" ${JSON.stringify(args.remotePandaproxy.replace(/\/$/, "") + "/topics/" + TOPIC)}`,
    "status=$?",
    "rm -f \"$tmp\"",
    "exit $status",
  ].join("; ");
  return ssh(args, command, body + "\n").stdout.trim();
}

async function loadXHelpers(args) {
  const helperPath = path.resolve(args.helperPath);
  if (!fs.existsSync(helperPath)) throw new Error(`Rebrowser X helper not found: ${helperPath}`);
  return import(pathToFileURL(helperPath).href);
}

function artifactDescriptor(localPath, localRoot, remoteRoot) {
  const bytes = fs.readFileSync(localPath);
  return {
    local_path: localPath,
    storage_path: remotePathFor(localPath, localRoot, remoteRoot),
    sha256: sha256Bytes(bytes),
    bytes: bytes.length,
  };
}

function rewriteArtifactPaths(event, localRoot, remoteRoot) {
  const mapPath = (value) => typeof value === "string" && value.startsWith(localRoot)
    ? remotePathFor(value, localRoot, remoteRoot)
    : value;
  for (const media of event.media || []) {
    media.local_path = mapPath(media.local_path);
    media.storage_path = mapPath(media.storage_path || media.local_path);
  }
  if (event.context?.artifacts) {
    for (const artifact of event.context.artifacts) {
      artifact.local_path = mapPath(artifact.local_path);
      artifact.storage_path = mapPath(artifact.storage_path || artifact.local_path);
    }
  }
}

async function screenshotMedia(page, localRoot, remoteRoot, collectorRunId, label, caption) {
  const filePath = path.join(localRoot, "screenshots", `${label}.png`);
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  await page.screenshot({ path: filePath, fullPage: true });
  const artifact = artifactDescriptor(filePath, localRoot, remoteRoot);
  return {
    media_id: artifact.sha256,
    media_kind: "screenshot",
    kind: "screenshot",
    mime_type: "image/png",
    local_path: artifact.local_path,
    storage_path: artifact.storage_path,
    sha256: artifact.sha256,
    caption,
    topics: ["x-notifications", "web-osint"],
    collector_run_id: collectorRunId,
    bytes: artifact.bytes,
  };
}

async function extractXState(page, options = {}) {
  const maxItems = options.maxItems || 16;
  const maxPosts = options.maxPosts || 12;
  return page.evaluate(({ maxItems, maxPosts }) => {
    const clean = (value) => String(value || "").replace(/\s+/g, " ").trim();
    const unique = (items) => Array.from(new Set(items.filter(Boolean)));
    const absolute = (href) => {
      try { return new URL(href, location.origin).toString(); } catch { return ""; }
    };
    const handleFromPath = (href) => {
      try {
        const path = new URL(href, location.origin).pathname.split("/").filter(Boolean);
        const first = path[0] || "";
        if (!first || ["i", "home", "notifications", "search", "messages", "settings"].includes(first)) return "";
        return first.toLowerCase();
      } catch {
        return "";
      }
    };
    const statusParts = (href) => {
      try {
        const url = new URL(href, location.origin);
        const match = url.pathname.match(/^\/([^/]+)\/status\/([0-9]+)/);
        if (!match) return null;
        return { handle: match[1].toLowerCase(), post_id: match[2], url: url.toString() };
      } catch {
        return null;
      }
    };
    const linkData = (root) => Array.from(root.querySelectorAll("a[href]"))
      .map((anchor) => ({ href: absolute(anchor.getAttribute("href") || ""), text: clean(anchor.innerText || anchor.getAttribute("aria-label") || "") }))
      .filter((link) => link.href);
    const statusLinks = (root) => unique(linkData(root).map((link) => statusParts(link.href)?.url || ""));
    const handles = (root) => unique([
      ...linkData(root).map((link) => handleFromPath(link.href)),
      ...clean(root.innerText).matchAll(/@([A-Za-z0-9_]{2,20})/g),
    ].map((value) => Array.isArray(value) ? value[1].toLowerCase() : value));

    const cells = Array.from(document.querySelectorAll('[data-testid="cellInnerDiv"]'))
      .filter((node) => {
        const rect = node.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0 && rect.bottom > 0 && rect.top < window.innerHeight * 2.5;
      })
      .slice(0, maxItems)
      .map((node, index) => {
        const text = clean(node.innerText);
        const links = linkData(node);
        return {
          notification_id: `visible_notification_${index}`,
          index,
          text,
          links,
          status_urls: statusLinks(node),
          author_handles: handles(node),
          has_video: Boolean(node.querySelector("video")),
          image_count: node.querySelectorAll("img").length,
          aria_labels: unique(Array.from(node.querySelectorAll("[aria-label]")).map((item) => clean(item.getAttribute("aria-label")))).slice(0, 30),
          notification_kind: /new post notifications/i.test(text) ? "new_post_notifications" : (/mentioned|replied|repost|liked|follow/i.test(text) ? "engagement" : "notification"),
        };
      })
      .filter((item) => item.text || item.links.length);

    const articles = Array.from(document.querySelectorAll('article[role="article"], article[data-testid="tweet"]'))
      .filter((node) => {
        const rect = node.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0 && rect.bottom > 0 && rect.top < window.innerHeight * 2.8;
      })
      .slice(0, maxPosts)
      .map((node, index) => {
        const text = clean(node.innerText);
        const links = linkData(node);
        const status = links.map((link) => statusParts(link.href)).find(Boolean) || null;
        const accountHandles = handles(node);
        const authorHandle = status?.handle || accountHandles[0] || "";
        return {
          post_id: status?.post_id || "",
          url: status?.url || "",
          canonical_url: status?.url || "",
          author_handle: authorHandle,
          author_name: "",
          text,
          links: links.map((link) => link.href),
          media_ids: [],
          topics: ["x-notifications"],
          has_video: Boolean(node.querySelector("video")),
          image_count: node.querySelectorAll("img").length,
          raw: {
            visible_index: index,
            link_texts: links.slice(0, 20),
            author_handles: accountHandles,
            aria_labels: unique(Array.from(node.querySelectorAll("[aria-label]")).map((item) => clean(item.getAttribute("aria-label")))).slice(0, 30),
          },
        };
      })
      .filter((item) => item.text || item.url);

    const allHandles = unique([...cells.flatMap((item) => item.author_handles || []), ...articles.map((item) => item.author_handle)]);
    const accounts = allHandles.map((handle) => ({
      handle,
      profile_url: `https://x.com/${handle}`,
      display_name: "",
      bio: "",
      topics: ["x-notifications"],
      raw: { observed_from: location.href },
    }));
    return {
      page_url: location.href,
      page_title: document.title,
      body_text_sample: clean(document.body?.innerText || "").slice(0, 8000),
      notifications: cells,
      posts: articles,
      accounts,
      links: unique([...cells.flatMap((item) => (item.links || []).map((link) => link.href)), ...articles.flatMap((item) => item.links || [])]),
      quality: {
        notification_rows_visible: cells.length,
        posts_visible: articles.length,
        account_handles_visible: allHandles.length,
      },
    };
  }, { maxItems, maxPosts });
}

async function assertNotXLoginScreen(page) {
  const state = await page.evaluate(() => {
    const clean = (value) => String(value || "").replace(/\s+/g, " ").trim();
    return {
      url: location.href,
      title: document.title,
      text: clean(document.body?.innerText || "").slice(0, 3000),
    };
  });
  const haystack = `${state.url}\n${state.title}\n${state.text}`.toLowerCase();
  const loginSignals = [
    "continue with phone",
    "email or username",
    "sign in to x",
    "create your account",
    "forgot password",
    "by continuing, you agree to our terms of service",
  ];
  if (loginSignals.some((signal) => haystack.includes(signal))) {
    throw new Error("X login/continue screen detected. Stop before publishing; user must restore the intended logged-in profile.");
  }
}

function eventFromCapture(args, capturedAt, collectorRunId, states, media, artifacts) {
  const notificationText = states.map((state) => state.notifications.map((item) => item.text).join("\n")).join("\n");
  const allNotifications = states.flatMap((state, stateIndex) => (state.notifications || []).map((item) => ({ ...item, state_index: stateIndex })));
  const postsByKey = new Map();
  for (const state of states) {
    for (const post of state.posts || []) {
      const key = post.post_id || post.url || stableHash(post.text);
      if (!postsByKey.has(key)) {
        postsByKey.set(key, {
          ...post,
          text: truncate(post.text),
          media_ids: media.map((item) => item.media_id),
        });
      }
    }
  }
  const accountsByHandle = new Map();
  for (const state of states) {
    for (const account of state.accounts || []) {
      if (account.handle && !accountsByHandle.has(account.handle)) accountsByHandle.set(account.handle, account);
    }
  }
  const allLinks = Array.from(new Set(states.flatMap((state) => state.links || []))).map((url) => ({ url }));
  const userInputs = allNotifications
    .filter((item) => item.text)
    .map((item) => ({
      input_id: stableHash(collectorRunId, "x_notification", item.state_index, item.index, item.text).slice(0, 24),
      input_kind: "x_notification",
      title: item.notification_kind === "new_post_notifications" ? "X new post notification" : "X notification",
      text: truncate(item.text),
      links: (item.links || []).map((link) => link.href || link).filter(Boolean),
      topics: ["x-notifications"],
      context: {
        notification_kind: item.notification_kind,
        state_index: item.state_index,
        visible_index: item.index,
        status_urls: item.status_urls || [],
        author_handles: item.author_handles || [],
        has_video: Boolean(item.has_video),
        image_count: item.image_count || 0,
      },
    }));
  return {
    schema_version: "v1",
    collector_run_id: collectorRunId,
    event_index: args.eventIndex,
    source_project: args.sourceProject,
    capture_method: "rebrowser_x_notifications",
    captured_at: capturedAt,
    page_url: states.at(-1)?.page_url || "https://x.com/notifications",
    page_title: states.at(-1)?.page_title || "Notifications / X",
    context: {
      producer: { name: PRODUCER_NAME, version: PRODUCER_VERSION },
      expected_account: args.expectedAccount || "",
      start_url: "https://x.com/notifications",
      final_url: states.at(-1)?.page_url || "",
      notifications: allNotifications,
      body_text_sample: truncate(states.at(-1)?.body_text_sample || ""),
      artifacts,
    },
    posts: Array.from(postsByKey.values()),
    accounts: Array.from(accountsByHandle.values()),
    media,
    web_documents: [],
    user_inputs: userInputs,
    links: allLinks,
    quality: {
      challenge: false,
      partial: false,
      notification_rows_visible: allNotifications.length,
      posts_visible: postsByKey.size,
      accounts_visible: accountsByHandle.size,
      notification_inputs: userInputs.length,
      media_artifacts: media.length,
      notification_text_sha256: sha256Text(notificationText),
    },
    topics: ["x-notifications", "web-osint"],
  };
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    usage();
    return;
  }
  requireConfig(args);

  const helpers = await loadXHelpers(args);
  const chromium = helpers.getChromium();
  const browser = await chromium.connectOverCDP(args.cdpUrl);
  const context = browser.contexts()[0] || await browser.newContext();
  const page = await context.newPage();
  const cdp = await context.newCDPSession(page);
  const controller = helpers.createSlowXController(page, cdp, {
    xDwellMs: [18_000, 30_000],
    xNavigationGapMs: [45_000, 90_000],
  });

  const capturedAt = nowIso();
  const collectorRunId = args.collectorRunId || `rebrowser_x_notifications_${new Date().toISOString().replace(/[-:]/g, "").replace(/\..+/, "Z")}_${crypto.randomBytes(3).toString("hex")}`;
  const localRoot = path.resolve(args.outputDir || path.join(os.tmpdir(), "web-osint-rebrowser-x-notifications", collectorRunId));
  const remoteRoot = args.rpcDataRoot ? `${args.rpcDataRoot.replace(/\/$/, "")}/media/rebrowser-x-notifications/${compactDate()}/${collectorRunId}` : "";
  fs.rmSync(localRoot, { recursive: true, force: true });
  fs.mkdirSync(localRoot, { recursive: true });

  const states = [];
  const media = [];
  const artifacts = [];
  let publishResponse = "";

  try {
    await controller.slowGoto("https://x.com/notifications", {
      reason: "opening X notifications",
      xDwellMs: [20_000, 32_000],
      timeout: 60_000,
    });
    await assertNotXLoginScreen(page);
    const notificationsState = await extractXState(page, { maxItems: args.maxItems, maxPosts: args.timelineItems });
    states.push({ phase: "notifications", ...notificationsState });
    media.push(await screenshotMedia(page, localRoot, remoteRoot, collectorRunId, "notifications", "X notifications page captured through Rebrowser"));

    let clickedGrouped = false;
    if (args.clickFirstGrouped) {
      let grouped = page.locator('[data-testid="cellInnerDiv"]').filter({ hasText: /New post notifications/i }).first();
      for (let i = 0; i < args.notificationScrolls && !(await grouped.count()); i += 1) {
        await controller.gentleReadScroll(430 + i * 80, {
          restMinMs: 7_000,
          restMaxMs: 14_000,
          label: `reading notifications list ${i + 1}`,
        });
        await assertNotXLoginScreen(page);
        const scrolledState = await extractXState(page, { maxItems: args.maxItems, maxPosts: args.timelineItems });
        states.push({ phase: `notifications_scroll_${i + 1}`, ...scrolledState });
        grouped = page.locator('[data-testid="cellInnerDiv"]').filter({ hasText: /New post notifications/i }).first();
      }
      if (await grouped.count()) {
        await controller.click(grouped, { timeout: 15_000 });
        clickedGrouped = true;
        for (let i = 0; i < args.scrolls; i += 1) {
        await controller.gentleReadScroll(520 + i * 90, {
            restMinMs: 8_000,
            restMaxMs: 16_000,
            label: `reading grouped notifications timeline ${i + 1}`,
        });
        await assertNotXLoginScreen(page);
      }
      }
    }

    if (clickedGrouped) {
      const timelineState = await extractXState(page, { maxItems: args.maxItems, maxPosts: args.timelineItems });
      states.push({ phase: "grouped_timeline", ...timelineState });
      media.push(await screenshotMedia(page, localRoot, remoteRoot, collectorRunId, "grouped-timeline", "X grouped new-post notifications timeline captured through Rebrowser"));
    }

    const metadataPath = path.join(localRoot, "metadata", "x-notifications-extraction.json");
    fs.mkdirSync(path.dirname(metadataPath), { recursive: true });
    fs.writeFileSync(metadataPath, JSON.stringify({ collector_run_id: collectorRunId, captured_at: capturedAt, states }, null, 2));
    artifacts.push(artifactDescriptor(metadataPath, localRoot, remoteRoot));

    const event = eventFromCapture(args, capturedAt, collectorRunId, states, media, artifacts);
    const eventPath = path.join(localRoot, "events", `${collectorRunId}.json`);
    fs.mkdirSync(path.dirname(eventPath), { recursive: true });
    fs.writeFileSync(eventPath, JSON.stringify(event, null, 2));
    artifacts.push(artifactDescriptor(eventPath, localRoot, remoteRoot));

    if (args.publish) {
      uploadArtifacts(args, localRoot, remoteRoot);
      rewriteArtifactPaths(event, localRoot, remoteRoot);
      const remoteEventPath = remotePathFor(eventPath, localRoot, remoteRoot);
      fs.writeFileSync(eventPath, JSON.stringify(event, null, 2));
      uploadArtifacts(args, localRoot, remoteRoot);
      publishResponse = publishCaptureEvent(args, event);
      console.log(JSON.stringify({
        ok: true,
        published: true,
        collector_run_id: collectorRunId,
        event_index: args.eventIndex,
        local_event_path: eventPath,
        remote_event_path: remoteEventPath,
        posts: event.posts.length,
        accounts: event.accounts.length,
        user_inputs: event.user_inputs.length,
        media: event.media.length,
        notifications: event.context.notifications.length,
        pandaproxy_response: publishResponse ? JSON.parse(publishResponse) : {},
      }, null, 2));
    } else {
      console.log(JSON.stringify({
        ok: true,
        published: false,
        collector_run_id: collectorRunId,
        event_path: eventPath,
        posts: event.posts.length,
        accounts: event.accounts.length,
        user_inputs: event.user_inputs.length,
        media: event.media.length,
        notifications: event.context.notifications.length,
      }, null, 2));
    }
  } finally {
    await cdp.detach().catch(() => {});
    if (!args.keepTab) await page.close().catch(() => {});
    if (typeof browser.disconnect === "function") {
      browser.disconnect();
    }
  }
}

main().then(() => {
  process.exit(0);
}).catch((error) => {
  console.error(error?.stack || error);
  process.exit(1);
});
