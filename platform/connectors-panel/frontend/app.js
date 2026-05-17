/* ── Connector & Plugin Panel – Frontend Application ─────────────────────── */
'use strict';

const API = '/api/connector-panel';
let _tenantId = 'default';
let _localToken = '';
let _sessionReady = null;

// ── Utilities ─────────────────────────────────────────────────────────────────

async function apiFetch(path, opts = {}) {
  await ensureSession();
  const url = `${API}${path}`;
  const headers = {
    'Content-Type': 'application/json',
    ...(_localToken ? { 'X-Local-Token': _localToken } : {}),
    ...(opts.headers || {}),
  };
  try {
    const res = await fetch(url, { ...opts, credentials: 'same-origin', headers });
    const text = await res.text();
    const data = text ? JSON.parse(text) : {};
    return res.ok ? { ok: true, data } : { ok: false, error: data.detail || data.message || 'Request failed', status: res.status };
  } catch (e) {
    return { ok: false, error: e.message || 'Network error', status: 0 };
  }
}

async function ensureSession() {
  if (!_sessionReady) {
    _sessionReady = fetch(`${API}/session`, {
      method: 'POST',
      credentials: 'same-origin',
    }).catch(() => null);
  }
  await _sessionReady;
}

function esc(v) {
  return String(v ?? '').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
}

function formatDate(ts) {
  if (!ts) return '—';
  const d = new Date(ts);
  if (isNaN(d)) return ts;
  return d.toLocaleString('en-GB', { day:'2-digit', month:'short', year:'numeric', hour:'2-digit', minute:'2-digit' });
}

function timeAgo(ts) {
  if (!ts) return '—';
  const diff = (Date.now() - new Date(ts)) / 1000;
  if (diff < 60)    return `${Math.round(diff)}s ago`;
  if (diff < 3600)  return `${Math.round(diff/60)}m ago`;
  if (diff < 86400) return `${Math.round(diff/3600)}h ago`;
  return `${Math.round(diff/86400)}d ago`;
}

function statusBadge(status) {
  const map = {
    active:'badge-active',inactive:'badge-inactive',installing:'badge-installing',
    failed:'badge-failed',degraded:'badge-degraded',enabled:'badge-active',disabled:'badge-inactive',
    beta:'badge-beta', free:'badge-free', pro:'badge-pro', enterprise:'badge-enterprise',
  };
  return `<span class="badge ${map[status]||'badge-inactive'}">${esc(status)}</span>`;
}

function dot(status) {
  return `<span class="status-dot ${status}"></span>`;
}

function toast(msg, type = 'info', duration = 3500) {
  const wrap = document.getElementById('toastContainer');
  if (!wrap) return;
  const el = document.createElement('div');
  el.className = `toast toast-${type}`;
  el.innerHTML = `<span>${esc(msg)}</span><button class="toast-close" onclick="this.parentElement.remove()">×</button>`;
  wrap.appendChild(el);
  setTimeout(() => el.remove(), duration);
}

function showModal(html) {
  let overlay = document.getElementById('modalOverlay');
  if (overlay) overlay.remove();
  overlay = document.createElement('div');
  overlay.id = 'modalOverlay';
  overlay.className = 'modal-overlay';
  overlay.innerHTML = `<div class="modal">${html}</div>`;
  overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });
  document.body.appendChild(overlay);
}

function closeModal() {
  const el = document.getElementById('modalOverlay');
  if (el) el.remove();
}

function confirm(msg, onYes) {
  showModal(`
    <div class="modal-header"><h3 class="modal-title">Confirm</h3><button class="modal-close" onclick="closeModal()">×</button></div>
    <p style="color:var(--text-muted);margin-bottom:8px;">${esc(msg)}</p>
    <div class="modal-footer">
      <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
      <button class="btn btn-danger" id="confirmYes">Confirm</button>
    </div>
  `);
  document.getElementById('confirmYes').onclick = () => { closeModal(); onYes(); };
}

function setBtnLoading(btn, loading) {
  if (!btn) return;
  btn.disabled = loading;
  btn.classList.toggle('btn-loading', loading);
}

// ── Navigation ─────────────────────────────────────────────────────────────────

function showSection(id) {
  _currentSection = id;
  document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  const sec = document.getElementById(`sec-${id}`);
  const nav = document.querySelector(`.nav-item[data-section="${id}"]`);
  if (sec) sec.classList.add('active');
  if (nav) nav.classList.add('active');
  const titleEl = document.querySelector('.topbar-title');
  const subEl = document.querySelector('.topbar-sub');
  if (titleEl) titleEl.textContent = navTitles[id] || 'Connector Panel';
  if (subEl) subEl.textContent = navSubs[id] || '';
  sectionLoaders[id]?.();
}

const navTitles = {
  dashboard:'Dashboard', marketplace:'Marketplace', installed:'Installed Connectors',
  oauth:'OAuth Manager', webhooks:'Webhook Manager', queues:'Queue Monitor',
  logs:'Logs & Monitoring', health:'Health Dashboard', permissions:'Permissions',
  plugins:'Plugin Registry', events:'Event Bus', settings:'Panel Settings',
  // ERP
  erp:'ERP Overview', vendors:'Vendors', 'purchase-orders':'Purchase Orders',
  invoices:'Invoices', inventory:'Inventory', warehouses:'Warehouses',
  // CRM
  crm:'CRM Overview', pipeline:'Sales Pipeline', leads:'Leads',
  contacts:'Contacts', opportunities:'Opportunities',
  // Ops
  tracking:'Shipment Tracking', workflows:'Workflow Builder', support:'Support Tickets',
};
const navSubs = {
  dashboard:'Enterprise operations overview',
  marketplace:'Browse and install connector integrations',
  installed:'Manage your active connectors',
  oauth:'Manage OAuth tokens and provider connections',
  webhooks:'Configure webhook endpoints and delivery',
  queues:'Monitor job queues and dead-letter queues',
  logs:'Real-time connector logs and history',
  health:'Connector and system health monitoring',
  permissions:'Plugin access control and permissions',
  plugins:'Registered plugin registry and status',
  events:'Event bus subscriptions and activity',
  settings:'Panel configuration and preferences',
  // ERP
  erp:'ERP module summary and quick actions',
  vendors:'Supplier and vendor master data',
  'purchase-orders':'Purchase order management',
  invoices:'Invoice tracking and payments',
  inventory:'Stock levels and reorder management',
  warehouses:'Warehouse locations and capacity',
  // CRM
  crm:'CRM summary and pipeline overview',
  pipeline:'Visual pipeline board by stage',
  leads:'Lead capture and qualification',
  contacts:'Customer and prospect directory',
  opportunities:'Deal tracking and revenue forecasting',
  // Ops
  tracking:'Multi-carrier shipment tracking',
  workflows:'Automated workflow definitions and runs',
  support:'Customer support tickets and SLA tracking',
};

let _currentSection = 'dashboard';

function reloadCurrentSection() {
  sectionLoaders[_currentSection]?.();
  if (_currentSection !== 'installed') loadInstalled();
}

// ── DASHBOARD ─────────────────────────────────────────────────────────────────

async function loadDashboard() {
  const [healthRes, logsRes, erpRes, crmRes, trkRes, sptRes] = await Promise.all([
    apiFetch('/health'),
    apiFetch(`/logs?tenant_id=${_tenantId}&limit=8`),
    apiFetch(`/erp/summary?tenant_id=${_tenantId}`),
    apiFetch(`/crm/summary?tenant_id=${_tenantId}`),
    apiFetch(`/tracking/stats?tenant_id=${_tenantId}`),
    apiFetch(`/support/summary?tenant_id=${_tenantId}`),
  ]);

  const h = healthRes.ok ? healthRes.data : {};
  const hs = h.stats || {};

  _setEl('statConnectors', hs.total_connectors ?? '—');

  if (erpRes.ok) {
    const e = erpRes.data;
    _setEl('statVendors', e.total_vendors ?? e.vendors ?? '—');
    _setEl('statPOs', e.total_pos ?? e.purchase_orders ?? '—');
  }
  if (crmRes.ok) {
    _setEl('statContacts', crmRes.data.total_contacts ?? crmRes.data.contacts ?? '—');
  }
  if (trkRes.ok) {
    const t = trkRes.data;
    _setEl('statShipments', t.in_transit ?? '—');
  }
  if (sptRes.ok) {
    const s = sptRes.data;
    _setEl('statTickets', s.open ?? '—');
  }

  // Recent logs
  const logs = logsRes.ok ? (logsRes.data.logs || logsRes.data || []) : [];
  const logEl = document.getElementById('recentLogs');
  if (logEl) {
    logEl.innerHTML = logs.length
      ? logs.map(l => renderLogLine(l)).join('')
      : '<div style="padding:16px;color:var(--text-muted);text-align:center;">No recent logs</div>';
  }

  // Shipments at risk
  if (trkRes.ok) {
    const ships = trkRes.data.high_risk_shipments || [];
    const el = document.getElementById('dashRiskShipments');
    if (el) {
      el.innerHTML = ships.length
        ? ships.slice(0,5).map(s => `
          <div style="display:flex;align-items:center;gap:8px;padding:8px 0;border-bottom:1px solid var(--border);">
            <span class="badge badge-failed">High Risk</span>
            <span style="font-size:12px;">${esc(s.tracking_number)} · ${esc(s.carrier)}</span>
            <span style="font-size:11px;color:var(--text-muted);margin-left:auto;">${esc(s.status)}</span>
          </div>`).join('')
        : '<div style="padding:12px;color:var(--text-muted);text-align:center;font-size:13px;">No high-risk shipments</div>';
    }
  }

  // Urgent tickets
  if (sptRes.ok) {
    const tickets = sptRes.data.urgent_tickets || [];
    const el = document.getElementById('dashUrgentTickets');
    if (el) {
      el.innerHTML = tickets.length
        ? tickets.slice(0,5).map(t => `
          <div style="display:flex;align-items:center;gap:8px;padding:8px 0;border-bottom:1px solid var(--border);">
            <span class="badge badge-failed">Urgent</span>
            <span style="font-size:12px;flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(t.subject)}</span>
            <span style="font-size:11px;color:var(--text-muted);">${timeAgo(t.created_at)}</span>
          </div>`).join('')
        : '<div style="padding:12px;color:var(--text-muted);text-align:center;font-size:13px;">No urgent tickets</div>';
    }
  }
}

function _setEl(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

// ── MARKETPLACE ───────────────────────────────────────────────────────────────

let _marketplace = [];

async function loadMarketplace() {
  const res = await apiFetch('/marketplace/connectors');
  if (!res.ok) { toast('Failed to load marketplace: ' + res.error, 'error'); return; }
  _marketplace = res.data.connectors || res.data || [];
  renderMarketplace(_marketplace);
}

function renderMarketplace(items) {
  const grid = document.getElementById('marketplaceGrid');
  if (!grid) return;
  const q = document.getElementById('mktSearch')?.value?.toLowerCase() || '';
  const cat = document.getElementById('mktCategory')?.value || '';
  let rows = items;
  if (q)   rows = rows.filter(c => (c.name+c.description+c.category).toLowerCase().includes(q));
  if (cat) rows = rows.filter(c => c.category === cat);
  if (!rows.length) {
    grid.innerHTML = `<div class="empty-state" style="grid-column:1/-1"><svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2"><circle cx="12" cy="12" r="10"/><path d="M8 12h8M12 8v8"/></svg><h3>No connectors found</h3><p>Try adjusting your search or filter</p></div>`;
    return;
  }
  grid.innerHTML = rows.map(c => renderConnectorCard(c)).join('');
}

const CONNECTOR_ICONS = {
  // ── Communication ───────────────────────────────────────────────────────────
  whatsapp: `<svg viewBox="0 0 40 40" fill="none"><rect width="40" height="40" rx="10" fill="#25D366"/><path fill="#fff" d="M20 8C13.4 8 8 13.4 8 20c0 2.2.6 4.3 1.7 6.1L8 32l6.1-1.7C15.7 31.4 17.8 32 20 32c6.6 0 12-5.4 12-12S26.6 8 20 8zm5.8 16.6c-.3.8-1.6 1.5-2.2 1.6-.6.1-1.3.1-2-.1-.7-.2-1.8-.7-3.5-1.8-2.5-1.6-4-4-4.2-4.2-.2-.3-1-1.4-1-2.6 0-1.2.6-1.8.9-2 .3-.3.6-.3.8-.3h.6c.2 0 .4 0 .6.5.3.7.9 2.1 1 2.3.1.2.1.4 0 .6-.1.2-.2.4-.3.5-.2.2-.3.4-.1.7.2.3.8 1.1 1.6 1.9 1.1 1 2 1.3 2.2 1.4.2.1.4 0 .6-.1.2-.2.6-.7.9-1 .2-.3.4-.2.7-.1l2.1 1c.2.1.4.2.5.4.1.3 0 1.1-.3 1.5z"/></svg>`,

  gmail: `<svg viewBox="0 0 40 40" fill="none"><rect width="40" height="40" rx="10" fill="#fff" stroke="#E2E8F0"/><path d="M8 28V14l12 9 12-9v14a1 1 0 01-1 1H9a1 1 0 01-1-1z" fill="#4285F4"/><path d="M8 14l12 9 12-9" stroke="#EA4335" stroke-width="0"/><path d="M9 13h22a1 1 0 011 1v.5L20 22.5 8 14.5V14a1 1 0 011-1z" fill="#EA4335"/><path d="M8 14.5L20 23l12-8.5" fill="none"/><path d="M8 14v14h5V19l7 5.5L27 19v9h5V14L20 23 8 14z" fill="#fff"/><path d="M8 14v14h5V19l7 5.5L27 19v9h5V14L20 23 8 14z" fill="none"/><rect x="8" y="13" width="24" height="15" rx="1" fill="none" stroke="#E2E8F0" stroke-width=".5"/><path d="M8 14l12 8.8L32 14" stroke="#EA4335" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`,

  slack: `<svg viewBox="0 0 40 40" fill="none"><rect width="40" height="40" rx="10" fill="#fff"/><path d="M15 10a3 3 0 00-3 3 3 3 0 003 3h3v-3a3 3 0 00-3-3z" fill="#E01E5A"/><path d="M15 16h-3a3 3 0 000 6h3v-6z" fill="#E01E5A"/><path d="M22 10a3 3 0 00-3 3v3h3a3 3 0 000-6z" fill="#36C5F0"/><path d="M28 13a3 3 0 00-6 0v3h3a3 3 0 003-3z" fill="#36C5F0"/><path d="M25 22h-3v3a3 3 0 003 3 3 3 0 003-3 3 3 0 00-3-3z" fill="#2EB67D"/><path d="M25 16h3a3 3 0 000-6 3 3 0 00-3 3v3z" fill="#2EB67D"/><path d="M18 25a3 3 0 003 3 3 3 0 003-3h-3v-3h-3v3z" fill="#ECB22E"/><path d="M15 22a3 3 0 003 3v-3h3v-3h-3a3 3 0 00-3 3z" fill="#ECB22E"/></svg>`,

  slack_enterprise: `<svg viewBox="0 0 40 40" fill="none"><rect width="40" height="40" rx="10" fill="#fff"/><path d="M15 10a3 3 0 00-3 3 3 3 0 003 3h3v-3a3 3 0 00-3-3z" fill="#E01E5A"/><path d="M15 16h-3a3 3 0 000 6h3v-6z" fill="#E01E5A"/><path d="M22 10a3 3 0 00-3 3v3h3a3 3 0 000-6z" fill="#36C5F0"/><path d="M28 13a3 3 0 00-6 0v3h3a3 3 0 003-3z" fill="#36C5F0"/><path d="M25 22h-3v3a3 3 0 003 3 3 3 0 003-3 3 3 0 00-3-3z" fill="#2EB67D"/><path d="M25 16h3a3 3 0 000-6 3 3 0 00-3 3v3z" fill="#2EB67D"/><path d="M18 25a3 3 0 003 3 3 3 0 003-3h-3v-3h-3v3z" fill="#ECB22E"/><path d="M15 22a3 3 0 003 3v-3h3v-3h-3a3 3 0 00-3 3z" fill="#ECB22E"/></svg>`,

  teams: `<svg viewBox="0 0 40 40" fill="none"><rect width="40" height="40" rx="10" fill="#5558AF"/><path d="M23 14h5a2 2 0 012 2v8a2 2 0 01-2 2h-5v2l-5-2H13a2 2 0 01-2-2v-8a2 2 0 012-2h10z" fill="#fff" opacity=".15"/><rect x="11" y="15" width="14" height="12" rx="2" fill="#fff"/><text x="18" y="24" font-family="Arial" font-size="8" font-weight="700" fill="#5558AF" text-anchor="middle">T</text><circle cx="25" cy="14" r="4" fill="#7B83EB"/><text x="25" y="17" font-family="Arial" font-size="5" font-weight="700" fill="#fff" text-anchor="middle">T</text></svg>`,

  outlook: `<svg viewBox="0 0 40 40" fill="none"><rect width="40" height="40" rx="10" fill="#0078D4"/><rect x="8" y="13" width="16" height="14" rx="2" fill="#fff"/><rect x="8" y="13" width="16" height="5" rx="0" fill="#0078D4" opacity=".3"/><path d="M8 18l8 5 8-5" stroke="#fff" stroke-width="1.5" stroke-linecap="round"/><path d="M21 16h11v11H21" stroke="#fff" stroke-width="1.5" stroke-linejoin="round"/><path d="M21 16l6 5-5 5" stroke="#fff" stroke-width="0" fill="none"/></svg>`,

  telegram: `<svg viewBox="0 0 40 40" fill="none"><rect width="40" height="40" rx="10" fill="#2AABEE"/><path d="M9 19.5l4 1.5 2 5 3-3.5 5 4 4-14-18 7z" fill="#fff"/><path d="M13 21l2 5 3-3.5" fill="none" stroke="#C8DAEA" stroke-width="1.5" stroke-linejoin="round"/><path d="M13 21l14-9-12 10z" fill="#A9C9DD"/></svg>`,

  discord: `<svg viewBox="0 0 40 40" fill="none"><rect width="40" height="40" rx="10" fill="#5865F2"/><path d="M27 13s-3-1-6-1-6 1-6 1l-3 14s3 2 9 2 9-2 9-2l-3-14z" fill="#fff" opacity=".15"/><path d="M25.3 13.5c-1.5-.7-3.4-1.1-5.3-1.1s-3.8.4-5.3 1.1c-2.2 1-3.7 3-3.7 5.3 0 2.5 1.2 4.7 3.2 6 .5.3 1.4.7 1.4.7s.4-1.2.6-2.2c1 .4 2.4.7 3.8.7s2.8-.3 3.8-.7c.2 1 .6 2.2.6 2.2s.9-.4 1.4-.7c2-1.3 3.2-3.5 3.2-6 0-2.3-1.5-4.3-3.7-5.3zm-8.3 7c-.8 0-1.5-.7-1.5-1.5S16.2 17.5 17 17.5s1.5.7 1.5 1.5-.7 1.5-1.5 1.5zm6 0c-.8 0-1.5-.7-1.5-1.5s.7-1.5 1.5-1.5 1.5.7 1.5 1.5-.7 1.5-1.5 1.5z" fill="#fff"/></svg>`,

  // ── CRM ─────────────────────────────────────────────────────────────────────
  salesforce: `<svg viewBox="0 0 40 40" fill="none"><rect width="40" height="40" rx="10" fill="#00A1E0"/><path d="M16 15c0-2.2 1.8-4 4-4 1.4 0 2.6.7 3.3 1.8.5-.3 1-.4 1.7-.4 1.9 0 3.5 1.6 3.5 3.5 0 .3 0 .6-.1.8C29.4 17.3 30 18.4 30 19.6c0 2-1.6 3.6-3.5 3.6H14c-1.7 0-3-1.3-3-3s1-2.8 2.4-3c-.3-.5-.4-1-.4-1.6 0-1.9 1.5-3.4 3-3.6z" fill="#fff"/></svg>`,

  hubspot: `<svg viewBox="0 0 40 40" fill="none"><rect width="40" height="40" rx="10" fill="#FF7A59"/><circle cx="24" cy="14" r="4" fill="#fff"/><circle cx="24" cy="14" r="2" fill="#FF7A59"/><path d="M20 14h-4v5H9v3h7v5h4v-5h11v-3H20v-5z" fill="#fff" opacity=".2"/><path d="M22 17v-3h-4v5H10v3h8v5h4v-5h8v-3h-8z" fill="#fff"/></svg>`,

  zoho_crm: `<svg viewBox="0 0 40 40" fill="none"><rect width="40" height="40" rx="10" fill="#C9222B"/><text x="20" y="27" font-family="Arial" font-size="22" font-weight="900" fill="#fff" text-anchor="middle">Z</text></svg>`,

  freshsales: `<svg viewBox="0 0 40 40" fill="none"><rect width="40" height="40" rx="10" fill="#4CA542"/><text x="20" y="27" font-family="Arial" font-size="22" font-weight="900" fill="#fff" text-anchor="middle">F</text></svg>`,

  pipedrive: `<svg viewBox="0 0 40 40" fill="none"><rect width="40" height="40" rx="10" fill="#1A1A2E"/><circle cx="20" cy="17" r="5" fill="#26C6DA" opacity=".9"/><rect x="17" y="22" width="6" height="10" rx="3" fill="#26C6DA" opacity=".9"/></svg>`,

  // ── ERP ─────────────────────────────────────────────────────────────────────
  sap: `<svg viewBox="0 0 40 40" fill="none"><rect width="40" height="40" rx="10" fill="#0070B1"/><text x="20" y="26" font-family="Arial" font-size="13" font-weight="900" fill="#fff" text-anchor="middle">SAP</text></svg>`,

  oracle_erp: `<svg viewBox="0 0 40 40" fill="none"><rect width="40" height="40" rx="10" fill="#C74634"/><text x="20" y="26" font-family="Arial" font-size="9" font-weight="700" fill="#fff" text-anchor="middle">ORACLE</text></svg>`,

  odoo: `<svg viewBox="0 0 40 40" fill="none"><rect width="40" height="40" rx="10" fill="#714B67"/><circle cx="14" cy="20" r="4" fill="#fff"/><circle cx="20" cy="20" r="4" fill="#fff"/><circle cx="26" cy="20" r="4" fill="#fff"/></svg>`,

  erpnext: `<svg viewBox="0 0 40 40" fill="none"><rect width="40" height="40" rx="10" fill="#0089C6"/><text x="20" y="26" font-family="Arial" font-size="11" font-weight="900" fill="#fff" text-anchor="middle">ERPNext</text></svg>`,

  netsuite: `<svg viewBox="0 0 40 40" fill="none"><rect width="40" height="40" rx="10" fill="#2F8BCC"/><text x="20" y="26" font-family="Arial" font-size="9" font-weight="700" fill="#fff" text-anchor="middle">NetSuite</text></svg>`,

  ms_dynamics_365: `<svg viewBox="0 0 40 40" fill="none"><rect width="40" height="40" rx="10" fill="#002050"/><path d="M12 12h10l6 8-6 8H12l6-8-6-8z" fill="#00BCF2"/></svg>`,

  dynamics_365: `<svg viewBox="0 0 40 40" fill="none"><rect width="40" height="40" rx="10" fill="#002050"/><path d="M12 12h10l6 8-6 8H12l6-8-6-8z" fill="#00BCF2"/></svg>`,

  erp_sync: `<svg viewBox="0 0 40 40" fill="none"><rect width="40" height="40" rx="10" fill="#1D4ED8"/><path d="M13 16h9M22 16l-3-3M22 16l-3 3M27 24h-9M18 24l3-3M18 24l3 3" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><circle cx="11" cy="16" r="2" fill="#93C5FD"/><circle cx="29" cy="24" r="2" fill="#93C5FD"/></svg>`,

  // ── Accounting ──────────────────────────────────────────────────────────────
  quickbooks: `<svg viewBox="0 0 40 40" fill="none"><rect width="40" height="40" rx="10" fill="#2CA01C"/><circle cx="20" cy="20" r="9" fill="#fff"/><path d="M16 16h5a3 3 0 010 6h-3v2h-2v-8zm2 2v2h3a1 1 0 000-2h-3z" fill="#2CA01C"/><circle cx="23" cy="25" r="2" fill="#2CA01C"/></svg>`,

  xero: `<svg viewBox="0 0 40 40" fill="none"><rect width="40" height="40" rx="10" fill="#13B5EA"/><path d="M13 15l5 5-5 5M27 15l-5 5 5 5" stroke="#fff" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`,

  zoho_books: `<svg viewBox="0 0 40 40" fill="none"><rect width="40" height="40" rx="10" fill="#C9222B"/><text x="20" y="27" font-family="Arial" font-size="22" font-weight="900" fill="#fff" text-anchor="middle">Z</text></svg>`,

  // ── Ecommerce ───────────────────────────────────────────────────────────────
  shopify: `<svg viewBox="0 0 40 40" fill="none"><rect width="40" height="40" rx="10" fill="#5E8E3E"/><path d="M26 13s-.2-1.3-1.3-1.4c-1-.1-1.8.6-2 .8 0 0-.4-.1-.8-.1-1 0-1.5.7-1.7 1.2-.3-.1-.7-.1-1-.1L18 25l8 1.5L29 14l-3-1zm-3.8 1c.1-.4.4-1 .9-1.3v.5l.6.2-.6 3.8c-.5-.2-.9-.5-.9-1V14zm2.5 3.5l.6-4 .7.3L25 25l-1-8.5h1zm1.8-3.8l.8.3.2 1.4-.3-.1-.7-1.6z" fill="#fff"/><path d="M18 25l1.5-11 1 .3L19 25h-1z" fill="#fff" opacity=".5"/></svg>`,

  woocommerce: `<svg viewBox="0 0 40 40" fill="none"><rect width="40" height="40" rx="10" fill="#96588A"/><text x="20" y="27" font-family="Arial" font-size="13" font-weight="900" fill="#fff" text-anchor="middle">Woo</text></svg>`,

  magento: `<svg viewBox="0 0 40 40" fill="none"><rect width="40" height="40" rx="10" fill="#EE672F"/><path d="M20 11l8 5v10l-4 2.5V17l-4-2.5L16 17v11.5L12 26V16l8-5z" fill="#fff"/></svg>`,

  amazon_seller: `<svg viewBox="0 0 40 40" fill="none"><rect width="40" height="40" rx="10" fill="#FF9900"/><text x="20" y="25" font-family="Arial" font-size="20" font-weight="900" fill="#fff" text-anchor="middle">a</text><path d="M12 28c5-2.5 12-2.5 17 0" stroke="#fff" stroke-width="2" stroke-linecap="round"/></svg>`,

  // ── Shipping ────────────────────────────────────────────────────────────────
  fedex: `<svg viewBox="0 0 40 40" fill="none"><rect width="40" height="40" rx="10" fill="#4D148C"/><text x="12" y="25" font-family="Arial" font-size="12" font-weight="900" fill="#fff">Fe</text><text x="23" y="25" font-family="Arial" font-size="12" font-weight="900" fill="#FF6600">dEx</text></svg>`,

  ups: `<svg viewBox="0 0 40 40" fill="none"><rect width="40" height="40" rx="10" fill="#351C15"/><path d="M20 10l8 4v9c0 4-8 7-8 7s-8-3-8-7v-9l8-4z" fill="#FFB500"/><text x="20" y="25" font-family="Arial" font-size="8" font-weight="900" fill="#351C15" text-anchor="middle">UPS</text></svg>`,

  dhl: `<svg viewBox="0 0 40 40" fill="none"><rect width="40" height="40" rx="10" fill="#FFCC00"/><text x="20" y="26" font-family="Arial" font-size="14" font-weight="900" fill="#CC0000" text-anchor="middle">DHL</text></svg>`,

  delhivery: `<svg viewBox="0 0 40 40" fill="none"><rect width="40" height="40" rx="10" fill="#D52B1E"/><text x="20" y="27" font-family="Arial" font-size="22" font-weight="900" fill="#fff" text-anchor="middle">D</text></svg>`,

  shiprocket: `<svg viewBox="0 0 40 40" fill="none"><rect width="40" height="40" rx="10" fill="#E03D24"/><path d="M20 9l3 6h5l-4 4 1.5 6L20 22l-5.5 3 1.5-6-4-4h5L20 9z" fill="#fff"/></svg>`,

  aftership: `<svg viewBox="0 0 40 40" fill="none"><rect width="40" height="40" rx="10" fill="#5C6BC0"/><text x="20" y="27" font-family="Arial" font-size="22" font-weight="900" fill="#fff" text-anchor="middle">A</text></svg>`,

  maersk: `<svg viewBox="0 0 40 40" fill="none"><rect width="40" height="40" rx="10" fill="#00243D"/><path d="M10 20h20M15 14l5 6 5-6M15 26l5-6 5 6" stroke="#42B0D5" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>`,

  msc: `<svg viewBox="0 0 40 40" fill="none"><rect width="40" height="40" rx="10" fill="#003087"/><text x="20" y="26" font-family="Arial" font-size="13" font-weight="900" fill="#fff" text-anchor="middle">MSC</text></svg>`,

  shipping_tracker: `<svg viewBox="0 0 40 40" fill="none"><rect width="40" height="40" rx="10" fill="#0EA5E9"/><path d="M8 22h18l-2-8h4l3 8" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><circle cx="13" cy="27" r="2.5" fill="#fff"/><circle cx="23" cy="27" r="2.5" fill="#fff"/><path d="M8 18h14" stroke="#fff" stroke-width="2" stroke-linecap="round"/></svg>`,

  // ── Support ─────────────────────────────────────────────────────────────────
  zendesk: `<svg viewBox="0 0 40 40" fill="none"><rect width="40" height="40" rx="10" fill="#1F73B7"/><path d="M20 12a8 8 0 100 16 8 8 0 000-16zm0 3c1.7 0 3 1.3 3 3s-1.3 3-3 3-3-1.3-3-3 1.3-3 3-3z" fill="#fff"/></svg>`,

  freshdesk: `<svg viewBox="0 0 40 40" fill="none"><rect width="40" height="40" rx="10" fill="#4CA542"/><path d="M13 14h14v12a6 6 0 01-6 6h-2a6 6 0 01-6-6V14z" fill="#fff" opacity=".9"/><circle cx="16" cy="20" r="2" fill="#4CA542"/><circle cx="24" cy="20" r="2" fill="#4CA542"/><path d="M17 24h6" stroke="#4CA542" stroke-width="1.5" stroke-linecap="round"/></svg>`,

  intercom: `<svg viewBox="0 0 40 40" fill="none"><rect width="40" height="40" rx="10" fill="#1F8DED"/><rect x="10" y="11" width="20" height="16" rx="4" fill="#fff"/><circle cx="15" cy="19" r="2" fill="#1F8DED"/><circle cx="20" cy="19" r="2" fill="#1F8DED"/><circle cx="25" cy="19" r="2" fill="#1F8DED"/><path d="M14 27l3-4h6l3 4" fill="#fff"/></svg>`,

  // ── AI ──────────────────────────────────────────────────────────────────────
  openai: `<svg viewBox="0 0 40 40" fill="none"><rect width="40" height="40" rx="10" fill="#000"/><path d="M20 10c-5.5 0-10 4.5-10 10s4.5 10 10 10 10-4.5 10-10S25.5 10 20 10zm0 4l1.5 4.5H26l-3.7 2.7 1.4 4.3L20 23l-3.7 2.5 1.4-4.3L14 18.5h4.5L20 14z" fill="#fff"/></svg>`,

  anthropic: `<svg viewBox="0 0 40 40" fill="none"><rect width="40" height="40" rx="10" fill="#CC785C"/><path d="M17 26l3-12 3 12h-2l-.7-3h-2.6L17 26h-1.5zm2-5h2l-1-4-1 4z" fill="#fff" font-family="serif"/><text x="20" y="26" font-family="Georgia,serif" font-size="14" font-weight="700" fill="#fff" text-anchor="middle">A</text></svg>`,

  google_gemini: `<svg viewBox="0 0 40 40" fill="none"><rect width="40" height="40" rx="10" fill="#fff" stroke="#E2E8F0"/><path d="M20 10c0 5.5-4.5 10-10 10 5.5 0 10 4.5 10 10 0-5.5 4.5-10 10-10-5.5 0-10-4.5-10-10z" fill="url(#gem)"/><defs><linearGradient id="gem" x1="10" y1="10" x2="30" y2="30"><stop offset="0%" stop-color="#4285F4"/><stop offset="50%" stop-color="#9B72CB"/><stop offset="100%" stop-color="#EA4335"/></linearGradient></defs></svg>`,

  // ── Platform / Generic ───────────────────────────────────────────────────────
  ocr_engine: `<svg viewBox="0 0 40 40" fill="none"><rect width="40" height="40" rx="10" fill="#3B82F6"/><rect x="11" y="10" width="14" height="18" rx="2" fill="#fff"/><path d="M13 15h10M13 18h10M13 21h7" stroke="#3B82F6" stroke-width="1.5" stroke-linecap="round"/><path d="M27 22l1-2 1 2 2 1-2 1-1 2-1-2-2-1 2-1z" fill="#FCD34D"/></svg>`,

  webhook_listener: `<svg viewBox="0 0 40 40" fill="none"><rect width="40" height="40" rx="10" fill="#7C3AED"/><path d="M14 20c0-3.3 2.7-6 6-6" stroke="#fff" stroke-width="2" stroke-linecap="round"/><path d="M11 20c0-5 4-9 9-9" stroke="#fff" stroke-width="2" stroke-linecap="round" opacity=".5"/><circle cx="20" cy="20" r="3" fill="#fff"/><path d="M20 23v5M17 31h6" stroke="#fff" stroke-width="2" stroke-linecap="round"/></svg>`,
};

function renderConnectorCard(c) {
  const icon = CONNECTOR_ICONS[c.id] || CONNECTOR_ICONS[c.connector_id] || '🔌';
  const installed = c.is_installed;
  const isBeta = c.is_beta;
  const tier = c.price_tier || 'free';
  return `
  <div class="connector-card">
    <div class="connector-card-header">
      <div class="connector-icon">${icon}</div>
      <div class="connector-info">
        <div class="connector-name">${esc(c.name)}</div>
        <div class="connector-cat">${esc(c.category)}</div>
      </div>
      ${isBeta ? '<span class="badge badge-beta">beta</span>' : ''}
    </div>
    <div class="connector-desc">${esc(c.description || '')}</div>
    <div class="connector-meta">
      <span class="badge badge-free">free</span>
      <span class="badge badge-info">${esc(c.category)}</span>
      ${c.supports_oauth ? '<span class="badge badge-info">OAuth</span>' : ''}
      ${c.supports_webhook ? '<span class="badge badge-info">Webhook</span>' : ''}
    </div>
    <div class="connector-actions">
      ${installed
        ? `<button class="btn btn-secondary btn-sm" onclick="configureConnector('${esc(c.id||c.connector_id)}')">Configure</button>
           <button class="btn btn-sm" style="color:var(--success);border:1px solid rgba(72,187,120,.3)">✓ Installed</button>`
        : `<button class="btn btn-primary btn-sm" onclick="installConnector('${esc(c.id||c.connector_id)}','${esc(c.name)}')">Install</button>
           <button class="btn btn-secondary btn-sm" onclick="viewConnectorDetails('${esc(c.id||c.connector_id)}')">Details</button>`
      }
    </div>
  </div>`;
}

async function installConnector(connectorId, name) {
  showModal(`
    <div class="modal-header">
      <h3 class="modal-title">Install ${esc(name)}</h3>
      <button class="modal-close" onclick="closeModal()">×</button>
    </div>
    <p style="color:var(--text-muted);margin-bottom:16px;">Configure this connector before installation.</p>
    <div class="form-group">
      <label>Tenant ID</label>
      <input id="installTenant" value="${esc(_tenantId)}" />
    </div>
    <div class="form-group">
      <label>API Key (if required)</label>
      <input id="installApiKey" type="password" placeholder="Enter API key or leave blank" />
    </div>
    <div class="form-group">
      <label>Additional Config (JSON)</label>
      <textarea id="installConfig" placeholder='{"key": "value"}'></textarea>
    </div>
    <div class="modal-footer">
      <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
      <button class="btn btn-primary" id="installSubmit" onclick="submitInstall('${esc(connectorId)}')">Install Connector</button>
    </div>
  `);
}

async function submitInstall(connectorId) {
  const btn = document.getElementById('installSubmit');
  setBtnLoading(btn, true);
  let config = {};
  try { config = JSON.parse(document.getElementById('installConfig').value || '{}'); } catch {}
  const apiKey = document.getElementById('installApiKey').value;
  if (apiKey) config.api_key = apiKey;
  const res = await apiFetch(`/marketplace/connectors/${connectorId}/install`, {
    method: 'POST',
    body: JSON.stringify({ connector_id: connectorId, tenant_id: _tenantId, config }),
  });
  setBtnLoading(btn, false);
  if (res.ok) {
    closeModal();
    toast(`${connectorId} installed successfully`, 'success');
    loadMarketplace(); loadInstalled();
  } else {
    toast('Install failed: ' + res.error, 'error');
  }
}

async function viewConnectorDetails(id) {
  const res = await apiFetch(`/marketplace/connectors/${id}`);
  if (!res.ok) { toast('Failed to load details', 'error'); return; }
  const c = res.data;
  showModal(`
    <div class="modal-header">
      <h3 class="modal-title">${esc(c.name)} v${esc(c.version)}</h3>
      <button class="modal-close" onclick="closeModal()">×</button>
    </div>
    <p style="color:var(--text-muted);margin-bottom:16px;">${esc(c.description)}</p>
    <div class="two-col" style="gap:8px;margin-bottom:16px;">
      <div><span style="color:var(--text-muted);font-size:12px;">Category</span><div>${esc(c.category)}</div></div>
      <div><span style="color:var(--text-muted);font-size:12px;">Author</span><div>${esc(c.author)}</div></div>
      <div><span style="color:var(--text-muted);font-size:12px;">OAuth</span><div>${c.supports_oauth ? '✓ Yes' : '✗ No'}</div></div>
      <div><span style="color:var(--text-muted);font-size:12px;">Webhooks</span><div>${c.supports_webhook ? '✓ Yes' : '✗ No'}</div></div>
    </div>
    <div style="margin-bottom:12px;"><span style="color:var(--text-muted);font-size:12px;">Permissions</span>
      <div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:6px;">
        ${(c.permissions||[]).map(p=>`<span class="badge badge-info">${esc(p)}</span>`).join('')}
      </div>
    </div>
    <div><span style="color:var(--text-muted);font-size:12px;">Events</span>
      <div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:6px;">
        ${(c.events||[]).map(e=>`<span class="badge badge-inactive">${esc(e)}</span>`).join('')}
      </div>
    </div>
    <div class="modal-footer">
      <button class="btn btn-secondary" onclick="closeModal()">Close</button>
      <button class="btn btn-primary" onclick="closeModal();installConnector('${esc(c.id)}','${esc(c.name)}')">Install</button>
    </div>
  `);
}

// ── INSTALLED CONNECTORS ──────────────────────────────────────────────────────

function updateSidebarVisibility(rows) {
  const cats = new Set((rows || []).map(c => (c.category || '').toLowerCase()));
  const any = cats.size > 0;
  const visibility = {
    'sidebar-erp':        cats.has('erp') || cats.has('accounting'),
    'sidebar-crm':        cats.has('crm'),
    'sidebar-tracking':   cats.has('tracking') || cats.has('shipping'),
    'sidebar-support':    cats.has('support'),
    'sidebar-automation': any,
    'sidebar-operations': any,
  };
  const sectionGroup = {
    erp:'sidebar-erp', vendors:'sidebar-erp', 'purchase-orders':'sidebar-erp',
    invoices:'sidebar-erp', inventory:'sidebar-erp', warehouses:'sidebar-erp',
    crm:'sidebar-crm', pipeline:'sidebar-crm', leads:'sidebar-crm',
    contacts:'sidebar-crm', opportunities:'sidebar-crm',
    tracking:'sidebar-tracking',
    support:'sidebar-support',
    workflows:'sidebar-automation', events:'sidebar-automation',
    queues:'sidebar-operations', logs:'sidebar-operations',
    health:'sidebar-operations', oauth:'sidebar-operations', webhooks:'sidebar-operations',
  };
  for (const [id, visible] of Object.entries(visibility)) {
    const el = document.getElementById(id);
    if (el) el.style.display = visible ? '' : 'none';
  }
  const activeGroup = sectionGroup[_currentSection];
  if (activeGroup && !visibility[activeGroup]) showSection('dashboard');
}

async function loadInstalled() {
  const res = await apiFetch(`/connectors?tenant_id=${_tenantId}`);
  const rows = res.ok ? (res.data.connectors || res.data || []) : [];
  updateSidebarVisibility(rows);
  const tbody = document.getElementById('installedTbody');
  if (!tbody) return;
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="8"><div class="empty-state"><h3>No connectors installed</h3><p>Visit the Marketplace to install your first connector</p></div></td></tr>`;
    return;
  }
  tbody.innerHTML = rows.map(c => `
    <tr>
      <td>
        <div style="display:flex;align-items:center;gap:8px;">
          ${dot(c.status)} <strong>${esc(c.name)}</strong>
        </div>
        <div style="font-size:11px;color:var(--text-muted);">${esc(c.category)}</div>
      </td>
      <td>${statusBadge(c.status)}</td>
      <td>${esc(c.version || '—')}</td>
      <td>${timeAgo(c.last_sync)}</td>
      <td>${timeAgo(c.last_heartbeat)}</td>
      <td>
        <div style="display:flex;align-items:center;gap:8px;min-width:100px;">
          <div class="health-bar" style="flex:1"><div class="health-fill ${healthClass(c.health_score)}" style="width:${Math.round((c.health_score||0)*100)}%"></div></div>
          <span style="font-size:11px;color:var(--text-muted);">${Math.round((c.health_score||0)*100)}%</span>
        </div>
      </td>
      <td>${c.failure_count || 0} fails</td>
      <td>
        <div style="display:flex;gap:6px;">
          <button class="btn btn-xs btn-secondary" onclick="configureConnector('${esc(c.id||c.connector_id)}')">Config</button>
          <button class="btn btn-xs btn-secondary" onclick="testConnector('${esc(c.id||c.connector_id)}')">Test</button>
          <button class="btn btn-xs" style="color:var(--danger);border:1px solid rgba(252,92,92,.2);" onclick="uninstallConnector('${esc(c.id||c.connector_id)}','${esc(c.name)}')">Remove</button>
        </div>
      </td>
    </tr>`).join('');
}

function healthClass(score) {
  if ((score||0) >= .75) return 'high';
  if ((score||0) >= .4)  return 'medium';
  return 'low';
}

async function configureConnector(id) {
  const res = await apiFetch(`/connectors/${id}`);
  if (!res.ok) { toast('Failed to load connector', 'error'); return; }
  const c = res.data;
  showModal(`
    <div class="modal-header">
      <h3 class="modal-title">Configure ${esc(c.name)}</h3>
      <button class="modal-close" onclick="closeModal()">×</button>
    </div>
    <div style="display:flex;gap:8px;margin-bottom:16px;align-items:center;">
      ${statusBadge(c.status)}
      <span style="color:var(--text-muted);font-size:12px;">v${esc(c.version||'1.0.0')}</span>
    </div>
    <div class="settings-row" style="padding:0 0 12px 0;border-bottom:1px solid var(--border);">
      <div class="settings-info"><div class="settings-key">Active</div><div class="settings-desc">Enable or disable this connector</div></div>
      <label class="toggle"><input type="checkbox" id="connActive" ${c.is_active ? 'checked' : ''}><div class="toggle-track"></div><div class="toggle-thumb"></div></label>
    </div>
    <div class="form-group" style="margin-top:14px;">
      <label>Configuration (JSON)</label>
      <textarea id="connConfig" rows="6">${esc(JSON.stringify(c.config || {}, null, 2))}</textarea>
    </div>
    <div class="modal-footer">
      <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
      <button class="btn btn-primary" id="saveConnBtn" onclick="saveConnectorConfig('${esc(c.id||c.connector_id)}')">Save Changes</button>
    </div>
  `);
}

async function saveConnectorConfig(id) {
  const btn = document.getElementById('saveConnBtn');
  setBtnLoading(btn, true);
  let config = {};
  try { config = JSON.parse(document.getElementById('connConfig').value || '{}'); } catch { toast('Invalid JSON config', 'error'); setBtnLoading(btn, false); return; }
  const is_active = document.getElementById('connActive').checked;
  const res = await apiFetch(`/connectors/${id}`, { method:'PUT', body:JSON.stringify({ config, is_active }) });
  setBtnLoading(btn, false);
  if (res.ok) { closeModal(); toast('Connector updated', 'success'); loadInstalled(); }
  else toast('Update failed: ' + res.error, 'error');
}

async function testConnector(id) {
  const btn = event.target;
  setBtnLoading(btn, true);
  const res = await apiFetch(`/connectors/${id}/test`, { method:'POST' });
  setBtnLoading(btn, false);
  if (res.ok) toast(`Connection test: ${res.data.message || 'success'}`, 'success');
  else toast('Test failed: ' + res.error, 'error');
}

async function uninstallConnector(id, name) {
  confirm(`Remove connector "${name}"? This cannot be undone.`, async () => {
    const res = await apiFetch(`/connectors/${id}`, { method:'DELETE' });
    if (res.ok) { toast(`${name} removed`, 'success'); loadInstalled(); }
    else toast('Remove failed: ' + res.error, 'error');
  });
}

// ── OAUTH MANAGER ─────────────────────────────────────────────────────────────

async function loadOAuth() {
  const [tokRes, provRes] = await Promise.all([
    apiFetch(`/oauth/tokens?tenant_id=${_tenantId}`),
    apiFetch('/oauth/providers'),
  ]);
  const tokens = tokRes.ok ? (tokRes.data.tokens || tokRes.data || []) : [];
  const providers = provRes.ok ? (provRes.data.providers || provRes.data || []) : [];
  renderOAuthProviders(providers, tokens);
  renderOAuthTokens(tokens);
}

const PROVIDER_ICONS = { google:'🔵', microsoft:'🟦', whatsapp_business:'💚', shopify:'🟣', slack:'🟡', hubspot:'🟠' };

function renderOAuthProviders(providers, tokens) {
  const el = document.getElementById('oauthProviderList');
  if (!el) return;
  el.innerHTML = providers.map(p => {
    const tok = tokens.find(t => t.provider === p.id);
    return `
    <div class="oauth-provider-row">
      <div class="oauth-provider-icon">${PROVIDER_ICONS[p.id] || '🔑'}</div>
      <div class="oauth-provider-info">
        <div class="oauth-provider-name">${esc(p.name)}</div>
        <div class="oauth-provider-sub">${esc(p.description || p.auth_type || 'OAuth 2.0')}</div>
      </div>
      ${tok
        ? `<span class="badge ${tok.is_valid ? 'badge-active' : 'badge-failed'}">${tok.is_valid ? 'Connected' : 'Expired'}</span>
           <button class="btn btn-sm btn-secondary" onclick="revokeToken('${esc(tok.token_id)}')">Disconnect</button>
           ${!tok.is_valid ? `<button class="btn btn-sm btn-primary" onclick="refreshToken('${esc(tok.token_id)}')">Refresh</button>` : ''}`
        : `<span class="badge badge-inactive">Not connected</span>
           <button class="btn btn-sm btn-primary" onclick="startOAuth('${esc(p.id)}')">Connect</button>`
      }
    </div>`;
  }).join('');
}

function renderOAuthTokens(tokens) {
  const tbody = document.getElementById('oauthTokenTbody');
  if (!tbody) return;
  if (!tokens.length) {
    tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--text-muted);padding:24px;">No OAuth tokens stored</td></tr>';
    return;
  }
  tbody.innerHTML = tokens.map(t => `
    <tr>
      <td>${esc(t.provider)}</td>
      <td>${esc(t.connector_id || '—')}</td>
      <td>${(t.scopes||[]).map(s => `<span class="badge badge-info">${esc(s)}</span>`).join(' ')}</td>
      <td>${t.is_valid ? '<span class="badge badge-active">Valid</span>' : '<span class="badge badge-failed">Expired</span>'}</td>
      <td>${esc(formatDate(t.expires_at))}</td>
      <td>
        <button class="btn btn-xs btn-secondary" onclick="revokeToken('${esc(t.id)}')">Revoke</button>
        ${!t.is_valid ? `<button class="btn btn-xs btn-primary" onclick="refreshToken('${esc(t.id)}')">Refresh</button>` : ''}
      </td>
    </tr>`).join('');
}

async function startOAuth(provider) {
  const res = await apiFetch(`/oauth/authorize/${provider}?tenant_id=${_tenantId}`, { method:'GET' });
  if (res.ok && res.data.auth_url) {
    window.open(res.data.auth_url, '_blank', 'width=600,height=700');
    toast(`OAuth flow started for ${provider}`, 'info');
  } else toast('Failed to start OAuth: ' + res.error, 'error');
}

async function revokeToken(tokenId) {
  const res = await apiFetch(`/oauth/tokens/${tokenId}`, { method:'DELETE' });
  if (res.ok) { toast('Token revoked', 'success'); loadOAuth(); }
  else toast('Revoke failed: ' + res.error, 'error');
}

async function refreshToken(tokenId) {
  const res = await apiFetch(`/oauth/tokens/${tokenId}/refresh`, { method:'POST', body:'{}' });
  if (res.ok) { toast('Token refreshed', 'success'); loadOAuth(); }
  else toast('Refresh failed: ' + res.error, 'error');
}

// ── WEBHOOK MANAGER ───────────────────────────────────────────────────────────

async function loadWebhooks() {
  const res = await apiFetch(`/webhooks?tenant_id=${_tenantId}`);
  const rows = res.ok ? (res.data.webhooks || res.data || []) : [];
  const tbody = document.getElementById('webhookTbody');
  if (!tbody) return;
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="6"><div class="empty-state"><h3>No webhooks configured</h3><p>Create a webhook to start receiving events</p></div></td></tr>';
    return;
  }
  tbody.innerHTML = rows.map(w => `
    <tr>
      <td>${esc(w.connector_id || '—')}</td>
      <td><span class="webhook-url">${esc(w.url)}</span></td>
      <td>${(w.events||[]).map(e=>`<span class="badge badge-info">${esc(e)}</span>`).join(' ')}</td>
      <td>${w.is_active ? '<span class="badge badge-active">Active</span>' : '<span class="badge badge-inactive">Inactive</span>'}</td>
      <td>${timeAgo(w.last_triggered)}</td>
      <td>${w.success_count||0}✓ / ${w.failure_count||0}✗</td>
      <td>
        <button class="btn btn-xs btn-secondary" onclick="testWebhook('${esc(w.webhook_id)}')">Test</button>
        <button class="btn btn-xs btn-secondary" onclick="editWebhook('${esc(w.webhook_id)}')">Edit</button>
        <button class="btn btn-xs" style="color:var(--danger);border:1px solid rgba(252,92,92,.2);" onclick="deleteWebhook('${esc(w.webhook_id)}')">Delete</button>
      </td>
    </tr>`).join('');
}

function createWebhookModal() {
  showModal(`
    <div class="modal-header"><h3 class="modal-title">Create Webhook</h3><button class="modal-close" onclick="closeModal()">×</button></div>
    <div class="form-group"><label>Connector ID</label><input id="wkConnector" placeholder="connector_id" /></div>
    <div class="form-group"><label>Endpoint URL</label><input id="wkUrl" type="url" placeholder="https://your-server.com/webhook" /></div>
    <div class="form-group"><label>Events (comma-separated)</label><input id="wkEvents" placeholder="invoice.created,shipment.updated" /></div>
    <div class="modal-footer">
      <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
      <button class="btn btn-primary" id="createWkBtn" onclick="submitCreateWebhook()">Create Webhook</button>
    </div>
  `);
}

async function submitCreateWebhook() {
  const btn = document.getElementById('createWkBtn');
  setBtnLoading(btn, true);
  const connector_id = document.getElementById('wkConnector').value;
  const url = document.getElementById('wkUrl').value;
  const events = document.getElementById('wkEvents').value.split(',').map(s=>s.trim()).filter(Boolean);
  if (!url) { toast('URL is required', 'error'); setBtnLoading(btn, false); return; }
  const res = await apiFetch('/webhooks', { method:'POST', body:JSON.stringify({ connector_id, tenant_id:_tenantId, url, events }) });
  setBtnLoading(btn, false);
  if (res.ok) { closeModal(); toast('Webhook created', 'success'); loadWebhooks(); }
  else toast('Create failed: ' + res.error, 'error');
}

async function testWebhook(id) {
  const res = await apiFetch(`/webhooks/${id}/test`, { method:'POST', body:'{}' });
  if (res.ok) toast('Test event delivered successfully', 'success');
  else toast('Test delivery failed: ' + res.error, 'error');
}

async function deleteWebhook(id) {
  confirm('Delete this webhook?', async () => {
    const res = await apiFetch(`/webhooks/${id}`, { method:'DELETE' });
    if (res.ok) { toast('Webhook deleted', 'success'); loadWebhooks(); }
    else toast('Delete failed: ' + res.error, 'error');
  });
}

// ── QUEUE MONITOR ─────────────────────────────────────────────────────────────

async function loadQueues() {
  const [statsRes, jobsRes, dlRes] = await Promise.all([
    apiFetch(`/queues/stats?tenant_id=${_tenantId}`),
    apiFetch(`/queues/jobs?tenant_id=${_tenantId}&limit=25`),
    apiFetch(`/queues/dead-letters?tenant_id=${_tenantId}`),
  ]);
  if (statsRes.ok) renderQueueStats(statsRes.data);
  const jobs = jobsRes.ok ? (jobsRes.data.jobs || jobsRes.data || []) : [];
  renderQueueJobs(jobs, 'queueJobsTbody');
  const dl = dlRes.ok ? (dlRes.data.jobs || dlRes.data || []) : [];
  renderQueueJobs(dl, 'deadLetterTbody', true);
}

function renderQueueStats(s) {
  const ids = { queued:'qstatQueued', processing:'qstatProcessing', dead:'qstatDead', processed:'qstatProcessed' };
  const vals = { queued: s.queued||s.total_queued||0, processing: s.processing||0, dead: s.dead_letters||s.total_dead_letters||0, processed: s.total_processed||0 };
  Object.entries(ids).forEach(([k, id]) => {
    const el = document.getElementById(id);
    if (el) el.textContent = vals[k];
  });
}

function renderQueueJobs(jobs, tbodyId, isDL = false) {
  const tbody = document.getElementById(tbodyId);
  if (!tbody) return;
  if (!jobs.length) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center;color:var(--text-muted);padding:20px;">${isDL ? 'No dead-letter items' : 'No jobs in queue'}</td></tr>`;
    return;
  }
  tbody.innerHTML = jobs.map(j => `
    <tr>
      <td style="font-family:monospace;font-size:11px;">${esc((j.job_id||j.id||'').slice(0,12))}…</td>
      <td>${esc(j.connector_id||'—')}</td>
      <td>${esc(j.job_type||'—')}</td>
      <td>${statusBadge(j.status)}</td>
      <td>${j.attempts||0} / ${j.max_attempts||3}</td>
      <td>${esc(j.error ? j.error.slice(0,40)+'…' : '—')}</td>
      <td>${timeAgo(j.created_at)}</td>
      <td>
        ${isDL || j.status === 'failed' || j.status === 'dead'
          ? `<button class="btn btn-xs btn-secondary" onclick="retryJob('${esc(j.job_id||j.id)}',${isDL})">Retry</button>` : ''}
        <button class="btn btn-xs" style="color:var(--danger);border:1px solid rgba(252,92,92,.2);" onclick="cancelJob('${esc(j.job_id||j.id)}')">Cancel</button>
      </td>
    </tr>`).join('');
}

async function retryJob(id, isDL) {
  const endpoint = isDL ? `/queues/dead-letters/${id}/retry` : `/queues/jobs/${id}/retry`;
  const res = await apiFetch(endpoint, { method:'POST', body:'{}' });
  if (res.ok) { toast('Job queued for retry', 'success'); loadQueues(); }
  else toast('Retry failed: ' + res.error, 'error');
}

async function cancelJob(id) {
  confirm('Cancel this job?', async () => {
    const res = await apiFetch(`/queues/jobs/${id}`, { method:'DELETE' });
    if (res.ok) { toast('Job cancelled', 'success'); loadQueues(); }
    else toast('Cancel failed: ' + res.error, 'error');
  });
}

async function clearDeadLetters() {
  confirm('Clear all dead-letter items for this tenant?', async () => {
    const res = await apiFetch(`/queues/dead-letters?tenant_id=${_tenantId}`, { method:'DELETE' });
    if (res.ok) { toast('Dead-letter queue cleared', 'success'); loadQueues(); }
    else toast('Clear failed: ' + res.error, 'error');
  });
}

// ── LOGS ──────────────────────────────────────────────────────────────────────

let _logWs = null;

async function loadLogs() {
  const level = document.getElementById('logLevelFilter')?.value || '';
  const connector = document.getElementById('logConnFilter')?.value || '';
  let path = `/logs?tenant_id=${_tenantId}&limit=100`;
  if (level) path += `&level=${level}`;
  if (connector) path += `&connector_id=${connector}`;
  const res = await apiFetch(path);
  const logs = res.ok ? (res.data.logs || res.data || []) : [];
  const el = document.getElementById('logStreamEl');
  if (el) {
    el.innerHTML = logs.length
      ? logs.map(l => renderLogLine(l)).join('')
      : '<div style="padding:16px;color:var(--text-muted);text-align:center;">No logs found</div>';
    el.scrollTop = el.scrollHeight;
  }
}

function renderLogLine(l) {
  return `<div class="log-line">
    <span class="log-ts">${esc(formatDate(l.timestamp||l.created_at))}</span>
    <span class="log-lvl ${esc(l.level||'INFO')}">${esc(l.level||'INFO')}</span>
    <span class="log-connector">[${esc(l.connector_id||'system')}]</span>
    <span class="log-msg">${esc(l.message)}</span>
  </div>`;
}

function toggleLogStream() {
  const btn = document.getElementById('streamBtn');
  if (_logWs) {
    _logWs.close();
    _logWs = null;
    if (btn) btn.textContent = 'Start Live Stream';
    toast('Log stream stopped', 'info');
    return;
  }
  const wsUrl = `ws://${location.host}/api/connector-panel/logs/stream`;
  try {
    _logWs = new WebSocket(wsUrl);
    _logWs.onmessage = e => {
      try {
        const l = JSON.parse(e.data);
        const el = document.getElementById('logStreamEl');
        if (el) {
          el.insertAdjacentHTML('beforeend', renderLogLine(l));
          el.scrollTop = el.scrollHeight;
          if (el.children.length > 500) el.removeChild(el.firstChild);
        }
      } catch {}
    };
    _logWs.onopen = () => { if (btn) btn.textContent = 'Stop Stream'; toast('Live log stream started', 'success'); };
    _logWs.onclose = () => { _logWs = null; if (btn) btn.textContent = 'Start Live Stream'; };
    _logWs.onerror = () => { toast('WebSocket connection failed — live stream unavailable', 'warn'); };
  } catch { toast('WebSocket not supported', 'error'); }
}

// ── HEALTH ────────────────────────────────────────────────────────────────────

async function loadHealth() {
  const res = await apiFetch(`/health/connectors?tenant_id=${_tenantId}`);
  const items = res.ok ? (res.data.connectors || res.data || []) : [];
  const grid = document.getElementById('healthGrid');
  if (!grid) return;
  if (!items.length) {
    grid.innerHTML = '<div class="empty-state" style="grid-column:1/-1"><h3>No connectors to monitor</h3><p>Install connectors to view their health</p></div>';
    return;
  }
  grid.innerHTML = items.map(c => {
    const score = Math.round((c.health_score||c.score||0)*100);
    return `
    <div class="health-card">
      <div class="health-card-header">
        ${dot(c.status||'inactive')}
        <span class="health-name">${esc(c.name||c.connector_id)}</span>
        <span class="health-score" style="color:${score>=75?'var(--success)':score>=40?'var(--warning)':'var(--danger)'}">${score}%</span>
      </div>
      <div class="health-bar"><div class="health-fill ${healthClass(c.health_score||c.score)}" style="width:${score}%"></div></div>
      <div class="health-meta">
        <span class="health-key">Last Heartbeat</span><span class="health-val">${timeAgo(c.last_heartbeat)}</span>
        <span class="health-key">Last Sync</span><span class="health-val">${timeAgo(c.last_sync)}</span>
        <span class="health-key">Failures</span><span class="health-val">${c.failure_count||0}</span>
        <span class="health-key">Retries</span><span class="health-val">${c.retry_count||0}</span>
        ${c.response_latency_ms ? `<span class="health-key">Latency</span><span class="health-val">${esc(c.response_latency_ms)}ms</span>` : ''}
        ${c.api_quota_limit ? `<span class="health-key">API Quota</span><span class="health-val">${esc(c.api_quota_used||0)}/${esc(c.api_quota_limit)}</span>` : ''}
      </div>
    </div>`;
  }).join('');
}

// ── PLUGINS ───────────────────────────────────────────────────────────────────

async function loadPlugins() {
  const res = await apiFetch('/plugins');
  const plugins = res.ok ? (res.data.plugins || res.data || []) : [];
  const tbody = document.getElementById('pluginsTbody');
  if (!tbody) return;
  if (!plugins.length) {
    tbody.innerHTML = '<tr><td colspan="6"><div class="empty-state"><h3>No plugins registered</h3></div></td></tr>';
    return;
  }
  tbody.innerHTML = plugins.map(p => `
    <tr>
      <td><strong>${esc(p.name||p.plugin_id)}</strong><div style="font-size:11px;color:var(--text-muted);">${esc(p.plugin_id||p.id||'')}</div></td>
      <td>${esc(p.version||'—')}</td>
      <td>${esc(p.category||p.type||'—')}</td>
      <td>${statusBadge(p.status||'registered')}</td>
      <td>${(p.permissions||p.hooks||[]).slice(0,3).map(h=>`<span class="badge badge-info">${esc(h)}</span>`).join(' ')}</td>
      <td>
        ${p.status==='enabled'
          ? `<button class="btn btn-xs btn-secondary" onclick="togglePlugin('${esc(p.plugin_id||p.id)}','disable')">Disable</button>`
          : `<button class="btn btn-xs btn-primary" onclick="togglePlugin('${esc(p.plugin_id||p.id)}','enable')">Enable</button>`
        }
        <button class="btn btn-xs btn-secondary" onclick="viewPluginPerms('${esc(p.plugin_id||p.id)}')">Permissions</button>
      </td>
    </tr>`).join('');
}

async function togglePlugin(id, action) {
  const res = await apiFetch(`/plugins/${id}/${action}`, { method:'POST', body:'{}' });
  if (res.ok) { toast(`Plugin ${action}d`, 'success'); loadPlugins(); }
  else toast(`${action} failed: ` + res.error, 'error');
}

async function viewPluginPerms(id) {
  const res = await apiFetch(`/plugins/${id}/permissions`);
  const perms = res.ok ? (res.data.permissions||res.data||[]) : [];
  showModal(`
    <div class="modal-header"><h3 class="modal-title">Permissions: ${esc(id)}</h3><button class="modal-close" onclick="closeModal()">×</button></div>
    <div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:16px;">
      ${perms.length ? perms.map(p=>`
        <div style="display:flex;align-items:center;gap:6px;background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:6px 10px;">
          <span class="badge badge-active">${esc(p.permission)}</span>
          <span style="font-size:11px;color:var(--text-muted);">${esc(p.granted_by||'system')}</span>
          <button class="btn btn-xs" style="color:var(--danger);" onclick="revokePermission('${esc(id)}','${esc(p.permission)}')">✕</button>
        </div>`).join('')
      : '<p style="color:var(--text-muted);">No permissions granted</p>'}
    </div>
    <div class="input-group">
      <input id="newPermInput" placeholder="permission.scope" />
      <button class="btn btn-primary btn-sm" onclick="grantPermission('${esc(id)}')">Grant</button>
    </div>
    <div class="modal-footer"><button class="btn btn-secondary" onclick="closeModal()">Close</button></div>
  `);
}

async function grantPermission(pluginId) {
  const perm = document.getElementById('newPermInput')?.value?.trim();
  if (!perm) { toast('Enter a permission', 'error'); return; }
  const res = await apiFetch(`/plugins/${pluginId}/permissions`, {
    method:'POST', body:JSON.stringify({ permission:perm, tenant_id:_tenantId, granted_by:'admin' })
  });
  if (res.ok) { toast(`Permission "${perm}" granted`, 'success'); closeModal(); }
  else toast('Grant failed: ' + res.error, 'error');
}

async function revokePermission(pluginId, permission) {
  const res = await apiFetch(`/plugins/${pluginId}/permissions/${encodeURIComponent(permission)}`, { method:'DELETE' });
  if (res.ok) { toast('Permission revoked', 'success'); closeModal(); }
  else toast('Revoke failed: ' + res.error, 'error');
}

// ── EVENTS ────────────────────────────────────────────────────────────────────

let _eventWs = null;

async function loadEvents() {
  const [evRes, typeRes] = await Promise.all([
    apiFetch(`/events?tenant_id=${_tenantId}&limit=50`),
    apiFetch('/events/types'),
  ]);
  const events = evRes.ok ? (evRes.data.events || evRes.data || []) : [];
  const types = typeRes.ok ? (typeRes.data.event_types || typeRes.data || []) : [];
  renderEventTypes(types);
  renderEventFeed(events);
}

function renderEventTypes(types) {
  const el = document.getElementById('eventTypeGrid');
  if (!el) return;
  el.innerHTML = types.slice(0,20).map(t =>
    `<span class="badge badge-info" style="cursor:pointer;" onclick="filterEventType('${esc(t)}')">${esc(t)}</span>`
  ).join('');
}

function renderEventFeed(events) {
  const el = document.getElementById('eventFeed');
  if (!el) return;
  el.innerHTML = events.length
    ? events.map(e => `
      <div style="display:flex;align-items:flex-start;gap:10px;padding:10px 0;border-bottom:1px solid var(--border);">
        <span class="badge badge-info" style="flex-shrink:0;">${esc(e.event_type)}</span>
        <div style="flex:1;min-width:0;">
          <div style="font-size:12px;color:var(--text-muted);">${esc(e.source_connector_id||'system')} · ${timeAgo(e.published_at)}</div>
          <div style="font-size:12px;margin-top:2px;font-family:monospace;">${esc(JSON.stringify(e.payload||{}).slice(0,80))}</div>
        </div>
      </div>`).join('')
    : '<div style="color:var(--text-muted);padding:20px;text-align:center;">No events yet</div>';
}

function subscribeToEvents() {
  if (_eventWs) { _eventWs.close(); _eventWs = null; document.getElementById('subEventsBtn').textContent = 'Subscribe Live'; return; }
  const wsUrl = `ws://${location.host}/api/connector-panel/events/subscribe`;
  try {
    _eventWs = new WebSocket(wsUrl);
    _eventWs.onmessage = e => {
      try {
        const ev = JSON.parse(e.data);
        const feed = document.getElementById('eventFeed');
        if (feed) {
          const line = `<div style="display:flex;align-items:flex-start;gap:10px;padding:10px 0;border-bottom:1px solid var(--border);animation:slideIn .2s ease;">
            <span class="badge badge-active" style="flex-shrink:0;">${esc(ev.event_type)}</span>
            <div style="flex:1;min-width:0;"><div style="font-size:12px;color:var(--text-muted);">${esc(ev.source_connector_id||'system')} · just now</div>
            <div style="font-size:12px;margin-top:2px;font-family:monospace;">${esc(JSON.stringify(ev.payload||{}).slice(0,80))}</div></div></div>`;
          feed.insertAdjacentHTML('afterbegin', line);
        }
      } catch {}
    };
    _eventWs.onopen = () => { document.getElementById('subEventsBtn').textContent = 'Unsubscribe'; toast('Live event stream connected', 'success'); };
    _eventWs.onclose = () => { _eventWs = null; document.getElementById('subEventsBtn').textContent = 'Subscribe Live'; };
    _eventWs.onerror = () => toast('Event stream connection failed', 'warn');
  } catch { toast('WebSocket not supported', 'error'); }
}

// ── PERMISSIONS ───────────────────────────────────────────────────────────────

async function loadPermissions() {
  const res = await apiFetch(`/plugins?tenant_id=${_tenantId}`);
  const plugins = res.ok ? (res.data.plugins || res.data || []) : [];
  renderPermissionsMatrix(plugins);
}

const COMMON_PERMS = ['messages.read','messages.send','connectors.view','connectors.run','approvals.view','approvals.decide','ocr.view','ocr.review','search.view','tracking.view','workspace.view'];

function renderPermissionsMatrix(plugins) {
  const el = document.getElementById('permissionsMatrix');
  if (!el) return;
  el.innerHTML = `
    <table class="permissions-table">
      <thead><tr><th>Plugin</th>${COMMON_PERMS.map(p=>`<th style="writing-mode:vertical-lr;transform:rotate(180deg);padding:8px 4px;font-size:10px;">${esc(p)}</th>`).join('')}</tr></thead>
      <tbody>
        ${plugins.map(p => `
          <tr>
            <td><strong>${esc(p.name||p.plugin_id)}</strong></td>
            ${COMMON_PERMS.map(perm => {
              const has = (p.permissions||[]).includes(perm);
              return `<td class="check ${has?'granted':'denied'}" title="${esc(perm)}">${has ? '✓' : '·'}</td>`;
            }).join('')}
          </tr>`).join('')}
      </tbody>
    </table>`;
}

// ── PANEL SETTINGS ────────────────────────────────────────────────────────────

function loadSettings() {
  const tenantEl = document.getElementById('settingsTenant');
  if (tenantEl) tenantEl.value = _tenantId;
}

function saveSettings() {
  const val = document.getElementById('settingsTenant')?.value?.trim();
  if (val) { _tenantId = val; toast('Settings saved', 'success'); }
  else toast('Tenant ID cannot be empty', 'error');
}

// ── ERP ───────────────────────────────────────────────────────────────────────

async function loadERP() {
  const res = await apiFetch(`/erp/summary?tenant_id=${_tenantId}`);
  if (!res.ok) return;
  const d = res.data;
  _setEl('erpVendors', d.total_vendors ?? '—');
  _setEl('erpPOs', d.total_pos ?? '—');
  _setEl('erpOverdueInv', d.overdue_invoices ?? '—');
  _setEl('erpLowStock', d.low_stock_items ?? '—');
  _setEl('erpWarehouses', d.total_warehouses ?? '—');

  const posRes = await apiFetch(`/erp/purchase-orders?tenant_id=${_tenantId}&limit=5`);
  const pos = posRes.ok ? (posRes.data.purchase_orders || posRes.data || []) : [];
  const el = document.getElementById('erpRecentPOs');
  if (el) {
    el.innerHTML = pos.length
      ? pos.map(p => `
        <div style="display:flex;align-items:center;gap:8px;padding:8px 0;border-bottom:1px solid var(--border);">
          <span style="font-size:12px;font-weight:600;">${esc(p.po_number)}</span>
          <span style="font-size:11px;color:var(--text-muted);">${esc(p.vendor_name||'—')}</span>
          ${statusBadge(p.status)}
          <span style="margin-left:auto;font-size:12px;">${p.total_amount ? '$'+Number(p.total_amount).toLocaleString() : '—'}</span>
        </div>`).join('')
      : '<div style="padding:16px;color:var(--text-muted);text-align:center;">No purchase orders</div>';
  }
}

async function loadVendors() {
  const q = document.getElementById('vendorSearch')?.value || '';
  let path = `/erp/vendors?tenant_id=${_tenantId}&limit=100`;
  if (q) path += `&q=${encodeURIComponent(q)}`;
  const res = await apiFetch(path);
  const rows = res.ok ? (res.data.vendors || res.data || []) : [];
  const tbody = document.getElementById('vendorsTbody');
  if (!tbody) return;
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="7"><div class="empty-state"><h3>No vendors found</h3><p>Add your first vendor to get started</p></div></td></tr>`;
    return;
  }
  tbody.innerHTML = rows.map(v => `
    <tr>
      <td><strong>${esc(v.name)}</strong></td>
      <td style="font-family:monospace;font-size:11px;">${esc(v.code||'—')}</td>
      <td><a href="mailto:${esc(v.email||'')}" style="color:var(--accent);">${esc(v.email||'—')}</a></td>
      <td>${esc(v.category||'—')}</td>
      <td>${esc(v.payment_terms||'—')}</td>
      <td>${statusBadge(v.status||'active')}</td>
      <td>
        <button class="btn btn-xs btn-secondary" onclick="editVendorModal('${esc(v.id)}')">Edit</button>
        <button class="btn btn-xs" style="color:var(--danger);border:1px solid rgba(220,38,38,.2);" onclick="deleteVendor('${esc(v.id)}','${esc(v.name)}')">Remove</button>
      </td>
    </tr>`).join('');
}

function createVendorModal(v = {}) {
  const edit = !!v.id;
  showModal(`
    <div class="modal-header"><h3 class="modal-title">${edit ? 'Edit' : 'Add'} Vendor</h3><button class="modal-close" onclick="closeModal()">×</button></div>
    <div class="two-col" style="gap:12px;">
      <div class="form-group"><label>Vendor Name *</label><input id="vnName" value="${esc(v.name||'')}" placeholder="Acme Corp" /></div>
      <div class="form-group"><label>Vendor Code</label><input id="vnCode" value="${esc(v.code||'')}" placeholder="VND-001" /></div>
    </div>
    <div class="two-col" style="gap:12px;">
      <div class="form-group"><label>Email</label><input id="vnEmail" type="email" value="${esc(v.email||'')}" /></div>
      <div class="form-group"><label>Phone</label><input id="vnPhone" value="${esc(v.phone||'')}" /></div>
    </div>
    <div class="two-col" style="gap:12px;">
      <div class="form-group"><label>Category</label>
        <select id="vnCategory">
          ${['supplier','manufacturer','distributor','service'].map(c=>`<option ${v.category===c?'selected':''}>${c}</option>`).join('')}
        </select>
      </div>
      <div class="form-group"><label>Payment Terms</label><input id="vnTerms" value="${esc(v.payment_terms||'Net 30')}" /></div>
    </div>
    <div class="form-group"><label>Address</label><input id="vnAddress" value="${esc(v.address||'')}" /></div>
    <div class="modal-footer">
      <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
      <button class="btn btn-primary" id="saveVnBtn" onclick="submitVendor('${esc(v.id||'')}')">Save Vendor</button>
    </div>
  `);
}

async function editVendorModal(id) {
  const res = await apiFetch(`/erp/vendors/${id}`);
  if (res.ok) createVendorModal(res.data);
  else toast('Failed to load vendor', 'error');
}

async function submitVendor(id) {
  const btn = document.getElementById('saveVnBtn');
  setBtnLoading(btn, true);
  const body = {
    name: document.getElementById('vnName').value.trim(),
    code: document.getElementById('vnCode').value.trim(),
    email: document.getElementById('vnEmail').value.trim(),
    phone: document.getElementById('vnPhone').value.trim(),
    category: document.getElementById('vnCategory').value,
    payment_terms: document.getElementById('vnTerms').value.trim(),
    address: document.getElementById('vnAddress').value.trim(),
    tenant_id: _tenantId,
  };
  if (!body.name) { toast('Vendor name required', 'error'); setBtnLoading(btn, false); return; }
  const res = id
    ? await apiFetch(`/erp/vendors/${id}`, { method:'PATCH', body:JSON.stringify(body) })
    : await apiFetch('/erp/vendors', { method:'POST', body:JSON.stringify(body) });
  setBtnLoading(btn, false);
  if (res.ok) { closeModal(); toast(id ? 'Vendor updated' : 'Vendor created', 'success'); loadVendors(); }
  else toast('Save failed: ' + res.error, 'error');
}

async function deleteVendor(id, name) {
  confirm(`Remove vendor "${name}"?`, async () => {
    const res = await apiFetch(`/erp/vendors/${id}`, { method:'DELETE' });
    if (res.ok) { toast('Vendor removed', 'success'); loadVendors(); }
    else toast('Delete failed: ' + res.error, 'error');
  });
}

async function loadPurchaseOrders() {
  const status = document.getElementById('poStatusFilter')?.value || '';
  let path = `/erp/purchase-orders?tenant_id=${_tenantId}&limit=100`;
  if (status) path += `&status=${status}`;
  const res = await apiFetch(path);
  const rows = res.ok ? (res.data.purchase_orders || res.data || []) : [];
  const tbody = document.getElementById('poTbody');
  if (!tbody) return;
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="7"><div class="empty-state"><h3>No purchase orders</h3></div></td></tr>`;
    return;
  }
  tbody.innerHTML = rows.map(p => `
    <tr>
      <td><strong>${esc(p.po_number)}</strong></td>
      <td>${esc(p.vendor_name||p.vendor_id||'—')}</td>
      <td>${statusBadge(p.status)}</td>
      <td>${p.total_amount ? '$'+Number(p.total_amount).toLocaleString() : '—'}</td>
      <td>${esc(formatDate(p.order_date))}</td>
      <td>${esc(formatDate(p.expected_delivery))}</td>
      <td>
        <button class="btn btn-xs btn-secondary" onclick="editPOModal('${esc(p.id)}')">Edit</button>
        <button class="btn btn-xs btn-secondary" onclick="updatePOStatus('${esc(p.id)}','${esc(p.status)}')">Status</button>
      </td>
    </tr>`).join('');
}

function createPOModal(po = {}) {
  const edit = !!po.id;
  showModal(`
    <div class="modal-header"><h3 class="modal-title">${edit ? 'Edit' : 'New'} Purchase Order</h3><button class="modal-close" onclick="closeModal()">×</button></div>
    <div class="two-col" style="gap:12px;">
      <div class="form-group"><label>PO Number</label><input id="poNum" value="${esc(po.po_number||'')}" placeholder="PO-2026-001" /></div>
      <div class="form-group"><label>Vendor ID *</label><input id="poVendor" value="${esc(po.vendor_id||'')}" placeholder="vendor_id" /></div>
    </div>
    <div class="two-col" style="gap:12px;">
      <div class="form-group"><label>Total Amount</label><input id="poAmount" type="number" step="0.01" value="${esc(po.total_amount||'')}" /></div>
      <div class="form-group"><label>Currency</label><input id="poCurrency" value="${esc(po.currency||'USD')}" /></div>
    </div>
    <div class="two-col" style="gap:12px;">
      <div class="form-group"><label>Order Date</label><input id="poOrderDate" type="date" value="${esc((po.order_date||'').slice(0,10))}" /></div>
      <div class="form-group"><label>Expected Delivery</label><input id="poDelivery" type="date" value="${esc((po.expected_delivery||'').slice(0,10))}" /></div>
    </div>
    <div class="form-group"><label>Notes</label><textarea id="poNotes">${esc(po.notes||'')}</textarea></div>
    <div class="modal-footer">
      <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
      <button class="btn btn-primary" id="savePOBtn" onclick="submitPO('${esc(po.id||'')}')">Save PO</button>
    </div>
  `);
}

async function editPOModal(id) {
  const res = await apiFetch(`/erp/purchase-orders/${id}`);
  if (res.ok) createPOModal(res.data);
  else toast('Failed to load PO', 'error');
}

async function submitPO(id) {
  const btn = document.getElementById('savePOBtn');
  setBtnLoading(btn, true);
  const body = {
    po_number: document.getElementById('poNum').value.trim(),
    vendor_id: document.getElementById('poVendor').value.trim(),
    total_amount: parseFloat(document.getElementById('poAmount').value) || 0,
    currency: document.getElementById('poCurrency').value.trim() || 'USD',
    order_date: document.getElementById('poOrderDate').value || null,
    expected_delivery: document.getElementById('poDelivery').value || null,
    notes: document.getElementById('poNotes').value.trim(),
    tenant_id: _tenantId,
  };
  if (!body.vendor_id) { toast('Vendor ID required', 'error'); setBtnLoading(btn, false); return; }
  const res = id
    ? await apiFetch(`/erp/purchase-orders/${id}`, { method:'PATCH', body:JSON.stringify(body) })
    : await apiFetch('/erp/purchase-orders', { method:'POST', body:JSON.stringify(body) });
  setBtnLoading(btn, false);
  if (res.ok) { closeModal(); toast('PO saved', 'success'); loadPurchaseOrders(); }
  else toast('Save failed: ' + res.error, 'error');
}

async function updatePOStatus(id, current) {
  const statuses = ['draft','pending','approved','received','cancelled'];
  showModal(`
    <div class="modal-header"><h3 class="modal-title">Update PO Status</h3><button class="modal-close" onclick="closeModal()">×</button></div>
    <div class="form-group"><label>New Status</label>
      <select id="poStatusSel">${statuses.map(s=>`<option value="${s}" ${s===current?'selected':''}>${s}</option>`).join('')}</select>
    </div>
    <div class="modal-footer">
      <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
      <button class="btn btn-primary" onclick="apiFetch('/erp/purchase-orders/${id}',{method:'PATCH',body:JSON.stringify({status:document.getElementById('poStatusSel').value})}).then(r=>{closeModal();if(r.ok){toast('Status updated','success');loadPurchaseOrders();}else toast('Failed: '+r.error,'error')})">Update</button>
    </div>
  `);
}

async function loadInvoices() {
  const status = document.getElementById('invStatusFilter')?.value || '';
  let path = `/erp/invoices?tenant_id=${_tenantId}&limit=100`;
  if (status) path += `&status=${status}`;
  const res = await apiFetch(path);
  const rows = res.ok ? (res.data.invoices || res.data || []) : [];
  const tbody = document.getElementById('invoicesTbody');
  if (!tbody) return;
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="6"><div class="empty-state"><h3>No invoices found</h3></div></td></tr>`;
    return;
  }
  tbody.innerHTML = rows.map(inv => `
    <tr>
      <td><strong>${esc(inv.invoice_number)}</strong></td>
      <td>${esc(inv.vendor_name||inv.vendor_id||'—')}</td>
      <td>${statusBadge(inv.status)}</td>
      <td>${inv.amount ? '$'+Number(inv.amount).toLocaleString() : '—'}</td>
      <td style="${inv.status==='overdue'?'color:var(--danger);font-weight:600;':''}">${esc(formatDate(inv.due_date))}</td>
      <td>
        <button class="btn btn-xs btn-secondary" onclick="editInvoiceModal('${esc(inv.id)}')">Edit</button>
        ${inv.status!=='paid'?`<button class="btn btn-xs btn-primary" onclick="markInvoicePaid('${esc(inv.id)}')">Mark Paid</button>`:''}
      </td>
    </tr>`).join('');
}

function createInvoiceModal(inv = {}) {
  const edit = !!inv.id;
  showModal(`
    <div class="modal-header"><h3 class="modal-title">${edit ? 'Edit' : 'New'} Invoice</h3><button class="modal-close" onclick="closeModal()">×</button></div>
    <div class="two-col" style="gap:12px;">
      <div class="form-group"><label>Invoice Number</label><input id="invNum" value="${esc(inv.invoice_number||'')}" placeholder="INV-2026-001" /></div>
      <div class="form-group"><label>Vendor ID *</label><input id="invVendor" value="${esc(inv.vendor_id||'')}" /></div>
    </div>
    <div class="two-col" style="gap:12px;">
      <div class="form-group"><label>Amount</label><input id="invAmount" type="number" step="0.01" value="${esc(inv.amount||'')}" /></div>
      <div class="form-group"><label>Due Date</label><input id="invDue" type="date" value="${esc((inv.due_date||'').slice(0,10))}" /></div>
    </div>
    <div class="form-group"><label>Notes</label><textarea id="invNotes">${esc(inv.notes||'')}</textarea></div>
    <div class="modal-footer">
      <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
      <button class="btn btn-primary" id="saveInvBtn" onclick="submitInvoice('${esc(inv.id||'')}')">Save Invoice</button>
    </div>
  `);
}

async function editInvoiceModal(id) {
  const res = await apiFetch(`/erp/invoices/${id}`);
  if (res.ok) createInvoiceModal(res.data);
  else toast('Failed to load invoice', 'error');
}

async function submitInvoice(id) {
  const btn = document.getElementById('saveInvBtn');
  setBtnLoading(btn, true);
  const body = {
    invoice_number: document.getElementById('invNum').value.trim(),
    vendor_id: document.getElementById('invVendor').value.trim(),
    amount: parseFloat(document.getElementById('invAmount').value) || 0,
    due_date: document.getElementById('invDue').value || null,
    notes: document.getElementById('invNotes').value.trim(),
    tenant_id: _tenantId,
  };
  if (!body.vendor_id) { toast('Vendor ID required', 'error'); setBtnLoading(btn, false); return; }
  const res = id
    ? await apiFetch(`/erp/invoices/${id}`, { method:'PATCH', body:JSON.stringify(body) })
    : await apiFetch('/erp/invoices', { method:'POST', body:JSON.stringify(body) });
  setBtnLoading(btn, false);
  if (res.ok) { closeModal(); toast('Invoice saved', 'success'); loadInvoices(); }
  else toast('Save failed: ' + res.error, 'error');
}

async function markInvoicePaid(id) {
  const res = await apiFetch(`/erp/invoices/${id}`, { method:'PATCH', body:JSON.stringify({ status:'paid' }) });
  if (res.ok) { toast('Invoice marked as paid', 'success'); loadInvoices(); }
  else toast('Failed: ' + res.error, 'error');
}

async function loadInventory() {
  const lowOnly = document.getElementById('lowStockOnly')?.checked || false;
  const q = document.getElementById('invSearch')?.value || '';
  let path = `/erp/inventory?tenant_id=${_tenantId}&limit=100`;
  if (lowOnly) path += '&low_stock=true';
  if (q) path += `&q=${encodeURIComponent(q)}`;
  const res = await apiFetch(path);
  const rows = res.ok ? (res.data.inventory || res.data || []) : [];
  const tbody = document.getElementById('inventoryTbody');
  if (!tbody) return;
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="8"><div class="empty-state"><h3>No inventory items</h3></div></td></tr>`;
    return;
  }
  tbody.innerHTML = rows.map(item => {
    const isLow = item.quantity <= (item.reorder_point || 0);
    return `
    <tr${isLow ? ' style="background:rgba(245,158,11,.06);"' : ''}>
      <td style="font-family:monospace;font-size:11px;">${esc(item.sku||'—')}</td>
      <td><strong>${esc(item.name)}</strong></td>
      <td>${esc(item.warehouse_name||item.warehouse_id||'—')}</td>
      <td style="${isLow?'color:var(--danger);font-weight:700;':''}">${item.quantity ?? '—'}</td>
      <td>${item.reserved ?? 0}</td>
      <td>${item.reorder_point ?? '—'}</td>
      <td>${isLow ? '<span class="badge badge-failed">Low Stock</span>' : '<span class="badge badge-active">OK</span>'}</td>
      <td>
        <button class="btn btn-xs btn-secondary" onclick="editInventoryModal('${esc(item.id)}')">Edit</button>
        <button class="btn btn-xs btn-secondary" onclick="adjustStockModal('${esc(item.id)}','${esc(item.name)}',${item.quantity||0})">Adjust</button>
      </td>
    </tr>`;
  }).join('');
}

function createInventoryModal(item = {}) {
  const edit = !!item.id;
  showModal(`
    <div class="modal-header"><h3 class="modal-title">${edit ? 'Edit' : 'Add'} Inventory Item</h3><button class="modal-close" onclick="closeModal()">×</button></div>
    <div class="two-col" style="gap:12px;">
      <div class="form-group"><label>SKU</label><input id="invISku" value="${esc(item.sku||'')}" placeholder="SKU-001" /></div>
      <div class="form-group"><label>Item Name *</label><input id="invIName" value="${esc(item.name||'')}" /></div>
    </div>
    <div class="two-col" style="gap:12px;">
      <div class="form-group"><label>Warehouse ID</label><input id="invIWarehouse" value="${esc(item.warehouse_id||'')}" /></div>
      <div class="form-group"><label>Quantity</label><input id="invIQty" type="number" value="${esc(item.quantity||0)}" /></div>
    </div>
    <div class="two-col" style="gap:12px;">
      <div class="form-group"><label>Reorder Point</label><input id="invIReorder" type="number" value="${esc(item.reorder_point||0)}" /></div>
      <div class="form-group"><label>Unit Cost</label><input id="invICost" type="number" step="0.01" value="${esc(item.unit_cost||'')}" /></div>
    </div>
    <div class="modal-footer">
      <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
      <button class="btn btn-primary" id="saveInvIBtn" onclick="submitInventoryItem('${esc(item.id||'')}')">Save Item</button>
    </div>
  `);
}

async function editInventoryModal(id) {
  const res = await apiFetch(`/erp/inventory/${id}`);
  if (res.ok) createInventoryModal(res.data);
  else toast('Failed to load item', 'error');
}

async function submitInventoryItem(id) {
  const btn = document.getElementById('saveInvIBtn');
  setBtnLoading(btn, true);
  const body = {
    sku: document.getElementById('invISku').value.trim(),
    name: document.getElementById('invIName').value.trim(),
    warehouse_id: document.getElementById('invIWarehouse').value.trim(),
    quantity: parseInt(document.getElementById('invIQty').value) || 0,
    reorder_point: parseInt(document.getElementById('invIReorder').value) || 0,
    unit_cost: parseFloat(document.getElementById('invICost').value) || null,
    tenant_id: _tenantId,
  };
  if (!body.name) { toast('Item name required', 'error'); setBtnLoading(btn, false); return; }
  const res = id
    ? await apiFetch(`/erp/inventory/${id}`, { method:'PATCH', body:JSON.stringify(body) })
    : await apiFetch('/erp/inventory', { method:'POST', body:JSON.stringify(body) });
  setBtnLoading(btn, false);
  if (res.ok) { closeModal(); toast('Item saved', 'success'); loadInventory(); }
  else toast('Save failed: ' + res.error, 'error');
}

function adjustStockModal(id, name, current) {
  showModal(`
    <div class="modal-header"><h3 class="modal-title">Adjust Stock: ${esc(name)}</h3><button class="modal-close" onclick="closeModal()">×</button></div>
    <p style="color:var(--text-muted);font-size:13px;margin-bottom:12px;">Current quantity: <strong>${current}</strong></p>
    <div class="form-group"><label>Adjustment (+ or -)</label><input id="adjQty" type="number" placeholder="+50 or -10" /></div>
    <div class="form-group"><label>Reason</label><input id="adjReason" placeholder="Stock receipt, correction…" /></div>
    <div class="modal-footer">
      <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
      <button class="btn btn-primary" onclick="submitStockAdjust('${esc(id)}',${current})">Apply Adjustment</button>
    </div>
  `);
}

async function submitStockAdjust(id, current) {
  const adj = parseInt(document.getElementById('adjQty').value);
  if (isNaN(adj)) { toast('Enter a valid adjustment', 'error'); return; }
  const newQty = Math.max(0, current + adj);
  const res = await apiFetch(`/erp/inventory/${id}`, { method:'PATCH', body:JSON.stringify({ quantity: newQty }) });
  if (res.ok) { closeModal(); toast(`Stock updated to ${newQty}`, 'success'); loadInventory(); }
  else toast('Failed: ' + res.error, 'error');
}

async function loadWarehouses() {
  const res = await apiFetch(`/erp/warehouses?tenant_id=${_tenantId}`);
  const rows = res.ok ? (res.data.warehouses || res.data || []) : [];
  const grid = document.getElementById('warehouseGrid');
  if (!grid) return;
  if (!rows.length) {
    grid.innerHTML = '<div class="empty-state" style="grid-column:1/-1"><h3>No warehouses configured</h3><p>Add a warehouse to start tracking inventory</p></div>';
    return;
  }
  grid.innerHTML = rows.map(w => `
    <div class="health-card">
      <div class="health-card-header">
        ${dot(w.status||'active')}
        <span class="health-name">${esc(w.name)}</span>
        <span style="margin-left:auto;font-size:11px;color:var(--text-muted);">${esc(w.code||'')}</span>
      </div>
      <div class="health-meta">
        <span class="health-key">Location</span><span class="health-val">${esc(w.city||'—')}${w.country?', '+esc(w.country):''}</span>
        <span class="health-key">Capacity</span><span class="health-val">${w.capacity ? esc(Number(w.capacity).toLocaleString())+' units' : '—'}</span>
        <span class="health-key">Manager</span><span class="health-val">${esc(w.manager_name||'—')}</span>
      </div>
      <div style="margin-top:8px;display:flex;gap:6px;">
        <button class="btn btn-xs btn-secondary" onclick="editWarehouseModal('${esc(w.id)}')">Edit</button>
      </div>
    </div>`).join('');
}

function createWarehouseModal(wh = {}) {
  const edit = !!wh.id;
  showModal(`
    <div class="modal-header"><h3 class="modal-title">${edit ? 'Edit' : 'Add'} Warehouse</h3><button class="modal-close" onclick="closeModal()">×</button></div>
    <div class="two-col" style="gap:12px;">
      <div class="form-group"><label>Name *</label><input id="whName" value="${esc(wh.name||'')}" placeholder="Main Warehouse" /></div>
      <div class="form-group"><label>Code</label><input id="whCode" value="${esc(wh.code||'')}" placeholder="WH-001" /></div>
    </div>
    <div class="two-col" style="gap:12px;">
      <div class="form-group"><label>City</label><input id="whCity" value="${esc(wh.city||'')}" /></div>
      <div class="form-group"><label>Country</label><input id="whCountry" value="${esc(wh.country||'')}" /></div>
    </div>
    <div class="two-col" style="gap:12px;">
      <div class="form-group"><label>Capacity (units)</label><input id="whCap" type="number" value="${esc(wh.capacity||'')}" /></div>
      <div class="form-group"><label>Manager Name</label><input id="whMgr" value="${esc(wh.manager_name||'')}" /></div>
    </div>
    <div class="modal-footer">
      <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
      <button class="btn btn-primary" id="saveWhBtn" onclick="submitWarehouse('${esc(wh.id||'')}')">Save Warehouse</button>
    </div>
  `);
}

async function editWarehouseModal(id) {
  const res = await apiFetch(`/erp/warehouses/${id}`);
  if (res.ok) createWarehouseModal(res.data);
  else toast('Failed to load warehouse', 'error');
}

async function submitWarehouse(id) {
  const btn = document.getElementById('saveWhBtn');
  setBtnLoading(btn, true);
  const body = {
    name: document.getElementById('whName').value.trim(),
    code: document.getElementById('whCode').value.trim(),
    city: document.getElementById('whCity').value.trim(),
    country: document.getElementById('whCountry').value.trim(),
    capacity: parseInt(document.getElementById('whCap').value) || null,
    manager_name: document.getElementById('whMgr').value.trim(),
    tenant_id: _tenantId,
  };
  if (!body.name) { toast('Warehouse name required', 'error'); setBtnLoading(btn, false); return; }
  const res = id
    ? await apiFetch(`/erp/warehouses/${id}`, { method:'PATCH', body:JSON.stringify(body) })
    : await apiFetch('/erp/warehouses', { method:'POST', body:JSON.stringify(body) });
  setBtnLoading(btn, false);
  if (res.ok) { closeModal(); toast('Warehouse saved', 'success'); loadWarehouses(); }
  else toast('Save failed: ' + res.error, 'error');
}

// ── CRM ───────────────────────────────────────────────────────────────────────

async function loadCRM() {
  const res = await apiFetch(`/crm/summary?tenant_id=${_tenantId}`);
  if (!res.ok) return;
  const d = res.data;
  _setEl('crmContacts', d.total_contacts ?? '—');
  _setEl('crmLeads', d.open_leads ?? '—');
  _setEl('crmOpps', d.total_opportunities ?? '—');
  _setEl('crmPipeline', d.pipeline_value ? '$'+Number(d.pipeline_value).toLocaleString() : '—');
  _setEl('crmWon', d.won_revenue ? '$'+Number(d.won_revenue).toLocaleString() : '—');

  const pipeRes = await apiFetch(`/crm/pipeline?tenant_id=${_tenantId}`);
  const stages = pipeRes.ok ? (pipeRes.data.stages || pipeRes.data || []) : [];
  const el = document.getElementById('crmPipelineSummary');
  if (el) {
    el.innerHTML = stages.length
      ? stages.map(s => `
        <div style="display:flex;align-items:center;gap:8px;padding:8px 0;border-bottom:1px solid var(--border);">
          <span style="font-size:12px;font-weight:600;min-width:110px;">${esc(s.stage)}</span>
          <span style="font-size:11px;color:var(--text-muted);">${s.count} deal${s.count!==1?'s':''}</span>
          <span style="margin-left:auto;font-size:12px;color:var(--accent);">${s.value ? '$'+Number(s.value).toLocaleString() : '—'}</span>
        </div>`).join('')
      : '<div style="padding:16px;color:var(--text-muted);text-align:center;">No pipeline data</div>';
  }
}

const PIPELINE_STAGES = ['prospecting','qualification','proposal','negotiation','closed_won','closed_lost'];
const STAGE_COLORS = {
  prospecting:'#64748B', qualification:'#2563EB', proposal:'#7C3AED',
  negotiation:'#D97706', closed_won:'#16A34A', closed_lost:'#DC2626',
};

async function loadPipeline() {
  const res = await apiFetch(`/crm/pipeline?tenant_id=${_tenantId}`);
  const board = document.getElementById('pipelineBoard');
  if (!board) return;
  const stagesData = res.ok ? (res.data.stages || []) : [];
  const stageMap = {};
  stagesData.forEach(s => { stageMap[s.stage] = s.opportunities || []; });

  board.innerHTML = PIPELINE_STAGES.map(stage => {
    const items = stageMap[stage] || [];
    const color = STAGE_COLORS[stage] || '#64748B';
    const total = items.reduce((s, o) => s + (o.value || 0), 0);
    return `
    <div style="min-width:220px;flex:1;background:var(--bg);border:1px solid var(--border);border-radius:10px;padding:12px;display:flex;flex-direction:column;gap:8px;">
      <div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;">
        <span style="width:8px;height:8px;border-radius:50%;background:${color};flex-shrink:0;"></span>
        <span style="font-size:12px;font-weight:700;text-transform:capitalize;">${esc(stage.replace('_',' '))}</span>
        <span style="margin-left:auto;font-size:11px;color:var(--text-muted);">${items.length}</span>
      </div>
      <div style="font-size:11px;color:var(--text-muted);margin-bottom:4px;">
        ${total ? '$'+total.toLocaleString() : '—'}
      </div>
      ${items.map(o => `
        <div style="background:var(--panel);border:1px solid var(--border);border-radius:7px;padding:10px;cursor:pointer;" onclick="editOpportunityModal('${esc(o.id)}')">
          <div style="font-size:12px;font-weight:600;margin-bottom:4px;">${esc(o.title)}</div>
          <div style="font-size:11px;color:var(--text-muted);">${esc(o.contact_name||'—')}</div>
          <div style="display:flex;align-items:center;margin-top:6px;">
            <span style="font-size:12px;color:${color};font-weight:600;">${o.value ? '$'+Number(o.value).toLocaleString() : '—'}</span>
            <span style="margin-left:auto;font-size:10px;color:var(--text-muted);">${o.probability != null ? esc(o.probability)+'%' : ''}</span>
          </div>
        </div>`).join('')}
    </div>`;
  }).join('');
}

async function loadLeads() {
  const status = document.getElementById('leadStatusFilter')?.value || '';
  let path = `/crm/leads?tenant_id=${_tenantId}&limit=100`;
  if (status) path += `&status=${status}`;
  const res = await apiFetch(path);
  const rows = res.ok ? (res.data.leads || res.data || []) : [];
  const tbody = document.getElementById('leadsTbody');
  if (!tbody) return;
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="8"><div class="empty-state"><h3>No leads found</h3></div></td></tr>`;
    return;
  }
  tbody.innerHTML = rows.map(l => `
    <tr>
      <td><strong>${esc(l.title)}</strong></td>
      <td>${esc(l.contact_name||'—')}</td>
      <td>${esc(l.source||'—')}</td>
      <td>${statusBadge(l.status||'new')}</td>
      <td>${l.score != null ? `<span style="font-weight:600;color:${l.score>=70?'var(--success)':l.score>=40?'var(--warning)':'var(--danger)'}">${l.score}</span>` : '—'}</td>
      <td>${esc(l.assigned_to||'—')}</td>
      <td>${timeAgo(l.created_at)}</td>
      <td>
        <button class="btn btn-xs btn-secondary" onclick="editLeadModal('${esc(l.id)}')">Edit</button>
        <button class="btn btn-xs btn-primary" onclick="convertLead('${esc(l.id)}')">Convert</button>
      </td>
    </tr>`).join('');
}

function createLeadModal(lead = {}) {
  const edit = !!lead.id;
  showModal(`
    <div class="modal-header"><h3 class="modal-title">${edit ? 'Edit' : 'New'} Lead</h3><button class="modal-close" onclick="closeModal()">×</button></div>
    <div class="form-group"><label>Title *</label><input id="ldTitle" value="${esc(lead.title||'')}" placeholder="Lead from website" /></div>
    <div class="two-col" style="gap:12px;">
      <div class="form-group"><label>Contact Name</label><input id="ldContact" value="${esc(lead.contact_name||'')}" /></div>
      <div class="form-group"><label>Email</label><input id="ldEmail" type="email" value="${esc(lead.email||'')}" /></div>
    </div>
    <div class="two-col" style="gap:12px;">
      <div class="form-group"><label>Source</label>
        <select id="ldSource">
          ${['website','email','phone','referral','social','other'].map(s=>`<option ${lead.source===s?'selected':''}>${s}</option>`).join('')}
        </select>
      </div>
      <div class="form-group"><label>Score (0-100)</label><input id="ldScore" type="number" min="0" max="100" value="${esc(lead.score??50)}" /></div>
    </div>
    <div class="form-group"><label>Assigned To</label><input id="ldAssigned" value="${esc(lead.assigned_to||'')}" /></div>
    <div class="modal-footer">
      <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
      <button class="btn btn-primary" id="saveLdBtn" onclick="submitLead('${esc(lead.id||'')}')">Save Lead</button>
    </div>
  `);
}

async function editLeadModal(id) {
  const res = await apiFetch(`/crm/leads/${id}`);
  if (res.ok) createLeadModal(res.data);
  else toast('Failed to load lead', 'error');
}

async function submitLead(id) {
  const btn = document.getElementById('saveLdBtn');
  setBtnLoading(btn, true);
  const body = {
    title: document.getElementById('ldTitle').value.trim(),
    contact_name: document.getElementById('ldContact').value.trim(),
    email: document.getElementById('ldEmail').value.trim(),
    source: document.getElementById('ldSource').value,
    score: parseInt(document.getElementById('ldScore').value) || 50,
    assigned_to: document.getElementById('ldAssigned').value.trim(),
    tenant_id: _tenantId,
  };
  if (!body.title) { toast('Title required', 'error'); setBtnLoading(btn, false); return; }
  const res = id
    ? await apiFetch(`/crm/leads/${id}`, { method:'PATCH', body:JSON.stringify(body) })
    : await apiFetch('/crm/leads', { method:'POST', body:JSON.stringify(body) });
  setBtnLoading(btn, false);
  if (res.ok) { closeModal(); toast('Lead saved', 'success'); loadLeads(); }
  else toast('Save failed: ' + res.error, 'error');
}

async function convertLead(id) {
  confirm('Convert this lead to an opportunity?', async () => {
    const res = await apiFetch(`/crm/leads/${id}`, { method:'PATCH', body:JSON.stringify({ status:'qualified' }) });
    if (res.ok) { toast('Lead converted', 'success'); loadLeads(); }
    else toast('Conversion failed: ' + res.error, 'error');
  });
}

async function loadContacts() {
  const q = document.getElementById('contactSearch')?.value || '';
  let path = `/crm/contacts?tenant_id=${_tenantId}&limit=100`;
  if (q) path += `&q=${encodeURIComponent(q)}`;
  const res = await apiFetch(path);
  const rows = res.ok ? (res.data.contacts || res.data || []) : [];
  const tbody = document.getElementById('contactsTbody');
  if (!tbody) return;
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="7"><div class="empty-state"><h3>No contacts found</h3></div></td></tr>`;
    return;
  }
  tbody.innerHTML = rows.map(c => `
    <tr>
      <td><strong>${esc(c.first_name+' '+(c.last_name||''))}</strong></td>
      <td><a href="mailto:${esc(c.email||'')}" style="color:var(--accent);">${esc(c.email||'—')}</a></td>
      <td>${esc(c.company||'—')}</td>
      <td>${esc(c.job_title||'—')}</td>
      <td>${c.score != null ? `<span style="font-weight:600;color:${c.score>=70?'var(--success)':c.score>=40?'var(--warning)':'var(--danger)'}">${c.score}</span>` : '—'}</td>
      <td>${statusBadge(c.status||'active')}</td>
      <td>
        <button class="btn btn-xs btn-secondary" onclick="editContactModal('${esc(c.id)}')">Edit</button>
        <button class="btn btn-xs" style="color:var(--danger);border:1px solid rgba(220,38,38,.2);" onclick="deleteContact('${esc(c.id)}','${esc(c.first_name+' '+(c.last_name||''))}')">Remove</button>
      </td>
    </tr>`).join('');
}

function createContactModal(c = {}) {
  const edit = !!c.id;
  showModal(`
    <div class="modal-header"><h3 class="modal-title">${edit ? 'Edit' : 'New'} Contact</h3><button class="modal-close" onclick="closeModal()">×</button></div>
    <div class="two-col" style="gap:12px;">
      <div class="form-group"><label>First Name *</label><input id="ctFirst" value="${esc(c.first_name||'')}" /></div>
      <div class="form-group"><label>Last Name</label><input id="ctLast" value="${esc(c.last_name||'')}" /></div>
    </div>
    <div class="two-col" style="gap:12px;">
      <div class="form-group"><label>Email</label><input id="ctEmail" type="email" value="${esc(c.email||'')}" /></div>
      <div class="form-group"><label>Phone</label><input id="ctPhone" value="${esc(c.phone||'')}" /></div>
    </div>
    <div class="two-col" style="gap:12px;">
      <div class="form-group"><label>Company</label><input id="ctCompany" value="${esc(c.company||'')}" /></div>
      <div class="form-group"><label>Job Title</label><input id="ctTitle" value="${esc(c.job_title||'')}" /></div>
    </div>
    <div class="modal-footer">
      <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
      <button class="btn btn-primary" id="saveCtBtn" onclick="submitContact('${esc(c.id||'')}')">Save Contact</button>
    </div>
  `);
}

async function editContactModal(id) {
  const res = await apiFetch(`/crm/contacts/${id}`);
  if (res.ok) createContactModal(res.data);
  else toast('Failed to load contact', 'error');
}

async function submitContact(id) {
  const btn = document.getElementById('saveCtBtn');
  setBtnLoading(btn, true);
  const body = {
    first_name: document.getElementById('ctFirst').value.trim(),
    last_name: document.getElementById('ctLast').value.trim(),
    email: document.getElementById('ctEmail').value.trim(),
    phone: document.getElementById('ctPhone').value.trim(),
    company: document.getElementById('ctCompany').value.trim(),
    job_title: document.getElementById('ctTitle').value.trim(),
    tenant_id: _tenantId,
  };
  if (!body.first_name) { toast('First name required', 'error'); setBtnLoading(btn, false); return; }
  const res = id
    ? await apiFetch(`/crm/contacts/${id}`, { method:'PATCH', body:JSON.stringify(body) })
    : await apiFetch('/crm/contacts', { method:'POST', body:JSON.stringify(body) });
  setBtnLoading(btn, false);
  if (res.ok) { closeModal(); toast('Contact saved', 'success'); loadContacts(); }
  else toast('Save failed: ' + res.error, 'error');
}

async function deleteContact(id, name) {
  confirm(`Remove contact "${name}"?`, async () => {
    const res = await apiFetch(`/crm/contacts/${id}`, { method:'DELETE' });
    if (res.ok) { toast('Contact removed', 'success'); loadContacts(); }
    else toast('Delete failed: ' + res.error, 'error');
  });
}

async function loadOpportunities() {
  const stage = document.getElementById('oppStageFilter')?.value || '';
  let path = `/crm/opportunities?tenant_id=${_tenantId}&limit=100`;
  if (stage) path += `&stage=${stage}`;
  const res = await apiFetch(path);
  const rows = res.ok ? (res.data.opportunities || res.data || []) : [];
  const tbody = document.getElementById('opportunitiesTbody');
  if (!tbody) return;
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="7"><div class="empty-state"><h3>No opportunities found</h3></div></td></tr>`;
    return;
  }
  tbody.innerHTML = rows.map(o => {
    const color = STAGE_COLORS[o.stage] || '#64748B';
    return `
    <tr>
      <td><strong>${esc(o.title)}</strong></td>
      <td>${esc(o.contact_name||'—')}</td>
      <td><span class="badge" style="background:${color}20;color:${color};">${esc(o.stage||'—')}</span></td>
      <td style="font-weight:600;">${o.value ? '$'+Number(o.value).toLocaleString() : '—'}</td>
      <td>${o.probability != null ? o.probability+'%' : '—'}</td>
      <td>${esc(formatDate(o.close_date))}</td>
      <td>
        <button class="btn btn-xs btn-secondary" onclick="editOpportunityModal('${esc(o.id)}')">Edit</button>
        <button class="btn btn-xs" style="color:var(--danger);border:1px solid rgba(220,38,38,.2);" onclick="deleteOpportunity('${esc(o.id)}','${esc(o.title)}')">Remove</button>
      </td>
    </tr>`;
  }).join('');
}

function createOpportunityModal(opp = {}) {
  const edit = !!opp.id;
  showModal(`
    <div class="modal-header"><h3 class="modal-title">${edit ? 'Edit' : 'New'} Opportunity</h3><button class="modal-close" onclick="closeModal()">×</button></div>
    <div class="form-group"><label>Title *</label><input id="opTitle" value="${esc(opp.title||'')}" placeholder="Enterprise Deal — Acme Corp" /></div>
    <div class="two-col" style="gap:12px;">
      <div class="form-group"><label>Stage</label>
        <select id="opStage">
          ${PIPELINE_STAGES.map(s=>`<option ${opp.stage===s?'selected':''}>${s}</option>`).join('')}
        </select>
      </div>
      <div class="form-group"><label>Value ($)</label><input id="opValue" type="number" step="0.01" value="${esc(opp.value||'')}" /></div>
    </div>
    <div class="two-col" style="gap:12px;">
      <div class="form-group"><label>Probability (%)</label><input id="opProb" type="number" min="0" max="100" value="${esc(opp.probability??50)}" /></div>
      <div class="form-group"><label>Close Date</label><input id="opClose" type="date" value="${esc((opp.close_date||'').slice(0,10))}" /></div>
    </div>
    <div class="form-group"><label>Contact Name</label><input id="opContact" value="${esc(opp.contact_name||'')}" /></div>
    <div class="modal-footer">
      <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
      <button class="btn btn-primary" id="saveOpBtn" onclick="submitOpportunity('${esc(opp.id||'')}')">Save Deal</button>
    </div>
  `);
}

async function editOpportunityModal(id) {
  const res = await apiFetch(`/crm/opportunities/${id}`);
  if (res.ok) createOpportunityModal(res.data);
  else toast('Failed to load opportunity', 'error');
}

async function submitOpportunity(id) {
  const btn = document.getElementById('saveOpBtn');
  setBtnLoading(btn, true);
  const body = {
    title: document.getElementById('opTitle').value.trim(),
    stage: document.getElementById('opStage').value,
    value: parseFloat(document.getElementById('opValue').value) || null,
    probability: parseInt(document.getElementById('opProb').value) || 50,
    close_date: document.getElementById('opClose').value || null,
    contact_name: document.getElementById('opContact').value.trim(),
    tenant_id: _tenantId,
  };
  if (!body.title) { toast('Title required', 'error'); setBtnLoading(btn, false); return; }
  const res = id
    ? await apiFetch(`/crm/opportunities/${id}`, { method:'PATCH', body:JSON.stringify(body) })
    : await apiFetch('/crm/opportunities', { method:'POST', body:JSON.stringify(body) });
  setBtnLoading(btn, false);
  if (res.ok) { closeModal(); toast('Deal saved', 'success'); loadOpportunities(); }
  else toast('Save failed: ' + res.error, 'error');
}

async function deleteOpportunity(id, title) {
  confirm(`Remove deal "${title}"?`, async () => {
    const res = await apiFetch(`/crm/opportunities/${id}`, { method:'DELETE' });
    if (res.ok) { toast('Deal removed', 'success'); loadOpportunities(); }
    else toast('Delete failed: ' + res.error, 'error');
  });
}

// ── TRACKING ──────────────────────────────────────────────────────────────────

const RISK_BADGE = { low:'badge-active', medium:'badge-installing', high:'badge-failed' };

async function loadTracking() {
  const q = document.getElementById('trackingSearch')?.value || '';
  const carrier = document.getElementById('trackingCarrierFilter')?.value || '';
  const status = document.getElementById('trackingStatusFilter')?.value || '';
  let path = `/tracking?tenant_id=${_tenantId}&limit=100`;
  if (q) path += `&q=${encodeURIComponent(q)}`;
  if (carrier) path += `&carrier=${carrier}`;
  if (status) path += `&status=${status}`;

  const [res, statsRes] = await Promise.all([
    apiFetch(path),
    apiFetch(`/tracking/stats?tenant_id=${_tenantId}`),
  ]);

  if (statsRes.ok) {
    const s = statsRes.data;
    _setEl('trkTotal', s.total ?? '—');
    _setEl('trkInTransit', s.in_transit ?? '—');
    _setEl('trkDelivered', s.delivered ?? '—');
    _setEl('trkExceptions', s.exceptions ?? '—');
    _setEl('trkHighRisk', s.high_risk ?? '—');

    const badge = document.getElementById('trackingBadge');
    if (badge && s.exceptions > 0) { badge.textContent = s.exceptions; badge.style.display = ''; }
  }

  const rows = res.ok ? (res.data.shipments || res.data || []) : [];
  const tbody = document.getElementById('trackingTbody');
  if (!tbody) return;
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="8"><div class="empty-state"><h3>No shipments found</h3><p>Add a shipment to start tracking</p></div></td></tr>`;
    return;
  }
  tbody.innerHTML = rows.map(s => `
    <tr>
      <td><strong style="font-family:monospace;font-size:11px;">${esc(s.tracking_number)}</strong></td>
      <td>${esc(s.carrier||'—')}</td>
      <td><span class="badge badge-info">${esc(s.tracking_type||'awb')}</span></td>
      <td>${statusBadge(s.status||'pending')}</td>
      <td style="font-size:12px;">${esc(s.origin||'—')} → ${esc(s.destination||'—')}</td>
      <td style="font-size:12px;">${esc(formatDate(s.estimated_delivery))}</td>
      <td><span class="badge ${RISK_BADGE[s.ai_delay_risk]||'badge-inactive'}">${esc(s.ai_delay_risk||'low')}</span></td>
      <td>
        <button class="btn btn-xs btn-secondary" onclick="viewShipmentModal('${esc(s.id)}')">Details</button>
        <button class="btn btn-xs btn-secondary" onclick="addTrackingEventModal('${esc(s.id)}')">Update</button>
      </td>
    </tr>`).join('');
}

function addShipmentModal() {
  showModal(`
    <div class="modal-header"><h3 class="modal-title">Add Shipment</h3><button class="modal-close" onclick="closeModal()">×</button></div>
    <div class="two-col" style="gap:12px;">
      <div class="form-group"><label>Tracking Number *</label><input id="shTrack" placeholder="AWB / BL / Container" /></div>
      <div class="form-group"><label>Carrier</label>
        <select id="shCarrier">
          <option value="fedex">FedEx</option><option value="ups">UPS</option>
          <option value="dhl">DHL</option><option value="delhivery">Delhivery</option>
          <option value="shiprocket">Shiprocket</option><option value="aftership">AfterShip</option>
          <option value="maersk">Maersk</option><option value="msc">MSC</option><option value="other">Other</option>
        </select>
      </div>
    </div>
    <div class="two-col" style="gap:12px;">
      <div class="form-group"><label>Tracking Type</label>
        <select id="shType">
          <option value="awb">AWB (Air)</option><option value="bl">BL (Sea)</option>
          <option value="container">Container</option><option value="order">Order</option>
        </select>
      </div>
      <div class="form-group"><label>Reference</label><input id="shRef" placeholder="Order / PO ref" /></div>
    </div>
    <div class="two-col" style="gap:12px;">
      <div class="form-group"><label>Origin</label><input id="shOrigin" placeholder="Mumbai, IN" /></div>
      <div class="form-group"><label>Destination</label><input id="shDest" placeholder="London, GB" /></div>
    </div>
    <div class="two-col" style="gap:12px;">
      <div class="form-group"><label>Ship Date</label><input id="shDate" type="date" /></div>
      <div class="form-group"><label>Est. Delivery</label><input id="shETA" type="date" /></div>
    </div>
    <div class="modal-footer">
      <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
      <button class="btn btn-primary" id="saveShBtn" onclick="submitShipment()">Add Shipment</button>
    </div>
  `);
}

async function submitShipment() {
  const btn = document.getElementById('saveShBtn');
  setBtnLoading(btn, true);
  const body = {
    tracking_number: document.getElementById('shTrack').value.trim(),
    carrier: document.getElementById('shCarrier').value,
    tracking_type: document.getElementById('shType').value,
    reference: document.getElementById('shRef').value.trim(),
    origin: document.getElementById('shOrigin').value.trim(),
    destination: document.getElementById('shDest').value.trim(),
    ship_date: document.getElementById('shDate').value || null,
    estimated_delivery: document.getElementById('shETA').value || null,
    tenant_id: _tenantId,
  };
  if (!body.tracking_number) { toast('Tracking number required', 'error'); setBtnLoading(btn, false); return; }
  const res = await apiFetch('/tracking', { method:'POST', body:JSON.stringify(body) });
  setBtnLoading(btn, false);
  if (res.ok) { closeModal(); toast('Shipment added', 'success'); loadTracking(); }
  else toast('Failed: ' + res.error, 'error');
}

async function viewShipmentModal(id) {
  const res = await apiFetch(`/tracking/${id}`);
  if (!res.ok) { toast('Failed to load shipment', 'error'); return; }
  const s = res.data;
  const events = s.events || [];
  showModal(`
    <div class="modal-header">
      <h3 class="modal-title">${esc(s.tracking_number)}</h3>
      <button class="modal-close" onclick="closeModal()">×</button>
    </div>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px;">
      ${statusBadge(s.status)} <span class="badge badge-info">${esc(s.carrier)}</span>
      <span class="badge ${RISK_BADGE[s.ai_delay_risk]||'badge-inactive'}">Risk: ${esc(s.ai_delay_risk||'low')}</span>
    </div>
    <div class="two-col" style="gap:8px;font-size:12px;margin-bottom:12px;">
      <div><span style="color:var(--text-muted);">Origin</span><div>${esc(s.origin||'—')}</div></div>
      <div><span style="color:var(--text-muted);">Destination</span><div>${esc(s.destination||'—')}</div></div>
      <div><span style="color:var(--text-muted);">Est. Delivery</span><div>${esc(formatDate(s.estimated_delivery))}</div></div>
      <div><span style="color:var(--text-muted);">Reference</span><div>${esc(s.reference||'—')}</div></div>
    </div>
    <div style="font-size:12px;font-weight:600;margin-bottom:8px;">Tracking Events</div>
    <div style="max-height:220px;overflow-y:auto;">
      ${events.length ? events.map(e => `
        <div style="display:flex;gap:10px;padding:8px 0;border-bottom:1px solid var(--border);">
          <div style="font-size:11px;color:var(--text-muted);min-width:130px;">${esc(formatDate(e.event_time))}</div>
          <div>
            <div style="font-size:12px;">${esc(e.description)}</div>
            <div style="font-size:11px;color:var(--text-muted);">${esc(e.location||'')}</div>
          </div>
        </div>`).join('')
      : '<div style="padding:12px;color:var(--text-muted);text-align:center;">No events yet</div>'}
    </div>
    <div class="modal-footer">
      <button class="btn btn-secondary" onclick="closeModal()">Close</button>
      <button class="btn btn-primary" onclick="closeModal();addTrackingEventModal('${esc(s.id)}')">Add Event</button>
    </div>
  `);
}

function addTrackingEventModal(shipmentId) {
  showModal(`
    <div class="modal-header"><h3 class="modal-title">Add Tracking Event</h3><button class="modal-close" onclick="closeModal()">×</button></div>
    <div class="form-group"><label>Status *</label>
      <select id="tevStatus">
        <option value="pending">Pending</option><option value="in_transit">In Transit</option>
        <option value="out_for_delivery">Out for Delivery</option><option value="delivered">Delivered</option>
        <option value="exception">Exception</option><option value="returned">Returned</option>
      </select>
    </div>
    <div class="form-group"><label>Description *</label><input id="tevDesc" placeholder="Shipment departed origin facility" /></div>
    <div class="form-group"><label>Location</label><input id="tevLoc" placeholder="Mumbai, IN" /></div>
    <div class="modal-footer">
      <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
      <button class="btn btn-primary" id="saveTevBtn" onclick="submitTrackingEvent('${esc(shipmentId)}')">Add Event</button>
    </div>
  `);
}

async function submitTrackingEvent(shipmentId) {
  const btn = document.getElementById('saveTevBtn');
  setBtnLoading(btn, true);
  const body = {
    status: document.getElementById('tevStatus').value,
    description: document.getElementById('tevDesc').value.trim(),
    location: document.getElementById('tevLoc').value.trim(),
  };
  if (!body.description) { toast('Description required', 'error'); setBtnLoading(btn, false); return; }
  const res = await apiFetch(`/tracking/${shipmentId}/events`, { method:'POST', body:JSON.stringify(body) });
  setBtnLoading(btn, false);
  if (res.ok) { closeModal(); toast('Event added', 'success'); loadTracking(); }
  else toast('Failed: ' + res.error, 'error');
}

// ── WORKFLOWS ─────────────────────────────────────────────────────────────────

async function loadWorkflows() {
  const status = document.getElementById('wfStatusFilter')?.value || '';
  let path = `/workflows?tenant_id=${_tenantId}&limit=100`;
  if (status) path += `&status=${status}`;

  const [res, summRes] = await Promise.all([
    apiFetch(path),
    apiFetch(`/workflows/summary?tenant_id=${_tenantId}`),
  ]);

  if (summRes.ok) {
    const s = summRes.data;
    _setEl('wfTotal', s.total ?? '—');
    _setEl('wfActive', s.active ?? '—');
    _setEl('wfExecutions', s.total_executions ?? '—');
    _setEl('wfFailed', s.failed_executions ?? '—');
  }

  const rows = res.ok ? (res.data.workflows || res.data || []) : [];
  const tbody = document.getElementById('workflowsTbody');
  if (!tbody) return;
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="6"><div class="empty-state"><h3>No workflows</h3><p>Create your first workflow to automate operations</p></div></td></tr>`;
    return;
  }
  tbody.innerHTML = rows.map(w => `
    <tr>
      <td>
        <strong>${esc(w.name)}</strong>
        <div style="font-size:11px;color:var(--text-muted);">${esc(w.description||'')}</div>
      </td>
      <td><span class="badge badge-info">${esc(w.trigger_type||'manual')}</span></td>
      <td>${statusBadge(w.status||'draft')}</td>
      <td>${w.run_count ?? 0}</td>
      <td>${timeAgo(w.last_run_at)}</td>
      <td>
        <button class="btn btn-xs btn-primary" onclick="runWorkflow('${esc(w.id)}','${esc(w.name)}')">Run</button>
        <button class="btn btn-xs btn-secondary" onclick="editWorkflowModal('${esc(w.id)}')">Edit</button>
        <button class="btn btn-xs btn-secondary" onclick="viewExecutions('${esc(w.id)}','${esc(w.name)}')">History</button>
        <button class="btn btn-xs" style="color:var(--danger);border:1px solid rgba(220,38,38,.2);" onclick="deleteWorkflow('${esc(w.id)}','${esc(w.name)}')">Delete</button>
      </td>
    </tr>`).join('');
}

function createWorkflowModal(wf = {}) {
  const edit = !!wf.id;
  const stepsJson = wf.steps_json || '[{"type":"action","name":"Step 1","config":{}}]';
  showModal(`
    <div class="modal-header"><h3 class="modal-title">${edit ? 'Edit' : 'New'} Workflow</h3><button class="modal-close" onclick="closeModal()">×</button></div>
    <div class="form-group"><label>Workflow Name *</label><input id="wfName" value="${esc(wf.name||'')}" placeholder="Invoice Auto-Process" /></div>
    <div class="form-group"><label>Description</label><input id="wfDesc" value="${esc(wf.description||'')}" placeholder="Optional description" /></div>
    <div class="two-col" style="gap:12px;">
      <div class="form-group"><label>Trigger Type</label>
        <select id="wfTrigger">
          ${['manual','event','schedule','webhook','condition'].map(t=>`<option ${wf.trigger_type===t?'selected':''}>${t}</option>`).join('')}
        </select>
      </div>
      <div class="form-group"><label>Trigger Config</label><input id="wfTriggerConf" value="${esc(wf.trigger_config||'')}" placeholder="event.type or cron expression" /></div>
    </div>
    <div class="form-group"><label>Steps (JSON)</label><textarea id="wfSteps" rows="5" style="font-family:monospace;font-size:12px;">${esc(typeof stepsJson==='string'?stepsJson:JSON.stringify(stepsJson,null,2))}</textarea></div>
    <div class="modal-footer">
      <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
      <button class="btn btn-primary" id="saveWfBtn" onclick="submitWorkflow('${esc(wf.id||'')}')">Save Workflow</button>
    </div>
  `);
}

async function editWorkflowModal(id) {
  const res = await apiFetch(`/workflows/${id}`);
  if (res.ok) createWorkflowModal(res.data);
  else toast('Failed to load workflow', 'error');
}

async function submitWorkflow(id) {
  const btn = document.getElementById('saveWfBtn');
  setBtnLoading(btn, true);
  let steps = [];
  try { steps = JSON.parse(document.getElementById('wfSteps').value || '[]'); } catch { toast('Invalid JSON in Steps', 'error'); setBtnLoading(btn, false); return; }
  const body = {
    name: document.getElementById('wfName').value.trim(),
    description: document.getElementById('wfDesc').value.trim(),
    trigger_type: document.getElementById('wfTrigger').value,
    trigger_config: document.getElementById('wfTriggerConf').value.trim(),
    steps_json: steps,
    tenant_id: _tenantId,
  };
  if (!body.name) { toast('Workflow name required', 'error'); setBtnLoading(btn, false); return; }
  const res = id
    ? await apiFetch(`/workflows/${id}`, { method:'PATCH', body:JSON.stringify(body) })
    : await apiFetch('/workflows', { method:'POST', body:JSON.stringify(body) });
  setBtnLoading(btn, false);
  if (res.ok) { closeModal(); toast('Workflow saved', 'success'); loadWorkflows(); }
  else toast('Save failed: ' + res.error, 'error');
}

async function runWorkflow(id, name) {
  const res = await apiFetch(`/workflows/${id}/run`, { method:'POST', body:'{}' });
  if (res.ok) toast(`Workflow "${name}" triggered`, 'success');
  else toast('Run failed: ' + res.error, 'error');
}

async function viewExecutions(id, name) {
  const res = await apiFetch(`/workflows/${id}/executions`);
  const execs = res.ok ? (res.data.executions || res.data || []) : [];
  showModal(`
    <div class="modal-header"><h3 class="modal-title">Executions: ${esc(name)}</h3><button class="modal-close" onclick="closeModal()">×</button></div>
    <div style="max-height:400px;overflow-y:auto;">
      ${execs.length ? `
        <table style="width:100%;border-collapse:collapse;font-size:12px;">
          <thead><tr>${['Run ID','Status','Triggered','Completed','Error'].map(h=>`<th style="text-align:left;padding:6px 8px;border-bottom:1px solid var(--border);font-size:11px;color:var(--text-muted);">${h}</th>`).join('')}</tr></thead>
          <tbody>
            ${execs.map(e=>`
              <tr>
                <td style="padding:6px 8px;font-family:monospace;font-size:11px;">${esc((e.id||'').slice(0,12))}…</td>
                <td style="padding:6px 8px;">${statusBadge(e.status)}</td>
                <td style="padding:6px 8px;">${timeAgo(e.started_at)}</td>
                <td style="padding:6px 8px;">${timeAgo(e.completed_at)}</td>
                <td style="padding:6px 8px;color:var(--danger);font-size:11px;">${esc(e.error_message||'—')}</td>
              </tr>`).join('')}
          </tbody>
        </table>`
      : '<div style="padding:24px;color:var(--text-muted);text-align:center;">No executions yet</div>'}
    </div>
    <div class="modal-footer"><button class="btn btn-secondary" onclick="closeModal()">Close</button></div>
  `);
}

async function deleteWorkflow(id, name) {
  confirm(`Delete workflow "${name}"?`, async () => {
    const res = await apiFetch(`/workflows/${id}`, { method:'DELETE' });
    if (res.ok) { toast('Workflow deleted', 'success'); loadWorkflows(); }
    else toast('Delete failed: ' + res.error, 'error');
  });
}

// ── SUPPORT TICKETS ───────────────────────────────────────────────────────────

const PRIORITY_COLORS = { urgent:'var(--danger)', high:'var(--warning)', normal:'var(--accent)', low:'var(--text-muted)' };

async function loadTickets() {
  const status = document.getElementById('sptStatusFilter')?.value || '';
  const priority = document.getElementById('sptPriorityFilter')?.value || '';
  const q = document.getElementById('sptSearch')?.value || '';
  let path = `/support/tickets?tenant_id=${_tenantId}&limit=100`;
  if (status) path += `&status=${status}`;
  if (priority) path += `&priority=${priority}`;
  if (q) path += `&q=${encodeURIComponent(q)}`;

  const [res, summRes] = await Promise.all([
    apiFetch(path),
    apiFetch(`/support/summary?tenant_id=${_tenantId}`),
  ]);

  if (summRes.ok) {
    const s = summRes.data;
    _setEl('sptTotal', s.total ?? '—');
    _setEl('sptOpen', s.open ?? '—');
    _setEl('sptUrgent', s.urgent ?? '—');
    _setEl('sptResolved', s.resolved ?? '—');

    const badge = document.getElementById('supportBadge');
    if (badge && s.open > 0) { badge.textContent = s.open; badge.style.display = ''; }
  }

  const rows = res.ok ? (res.data.tickets || res.data || []) : [];
  const tbody = document.getElementById('ticketsTbody');
  if (!tbody) return;
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="8"><div class="empty-state"><h3>No tickets found</h3></div></td></tr>`;
    return;
  }
  tbody.innerHTML = rows.map(t => {
    const pc = PRIORITY_COLORS[t.priority] || 'var(--text-muted)';
    const slaPast = t.sla_due_at && new Date(t.sla_due_at) < new Date() && t.status !== 'resolved';
    return `
    <tr${slaPast?' style="background:rgba(220,38,38,.04);"':''}>
      <td style="font-family:monospace;font-size:11px;">#${esc(t.ticket_number||(t.id||'').slice(0,8))}</td>
      <td><strong>${esc(t.subject)}</strong><div style="font-size:11px;color:var(--text-muted);">${esc(t.customer_name||'')}</div></td>
      <td><span style="font-weight:600;color:${pc};">${esc(t.priority||'normal')}</span></td>
      <td><span class="badge badge-info">${esc(t.channel||'email')}</span></td>
      <td>${statusBadge(t.status||'open')}</td>
      <td style="${slaPast?'color:var(--danger);font-weight:600;':''}">${esc(formatDate(t.sla_due_at))}</td>
      <td>${timeAgo(t.created_at)}</td>
      <td>
        <button class="btn btn-xs btn-secondary" onclick="viewTicketModal('${esc(t.id)}')">View</button>
        <button class="btn btn-xs btn-primary" onclick="replyTicketModal('${esc(t.id)}','${esc(t.subject)}')">Reply</button>
      </td>
    </tr>`;
  }).join('');
}

function createTicketModal() {
  showModal(`
    <div class="modal-header"><h3 class="modal-title">New Ticket</h3><button class="modal-close" onclick="closeModal()">×</button></div>
    <div class="form-group"><label>Subject *</label><input id="tkSubject" placeholder="Shipment not received…" /></div>
    <div class="two-col" style="gap:12px;">
      <div class="form-group"><label>Customer Name</label><input id="tkCustomer" /></div>
      <div class="form-group"><label>Customer Email</label><input id="tkEmail" type="email" /></div>
    </div>
    <div class="two-col" style="gap:12px;">
      <div class="form-group"><label>Priority</label>
        <select id="tkPriority">
          <option value="low">Low</option><option value="normal" selected>Normal</option>
          <option value="high">High</option><option value="urgent">Urgent</option>
        </select>
      </div>
      <div class="form-group"><label>Channel</label>
        <select id="tkChannel">
          <option value="email">Email</option><option value="whatsapp">WhatsApp</option>
          <option value="phone">Phone</option><option value="chat">Chat</option><option value="portal">Portal</option>
        </select>
      </div>
    </div>
    <div class="form-group"><label>Description</label><textarea id="tkDesc" rows="4" placeholder="Describe the issue…"></textarea></div>
    <div class="modal-footer">
      <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
      <button class="btn btn-primary" id="saveTkBtn" onclick="submitTicket()">Create Ticket</button>
    </div>
  `);
}

async function submitTicket() {
  const btn = document.getElementById('saveTkBtn');
  setBtnLoading(btn, true);
  const body = {
    subject: document.getElementById('tkSubject').value.trim(),
    customer_name: document.getElementById('tkCustomer').value.trim(),
    customer_email: document.getElementById('tkEmail').value.trim(),
    priority: document.getElementById('tkPriority').value,
    channel: document.getElementById('tkChannel').value,
    description: document.getElementById('tkDesc').value.trim(),
    tenant_id: _tenantId,
  };
  if (!body.subject) { toast('Subject required', 'error'); setBtnLoading(btn, false); return; }
  const res = await apiFetch('/support/tickets', { method:'POST', body:JSON.stringify(body) });
  setBtnLoading(btn, false);
  if (res.ok) { closeModal(); toast('Ticket created', 'success'); loadTickets(); }
  else toast('Failed: ' + res.error, 'error');
}

async function viewTicketModal(id) {
  const res = await apiFetch(`/support/tickets/${id}`);
  if (!res.ok) { toast('Failed to load ticket', 'error'); return; }
  const t = res.data;
  const msgs = t.messages || [];
  const pc = PRIORITY_COLORS[t.priority] || 'var(--text-muted)';
  showModal(`
    <div class="modal-header">
      <h3 class="modal-title">${esc(t.subject)}</h3>
      <button class="modal-close" onclick="closeModal()">×</button>
    </div>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px;">
      ${statusBadge(t.status)} <span class="badge badge-info">${esc(t.channel||'email')}</span>
      <span style="font-weight:600;color:${pc};">${esc(t.priority)}</span>
      <span style="font-size:11px;color:var(--text-muted);margin-left:auto;">SLA: ${esc(formatDate(t.sla_due_at))}</span>
    </div>
    <div style="font-size:12px;color:var(--text-muted);margin-bottom:12px;">${esc(t.description||'')}</div>
    <div style="font-size:12px;font-weight:600;margin-bottom:8px;">Messages</div>
    <div style="max-height:240px;overflow-y:auto;">
      ${msgs.length ? msgs.map(m => `
        <div style="padding:8px 12px;margin-bottom:8px;background:${m.sender_type==='customer'?'var(--bg)':'var(--accent-subtle)'};border-radius:8px;border:1px solid var(--border);">
          <div style="display:flex;gap:6px;margin-bottom:4px;">
            <span style="font-size:11px;font-weight:600;">${esc(m.sender_id||'Customer')}</span>
            <span style="font-size:11px;color:var(--text-muted);">${timeAgo(m.created_at)}</span>
          </div>
          <div style="font-size:12px;">${esc(m.content)}</div>
        </div>`).join('')
      : '<div style="padding:12px;color:var(--text-muted);text-align:center;">No messages</div>'}
    </div>
    <div class="modal-footer">
      <button class="btn btn-secondary" onclick="closeModal()">Close</button>
      <button class="btn btn-primary" onclick="closeModal();replyTicketModal('${esc(t.id)}','${esc(t.subject)}')">Reply</button>
      ${t.status!=='resolved'?`<button class="btn btn-secondary" onclick="resolveTicket('${esc(t.id)}')">Resolve</button>`:''}
    </div>
  `);
}

function replyTicketModal(ticketId, subject) {
  showModal(`
    <div class="modal-header"><h3 class="modal-title">Reply: ${esc(subject)}</h3><button class="modal-close" onclick="closeModal()">×</button></div>
    <div class="form-group"><label>Message *</label><textarea id="replyMsg" rows="5" placeholder="Type your reply…"></textarea></div>
    <div class="form-group"><label>Update Status</label>
      <select id="replyStatus">
        <option value="">No change</option><option value="open">Open</option>
        <option value="in_progress">In Progress</option><option value="pending">Pending</option>
        <option value="resolved">Resolved</option>
      </select>
    </div>
    <div class="modal-footer">
      <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
      <button class="btn btn-primary" id="sendReplyBtn" onclick="submitReply('${esc(ticketId)}')">Send Reply</button>
    </div>
  `);
}

async function submitReply(ticketId) {
  const btn = document.getElementById('sendReplyBtn');
  setBtnLoading(btn, true);
  const content = document.getElementById('replyMsg').value.trim();
  const newStatus = document.getElementById('replyStatus').value;
  if (!content) { toast('Message required', 'error'); setBtnLoading(btn, false); return; }
  const msgRes = await apiFetch(`/support/tickets/${ticketId}/messages`, {
    method: 'POST',
    body: JSON.stringify({ content, sender_type:'agent', sender_id:'agent', tenant_id:_tenantId }),
  });
  if (newStatus) {
    await apiFetch(`/support/tickets/${ticketId}`, { method:'PATCH', body:JSON.stringify({ status:newStatus }) });
  }
  setBtnLoading(btn, false);
  if (msgRes.ok) { closeModal(); toast('Reply sent', 'success'); loadTickets(); }
  else toast('Failed: ' + msgRes.error, 'error');
}

async function resolveTicket(id) {
  const res = await apiFetch(`/support/tickets/${id}`, { method:'PATCH', body:JSON.stringify({ status:'resolved' }) });
  if (res.ok) { closeModal(); toast('Ticket resolved', 'success'); loadTickets(); }
  else toast('Failed: ' + res.error, 'error');
}

// ── Section loaders ───────────────────────────────────────────────────────────

const sectionLoaders = {
  dashboard:        loadDashboard,
  marketplace:      loadMarketplace,
  installed:        loadInstalled,
  oauth:            loadOAuth,
  webhooks:         loadWebhooks,
  queues:           loadQueues,
  logs:             loadLogs,
  health:           loadHealth,
  plugins:          loadPlugins,
  events:           loadEvents,
  permissions:      loadPermissions,
  settings:         loadSettings,
  // ERP
  erp:              loadERP,
  vendors:          loadVendors,
  'purchase-orders':loadPurchaseOrders,
  invoices:         loadInvoices,
  inventory:        loadInventory,
  warehouses:       loadWarehouses,
  // CRM
  crm:              loadCRM,
  pipeline:         loadPipeline,
  leads:            loadLeads,
  contacts:         loadContacts,
  opportunities:    loadOpportunities,
  // Ops
  tracking:         loadTracking,
  workflows:        loadWorkflows,
  support:          loadTickets,
};

// ── Init ──────────────────────────────────────────────────────────────────────

async function initAuth() {
  await ensureSession();
}

document.addEventListener('DOMContentLoaded', async () => {
  await initAuth();
  showSection('dashboard');
  loadInstalled();
  setInterval(loadDashboard, 30000);
});
