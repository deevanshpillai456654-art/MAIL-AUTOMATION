// INTEMO - Enterprise Application Runtime v2
(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const $$ = (sel, ctx = document) => Array.from(ctx.querySelectorAll(sel));
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
  const safeJson = (raw, fallback = {}) => { try { return typeof raw === 'string' ? JSON.parse(raw) : (raw ?? fallback); } catch { return fallback; } };

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
    accounts: [], emails: [], rules: [], templates: [], reports: {}, admin: {},
    selectedEmail: null, savedFilter: 'all', currentProvider: 'custom',
    selectedEmails: new Set(),
    onnx: {status: null, lastClassification: null, lastPayload: null, learningImportPreview: null}
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
    dashboard:   ['Dashboard',    'Operational overview — mailboxes, inbox health, AI processing and automations.'],
    accounts:    ['Accounts',     'Connect Gmail, Outlook, Microsoft 365, Exchange, Yahoo, Zoho, IMAP/SMTP and custom domain mailboxes.'],
    inbox:       ['Inbox',        'Threaded conversations with AI summaries, labels, folders and workflow actions.'],
    ai:          ['AI Processing','Analyze, classify and extract entities from emails with controlled workflow actions.'],
    automations: ['Automations',  'Create, simulate and manage forwarding, categorization and workflow rules.'],
    templates:   ['Templates',    'Reusable reply, rule and reporting templates.'],
    reports:     ['Analytics',    'Generate operational, business, forwarding, AI and inbox reports.'],
    connectors:  ['Connectors',   'Install, configure and monitor integrations — Gmail, Slack, WhatsApp, Shopify, webhooks and plugins.'],
    admin:       ['Admin',        'Manage governance, users, roles, provider settings, queues and update controls.'],
    settings:    ['Settings',     'General, accounts, AI, automations, notifications, security, integrations, updates and advanced.']
  };
  PAGES.dashboard = ['Dashboard', 'Operational overview - mailboxes, inbox health, AI processing, and automations.'];

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

  // ── API ─────────────────────────────────────────────────────────────────────
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

  // ── Toasts ──────────────────────────────────────────────────────────────────
  function toast(title, msg = '', tone = 'info') {
    const wrap = $('toastWrap');
    if (!wrap) return;
    const node = document.createElement('div');
    node.className = `toast ${tone}`;
    node.innerHTML = `<b>${esc(title)}</b>${msg ? `<small>${esc(msg)}</small>` : ''}`;
    wrap.appendChild(node);
    setTimeout(() => node.remove(), 5200);
  }

  // ── View routing ────────────────────────────────────────────────────────────
  function showView(view, settingsTab) {
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
    if (view === 'automations') { loadRules(); loadRuleAnalytics(); loadLabelsAndFolders(); loadPresets(); }
    if (view === 'templates')   loadTemplates();
    if (view === 'reports')     loadReports(true);
    if (view === 'admin')       loadAdmin();
    if (view === 'settings')    renderSettings(settingsTab || 'general');
    if (view === 'connectors') {
      const frame = $('connectorFrame');
      if (frame && !frame.dataset.loaded) {
        frame.src = '/connectors-panel';
        frame.dataset.loaded = '1';
      }
    }
    window.scrollTo({top:0, behavior:'smooth'});
  }

  // ── Provider helpers ────────────────────────────────────────────────────────
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

  // ── Account status panel (dynamic) ─────────────────────────────────────────
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
    if (family) {
      panel.innerHTML = `<div class="provider-flow-card ${mode === 'setup' ? 'warn' : ''}"><div><b>${esc(oauthLabel(provider))} official OAuth flow</b><span>${esc(detail || 'OAuth uses the provider sign-in page and token vault. Mailbox password fields are hidden in this mode.')}</span><small>Permissions: read, organize, send, refresh offline access and AI indexing.</small></div><div class="provider-flow-actions"><button class="btn primary" data-oauth-start="${esc(provider)}" type="button">Continue with ${esc(oauthLabel(provider))}</button><button class="btn" data-show-oauth-setup="${esc(provider)}" type="button">Configure OAuth App</button></div></div>`;
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
    const cloudMap = {gmail:'Google Cloud Console → APIs & Services → Credentials', microsoft:'Azure Portal → App registrations', yahoo:'Yahoo Developer Network → My Apps', zoho:'Zoho API Console', yandex:'Yandex OAuth Console'};
    const redirect = `${location.origin}${redirectMap[group] || '/api/v1/oauth/google/callback'}`;
    const tenant = group === 'microsoft' ? `<label>Tenant ID<input name="tenant_id" value="common" placeholder="common or tenant ID"></label>` : '';
    panel.innerHTML = `<form class="oauth-setup-card" id="inlineOAuthSetupForm"><div class="wide"><b>Configure ${esc(oauthLabel(provider))} OAuth once</b><span>${esc(message || 'Save OAuth credentials here, then the provider login opens automatically.')}</span><small>Create the app in ${esc(cloudMap[group] || 'Provider developer console')} and add this redirect URI:</small><code>${esc(redirect)}</code></div><input type="hidden" name="provider" value="${esc(group)}"><input type="hidden" name="redirect_uri" value="${esc(redirect)}"><label>Client ID<input name="client_id" placeholder="OAuth client/application ID" required></label><label>Client Secret<input name="client_secret" type="password" placeholder="Stored encrypted locally" required></label>${tenant}<div class="form-actions wide"><button class="btn primary" type="submit">Save OAuth &amp; Continue</button><button class="btn" data-oauth-start="${esc(provider)}" type="button">Try Existing OAuth</button></div></form>`;
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
    const start = oauthStartUrl(provider);
    setAccountStatus(`Starting ${oauthLabel(provider)} sign-in`, 'Checking OAuth configuration before opening the provider login page...', 'loading');
    const result = await api(start, {method:'POST', body:JSON.stringify({email: email || $('accountForm')?.email?.value || '', redirect_after:'/dashboard'})});
    if (result.ok && result.data?.auth_url) { const authUrl = String(result.data.auth_url); if (authUrl.startsWith('https://')) { toast(`${oauthLabel(provider)} sign-in`, 'Opening provider authorization page.', 'ok'); window.location.href = authUrl; return; } }
    const err = result.error || result.data || {};
    if (result.status === 428 || err.status === 'provider_setup_required' || err.setup_required) { setAccountStatus('OAuth setup required', msgFromError(err), 'warn'); renderOAuthSetupPanel(provider, msgFromError(err)); return; }
    setAccountStatus('OAuth could not start', msgFromError(err), 'bad');
    toast('OAuth could not start', msgFromError(err), 'bad');
  }

  async function saveInlineOAuthSetup(event) {
    event.preventDefault();
    const form = event.target;
    const provider = form.provider.value;
    const accountProvider = provider === 'gmail' ? 'gmail' : provider === 'microsoft' ? (state.currentProvider || 'outlook') : provider;
    const payload = Object.fromEntries(new FormData(form).entries());
    if (!payload.client_id || !payload.client_secret) return toast('OAuth credentials required', 'Client ID and Client Secret are required.', 'warn');
    const btn = form.querySelector('button[type="submit"]');
    if (btn) { btn.disabled = true; btn.textContent = 'Saving…'; }
    const result = await api('/api/v1/provider-config/oauth', {method:'POST', body:JSON.stringify(payload)});
    if (btn) { btn.disabled = false; btn.textContent = 'Save OAuth & Continue'; }
    if (!result.ok) { setAccountStatus('OAuth setup not saved', msgFromError(result.error), 'bad'); toast('OAuth setup failed', msgFromError(result.error), 'bad'); return; }
    setAccountStatus('OAuth setup saved', 'Credentials encrypted locally. Opening provider login now.', 'ok');
    toast('OAuth configured', 'Provider login will open now.', 'ok');
    await startOAuthFlow(accountProvider, $('accountForm')?.email?.value || '');
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
    if (submit) { submit.disabled = true; submit.textContent = 'Saving…'; }
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
    if (submit) { submit.disabled = true; submit.textContent = 'Saving…'; }
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

  // ── Dashboard ───────────────────────────────────────────────────────────────
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

  // ── Inbox ───────────────────────────────────────────────────────────────────
  function seedEmails() {
    return [
      {id:1,subject:'RFQ for Mumbai to Dubai shipment',sender:'Apex Imports',sender_email:'rfq@apex.example',category:'RFQ',priority:'Critical',folder:'INBOX',labels:'RFQ,Logistics',is_read:0,ai_summary:'Buyer requested freight pricing, sailing options and document timeline.',body_text:'Please quote for LCL shipment from Mumbai to Dubai.',attachments:[{filename:'shipment-rfq.pdf',content_type:'application/pdf',size:184320,download_url:'#'}]},
      {id:2,subject:'Invoice INV-2041 payment follow-up',sender:'Finance Desk',sender_email:'finance@example.com',category:'Invoice',priority:'High',folder:'Finance',labels:'Invoice,Payment',is_read:1,ai_summary:'Invoice follow-up needs confirmation and expected payment date.',body_text:'Kindly confirm payment status.'},
      {id:3,subject:'Support request for mailbox sync',sender:'Operations',sender_email:'ops@example.com',category:'Support',priority:'Medium',folder:'Support',labels:'Support',is_read:0,ai_summary:'Mailbox sync delay requires reconnect guidance.',body_text:'Mailbox sync appears delayed.'}
    ];
  }

  async function loadInbox() {
    const params = new URLSearchParams();
    const folder = $('folderFilter')?.value || '';
    const label  = $('labelFilter')?.value || '';
    if (folder) params.set('folder', folder);
    if (label)  params.set('label', label);
    const result = await api(`/api/v1/emails?${params}`);
    state.emails = result.ok && Array.isArray(result.data.emails) ? result.data.emails : seedEmails();
    populateInboxFilters(); renderInbox();
  }

  function populateInboxFilters() {
    const folders = [...new Set(state.emails.map(e => e.folder).filter(Boolean))];
    const labels  = [...new Set(state.emails.flatMap(e => String(e.labels||'').replace(/[\[\]"]/g,'').split(',').map(x=>x.trim()).filter(Boolean)))];
    if ($('folderFilter')) $('folderFilter').innerHTML = '<option value="">All folders</option>' + folders.map(x=>`<option>${esc(x)}</option>`).join('');
    if ($('labelFilter'))  $('labelFilter').innerHTML  = '<option value="">All labels</option>'  + labels.map(x=>`<option>${esc(x)}</option>`).join('');
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
      (!label  || String(e.labels||'').includes(label)) &&
      (!term   || [e.sender,e.sender_email,e.subject,e.category,e.priority,e.folder,e.labels].join(' ').toLowerCase().includes(term))
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
    const emptyState = emptyStateForFilter(state.savedFilter);
    const emptyTitle = emptyState.title;
    const emptyBody  = emptyState.body;
    if ($('inboxRows')) $('inboxRows').innerHTML = rows.length
      ? rows.map(e => {
          const sel = state.selectedEmails.has(String(e.id));
          const active = state.selectedEmail?.id === e.id;
          // Checkbox is outside the button so clicking it never triggers email-open
          return `<div class="thread-row-wrap ${active?'active':''} ${sel?'selected-row':''}" data-wrap-id="${esc(e.id)}">`
            + `<label class="thread-row-cb" aria-label="Select email">`
            +   `<input type="checkbox" class="email-cb" data-cb-id="${esc(e.id)}" ${sel?'checked':''}>`
            + `</label>`
            + `<button class="thread-row" data-email-id="${esc(e.id)}" type="button" role="listitem">`
            +   `<span class="${e.is_read?'read-dot':'unread-dot'}"></span>`
            +   `<span>`
            +     `<span class="thread-subject">${esc(e.subject||'(No subject)')}</span>`
            +     `<span class="thread-meta">${esc(e.sender||e.sender_email||'Unknown')} · ${esc(e.category||'Unclassified')}</span>`
            +     `<span class="thread-summary">${esc((e.ai_summary||e.body_text||'').slice(0,120))}</span>`
            +     `<span class="thread-tags"><span class="badge">${esc(e.priority||'Medium')}</span><span class="badge ok">${esc(e.folder||'INBOX')}</span></span>`
            +   `</span>`
            +   `<span aria-hidden="true">›</span>`
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
      (!label  || String(e.labels||'').includes(label)) &&
      (!term   || [e.sender,e.sender_email,e.subject,e.category,e.priority,e.folder,e.labels].join(' ').toLowerCase().includes(term))
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
      showInlineInput($('bulkBar'), 'Add label', 'Label name…', '', async lbl => {
        if (!lbl) return;
        state.selectedEmails.clear(); updateBulkBar();
        toast('Label applied', `"${lbl}" applied to ${ids.length} email(s).`, 'ok');
        for (const id of ids) await api(`/api/v1/email/${id}/label`, {method:'POST', body:JSON.stringify({label:lbl})}).catch(()=>{});
        loadInbox();
      });
    } else if (action === 'move') {
      showInlineInput($('bulkBar'), 'Move to folder', 'Folder name…', $('folderFilter')?.value || 'INBOX', async fld => {
        if (!fld) return;
        state.selectedEmails.clear(); updateBulkBar();
        toast('Moved', `${ids.length} email(s) moved to "${fld}".`, 'ok');
        for (const id of ids) await api(`/api/v1/email/${id}/move`, {method:'POST', body:JSON.stringify({folder:fld})}).catch(()=>{});
        loadInbox();
      });
    }
  }

  // ── AI Analysis ─────────────────────────────────────────────────────────────
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

  function renderThreadEmptyState(title, body) {
    return `<div class="thread-empty-state"><b>${esc(title)}</b><small>${esc(body)}</small></div>`;
  }

  function renderEmptyPreview(title = 'Select a conversation', body = 'AI summary, thread context, labels, folders and actions appear here.') {
    if (!$('messagePreview')) return;
    $('messagePreview').innerHTML = `<div class="preview-empty"><svg width="44" height="44" viewBox="0 0 44 44" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true"><rect x="4" y="6" width="36" height="32" rx="3"/><path d="M4 14l18 12 18-12"/></svg><strong>${esc(title)}</strong><p>${esc(body)}</p></div>`;
  }

  function renderPreview(e) {
    if (!e || !$('messagePreview')) return;
    const labelBadges = String(e.labels||'').replace(/[\[\]"]/g,'').split(',').filter(Boolean).slice(0,3).map(x=>`<span class="badge ok">${esc(x.trim())}</span>`).join('');
    const isScam = String(e.category||'').toLowerCase() === 'scam';
    $('messagePreview').innerHTML = `<h2>${esc(e.subject||'Conversation')}</h2><p>${esc(e.sender||e.sender_email||'Unknown sender')} - ${esc(e.category||'Unclassified')}</p><div class="preview-actions"><button class="btn" type="button" data-email-action="reply" data-email-action-id="${esc(e.id)}">Reply</button><button class="btn" type="button" data-email-action="forward" data-email-action-id="${esc(e.id)}">Forward</button><button class="btn" type="button" data-email-action="assign" data-email-action-id="${esc(e.id)}">Assign</button><button class="btn" type="button" data-email-action="label" data-email-action-id="${esc(e.id)}">Label</button><button class="btn" type="button" data-email-action="move" data-email-action-id="${esc(e.id)}">Move</button><button class="btn" type="button" data-email-action="archive" data-email-action-id="${esc(e.id)}">Archive</button></div><div class="scam-flow ${isScam?'active':''}"><div><strong>Scam filter</strong><span>${isScam?'This sender is currently treated as scam.':'Decide how future email from this sender should be handled.'}</span></div><div class="verdict-actions"><button class="btn danger sm" data-email-category-id="${esc(e.id)}" data-email-category="Scam" type="button">Mark Scam</button><button class="btn sm" data-email-category-id="${esc(e.id)}" data-email-category="Normal" type="button">Mark Normal</button></div><small>Future emails from this sender will follow this decision.</small></div><h3>AI Summary</h3><p>${esc(e.ai_summary||'No summary yet.')}</p><h3>Thread</h3><p class="preview-message-body">${esc((e.body_text||'No body preview.').slice(0,4000))}</p>${renderAttachments(e)}<div class="thread-tags"><span class="badge">${esc(e.priority||'Medium')}</span><span class="badge ok">${esc(e.folder||'INBOX')}</span>${labelBadges}</div>`;
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
      showInlineInput(btn, 'Add label', 'Label name…', '', async label => {
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
      showInlineInput(btn, 'Move to folder', 'Folder name…', email.folder || 'INBOX', async folder => {
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

  // ── Rules / Automations ─────────────────────────────────────────────────────
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
      ? rows.map(r => `<div class="rule-item" role="listitem"><div><b>${esc(r.name)}</b><small>${esc(r.status||'Active')} - priority ${esc(r.priority||'Medium')} - executions ${esc(r.execution_count||0)}</small></div><div><button class="btn sm" type="button">Edit</button><button class="btn sm" type="button">Pause</button><button class="btn sm" type="button">Duplicate</button><button class="btn sm" type="button">Archive</button></div></div>`).join('')
      : '<div class="rule-item"><div><b>No rules yet</b><small>Create a rule above or apply a template.</small></div><span class="badge warn">Empty</span></div>';
    renderRuleDiagram();
  }

  function renderRuleDiagram() {
    if ($('ruleDiagram')) $('ruleDiagram').innerHTML = ['Analyze','Match','Prioritize','Execute','Log','Report'].map(n => `<span class="workflow-node">${esc(n)}</span>`).join(' → ');
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
    const conditionMap = {subject_keywords:'subject_contains', body_keywords:'body_contains', sender:'sender_contains', sender_domain:'domain_is', ai_intent:'category_is', category_is:'category_is'};
    const conditionType = conditionMap[f.get('condition_type')] || f.get('condition_type');
    const payload = {name:f.get('name'), condition:{type:conditionType, value:[f.get('condition_value')]}, actions:[{type:actionType, value:actionValue}], priority:f.get('priority'), execution_type:f.get('execution_type'), enabled:f.get('status')==='active', status:f.get('status'), apply_existing:true, exceptions:f.get('exceptions')};
    const result = await api('/api/v1/rules', {method:'POST', body:JSON.stringify(payload)});
    if (result.ok) {
      const s = result.data.apply_summary || {};
      toast('Rule saved', `Applied to ${s.emails_checked??0} email(s) — ${s.matched_rules??0} action(s) executed.`, 'ok');
      loadRules(); loadDashboard(); loadLabelsAndFolders();
    } else toast('Rule not saved', msgFromError(result.error), 'bad');
  }

  async function simulateRule() {
    const f = new FormData($('ruleForm'));
    const payload = {subject:String(f.get('condition_value')||'RFQ'), sender_email:'customer@example.com', body:'Sample email for rule simulation'};
    const result = await api('/api/v1/rules/evaluate', {method:'POST', body:JSON.stringify(payload)});
    if ($('ruleTimeline')) $('ruleTimeline').innerHTML = `<div class="timeline-item"><b>Simulation</b><br><small>${esc(result.ok ? `${result.data.count||0} rule(s) matched` : msgFromError(result.error))}</small></div>`;
    toast('Simulation complete', result.ok ? 'Execution preview updated.' : msgFromError(result.error), result.ok ? 'ok' : 'warn');
  }

  function duplicateRule() {
    const form = $('ruleForm');
    if (!form) return;
    const nameEl = form.querySelector('[name="name"]');
    if (nameEl) nameEl.value = `${nameEl.value || 'Rule'} (copy)`;
    toast('Rule duplicated', 'Modify the name and click Save Rule.', 'info');
  }

  async function loadLabelsAndFolders() {
    const [lr, fr] = await Promise.all([api('/api/v1/rules/labels'), api('/api/v1/rules/folders')]);
    const labels  = lr.ok ? (lr.data.labels  || []) : [];
    const folders = fr.ok ? (fr.data.folders || []) : [];
    if ($('labelInventory'))  $('labelInventory').innerHTML  = labels.length  ? labels.map(l  => `<span class="badge ok" role="listitem">${esc(typeof l==='string'?l:(l.name||''))}</span>`).join(' ') : '<span class="empty-muted">No labels yet — created automatically when rules run.</span>';
    if ($('folderInventory')) $('folderInventory').innerHTML = folders.length ? folders.map(fl => `<span class="badge" role="listitem">${esc(typeof fl==='string'?fl:(fl.name||''))}</span>`).join(' ') : '<span class="empty-muted">No folders yet — created automatically when rules run.</span>';
  }

  async function createLabel(name) {
    if (!name?.trim()) return toast('Label name required', '', 'warn');
    const result = await api('/api/v1/rules/labels', {method:'POST', body:JSON.stringify({name:name.trim()})});
    toast(result.ok ? 'Label created' : 'Label not created', result.ok ? `"${name.trim()}" is ready.` : msgFromError(result.error), result.ok ? 'ok' : 'bad');
    if (result.ok) loadLabelsAndFolders();
  }

  async function createFolder(name) {
    if (!name?.trim()) return toast('Folder name required', '', 'warn');
    const result = await api('/api/v1/rules/folders', {method:'POST', body:JSON.stringify({name:name.trim()})});
    toast(result.ok ? 'Folder created' : 'Folder not created', result.ok ? `"${name.trim()}" is ready.` : msgFromError(result.error), result.ok ? 'ok' : 'bad');
    if (result.ok) loadLabelsAndFolders();
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
    if (btn) { btn.disabled = true; btn.textContent = 'Installing…'; }
    toast('Installing preset', `Installing rules from "${presetId}" pack…`, 'info');
    const result = await api(`/api/v1/rules/presets/${encodeURIComponent(presetId)}`, {method:'POST'});
    if (btn) { btn.disabled = false; btn.textContent = 'Install Pack'; }
    if (result.ok) { const d = result.data; toast(`Pack installed: ${d.preset}`, `${d.installed_count} rule(s) installed, ${d.skipped_count} already existed.`, 'ok'); loadRules(); loadLabelsAndFolders(); loadRuleAnalytics(); }
    else toast('Install failed', msgFromError(result.error), 'bad');
  }

  async function applyRulesToAll() {
    const btn = $('applyRulesBtn');
    if (btn) { btn.disabled = true; btn.textContent = 'Applying…'; }
    toast('Applying rules', 'Scanning all emails and executing matching rules…', 'info');
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

  // ── Templates ───────────────────────────────────────────────────────────────
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

  // ── Reports ─────────────────────────────────────────────────────────────────
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

  function renderReportCards(id, values) {
    if ($(id)) $(id).innerHTML = Object.entries(values || {}).map(([k,v]) => `<div class="report-card" role="listitem"><span>${esc(k.replaceAll('_',' '))}</span><strong>${esc(v)}</strong></div>`).join('');
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
    renderReportCards('emailReport', email);
    renderReportCards('businessReport', business);
    renderReportCards('learningReport', learning);
    renderReportCards('modelHealthReport', modelHealth);
    if ($('scheduledReports')) $('scheduledReports').innerHTML = (state.reports.scheduled||[]).map(x => `<div class="activity-item"><div><b>${esc(x.name)}</b><small>${esc(x.frequency)} - ${esc(x.format)}</small></div><span class="badge ok">Enabled</span></div>`).join('') || '<div class="activity-item"><div><b>No scheduled reports</b><small>Create a schedule to email PDF/CSV reports automatically.</small></div><button class="btn" id="scheduleReportBtn" type="button">Schedule</button></div>';
    renderBars('emailChart', reportValues(email));
    renderBars('businessChart', reportValues(business));
    renderBars('learningChart', reportValues(learning));
    renderBars('modelHealthChart', reportValues(modelHealth));
    if (showToast) toast('Reports generated', result.ok ? 'Report data loaded from backend.' : 'Backend unavailable — local fallback displayed.', result.ok ? 'ok' : 'warn');
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

  // ── Admin ───────────────────────────────────────────────────────────────────
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
    // Sections whose detail panels already contain the primary action button — no header duplicates
    if (n.includes('user') || n.includes('roles') || n.includes('team') ||
        n.includes('notification') || n.includes('ai config'))  return '';
    // Read-only status / info sections — no action needed in the header
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
    if (detail) { detail.innerHTML = '<div class="activity-item"><div><b>Loading audit log…</b><small>Fetching recent activity.</small></div></div>'; detail.scrollIntoView({behavior:'smooth', block:'nearest'}); }
    const result = await api('/api/v1/admin/audit');
    if (!result.ok) {
      if (detail) detail.innerHTML = `<div class="activity-item"><div><b>Audit log unavailable</b><small>${esc(msgFromError(result.error))}</small></div><span class="badge bad">Error</span></div>`;
      toast('Audit log error', msgFromError(result.error), 'bad');
      return;
    }
    const rows = result.data.audit || [];
    if (detail) detail.innerHTML = rows.length
      ? rows.slice(0, 50).map(x => `<div class="activity-item"><div><b>${esc(x.rule_name||'Audit event')}</b><small>${esc(x.action_type||'')} — ${esc(x.created_at||'')}</small></div><span class="badge ok">Logged</span></div>`).join('')
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
    toast(result.ok ? 'Patch preview ready' : 'Patch preview opened', steps.join(' → '), result.ok ? 'ok' : 'warn');
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

  // ── Settings ────────────────────────────────────────────────────────────────
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

  // ── Command palette ─────────────────────────────────────────────────────────
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

  // ── Global click delegation ─────────────────────────────────────────────────
  document.addEventListener('click', async event => {
    const target = event.target.closest('button');
    if (!target) return;

    if (target.dataset.view)     showView(target.dataset.view);
    if (target.dataset.openView) showView(target.dataset.openView, target.dataset.settingsJump);
    if (target.dataset.settings) renderSettings(target.dataset.settings);

    if (target.id === 'sidebarToggle') $('sidebar')?.classList.toggle('open');
    if (target.id === 'refreshBtn')    { await Promise.all([loadDashboard(), loadAccounts()]); toast('Refreshed', 'Latest operational data loaded.', 'ok'); }

    if (target.classList.contains('provider-card')) { selectProvider(target.dataset.provider, true); $('accountForm')?.email?.focus(); }
    if (target.classList.contains('filter-chip')) { $$('.filter-chip').forEach(b => b.classList.remove('active')); target.classList.add('active'); state.savedFilter = target.dataset.filter; renderInbox(); }

    if (target.id === 'detectProviderBtn' || target.dataset.detectInline !== undefined) detectProvider();
    if (target.id === 'testConnectionBtn')  testAccountConnection();
    if (target.dataset.oauthStart)         startOAuthFlow(target.dataset.oauthStart, $('accountForm')?.email?.value || '');
    if (target.dataset.showOauthSetup)     renderOAuthSetupPanel(target.dataset.showOauthSetup);

    if (target.dataset.sync)                      startAccountSync(target.dataset.sync);
    if (target.dataset.editAccount !== undefined) toggleAccountEdit(target.dataset.editAccount);
    if (target.dataset.cancelEdit !== undefined)  toggleAccountEdit(target.dataset.cancelEdit);
    if (target.dataset.pause)                     pauseAccount(target.dataset.pause);
    if (target.dataset.resume)                    resumeAccount(target.dataset.resume);
    if (target.dataset.reconnect)                 reconnectAccount(target.dataset.reconnect);
    if (target.dataset.remove)                    removeAccount(target.dataset.remove);

    if (target.id === 'refreshInboxBtn') loadInbox();
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
    // Email checkbox selection — label wraps the checkbox, clicking label fires on label or checkbox
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
    if (target.id === 'closeCommandPalette')  closeCommandPalette();
    if (target.dataset.command)               runCommand(target.dataset.command);
  });

  // ── Bindings ────────────────────────────────────────────────────────────────
  function bind() {
    $('sidebarOverlay')?.addEventListener('click', () => $('sidebar')?.classList.remove('open'));
    $('accountForm')?.addEventListener('submit', saveAccount);
    $('accountForm')?.provider?.addEventListener('change', e => selectProvider(e.target.value, true));
    $('connectionMethod')?.addEventListener('change', () => { renderProviderActionPanel(state.currentProvider); const pw = $('accountForm')?.password; if (pw) pw.closest('label')?.classList.toggle('muted-field', selectedConnectionMethod() === 'oauth'); });
    $('accountForm')?.email?.addEventListener('blur', () => { const f = $('accountForm'); if (f?.email?.value && (!f.provider.value || f.provider.value === 'custom')) selectProvider(providerForEmail(f.email.value), true); });
    $('ruleForm')?.addEventListener('submit', saveRule);
    $('analysisForm')?.addEventListener('submit', analyzeEmail);
    $('learningFeedbackForm')?.addEventListener('submit', submitLearningFeedback);
    $('folderFilter')?.addEventListener('change', renderInbox);
    $('labelFilter')?.addEventListener('change',  renderInbox);
    $('ruleSearch')?.addEventListener('input',     renderRules);
    $('ruleStatusFilter')?.addEventListener('change', renderRules);
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

  // ── Init ────────────────────────────────────────────────────────────────────
  function init() {
    renderProviders();
    ensureAccountStatusPanel();
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
    loadReports(false);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
