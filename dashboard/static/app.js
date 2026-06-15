const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const state = {
  facets: {},
  activeView: 'live',
  fsPath: '',
};

const widthKey = 'web-osint-dashboard-column-widths-v2';
const savedWidths = JSON.parse(localStorage.getItem(widthKey) || '{}');

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;',
  }[ch]));
}

function fmt(value) {
  if (value === null || value === undefined || value === '') return '';
  if (Array.isArray(value)) return value.join(', ');
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

function fmtNum(value) {
  const n = Number(value || 0);
  return Number.isFinite(n) ? n.toLocaleString() : '0';
}

function fmtBytes(value) {
  const n = Number(value || 0);
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let v = n;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${v.toFixed(i ? 1 : 0)} ${units[i]}`;
}

function fmtDate(value) {
  if (!value) return '';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString();
}

function ageText(seconds) {
  const n = Number(seconds || 0);
  if (n < 60) return `${Math.max(0, Math.round(n))}s`;
  if (n < 3600) return `${Math.round(n / 60)}m`;
  if (n < 86400) return `${Math.round(n / 3600)}h`;
  return `${Math.round(n / 86400)}d`;
}

async function api(path) {
  const res = await fetch(path, { headers: { Accept: 'application/json' } });
  const text = await res.text();
  let data;
  try { data = text ? JSON.parse(text) : {}; }
  catch { data = { error: text }; }
  if (!res.ok) throw new Error(data.error || `${res.status} ${res.statusText}`);
  return data;
}

async function apiPost(path, body) {
  const res = await fetch(path, {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const text = await res.text();
  let data;
  try { data = text ? JSON.parse(text) : {}; }
  catch { data = { error: text }; }
  if (!res.ok) throw new Error(data.error || `${res.status} ${res.statusText}`);
  return data;
}

function params(obj) {
  const out = new URLSearchParams();
  Object.entries(obj).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') out.set(k, v);
  });
  return out.toString();
}

function frame() {
  return $('#frameSelect').value || '24h';
}

function typesenseValue(value) {
  return `\`${String(value).replace(/\\/g, '\\\\').replace(/`/g, '\\`')}\``;
}

function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  localStorage.setItem('web-osint-dashboard-theme', theme);
  $('#themeSwitch').setAttribute('aria-checked', theme === 'dark' ? 'true' : 'false');
}

function initTheme() {
  setTheme(document.documentElement.dataset.theme || 'dark');
  $('#themeSwitch').addEventListener('click', () => {
    setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
  });
}

function card(label, value, foot = '', cls = '') {
  return `<div class="card ${cls}"><div class="label">${escapeHtml(label)}</div><div class="value">${escapeHtml(value)}</div><div class="foot">${escapeHtml(foot)}</div></div>`;
}

function kv(items) {
  return `<dl class="kv-list">${items.map(([k, v, cls]) => `<dt>${escapeHtml(k)}</dt><dd class="${cls || ''}">${escapeHtml(v)}</dd>`).join('')}</dl>`;
}

function statusClass(ok) {
  return ok ? 'status-ok' : 'status-error';
}

function stageLabel(kind) {
  const map = {
    google_search_page: 'Google SERP',
    x_page: 'X page/search',
    web_page: 'Opened page',
    search_result: 'Search result',
    user_input: 'User input',
    x_post: 'X post',
    x_account: 'X account',
    media: 'Media',
    capture: 'Capture',
  };
  return map[kind] || kind || '';
}

function linkCell(url) {
  if (!url) return '';
  const safe = escapeHtml(url);
  if (url.startsWith('http')) return `<a class="linkish" href="${safe}" target="_blank" rel="noreferrer">${safe}</a>`;
  return `<span class="visitedish">${safe}</span>`;
}

function pillList(values) {
  return (values || []).slice(0, 12).map(v => `<span class="pill">${escapeHtml(v)}</span>`).join('');
}

function renderTable(container, columns, rows, options = {}) {
  const id = options.id || 'table';
  const rowClass = options.onRow ? 'row-clickable' : '';
  container.innerHTML = `
    <div class="table-wrap">
      <table data-table-id="${escapeHtml(id)}">
        <thead><tr>${columns.map(col => {
          const width = savedWidths[`${id}:${col.key}`] || col.width || 160;
          return `<th data-key="${escapeHtml(col.key)}" style="width:${width}px;min-width:${width}px">${escapeHtml(col.label)}<span class="resize-handle" data-key="${escapeHtml(col.key)}"></span></th>`;
        }).join('')}</tr></thead>
        <tbody>${(rows || []).map((row, idx) => `<tr class="${rowClass}" data-idx="${idx}">${columns.map(col => {
          const width = savedWidths[`${id}:${col.key}`] || col.width || 160;
          const raw = col.render ? col.render(row) : escapeHtml(fmt(row[col.key]));
          return `<td style="width:${width}px;min-width:${width}px">${raw}</td>`;
        }).join('')}</tr>`).join('')}</tbody>
      </table>
    </div>`;
  const table = $('table', container);
  if (options.onRow) {
    $$('tbody tr', table).forEach(tr => tr.addEventListener('click', () => options.onRow(rows[Number(tr.dataset.idx)])));
  }
  enableResize(table, id);
}

function renderDynamicTable(container, rows, id) {
  const keys = Array.from((rows || []).reduce((set, row) => {
    Object.keys(row || {}).forEach(k => set.add(k));
    return set;
  }, new Set()));
  const columns = keys.map(key => ({
    key,
    label: key.replaceAll('_', ' '),
    width: key.includes('query') || key.includes('text') ? 360 : 160,
    render: row => {
      const value = row[key];
      if (String(key).includes('url')) return linkCell(value || '');
      if (typeof value === 'object' && value !== null) return `<pre class="inline-json">${escapeHtml(JSON.stringify(value, null, 2))}</pre>`;
      return escapeHtml(fmt(value));
    },
  }));
  renderTable(container, columns, rows || [], { id });
}

function enableResize(table, id) {
  $$('th .resize-handle', table).forEach(handle => {
    handle.addEventListener('mousedown', ev => {
      ev.preventDefault();
      ev.stopPropagation();
      const th = handle.closest('th');
      const key = handle.dataset.key;
      const startX = ev.clientX;
      const startW = th.offsetWidth;
      function move(e) {
        const next = Math.max(64, startW + e.clientX - startX);
        savedWidths[`${id}:${key}`] = next;
        localStorage.setItem(widthKey, JSON.stringify(savedWidths));
        const index = Array.from(th.parentElement.children).indexOf(th);
        $$(`tr > *:nth-child(${index + 1})`, table).forEach(cell => {
          cell.style.width = `${next}px`;
          cell.style.minWidth = `${next}px`;
        });
      }
      function up() {
        document.removeEventListener('mousemove', move);
        document.removeEventListener('mouseup', up);
      }
      document.addEventListener('mousemove', move);
      document.addEventListener('mouseup', up);
    });
  });
}

function renderHistogram(container, rows, valueKey = 'rows', labelKey = 'bucket') {
  const data = rows || [];
  const max = Math.max(1, ...data.map(r => Number(r[valueKey] || 0)));
  if (!data.length) {
    container.innerHTML = '<div class="empty">No activity in this timeframe.</div>';
    return;
  }
  container.innerHTML = `<div class="bars">${data.map(row => {
    const value = Number(row[valueKey] || 0);
    const pct = Math.max(2, (value / max) * 100);
    return `<div class="bar-row" title="${escapeHtml(`${fmtDate(row[labelKey])}: ${value}`)}">
      <div class="bar-label">${escapeHtml(shortBucket(row[labelKey]))}</div>
      <div class="bar-track"><div class="bar-fill" style="width:${pct}%"></div></div>
      <div class="bar-value">${escapeHtml(fmtNum(value))}</div>
    </div>`;
  }).join('')}</div>`;
}

function shortBucket(value) {
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString([], { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

function openDetail(title, meta, value) {
  $('#detailTitle').textContent = title || 'Detail';
  $('#detailMeta').textContent = meta || '';
  $('#detailBody').textContent = typeof value === 'string' ? value : JSON.stringify(value, null, 2);
  $('#detailDrawer').classList.add('open');
  $('#detailDrawer').setAttribute('aria-hidden', 'false');
}

async function loadFacets() {
  state.facets = await api('/api/facets');
  fillSelect($('#typesenseProject'), state.facets.source_project, 'All projects');
  fillSelect($('#typesenseKind'), state.facets.source_kind, 'All steps', stageLabel);
}

function fillSelect(select, rows, allLabel, labelFn = x => x) {
  const current = select.value;
  select.innerHTML = `<option value="">${escapeHtml(allLabel)}</option>` + (rows || []).map(r => {
    const label = `${labelFn(r.value)} (${fmtNum(r.rows)})`;
    return `<option value="${escapeHtml(r.value)}">${escapeHtml(label)}</option>`;
  }).join('');
  select.value = current;
}

async function loadLive() {
  const data = await api(`/api/live?${params({ frame: frame() })}`);
  const t = data.totals || {};
  $('#liveCards').innerHTML = [
    card('Evidence rows', fmtNum(t.evidence_rows), `${fmtNum(t.unique_evidence)} unique IDs`),
    card('Last ingest', ageText(t.ingest_age_seconds), fmtDate(t.last_ingested_at), Number(t.ingest_age_seconds || 999999) < 300 ? 'good-card' : 'warn-card'),
    card('Collector runs', fmtNum(t.collector_runs), 'observed runs'),
    card('Media rows', fmtNum(t.media_marked_rows), `${fmtNum(t.ocr_marked_rows)} OCR-marked rows`),
    card('Services', serviceSummary(data.services), 'healthy / total'),
  ].join('');
  renderFlow(data);
  renderHistogram($('#liveHistogram'), data.histogram || []);
  renderTable($('#liveStageRows'), [
    { key: 'source_kind', label: 'Stage', width: 170, render: r => stageLabel(r.source_kind) },
    { key: 'rows', label: 'Rows', width: 100, render: r => fmtNum(r.rows) },
    { key: 'last_ingested_at', label: 'Last Ingested', width: 190, render: r => fmtDate(r.last_ingested_at) },
  ], data.stage_rows || [], { id: 'live-stage-rows' });
  renderTable($('#liveRuns'), runColumns(), data.latest_runs || [], { id: 'live-runs' });
}

function serviceSummary(services) {
  const vals = Object.values(services || {});
  const ok = vals.filter(v => v && v.ok).length;
  return `${ok}/${vals.length}`;
}

function renderFlow(data) {
  const services = data.services || {};
  const steps = [
    ['Collectors', true, 'runs'],
    ['Redpanda', services.redpanda?.ok, 'topics'],
    ['Worker', services.normalizer?.ok, 'materialize'],
    ['Meaning', services.normalizer?.ok, `${fmtNum(services.normalizer?.data?.labels_emitted || 0)} labels`],
    ['Research', services.research_planner?.ok, `${fmtNum(services.research_planner?.data?.tasks_created || 0)} tasks`],
    ['Filesystem', services.filesystem?.ok, 'media/OCR'],
    ['Pebble', services.normalizer?.ok, 'exact lookup'],
    ['Typesense', services.typesense?.ok, 'keyword'],
    ['Qdrant', services.qdrant?.ok, `${fmtNum(services.qdrant?.data?.result?.points_count || 0)} points`],
    ['ClickHouse', services.clickhouse?.ok, 'analytics'],
  ];
  $('#flowRail').innerHTML = steps.map(([name, ok, foot], idx) => `
    <div class="flow-step ${ok ? 'ok' : 'bad'}">
      <div class="flow-index">${idx + 1}</div>
      <div class="flow-name">${escapeHtml(name)}</div>
      <div class="flow-foot">${escapeHtml(foot)}</div>
    </div>`).join('');
}

function runColumns() {
  return [
    { key: 'updated_at', label: 'Updated', width: 176, render: r => fmtDate(r.updated_at) },
    { key: 'source_project', label: 'Project', width: 140 },
    { key: 'capture_method', label: 'Method', width: 220 },
    { key: 'collector_run_id', label: 'Run ID', width: 360 },
    { key: 'records_seen', label: 'Seen', width: 90, render: r => fmtNum(r.records_seen) },
    { key: 'records_emitted', label: 'Emitted', width: 100, render: r => fmtNum(r.records_emitted) },
    { key: 'challenge', label: 'Challenge', width: 100, render: r => r.challenge ? 'yes' : '' },
    { key: 'partial', label: 'Partial', width: 90, render: r => r.partial ? 'yes' : '' },
  ];
}

async function loadCollectors() {
  const data = await api(`/api/stage/collectors?${params({ frame: frame() })}`);
  const runs = data.runs || [];
  $('#collectorCards').innerHTML = [
    card('Runs', fmtNum(runs.length), 'collector batches'),
    card('Seen', fmtNum(runs.reduce((sum, r) => sum + Number(r.records_seen || 0), 0)), 'records seen'),
    card('Emitted', fmtNum(runs.reduce((sum, r) => sum + Number(r.records_emitted || 0), 0)), 'records emitted'),
    card('Challenges', fmtNum(runs.filter(r => r.challenge).length), 'flagged runs'),
  ].join('');
  renderHistogram($('#collectorHistogram'), data.histogram || []);
  renderTable($('#collectorRuns'), runColumns(), runs, { id: 'collector-runs', onRow: row => openDetail(row.collector_run_id, 'Collector run', row) });
  renderTable($('#collectorMethods'), [
    { key: 'source_project', label: 'Project', width: 150 },
    { key: 'capture_method', label: 'Method', width: 260 },
    { key: 'run_rows', label: 'Rows', width: 90, render: r => fmtNum(r.run_rows) },
    { key: 'records_seen', label: 'Seen', width: 90, render: r => fmtNum(r.records_seen) },
    { key: 'records_emitted', label: 'Emitted', width: 100, render: r => fmtNum(r.records_emitted) },
    { key: 'last_seen', label: 'Last Seen', width: 180, render: r => fmtDate(r.last_seen) },
  ], data.by_method || [], { id: 'collector-methods' });
}

async function loadStream() {
  const data = await api('/api/stage/redpanda');
  const normalizer = data.normalizer?.data || {};
  const planner = data.research_planner?.data || {};
  $('#streamCards').innerHTML = [
    card('Topics', fmtNum((data.topics || []).filter(t => !t.internal).length), 'Kafka namespace'),
    card('Brokers', fmtNum((data.brokers || []).length), 'active nodes'),
    card('Processed', fmtNum(normalizer.processed), 'worker counter'),
    card('Failures', fmtNum(normalizer.failed), 'worker counter', Number(normalizer.failed || 0) ? 'bad-card' : 'good-card'),
    card('Planner tasks', fmtNum(planner.tasks_created), `${fmtNum(planner.signals_created)} signals`),
    card('Pebble keys', fmtNum(data.pebble?.data?.total_keys), 'materialized exact state'),
  ].join('');
  renderHistogram($('#streamHistogram'), data.activity || []);
  renderTable($('#streamTopics'), [
    { key: 'topic', label: 'Topic', width: 270 },
    { key: 'partitions', label: 'Partitions', width: 100, render: r => fmtNum(r.partitions) },
    { key: 'leaders', label: 'Leaders', width: 100 },
    { key: 'cores', label: 'Cores', width: 90 },
    { key: 'internal', label: 'Internal', width: 90, render: r => r.internal ? 'yes' : '' },
  ], data.topics || [], { id: 'stream-topics' });
  $('#streamWorker').innerHTML = kv([
    ['Processed', fmtNum(normalizer.processed)],
    ['Failed', fmtNum(normalizer.failed), normalizer.failed ? 'status-error' : 'status-ok'],
    ['Posts indexed', fmtNum(normalizer.posts_indexed)],
    ['Accounts indexed', fmtNum(normalizer.accounts_indexed)],
    ['Media indexed', fmtNum(normalizer.media_indexed)],
    ['Search indexed', fmtNum(normalizer.search_indexed)],
    ['Labels emitted', fmtNum(normalizer.labels_emitted)],
    ['Planner runs', fmtNum(planner.runs)],
    ['Planner failed', fmtNum(planner.failed), planner.failed ? 'status-error' : 'status-ok'],
    ['Signals created', fmtNum(planner.signals_created)],
    ['Questions created', fmtNum(planner.questions_created)],
    ['Tasks created', fmtNum(planner.tasks_created)],
    ['Planner last run', fmtDate(planner.last_run_at)],
  ]);
  renderTable($('#streamMetrics'), [
    { key: 'key', label: 'Topic', width: 280 },
    { key: 'value', label: 'Request bytes', width: 160, render: r => fmtBytes(r.value) },
  ], data.bytes_by_topic || [], { id: 'stream-metrics' });
}

async function loadFilesystem(path = state.fsPath) {
  const data = await api(`/api/stage/filesystem?${params({ frame: frame() })}`);
  $('#fsCards').innerHTML = [
    card('Files', fmtNum(data.total_files), 'media/OCR roots'),
    card('Bytes', fmtBytes(data.total_bytes), 'artifact storage'),
    ...((data.roots || []).map(root => card(root.root.split('/').pop(), fmtNum(root.files), fmtBytes(root.bytes)))),
  ].join('');
  renderHistogram($('#fsHistogram'), data.histogram || [], 'files');
  renderGallery(data.recent || []);
  await loadFsTree(path || data.roots?.[0]?.root || '');
}

async function loadFsTree(path = '') {
  const data = await api(`/api/stage/fs-tree?${params({ path })}`);
  state.fsPath = data.root;
  $('#fsCrumbs').innerHTML = `${escapeHtml(data.root)} ${data.parent ? `<button class="tiny" data-path="${escapeHtml(data.parent)}">Up</button>` : ''}`;
  $('#fsTree').innerHTML = (data.entries || []).map(entry => `
    <button class="tree-row ${entry.type}" data-path="${escapeHtml(entry.path)}" data-type="${escapeHtml(entry.type)}">
      <span>${entry.type === 'dir' ? '▸' : '•'}</span>
      <span>${escapeHtml(entry.name)}</span>
      <span>${entry.type === 'file' ? escapeHtml(fmtBytes(entry.bytes)) : ''}</span>
    </button>`).join('');
  $$('#fsCrumbs button, #fsTree .tree-row').forEach(btn => btn.addEventListener('click', () => {
    if (btn.dataset.type === 'file') viewFsFile(btn.dataset.path);
    else loadFsTree(btn.dataset.path);
  }));
}

async function viewFsFile(path) {
  const url = `/api/stage/fs-file?${params({ path })}`;
  const ext = path.split('.').pop().toLowerCase();
  if (['png', 'jpg', 'jpeg', 'webp', 'gif'].includes(ext)) {
    $('#fsViewer').innerHTML = `<img src="${escapeHtml(url)}" alt="">`;
    return;
  }
  const data = await api(url);
  $('#fsViewer').innerHTML = `<div class="meta-line">${escapeHtml(data.path)} · ${escapeHtml(fmtBytes(data.bytes))}${data.truncated ? ' · truncated' : ''}</div><pre class="json-box">${escapeHtml(data.text || '')}</pre>`;
}

function renderGallery(rows) {
  $('#fsGallery').innerHTML = rows.map(row => {
    const isImage = row.kind === 'image';
    const url = `/api/stage/fs-file?${params({ path: row.path })}`;
    return `<article class="media-card">
      ${isImage ? `<img loading="lazy" src="${escapeHtml(url)}" alt="">` : '<div class="file-tile">FILE</div>'}
      <div class="media-body">
        <strong>${escapeHtml(row.name)}</strong>
        <div class="meta-line">${escapeHtml(fmtDate(row.modified_at))} · ${escapeHtml(fmtBytes(row.bytes))}</div>
        <button data-path="${escapeHtml(row.path)}" class="fs-open">Open</button>
      </div>
    </article>`;
  }).join('');
  $$('.fs-open').forEach(btn => btn.addEventListener('click', () => viewFsFile(btn.dataset.path)));
}

async function loadPebble() {
  const data = await api('/api/stage/pebble');
  $('#pebbleCards').innerHTML = [
    card('Keys', fmtNum(data.total_keys), 'materialized state entries'),
    card('Value bytes', fmtBytes(data.total_value_bytes), 'JSON envelopes'),
    card('Prefixes', fmtNum((data.prefixes || []).length), 'key families'),
  ].join('');
  renderTable($('#pebblePrefixes'), [
    { key: 'prefix', label: 'Prefix', width: 130 },
    { key: 'keys', label: 'Keys', width: 90, render: r => fmtNum(r.keys) },
    { key: 'value_bytes', label: 'Value bytes', width: 130, render: r => fmtBytes(r.value_bytes) },
    { key: 'samples', label: 'Samples', width: 420, render: r => pillList(r.samples) },
  ], data.prefixes || [], { id: 'pebble-prefixes' });
  renderTable($('#pebbleKeys'), [{ key: 'key', label: 'Key', width: 520 }], (data.sample_keys || []).map(key => ({ key })), { id: 'pebble-keys' });
  $('#pebbleRaw').textContent = JSON.stringify(data.metrics || {}, null, 2);
}

async function loadTypesenseStage() {
  const data = await api(`/api/stage/typesense?${params({ frame: frame() })}`);
  const c = data.collection || {};
  const s = data.stats || {};
  $('#typesenseCards').innerHTML = [
    card('Health', data.health?.ok ? 'ok' : 'down', 'Typesense API', data.health?.ok ? 'good-card' : 'bad-card'),
    card('Documents', fmtNum(c.num_documents), c.name || 'evidence_posts'),
    card('Search latency', `${fmtNum(s.search_latency_ms)} ms`, 'current stat'),
    card('Requests/sec', fmtNum(s.total_requests_per_second), 'current stat'),
    card('Pending writes', fmtNum(s.pending_write_batches), 'write queue', Number(s.pending_write_batches || 0) ? 'warn-card' : ''),
  ].join('');
  renderHistogram($('#typesenseHistogram'), data.histogram || []);
  renderDynamicTable($('#typesenseSchema'), c.fields || [], 'typesense-schema');
  await loadTypesenseSearch();
}

async function loadTypesenseSearch() {
  const filter = [];
  if ($('#typesenseProject').value) filter.push(`source_projects:=${typesenseValue($('#typesenseProject').value)}`);
  if ($('#typesenseKind').value) filter.push(`source_kind:=${typesenseValue($('#typesenseKind').value)}`);
  const data = await api(`/api/search?${params({ q: $('#typesenseQ').value.trim() || '*', filter_by: filter.join(' && '), per_page: 50 })}`);
  $('#typesenseMeta').textContent = `${fmtNum(data.found)} matching Typesense documents.`;
  const rows = (data.hits || []).map(h => ({ score: h.text_match, ...(h.document || {}) }));
  renderTable($('#typesenseTable'), [
    { key: 'score', label: 'Score', width: 110 },
    { key: 'source_kind', label: 'Stage', width: 150, render: r => stageLabel(r.source_kind) },
    { key: 'source_projects', label: 'Project', width: 150, render: r => fmt(r.source_projects) },
    { key: 'id', label: 'ID', width: 260 },
    { key: 'canonical_url', label: 'URL', width: 300, render: r => linkCell(r.canonical_url) },
    { key: 'author_handle', label: 'Author', width: 140 },
    { key: 'text', label: 'Text', width: 460, render: r => `<div class="cell-snippet">${escapeHtml(r.text || '')}</div>` },
    { key: 'topics', label: 'Topics', width: 220, render: r => pillList(r.topics) },
  ], rows, { id: 'typesense-search', onRow: row => openDetail(row.id, 'Typesense document', row) });
}

async function loadQdrantStage() {
  const data = await api(`/api/stage/qdrant?${params({ frame: frame() })}`);
  const result = data.collection?.result || {};
  const paramsObj = result.config?.params || {};
  $('#qdrantCards').innerHTML = [
    card('Status', result.status || data.collection?.status || '', 'collection', result.status === 'green' ? 'good-card' : 'warn-card'),
    card('Points', fmtNum(result.points_count), 'payload points'),
    card('Indexed vectors', fmtNum(result.indexed_vectors_count), 'HNSW indexed'),
    card('Segments', fmtNum(result.segments_count), 'storage segments'),
    card('Update queue', fmtNum(result.update_queue?.length), 'pending updates'),
  ].join('');
  renderHistogram($('#qdrantHistogram'), data.histogram || []);
  renderDynamicTable($('#qdrantVectors'), Object.entries(paramsObj.vectors || {}).map(([name, cfg]) => ({ name, ...cfg })), 'qdrant-vectors');
  renderDynamicTable($('#qdrantPayload'), Object.entries(result.payload_schema || {}).map(([field, cfg]) => ({ field, ...cfg })), 'qdrant-payload');
  renderDynamicTable($('#qdrantMetrics'), data.metrics || [], 'qdrant-metrics');
}

async function loadClickHouseStage() {
  const data = await api(`/api/stage/clickhouse?${params({ frame: frame() })}`);
  const t = data.totals || {};
  $('#clickhouseCards').innerHTML = [
    card('Rows', fmtNum(t.evidence_rows), `${fmtNum(t.unique_evidence)} unique IDs`),
    card('Runs', fmtNum(t.collector_runs), 'collector runs'),
    card('Last ingest', fmtDate(t.last_ingested_at), 'ClickHouse evidence_events'),
    card('Tables', fmtNum((data.tables || []).length), 'ClickHouse database'),
  ].join('');
  renderHistogram($('#clickhouseHistogram'), data.histogram || []);
  renderTable($('#clickhouseTables'), [
    { key: 'name', label: 'Table', width: 230 },
    { key: 'total_rows', label: 'Rows', width: 120, render: r => fmtNum(r.total_rows) },
    { key: 'total_bytes', label: 'Bytes', width: 130, render: r => fmtBytes(r.total_bytes) },
  ], data.tables || [], { id: 'clickhouse-tables' });
  renderDynamicTable($('#clickhouseMetrics'), [...(data.metrics || []), ...(data.asynchronous_metrics || [])], 'clickhouse-metrics');
  await runClickHouseQuery();
}

async function runClickHouseQuery() {
  $('#chQueryMeta').textContent = 'Running...';
  try {
    const data = await apiPost('/api/clickhouse/query', { query: $('#chQuery').value });
    $('#chQueryMeta').textContent = `${fmtNum(data.rows || data.data?.length || 0)} rows.`;
    renderDynamicTable($('#chQueryTable'), data.data || [], 'clickhouse-query');
  } catch (err) {
    $('#chQueryMeta').textContent = err.message;
    $('#chQueryTable').innerHTML = '';
  }
}

async function loadMeaningStage() {
  const data = await api(`/api/stage/meaning?${params({ frame: frame() })}`);
  const t = data.totals || {};
  $('#meaningCards').innerHTML = [
    card('Annotations', fmtNum(t.annotations), `${fmtNum(t.annotated_evidence)} evidence IDs`),
    card('Labels', fmtNum(t.unique_labels), 'unique label ids'),
    card('Accepted', fmtNum(t.accepted), `${fmtNum(t.proposed)} proposed`),
    card('Avg confidence', Number(t.avg_confidence || 0).toFixed(3), 'semantic_annotations'),
    card('Last label', fmtDate(t.last_annotation_at), 'latest annotation'),
  ].join('');
  renderHistogram($('#meaningHistogram'), data.histogram || []);
  renderTable($('#meaningFamilies'), [
    { key: 'annotation_family', label: 'Family', width: 170 },
    { key: 'annotations', label: 'Annotations', width: 120, render: r => fmtNum(r.annotations) },
    { key: 'labels', label: 'Labels', width: 90, render: r => fmtNum(r.labels) },
    { key: 'evidence', label: 'Evidence', width: 100, render: r => fmtNum(r.evidence) },
    { key: 'avg_confidence', label: 'Avg conf', width: 100 },
    { key: 'last_seen', label: 'Last Seen', width: 180, render: r => fmtDate(r.last_seen) },
  ], data.by_family || [], { id: 'meaning-families' });
  renderTable($('#meaningLabels'), [
    { key: 'annotation_family', label: 'Family', width: 150 },
    { key: 'label_id', label: 'Label', width: 260 },
    { key: 'status', label: 'Status', width: 110 },
    { key: 'annotations', label: 'Rows', width: 90, render: r => fmtNum(r.annotations) },
    { key: 'evidence', label: 'Evidence', width: 100, render: r => fmtNum(r.evidence) },
    { key: 'avg_confidence', label: 'Avg conf', width: 100 },
    { key: 'last_seen', label: 'Last Seen', width: 180, render: r => fmtDate(r.last_seen) },
  ], data.top_labels || [], { id: 'meaning-labels' });
  renderTable($('#meaningRecent'), [
    { key: 'created_at', label: 'Created', width: 180, render: r => fmtDate(r.created_at) },
    { key: 'annotation_family', label: 'Family', width: 150 },
    { key: 'label_id', label: 'Label', width: 260 },
    { key: 'status', label: 'Status', width: 110 },
    { key: 'confidence', label: 'Conf', width: 90 },
    { key: 'evidence_id', label: 'Evidence ID', width: 260 },
    { key: 'target_type', label: 'Target', width: 120 },
    { key: 'value_json', label: 'Value', width: 360, render: r => `<pre class="inline-json">${escapeHtml(r.value_json || '')}</pre>` },
  ], data.recent || [], { id: 'meaning-recent', onRow: row => openDetail(row.annotation_id || row.label_id, 'Semantic annotation', row) });
  renderTable($('#meaningQuestions'), [
    { key: 'created_at', label: 'Created', width: 180, render: r => fmtDate(r.created_at) },
    { key: 'status', label: 'Status', width: 110 },
    { key: 'priority', label: 'Priority', width: 90 },
    { key: 'question_type', label: 'Type', width: 160 },
    { key: 'question_text', label: 'Question', width: 520 },
    { key: 'rationale', label: 'Rationale', width: 460 },
  ], data.research_questions || [], { id: 'meaning-questions', onRow: row => openDetail(row.question_id, 'Research question', row) });
  renderTable($('#meaningTasks'), [
    { key: 'created_at', label: 'Created', width: 180, render: r => fmtDate(r.created_at) },
    { key: 'status', label: 'Status', width: 110 },
    { key: 'priority', label: 'Priority', width: 90 },
    { key: 'task_type', label: 'Task', width: 180 },
    { key: 'question_id', label: 'Question ID', width: 260 },
    { key: 'dedupe_key', label: 'Dedupe', width: 300 },
    { key: 'rationale', label: 'Rationale', width: 460 },
  ], data.autonomous_tasks || [], { id: 'meaning-tasks', onRow: row => openDetail(row.task_id, 'Autonomous task', row) });
  renderTable($('#meaningSignals'), [
    { key: 'created_at', label: 'Created', width: 180, render: r => fmtDate(r.created_at) },
    { key: 'signal_type', label: 'Signal', width: 180 },
    { key: 'primary_entity_id', label: 'Entity', width: 220 },
    { key: 'topic_label_id', label: 'Topic', width: 220 },
    { key: 'signal_summary', label: 'Summary', width: 520 },
    { key: 'novelty_score', label: 'Novelty', width: 90 },
    { key: 'uncertainty_score', label: 'Uncertainty', width: 110 },
    { key: 'impact_score', label: 'Impact', width: 90 },
  ], data.research_signals || [], { id: 'meaning-signals', onRow: row => openDetail(row.signal_type, 'Research signal', row) });
}

function activateView(id) {
  state.activeView = id;
  $$('.tab').forEach(tab => tab.classList.toggle('active', tab.dataset.view === id));
  $$('.view').forEach(view => view.classList.toggle('active', view.id === id));
  loadActive();
}

function loadActive() {
  const id = state.activeView;
  if (id === 'live') return loadLive();
  if (id === 'collectors') return loadCollectors();
  if (id === 'stream') return loadStream();
  if (id === 'filesystem') return loadFilesystem();
  if (id === 'pebble') return loadPebble();
  if (id === 'typesense') return loadTypesenseStage();
  if (id === 'qdrant') return loadQdrantStage();
  if (id === 'meaning') return loadMeaningStage();
  if (id === 'clickhouse') return loadClickHouseStage();
}

function bindEvents() {
  $$('.tab').forEach(tab => tab.addEventListener('click', () => activateView(tab.dataset.view)));
  $('#refreshAll').addEventListener('click', () => loadActive());
  $('#frameSelect').addEventListener('change', () => loadActive());
  $('#detailClose').addEventListener('click', () => {
    $('#detailDrawer').classList.remove('open');
    $('#detailDrawer').setAttribute('aria-hidden', 'true');
  });
  $('#typesenseGo').addEventListener('click', loadTypesenseSearch);
  $('#typesenseQ').addEventListener('keydown', ev => { if (ev.key === 'Enter') loadTypesenseSearch(); });
  $('#typesenseProject').addEventListener('change', loadTypesenseSearch);
  $('#typesenseKind').addEventListener('change', loadTypesenseSearch);
  $('#chRun').addEventListener('click', runClickHouseQuery);
  $('#chPlay').addEventListener('click', () => { $('#clickhouseFrame').src = '/clickhouse/play'; });
  $('#chDashboard').addEventListener('click', () => { $('#clickhouseFrame').src = '/clickhouse/dashboard'; });
  $('#chClickstack').addEventListener('click', () => { $('#clickhouseFrame').src = '/clickhouse/clickstack'; });
}

async function boot() {
  initTheme();
  bindEvents();
  await loadFacets();
  await loadLive();
}

boot().catch(err => {
  document.body.insertAdjacentHTML('afterbegin', `<div class="panel status-error">Dashboard failed to load: ${escapeHtml(err.message)}</div>`);
});
