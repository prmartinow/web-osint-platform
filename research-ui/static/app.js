const state = {
  route: 'home',
  queue: 'all',
  kind: '',
  project: '',
  q: '',
  limit: '80',
  selectedId: '',
  previewTaskKey: '',
  rows: [],
  facets: null,
  home: null,
  currentSource: null,
  currentDoc: null,
  selectedBlock: null,
  homeEvidenceKind: '',
  inboxPreviewTab: 'preview',
  projectPhase: '',
  projectOwner: '',
  libraryMode: 'hybrid',
  libraryScope: 'corpus',
  librarySort: 'relevance',
  libraryDateFrom: '',
  libraryDateTo: '',
  libraryIncludeArchived: false,
  librarySelectedId: '',
  librarySelectedIds: new Set(),
  libraryPreviewTab: 'overview',
  evidenceMode: 'hybrid',
  evidenceType: '',
  evidenceReviewState: '',
  evidenceSourceKind: '',
  evidenceAnchorType: '',
  evidenceSelectedId: '',
  evidenceSelectedIds: new Set(),
  evidencePreviewTab: 'overview',
  evidenceRows: [],
};

const $ = (id) => document.getElementById(id);

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;'
  })[char]);
}

function cssEscape(value) {
  if (window.CSS?.escape) return CSS.escape(value);
  return String(value ?? '').replace(/["\\]/g, '\\$&');
}

function fmtDate(value) {
  if (!value) return '';
  return String(value).replace('T', ' ').replace(/Z$/, '');
}

function titleFor(row) {
  return row.title || row.canonical_url || row.evidence_id || '(untitled source)';
}

function taskTitleFor(row) {
  return row.task_label || row.review_hint || titleFor(row);
}

function sourceGlyph(kind) {
  if (kind === 'x_post' || kind === 'x_account' || kind === 'x_page') return 'X';
  if (kind === 'web_page' || kind === 'search_result' || kind === 'google_search_page') return 'W';
  if (kind === 'media') return 'M';
  if (kind === 'user_input') return 'D';
  return 'S';
}

function titleCase(value) {
  return String(value || '')
    .replaceAll('_', ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function sourceIdFor(row) {
  return row.source_evidence_id || row.evidence_id || '';
}

function taskKeyFor(row) {
  return row.task_id || [
    sourceIdFor(row),
    row.task_type || 'source',
    row.object_type || '',
    row.object_id || row.object_text || '',
  ].filter(Boolean).join(':');
}

function queueLabelFor(id) {
  const queue = (state.facets?.queues || []).find((item) => item.id === id);
  if (queue) return queue.label;
  if (id === 'all') return 'All queues';
  return titleCase(id);
}

function taskTypeLabel(row) {
  return row.task_type ? titleCase(row.task_type) : (row.review_hint ? titleCase(row.review_hint) : 'Source triage');
}

function sourceLabelFor(row) {
  return row.source_label || titleCase(row.source_kind || 'source');
}

function taskIconFor(row) {
  if (row.task_type?.includes('media')) return 'M';
  if (row.task_type?.includes('entity')) return 'E';
  if (row.task_type?.includes('claim') || row.task_type?.includes('fact')) return 'C';
  if (row.task_type?.includes('evidence') || row.task_type?.includes('selection')) return 'S';
  if (row.source_kind?.startsWith('x_')) return 'X';
  if (row.source_kind?.includes('web') || row.domain) return 'W';
  return sourceGlyph(row.source_kind);
}

function taskAccentFor(row) {
  if (row.task_priority === 'blocking') return 'danger';
  if (row.task_priority === 'high') return 'warn';
  if (row.task_type?.includes('media')) return 'purple';
  if (row.task_type?.includes('entity')) return 'teal';
  return 'blue';
}

function selectedPreviewRow() {
  return state.rows.find((row) => taskKeyFor(row) === state.previewTaskKey) || null;
}

function progressBar(percent) {
  const safe = Math.max(0, Math.min(100, Number(percent || 0)));
  return `<span class="bar"><span style="width:${safe}%"></span></span>`;
}

const routeConfig = {
  home: { title: 'Research brief', endpoint: '/api/home' },
  inbox: { title: 'Inbox', endpoint: '/api/inbox' },
  projects: { title: 'Projects', endpoint: '/api/projects' },
  library: { title: 'Source Library', endpoint: '/api/library' },
  evidence: { title: 'Evidence Ledger', endpoint: '/api/evidence' },
  entities: { title: 'Entity Directory', endpoint: '/api/entities' },
  claims: { title: 'Claims Ledger', endpoint: '/api/claims' },
  reviews: { title: 'Reviews', endpoint: '/api/reviews' },
  publishing: { title: 'Publishing', endpoint: '/api/publishing' },
  taxonomy: { title: 'Taxonomy', endpoint: '/api/taxonomy' },
};

function currentHashParts() {
  const raw = (location.hash || '').replace(/^#/, '');
  const separator = raw.indexOf('?');
  const route = separator >= 0 ? raw.slice(0, separator) : raw;
  const query = separator >= 0 ? raw.slice(separator + 1) : '';
  return { route, params: new URLSearchParams(query) };
}

function applyHashParams() {
  const { route, params } = currentHashParts();
  if (route === 'library') {
    state.q = params.get('q') || state.q || '';
    state.kind = params.get('type') || params.get('kind') || state.kind || '';
    state.project = params.get('project') || state.project || '';
    state.libraryMode = params.get('mode') || state.libraryMode || 'hybrid';
    state.libraryScope = params.get('scope') || state.libraryScope || 'corpus';
    state.librarySort = params.get('sort') || state.librarySort || 'relevance';
    state.libraryDateFrom = params.get('date_from') || '';
    state.libraryDateTo = params.get('date_to') || '';
    state.libraryIncludeArchived = params.get('include_archived') === '1';
    const inspect = params.get('inspect') || '';
    state.librarySelectedId = inspect.startsWith('source:') ? inspect.slice(7) : inspect;
  }
  if (route === 'evidence') {
    state.q = params.get('q') || state.q || '';
    state.project = params.get('project') || state.project || '';
    state.evidenceMode = params.get('mode') || state.evidenceMode || 'hybrid';
    state.evidenceType = params.get('type') || '';
    state.evidenceReviewState = params.get('review_state') || '';
    state.evidenceSourceKind = params.get('source_kind') || '';
    state.evidenceAnchorType = params.get('anchor_type') || '';
    const inspect = params.get('inspect') || '';
    state.evidenceSelectedId = inspect.startsWith('evidence:') ? inspect.slice(9) : inspect;
  }
}

function routeHash() {
  if (state.route === 'evidence') {
    const params = new URLSearchParams();
    if (state.q) params.set('q', state.q);
    if (state.project) params.set('project', state.project);
    if (state.evidenceMode && state.evidenceMode !== 'hybrid') params.set('mode', state.evidenceMode);
    if (state.evidenceType) params.set('type', state.evidenceType);
    if (state.evidenceReviewState) params.set('review_state', state.evidenceReviewState);
    if (state.evidenceSourceKind) params.set('source_kind', state.evidenceSourceKind);
    if (state.evidenceAnchorType) params.set('anchor_type', state.evidenceAnchorType);
    if (state.evidenceSelectedId) params.set('inspect', `evidence:${state.evidenceSelectedId}`);
    const query = params.toString();
    return `#evidence${query ? '?' + query : ''}`;
  }
  if (state.route !== 'library') return `#${state.route}`;
  const params = new URLSearchParams();
  if (state.q) params.set('q', state.q);
  if (state.kind) params.set('type', state.kind);
  if (state.project) params.set('project', state.project);
  if (state.libraryMode && state.libraryMode !== 'hybrid') params.set('mode', state.libraryMode);
  if (state.libraryScope && state.libraryScope !== 'corpus') params.set('scope', state.libraryScope);
  if (state.librarySort && state.librarySort !== 'relevance') params.set('sort', state.librarySort);
  if (state.libraryDateFrom) params.set('date_from', state.libraryDateFrom);
  if (state.libraryDateTo) params.set('date_to', state.libraryDateTo);
  if (state.libraryIncludeArchived) params.set('include_archived', '1');
  if (state.librarySelectedId) params.set('inspect', `source:${state.librarySelectedId}`);
  const query = params.toString();
  return `#library${query ? '?' + query : ''}`;
}

function replaceRouteHash() {
  history.replaceState(null, '', routeHash());
}

function sourceKindForCoverage(key) {
  if (key === 'x') return 'x_post';
  if (key === 'web') return 'web_page';
  if (key === 'papers') return 'user_input';
  if (key === 'media') return 'media';
  return '';
}

function openInboxQueue(queue = 'all', q = '') {
  state.queue = queue;
  state.q = q;
  state.previewTaskKey = '';
  syncInboxSearchInputs(q);
  setRoute('inbox');
}

function openLibraryView({ q = '', kind = '', project = state.project || '', scope = 'corpus', mode = 'hybrid' } = {}) {
  state.q = q;
  state.kind = kind;
  state.project = project;
  state.libraryScope = scope;
  state.libraryMode = mode;
  state.librarySelectedId = '';
  syncInboxSearchInputs(q);
  if ($('projectSelect')) $('projectSelect').value = project;
  setRoute('library');
}

async function fetchJson(url) {
  const response = await fetch(url, { cache: 'no-store' });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || response.statusText);
  return data;
}

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || response.statusText);
  return data;
}

function activateTab(name) {
  document.querySelectorAll('.tab').forEach((item) => item.classList.toggle('active', item.dataset.tab === name));
  document.querySelectorAll('.tab-pane').forEach((item) => item.classList.toggle('active', item.id === `tab-${name}`));
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
  $('navInboxCount').textContent = totals.unique_evidence ?? 0;

  const queues = data.queues || [];
  $('inboxQueueCount').textContent = queues.length;
  $('inboxActiveFilter').textContent = queueLabelFor(state.queue);
  const queueById = new Map(queues.map((queue) => [queue.id, queue]));
  const queueGroups = [
    { title: 'My work', ids: ['all', 'needs_review'] },
    { title: 'Capture', ids: ['source_triage', 'version_review', 'x_sources', 'web_sources', 'manual_docs'] },
    { title: 'Enrichment', ids: ['extraction_review', 'media_review', 'correction_review'] },
    { title: 'Knowledge', ids: ['evidence_selection', 'entity_resolution', 'claim_review', 'fact_review'] },
    { title: 'Publishing', ids: ['selection_review', 'annotation_followup'] },
  ];
  const rendered = new Set();
  $('queueList').innerHTML = queueGroups.map((group) => {
    const items = group.ids.map((id) => queueById.get(id)).filter(Boolean);
    items.forEach((item) => rendered.add(item.id));
    if (!items.length) return '';
    return `
      <section class="queue-group">
        <h3>${escapeHtml(group.title)}</h3>
        ${items.map((queue) => `
          <button class="queue ${state.queue === queue.id ? 'active' : ''}" data-queue="${escapeHtml(queue.id)}">
            <span class="queue-mark"></span>
            <span class="queue-copy">
              <strong>${escapeHtml(queue.label)}</strong>
              <em>${escapeHtml(queueDescription(queue.id))}</em>
            </span>
            ${queue.count || queue.count === 0 ? `<span class="count">${escapeHtml(queue.count)}</span>` : ''}
          </button>
        `).join('')}
      </section>
    `;
  }).join('') + queues.filter((queue) => !rendered.has(queue.id)).map((queue) => `
    <button class="queue ${state.queue === queue.id ? 'active' : ''}" data-queue="${escapeHtml(queue.id)}">
      <span class="queue-mark"></span>
      <span class="queue-copy">
        <strong>${escapeHtml(queue.label)}</strong>
        <em>Saved queue</em>
      </span>
      ${queue.count || queue.count === 0 ? `<span class="count">${escapeHtml(queue.count)}</span>` : ''}
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
      state.previewTaskKey = '';
      loadInbox();
      renderFacets(state.facets);
    });
  });
  document.querySelectorAll('[data-kind]').forEach((button) => {
    button.addEventListener('click', () => {
      state.kind = button.dataset.kind || '';
      state.previewTaskKey = '';
      loadInbox();
      renderFacets(state.facets);
    });
  });
  document.querySelectorAll('[data-domain]').forEach((button) => {
    button.addEventListener('click', () => {
      state.q = button.dataset.domain || '';
      syncInboxSearchInputs(state.q);
      state.previewTaskKey = '';
      loadInbox();
    });
  });
}

function queueDescription(id) {
  const descriptions = {
    all: 'Everything that needs review',
    needs_review: 'Open review work',
    source_triage: 'New captures and raw sources',
    extraction_review: 'Normalized content checks',
    media_review: 'OCR, screenshots, video, and VL outputs',
    evidence_selection: 'Source passages worth keeping',
    version_review: 'Potentially superseded captures',
    entity_resolution: 'People, labs, models, repos, and accounts',
    claim_review: 'Claims that need support or contradiction checks',
    fact_review: 'Structured facts before promotion',
    correction_review: 'Text and metadata fixes',
    selection_review: 'Publication candidates',
    annotation_followup: 'Machine annotations to inspect',
    x_sources: 'Captured X evidence',
    web_sources: 'Web pages and blog posts',
    manual_docs: 'User-added research documents',
  };
  return descriptions[id] || 'Review queue';
}

function renderHome(data) {
  state.home = data;
  const project = data.active_project || {};
  const brief = data.brief || {};
  $('activeProjectName').textContent = project.name || 'Active research project';
  $('projectPickerLabel').textContent = project.name || 'Active research project';
  $('activeProjectMeta').textContent = project.description || 'Evidence workspace';
  $('activeProjectMeter').style.width = `${Math.max(0, Math.min(100, Number(project.completion_percent || 0)))}%`;
  $('homeUpdated').textContent = project.updated_at ? `Updated ${fmtDate(project.updated_at)}` : 'No recent ingest';
  $('activeQuestion').textContent = brief.question || 'What evidence needs review?';
  $('activeQuestionScope').textContent = brief.scope || '';

  $('briefStats').innerHTML = (brief.stats || []).map((item) => `
    <button type="button" class="stat-chip stat-action" data-home-route="${escapeHtml(item.route || 'library')}"><strong>${escapeHtml(item.value ?? 0)}</strong>${escapeHtml(item.label || '')}</button>
  `).join('');

  const workflow = brief.workflow || [];
  const workflowHtml = workflow.map((item) => `
    <button type="button" class="workflow-row" data-home-route="${escapeHtml(item.route || 'inbox')}" title="${escapeHtml(item.label || '')}: ${escapeHtml(item.percent ?? 0)}%">
      <span>${escapeHtml(item.label || '')}</span>
      ${progressBar(item.percent)}
      <strong>${escapeHtml(item.percent ?? 0)}%</strong>
    </button>
  `).join('');
  if (workflowHtml) {
    $('briefStats').insertAdjacentHTML('beforeend', `<div class="workflow-stack">${workflowHtml}</div>`);
  }

  $('todayQueue').innerHTML = (data.queue || []).map((item) => `
    <button class="task-row" data-queue-jump="${escapeHtml(item.label || '')}">
      <span class="task-count">${escapeHtml(item.count ?? 0)}</span>
      <span>${escapeHtml(item.label || '')}</span>
      <em>${escapeHtml(item.hint || '')}</em>
    </button>
  `).join('');

  const evidenceRows = data.recent_evidence || [];
  const sourceOptions = [...new Map(evidenceRows.map((row) => [row.source_kind || '', row.source_label || sourceLabelFor(row)])).entries()]
    .filter(([id]) => id)
    .sort((a, b) => a[1].localeCompare(b[1]));
  if ($('homeSourceFilter')) {
    $('homeSourceFilter').innerHTML = '<option value="">All source types</option>' + sourceOptions.map(([id, label]) => (
      `<option value="${escapeHtml(id)}" ${state.homeEvidenceKind === id ? 'selected' : ''}>${escapeHtml(label)}</option>`
    )).join('');
  }
  const visibleEvidenceRows = evidenceRows.filter((row) => !state.homeEvidenceKind || row.source_kind === state.homeEvidenceKind).slice(0, 6);
  $('signalRows').innerHTML = visibleEvidenceRows.length ? visibleEvidenceRows.map((row) => `
    <button class="signal-row" data-id="${escapeHtml(row.evidence_id)}">
      <span class="source-glyph">${escapeHtml(sourceGlyph(row.source_kind))}</span>
      <span class="signal-main">
        <strong>${escapeHtml(titleFor(row))}</strong>
        <em>${escapeHtml([row.source_label, row.author_handle ? '@' + row.author_handle : row.domain, fmtDate(row.last_ingested_at)].filter(Boolean).join(' · '))}</em>
      </span>
      <span class="signal-tags">
        ${row.has_ocr ? '<span class="status-badge ok">OCR</span>' : ''}
        ${row.has_media ? '<span class="status-badge info">media</span>' : ''}
        <span class="status-badge">${escapeHtml(row.review_hint || 'triage')}</span>
      </span>
    </button>
  `).join('') : '<p class="muted padded">No evidence has landed for this source filter yet.</p>';

  const contradictions = data.contradictions || [];
  $('contradictionCount').textContent = `${contradictions.length} open`;
  $('contradictionList').innerHTML = contradictions.length ? contradictions.map((item) => `
    <button class="compact-row" data-home-route="claims">
      <strong>${escapeHtml(item.title)}</strong>
      <span>${escapeHtml(item.detail || '')}</span>
      <em>${escapeHtml(item.sources ?? 0)} sources</em>
    </button>
  `).join('') : '<p class="muted padded">No contradiction candidates yet.</p>';

  const coverage = data.coverage || {};
  const coverageRows = coverage.rows || [];
  $('coverageGapCount').textContent = `${coverage.gaps || 0} gaps`;
  $('coverageMatrix').innerHTML = coverageRows.length ? `
    <table>
      <thead><tr><th>Where the current brief is strong and where it needs more sources</th><th>X/social</th><th>Web</th><th>Papers/docs</th><th>Media</th></tr></thead>
      <tbody>${coverageRows.map((row) => `
        <tr>
          <td>${escapeHtml(row.topic)}</td>
          ${['x', 'web', 'papers', 'media'].map((key) => {
            const count = Number(row[key] || 0);
            return `<td><button type="button" class="coverage-cell" data-coverage-topic="${escapeHtml(row.topic)}" data-coverage-kind="${escapeHtml(key)}" aria-label="${escapeHtml(row.topic)} ${key}: ${count} source${count === 1 ? '' : 's'}"><span class="dot-scale count-${Math.min(5, count)}"></span><strong>${escapeHtml(count)}</strong></button></td>`;
          }).join('')}
        </tr>
      `).join('')}</tbody>
    </table>
  ` : '<p class="muted padded">Coverage appears after captures are indexed.</p>';

  const publication = data.publication || {};
  const checks = Number(publication.checks_passed || 0);
  const total = Number(publication.checks_total || 1);
  $('publishReadiness').innerHTML = `
    <p><strong>${checks} of ${total}</strong> checks passed</p>
    ${progressBar(total ? Math.round((checks / total) * 100) : 0)}
    <div class="tag-line">${publication.blockers ? `<span class="status-badge danger">${escapeHtml(publication.blockers)} blockers</span>` : '<span class="status-badge ok">No blockers recorded</span>'}</div>
  `;

  $('openQuestions').innerHTML = (data.open_questions || []).map((question, index) => {
    const text = typeof question === 'string' ? question : question.text || question.question || '';
    const owner = typeof question === 'string' ? 'unassigned' : question.owner || 'unassigned';
    const blocked = typeof question !== 'string' && question.blocked;
    return `
    <article class="compact-row question-card">
      <span class="question-number">${String(index + 1).padStart(2, '0')}</span>
      <strong>${escapeHtml(text)}</strong>
      <em>${escapeHtml(owner)}${blocked ? ' · blocked' : ''}</em>
      <div class="question-actions">
        <button type="button" class="text-button" data-question-route="projects">Open</button>
        <button type="button" class="text-button" data-question-route="library" data-question-text="${escapeHtml(text)}">Find evidence</button>
        <button type="button" class="text-button" data-question-route="inbox" data-question-text="${escapeHtml(text)}">Assign</button>
      </div>
    </article>
  `;
  }).join('');

  document.querySelectorAll('.signal-row[data-id]').forEach((button) => {
    button.addEventListener('click', () => selectSource(button.dataset.id));
  });
  const queueRoutes = {
    'New captures': 'source_triage',
    'Entity matches': 'entity_resolution',
    'Contradictions': 'claim_review',
    'Assigned reviews': 'needs_review',
  };
  document.querySelectorAll('[data-queue-jump]').forEach((button) => {
    button.addEventListener('click', () => {
      openInboxQueue(queueRoutes[button.dataset.queueJump] || 'all');
    });
  });
  document.querySelectorAll('[data-home-route]').forEach((button) => {
    button.addEventListener('click', () => setRoute(button.dataset.homeRoute || 'home'));
  });
  document.querySelectorAll('[data-coverage-kind]').forEach((button) => {
    button.addEventListener('click', () => {
      openLibraryView({
        q: button.dataset.coverageTopic || '',
        kind: sourceKindForCoverage(button.dataset.coverageKind || ''),
        scope: 'corpus',
        mode: 'hybrid',
      });
    });
  });
  document.querySelectorAll('[data-question-route]').forEach((button) => {
    button.addEventListener('click', () => {
      const route = button.dataset.questionRoute || 'projects';
      const text = button.dataset.questionText || '';
      if (route === 'library') return openLibraryView({ q: text, mode: 'hybrid' });
      if (route === 'inbox') return openInboxQueue('needs_review', text);
      return setRoute(route);
    });
  });
  if ($('homeSourceFilter')) {
    $('homeSourceFilter').onchange = () => {
      state.homeEvidenceKind = $('homeSourceFilter').value;
      renderHome(state.home);
    };
  }
}

async function loadHome() {
  try {
    renderHome(await fetchJson('/api/home'));
  } catch (error) {
    $('homeUpdated').textContent = `Home summary error: ${error.message}`;
  }
}

function pageHeader(title, subtitle, actions = '') {
  return `
    <header class="page-header">
      <div>
        <div class="breadcrumb">Research UI / ${escapeHtml(title)}</div>
        <h1>${escapeHtml(title)}</h1>
        <p>${escapeHtml(subtitle || '')}</p>
      </div>
      <div class="page-actions">${actions}</div>
    </header>
  `;
}

function metricCards(items) {
  return `<div class="metric-grid">${items.map((item) => `
    <article class="metric-card panel">
      <span>${escapeHtml(item.label)}</span>
      <strong>${escapeHtml(item.value ?? 0)}</strong>
      ${item.hint ? `<em>${escapeHtml(item.hint)}</em>` : ''}
    </article>
  `).join('')}</div>`;
}

function sourceButton(row, extra = '') {
  return `
    <button class="object-row" data-id="${escapeHtml(row.evidence_id || row.source_evidence_id || '')}">
      <span class="source-glyph">${escapeHtml(sourceGlyph(row.source_kind))}</span>
      <span class="object-main">
        <strong>${escapeHtml(row.title || row.canonical_url || row.evidence_id || row.source_evidence_id || '(untitled)')}</strong>
        <em>${escapeHtml([row.source_label || row.source_kind, row.source_project, row.domain, fmtDate(row.last_ingested_at || row.updated_at)].filter(Boolean).join(' · '))}</em>
        ${row.snippet ? `<p>${escapeHtml(row.snippet)}</p>` : ''}
      </span>
      <span class="object-side">${extra}</span>
    </button>
  `;
}

function bindObjectRows() {
  document.querySelectorAll('.object-row[data-id]').forEach((button) => {
    const id = button.dataset.id;
    if (!id) return;
    button.addEventListener('click', () => selectSource(id));
  });
}

function numeric(row, key) {
  return Number(row?.[key] || 0);
}

function percentLike(completed, total) {
  const safeTotal = Number(total || 0);
  if (!safeTotal) return 0;
  return Math.round((Number(completed || 0) / safeTotal) * 100);
}

function projectCoverageRows(row) {
  return [
    { label: 'Release claims', x: numeric(row, 'x_sources'), web: numeric(row, 'web_sources'), media: numeric(row, 'media_sources'), docs: numeric(row, 'manual_sources') },
    { label: 'Benchmarks', x: numeric(row, 'x_sources'), web: numeric(row, 'web_sources'), media: numeric(row, 'ocr_rows'), docs: numeric(row, 'manual_sources') },
    { label: 'Licensing', x: numeric(row, 'x_sources'), web: numeric(row, 'web_sources'), media: 0, docs: numeric(row, 'manual_sources') },
    { label: 'Hardware & cost', x: numeric(row, 'x_sources'), web: numeric(row, 'web_sources'), media: numeric(row, 'media_sources'), docs: numeric(row, 'manual_sources') },
  ];
}

function coverageDot(value, label) {
  const count = Number(value || 0);
  const bucket = count === 0 ? 0 : count === 1 ? 1 : count === 2 ? 2 : 3;
  return `<span class="project-coverage-cell" aria-label="${escapeHtml(label)}: ${count} source${count === 1 ? '' : 's'}"><span class="dot-scale count-${bucket}"></span><strong>${escapeHtml(count)}</strong></span>`;
}

function sourceTargetPercent(target) {
  return percentLike(target.current, Math.max(1, target.target || 1));
}

function projectRouteButton(row, label, route) {
  return `<button type="button" class="text-button project-nav-action" data-project="${escapeHtml(row.project_id || '')}" data-route-target="${escapeHtml(route)}">${escapeHtml(label)}</button>`;
}

function briefLines(items, key = 'text') {
  return (items || []).map((item) => item?.[key] || '').filter(Boolean).join('\n');
}

function definitionsText(items) {
  return (items || []).map((item) => `${item.term || ''}: ${item.definition || ''}`.trim()).filter(Boolean).join('\n');
}

function splitLines(value) {
  return String(value || '').split(/\n+/).map((line) => line.trim()).filter(Boolean);
}

function parseDefinitionLines(value) {
  return splitLines(value).map((line) => {
    const match = line.match(/^([^:—-]+)\s*(?::|—|-)\s*(.*)$/);
    if (!match) return { term: line, definition: '' };
    return { term: match[1].trim(), definition: match[2].trim() };
  });
}

function activeProjectRow(rows) {
  if (!rows.length) return null;
  if (state.project) {
    return rows.find((row) => String(row.project_id || '') === String(state.project)) || rows[0];
  }
  return rows[0];
}

function renderProjectLocalNav(row) {
  return `
    <nav class="project-local-nav" aria-label="${escapeHtml(row.name)} local navigation">
      ${projectRouteButton(row, 'Home', 'home')}
      <button type="button" class="text-button active" disabled>Brief</button>
      ${projectRouteButton(row, 'Sources', 'library')}
      ${projectRouteButton(row, 'Evidence', 'evidence')}
      ${projectRouteButton(row, 'Claims', 'claims')}
      ${projectRouteButton(row, 'Entities', 'entities')}
      <button type="button" class="text-button" disabled>Timeline</button>
      <button type="button" class="text-button" disabled>Compare</button>
      <button type="button" class="text-button" disabled>Drafts</button>
      ${projectRouteButton(row, 'Publishing', 'publishing')}
      ${projectRouteButton(row, 'Inbox', 'inbox')}
    </nav>
  `;
}

function renderSourceTarget(target) {
  const pct = sourceTargetPercent(target);
  return `
    <div class="source-target-row">
      <span>${escapeHtml(target.label)}</span>
      ${progressBar(Math.min(100, pct))}
      <strong>${escapeHtml(target.current)} / ${escapeHtml(target.target)}</strong>
    </div>
  `;
}

function renderCoverageRule(rule) {
  return `
    <div class="coverage-rule ${rule.status === 'pass' ? 'ok' : 'warn'}">
      <span class="status-badge ${rule.status === 'pass' ? 'ok' : 'warn'}">${escapeHtml(rule.status === 'pass' ? 'pass' : 'needs work')}</span>
      <strong>${escapeHtml(rule.label)}</strong>
      <p>${escapeHtml(rule.rule)}</p>
      <em>${escapeHtml(rule.current)} / ${escapeHtml(rule.target)}</em>
    </div>
  `;
}

function renderProjectBlocker(row, blocker) {
  return `
    <button type="button" class="project-blocker-item" data-project="${escapeHtml(row.project_id || '')}" data-route-target="${escapeHtml(blocker.route || 'inbox')}">
      <span class="status-badge ${escapeHtml(blocker.severity || 'warn')}">${escapeHtml(blocker.count || 0)}</span>
      <strong>${escapeHtml(blocker.label)}</strong>
      <p>${escapeHtml(blocker.detail || '')}</p>
    </button>
  `;
}

function renderSavedView(row, view) {
  return `
    <button type="button" class="saved-view-row" data-project="${escapeHtml(row.project_id || '')}" data-route-target="${escapeHtml(view.route || 'library')}">
      <strong>${escapeHtml(view.label)}</strong>
      <span>${escapeHtml(view.description || '')}</span>
    </button>
  `;
}

function renderAuditEvent(event) {
  return `
    <div class="audit-event-row">
      <span>${escapeHtml(fmtDate(event.created_at))}</span>
      <strong>${escapeHtml(titleCase(event.event_type || 'project event'))}</strong>
      <em>${escapeHtml(event.actor || '')}</em>
    </div>
  `;
}

function renderQuestionMoveControls(questions) {
  const rows = questions || [];
  if (!rows.length) return '<p class="muted">No open questions yet.</p>';
  return `
    <div class="question-move-list">
      ${rows.map((question, index) => `
        <div class="question-move-row">
          <span>${escapeHtml(question.text || question.question || '')}</span>
          <button type="button" class="icon-button" data-question-move="${index}:-1" ${index === 0 ? 'disabled' : ''}>Up</button>
          <button type="button" class="icon-button" data-question-move="${index}:1" ${index === rows.length - 1 ? 'disabled' : ''}>Down</button>
        </div>
      `).join('')}
    </div>
  `;
}

function moveTextareaLine(selector, index, delta) {
  const textarea = document.querySelector(selector);
  if (!textarea) return;
  const lines = splitLines(textarea.value);
  const target = index + delta;
  if (target < 0 || target >= lines.length) return;
  const [item] = lines.splice(index, 1);
  lines.splice(target, 0, item);
  textarea.value = lines.join('\n');
  textarea.dispatchEvent(new Event('input', { bubbles: true }));
}

function projectBriefPayload(row) {
  const scopeTags = splitLines(document.querySelector('[data-brief-scope="tags"]')?.value || '').flatMap((line) => line.split(',')).map((item) => item.trim()).filter(Boolean);
  return {
    project_id: row.project_id || '',
    project_name: row.name || row.project_id || '(unassigned)',
    expected_version: state.activeProjectBriefVersion || row.brief?.version || '',
    idempotency_key: `project-brief-${Date.now()}-${Math.random().toString(16).slice(2)}`,
    research_question: document.querySelector('[data-brief-field="research_question"]')?.value || '',
    decision_supported: document.querySelector('[data-brief-field="decision_supported"]')?.value || '',
    scope: {
      time_window: document.querySelector('[data-brief-scope="time_window"]')?.value || '',
      geography: document.querySelector('[data-brief-scope="geography"]')?.value || '',
      population: document.querySelector('[data-brief-scope="population"]')?.value || '',
      evidence_policy: document.querySelector('[data-brief-scope="evidence_policy"]')?.value || '',
      tags: scopeTags,
    },
    inclusion_criteria: splitLines(document.querySelector('[data-brief-list="inclusion_criteria"]')?.value || '').map((text) => ({ text, status: 'active' })),
    exclusion_criteria: splitLines(document.querySelector('[data-brief-list="exclusion_criteria"]')?.value || '').map((text) => ({ text, status: 'active' })),
    open_questions: splitLines(document.querySelector('[data-brief-list="open_questions"]')?.value || '').map((text) => ({ text, status: 'open', owner: 'web-osint-user' })),
    working_definitions: parseDefinitionLines(document.querySelector('[data-brief-list="working_definitions"]')?.value || ''),
    limitations: splitLines(document.querySelector('[data-brief-list="limitations"]')?.value || '').map((text) => ({ text, status: 'active' })),
  };
}

function setProjectBriefStatus(text, mode = '') {
  const node = $('projectBriefSaveStatus');
  if (!node) return;
  node.textContent = text;
  node.className = `status-badge ${mode}`.trim();
}

function scheduleProjectBriefSave(row) {
  setProjectBriefStatus('Saving...', 'warn');
  clearTimeout(window.__projectBriefSaveTimer);
  window.__projectBriefSaveTimer = setTimeout(() => saveProjectBrief(row), 850);
}

async function saveProjectBrief(row) {
  try {
    const result = await postJson('/api/project-brief', projectBriefPayload(row));
    row.brief = result.brief;
    state.activeProjectBriefVersion = result.brief.version;
    $('projectBriefVersion').textContent = `v${result.brief.version}`;
    $('projectBriefMaterialChanges').textContent = result.brief.material_changes_since_review ?? 0;
    $('projectBriefReviewState').textContent = titleCase(result.brief.review_state || 'draft');
    setProjectBriefStatus('Saved just now', 'ok');
  } catch (error) {
    setProjectBriefStatus(error.message, 'danger');
  }
}

async function sendProjectBriefToReview(row) {
  setProjectBriefStatus('Sending to review...', 'warn');
  clearTimeout(window.__projectBriefSaveTimer);
  try {
    const result = await postJson('/api/project-brief/review', projectBriefPayload(row));
    row.brief = result.brief;
    state.activeProjectBriefVersion = result.brief.version;
    loadRoutePage();
  } catch (error) {
    setProjectBriefStatus(error.message, 'danger');
  }
}

function renderProjectsPage(data) {
  const rows = data.rows || [];
  const ownerOptions = [...new Set(rows.map((row) => row.owner).filter(Boolean))];
  const phaseOptions = [...new Set(rows.map((row) => row.phase).filter(Boolean))];
  const visibleRows = rows.filter((row) => {
    if (state.projectPhase && row.phase !== state.projectPhase) return false;
    if (state.projectOwner && row.owner !== state.projectOwner) return false;
    return true;
  });
  const sourceTotal = visibleRows.reduce((sum, row) => sum + numeric(row, 'sources'), 0);
  const acceptedEvidence = visibleRows.reduce((sum, row) => sum + numeric(row, 'accepted_evidence'), 0);
  const blockers = visibleRows.reduce((sum, row) => sum + numeric(row, 'publication_blockers'), 0);
  const activeRow = activeProjectRow(visibleRows);
  const brief = activeRow?.brief || {};
  state.activeProjectBriefVersion = brief.version || '';
  $('routePage').innerHTML = `
    ${pageHeader('Projects', 'Project Brief workspace for research scope, coverage rules, open questions, and review handoff.')}
    <section class="panel projects-toolbar" aria-label="Project filters">
      <label>
        <span>Search</span>
        <input id="projectRouteSearch" type="search" value="${escapeHtml(state.q)}" placeholder="Search project, source, domain, or question">
      </label>
      <label>
        <span>Project</span>
        <select id="projectWorkspaceSelect">
          ${visibleRows.map((row) => `<option value="${escapeHtml(row.project_id || '')}" ${activeRow && (row.project_id || '') === (activeRow.project_id || '') ? 'selected' : ''}>${escapeHtml(row.name)}</option>`).join('')}
        </select>
      </label>
      <label>
        <span>Phase</span>
        <select id="projectPhaseFilter">
          <option value="">All phases</option>
          ${phaseOptions.map((phase) => `<option value="${escapeHtml(phase)}" ${state.projectPhase === phase ? 'selected' : ''}>${escapeHtml(titleCase(phase))}</option>`).join('')}
        </select>
      </label>
      <label>
        <span>Owner</span>
        <select id="projectOwnerFilter">
          <option value="">All owners</option>
          ${ownerOptions.map((owner) => `<option value="${escapeHtml(owner)}" ${state.projectOwner === owner ? 'selected' : ''}>${escapeHtml(owner)}</option>`).join('')}
        </select>
      </label>
    </section>
    ${metricCards([
      { label: 'Projects', value: visibleRows.length, hint: rows.length !== visibleRows.length ? `${rows.length} total` : 'visible' },
      { label: 'Sources', value: sourceTotal },
      { label: 'Accepted evidence', value: acceptedEvidence, hint: 'review layer' },
      { label: 'Publication blockers', value: blockers, hint: blockers ? 'needs work' : 'clear' },
    ])}
    ${activeRow ? `
      <article class="project-brief-workspace">
        <header class="panel project-brief-header">
          <div>
            <div class="breadcrumb">Projects / ${escapeHtml(activeRow.visibility || 'internal')} / Brief</div>
            <h2>${escapeHtml(activeRow.name)}</h2>
            <p>${escapeHtml(activeRow.scope || 'Project-scoped evidence review and curation workspace.')}</p>
            <div class="tag-line">
              <span id="projectBriefReviewState" class="pill">${escapeHtml(titleCase(brief.review_state || 'draft'))}</span>
              <span id="projectBriefVersion" class="pill">v${escapeHtml(brief.version || '1')}</span>
              <span class="pill">${escapeHtml(activeRow.sources)} captured sources</span>
              <span class="pill">${escapeHtml(activeRow.accepted_evidence)} accepted evidence</span>
            </div>
          </div>
          <div class="project-brief-actions">
            <span id="projectBriefSaveStatus" class="status-badge ok">Saved</span>
            <button id="projectBriefPreviewButton" type="button" class="secondary">Preview changes</button>
            <button id="projectBriefReviewButton" type="button">Send to review</button>
          </div>
        </header>
        ${renderProjectLocalNav(activeRow)}
        <div class="project-brief-layout">
          <section class="project-brief-editor panel">
            <div class="brief-editor-section">
              <div class="panel-title-row"><h2>Research Question And Scope</h2><span class="status-badge">autosave</span></div>
              <label><span>Research question</span><textarea data-brief-field="research_question">${escapeHtml(brief.research_question || '')}</textarea></label>
              <label><span>Decision supported</span><textarea data-brief-field="decision_supported">${escapeHtml(brief.decision_supported || '')}</textarea></label>
              <div class="scope-field-grid">
                <label><span>Time window</span><input data-brief-scope="time_window" value="${escapeHtml(brief.scope?.time_window || '')}"></label>
                <label><span>Geography</span><input data-brief-scope="geography" value="${escapeHtml(brief.scope?.geography || '')}"></label>
                <label class="wide"><span>Population / domain</span><input data-brief-scope="population" value="${escapeHtml(brief.scope?.population || '')}"></label>
                <label class="wide"><span>Evidence policy</span><textarea data-brief-scope="evidence_policy">${escapeHtml(brief.scope?.evidence_policy || '')}</textarea></label>
                <label class="wide"><span>Tags</span><input data-brief-scope="tags" value="${escapeHtml((brief.scope?.tags || []).join(', '))}"></label>
              </div>
            </div>
            <div class="criteria-grid">
              <label><span>Inclusion criteria</span><textarea data-brief-list="inclusion_criteria">${escapeHtml(briefLines(brief.inclusion_criteria))}</textarea></label>
              <label><span>Exclusion criteria</span><textarea data-brief-list="exclusion_criteria">${escapeHtml(briefLines(brief.exclusion_criteria))}</textarea></label>
            </div>
            <div class="brief-editor-section">
              <div class="panel-title-row">
                <h2>Open Questions</h2>
                <div class="title-action-group">
                  <span class="status-badge warn">${escapeHtml((brief.open_questions || []).length)} active</span>
                  <button id="projectAddQuestion" type="button" class="secondary">Add question</button>
                </div>
              </div>
              <textarea data-brief-list="open_questions">${escapeHtml(briefLines(brief.open_questions))}</textarea>
              ${renderQuestionMoveControls(brief.open_questions || [])}
            </div>
            <div class="brief-editor-section">
              <div class="panel-title-row"><h2>Working Definitions</h2><span class="status-badge">project terms</span></div>
              <textarea data-brief-list="working_definitions">${escapeHtml(definitionsText(brief.working_definitions))}</textarea>
            </div>
            <div class="brief-editor-section">
              <div class="panel-title-row"><h2>Key Accepted Findings</h2><span class="status-badge ${activeRow.accepted_claims ? 'ok' : 'warn'}">claim projections</span></div>
              <div class="accepted-finding-box">
                ${activeRow.accepted_claims ? `<strong>${escapeHtml(activeRow.accepted_claims)} accepted claim${activeRow.accepted_claims === 1 ? '' : 's'}</strong><p>Findings are projected from accepted claim assertions and reviewed evidence. Edit them in the Claims Ledger.</p>` : '<strong>No accepted claims yet</strong><p>Promote evidence into reviewed claims before this section can produce publication-ready findings.</p>'}
                <button type="button" class="secondary" data-project="${escapeHtml(activeRow.project_id || '')}" data-route-target="claims">Open Claims Ledger</button>
              </div>
            </div>
            <div class="brief-editor-section">
              <div class="panel-title-row"><h2>Known Limitations</h2><span class="status-badge">publication boundary</span></div>
              <textarea data-brief-list="limitations">${escapeHtml(briefLines(brief.limitations))}</textarea>
            </div>
          </section>
          <aside class="project-brief-rail">
            <section class="panel rail-card">
              <div class="panel-title-row"><h2>Review Handoff</h2><span class="status-badge ${brief.review_state === 'ready_for_review' ? 'ok' : 'warn'}">${escapeHtml(titleCase(brief.review_state || 'draft'))}</span></div>
              <div class="handoff-stat"><span>Material changes since review</span><strong id="projectBriefMaterialChanges">${escapeHtml(brief.material_changes_since_review ?? 0)}</strong></div>
              <div class="handoff-stat"><span>Last review request</span><strong>${escapeHtml(fmtDate(brief.last_review_requested_at) || 'not sent')}</strong></div>
              <p>Ordinary edits create audit records. Send to review creates a formal review event tied to this brief version.</p>
            </section>
            <section class="panel rail-card">
              <div class="panel-title-row"><h2>Project Controls</h2><span class="status-badge">${escapeHtml(activeRow.visibility || 'internal')}</span></div>
              <div class="project-mini-list">
                <div><span>Owner</span><strong>${escapeHtml(activeRow.owner || 'unassigned')}</strong></div>
                <div><span>Contributors</span><strong>${escapeHtml((activeRow.contributors || []).join(', ') || 'none')}</strong></div>
                <div><span>Phase</span><strong>${escapeHtml(titleCase(activeRow.phase))}</strong></div>
                <div><span>Due</span><strong>${escapeHtml(fmtDate(activeRow.due_at) || 'not set')}</strong></div>
                <div><span>Next review</span><strong>${escapeHtml(fmtDate(activeRow.next_review_at) || 'not set')}</strong></div>
                <div><span>First capture</span><strong>${escapeHtml(fmtDate(activeRow.first_capture) || 'none')}</strong></div>
                <div><span>Last activity</span><strong>${escapeHtml(fmtDate(activeRow.last_activity) || 'none')}</strong></div>
              </div>
            </section>
            <section class="panel rail-card">
              <div class="panel-title-row"><h2>Source Targets</h2><span class="status-badge">coverage</span></div>
              <div class="source-target-list">${(activeRow.source_targets || []).map(renderSourceTarget).join('')}</div>
            </section>
            <section class="panel rail-card">
              <div class="panel-title-row"><h2>Coverage Rules</h2><span class="status-badge">publication checks</span></div>
              <div class="coverage-rule-list">${(activeRow.coverage_targets || []).map(renderCoverageRule).join('')}</div>
            </section>
            <section class="panel rail-card">
              <div class="panel-title-row"><h2>Current Blockers</h2><span class="status-badge ${activeRow.blockers?.length ? 'danger' : 'ok'}">${escapeHtml(activeRow.blockers?.length || 0)}</span></div>
              <div class="project-blocker-list">${(activeRow.blockers || []).map((blocker) => renderProjectBlocker(activeRow, blocker)).join('') || '<p>No current project blockers.</p>'}</div>
            </section>
            <section class="panel rail-card">
              <div class="panel-title-row"><h2>Saved Views</h2><span class="status-badge">deep links</span></div>
              <div class="saved-view-list">${(activeRow.saved_views || []).map((view) => renderSavedView(activeRow, view)).join('')}</div>
            </section>
            <section class="panel rail-card">
              <div class="panel-title-row"><h2>Audit And Review Activity</h2><span class="status-badge">append-only</span></div>
              <div class="audit-list">${(activeRow.activity || []).map(renderAuditEvent).join('') || '<p>No project brief activity yet.</p>'}</div>
            </section>
          </aside>
        </div>
      </article>
    ` : `<div class="empty-state panel"><h2>No projects found</h2><p>${state.q || state.projectPhase || state.projectOwner ? 'No project matches the active filters.' : 'Capture a source to initialize a project brief.'}</p></div>`}
  `;
  $('projectRouteSearch')?.addEventListener('input', () => {
    state.q = $('projectRouteSearch').value.trim();
    if ($('searchInput').value !== state.q) $('searchInput').value = state.q;
    clearTimeout(window.__projectTimer);
    window.__projectTimer = setTimeout(loadRoutePage, 250);
  });
  $('projectWorkspaceSelect')?.addEventListener('change', () => {
    state.project = $('projectWorkspaceSelect').value;
    if ($('projectSelect')) $('projectSelect').value = state.project;
    renderProjectsPage(data);
  });
  $('projectPhaseFilter')?.addEventListener('change', () => {
    state.projectPhase = $('projectPhaseFilter').value;
    renderProjectsPage(data);
  });
  $('projectOwnerFilter')?.addEventListener('change', () => {
    state.projectOwner = $('projectOwnerFilter').value;
    renderProjectsPage(data);
  });
  document.querySelectorAll('[data-brief-field], [data-brief-scope], [data-brief-list]').forEach((field) => {
    field.addEventListener('input', () => activeRow && scheduleProjectBriefSave(activeRow));
  });
  document.querySelectorAll('[data-question-move]').forEach((button) => {
    button.addEventListener('click', () => {
      const [index, delta] = String(button.dataset.questionMove || '').split(':').map((value) => Number(value));
      moveTextareaLine('[data-brief-list="open_questions"]', index, delta);
    });
  });
  $('projectAddQuestion')?.addEventListener('click', () => {
    const textarea = document.querySelector('[data-brief-list="open_questions"]');
    if (!textarea || !activeRow) return;
    const lines = splitLines(textarea.value);
    lines.push('New open question');
    textarea.value = lines.join('\n');
    textarea.focus();
    textarea.dispatchEvent(new Event('input', { bubbles: true }));
  });
  $('projectBriefPreviewButton')?.addEventListener('click', () => {
    if (!activeRow) return;
    const payload = projectBriefPayload(activeRow);
    const preview = [
      `Research question: ${payload.research_question}`,
      `Decision supported: ${payload.decision_supported}`,
      `Inclusion criteria: ${payload.inclusion_criteria.length}`,
      `Open questions: ${payload.open_questions.length}`,
      `Definitions: ${payload.working_definitions.length}`,
      `Limitations: ${payload.limitations.length}`,
    ].join('\n');
    window.alert(preview);
  });
  $('projectBriefReviewButton')?.addEventListener('click', () => activeRow && sendProjectBriefToReview(activeRow));
  document.querySelectorAll('[data-route-target]').forEach((button) => {
    button.addEventListener('click', () => {
      state.project = button.dataset.project || '';
      if ($('projectSelect')) $('projectSelect').value = state.project;
      setRoute(button.dataset.routeTarget || 'projects');
    });
  });
}

function renderLibraryPage(data) {
  const rows = data.rows || data.results?.rows || [];
  if (!state.librarySelectedId && rows[0]?.evidence_id) state.librarySelectedId = rows[0].evidence_id;
  const summary = data.summary || {};
  const query = data.query || {};
  const preview = data.preview || null;
  const selectedIds = new Set(state.librarySelectedIds || []);
  const sourceKindOptions = [{ id: '', label: 'All source types' }].concat((data.facets || []).find((group) => group.id === 'source_type')?.items || []);
  $('routePage').innerHTML = `
    ${pageHeader('Source Library', 'Corpus workspace for source records, immutable captures, normalized extractions, artifacts, evidence links, and discovery provenance.', `
      <button id="libraryImportSource" class="secondary" type="button">Import manual source</button>
      <button id="libraryOpenSelected" type="button">Open selected</button>
    `)}
    ${metricCards([
      { label: 'Source records', value: summary.source_records ?? rows.length, hint: data.scope?.label || 'corpus' },
      { label: 'Immutable captures', value: summary.captures ?? 0 },
      { label: 'Normalized captures', value: summary.normalized_captures ?? 0 },
      { label: 'Version clusters', value: summary.duplicate_clusters ?? 0 },
      { label: 'New since view', value: summary.new_since_view ?? 0 },
    ])}
    <section class="library-shell">
      <aside class="panel library-facet-panel">
        <div class="panel-title-row"><h2>Scope</h2><span class="status-badge">${escapeHtml(query.mode || state.libraryMode)}</span></div>
        <label class="library-control"><span>Search scope</span>
          <select id="libraryScope">
            <option value="corpus" ${(query.scope || state.libraryScope) === 'corpus' ? 'selected' : ''}>Entire corpus</option>
            <option value="project" ${(query.scope || state.libraryScope) === 'project' || state.project ? 'selected' : ''}>Current project</option>
          </select>
        </label>
        <label class="library-control"><span>Search mode</span>
          <div class="segmented-control" id="libraryModeButtons">
            ${['exact', 'semantic', 'hybrid'].map((mode) => `<button type="button" data-library-mode="${mode}" class="${(query.mode || state.libraryMode) === mode ? 'active' : ''}">${escapeHtml(titleCase(mode))}</button>`).join('')}
          </div>
        </label>
        <label class="library-control"><span>Source type</span>
          <select id="librarySourceKind">
            ${sourceKindOptions.map((item) => `<option value="${escapeHtml(item.id)}" ${state.kind === item.id ? 'selected' : ''}>${escapeHtml(item.label)}</option>`).join('')}
          </select>
        </label>
        <label class="library-control"><span>Sort</span>
          <select id="librarySort">
            ${[
              ['relevance', 'Relevance / recent'],
              ['captured_desc', 'Captured date'],
              ['published_desc', 'Published date'],
              ['freshness', 'Freshness signals'],
            ].map(([value, label]) => `<option value="${value}" ${state.librarySort === value ? 'selected' : ''}>${label}</option>`).join('')}
          </select>
        </label>
        <div class="date-filter-grid">
          <label class="library-control"><span>From</span><input id="libraryDateFrom" type="date" value="${escapeHtml(state.libraryDateFrom)}"></label>
          <label class="library-control"><span>To</span><input id="libraryDateTo" type="date" value="${escapeHtml(state.libraryDateTo)}"></label>
        </div>
        <label class="checkbox-row"><input id="libraryIncludeArchived" type="checkbox" ${state.libraryIncludeArchived ? 'checked' : ''}> Include archived</label>
        <div class="saved-view-list library-saved-views">
          ${(data.saved_views || []).map((view) => `<button type="button" data-library-saved-view="${escapeHtml(view.id)}"><strong>${escapeHtml(view.label)}</strong><span>${escapeHtml(view.description || '')}</span></button>`).join('')}
        </div>
        ${(data.facets || []).map(renderLibraryFacetGroup).join('')}
      </aside>
      <section class="panel library-results-panel">
        <div class="library-search-strip">
          <label><span>${(state.libraryScope === 'project' || state.project) ? 'Project search' : 'Corpus search'}</span><input id="librarySearchInput" type="search" value="${escapeHtml(query.text ?? state.q)}" placeholder="Search titles, URLs, handles, extracted text, OCR, claims, or ids"></label>
          <button id="libraryClearFilters" class="secondary" type="button">Clear</button>
        </div>
        <div class="library-explanation">
          <span class="status-badge info">${escapeHtml(titleCase(query.mode || state.libraryMode))}</span>
          <p>${escapeHtml(query.explanation || '')}</p>
        </div>
        <div class="library-bulk-toolbar">
          <label><input id="librarySelectAll" type="checkbox"> Select page</label>
          <button class="secondary" data-library-action="add_to_project" type="button">Add to project</button>
          <button class="secondary" data-library-action="assign_review" type="button">Assign review</button>
          <button class="secondary" data-library-action="merge_cluster" type="button">Merge cluster</button>
          <button class="secondary danger-button" data-library-action="archive" type="button">Archive</button>
          <span id="libraryActionStatus" class="muted"></span>
        </div>
        <div class="library-results-list">
          ${rows.map((row) => renderLibraryResultRow(row, selectedIds)).join('') || '<div class="empty-state"><h2>No source records</h2><p>Try a broader query, remove filters, or import a manual source.</p></div>'}
        </div>
      </section>
      <aside class="panel library-preview-panel">
        ${renderLibraryPreview(preview)}
      </aside>
    </section>
  `;
  wireLibraryEvents(data);
}

function renderLibraryFacetGroup(group) {
  const items = group.items || [];
  if (!items.length) return '';
  return `
    <section class="library-facet-group">
      <h3>${escapeHtml(group.label || titleCase(group.id))}</h3>
      <div class="facet-list compact">
        ${items.slice(0, 12).map((item) => `
          <button type="button" class="facet" data-library-facet-group="${escapeHtml(group.id)}" data-library-facet-id="${escapeHtml(item.id)}">
            <span>${escapeHtml(item.label || item.id || '(blank)')}</span>
            <strong class="count">${escapeHtml(item.count ?? 0)}</strong>
          </button>
        `).join('')}
      </div>
    </section>
  `;
}

function renderLibraryResultRow(row, selectedIds) {
  const id = row.evidence_id || '';
  const active = state.librarySelectedId === id;
  const checked = selectedIds.has(id);
  const layerClass = row.source_layer === 'discovery provenance' ? 'warn' : row.review_state === 'review-linked' ? 'ok' : '';
  return `
    <article class="library-source-row ${active ? 'active' : ''}" data-library-id="${escapeHtml(id)}">
      <input class="library-check" type="checkbox" ${checked ? 'checked' : ''} aria-label="Select source record">
      <span class="source-glyph">${escapeHtml(sourceGlyph(row.source_kind))}</span>
      <div class="library-source-main">
        <div class="library-title-line">
          <strong>${escapeHtml(titleFor(row))}</strong>
          <span class="status-badge ${escapeHtml(layerClass)}">${escapeHtml(row.source_layer || row.source_label || 'source')}</span>
          ${row.duplicate_state === 'candidate_duplicate' ? '<span class="status-badge warn">version cluster</span>' : ''}
        </div>
        <p>${escapeHtml(row.snippet || row.canonical_url || id)}</p>
        <div class="row-meta">
          <span class="pill">${escapeHtml(row.source_label || row.source_kind)}</span>
          ${row.author_handle ? `<span class="pill">@${escapeHtml(row.author_handle)}</span>` : ''}
          ${row.domain ? `<span class="pill">${escapeHtml(row.domain)}</span>` : ''}
          ${row.source_project ? `<span class="pill">${escapeHtml(row.source_project)}</span>` : ''}
          <span class="pill">${escapeHtml(row.observations || 0)} capture${Number(row.observations || 0) === 1 ? '' : 's'}</span>
          ${row.artifact_available ? '<span class="pill ok">artifacts</span>' : ''}
          ${row.has_ocr || row.ocr_count ? '<span class="pill ok">OCR</span>' : ''}
          ${row.vl_count ? '<span class="pill ok">VL</span>' : ''}
        </div>
        <div class="match-line">${escapeHtml(row.match_explanation || 'Matched captured source metadata.')}</div>
      </div>
      <div class="library-source-counts">
        <span><strong>${escapeHtml(row.evidence_count || 0)}</strong> evidence</span>
        <span><strong>${escapeHtml(row.claim_count || 0)}</strong> claims</span>
        <span><strong>${escapeHtml(row.entity_count || 0)}</strong> entities</span>
        <em>${escapeHtml(fmtDate(row.last_ingested_at) || 'no date')}</em>
      </div>
    </article>
  `;
}

function renderLibraryPreview(preview) {
  if (!preview) {
    return `
      <div class="empty-state">
        <h2>Source Preview</h2>
        <p>Select a source record to inspect source identity, capture history, extraction state, artifacts, evidence, claims, entities, and review work before opening the Source Workbench.</p>
      </div>
    `;
  }
  const source = preview.source || {};
  const counts = preview.counts || {};
  const artifacts = preview.artifacts || [];
  const review = preview.review || {};
  const captures = preview.captures || [];
  const activeTab = ['overview', 'captures', 'artifacts', 'research'].includes(state.libraryPreviewTab) ? state.libraryPreviewTab : 'overview';
  const tabButton = (id, label) => `<button type="button" data-library-preview-tab="${id}" class="${activeTab === id ? 'active' : ''}">${label}</button>`;
  const sectionClass = (id) => `library-preview-section ${activeTab === id ? 'active' : ''}`;
  return `
    <div class="library-preview-head">
      <span class="source-glyph">${escapeHtml(sourceGlyph(source.source_kind))}</span>
      <div>
        <h2>${escapeHtml(source.title || source.canonical_url || source.evidence_id || 'Source record')}</h2>
        <p>${escapeHtml([source_kind_labelClient(source.source_kind), source.author_handle ? '@' + source.author_handle : source.domain, fmtDate(source.captured_at)].filter(Boolean).join(' · '))}</p>
      </div>
    </div>
    <nav class="library-preview-tabs" aria-label="Source preview layers">
      ${tabButton('overview', 'Overview')}
      ${tabButton('captures', 'Captures')}
      ${tabButton('artifacts', 'Artifacts')}
      ${tabButton('research', 'Research')}
    </nav>
    <section class="${sectionClass('overview')}" data-library-preview-section="overview">
      <div class="library-layer-stack">
        ${libraryLayerRow('Source record', source.evidence_id || '', 'Mutable logical identity; groups captures and research links.')}
        ${libraryLayerRow('Immutable captures', counts.captures || 0, 'Frozen observations with timestamps, hashes, and collection context.')}
        ${libraryLayerRow('Normalized extraction', source.text ? `${String(source.text).length} chars` : 'missing', 'Parsed text, OCR, transcript, VL output, and proposed structure remain observations.')}
        ${libraryLayerRow('Artifact manifest', counts.artifacts || 0, 'DOM, screenshots, PDFs, media, OCR/VL files, source bundles, or repo files.')}
        ${libraryLayerRow('Curated research', `${counts.evidence || 0} evidence · ${counts.claims || 0} claims`, 'Human-selected evidence and claim records with anchors.')}
      </div>
      <section class="preview-card">
        <h4>Discovery trail</h4>
        <p>${source.source_kind === 'google_search_page' || source.source_kind === 'search_result' ? 'This record is discovery provenance. The opened captured page should become the substantive source unless the search result itself is being studied.' : 'This record can be used as a substantive source if its capture and normalized extraction are sufficient.'}</p>
        ${source.canonical_url ? `<a href="${escapeHtml(source.canonical_url)}" target="_blank" rel="noreferrer">${escapeHtml(source.canonical_url)}</a>` : ''}
      </section>
    </section>
    <section class="${sectionClass('captures')}" data-library-preview-section="captures">
      <section class="preview-card">
        <h4>Current capture</h4>
        <div class="source-trail">
          <span><strong>Captured</strong>${escapeHtml(fmtDate(source.captured_at) || 'unknown')}</span>
          <span><strong>Ingested</strong>${escapeHtml(fmtDate(source.ingested_at) || 'unknown')}</span>
          <span><strong>Collector</strong>${escapeHtml(source.collector_run_id || 'unknown')}</span>
          <span><strong>Project</strong>${escapeHtml(source.source_project || '(unassigned)')}</span>
        </div>
      </section>
      <section class="preview-card">
        <h4>Capture history</h4>
        <div class="library-capture-list">
          ${captures.length ? captures.slice(0, 8).map((capture, index) => `
            <div class="library-capture-row">
              <span>${String(index + 1).padStart(2, '0')}</span>
              <strong>${escapeHtml(fmtDate(capture.ingested_at || capture.captured_at) || 'unknown')}</strong>
              <em>${escapeHtml(capture.collector_run_id || capture.capture_method || 'capture')}</em>
            </div>
          `).join('') : '<p>No immutable capture rows are linked yet.</p>'}
        </div>
      </section>
    </section>
    <section class="${sectionClass('artifacts')}" data-library-preview-section="artifacts">
      <section class="preview-card">
        <h4>Artifact manifest</h4>
        ${artifacts.length ? `<div class="artifact-link-list">${artifacts.slice(0, 10).map((item) => `<a href="${escapeHtml(item.url || '#')}" target="_blank" rel="noreferrer">${escapeHtml(item.path || item.url)}</a>`).join('')}</div>` : '<p>No artifact paths are linked to this source yet.</p>'}
        <div class="tag-line">
          <span class="pill">${escapeHtml(counts.ocr || 0)} OCR</span>
          <span class="pill">${escapeHtml(counts.vl || 0)} VL</span>
          <span class="pill">${escapeHtml(counts.annotations || 0)} annotations</span>
        </div>
      </section>
    </section>
    <section class="${sectionClass('research')}" data-library-preview-section="research">
      <section class="preview-card">
        <h4>Review objects</h4>
        <div class="source-trail">
          <span><strong>Evidence</strong>${escapeHtml(counts.evidence || 0)}</span>
          <span><strong>Claims</strong>${escapeHtml(counts.claims || 0)}</span>
          <span><strong>Entities</strong>${escapeHtml(counts.entities || 0)}</span>
          <span><strong>Facts</strong>${escapeHtml((review.proposed_facts || []).length)}</span>
        </div>
      </section>
    </section>
    <div id="libraryPreviewActionStatus" class="review-status muted"></div>
    <div class="library-preview-actions">
      <button class="secondary" type="button" data-library-preview-action="assign_review">Assign review</button>
      <button class="secondary" type="button" data-library-preview-action="archive">Archive</button>
      <button type="button" data-library-preview-action="open_workbench">Open workbench</button>
    </div>
  `;
}

function source_kind_labelClient(kind) {
  const labels = {
    x_post: 'X post',
    x_account: 'X account',
    x_page: 'X page',
    web_page: 'Web/blog',
    search_result: 'Search result',
    google_search_page: 'Google SERP',
    media: 'Media',
    user_input: 'Manual doc',
  };
  return labels[kind] || titleCase(kind || 'source');
}

function libraryLayerRow(label, value, detail) {
  return `
    <div>
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
      <p>${escapeHtml(detail)}</p>
    </div>
  `;
}

function wireLibraryEvents(data) {
  const reload = () => {
    replaceRouteHash();
    loadRoutePage();
  };
  $('librarySearchInput')?.addEventListener('input', () => {
    state.q = $('librarySearchInput').value.trim();
    if ($('searchInput') && $('searchInput').value !== state.q) $('searchInput').value = state.q;
    clearTimeout(window.__libraryTimer);
    window.__libraryTimer = setTimeout(reload, 300);
  });
  document.querySelectorAll('[data-library-mode]').forEach((button) => {
    button.addEventListener('click', () => {
      state.libraryMode = button.dataset.libraryMode || 'hybrid';
      reload();
    });
  });
  $('libraryScope')?.addEventListener('change', () => {
    state.libraryScope = $('libraryScope').value || 'corpus';
    if (state.libraryScope === 'corpus') state.project = '';
    reload();
  });
  $('librarySourceKind')?.addEventListener('change', () => {
    state.kind = $('librarySourceKind').value;
    reload();
  });
  $('librarySort')?.addEventListener('change', () => {
    state.librarySort = $('librarySort').value;
    reload();
  });
  $('libraryDateFrom')?.addEventListener('change', () => {
    state.libraryDateFrom = $('libraryDateFrom').value;
    reload();
  });
  $('libraryDateTo')?.addEventListener('change', () => {
    state.libraryDateTo = $('libraryDateTo').value;
    reload();
  });
  $('libraryIncludeArchived')?.addEventListener('change', () => {
    state.libraryIncludeArchived = $('libraryIncludeArchived').checked;
    reload();
  });
  $('libraryClearFilters')?.addEventListener('click', () => {
    state.q = '';
    state.kind = '';
    state.project = '';
    state.libraryMode = 'hybrid';
    state.libraryScope = 'corpus';
    state.librarySort = 'relevance';
    state.libraryDateFrom = '';
    state.libraryDateTo = '';
    state.libraryIncludeArchived = false;
    state.librarySelectedId = '';
    state.librarySelectedIds = new Set();
    if ($('searchInput')) $('searchInput').value = '';
    reload();
  });
  document.querySelectorAll('.library-source-row[data-library-id]').forEach((row) => {
    row.addEventListener('click', () => {
      state.librarySelectedId = row.dataset.libraryId || '';
      reload();
    });
    row.querySelector('.library-check')?.addEventListener('click', (event) => {
      event.stopPropagation();
      const id = row.dataset.libraryId || '';
      if (!id) return;
      if (event.currentTarget.checked) state.librarySelectedIds.add(id);
      else state.librarySelectedIds.delete(id);
    });
  });
  $('librarySelectAll')?.addEventListener('change', () => {
    const checked = $('librarySelectAll').checked;
    (data.rows || data.results?.rows || []).forEach((row) => {
      if (!row.evidence_id) return;
      if (checked) state.librarySelectedIds.add(row.evidence_id);
      else state.librarySelectedIds.delete(row.evidence_id);
    });
    document.querySelectorAll('.library-check').forEach((box) => { box.checked = checked; });
  });
  document.querySelectorAll('[data-library-action], [data-library-preview-action]').forEach((button) => {
    button.addEventListener('click', async () => applyLibraryAction(button.dataset.libraryAction || button.dataset.libraryPreviewAction));
  });
  document.querySelectorAll('[data-library-preview-tab]').forEach((button) => {
    button.addEventListener('click', () => {
      state.libraryPreviewTab = button.dataset.libraryPreviewTab || 'overview';
      document.querySelectorAll('[data-library-preview-tab]').forEach((tab) => tab.classList.toggle('active', tab === button));
      document.querySelectorAll('[data-library-preview-section]').forEach((section) => {
        section.classList.toggle('active', section.dataset.libraryPreviewSection === state.libraryPreviewTab);
      });
    });
  });
  $('libraryOpenSelected')?.addEventListener('click', () => applyLibraryAction('open_workbench'));
  $('libraryImportSource')?.addEventListener('click', () => {
    const status = $('libraryActionStatus');
    if (status) status.textContent = 'Manual source import will use the capture/source adapter flow; use Inbox capture for now.';
  });
  document.querySelectorAll('[data-library-facet-group]').forEach((button) => {
    button.addEventListener('click', () => {
      const group = button.dataset.libraryFacetGroup;
      const id = button.dataset.libraryFacetId || '';
      if (group === 'source_type') state.kind = id;
      if (group === 'project') state.project = id;
      reload();
    });
  });
  document.querySelectorAll('[data-library-saved-view]').forEach((button) => {
    button.addEventListener('click', () => {
      const view = button.dataset.librarySavedView || '';
      if (view === 'versions') state.librarySort = 'freshness';
      if (view === 'google-provenance') state.kind = 'google_search_page';
      if (view === 'needs-extraction') state.librarySort = 'freshness';
      reload();
    });
  });
}

async function applyLibraryAction(action) {
  const ids = Array.from(state.librarySelectedIds || []);
  if (!ids.length && state.librarySelectedId) ids.push(state.librarySelectedId);
  const status = $('libraryActionStatus') || $('libraryPreviewActionStatus');
  if (!ids.length) {
    if (status) status.textContent = 'Select at least one source record.';
    return;
  }
  if (action === 'open_workbench') {
    await selectSource(ids[0]);
    return;
  }
  try {
    if (status) status.textContent = `${titleCase(action)}...`;
    await postJson('/api/library/actions', {
      action,
      source_ids: ids,
      project: state.project || '',
      target_project: state.project || '',
      note: `Library ${action} from Source Library page`,
      idempotency_key: `library-${action}-${Date.now()}`,
    });
    if (status) status.textContent = `${titleCase(action)} recorded for ${ids.length} source${ids.length === 1 ? '' : 's'}.`;
    await loadRoutePage();
  } catch (error) {
    if (status) status.textContent = error.message;
  }
}

function evidenceRowKey(row) {
  return row.ledger_id || [row.object_type, row.object_id || row.source_evidence_id].filter(Boolean).join(':');
}

function evidenceTitleFor(row) {
  return row.quote || row.proposed_fact || row.normalized_observation || row.title || row.canonical_url || row.source_evidence_id || '(untitled evidence)';
}

function evidenceObjectGlyph(row) {
  if (row.object_type === 'proposed_fact') return 'F';
  if (row.object_type === 'claim_stub') return 'C';
  if (row.object_type === 'entity_link') return 'E';
  if (row.object_type === 'normalized_correction') return 'N';
  if (row.object_type === 'annotation') return 'A';
  if (row.object_type === 'evidence_candidate') return sourceGlyph(row.source_kind);
  return 'S';
}

function evidenceFacetGroup(title, items, activeValue, filterName) {
  const options = items || [];
  return `
    <section class="evidence-facet-group">
      <h3>${escapeHtml(title)}</h3>
      <button class="facet ${activeValue ? '' : 'active'}" type="button" data-evidence-filter="${escapeHtml(filterName)}" data-filter-value="">
        <span>All ${escapeHtml(title.toLowerCase())}</span><strong>${escapeHtml(options.reduce((sum, item) => sum + Number(item.count || 0), 0))}</strong>
      </button>
      <div class="facet-list compact">
        ${options.map((item) => `
          <button class="facet ${activeValue === item.id ? 'active' : ''}" type="button" data-evidence-filter="${escapeHtml(filterName)}" data-filter-value="${escapeHtml(item.id)}">
            <span>${escapeHtml(item.label || item.id)}</span><strong>${escapeHtml(item.count || 0)}</strong>
          </button>
        `).join('')}
      </div>
    </section>
  `;
}

function evidenceLayerSummary(row) {
  return `
    <div class="evidence-layer-stack">
      <div><span>Immutable source</span><strong>${escapeHtml(row.title || row.canonical_url || row.source_evidence_id || 'Source record')}</strong></div>
      <div><span>Review object</span><strong>${escapeHtml(titleCase(row.object_type || 'evidence'))} · ${escapeHtml(row.review_state || 'open')}</strong></div>
      <div><span>Normalized observation</span><strong>${escapeHtml(row.normalized_observation || 'No normalized observation attached')}</strong></div>
      <div><span>Structured fact / claim</span><strong>${escapeHtml(row.proposed_fact || row.claim_conflict_label || 'Not promoted')}</strong></div>
    </div>
  `;
}

function renderEvidencePreview(data) {
  const preview = data.preview || {};
  const row = preview.row || null;
  if (!row) {
    return `
      <div class="empty-state">
        <h2>Evidence Detail</h2>
        <p>Select a ledger row to inspect its source, review object, normalized observation, linked claims, and provenance.</p>
      </div>
    `;
  }
  const activeTab = ['overview', 'provenance', 'observation', 'claims'].includes(state.evidencePreviewTab) ? state.evidencePreviewTab : 'overview';
  const previewTab = (id, label) => `<button class="${activeTab === id ? 'active' : ''}" type="button" data-evidence-preview-tab="${id}">${label}</button>`;
  const sectionClass = (id) => `evidence-preview-section ${activeTab === id ? 'active' : ''}`;
  const linkedFacts = preview.linked_facts || [];
  const linkedClaims = preview.linked_claims || [];
  const corrections = preview.linked_corrections || [];
  const annotations = preview.linked_annotations || [];
  const source = preview.source || {};
  return `
    <div class="evidence-preview-head">
      <span class="source-glyph">${escapeHtml(evidenceObjectGlyph(row))}</span>
      <div>
        <h2>${escapeHtml(evidenceTitleFor(row))}</h2>
        <p>${escapeHtml([row.source_label, row.author_handle ? '@' + row.author_handle : row.domain, fmtDate(row.updated_at)].filter(Boolean).join(' · '))}</p>
      </div>
    </div>

    <nav class="evidence-preview-tabs" aria-label="Evidence detail sections">
      ${previewTab('overview', 'Overview')}
      ${previewTab('provenance', 'Provenance')}
      ${previewTab('observation', 'Observation')}
      ${previewTab('claims', 'Claims')}
    </nav>

    <section class="${sectionClass('overview')}" data-evidence-preview-section="overview">
      ${evidenceLayerSummary(row)}
      <div class="evidence-warning">
        Accepting this row updates only <strong>${escapeHtml(titleCase(row.object_type || 'this object'))}</strong>. It does not accept linked proposed facts, claims, or corrections.
      </div>
      ${row.note ? `<p class="muted">${escapeHtml(row.note)}</p>` : ''}
      <div class="tag-line">
        <span class="pill">${escapeHtml(row.evidence_type || 'evidence')}</span>
        <span class="pill">${escapeHtml(row.anchor_type || 'source_record')}</span>
        <span class="pill">${escapeHtml(row.review_state || 'open')}</span>
        ${row.claim_conflict ? '<span class="pill warn">possible conflict</span>' : ''}
      </div>
    </section>

    <section class="${sectionClass('provenance')}" data-evidence-preview-section="provenance">
      <div class="evidence-provenance-stack">
        ${(preview.provenance || []).map((step, index) => `
          <article>
            <span>${String(index + 1).padStart(2, '0')}</span>
            <div>
              <strong>${escapeHtml(step.label)}</strong>
              <p>${escapeHtml(step.value)}</p>
              ${step.meta ? `<em>${escapeHtml(step.meta)}</em>` : ''}
            </div>
          </article>
        `).join('')}
      </div>
      <div class="source-trail">
        <span><strong>Capture ref</strong>${escapeHtml(row.capture_ref || 'not recorded')}</span>
        <span><strong>Capture hash</strong>${escapeHtml(row.capture_hash || 'not recorded')}</span>
        <span><strong>Source ID</strong>${escapeHtml(row.source_evidence_id || '')}</span>
        <span><strong>Object ID</strong>${escapeHtml(row.object_id || '')}</span>
      </div>
      ${source.canonical_url ? `<p><a href="${escapeHtml(source.canonical_url)}" target="_blank" rel="noreferrer">${escapeHtml(source.canonical_url)}</a></p>` : ''}
    </section>

    <section class="${sectionClass('observation')}" data-evidence-preview-section="observation">
      <article class="evidence-preview-card">
        <h4>Evidence anchor</h4>
        <p>${escapeHtml(row.quote || row.anchor_label || 'No anchor text recorded.')}</p>
      </article>
      <article class="evidence-preview-card">
        <h4>Machine / normalized observation</h4>
        <p>${escapeHtml(row.normalized_observation || 'No normalized observation recorded for this ledger row.')}</p>
      </article>
      <article class="evidence-preview-card">
        <h4>Linked proposed facts (${linkedFacts.length})</h4>
        ${linkedFacts.map((fact) => `<p><strong>${escapeHtml(fact.fact_type || 'fact')}</strong> · ${escapeHtml(fact.status || '')}<br>${escapeHtml(fact.normalized_value || fact.raw_value || fact.evidence_quote || '')}</p>`).join('') || '<p class="muted">No linked proposed facts.</p>'}
      </article>
      <article class="evidence-preview-card">
        <h4>Corrections / annotations</h4>
        ${corrections.map((item) => `<p><strong>${escapeHtml(item.correction_kind || 'correction')}</strong> · ${escapeHtml(item.status || '')}<br>${escapeHtml(item.corrected_text || '')}</p>`).join('')}
        ${annotations.map((item) => `<p><strong>${escapeHtml(item.annotation_type || 'annotation')}</strong> · ${escapeHtml(item.status || '')}<br>${escapeHtml(item.body || '')}</p>`).join('')}
        ${!corrections.length && !annotations.length ? '<p class="muted">No corrections or annotations linked yet.</p>' : ''}
      </article>
    </section>

    <section class="${sectionClass('claims')}" data-evidence-preview-section="claims">
      <article class="evidence-preview-card">
        <h4>Linked claims (${linkedClaims.length})</h4>
        ${linkedClaims.map((claim) => `
          <p>
            <strong>${escapeHtml(claim.claim_type || 'claim')}</strong> · ${escapeHtml(claim.evidence_relation || '')} · ${escapeHtml(claim.status || '')}<br>
            ${escapeHtml(claim.claim_text || '')}
          </p>
        `).join('') || '<p class="muted">No linked claims.</p>'}
      </article>
      <div class="evidence-warning">
        Claims remain contestable publication candidates until separately reviewed against their supporting evidence.
      </div>
    </section>

    <label class="preview-note">Decision note
      <input id="evidenceDecisionNote" placeholder="Optional decision note, claim link target, taxonomy label, or export context">
    </label>
    <div id="evidenceActionStatus" class="review-status muted"></div>
    <div class="evidence-preview-actions">
      <button class="secondary" data-evidence-action="assign_review">Assign</button>
      <button class="secondary" data-evidence-action="defer">Defer</button>
      <button class="secondary" data-evidence-action="reject">Reject</button>
      <button class="secondary" data-evidence-action="link_claim">Link claim</button>
      <button class="secondary" data-evidence-action="create_claim">Create claim</button>
      <button class="secondary" data-evidence-action="change_type">Change type</button>
      <button class="secondary" data-evidence-action="taxonomy">Taxonomy</button>
      <button class="secondary" data-evidence-action="export_publication">Export</button>
      <button class="secondary" data-evidence-action="open_workbench">Open source</button>
      <button data-evidence-action="accept">Accept & next</button>
    </div>
  `;
}

function renderEvidencePage(data) {
  const rows = data.rows || data.results?.rows || [];
  state.evidenceRows = rows;
  if (!state.evidenceSelectedId || !rows.some((row) => evidenceRowKey(row) === state.evidenceSelectedId)) {
    state.evidenceSelectedId = data.selected_id || (rows[0] ? evidenceRowKey(rows[0]) : '');
  }
  const summary = data.summary || {};
  const facets = data.facets || {};
  const selectedId = state.evidenceSelectedId;
  $('routePage').innerHTML = `
    ${pageHeader('Evidence Ledger', 'Review evidence objects, candidates, anchors, derived observations, and claim links without collapsing their provenance layers.')}
    ${metricCards([
      { label: 'Visible objects', value: summary.visible ?? rows.length },
      { label: 'Selections', value: summary.selections ?? 0 },
      { label: 'Proposed facts', value: summary.proposed_facts ?? 0 },
      { label: 'Claim conflicts', value: summary.claim_conflicts ?? 0 },
    ])}
    <section class="evidence-shell">
      <aside class="panel evidence-filter-panel">
        <label class="library-control"><span>Review mode</span>
          <div class="segmented-control">
            ${['exact', 'semantic', 'hybrid'].map((mode) => `<button class="${state.evidenceMode === mode ? 'active' : ''}" type="button" data-evidence-mode="${mode}">${escapeHtml(titleCase(mode))}</button>`).join('')}
          </div>
        </label>
        ${evidenceFacetGroup('Evidence type', facets.evidence_types, state.evidenceType, 'type')}
        ${evidenceFacetGroup('Review state', facets.review_states, state.evidenceReviewState, 'review_state')}
        ${evidenceFacetGroup('Source kind', facets.source_kinds, state.evidenceSourceKind, 'source_kind')}
        ${evidenceFacetGroup('Anchor type', facets.anchor_types, '', 'anchor_type')}
      </aside>

      <section class="panel evidence-ledger-panel">
        <div class="evidence-search-strip">
          <label><span>Evidence search</span><input id="evidenceSearchInput" value="${escapeHtml(state.q)}" placeholder="Search quotes, anchors, claims, URLs, sources"></label>
          <button class="secondary" id="evidenceClearFilters">Clear</button>
        </div>
        <div class="evidence-explanation">
          <span class="status-badge info">${escapeHtml(titleCase(state.evidenceMode || 'hybrid'))}</span>
          <p>${escapeHtml(data.scope?.q ? `Filtered by "${data.scope.q}".` : 'Showing reviewable evidence objects and source candidates by latest activity.')}</p>
        </div>
        <div class="evidence-bulk-toolbar">
          <label><input type="checkbox" id="evidenceSelectAll"> Select visible</label>
          ${['accept', 'reject', 'defer', 'assign_review', 'link_claim', 'create_claim', 'change_type', 'taxonomy', 'export_publication'].map((action) => `<button class="secondary" data-evidence-bulk-action="${action}">${escapeHtml(titleCase(action))}</button>`).join('')}
          <span id="evidenceBulkStatus" class="muted"></span>
        </div>
        <div class="evidence-results-list">
          ${rows.length ? rows.map((row) => {
            const rowKey = evidenceRowKey(row);
            const selected = rowKey === selectedId;
            return `
              <article class="evidence-row ${selected ? 'active' : ''}" data-ledger-id="${escapeHtml(rowKey)}" data-source-id="${escapeHtml(row.source_evidence_id || '')}" data-object-type="${escapeHtml(row.object_type || '')}">
                <input class="evidence-check" type="checkbox" aria-label="Select evidence object" ${state.evidenceSelectedIds.has(rowKey) ? 'checked' : ''}>
                <span class="source-glyph">${escapeHtml(evidenceObjectGlyph(row))}</span>
                <div class="evidence-row-main">
                  <div class="evidence-title-line">
                    <strong>${escapeHtml(evidenceTitleFor(row))}</strong>
                    ${row.claim_conflict ? '<span class="pill warn">conflict</span>' : ''}
                  </div>
                  <p>${escapeHtml(row.match_explanation || row.immutable_note || '')}</p>
                  <div class="row-meta">
                    <span class="pill">${escapeHtml(titleCase(row.object_type || 'evidence'))}</span>
                    <span class="pill">${escapeHtml(row.evidence_type || 'evidence')}</span>
                    <span class="pill">${escapeHtml(row.review_state || 'open')}</span>
                    <span class="pill">${escapeHtml(row.anchor_type || 'source_record')}</span>
                    ${row.source_label ? `<span class="pill">${escapeHtml(row.source_label)}</span>` : ''}
                    ${row.author_handle ? `<span class="pill">@${escapeHtml(row.author_handle)}</span>` : ''}
                    ${row.domain ? `<span class="pill">${escapeHtml(row.domain)}</span>` : ''}
                  </div>
                </div>
                <div class="evidence-row-counts">
                  <strong>${escapeHtml(row.fact_count || 0)}</strong><em>facts</em>
                  <strong>${escapeHtml(row.claim_count || 0)}</strong><em>claims</em>
                  <strong>${escapeHtml(row.annotation_count || 0)}</strong><em>notes</em>
                </div>
              </article>
            `;
          }).join('') : '<div class="empty-state"><h2>No evidence objects</h2><p>Try a different search, source filter, or review-state filter.</p></div>'}
        </div>
      </section>

      <aside class="panel evidence-detail-panel">
        ${renderEvidencePreview(data)}
      </aside>
    </section>
  `;
  bindEvidencePage(data);
}

function evidenceReviewStatusForAction(row, action) {
  const objectType = row.object_type || '';
  if (action === 'accept') return acceptStatusByObject[objectType] || 'accepted';
  if (action === 'reject') return rejectStatusByObject[objectType] || 'rejected';
  if (action === 'defer') return deferStatusByObject[objectType] || 'open';
  return '';
}

function evidenceEventTypeForAction(action) {
  return {
    accept: 'evidence.review_action.recorded',
    reject: 'evidence.review_action.recorded',
    defer: 'evidence.review_action.recorded',
    assign_review: 'evidence.assignment.recorded',
    link_claim: 'evidence.claim_link.requested',
    create_claim: 'evidence.claim_create.requested',
    change_type: 'evidence.type_change.requested',
    taxonomy: 'evidence.taxonomy_label.requested',
    export_publication: 'evidence.publication_export.requested',
  }[action] || 'evidence.action.recorded';
}

function evidenceAnchorForRow(row, action) {
  return {
    kind: 'evidence_ledger_object',
    ledger_id: evidenceRowKey(row),
    source_evidence_id: row.source_evidence_id || '',
    object_type: row.object_type || '',
    object_id: row.object_id || '',
    evidence_type: row.evidence_type || '',
    anchor_type: row.anchor_type || '',
    action,
  };
}

async function persistEvidenceAction(row, action, note = '') {
  if (!row) return;
  if (action === 'open_workbench') {
    await selectSource(row.source_evidence_id);
    return;
  }
  if (['accept', 'reject', 'defer'].includes(action) && row.can_update_review_state && reviewStatusOptions[row.object_type]) {
    await postJson('/api/review-state', {
      source_evidence_id: row.source_evidence_id || '',
      source_project: row.source_project || '',
      project: row.source_project || state.project || '',
      subject_type: row.object_type || '',
      subject_id: row.object_id || '',
      status: evidenceReviewStatusForAction(row, action),
      note,
      source_anchor: evidenceAnchorForRow(row, action),
      idempotency_key: `${evidenceRowKey(row)}:${action}:${Date.now()}`,
    });
    return;
  }
  await postJson('/api/review/events', {
    event_type: evidenceEventTypeForAction(action),
    source_evidence_id: row.source_evidence_id || '',
    source_project: row.source_project || '',
    project: row.source_project || state.project || '',
    subject_type: row.object_type || 'evidence_candidate',
    subject_id: row.object_id || evidenceRowKey(row),
    action,
    decision: previewDecisionForAction(action),
    status: previewDecisionForAction(action),
    note,
    source_anchor: evidenceAnchorForRow(row, action),
    idempotency_key: `${evidenceRowKey(row)}:${action}:${Date.now()}`,
  });
}

function nextEvidenceSelectionAfter(row) {
  const rows = state.evidenceRows || [];
  const index = rows.findIndex((item) => evidenceRowKey(item) === evidenceRowKey(row));
  const next = rows[index + 1] || rows[index - 1] || null;
  return next ? evidenceRowKey(next) : '';
}

async function applyEvidenceAction(row, action) {
  const status = $('evidenceActionStatus') || $('evidenceBulkStatus');
  const note = $('evidenceDecisionNote')?.value || '';
  if (!row) {
    if (status) status.textContent = 'Select an evidence row first.';
    return;
  }
  if (status) status.textContent = `${titleCase(action)}...`;
  await persistEvidenceAction(row, action, note);
  if (['accept', 'reject', 'defer'].includes(action)) {
    state.evidenceSelectedId = nextEvidenceSelectionAfter(row);
  }
  state.evidenceSelectedIds.clear();
  if (status) status.textContent = `${titleCase(action)} recorded.`;
  replaceRouteHash();
  await loadRoutePage();
}

async function applyBulkEvidenceAction(action) {
  const status = $('evidenceBulkStatus');
  const selectedIds = Array.from(document.querySelectorAll('.evidence-row .evidence-check:checked'))
    .map((checkbox) => checkbox.closest('.evidence-row')?.dataset.ledgerId)
    .filter(Boolean);
  const selectedRows = state.evidenceRows.filter((row) => selectedIds.includes(evidenceRowKey(row)));
  if (!selectedRows.length) {
    if (status) status.textContent = 'Select at least one evidence object.';
    return;
  }
  if (status) status.textContent = `${titleCase(action)} ${selectedRows.length} evidence object${selectedRows.length === 1 ? '' : 's'}...`;
  for (const row of selectedRows) {
    await persistEvidenceAction(row, action, `Bulk ${titleCase(action)} from Evidence Ledger`);
  }
  state.evidenceSelectedIds.clear();
  if (status) status.textContent = `${titleCase(action)} recorded for ${selectedRows.length}.`;
  await loadRoutePage();
}

function moveEvidenceSelection(delta) {
  if (state.route !== 'evidence') return;
  const rows = state.evidenceRows || [];
  if (!rows.length) return;
  const current = rows.findIndex((row) => evidenceRowKey(row) === state.evidenceSelectedId);
  const nextIndex = Math.max(0, Math.min(rows.length - 1, (current >= 0 ? current : 0) + delta));
  state.evidenceSelectedId = evidenceRowKey(rows[nextIndex]);
  replaceRouteHash();
  loadRoutePage();
}

function bindEvidenceKeyboard() {
  if (window.__webOsintEvidenceKeyboardBound) return;
  window.__webOsintEvidenceKeyboardBound = true;
  window.addEventListener('keydown', async (event) => {
    if (state.route !== 'evidence') return;
    const active = document.activeElement;
    if (active && ['INPUT', 'TEXTAREA', 'SELECT', 'BUTTON'].includes(active.tagName)) return;
    const key = event.key.toLowerCase();
    if (key === 'j') {
      event.preventDefault();
      moveEvidenceSelection(1);
    } else if (key === 'k') {
      event.preventDefault();
      moveEvidenceSelection(-1);
    } else if (['a', 'r', 'd'].includes(key)) {
      event.preventDefault();
      const row = state.evidenceRows.find((item) => evidenceRowKey(item) === state.evidenceSelectedId);
      const action = key === 'a' ? 'accept' : key === 'r' ? 'reject' : 'defer';
      try {
        await applyEvidenceAction(row, action);
      } catch (error) {
        const status = $('evidenceActionStatus') || $('evidenceBulkStatus');
        if (status) status.textContent = error.message;
      }
    }
  });
}

function bindEvidencePage(data) {
  document.querySelectorAll('[data-evidence-mode]').forEach((button) => {
    button.addEventListener('click', () => {
      state.evidenceMode = button.dataset.evidenceMode || 'hybrid';
      replaceRouteHash();
      loadRoutePage();
    });
  });
  document.querySelectorAll('[data-evidence-filter]').forEach((button) => {
    button.addEventListener('click', () => {
      const filter = button.dataset.evidenceFilter;
      const value = button.dataset.filterValue || '';
      if (filter === 'type') state.evidenceType = value;
      if (filter === 'review_state') state.evidenceReviewState = value;
      if (filter === 'source_kind') state.evidenceSourceKind = value;
      if (filter === 'anchor_type') state.evidenceAnchorType = value;
      state.evidenceSelectedId = '';
      replaceRouteHash();
      loadRoutePage();
    });
  });
  $('evidenceSearchInput')?.addEventListener('input', () => {
    state.q = $('evidenceSearchInput').value.trim();
    clearTimeout(window.__evidenceSearchTimer);
    window.__evidenceSearchTimer = setTimeout(() => {
      state.evidenceSelectedId = '';
      replaceRouteHash();
      loadRoutePage();
    }, 250);
  });
  $('evidenceClearFilters')?.addEventListener('click', () => {
    state.q = '';
    state.project = '';
    state.evidenceMode = 'hybrid';
    state.evidenceType = '';
    state.evidenceReviewState = '';
    state.evidenceSourceKind = '';
    state.evidenceAnchorType = '';
    state.evidenceSelectedId = '';
    state.evidenceSelectedIds.clear();
    replaceRouteHash();
    loadRoutePage();
  });
  $('evidenceSelectAll')?.addEventListener('change', () => {
    const checked = $('evidenceSelectAll').checked;
    state.evidenceSelectedIds.clear();
    document.querySelectorAll('.evidence-row').forEach((row) => {
      const id = row.dataset.ledgerId || '';
      const checkbox = row.querySelector('.evidence-check');
      if (checkbox) checkbox.checked = checked;
      if (checked && id) state.evidenceSelectedIds.add(id);
    });
  });
  document.querySelectorAll('.evidence-row').forEach((row) => {
    row.addEventListener('click', () => {
      state.evidenceSelectedId = row.dataset.ledgerId || '';
      replaceRouteHash();
      loadRoutePage();
    });
    row.addEventListener('dblclick', async () => {
      if (row.dataset.sourceId) await selectSource(row.dataset.sourceId);
    });
    row.querySelector('.evidence-check')?.addEventListener('click', (event) => {
      event.stopPropagation();
      const id = row.dataset.ledgerId || '';
      if (!id) return;
      if (event.currentTarget.checked) state.evidenceSelectedIds.add(id);
      else state.evidenceSelectedIds.delete(id);
    });
  });
  document.querySelectorAll('[data-evidence-preview-tab]').forEach((button) => {
    button.addEventListener('click', () => {
      state.evidencePreviewTab = button.dataset.evidencePreviewTab || 'overview';
      document.querySelectorAll('[data-evidence-preview-tab]').forEach((tab) => tab.classList.toggle('active', tab === button));
      document.querySelectorAll('[data-evidence-preview-section]').forEach((section) => {
        section.classList.toggle('active', section.dataset.evidencePreviewSection === state.evidencePreviewTab);
      });
    });
  });
  document.querySelectorAll('[data-evidence-action]').forEach((button) => {
    button.addEventListener('click', async () => {
      const row = (data.rows || []).find((item) => evidenceRowKey(item) === state.evidenceSelectedId) || data.preview?.row;
      try {
        await applyEvidenceAction(row, button.dataset.evidenceAction || 'defer');
      } catch (error) {
        const status = $('evidenceActionStatus');
        if (status) status.textContent = error.message;
      }
    });
  });
  document.querySelectorAll('[data-evidence-bulk-action]').forEach((button) => {
    button.addEventListener('click', async () => {
      try {
        await applyBulkEvidenceAction(button.dataset.evidenceBulkAction || 'defer');
      } catch (error) {
        const status = $('evidenceBulkStatus');
        if (status) status.textContent = error.message;
      }
    });
  });
  bindEvidenceKeyboard();
}

function renderEntitiesPage(data) {
  const curated = data.curated || [];
  const extracted = data.extracted || [];
  $('routePage').innerHTML = `
    ${pageHeader('Entity Directory', 'Candidate and curated entities with source-backed mentions.')}
    ${metricCards([
      { label: 'Curated links', value: curated.length },
      { label: 'Extracted entities', value: extracted.length },
      { label: 'Entity types', value: (data.type_counts || []).length },
    ])}
    <section class="page-two-col">
      <div class="panel page-panel">
        <div class="panel-title-row"><h2>Curated Entity Links</h2><span class="status-badge">human layer</span></div>
        ${curated.map((row) => `
          <article class="review-item">
            <div class="tag-line"><span class="pill">${escapeHtml(row.status)}</span><span class="pill">${escapeHtml(row.entity_type)}</span></div>
            <p><strong>${escapeHtml(row.canonical_name || row.canonical_entity_id || row.mention_text)}</strong></p>
            <p class="muted">${escapeHtml(row.mention_text || '')}</p>
            <button class="secondary object-link" data-id="${escapeHtml(row.source_evidence_id)}">Open source</button>
          </article>
        `).join('') || '<p class="muted padded">No curated entity links yet.</p>'}
      </div>
      <div class="panel page-panel">
        <div class="panel-title-row"><h2>Extracted Mentions</h2><span class="status-badge warn">machine / parser layer</span></div>
        <div class="chip-cloud">${extracted.map((row) => `
          <span class="entity-chip"><strong>${escapeHtml(row.entity)}</strong><em>${escapeHtml(row.sources)} sources · ${escapeHtml(row.mentions)} mentions</em></span>
        `).join('') || '<p class="muted padded">No extracted entity array values yet.</p>'}</div>
      </div>
    </section>
  `;
  document.querySelectorAll('.object-link[data-id]').forEach((button) => button.addEventListener('click', () => selectSource(button.dataset.id)));
}

function renderClaimsPage(data) {
  const claims = data.claims || [];
  $('routePage').innerHTML = `
    ${pageHeader('Claims Ledger', 'Draft and proposed assertions remain contestable until reviewed against evidence.')}
    ${metricCards([
      { label: 'Claim stubs', value: claims.length },
      { label: 'Claim groups', value: (data.type_counts || []).length },
      { label: 'Possible conflicts', value: (data.possible_conflicts || []).length },
    ])}
    <section class="panel page-panel">
      <div class="panel-title-row"><h2>Claims</h2><span class="status-badge warn">not published</span></div>
      ${claims.map((row) => `
        <article class="review-item">
          <div class="tag-line"><span class="pill">${escapeHtml(row.status)}</span><span class="pill">${escapeHtml(row.claim_type)}</span><span class="pill">${escapeHtml(row.evidence_relation)}</span></div>
          <p><strong>${escapeHtml(row.claim_text)}</strong></p>
          ${row.note ? `<p class="muted">${escapeHtml(row.note)}</p>` : ''}
          <button class="secondary object-link" data-id="${escapeHtml(row.source_evidence_id)}">Open evidence source</button>
        </article>
      `).join('') || '<p class="muted padded">No claim stubs yet.</p>'}
    </section>
  `;
  document.querySelectorAll('.object-link[data-id]').forEach((button) => button.addEventListener('click', () => selectSource(button.dataset.id)));
}

function renderReviewsPage(data) {
  const queue = data.queue || [];
  const events = data.events || [];
  $('routePage').innerHTML = `
    ${pageHeader('Reviews', 'Formal decisions, save-and-next queues, and review-event history.')}
    ${metricCards([
      { label: 'Review events', value: data.counts?.review_events || 0 },
      { label: 'Annotations', value: data.counts?.annotations || 0 },
      { label: 'Open queues', value: queue.filter((item) => Number(item.count || 0) > 0).length },
    ])}
    <section class="page-two-col">
      <div class="panel page-panel">
        <div class="panel-title-row"><h2>Review Queues</h2><span class="status-badge info">decision work</span></div>
        ${queue.map((item) => `
          <article class="queue-card">
            <strong>${escapeHtml(item.label)}</strong>
            <span>${escapeHtml(item.count)}</span>
            <p>${escapeHtml(item.reason)}</p>
          </article>
        `).join('')}
      </div>
      <div class="panel page-panel">
        <div class="panel-title-row"><h2>Recent Events</h2><span class="status-badge">append-only</span></div>
        ${events.map((row) => `
          <article class="review-item compact">
            <div class="tag-line"><span class="pill">${escapeHtml(row.event_type)}</span><span class="pill">${escapeHtml(row.subject_type)}</span></div>
            <p>${escapeHtml(row.source_evidence_id)}</p>
            <div class="muted">${escapeHtml(fmtDate(row.created_at))} · ${escapeHtml(row.actor)}</div>
          </article>
        `).join('') || '<p class="muted padded">No review events yet.</p>'}
      </div>
    </section>
  `;
}

function renderPublishingPage(data) {
  const checks = data.checks || [];
  $('routePage').innerHTML = `
    ${pageHeader('Publishing', 'Frozen snapshots and approval gates before public website reuse.')}
    ${metricCards([
      { label: 'Bundles', value: (data.bundles || []).length },
      { label: 'Checks', value: checks.length },
      { label: 'Blocked', value: checks.filter((item) => item.state === 'blocked').length },
    ])}
    <section class="panel page-panel">
      <div class="panel-title-row"><h2>Publication Checks</h2><span class="status-badge warn">snapshot not active yet</span></div>
      ${checks.map((item) => `
        <article class="check-row">
          <span class="status-badge ${item.state === 'pass' ? 'ok' : item.state === 'blocked' ? 'danger' : 'warn'}">${escapeHtml(item.state)}</span>
          <strong>${escapeHtml(item.label)}</strong>
        </article>
      `).join('')}
      <p class="muted padded">${escapeHtml(data.snapshot_policy || '')}</p>
    </section>
  `;
}

function renderTaxonomyPage(data) {
  const core = data.core || {};
  const usage = data.usage || {};
  const group = (title, terms, used = []) => `
    <section class="panel page-panel">
      <div class="panel-title-row"><h2>${escapeHtml(title)}</h2><span class="status-badge">controlled terms</span></div>
      <div class="chip-cloud">${(terms || []).map((term) => {
        const hit = (used || []).find((row) => row.term === term);
        return `<span class="entity-chip"><strong>${escapeHtml(term)}</strong><em>${escapeHtml(hit?.usage ?? 0)} uses</em></span>`;
      }).join('')}</div>
    </section>
  `;
  $('routePage').innerHTML = `
    ${pageHeader('Taxonomy', 'Governed labels for entities, evidence, claim properties, and review reasons.')}
    <section class="page-two-col">
      ${group('Entity types', core.entity_types, usage.entity_types)}
      ${group('Claim properties', core.claim_properties, usage.claim_types)}
      ${group('Evidence types', core.evidence_types, [])}
      ${group('Review reason codes', core.review_reason_codes, [])}
    </section>
  `;
}

function renderRoutePage(route, data) {
  if (route === 'projects') return renderProjectsPage(data);
  if (route === 'library') return renderLibraryPage(data);
  if (route === 'evidence') return renderEvidencePage(data);
  if (route === 'entities') return renderEntitiesPage(data);
  if (route === 'claims') return renderClaimsPage(data);
  if (route === 'reviews') return renderReviewsPage(data);
  if (route === 'publishing') return renderPublishingPage(data);
  if (route === 'taxonomy') return renderTaxonomyPage(data);
}

function routeQuery() {
  const params = new URLSearchParams({ limit: state.limit });
  if (state.q) params.set('q', state.q);
  if (state.kind && state.route !== 'evidence') params.set('kind', state.kind);
  if (state.project) params.set('project', state.project);
  if (state.route === 'library') {
    params.set('mode', state.libraryMode || 'hybrid');
    params.set('scope', state.libraryScope || 'corpus');
    params.set('sort', state.librarySort || 'relevance');
    if (state.kind) params.set('type', state.kind);
    if (state.libraryDateFrom) params.set('date_from', state.libraryDateFrom);
    if (state.libraryDateTo) params.set('date_to', state.libraryDateTo);
    if (state.libraryIncludeArchived) params.set('include_archived', '1');
    if (state.librarySelectedId) params.set('inspect', `source:${state.librarySelectedId}`);
  }
  if (state.route === 'evidence') {
    params.set('mode', state.evidenceMode || 'hybrid');
    if (state.evidenceType) params.set('type', state.evidenceType);
    if (state.evidenceReviewState) params.set('review_state', state.evidenceReviewState);
    if (state.evidenceSourceKind) params.set('source_kind', state.evidenceSourceKind);
    if (state.evidenceAnchorType) params.set('anchor_type', state.evidenceAnchorType);
    if (state.evidenceSelectedId) params.set('inspect', `evidence:${state.evidenceSelectedId}`);
  }
  return params.toString();
}

function updateRouteVisibility() {
  const route = state.route;
  const showHome = route === 'home';
  const showInbox = route === 'home' || route === 'inbox';
  document.querySelector('.brief-hero')?.classList.toggle('hidden', !showHome);
  document.querySelector('.brief-grid')?.classList.toggle('hidden', !showHome);
  document.querySelector('.home-grid')?.classList.toggle('hidden', !showHome);
  $('inbox')?.classList.toggle('hidden', !showInbox);
  $('routePage')?.classList.toggle('hidden', showHome || route === 'inbox');
  document.querySelectorAll('[data-route]').forEach((button) => button.classList.toggle('active', button.dataset.route === route));
}

async function loadRoutePage() {
  updateRouteVisibility();
  if (state.route === 'home') {
    await loadHome();
    return;
  }
  if (state.route === 'inbox') {
    await loadInbox();
    return;
  }
  const config = routeConfig[state.route];
  if (!config) return;
  $('routePage').innerHTML = `${pageHeader(config.title, 'Loading route read model...')}<div class="empty-state panel"><h2>Loading</h2><p>Building the ${escapeHtml(config.title)} view.</p></div>`;
  try {
    const data = await fetchJson(`${config.endpoint}?${routeQuery()}`);
    renderRoutePage(state.route, data);
  } catch (error) {
    $('routePage').innerHTML = `${pageHeader(config.title, 'Could not load this read model.')}<div class="empty-state panel"><h2>${escapeHtml(config.title)} error</h2><p>${escapeHtml(error.message)}</p></div>`;
  }
}

function setRoute(route, push = true) {
  state.route = routeConfig[route] ? route : 'home';
  if (push) replaceRouteHash();
  loadRoutePage();
}

function renderInbox(rows) {
  state.rows = rows;
  const highPriority = rows.filter((row) => row.task_priority === 'high' || row.task_priority === 'blocking').length;
  $('inboxOpenTasks').textContent = `${rows.length} open task${rows.length === 1 ? '' : 's'}`;
  $('inboxHighPriority').textContent = `${highPriority} high priority`;
  $('inboxVisibleCount').textContent = `${rows.length} visible task${rows.length === 1 ? '' : 's'}`;
  $('inboxLiveState').textContent = `updated ${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
  if (!rows.length) {
    $('inboxRows').innerHTML = `<div class="empty-state"><h2>No review tasks</h2><p>Try a different queue or search.</p></div>`;
    renderInboxPreview(null);
    return;
  }
  if (!state.previewTaskKey || !rows.some((row) => taskKeyFor(row) === state.previewTaskKey)) {
    state.previewTaskKey = taskKeyFor(rows[0]);
  }
  $('inboxRows').innerHTML = rows.map((row) => {
    const sourceId = sourceIdFor(row);
    const taskKey = taskKeyFor(row);
    const selected = state.previewTaskKey === taskKey;
    const accent = taskAccentFor(row);
    return `
    <article class="task-card row ${selected ? 'active' : ''}"
      data-id="${escapeHtml(sourceId)}"
      data-task-key="${escapeHtml(taskKey)}"
      data-task-type="${escapeHtml(row.task_type || '')}"
      data-object-type="${escapeHtml(row.object_type || '')}">
      <input class="task-check" type="checkbox" aria-label="Select task">
      <span class="task-kind-icon ${escapeHtml(accent)}">${escapeHtml(taskIconFor(row))}</span>
      <div class="task-main">
        <div class="task-title-line">
          <span class="task-title">${escapeHtml(taskTitleFor(row))}</span>
          ${row.task_priority ? `<span class="pill task-priority ${escapeHtml(row.task_priority)}">${escapeHtml(row.task_priority)}</span>` : ''}
        </div>
        <div class="task-source">${escapeHtml(titleFor(row))}</div>
        <div class="row-snippet">${escapeHtml(row.task_reason || row.snippet || row.canonical_url || row.evidence_id)}</div>
        ${row.object_text ? `<div class="task-object">${escapeHtml(row.object_text)}</div>` : ''}
        <div class="row-meta">
          <span class="pill">${escapeHtml(taskTypeLabel(row))}</span>
          ${row.object_type && row.object_type !== 'source' ? `<span class="pill">${escapeHtml(titleCase(row.object_type))}</span>` : ''}
          ${row.task_state ? `<span class="pill">${escapeHtml(titleCase(row.task_state))}</span>` : ''}
          <span class="pill">${escapeHtml(sourceLabelFor(row))}</span>
          ${row.author_handle ? `<span class="pill">@${escapeHtml(row.author_handle)}</span>` : ''}
          ${row.domain ? `<span class="pill">${escapeHtml(row.domain)}</span>` : ''}
          ${row.has_media ? `<span class="pill ok">media</span>` : ''}
          ${row.has_ocr ? `<span class="pill ok">OCR</span>` : ''}
          ${row.review_hint ? `<span class="pill warn">${escapeHtml(row.review_hint)}</span>` : ''}
        </div>
      </div>
      <div class="task-side">
        <span class="task-state">${escapeHtml(titleCase(row.task_state || 'open'))}</span>
        <span>${escapeHtml(fmtDate(row.task_updated_at || row.last_ingested_at) || 'no timestamp')}</span>
        <em>${row.text_chars || 0} chars · ${row.observations || 0} obs</em>
      </div>
    </article>
  `;
  }).join('');
  document.querySelectorAll('.row[data-id]').forEach((row) => {
    row.addEventListener('click', () => {
      state.previewTaskKey = row.dataset.taskKey || '';
      renderInbox(state.rows);
    });
    row.addEventListener('dblclick', async () => {
      await openPreviewSource(row.dataset.id, row.dataset.taskType);
    });
    row.querySelector('.task-check')?.addEventListener('click', (event) => {
      event.stopPropagation();
    });
  });
  renderInboxPreview(selectedPreviewRow());
}

function renderInboxPreview(row) {
  if (!row) {
    $('inboxPreview').className = 'task-preview empty-preview';
    $('inboxPreview').innerHTML = `
      <div class="empty-state">
        <h2>Task Preview</h2>
        <p>Select a task to inspect the original source, normalized candidate, artifacts, provenance, and review action path.</p>
      </div>
    `;
    return;
  }
  const sourceId = sourceIdFor(row);
  const sourceTitle = titleFor(row);
  const originalText = row.snippet || row.canonical_url || row.evidence_id || '';
  const candidateText = row.object_text || row.task_reason || row.snippet || '';
  const activeTab = ['preview', 'proposed', 'metadata', 'activity'].includes(state.inboxPreviewTab) ? state.inboxPreviewTab : 'preview';
  const previewTab = (id, label) => `<button class="${activeTab === id ? 'active' : ''}" type="button" data-preview-tab="${id}">${label}</button>`;
  const previewSectionClass = (id) => `preview-card preview-section ${activeTab === id ? 'active' : ''}`;
  $('inboxPreview').className = 'task-preview';
  $('inboxPreview').innerHTML = `
    <div class="preview-topline">
      <span class="task-kind-icon ${escapeHtml(taskAccentFor(row))}">${escapeHtml(taskIconFor(row))}</span>
      <div>
        <h2>${escapeHtml(taskTypeLabel(row))}</h2>
        <h3>${escapeHtml(taskTitleFor(row))}</h3>
      </div>
      ${row.task_priority ? `<span class="pill task-priority ${escapeHtml(row.task_priority)}">${escapeHtml(row.task_priority)}</span>` : ''}
    </div>

    <div class="preview-meta-grid">
      <div><span>Project</span><strong>${escapeHtml(row.source_project || 'Inbox')}</strong></div>
      <div><span>Owner</span><strong>You</strong></div>
      <div><span>Captured</span><strong>${escapeHtml(fmtDate(row.captured_at || row.last_ingested_at) || 'Unknown')}</strong></div>
    </div>

    <section class="preview-card reason-card">
      <h4>Why this is here</h4>
      <p>${escapeHtml(row.task_reason || row.review_hint || 'This source or derived object needs human inspection before promotion.')}</p>
    </section>

    <nav class="preview-tabs" aria-label="Task preview sections">
      ${previewTab('preview', 'Preview')}
      ${previewTab('proposed', 'Proposed change')}
      ${previewTab('metadata', 'Metadata')}
      ${previewTab('activity', 'Activity')}
    </nav>

    <section class="${previewSectionClass('preview')} source-card" data-preview-section="preview">
      <div class="source-card-head">
        <span class="source-glyph">${escapeHtml(sourceGlyph(row.source_kind))}</span>
        <div>
          <h4>${escapeHtml(sourceTitle)}</h4>
          <p>${escapeHtml([sourceLabelFor(row), row.author_handle ? '@' + row.author_handle : row.domain, fmtDate(row.posted_at || row.captured_at)].filter(Boolean).join(' · '))}</p>
        </div>
      </div>
      ${row.canonical_url ? `<a href="${escapeHtml(row.canonical_url)}" target="_blank" rel="noreferrer">${escapeHtml(row.canonical_url)}</a>` : ''}
      <p>${escapeHtml(originalText || 'No source preview text available yet.')}</p>
    </section>

    <section class="${previewSectionClass('proposed')} normalized-card" data-preview-section="proposed">
      <h4>Proposed normalized work item</h4>
      <p>${escapeHtml(candidateText || 'No derived candidate text is available for this task yet.')}</p>
      <div class="tag-line">
        ${row.object_type ? `<span class="pill">${escapeHtml(titleCase(row.object_type))}</span>` : ''}
        ${row.object_id ? `<span class="pill">${escapeHtml(row.object_id)}</span>` : ''}
        ${row.has_media ? `<span class="pill ok">media attached</span>` : ''}
        ${row.has_ocr ? `<span class="pill ok">OCR available</span>` : ''}
      </div>
    </section>

    <section class="${previewSectionClass('metadata')}" data-preview-section="metadata">
      <h4>Metadata and artifacts</h4>
      <div class="source-trail">
        <span><strong>Source</strong>${escapeHtml(sourceId || 'unknown')}</span>
        <span><strong>Task</strong>${escapeHtml(row.task_id || taskKeyFor(row))}</span>
        <span><strong>State</strong>${escapeHtml(titleCase(row.task_state || 'open'))}</span>
        <span><strong>Updated</strong>${escapeHtml(fmtDate(row.task_updated_at || row.last_ingested_at) || 'unknown')}</span>
      </div>
      <div class="tag-line preview-artifact-flags">
        ${row.has_media ? '<span class="pill ok">media attached</span>' : '<span class="pill">no media flag</span>'}
        ${row.has_ocr ? '<span class="pill ok">OCR available</span>' : '<span class="pill">no OCR flag</span>'}
        <span class="pill">${escapeHtml(row.text_chars || 0)} text chars</span>
        <span class="pill">${escapeHtml(row.observations || 0)} observations</span>
      </div>
    </section>

    <section class="${previewSectionClass('activity')}" data-preview-section="activity">
      <h4>Activity</h4>
      <div class="source-trail">
        <span><strong>Review type</strong>${escapeHtml(taskTypeLabel(row))}</span>
        <span><strong>Priority</strong>${escapeHtml(row.task_priority || 'normal')}</span>
        <span><strong>Owner</strong>web-osint-user</span>
        <span><strong>Next action</strong>Accept, edit, reject, defer, assign, or archive.</span>
      </div>
    </section>

    <label class="preview-note">Decision note
      <input id="previewDecisionNote" placeholder="Optional reason, correction note, or handoff context">
    </label>
    <div id="previewActionStatus" class="review-status muted"></div>
    <div class="preview-actions">
      <button class="secondary" data-preview-action="assign">Assign</button>
      <button class="secondary" data-preview-action="defer">Defer</button>
      <button class="secondary" data-preview-action="reject">Reject</button>
      <button class="secondary danger-button" data-preview-action="archive">Archive</button>
      <button class="secondary" data-preview-action="edit">Edit proposal</button>
      <button data-preview-action="open">Open workbench</button>
      <button data-preview-action="accept">Accept & next</button>
    </div>
  `;
  document.querySelectorAll('[data-preview-action]').forEach((button) => {
    button.addEventListener('click', async () => {
      const action = button.dataset.previewAction;
      const status = $('previewActionStatus');
      if (action === 'open') {
        status.textContent = 'Opening source workbench...';
        await openPreviewSource(sourceId, row.task_type);
        status.textContent = '';
        return;
      }
      if (action === 'edit') {
        status.textContent = 'Opening source workbench for editing...';
        await openPreviewSource(sourceId, row.task_type);
        status.textContent = '';
        return;
      }
      try {
        await applyPreviewDecision(row, action);
      } catch (error) {
        status.textContent = error.message;
      }
    });
  });
  document.querySelectorAll('[data-preview-tab]').forEach((button) => {
    button.addEventListener('click', () => {
      state.inboxPreviewTab = button.dataset.previewTab || 'preview';
      document.querySelectorAll('[data-preview-tab]').forEach((tab) => tab.classList.toggle('active', tab === button));
      document.querySelectorAll('[data-preview-section]').forEach((section) => {
        section.classList.toggle('active', section.dataset.previewSection === state.inboxPreviewTab);
      });
    });
  });
}

function previewDecisionForAction(action) {
  if (action === 'accept') return 'accepted';
  if (action === 'reject') return 'rejected';
  if (action === 'defer') return 'deferred';
  if (action === 'archive') return 'archived';
  return action || 'updated';
}

function reviewStatusForPreviewAction(row, action) {
  const objectType = row.object_type || '';
  if (action === 'accept') return acceptStatusByObject[objectType] || 'accepted';
  if (action === 'reject') return rejectStatusByObject[objectType] || 'rejected';
  if (action === 'defer') return deferStatusByObject[objectType] || 'open';
  if (action === 'archive') return 'superseded';
  return '';
}

function isReviewObjectTask(row) {
  return Boolean(row.object_type && row.object_id && reviewStatusOptions[row.object_type]);
}

function sourceAnchorForTask(row) {
  return {
    kind: 'review_task',
    source_evidence_id: sourceIdFor(row),
    task_id: row.task_id || taskKeyFor(row),
    task_type: row.task_type || '',
    object_type: row.object_type || '',
    object_id: row.object_id || '',
  };
}

async function applyPreviewDecision(row, action) {
  const status = $('previewActionStatus');
  const note = $('previewDecisionNote')?.value || '';
  const decision = previewDecisionForAction(action);
  status.textContent = `${titleCase(decision)}...`;
  await persistInboxDecision(row, action, note);
  status.textContent = `${titleCase(decision)} decision saved. Refreshing queue...`;
  const currentIndex = state.rows.findIndex((item) => taskKeyFor(item) === taskKeyFor(row));
  const next = state.rows[currentIndex + 1] || state.rows[currentIndex - 1] || null;
  state.previewTaskKey = next ? taskKeyFor(next) : '';
  await loadFacets();
  await loadInbox();
}

async function persistInboxDecision(row, action, note = '') {
  const sourceId = sourceIdFor(row);
  const decision = previewDecisionForAction(action);
  if (action === 'assign') {
    await postJson('/api/review/events', {
      event_type: 'review_task.assignment.recorded',
      source_evidence_id: sourceId,
      source_project: row.source_project || '',
      project: row.source_project || '',
      subject_type: 'review_task',
      subject_id: row.task_id || taskKeyFor(row),
      task_type: row.task_type || '',
      object_type: row.object_type || 'source',
      object_id: row.object_id || sourceId,
      decision: 'assigned',
      status: 'assigned',
      assignee: 'web-osint-user',
      note,
      source_anchor: sourceAnchorForTask(row),
      idempotency_key: `${row.task_id || taskKeyFor(row)}:assigned:${Date.now()}`,
    });
    return;
  }
  if (isReviewObjectTask(row)) {
    await postJson('/api/review-state', {
      source_evidence_id: sourceId,
      source_project: row.source_project || '',
      project: row.source_project || '',
      subject_type: row.object_type,
      subject_id: row.object_id,
      status: reviewStatusForPreviewAction(row, action),
      note,
      source_anchor: sourceAnchorForTask(row),
      idempotency_key: `${row.task_id || taskKeyFor(row)}:${decision}:${Date.now()}`,
    });
    return;
  }
  await postJson('/api/review/events', {
    event_type: 'review_task.decision.recorded',
    source_evidence_id: sourceId,
    source_project: row.source_project || '',
    project: row.source_project || '',
    subject_type: 'review_task',
    subject_id: row.task_id || taskKeyFor(row),
    task_type: row.task_type || '',
    object_type: row.object_type || 'source',
    object_id: row.object_id || sourceId,
    decision,
    status: decision,
    note,
    source_anchor: sourceAnchorForTask(row),
    idempotency_key: `${row.task_id || taskKeyFor(row)}:${decision}:${Date.now()}`,
  });
}

async function applyBulkInboxAction(action) {
  const selectedKeys = Array.from(document.querySelectorAll('#inboxRows .task-check:checked'))
    .map((checkbox) => checkbox.closest('.task-card')?.dataset.taskKey)
    .filter(Boolean);
  const selectedRows = state.rows.filter((row) => selectedKeys.includes(taskKeyFor(row)));
  const preview = $('previewActionStatus');
  if (!selectedRows.length) {
    if (preview) preview.textContent = 'Select at least one task.';
    return;
  }
  const note = `Bulk ${previewDecisionForAction(action)} from Inbox`;
  if (preview) preview.textContent = `${titleCase(action)} ${selectedRows.length} task${selectedRows.length === 1 ? '' : 's'}...`;
  for (const row of selectedRows) {
    await persistInboxDecision(row, action, note);
  }
  if (preview) preview.textContent = `${titleCase(previewDecisionForAction(action))} saved for ${selectedRows.length} task${selectedRows.length === 1 ? '' : 's'}.`;
  state.previewTaskKey = '';
  await loadFacets();
  await loadInbox();
}

async function openPreviewSource(sourceId, taskType) {
  if (!sourceId) return;
  await selectSource(sourceId);
  if (taskType && taskType !== 'source_triage') activateTab('review');
}

function syncInboxSearchInputs(value) {
  if ($('searchInput')) $('searchInput').value = value;
  if ($('inboxLocalSearch')) $('inboxLocalSearch').value = value;
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
  $('inboxLiveState').textContent = 'refreshing...';
  try {
    const data = await fetchJson(`/api/inbox?${params.toString()}`);
    renderInbox(data.rows || []);
  } catch (error) {
    $('inboxRows').innerHTML = `<div class="empty-state"><h2>Inbox error</h2><p>${escapeHtml(error.message)}</p></div>`;
    $('inboxLiveState').textContent = 'error';
    renderInboxPreview(null);
  }
}

function renderKv(items) {
  return `<dl class="kv">${items.map(([key, value]) => `
    <dt>${escapeHtml(key)}</dt><dd>${value || value === 0 ? escapeHtml(value) : ''}</dd>
  `).join('')}</dl>`;
}

function renderNormalized(source) {
  const latest = source.latest || {};
  const review = source.review || {};
  const corrections = review.normalized_corrections || [];
  const links = (latest.links || []).map((link) => `<a href="${escapeHtml(link)}" target="_blank" rel="noreferrer">${escapeHtml(link)}</a>`).join('<br>');
  const raw = latest.raw || {};
  $('tab-normalized').innerHTML = `
    <div class="source-summary-grid">
      <section class="card">
        <h3>Source identity</h3>
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
      </section>
      <section class="card">
        <h3>Capture state</h3>
        ${renderKv([
          ['Source kind', latest.source_kind],
          ['Has media', latest.has_media ? 'yes' : 'no'],
          ['Has OCR', latest.has_ocr ? 'yes' : 'no'],
          ['Raw fields', Object.keys(raw).length],
          ['Artifacts', (latest.artifact_paths || []).length],
        ])}
      </section>
    </div>
    <div class="side-by-side">
      <section class="source-pane">
        <div class="pane-title"><h3>Original / capture metadata</h3><span class="status-badge">immutable layer</span></div>
        <div class="source-text compact">${escapeHtml(JSON.stringify({
          url: latest.canonical_url,
          source_kind: latest.source_kind,
          author_handle: latest.author_handle,
          posted_at: latest.posted_at,
          captured_at: latest.captured_at,
          collector_run_id: latest.collector_run_id,
          artifact_paths: (latest.artifact_paths || []).map((item) => item.path),
        }, null, 2))}</div>
      </section>
      <section class="source-pane">
        <div class="pane-title"><h3>Normalized text</h3><span class="status-badge warn">derived layer</span></div>
        <div class="source-text">${escapeHtml(latest.text || '(no extracted text)')}</div>
      </section>
    </div>
    ${corrections.length ? `
      <section class="card correction-overlay">
        <div class="pane-title"><h3>Correction overlay</h3><span class="status-badge warn">reviewed separately</span></div>
        <div class="cards">${corrections.map((row) => `
          <article class="review-item compact">
            <div class="tag-line">
              <span class="pill">${escapeHtml(row.status)}</span>
              <span class="pill">${escapeHtml(row.correction_kind)}</span>
              ${row.block_id ? `<span class="pill">${escapeHtml(row.block_id)}</span>` : ''}
            </div>
            <div class="diff-pair">
              <div><strong>Original</strong><p>${escapeHtml(row.original_text)}</p></div>
              <div><strong>Corrected</strong><p>${escapeHtml(row.corrected_text)}</p></div>
            </div>
            ${row.note ? `<p class="muted">${escapeHtml(row.note)}</p>` : ''}
            <div class="muted">${fmtDate(row.updated_at)} · ${escapeHtml(row.actor)}</div>
          </article>
        `).join('')}</div>
      </section>
    ` : ''}
  `;
}

function renderProvenance(source) {
  const latest = source.latest || {};
  const raw = latest.raw || {};
  const review = source.review || {};
  const artifacts = latest.artifact_paths || [];
  const steps = [
    { label: 'Captured source', value: latest.canonical_url || latest.evidence_id, meta: fmtDate(latest.captured_at) },
    { label: 'Collector run', value: latest.collector_run_id || '(unknown)', meta: latest.capture_method || '' },
    { label: 'Normalized evidence row', value: latest.evidence_id || '', meta: fmtDate(latest.ingested_at) },
    { label: 'Artifacts', value: `${artifacts.length} local artifact(s)`, meta: artifacts.map((item) => item.path).slice(0, 3).join(' · ') },
    { label: 'Machine observations', value: `${(source.annotations || []).length} semantic · ${(source.ocr || []).length} OCR · ${(source.vl || []).length} VL`, meta: 'review before promotion' },
    { label: 'Human review events', value: `${review.counts?.events || 0} event(s)`, meta: 'append-only JSONL + ClickHouse projection' },
  ];
  $('tab-provenance').innerHTML = `
    <div class="provenance-stack">
      ${steps.map((step, index) => `
        <article class="provenance-step">
          <span>${String(index + 1).padStart(2, '0')}</span>
          <div>
            <h3>${escapeHtml(step.label)}</h3>
            <p>${escapeHtml(step.value)}</p>
            ${step.meta ? `<em>${escapeHtml(step.meta)}</em>` : ''}
          </div>
        </article>
      `).join('')}
    </div>
    <section class="card">
      <h3>Raw capture hints</h3>
      <pre>${escapeHtml(JSON.stringify({
        raw_keys: Object.keys(raw),
        content_representations: raw.content_representations || {},
        omitted_content: raw.omitted_content || raw.omissions || [],
      }, null, 2))}</pre>
    </section>
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

function evidenceDocumentPath(source) {
  const latest = source.latest || {};
  const raw = latest.raw || {};
  const reps = raw.content_representations || {};
  return latest.evidence_document_path
    || raw.evidence_document_path
    || reps.canonical_evidence_document
    || reps.evidence_document
    || (latest.artifact_paths || []).map((item) => item.path).find((path) => /\/evidence_document\//.test(path))
    || '';
}

function artifactUrl(path) {
  return `/api/artifact?path=${encodeURIComponent(path)}`;
}

function blockStableId(block, index) {
  return block.block_id || block.id || block.anchor?.block_id || block.anchor?.dom_id || `block-${index + 1}`;
}

function textForBlock(block) {
  if (block.text) return String(block.text);
  if (Array.isArray(block.rows)) return block.rows.map((row) => (row || []).join(' | ')).join('\n');
  return '';
}

function sourceAnchorForBlock(doc, docPath, block, index) {
  const blockId = blockStableId(block, index);
  return {
    document_id: doc.document_id || '',
    block_id: blockId,
    block_index: index,
    block_type: block.type || '',
    artifact_path: docPath,
    selector: block.anchor || {},
    quote: textForBlock(block),
  };
}

function renderEvidenceDocumentPlaceholder(source) {
  const docPath = evidenceDocumentPath(source);
  if (!docPath) {
    $('tab-evidence-document').innerHTML = `<div class="empty-state"><h2>No EvidenceDocument</h2><p>This source does not expose a canonical EvidenceDocument artifact yet.</p></div>`;
    return;
  }
  $('tab-evidence-document').innerHTML = `<div class="empty-state"><h2>Loading EvidenceDocument</h2><p>${escapeHtml(docPath)}</p></div>`;
  fetch(artifactUrl(docPath), { cache: 'no-store' })
    .then((response) => response.text().then((text) => ({ response, text })))
    .then(({ response, text }) => {
      if (!response.ok) throw new Error(text || response.statusText);
      renderEvidenceDocument(JSON.parse(text), docPath);
    })
    .catch((error) => {
      $('tab-evidence-document').innerHTML = `
        <div class="empty-state">
          <h2>EvidenceDocument error</h2>
          <p>${escapeHtml(error.message)}</p>
          <p><a href="${escapeHtml(artifactUrl(docPath))}" target="_blank" rel="noreferrer">${escapeHtml(docPath)}</a></p>
        </div>
      `;
    });
}

function renderEvidenceDocument(doc, docPath) {
  state.currentDoc = { doc, docPath };
  const blocks = doc.blocks || [];
  const assets = doc.assets || [];
  const quality = doc.revision?.quality || {};
  $('tab-evidence-document').innerHTML = `
    <div class="cards">
      <div class="card">
        <h3>${escapeHtml(doc.source?.title || doc.document_id || 'EvidenceDocument')}</h3>
        ${renderKv([
          ['Document ID', doc.document_id],
          ['Revision', doc.revision?.revision_id || ''],
          ['Producer', [doc.revision?.producer?.name, doc.revision?.producer?.version].filter(Boolean).join(' ')],
          ['Canonical URL', doc.source?.canonical_url || ''],
          ['Captured', doc.captures?.[0]?.captured_at || doc.created_at || ''],
          ['Blocks', blocks.length],
          ['Assets', assets.length],
          ['Quality', Object.entries(quality).map(([k, v]) => `${k}: ${v}`).join(' · ')],
        ])}
        <p><a href="${escapeHtml(artifactUrl(docPath))}" target="_blank" rel="noreferrer">Open EvidenceDocument JSON</a></p>
      </div>
      <div class="card">
        <h3>Blocks</h3>
        <p class="muted">Select a block to create a durable evidence selection, annotation, or proposed fact.</p>
        <div class="doc-blocks">${blocks.slice(0, 180).map((block, index) => {
          const blockId = blockStableId(block, index);
          const isSelected = state.selectedBlock?.block_id === blockId;
          return `
          <div class="doc-block selectable ${isSelected ? 'selected' : ''}" data-block-index="${index}">
            <div class="tag-line">
              <span class="pill">${escapeHtml(block.type || 'block')}</span>
              <span class="pill">${escapeHtml(blockId)}</span>
              ${block.level ? `<span class="pill">${escapeHtml(block.level)}</span>` : ''}
              ${block.anchor?.dom_path ? `<span class="pill">${escapeHtml(block.anchor.dom_path)}</span>` : ''}
            </div>
            ${block.rows ? renderMiniTable(block.rows) : `<p>${escapeHtml(block.text || '')}</p>`}
            <div class="doc-block-actions">
              <button class="secondary" data-block-action="select" data-block-index="${index}">${isSelected ? 'Selected' : 'Select evidence'}</button>
            </div>
          </div>
        `;
        }).join('')}</div>
      </div>
      <div class="card">
        <h3>Assets</h3>
        ${assets.length ? assets.slice(0, 80).map((asset) => `
          <div class="doc-asset">
            <div class="tag-line">
              <span class="pill">${escapeHtml(asset.type || 'asset')}</span>
              ${asset.width || asset.height ? `<span class="pill">${asset.width || 0}x${asset.height || 0}</span>` : ''}
            </div>
            ${asset.path ? `<p><a href="${escapeHtml(artifactUrl(asset.path))}" target="_blank" rel="noreferrer">${escapeHtml(asset.path)}</a></p>` : ''}
            ${asset.url ? `<p><a href="${escapeHtml(asset.url)}" target="_blank" rel="noreferrer">${escapeHtml(asset.alt || asset.url)}</a></p>` : ''}
            ${asset.path && /\.(png|jpg|jpeg|gif|webp)$/i.test(asset.path) ? `<img class="artifact-img" src="${escapeHtml(artifactUrl(asset.path))}" alt="">` : ''}
          </div>
        `).join('') : '<p class="muted">No assets recorded.</p>'}
      </div>
    </div>
  `;
  document.querySelectorAll('[data-block-action="select"]').forEach((button) => {
    button.addEventListener('click', () => {
      const index = Number(button.dataset.blockIndex || 0);
      selectEvidenceBlock(doc, docPath, blocks[index], index);
    });
  });
}

function renderMiniTable(rows) {
  return `
    <div class="mini-table-wrap">
      <table class="mini-table">
        <tbody>${(rows || []).slice(0, 60).map((row) => `<tr>${(row || []).slice(0, 20).map((cell) => `<td>${escapeHtml(cell)}</td>`).join('')}</tr>`).join('')}</tbody>
      </table>
    </div>
  `;
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

function selectEvidenceBlock(doc, docPath, block, index) {
  const anchor = sourceAnchorForBlock(doc, docPath, block, index);
  state.selectedBlock = {
    source_evidence_id: state.currentSource?.latest?.evidence_id || state.selectedId,
    document_id: anchor.document_id,
    block_id: anchor.block_id,
    block_type: anchor.block_type,
    quote: anchor.quote,
    source_anchor: anchor,
  };
  document.querySelectorAll('.doc-block[data-block-index]').forEach((item) => {
    item.classList.toggle('selected', Number(item.dataset.blockIndex) === index);
  });
  renderReview(state.currentSource);
  activateTab('review');
}

function parseJsonField(value) {
  if (!value) return {};
  try {
    return JSON.parse(value);
  } catch {
    return {};
  }
}

const reviewStatusOptions = {
  evidence_selection: ['selected', 'accepted', 'rejected', 'needs_more_evidence', 'superseded'],
  annotation: ['open', 'accepted', 'resolved', 'rejected', 'superseded'],
  proposed_fact: ['proposed', 'accepted', 'rejected', 'needs_more_evidence', 'superseded'],
  normalized_correction: ['proposed', 'accepted', 'rejected', 'needs_more_evidence', 'superseded'],
  entity_link: ['proposed', 'matched', 'created', 'rejected', 'merged', 'superseded'],
  claim_stub: ['draft', 'under_review', 'accepted', 'disputed', 'rejected', 'superseded'],
};

const acceptStatusByObject = {
  evidence_selection: 'accepted',
  annotation: 'resolved',
  proposed_fact: 'accepted',
  normalized_correction: 'accepted',
  entity_link: 'matched',
  claim_stub: 'accepted',
};

const rejectStatusByObject = {
  evidence_selection: 'rejected',
  annotation: 'rejected',
  proposed_fact: 'rejected',
  normalized_correction: 'rejected',
  entity_link: 'rejected',
  claim_stub: 'rejected',
};

const deferStatusByObject = {
  evidence_selection: 'needs_more_evidence',
  annotation: 'open',
  proposed_fact: 'needs_more_evidence',
  normalized_correction: 'needs_more_evidence',
  entity_link: 'proposed',
  claim_stub: 'under_review',
};

function reviewStateControls(subjectType, subjectId, currentStatus) {
  const options = reviewStatusOptions[subjectType] || ['open', 'accepted', 'rejected', 'superseded'];
  return `
    <div class="review-state-controls">
      <label>Status
        <select data-review-status="${escapeHtml(subjectType)}:${escapeHtml(subjectId)}">
          ${options.map((option) => `<option value="${escapeHtml(option)}" ${option === currentStatus ? 'selected' : ''}>${escapeHtml(option)}</option>`).join('')}
        </select>
      </label>
      <label>Decision note
        <input data-review-note="${escapeHtml(subjectType)}:${escapeHtml(subjectId)}" placeholder="Optional reason or correction note">
      </label>
      <button class="secondary" data-review-update="${escapeHtml(subjectType)}:${escapeHtml(subjectId)}">Update state</button>
    </div>
  `;
}

function selectionForSelectedBlock(review) {
  if (!state.selectedBlock) return null;
  return (review?.selections || []).find((row) => (
    row.document_id === state.selectedBlock.document_id && row.block_id === state.selectedBlock.block_id
  )) || null;
}

function selectedReviewBase(source) {
  const latest = source?.latest || {};
  const selected = state.selectedBlock || {};
  return {
    source_evidence_id: latest.evidence_id || state.selectedId,
    source_project: latest.source_project || '',
    project: latest.source_project || '',
    document_id: selected.document_id || '',
    block_id: selected.block_id || '',
    quote: selected.quote || '',
    source_anchor: selected.source_anchor || {},
  };
}

function renderReviewList(title, rows, renderer) {
  return `
    <section class="review-list">
      <h3>${escapeHtml(title)} (${rows.length})</h3>
      ${rows.length ? rows.map(renderer).join('') : '<p class="muted">None yet.</p>'}
    </section>
  `;
}

function renderReview(source) {
  if (!source) return;
  const review = source.review || {};
  const selected = state.selectedBlock;
  const attachedSelection = selectionForSelectedBlock(review);
  $('tab-review').innerHTML = `
    <div class="review-grid">
      <section class="card review-form">
        <h3>Selected Evidence</h3>
        ${selected ? `
          <div class="tag-line">
            <span class="pill">${escapeHtml(selected.block_type || 'block')}</span>
            <span class="pill">${escapeHtml(selected.document_id || '')}</span>
            <span class="pill">${escapeHtml(selected.block_id || '')}</span>
            ${attachedSelection ? `<span class="pill ok">saved selection</span>` : '<span class="pill warn">not saved yet</span>'}
          </div>
          <blockquote>${escapeHtml(selected.quote || '(empty block)')}</blockquote>
          <label>Selection note
            <textarea id="selectionNote" placeholder="Why this block matters, what it supports, or what needs review"></textarea>
          </label>
          <div class="form-actions">
            <button id="saveSelection">Save evidence selection</button>
          </div>
        ` : `
          <p class="muted">Select a block in the EvidenceDocument tab to anchor a selection, annotation, or proposed fact.</p>
        `}
      </section>

      <section class="card review-form">
        <h3>Annotation</h3>
        <label>Type
          <select id="annotationType">
            <option value="note">Note</option>
            <option value="correction">Correction</option>
            <option value="question">Question</option>
            <option value="claim_context">Claim context</option>
            <option value="publication_note">Publication note</option>
          </select>
        </label>
        <label>Body
          <textarea id="annotationBody" placeholder="Reviewer note, correction, question, or publication thought"></textarea>
        </label>
        <div class="form-actions">
          <button id="saveAnnotation">Save annotation</button>
        </div>
      </section>

      <section class="card review-form">
        <h3>Normalized Correction</h3>
        ${selected ? `
          <label>Correction kind
            <select id="correctionKind">
              <option value="normalized_text">Normalized text</option>
              <option value="ocr_text">OCR text</option>
              <option value="transcript">Transcript</option>
              <option value="table_cell">Table cell</option>
              <option value="layout">Layout / reading order</option>
              <option value="metadata">Metadata</option>
            </select>
          </label>
          <label>Original text
            <textarea id="correctionOriginal">${escapeHtml(selected.quote || '')}</textarea>
          </label>
          <label>Corrected text
            <textarea id="correctionCorrected">${escapeHtml(selected.quote || '')}</textarea>
          </label>
          <label>Correction note
            <textarea id="correctionNote" placeholder="What changed and why this correction is safer"></textarea>
          </label>
          <div class="form-actions">
            <button id="saveCorrection">Save correction overlay</button>
          </div>
        ` : `
          <p class="muted">Select a block in the EvidenceDocument tab to create a versioned normalized/OCR/transcript correction.</p>
        `}
      </section>

      <section class="card review-form">
        <h3>Proposed Fact</h3>
        <label>Fact type
          <select id="factType">
            <option value="model_release">Model release</option>
            <option value="benchmark_result">Benchmark result</option>
            <option value="product_feature">Product feature</option>
            <option value="hardware_claim">Hardware claim</option>
            <option value="repo_metadata">Repo metadata</option>
            <option value="source_metadata">Source metadata</option>
            <option value="general">General</option>
          </select>
        </label>
        <label>Field path
          <input id="factFieldPath" placeholder="example: model.name, benchmark.score, release.date">
        </label>
        <label>Raw value
          <textarea id="factRawValue" placeholder="Value exactly as seen in the source">${escapeHtml(selected?.quote || '')}</textarea>
        </label>
        <label>Normalized value
          <input id="factNormalizedValue" placeholder="Cleaned value, optional">
        </label>
        <label>Unit
          <input id="factUnit" placeholder="%, WER, tokens/s, ms, etc.">
        </label>
        <label>Note
          <textarea id="factNote" placeholder="Scope, qualifier, benchmark setting, uncertainty, or review concern"></textarea>
        </label>
        <div class="form-actions">
          <button id="saveFact">Save proposed fact</button>
        </div>
      </section>

      <section class="card review-form">
        <h3>Entity Link</h3>
        <label>Entity type
          <select id="entityType">
            <option value="lab">Lab / company</option>
            <option value="person">Person</option>
            <option value="model">Model</option>
            <option value="benchmark">Benchmark</option>
            <option value="dataset">Dataset</option>
            <option value="repo">Repository</option>
            <option value="paper">Paper</option>
            <option value="hardware">Hardware</option>
            <option value="tool">Tool</option>
            <option value="topic">Topic</option>
          </select>
        </label>
        <label>Mention text
          <textarea id="entityMentionText" placeholder="Text span or object being linked">${escapeHtml(selected?.quote || '')}</textarea>
        </label>
        <label>Canonical name
          <input id="entityCanonicalName" placeholder="Preferred entity name, if known">
        </label>
        <label>Canonical ID
          <input id="entityCanonicalId" placeholder="Optional existing entity id">
        </label>
        <label>Note
          <textarea id="entityNote" placeholder="Alias, ambiguity, merge thought, or why this entity matters"></textarea>
        </label>
        <div class="form-actions">
          <button id="saveEntityLink">Save entity link</button>
        </div>
      </section>

      <section class="card review-form">
        <h3>Claim Stub</h3>
        <label>Claim type
          <select id="claimType">
            <option value="model_capability">Model capability</option>
            <option value="benchmark_result">Benchmark result</option>
            <option value="release_claim">Release claim</option>
            <option value="architecture_claim">Architecture claim</option>
            <option value="hardware_claim">Hardware claim</option>
            <option value="product_feature">Product feature</option>
            <option value="general">General</option>
          </select>
        </label>
        <label>Evidence relation
          <select id="claimEvidenceRelation">
            <option value="supports">Supports</option>
            <option value="refutes">Refutes</option>
            <option value="mentions">Mentions</option>
            <option value="context">Context</option>
            <option value="uncertain">Uncertain</option>
          </select>
        </label>
        <label>Claim text
          <textarea id="claimText" placeholder="Atomic claim that this source supports, refutes, or mentions">${escapeHtml(selected?.quote || '')}</textarea>
        </label>
        <label>Qualifier JSON
          <textarea id="claimQualifier" placeholder='{"scope":"", "benchmark":"", "date":""}'></textarea>
        </label>
        <label>Note
          <textarea id="claimNote" placeholder="Uncertainty, missing context, contradiction, or review concern"></textarea>
        </label>
        <div class="form-actions">
          <button id="saveClaimRecord">Save claim stub</button>
        </div>
      </section>
    </div>

    <div id="reviewStatus" class="review-status muted"></div>
    <div class="review-history">
      ${renderReviewList('Evidence selections', review.selections || [], (row) => `
        <article class="review-item">
          <div class="tag-line">
            <span class="pill">${escapeHtml(row.status)}</span>
            <span class="pill">${escapeHtml(row.selection_kind)}</span>
            <span class="pill">${escapeHtml(row.block_id)}</span>
          </div>
          <p>${escapeHtml(row.quote)}</p>
          ${row.note ? `<p class="muted">${escapeHtml(row.note)}</p>` : ''}
          <div class="muted">${fmtDate(row.updated_at)} · ${escapeHtml(row.actor)}</div>
          ${reviewStateControls('evidence_selection', row.selection_id, row.status)}
        </article>
      `)}
      ${renderReviewList('Annotations', review.annotations || [], (row) => `
        <article class="review-item">
          <div class="tag-line">
            <span class="pill">${escapeHtml(row.status)}</span>
            <span class="pill">${escapeHtml(row.annotation_type)}</span>
            ${row.evidence_selection_id ? `<span class="pill">${escapeHtml(row.evidence_selection_id)}</span>` : ''}
          </div>
          <p>${escapeHtml(row.body)}</p>
          <div class="muted">${fmtDate(row.updated_at)} · ${escapeHtml(row.actor)}</div>
          ${reviewStateControls('annotation', row.annotation_id, row.status)}
        </article>
      `)}
      ${renderReviewList('Normalized corrections', review.normalized_corrections || [], (row) => `
        <article class="review-item">
          <div class="tag-line">
            <span class="pill">${escapeHtml(row.status)}</span>
            <span class="pill">${escapeHtml(row.correction_kind)}</span>
            ${row.block_id ? `<span class="pill">${escapeHtml(row.block_id)}</span>` : ''}
          </div>
          <div class="diff-pair">
            <div><strong>Original</strong><p>${escapeHtml(row.original_text)}</p></div>
            <div><strong>Corrected</strong><p>${escapeHtml(row.corrected_text)}</p></div>
          </div>
          ${row.note ? `<p class="muted">${escapeHtml(row.note)}</p>` : ''}
          <div class="muted">${fmtDate(row.updated_at)} · ${escapeHtml(row.actor)}</div>
          ${reviewStateControls('normalized_correction', row.correction_id, row.status)}
        </article>
      `)}
      ${renderReviewList('Proposed facts', review.proposed_facts || [], (row) => `
        <article class="review-item">
          <div class="tag-line">
            <span class="pill">${escapeHtml(row.status)}</span>
            <span class="pill">${escapeHtml(row.fact_type)}</span>
            ${row.field_path ? `<span class="pill">${escapeHtml(row.field_path)}</span>` : ''}
          </div>
          <p><strong>${escapeHtml(row.normalized_value || row.raw_value)}</strong>${row.unit ? ` ${escapeHtml(row.unit)}` : ''}</p>
          ${row.evidence_quote ? `<p class="muted">${escapeHtml(row.evidence_quote)}</p>` : ''}
          ${row.note ? `<p class="muted">${escapeHtml(row.note)}</p>` : ''}
          <div class="muted">${fmtDate(row.updated_at)} · ${escapeHtml(row.actor)}</div>
          ${reviewStateControls('proposed_fact', row.proposed_fact_id, row.status)}
        </article>
      `)}
      ${renderReviewList('Entity links', review.entity_links || [], (row) => `
        <article class="review-item">
          <div class="tag-line">
            <span class="pill">${escapeHtml(row.status)}</span>
            <span class="pill">${escapeHtml(row.entity_type)}</span>
            ${row.evidence_selection_id ? `<span class="pill">${escapeHtml(row.evidence_selection_id)}</span>` : ''}
          </div>
          <p><strong>${escapeHtml(row.canonical_name || row.canonical_entity_id || row.mention_text)}</strong></p>
          ${row.mention_text ? `<p class="muted">${escapeHtml(row.mention_text)}</p>` : ''}
          ${row.note ? `<p class="muted">${escapeHtml(row.note)}</p>` : ''}
          <div class="muted">${fmtDate(row.updated_at)} · ${escapeHtml(row.actor)}</div>
          ${reviewStateControls('entity_link', row.entity_link_id, row.status)}
        </article>
      `)}
      ${renderReviewList('Claim stubs', review.claim_records || [], (row) => `
        <article class="review-item">
          <div class="tag-line">
            <span class="pill">${escapeHtml(row.status)}</span>
            <span class="pill">${escapeHtml(row.claim_type)}</span>
            <span class="pill">${escapeHtml(row.evidence_relation)}</span>
            ${row.evidence_selection_id ? `<span class="pill">${escapeHtml(row.evidence_selection_id)}</span>` : ''}
          </div>
          <p><strong>${escapeHtml(row.claim_text)}</strong></p>
          ${row.note ? `<p class="muted">${escapeHtml(row.note)}</p>` : ''}
          <div class="muted">${fmtDate(row.updated_at)} · ${escapeHtml(row.actor)}</div>
          ${reviewStateControls('claim_stub', row.claim_id, row.status)}
        </article>
      `)}
      ${renderReviewList('Review events', review.events || [], (row) => `
        <article class="review-item compact">
          <div class="tag-line">
            <span class="pill">${escapeHtml(row.event_type)}</span>
            <span class="pill">${escapeHtml(row.subject_type)}</span>
          </div>
          <pre>${escapeHtml(JSON.stringify(parseJsonField(row.payload_json), null, 2))}</pre>
          <div class="muted">${fmtDate(row.created_at)} · ${escapeHtml(row.actor)}</div>
        </article>
      `)}
    </div>
  `;
  wireReviewEvents(source, attachedSelection);
}

async function refreshReviewState() {
  const source = await fetchJson(`/api/source?id=${encodeURIComponent(state.selectedId)}`);
  state.currentSource = source;
  renderNormalized(source);
  renderReview(source);
  renderProvenance(source);
  renderRaw(source);
}

function wireReviewEvents(source, attachedSelection) {
  const status = $('reviewStatus');
  const saveSelection = $('saveSelection');
  if (saveSelection) {
    saveSelection.addEventListener('click', async () => {
      try {
        status.textContent = 'Saving evidence selection...';
        const base = selectedReviewBase(source);
        await postJson('/api/evidence/selections', {
          ...base,
          selection_kind: state.selectedBlock?.block_type || 'text',
          note: $('selectionNote').value,
          status: 'selected',
        });
        await refreshReviewState();
      } catch (error) {
        status.textContent = error.message;
      }
    });
  }
  $('saveAnnotation').addEventListener('click', async () => {
    try {
      status.textContent = 'Saving annotation...';
      const base = selectedReviewBase(source);
      await postJson('/api/annotations', {
        ...base,
        evidence_selection_id: attachedSelection?.selection_id || '',
        annotation_type: $('annotationType').value,
        body: $('annotationBody').value,
        status: 'open',
      });
      await refreshReviewState();
    } catch (error) {
      status.textContent = error.message;
    }
  });
  const saveCorrection = $('saveCorrection');
  if (saveCorrection) {
    saveCorrection.addEventListener('click', async () => {
      try {
        status.textContent = 'Saving correction overlay...';
        const base = selectedReviewBase(source);
        await postJson('/api/normalized-corrections', {
          ...base,
          correction_kind: $('correctionKind').value,
          original_text: $('correctionOriginal').value,
          corrected_text: $('correctionCorrected').value,
          note: $('correctionNote').value,
          status: 'proposed',
        });
        await refreshReviewState();
      } catch (error) {
        status.textContent = error.message;
      }
    });
  }
  $('saveFact').addEventListener('click', async () => {
    try {
      status.textContent = 'Saving proposed fact...';
      const base = selectedReviewBase(source);
      await postJson('/api/proposed-facts', {
        ...base,
        evidence_selection_id: attachedSelection?.selection_id || '',
        fact_type: $('factType').value,
        field_path: $('factFieldPath').value,
        raw_value: $('factRawValue').value,
        normalized_value: $('factNormalizedValue').value,
        unit: $('factUnit').value,
        note: $('factNote').value,
        evidence_quote: state.selectedBlock?.quote || '',
        status: 'proposed',
      });
      await refreshReviewState();
    } catch (error) {
      status.textContent = error.message;
    }
  });
  $('saveEntityLink').addEventListener('click', async () => {
    try {
      status.textContent = 'Saving entity link...';
      const base = selectedReviewBase(source);
      await postJson('/api/entity-links', {
        ...base,
        evidence_selection_id: attachedSelection?.selection_id || '',
        entity_type: $('entityType').value,
        mention_text: $('entityMentionText').value,
        canonical_name: $('entityCanonicalName').value,
        canonical_entity_id: $('entityCanonicalId').value,
        note: $('entityNote').value,
        status: 'proposed',
      });
      await refreshReviewState();
    } catch (error) {
      status.textContent = error.message;
    }
  });
  $('saveClaimRecord').addEventListener('click', async () => {
    try {
      status.textContent = 'Saving claim stub...';
      const qualifierText = $('claimQualifier').value.trim();
      let qualifier = {};
      if (qualifierText) {
        try {
          qualifier = JSON.parse(qualifierText);
        } catch (error) {
          status.textContent = `Qualifier JSON error: ${error.message}`;
          return;
        }
      }
      const base = selectedReviewBase(source);
      await postJson('/api/claim-records', {
        ...base,
        evidence_selection_id: attachedSelection?.selection_id || '',
        claim_type: $('claimType').value,
        evidence_relation: $('claimEvidenceRelation').value,
        claim_text: $('claimText').value,
        qualifier,
        note: $('claimNote').value,
        status: 'draft',
      });
      await refreshReviewState();
    } catch (error) {
      status.textContent = error.message;
    }
  });
  document.querySelectorAll('[data-review-update]').forEach((button) => {
    button.addEventListener('click', async () => {
      const key = button.dataset.reviewUpdate || '';
      const separator = key.indexOf(':');
      const subjectType = key.slice(0, separator);
      const subjectId = key.slice(separator + 1);
      const statusSelect = document.querySelector(`[data-review-status="${cssEscape(key)}"]`);
      const noteInput = document.querySelector(`[data-review-note="${cssEscape(key)}"]`);
      try {
        status.textContent = 'Updating review state...';
        await postJson('/api/review-state', {
          source_evidence_id: source.latest?.evidence_id || state.selectedId,
          source_project: source.latest?.source_project || '',
          project: source.latest?.source_project || '',
          subject_type: subjectType,
          subject_id: subjectId,
          status: statusSelect?.value || '',
          note: noteInput?.value || '',
        });
        await refreshReviewState();
      } catch (error) {
        status.textContent = error.message;
      }
    });
  });
}

function renderRaw(source) {
  $('tab-raw').innerHTML = `<pre>${escapeHtml(JSON.stringify({
    latest: source.latest,
    observations: source.observations,
    review: source.review,
  }, null, 2))}</pre>`;
}

async function selectSource(id) {
  if (state.selectedId !== id) state.selectedBlock = null;
  state.selectedId = id;
  document.body.classList.add('has-source');
  $('sourceEmpty').classList.add('hidden');
  $('sourceView').classList.remove('hidden');
  $('sourceTitle').textContent = 'Loading source...';
  try {
    const source = await fetchJson(`/api/source?id=${encodeURIComponent(id)}`);
    state.currentSource = source;
    const latest = source.latest || {};
    $('sourceKind').textContent = latest.source_kind || 'source';
    $('sourceTitle').textContent = latest.title || latest.canonical_url || latest.evidence_id || '(untitled source)';
    $('sourceUrl').textContent = latest.canonical_url || '';
    $('sourceUrl').href = latest.canonical_url || '#';
    $('sourceMeta').textContent = `${latest.author_handle ? '@' + latest.author_handle + ' · ' : ''}${latest.domain || ''} · ${fmtDate(latest.captured_at)}`;
    renderNormalized(source);
    renderEvidenceDocumentPlaceholder(source);
    renderArtifacts(source);
    renderEnrichment(source);
    renderRelated(source);
    renderRaw(source);
    renderReview(source);
    renderProvenance(source);
    document.querySelectorAll('.row').forEach((row) => {
      row.classList.toggle('source-open', row.dataset.id === id);
    });
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
    loadHome();
    loadFacets();
    loadInbox();
    loadRoutePage();
    if (state.selectedId) selectSource(state.selectedId);
  });
  $('datalabCase').addEventListener('click', () => {
    state.queue = 'all';
    state.kind = '';
    state.project = '';
    state.q = 'datalab chandra';
    syncInboxSearchInputs(state.q);
    $('projectSelect').value = '';
    loadFacets();
    loadInbox();
    setRoute('inbox');
  });
  $('captureSourceButton').addEventListener('click', () => {
    setRoute('inbox');
  });
  $('openInboxLink').addEventListener('click', (event) => {
    event.preventDefault();
    setRoute('inbox');
  });
  $('allSourcesButton').addEventListener('click', () => {
    state.queue = 'all';
    state.kind = state.homeEvidenceKind || '';
    state.q = '';
    state.libraryScope = 'corpus';
    syncInboxSearchInputs('');
    loadFacets();
    loadInbox();
    setRoute('library');
  });
  document.querySelectorAll('[data-route]').forEach((button) => {
    button.addEventListener('click', () => {
      setRoute(button.dataset.route || 'home');
    });
  });
  $('searchInput').addEventListener('input', () => {
    state.q = $('searchInput').value.trim();
    if ($('inboxLocalSearch') && $('inboxLocalSearch').value !== state.q) $('inboxLocalSearch').value = state.q;
    clearTimeout(window.__inboxTimer);
    window.__inboxTimer = setTimeout(() => {
      if (state.route === 'library' || state.route === 'evidence') replaceRouteHash();
      if (state.route === 'home' || state.route === 'inbox') loadInbox();
      else loadRoutePage();
    }, 250);
  });
  $('inboxLocalSearch').addEventListener('input', () => {
    state.q = $('inboxLocalSearch').value.trim();
    if ($('searchInput').value !== state.q) $('searchInput').value = state.q;
    clearTimeout(window.__inboxTimer);
    window.__inboxTimer = setTimeout(() => loadInbox(), 250);
  });
  $('inboxClearFilters').addEventListener('click', () => {
    state.queue = 'all';
    state.kind = '';
    state.project = '';
    state.q = '';
    state.previewTaskKey = '';
    syncInboxSearchInputs('');
    $('projectSelect').value = '';
    loadFacets();
    loadInbox();
  });
  $('inboxRefreshInline').addEventListener('click', () => {
    loadFacets();
    loadInbox();
  });
  $('inboxSelectAll').addEventListener('change', () => {
    document.querySelectorAll('#inboxRows .task-check').forEach((checkbox) => {
      checkbox.checked = $('inboxSelectAll').checked;
    });
  });
  document.querySelectorAll('[data-bulk-action]').forEach((button) => {
    button.addEventListener('click', async () => {
      try {
        await applyBulkInboxAction(button.dataset.bulkAction || 'defer');
      } catch (error) {
        const preview = $('previewActionStatus');
        if (preview) preview.textContent = error.message;
      }
    });
  });
  $('projectSelect').addEventListener('change', () => {
    state.project = $('projectSelect').value;
    state.previewTaskKey = '';
    loadInbox();
    if (state.route !== 'home' && state.route !== 'inbox') {
      if (state.route === 'library' || state.route === 'evidence') replaceRouteHash();
      loadRoutePage();
    }
  });
  $('limitSelect').addEventListener('change', () => {
    state.limit = $('limitSelect').value;
    loadInbox();
    if (state.route !== 'home' && state.route !== 'inbox') loadRoutePage();
  });
  document.querySelectorAll('.tab').forEach((tab) => {
    tab.addEventListener('click', () => activateTab(tab.dataset.tab));
  });
  window.addEventListener('hashchange', () => {
    const { route } = currentHashParts();
    applyHashParams();
    setRoute(route, false);
  });
}

async function init() {
  wireEvents();
  const { route } = currentHashParts();
  state.route = routeConfig[route] ? route : 'home';
  applyHashParams();
  await loadHome();
  await loadFacets();
  await loadInbox();
  await loadRoutePage();
}

init().catch((error) => {
  $('inboxRows').innerHTML = `<div class="empty-state"><h2>Startup error</h2><p>${escapeHtml(error.message)}</p></div>`;
});
