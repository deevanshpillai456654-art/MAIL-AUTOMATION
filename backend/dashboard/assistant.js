/**
 * INTEMO AI Support Assistant — Frontend Logic
 *
 * Architecture:
 *   AssistantAPI    — fetch wrapper around /api/v1/assistant/*
 *   SessionStore    — current session state (mode, sessionId, issue)
 *   UIController    — panels, navigation, visual rendering
 *   ToastManager    — notifications
 *   ConfirmModal    — pre-action confirmation dialog
 *
 * No external dependencies — vanilla JS only.
 */
'use strict';

window.setSafeHTML = function(el, html) {
  if (!el) return;
  if (typeof html !== 'string') {
    el.textContent = String(html);
    return;
  }
  const parser = new DOMParser();
  const doc = parser.parseFromString(html, 'text/html');
  const badTags = doc.querySelectorAll('script, iframe, object, embed, form, base, applet, meta, link');
  badTags.forEach(n => n.remove());
  const all = doc.querySelectorAll('*');
  for (let i = 0; i < all.length; i++) {
    const node = all[i];
    for (let j = node.attributes.length - 1; j >= 0; j--) {
      const attr = node.attributes[j];
      if (attr.name.toLowerCase().startsWith('on') || attr.name.toLowerCase() === 'javascript:') {
        node.removeAttribute(attr.name);
      }
    }
  }
  el.replaceChildren(...doc.body.childNodes);
};


function esc(v) {
  return String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

// ─── constants ────────────────────────────────────────────────────────────────

const BASE   = '/api/v1';
const ASST   = `${BASE}/assistant`;

// detect admin mode from URL ?mode=admin or ?admin=1
const IS_ADMIN = (() => {
  const p = new URLSearchParams(window.location.search);
  return p.get('mode') === 'admin' || p.get('admin') === '1';
})();

// ─── API layer ─────────────────────────────────────────────────────────────────

const AssistantAPI = {
  _sessionReady: null,
  async _ensureSession() {
    if (!this._sessionReady) {
      this._sessionReady = fetch(`${BASE}/session/bootstrap`, {
        method: 'POST',
        credentials: 'same-origin',
      }).catch(() => null);
    }
    await this._sessionReady;
  },

  _headers() {
    const h = { 'Content-Type': 'application/json' };
    if (IS_ADMIN) h['X-Assistant-Mode'] = 'admin';
    return h;
  },

  async _fetch(path, opts = {}) {
    await this._ensureSession();
    const url = path.startsWith('http') ? path : `${ASST}${path}`;
    const res = await fetch(url, {
      headers: this._headers(),
      credentials: 'same-origin',
      ...opts,
    });
    if (!res.ok) {
      let msg = `HTTP ${res.status}`;
      try { const j = await res.json(); msg = j.detail || j.message || msg; } catch (_) {}
      throw new Error(msg);
    }
    return res.json();
  },

  // issues
  async getIssues()           { return this._fetch('/issues'); },
  async getIssue(id)          { return this._fetch(`/issues/${id}`); },
  async searchIssues(q)       { return this._fetch(`/issues/search?q=${encodeURIComponent(q)}`); },
  async getCategories()       { return this._fetch('/categories'); },

  // session
  async createSession(runDiag = true) {
    return this._fetch('/session', {
      method: 'POST',
      body: JSON.stringify({ mode: IS_ADMIN ? 'admin' : 'user', run_diagnostics: runDiag }),
    });
  },
  async getSession(id)        { return this._fetch(`/session/${id}`); },
  async closeSession(id)      { return this._fetch(`/session/${id}`, { method: 'DELETE' }); },

  // flow navigation
  async startFlow(sessionId, issueId) {
    return this._fetch(`/session/${sessionId}/flow`, {
      method: 'POST',
      body: JSON.stringify({ issue_id: issueId }),
    });
  },
  async advanceStep(sessionId, outcome = 'ok') {
    return this._fetch(`/session/${sessionId}/advance`, {
      method: 'POST',
      body: JSON.stringify({ outcome }),
    });
  },
  async currentStep(sessionId) { return this._fetch(`/session/${sessionId}/step`); },

  // diagnostics
  async runDiagnostics()      { return this._fetch('/diagnostics'); },
  async quickCheck()          { return this._fetch('/diagnostics/quick'); },

  // actions
  async listActions()         { return this._fetch('/actions'); },
  async getAction(id)         { return this._fetch(`/actions/${id}`); },
  async executeAction(id, params = {}, confirmed = false) {
    return this._fetch(`/actions/${id}/execute`, {
      method: 'POST',
      body: JSON.stringify({ params, confirmed }),
    });
  },
};

// ─── session store ─────────────────────────────────────────────────────────────

const SessionStore = {
  sessionId: null,
  mode: IS_ADMIN ? 'admin' : 'user',
  currentIssueId: null,
  diagnostics: null,
  issues: [],
  categories: [],

  async init() {
    try {
      const data = await AssistantAPI.createSession(true);
      this.sessionId = data.session_id;
      this.mode = data.mode;
      this.diagnostics = data.diagnostics;
      return data;
    } catch (e) {
      return null;
    }
  },

  async loadIssues() {
    const data = await AssistantAPI.getIssues();
    this.issues = data.issues || [];
    const cats = await AssistantAPI.getCategories();
    this.categories = cats.categories || [];
    return this.issues;
  },
};

// ─── toast ─────────────────────────────────────────────────────────────────────

const Toast = {
  show(msg, type = 'info', duration = 4000) {
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.textContent = msg;
    const container = document.getElementById('toastContainer');
    container.appendChild(el);
    setTimeout(() => { el.style.opacity = '0'; el.style.transition = 'opacity .3s'; }, duration - 300);
    setTimeout(() => el.remove(), duration);
  },
  success(msg) { this.show(msg, 'success'); },
  error(msg)   { this.show(msg, 'error', 6000); },
  info(msg)    { this.show(msg, 'info'); },
  warning(msg) { this.show(msg, 'warning'); },
};

// ─── confirmation modal ──────────────────────────────────────────────────────

const ConfirmModal = {
  _resolve: null,

  show(title, impact, rollback) {
    document.getElementById('modalTitle').textContent   = title;
    document.getElementById('modalImpact').textContent  = impact;
    document.getElementById('modalRollback').textContent = rollback;
    const modal = document.getElementById('confirmModal');
    modal.classList.add('open');
    modal.removeAttribute('aria-hidden');
    return new Promise(resolve => { this._resolve = resolve; });
  },

  _close(confirmed) {
    const modal = document.getElementById('confirmModal');
    modal.classList.remove('open');
    modal.setAttribute('aria-hidden', 'true');
    if (this._resolve) this._resolve(confirmed);
    this._resolve = null;
  },

  init() {
    document.getElementById('modalCancel').addEventListener('click',  () => this._close(false));
    document.getElementById('modalConfirm').addEventListener('click', () => this._close(true));
    document.getElementById('confirmModal').addEventListener('click', e => {
      if (e.target === document.getElementById('confirmModal')) this._close(false);
    });
  },
};

// ─── visual renderers ─────────────────────────────────────────────────────────

function renderSeverityBadge(severity) {
  const labels = { info: 'Info', low: 'Low', moderate: 'Moderate', high: 'High', critical: 'Critical' };
  const icons  = { info: 'ℹ', low: '✔', moderate: '⚠', high: '⚠', critical: '🔴' };
  return `<span class="severity-badge ${esc(severity)}">${icons[severity] || '●'} ${esc(labels[severity] || severity)}</span>`;
}

function renderVisualFlow(nodes, currentIndex = 0) {
  if (!nodes || !nodes.length) return '';
  return nodes.map((node, i) => {
    const cls = i < currentIndex ? 'done' : (i === currentIndex ? 'active' : '');
    const arrow = i < nodes.length - 1 ? '<span class="vf-arrow">→</span>' : '';
    return `<div class="vf-node"><span class="vf-label ${cls}">${esc(node)}</span>${arrow}</div>`;
  }).join('');
}

function renderVisual(visual) {
  if (!visual) return '';
  let content = '';

  if (visual.type === 'svg') {
    content = `<div class="sv-content">${visual.content}</div>`; // intentional SVG markup
  } else if (visual.type === 'flow_diagram') {
    const nodes = (visual.content || '').split('|');
    const items = nodes.map(n => `<div class="fdv-node">${esc(n)}</div><div class="fdv-arrow">↓</div>`).join('');
    // Remove last arrow
    const cleaned = items.replace(/<div class="fdv-arrow">↓<\/div>$/, '');
    content = `<div class="sv-content"><div class="flow-diagram-visual">${cleaned}</div></div>`;
  } else {
    content = `<div class="sv-content sv-content--text">${esc(visual.content)}</div>`;
  }

  const annotation = visual.annotation
    ? `<div class="sv-annotation">ℹ ${esc(visual.annotation)}</div>`
    : '';

  return `
    <div class="step-visual">
      <div class="sv-title">${esc(visual.title)}</div>
      ${content}
      ${annotation}
    </div>`;
}

function renderAction(action, sessionId) {
  if (!action) return '';
  const styleMap = { primary: 'btn-primary', secondary: 'btn-secondary', danger: 'btn-danger' };
  const cls = styleMap[action.style] || 'btn-primary';
  return `
    <div class="step-action">
      <button class="btn ${cls}" type="button" data-action="${esc(action.action_id)}"
              data-confirm="${esc(action.confirm_required)}"
              data-session="${esc(sessionId || '')}">
        ${esc(action.label)}
      </button>
    </div>`;
}

function renderStep(step, sessionId) {
  const visual  = renderVisual(step.visual);
  const action  = renderAction(step.action, sessionId);
  const detail  = step.detail
    ? `<div class="step-detail">${esc(step.detail)}</div>` : '';
  const expected = step.expected_result
    ? `<div class="step-expected">${esc(step.expected_result)}</div>` : '';
  const adminBadge = step.admin_only
    ? '<span class="admin-badge">⚙ Admin</span>' : '';

  const instruction = esc(step.instruction || '')
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\n/g, '<br>');

  return `
    <div class="step-card active-step" id="stepCard">
      <div class="step-card-header">
        <div class="step-number">${esc(step.number)}</div>
        <div class="step-title">${esc(step.title)}${adminBadge}</div>
      </div>
      <div class="step-instruction">${instruction}</div>
      ${detail}
      ${visual}
      ${expected}
      ${action}
    </div>`;
}

// ─── UI controller ─────────────────────────────────────────────────────────────

const UI = {
  _currentPanel: 'home',

  showPanel(name) {
    ['Home', 'Diag', 'Flow'].forEach(p => {
      const el = document.getElementById(`panel${p}`);
      if (el) el.style.display = p.toLowerCase() === name ? '' : 'none';
    });
    this._currentPanel = name;
  },

  // ── sidebar nav ──────────────────────────────────────────────────────────

  renderSidebar(issues) {
    const nav = document.getElementById('issueNav');
    if (!issues.length) {
      window.setSafeHTML(nav, '<div class="sidebar-empty">No issues found.</div>');
      return;
    }

    const byCat = {};
    issues.forEach(i => { (byCat[i.category] = byCat[i.category] || []).push(i); });

    const catLabels = {
      auth: '🔐 Authentication',
      sync: '🔄 Email Sync',
      extension: '🧩 Browser Extension',
      classification: '🏷 Classification',
      service: '⚙ Service / Backend',
      performance: '📊 Performance',
      onboarding: '🚀 Getting Started',
    };

    window.setSafeHTML(nav, Object.entries(byCat).map(([cat, items]) => `
      <div class="cat-group">
        <div class="cat-label">${esc(catLabels[cat] || cat)}</div>
        ${items.map(i => `
          <button class="issue-btn" data-issue="${esc(i.id)}">
            <span class="dot ${esc(i.severity)}"></span>
            <span class="btn-text">
              <div class="btn-title">${esc(i.title)}</div>
              <div class="btn-cat">${esc(i.step_count)} steps</div>
            </span>
          </button>`).join('')}
      </div>`).join(''));

    nav.querySelectorAll('.issue-btn').forEach(btn => {
      btn.addEventListener('click', () => FlowController.open(btn.dataset.issue));
    });
  },

  setActiveIssue(issueId) {
    document.querySelectorAll('.issue-btn').forEach(b => {
      b.classList.toggle('active', b.dataset.issue === issueId);
    });
  },

  // ── home panel ───────────────────────────────────────────────────────────

  renderHome(sessionData) {
    const diag = sessionData?.diagnostics || {};
    const suggested = sessionData?.suggested_issues || [];

    // stats
    document.getElementById('statIssues').textContent     = SessionStore.issues.length || '—';
    document.getElementById('statActions').textContent    = '8';
    document.getElementById('statCategories').textContent = SessionStore.categories.length || '—';

    // detected issues
    const det = diag.detected_issues || [];
    if (det.length) {
      document.getElementById('detectedSection').style.display = '';
      const list = document.getElementById('detectedList');
      window.setSafeHTML(list, det.map(id => {
        const issue = SessionStore.issues.find(i => i.id === id);
        if (!issue) return '';
        return `
          <div class="diag-issue-row" data-issue="${esc(issue.id)}">
            <span class="dot ${esc(issue.severity)}"></span>
            <span class="dir-title">${esc(issue.title)}</span>
            <span class="dir-action">Fix this →</span>
          </div>`;
      }).join(''));
      list.querySelectorAll('.diag-issue-row').forEach(row => {
        row.addEventListener('click', () => FlowController.open(row.dataset.issue));
      });
    }

    // recommendations
    const recs = diag.recommendations || [];
    if (recs.length) {
      document.getElementById('recsSection').style.display = '';
      window.setSafeHTML(document.getElementById('recsList'), recs.map(r =>
        `<li class="rec-item">⚠ ${esc(r)}</li>`
      ).join(''));
    }

    // quick issues grid (prioritise suggested)
    const toShow = suggested.length ? suggested : SessionStore.issues.slice(0, 8);
    const grid = document.getElementById('quickIssuesGrid');
    window.setSafeHTML(grid, toShow.slice(0, 9).map(i => `
      <div class="quick-card" data-issue="${esc(i.id)}">
        <div class="qc-sev ${esc(i.severity)}">${esc(i.severity.toUpperCase())}</div>
        <div class="qc-title">${esc(i.title)}</div>
        <div class="qc-desc">${esc((i.description || '').slice(0, 90))}…</div>
      </div>`).join(''));
    grid.querySelectorAll('.quick-card').forEach(c => {
      c.addEventListener('click', () => FlowController.open(c.dataset.issue));
    });
  },

  // ── health bar ───────────────────────────────────────────────────────────

  updateHealth(overall) {
    const dot   = document.getElementById('healthDot');
    const label = document.getElementById('healthLabel');
    const labels = { healthy: 'Healthy', degraded: 'Degraded', unhealthy: 'Unhealthy', unknown: 'Unknown' };
    dot.className = overall;
    label.textContent = labels[overall] || overall;
  },

  // ── diagnostics panel ────────────────────────────────────────────────────

  renderDiagnostics(report) {
    document.getElementById('diagTimestamp').textContent =
      'Last run: ' + new Date(report.timestamp * 1000).toLocaleTimeString();

    this.updateHealth(report.overall);

    const grid = document.getElementById('diagGrid');
    const statusIcons = { healthy: '✓', degraded: '⚠', unhealthy: '✗', unknown: '?' };
    window.setSafeHTML(grid, (report.components || []).map(c => `
      <div class="diag-card">
        <div class="dc-name">${esc(c.name.replace(/_/g, ' '))}</div>
        <div class="dc-status">
          <span class="dot ${c.status === 'healthy' ? 'low' : c.status === 'degraded' ? 'moderate' : c.status === 'unhealthy' ? 'high' : 'info'}"></span>
          ${statusIcons[c.status] || '?'} ${esc(c.status)}
        </div>
        <div class="dc-msg">${esc(c.message || '')}</div>
      </div>`).join(''));

    // detected issues
    const det = report.detected_issues || [];
    if (det.length) {
      document.getElementById('diagIssuesSection').style.display = '';
      const list = document.getElementById('diagIssuesList');
      window.setSafeHTML(list, det.map(id => {
        const issue = SessionStore.issues.find(i => i.id === id);
        if (!issue) return '';
        return `
          <div class="diag-issue-row" data-issue="${esc(issue.id)}">
            <span class="dot ${esc(issue.severity)}"></span>
            <span class="dir-title">${esc(issue.title)}</span>
            <span class="dir-action">Start fix →</span>
          </div>`;
      }).join(''));
      list.querySelectorAll('.diag-issue-row').forEach(row => {
        row.addEventListener('click', () => FlowController.open(row.dataset.issue));
      });
    } else {
      document.getElementById('diagIssuesSection').style.display = 'none';
    }

    // recommendations
    const recs = report.recommendations || [];
    if (recs.length) {
      document.getElementById('diagRecsSection').style.display = '';
      window.setSafeHTML(document.getElementById('diagRecsList'), recs.map(r =>
        `<li>${esc(r)}</li>`).join(''));
    } else {
      document.getElementById('diagRecsSection').style.display = 'none';
    }

    this.showPanel('diag');
  },

  // ── flow panel ───────────────────────────────────────────────────────────

  renderFlowHeader(issue) {
    const icons = {
      auth: '🔐', sync: '🔄', extension: '🧩',
      classification: '🏷', service: '⚙', performance: '📊', onboarding: '🚀',
    };
    document.getElementById('flowIcon').textContent = icons[issue.category] || '🔧';
    document.getElementById('flowTitle').textContent = issue.title;
    document.getElementById('flowDesc').textContent  = issue.description || '';
    document.getElementById('flowSeverityBadge').outerHTML =
      `<span id="flowSeverityBadge">${renderSeverityBadge(issue.severity)}</span>`;

    window.setSafeHTML(
      document.getElementById('symptomsList'),
      (issue.symptoms || []).map(s => `<li>• ${esc(s)}</li>`).join('')
    );
  },

  renderFlowProgress(current, total) {
    const bar   = document.getElementById('flowProgress');
    const fill  = document.getElementById('progressFill');
    const label = document.getElementById('progressLabel');
    bar.style.display = '';
    fill.style.width  = `${Math.round((current / total) * 100)}%`;
    label.textContent = `Step ${current} of ${total}`;
  },

  renderStep(step, sessionId) {
    window.setSafeHTML(document.getElementById('stepsContainer'), renderStep(step, sessionId));
    document.getElementById('stepNav').style.display = '';
    document.getElementById('navHint').textContent =
      step.expected_result ? '✓ Expected: ' + step.expected_result.slice(0, 60) : '';

    // wire action buttons (scoped to step container only)
    document.getElementById('stepsContainer').querySelectorAll('[data-action]').forEach(btn => {
      btn.addEventListener('click', () => ActionController.run(btn));
    });
  },

  renderComplete(msg, related) {
    window.setSafeHTML(document.getElementById('stepsContainer'), '');
    document.getElementById('stepNav').style.display = 'none';
    document.getElementById('flowProgress').style.display = 'none';

    const banner = document.getElementById('flowComplete');
    banner.style.display = '';
    document.getElementById('flowCompleteMsg').textContent = msg || '';

    if (related && related.length) {
      document.getElementById('relatedSection').style.display = '';
      window.setSafeHTML(document.getElementById('relatedGrid'), related.map(r => `
        <div class="related-card" data-issue="${esc(r.id)}">
          <div class="rc-title">${esc(r.title)}</div>
          <div class="rc-cat">${esc(r.category)}</div>
        </div>`).join(''));
      document.getElementById('relatedGrid').querySelectorAll('.related-card').forEach(c => {
        c.addEventListener('click', () => FlowController.open(c.dataset.issue));
      });
    }

    // update flow diagram — all done
    const nodes = document.querySelectorAll('.vf-label');
    nodes.forEach(n => { n.classList.remove('active'); n.classList.add('done'); });
  },

  setLoading(btn, loading) {
    if (!btn) return;
    btn.classList.toggle('loading', loading);
    const spinner = btn.querySelector('.spinner');
    if (spinner) spinner.style.display = loading ? '' : 'none';
  },
};

// ─── flow controller ──────────────────────────────────────────────────────────

const FlowController = {
  _data: null,    // current issue detail
  _step: null,    // current step data

  async open(issueId) {
    if (!SessionStore.sessionId) await SessionStore.init();
    UI.showPanel('flow');
    UI.setActiveIssue(issueId);

    // hide complete banner, reset
    document.getElementById('flowComplete').style.display = 'none';
    document.getElementById('relatedSection').style.display = 'none';
    window.setSafeHTML(
      document.getElementById('stepsContainer'),
      '<div class="loading-placeholder skeleton skeleton--flow"></div>'
    );

    try {
      // load issue header
      this._data = await AssistantAPI.getIssue(issueId);
      UI.renderFlowHeader(this._data);

      // visual flow diagram (step 1 = active)
      window.setSafeHTML(
        document.getElementById('visualFlow'),
        renderVisualFlow(this._data.visual_flow_nodes, 0)
      );

      // start flow in session
      const flowData = await AssistantAPI.startFlow(SessionStore.sessionId, issueId);
      SessionStore.currentIssueId = issueId;

      if (flowData.current_step) {
        this._step = flowData.current_step;
        const prog = flowData.progress;
        UI.renderFlowProgress(prog.current, prog.total);
        UI.renderStep(this._step, SessionStore.sessionId);
      }
    } catch (e) {
      Toast.error('Failed to load issue: ' + e.message);
      window.setSafeHTML(
        document.getElementById('stepsContainer'),
        `<div class="error-message">${esc(e.message)}</div>`
      );
    }
  },

  async advance(outcome = 'ok') {
    if (!SessionStore.sessionId) return;
    const btnDone   = document.getElementById('btnStepDone');
    const btnFailed = document.getElementById('btnStepFailed');
    UI.setLoading(btnDone, true);
    UI.setLoading(btnFailed, true);

    try {
      const result = await AssistantAPI.advanceStep(SessionStore.sessionId, outcome);

      if (result.completed) {
        UI.renderComplete(result.message, result.related_issues);
        // update flow nodes to all done
        window.setSafeHTML(
          document.getElementById('visualFlow'),
          renderVisualFlow(this._data?.visual_flow_nodes || [], 9999)
        );
        Toast.success('Flow complete!');
        return;
      }

      if (result.issue) {
        // redirect to new issue
        this._data = result.issue;
        UI.renderFlowHeader(result.issue);
        window.setSafeHTML(
          document.getElementById('visualFlow'),
          renderVisualFlow(result.issue.visual_flow_nodes, 0)
        );
      }

      if (result.current_step) {
        this._step = result.current_step;
        const prog = result.progress;
        UI.renderFlowProgress(prog.current, prog.total);
        UI.renderStep(this._step, SessionStore.sessionId);

        // update visual flow diagram active node
        window.setSafeHTML(
          document.getElementById('visualFlow'),
          renderVisualFlow(this._data?.visual_flow_nodes || [], prog.current - 1)
        );
      }
    } catch (e) {
      Toast.error('Could not advance: ' + e.message);
    } finally {
      UI.setLoading(btnDone, false);
      UI.setLoading(btnFailed, false);
    }
  },
};

// ─── action controller ────────────────────────────────────────────────────────

const ActionController = {
  async run(btn) {
    const actionId  = btn.dataset.action;
    const confirm   = btn.dataset.confirm === 'true';
    const sessionId = btn.dataset.session || SessionStore.sessionId;

    UI.setLoading(btn, true);

    try {
      // first call — get impact info (may need confirmation)
      let result = await AssistantAPI.executeAction(actionId, {}, false);

      if (result.requires_confirmation) {
        UI.setLoading(btn, false);
        const ok = await ConfirmModal.show(
          `Confirm: ${result.action_id}`,
          result.impact,
          result.rollback || 'This action cannot be directly reversed.',
        );
        if (!ok) { Toast.info('Action cancelled.'); return; }
        UI.setLoading(btn, true);
        result = await AssistantAPI.executeAction(actionId, {}, true);
      }

      if (result.success) {
        Toast.success(result.message || 'Action completed successfully.');
        if (result.data?.redirect) {
          const redir = String(result.data.redirect);
          if (redir.startsWith('/') || redir.startsWith(window.location.origin)) {
            setTimeout(() => { window.location.href = redir; }, 1500);
          }
        }
        // refresh health indicator after action
        DiagController.quickCheck();
      } else {
        Toast.error(result.message || 'Action failed.');
      }
    } catch (e) {
      Toast.error('Action error: ' + e.message);
    } finally {
      UI.setLoading(btn, false);
    }
  },
};

// ─── diagnostics controller ──────────────────────────────────────────────────

const DiagController = {
  async run() {
    const btn   = document.getElementById('btnRunDiag');
    const label = document.getElementById('diagBtnLabel');
    const spin  = document.getElementById('diagSpinner');

    btn.classList.add('running');
    label.textContent = 'Running…';
    spin.style.display = '';

    try {
      const report = await AssistantAPI.runDiagnostics();
      UI.renderDiagnostics(report);

      // refresh home panel suggestions
      if (SessionStore.issues.length) {
        const suggested = (report.suggested_flows || []);
        if (suggested.length) {
          SessionStore.diagnostics = {
            detected_issues: report.detected_issues,
            recommendations: report.recommendations,
          };
          UI.renderHome({ diagnostics: SessionStore.diagnostics, suggested_issues: suggested });
        }
      }

      Toast.success('Diagnostics complete — overall: ' + report.overall);
    } catch (e) {
      Toast.error('Diagnostics failed: ' + e.message);
    } finally {
      btn.classList.remove('running');
      label.textContent = 'Run Diagnostics';
      spin.style.display = 'none';
    }
  },

  async quickCheck() {
    try {
      const data = await AssistantAPI.quickCheck();
      const dbOk  = data.database?.status === 'healthy';
      const actOk = data.accounts?.status !== 'unhealthy';
      const overall = dbOk && actOk ? 'healthy' : (!dbOk ? 'unhealthy' : 'degraded');
      UI.updateHealth(overall);
    } catch (_) {
      UI.updateHealth('unknown');
    }
  },
};

// ─── search ──────────────────────────────────────────────────────────────────

const Search = {
  _debounce: null,
  init() {
    const input = document.getElementById('issueSearch');
    input.addEventListener('input', () => {
      clearTimeout(this._debounce);
      this._debounce = setTimeout(() => this._run(input.value.trim()), 300);
    });
  },
  async _run(q) {
    if (!q) {
      UI.renderSidebar(SessionStore.issues);
      return;
    }
    try {
      const data = await AssistantAPI.searchIssues(q);
      UI.renderSidebar(data.results || []);
    } catch (_) {}
  },
};

// ─── bootstrap ───────────────────────────────────────────────────────────────

async function boot() {
  // mode badge
  const badge = document.getElementById('modeBadge');
  if (IS_ADMIN) {
    badge.textContent = 'Admin Mode';
    badge.classList.replace('user', 'admin');
  }

  // back to dashboard
  document.getElementById('btnBackDash').addEventListener('click', () => {
    window.location.href = '/dashboard';
  });

  // brand logo → back to assistant home
  document.getElementById('btnHome').addEventListener('click', () => {
    UI.showPanel('home');
    document.querySelectorAll('.issue-btn').forEach(b => b.classList.remove('active'));
  });

  // step nav buttons
  document.getElementById('btnStepDone').addEventListener('click', () => FlowController.advance('ok'));
  document.getElementById('btnStepFailed').addEventListener('click', () => FlowController.advance('failed'));

  // diagnostics button
  document.getElementById('btnRunDiag').addEventListener('click', () => DiagController.run());

  // init modal
  ConfirmModal.init();

  // init search
  Search.init();

  // init quick health check
  DiagController.quickCheck();

  // load issues for sidebar
  try {
    await SessionStore.loadIssues();
    UI.renderSidebar(SessionStore.issues);
  } catch (e) {}

  // create session with diagnostics
  try {
    const sessionData = await SessionStore.init();
    if (sessionData) {
      UI.updateHealth(sessionData.diagnostics?.overall || 'unknown');
      UI.renderHome(sessionData);

      // auto-open most severe detected issue if there is one
      const detected = sessionData.diagnostics?.detected_issues || [];
      if (detected.length) {
        // show detected section on home but don't auto-navigate to flow
      }
    }
  } catch (e) {
    UI.renderHome({});
  }

  UI.showPanel('home');
}

// handle URL params: ?issue=XXX auto-opens a flow
function handleURLParams() {
  const params = new URLSearchParams(window.location.search);
  const issueId = params.get('issue');
  if (issueId) {
    // wait for boot then open
    setTimeout(() => FlowController.open(issueId), 800);
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => { boot().then(handleURLParams); });
} else {
  boot().then(handleURLParams);
}
