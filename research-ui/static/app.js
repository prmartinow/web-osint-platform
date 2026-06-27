const state = {
  route: 'home',
  queue: 'all',
  kind: '',
  project: '',
  q: '',
  limit: '80',
  selectedId: '',
  previewTaskKey: '',
  routeScrollMemory: {},  // route -> scrollY, for back-nav scroll restoration
  entityDetailId: '',     // entity_row_id for the /entity-detail route
  entityDetailTab: 'overview',
  conflictClusterId: '',
  conflictResolution: 'leave_unresolved',
  conflictReasonCode: 'unresolved',
  conflictPreferredClaimId: '',
  timelineLane: '',
  timelineDateType: 'event',
  timelineDateFrom: '',
  timelineDateTo: '',
  timelineConfidence: '',
  timelineReviewState: '',
  timelineSourceKind: '',
  timelineSavedView: '',
  topicDetailId: '',
  topicDetailTab: 'overview',
  compareViewId: 'claims',
  compareSelectedCellKey: '',
  compareData: null,
  benchmarkId: 'benchmark',
  draftId: 'working-draft',
  publicationBundleId: '',
  publicationDetailTab: 'overview',
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
  evidenceQueue: 'all',
  evidenceType: '',
  evidenceReviewState: '',
  evidenceSourceKind: '',
  evidenceAnchorType: '',
  evidenceSelectedId: '',
  evidenceSelectedIds: new Set(),
  evidencePreviewTab: 'overview',
  evidenceRows: [],
  entityQueue: 'all',
  entityType: '',
  entityReviewState: '',
  entitySourceKind: '',
  entitySelectedId: '',
  entitySelectedIds: new Set(),
  entityPreviewTab: 'identity',
  entityRows: [],
  claimQueue: 'all',
  claimType: '',
  claimReviewState: '',
  claimContradictionState: '',
  claimSourceKind: '',
  claimSelectedId: '',
  claimSelectedIds: new Set(),
  claimPreviewTab: 'review',
  claimRows: [],
  reviewQueue: 'all',
  reviewType: '',
  reviewDecisionState: '',
  reviewPriority: '',
  reviewLayer: '',
  reviewSelectedId: '',
  reviewSelectedIds: new Set(),
  reviewPreviewTab: 'review',
  reviewRows: [],
  publishingRows: [],
  publishingSelectedId: '',
  publishingPreviewTab: 'readiness',
  captureLaunchStatus: '',
  sidebarCollapsed: localStorage.getItem('web-osint-sidebar-collapsed') === '1',
  taxonomyQueue: 'proposed_terms',
  taxonomyVocabulary: '',
  taxonomyReviewState: '',
  taxonomySearchMode: 'hybrid',
  taxonomySelectedId: '',
  taxonomySelectedIds: new Set(),
  taxonomyPreviewTab: 'overview',
  taxonomyRows: [],
};

const $ = (id) => document.getElementById(id);

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;'
  })[char]);
}

// Allowlist URL schemes before interpolating a server-supplied URL into an
// href/src attribute. escapeHtml alone does not stop "javascript:" URLs, so a
// captured/normalized value like "javascript:alert(1)" would otherwise survive
// and become a clickable XSS vector. Relative URLs (incl. the /api/artifact
// links) and known-safe schemes pass through; anything else is neutralized.
const SAFE_URL_SCHEMES = /^(https?:|mailto:|\/|$)/i;
function safeUrl(value) {
  const raw = String(value ?? '').trim();
  return SAFE_URL_SCHEMES.test(raw) ? raw : '#';
}

// Build a stable idempotency key per logical mutation. A retry of the exact
// same action (same object + action + current status) produces the same key,
// so the backend can dedupe a double-submit; a genuine new action (e.g. a
// status change) changes the current status and gets a fresh key. Using
// Date.now() here defeated server-side dedup because every click minted a
// unique key.
function idempotencyKey(...parts) {
  return parts.map((p) => String(p ?? '')).join(':');
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
  timeline: { title: 'Timeline', endpoint: '' },
  compare: { title: 'Compare', endpoint: '' },
  'topic-detail': { title: 'Topic Detail', endpoint: '' },
  benchmark: { title: 'Benchmark Detail', endpoint: '' },
  draft: { title: 'Draft Editor', endpoint: '' },
  'publication-detail': { title: 'Publication Review', endpoint: '' },
  'entity-detail': { title: 'Entity Detail', endpoint: '' },
  'conflict-detail': { title: 'Conflict Resolution', endpoint: '' },
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
    state.evidenceQueue = params.get('queue') || state.evidenceQueue || 'all';
    state.evidenceType = params.get('type') || '';
    state.evidenceReviewState = params.get('review_state') || '';
    state.evidenceSourceKind = params.get('source_kind') || '';
    state.evidenceAnchorType = params.get('anchor_type') || '';
    const inspect = params.get('inspect') || '';
    state.evidenceSelectedId = inspect.startsWith('evidence:') ? inspect.slice(9) : inspect;
  }
  if (route === 'entities') {
    state.q = params.get('q') || state.q || '';
    state.project = params.get('project') || state.project || '';
    state.entityQueue = params.get('queue') || state.entityQueue || 'all';
    state.entityType = params.get('entity_type') || '';
    state.entityReviewState = params.get('review_state') || '';
    state.entitySourceKind = params.get('source_kind') || '';
    const inspect = params.get('inspect') || '';
    state.entitySelectedId = inspect.startsWith('entity:') ? inspect.slice(7) : inspect;
  }
  if (route === 'claims') {
    state.q = params.get('q') || state.q || '';
    state.project = params.get('project') || state.project || '';
    state.claimQueue = params.get('queue') || 'all';
    state.claimType = params.get('claim_type') || '';
    state.claimReviewState = params.get('review_state') || '';
    state.claimContradictionState = params.get('contradiction_state') || '';
    state.claimSourceKind = params.get('source_kind') || '';
    const inspect = params.get('inspect') || '';
    state.claimSelectedId = inspect.startsWith('claim:') ? inspect.slice(6) : inspect;
  }
  if (route === 'reviews') {
    state.q = params.get('q') || state.q || '';
    state.project = params.get('project') || state.project || '';
    state.reviewQueue = params.get('queue') || 'all';
    state.reviewType = params.get('type') || '';
    state.reviewDecisionState = params.get('decision_state') || '';
    state.reviewPriority = params.get('priority') || '';
    state.reviewLayer = params.get('layer') || '';
    state.reviewPreviewTab = params.get('tab') || 'review';
    const inspect = params.get('inspect') || '';
    state.reviewSelectedId = inspect.startsWith('review:') ? inspect.slice(7) : inspect;
  }
  if (route === 'publishing') {
    state.q = params.get('q') || state.q || '';
    state.project = params.get('project') || state.project || '';
    state.publishingPreviewTab = params.get('tab') || state.publishingPreviewTab || 'readiness';
    const inspect = params.get('inspect') || '';
    state.publishingSelectedId = inspect.startsWith('bundle:') ? inspect.slice(7) : inspect;
  }
  if (route === 'taxonomy') {
    state.q = params.get('q') || state.q || '';
    state.project = params.get('project') || state.project || '';
    state.taxonomyQueue = params.get('queue') || state.taxonomyQueue || 'proposed_terms';
    state.taxonomyVocabulary = params.get('vocabulary') || '';
    state.taxonomyReviewState = params.get('review_state') || '';
    state.taxonomySearchMode = params.get('mode') || state.taxonomySearchMode || 'hybrid';
    state.taxonomyPreviewTab = params.get('tab') || state.taxonomyPreviewTab || 'overview';
    const inspect = params.get('inspect') || '';
    state.taxonomySelectedId = inspect.startsWith('taxonomy:') ? inspect.slice(9) : inspect;
  }
  if (route === 'inbox') {
    state.queue = params.get('queue') || state.queue || 'all';
    state.q = params.get('q') || state.q || '';
    const inboxInspect = params.get('inspect') || '';
    state.previewTaskKey = inboxInspect.startsWith('task:') ? inboxInspect.slice(5) : inboxInspect;
  }
  if (route === 'entity-detail') {
    state.entityDetailId = params.get('id') || '';
    state.entityDetailTab = params.get('tab') || 'overview';
  }
  if (route === 'conflict-detail') {
    state.conflictClusterId = params.get('id') || '';
    state.conflictResolution = params.get('resolution') || 'leave_unresolved';
    state.conflictReasonCode = params.get('reason') || 'unresolved';
  }
  if (route === 'timeline') {
    state.project = params.get('project') || state.project || '';
    state.q = params.get('q') || state.q || '';
    state.timelineLane = params.get('lane') || '';
    state.timelineDateType = params.get('date_type') || 'event';
    state.timelineDateFrom = params.get('date_from') || '';
    state.timelineDateTo = params.get('date_to') || '';
    state.timelineConfidence = params.get('confidence') || '';
    state.timelineReviewState = params.get('review_state') || '';
    state.timelineSourceKind = params.get('source_kind') || '';
    state.timelineSavedView = params.get('saved_view') || '';
  }
  if (route === 'compare') {
    state.project = params.get('project') || state.project || '';
    state.compareViewId = params.get('view') || 'claims';
  }
  if (route === 'topic-detail') {
    state.topicDetailId = params.get('id') || '';
    state.topicDetailTab = params.get('tab') || 'overview';
    state.project = params.get('project') || state.project || '';
  }
  if (route === 'benchmark') {
    state.benchmarkId = params.get('id') || 'benchmark';
    state.project = params.get('project') || state.project || '';
  }
  if (route === 'draft') {
    state.draftId = params.get('id') || 'working-draft';
    state.project = params.get('project') || state.project || '';
  }
  if (route === 'publication-detail') {
    state.publicationBundleId = params.get('id') || '';
    state.publicationDetailTab = params.get('tab') || 'overview';
  }
}

function routeHash() {
  if (state.route === 'evidence') {
    const params = new URLSearchParams();
    if (state.q) params.set('q', state.q);
    if (state.project) params.set('project', state.project);
    if (state.evidenceMode && state.evidenceMode !== 'hybrid') params.set('mode', state.evidenceMode);
    if (state.evidenceQueue && state.evidenceQueue !== 'all') params.set('queue', state.evidenceQueue);
    if (state.evidenceType) params.set('type', state.evidenceType);
    if (state.evidenceReviewState) params.set('review_state', state.evidenceReviewState);
    if (state.evidenceSourceKind) params.set('source_kind', state.evidenceSourceKind);
    if (state.evidenceAnchorType) params.set('anchor_type', state.evidenceAnchorType);
    if (state.evidenceSelectedId) params.set('inspect', `evidence:${state.evidenceSelectedId}`);
    const query = params.toString();
    return `#evidence${query ? '?' + query : ''}`;
  }
  if (state.route === 'entities') {
    const params = new URLSearchParams();
    if (state.q) params.set('q', state.q);
    if (state.project) params.set('project', state.project);
    if (state.entityQueue && state.entityQueue !== 'all') params.set('queue', state.entityQueue);
    if (state.entityType) params.set('entity_type', state.entityType);
    if (state.entityReviewState) params.set('review_state', state.entityReviewState);
    if (state.entitySourceKind) params.set('source_kind', state.entitySourceKind);
    if (state.entitySelectedId) params.set('inspect', `entity:${state.entitySelectedId}`);
    const query = params.toString();
    return `#entities${query ? '?' + query : ''}`;
  }
  if (state.route === 'claims') {
    const params = new URLSearchParams();
    if (state.q) params.set('q', state.q);
    if (state.project) params.set('project', state.project);
    if (state.claimQueue && state.claimQueue !== 'all') params.set('queue', state.claimQueue);
    if (state.claimType) params.set('claim_type', state.claimType);
    if (state.claimReviewState) params.set('review_state', state.claimReviewState);
    if (state.claimContradictionState) params.set('contradiction_state', state.claimContradictionState);
    if (state.claimSourceKind) params.set('source_kind', state.claimSourceKind);
    if (state.claimSelectedId) params.set('inspect', `claim:${state.claimSelectedId}`);
    const query = params.toString();
    return `#claims${query ? '?' + query : ''}`;
  }
  if (state.route === 'reviews') {
    const params = new URLSearchParams();
    if (state.q) params.set('q', state.q);
    if (state.project) params.set('project', state.project);
    if (state.reviewQueue && state.reviewQueue !== 'all') params.set('queue', state.reviewQueue);
    if (state.reviewType) params.set('type', state.reviewType);
    if (state.reviewDecisionState) params.set('decision_state', state.reviewDecisionState);
    if (state.reviewPriority) params.set('priority', state.reviewPriority);
    if (state.reviewLayer) params.set('layer', state.reviewLayer);
    if (state.reviewSelectedId) params.set('inspect', `review:${state.reviewSelectedId}`);
    if (state.reviewPreviewTab && state.reviewPreviewTab !== 'review') params.set('tab', state.reviewPreviewTab);
    const query = params.toString();
    return `#reviews${query ? '?' + query : ''}`;
  }
  if (state.route === 'publishing') {
    const params = new URLSearchParams();
    if (state.q) params.set('q', state.q);
    if (state.project) params.set('project', state.project);
    if (state.publishingSelectedId) params.set('inspect', `bundle:${state.publishingSelectedId}`);
    if (state.publishingPreviewTab && state.publishingPreviewTab !== 'readiness') params.set('tab', state.publishingPreviewTab);
    const query = params.toString();
    return `#publishing${query ? '?' + query : ''}`;
  }
  if (state.route === 'taxonomy') {
    const params = new URLSearchParams();
    if (state.q) params.set('q', state.q);
    if (state.project) params.set('project', state.project);
    if (state.taxonomyQueue && state.taxonomyQueue !== 'proposed_terms') params.set('queue', state.taxonomyQueue);
    if (state.taxonomyVocabulary) params.set('vocabulary', state.taxonomyVocabulary);
    if (state.taxonomyReviewState) params.set('review_state', state.taxonomyReviewState);
    if (state.taxonomySearchMode && state.taxonomySearchMode !== 'hybrid') params.set('mode', state.taxonomySearchMode);
    if (state.taxonomySelectedId) params.set('inspect', `taxonomy:${state.taxonomySelectedId}`);
    if (state.taxonomyPreviewTab && state.taxonomyPreviewTab !== 'overview') params.set('tab', state.taxonomyPreviewTab);
    const query = params.toString();
    return `#taxonomy${query ? '?' + query : ''}`;
  }
  if (state.route === 'inbox') {
    const params = new URLSearchParams();
    if (state.q) params.set('q', state.q);
    if (state.queue && state.queue !== 'all') params.set('queue', state.queue);
    if (state.previewTaskKey) params.set('inspect', `task:${state.previewTaskKey}`);
    const query = params.toString();
    return `#inbox${query ? '?' + query : ''}`;
  }
  if (state.route === 'entity-detail') {
    const params = new URLSearchParams();
    if (state.entityDetailId) params.set('id', state.entityDetailId);
    if (state.entityDetailTab && state.entityDetailTab !== 'overview') params.set('tab', state.entityDetailTab);
    const query = params.toString();
    return `#entity-detail${query ? '?' + query : ''}`;
  }
  if (state.route === 'conflict-detail') {
    const params = new URLSearchParams();
    if (state.conflictClusterId) params.set('id', state.conflictClusterId);
    if (state.conflictResolution && state.conflictResolution !== 'leave_unresolved') params.set('resolution', state.conflictResolution);
    if (state.conflictReasonCode && state.conflictReasonCode !== 'unresolved') params.set('reason', state.conflictReasonCode);
    const query = params.toString();
    return `#conflict-detail${query ? '?' + query : ''}`;
  }
  if (state.route === 'timeline') {
    const params = new URLSearchParams();
    if (state.project) params.set('project', state.project);
    if (state.q) params.set('q', state.q);
    if (state.timelineLane) params.set('lane', state.timelineLane);
    if (state.timelineDateType && state.timelineDateType !== 'event') params.set('date_type', state.timelineDateType);
    if (state.timelineDateFrom) params.set('date_from', state.timelineDateFrom);
    if (state.timelineDateTo) params.set('date_to', state.timelineDateTo);
    if (state.timelineConfidence) params.set('confidence', state.timelineConfidence);
    if (state.timelineReviewState) params.set('review_state', state.timelineReviewState);
    if (state.timelineSourceKind) params.set('source_kind', state.timelineSourceKind);
    if (state.timelineSavedView) params.set('saved_view', state.timelineSavedView);
    const query = params.toString();
    return `#timeline${query ? '?' + query : ''}`;
  }
  if (state.route === 'compare') {
    const params = new URLSearchParams();
    if (state.project) params.set('project', state.project);
    if (state.compareViewId && state.compareViewId !== 'claims') params.set('view', state.compareViewId);
    const query = params.toString();
    return `#compare${query ? '?' + query : ''}`;
  }
  if (state.route === 'topic-detail') {
    const params = new URLSearchParams();
    if (state.topicDetailId) params.set('id', state.topicDetailId);
    if (state.project) params.set('project', state.project);
    if (state.topicDetailTab && state.topicDetailTab !== 'overview') params.set('tab', state.topicDetailTab);
    const query = params.toString();
    return `#topic-detail${query ? '?' + query : ''}`;
  }
  if (state.route === 'benchmark') {
    const params = new URLSearchParams();
    if (state.benchmarkId && state.benchmarkId !== 'benchmark') params.set('id', state.benchmarkId);
    if (state.project) params.set('project', state.project);
    const query = params.toString();
    return `#benchmark${query ? '?' + query : ''}`;
  }
  if (state.route === 'draft') {
    const params = new URLSearchParams();
    if (state.draftId && state.draftId !== 'working-draft') params.set('id', state.draftId);
    if (state.project) params.set('project', state.project);
    const query = params.toString();
    return `#draft${query ? '?' + query : ''}`;
  }
  if (state.route === 'publication-detail') {
    const params = new URLSearchParams();
    if (state.publicationBundleId) params.set('id', state.publicationBundleId);
    if (state.publicationDetailTab && state.publicationDetailTab !== 'overview') params.set('tab', state.publicationDetailTab);
    const query = params.toString();
    return `#publication-detail${query ? '?' + query : ''}`;
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

function pushRouteHash() {
  history.pushState(null, '', routeHash());
}

function sourceKindForCoverage(key) {
  if (key === 'x') return 'x_post';
  if (key === 'web') return 'web_page';
  // The "papers" column historically counted user_input (manual research
  // notes/docs), not arXiv-style papers. The header is labeled "Notes/docs"
  // to reflect that honestly; the key stays "papers" for data compatibility.
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

// Read the response body, parsing JSON only when the server actually sent
// JSON. A ClickHouse 502 or a reverse-proxy error page returns HTML, and
// calling response.json() on it throws a useless "Unexpected token '<'" that
// hides the real status. Fall back to the status text in that case.
async function readResponse(response) {
  const text = await response.text();
  let data = null;
  const contentType = response.headers.get('content-type') || '';
  if (contentType.includes('application/json') || (text.trim().startsWith('{') || text.trim().startsWith('['))) {
    try { data = JSON.parse(text); } catch (_) { data = null; }
  }
  if (!response.ok) {
    const message = (data && (data.error || data.message)) || response.statusText || `HTTP ${response.status}`;
    throw new Error(message);
  }
  return data !== null ? data : text;
}

// Monotonic sequence guard so a stale fetch (e.g. from an earlier keystroke in
// the search box, or a refresh started before the user selected a different
// source) cannot overwrite the UI with older data. makeFetchToken() starts a
// new round; isCurrentFetchToken(token) returns false once a newer round began.
let __fetchTokenCounter = 0;
function makeFetchToken() { __fetchTokenCounter += 1; return __fetchTokenCounter; }
function isCurrentFetchToken(token) { return token === __fetchTokenCounter; }

async function fetchJson(url, signal) {
  const response = await fetch(url, { cache: 'no-store', signal });
  return readResponse(response);
}

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return readResponse(response);
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

function setSidebarCollapsed(collapsed) {
  state.sidebarCollapsed = Boolean(collapsed);
  document.body.classList.toggle('rail-collapsed', state.sidebarCollapsed);
  localStorage.setItem('web-osint-sidebar-collapsed', state.sidebarCollapsed ? '1' : '0');
  const toggle = $('sidebarToggle');
  if (!toggle) return;
  const label = state.sidebarCollapsed ? 'Open sidebar' : 'Close sidebar';
  toggle.setAttribute('aria-expanded', state.sidebarCollapsed ? 'false' : 'true');
  toggle.setAttribute('aria-label', label);
  toggle.setAttribute('title', label);
  toggle.dataset.tooltip = label;
}

function renderFacets(data) {
  state.facets = data;
  const totals = data.totals || {};
  $('totals').textContent = `${totals.unique_evidence ?? 0} unique sources · ${totals.evidence_rows ?? 0} rows · last ingest ${fmtDate(totals.last_ingested_at)}`;
  $('navInboxCount').textContent = totals.unique_evidence ?? 0;
  if ($('pnavInboxCount')) $('pnavInboxCount').textContent = totals.unique_evidence ?? 0;

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
      <thead><tr><th>Where the current brief is strong and where it needs more sources</th><th>X/social</th><th>Web</th><th>Notes/docs</th><th>Media</th></tr></thead>
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
    // Thread the active project so the backend sources the research brief
    // (question, scope, open questions) for the project the analyst is in,
    // rather than returning a fixed hardcoded brief.
    const homePath = state.project ? `/api/home?project=${encodeURIComponent(state.project)}` : '/api/home';
    renderHome(await fetchJson(homePath));
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
  document.querySelectorAll('.object-row[data-id], .mini-source-row[data-id], .timeline-item [data-id], .ledger-table [data-id], .detail-card [data-id]').forEach((button) => {
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
      ${projectRouteButton(row, 'Timeline', 'timeline')}
      ${projectRouteButton(row, 'Compare', 'compare')}
      ${projectRouteButton(row, 'Drafts', 'draft')}
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
    idempotency_key: idempotencyKey('project-brief', row.project_id || '', state.activeProjectBriefVersion || row.brief?.version || ''),
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
  window.__projectBriefSaveTimer = setTimeout(() => serializedSaveProjectBrief(row), 850);
}

// Serialize brief saves so overlapping autosaves cannot clobber each other or
// write version state from a stale row. A second save while one is in flight
// is queued and runs after the first resolves, always re-reading the form.
window.__projectBriefSaveInFlight = null;
async function serializedSaveProjectBrief(row) {
  while (window.__projectBriefSaveInFlight) {
    try { await window.__projectBriefSaveInFlight; } catch (_) { /* handled below */ }
  }
  const promise = saveProjectBrief(row);
  window.__projectBriefSaveInFlight = promise;
  try {
    await promise;
  } finally {
    if (window.__projectBriefSaveInFlight === promise) window.__projectBriefSaveInFlight = null;
  }
}

async function saveProjectBrief(row) {
  try {
    const result = await postJson('/api/project-brief', projectBriefPayload(row));
    // Only apply version/display state if this row is still the active project
    // by the time the save resolves; the user may have switched projects.
    if (row && state.project && row.project_id !== state.project) {
      setProjectBriefStatus('Saved (project switched since edit)', 'warn');
      return;
    }
    row.brief = result.brief;
    state.activeProjectBriefVersion = result.brief.version;
    if ($('projectBriefVersion')) $('projectBriefVersion').textContent = `v${result.brief.version}`;
    if ($('projectBriefMaterialChanges')) $('projectBriefMaterialChanges').textContent = result.brief.material_changes_since_review ?? 0;
    if ($('projectBriefReviewState')) $('projectBriefReviewState').textContent = titleCase(result.brief.review_state || 'draft');
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
        ${source.canonical_url ? `<a href="${escapeHtml(safeUrl(source.canonical_url))}" target="_blank" rel="noreferrer">${escapeHtml(source.canonical_url)}</a>` : ''}
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
        ${artifacts.length ? `<div class="artifact-link-list">${artifacts.slice(0, 10).map((item) => `<a href="${escapeHtml(safeUrl(item.url || '#'))}" target="_blank" rel="noreferrer">${escapeHtml(item.path || item.url)}</a>`).join('')}</div>` : '<p>No artifact paths are linked to this source yet.</p>'}
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
      idempotency_key: idempotencyKey('library', action, ids.slice().sort().join(',')),
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

function evidenceQueueGroup(items) {
  const queues = items || [];
  return `
    <section class="evidence-facet-group evidence-queue-group">
      <h3>Review queues</h3>
      <div class="facet-list compact">
        ${queues.map((item) => `
          <button class="facet ${state.evidenceQueue === item.id ? 'active' : ''}" type="button" data-evidence-queue="${escapeHtml(item.id)}">
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
      ${source.canonical_url ? `<p><a href="${escapeHtml(safeUrl(source.canonical_url))}" target="_blank" rel="noreferrer">${escapeHtml(source.canonical_url)}</a></p>` : ''}
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
      <button class="secondary" data-evidence-action="classify">Classify</button>
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
      { label: `Visible objects${rows.length >= Number(state.limit || 200) ? ' (truncated)' : ''}`, value: summary.visible ?? rows.length, hint: rows.length >= Number(state.limit || 200) ? 'showing first ' + rows.length + ' — refine to see all' : '' },
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
        ${evidenceQueueGroup(facets.queues)}
        ${evidenceFacetGroup('Evidence type', facets.evidence_types, state.evidenceType, 'type')}
        ${evidenceFacetGroup('Review state', facets.review_states, state.evidenceReviewState, 'review_state')}
        ${evidenceFacetGroup('Source kind', facets.source_kinds, state.evidenceSourceKind, 'source_kind')}
        ${evidenceFacetGroup('Anchor type', facets.anchor_types, state.evidenceAnchorType, 'anchor_type')}
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
          ${['accept', 'reject', 'defer', 'assign_review', 'link_claim', 'create_claim', 'classify', 'change_type', 'taxonomy', 'export_publication'].map((action) => `<button class="secondary" data-evidence-bulk-action="${action}">${escapeHtml(titleCase(action))}</button>`).join('')}
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
    classify: 'evidence.classification.requested',
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
      actor: REVIEW_UI_ACTOR,
      expected_version: expectedVersionForRow(row),
      status: evidenceReviewStatusForAction(row, action),
      note,
      source_anchor: evidenceAnchorForRow(row, action),
      idempotency_key: idempotencyKey(evidenceRowKey(row), action, row.review_state || row.status || ''),
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
    idempotency_key: idempotencyKey(evidenceRowKey(row), action, row.review_state || row.status || ''),
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
  document.querySelectorAll('[data-evidence-queue]').forEach((button) => {
    button.addEventListener('click', () => {
      state.evidenceQueue = button.dataset.evidenceQueue || 'all';
      state.evidenceSelectedId = '';
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
    state.evidenceQueue = 'all';
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

function entityRowKey(row) {
  return row.entity_row_id || [row.row_kind, row.object_id || row.entity_name].filter(Boolean).join(':');
}

function entityGlyph(row) {
  if (row.row_kind === 'canonical_entity') return 'I';
  if (row.row_kind === 'merge_cluster') return 'M';
  if (row.row_kind === 'extracted_entity') return 'X';
  if ((row.review_state || '').includes('rejected')) return 'R';
  return 'E';
}

function entityQueueGroup(items) {
  const queues = items || [];
  return `
    <section class="entity-facet-group">
      <h3>Resolution queues</h3>
      <div class="facet-list compact">
        ${queues.map((item) => `
          <button class="facet ${state.entityQueue === item.id ? 'active' : ''}" type="button" data-entity-queue="${escapeHtml(item.id)}">
            <span>${escapeHtml(item.label || item.id)}</span><strong>${escapeHtml(item.count || 0)}</strong>
          </button>
        `).join('')}
      </div>
    </section>
  `;
}

function entityFacetGroup(title, items, activeValue, filterName) {
  const options = items || [];
  return `
    <section class="entity-facet-group">
      <h3>${escapeHtml(title)}</h3>
      <button class="facet ${activeValue ? '' : 'active'}" type="button" data-entity-filter="${escapeHtml(filterName)}" data-filter-value="">
        <span>All ${escapeHtml(title.toLowerCase())}</span><strong>${escapeHtml(options.reduce((sum, item) => sum + Number(item.count || 0), 0))}</strong>
      </button>
      <div class="facet-list compact">
        ${options.map((item) => `
          <button class="facet ${activeValue === item.id ? 'active' : ''}" type="button" data-entity-filter="${escapeHtml(filterName)}" data-filter-value="${escapeHtml(item.id)}">
            <span>${escapeHtml(item.label || item.id)}</span><strong>${escapeHtml(item.count || 0)}</strong>
          </button>
        `).join('')}
      </div>
    </section>
  `;
}

function renderEntityPreview(data) {
  const preview = data.preview || {};
  const row = preview.row || null;
  if (!row) {
    return `
      <div class="empty-state">
        <h2>Identity Preview</h2>
        <p>Select an entity row to inspect mentions, proposed canonical matches, relation proposals, and provenance.</p>
      </div>
    `;
  }
  const activeTab = ['identity', 'mentions', 'relations', 'provenance'].includes(state.entityPreviewTab) ? state.entityPreviewTab : 'identity';
  const tab = (id, label) => `<button class="${activeTab === id ? 'active' : ''}" type="button" data-entity-preview-tab="${id}">${label}</button>`;
  const sectionClass = (id) => `entity-preview-section ${activeTab === id ? 'active' : ''}`;
  const mentions = preview.mentions || [];
  const matches = preview.proposed_matches || [];
  const relations = preview.relationship_proposals || [];
  return `
    <div class="entity-preview-head">
      <span class="source-glyph">${escapeHtml(entityGlyph(row))}</span>
      <div>
        <h2>${escapeHtml(row.entity_name || row.mention_text || 'Unnamed entity')}</h2>
        <p>${escapeHtml([row.entity_type, titleCase(row.row_kind || ''), row.review_state].filter(Boolean).join(' · '))}</p>
      </div>
    </div>
    <nav class="entity-preview-tabs" aria-label="Entity preview sections">
      ${tab('identity', 'Identity')}
      ${tab('mentions', 'Mentions')}
      ${tab('relations', 'Relations')}
      ${tab('provenance', 'Provenance')}
    </nav>
    <section class="${sectionClass('identity')}" data-entity-preview-section="identity">
      <div class="entity-layer-stack">
        <div><span>Mention</span><strong>${escapeHtml(row.mention_text || row.entity_name || '')}</strong></div>
        <div><span>Canonical candidate</span><strong>${escapeHtml(row.canonical_name || row.canonical_entity_id || 'Not selected')}</strong></div>
        <div><span>Match rationale</span><strong>${escapeHtml(row.match_reason || 'No rationale recorded.')}</strong></div>
        <div><span>Boundary</span><strong>Matching resolves identity only. Aliases, facts, claims, and relationships remain separately reviewable.</strong></div>
      </div>
      <div class="tag-line">
        <span class="pill">${escapeHtml(row.review_state || 'candidate')}</span>
        <span class="pill">${escapeHtml(row.entity_type || 'unknown')}</span>
        <span class="pill">${escapeHtml(row.match_confidence || 'review')}</span>
        ${row.pending_relation_count ? `<span class="pill warn">${escapeHtml(row.pending_relation_count)} relation candidates</span>` : ''}
      </div>
      <div class="entity-detail-link-row"><button class="secondary" data-entity-detail-link="${escapeHtml(row.entity_row_id || '')}">Open detail page</button></div>
    </section>
    <section class="${sectionClass('mentions')}" data-entity-preview-section="mentions">
      <article class="entity-preview-card">
        <h4>Exact source-capture mentions (${mentions.length})</h4>
        ${mentions.map((item) => `
          <p><strong>${escapeHtml(item.mention_text || item.canonical_name || '')}</strong> · ${escapeHtml(item.status || '')}<br>${escapeHtml(item.source_title || item.source_evidence_id || '')}</p>
        `).join('') || '<p class="muted">No source-linked mentions found for this row.</p>'}
      </article>
      <article class="entity-preview-card">
        <h4>Proposed canonical matches</h4>
        ${matches.map((item) => `<p><strong>${escapeHtml(item.candidate || '')}</strong> · ${escapeHtml(item.state || '')}<br>${escapeHtml(item.reason || '')}</p>`).join('') || '<p class="muted">No canonical match proposals recorded.</p>'}
      </article>
    </section>
    <section class="${sectionClass('relations')}" data-entity-preview-section="relations">
      <article class="entity-preview-card">
        <h4>Relationship and claim proposals (${relations.length})</h4>
        ${relations.map((item) => `<p><strong>${escapeHtml(item.claim_type || 'claim')}</strong> · ${escapeHtml(item.evidence_relation || '')} · ${escapeHtml(item.status || '')}<br>${escapeHtml(item.claim_text || '')}</p>`).join('') || '<p class="muted">No linked claim or relation proposals found.</p>'}
      </article>
      <div class="entity-warning">Accepting an identity match does not accept aliases, identifiers, facts, claims, or relationships.</div>
    </section>
    <section class="${sectionClass('provenance')}" data-entity-preview-section="provenance">
      <div class="entity-provenance-stack">
        ${(preview.provenance || []).map((step, index) => `
          <article>
            <span>${String(index + 1).padStart(2, '0')}</span>
            <div><strong>${escapeHtml(step.label)}</strong><p>${escapeHtml(step.value)}</p>${step.meta ? `<em>${escapeHtml(step.meta)}</em>` : ''}</div>
          </article>
        `).join('')}
      </div>
      ${preview.source?.canonical_url ? `<p><a href="${escapeHtml(safeUrl(preview.source.canonical_url))}" target="_blank" rel="noreferrer">${escapeHtml(preview.source.canonical_url)}</a></p>` : ''}
    </section>
    <label class="preview-note">Resolution note
      <input id="entityDecisionNote" placeholder="Optional identity rationale, alias note, relation handoff, or merge context">
    </label>
    <div id="entityActionStatus" class="review-status muted"></div>
    <div class="entity-preview-actions">
      <button class="secondary" data-entity-action="defer">Defer</button>
      <button class="secondary" data-entity-action="reject">Reject</button>
      <button class="secondary" data-entity-action="merge">Merge</button>
      <button class="secondary" data-entity-action="split">Split</button>
      <button class="secondary" data-entity-action="open_source">Open source</button>
      <button data-entity-action="create">Create identity</button>
      <button data-entity-action="match">Match & next</button>
    </div>
  `;
}

function renderEntitiesPage(data) {
  const rows = data.rows || [];
  state.entityRows = rows;
  if (!state.entitySelectedId || !rows.some((row) => entityRowKey(row) === state.entitySelectedId)) {
    state.entitySelectedId = data.selected_id || (rows[0] ? entityRowKey(rows[0]) : '');
  }
  const summary = data.summary || {};
  const facets = data.facets || {};
  const selectedId = state.entitySelectedId;
  $('routePage').innerHTML = `
    ${pageHeader('Entity Directory', 'Resolve canonical identities, mentions, aliases, and relation candidates without promoting facts or claims.')}
    ${metricCards([
      { label: 'Visible entities', value: summary.visible ?? rows.length },
      { label: 'Candidates', value: summary.candidates ?? 0 },
      { label: 'Canonical', value: summary.canonical ?? 0 },
      { label: 'Pending relations', value: summary.pending_relations ?? 0 },
    ])}
    <section class="entity-shell">
      <aside class="panel entity-filter-panel">
        ${entityQueueGroup(facets.queues)}
        ${entityFacetGroup('Entity type', facets.entity_types, state.entityType, 'entity_type')}
        ${entityFacetGroup('Review state', facets.review_states, state.entityReviewState, 'review_state')}
        ${entityFacetGroup('Source kind', facets.source_kinds, state.entitySourceKind, 'source_kind')}
      </aside>
      <section class="panel entity-results-panel">
        <div class="entity-search-strip">
          <label><span>Entity search</span><input id="entitySearchInput" value="${escapeHtml(state.q)}" placeholder="Search names, aliases, handles, labs, models, sources"></label>
          <button class="secondary" id="entityClearFilters">Clear</button>
        </div>
        <div class="entity-explanation">
          <span class="status-badge info">${escapeHtml(titleCase(state.entityQueue || 'all'))}</span>
          <p>Rows represent identities, unresolved candidates, merge clusters, or entities with pending relations.</p>
        </div>
        <div class="entity-bulk-toolbar">
          <label><input type="checkbox" id="entitySelectAll"> Select visible</label>
          ${['match', 'create', 'reject', 'defer', 'merge', 'split'].map((action) => `<button class="secondary" data-entity-bulk-action="${action}">${escapeHtml(titleCase(action))}</button>`).join('')}
          <span id="entityBulkStatus" class="muted"></span>
        </div>
        <div class="entity-results-list">
          ${rows.length ? rows.map((row) => {
            const rowKey = entityRowKey(row);
            const selected = rowKey === selectedId;
            return `
              <article class="entity-row ${selected ? 'active' : ''}" data-entity-row-id="${escapeHtml(rowKey)}" data-source-id="${escapeHtml(row.source_evidence_id || '')}" data-object-type="${escapeHtml(row.object_type || '')}">
                <input class="entity-check" type="checkbox" aria-label="Select entity row" ${state.entitySelectedIds.has(rowKey) ? 'checked' : ''}>
                <span class="source-glyph">${escapeHtml(entityGlyph(row))}</span>
                <div class="entity-row-main">
                  <div class="entity-title-line">
                    <strong>${escapeHtml(row.entity_name || row.mention_text || 'Unnamed entity')}</strong>
                    ${row.row_kind === 'merge_cluster' ? '<span class="pill warn">merge</span>' : ''}
                  </div>
                  <p>${escapeHtml(row.match_reason || row.note || '')}</p>
                  <div class="row-meta">
                    <span class="pill">${escapeHtml(titleCase(row.row_kind || 'entity'))}</span>
                    <span class="pill">${escapeHtml(row.entity_type || 'unknown')}</span>
                    <span class="pill">${escapeHtml(row.review_state || 'candidate')}</span>
                    ${row.source_label ? `<span class="pill">${escapeHtml(row.source_label)}</span>` : ''}
                    ${row.domain ? `<span class="pill">${escapeHtml(row.domain)}</span>` : ''}
                  </div>
                </div>
                <div class="entity-row-counts">
                  <strong>${escapeHtml(row.mention_count || 0)}</strong><em>mentions</em>
                  <strong>${escapeHtml(row.source_count || 0)}</strong><em>sources</em>
                  <strong>${escapeHtml(row.pending_relation_count || 0)}</strong><em>relations</em>
                </div>
              </article>
            `;
          }).join('') : '<div class="empty-state"><h2>No entity rows</h2><p>Try another queue or filter.</p></div>'}
        </div>
      </section>
      <aside class="panel entity-preview-panel">
        ${renderEntityPreview(data)}
      </aside>
    </section>
  `;
  bindEntityPage(data);
}

function entityStatusForAction(row, action) {
  if (action === 'match') return 'matched';
  if (action === 'create') return 'created';
  if (action === 'reject') return 'rejected';
  if (action === 'defer') return 'proposed';
  if (action === 'merge') return 'merged';
  if (action === 'split') return 'proposed';
  return row.review_state || 'proposed';
}

function entityEventTypeForAction(action) {
  return {
    match: 'entity.identity_match.recorded',
    create: 'entity.identity_create.requested',
    reject: 'entity.identity_reject.recorded',
    defer: 'entity.identity_defer.recorded',
    merge: 'entity.merge.requested',
    split: 'entity.split.requested',
  }[action] || 'entity.action.recorded';
}

function entityAnchorForRow(row, action) {
  return {
    kind: 'entity_directory_row',
    entity_row_id: entityRowKey(row),
    source_evidence_id: row.source_evidence_id || '',
    object_type: row.object_type || '',
    object_id: row.object_id || '',
    entity_name: row.entity_name || '',
    entity_type: row.entity_type || '',
    action,
  };
}

async function persistEntityAction(row, action, note = '') {
  if (!row) return;
  if (action === 'open_source') {
    if (row.source_evidence_id) await selectSource(row.source_evidence_id);
    return;
  }
  if (row.object_type === 'entity_link' && row.object_id && ['match', 'create', 'reject', 'defer', 'merge', 'split'].includes(action)) {
    await postJson('/api/review-state', {
      source_evidence_id: row.source_evidence_id || '',
      source_project: row.source_project || '',
      project: row.source_project || state.project || '',
      subject_type: 'entity_link',
      subject_id: row.object_id,
      actor: REVIEW_UI_ACTOR,
      expected_version: expectedVersionForRow(row),
      status: entityStatusForAction(row, action),
      note,
      source_anchor: entityAnchorForRow(row, action),
      idempotency_key: idempotencyKey(entityRowKey(row), action, row.review_state || row.status || ''),
    });
    return;
  }
  await postJson('/api/review/events', {
    event_type: entityEventTypeForAction(action),
    source_evidence_id: row.source_evidence_id || '',
    source_project: row.source_project || '',
    project: row.source_project || state.project || '',
    subject_type: row.object_type || row.row_kind || 'entity',
    subject_id: row.object_id || entityRowKey(row),
    action,
    status: entityStatusForAction(row, action),
    note,
    source_anchor: entityAnchorForRow(row, action),
    idempotency_key: idempotencyKey(entityRowKey(row), action, row.review_state || row.status || ''),
  });
}

function nextEntitySelectionAfter(row) {
  const rows = state.entityRows || [];
  const index = rows.findIndex((item) => entityRowKey(item) === entityRowKey(row));
  const next = rows[index + 1] || rows[index - 1] || null;
  return next ? entityRowKey(next) : '';
}

async function applyEntityAction(row, action) {
  const status = $('entityActionStatus') || $('entityBulkStatus');
  const note = $('entityDecisionNote')?.value || '';
  if (!row) {
    if (status) status.textContent = 'Select an entity row first.';
    return;
  }
  if (status) status.textContent = `${titleCase(action)}...`;
  await persistEntityAction(row, action, note);
  if (['match', 'create', 'reject', 'defer'].includes(action)) {
    state.entitySelectedId = nextEntitySelectionAfter(row);
  }
  state.entitySelectedIds.clear();
  if (status) status.textContent = `${titleCase(action)} recorded.`;
  replaceRouteHash();
  await loadRoutePage();
}

async function applyBulkEntityAction(action) {
  const status = $('entityBulkStatus');
  const selectedIds = Array.from(document.querySelectorAll('.entity-row .entity-check:checked'))
    .map((checkbox) => checkbox.closest('.entity-row')?.dataset.entityRowId)
    .filter(Boolean);
  const selectedRows = state.entityRows.filter((row) => selectedIds.includes(entityRowKey(row)));
  if (!selectedRows.length) {
    if (status) status.textContent = 'Select at least one entity row.';
    return;
  }
  if (status) status.textContent = `${titleCase(action)} ${selectedRows.length} entity row${selectedRows.length === 1 ? '' : 's'}...`;
  for (const row of selectedRows) {
    await persistEntityAction(row, action, `Bulk ${titleCase(action)} from Entity Directory`);
  }
  state.entitySelectedIds.clear();
  if (status) status.textContent = `${titleCase(action)} recorded for ${selectedRows.length}.`;
  await loadRoutePage();
}

function moveEntitySelection(delta) {
  if (state.route !== 'entities') return;
  const rows = state.entityRows || [];
  if (!rows.length) return;
  const current = rows.findIndex((row) => entityRowKey(row) === state.entitySelectedId);
  const nextIndex = Math.max(0, Math.min(rows.length - 1, (current >= 0 ? current : 0) + delta));
  state.entitySelectedId = entityRowKey(rows[nextIndex]);
  replaceRouteHash();
  loadRoutePage();
}

function bindEntityKeyboard() {
  if (window.__webOsintEntityKeyboardBound) return;
  window.__webOsintEntityKeyboardBound = true;
  window.addEventListener('keydown', async (event) => {
    if (state.route !== 'entities') return;
    const active = document.activeElement;
    if (active && ['INPUT', 'TEXTAREA', 'SELECT', 'BUTTON'].includes(active.tagName)) return;
    const key = event.key.toLowerCase();
    if (key === 'j') {
      event.preventDefault();
      moveEntitySelection(1);
    } else if (key === 'k') {
      event.preventDefault();
      moveEntitySelection(-1);
    } else if (['m', 'c', 'r', 'd'].includes(key)) {
      event.preventDefault();
      const row = state.entityRows.find((item) => entityRowKey(item) === state.entitySelectedId);
      const action = key === 'm' ? 'match' : key === 'c' ? 'create' : key === 'r' ? 'reject' : 'defer';
      try {
        await applyEntityAction(row, action);
      } catch (error) {
        const status = $('entityActionStatus') || $('entityBulkStatus');
        if (status) status.textContent = error.message;
      }
    }
  });
}

function bindEntityPage(data) {
  document.querySelectorAll('[data-entity-detail-link]').forEach((el) => {
    el.addEventListener('click', () => openEntityDetail(el.dataset.entityDetailLink || ''));
  });
  document.querySelectorAll('[data-entity-queue]').forEach((button) => {
    button.addEventListener('click', () => {
      state.entityQueue = button.dataset.entityQueue || 'all';
      state.entitySelectedId = '';
      replaceRouteHash();
      loadRoutePage();
    });
  });
  document.querySelectorAll('[data-entity-filter]').forEach((button) => {
    button.addEventListener('click', () => {
      const filter = button.dataset.entityFilter;
      const value = button.dataset.filterValue || '';
      if (filter === 'entity_type') state.entityType = value;
      if (filter === 'review_state') state.entityReviewState = value;
      if (filter === 'source_kind') state.entitySourceKind = value;
      state.entitySelectedId = '';
      replaceRouteHash();
      loadRoutePage();
    });
  });
  $('entitySearchInput')?.addEventListener('input', () => {
    state.q = $('entitySearchInput').value.trim();
    clearTimeout(window.__entitySearchTimer);
    window.__entitySearchTimer = setTimeout(() => {
      state.entitySelectedId = '';
      replaceRouteHash();
      loadRoutePage();
    }, 250);
  });
  $('entityClearFilters')?.addEventListener('click', () => {
    state.q = '';
    state.project = '';
    state.entityQueue = 'all';
    state.entityType = '';
    state.entityReviewState = '';
    state.entitySourceKind = '';
    state.entitySelectedId = '';
    state.entitySelectedIds.clear();
    replaceRouteHash();
    loadRoutePage();
  });
  $('entitySelectAll')?.addEventListener('change', () => {
    const checked = $('entitySelectAll').checked;
    state.entitySelectedIds.clear();
    document.querySelectorAll('.entity-row').forEach((row) => {
      const id = row.dataset.entityRowId || '';
      const checkbox = row.querySelector('.entity-check');
      if (checkbox) checkbox.checked = checked;
      if (checked && id) state.entitySelectedIds.add(id);
    });
  });
  document.querySelectorAll('.entity-row').forEach((row) => {
    row.addEventListener('click', () => {
      state.entitySelectedId = row.dataset.entityRowId || '';
      replaceRouteHash();
      loadRoutePage();
    });
    row.addEventListener('dblclick', async () => {
      if (row.dataset.sourceId) await selectSource(row.dataset.sourceId);
    });
    row.querySelector('.entity-check')?.addEventListener('click', (event) => {
      event.stopPropagation();
      const id = row.dataset.entityRowId || '';
      if (!id) return;
      if (event.currentTarget.checked) state.entitySelectedIds.add(id);
      else state.entitySelectedIds.delete(id);
    });
  });
  document.querySelectorAll('[data-entity-preview-tab]').forEach((button) => {
    button.addEventListener('click', () => {
      state.entityPreviewTab = button.dataset.entityPreviewTab || 'identity';
      document.querySelectorAll('[data-entity-preview-tab]').forEach((tab) => tab.classList.toggle('active', tab === button));
      document.querySelectorAll('[data-entity-preview-section]').forEach((section) => {
        section.classList.toggle('active', section.dataset.entityPreviewSection === state.entityPreviewTab);
      });
    });
  });
  document.querySelectorAll('[data-entity-action]').forEach((button) => {
    button.addEventListener('click', async () => {
      const row = (data.rows || []).find((item) => entityRowKey(item) === state.entitySelectedId) || data.preview?.row;
      try {
        await applyEntityAction(row, button.dataset.entityAction || 'defer');
      } catch (error) {
        const status = $('entityActionStatus');
        if (status) status.textContent = error.message;
      }
    });
  });
  document.querySelectorAll('[data-entity-bulk-action]').forEach((button) => {
    button.addEventListener('click', async () => {
      try {
        await applyBulkEntityAction(button.dataset.entityBulkAction || 'defer');
      } catch (error) {
        const status = $('entityBulkStatus');
        if (status) status.textContent = error.message;
      }
    });
  });
  bindEntityKeyboard();
}

function claimRowKey(row) {
  return row.claim_row_id || [row.row_kind, row.object_id || row.claim_text].filter(Boolean).join(':');
}

function claimGlyph(row) {
  const kind = row.row_kind || '';
  const contradiction = row.contradiction_state || '';
  const review = row.review_state || '';
  if (kind === 'conflict_cluster') return '!';
  if (kind === 'duplicate_cluster') return 'D';
  if (contradiction === 'disputed' || contradiction === 'conflict') return 'U';
  if (review === 'accepted' || review === 'published') return 'A';
  if (review === 'rejected' || review === 'superseded') return 'R';
  return 'C';
}

function claimQueueGroup(items) {
  const queues = items || [];
  return `
    <section class="claim-facet-group">
      <h3>Review queues</h3>
      <div class="facet-list compact">
        ${queues.map((item) => `
          <button class="facet ${state.claimQueue === item.id ? 'active' : ''}" type="button" data-claim-queue="${escapeHtml(item.id)}">
            <span>${escapeHtml(item.label || item.id)}</span><strong>${escapeHtml(item.count || 0)}</strong>
          </button>
        `).join('')}
      </div>
    </section>
  `;
}

function claimFacetGroup(title, items, activeValue, filterName) {
  const options = items || [];
  return `
    <section class="claim-facet-group">
      <h3>${escapeHtml(title)}</h3>
      <button class="facet ${activeValue ? '' : 'active'}" type="button" data-claim-filter="${escapeHtml(filterName)}" data-filter-value="">
        <span>All ${escapeHtml(title.toLowerCase())}</span><strong>${escapeHtml(options.reduce((sum, item) => sum + Number(item.count || 0), 0))}</strong>
      </button>
      <div class="facet-list compact">
        ${options.map((item) => `
          <button class="facet ${activeValue === item.id ? 'active' : ''}" type="button" data-claim-filter="${escapeHtml(filterName)}" data-filter-value="${escapeHtml(item.id)}">
            <span>${escapeHtml(item.label || item.id)}</span><strong>${escapeHtml(item.count || 0)}</strong>
          </button>
        `).join('')}
      </div>
    </section>
  `;
}

function renderClaimPreview(data) {
  const preview = data.preview || {};
  const row = preview.row || null;
  if (!row) {
    return `
      <div class="empty-state">
        <h2>Claim Review</h2>
        <p>Select a claim to inspect assertions, evidence stance, entity links, provenance, and review history.</p>
      </div>
    `;
  }
  const activeTab = ['review', 'assertions', 'evidence', 'entities', 'provenance', 'history'].includes(state.claimPreviewTab) ? state.claimPreviewTab : 'review';
  const tab = (id, label) => `<button class="${activeTab === id ? 'active' : ''}" type="button" data-claim-preview-tab="${id}">${label}</button>`;
  const sectionClass = (id) => `claim-preview-section ${activeTab === id ? 'active' : ''}`;
  const assertions = preview.assertions || [];
  const evidence = preview.evidence || [];
  const facts = preview.facts || [];
  const entities = preview.entities || [];
  const events = preview.events || [];
  const qualifier = row.qualifier && typeof row.qualifier === 'object' ? JSON.stringify(row.qualifier) : (row.qualifier || '');
  return `
    <div class="claim-preview-head">
      <span class="source-glyph">${escapeHtml(claimGlyph(row))}</span>
      <div>
        <h2>${escapeHtml(row.subject || 'Claim')}</h2>
        <p>${escapeHtml([row.property, row.review_state, row.contradiction_state].filter(Boolean).join(' · '))}</p>
      </div>
    </div>
    <nav class="claim-preview-tabs" aria-label="Claim preview sections">
      ${tab('review', 'Review')}
      ${tab('assertions', 'Assertions')}
      ${tab('evidence', 'Evidence')}
      ${tab('entities', 'Entities')}
      ${tab('provenance', 'Provenance')}
      ${tab('history', 'History')}
    </nav>
    <section class="${sectionClass('review')}" data-claim-preview-section="review">
      <div class="claim-layer-stack">
        <div><span>Claim language</span><strong>${escapeHtml(row.claim_text || row.value || '')}</strong></div>
        <div><span>Structured proposition</span><strong>${escapeHtml(row.subject || '')} -> ${escapeHtml(row.property || '')} -> ${escapeHtml(row.value || '')}</strong></div>
        <div><span>Qualifiers</span><strong>${escapeHtml(qualifier || 'No qualifiers recorded')}</strong></div>
        <div><span>Scope boundary</span><strong>Accepting this claim selects a reviewed assertion for the current scope. It does not mutate source evidence or delete conflicting assertions.</strong></div>
      </div>
      <div class="tag-line">
        <span class="pill">${escapeHtml(row.review_state || 'draft')}</span>
        <span class="pill">${escapeHtml(row.contradiction_state || 'contextual')}</span>
        <span class="pill">${escapeHtml(row.source_diversity || 0)} source${Number(row.source_diversity || 0) === 1 ? '' : 's'}</span>
        ${row.publication_blockers ? `<span class="pill warn">${escapeHtml(row.publication_blockers)} publication blocker${Number(row.publication_blockers) === 1 ? '' : 's'}</span>` : '<span class="pill ok">draft eligible</span>'}
      </div>
      <label class="preview-note">Decision note
        <input id="claimDecisionNote" placeholder="Optional rationale, qualifier change, conflict note, or publication blocker">
      </label>
    </section>
    <section class="${sectionClass('assertions')}" data-claim-preview-section="assertions">
      <article class="claim-preview-card">
        <h4>Grouped assertions (${assertions.length})</h4>
        ${assertions.map((item) => `
          <p><strong>${escapeHtml(item.claim_text || '')}</strong><br>${escapeHtml([item.claim_type, item.evidence_relation, item.status].filter(Boolean).join(' · '))}</p>
        `).join('') || '<p class="muted">No grouped assertions found.</p>'}
      </article>
      <div class="claim-warning">Review state and contradiction state are independent. A reviewed claim can still be disputed if contrary evidence exists.</div>
    </section>
    <section class="${sectionClass('evidence')}" data-claim-preview-section="evidence">
      <article class="claim-preview-card">
        <h4>Evidence stance</h4>
        <p><strong>${escapeHtml(row.support_count || 0)} supporting</strong> · ${escapeHtml(row.refute_count || 0)} refuting · ${escapeHtml(row.context_count || 0)} contextual</p>
        ${evidence.map((item) => `<p><strong>${escapeHtml(item.selection_kind || 'selection')}</strong> · ${escapeHtml(item.status || '')}<br>${escapeHtml(item.quote || item.selection_id || '')}</p>`).join('') || '<p class="muted">No explicit evidence selections linked to this source.</p>'}
      </article>
      <article class="claim-preview-card">
        <h4>Proposed facts (${facts.length})</h4>
        ${facts.map((item) => `<p><strong>${escapeHtml(item.fact_type || item.field_path || '')}</strong> · ${escapeHtml(item.status || '')}<br>${escapeHtml(item.normalized_value || item.raw_value || '')}</p>`).join('') || '<p class="muted">No proposed facts linked to this source.</p>'}
      </article>
    </section>
    <section class="${sectionClass('entities')}" data-claim-preview-section="entities">
      <article class="claim-preview-card">
        <h4>Linked entities (${entities.length})</h4>
        ${entities.map((item) => `<p><strong>${escapeHtml(item.canonical_name || item.mention_text || '')}</strong> · ${escapeHtml(item.entity_type || '')} · ${escapeHtml(item.status || '')}</p>`).join('') || '<p class="muted">No entity links attached to this claim source.</p>'}
      </article>
    </section>
    <section class="${sectionClass('provenance')}" data-claim-preview-section="provenance">
      <div class="claim-provenance-stack">
        ${(preview.provenance || []).map((step, index) => `
          <article>
            <span>${String(index + 1).padStart(2, '0')}</span>
            <div><strong>${escapeHtml(step.label)}</strong><p>${escapeHtml(step.value)}</p>${step.meta ? `<em>${escapeHtml(step.meta)}</em>` : ''}</div>
          </article>
        `).join('')}
      </div>
      ${preview.source?.canonical_url ? `<p><a href="${escapeHtml(safeUrl(preview.source.canonical_url))}" target="_blank" rel="noreferrer">${escapeHtml(preview.source.canonical_url)}</a></p>` : ''}
    </section>
    <section class="${sectionClass('history')}" data-claim-preview-section="history">
      <article class="claim-preview-card">
        <h4>Review history (${events.length})</h4>
        ${events.map((item) => `<p><strong>${escapeHtml(item.event_type || '')}</strong><br>${escapeHtml(fmtDate(item.created_at))} · ${escapeHtml(item.actor || '')}</p>`).join('') || '<p class="muted">No review events recorded for this claim yet.</p>'}
      </article>
    </section>
    <div id="claimActionStatus" class="review-status muted"></div>
    <div class="claim-preview-actions">
      <button class="secondary" data-claim-action="defer">Defer</button>
      <button class="secondary" data-claim-action="reject">Reject</button>
      <button class="secondary" data-claim-action="dispute">Dispute</button>
      <button class="secondary" data-claim-action="revise">Revise</button>
      <button class="secondary" data-claim-action="edit_assertion">Edit assertion</button>
      <button class="secondary" data-claim-action="edit_qualifiers">Edit qualifiers</button>
      <button class="secondary" data-claim-action="select_preferred_assertion">Select preferred</button>
      <button class="secondary" data-claim-action="link_evidence">Link evidence</button>
      <button class="secondary" data-claim-action="unlink_evidence">Unlink evidence</button>
      <button class="secondary" data-claim-action="change_stance">Change stance</button>
      <button class="secondary" data-claim-action="merge">Merge</button>
      <button class="secondary" data-claim-action="split">Split</button>
      <button class="secondary" data-claim-action="assign_review">Assign</button>
      <button class="secondary" data-claim-action="taxonomy">Label</button>
      <button class="secondary" data-claim-action="link_related">Related</button>
      <button class="secondary" data-claim-action="add_to_draft">Add to draft</button>
      <button class="secondary" data-claim-action="open_source">Open source</button>
      <button data-claim-action="accept">Accept & next</button>
    </div>
  `;
}

function renderClaimsPage(data) {
  const rows = data.rows || data.results?.rows || [];
  state.claimRows = rows;
  if (!state.claimSelectedId || !rows.some((row) => claimRowKey(row) === state.claimSelectedId)) {
    state.claimSelectedId = data.selection?.selected_id || (rows[0] ? claimRowKey(rows[0]) : '');
  }
  const summary = data.summary || {};
  const facets = data.facets || {};
  const selectedId = state.claimSelectedId;
  $('routePage').innerHTML = `
    ${pageHeader('Claims Ledger', 'Review structured propositions, competing assertions, support/refute evidence, and publication blockers without mutating captured evidence.')}
    ${metricCards([
      { label: 'Visible claims', value: summary.visible ?? rows.length },
      { label: 'Accepted', value: summary.accepted ?? 0 },
      { label: 'Disputed', value: summary.disputed ?? 0 },
      { label: 'Conflict clusters', value: summary.conflicts ?? 0 },
      { label: 'Publication blockers', value: summary.publication_blockers ?? 0 },
    ])}
    <section class="claim-shell">
      <aside class="panel claim-filter-panel">
        ${claimQueueGroup(facets.queues)}
        ${claimFacetGroup('Claim type', facets.claim_types, state.claimType, 'claim_type')}
        ${claimFacetGroup('Review state', facets.review_states, state.claimReviewState, 'review_state')}
        ${claimFacetGroup('Contradiction state', facets.contradiction_states, state.claimContradictionState, 'contradiction_state')}
        ${claimFacetGroup('Source kind', facets.source_kinds, state.claimSourceKind, 'source_kind')}
      </aside>
      <section class="panel claim-ledger-panel">
        <div class="claim-search-strip">
          <label><span>Claim search</span><input id="claimSearchInput" value="${escapeHtml(state.q)}" placeholder="Search claim language, subject, value, source, account, or URL"></label>
          <button class="secondary" id="claimClearFilters">Clear</button>
        </div>
        <div class="claim-explanation">
          <span class="status-badge info">${escapeHtml(titleCase(state.claimQueue || 'all'))}</span>
          <p>Rows represent reviewed claims, proposed assertions, conflict clusters, duplicates, and superseded claims.</p>
        </div>
        <div class="claim-bulk-toolbar">
          <label><input type="checkbox" id="claimSelectAll"> Select visible</label>
          ${['accept', 'dispute', 'reject', 'defer', 'revise', 'select_preferred_assertion', 'merge', 'split', 'add_to_draft'].map((action) => `<button class="secondary" data-claim-bulk-action="${action}">${escapeHtml(titleCase(action))}</button>`).join('')}
          <span id="claimBulkStatus" class="muted"></span>
        </div>
        <div class="claim-results-list">
          ${rows.length ? rows.map((row) => {
            const rowKey = claimRowKey(row);
            const selected = rowKey === selectedId;
            return `
              <article class="claim-row ${selected ? 'active' : ''}" data-claim-row-id="${escapeHtml(rowKey)}" data-source-id="${escapeHtml(row.source_evidence_id || row.evidence_id || '')}" data-object-type="${escapeHtml(row.object_type || '')}">
                <input class="claim-check" type="checkbox" aria-label="Select claim row" ${state.claimSelectedIds.has(rowKey) ? 'checked' : ''}>
                <span class="source-glyph">${escapeHtml(claimGlyph(row))}</span>
                <div class="claim-row-main">
                  <div class="claim-title-line">
                    <strong>${escapeHtml(row.claim_text || row.value || 'Untitled claim')}</strong>
                    ${row.row_kind === 'conflict_cluster' ? '<span class="pill warn">conflict</span>' : ''}
                    ${row.row_kind === 'duplicate_cluster' ? '<span class="pill warn">duplicate</span>' : ''}
                  </div>
                  <p>${escapeHtml(`${row.subject || 'Subject'} -> ${row.property || 'property'} -> ${row.value || ''}`)}</p>
                  <div class="row-meta">
                    <span class="pill">${escapeHtml(titleCase(row.row_kind || 'claim'))}</span>
                    <span class="pill">${escapeHtml(row.claim_type || 'general')}</span>
                    <span class="pill">${escapeHtml(row.review_state || 'draft')}</span>
                    <span class="pill">${escapeHtml(row.contradiction_state || 'contextual')}</span>
                    ${row.source_label ? `<span class="pill">${escapeHtml(row.source_label)}</span>` : ''}
                    ${row.author_handle ? `<span class="pill">@${escapeHtml(row.author_handle)}</span>` : ''}
                    ${row.domain ? `<span class="pill">${escapeHtml(row.domain)}</span>` : ''}
                  </div>
                </div>
                <div class="claim-row-counts">
                  <strong>${escapeHtml(row.support_count || 0)}</strong><em>support</em>
                  <strong>${escapeHtml(row.refute_count || 0)}</strong><em>refute</em>
                  <strong>${escapeHtml(row.source_diversity || 0)}</strong><em>sources</em>
                  <strong>${escapeHtml(row.publication_blockers || 0)}</strong><em>blockers</em>
                </div>
              </article>
            `;
          }).join('') : '<div class="empty-state"><h2>No claim rows</h2><p>Try another queue or filter.</p></div>'}
        </div>
      </section>
      <aside class="panel claim-preview-panel">
        ${renderClaimPreview(data)}
      </aside>
    </section>
  `;
  bindClaimPage(data);
}

function claimStatusForAction(row, action) {
  if (action === 'accept') return 'accepted';
  if (action === 'dispute') return 'disputed';
  if (action === 'reject') return 'rejected';
  if (action === 'defer') return 'under_review';
  if (action === 'revise') return 'under_review';
  if (action === 'merge') return 'superseded';
  return row.review_state || 'under_review';
}

function claimEventTypeForAction(action) {
  return {
    accept: 'claim.accepted',
    dispute: 'claim.disputed',
    reject: 'claim.rejected',
    defer: 'claim.deferred',
    revise: 'claim.revision.requested',
    edit_assertion: 'claim.assertion_edit.requested',
    edit_qualifiers: 'claim.qualifier_edit.requested',
    select_preferred_assertion: 'claim.preferred_assertion.selected',
    link_evidence: 'claim.evidence_link.requested',
    unlink_evidence: 'claim.evidence_unlink.requested',
    change_stance: 'claim.evidence_stance_change.requested',
    merge: 'claim.merge.requested',
    split: 'claim.split.requested',
    assign_review: 'claim.assignment.recorded',
    taxonomy: 'claim.taxonomy_label.requested',
    link_related: 'claim.related_link.requested',
    add_to_draft: 'claim.publication_draft_add.requested',
    open_source: 'claim.source_opened',
  }[action] || 'claim.action.recorded';
}

function claimAnchorForRow(row, action) {
  return {
    kind: 'claims_ledger_row',
    claim_row_id: claimRowKey(row),
    source_evidence_id: row.source_evidence_id || row.evidence_id || '',
    object_type: row.object_type || '',
    object_id: row.object_id || '',
    claim_type: row.claim_type || '',
    subject: row.subject || '',
    property: row.property || '',
    value: row.value || '',
    action,
  };
}

async function persistClaimAction(row, action, note = '') {
  if (!row) return;
  if (action === 'open_source') {
    const sourceId = row.source_evidence_id || row.evidence_id || '';
    if (sourceId) await selectSource(sourceId);
    return;
  }
  if (row.object_type === 'claim_stub' && row.object_id && ['accept', 'dispute', 'reject', 'defer', 'revise'].includes(action)) {
    await postJson('/api/review-state', {
      source_evidence_id: row.source_evidence_id || row.evidence_id || '',
      source_project: row.source_project || '',
      project: row.source_project || state.project || '',
      subject_type: 'claim_stub',
      subject_id: row.object_id,
      actor: REVIEW_UI_ACTOR,
      expected_version: expectedVersionForRow(row),
      status: claimStatusForAction(row, action),
      note,
      source_anchor: claimAnchorForRow(row, action),
      idempotency_key: idempotencyKey(claimRowKey(row), action, row.review_state || row.status || ''),
    });
    return;
  }
  await postJson('/api/review/events', {
    event_type: claimEventTypeForAction(action),
    source_evidence_id: row.source_evidence_id || row.evidence_id || '',
    source_project: row.source_project || '',
    project: row.source_project || state.project || '',
    subject_type: row.object_type || row.row_kind || 'claim',
    subject_id: row.object_id || claimRowKey(row),
    action,
    status: claimStatusForAction(row, action),
    note,
    source_anchor: claimAnchorForRow(row, action),
    idempotency_key: idempotencyKey(claimRowKey(row), action, row.review_state || row.status || ''),
  });
}

function nextClaimSelectionAfter(row) {
  const rows = state.claimRows || [];
  const index = rows.findIndex((item) => claimRowKey(item) === claimRowKey(row));
  const next = rows[index + 1] || rows[index - 1] || null;
  return next ? claimRowKey(next) : '';
}

async function applyClaimAction(row, action) {
  const status = $('claimActionStatus') || $('claimBulkStatus');
  const note = $('claimDecisionNote')?.value || '';
  if (!row) {
    if (status) status.textContent = 'Select a claim row first.';
    return;
  }
  if (status) status.textContent = `${titleCase(action)}...`;
  await persistClaimAction(row, action, note);
  if (['accept', 'dispute', 'reject', 'defer'].includes(action)) {
    state.claimSelectedId = nextClaimSelectionAfter(row);
  }
  state.claimSelectedIds.clear();
  if (status) status.textContent = `${titleCase(action)} recorded.`;
  replaceRouteHash();
  await loadRoutePage();
}

async function applyBulkClaimAction(action) {
  const status = $('claimBulkStatus');
  const selectedIds = Array.from(document.querySelectorAll('.claim-row .claim-check:checked'))
    .map((checkbox) => checkbox.closest('.claim-row')?.dataset.claimRowId)
    .filter(Boolean);
  const selectedRows = state.claimRows.filter((row) => selectedIds.includes(claimRowKey(row)));
  if (!selectedRows.length) {
    if (status) status.textContent = 'Select at least one claim row.';
    return;
  }
  if (status) status.textContent = `${titleCase(action)} ${selectedRows.length} claim row${selectedRows.length === 1 ? '' : 's'}...`;
  for (const row of selectedRows) {
    await persistClaimAction(row, action, `Bulk ${titleCase(action)} from Claims Ledger`);
  }
  state.claimSelectedIds.clear();
  if (status) status.textContent = `${titleCase(action)} recorded for ${selectedRows.length}.`;
  await loadRoutePage();
}

function moveClaimSelection(delta) {
  if (state.route !== 'claims') return;
  const rows = state.claimRows || [];
  if (!rows.length) return;
  const current = rows.findIndex((row) => claimRowKey(row) === state.claimSelectedId);
  const nextIndex = Math.max(0, Math.min(rows.length - 1, (current >= 0 ? current : 0) + delta));
  state.claimSelectedId = claimRowKey(rows[nextIndex]);
  replaceRouteHash();
  loadRoutePage();
}

function bindClaimKeyboard() {
  if (window.__webOsintClaimKeyboardBound) return;
  window.__webOsintClaimKeyboardBound = true;
  window.addEventListener('keydown', async (event) => {
    if (state.route !== 'claims') return;
    const active = document.activeElement;
    if (active && ['INPUT', 'TEXTAREA', 'SELECT', 'BUTTON'].includes(active.tagName)) return;
    const key = event.key.toLowerCase();
    if (key === 'j') {
      event.preventDefault();
      moveClaimSelection(1);
    } else if (key === 'k') {
      event.preventDefault();
      moveClaimSelection(-1);
    } else if (['a', 'u', 'r', 'd', 'e', 'o'].includes(key)) {
      event.preventDefault();
      const row = state.claimRows.find((item) => claimRowKey(item) === state.claimSelectedId);
      const action = key === 'a' ? 'accept' : key === 'u' ? 'dispute' : key === 'r' ? 'reject' : key === 'd' ? 'defer' : key === 'e' ? 'edit_assertion' : 'open_source';
      try {
        await applyClaimAction(row, action);
      } catch (error) {
        const status = $('claimActionStatus') || $('claimBulkStatus');
        if (status) status.textContent = error.message;
      }
    }
  });
}

function bindClaimPage(data) {
  document.querySelectorAll('[data-claim-queue]').forEach((button) => {
    button.addEventListener('click', () => {
      state.claimQueue = button.dataset.claimQueue || 'all';
      state.claimSelectedId = '';
      replaceRouteHash();
      loadRoutePage();
    });
  });
  document.querySelectorAll('[data-claim-filter]').forEach((button) => {
    button.addEventListener('click', () => {
      const filter = button.dataset.claimFilter;
      const value = button.dataset.filterValue || '';
      if (filter === 'claim_type') state.claimType = value;
      if (filter === 'review_state') state.claimReviewState = value;
      if (filter === 'contradiction_state') state.claimContradictionState = value;
      if (filter === 'source_kind') state.claimSourceKind = value;
      state.claimSelectedId = '';
      replaceRouteHash();
      loadRoutePage();
    });
  });
  $('claimSearchInput')?.addEventListener('input', () => {
    state.q = $('claimSearchInput').value.trim();
    clearTimeout(window.__claimSearchTimer);
    window.__claimSearchTimer = setTimeout(() => {
      state.claimSelectedId = '';
      replaceRouteHash();
      loadRoutePage();
    }, 250);
  });
  $('claimClearFilters')?.addEventListener('click', () => {
    state.q = '';
    state.project = '';
    state.claimQueue = 'all';
    state.claimType = '';
    state.claimReviewState = '';
    state.claimContradictionState = '';
    state.claimSourceKind = '';
    state.claimSelectedId = '';
    state.claimSelectedIds.clear();
    replaceRouteHash();
    loadRoutePage();
  });
  $('claimSelectAll')?.addEventListener('change', () => {
    const checked = $('claimSelectAll').checked;
    state.claimSelectedIds.clear();
    document.querySelectorAll('.claim-row').forEach((row) => {
      const id = row.dataset.claimRowId || '';
      const checkbox = row.querySelector('.claim-check');
      if (checkbox) checkbox.checked = checked;
      if (checked && id) state.claimSelectedIds.add(id);
    });
  });
  document.querySelectorAll('.claim-row').forEach((row) => {
    row.addEventListener('click', () => {
      state.claimSelectedId = row.dataset.claimRowId || '';
      replaceRouteHash();
      loadRoutePage();
    });
    row.addEventListener('dblclick', async () => {
      if (row.dataset.sourceId) await selectSource(row.dataset.sourceId);
    });
    row.querySelector('.claim-check')?.addEventListener('click', (event) => {
      event.stopPropagation();
      const id = row.dataset.claimRowId || '';
      if (!id) return;
      if (event.currentTarget.checked) state.claimSelectedIds.add(id);
      else state.claimSelectedIds.delete(id);
    });
  });
  document.querySelectorAll('[data-claim-preview-tab]').forEach((button) => {
    button.addEventListener('click', () => {
      state.claimPreviewTab = button.dataset.claimPreviewTab || 'review';
      document.querySelectorAll('[data-claim-preview-tab]').forEach((tab) => tab.classList.toggle('active', tab === button));
      document.querySelectorAll('[data-claim-preview-section]').forEach((section) => {
        section.classList.toggle('active', section.dataset.claimPreviewSection === state.claimPreviewTab);
      });
    });
  });
  document.querySelectorAll('[data-claim-action]').forEach((button) => {
    button.addEventListener('click', async () => {
      const row = (data.rows || []).find((item) => claimRowKey(item) === state.claimSelectedId) || data.preview?.row;
      try {
        await applyClaimAction(row, button.dataset.claimAction || 'defer');
      } catch (error) {
        const status = $('claimActionStatus');
        if (status) status.textContent = error.message;
      }
    });
  });
  document.querySelectorAll('[data-claim-bulk-action]').forEach((button) => {
    button.addEventListener('click', async () => {
      try {
        await applyBulkClaimAction(button.dataset.claimBulkAction || 'defer');
      } catch (error) {
        const status = $('claimBulkStatus');
        if (status) status.textContent = error.message;
      }
    });
  });
  bindClaimKeyboard();
}

function reviewTaskKey(row) {
  return row.task_id || [row.object_type, row.object_id].filter(Boolean).join(':');
}

function reviewGlyph(row) {
  const type = row.object_type || '';
  const stateValue = row.decision_state || '';
  if (stateValue === 'blocked') return '!';
  if (stateValue === 'approved') return 'A';
  if (stateValue === 'rejected') return 'R';
  if (type.includes('claim')) return 'C';
  if (type.includes('entity')) return 'E';
  if (type.includes('fact')) return 'F';
  if (type.includes('publication')) return 'P';
  return 'V';
}

function reviewQueueGroup(items) {
  const queues = items || [];
  return `
    <section class="review-facet-group">
      <h3>Formal queues</h3>
      <div class="facet-list compact">
        ${queues.map((item) => `
          <button class="facet ${state.reviewQueue === item.id ? 'active' : ''}" type="button" data-review-queue="${escapeHtml(item.id)}">
            <span>${escapeHtml(item.label || item.id)}</span><strong>${escapeHtml(item.count || 0)}</strong>
          </button>
        `).join('')}
      </div>
    </section>
  `;
}

function reviewFacetGroup(title, items, activeValue, filterName) {
  const options = items || [];
  return `
    <section class="review-facet-group">
      <h3>${escapeHtml(title)}</h3>
      <button class="facet ${activeValue ? '' : 'active'}" type="button" data-review-filter="${escapeHtml(filterName)}" data-filter-value="">
        <span>All ${escapeHtml(title.toLowerCase())}</span><strong>${escapeHtml(options.reduce((sum, item) => sum + Number(item.count || 0), 0))}</strong>
      </button>
      <div class="facet-list compact">
        ${options.map((item) => `
          <button class="facet ${activeValue === item.id ? 'active' : ''}" type="button" data-review-filter="${escapeHtml(filterName)}" data-filter-value="${escapeHtml(item.id)}">
            <span>${escapeHtml(item.label || item.id)}</span><strong>${escapeHtml(item.count || 0)}</strong>
          </button>
        `).join('')}
      </div>
    </section>
  `;
}

function renderReviewPreview(data) {
  const preview = data.preview || {};
  const row = preview.row || null;
  if (!row) {
    return `
      <div class="empty-state">
        <h2>Decision Panel</h2>
        <p>Select a review task to inspect object boundaries, exact source anchors, proposed changes, provenance, and durable history.</p>
      </div>
    `;
  }
  const activeTab = ['review', 'source', 'proposed', 'provenance', 'history'].includes(state.reviewPreviewTab) ? state.reviewPreviewTab : 'review';
  const tab = (id, label) => `<button class="${activeTab === id ? 'active' : ''}" type="button" data-review-preview-tab="${id}">${label}</button>`;
  const sectionClass = (id) => `review-preview-section ${activeTab === id ? 'active' : ''}`;
  const proposed = preview.proposed_change || {};
  return `
    <div class="review-preview-head">
      <span class="source-glyph">${escapeHtml(reviewGlyph(row))}</span>
      <div>
        <h2>${escapeHtml(row.object_kind || row.object_type || 'Review task')}</h2>
        <p>${escapeHtml([row.decision_state, row.priority, row.epistemic_layer].filter(Boolean).join(' · '))}</p>
      </div>
    </div>
    <nav class="review-preview-tabs" aria-label="Review preview sections">
      ${tab('review', 'Review')}
      ${tab('source', 'Source')}
      ${tab('proposed', 'Proposed change')}
      ${tab('provenance', 'Provenance')}
      ${tab('history', 'History')}
    </nav>
    <section class="${sectionClass('review')}" data-review-preview-section="review">
      <div class="review-layer-stack">
        <div><span>Decision scope</span><strong>${escapeHtml(row.object_type || '')} / ${escapeHtml(row.object_id || '')}</strong></div>
        <div><span>Object version</span><strong>${escapeHtml(row.object_version || '')}</strong></div>
        <div><span>Boundary</span><strong>Approving this task decides only this object version. Linked evidence, facts, claims, and publication snapshots remain separately reviewable.</strong></div>
        <div><span>Publication impact</span><strong>${escapeHtml(row.publication_impact || '')}</strong></div>
      </div>
      <article class="review-preview-card">
        <h4>Checklist</h4>
        ${(preview.checklist || []).map((item) => `<p><strong>${escapeHtml(item.label || '')}</strong><br>${escapeHtml(item.detail || item.state || '')}</p>`).join('')}
      </article>
      <label class="preview-note">Reviewer comment
        <input id="reviewDecisionNote" placeholder="Reason, blocker, requested change, or source-anchor concern">
      </label>
    </section>
    <section class="${sectionClass('source')}" data-review-preview-section="source">
      <article class="review-preview-card">
        <h4>Immutable source and anchor</h4>
        ${(preview.artifact_manifest || []).map((item) => `<p><strong>${escapeHtml(item.label || '')}</strong><br>${escapeHtml(item.value || '')}${item.meta ? `<br><em>${escapeHtml(item.meta)}</em>` : ''}</p>`).join('')}
      </article>
      ${preview.source?.canonical_url ? `<p><a href="${escapeHtml(safeUrl(preview.source.canonical_url))}" target="_blank" rel="noreferrer">${escapeHtml(preview.source.canonical_url)}</a></p>` : ''}
    </section>
    <section class="${sectionClass('proposed')}" data-review-preview-section="proposed">
      <div class="review-diff-pair">
        <article class="review-preview-card"><h4>Before</h4><p>${escapeHtml(proposed.before || '')}</p></article>
        <article class="review-preview-card"><h4>After</h4><p>${escapeHtml(proposed.after || '')}</p></article>
      </div>
      <article class="review-preview-card">
        <h4>Proposal text</h4>
        <p>${escapeHtml(proposed.proposal || row.object_text || '')}</p>
      </article>
      <article class="review-preview-card">
        <h4>Adjacent objects not decided here</h4>
        ${(preview.adjacent_objects || []).map((item) => `<p><strong>${escapeHtml(item.label || '')}</strong><br>${escapeHtml(item.detail || '')}</p>`).join('')}
      </article>
    </section>
    <section class="${sectionClass('provenance')}" data-review-preview-section="provenance">
      <div class="review-provenance-stack">
        ${(preview.provenance || []).map((step, index) => `
          <article>
            <span>${String(index + 1).padStart(2, '0')}</span>
            <div><strong>${escapeHtml(step.label)}</strong><p>${escapeHtml(step.value)}</p>${step.meta ? `<em>${escapeHtml(step.meta)}</em>` : ''}</div>
          </article>
        `).join('')}
      </div>
    </section>
    <section class="${sectionClass('history')}" data-review-preview-section="history">
      <article class="review-preview-card">
        <h4>Durable review events (${(preview.history || []).length})</h4>
        ${(preview.history || []).map((item) => `<p><strong>${escapeHtml(item.event_type || '')}</strong><br>${escapeHtml(fmtDate(item.created_at))} · ${escapeHtml(item.actor || '')}</p>`).join('') || '<p class="muted">No review-event history for this object yet.</p>'}
      </article>
    </section>
    <div id="reviewActionStatus" class="review-status muted"></div>
    <div class="review-preview-actions">
      <button class="secondary" data-review-action="defer">Defer</button>
      <button class="secondary" data-review-action="reject">Reject</button>
      <button class="secondary" data-review-action="request_changes">Request changes</button>
      <button class="secondary" data-review-action="assign">Assign</button>
      <button class="secondary" data-review-action="edit_proposal">Edit proposal</button>
      <button class="secondary" data-review-action="history">History</button>
      <button class="secondary" data-review-action="reopen">Reopen</button>
      <button class="secondary" data-review-action="open_source">Open source</button>
      <button data-review-action="approve">Approve & next</button>
    </div>
  `;
}

function renderReviewsPage(data) {
  const rows = data.rows || data.results?.rows || [];
  state.reviewRows = rows;
  if (!state.reviewSelectedId || !rows.some((row) => reviewTaskKey(row) === state.reviewSelectedId)) {
    state.reviewSelectedId = data.selection?.selected_task_id || (rows[0] ? reviewTaskKey(rows[0]) : '');
  }
  const summary = data.summary || {};
  const facets = data.facets || {};
  const selectedId = state.reviewSelectedId;
  const queueLabel = (data.queues || []).find((queue) => queue.id === state.reviewQueue)?.label || titleCase(state.reviewQueue || 'all');
  $('routePage').innerHTML = `
    <header class="page-header trace-page-header">
      <div>
        <span class="breadcrumb">Research UI / Formal reviews</span>
        <div class="title-action-group">
          <span class="status-badge ok">durable human decisions</span>
          <span class="status-badge danger">${escapeHtml(summary.blockers ?? 0)} publication blockers</span>
        </div>
        <h1>Reviews</h1>
        <p>Make accountable decisions across source evidence, derived observations, curated assertions, and frozen publication snapshots.</p>
      </div>
      <div class="page-actions">
        <button class="secondary" data-review-action-shortcut="history">Decision history</button>
        <button class="secondary" data-review-action-shortcut="create_queue">Create queue</button>
        <button data-review-bulk-action="approve">Review assigned</button>
      </div>
    </header>
    <section class="operation-search-card">
      <label class="operation-search">
        <span class="sr-only">Review search</span>
        <input id="reviewSearchInput" value="${escapeHtml(state.q)}" placeholder="Search review tasks, source anchors, proposed changes, claims, facts, blockers">
      </label>
      <div class="operation-search-controls">
        <div class="segmented-control" aria-label="Review search mode">
          <button class="secondary" type="button">Exact</button>
          <button class="secondary" type="button">Semantic</button>
          <button class="active" type="button">Hybrid</button>
        </div>
        <select id="reviewScopeSelect" aria-label="Review scope">
          <option value="">Scope: All projects</option>
          ${state.project ? `<option value="${escapeHtml(state.project)}" selected>Project: ${escapeHtml(state.project)}</option>` : ''}
        </select>
        <button id="reviewSearchButton" type="button">Search</button>
        <button class="secondary compact-clear" id="reviewClearFilters" type="button">Clear</button>
      </div>
      <div class="operation-search-meta">
        <span class="status-badge info">Human review only</span>
        <p>Hybrid match: task fields plus exact source anchors, proposed changes, linked claims, entities, reviewer comments, and prior decisions.</p>
        <strong>${escapeHtml(summary.open ?? 0)} waiting · ${escapeHtml(summary.blockers ?? 0)} blocking · ${escapeHtml(summary.visible ?? rows.length)} visible</strong>
      </div>
    </section>
    <section class="review-shell trace-workbench">
      <aside class="panel review-filter-panel">
        ${reviewQueueGroup(data.queues)}
        ${reviewFacetGroup('Object type', facets.object_types, state.reviewType, 'type')}
        ${reviewFacetGroup('Decision state', facets.decision_states, state.reviewDecisionState, 'decision_state')}
        ${reviewFacetGroup('Priority', facets.priorities, state.reviewPriority, 'priority')}
        ${reviewFacetGroup('Epistemic layer', facets.epistemic_layers, state.reviewLayer, 'layer')}
      </aside>
      <section class="panel review-ledger-panel">
        <div class="review-explanation">
          <span class="status-badge info">${escapeHtml(queueLabel)}</span>
          <p>Tasks are formal decisions. Inbox triage stays separate; save-and-next advances only after the durable event succeeds.</p>
        </div>
        <div class="review-bulk-toolbar">
          <label><input type="checkbox" id="reviewSelectAll"> Select visible</label>
          ${['approve', 'reject', 'request_changes', 'defer', 'assign'].map((action) => `<button class="secondary" data-review-bulk-action="${action}">${escapeHtml(titleCase(action))}</button>`).join('')}
          <span id="reviewBulkStatus" class="muted"></span>
        </div>
        <div class="review-results-list">
          ${rows.length ? rows.map((row) => {
            const rowKey = reviewTaskKey(row);
            const selected = rowKey === selectedId;
            return `
              <article class="review-row ${selected ? 'active' : ''}" data-review-task-id="${escapeHtml(rowKey)}" data-source-id="${escapeHtml(row.source_evidence_id || row.evidence_id || '')}" data-object-type="${escapeHtml(row.object_type || '')}">
                <input class="review-check" type="checkbox" aria-label="Select review task" ${state.reviewSelectedIds.has(rowKey) ? 'checked' : ''}>
                <span class="source-glyph">${escapeHtml(reviewGlyph(row))}</span>
                <div class="review-row-main">
                  <div class="review-title-line">
                    <strong>${escapeHtml(row.object_text || row.object_kind || row.object_type || 'Review task')}</strong>
                    ${row.blocker_count ? `<span class="pill warn">${escapeHtml(row.blocker_count)} blocker${Number(row.blocker_count) === 1 ? '' : 's'}</span>` : ''}
                  </div>
                  <p>${escapeHtml(row.source_anchor_summary || row.review_reason || '')}</p>
                  <div class="row-meta">
                    <span class="pill">${escapeHtml(row.object_type || 'object')}</span>
                    <span class="pill">${escapeHtml(row.decision_state || 'open')}</span>
                    <span class="pill">${escapeHtml(row.priority || 'normal')}</span>
                    <span class="pill">${escapeHtml(row.epistemic_layer || 'layer')}</span>
                    ${row.assignee ? `<span class="pill">${escapeHtml(row.assignee)}</span>` : ''}
                    ${row.source_label ? `<span class="pill">${escapeHtml(row.source_label)}</span>` : ''}
                    ${row.domain ? `<span class="pill">${escapeHtml(row.domain)}</span>` : ''}
                  </div>
                </div>
                <div class="review-row-state">
                  <span class="status-badge ${Number(row.blocker_count || 0) ? 'danger' : row.decision_state === 'approved' ? 'ok' : 'warn'}">${escapeHtml(titleCase(row.decision_state || 'open'))}</span>
                  <em>${escapeHtml(titleCase(row.priority || 'normal'))} priority</em>
                  <em>${row.assignee ? `Assigned ${escapeHtml(row.assignee)}` : 'Unassigned'}</em>
                  <em>${escapeHtml(fmtDate(row.updated_at || row.created_at) || '')}</em>
                </div>
              </article>
            `;
          }).join('') : '<div class="empty-state"><h2>No review tasks</h2><p>Try another queue or filter.</p></div>'}
        </div>
      </section>
      <aside class="panel review-preview-panel">
        ${renderReviewPreview(data)}
      </aside>
    </section>
  `;
  bindReviewPage(data);
}

// Every UI-initiated mutation carries an explicit human actor (spec §28
// actor union). The Phase 2 machine-origin guard treats model:/worker: prefixes
// as model_run; the UI is always the human surface.
const REVIEW_UI_ACTOR = 'human:web-osint-user';

// Optimistic-concurrency token (spec §31) echoed back to /api/review-state.
// The server compares this to the object's updated_at. Reads from the row's
// optimistic_version first (review-task / publishing rows surface it), then
// falls back to updated_at. Empty string -> no OCC check (server treats absent
// expected_version as optional, so legacy rows still work).
function expectedVersionForRow(row) {
  if (!row) return '';
  return String(row.optimistic_version || row.updated_at || row.version || '');
}

function reviewStatusForAction(row, action) {
  if (action === 'approve') return 'approved';
  if (action === 'reject') return 'rejected';
  if (action === 'request_changes') return 'changes_requested';
  if (action === 'defer') return 'deferred';
  if (action === 'assign') return 'assigned';
  if (action === 'reopen') return 'open';
  return row.decision_state || 'open';
}

function reviewEventTypeForAction(action) {
  return {
    approve: 'review.decision.approved',
    reject: 'review.decision.rejected',
    request_changes: 'review.decision.changes_requested',
    defer: 'review.decision.deferred',
    assign: 'review.assignment.recorded',
    edit_proposal: 'review.proposal_edit.requested',
    open_source: 'review.source_opened',
    reopen: 'review.reopened',
    history: 'review.history.opened',
  }[action] || 'review.action.recorded';
}

function reviewAnchorForRow(row, action) {
  return {
    kind: 'reviews_task_row',
    task_id: reviewTaskKey(row),
    source_evidence_id: row.source_evidence_id || row.evidence_id || '',
    object_type: row.object_type || '',
    object_id: row.object_id || '',
    object_version: row.object_version || '',
    action,
  };
}

async function persistReviewAction(row, action, note = '') {
  if (!row) return;
  if (action === 'open_source') {
    const sourceId = row.source_evidence_id || row.evidence_id || '';
    if (sourceId) await selectSource(sourceId);
    return;
  }
  const supported = ['evidence_selection', 'annotation', 'proposed_fact', 'normalized_correction', 'entity_link', 'claim_stub'].includes(row.object_type || '');
  if (supported && ['approve', 'reject', 'request_changes', 'defer', 'assign', 'reopen'].includes(action)) {
    await postJson('/api/review-state', {
      source_evidence_id: row.source_evidence_id || row.evidence_id || '',
      source_project: row.source_project || '',
      project: row.source_project || state.project || '',
      subject_type: row.object_type || '',
      subject_id: row.object_id || '',
      actor: REVIEW_UI_ACTOR,
      expected_version: expectedVersionForRow(row),
      status: reviewStatusForAction(row, action),
      note,
      source_anchor: reviewAnchorForRow(row, action),
      idempotency_key: idempotencyKey(reviewTaskKey(row), action, row.review_state || row.status || row.decision_state || ''),
    });
    return;
  }
  await postJson('/api/review/events', {
    event_type: reviewEventTypeForAction(action),
    source_evidence_id: row.source_evidence_id || row.evidence_id || '',
    source_project: row.source_project || '',
    project: row.source_project || state.project || '',
    subject_type: row.object_type || 'review_task',
    subject_id: row.object_id || reviewTaskKey(row),
    action,
    status: reviewStatusForAction(row, action),
    note,
    source_anchor: reviewAnchorForRow(row, action),
    idempotency_key: idempotencyKey(reviewTaskKey(row), action, row.review_state || row.status || row.decision_state || ''),
  });
}

function nextReviewSelectionAfter(row) {
  const rows = state.reviewRows || [];
  const index = rows.findIndex((item) => reviewTaskKey(item) === reviewTaskKey(row));
  const next = rows[index + 1] || rows[index - 1] || null;
  return next ? reviewTaskKey(next) : '';
}

async function applyReviewAction(row, action) {
  const status = $('reviewActionStatus') || $('reviewBulkStatus');
  const note = $('reviewDecisionNote')?.value || '';
  if (!row) {
    if (status) status.textContent = 'Select a review task first.';
    return;
  }
  if (action === 'history') {
    state.reviewPreviewTab = 'history';
    replaceRouteHash();
    loadRoutePage();
    return;
  }
  if (status) status.textContent = `${titleCase(action)}...`;
  await persistReviewAction(row, action, note);
  if (['approve', 'reject', 'request_changes', 'defer'].includes(action)) {
    state.reviewSelectedId = nextReviewSelectionAfter(row);
  }
  state.reviewSelectedIds.clear();
  if (status) status.textContent = `${titleCase(action)} recorded.`;
  replaceRouteHash();
  await loadRoutePage();
}

async function applyBulkReviewAction(action) {
  const status = $('reviewBulkStatus');
  const selectedIds = Array.from(document.querySelectorAll('.review-row .review-check:checked'))
    .map((checkbox) => checkbox.closest('.review-row')?.dataset.reviewTaskId)
    .filter(Boolean);
  const selectedRows = state.reviewRows.filter((row) => selectedIds.includes(reviewTaskKey(row)));
  if (!selectedRows.length) {
    if (status) status.textContent = 'Select at least one review task.';
    return;
  }
  if (status) status.textContent = `${titleCase(action)} ${selectedRows.length} review task${selectedRows.length === 1 ? '' : 's'}...`;
  for (const row of selectedRows) {
    await persistReviewAction(row, action, `Bulk ${titleCase(action)} from Reviews`);
  }
  state.reviewSelectedIds.clear();
  if (status) status.textContent = `${titleCase(action)} recorded for ${selectedRows.length}.`;
  await loadRoutePage();
}

function moveReviewSelection(delta) {
  if (state.route !== 'reviews') return;
  const rows = state.reviewRows || [];
  if (!rows.length) return;
  const current = rows.findIndex((row) => reviewTaskKey(row) === state.reviewSelectedId);
  const nextIndex = Math.max(0, Math.min(rows.length - 1, (current >= 0 ? current : 0) + delta));
  state.reviewSelectedId = reviewTaskKey(rows[nextIndex]);
  replaceRouteHash();
  loadRoutePage();
}

function bindReviewKeyboard() {
  if (window.__webOsintReviewKeyboardBound) return;
  window.__webOsintReviewKeyboardBound = true;
  window.addEventListener('keydown', async (event) => {
    if (state.route !== 'reviews') return;
    const active = document.activeElement;
    if (active && ['INPUT', 'TEXTAREA', 'SELECT', 'BUTTON'].includes(active.tagName)) return;
    const key = event.key.toLowerCase();
    if (key === 'j') {
      event.preventDefault();
      moveReviewSelection(1);
    } else if (key === 'k') {
      event.preventDefault();
      moveReviewSelection(-1);
    } else if (['a', 'r', 'x', 'd', 'e', 'o', 'h'].includes(key)) {
      event.preventDefault();
      const row = state.reviewRows.find((item) => reviewTaskKey(item) === state.reviewSelectedId);
      const action = key === 'a' ? 'approve' : key === 'r' ? 'reject' : key === 'x' ? 'request_changes' : key === 'd' ? 'defer' : key === 'e' ? 'edit_proposal' : key === 'o' ? 'open_source' : 'history';
      try {
        await applyReviewAction(row, action);
      } catch (error) {
        const status = $('reviewActionStatus') || $('reviewBulkStatus');
        if (status) status.textContent = error.message;
      }
    }
  });
}

function bindReviewPage(data) {
  document.querySelectorAll('[data-review-queue]').forEach((button) => {
    button.addEventListener('click', () => {
      state.reviewQueue = button.dataset.reviewQueue || 'all';
      state.reviewSelectedId = '';
      replaceRouteHash();
      loadRoutePage();
    });
  });
  document.querySelectorAll('[data-review-filter]').forEach((button) => {
    button.addEventListener('click', () => {
      const filter = button.dataset.reviewFilter;
      const value = button.dataset.filterValue || '';
      if (filter === 'type') state.reviewType = value;
      if (filter === 'decision_state') state.reviewDecisionState = value;
      if (filter === 'priority') state.reviewPriority = value;
      if (filter === 'layer') state.reviewLayer = value;
      state.reviewSelectedId = '';
      replaceRouteHash();
      loadRoutePage();
    });
  });
  $('reviewSearchInput')?.addEventListener('input', () => {
    state.q = $('reviewSearchInput').value.trim();
    clearTimeout(window.__reviewSearchTimer);
    window.__reviewSearchTimer = setTimeout(() => {
      state.reviewSelectedId = '';
      replaceRouteHash();
      loadRoutePage();
    }, 250);
  });
  $('reviewSearchButton')?.addEventListener('click', () => {
    state.q = $('reviewSearchInput')?.value.trim() || '';
    state.reviewSelectedId = '';
    replaceRouteHash();
    loadRoutePage();
  });
  $('reviewScopeSelect')?.addEventListener('change', () => {
    state.project = $('reviewScopeSelect').value || '';
    state.reviewSelectedId = '';
    replaceRouteHash();
    loadRoutePage();
  });
  $('reviewClearFilters')?.addEventListener('click', () => {
    state.q = '';
    state.project = '';
    state.reviewQueue = 'all';
    state.reviewType = '';
    state.reviewDecisionState = '';
    state.reviewPriority = '';
    state.reviewLayer = '';
    state.reviewSelectedId = '';
    state.reviewSelectedIds.clear();
    replaceRouteHash();
    loadRoutePage();
  });
  document.querySelectorAll('[data-review-action-shortcut]').forEach((button) => {
    button.addEventListener('click', async () => {
      const row = state.reviewRows.find((item) => reviewTaskKey(item) === state.reviewSelectedId) || state.reviewRows[0];
      const action = button.dataset.reviewActionShortcut || 'history';
      const status = $('reviewBulkStatus');
      if (action === 'history') {
        state.reviewPreviewTab = 'history';
        replaceRouteHash();
        loadRoutePage();
        return;
      }
      if (status) status.textContent = `${button.textContent.trim()} is queued for a later workflow cut.`;
      if (row) {
        await persistReviewAction(row, 'history', `${button.textContent.trim()} opened from Reviews header.`);
      }
    });
  });
  $('reviewSelectAll')?.addEventListener('change', () => {
    const checked = $('reviewSelectAll').checked;
    state.reviewSelectedIds.clear();
    document.querySelectorAll('.review-row').forEach((row) => {
      const id = row.dataset.reviewTaskId || '';
      const checkbox = row.querySelector('.review-check');
      if (checkbox) checkbox.checked = checked;
      if (checked && id) state.reviewSelectedIds.add(id);
    });
  });
  document.querySelectorAll('.review-row').forEach((row) => {
    row.addEventListener('click', () => {
      state.reviewSelectedId = row.dataset.reviewTaskId || '';
      replaceRouteHash();
      loadRoutePage();
    });
    row.addEventListener('dblclick', async () => {
      if (row.dataset.sourceId) await selectSource(row.dataset.sourceId);
    });
    row.querySelector('.review-check')?.addEventListener('click', (event) => {
      event.stopPropagation();
      const id = row.dataset.reviewTaskId || '';
      if (!id) return;
      if (event.currentTarget.checked) state.reviewSelectedIds.add(id);
      else state.reviewSelectedIds.delete(id);
    });
  });
  document.querySelectorAll('[data-review-preview-tab]').forEach((button) => {
    button.addEventListener('click', () => {
      state.reviewPreviewTab = button.dataset.reviewPreviewTab || 'review';
      replaceRouteHash();
      document.querySelectorAll('[data-review-preview-tab]').forEach((tab) => tab.classList.toggle('active', tab === button));
      document.querySelectorAll('[data-review-preview-section]').forEach((section) => {
        section.classList.toggle('active', section.dataset.reviewPreviewSection === state.reviewPreviewTab);
      });
    });
  });
  document.querySelectorAll('[data-review-action]').forEach((button) => {
    button.addEventListener('click', async () => {
      const row = (data.rows || []).find((item) => reviewTaskKey(item) === state.reviewSelectedId) || data.preview?.row;
      try {
        await applyReviewAction(row, button.dataset.reviewAction || 'defer');
      } catch (error) {
        const status = $('reviewActionStatus');
        if (status) status.textContent = error.message;
      }
    });
  });
  document.querySelectorAll('[data-review-bulk-action]').forEach((button) => {
    button.addEventListener('click', async () => {
      try {
        await applyBulkReviewAction(button.dataset.reviewBulkAction || 'defer');
      } catch (error) {
        const status = $('reviewBulkStatus');
        if (status) status.textContent = error.message;
      }
    });
  });
  bindReviewKeyboard();
}

function publishingBundleKey(row) {
  return row.bundle_id || [row.project, row.package_type].filter(Boolean).join(':');
}

function publishingGlyph(row) {
  const type = row.package_type || '';
  if (type.includes('comparison')) return 'CMP';
  if (type.includes('benchmark')) return 'BRF';
  if (type.includes('entity')) return 'ENT';
  if (type.includes('timeline')) return 'TL';
  if (type.includes('export')) return 'EXP';
  return 'PUB';
}

function publishingStateClass(value) {
  const stateValue = String(value || '');
  if (stateValue.includes('failed') || stateValue.includes('blocked')) return 'danger';
  if (stateValue.includes('ready') || stateValue.includes('approved') || stateValue.includes('published')) return 'ok';
  if (stateValue.includes('review') || stateValue.includes('assembling')) return 'info';
  return 'warn';
}

function renderPublishingPreview(data) {
  const preview = data.preview || {};
  const row = preview.row || null;
  if (!row) {
    return `
      <div class="empty-state">
        <h2>Package detail</h2>
        <p>Select a publication package to inspect readiness, contents, citations, snapshot state, handoff targets, and history.</p>
      </div>
    `;
  }
  const activeTab = ['readiness', 'contents', 'citations', 'snapshot', 'handoff', 'history'].includes(state.publishingPreviewTab) ? state.publishingPreviewTab : 'readiness';
  const tab = (id, label) => `<button class="${activeTab === id ? 'active' : ''}" type="button" data-publishing-preview-tab="${id}">${label}</button>`;
  const sectionClass = (id) => `publishing-preview-section ${activeTab === id ? 'active' : ''}`;
  const checkClass = (check) => check.state === 'pass' ? 'ok' : check.state === 'blocked' ? 'danger' : 'warn';
  return `
    <div class="review-preview-head publishing-preview-head">
      <span class="source-glyph">${escapeHtml(publishingGlyph(row))}</span>
      <div>
        <h2>${escapeHtml(row.title || 'Publication package')}</h2>
        <p>${escapeHtml([row.display_state, row.package_type_label, row.target].filter(Boolean).map(titleCase).join(' · '))}</p>
      </div>
    </div>
    <nav class="review-preview-tabs publishing-preview-tabs" aria-label="Publication detail sections">
      ${tab('readiness', 'Readiness')}
      ${tab('contents', 'Contents')}
      ${tab('citations', 'Citations')}
      ${tab('snapshot', 'Snapshot')}
      ${tab('handoff', 'Handoff')}
      ${tab('history', 'History')}
    </nav>
    <section class="${sectionClass('readiness')}" data-publishing-preview-section="readiness">
      <article class="review-preview-card readiness-card">
        <h4>Snapshot readiness</h4>
        <div class="readiness-line">
          <strong>${escapeHtml(row.readiness_percent || 0)}%</strong>
          <span>${escapeHtml(row.checks_passed || 0)} of ${escapeHtml(row.checks_total || 0)} checks pass</span>
          <em>${escapeHtml(row.blocker_count || 0)} blockers</em>
        </div>
        ${progressBar(row.readiness_percent || 0)}
      </article>
      <article class="review-preview-card">
        <h4>Blocking and required checks</h4>
        ${(preview.checks || []).map((check) => `
          <p><span class="status-badge ${checkClass(check)}">${escapeHtml(check.state || '')}</span> <strong>${escapeHtml(check.label || '')}</strong><br>${escapeHtml(check.detail || '')}</p>
        `).join('')}
      </article>
      <article class="review-preview-card">
        <h4>Package layers</h4>
        <div class="review-layer-stack">
          <div><span>Mutable draft</span><strong>${escapeHtml(row.draft_revision || '')}</strong></div>
          <div><span>Curated objects</span><strong>${escapeHtml(row.claim_count || 0)} claims · ${escapeHtml(row.evidence_count || 0)} evidence</strong></div>
          <div><span>Package manifest</span><strong>${escapeHtml(row.manifest_version || '')}</strong></div>
          <div><span>Snapshot</span><strong>${escapeHtml(titleCase(row.snapshot_state || 'none'))}</strong></div>
          <div><span>Handoff</span><strong>${escapeHtml(row.release_state || 'waiting')}</strong></div>
        </div>
      </article>
    </section>
    <section class="${sectionClass('contents')}" data-publishing-preview-section="contents">
      <article class="review-preview-card">
        <h4>Package outline</h4>
        ${(preview.contents || []).map((item, index) => `<p><strong>${String(index + 1).padStart(2, '0')} · ${escapeHtml(item.label || '')}</strong><br>${escapeHtml(item.detail || '')}</p>`).join('')}
      </article>
      <article class="review-preview-card manifest-grid">
        <h4>Manifest composition</h4>
        <p><strong>${escapeHtml(row.section_count || 0)}</strong><br>sections</p>
        <p><strong>${escapeHtml(row.claim_count || 0)}</strong><br>claims</p>
        <p><strong>${escapeHtml(row.evidence_count || 0)}</strong><br>evidence objects</p>
        <p><strong>${escapeHtml(row.citation_count || 0)}</strong><br>citations</p>
        <p><strong>${escapeHtml(row.capture_count || 0)}</strong><br>captures</p>
        <p><strong>${escapeHtml(row.media_count || 0)}</strong><br>media assets</p>
      </article>
    </section>
    <section class="${sectionClass('citations')}" data-publishing-preview-section="citations">
      <article class="review-preview-card">
        <h4>Citation and provenance checks</h4>
        ${(preview.citations || []).map((item) => `<p><span class="status-badge ${publishingStateClass(item.state)}">${escapeHtml(item.state || '')}</span> <strong>${escapeHtml(item.label || '')}</strong><br>${escapeHtml(item.detail || '')}</p>`).join('')}
      </article>
    </section>
    <section class="${sectionClass('snapshot')}" data-publishing-preview-section="snapshot">
      <article class="review-preview-card">
        <h4>Snapshot candidate</h4>
        <p><strong>${escapeHtml(titleCase(preview.snapshot?.state || 'none'))}</strong><br>${escapeHtml(preview.snapshot?.note || '')}</p>
        <p><strong>Manifest hash</strong><br><code>${escapeHtml(preview.snapshot?.manifest_hash || '')}</code></p>
        <p><strong>Frozen inputs</strong><br>${escapeHtml(preview.snapshot?.draft_revision || '')} · ${escapeHtml(preview.snapshot?.manifest_version || '')}</p>
      </article>
    </section>
    <section class="${sectionClass('handoff')}" data-publishing-preview-section="handoff">
      <article class="review-preview-card">
        <h4>Configured handoff targets</h4>
        ${(preview.handoff || []).map((item) => `<p><strong>${escapeHtml(item.label || '')}</strong><br>${escapeHtml(item.detail || '')}</p>`).join('')}
      </article>
    </section>
    <section class="${sectionClass('history')}" data-publishing-preview-section="history">
      <article class="review-preview-card">
        <h4>Package, review, and release history</h4>
        ${(preview.history || []).map((item) => `<p><strong>${escapeHtml(item.event_type || '')}</strong><br>${escapeHtml(fmtDate(item.created_at))} · ${escapeHtml(item.actor || '')}<br>${escapeHtml(item.detail || '')}</p>`).join('')}
      </article>
    </section>
    <div id="publishingActionStatus" class="review-status muted"></div>
    ${renderPublishingActions(preview.row)}
  `;
}

// Drive enabled/disabled from the backend's persisted snapshot/release state so
// the UI never offers publish before an approved frozen snapshot exists.
function renderPublishingActions(row) {
  const permitted = row?.permitted_actions || ['open_package', 'run_checks', 'focus_blockers'];
  const disabled = row?.disabled_actions || ['request_review', 'create_handoff', 'publish_snapshot', 'supersede_release'];
  const labelFor = (action) => ({
    open_package: 'Open package', run_checks: 'Run checks', focus_blockers: 'Resolve blockers',
    create_snapshot: 'Create snapshot', request_review: 'Request review',
    create_handoff: 'Create handoff', publish_snapshot: 'Publish snapshot', supersede_release: 'Supersede release',
    new_package: 'New package', create_from_draft: 'Create from draft', published_releases: 'Published releases',
  })[action] || action;
  const all = [...new Set([...permitted, ...disabled])];
  return `<div class="review-preview-actions publishing-actions">
    ${all.map((action) => {
      const isDisabled = disabled.includes(action) && !permitted.includes(action);
      return `<button class="secondary" data-publishing-action="${escapeHtml(action)}" ${isDisabled ? 'disabled title="Unavailable for the current snapshot state"' : ''}>${escapeHtml(labelFor(action))}</button>`;
    }).join('')}
  </div>`;
}

async function persistPublishingAction(row, action) {
  if (!row) return;
  if (action === 'open_package') {
    openPublicationDetail(row);
    return;
  }
  const endpoint = {
    create_snapshot: '/api/publishing/snapshot',
    request_review: '/api/publishing/request-review',
    publish_snapshot: '/api/publishing/publish',
    supersede_release: '/api/publishing/supersede',
  }[action];
  if (endpoint) {
    await postJson(endpoint, {
      bundle_id: publishingBundleKey(row),
      snapshot_id: row.latest_snapshot_id || '',
      actor: REVIEW_UI_ACTOR,
      expected_version: row.snapshot_updated_at || row.optimistic_version || '',
    });
    return;
  }
  await postJson('/api/review/events', {
    event_type: `publishing.${action}.recorded`,
    source_evidence_id: '',
    source_project: row.project || state.project || '',
    project: row.project || state.project || '',
    subject_type: 'publication_bundle',
    subject_id: publishingBundleKey(row),
    action,
    status: row.display_state || 'draft',
    note: `${titleCase(action)} from Publishing workspace`,
    source_anchor: {
      kind: 'publication_bundle',
      bundle_id: publishingBundleKey(row),
      manifest_hash: row.manifest_hash || '',
      optimistic_version: row.optimistic_version || '',
    },
    idempotency_key: idempotencyKey(publishingBundleKey(row), action, row.display_state || row.release_state || ''),
  });
}

function movePublishingSelection(delta) {
  if (state.route !== 'publishing') return;
  const rows = state.publishingRows || [];
  if (!rows.length) return;
  const current = rows.findIndex((row) => publishingBundleKey(row) === state.publishingSelectedId);
  const nextIndex = Math.max(0, Math.min(rows.length - 1, (current >= 0 ? current : 0) + delta));
  state.publishingSelectedId = publishingBundleKey(rows[nextIndex]);
  replaceRouteHash();
  loadRoutePage();
}

function bindPublishingKeyboard() {
  if (window.__webOsintPublishingKeyboardBound) return;
  window.__webOsintPublishingKeyboardBound = true;
  window.addEventListener('keydown', async (event) => {
    if (state.route !== 'publishing') return;
    const active = document.activeElement;
    if (active && ['INPUT', 'TEXTAREA', 'SELECT', 'BUTTON'].includes(active.tagName)) return;
    const key = event.key.toLowerCase();
    if (key === 'j') { event.preventDefault(); movePublishingSelection(1); return; }
    if (key === 'k') { event.preventDefault(); movePublishingSelection(-1); return; }
    // Space toggles the bulk-selection checkbox for the focused bundle.
    if (key === ' ') {
      event.preventDefault();
      const row = (state.publishingRows || []).find((item) => publishingBundleKey(item) === state.publishingSelectedId);
      if (row) {
        const key0 = publishingBundleKey(row);
        state.taxonomySelectedIds = state.taxonomySelectedIds || new Set();
        if (state.taxonomySelectedIds.has(key0)) state.taxonomySelectedIds.delete(key0);
        else state.taxonomySelectedIds.add(key0);
        loadRoutePage();
      }
      return;
    }
    if (['o', 'c', 'b', 's', 'r', 'e', 'p', 'h'].includes(key)) {
      event.preventDefault();
      const row = (state.publishingRows || []).find((item) => publishingBundleKey(item) === state.publishingSelectedId);
      // Map key -> the existing publishing action vocabulary. Snapshot/publish
      // respect disabled_actions (no-op when the row marks them unavailable).
      const actionMap = { o: 'open_package', c: 'run_checks', b: 'focus_blockers', s: 'create_snapshot', r: 'request_review', e: 'create_handoff', p: 'publish_snapshot', h: 'history' };
      const action = actionMap[key];
      const disabled = new Set(row?.disabled_actions || ['create_snapshot', 'request_review', 'create_handoff', 'publish_snapshot', 'supersede_release']);
      if (['create_snapshot', 'publish_snapshot'].includes(action) && disabled.has(action)) {
        const status = $('publishingActionStatus');
        if (status) status.textContent = `${action} is not available for this bundle.`;
        return;
      }
      try {
        if (action === 'open_package') {
          openPublicationDetail(row);
        } else if (action === 'history' || action === 'focus_blockers' || action === 'create_handoff') {
          // Read-only / preview actions: switch preview tab where one exists.
          if (action === 'focus_blockers') state.publishingPreviewTab = 'readiness';
          else if (action === 'history') state.publishingPreviewTab = 'audit';
          else state.publishingPreviewTab = 'readiness';
          replaceRouteHash();
          loadRoutePage();
        } else {
          await persistPublishingAction(row, action);
        }
      } catch (error) {
        const status = $('publishingActionStatus');
        if (status) status.textContent = error.message;
      }
    }
  });
}

function bindPublishingPage(data) {
  $('publishingSearchInput')?.addEventListener('input', () => {
    state.q = $('publishingSearchInput').value.trim();
    clearTimeout(window.__publishingSearchTimer);
    window.__publishingSearchTimer = setTimeout(() => {
      state.publishingSelectedId = '';
      replaceRouteHash();
      loadRoutePage();
    }, 250);
  });
  $('publishingSearchButton')?.addEventListener('click', () => {
    state.q = $('publishingSearchInput')?.value.trim() || '';
    state.publishingSelectedId = '';
    replaceRouteHash();
    loadRoutePage();
  });
  $('publishingScopeSelect')?.addEventListener('change', () => {
    state.project = $('publishingScopeSelect').value || '';
    state.publishingSelectedId = '';
    replaceRouteHash();
    loadRoutePage();
  });
  $('publishingClearFilters')?.addEventListener('click', () => {
    state.q = '';
    state.project = '';
    state.publishingSelectedId = '';
    state.publishingPreviewTab = 'readiness';
    replaceRouteHash();
    loadRoutePage();
  });
	  document.querySelectorAll('.publish-row').forEach((rowEl) => {
	    rowEl.addEventListener('click', () => {
	      state.publishingSelectedId = rowEl.dataset.bundleId || '';
	      replaceRouteHash();
	      loadRoutePage();
	    });
	    rowEl.addEventListener('dblclick', () => {
	      const row = (data.bundles || []).find((item) => publishingBundleKey(item) === (rowEl.dataset.bundleId || ''));
	      openPublicationDetail(row);
	    });
	  });
  document.querySelectorAll('[data-publishing-preview-tab]').forEach((button) => {
    button.addEventListener('click', () => {
      state.publishingPreviewTab = button.dataset.publishingPreviewTab || 'readiness';
      replaceRouteHash();
      document.querySelectorAll('[data-publishing-preview-tab]').forEach((tab) => tab.classList.toggle('active', tab === button));
      document.querySelectorAll('[data-publishing-preview-section]').forEach((section) => {
        section.classList.toggle('active', section.dataset.publishingPreviewSection === state.publishingPreviewTab);
      });
    });
  });
  document.querySelectorAll('[data-publishing-action]').forEach((button) => {
    button.addEventListener('click', async () => {
      if (button.disabled) return;
      const row = (data.bundles || []).find((item) => publishingBundleKey(item) === state.publishingSelectedId) || data.preview?.row;
      const status = $('publishingActionStatus');
      try {
        if (status) status.textContent = `${button.textContent.trim()}...`;
	        await persistPublishingAction(row, button.dataset.publishingAction || 'run_checks');
	        if (status) status.textContent = `${button.textContent.trim()} recorded.`;
	        if (state.route === 'publishing') await loadRoutePage();
	      } catch (error) {
        if (status) status.textContent = error.message;
      }
    });
  });
  bindPublishingKeyboard();
}

function renderPublishingPage(data) {
  const rows = data.bundles || data.results?.rows || [];
  state.publishingRows = rows;
  if (!state.publishingSelectedId || !rows.some((row) => publishingBundleKey(row) === state.publishingSelectedId)) {
    state.publishingSelectedId = data.preview?.row ? publishingBundleKey(data.preview.row) : (rows[0] ? publishingBundleKey(rows[0]) : '');
  }
  const summary = data.summary || {};
  $('routePage').innerHTML = `
    <header class="page-header trace-page-header">
      <div>
        <span class="breadcrumb">Research UI / Publication preparation</span>
        <div class="title-action-group">
          <span class="status-badge info">snapshot-backed workflow</span>
          <span class="status-badge danger">${escapeHtml(summary.blocked || 0)} blocking checks</span>
        </div>
        <h1>Publishing</h1>
        <p>Assemble reviewed claims and exact source citations into frozen, reusable publication packages.</p>
        <p class="muted">Snapshot creation freezes the current manifest. Publish remains gated on an approved snapshot.</p>
      </div>
      <div class="page-actions">
        <button class="secondary" data-publishing-action="published_releases">Published releases</button>
        <button class="secondary" data-publishing-action="create_from_draft">Create from draft</button>
        <button data-publishing-action="new_package">New package</button>
      </div>
    </header>
    <section class="operation-search-card">
      <label class="operation-search">
        <span class="sr-only">Publishing search</span>
        <input id="publishingSearchInput" value="${escapeHtml(state.q)}" placeholder="Search publication packages, claims, citations, handoff targets">
      </label>
      <div class="operation-search-controls">
        <div class="segmented-control" aria-label="Publishing search mode">
          <button class="secondary" type="button">Exact</button>
          <button class="secondary" type="button">Semantic</button>
          <button class="active" type="button">Hybrid</button>
        </div>
        <select id="publishingScopeSelect" aria-label="Publishing scope">
          <option value="">Project: All projects</option>
          ${state.project ? `<option value="${escapeHtml(state.project)}" selected>Project: ${escapeHtml(state.project)}</option>` : ''}
        </select>
        <button id="publishingSearchButton" type="button">Search</button>
        <button class="secondary compact-clear" id="publishingClearFilters" type="button">Clear</button>
      </div>
      <div class="operation-search-meta">
        <span class="status-badge info">Frozen snapshot workflow</span>
        <p>Approvals and releases reference immutable snapshot IDs and manifest hashes, never mutable live bundle queries.</p>
        <strong>${escapeHtml(summary.bundles ?? rows.length)} active · ${escapeHtml(summary.blocked ?? 0)} blocked · ${escapeHtml(summary.ready ?? 0)} ready</strong>
      </div>
    </section>
    <section class="publishing-shell trace-workbench">
      <aside class="panel review-filter-panel publishing-filter-panel">
        <section class="review-facet-group">
          <h3>Publishing queues</h3>
          <div class="facet-list compact">
            ${(data.queues || []).map((item) => `
              <button class="facet" type="button">
                <span>${escapeHtml(item.label || item.id)}</span><strong>${escapeHtml(item.count || 0)}</strong>
              </button>
            `).join('')}
          </div>
        </section>
        ${reviewFacetGroup('Package type', data.facets?.package_types, '', 'publishing_type')}
        ${reviewFacetGroup('Displayed state', data.facets?.displayed_states, '', 'publishing_state')}
        ${reviewFacetGroup('Target and handoff', data.facets?.targets, '', 'publishing_target')}
      </aside>
      <section class="panel review-ledger-panel publishing-ledger-panel">
        <div class="review-explanation">
          <span class="status-badge info">${escapeHtml(summary.bundles || 0)} publication packages</span>
          <p>Mutable package manifests become publishable only after checks pass, a frozen snapshot is created, and snapshot review is complete.</p>
        </div>
        <div class="review-bulk-toolbar">
          <label><input type="checkbox" id="publishingSelectAll"> Select visible</label>
          ${['run_checks', 'create_snapshot', 'request_review', 'create_handoff'].map((action) => `<button class="secondary" data-publishing-action="${action}">${escapeHtml(titleCase(action))}</button>`).join('')}
          <span id="publishingBulkStatus" class="muted"></span>
        </div>
        <div class="publish-results-list">
          ${rows.length ? rows.map((row) => {
            const rowKey = publishingBundleKey(row);
            const selected = rowKey === state.publishingSelectedId;
            return `
              <article class="publish-row ${selected ? 'active' : ''}" data-bundle-id="${escapeHtml(rowKey)}">
                <input class="review-check" type="checkbox" aria-label="Select publication package">
                <span class="package-glyph">${escapeHtml(publishingGlyph(row))}</span>
                <div class="review-row-main">
                  <div class="review-title-line">
                    <span class="pill">${escapeHtml(row.package_type_label || row.package_type || 'Package')}</span>
                    <strong>${escapeHtml(row.title || 'Publication package')}</strong>
                  </div>
                  <p>${escapeHtml(row.section_count || 0)} sections · ${escapeHtml(row.claim_count || 0)} claims · ${escapeHtml(row.evidence_count || 0)} evidence objects · ${escapeHtml(row.citation_count || 0)} citations</p>
                  <div class="row-meta">
                    <span class="pill ${row.blocker_count ? 'warn' : 'ok'}">${escapeHtml(row.blocker_count || 0)} blockers</span>
                    <span class="pill">${escapeHtml(row.checks_passed || 0)} / ${escapeHtml(row.checks_total || 0)} checks</span>
                    <span class="pill">${escapeHtml(row.snapshot_state || 'no snapshot')}</span>
                    <span class="pill">${escapeHtml(row.capture_count || 0)} captures pinned</span>
                  </div>
                  <div class="package-progress">${progressBar(row.readiness_percent || 0)}<small>${escapeHtml(row.readiness_percent || 0)}% ready</small></div>
                </div>
                <div class="review-row-state">
                  <span class="status-badge ${publishingStateClass(row.display_state)}">${escapeHtml(titleCase(row.display_state || 'draft'))}</span>
                  <em>${escapeHtml(row.owner || '')}</em>
                  <em>${escapeHtml(row.draft_revision || '')}</em>
                  <em>${escapeHtml(fmtDate(row.updated_at) || '')}</em>
                </div>
              </article>
            `;
          }).join('') : '<div class="empty-state"><h2>No publication packages</h2><p>Create a package from reviewed claims, evidence, or a draft.</p></div>'}
        </div>
      </section>
      <aside class="panel review-preview-panel publishing-preview-panel">
        ${renderPublishingPreview(data)}
      </aside>
    </section>
  `;
  bindPublishingPage(data);
}

function taxonomyRecordKey(row) {
  return row?.record_id || row?.stable_id || row?.term || '';
}

function taxonomyGlyph(row) {
  const vocabulary = row?.vocabulary || '';
  if (vocabulary === 'model_facets') return 'MOD';
  if (vocabulary === 'claim_properties') return 'CLM';
  if (vocabulary === 'benchmark_facets') return 'BEN';
  if (vocabulary === 'entity_types') return 'ENT';
  if (vocabulary === 'source_categories') return 'SRC';
  if (vocabulary === 'evidence_types') return 'EVD';
  if (vocabulary === 'review_reason_codes') return 'REV';
  if (vocabulary === 'topics') return 'TOP';
  return 'TAX';
}

function taxonomyStateLabel(stateValue) {
  return {
    accepted: 'Accepted',
    proposed: 'Needs mapping',
    mapping_conflict: 'Conflict',
    under_review: 'Under review',
    deprecated: 'Deprecated',
  }[stateValue] || titleCase(stateValue || 'draft');
}

function taxonomyStateClass(stateValue) {
  return {
    accepted: 'ok',
    proposed: 'warn',
    mapping_conflict: 'danger',
    under_review: 'info',
    deprecated: '',
  }[stateValue] || '';
}

function taxonomyUsageTokens(row) {
  const usage = row.usage || {};
  return [
    ['observations', 'observations'],
    ['evidence', 'evidence'],
    ['claims', 'claims'],
    ['projects', 'projects'],
    ['packages', 'packages'],
  ].filter(([key]) => Number(usage[key] || 0) > 0).map(([key, label]) => `
    <span class="usage-token ${escapeHtml(key)}">${escapeHtml(usage[key])} ${escapeHtml(label)}</span>
  `).join('');
}

function taxonomyQueueList(queues) {
  return `
    <section class="taxonomy-facet-section">
      <div class="facet-title">My taxonomy work</div>
      <div class="saved-list">
        ${(queues || []).map((item) => `
          <button class="saved-item ${state.taxonomyQueue === item.id ? 'active' : ''}" type="button" data-taxonomy-queue="${escapeHtml(item.id)}">
            <span>${escapeHtml(item.label || item.id)}</span>
            <strong class="${item.id === 'mapping_conflicts' || item.id === 'publication_impact' ? 'alert' : item.id === 'proposed_terms' ? 'amber' : ''}">${escapeHtml(item.count || 0)}</strong>
          </button>
        `).join('')}
      </div>
    </section>
  `;
}

function taxonomyVocabularyList(vocabularies) {
  return `
    <section class="taxonomy-facet-section">
      <div class="facet-title">Controlled vocabularies <span>${escapeHtml((vocabularies || []).length)} sets</span></div>
      <button class="facet ${state.taxonomyVocabulary ? '' : 'active'}" type="button" data-taxonomy-vocabulary="">
        <span>All controlled sets</span><strong>${escapeHtml((vocabularies || []).reduce((sum, item) => sum + Number(item.count || 0), 0))}</strong>
      </button>
      ${(vocabularies || []).map((item) => `
        <button class="facet ${state.taxonomyVocabulary === item.id ? 'active' : ''}" type="button" data-taxonomy-vocabulary="${escapeHtml(item.id)}">
          <span><span class="taxonomy-mini-icon">${escapeHtml((item.label || item.id).slice(0, 3).toUpperCase())}</span>${escapeHtml(item.label || item.id)}</span>
          <strong>${escapeHtml(item.count || 0)}</strong>
        </button>
      `).join('')}
    </section>
  `;
}

function taxonomyHierarchyTree(nodes) {
  return `
    <section class="taxonomy-facet-section">
      <div class="facet-title">Hierarchy <span>active branch</span></div>
      <div class="taxonomy-tree">
        ${(nodes || []).map((node) => `
          <button class="taxonomy-tree-node depth-${escapeHtml(node.depth || 0)} ${node.active ? 'active' : ''} ${node.leaf ? 'leaf' : ''}" type="button" data-taxonomy-inspect="${escapeHtml(node.id || '')}">
            <span>${node.leaf ? '-' : '+'}</span>
            <strong>${escapeHtml(node.label || node.id)}</strong>
            <em>${escapeHtml(node.count || 0)}</em>
          </button>
        `).join('')}
      </div>
    </section>
  `;
}

function taxonomyStateFilters(facets) {
  const states = facets?.review_states || [];
  return `
    <section class="taxonomy-facet-section">
      <div class="facet-title">Term state</div>
      <button class="facet ${state.taxonomyReviewState ? '' : 'active'}" type="button" data-taxonomy-state="">
        <span>All states</span><strong>${escapeHtml(states.reduce((sum, item) => sum + Number(item.count || 0), 0))}</strong>
      </button>
      ${states.map((item) => `
        <button class="facet ${state.taxonomyReviewState === item.id ? 'active' : ''}" type="button" data-taxonomy-state="${escapeHtml(item.id)}">
          <span><i class="facet-dot ${escapeHtml(item.id)}"></i>${escapeHtml(item.label || item.id)}</span>
          <strong>${escapeHtml(item.count || 0)}</strong>
        </button>
      `).join('')}
    </section>
  `;
}

function renderTaxonomyPreview(data) {
  const preview = data.preview || {};
  const row = preview.row || null;
  if (!row) {
    return `
      <div class="empty-state">
        <h2>Taxonomy Preview</h2>
        <p>Select a term to inspect mappings, usage, policy, publication impact, and history.</p>
      </div>
    `;
  }
  const activeTab = ['overview', 'usage', 'mappings', 'publication', 'history'].includes(state.taxonomyPreviewTab) ? state.taxonomyPreviewTab : 'overview';
  const tab = (id, label) => `<button class="${activeTab === id ? 'active' : ''}" type="button" data-taxonomy-preview-tab="${id}">${label}</button>`;
  const sectionClass = (id) => `taxonomy-preview-section ${activeTab === id ? 'active' : ''}`;
  const policy = preview.policy || {};
  return `
    <div class="taxonomy-preview-head">
      <span class="taxonomy-glyph">${escapeHtml(taxonomyGlyph(row))}</span>
      <div>
        <h2>${escapeHtml(row.term || 'Taxonomy term')}</h2>
        <p>${escapeHtml([row.vocabulary_label, row.hierarchy_path, row.stable_id].filter(Boolean).join(' / '))}</p>
      </div>
      <span class="status-badge ${escapeHtml(taxonomyStateClass(row.review_state))}">${escapeHtml(taxonomyStateLabel(row.review_state))}</span>
    </div>
    <nav class="taxonomy-preview-tabs" aria-label="Taxonomy preview sections">
      ${tab('overview', 'Overview')}
      ${tab('usage', 'Usage')}
      ${tab('mappings', 'Mappings')}
      ${tab('publication', 'Publication')}
      ${tab('history', 'History')}
    </nav>
    <section class="${sectionClass('overview')}" data-taxonomy-preview-section="overview">
      <article class="taxonomy-preview-card">
        <h4>Definition</h4>
        <p>${escapeHtml(row.definition || 'No definition available.')}</p>
      </article>
      <article class="taxonomy-preview-card">
        <h4>Aliases and observed labels</h4>
        <div class="tag-line">${(row.aliases || []).map((alias) => `<span class="pill">${escapeHtml(alias)}</span>`).join('') || '<span class="muted">No aliases recorded.</span>'}</div>
      </article>
      <div class="taxonomy-policy-grid">
        <span>Lifecycle</span><strong>${escapeHtml(row.lifecycle_state || '')}</strong>
        <span>Owner</span><strong>${escapeHtml(row.owner || '')}</strong>
        <span>Priority</span><strong>${escapeHtml(row.priority || '')}</strong>
        <span>Publication safe</span><strong class="${policy.publication_safe === false ? 'warn' : ''}">${escapeHtml(policy.publication_safe === false ? 'No' : 'Yes / not restricted')}</strong>
        <span>Required qualifier</span><strong>${escapeHtml(policy.required_qualifier || 'No required qualifier recorded')}</strong>
      </div>
    </section>
    <section class="${sectionClass('usage')}" data-taxonomy-preview-section="usage">
      <div class="taxonomy-usage-strip">
        ${(preview.usage_stats || []).map((item) => `
          <article><strong>${escapeHtml(item.value || 0)}</strong><span>${escapeHtml(item.label)}</span><em>${escapeHtml(item.hint || '')}</em></article>
        `).join('')}
      </div>
      <article class="taxonomy-preview-card">
        <h4>Source anchors</h4>
        ${(preview.anchors || []).map((item) => `
          <p><strong>${escapeHtml(item.label || item.source_kind || '')}</strong><br>${escapeHtml(item.count || 0)} captured source${Number(item.count || 0) === 1 ? '' : 's'}</p>
        `).join('') || '<p class="muted">No source anchors are linked yet.</p>'}
      </article>
    </section>
    <section class="${sectionClass('mappings')}" data-taxonomy-preview-section="mappings">
      <article class="taxonomy-preview-card">
        <h4>Mapping candidates</h4>
        ${(preview.mapping_candidates || []).map((item) => `
          <div class="taxonomy-mapping-row">
            <span>${escapeHtml(Math.round(Number(item.confidence || 0) * 100))}%</span>
            <div><strong>${escapeHtml(item.term || '')}</strong><p>${escapeHtml([item.stable_id, item.relation].filter(Boolean).join(' / '))}</p></div>
          </div>
        `).join('') || '<p class="muted">No mapping candidates recorded.</p>'}
      </article>
    </section>
    <section class="${sectionClass('publication')}" data-taxonomy-preview-section="publication">
      <article class="taxonomy-preview-card">
        <h4>Publication impact</h4>
        ${(preview.publication_impacts || []).map((item) => `
          <div class="taxonomy-impact-row ${item.state === 'blocking' ? 'blocking' : ''}">
            <strong>${escapeHtml(item.label || '')}</strong>
            <span>${escapeHtml(item.count || 0)}</span>
            <p>${escapeHtml(item.detail || '')}</p>
          </div>
        `).join('') || '<p class="muted">No publication impact recorded.</p>'}
      </article>
      <article class="taxonomy-preview-card">
        <h4>Decision rule</h4>
        <p>${escapeHtml(policy.decision_rule || policy.replacement || 'No decision policy recorded.')}</p>
      </article>
    </section>
    <section class="${sectionClass('history')}" data-taxonomy-preview-section="history">
      <article class="taxonomy-preview-card">
        <h4>History</h4>
        ${(preview.history || []).map((item) => `<p><strong>${escapeHtml(item.event_type || '')}</strong><br>${escapeHtml(fmtDate(item.created_at))} / ${escapeHtml(item.actor || '')}<br>${escapeHtml(item.detail || '')}</p>`).join('') || '<p class="muted">No history recorded.</p>'}
      </article>
    </section>
    <label class="preview-note">Decision note
      <input id="taxonomyDecisionNote" placeholder="Optional taxonomy rationale, mapping target, qualifier, or publication note">
    </label>
    <div id="taxonomyActionStatus" class="review-status muted"></div>
    <div class="taxonomy-preview-actions">
      <button class="secondary" data-taxonomy-action="assign_review">Assign</button>
      <button class="secondary" data-taxonomy-action="add_alias">Add alias</button>
      <button class="secondary" data-taxonomy-action="map">Map</button>
      <button class="secondary" data-taxonomy-action="merge">Merge</button>
      <button class="secondary" data-taxonomy-action="deprecate">Deprecate</button>
      <button data-taxonomy-action="promote">Promote</button>
    </div>
  `;
}

function renderTaxonomyPage(data) {
  const rows = data.rows || data.results?.rows || [];
  state.taxonomyRows = rows;
  if (!state.taxonomySelectedId || !rows.some((row) => taxonomyRecordKey(row) === state.taxonomySelectedId)) {
    state.taxonomySelectedId = data.preview?.row ? taxonomyRecordKey(data.preview.row) : (rows[0] ? taxonomyRecordKey(rows[0]) : '');
  }
  const summary = data.summary || {};
  const query = data.query || {};
  const activeQueueLabel = (data.queues || []).find((item) => item.id === state.taxonomyQueue)?.label || 'Taxonomy work';
  $('routePage').innerHTML = `
    ${pageHeader(
      'Taxonomy',
      'Govern controlled terms, aliases, mappings, and publication-safe vocabulary across the research corpus.',
      `<button class="secondary" data-taxonomy-action="version_history">Version history</button><button class="secondary" data-taxonomy-action="import_mappings">Import mappings</button><button data-taxonomy-action="create_term">New term</button>`
    )}
    <section class="taxonomy-search-card panel">
      <label class="taxonomy-search-main">
        <span class="sr-only">Search taxonomy</span>
        <input id="taxonomySearchInput" type="search" value="${escapeHtml(state.q)}" placeholder="Search terms, aliases, stable IDs, definitions, hierarchy paths...">
      </label>
      <div class="mode-toggle taxonomy-mode-toggle">
        ${['exact', 'semantic', 'hybrid'].map((mode) => `<button class="mode-btn ${state.taxonomySearchMode === mode ? 'active' : ''}" type="button" data-taxonomy-mode="${mode}">${escapeHtml(titleCase(mode))}</button>`).join('')}
      </div>
      <select id="taxonomyVocabularySelect">
        <option value="">Vocabulary: All controlled sets</option>
        ${(data.vocabularies || []).map((item) => `<option value="${escapeHtml(item.id)}" ${state.taxonomyVocabulary === item.id ? 'selected' : ''}>${escapeHtml(item.label)} (${escapeHtml(item.count || 0)})</option>`).join('')}
      </select>
      <button id="taxonomySearchButton">Search</button>
      <div class="taxonomy-search-meta">
        <span class="scope-pill">${escapeHtml((query.mode || state.taxonomySearchMode || 'hybrid').toUpperCase())} match</span>
        <span>${escapeHtml(summary.visible ?? rows.length)} visible of ${escapeHtml(summary.terms ?? rows.length)} terms</span>
        <span>${escapeHtml(summary.accepted || 0)} accepted</span>
        <span>${escapeHtml(summary.proposals || 0)} proposals</span>
        <span>${escapeHtml(summary.conflicts || 0)} conflicts</span>
        <span>${escapeHtml(summary.publication_impacts || 0)} publication impacts</span>
      </div>
    </section>
    <section class="taxonomy-shell trace-workbench">
      <aside class="panel taxonomy-filter-panel">
        <div class="pane-head"><h2>Taxonomy structure</h2><span class="count">${escapeHtml(data.draft_release?.label || 'draft')}</span><button id="taxonomyClearFilters" class="text-button" type="button">Clear</button></div>
        <div class="taxonomy-facets-scroll">
          ${taxonomyQueueList(data.queues || [])}
          ${taxonomyVocabularyList(data.vocabularies || [])}
          ${taxonomyHierarchyTree(data.hierarchy || [])}
          ${taxonomyStateFilters(data.facets || {})}
        </div>
      </aside>
      <section class="panel taxonomy-ledger-panel">
        <div class="taxonomy-results-head">
          <label><input type="checkbox" id="taxonomySelectAll"> Select visible</label>
          <div><strong>${escapeHtml(summary.visible ?? rows.length)} terms and mappings</strong><p>${escapeHtml(activeQueueLabel)} / draft taxonomy version / immutable term history</p></div>
          <span class="spacer"></span>
          <button class="secondary" data-taxonomy-sort="recent">Recently changed</button>
        </div>
        <div class="taxonomy-result-tabs">
          ${(data.queues || []).filter((item) => ['all', 'proposed_terms', 'awaiting_review', 'mapping_conflicts', 'deprecated'].includes(item.id)).map((item) => `
            <button class="${state.taxonomyQueue === item.id ? 'active' : ''}" type="button" data-taxonomy-queue="${escapeHtml(item.id)}">${escapeHtml(item.label)} <span>${escapeHtml(item.count || 0)}</span></button>
          `).join('')}
        </div>
        <div class="review-bulk-toolbar">
          ${['assign_review', 'promote', 'map', 'merge', 'add_alias', 'deprecate', 'export'].map((action) => `<button class="secondary" data-taxonomy-bulk-action="${action}">${escapeHtml(titleCase(action))}</button>`).join('')}
          <span id="taxonomyBulkStatus" class="muted"></span>
        </div>
        <div class="taxonomy-term-list">
          ${rows.length ? rows.map((row) => {
            const rowKey = taxonomyRecordKey(row);
            const selected = rowKey === state.taxonomySelectedId;
            return `
              <article class="taxonomy-row ${selected ? 'active' : ''} ${row.review_state || ''}" data-taxonomy-row-id="${escapeHtml(rowKey)}">
                <input class="taxonomy-check" type="checkbox" aria-label="Select taxonomy row" ${state.taxonomySelectedIds.has(rowKey) ? 'checked' : ''}>
                <span class="taxonomy-glyph">${escapeHtml(taxonomyGlyph(row))}</span>
                <div class="taxonomy-row-main">
                  <div class="taxonomy-title-line">
                    <span class="status-badge ${escapeHtml(taxonomyStateClass(row.review_state))}">${escapeHtml(taxonomyStateLabel(row.review_state))}</span>
                    <strong>${escapeHtml(row.term || '')}</strong>
                    ${row.publication_impacts?.length ? '<span class="pill warn">publication impact</span>' : ''}
                  </div>
                  <p>${escapeHtml(row.definition || '')}</p>
                  <div class="taxonomy-id-line"><strong>${escapeHtml(row.stable_id || row.record_id || '')}</strong><span>${escapeHtml(row.hierarchy_path || '')}</span></div>
                  <div class="taxonomy-alias-line">${(row.aliases || []).length ? `<strong>Aliases:</strong> ${escapeHtml((row.aliases || []).join(' / '))}` : 'No aliases recorded'}</div>
                  <div class="taxonomy-usage-line">${taxonomyUsageTokens(row) || '<span class="usage-token">0 usage</span>'}</div>
                </div>
                <div class="taxonomy-row-side">
                  <span class="status-badge ${escapeHtml(taxonomyStateClass(row.review_state))}">${escapeHtml(taxonomyStateLabel(row.review_state))}</span>
                  <em>${escapeHtml(row.owner || '')}</em>
                  <em>${escapeHtml(row.priority || '')}</em>
                  <em>${escapeHtml(fmtDate(row.updated_at) || '')}</em>
                </div>
              </article>
            `;
          }).join('') : '<div class="empty-state"><h2>No taxonomy rows</h2><p>Try another queue, vocabulary, or search.</p></div>'}
        </div>
      </section>
      <aside class="panel taxonomy-preview-panel">
        ${renderTaxonomyPreview(data)}
      </aside>
    </section>
  `;
  bindTaxonomyPage(data);
}

async function applyTaxonomyAction(row, action) {
  if (!row) return;
  const note = $('taxonomyDecisionNote')?.value || '';
  const payload = {
    event_type: `taxonomy.${action}.requested`,
    source_evidence_id: 'taxonomy:global',
    project: state.project || '',
    subject_type: 'taxonomy_term',
    subject_id: taxonomyRecordKey(row),
    action,
    note,
    source_anchor: {
      kind: 'taxonomy_term',
      stable_id: row.stable_id || row.record_id,
      vocabulary: row.vocabulary,
      term: row.term,
    },
    idempotency_key: idempotencyKey('taxonomy', action, taxonomyRecordKey(row), row.review_state || ''),
  };
  const status = $('taxonomyActionStatus');
  if (status) status.textContent = 'Recording action...';
  await postJson('/api/review/events', payload);
  if (status) status.textContent = `${titleCase(action)} recorded`;
}

async function applyBulkTaxonomyAction(action) {
  const ids = Array.from(state.taxonomySelectedIds);
  const status = $('taxonomyBulkStatus');
  if (!ids.length) {
    if (status) status.textContent = 'Select at least one taxonomy row first.';
    return;
  }
  if (status) status.textContent = `Recording ${ids.length} action${ids.length === 1 ? '' : 's'}...`;
  for (const id of ids) {
    const row = state.taxonomyRows.find((item) => taxonomyRecordKey(item) === id);
    if (row) await applyTaxonomyAction(row, action);
  }
  if (status) status.textContent = `${titleCase(action)} recorded for ${ids.length} row${ids.length === 1 ? '' : 's'}.`;
}

function moveTaxonomySelection(delta) {
  if (state.route !== 'taxonomy') return;
  const rows = state.taxonomyRows || [];
  if (!rows.length) return;
  const current = rows.findIndex((row) => taxonomyRecordKey(row) === state.taxonomySelectedId);
  const nextIndex = Math.max(0, Math.min(rows.length - 1, (current >= 0 ? current : 0) + delta));
  state.taxonomySelectedId = taxonomyRecordKey(rows[nextIndex]);
  replaceRouteHash();
  loadRoutePage();
}

function bindTaxonomyKeyboard() {
  if (window.__webOsintTaxonomyKeyboardBound) return;
  window.__webOsintTaxonomyKeyboardBound = true;
  window.addEventListener('keydown', async (event) => {
    if (state.route !== 'taxonomy') return;
    const active = document.activeElement;
    if (active && ['INPUT', 'TEXTAREA', 'SELECT', 'BUTTON'].includes(active.tagName)) return;
    const key = event.key.toLowerCase();
    if (key === 'j') { event.preventDefault(); moveTaxonomySelection(1); return; }
    if (key === 'k') { event.preventDefault(); moveTaxonomySelection(-1); return; }
    // Space toggles the row's bulk-selection checkbox.
    if (key === ' ') {
      event.preventDefault();
      const row = (state.taxonomyRows || []).find((item) => taxonomyRecordKey(item) === state.taxonomySelectedId);
      if (row) {
        const rk = taxonomyRecordKey(row);
        state.taxonomySelectedIds = state.taxonomySelectedIds || new Set();
        if (state.taxonomySelectedIds.has(rk)) state.taxonomySelectedIds.delete(rk);
        else state.taxonomySelectedIds.add(rk);
        loadRoutePage();
      }
      return;
    }
    if (['m', 'p', 'r', 'e', 'o', 'h'].includes(key)) {
      event.preventDefault();
      const row = (state.taxonomyRows || []).find((item) => taxonomyRecordKey(item) === state.taxonomySelectedId);
      const actionMap = { m: 'map', p: 'promote', r: 'reject', e: 'edit', o: 'usage', h: 'history' };
      const action = actionMap[key];
      try {
        if (action === 'usage' || action === 'history' || action === 'edit') {
          // Read-only / preview navigation.
          state.taxonomyPreviewTab = (action === 'usage') ? 'usage' : (action === 'history' ? 'audit' : state.taxonomyPreviewTab);
          replaceRouteHash();
          loadRoutePage();
        } else {
          await applyTaxonomyAction(row, action);
        }
      } catch (error) {
        const status = $('taxonomyActionStatus');
        if (status) status.textContent = error.message;
      }
    }
  });
}

function bindTaxonomyPage(data) {
  const commit = () => {
    state.taxonomySelectedIds.clear();
    replaceRouteHash();
    loadRoutePage();
  };
  $('taxonomySearchInput')?.addEventListener('input', () => {
    state.q = $('taxonomySearchInput').value.trim();
    clearTimeout(window.__taxonomySearchTimer);
    window.__taxonomySearchTimer = setTimeout(commit, 260);
  });
  $('taxonomySearchButton')?.addEventListener('click', commit);
  $('taxonomyVocabularySelect')?.addEventListener('change', () => {
    state.taxonomyVocabulary = $('taxonomyVocabularySelect').value;
    commit();
  });
  $('taxonomyClearFilters')?.addEventListener('click', () => {
    state.q = '';
    state.taxonomyQueue = 'proposed_terms';
    state.taxonomyVocabulary = '';
    state.taxonomyReviewState = '';
    state.taxonomySearchMode = 'hybrid';
    state.taxonomySelectedId = '';
    state.taxonomySelectedIds.clear();
    replaceRouteHash();
    loadRoutePage();
  });
  document.querySelectorAll('[data-taxonomy-mode]').forEach((button) => {
    button.addEventListener('click', () => {
      state.taxonomySearchMode = button.dataset.taxonomyMode || 'hybrid';
      commit();
    });
  });
  document.querySelectorAll('[data-taxonomy-queue]').forEach((button) => {
    button.addEventListener('click', () => {
      state.taxonomyQueue = button.dataset.taxonomyQueue || 'all';
      state.taxonomySelectedId = '';
      commit();
    });
  });
  document.querySelectorAll('[data-taxonomy-vocabulary]').forEach((button) => {
    button.addEventListener('click', () => {
      state.taxonomyVocabulary = button.dataset.taxonomyVocabulary || '';
      state.taxonomySelectedId = '';
      commit();
    });
  });
  document.querySelectorAll('[data-taxonomy-state]').forEach((button) => {
    button.addEventListener('click', () => {
      state.taxonomyReviewState = button.dataset.taxonomyState || '';
      state.taxonomySelectedId = '';
      commit();
    });
  });
  document.querySelectorAll('[data-taxonomy-inspect]').forEach((button) => {
    button.addEventListener('click', () => {
      const id = button.dataset.taxonomyInspect || '';
      const match = state.taxonomyRows.find((row) => taxonomyRecordKey(row) === id);
      if (match) {
        state.taxonomySelectedId = id;
        replaceRouteHash();
        loadRoutePage();
      }
    });
  });
  $('taxonomySelectAll')?.addEventListener('change', () => {
    const checked = $('taxonomySelectAll').checked;
    state.taxonomySelectedIds.clear();
    document.querySelectorAll('.taxonomy-row').forEach((row) => {
      const id = row.dataset.taxonomyRowId || '';
      const checkbox = row.querySelector('.taxonomy-check');
      if (checkbox) checkbox.checked = checked;
      if (checked && id) state.taxonomySelectedIds.add(id);
    });
  });
  document.querySelectorAll('.taxonomy-row').forEach((row) => {
    row.addEventListener('click', () => {
      state.taxonomySelectedId = row.dataset.taxonomyRowId || '';
      replaceRouteHash();
      loadRoutePage();
    });
    row.querySelector('.taxonomy-check')?.addEventListener('click', (event) => {
      event.stopPropagation();
      const id = row.dataset.taxonomyRowId || '';
      if (!id) return;
      if (event.currentTarget.checked) state.taxonomySelectedIds.add(id);
      else state.taxonomySelectedIds.delete(id);
    });
  });
  document.querySelectorAll('[data-taxonomy-preview-tab]').forEach((button) => {
    button.addEventListener('click', () => {
      state.taxonomyPreviewTab = button.dataset.taxonomyPreviewTab || 'overview';
      document.querySelectorAll('[data-taxonomy-preview-tab]').forEach((tab) => tab.classList.toggle('active', tab === button));
      document.querySelectorAll('[data-taxonomy-preview-section]').forEach((section) => {
        section.classList.toggle('active', section.dataset.taxonomyPreviewSection === state.taxonomyPreviewTab);
      });
      replaceRouteHash();
    });
  });
  document.querySelectorAll('[data-taxonomy-action]').forEach((button) => {
    button.addEventListener('click', async () => {
      const row = state.taxonomyRows.find((item) => taxonomyRecordKey(item) === state.taxonomySelectedId) || data.preview?.row;
      try {
        await applyTaxonomyAction(row, button.dataset.taxonomyAction || 'review');
      } catch (error) {
        const status = $('taxonomyActionStatus');
        if (status) status.textContent = error.message;
      }
    });
  });
  document.querySelectorAll('[data-taxonomy-bulk-action]').forEach((button) => {
    button.addEventListener('click', async () => {
      try {
        await applyBulkTaxonomyAction(button.dataset.taxonomyBulkAction || 'review');
      } catch (error) {
        const status = $('taxonomyBulkStatus');
        if (status) status.textContent = error.message;
      }
    });
  });
  bindTaxonomyKeyboard();
}

async function loadEntityDetail() {
  const entityId = state.entityDetailId || '';
  if (!entityId) {
    $('routePage').innerHTML = pageHeader('Entity Detail', 'No entity selected.');
    return;
  }
  const routeKey = 'entity-detail';
  $('routePage').innerHTML = pageHeader('Entity Detail', 'Loading entity...');
  const token = makeFetchToken();
  try {
    const data = await fetchJson(`/api/entity/${encodeURIComponent(entityId)}`);
    if (!isCurrentFetchToken(token) || state.route !== routeKey) return;
    renderEntityDetailPage(data);
  } catch (error) {
    if (!isCurrentFetchToken(token) || state.route !== routeKey) return;
    $('routePage').innerHTML = pageHeader('Entity Detail', 'Could not load this entity.') + `<div class="empty-state panel"><h2>Entity error</h2><p>${escapeHtml(error.message)}</p></div>`;
  }
}

function openEntityDetail(entityRowId) {
  if (!entityRowId) return;
  state.entityDetailId = entityRowId;
  state.entityDetailTab = 'overview';
  setRoute('entity-detail');
}

function renderEntityDetailPage(data) {
  const h = data.header || {};
  const facts = data.fact_ledger || [];
  const mentions = data.mentions || [];
  const sources = data.sources || [];
  const tabs = data.tabs || ['overview', 'claims', 'sources'];
  const tab = (id, label) => `<button class="secondary ${state.entityDetailTab === id ? 'active' : ''}" data-entity-detail-tab="${escapeHtml(id)}">${escapeHtml(label)}</button>`;
  const factRow = (f) => `
    <tr class="entity-fact-row">
      <td><span class="pill">${escapeHtml(titleCase(f.property || 'claim'))}</span></td>
      <td>${escapeHtml(f.value || '')}</td>
      <td>${Object.entries(f.qualifiers || {}).map(([k, v]) => `<span class="pill">${escapeHtml(k)}=${escapeHtml(String(v))}</span>`).join(' ') || '<span class="muted">—</span>'}</td>
      <td>
        ${f.supporting ? '<span class="status-badge ok">supports</span>' : ''}
        ${f.refuting ? '<span class="status-badge danger">refutes</span>' : ''}
        ${!f.supporting && !f.refuting ? '<span class="muted">—</span>' : ''}
      </td>
      <td><span class="status-badge ${f.review_state === 'accepted' || f.review_state === 'published' ? 'ok' : f.review_state === 'rejected' || f.review_state === 'disputed' ? 'danger' : 'warn'}">${escapeHtml(f.review_state || 'under_review')}</span></td>
      <td><span class="pill ${f.conflict_status === 'disputed' ? 'warn' : ''}">${escapeHtml(titleCase((f.conflict_status || 'under_review').replace(/_/g, ' ')))}</span></td>
    </tr>`;
  const mentionItem = (m) => `<li><strong>${escapeHtml(m.mention_text || m.canonical_name || '')}</strong> <span class="muted">${escapeHtml(m.source_title || '')}</span> ${m.status ? `<span class="pill">${escapeHtml(m.status)}</span>` : ''}</li>`;
  const sourceItem = (s) => `<li><strong>${escapeHtml(s.title || s.source_evidence_id || '')}</strong> <span class="pill">${escapeHtml(titleCase(s.source_kind || 'source'))}</span></li>`;
  $('routePage').innerHTML = `
    ${pageHeader(h.canonical_name || 'Entity Detail', `${escapeHtml(titleCase(h.entity_type || 'entity'))} · ${h.source_count || 0} source(s) · ${h.claim_count || 0} claim(s) · ${h.conflict_count || 0} conflict(s)`)}
    <div class="entity-detail-shell">
      <section class="panel entity-header-card">
        <div class="entity-identity">
          <h2>${escapeHtml(h.canonical_name || '(unnamed)')}</h2>
          <div class="entity-meta">
            <span class="pill">${escapeHtml(titleCase(h.entity_type || 'entity'))}</span>
            ${h.canonical_entity_id ? `<span class="pill">${escapeHtml(h.canonical_entity_id)}</span>` : ''}
            <span class="status-badge ${h.review_state === 'accepted' || h.review_state === 'matched' ? 'ok' : h.review_state === 'rejected' ? 'danger' : 'warn'}">${escapeHtml(titleCase((h.review_state || 'unresolved').replace(/_/g, ' ')))}</span>
          </div>
          ${h.aliases && h.aliases.length ? `<div class="entity-aliases"><span class="muted">Aliases:</span> ${h.aliases.map((a) => `<span class="pill">${escapeHtml(a)}</span>`).join(' ')}</div>` : ''}
        </div>
        <div class="entity-counts">
          <div><strong>${h.source_count || 0}</strong><span class="muted">sources</span></div>
          <div><strong>${h.claim_count || 0}</strong><span class="muted">claims</span></div>
          <div><strong>${h.supporting_count || 0}</strong><span class="muted">supporting</span></div>
          <div><strong>${h.refuting_count || 0}</strong><span class="muted">refuting</span></div>
          <div><strong>${h.conflict_count || 0}</strong><span class="muted">conflicts</span></div>
        </div>
      </section>
      <nav class="entity-detail-tabs">${tabs.map((id) => tab(id, titleCase(id))).join('')}</nav>
      <section class="panel entity-fact-ledger" data-entity-detail-section="claims">
        <h3>Fact ledger</h3>
        ${facts.length ? `<table class="ledger-table"><thead><tr><th>Property</th><th>Value</th><th>Qualifiers</th><th>Relation</th><th>Review</th><th>Conflict</th></tr></thead><tbody>${facts.map(factRow).join('')}</tbody></table>` : '<p class="muted">No claims touch this entity yet.</p>'}
      </section>
      <section class="panel entity-side" data-entity-detail-section="overview">
        <h3>Mentions</h3>
        ${mentions.length ? `<ul class="entity-mention-list">${mentions.map(mentionItem).join('')}</ul>` : '<p class="muted">No mentions recorded.</p>'}
        <h3>Sources</h3>
        ${sources.length ? `<ul class="entity-source-list">${sources.map(sourceItem).join('')}</ul>` : '<p class="muted">No sources linked.</p>'}
      </section>
    </div>`;
  document.querySelectorAll('[data-entity-detail-tab]').forEach((button) => {
    button.addEventListener('click', () => {
      state.entityDetailTab = button.dataset.entityDetailTab || 'overview';
      replaceRouteHash();
      document.querySelectorAll('[data-entity-detail-tab]').forEach((b) => b.classList.toggle('active', b === button));
    });
  });
}

async function loadConflictDetail() {
  const clusterId = state.conflictClusterId || '';
  if (!clusterId) {
    $('routePage').innerHTML = pageHeader('Conflict Resolution', 'No conflict selected.');
    return;
  }
  const routeKey = 'conflict-detail';
  $('routePage').innerHTML = pageHeader('Conflict Resolution', 'Loading conflict cluster...');
  const token = makeFetchToken();
  try {
    const data = await fetchJson(`/api/conflicts/${encodeURIComponent(clusterId)}`);
    if (!isCurrentFetchToken(token) || state.route !== routeKey) return;
    renderConflictDetailPage(data);
  } catch (error) {
    if (!isCurrentFetchToken(token) || state.route !== routeKey) return;
    $('routePage').innerHTML = pageHeader('Conflict Resolution', 'Could not load this conflict.') + `<div class="empty-state panel"><h2>Conflict error</h2><p>${escapeHtml(error.message)}</p></div>`;
  }
}

function openConflictDetail(clusterId) {
  if (!clusterId) return;
  state.conflictClusterId = clusterId;
  state.conflictResolution = 'leave_unresolved';
  state.conflictReasonCode = 'unresolved';
  state.conflictPreferredClaimId = '';
  setRoute('conflict-detail');
}

async function persistConflictResolution(row) {
  const status = $('conflictActionStatus');
  try {
    if (status) status.textContent = 'Recording resolution...';
    const result = await postJson('/api/conflicts/resolve', {
      cluster_id: state.conflictClusterId,
      resolution: state.conflictResolution || 'leave_unresolved',
      reason_code: state.conflictReasonCode || 'unresolved',
      preferred_claim_id: state.conflictPreferredClaimId || '',
      note: $('conflictReviewerNote')?.value || '',
      actor: REVIEW_UI_ACTOR,
      expected_version: expectedVersionForRow(row),
    });
    if (status) status.textContent = `Resolution recorded: ${result.resolution}${result.promoted ? ' (preferred promoted)' : ''}.`;
  } catch (error) {
    if (status) status.textContent = error.message;
  }
}

function renderConflictDetailPage(data) {
  const assertions = data.assertions || [];
  const options = data.resolution_options || [];
  const reasons = data.reason_codes || [];
  const prior = data.prior_decisions || [];
  const card = (a) => `
    <article class="conflict-assertion-card ${a.review_state === 'accepted' ? 'preferred' : ''} ${a.review_state === 'rejected' || a.review_state === 'disputed' ? 'disputed' : ''}">
      <header><strong>${escapeHtml(a.value || '')}</strong> <span class="status-badge ${a.contradiction_state === 'disputed' ? 'danger' : a.contradiction_state === 'supported' ? 'ok' : 'warn'}">${escapeHtml(titleCase((a.contradiction_state || 'under_review').replace(/_/g, ' ')))}</span></header>
      <dl>
        <dt>Source</dt><dd>${escapeHtml(a.source_title || a.source_evidence_id || '—')} <span class="pill">${escapeHtml(titleCase(a.source_kind || 'source'))}</span></dd>
        <dt>Effective date</dt><dd>${escapeHtml(a.effective_date || '—')}</dd>
        <dt>Relation</dt><dd>${escapeHtml(a.evidence_relation || '—')}</dd>
        <dt>Qualifiers</dt><dd>${Object.entries(a.qualifiers || {}).map(([k, v]) => `<span class="pill">${escapeHtml(k)}=${escapeHtml(String(v))}</span>`).join(' ') || '—'}</dd>
      </dl>
      <label class="conflict-preferred-pick"><input type="radio" name="conflict-preferred" value="${escapeHtml(a.claim_id || '')}" ${state.conflictPreferredClaimId === a.claim_id ? 'checked' : ''}> Prefer this assertion</label>
    </article>`;
  $('routePage').innerHTML = `
    ${pageHeader(`Conflict: ${data.subject || data.cluster_id}`, `${assertions.length} assertion(s) · resolves without deleting any assertion`)}
    <div class="conflict-detail-shell">
      <section class="panel conflict-assertions">
        <h3>Assertions (vertical list — no assertion is deleted by resolving)</h3>
        ${assertions.length ? assertions.map(card).join('') : '<p class="muted">No assertions in this cluster.</p>'}
        ${prior.length ? `<details class="conflict-prior"><summary>Prior reviewer decisions (${prior.length})</summary><ul>${prior.map((p) => `<li>${escapeHtml(p.claim_id || '')} — ${escapeHtml(p.review_state)} / ${escapeHtml(p.contradiction_state)}</li>`).join('')}</ul></details>` : ''}
      </section>
      <section class="panel conflict-resolution-form">
        <h3>Resolve</h3>
        <label>Resolution</label>
        <select id="conflictResolutionSelect">
          ${options.map((o) => `<option value="${escapeHtml(o)}" ${state.conflictResolution === o ? 'selected' : ''}>${escapeHtml(titleCase(o.replace(/_/g, ' ')))}</option>`).join('')}
        </select>
        <label>Reason code</label>
        <select id="conflictReasonSelect">
          ${reasons.map((r) => `<option value="${escapeHtml(r)}" ${state.conflictReasonCode === r ? 'selected' : ''}>${escapeHtml(titleCase(r.replace(/_/g, ' ')))}</option>`).join('')}
        </select>
        <label>Reviewer note</label>
        <textarea id="conflictReviewerNote" rows="3" placeholder="Why this resolution?"></textarea>
        <button id="conflictResolveBtn" class="primary">Record resolution</button>
        <p id="conflictActionStatus" class="muted"></p>
      </section>
    </div>`;
  const resSel = $('conflictResolutionSelect');
  const reasonSel = $('conflictReasonSelect');
  if (resSel) resSel.addEventListener('change', () => { state.conflictResolution = resSel.value; replaceRouteHash(); });
  if (reasonSel) reasonSel.addEventListener('change', () => { state.conflictReasonCode = reasonSel.value; replaceRouteHash(); });
  document.querySelectorAll('input[name="conflict-preferred"]').forEach((radio) => {
    radio.addEventListener('change', () => { state.conflictPreferredClaimId = radio.value; });
  });
  const btn = $('conflictResolveBtn');
  if (btn) btn.addEventListener('click', () => persistConflictResolution({ optimistic_version: '', updated_at: '' }));
}

function routeProjectId() {
  return state.project || state.home?.active_project?.project_id || '__active__';
}

function statusBadge(value) {
  const text = String(value || 'unknown');
  return `<span class="status-badge ${publishingStateClass(text)}">${escapeHtml(titleCase(text.replace(/_/g, ' ')))}</span>`;
}

function renderMiniSourceList(sources) {
  const rows = sources || [];
  if (!rows.length) return '<p class="muted">No sources in this view.</p>';
  return `<div class="mini-source-list">${rows.slice(0, 40).map((row) => `
    <button class="mini-source-row object-row" type="button" data-id="${escapeHtml(row.evidence_id || row.source_evidence_id || '')}">
      <strong>${escapeHtml(row.title || row.canonical_url || row.evidence_id || row.source_evidence_id || 'Source')}</strong>
      <span>${escapeHtml([row.source_label || row.source_kind, row.domain, fmtDate(row.last_ingested_at || row.updated_at)].filter(Boolean).join(' · '))}</span>
    </button>
  `).join('')}</div>`;
}

function optionList(items, active, allLabel) {
  const rows = items || [];
  return `<option value="">${escapeHtml(allLabel)}</option>${rows.map((item) => {
    const id = item.id ?? item.value ?? '';
    const label = item.label || titleCase(String(id).replace(/_/g, ' '));
    const count = item.count !== undefined ? ` (${item.count})` : '';
    return `<option value="${escapeHtml(id)}" ${String(active || '') === String(id) ? 'selected' : ''}>${escapeHtml(label)}${escapeHtml(count)}</option>`;
  }).join('')}`;
}

function timelineDateTypeOptions(data) {
  const rows = data.date_types || [
    { id: 'event', label: 'Event date' },
    { id: 'source', label: 'Source date' },
    { id: 'capture', label: 'Capture/update date' },
  ];
  return rows.map((item) => `<option value="${escapeHtml(item.id)}" ${state.timelineDateType === item.id ? 'selected' : ''}>${escapeHtml(item.label)}</option>`).join('');
}

function setTimelineFilterStateFromQuery(query) {
  state.timelineLane = query.lane || '';
  state.timelineDateType = query.date_type || 'event';
  state.timelineDateFrom = query.date_from || '';
  state.timelineDateTo = query.date_to || '';
  state.timelineConfidence = query.confidence || '';
  state.timelineReviewState = query.review_state || '';
  state.timelineSourceKind = query.source_kind || '';
  state.timelineSavedView = query.saved_view || '';
}

function clearTimelineFilterState() {
  state.timelineLane = '';
  state.timelineDateType = 'event';
  state.timelineDateFrom = '';
  state.timelineDateTo = '';
  state.timelineConfidence = '';
  state.timelineReviewState = '';
  state.timelineSourceKind = '';
  state.timelineSavedView = '';
}

async function loadTimelinePage() {
  const projectId = routeProjectId();
  const params = new URLSearchParams({ limit: state.limit });
  if (state.q) params.set('q', state.q);
  if (state.timelineLane) params.set('lane', state.timelineLane);
  if (state.timelineDateType && state.timelineDateType !== 'event') params.set('date_type', state.timelineDateType);
  if (state.timelineDateFrom) params.set('date_from', state.timelineDateFrom);
  if (state.timelineDateTo) params.set('date_to', state.timelineDateTo);
  if (state.timelineConfidence) params.set('confidence', state.timelineConfidence);
  if (state.timelineReviewState) params.set('review_state', state.timelineReviewState);
  if (state.timelineSourceKind) params.set('source_kind', state.timelineSourceKind);
  if (state.timelineSavedView) params.set('saved_view', state.timelineSavedView);
  $('routePage').innerHTML = pageHeader('Timeline', 'Loading chronological evidence and claim events...');
  const token = makeFetchToken();
  try {
    const data = await fetchJson(`/api/project/${encodeURIComponent(projectId)}/timeline?${params.toString()}`);
    if (!isCurrentFetchToken(token) || state.route !== 'timeline') return;
    renderTimelinePage(data);
  } catch (error) {
    if (!isCurrentFetchToken(token) || state.route !== 'timeline') return;
    $('routePage').innerHTML = pageHeader('Timeline', 'Could not load timeline.') + `<div class="empty-state panel"><h2>Timeline error</h2><p>${escapeHtml(error.message)}</p></div>`;
  }
}

function renderTimelinePage(data) {
  const items = data.items || data.results?.items || [];
  const summary = data.summary || {};
  const query = data.query || {};
  setTimelineFilterStateFromQuery(query);
  const facets = data.facets || {};
  $('routePage').innerHTML = `
    ${pageHeader('Timeline', `${escapeHtml(data.scope?.project || 'Active project')} · ${escapeHtml(summary.items || 0)} event(s)`, `
      <button class="secondary" type="button" data-route-target="compare" data-project="${escapeHtml(data.scope?.project || state.project || '')}">Compare</button>
      <button type="button" data-route-target="draft" data-project="${escapeHtml(data.scope?.project || state.project || '')}">Draft</button>
    `)}
    ${metricCards([
      { label: 'Events', value: summary.items || items.length },
      { label: 'Captures', value: summary.captures || 0 },
      { label: 'Claims', value: summary.claims || 0 },
      { label: 'Conflicts', value: summary.conflicts || 0 },
    ])}
    <section class="timeline-controls panel">
      <div class="timeline-saved-views">
        ${(data.saved_views || []).map((view) => `<button class="secondary ${state.timelineSavedView === view.id ? 'active' : ''}" type="button" data-timeline-saved-view="${escapeHtml(view.id)}">${escapeHtml(view.label || view.id)}</button>`).join('')}
      </div>
      <div class="timeline-filter-grid">
        <label><span>Date type</span><select data-timeline-filter="date_type">${timelineDateTypeOptions(data)}</select></label>
        <label><span>From</span><input data-timeline-filter="date_from" type="date" value="${escapeHtml(state.timelineDateFrom)}"></label>
        <label><span>To</span><input data-timeline-filter="date_to" type="date" value="${escapeHtml(state.timelineDateTo)}"></label>
        <label><span>Lane</span><select data-timeline-filter="lane">${optionList(facets.lanes || data.lanes, state.timelineLane, 'All lanes')}</select></label>
        <label><span>Confidence</span><select data-timeline-filter="confidence">${optionList(facets.confidence, state.timelineConfidence, 'All confidence states')}</select></label>
        <label><span>Review state</span><select data-timeline-filter="review_state">${optionList(facets.review_states, state.timelineReviewState, 'All review states')}</select></label>
        <label><span>Source kind</span><select data-timeline-filter="source_kind">${optionList(facets.source_kinds, state.timelineSourceKind, 'All source kinds')}</select></label>
        <button class="secondary" type="button" id="timelineClearFilters">Clear</button>
      </div>
      <p class="muted">Date filters use the selected existing date field and leave unknown dates out only when a range is active.</p>
    </section>
    <section class="timeline-shell panel">
      <div class="timeline-lanes">
        ${(data.lanes || []).map((lane) => `<span class="pill">${escapeHtml(lane.label)} ${escapeHtml(lane.count || 0)}</span>`).join('')}
      </div>
      <div class="timeline-list">
        ${items.length ? items.map((item) => `
          <article class="timeline-item ${escapeHtml(item.conflict_state || '')}">
            <time>${escapeHtml(fmtDate(item.selected_date || item.date) || 'undated')}</time>
            <div>
              <strong>${escapeHtml(item.summary || item.item_id || 'Timeline item')}</strong>
              <p>${escapeHtml([titleCase(item.event_type || ''), item.selected_date_type ? `${titleCase(item.selected_date_type)} date` : '', item.date_precision, item.review_state, item.conflict_state, item.confidence_state, item.source_label].filter(Boolean).join(' · '))}</p>
              <div class="tag-line">
                ${(item.entities || []).slice(0, 4).map((value) => `<span class="pill">${escapeHtml(value)}</span>`).join('')}
                ${(item.source_ids || []).slice(0, 2).map((value) => `<button class="text-button" type="button" data-id="${escapeHtml(value)}">${escapeHtml(value)}</button>`).join('')}
              </div>
            </div>
          </article>
        `).join('') : '<div class="empty-state"><h2>No timeline events</h2><p>No captures or claims match this project.</p></div>'}
      </div>
    </section>
  `;
  bindObjectRows();
  document.querySelectorAll('[data-route-target]').forEach((button) => button.addEventListener('click', () => {
    state.project = button.dataset.project || state.project;
    setRoute(button.dataset.routeTarget || 'projects');
  }));
  document.querySelectorAll('[data-timeline-filter]').forEach((control) => control.addEventListener('change', () => {
    const key = control.dataset.timelineFilter;
    if (key === 'lane') state.timelineLane = control.value;
    if (key === 'date_type') state.timelineDateType = control.value || 'event';
    if (key === 'date_from') state.timelineDateFrom = control.value;
    if (key === 'date_to') state.timelineDateTo = control.value;
    if (key === 'confidence') state.timelineConfidence = control.value;
    if (key === 'review_state') state.timelineReviewState = control.value;
    if (key === 'source_kind') state.timelineSourceKind = control.value;
    state.timelineSavedView = '';
    replaceRouteHash();
    loadTimelinePage();
  }));
  document.querySelectorAll('[data-timeline-saved-view]').forEach((button) => button.addEventListener('click', () => {
    const view = (data.saved_views || []).find((item) => item.id === button.dataset.timelineSavedView);
    clearTimelineFilterState();
    state.timelineSavedView = view?.id || '';
    const filters = view?.filters || {};
    state.timelineLane = filters.lane || '';
    state.timelineDateType = filters.date_type || 'event';
    state.timelineConfidence = filters.confidence || '';
    state.timelineReviewState = filters.review_state || '';
    state.timelineSourceKind = filters.source_kind || '';
    replaceRouteHash();
    loadTimelinePage();
  }));
  $('timelineClearFilters')?.addEventListener('click', () => {
    clearTimelineFilterState();
    replaceRouteHash();
    loadTimelinePage();
  });
}

async function loadComparePage() {
  const projectId = routeProjectId();
  $('routePage').innerHTML = pageHeader('Compare', 'Loading comparison matrix...');
  const token = makeFetchToken();
  try {
    const data = await fetchJson(`/api/project/${encodeURIComponent(projectId)}/compare/${encodeURIComponent(state.compareViewId || 'claims')}?limit=${encodeURIComponent(state.limit)}`);
    if (!isCurrentFetchToken(token) || state.route !== 'compare') return;
    renderComparePage(data);
  } catch (error) {
    if (!isCurrentFetchToken(token) || state.route !== 'compare') return;
    $('routePage').innerHTML = pageHeader('Compare', 'Could not load comparison matrix.') + `<div class="empty-state panel"><h2>Compare error</h2><p>${escapeHtml(error.message)}</p></div>`;
  }
}

function compareCellKey(rowIndex, cellIndex) {
  return `${rowIndex}:${cellIndex}`;
}

function compareStateClass(value) {
  const text = String(value || '').toLowerCase();
  if (text === 'reproduced' || text === 'independently-measured') return 'ok';
  if (text === 'vendor-reported') return 'info';
  if (text === 'disputed' || text === 'stale' || text === 'na') return 'danger';
  return 'warn';
}

function compareStateBadge(value) {
  const text = String(value || 'missing');
  return `<span class="status-badge ${compareStateClass(text)}">${escapeHtml(titleCase(text.replace(/-/g, ' ')))}</span>`;
}

function compareCellEntries(rows, columns) {
  const entries = [];
  rows.forEach((row, rowIndex) => {
    (row.cells || []).forEach((cell, cellIndex) => {
      entries.push({
        key: compareCellKey(rowIndex, cellIndex),
        row,
        column: columns[cellIndex] || { id: cell.entity, label: cell.entity },
        cell,
      });
    });
  });
  return entries;
}

function renderCompareEvidenceItem(item) {
  const meta = [item.kind, item.status, item.anchor_type, item.anchor_label, fmtDate(item.updated_at || item.captured_at)].filter(Boolean).join(' - ');
  return `
    <article class="compare-evidence-item">
      <header>
        <strong>${escapeHtml(item.label || item.kind || 'Evidence')}</strong>
        ${item.object_id ? `<code>${escapeHtml(item.object_id)}</code>` : ''}
      </header>
      ${meta ? `<p class="muted">${escapeHtml(meta)}</p>` : ''}
      ${item.detail ? `<p>${escapeHtml(item.detail)}</p>` : '<p class="muted">No detail text captured for this evidence record.</p>'}
      <div class="tag-line">
        ${item.source_evidence_id ? `<button class="text-button" type="button" data-id="${escapeHtml(item.source_evidence_id)}">Open source</button>` : ''}
        ${item.canonical_url ? `<span class="pill">${escapeHtml(item.canonical_url)}</span>` : ''}
      </div>
    </article>
  `;
}

function renderCompareAssertion(assertion) {
  const evidence = assertion.evidence || [];
  return `
    <article class="compare-assertion">
      <header>
        <strong>${escapeHtml(assertion.value || assertion.claim_text || assertion.claim_id || 'Assertion')}</strong>
        ${compareStateBadge(assertion.review_state || 'draft')}
      </header>
      <p>${escapeHtml(assertion.claim_text || '')}</p>
      <div class="tag-line">
        ${assertion.evidence_relation ? `<span class="pill">${escapeHtml(assertion.evidence_relation)}</span>` : ''}
        ${assertion.contradiction_state ? `<span class="pill">${escapeHtml(assertion.contradiction_state)}</span>` : ''}
        ${assertion.source_label ? `<span class="pill">${escapeHtml(assertion.source_label)}</span>` : ''}
        ${assertion.source_evidence_id ? `<button class="text-button" type="button" data-id="${escapeHtml(assertion.source_evidence_id)}">Open source</button>` : ''}
      </div>
      ${evidence.length ? `<div class="compare-assertion-evidence">${evidence.map(renderCompareEvidenceItem).join('')}</div>` : '<p class="muted">No exact evidence records are linked to this assertion.</p>'}
    </article>
  `;
}

function renderCompareEvidenceDrawer(entry) {
  if (!entry) {
    return `
      <aside class="compare-evidence-drawer">
        <div class="empty-state">
          <h2>Evidence drawer</h2>
          <p>Select a populated comparison cell to inspect linked claims, exact evidence records, and source anchors.</p>
        </div>
      </aside>
    `;
  }
  const cell = entry.cell || {};
  const assertions = cell.assertions || [];
  const evidence = cell.evidence || [];
  const sourceIds = cell.source_ids || [];
  return `
    <aside class="compare-evidence-drawer" id="compareEvidenceDrawer">
      <div class="pane-title">
        <h2>${escapeHtml(entry.column?.label || cell.entity || 'Entity')}</h2>
        ${compareStateBadge(cell.state)}
      </div>
      <p class="muted">${escapeHtml(titleCase(entry.row?.property || 'property'))}</p>
      <strong>${escapeHtml(cell.value || 'No value captured')}</strong>
      <p>${escapeHtml(cell.state_reason || '')}</p>
      <div class="tag-line">
        <span class="pill">${escapeHtml(assertions.length)} assertion(s)</span>
        <span class="pill">${escapeHtml(evidence.length)} selected evidence record(s)</span>
        ${sourceIds.map((sourceId) => `<button class="text-button" type="button" data-id="${escapeHtml(sourceId)}">Open source</button>`).join('')}
      </div>
      <section>
        <h3>Selected Evidence</h3>
        ${evidence.length ? evidence.map(renderCompareEvidenceItem).join('') : '<p class="muted">This cell has no exact source, selection, or fact evidence linked to the selected assertion.</p>'}
      </section>
      <section>
        <h3>Assertions</h3>
        ${assertions.length ? assertions.map(renderCompareAssertion).join('') : '<p class="muted">No assertion exists for this entity/property pair.</p>'}
      </section>
    </aside>
  `;
}

function renderComparePage(data) {
  const columns = data.columns || [];
  const rows = data.rows || [];
  state.compareData = data;
  const entries = compareCellEntries(rows, columns);
  const preferredEntry = entries.find((entry) => entry.key === state.compareSelectedCellKey)
    || entries.find((entry) => entry.cell?.claim_id || Number(entry.cell?.assertion_count || 0) > 0)
    || null;
  state.compareSelectedCellKey = preferredEntry?.key || '';
  $('routePage').innerHTML = `
    ${pageHeader('Compare', `${escapeHtml(columns.length)} entities · ${escapeHtml(rows.length)} properties`)}
    <section class="compare-shell">
      <div class="compare-legend">${(data.legend || []).map((item) => `<span class="pill">${escapeHtml(item)}</span>`).join('')}</div>
      <div class="compare-workspace">
        <div class="compare-table-wrap">
          <table class="ledger-table compare-table">
            <thead><tr><th>Property</th>${columns.map((col) => `<th>${escapeHtml(col.label || col.id)}</th>`).join('')}</tr></thead>
            <tbody>
              ${rows.length ? rows.map((row, rowIndex) => `
                <tr>
                  <th>${escapeHtml(titleCase(row.property || 'property'))}</th>
                  ${(row.cells || []).map((cell, cellIndex) => {
                    const key = compareCellKey(rowIndex, cellIndex);
                    const populated = cell.claim_id || Number(cell.assertion_count || 0) > 0;
                    return `
                      <td class="compare-cell ${state.compareSelectedCellKey === key ? 'selected' : ''}" data-compare-cell="${escapeHtml(key)}">
                        <div class="compare-cell-head">${compareStateBadge(cell.state)}<span>${escapeHtml(cell.assertion_count || 0)} assertion(s)</span></div>
                        <strong>${escapeHtml(cell.value || 'No value')}</strong>
                        <p>${escapeHtml(cell.state_reason || '')}</p>
                        <div class="tag-line">
                          ${cell.source_evidence_id ? `<button class="text-button" type="button" data-id="${escapeHtml(cell.source_evidence_id)}">Source</button>` : '<span class="muted">No source</span>'}
                          ${populated ? `<button class="text-button" type="button" data-compare-inspect="${escapeHtml(key)}">Inspect</button>` : ''}
                        </div>
                      </td>
                    `;
                  }).join('')}
                </tr>
              `).join('') : '<tr><td colspan="99">No scoped claims available for comparison.</td></tr>'}
            </tbody>
          </table>
        </div>
        ${renderCompareEvidenceDrawer(preferredEntry)}
      </div>
    </section>
  `;
  document.querySelectorAll('[data-compare-inspect], .compare-cell[data-compare-cell]').forEach((node) => node.addEventListener('click', (event) => {
    if (node.dataset.compareInspect) event.stopPropagation();
    if (event.target.closest('[data-id]')) return;
    const key = node.dataset.compareInspect || node.dataset.compareCell || '';
    const entry = entries.find((item) => item.key === key);
    if (!entry || (!entry.cell?.claim_id && Number(entry.cell?.assertion_count || 0) <= 0)) return;
    state.compareSelectedCellKey = key;
    renderComparePage(data);
  }));
  bindObjectRows();
}

async function loadTopicDetailPage() {
  if (!state.topicDetailId) {
    $('routePage').innerHTML = pageHeader('Topic Detail', 'No topic selected.') + '<div class="empty-state panel"><h2>Select a topic</h2><p>Open a taxonomy topic to inspect source coverage, claims, entities, and timeline events.</p></div>';
    return;
  }
  const params = new URLSearchParams();
  if (state.project) params.set('project', state.project);
  $('routePage').innerHTML = pageHeader('Topic Detail', 'Loading topic...');
  const token = makeFetchToken();
  try {
    const data = await fetchJson(`/api/topic/${encodeURIComponent(state.topicDetailId)}?${params.toString()}`);
    if (!isCurrentFetchToken(token) || state.route !== 'topic-detail') return;
    renderTopicDetailPage(data);
  } catch (error) {
    if (!isCurrentFetchToken(token) || state.route !== 'topic-detail') return;
    $('routePage').innerHTML = pageHeader('Topic Detail', 'Could not load topic.') + `<div class="empty-state panel"><h2>Topic error</h2><p>${escapeHtml(error.message)}</p></div>`;
  }
}

function renderTopicDetailPage(data) {
  const h = data.header || {};
  const tabs = data.tabs || ['overview'];
  const active = tabs.includes(state.topicDetailTab) ? state.topicDetailTab : 'overview';
  const tabButton = (id) => `<button class="secondary ${active === id ? 'active' : ''}" type="button" data-topic-tab="${escapeHtml(id)}">${escapeHtml(titleCase(id))}</button>`;
  $('routePage').innerHTML = `
    ${pageHeader(h.label || 'Topic Detail', `${escapeHtml(h.source_count || 0)} sources · ${escapeHtml(h.claim_count || 0)} claims · ${escapeHtml(h.entity_count || 0)} entities`)}
    <section class="synthesis-detail-shell">
      <article class="panel detail-card">
        <h2>${escapeHtml(h.label || 'Topic')}</h2>
        <p>${escapeHtml(h.definition || '')}</p>
        <div class="tag-line">${statusBadge(h.review_state)}<span class="pill">${escapeHtml(h.topic_id || '')}</span></div>
      </article>
      <nav class="entity-detail-tabs">${tabs.map(tabButton).join('')}</nav>
      <section class="panel detail-card" data-topic-section="overview">
        <h3>Coverage</h3>
        <div class="coverage-rule-list">
          ${(data.coverage?.sources || []).map((item) => `<div class="coverage-rule"><strong>${escapeHtml(item.label)}</strong><em>${escapeHtml(item.count)}</em></div>`).join('')}
        </div>
      </section>
      <section class="panel detail-card" data-topic-section="evidence"><h3>Evidence</h3>${renderMiniSourceList(data.sources || [])}</section>
      <section class="panel detail-card" data-topic-section="claims"><h3>Claims</h3>${(data.claims || []).map((claim) => `<p><strong>${escapeHtml(claim.claim_text || '')}</strong><br>${statusBadge(claim.review_state)} ${statusBadge(claim.contradiction_state)}</p>`).join('') || '<p class="muted">No claims.</p>'}</section>
      <section class="panel detail-card" data-topic-section="entities"><h3>Entities</h3><div class="tag-line">${(data.entities || []).map((entity) => `<span class="pill">${escapeHtml(entity)}</span>`).join('') || '<span class="muted">No entities.</span>'}</div></section>
    </section>
  `;
  document.querySelectorAll('[data-topic-tab]').forEach((button) => button.addEventListener('click', () => {
    state.topicDetailTab = button.dataset.topicTab || 'overview';
    replaceRouteHash();
  }));
  bindObjectRows();
}

async function loadBenchmarkPage() {
  const params = new URLSearchParams();
  if (state.project) params.set('project', state.project);
  $('routePage').innerHTML = pageHeader('Benchmark Detail', 'Loading benchmark...');
  const token = makeFetchToken();
  try {
    const data = await fetchJson(`/api/benchmark/${encodeURIComponent(state.benchmarkId || 'benchmark')}?${params.toString()}`);
    if (!isCurrentFetchToken(token) || state.route !== 'benchmark') return;
    renderBenchmarkPage(data);
  } catch (error) {
    if (!isCurrentFetchToken(token) || state.route !== 'benchmark') return;
    $('routePage').innerHTML = pageHeader('Benchmark Detail', 'Could not load benchmark.') + `<div class="empty-state panel"><h2>Benchmark error</h2><p>${escapeHtml(error.message)}</p></div>`;
  }
}

function renderBenchmarkPage(data) {
  const h = data.header || {};
  const rows = data.results || [];
  $('routePage').innerHTML = `
    ${pageHeader(h.label || 'Benchmark Detail', `${escapeHtml(rows.length)} result(s) · ${escapeHtml(h.methodology_state || '')}`)}
    <section class="benchmark-shell panel">
      <div class="review-layer-stack">
        ${(data.checks || []).map((check) => `<div><span>${escapeHtml(check.label)}</span><strong>${escapeHtml(check.state)}</strong></div>`).join('')}
      </div>
      <table class="ledger-table">
        <thead><tr><th>Model</th><th>Metric</th><th>Value</th><th>Config</th><th>Ranking</th><th>Evidence</th></tr></thead>
        <tbody>
          ${rows.length ? rows.map((row) => `<tr><td>${escapeHtml(row.model || '')}</td><td>${escapeHtml(row.metric || '')}</td><td>${escapeHtml(row.value || '')}</td><td><code>${escapeHtml(row.config_key || '')}</code></td><td>${statusBadge(row.default_ranked ? 'ranked' : 'incomparable')}</td><td>${row.source_evidence_id ? `<button class="text-button" data-id="${escapeHtml(row.source_evidence_id)}">Open</button>` : '<span class="muted">None</span>'}</td></tr>`).join('') : '<tr><td colspan="6">No benchmark claims match this view.</td></tr>'}
        </tbody>
      </table>
    </section>
  `;
  bindObjectRows();
}

async function loadDraftPage() {
  const projectId = routeProjectId();
  $('routePage').innerHTML = pageHeader('Draft Editor', 'Loading draft...');
  const token = makeFetchToken();
  try {
    const data = await fetchJson(`/api/project/${encodeURIComponent(projectId)}/draft/${encodeURIComponent(state.draftId || 'working-draft')}`);
    if (!isCurrentFetchToken(token) || state.route !== 'draft') return;
    renderDraftPage(data);
  } catch (error) {
    if (!isCurrentFetchToken(token) || state.route !== 'draft') return;
    $('routePage').innerHTML = pageHeader('Draft Editor', 'Could not load draft.') + `<div class="empty-state panel"><h2>Draft error</h2><p>${escapeHtml(error.message)}</p></div>`;
  }
}

function renderDraftPage(data) {
  const paragraphs = data.paragraphs || [];
  $('routePage').innerHTML = `
    ${pageHeader(data.header?.title || 'Draft Editor', `Revision ${escapeHtml(data.header?.revision || '')} · ${escapeHtml((data.references || []).length)} references`)}
    <section class="draft-shell">
      <aside class="panel draft-outline">${(data.outline || []).map((item) => `<button class="saved-item" type="button"><span>${escapeHtml(item.label)}</span><strong>${escapeHtml(item.status)}</strong></button>`).join('')}</aside>
      <section class="panel draft-editor-pane">
        ${paragraphs.map((paragraph) => `
          <article class="draft-paragraph ${paragraph.support_state === 'unsupported' ? 'unsupported' : ''}">
            <p>${escapeHtml(paragraph.text || '')}</p>
            <div class="tag-line">${statusBadge(paragraph.support_state)} ${(paragraph.references || []).map((ref) => `<span class="pill">${escapeHtml(ref.object_type)}:${escapeHtml(ref.object_id)}</span>`).join('')}</div>
          </article>
        `).join('') || '<div class="empty-state"><h2>No draft paragraphs</h2><p>No claims are available for this draft.</p></div>'}
      </section>
      <aside class="panel draft-evidence-rail">${renderMiniSourceList(data.evidence_rail || [])}</aside>
    </section>
  `;
  bindObjectRows();
}

function openPublicationDetail(row) {
  if (!row) return;
  state.publicationBundleId = publishingBundleKey(row);
  state.publicationDetailTab = 'overview';
  setRoute('publication-detail');
}

async function loadPublicationDetailPage() {
  if (!state.publicationBundleId) {
    $('routePage').innerHTML = pageHeader('Publication Review', 'No publication bundle selected.');
    return;
  }
  $('routePage').innerHTML = pageHeader('Publication Review', 'Loading publication snapshot detail...');
  const token = makeFetchToken();
  try {
    const data = await fetchJson(`/api/publishing/${encodeURIComponent(state.publicationBundleId)}`);
    if (!isCurrentFetchToken(token) || state.route !== 'publication-detail') return;
    renderPublicationDetailPage(data);
  } catch (error) {
    if (!isCurrentFetchToken(token) || state.route !== 'publication-detail') return;
    $('routePage').innerHTML = pageHeader('Publication Review', 'Could not load publication detail.') + `<div class="empty-state panel"><h2>Publication error</h2><p>${escapeHtml(error.message)}</p></div>`;
  }
}

async function persistPublicationDetailAction(action, data) {
  const bundle = data.bundle || {};
  const snapshot = data.snapshot || {};
  const endpoint = {
    create_snapshot: '/api/publishing/snapshot',
    request_review: '/api/publishing/request-review',
    approve_snapshot: '/api/publishing/approve',
    request_changes: '/api/publishing/request-changes',
    publish_snapshot: '/api/publishing/publish',
    supersede_release: '/api/publishing/supersede',
  }[action];
  if (!endpoint) return;
  const status = $('publicationDetailStatus');
  try {
    if (status) status.textContent = `${titleCase(action)}...`;
    await postJson(endpoint, {
      bundle_id: publishingBundleKey(bundle),
      snapshot_id: snapshot.snapshot_id || '',
      actor: REVIEW_UI_ACTOR,
      expected_version: snapshot.updated_at || bundle.optimistic_version || '',
    });
    if (status) status.textContent = `${titleCase(action)} recorded.`;
    await loadPublicationDetailPage();
  } catch (error) {
    if (status) status.textContent = error.message;
  }
}

function renderPublicationDetailPage(data) {
  const bundle = data.bundle || {};
  const snapshot = data.snapshot || {};
  const tabs = data.tabs || ['overview'];
  const active = tabs.includes(state.publicationDetailTab) ? state.publicationDetailTab : 'overview';
  const tabButton = (id) => `<button class="secondary ${active === id ? 'active' : ''}" type="button" data-publication-tab="${escapeHtml(id)}">${escapeHtml(titleCase(id))}</button>`;
  $('routePage').innerHTML = `
    ${pageHeader(bundle.title || 'Publication Review', `${escapeHtml(bundle.display_state || 'draft')} · ${escapeHtml(data.manifest_hash || bundle.manifest_hash || '')}`, `
      <button class="secondary" type="button" data-route-target="publishing">Back to publishing</button>
    `)}
    <section class="publication-detail-shell">
      <header class="panel publication-detail-head">
        <div>
          <h2>${escapeHtml(bundle.package_type_label || bundle.package_type || 'Package')}</h2>
          <p>${escapeHtml(bundle.target || '')}</p>
          <div class="tag-line">${statusBadge(bundle.display_state)}${statusBadge(snapshot.review_state || 'no_snapshot')}<span class="pill">${escapeHtml(snapshot.snapshot_id || 'No snapshot')}</span></div>
        </div>
        <div class="publication-detail-actions">
          <button data-publication-action="create_snapshot">Create snapshot</button>
          <button class="secondary" data-publication-action="request_review" ${snapshot.snapshot_id ? '' : 'disabled'}>Request review</button>
          <button class="secondary" data-publication-action="approve_snapshot" ${snapshot.snapshot_id ? '' : 'disabled'}>Approve</button>
          <button class="secondary" data-publication-action="request_changes" ${snapshot.snapshot_id ? '' : 'disabled'}>Request changes</button>
          <button data-publication-action="publish_snapshot" ${snapshot.review_state === 'approved' ? '' : 'disabled'}>Publish</button>
          <button class="secondary danger-button" data-publication-action="supersede_release" ${bundle.release_state === 'published' ? '' : 'disabled'}>Supersede</button>
          <span id="publicationDetailStatus" class="muted"></span>
        </div>
      </header>
      <nav class="entity-detail-tabs">${tabs.map(tabButton).join('')}</nav>
      <section class="panel detail-card" data-publication-section="overview">
        ${metricCards([
          { label: 'Claims', value: data.manifest_summary?.claims || 0 },
          { label: 'Evidence', value: data.manifest_summary?.evidence || 0 },
          { label: 'Sources', value: data.manifest_summary?.sources || 0 },
          { label: 'Taxonomy IDs', value: data.manifest_summary?.taxonomy_terms || 0 },
        ])}
      </section>
      <section class="panel detail-card" data-publication-section="checks">
        <h3>Checks</h3>
        ${(data.checks || []).map((check) => `<p>${statusBadge(check.state)} <strong>${escapeHtml(check.label)}</strong><br>${escapeHtml(check.detail || '')}</p>`).join('')}
      </section>
      <section class="panel detail-card" data-publication-section="changed_content">
        <h3>Changed content</h3>
        ${(data.changed_content || []).map((row) => `<p><strong>${escapeHtml(row.label)}</strong><br><code>${escapeHtml(row.before || '')}</code><br><code>${escapeHtml(row.after || '')}</code></p>`).join('')}
      </section>
      <section class="panel detail-card" data-publication-section="claims"><h3>Claims</h3>${(data.claims || []).map((claim) => `<p><strong>${escapeHtml(claim.claim_text || '')}</strong><br>${statusBadge(claim.review_state)} ${claim.source_evidence_id ? `<button class="text-button" data-id="${escapeHtml(claim.source_evidence_id)}">Source</button>` : ''}</p>`).join('') || '<p class="muted">No claims.</p>'}</section>
      <section class="panel detail-card" data-publication-section="evidence"><h3>Evidence</h3>${renderMiniSourceList(data.sources || [])}</section>
      <section class="panel detail-card" data-publication-section="contradictions"><h3>Contradictions</h3>${(data.contradictions || []).map((claim) => `<p>${statusBadge(claim.contradiction_state)} ${escapeHtml(claim.claim_text || '')}</p>`).join('') || '<p class="muted">No unresolved contradictions in this manifest.</p>'}</section>
      <section class="panel detail-card" data-publication-section="discussion"><h3>Discussion</h3>${(data.discussion || []).map((event) => `<p><strong>${escapeHtml(event.event_type)}</strong><br>${escapeHtml(fmtDate(event.created_at))} · ${escapeHtml(event.actor || '')}</p>`).join('') || '<p class="muted">No review discussion yet.</p>'}</section>
      <section class="panel detail-card" data-publication-section="public_preview"><h3>Public preview</h3><p>${escapeHtml(data.public_preview?.title || bundle.title || '')}</p><p>${escapeHtml(data.public_preview?.claim_count || 0)} claims · ${escapeHtml(data.public_preview?.citation_count || 0)} citations</p></section>
    </section>
  `;
  document.querySelectorAll('[data-publication-tab]').forEach((button) => button.addEventListener('click', () => {
    state.publicationDetailTab = button.dataset.publicationTab || 'overview';
    replaceRouteHash();
    document.querySelectorAll('[data-publication-tab]').forEach((tab) => tab.classList.toggle('active', tab === button));
    document.querySelectorAll('[data-publication-section]').forEach((section) => section.classList.toggle('hidden', section.dataset.publicationSection !== state.publicationDetailTab && state.publicationDetailTab !== 'overview'));
  }));
  document.querySelectorAll('[data-publication-section]').forEach((section) => section.classList.toggle('hidden', section.dataset.publicationSection !== active && active !== 'overview'));
  document.querySelectorAll('[data-publication-action]').forEach((button) => button.addEventListener('click', () => persistPublicationDetailAction(button.dataset.publicationAction || '', data)));
  document.querySelectorAll('[data-route-target]').forEach((button) => button.addEventListener('click', () => setRoute(button.dataset.routeTarget || 'publishing')));
  bindObjectRows();
}

function renderRoutePage(route, data) {
  if (route === 'timeline') return renderTimelinePage(data);
  if (route === 'compare') return renderComparePage(data);
  if (route === 'topic-detail') return renderTopicDetailPage(data);
  if (route === 'benchmark') return renderBenchmarkPage(data);
  if (route === 'draft') return renderDraftPage(data);
  if (route === 'publication-detail') return renderPublicationDetailPage(data);
  if (route === 'entity-detail') return renderEntityDetailPage(data);
  if (route === 'conflict-detail') return renderConflictDetailPage(data);
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
    if (state.evidenceQueue && state.evidenceQueue !== 'all') params.set('queue', state.evidenceQueue);
    if (state.evidenceType) params.set('type', state.evidenceType);
    if (state.evidenceReviewState) params.set('review_state', state.evidenceReviewState);
    if (state.evidenceSourceKind) params.set('source_kind', state.evidenceSourceKind);
    if (state.evidenceAnchorType) params.set('anchor_type', state.evidenceAnchorType);
    if (state.evidenceSelectedId) params.set('inspect', `evidence:${state.evidenceSelectedId}`);
  }
  if (state.route === 'entities') {
    if (state.entityQueue && state.entityQueue !== 'all') params.set('queue', state.entityQueue);
    if (state.entityType) params.set('entity_type', state.entityType);
    if (state.entityReviewState) params.set('review_state', state.entityReviewState);
    if (state.entitySourceKind) params.set('source_kind', state.entitySourceKind);
    if (state.entitySelectedId) params.set('inspect', `entity:${state.entitySelectedId}`);
  }
  if (state.route === 'claims') {
    if (state.claimQueue && state.claimQueue !== 'all') params.set('queue', state.claimQueue);
    if (state.claimType) params.set('claim_type', state.claimType);
    if (state.claimReviewState) params.set('review_state', state.claimReviewState);
    if (state.claimContradictionState) params.set('contradiction_state', state.claimContradictionState);
    if (state.claimSourceKind) params.set('source_kind', state.claimSourceKind);
    if (state.claimSelectedId) params.set('inspect', `claim:${state.claimSelectedId}`);
  }
  if (state.route === 'reviews') {
    if (state.reviewQueue && state.reviewQueue !== 'all') params.set('queue', state.reviewQueue);
    if (state.reviewType) params.set('type', state.reviewType);
    if (state.reviewDecisionState) params.set('decision_state', state.reviewDecisionState);
    if (state.reviewPriority) params.set('priority', state.reviewPriority);
    if (state.reviewLayer) params.set('layer', state.reviewLayer);
    if (state.reviewSelectedId) params.set('inspect', `review:${state.reviewSelectedId}`);
    if (state.reviewPreviewTab && state.reviewPreviewTab !== 'review') params.set('tab', state.reviewPreviewTab);
  }
  if (state.route === 'publishing') {
    if (state.publishingSelectedId) params.set('inspect', `bundle:${state.publishingSelectedId}`);
    if (state.publishingPreviewTab && state.publishingPreviewTab !== 'readiness') params.set('tab', state.publishingPreviewTab);
  }
  if (state.route === 'taxonomy') {
    if (state.taxonomyQueue && state.taxonomyQueue !== 'proposed_terms') params.set('queue', state.taxonomyQueue);
    if (state.taxonomyVocabulary) params.set('vocabulary', state.taxonomyVocabulary);
    if (state.taxonomyReviewState) params.set('review_state', state.taxonomyReviewState);
    if (state.taxonomySearchMode && state.taxonomySearchMode !== 'hybrid') params.set('mode', state.taxonomySearchMode);
    if (state.taxonomySelectedId) params.set('inspect', `taxonomy:${state.taxonomySelectedId}`);
    if (state.taxonomyPreviewTab && state.taxonomyPreviewTab !== 'overview') params.set('tab', state.taxonomyPreviewTab);
  }
  return params.toString();
}

function updateRouteVisibility() {
  const route = state.route;
  const showHome = route === 'home';
  const showInbox = route === 'inbox';
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
  if (state.route === 'entity-detail') {
    await loadEntityDetail();
    return;
  }
  if (state.route === 'conflict-detail') {
    await loadConflictDetail();
    return;
  }
  if (state.route === 'timeline') {
    await loadTimelinePage();
    return;
  }
  if (state.route === 'compare') {
    await loadComparePage();
    return;
  }
  if (state.route === 'topic-detail') {
    await loadTopicDetailPage();
    return;
  }
  if (state.route === 'benchmark') {
    await loadBenchmarkPage();
    return;
  }
  if (state.route === 'draft') {
    await loadDraftPage();
    return;
  }
  if (state.route === 'publication-detail') {
    await loadPublicationDetailPage();
    return;
  }
  const config = routeConfig[state.route];
  if (!config) return;
  const routeKey = state.route;
  $('routePage').innerHTML = `${pageHeader(config.title, 'Loading route read model...')}<div class="empty-state panel"><h2>Loading</h2><p>Building the ${escapeHtml(config.title)} view.</p></div>`;
  const token = makeFetchToken();
  try {
    const data = await fetchJson(`${config.endpoint}?${routeQuery()}`);
    // Ignore stale responses (e.g. the user typed again or switched routes).
    if (!isCurrentFetchToken(token) || state.route !== routeKey) return;
    renderRoutePage(state.route, data);
  } catch (error) {
    if (!isCurrentFetchToken(token) || state.route !== routeKey) return;
    $('routePage').innerHTML = `${pageHeader(config.title, 'Could not load this read model.')}<div class="empty-state panel"><h2>${escapeHtml(config.title)} error</h2><p>${escapeHtml(error.message)}</p></div>`;
  }
}

function setRoute(route, push = true) {
  state.route = routeConfig[route] ? route : 'home';
  // push=true (user-initiated nav) -> new history entry so Back returns here.
  // push=false (hashchange replay) -> replace, no extra entry.
  if (push) pushRouteHash(); else replaceRouteHash();
  loadRoutePage();
}

function renderInbox(rows) {
  state.rows = rows;
  const highPriority = rows.filter((row) => row.task_priority === 'high' || row.task_priority === 'blocking').length;
  $('inboxOpenTasks').textContent = `${rows.length} open task${rows.length === 1 ? '' : 's'}`;
  $('inboxHighPriority').textContent = `${highPriority} high priority`;
  $('inboxVisibleCount').textContent = `${rows.length} visible task${rows.length === 1 ? '' : 's'}${rows.length >= Number(state.limit || 200) ? ' (showing first ' + rows.length + ' — more may exist; refine the search or queue)' : ''}`;
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
      ${row.canonical_url ? `<a href="${escapeHtml(safeUrl(row.canonical_url))}" target="_blank" rel="noreferrer">${escapeHtml(row.canonical_url)}</a>` : ''}
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
      idempotency_key: idempotencyKey(row.task_id || taskKeyFor(row), 'assigned', row.status || row.task_state || ''),
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
      actor: REVIEW_UI_ACTOR,
      expected_version: expectedVersionForRow(row),
      status: reviewStatusForPreviewAction(row, action),
      note,
      source_anchor: sourceAnchorForTask(row),
      idempotency_key: idempotencyKey(row.task_id || taskKeyFor(row), decision, row.status || row.task_state || ''),
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
    idempotency_key: idempotencyKey(row.task_id || taskKeyFor(row), decision, row.status || row.task_state || ''),
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
  const token = makeFetchToken();
  try {
    const data = await fetchJson(`/api/inbox?${params.toString()}`);
    // Ignore stale inbox responses (e.g. from an earlier search keystroke).
    if (!isCurrentFetchToken(token)) return;
    renderInbox(data.rows || []);
  } catch (error) {
    if (!isCurrentFetchToken(token)) return;
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
  const links = (latest.links || []).map((link) => `<a href="${escapeHtml(safeUrl(link))}" target="_blank" rel="noreferrer">${escapeHtml(link)}</a>`).join('<br>');
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
  // Pull capture-provenance fields from raw if present. The spec wants a
  // rebrowser session id, capture status, and supersedence; today the capture
  // only records method/run/timestamp, so surface what exists and label the
  // rest as not recorded rather than hiding the gap.
  const captureStatus = raw.capture_status || raw.status || latest.capture_status || '';
  const rebrowserSession = raw.rebrowser_session_id || raw.session_id || '';
  const supersedes = raw.supersedes_capture_id || latest.supersedes_capture_id || '';
  const steps = [
    { label: 'Captured source', value: latest.canonical_url || latest.evidence_id, meta: fmtDate(latest.captured_at) },
    { label: 'Collector run', value: latest.collector_run_id || '(not recorded)', meta: latest.capture_method || '' },
    { label: 'Capture status', value: captureStatus || '(not recorded)', meta: rebrowserSession ? `session ${rebrowserSession}` : 'no rebrowser session id recorded' },
    { label: 'Supersedes', value: supersedes || '(none — first capture)', meta: '' },
    { label: 'Normalized evidence row', value: latest.evidence_id || '', meta: fmtDate(latest.ingested_at) },
    { label: 'Artifact manifest', value: `${artifacts.length} local artifact(s)`, meta: artifacts.map((item) => item.path || item).join(' · ') || 'no artifact paths' },
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
      <h3>Artifact paths</h3>
      ${artifacts.length ? `<div class="artifact-link-list">${artifacts.map((item) => `<span class="muted">${escapeHtml(item.path || item)}</span>`).join('<br>')}</div>` : '<p class="muted">No local artifact paths recorded.</p>'}
    </section>
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
        <p><a href="${escapeHtml(safeUrl(artifact.url))}" target="_blank" rel="noreferrer">${escapeHtml(artifact.path)}</a></p>
        ${isImage ? `<img class="artifact-img" src="${escapeHtml(safeUrl(artifact.url))}" alt="">` : ''}
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
            ${asset.url ? `<p><a href="${escapeHtml(safeUrl(asset.url))}" target="_blank" rel="noreferrer">${escapeHtml(asset.alt || asset.url)}</a></p>` : ''}
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
        ${row.text_artifact_path_url ? `<p><a href="${escapeHtml(safeUrl(row.text_artifact_path_url))}" target="_blank" rel="noreferrer">OCR text artifact</a></p>` : ''}
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
  const selectedId = state.selectedId;
  const token = makeFetchToken();
  const source = await fetchJson(`/api/source?id=${encodeURIComponent(selectedId)}`);
  // Ignore if the user selected a different source while this refresh was in
  // flight, or a newer refresh started.
  if (!isCurrentFetchToken(token) || state.selectedId !== selectedId) return;
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
          actor: REVIEW_UI_ACTOR,
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

async function launchCaptureFlow(seed = '') {
  const seedUrl = seed || window.prompt('Capture URL', '') || '';
  if (!seedUrl.trim()) return;
  state.captureLaunchStatus = 'Launching capture...';
  try {
    const result = await postJson('/api/rebrowser/launch-capture', {
      project_id: state.project || state.home?.active_project?.project_id || '',
      seed_url: seedUrl.trim(),
      return_route: routeHash(),
      actor: REVIEW_UI_ACTOR,
    });
    state.captureLaunchStatus = result.message || 'Capture launch recorded.';
    window.alert(state.captureLaunchStatus);
    await loadInbox();
  } catch (error) {
    state.captureLaunchStatus = error.message;
    window.alert(error.message);
  }
}

function wireEvents() {
  setSidebarCollapsed(state.sidebarCollapsed);
  $('sidebarToggle')?.addEventListener('click', () => {
    setSidebarCollapsed(!state.sidebarCollapsed);
  });
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
    launchCaptureFlow();
  });
  $('captureTopButton')?.addEventListener('click', () => {
    launchCaptureFlow();
  });
  $('newNoteButton')?.addEventListener('click', () => {
    openInboxQueue('manual_docs');
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
      if (state.route === 'library' || state.route === 'evidence' || state.route === 'entities' || state.route === 'claims' || state.route === 'reviews' || state.route === 'publishing' || state.route === 'taxonomy' || state.route === 'timeline' || state.route === 'compare' || state.route === 'draft') replaceRouteHash();
      if (state.route === 'home') openLibraryView({ q: state.q, mode: 'hybrid', scope: 'corpus' });
      else if (state.route === 'inbox') loadInbox();
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
    if (state.route === 'inbox') loadInbox();
    if (state.route !== 'home' && state.route !== 'inbox') {
      if (state.route === 'library' || state.route === 'evidence' || state.route === 'entities' || state.route === 'claims' || state.route === 'reviews' || state.route === 'publishing' || state.route === 'taxonomy' || state.route === 'timeline' || state.route === 'compare' || state.route === 'draft') replaceRouteHash();
      loadRoutePage();
    }
  });
  $('limitSelect').addEventListener('change', () => {
    state.limit = $('limitSelect').value;
    if (state.route === 'inbox') loadInbox();
    if (state.route !== 'home' && state.route !== 'inbox') loadRoutePage();
  });
  document.querySelectorAll('.tab').forEach((tab) => {
    tab.addEventListener('click', () => activateTab(tab.dataset.tab));
  });
  window.addEventListener('hashchange', () => {
    const { route: previousRoute } = currentHashParts();
    // Capture scroll of the outgoing route before the swap (spec section 4).
    state.routeScrollMemory[previousRoute] = window.scrollY;
    const { route } = currentHashParts();
    applyHashParams();
    setRoute(route, false);
    // Restore scroll of the incoming route if we have a memory entry.
    const saved = state.routeScrollMemory[route];
    if (typeof saved === 'number') {
      requestAnimationFrame(() => window.scrollTo(0, saved));
    }
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
