// INTEMO setup wizard — extracted from setup.html so the page can run
// under a strict CSP (script-src 'self' 'nonce-...') without 'unsafe-inline'.
(function () {
  'use strict';

  const API = (location.origin && location.origin.startsWith('http')) ? location.origin : 'http://127.0.0.1:4597';
  let statusData = {};

  function escapeHtml(v) {
    return String(v ?? '').replace(/[&<>'"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[c]));
  }

  function toast(title, msg) {
    const el = document.createElement('div');
    el.className = 'toast';
    el.innerHTML = `<strong>${escapeHtml(title)}</strong><span>${escapeHtml(msg || '')}</span>`;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 5200);
  }

  let localSessionReady = null;
  async function ensureLocalSession() {
    if (!localSessionReady) {
      localSessionReady = fetch(API + '/api/v1/session/bootstrap', { method: 'POST', credentials: 'same-origin' }).catch(() => null);
    }
    await localSessionReady;
  }

  async function api(path, options = {}) {
    await ensureLocalSession();
    const res = await fetch(API + '/api/v1' + path, {
      ...options,
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    });
    const text = await res.text();
    let data = {};
    try { data = text ? JSON.parse(text) : {}; } catch { data = { raw: text }; }
    if (!res.ok) {
      const detail = data.detail || data.message || `HTTP ${res.status}`;
      throw new Error(typeof detail === 'string' ? detail : (detail.message || JSON.stringify(detail)));
    }
    return data;
  }

  async function loadStatus() {
    const apiTag = document.getElementById('apiTag');
    try {
      await api('/health');
      apiTag.textContent = 'Online';
      apiTag.className = 'tag good';
      document.getElementById('apiDetail').textContent = 'Local API is running at ' + API;
    } catch (e) {
      apiTag.textContent = 'Offline';
      apiTag.className = 'tag bad';
      document.getElementById('apiDetail').textContent = 'Start the service, then refresh.';
      return;
    }
    await loadHardeningStatus();
    statusData = await api('/provider-config/status');
    const oauthReady = Object.values(statusData.oauth_groups || {}).every(x => x.configured);
    document.getElementById('oauthTag').textContent = oauthReady ? 'Ready' : 'Setup required';
    document.getElementById('oauthTag').className = 'tag ' + (oauthReady ? 'good' : 'warn');
    renderStatus();
    selectProvider();
  }

  async function loadHardeningStatus() {
    const tag = document.getElementById('securityHardeningTag');
    const detail = document.getElementById('securityHardeningDetail');
    try {
      const d = await api('/security/local-runtime');
      const ok = d.status === 'passed';
      tag.textContent = ok ? 'Hardened' : 'Review';
      tag.className = 'tag ' + (ok ? 'good' : 'warn');
      detail.textContent = `Loopback: ${d.local_only.bind_host}. Windows Firewall: ${d.firewall.status}. Port ${d.firewall.port}.`;
    } catch (e) {
      tag.textContent = 'Review';
      tag.className = 'tag warn';
      detail.textContent = 'Security hardening check unavailable.';
    }
  }

  function renderStatus() {
    const rows = Object.values(statusData.oauth_groups || {})
      .map(s => `<div class="provider-row"><div><b>${escapeHtml(s.display_name || s.provider)}</b><div class="small">${escapeHtml(s.message)}<br>Redirect: ${escapeHtml(s.redirect_uri)}</div></div><span class="tag ${s.configured ? 'good' : 'warn'}">${s.configured ? 'Configured' : 'Missing'}</span></div>`)
      .join('');
    document.getElementById('statusList').innerHTML = rows || '<p class="small">No OAuth status available.</p>';
  }

  function selectProvider() {
    const p = document.getElementById('oauthProvider').value;
    const s = (statusData.oauth_groups || {})[p] || {};
    document.getElementById('tenantBox').style.display = p === 'microsoft' ? 'block' : 'none';
    document.getElementById('redirectUri').textContent = s.redirect_uri || (({
      gmail: API + '/api/v1/oauth/google/callback',
      microsoft: API + '/api/v1/oauth/microsoft/callback',
      yahoo: API + '/api/v1/oauth/yahoo/callback',
      zoho: API + '/api/v1/oauth/zoho/callback',
      yandex: API + '/api/v1/oauth/yandex/callback',
    }[p]) || API + '/api/v1/oauth/google/callback');
    const consoleUrl = String(s.cloud_console_url || '');
    document.getElementById('consoleLink').href = consoleUrl.startsWith('https://') ? consoleUrl : '#';
    document.getElementById('providerNotes').textContent = s.notes || '';
    document.getElementById('tenantId').value = s.tenant_id || 'common';
  }

  async function saveOAuth() {
    const provider = document.getElementById('oauthProvider').value;
    const payload = {
      provider,
      client_id: document.getElementById('clientId').value.trim(),
      client_secret: document.getElementById('clientSecret').value,
      tenant_id: document.getElementById('tenantId').value || 'common',
      redirect_uri: document.getElementById('redirectUri').textContent.trim(),
    };
    if (!payload.client_id || !payload.client_secret) {
      toast('Missing credentials', 'Client ID and Client Secret are required.');
      return;
    }
    try {
      await api('/provider-config/oauth', { method: 'POST', body: JSON.stringify(payload) });
      document.getElementById('clientSecret').value = '';
      toast('Provider saved', 'Credentials were encrypted locally. You can now connect this provider.');
      await loadStatus();
    } catch (e) {
      toast('Save failed', e.message);
    }
  }

  async function testOAuth() {
    const p = document.getElementById('oauthProvider').value;
    try {
      const startMap = {
        gmail: '/oauth/google/start',
        microsoft: '/oauth/microsoft/start',
        yahoo: '/oauth/yahoo/start',
        zoho: '/oauth/zoho/start',
        yandex: '/oauth/yandex/start',
      };
      const d = await api(startMap[p] || '/oauth/google/start', { method: 'POST' });
      if (d.auth_url) {
        const authUrl = String(d.auth_url);
        if (authUrl.startsWith('https://')) {
          toast('OAuth ready', 'Opening provider sign-in.');
          location.href = authUrl;
        }
      } else {
        toast('OAuth unavailable', d.message || 'Not configured');
      }
    } catch (e) {
      toast('OAuth unavailable', e.message);
    }
  }

  function attach(id, event, fn) {
    const el = document.getElementById(id);
    if (el) el.addEventListener(event, fn);
  }

  attach('setupRefreshBtn', 'click', loadStatus);
  attach('setupSaveOAuthBtn', 'click', saveOAuth);
  attach('setupTestOAuthBtn', 'click', testOAuth);
  attach('oauthProvider', 'change', selectProvider);

  loadStatus();
})();
