(function () {
  'use strict';

  const DEFAULTS = AIOExtensionRuntime.DEFAULT_SETTINGS;
  const CANDIDATE_ORIGINS = [
    'http://127.0.0.1:4597', 'http://localhost:4597',
    'http://127.0.0.1:4501', 'http://localhost:4501',
    'http://127.0.0.1:4510', 'http://localhost:4510'
  ];
  const DASHBOARD_PATHS = new Set(['/dashboard', '/security', '/setup', '/admin']);
  const br = globalThis.browser || globalThis.chrome;
  const $ = id => document.getElementById(id);

  // ── origin validation ─────────────────────────────────────────────────────
  function cleanOrigin(value) {
    const raw = String(value || '').trim();
    if (!raw) throw new Error('API origin is required — e.g. http://127.0.0.1:4597');
    const origin = new URL(raw).origin;
    if (!AIOExtensionRuntime.isSafeOrigin(origin)) {
      throw new Error('Only http://127.0.0.1 and http://localhost origins are allowed.');
    }
    return origin;
  }

  // ── storage helpers ───────────────────────────────────────────────────────
  function storageGet(keys) {
    return new Promise(resolve => br.storage.local.get(keys, r => resolve(r || {})));
  }

  function storageSet(values) {
    return new Promise(resolve => br.storage.local.set(values, () => resolve(true)));
  }

  async function loadSettings() {
    const stored = await storageGet(['apiOrigin', 'settings']);
    const nested = stored.settings || {};
    return {
      ...DEFAULTS,
      ...nested,
      apiOrigin: stored.apiOrigin || nested.apiOrigin || DEFAULTS.apiOrigin
    };
  }

  async function saveSettings(settings) {
    const normalized = {
      ...DEFAULTS,
      ...settings,
      apiOrigin: cleanOrigin(settings.apiOrigin),
      dashboardPath: DASHBOARD_PATHS.has(settings.dashboardPath)
        ? settings.dashboardPath
        : DEFAULTS.dashboardPath,
      threatThreshold:         Number(settings.threatThreshold)         || 30,
      notificationThreshold:   Number(settings.notificationThreshold)   || 56,
      statsRefreshInterval:    Number(settings.statsRefreshInterval)     || 120,
      autoDiscover:            !!settings.autoDiscover,
      autoClassify:            !!settings.autoClassify,
      showBadges:              !!settings.showBadges,
      showSuggestions:         !!settings.showSuggestions,
      enableTelemetry:         !!settings.enableTelemetry,
      showThreatBadges:        !!settings.showThreatBadges,
      highlightScamEmails:     !!settings.highlightScamEmails,
      showQuickActions:        !!settings.showQuickActions,
      analyzeDomains:          !!settings.analyzeDomains,
      browserNotifications:    !!settings.browserNotifications,
      compactBadges:           !!settings.compactBadges,
      keyboardShortcuts:       !!settings.keyboardShortcuts
    };
    await storageSet({ apiOrigin: normalized.apiOrigin, settings: normalized });
    return normalized;
  }

  // ── connection test ───────────────────────────────────────────────────────
  async function testOrigin(origin, autoDiscover) {
    const candidates = autoDiscover
      ? [...new Set([origin, ...CANDIDATE_ORIGINS].filter(Boolean))]
      : [origin];
    for (const candidate of candidates) {
      if (!AIOExtensionRuntime.isSafeOrigin(candidate)) continue;
      try {
        const response = await AIOExtensionRuntime.withTimeout(
          `${candidate}/api/v1/health`,
          { method: 'GET', headers: { 'X-Client-Request-ID': `options_${Date.now()}` } },
          3500
        );
        if (response.ok) return { ok: true, origin: candidate };
      } catch {}
    }
    return { ok: false, origin };
  }

  // ── status display ────────────────────────────────────────────────────────
  function setStatus(state, title, detail) {
    $('statusDot').className = `dot ${state}`;
    $('statusText').textContent = title;
    $('statusDetail').textContent = detail;
  }

  // ── form read / render ────────────────────────────────────────────────────
  function readForm() {
    const current = {
      apiOrigin: $('origin').value.trim(),
      dashboardPath: $('dashboardPath').value,
      threatThreshold: Number($('threatThreshold').value),
      notificationThreshold: Number($('notificationThreshold').value),
      statsRefreshInterval: Number($('statsRefreshInterval').value)
    };
    document.querySelectorAll('.toggle').forEach(btn => {
      current[btn.dataset.key] = btn.classList.contains('active');
    });
    return current;
  }

  function render(settings) {
    $('origin').value = settings.apiOrigin || DEFAULTS.apiOrigin;
    $('dashboardPath').value = DASHBOARD_PATHS.has(settings.dashboardPath)
      ? settings.dashboardPath : DEFAULTS.dashboardPath;

    const threatVal = settings.threatThreshold ?? DEFAULTS.threatThreshold;
    $('threatThreshold').value = threatVal;
    $('thresholdVal').textContent = String(threatVal);

    const notifVal = settings.notificationThreshold ?? DEFAULTS.notificationThreshold;
    $('notificationThreshold').value = notifVal;
    $('notifThresholdVal').textContent = String(notifVal);

    const intervalVal = settings.statsRefreshInterval ?? DEFAULTS.statsRefreshInterval;
    $('statsRefreshInterval').value = String(intervalVal);

    document.querySelectorAll('.toggle').forEach(btn => {
      btn.classList.toggle('active', !!settings[btn.dataset.key]);
    });

    try { $('extensionName').textContent = br.runtime.getManifest().name; } catch {}
  }

  // ── toast ─────────────────────────────────────────────────────────────────
  function showToast(msg) {
    const el = $('saveToast');
    el.textContent = msg;
    el.classList.remove('hidden');
    setTimeout(() => el.classList.add('hidden'), 2500);
  }

  // ── range input live labels ───────────────────────────────────────────────
  $('threatThreshold').addEventListener('input', () => {
    $('thresholdVal').textContent = $('threatThreshold').value;
  });
  $('notificationThreshold').addEventListener('input', () => {
    $('notifThresholdVal').textContent = $('notificationThreshold').value;
  });

  // ── toggle clicks ─────────────────────────────────────────────────────────
  function bindToggles() {
    document.querySelectorAll('.toggle').forEach(btn =>
      btn.addEventListener('click', () => btn.classList.toggle('active'))
    );
  }

  // ── init ──────────────────────────────────────────────────────────────────
  document.addEventListener('DOMContentLoaded', async () => {
    bindToggles();
    render(await loadSettings());

    $('save').addEventListener('click', async () => {
      try {
        const settings = await saveSettings(readForm());
        render(settings);
        setStatus('', 'Settings saved', `Using ${settings.apiOrigin}${settings.dashboardPath}`);
        showToast('Settings saved');
      } catch (err) {
        setStatus('offline', 'Settings not saved', err.message);
      }
    });

    $('testConnection').addEventListener('click', async () => {
      try {
        const form = readForm();
        const settings = await saveSettings(form);
        setStatus('', 'Testing connection…', settings.apiOrigin);
        const result = await testOrigin(settings.apiOrigin, settings.autoDiscover);
        if (result.ok) {
          const updated = await saveSettings({ ...settings, apiOrigin: result.origin });
          $('origin').value = result.origin;
          render(updated);
          setStatus('online', 'Local service online', `Connected to ${result.origin}/api/v1/health`);
        } else {
          setStatus('offline', 'Service offline', 'Start the INTEMO desktop app, then test again.');
        }
      } catch (err) {
        setStatus('offline', 'Connection failed', err.message);
      }
    });

    $('openDashboard').addEventListener('click', async () => {
      try {
        const settings = await saveSettings(readForm());
        br.tabs.create({ url: `${settings.apiOrigin}${settings.dashboardPath}` });
      } catch (err) {
        setStatus('offline', 'Cannot open page', err.message);
      }
    });

    $('reset').addEventListener('click', async () => {
      const settings = await saveSettings(DEFAULTS);
      render(settings);
      setStatus('', 'Settings reset', 'All options restored to defaults.');
      showToast('Reset to defaults');
    });
  });
})();
