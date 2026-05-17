'use strict';

// ── API base ─────────────────────────────────────────────
const API = '/api/v1/threat';
const WS_URL = `ws://${location.host}/api/v1/ws/alerts`;

// ── Navigation ───────────────────────────────────────────
const VIEW_META = {
  'dashboard':       { title: 'Threat Dashboard',       sub: 'Real-time security overview' },
  'feed':            { title: 'Live Threat Feed',        sub: 'Recent lookalike domain detections' },
  'scam-emails':     { title: 'Scam Email Center',       sub: 'Review & manage flagged emails' },
  'lookalike':       { title: 'Lookalike Monitor',       sub: 'Brand impersonation intelligence' },
  'domain-analyser': { title: 'Domain Analyser',         sub: 'Inspect any domain for threat indicators' },
  'blacklist':       { title: 'Blacklist Management',    sub: 'Blocked senders & domains' },
  'whitelist':       { title: 'Trusted Senders',         sub: 'Whitelisted senders & domains' },
  'audit':           { title: 'Audit Log',               sub: 'Record of all security actions' },
};

document.querySelectorAll('.threat-nav-btn').forEach(btn => {
  btn.addEventListener('click', () => showView(btn.dataset.view));
});

function showView(name) {
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.querySelectorAll('.threat-nav-btn').forEach(b => { b.classList.remove('active'); b.removeAttribute('aria-current'); });
  const view = document.getElementById('view-' + name);
  if (view) view.classList.add('active');
  const btn = document.querySelector(`[data-view="${name}"]`);
  if (btn) { btn.classList.add('active'); btn.setAttribute('aria-current', 'page'); }
  const meta = VIEW_META[name] || {};
  document.getElementById('viewTitle').textContent = meta.title || name;
  document.getElementById('viewSub').textContent = meta.sub || '';
  loadView(name);
}

function loadView(name) {
  if (name === 'dashboard')       loadDashboard();
  else if (name === 'feed')       loadFeed();
  else if (name === 'scam-emails') loadScamEmails();
  else if (name === 'lookalike')  loadLookalike();
  else if (name === 'blacklist')  loadBlacklist();
  else if (name === 'whitelist')  loadWhitelist();
  else if (name === 'audit')      loadAudit();
}

document.getElementById('refreshBtn').addEventListener('click', () => {
  const active = document.querySelector('.threat-nav-btn.active');
  if (active) loadView(active.dataset.view);
});

// ── Fetch helper ─────────────────────────────────────────
let localSessionReady = null;
async function ensureLocalSession() {
  if (!localSessionReady) {
    localSessionReady = fetch('/api/v1/session/bootstrap', {
      method: 'POST',
      credentials: 'same-origin',
    }).catch(() => null);
  }
  await localSessionReady;
}

async function api(path, opts = {}) {
  await ensureLocalSession();
  // FIX: only set Content-Type when a body is present (avoids proxy rejections on GET)
  const hdrs = opts.body != null ? { 'Content-Type': 'application/json' } : {};
  const res = await fetch(API + path, { ...opts, credentials: 'same-origin', headers: { ...hdrs, ...opts.headers } });
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${await res.text()}`);
  return res.json();
}

// ── Severity helpers ──────────────────────────────────────
function scoreToSeverity(score) {
  if (score <= 20) return 'low';
  if (score <= 55) return 'medium';
  if (score <= 80) return 'high';
  return 'critical';
}

function severityBadge(s) {
  return `<span class="severity-badge ${esc(s)}">${esc(s)}</span>`;
}

function scoreBar(score) {
  const sev = scoreToSeverity(score);
  const width = Math.max(0, Math.min(100, Math.round((Number(score) || 0) / 5) * 5));
  return `<div class="score-bar-wrap">
    <div class="score-bar-bg"><div class="score-bar-fill ${sev} score-w-${width}"></div></div>
    <span class="score-number severity-text-${esc(sev)}">${esc(score)}</span>
  </div>`;
}

function threatTypeBadge(t) {
  return t ? `<span class="threat-type-badge">${esc(t.replace(/_/g, ' '))}</span>` : '—';
}

function fmtDate(d) {
  if (!d) return '—';
  try { return new Date(d).toLocaleString(); } catch { return esc(d); }
}

function reasonTags(reasons) {
  if (!reasons || !reasons.length) return '—';
  return `<ul class="reasons-list">${reasons.slice(0,4).map(r => `<li class="reason-tag">${esc(r)}</li>`).join('')}${reasons.length > 4 ? `<li class="reason-tag">+${reasons.length-4} more</li>` : ''}</ul>`;
}

// ── Dashboard ─────────────────────────────────────────────
async function loadDashboard() {
  try {
    const data = await api('/stats');
    const s = data.stats;
    document.getElementById('statsGrid').innerHTML = `
      <div class="stat-card critical">
        <div class="stat-label">Scam Blocked</div>
        <div class="stat-value">${esc(s.scam_blocked)}</div>
        <div class="stat-sub">All time</div>
      </div>
      <div class="stat-card warning">
        <div class="stat-label">Pending Review</div>
        <div class="stat-value">${esc(s.pending_review)}</div>
        <div class="stat-sub">Need attention</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Lookalike Alerts</div>
        <div class="stat-value">${esc(s.lookalike_alerts_active)}</div>
        <div class="stat-sub">${esc(s.lookalike_alerts_total)} total</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Blacklisted</div>
        <div class="stat-value">${esc(s.blacklisted_entries)}</div>
        <div class="stat-sub">Senders & domains</div>
      </div>
      <div class="stat-card safe">
        <div class="stat-label">Trusted</div>
        <div class="stat-value">${esc(s.trusted_entries)}</div>
        <div class="stat-sub">Whitelisted</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Total Emails</div>
        <div class="stat-value">${esc(s.total_emails)}</div>
        <div class="stat-sub">Processed</div>
      </div>
    `;

    // Update badges
    setNavBadge('feedBadge', s.lookalike_alerts_active);
    setNavBadge('scamBadge', s.scam_blocked);

    // Brands table
    const brands = s.top_impersonated_brands || [];
    document.getElementById('brandsBody').innerHTML = brands.length
      ? brands.map(b => `<tr>
          <td><b>${esc(b.brand)}</b></td>
          <td>${Number(b.count) || 0}</td>
          <td>${severityBadge(b.count > 5 ? 'critical' : b.count > 2 ? 'high' : 'medium')}</td>
        </tr>`).join('')
      : '<tr><td colspan="3" class="empty-state"><p>No data</p></td></tr>';

    // Types table
    const types = s.threat_type_breakdown || {};
    const typeRows = Object.entries(types);
    document.getElementById('typesBody').innerHTML = typeRows.length
      ? typeRows.map(([t, c]) => `<tr><td>${threatTypeBadge(t)}</td><td>${Number(c) || 0}</td></tr>`).join('')
      : '<tr><td colspan="2" class="empty-state"><p>No data</p></td></tr>';

  } catch (e) {
    document.getElementById('statsGrid').innerHTML = `<div class="stat-card"><div class="stat-label">Error</div><div class="stat-value error-value">${esc(e.message)}</div></div>`;
  }
}

// ── Live Feed ─────────────────────────────────────────────
let feedOffset = 0;
const FEED_LIMIT = 50;

async function loadFeed() {
  const status = document.getElementById('feedStatusFilter')?.value || '';
  const search = document.getElementById('feedSearch')?.value.trim() || '';
  let url = `/feed?limit=${FEED_LIMIT}&offset=${feedOffset}`;
  if (status) url += `&status=${encodeURIComponent(status)}`;
  if (search) url += `&search=${encodeURIComponent(search)}`;
  try {
    const data = await api(url);
    const items = data.feed || [];
    document.getElementById('feedBody').innerHTML = items.length
      ? items.map(f => `<tr>
          <td><b class="text-primary">${esc(f.detected_domain) || '—'}</b></td>
          <td>${f.impersonated_brand ? `<b>${esc(f.impersonated_brand)}</b><br><small class="text-muted">${esc(f.impersonated_domain || '')}</small>` : '—'}</td>
          <td>${threatTypeBadge(f.threat_type)}</td>
          <td>${scoreBar(f.confidence_score || 0)}</td>
          <td class="text-muted-xs">${esc(f.sender_email || '—')}</td>
          <td class="text-xs">${fmtDate(f.created_at)}</td>
          <td>${severityBadge(f.status === 'confirmed' ? 'critical' : f.status === 'active' ? 'high' : 'low')}</td>
          <td><button class="btn btn-ghost btn-sm" data-action="dismiss-alert" data-id="${esc(f.id)}" type="button">Dismiss</button></td>
        </tr>`).join('')
      : '<tr><td colspan="8" class="empty-state"><p>No threats detected</p></td></tr>';

    document.getElementById('feedPagination').innerHTML = `
      <span class="page-info">Showing ${feedOffset+1}–${Math.min(feedOffset+FEED_LIMIT, Number(data.total))} of ${esc(data.total)}</span>
      ${feedOffset > 0 ? `<button class="btn btn-ghost btn-sm" data-action="feed-page" data-dir="-1" type="button">← Prev</button>` : ''}
      ${feedOffset + FEED_LIMIT < data.total ? `<button class="btn btn-ghost btn-sm" data-action="feed-page" data-dir="1" type="button">Next →</button>` : ''}
    `;
  } catch (e) {
    document.getElementById('feedBody').innerHTML = `<tr><td colspan="8" class="table-error">${esc(e.message)}</td></tr>`;
  }
}

function feedPage(dir) {
  feedOffset = Math.max(0, feedOffset + dir * FEED_LIMIT);
  loadFeed();
}

async function dismissAlert(id) {
  try {
    await api(`/lookalike/${id}/dismiss`, { method: 'POST' });
    showToast('Alert dismissed', '', 'low');
    loadFeed();
  } catch (e) { showToast('Dismiss failed', e.message, 'high'); }
}

// ── Scam Emails ───────────────────────────────────────────
async function loadScamEmails() {
  const cat = document.getElementById('emailCategoryFilter')?.value || 'Scam';
  try {
    const data = await api(`/emails/scam?category=${encodeURIComponent(cat)}&limit=100`);
    const emails = data.emails || [];
    document.getElementById('scamEmailsBody').innerHTML = emails.length
      ? emails.map(e => `<tr>
          <td class="subject-cell" title="${esc(e.subject)}">${esc(e.subject || '(no subject)')}</td>
          <td class="text-xs">${esc(e.sender || '')} <br><span class="text-muted">${esc(e.sender_email || '')}</span></td>
          <td>${e.category === 'Scam' ? severityBadge('critical') : severityBadge('review')}</td>
          <td>${scoreBar(Math.round((e.confidence || 0)*100))}</td>
          <td>${reasonTags(e.scam_reasons)}</td>
          <td class="text-xs">${fmtDate(e.date)}</td>
          <td class="nowrap">
            <button class="btn btn-success btn-sm" data-action="restore-email" data-id="${esc(e.id)}" type="button">Restore</button>
            <button class="btn btn-danger btn-sm" data-action="confirm-scam" data-id="${esc(e.id)}" type="button">Confirm</button>
          </td>
        </tr>`).join('')
      : '<tr><td colspan="7" class="empty-state"><p>No emails in this category</p></td></tr>';
  } catch (err) {
    document.getElementById('scamEmailsBody').innerHTML = `<tr><td colspan="7" class="table-error">${esc(err.message)}</td></tr>`;
  }
}

async function restoreEmail(id) {
  try {
    await api(`/emails/${id}/restore`, { method: 'POST' });
    showToast('Email restored to Inbox', '', 'low');
    loadScamEmails();
  } catch (e) { showToast('Restore failed', e.message, 'high'); }
}

async function confirmScam(id) {
  try {
    await api(`/emails/${id}/confirm`, { method: 'POST', body: JSON.stringify({ block_sender: true }) });
    showToast('Email confirmed as scam. Sender blocked.', '', 'medium');
    loadScamEmails();
    loadDashboard();
  } catch (e) { showToast('Failed', e.message, 'high'); }
}

// ── Lookalike Monitor ─────────────────────────────────────
async function loadLookalike() {
  try {
    const data = await api('/lookalike/monitor?limit=200');
    const alerts = data.alerts || [];
    const brands = data.brand_summary || [];

    document.getElementById('lookalikeCount').textContent = `${alerts.length} Active`;

    document.getElementById('brandGrid').innerHTML = brands.length
      ? brands.map(b => `<button class="brand-card" data-action="filter-lookalike-brand" data-brand="${esc(b.brand)}" type="button">
          <div class="brand-name">${esc(b.brand)}</div>
          <div class="brand-detections">${esc(b.detections)} detection${b.detections !== 1 ? 's' : ''}</div>
          <div class="brand-score">${esc(b.max_score)}</div>
        </button>`).join('')
      : '<p class="empty-muted">No active brand alerts</p>';

    renderLookalikeTable(alerts);
  } catch (e) {
    document.getElementById('lookalikeBody').innerHTML = `<tr><td colspan="6" class="table-error">${esc(e.message)}</td></tr>`;
  }
}

function renderLookalikeTable(alerts) {
  document.getElementById('lookalikeBody').innerHTML = alerts.length
    ? alerts.map(a => `<tr>
        <td><b class="severity-text-critical">${esc(a.detected_domain)}</b></td>
        <td>${a.impersonated_brand ? `<b>${esc(a.impersonated_brand)}</b>` : '—'}</td>
        <td>${threatTypeBadge(a.threat_type)}</td>
        <td>${scoreBar(a.confidence_score || 0)}</td>
        <td>${reasonTags(a.reasons)}</td>
        <td class="text-xs">${fmtDate(a.created_at)}</td>
      </tr>`).join('')
    : '<tr><td colspan="6" class="empty-state"><p>No lookalike alerts</p></td></tr>';
}

function filterLookalikeByBrand(brand) {
  api(`/lookalike/monitor?brand=${encodeURIComponent(brand)}&limit=200`)
    .then(d => renderLookalikeTable(d.alerts || []))
    .catch(() => {});
}

// ── Domain Analyser ───────────────────────────────────────
async function analyseDomain() {
  const input = document.getElementById('domainInput').value.trim();
  if (!input) return;
  const result = document.getElementById('analyserResult');
  result.classList.add('visible');
  result.innerHTML = '<p class="text-muted">Analysing…</p>';
  try {
    let domain = input;
    if (input.includes('@')) domain = input.split('@')[1];
    const data = await api(`/domain/${encodeURIComponent(domain)}`);
    const r = data.result;
    const sev = scoreToSeverity(r.confidence_score);
    result.innerHTML = `
      ${r.is_lookalike ? `<div class="impersonation-banner">
        <svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M10 2l8 14H2L10 2Z"/><path d="M10 8v4M10 14h.01"/></svg>
        <div>
          <div class="impersonation-banner-text">&#x26A0;&#xFE0F; Lookalike domain detected — possible impersonation of <b>${esc(r.impersonated_brand || r.impersonated_domain)}</b></div>
          <div class="impersonation-banner-detail">${esc(r.threat_type || '')}: &#x27;${esc(r.domain)}&#x27; closely resembles &#x27;${esc(r.impersonated_domain)}&#x27;</div>
        </div>
      </div>` : ''}
      <div class="three-stat-grid">
        <div><div class="stat-label">Threat Score</div><div class="threat-score-value severity-text-${esc(sev)}">${Number(r.confidence_score) || 0}/100</div></div>
        <div><div class="stat-label">Threat Level</div><div class="mt-4">${severityBadge(r.threat_level || sev)}</div></div>
        <div><div class="stat-label">Threat Type</div><div class="mt-4">${threatTypeBadge(r.threat_type)}</div></div>
      </div>
      ${r.levenshtein_distance != null ? `<p class="lookalike-detail">Edit distance from &#x27;${esc(r.impersonated_domain)}&#x27;: <b>${Number(r.levenshtein_distance)}</b> ${r.visual_score != null ? `| Visual similarity: <b>${(r.visual_score*100).toFixed(0)}%</b>` : ''}</p>` : ''}
      ${r.reasons && r.reasons.length ? `<div class="mb-10"><div class="stat-label mb-6">Detection Reasons</div>${reasonTags(r.reasons)}</div>` : ''}
      <div class="action-row">
        <button class="btn btn-danger btn-sm" data-action="quick-block" data-entry-type="domain" data-value="${esc(r.domain)}" type="button">Block Domain</button>
        <button class="btn btn-success btn-sm" data-action="quick-trust" data-entry-type="domain" data-value="${esc(r.domain)}" type="button">Trust Domain</button>
      </div>
    `;
  } catch (e) {
    result.innerHTML = `<p class="severity-text-critical">${esc(e.message)}</p>`;
  }
}

document.getElementById('domainInput').addEventListener('keydown', e => {
  if (e.key === 'Enter') analyseDomain();
});

document.getElementById('feedSearch').addEventListener('keydown', e => {
  if (e.key === 'Enter') { feedOffset = 0; loadFeed(); }
});

document.addEventListener('click', event => {
  const target = event.target.closest('[data-action]');
  if (!target) return;
  const action = target.dataset.action;
  if (action === 'load-feed') return loadFeed();
  if (action === 'load-scam-emails') return loadScamEmails();
  if (action === 'analyse-domain') return analyseDomain();
  if (action === 'show-blacklist-form') return showAddBlacklist();
  if (action === 'hide-blacklist-form') return hideAddBlacklist();
  if (action === 'add-blacklist') return addToBlacklist();
  if (action === 'show-whitelist-form') return showAddWhitelist();
  if (action === 'hide-whitelist-form') return hideAddWhitelist();
  if (action === 'add-whitelist') return addToWhitelist();
  if (action === 'dismiss-alert') return dismissAlert(target.dataset.id);
  if (action === 'feed-page') return feedPage(Number(target.dataset.dir || 0));
  if (action === 'restore-email') return restoreEmail(target.dataset.id);
  if (action === 'confirm-scam') return confirmScam(target.dataset.id);
  if (action === 'filter-lookalike-brand') return filterLookalikeByBrand(target.dataset.brand || '');
  if (action === 'quick-block') return quickBlock(target.dataset.entryType || 'domain', target.dataset.value || '');
  if (action === 'quick-trust') return quickTrust(target.dataset.entryType || 'domain', target.dataset.value || '');
  if (action === 'remove-blacklist') return removeBlacklist(target.dataset.id);
  if (action === 'remove-whitelist') return removeWhitelist(target.dataset.id);
});

async function quickBlock(type, value) {
  try {
    await api('/blacklist', { method: 'POST', body: JSON.stringify({ entry_type: type, value }) });
    showToast(`${value} blocked`, '', 'medium');
  } catch (e) { showToast('Failed', e.message, 'high'); }
}

async function quickTrust(type, value) {
  try {
    await api('/whitelist', { method: 'POST', body: JSON.stringify({ entry_type: type, value }) });
    showToast(`${value} trusted`, '', 'low');
  } catch (e) { showToast('Failed', e.message, 'high'); }
}

// ── Blacklist ─────────────────────────────────────────────
async function loadBlacklist() {
  try {
    const data = await api('/blacklist?limit=200');
    document.getElementById('blacklistBody').innerHTML = (data.items || []).length
      ? data.items.map(i => `<tr>
          <td>${i.entry_type === 'sender' ? '<span class="dot-blue">●</span> Sender' : '<span class="dot-blue">●</span> Domain'}</td>
          <td class="mono-red">${esc(i.value)}</td>
          <td class="text-muted-xs">${esc(i.reason || '—')}</td>
          <td>${scoreBar(i.score || 0)}</td>
          <td class="text-xs">${fmtDate(i.created_at)}</td>
          <td><button class="btn btn-ghost btn-sm" data-action="remove-blacklist" data-id="${esc(i.id)}" type="button">Remove</button></td>
        </tr>`).join('')
      : '<tr><td colspan="6" class="empty-state"><p>No blacklisted entries</p></td></tr>';
  } catch (e) { console.error(e); }
}

function showAddBlacklist() {
  document.getElementById('addBlacklistForm').classList.remove('hidden');
}

function hideAddBlacklist() {
  document.getElementById('addBlacklistForm').classList.add('hidden');
}

async function addToBlacklist() {
  const type = document.getElementById('blType').value;
  const value = document.getElementById('blValue').value.trim();
  const reason = document.getElementById('blReason').value.trim();
  if (!value) return;
  try {
    await api('/blacklist', { method: 'POST', body: JSON.stringify({ entry_type: type, value, reason }) });
    document.getElementById('blValue').value = '';
    document.getElementById('blReason').value = '';
    hideAddBlacklist();
    showToast(`${value} blocked`, '', 'medium');
    loadBlacklist();
  } catch (e) { showToast('Failed', e.message, 'high'); }
}

async function removeBlacklist(id) {
  if (!confirm('Remove this blacklist entry?')) return;
  try {
    await api(`/blacklist/${id}`, { method: 'DELETE' });
    showToast('Entry removed', '', 'low');
    loadBlacklist();
  } catch (e) { showToast('Failed', e.message, 'high'); }
}

// ── Whitelist ─────────────────────────────────────────────
async function loadWhitelist() {
  try {
    const data = await api('/whitelist?limit=200');
    document.getElementById('whitelistBody').innerHTML = (data.items || []).length
      ? data.items.map(i => `<tr>
          <td>${i.entry_type === 'sender' ? 'Sender' : 'Domain'}</td>
          <td class="mono-green">${esc(i.value)}</td>
          <td class="text-muted-xs">${esc(i.reason || '—')}</td>
          <td class="text-xs">${fmtDate(i.created_at)}</td>
          <td><button class="btn btn-ghost btn-sm" data-action="remove-whitelist" data-id="${esc(i.id)}" type="button">Remove</button></td>
        </tr>`).join('')
      : '<tr><td colspan="5" class="empty-state"><p>No trusted entries</p></td></tr>';
  } catch (e) { console.error(e); }
}

function showAddWhitelist() {
  document.getElementById('addWhitelistForm').classList.remove('hidden');
}

function hideAddWhitelist() {
  document.getElementById('addWhitelistForm').classList.add('hidden');
}

async function addToWhitelist() {
  const type = document.getElementById('wlType').value;
  const value = document.getElementById('wlValue').value.trim();
  const reason = document.getElementById('wlReason').value.trim();
  if (!value) return;
  try {
    await api('/whitelist', { method: 'POST', body: JSON.stringify({ entry_type: type, value, reason }) });
    document.getElementById('wlValue').value = '';
    document.getElementById('wlReason').value = '';
    hideAddWhitelist();
    showToast(`${value} trusted`, '', 'low');
    loadWhitelist();
  } catch (e) { showToast('Failed', e.message, 'high'); }
}

async function removeWhitelist(id) {
  if (!confirm('Remove this trusted entry?')) return;
  try {
    await api(`/whitelist/${id}`, { method: 'DELETE' });
    showToast('Entry removed', '', 'low');
    loadWhitelist();
  } catch (e) { showToast('Failed', e.message, 'high'); }
}

// ── Audit Log ─────────────────────────────────────────────
async function loadAudit() {
  try {
    const data = await api('/audit?limit=200');
    document.getElementById('auditBody').innerHTML = (data.items || []).length
      ? data.items.map(i => `<tr>
          <td class="text-primary font-bold">${esc(i.action)}</td>
          <td class="text-xs">${esc(i.target_type || '—')}</td>
          <td class="mono-xs">${esc(i.target_value || '—')}</td>
          <td class="text-muted-xs">${esc(i.detail || '—')}</td>
          <td class="text-xs">${esc(i.performed_by || 'system')}</td>
          <td class="text-xs">${fmtDate(i.created_at)}</td>
        </tr>`).join('')
      : '<tr><td colspan="6" class="empty-state"><p>No audit events recorded</p></td></tr>';
  } catch (e) { console.error(e); }
}

// ── Toast notifications ───────────────────────────────────
function showToast(message, sub, severity = 'medium', duration = 5000) {
  const stream = document.getElementById('alertStream');
  const toast = document.createElement('div');
  toast.className = `alert-toast ${severity}`;
  toast.innerHTML = `
    <div class="toast-type">${esc(severity).toUpperCase()}</div>
    <div class="toast-msg">${esc(message)}</div>
    ${sub ? `<div class="toast-sub">${esc(sub)}</div>` : ''}
  `;
  stream.appendChild(toast);
  toast.addEventListener('click', () => removeToast(toast));
  setTimeout(() => removeToast(toast), duration);
}

function removeToast(toast) {
  toast.classList.add('removing');
  setTimeout(() => toast.remove(), 200);
}

// ── WebSocket ─────────────────────────────────────────────
let ws = null;
let wsReconnectTimer = null;

function connectWS() {
  try {
    ws = new WebSocket(WS_URL);
    ws.onopen = () => {
      setLiveStatus('connected', 'Live');
      ws.send(JSON.stringify({ type: 'set_filter', filter: { min_severity: 'medium' } }));
    };
    ws.onmessage = e => handleWSMessage(JSON.parse(e.data));
    ws.onclose = () => {
      setLiveStatus('error', 'Disconnected');
      wsReconnectTimer = setTimeout(connectWS, 5000);
    };
    ws.onerror = () => setLiveStatus('error', 'Error');
  } catch (err) {
    setLiveStatus('error', 'Unavailable');
  }
}

function handleWSMessage(msg) {
  if (!msg || !msg.type) return;
  if (msg.type === 'heartbeat') return;

  if (msg.type === 'scam_detected') {
    const p = msg.payload;
    showToast(
      `Scam detected: ${p.subject || '(no subject)'}`,
      `From: ${p.sender_email} — Confidence: ${Math.round((p.confidence||0)*100)}%`,
      msg.severity || 'high',
      8000
    );
    // Refresh scam email count
    loadDashboard();
  }

  if (msg.type === 'lookalike_detected') {
    const p = msg.payload;
    showToast(
      `⚠️ Lookalike domain: ${p.detected_domain}`,
      p.warning || `Impersonating ${p.impersonated_brand}`,
      msg.severity || 'critical',
      10000
    );
  }

  if (msg.type === 'stats_update') {
    // silently refresh dashboard if on it
    const isDash = document.querySelector('[data-view="dashboard"].active');
    if (isDash) loadDashboard();
  }
}

function setLiveStatus(state, label) {
  const dot = document.getElementById('liveDot');
  const status = document.getElementById('liveStatus');
  dot.className = 'live-dot ' + state;
  status.textContent = label;
}

function setNavBadge(id, count) {
  const el = document.getElementById(id);
  if (!el) return;
  if (count > 0) {
    el.textContent = count > 99 ? '99+' : count;
    el.classList.add('visible');
  } else {
    el.classList.remove('visible');
  }
}

// ── Escape helper ─────────────────────────────────────────
function esc(s) {
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── Init ──────────────────────────────────────────────────
loadDashboard();
connectWS();
// Send heartbeat ping every 25 seconds
setInterval(() => { if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'ping' })); }, 25000);
// Auto-refresh dashboard every 60 seconds
setInterval(() => {
  const active = document.querySelector('.threat-nav-btn.active');
  if (active && active.dataset.view === 'dashboard') loadDashboard();
}, 60000);
