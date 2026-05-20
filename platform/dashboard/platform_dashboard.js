
window.setSafeHTML = function(el, html) {
  if (!el) return;
  if (typeof html !== 'string') {
    el.textContent = String(html);
    return;
  }
  const parser = new DOMParser();
  const doc = parser.parseFromString(html, 'text/html');
  const badTags = doc.querySelectorAll('script, iframe, object, embed, form, base, applet, meta, link');
  badTags.forEach(n => n.remove());
  const all = doc.querySelectorAll('*');
  for (let i = 0; i < all.length; i++) {
    const node = all[i];
    for (let j = node.attributes.length - 1; j >= 0; j--) {
      const attr = node.attributes[j];
      if (attr.name.toLowerCase().startsWith('on') || attr.name.toLowerCase() === 'javascript:') {
        node.removeAttribute(attr.name);
      }
    }
  }
  el.replaceChildren(...doc.body.childNodes);
};

const widgets = [
  ['Shipments', 'Unified shipment workspaces'],
  ['Approvals', 'Human-controlled automation queue'],
  ['WhatsApp Ops', 'Local-session operational messaging'],
  ['OCR', 'Document intelligence and review'],
  ['Tracking', 'Normalized shipment timelines'],
  ['Queues', 'Retry and dead-letter monitoring'],
  ['Search', 'AWB, BL, invoice, container lookup'],
  ['Security', 'Tenant isolation and audit logs'],
];
const root = document.getElementById('platform-widgets');
if (root) {
  window.setSafeHTML(
    root,
    widgets.map(([title, body]) => `<article class="card"><h2>${title}</h2><p>${body}</p></article>`).join('')
  );
}
