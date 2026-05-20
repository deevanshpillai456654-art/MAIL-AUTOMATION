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

/* =========================================================
   MailPilot AI Automation Platform – Frontend SPA
   ========================================================= */

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
const state = {
  tenant: localStorage.getItem('ai_tenant') || 'default',
  currentPage: 'dashboard',
  workflows: [],
  builder: {
    workflowId: null,
    name: 'Untitled Workflow',
    nodes: [],
    connections: [],
    selectedNodeId: null,
    draggingNode: null,
    zoom: 1,
    offset: { x: 0, y: 0 },
  },
};

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------
const BASE = '/api/ai-automation';

async function api(path, opts = {}) {
  const sep = path.includes('?') ? '&' : '?';
  const url = `${BASE}${path}${sep}tenant_id=${encodeURIComponent(state.tenant)}`;
  try {
    const r = await fetch(url, {
      headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
      ...opts,
    });
    const data = await r.json().catch(() => ({}));
    return { ok: r.ok, status: r.status, data };
  } catch (e) {
    return { ok: false, error: e.message, data: {} };
  }
}

// ---------------------------------------------------------------------------
// Toast
// ---------------------------------------------------------------------------
function toast(title, msg = '', type = 'info') {
  const icons = { ok: '✅', bad: '❌', info: 'ℹ️' };
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  window.setSafeHTML(el, `<span class="toast-icon">${icons[type] || '💬'}</span>
    <div class="toast-body"><div class="toast-title">${esc(title)}</div>${msg ? `<div class="toast-msg">${esc(msg)}</div>` : ''}</div>`);
  document.getElementById('toastContainer').appendChild(el);
  setTimeout(() => el.remove(), 4000);
}

function esc(s) {
  return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ---------------------------------------------------------------------------
// Modal
// ---------------------------------------------------------------------------
function showModal(title, bodyHtml, footerHtml = '') {
  document.getElementById('modalTitle').textContent = title;
  window.setSafeHTML(document.getElementById('modalBody'), bodyHtml);
  window.setSafeHTML(document.getElementById('modalFooter'), footerHtml);
  document.getElementById('modalOverlay').style.display = 'flex';
}
function closeModal() { document.getElementById('modalOverlay').style.display = 'none'; }

// ---------------------------------------------------------------------------
// Navigation
// ---------------------------------------------------------------------------
function showPage(page) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  const pageEl = document.getElementById(`page-${page}`);
  if (pageEl) pageEl.classList.add('active');
  const navEl = document.querySelector(`[data-page="${page}"]`);
  if (navEl) navEl.classList.add('active');
  state.currentPage = page;

  const titles = {
    dashboard: 'Dashboard', analytics: 'Analytics', workflows: 'Workflows',
    builder: 'Workflow Builder', templates: 'Templates', executions: 'Executions',
    'ai-monitor': 'AI Providers', ocr: 'OCR Review', search: 'Semantic Search',
    approvals: 'Approvals', settings: 'Settings',
  };
  document.getElementById('pageTitle').textContent = titles[page] || page;

  const loaders = {
    dashboard: loadDashboard, analytics: loadAnalytics, workflows: loadWorkflows,
    executions: loadExecutions, 'ai-monitor': loadAIMonitor, ocr: loadOCR,
    approvals: loadApprovals, templates: loadTemplates,
  };
  if (loaders[page]) loaders[page]();
}

document.addEventListener('click', e => {
  const navItem = e.target.closest('[data-page]');
  if (navItem && navItem.classList.contains('nav-item')) showPage(navItem.dataset.page);
  const settingsTab = e.target.closest('[data-settings-tab]');
  if (settingsTab) activateSettingsTab(settingsTab.dataset.settingsTab);
});

// ---------------------------------------------------------------------------
// Tenant
// ---------------------------------------------------------------------------
function setTenant(t) {
  state.tenant = t;
  localStorage.setItem('ai_tenant', t);
  document.getElementById('tenantBadge').textContent = t;
}

function relTime(iso) {
  if (!iso) return '—';
  const diff = Date.now() - new Date(iso).getTime();
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s/60)}m ago`;
  if (s < 86400) return `${Math.floor(s/3600)}h ago`;
  return `${Math.floor(s/86400)}d ago`;
}

function fmtDuration(ms) {
  if (!ms) return '—';
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms/1000).toFixed(1)}s`;
  return `${Math.floor(ms/60000)}m ${Math.floor((ms%60000)/1000)}s`;
}

function statusBadge(status) {
  const labels = {
    draft: 'Draft', active: 'Active', paused: 'Paused', archived: 'Archived',
    running: 'Running', completed: 'Done', failed: 'Failed', pending: 'Pending',
    waiting_approval: 'Waiting', cancelled: 'Cancelled',
    low: 'Low', medium: 'Medium', high: 'High', critical: 'Critical',
  };
  return `<span class="badge badge-${status}">${labels[status] || status}</span>`;
}

// ---------------------------------------------------------------------------
// Dashboard
// ---------------------------------------------------------------------------
async function loadDashboard() {
  const [stats, execRes, approvalRes] = await Promise.all([
    api('/analytics/stats'),
    api('/executions/?limit=5'),
    api('/approvals/?status=pending&limit=5'),
  ]);

  if (stats.ok) renderStats(stats.data);
  if (execRes.ok) renderRecentExecs(execRes.data);
  if (approvalRes.ok) renderPendingApprovals(approvalRes.data);

  // Update badges
  if (approvalRes.ok) {
    const badge = document.getElementById('approvalBadge');
    badge.textContent = approvalRes.data.length || 0;
    badge.style.display = approvalRes.data.length ? '' : 'none';
  }
}

function renderStats(s) {
  const stats = [
    { label: 'Total Workflows', value: s.total_workflows, icon: '🔄', sub: `${s.active_workflows} active` },
    { label: 'Total Executions', value: s.total_executions, icon: '▶️', sub: `${s.running_executions} running` },
    { label: 'Pending Approvals', value: s.pending_approvals, icon: '✋', sub: 'needs attention' },
    { label: 'AI Requests Today', value: s.ai_requests_today, icon: '🤖', sub: 'across all providers' },
    { label: 'OCR Docs Today', value: s.ocr_documents_today, icon: '📄', sub: 'processed' },
  ];
  window.setSafeHTML(document.getElementById('dashStats'), stats.map(s =>
    `<div class="stat-card">
      <div class="stat-icon">${s.icon}</div>
      <div class="stat-label">${esc(s.label)}</div>
      <div class="stat-value">${s.value ?? 0}</div>
      <div class="stat-change">${esc(s.sub)}</div>
    </div>`
  ).join(''));
}

function renderRecentExecs(execs) {
  if (!execs.length) {
    window.setSafeHTML(
      document.getElementById('recentExecs'),
      '<div class="empty" style="padding:20px"><div class="empty-desc">No executions yet</div></div>'
    );
    return;
  }
  window.setSafeHTML(
    document.getElementById('recentExecs'),
    `<div class="timeline">${execs.map(e =>
      `<div class="timeline-item">
        <div class="timeline-dot ${e.status}">
          ${{ running:'▶', completed:'✓', failed:'✕', waiting_approval:'⏸', pending:'…' }[e.status] || '·'}
        </div>
        <div class="timeline-body">
          <div class="timeline-title">${esc(e.workflow_name)}</div>
          <div class="timeline-meta">${statusBadge(e.status)} · ${relTime(e.started_at)} · ${fmtDuration(e.duration_ms)}</div>
        </div>
      </div>`
    ).join('')}</div>`
  );
}

function renderPendingApprovals(approvals) {
  if (!approvals.length) {
    window.setSafeHTML(
      document.getElementById('pendingApprovals'),
      '<div class="empty" style="padding:20px"><div class="empty-desc">No pending approvals</div></div>'
    );
    return;
  }
  window.setSafeHTML(document.getElementById('pendingApprovals'), approvals.map(a =>
    `<div style="padding:10px 0;border-bottom:1px solid var(--border)">
      <div style="display:flex;align-items:center;justify-content:space-between">
        <div style="font-size:13px;font-weight:500">${esc(a.title)}</div>
        ${statusBadge(a.risk_level)}
      </div>
      <div style="font-size:11px;color:var(--text2);margin-top:2px">${relTime(a.created_at)}</div>
      <div style="margin-top:6px;display:flex;gap:6px">
        <button class="btn btn-success btn-sm" onclick="decideApproval('${esc(a.id)}','approved')">✓ Approve</button>
        <button class="btn btn-danger btn-sm" onclick="decideApproval('${esc(a.id)}','rejected')">✕ Reject</button>
      </div>
    </div>`
  ).join(''));
}

// ---------------------------------------------------------------------------
// Workflows
// ---------------------------------------------------------------------------
async function loadWorkflows() {
  const status = document.getElementById('wfStatusFilter')?.value || '';
  const path = `/workflows/${status ? `?status=${status}&` : '?'}limit=50`;
  const res = await api(path.replace('?&','?'));
  const grid = document.getElementById('workflowGrid');
  if (!res.ok) { window.setSafeHTML(
    grid,
    `<div class="empty"><div class="empty-desc">Error loading workflows</div></div>`
  ); return; }
  state.workflows = res.data;
  if (!res.data.length) {
    window.setSafeHTML(
      grid,
      `<div class="empty"><div class="empty-icon">🔄</div><div class="empty-title">No Workflows</div><div class="empty-desc">Create your first workflow to get started</div></div>`
    );
    return;
  }
  window.setSafeHTML(grid, res.data.map(wf => `
    <div class="workflow-card" onclick="openWorkflow('${esc(wf.id)}')">
      <div class="workflow-card-header">
        <div>
          <div class="workflow-name">${esc(wf.name)}</div>
          <div style="font-size:11px;color:var(--text3);margin-top:2px">${wf.nodes?.length || 0} nodes · v${wf.version}</div>
        </div>
        ${statusBadge(wf.status)}
      </div>
      <div class="workflow-desc">${esc(wf.description || 'No description')}</div>
      <div class="workflow-meta">
        ${(wf.tags || []).map(t => `<span class="badge badge-draft">${esc(t)}</span>`).join('')}
      </div>
      <div class="workflow-stats">
        <div class="workflow-stat"><div class="workflow-stat-val" style="color:var(--accent)">${wf.nodes?.length || 0}</div><div class="workflow-stat-lbl">Nodes</div></div>
        <div class="workflow-stat"><div class="workflow-stat-val">${relTime(wf.updated_at)}</div><div class="workflow-stat-lbl">Updated</div></div>
      </div>
      <div style="margin-top:10px;display:flex;gap:6px" onclick="event.stopPropagation()">
        <button class="btn btn-secondary btn-sm" onclick="editWorkflow('${esc(wf.id)}')">✏️ Edit</button>
        <button class="btn btn-success btn-sm" onclick="triggerWorkflow('${esc(wf.id)}')">▶ Run</button>
        <button class="btn btn-ghost btn-sm" onclick="deleteWorkflow('${esc(wf.id)}')">🗑</button>
      </div>
    </div>
  `).join(''));
}

function showCreateWorkflow() {
  showModal('Create Workflow',
    `<div class="form-group"><label class="form-label">Name</label><input type="text" id="mWfName" class="form-input" placeholder="My Workflow"></div>
     <div class="form-group"><label class="form-label">Description</label><textarea id="mWfDesc" class="form-textarea" placeholder="What does this workflow do?"></textarea></div>
     <div class="form-group"><label class="form-label">Tags (comma-separated)</label><input type="text" id="mWfTags" class="form-input" placeholder="email,automation"></div>`,
    `<button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
     <button class="btn btn-primary" onclick="createWorkflow()">Create</button>`
  );
}

async function createWorkflow() {
  const name = document.getElementById('mWfName').value.trim();
  if (!name) { toast('Error', 'Name is required', 'bad'); return; }
  const tags = document.getElementById('mWfTags').value.split(',').map(t=>t.trim()).filter(Boolean);
  const res = await api('/workflows/', { method: 'POST', body: JSON.stringify({
    name, description: document.getElementById('mWfDesc').value, tags
  })});
  if (!res.ok) { toast('Error', 'Failed to create workflow', 'bad'); return; }
  closeModal();
  toast('Created', `Workflow "${name}" created`, 'ok');
  loadWorkflows();
}

function openWorkflow(id) { editWorkflow(id); }

function editWorkflow(id) {
  const wf = state.workflows.find(w => w.id === id);
  if (!wf) return;
  state.builder.workflowId = id;
  state.builder.name = wf.name;
  state.builder.nodes = JSON.parse(JSON.stringify(wf.nodes || []));
  state.builder.connections = JSON.parse(JSON.stringify(wf.connections || []));
  document.getElementById('builderWfName').textContent = wf.name;
  showPage('builder');
  renderBuilder();
}

async function triggerWorkflow(id) {
  const res = await api('/executions/', { method: 'POST', body: JSON.stringify({ workflow_id: id, trigger_data: { source: 'manual' } })});
  if (!res.ok) { toast('Error', 'Failed to trigger workflow', 'bad'); return; }
  toast('Triggered', 'Workflow execution started', 'ok');
  loadExecutions();
}

async function deleteWorkflow(id) {
  if (!confirm('Delete this workflow?')) return;
  const res = await api(`/workflows/${id}`, { method: 'DELETE' });
  if (res.status !== 204 && !res.ok) { toast('Error', 'Failed to delete', 'bad'); return; }
  toast('Deleted', 'Workflow removed', 'ok');
  loadWorkflows();
}

// ---------------------------------------------------------------------------
// Templates
// ---------------------------------------------------------------------------
const TEMPLATES = [
  { name: 'Shipping Automation', desc: 'Email OCR → classify → approve high-value → ERP → notify', tags: ['shipping','ocr','approval'], icon: '📦', file: 'shipping_automation' },
  { name: 'Invoice Processing', desc: 'Upload → OCR → extract → approve → accounting sync', tags: ['invoice','finance','ocr'], icon: '🧾', file: 'invoice_automation' },
  { name: 'Customer Communication', desc: 'Email → intent classify → AI draft → review → send', tags: ['email','ai','customer-service'], icon: '💬', file: 'customer_communication' },
  { name: 'Approval Workflow', desc: 'Request → AI risk check → tiered approval → notify', tags: ['approval','risk','escalation'], icon: '✅', file: 'approval_workflow' },
];

function loadTemplates() {
  window.setSafeHTML(document.getElementById('templateGrid'), TEMPLATES.map(t => `
    <div class="workflow-card">
      <div class="workflow-card-header">
        <div>
          <div class="workflow-name">${t.icon} ${esc(t.name)}</div>
        </div>
      </div>
      <div class="workflow-desc">${esc(t.desc)}</div>
      <div class="workflow-meta">${t.tags.map(tag => `<span class="badge badge-draft">${esc(tag)}</span>`).join('')}</div>
      <div style="margin-top:10px;">
        <button class="btn btn-primary btn-sm" onclick="useTemplate('${esc(t.file)}','${esc(t.name)}')">Use Template</button>
      </div>
    </div>
  `).join(''));
}

async function useTemplate(file, name) {
  try {
    const r = await fetch(`/ai-automation/workflows/templates/${file}.json`);
    if (!r.ok) throw new Error('Template not found');
    const tpl = await r.json();
    const res = await api('/workflows/', { method: 'POST', body: JSON.stringify({ ...tpl, name }) });
    if (!res.ok) throw new Error('Failed to create');
    toast('Created', `Workflow "${name}" created from template`, 'ok');
    showPage('workflows');
  } catch (e) {
    // Fallback: create empty workflow with template name
    const res = await api('/workflows/', { method: 'POST', body: JSON.stringify({ name, description: `From template: ${name}`, tags: [] }) });
    if (res.ok) { toast('Created', `Workflow "${name}" created`, 'ok'); showPage('workflows'); }
    else toast('Error', e.message, 'bad');
  }
}

// ---------------------------------------------------------------------------
// Executions
// ---------------------------------------------------------------------------
async function loadExecutions() {
  const status = document.getElementById('execStatusFilter')?.value || '';
  const path = `/executions/${status ? `?status=${status}&` : '?'}limit=50`;
  const res = await api(path.replace('?&','?'));
  const tbody = document.getElementById('execTableBody');
  if (!res.ok) { window.setSafeHTML(
    tbody,
    `<tr><td colspan="6" style="text-align:center;color:var(--text3)">Error loading</td></tr>`
  ); return; }
  if (!res.data.length) { window.setSafeHTML(
    tbody,
    `<tr><td colspan="6" style="text-align:center;color:var(--text3);padding:24px">No executions</td></tr>`
  ); return; }
  window.setSafeHTML(tbody, res.data.map(e => `
    <tr>
      <td class="td-mono">${e.id.slice(0,8)}…</td>
      <td>${esc(e.workflow_name)}</td>
      <td>${statusBadge(e.status)}</td>
      <td style="color:var(--text2);font-size:12px">${relTime(e.started_at)}</td>
      <td style="color:var(--text2);font-size:12px">${fmtDuration(e.duration_ms)}</td>
      <td>
        <button class="btn btn-ghost btn-sm" onclick="viewExecution('${esc(e.id)}')">View</button>
        ${e.status === 'running' ? `<button class="btn btn-danger btn-sm" onclick="cancelExecution('${esc(e.id)}')">Cancel</button>` : ''}
      </td>
    </tr>
  `).join(''));
}

async function viewExecution(id) {
  const res = await api(`/executions/${id}`);
  if (!res.ok) { toast('Error', 'Could not load execution', 'bad'); return; }
  const e = res.data;
  const steps = e.steps || [];
  showModal(`Execution ${id.slice(0,8)}…`,
    `<div style="margin-bottom:12px">${statusBadge(e.status)} · ${relTime(e.started_at)} · ${fmtDuration(e.duration_ms)}</div>
     ${e.error ? `<div style="background:rgba(239,68,68,0.1);border:1px solid var(--red);border-radius:6px;padding:8px 12px;font-size:12px;color:var(--red);margin-bottom:12px">${esc(e.error)}</div>` : ''}
     <div class="timeline">${steps.map(s => `
       <div class="timeline-item">
         <div class="timeline-dot ${s.status}">${{completed:'✓',failed:'✕',running:'▶',pending:'…'}[s.status]||'·'}</div>
         <div class="timeline-body">
           <div class="timeline-title">${esc(s.node_type)}</div>
           <div class="timeline-meta">${statusBadge(s.status)} · ${fmtDuration(s.duration_ms)} ${s.error ? `· <span style="color:var(--red)">${esc(s.error)}</span>` : ''}</div>
         </div>
       </div>`).join('')}
     </div>`,
    `<button class="btn btn-secondary" onclick="closeModal()">Close</button>`
  );
}

async function cancelExecution(id) {
  const res = await api(`/executions/${id}/cancel`, { method: 'POST' });
  if (!res.ok) { toast('Error', 'Could not cancel', 'bad'); return; }
  toast('Cancelled', 'Execution cancelled', 'ok');
  loadExecutions();
}

// ---------------------------------------------------------------------------
// AI Monitor
// ---------------------------------------------------------------------------
const PROVIDER_INFO = {
  openai:   { icon: '🟢', name: 'OpenAI', color: 'var(--green)' },
  claude:   { icon: '🟣', name: 'Claude', color: 'var(--purple)' },
  gemini:   { icon: '🔵', name: 'Gemini', color: 'var(--accent)' },
  deepseek: { icon: '🟡', name: 'DeepSeek', color: 'var(--yellow)' },
  local:    { icon: '⚪', name: 'Local (Ollama)', color: 'var(--text3)' },
};

async function loadAIMonitor() {
  const [providersRes, usageRes] = await Promise.all([
    api('/ai/providers'),
    api('/ai/usage?days=7'),
  ]);

  const grid = document.getElementById('providerGrid');
  const configured = providersRes.ok ? providersRes.data : [];
  const allProviders = ['openai', 'claude', 'gemini', 'deepseek', 'local'];

  window.setSafeHTML(grid, allProviders.map(p => {
    const cfg = configured.find(c => c.provider === p);
    const info = PROVIDER_INFO[p] || { icon: '⚪', name: p };
    const enabled = cfg?.enabled ?? false;
    return `<div class="provider-card">
      <div class="provider-name">
        <div class="provider-dot ${enabled ? '' : 'disabled'}"></div>
        ${info.icon} ${info.name}
        <span style="margin-left:auto">${enabled ? '<span class="badge badge-active">ON</span>' : '<span class="badge badge-draft">OFF</span>'}</span>
      </div>
      ${cfg ? `
        <div class="provider-metric"><span class="provider-metric-label">Model</span><span class="provider-metric-value">${esc(cfg.default_model || '—')}</span></div>
        <div class="provider-metric"><span class="provider-metric-label">Rate limit</span><span class="provider-metric-value">${cfg.rate_limit_rpm || 60}/min</span></div>
      ` : `<div style="font-size:12px;color:var(--text3);margin-bottom:8px">Not configured</div>`}
      <button class="btn btn-secondary btn-sm" style="width:100%;margin-top:6px" onclick="configureProvider('${p}')">⚙️ Configure</button>
    </div>`;
  }).join(''));

  if (usageRes.ok && usageRes.data.length) renderAIUsage(usageRes.data);
}

function renderAIUsage(usage) {
  const max = Math.max(...usage.map(u => u.requests || 1));
  window.setSafeHTML(
    document.getElementById('aiUsageChart'),
    `<div class="chart-bar-wrap" style="padding:4px 0">${usage.map(u => `
      <div class="chart-bar-row">
        <div class="chart-bar-label">${esc(u.provider)}</div>
        <div class="chart-bar-track"><div class="chart-bar-fill" style="width:${(u.requests/max*100).toFixed(1)}%"></div></div>
        <div class="chart-bar-val">${u.requests} req</div>
      </div>`).join('')}
    </div>`
  );
}

function configureProvider(provider) {
  showModal(`Configure ${PROVIDER_INFO[provider]?.name || provider}`,
    `<div class="form-group"><label class="form-label">API Key</label>
       <input type="password" id="cfgKey" class="form-input" placeholder="sk-..."></div>
     <div class="form-group"><label class="form-label">Default Model</label>
       <input type="text" id="cfgModel" class="form-input" placeholder="${provider === 'local' ? 'llama3.2' : 'leave blank for default'}"></div>
     <div class="form-group"><label class="form-label">Base URL (optional)</label>
       <input type="text" id="cfgUrl" class="form-input" placeholder="https://api.${provider}.com/v1"></div>
     <div class="form-group" style="display:flex;align-items:center;gap:8px">
       <input type="checkbox" id="cfgEnabled" checked>
       <label class="form-label" style="margin:0">Enabled</label>
     </div>`,
    `<button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
     <button class="btn btn-primary" onclick="saveProvider('${provider}')">Save</button>`
  );
}

async function saveProvider(provider) {
  const body = {
    provider,
    api_key: document.getElementById('cfgKey').value || undefined,
    default_model: document.getElementById('cfgModel').value || undefined,
    base_url: document.getElementById('cfgUrl').value || undefined,
    enabled: document.getElementById('cfgEnabled').checked,
    rate_limit_rpm: 60,
  };
  const res = await api(`/ai/providers/${provider}`, { method: 'PUT', body: JSON.stringify(body) });
  if (!res.ok) { toast('Error', 'Failed to save provider', 'bad'); return; }
  closeModal();
  toast('Saved', `${provider} configured`, 'ok');
  loadAIMonitor();
}

// ---------------------------------------------------------------------------
// OCR Review
// ---------------------------------------------------------------------------
async function loadOCR() {
  const reviewOnly = document.getElementById('ocrReviewOnly')?.checked;
  const path = `/ocr/results${reviewOnly ? '?needs_review=true&' : '?'}limit=50`;
  const res = await api(path.replace('?&','?'));
  const grid = document.getElementById('ocrGrid');
  if (!res.ok) { window.setSafeHTML(
    grid,
    `<div class="empty"><div class="empty-desc">Error loading OCR results</div></div>`
  ); return; }
  if (!res.data.length) {
    window.setSafeHTML(
      grid,
      `<div class="empty"><div class="empty-icon">📄</div><div class="empty-title">No Documents</div><div class="empty-desc">No OCR results to review</div></div>`
    );
    return;
  }
  const reviewCount = res.data.filter(d => d.needs_review).length;
  const badge = document.getElementById('ocrBadge');
  badge.textContent = reviewCount;
  badge.style.display = reviewCount ? '' : 'none';

  window.setSafeHTML(grid, res.data.map(doc => {
    const conf = doc.confidence || 0;
    const confClass = conf >= 0.8 ? '' : conf >= 0.6 ? 'med' : 'low';
    return `<div class="ocr-card ${doc.needs_review ? 'needs-review' : ''}">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px">
        <div style="font-size:12px;font-weight:600">${esc(doc.document_type || 'Unknown')}</div>
        ${doc.needs_review ? '<span class="badge badge-pending">Needs Review</span>' : '<span class="badge badge-completed">Validated</span>'}
      </div>
      <div class="ocr-confidence">
        <div class="ocr-confidence-bar ${confClass}" style="width:${(conf*100).toFixed(0)}%"></div>
      </div>
      <div style="font-size:11px;color:var(--text3);margin-bottom:6px">Confidence: ${(conf*100).toFixed(0)}%</div>
      <div class="ocr-fields">${(doc.fields || []).slice(0,4).map(f =>
        `<div class="ocr-field"><span class="ocr-field-name">${esc(f.name)}</span><span class="ocr-field-value">${esc(f.value || '—')}</span></div>`
      ).join('')}</div>
      ${doc.review_reason ? `<div style="font-size:11px;color:var(--yellow);margin-top:6px">⚠ ${esc(doc.review_reason)}</div>` : ''}
    </div>`;
  }).join(''));
}

// ---------------------------------------------------------------------------
// Approvals
// ---------------------------------------------------------------------------
async function loadApprovals() {
  const status = document.getElementById('approvalStatusFilter')?.value || '';
  const path = `/approvals/${status ? `?status=${status}&` : '?'}limit=50`;
  const res = await api(path.replace('?&','?'));
  const grid = document.getElementById('approvalGrid');
  if (!res.ok) { window.setSafeHTML(
    grid,
    `<div class="empty"><div class="empty-desc">Error loading</div></div>`
  ); return; }
  if (!res.data.length) {
    window.setSafeHTML(
      grid,
      `<div class="empty"><div class="empty-icon">✅</div><div class="empty-title">All Clear</div><div class="empty-desc">No approvals matching filter</div></div>`
    );
    return;
  }
  const pendingCount = res.data.filter(a => a.status === 'pending').length;
  const badge = document.getElementById('approvalBadge');
  badge.textContent = pendingCount;
  badge.style.display = pendingCount ? '' : 'none';

  window.setSafeHTML(grid, res.data.map(a => `
    <div class="approval-card">
      <div class="approval-header">
        <div>
          <div class="approval-title">${esc(a.title)}</div>
          <div class="approval-meta">
            ${statusBadge(a.risk_level)} · ${statusBadge(a.status)} ·
            ${a.assignee_group ? `Group: ${esc(a.assignee_group)} · ` : ''}
            ${relTime(a.created_at)}
          </div>
        </div>
      </div>
      ${a.description ? `<div style="font-size:12px;color:var(--text2)">${esc(a.description)}</div>` : ''}
      ${a.status === 'pending' ? `
        <div class="approval-actions">
          <button class="btn btn-success btn-sm" onclick="decideApproval('${esc(a.id)}','approved')">✓ Approve</button>
          <button class="btn btn-danger btn-sm" onclick="decideApproval('${esc(a.id)}','rejected')">✕ Reject</button>
          <button class="btn btn-secondary btn-sm" onclick="viewApprovalDetail('${esc(a.id)}')">View Details</button>
        </div>
      ` : `<div style="margin-top:8px;font-size:12px;color:var(--text2)">
        Decision: <strong>${a.decision || a.status}</strong>
        ${a.decided_by ? ` by ${esc(a.decided_by)}` : ''}
        ${a.decision_notes ? `<br><em>${esc(a.decision_notes)}</em>` : ''}
      </div>`}
    </div>
  `).join(''));
}

async function decideApproval(id, decision) {
  const notes = decision === 'rejected' ? prompt('Rejection reason (optional):') : null;
  const res = await api(`/approvals/${id}/decide`, {
    method: 'POST',
    body: JSON.stringify({ status: decision, decided_by: 'current_user', notes }),
  });
  if (!res.ok) { toast('Error', 'Failed to record decision', 'bad'); return; }
  toast(decision === 'approved' ? 'Approved' : 'Rejected', 'Decision recorded', decision === 'approved' ? 'ok' : 'bad');
  loadApprovals();
}

function viewApprovalDetail(id) {
  api(`/approvals/${id}`).then(res => {
    if (!res.ok) { toast('Error','Could not load', 'bad'); return; }
    const a = res.data;
    showModal(a.title,
      `<div style="margin-bottom:12px">${statusBadge(a.risk_level)} ${statusBadge(a.status)}</div>
       <div style="font-size:13px;margin-bottom:8px">${esc(a.description || '')}</div>
       <pre style="background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:12px;font-size:11px;overflow:auto;max-height:200px"><code>${esc(JSON.stringify(a.data||{},null,2))}</code></pre>`,
      `<button class="btn btn-success" onclick="closeModal();decideApproval('${esc(a.id)}','approved')">✓ Approve</button>
       <button class="btn btn-danger" onclick="closeModal();decideApproval('${esc(a.id)}','rejected')">✕ Reject</button>
       <button class="btn btn-secondary" onclick="closeModal()">Close</button>`
    );
  });
}

// ---------------------------------------------------------------------------
// Analytics
// ---------------------------------------------------------------------------
async function loadAnalytics() {
  const days = document.getElementById('analyticsDays')?.value || 7;
  const [wfRes, timelineRes] = await Promise.all([
    api('/analytics/workflows'),
    api(`/analytics/executions/timeline?days=${days}`),
  ]);
  if (wfRes.ok) renderAnalyticsTable(wfRes.data);
  if (timelineRes.ok) renderTimeline(timelineRes.data);
}

function renderAnalyticsTable(data) {
  const tbody = document.getElementById('analyticsTableBody');
  if (!data.length) { window.setSafeHTML(
    tbody,
    `<tr><td colspan="6" style="text-align:center;color:var(--text3);padding:24px">No data</td></tr>`
  ); return; }
  window.setSafeHTML(tbody, data.map(w => `
    <tr>
      <td>${esc(w.workflow_name)}</td>
      <td>${w.total_executions}</td>
      <td style="color:var(--green)">${w.successful}</td>
      <td style="color:var(--red)">${w.failed}</td>
      <td class="td-mono">${fmtDuration(w.avg_duration_ms)}</td>
      <td><div style="display:flex;align-items:center;gap:8px">
        <div class="chart-bar-track" style="width:80px"><div class="chart-bar-fill" style="width:${w.success_rate.toFixed(0)}%;background:${w.success_rate>80?'var(--green)':w.success_rate>50?'var(--yellow)':'var(--red)'}"></div></div>
        <span style="font-size:12px">${w.success_rate.toFixed(0)}%</span>
      </div></td>
    </tr>
  `).join(''));
}

function renderTimeline(data) {
  if (!data.length) { window.setSafeHTML(
    document.getElementById('timelineChart'),
    '<div class="empty" style="padding:20px"><div class="empty-desc">No execution data</div></div>'
  ); return; }
  const maxTotal = Math.max(...data.map(d => d.total), 1);
  window.setSafeHTML(
    document.getElementById('timelineChart'),
    `<div class="chart-bar-wrap" style="padding:4px 0">
      ${data.map(d => `<div class="chart-bar-row">
        <div class="chart-bar-label" style="min-width:90px">${esc(d.date)}</div>
        <div class="chart-bar-track" style="position:relative">
          <div class="chart-bar-fill" style="width:${(d.total/maxTotal*100).toFixed(1)}%;background:var(--accent)"></div>
        </div>
        <div class="chart-bar-val">${d.total} runs</div>
      </div>`).join('')}
    </div>`
  );
}

// ---------------------------------------------------------------------------
// Search
// ---------------------------------------------------------------------------
async function doSearch() {
  const q = document.getElementById('searchInput').value.trim();
  if (!q) return;
  const res = await api('/search/', { method: 'POST', body: JSON.stringify({ query: q, tenant_id: state.tenant }) });
  const el = document.getElementById('searchResults');
  if (!res.ok) { window.setSafeHTML(el, `<div class="empty"><div class="empty-desc">Search failed</div></div>`); return; }
  const { results, total, took_ms } = res.data;
  if (!results.length) { window.setSafeHTML(
    el,
    `<div class="empty"><div class="empty-desc">No results for "${esc(q)}"</div></div>`
  ); return; }
  window.setSafeHTML(
    el,
    `<div style="font-size:12px;color:var(--text3);margin-bottom:10px">${total} results (${took_ms}ms)</div>
      ${results.map(r => `<div class="search-result" onclick="navigateToResult('${esc(r.type)}','${esc(r.id)}')">
        <div class="search-result-type">${esc(r.type)}</div>
        <div class="search-result-title">${esc(r.title)}</div>
        ${r.snippet ? `<div class="search-result-snippet">${esc(r.snippet)}</div>` : ''}
      </div>`).join('')}`
  );
}

function navigateToResult(type, id) {
  if (type === 'workflow') { showPage('workflows'); }
  else if (type === 'execution') { showPage('executions'); viewExecution(id); }
}

// ---------------------------------------------------------------------------
// Workflow Builder
// ---------------------------------------------------------------------------
const NODE_PALETTE = [
  { category: 'Triggers', nodes: [
    { type: 'trigger_email', label: 'Email Trigger', icon: '📧', color: 'var(--accent)' },
    { type: 'trigger_webhook', label: 'Webhook Trigger', icon: '🔗', color: 'var(--cyan)' },
    { type: 'trigger_schedule', label: 'Schedule', icon: '⏰', color: 'var(--purple)' },
    { type: 'trigger_manual', label: 'Manual', icon: '👆', color: 'var(--text3)' },
  ]},
  { category: 'AI', nodes: [
    { type: 'ai_classify', label: 'Classify', icon: '🏷', color: 'var(--purple)' },
    { type: 'ai_extract', label: 'Extract', icon: '📤', color: 'var(--purple)' },
    { type: 'ai_summarize', label: 'Summarize', icon: '📝', color: 'var(--purple)' },
    { type: 'ai_generate', label: 'Generate', icon: '✨', color: 'var(--purple)' },
    { type: 'ai_sentiment', label: 'Sentiment', icon: '💭', color: 'var(--purple)' },
  ]},
  { category: 'OCR', nodes: [
    { type: 'ocr_process', label: 'OCR Process', icon: '📄', color: 'var(--yellow)' },
    { type: 'ocr_validate', label: 'OCR Validate', icon: '✔️', color: 'var(--yellow)' },
  ]},
  { category: 'Logic', nodes: [
    { type: 'condition', label: 'Condition', icon: '◇', color: 'var(--orange)' },
    { type: 'switch', label: 'Switch', icon: '⇌', color: 'var(--orange)' },
    { type: 'delay', label: 'Delay', icon: '⏳', color: 'var(--text2)' },
    { type: 'merge', label: 'Merge', icon: '⊕', color: 'var(--text2)' },
  ]},
  { category: 'Approval', nodes: [
    { type: 'approval_request', label: 'Approval', icon: '✋', color: 'var(--red)' },
    { type: 'approval_gate', label: 'Gate', icon: '🚦', color: 'var(--red)' },
  ]},
  { category: 'Actions', nodes: [
    { type: 'send_email', label: 'Send Email', icon: '📨', color: 'var(--green)' },
    { type: 'http_request', label: 'HTTP Request', icon: '🌐', color: 'var(--cyan)' },
    { type: 'transform', label: 'Transform', icon: '⚙️', color: 'var(--text2)' },
    { type: 'log', label: 'Log', icon: '📋', color: 'var(--text3)' },
    { type: 'search', label: 'Search', icon: '🔍', color: 'var(--accent)' },
    { type: 'agent_run', label: 'Run Agent', icon: '🤖', color: 'var(--purple)' },
  ]},
];

const NODE_COLORS = {};
NODE_PALETTE.forEach(cat => cat.nodes.forEach(n => { NODE_COLORS[n.type] = n.color; }));
const NODE_ICONS = {};
NODE_PALETTE.forEach(cat => cat.nodes.forEach(n => { NODE_ICONS[n.type] = n.icon; }));

function renderBuilder() {
  renderPalette();
  renderCanvas();
}

function renderPalette() {
  window.setSafeHTML(document.getElementById('nodePalette'), NODE_PALETTE.map(cat =>
    `<div class="node-category">${cat.category}</div>` +
    cat.nodes.map(n =>
      `<div class="node-item" draggable="true" data-node-type="${n.type}"
        ondragstart="onNodeDragStart(event,'${n.type}')">
        <div class="node-dot" style="background:${n.color}"></div>${n.icon} ${n.label}
      </div>`
    ).join('')
  ).join(''));
}

function onNodeDragStart(e, type) { e.dataTransfer.setData('node_type', type); }

function renderCanvas() {
  const canvas = document.getElementById('flowCanvas');
  window.setSafeHTML(canvas, state.builder.nodes.map(n => renderNode(n)).join(''));
  renderConnections();
  canvas.querySelectorAll('.flow-node').forEach(el => initNodeDrag(el));

  const wrap = document.getElementById('canvasWrap');
  wrap.ondragover = e => e.preventDefault();
  wrap.ondrop = e => {
    e.preventDefault();
    const type = e.dataTransfer.getData('node_type');
    if (!type) return;
    const rect = wrap.getBoundingClientRect();
    addNode(type, { x: e.clientX - rect.left - 80, y: e.clientY - rect.top - 30 });
  };
}

function renderNode(node) {
  const color = NODE_COLORS[node.type] || 'var(--text3)';
  const icon = NODE_ICONS[node.type] || '⬡';
  const selected = state.builder.selectedNodeId === node.id;
  return `<div class="flow-node ${selected ? 'selected' : ''}" id="node-${node.id}"
      style="left:${node.position.x}px;top:${node.position.y}px"
      onclick="selectNode('${node.id}')"
      data-node-id="${node.id}">
    <div class="flow-node-port in" data-port="in" data-node="${node.id}"></div>
    <div class="flow-node-header">
      <span class="flow-node-icon" style="color:${color}">${icon}</span>
      <div>
        <div class="flow-node-title">${esc(node.label)}</div>
        <div class="flow-node-type">${esc(node.type)}</div>
      </div>
    </div>
    <div class="flow-node-port out" data-port="out" data-node="${node.id}"></div>
  </div>`;
}

function renderConnections() {
  const svg = document.getElementById('connectionsSvg');
  window.setSafeHTML(svg, state.builder.connections.map(conn => {
    const src = document.getElementById(`node-${conn.source_id}`);
    const tgt = document.getElementById(`node-${conn.target_id}`);
    if (!src || !tgt) return '';
    const s = { x: src.offsetLeft + src.offsetWidth, y: src.offsetTop + src.offsetHeight / 2 };
    const t = { x: tgt.offsetLeft, y: tgt.offsetTop + tgt.offsetHeight / 2 };
    const cx = (s.x + t.x) / 2;
    return `<path class="connection-path" d="M${s.x},${s.y} C${cx},${s.y} ${cx},${t.y} ${t.x},${t.y}"/>`;
  }).join(''));
}

function selectNode(id) {
  state.builder.selectedNodeId = id;
  document.querySelectorAll('.flow-node').forEach(n => n.classList.toggle('selected', n.dataset.nodeId === id));
  renderNodeProps(id);
}

function renderNodeProps(id) {
  const node = state.builder.nodes.find(n => n.id === id);
  if (!node) return;
  const icon = NODE_ICONS[node.type] || '⬡';
  window.setSafeHTML(document.getElementById('propsContent'), `
    <div style="margin-bottom:12px;display:flex;align-items:center;gap:8px">
      <span style="font-size:20px">${icon}</span>
      <div><div style="font-weight:600">${esc(node.label)}</div><div style="font-size:11px;color:var(--text3)">${esc(node.type)}</div></div>
    </div>
    <div class="form-group">
      <label class="form-label">Label</label>
      <input type="text" class="form-input" value="${esc(node.label)}"
        onchange="updateNodeLabel('${id}',this.value)">
    </div>
    <div class="form-group">
      <label class="form-label">Config (JSON)</label>
      <textarea class="form-textarea" style="font-family:monospace;font-size:11px;min-height:120px"
        onchange="updateNodeConfig('${id}',this.value)">${esc(JSON.stringify(node.config||{},null,2))}</textarea>
    </div>
    <button class="btn btn-danger btn-sm" style="width:100%" onclick="removeNode('${id}')">🗑 Remove Node</button>
  `);
}

function updateNodeLabel(id, label) {
  const node = state.builder.nodes.find(n => n.id === id);
  if (node) { node.label = label; document.querySelector(`#node-${id} .flow-node-title`).textContent = label; }
}

function updateNodeConfig(id, json) {
  try {
    const config = JSON.parse(json);
    const node = state.builder.nodes.find(n => n.id === id);
    if (node) node.config = config;
  } catch { /* invalid JSON */ }
}

function addNode(type, position) {
  const id = 'n' + Date.now();
  const palette = NODE_PALETTE.flatMap(c => c.nodes).find(n => n.type === type);
  const node = { id, type, label: palette?.label || type, config: {}, position };
  state.builder.nodes.push(node);
  const canvas = document.getElementById('flowCanvas');
  const el = document.createElement('div');
  el.outerHTML = renderNode(node);
  canvas.insertAdjacentHTML('beforeend', renderNode(node));
  initNodeDrag(document.getElementById(`node-${id}`));
}

function removeNode(id) {
  state.builder.nodes = state.builder.nodes.filter(n => n.id !== id);
  state.builder.connections = state.builder.connections.filter(c => c.source_id !== id && c.target_id !== id);
  if (state.builder.selectedNodeId === id) {
    state.builder.selectedNodeId = null;
    document.getElementById('propsContent').textContent = 'Select a node to edit properties';
  }
  renderCanvas();
}

function initNodeDrag(el) {
  if (!el) return;
  el.addEventListener('mousedown', e => {
    if (e.target.classList.contains('flow-node-port')) return;
    const startX = e.clientX - el.offsetLeft;
    const startY = e.clientY - el.offsetTop;
    const onMove = ev => {
      el.style.left = (ev.clientX - startX) + 'px';
      el.style.top = (ev.clientY - startY) + 'px';
      renderConnections();
      const id = el.dataset.nodeId;
      const node = state.builder.nodes.find(n => n.id === id);
      if (node) { node.position = { x: ev.clientX - startX, y: ev.clientY - startY }; }
    };
    const onUp = () => { document.removeEventListener('mousemove', onMove); document.removeEventListener('mouseup', onUp); };
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
    e.preventDefault();
  });
}

function autoLayout() {
  const perRow = 4;
  state.builder.nodes.forEach((n, i) => {
    n.position = { x: 120 + (i % perRow) * 240, y: 120 + Math.floor(i / perRow) * 120 };
  });
  renderCanvas();
}

async function saveWorkflow() {
  if (!state.builder.workflowId) {
    const name = state.builder.name;
    const res = await api('/workflows/', { method: 'POST', body: JSON.stringify({
      name, nodes: state.builder.nodes, connections: state.builder.connections
    })});
    if (!res.ok) { toast('Error', 'Failed to save', 'bad'); return; }
    state.builder.workflowId = res.data.id;
    toast('Saved', `Workflow "${name}" saved`, 'ok');
  } else {
    const res = await api(`/workflows/${state.builder.workflowId}`, { method: 'PUT', body: JSON.stringify({
      name: state.builder.name, nodes: state.builder.nodes, connections: state.builder.connections
    })});
    if (!res.ok) { toast('Error', 'Failed to save', 'bad'); return; }
    toast('Saved', 'Workflow updated', 'ok');
  }
}

async function activateWorkflow() {
  if (!state.builder.workflowId) { await saveWorkflow(); }
  const res = await api(`/workflows/${state.builder.workflowId}/activate`, { method: 'POST' });
  if (!res.ok) { toast('Error', 'Failed to activate', 'bad'); return; }
  toast('Activated', 'Workflow is now active', 'ok');
}

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------
function activateSettingsTab(tab) {
  document.querySelectorAll('[data-settings-tab]').forEach(t => t.classList.toggle('active', t.dataset.settingsTab === tab));
}

function saveSettings() {
  const t = document.getElementById('settingsTenant').value.trim();
  if (t) setTenant(t);
  toast('Saved', 'Settings saved', 'ok');
}

// ---------------------------------------------------------------------------
// Quick Run
// ---------------------------------------------------------------------------
document.getElementById('quickRunBtn').onclick = async () => {
  const res = await api('/workflows/?status=active&limit=20');
  if (!res.ok || !res.data.length) { toast('No active workflows', 'Activate a workflow first', 'info'); return; }
  showModal('Run a Workflow',
    `<div class="form-group"><label class="form-label">Select workflow</label>
     <select id="qrWf" class="form-select">${res.data.map(w => `<option value="${w.id}">${esc(w.name)}</option>`).join('')}</select></div>
     <div class="form-group"><label class="form-label">Trigger Data (JSON)</label>
     <textarea id="qrData" class="form-textarea" style="font-family:monospace;font-size:12px">{"source":"manual"}</textarea></div>`,
    `<button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
     <button class="btn btn-primary" onclick="runQuickWorkflow()">▶ Run</button>`
  );
};

async function runQuickWorkflow() {
  const id = document.getElementById('qrWf').value;
  let data = {};
  try { data = JSON.parse(document.getElementById('qrData').value); } catch { toast('Error', 'Invalid JSON', 'bad'); return; }
  const res = await api('/executions/', { method: 'POST', body: JSON.stringify({ workflow_id: id, trigger_data: data }) });
  if (!res.ok) { toast('Error', 'Failed to trigger', 'bad'); return; }
  closeModal();
  toast('Running', 'Workflow execution started', 'ok');
  showPage('executions');
}

// ---------------------------------------------------------------------------
// Auto-refresh pending counts
// ---------------------------------------------------------------------------
setInterval(async () => {
  if (state.currentPage === 'dashboard') loadDashboard();
  const pendRes = await api('/approvals/?status=pending&limit=1');
  if (pendRes.ok) {
    const badge = document.getElementById('approvalBadge');
    const count = pendRes.data.length;
    badge.textContent = count;
    badge.style.display = count ? '' : 'none';
  }
}, 30000);

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------
function init() {
  setTenant(state.tenant);
  document.getElementById('settingsTenant').value = state.tenant;
  showPage('dashboard');
}

init();
