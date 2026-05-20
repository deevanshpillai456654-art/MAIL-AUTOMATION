"""Tests for the autonomous operational agents (backend/api/agents.py)."""
import asyncio
import sqlite3
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ── DB seeding ────────────────────────────────────────────────────────────────

def _seed_main_db(path: str, emails: int = 5, active_threats: int = 0):
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE IF NOT EXISTS emails (
            id INTEGER PRIMARY KEY, account_id INTEGER, category TEXT,
            confidence REAL DEFAULT 0.9, is_read INTEGER DEFAULT 0,
            is_processed INTEGER DEFAULT 1, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY, status TEXT, last_sync_at TEXT
        );
        CREATE TABLE IF NOT EXISTS threat_lookalike_alerts (
            id INTEGER PRIMARY KEY, status TEXT, confidence_score INTEGER,
            impersonated_brand TEXT, detected_domain TEXT, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS mailbox_quarantine (id INTEGER PRIMARY KEY);
    """)
    now = datetime.now(timezone.utc).isoformat()
    for i in range(emails):
        con.execute(
            "INSERT INTO emails (account_id, category, created_at) VALUES (1, 'Work', ?)",
            (now,),
        )
    for i in range(active_threats):
        con.execute(
            "INSERT INTO threat_lookalike_alerts (status, confidence_score, impersonated_brand, detected_domain, created_at) VALUES (?,?,?,?,?)",
            ("active", 85, "PayPal", f"paypa1-{i}.com", now),
        )
    con.commit()
    con.close()


def _seed_wf_db(path: str):
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE IF NOT EXISTS workflows (
            id TEXT PRIMARY KEY, name TEXT, is_active INTEGER DEFAULT 1,
            trigger_cfg TEXT, steps_json TEXT, run_count INTEGER DEFAULT 0,
            success_count INTEGER DEFAULT 0, fail_count INTEGER DEFAULT 0,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS workflow_executions (
            id TEXT PRIMARY KEY, workflow_id TEXT, status TEXT,
            trigger_type TEXT, created_at TEXT, started_at TEXT,
            finished_at TEXT, error TEXT, step_count INTEGER,
            steps_done INTEGER, duration_ms INTEGER
        );
    """)
    con.commit()
    con.close()


# ── fixture ───────────────────────────────────────────────────────────────────

def _patch_env(monkeypatch, tmp_path):
    """Patch both the intelligence module (where agents read data) and event bus."""
    from backend.api import operational_intelligence as oi

    main_db = str(tmp_path / "main.db")
    wf_db   = str(tmp_path / "wf.db")
    _seed_main_db(main_db, emails=10, active_threats=2)
    _seed_wf_db(wf_db)

    monkeypatch.setattr(oi, "DB_PATH", main_db)
    monkeypatch.setattr(oi, "_WORKFLOWS_DB", wf_db)
    monkeypatch.setattr(oi, "_engine", oi.IntelligenceEngine())

    async def _noop_emit(*a, **kw):
        return "test-event-id"

    monkeypatch.setattr("backend.api.event_bus.emit", _noop_emit)
    return main_db, wf_db


# ── agent unit tests ──────────────────────────────────────────────────────────

def test_inbox_monitor_agent_run_cycle_does_not_raise(tmp_path, monkeypatch):
    _patch_env(monkeypatch, tmp_path)
    from backend.api.agents import InboxMonitorAgent

    agent = InboxMonitorAgent()

    async def _go():
        await agent.run_cycle()

    asyncio.run(_go())


def test_threat_watch_agent_run_cycle_does_not_raise(tmp_path, monkeypatch):
    _patch_env(monkeypatch, tmp_path)
    from backend.api.agents import ThreatWatchAgent

    agent = ThreatWatchAgent()

    async def _go():
        await agent.run_cycle()

    asyncio.run(_go())


def test_workflow_orchestrator_agent_run_cycle_does_not_raise(tmp_path, monkeypatch):
    _patch_env(monkeypatch, tmp_path)
    from backend.api.agents import WorkflowOrchestratorAgent

    agent = WorkflowOrchestratorAgent()

    async def _go():
        await agent.run_cycle()

    asyncio.run(_go())


def test_security_posture_agent_run_cycle_does_not_raise(tmp_path, monkeypatch):
    _patch_env(monkeypatch, tmp_path)
    from backend.api.agents import SecurityPostureAgent

    agent = SecurityPostureAgent()

    async def _go():
        await agent.run_cycle()

    asyncio.run(_go())


# ── AgentSupervisor ───────────────────────────────────────────────────────────

def test_supervisor_start_registers_all_agents(tmp_path, monkeypatch):
    _patch_env(monkeypatch, tmp_path)
    from backend.api import agents

    # Use the module singleton which already has agents registered
    supervisor = agents.get_supervisor()
    count = len(supervisor._agents)
    assert count >= 4  # 6 built-in agents registered at module load time


def test_supervisor_health_returns_agent_list(tmp_path, monkeypatch):
    _patch_env(monkeypatch, tmp_path)
    from backend.api import agents

    supervisor = agents.get_supervisor()
    health = supervisor.supervisor_health()
    assert "agents" in health
    assert "total_agents" in health
    ids = {a["id"] for a in health["agents"]}
    assert "inbox_monitor" in ids
    assert "threat_watch" in ids


# ── REST endpoints ─────────────────────────────────────────────────────────────

def _client(tmp_path, monkeypatch):
    from backend.api import agents
    from backend.auth.local_auth import require_local_auth

    _patch_env(monkeypatch, tmp_path)

    app = FastAPI()
    app.dependency_overrides[require_local_auth] = lambda: None
    app.include_router(agents.router, prefix="/api/v1")
    return TestClient(app)


def test_agents_list_endpoint_returns_all_agents(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/api/v1/agents")
    assert resp.status_code == 200
    data = resp.json()
    assert "agents" in data
    assert len(data["agents"]) >= 4


def test_agents_list_includes_expected_agent_ids(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/api/v1/agents")
    # agent status uses "id" key (not "agent_id")
    ids = {a["id"] for a in resp.json()["agents"]}
    assert "inbox_monitor" in ids
    assert "threat_watch" in ids
    assert "workflow_orchestrator" in ids


def test_agent_health_endpoint(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/api/v1/agents/health")
    assert resp.status_code == 200


def test_agent_actions_endpoint_returns_list(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/api/v1/agents/actions?limit=10")
    assert resp.status_code == 200
    assert "actions" in resp.json()


def test_get_agent_detail_returns_404_for_unknown(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/api/v1/agents/nonexistent_agent_xyz")
    assert resp.status_code == 404


def test_trigger_known_agent_endpoint(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.post("/api/v1/agents/inbox_monitor/trigger")
    assert resp.status_code in (200, 202)


def test_supervisor_start_all_respects_runtime_agent_toggle(monkeypatch):
    from backend.api.agents import AgentSupervisor, OperationalAgent

    class ProbeAgent(OperationalAgent):
        agent_id = "inbox_monitor"
        name = "Inbox Monitor"

        async def run_cycle(self):
            return None

    monkeypatch.setenv("AIO_RUNTIME_PROFILE", "enterprise")
    monkeypatch.setenv("AIO_AGENT_INBOX_MONITOR", "false")
    supervisor = AgentSupervisor()
    agent = ProbeAgent()
    supervisor.register(agent)

    async def _go():
        await supervisor.start_all()
        return supervisor.supervisor_health()

    health = asyncio.run(_go())

    assert agent._running is False
    assert health["running"] == 0
    assert health["agents"][0]["enabled"] is False
    assert health["agents"][0]["start_blocked_reason"] == "disabled_by_runtime_policy"


def test_supervisor_starts_enabled_agents_by_priority(monkeypatch):
    from backend.api.agents import AgentSupervisor, OperationalAgent

    started = []

    class SlowAgent(OperationalAgent):
        agent_id = "performance_analyst"
        name = "Performance Analyst"

        async def start(self):
            started.append(self.agent_id)
            await super().start()

        async def run_cycle(self):
            return None

    class FastAgent(OperationalAgent):
        agent_id = "workflow_orchestrator"
        name = "Workflow Orchestrator"

        async def start(self):
            started.append(self.agent_id)
            await super().start()

        async def run_cycle(self):
            return None

    monkeypatch.setenv("AIO_RUNTIME_PROFILE", "enterprise")
    supervisor = AgentSupervisor()
    supervisor.register(SlowAgent())
    supervisor.register(FastAgent())

    async def _go():
        await supervisor.start_all()
        await supervisor.stop_all()

    asyncio.run(_go())

    assert started[:2] == ["workflow_orchestrator", "performance_analyst"]


def test_disabled_agent_trigger_returns_policy_error(monkeypatch):
    from backend.api.agents import AgentSupervisor, OperationalAgent

    class ProbeAgent(OperationalAgent):
        agent_id = "threat_watch"
        name = "Threat Watch"

        async def run_cycle(self):
            return None

    monkeypatch.setenv("AIO_RUNTIME_PROFILE", "enterprise")
    monkeypatch.setenv("AIO_AGENT_THREAT_WATCH", "false")
    supervisor = AgentSupervisor()
    supervisor.register(ProbeAgent())

    async def _go():
        return await supervisor.trigger("threat_watch")

    with pytest.raises(PermissionError):
        asyncio.run(_go())


def test_disabled_agents_do_not_make_supervisor_unhealthy(monkeypatch):
    from backend.api.agents import AgentSupervisor, OperationalAgent

    class ProbeAgent(OperationalAgent):
        agent_id = "inbox_monitor"
        name = "Inbox Monitor"

        async def run_cycle(self):
            return None

    monkeypatch.setenv("AIO_RUNTIME_PROFILE", "low_resource")
    supervisor = AgentSupervisor()
    supervisor.register(ProbeAgent())

    async def _go():
        await supervisor.start_all()
        return supervisor.supervisor_health()

    health = asyncio.run(_go())

    assert health["profile"] == "low_resource"
    assert health["enabled"] == 0
    assert health["disabled"] == 1
    assert health["running"] == 0
    assert health["healthy"] is True


def test_supervisor_health_reports_policy_counts(monkeypatch):
    from backend.api.agents import AgentSupervisor, OperationalAgent

    class EnabledAgent(OperationalAgent):
        agent_id = "workflow_orchestrator"
        name = "Workflow Orchestrator"

        async def run_cycle(self):
            return None

    class DisabledAgent(OperationalAgent):
        agent_id = "security_posture"
        name = "Security Posture"

        async def run_cycle(self):
            return None

    monkeypatch.setenv("AIO_RUNTIME_PROFILE", "enterprise")
    monkeypatch.setenv("AIO_AGENT_SECURITY_POSTURE", "false")
    supervisor = AgentSupervisor()
    supervisor.register(DisabledAgent())
    supervisor.register(EnabledAgent())

    async def _go():
        await supervisor.start_all()
        health = supervisor.supervisor_health()
        await supervisor.stop_all()
        return health

    health = asyncio.run(_go())

    assert health["profile"] == "enterprise"
    assert health["enabled"] == 1
    assert health["disabled"] == 1
    assert health["autostart_blocked"] == 1
    assert health["running"] == 1
    assert health["agents"][0]["id"] == "workflow_orchestrator"
    assert health["agents"][0]["limits"]["queue_limit"] > 0
