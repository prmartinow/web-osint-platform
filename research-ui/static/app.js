const state = {
  queue: 'all',
  kind: '',
  project: '',
  q: '',
  limit: '80',
  selectedId: '',
  rows: [],
  facets: null,
  currentSource: null,
  currentDoc: null,
  selectedBlock: null,
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
  renderReview(source);
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
    tab.addEventListener('click', () => activateTab(tab.dataset.tab));
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
