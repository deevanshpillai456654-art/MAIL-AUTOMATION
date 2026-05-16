importScripts('extension_runtime.js', 'secure_message_bridge.js');
AIOExtensionRuntime.configure('intemo-extension');

const ALARM_STATS_POLL = 'intemo_stats_poll';

// ── alarm setup ──────────────────────────────────────────────────────────────
// MV3 minimum alarm period is 1 minute. No keepalive alarm — the SW wakes
// when the alarm fires or on port/message events; trying to keep it alive
// via a sub-minute alarm is rejected by Chrome and wastes the alarms quota.
chrome.alarms.getAll(alarms => {
  const hasStatsAlarm = alarms.some(a => a.name === ALARM_STATS_POLL);
  if (!hasStatsAlarm) {
    chrome.alarms.create(ALARM_STATS_POLL, { periodInMinutes: 2 });
  }
});

chrome.alarms.onAlarm.addListener(async alarm => {
  if (alarm.name === ALARM_STATS_POLL) await pollStats();
});

// ── stats polling ─────────────────────────────────────────────────────────────
async function pollStats() {
  try {
    const stats = await AIOExtensionRuntime.getThreatStats(true);
    const scamCount = stats.scam_emails_today ?? stats.critical_today ?? 0;
    AIOExtensionRuntime.updateBadge(Number(scamCount) || 0);
    await chrome.storage.local.set({ cachedStats: stats, statsUpdatedAt: Date.now() });
  } catch {}
}

// ── notification helper ───────────────────────────────────────────────────────
async function maybeNotify(title, message, score = 100) {
  const settings = await AIOExtensionRuntime.getSettings();
  if (!settings.browserNotifications) return;
  if (score < (Number(settings.notificationThreshold) || 56)) return;
  AIOExtensionRuntime.showNotification(title, message);
}

// ── message dispatcher ────────────────────────────────────────────────────────
async function handle(message, _sender) {
  const validation = AIOExtensionBridge.validateMessage(message);
  if (!validation.ok) return { ok: false, reason: validation.reason };
  const payload = validation.message.payload || {};

  try {
    switch (validation.message.type) {

      case 'AIO_GET_STATUS': {
        const origin = await AIOExtensionRuntime.discoverApi(true);
        const settings = await AIOExtensionRuntime.getSettings();
        return { ok: true, online: AIOExtensionRuntime.state.online, origin, settings };
      }

      case 'AIO_GET_SETTINGS': {
        return { ok: true, settings: await AIOExtensionRuntime.getSettings() };
      }

      case 'AIO_SAVE_SETTINGS': {
        const saved = await AIOExtensionRuntime.saveSettings(payload);
        return { ok: true, settings: saved };
      }

      case 'AIO_GET_PROVIDERS': {
        return { ok: true, result: await AIOExtensionRuntime.api('/providers') };
      }

      case 'AIO_CLASSIFY_EMAIL': {
        const settings = await AIOExtensionRuntime.getSettings();
        if (!settings.autoClassify) return { ok: false, reason: 'auto_classify_disabled' };
        const result = await AIOExtensionRuntime.api('/classify', {
          method: 'POST',
          body: JSON.stringify(payload)
        });
        const confidence = Number(result.confidence) || 0;
        const score = Math.round(confidence * 100);
        if ((result.category || '').toLowerCase() === 'scam' || score > 80) {
          await maybeNotify(
            'Scam email detected',
            `From: ${payload.sender || 'unknown'} — ${payload.subject || ''}`,
            score
          );
        }
        return { ok: true, result };
      }

      case 'AIO_GET_THREAT_STATS': {
        const stats = await AIOExtensionRuntime.getThreatStats(!!payload.force);
        return { ok: true, stats };
      }

      case 'AIO_GET_RECENT_THREATS': {
        // FIX: explicit items key — don't spread unknown object onto response
        const limit = Math.min(Number(payload.limit) || 10, 50);
        const data = await AIOExtensionRuntime.getRecentThreats(limit);
        return { ok: true, items: data.items || [] };
      }

      case 'AIO_ANALYZE_DOMAIN': {
        if (!payload.domain) return { ok: false, reason: 'domain_required' };
        const result = await AIOExtensionRuntime.analyzeDomain(payload.domain);
        return { ok: true, result };
      }

      case 'AIO_REPORT_SCAM': {
        if (!payload.email_id) return { ok: false, reason: 'email_id_required' };
        try {
          const result = await AIOExtensionRuntime.reportScam(
            payload.email_id, payload.block_sender !== false
          );
          await pollStats();
          return { ok: true, result };
        } catch (err) {
          return { ok: false, error: err.message };
        }
      }

      case 'AIO_MARK_SAFE': {
        if (!payload.email_id) return { ok: false, reason: 'email_id_required' };
        try {
          const result = await AIOExtensionRuntime.markSafe(payload.email_id);
          await pollStats();
          return { ok: true, result };
        } catch (err) {
          return { ok: false, error: err.message };
        }
      }

      case 'AIO_BLACKLIST_SENDER': {
        if (!payload.entry) return { ok: false, reason: 'entry_required' };
        const result = await AIOExtensionRuntime.blacklistSender(
          payload.entry,
          payload.entry_type || 'email',
          payload.reason || 'Reported by extension'
        );
        return { ok: true, result };
      }

      case 'AIO_WHITELIST_SENDER': {
        if (!payload.entry) return { ok: false, reason: 'entry_required' };
        const result = await AIOExtensionRuntime.whitelistSender(
          payload.entry,
          payload.entry_type || 'email',
          payload.notes || 'Trusted via extension'
        );
        return { ok: true, result };
      }

      case 'AIO_SHOW_NOTIFICATION': {
        await maybeNotify(payload.title || 'Alert', payload.message || '', 100);
        return { ok: true };
      }

      case 'AIO_UPDATE_BADGE': {
        AIOExtensionRuntime.updateBadge(Number(payload.count) || 0);
        return { ok: true };
      }

      case 'AIO_SEND_FEEDBACK': {
        await AIOExtensionRuntime.api('/feedback', {
          method: 'POST',
          body: JSON.stringify(payload)
        });
        return { ok: true };
      }

      case 'AIO_RUNTIME_TELEMETRY': {
        const settings = await AIOExtensionRuntime.getSettings();
        if (!settings.enableTelemetry) return { ok: true, skipped: 'telemetry_disabled' };
        await AIOExtensionRuntime.api('/frontend/telemetry', {
          method: 'POST',
          body: JSON.stringify({ client_id: 'intemo-extension', events: [payload] })
        });
        return { ok: true };
      }

      case 'AIO_OPEN_DASHBOARD': {
        const settings = await AIOExtensionRuntime.getSettings();
        const origin = await AIOExtensionRuntime.discoverApi();
        const path = payload.path || settings.dashboardPath || '/dashboard';
        chrome.tabs.create({ url: `${origin}${path}` });
        return { ok: true };
      }

      default:
        return { ok: false, reason: 'unhandled_message' };
    }
  } catch (error) {
    return { ok: false, error: error.message };
  }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  handle(message, sender).then(sendResponse);
  return true;
});

chrome.runtime.onInstalled.addListener(async ({ reason }) => {
  const current = await AIOExtensionRuntime.getSettings();
  await AIOExtensionRuntime.saveSettings({
    ...current,
    clientRuntimeVersion: chrome.runtime.getManifest().version
  });
  await pollStats();
  if (reason === 'install') {
    const origin = await AIOExtensionRuntime.discoverApi(true);
    if (AIOExtensionRuntime.state.online) {
      chrome.tabs.create({ url: `${origin}/dashboard` });
    }
  }
});

chrome.runtime.onStartup.addListener(() => pollStats());
