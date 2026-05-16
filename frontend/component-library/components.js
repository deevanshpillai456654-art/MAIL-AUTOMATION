export function statusPill(label, status = 'neutral') {
  const safe = String(label || '').replace(/[<>&]/g, c => ({'<':'&lt;','>':'&gt;','&':'&amp;'}[c]));
  return `<span class="aio-pill aio-${status}">${safe}</span>`;
}
export function mailboxCard(mailbox) {
  const esc = s => String(s || '').replace(/[<>&"']/g, c => ({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;',"'":'&#39;'}[c]));
  const name = esc(mailbox.name || mailbox.email || 'Mailbox');
  const provider = esc(mailbox.provider || 'provider');
  const status = esc(mailbox.status || 'unknown');
  return `<article class="aio-card"><strong>${name}</strong><small>${provider} · ${status}</small></article>`;
}
