const TOKEN_KEY = 'dokumatAuthToken';
const STATUS = {
  draft: 'Entwurf',
  checked_out: 'Ausgecheckt',
  in_review: 'In Prüfung',
  approved: 'Genehmigt',
  rejected: 'Abgelehnt',
  released: 'Freigegeben',
  queued: 'Eingeplant',
  extracting: 'Lokale Zerlegung läuft',
  extracted: 'Lokal zerlegt',
  analyzing: 'OpenAI-Analyse läuft',
  cancelling: 'Wird abgebrochen',
  cancelled: 'Abgebrochen',
  completed: 'Abgeschlossen',
  processing: 'Wird verarbeitet',
  ready: 'Bereit',
  failed: 'Fehlgeschlagen',
};

const state = {
  token: localStorage.getItem(TOKEN_KEY) || '',
  user: null,
  adminUsers: [],
  managedDocuments: [],
  selectedManagedId: null,
  selectedManaged: null,
  selectedDocument: null,
  templates: [],
  selectedTemplateId: null,
  selectedTemplate: null,
  templateMatches: [],
  selectedTemplateSectionIds: [],
  selectedTemplateCheck: null,
  documentChecks: [],
  structureMapping: null,
  outlineResult: null,
  sectionTextMode: 'cleaned_text',
  activePage: 'cockpit',
  activeTab: 'overview',
  semanticResults: [],
  semanticQuery: '',
};

const el = {
  authScreen: document.getElementById('auth-screen'),
  appShell: document.getElementById('app-shell'),
  showLogin: document.getElementById('show-login'),
  showRegister: document.getElementById('show-register'),
  loginScreenForm: document.getElementById('login-screen-form'),
  loginScreenUsername: document.getElementById('login-screen-username'),
  loginScreenPassword: document.getElementById('login-screen-password'),
  registerForm: document.getElementById('register-form'),
  registerDisplayName: document.getElementById('register-display-name'),
  registerUsername: document.getElementById('register-username'),
  registerEmail: document.getElementById('register-email'),
  registerPassword: document.getElementById('register-password'),
  loginForm: document.getElementById('login-form'),
  loginUsername: document.getElementById('login-username'),
  loginPassword: document.getElementById('login-password'),
  logoutButton: document.getElementById('logout-button'),
  sessionPanel: document.getElementById('session-panel'),
  sessionName: document.getElementById('session-name'),
  sessionMeta: document.getElementById('session-meta'),
  uploadForm: document.getElementById('upload-form'),
  uploadTitle: document.getElementById('upload-title'),
  uploadDescription: document.getElementById('upload-description'),
  uploadChangeSummary: document.getElementById('upload-change-summary'),
  uploadFile: document.getElementById('upload-file'),
  checkinForm: document.getElementById('checkin-form'),
  checkinSummary: document.getElementById('checkin-summary'),
  checkinFile: document.getElementById('checkin-file'),
  outlineForm: document.getElementById('outline-form'),
  outlineFile: document.getElementById('outline-file'),
  outlineCurrentDocument: document.getElementById('outline-current-document'),
  templateUploadForm: document.getElementById('template-upload-form'),
  templateUploadFile: document.getElementById('template-upload-file'),
  refreshTemplates: document.getElementById('refresh-templates'),
  templateList: document.getElementById('template-list'),
  refreshDocuments: document.getElementById('refresh-documents'),
  documentList: document.getElementById('document-list'),
  statusPill: document.getElementById('status-pill'),
  heroTitle: document.getElementById('hero-title'),
  heroSubtitle: document.getElementById('hero-subtitle'),
  checkoutDocument: document.getElementById('checkout-document'),
  cancelCheckoutDocument: document.getElementById('cancel-checkout-document'),
  submitReviewDocument: document.getElementById('submit-review-document'),
  approveDocument: document.getElementById('approve-document'),
  rejectDocument: document.getElementById('reject-document'),
  releaseDocument: document.getElementById('release-document'),
  reprocessDocument: document.getElementById('reprocess-document'),
  analyzeDocument: document.getElementById('analyze-document'),
  refreshEmbeddingsDocument: document.getElementById('refresh-embeddings-document'),
  cancelDocument: document.getElementById('cancel-document'),
  cancelTemplate: document.getElementById('cancel-template'),
  runStructureMapping: document.getElementById('run-structure-mapping'),
  runTemplateCheckSample: document.getElementById('run-template-check-sample'),
  runTemplateCheck: document.getElementById('run-template-check'),
  managedDocumentMeta: document.getElementById('managed-document-meta'),
  versionHistory: document.getElementById('version-history'),
  summaryGrid: document.getElementById('summary-grid'),
  analysisStatusBadge: document.getElementById('analysis-status-badge'),
  analysisStatusText: document.getElementById('analysis-status-text'),
  documentStatusList: document.getElementById('document-status-list'),
  outlineMeta: document.getElementById('outline-meta'),
  outlineTree: document.getElementById('outline-tree'),
  outlineMarkdown: document.getElementById('outline-markdown'),
  outlineChunks: document.getElementById('outline-chunks'),
  templateMeta: document.getElementById('template-meta'),
  templateMatchList: document.getElementById('template-match-list'),
  templateSectionList: document.getElementById('template-section-list'),
  structureMappingList: document.getElementById('structure-mapping-list'),
  templateCheckMeta: document.getElementById('template-check-meta'),
  templateCheckSummary: document.getElementById('template-check-summary'),
  templateCheckScoreGrid: document.getElementById('template-check-score-grid'),
  templateGapList: document.getElementById('template-gap-list'),
  templateCheckResults: document.getElementById('template-check-results'),
  refreshTemplateMatches: document.getElementById('refresh-template-matches'),
  selectAllTemplateSections: document.getElementById('select-all-template-sections'),
  selectNoneTemplateSections: document.getElementById('select-none-template-sections'),
  semanticSearchForm: document.getElementById('semantic-search-form'),
  semanticSearchQuery: document.getElementById('semantic-search-query'),
  semanticSearchScopeCurrent: document.getElementById('semantic-search-scope-current'),
  semanticSearchMeta: document.getElementById('semantic-search-meta'),
  semanticSearchResults: document.getElementById('semantic-search-results'),
  adminPageButton: document.getElementById('admin-page-button'),
  refreshUsers: document.getElementById('refresh-users'),
  adminUserList: document.getElementById('admin-user-list'),
  sectionList: document.getElementById('section-list'),
  pageList: document.getElementById('page-list'),
  imageGrid: document.getElementById('image-grid'),
  sectionCount: document.getElementById('section-count'),
  imageCount: document.getElementById('image-count'),
  sectionTextMode: document.getElementById('section-text-mode'),
  toastContainer: document.getElementById('toast-container'),
  pageButtons: [...document.querySelectorAll('.page-button')],
  pagePanels: [...document.querySelectorAll('.page-panel')],
  tabButtons: [...document.querySelectorAll('.tab-button')],
  tabPanels: [...document.querySelectorAll('.tab-panel')],
  documentItemTemplate: document.getElementById('document-item-template'),
  templateItemTemplate: document.getElementById('template-item-template'),
};

const TAB_TO_PAGE = {
  overview: 'cockpit',
  status: 'cockpit',
  workspace: 'documents',
  document: 'documents',
  outline: 'quality',
  templates: 'quality',
  search: 'search',
};

const ROLE_LABELS = {
  creator: 'Ersteller',
  reviewer: 'Prüfer',
  admin: 'Administrator',
};

const t = (v) => STATUS[v] || v || 'Unbekannt';
const h = (v) => String(v ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
const fmt = (v) => v ? new Date(v).toLocaleString('de-DE') : 'Unbekannt';
const reviewer = () => {
  const roles = state.user?.roles || (state.user?.role ? [state.user.role] : []);
  return roles.includes('reviewer') || roles.includes('admin');
};
const currentVersion = () => state.selectedManaged?.current_version || null;
const currentDocumentId = () => state.selectedDocument?.id || currentVersion()?.document_id || null;

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (state.token) headers.set('Authorization', `Bearer ${state.token}`);
  const res = await fetch(path, { ...options, headers });
  if (!res.ok) {
    let msg = `Fehler ${res.status}`;
    try {
      const body = await res.json();
      if (body.detail) msg = body.detail;
    } catch {}
    if (res.status === 401 && path !== '/auth/login') resetSession();
    throw new Error(msg);
  }
  return (res.headers.get('content-type') || '').includes('application/json') ? res.json() : null;
}

async function hydrateSessionData() {
  const results = await Promise.allSettled([loadManagedDocuments(), loadTemplates(), loadUsers()]);
  const failed = results.filter((result) => result.status === 'rejected');
  if (failed.length) {
    console.error('Session hydration failed', failed);
    toast('Anmeldung erfolgreich, aber nicht alle Inhalte konnten geladen werden.', 'info');
  }
}

function setStatus(text, kind = '') {
  el.statusPill.textContent = text;
  el.statusPill.className = `pill ${kind}`.trim();
}

function toast(text, kind = 'info') {
  const n = document.createElement('div');
  n.className = `toast ${kind}`;
  n.textContent = text;
  el.toastContainer.appendChild(n);
  requestAnimationFrame(() => n.classList.add('visible'));
  setTimeout(() => {
    n.classList.remove('visible');
    setTimeout(() => n.remove(), 220);
  }, 3200);
}

function persistToken(token) {
  state.token = token || '';
  if (state.token) localStorage.setItem(TOKEN_KEY, state.token);
  else localStorage.removeItem(TOKEN_KEY);
}

function resetSession() {
  persistToken('');
  state.user = null;
  state.adminUsers = [];
  state.managedDocuments = [];
  state.selectedManagedId = null;
  state.selectedManaged = null;
  state.selectedDocument = null;
  state.templates = [];
  state.selectedTemplateId = null;
  state.selectedTemplate = null;
  state.templateMatches = [];
  state.selectedTemplateSectionIds = [];
  state.selectedTemplateCheck = null;
  state.documentChecks = [];
  state.structureMapping = null;
  state.outlineResult = null;
  state.semanticResults = [];
  state.semanticQuery = '';
  state.activePage = 'cockpit';
  state.activeTab = 'overview';
}

function setActivePage(name) {
  state.activePage = name;
  el.pageButtons.forEach((b) => b.classList.toggle('active', b.dataset.page === name));
  el.pagePanels.forEach((p) => p.classList.toggle('active', p.id === `page-${name}`));
}

function setActiveTab(name) {
  state.activeTab = name;
  setActivePage(TAB_TO_PAGE[name] || 'cockpit');
  el.tabButtons.forEach((b) => b.classList.toggle('active', b.dataset.tab === name));
  el.tabPanels.forEach((p) => p.classList.toggle('active', p.id === `tab-${name}`));
  renderDocumentTab();
}

function renderAuth() {
  const logged = Boolean(state.user);
  const roles = state.user?.roles || (state.user?.role ? [state.user.role] : []);
  el.authScreen.hidden = logged;
  el.appShell.hidden = !logged;
  el.loginForm.hidden = true;
  el.sessionPanel.hidden = !logged;
  el.logoutButton.hidden = !logged;
  el.adminPageButton.hidden = !roles.includes('admin');
  el.sessionName.textContent = logged ? state.user.display_name : 'Nicht angemeldet';
  el.sessionMeta.textContent = logged
    ? `${state.user.username} · ${roles.map((role) => ROLE_LABELS[role] || role).join(', ')} · ${state.user.auth_provider}`
    : 'Bitte anmelden, um Dokumente zu verwalten.';
  if (logged && state.activePage === 'admin' && !roles.includes('admin')) setActiveTab('overview');
}

function renderManagedList() {
  el.documentList.innerHTML = !state.user ? '<div class="empty-state">Bitte zuerst anmelden.</div>' : !state.managedDocuments.length ? '<div class="empty-state">Noch keine verwalteten Dokumente vorhanden.</div>' : '';
  state.managedDocuments.forEach((doc) => {
    const v = doc.current_version;
    const b = el.documentItemTemplate.content.firstElementChild.cloneNode(true);
    b.classList.toggle('active', doc.id === state.selectedManagedId);
    b.querySelector('.document-title').textContent = doc.title;
    b.querySelector('.document-meta').textContent = `${t(doc.status)} · v${v?.version_number || '-'} · ${fmt(doc.updated_at)}`;
    b.querySelector('.document-status-dot').className = `document-status-dot ${v?.processing_status || doc.status}`;
    b.querySelector('.document-submeta').innerHTML = `<span class="status-chip">${h(t(doc.status))}</span><span class="status-chip">${h(t(v?.processing_status))}</span>`;
    b.addEventListener('click', async () => { await loadManagedDetail(doc.id); setActiveTab('overview'); });
    el.documentList.appendChild(b);
  });
}

function renderHero() {
  if (!state.selectedManaged) {
    el.heroTitle.textContent = state.user ? 'Kein Dokument ausgewählt' : 'Anmeldung erforderlich';
    el.heroSubtitle.textContent = state.user ? 'Wähle links ein Dokument aus oder lege ein neues an.' : 'Bitte anmelden, um Dokumente hochzuladen und freizugeben.';
    el.analysisStatusBadge.textContent = 'Bereit';
    el.analysisStatusBadge.className = 'status-badge not-analyzed';
    el.analysisStatusText.textContent = 'Die technische Detailansicht bezieht sich auf die aktuelle Version des verwalteten Dokuments.';
    return;
  }
  const tech = state.selectedDocument;
  const label = tech?.status === 'completed' ? 'OpenAI analysiert' : tech?.status === 'extracted' ? 'Lokal zerlegt' : t(tech?.status || 'draft');
  el.heroTitle.textContent = state.selectedManaged.title;
  el.heroSubtitle.textContent = `Zuletzt aktualisiert ${fmt(state.selectedManaged.updated_at)} · ${t(state.selectedManaged.status)} · ${currentVersion() ? `Version ${currentVersion().version_number}` : 'keine Version'}`;
  el.analysisStatusBadge.textContent = label;
  el.analysisStatusBadge.className = 'status-badge';
  el.analysisStatusText.textContent = tech ? `Technischer Status der aktuellen Version: ${t(tech.status)}.` : 'Noch keine technische Dokumentversion vorhanden.';
}

function renderSummary() {
  if (!state.selectedManaged) {
    el.summaryGrid.innerHTML = '';
    return;
  }
  const tech = state.selectedDocument;
  const v = currentVersion();
  const items = [
    ['Dokument', state.selectedManaged.title],
    ['Lenkungsstatus', t(state.selectedManaged.status)],
    ['Version', v ? `v${v.version_number}` : 'Keine'],
    ['Datei', v?.original_filename || 'Keine'],
    ['Seiten', tech?.page_count || 0],
    ['Abschnitte', tech?.sections?.length || 0],
    ['Bilder', tech?.images?.length || 0],
    ['Besitzer', state.selectedManaged.owner_name],
  ];
  el.summaryGrid.innerHTML = items.map(([k, v2]) => `<div class="summary-tile"><span class="label">${h(k)}</span><span class="value">${h(v2)}</span></div>`).join('');
}

function renderWorkflow() {
  if (!state.selectedManaged) {
    el.managedDocumentMeta.textContent = 'Noch kein Dokument ausgewählt.';
    el.versionHistory.innerHTML = '<div class="empty-state">Noch keine Versionen vorhanden.</div>';
    el.documentStatusList.innerHTML = '<div class="empty-state">Noch kein Dokument ausgewählt.</div>';
    return;
  }
  const m = state.selectedManaged;
  const v = currentVersion();
  const tech = state.selectedDocument;
  el.managedDocumentMeta.textContent = [`Besitzer: ${m.owner_name}`, m.checked_out_by_name ? `ausgecheckt von ${m.checked_out_by_name}` : 'nicht ausgecheckt', v?.reviewed_by_name ? `bewertet von ${v.reviewed_by_name}` : null].filter(Boolean).join(' · ');
  el.documentStatusList.innerHTML = [['Lenkungsstatus', t(m.status)], ['Version-Workflow', t(v?.status)], ['Technische Verarbeitung', t(tech?.status)], ['Gliederungsprüfung', state.outlineResult ? 'Vorhanden' : 'Noch nicht durchgeführt']].map(([k, v2]) => `<div class="status-row"><span class="label">${h(k)}</span><span class="value">${h(v2)}</span></div>`).join('');
  el.versionHistory.innerHTML = (m.versions || []).map((item) => `<article class="gap-card"><div class="row-between"><strong>Version ${item.version_number}</strong><span class="status-chip">${h(t(item.status))}</span></div><div class="muted">${h(item.original_filename)} · ${fmt(item.updated_at)}</div><div>${h(item.change_summary || 'Kein Änderungshinweis')}</div>${item.review_comment ? `<div class="muted">Review: ${h(item.review_comment)}</div>` : ''}</article>`).join('') || '<div class="empty-state">Noch keine Versionen vorhanden.</div>';
}

function renderOutline() {
  if (!state.outlineResult) {
    el.outlineMeta.textContent = 'Noch keine Prüfung ausgeführt.';
    el.outlineTree.innerHTML = '<div class="empty-state">Noch keine Gliederung vorhanden.</div>';
    el.outlineMarkdown.textContent = 'Noch keine Rohansicht vorhanden.';
    el.outlineChunks.innerHTML = '<div class="empty-state">Noch keine Chunk-Daten vorhanden.</div>';
    return;
  }
  const walk = (nodes) => `<ul>${(nodes || []).map((n) => `<li><strong>${h(n.heading)}</strong>${n.children?.length ? walk(n.children) : ''}</li>`).join('')}</ul>`;
  el.outlineMeta.textContent = `${state.outlineResult.analysis_mode} · ${state.outlineResult.chunk_count} Chunk(s)`;
  el.outlineTree.innerHTML = walk(state.outlineResult.hierarchy);
  el.outlineMarkdown.textContent = state.outlineResult.raw_outline_markdown || '';
  el.outlineChunks.innerHTML = (state.outlineResult.chunks || []).map((c) => `<article class="page-card"><h3>Chunk ${c.chunk_index}</h3><div class="page-meta">Seiten ${c.start_page}-${c.end_page}</div><pre class="preformatted">${h(c.raw_outline_markdown || '')}</pre></article>`).join('') || '<div class="empty-state">Keine Chunk-Daten vorhanden.</div>';
}

function renderDocumentTab() {
  const doc = state.selectedDocument;
  if (!doc) {
    el.sectionCount.textContent = '0 Einträge';
    el.imageCount.textContent = '0 Einträge';
    el.sectionList.innerHTML = '<div class="empty-state">Kein technisches Dokument geladen.</div>';
    el.imageGrid.innerHTML = '<div class="empty-state">Kein technisches Dokument geladen.</div>';
    el.pageList.innerHTML = '<div class="empty-state">Kein technisches Dokument geladen.</div>';
    return;
  }
  if (state.activeTab !== 'document') {
    el.sectionCount.textContent = `${doc.sections.length} Einträge`;
    el.imageCount.textContent = `${doc.images.length} Einträge`;
    el.sectionList.innerHTML = '<div class="empty-state">Dokumentansicht öffnen, um Abschnitte zu laden.</div>';
    el.imageGrid.innerHTML = '<div class="empty-state">Bilder werden erst in der Dokumentansicht geladen.</div>';
    el.pageList.innerHTML = '<div class="empty-state">Seitenvorschau wird erst in der Dokumentansicht geladen.</div>';
    return;
  }
  const field = state.sectionTextMode;
  el.sectionCount.textContent = `${doc.sections.length} Einträge`;
  el.imageCount.textContent = `${doc.images.length} Einträge`;
  el.sectionList.innerHTML = doc.sections.map((s) => `<article class="section-card"><h3>${h(s.heading)}</h3><div class="section-meta">${s.start_page}-${s.end_page} · Level ${s.level}</div><p>${h(s.summary || 'Keine Zusammenfassung vorhanden.')}</p><pre class="preformatted">${h(s[field] || '')}</pre></article>`).join('') || '<div class="empty-state">Keine Abschnitte vorhanden.</div>';
  el.imageGrid.innerHTML = doc.images.map((i) => `<article class="image-card"><img src="/${encodeURI(i.storage_path)}" alt="Bild von Seite ${i.page_number}" loading="lazy"><div class="body"><strong>Seite ${i.page_number}</strong><span class="muted">${h(i.filename)}</span></div></article>`).join('') || '<div class="empty-state">Keine Bilder extrahiert.</div>';
  el.pageList.innerHTML = doc.pages.slice(0, 10).map((p) => `<article class="page-card"><h3>Seite ${p.page_number}</h3><pre class="preformatted">${h((p.text_content || '').slice(0, 2500))}</pre></article>`).join('') || '<div class="empty-state">Keine Seiten gespeichert.</div>';
}

function renderTemplates() {
  el.templateList.innerHTML = !state.user ? '<div class="empty-state">Bitte zuerst anmelden.</div>' : !state.templates.length ? '<div class="empty-state">Noch keine Vorlagen vorhanden.</div>' : '';
  state.templates.forEach((tpl) => {
    const b = el.templateItemTemplate.content.firstElementChild.cloneNode(true);
    b.classList.toggle('active', tpl.id === state.selectedTemplateId);
    b.querySelector('.document-title').textContent = tpl.display_name;
    b.querySelector('.document-meta').textContent = `${tpl.section_count} Abschnitte · ${fmt(tpl.updated_at)}`;
    b.querySelector('.document-status-dot').className = `document-status-dot ${tpl.status === 'ready' ? 'completed' : tpl.status}`;
    b.querySelector('.document-submeta').innerHTML = `<span class="status-chip">${h(t(tpl.status))}</span>`;
    b.addEventListener('click', async () => { await loadTemplateDetail(tpl.id); setActiveTab('templates'); });
    el.templateList.appendChild(b);
  });
  if (!state.selectedTemplate) {
    el.templateMeta.textContent = 'Noch keine Vorlage ausgewählt.';
    el.templateSectionList.innerHTML = '<div class="empty-state">Noch keine Vorlage ausgewählt.</div>';
  } else {
    el.templateMeta.textContent = `${state.selectedTemplate.display_name} · ${state.selectedTemplate.section_count} Abschnitte`;
    el.templateSectionList.innerHTML = (state.selectedTemplate.sections || []).map((s) => `<article class="page-card"><h3>${h(s.heading)}</h3><p>${h(s.requirement_summary || '')}</p></article>`).join('') || '<div class="empty-state">Keine Vorlagenabschnitte vorhanden.</div>';
  }
  el.templateMatchList.innerHTML = state.templateMatches.map((m) => `<label class="match-card ${m.is_match ? 'matched' : 'missing'}"><div class="match-card-main"><input type="checkbox" data-template-section-id="${m.template_section_id}" ${state.selectedTemplateSectionIds.includes(m.template_section_id) ? 'checked' : ''}><div class="match-card-copy"><strong>${h(m.template_heading)}</strong><div class="muted">${m.matched_document_heading ? `${h(m.matched_document_heading)} · Seiten ${m.matched_start_page}-${m.matched_end_page}` : 'Kein Match'}</div></div></div><span class="status-chip">${m.is_match ? `Match ${Number(m.match_score).toFixed(2)}` : 'Kein Match'}</span></label>`).join('') || '<div class="empty-state">Noch keine Zuordnung geladen.</div>';
  el.templateMatchList.querySelectorAll('input[type="checkbox"]').forEach((box) => box.addEventListener('change', () => {
    const id = box.getAttribute('data-template-section-id');
    state.selectedTemplateSectionIds = box.checked ? [...new Set([...state.selectedTemplateSectionIds, id])] : state.selectedTemplateSectionIds.filter((x) => x !== id);
    updateButtons();
  }));
  el.structureMappingList.innerHTML = state.structureMapping?.items?.map((i) => `<article class="page-card"><h3>${h(i.template_heading)}</h3><p>${h(i.reasoning || '')}</p></article>`).join('') || '<div class="empty-state">Noch kein Strukturmapping vorhanden.</div>';
  renderTemplateCheck();
}

function renderTemplateCheck() {
  const c = state.selectedTemplateCheck;
  if (!c) {
    el.templateCheckMeta.textContent = 'Noch keine Prüfung ausgeführt.';
    el.templateCheckSummary.textContent = 'Wähle eine Vorlage und ein Dokument aus, um die Prüfung zu starten.';
    el.templateCheckScoreGrid.innerHTML = '';
    el.templateGapList.innerHTML = '';
    el.templateCheckResults.innerHTML = '<div class="empty-state">Noch kein Prüfergebnis vorhanden.</div>';
    return;
  }
  const complete = c.section_checks.filter((x) => x.coverage_status === 'complete').length;
  const partial = c.section_checks.filter((x) => x.coverage_status === 'partial').length;
  const missing = c.section_checks.filter((x) => x.coverage_status === 'missing').length;
  const total = Math.max(1, c.required_section_count || c.section_checks.length || 1);
  const score = Math.round(((complete + partial * 0.5) / total) * 100);
  el.templateCheckMeta.textContent = `${fmt(c.updated_at)} · ${c.matched_section_count}/${c.required_section_count} Abschnitte gefunden`;
  el.templateCheckSummary.textContent = `${c.summary || ''} Vollständig: ${complete}, teilweise: ${partial}, fehlend: ${missing}.`;
  el.templateCheckScoreGrid.innerHTML = [['Gesamtscore', `${score}%`], ['Vollständig', complete], ['Teilweise', partial], ['Fehlend', missing]].map(([k, v]) => `<div class="summary-tile"><span class="label">${h(k)}</span><span class="value">${h(v)}</span></div>`).join('');
  el.templateGapList.innerHTML = c.section_checks.filter((x) => x.coverage_status !== 'complete').map((x) => `<article class="gap-card"><strong>${h(x.template_heading)}</strong><div class="muted">${h(x.document_heading || 'Kein passender Abschnitt')}</div></article>`).join('') || '<div class="empty-state">Keine Pflichtlücken erkannt.</div>';
  el.templateCheckResults.innerHTML = c.section_checks.map((x) => `<article class="template-check-card ${x.coverage_status}"><div class="row-between"><h3>${h(x.template_heading)}</h3><span class="status-chip">${h(x.coverage_status)}</span></div><p>${h(x.reasoning)}</p></article>`).join('');
}

function renderSearch() {
  el.semanticSearchMeta.textContent = state.semanticResults.length ? `${state.semanticResults.length} Treffer für "${state.semanticQuery}"` : state.semanticQuery ? `Keine Treffer für "${state.semanticQuery}" gefunden.` : 'Noch keine Suche ausgeführt.';
  el.semanticSearchResults.innerHTML = state.semanticResults.map((r) => `<article class="search-result-card"><div class="row-between"><div><h3>${h(r.normalized_heading || r.heading)}</h3><div class="muted">${h(r.document_filename)} · Seiten ${r.start_page}-${r.end_page}</div></div><div class="search-score">${Number(r.score).toFixed(3)}</div></div><p>${h(r.snippet || '')}</p></article>`).join('') || '<div class="empty-state">Noch keine Suchtreffer vorhanden.</div>';
}

function renderAdminUsers() {
  if (!(state.user?.roles || []).includes('admin')) {
    el.adminUserList.innerHTML = '<div class="empty-state">Keine Admin-Rechte vorhanden.</div>';
    return;
  }
  el.adminUserList.innerHTML = state.adminUsers.length ? state.adminUsers.map((user) => `
    <form class="admin-user-card" data-user-id="${user.id}">
      <div class="row-between">
        <strong>${h(user.username)}</strong>
        <span class="status-chip">${h(user.is_active ? 'Aktiv' : 'Inaktiv')}</span>
      </div>
      <div class="admin-user-grid">
        <label class="stack compact"><span class="field-label">Anzeigename</span><input type="text" name="display_name" value="${h(user.display_name)}"></label>
        <label class="stack compact"><span class="field-label">E-Mail</span><input type="text" name="email" value="${h(user.email || '')}"></label>
      </div>
      <div class="role-picker">
        ${['creator', 'reviewer', 'admin'].map((role) => `<label class="role-option"><input type="checkbox" name="roles" value="${role}" ${user.roles?.includes(role) ? 'checked' : ''}><span>${ROLE_LABELS[role]}</span></label>`).join('')}
        <label class="role-option"><input type="checkbox" name="is_active" ${user.is_active ? 'checked' : ''}><span>Aktiv</span></label>
      </div>
      <button type="submit" class="button-secondary">Benutzer speichern</button>
    </form>
  `).join('') : '<div class="empty-state">Noch keine Benutzer vorhanden.</div>';
  el.adminUserList.querySelectorAll('form[data-user-id]').forEach((form) => {
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const formData = new FormData(form);
      try {
        await api(`/admin/users/${form.getAttribute('data-user-id')}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            display_name: formData.get('display_name'),
            email: formData.get('email'),
            roles: formData.getAll('roles').map((value) => String(value)),
            is_active: form.querySelector('input[name="is_active"]').checked,
          }),
        });
        await loadUsers();
        toast('Benutzer gespeichert.', 'success');
      } catch (error) {
        alert(error.message);
      }
    });
  });
}

function updateButtons() {
  const m = state.selectedManaged;
  const tech = state.selectedDocument;
  const outByMe = m?.checked_out_by_id && m.checked_out_by_id === state.user?.id;
  const roles = state.user?.roles || (state.user?.role ? [state.user.role] : []);
  const busy = ['queued', 'extracting', 'analyzing'].includes(tech?.status);
  el.checkoutDocument.disabled = !state.user || !m || Boolean(m.checked_out_by_id);
  el.cancelCheckoutDocument.disabled = !state.user || !m || (!outByMe && !roles.includes('admin'));
  el.submitReviewDocument.disabled = !state.user || !m || Boolean(m.checked_out_by_id) || ['in_review', 'approved', 'released'].includes(m.status);
  el.approveDocument.disabled = !reviewer() || currentVersion()?.status !== 'in_review';
  el.rejectDocument.disabled = !reviewer() || currentVersion()?.status !== 'in_review';
  el.releaseDocument.disabled = !reviewer() || currentVersion()?.status !== 'approved';
  el.reprocessDocument.disabled = !tech || busy;
  el.analyzeDocument.disabled = !tech || busy || !['extracted', 'completed'].includes(tech.status);
  el.refreshEmbeddingsDocument.disabled = !tech || busy || !['extracted', 'completed'].includes(tech.status);
  el.cancelDocument.disabled = !tech || !['queued', 'extracting', 'analyzing', 'cancelling'].includes(tech.status);
  el.runStructureMapping.disabled = !state.selectedTemplateId || state.selectedTemplate?.status !== 'ready' || !currentDocumentId();
  el.runTemplateCheckSample.disabled = !state.selectedTemplateId || state.selectedTemplate?.status !== 'ready' || !tech?.sections?.length;
  el.runTemplateCheck.disabled = !state.selectedTemplateId || state.selectedTemplate?.status !== 'ready' || !state.selectedTemplateSectionIds.length || !tech?.sections?.length;
  el.cancelTemplate.disabled = !state.selectedTemplateId || !['processing', 'cancelling'].includes(state.selectedTemplate?.status);
}

function repaint() {
  renderAuth();
  renderManagedList();
  renderHero();
  renderSummary();
  renderWorkflow();
  renderOutline();
  renderDocumentTab();
  renderTemplates();
  renderSearch();
  renderAdminUsers();
  updateButtons();
}

async function loadManagedDocuments() {
  if (!state.user) return;
  state.managedDocuments = await api('/managed-documents');
  if (!state.selectedManagedId && state.managedDocuments.length) state.selectedManagedId = state.managedDocuments[0].id;
  if (state.selectedManagedId) await loadManagedDetail(state.selectedManagedId, false);
  else repaint();
}

async function loadManagedDetail(id, paintList = true) {
  state.selectedManagedId = id;
  state.selectedManaged = await api(`/managed-documents/${id}`);
  state.selectedDocument = state.selectedManaged.current_document || null;
  if (state.selectedDocument) {
    state.selectedDocument.sections = Array.isArray(state.selectedDocument.sections) ? state.selectedDocument.sections : [];
    state.selectedDocument.images = Array.isArray(state.selectedDocument.images) ? state.selectedDocument.images : [];
    state.selectedDocument.pages = Array.isArray(state.selectedDocument.pages) ? state.selectedDocument.pages : [];
  }
  state.outlineResult = state.selectedDocument?.outline_check || null;
  if (currentDocumentId()) {
    state.documentChecks = await api(`/documents/${currentDocumentId()}/template-checks`);
    state.selectedTemplateCheck = state.documentChecks.find((x) => x.template_id === state.selectedTemplateId) || null;
  }
  if (paintList) renderManagedList();
  repaint();
  if (state.selectedTemplateId && state.selectedTemplate?.status === 'ready' && currentDocumentId()) await loadTemplateMatches();
}

async function loadTemplates() {
  if (!state.user) return;
  state.templates = await api('/templates');
  if (!state.selectedTemplateId && state.templates.length) state.selectedTemplateId = state.templates[0].id;
  if (state.selectedTemplateId) await loadTemplateDetail(state.selectedTemplateId, false);
  else repaint();
}

async function loadUsers() {
  if (!(state.user?.roles || []).includes('admin')) {
    state.adminUsers = [];
    repaint();
    return;
  }
  state.adminUsers = await api('/admin/users');
  repaint();
}

async function loadTemplateDetail(id, paintList = true) {
  state.selectedTemplateId = id;
  state.selectedTemplate = await api(`/templates/${id}`);
  state.templateMatches = [];
  state.selectedTemplateSectionIds = [];
  state.structureMapping = null;
  state.selectedTemplateCheck = state.documentChecks.find((x) => x.template_id === state.selectedTemplateId) || null;
  if (paintList) renderTemplates();
  repaint();
  if (currentDocumentId() && state.selectedTemplate?.status === 'ready') await loadTemplateMatches();
}

async function loadTemplateMatches() {
  if (!state.selectedTemplateId || !currentDocumentId()) {
    state.templateMatches = [];
    repaint();
    return;
  }
  state.templateMatches = await api(`/templates/${state.selectedTemplateId}/matches/${currentDocumentId()}`);
  state.selectedTemplateSectionIds = state.templateMatches.filter((x) => x.is_match).map((x) => x.template_section_id);
  repaint();
}

el.showLogin.addEventListener('click', () => {
  el.showLogin.classList.add('active');
  el.showRegister.classList.remove('active');
  el.loginScreenForm.hidden = false;
  el.registerForm.hidden = true;
});

el.showRegister.addEventListener('click', () => {
  el.showRegister.classList.add('active');
  el.showLogin.classList.remove('active');
  el.loginScreenForm.hidden = true;
  el.registerForm.hidden = false;
});

el.loginScreenForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  try {
    const s = await api('/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username: el.loginScreenUsername.value.trim(), password: el.loginScreenPassword.value }) });
    persistToken(s.token);
    state.user = s.user;
    el.loginScreenForm.reset();
    setActiveTab('overview');
    repaint();
    await hydrateSessionData();
    setStatus('Angemeldet', 'completed');
    toast(`Willkommen ${s.user.display_name}.`, 'success');
    repaint();
  } catch (err) {
    alert(err.message);
  }
});

el.registerForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  try {
    const s = await api('/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        username: el.registerUsername.value.trim(),
        password: el.registerPassword.value,
        display_name: el.registerDisplayName.value.trim(),
        email: el.registerEmail.value.trim() || null,
      }),
    });
    persistToken(s.token);
    state.user = s.user;
    el.registerForm.reset();
    setActiveTab('overview');
    repaint();
    await hydrateSessionData();
    setStatus('Registriert und angemeldet', 'completed');
    toast(`Willkommen ${s.user.display_name}.`, 'success');
    repaint();
  } catch (err) {
    alert(err.message);
  }
});

el.logoutButton.addEventListener('click', async () => {
  try { if (state.token) await api('/auth/logout', { method: 'POST' }); } catch {}
  resetSession();
  el.showLogin.classList.add('active');
  el.showRegister.classList.remove('active');
  el.loginScreenForm.hidden = false;
  el.registerForm.hidden = true;
  repaint();
  setStatus('Abgemeldet', 'completed');
});

el.uploadForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const file = el.uploadFile.files[0];
  if (!file) return alert('Bitte zuerst eine PDF-Datei auswählen.');
  const fd = new FormData();
  fd.append('title', el.uploadTitle.value.trim());
  fd.append('description', el.uploadDescription.value.trim());
  fd.append('change_summary', el.uploadChangeSummary.value.trim());
  fd.append('file', file);
  try {
    await api('/managed-documents/upload', { method: 'POST', body: fd });
    el.uploadForm.reset();
    await loadManagedDocuments();
    setActiveTab('overview');
    setStatus('Dokument angelegt', 'completed');
  } catch (err) {
    alert(err.message);
  }
});

el.checkinForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  if (!state.selectedManagedId) return alert('Bitte zuerst ein Dokument auswählen.');
  const file = el.checkinFile.files[0];
  if (!file) return alert('Bitte zuerst eine PDF-Datei auswählen.');
  const fd = new FormData();
  fd.append('change_summary', el.checkinSummary.value.trim());
  fd.append('file', file);
  try {
    await api(`/managed-documents/${state.selectedManagedId}/checkin`, { method: 'POST', body: fd });
    el.checkinForm.reset();
    await loadManagedDocuments();
    setStatus('Neue Version eingecheckt', 'completed');
  } catch (err) {
    alert(err.message);
  }
});

el.checkoutDocument.addEventListener('click', async () => { try { await api(`/managed-documents/${state.selectedManagedId}/checkout`, { method: 'POST' }); await loadManagedDocuments(); } catch (err) { alert(err.message); } });
el.cancelCheckoutDocument.addEventListener('click', async () => { try { await api(`/managed-documents/${state.selectedManagedId}/cancel-checkout`, { method: 'POST' }); await loadManagedDocuments(); } catch (err) { alert(err.message); } });
el.submitReviewDocument.addEventListener('click', async () => { try { await api(`/managed-documents/${state.selectedManagedId}/submit-review`, { method: 'POST' }); await loadManagedDocuments(); } catch (err) { alert(err.message); } });
el.approveDocument.addEventListener('click', async () => { const comment = window.prompt('Kommentar zur Genehmigung (optional):', '') || ''; try { await api(`/managed-documents/${state.selectedManagedId}/approve`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ comment }) }); await loadManagedDocuments(); } catch (err) { alert(err.message); } });
el.rejectDocument.addEventListener('click', async () => { const comment = window.prompt('Begründung für die Ablehnung:', ''); if (comment === null) return; try { await api(`/managed-documents/${state.selectedManagedId}/reject`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ comment }) }); await loadManagedDocuments(); } catch (err) { alert(err.message); } });
el.releaseDocument.addEventListener('click', async () => { const comment = window.prompt('Kommentar zur Freigabe (optional):', '') || ''; try { await api(`/managed-documents/${state.selectedManagedId}/release`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ comment }) }); await loadManagedDocuments(); } catch (err) { alert(err.message); } });
el.refreshDocuments.addEventListener('click', () => loadManagedDocuments().catch((err) => alert(err.message)));
el.reprocessDocument.addEventListener('click', async () => { try { await api(`/documents/${currentDocumentId()}/reprocess`, { method: 'POST' }); await loadManagedDocuments(); } catch (err) { alert(err.message); } });
el.analyzeDocument.addEventListener('click', async () => { try { await api(`/documents/${currentDocumentId()}/analyze`, { method: 'POST' }); await loadManagedDocuments(); } catch (err) { alert(err.message); } });
el.refreshEmbeddingsDocument.addEventListener('click', async () => { try { await api(`/documents/${currentDocumentId()}/refresh-embeddings`, { method: 'POST' }); await loadManagedDocuments(); } catch (err) { alert(err.message); } });
el.cancelDocument.addEventListener('click', async () => { try { await api(`/documents/${currentDocumentId()}/cancel`, { method: 'POST' }); await loadManagedDocuments(); } catch (err) { alert(err.message); } });
el.outlineForm.addEventListener('submit', async (e) => { e.preventDefault(); const file = el.outlineFile.files[0]; if (!file) return alert('Bitte zuerst eine PDF-Datei auswählen.'); const fd = new FormData(); fd.append('file', file); try { state.outlineResult = await api('/outline-check/upload', { method: 'POST', body: fd }); repaint(); setActiveTab('outline'); } catch (err) { alert(err.message); } });
el.outlineCurrentDocument.addEventListener('click', async () => { if (!currentDocumentId()) return alert('Bitte zuerst ein Dokument auswählen.'); try { state.outlineResult = await api(`/documents/${currentDocumentId()}/outline-check`, { method: 'POST' }); await loadManagedDetail(state.selectedManagedId, false); setActiveTab('outline'); } catch (err) { alert(err.message); } });
el.templateUploadForm.addEventListener('submit', async (e) => { e.preventDefault(); const file = el.templateUploadFile.files[0]; if (!file) return alert('Bitte zuerst eine Template-PDF auswählen.'); const fd = new FormData(); fd.append('file', file); try { const tpl = await api('/templates/upload', { method: 'POST', body: fd }); state.selectedTemplateId = tpl.id; el.templateUploadForm.reset(); await loadTemplates(); setActiveTab('templates'); } catch (err) { alert(err.message); } });
el.refreshTemplates.addEventListener('click', () => loadTemplates().catch((err) => alert(err.message)));
el.refreshTemplateMatches.addEventListener('click', () => loadTemplateMatches().catch((err) => alert(err.message)));
el.selectAllTemplateSections.addEventListener('click', () => { state.selectedTemplateSectionIds = state.templateMatches.map((x) => x.template_section_id); repaint(); });
el.selectNoneTemplateSections.addEventListener('click', () => { state.selectedTemplateSectionIds = []; repaint(); });
el.runTemplateCheck.addEventListener('click', async () => { try { state.selectedTemplateCheck = await api(`/templates/${state.selectedTemplateId}/check/${currentDocumentId()}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ template_section_ids: state.selectedTemplateSectionIds }) }); state.documentChecks = await api(`/documents/${currentDocumentId()}/template-checks`); state.selectedTemplateCheck = state.documentChecks.find((x) => x.template_id === state.selectedTemplateId) || state.selectedTemplateCheck; repaint(); setActiveTab('templates'); } catch (err) { alert(err.message); } });
el.runTemplateCheckSample.addEventListener('click', async () => { try { state.selectedTemplateCheck = await api(`/templates/${state.selectedTemplateId}/check-sample/${currentDocumentId()}`, { method: 'POST' }); state.documentChecks = await api(`/documents/${currentDocumentId()}/template-checks`); state.selectedTemplateCheck = state.documentChecks.find((x) => x.template_id === state.selectedTemplateId) || state.selectedTemplateCheck; repaint(); setActiveTab('templates'); } catch (err) { alert(err.message); } });
el.runStructureMapping.addEventListener('click', async () => { try { state.structureMapping = await api(`/templates/${state.selectedTemplateId}/structure-map/${currentDocumentId()}`, { method: 'POST' }); repaint(); setActiveTab('templates'); } catch (err) { alert(err.message); } });
el.cancelTemplate.addEventListener('click', async () => { try { await api(`/templates/${state.selectedTemplateId}/cancel`, { method: 'POST' }); await loadTemplates(); } catch (err) { alert(err.message); } });
el.semanticSearchForm.addEventListener('submit', async (e) => { e.preventDefault(); const q = el.semanticSearchQuery.value.trim(); if (!q) return alert('Bitte einen Suchbegriff eingeben.'); try { const r = await api('/search/sections', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ query: q, limit: 8, document_id: el.semanticSearchScopeCurrent.checked ? currentDocumentId() : null }) }); state.semanticQuery = q; state.semanticResults = r.results || []; repaint(); setActiveTab('search'); } catch (err) { alert(err.message); } });
el.sectionTextMode.addEventListener('click', (e) => { const b = e.target.closest('[data-mode]'); if (!b) return; state.sectionTextMode = b.dataset.mode; [...el.sectionTextMode.querySelectorAll('[data-mode]')].forEach((x) => x.classList.toggle('active', x.dataset.mode === state.sectionTextMode)); renderDocumentTab(); });
el.pageButtons.forEach((b) => b.addEventListener('click', () => {
  const page = b.dataset.page;
  if (page === 'cockpit') setActiveTab(state.activeTab === 'status' ? 'status' : 'overview');
  else if (page === 'documents') setActiveTab(state.activeTab === 'document' ? 'document' : 'workspace');
  else if (page === 'quality') setActiveTab(state.activeTab === 'templates' ? 'templates' : 'outline');
  else if (page === 'admin') setActivePage('admin');
  else setActiveTab('search');
}));
el.tabButtons.forEach((b) => b.addEventListener('click', () => setActiveTab(b.dataset.tab)));
el.refreshUsers.addEventListener('click', () => loadUsers().catch((err) => alert(err.message)));

(async function init() {
  repaint();
  setActiveTab('overview');
  if (!state.token) return;
  try {
    state.user = await api('/auth/me');
    repaint();
    await hydrateSessionData();
    setStatus('Bereit', 'completed');
    repaint();
  } catch (err) {
    console.error(err);
    resetSession();
    state.adminUsers = [];
    repaint();
  }
})();
