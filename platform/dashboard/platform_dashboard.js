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
  root.innerHTML = widgets.map(([title, body]) => `<article class="card"><h2>${title}</h2><p>${body}</p></article>`).join('');
}
