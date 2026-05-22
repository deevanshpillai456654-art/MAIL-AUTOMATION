// INTEMO - Enterprise Application Runtime v2
(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const $$ = (sel, ctx = document) => Array.from(ctx.querySelectorAll(sel));
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
  const safeJson = (raw, fallback = {}) => { try { return typeof raw === 'string' ? JSON.parse(raw) : (raw ?? fallback); } catch { return fallback; } };

  // Ops-views helpers — querySelector shorthand, escape alias, event binder, API wrapper
  const _q = (sel, ctx = document) => ctx.querySelector(sel);
  const _esc = esc;
  function _bind(id, event, fn) { const el = document.getElementById(id); if (el) el.addEventListener(event, fn); }
  async function _api(path, method = 'GET', body) {
    const opt = { method };
    if (body !== undefined) opt.body = JSON.stringify(body);
    const result = await api('/api/v1' + path, opt);
    if (!result.ok) throw Object.assign(new Error(String(result.error?.detail || result.error?.message || 'Request failed')), { status: result.status });
    return result.data;
  }
  function _debounce(fn, ms = 280) {
    let t;
    return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
  }

  function applyDynamicVisuals(root = document) {
    root.querySelectorAll('[data-progress]').forEach(el => {
      const value = Math.max(0, Math.min(100, Number(el.dataset.progress) || 0));
      el.style.width = `${value}%`;
    });
    root.querySelectorAll('[data-bar-height]').forEach(el => {
      const value = Math.max(8, Math.min(100, Number(el.dataset.barHeight) || 8));
      el.style.height = `${value}%`;
    });
  }

  const state = {
    currentView: 'dashboard',
    accounts: [], emails: [], folders: [], labels: [], rules: [], templates: [], reports: {}, admin: {},
    selectedEmail: null, selectedMailboxId: '', savedFilter: 'all', currentProvider: 'custom',
    selectedEmails: new Set(),
    onnx: {status: null, lastClassification: null, lastPayload: null, learningImportPreview: null},
    runtime: {profile: 'standard', ai_mode: 'cloud', frontend: {low_resource: false, minimal_animations: false, deferred_rendering: false}}
  };

  const PROVIDER_DEFAULTS = {
    gmail:        {label:'Gmail',           method:'oauth_or_app_password', imap_host:'imap.gmail.com',        imap_port:993,  smtp_host:'smtp.gmail.com',      smtp_port:465, ssl:true, oauth:'gmail'},
    outlook:      {label:'Outlook',         method:'oauth_or_app_password', imap_host:'outlook.office365.com', imap_port:993,  smtp_host:'smtp.office365.com',  smtp_port:587, ssl:true, oauth:'microsoft'},
    microsoft365: {label:'Microsoft 365',   method:'oauth_or_app_password', imap_host:'outlook.office365.com', imap_port:993,  smtp_host:'smtp.office365.com',  smtp_port:587, ssl:true, oauth:'microsoft'},
    exchange:     {label:'Exchange Online', method:'oauth_or_app_password', imap_host:'outlook.office365.com', imap_port:993,  smtp_host:'smtp.office365.com',  smtp_port:587, ssl:true, oauth:'microsoft'},
    yahoo:        {label:'Yahoo Mail',      method:'oauth_or_app_password', imap_host:'imap.mail.yahoo.com',   imap_port:993,  smtp_host:'smtp.mail.yahoo.com', smtp_port:465, ssl:true, oauth:'yahoo'},
    zoho:         {label:'Zoho Mail',       method:'oauth_or_app_password', imap_host:'imap.zoho.com',         imap_port:993,  smtp_host:'smtp.zoho.com',       smtp_port:465, ssl:true, oauth:'zoho'},
    yandex:       {label:'Yandex Mail',     method:'oauth_or_app_password', imap_host:'imap.yandex.com',       imap_port:993,  smtp_host:'smtp.yandex.com',     smtp_port:465, ssl:true, oauth:'yandex'},
    icloud:       {label:'iCloud Mail',     method:'app_password',          imap_host:'imap.mail.me.com',      imap_port:993,  smtp_host:'smtp.mail.me.com',    smtp_port:587, ssl:true},
    proton:       {label:'Proton Bridge',   method:'bridge_password',       imap_host:'127.0.0.1',             imap_port:1143, smtp_host:'127.0.0.1',           smtp_port:1025,ssl:true},
    fastmail:     {label:'Fastmail',        method:'app_password',          imap_host:'imap.fastmail.com',     imap_port:993,  smtp_host:'smtp.fastmail.com',   smtp_port:465, ssl:true},
    aol:          {label:'AOL Mail',        method:'app_password',          imap_host:'imap.aol.com',          imap_port:993,  smtp_host:'smtp.aol.com',        smtp_port:465, ssl:true},
    imap:         {label:'IMAP/SMTP',       method:'app_password',          imap_host:'imap.example.com',      imap_port:993,  smtp_host:'smtp.example.com',    smtp_port:465, ssl:true},
    cpanel:       {label:'cPanel Mail',     method:'app_password',          imap_host:'mail.example.com',      imap_port:993,  smtp_host:'mail.example.com',    smtp_port:465, ssl:true},
    zimbra:       {label:'Zimbra',          method:'app_password',          imap_host:'mail.example.com',      imap_port:993,  smtp_host:'mail.example.com',    smtp_port:465, ssl:true},
    custom:       {label:'Custom Domain',   method:'app_password',          imap_host:'',                      imap_port:993,  smtp_host:'',                    smtp_port:465, ssl:true}
  };

  const PROVIDERS = [
    ['gmail','Gmail','OAuth - API sync'], ['outlook','Outlook','Microsoft OAuth'],
    ['microsoft365','Microsoft 365','Graph API'], ['exchange','Exchange','Enterprise Graph'],
    ['yahoo','Yahoo','OAuth or app password'], ['zoho','Zoho','OAuth or IMAP'],
    ['yandex','Yandex','OAuth or app password'], ['icloud','iCloud','App-specific password'],
    ['proton','Proton Bridge','Local bridge'], ['fastmail','Fastmail','App password'],
    ['aol','AOL','App password'], ['imap','IMAP/SMTP','Universal mailbox'],
    ['custom','Custom Domain','support@company.com']
  ];

  const PROVIDER_LOGO_IMAGES = {
    gmail: '/dashboard/assets/providers/gmail.svg',
    outlook: '/dashboard/assets/providers/outlook.svg',
    microsoft365: '/dashboard/assets/providers/microsoft365.svg',
    exchange: '/dashboard/assets/providers/exchange.svg',
    yahoo: '/dashboard/assets/providers/yahoo.svg',
    zoho: '/dashboard/assets/providers/zoho.svg',
    yandex: '/dashboard/assets/providers/yandex.svg',
    icloud: '/dashboard/assets/providers/icloud.svg',
    proton: '/dashboard/assets/providers/proton.svg',
    fastmail: '/dashboard/assets/providers/fastmail.svg',
    aol: '/dashboard/assets/providers/aol.svg',
    imap: '/dashboard/assets/providers/imap.svg',
    custom: '/dashboard/assets/providers/custom.svg'
  };

  const PAGES = {
    dashboard:   ['Dashboard',    'Operational overview  -  mailboxes, inbox health, AI processing and automations.'],
    accounts:    ['Accounts',     'Connect Gmail, Outlook, Microsoft 365, Exchange, Yahoo, Zoho, IMAP/SMTP and custom domain mailboxes.'],
    inbox:       ['Inbox',        'Threaded conversations with AI summaries, labels, folders and workflow actions.'],
    ai:          ['AI Processing','Analyze, classify and extract entities from emails with controlled workflow actions.'],
    automations: ['Automations',  'Create, simulate and manage forwarding, categorization and workflow rules.'],
    templates:   ['Templates',    'Reusable reply, rule and reporting templates.'],
    reports:     ['Analytics',    'Generate operational, business, forwarding, AI and inbox reports.'],
    connectors:  ['Connectors',   'Install, configure and monitor integrations  -  Gmail, Slack, WhatsApp, Shopify, webhooks and plugins.'],
    ocr:         ['OCR Engine',   'Scan PDFs, images and emails  -  extract text and structured fields like invoice numbers, dates and amounts.'],
    workflows:   ['Workflow Engine',    'Build, activate and monitor AI-native operational workflows  -  from inbox triage to threat escalation.'],
    command:     ['Command Center',    'Unified operational intelligence  -  real-time event timeline, AI insights, autonomous agents, and system health.'],
    webhooks:    ['Webhooks',     'Push platform events to Slack, PagerDuty, n8n or any HTTP endpoint with HMAC-signed payloads.'],
    admin:       ['Admin',        'Manage governance, users, roles, provider settings, queues and update controls.'],
    settings:    ['Settings',     'General, accounts, AI, automations, notifications, security, integrations, updates and advanced.']
  };
  PAGES.dashboard = ['Dashboard', 'Operational overview - mailboxes, inbox health, AI processing, and automations.'];
  PAGES.dispatches = ['Activity Queue', 'Scheduled operational digests - generate and deliver platform reports on a recurring schedule.'];
  PAGES.playbooks  = ['AI Actions', 'Automation sequences - trigger workflows, webhooks, notifications and incident comments in response to platform events.'];
  PAGES.webhooks   = ['Webhook Channels', 'Push platform events to Slack, PagerDuty, n8n or any HTTP endpoint with HMAC-signed payloads.'];
  PAGES.sla        = ['Service Goals', 'Response and resolution time targets per severity with automatic event emission.'];
  PAGES.oncall     = ['Team Availability', 'Rotation schedules and escalation policies for unacknowledged incidents.'];
  PAGES['api-keys'] = ['API Access', 'Manage named access keys for external integrations - hashed storage, scope control, expiry and rotation.'];
  PAGES.maintenance = ['System Updates', 'Schedule planned update windows and suppress alerts for the duration.'];
  PAGES.runbooks   = ['Automation Guides', 'Human-readable operational documentation with full version history and search.'];
  PAGES.changes    = ['Change Requests', 'Plan, approve and track operational changes.'];
  PAGES.problems   = ['Service Issues', 'Track recurring service issues and root-cause work.'];
  PAGES.risks      = ['Risk Overview', 'Review business risk, ownership and mitigation status.'];
  PAGES.certificates = ['Secure Access', 'Track certificates, expiry and renewal readiness.'];
  PAGES.configs    = ['Workspace Settings', 'Manage workspace configuration and version history.'];
  PAGES.flags      = ['Status Markers', 'Manage feature flags and rollout status markers.'];
  PAGES.capacity   = ['System Usage', 'Monitor capacity and resource utilization.'];
  PAGES.knowledge  = ['Knowledge Base', 'Search and maintain internal operating knowledge.'];
  PAGES.slos        = ['SLO Management', 'Service Level Objectives with error budget computation, breach detection and lifecycle management.'];
  PAGES.deployments = ['Releases', 'Track releases, rollout status and operational notes.'];
  PAGES.agents      = ['Agents', 'Autonomous operational agents, lifecycle controls and recent agent actions.'];

  const FALLBACK_ADMIN_SECTIONS = [
    ['User Management','Manage users, invites and account ownership.'],
    ['Roles & Permissions','Control access and approval workflows.'],
    ['Team Management','Configure teams and assignment queues.'],
    ['System Health','Review API, DB, queue and sync health.'],
    ['Rule Management','Audit rule lifecycle, versions and approvals.'],
    ['Automation Management','Manage automation retries and failures.'],
    ['Email Provider Management','Configure OAuth, IMAP, SMTP and provider defaults.'],
    ['Update Center','Validate ZIP patches, backup, install and rollback.'],
    ['Audit Logs','Review sync, forwarding, categorization and admin events.'],
    ['Security Center','Review sessions, RBAC, credential vault and rate limits.'],
    ['Backup Manager','Validate backups and recovery points.'],
    ['Database Health','Inspect indexes, migrations and integrity status.'],
    ['API Integrations','Manage integrations and webhooks.'],
    ['Notification Management','Configure alert rules and recipients.'],
    ['AI Configuration','Manage classification, thresholds and review queues.'],
    ['Queue Monitoring','Review sync, AI, forwarding, reports and update queues.'],
    ['Storage Management','Control retention, attachments and quotas.'],
    ['Maintenance Mode','Safely pause operations during maintenance.'],
    ['Activity Monitoring','Review operational activity and anomalies.'],
    ['License / Subscription','View license, plan and deployment entitlement.']
  ].map(([name, description]) => ({name, description, items:[{label:'Status',value:'Ready'},{label:'Controls',value:'Available'},{label:'Audit',value:'Enabled'}]}));

  // -- API ---------------------------------------------------------------------
  function requiresAiAdminRole(url, method = 'GET') {
    let path = String(url || '');
    try { path = new URL(path, location.origin).pathname; } catch { path = path.split('?')[0]; }
    const verb = String(method || 'GET').toUpperCase();
    if (path === '/api/v1/ai/learning/export') return true;
    if (path === '/api/v1/ai/learning/import' || path === '/api/v1/ai/learning/import/preview') return true;
    if (verb === 'DELETE' && path.startsWith('/api/v1/ai/learning/overrides/')) return true;
    if (verb === 'POST' && path === '/api/v1/ai/onnx/evaluate') return true;
    if (verb === 'POST' && path.startsWith('/api/v1/ai/self-healing/models/')) return true;
    if (path.startsWith('/api/v1/ai/backups/')) return true;
    return false;
  }

  let localSessionReady = null;
  async function ensureLocalSession() {
    if (!localSessionReady) {
      localSessionReady = fetch('/api/v1/session/bootstrap', {
        method: 'POST',
        credentials: 'same-origin'
      }).catch(() => null);
    }
    await localSessionReady;
  }

  async function api(url, opt = {}) {
    await ensureLocalSession();
    const method = opt.method || 'GET';
    const headers = {'Content-Type':'application/json', ...(opt.headers || {})};
    if (requiresAiAdminRole(url, method) && !headers['X-Intemo-Role']) headers['X-Intemo-Role'] = 'admin';
    const options = {...opt, headers};
    options.credentials = 'same-origin';
    if (opt.body instanceof FormData) delete options.headers['Content-Type'];
    try {
      const res = await fetch(url, options);
      const text = await res.text();
      const data = text ? safeJson(text, {message:text}) : {};
      return res.ok ? {ok:true, status:res.status, data} : {ok:false, status:res.status, error:data.detail || data.message || data};
    } catch (err) {
      return {ok:false, status:0, error:{message:err.message || 'Network error'}};
    }
  }

  function msgFromError(error) {
    if (!error) return 'Request failed.';
    if (typeof error === 'string') return error;
    return error.client_message || error.message || error.status || JSON.stringify(error).slice(0, 220);
  }

  async function loadRuntimeProfile() {
    const result = await api('/api/v1/runtime/frontend');
    if (!result.ok) return state.runtime;
    state.runtime = result.data || state.runtime;
    const flags = state.runtime.frontend || {};
    document.documentElement.dataset.runtimeProfile = state.runtime.profile || 'standard';
    document.documentElement.dataset.aiMode = state.runtime.ai_mode || 'cloud';
    document.documentElement.classList.toggle('low-resource-mode', !!flags.low_resource);
    document.documentElement.classList.toggle('minimal-animations', !!flags.minimal_animations);
    _syncLowResBtn(!!flags.low_resource);
    return state.runtime;
  }

  function _syncLowResBtn(isActive) {
    const btn = _q('#lowResToggleBtn');
    if (!btn) return;
    btn.classList.toggle('active', isActive);
    btn.title = isActive ? 'Low Resource Mode ON — click to disable' : 'Low Resource Mode OFF — click to enable';
    const lbl = _q('#lowResLabel');
    if (lbl) lbl.textContent = isActive ? 'Low Res: ON' : 'Low Resource';
  }

  async function _toggleLowResourceMode() {
    const isActive = _q('#lowResToggleBtn').classList.contains('active');
    const newState = !isActive;
    try {
      await _api('/runtime/low-resource-mode', 'POST', {enabled: newState});
      _syncLowResBtn(newState);
      document.documentElement.classList.toggle('low-resource-mode', newState);
      document.documentElement.classList.toggle('minimal-animations', newState);
      if (newState) document.documentElement.dataset.runtimeProfile = 'low_resource';
      await loadRuntimeProfile();
    } catch(err) {
      console.error('Failed to toggle low resource mode:', err);
    }
  }

  function connectorNavIcon(category) {
    const cat = String(category || '').toLowerCase();
    if (cat === 'ai') return '<circle cx="10" cy="10" r="3"/><path d="M10 2v2M10 16v2M2 10h2M16 10h2M4.2 4.2l1.4 1.4M14.4 14.4l1.4 1.4M4.2 15.8l1.4-1.4M14.4 5.6l1.4-1.4"/>';
    if (cat === 'communication') return '<path d="M3 5h14v9H7l-4 4V5Z"/><path d="M6 8h8M6 11h5"/>';
    if (cat === 'webhook') return '<path d="M7 10a3 3 0 1 0 6 0 3 3 0 0 0-6 0Z"/><path d="M10 7V4M10 16v-3M7 10H4M16 10h-3"/>';
    if (cat === 'erp' || cat === 'accounting') return '<rect x="3" y="3" width="14" height="14" rx="2"/><path d="M6 7h8M6 10h8M6 13h5"/>';
    if (cat === 'crm' || cat === 'support') return '<circle cx="10" cy="6.5" r="3"/><path d="M4 17a6 6 0 0 1 12 0"/>';
    if (cat === 'tracking') return '<circle cx="10" cy="10" r="7"/><path d="m13 7-2 5-4 1 2-5 4-1Z"/>';
    return '<circle cx="5" cy="10" r="2.5"/><circle cx="15" cy="5" r="2.5"/><circle cx="15" cy="15" r="2.5"/><path d="M7.4 9l5.2-2.8M7.4 11l5.2 2.8"/>';
  }

  const CONNECTOR_FEATURE_VIEWS = {
    ocr_engine: 'ocr'
  };

  function renderInstalledConnectorNavigation(connectors) {
    const host = $('installedConnectorNav');
    if (!host) return;
    const installed = (connectors || [])
      .filter(connector => connector && connector.is_installed)
      .filter(connector => connector.id);
    host.innerHTML = installed.map(connector => `
      <button class="nav-btn connector-nav-btn" data-connector-nav-id="${esc(connector.id)}" type="button">
        <svg class="nav-icon" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true">
          ${connectorNavIcon(connector.category)}
        </svg>
        ${esc(connector.name || connector.id)}
      </button>
    `).join('');
    host.hidden = installed.length === 0;
  }

  function openConnectorFromMainNav(connectorId) {
    const featureView = CONNECTOR_FEATURE_VIEWS[connectorId];
    if (featureView) {
      showView(featureView);
      return;
    }
    showView('connectors');
    const frame = $('connectorFrame');
    if (!frame) return;
    const target = `/connectors-panel?connector=${encodeURIComponent(connectorId || '')}&section=installed&t=${Date.now()}`;
    frame.src = target;
    frame.dataset.loaded = '1';
  }

  async function refreshConnectorFeatureNavigation() {
    const result = await api('/api/connector-panel/marketplace/connectors?tenant_id=default');
    const connectors = result.ok && Array.isArray(result.data) ? result.data : [];
    renderInstalledConnectorNavigation(connectors);
    const installedIds = new Set(
      connectors
        .filter(connector => connector && connector.is_installed)
        .map(connector => connector.id)
        .filter(Boolean)
    );
    const installedCategories = new Set(
      connectors
        .filter(connector => connector && connector.is_installed)
        .map(connector => String(connector.category || '').toLowerCase())
        .filter(Boolean)
    );
    $$('[data-requires-connector], [data-requires-connector-category], [data-requires-active-connector]').forEach(el => {
      const requiredIds = String(el.dataset.requiresConnector || '').split(/\s+/).filter(Boolean);
      const requiredCategories = String(el.dataset.requiresConnectorCategory || '').toLowerCase().split(/\s+/).filter(Boolean);
      const needsAnyConnector = el.hasAttribute('data-requires-active-connector');
      const visible = (
        (!requiredIds.length || requiredIds.some(id => installedIds.has(id))) &&
        (!requiredCategories.length || requiredCategories.some(category => installedCategories.has(category))) &&
        (!needsAnyConnector || installedIds.size > 0)
      );
      el.hidden = !visible;
      el.setAttribute('aria-hidden', visible ? 'false' : 'true');
      el.tabIndex = visible ? 0 : -1;
    });
    const activeView = document.querySelector(`.nav-btn[data-view="${state.currentView}"]`);
    if (activeView?.hidden) showView('connectors');
    const activeConnectorId = Object.entries(CONNECTOR_FEATURE_VIEWS)
      .find(([, view]) => view === state.currentView)?.[0];
    if (activeConnectorId && !installedIds.has(activeConnectorId)) showView('connectors');
  }

  window.addEventListener('message', event => {
    if (event.origin !== location.origin) return;
    if (event.data?.type === 'connectors:changed') refreshConnectorFeatureNavigation();
  });

  // -- Toasts ------------------------------------------------------------------
  function toast(title, msg = '', tone = 'info') {
    const wrap = $('toastWrap');
    if (!wrap) return;
    const node = document.createElement('div');
    node.className = `toast ${tone}`;
    node.innerHTML = `<b>${esc(title)}</b>${msg ? `<small>${esc(msg)}</small>` : ''}`;
    wrap.appendChild(node);
    setTimeout(() => node.remove(), 5200);
  }

  // -- View routing ------------------------------------------------------------
  function showView(view, settingsTab) {
    const requestedNav = document.querySelector(`.nav-btn[data-view="${view}"]`);
    if (requestedNav?.hidden) view = 'connectors';
    state.currentView = view;
    $$('.view').forEach(el => el.classList.toggle('active', el.id === `view-${view}`));
    $$('.nav-btn').forEach(btn => {
      const active = btn.dataset.view === view;
      btn.classList.toggle('active', active);
      if (active) btn.setAttribute('aria-current', 'page');
      else btn.removeAttribute('aria-current');
    });
    const [title, subtitle] = PAGES[view] || PAGES.dashboard;
    if ($('pageTitle'))    $('pageTitle').textContent    = title;
    if ($('pageSubtitle')) $('pageSubtitle').textContent = subtitle;
    if (view === 'accounts')    loadAccounts();
    if (view === 'inbox')       loadInbox();
    if (view === 'automations') { loadRules(); loadRuleAnalytics(); populateRuleMailboxOptions(); loadLabelsAndFolders(); loadPresets(); }
    if (view === 'templates')   loadTemplates();
    if (view === 'reports')     loadReports(true);
    if (view === 'admin')       loadAdmin();
    if (view === 'settings')    renderSettings(settingsTab || 'general');
    if (view === 'connectors') {
      const frame = $('connectorFrame');
      if (frame && !frame.dataset.loaded) {
        frame.src = '/connectors-panel?t=' + Date.now();
        frame.dataset.loaded = '1';
      }
    }
    if (view === 'ocr')       initOCRView();
    if (view === 'workflows') initWorkflowsView();
    if (view === 'webhooks')   initWebhooksView();
    if (view === 'dispatches') initDispatchesView();
    if (view === 'playbooks')  initPlaybooksView();
    if (view === 'sla')         initSlaView();
    if (view === 'maintenance') initMaintenanceView();
    if (view === 'api-keys')   initApiKeysView();
    if (view === 'oncall')     initOncallView();
    if (view === 'runbooks')   initRunbooksView();
    if (view === 'slos')       initSlosView();
    if (view === 'changes')    initChangesView();
    if (view === 'risks')      initRisksView();
    if (view === 'certificates') initCertificatesView();
    if (view === 'configs')    initConfigsView();
    if (view === 'licenses')   initLicensesView();
    if (view === 'budgets')    initBudgetsView();
    if (view === 'flags')      initFlagsView();
    if (view === 'vendors')    initVendorsView();
    if (view === 'capacity')   initCapacityView();
    if (view === 'knowledge')  initKnowledgeView();
    if (view === 'assets')     initAssetsView();
    if (view === 'deployments') initDeploymentsView();
    if (view === 'services')   initServicesView();
    if (view === 'problems')   initProblemsView();
    if (view === 'agents')     initAgentsView();
    if (view === 'command')   initCommandCenterView();
    // Keep event stream alive while on command center; close when navigating away
    if (view !== 'command' && _cmdWs && _cmdWs.readyState === WebSocket.OPEN) {
      try { _cmdWs.close(); } catch (_) {}
      _cmdWs = null;
    }
    window.scrollTo({top:0, behavior:'smooth'});
  }

  // -- Provider helpers --------------------------------------------------------
  function oauthFamily(provider) {
    if (provider === 'gmail') return 'gmail';
    if (['outlook','microsoft365','exchange'].includes(provider)) return 'microsoft';
    if (['yahoo','zoho','yandex'].includes(provider)) return provider;
    return '';
  }

  function oauthLabel(provider) {
    if (provider === 'gmail') return 'Google';
    if (['outlook','microsoft365','exchange'].includes(provider)) return 'Microsoft';
    if (provider === 'yahoo') return 'Yahoo';
    if (provider === 'zoho') return 'Zoho';
    if (provider === 'yandex') return 'Yandex';
    return PROVIDER_DEFAULTS[provider]?.label || provider;
  }

  function oauthStartUrl(provider) {
    if (provider === 'gmail') return '/api/v1/oauth/google/start';
    if (['outlook','microsoft365','exchange'].includes(provider)) return '/api/v1/oauth/microsoft/start';
    if (provider === 'yahoo') return '/api/v1/oauth/yahoo/start';
    if (provider === 'zoho') return '/api/v1/oauth/zoho/start';
    if (provider === 'yandex') return '/api/v1/oauth/yandex/start';
    return '';
  }

  function oauthStartUrlWithEmail(provider, email) {
    const base = oauthStartUrl(provider);
    if (!base) return '';
    const parsed = new URL(base, window.location.origin);
    parsed.searchParams.set('email', email);
    return `${parsed.pathname}${parsed.search}`;
  }

  function updateOAuthSubmitState() {
    const form = $('accountForm');
    const submit = form?.querySelector('button[type="submit"]');
    if (!submit) return;
    const oauthActive = Boolean(oauthFamily(state.currentProvider) && selectedConnectionMethod() === 'oauth');
    submit.disabled = oauthActive;
  }

  function useAppPasswordFlow() {
    const select = $('connectionMethod');
    if (select) select.value = 'app_password';
    const pw = $('accountForm')?.password;
    if (pw) {
      const label = pw.closest('label');
      label?.classList.remove('muted-field');
      pw.required = true;
      pw.disabled = false;
    }
    renderProviderActionPanel(state.currentProvider || 'custom');
    updateOAuthSubmitState();
  }

  function providerForEmail(email) {
    const domain = String(email || '').toLowerCase().split('@').pop() || '';
    if (['gmail.com','googlemail.com'].includes(domain)) return 'gmail';
    if (['outlook.com','hotmail.com','live.com','msn.com'].includes(domain) || domain.endsWith('.onmicrosoft.com')) return 'outlook';
    if (['yahoo.com','ymail.com'].includes(domain)) return 'yahoo';
    if (['zoho.com','zohomail.com'].includes(domain)) return 'zoho';
    if (['yandex.com','yandex.ru','ya.ru'].includes(domain)) return 'yandex';
    if (['icloud.com','me.com','mac.com'].includes(domain)) return 'icloud';
    if (['proton.me','protonmail.com','pm.me'].includes(domain)) return 'proton';
    if (domain === 'fastmail.com') return 'fastmail';
    if (domain === 'aol.com') return 'aol';
    return 'custom';
  }

  function defaultsFor(provider, email = '') {
    const base = {...(PROVIDER_DEFAULTS[provider] || PROVIDER_DEFAULTS.custom)};
    const domain = String(email || '').toLowerCase().split('@').pop() || '';
    if (provider === 'custom' && domain) { base.imap_host = `imap.${domain}`; base.smtp_host = `smtp.${domain}`; }
    return base;
  }

  // -- Account status panel (dynamic) -----------------------------------------
  function ensureAccountStatusPanel() {
    const form = $('accountForm');
    if (!form) return;
    if (!$('accountStatusPanel')) {
      const el = document.createElement('div');
      el.id = 'accountStatusPanel';
      el.className = 'account-status-panel wide';
      el.innerHTML = '<b>Connection status</b><span>Select a provider or enter an email to begin.</span>';
      form.appendChild(el);
    }
    if (!$('oauthActionPanel')) {
      const el = document.createElement('div');
      el.id = 'oauthActionPanel';
      el.className = 'oauth-action-panel wide';
      form.appendChild(el);
    }
  }

  function setAccountStatus(title, detail = '', tone = 'info') {
    ensureAccountStatusPanel();
    const panel = $('accountStatusPanel');
    if (!panel) return;
    panel.className = `account-status-panel wide ${tone}`;
    panel.innerHTML = `<b>${esc(title)}</b><span>${esc(detail)}</span>`;
  }

  function renderProviderActionPanel(provider, mode = 'normal', detail = '') {
    ensureAccountStatusPanel();
    const panel = $('oauthActionPanel');
    if (!panel) return;
    const family = oauthFamily(provider);
    const d = defaultsFor(provider, $('accountForm')?.email?.value || '');
    if (family && selectedConnectionMethod() !== 'app_password') {
      const guidance = family === 'gmail'
        ? 'Gmail uses Google OAuth. Google OAuth can be blocked until the Google Cloud OAuth consent screen is configured and the mailbox is added as a test user.'
        : family === 'yahoo'
          ? 'Yahoo mail requires an app password for IMAP/SMTP, or a correctly configured Yahoo OAuth app for OAuth mail access.'
          : family === 'zoho'
            ? 'Zoho supports IMAP/SMTP app passwords and OAuth depending on the account region.'
            : 'OAuth uses the provider sign-in page and token vault. Mailbox password fields are hidden in this mode.';
      panel.innerHTML = `<div class="provider-flow-card ${mode === 'setup' ? 'warn' : ''}"><div><b>${esc(oauthLabel(provider))} official OAuth flow</b><span>${esc(detail || guidance)}</span><small>Permissions: read, organize, send, refresh offline access and AI indexing.</small></div><div class="provider-flow-actions"><button class="btn primary" data-oauth-start="${esc(provider)}" type="button">Continue OAuth for entered email</button><button class="btn" data-show-oauth-setup="${esc(provider)}" type="button">Configure OAuth App</button><button class="btn" data-use-app-password type="button">Use app password instead</button></div></div>`;
      return;
    }
    const guidance = provider === 'proton' ? 'Start Proton Mail Bridge first, then enter the bridge credentials and local IMAP/SMTP ports.'
      : provider === 'yahoo' ? 'Yahoo mail requires an app password for IMAP/SMTP. Generate one in Yahoo Account Security.'
      : 'Enter the IMAP/SMTP credentials for this mailbox.';
    panel.innerHTML = `<div class="provider-flow-card"><div><b>${esc(d.label || 'Mailbox')} secure app-password flow</b><span>${esc(guidance)}</span></div><div class="provider-flow-actions"><button class="btn" data-detect-inline type="button">Auto Detect Settings</button></div></div>`;
  }

  function renderOAuthSetupPanel(provider, message = '') {
    ensureAccountStatusPanel();
    const panel = $('oauthActionPanel');
    if (!panel) return;
    const group = oauthFamily(provider);
    if (!group) { renderProviderActionPanel(provider); return; }
    const redirectMap = {gmail:'/api/v1/oauth/google/callback', microsoft:'/api/v1/oauth/microsoft/callback', yahoo:'/api/v1/oauth/yahoo/callback', zoho:'/api/v1/oauth/zoho/callback', yandex:'/api/v1/oauth/yandex/callback'};
    const cloudMap = {gmail:'Google Cloud Console -> APIs & Services -> Credentials', microsoft:'Azure Portal -> App registrations', yahoo:'Yahoo Developer Network -> My Apps', zoho:'Zoho API Console', yandex:'Yandex OAuth Console'};
    const redirect = `${location.origin}${redirectMap[group] || '/api/v1/oauth/google/callback'}`;
    const tenant = group === 'microsoft' ? `<label>Tenant ID<input name="tenant_id" value="common" placeholder="common or tenant ID"></label>` : '';
    const accountEmail = String($('accountForm')?.email?.value || '').trim().toLowerCase();
    panel.innerHTML = `<form class="oauth-setup-card" id="inlineOAuthSetupForm"><div class="wide"><b>Configure ${esc(oauthLabel(provider))} OAuth app</b><span>${esc(message || 'Save OAuth app details for this mailbox. Provider login starts only when you continue OAuth separately.')}</span><small>${group === 'gmail' ? 'Google OAuth can be blocked until the Google Cloud OAuth consent screen is configured with the correct test user.' : ''} Create the app in ${esc(cloudMap[group] || 'Provider developer console')} and add this redirect URI:</small><code>${esc(redirect)}</code></div><input type="hidden" name="provider" value="${esc(group)}"><input type="hidden" name="email_address" value="${esc(accountEmail)}"><input type="hidden" name="redirect_uri" value="${esc(redirect)}"><label>Email address<input value="${esc(accountEmail)}" readonly></label><label>Client ID<input name="client_id" placeholder="OAuth client/application ID" required></label><label>Client Secret<input name="client_secret" type="password" placeholder="Stored encrypted locally" required></label>${tenant}<div class="form-actions wide"><button class="btn primary" type="submit">Save OAuth app details</button><button class="btn" data-continue-oauth="${esc(provider)}" type="button">Continue OAuth for entered email</button><button class="btn" data-use-app-password type="button">Use app password instead</button></div></form>`;
  }

  function renderProviders() {
    const grid = $('providerGrid');
    if (!grid) return;
    grid.innerHTML = PROVIDERS.map(([id, name, desc]) =>
      `<button class="provider-card" data-provider="${id}" type="button">${providerLogoMarkup(id)}<span class="provider-card-copy"><b>${esc(name)}</b><span class="provider-description">${esc(desc)}</span></span></button>`
    ).join('');
    selectProvider(state.currentProvider || 'custom', false);
  }

  function providerLogoMarkup(provider) {
    const src = PROVIDER_LOGO_IMAGES[provider] || PROVIDER_LOGO_IMAGES.custom;
    return `<span class="provider-logo-frame" aria-hidden="true"><img class="provider-logo-img" src="${esc(src)}" alt="" width="44" height="44" loading="lazy"></span>`;
  }

  function updateConnectionMethod(provider) {
    const select = $('connectionMethod');
    if (!select) return;
    const family = oauthFamily(provider);
    select.innerHTML = family
      ? '<option value="oauth">Official OAuth Sign-in</option><option value="app_password">App password / IMAP-SMTP</option>'
      : '<option value="app_password">App password / IMAP-SMTP</option>';
    select.value = family ? 'oauth' : 'app_password';
    const pw = $('accountForm')?.password;
    if (pw) {
      const label = pw.closest('label');
      const oauthOn = family && select.value === 'oauth';
      label?.classList.toggle('muted-field', oauthOn);
      pw.required = !oauthOn;
      pw.disabled = !!oauthOn;
      if (oauthOn) pw.value = '';
    }
    updateOAuthSubmitState();
  }

  function selectedConnectionMethod() {
    return $('connectionMethod')?.value || (oauthFamily(state.currentProvider) ? 'oauth' : 'app_password');
  }

  function applyProviderDefaults(provider, override = false) {
    const form = $('accountForm');
    if (!form) return;
    const email = form.email?.value || '';
    const d = defaultsFor(provider, email);
    if (form.provider) form.provider.value = provider;
    if (override || !form.imap_host.value || form.imap_host.value.includes('example.com')) form.imap_host.value = d.imap_host || '';
    if (override || !form.imap_port.value) form.imap_port.value = d.imap_port || 993;
    if (override || !form.smtp_host.value || form.smtp_host.value.includes('example.com')) form.smtp_host.value = d.smtp_host || '';
    if (override || !form.smtp_port.value) form.smtp_port.value = d.smtp_port || 465;
    if (form.ssl) form.ssl.checked = d.ssl !== false;
    updateConnectionMethod(provider);
    setAccountStatus(`${d.label || provider} selected`, `${d.oauth ? 'OAuth is the default.' : 'App-password flow.'} IMAP ${d.imap_host || 'manual'}:${d.imap_port} - SMTP ${d.smtp_host || 'manual'}:${d.smtp_port}`, 'info');
    renderProviderActionPanel(provider);
    $$('.provider-card').forEach(card => card.classList.toggle('active', card.dataset.provider === provider));
  }

  function selectProvider(provider, override = true) {
    state.currentProvider = provider || 'custom';
    applyProviderDefaults(state.currentProvider, override);
  }

  async function detectProvider() {
    const form = $('accountForm');
    if (!form) return;
    const email = form.email.value.trim();
    if (!email) return setAccountStatus('Email required', 'Enter the mailbox address before detection.', 'warn');
    setAccountStatus('Detecting provider', 'Checking provider defaults and authentication method...', 'loading');
    const result = await api('/api/v1/accounts/detect', {method:'POST', body:JSON.stringify({email})});
    const fallback = providerForEmail(email);
    const data = result.ok ? result.data : {};
    const provider = data.provider || fallback;
    if (form.provider) form.provider.value = provider;
    state.currentProvider = provider;
    const d = data.defaults || data;
    form.imap_host.value = d.imap_host || defaultsFor(provider, email).imap_host || '';
    form.imap_port.value = d.imap_port || defaultsFor(provider, email).imap_port || 993;
    form.smtp_host.value = d.smtp_host || defaultsFor(provider, email).smtp_host || '';
    form.smtp_port.value = d.smtp_port || defaultsFor(provider, email).smtp_port || 465;
    form.ssl.checked = data.ssl !== false;
    updateConnectionMethod(provider);
    setAccountStatus('Provider detected', data.client_message || `${PROVIDER_DEFAULTS[provider]?.label || provider} defaults loaded.`, 'ok');
    renderProviderActionPanel(provider, data.setup_required ? 'setup' : 'normal', data.client_message || '');
    $$('.provider-card').forEach(card => card.classList.toggle('active', card.dataset.provider === provider));
  }

  function accountPayload(form) {
    const fd = new FormData(form);
    const payload = Object.fromEntries(fd.entries());
    const provider = payload.provider || state.currentProvider || providerForEmail(payload.email);
    const d = defaultsFor(provider, payload.email);
    const method = payload.connection_method || selectedConnectionMethod();
    return {
      email: String(payload.email || '').trim().toLowerCase(), provider,
      password: method === 'oauth' ? null : (payload.password || null),
      host: payload.imap_host || d.imap_host || null,
      port: Number(payload.imap_port || d.imap_port || 993),
      security: payload.ssl ? 'ssl' : 'starttls',
      imap_host: payload.imap_host || d.imap_host || null,
      imap_port: Number(payload.imap_port || d.imap_port || 993),
      smtp_host: payload.smtp_host || d.smtp_host || null,
      smtp_port: Number(payload.smtp_port || d.smtp_port || 465),
      ssl: Boolean(fd.get('ssl')),
      sync_interval: Number(payload.sync_interval || 20),
      connection_method: method
    };
  }

  async function startOAuthFlow(provider, email) {
    const family = oauthFamily(provider);
    if (!family) { setAccountStatus('App-password flow required', 'This provider connects via IMAP/SMTP. Enter the mailbox app password and click Save & Start Sync.', 'warn'); renderProviderActionPanel(provider); return; }
    const accountEmail = String(email || $('accountForm')?.email?.value || '').trim().toLowerCase();
    if (!accountEmail) {
      const msg = 'Enter the email address before configuring or starting OAuth.';
      setAccountStatus('Email address required', msg, 'warn');
      toast('Email address required', msg, 'warn');
      return;
    }
    const start = oauthStartUrlWithEmail(provider, accountEmail);
    setAccountStatus(`Starting ${oauthLabel(provider)} sign-in`, 'Checking OAuth configuration before opening the provider login page...', 'loading');
    const result = await api(start, {method:'POST', body:JSON.stringify({email: accountEmail, email_address: accountEmail, redirect_after:'/dashboard'})});
    if (result.ok && result.data?.auth_url) { const target = String(result.data.auth_url); if (target.startsWith('https://')) { toast(`${oauthLabel(provider)} sign-in`, 'Opening provider authorization page.', 'ok'); window.location.assign(target); return; } }
    const err = result.error || result.data || {};
    if (result.status === 428 || err.status === 'provider_setup_required' || err.setup_required) { setAccountStatus('OAuth setup required', msgFromError(err), 'warn'); renderOAuthSetupPanel(provider, msgFromError(err)); return; }
    setAccountStatus('OAuth could not start', msgFromError(err), 'bad');
    toast('OAuth could not start', msgFromError(err), 'bad');
  }

  async function saveInlineOAuthSetup(event) {
    event.preventDefault();
    const form = event.target;
    const provider = form.provider.value;
    const payload = Object.fromEntries(new FormData(form).entries());
    const accountEmail = String(payload.email_address || $('accountForm')?.email?.value || '').trim().toLowerCase();
    if (!accountEmail) return toast('Email address required', 'Enter the email address before configuring or starting OAuth.', 'warn');
    if (!payload.client_id || !payload.client_secret) return toast('OAuth credentials required', 'Client ID and Client Secret are required.', 'warn');
    const btn = form.querySelector('button[type="submit"]');
    if (btn) { btn.disabled = true; btn.textContent = 'Saving...'; }
    const result = await api('/api/v1/oauth/config', {method:'POST', body:JSON.stringify({
      provider,
      email_address: accountEmail,
      client_id: payload.client_id,
      client_secret: payload.client_secret,
      redirect_uri: payload.redirect_uri,
      provider_options: payload.tenant_id ? {tenant_id: payload.tenant_id} : {}
    })});
    if (btn) { btn.disabled = false; btn.textContent = 'Save OAuth app details'; }
    if (!result.ok) { setAccountStatus('OAuth setup not saved', msgFromError(result.error), 'bad'); toast('OAuth setup failed', msgFromError(result.error), 'bad'); return; }
    setAccountStatus('OAuth setup saved', 'Credentials encrypted locally. Continue OAuth for the entered email when ready.', 'ok');
    toast('OAuth configured', 'OAuth app details saved for this mailbox.', 'ok');
  }

  async function testAccountConnection() {
    const form = $('accountForm');
    if (!form) return;
    const payload = accountPayload(form);
    if (!payload.email || !payload.email.includes('@')) return setAccountStatus('Email required', 'Enter a mailbox address before testing.', 'warn');
    setAccountStatus('Testing connection', 'Verifying IMAP/SMTP reachability and credentials...', 'loading');
    const result = await api('/api/v1/accounts/test', {method:'POST', body:JSON.stringify(payload)});
    if (result.ok) { setAccountStatus('Connection successful', result.data.message || 'IMAP/SMTP credentials validated.', 'ok'); toast('Connection OK', result.data.message || 'Mailbox reachable.', 'ok'); }
    else if (result.status === 404) { setAccountStatus('Test not available', 'Use Auto Detect or Save & Start Sync to validate.', 'warn'); }
    else { setAccountStatus('Connection failed', msgFromError(result.error), 'bad'); toast('Connection test failed', msgFromError(result.error), 'bad'); }
  }

  async function saveAccount(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const payload = accountPayload(form);
    if (!payload.email || !payload.email.includes('@')) return setAccountStatus('Valid email required', 'Enter a valid mailbox address.', 'warn');
    if (oauthFamily(payload.provider) && payload.connection_method === 'oauth') { await startOAuthFlow(payload.provider, payload.email); return; }
    const submit = form.querySelector('button[type="submit"]');
    if (submit) { submit.disabled = true; submit.textContent = 'Saving...'; }
    setAccountStatus('Saving account', 'Encrypting credentials and creating account record...', 'loading');
    const result = await api('/api/v1/accounts', {method:'POST', body:JSON.stringify(payload)});
    if (submit) { submit.disabled = false; submit.textContent = 'Save & Start Sync'; }
    if (result.ok) {
      const account = result.data.account || {};
      const good = result.data.ok !== false && result.data.status !== 'saved_needs_repair';
      setAccountStatus(good ? 'Account connected' : 'Account saved but needs repair', result.data.message || `${account.email || payload.email} is persisted.`, good ? 'ok' : 'warn');
      toast(good ? 'Account connected' : 'Repair required', result.data.message || 'Account state saved.', good ? 'ok' : 'warn');
      form.password.value = '';
      await loadAccounts(); await loadDashboard();
      if (good && account.id) { await startAccountSync(account.id, false); await finishAccountSetup(account.id); }
      return;
    }
    const err = result.error || {};
    const status = typeof err === 'object' ? err.status : '';
    if (status === 'oauth_required' || result.status === 409) {
      const rawStart = err.oauth_start_url || oauthStartUrl(payload.provider);
      const start = String(rawStart || '');
      setAccountStatus('OAuth sign-in required', 'Opening the provider sign-in flow.', 'warn');
      if (start && (start.startsWith('/') || start.startsWith('https://'))) window.open(`${start}?email=${encodeURIComponent(payload.email)}`, '_blank', 'noopener');
      toast('OAuth required', 'Complete sign-in in the provider window, then return to Accounts.', 'warn');
      return;
    }
    if (status === 'provider_setup_required' || result.status === 428) { setAccountStatus('Provider OAuth setup required', msgFromError(err), 'warn'); renderOAuthSetupPanel(payload.provider, msgFromError(err)); toast('Provider setup required', 'Save OAuth credentials or enter an app password.', 'warn'); return; }
    setAccountStatus('Account not saved', msgFromError(err), 'bad');
    toast('Account save failed', msgFromError(err), 'bad');
  }

  async function finishAccountSetup(accountId) {
    await loadDashboard();
    const strip = document.querySelector('.onboarding-strip');
    if (strip) Array.from(strip.children).forEach((s, i) => s.classList.toggle('active', i <= 1));
  }

  function renderAccounts() {
    const list = $('accountList');
    if (!list) return;
    if (!state.accounts.length) { list.innerHTML = '<div class="account-item"><div><b>No accounts connected</b><small>Add a mailbox above to start sync. Accounts are never removed automatically.</small></div><span class="badge warn">Action required</span></div>'; return; }
    list.innerHTML = state.accounts.map(a => {
      const meta = typeof a.metadata === 'string' ? safeJson(a.metadata, {}) : (a.metadata || {});
      const status = a.status || 'connected';
      const paused = status === 'paused';
      const reconnect = a.reconnect_state && a.reconnect_state !== 'ok' && a.reconnect_state !== 'active' ? ` - ${a.reconnect_state}` : '';
      const badge = status === 'connected' ? 'ok' : status === 'paused' ? 'warn' : 'bad';
      const auth = a.auth_type || meta.auth_type || (oauthFamily(a.provider) ? 'oauth' : 'manual');
      const syncState = a.sync_status || meta.sync_status || status;
      return `<div class="account-item" id="account-row-${esc(a.id)}">
        <div><b>${esc(a.email)}</b><small>${esc(a.provider)} - ${esc(auth)} - ${esc(syncState)}${esc(reconnect)} - every ${esc(meta.sync_interval || 20)}s</small></div>
        <div class="account-actions">
          <button class="btn sm" data-sync="${esc(a.id)}" type="button">Sync</button>
          <button class="btn sm" data-edit-account="${esc(a.id)}" type="button">Edit</button>
          ${paused ? `<button class="btn sm" data-resume="${esc(a.id)}" type="button">Resume</button>` : `<button class="btn sm" data-pause="${esc(a.id)}" type="button">Pause</button>`}
          <button class="btn sm" data-reconnect="${esc(a.id)}" type="button">Reconnect</button>
          <button class="btn sm danger" data-remove="${esc(a.id)}" type="button">Remove</button>
          <span class="badge ${badge}">${esc(status)}</span>
        </div>
        <div class="account-edit-panel is-hidden" id="edit-panel-${esc(a.id)}">
          <form class="form-grid" id="edit-form-${esc(a.id)}">
            <label>New Password / App Password<input name="password" type="password" placeholder="Leave blank to keep current" /></label>
            <label>IMAP Host<input name="imap_host" value="${esc(meta.imap_host || '')}" placeholder="imap.example.com" /></label>
            <label>IMAP Port<input name="imap_port" type="number" value="${esc(meta.imap_port || 993)}" /></label>
            <label>SMTP Host<input name="smtp_host" value="${esc(meta.smtp_host || '')}" placeholder="smtp.example.com" /></label>
            <label>SMTP Port<input name="smtp_port" type="number" value="${esc(meta.smtp_port || 465)}" /></label>
            <label>Sync Interval<select name="sync_interval"><option value="20" ${(meta.sync_interval||20)==20?'selected':''}>Every 20 seconds</option><option value="30" ${(meta.sync_interval||20)==30?'selected':''}>Every 30 seconds</option><option value="60" ${(meta.sync_interval||20)==60?'selected':''}>Every 60 seconds</option></select></label>
            <label class="check wide"><input name="ssl" type="checkbox" ${meta.security!=='starttls'?'checked':''} /> Use SSL / TLS</label>
            <div class="form-actions wide"><button class="btn primary" type="submit">Save Changes</button><button class="btn" data-cancel-edit="${esc(a.id)}" type="button">Cancel</button></div>
          </form>
        </div>
      </div>`;
    }).join('');
    state.accounts.forEach(a => {
      $(`edit-form-${a.id}`)?.addEventListener('submit', e => { e.preventDefault(); saveAccountEdit(a.id, e.currentTarget); });
    });
  }

  async function pauseAccount(id) {
    const result = await api(`/api/v1/accounts/${id}/pause`, {method:'POST'});
    toast(result.ok ? 'Sync paused' : 'Pause failed', result.ok ? 'Account will not sync until resumed.' : msgFromError(result.error), result.ok ? 'warn' : 'bad');
    await loadAccounts();
  }

  async function resumeAccount(id) {
    const result = await api(`/api/v1/accounts/${id}/resume`, {method:'POST'});
    toast(result.ok ? 'Sync resumed' : 'Resume failed', result.ok ? 'Account is active again.' : msgFromError(result.error), result.ok ? 'ok' : 'bad');
    await loadAccounts();
  }

  function toggleAccountEdit(id) {
    const panel = $(`edit-panel-${id}`);
    if (panel) panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
  }

  async function saveAccountEdit(id, form) {
    const fd = new FormData(form);
    const payload = {};
    const pw = fd.get('password'); if (pw) payload.password = pw;
    const ih = fd.get('imap_host'); if (ih) payload.imap_host = ih;
    const ip = fd.get('imap_port'); if (ip) payload.imap_port = Number(ip);
    const sh = fd.get('smtp_host'); if (sh) payload.smtp_host = sh;
    const sp = fd.get('smtp_port'); if (sp) payload.smtp_port = Number(sp);
    const si = fd.get('sync_interval'); if (si) payload.sync_interval = Number(si);
    payload.ssl = fd.get('ssl') === 'on';
    const submit = form.querySelector('button[type="submit"]');
    if (submit) { submit.disabled = true; submit.textContent = 'Saving...'; }
    const result = await api(`/api/v1/accounts/${id}`, {method:'PUT', body:JSON.stringify(payload)});
    if (submit) { submit.disabled = false; submit.textContent = 'Save Changes'; }
    if (result.ok) { toast('Account updated', 'Settings saved.', 'ok'); await loadAccounts(); }
    else toast('Update failed', msgFromError(result.error), 'bad');
  }

  async function loadAccounts() {
    const result = await api('/api/v1/accounts');
    state.accounts = result.ok ? (result.data.accounts || []) : [];
    renderAccounts();
  }

  async function startAccountSync(id, showToast = true) {
    const result = await api('/api/v1/sync/start', {method:'POST', body:JSON.stringify({account_id:Number(id), max_results:50})});
    if (showToast) toast(result.ok ? 'Sync started' : 'Sync not started', result.ok ? 'Background sync is queued.' : msgFromError(result.error), result.ok ? 'ok' : 'warn');
    await loadAccounts();
  }

  async function refreshInboxSync() {
    const mailboxId = $('ruleMailboxSelect')?.value || selectedMailboxId();
    const button = $('refreshInboxBtn');
    const original = button?.innerHTML;
    if (button) { button.disabled = true; button.textContent = 'Refreshing...'; }
    const result = mailboxId
      ? await api(`/api/v1/mailboxes/${encodeURIComponent(mailboxId)}/sync`, {method:'POST'})
      : await api('/api/v1/sync/all', {method:'POST'});
    if (button) { button.disabled = false; button.innerHTML = original || 'Refresh'; }
    toast(
      result.ok ? 'Inbox refreshed' : 'Refresh failed',
      result.ok ? (mailboxId ? 'Selected mailbox synced.' : 'Enabled mailboxes synced.') : msgFromError(result.error),
      result.ok ? 'ok' : 'bad'
    );
    await loadAccounts();
    await loadInbox();
  }

  async function reconnectAccount(id) {
    const account = state.accounts.find(a => String(a.id) === String(id));
    const start = oauthStartUrl(account?.provider || '');
    if (start) { await startOAuthFlow(account?.provider || '', account?.email || ''); return; }
    toast('Reconnect required', 'Edit the account password / app password in Accounts and save again.', 'warn');
  }

  async function removeAccount(id) {
    if (!confirm('Remove this account? Accounts are never removed automatically.')) return;
    const result = await api(`/api/v1/accounts/${id}`, {method:'DELETE'});
    toast(result.ok ? 'Account removed' : 'Remove failed', result.ok ? 'Manual removal completed.' : msgFromError(result.error), result.ok ? 'ok' : 'bad');
    await loadAccounts(); await loadDashboard();
  }

  // -- Dashboard ---------------------------------------------------------------
  function renderMetrics(data = {}) {
    const m = data.metrics || {};
    const failedSyncs   = m.failed_syncs ?? 0;
    const unread        = m.unread       ?? 0;
    const queued        = m.queued       ?? 0;
    const automations   = m.automations  ?? state.rules.filter(r => r.enabled !== false).length;
    const inboxHealth   = m.inbox_health ?? '96%';
    const accounts      = m.accounts     ?? state.accounts.length;

    const items = [
      { label: 'Connected Accounts', val: accounts,   sub: 'Persistent mailboxes',        cls: '' },
      { label: 'Inbox Health',        val: inboxHealth, sub: 'Unread and failed sync score', cls: String(inboxHealth).replace('%','') >= 90 ? 'ok' : String(inboxHealth).replace('%','') >= 70 ? 'warn' : 'bad' },
      { label: 'Unread Emails',       val: unread,     sub: 'Needs attention',              cls: unread > 10 ? 'warn' : '' },
      { label: 'Queued Emails',       val: queued,     sub: 'Awaiting processing',          cls: queued > 50 ? 'warn' : '' },
      { label: 'Failed Syncs',        val: failedSyncs, sub: 'Reconnect required',          cls: failedSyncs > 0 ? 'bad' : '' },
      { label: 'Active Automations',  val: automations, sub: 'Rules enabled',               cls: automations > 0 ? 'ok' : '' },
    ];
    if ($('operationsMetrics')) $('operationsMetrics').innerHTML = items.map(({ label, val, sub, cls }) =>
      `<div class="dash-stat-row" role="listitem">
        <div>
          <div class="dash-stat-label">${esc(label)}</div>
          <div class="dash-stat-sub">${esc(sub)}</div>
        </div>
        <strong class="dash-stat-val${cls ? ' ' + cls : ''}">${esc(String(val))}</strong>
      </div>`
    ).join('');
  }

  function renderPerformance(data = {}) {
    const rows = data.performance || [{name:'Emails processed',value:96},{name:'Automation success',value:95},{name:'AI confidence',value:94},{name:'Sync uptime',value:99},{name:'Forwarding reliability',value:96}];
    if ($('performanceList')) $('performanceList').innerHTML = rows.map(r =>
      `<div class="progress-row"><div class="progress-row-fill"><b>${esc(r.name)}</b><div class="progress-track"><div class="progress-fill" data-progress="${Math.max(0,Number(r.value)||0)}"></div></div></div><strong>${esc(r.value)}%</strong></div>`
    ).join('');
    applyDynamicVisuals($('performanceList'));
  }

  function renderActivity(data = {}) {
    const rows = data.activity || [{title:'Sync ready',detail:'Background sync is configured for active accounts',status:'Ready'},{title:'Rules controlled',detail:'Forwarding and categorization run only from saved rules',status:'Controlled'},{title:'AI ready',detail:'Classification and extraction are available',status:'Ready'}];
    if ($('activityList')) $('activityList').innerHTML = rows.map(x =>
      `<div class="activity-item" role="listitem"><div><b>${esc(x.title)}</b><small>${esc(x.detail)}</small></div><span class="badge ok">${esc(x.status)}</span></div>`
    ).join('');
    const notes = data.notifications || [{title:'No critical alerts',detail:'Operations are running normally',level:'ok'}];
    if ($('notificationList')) $('notificationList').innerHTML = notes.map(n =>
      `<div class="notification-item" role="listitem"><div><b>${esc(n.title)}</b><small>${esc(n.detail)}</small></div><span class="badge ${n.level==='bad'?'bad':n.level==='warn'?'warn':'ok'}">${esc(n.level||'ok')}</span></div>`
    ).join('');
  }

  async function loadDashboard() {
    const result = await api('/api/v1/operations/overview');
    const data = result.ok ? result.data : {};
    renderMetrics(data); renderPerformance(data); renderActivity(data);
    const sync = data.sync || {};
    if ($('syncPillText')) $('syncPillText').textContent = sync.status || 'Ready';
    if ($('sideSyncInterval')) $('sideSyncInterval').textContent = `${sync.interval || 20}s`;
    _loadDashIntelStrip();
  }

  async function _loadDashIntelStrip() {
    const strip = $('dashIntelStrip');
    if (!strip) return;

    const r = await api('/api/v1/telemetry/summary');
    if (!r.ok) return;

    const d = r.data;
    const scoreTone = s => s >= 80 ? 'ok' : s >= 60 ? 'accent' : s >= 40 ? 'warn' : 'danger';
    const metrics = d.metrics || [];

    const cards = [
      `<button class="telemetry-action-card" data-open-view="command" type="button">
        <div class="telemetry-card-value ${scoreTone(d.health_score)}">${d.health_score}</div>
        <strong>Platform Health</strong>
        <span>${esc(d.health_status)}</span>
      </button>`,
      ...metrics.map(m => {
        const tone = m.alert ? 'danger' : (m.trend === 'up' && !m.alert ? 'ok' : 'accent');
        const view = m.id === 'active_threats' ? 'security' : m.id === 'workflow_success' ? 'workflows' : 'command';
        return `<button class="telemetry-action-card" data-open-view="${view}" type="button">
          <div class="telemetry-card-value ${tone}">${m.value}${esc(m.unit || '')}</div>
          <strong>${esc(m.label)}</strong>
          <span>${m.alert ? 'Needs attention' : (m.trend === 'up' ? 'Trending up' : 'Nominal')}</span>
        </button>`;
      }),
    ];

    strip.innerHTML = cards.join('');
    strip.querySelectorAll('[data-open-view]').forEach(btn => {
      btn.addEventListener('click', () => showView(btn.dataset.openView));
    });
  }

  // -- OCR Engine ---------------------------------------------------------------

  let _ocrFile       = null;   // selected file for single scan
  let _ocrLastResult = null;   // last scan result (for copy/download)
  let _ocrBatchFiles = [];     // batch file list
  let _ocrReady      = false;  // setup runs exactly once
  let _ocrEmails     = [];     // cached email list to avoid large data-attributes

  function initOCRView() {
    if (_ocrReady) {
      // Re-entry: just reload the active tab's data
      const activeTab = document.querySelector('.ocr-tab.active')?.dataset?.ocrTab;
      if (activeTab === 'history') _loadOcrHistory();
      if (activeTab === 'email')   _loadOcrEmails();
      return;
    }
    _ocrReady = true;
    _setupOcrTabs();
    _setupDropZone();
    _setupBatchZone();
    _loadOcrHistory();
  }

  function _setupOcrTabs() {
    $$('.ocr-tab').forEach(tab => {
      tab.addEventListener('click', () => {
        const id = tab.dataset.ocrTab;
        $$('.ocr-tab').forEach(t => { t.classList.remove('active'); t.setAttribute('aria-selected', 'false'); });
        $$('.ocr-panel').forEach(p => p.classList.remove('active'));
        tab.classList.add('active');
        tab.setAttribute('aria-selected', 'true');
        const panel = document.getElementById(`ocrTab-${id}`);
        if (panel) panel.classList.add('active');
        if (id === 'history') _loadOcrHistory();
        if (id === 'email')   _loadOcrEmails();
      });
    });
    $('ocrRefreshEmailsBtn')?.addEventListener('click', _loadOcrEmails);
    $('ocrClearHistoryBtn')?.addEventListener('click', async () => {
      await api('/api/v1/ocr/history', { method: 'DELETE' });
      toast('Cleared', 'OCR history cleared.', 'ok');
      _loadOcrHistory();
    });
  }

  function _setupDropZone() {
    const zone  = $('ocrDropZone');
    const input = $('ocrFileInput');
    const btn   = $('ocrScanBtn');
    if (!zone || !input || !btn) return;

    // Open file picker on zone click (stop propagation to prevent double-fire)
    zone.addEventListener('click', e => { if (e.target !== input) input.click(); });
    zone.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); } });

    zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('drag-over'); });
    zone.addEventListener('dragleave', e => { if (!zone.contains(e.relatedTarget)) zone.classList.remove('drag-over'); });
    zone.addEventListener('drop', e => {
      e.preventDefault();
      zone.classList.remove('drag-over');
      const f = e.dataTransfer.files[0];
      if (f) _setOcrFile(f);
    });

    input.addEventListener('change', () => {
      if (input.files && input.files[0]) _setOcrFile(input.files[0]);
    });

    btn.addEventListener('click', _runOcrScan);

    $('ocrCopyBtn')?.addEventListener('click', () => {
      if (!_ocrLastResult?.raw_text) return;
      navigator.clipboard.writeText(_ocrLastResult.raw_text)
        .then(() => toast('Copied', 'Text copied to clipboard.', 'ok'));
    });
    $('ocrDownloadBtn')?.addEventListener('click', () => {
      if (!_ocrLastResult) return;
      _downloadJson(_ocrLastResult, _ocrLastResult.filename || 'ocr-result');
    });
  }

  function _setOcrFile(file) {
    _ocrFile = file;
    const info = $('ocrFileInfo');
    const btn  = $('ocrScanBtn');
    if (info) { info.classList.remove('hidden'); info.textContent = `${file.name}  Â·  ${(file.size / 1024).toFixed(1)} KB`; }
    if (btn)  btn.disabled = false;
  }

  async function _runOcrScan() {
    if (!_ocrFile) { toast('No file', 'Select or drop a file first.', 'error'); return; }
    const btn  = $('ocrScanBtn');
    const mode = document.querySelector('input[name="ocrMode"]:checked')?.value || 'auto';

    if (btn) { btn.disabled = true; btn.textContent = 'Scanning...'; }
    _renderResult($('ocrResultBody'), null, 'loading');

    const fd = new FormData();
    fd.append('file', _ocrFile);
    fd.append('mode', mode);

    try {
      const res  = await fetch('/api/v1/ocr/scan', { method: 'POST', credentials: 'same-origin', body: fd });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `Server error ${res.status}`);
      _ocrLastResult = data;
      _renderResult($('ocrResultBody'), data);
      const cb = $('ocrCopyBtn'); if (cb) cb.hidden = false;
      const db = $('ocrDownloadBtn'); if (db) db.hidden = false;
    } catch (err) {
      _renderResult($('ocrResultBody'), null, 'error', err.message);
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = `<svg width="13" height="13" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2">
          <rect x="2" y="3" width="16" height="12" rx="1"/><path d="M5 7h6M5 10h4"/></svg> Scan Document`;
      }
    }
  }

  function _renderResult(el, data, state = 'done', errMsg = '') {
    if (!el) return;
    if (state === 'loading') {
      el.innerHTML = '<div class="ocr-result-loading"><div class="spinner" aria-hidden="true"></div><p>Extracting text...</p></div>';
      return;
    }
    if (state === 'error') {
      el.innerHTML = `<div class="ocr-result-error">
        <p>Scan failed</p>
        <p class="ocr-result-muted">${esc(errMsg || 'Unknown error')}</p>
      </div>`;
      return;
    }
    if (!data) return;

    const fields    = data.fields || {};
    const fieldKeys = Object.keys(fields).filter(k => !k.startsWith('_'));
    const dtype     = fields._detected_type || data.mode || 'document';

    el.innerHTML = `
      <div class="ocr-result-meta">
        <span class="ocr-result-chip">${esc(dtype)}</span>
        <span class="ocr-result-muted">${data.page_count || 1} page(s)</span>
        <span class="ocr-result-muted">${data.word_count || 0} words</span>
        <span class="ocr-result-muted">${esc(data.filename || '')}</span>
      </div>
      ${fieldKeys.length ? `
        <h3 class="ocr-result-section-title">Extracted Fields</h3>
        <table class="ocr-result-table">
          <tbody>${fieldKeys.map(k => `<tr>
            <td class="ocr-result-key">${esc(k.replace(/_/g, ' '))}</td>
            <td class="ocr-result-value">${esc(String(fields[k]))}</td>
          </tr>`).join('')}</tbody>
        </table>` : '<p class="ocr-result-muted">No structured fields detected.</p>'}
      <h3 class="ocr-result-section-title">Raw Text</h3>
      <pre class="ocr-result-raw">${esc((data.raw_text || '').substring(0, 15000))}</pre>`;
  }

  async function _loadOcrEmails() {
    const list = $('ocrEmailList');
    if (!list) return;
    list.innerHTML = '<div class="empty-state"><div class="spinner"></div></div>';

    const res = await api('/api/v1/emails?limit=50');
    _ocrEmails = (res.ok && Array.isArray(res.data?.emails)) ? res.data.emails : [];

    if (!_ocrEmails.length) {
      list.innerHTML = `<div class="empty-state ocr-table-state">
        <p>No emails loaded</p>
        <p class="ocr-table-muted">Connect a mailbox account first, or use the Scan Document tab.</p>
      </div>`;
      return;
    }

    list.innerHTML = `<table class="ocr-data-table">
      <thead><tr>
        <th>Subject</th>
        <th>From</th>
        <th>Category</th>
        <th></th>
      </tr></thead>
      <tbody>${_ocrEmails.map((e, i) => `<tr>
        <td class="ocr-table-text" title="${esc(e.subject||'')}">${esc(e.subject || '(no subject)')}</td>
        <td class="ocr-table-muted">${esc(e.sender || e.sender_email || '')}</td>
        <td>${esc(e.category || '-')}</td>
        <td class="ocr-table-actions"><button class="btn sm ocr-email-scan-btn" type="button" data-ocr-idx="${i}">Scan</button></td>
      </tr>`).join('')}</tbody>
    </table>`;

    list.removeEventListener('click', _ocrEmailListClick);
    list.addEventListener('click', _ocrEmailListClick);
  }

  function _ocrEmailListClick(e) {
    const btn = e.target.closest('[data-ocr-idx]');
    if (!btn) return;
    e.stopPropagation();
    const em = _ocrEmails[Number(btn.dataset.ocrIdx)];
    if (!em) return;
    _scanEmailContent({
      subject:   em.subject   || '',
      sender:    em.sender    || em.sender_email || '',
      body_text: em.body_text || em.ai_summary   || '',
      body_html: em.body_html || '',
    });
  }

  async function _scanEmailContent(payload) {
    const resultPanel = $('ocrEmailResultPanel');
    const resultBody  = $('ocrEmailResultBody');
    const resultTitle = $('ocrEmailResultTitle');
    if (!resultPanel || !resultBody) return;

    resultPanel.hidden = false;
    if (resultTitle) resultTitle.textContent = payload.subject || 'Email Scan';
    _renderResult(resultBody, null, 'loading');
    resultPanel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

    try {
      const res  = await fetch('/api/v1/ocr/scan-email', {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `Server error ${res.status}`);
      _ocrLastResult = data;
      _renderResult(resultBody, data);
      const copyBtn = $('ocrEmailCopyBtn');
      if (copyBtn) {
        const newBtn = copyBtn.cloneNode(true); // remove old listeners
        copyBtn.replaceWith(newBtn);
        newBtn.addEventListener('click', () => {
          navigator.clipboard.writeText(data.raw_text || '').then(() => toast('Copied', '', 'ok'));
        });
      }
    } catch (err) {
      _renderResult(resultBody, null, 'error', err.message);
    }
  }

  async function _loadOcrHistory() {
    const list = $('ocrHistoryList');
    if (!list) return;
    list.innerHTML = '<div class="empty-state"><div class="spinner"></div></div>';

    const res  = await api('/api/v1/ocr/history?limit=50');
    const jobs = res.ok ? (res.data?.jobs || []) : [];

    if (!jobs.length) {
      list.innerHTML = '<div class="empty-state ocr-table-state"><p>No scans yet</p><p class="ocr-table-muted">Upload a document or scan an email to get started.</p></div>';
      return;
    }

    list.innerHTML = `<table class="ocr-data-table">
      <thead><tr>
        <th>File / Email</th>
        <th>Mode</th>
        <th>Words</th>
        <th>Scanned</th>
        <th></th>
      </tr></thead>
      <tbody>${jobs.map(j => `<tr>
        <td class="ocr-table-text">${esc(j.filename||'-')}</td>
        <td class="ocr-table-muted">${esc(j.mode||'auto')}</td>
        <td>${j.word_count||0}</td>
        <td class="ocr-table-muted">${j.created_at ? new Date(j.created_at).toLocaleString('en-GB',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'}) : '-'}</td>
        <td class="ocr-table-actions">
          <button class="btn sm" type="button" data-hview="${esc(j.id)}">View</button>
          <button class="btn sm btn-danger-text" type="button" data-hdel="${esc(j.id)}">Delete</button>
        </td>
      </tr>`).join('')}</tbody>
    </table>`;

    list.querySelectorAll('[data-hview]').forEach(btn => btn.addEventListener('click', async () => {
      const r = await api(`/api/v1/ocr/result/${btn.dataset.hview}`);
      if (r.ok) { _ocrLastResult = r.data; _showOcrModal(r.data); }
      else toast('Error', 'Could not load result.', 'error');
    }));
    list.querySelectorAll('[data-hdel]').forEach(btn => btn.addEventListener('click', async () => {
      await api(`/api/v1/ocr/history/${btn.dataset.hdel}`, { method: 'DELETE' });
      _loadOcrHistory();
    }));
  }

  function _showOcrModal(data) {
    document.querySelectorAll('.modal-overlay').forEach(m => m.remove());
    const wrap = document.createElement('div');
    wrap.className = 'modal-overlay';
    wrap.innerHTML = `
      <div class="ocr-modal">
        <div class="ocr-modal-head">
          <strong class="ocr-modal-title">${esc(data.filename || 'OCR Result')}</strong>
          <button class="btn sm" type="button" id="_ocrMCopy">Copy Text</button>
          <button class="btn sm primary" type="button" id="_ocrMDl">Download JSON</button>
          <button class="ocr-modal-close" type="button" id="_ocrMClose" aria-label="Close">x</button>
        </div>
        <div class="ocr-modal-body" id="_ocrMBody"></div>
      </div>`;
    document.body.appendChild(wrap);
    _renderResult(document.getElementById('_ocrMBody'), data);
    document.getElementById('_ocrMClose').onclick = () => wrap.remove();
    document.getElementById('_ocrMCopy').onclick  = () => { navigator.clipboard.writeText(data.raw_text||''); toast('Copied','','ok'); };
    document.getElementById('_ocrMDl').onclick    = () => _downloadJson(data, data.filename || 'ocr');
    wrap.addEventListener('click', e => { if (e.target === wrap) wrap.remove(); });
  }

  function _downloadJson(obj, name) {
    const blob = new Blob([JSON.stringify(obj, null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = name.replace(/[^a-z0-9_\-\.]/gi, '_') + '.json';
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  }

  function _setupBatchZone() {
    const zone     = $('batchDropZone');
    const input    = $('batchFileInput');
    const runBtn   = $('batchRunBtn');
    const clearBtn = $('batchClearBtn');
    if (!zone || !input) return;

    zone.addEventListener('click', e => { if (e.target !== input) input.click(); });
    zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('drag-over'); });
    zone.addEventListener('dragleave', e => { if (!zone.contains(e.relatedTarget)) zone.classList.remove('drag-over'); });
    zone.addEventListener('drop', e => { e.preventDefault(); zone.classList.remove('drag-over'); _addBatch(Array.from(e.dataTransfer.files)); });
    input.addEventListener('change', () => _addBatch(Array.from(input.files)));
    runBtn?.addEventListener('click', _runBatch);
    clearBtn?.addEventListener('click', () => { _ocrBatchFiles = []; _renderBatchList(); });
  }

  function _addBatch(files) {
    files.slice(0, 20 - _ocrBatchFiles.length).forEach(f => {
      if (!_ocrBatchFiles.find(x => x.name === f.name && x.size === f.size)) _ocrBatchFiles.push(f);
    });
    _renderBatchList();
  }

  function _renderBatchList() {
    const list   = $('batchFileList');
    const runBtn = $('batchRunBtn');
    if (!list) return;
    if (!_ocrBatchFiles.length) { list.innerHTML = ''; if (runBtn) runBtn.disabled = true; return; }
    if (runBtn) runBtn.disabled = false;
    list.innerHTML = _ocrBatchFiles.map((f, i) => `
      <div class="ocr-batch-file">
        <svg width="12" height="12" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 4h8l4 4v8a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1z"/><path d="M12 4v4h4"/></svg>
        <span class="ocr-batch-file-name">${esc(f.name)}</span>
        <span class="ocr-batch-file-size">${(f.size / 1024).toFixed(1)} KB</span>
        <button class="ocr-batch-remove" type="button" data-brm="${i}" aria-label="Remove file">x</button>
      </div>`).join('');
    list.querySelectorAll('[data-brm]').forEach(btn => btn.addEventListener('click', () => {
      _ocrBatchFiles.splice(Number(btn.dataset.brm), 1); _renderBatchList();
    }));
  }

  async function _runBatch() {
    const out    = $('batchResults');
    const runBtn = $('batchRunBtn');
    if (!out || !_ocrBatchFiles.length) return;
    runBtn.disabled = true; runBtn.textContent = 'Processing...';
    out.innerHTML = `<div class="empty-state ocr-batch-results"><div class="spinner"></div><p>Processing ${_ocrBatchFiles.length} file(s)...</p></div>`;

    const results = [];
    for (let i = 0; i < _ocrBatchFiles.length; i++) {
      const f = _ocrBatchFiles[i];
      runBtn.textContent = `Processing ${i + 1}/${_ocrBatchFiles.length}...`;
      const fd = new FormData();
      fd.append('file', f); fd.append('mode', 'auto');
      try {
        const res  = await fetch('/api/v1/ocr/scan', { method: 'POST', credentials: 'same-origin', body: fd });
        const data = await res.json().catch(() => ({}));
        results.push({ name: f.name, ok: res.ok, data: res.ok ? data : null, err: res.ok ? null : (data.detail || 'Failed') });
      } catch (e) { results.push({ name: f.name, ok: false, data: null, err: e.message }); }
    }

    out.innerHTML = `<div class="ocr-batch-summary">Batch complete - ${results.filter(r=>r.ok).length}/${results.length} succeeded</div>
      ${results.map(r => `
        <div class="ocr-batch-card">
          <div class="ocr-batch-card-head">
            <span class="ocr-batch-status ${r.ok ? 'ocr-batch-status--ok' : 'ocr-batch-status--error'}">${r.ok ? 'OK' : 'Error'}</span>
            <span class="ocr-batch-file-name">${esc(r.name)}</span>
            ${r.ok ? `<span class="ocr-table-muted">${r.data.word_count||0} words</span>
              <button class="btn sm" data-bc="${esc(r.data.job_id)}">Copy</button>
              <button class="btn sm" data-bd="${esc(r.data.job_id)}">JSON</button>` : `<span class="ocr-batch-status--error">${esc(r.err||'')}</span>`}
          </div>
          ${r.ok && r.data ? `<div class="ocr-batch-fields">
            ${Object.entries(r.data.fields||{}).filter(([k])=>!k.startsWith('_')).slice(0,6).map(([k,v])=>`
              <span class="ocr-batch-field"><b>${esc(k.replace(/_/g,' '))}:</b> ${esc(String(v))}</span>`).join('')}
          </div>` : ''}
        </div>`).join('')}`;

    out.querySelectorAll('[data-bc]').forEach(btn => btn.addEventListener('click', async () => {
      const r = await api(`/api/v1/ocr/result/${btn.dataset.bc}`);
      if (r.ok) navigator.clipboard.writeText(r.data.raw_text||'').then(() => toast('Copied','','ok'));
    }));
    out.querySelectorAll('[data-bd]').forEach(btn => btn.addEventListener('click', async () => {
      const r = await api(`/api/v1/ocr/result/${btn.dataset.bd}`);
      if (r.ok) _downloadJson(r.data, r.data.filename || btn.dataset.bd);
    }));

    runBtn.disabled = false; runBtn.textContent = 'Run Batch OCR';
  }

  async function loadCertification() {
    const result = await api('/api/v1/enterprise/certification');
    const data = result.ok ? result.data : {};
    const card = $('certificationCard');
    if (!card) return;
    const score = data.overall_score || data.score || 100;
    const span = card.querySelector('span');
    if (span) span.textContent = `Production governance score ${score}%. Runtime checks are available under Settings > Advanced.`;
  }

  // -- Inbox -------------------------------------------------------------------
  function seedEmails() {
    return [
      {id:1,subject:'RFQ for Mumbai to Dubai shipment',sender:'Apex Imports',sender_email:'rfq@apex.example',category:'RFQ',priority:'Critical',folder:'INBOX',labels:'RFQ,Logistics',is_read:0,ai_summary:'Buyer requested freight pricing, sailing options and document timeline.',body_text:'Please quote for LCL shipment from Mumbai to Dubai.',attachments:[{filename:'shipment-rfq.pdf',content_type:'application/pdf',size:184320,download_url:'#'}]},
      {id:2,subject:'Invoice INV-2041 payment follow-up',sender:'Finance Desk',sender_email:'finance@example.com',category:'Invoice',priority:'High',folder:'Finance',labels:'Invoice,Payment',is_read:1,ai_summary:'Invoice follow-up needs confirmation and expected payment date.',body_text:'Kindly confirm payment status.'},
      {id:3,subject:'Support request for mailbox sync',sender:'Operations',sender_email:'ops@example.com',category:'Support',priority:'Medium',folder:'Support',labels:'Support',is_read:0,ai_summary:'Mailbox sync delay requires reconnect guidance.',body_text:'Mailbox sync appears delayed.'}
    ];
  }

  function providerLabel(provider) {
    const key = String(provider || '').toLowerCase();
    return PROVIDER_DEFAULTS[key]?.label || (key ? key.replace(/[_-]+/g, ' ').replace(/\b\w/g, ch => ch.toUpperCase()) : '');
  }

  function accountLabel(account) {
    if (!account) return '';
    const provider = providerLabel(account.provider || account.oauth_provider || '');
    return `${account.email || account.email_address || 'Mailbox'}${provider ? ` (${provider})` : ''}`;
  }

  function selectedMailboxId() {
    const value = $('accountFilter')?.value || state.selectedMailboxId || '';
    return value ? String(value) : '';
  }

  function selectedMailbox() {
    const id = selectedMailboxId();
    return id ? state.accounts.find(a => String(a.id) === id) : null;
  }

  async function loadMailboxBuckets(mailboxId) {
    state.folders = [];
    state.labels = [];
    if (!mailboxId) return;
    const [folders, labels] = await Promise.all([
      api(`/api/v1/mailboxes/${encodeURIComponent(mailboxId)}/folders`),
      api(`/api/v1/mailboxes/${encodeURIComponent(mailboxId)}/labels`)
    ]);
    state.folders = folders.ok ? (folders.data.folders || []) : [];
    state.labels = labels.ok ? (labels.data.labels || []) : [];
  }

  async function loadInbox() {
    if (!state.accounts.length) await loadAccounts();
    state.selectedMailboxId = selectedMailboxId();
    await loadMailboxBuckets(state.selectedMailboxId);
    const params = new URLSearchParams({limit: '50'});
    const folder = $('folderFilter')?.value || '';
    const label  = $('labelFilter')?.value || '';
    if (state.selectedMailboxId) params.set('mailbox_id', state.selectedMailboxId);
    if (folder) params.set('folder', folder);
    if (label)  params.set('label', label);
    if (state.savedFilter === 'unread') params.set('unread', 'true');
    const result = await api(`/api/v1/inbox?${params}`);
    state.emails = result.ok && Array.isArray(result.data.emails) ? result.data.emails : [];
    if (!result.ok) toast('Inbox not loaded', msgFromError(result.error), 'warn');
    populateInboxFilters(); renderInbox();
  }

  function populateInboxFilters() {
    const accountFilter = $('accountFilter');
    if (accountFilter) {
      const current = state.selectedMailboxId || accountFilter.value || '';
      accountFilter.innerHTML = '<option value="">All accounts</option>' + state.accounts.map(account =>
        `<option value="${esc(account.id)}" ${String(account.id) === String(current) ? 'selected' : ''}>${esc(accountLabel(account))}</option>`
      ).join('');
      accountFilter.value = current && state.accounts.some(a => String(a.id) === String(current)) ? current : '';
      state.selectedMailboxId = accountFilter.value;
    }

    const mailbox = selectedMailbox();
    const hint = $('mailboxFilterHint');
    if (hint) hint.textContent = mailbox
      ? `Showing folders and labels for ${mailbox.email || mailbox.email_address}.`
      : 'Showing all connected mailboxes.';

    const folderSelect = $('folderFilter');
    const labelSelect = $('labelFilter');
    const currentFolder = folderSelect?.value || '';
    const currentLabel = labelSelect?.value || '';
    if (folderSelect) {
      const folderOptions = state.selectedMailboxId
        ? state.folders.map(x => `<option value="${esc(x.name)}" ${x.name === currentFolder ? 'selected' : ''}>${esc(x.name)}</option>`).join('')
        : '<option value="" disabled>Select an account to view folders</option>';
      folderSelect.innerHTML = '<option value="">All folders</option>' + folderOptions;
      if (currentFolder && state.folders.some(x => x.name === currentFolder)) folderSelect.value = currentFolder;
    }
    if (labelSelect) {
      const labelOptions = state.selectedMailboxId
        ? state.labels.map(x => `<option value="${esc(x.name)}" ${x.name === currentLabel ? 'selected' : ''}>${esc(x.name)}</option>`).join('')
        : '<option value="" disabled>Select an account to view labels</option>';
      labelSelect.innerHTML = '<option value="">All labels</option>' + labelOptions;
      if (currentLabel && state.labels.some(x => x.name === currentLabel)) labelSelect.value = currentLabel;
    }
    populateFilterChips();
  }

  function populateFilterChips() {
    const container = $('filterChips');
    if (!container) return;

    // Build dynamic chips from the actual email data the client has
    const categories = [...new Set(state.emails.map(e => e.category).filter(Boolean))];
    const folders    = [...new Set(state.emails.map(e => e.folder).filter(Boolean).filter(f => !['INBOX','inbox'].includes(f)))];

    const active = state.savedFilter || 'all';

    const staticChips = [
      `<button class="filter-chip ${active==='all'?'active':''}" data-filter="all" type="button">All</button>`,
      `<button class="filter-chip ${active==='unread'?'active':''}" data-filter="unread" type="button">Unread</button>`,
      `<button class="filter-chip ${active==='scam'?'active':''}" data-filter="scam" type="button">Scam</button>`,
    ];

    // One chip per distinct category found in the client's emails
    const catChips = categories.map(cat => {
      const key = 'cat_' + cat.toLowerCase().replace(/[^a-z0-9]+/g,'_');
      return `<button class="filter-chip ${active===key?'active':''}" data-filter="${esc(key)}"
        data-filter-type="category" data-filter-value="${esc(cat)}" type="button">${esc(cat)}</button>`;
    });

    // One chip per non-INBOX folder
    const folderChips = folders.map(folder => {
      const key = 'fol_' + folder.toLowerCase().replace(/[^a-z0-9]+/g,'_');
      return `<button class="filter-chip ${active===key?'active':''}" data-filter="${esc(key)}"
        data-filter-type="folder" data-filter-value="${esc(folder)}" type="button">${esc(folder)}</button>`;
    });

    container.innerHTML = [...staticChips, ...catChips, ...folderChips].join('');
  }

  function renderInbox() {
    const term   = $('globalSearch')?.value?.toLowerCase() || '';
    const folder = $('folderFilter')?.value || '';
    const label  = $('labelFilter')?.value  || '';
    let rows = state.emails.filter(e =>
      (!folder || e.folder === folder) &&
      (!label  || labelsForEmail(e).includes(label)) &&
      (!term   || [e.sender,e.sender_email,e.subject,e.category,e.priority,e.folder,labelsForEmail(e).join(' '),e.email_address,e.provider].join(' ').toLowerCase().includes(term))
    );
    // Static filters
    if (state.savedFilter === 'unread')   rows = rows.filter(e => !e.is_read);
    if (state.savedFilter === 'priority') rows = rows.filter(e => ['Critical','High'].includes(e.priority));
    if (state.savedFilter === 'rfq')      rows = rows.filter(e => String(e.category||e.subject).toLowerCase().includes('rfq'));
    if (state.savedFilter === 'scam')     rows = rows.filter(e => String(e.category||'').toLowerCase() === 'scam' || String(e.folder||'').toLowerCase() === 'scam' || String(e.labels||'').toLowerCase().includes('scam'));
    // Dynamic filters from populated chips (category/folder based on client's actual data)
    if (!['all','unread','priority','rfq','scam'].includes(state.savedFilter) && state.savedFilter) {
      const activeChip = $$('.filter-chip').find(b => b.dataset.filter === state.savedFilter);
      if (activeChip?.dataset.filterType === 'category') {
        const val = activeChip.dataset.filterValue;
        rows = rows.filter(e => (e.category||'').toLowerCase() === val.toLowerCase());
      } else if (activeChip?.dataset.filterType === 'folder') {
        const val = activeChip.dataset.filterValue;
        rows = rows.filter(e => (e.folder||'').toLowerCase() === val.toLowerCase());
      }
    }
    const emptyState = emptyStateForInbox(rows.length);
    const emptyTitle = emptyState.title;
    const emptyBody  = emptyState.body;
    if ($('inboxRows')) $('inboxRows').innerHTML = rows.length
      ? rows.map(e => {
          const sel = state.selectedEmails.has(String(e.id));
          const active = state.selectedEmail?.id === e.id;
          const sourceEmail = e.email_address || e.account_email || e.source?.email_address || 'Unknown account';
          const provider = providerLabel(e.provider || e.source?.provider || '');
          const labelBadges = labelsForEmail(e).slice(0, 2).map(x => `<span class="badge neutral">${esc(x)}</span>`).join('');
          // Checkbox is outside the button so clicking it never triggers email-open
          return `<div class="thread-row-wrap ${active?'active':''} ${sel?'selected-row':''}" data-wrap-id="${esc(e.id)}">`
            + `<label class="thread-row-cb" aria-label="Select email">`
            +   `<input type="checkbox" class="email-cb" data-cb-id="${esc(e.id)}" ${sel?'checked':''}>`
            + `</label>`
            + `<button class="thread-row" data-email-id="${esc(e.id)}" type="button" role="listitem">`
            +   `<span class="${e.is_read?'read-dot':'unread-dot'}"></span>`
            +   `<span>`
            +     `<span class="thread-subject">${esc(e.subject||'(No subject)')}</span>`
            +     `<span class="thread-meta">From: ${esc(e.sender||e.sender_email||'Unknown sender')}</span>`
            +     `<span class="thread-meta">Account: ${esc(sourceEmail)}${provider ? ` - Provider: ${esc(provider)}` : ''}</span>`
            +     `<span class="thread-summary">${esc((e.ai_summary||e.snippet||e.body_text||'').slice(0,140))}</span>`
            +     `<span class="thread-tags"><span class="badge">${esc(e.priority||'Medium')}</span><span class="badge ok">${esc(e.folder||'INBOX')}</span>${labelBadges}</span>`
            +   `</span>`
            +   `<span aria-hidden="true">&rsaquo;</span>`
            + `</button>`
            + `</div>`;
        }).join('')
      : renderThreadEmptyState(emptyTitle, emptyBody);
    if (!rows.length) {
      state.selectedEmail = null;
      renderEmptyPreview(emptyTitle, emptyBody);
      return;
    }
    if (!state.selectedEmail || !rows.some(e => String(e.id) === String(state.selectedEmail.id))) state.selectedEmail = rows[0];
    renderPreview(state.selectedEmail);
  }

  function labelsForEmail(email) {
    const raw = email?.labels ?? email?.label_names ?? [];
    if (Array.isArray(raw)) return raw.map(x => String(x).trim()).filter(Boolean);
    const text = String(raw || '').trim();
    if (!text) return [];
    try {
      const parsed = JSON.parse(text);
      if (Array.isArray(parsed)) return parsed.map(x => String(x).trim()).filter(Boolean);
    } catch {}
    return text.replace(/[\[\]"]/g,'').split(',').map(x => x.trim()).filter(Boolean);
  }

  function toggleEmailSelect(id, checked) {
    const sid = String(id);
    if (checked) state.selectedEmails.add(sid); else state.selectedEmails.delete(sid);
    // Toggle on the wrap div, not the button, so no re-render needed
    const wrap = document.querySelector(`[data-wrap-id="${sid}"]`);
    if (wrap) wrap.classList.toggle('selected-row', checked);
    updateBulkBar();
  }

  function updateBulkBar() {
    const bar = $('bulkBar');
    if (!bar) return;
    const count = state.selectedEmails.size;
    if (count > 0) {
      bar.classList.remove('hidden');
      const el = $('bulkCount');
      if (el) el.textContent = `${count} selected`;
    } else {
      bar.classList.add('hidden');
    }
  }

  function toggleSelectAll() {
    const term   = $('globalSearch')?.value?.toLowerCase() || '';
    const folder = $('folderFilter')?.value || '';
    const label  = $('labelFilter')?.value  || '';
    const visible = state.emails.filter(e =>
      (!folder || e.folder === folder) &&
      (!label  || labelsForEmail(e).includes(label)) &&
      (!term   || [e.sender,e.sender_email,e.subject,e.category,e.priority,e.folder,labelsForEmail(e).join(' '),e.email_address,e.provider].join(' ').toLowerCase().includes(term))
    );
    const allSelected = visible.length > 0 && visible.every(e => state.selectedEmails.has(String(e.id)));
    if (allSelected) {
      visible.forEach(e => state.selectedEmails.delete(String(e.id)));
    } else {
      visible.forEach(e => state.selectedEmails.add(String(e.id)));
    }
    // Update wrap classes without full re-render
    document.querySelectorAll('[data-wrap-id]').forEach(wrap => {
      const id = wrap.dataset.wrapId;
      const checked = state.selectedEmails.has(id);
      wrap.classList.toggle('selected-row', checked);
      const cb = wrap.querySelector('.email-cb');
      if (cb) cb.checked = checked;
    });
    updateBulkBar();
  }

  async function executeBulkAction(action) {
    const ids = [...state.selectedEmails];
    if (!ids.length) return;
    if (action === 'archive') {
      state.emails = state.emails.map(e => ids.includes(String(e.id)) ? {...e, folder:'Archive', is_read:1} : e);
      state.selectedEmails.clear(); updateBulkBar(); renderInbox();
      toast('Archived', `${ids.length} email(s) archived.`, 'ok');
      ids.forEach(id => api(`/api/v1/email/${id}/archive`, {method:'POST'}).catch(()=>{}));
    } else if (action === 'markRead') {
      state.emails = state.emails.map(e => ids.includes(String(e.id)) ? {...e, is_read:1} : e);
      state.selectedEmails.clear(); updateBulkBar(); renderInbox();
      toast('Marked read', `${ids.length} email(s) marked as read.`, 'ok');
    } else if (action === 'label') {
      showInlineInput($('bulkBar'), 'Add label', 'Label name...', '', async lbl => {
        if (!lbl) return;
        state.selectedEmails.clear(); updateBulkBar();
        toast('Label applied', `"${lbl}" applied to ${ids.length} email(s).`, 'ok');
        for (const id of ids) await api(`/api/v1/email/${id}/label`, {method:'POST', body:JSON.stringify({label:lbl})}).catch(()=>{});
        loadInbox();
      });
    } else if (action === 'move') {
      showInlineInput($('bulkBar'), 'Move to folder', 'Folder name...', $('folderFilter')?.value || 'INBOX', async fld => {
        if (!fld) return;
        state.selectedEmails.clear(); updateBulkBar();
        toast('Moved', `${ids.length} email(s) moved to "${fld}".`, 'ok');
        for (const id of ids) await api(`/api/v1/email/${id}/move`, {method:'POST', body:JSON.stringify({folder:fld})}).catch(()=>{});
        loadInbox();
      });
    }
  }

  // -- AI Analysis -------------------------------------------------------------
  function filterLabel(filter) {
    const chip = $$('.filter-chip').find(btn => btn.dataset.filter === filter);
    const label = chip?.textContent?.trim() || String(filter || '').replace(/[-_]+/g, ' ');
    return label.replace(/\s+/g, ' ').trim() || 'filtered';
  }

  function emptyStateForFilter(filter) {
    if (!filter || filter === 'all') return {title:'No conversations found', body:'Connect an account or adjust filters.'};
    if (filter === 'scam') return {title:'No scam conversations', body:'Messages marked or detected as scams will appear here.'};
    const label = filterLabel(filter);
    return {title:`No ${label} conversations`, body:'Messages matching this filter will appear here.'};
  }

  function emptyStateForInbox(rowCount) {
    if (rowCount) return emptyStateForFilter(state.savedFilter);
    if (!state.accounts.length) {
      return {title:'Connect a mailbox to see conversations.', body:'Add Gmail, Outlook, Yahoo, Zoho, Yandex, or IMAP accounts from Accounts.'};
    }
    const scoped = selectedMailbox();
    const relevant = scoped ? [scoped] : state.accounts;
    const failed = relevant.find(a => a.last_error || ['degraded', 'needs_reconnect'].includes(String(a.status || '').toLowerCase()));
    if (failed) {
      return {
        title:'Mailbox sync failed.',
        body:`${failed.email || failed.email_address || 'Selected account'} needs attention. ${failed.last_error || 'Reconnect or refresh this mailbox.'}`,
      };
    }
    const hasSynced = relevant.some(a => a.last_sync_at);
    if (!hasSynced) {
      return {title:'Mailbox connected. Start sync to load emails.', body:'Use Refresh to sync the selected account or all enabled accounts.'};
    }
    return {title:'No conversations found for this filter.', body:'Adjust the account, folder, label, unread, or search filters.'};
  }

  function renderThreadEmptyState(title, body) {
    return `<div class="thread-empty-state"><b>${esc(title)}</b><small>${esc(body)}</small></div>`;
  }

  function renderEmptyPreview(title = 'Select a conversation', body = 'AI summary, thread context, labels, folders and actions appear here.') {
    if (!$('messagePreview')) return;
    $('messagePreview').innerHTML = `<div class="preview-empty"><svg width="44" height="44" viewBox="0 0 44 44" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true"><rect x="4" y="6" width="36" height="32" rx="3"/><path d="M4 14l18 12 18-12"/></svg><strong>${esc(title)}</strong><p>${esc(body)}</p></div>`;
  }

  function renderPreview(e) {
    if (!e || !$('messagePreview')) return;
    const labelBadges = labelsForEmail(e).slice(0,3).map(x=>`<span class="badge ok">${esc(x.trim())}</span>`).join('');
    const isScam = String(e.category||'').toLowerCase() === 'scam';
    const sourceEmail = e.email_address || e.account_email || e.source?.email_address || 'Unknown account';
    const provider = providerLabel(e.provider || e.source?.provider || '');
    $('messagePreview').innerHTML = `<h2>${esc(e.subject||'Conversation')}</h2><p>${esc(e.sender||e.sender_email||'Unknown sender')} - ${esc(e.category||'Unclassified')}</p><p class="preview-source">Account: ${esc(sourceEmail)}${provider ? ` - Provider: ${esc(provider)}` : ''}</p><div class="preview-actions"><button class="btn" type="button" data-email-action="reply" data-email-action-id="${esc(e.id)}">Reply</button><button class="btn" type="button" data-email-action="forward" data-email-action-id="${esc(e.id)}">Forward</button><button class="btn" type="button" data-email-action="assign" data-email-action-id="${esc(e.id)}">Assign</button><button class="btn" type="button" data-email-action="label" data-email-action-id="${esc(e.id)}">Label</button><button class="btn" type="button" data-email-action="move" data-email-action-id="${esc(e.id)}">Move</button><button class="btn" type="button" data-email-action="archive" data-email-action-id="${esc(e.id)}">Archive</button></div><div class="scam-flow ${isScam?'active':''}"><div><strong>Scam filter</strong><span>${isScam?'This sender is currently treated as scam.':'Decide how future email from this sender should be handled.'}</span></div><div class="verdict-actions"><button class="btn danger sm" data-email-category-id="${esc(e.id)}" data-email-category="Scam" type="button">Mark Scam</button><button class="btn sm" data-email-category-id="${esc(e.id)}" data-email-category="Normal" type="button">Mark Normal</button></div><small>Future emails from this sender will follow this decision.</small></div><h3>AI Summary</h3><p>${esc(e.ai_summary||'No summary yet.')}</p><h3>Thread</h3><p class="preview-message-body">${esc((e.body_text||'No body preview.').slice(0,4000))}</p>${renderAttachments(e)}<div class="thread-tags"><span class="badge">${esc(e.priority||'Medium')}</span><span class="badge ok">${esc(e.folder||'INBOX')}</span>${labelBadges}</div>`;
  }

  async function applyEmailVerdict(emailId, category) {
    if (!emailId || !category) return;
    const result = await api('/api/v1/scam-filter/verdict', {method:'POST', body:JSON.stringify({email_id:Number(emailId), category, user_id:0})});
    if (!result.ok) return toast('Scam filter update failed', msgFromError(result.error), 'bad');
    const nextFolder = category === 'Scam' ? 'Scam' : 'INBOX';
    const nextPriority = category === 'Scam' ? 'Critical' : 'Medium';
    state.emails = state.emails.map(item => {
      if (String(item.id) !== String(emailId)) return item;
      const labels = String(item.labels || '').includes(category) ? item.labels : `${item.labels || ''}${item.labels ? ',' : ''}${category}`;
      return {...item, category, folder: nextFolder, priority: nextPriority, labels};
    });
    state.selectedEmail = state.emails.find(item => String(item.id) === String(emailId)) || state.selectedEmail;
    if (category === 'Normal' && state.savedFilter === 'scam') {
      $$('.filter-chip').forEach(b => b.classList.remove('active'));
      const allChip = $$('.filter-chip').find(b => !b.dataset.filter || b.dataset.filter === 'all');
      if (allChip) allChip.classList.add('active');
      state.savedFilter = 'all';
    }
    renderInbox();
    const msg = category === 'Normal'
      ? 'Email moved to Inbox. Future emails from this sender will be treated as normal.'
      : 'Future emails from this sender will be flagged as scam.';
    toast('Scam filter updated', msg, 'ok');
  }

  function openMailtoLink(href) {
    const a = document.createElement('a');
    a.href = href;
    a.style.display = 'none';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }

  function showInlineInput(anchorEl, title, placeholder, defaultVal, onSubmit) {
    let existing = document.getElementById('inlineActionForm');
    if (existing) existing.remove();
    const form = document.createElement('div');
    form.id = 'inlineActionForm';
    form.style.cssText = 'display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin-top:8px;padding:8px;background:var(--surface,#f8f8f8);border:1px solid var(--border,#e0e0e0);border-radius:6px;';
    form.innerHTML = `<span style="font-size:13px;font-weight:600">${esc(title)}:</span><input id="inlineActionInput" type="text" placeholder="${esc(placeholder)}" value="${esc(defaultVal)}" style="flex:1;min-width:120px;padding:4px 8px;border:1px solid var(--border,#ccc);border-radius:4px;font-size:13px;" /><button type="button" id="inlineActionOk" class="btn sm">Apply</button><button type="button" id="inlineActionCancel" class="btn sm">Cancel</button>`;
    const preview = document.getElementById('messagePreview');
    if (preview) preview.appendChild(form); else if (anchorEl?.parentNode) anchorEl.parentNode.insertAdjacentElement('afterend', form);
    const input = document.getElementById('inlineActionInput');
    input?.focus(); input?.select();
    const submit = () => { const v = input?.value?.trim(); form.remove(); if (v) onSubmit(v); };
    document.getElementById('inlineActionOk')?.addEventListener('click', submit);
    document.getElementById('inlineActionCancel')?.addEventListener('click', () => form.remove());
    input?.addEventListener('keydown', ev => { if (ev.key === 'Enter') submit(); if (ev.key === 'Escape') form.remove(); });
  }

  async function handleEmailAction(action, emailId) {
    const email = state.emails.find(e => String(e.id) === String(emailId));
    if (!email && action !== 'assign') return;
    const btn = document.querySelector(`[data-email-action="${esc(action)}"][data-email-action-id="${esc(emailId)}"]`);
    if (action === 'reply') {
      const to = encodeURIComponent(email.sender_email || '');
      const subject = encodeURIComponent(`Re: ${email.subject || ''}`);
      openMailtoLink(`mailto:${to}?subject=${subject}`);
      toast('Reply', `Opening mail client to reply to ${email.sender || email.sender_email || 'sender'}.`, 'info');
    } else if (action === 'forward') {
      const subject = encodeURIComponent(`Fwd: ${email.subject || ''}`);
      const body = encodeURIComponent(`\n\n--- Forwarded message ---\nFrom: ${email.sender || email.sender_email || ''}\nSubject: ${email.subject || ''}\n\n${(email.body_text || '').slice(0, 2000)}`);
      openMailtoLink(`mailto:?subject=${subject}&body=${body}`);
      toast('Forward', 'Opening mail client to forward this email.', 'info');
    } else if (action === 'assign') {
      toast('Assign', 'Assignment queues are configured in the Admin panel under Team Management.', 'info');
    } else if (action === 'label') {
      showInlineInput(btn, 'Add label', 'Label name...', '', async label => {
        const result = await api(`/api/v1/email/${emailId}/label`, {method:'POST', body:JSON.stringify({label})});
        if (!result.ok) { toast('Label failed', msgFromError(result.error), 'bad'); return; }
        state.emails = state.emails.map(item => {
          if (String(item.id) !== String(emailId)) return item;
          const existing = String(item.labels || '');
          const labels = existing.includes(label) ? existing : `${existing}${existing ? ',' : ''}${label}`;
          return {...item, labels};
        });
        state.selectedEmail = state.emails.find(item => String(item.id) === String(emailId)) || state.selectedEmail;
        renderInbox(); renderPreview(state.selectedEmail);
        toast('Label added', `Label "${label}" applied.`, 'ok');
      });
    } else if (action === 'move') {
      showInlineInput(btn, 'Move to folder', 'Folder name...', email.folder || 'INBOX', async folder => {
        const result = await api(`/api/v1/email/${emailId}/move`, {method:'POST', body:JSON.stringify({folder})});
        if (!result.ok) { toast('Move failed', msgFromError(result.error), 'bad'); return; }
        state.emails = state.emails.map(item => String(item.id) === String(emailId) ? {...item, folder} : item);
        state.selectedEmail = state.emails.find(item => String(item.id) === String(emailId)) || state.selectedEmail;
        renderInbox(); renderPreview(state.selectedEmail);
        toast('Email moved', `Moved to "${folder}".`, 'ok');
      });
    } else if (action === 'archive') {
      state.emails = state.emails.map(item => String(item.id) === String(emailId) ? {...item, folder: 'Archive', is_read: 1} : item);
      state.selectedEmail = null;
      renderInbox();
      toast('Archived', 'Email moved to Archive.', 'ok');
      api(`/api/v1/email/${emailId}/archive`, {method:'POST'}).catch(() => {});
    }
  }

  function renderAttachments(email) {
    const attachments = normalizedAttachments(email);
    if (!attachments.length && !email?.has_attachments) return '';
    if (!attachments.length) return '<h3>Attachments</h3><div class="attachment-list"><div class="attachment-empty">Attachments were detected, but download metadata is not available yet. Refresh sync to fetch attachment details.</div></div>';
    return `<h3>Attachments</h3><div class="attachment-list">${attachments.map(item => {
      const name = item.filename || item.name || 'attachment';
      const type = item.content_type || item.mime_type || 'file';
      const href = attachmentDownloadHref(item);
      return `<div class="attachment-item"><div class="attachment-meta"><b>${esc(name)}</b><small>${esc(type)}${item.size ? ` - ${esc(formatBytes(item.size))}` : ''}</small></div><a class="btn sm attachment-download" href="${esc(href)}" download="${esc(name)}">Download</a></div>`;
    }).join('')}</div>`;
  }

  function normalizedAttachments(email) {
    let raw = email?.attachments || [];
    if (typeof raw === 'string') raw = safeJson(raw, []);
    if (!Array.isArray(raw)) raw = [];
    return raw.filter(Boolean);
  }

  function attachmentDownloadHref(item) {
    const safeHref = u => {
      const s = String(u || '');
      if (/^(https?:|data:|\/)/i.test(s)) return s;
      return '#';
    };
    if (item.download_url || item.url || item.href) return safeHref(item.download_url || item.url || item.href);
    if (item.data_url) return safeHref(item.data_url);
    const content = item.content || item.content_bytes || item.base64;
    if (content) return `data:${item.content_type || 'application/octet-stream'};base64,${content}`;
    const id = item.attachment_id || item.id;
    return id ? `/api/v1/attachments/${encodeURIComponent(id)}/download` : '#';
  }

  function formatBytes(value) {
    const bytes = Number(value) || 0;
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1048576) return `${Math.round(bytes / 1024)} KB`;
    return `${(bytes / 1048576).toFixed(1)} MB`;
  }

  async function loadOnnxStatus() {
    const result = await api('/api/v1/ai/onnx/status');
    const status = result.ok ? result.data : {
      status: 'degraded',
      mode: 'fallback',
      runtime_available: false,
      active_model: null,
      learning: {learned_overrides: 0},
      self_healing: {fallback_active: true, events: []}
    };
    state.onnx.status = status;
    renderOnnxStatus(status);
    loadLearningMemory();
    loadLearningAudit();
    loadAiBackups();
  }

  async function loadLearningMemory() {
    if (!$('learningMemoryList')) return;
    const result = await api('/api/v1/ai/learning/overrides');
    renderLearningMemory(result.ok ? result.data : {total: 0, items: []});
  }

  async function loadLearningAudit() {
    if (!$('learningAuditList')) return;
    const result = await api('/api/v1/ai/learning/events');
    renderLearningAudit(result.ok ? result.data : {total: 0, items: []});
  }

  function renderOnnxStatus(status) {
    if (!$('onnxHealthGrid')) return;
    const learning = status.learning || {};
    const healing = status.self_healing || {};
    const quarantined = Array.isArray(healing.quarantined_models) ? healing.quarantined_models : [];
    if ($('onnxRuntimeState')) $('onnxRuntimeState').textContent = status.runtime_available ? 'ONNX Ready' : 'Fallback Ready';
    if ($('onnxModeState')) $('onnxModeState').textContent = healing.fallback_active ? 'Self-healing fallback' : 'ONNX inference';
    if ($('onnxModelState')) $('onnxModelState').textContent = status.active_model || 'Rules fallback';
    if ($('onnxLearningState')) $('onnxLearningState').textContent = `${learning.learned_overrides || 0} rules`;
    $('onnxHealthGrid').dataset.mode = status.mode || 'fallback';
    if ($('onnxRecoveryList')) $('onnxRecoveryList').innerHTML = quarantined.length
      ? quarantined.map(model => `
        <div class="onnx-recovery-item">
          <div>
            <b>${esc(model)}</b>
            <span>Quarantined model can be revalidated after repair.</span>
          </div>
          <button class="btn sm" type="button" data-recover-onnx-model="${esc(model)}">Recover</button>
        </div>`).join('')
      : '<div class="onnx-recovery-empty">No quarantined ONNX models.</div>';
  }

  function renderLearningMemory(memory) {
    const items = Array.isArray(memory.items) ? memory.items : [];
    if (!$('learningMemoryList')) return;
    $('learningMemoryList').innerHTML = items.length
      ? `<div class="learning-memory-title"><b>Learned decisions</b><span>${esc(items.length)} active override(s)</span></div>` + items.map(item => `
        <div class="learning-memory-item">
          <div>
            <b>${esc(item.key)}</b>
            <span>${esc(item.category || 'Unknown')} - ${esc(item.priority || 'Medium')} - ${esc(item.scope || 'sender')} - ${esc(item.hits || 0)} hit(s)</span>
          </div>
          <button class="btn sm" type="button" data-forget-learning-key="${esc(item.key)}">Forget</button>
        </div>`).join('')
      : '<div class="learning-memory-empty">No learned sender or domain decisions yet.</div>';
  }

  function renderLearningAudit(events) {
    const items = Array.isArray(events.items) ? events.items : [];
    if (!$('learningAuditList')) return;
    $('learningAuditList').innerHTML = items.length
      ? `<div class="learning-audit-title"><b>Learning audit</b><span>${esc(events.total || items.length)} retained event(s)</span></div>` + items.slice(0, 6).map(item => `
        <div class="learning-audit-item">
          <b>${esc(item.action || 'learned')}</b>
          <span>${esc(item.key || 'memory')} - ${esc(item.actual_category || 'Unknown')} - ${esc(item.priority || 'Medium')}</span>
        </div>`).join('')
      : '<div class="learning-audit-empty">No learning events yet.</div>';
  }

  async function forgetLearningOverride(key) {
    const result = await api(`/api/v1/ai/learning/overrides/${encodeURIComponent(key)}`, {method:'DELETE'});
    toast(result.ok ? 'Learning forgotten' : 'Learning not changed', result.ok ? `${key} will use normal classification again.` : msgFromError(result.error), result.ok ? 'ok' : 'warn');
    loadLearningMemory();
    loadLearningAudit();
    loadOnnxStatus();
  }

  async function exportLearningMemory() {
    const result = await api('/api/v1/ai/learning/export');
    if (!result.ok) {
      toast('Learning export failed', msgFromError(result.error), 'warn');
      return;
    }
    const text = JSON.stringify(result.data, null, 2);
    if ($('learningImportText')) $('learningImportText').value = text;
    state.onnx.learningImportPreview = null;
    renderLearningImportPreview(null);
    toast('Learning memory exported', 'The JSON backup is ready in the import box.', 'ok');
  }

  function parseLearningImportPayload() {
    try {
      const raw = ($('learningImportText')?.value || '').trim();
      if (!raw) return {ok:false, message:'Paste a learning memory JSON export first.'};
      const payload = JSON.parse(raw);
      if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
        return {ok:false, message:'Learning memory import must be a JSON object.'};
      }
      return {ok:true, payload};
    } catch {
      return {ok:false, message:'Paste a valid learning memory JSON export.'};
    }
  }

  function renderLearningImportPreview(preview) {
    const el = $('learningImportPreview');
    if (!el) return;
    if (!preview) {
      el.className = 'learning-import-preview';
      el.textContent = 'Preview an import to review new decisions, conflicts, invalid rows, and replace impact before applying it.';
      return;
    }
    const conflicts = Array.isArray(preview.conflicts) ? preview.conflicts : [];
    const invalid = Array.isArray(preview.invalid_items) ? preview.invalid_items : [];
    const removed = Array.isArray(preview.removed_keys) ? preview.removed_keys : [];
    const tone = preview.status === 'review_required' ? 'review-required' : 'ready';
    const conflictRows = conflicts.slice(0, 5).map(item => `
      <div class="learning-import-conflict">
        <b>${esc(item.key)}</b>
        <span>Current: ${esc(item.existing?.category || 'Unknown')} / ${esc(item.existing?.priority || 'Medium')}</span>
        <span>Incoming: ${esc(item.incoming?.category || 'Unknown')} / ${esc(item.incoming?.priority || 'Medium')}</span>
      </div>`).join('');
    const invalidRows = invalid.slice(0, 5).map(item => `<span class="badge warn">${esc(item.key || 'invalid row')}</span>`).join('');
    const removedRows = removed.slice(0, 5).map(key => `<span class="badge warn">${esc(key)}</span>`).join('');
    el.className = `learning-import-preview ${tone}`;
    el.innerHTML = `
      <div class="learning-import-summary">
        <b>${preview.status === 'review_required' ? 'Review required before import' : 'Import preview ready'}</b>
        <span>${esc(preview.total_incoming || 0)} incoming - ${esc(preview.new_count || 0)} new - ${esc(preview.conflict_count || 0)} conflict(s) - ${esc(preview.invalid_count || 0)} invalid</span>
      </div>
      ${conflictRows ? `<div class="learning-import-conflicts">${conflictRows}</div>` : ''}
      ${invalidRows ? `<div class="learning-import-badges"><b>Invalid rows</b>${invalidRows}</div>` : ''}
      ${removedRows ? `<div class="learning-import-badges"><b>Replace removes</b>${removedRows}</div>` : ''}
      <div class="learning-import-actions">
        <button class="btn sm" type="button" data-learning-import-merge>Merge Import</button>
        <button class="btn sm" type="button" data-learning-import-replace>Replace Memory</button>
      </div>`;
  }

  async function previewLearningImport() {
    const parsed = parseLearningImportPayload();
    if (!parsed.ok) {
      toast('Learning preview failed', parsed.message, 'warn');
      return;
    }
    const result = await api('/api/v1/ai/learning/import/preview', {method:'POST', body:JSON.stringify(parsed.payload)});
    if (!result.ok) {
      toast('Learning preview failed', msgFromError(result.error), 'warn');
      return;
    }
    state.onnx.learningImportPreview = result.data;
    renderLearningImportPreview(result.data);
    toast(
      result.data.status === 'review_required' ? 'Learning review required' : 'Learning import ready',
      `${result.data.conflict_count || 0} conflict(s), ${result.data.new_count || 0} new decision(s).`,
      result.data.status === 'review_required' ? 'warn' : 'ok'
    );
  }

  async function importLearningMemory(replace = false) {
    const parsed = parseLearningImportPayload();
    if (!parsed.ok) {
      toast('Learning import failed', parsed.message, 'warn');
      return;
    }
    const payload = {...parsed.payload, replace: Boolean(replace || parsed.payload.replace)};
    const result = await api('/api/v1/ai/learning/import', {method:'POST', body:JSON.stringify(payload)});
    toast(result.ok ? 'Learning memory imported' : 'Learning import failed', result.ok ? `${result.data.imported_overrides || 0} learned decision(s) restored.` : msgFromError(result.error), result.ok ? 'ok' : 'warn');
    if (result.ok) {
      state.onnx.learningImportPreview = null;
      renderLearningImportPreview(null);
      loadOnnxStatus();
      loadLearningMemory();
      loadLearningAudit();
    }
  }

  async function loadAiBackups() {
    if (!$('aiBackupList')) return;
    const result = await api('/api/v1/ai/backups/status');
    renderAiBackups(result.ok ? result.data : {total_backups: 0, backups: [], schedule: {}});
  }

  function renderAiBackups(data) {
    const el = $('aiBackupList');
    if (!el) return;
    const backups = Array.isArray(data.backups) ? data.backups : [];
    const schedule = data.schedule || {};
    if ($('aiBackupInterval') && schedule.interval_seconds) {
      $('aiBackupInterval').value = String(schedule.interval_seconds);
    }
    const rows = backups.slice(0, 5).map(item => `
      <div class="ai-backup-item">
        <div>
          <b>${esc(item.backup_id || 'AI backup')}</b>
          <span>${esc(item.reason || 'manual')} - ${esc(new Date((item.created_at || 0) * 1000).toLocaleString())}</span>
        </div>
        <button class="btn sm" type="button" data-restore-ai-backup="${esc(item.backup_id || '')}">Restore</button>
      </div>`).join('');
    el.innerHTML = `
      <div class="ai-backup-status">
        <span>${schedule.enabled === false ? 'Scheduled backups paused' : 'Scheduled backups enabled'}</span>
        <span>${esc(backups.length)} retained backup(s)</span>
      </div>
      ${rows || '<div class="ai-backup-empty">No AI state backups yet.</div>'}`;
  }

  async function backupAiState() {
    const result = await api('/api/v1/ai/backups/run', {method:'POST', body:JSON.stringify({})});
    toast(result.ok ? 'AI backup created' : 'AI backup failed', result.ok ? `${result.data.backup_id} is available for restore.` : msgFromError(result.error), result.ok ? 'ok' : 'warn');
    if (result.ok) loadAiBackups();
  }

  async function saveAiBackupSchedule() {
    const interval = Number($('aiBackupInterval')?.value || 86400);
    const result = await api('/api/v1/ai/backups/schedule', {
      method:'POST',
      body:JSON.stringify({enabled:true, interval_seconds:interval, retention:7})
    });
    toast(result.ok ? 'AI backup schedule saved' : 'Backup schedule failed', result.ok ? 'Learning, model registry and healing logs are covered.' : msgFromError(result.error), result.ok ? 'ok' : 'warn');
    if (result.ok) loadAiBackups();
  }

  async function restoreAiStateBackup(backupId) {
    if (!backupId) return;
    const result = await api(`/api/v1/ai/backups/${encodeURIComponent(backupId)}/restore`, {method:'POST', body:JSON.stringify({})});
    toast(result.ok ? 'AI state restored' : 'AI restore failed', result.ok ? `${backupId} restored learning and model state.` : msgFromError(result.error), result.ok ? 'ok' : 'warn');
    if (result.ok) {
      loadOnnxStatus();
      loadLearningMemory();
      loadLearningAudit();
      loadAiBackups();
    }
  }

  async function recoverOnnxModel(modelName) {
    const result = await api(`/api/v1/ai/self-healing/models/${encodeURIComponent(modelName)}/recover`, {method:'POST'});
    toast(result.ok ? 'Model recovery complete' : 'Model recovery failed', result.ok ? `Active model: ${result.data.active_model || 'fallback rules'}` : msgFromError(result.error), result.ok ? 'ok' : 'warn');
    loadOnnxStatus();
  }

  function renderEntityGroups(entities) {
    if (!entities) return '';
    if (Array.isArray(entities)) return entities.map(x => `<span class="badge ok">${esc(x)}</span>`).join('');
    return Object.entries(entities).flatMap(([name, values]) => {
      const items = Array.isArray(values) ? values : [];
      return items.slice(0, 6).map(value => `<span class="badge ok">${esc(name)}: ${esc(value)}</span>`);
    }).join('');
  }

  function renderOnnxAnalysis(classification, analysis = {}) {
    const healing = classification.self_healing || {};
    const model = classification.model || {};
    const learning = classification.learning || {};
    const entityTags = renderEntityGroups(analysis.entities);
    if ($('analysisResult')) $('analysisResult').innerHTML = `
      <div class="ai-result-summary">
        <div>
          <span>Category</span>
          <strong>${esc(classification.category || analysis.classification || 'Classified')}</strong>
        </div>
        <div>
          <span>Confidence</span>
          <strong>${esc(Math.round(Number(classification.confidence || analysis.confidence || 0) * 100))}%</strong>
        </div>
        <div>
          <span>Priority</span>
          <strong>${esc(classification.priority || analysis.priority || 'Medium')}</strong>
        </div>
      </div>
      <div class="result-group">
        <h4>Runtime</h4>
        <div class="result-val">${esc(model.name || 'rules-fallback')} - ${esc(model.engine || classification.source || 'local')}</div>
        <small>${healing.fallback_active ? 'Self-healing fallback is active.' : 'ONNX model inference is active.'}</small>
      </div>
      <div class="result-group">
        <h4>Learning</h4>
        <div class="result-val">${learning.matched ? `Matched ${esc(learning.matched_key)}` : `${esc(learning.learned_overrides || 0)} learned overrides available`}</div>
      </div>
      <div class="result-group">
        <h4>Entities</h4>
        <div class="entity-tags">${entityTags || '<span class="badge">No entities detected</span>'}</div>
      </div>`;
  }

  async function analyzeEmail(event) {
    event.preventDefault();
    const f = new FormData(event.currentTarget);
    const payload = {subject:f.get('subject'), sender_email:f.get('sender_email'), body:f.get('body')};
    state.onnx.lastPayload = payload;
    if ($('analysisResult')) $('analysisResult').innerHTML = '<div class="empty-state"><h3>Analyzing</h3><p>Running ONNX control plane and extraction.</p></div>';
    const [classificationResult, analysisResult] = await Promise.all([
      api('/api/v1/ai/onnx/classify', {method:'POST', body:JSON.stringify(payload)}),
      api('/api/v1/analysis/email', {method:'POST', body:JSON.stringify(payload)})
    ]);
    const classification = classificationResult.ok ? classificationResult.data : {category:'Personal', confidence:.5, priority:'Medium', source:'local_error', model:{engine:'local_fallback'}, self_healing:{fallback_active:true}, learning:{}};
    const analysis = analysisResult.ok ? analysisResult.data : {};
    state.onnx.lastClassification = classification;
    renderOnnxAnalysis(classification, analysis);
    loadOnnxStatus();
  }

  async function submitLearningFeedback(event) {
    event.preventDefault();
    const f = new FormData(event.currentTarget);
    const payload = {
      ...(state.onnx.lastPayload || {}),
      predicted_category: state.onnx.lastClassification?.category || '',
      actual_category: f.get('actual_category'),
      priority: f.get('priority'),
      scope: f.get('scope')
    };
    const result = await api('/api/v1/ai/learning/feedback', {method:'POST', body:JSON.stringify(payload)});
    toast(result.ok ? 'Learning saved' : 'Learning not saved', result.ok ? 'Future emails matching this sender or domain will use the corrected decision.' : msgFromError(result.error), result.ok ? 'ok' : 'warn');
    if (result.ok) { loadOnnxStatus(); loadLearningMemory(); loadLearningAudit(); }
  }

  // -- Rules / Automations -----------------------------------------------------
  async function loadRules() {
    const result = await api('/api/v1/rules');
    state.rules = result.ok ? (result.data.rules || []) : [];
    renderRules();
  }

  function renderRules() {
    const term   = ($('ruleSearch')?.value || '').toLowerCase();
    const status = $('ruleStatusFilter')?.value || '';
    const rows   = state.rules.filter(r => (!term || String(r.name).toLowerCase().includes(term)) && (!status || String(r.status||'Active').toLowerCase() === status.toLowerCase()));
    if ($('ruleList')) $('ruleList').innerHTML = rows.length
      ? rows.map(r => `<div class="rule-item" role="listitem" data-rule-id="${esc(r.id)}"><div><b>${esc(r.name)}</b><small>${esc(r.status||'Active')} - ${esc(r.mailbox_scope === 'selected' ? 'one mailbox' : 'all mailboxes')} - priority ${esc(r.priority||'Medium')} - executions ${esc(r.execution_count||0)}</small></div><div><button class="btn sm" data-simulate-rule-id="${esc(r.id)}" type="button">Test</button><button class="btn sm" type="button">Pause</button><button class="btn sm" type="button">Duplicate</button><button class="btn sm" type="button">Archive</button></div></div>`).join('')
      : '<div class="rule-item"><div><b>No rules created yet. Create your first automation rule.</b><small>Sample rules are hidden until you load a pack.</small></div><span class="badge warn">Empty</span></div>';
    renderRuleDiagram();
  }

  function renderRuleDiagram() {
    if ($('ruleDiagram')) $('ruleDiagram').innerHTML = ['Analyze','Match','Prioritize','Execute','Log','Report'].map(n => `<span class="workflow-node">${esc(n)}</span>`).join(' -> ');
  }

  function renderWorkflowSteps(steps) {
    return steps.map(step => `<span class="workflow-node">${esc(step)}</span>`).join('<span class="workflow-arrow" aria-hidden="true">&rarr;</span>');
  }

  function renderRuleDiagram() {
    if ($('ruleDiagram')) $('ruleDiagram').innerHTML = renderWorkflowSteps(['Analyze','Match','Prioritize','Execute','Log','Report']);
  }

  async function saveRule(event) {
    event.preventDefault();
    const f = new FormData(event.currentTarget);
    const actionType = f.get('action_type');
    let actionValue = f.get('action_value') || '';
    if (actionType === 'forward_email') actionValue = {to:actionValue.split(',').map(x=>x.trim()).filter(Boolean), subject_prefix:'Fwd:', include_body:true, requires_approval:false};
    const mailboxId = String(f.get('mailbox_id') || '').trim();
    const values = String(f.get('condition_value') || '').split(',').map(x => x.trim()).filter(Boolean);
    const action = {type:actionType, value:actionValue, auto_create_target:f.get('auto_create_target') === 'on', provider_action_required:true};
    if (f.get('target_folder_id')) action.target_folder_id = Number(f.get('target_folder_id'));
    if (f.get('target_label_id')) action.target_label_id = Number(f.get('target_label_id'));
    const payload = {name:f.get('name'), mailbox_scope:mailboxId ? 'selected' : 'all', mailbox_id:mailboxId ? Number(mailboxId) : null, scan_scope:f.get('scan_scope') || 'entire_email_with_attachments', match_mode:f.get('match_mode') || 'any', condition:{type:f.get('condition_type') || 'entire_email_contains', value:values}, actions:[action], priority:f.get('priority'), enabled:f.get('status')==='active', status:f.get('status'), apply_existing:false, exceptions:f.get('exceptions')};
    const result = await api('/api/v1/rules', {method:'POST', body:JSON.stringify(payload)});
    if (result.ok) {
      state.lastRuleId = result.data.rule_id;
      toast('Rule saved', 'Rule is ready. Use Test rule to preview matches or Apply Rules to All to run it.', 'ok');
      loadRules(); loadDashboard(); loadLabelsAndFolders();
    } else toast('Rule not saved', msgFromError(result.error), 'bad');
  }

  function currentRuleFormPayload() {
    const f = new FormData($('ruleForm'));
    const mailboxId = String(f.get('mailbox_id') || '').trim();
    const values = String(f.get('condition_value') || '').split(',').map(x => x.trim()).filter(Boolean);
    const actionType = f.get('action_type');
    let actionValue = f.get('action_value') || '';
    if (actionType === 'forward_email') actionValue = {to:String(actionValue).split(',').map(x=>x.trim()).filter(Boolean), subject_prefix:'Fwd:', include_body:true, requires_approval:false};
    return {name:f.get('name') || 'Untitled rule', mailbox_scope:mailboxId ? 'selected' : 'all', mailbox_id:mailboxId ? Number(mailboxId) : null, scan_scope:f.get('scan_scope') || 'entire_email_with_attachments', match_mode:f.get('match_mode') || 'any', condition:{type:f.get('condition_type') || 'entire_email_contains', value:values}, actions:[{type:actionType, value:actionValue}], priority:f.get('priority') || 'Medium', enabled:true, apply_existing:false};
  }

  function renderSimulationPanel(data, ok = true) {
    const panel = $('ruleSimulationPanel');
    if (!panel) return;
    if (!ok) { panel.innerHTML = `<strong>Simulation failed</strong><p>${esc(data)}</p>`; return; }
    const matches = data.matches || [];
    panel.innerHTML = `<strong>Simulation complete</strong><p>Matched ${esc(data.matched_count || 0)} of ${esc(data.scanned_count || 0)} scanned emails. No messages were modified.</p>${matches.length ? `<ul>${matches.map(m => `<li><b>${esc(m.subject || '(no subject)')}</b><span>${esc(m.matched_source || 'email')} - ${(m.planned_actions || []).map(esc).join(', ')}</span></li>`).join('')}</ul>` : '<p>No conversations found for this filter.</p>'}`;
  }

  async function simulateRule(ruleId = null) {
    let id = ruleId || state.lastRuleId || state.rules?.[0]?.id;
    if (!id) {
      const draft = currentRuleFormPayload();
      if (!draft.name || !draft.condition.value.length) return renderSimulationPanel('Enter a rule name and keyword before testing.', false);
      const saved = await api('/api/v1/rules', {method:'POST', body:JSON.stringify(draft)});
      if (!saved.ok) return renderSimulationPanel(msgFromError(saved.error), false);
      id = saved.data.rule_id;
      state.lastRuleId = id;
      await loadRules();
    }
    const mailboxId = $('ruleMailboxSelect')?.value || selectedMailboxId();
    const payload = {limit:100};
    if (mailboxId) payload.mailbox_id = Number(mailboxId);
    const result = await api(`/api/v1/rules/${encodeURIComponent(id)}/simulate`, {method:'POST', body:JSON.stringify(payload)});
    if ($('ruleTimeline')) $('ruleTimeline').innerHTML = `<div class="timeline-item"><b>Simulation</b><br><small>${esc(result.ok ? `Matched ${result.data.matched_count||0} of ${result.data.scanned_count||0}` : msgFromError(result.error))}</small></div>`;
    if (result.ok) renderSimulationPanel(result.data, true); else renderSimulationPanel(msgFromError(result.error), false);
    toast('Simulation complete', result.ok ? 'No messages were modified.' : msgFromError(result.error), result.ok ? 'ok' : 'warn');
  }

  function duplicateRule() {
    const form = $('ruleForm');
    if (!form) return;
    const nameEl = form.querySelector('[name="name"]');
    if (nameEl) nameEl.value = `${nameEl.value || 'Rule'} (copy)`;
    toast('Rule duplicated', 'Modify the name and click Save Rule.', 'info');
  }

  async function populateRuleMailboxOptions() {
    if (!state.accounts.length) await loadAccounts();
    const select = $('ruleMailboxSelect');
    if (!select) return;
    const current = select.value || '';
    select.innerHTML = '<option value="">All connected mailboxes</option>' + state.accounts.map(account =>
      `<option value="${esc(account.id)}" ${String(account.id) === String(current) ? 'selected' : ''}>${esc(accountLabel(account))}</option>`
    ).join('');
    if (current && state.accounts.some(a => String(a.id) === String(current))) select.value = current;
  }

  async function loadLabelsAndFolders() {
    const ruleMailboxId = $('ruleMailboxSelect')?.value || selectedMailboxId();
    const labelUrl = ruleMailboxId ? `/api/v1/mailboxes/${encodeURIComponent(ruleMailboxId)}/labels` : '/api/v1/rules/labels';
    const folderUrl = ruleMailboxId ? `/api/v1/mailboxes/${encodeURIComponent(ruleMailboxId)}/folders` : '/api/v1/rules/folders';
    const [lr, fr] = await Promise.all([api(labelUrl), api(folderUrl)]);
    const labels  = lr.ok ? (lr.data.labels  || []) : [];
    const folders = fr.ok ? (fr.data.folders || []) : [];
    if ($('labelInventory'))  $('labelInventory').innerHTML  = labels.length  ? labels.map(l  => `<span class="badge ok" role="listitem">${esc(typeof l==='string'?l:(l.name||''))}</span>`).join(' ') : '<span class="empty-muted">Sync folders and labels first.</span>';
    if ($('folderInventory')) $('folderInventory').innerHTML = folders.length ? folders.map(fl => `<span class="badge" role="listitem">${esc(typeof fl==='string'?fl:(fl.name||''))}</span>`).join(' ') : '<span class="empty-muted">Sync folders and labels first.</span>';
    const folderSelect = $('ruleTargetFolder');
    const labelSelect = $('ruleTargetLabel');
    if (folderSelect) folderSelect.innerHTML = '<option value="">Use folder name below</option>' + folders.map(fl => `<option value="${esc(fl.id)}">${esc(fl.name || '')}</option>`).join('');
    if (labelSelect) labelSelect.innerHTML = '<option value="">Use label name below</option>' + labels.map(l => `<option value="${esc(l.id)}">${esc(l.name || '')}</option>`).join('');
  }

  async function scanRuleMailboxStructure() {
    const mailboxId = $('ruleMailboxSelect')?.value || selectedMailboxId();
    if (!mailboxId) return toast('Select an email account first', 'Choose one mailbox before scanning folders and labels.', 'warn');
    const btn = $('scanRuleStructureBtn');
    if (btn) { btn.disabled = true; btn.textContent = 'Scanning folders and labels...'; }
    const result = await api(`/api/v1/mailboxes/${encodeURIComponent(mailboxId)}/sync-structure`, {method:'POST'});
    if (btn) { btn.disabled = false; btn.textContent = 'Scan folders and labels'; }
    toast(result.ok ? 'Folders and labels synced' : 'Folder scan failed', result.ok ? 'Folders and labels synced.' : 'Could not sync folders/labels for this mailbox. Retry.', result.ok ? 'ok' : 'bad');
    await loadMailboxBuckets(mailboxId);
    populateInboxFilters();
    await loadLabelsAndFolders();
  }

  async function createLabel(name) {
    if (!name?.trim()) return toast('Label name required', '', 'warn');
    const mailboxId = $('ruleMailboxSelect')?.value || selectedMailboxId();
    if (!mailboxId) return toast('Select an email account before creating a label.', 'Labels must be created inside one connected mailbox.', 'warn');
    const result = await api(`/api/v1/mailboxes/${encodeURIComponent(mailboxId)}/labels`, {method:'POST', body:JSON.stringify({name:name.trim()})});
    toast(result.ok ? 'Label created' : 'Label not created', result.ok ? (result.data.message || `Label created in ${selectedMailbox()?.email || 'selected mailbox'}`) : msgFromError(result.error), result.ok ? 'ok' : 'bad');
    if (result.ok) { await loadMailboxBuckets(mailboxId); populateInboxFilters(); loadLabelsAndFolders(); }
  }

  async function createFolder(name) {
    if (!name?.trim()) return toast('Folder name required', '', 'warn');
    const mailboxId = selectedMailboxId();
    if (!mailboxId) return toast('Select an email account before creating a folder.', 'Folders must be created inside one connected mailbox.', 'warn');
    const result = await api(`/api/v1/mailboxes/${encodeURIComponent(mailboxId)}/folders`, {method:'POST', body:JSON.stringify({name:name.trim()})});
    toast(result.ok ? 'Folder created' : 'Folder not created', result.ok ? (result.data.message || `Folder created in ${selectedMailbox()?.email || 'selected mailbox'}`) : msgFromError(result.error), result.ok ? 'ok' : 'bad');
    if (result.ok) { await loadMailboxBuckets(mailboxId); populateInboxFilters(); loadLabelsAndFolders(); }
  }

  async function loadPresets() {
    const result = await api('/api/v1/rules/presets');
    const packs = result.ok ? (result.data.presets || []) : [];
    const el = $('presetPacksList');
    if (!el) return;
    if (!packs.length) { el.innerHTML = '<span class="empty-muted-sm">No preset packs available.</span>'; return; }
    el.innerHTML = packs.map(p => `<div class="preset-pack-card" role="listitem"><div class="preset-pack-top"><div><h3>${esc(p.name)}</h3><p>${esc(p.description)}</p></div><span class="badge ok">${esc(p.rule_count)} rules</span></div><div class="preset-pack-meta">${(p.tags||[]).map(t=>`<span class="badge neutral">${esc(t)}</span>`).join('')}</div><div class="preset-pack-actions"><button class="btn primary sm" data-install-preset="${esc(p.id)}" type="button">Install Pack</button><span>Creates ${esc((p.folders||[]).length)} folders and labels</span></div></div>`).join('');
  }

  async function installPreset(presetId, btn) {
    if (btn) { btn.disabled = true; btn.textContent = 'Installing...'; }
    toast('Installing preset', `Installing rules from "${presetId}" pack...`, 'info');
    const result = await api(`/api/v1/rules/presets/${encodeURIComponent(presetId)}`, {method:'POST'});
    if (btn) { btn.disabled = false; btn.textContent = 'Install Pack'; }
    if (result.ok) { const d = result.data; toast(`Pack installed: ${d.preset}`, `${d.installed_count} rule(s) installed, ${d.skipped_count} already existed.`, 'ok'); loadRules(); loadLabelsAndFolders(); loadRuleAnalytics(); }
    else toast('Install failed', msgFromError(result.error), 'bad');
  }

  async function applyRulesToAll() {
    const btn = $('applyRulesBtn');
    if (btn) { btn.disabled = true; btn.textContent = 'Applying...'; }
    toast('Applying rules', 'Scanning all emails and executing matching rules...', 'info');
    const result = await api('/api/v1/rules/apply', {method:'POST', body:JSON.stringify({limit:1000, provider_write:true})});
    if (btn) { btn.disabled = false; btn.textContent = 'Apply Rules to All'; }
    if (result.ok) { const matched = result.data.matched_rules ?? result.data.count ?? 0; const checked = result.data.emails_checked ?? 0; toast('Rules applied', `${matched} action(s) executed across ${checked} email(s).`, 'ok'); loadRuleAnalytics(); loadLabelsAndFolders(); }
    else toast('Apply failed', msgFromError(result.error), 'bad');
  }

  async function loadRuleAnalytics() {
    const result = await api('/api/v1/rules/analytics');
    const data = result.ok ? result.data : {};
    const a = data.analytics || {triggered_rules:0, failed_rules:0, skipped_rules:0, forwarding_statistics:0, categorization_statistics:0};
    if ($('ruleAnalytics')) $('ruleAnalytics').innerHTML = Object.entries(a).map(([k,v]) => `<div class="report-card" role="listitem"><span>${esc(k.replaceAll('_',' '))}</span><strong>${esc(v)}</strong></div>`).join('');
    const timeline = data.timeline || [];
    if ($('ruleTimeline')) $('ruleTimeline').innerHTML = timeline.map(x => `<div class="timeline-item"><b>${esc(x.title)}</b><br><small>${esc(x.detail)}</small></div>`).join('') || '<div class="timeline-item"><b>No executions yet</b><br><small>Rule execution history appears here.</small></div>';
  }

  // -- Templates ---------------------------------------------------------------
  async function loadTemplates() {
    const result = await api('/api/v1/templates');
    state.templates = result.ok ? (result.data.templates || []) : [
      {id:'rfq-routing', name:'RFQ Routing', description:'Forward RFQs to sales/logistics and label as RFQ.', category:'Freight'},
      {id:'invoice-review', name:'Invoice Review', description:'Categorize invoices and assign finance follow-up.', category:'Finance'},
      {id:'support-escalation', name:'Support Escalation', description:'Route support complaints to team queue with priority.', category:'Support'}
    ];
    if ($('templateGrid')) $('templateGrid').innerHTML = state.templates.map(t =>
      `<article class="template-card" role="listitem"><h3>${esc(t.name)}</h3><p>${esc(t.description)}</p><small>${esc(t.category)}</small><br><button class="btn" data-template="${esc(t.id)}" type="button">Use Template</button></article>`
    ).join('');
  }

  async function createTemplate() {
    const name = $('templateNameInput')?.value?.trim();
    const vars = $('templateVarsInput')?.value?.trim();
    if (!name) return toast('Name required', 'Enter a template name.', 'warn');
    const result = await api('/api/v1/templates', {method:'POST', body:JSON.stringify({name, variables:vars||'', category:'Custom', body:''})});
    toast(result.ok ? 'Template created' : 'Template not created', result.ok ? `"${name}" is ready to use.` : msgFromError(result.error), result.ok ? 'ok' : 'bad');
    if (result.ok) { if ($('templateNameInput')) $('templateNameInput').value = ''; if ($('templateVarsInput')) $('templateVarsInput').value = ''; loadTemplates(); }
  }

  // -- Reports -----------------------------------------------------------------
  function fallbackReports() {
    return {
      email: {received:state.emails.length||3, processed:state.emails.length||3, unread:state.emails.filter(e=>!e.is_read).length||2, categorized:state.emails.length||3, forwarded:0, failed:0},
      business: {rfq_trends:1, invoice_volume:1, support_trends:1, freight_inquiries:1, lead_extraction:1},
      ai: {accuracy:'94%', average_confidence:'0.91', processing_time:'<1s'},
      learning: {scam_false_positives:0, scam_false_negatives:0, learning_corrections:0, learned_overrides:0, learning_accuracy:'100%'},
      model_health: {onnx_fallback_rate:'100%', fallback_active:'Yes', active_model:'rules-fallback', quarantined_models:0, runtime:'Fallback'},
      scheduled: [{name:'Daily Operations Report', frequency:'Daily', format:'PDF + CSV'}]
    };
  }

  function reportValues(values) {
    return Object.values(values || {}).map(value => {
      if (typeof value === 'string' && value.trim().endsWith('%')) return Number.parseFloat(value);
      return Number(value);
    });
  }

  function reportNumber(value) {
    if (typeof value === 'string' && value.trim().endsWith('%')) return Number.parseFloat(value);
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : 0;
  }

  function reportLabel(key) {
    return String(key || '').replaceAll('_', ' ').replace(/\b\w/g, c => c.toUpperCase());
  }

  function buildReportSummary(email = {}, business = {}, learning = {}, modelHealth = {}) {
    const received = reportNumber(email.received);
    const processed = reportNumber(email.processed);
    const failed = reportNumber(email.failed);
    const categorized = reportNumber(email.categorized);
    const forwarded = reportNumber(email.forwarded);
    const learningAccuracy = reportNumber(learning.learning_accuracy);
    const fallbackRate = reportNumber(modelHealth.onnx_fallback_rate);
    const businessSignals = Object.values(business).reduce((total, value) => total + reportNumber(value), 0);
    const processRate = received ? Math.min(100, (processed / received) * 100) : (processed ? 100 : 0);
    const categorizedRate = processed ? Math.min(100, (categorized / processed) * 100) : 0;
    const failureRate = processed ? Math.min(100, (failed / processed) * 100) : 0;
    const modelScore = Math.max(0, 100 - fallbackRate);
    const healthScore = Math.round((processRate + categorizedRate + Math.max(0, 100 - failureRate) + learningAccuracy + modelScore) / 5);
    return {
      received,
      processed,
      failed,
      categorized,
      forwarded,
      learningAccuracy,
      fallbackRate,
      businessSignals,
      processRate,
      categorizedRate,
      failureRate,
      modelScore,
      healthScore,
      status: healthScore >= 90 ? 'ready' : healthScore >= 70 ? 'watch' : 'risk',
      runtime: modelHealth.runtime || modelHealth.active_model || 'Runtime',
    };
  }

  function renderReportKpis(summary) {
    const items = [
      {label:'Processed', value:summary.processed, meta:`${Math.round(summary.processRate)}% of received`, tone:'blue'},
      {label:'Categorized', value:summary.categorized, meta:`${Math.round(summary.categorizedRate)}% classified`, tone:'green'},
      {label:'Business Signals', value:summary.businessSignals, meta:'RFQ, invoice, support and freight', tone:'violet'},
      {label:'Learning Accuracy', value:`${Math.round(summary.learningAccuracy)}%`, meta:`${Math.round(summary.fallbackRate)}% fallback`, tone:summary.learningAccuracy >= 90 ? 'green' : 'amber'},
    ];
    const strip = $('reportKpiStrip');
    if (strip) {
      strip.classList.add('report-kpi-strip');
      strip.innerHTML = items.map(item => `
      <div class="report-kpi-card report-kpi-${item.tone}" role="listitem">
        <span>${esc(item.label)}</span>
        <strong>${esc(item.value)}</strong>
        <small>${esc(item.meta)}</small>
      </div>
    `).join('');
    }
  }

  function renderReportInsightPanel(summary) {
    if (!$('reportInsightPanel')) return;
    const insightPanel = $('reportInsightPanel').closest('.panel');
    if (insightPanel) insightPanel.classList.add('report-insight-panel');
    $('reportInsightPanel').innerHTML = `
      <div class="report-signal-status report-signal-${summary.status}">
        <span>Health score</span>
        <strong>${summary.healthScore}%</strong>
      </div>
      <div class="report-signal-bars">
        ${[
          ['Processing', summary.processRate],
          ['Classification', summary.categorizedRate],
          ['Reliability', Math.max(0, 100 - summary.failureRate)],
          ['Learning', summary.learningAccuracy],
          ['Model', summary.modelScore],
        ].map(([label, value]) => `
          <div class="report-signal-row">
            <div><span>${esc(label)}</span><strong>${Math.round(value)}%</strong></div>
            <div class="report-signal-track"><div class="report-signal-fill" data-progress="${Math.round(value)}"></div></div>
          </div>
        `).join('')}
      </div>
      <div class="report-signal-meta">
        <div><span>Runtime</span><strong>${esc(summary.runtime)}</strong></div>
        <div><span>Failures</span><strong>${summary.failed}</strong></div>
      </div>
    `;
    applyDynamicVisuals($('reportInsightPanel'));
  }

  function renderReportPipeline(summary) {
    const max = Math.max(summary.received, summary.processed, summary.categorized, summary.forwarded, 1);
    const stages = [
      ['Received', summary.received],
      ['Processed', summary.processed],
      ['Categorized', summary.categorized],
      ['Forwarded', summary.forwarded],
    ];
    const pipeline = $('reportPipeline');
    if (pipeline) {
      pipeline.classList.add('report-pipeline');
      pipeline.innerHTML = stages.map(([label, value]) => `
      <div class="report-pipeline-card" role="listitem">
        <div><span>${esc(label)}</span><strong>${value}</strong></div>
        <div class="report-pipeline-track"><div class="report-pipeline-fill" data-progress="${Math.round((value / max) * 100)}"></div></div>
      </div>
    `).join('');
      applyDynamicVisuals(pipeline);
    }
  }

  function renderReportCards(id, values) {
    if ($(id)) $(id).innerHTML = Object.entries(values || {}).map(([k,v]) => `
      <div class="report-card report-card-modern" role="listitem">
        <span>${esc(reportLabel(k))}</span>
        <strong>${esc(v)}</strong>
      </div>
    `).join('');
  }

  function renderBars(id, values) {
    const vals = values.filter(v => !Number.isNaN(Number(v))).length ? values.map(Number) : [20,45,72,38,90,55];
    const max = Math.max(...vals, 1);
    if ($(id)) { $(id).innerHTML = vals.map(v => `<div class="chart-bar" data-bar-height="${Math.max(8,Math.round((Number(v) / max) * 100))}"></div>`).join(''); applyDynamicVisuals($(id)); }
  }

  async function loadReports(showToast = false) {
    const result = await api('/api/v1/reports/summary');
    state.reports = result.ok ? result.data : fallbackReports();
    const email    = state.reports.email    || fallbackReports().email;
    const business = state.reports.business || fallbackReports().business;
    const learning = state.reports.learning || fallbackReports().learning;
    const modelHealth = state.reports.model_health || fallbackReports().model_health;
    const summary = buildReportSummary(email, business, learning, modelHealth);
    renderReportKpis(summary);
    renderReportInsightPanel(summary);
    renderReportPipeline(summary);
    renderReportCards('emailReport', email);
    renderReportCards('businessReport', business);
    renderReportCards('learningReport', learning);
    renderReportCards('modelHealthReport', modelHealth);
    if ($('scheduledReports')) $('scheduledReports').innerHTML = (state.reports.scheduled||[]).map(x => `<div class="activity-item"><div><b>${esc(x.name)}</b><small>${esc(x.frequency)} - ${esc(x.format)}</small></div><span class="badge ok">Enabled</span></div>`).join('') || '<div class="activity-item"><div><b>No scheduled reports</b><small>Create a schedule to email PDF/CSV reports automatically.</small></div><button class="btn" id="scheduleReportBtn" type="button">Schedule</button></div>';
    renderBars('emailChart', reportValues(email));
    renderBars('businessChart', reportValues(business));
    renderBars('learningChart', reportValues(learning));
    renderBars('modelHealthChart', reportValues(modelHealth));
    if (showToast) toast('Reports generated', result.ok ? 'Report data loaded from backend.' : 'Backend unavailable  -  local fallback displayed.', result.ok ? 'ok' : 'warn');
  }

  async function scheduleReport() {
    const result = await api('/api/v1/reports/schedule', {method:'POST', body:JSON.stringify({name:'Operations Report', frequency:'weekly', format:'pdf_csv'})});
    toast(result.ok ? 'Report scheduled' : 'Schedule failed', result.ok ? 'Scheduled reporting is enabled.' : msgFromError(result.error), result.ok ? 'ok' : 'bad');
    loadReports();
  }

  function exportPDF() {
    const reports = state.reports || fallbackReports();
    const email       = reports.email       || {};
    const business    = reports.business    || {};
    const learning    = reports.learning    || {};
    const modelHealth = reports.model_health || {};
    const now = new Date().toLocaleString();

    function tableRows(data) {
      return Object.entries(data).map(([k, v]) =>
        `<tr><td>${esc(k.replace(/_/g,' ').replace(/\b\w/g, c => c.toUpperCase()))}</td><td>${esc(String(v))}</td></tr>`
      ).join('');
    }
    function section(title, data) {
      if (!Object.keys(data).length) return '';
      return `<div class="sec"><h2>${title}</h2><table><thead><tr><th>Metric</th><th>Value</th></tr></thead><tbody>${tableRows(data)}</tbody></table></div>`;
    }

    const html = `<!DOCTYPE html><html><head><meta charset="UTF-8">
<title>INTEMO Report</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,'Segoe UI',sans-serif;font-size:12px;color:#1e293b;padding:36px 40px}
h1{font-size:20px;color:#2563eb;margin-bottom:3px}
.meta{font-size:11px;color:#64748b;margin-bottom:28px}
.sec{margin-bottom:26px;page-break-inside:avoid}
h2{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:#475569;margin-bottom:8px;padding-bottom:5px;border-bottom:2px solid #2563eb}
table{width:100%;border-collapse:collapse}
th{background:#f1f5f9;text-align:left;padding:6px 10px;font-size:10px;text-transform:uppercase;letter-spacing:.04em;color:#64748b}
td{padding:7px 10px;border-bottom:1px solid #e2e8f0}
td:last-child{text-align:right;font-weight:600;color:#2563eb}
tr:last-child td{border-bottom:none}
.footer{margin-top:32px;font-size:10px;color:#94a3b8;text-align:center;border-top:1px solid #e2e8f0;padding-top:12px}
@media print{body{padding:0}}
</style></head><body>
<h1>INTEMO AI Email Operations Report</h1>
<div class="meta">Generated: ${now}</div>
${section('Email Processing', email)}
${section('Business Intelligence', business)}
${section('AI Learning', learning)}
${section('Model Health', modelHealth)}
<div class="footer">INTEMO Enterprise &middot; Confidential &middot; ${now}</div>
</body></html>`;

    const win = window.open('', '_blank', 'width=820,height=960,scrollbars=yes');
    if (!win) { toast('Popup blocked', 'Allow popups for this site then try again.', 'warn'); return; }
    win.document.write(html);
    win.document.close();
    win.focus();
    setTimeout(() => { win.print(); }, 350);
  }

  // -- Admin -------------------------------------------------------------------
  async function loadAdmin() {
    const [adminResult, govResult] = await Promise.all([api('/api/v1/admin/overview'), api('/api/v1/governance/readiness')]);
    state.admin = adminResult.ok ? adminResult.data : {sections:FALLBACK_ADMIN_SECTIONS};
    state.governance = govResult.ok ? govResult.data : {areas:[]};
    const sections = state.admin.sections?.length ? state.admin.sections : FALLBACK_ADMIN_SECTIONS;
    state.admin.sections = sections;
    if ($('adminTabs')) $('adminTabs').innerHTML = sections.map((s,i) => `<button class="admin-tab ${i===0?'active':''}" data-admin-index="${i}" type="button">${esc(s.name)}</button>`).join('');
    renderAdminSection(0);
  }

  function adminActionButtons(name) {
    const n = String(name || '').toLowerCase();
    // Sections whose detail panels already contain the primary action button  -  no header duplicates
    if (n.includes('user') || n.includes('roles') || n.includes('team') ||
        n.includes('notification') || n.includes('ai config'))  return '';
    // Read-only status / info sections  -  no action needed in the header
    if (n.includes('system health') || n.includes('database') || n.includes('license')) return '';
    // Sections with meaningful per-section header actions
    if (n.includes('update'))      return '<button class="btn primary" data-admin-open-updates type="button">Open Update Center</button><button class="btn" data-admin-preview-update type="button">Preview Patch Flow</button>';
    if (n.includes('email'))       return '<button class="btn primary" data-open-view="accounts" type="button">Add Provider Account</button><button class="btn" data-open-view="settings" data-settings-jump="accounts" type="button">Provider Settings</button>';
    if (n.includes('rule'))        return '<button class="btn primary" data-open-view="automations" type="button">Manage Rules</button><button class="btn" id="simulateRuleBtn" type="button">Simulate Rule</button>';
    if (n.includes('security'))    return '<button class="btn primary" data-open-view="settings" data-settings-jump="security" type="button">Open Security Settings</button>';
    if (n.includes('audit'))       return '<button class="btn" data-load-audit type="button">Load Audit Logs</button>';
    if (n.includes('backup'))      return '<button class="btn primary" data-admin-action="backup" type="button">Create Backup Checkpoint</button><button class="btn" data-admin-audit type="button">View Backup History</button>';
    if (n.includes('queue'))       return '<button class="btn primary" data-admin-action="queue" type="button">Open Queue Controls</button><button class="btn" data-admin-audit type="button">View Failures</button>';
    if (n.includes('automation'))  return '<button class="btn primary" data-open-view="automations" type="button">View Automations</button>';
    if (n.includes('api'))         return '<button class="btn" data-admin-action="api" type="button">Test Integrations</button>';
    if (n.includes('storage'))     return '<button class="btn primary" data-admin-action="storage" type="button">Configure Retention</button>';
    if (n.includes('maintenance')) return '<button class="btn primary" data-admin-action="maintenance" type="button">Toggle Maintenance Mode</button>';
    if (n.includes('activity'))    return '<button class="btn" data-load-audit type="button">Refresh Activity</button>';
    return '';
  }

  function adminSectionDetails(name) {
    const n = String(name || '').toLowerCase();
    if (n.includes('user'))             return `<div class="control-grid"><label>Invite user<input placeholder="name@company.com"></label><label>Default role<select><option>Staff</option><option>Admin</option><option>Viewer</option></select></label><button class="btn primary" data-admin-action type="button">Send Invite</button></div>`;
    if (n.includes('roles'))            return `<div class="control-grid"><label>Role<select><option>Admin</option><option>Manager</option><option>Staff</option></select></label><label class="check"><input type="checkbox" checked> Can manage rules</label><label class="check"><input type="checkbox" checked> Can connect accounts</label><label class="check"><input type="checkbox"> Can install updates</label><button class="btn primary" data-admin-action type="button">Save Permissions</button></div>`;
    if (n.includes('team'))             return `<div class="control-grid"><label>Team name<input placeholder="Operations Team"></label><label>Assignment queue<select><option>Round robin</option><option>Least active</option><option>Manual</option></select></label><button class="btn primary" data-admin-action type="button">Create Team</button></div>`;
    if (n.includes('system health'))    return `<div class="report-cards"><div class="report-card"><span>API</span><strong>Ready</strong></div><div class="report-card"><span>Database</span><strong>Ready</strong></div><div class="report-card"><span>Queues</span><strong>Ready</strong></div><div class="report-card"><span>Sync</span><strong>Ready</strong></div></div>`;
    if (n.includes('email provider'))   return `<div class="settings-grid"><div class="settings-card"><b>OAuth providers</b><span>Gmail uses Google OAuth. Outlook, Microsoft 365 and Exchange use Microsoft OAuth.</span><button class="btn primary" data-open-view="accounts" type="button">Open Account Manager</button></div><div class="settings-card"><b>App-password providers</b><span>Yahoo, Zoho, Proton Bridge, IMAP/SMTP and custom domains use encrypted app-password settings.</span><button class="btn" data-open-view="settings" data-settings-jump="accounts" type="button">Account Settings</button></div></div>`;
    if (n.includes('update'))           return `<div class="workflow-diagram"><span class="workflow-node">Upload ZIP</span><span class="workflow-node">Validate</span><span class="workflow-node">Preview</span><span class="workflow-node">Backup</span><span class="workflow-node">Install</span><span class="workflow-node">Rollback</span></div>`;
    if (n.includes('security'))         return `<div class="settings-grid"><div class="settings-card"><b>Vault</b><span>Tokens and passwords are encrypted locally.</span><span class="badge ok">Enabled</span></div><div class="settings-card"><b>RBAC</b><span>Admin functions are role-controlled.</span><span class="badge ok">Enabled</span></div><div class="settings-card"><b>Audit</b><span>Admin and rule actions are logged.</span><span class="badge ok">Enabled</span></div></div>`;
    if (n.includes('backup'))           return `<div class="control-grid"><label>Backup schedule<select><option>Daily</option><option>Weekly</option><option>Before updates</option></select></label><label>Retention<select><option>30 days</option><option>90 days</option></select></label><button class="btn primary" data-admin-action type="button">Save Backup Policy</button></div>`;
    if (n.includes('database'))         return `<div class="report-cards"><div class="report-card"><span>Indexes</span><strong>Ready</strong></div><div class="report-card"><span>Migrations</span><strong>Ready</strong></div><div class="report-card"><span>Integrity</span><strong>Ready</strong></div></div>`;
    if (n.includes('notification'))     return `<div class="control-grid"><label>Admin alert email<input placeholder="admin@company.com"></label><label class="check"><input type="checkbox" checked> Sync failures</label><label class="check"><input type="checkbox" checked> Rule failures</label><label class="check"><input type="checkbox" checked> Update failures</label><button class="btn primary" data-admin-action type="button">Save Alerts</button></div>`;
    if (n.includes('ai configuration')) return `<div class="control-grid"><label>Confidence threshold<input type="number" value="85"></label><label>Review queue<select><option>Manual review below threshold</option><option>Auto classify all</option></select></label><button class="btn primary" data-admin-action type="button">Save AI Policy</button></div>`;
    if (n.includes('queue'))            return `<div class="report-cards"><div class="report-card"><span>Email sync</span><strong>Ready</strong></div><div class="report-card"><span>AI processing</span><strong>Ready</strong></div><div class="report-card"><span>Forwarding</span><strong>Ready</strong></div><div class="report-card"><span>Reports</span><strong>Ready</strong></div></div>`;
    if (n.includes('license'))          return `<div class="settings-grid"><div class="settings-card"><b>License status</b><span>Client runtime license controls are available for commercial deployment.</span><span class="badge ok">Ready</span></div></div>`;
    return `<div class="control-grid"><label>Policy name<input value="${esc(name||'Admin Control')}"></label><label>Status<select><option>Enabled</option><option>Paused</option></select></label><button class="btn primary" data-admin-action type="button">Save ${esc(name||'Admin')} Controls</button></div>`;
  }

  function renderAdminSection(index) {
    const sections = state.admin.sections?.length ? state.admin.sections : FALLBACK_ADMIN_SECTIONS;
    const s = sections[index] || sections[0];
    $$('.admin-tab').forEach((b,i) => b.classList.toggle('active', i === index));
    const govCards = (state.governance?.areas || []).slice(0,4).map(x => `<div class="report-card"><span>${esc(x.name)}</span><strong>${esc(x.score)}%</strong></div>`).join('');
    if ($('adminContent')) $('adminContent').innerHTML = `<div class="panel-head"><div><h2>${esc(s.name||'Admin')}</h2><p>${esc(s.description||'System management')}</p></div></div><div class="admin-actions">${adminActionButtons(s.name)}</div>${adminSectionDetails(s.name)}<h3>Operational Status</h3><div class="report-cards">${(s.items||[]).map(x=>`<div class="report-card"><span>${esc(x.label)}</span><strong>${esc(x.value)}</strong></div>`).join('')}${govCards}</div><div id="adminDetail" class="activity-list"><div class="activity-item"><div><b>${esc(s.name)} loaded</b><small>Controls above are active.</small></div><span class="badge ok">Ready</span></div></div>`;
  }

  async function loadAuditLogs() {
    const detail = $('adminDetail');
    if (detail) { detail.innerHTML = '<div class="activity-item"><div><b>Loading audit log...</b><small>Fetching recent activity.</small></div></div>'; detail.scrollIntoView({behavior:'smooth', block:'nearest'}); }
    const result = await api('/api/v1/admin/audit');
    if (!result.ok) {
      if (detail) detail.innerHTML = `<div class="activity-item"><div><b>Audit log unavailable</b><small>${esc(msgFromError(result.error))}</small></div><span class="badge bad">Error</span></div>`;
      toast('Audit log error', msgFromError(result.error), 'bad');
      return;
    }
    const rows = result.data.audit || [];
    if (detail) detail.innerHTML = rows.length
      ? rows.slice(0, 50).map(x => `<div class="activity-item"><div><b>${esc(x.rule_name||'Audit event')}</b><small>${esc(x.action_type||'')}  -  ${esc(x.created_at||'')}</small></div><span class="badge ok">Logged</span></div>`).join('')
      : '<div class="activity-item"><div><b>No audit events yet</b><small>Rule, sync and forwarding actions will appear here as they occur.</small></div></div>';
    toast('Audit log', `${rows.length} event${rows.length !== 1 ? 's' : ''} found.`, rows.length > 0 ? 'ok' : 'info');
  }

  async function loadUpdateStatus() {
    const result = await api('/api/v1/updates/status');
    const rows = result.ok ? (result.data.updates || result.data.history || []) : [];
    if ($('updateStatus')) $('updateStatus').innerHTML = rows.length ? rows.map(u => `<div class="activity-item"><div><b>${esc(u.name||u.version||'Patch')}</b><small>${esc(u.status||'ready')} - ${esc(u.created_at||'')}</small></div><span class="badge ok">${esc(u.type||'patch')}</span></div>`).join('') : '<div class="activity-item"><div><b>No patches installed</b><small>Upload a patch ZIP to preview and validate.</small></div><span class="badge ok">Ready</span></div>';
  }

  async function previewPatch() {
    const result = await api('/api/v1/updates/preview', {method:'POST', body:JSON.stringify({})});
    const steps = result.ok ? (result.data.steps || []) : ['Validate ZIP','Preview changes','Backup','Install','Rollback ready'];
    if ($('updatePreview')) $('updatePreview').innerHTML = steps.map(s => `<span class="workflow-node">${esc(s)}</span>`).join(' ');
    toast(result.ok ? 'Patch preview ready' : 'Patch preview opened', steps.join(' -> '), result.ok ? 'ok' : 'warn');
  }

  async function submitPatch(event) {
    event.preventDefault();
    const file = event.currentTarget.querySelector('input[type="file"]')?.files?.[0];
    if (!file) return toast('Patch ZIP required', 'Choose a ZIP patch before validation.', 'warn');
    const form = new FormData(); form.append('file', file);
    toast('Validating patch', 'ZIP integrity, dependencies and rollback readiness are being checked.', 'info');
    const result = await api('/api/v1/updates/validate', {method:'POST', body:form});
    toast(result.ok ? 'Patch validated' : 'Patch validation failed', result.ok ? 'Review preview, then install from the Windows runtime.' : msgFromError(result.error), result.ok ? 'ok' : 'bad');
    loadUpdateStatus();
  }

  async function loadAdvancedDiagnostics() {
    const result = await api('/api/v1/governance/overview');
    const data = result.ok ? result.data : {areas:[], queues:[]};
    if ($('settingsContent')) $('settingsContent').insertAdjacentHTML('beforeend',
      `<div class="report-cards">${(data.areas||[]).slice(0,8).map(a=>`<div class="report-card"><span>${esc(a.name)}</span><strong>${esc(a.score)}%</strong></div>`).join('')}</div><h3>Queue Governance</h3><div class="activity-list">${(data.queues||[]).map(q=>`<div class="activity-item"><div><b>${esc(q.name)}</b><small>${esc(q.purpose)}</small></div><span class="badge ok">${esc(q.priority)}</span></div>`).join('')||'<div class="activity-item"><div><b>Queues ready</b><small>No queue alerts.</small></div></div>'}</div>`
    );
  }

  // -- Settings ----------------------------------------------------------------
  function renderSettings(tab = 'general') {
    $$('.settings-tab').forEach(b => b.classList.toggle('active', b.dataset.settings === tab));
    const blocks = {
      general:       `<h2>General</h2><p>Control default operational behavior for the local enterprise runtime.</p><form class="form-grid settings-form"><label>Default sync interval<select name="sync_interval"><option value="20">20 seconds</option><option value="30">30 seconds</option><option value="60">60 seconds</option></select></label><label>Default landing page<select name="landing"><option>Dashboard</option><option>Inbox</option><option>Accounts</option></select></label><label class="check wide"><input name="preserve_accounts" type="checkbox" checked> Preserve accounts during restart, update, crash and failed sync</label><label class="check wide"><input name="manual_delete_only" type="checkbox" checked> Manual account removal only</label><div class="form-actions"><button class="btn primary" type="submit">Save General Settings</button></div></form>`,
      accounts:      `<h2>Accounts</h2><p>Provider onboarding, credential persistence and reconnect policy.</p><div class="settings-grid"><div class="settings-card"><b>Provider onboarding</b><span>Gmail uses Google OAuth. Outlook, Microsoft 365 and Exchange use Microsoft OAuth. Yahoo, Proton Bridge and custom domains use secure app-password/IMAP-SMTP flows. Zoho supports IMAP/SMTP.</span><button class="btn primary" data-open-view="accounts" type="button">Open Account Manager</button></div><div class="settings-card"><b>Persistence rule</b><span>Accounts are never removed automatically after restart, failed OAuth, wrong password, migration or update. They move to Reconnect Required.</span><button class="btn" data-settings-action="account-policy" type="button">Save Account Policy</button></div></div>`,
      ai:            `<h2>AI Processing Settings</h2><p>Configure classification and extraction behavior.</p><form class="form-grid settings-form"><label>Classification mode<select name="mode"><option>Balanced</option><option>Strict</option><option>High recall</option></select></label><label>Minimum confidence<input name="confidence" type="number" min="0" max="100" value="85"></label><label class="check"><input name="attachments" type="checkbox" checked> Analyze supported attachments</label><label class="check"><input name="corrections" type="checkbox" checked> Learn from manual corrections</label><label class="wide">Active categories<input value="RFQ, Invoice, Support, Shipment, Lead, Complaint, Payment, Logistics"></label><div class="form-actions"><button class="btn primary" type="submit">Save AI Settings</button><button class="btn" data-open-view="ai" type="button">Run Test Analysis</button></div></form>`,
      automations:   `<h2>Automation Settings</h2><p>Control retries, approvals and safe execution for rules and workflows.</p><form class="form-grid settings-form"><label>Retry count<select><option>1 retry</option><option selected>3 retries</option><option>5 retries</option></select></label><label>Failure action<select><option selected>Pause affected rule</option><option>Notify admin only</option><option>Retry later</option></select></label><label class="check"><input type="checkbox" checked> Require rule approval for forwarding</label><label class="check"><input type="checkbox" checked> Prevent duplicate forwarding</label><div class="form-actions"><button class="btn primary" type="submit">Save Automation Settings</button><button class="btn" data-open-view="automations" type="button">Manage Rules</button></div></form>`,
      notifications: `<h2>Notification Settings</h2><p>Choose which operational events should alert admins and users.</p><form class="form-grid settings-form"><label class="check"><input type="checkbox" checked> Sync failures</label><label class="check"><input type="checkbox" checked> Forwarding failures</label><label class="check"><input type="checkbox" checked> OAuth reconnect required</label><label class="check"><input type="checkbox" checked> Update validation failures</label><label>Alert email<input type="email" placeholder="admin@company.com"></label><label>Digest frequency<select><option>Immediate</option><option selected>Daily digest</option><option>Weekly digest</option></select></label><div class="form-actions"><button class="btn primary" type="submit">Save Notification Rules</button></div></form>`,
      security:      `<h2>Security Settings</h2><p>Credential vault, OAuth token lifecycle, RBAC and secure backup controls.</p><div class="settings-grid"><div class="settings-card"><b>Credential Vault</b><span>OAuth tokens and app passwords are encrypted locally. Raw secrets are never shown back to the UI.</span><span class="badge ok">Enabled</span></div><div class="settings-card"><b>Session &amp; RBAC</b><span>Admin areas require role permission and all actions are audit-ready.</span><span class="badge ok">Protected</span></div></div><div class="form-actions"><button class="btn primary" data-settings-action="security-review" type="button">Run Security Review</button></div>`,
      integrations:  `<h2>Integrations</h2><p>Configure provider APIs and operational webhooks.</p><form class="form-grid settings-form"><label>Webhook URL<input placeholder="https://company.com/webhooks/email-ops"></label><label>Integration status<select><option>Enabled</option><option>Paused</option></select></label><label class="check"><input type="checkbox" checked> Sign webhook payloads</label><label class="check"><input type="checkbox" checked> Retry failed webhooks</label><div class="form-actions"><button class="btn primary" type="submit">Save Integrations</button></div></form>`,
      updates:       `<h2>System Updates</h2><p>Upload ZIP patches, validate, preview changes, backup, install and rollback when required.</p><form id="patchForm" class="stacked-form"><input name="file" type="file" accept=".zip"><div class="form-actions"><button class="btn" id="previewPatchBtn" type="button">Preview Changes</button><button class="btn primary" type="submit">Validate Patch</button></div></form><div class="workflow-diagram" id="updatePreview"><span class="workflow-node">Upload ZIP</span><span class="workflow-node">Validate</span><span class="workflow-node">Preview</span><span class="workflow-node">Backup</span><span class="workflow-node">Install</span><span class="workflow-node">Rollback Ready</span></div><div id="updateStatus" class="activity-list"></div>`,
      advanced:      `<h2>Advanced Diagnostics</h2><p>Admin-only system diagnostics. Normal users do not need this section.</p>`
    };
    if ($('settingsContent')) $('settingsContent').innerHTML = blocks[tab] || blocks.general;
    if (tab === 'updates')  { loadUpdateStatus(); $('patchForm')?.addEventListener('submit', submitPatch); }
    if (tab === 'advanced') loadAdvancedDiagnostics();
  }

  // -- Command palette ---------------------------------------------------------
  const PALETTE_ACTIONS = [
    {title:'Add email account',           section:'Accounts',    action:'accounts',          shortcut:'A'},
    {title:'Open inbox',                  section:'Inbox',       action:'inbox',             shortcut:'I'},
    {title:'Create automation rule',      section:'Automations', action:'automations',       shortcut:'R'},
    {title:'Generate reports',            section:'Analytics',   action:'reports',           shortcut:'P'},
    {title:'Open update center',          section:'Settings',    action:'settings:updates',  shortcut:'U'},
    {title:'Advanced system diagnostics', section:'Settings',    action:'settings:advanced', shortcut:'D'}
  ];

  function renderCommandPalette() {
    const q = ($('commandSearch')?.value || '').toLowerCase();
    const rows = PALETTE_ACTIONS.filter(a => !q || `${a.title} ${a.section}`.toLowerCase().includes(q));
    if ($('commandList')) $('commandList').innerHTML = rows.map(a =>
      `<button class="command-item" data-command="${esc(a.action)}" type="button" role="option"><span><b>${esc(a.title)}</b><small>${esc(a.section)}</small></span><span class="kbd">${esc(a.shortcut)}</span></button>`
    ).join('') || '<div class="activity-item"><b>No matching action</b><small>Try accounts, rules, reports, updates or inbox.</small></div>';
  }

  function openCommandPalette() {
    const p = $('commandPalette');
    if (!p) return;
    renderCommandPalette();
    p.classList.add('open');
    p.setAttribute('aria-hidden', 'false');
    setTimeout(() => $('commandSearch')?.focus(), 30);
  }

  function closeCommandPalette() {
    const p = $('commandPalette');
    if (!p) return;
    p.classList.remove('open');
    p.setAttribute('aria-hidden', 'true');
  }

  function runCommand(action) {
    if (!action) return;
    if (action.includes(':')) { const [view, tab] = action.split(':'); showView(view, tab); }
    else showView(action);
    closeCommandPalette();
  }

  function applyNavigationRole(role = localStorage.getItem('ai36NavRole') || 'basic-client') {
    const nav = document.querySelector('.main-nav');
    if (!nav) return;
    nav.dataset.navRole = role;
    nav.querySelectorAll('[data-nav-role]').forEach(item => {
      const roles = String(item.dataset.navRole || '').split(/\s+/).filter(Boolean);
      item.hidden = roles.length > 0 && !roles.includes(role);
    });
    const chip = $('navRoleChip');
    if (chip) chip.textContent = role === 'advanced-admin' ? 'Advanced admin' : role === 'business-admin' ? 'Business admin' : role === 'admin' ? 'Admin' : 'Essentials';
  }

  function setNavigationRole(role) {
    localStorage.setItem('ai36NavRole', role);
    applyNavigationRole(role);
  }

  function setSidebarOpen(open) {
    $('sidebar')?.classList.toggle('open', open);
    $('sidebarOverlay')?.classList.toggle('open', open);
    $('sidebarToggle')?.setAttribute('aria-expanded', String(open));
  }

  // -- Global click delegation -------------------------------------------------
  document.addEventListener('click', async event => {
    const target = event.target.closest('button');
    if (!target) return;

    if (target.dataset.view) {
      showView(target.dataset.view);
      setSidebarOpen(false);
    }
    if (target.dataset.openView) showView(target.dataset.openView, target.dataset.settingsJump);
    if (target.dataset.connectorNavId) openConnectorFromMainNav(target.dataset.connectorNavId);
    if (target.dataset.settings) renderSettings(target.dataset.settings);

    if (target.id === 'sidebarToggle') setSidebarOpen(!$('sidebar')?.classList.contains('open'));
    if (target.id === 'refreshBtn')    { await Promise.all([loadDashboard(), loadAccounts()]); toast('Refreshed', 'Latest operational data loaded.', 'ok'); }

    if (target.classList.contains('provider-card')) { selectProvider(target.dataset.provider, true); $('accountForm')?.email?.focus(); }
    if (target.classList.contains('filter-chip')) { $$('.filter-chip').forEach(b => b.classList.remove('active')); target.classList.add('active'); state.savedFilter = target.dataset.filter; renderInbox(); }

    if (target.id === 'detectProviderBtn' || target.dataset.detectInline !== undefined) detectProvider();
    if (target.id === 'testConnectionBtn')  testAccountConnection();
    if (target.dataset.oauthStart)         startOAuthFlow(target.dataset.oauthStart, $('accountForm')?.email?.value || '');
    if (target.dataset.continueOauth)      startOAuthFlow(target.dataset.continueOauth, $('accountForm')?.email?.value || '');
    if (target.dataset.showOauthSetup)     renderOAuthSetupPanel(target.dataset.showOauthSetup);
    if (target.dataset.useAppPassword !== undefined) useAppPasswordFlow();

    if (target.dataset.sync)                      startAccountSync(target.dataset.sync);
    if (target.dataset.editAccount !== undefined) toggleAccountEdit(target.dataset.editAccount);
    if (target.dataset.cancelEdit !== undefined)  toggleAccountEdit(target.dataset.cancelEdit);
    if (target.dataset.pause)                     pauseAccount(target.dataset.pause);
    if (target.dataset.resume)                    resumeAccount(target.dataset.resume);
    if (target.dataset.reconnect)                 reconnectAccount(target.dataset.reconnect);
    if (target.dataset.remove)                    removeAccount(target.dataset.remove);

    if (target.id === 'refreshInboxBtn') { refreshInboxSync(); return; }
    if (target.id === 'bulkActionBtn')  { toggleSelectAll(); return; }
    // Bulk bar actions
    if (target.id === 'bulkReadBtn')    { executeBulkAction('markRead'); return; }
    if (target.id === 'bulkArchiveBtn') { executeBulkAction('archive'); return; }
    if (target.id === 'bulkLabelBtn')   { executeBulkAction('label'); return; }
    if (target.id === 'bulkMoveBtn')    { executeBulkAction('move'); return; }
    if (target.id === 'bulkClearBtn')   { state.selectedEmails.clear(); updateBulkBar(); renderInbox(); return; }
    // Sidebar inline folder/label creation
    if (target.id === 'sidebarCreateFolderBtn') { const inp = $('sidebarNewFolder'); createFolder(inp?.value); if (inp) inp.value = ''; return; }
    if (target.id === 'sidebarCreateLabelBtn')  { const inp = $('sidebarNewLabel');  createLabel(inp?.value);  if (inp) inp.value = ''; return; }
    // Email checkbox selection  -  label wraps the checkbox, clicking label fires on label or checkbox
    if (target.dataset.cbId || target.closest('.thread-row-cb')) {
      const cb = target.type === 'checkbox' ? target : target.closest('.thread-row-cb')?.querySelector('.email-cb');
      if (cb) toggleEmailSelect(cb.dataset.cbId, cb.checked);
      return;
    }
    if (target.dataset.emailCategory) { applyEmailVerdict(target.dataset.emailCategoryId, target.dataset.emailCategory); return; }
    if (target.dataset.emailAction) { handleEmailAction(target.dataset.emailAction, target.dataset.emailActionId); return; }
    // Use closest so clicking any text/span inside the button still opens the email
    const emailBtn = target.closest('[data-email-id]');
    if (emailBtn?.dataset.emailId) { state.selectedEmail = state.emails.find(e => String(e.id) === String(emailBtn.dataset.emailId)); renderPreview(state.selectedEmail); renderInbox(); }

    if (target.id === 'simulateRuleBtn')   simulateRule();
    if (target.dataset.simulateRuleId)     simulateRule(target.dataset.simulateRuleId);
    if (target.id === 'scanRuleStructureBtn') scanRuleMailboxStructure();
    if (target.dataset.recoverOnnxModel)   recoverOnnxModel(target.dataset.recoverOnnxModel);
    if (target.dataset.forgetLearningKey)  forgetLearningOverride(target.dataset.forgetLearningKey);
    if (target.id === 'exportLearningMemoryBtn') exportLearningMemory();
    if (target.id === 'previewLearningImportBtn') previewLearningImport();
    if (target.id === 'importLearningMemoryBtn') importLearningMemory();
    if (target.dataset.learningImportMerge !== undefined) importLearningMemory(false);
    if (target.dataset.learningImportReplace !== undefined) importLearningMemory(true);
    if (target.id === 'backupAiStateBtn') backupAiState();
    if (target.id === 'saveAiBackupScheduleBtn') saveAiBackupSchedule();
    if (target.dataset.restoreAiBackup) restoreAiStateBackup(target.dataset.restoreAiBackup);
    if (target.id === 'applyRulesBtn')     applyRulesToAll();
    if (target.id === 'exportRulesBtn')    window.location.href = '/api/v1/rules/export';
    if (target.id === 'duplicateRuleBtn')  duplicateRule();
    if (target.id === 'createLabelBtn')    { const inp = $('newLabelInput');  createLabel(inp?.value);  if (inp) inp.value = ''; }
    if (target.id === 'createFolderBtn')   { const inp = $('newFolderInput'); createFolder(inp?.value); if (inp) inp.value = ''; }
    if (target.id === 'refreshPresetsBtn') loadPresets();
    if (target.dataset.installPreset)      installPreset(target.dataset.installPreset, target);

    if (target.id === 'newTemplateBtn')    $('templateNameInput')?.focus();
    if (target.id === 'createTemplateBtn') createTemplate();
    if (target.dataset.template)           toast('Template loaded', `Template "${esc(target.dataset.template)}" is ready to customize.`, 'ok');

    if (target.dataset.adminIndex !== undefined)       renderAdminSection(Number(target.dataset.adminIndex));
    if (target.dataset.adminOpenUpdates !== undefined) showView('settings', 'updates');
    if (target.dataset.adminPreviewUpdate !== undefined) { showView('settings', 'updates'); setTimeout(previewPatch, 80); }
    if (target.dataset.loadAudit !== undefined)        loadAuditLogs();
    if (target.dataset.adminAction !== undefined) {
      const action = target.dataset.adminAction;
      if (action === 'backup') { showView('settings', 'updates'); return; }
      if (action === 'queue') {
        const r = await api('/api/v1/admin/overview');
        const detail = $('adminDetail');
        if (detail) { detail.innerHTML = r.ok ? '<div class="activity-item"><div><b>Queue status</b><small>Sync, AI, forwarding and report queues operational.</small></div><span class="badge ok">Ready</span></div>' : `<div class="activity-item"><div><b>Queue check failed</b><small>${esc(msgFromError(r.error))}</small></div><span class="badge bad">Error</span></div>`; detail.scrollIntoView({behavior:'smooth', block:'nearest'}); }
        toast(r.ok ? 'Queue controls' : 'Queue check failed', r.ok ? 'All queues are operational.' : msgFromError(r.error), r.ok ? 'ok' : 'bad');
        return;
      }
      const grid = $('adminContent')?.querySelector('.control-grid');
      const inputs = grid ? Array.from(grid.querySelectorAll('input,select,textarea')) : [];
      const payload = {};
      inputs.forEach(inp => { if (inp.name) payload[inp.name] = inp.type === 'checkbox' ? inp.checked : inp.value; });
      if (Object.keys(payload).length > 0) {
        const r = await api('/api/v1/settings', {method:'PUT', body:JSON.stringify(payload)});
        toast(r.ok ? 'Settings saved' : 'Settings not saved', r.ok ? 'Admin configuration applied.' : msgFromError(r.error), r.ok ? 'ok' : 'warn');
      } else {
        toast('Controls ready', 'Admin section is active.', 'ok');
      }
    }
    if (target.dataset.adminAudit !== undefined)       loadAuditLogs();

    if (target.id === 'previewPatchBtn')    previewPatch();
    if (target.id === 'generateReportBtn')  loadReports(true);
    if (target.id === 'exportPdfBtn')       { exportPDF(); return; }
    if (target.id === 'exportCsvBtn')       { toast('CSV export started', 'Downloading report export.', 'ok'); window.location.href = '/api/v1/reports/export.csv'; }
    if (target.id === 'scheduleReportBtn')  scheduleReport();
    if (target.dataset.settingsAction !== undefined) toast('Settings saved', 'Configuration accepted.', 'ok');

    if (target.id === 'viewCertificationBtn') showView('settings', 'advanced');
    if (target.id === 'commandPaletteBtn')    openCommandPalette();
    if (target.id === 'lowResToggleBtn')      _toggleLowResourceMode();
    if (target.id === 'closeCommandPalette')  closeCommandPalette();
    if (target.dataset.command)               runCommand(target.dataset.command);
    if (target.id === 'navModeToggle') {
      const current = localStorage.getItem('ai36NavRole') || 'basic-client';
      const next = current === 'basic-client' ? 'advanced-admin' : 'basic-client';
      setNavigationRole(next);
      target.setAttribute('aria-pressed', String(next !== 'basic-client'));
      target.textContent = next === 'basic-client' ? 'Show advanced tools' : 'Show essentials only';
    }
  });

  // -- Theme switcher ----------------------------------------------------------
  function initThemeSwitcher() {
    const THEME_KEY = 'intemo_theme';
    const saved = localStorage.getItem(THEME_KEY) || 'light';
    applyTheme(saved);
    document.querySelectorAll('[data-theme-set]').forEach(btn => {
      btn.addEventListener('click', () => {
        const t = btn.dataset.themeSet;
        applyTheme(t);
        localStorage.setItem(THEME_KEY, t);
      });
    });
  }

  function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    document.querySelectorAll('[data-theme-set]').forEach(btn => {
      const on = btn.dataset.themeSet === theme;
      btn.classList.toggle('active', on);
      btn.setAttribute('aria-pressed', String(on));
    });
  }

  // -- Bindings ----------------------------------------------------------------
  function bind() {
    initThemeSwitcher();
    $('sidebarOverlay')?.addEventListener('click', () => setSidebarOpen(false));
    $('accountForm')?.addEventListener('submit', saveAccount);
    $('accountForm')?.provider?.addEventListener('change', e => selectProvider(e.target.value, true));
    $('connectionMethod')?.addEventListener('change', () => { renderProviderActionPanel(state.currentProvider); const pw = $('accountForm')?.password; if (pw) pw.closest('label')?.classList.toggle('muted-field', selectedConnectionMethod() === 'oauth'); updateOAuthSubmitState(); });
    $('accountForm')?.email?.addEventListener('blur', () => { const f = $('accountForm'); if (f?.email?.value && (!f.provider.value || f.provider.value === 'custom')) selectProvider(providerForEmail(f.email.value), true); });
    $('ruleForm')?.addEventListener('submit', saveRule);
    $('analysisForm')?.addEventListener('submit', analyzeEmail);
    $('learningFeedbackForm')?.addEventListener('submit', submitLearningFeedback);
    $('accountFilter')?.addEventListener('change', e => {
      state.selectedMailboxId = e.target.value || '';
      if ($('folderFilter')) $('folderFilter').value = '';
      if ($('labelFilter')) $('labelFilter').value = '';
      loadInbox();
    });
    $('folderFilter')?.addEventListener('change', loadInbox);
    $('labelFilter')?.addEventListener('change',  loadInbox);
    $('ruleSearch')?.addEventListener('input',     renderRules);
    $('ruleStatusFilter')?.addEventListener('change', renderRules);
    $('ruleMailboxSelect')?.addEventListener('change', loadLabelsAndFolders);
    $('newLabelInput')?.addEventListener('keydown',  e => { if (e.key === 'Enter') { e.preventDefault(); createLabel(e.target.value); e.target.value = ''; } });
    $('newFolderInput')?.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); createFolder(e.target.value); e.target.value = ''; } });
    $('sidebarNewFolder')?.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); createFolder(e.target.value); if (e.target) e.target.value = ''; } });
    $('sidebarNewLabel')?.addEventListener('keydown',  e => { if (e.key === 'Enter') { e.preventDefault(); createLabel(e.target.value);  if (e.target) e.target.value = ''; } });
    $('globalSearch')?.addEventListener('input',     () => { if (state.currentView === 'inbox') renderInbox(); });
    $('commandSearch')?.addEventListener('input',    renderCommandPalette);
    document.addEventListener('keydown', e => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); openCommandPalette(); }
      if (e.key === 'Escape') closeCommandPalette();
    });
    document.addEventListener('submit', e => {
      if (e.target?.id === 'inlineOAuthSetupForm') { saveInlineOAuthSetup(e); return; }
      if (e.target?.classList?.contains('settings-form')) { e.preventDefault(); const payload = Object.fromEntries(new FormData(e.target).entries()); api('/api/v1/settings', {method:'PUT', body:JSON.stringify(payload)}).then(r => toast(r.ok ? 'Settings saved' : 'Settings not saved', r.ok ? 'Configuration applied locally.' : msgFromError(r.error), r.ok ? 'ok' : 'warn')); }
    });
  }

  // -- Workflow Engine ----------------------------------------------------------
  let _wfReady = false;

  function initWorkflowsView() {
    if (_wfReady) {
      const activeTab = document.querySelector('#view-workflows .ocr-tab.active')?.dataset?.ocrTab;
      if (activeTab === 'active')      { _loadWfStats(); _loadWfActive(); }
      if (activeTab === 'marketplace') _loadWfMarketplace();
      if (activeTab === 'history')     _loadWfHistory();
      return;
    }
    _wfReady = true;
    _setupWfTabs();
    _loadWfStats();
    _loadWfActive();
  }

  function _setupWfTabs() {
    const section = $('view-workflows');
    if (!section) return;
    const tabs   = $$('.ocr-tab', section);
    const panels = $$('.ocr-panel', section);

    tabs.forEach(tab => {
      tab.addEventListener('click', () => {
        const id = tab.dataset.ocrTab;
        tabs.forEach(t => { t.classList.remove('active'); t.setAttribute('aria-selected', 'false'); });
        panels.forEach(p => p.classList.remove('active'));
        tab.classList.add('active');
        tab.setAttribute('aria-selected', 'true');
        const panel = $(`wfTab-${id}`);
        if (panel) panel.classList.add('active');
        if (id === 'active')      { _loadWfStats(); _loadWfActive(); }
        if (id === 'marketplace') _loadWfMarketplace();
        if (id === 'history')     _loadWfHistory();
      });
    });

    $('wfRefreshHistoryBtn')?.addEventListener('click', _loadWfHistory);
  }

  async function _loadWfStats() {
    const strip = $('wfStatsStrip');
    if (!strip) return;
    const r = await api('/api/v1/workflows/stats');
    if (!r.ok) { strip.innerHTML = ''; return; }
    const s = r.data;
    const successRate = s.total_runs > 0 ? Math.round((s.total_succeeded / s.total_runs) * 100) : 100;
    strip.innerHTML = [
      ['Total Workflows',    s.total_workflows  ?? 0],
      ['Active',             s.active_workflows ?? 0],
      ['Total Runs',         s.total_runs       ?? 0],
      ['Success Rate',       `${successRate}%`],
      ['Last 24h Succeeded', s.last_24h?.succeeded ?? 0],
      ['Last 24h Failed',    s.last_24h?.failed    ?? 0],
    ].map(([label, val]) => `
      <div class="wf-stat-card">
        <div class="wf-stat-value">${esc(String(val))}</div>
        <div class="wf-stat-label">${esc(label)}</div>
      </div>`).join('');
  }

  async function _loadWfActive() {
    const list = $('wfActiveList');
    if (!list) return;
    list.innerHTML = '<div class="empty-state"><div class="spinner"></div></div>';
    const r = await api('/api/v1/workflows');
    if (!r.ok) {
      list.innerHTML = `<div class="empty-state"><p>Failed to load workflows: ${esc(msgFromError(r.error))}</p></div>`;
      return;
    }
    const items = r.data.workflows || [];
    if (!items.length) {
      list.innerHTML = `<div class="empty-state"><h3>No workflows yet</h3><p>Head to the <strong>Marketplace</strong> tab to activate a workflow template.</p></div>`;
      return;
    }
    list.innerHTML = items.map(w => `
      <article class="wf-active-card" data-wf-id="${esc(w.id)}">
        <div class="panel-head">
          <div>
            <h2>${esc(w.name)}</h2>
            <p>${esc(w.description || '')}</p>
          </div>
          <div class="wf-card-actions">
            <span class="badge ${w.is_active ? 'ok' : 'neutral'}">${w.is_active ? 'Active' : 'Inactive'}</span>
            <button class="btn sm wf-run-btn"    type="button" data-wf-id="${esc(w.id)}" ${!w.is_active ? 'disabled' : ''}>Run</button>
            <button class="btn sm ghost wf-toggle-btn" type="button" data-wf-id="${esc(w.id)}" data-wf-active="${w.is_active ? '1' : '0'}">${w.is_active ? 'Deactivate' : 'Activate'}</button>
            <button class="btn sm danger wf-delete-btn" type="button" data-wf-id="${esc(w.id)}">Delete</button>
          </div>
        </div>
        <div class="wf-card-meta">
          <span>Trigger: <strong>${esc(w.trigger_type || 'manual')}</strong></span>
          <span>Category: <strong>${esc(w.category || 'general')}</strong></span>
          <span>Runs: <strong>${esc(String(w.run_count ?? 0))}</strong></span>
          <span>Last run: <strong>${w.last_run_at ? new Date(w.last_run_at).toLocaleString() : 'Never'}</strong></span>
        </div>
      </article>`).join('');

    list.querySelectorAll('.wf-run-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        const id = btn.dataset.wfId;
        btn.disabled = true; btn.textContent = 'Running...';
        const r2 = await api(`/api/v1/workflows/${id}/execute`, { method: 'POST', body: JSON.stringify({}) });
        if (r2.ok) {
          toast('Workflow started', 'Execution dispatched in background.', 'ok');
          setTimeout(_loadWfHistory, 1800);
        } else {
          toast('Run failed', msgFromError(r2.error), 'error');
        }
        btn.disabled = false; btn.textContent = 'Run';
      });
    });

    list.querySelectorAll('.wf-toggle-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        const id     = btn.dataset.wfId;
        const active = btn.dataset.wfActive === '1';
        btn.disabled = true; btn.textContent = active ? 'Deactivating...' : 'Activating...';
        const r2 = await api(`/api/v1/workflows/${id}/${active ? 'deactivate' : 'activate'}`, { method: 'POST' });
        if (r2.ok) {
          toast(active ? 'Workflow deactivated' : 'Workflow activated', '', 'ok');
          _loadWfStats();
          _loadWfActive();
        } else {
          toast('Failed', msgFromError(r2.error), 'error');
          btn.disabled = false;
          btn.textContent = active ? 'Deactivate' : 'Activate';
        }
      });
    });

    list.querySelectorAll('.wf-delete-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        const id = btn.dataset.wfId;
        if (!confirm('Delete this workflow permanently?')) return;
        btn.disabled = true; btn.textContent = 'Deleting...';
        const r2 = await api(`/api/v1/workflows/${id}`, { method: 'DELETE' });
        if (r2.ok) {
          toast('Deleted', 'Workflow removed.', 'ok');
          _loadWfStats();
          _loadWfActive();
        } else {
          toast('Delete failed', msgFromError(r2.error), 'error');
          btn.disabled = false; btn.textContent = 'Delete';
        }
      });
    });
  }

  async function _loadWfMarketplace() {
    const grid      = $('wfTemplateGrid');
    const recoLabel = $('wfRecoLabel');
    if (!grid) return;
    grid.innerHTML = '<div class="empty-state"><div class="spinner"></div></div>';

    const [tmplRes, recoRes] = await Promise.all([
      api('/api/v1/workflows/templates'),
      api('/api/v1/workflows/recommendations'),
    ]);

    if (!tmplRes.ok) {
      grid.innerHTML = `<div class="empty-state"><p>Failed to load templates: ${esc(msgFromError(tmplRes.error))}</p></div>`;
      return;
    }

    const templates = tmplRes.data.templates || [];
    const recoIds   = new Set((recoRes.ok ? recoRes.data.recommendations || [] : []).map(r => r.template_id));
    if (recoLabel) recoLabel.style.display = recoIds.size ? '' : 'none';

    if (!templates.length) {
      grid.innerHTML = '<div class="empty-state"><h3>No templates available</h3></div>';
      return;
    }

    const sorted = [...templates].sort((a, b) => {
      const aRec = recoIds.has(a.template_id) ? 1 : 0;
      const bRec = recoIds.has(b.template_id) ? 1 : 0;
      return bRec - aRec;
    });

    grid.innerHTML = sorted.map(t => `
      <article class="wf-template-card" data-tmpl-id="${esc(t.template_id)}">
        <div class="wf-template-head">
          <div class="wf-template-copy">
            <h3 class="wf-template-title">${esc(t.name)}</h3>
            <p class="wf-template-desc">${esc(t.description || '')}</p>
          </div>
          ${recoIds.has(t.template_id) ? '<span class="badge ok workflow-reco-label">Recommended</span>' : ''}
        </div>
        <div class="wf-template-meta">
          <span>Trigger: <strong>${esc(t.trigger_type || 'manual')}</strong></span>
          <span>Steps: <strong>${t.steps?.length ?? 0}</strong></span>
          ${t.category ? `<span>Category: <strong>${esc(t.category)}</strong></span>` : ''}
          ${t.impact   ? `<span>Impact: <strong>${esc(t.impact)}</strong></span>`    : ''}
        </div>
        <button class="btn sm wf-activate-tmpl-btn" type="button" data-tmpl-id="${esc(t.template_id)}">Activate</button>
      </article>`).join('');

    grid.querySelectorAll('.wf-activate-tmpl-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        const tmplId = btn.dataset.tmplId;
        btn.disabled = true; btn.textContent = 'Activating...';
        const r2 = await api('/api/v1/workflows', {
          method: 'POST',
          body: JSON.stringify({ template_id: tmplId }),
        });
        if (r2.ok) {
          toast('Workflow activated', 'Switch to Active Workflows to manage it.', 'ok');
          btn.textContent = 'Activated';
          _loadWfStats();
        } else {
          toast('Activation failed', msgFromError(r2.error), 'error');
          btn.disabled = false; btn.textContent = 'Activate';
        }
      });
    });
  }

  async function _loadWfHistory() {
    const list = $('wfHistoryList');
    if (!list) return;
    list.innerHTML = '<div class="empty-state"><div class="spinner"></div></div>';
    const r = await api('/api/v1/workflows/executions/all?limit=100');
    if (!r.ok) {
      list.innerHTML = `<div class="empty-state"><p>Failed to load history: ${esc(msgFromError(r.error))}</p></div>`;
      return;
    }
    const items = r.data.executions || [];
    if (!items.length) {
      list.innerHTML = '<div class="empty-state"><h3>No executions yet</h3><p>Run a workflow to see its history here.</p></div>';
      return;
    }
    const STATUS_BADGE = { succeeded: 'ok', failed: 'bad', running: 'warn', pending: 'neutral' };
    list.innerHTML = `<div class="wf-history-scroll"><table class="data-table"><thead><tr>
      <th>Workflow</th><th>Trigger</th><th>Status</th><th>Steps</th><th>Duration</th><th>Started</th><th>Error</th>
    </tr></thead><tbody>${items.map(ex => {
      const durMs  = ex.duration_ms != null ? ex.duration_ms : (ex.finished_at && ex.started_at ? new Date(ex.finished_at) - new Date(ex.started_at) : null);
      const dur    = durMs != null ? `${(durMs / 1000).toFixed(1)}s` : (ex.status === 'running' ? 'Running...' : ' - ');
      const steps  = ex.step_count ? `${ex.steps_done ?? 0}/${ex.step_count}` : ' - ';
      const badge  = STATUS_BADGE[ex.status] || 'neutral';
      return `<tr>
        <td>${esc(ex.workflow_name || ex.workflow_id || ' - ')}</td>
        <td>${esc(ex.trigger_type || 'manual')}</td>
        <td><span class="badge ${badge}">${esc(ex.status)}</span></td>
        <td>${steps}</td>
        <td>${dur}</td>
        <td>${ex.started_at ? new Date(ex.started_at).toLocaleString() : ' - '}</td>
        <td class="wf-history-error" title="${esc(ex.error || '')}">${esc(ex.error || ' - ')}</td>
      </tr>`;
    }).join('')}</tbody></table></div>`;
  }

  // -- Alert Rules tab ---------------------------------------------------------

  let _alertEditId = null;
  let _alertRulesReady = false;

  function _initAlertRulesListeners() {
    if (_alertRulesReady) return;
    _alertRulesReady = true;
    $('cmdAlertAddBtn')?.addEventListener('click', () => _openAlertModal(null));
    $('cmdAlertRefreshBtn')?.addEventListener('click', _loadCmdAlerts);
    $('cmdAlertCancelBtn')?.addEventListener('click', _closeAlertModal);
    $('cmdAlertModal')?.addEventListener('click', (e) => { if (e.target === $('cmdAlertModal')) _closeAlertModal(); });
    $('cmdAlertForm')?.addEventListener('submit', async (e) => { e.preventDefault(); await _saveAlertRule(); });
  }

  async function _loadCmdAlerts() {
    _initAlertRulesListeners();
    const metricsEl = $('cmdAlertMetrics');
    const listEl    = $('cmdAlertRulesList');
    if (!listEl) return;

    listEl.innerHTML = '<div class="empty-state"><div class="spinner"></div></div>';

    const r = await api('/api/v1/alert-rules/status');
    if (!r.ok && !r.running) {
      listEl.innerHTML = '<div class="empty-state">Failed to load alert rules.</div>';
      return;
    }

    // Metric snapshot strip
    const metrics = r.metrics || {};
    if (metricsEl) {
      const _metricLabel = {
        active_threats: 'Active Threats', health_score: 'Health Score',
        workflow_success_rate: 'WF Success %', running_agents: 'Agents Running',
        emails_last_1h: 'Emails (1h)', scam_last_24h: 'Scam (24h)',
      };
      metricsEl.innerHTML = Object.entries(metrics).map(([k, v]) => `
        <div class="intel-card" style="min-width:110px;">
          <div class="intel-card-label">${esc(_metricLabel[k] || k)}</div>
          <div class="intel-card-value">${typeof v === 'number' ? v.toFixed(v % 1 === 0 ? 0 : 1) : v}</div>
        </div>`).join('');
    }

    const rules = r.rules || [];
    if (!rules.length) {
      listEl.innerHTML = `<div class="empty-state">No alert rules defined. Click <strong>+ Add Rule</strong> to monitor platform metrics and auto-trigger webhooks on threshold breaches.</div>`;
      return;
    }

    const SEV_COLOR = { low: 'var(--text-muted)', medium: 'var(--accent)', high: 'var(--warn)', critical: 'var(--danger)' };
    listEl.innerHTML = `<div style="display:grid;gap:10px;">${rules.map(rule => {
      const breached = rule.breached;
      const badge = breached
        ? `<span style="font-size:11px;background:var(--danger);color:#fff;padding:2px 8px;border-radius:10px;">BREACHED</span>`
        : `<span style="font-size:11px;background:var(--surface-alt);color:var(--ok);padding:2px 8px;border-radius:10px;">OK</span>`;
      return `<div class="panel" style="padding:14px 16px;${breached ? 'border-color:var(--danger);' : ''}">
        <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;">
          <div style="display:flex;align-items:center;gap:10px;">
            ${badge}
            <div>
              <div style="font-size:14px;font-weight:600;">${esc(rule.rule_name)}</div>
              <div style="font-size:11px;color:var(--text-muted);">${esc(rule.metric)} ${esc(rule.operator)} ${rule.threshold}  -  current: <strong>${rule.current_value ?? ' - '}</strong></div>
            </div>
          </div>
          <div style="display:flex;gap:6px;align-items:center;">
            <span style="font-size:11px;color:${SEV_COLOR[rule.severity] || 'var(--text-muted)'};">${esc(rule.severity)}</span>
            <button class="btn sm" type="button" data-alert-edit="${esc(rule.rule_id)}">Edit</button>
            <button class="btn sm danger" type="button" data-alert-del="${esc(rule.rule_id)}">Delete</button>
          </div>
        </div>
        ${rule.last_breach ? `<div style="margin-top:6px;font-size:11px;color:var(--text-muted);">Last breach: ${esc(rule.last_breach.slice(0,19).replace('T',' '))} UTC Â· ${rule.breach_count} total</div>` : ''}
      </div>`;
    }).join('')}</div>`;

    listEl.querySelectorAll('[data-alert-edit]').forEach(btn => {
      btn.addEventListener('click', async () => {
        const r2 = await api(`/api/v1/alert-rules/${btn.dataset.alertEdit}`);
        if (r2.ok || r2.id) _openAlertModal(r2);
        else toast('Failed', msgFromError(r2.error), 'error');
      });
    });
    listEl.querySelectorAll('[data-alert-del]').forEach(btn => {
      btn.addEventListener('click', async () => {
        if (!confirm('Delete this alert rule?')) return;
        const r2 = await api(`/api/v1/alert-rules/${btn.dataset.alertDel}`, { method: 'DELETE' });
        if (r2.ok || r2.status === 204) { toast('Rule deleted', '', 'ok'); _loadCmdAlerts(); }
        else toast('Delete failed', msgFromError(r2.error), 'error');
      });
    });
  }

  function _openAlertModal(rule) {
    _alertEditId = rule ? rule.id : null;
    $('cmdAlertModalTitle').textContent = rule ? 'Edit Alert Rule' : 'Add Alert Rule';
    $('cmdAlertName').value      = rule ? rule.name      : '';
    $('cmdAlertMetric').value    = rule ? rule.metric     : 'active_threats';
    $('cmdAlertOperator').value  = rule ? rule.operator   : '>';
    $('cmdAlertThreshold').value = rule ? rule.threshold  : '';
    $('cmdAlertSeverity').value  = rule ? rule.severity   : 'medium';
    $('cmdAlertCooldown').value  = rule ? rule.cooldown_min : 30;
    const modal = $('cmdAlertModal');
    modal.style.display = 'flex';
  }

  function _closeAlertModal() {
    $('cmdAlertModal').style.display = 'none';
    _alertEditId = null;
  }

  async function _saveAlertRule() {
    const body = {
      name:         $('cmdAlertName').value.trim(),
      metric:       $('cmdAlertMetric').value,
      operator:     $('cmdAlertOperator').value,
      threshold:    parseFloat($('cmdAlertThreshold').value),
      severity:     $('cmdAlertSeverity').value,
      cooldown_min: parseInt($('cmdAlertCooldown').value, 10),
    };
    const isEdit = Boolean(_alertEditId);
    const r = await api(
      isEdit ? `/api/v1/alert-rules/${_alertEditId}` : '/api/v1/alert-rules',
      { method: isEdit ? 'PATCH' : 'POST', body: JSON.stringify(body) }
    );
    if (r.ok || r.id) {
      toast(isEdit ? 'Rule updated' : 'Rule created', body.name, 'ok');
      _closeAlertModal();
      _loadCmdAlerts();
    } else {
      toast('Save failed', msgFromError(r.error || r.detail), 'error');
    }
  }

  // -- Outbound Webhooks --------------------------------------------------------

  let _whReady = false;
  let _whEditId = null;

  function initWebhooksView() {
    _loadWebhooks();
    if (_whReady) return;
    _whReady = true;

    $('whAddBtn')?.addEventListener('click', () => _openWhModal(null));
    $('whCancelBtn')?.addEventListener('click', _closeWhModal);
    $('whModal')?.addEventListener('click', (e) => { if (e.target === $('whModal')) _closeWhModal(); });
    $('whForm')?.addEventListener('submit', async (e) => { e.preventDefault(); await _saveWebhook(); });
    $('whTestBtn')?.addEventListener('click', _testWebhook);
  }

  async function _loadWebhooks() {
    const statsEl = $('whStats');
    const listEl  = $('whList');
    if (!listEl) return;

    const [whR, telR] = await Promise.all([
      api('/api/v1/webhooks'),
      api('/api/v1/telemetry/summary'),
    ]);

    if (statsEl) {
      const webhooks = whR.ok ? (whR.webhooks || []) : [];
      const active   = webhooks.filter(w => w.is_active).length;
      statsEl.innerHTML = `
        <div class="intel-card" style="min-width:130px;">
          <div class="intel-card-label">Total Webhooks</div>
          <div class="intel-card-value">${webhooks.length}</div>
        </div>
        <div class="intel-card" style="min-width:130px;">
          <div class="intel-card-label">Active</div>
          <div class="intel-card-value" style="color:var(--ok)">${active}</div>
        </div>
        <div class="intel-card" style="min-width:130px;">
          <div class="intel-card-label">Inactive</div>
          <div class="intel-card-value" style="color:var(--text-muted)">${webhooks.length - active}</div>
        </div>`;
    }

    if (!whR.ok) {
      listEl.innerHTML = `<div class="empty-state">Failed to load webhooks.</div>`;
      return;
    }

    const webhooks = whR.webhooks || [];
    if (!webhooks.length) {
      listEl.innerHTML = `<div class="empty-state">No webhooks configured yet. Click <strong>+ Add Webhook</strong> to push platform events to Slack, PagerDuty or any HTTP endpoint.</div>`;
      return;
    }

    listEl.innerHTML = `<div style="display:grid;gap:12px;">${webhooks.map(wh => `
      <div class="panel" style="padding:16px 18px;">
        <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;">
          <div style="display:flex;align-items:center;gap:10px;">
            <span style="width:8px;height:8px;border-radius:50%;background:${wh.is_active ? 'var(--ok)' : 'var(--text-muted)'};flex-shrink:0;"></span>
            <div>
              <div style="font-size:14px;font-weight:600;">${esc(wh.name)}</div>
              <div style="font-size:11px;color:var(--text-muted);word-break:break-all;">${esc(wh.url)}</div>
            </div>
          </div>
          <div style="display:flex;gap:8px;flex-shrink:0;">
            <button class="btn sm" type="button" data-wh-deliveries="${esc(wh.id)}">Deliveries</button>
            <button class="btn sm" type="button" data-wh-edit="${esc(wh.id)}">Edit</button>
            <button class="btn sm danger" type="button" data-wh-del="${esc(wh.id)}">Delete</button>
          </div>
        </div>
        <div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap;">
          <span style="font-size:11px;background:var(--accent-subtle);color:var(--accent);padding:2px 8px;border-radius:10px;">${esc((wh.events || []).join(', '))}</span>
          <span style="font-size:11px;background:var(--surface-alt);color:var(--text-muted);padding:2px 8px;border-radius:10px;">min: ${esc(wh.min_severity)}</span>
          ${wh.secret ? `<span style="font-size:11px;background:var(--surface-alt);color:var(--text-muted);padding:2px 8px;border-radius:10px;">HMAC signed</span>` : ''}
        </div>
      </div>`).join('')}</div>`;

    listEl.querySelectorAll('[data-wh-edit]').forEach(btn => {
      btn.addEventListener('click', () => {
        const wh = webhooks.find(w => w.id === btn.dataset.whEdit);
        if (wh) _openWhModal(wh);
      });
    });
    listEl.querySelectorAll('[data-wh-del]').forEach(btn => {
      btn.addEventListener('click', async () => {
        if (!confirm('Delete this webhook?')) return;
        const r = await api(`/api/v1/webhooks/${btn.dataset.whDel}`, { method: 'DELETE' });
        if (r.ok || r.status === 204) { toast('Webhook deleted', '', 'ok'); _loadWebhooks(); }
        else toast('Delete failed', msgFromError(r.error), 'error');
      });
    });
    listEl.querySelectorAll('[data-wh-deliveries]').forEach(btn => {
      btn.addEventListener('click', async () => {
        const r = await api(`/api/v1/webhooks/${btn.dataset.whDeliveries}/deliveries`);
        if (!r.ok) { toast('Failed', msgFromError(r.error), 'error'); return; }
        const deliveries = r.deliveries || [];
        if (!deliveries.length) { toast('No deliveries', 'No delivery attempts logged yet.', 'info'); return; }
        const rows = deliveries.slice(0, 20).map(d => `
          <tr>
            <td style="font-size:11px;">${esc(d.event_type)}</td>
            <td style="text-align:center;"><span style="color:${d.success ? 'var(--ok)' : 'var(--danger)'}">${d.success ? 'OK' : 'Failed'}</span></td>
            <td style="text-align:center;">${d.status_code ?? ' - '}</td>
            <td style="text-align:right;">${d.duration_ms}ms</td>
            <td style="font-size:10px;color:var(--text-muted);">${d.attempt > 1 ? `retry ${d.attempt}` : 'first'}</td>
          </tr>`).join('');
        const modal = document.createElement('div');
        modal.style.cssText = 'position:fixed;inset:0;z-index:910;background:rgba(0,0,0,.5);display:flex;align-items:center;justify-content:center;';
        modal.innerHTML = `<div style="background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:24px;width:min(640px,95vw);max-height:80vh;overflow-y:auto;">
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;">
            <h3 style="font-size:14px;font-weight:700;margin:0;">Delivery Log (last ${deliveries.length})</h3>
            <button type="button" style="background:none;border:none;font-size:18px;cursor:pointer;color:var(--text-muted);">x</button>
          </div>
          <table style="width:100%;border-collapse:collapse;font-size:12px;">
            <thead><tr style="color:var(--text-muted);border-bottom:1px solid var(--border);">
              <th style="text-align:left;padding:4px 0;">Event</th><th>OK</th><th>Status</th><th>Duration</th><th>Attempt</th>
            </tr></thead><tbody>${rows}</tbody>
          </table></div>`;
        modal.querySelector('button').addEventListener('click', () => document.body.removeChild(modal));
        modal.addEventListener('click', (e) => { if (e.target === modal) document.body.removeChild(modal); });
        document.body.appendChild(modal);
      });
    });
  }

  function _openWhModal(wh) {
    _whEditId = wh ? wh.id : null;
    $('whModalTitle').textContent = wh ? 'Edit Webhook' : 'Add Webhook';
    $('whName').value     = wh ? wh.name : '';
    $('whUrl').value      = wh ? wh.url  : '';
    $('whEvents').value   = wh ? (wh.events || ['*']).join(', ') : '*';
    $('whSeverity').value = wh ? (wh.min_severity || 'low') : 'low';
    $('whSecret').value   = wh ? (wh.secret || '') : '';
    $('whTestResult').style.display = 'none';
    const modal = $('whModal');
    modal.style.display = 'flex';
  }

  function _closeWhModal() {
    $('whModal').style.display = 'none';
    _whEditId = null;
  }

  async function _saveWebhook() {
    const body = {
      name:         $('whName').value.trim(),
      url:          $('whUrl').value.trim(),
      events:       $('whEvents').value.split(',').map(s => s.trim()).filter(Boolean),
      min_severity: $('whSeverity').value,
      secret:       $('whSecret').value.trim(),
    };
    const isEdit = Boolean(_whEditId);
    const r = await api(
      isEdit ? `/api/v1/webhooks/${_whEditId}` : '/api/v1/webhooks',
      { method: isEdit ? 'PATCH' : 'POST', body: JSON.stringify(body) }
    );
    if (r.ok || r.id) {
      toast(isEdit ? 'Webhook updated' : 'Webhook created', body.name, 'ok');
      _closeWhModal();
      _loadWebhooks();
    } else {
      toast('Save failed', msgFromError(r.error || r.detail), 'error');
    }
  }

  async function _testWebhook() {
    const url    = $('whUrl').value.trim();
    const secret = $('whSecret').value.trim();
    if (!url) { toast('URL required', '', 'error'); return; }
    const resultEl = $('whTestResult');
    resultEl.innerHTML = '<div class="spinner" style="width:16px;height:16px;"></div>';
    resultEl.style.display = 'flex';
    const r = await api('/api/v1/webhooks/test', {
      method: 'POST',
      body: JSON.stringify({ url, secret, event_type: 'test.ping' }),
    });
    if (r.ok !== undefined) {
      const col = r.ok ? 'var(--ok)' : 'var(--danger)';
      resultEl.innerHTML = `<div style="font-size:12px;color:${col};padding:8px 0;">
        ${r.ok ? 'OK Success' : 'Failed Failed'}  -  HTTP ${r.status_code ?? 'N/A'} in ${r.duration_ms}ms
        ${r.error ? `<br><span style="color:var(--text-muted);">${esc(r.error)}</span>` : ''}
      </div>`;
    } else {
      resultEl.innerHTML = `<div style="font-size:12px;color:var(--danger);">Request error</div>`;
    }
  }

  // -- Autonomous Agents ---------------------------------------------------------
  let _agentsReady = false;
  let _agentsStartupRefreshes = 0;

  function initAgentsView() {
    if (!_agentsReady) {
      _agentsReady = true;
      $('agentsRefreshBtn')?.addEventListener('click', loadAgentsDashboard);
      $('agentGrid')?.addEventListener('click', event => {
        const trigger = event.target.closest('[data-agent-trigger]');
        if (trigger) {
          runAgentNow(trigger.dataset.agentTrigger, trigger);
          return;
        }
        const toggle = event.target.closest('[data-agent-toggle]');
        if (toggle) {
          toggleAgentPaused(toggle.dataset.agentToggle, toggle.dataset.agentPaused === '1', toggle);
        }
      });
    }
    loadAgentsDashboard();
  }

  async function loadAgentsDashboard() {
    const grid = $('agentGrid');
    const feed = $('agentActionFeed');
    const kpis = $('agentKpiStrip');
    if (grid) grid.innerHTML = '<div class="empty-state"><div class="spinner"></div></div>';
    if (feed) feed.innerHTML = '<div class="empty-state"><p>Loading...</p></div>';
    if (kpis) kpis.innerHTML = '';

    const refreshBtn = $('agentsRefreshBtn');
    if (refreshBtn) refreshBtn.disabled = true;
    const [healthR, actionsR] = await Promise.all([
      api('/api/v1/agents/health'),
      api('/api/v1/agents/actions?limit=30'),
    ]);
    if (refreshBtn) refreshBtn.disabled = false;

    if (!healthR.ok) {
      if (grid) grid.innerHTML = `<div class="empty-state"><h3>Agents unavailable</h3><p>${esc(msgFromError(healthR.error))}</p></div>`;
      if (feed) feed.innerHTML = '<div class="empty-state"><p>No agent action data loaded.</p></div>';
      const supervisor = $('agentSupervisorState');
      if (supervisor) {
        supervisor.textContent = 'Unavailable';
        supervisor.className = 'agent-supervisor-state bad';
      }
      return;
    }

    const health = healthR.data || {};
    renderAgentsDashboard(health, actionsR.ok ? (actionsR.data.actions || []) : []);
    if (health.supervisor_running) {
      _agentsStartupRefreshes = 0;
    } else if ((health.agents || []).length && _agentsStartupRefreshes < 2) {
      _agentsStartupRefreshes += 1;
      setTimeout(loadAgentsDashboard, 1500);
    }
  }

  function agentRuntimeLabel(agent) {
    if (!agent.enabled) return 'Disabled';
    if (agent.running && !agent.paused) return 'Running';
    if (agent.paused) return 'Paused';
    if (agent.start_blocked_reason) return 'Blocked';
    return 'Stopped';
  }

  function agentRuntimeTone(agent) {
    if (!agent.enabled) return 'neutral';
    if (agent.error_count > 0 || agent.start_blocked_reason) return 'bad';
    if (agent.paused) return 'warn';
    if (agent.running) return 'ok';
    return 'neutral';
  }

  function agentTimeLabel(value) {
    if (!value) return 'Not yet';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return 'Not yet';
    return date.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  }

  function agentIntervalLabel(seconds) {
    const total = Number(seconds) || 0;
    if (total <= 0) return 'Manual';
    if (total < 60) return `${total}s`;
    const minutes = Math.round(total / 60);
    if (minutes < 60) return `${minutes}m`;
    return `${Math.round(minutes / 60)}h`;
  }

  function agentLimitsLabel(limits) {
    const entries = Object.entries(limits || {}).filter(([, value]) => value !== undefined && value !== null && value !== '');
    if (!entries.length) return 'Default';
    return entries.slice(0, 2).map(([key, value]) => `${key}: ${value}`).join(' / ');
  }

  function renderAgentsDashboard(health, actions) {
    const agents = health.agents || [];
    const supervisor = $('agentSupervisorState');
    if (supervisor) {
      const healthy = Boolean(health.healthy);
      supervisor.textContent = health.supervisor_running ? (healthy ? 'Healthy' : 'Needs attention') : 'Stopped';
      supervisor.className = `agent-supervisor-state ${healthy ? 'ok' : health.supervisor_running ? 'warn' : 'bad'}`;
    }

    const kpis = $('agentKpiStrip');
    if (kpis) {
      const kpiItems = [
        { label: 'Total Agents', value: health.total_agents ?? agents.length, tone: 'accent' },
        { label: 'Running', value: health.running ?? agents.filter(agent => agent.running && !agent.paused).length, tone: 'ok' },
        { label: 'Paused', value: health.paused ?? agents.filter(agent => agent.paused).length, tone: 'warn' },
        { label: 'Errors', value: health.errored ?? agents.filter(agent => agent.error_count > 0).length, tone: 'bad' },
        { label: 'Profile', value: health.low_resource ? 'Low Resource' : esc(health.profile || 'Standard'), tone: 'neutral' },
      ];
      kpis.innerHTML = kpiItems.map(item => `
        <div class="agent-kpi-card ${item.tone}">
          <span>${esc(item.label)}</span>
          <strong>${esc(item.value)}</strong>
        </div>
      `).join('');
    }

    const grid = $('agentGrid');
    if (grid) {
      if (!agents.length) {
        grid.innerHTML = '<div class="empty-state"><h3>No agents registered</h3><p>The agent supervisor did not return any registered agents.</p></div>';
      } else {
        grid.innerHTML = agents.map(agent => {
          const tone = agentRuntimeTone(agent);
          const label = agentRuntimeLabel(agent);
          const runDisabled = !agent.enabled ? 'disabled' : '';
          return `
            <article class="agent-card ${tone}" data-agent-id="${esc(agent.id)}">
              <div class="agent-card-head">
                <div class="agent-title-wrap">
                  <strong>${esc(agent.name)}</strong>
                  <span>${esc(agent.domain || 'general')}</span>
                </div>
                <span class="agent-status-pill ${tone}">${esc(label)}</span>
              </div>
              <p class="agent-description">${esc(agent.description || 'Operational agent')}</p>
              <div class="agent-meta-grid">
                <span><b>Runs</b><small>${esc(agent.run_count ?? 0)}</small></span>
                <span><b>Interval</b><small>${esc(agentIntervalLabel(agent.interval_s))}</small></span>
                <span><b>Last Run</b><small>${esc(agentTimeLabel(agent.last_run))}</small></span>
                <span><b>Next Run</b><small>${esc(agentTimeLabel(agent.next_run))}</small></span>
                <span><b>Policy</b><small>${agent.enabled ? (agent.auto_start ? 'Autostart' : 'Manual Start') : 'Disabled'}</small></span>
                <span><b>Limits</b><small>${esc(agentLimitsLabel(agent.limits))}</small></span>
              </div>
              ${agent.last_error ? `<div class="agent-error-line">${esc(agent.last_error)}</div>` : ''}
              <div class="agent-card-actions">
                <button class="btn sm" type="button" data-agent-trigger="${esc(agent.id)}" ${runDisabled}>Run Now</button>
                <button class="btn sm ghost" type="button" data-agent-toggle="${esc(agent.id)}" data-agent-paused="${agent.paused ? '1' : '0'}">${agent.paused ? 'Resume' : 'Pause'}</button>
              </div>
            </article>
          `;
        }).join('');
      }
    }

    renderAgentActionFeed(actions);
  }

  function renderAgentActionFeed(actions) {
    const feed = $('agentActionFeed');
    if (!feed) return;
    if (!actions.length) {
      feed.innerHTML = '<div class="empty-state"><p>No recent agent actions.</p></div>';
      return;
    }
    const toneForSeverity = { critical: 'bad', high: 'bad', medium: 'warn', low: 'neutral', info: 'neutral' };
    feed.innerHTML = actions.map(action => {
      const tone = toneForSeverity[action.severity] || 'neutral';
      return `
        <div class="agent-action-item ${tone}">
          <div>
            <span class="agent-action-meta">
              <b>${esc(action.agent_name || action.agent_id || 'Agent')}</b>
              <small>${esc(action.action_type || 'action')}</small>
            </span>
            <strong>${esc(action.title || 'Agent action')}</strong>
            ${action.detail ? `<p>${esc(action.detail)}</p>` : ''}
          </div>
          <time>${esc(agentTimeLabel(action.created_at))}</time>
        </div>
      `;
    }).join('');
  }

  async function runAgentNow(agentId, button) {
    if (!agentId) return;
    if (button) {
      button.disabled = true;
      button.textContent = 'Running...';
    }
    const result = await api(`/api/v1/agents/${encodeURIComponent(agentId)}/trigger`, { method: 'POST' });
    if (result.ok) {
      toast('Agent triggered', `${agentId} run cycle dispatched.`, 'ok');
      setTimeout(loadAgentsDashboard, 1200);
    } else {
      toast('Agent trigger failed', msgFromError(result.error), 'error');
      if (button) {
        button.disabled = false;
        button.textContent = 'Run Now';
      }
    }
  }

  async function toggleAgentPaused(agentId, paused, button) {
    if (!agentId) return;
    if (button) button.disabled = true;
    const action = paused ? 'resume' : 'pause';
    const result = await api(`/api/v1/agents/${encodeURIComponent(agentId)}/${action}`, { method: 'POST' });
    if (result.ok) {
      toast(paused ? 'Agent resumed' : 'Agent paused', agentId, 'ok');
      loadAgentsDashboard();
    } else {
      toast('Agent state change failed', msgFromError(result.error), 'error');
      if (button) button.disabled = false;
    }
  }

  // -- Operational Command Center -----------------------------------------------
  let _cmdReady = false;
  let _cmdWs    = null;
  let _cmdTimelineEvents = [];

  function initCommandCenterView() {
    if (_cmdReady) {
      const activeTab = document.querySelector('#view-command .ocr-tab.active')?.dataset?.cmdTab;
      if (activeTab === 'intelligence') { _loadCmdIntelligence(); }
      if (activeTab === 'timeline')     { _connectCmdTimeline(); }
      if (activeTab === 'agents')       { _loadCmdAgents(); }
      if (activeTab === 'health')       { _loadCmdHealth(); }
      if (activeTab === 'alerts')       { _loadCmdAlerts(); }
      if (activeTab === 'audit')        { _loadAuditLog(); }
      if (activeTab === 'incidents')    { _loadIncidents(); }
      return;
    }
    _cmdReady = true;
    _setupCmdTabs();
    _loadCmdIntelligence();
    _connectCmdTimeline();
  }

  function _setupCmdTabs() {
    const section = $('view-command');
    if (!section) return;
    const tabs   = $$('.ocr-tab', section);
    const panels = $$('.ocr-panel', section);

    tabs.forEach(tab => {
      tab.addEventListener('click', () => {
        const id = tab.dataset.cmdTab;
        tabs.forEach(t => { t.classList.remove('active'); t.setAttribute('aria-selected', 'false'); });
        panels.forEach(p => p.classList.remove('active'));
        tab.classList.add('active');
        tab.setAttribute('aria-selected', 'true');
        const panel = $(`cmdTab-${id}`);
        if (panel) panel.classList.add('active');
        if (id === 'intelligence') _loadCmdIntelligence();
        if (id === 'timeline')     _connectCmdTimeline();
        if (id === 'agents')       { _loadCmdAgents(); _loadCmdAgentActions(); }
        if (id === 'health')       _loadCmdHealth();
        if (id === 'alerts')       _loadCmdAlerts();
        if (id === 'audit')        _loadAuditLog();
        if (id === 'incidents')    _loadIncidents();
      });
    });

    $('cmdAnalyzeBtn')?.addEventListener('click', async () => {
      const btn = $('cmdAnalyzeBtn');
      if (btn) { btn.disabled = true; btn.textContent = 'Analysing...'; }
      const r = await api('/api/v1/intelligence/analyze', { method: 'POST' });
      if (r.ok) {
        toast('Analysis dispatched', 'Findings will appear in the timeline shortly.', 'ok');
        setTimeout(_loadCmdIntelligence, 2000);
      } else {
        toast('Analysis failed', msgFromError(r.error), 'error');
      }
      if (btn) { btn.disabled = false; btn.textContent = 'Run Analysis'; }
    });

    $('cmdRefreshAgentsBtn')?.addEventListener('click', () => { _loadCmdAgents(); _loadCmdAgentActions(); });
    $('cmdClearTimelineBtn')?.addEventListener('click', () => {
      _cmdTimelineEvents = [];
      const list = $('cmdTimelineList');
      if (list) list.innerHTML = '<div class="empty-state"><p>Timeline cleared. New events will appear as they arrive.</p></div>';
    });
  }

  // -- Intelligence tab --------------------------------------------------------

  async function _loadCmdIntelligence() {
    const [healthR, insightR, predR] = await Promise.all([
      api('/api/v1/intelligence/health'),
      api('/api/v1/intelligence/insights'),
      api('/api/v1/intelligence/predictions'),
    ]);

    // Health strip
    const strip = $('cmdHealthStrip');
    if (strip && healthR.ok) {
      const h = healthR.data;
      const scoreColor = h.overall >= 85 ? 'ok' : h.overall >= 70 ? 'neutral' : h.overall >= 50 ? 'warn' : 'bad';
      strip.innerHTML = `
        <div style="display:flex;align-items:center;gap:10px;background:var(--surface-raised);border:1px solid var(--border);border-radius:8px;padding:10px 20px;">
          <div style="font-size:34px;font-weight:800;color:var(--accent);">${h.overall}</div>
          <div>
            <div style="font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.5px;color:var(--text-muted);">Health Score</div>
            <span class="badge ${scoreColor}" style="margin-top:2px;">${h.status}</span>
          </div>
        </div>
        ${Object.entries(h.components || {}).map(([key, comp]) => `
          <div style="background:var(--surface-raised);border:1px solid var(--border);border-radius:8px;padding:10px 14px;min-width:130px;">
            <div style="font-size:19px;font-weight:700;color:var(--accent);">${comp.score}%</div>
            <div style="font-size:11px;color:var(--text-muted);margin-top:1px;">${esc(comp.label)}</div>
          </div>`).join('')}`;
    }

    // Insights
    const insightList = $('cmdInsightList');
    if (insightList && insightR.ok) {
      const items = insightR.data.insights || [];
      if (!items.length) {
        insightList.innerHTML = '<div class="empty-state"><h3>All systems nominal</h3><p>No operational insights at this time. The platform is running optimally.</p></div>';
      } else {
        const SEV_BADGE = { critical: 'bad', high: 'bad', medium: 'warn', low: 'neutral' };
        const TYPE_ICON = {
          anomaly:     '!',
          security:    'ðŸ›¡',
          opportunity: '*',
          pattern:     '*',
        };
        insightList.innerHTML = items.map(ins => `
          <div class="activity-item" style="padding:12px;border-bottom:1px solid var(--border-soft);">
            <div style="display:flex;flex-direction:column;gap:3px;flex:1;">
              <div style="display:flex;align-items:center;gap:6px;">
                <span style="font-size:13px;">${TYPE_ICON[ins.type] || '*'}</span>
                <strong style="font-size:13px;">${esc(ins.title)}</strong>
                <span class="badge ${SEV_BADGE[ins.severity] || 'neutral'}" style="font-size:10px;">${esc(ins.severity)}</span>
              </div>
              <span style="font-size:12px;color:var(--text-muted);">${esc(ins.description)}</span>
              ${ins.action ? `<span style="font-size:11px;color:var(--accent);margin-top:2px;">-> ${esc(ins.action)}</span>` : ''}
            </div>
            ${ins.action_type === 'activate_workflow' ? `
              <button class="btn sm" type="button" data-activate-workflow="${esc(ins.action_target)}" style="flex-shrink:0;">Activate</button>
            ` : ins.action_type === 'navigate' ? `
              <button class="btn sm ghost" type="button" data-open-view="${esc(ins.action_target)}" style="flex-shrink:0;">Open</button>
            ` : ''}
          </div>`).join('');

        // Wire activate workflow buttons
        insightList.querySelectorAll('[data-activate-workflow]').forEach(btn => {
          btn.addEventListener('click', async () => {
            const tmplId = btn.dataset.activateWorkflow;
            btn.disabled = true; btn.textContent = 'Activating...';
            const r2 = await api('/api/v1/workflows', { method: 'POST', body: JSON.stringify({ template_id: tmplId }) });
            if (r2.ok) {
              toast('Workflow activated', 'Check the Workflows view to manage it.', 'ok');
              btn.textContent = 'Activated';
            } else {
              toast('Activation failed', msgFromError(r2.error), 'error');
              btn.disabled = false; btn.textContent = 'Activate';
            }
          });
        });

        // Wire navigate buttons
        insightList.querySelectorAll('[data-open-view]').forEach(btn => {
          btn.addEventListener('click', () => showView(btn.dataset.openView));
        });
      }
    }

    // Predictions
    const predBox = $('cmdPredictions');
    if (predBox && predR.ok) {
      const preds = predR.data.predictions || [];
      predBox.innerHTML = preds.map(p => `
        <div style="background:var(--surface-raised);border:1px solid var(--border);border-radius:8px;padding:12px 16px;min-width:160px;flex:1;">
          <div style="font-size:24px;font-weight:700;color:var(--accent);">${esc(String(p.value))} <span style="font-size:12px;font-weight:400;color:var(--text-muted);">${esc(p.unit)}</span></div>
          <div style="font-size:12px;font-weight:600;margin:2px 0;">${esc(p.title)}</div>
          <div style="font-size:11px;color:var(--text-muted);">Confidence: ${p.confidence}% Â· ${esc(p.horizon)}</div>
        </div>`).join('') || '<p style="color:var(--text-muted);font-size:13px;">No predictions available yet.</p>';
    }
  }

  // -- Live Timeline tab -------------------------------------------------------

  function _connectCmdTimeline() {
    const statusEl = $('cmdWsStatus');

    if (_cmdWs && _cmdWs.readyState === WebSocket.OPEN) return;
    if (_cmdWs) { try { _cmdWs.close(); } catch (_) {} }

    try {
      const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
      _cmdWs = new WebSocket(`${proto}//${location.host}/api/v1/events/stream`);

      _cmdWs.onopen = () => {
        if (statusEl) { statusEl.textContent = 'Live'; statusEl.className = 'badge ok'; }
      };

      _cmdWs.onclose = () => {
        if (statusEl) { statusEl.textContent = 'Disconnected'; statusEl.className = 'badge neutral'; }
        // Reconnect after 5s
        setTimeout(() => {
          if (state.currentView === 'command') _connectCmdTimeline();
        }, 5000);
      };

      _cmdWs.onerror = () => {
        if (statusEl) { statusEl.textContent = 'Error'; statusEl.className = 'badge bad'; }
      };

      _cmdWs.onmessage = (msg) => {
        try {
          const data = JSON.parse(msg.data);
          const event = data.event;
          if (!event || event.type === 'heartbeat' || event.type === 'connection_ack' || event.type === 'pong') return;
          _cmdTimelineEvents.unshift(event);
          if (_cmdTimelineEvents.length > 200) _cmdTimelineEvents.pop();
          _renderTimelineEvent(event);
        } catch (_) {}
      };

      // Load recent history on connect
      _loadTimelineHistory();

    } catch (err) {
      if (statusEl) { statusEl.textContent = 'Unavailable'; statusEl.className = 'badge neutral'; }
    }
  }

  async function _loadTimelineHistory() {
    const r = await api('/api/v1/events/history?limit=50');
    if (!r.ok) return;
    const events = (r.data.events || []).reverse();
    const list = $('cmdTimelineList');
    if (!list) return;
    if (!events.length) {
      list.innerHTML = '<div class="empty-state"><p>No events yet  -  agents will begin emitting events shortly.</p></div>';
      return;
    }
    list.innerHTML = '';
    events.forEach(ev => _renderTimelineEvent(ev, true));
  }

  function _renderTimelineEvent(event, prepend = false) {
    const list = $('cmdTimelineList');
    if (!list) return;

    // Remove empty state if present
    const empty = list.querySelector('.empty-state');
    if (empty) empty.remove();

    const SEV_BADGE = { critical: 'bad', high: 'bad', medium: 'warn', low: 'neutral' };
    const TYPE_LABEL = {
      'workflow.executed':        'Workflow Run',
      'workflow.failed':          'Workflow Failed',
      'threat.detected':          'Threat Detected',
      'threat.escalated':         'Threat Escalated',
      'agent.action':             'Agent Action',
      'agent.insight':            'Insight',
      'agent.anomaly':            'Anomaly',
      'intelligence.anomaly':     'Intelligence',
      'intelligence.recommendation': 'Recommendation',
      'system.health_check':      'Health Check',
      'system.circuit_open':      'Circuit Open',
      'system.circuit_closed':    'Circuit Closed',
      'ocr.completed':            'OCR Complete',
      'email.classified':         'Email Classified',
    };

    const label     = TYPE_LABEL[event.type] || event.type;
    const sev       = event.severity || 'low';
    const badge     = SEV_BADGE[sev] || 'neutral';
    const source    = event.source || ' - ';
    const time      = event.created_at ? new Date(event.created_at).toLocaleTimeString() : '';
    const payload   = event.payload || {};
    const detail    = payload.title || payload.detail || payload.message || payload.description || JSON.stringify(payload).slice(0, 120);

    const el = document.createElement('div');
    el.className = 'activity-item';
    el.style.cssText = 'padding:10px 12px;border-bottom:1px solid var(--border-soft);animation:fadeInDown .2s ease;';
    el.innerHTML = `
      <div style="display:flex;flex-direction:column;gap:2px;flex:1;min-width:0;">
        <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
          <span class="badge ${badge}" style="font-size:10px;">${esc(sev)}</span>
          <strong style="font-size:12px;">${esc(label)}</strong>
          <span style="font-size:11px;color:var(--text-muted);">from ${esc(source)}</span>
        </div>
        ${detail ? `<span style="font-size:12px;color:var(--text-muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${esc(detail)}">${esc(detail)}</span>` : ''}
      </div>
      <span style="font-size:11px;color:var(--text-muted);white-space:nowrap;margin-left:8px;">${time}</span>`;

    if (prepend) {
      list.insertBefore(el, list.firstChild);
    } else {
      list.insertBefore(el, list.firstChild);
      // Keep list bounded
      while (list.children.length > 200) list.removeChild(list.lastChild);
    }
  }

  // -- Agents tab --------------------------------------------------------------

  async function _loadCmdAgents() {
    const list = $('cmdAgentList');
    if (!list) return;
    list.innerHTML = '<div class="empty-state"><div class="spinner"></div></div>';
    const r = await api('/api/v1/agents');
    if (!r.ok) {
      list.innerHTML = `<div class="empty-state"><p>Failed to load agents: ${esc(msgFromError(r.error))}</p></div>`;
      return;
    }
    const agents = r.data.agents || [];
    list.innerHTML = agents.map(ag => `
      <div class="activity-item" style="padding:12px;border-bottom:1px solid var(--border-soft);" data-agent-id="${esc(ag.id)}">
        <div style="flex:1;">
          <div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;">
            <strong style="font-size:13px;">${esc(ag.name)}</strong>
            <span class="badge ${ag.running && !ag.paused ? 'ok' : ag.paused ? 'warn' : 'neutral'}">${ag.running && !ag.paused ? 'Running' : ag.paused ? 'Paused' : 'Stopped'}</span>
            ${ag.error_count > 0 ? `<span class="badge bad">${ag.error_count} error(s)</span>` : ''}
          </div>
          <p style="font-size:12px;color:var(--text-muted);margin:0 0 4px;">${esc(ag.description)}</p>
          <div style="font-size:11px;color:var(--text-muted);display:flex;gap:16px;flex-wrap:wrap;">
            <span>Domain: <strong>${esc(ag.domain)}</strong></span>
            <span>Runs: <strong>${ag.run_count}</strong></span>
            <span>Interval: <strong>${ag.interval_s}s</strong></span>
            <span>Last run: <strong>${ag.last_run ? new Date(ag.last_run).toLocaleTimeString() : 'Not yet'}</strong></span>
          </div>
        </div>
        <div style="display:flex;gap:6px;flex-shrink:0;align-items:flex-start;">
          <button class="btn sm agent-trigger-btn" type="button" data-agent-id="${esc(ag.id)}">Trigger</button>
          <button class="btn sm ghost agent-pause-btn" type="button" data-agent-id="${esc(ag.id)}" data-paused="${ag.paused ? '1' : '0'}">${ag.paused ? 'Resume' : 'Pause'}</button>
        </div>
      </div>`).join('');

    list.querySelectorAll('.agent-trigger-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        const id = btn.dataset.agentId;
        btn.disabled = true; btn.textContent = 'Running...';
        const r2 = await api(`/api/v1/agents/${id}/trigger`, { method: 'POST' });
        if (r2.ok) {
          toast('Agent triggered', `${id} cycle dispatched.`, 'ok');
          setTimeout(_loadCmdAgentActions, 1500);
        } else {
          toast('Trigger failed', msgFromError(r2.error), 'error');
        }
        btn.disabled = false; btn.textContent = 'Trigger';
      });
    });

    list.querySelectorAll('.agent-pause-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        const id     = btn.dataset.agentId;
        const paused = btn.dataset.paused === '1';
        const r2 = await api(`/api/v1/agents/${id}/${paused ? 'resume' : 'pause'}`, { method: 'POST' });
        if (r2.ok) { toast(paused ? 'Resumed' : 'Paused', '', 'ok'); _loadCmdAgents(); }
        else { toast('Failed', msgFromError(r2.error), 'error'); }
      });
    });
  }

  async function _loadCmdAgentActions() {
    const box = $('cmdAgentActions');
    if (!box) return;
    const r = await api('/api/v1/agents/actions?limit=30');
    if (!r.ok) { box.innerHTML = `<p style="padding:12px;color:var(--text-muted);">Failed: ${esc(msgFromError(r.error))}</p>`; return; }
    const actions = r.data.actions || [];
    if (!actions.length) {
      box.innerHTML = '<div class="empty-state"><p>No agent actions yet. Trigger an agent above to see its output here.</p></div>';
      return;
    }
    const SEV_BADGE = { critical: 'bad', high: 'bad', medium: 'warn', low: 'neutral' };
    box.innerHTML = actions.map(a => `
      <div class="activity-item" style="padding:10px 12px;border-bottom:1px solid var(--border-soft);">
        <div style="flex:1;">
          <div style="display:flex;align-items:center;gap:6px;margin-bottom:2px;">
            <span class="badge ${SEV_BADGE[a.severity] || 'neutral'}" style="font-size:10px;">${esc(a.severity || 'low')}</span>
            <strong style="font-size:12px;">${esc(a.title || a.action_type)}</strong>
            <span style="font-size:11px;color:var(--text-muted);">${esc(a.agent_name || a.agent_id)}</span>
          </div>
          ${a.detail ? `<span style="font-size:12px;color:var(--text-muted);">${esc(a.detail)}</span>` : ''}
        </div>
        <span style="font-size:11px;color:var(--text-muted);white-space:nowrap;margin-left:8px;">${a.created_at ? new Date(a.created_at).toLocaleTimeString() : ''}</span>
      </div>`).join('');
  }

  // -- Health tab --------------------------------------------------------------

  function _svgSparkline(values, min, max, w, h) {
    w = w || 100; h = h || 32;
    if (!values || values.length < 2) {
      return `<svg width="${w}" height="${h}"><line x1="0" y1="${h/2}" x2="${w}" y2="${h/2}" stroke="var(--accent)" stroke-width="1.5" opacity="0.4"/></svg>`;
    }
    const range = (max - min) || 1;
    const pts = values.map((v, i) => {
      const x = (i / (values.length - 1)) * w;
      const y = h - ((v - min) / range) * (h - 6) - 3;
      return x.toFixed(1) + ',' + y.toFixed(1);
    }).join(' ');
    return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" style="display:block;"><polyline points="${pts}" fill="none" stroke="var(--accent)" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/></svg>`;
  }

  const _SPARK_META = {
    active_threats:        { label: 'Active Threats',   warn: v => v >= 10 },
    health_score:          { label: 'Health Score',     warn: v => v < 70 },
    workflow_success_rate: { label: 'WF Success Rate',  warn: v => v < 80 },
    running_agents:        { label: 'Running Agents',   warn: null },
    emails_last_1h:        { label: 'Emails / hr',      warn: null },
    scam_last_24h:         { label: 'Scam Detections',  warn: v => v > 0 },
  };

  async function _loadCmdHealth() {
    const box = $('cmdHealthDetail');
    if (!box) return;
    box.innerHTML = '<div class="empty-state"><div class="spinner"></div></div>';
    const [healthR, anonR, patternsR, reconcR, schedR, sparkR] = await Promise.all([
      api('/api/v1/intelligence/health'),
      api('/api/v1/intelligence/anomalies'),
      api('/api/v1/intelligence/patterns'),
      api('/api/v1/reconciler/status'),
      api('/api/v1/workflow-scheduler/status'),
      api('/api/v1/metric-snapshots/sparklines'),
    ]);
    if (!healthR.ok) {
      box.innerHTML = `<div class="empty-state"><p>Failed: ${esc(msgFromError(healthR.error))}</p></div>`;
      return;
    }
    const h        = healthR.data;
    const anomalies = anonR.ok ? anonR.data.anomalies || [] : [];
    const patterns  = patternsR.ok ? patternsR.data.patterns || [] : [];
    const recStatus  = reconcR.ok ? reconcR.data : null;
    const schedStatus = schedR.ok ? schedR.data : null;
    const sparklines  = sparkR.ok ? (sparkR.data.sparklines || {}) : {};
    const SEV_BADGE = { critical: 'bad', high: 'bad', medium: 'warn', low: 'neutral' };

    const sparklinesHtml = Object.keys(sparklines).length ? `
      <article class="panel" style="margin-bottom:14px;">
        <div class="panel-head"><div><h2>Metric Trends</h2><p>Hourly snapshots  -  last 24 hours</p></div></div>
        <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px;padding:12px;">
          ${Object.entries(_SPARK_META).map(([key, meta]) => {
            const s = sparklines[key] || { values: [], min: 0, max: 0, last: 0, count: 0 };
            const decimals = (key === 'health_score' || key === 'workflow_success_rate') ? 1 : 0;
            const isWarn = meta.warn && s.count > 0 && meta.warn(s.last);
            return `
              <div style="background:var(--bg-deep);border-radius:6px;padding:10px;">
                <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:6px;">
                  <span style="font-size:11px;color:var(--text-muted);">${esc(meta.label)}</span>
                  <strong style="font-size:14px;color:${isWarn ? 'var(--danger,#e55)' : 'inherit'};">${s.count ? Number(s.last).toFixed(decimals) : ' - '}</strong>
                </div>
                ${_svgSparkline(s.values, s.min, s.max)}
                <div style="display:flex;justify-content:space-between;font-size:10px;color:var(--text-muted);margin-top:4px;">
                  <span>${s.count ? Number(s.min).toFixed(0) : ''}</span>
                  <span>${s.count ? s.count + ' pts' : 'No data'}</span>
                  <span>${s.count ? Number(s.max).toFixed(0) : ''}</span>
                </div>
              </div>`;
          }).join('')}
        </div>
      </article>` : '';

    const reconcilerHtml = recStatus ? (() => {
      const s = recStatus;
      const lastRun = s.last_run ? new Date(s.last_run).toLocaleString() : 'Never';
      const summary = s.last_summary || {};
      const issues  = summary.actions || [];
      return `
        <article class="panel" style="margin-bottom:14px;">
          <div class="panel-head">
            <div>
              <h2>Self-Healing Reconciler</h2>
              <p>Automatic drift detection &amp; repair every ${Math.round(s.cycle_interval_s / 60)} minutes</p>
            </div>
            <button class="btn ghost" id="triggerReconcilerBtn" style="font-size:12px;">Run Now</button>
          </div>
          <div class="report-cards" style="margin-bottom:10px;">
            <div class="report-card">
              <span>Status</span>
              <strong><span class="badge ${s.running ? 'ok' : 'bad'}">${s.running ? 'Running' : 'Stopped'}</span></strong>
            </div>
            <div class="report-card">
              <span>Cycles Run</span>
              <strong>${s.run_count}</strong>
            </div>
            <div class="report-card">
              <span>Last Run</span>
              <strong style="font-size:11px;">${esc(lastRun)}</strong>
            </div>
            <div class="report-card">
              <span>Actions Taken</span>
              <strong>${summary.actions_taken || 0}</strong>
            </div>
          </div>
          ${issues.length ? `
            <div class="activity-list">
              ${issues.map(a => `
                <div class="activity-item" style="padding:8px 12px;">
                  <span style="font-size:12px;color:var(--text-muted);">-> ${esc(a)}</span>
                </div>`).join('')}
            </div>` : `<p style="font-size:12px;color:var(--text-muted);padding:0 12px 10px;">No issues in last cycle.</p>`}
        </article>`;
    })() : '';

    box.innerHTML = `
      ${sparklinesHtml}

      <!-- Component health grid -->
      <div class="report-cards" style="margin-bottom:16px;">
        ${Object.entries(h.components || {}).map(([, comp]) => `
          <div class="report-card">
            <span>${esc(comp.label)}</span>
            <strong>${comp.score}%</strong>
            <small style="color:var(--text-muted);font-size:10px;">${esc(comp.detail || '')}</small>
          </div>`).join('')}
      </div>

      ${reconcilerHtml}

      ${schedStatus ? (() => {
        const s = schedStatus;
        const upcoming = s.upcoming || [];
        const nextFire = upcoming[0];
        return `
          <article class="panel" style="margin-bottom:14px;">
            <div class="panel-head">
              <div>
                <h2>Workflow Scheduler</h2>
                <p>${s.scheduled_workflows} scheduled workflow${s.scheduled_workflows !== 1 ? 's' : ''} Â· ${s.checks_run} checks run</p>
              </div>
              <button class="btn ghost" id="triggerSchedulerBtn" style="font-size:12px;">Check Now</button>
            </div>
            <div class="report-cards" style="margin-bottom:10px;">
              <div class="report-card">
                <span>Status</span>
                <strong><span class="badge ${s.running ? 'ok' : 'bad'}">${s.running ? 'Running' : 'Stopped'}</span></strong>
              </div>
              <div class="report-card">
                <span>Scheduled WFs</span>
                <strong>${s.scheduled_workflows}</strong>
              </div>
              ${nextFire ? `<div class="report-card">
                <span>Next Fire</span>
                <strong style="font-size:11px;">${esc(nextFire.workflow_name || '')}</strong>
                <small style="font-size:10px;color:var(--text-muted);">${nextFire.minutes_until != null ? `in ${nextFire.minutes_until} min` : ''}</small>
              </div>` : ''}
              <div class="report-card">
                <span>Recently Fired</span>
                <strong>${(s.recently_fired || []).length}</strong>
              </div>
            </div>
          </article>`;
      })() : ''}

      ${anomalies.length ? `
        <article class="panel" style="margin-bottom:14px;">
          <div class="panel-head"><div><h2>Active Anomalies (${anomalies.length})</h2></div></div>
          <div class="activity-list">
            ${anomalies.map(a => `
              <div class="activity-item" style="padding:10px 12px;">
                <div style="flex:1;">
                  <div style="display:flex;gap:6px;align-items:center;margin-bottom:3px;">
                    <span class="badge ${SEV_BADGE[a.severity] || 'neutral'}">${esc(a.severity)}</span>
                    <strong style="font-size:13px;">${esc(a.title)}</strong>
                  </div>
                  <p style="font-size:12px;color:var(--text-muted);margin:0 0 3px;">${esc(a.description)}</p>
                  ${a.recommended_action ? `<span style="font-size:11px;color:var(--accent);">-> ${esc(a.recommended_action)}</span>` : ''}
                </div>
              </div>`).join('')}
          </div>
        </article>` : `<article class="panel" style="margin-bottom:14px;"><div class="panel-head"><div><h2>Anomalies</h2><p>No active anomalies detected.</p></div></div></article>`}

      ${patterns.length ? `
        <article class="panel">
          <div class="panel-head"><div><h2>Detected Patterns</h2></div></div>
          <div class="report-cards">
            ${patterns.map(p => `
              <div class="report-card">
                <span>${esc(p.title)}</span>
                <strong>${esc(String(p.value))}${esc(p.unit ? ' ' + p.unit : '')}</strong>
                <small style="font-size:10px;color:var(--text-muted);">${esc(p.description || '')}</small>
              </div>`).join('')}
          </div>
        </article>` : ''}`;

    // Wire "Run Now" button (reconciler)
    const triggerBtn = document.getElementById('triggerReconcilerBtn');
    if (triggerBtn) {
      triggerBtn.addEventListener('click', async () => {
        triggerBtn.disabled = true;
        triggerBtn.textContent = 'Running...';
        const r = await api('/api/v1/reconciler/trigger', { method: 'POST' });
        triggerBtn.textContent = r.ok ? 'Dispatched' : 'Error';
        setTimeout(() => _loadCmdHealth(), 2000);
      });
    }

    // Wire "Check Now" button (scheduler)
    const schedBtn = document.getElementById('triggerSchedulerBtn');
    if (schedBtn) {
      schedBtn.addEventListener('click', async () => {
        schedBtn.disabled = true;
        schedBtn.textContent = 'Checking...';
        const r = await api('/api/v1/workflow-scheduler/trigger', { method: 'POST' });
        schedBtn.textContent = r.ok ? 'Done' : 'Error';
        setTimeout(() => _loadCmdHealth(), 1500);
      });
    }
  }

  // -- Playbooks -----------------------------------------------------------------

  let _pbReady = false;
  let _pbEditId = null;
  const _PB_STATUS_BADGE = { completed: 'ok', running: 'neutral', failed: 'bad' };
  const _PB_STEP_BADGE   = { ok: 'ok', error: 'bad', skipped: 'neutral' };

  function playbookTriggerLabel(type) {
    if (type === 'event') return 'Event';
    if (type === 'incident') return 'Incident';
    return 'Manual';
  }

  function playbookMetaText(pb, stepCount) {
    const trigger = playbookTriggerLabel(pb.trigger_type);
    const filter = pb.trigger_filter ? `: ${pb.trigger_filter}` : '';
    const runs = Number(pb.run_count || 0);
    return `${trigger}${filter} - ${stepCount} step${stepCount !== 1 ? 's' : ''} - ${runs} run${runs !== 1 ? 's' : ''}`;
  }

  function initPlaybooksView() {
    _loadPlaybookList();
    _loadPbRuns();
    if (_pbReady) return;
    _pbReady = true;

    $('pbAddBtn')?.addEventListener('click', () => _openPbModal());
    $('pbRefreshBtn')?.addEventListener('click', () => { _loadPlaybookList(); _loadPbRuns(); });
    $('pbCancelBtn')?.addEventListener('click', () => { $('pbModal').style.display = 'none'; _pbEditId = null; });
    $('pbRunModalCloseBtn')?.addEventListener('click', () => { $('pbRunModal').style.display = 'none'; });

    $('pbTriggerType')?.addEventListener('change', () => {
      const t = $('pbTriggerType').value;
      $('pbTriggerFilterRow').style.display = t === 'manual' ? 'none' : '';
      $('pbTriggerFilterLabel').textContent = t === 'incident' ? 'Min severity' : 'Event type';
      $('pbTriggerFilter').placeholder = t === 'incident' ? 'high' : 'alert.threshold.breach';
    });

    $('pbForm')?.addEventListener('submit', async e => {
      e.preventDefault();
      let steps = [];
      try { steps = JSON.parse($('pbSteps').value || '[]'); }
      catch { alert('Steps must be valid JSON.'); return; }
      const body = {
        name:           $('pbName').value.trim(),
        description:    $('pbDesc').value.trim(),
        trigger_type:   $('pbTriggerType').value,
        trigger_filter: $('pbTriggerFilter').value.trim(),
        steps,
        enabled:        true,
      };
      const url    = _pbEditId ? `/api/v1/playbooks/${_pbEditId}` : '/api/v1/playbooks';
      const method = _pbEditId ? 'PATCH' : 'POST';
      const r = await api(url, { method, body: JSON.stringify(body) });
      if (r.ok) {
        $('pbModal').style.display = 'none';
        _pbEditId = null;
        _loadPlaybookList();
      }
    });
  }

  async function _loadPlaybookList() {
    const list = $('pbList');
    if (!list) return;
    const r = await api('/api/v1/playbooks');
    if (!r.ok) { list.innerHTML = '<div class="empty-state"><p>Failed to load.</p></div>'; return; }
    const playbooks = r.data.playbooks || [];
    if (!playbooks.length) {
      list.innerHTML = '<div class="empty-state"><p>No playbooks defined yet. Create one to automate platform responses.</p></div>';
      return;
    }
    list.innerHTML = `
      <div class="playbook-list" role="list">
        ${playbooks.map(pb => {
          const stepCount = (pb.steps || []).length;
          const triggerLabel = playbookTriggerLabel(pb.trigger_type);
          const runCount = Number(pb.run_count || 0);
          return `
            <div class="playbook-item" data-pb-id="${esc(pb.id)}" role="listitem" tabindex="0">
              <div class="playbook-main">
                <div class="playbook-title-row">
                  <span class="playbook-trigger-chip">${esc(triggerLabel)}</span>
                  <strong>${esc(pb.name)}</strong>
                  ${!pb.enabled ? '<span class="badge neutral playbook-status-chip">Disabled</span>' : ''}
                </div>
                <p class="playbook-description">${esc(pb.description || 'No description provided.')}</p>
                <div class="playbook-meta" aria-label="${esc(playbookMetaText(pb, stepCount))}">
                  <span>${esc(triggerLabel)}${pb.trigger_filter ? ': ' + esc(pb.trigger_filter) : ''}</span>
                  <span>${stepCount} step${stepCount !== 1 ? 's' : ''}</span>
                  <span>${runCount} run${runCount !== 1 ? 's' : ''}</span>
                </div>
              </div>
              <div class="playbook-actions">
                <button class="btn sm ghost" data-pb-run="${esc(pb.id)}" type="button">Run</button>
                <button class="btn sm ghost" data-pb-edit="${esc(pb.id)}" type="button">Edit</button>
                <button class="btn sm ghost playbook-delete-btn" data-pb-del="${esc(pb.id)}" type="button">Delete</button>
              </div>
            </div>`;
        }).join('')}
      </div>`;

    list.querySelectorAll('[data-pb-id]').forEach(row => {
      row.addEventListener('click', e => {
        if (e.target.closest('[data-pb-run],[data-pb-edit],[data-pb-del]')) return;
        _loadPbRuns(row.dataset.pbId, playbooks.find(p => p.id === row.dataset.pbId)?.name);
      });
    });
    list.querySelectorAll('[data-pb-run]').forEach(btn => {
      btn.addEventListener('click', async e => {
        e.stopPropagation();
        btn.disabled = true; btn.textContent = '...';
        const r = await api(`/api/v1/playbooks/${btn.dataset.pbRun}/run`, { method: 'POST' });
        btn.textContent = r.ok ? 'Dispatched' : 'Error';
        setTimeout(() => { btn.disabled = false; btn.textContent = 'Run'; _loadPbRuns(); }, 1500);
      });
    });
    list.querySelectorAll('[data-pb-edit]').forEach(btn => {
      btn.addEventListener('click', e => {
        e.stopPropagation();
        _openPbModal(btn.dataset.pbEdit, playbooks.find(p => p.id === btn.dataset.pbEdit));
      });
    });
    list.querySelectorAll('[data-pb-del]').forEach(btn => {
      btn.addEventListener('click', async e => {
        e.stopPropagation();
        if (!confirm('Delete this playbook and all its run history?')) return;
        await api(`/api/v1/playbooks/${btn.dataset.pbDel}`, { method: 'DELETE' });
        _loadPlaybookList();
        _loadPbRuns();
      });
    });
  }

  async function _loadPbRuns(playbookId, playbookName) {
    const list = $('pbRunList');
    const title = $('pbRunsTitle');
    if (!list) return;
    if (title) title.textContent = playbookName ? `Runs  -  ${playbookName}` : 'Recent Runs';
    list.innerHTML = '<div class="empty-state"><div class="spinner"></div></div>';

    const url = playbookId
      ? `/api/v1/playbooks/runs?limit=20&playbook_id=${encodeURIComponent(playbookId)}`
      : '/api/v1/playbooks/runs?limit=20';
    const r = await api(url);
    if (!r.ok) { list.innerHTML = '<div class="empty-state"><p>Failed to load runs.</p></div>'; return; }
    const runs = r.data.runs || [];
    if (!runs.length) {
      list.innerHTML = '<div class="empty-state"><p>No runs yet.</p></div>';
      return;
    }
    list.innerHTML = `
      <div class="playbook-run-list" role="list">
        ${runs.map(run => {
          const badge = _PB_STATUS_BADGE[run.status] || 'neutral';
          const ts    = run.started_at ? new Date(run.started_at).toLocaleString() : '';
          const dur   = (run.started_at && run.finished_at)
            ? `${((new Date(run.finished_at) - new Date(run.started_at)) / 1000).toFixed(1)}s`
            : (run.status === 'running' ? 'running...' : ' - ');
          return `
            <div class="playbook-run-item" data-run-id="${esc(run.id)}" role="listitem" tabindex="0">
              <span class="badge ${badge} playbook-run-status">${esc(run.status)}</span>
              <div class="playbook-run-main">
                <strong>${esc(run.playbook_name)}</strong>
                <p class="playbook-meta">
                  <span>${esc(run.triggered_by)}</span>
                  <span>${run.steps_done}/${run.steps_total} steps</span>
                  <span>${esc(dur)}</span>
                </p>
              </div>
              <span class="playbook-run-time">${esc(ts)}</span>
            </div>`;
        }).join('')}
      </div>`;

    list.querySelectorAll('[data-run-id]').forEach(row => {
      row.addEventListener('click', () => _openPbRunModal(row.dataset.runId));
    });
  }

  async function _openPbRunModal(runId) {
    const modal = $('pbRunModal');
    if (!modal) return;
    modal.style.display = 'flex';
    $('pbRunModalTitle').textContent = 'Loading...';
    $('pbRunModalSteps').innerHTML = '<div class="empty-state"><div class="spinner"></div></div>';

    const r = await api(`/api/v1/playbooks/runs/${runId}`);
    if (!r.ok) { $('pbRunModalTitle').textContent = 'Failed to load'; return; }
    const run = r.data;
    $('pbRunModalTitle').textContent = run.playbook_name || 'Run Detail';
    const badge = _PB_STATUS_BADGE[run.status] || 'neutral';
    $('pbRunModalMeta').innerHTML = `
      <span class="badge ${badge}">${esc(run.status)}</span>
      <span>Triggered by: ${esc(run.triggered_by)}</span>
      <span>${run.started_at ? new Date(run.started_at).toLocaleString() : ''}</span>
      <span>${run.steps_done}/${run.steps_total} steps</span>`;

    const steps = Array.isArray(run.step_log) ? run.step_log : [];
    $('pbRunModalSteps').innerHTML = steps.length ? steps.map((s, i) => {
      const sb = _PB_STEP_BADGE[s.status] || 'neutral';
      return `
        <div style="background:var(--bg-deep);border-radius:6px;padding:8px 10px;">
          <div style="display:flex;gap:6px;align-items:center;margin-bottom:3px;">
            <span style="font-size:10px;color:var(--text-muted);">${i+1}.</span>
            <code style="font-size:11px;background:transparent;">${esc(s.type)}</code>
            <span class="badge ${sb}" style="font-size:9px;margin-left:auto;">${esc(s.status)}</span>
          </div>
          ${s.output ? `<p style="margin:0;font-size:11px;color:var(--text-muted);">${esc(s.output)}</p>` : ''}
          ${s.error  ? `<p style="margin:0;font-size:11px;color:var(--danger,#e55);">Error: ${esc(s.error)}</p>` : ''}
        </div>`;
    }).join('') : '<p style="font-size:12px;color:var(--text-muted);">No step log.</p>';
  }

  function _openPbModal(pbId, pb) {
    _pbEditId = pbId || null;
    $('pbModalTitle').textContent = pbId ? 'Edit Playbook' : 'New Playbook';
    $('pbName').value          = pb?.name        || '';
    $('pbDesc').value          = pb?.description || '';
    $('pbTriggerType').value   = pb?.trigger_type   || 'manual';
    $('pbTriggerFilter').value = pb?.trigger_filter || '';
    $('pbSteps').value = JSON.stringify(pb?.steps || [], null, 2);
    const t = pb?.trigger_type || 'manual';
    $('pbTriggerFilterRow').style.display = t === 'manual' ? 'none' : '';
    $('pbTriggerFilterLabel').textContent = t === 'incident' ? 'Min severity' : 'Event type';
    $('pbModal').style.display = 'flex';
  }

  // -- Dispatches (Scheduled Reports) -------------------------------------------

  let _dispReady = false;
  let _dispEditId = null;
  const _INTERVAL_LABELS = { 1:'Hourly', 6:'Every 6h', 12:'Every 12h', 24:'Daily', 168:'Weekly' };

  function initDispatchesView() {
    _loadDispatches();
    if (_dispReady) return;
    _dispReady = true;

    const addBtn    = $('dispAddBtn');
    const refreshBtn = $('dispRefreshBtn');
    const cancelBtn = $('dispCancelBtn');
    const closeRun  = $('dispRunModalCloseBtn');
    const delivery  = $('dispDelivery');
    const form      = $('dispForm');

    addBtn?.addEventListener('click', () => _openDispModal());
    refreshBtn?.addEventListener('click', () => _loadDispatches());
    cancelBtn?.addEventListener('click', () => { $('dispModal').style.display = 'none'; _dispEditId = null; });
    closeRun?.addEventListener('click', () => { $('dispRunModal').style.display = 'none'; });
    delivery?.addEventListener('change', () => {
      $('dispWebhookRow').style.display = delivery.value === 'webhook' ? '' : 'none';
    });

    form?.addEventListener('submit', async e => {
      e.preventDefault();
      const sections = Array.from(form.querySelectorAll('[name="section"]:checked')).map(c => c.value).join(',');
      if (!sections) { alert('Select at least one section.'); return; }
      const body = {
        name:           $('dispName')?.value?.trim(),
        interval_hours: parseInt($('dispInterval')?.value || '24'),
        sections,
        delivery:       $('dispDelivery')?.value || 'store',
        webhook_url:    $('dispWebhookUrl')?.value?.trim() || '',
        enabled:        true,
      };
      const url    = _dispEditId ? `/api/v1/scheduled-reports/${_dispEditId}` : '/api/v1/scheduled-reports';
      const method = _dispEditId ? 'PATCH' : 'POST';
      const r = await api(url, { method, body: JSON.stringify(body) });
      if (r.ok) {
        $('dispModal').style.display = 'none';
        _dispEditId = null;
        _loadDispatches();
      }
    });
  }

  async function _loadDispatches() {
    await Promise.all([_loadDispConfigs(), _loadDispRuns()]);
    _updateDispStats();
  }

  async function _updateDispStats() {
    const strip = $('dispStatsStrip');
    if (!strip) return;
    const [cfgR, runR] = await Promise.all([
      api('/api/v1/scheduled-reports'),
      api('/api/v1/scheduled-reports/runs?limit=50'),
    ]);
    const configs = cfgR.ok ? (cfgR.data.configs || []) : [];
    const runs    = runR.ok ? (runR.data.runs    || []) : [];
    const enabled = configs.filter(c => c.enabled).length;
    const ok      = runs.filter(r => r.status === 'ok').length;
    const err     = runs.filter(r => r.status === 'error').length;
    strip.innerHTML = `
      <div class="report-card" style="padding:8px 12px;min-width:90px;"><span>Schedules</span><strong>${configs.length}</strong></div>
      <div class="report-card" style="padding:8px 12px;min-width:90px;"><span>Active</span><strong>${enabled}</strong></div>
      <div class="report-card" style="padding:8px 12px;min-width:90px;"><span>Runs OK</span><strong style="color:var(--ok,#5a5);">${ok}</strong></div>
      ${err ? `<div class="report-card" style="padding:8px 12px;min-width:90px;"><span>Errors</span><strong style="color:var(--danger,#e55);">${err}</strong></div>` : ''}`;
  }

  async function _loadDispConfigs() {
    const list = $('dispConfigList');
    if (!list) return;
    const r = await api('/api/v1/scheduled-reports');
    if (!r.ok) { list.innerHTML = '<div class="empty-state"><p>Failed to load.</p></div>'; return; }
    const configs = r.data.configs || [];
    if (!configs.length) {
      list.innerHTML = '<div class="empty-state"><p>No report schedules configured yet.</p></div>';
      return;
    }
    list.innerHTML = `
      <table style="width:100%;font-size:12px;border-collapse:collapse;">
        <thead><tr style="border-bottom:1px solid var(--border);">
          <th style="text-align:left;padding:8px 12px;font-weight:600;color:var(--text-muted);">Name</th>
          <th style="text-align:left;padding:8px 12px;font-weight:600;color:var(--text-muted);">Interval</th>
          <th style="text-align:left;padding:8px 12px;font-weight:600;color:var(--text-muted);">Sections</th>
          <th style="text-align:left;padding:8px 12px;font-weight:600;color:var(--text-muted);">Last Run</th>
          <th style="text-align:left;padding:8px 12px;font-weight:600;color:var(--text-muted);">Next Run</th>
          <th style="padding:8px 12px;"></th>
        </tr></thead>
        <tbody>
          ${configs.map(c => {
            const intLabel = _INTERVAL_LABELS[c.interval_hours] || `${c.interval_hours}h`;
            const lastRun  = c.last_run ? new Date(c.last_run).toLocaleString() : ' - ';
            const nextRun  = c.next_run ? new Date(c.next_run).toLocaleString() : ' - ';
            const sects    = (c.sections || '').split(',').length;
            return `<tr style="border-bottom:1px solid var(--border);" data-cfg-id="${esc(c.id)}">
              <td style="padding:9px 12px;font-weight:600;">${esc(c.name)} ${c.enabled ? '' : '<span class="badge neutral" style="font-size:9px;">paused</span>'}</td>
              <td style="padding:9px 12px;color:var(--text-muted);">${esc(intLabel)}</td>
              <td style="padding:9px 12px;color:var(--text-muted);">${sects} section${sects !== 1 ? 's' : ''}</td>
              <td style="padding:9px 12px;color:var(--text-muted);">${esc(lastRun)}</td>
              <td style="padding:9px 12px;color:var(--text-muted);">${esc(nextRun)}</td>
              <td style="padding:9px 12px;white-space:nowrap;">
                <button class="btn sm ghost" data-run-now="${esc(c.id)}" style="font-size:10px;">Run Now</button>
                <button class="btn sm ghost" data-edit-cfg="${esc(c.id)}" style="font-size:10px;">Edit</button>
                <button class="btn sm ghost" data-del-cfg="${esc(c.id)}" style="font-size:10px;color:var(--danger,#e55);">Del</button>
              </td>
            </tr>`;
          }).join('')}
        </tbody>
      </table>`;

    list.querySelectorAll('[data-run-now]').forEach(btn => {
      btn.addEventListener('click', async () => {
        btn.disabled = true; btn.textContent = '...';
        const r = await api(`/api/v1/scheduled-reports/${btn.dataset.runNow}/run`, { method: 'POST' });
        btn.textContent = r.ok ? 'Dispatched' : 'Error';
        setTimeout(() => _loadDispatches(), 1500);
      });
    });
    list.querySelectorAll('[data-edit-cfg]').forEach(btn => {
      btn.addEventListener('click', () => _openDispModal(btn.dataset.editCfg, configs.find(c => c.id === btn.dataset.editCfg)));
    });
    list.querySelectorAll('[data-del-cfg]').forEach(btn => {
      btn.addEventListener('click', async () => {
        if (!confirm('Delete this report schedule and all its run history?')) return;
        await api(`/api/v1/scheduled-reports/${btn.dataset.delCfg}`, { method: 'DELETE' });
        _loadDispatches();
      });
    });
  }

  async function _loadDispRuns(configId) {
    const list = $('dispRunList');
    if (!list) return;
    const url = configId
      ? `/api/v1/scheduled-reports/runs?limit=20&config_id=${encodeURIComponent(configId)}`
      : '/api/v1/scheduled-reports/runs?limit=20';
    const r = await api(url);
    if (!r.ok) { list.innerHTML = '<div class="empty-state"><p>Failed to load runs.</p></div>'; return; }
    const runs = r.data.runs || [];
    if (!runs.length) {
      list.innerHTML = '<div class="empty-state"><p>No runs yet.</p></div>';
      return;
    }
    list.innerHTML = `
      <div class="activity-list">
        ${runs.map(run => {
          const ts = run.generated_at ? new Date(run.generated_at).toLocaleString() : '';
          const ok = run.status === 'ok';
          return `
            <div class="activity-item" style="padding:9px 12px;gap:10px;cursor:pointer;" data-run-id="${esc(run.id)}">
              <span class="badge ${ok ? 'ok' : 'bad'}" style="font-size:10px;flex-shrink:0;">${esc(run.status)}</span>
              <div style="flex:1;min-width:0;">
                <p style="margin:0;font-size:12px;font-weight:600;">${esc(run.config_name)}</p>
                ${run.error_msg ? `<p style="margin:2px 0 0;font-size:11px;color:var(--danger,#e55);">${esc(run.error_msg)}</p>` : ''}
              </div>
              <span style="font-size:10px;color:var(--text-muted);white-space:nowrap;">${esc(ts)}</span>
              ${run.delivered ? '<span style="font-size:10px;color:var(--ok,#5a5);">OK delivered</span>' : ''}
            </div>`;
        }).join('')}
      </div>`;

    list.querySelectorAll('[data-run-id]').forEach(row => {
      row.addEventListener('click', () => _openRunModal(row.dataset.runId));
    });
  }

  async function _openRunModal(runId) {
    const modal = $('dispRunModal');
    if (!modal) return;
    modal.style.display = 'flex';
    $('dispRunModalTitle').textContent = 'Loading report...';
    $('dispRunModalContent').textContent = '';

    const r = await api(`/api/v1/scheduled-reports/runs/${runId}`);
    if (!r.ok) { $('dispRunModalTitle').textContent = 'Failed to load run'; return; }
    const run = r.data;
    $('dispRunModalTitle').textContent = run.config_name || 'Report Run';
    $('dispRunModalMeta').innerHTML = `
      <span class="badge ${run.status === 'ok' ? 'ok' : 'bad'}">${esc(run.status)}</span>
      <span>${run.generated_at ? new Date(run.generated_at).toLocaleString() : ''}</span>
      ${run.delivered ? '<span style="color:var(--ok,#5a5);">OK Delivered</span>' : ''}`;
    $('dispRunModalContent').textContent = run.content
      ? JSON.stringify(run.content, null, 2)
      : (run.error_msg || 'No content');
  }

  function _openDispModal(configId, cfg) {
    _dispEditId = configId || null;
    const modal = $('dispModal');
    if (!modal) return;
    $('dispModalTitle').textContent = configId ? 'Edit Schedule' : 'New Report Schedule';
    $('dispName').value        = cfg?.name || '';
    $('dispInterval').value    = cfg?.interval_hours || 24;
    $('dispDelivery').value    = cfg?.delivery || 'store';
    $('dispWebhookUrl').value  = cfg?.webhook_url || '';
    $('dispWebhookRow').style.display = (cfg?.delivery === 'webhook') ? '' : 'none';
    // Restore section checkboxes
    const active = new Set((cfg?.sections || '').split(',').map(s => s.trim()));
    modal.querySelectorAll('[name="section"]').forEach(cb => {
      cb.checked = !configId || active.has(cb.value);
    });
    modal.style.display = 'flex';
  }

  // -- Incidents -----------------------------------------------------------------

  let _activeIncidentId = null;
  const _INC_SEV_BADGE = { critical: 'bad', high: 'bad', medium: 'warn', low: 'neutral' };
  const _INC_STATUS_BADGE = { open: 'bad', acknowledged: 'warn', resolved: 'ok' };

  async function _loadIncidents() {
    await Promise.all([_loadIncidentStats(), _loadIncidentList()]);
    _wireIncidentControls();
  }

  async function _loadIncidentStats() {
    const strip = $('incidentStatsStrip');
    if (!strip) return;
    const r = await api('/api/v1/incidents/stats');
    if (!r.ok) { strip.innerHTML = ''; return; }
    const d = r.data;
    const bs = d.by_status || {};
    strip.innerHTML = `
      <div class="report-card" style="padding:8px 12px;min-width:90px;"><span>Total</span><strong>${d.total}</strong></div>
      <div class="report-card" style="padding:8px 12px;min-width:90px;"><span>Open</span><strong style="color:${bs.open ? 'var(--danger,#e55)' : 'inherit'};">${bs.open || 0}</strong></div>
      <div class="report-card" style="padding:8px 12px;min-width:90px;"><span>Acknowledged</span><strong style="color:${bs.acknowledged ? 'var(--warn,#f90)' : 'inherit'};">${bs.acknowledged || 0}</strong></div>
      <div class="report-card" style="padding:8px 12px;min-width:90px;"><span>Resolved</span><strong style="color:var(--ok,#5a5);">${bs.resolved || 0}</strong></div>
      <div class="report-card" style="padding:8px 12px;min-width:90px;"><span>Opened 24h</span><strong>${d.opened_24h}</strong></div>`;
  }

  async function _loadIncidentList() {
    const list = $('incidentList');
    if (!list) return;
    list.innerHTML = '<div class="empty-state"><div class="spinner"></div></div>';
    const params = new URLSearchParams({ limit: 50 });
    const status = $('incStatusFilter')?.value;
    const sev    = $('incSevFilter')?.value;
    if (status) params.set('status',   status);
    if (sev)    params.set('severity', sev);
    const r = await api(`/api/v1/incidents?${params}`);
    if (!r.ok) {
      list.innerHTML = '<div class="empty-state"><p>Failed to load incidents.</p></div>';
      return;
    }
    const { incidents, total } = r.data;
    if (!incidents.length) {
      list.innerHTML = '<div class="empty-state"><p>No incidents found.</p></div>';
      return;
    }
    list.innerHTML = `
      <div class="activity-list">
        ${incidents.map(inc => {
          const sevBadge    = _INC_SEV_BADGE[inc.severity]    || 'neutral';
          const statusBadge = _INC_STATUS_BADGE[inc.status]   || 'neutral';
          const ts = inc.created_at ? new Date(inc.created_at).toLocaleString() : '';
          return `
            <div class="activity-item" data-inc-id="${esc(inc.id)}" style="padding:10px 12px;cursor:pointer;gap:10px;">
              <div style="flex:1;min-width:0;">
                <div style="display:flex;gap:6px;align-items:center;margin-bottom:3px;flex-wrap:wrap;">
                  <span class="badge ${sevBadge}">${esc(inc.severity)}</span>
                  <span class="badge ${statusBadge}" style="font-size:10px;">${esc(inc.status)}</span>
                  ${inc.metric ? `<code style="font-size:10px;color:var(--text-muted);background:var(--bg-deep);padding:1px 5px;border-radius:3px;">${esc(inc.metric)}</code>` : ''}
                </div>
                <p style="margin:0;font-size:13px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${esc(inc.title)}</p>
                ${inc.assigned_to ? `<span style="font-size:11px;color:var(--text-muted);">-> ${esc(inc.assigned_to)}</span>` : ''}
              </div>
              <div style="flex-shrink:0;text-align:right;">
                <span style="font-size:10px;color:var(--text-muted);white-space:nowrap;">${esc(ts)}</span>
                <div style="display:flex;gap:4px;margin-top:4px;justify-content:flex-end;">
                  ${inc.status === 'open' ? `<button class="btn sm ghost" data-ack="${esc(inc.id)}" style="font-size:10px;padding:2px 7px;">Ack</button>` : ''}
                  ${inc.status !== 'resolved' ? `<button class="btn sm ghost" data-resolve="${esc(inc.id)}" style="font-size:10px;padding:2px 7px;">Resolve</button>` : ''}
                </div>
              </div>
            </div>`;
        }).join('')}
      </div>
      ${total > 50 ? `<p style="font-size:11px;color:var(--text-muted);text-align:center;padding:8px;">${total} total  -  showing 50</p>` : ''}`;

    // Row click -> detail modal
    list.querySelectorAll('[data-inc-id]').forEach(row => {
      row.addEventListener('click', e => {
        if (e.target.closest('[data-ack],[data-resolve]')) return;
        _openIncidentModal(row.dataset.incId);
      });
    });
    // Inline ack/resolve
    list.querySelectorAll('[data-ack]').forEach(btn => {
      btn.addEventListener('click', async e => {
        e.stopPropagation();
        btn.disabled = true; btn.textContent = '...';
        await api(`/api/v1/incidents/${btn.dataset.ack}/acknowledge`, { method: 'POST' });
        _loadIncidents();
      });
    });
    list.querySelectorAll('[data-resolve]').forEach(btn => {
      btn.addEventListener('click', async e => {
        e.stopPropagation();
        btn.disabled = true; btn.textContent = '...';
        await api(`/api/v1/incidents/${btn.dataset.resolve}/resolve`, { method: 'POST' });
        _loadIncidents();
      });
    });
  }

  async function _openIncidentModal(incidentId) {
    _activeIncidentId = incidentId;
    const modal = $('incidentModal');
    if (!modal) return;
    modal.style.display = 'flex';
    $('incModalTitle').textContent = 'Loading...';
    $('incModalTimeline').innerHTML = '<div class="empty-state"><div class="spinner"></div></div>';

    const r = await api(`/api/v1/incidents/${incidentId}`);
    if (!r.ok) {
      $('incModalTitle').textContent = 'Failed to load incident';
      return;
    }
    const { incident: inc, timeline } = r.data;
    $('incModalTitle').textContent = inc.title;
    const sevBadge    = _INC_SEV_BADGE[inc.severity]  || 'neutral';
    const statusBadge = _INC_STATUS_BADGE[inc.status] || 'neutral';
    $('incModalMeta').innerHTML = `
      <span class="badge ${sevBadge}">${esc(inc.severity)}</span>
      <span class="badge ${statusBadge}">${esc(inc.status)}</span>
      ${inc.metric ? `<code style="font-size:11px;background:var(--bg-deep);padding:2px 6px;border-radius:3px;">${esc(inc.metric)}</code>` : ''}
      <span style="font-size:11px;color:var(--text-muted);">Created ${inc.created_at ? new Date(inc.created_at).toLocaleString() : ''}</span>`;
    $('incModalDesc').textContent = inc.description || ' - ';

    const actions = [];
    if (inc.status === 'open') actions.push(`<button class="btn sm" id="incAckBtn">Acknowledge</button>`);
    if (inc.status !== 'resolved') actions.push(`<button class="btn sm primary" id="incResolveBtn">Resolve</button>`);
    $('incModalActions').innerHTML = actions.join('');

    $('incAckBtn')?.addEventListener('click', async () => {
      await api(`/api/v1/incidents/${incidentId}/acknowledge`, { method: 'POST' });
      modal.style.display = 'none';
      _loadIncidents();
    });
    $('incResolveBtn')?.addEventListener('click', async () => {
      await api(`/api/v1/incidents/${incidentId}/resolve`, { method: 'POST' });
      modal.style.display = 'none';
      _loadIncidents();
    });

    const _TL_ACTION_ICON = {
      created: 'new', acknowledged: 'view', resolved: 'OK',
      repeated_breach: '!', commented: 'comment', assigned: 'user',
    };
    $('incModalTimeline').innerHTML = timeline.length ? `
      <div style="display:flex;flex-direction:column;gap:6px;">
        ${timeline.map(t => `
          <div style="display:flex;gap:8px;align-items:flex-start;">
            <span style="font-size:14px;flex-shrink:0;">${_TL_ACTION_ICON[t.action] || '*'}</span>
            <div style="flex:1;min-width:0;">
              <div style="display:flex;gap:6px;align-items:baseline;flex-wrap:wrap;">
                <strong style="font-size:12px;">${esc(t.action)}</strong>
                <span style="font-size:10px;color:var(--text-muted);">${t.actor}</span>
                <span style="font-size:10px;color:var(--text-muted);margin-left:auto;">${t.ts ? new Date(t.ts).toLocaleTimeString() : ''}</span>
              </div>
              ${t.note ? `<p style="font-size:12px;color:var(--text-muted);margin:2px 0 0;">${esc(t.note)}</p>` : ''}
            </div>
          </div>`).join('')}
      </div>` : '<p style="font-size:12px;color:var(--text-muted);">No timeline entries.</p>';
  }

  function _wireIncidentControls() {
    const closeBtn = $('incModalCloseBtn');
    if (closeBtn && !closeBtn._incWired) {
      closeBtn._incWired = true;
      closeBtn.addEventListener('click', () => {
        $('incidentModal').style.display = 'none';
        _activeIncidentId = null;
      });
    }
    const commentBtn = $('incCommentBtn');
    if (commentBtn && !commentBtn._incWired) {
      commentBtn._incWired = true;
      commentBtn.addEventListener('click', async () => {
        const input = $('incCommentInput');
        const note  = input?.value?.trim();
        if (!note || !_activeIncidentId) return;
        commentBtn.disabled = true;
        const r = await api(`/api/v1/incidents/${_activeIncidentId}/comment`, {
          method: 'POST', body: JSON.stringify({ note }),
        });
        commentBtn.disabled = false;
        if (r.ok) {
          input.value = '';
          _openIncidentModal(_activeIncidentId);
        }
      });
    }
    const refreshBtn = $('incRefreshBtn');
    if (refreshBtn && !refreshBtn._incWired) {
      refreshBtn._incWired = true;
      refreshBtn.addEventListener('click', () => _loadIncidents());
    }
    [$('incStatusFilter'), $('incSevFilter')].forEach(el => {
      if (el && !el._incWired) {
        el._incWired = true;
        el.addEventListener('change', () => _loadIncidentList());
      }
    });
    const createBtn = $('incCreateBtn');
    if (createBtn && !createBtn._incWired) {
      createBtn._incWired = true;
      createBtn.addEventListener('click', () => {
        $('incCreateModal').style.display = 'flex';
      });
    }
    const cancelBtn = $('incCreateCancelBtn');
    if (cancelBtn && !cancelBtn._incWired) {
      cancelBtn._incWired = true;
      cancelBtn.addEventListener('click', () => {
        $('incCreateModal').style.display = 'none';
      });
    }
    const createForm = $('incCreateForm');
    if (createForm && !createForm._incWired) {
      createForm._incWired = true;
      createForm.addEventListener('submit', async e => {
        e.preventDefault();
        const title = $('incCreateTitle')?.value?.trim();
        const desc  = $('incCreateDesc')?.value?.trim();
        const sev   = $('incCreateSev')?.value;
        if (!title) return;
        const r = await api('/api/v1/incidents', {
          method: 'POST',
          body: JSON.stringify({ title, description: desc, severity: sev }),
        });
        if (r.ok) {
          $('incCreateModal').style.display = 'none';
          createForm.reset();
          _loadIncidents();
        }
      });
    }
  }

  // -- Audit Log ----------------------------------------------------------------

  const _auditState = { offset: 0, limit: 50, total: 0 };
  const _SEV_BADGE = { critical: 'bad', high: 'bad', medium: 'warn', low: 'neutral', info: 'neutral' };

  async function _loadAuditLog() {
    await Promise.all([_loadAuditStats(), _loadAuditEntries(0)]);
    _wireAuditControls();
  }

  async function _loadAuditStats() {
    const strip = $('auditStatsStrip');
    if (!strip) return;
    const r = await api('/api/v1/audit-log/stats');
    if (!r.ok) { strip.innerHTML = ''; return; }
    const d = r.data;
    const sev = d.by_severity || {};
    strip.innerHTML = `
      <div class="report-card" style="padding:8px 12px;min-width:90px;"><span>Total</span><strong>${d.total}</strong></div>
      <div class="report-card" style="padding:8px 12px;min-width:90px;"><span>Last 24h</span><strong>${d.last_24h}</strong></div>
      ${(sev.critical || sev.high) ? `<div class="report-card" style="padding:8px 12px;min-width:90px;"><span>Critical/High</span><strong style="color:var(--danger,#e55);">${(sev.critical||0)+(sev.high||0)}</strong></div>` : ''}
      ${sev.medium ? `<div class="report-card" style="padding:8px 12px;min-width:90px;"><span>Medium</span><strong style="color:var(--warn,#f90);">${sev.medium}</strong></div>` : ''}`;

    // Populate event-type filter
    const sel = $('auditTypeFilter');
    if (sel && d.top_event_types) {
      const existing = new Set(Array.from(sel.options).map(o => o.value));
      d.top_event_types.forEach(({ event_type }) => {
        if (!existing.has(event_type)) {
          const opt = document.createElement('option');
          opt.value = event_type; opt.textContent = event_type;
          sel.appendChild(opt);
        }
      });
    }
  }

  async function _loadAuditEntries(offset) {
    const list = $('auditEntriesList');
    if (!list) return;
    _auditState.offset = offset;
    list.innerHTML = '<div class="empty-state"><div class="spinner"></div></div>';

    const params = new URLSearchParams({
      limit:  _auditState.limit,
      offset: offset,
    });
    const sev  = $('auditSevFilter')?.value;
    const type = $('auditTypeFilter')?.value;
    const q    = $('auditSearchInput')?.value?.trim();
    if (sev)  params.set('severity',   sev);
    if (type) params.set('event_type', type);
    if (q)    params.set('q', q);

    const r = await api(`/api/v1/audit-log?${params}`);
    if (!r.ok) {
      list.innerHTML = `<div class="empty-state"><p>Failed to load audit log.</p></div>`;
      return;
    }
    const { entries, total } = r.data;
    _auditState.total = total;

    if (!entries.length) {
      list.innerHTML = '<div class="empty-state"><p>No audit entries match the current filters.</p></div>';
      _renderAuditPagination();
      return;
    }

    list.innerHTML = `
      <div class="activity-list">
        ${entries.map(e => {
          const badge = _SEV_BADGE[e.severity] || 'neutral';
          const ts    = e.ts ? new Date(e.ts).toLocaleString() : '';
          return `
            <div class="activity-item" style="padding:9px 12px;gap:10px;">
              <div style="flex:1;min-width:0;">
                <div style="display:flex;gap:6px;align-items:center;margin-bottom:2px;flex-wrap:wrap;">
                  <span class="badge ${badge}" style="font-size:10px;">${esc(e.severity)}</span>
                  <code style="font-size:10px;color:var(--text-muted);background:var(--bg-deep);padding:1px 5px;border-radius:3px;">${esc(e.event_type)}</code>
                  <span style="font-size:10px;color:var(--text-muted);">${esc(e.actor)}</span>
                </div>
                <p style="margin:0;font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${esc(e.summary)}</p>
              </div>
              <span style="font-size:10px;color:var(--text-muted);white-space:nowrap;flex-shrink:0;">${esc(ts)}</span>
            </div>`;
        }).join('')}
      </div>`;
    _renderAuditPagination();
  }

  function _renderAuditPagination() {
    const pg = $('auditPagination');
    if (!pg) return;
    const { offset, limit, total } = _auditState;
    const page    = Math.floor(offset / limit) + 1;
    const maxPage = Math.max(1, Math.ceil(total / limit));
    pg.innerHTML = `
      <button class="btn sm ghost" ${page <= 1 ? 'disabled' : ''} id="auditPrevBtn"><- Prev</button>
      <span style="color:var(--text-muted);">Page ${page} / ${maxPage} Â· ${total} entries</span>
      <button class="btn sm ghost" ${page >= maxPage ? 'disabled' : ''} id="auditNextBtn">Next -></button>`;
    pg.querySelector('#auditPrevBtn')?.addEventListener('click', () => _loadAuditEntries(offset - limit));
    pg.querySelector('#auditNextBtn')?.addEventListener('click', () => _loadAuditEntries(offset + limit));
  }

  function _wireAuditControls() {
    const refresh = $('auditRefreshBtn');
    const exportB = $('auditExportBtn');
    const search  = $('auditSearchInput');
    const sevSel  = $('auditSevFilter');
    const typeSel = $('auditTypeFilter');

    if (refresh && !refresh._auditWired) {
      refresh._auditWired = true;
      refresh.addEventListener('click', () => _loadAuditLog());
    }
    if (exportB && !exportB._auditWired) {
      exportB._auditWired = true;
      exportB.addEventListener('click', () => {
        const p = new URLSearchParams();
        const sev  = $('auditSevFilter')?.value;
        const type = $('auditTypeFilter')?.value;
        if (sev)  p.set('severity', sev);
        if (type) p.set('event_type', type);
        const url = `/api/v1/audit-log/export?${p}`;
        const a = document.createElement('a');
        a.href = url; a.download = ''; a.click();
      });
    }
    [search, sevSel, typeSel].forEach(el => {
      if (el && !el._auditWired) {
        el._auditWired = true;
        el.addEventListener('change', () => _loadAuditEntries(0));
        if (el === search) el.addEventListener('keydown', e => { if (e.key === 'Enter') _loadAuditEntries(0); });
      }
    });
  }

  // -- Notification Center ------------------------------------------------------

  let _notifOpen = false;
  let _notifPollTimer = null;

  function _initNotificationCenter() {
    const bell    = $('notifBellBtn');
    const panel   = $('notifPanel');
    const overlay = $('notifOverlay');
    if (!bell || !panel) return;

    bell.addEventListener('click', () => _notifOpen ? _closeNotifPanel() : _openNotifPanel());
    $('notifCloseBtn')?.addEventListener('click', _closeNotifPanel);
    overlay.addEventListener('click', _closeNotifPanel);
    $('notifMarkAllBtn')?.addEventListener('click', async () => {
      await api('/api/v1/notifications/read-all', { method: 'POST' });
      _refreshNotifList();
      _refreshNotifBadge();
    });
    $('notifClearBtn')?.addEventListener('click', async () => {
      if (!confirm('Clear all notifications?')) return;
      await api('/api/v1/notifications', { method: 'DELETE' });
      _refreshNotifList();
      _refreshNotifBadge();
    });

    // Poll badge count every 30s
    _notifPollTimer = setInterval(_refreshNotifBadge, 30_000);
    _refreshNotifBadge();
  }

  async function _refreshNotifBadge() {
    const r = await api('/api/v1/notifications/count');
    const badge = $('notifBadge');
    if (!badge) return;
    const n = r.unread ?? 0;
    badge.textContent = n > 99 ? '99+' : String(n);
    badge.style.display = n > 0 ? 'block' : 'none';
    $('notifBellBtn')?.setAttribute('aria-label', n > 0 ? `${n} unread notifications` : 'Notifications');
  }

  function _openNotifPanel() {
    _notifOpen = true;
    const panel   = $('notifPanel');
    const overlay = $('notifOverlay');
    panel.hidden   = false;
    overlay.hidden = false;
    panel.style.right = '0';
    $('notifBellBtn')?.setAttribute('aria-expanded', 'true');
    _refreshNotifList();
  }

  function _closeNotifPanel() {
    _notifOpen = false;
    const panel   = $('notifPanel');
    const overlay = $('notifOverlay');
    panel.style.right = '-360px';
    setTimeout(() => {
      panel.hidden   = true;
      overlay.hidden = true;
    }, 260);
    $('notifBellBtn')?.setAttribute('aria-expanded', 'false');
    _refreshNotifBadge();
  }

  async function _refreshNotifList() {
    const listEl = $('notifList');
    if (!listEl) return;

    const r = await api('/api/v1/notifications?limit=60');
    const notifs  = r.notifications || [];
    const unread  = r.unread ?? 0;

    $('notifSubtitle').textContent = unread > 0 ? `${unread} unread` : 'All caught up';

    const SEV_COLOR = {
      low:      'var(--text-muted)',
      medium:   'var(--accent)',
      high:     'var(--warn, #f59e0b)',
      critical: 'var(--danger)',
    };
    const VIEW_LABEL = {
      command:   'Command Center',
      workflows: 'Workflows',
    };

    if (!notifs.length) {
      listEl.innerHTML = `<div style="padding:24px;text-align:center;color:var(--text-muted);font-size:13px;">No notifications yet</div>`;
      return;
    }

    listEl.innerHTML = notifs.map(n => `
      <div data-notif-id="${esc(n.id)}" style="display:flex;gap:10px;padding:12px 16px;border-bottom:1px solid var(--border);${!n.is_read ? 'background:var(--accent-subtle);' : ''}cursor:pointer;transition:background .15s;">
        <div style="flex-shrink:0;width:6px;height:6px;border-radius:50%;margin-top:6px;background:${SEV_COLOR[n.severity] || 'var(--text-muted)'};"></div>
        <div style="flex:1;min-width:0;">
          <div style="font-size:13px;font-weight:${n.is_read ? '400' : '600'};line-height:1.3;">${esc(n.title)}</div>
          ${n.body ? `<div style="font-size:11px;color:var(--text-muted);margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${esc(n.body)}">${esc(n.body)}</div>` : ''}
          <div style="font-size:10px;color:var(--text-muted);margin-top:4px;display:flex;gap:8px;">
            <span>${esc(n.created_at?.slice(0,19)?.replace('T',' '))} UTC</span>
            ${n.view_hint ? `<span style="color:var(--accent);cursor:pointer;" data-notif-nav="${esc(n.view_hint)}">${esc(VIEW_LABEL[n.view_hint] || n.view_hint)} -></span>` : ''}
          </div>
        </div>
        <button type="button" data-notif-del="${esc(n.id)}" aria-label="Dismiss"
                style="background:none;border:none;cursor:pointer;color:var(--text-muted);font-size:14px;flex-shrink:0;padding:0 2px;opacity:.5;line-height:1;">x</button>
      </div>`).join('');

    // Click on row -> mark read
    listEl.querySelectorAll('[data-notif-id]').forEach(row => {
      row.addEventListener('click', async (e) => {
        if (e.target.closest('[data-notif-del]') || e.target.closest('[data-notif-nav]')) return;
        const id = row.dataset.notifId;
        await api(`/api/v1/notifications/${id}/read`, { method: 'POST' });
        row.style.background = '';
        row.querySelector('div > div:first-child').style.fontWeight = '400';
        _refreshNotifBadge();
      });
    });

    // Navigate link
    listEl.querySelectorAll('[data-notif-nav]').forEach(link => {
      link.addEventListener('click', (e) => {
        e.stopPropagation();
        _closeNotifPanel();
        showView(link.dataset.notifNav);
      });
    });

    // Delete button
    listEl.querySelectorAll('[data-notif-del]').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        e.stopPropagation();
        const row = btn.closest('[data-notif-id]');
        await api(`/api/v1/notifications/${btn.dataset.notifDel}`, { method: 'DELETE' });
        row?.remove();
        _refreshNotifBadge();
      });
    });
  }

  // -- Init --------------------------------------------------------------------
  async function init() {
    await loadRuntimeProfile();
    renderProviders();
    ensureAccountStatusPanel();
    applyNavigationRole(localStorage.getItem('ai36NavRole') || 'basic-client');
    updateOAuthSubmitState();
    bind();
    renderMetrics();
    renderPerformance();
    renderActivity();
    renderRuleDiagram();
    renderSettings('general');
    loadDashboard();
    loadOnnxStatus();
    loadCertification();
    loadAccounts();
    loadTemplates();
    if (!state.runtime?.frontend?.deferred_rendering) {
      loadReports(false);
      refreshConnectorFeatureNavigation();
    } else {
      setTimeout(() => loadReports(false), 1200);
      setTimeout(() => refreshConnectorFeatureNavigation(), 1600);
    }
    _initNotificationCenter();
  }

  // -- SLA Tracker ----------------------------------------------------------

  let _slaEditId = null;

  function initSlaView() {
    _loadSlaPolicies();
    _loadSlaBreaches();
    _loadSlaStats();

    _bind('slaAddBtn', 'click', () => _openSlaModal(null));
    _bind('slaPolicyModalClose',  'click', _closeSlaModal);
    _bind('slaPolicyModalCancel', 'click', _closeSlaModal);
    _bind('slaBreachTypeFilter',  'change', _loadSlaBreaches);
    _bind('slaBreachSevFilter',   'change', _loadSlaBreaches);

    _q('#slaPolicyModal').addEventListener('click', e => {
      if (e.target === _q('#slaPolicyModal')) _closeSlaModal();
    });

    _q('#slaPolicyForm').addEventListener('submit', async e => {
      e.preventDefault();
      const name     = _q('#slaPolName').value.trim();
      const severity = _q('#slaPolSeverity').value;
      const resp     = parseInt(_q('#slaPolResponse').value, 10);
      const res      = parseInt(_q('#slaPolResolve').value, 10);
      const enabled  = _q('#slaPolEnabled').checked;
      if (!name) return;
      const body = { name, severity, response_minutes: resp, resolve_minutes: res, enabled };
      try {
        if (_slaEditId) {
          await _api(`/sla/policies/${_slaEditId}`, 'PATCH', body);
        } else {
          await _api('/sla/policies', 'POST', body);
        }
        _closeSlaModal();
        _loadSlaPolicies();
        _loadSlaStats();
      } catch (err) {
        alert('Save failed: ' + (err.message || err));
      }
    });
  }

  async function _loadSlaPolicies() {
    const tbody = _q('#slaPoliciesTbody');
    try {
      const data = await _api('/sla/policies');
      const list = data.policies || [];
      _q('#slaPoliciesCount').textContent = `${list.length} polic${list.length === 1 ? 'y' : 'ies'}`;
      if (!list.length) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-muted);padding:24px;">No SLA policies defined yet.</td></tr>';
        return;
      }
      tbody.innerHTML = list.map(p => {
        const sevLabel = p.severity || '<span style="color:var(--text-muted)">All</span>';
        const statusBadge = p.enabled
          ? '<span class="badge success">Active</span>'
          : '<span class="badge muted">Disabled</span>';
        return `<tr>
          <td><strong>${_esc(p.name)}</strong></td>
          <td>${sevLabel}</td>
          <td>${p.response_minutes} min</td>
          <td>${p.resolve_minutes} min</td>
          <td>${statusBadge}</td>
          <td style="text-align:right;">
            <button class="btn xs" onclick="_openSlaModal('${p.id}')">Edit</button>
            <button class="btn xs danger" onclick="_deleteSlaPolicy('${p.id}', '${_esc(p.name)}')">Delete</button>
          </td>
        </tr>`;
      }).join('');
    } catch (_) {
      tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-muted);padding:24px;">Failed to load policies.</td></tr>';
    }
  }

  async function _loadSlaBreaches() {
    const tbody   = _q('#slaBreachesTbody');
    const type    = (_q('#slaBreachTypeFilter') || {}).value || '';
    const sev     = (_q('#slaBreachSevFilter')  || {}).value || '';
    let url = '/sla/breaches?limit=50';
    if (type) url += '&breach_type=' + encodeURIComponent(type);
    if (sev)  url += '&severity='    + encodeURIComponent(sev);
    try {
      const data = await _api(url);
      const list = data.breaches || [];
      if (!list.length) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--text-muted);padding:24px;">No breaches recorded.</td></tr>';
        return;
      }
      const typeLabel = t => t === 'response'
        ? '<span class="badge warning">Response</span>'
        : '<span class="badge danger">Resolution</span>';
      tbody.innerHTML = list.map(b => `<tr>
        <td title="${_esc(b.incident_id)}">${_esc(b.incident_title)}</td>
        <td><span class="badge ${_sevClass(b.incident_severity)}">${b.incident_severity || ' - '}</span></td>
        <td>${typeLabel(b.breach_type)}</td>
        <td>${_esc(b.policy_name)}</td>
        <td style="font-size:11px;color:var(--text-muted);">${_relativeTime(b.breached_at)}</td>
      </tr>`).join('');
    } catch (_) {
      tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--text-muted);padding:24px;">Failed to load breaches.</td></tr>';
    }
  }

  async function _loadSlaStats() {
    try {
      const data = await _api('/sla/policies/stats');
      const strip = _q('#slaStatsStrip');
      strip.innerHTML = [
        { label: 'Active Policies',   value: data.enabled_policies ?? 0,   cls: '' },
        { label: 'Open Breaches',     value: data.open_breaches ?? 0,       cls: (data.open_breaches > 0) ? 'danger' : '' },
        { label: 'Breaches Today',    value: data.breaches_today ?? 0,      cls: (data.breaches_today > 0) ? 'warning' : '' },
        { label: 'Response Breaches', value: (data.breaches_by_type || {}).response ?? 0, cls: '' },
        { label: 'Resolve Breaches',  value: (data.breaches_by_type || {}).resolve  ?? 0, cls: '' },
      ].map(s => `<div class="stat-card ${s.cls}"><div class="stat-value">${s.value}</div><div class="stat-label">${s.label}</div></div>`).join('');
    } catch (_) {}
  }

  async function _openSlaModal(policyId) {
    _slaEditId = policyId;
    _q('#slaPolicyModalTitle').textContent = policyId ? 'Edit Service Goal' : 'New Service Goal';
    _q('#slaPolName').value      = '';
    _q('#slaPolSeverity').value  = '';
    _q('#slaPolResponse').value  = '60';
    _q('#slaPolResolve').value   = '240';
    _q('#slaPolEnabled').checked = true;
    if (policyId) {
      try {
        const p = await _api(`/sla/policies/${policyId}`);
        _q('#slaPolName').value      = p.name || '';
        _q('#slaPolSeverity').value  = p.severity || '';
        _q('#slaPolResponse').value  = p.response_minutes ?? 60;
        _q('#slaPolResolve').value   = p.resolve_minutes  ?? 240;
        _q('#slaPolEnabled').checked = !!p.enabled;
      } catch (_) {}
    }
    _q('#slaPolicyModal').hidden = false;
  }

  function _closeSlaModal() {
    _q('#slaPolicyModal').hidden = true;
    _slaEditId = null;
  }

  async function _deleteSlaPolicy(id, name) {
    if (!confirm(`Delete SLA policy "${name}"? All associated breach records will also be removed.`)) return;
    try {
      await _api(`/sla/policies/${id}`, 'DELETE');
      _loadSlaPolicies();
      _loadSlaBreaches();
      _loadSlaStats();
    } catch (err) {
      alert('Delete failed: ' + (err.message || err));
    }
  }

  // -- On-call ---------------------------------------------------------------

  let _oncallEditSchId = null;

  function initOncallView() {
    _loadOncallCurrent();
    _loadOncallSchedules();

    _bind('oncallAddScheduleBtn',    'click', () => _openOncallScheduleModal(null));
    _bind('oncallScheduleModalClose','click', _closeOncallScheduleModal);
    _bind('oncallScheduleModalCancel','click', _closeOncallScheduleModal);
    _bind('oncallSlotModalClose',    'click', () => { _q('#oncallSlotModal').hidden = true; });
    _bind('oncallSlotModalCancel',   'click', () => { _q('#oncallSlotModal').hidden = true; });
    _bind('oncallEscModalClose',     'click', () => { _q('#oncallEscModal').hidden = true; });
    _bind('oncallEscModalCancel',    'click', () => { _q('#oncallEscModal').hidden = true; });

    _q('#oncallScheduleModal').addEventListener('click', e => {
      if (e.target === _q('#oncallScheduleModal')) _closeOncallScheduleModal();
    });

    _q('#oncallScheduleForm').addEventListener('submit', async e => {
      e.preventDefault();
      const body = {
        name:        _q('#oncallSchName').value.trim(),
        description: _q('#oncallSchDesc').value.trim(),
        timezone:    _q('#oncallSchTz').value.trim() || 'UTC',
        enabled:     _q('#oncallSchEnabled').checked,
      };
      if (!body.name) return;
      try {
        if (_oncallEditSchId) {
          await _api(`/oncall/schedules/${_oncallEditSchId}`, 'PATCH', body);
        } else {
          await _api('/oncall/schedules', 'POST', body);
        }
        _closeOncallScheduleModal();
        _loadOncallSchedules();
      } catch (err) { alert('Save failed: ' + (err.message || err)); }
    });

    _q('#oncallSlotForm').addEventListener('submit', async e => {
      e.preventDefault();
      const body = {
        schedule_id:  _q('#oncallSlotScheduleId').value,
        member_name:  _q('#oncallSlotName').value.trim(),
        member_email: _q('#oncallSlotEmail').value.trim(),
        starts_at:    _q('#oncallSlotStart').value.trim(),
        ends_at:      _q('#oncallSlotEnd').value.trim(),
        is_override:  _q('#oncallSlotOverride').checked,
        note:         _q('#oncallSlotNote').value.trim(),
      };
      try {
        await _api('/oncall/slots', 'POST', body);
        _q('#oncallSlotModal').hidden = true;
        _loadOncallSchedules();
        _loadOncallCurrent();
      } catch (err) { alert('Add slot failed: ' + (err.message || err)); }
    });

    _q('#oncallEscForm').addEventListener('submit', async e => {
      e.preventDefault();
      const body = {
        schedule_id:   _q('#oncallEscScheduleId').value,
        level:         parseInt(_q('#oncallEscLevel').value, 10),
        contact_name:  _q('#oncallEscName').value.trim(),
        contact_email: _q('#oncallEscEmail').value.trim(),
        delay_minutes: parseInt(_q('#oncallEscDelay').value, 10),
      };
      try {
        await _api('/oncall/escalations', 'POST', body);
        _q('#oncallEscModal').hidden = true;
        _loadOncallSchedules();
      } catch (err) { alert('Add tier failed: ' + (err.message || err)); }
    });
  }

  async function _loadOncallCurrent() {
    try {
      const data = await _api('/oncall/schedules/current');
      const slots = data.on_call || [];
      const el = _q('#oncallCurrentList');
      if (!slots.length) {
        el.innerHTML = '<span style="color:var(--text-muted);">No one is currently on call.</span>';
      } else {
        el.innerHTML = slots.map(s =>
          `<div style="display:flex;align-items:center;gap:10px;margin-bottom:4px;">
            <span class="badge success" style="min-width:60px;text-align:center;">${_esc(s.schedule_name)}</span>
            <strong>${_esc(s.member_name)}</strong>
            ${s.member_email ? `<span style="color:var(--text-muted);font-size:11px;">&lt;${_esc(s.member_email)}&gt;</span>` : ''}
            ${s.is_override ? '<span class="badge warning" style="font-size:10px;">override</span>' : ''}
            <span style="color:var(--text-muted);font-size:11px;">until ${_relativeTime(s.ends_at)}</span>
          </div>`
        ).join('');
      }
    } catch (_) {}
  }

  async function _loadOncallSchedules() {
    const container = _q('#oncallSchedulesList');
    try {
      const data = await _api('/oncall/schedules');
      const list = data.schedules || [];
      if (!list.length) {
        container.innerHTML = '<p style="color:var(--text-muted);text-align:center;padding:32px;">No schedules defined yet.</p>';
        return;
      }
      const cards = await Promise.all(list.map(async s => {
        let detail = s;
        try { detail = await _api(`/oncall/schedules/${s.id}`); } catch (_) {}
        const current   = (detail.current_oncall || []);
        const slots     = (detail.upcoming_slots || []).slice(0, 5);
        const escs      = (detail.escalation_policy || []);
        const statusBadge = s.enabled
          ? '<span class="badge success">Active</span>'
          : '<span class="badge muted">Disabled</span>';
        const currentHtml = current.length
          ? current.map(c => `<span class="badge success">${_esc(c.member_name)}</span>`).join(' ')
          : '<span style="color:var(--text-muted);font-size:11px;">No one on call</span>';
        const slotsHtml = slots.length
          ? `<table class="data-table" style="margin-top:8px;"><thead><tr><th>Member</th><th>Starts</th><th>Ends</th><th>Type</th><th></th></tr></thead><tbody>
              ${slots.map(slot => `<tr>
                <td>${_esc(slot.member_name)} ${slot.member_email ? `<span style="color:var(--text-muted);font-size:11px;">&lt;${_esc(slot.member_email)}&gt;</span>` : ''}</td>
                <td style="font-size:11px;">${_relativeTime(slot.starts_at)}</td>
                <td style="font-size:11px;">${_relativeTime(slot.ends_at)}</td>
                <td>${slot.is_override ? '<span class="badge warning">Override</span>' : '<span class="badge info">Rotation</span>'}</td>
                <td><button class="btn xs danger" onclick="_deleteOncallSlot('${slot.id}')">Remove</button></td>
              </tr>`).join('')}
            </tbody></table>`
          : '<p style="color:var(--text-muted);font-size:12px;margin:8px 0;">No upcoming slots.</p>';
        const escHtml = escs.length
          ? `<table class="data-table" style="margin-top:8px;"><thead><tr><th>Level</th><th>Contact</th><th>After</th><th></th></tr></thead><tbody>
              ${escs.map(e => `<tr>
                <td><strong>L${e.level}</strong></td>
                <td>${_esc(e.contact_name)} ${e.contact_email ? `<span style="color:var(--text-muted);font-size:11px;">&lt;${_esc(e.contact_email)}&gt;</span>` : ''}</td>
                <td style="font-size:11px;">${e.delay_minutes} min</td>
                <td><button class="btn xs danger" onclick="_deleteOncallEsc('${e.id}')">Remove</button></td>
              </tr>`).join('')}
            </tbody></table>`
          : '<p style="color:var(--text-muted);font-size:12px;margin:8px 0;">No escalation policy.</p>';
        return `<article class="panel" style="margin-bottom:16px;">
          <div class="panel-head" style="display:flex;align-items:center;justify-content:space-between;">
            <div style="display:flex;align-items:center;gap:10px;">
              <span class="panel-title">${_esc(s.name)}</span>
              ${statusBadge}
              <span style="font-size:11px;color:var(--text-muted);">TZ: ${_esc(s.timezone || 'UTC')}</span>
            </div>
            <div style="display:flex;gap:6px;">
              <button class="btn xs" onclick="_openOncallScheduleModal('${s.id}')">Edit</button>
              <button class="btn xs primary" onclick="_openOncallSlotModal('${s.id}')">+ Slot</button>
              <button class="btn xs" onclick="_openOncallEscModal('${s.id}')">+ Escalation</button>
              <button class="btn xs danger" onclick="_deleteOncallSchedule('${s.id}','${_esc(s.name)}')">Delete</button>
            </div>
          </div>
          <div class="panel-body">
            <div style="margin-bottom:12px;">
              <div style="font-size:11px;font-weight:600;color:var(--text-muted);margin-bottom:4px;">ON CALL NOW</div>
              ${currentHtml}
            </div>
            <details open>
              <summary style="font-size:12px;font-weight:600;cursor:pointer;margin-bottom:4px;">Upcoming Slots</summary>
              ${slotsHtml}
            </details>
            <details style="margin-top:12px;">
              <summary style="font-size:12px;font-weight:600;cursor:pointer;margin-bottom:4px;">Escalation Policy</summary>
              ${escHtml}
            </details>
          </div>
        </article>`;
      }));
      container.innerHTML = cards.join('');
    } catch (_) {
      container.innerHTML = '<p style="color:var(--text-muted);text-align:center;padding:32px;">Failed to load schedules.</p>';
    }
  }

  function _openOncallScheduleModal(scheduleId) {
    _oncallEditSchId = scheduleId;
    _q('#oncallScheduleModalTitle').textContent = scheduleId ? 'Edit Schedule' : 'New Schedule';
    _q('#oncallSchName').value    = '';
    _q('#oncallSchDesc').value    = '';
    _q('#oncallSchTz').value      = 'UTC';
    _q('#oncallSchEnabled').checked = true;
    if (scheduleId) {
      _api(`/oncall/schedules/${scheduleId}`).then(s => {
        _q('#oncallSchName').value     = s.name        || '';
        _q('#oncallSchDesc').value     = s.description || '';
        _q('#oncallSchTz').value       = s.timezone    || 'UTC';
        _q('#oncallSchEnabled').checked = !!s.enabled;
      }).catch(() => {});
    }
    _q('#oncallScheduleModal').hidden = false;
  }

  function _closeOncallScheduleModal() {
    _q('#oncallScheduleModal').hidden = true;
    _oncallEditSchId = null;
  }

  function _openOncallSlotModal(scheduleId) {
    _q('#oncallSlotScheduleId').value = scheduleId;
    _q('#oncallSlotName').value  = '';
    _q('#oncallSlotEmail').value = '';
    _q('#oncallSlotStart').value = '';
    _q('#oncallSlotEnd').value   = '';
    _q('#oncallSlotOverride').checked = false;
    _q('#oncallSlotNote').value  = '';
    _q('#oncallSlotModal').hidden = false;
  }

  function _openOncallEscModal(scheduleId) {
    _q('#oncallEscScheduleId').value = scheduleId;
    _q('#oncallEscLevel').value = '1';
    _q('#oncallEscName').value  = '';
    _q('#oncallEscEmail').value = '';
    _q('#oncallEscDelay').value = '15';
    _q('#oncallEscModal').hidden = false;
  }

  async function _deleteOncallSchedule(id, name) {
    if (!confirm(`Delete on-call schedule "${name}" and all its slots?`)) return;
    try {
      await _api(`/oncall/schedules/${id}`, 'DELETE');
      _loadOncallSchedules();
      _loadOncallCurrent();
    } catch (err) { alert('Delete failed: ' + (err.message || err)); }
  }

  async function _deleteOncallSlot(id) {
    try {
      await _api(`/oncall/slots/${id}`, 'DELETE');
      _loadOncallSchedules();
      _loadOncallCurrent();
    } catch (err) { alert('Remove slot failed: ' + (err.message || err)); }
  }

  async function _deleteOncallEsc(id) {
    try {
      await _api(`/oncall/escalations/${id}`, 'DELETE');
      _loadOncallSchedules();
    } catch (err) { alert('Remove tier failed: ' + (err.message || err)); }
  }

  // -- API Keys --------------------------------------------------------------

  let _akEditId = null;

  function initApiKeysView() {
    _loadApiKeys();
    _loadAkStats();

    _bind('akAddBtn',      'click', () => _openAkModal(null));
    _bind('akModalClose',  'click', _closeAkModal);
    _bind('akModalCancel', 'click', _closeAkModal);
    _bind('akRevealClose', 'click', () => { _q('#akRevealModal').hidden = true; _loadApiKeys(); _loadAkStats(); });
    _bind('akRevealDone',  'click', () => { _q('#akRevealModal').hidden = true; _loadApiKeys(); _loadAkStats(); });
    _bind('akEnabledOnly', 'change', _loadApiKeys);

    _q('#akModal').addEventListener('click', e => {
      if (e.target === _q('#akModal')) _closeAkModal();
    });

    _q('#akForm').addEventListener('submit', async e => {
      e.preventDefault();
      const name    = _q('#akName').value.trim();
      const desc    = _q('#akDesc').value.trim();
      const expires = _q('#akExpires').value.trim() || null;
      const enabled = _q('#akEnabled').checked;
      const scopes  = [..._q('#akScopesGroup').querySelectorAll('input[type=checkbox]:checked')]
                        .map(cb => cb.value);
      if (!name) return;
      const body = { name, description: desc, scopes, expires_at: expires, enabled };
      try {
        let data;
        if (_akEditId) {
          await _api(`/api-keys/${_akEditId}`, 'PATCH', body);
          _closeAkModal();
          _loadApiKeys();
          _loadAkStats();
        } else {
          data = await _api('/api-keys', 'POST', body);
          _closeAkModal();
          _showAkReveal(data.key, data.warning || '');
        }
      } catch (err) {
        alert('Save failed: ' + (err.message || err));
      }
    });
  }

  async function _loadApiKeys() {
    const tbody       = _q('#akTbody');
    const enabledOnly = (_q('#akEnabledOnly') || {}).checked || false;
    let url = '/api-keys?limit=200';
    if (enabledOnly) url += '&enabled_only=true';
    try {
      const data = await _api(url);
      const list = data.keys || [];
      if (!list.length) {
        tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:var(--text-muted);padding:24px;">No API keys yet.</td></tr>';
        return;
      }
      tbody.innerHTML = list.map(k => {
        const scopes  = Array.isArray(k.scopes) ? k.scopes : (k.scopes || '').split(',').filter(Boolean);
        const scopeHtml = scopes.length ? scopes.map(s => `<span class="badge info" style="margin-right:2px;">${_esc(s)}</span>`).join('') : '<span style="color:var(--text-muted);font-size:11px;">full</span>';
        const expiry  = k.expires_at ? _relativeTime(k.expires_at) : '<span style="color:var(--text-muted);">Never</span>';
        const lastUsed = k.last_used_at ? _relativeTime(k.last_used_at) : '<span style="color:var(--text-muted);"> - </span>';
        const statusBadge = k.enabled
          ? '<span class="badge success">Active</span>'
          : '<span class="badge muted">Disabled</span>';
        return `<tr>
          <td>
            <strong>${_esc(k.name)}</strong>
            ${k.description ? `<div style="font-size:11px;color:var(--text-muted);">${_esc(k.description)}</div>` : ''}
          </td>
          <td><code style="font-size:11px;">${_esc(k.key_prefix)}</code></td>
          <td>${scopeHtml}</td>
          <td style="font-size:11px;">${expiry}</td>
          <td style="font-size:11px;">${lastUsed}</td>
          <td style="text-align:right;">${k.use_count ?? 0}</td>
          <td>${statusBadge}</td>
          <td style="text-align:right;white-space:nowrap;">
            <button class="btn xs" onclick="_openAkModal('${k.id}')">Edit</button>
            <button class="btn xs warning" onclick="_rotateAkKey('${k.id}','${_esc(k.name)}')">Rotate</button>
            <button class="btn xs danger"  onclick="_deleteAkKey('${k.id}','${_esc(k.name)}')">Delete</button>
          </td>
        </tr>`;
      }).join('');
    } catch (_) {
      tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:var(--text-muted);padding:24px;">Failed to load keys.</td></tr>';
    }
  }

  async function _loadAkStats() {
    try {
      const d = await _api('/api-keys/stats');
      _q('#akStatsStrip').innerHTML = [
        { label: 'Total Keys',    value: d.total       ?? 0, cls: '' },
        { label: 'Active',        value: d.enabled     ?? 0, cls: '' },
        { label: 'Disabled',      value: d.disabled    ?? 0, cls: d.disabled > 0 ? 'muted' : '' },
        { label: 'Expired',       value: d.expired     ?? 0, cls: d.expired  > 0 ? 'danger' : '' },
        { label: 'Total API Calls', value: d.total_calls ?? 0, cls: '' },
      ].map(s => `<div class="stat-card ${s.cls}"><div class="stat-value">${s.value}</div><div class="stat-label">${s.label}</div></div>`).join('');
    } catch (_) {}
  }

  async function _openAkModal(keyId) {
    _akEditId = keyId;
    _q('#akModalTitle').textContent = keyId ? 'Edit Access Key' : 'New Access Key';
    _q('#akSaveBtn').textContent    = keyId ? 'Save Changes' : 'Create Key';
    _q('#akName').value    = '';
    _q('#akDesc').value    = '';
    _q('#akExpires').value = '';
    _q('#akEnabled').checked = true;
    _q('#akScopesGroup').querySelectorAll('input[type=checkbox]').forEach(cb => cb.checked = false);
    if (keyId) {
      try {
        const k = await _api(`/api-keys/${keyId}`);
        _q('#akName').value    = k.name        || '';
        _q('#akDesc').value    = k.description || '';
        _q('#akExpires').value = k.expires_at  || '';
        _q('#akEnabled').checked = !!k.enabled;
        const scopes = Array.isArray(k.scopes) ? k.scopes : [];
        _q('#akScopesGroup').querySelectorAll('input[type=checkbox]').forEach(cb => {
          cb.checked = scopes.includes(cb.value);
        });
      } catch (_) {}
    }
    _q('#akModal').hidden = false;
  }

  function _closeAkModal() {
    _q('#akModal').hidden = true;
    _akEditId = null;
  }

  function _showAkReveal(key, warning) {
    _q('#akRevealKey').textContent     = key;
    _q('#akRevealWarning').textContent = warning;
    _q('#akRevealModal').hidden = false;
  }

  function _copyAkKey() {
    const key = _q('#akRevealKey').textContent;
    navigator.clipboard.writeText(key).then(() => {
      _q('#akCopyBtn').textContent = 'Copied!';
      setTimeout(() => { _q('#akCopyBtn').textContent = 'Copy'; }, 2000);
    }).catch(() => {});
  }

  async function _rotateAkKey(id, name) {
    if (!confirm(`Rotate API key "${name}"? The old key will stop working immediately.`)) return;
    try {
      const data = await _api(`/api-keys/${id}/rotate`, 'POST');
      _showAkReveal(data.key, data.warning || '');
    } catch (err) {
      alert('Rotate failed: ' + (err.message || err));
    }
  }

  async function _deleteAkKey(id, name) {
    if (!confirm(`Permanently delete API key "${name}"?`)) return;
    try {
      await _api(`/api-keys/${id}`, 'DELETE');
      _loadApiKeys();
      _loadAkStats();
    } catch (err) {
      alert('Delete failed: ' + (err.message || err));
    }
  }

  // -- Maintenance Windows ---------------------------------------------------

  let _maintEditId = null;

  function initMaintenanceView() {
    _loadMaintenanceWindows();
    _loadMaintenanceStatus();

    _bind('maintAddBtn',           'click', () => _openMaintModal(null));
    _bind('maintWindowModalClose', 'click', _closeMaintModal);
    _bind('maintWindowModalCancel','click', _closeMaintModal);
    _bind('maintLogModalClose',    'click', _closeMaintLogModal);
    _bind('maintLogModalCloseBtn', 'click', _closeMaintLogModal);
    _bind('maintStatusFilter',     'change', _loadMaintenanceWindows);
    _bind('maintRefreshBtn',       'click', () => { _loadMaintenanceWindows(); _loadMaintenanceStatus(); });

    _q('#maintWindowModal').addEventListener('click', e => {
      if (e.target === _q('#maintWindowModal')) _closeMaintModal();
    });
    _q('#maintLogModal').addEventListener('click', e => {
      if (e.target === _q('#maintLogModal')) _closeMaintLogModal();
    });

    _q('#maintWindowForm').addEventListener('submit', async e => {
      e.preventDefault();
      const name      = _q('#maintWinName').value.trim();
      const desc      = _q('#maintWinDesc').value.trim();
      const startsAt  = _q('#maintWinStartsAt').value.trim();
      const endsAt    = _q('#maintWinEndsAt').value.trim();
      const suppAlerts   = _q('#maintWinAlerts').checked;
      const suppInc      = _q('#maintWinIncidents').checked;
      const suppSla      = _q('#maintWinSla').checked;
      if (!name || !startsAt || !endsAt) return;
      const body = {
        name, description: desc, starts_at: startsAt, ends_at: endsAt,
        suppress_alerts: suppAlerts, suppress_incidents: suppInc, suppress_sla: suppSla,
      };
      try {
        if (_maintEditId) {
          await _api(`/maintenance/${_maintEditId}`, 'PATCH', body);
        } else {
          await _api('/maintenance', 'POST', body);
        }
        _closeMaintModal();
        _loadMaintenanceWindows();
        _loadMaintenanceStatus();
      } catch (err) {
        alert('Save failed: ' + (err.message || err));
      }
    });
  }

  async function _loadMaintenanceWindows() {
    const tbody  = _q('#maintWindowsTbody');
    const status = (_q('#maintStatusFilter') || {}).value || '';
    let url = '/maintenance?limit=100';
    if (status) url += '&status=' + encodeURIComponent(status);
    try {
      const data = await _api(url);
      const list = data.windows || [];
      _q('#maintWindowsCount').textContent = `${data.total ?? list.length} window${list.length !== 1 ? 's' : ''}`;
      if (!list.length) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-muted);padding:24px;">No system update windows found.</td></tr>';
        return;
      }
      const statusBadge = s => ({
        scheduled: '<span class="badge info">Scheduled</span>',
        active:    '<span class="badge warning">Active</span>',
        completed: '<span class="badge success">Completed</span>',
        cancelled: '<span class="badge muted">Cancelled</span>',
      }[s] || `<span class="badge">${s}</span>`);

      tbody.innerHTML = list.map(w => {
        const suppressed = [
          w.suppress_alerts    ? 'Alerts'    : '',
          w.suppress_incidents ? 'Incidents' : '',
          w.suppress_sla       ? 'SLA'       : '',
        ].filter(Boolean).join(', ') || ' - ';
        const actions = w.status === 'scheduled'
          ? `<button class="btn xs success" onclick="_maintActivate('${w.id}')">Activate</button>
             <button class="btn xs danger"  onclick="_maintCancel('${w.id}', '${_esc(w.name)}')">Cancel</button>`
          : w.status === 'active'
          ? `<button class="btn xs" onclick="_maintComplete('${w.id}')">Complete</button>
             <button class="btn xs danger" onclick="_maintCancel('${w.id}', '${_esc(w.name)}')">Cancel</button>`
          : '';
        return `<tr>
          <td>
            <a href="#" onclick="event.preventDefault();_openMaintLogModal('${w.id}','${_esc(w.name)}')" style="font-weight:600;">${_esc(w.name)}</a>
            ${w.description ? `<div style="font-size:11px;color:var(--text-muted);">${_esc(w.description)}</div>` : ''}
          </td>
          <td style="font-size:11px;">${_relativeTime(w.starts_at)}</td>
          <td style="font-size:11px;">${_relativeTime(w.ends_at)}</td>
          <td>${statusBadge(w.status)}</td>
          <td style="font-size:11px;color:var(--text-muted);">${suppressed}</td>
          <td style="text-align:right;white-space:nowrap;">
            ${actions}
            ${w.status !== 'active' ? `<button class="btn xs" onclick="_openMaintModal('${w.id}')">Edit</button>` : ''}
            ${w.status !== 'active' ? `<button class="btn xs danger" onclick="_deleteMaintWindow('${w.id}','${_esc(w.name)}')">Delete</button>` : ''}
          </td>
        </tr>`;
      }).join('');
    } catch (_) {
      tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-muted);padding:24px;">Failed to load windows.</td></tr>';
    }
  }

  async function _loadMaintenanceStatus() {
    try {
      const data = await _api('/maintenance/status');
      const banner = _q('#maintActiveBanner');
      if (data.is_active && data.active_window) {
        banner.hidden = false;
        _q('#maintActiveBannerText').textContent =
          `Maintenance active: "${data.active_window.name}"  -  ends ${_relativeTime(data.active_window.ends_at)}`;
      } else {
        banner.hidden = true;
      }
      const c = data.counts || {};
      const strip = _q('#maintStatsStrip');
      strip.innerHTML = [
        { label: 'Scheduled',  value: c.scheduled  ?? 0, cls: '' },
        { label: 'Active',     value: c.active      ?? 0, cls: c.active > 0 ? 'warning' : '' },
        { label: 'Completed',  value: c.completed   ?? 0, cls: '' },
        { label: 'Cancelled',  value: c.cancelled   ?? 0, cls: '' },
      ].map(s => `<div class="stat-card ${s.cls}"><div class="stat-value">${s.value}</div><div class="stat-label">${s.label}</div></div>`).join('');
    } catch (_) {}
  }

  async function _openMaintModal(windowId) {
    _maintEditId = windowId;
    _q('#maintWindowModalTitle').textContent = windowId ? 'Edit System Update Window' : 'New System Update Window';
    _q('#maintWinName').value     = '';
    _q('#maintWinDesc').value     = '';
    _q('#maintWinStartsAt').value = '';
    _q('#maintWinEndsAt').value   = '';
    _q('#maintWinAlerts').checked    = true;
    _q('#maintWinIncidents').checked = true;
    _q('#maintWinSla').checked       = true;
    if (windowId) {
      try {
        const w = await _api(`/maintenance/${windowId}`);
        _q('#maintWinName').value     = w.name        || '';
        _q('#maintWinDesc').value     = w.description || '';
        _q('#maintWinStartsAt').value = w.starts_at   || '';
        _q('#maintWinEndsAt').value   = w.ends_at     || '';
        _q('#maintWinAlerts').checked    = !!w.suppress_alerts;
        _q('#maintWinIncidents').checked = !!w.suppress_incidents;
        _q('#maintWinSla').checked       = !!w.suppress_sla;
      } catch (_) {}
    }
    _q('#maintWindowModal').hidden = false;
  }

  function _closeMaintModal() {
    _q('#maintWindowModal').hidden = true;
    _maintEditId = null;
  }

  async function _openMaintLogModal(windowId, name) {
    _q('#maintLogModalTitle').textContent = `Window Log: ${name}`;
    _q('#maintLogModalBody').innerHTML = '<p style="color:var(--text-muted);text-align:center;">Loading...</p>';
    _q('#maintLogModal').hidden = false;
    try {
      const w = await _api(`/maintenance/${windowId}`);
      const log = w.log || [];
      if (!log.length) {
        _q('#maintLogModalBody').innerHTML = '<p style="color:var(--text-muted);text-align:center;padding:20px;">No log entries.</p>';
        return;
      }
      _q('#maintLogModalBody').innerHTML = `
        <table class="data-table">
          <thead><tr><th>Event</th><th>Note</th><th>Time</th></tr></thead>
          <tbody>${log.map(e => `<tr>
            <td><strong>${_esc(e.event)}</strong></td>
            <td style="font-size:11px;color:var(--text-muted);">${_esc(e.note)}</td>
            <td style="font-size:11px;color:var(--text-muted);">${_relativeTime(e.ts)}</td>
          </tr>`).join('')}</tbody>
        </table>`;
    } catch (_) {
      _q('#maintLogModalBody').innerHTML = '<p style="color:var(--text-muted);text-align:center;">Failed to load log.</p>';
    }
  }

  function _closeMaintLogModal() { _q('#maintLogModal').hidden = true; }

  async function _maintActivate(id) {
    try {
      await _api(`/maintenance/${id}/activate`, 'POST');
      _loadMaintenanceWindows();
      _loadMaintenanceStatus();
    } catch (err) { alert('Activate failed: ' + (err.message || err)); }
  }

  async function _maintComplete(id) {
    try {
      await _api(`/maintenance/${id}/complete`, 'POST');
      _loadMaintenanceWindows();
      _loadMaintenanceStatus();
    } catch (err) { alert('Complete failed: ' + (err.message || err)); }
  }

  async function _maintCancel(id, name) {
    if (!confirm(`Cancel system update window "${name}"?`)) return;
    try {
      await _api(`/maintenance/${id}/cancel`, 'POST');
      _loadMaintenanceWindows();
      _loadMaintenanceStatus();
    } catch (err) { alert('Cancel failed: ' + (err.message || err)); }
  }

  async function _deleteMaintWindow(id, name) {
    if (!confirm(`Delete system update window "${name}"?`)) return;
    try {
      await _api(`/maintenance/${id}`, 'DELETE');
      _loadMaintenanceWindows();
      _loadMaintenanceStatus();
    } catch (err) { alert('Delete failed: ' + (err.message || err)); }
  }

  // ===========================================================================
  // RUNBOOKS
  // ===========================================================================
  let _rbOffset = 0;
  const _RB_LIMIT = 25;
  let _rbCurrentId = null;

  function initRunbooksView() {
    _loadRbCategories();
    _loadRbStats();
    _loadRunbooks();

    _q('#rbAddBtn').onclick = () => _openRbModal();
    _q('#rbRefreshBtn').onclick = () => { _loadRbStats(); _loadRunbooks(); };
    _q('#rbSearchBtn').onclick = () => { _rbOffset = 0; _loadRunbooks(); };
    _q('#rbSearchInput').onkeydown = e => { if (e.key === 'Enter') { _rbOffset = 0; _loadRunbooks(); } };
    _q('#rbCategoryFilter').onchange = () => { _rbOffset = 0; _loadRunbooks(); };

    _q('#rbEditModalClose').onclick   = () => _closeRbModal();
    _q('#rbEditModalCancel').onclick  = () => _closeRbModal();
    _q('#rbEditForm').onsubmit        = e  => { e.preventDefault(); _saveRunbook(); };

    _q('#rbVersionModalClose').onclick    = () => { _q('#rbVersionModal').hidden = true; };
    _q('#rbVersionModalCloseBtn').onclick  = () => { _q('#rbVersionModal').hidden = true; };
    _q('#rbDetailEditBtn').onclick = () => {
      if (_rbCurrentId) _loadRbForEdit(_rbCurrentId);
    };
    _q('#rbVersionHistoryBtn').onclick = () => {
      if (_rbCurrentId) _loadRbVersions(_rbCurrentId);
    };
  }

  async function _loadRbStats() {
    try {
      const s = await _api('/runbooks/stats');
      const strip = _q('#rbStatsStrip');
      strip.innerHTML = [
        ['Total', s.total],
        ['Versions', s.total_versions],
        ['Categories', (s.by_category || []).length],
      ].map(([l, v]) =>
        `<div style="background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:10px 16px;min-width:90px;">
           <div style="font-size:20px;font-weight:700;">${v}</div>
           <div style="font-size:11px;color:var(--text-muted);">${l}</div>
         </div>`
      ).join('');
    } catch (_) {}
  }

  async function _loadRbCategories() {
    try {
      const data = await _api('/runbooks/categories');
      const sel = _q('#rbCategoryFilter');
      const current = sel.value;
      sel.innerHTML = '<option value="">All categories</option>' +
        (data.categories || []).map(c => `<option value="${_esc(c)}">${_esc(c)}</option>`).join('');
      sel.value = current;
    } catch (_) {}
  }

  async function _loadRunbooks() {
    const q  = _q('#rbSearchInput').value.trim();
    const cat = _q('#rbCategoryFilter').value;
    const params = new URLSearchParams({ limit: _RB_LIMIT, offset: _rbOffset });
    if (q)   params.set('q', q);
    if (cat) params.set('category', cat);
    const tbody = _q('#rbListTbody');
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-muted);padding:24px;">Loading...</td></tr>';
    try {
      const data = await _api(`/runbooks?${params}`);
      const rbs = data.runbooks || [];
      _q('#rbListCount').textContent = `${data.total} total`;
      if (!rbs.length) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-muted);padding:24px;">No runbooks found.</td></tr>';
      } else {
        tbody.innerHTML = rbs.map(r => {
          const tags = (r.tags || []).map(t => `<span style="background:var(--accent-bg);color:var(--accent);border-radius:4px;padding:1px 5px;font-size:10px;margin-right:2px;">${_esc(t)}</span>`).join('');
          return `<tr style="cursor:pointer;" onclick="_rbOpenDetail('${r.id}')">
            <td><strong>${_esc(r.title)}</strong><br><small style="color:var(--text-muted);">${_esc((r.content_preview||'').slice(0,80))}</small></td>
            <td>${_esc(r.category||' - ')}</td>
            <td>${tags||' - '}</td>
            <td>${r.view_count||0}</td>
            <td style="font-size:11px;">${(r.updated_at||'').slice(0,10)}</td>
            <td>
              <button class="btn xs" onclick="event.stopPropagation();_loadRbForEdit('${r.id}')">Edit</button>
              <button class="btn xs danger" onclick="event.stopPropagation();_deleteRunbook('${r.id}','${_esc(r.title).replace(/'/g,"\\'")}')">Del</button>
            </td>
          </tr>`;
        }).join('');
      }
      _renderRbPagination(data.total, _rbOffset, _RB_LIMIT);
    } catch (err) {
      tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--danger);padding:24px;">${_esc(err.message||'Error')}</td></tr>`;
    }
  }

  function _renderRbPagination(total, offset, limit) {
    const pag = _q('#rbPagination');
    const page = Math.floor(offset / limit) + 1;
    const pages = Math.ceil(total / limit) || 1;
    pag.innerHTML = `
      <button class="btn xs" ${offset === 0 ? 'disabled' : ''} onclick="_rbOffset=Math.max(0,_rbOffset-${limit});_loadRunbooks()">Prev</button>
      <span style="color:var(--text-muted);">Page ${page} / ${pages}</span>
      <button class="btn xs" ${offset + limit >= total ? 'disabled' : ''} onclick="_rbOffset=_rbOffset+${limit};_loadRunbooks()">Next</button>`;
  }

  async function _rbOpenDetail(id) {
    _rbCurrentId = id;
    try {
      const rb = await _api(`/runbooks/${id}`);
      const panel = _q('#rbDetailPanel');
      panel.hidden = false;
      _q('#rbDetailTitle').textContent = rb.title;
      const tags = (rb.tags || []).join(', ');
      _q('#rbDetailMeta').innerHTML =
        `<strong>Category:</strong> ${_esc(rb.category||' - ')} &nbsp;|&nbsp;
         <strong>Tags:</strong> ${_esc(tags||' - ')} &nbsp;|&nbsp;
         <strong>Owner:</strong> ${_esc(rb.owner||' - ')} &nbsp;|&nbsp;
         <strong>Views:</strong> ${rb.view_count}` +
        (rb.latest_version ? `<br><strong>v${rb.latest_version.version_number}</strong>  -  ${_esc(rb.latest_version.change_note||'')} by ${_esc(rb.latest_version.edited_by||'?')} on ${(rb.latest_version.edited_at||'').slice(0,10)}` : '');
      _q('#rbDetailContent').textContent = rb.content_md || '(empty)';
    } catch (err) { alert('Load failed: ' + (err.message || err)); }
  }

  function _openRbModal(rb) {
    _q('#rbEditModalTitle').textContent = rb ? 'Edit Automation Guide' : 'New Automation Guide';
    _q('#rbFormId').value           = rb ? rb.id : '';
    _q('#rbFormTitle').value        = rb ? rb.title : '';
    _q('#rbFormCategory').value     = rb ? (rb.category||'') : '';
    _q('#rbFormTags').value         = rb ? (Array.isArray(rb.tags) ? rb.tags.join(', ') : (rb.tags||'')) : '';
    _q('#rbFormOwner').value        = rb ? (rb.owner||'') : '';
    _q('#rbFormContent').value      = rb ? (rb.content_md||'') : '';
    _q('#rbFormChangeNote').value   = '';
    _q('#rbEditModal').hidden = false;
  }

  function _closeRbModal() { _q('#rbEditModal').hidden = true; }

  async function _loadRbForEdit(id) {
    try {
      const rb = await _api(`/runbooks/${id}`);
      _openRbModal(rb);
    } catch (err) { alert('Load failed: ' + (err.message || err)); }
  }

  async function _saveRunbook() {
    const id   = _q('#rbFormId').value;
    const body = {
      title:      _q('#rbFormTitle').value.trim(),
      category:   _q('#rbFormCategory').value.trim(),
      tags:       _q('#rbFormTags').value.trim(),
      owner:      _q('#rbFormOwner').value.trim(),
      content_md: _q('#rbFormContent').value,
      change_note: _q('#rbFormChangeNote').value.trim() || 'Updated',
      edited_by:  'user',
    };
    try {
      if (id) {
        await _api(`/runbooks/${id}`, 'PATCH', body);
      } else {
        await _api('/runbooks', 'POST', body);
      }
      _closeRbModal();
      _loadRbStats();
      _loadRbCategories();
      _loadRunbooks();
      if (_rbCurrentId === id) _rbOpenDetail(id);
    } catch (err) { alert('Save failed: ' + (err.message || err)); }
  }

  async function _loadRbVersions(id) {
    try {
      const data = await _api(`/runbooks/${id}/versions`);
      const versions = data.versions || [];
      _q('#rbVersionModalTitle').textContent = 'Version History';
      _q('#rbVersionList').innerHTML = versions.length
        ? versions.map(v =>
            `<div style="border-bottom:1px solid var(--border);padding:12px 0;">
               <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">
                 <strong>v${v.version_number}</strong>
                 <span style="font-size:11px;color:var(--text-muted);">${(v.edited_at||'').slice(0,16).replace('T',' ')} UTC</span>
                 <span style="font-size:11px;color:var(--text-muted);">by ${_esc(v.edited_by||'?')}</span>
               </div>
               <div style="font-size:12px;">${_esc(v.change_note||'')}</div>
               <button class="btn xs" style="margin-top:6px;" onclick="_viewRbVersion('${id}',${v.version_number})">View content</button>
             </div>`
          ).join('')
        : '<p style="color:var(--text-muted);padding:16px;">No versions recorded.</p>';
      _q('#rbVersionModal').hidden = false;
    } catch (err) { alert('Load failed: ' + (err.message || err)); }
  }

  async function _viewRbVersion(id, num) {
    try {
      const v = await _api(`/runbooks/${id}/versions/${num}`);
      const w = window.open('', '_blank', 'width=700,height=560,scrollbars=yes');
      if (w) {
        w.document.write(`<pre style="font-family:monospace;white-space:pre-wrap;padding:20px;">${v.content_md||'(empty)'}</pre>`);
        w.document.close();
      }
    } catch (err) { alert('Load failed: ' + (err.message || err)); }
  }

  async function _deleteRunbook(id, name) {
    if (!confirm(`Delete runbook "${name}"?`)) return;
    try {
      await _api(`/runbooks/${id}`, 'DELETE');
      if (_rbCurrentId === id) {
        _rbCurrentId = null;
        _q('#rbDetailPanel').hidden = true;
      }
      _loadRbStats();
      _loadRunbooks();
    } catch (err) { alert('Delete failed: ' + (err.message || err)); }
  }

  // ── SLO Management ───────────────────────────────────────────────────────────
  let _sloOffset=0; const _SLO_LIMIT=50; let _sloCurrentId=null;

  function initSlosView() {
    _loadSloStats(); _loadSlos();
    _q('#sloAddBtn').onclick     = () => _openSloModal();
    _q('#sloRefreshBtn').onclick = () => { _loadSloStats(); _loadSlos(); };
    _q('#sloSearchBtn').onclick  = () => { _sloOffset=0; _loadSlos(); };
    _q('#sloSearchInput').onkeydown = e => { if(e.key==='Enter'){_sloOffset=0;_loadSlos();} };
    _q('#sloStatusFilter').onchange = () => { _sloOffset=0; _loadSlos(); };
    _q('#sloWindowFilter').onchange = () => { _sloOffset=0; _loadSlos(); };
    _q('#sloEditModalClose').onclick  = () => { _q('#sloEditModal').hidden=true; };
    _q('#sloEditModalCancel').onclick = () => { _q('#sloEditModal').hidden=true; };
    _q('#sloEditForm').onsubmit = e => { e.preventDefault(); _saveSlo(); };
    _q('#sloDetailModalClose').onclick    = () => { _q('#sloDetailModal').hidden=true; };
    _q('#sloDetailModalCloseBtn').onclick = () => { _q('#sloDetailModal').hidden=true; };
    _q('#sloDetailEditBtn').onclick    = () => { if(_sloCurrentId) _openSloModal(_sloCurrentId); };
    _q('#sloTransitionBtn').onclick    = () => { if(_sloCurrentId) _openSloTransModal(); };
    _q('#sloAddMeasBtn').onclick       = () => { if(_sloCurrentId) { _q('#sloMeasModal').hidden=false; _q('#sloMeasForm').reset(); } };
    _q('#sloTransitionModalClose').onclick  = () => { _q('#sloTransitionModal').hidden=true; };
    _q('#sloTransitionModalCancel').onclick = () => { _q('#sloTransitionModal').hidden=true; };
    _q('#sloTransitionForm').onsubmit = e => { e.preventDefault(); _doSloTransition(); };
    _q('#sloMeasModalClose').onclick  = () => { _q('#sloMeasModal').hidden=true; };
    _q('#sloMeasModalCancel').onclick = () => { _q('#sloMeasModal').hidden=true; };
    _q('#sloMeasForm').onsubmit = e => { e.preventDefault(); _addSloMeasurement(); };
  }

  async function _loadSloStats() {
    try {
      const s=await _api('/slos/stats');
      const strip=_q('#sloStatsStrip');
      strip.innerHTML=`<div class="ops-stats-strip">${[['Total',s.total],['Active',s.active],['Breaching',s.breaching],['Avg Target',s.avg_target!=null?s.avg_target.toFixed(2)+'%':'—']].map(([l,v])=>
        `<div class="ops-stat-card${l==='Breaching'&&v>0?' ops-tone-danger':''}"><span class="ops-stat-value">${v||0}</span><span class="ops-stat-label">${l}</span></div>`).join('')}</div>`;
    } catch(_) {}
  }

  async function _loadSlos() {
    const q=_q('#sloSearchInput').value.trim(); const status=_q('#sloStatusFilter').value; const tw=_q('#sloWindowFilter').value;
    const params=new URLSearchParams({limit:_SLO_LIMIT,offset:_sloOffset});
    if(q) params.set('q',q); if(status) params.set('status',status); if(tw) params.set('time_window',tw);
    const tbody=_q('#sloListTbody');
    tbody.innerHTML='<tr><td colspan="8" class="ops-table-state">Loading...</td></tr>';
    try {
      const data=await _api(`/slos?${params}`); const rows=data.slos||[];
      _q('#sloListCount').textContent=`${data.total} total`;
      if(!rows.length){tbody.innerHTML='<tr><td colspan="8" class="ops-table-state">No SLOs found.</td></tr>';return;}
      tbody.innerHTML=rows.map(r=>{
        const breachBadge=r.is_breaching===true?'<span class="badge bad">Breaching</span>':r.is_breaching===false?'<span class="badge ok">Healthy</span>':'<span class="ops-tone-warn">—</span>';
        const consumedPct=r.error_budget_consumed_pct!=null?r.error_budget_consumed_pct.toFixed(1)+'%':'—';
        return `<tr class="ops-row-link" onclick="_sloOpenDetail('${r.id}')">
          <td><strong>${_esc(r.name||'')}</strong></td><td>${_esc(r.service||'')}</td>
          <td>${r.target_pct}%</td><td>${r.latest_actual_pct!=null?r.latest_actual_pct+'%':'—'}</td>
          <td>${consumedPct}</td><td>${breachBadge}</td>
          <td class="ops-date">${_esc(r.time_window||'')}</td>
          <td><button class="btn xs" onclick="event.stopPropagation();_openSloModal('${r.id}')">Edit</button>
              <button class="btn xs danger" onclick="event.stopPropagation();_deleteSlo('${r.id}','${_esc(r.name||'').replace(/'/g,"\\'")}')">Del</button></td>
        </tr>`;
      }).join('');
      const pages=Math.ceil(data.total/_SLO_LIMIT)||1; const page=Math.floor(_sloOffset/_SLO_LIMIT)+1;
      _q('#sloPagination').innerHTML=`<button class="btn xs" ${_sloOffset===0?'disabled':''} onclick="_sloOffset=Math.max(0,_sloOffset-${_SLO_LIMIT});_loadSlos()">Prev</button>
        <span class="ops-pagination-label">Page ${page}/${pages}</span>
        <button class="btn xs" ${_sloOffset+_SLO_LIMIT>=data.total?'disabled':''} onclick="_sloOffset+=_SLO_LIMIT;_loadSlos()">Next</button>`;
    } catch(err){tbody.innerHTML=`<tr><td colspan="8" class="ops-table-state ops-table-state-danger">${_esc(err.message||'Error')}</td></tr>`;}
  }

  async function _sloOpenDetail(id) {
    _sloCurrentId=id; _q('#sloDetailModal').hidden=false; _q('#sloDetailModalBody').innerHTML='Loading...';
    try {
      const s=await _api(`/slos/${id}`);
      _q('#sloDetailModalTitle').textContent=s.name||'SLO';
      const measData=await _api(`/slos/${id}/measurements?limit=5`); const meas=(measData.measurements||[]);
      const allowed={draft:['active','cancelled'],active:['paused','deprecated'],paused:['active','deprecated'],deprecated:[],cancelled:[]};
      _q('#sloTransitionStatus').innerHTML=(allowed[s.status]||[]).map(st=>`<option value="${st}">${st}</option>`).join('')||'<option value="">No transitions</option>';
      const budBar=s.error_budget_consumed_pct!=null?`<div style="margin-top:8px;"><div style="display:flex;justify-content:space-between;font-size:12px;"><span>Error budget consumed</span><span>${s.error_budget_consumed_pct.toFixed(1)}%</span></div><div style="height:6px;background:var(--border);border-radius:3px;margin-top:3px;"><div style="width:${Math.min(100,s.error_budget_consumed_pct).toFixed(1)}%;height:100%;background:${s.is_breaching?'var(--danger)':'var(--accent)'};border-radius:3px;"></div></div></div>`:'';
      _q('#sloDetailModalBody').innerHTML=`<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:13px;">
        <div><b>Service</b><br>${_esc(s.service||'—')}</div><div><b>Status</b><br>${_esc(s.status||'')}</div>
        <div><b>Target</b><br>${s.target_pct}%</div><div><b>Error Budget</b><br>${s.error_budget_pct}%</div>
        <div><b>Latest Actual</b><br>${s.latest_actual_pct!=null?s.latest_actual_pct+'%':'No data'}</div>
        <div><b>Breaching</b><br>${s.is_breaching===true?'<span style="color:var(--danger);">Yes</span>':s.is_breaching===false?'<span style="color:var(--success,#2a9d8f);">No</span>':'—'}</div>
        <div><b>Window</b><br>${_esc(s.time_window||'')}</div><div><b>Owner</b><br>${_esc(s.owner||'—')}</div>
      </div>${budBar}
      <h4 style="margin:12px 0 4px;">Recent Measurements</h4>
      <table style="width:100%;font-size:12px;border-collapse:collapse;">
        <thead><tr><th style="text-align:left;padding:2px 4px;">Recorded</th><th style="text-align:right;padding:2px 4px;">Actual %</th><th style="text-align:right;padding:2px 4px;">Good / Total</th></tr></thead>
        <tbody>${meas.length?meas.map(m=>`<tr><td style="padding:2px 4px;">${(m.recorded_at||'').slice(0,16)}</td><td style="text-align:right;padding:2px 4px;">${m.actual_pct}%</td><td style="text-align:right;padding:2px 4px;">${m.good_events}/${m.total_events}</td></tr>`).join(''):'<tr><td colspan="3" style="color:var(--text-muted);padding:4px;">No measurements yet</td></tr>'}</tbody>
      </table>`;
    } catch(err){_q('#sloDetailModalBody').innerHTML=`<p style="color:var(--danger);">${_esc(err.message||'Error')}</p>`;}
  }

  async function _openSloModal(id) {
    _q('#sloEditModal').hidden=false; _q('#sloEditModalTitle').textContent=id?'Edit SLO':'New SLO'; _q('#sloFormId').value=id||'';
    if(id){try{const s=await _api(`/slos/${id}`);
      _q('#sloFormName').value=s.name||''; _q('#sloFormService').value=s.service||''; _q('#sloFormTarget').value=s.target_pct||99.9;
      _q('#sloFormWindow').value=s.time_window||'rolling_30d'; _q('#sloFormOwner').value=s.owner||'';
      _q('#sloFormTeam').value=s.team||''; _q('#sloFormDesc').value=s.description||'';
    }catch(_){}}
    else{['sloFormName','sloFormService','sloFormOwner','sloFormTeam','sloFormDesc'].forEach(id=>{const el=_q('#'+id);if(el)el.value=''});_q('#sloFormTarget').value=99.9;_q('#sloFormWindow').value='rolling_30d';}
  }

  async function _saveSlo() {
    const id=_q('#sloFormId').value;
    const body={name:_q('#sloFormName').value,service:_q('#sloFormService').value,target_pct:parseFloat(_q('#sloFormTarget').value),
      time_window:_q('#sloFormWindow').value,owner:_q('#sloFormOwner').value,team:_q('#sloFormTeam').value,description:_q('#sloFormDesc').value};
    try{await _api(id?`/slos/${id}`:'/slos',id?'PATCH':'POST',body);_q('#sloEditModal').hidden=true;_loadSloStats();_loadSlos();}
    catch(err){alert('Save failed: '+(err.message||err));}
  }

  async function _openSloTransModal() { _q('#sloTransitionModal').hidden=false; }

  async function _doSloTransition() {
    const status=_q('#sloTransitionStatus').value; const notes=_q('#sloTransitionNotes').value; if(!status) return;
    try{await _api(`/slos/${_sloCurrentId}/transition`,'POST',{status,notes});_q('#sloTransitionModal').hidden=true;_sloOpenDetail(_sloCurrentId);_loadSloStats();_loadSlos();}
    catch(err){alert('Transition failed: '+(err.message||err));}
  }

  async function _addSloMeasurement() {
    const body={actual_pct:parseFloat(_q('#sloMeasActual').value),good_events:parseInt(_q('#sloMeasGood').value)||0,total_events:parseInt(_q('#sloMeasTotal').value)||0,notes:_q('#sloMeasNotes').value};
    try{await _api(`/slos/${_sloCurrentId}/measurements`,'POST',body);_q('#sloMeasModal').hidden=true;_sloOpenDetail(_sloCurrentId);_loadSloStats();_loadSlos();}
    catch(err){alert('Failed: '+(err.message||err));}
  }

  async function _deleteSlo(id,name) {
    if(!confirm(`Delete SLO "${name}"?`)) return;
    try{await _api(`/slos/${id}`,'DELETE');_loadSloStats();_loadSlos();}
    catch(err){alert('Delete failed: '+(err.message||err));}
  }

  // ── Change Management ────────────────────────────────────────────────────────
  let _crOffset = 0; const _CR_LIMIT = 50; let _crCurrentId = null;

  function initChangesView() {
    _loadCrStats(); _loadChanges();
    _q('#crAddBtn').onclick = () => _openCrModal();
    _q('#crRefreshBtn').onclick = () => { _loadCrStats(); _loadChanges(); };
    _q('#crSearchBtn').onclick = () => { _crOffset = 0; _loadChanges(); };
    _q('#crSearchInput').onkeydown = e => { if (e.key === 'Enter') { _crOffset = 0; _loadChanges(); } };
    _q('#crStatusFilter').onchange = () => { _crOffset = 0; _loadChanges(); };
    _q('#crRiskFilter').onchange   = () => { _crOffset = 0; _loadChanges(); };
    _q('#crTypeFilter').onchange   = () => { _crOffset = 0; _loadChanges(); };
    _q('#crEditModalClose').onclick  = () => _closeCrModal();
    _q('#crEditModalCancel').onclick = () => _closeCrModal();
    _q('#crEditForm').onsubmit = e => { e.preventDefault(); _saveCr(); };
    _q('#crDetailModalClose').onclick    = () => { _q('#crDetailModal').hidden = true; };
    _q('#crDetailModalCloseBtn').onclick = () => { _q('#crDetailModal').hidden = true; };
    _q('#crDetailEditBtn').onclick = () => { if (_crCurrentId) _openCrModal(_crCurrentId); };
    _q('#crTransitionBtn').onclick = () => { if (_crCurrentId) _openCrTransition(_crCurrentId); };
    _q('#crAddApproverBtn').onclick = () => { if (_crCurrentId) { _q('#crApproverModal').hidden = false; _q('#crApproverName').value = ''; _q('#crApproverNote').value = ''; } };
    _q('#crTransitionModalClose').onclick  = () => { _q('#crTransitionModal').hidden = true; };
    _q('#crTransitionModalCancel').onclick = () => { _q('#crTransitionModal').hidden = true; };
    _q('#crTransitionForm').onsubmit = e => { e.preventDefault(); _submitCrTransition(); };
    _q('#crApproverModalClose').onclick  = () => { _q('#crApproverModal').hidden = true; };
    _q('#crApproverModalCancel').onclick = () => { _q('#crApproverModal').hidden = true; };
    _q('#crApproverForm').onsubmit = e => { e.preventDefault(); _addCrApprover(); };
  }

  async function _loadCrStats() {
    try {
      const s = await _api('/changes/stats');
      const strip = _q('#crStatsStrip');
      const items = [['Total', s.total], ['Open', s.by_status?.find(x=>x.status==='draft')?.count||0],
        ['In Progress', s.by_status?.find(x=>x.status==='in_progress')?.count||0], ['Completed', s.by_status?.find(x=>x.status==='completed')?.count||0]];
      strip.innerHTML = `<div class="ops-stats-strip">${items.map(([l,v]) => `<div class="ops-stat-card"><span class="ops-stat-value">${v||0}</span><span class="ops-stat-label">${l}</span></div>`).join('')}</div>`;
    } catch(_) {}
  }

  async function _loadChanges() {
    const q = _q('#crSearchInput').value.trim();
    const status = _q('#crStatusFilter').value;
    const risk = _q('#crRiskFilter').value;
    const type = _q('#crTypeFilter').value;
    const params = new URLSearchParams({ limit: _CR_LIMIT, offset: _crOffset });
    if (q) params.set('q', q); if (status) params.set('status', status);
    if (risk) params.set('risk_level', risk); if (type) params.set('change_type', type);
    const tbody = _q('#crListTbody');
    tbody.innerHTML = '<tr><td colspan="7" class="ops-table-state">Loading...</td></tr>';
    try {
      const data = await _api(`/changes?${params}`);
      const rows = data.changes || [];
      _q('#crListCount').textContent = `${data.total} total`;
      if (!rows.length) { tbody.innerHTML = '<tr><td colspan="7" class="ops-table-state">No changes found.</td></tr>'; }
      else tbody.innerHTML = rows.map(r => `<tr class="ops-row-link" onclick="_openCrDetail('${r.id}')">
        <td><strong>${_esc(r.title)}</strong></td><td>${_esc(r.change_type||'')}</td>
        <td><span class="badge ${r.risk_level==='critical'?'bad':r.risk_level==='high'?'warn':'ok'}">${_esc(r.risk_level||'')}</span></td>
        <td><span class="badge">${_esc(r.status||'')}</span></td><td>${_esc(r.owner||'')}</td>
        <td class="ops-date">${(r.planned_start||'').slice(0,10)||'—'}</td>
        <td><button class="btn xs" onclick="event.stopPropagation();_openCrModal('${r.id}')">Edit</button>
            <button class="btn xs danger" onclick="event.stopPropagation();_deleteCr('${r.id}','${_esc(r.title).replace(/'/g,"\\'")}')">Del</button></td>
      </tr>`).join('');
      const pages = Math.ceil(data.total / _CR_LIMIT) || 1;
      const page = Math.floor(_crOffset / _CR_LIMIT) + 1;
      _q('#crPagination').innerHTML = `<button class="btn xs" ${_crOffset===0?'disabled':''} onclick="_crOffset=Math.max(0,_crOffset-${_CR_LIMIT});_loadChanges()">Prev</button>
        <span class="ops-pagination-label">Page ${page}/${pages}</span>
        <button class="btn xs" ${_crOffset+_CR_LIMIT>=data.total?'disabled':''} onclick="_crOffset+=_crOffset+${_CR_LIMIT};_loadChanges()">Next</button>`;
    } catch(err) { tbody.innerHTML = `<tr><td colspan="7" class="ops-table-state ops-table-state-danger">${_esc(err.message||'Error')}</td></tr>`; }
  }

  async function _openCrDetail(id) {
    _crCurrentId = id;
    _q('#crDetailModal').hidden = false;
    _q('#crDetailModalBody').innerHTML = 'Loading...';
    try {
      const cr = await _api(`/changes/${id}`);
      _q('#crDetailModalTitle').textContent = cr.title;
      const appR = await _api(`/changes/${id}/approvals`);
      const approvals = (appR.approvals||[]).map(a => `<li>${_esc(a.name)} — <strong>${_esc(a.decision||'pending')}</strong>${a.notes?` <em>${_esc(a.notes)}</em>`:''}</li>`).join('');
      _q('#crDetailModalBody').innerHTML = `
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:13px;">
          <div><b>Type</b><br>${_esc(cr.change_type||'')}</div><div><b>Risk</b><br>${_esc(cr.risk_level||'')}</div>
          <div><b>Status</b><br>${_esc(cr.status||'')}</div><div><b>Owner</b><br>${_esc(cr.owner||'')}</div>
          <div><b>Planned Start</b><br>${(cr.planned_start||'').slice(0,16)||'—'}</div>
          <div><b>Planned End</b><br>${(cr.planned_end||'').slice(0,16)||'—'}</div>
        </div>
        ${cr.description?`<p style="margin-top:10px;">${_esc(cr.description)}</p>`:''}
        ${cr.rollback_plan?`<p><b>Rollback:</b> ${_esc(cr.rollback_plan)}</p>`:''}
        <h4 style="margin:12px 0 4px;">Approvers</h4><ul style="margin:0;padding-left:18px;">${approvals||'<li style="color:var(--text-muted);">None yet</li>'}</ul>`;
    } catch(err) { _q('#crDetailModalBody').innerHTML = `<p style="color:var(--danger);">${_esc(err.message||'Error')}</p>`; }
  }

  async function _openCrModal(id) {
    _q('#crFormId').value = id || '';
    _q('#crEditModalTitle').textContent = id ? 'Edit Change Request' : 'New Change Request';
    if (id) {
      try {
        const cr = await _api(`/changes/${id}`);
        _q('#crFormTitle').value = cr.title || ''; _q('#crFormDesc').value = cr.description || '';
        _q('#crFormType').value = cr.change_type || 'normal'; _q('#crFormRisk').value = cr.risk_level || 'low';
        _q('#crFormOwner').value = cr.owner || ''; _q('#crFormAssignee').value = cr.assignee || '';
        _q('#crFormPlannedStart').value = cr.planned_start || ''; _q('#crFormPlannedEnd').value = cr.planned_end || '';
        _q('#crFormRollback').value = cr.rollback_plan || ''; _q('#crFormIncident').value = cr.linked_incident_id || '';
        _q('#crFormRunbook').value = cr.linked_runbook_id || ''; _q('#crFormNote').value = '';
      } catch(_) {}
    } else {
      ['crFormTitle','crFormDesc','crFormOwner','crFormAssignee','crFormPlannedStart','crFormPlannedEnd','crFormRollback','crFormIncident','crFormRunbook','crFormNote'].forEach(id => { _q('#'+id).value = ''; });
      _q('#crFormType').value = 'normal'; _q('#crFormRisk').value = 'low';
    }
    _q('#crEditModal').hidden = false; _q('#crFormTitle').focus();
  }
  function _closeCrModal() { _q('#crEditModal').hidden = true; }

  async function _saveCr() {
    const id = _q('#crFormId').value;
    const body = { title: _q('#crFormTitle').value, description: _q('#crFormDesc').value,
      change_type: _q('#crFormType').value, risk_level: _q('#crFormRisk').value,
      owner: _q('#crFormOwner').value, assignee: _q('#crFormAssignee').value,
      planned_start: _q('#crFormPlannedStart').value || null, planned_end: _q('#crFormPlannedEnd').value || null,
      rollback_plan: _q('#crFormRollback').value, linked_incident_id: _q('#crFormIncident').value || null,
      linked_runbook_id: _q('#crFormRunbook').value || null, change_note: _q('#crFormNote').value };
    try {
      await _api(id ? `/changes/${id}` : '/changes', id ? 'PATCH' : 'POST', body);
      _closeCrModal(); _loadCrStats(); _loadChanges();
    } catch(err) { alert('Save failed: ' + (err.message||err)); }
  }

  async function _openCrTransition(id) {
    try {
      const cr = await _api(`/changes/${id}`);
      const allowed = { draft:['review','cancelled'], review:['approved','rejected','cancelled'],
        approved:['in_progress','cancelled'], in_progress:['completed','failed','cancelled'],
        completed:[], rejected:[], cancelled:[], failed:[] };
      const opts = (allowed[cr.status]||[]).map(s => `<option value="${s}">${s}</option>`).join('');
      _q('#crTransitionStatus').innerHTML = opts || '<option value="">No transitions available</option>';
      _q('#crTransitionApprovedBy').value = ''; _q('#crTransitionNote').value = '';
      _q('#crTransitionModal').hidden = false;
    } catch(_) {}
  }

  async function _submitCrTransition() {
    const status = _q('#crTransitionStatus').value;
    if (!status) return;
    try {
      await _api(`/changes/${_crCurrentId}/transition`, 'POST', { status, approved_by: _q('#crTransitionApprovedBy').value, notes: _q('#crTransitionNote').value });
      _q('#crTransitionModal').hidden = true; _openCrDetail(_crCurrentId); _loadCrStats(); _loadChanges();
    } catch(err) { alert('Transition failed: ' + (err.message||err)); }
  }

  async function _addCrApprover() {
    try {
      await _api(`/changes/${_crCurrentId}/approvals`, 'POST', { name: _q('#crApproverName').value, notes: _q('#crApproverNote').value });
      _q('#crApproverModal').hidden = true; _openCrDetail(_crCurrentId);
    } catch(err) { alert('Failed: ' + (err.message||err)); }
  }

  async function _deleteCr(id, name) {
    if (!confirm(`Delete change request "${name}"?`)) return;
    try { await _api(`/changes/${id}`, 'DELETE'); _loadCrStats(); _loadChanges(); }
    catch(err) { alert('Delete failed: ' + (err.message||err)); }
  }

  // ── Risk Register ────────────────────────────────────────────────────────────
  let _riskOffset = 0; const _RISK_LIMIT = 50; let _riskCurrentId = null;

  function initRisksView() {
    _loadRiskStats(); _loadRisks();
    _q('#riskNewBtn').onclick = () => _openRiskModal();
    _q('#riskSearch').oninput = _debounce(() => { _riskOffset = 0; _loadRisks(); });
    _q('#riskStatusFilter').onchange = () => { _riskOffset = 0; _loadRisks(); };
    _q('#riskCatFilter').onchange    = () => { _riskOffset = 0; _loadRisks(); };
    _q('#riskLevelFilter').onchange  = () => { _riskOffset = 0; _loadRisks(); };
    _q('#riskDetailClose').onclick   = () => { _q('#riskDetailDialog').hidden = true; };
    _q('#riskFormClose').onclick     = () => { _q('#riskFormDialog').hidden = true; };
    _q('#riskFormCancel').onclick    = () => { _q('#riskFormDialog').hidden = true; };
    _q('#riskForm').onsubmit         = e => { e.preventDefault(); _saveRisk(); };
    _q('#riskRevClose').onclick      = () => { _q('#riskRevDialog').hidden = true; };
    _q('#riskRevCancel').onclick     = () => { _q('#riskRevDialog').hidden = true; };
    _q('#riskRevForm').onsubmit      = e => { e.preventDefault(); _addRiskReview(); };
    _q('#riskAddRevBtn').onclick     = () => { if (_riskCurrentId) { _q('#riskRevDialog').hidden = false; } };
    _q('#riskTransBtn').onclick      = () => { if (_riskCurrentId) _doRiskTransition(); };
  }

  async function _loadRiskStats() {
    try {
      const s = await _api('/risks/stats');
      _q('#riskStatTotal').textContent    = s.total || 0;
      _q('#riskStatOpen').textContent     = s.open || 0;
      _q('#riskStatCritical').textContent = s.critical || 0;
      _q('#riskStatHigh').textContent     = s.high || 0;
      _q('#riskStatAvg').textContent      = s.avg_score != null ? s.avg_score.toFixed(1) : '—';
    } catch(_) {}
  }

  async function _loadRisks() {
    const q = _q('#riskSearch').value.trim();
    const status = _q('#riskStatusFilter').value;
    const cat = _q('#riskCatFilter').value;
    const level = _q('#riskLevelFilter').value;
    const params = new URLSearchParams({ limit: _RISK_LIMIT, offset: _riskOffset });
    if (q) params.set('q', q); if (status) params.set('status', status);
    if (cat) params.set('category', cat); if (level) params.set('risk_level', level);
    const tbody = _q('#riskTbody');
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-muted);padding:24px;">Loading...</td></tr>';
    try {
      const data = await _api(`/risks?${params}`);
      const rows = data.risks || [];
      if (!rows.length) { tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-muted);padding:24px;">No risks found.</td></tr>'; return; }
      tbody.innerHTML = rows.map(r => `<tr style="cursor:pointer;" onclick="_riskOpenDetail('${r.id}')">
        <td><strong>${_esc(r.title)}</strong></td><td>${_esc(r.category||'')}</td>
        <td><span class="badge ${r.risk_level==='critical'?'bad':r.risk_level==='high'?'warn':'ok'}">${_esc(r.risk_level||'')}</span></td>
        <td>${r.risk_score||'—'}</td><td><span class="badge">${_esc(r.status||'')}</span></td>
        <td><button class="btn xs" onclick="event.stopPropagation();_openRiskModal('${r.id}')">Edit</button>
            <button class="btn xs danger" onclick="event.stopPropagation();_deleteRisk('${r.id}','${_esc(r.title).replace(/'/g,"\\'")}')">Del</button></td>
      </tr>`).join('');
      const pages = Math.ceil(data.total/_RISK_LIMIT)||1; const page = Math.floor(_riskOffset/_RISK_LIMIT)+1;
      _q('#riskPager').innerHTML = `<button class="btn xs" ${_riskOffset===0?'disabled':''} onclick="_riskOffset=Math.max(0,_riskOffset-${_RISK_LIMIT});_loadRisks()">Prev</button>
        <span style="color:var(--text-muted);">Page ${page}/${pages}</span>
        <button class="btn xs" ${_riskOffset+_RISK_LIMIT>=data.total?'disabled':''} onclick="_riskOffset+=_RISK_LIMIT;_loadRisks()">Next</button>`;
    } catch(err) { tbody.innerHTML = `<tr><td colspan="6" style="color:var(--danger);text-align:center;padding:24px;">${_esc(err.message||'Error')}</td></tr>`; }
  }

  async function _riskOpenDetail(id) {
    _riskCurrentId = id;
    _q('#riskDetailDialog').hidden = false;
    _q('#riskDetailMeta').innerHTML = 'Loading...'; _q('#riskRevTbody').innerHTML = '';
    try {
      const r = await _api(`/risks/${id}`);
      _q('#riskDetailTitle').textContent = r.title;
      _q('#riskDetailMeta').innerHTML = `
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:13px;">
          <div><b>Category</b><br>${_esc(r.category||'')}</div><div><b>Level</b><br>${_esc(r.risk_level||'')}</div>
          <div><b>Score</b><br>${r.risk_score||'—'}</div><div><b>Status</b><br>${_esc(r.status||'')}</div>
          <div><b>Owner</b><br>${_esc(r.owner||'—')}</div><div><b>Mitigation</b><br>${_esc(r.mitigation_plan||'—').slice(0,80)}</div>
        </div>`;
      const tSel = _q('#riskTransSelect');
      const allowed = { identified:['assessed','accepted','closed'], assessed:['mitigating','accepted','closed'],
        mitigating:['resolved','accepted','closed'], accepted:['closed'], resolved:[], closed:[] };
      tSel.innerHTML = (allowed[r.status]||[]).map(s=>`<option value="${s}">${s}</option>`).join('') || '<option value="">No transitions</option>';
      const revData = await _api(`/risks/${id}/reviews`);
      const revs = revData.reviews || [];
      _q('#riskRevTbody').innerHTML = revs.length ? revs.map(rv => `<tr><td>${rv.likelihood}×${rv.impact}</td><td>${_esc(rv.notes||'')}</td><td style="font-size:11px;">${(rv.reviewed_at||'').slice(0,10)}</td></tr>`).join('') : '<tr><td colspan="3" style="color:var(--text-muted);">No reviews</td></tr>';
    } catch(err) { _q('#riskDetailMeta').innerHTML = `<p style="color:var(--danger);">${_esc(err.message||'Error')}</p>`; }
  }

  async function _openRiskModal(id) {
    _q('#riskFormDialog').hidden = false;
    _q('#riskFormTitle').textContent = id ? 'Edit Risk' : 'New Risk';
    _q('#riskForm').dataset.id = id || '';
    if (id) {
      try {
        const r = await _api(`/risks/${id}`);
        _q('#riskForm').querySelectorAll('[name]').forEach(el => { if (r[el.name] != null) el.value = r[el.name]; });
      } catch(_) {}
    } else { _q('#riskForm').reset(); }
  }

  async function _saveRisk() {
    const form = _q('#riskForm'); const id = form.dataset.id;
    const fd = new FormData(form);
    const body = Object.fromEntries(fd.entries());
    try {
      await _api(id ? `/risks/${id}` : '/risks', id ? 'PATCH' : 'POST', body);
      _q('#riskFormDialog').hidden = true; _loadRiskStats(); _loadRisks();
    } catch(err) { alert('Save failed: ' + (err.message||err)); }
  }

  async function _doRiskTransition() {
    const status = _q('#riskTransSelect').value; if (!status) return;
    try { await _api(`/risks/${_riskCurrentId}/transition`, 'POST', { status }); _riskOpenDetail(_riskCurrentId); _loadRiskStats(); _loadRisks(); }
    catch(err) { alert('Transition failed: ' + (err.message||err)); }
  }

  async function _addRiskReview() {
    const form = _q('#riskRevForm');
    const body = { likelihood: parseInt(form.querySelector('[name=likelihood]')?.value||3), impact: parseInt(form.querySelector('[name=impact]')?.value||3), notes: form.querySelector('[name=notes]')?.value||'' };
    try { await _api(`/risks/${_riskCurrentId}/reviews`, 'POST', body); _q('#riskRevDialog').hidden = true; _riskOpenDetail(_riskCurrentId); }
    catch(err) { alert('Failed: ' + (err.message||err)); }
  }

  async function _deleteRisk(id, name) {
    if (!confirm(`Delete risk "${name}"?`)) return;
    try { await _api(`/risks/${id}`, 'DELETE'); _loadRiskStats(); _loadRisks(); }
    catch(err) { alert('Delete failed: ' + (err.message||err)); }
  }

  // ── Certificates ─────────────────────────────────────────────────────────────
  let _certOffset = 0; const _CERT_LIMIT = 50; let _certCurrentId = null;

  function initCertificatesView() {
    _loadCertStats(); _loadCerts();
    _q('#certNewBtn').onclick = () => _openCertModal();
    _q('#certSearch').oninput = _debounce(() => { _certOffset = 0; _loadCerts(); });
    _q('#certStatusFilter').onchange = () => { _certOffset = 0; _loadCerts(); };
    _q('#certTypeFilter').onchange   = () => { _certOffset = 0; _loadCerts(); };
    _q('#certEnvFilter').onchange    = () => { _certOffset = 0; _loadCerts(); };
    _q('#certDetailClose').onclick   = () => { _q('#certDetailDialog').hidden = true; };
    _q('#certFormClose').onclick     = () => { _q('#certFormDialog').hidden = true; };
    _q('#certFormCancel').onclick    = () => { _q('#certFormDialog').hidden = true; };
    _q('#certForm').onsubmit         = e => { e.preventDefault(); _saveCert(); };
    _q('#certRenewClose').onclick    = () => { _q('#certRenewDialog').hidden = true; };
    _q('#certRenewCancel').onclick   = () => { _q('#certRenewDialog').hidden = true; };
    _q('#certRenewForm').onsubmit    = e => { e.preventDefault(); _addCertRenewal(); };
    _q('#certRenewBtn').onclick      = () => { if (_certCurrentId) { _q('#certRenewDialog').hidden = false; } };
    _q('#certTransBtn').onclick      = () => { if (_certCurrentId) _doCertTransition(); };
  }

  async function _loadCertStats() {
    try {
      const s = await _api('/certificates/stats');
      _q('#certStatTotal').textContent    = s.total || 0;
      _q('#certStatActive').textContent   = s.active || 0;
      _q('#certStatExpiring').textContent = s.expiring_soon || 0;
      _q('#certStatExpired').textContent  = s.expired || 0;
      _q('#certStatRevoked').textContent  = s.revoked || 0;
      _q('#certStatAutoRenew').textContent = s.auto_renew || 0;
    } catch(_) {}
  }

  async function _loadCerts() {
    const q = _q('#certSearch').value.trim();
    const status = _q('#certStatusFilter').value; const type = _q('#certTypeFilter').value; const env = _q('#certEnvFilter').value;
    const params = new URLSearchParams({ limit: _CERT_LIMIT, offset: _certOffset });
    if (q) params.set('q', q); if (status) params.set('status', status); if (type) params.set('cert_type', type); if (env) params.set('environment', env);
    const tbody = _q('#certTbody');
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-muted);padding:24px;">Loading...</td></tr>';
    try {
      const data = await _api(`/certificates?${params}`); const rows = data.certificates || [];
      if (!rows.length) { tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-muted);padding:24px;">No certificates found.</td></tr>'; return; }
      tbody.innerHTML = rows.map(r => `<tr style="cursor:pointer;" onclick="_certOpenDetail('${r.id}')">
        <td><strong>${_esc(r.common_name||r.name||'')}</strong></td><td>${_esc(r.cert_type||'')}</td>
        <td><span class="badge ${r.status==='expired'?'bad':r.status==='expiring_soon'?'warn':'ok'}">${_esc(r.status||'')}</span></td>
        <td style="font-size:11px;">${(r.expires_at||'').slice(0,10)||'—'}</td>
        <td>${_esc(r.environment||'')}</td>
        <td><button class="btn xs" onclick="event.stopPropagation();_openCertModal('${r.id}')">Edit</button>
            <button class="btn xs danger" onclick="event.stopPropagation();_deleteCert('${r.id}','${_esc((r.common_name||r.name||'')).replace(/'/g,"\\'")}')">Del</button></td>
      </tr>`).join('');
      const pages=Math.ceil(data.total/_CERT_LIMIT)||1; const page=Math.floor(_certOffset/_CERT_LIMIT)+1;
      _q('#certPager').innerHTML = `<button class="btn xs" ${_certOffset===0?'disabled':''} onclick="_certOffset=Math.max(0,_certOffset-${_CERT_LIMIT});_loadCerts()">Prev</button>
        <span style="color:var(--text-muted);">Page ${page}/${pages}</span>
        <button class="btn xs" ${_certOffset+_CERT_LIMIT>=data.total?'disabled':''} onclick="_certOffset+=_CERT_LIMIT;_loadCerts()">Next</button>`;
    } catch(err) { tbody.innerHTML = `<tr><td colspan="6" style="color:var(--danger);text-align:center;padding:24px;">${_esc(err.message||'Error')}</td></tr>`; }
  }

  async function _certOpenDetail(id) {
    _certCurrentId = id; _q('#certDetailDialog').hidden = false;
    _q('#certDetailMeta').innerHTML = 'Loading...'; _q('#certRenTbody').innerHTML = '';
    try {
      const c = await _api(`/certificates/${id}`);
      _q('#certDetailTitle').textContent = c.common_name || c.name || 'Certificate';
      _q('#certDetailMeta').innerHTML = `<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:13px;">
        <div><b>Type</b><br>${_esc(c.cert_type||'')}</div><div><b>Status</b><br>${_esc(c.status||'')}</div>
        <div><b>Issuer</b><br>${_esc(c.issuer||'—')}</div><div><b>Environment</b><br>${_esc(c.environment||'')}</div>
        <div><b>Issued</b><br>${(c.issued_at||'').slice(0,10)||'—'}</div><div><b>Expires</b><br>${(c.expires_at||'').slice(0,10)||'—'}</div>
        <div><b>Auto Renew</b><br>${c.auto_renew?'Yes':'No'}</div><div><b>Owner</b><br>${_esc(c.owner||'—')}</div>
      </div>`;
      const tSel = _q('#certTransSelect');
      const allowed = { active:['expired','revoked'], expired:['active'], expiring_soon:['active','revoked'], revoked:[] };
      tSel.innerHTML = (allowed[c.status]||[]).map(s=>`<option value="${s}">${s}</option>`).join('')||'<option value="">No transitions</option>';
      const renData = await _api(`/certificates/${id}/renewals`);
      const rens = renData.renewals || [];
      _q('#certRenTbody').innerHTML = rens.length ? rens.map(r=>`<tr><td>${_esc(r.renewed_by||'')}</td><td>${_esc(r.notes||'')}</td><td style="font-size:11px;">${(r.renewed_at||'').slice(0,10)}</td></tr>`).join('') : '<tr><td colspan="3" style="color:var(--text-muted);">No renewals</td></tr>';
    } catch(err) { _q('#certDetailMeta').innerHTML = `<p style="color:var(--danger);">${_esc(err.message||'Error')}</p>`; }
  }

  async function _openCertModal(id) {
    _q('#certFormDialog').hidden = false; _q('#certFormTitle').textContent = id?'Edit Certificate':'New Certificate';
    _q('#certForm').dataset.id = id||'';
    if (id) { try { const c=await _api(`/certificates/${id}`); _q('#certForm').querySelectorAll('[name]').forEach(el=>{if(c[el.name]!=null)el.value=c[el.name];}); } catch(_){} }
    else { _q('#certForm').reset(); }
  }

  async function _saveCert() {
    const form=_q('#certForm'); const id=form.dataset.id;
    const body=Object.fromEntries(new FormData(form).entries());
    try { await _api(id?`/certificates/${id}`:'/certificates', id?'PATCH':'POST', body); _q('#certFormDialog').hidden=true; _loadCertStats(); _loadCerts(); }
    catch(err) { alert('Save failed: '+(err.message||err)); }
  }

  async function _doCertTransition() {
    const status=_q('#certTransSelect').value; if(!status) return;
    try { await _api(`/certificates/${_certCurrentId}/transition`,'POST',{status}); _certOpenDetail(_certCurrentId); _loadCertStats(); _loadCerts(); }
    catch(err) { alert('Transition failed: '+(err.message||err)); }
  }

  async function _addCertRenewal() {
    const form=_q('#certRenewForm');
    const body={renewed_by:form.querySelector('[name=renewed_by]')?.value||'', notes:form.querySelector('[name=notes]')?.value||''};
    try { await _api(`/certificates/${_certCurrentId}/renew`,'POST',body); _q('#certRenewDialog').hidden=true; _certOpenDetail(_certCurrentId); }
    catch(err) { alert('Failed: '+(err.message||err)); }
  }

  async function _deleteCert(id, name) {
    if (!confirm(`Delete certificate "${name}"?`)) return;
    try { await _api(`/certificates/${id}`,'DELETE'); _loadCertStats(); _loadCerts(); }
    catch(err) { alert('Delete failed: '+(err.message||err)); }
  }

  // ── Config Management ────────────────────────────────────────────────────────
  let _cfgOffset=0; const _CFG_LIMIT=50; let _cfgCurrentId=null;

  function initConfigsView() {
    _loadCfgStats(); _loadConfigs();
    _q('#cfgNewBtn').onclick = () => _openCfgModal();
    _q('#cfgSearch').oninput = _debounce(() => { _cfgOffset=0; _loadConfigs(); });
    _q('#cfgEnvFilter').onchange    = () => { _cfgOffset=0; _loadConfigs(); };
    _q('#cfgTypeFilter').onchange   = () => { _cfgOffset=0; _loadConfigs(); };
    _q('#cfgStatusFilter').onchange = () => { _cfgOffset=0; _loadConfigs(); };
    _q('#cfgDetailClose').onclick   = () => { _q('#cfgDetailDialog').hidden=true; };
    _q('#cfgFormClose').onclick     = () => { _q('#cfgFormDialog').hidden=true; };
    _q('#cfgFormCancel').onclick    = () => { _q('#cfgFormDialog').hidden=true; };
    _q('#cfgForm').onsubmit         = e => { e.preventDefault(); _saveCfg(); };
    _q('#cfgEditClose').onclick     = () => { _q('#cfgEditDialog').hidden=true; };
    _q('#cfgEditCancel').onclick    = () => { _q('#cfgEditDialog').hidden=true; };
    _q('#cfgEditForm').onsubmit     = e => { e.preventDefault(); _promoteCfg(); };
    _q('#cfgTransBtn').onclick      = () => { if(_cfgCurrentId) _doCfgTransition(); };
    _q('#cfgPromoteBtn').onclick    = () => { if(_cfgCurrentId) { _q('#cfgEditDialog').hidden=false; } };
  }

  async function _loadCfgStats() {
    try {
      const s=await _api('/configs/stats');
      _q('#cfgStatTotal').textContent    = s.total||0;
      _q('#cfgStatActive').textContent   = s.active||0;
      _q('#cfgStatDepr').textContent     = s.deprecated||0;
      _q('#cfgStatVersions').textContent = s.total_versions||0;
    } catch(_) {}
  }

  async function _loadConfigs() {
    const q=_q('#cfgSearch').value.trim(); const env=_q('#cfgEnvFilter').value; const type=_q('#cfgTypeFilter').value; const status=_q('#cfgStatusFilter').value;
    const params=new URLSearchParams({limit:_CFG_LIMIT,offset:_cfgOffset});
    if(q) params.set('q',q); if(env) params.set('environment',env); if(type) params.set('config_type',type); if(status) params.set('status',status);
    const tbody=_q('#cfgTbody');
    tbody.innerHTML='<tr><td colspan="6" style="text-align:center;color:var(--text-muted);padding:24px;">Loading...</td></tr>';
    try {
      const data=await _api(`/configs?${params}`); const rows=data.configs||[];
      if(!rows.length){tbody.innerHTML='<tr><td colspan="6" style="text-align:center;color:var(--text-muted);padding:24px;">No configs found.</td></tr>';return;}
      tbody.innerHTML=rows.map(r=>`<tr style="cursor:pointer;" onclick="_cfgOpenDetail('${r.id}')">
        <td><strong>${_esc(r.name||'')}</strong></td><td>${_esc(r.config_type||'')}</td>
        <td>${_esc(r.environment||'')}</td><td><span class="badge">${_esc(r.status||'')}</span></td>
        <td>v${r.version||1}</td>
        <td><button class="btn xs" onclick="event.stopPropagation();_openCfgModal('${r.id}')">Edit</button>
            <button class="btn xs danger" onclick="event.stopPropagation();_deleteCfg('${r.id}','${_esc(r.name||'').replace(/'/g,"\\'")}')">Del</button></td>
      </tr>`).join('');
      const pages=Math.ceil(data.total/_CFG_LIMIT)||1; const page=Math.floor(_cfgOffset/_CFG_LIMIT)+1;
      _q('#cfgPager').innerHTML=`<button class="btn xs" ${_cfgOffset===0?'disabled':''} onclick="_cfgOffset=Math.max(0,_cfgOffset-${_CFG_LIMIT});_loadConfigs()">Prev</button>
        <span style="color:var(--text-muted);">Page ${page}/${pages}</span>
        <button class="btn xs" ${_cfgOffset+_CFG_LIMIT>=data.total?'disabled':''} onclick="_cfgOffset+=_CFG_LIMIT;_loadConfigs()">Next</button>`;
    } catch(err){tbody.innerHTML=`<tr><td colspan="6" style="color:var(--danger);text-align:center;padding:24px;">${_esc(err.message||'Error')}</td></tr>`;}
  }

  async function _cfgOpenDetail(id) {
    _cfgCurrentId=id; _q('#cfgDetailDialog').hidden=false;
    _q('#cfgDetailMeta').innerHTML='Loading...'; _q('#cfgVerTbody').innerHTML='';
    try {
      const c=await _api(`/configs/${id}`);
      _q('#cfgDetailTitle').textContent=c.name||'Config';
      _q('#cfgDetailMeta').innerHTML=`<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:13px;">
        <div><b>Type</b><br>${_esc(c.config_type||'')}</div><div><b>Status</b><br>${_esc(c.status||'')}</div>
        <div><b>Environment</b><br>${_esc(c.environment||'')}</div><div><b>Version</b><br>v${c.version||1}</div>
        <div><b>Owner</b><br>${_esc(c.owner||'—')}</div><div><b>Team</b><br>${_esc(c.team||'—')}</div>
      </div>${c.value?`<pre style="margin-top:8px;background:var(--surface);padding:8px;border-radius:4px;overflow:auto;max-height:150px;font-size:11px;">${_esc(c.value)}</pre>`:''}`;
      const allowed={draft:['active','deprecated'],active:['deprecated'],deprecated:[],archived:[]};
      _q('#cfgTransSelect').innerHTML=(allowed[c.status]||[]).map(s=>`<option value="${s}">${s}</option>`).join('')||'<option value="">No transitions</option>';
      const promoted_to=_q('#cfgPromoteSelect');
      promoted_to.innerHTML=['staging','production','dr'].map(e=>`<option value="${e}">${e}</option>`).join('');
      const verData=await _api(`/configs/${id}/versions`);
      const vers=verData.versions||[];
      _q('#cfgVerTbody').innerHTML=vers.length?vers.map(v=>`<tr><td>v${v.version}</td><td>${_esc(v.promoted_by||'')}</td><td style="font-size:11px;">${(v.promoted_at||'').slice(0,10)}</td></tr>`).join(''):'<tr><td colspan="3" style="color:var(--text-muted);">No versions</td></tr>';
    } catch(err){_q('#cfgDetailMeta').innerHTML=`<p style="color:var(--danger);">${_esc(err.message||'Error')}</p>`;}
  }

  async function _openCfgModal(id) {
    _q('#cfgFormDialog').hidden=false; _q('#cfgFormTitle').textContent=id?'Edit Config':'New Config'; _q('#cfgForm').dataset.id=id||'';
    if(id){try{const c=await _api(`/configs/${id}`);_q('#cfgForm').querySelectorAll('[name]').forEach(el=>{if(c[el.name]!=null)el.value=c[el.name];});}catch(_){}}
    else{_q('#cfgForm').reset();}
  }

  async function _saveCfg() {
    const form=_q('#cfgForm'); const id=form.dataset.id; const body=Object.fromEntries(new FormData(form).entries());
    try{await _api(id?`/configs/${id}`:'/configs',id?'PATCH':'POST',body);_q('#cfgFormDialog').hidden=true;_loadCfgStats();_loadConfigs();}
    catch(err){alert('Save failed: '+(err.message||err));}
  }

  async function _doCfgTransition() {
    const status=_q('#cfgTransSelect').value; if(!status) return;
    try{await _api(`/configs/${_cfgCurrentId}/transition`,'POST',{status});_cfgOpenDetail(_cfgCurrentId);_loadCfgStats();_loadConfigs();}
    catch(err){alert('Transition failed: '+(err.message||err));}
  }

  async function _promoteCfg() {
    const env=_q('#cfgPromoteSelect').value; const by=_q('#cfgPromoteBy').value;
    try{await _api(`/configs/${_cfgCurrentId}/promote`,'POST',{target_environment:env,promoted_by:by});_q('#cfgEditDialog').hidden=true;_cfgOpenDetail(_cfgCurrentId);}
    catch(err){alert('Promote failed: '+(err.message||err));}
  }

  async function _deleteCfg(id,name) {
    if(!confirm(`Delete config "${name}"?`)) return;
    try{await _api(`/configs/${id}`,'DELETE');_loadCfgStats();_loadConfigs();}
    catch(err){alert('Delete failed: '+(err.message||err));}
  }

  // ── License Management ───────────────────────────────────────────────────────
  let _licOffset=0; const _LIC_LIMIT=50; let _licCurrentId=null;

  function initLicensesView() {
    _loadLicStats(); _loadLicenses();
    _q('#licNewBtn').onclick = () => _openLicModal();
    _q('#licSearch').oninput = _debounce(() => { _licOffset=0; _loadLicenses(); });
    _q('#licStatusFilter').onchange = () => { _licOffset=0; _loadLicenses(); };
    _q('#licTypeFilter').onchange   = () => { _licOffset=0; _loadLicenses(); };
    _q('#licDetailClose').onclick   = () => { _q('#licDetailDialog').hidden=true; };
    _q('#licFormClose').onclick     = () => { _q('#licFormDialog').hidden=true; };
    _q('#licFormCancel').onclick    = () => { _q('#licFormDialog').hidden=true; };
    _q('#licForm').onsubmit         = e => { e.preventDefault(); _saveLic(); };
    _q('#licAsnClose').onclick      = () => { _q('#licAsnDialog').hidden=true; };
    _q('#licAsnCancel').onclick     = () => { _q('#licAsnDialog').hidden=true; };
    _q('#licAsnForm').onsubmit      = e => { e.preventDefault(); _addLicAsn(); };
    _q('#licRenClose').onclick      = () => { _q('#licRenDialog').hidden=true; };
    _q('#licRenCancel').onclick     = () => { _q('#licRenDialog').hidden=true; };
    _q('#licRenForm').onsubmit      = e => { e.preventDefault(); _addLicRen(); };
    _q('#licAddAsnBtn').onclick     = () => { if(_licCurrentId){_q('#licAsnDialog').hidden=false;_q('#licAsnForm').reset();} };
    _q('#licAddRenBtn').onclick     = () => { if(_licCurrentId){_q('#licRenDialog').hidden=false;_q('#licRenForm').reset();} };
    _q('#licTransBtn').onclick      = () => { if(_licCurrentId) _doLicTransition(); };
  }

  async function _loadLicStats() {
    try {
      const s=await _api('/licenses/stats');
      _q('#licStatTotal').textContent   = s.total||0; _q('#licStatActive').textContent  = s.active||0;
      _q('#licStatExpiring').textContent= s.expiring_soon||0; _q('#licStatCost').textContent    = s.total_cost!=null?s.total_cost.toFixed(2):'—';
      _q('#licStatSeats').textContent   = s.total_seats||0;
    } catch(_) {}
  }

  async function _loadLicenses() {
    const q=_q('#licSearch').value.trim(); const status=_q('#licStatusFilter').value; const type=_q('#licTypeFilter').value;
    const params=new URLSearchParams({limit:_LIC_LIMIT,offset:_licOffset});
    if(q) params.set('q',q); if(status) params.set('status',status); if(type) params.set('license_type',type);
    const tbody=_q('#licTbody');
    tbody.innerHTML='<tr><td colspan="6" style="text-align:center;color:var(--text-muted);padding:24px;">Loading...</td></tr>';
    try {
      const data=await _api(`/licenses?${params}`); const rows=data.licenses||[];
      if(!rows.length){tbody.innerHTML='<tr><td colspan="6" style="text-align:center;color:var(--text-muted);padding:24px;">No licenses found.</td></tr>';return;}
      tbody.innerHTML=rows.map(r=>`<tr style="cursor:pointer;" onclick="_licOpenDetail('${r.id}')">
        <td><strong>${_esc(r.name||'')}</strong></td><td>${_esc(r.license_type||'')}</td>
        <td><span class="badge ${r.status==='expired'?'bad':r.status==='expiring_soon'?'warn':'ok'}">${_esc(r.status||'')}</span></td>
        <td>${r.total_seats||'—'}</td><td style="font-size:11px;">${(r.expires_at||'').slice(0,10)||'—'}</td>
        <td><button class="btn xs" onclick="event.stopPropagation();_openLicModal('${r.id}')">Edit</button>
            <button class="btn xs danger" onclick="event.stopPropagation();_deleteLic('${r.id}','${_esc(r.name||'').replace(/'/g,"\\'")}')">Del</button></td>
      </tr>`).join('');
      const pages=Math.ceil(data.total/_LIC_LIMIT)||1; const page=Math.floor(_licOffset/_LIC_LIMIT)+1;
      _q('#licPager').innerHTML=`<button class="btn xs" ${_licOffset===0?'disabled':''} onclick="_licOffset=Math.max(0,_licOffset-${_LIC_LIMIT});_loadLicenses()">Prev</button>
        <span style="color:var(--text-muted);">Page ${page}/${pages}</span>
        <button class="btn xs" ${_licOffset+_LIC_LIMIT>=data.total?'disabled':''} onclick="_licOffset+=_LIC_LIMIT;_loadLicenses()">Next</button>`;
    } catch(err){tbody.innerHTML=`<tr><td colspan="6" style="color:var(--danger);text-align:center;padding:24px;">${_esc(err.message||'Error')}</td></tr>`;}
  }

  async function _licOpenDetail(id) {
    _licCurrentId=id; _q('#licDetailDialog').hidden=false;
    _q('#licDetailMeta').innerHTML='Loading...'; _q('#licAsnTbody').innerHTML=''; _q('#licRenTbody').innerHTML='';
    try {
      const l=await _api(`/licenses/${id}`);
      _q('#licDetailTitle').textContent=l.name||'License';
      _q('#licDetailMeta').innerHTML=`<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:13px;">
        <div><b>Type</b><br>${_esc(l.license_type||'')}</div><div><b>Status</b><br>${_esc(l.status||'')}</div>
        <div><b>Seats</b><br>${l.total_seats||'—'} (used: ${l.used_seats||0})</div><div><b>Cost/yr</b><br>${l.cost_per_year!=null?l.cost_per_year:'—'}</div>
        <div><b>Vendor</b><br>${_esc(l.vendor||'—')}</div><div><b>Expires</b><br>${(l.expires_at||'').slice(0,10)||'—'}</div>
      </div>`;
      const allowed={active:['expired','suspended'],expired:['active'],suspended:['active'],cancelled:[]};
      _q('#licTransSelect').innerHTML=(allowed[l.status]||[]).map(s=>`<option value="${s}">${s}</option>`).join('')||'<option value="">No transitions</option>';
      const [asnData,renData]=await Promise.all([_api(`/licenses/${id}/assignments`),_api(`/licenses/${id}/renewals`)]);
      const asns=asnData.assignments||[];
      _q('#licAsnTbody').innerHTML=asns.length?asns.map(a=>`<tr><td>${_esc(a.user_email||'')}</td><td>${_esc(a.role||'')}</td>
        <td><button class="btn xs danger" onclick="_deleteLicAsn('${id}','${a.id}')">Remove</button></td></tr>`).join(''):'<tr><td colspan="3" style="color:var(--text-muted);">No assignments</td></tr>';
      const rens=renData.renewals||[];
      _q('#licRenTbody').innerHTML=rens.length?rens.map(r=>`<tr><td>${_esc(r.renewed_by||'')}</td><td>${_esc(r.notes||'')}</td><td style="font-size:11px;">${(r.renewed_at||'').slice(0,10)}</td></tr>`).join(''):'<tr><td colspan="3" style="color:var(--text-muted);">No renewals</td></tr>';
    } catch(err){_q('#licDetailMeta').innerHTML=`<p style="color:var(--danger);">${_esc(err.message||'Error')}</p>`;}
  }

  async function _openLicModal(id) {
    _q('#licFormDialog').hidden=false; _q('#licFormTitle').textContent=id?'Edit License':'New License'; _q('#licForm').dataset.id=id||'';
    if(id){try{const l=await _api(`/licenses/${id}`);_q('#licForm').querySelectorAll('[name]').forEach(el=>{if(l[el.name]!=null)el.value=l[el.name];});}catch(_){}}
    else{_q('#licForm').reset();}
  }

  async function _saveLic() {
    const form=_q('#licForm'); const id=form.dataset.id; const body=Object.fromEntries(new FormData(form).entries());
    try{await _api(id?`/licenses/${id}`:'/licenses',id?'PATCH':'POST',body);_q('#licFormDialog').hidden=true;_loadLicStats();_loadLicenses();}
    catch(err){alert('Save failed: '+(err.message||err));}
  }

  async function _doLicTransition() {
    const status=_q('#licTransSelect').value; if(!status) return;
    try{await _api(`/licenses/${_licCurrentId}/transition`,'POST',{status});_licOpenDetail(_licCurrentId);_loadLicStats();_loadLicenses();}
    catch(err){alert('Transition failed: '+(err.message||err));}
  }

  async function _addLicAsn() {
    const form=_q('#licAsnForm'); const body={user_email:form.querySelector('[name=user_email]')?.value||'',role:form.querySelector('[name=role]')?.value||''};
    try{await _api(`/licenses/${_licCurrentId}/assignments`,'POST',body);_q('#licAsnDialog').hidden=true;_licOpenDetail(_licCurrentId);}
    catch(err){alert('Failed: '+(err.message||err));}
  }

  async function _deleteLicAsn(licId,asnId) {
    if(!confirm('Remove assignment?')) return;
    try{await _api(`/licenses/${licId}/assignments/${asnId}`,'DELETE');_licOpenDetail(licId);}
    catch(err){alert('Failed: '+(err.message||err));}
  }

  async function _addLicRen() {
    const form=_q('#licRenForm'); const body={renewed_by:form.querySelector('[name=renewed_by]')?.value||'',notes:form.querySelector('[name=notes]')?.value||''};
    try{await _api(`/licenses/${_licCurrentId}/renewals`,'POST',body);_q('#licRenDialog').hidden=true;_licOpenDetail(_licCurrentId);}
    catch(err){alert('Failed: '+(err.message||err));}
  }

  async function _deleteLic(id,name) {
    if(!confirm(`Delete license "${name}"?`)) return;
    try{await _api(`/licenses/${id}`,'DELETE');_loadLicStats();_loadLicenses();}
    catch(err){alert('Delete failed: '+(err.message||err));}
  }

  // ── Budget Tracking ──────────────────────────────────────────────────────────
  let _budOffset=0; const _BUD_LIMIT=50; let _budCurrentId=null;

  function initBudgetsView() {
    _loadBudStats(); _loadBudgets();
    _q('#budNewBtn').onclick = () => _openBudModal();
    _q('#budSearch').oninput = _debounce(() => { _budOffset=0; _loadBudgets(); });
    _q('#budStatusFilter').onchange = () => { _budOffset=0; _loadBudgets(); };
    _q('#budCatFilter').onchange    = () => { _budOffset=0; _loadBudgets(); };
    _q('#budDetailClose').onclick   = () => { _q('#budDetailDialog').hidden=true; };
    _q('#budFormClose').onclick     = () => { _q('#budFormDialog').hidden=true; };
    _q('#budFormCancel').onclick    = () => { _q('#budFormDialog').hidden=true; };
    _q('#budForm').onsubmit         = e => { e.preventDefault(); _saveBud(); };
    _q('#budEntryClose').onclick    = () => { _q('#budEntryDialog').hidden=true; };
    _q('#budEntryCancel').onclick   = () => { _q('#budEntryDialog').hidden=true; };
    _q('#budEntryForm').onsubmit    = e => { e.preventDefault(); _addBudEntry(); };
    _q('#budAddEntryBtn').onclick   = () => { if(_budCurrentId){_q('#budEntryDialog').hidden=false;_q('#budEntryForm').reset();} };
    _q('#budTransBtn').onclick      = () => { if(_budCurrentId) _doBudTransition(); };
  }

  async function _loadBudStats() {
    try {
      const s=await _api('/budgets/stats');
      _q('#budStatTotal').textContent  = s.total||0; _q('#budStatActive').textContent = s.active||0;
      _q('#budStatAlloc').textContent  = s.total_allocated!=null?s.total_allocated.toFixed(2):'—';
      _q('#budStatSpent').textContent  = s.total_spent!=null?s.total_spent.toFixed(2):'—';
      _q('#budStatOver').textContent   = s.over_budget||0;
    } catch(_) {}
  }

  async function _loadBudgets() {
    const q=_q('#budSearch').value.trim(); const status=_q('#budStatusFilter').value; const cat=_q('#budCatFilter').value;
    const params=new URLSearchParams({limit:_BUD_LIMIT,offset:_budOffset});
    if(q) params.set('q',q); if(status) params.set('status',status); if(cat) params.set('category',cat);
    const tbody=_q('#budTbody');
    tbody.innerHTML='<tr><td colspan="6" style="text-align:center;color:var(--text-muted);padding:24px;">Loading...</td></tr>';
    try {
      const data=await _api(`/budgets?${params}`); const rows=data.budgets||[];
      if(!rows.length){tbody.innerHTML='<tr><td colspan="6" style="text-align:center;color:var(--text-muted);padding:24px;">No budgets found.</td></tr>';return;}
      tbody.innerHTML=rows.map(r=>`<tr style="cursor:pointer;" onclick="_budOpenDetail('${r.id}')">
        <td><strong>${_esc(r.name||'')}</strong></td><td>${_esc(r.category||'')}</td>
        <td><span class="badge ${r.is_over_budget?'bad':'ok'}">${_esc(r.status||'')}</span></td>
        <td>${r.amount!=null?r.amount:''} ${_esc(r.currency||'')}</td>
        <td>${r.total_spent!=null?r.total_spent.toFixed(2):'—'}</td>
        <td><button class="btn xs" onclick="event.stopPropagation();_openBudModal('${r.id}')">Edit</button>
            <button class="btn xs danger" onclick="event.stopPropagation();_deleteBud('${r.id}','${_esc(r.name||'').replace(/'/g,"\\'")}')">Del</button></td>
      </tr>`).join('');
      const pages=Math.ceil(data.total/_BUD_LIMIT)||1; const page=Math.floor(_budOffset/_BUD_LIMIT)+1;
      _q('#budPager').innerHTML=`<button class="btn xs" ${_budOffset===0?'disabled':''} onclick="_budOffset=Math.max(0,_budOffset-${_BUD_LIMIT});_loadBudgets()">Prev</button>
        <span style="color:var(--text-muted);">Page ${page}/${pages}</span>
        <button class="btn xs" ${_budOffset+_BUD_LIMIT>=data.total?'disabled':''} onclick="_budOffset+=_BUD_LIMIT;_loadBudgets()">Next</button>`;
    } catch(err){tbody.innerHTML=`<tr><td colspan="6" style="color:var(--danger);text-align:center;padding:24px;">${_esc(err.message||'Error')}</td></tr>`;}
  }

  async function _budOpenDetail(id) {
    _budCurrentId=id; _q('#budDetailDialog').hidden=false;
    _q('#budDetailMeta').innerHTML='Loading...'; _q('#budEntryTbody').innerHTML='';
    try {
      const b=await _api(`/budgets/${id}`);
      _q('#budDetailTitle').textContent=b.name||'Budget';
      const pct=b.amount>0?Math.min(100,Math.round((b.total_spent||0)/b.amount*100)):0;
      _q('#budDetailMeta').innerHTML=`<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:13px;">
        <div><b>Category</b><br>${_esc(b.category||'')}</div><div><b>Status</b><br>${_esc(b.status||'')}</div>
        <div><b>Allocated</b><br>${b.amount} ${_esc(b.currency||'')}</div><div><b>Spent</b><br>${(b.total_spent||0).toFixed(2)} (${pct}%)</div>
        <div><b>Period</b><br>${(b.period_start||'').slice(0,10)||'—'} → ${(b.period_end||'').slice(0,10)||'—'}</div>
        <div><b>Owner</b><br>${_esc(b.owner||'—')}</div>
      </div>`;
      const allowed={draft:['active','cancelled'],active:['closed','cancelled'],closed:[],cancelled:[]};
      _q('#budTransSelect').innerHTML=(allowed[b.status]||[]).map(s=>`<option value="${s}">${s}</option>`).join('')||'<option value="">No transitions</option>';
      const entData=await _api(`/budgets/${id}/entries`); const ents=entData.entries||[];
      _q('#budEntryTbody').innerHTML=ents.length?ents.map(e=>`<tr><td>${_esc(e.description||'')}</td><td>${e.amount} ${_esc(e.currency||'')}</td>
        <td>${_esc(e.category||'')}</td><td style="font-size:11px;">${(e.date||'').slice(0,10)}</td>
        <td><button class="btn xs danger" onclick="_deleteBudEntry('${id}','${e.id}')">Del</button></td></tr>`).join(''):'<tr><td colspan="5" style="color:var(--text-muted);">No entries</td></tr>';
    } catch(err){_q('#budDetailMeta').innerHTML=`<p style="color:var(--danger);">${_esc(err.message||'Error')}</p>`;}
  }

  async function _openBudModal(id) {
    _q('#budFormDialog').hidden=false; _q('#budFormTitle').textContent=id?'Edit Budget':'New Budget'; _q('#budForm').dataset.id=id||'';
    if(id){try{const b=await _api(`/budgets/${id}`);_q('#budForm').querySelectorAll('[name]').forEach(el=>{if(b[el.name]!=null)el.value=b[el.name];});}catch(_){}}
    else{_q('#budForm').reset();}
  }

  async function _saveBud() {
    const form=_q('#budForm'); const id=form.dataset.id; const body=Object.fromEntries(new FormData(form).entries());
    try{await _api(id?`/budgets/${id}`:'/budgets',id?'PATCH':'POST',body);_q('#budFormDialog').hidden=true;_loadBudStats();_loadBudgets();}
    catch(err){alert('Save failed: '+(err.message||err));}
  }

  async function _doBudTransition() {
    const status=_q('#budTransSelect').value; if(!status) return;
    try{await _api(`/budgets/${_budCurrentId}/transition`,'POST',{status});_budOpenDetail(_budCurrentId);_loadBudStats();_loadBudgets();}
    catch(err){alert('Transition failed: '+(err.message||err));}
  }

  async function _addBudEntry() {
    const form=_q('#budEntryForm'); const body=Object.fromEntries(new FormData(form).entries());
    try{await _api(`/budgets/${_budCurrentId}/entries`,'POST',body);_q('#budEntryDialog').hidden=true;_budOpenDetail(_budCurrentId);}
    catch(err){alert('Failed: '+(err.message||err));}
  }

  async function _deleteBudEntry(budId,entryId) {
    if(!confirm('Delete cost entry?')) return;
    try{await _api(`/budgets/${budId}/entries/${entryId}`,'DELETE');_budOpenDetail(budId);}
    catch(err){alert('Failed: '+(err.message||err));}
  }

  async function _deleteBud(id,name) {
    if(!confirm(`Delete budget "${name}"?`)) return;
    try{await _api(`/budgets/${id}`,'DELETE');_loadBudStats();_loadBudgets();}
    catch(err){alert('Delete failed: '+(err.message||err));}
  }

  // ── Feature Flags ────────────────────────────────────────────────────────────
  let _flagOffset=0; const _FLAG_LIMIT=50; let _flagCurrentId=null;

  function initFlagsView() {
    _loadFlagStats(); _loadFlags();
    _q('#flag-add-btn').onclick  = () => _openFlagModal();
    _q('#flag-search').oninput   = _debounce(() => { _flagOffset=0; _loadFlags(); });
    _q('#flag-filter-status').onchange = () => { _flagOffset=0; _loadFlags(); };
    _q('#flag-detail-close').onclick   = () => { _q('#flag-detail').hidden=true; };
    _q('#flag-modal-close').onclick    = () => { _q('#flag-modal').hidden=true; };
    _q('#flag-modal-cancel').onclick   = () => { _q('#flag-modal').hidden=true; };
    _q('#flag-modal-save').onclick     = () => _saveFlag();
    _q('#flag-transition-modal-close').onclick  = () => { _q('#flag-transition-modal').hidden=true; };
    _q('#flag-transition-cancel').onclick       = () => { _q('#flag-transition-modal').hidden=true; };
    _q('#flag-transition-submit').onclick       = () => _doFlagTransition();
    _q('#flag-edit-btn').onclick       = () => { if(_flagCurrentId) _openFlagModal(_flagCurrentId); };
    _q('#flag-transition-btn').onclick = () => { if(_flagCurrentId) _openFlagTransitionModal(); };
    _q('#flag-delete-btn').onclick     = () => { if(_flagCurrentId) _deleteFlagCurrent(); };
    _q('#flag-env-save-btn').onclick   = () => { if(_flagCurrentId) _saveFlagEnv(); };
    _q('#flag-evt-add-btn').onclick    = () => { if(_flagCurrentId) _addFlagEvt(); };
  }

  async function _loadFlagStats() {
    try {
      const s=await _api('/flags/stats');
      _q('#flag-stats-row').innerHTML=[['Total',s.total],['Active',s.active],['Killed',s.killed],['Rollout',s.rollout]].map(([l,v])=>
        `<div class="report-card" style="padding:8px 12px;min-width:90px;"><span>${l}</span><strong>${v||0}</strong></div>`).join('');
    } catch(_) {}
  }

  async function _loadFlags() {
    const q=_q('#flag-search').value.trim(); const status=_q('#flag-filter-status').value;
    const params=new URLSearchParams({limit:_FLAG_LIMIT,offset:_flagOffset});
    if(q) params.set('q',q); if(status) params.set('status',status);
    const tbody=_q('#flag-tbody');
    tbody.innerHTML='<tr><td colspan="5" style="text-align:center;color:var(--text-muted);padding:24px;">Loading...</td></tr>';
    try {
      const data=await _api(`/flags?${params}`); const rows=data.flags||[];
      if(!rows.length){tbody.innerHTML='<tr><td colspan="5" style="text-align:center;color:var(--text-muted);padding:24px;">No flags found.</td></tr>';return;}
      tbody.innerHTML=rows.map(r=>`<tr style="cursor:pointer;" onclick="_flagOpenDetail('${r.id}')">
        <td><strong>${_esc(r.key||r.name||'')}</strong></td><td>${_esc(r.flag_type||'')}</td>
        <td><span class="badge">${_esc(r.status||'')}</span></td><td>${_esc(r.owner||'')}</td>
        <td><button class="btn xs danger" onclick="event.stopPropagation();_deleteFlagById('${r.id}','${_esc(r.key||r.name||'').replace(/'/g,"\\'")}')">Del</button></td>
      </tr>`).join('');
      const pages=Math.ceil(data.total/_FLAG_LIMIT)||1; const page=Math.floor(_flagOffset/_FLAG_LIMIT)+1;
      _q('#flag-pagination').innerHTML=`<button class="btn xs" ${_flagOffset===0?'disabled':''} onclick="_flagOffset=Math.max(0,_flagOffset-${_FLAG_LIMIT});_loadFlags()">Prev</button>
        <span style="color:var(--text-muted);">Page ${page}/${pages}</span>
        <button class="btn xs" ${_flagOffset+_FLAG_LIMIT>=data.total?'disabled':''} onclick="_flagOffset+=_FLAG_LIMIT;_loadFlags()">Next</button>`;
    } catch(err){tbody.innerHTML=`<tr><td colspan="5" style="color:var(--danger);text-align:center;padding:24px;">${_esc(err.message||'Error')}</td></tr>`;}
  }

  async function _flagOpenDetail(id) {
    _flagCurrentId=id; _q('#flag-detail').hidden=false;
    _q('#flag-detail-meta').innerHTML='Loading...'; _q('#flag-env-list').innerHTML=''; _q('#flag-evt-list').innerHTML='';
    try {
      const f=await _api(`/flags/${id}`);
      _q('#flag-detail-title').textContent=f.key||f.name||'Flag';
      _q('#flag-detail-meta').innerHTML=`<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:13px;">
        <div><b>Type</b><br>${_esc(f.flag_type||'')}</div><div><b>Status</b><br>${_esc(f.status||'')}</div>
        <div><b>Owner</b><br>${_esc(f.owner||'—')}</div><div><b>Tags</b><br>${_esc(f.tags||'—')}</div>
      </div>${f.description?`<p style="margin-top:8px;font-size:13px;">${_esc(f.description)}</p>`:''}`;
      const envData=await _api(`/flags/${id}/environments`); const envs=envData.environments||[];
      _q('#flag-env-list').innerHTML=envs.length?envs.map(e=>`<div style="display:flex;gap:8px;align-items:center;font-size:12px;">
        <strong style="min-width:80px;">${_esc(e.environment)}</strong>
        <span class="badge ${e.enabled?'ok':'bad'}">${e.enabled?'on':'off'}</span>
        <span style="color:var(--text-muted);">rollout: ${e.rollout_percentage||0}%</span></div>`).join(''):'<span style="color:var(--text-muted);font-size:12px;">No environments</span>';
      const evtData=await _api(`/flags/${id}/events`); const evts=evtData.events||[];
      _q('#flag-evt-list').innerHTML=evts.slice(0,10).map(e=>`<div style="font-size:12px;border-bottom:1px solid var(--border);padding:4px 0;">
        <span style="color:var(--text-muted);">${(e.created_at||'').slice(0,10)}</span> ${_esc(e.note||'')} <em style="color:var(--text-muted);">${_esc(e.author||'')}</em></div>`).join('')||'<span style="color:var(--text-muted);font-size:12px;">No events</span>';
    } catch(err){_q('#flag-detail-meta').innerHTML=`<p style="color:var(--danger);">${_esc(err.message||'Error')}</p>`;}
  }

  async function _openFlagModal(id) {
    _q('#flag-modal').hidden=false; _q('#flag-modal-title').textContent=id?'Edit Flag':'New Flag'; _q('#flag-modal').dataset.id=id||'';
    if(id){try{const f=await _api(`/flags/${id}`);['flag-f-name','flag-f-desc','flag-f-owner','flag-f-tags'].forEach(elId=>{const n=elId.replace('flag-f-','');const el=_q('#'+elId);if(el&&f[n]!=null)el.value=f[n];});}catch(_){}}
    else{['flag-f-name','flag-f-desc','flag-f-owner','flag-f-tags'].forEach(id=>{ const el=_q('#'+id); if(el) el.value=''; });}
  }

  async function _saveFlag() {
    const id=_q('#flag-modal').dataset.id;
    const body={name:_q('#flag-f-name').value,description:_q('#flag-f-desc').value,owner:_q('#flag-f-owner').value,tags:_q('#flag-f-tags').value};
    try{await _api(id?`/flags/${id}`:'/flags',id?'PATCH':'POST',body);_q('#flag-modal').hidden=true;_loadFlagStats();_loadFlags();}
    catch(err){alert('Save failed: '+(err.message||err));}
  }

  async function _openFlagTransitionModal() {
    try{const f=await _api(`/flags/${_flagCurrentId}`);
      const allowed={draft:['active','killed'],active:['paused','killed'],paused:['active','killed'],killed:[],archived:[]};
      _q('#flag-transition-status').innerHTML=(allowed[f.status]||[]).map(s=>`<option value="${s}">${s}</option>`).join('')||'<option value="">No transitions</option>';
      _q('#flag-transition-modal').hidden=false;}catch(_){}
  }

  async function _doFlagTransition() {
    const status=_q('#flag-transition-status').value; if(!status) return;
    const author=_q('#flag-transition-author').value;
    try{await _api(`/flags/${_flagCurrentId}/transition`,'POST',{status,author});_q('#flag-transition-modal').hidden=true;_flagOpenDetail(_flagCurrentId);_loadFlagStats();_loadFlags();}
    catch(err){alert('Transition failed: '+(err.message||err));}
  }

  async function _saveFlagEnv() {
    const env=_q('#flag-env-name').value.trim(); if(!env) return;
    const enabled=_q('#flag-env-enabled').value==='true'; const pct=parseInt(_q('#flag-env-rollout').value)||0;
    try{await _api(`/flags/${_flagCurrentId}/environments`,'POST',{environment:env,enabled,rollout_percentage:pct});_flagOpenDetail(_flagCurrentId);}
    catch(err){alert('Failed: '+(err.message||err));}
  }

  async function _addFlagEvt() {
    const note=_q('#flag-evt-note').value.trim(); const author=_q('#flag-evt-author').value.trim();
    if(!note) return;
    try{await _api(`/flags/${_flagCurrentId}/events`,'POST',{note,author});_q('#flag-evt-note').value='';_flagOpenDetail(_flagCurrentId);}
    catch(err){alert('Failed: '+(err.message||err));}
  }

  async function _deleteFlagCurrent() {
    const id=_flagCurrentId; if(!id||!confirm('Delete this flag?')) return;
    try{await _api(`/flags/${id}`,'DELETE');_q('#flag-detail').hidden=true;_flagCurrentId=null;_loadFlagStats();_loadFlags();}
    catch(err){alert('Delete failed: '+(err.message||err));}
  }

  async function _deleteFlagById(id,name) {
    if(!confirm(`Delete flag "${name}"?`)) return;
    try{await _api(`/flags/${id}`,'DELETE');_loadFlagStats();_loadFlags();}
    catch(err){alert('Delete failed: '+(err.message||err));}
  }

  // ── Vendor Management ────────────────────────────────────────────────────────
  let _venOffset=0; const _VEN_LIMIT=50; let _venCurrentId=null;

  function initVendorsView() {
    _loadVenStats(); _loadVendors();
    _q('#ven-add-btn').onclick  = () => _openVenModal();
    _q('#ven-search').oninput   = _debounce(() => { _venOffset=0; _loadVendors(); });
    _q('#ven-filter-status').onchange   = () => { _venOffset=0; _loadVendors(); };
    _q('#ven-filter-category').onchange = () => { _venOffset=0; _loadVendors(); };
    _q('#ven-detail-close').onclick     = () => { _q('#ven-detail').hidden=true; };
    _q('#ven-modal-close').onclick      = () => { _q('#ven-modal').hidden=true; };
    _q('#ven-modal-cancel').onclick     = () => { _q('#ven-modal').hidden=true; };
    _q('#ven-modal-save').onclick       = () => _saveVen();
    _q('#ven-transition-modal-close').onclick  = () => { _q('#ven-transition-modal').hidden=true; };
    _q('#ven-transition-cancel').onclick       = () => { _q('#ven-transition-modal').hidden=true; };
    _q('#ven-transition-submit').onclick       = () => _doVenTransition();
    _q('#ven-edit-btn').onclick       = () => { if(_venCurrentId) _openVenModal(_venCurrentId); };
    _q('#ven-transition-btn').onclick = () => { if(_venCurrentId) _openVenTransModal(); };
    _q('#ven-delete-btn').onclick     = () => { if(_venCurrentId) _deleteVenCurrent(); };
    _q('#ven-con-add-btn').onclick    = () => { if(_venCurrentId) _addVenContact(); };
    _q('#ven-rev-add-btn').onclick    = () => { if(_venCurrentId) _addVenReview(); };
  }

  async function _loadVenStats() {
    try {
      const s=await _api('/vendors/stats');
      _q('#ven-stats-row').innerHTML=[['Total',s.total],['Active',s.active],['Expiring',s.expiring_soon||0],['Inactive',s.inactive||0]].map(([l,v])=>
        `<div class="report-card" style="padding:8px 12px;min-width:90px;"><span>${l}</span><strong>${v||0}</strong></div>`).join('');
    } catch(_) {}
  }

  async function _loadVendors() {
    const q=_q('#ven-search').value.trim(); const status=_q('#ven-filter-status').value; const cat=_q('#ven-filter-category').value;
    const params=new URLSearchParams({limit:_VEN_LIMIT,offset:_venOffset});
    if(q) params.set('q',q); if(status) params.set('status',status); if(cat) params.set('category',cat);
    const tbody=_q('#ven-tbody');
    tbody.innerHTML='<tr><td colspan="5" style="text-align:center;color:var(--text-muted);padding:24px;">Loading...</td></tr>';
    try {
      const data=await _api(`/vendors?${params}`); const rows=data.vendors||[];
      if(!rows.length){tbody.innerHTML='<tr><td colspan="5" style="text-align:center;color:var(--text-muted);padding:24px;">No vendors found.</td></tr>';return;}
      tbody.innerHTML=rows.map(r=>`<tr style="cursor:pointer;" onclick="_venOpenDetail('${r.id}')">
        <td><strong>${_esc(r.name||'')}</strong></td><td>${_esc(r.category||'')}</td>
        <td><span class="badge">${_esc(r.status||'')}</span></td>
        <td style="font-size:11px;">${(r.contract_end||'').slice(0,10)||'—'}</td>
        <td><button class="btn xs danger" onclick="event.stopPropagation();_deleteVenById('${r.id}','${_esc(r.name||'').replace(/'/g,"\\'")}')">Del</button></td>
      </tr>`).join('');
      const pages=Math.ceil(data.total/_VEN_LIMIT)||1; const page=Math.floor(_venOffset/_VEN_LIMIT)+1;
      _q('#ven-pagination').innerHTML=`<button class="btn xs" ${_venOffset===0?'disabled':''} onclick="_venOffset=Math.max(0,_venOffset-${_VEN_LIMIT});_loadVendors()">Prev</button>
        <span style="color:var(--text-muted);">Page ${page}/${pages}</span>
        <button class="btn xs" ${_venOffset+_VEN_LIMIT>=data.total?'disabled':''} onclick="_venOffset+=_VEN_LIMIT;_loadVendors()">Next</button>`;
    } catch(err){tbody.innerHTML=`<tr><td colspan="5" style="color:var(--danger);text-align:center;padding:24px;">${_esc(err.message||'Error')}</td></tr>`;}
  }

  async function _venOpenDetail(id) {
    _venCurrentId=id; _q('#ven-detail').hidden=false;
    _q('#ven-detail-body').innerHTML='Loading...'; _q('#ven-con-list').innerHTML=''; _q('#ven-rev-list').innerHTML='';
    try {
      const v=await _api(`/vendors/${id}`);
      _q('#ven-detail-title').textContent=v.name||'Vendor';
      _q('#ven-detail-body').innerHTML=`<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:13px;">
        <div><b>Category</b><br>${_esc(v.category||'')}</div><div><b>Status</b><br>${_esc(v.status||'')}</div>
        <div><b>Website</b><br>${v.website?`<a href="${_esc(v.website)}" target="_blank">${_esc(v.website)}</a>`:'—'}</div>
        <div><b>Contract</b><br>${(v.contract_start||'').slice(0,10)||'—'} → ${(v.contract_end||'').slice(0,10)||'—'}</div>
        <div><b>Value</b><br>${v.contract_value!=null?v.contract_value:'—'}</div><div><b>Owner</b><br>${_esc(v.owner||'—')}</div>
      </div>`;
      const allowed={prospect:['active','rejected'],active:['inactive','terminated'],inactive:['active'],terminated:[],rejected:[]};
      _q('#ven-transition-status').innerHTML=(allowed[v.status]||[]).map(s=>`<option value="${s}">${s}</option>`).join('')||'<option value="">No transitions</option>';
      const [conData,revData]=await Promise.all([_api(`/vendors/${id}/contacts`),_api(`/vendors/${id}/reviews`)]);
      const cons=conData.contacts||[];
      _q('#ven-con-list').innerHTML=cons.length?cons.map(c=>`<div style="font-size:12px;padding:3px 0;">${_esc(c.name)} (${_esc(c.role||'')}) — ${_esc(c.email||'')}</div>`).join(''):'<span style="color:var(--text-muted);font-size:12px;">No contacts</span>';
      const revs=revData.reviews||[];
      _q('#ven-rev-list').innerHTML=revs.length?revs.map(r=>`<div style="font-size:12px;padding:3px 0;border-bottom:1px solid var(--border);">★${r.rating} — ${_esc(r.notes||'')} <em style="color:var(--text-muted);">${_esc(r.reviewer||'')}</em></div>`).join(''):'<span style="color:var(--text-muted);font-size:12px;">No reviews</span>';
    } catch(err){_q('#ven-detail-body').innerHTML=`<p style="color:var(--danger);">${_esc(err.message||'Error')}</p>`;}
  }

  async function _openVenModal(id) {
    _q('#ven-modal').hidden=false; _q('#ven-modal-title').textContent=id?'Edit Vendor':'New Vendor'; _q('#ven-modal').dataset.id=id||'';
    const fields=['ven-f-name','ven-f-category','ven-f-website','ven-f-start','ven-f-end','ven-f-value','ven-f-sla','ven-f-owner','ven-f-notes'];
    if(id){try{const v=await _api(`/vendors/${id}`);fields.forEach(fid=>{const n=fid.replace('ven-f-','');const map={start:'contract_start',end:'contract_end',value:'contract_value',sla:'sla_tier'};const key=map[n]||n;const el=_q('#'+fid);if(el&&v[key]!=null)el.value=v[key];});}catch(_){}}
    else{fields.forEach(fid=>{const el=_q('#'+fid);if(el)el.value='';});}
  }

  async function _saveVen() {
    const id=_q('#ven-modal').dataset.id;
    const body={name:_q('#ven-f-name').value,category:_q('#ven-f-category').value,website:_q('#ven-f-website').value,
      contract_start:_q('#ven-f-start').value||null,contract_end:_q('#ven-f-end').value||null,
      contract_value:_q('#ven-f-value').value?parseFloat(_q('#ven-f-value').value):null,
      sla_tier:_q('#ven-f-sla').value,owner:_q('#ven-f-owner').value,notes:_q('#ven-f-notes').value};
    try{await _api(id?`/vendors/${id}`:'/vendors',id?'PATCH':'POST',body);_q('#ven-modal').hidden=true;_loadVenStats();_loadVendors();}
    catch(err){alert('Save failed: '+(err.message||err));}
  }

  async function _openVenTransModal() {
    _q('#ven-transition-modal').hidden=false;
  }

  async function _doVenTransition() {
    const status=_q('#ven-transition-status').value; if(!status) return;
    try{await _api(`/vendors/${_venCurrentId}/transition`,'POST',{status});_q('#ven-transition-modal').hidden=true;_venOpenDetail(_venCurrentId);_loadVenStats();_loadVendors();}
    catch(err){alert('Transition failed: '+(err.message||err));}
  }

  async function _addVenContact() {
    const name=_q('#ven-con-name').value.trim(); if(!name) return;
    const body={name,email:_q('#ven-con-email').value,role:_q('#ven-con-role').value};
    try{await _api(`/vendors/${_venCurrentId}/contacts`,'POST',body);_q('#ven-con-name').value='';_venOpenDetail(_venCurrentId);}
    catch(err){alert('Failed: '+(err.message||err));}
  }

  async function _addVenReview() {
    const body={rating:parseInt(_q('#ven-rev-rating').value)||3,reviewer:_q('#ven-rev-reviewer').value,notes:_q('#ven-rev-notes').value};
    try{await _api(`/vendors/${_venCurrentId}/reviews`,'POST',body);_venOpenDetail(_venCurrentId);}
    catch(err){alert('Failed: '+(err.message||err));}
  }

  async function _deleteVenCurrent() {
    if(!_venCurrentId||!confirm('Delete this vendor?')) return;
    try{await _api(`/vendors/${_venCurrentId}`,'DELETE');_q('#ven-detail').hidden=true;_venCurrentId=null;_loadVenStats();_loadVendors();}
    catch(err){alert('Delete failed: '+(err.message||err));}
  }

  async function _deleteVenById(id,name) {
    if(!confirm(`Delete vendor "${name}"?`)) return;
    try{await _api(`/vendors/${id}`,'DELETE');_loadVenStats();_loadVendors();}
    catch(err){alert('Delete failed: '+(err.message||err));}
  }

  // ── Capacity Planning ────────────────────────────────────────────────────────
  let _capOffset=0; const _CAP_LIMIT=50; let _capCurrentId=null;

  function initCapacityView() {
    _loadCapStats(); _loadCapacity();
    _q('#cap-add-btn').onclick   = () => _openCapModal();
    _q('#cap-search').oninput    = _debounce(() => { _capOffset=0; _loadCapacity(); });
    _q('#cap-filter-type').onchange   = () => { _capOffset=0; _loadCapacity(); };
    _q('#cap-filter-status').onchange = () => { _capOffset=0; _loadCapacity(); };
    _q('#cap-filter-env').onchange    = () => { _capOffset=0; _loadCapacity(); };
    _q('#cap-detail-close').onclick   = () => { _q('#cap-detail').hidden=true; };
    _q('#cap-modal-close').onclick    = () => { _q('#cap-modal').hidden=true; };
    _q('#cap-modal-cancel').onclick   = () => { _q('#cap-modal').hidden=true; };
    _q('#cap-modal-save').onclick     = () => _saveCap();
    _q('#cap-transition-modal-close').onclick  = () => { _q('#cap-transition-modal').hidden=true; };
    _q('#cap-transition-cancel').onclick       = () => { _q('#cap-transition-modal').hidden=true; };
    _q('#cap-transition-submit').onclick       = () => _doCapTransition();
    _q('#cap-edit-btn').onclick       = () => { if(_capCurrentId) _openCapModal(_capCurrentId); };
    _q('#cap-transition-btn').onclick = () => { if(_capCurrentId) _openCapTransModal(); };
    _q('#cap-delete-btn').onclick     = () => { if(_capCurrentId) _deleteCapCurrent(); };
    _q('#cap-snap-add-btn').onclick   = () => { if(_capCurrentId) _addCapSnap(); };
  }

  async function _loadCapStats() {
    try {
      const s=await _api('/capacity/resources/stats');
      _q('#cap-stats-row').innerHTML=[['Total',s.total],['Active',s.active],['Warning',s.warning||0],['Critical',s.critical||0]].map(([l,v])=>
        `<div class="report-card" style="padding:8px 12px;min-width:90px;"><span>${l}</span><strong>${v||0}</strong></div>`).join('');
    } catch(_) {}
  }

  async function _loadCapacity() {
    const q=_q('#cap-search').value.trim(); const type=_q('#cap-filter-type').value; const status=_q('#cap-filter-status').value; const env=_q('#cap-filter-env').value;
    const params=new URLSearchParams({limit:_CAP_LIMIT,offset:_capOffset});
    if(q) params.set('q',q); if(type) params.set('resource_type',type); if(status) params.set('status',status); if(env) params.set('environment',env);
    const tbody=_q('#cap-tbody');
    tbody.innerHTML='<tr><td colspan="5" style="text-align:center;color:var(--text-muted);padding:24px;">Loading...</td></tr>';
    try {
      const data=await _api(`/capacity/resources?${params}`); const rows=data.resources||[];
      if(!rows.length){tbody.innerHTML='<tr><td colspan="5" style="text-align:center;color:var(--text-muted);padding:24px;">No resources found.</td></tr>';return;}
      tbody.innerHTML=rows.map(r=>`<tr style="cursor:pointer;" onclick="_capOpenDetail('${r.id}')">
        <td><strong>${_esc(r.name||'')}</strong></td><td>${_esc(r.resource_type||'')}</td>
        <td><span class="badge ${r.utilization_pct>90?'bad':r.utilization_pct>70?'warn':'ok'}">${r.utilization_pct!=null?r.utilization_pct.toFixed(1)+'%':'—'}</span></td>
        <td>${_esc(r.environment||'')}</td>
        <td><button class="btn xs danger" onclick="event.stopPropagation();_deleteCapById('${r.id}','${_esc(r.name||'').replace(/'/g,"\\'")}')">Del</button></td>
      </tr>`).join('');
      const pages=Math.ceil(data.total/_CAP_LIMIT)||1; const page=Math.floor(_capOffset/_CAP_LIMIT)+1;
      _q('#cap-pagination').innerHTML=`<button class="btn xs" ${_capOffset===0?'disabled':''} onclick="_capOffset=Math.max(0,_capOffset-${_CAP_LIMIT});_loadCapacity()">Prev</button>
        <span style="color:var(--text-muted);">Page ${page}/${pages}</span>
        <button class="btn xs" ${_capOffset+_CAP_LIMIT>=data.total?'disabled':''} onclick="_capOffset+=_CAP_LIMIT;_loadCapacity()">Next</button>`;
    } catch(err){tbody.innerHTML=`<tr><td colspan="5" style="color:var(--danger);text-align:center;padding:24px;">${_esc(err.message||'Error')}</td></tr>`;}
  }

  async function _capOpenDetail(id) {
    _capCurrentId=id; _q('#cap-detail').hidden=false;
    _q('#cap-detail-body').innerHTML='Loading...'; _q('#cap-snap-list').innerHTML='';
    try {
      const r=await _api(`/capacity/resources/${id}`);
      _q('#cap-detail-title').textContent=r.name||'Resource';
      _q('#cap-detail-body').innerHTML=`<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:13px;">
        <div><b>Type</b><br>${_esc(r.resource_type||'')}</div><div><b>Status</b><br>${_esc(r.status||'')}</div>
        <div><b>Total</b><br>${r.total_capacity} ${_esc(r.unit||'')}</div><div><b>Used</b><br>${r.used_capacity||0} (${r.utilization_pct!=null?r.utilization_pct.toFixed(1):'0'}%)</div>
        <div><b>Allocated</b><br>${r.allocated_capacity||0}</div><div><b>Reserved</b><br>${r.reserved_capacity||0}</div>
        <div><b>Environment</b><br>${_esc(r.environment||'')}</div><div><b>Owner</b><br>${_esc(r.owner||'—')}</div>
      </div>`;
      const allowed={active:['warning','critical','decommissioned'],warning:['active','critical'],critical:['active','decommissioned'],decommissioned:[]};
      _q('#cap-transition-status').innerHTML=(allowed[r.status]||[]).map(s=>`<option value="${s}">${s}</option>`).join('')||'<option value="">No transitions</option>';
      const snapData=await _api(`/capacity/resources/${id}/snapshots`); const snaps=(snapData.snapshots||[]).slice(0,10);
      _q('#cap-snap-list').innerHTML=snaps.length?snaps.map(s=>`<div style="font-size:12px;padding:2px 0;">${(s.recorded_at||'').slice(0,16)} used=${s.used_capacity} ${_esc(s.notes||'')}</div>`).join(''):'<span style="color:var(--text-muted);font-size:12px;">No snapshots</span>';
    } catch(err){_q('#cap-detail-body').innerHTML=`<p style="color:var(--danger);">${_esc(err.message||'Error')}</p>`;}
  }

  async function _openCapModal(id) {
    _q('#cap-modal').hidden=false; _q('#cap-modal-title').textContent=id?'Edit Resource':'New Resource'; _q('#cap-modal').dataset.id=id||'';
    const fields=['cap-f-name','cap-f-type','cap-f-unit','cap-f-total','cap-f-allocated','cap-f-reserved','cap-f-env','cap-f-owner','cap-f-team','cap-f-notes'];
    if(id){try{const r=await _api(`/capacity/resources/${id}`);fields.forEach(fid=>{const n=fid.replace('cap-f-','');const map={type:'resource_type',total:'total_capacity',allocated:'allocated_capacity',reserved:'reserved_capacity',env:'environment'};const key=map[n]||n;const el=_q('#'+fid);if(el&&r[key]!=null)el.value=r[key];});}catch(_){}}
    else{fields.forEach(fid=>{const el=_q('#'+fid);if(el)el.value=''});}
  }

  async function _saveCap() {
    const id=_q('#cap-modal').dataset.id;
    const body={name:_q('#cap-f-name').value,resource_type:_q('#cap-f-type').value,unit:_q('#cap-f-unit').value,
      total_capacity:parseFloat(_q('#cap-f-total').value)||0,allocated_capacity:parseFloat(_q('#cap-f-allocated').value)||0,
      reserved_capacity:parseFloat(_q('#cap-f-reserved').value)||0,environment:_q('#cap-f-env').value,
      owner:_q('#cap-f-owner').value,team:_q('#cap-f-team').value,notes:_q('#cap-f-notes').value};
    try{await _api(id?`/capacity/resources/${id}`:'/capacity/resources',id?'PATCH':'POST',body);_q('#cap-modal').hidden=true;_loadCapStats();_loadCapacity();}
    catch(err){alert('Save failed: '+(err.message||err));}
  }

  async function _openCapTransModal() { _q('#cap-transition-modal').hidden=false; }

  async function _doCapTransition() {
    const status=_q('#cap-transition-status').value; if(!status) return;
    try{await _api(`/capacity/resources/${_capCurrentId}/transition`,'POST',{status});_q('#cap-transition-modal').hidden=true;_capOpenDetail(_capCurrentId);_loadCapStats();_loadCapacity();}
    catch(err){alert('Transition failed: '+(err.message||err));}
  }

  async function _addCapSnap() {
    const body={used_capacity:parseFloat(_q('#cap-snap-used').value)||0,total_capacity:parseFloat(_q('#cap-snap-total').value)||0,notes:_q('#cap-snap-notes').value};
    try{await _api(`/capacity/resources/${_capCurrentId}/snapshots`,'POST',body);_capOpenDetail(_capCurrentId);}
    catch(err){alert('Failed: '+(err.message||err));}
  }

  async function _deleteCapCurrent() {
    if(!_capCurrentId||!confirm('Delete this resource?')) return;
    try{await _api(`/capacity/resources/${_capCurrentId}`,'DELETE');_q('#cap-detail').hidden=true;_capCurrentId=null;_loadCapStats();_loadCapacity();}
    catch(err){alert('Delete failed: '+(err.message||err));}
  }

  async function _deleteCapById(id,name) {
    if(!confirm(`Delete resource "${name}"?`)) return;
    try{await _api(`/capacity/resources/${id}`,'DELETE');_loadCapStats();_loadCapacity();}
    catch(err){alert('Delete failed: '+(err.message||err));}
  }

  // ── Knowledge Base ───────────────────────────────────────────────────────────
  let _kbOffset=0; const _KB_LIMIT=50; let _kbCurrentId=null;

  function initKnowledgeView() {
    _loadKbStats(); _loadKb();
    _q('#kb-add-btn').onclick   = () => _openKbModal();
    _q('#kb-search').oninput    = _debounce(() => { _kbOffset=0; _loadKb(); });
    _q('#kb-filter-status').onchange   = () => { _kbOffset=0; _loadKb(); };
    _q('#kb-filter-category').onchange = () => { _kbOffset=0; _loadKb(); };
    _q('#kb-detail-close').onclick     = () => { _q('#kb-detail').hidden=true; };
    _q('#kb-modal-close').onclick      = () => { _q('#kb-modal').hidden=true; };
    _q('#kb-modal-cancel').onclick     = () => { _q('#kb-modal').hidden=true; };
    _q('#kb-modal-save').onclick       = () => _saveKb();
    _q('#kb-transition-modal-close').onclick  = () => { _q('#kb-transition-modal').hidden=true; };
    _q('#kb-transition-cancel').onclick       = () => { _q('#kb-transition-modal').hidden=true; };
    _q('#kb-transition-submit').onclick       = () => _doKbTransition();
    _q('#kb-edit-btn').onclick       = () => { if(_kbCurrentId) _openKbModal(_kbCurrentId); };
    _q('#kb-transition-btn').onclick = () => { if(_kbCurrentId) _openKbTransModal(); };
    _q('#kb-delete-btn').onclick     = () => { if(_kbCurrentId) _deleteKbCurrent(); };
    _q('#kb-rev-save-btn').onclick   = () => { if(_kbCurrentId) _saveKbRevision(); };
  }

  async function _loadKbStats() {
    try {
      const s=await _api('/kb/articles/stats');
      _q('#kb-stats-row').innerHTML=[['Total',s.total],['Published',s.published||0],['Views',s.total_views||0],['Categories',(s.by_category||[]).length]].map(([l,v])=>
        `<div class="report-card" style="padding:8px 12px;min-width:90px;"><span>${l}</span><strong>${v||0}</strong></div>`).join('');
    } catch(_) {}
  }

  async function _loadKb() {
    const q=_q('#kb-search').value.trim(); const status=_q('#kb-filter-status').value; const cat=_q('#kb-filter-category').value;
    const params=new URLSearchParams({limit:_KB_LIMIT,offset:_kbOffset});
    if(q) params.set('q',q); if(status) params.set('status',status); if(cat) params.set('category',cat);
    const tbody=_q('#kb-tbody');
    tbody.innerHTML='<tr><td colspan="5" style="text-align:center;color:var(--text-muted);padding:24px;">Loading...</td></tr>';
    try {
      const data=await _api(`/kb/articles?${params}`); const rows=data.articles||[];
      if(!rows.length){tbody.innerHTML='<tr><td colspan="5" style="text-align:center;color:var(--text-muted);padding:24px;">No articles found.</td></tr>';return;}
      tbody.innerHTML=rows.map(r=>`<tr style="cursor:pointer;" onclick="_kbOpenDetail('${r.id}')">
        <td><strong>${_esc(r.title||'')}</strong></td><td>${_esc(r.category||'')}</td>
        <td><span class="badge">${_esc(r.status||'')}</span></td><td>${r.view_count||0}</td>
        <td><button class="btn xs" onclick="event.stopPropagation();_openKbModal('${r.id}')">Edit</button>
            <button class="btn xs danger" onclick="event.stopPropagation();_deleteKbById('${r.id}','${_esc(r.title||'').replace(/'/g,"\\'")}')">Del</button></td>
      </tr>`).join('');
      const pages=Math.ceil(data.total/_KB_LIMIT)||1; const page=Math.floor(_kbOffset/_KB_LIMIT)+1;
      _q('#kb-pagination').innerHTML=`<button class="btn xs" ${_kbOffset===0?'disabled':''} onclick="_kbOffset=Math.max(0,_kbOffset-${_KB_LIMIT});_loadKb()">Prev</button>
        <span style="color:var(--text-muted);">Page ${page}/${pages}</span>
        <button class="btn xs" ${_kbOffset+_KB_LIMIT>=data.total?'disabled':''} onclick="_kbOffset+=_KB_LIMIT;_loadKb()">Next</button>`;
    } catch(err){tbody.innerHTML=`<tr><td colspan="5" style="color:var(--danger);text-align:center;padding:24px;">${_esc(err.message||'Error')}</td></tr>`;}
  }

  async function _kbOpenDetail(id) {
    _kbCurrentId=id; _q('#kb-detail').hidden=false;
    _q('#kb-detail-meta').innerHTML='Loading...'; _q('#kb-detail-body').innerHTML=''; _q('#kb-rev-list').innerHTML='';
    try {
      const a=await _api(`/kb/articles/${id}`);
      _q('#kb-detail-title').textContent=a.title||'Article';
      _q('#kb-detail-meta').innerHTML=`<div style="display:flex;gap:16px;font-size:13px;flex-wrap:wrap;">
        <span><b>Category:</b> ${_esc(a.category||'')}</span><span><b>Status:</b> ${_esc(a.status||'')}</span>
        <span><b>Author:</b> ${_esc(a.author||'—')}</span><span><b>Views:</b> ${a.view_count||0}</span>
        <span><b>Tags:</b> ${_esc(a.tags||'—')}</span></div>`;
      _q('#kb-detail-body').innerHTML=`<div style="margin-top:12px;white-space:pre-wrap;font-size:13px;border:1px solid var(--border);border-radius:6px;padding:12px;max-height:300px;overflow:auto;">${_esc(a.body||'')}</div>`;
      const allowed={draft:['published','archived'],published:['draft','archived'],archived:['draft'],deprecated:[]};
      _q('#kb-transition-status').innerHTML=(allowed[a.status]||[]).map(s=>`<option value="${s}">${s}</option>`).join('')||'<option value="">No transitions</option>';
      const revData=await _api(`/kb/articles/${id}/revisions`); const revs=revData.revisions||[];
      _q('#kb-rev-list').innerHTML=revs.length?revs.map(r=>`<div style="font-size:12px;padding:2px 0;">Rev${r.revision_number} — ${_esc(r.author||'')} — ${(r.created_at||'').slice(0,10)} ${r.change_note?`<em>${_esc(r.change_note)}</em>`:''}</div>`).join(''):'<span style="color:var(--text-muted);font-size:12px;">No revisions</span>';
    } catch(err){_q('#kb-detail-meta').innerHTML=`<p style="color:var(--danger);">${_esc(err.message||'Error')}</p>`;}
  }

  async function _openKbModal(id) {
    _q('#kb-modal').hidden=false; _q('#kb-modal-title').textContent=id?'Edit Article':'New Article'; _q('#kb-modal').dataset.id=id||'';
    const fields={title:'kb-f-title',category:'kb-f-category',tags:'kb-f-tags',author:'kb-f-author',body:'kb-f-body'};
    if(id){try{const a=await _api(`/kb/articles/${id}`);Object.entries(fields).forEach(([k,fid])=>{const el=_q('#'+fid);if(el&&a[k]!=null)el.value=a[k];});}catch(_){}}
    else{Object.values(fields).forEach(fid=>{const el=_q('#'+fid);if(el)el.value=''});}
  }

  async function _saveKb() {
    const id=_q('#kb-modal').dataset.id;
    const body={title:_q('#kb-f-title').value,category:_q('#kb-f-category').value,tags:_q('#kb-f-tags').value,author:_q('#kb-f-author').value,body:_q('#kb-f-body').value};
    try{await _api(id?`/kb/articles/${id}`:'/kb/articles',id?'PATCH':'POST',body);_q('#kb-modal').hidden=true;_loadKbStats();_loadKb();}
    catch(err){alert('Save failed: '+(err.message||err));}
  }

  async function _openKbTransModal() { _q('#kb-transition-modal').hidden=false; }

  async function _doKbTransition() {
    const status=_q('#kb-transition-status').value; const author=_q('#kb-transition-author').value; if(!status) return;
    try{await _api(`/kb/articles/${_kbCurrentId}/transition`,'POST',{status,author});_q('#kb-transition-modal').hidden=true;_kbOpenDetail(_kbCurrentId);_loadKbStats();_loadKb();}
    catch(err){alert('Transition failed: '+(err.message||err));}
  }

  async function _saveKbRevision() {
    const body={author:_q('#kb-rev-author').value,body:_q('#kb-f-body')?.value||''};
    try{await _api(`/kb/articles/${_kbCurrentId}/revisions`,'POST',body);_kbOpenDetail(_kbCurrentId);}
    catch(err){alert('Failed: '+(err.message||err));}
  }

  async function _deleteKbCurrent() {
    if(!_kbCurrentId||!confirm('Delete this article?')) return;
    try{await _api(`/kb/articles/${_kbCurrentId}`,'DELETE');_q('#kb-detail').hidden=true;_kbCurrentId=null;_loadKbStats();_loadKb();}
    catch(err){alert('Delete failed: '+(err.message||err));}
  }

  async function _deleteKbById(id,name) {
    if(!confirm(`Delete article "${name}"?`)) return;
    try{await _api(`/kb/articles/${id}`,'DELETE');_loadKbStats();_loadKb();}
    catch(err){alert('Delete failed: '+(err.message||err));}
  }

  // ── Asset Management ─────────────────────────────────────────────────────────
  let _assetOffset=0; const _ASSET_LIMIT=50; let _assetCurrentId=null;

  function initAssetsView() {
    _loadAssetStats(); _loadAssets();
    _q('#asset-add-btn').onclick   = () => _openAssetModal();
    _q('#asset-search').oninput    = _debounce(() => { _assetOffset=0; _loadAssets(); });
    _q('#asset-filter-type').onchange   = () => { _assetOffset=0; _loadAssets(); };
    _q('#asset-filter-status').onchange = () => { _assetOffset=0; _loadAssets(); };
    _q('#asset-filter-env').onchange    = () => { _assetOffset=0; _loadAssets(); };
    _q('#asset-detail-close').onclick   = () => { _q('#asset-detail').hidden=true; };
    _q('#asset-modal-close').onclick    = () => { _q('#asset-modal').hidden=true; };
    _q('#asset-modal-cancel').onclick   = () => { _q('#asset-modal').hidden=true; };
    _q('#asset-modal-save').onclick     = () => _saveAsset();
    _q('#asset-transition-modal').onsubmit = e => { e.preventDefault(); _doAssetTransition(); };
    _q('#asset-transition-modal-close').onclick  = () => { _q('#asset-transition-modal').hidden=true; };
    _q('#asset-transition-cancel').onclick       = () => { _q('#asset-transition-modal').hidden=true; };
    _q('#asset-transition-submit').onclick       = () => _doAssetTransition();
    _q('#asset-edit-btn').onclick       = () => { if(_assetCurrentId) _openAssetModal(_assetCurrentId); };
    _q('#asset-transition-btn').onclick = () => { if(_assetCurrentId) _openAssetTransModal(); };
    _q('#asset-delete-btn').onclick     = () => { if(_assetCurrentId) _deleteAssetCurrent(); };
    _q('#asset-rel-add-btn').onclick    = () => { if(_assetCurrentId) _addAssetRel(); };
    _q('#asset-evt-add-btn').onclick    = () => { if(_assetCurrentId) _addAssetEvt(); };
  }

  async function _loadAssetStats() {
    try {
      const s=await _api('/assets/stats');
      _q('#asset-stats-row').innerHTML=[['Total',s.total],['Active',s.active||0],['Retired',s.retired||0],['Types',(s.by_type||[]).length]].map(([l,v])=>
        `<div class="report-card" style="padding:8px 12px;min-width:90px;"><span>${l}</span><strong>${v||0}</strong></div>`).join('');
    } catch(_) {}
  }

  async function _loadAssets() {
    const q=_q('#asset-search').value.trim(); const type=_q('#asset-filter-type').value; const status=_q('#asset-filter-status').value; const env=_q('#asset-filter-env').value;
    const params=new URLSearchParams({limit:_ASSET_LIMIT,offset:_assetOffset});
    if(q) params.set('q',q); if(type) params.set('asset_type',type); if(status) params.set('status',status); if(env) params.set('environment',env);
    const tbody=_q('#asset-tbody');
    tbody.innerHTML='<tr><td colspan="5" style="text-align:center;color:var(--text-muted);padding:24px;">Loading...</td></tr>';
    try {
      const data=await _api(`/assets?${params}`); const rows=data.assets||[];
      if(!rows.length){tbody.innerHTML='<tr><td colspan="5" style="text-align:center;color:var(--text-muted);padding:24px;">No assets found.</td></tr>';return;}
      tbody.innerHTML=rows.map(r=>`<tr style="cursor:pointer;" onclick="_assetOpenDetail('${r.id}')">
        <td><strong>${_esc(r.name||'')}</strong></td><td>${_esc(r.asset_type||'')}</td>
        <td><span class="badge">${_esc(r.status||'')}</span></td><td>${_esc(r.environment||'')}</td>
        <td><button class="btn xs" onclick="event.stopPropagation();_openAssetModal('${r.id}')">Edit</button>
            <button class="btn xs danger" onclick="event.stopPropagation();_deleteAssetById('${r.id}','${_esc(r.name||'').replace(/'/g,"\\'")}')">Del</button></td>
      </tr>`).join('');
      const pages=Math.ceil(data.total/_ASSET_LIMIT)||1; const page=Math.floor(_assetOffset/_ASSET_LIMIT)+1;
      _q('#asset-pagination').innerHTML=`<button class="btn xs" ${_assetOffset===0?'disabled':''} onclick="_assetOffset=Math.max(0,_assetOffset-${_ASSET_LIMIT});_loadAssets()">Prev</button>
        <span style="color:var(--text-muted);">Page ${page}/${pages}</span>
        <button class="btn xs" ${_assetOffset+_ASSET_LIMIT>=data.total?'disabled':''} onclick="_assetOffset+=_ASSET_LIMIT;_loadAssets()">Next</button>`;
    } catch(err){tbody.innerHTML=`<tr><td colspan="5" style="color:var(--danger);text-align:center;padding:24px;">${_esc(err.message||'Error')}</td></tr>`;}
  }

  async function _assetOpenDetail(id) {
    _assetCurrentId=id; _q('#asset-detail').hidden=false;
    _q('#asset-detail-body').innerHTML='Loading...'; _q('#asset-rel-list').innerHTML=''; _q('#asset-evt-list').innerHTML='';
    try {
      const a=await _api(`/assets/${id}`);
      _q('#asset-detail-title').textContent=a.name||'Asset';
      _q('#asset-detail-body').innerHTML=`<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:13px;">
        <div><b>Type</b><br>${_esc(a.asset_type||'')}</div><div><b>Status</b><br>${_esc(a.status||'')}</div>
        <div><b>Environment</b><br>${_esc(a.environment||'')}</div><div><b>Hostname</b><br>${_esc(a.hostname||'—')}</div>
        <div><b>IP</b><br>${_esc(a.ip_address||'—')}</div><div><b>Version</b><br>${_esc(a.version||'—')}</div>
        <div><b>Owner</b><br>${_esc(a.owner||'—')}</div><div><b>Team</b><br>${_esc(a.team||'—')}</div>
      </div>`;
      const allowed={active:['maintenance','retired','decommissioned'],maintenance:['active'],retired:['active'],decommissioned:[]};
      _q('#asset-transition-status').innerHTML=(allowed[a.status]||[]).map(s=>`<option value="${s}">${s}</option>`).join('')||'<option value="">No transitions</option>';
      const [relData,evtData]=await Promise.all([_api(`/assets/${id}/relationships`),_api(`/assets/${id}/events`)]);
      const rels=relData.relationships||[];
      _q('#asset-rel-list').innerHTML=rels.length?rels.map(r=>`<div style="font-size:12px;padding:2px 0;">${_esc(r.relationship_type)} → ${_esc(r.target_id)} <button class="btn xs danger" onclick="_deleteAssetRel('${id}','${r.id}')">✕</button></div>`).join(''):'<span style="color:var(--text-muted);font-size:12px;">No relationships</span>';
      const evts=evtData.events||[];
      _q('#asset-evt-list').innerHTML=evts.slice(0,8).map(e=>`<div style="font-size:12px;padding:2px 0;">${(e.created_at||'').slice(0,10)} ${_esc(e.note||'')} <em style="color:var(--text-muted);">${_esc(e.author||'')}</em></div>`).join('')||'<span style="color:var(--text-muted);font-size:12px;">No events</span>';
    } catch(err){_q('#asset-detail-body').innerHTML=`<p style="color:var(--danger);">${_esc(err.message||'Error')}</p>`;}
  }

  async function _openAssetModal(id) {
    _q('#asset-modal').hidden=false; _q('#asset-modal-title').textContent=id?'Edit Asset':'New Asset'; _q('#asset-modal').dataset.id=id||'';
    const map={name:'asset-f-name',asset_type:'asset-f-type',environment:'asset-f-env',hostname:'asset-f-hostname',ip_address:'asset-f-ip',version:'asset-f-version',owner:'asset-f-owner',team:'asset-f-team',tags:'asset-f-tags',description:'asset-f-desc'};
    if(id){try{const a=await _api(`/assets/${id}`);Object.entries(map).forEach(([k,fid])=>{const el=_q('#'+fid);if(el&&a[k]!=null)el.value=a[k];});}catch(_){}}
    else{Object.values(map).forEach(fid=>{const el=_q('#'+fid);if(el)el.value=''});}
  }

  async function _saveAsset() {
    const id=_q('#asset-modal').dataset.id;
    const body={name:_q('#asset-f-name').value,asset_type:_q('#asset-f-type').value,environment:_q('#asset-f-env').value,
      hostname:_q('#asset-f-hostname').value,ip_address:_q('#asset-f-ip').value,version:_q('#asset-f-version').value,
      owner:_q('#asset-f-owner').value,team:_q('#asset-f-team').value,tags:_q('#asset-f-tags').value,description:_q('#asset-f-desc').value};
    try{await _api(id?`/assets/${id}`:'/assets',id?'PATCH':'POST',body);_q('#asset-modal').hidden=true;_loadAssetStats();_loadAssets();}
    catch(err){alert('Save failed: '+(err.message||err));}
  }

  async function _openAssetTransModal() { _q('#asset-transition-modal').hidden=false; }

  async function _doAssetTransition() {
    const status=_q('#asset-transition-status').value; const note=_q('#asset-transition-note').value; const author=_q('#asset-transition-author').value; if(!status) return;
    try{await _api(`/assets/${_assetCurrentId}/transition`,'POST',{status,note,author});_q('#asset-transition-modal').hidden=true;_assetOpenDetail(_assetCurrentId);_loadAssetStats();_loadAssets();}
    catch(err){alert('Transition failed: '+(err.message||err));}
  }

  async function _addAssetRel() {
    const target=_q('#asset-rel-target-id').value.trim(); const type=_q('#asset-rel-type').value; if(!target) return;
    try{await _api(`/assets/${_assetCurrentId}/relationships`,'POST',{target_id:target,relationship_type:type});_assetOpenDetail(_assetCurrentId);}
    catch(err){alert('Failed: '+(err.message||err));}
  }

  async function _deleteAssetRel(assetId,relId) {
    try{await _api(`/assets/${assetId}/relationships/${relId}`,'DELETE');_assetOpenDetail(assetId);}
    catch(err){alert('Failed: '+(err.message||err));}
  }

  async function _addAssetEvt() {
    const note=_q('#asset-evt-note').value.trim(); const author=_q('#asset-evt-author').value.trim(); if(!note) return;
    try{await _api(`/assets/${_assetCurrentId}/events`,'POST',{note,author});_q('#asset-evt-note').value='';_assetOpenDetail(_assetCurrentId);}
    catch(err){alert('Failed: '+(err.message||err));}
  }

  async function _deleteAssetCurrent() {
    if(!_assetCurrentId||!confirm('Delete this asset?')) return;
    try{await _api(`/assets/${_assetCurrentId}`,'DELETE');_q('#asset-detail').hidden=true;_assetCurrentId=null;_loadAssetStats();_loadAssets();}
    catch(err){alert('Delete failed: '+(err.message||err));}
  }

  async function _deleteAssetById(id,name) {
    if(!confirm(`Delete asset "${name}"?`)) return;
    try{await _api(`/assets/${id}`,'DELETE');_loadAssetStats();_loadAssets();}
    catch(err){alert('Delete failed: '+(err.message||err));}
  }

  // ── Deployments ───────────────────────────────────────────────────────────────
  let _depOffset=0; const _DEP_LIMIT=50; let _depCurrentId=null;

  function initDeploymentsView() {
    _loadDepStats(); _loadDeployments();
    _q('#depAddBtn').onclick     = () => _openDepModal();
    _q('#depRefreshBtn').onclick = () => { _loadDepStats(); _loadDeployments(); };
    _q('#depSearchBtn').onclick  = () => { _depOffset=0; _loadDeployments(); };
    _q('#depSearchInput').onkeydown = e => { if(e.key==='Enter'){_depOffset=0;_loadDeployments();} };
    _q('#depStatusFilter').onchange = () => { _depOffset=0; _loadDeployments(); };
    _q('#depEnvFilter').onchange    = () => { _depOffset=0; _loadDeployments(); };
    _q('#depEditModalClose').onclick  = () => { _q('#depEditModal').hidden=true; };
    _q('#depEditModalCancel').onclick = () => { _q('#depEditModal').hidden=true; };
    _q('#depEditForm').onsubmit = e => { e.preventDefault(); _saveDep(); };
    _q('#depDetailModalClose').onclick    = () => { _q('#depDetailModal').hidden=true; };
    _q('#depDetailModalCloseBtn').onclick = () => { _q('#depDetailModal').hidden=true; };
    _q('#depDetailEditBtn').onclick = () => { if(_depCurrentId) _openDepModal(_depCurrentId); };
    _q('#depTransitionBtn').onclick = () => { if(_depCurrentId) _openDepTransModal(); };
    _q('#depAddNoteBtn').onclick     = () => { if(_depCurrentId) { _q('#depNoteModal').hidden=false; _q('#depNoteForm').reset(); } };
    _q('#depTransitionModalClose').onclick  = () => { _q('#depTransitionModal').hidden=true; };
    _q('#depTransitionModalCancel').onclick = () => { _q('#depTransitionModal').hidden=true; };
    _q('#depTransitionForm').onsubmit = e => { e.preventDefault(); _doDepTransition(); };
    _q('#depNoteModalClose').onclick  = () => { _q('#depNoteModal').hidden=true; };
    _q('#depNoteModalCancel').onclick = () => { _q('#depNoteModal').hidden=true; };
    _q('#depNoteForm').onsubmit = e => { e.preventDefault(); _addDepNote(); };
  }

  async function _loadDepStats() {
    try {
      const s=await _api('/deployments/stats');
      const strip=_q('#depStatsStrip');
      strip.innerHTML=[['Total',s.total],['Running',s.running||0],['Success',s.successful||0],['Failed',s.failed||0]].map(([l,v])=>
        `<div class="report-card" style="padding:8px 12px;min-width:90px;"><span>${l}</span><strong>${v||0}</strong></div>`).join('');
    } catch(_) {}
  }

  async function _loadDeployments() {
    const q=_q('#depSearchInput').value.trim(); const status=_q('#depStatusFilter').value; const env=_q('#depEnvFilter').value;
    const params=new URLSearchParams({limit:_DEP_LIMIT,offset:_depOffset});
    if(q) params.set('q',q); if(status) params.set('status',status); if(env) params.set('environment',env);
    const tbody=_q('#depListTbody');
    tbody.innerHTML='<tr><td colspan="6" style="text-align:center;color:var(--text-muted);padding:24px;">Loading...</td></tr>';
    try {
      const data=await _api(`/deployments?${params}`); const rows=data.deployments||[];
      _q('#depListCount').textContent=`${data.total} total`;
      if(!rows.length){tbody.innerHTML='<tr><td colspan="6" style="text-align:center;color:var(--text-muted);padding:24px;">No deployments found.</td></tr>';return;}
      tbody.innerHTML=rows.map(r=>`<tr style="cursor:pointer;" onclick="_depOpenDetail('${r.id}')">
        <td><strong>${_esc(r.name||'')}</strong></td><td>${_esc(r.version||'')}</td>
        <td>${_esc(r.environment||'')}</td>
        <td><span class="badge ${r.status==='failed'?'bad':r.status==='running'?'warn':'ok'}">${_esc(r.status||'')}</span></td>
        <td>${_esc(r.deployer||'')}</td>
        <td><button class="btn xs" onclick="event.stopPropagation();_openDepModal('${r.id}')">Edit</button></td>
      </tr>`).join('');
      const pages=Math.ceil(data.total/_DEP_LIMIT)||1; const page=Math.floor(_depOffset/_DEP_LIMIT)+1;
      _q('#depPagination').innerHTML=`<button class="btn xs" ${_depOffset===0?'disabled':''} onclick="_depOffset=Math.max(0,_depOffset-${_DEP_LIMIT});_loadDeployments()">Prev</button>
        <span style="color:var(--text-muted);">Page ${page}/${pages}</span>
        <button class="btn xs" ${_depOffset+_DEP_LIMIT>=data.total?'disabled':''} onclick="_depOffset+=_DEP_LIMIT;_loadDeployments()">Next</button>`;
    } catch(err){tbody.innerHTML=`<tr><td colspan="6" style="color:var(--danger);text-align:center;padding:24px;">${_esc(err.message||'Error')}</td></tr>`;}
  }

  async function _depOpenDetail(id) {
    _depCurrentId=id; _q('#depDetailModal').hidden=false; _q('#depDetailModalBody').innerHTML='Loading...';
    try {
      const d=await _api(`/deployments/${id}`);
      _q('#depDetailModalTitle').textContent=`${d.name||''} v${d.version||''}`;
      const notesData=await _api(`/deployments/${id}/notes`); const notes=(notesData.notes||[]);
      const allowed={pending:['running','cancelled'],running:['success','failed','rolled_back'],success:[],failed:['rolled_back'],rolled_back:[],cancelled:[]};
      _q('#depTransitionStatus').innerHTML=(allowed[d.status]||[]).map(s=>`<option value="${s}">${s}</option>`).join('')||'<option value="">No transitions</option>';
      _q('#depDetailModalBody').innerHTML=`<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:13px;">
        <div><b>Version</b><br>${_esc(d.version||'')}</div><div><b>Status</b><br>${_esc(d.status||'')}</div>
        <div><b>Environment</b><br>${_esc(d.environment||'')}</div><div><b>Deployer</b><br>${_esc(d.deployer||'—')}</div>
        <div><b>Service ID</b><br>${_esc(d.service_id||'—')}</div><div><b>Change ID</b><br>${_esc(d.change_id||'—')}</div>
      </div>${d.notes?`<p style="margin-top:8px;font-size:13px;">${_esc(d.notes)}</p>`:''}
      <h4 style="margin:12px 0 4px;">Activity Notes</h4>
      <div>${notes.map(n=>`<div style="font-size:12px;padding:2px 0;border-bottom:1px solid var(--border);">${(n.created_at||'').slice(0,10)} ${_esc(n.text||'')} <em style="color:var(--text-muted);">${_esc(n.author||'')}</em></div>`).join('')||'<span style="color:var(--text-muted);">No notes</span>'}</div>`;
    } catch(err){_q('#depDetailModalBody').innerHTML=`<p style="color:var(--danger);">${_esc(err.message||'Error')}</p>`;}
  }

  async function _openDepModal(id) {
    _q('#depEditModal').hidden=false; _q('#depEditModalTitle').textContent=id?'Edit Deployment':'New Deployment'; _q('#depFormId').value=id||'';
    const map={name:'depFormName',version:'depFormVersion',environment:'depFormEnv',deployer:'depFormDeployer',service_id:'depFormServiceId',change_id:'depFormChangeId',notes:'depFormNotes'};
    if(id){try{const d=await _api(`/deployments/${id}`);Object.entries(map).forEach(([k,eid])=>{const el=_q('#'+eid);if(el&&d[k]!=null)el.value=d[k];});}catch(_){}}
    else{Object.values(map).forEach(eid=>{const el=_q('#'+eid);if(el)el.value=''});}
  }

  async function _saveDep() {
    const id=_q('#depFormId').value;
    const body={name:_q('#depFormName').value,version:_q('#depFormVersion').value,environment:_q('#depFormEnv').value,
      deployer:_q('#depFormDeployer').value,service_id:_q('#depFormServiceId').value||null,
      change_id:_q('#depFormChangeId').value||null,notes:_q('#depFormNotes').value};
    try{await _api(id?`/deployments/${id}`:'/deployments',id?'PATCH':'POST',body);_q('#depEditModal').hidden=true;_loadDepStats();_loadDeployments();}
    catch(err){alert('Save failed: '+(err.message||err));}
  }

  async function _openDepTransModal() { _q('#depTransitionModal').hidden=false; }

  async function _doDepTransition() {
    const status=_q('#depTransitionStatus').value; const note=_q('#depTransitionNote').value; const author=_q('#depTransitionAuthor').value; if(!status) return;
    try{await _api(`/deployments/${_depCurrentId}/transition`,'POST',{status,note,author});_q('#depTransitionModal').hidden=true;_depOpenDetail(_depCurrentId);_loadDepStats();_loadDeployments();}
    catch(err){alert('Transition failed: '+(err.message||err));}
  }

  async function _addDepNote() {
    const body={text:_q('#depNoteText').value,author:_q('#depNoteAuthor').value};
    try{await _api(`/deployments/${_depCurrentId}/notes`,'POST',body);_q('#depNoteModal').hidden=true;_depOpenDetail(_depCurrentId);}
    catch(err){alert('Failed: '+(err.message||err));}
  }

  // ── Service Catalog ───────────────────────────────────────────────────────────
  let _svcOffset=0; const _SVC_LIMIT=50; let _svcCurrentId=null;

  function initServicesView() {
    _loadSvcStats(); _loadServices();
    _q('#svcAddBtn').onclick     = () => _openSvcModal();
    _q('#svcRefreshBtn').onclick = () => { _loadSvcStats(); _loadServices(); };
    _q('#svcSearchBtn').onclick  = () => { _svcOffset=0; _loadServices(); };
    _q('#svcSearchInput').onkeydown = e => { if(e.key==='Enter'){_svcOffset=0;_loadServices();} };
    _q('#svcStatusFilter').onchange = () => { _svcOffset=0; _loadServices(); };
    _q('#svcTierFilter').onchange   = () => { _svcOffset=0; _loadServices(); };
    _q('#svcEditModalClose').onclick  = () => { _q('#svcEditModal').hidden=true; };
    _q('#svcEditModalCancel').onclick = () => { _q('#svcEditModal').hidden=true; };
    _q('#svcEditForm').onsubmit = e => { e.preventDefault(); _saveSvc(); };
    _q('#svcDetailModalClose').onclick    = () => { _q('#svcDetailModal').hidden=true; };
    _q('#svcDetailModalCloseBtn').onclick = () => { _q('#svcDetailModal').hidden=true; };
    _q('#svcDetailEditBtn').onclick   = () => { if(_svcCurrentId) _openSvcModal(_svcCurrentId); };
    _q('#svcUpdateStatusBtn').onclick = () => { if(_svcCurrentId) { _q('#svcStatusModal').hidden=false; _q('#svcStatusForm').reset(); } };
    _q('#svcStatusModalClose').onclick  = () => { _q('#svcStatusModal').hidden=true; };
    _q('#svcStatusModalCancel').onclick = () => { _q('#svcStatusModal').hidden=true; };
    _q('#svcStatusForm').onsubmit = e => { e.preventDefault(); _doSvcStatus(); };
  }

  async function _loadSvcStats() {
    try {
      const s=await _api('/services/stats');
      const strip=_q('#svcStatsStrip');
      strip.innerHTML=[['Total',s.total],['Operational',s.operational||0],['Degraded',s.degraded||0],['Down',s.down||0]].map(([l,v])=>
        `<div class="report-card" style="padding:8px 12px;min-width:90px;"><span>${l}</span><strong>${v||0}</strong></div>`).join('');
    } catch(_) {}
  }

  async function _loadServices() {
    const q=_q('#svcSearchInput').value.trim(); const status=_q('#svcStatusFilter').value; const tier=_q('#svcTierFilter').value;
    const params=new URLSearchParams({limit:_SVC_LIMIT,offset:_svcOffset});
    if(q) params.set('q',q); if(status) params.set('status',status); if(tier) params.set('tier',tier);
    const tbody=_q('#svcListTbody');
    tbody.innerHTML='<tr><td colspan="5" style="text-align:center;color:var(--text-muted);padding:24px;">Loading...</td></tr>';
    try {
      const data=await _api(`/services?${params}`); const rows=data.services||[];
      _q('#svcListCount').textContent=`${data.total} total`;
      if(!rows.length){tbody.innerHTML='<tr><td colspan="5" style="text-align:center;color:var(--text-muted);padding:24px;">No services found.</td></tr>';return;}
      tbody.innerHTML=rows.map(r=>`<tr style="cursor:pointer;" onclick="_svcOpenDetail('${r.id}')">
        <td><strong>${_esc(r.name||'')}</strong></td><td>${_esc(r.tier||'')}</td>
        <td><span class="badge ${r.status==='down'?'bad':r.status==='degraded'?'warn':'ok'}">${_esc(r.status||'')}</span></td>
        <td>${_esc(r.owner||'')}</td>
        <td><button class="btn xs" onclick="event.stopPropagation();_openSvcModal('${r.id}')">Edit</button></td>
      </tr>`).join('');
      const pages=Math.ceil(data.total/_SVC_LIMIT)||1; const page=Math.floor(_svcOffset/_SVC_LIMIT)+1;
      _q('#svcPagination').innerHTML=`<button class="btn xs" ${_svcOffset===0?'disabled':''} onclick="_svcOffset=Math.max(0,_svcOffset-${_SVC_LIMIT});_loadServices()">Prev</button>
        <span style="color:var(--text-muted);">Page ${page}/${pages}</span>
        <button class="btn xs" ${_svcOffset+_SVC_LIMIT>=data.total?'disabled':''} onclick="_svcOffset+=_SVC_LIMIT;_loadServices()">Next</button>`;
    } catch(err){tbody.innerHTML=`<tr><td colspan="5" style="color:var(--danger);text-align:center;padding:24px;">${_esc(err.message||'Error')}</td></tr>`;}
  }

  async function _svcOpenDetail(id) {
    _svcCurrentId=id; _q('#svcDetailModal').hidden=false; _q('#svcDetailModalBody').innerHTML='Loading...';
    try {
      const s=await _api(`/services/${id}`);
      _q('#svcDetailModalTitle').textContent=s.name||'Service';
      const histData=await _api(`/services/${id}/history`); const hist=(histData.history||[]).slice(0,5);
      _q('#svcDetailModalBody').innerHTML=`<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:13px;">
        <div><b>Tier</b><br>${_esc(s.tier||'')}</div><div><b>Status</b><br><span class="badge ${s.status==='down'?'bad':s.status==='degraded'?'warn':'ok'}">${_esc(s.status||'')}</span></div>
        <div><b>Owner</b><br>${_esc(s.owner||'—')}</div><div><b>Team</b><br>${_esc(s.team||'—')}</div>
        ${s.doc_url?`<div><b>Docs</b><br><a href="${_esc(s.doc_url)}" target="_blank">Link</a></div>`:''}
        ${s.health_url?`<div><b>Health</b><br><a href="${_esc(s.health_url)}" target="_blank">Check</a></div>`:''}
      </div>${s.description?`<p style="margin-top:8px;font-size:13px;">${_esc(s.description)}</p>`:''}
      <h4 style="margin:12px 0 4px;">Status History</h4>
      <div>${hist.map(h=>`<div style="font-size:12px;padding:2px 0;">${(h.changed_at||'').slice(0,16)} <strong>${_esc(h.status)}</strong> ${_esc(h.reason||'')} <em style="color:var(--text-muted);">${_esc(h.changed_by||'')}</em></div>`).join('')||'<span style="color:var(--text-muted);">No history</span>'}</div>`;
    } catch(err){_q('#svcDetailModalBody').innerHTML=`<p style="color:var(--danger);">${_esc(err.message||'Error')}</p>`;}
  }

  async function _openSvcModal(id) {
    _q('#svcEditModal').hidden=false; _q('#svcEditModalTitle').textContent=id?'Edit Service':'New Service'; _q('#svcFormId').value=id||'';
    const map={name:'svcFormName',description:'svcFormDesc',tier:'svcFormTier',status:'svcFormStatus',owner:'svcFormOwner',team:'svcFormTeam',doc_url:'svcFormDocUrl',health_url:'svcFormHealthUrl'};
    if(id){try{const s=await _api(`/services/${id}`);Object.entries(map).forEach(([k,eid])=>{const el=_q('#'+eid);if(el&&s[k]!=null)el.value=s[k];});}catch(_){}}
    else{Object.values(map).forEach(eid=>{const el=_q('#'+eid);if(el)el.value=''});}
  }

  async function _saveSvc() {
    const id=_q('#svcFormId').value;
    const body={name:_q('#svcFormName').value,description:_q('#svcFormDesc').value,tier:_q('#svcFormTier').value,
      status:_q('#svcFormStatus').value,owner:_q('#svcFormOwner').value,team:_q('#svcFormTeam').value,
      doc_url:_q('#svcFormDocUrl').value||null,health_url:_q('#svcFormHealthUrl').value||null};
    try{await _api(id?`/services/${id}`:'/services',id?'PATCH':'POST',body);_q('#svcEditModal').hidden=true;_loadSvcStats();_loadServices();}
    catch(err){alert('Save failed: '+(err.message||err));}
  }

  async function _doSvcStatus() {
    const status=_q('#svcStatusSelect').value; const reason=_q('#svcStatusReason').value; const changed_by=_q('#svcStatusAuthor').value; if(!status) return;
    try{await _api(`/services/${_svcCurrentId}/status`,'POST',{status,reason,changed_by});_q('#svcStatusModal').hidden=true;_svcOpenDetail(_svcCurrentId);_loadSvcStats();_loadServices();}
    catch(err){alert('Failed: '+(err.message||err));}
  }

  // ── Problem Management ────────────────────────────────────────────────────────
  let _prOffset=0; const _PR_LIMIT=50; let _prCurrentId=null;

  function initProblemsView() {
    _loadPrStats(); _loadProblems();
    _q('#prAddBtn').onclick     = () => _openPrModal();
    _q('#prRefreshBtn').onclick = () => { _loadPrStats(); _loadProblems(); };
    _q('#prSearchBtn').onclick  = () => { _prOffset=0; _loadProblems(); };
    _q('#prSearchInput').onkeydown = e => { if(e.key==='Enter'){_prOffset=0;_loadProblems();} };
    _q('#prStatusFilter').onchange   = () => { _prOffset=0; _loadProblems(); };
    _q('#prPriorityFilter').onchange = () => { _prOffset=0; _loadProblems(); };
    _q('#prEditModalClose').onclick  = () => { _q('#prEditModal').hidden=true; };
    _q('#prEditModalCancel').onclick = () => { _q('#prEditModal').hidden=true; };
    _q('#prEditForm').onsubmit = e => { e.preventDefault(); _savePr(); };
    _q('#prDetailModalClose').onclick    = () => { _q('#prDetailModal').hidden=true; };
    _q('#prDetailModalCloseBtn').onclick = () => { _q('#prDetailModal').hidden=true; };
    _q('#prDetailEditBtn').onclick    = () => { if(_prCurrentId) _openPrModal(_prCurrentId); };
    _q('#prTransitionBtn').onclick    = () => { if(_prCurrentId) _openPrTransModal(); };
    _q('#prLinkIncidentBtn').onclick  = () => { if(_prCurrentId) { _q('#prLinkIncidentModal').hidden=false; _q('#prLinkIncidentForm').reset(); } };
    _q('#prAddTimelineBtn').onclick   = () => { if(_prCurrentId) { _q('#prTimelineModal').hidden=false; _q('#prTimelineForm').reset(); } };
    _q('#prTransitionModalClose').onclick  = () => { _q('#prTransitionModal').hidden=true; };
    _q('#prTransitionModalCancel').onclick = () => { _q('#prTransitionModal').hidden=true; };
    _q('#prTransitionForm').onsubmit = e => { e.preventDefault(); _doPrTransition(); };
    _q('#prLinkIncidentModalClose').onclick  = () => { _q('#prLinkIncidentModal').hidden=true; };
    _q('#prLinkIncidentModalCancel').onclick = () => { _q('#prLinkIncidentModal').hidden=true; };
    _q('#prLinkIncidentForm').onsubmit = e => { e.preventDefault(); _linkPrIncident(); };
    _q('#prTimelineModalClose').onclick  = () => { _q('#prTimelineModal').hidden=true; };
    _q('#prTimelineModalCancel').onclick = () => { _q('#prTimelineModal').hidden=true; };
    _q('#prTimelineForm').onsubmit = e => { e.preventDefault(); _addPrTimeline(); };
  }

  async function _loadPrStats() {
    try {
      const s=await _api('/problems/stats');
      const strip=_q('#prStatsStrip');
      strip.innerHTML=`<div class="ops-stats-strip">${[['Total',s.total],['Open',s.open||0],['In Analysis',s.in_analysis||0],['Resolved',s.resolved||0]].map(([l,v])=>
        `<div class="ops-stat-card"><span class="ops-stat-value">${v||0}</span><span class="ops-stat-label">${l}</span></div>`).join('')}</div>`;
    } catch(_) {}
  }

  async function _loadProblems() {
    const q=_q('#prSearchInput').value.trim(); const status=_q('#prStatusFilter').value; const priority=_q('#prPriorityFilter').value;
    const params=new URLSearchParams({limit:_PR_LIMIT,offset:_prOffset});
    if(q) params.set('q',q); if(status) params.set('status',status); if(priority) params.set('priority',priority);
    const tbody=_q('#prListTbody');
    tbody.innerHTML='<tr><td colspan="6" class="ops-table-state">Loading...</td></tr>';
    try {
      const data=await _api(`/problems?${params}`); const rows=data.problems||[];
      _q('#prListCount').textContent=`${data.total} total`;
      if(!rows.length){tbody.innerHTML='<tr><td colspan="6" class="ops-table-state">No problems found.</td></tr>';return;}
      tbody.innerHTML=rows.map(r=>`<tr class="ops-row-link" onclick="_openPrDetail('${r.id}')">
        <td><strong>${_esc(r.title||'')}</strong></td><td>${_esc(r.category||'')}</td>
        <td><span class="badge ${r.priority==='critical'?'bad':r.priority==='high'?'warn':'ok'}">${_esc(r.priority||'')}</span></td>
        <td><span class="badge">${_esc(r.status||'')}</span></td><td>${_esc(r.owner||'')}</td>
        <td><button class="btn xs" onclick="event.stopPropagation();_openPrModal('${r.id}')">Edit</button></td>
      </tr>`).join('');
      const pages=Math.ceil(data.total/_PR_LIMIT)||1; const page=Math.floor(_prOffset/_PR_LIMIT)+1;
      _q('#prPagination').innerHTML=`<button class="btn xs" ${_prOffset===0?'disabled':''} onclick="_prOffset=Math.max(0,_prOffset-${_PR_LIMIT});_loadProblems()">Prev</button>
        <span class="ops-pagination-label">Page ${page}/${pages}</span>
        <button class="btn xs" ${_prOffset+_PR_LIMIT>=data.total?'disabled':''} onclick="_prOffset+=_PR_LIMIT;_loadProblems()">Next</button>`;
    } catch(err){tbody.innerHTML=`<tr><td colspan="6" class="ops-table-state ops-table-state-danger">${_esc(err.message||'Error')}</td></tr>`;}
  }

  async function _openPrDetail(id) {
    _prCurrentId=id; _q('#prDetailModal').hidden=false; _q('#prDetailModalBody').innerHTML='Loading...';
    try {
      const p=await _api(`/problems/${id}`);
      _q('#prDetailModalTitle').textContent=p.title||'Problem';
      const [tlData]=await Promise.all([_api(`/problems/${id}/timeline`)]);
      const tl=(tlData.timeline||[]).slice(0,8);
      const allowed={open:['in_analysis','closed'],in_analysis:['known_error','closed'],known_error:['in_fix','closed'],in_fix:['resolved','closed'],resolved:[],closed:[]};
      _q('#prTransitionStatus').innerHTML=(allowed[p.status]||[]).map(s=>`<option value="${s}">${s}</option>`).join('')||'<option value="">No transitions</option>';
      _q('#prDetailModalBody').innerHTML=`<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:13px;">
        <div><b>Priority</b><br>${_esc(p.priority||'')}</div><div><b>Status</b><br>${_esc(p.status||'')}</div>
        <div><b>Category</b><br>${_esc(p.category||'')}</div><div><b>Owner</b><br>${_esc(p.owner||'—')}</div>
      </div>
      ${p.description?`<p style="margin-top:8px;font-size:13px;">${_esc(p.description)}</p>`:''}
      ${p.root_cause?`<p style="font-size:13px;"><b>Root Cause:</b> ${_esc(p.root_cause)}</p>`:''}
      ${p.workaround?`<p style="font-size:13px;"><b>Workaround:</b> ${_esc(p.workaround)}</p>`:''}
      <h4 style="margin:12px 0 4px;">Timeline</h4>
      <div>${tl.map(e=>`<div style="font-size:12px;padding:2px 0;border-bottom:1px solid var(--border);">${(e.created_at||'').slice(0,16)} <strong>${_esc(e.event_type||'')}</strong> ${_esc(e.note||'')} <em style="color:var(--text-muted);">${_esc(e.author||'')}</em></div>`).join('')||'<span style="color:var(--text-muted);">No timeline</span>'}</div>`;
    } catch(err){_q('#prDetailModalBody').innerHTML=`<p style="color:var(--danger);">${_esc(err.message||'Error')}</p>`;}
  }

  async function _openPrModal(id) {
    _q('#prEditModal').hidden=false; _q('#prEditModalTitle').textContent=id?'Edit Problem':'New Problem'; _q('#prFormId').value=id||'';
    const map={title:'prFormTitle',description:'prFormDesc',priority:'prFormPriority',category:'prFormCategory',owner:'prFormOwner',assignee:'prFormAssignee',root_cause:'prFormRootCause',workaround:'prFormWorkaround',linked_change_id:'prFormLinkedChange'};
    if(id){try{const p=await _api(`/problems/${id}`);Object.entries(map).forEach(([k,eid])=>{const el=_q('#'+eid);if(el&&p[k]!=null)el.value=p[k];});}catch(_){}}
    else{Object.values(map).forEach(eid=>{const el=_q('#'+eid);if(el)el.value=''});}
  }

  async function _savePr() {
    const id=_q('#prFormId').value;
    const body={title:_q('#prFormTitle').value,description:_q('#prFormDesc').value,priority:_q('#prFormPriority').value,
      category:_q('#prFormCategory').value,owner:_q('#prFormOwner').value,assignee:_q('#prFormAssignee').value,
      root_cause:_q('#prFormRootCause').value,workaround:_q('#prFormWorkaround').value,
      linked_change_id:_q('#prFormLinkedChange').value||null};
    try{await _api(id?`/problems/${id}`:'/problems',id?'PATCH':'POST',body);_q('#prEditModal').hidden=true;_loadPrStats();_loadProblems();}
    catch(err){alert('Save failed: '+(err.message||err));}
  }

  async function _openPrTransModal() { _q('#prTransitionModal').hidden=false; }

  async function _doPrTransition() {
    const status=_q('#prTransitionStatus').value; const note=_q('#prTransitionNote').value; if(!status) return;
    try{await _api(`/problems/${_prCurrentId}/transition`,'POST',{status,note});_q('#prTransitionModal').hidden=true;_openPrDetail(_prCurrentId);_loadPrStats();_loadProblems();}
    catch(err){alert('Transition failed: '+(err.message||err));}
  }

  async function _linkPrIncident() {
    const incident_id=_q('#prLinkIncidentId').value.trim(); if(!incident_id) return;
    try{await _api(`/problems/${_prCurrentId}/incidents`,'POST',{incident_id});_q('#prLinkIncidentModal').hidden=true;_openPrDetail(_prCurrentId);}
    catch(err){alert('Failed: '+(err.message||err));}
  }

  async function _addPrTimeline() {
    const body={event_type:_q('#prTimelineEventType').value,note:_q('#prTimelineNote').value,author:_q('#prTimelineAuthor').value};
    try{await _api(`/problems/${_prCurrentId}/timeline`,'POST',body);_q('#prTimelineModal').hidden=true;_openPrDetail(_prCurrentId);}
    catch(err){alert('Failed: '+(err.message||err));}
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
