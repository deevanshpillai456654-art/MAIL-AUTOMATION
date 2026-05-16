(function () {
  'use strict';

  const platform = (document.documentElement.dataset.platform || 'extension').toLowerCase();
  AIOExtensionRuntime.configure(platform);

  const $ = id => document.getElementById(id);
  const br = () => globalThis.browser || globalThis.chrome;

  // ── status ────────────────────────────────────────────────────────────────
  function setStatus(ok, origin) {
    $('statusDot').className = `dot ${ok ? 'online' : 'offline'}`;
    $('statusText').textContent = ok ? 'Local service online' : 'Local service offline';
    $('originText').textContent = origin || 'No local service found';
  }

  // ── stats ─────────────────────────────────────────────────────────────────
  async function loadStats() {
    const res = await AIOExtensionBridge.sendToRuntime('AIO_GET_THREAT_STATS', { force: false });
    if (!res || !res.ok) return;
    const s = res.stats || {};
    $('statScam').textContent       = s.scam_emails_today   ?? s.critical_today   ?? '0';
    $('statSuspicious').textContent = s.suspicious_today    ?? s.suspicious_emails ?? '0';
    $('statTotal').textContent      = s.total_emails_today  ?? s.total_emails      ?? '—';
  }

  async function loadProviders() {
    try {
      const providers = await AIOExtensionRuntime.api('/providers');
      $('statProviders').textContent = String((providers.providers || []).length);
    } catch { $('statProviders').textContent = '—'; }
  }

  // ── recent threats ────────────────────────────────────────────────────────
  const LEVEL_COLORS = {
    scam:       { bg: '#fee2e2', color: '#991b1b', dot: '#ef4444' },
    suspicious: { bg: '#ffedd5', color: '#9a3412', dot: '#f97316' },
    review:     { bg: '#fef9c3', color: '#854d0e', dot: '#eab308' },
    clean:      { bg: '#dcfce7', color: '#166534', dot: '#22c55e' }
  };

  function scoreToLevel(score) {
    if (score <= 20) return 'clean';
    if (score <= 55) return 'review';
    if (score <= 80) return 'suspicious';
    return 'scam';
  }

  async function loadThreats() {
    const res = await AIOExtensionBridge.sendToRuntime('AIO_GET_RECENT_THREATS', { limit: 5 });
    if (!res || !res.ok) return;
    const items = res.items || [];
    $('threatCount').textContent = String(items.length);

    // FIX: always update visibility — hide on empty to clear stale content
    if (!items.length) {
      $('threatSection').classList.add('hidden');
      return;
    }

    $('threatSection').classList.remove('hidden');
    const list = $('threatList');
    list.innerHTML = '';
    items.forEach(item => {
      const score = item.confidence_score ?? 0;
      const level = scoreToLevel(score);
      const c = LEVEL_COLORS[level] || LEVEL_COLORS.review;

      // FIX: DOM construction — no innerHTML with API data (XSS prevention)
      const row = document.createElement('div');
      row.className = 'threat-item';

      const dot = document.createElement('span');
      dot.className = 'threat-dot';
      dot.style.background = c.dot;

      const info = document.createElement('div');
      info.className = 'threat-info';

      const domainSpan = document.createElement('span');
      domainSpan.className = 'threat-domain';
      domainSpan.textContent = item.detected_domain || item.sender_email || '—';

      const metaSpan = document.createElement('span');
      metaSpan.className = 'threat-meta';
      metaSpan.textContent = item.impersonated_brand || item.threat_type || level;

      info.appendChild(domainSpan);
      info.appendChild(metaSpan);

      const scoreSpan = document.createElement('span');
      scoreSpan.className = 'threat-score';
      scoreSpan.style.background = c.bg;
      scoreSpan.style.color = c.color;
      scoreSpan.textContent = String(score);

      row.appendChild(dot);
      row.appendChild(info);
      row.appendChild(scoreSpan);
      list.appendChild(row);
    });
  }

  // ── settings toggles ──────────────────────────────────────────────────────
  async function loadToggles() {
    const res = await AIOExtensionBridge.sendToRuntime('AIO_GET_SETTINGS', {});
    if (!res || !res.ok) return;
    const s = res.settings || {};
    $('toggleClassify').classList.toggle('active', !!s.autoClassify);
    $('toggleBadges').classList.toggle('active',   !!s.showBadges);
    $('toggleThreat').classList.toggle('active',   !!s.showThreatBadges);
  }

  function bindToggles() {
    const toggleMap = {
      toggleClassify: 'autoClassify',
      toggleBadges:   'showBadges',
      toggleThreat:   'showThreatBadges'
    };
    Object.entries(toggleMap).forEach(([btnId, key]) => {
      $(btnId).addEventListener('click', async () => {
        $(btnId).classList.toggle('active');
        const isActive = $(btnId).classList.contains('active');
        const res = await AIOExtensionBridge.sendToRuntime('AIO_GET_SETTINGS', {});
        const current = (res && res.settings) || {};
        await AIOExtensionBridge.sendToRuntime('AIO_SAVE_SETTINGS', { ...current, [key]: isActive });
      });
    });
  }

  // ── domain checker ────────────────────────────────────────────────────────
  function renderDomainResult(data) {
    const el = $('domainResult');
    if (!data) { el.classList.add('hidden'); return; }
    const score = data.confidence_score ?? 0;
    const level = scoreToLevel(score);
    const c = LEVEL_COLORS[level] || LEVEL_COLORS.review;
    const reasons = (data.reasons || []).slice(0, 2).join('; ') || 'No issues detected';

    el.className = 'domain-result';
    el.innerHTML = '';

    // FIX: DOM construction — no innerHTML with API data (XSS prevention)
    const header = document.createElement('div');
    header.className = 'domain-result-header';

    const dot = document.createElement('span');
    dot.className = 'threat-dot';
    dot.style.background = c.dot;

    const strong = document.createElement('strong');
    strong.textContent = data.domain || '—';

    const badge = document.createElement('span');
    badge.className = 'domain-badge';
    badge.style.background = c.bg;
    badge.style.color = c.color;
    badge.textContent = `${level} · ${score}/100`;

    header.appendChild(dot);
    header.appendChild(strong);
    header.appendChild(badge);

    const note = document.createElement('p');
    note.className = 'domain-note';
    note.textContent = reasons;

    el.appendChild(header);
    el.appendChild(note);
  }

  $('domainCheck').addEventListener('click', async () => {
    const domain = $('domainInput').value.trim().replace(/^https?:\/\//i, '').split('/')[0];
    if (!domain) return;
    $('domainCheck').textContent = '…';
    $('domainResult').classList.remove('hidden');
    $('domainResult').textContent = 'Checking…';
    const res = await AIOExtensionBridge.sendToRuntime('AIO_ANALYZE_DOMAIN', { domain });
    $('domainCheck').textContent = 'Check';
    renderDomainResult(res && res.ok ? res.result : null);
  });

  $('domainInput').addEventListener('keydown', e => {
    if (e.key === 'Enter') $('domainCheck').click();
  });

  // ── navigation ────────────────────────────────────────────────────────────
  $('openDashboard').addEventListener('click', async () => {
    const res = await AIOExtensionBridge.sendToRuntime('AIO_GET_SETTINGS', {});
    const s = (res && res.settings) || {};
    const origin = await AIOExtensionRuntime.discoverApi();
    br().tabs.create({ url: `${origin}${s.dashboardPath || '/dashboard'}` });
  });

  $('openSecurity').addEventListener('click', () => {
    AIOExtensionBridge.sendToRuntime('AIO_OPEN_DASHBOARD', { path: '/security' });
  });

  $('openSettings').addEventListener('click', () => br().runtime.openOptionsPage());

  // ── refresh ───────────────────────────────────────────────────────────────
  async function refresh() {
    $('refresh').textContent = '…';
    const origin = await AIOExtensionRuntime.discoverApi(true);
    setStatus(AIOExtensionRuntime.state.online, origin);
    await Promise.allSettled([loadStats(), loadProviders(), loadThreats(), loadToggles()]);
    $('refresh').textContent = '↻';
  }

  $('refresh').addEventListener('click', refresh);

  // ── init ──────────────────────────────────────────────────────────────────
  try {
    const manifest = br().runtime.getManifest();
    $('platform').textContent = manifest.name || 'INTEMO';
    $('extVersion').textContent = manifest.version || '14.0.1B';
  } catch {}

  bindToggles();
  refresh();
})();
