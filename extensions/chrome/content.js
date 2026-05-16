(function () {
  'use strict';
  if (window.__INTEMO_CONTENT_LOADED__) return;
  window.__INTEMO_CONTENT_LOADED__ = true;

  // ── constants ──────────────────────────────────────────────────────────────
  const MAX_ROWS_PER_PASS = 80;
  const DOMAIN_CACHE_TTL  = 300000;
  const DEFAULT_SETTINGS = {
    autoClassify: true, showBadges: true, showSuggestions: true,
    showThreatBadges: true, threatThreshold: 30,
    highlightScamEmails: true, showQuickActions: true,
    analyzeDomains: true, compactBadges: false, keyboardShortcuts: true
  };

  const processed = new Map(); // id → {label, level, senderEmail} or null (in-progress)
  const domainCache = Object.create(null);
  let timer = null;
  let cachedSettings = { ...DEFAULT_SETTINGS };
  let settingsLoadedAt = 0;
  let activeTooltip = null;

  // ── utils ──────────────────────────────────────────────────────────────────
  function br() { return globalThis.browser || globalThis.chrome; }
  function text(el) { return (el && el.textContent || '').trim(); }
  function isGmail() { return location.hostname === 'mail.google.com'; }
  function isOutlook() { return location.hostname.includes('outlook'); }

  // FIX: replace deprecated unescape() with TextEncoder-based btoa
  function rowHash(str) {
    const bytes = new TextEncoder().encode(str.slice(0, 120));
    let binary = '';
    bytes.forEach(b => { binary += String.fromCharCode(b); });
    return btoa(binary).replace(/=+$/, '');
  }

  function messageId(row) {
    return row.getAttribute('data-legacy-message-id')
      || row.getAttribute('data-message-id')
      || row.id
      || rowHash(text(row));
  }

  // FIX: XSS-safe text escaping for innerHTML insertion
  function esc(str) {
    return String(str || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function storageGet(keys) {
    return new Promise(resolve => {
      try { br().storage.local.get(keys, r => resolve(r || {})); }
      catch { resolve({}); }
    });
  }

  async function loadSettings() {
    if (Date.now() - settingsLoadedAt < 30000) return cachedSettings;
    const stored = await storageGet(['settings']);
    cachedSettings = { ...DEFAULT_SETTINGS, ...(stored.settings || {}) };
    settingsLoadedAt = Date.now();
    return cachedSettings;
  }

  // ── threat level helpers ───────────────────────────────────────────────────
  function scoreToLevel(score) {
    if (score <= 20) return 'clean';
    if (score <= 55) return 'review';
    if (score <= 80) return 'suspicious';
    return 'scam';
  }

  function levelColor(level) {
    return {
      clean:      { bg: '#dcfce7', color: '#166534', border: '#86efac', dot: '#22c55e' },
      review:     { bg: '#fef9c3', color: '#854d0e', border: '#fde047', dot: '#eab308' },
      suspicious: { bg: '#ffedd5', color: '#9a3412', border: '#fed7aa', dot: '#f97316' },
      scam:       { bg: '#fee2e2', color: '#991b1b', border: '#fca5a5', dot: '#ef4444' }
    }[level] || { bg: '#f1f5f9', color: '#475569', border: '#cbd5e1', dot: '#94a3b8' };
  }

  // ── row data extraction ────────────────────────────────────────────────────
  function rowData(row) {
    let subject = '', sender = '', senderEmail = '', snippet = '';
    if (isGmail()) {
      subject = text(row.querySelector('.bog,.bqe,.hP,.subject,[data-subject]'));
      const sEl = row.querySelector('.zF,.yW span[email],.sender,[data-sender]');
      sender = text(sEl);
      senderEmail = sEl ? (sEl.getAttribute('email') || sEl.getAttribute('data-email') || sender) : sender;
      snippet = text(row.querySelector('.y2,.snippet,[data-snippet]'));
    } else if (isOutlook()) {
      subject = text(row.querySelector('[aria-label][class*="subject"],[class*="Subject"],span[class*="subject"]'));
      const sEl = row.querySelector('[class*="sender"],[class*="from"],[class*="personName"]');
      sender = text(sEl);
      senderEmail = sEl ? (sEl.getAttribute('data-email') || sEl.title || sender) : sender;
      snippet = text(row.querySelector('[class*="preview"],[class*="snippet"]'));
    }
    if (!subject && !sender) return null;
    return { subject, sender, sender_email: senderEmail, body: snippet };
  }

  // ── badge rendering ────────────────────────────────────────────────────────
  function attachBadge(row, label, level, compact) {
    const existing = row.querySelector('.intemo-badge');
    if (existing) existing.remove();
    const c = levelColor(level);
    const badge = document.createElement('span');
    badge.className = `intemo-badge intemo-badge-${level}`;

    // FIX: use DOM construction instead of innerHTML (prevents XSS from API data)
    const dot = document.createElement('span');
    dot.className = 'intemo-badge-dot';
    dot.style.cssText = `width:6px;height:6px;border-radius:50%;background:${c.dot};flex-shrink:0`;
    badge.appendChild(dot);

    if (!compact) {
      const txt = document.createElement('span');
      txt.textContent = label; // safe — textContent never executes HTML
      badge.appendChild(txt);
    }

    badge.style.cssText = [
      'display:inline-flex', 'align-items:center', 'gap:4px',
      `margin-left:${compact ? '4px' : '8px'}`,
      `padding:${compact ? '2px 4px' : '3px 8px'}`,
      'border-radius:999px',
      `background:${c.bg}`, `color:${c.color}`,
      `border:1px solid ${c.border}`,
      'font:700 10px system-ui', 'vertical-align:middle',
      'white-space:nowrap', 'line-height:1.3'
    ].join(';');

    const target = row.querySelector('.bog,.bqe,.hP,.subject,[class*="subject"]') || row;
    target.appendChild(badge);
  }

  function highlightRow(row, level) {
    if (level === 'suspicious') {
      row.style.borderLeft = '3px solid #f97316';
    } else if (level === 'scam') {
      row.style.background = 'rgba(239,68,68,0.05)';
      row.style.borderLeft = '3px solid #ef4444';
    }
  }

  // ── quick action toolbar ───────────────────────────────────────────────────
  function buildToolbar(row, emailId, senderEmail) {
    if (row.querySelector('.intemo-toolbar')) return;
    const bar = document.createElement('div');
    bar.className = 'intemo-toolbar';
    bar.style.cssText = [
      'display:none', 'position:absolute', 'right:8px', 'top:50%',
      'transform:translateY(-50%)', 'gap:4px', 'z-index:9999',
      'background:rgba(7,11,22,.92)', 'border:1px solid rgba(255,255,255,.12)',
      'border-radius:10px', 'padding:4px', 'box-shadow:0 8px 24px rgba(0,0,0,.4)'
    ].join(';');

    const mkBtn = (label, title, bg) => {
      const b = document.createElement('button');
      b.type = 'button';
      b.textContent = label;
      b.title = title;
      b.style.cssText = [
        `background:${bg}`, 'border:0', 'border-radius:7px', 'padding:4px 7px',
        'font:700 10px system-ui', 'cursor:pointer', 'color:#fff',
        'transition:opacity .15s', 'white-space:nowrap'
      ].join(';');
      return b;
    };

    const reportBtn = mkBtn('🚨 Report', 'Report sender as scam',    '#ef4444');
    const safeBtn   = mkBtn('✓ Safe',    'Mark sender as safe',       '#22c55e');
    const blockBtn  = mkBtn('🚫 Block',  'Block this sender',         '#f97316');
    const dashBtn   = mkBtn('🔍 Details','Open in security panel',    '#6366f1');

    // Shared action runner: keeps toolbar visible during async request,
    // shows result, then auto-hides if mouse has already left the row.
    async function runAction(btn, label, msgType, payload) {
      if (btn.dataset.busy) return;
      btn.dataset.busy = '1';
      bar.dataset.pending = '1'; // block mouseleave from hiding toolbar mid-request
      const prev = btn.textContent;
      btn.textContent = '…';
      btn.disabled = true;
      const res = await AIOExtensionBridge.sendToRuntime(msgType, payload);
      btn.disabled = false;
      if (res && res.ok) {
        btn.textContent = prev + ' ✓';
        delete btn.dataset.busy;
      } else {
        btn.textContent = '✗ Failed';
        setTimeout(() => { btn.textContent = prev; delete btn.dataset.busy; }, 2000);
      }
      delete bar.dataset.pending;
      if (!row.matches(':hover')) bar.style.display = 'none';
    }

    // Report — blacklists sender directly (works without email in INTEMO DB)
    reportBtn.addEventListener('click', e => {
      e.stopPropagation(); e.preventDefault();
      if (!senderEmail) return;
      runAction(reportBtn, '🚨 Report', 'AIO_BLACKLIST_SENDER', {
        entry: senderEmail, entry_type: 'email', reason: 'Reported as scam via extension'
      }).then(() => {
        if (reportBtn.textContent.includes('✓')) {
          attachBadge(row, 'Scam', 'scam', false);
          highlightRow(row, 'scam');
        }
      });
    });

    // Safe — whitelists sender directly
    safeBtn.addEventListener('click', e => {
      e.stopPropagation(); e.preventDefault();
      if (!senderEmail) return;
      runAction(safeBtn, '✓ Safe', 'AIO_WHITELIST_SENDER', {
        entry: senderEmail, entry_type: 'email', notes: 'Marked safe via extension'
      }).then(() => {
        if (safeBtn.textContent.includes('✓')) {
          attachBadge(row, 'Normal', 'clean', false);
          row.style.background = '';
          row.style.borderLeft = '';
        }
      });
    });

    // Block — blacklists sender
    blockBtn.addEventListener('click', e => {
      e.stopPropagation(); e.preventDefault();
      if (!senderEmail) return;
      runAction(blockBtn, '🚫 Block', 'AIO_BLACKLIST_SENDER', {
        entry: senderEmail, entry_type: 'email', reason: 'Blocked via extension'
      });
    });

    // Details — opens security panel in a new tab
    dashBtn.addEventListener('click', e => {
      e.stopPropagation(); e.preventDefault();
      AIOExtensionBridge.sendToRuntime('AIO_OPEN_DASHBOARD', { path: '/security' });
    });

    bar.append(reportBtn, safeBtn, blockBtn, dashBtn);

    if (row.style.position !== 'relative' && row.style.position !== 'absolute') {
      row.style.position = 'relative';
    }
    row.appendChild(bar);

    row.addEventListener('mouseenter', () => { bar.style.display = 'flex'; });
    // Only hide if no action is in-flight
    row.addEventListener('mouseleave', () => { if (!bar.dataset.pending) bar.style.display = 'none'; });
  }

  // ── domain tooltip ─────────────────────────────────────────────────────────
  function removeTooltip() {
    if (activeTooltip) { activeTooltip.remove(); activeTooltip = null; }
  }

  // FIX: build tooltip with DOM methods — no innerHTML with API data (XSS)
  function showDomainTooltip(anchorEl, domain, data) {
    removeTooltip();
    const score = Number(data.confidence_score) || 0;
    const level = scoreToLevel(score);
    const c = levelColor(level);

    const tip = document.createElement('div');
    tip.className = 'intemo-domain-tooltip';
    tip.style.cssText = [
      'position:fixed', 'z-index:999999',
      'background:#0f172a', 'border:1px solid rgba(255,255,255,.14)',
      'border-radius:12px', 'padding:12px 14px',
      'font:13px system-ui', 'color:#f8fafc',
      'box-shadow:0 20px 60px rgba(0,0,0,.5)',
      'min-width:200px', 'max-width:280px', 'pointer-events:none'
    ].join(';');

    // Header row
    const header = document.createElement('div');
    header.style.cssText = 'display:flex;align-items:center;gap:8px;margin-bottom:8px';

    const dot = document.createElement('span');
    dot.style.cssText = `width:8px;height:8px;border-radius:50%;background:${c.dot};flex-shrink:0`;

    const domainEl = document.createElement('strong');
    domainEl.style.fontSize = '12px';
    domainEl.textContent = domain; // safe — textContent

    const levelEl = document.createElement('span');
    levelEl.style.cssText = `margin-left:auto;font-size:11px;padding:2px 7px;border-radius:999px;background:${c.bg};color:${c.color}`;
    levelEl.textContent = level;

    header.append(dot, domainEl, levelEl);

    // Score row
    const scoreRow = document.createElement('div');
    scoreRow.style.cssText = 'font-size:12px;color:#94a3b8;margin-bottom:0';

    const scoreLabel = document.createTextNode('Threat score: ');
    const scoreVal = document.createElement('strong');
    scoreVal.style.color = c.dot;
    scoreVal.textContent = `${score}/100`;

    scoreRow.appendChild(scoreLabel);
    scoreRow.appendChild(scoreVal);

    if (data.classification) {
      scoreRow.appendChild(document.createTextNode(` · ${data.classification}`));
    }

    tip.appendChild(header);
    tip.appendChild(scoreRow);

    // Reasons list
    const reasons = Array.isArray(data.reasons) ? data.reasons.slice(0, 3) : [];
    if (reasons.length) {
      scoreRow.style.marginBottom = '8px';
      const ul = document.createElement('ul');
      ul.style.cssText = 'margin:0;padding-left:16px';
      reasons.forEach(r => {
        const li = document.createElement('li');
        li.style.cssText = 'color:#94a3b8;font-size:11px';
        li.textContent = String(r); // safe
        ul.appendChild(li);
      });
      tip.appendChild(ul);
    }

    document.body.appendChild(tip);
    activeTooltip = tip;

    // Position below/above anchor
    const rect = anchorEl.getBoundingClientRect();
    let top = rect.bottom + 6, left = rect.left;
    if (top + 160 > innerHeight) top = rect.top - 160 - 6;
    if (left + 284 > innerWidth)  left = innerWidth - 294;
    top  = Math.max(4, top);
    left = Math.max(4, left);
    tip.style.top  = `${top}px`;
    tip.style.left = `${left}px`;
  }

  // FIX: renamed from wireDoaminHover (typo)
  function wireDomainHover(senderEl) {
    if (!senderEl || senderEl.__intemo_wired__) return;
    senderEl.__intemo_wired__ = true;
    const senderText = text(senderEl);
    const domainMatch = senderText.match(/@([\w.-]+)/);
    if (!domainMatch) return;
    const domain = domainMatch[1];

    senderEl.style.cursor = 'help';
    senderEl.addEventListener('mouseenter', async () => {
      const settings = await loadSettings();
      if (!settings.analyzeDomains) return;
      const cached = domainCache[domain];
      if (cached && Date.now() - cached.at < DOMAIN_CACHE_TTL) {
        showDomainTooltip(senderEl, domain, cached.data);
        return;
      }
      const res = await AIOExtensionBridge.sendToRuntime('AIO_ANALYZE_DOMAIN', { domain });
      if (res && res.ok && res.result) {
        domainCache[domain] = { data: res.result, at: Date.now() };
        showDomainTooltip(senderEl, domain, res.result);
      }
    });
    senderEl.addEventListener('mouseleave', () => setTimeout(removeTooltip, 300));
  }

  // ── row processing ─────────────────────────────────────────────────────────
  async function processRow(row) {
    const id = messageId(row);

    // Row was previously classified — re-attach badge if the webmail re-rendered it away
    if (processed.has(id)) {
      const cached = processed.get(id);
      if (cached && !row.querySelector('.intemo-badge')) {
        const settings = await loadSettings();
        const shouldBadge = settings.showBadges || (settings.showThreatBadges && cached.level !== 'clean');
        if (shouldBadge) attachBadge(row, cached.label, cached.level, settings.compactBadges);
        if (settings.highlightScamEmails && (cached.level === 'suspicious' || cached.level === 'scam')) {
          highlightRow(row, cached.level);
        }
        if (settings.showQuickActions && !row.querySelector('.intemo-toolbar')) {
          buildToolbar(row, id, cached.senderEmail);
        }
      }
      return;
    }

    // Mark as in-progress BEFORE any await to prevent concurrent duplicate requests
    processed.set(id, null);
    if (processed.size > 3000) processed.delete(processed.keys().next().value);

    const settings = await loadSettings();
    const data = rowData(row);
    if (!data) return;

    // Wire domain hover (no await — just attaches event listeners)
    if (settings.analyzeDomains) {
      const senderEl = row.querySelector(
        '.zF,.yW span[email],.sender,[data-sender],[class*="personName"],[class*="sender"]'
      );
      wireDomainHover(senderEl);
    }

    if (!settings.autoClassify) return;

    const response = await AIOExtensionBridge.sendToRuntime('AIO_CLASSIFY_EMAIL', {
      message_id: id, ...data
    });
    if (!response || !response.ok || !response.result) return;

    const result     = response.result;
    const confidence = Number(result.confidence) || 0;
    const score      = Math.round(confidence * 100);
    const level      = scoreToLevel(score);
    const label      = `${result.category || ''} ${score}%`.trim();

    // Cache result so re-renders can re-attach without hitting the API again
    processed.set(id, { label, level, senderEmail: data.sender_email });

    const shouldBadge = settings.showBadges || (settings.showThreatBadges && level !== 'clean');
    if (shouldBadge) {
      attachBadge(row, label, level, settings.compactBadges);
    }

    if (settings.highlightScamEmails && (level === 'suspicious' || level === 'scam')) {
      highlightRow(row, level);
    }

    if (settings.showQuickActions) {
      buildToolbar(row, id, data.sender_email);
    }
  }

  // ── keyboard shortcuts ─────────────────────────────────────────────────────
  document.addEventListener('keydown', async e => {
    if (!e.ctrlKey || !e.shiftKey) return;
    const settings = await loadSettings();
    if (!settings.keyboardShortcuts) return;
    if (e.key === 'S') {
      e.preventDefault();
      AIOExtensionBridge.sendToRuntime('AIO_OPEN_DASHBOARD', { path: '/security' });
    } else if (e.key === 'D') {
      e.preventDefault();
      AIOExtensionBridge.sendToRuntime('AIO_OPEN_DASHBOARD', { path: '/dashboard' });
    }
  });

  // ── inbox scanner ──────────────────────────────────────────────────────────
  async function scan() {
    const settings = await loadSettings();
    if (!settings.autoClassify && !settings.analyzeDomains) return;
    const selectors = isGmail()
      ? '.zA,.tr,[data-email-row]'
      : '.ms-List-cell,[class*="listItem"],[class*="mailListItem"]';
    const rows = Array.from(document.querySelectorAll(selectors)).slice(0, MAX_ROWS_PER_PASS);
    rows.forEach(row => processRow(row).catch(() => {}));
  }

  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(() => scan().catch(() => {}), 600);
  }

  const observer = new MutationObserver(schedule);
  observer.observe(document.documentElement, { childList: true, subtree: true });
  window.addEventListener('beforeunload', () => { observer.disconnect(); removeTooltip(); });
  document.addEventListener('click', removeTooltip);

  br().storage.onChanged.addListener((changes, area) => {
    if (area !== 'local' || !changes.settings) return;
    cachedSettings = { ...DEFAULT_SETTINGS, ...(changes.settings.newValue || {}) };
    settingsLoadedAt = Date.now();
    if (!cachedSettings.showBadges && !cachedSettings.showThreatBadges) {
      document.querySelectorAll('.intemo-badge').forEach(el => el.remove());
    }
    if (!cachedSettings.showQuickActions) {
      document.querySelectorAll('.intemo-toolbar').forEach(el => el.remove());
    }
    schedule();
  });

  schedule();
})();
