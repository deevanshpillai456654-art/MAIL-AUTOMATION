# Tally Connector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a working Tally connector to the existing AI36 FastAPI connector ecosystem.

**Architecture:** Implement Tally in the current Python/FastAPI and connector-panel stack. The marketplace exposes a Tally connector, the dashboard renders it from install state, and `/api/v1/tally/*` endpoints provide connection, XML, sync, analytics, logs, and discovery operations backed by SQLite tables.

**Tech Stack:** FastAPI, SQLite, Python standard XML/HTTP libraries, existing connector panel HTML/CSS/JS, pytest.

---

### Task 1: Marketplace And Plugin Registration

**Files:**
- Modify: `platform/connectors-panel/backend/marketplace.py`
- Create: `platform/connectors-panel/plugins/tally/plugin.json`
- Create: `platform/connectors-panel/plugins/tally/module.py`
- Test: `tests/test_tally_connector_marketplace.py`

- [x] Add a `tally` marketplace catalog item in category `accounting` with Tally-specific description, permissions, events, OAuth disabled, webhook enabled, and Tally domain favicon.
- [x] Add a plugin manifest and module exposing metadata and a `test_connection` placeholder that validates host/port/company config.
- [x] Test that Tally appears in the marketplace and no unrelated accounting connector is added by this task.

### Task 2: Tally Service And Tables

**Files:**
- Create: `backend/api/tally.py`
- Modify: `backend/api/routes.py`
- Test: `tests/test_tally_api.py`

- [x] Add SQLite table initialization for `tally_connections`, `tally_sync_jobs`, `tally_companies`, `tally_ledgers`, `tally_vouchers`, `tally_inventory`, `tally_gst_reports`, `tally_audit_logs`, `tally_workflows`, and `tally_notifications`.
- [x] Implement endpoints for connect, disconnect, test, discovery, companies, ledgers, vouchers, inventory, GST, sync, analytics, logs, and export.
- [x] Use encrypted config storage with existing local crypto helper when available and deterministic fallback for tests.
- [x] Test endpoint behavior without requiring a live Tally installation.

### Task 3: Tally XML Helpers

**Files:**
- Create: `backend/services/connectors/tally/xml.py`
- Create: `backend/services/connectors/tally/client.py`
- Create: `backend/services/connectors/tally/__init__.py`
- Test: `tests/test_tally_xml.py`

- [x] Build XML envelopes for company, ledger, voucher, inventory, and GST export queries.
- [x] Parse Tally XML responses into dictionaries/lists for companies, ledgers, vouchers, stock items, and GST summaries.
- [x] Add timeout/retry-safe HTTP POST client for local and remote Tally XML API.

### Task 4: Connector Panel UI

**Files:**
- Modify: `platform/connectors-panel/frontend/app.js`
- Modify: `platform/connectors-panel/frontend/index.html`
- Modify: `platform/connectors-panel/frontend/styles.css`
- Test: `tests/test_tally_connector_frontend.py`

- [x] Add Tally card-specific configure modal fields for localhost, remote, and LAN discovery modes.
- [x] Add Tally dashboard section with connection status, company, last sync, health, workflows, errors, version, server mode, logs, and actions.
- [x] Add frontend tests that assert the Tally UI hooks, actions, and labels exist.

### Task 5: Verification

**Files:**
- Test: all changed tests

- [x] Run focused Tally tests.
- [x] Run connector/dashboard tests.
- [x] Run the full pytest suite.
- [ ] Restart the local backend and verify `/dashboard`, `/connectors-panel`, `/api/connector-panel/marketplace/connectors`, and `/api/v1/tally/status` respond.
