// INTEMO dashboard — shared list-state helpers.
//
// Extracted from enterprise-ui.js (Wave-17 pilot of the JS split) so that
// list/table renderers can call a single set of empty-state helpers. Loaded
// BEFORE enterprise-ui.js via a regular <script> tag, exposes both helpers
// as globals (matches the existing premium-ui.js / scam-panel.js loading
// pattern). No build step / no module loader required.
(function (global) {
  'use strict';

  function esc(v) {
    return String(v ?? '').replace(/[&<>"']/g, m => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[m]));
  }

  // Empty-row helper for <tbody> contexts — a <div> inside <tbody> is invalid
  // HTML, so this renders a single full-width row with the placeholder text.
  function renderEmptyRow(tbody, { colspan = 1, title = 'Nothing here yet', hint = '' } = {}) {
    if (!tbody) return;
    const body = hint
      ? `<strong>${esc(title)}</strong><br><span class="ops-table-state-hint">${esc(hint)}</span>`
      : esc(title);
    tbody.innerHTML = `<tr><td colspan="${esc(String(colspan))}" class="ops-table-state">${body}</td></tr>`;
  }

  // Empty-state helper for div-based lists — matches existing .empty-state CSS
  // (h3 + p layout). Optional action button.
  function renderEmptyState(el, { title = 'Nothing here yet', hint = '', action = null } = {}) {
    if (!el) return;
    const actionHtml = action && action.label
      ? `<button type="button" class="btn btn-subtle empty-state-action">${esc(action.label)}</button>`
      : '';
    el.innerHTML = `
      <div class="empty-state" role="status" aria-live="polite">
        <h3>${esc(title)}</h3>
        ${hint ? `<p>${esc(hint)}</p>` : ''}
        ${actionHtml}
      </div>`;
    if (action && action.onclick) {
      el.querySelector('.empty-state-action')?.addEventListener('click', action.onclick);
    }
  }

  global.renderEmptyState = renderEmptyState;
  global.renderEmptyRow = renderEmptyRow;
})(typeof globalThis !== 'undefined' ? globalThis : window);
