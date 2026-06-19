const state = {
  queue: 'all',
  kind: '',
  project: '',
  q: '',
  limit: '80',
  selectedId: '',
  rows: [],
  facets: null,
};

const $ = (id) => document.getElementById(id);

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;'
  })[char]);
}

function fmtDate(value) {
  if (!value) return '';
  return String(value).replace('T', ' ').replace(/Z$/, '');
}

function titleFor(row) {
  return row.title || row.canonical_url || row.evidence_id || '(untitled source)';
}

async function fetchJson(url) {
  const response = await fetch(url, { cache: 'no-store' });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || response.statusText);
  return data;
}

function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  localStorage.setItem('web-osint-research-theme', theme);
  $('themeSwitch').setAttribute('aria-checked', theme === 'dark' ? 'true' : 'false');
}

function renderFacets(data) {
  state.facets = data;
  const totals = data.totals || {};
  $('totals').textContent = `${totals.unique_evidence ?? 0} unique sources · ${totals.evidence_rows ?? 0} rows · last ingest ${fmtDate(totals.last_ingested_at)}`;

  $('queueList').innerHTML = (data.queues || []).map((queue) => `
    <button class="queue ${state.queue === queue.id ? 'active' : ''}" data-queue="${escapeHtml(queue.id)}">
      <span>${escapeHtml(queue.label)}</span>
    </button>
  `).join('');
  $('kindList').innerHTML = [
    `<button class="facet ${state.kind === '' ? 'active' : ''}" data-kind=""><span>All source types</span><span class="count">${totals.evidence_rows ?? ''}</span></button>`,
    ...(data.source_kinds || []).map((row) => `
      <button class="facet ${state.kind === row.source_kind ? 'active' : ''}" data-kind="${escapeHtml(row.source_kind)}">
        <span>${escapeHtml(row.source_kind)}</span><span class="count">${row.rows}</span>
      </button>
    `)
  ].join('');
  $('domainList').innerHTML = (data.domains || []).map((row) => `
    <button class="facet" data-domain="${escapeHtml(row.domain)}">
      <span>${escapeHtml(row.domain)}</span><span class="count">${row.rows}</span>
    </button>
  `).join('');

  const currentProject = state.project;
  $('projectSelect').innerHTML = `<option value="">All projects</option>` + (data.projects || []).map((row) => (
    `<option value="${escapeHtml(row.source_project)}">${escapeHtml(row.source_project || '(blank)')} (${row.rows})</option>`
  )).join('');
  $('projectSelect').value = currentProject;

  document.querySelectorAll('[data-queue]').forEach((button) => {
    button.addEventListener('click', () => {
      state.queue = button.dataset.queue || 'all';
      loadInbox();
      renderFacets(state.facets);
    });
  });
  document.querySelectorAll('[data-kind]').forEach((button) => {
    button.addEventListener('click', () => {
      state.kind = button.dataset.kind || '';
      loadInbox();
      renderFacets(state.facets);
    });
  });
  document.querySelectorAll('[data-domain]').forEach((button) => {
    button.addEventListener('click', () => {
      $('searchInput').value = button.dataset.domain || '';
      state.q = $('searchInput').value;
      loadInbox();
    });
  });
}

function renderInbox(rows) {
  state.rows = rows;
  if (!rows.length) {
    $('inboxRows').innerHTML = `<div class="empty-state"><h2>No sources</h2><p>Try a different queue or search.</p></div>`;
    return;
  }
  $('inboxRows').innerHTML = rows.map((row) => `
    <article class="row ${state.selectedId === row.evidence_id ? 'active' : ''}" data-id="${escapeHtml(row.evidence_id)}">
      <div class="row-title">${escapeHtml(titleFor(row))}</div>
      <div class="row-meta">
        <span class="pill">${escapeHtml(row.source_label || row.source_kind)}</span>
        ${row.author_handle ? `<span class="pill">@${escapeHtml(row.author_handle)}</span>` : ''}
        ${row.domain ? `<span class="pill">${escapeHtml(row.domain)}</span>` : ''}
        ${row.has_media ? `<span class="pill ok">media</span>` : ''}
        ${row.has_ocr ? `<span class="pill ok">OCR</span>` : ''}
        <span class="pill warn">${escapeHtml(row.review_hint || 'triage')}</span>
      </div>
      <div class="row-snippet">${escapeHtml(row.snippet || row.canonical_url || row.evidence_id)}</div>
      <div class="muted">${fmtDate(row.last_ingested_at)} · ${row.text_chars || 0} chars · ${row.observations || 0} observation(s)</div>
    </article>
  `).join('');
  document.querySelectorAll('.row[data-id]').forEach((row) => {
    row.addEventListener('click', () => selectSource(row.dataset.id));
  });
}

async function loadFacets() {
  renderFacets(await fetchJson('/api/facets'));
}

async function loadInbox() {
  const params = new URLSearchParams({
    queue: state.queue,
    limit: state.limit,
  });
  if (state.kind) params.set('kind', state.kind);
  if (state.project) params.set('project', state.project);
  if (state.q) params.set('q', state.q);
  $('inboxRows').innerHTML = `<div class="empty-state"><h2>Loading</h2><p>Reading the evidence inbox.</p></div>`;
  try {
    const data = await fetchJson(`/api/inbox?${params.toString()}`);
    renderInbox(data.rows || []);
  } catch (error) {
    $('inboxRows').innerHTML = `<div class="empty-state"><h2>Inbox error</h2><p>${escapeHtml(error.message)}</p></div>`;
  }
}

function renderKv(items) {
  return `<dl class="kv">${items.map(([key, value]) => `
    <dt>${escapeHtml(key)}</dt><dd>${value || value === 0 ? escapeHtml(value) : ''}</dd>
  `).join('')}</dl>`;
}

function renderNormalized(source) {
  const latest = source.latest || {};
  const links = (latest.links || []).map((link) => `<a href="${escapeHtml(link)}" target="_blank" rel="noreferrer">${escapeHtml(link)}</a>`).join('<br>');
  $('tab-normalized').innerHTML = `
    ${renderKv([
      ['Evidence ID', latest.evidence_id],
      ['Collector run', latest.collector_run_id],
      ['Capture method', latest.capture_method],
      ['Project', latest.source_project],
      ['Author / domain', [latest.author_handle ? '@' + latest.author_handle : '', latest.domain].filter(Boolean).join(' · ')],
      ['Captured', fmtDate(latest.captured_at)],
      ['Ingested', fmtDate(latest.ingested_at)],
      ['Topics', (latest.topics || []).join(', ')],
      ['Entities', (latest.entities || []).join(', ')],
    ])}
    ${links ? `<h3>Links</h3><p>${links}</p>` : ''}
    <h3>Normalized text</h3>
    <div class="source-text">${escapeHtml(latest.text || '(no extracted text)')}</div>
  `;
}

function renderArtifacts(source) {
  const latest = source.latest || {};
  const artifacts = latest.artifact_paths || [];
  if (!artifacts.length) {
    $('tab-artifacts').innerHTML = `<div class="empty-state"><h2>No artifacts</h2><p>No local artifact paths were found in this source row.</p></div>`;
    return;
  }
  $('tab-artifacts').innerHTML = `<div class="cards">${artifacts.map((artifact) => {
    const isImage = /\.(png|jpg|jpeg|gif|webp)$/i.test(artifact.path);
    return `
      <div class="card">
        <h3>${escapeHtml(artifact.path.split('/').pop())}</h3>
        <p><a href="${escapeHtml(artifact.url)}" target="_blank" rel="noreferrer">${escapeHtml(artifact.path)}</a></p>
        ${isImage ? `<img class="artifact-img" src="${escapeHtml(artifact.url)}" alt="">` : ''}
      </div>
    `;
  }).join('')}</div>`;
}

function renderEnrichment(source) {
  const annotations = source.annotations || [];
  const ocr = source.ocr || [];
  const vl = source.vl || [];
  $('tab-enrichment').innerHTML = `
    <div class="cards">
      <div class="card"><h3>Semantic annotations (${annotations.length})</h3>${annotations.length ? annotations.map((row) => `
        <p><strong>${escapeHtml(row.annotation_family)} / ${escapeHtml(row.label_id)}</strong> · ${escapeHtml(row.status)} · ${row.confidence}</p>
        ${row.span_text ? `<p>${escapeHtml(row.span_text)}</p>` : ''}
      `).join('') : '<p class="muted">No annotations for this source yet.</p>'}</div>
      <div class="card"><h3>OCR outputs (${ocr.length})</h3>${ocr.length ? ocr.map((row) => `
        <p><strong>${escapeHtml(row.engine)} ${escapeHtml(row.engine_version)}</strong> · ${escapeHtml(row.status)} · ${row.text_chars} chars · confidence ${row.mean_confidence}</p>
        ${row.text_artifact_path_url ? `<p><a href="${escapeHtml(row.text_artifact_path_url)}" target="_blank" rel="noreferrer">OCR text artifact</a></p>` : ''}
      `).join('') : '<p class="muted">No OCR rows for this source yet.</p>'}</div>
      <div class="card"><h3>VL embeddings (${vl.length})</h3>${vl.length ? vl.map((row) => `
        <p><strong>${escapeHtml(row.model)}</strong> · ${escapeHtml(row.status)} · ${escapeHtml(row.vector_name)} · ${row.image_width}×${row.image_height}</p>
        <p class="muted">${escapeHtml(row.qdrant_collection)} / ${escapeHtml(row.qdrant_point_id)}</p>
      `).join('') : '<p class="muted">No VL rows for this source yet.</p>'}</div>
    </div>
  `;
}

function renderRelated(source) {
  const related = source.related || [];
  $('tab-related').innerHTML = related.length ? `<div class="cards">${related.map((row) => `
    <button class="card related-card" data-id="${escapeHtml(row.evidence_id)}">
      <h3>${escapeHtml(row.title || row.canonical_url || row.evidence_id)}</h3>
      <p>${escapeHtml(row.source_label || row.source_kind)} · ${escapeHtml(row.author_handle || row.domain || '')}</p>
      <p class="muted">${fmtDate(row.last_ingested_at)} · ${row.text_chars || 0} chars</p>
    </button>
  `).join('')}</div>` : `<div class="empty-state"><h2>No related rows</h2><p>No matching URL, author, or domain rows were found.</p></div>`;
  document.querySelectorAll('.related-card').forEach((button) => {
    button.addEventListener('click', () => selectSource(button.dataset.id));
  });
}

function renderNotes(source) {
  const id = source.latest?.evidence_id || '';
  const key = `web-osint-research-note:${id}`;
  const note = localStorage.getItem(key) || '';
  $('tab-notes').innerHTML = `
    <h3>Local review note</h3>
    <p class="muted">Temporary browser-local notes for first-pass review. Durable annotation storage comes next.</p>
    <textarea id="noteText" placeholder="Evidence selection, correction, claim, entity link, publication thought...">${escapeHtml(note)}</textarea>
    <div class="top-actions" style="margin-top:8px">
      <button id="saveNote">Save note locally</button>
      <button id="clearNote" class="secondary">Clear</button>
    </div>
  `;
  $('saveNote').addEventListener('click', () => localStorage.setItem(key, $('noteText').value));
  $('clearNote').addEventListener('click', () => {
    localStorage.removeItem(key);
    $('noteText').value = '';
  });
}

function renderRaw(source) {
  $('tab-raw').innerHTML = `<pre>${escapeHtml(JSON.stringify({
    latest: source.latest,
    observations: source.observations,
  }, null, 2))}</pre>`;
}

async function selectSource(id) {
  state.selectedId = id;
  $('sourceEmpty').classList.add('hidden');
  $('sourceView').classList.remove('hidden');
  $('sourceTitle').textContent = 'Loading source...';
  try {
    const source = await fetchJson(`/api/source?id=${encodeURIComponent(id)}`);
    const latest = source.latest || {};
    $('sourceKind').textContent = latest.source_kind || 'source';
    $('sourceTitle').textContent = latest.title || latest.canonical_url || latest.evidence_id || '(untitled source)';
    $('sourceUrl').textContent = latest.canonical_url || '';
    $('sourceUrl').href = latest.canonical_url || '#';
    $('sourceMeta').textContent = `${latest.author_handle ? '@' + latest.author_handle + ' · ' : ''}${latest.domain || ''} · ${fmtDate(latest.captured_at)}`;
    renderNormalized(source);
    renderArtifacts(source);
    renderEnrichment(source);
    renderRelated(source);
    renderRaw(source);
    renderNotes(source);
    document.querySelectorAll('.row').forEach((row) => row.classList.toggle('active', row.dataset.id === id));
  } catch (error) {
    $('sourceTitle').textContent = 'Source error';
    $('tab-normalized').innerHTML = `<div class="empty-state"><h2>Failed to load source</h2><p>${escapeHtml(error.message)}</p></div>`;
  }
}

function wireEvents() {
  $('themeSwitch').addEventListener('click', () => {
    setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
  });
  setTheme(document.documentElement.dataset.theme || 'dark');

  $('refreshButton').addEventListener('click', () => {
    loadFacets();
    loadInbox();
    if (state.selectedId) selectSource(state.selectedId);
  });
  $('datalabCase').addEventListener('click', () => {
    state.queue = 'all';
    state.kind = '';
    state.project = '';
    state.q = 'datalab chandra';
    $('searchInput').value = state.q;
    $('projectSelect').value = '';
    loadFacets();
    loadInbox();
  });
  $('searchInput').addEventListener('input', () => {
    state.q = $('searchInput').value.trim();
    clearTimeout(window.__inboxTimer);
    window.__inboxTimer = setTimeout(loadInbox, 250);
  });
  $('projectSelect').addEventListener('change', () => {
    state.project = $('projectSelect').value;
    loadInbox();
  });
  $('limitSelect').addEventListener('change', () => {
    state.limit = $('limitSelect').value;
    loadInbox();
  });
  document.querySelectorAll('.tab').forEach((tab) => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.tab').forEach((item) => item.classList.remove('active'));
      document.querySelectorAll('.tab-pane').forEach((item) => item.classList.remove('active'));
      tab.classList.add('active');
      $(`tab-${tab.dataset.tab}`).classList.add('active');
    });
  });
}

async function init() {
  wireEvents();
  await loadFacets();
  await loadInbox();
}

init().catch((error) => {
  $('inboxRows').innerHTML = `<div class="empty-state"><h2>Startup error</h2><p>${escapeHtml(error.message)}</p></div>`;
});
