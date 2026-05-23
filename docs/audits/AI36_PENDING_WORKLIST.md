# AI36 Pending Worklist

Generated: 2026-05-15

Scope: Current local workspace after the light frontend, scam filter, sync-first workflow logic, extension packaging, ONNX control plane, learning memory, and self-healing work.

## Count Summary

Pending here means work that is still worth tracking. It does not mean the current build is failing.

- Blocking defects pending: 0
- Validation failures pending: 0
- Explicit unfinished source markers pending: 0
- Product/backlog items pending: 1
- Manual external validation items pending: 2
- Total tracked pending items: 3

## Pending Items

| ID | Area | Priority | Status | Reason | Next action |
| --- | --- | --- | --- | --- | --- |
| P-003 | Provider QA | P1 | Pending | Current tests use local/fake mailbox paths; real sandbox OAuth/IMAP accounts are still an external validation step. | Run a sandbox provider matrix for Gmail, Outlook, Microsoft 365, Exchange, Yahoo, Zoho, iCloud, and IMAP/SMTP. |
| P-010 | Extension manual QA | P1 | Pending | Extension ZIPs exist, but each browser still needs manual install verification in the actual browser UI. | Install the rebuilt ZIPs in Chrome, Edge, Brave, Opera, Firefox, Safari-compatible flow, Gmail-only Chrome, and Outlook add-in. |
| P-011 | Installer manual QA | P1 | Pending | A clean Windows install/startup/uninstall smoke test is still outside the automated suite. | Run the installer on a clean Windows profile and verify service start, shortcuts, dashboard, extension connection, and uninstall cleanup. |

## Cleared Since Last Count

- C-001 Service runner stop command: `backend/run.py stop` now finds the local API listener on port `4597`, terminates it gracefully, and is covered by `tests/test_service_runner.py`.
- C-002 Dashboard visual smoke gate: `npm run visual:smoke` captures Dashboard, Accounts, Inbox, Scam, AI, Automations, Templates, Reports, Admin, and Settings screenshots, validates that captures are nonblank, and writes `artifacts/dashboard-visual-smoke/manifest.json`.
- C-003 ONNX evaluation activation gate: `OnnxAIControlPlane.evaluate_model(...)`, `/api/v1/ai/onnx/evaluate`, and `npm run onnx:evaluate` now evaluate labeled cases, store checksum-linked evaluation results, and only activate models that meet the configured accuracy threshold.
- C-004 Learning import conflict review: `OnnxAIControlPlane.preview_learning_import(...)`, `/api/v1/ai/learning/import/preview`, and the AI dashboard import panel now show conflicts, invalid rows, replace impact, and merge/replace choices before applying a learning-memory JSON import.
- C-005 AI admin governance gates: Learning export/import/preview/forget, model quarantine/recovery, and activate-on-evaluate now require admin role or explicit AI permission headers; the dashboard sends the admin role header for those governance actions.
- C-006 AI state backup/restore automation: Scheduled and manual backups now snapshot ONNX model registry, learning memory, and self-healing logs; admin APIs and dashboard controls can configure schedules, create backups, list retained backups, and restore a selected backup.
- C-007 Learning and model-health analytics: Reports now include scam false positives, scam false negatives, learning corrections, learned overrides, learning accuracy, ONNX fallback rate, runtime, active model, and quarantine count in summary, CSV export, and dashboard analytics cards.
- C-008 Local security hardening flow: `/api/v1/security/local-runtime` now checks loopback binding, external-bind override state, installer firewall setup availability, and returns the Windows Firewall setup command; the setup page surfaces the check.

## Not Pending From Latest Work

- Light admin/dashboard frontend fixes.
- Email provider image grid and brand logo integration.
- Scam filter page spacing and empty-state fixes.
- Scam/normal feedback flow into learning memory.
- Prebuilt scam, marketing, sales, social media, investor, support, and leads rule categories.
- Sync-first, reuse-existing-workflow behavior before generating folders, labels, rules, automations, or forwarding flows.
- Browser extension source packages and ZIP packages.
- `index.html`, Gmail extension CSS, and `scam-panel.html` static warning cleanup.
- ONNX runtime control plane with local fallback and self-healing quarantine behavior.
- ONNX model evaluation and activation gate.
- Learning memory import preview and conflict review UI.
- Admin role gates for sensitive learning and ONNX self-healing actions.
- Scheduled AI state backup and restore for learning memory, model registry, and self-healing logs.
- Learning accuracy and ONNX model-health analytics cards and CSV fields.
- Local-only runtime and Windows Firewall hardening setup/check flow.
- Settings tab and panel spacing/gap regression.
- Enterprise cleanup pass: safe generated-cache cleanup, router composition extraction, dashboard/static route extraction, lifespan extraction, middleware/CORS extraction, logging extraction, launch/port selection extraction, API provider detection extraction, refactor audit documentation, and visual smoke cold-start stabilization.
- Service runner stop command.
- Dashboard screenshot smoke regression gate.

## Verification To Keep Current

Run these before closing a release:

```powershell
npm run validate
python -B -m pytest -q -p no:cacheprovider
```

Latest local verification on 2026-05-15:

- `npm run validate`: passed, 100.0/100
- `python -B -m pytest -q -p no:cacheprovider`: passed, 103 tests
- `npm run visual:smoke`: captured 10 nonblank dashboard screenshots
- `npm run onnx:evaluate`: no local ONNX models found; fallback classifier remains active
