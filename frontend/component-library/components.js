/**
 * INTEMO Component Library
 * Pure HTML-string builders for use in enterprise-ui.js view renderers.
 * All functions return sanitised HTML strings — never trust raw input.
 * Import: import { badge, kpiCard, ... } from '/frontend/component-library/components.js';
 */

// ── Escape helper ─────────────────────────────────────────────────────────────
const _e = s => String(s ?? '').replace(/[<>&"']/g, c => (
  { '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;', "'": '&#39;' }[c]
));

// ── Legacy exports (backwards compat) ────────────────────────────────────────

export function statusPill(label, status = 'neutral') {
  return `<span class="aio-pill aio-${_e(status)}">${_e(label)}</span>`;
}

export function mailboxCard(mailbox) {
  const name     = _e(mailbox.name || mailbox.email || 'Mailbox');
  const provider = _e(mailbox.provider || 'provider');
  const status   = _e(mailbox.status  || 'unknown');
  return `<article class="aio-card"><strong>${name}</strong><small>${provider} · ${status}</small></article>`;
}

// ── Badge ─────────────────────────────────────────────────────────────────────

/**
 * badge('Active', 'success') → <span class="badge badge-success">Active</span>
 * variants: success | warn | danger | info | ai | neutral
 */
export function badge(label, variant = 'neutral') {
  return `<span class="badge badge-${_e(variant)}">${_e(label)}</span>`;
}

// ── Status dot ────────────────────────────────────────────────────────────────

/**
 * statusDot('online') → <span class="status-dot online" aria-hidden="true"></span>
 * states: online | warn | offline | idle | pending
 */
export function statusDot(state = 'idle') {
  return `<span class="status-dot ${_e(state)}" aria-hidden="true"></span>`;
}

// ── KPI card ──────────────────────────────────────────────────────────────────

/**
 * kpiCard({ label, value, delta, deltaDir, accent })
 * deltaDir: 'up' | 'down' | 'neutral'
 * accent:   '' | 'health' | 'ai' | 'sync'
 */
export function kpiCard({ label = '', value = '—', delta = '', deltaDir = 'neutral', accent = '' } = {}) {
  const accentClass = accent ? ` card-kpi-accent--${_e(accent)}` : '';
  return `
<div class="card-kpi" role="article">
  <div class="card-kpi-accent${accentClass}"></div>
  <div class="card-kpi-label">${_e(label)}</div>
  <div class="card-kpi-value">${_e(value)}</div>
  <div class="card-kpi-delta ${_e(deltaDir)}">${_e(delta)}</div>
</div>`.trim();
}

// ── Stat row ──────────────────────────────────────────────────────────────────

/**
 * statRow({ label, sub, value, tone })
 * tone: '' | 'ok' | 'warn' | 'bad'
 */
export function statRow({ label = '', sub = '', value = '—', tone = '' } = {}) {
  const subHtml  = sub   ? `<div class="dash-stat-sub">${_e(sub)}</div>`         : '';
  const toneAttr = tone  ? ` ${_e(tone)}`                                        : '';
  return `
<div class="dash-stat-row">
  <div><div class="dash-stat-label">${_e(label)}</div>${subHtml}</div>
  <div class="dash-stat-val${toneAttr}">${_e(value)}</div>
</div>`.trim();
}

// ── Progress row ──────────────────────────────────────────────────────────────

/**
 * progressRow({ label, value, pct, color })
 * color: '' (accent) | 'green' | 'amber' | 'red' | 'purple'
 */
export function progressRow({ label = '', value = '', pct = 0, color = '' } = {}) {
  const width      = Math.min(100, Math.max(0, Number(pct) || 0));
  const colorClass = color ? ` ${_e(color)}` : '';
  return `
<div class="progress-row">
  <div class="pi-row">
    <span class="pi-label">${_e(label)}</span>
    <span class="pi-val">${_e(value)}</span>
  </div>
  <div class="progress-bar">
    <div class="progress-fill${colorClass}" style="width:${width}%"></div>
  </div>
</div>`.trim();
}

// ── Activity item ─────────────────────────────────────────────────────────────

/**
 * activityItem({ title, meta, time, iconClass })
 * iconClass: optional extra class on the .activity-icon element
 */
export function activityItem({ title = '', meta = '', time = '', iconClass = '' } = {}) {
  const iconExtra = iconClass ? ` ${_e(iconClass)}` : '';
  const metaHtml  = meta ? `<div class="activity-meta">${_e(meta)}</div>` : '';
  const timeHtml  = time ? `<div class="activity-time">${_e(time)}</div>` : '';
  return `
<div class="activity-item" role="listitem">
  <div class="activity-icon${iconExtra}" aria-hidden="true">
    <svg width="14" height="14" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><circle cx="10" cy="10" r="4"/></svg>
  </div>
  <div class="activity-body">
    <div class="activity-title">${_e(title)}</div>
    ${metaHtml}
  </div>
  ${timeHtml}
</div>`.trim();
}

// ── Empty state ───────────────────────────────────────────────────────────────

/**
 * emptyState({ message, action })
 * action: optional { label, id } for a CTA button
 */
export function emptyState({ message = 'Nothing here yet.', action = null } = {}) {
  const btn = action
    ? `<button type="button" class="btn btn-primary btn-sm" id="${_e(action.id)}">${_e(action.label)}</button>`
    : '';
  return `
<div class="empty-state">
  <div class="empty-state-icon" aria-hidden="true">
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round">
      <circle cx="10" cy="10" r="7"/><path d="M10 7v4M10 13h.01"/>
    </svg>
  </div>
  <p>${_e(message)}</p>
  ${btn}
</div>`.trim();
}

// ── Toast ─────────────────────────────────────────────────────────────────────

/**
 * showToast(message, type, durationMs)
 * type: 'ok' | 'error' | 'warn'
 * Appends a toast to document.body and removes it after durationMs.
 */
export function showToast(message, type = 'ok', durationMs = 3000) {
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.setAttribute('role', 'status');
  el.setAttribute('aria-live', 'polite');
  el.innerHTML = `<span class="toast-dot" aria-hidden="true"></span>${_e(message)}`;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), durationMs);
}

// ── Spinner ───────────────────────────────────────────────────────────────────

/** spinner() → inline spinner HTML */
export function spinner() {
  return `<span class="spinner" role="status" aria-label="Loading"></span>`;
}

// ── Table row ─────────────────────────────────────────────────────────────────

/**
 * tableRow(cells, options)
 * cells: string[] — already-escaped or safe values
 * options.clickId: optional id attribute on the <tr>
 */
export function tableRow(cells = [], { clickId = '' } = {}) {
  const id  = clickId ? ` id="${_e(clickId)}"` : '';
  const tds = cells.map(c => `<td>${c}</td>`).join('');
  return `<tr${id}>${tds}</tr>`;
}

/**
 * tableHead(headers)
 * headers: string[] — column heading labels
 */
export function tableHead(headers = []) {
  const ths = headers.map(h => `<th>${_e(h)}</th>`).join('');
  return `<thead><tr>${ths}</tr></thead>`;
}
