(function (global) {
  'use strict';

  const VERSION = '14.0.1B';
  const CANDIDATE_ORIGINS = [
    'http://127.0.0.1:4597', 'http://localhost:4597',
    'http://127.0.0.1:4501', 'http://localhost:4501',
    'http://127.0.0.1:4510', 'http://localhost:4510'
  ];
  const DEFAULT_SETTINGS = {
    apiOrigin: 'http://127.0.0.1:4597',
    dashboardPath: '/dashboard',
    autoDiscover: true,
    autoClassify: true,
    showBadges: true,
    showSuggestions: true,
    enableTelemetry: true,
    showThreatBadges: true,
    threatThreshold: 30,
    highlightScamEmails: true,
    browserNotifications: true,
    notificationThreshold: 56,
    compactBadges: false,
    showQuickActions: true,
    analyzeDomains: true,
    statsRefreshInterval: 120,
    keyboardShortcuts: true,
    clientRuntimeVersion: VERSION
  };

  const state = {
    apiOrigin: DEFAULT_SETTINGS.apiOrigin,
    online: false,
    lastCheck: 0,
    platform: 'generic',
    statsCache: null,
    statsCacheAt: 0,
    domainCache: Object.create(null),
    badgeCount: 0
  };

  const fallbackExtensionStore = {};
  const selfHealingEvents = [];

  function recordSelfHealing(action, detail = {}) {
    const last = selfHealingEvents[selfHealingEvents.length - 1];
    if (last && last.action === action && Date.now() - last.createdAt < 1000) return;
    selfHealingEvents.push({ action, detail, createdAt: Date.now() });
    selfHealingEvents.splice(0, Math.max(0, selfHealingEvents.length - 50));
  }

  function fallbackStorageResult(keys) {
    if (keys == null) return { ...fallbackExtensionStore };
    if (Array.isArray(keys)) {
      return keys.reduce((result, key) => {
        if (Object.prototype.hasOwnProperty.call(fallbackExtensionStore, key)) {
          result[key] = fallbackExtensionStore[key];
        }
        return result;
      }, {});
    }
    if (typeof keys === 'string') {
      return Object.prototype.hasOwnProperty.call(fallbackExtensionStore, keys)
        ? { [keys]: fallbackExtensionStore[keys] }
        : {};
    }
    if (typeof keys === 'object') {
      const result = { ...keys };
      Object.keys(keys).forEach(key => {
        if (Object.prototype.hasOwnProperty.call(fallbackExtensionStore, key)) {
          result[key] = fallbackExtensionStore[key];
        }
      });
      return result;
    }
    return {};
  }

  const fallbackBrowserApi = {
    storage: {
      local: {
        get(keys, callback) {
          recordSelfHealing('extension_browser_api_fallback', { api: 'storage.local.get' });
          if (callback) callback(fallbackStorageResult(keys));
        },
        set(values, callback) {
          recordSelfHealing('extension_browser_api_fallback', { api: 'storage.local.set' });
          Object.assign(fallbackExtensionStore, values || {});
          if (callback) callback();
        }
      }
    },
    action: {
      setBadgeText() {},
      setBadgeBackgroundColor() {}
    },
    notifications: {
      create() {}
    },
    runtime: {
      getManifest() {
        return { name: 'INTEMO AI Email Security', version: VERSION };
      },
      openOptionsPage() {}
    },
    tabs: {
      create() {}
    }
  };

  function browserApi() {
    const nativeApi = global.browser || global.chrome;
    if (nativeApi) return nativeApi;
    recordSelfHealing('extension_browser_api_fallback', { api: 'browserApi' });
    return fallbackBrowserApi;
  }

  function selfHealingStatus() {
    return {
      fallbackBrowserApiActive: !(global.browser || global.chrome),
      events: selfHealingEvents.slice(-50),
      fallbackStorageKeys: Object.keys(fallbackExtensionStore)
    };
  }

  function isSafeOrigin(origin) {
    try {
      const url = new URL(origin);
      return url.protocol === 'http:' && ['127.0.0.1', 'localhost'].includes(url.hostname);
    } catch { return false; }
  }

  function requestId(prefix = 'client_req') {
    const v = global.crypto && crypto.randomUUID ? crypto.randomUUID() : Math.random().toString(36).slice(2);
    return `${prefix}_${v}`;
  }

  async function storageGet(keys) {
    const br = browserApi();
    return new Promise(resolve => {
      try { br.storage.local.get(keys, result => resolve(result || {})); }
      catch { resolve({}); }
    });
  }

  async function storageSet(data) {
    const br = browserApi();
    return new Promise(resolve => {
      try { br.storage.local.set(data, () => resolve(true)); } catch { resolve(false); }
    });
  }

  async function getSettings() {
    const stored = await storageGet(['apiOrigin', 'settings']);
    const nested = stored.settings || {};
    return {
      ...DEFAULT_SETTINGS,
      ...nested,
      apiOrigin: stored.apiOrigin || nested.apiOrigin || DEFAULT_SETTINGS.apiOrigin
    };
  }

  async function saveSettings(settings) {
    const raw = settings || {};
    const merged = {
      ...DEFAULT_SETTINGS,
      ...raw,
      // Coerce numeric fields — form inputs arrive as strings
      threatThreshold:       Math.max(0, Math.min(100, Number(raw.threatThreshold)       || DEFAULT_SETTINGS.threatThreshold)),
      notificationThreshold: Math.max(0, Math.min(100, Number(raw.notificationThreshold) || DEFAULT_SETTINGS.notificationThreshold)),
      statsRefreshInterval:  Math.max(30, Number(raw.statsRefreshInterval)               || DEFAULT_SETTINGS.statsRefreshInterval),
      // Coerce booleans
      autoDiscover:         !!raw.autoDiscover,
      autoClassify:         !!raw.autoClassify,
      showBadges:           !!raw.showBadges,
      showSuggestions:      !!raw.showSuggestions,
      enableTelemetry:      !!raw.enableTelemetry,
      showThreatBadges:     !!raw.showThreatBadges,
      highlightScamEmails:  !!raw.highlightScamEmails,
      browserNotifications: !!raw.browserNotifications,
      compactBadges:        !!raw.compactBadges,
      showQuickActions:     !!raw.showQuickActions,
      analyzeDomains:       !!raw.analyzeDomains,
      keyboardShortcuts:    !!raw.keyboardShortcuts
    };
    if (!isSafeOrigin(merged.apiOrigin)) merged.apiOrigin = DEFAULT_SETTINGS.apiOrigin;
    await storageSet({ apiOrigin: merged.apiOrigin, settings: merged });
    return merged;
  }

  async function withTimeout(url, options = {}, timeout = 5000) {
    const controller = new AbortController();
    const id = setTimeout(() => controller.abort(), timeout);
    try { return await fetch(url, { ...options, signal: controller.signal }); }
    finally { clearTimeout(id); }
  }

  async function discoverApi(force = false) {
    const settings = await getSettings();
    if (!force && state.online && Date.now() - state.lastCheck < 25000) return state.apiOrigin;
    const origins = settings.autoDiscover
      ? [...new Set([settings.apiOrigin, ...CANDIDATE_ORIGINS].filter(Boolean).filter(isSafeOrigin))]
      : [settings.apiOrigin].filter(isSafeOrigin);
    for (const origin of origins) {
      try {
        const response = await withTimeout(`${origin}/api/v1/health`, {
          method: 'GET',
          headers: { 'X-Client-Request-ID': requestId() }
        });
        if (response.ok) {
          state.apiOrigin = origin;
          state.online = true;
          state.lastCheck = Date.now();
          await storageSet({ apiOrigin: origin, settings: { ...settings, apiOrigin: origin } });
          return origin;
        }
      } catch {}
    }
    state.apiOrigin = settings.apiOrigin;
    state.online = false;
    state.lastCheck = Date.now();
    return state.apiOrigin;
  }

  // FIX: only set Content-Type when a body is present (avoids proxy rejections on GET)
  async function api(path, options = {}) {
    const origin = await discoverApi();
    const hasBody = options.body != null;
    const headers = {
      'X-Client-Request-ID': requestId(),
      'X-AIO-Client-Platform': state.platform,
      'X-AIO-Extension-Version': VERSION,
      ...(options.headers || {})
    };
    if (hasBody) headers['Content-Type'] = 'application/json';
    const response = await withTimeout(`${origin}/api/v1${path}`, { ...options, headers });
    if (!response.ok) throw new Error(`API ${response.status}`);
    return await response.json().catch(() => ({}));
  }

  async function getThreatStats(force = false) {
    if (!force && state.statsCache && Date.now() - state.statsCacheAt < 60000) {
      return state.statsCache;
    }
    try {
      const data = await api('/threat/stats');
      state.statsCache = data;
      state.statsCacheAt = Date.now();
      return data;
    } catch { return state.statsCache || {}; }
  }

  async function getRecentThreats(limit = 10) {
    try {
      const data = await api(`/threat/feed?limit=${limit}`);
      return { items: Array.isArray(data.items) ? data.items : [] };
    } catch { return { items: [] }; }
  }

  async function analyzeDomain(domain) {
    if (!domain) return null;
    const key = domain.toLowerCase().replace(/[^\w.-]/g, '');
    if (!key) return null;
    const cached = state.domainCache[key];
    if (cached && Date.now() - cached.at < 300000) return cached.data;
    try {
      const data = await api(`/threat/domain/${encodeURIComponent(key)}`);
      state.domainCache[key] = { data, at: Date.now() };
      return data;
    } catch { return null; }
  }

  async function reportScam(emailId, blockSender = true) {
    return api(`/threat/emails/${emailId}/confirm`, {
      method: 'POST',
      body: JSON.stringify({ block_sender: blockSender })
    });
  }

  async function markSafe(emailId) {
    return api(`/threat/emails/${emailId}/restore`, { method: 'POST', body: '{}' });
  }

  async function blacklistSender(entry, entryType = 'email', reason = 'Reported by extension') {
    return api('/threat/blacklist', {
      method: 'POST',
      body: JSON.stringify({ entry_type: entryType, value: entry, reason, threat_type: 'user_report', score: 90, auto_block: true })
    });
  }

  async function whitelistSender(entry, entryType = 'email', notes = 'Trusted via extension') {
    return api('/threat/whitelist', {
      method: 'POST',
      body: JSON.stringify({ entry_type: entryType, value: entry, notes })
    });
  }

  function updateBadge(count) {
    state.badgeCount = count;
    const br = browserApi();
    if (!br || !br.action) return;
    const text = count > 0 ? (count > 99 ? '99+' : String(count)) : '';
    try {
      br.action.setBadgeText({ text });
      br.action.setBadgeBackgroundColor({ color: count > 0 ? '#ef4444' : '#6b7280' });
    } catch {}
  }

  function showNotification(title, message) {
    const br = browserApi();
    if (!br || !br.notifications) return;
    try {
      br.notifications.create(`intemo_${Date.now()}`, {
        type: 'basic',
        iconUrl: 'icons/icon48.png',
        title: `INTEMO: ${title}`,
        message: String(message || ''),
        priority: 2
      });
    } catch {}
  }

  function configure(platform) { state.platform = platform || state.platform; return state; }

  global.AIOExtensionRuntime = {
    configure, discoverApi, api,
    isSafeOrigin, state, requestId,
    selfHealingStatus,
    getSettings, saveSettings, withTimeout,
    getThreatStats, getRecentThreats, analyzeDomain,
    reportScam, markSafe, blacklistSender, whitelistSender,
    updateBadge, showNotification,
    DEFAULT_SETTINGS, VERSION
  };
})(typeof globalThis !== 'undefined' ? globalThis : window);
