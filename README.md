# AI Email Organizer — Local-First Enterprise Email Operations Platform

> Local-first enterprise email operations workspace for connected inboxes, smart classification, rules automation, scam/threat intelligence, reporting, admin governance, browser extensions, connector/plugin workflows, and Windows desktop/runtime deployment.

![AI Email Organizer Dashboard](./docs/screenshots/dashboard.png)

## Repository summary

AI Email Organizer is a client-ready, local-first email operations platform designed for teams that need to manage multiple inboxes, classify messages, apply automation rules, monitor account health, detect scams, generate operational reports, and control governance from one private workspace.

The package is built around a Python/FastAPI backend, native JavaScript dashboard/frontend files, browser extension packages, an Electron desktop shell, local runtime scripts, installer assets, and a plugin-oriented platform layer for connectors, logistics operations, tracking, OCR/search, WhatsApp workflows, and approval-first automation.

## GitHub About description

```text
Local-first enterprise AI email operations platform with inbox sync, OAuth/IMAP accounts, rules automation, ONNX classification, scam/threat intelligence, reports, admin governance, browser extensions, connector plugins, and Windows desktop packaging.
```

## Suggested GitHub topics

```text
email-client, email-automation, inbox-management, fastapi, python, javascript, electron, browser-extension, gmail, outlook, oauth2, imap, onnx, local-first, workflow-automation, phishing-detection, enterprise-email, reporting, windows-desktop
```

## Screenshots

These screenshots are taken from the actual app visual smoke artifacts included in the ZIP package.

> **Image link fix:** keep this `README.md` in the repository root and keep the screenshot files in `./docs/screenshots/`. The package is now flattened so GitHub can render the images directly.

### Dashboard

![Dashboard](./docs/screenshots/dashboard.png)

### Connected accounts

![Accounts](./docs/screenshots/accounts.png)

### Inbox operations

![Inbox](./docs/screenshots/inbox.png)

### AI processing

![AI Processing](./docs/screenshots/ai.png)

### Automations

![Automations](./docs/screenshots/automations.png)

### Templates

![Templates](./docs/screenshots/templates.png)

### Reports

![Reports](./docs/screenshots/reports.png)

### Admin governance

![Admin](./docs/screenshots/admin.png)

### Settings

![Settings](./docs/screenshots/settings.png)

### Scam / threat panel

![Scam Panel](./docs/screenshots/scam.png)

## Core capabilities

### 1. Unified email workspace

- Dashboard for inbox health, sync health, queued emails, active automations, failed syncs, and operational pulse.
- Multi-account email onboarding and provider detection.
- Gmail, Outlook/Microsoft, Yahoo, Zoho, Yandex, iCloud, AOL, Proton, Fastmail, Exchange, custom IMAP, and custom provider-oriented flows.
- Account persistence and reconnect/recovery-oriented backend modules.
- Inbox list and detail handling with category/status metadata and attachment support.

### 2. OAuth, IMAP, and provider handling

- Universal OAuth flow support.
- Gmail OAuth, Outlook OAuth, universal provider auth, IMAP auth, token storage, token crypto, state validation, PKCE, provider diagnostics, and OAuth lifecycle/recovery modules.
- Provider capability registry and provider failover/reliability helpers.
- Local callback handling for desktop/local deployment.

### 3. Smart classification and AI processing

- Email classifier and domain-intelligence modules.
- ONNX runtime control plane and model routing hooks.
- Adaptive AI pipeline, learning engine, embeddings, safety/governance, cost governance, provider rate limits, human review queue, tenant memory, and local-first AI runtime helpers.
- Scam/normal verdict and feedback-oriented workflows.

### 4. Rules and automation engine

- Rule creation and execution backend.
- Action executor for automation workflows.
- Email forwarding support.
- Scheduler and task queue support for background sync/automation.
- Persistent job queue and event bus foundations.

### 5. Scam, security, and threat intelligence

- Scam filter and threat intelligence API layers.
- Request signing, token vault, token rotation, credential encryption, DLP, redaction, sandboxing, SSRF protection, audit logging, tenant-boundary guard, and SBOM/security tooling.
- Security middleware, request governance, rate limiting, and safety-oriented modules.

### 6. Reporting, analytics, and templates

- Enterprise reports API and dashboard reports view.
- Analytics engine and production scorecard modules.
- Template library and enterprise templates API.
- Export/data exporter support.

### 7. Admin and governance

- Admin dashboard and enterprise governance API modules.
- Production readiness, production guardrails, final validation, granular scorecard, compliance engine, policy engine, and runtime policy helpers.
- User/admin-facing settings screens and operational controls.

### 8. Realtime and resilience

- WebSocket and realtime modules for alerts, pressure management, replay windows, resumable sessions, reconnect governance, reconciliation, and adaptive buffering.
- Crash recovery, backup/recovery, orphan recovery, sync recovery, mailbox quarantine, stale lock cleanup, idempotency, distributed scheduler/coordinator, and event retention/archival modules.

### 9. Browser and mail-client extensions

- Chrome, Edge, Brave, Firefox, Opera, and Safari extension folders.
- Gmail extension package.
- Outlook add-in package.
- Extension packaging scripts and generated browser extension ZIP packages.

### 10. Desktop and Windows deployment

- Electron desktop wrapper.
- Windows batch launch scripts.
- PyInstaller build scripts/specs.
- Inno Setup installer script and installer helper scripts.
- Offline installer/deployment folders and startup/service scripts.

### 11. Connector and plugin platform layer

The `/platform` layer provides connector/plugin foundations without rewriting the core app:

- Connector panel backend and frontend.
- Plugin runtime, plugin registry, sandbox, permissions, lifecycle, and queue helpers.
- Connector SDK and credentials/telemetry helpers.
- Plugins for approvals, communication timeline, connectors, OCR, search, tracking, WhatsApp operations, and shipment workspace.
- Tracking normalization/aggregation and sample tracking ingest.
- AI automation agents for approval, communication, OCR, search, workflow, and orchestration.

## Tech stack

| Area | Technology |
|---|---|
| Backend | Python, FastAPI, Pydantic, Uvicorn |
| AI / ML | ONNX Runtime, scikit-learn, NumPy, local-first AI helpers |
| Frontend | Native JavaScript, HTML, CSS |
| Desktop shell | Electron |
| Email connectivity | Gmail OAuth, Outlook OAuth, IMAP/SMTP-oriented account handling |
| Extensions | Browser extension packages, Gmail extension, Outlook add-in |
| Packaging | Windows batch scripts, PyInstaller, Inno Setup, offline installer assets |
| Runtime storage | Local runtime data folders and local database files |
| Security | Token crypto, credential encryption, audit, request signing, sandboxing, DLP, redaction |
| Testing | Pytest test suite, validation scripts, visual smoke scripts |

## Repository inventory from the ZIP

- Python files: `582`
- JavaScript files: `68`
- HTML files: `26`
- CSS files: `16`
- JSON files: `50`
- Markdown files: `45`
- PNG screenshots/assets: `49`
- Browser/client package ZIP files: `9`
- TypeScript / TSX / TXS files: `0`

## High-level folder structure

```text
.
├── backend/                  # FastAPI app, auth, sync, AI, rules, security, storage, realtime, dashboard
├── frontend/                 # Frontend component/design/theme/layout foundations
├── extensions/               # Chrome, Edge, Brave, Firefox, Opera, Safari extension sources
├── gmail-extension/          # Gmail extension files
├── outlook-addin/            # Outlook add-in files
├── desktop/electron/         # Electron desktop wrapper
├── platform/                 # Connector/plugin/logistics operations layer
├── browser-extension-packages/# Prebuilt extension ZIP packages
├── installer/                # Installer definition and deployment tooling
├── installers/               # Offline/enterprise deployment package docs
├── scripts/                  # Build, package, validation, service, security, smoke-test scripts
├── tests/                    # Pytest coverage for app, auth, frontend, sync, security, extensions
├── docs/                     # Architecture, auth, security, offline, API docs
├── artifacts/                # Visual smoke screenshots and validation artifacts
├── patches/                  # ZIP patch staging
├── backups/                  # Backup staging
└── requirements*.txt         # Runtime/dev/prod Python dependencies
```

## Quick start for local development

### Windows

```bat
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
start.bat
```

Then open:

```text
http://127.0.0.1:4597/dashboard
```

Setup page:

```text
http://127.0.0.1:4597/setup
```

### Manual backend start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m backend.main
```

### Desktop wrapper

```bash
cd desktop/electron
npm install
npm start
```

## Required environment configuration

Create a local `.env` file from the included example values and fill provider credentials on the target machine.

Important values:

```env
API_HOST=127.0.0.1
API_PORT=4597
APP_ENV=local

GMAIL_CLIENT_ID=
GMAIL_CLIENT_SECRET=
GMAIL_REDIRECT_URI=http://127.0.0.1:4597/api/v1/oauth/google/callback

OUTLOOK_CLIENT_ID=
OUTLOOK_CLIENT_SECRET=
OUTLOOK_REDIRECT_URI=http://127.0.0.1:4597/api/v1/oauth/microsoft/callback

YAHOO_CLIENT_ID=
YAHOO_CLIENT_SECRET=
YAHOO_REDIRECT_URI=http://127.0.0.1:4597/api/v1/oauth/yahoo/callback

ZOHO_CLIENT_ID=
ZOHO_CLIENT_SECRET=
ZOHO_REDIRECT_URI=http://127.0.0.1:4597/api/v1/oauth/zoho/callback
```

Do not commit real OAuth client secrets, token keys, local databases, logs, account data, or runtime artifacts.

## Useful commands

```bash
npm test
npm run validate
npm run visual:smoke
npm run onnx:evaluate
```

Direct Python commands:

```bash
python -B -m pytest -q -p no:cacheprovider
python -B scripts/validate_ai36_production_cleanup.py
python -B scripts/dashboard_visual_smoke.py
python -B scripts/evaluate_onnx_models.py
```

Browser extension package generation:

```bash
python -B scripts/package_browser_extensions.py
```

Installer/build helpers:

```bat
scripts\build.bat
scripts\build_installer.bat
scripts\diagnose_installer_build.bat
```

## GitHub publishing checklist

Before pushing this repository publicly or sharing it with clients, review and clean the repository:

- Keep source code, docs, screenshots, scripts, and examples.
- Do not commit `.env`, `.env.local`, real OAuth credentials, token keys, `.db` files, logs, private mail data, local attachments, generated caches, or build outputs.
- Keep actual screenshots under `docs/screenshots/` so GitHub can render them in the README.
- Keep `.gitignore` active and confirm it excludes local runtime files.
- Regenerate screenshots after major UI changes.
- Run `npm test` and `npm run validate` before tagging a release.
- Add a license file before publishing publicly.
- Add clear client/setup documentation for OAuth provider setup.
- Add a release note explaining the current package version and known limitations.

## Security notes

This project handles email, OAuth, attachments, and potentially sensitive user data. Treat it as a private/security-sensitive repository unless it has been fully scrubbed.

Recommended private files to exclude:

```text
.env
.env.local
*.key
*.pem
*.db
*.db-journal
logs/
data/
backend/data/
local-service/data/
local-service/logs/
artifacts/
__pycache__/
.pytest_cache/
build/
dist/
*.exe
*.dmg
*.app
```

If the app is being prepared for a public GitHub repo, do a secret scan before the first push.

## Validation and QA files included in the package

The ZIP includes these QA/validation documents:

- `AI36_FRONTEND_FIX_VALIDATION_REPORT.md`
- `AI36_FRONTEND_WARNING_FIX_REPORT.md`
- `AI36_MISSING_FILE_REPORT.md`
- `AI36_PACKAGE_MANIFEST.json`
- `ASSISTANT_ARCHITECTURE_REPORT.md`
- `SCALABILITY_REPORT.md`
- `SECURITY_HARDENING_REPORT.md`

Use those files as internal evidence and release-check documents. Re-run tests on the target machine before publishing a production release.

## Version notes

- Root package version: `9.8.1-ai36-frontend-fix`
- Desktop Electron package version: `9.7.0`
- Browser extension packages include `v14.0.1B` and Outlook add-in `v9.7.0` package names.

## License

Add the correct license before publishing. For private/client delivery, keep the repository private unless all branding, credentials, data, and proprietary files are approved for release.
