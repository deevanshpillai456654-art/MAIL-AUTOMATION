# Enterprise Cleanup And Refactor Audit

Date: 2026-05-15

This document records the safe cleanup baseline and the recommended refactor path for the INTEMO desktop email operations runtime.

## Current Architecture Map

- `backend/`: FastAPI desktop runtime, API routers, auth, sync, AI, rules, scheduler, security, storage, dashboard static files, and local data.
- `backend/main.py`: thin application composition root. It creates the FastAPI app and delegates logging, launch, middleware, lifespan, API router registration, and dashboard route registration.
- `backend/app/`: FastAPI composition helpers for logging setup, launch/port selection, middleware/CORS setup, lifespan orchestration, API router registration, and dashboard/static route registration.
- `backend/core/`: domain engines for mailbox orchestration, event stores, queues, replay, provider reliability, production readiness, policy, and scam filtering.
- `backend/ai/`: classifier, ONNX control plane, learning memory, self-healing, local-first AI runtime, queue, cache, vector, telemetry, and governance.
- `backend/api/`: REST boundaries for accounts, rules, reports, AI, admin, security, threat intelligence, runtime policy, health, updates, scheduler, extension connections, and assistant.
- `backend/dashboard/`: shipped admin dashboard, setup page, scam panel, assistant panel, PWA assets, runtime JS, offline queue, realtime client, and provider logos.
- `extensions/`: browser-specific extension folders. Most UI/runtime files are intentionally duplicated from `extensions/shared` during packaging.
- `gmail-extension/` and `outlook-addin/`: manual install packages and add-in source used by packaging and smoke tests.
- `scripts/`: build, installer, extension packaging, validation, visual smoke, ONNX evaluation, service sync, and security checks.
- `updater/`, `installer/`, `installers/`: update, rollback, startup repair, and Windows installer flows.
- `tests/`: regression coverage for API, auth, sync-first rules, scam learning, ONNX, backup, reports, dashboard visual smoke, extension packaging, and service runner.

## Scan Results

- Files scanned: 1,220 total files, 586 source-like files, 370 Python files.
- Python syntax baseline: no parse errors; `compileall` completed successfully.
- API route surface: 28 included routers plus direct app routes.
- Duplicate groups: 15 detected. Most are expected browser-extension copies and icon copies.
- Safe generated cleanup candidates found: 513 files, about 52.9 MB.
- Large generated/release artifacts: `build/pyinstaller`, visual smoke screenshots, website zip, local DB files, extension ZIP packages.
- Runtime data that must not be deleted automatically: `backend/data/*.db`, `backend/data/token.key`, `browser-extension-packages/*.zip`, installer payloads, packaged extension variants, and user/local mailbox state.

## Cleanup Completed

- Removed Python bytecode cache directories.
- Removed `.pytest_cache`.
- Removed `tmp_models_test` scratch state.
- Removed runtime log files from the root/logs area.
- Added ignore rules for regenerated `artifacts/`, `tmp_models_test/`, and validation reports.
- Restored the real dashboard light-theme meta tag so the baseline stayed green before cleanup work continued.
- Extracted API router composition into `backend/app/router_registry.py`, leaving all public `/api/v1` paths unchanged.
- Extracted dashboard, assistant, setup, admin, security, Outlook, icon, favicon, and root page routing into `backend/app/static_mounts.py`, leaving public page paths unchanged.
- Extracted startup/shutdown lifespan orchestration into `backend/app/lifespan.py`, preserving service discovery, offline first-run bootstrap, enterprise system startup, alert manager, scheduler, job runner, and shutdown cleanup behavior.
- Extracted CORS, GZip, and enterprise security middleware composition into `backend/app/middleware.py`, preserving local extension origins and production wildcard filtering.
- Extracted service logging setup into `backend/app/logging_config.py`, preserving redacted formatting and idempotent file/stream handler setup.
- Extracted launch-time port discovery and uvicorn settings into `backend/app/launcher.py`, preserving API port environment override behavior and discovery file writes.
- Extracted mailbox provider/domain detection into `backend/api/provider_detection.py`, preserving the `backend.api.routes.detect_mail_provider` compatibility export and account onboarding behavior.
- Stabilized dashboard visual smoke startup by launching screenshot-only uvicorn with lifespan disabled and waiting for DOM readiness instead of network idle.

## Target Architecture

Do not flatten this project blindly into a generic `/src` tree. The current package boundary is Python-first, and `backend` is already the import root used by tests, service launchers, installer scripts, and packaged builds.

Recommended enterprise structure:

```text
backend/
  app/                 # FastAPI composition, router registry, static mounts, lifespan
  api/                 # Thin REST adapters only
  core/                # Domain engines and business workflows
  modules/             # Feature modules: accounts, inbox, rules, scam, reports, admin
  ai/                  # ONNX, learning, local-first AI, self-healing
  services/            # External service facades and orchestration services
  integrations/        # Gmail, Outlook, IMAP, provider adapters
  database/            # Repository and migration boundaries
  security/            # Token vault, request signing, DLP, sandbox, SSRF, audit
  queues/              # Persistent jobs, scheduler tasks, retry/DLQ policies
  monitoring/          # Metrics, health, observability, diagnostics
  updates/             # Patch, rollback, startup repair, installer integration
  dashboard/           # Shipped static UI until a bundler is introduced
extensions/
  shared/              # Single source for extension UI/runtime code
  chrome|edge|...      # Generated/browser-specific manifests and packaged copies
scripts/
  build/
  validation/
  packaging/
  maintenance/
docs/
  architecture/
  operations/
  security/
  extensions/
```

## Refactor Plan

1. Continue the app composition layer without moving runtime files:
   - `backend/app/router_registry.py` is complete.
   - `backend/app/static_mounts.py` is complete.
   - `backend/app/lifespan.py` is complete.
   - `backend/app/middleware.py` is complete.
   - `backend/app/logging_config.py` is complete.
   - `backend/app/launcher.py` is complete.
   - keep `backend/main.py` as the stable launcher while delegating to those modules.

2. Split the largest files behind stable APIs:
   - `backend/api/routes.py` started with `backend/api/provider_detection.py`.
   - `backend/dashboard/enterprise-ui.js`
   - `backend/dashboard/enterprise-ui.css`
   - `backend/db/database.py`

3. Turn duplicated extension folders into generated artifacts:
   - keep `extensions/shared` as the source of truth.
   - generate browser folders through `scripts/package_browser_extensions.py`.
   - keep browser manifests as browser-specific inputs only.

4. Separate runtime data from source:
   - move local DBs and token keys to configured runtime home during startup.
   - keep sample fixtures under `tests/fixtures`.
   - never package `backend/data/emails.db` into releases.

5. Introduce service/repository seams:
   - API routers call feature services.
   - services call repositories, provider adapters, AI engines, and queues.
   - cross-module communication uses event bus/job queue contracts.

6. Add alias-like package boundaries for Python:
   - keep absolute imports from `backend.*`.
   - avoid deep relative imports.
   - expose stable interfaces through `backend.modules.<feature>`.

7. Add cleanup gates:
   - generated artifact audit.
   - import/syntax validation.
   - extension packaging check.
   - dashboard visual smoke.
   - ONNX evaluation.

## Deferred Or High-Risk Items

- Moving files into `/src` in one pass is high risk because launchers, installer scripts, static mounts, tests, and extension packaging assume the current paths.
- Removing duplicate extension files directly is high risk until packaging makes browser folders fully generated.
- Removing website/build/dist artifacts is high risk because this workspace also stores release and manual-install deliverables.
- Removing local DBs or token files is unsafe without explicit backup and migration.

## Remaining Technical Debt

- Largest API and dashboard files still need additional feature boundaries.
- Large dashboard JS/CSS files without module boundaries.
- Multiple overlapping API router domains.
- Extension source and generated output are not fully separated.
- Build/release artifacts live next to source.
- CLI scripts use `print`; production services should use structured logging, while CLI scripts can keep console output.
- Some empty placeholder directories need ownership decisions before deletion.

## Recommended Next Safe Phase

Next, continue splitting `backend/api/routes.py` by extracting attachment/account presentation helpers, then move to dashboard JS/CSS module boundaries. Keep public paths and installer/package assumptions unchanged.
