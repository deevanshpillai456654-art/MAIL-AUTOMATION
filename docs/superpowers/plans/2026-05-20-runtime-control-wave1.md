# Runtime Control Wave 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a lightweight runtime control plane that gates services, agents, AI modes, frontend behavior, and low-resource operation without rewriting the platform.

**Architecture:** Create `backend/core/runtime_control.py` as the single policy resolver for runtime profile, AI mode, service registry, agent registry, and router visibility. Wire it into config, lifespan startup, router registration, and a small `/api/v1/runtime` API for the dashboard.

**Tech Stack:** Python, FastAPI, SQLite-free in-memory policy resolution, existing static dashboard JavaScript.

---

### Task 1: Runtime Policy Core

**Files:**
- Create: `backend/core/runtime_control.py`
- Modify: `backend/config/__init__.py`
- Test: `tests/test_runtime_control_wave1.py`

- [ ] Write tests for `low_resource`, `lite`, `standard`, and `enterprise` profiles.
- [ ] Implement `RuntimeControl`, `RuntimeProfile`, `AI_MODE`, `is_service_enabled`, `is_agent_enabled`, and startup limits.
- [ ] Expose config constants from environment variables.

### Task 2: Startup and Router Gating

**Files:**
- Modify: `backend/app/lifespan.py`
- Modify: `backend/app/router_registry.py`
- Test: `tests/test_runtime_control_wave1.py`

- [ ] Write tests proving low-resource profile skips heavy autostart services.
- [ ] Write tests proving disabled routers are not registered.
- [ ] Patch startup to use a small `start_optional_service` helper.
- [ ] Patch router registration to consult runtime policy.

### Task 3: Runtime API and Frontend State

**Files:**
- Create: `backend/api/runtime_control.py`
- Modify: `backend/app/router_registry.py`
- Modify: `backend/dashboard/enterprise-ui.js`
- Test: `tests/test_runtime_control_wave1.py`

- [ ] Write API tests for `/api/v1/runtime/profile`, `/api/v1/runtime/services`, and `/api/v1/runtime/agents`.
- [ ] Return AI mode, low-resource state, service toggles, agent toggles, limits, and frontend flags.
- [ ] Patch dashboard JS to fetch runtime profile and apply low-resource CSS/state flags.

### Task 4: Verification

**Files:**
- Test: full suite

- [ ] Run focused tests.
- [ ] Run Python compile checks.
- [ ] Run dashboard JS syntax check.
- [ ] Run full pytest suite.
