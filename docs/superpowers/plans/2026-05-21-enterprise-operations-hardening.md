# Enterprise Operations Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a production operations control plane that hardens scalability, deployment, monitoring, recovery, low-resource operation, and maintainability across the platform.

**Architecture:** Add focused backend core modules plus an authenticated API router. Keep implementation lightweight and on-demand so it is safe for Windows 11 office systems and 4GB RAM clients.

**Tech Stack:** Python, FastAPI, Pydantic-style dictionaries, SQLite inspection, existing runtime policy and persistent queue modules, pytest.

---

### Task 1: Enterprise Operations Core

**Files:**
- Create: `backend/core/enterprise_operations.py`
- Test: `tests/test_enterprise_operations.py`

- [x] Write failing tests for service state persistence, restart protection, queue diagnostics, deployment validation, and report generation.
- [x] Implement `ServiceStateStore`, `QueueInspector`, `DeploymentValidator`, and `EnterpriseOperationsCenter`.
- [x] Verify tests pass.

### Task 2: Operations API Router

**Files:**
- Create: `backend/api/enterprise_operations.py`
- Modify: `backend/app/router_registry.py`
- Test: `tests/test_enterprise_operations_api.py`

- [x] Write failing API tests for overview, service controls, queue report, deployment validation, update diagnostics, observability dashboard, and final reports.
- [x] Implement authenticated API endpoints.
- [x] Register the router behind `/api/v1`.
- [x] Verify tests pass.

### Task 3: Queue Safety Upgrade

**Files:**
- Modify: `backend/core/persistent_job_queue.py`
- Test: `tests/test_enterprise_operations.py`

- [x] Write failing tests for dead-letter counts and queue cleanup.
- [x] Add dead-letter status semantics, per-queue counts, stale lease reporting, and safe cleanup helpers.
- [x] Verify tests pass.

### Task 4: Logging and Resource Diagnostics

**Files:**
- Modify: `backend/app/logging_config.py`
- Modify: `backend/core/enterprise_operations.py`
- Test: `tests/test_enterprise_operations.py`

- [x] Write failing tests proving log rotation handler is configured and low-resource recommendations are emitted.
- [x] Switch service logging to rotating file handler.
- [x] Add CPU, memory, log, cache, and cleanup diagnostics.
- [x] Verify tests pass.

### Task 5: Final Validation Reports

**Files:**
- Create: `ENTERPRISE_OPERATIONS_HARDENING_REPORT.md`
- Test: `tests/test_enterprise_operations.py`

- [x] Generate the 18 requested report sections from the implemented diagnostics.
- [x] Verify the report builder includes each required section and remaining technical debt.
- [x] Run targeted tests, then full validation command if feasible.

