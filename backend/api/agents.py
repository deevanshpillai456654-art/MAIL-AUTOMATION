"""
Autonomous Operational Agent System
====================================
Coordinated AI agents that continuously monitor, analyse, and act on
platform data without any user configuration.

Each agent:
  - Runs on a configurable schedule (or event-triggered)
  - Has a defined operational domain
  - Emits findings to the event bus
  - Publishes insights to the intelligence layer
  - Can trigger self-healing actions autonomously
  - Maintains its own health metrics

Built-in agents:
  InboxMonitorAgent       — watches email volume, processing rate, backlog
  ThreatWatchAgent        — monitors threat frequency, escalates high-risk patterns
  WorkflowOrchestratorAgent — monitors workflow health, triggers recovery
  FinanceMonitorAgent     — watches for Finance/invoice patterns, OCR opportunities
  PerformanceAnalystAgent — overall platform performance and SLA monitoring
  SecurityPostureAgent    — continuous security posture evaluation

AgentSupervisor:
  - Manages all agent lifecycles
  - Monitors agent health (heartbeats)
  - Auto-restarts crashed agents
  - Provides unified health dashboard

Endpoints:
  GET  /agents                  — list all agents and their status
  GET  /agents/{id}             — get agent detail + recent actions
  POST /agents/{id}/trigger     — manually trigger an agent run cycle
  POST /agents/{id}/pause       — pause agent
  POST /agents/{id}/resume      — resume paused agent
  GET  /agents/health           — agent supervisor health report
  GET  /agents/actions          — recent agent actions across all agents
"""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from backend.auth.local_auth import require_local_auth
from backend.config import DATA_DIR
from backend.core.runtime_control import get_runtime_control

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/agents", tags=["operational-agents"])

_ACTIONS_DB = str(Path(DATA_DIR) / "agent_actions.db")
DB_PATH     = str(Path(DATA_DIR) / "db.sqlite3")  # main DB for agent queries
_WORKFLOWS_DB = str(Path(DATA_DIR) / "workflows.db")


def _actions_db() -> sqlite3.Connection:
    con = sqlite3.connect(_ACTIONS_DB, timeout=10, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("""
        CREATE TABLE IF NOT EXISTS agent_actions (
            id          TEXT PRIMARY KEY,
            agent_id    TEXT NOT NULL,
            agent_name  TEXT NOT NULL,
            action_type TEXT NOT NULL,
            title       TEXT NOT NULL,
            detail      TEXT,
            severity    TEXT DEFAULT 'low',
            metadata    TEXT DEFAULT '{}',
            created_at  TEXT NOT NULL
        )
    """)
    con.execute("CREATE INDEX IF NOT EXISTS idx_aa_agent ON agent_actions(agent_id)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_aa_created ON agent_actions(created_at)")
    con.commit()
    return con


def _persist_action(entry: Dict[str, Any]) -> None:
    try:
        con = _actions_db()
        con.execute(
            """INSERT OR IGNORE INTO agent_actions
               (id, agent_id, agent_name, action_type, title, detail, severity, metadata, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                entry["id"],
                entry.get("agent_id", ""),
                entry.get("agent_name", ""),
                entry.get("action_type", "action"),
                entry.get("title", ""),
                entry.get("detail", ""),
                entry.get("severity", "low"),
                json.dumps(entry.get("metadata", {})),
                entry.get("created_at", datetime.now(timezone.utc).isoformat()),
            ),
        )
        con.commit()
        con.close()
    except Exception as exc:
        logger.debug("Agent action persist failed: %s", exc)


def _query_actions(agent_id: Optional[str] = None, limit: int = 100) -> List[Dict]:
    try:
        con = _actions_db()
        if agent_id:
            rows = con.execute(
                "SELECT * FROM agent_actions WHERE agent_id=? ORDER BY created_at DESC LIMIT ?",
                (agent_id, limit),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM agent_actions ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        con.close()
        result = []
        for r in rows:
            d = dict(r)
            try:
                d["metadata"] = json.loads(d.get("metadata") or "{}")
            except Exception:
                d["metadata"] = {}
            result.append(d)
        return result
    except Exception as exc:
        logger.debug("Agent action query failed: %s", exc)
        return []


# ── Agent action log (in-memory ring buffer + SQLite persistence) ──────────────

class _ActionRingBuffer:
    """Fixed-size ring buffer of recent agent actions."""

    def __init__(self, maxsize: int = 500) -> None:
        self._buf: List[Dict] = []
        self._maxsize = maxsize

    def append(self, action: Dict) -> None:
        self._buf.append(action)
        if len(self._buf) > self._maxsize:
            self._buf.pop(0)

    def get_all(self) -> List[Dict]:
        return list(reversed(self._buf))

    def get_by_agent(self, agent_id: str, limit: int = 50) -> List[Dict]:
        return [a for a in reversed(self._buf) if a.get("agent_id") == agent_id][:limit]


_action_log = _ActionRingBuffer()


# ── Base agent ─────────────────────────────────────────────────────────────────

class OperationalAgent:
    """
    Base class for all autonomous operational agents.

    Subclasses implement `run_cycle()` which is called on every tick.
    Agents self-report via `_act()` and `_insight()` helpers which:
      1. Record the action in the ring buffer
      2. Emit an event to the event bus
    """

    # Override in subclass
    agent_id:    str = "base_agent"
    name:        str = "Base Agent"
    description: str = "Base operational agent"
    domain:      str = "general"
    interval_s:  int = 300  # run every 5 minutes by default

    def __init__(self) -> None:
        self._running    = False
        self._paused     = False
        self._task:       Optional[asyncio.Task] = None
        self._last_run:   Optional[datetime] = None
        self._next_run:   Optional[datetime] = None
        self._run_count   = 0
        self._error_count = 0
        self._last_error: Optional[str] = None
        self._started_at: Optional[datetime] = None

    async def start(self) -> None:
        if self._running:
            return
        self._running    = True
        self._started_at = datetime.now(timezone.utc)
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Agent '%s' started", self.agent_id)
        await self._emit_event("agent.started", {"agent": self.agent_id, "name": self.name})

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
        logger.info("Agent '%s' stopped", self.agent_id)
        await self._emit_event("agent.stopped", {"agent": self.agent_id})

    def pause(self) -> None:
        self._paused = True
        logger.info("Agent '%s' paused", self.agent_id)

    def resume(self) -> None:
        self._paused = False
        logger.info("Agent '%s' resumed", self.agent_id)

    async def _run_loop(self) -> None:
        while self._running:
            try:
                if not self._paused:
                    self._next_run = None
                    await self.run_cycle()
                    self._run_count += 1
                    self._last_run = datetime.now(timezone.utc)
                self._next_run = datetime.now(timezone.utc) + timedelta(seconds=self.interval_s)
                await asyncio.sleep(self.interval_s)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._error_count += 1
                self._last_error = str(exc)
                logger.error("Agent '%s' cycle error: %s", self.agent_id, exc)
                await asyncio.sleep(min(self.interval_s, 60))

    async def run_cycle(self) -> None:
        """Override in subclass. Called every `interval_s` seconds."""
        pass

    # ── Agent action helpers ──────────────────────────────────────────────────

    async def _act(
        self,
        action_type: str,
        title: str,
        detail: str,
        severity: str = "low",
        metadata: Optional[Dict] = None,
    ) -> None:
        entry = {
            "id":          str(uuid.uuid4()),
            "agent_id":    self.agent_id,
            "agent_name":  self.name,
            "action_type": action_type,
            "title":       title,
            "detail":      detail,
            "severity":    severity,
            "metadata":    metadata or {},
            "created_at":  datetime.now(timezone.utc).isoformat(),
        }
        _action_log.append(entry)
        _persist_action(entry)
        await self._emit_event(
            "agent.action",
            payload={**entry},
            severity=severity,
        )

    async def _insight(self, title: str, detail: str, severity: str = "low") -> None:
        entry = {
            "id":          str(uuid.uuid4()),
            "agent_id":    self.agent_id,
            "agent_name":  self.name,
            "action_type": "insight",
            "title":       title,
            "detail":      detail,
            "severity":    severity,
            "metadata":    {},
            "created_at":  datetime.now(timezone.utc).isoformat(),
        }
        _action_log.append(entry)
        _persist_action(entry)
        await self._emit_event("agent.insight", payload=entry, severity=severity)

    async def _anomaly(self, title: str, detail: str, severity: str = "medium") -> None:
        entry = {
            "id":          str(uuid.uuid4()),
            "agent_id":    self.agent_id,
            "agent_name":  self.name,
            "action_type": "anomaly",
            "title":       title,
            "detail":      detail,
            "severity":    severity,
            "metadata":    {"detected_at": datetime.now(timezone.utc).isoformat()},
            "created_at":  datetime.now(timezone.utc).isoformat(),
        }
        _action_log.append(entry)
        _persist_action(entry)
        await self._emit_event("agent.anomaly", payload=entry, severity=severity)

    async def _emit_event(
        self,
        event_type: str,
        payload: Dict[str, Any] = None,
        severity: str = "low",
    ) -> None:
        try:
            from backend.api.event_bus import emit
            await emit(
                event_type=event_type,
                source=f"agent.{self.agent_id}",
                payload=payload or {},
                severity=severity,
            )
        except Exception as exc:
            logger.debug("Agent event emit failed: %s", exc)

    async def _trigger_active_workflow(
        self,
        template_id: str,
        reason: str,
        input_data: Optional[Dict] = None,
    ) -> bool:
        """
        Autonomously trigger an active workflow by its template ID.
        Returns True if an execution was dispatched, False if no active workflow found.
        """
        try:
            from backend.api.workflows import trigger_workflow_by_template
            exec_id = await trigger_workflow_by_template(
                template_id=template_id,
                input_data={"agent": self.agent_id, "reason": reason, **(input_data or {})},
                trigger_type="agent",
            )
            if exec_id:
                await self._act(
                    "workflow_auto_triggered",
                    f"Auto-triggered {template_id}",
                    f"Reason: {reason} | Execution: {exec_id}",
                    severity="medium",
                    metadata={"template_id": template_id, "exec_id": exec_id},
                )
                return True
        except Exception as exc:
            logger.debug("Agent auto-trigger failed (template=%s): %s", template_id, exc)
        return False

    def status(self) -> Dict[str, Any]:
        return {
            "id":           self.agent_id,
            "name":         self.name,
            "description":  self.description,
            "domain":       self.domain,
            "running":      self._running,
            "paused":       self._paused,
            "run_count":    self._run_count,
            "error_count":  self._error_count,
            "last_error":   self._last_error,
            "last_run":     self._last_run.isoformat() if self._last_run else None,
            "next_run":     self._next_run.isoformat() if self._next_run else None,
            "started_at":   self._started_at.isoformat() if self._started_at else None,
            "interval_s":   self.interval_s,
        }


# ── Built-in agents ────────────────────────────────────────────────────────────

class InboxMonitorAgent(OperationalAgent):
    """
    Monitors email inbox health: processing rates, backlogs, category anomalies.
    Triggers Smart Inbox Organizer recommendation if processing rate drops.
    """
    agent_id    = "inbox_monitor"
    name        = "Inbox Monitor"
    description = "Continuously monitors email processing rates, inbox backlog, and category distribution."
    domain      = "email"
    interval_s  = 180  # every 3 minutes

    async def run_cycle(self) -> None:
        try:
            from backend.api.operational_intelligence import _engine
            summary = _engine.email_summary()
            total   = summary["total"]
            if total == 0:
                return

            proc_rate = round(summary["processed"] / total * 100, 1)
            unread    = summary["unread"]

            if proc_rate < 70:
                await self._anomaly(
                    "Email processing backlog",
                    f"Only {proc_rate}% of {total} emails processed. {total - summary['processed']} awaiting AI analysis.",
                    severity="medium",
                )

            if unread > 10:
                await self._insight(
                    "Unread email count elevated",
                    f"{unread} unread emails detected. Smart Inbox Organizer can auto-prioritise these.",
                    severity="low",
                )

            # Emit processing telemetry
            await self._act(
                "telemetry",
                "Inbox health telemetry",
                f"Processed: {proc_rate}%, Unread: {unread}, Total: {total}",
                severity="low",
                metadata={"proc_rate": proc_rate, "unread": unread, "total": total},
            )
        except Exception as exc:
            logger.debug("InboxMonitorAgent cycle error: %s", exc)


class ThreatWatchAgent(OperationalAgent):
    """
    Monitors threat intelligence data: frequency, severity, unresolved threats.
    Escalates when high-confidence threats are detected or volume spikes.
    """
    agent_id    = "threat_watch"
    name        = "Threat Watch"
    description = "Real-time threat monitoring — detects spikes, escalates high-risk patterns, monitors brand impersonation."
    domain      = "security"
    interval_s  = 120  # every 2 minutes

    async def run_cycle(self) -> None:
        try:
            from backend.api.operational_intelligence import _engine
            summary = _engine.threat_summary()

            if summary["high_confidence"] >= 5:
                await self._anomaly(
                    "Critical threat concentration",
                    f"{summary['high_confidence']} high-confidence threats (≥80%) remain active and unaddressed.",
                    severity="critical",
                )

            elif summary["high_confidence"] >= 2:
                await self._anomaly(
                    "High-confidence threats detected",
                    f"{summary['high_confidence']} threats with ≥80% confidence need immediate review.",
                    severity="high",
                )

            if summary["last_24h"] > 10:
                await self._anomaly(
                    "Threat volume spike",
                    f"{summary['last_24h']} new threats in the last 24h — significantly above normal.",
                    severity="high",
                )

            if summary["top_brands"]:
                top = next(iter(summary["top_brands"]))
                count = summary["top_brands"][top]
                if count >= 5:
                    await self._insight(
                        f"Persistent {top} impersonation campaign",
                        f"{count} attempts to impersonate {top} detected. Consider activating Threat Escalation workflow.",
                        severity="high",
                    )

            if summary["active"] > 0:
                await self._act(
                    "threat_scan",
                    "Threat scan completed",
                    f"Active: {summary['active']}, High-confidence: {summary['high_confidence']}, Last 24h: {summary['last_24h']}",
                    severity="low" if summary["active"] < 5 else "medium",
                    metadata=summary,
                )

            # Autonomously trigger threat escalation if critical threats exist
            if summary["high_confidence"] >= 3:
                await self._trigger_active_workflow(
                    "threat_escalation",
                    f"Auto-triggered: {summary['high_confidence']} high-confidence threats detected",
                    {"threat_count": summary["high_confidence"]},
                )
        except Exception as exc:
            logger.debug("ThreatWatchAgent cycle error: %s", exc)


class WorkflowOrchestratorAgent(OperationalAgent):
    """
    Monitors workflow execution health, detects failure patterns,
    identifies which workflows should be activated based on current data.
    """
    agent_id    = "workflow_orchestrator"
    name        = "Workflow Orchestrator"
    description = "Monitors workflow execution health, failure patterns, and orchestration opportunities."
    domain      = "workflow"
    interval_s  = 240  # every 4 minutes

    async def run_cycle(self) -> None:
        try:
            from backend.api.operational_intelligence import _engine
            wf = _engine.workflow_summary()

            if wf["total"] == 0:
                await self._insight(
                    "No workflows configured",
                    "12 production-grade workflow templates are available in the Marketplace — activate with one click.",
                    severity="medium",
                )
                return

            if wf["active"] == 0:
                await self._insight(
                    "Workflows inactive",
                    f"{wf['total']} workflows created but none active. Activate to enable autonomous operations.",
                    severity="medium",
                )

            if wf["failed_24h"] >= 3:
                await self._anomaly(
                    "Workflow failure spike",
                    f"{wf['failed_24h']} executions failed in the last 24h. Review Execution History for details.",
                    severity="high",
                )

            if wf["total_runs"] > 0:
                await self._act(
                    "health_check",
                    "Workflow health check",
                    f"Active: {wf['active']}/{wf['total']}, Success rate: {wf['success_rate']}%, Runs today: {wf['last_24h']}",
                    severity="low",
                    metadata=wf,
                )

            # Auto-trigger smart inbox organizer daily if active and few runs today
            if wf["active"] > 0 and wf["last_24h"] == 0:
                await self._trigger_active_workflow(
                    "smart_inbox_organizer",
                    "Scheduled daily inbox organisation — no runs recorded today",
                )
        except Exception as exc:
            logger.debug("WorkflowOrchestratorAgent cycle error: %s", exc)


class FinanceMonitorAgent(OperationalAgent):
    """
    Monitors Finance-category emails, detects invoice patterns,
    recommends OCR pipeline activation, tracks financial communication volume.
    """
    agent_id    = "finance_monitor"
    name        = "Finance Monitor"
    description = "Watches Finance emails, detects invoice patterns, and recommends financial automation workflows."
    domain      = "finance"
    interval_s  = 300  # every 5 minutes

    async def run_cycle(self) -> None:
        try:
            from backend.api.operational_intelligence import _engine
            summary = _engine.email_summary()
            cats    = summary.get("categories", {})
            finance = cats.get("Finance", 0)

            if finance >= 1:
                await self._insight(
                    f"{finance} Finance email(s) detected",
                    "Invoice OCR Pipeline can automatically extract invoice numbers, amounts, and due dates.",
                    severity="low",
                )

            if finance >= 5:
                await self._act(
                    "finance_pattern",
                    "Finance email volume detected",
                    f"{finance} Finance emails in inbox — high OCR pipeline opportunity.",
                    severity="medium",
                    metadata={"finance_count": finance},
                )
        except Exception as exc:
            logger.debug("FinanceMonitorAgent cycle error: %s", exc)


class PerformanceAnalystAgent(OperationalAgent):
    """
    Continuous performance analyst: computes overall health score, detects
    degradation trends, and emits performance telemetry to the event bus.
    """
    agent_id    = "performance_analyst"
    name        = "Performance Analyst"
    description = "Continuous operational health monitoring — detects degradation trends and computes platform health score."
    domain      = "analytics"
    interval_s  = 600  # every 10 minutes

    def __init__(self) -> None:
        super().__init__()
        self._prev_health: Optional[int] = None

    async def run_cycle(self) -> None:
        try:
            from backend.api.operational_intelligence import _engine
            health = _engine.compute_health_score()
            score  = health["overall"]
            status = health["status"]

            if self._prev_health is not None:
                delta = score - self._prev_health
                if delta <= -10:
                    await self._anomaly(
                        "Operational health degradation",
                        f"Health score dropped {abs(delta)} points to {score}/100 ({status}).",
                        severity="high" if score < 60 else "medium",
                    )
                elif delta >= 10:
                    await self._act(
                        "recovery_detected",
                        "Operational health improved",
                        f"Health score improved {delta} points to {score}/100 ({status}).",
                        severity="low",
                    )

            self._prev_health = score

            await self._act(
                "health_telemetry",
                f"Platform health: {score}/100 ({status})",
                f"Email: {health['components']['email_processing']['score']}% | "
                f"Security: {health['components']['security']['score']}% | "
                f"Workflows: {health['components']['workflow_reliability']['score']}% | "
                f"Connectivity: {health['components']['connectivity']['score']}%",
                severity="low" if score >= 70 else "medium" if score >= 50 else "high",
                metadata=health,
            )

            # Emit health event to bus
            from backend.api.event_bus import emit
            await emit(
                "system.health_check",
                source=f"agent.{self.agent_id}",
                payload={"score": score, "status": status, "components": {k: v["score"] for k, v in health["components"].items()}},
                severity="low" if score >= 70 else "medium" if score >= 50 else "high",
            )
        except Exception as exc:
            logger.debug("PerformanceAnalystAgent cycle error: %s", exc)


class SecurityPostureAgent(OperationalAgent):
    """
    Continuous security posture evaluation: monitors threat activity,
    account security, and emits security intelligence events.
    """
    agent_id    = "security_posture"
    name        = "Security Posture"
    description = "Evaluates and monitors overall security posture, detects emerging attack patterns."
    domain      = "security"
    interval_s  = 180  # every 3 minutes

    async def run_cycle(self) -> None:
        try:
            from backend.api.operational_intelligence import _engine
            threat = _engine.threat_summary()
            acct   = _engine.account_summary()

            # Assess posture
            issues = []
            if threat["active"] > 5:
                issues.append(f"{threat['active']} active threats unresolved")
            if threat["high_confidence"] > 0:
                issues.append(f"{threat['high_confidence']} high-confidence threats")
            if acct["errored"] > 0:
                issues.append(f"{acct['errored']} accounts in error state")

            if issues:
                severity = "high" if len(issues) >= 2 else "medium"
                await self._act(
                    "posture_assessment",
                    "Security posture issues detected",
                    " | ".join(issues),
                    severity=severity,
                    metadata={"issues": issues, "threat": threat, "accounts": acct},
                )
            else:
                await self._act(
                    "posture_assessment",
                    "Security posture: nominal",
                    f"No critical issues — {threat['total']} total threats, {acct['active']}/{acct['total']} accounts healthy.",
                    severity="low",
                )
        except Exception as exc:
            logger.debug("SecurityPostureAgent cycle error: %s", exc)


# ── Agent supervisor ───────────────────────────────────────────────────────────

class AgentSupervisor:
    """
    Manages all operational agent lifecycles.
    Provides unified health dashboard and auto-restart on failure.
    """

    def __init__(self) -> None:
        self._agents: Dict[str, OperationalAgent] = {}
        self._started = False
        self._supervisor_task: Optional[asyncio.Task] = None

    def register(self, agent: OperationalAgent) -> None:
        self._agents[agent.agent_id] = agent

    def _agent_runtime_status(self, agent_id: str) -> Dict[str, Any]:
        runtime = get_runtime_control()
        policy = runtime.agent_status().get(agent_id, {})
        enabled = runtime.is_agent_enabled(agent_id)
        auto_start = runtime.should_autostart_agent(agent_id)
        return {
            "enabled": enabled,
            "auto_start": auto_start,
            "priority": int(policy.get("priority", 999)),
            "limits": policy.get("limits", {}),
            "start_blocked_reason": (
                None
                if enabled and auto_start
                else "disabled_by_runtime_policy"
                if not enabled
                else "autostart_disabled_by_runtime_policy"
            ),
        }

    def _ordered_agents(self) -> List[OperationalAgent]:
        return sorted(
            self._agents.values(),
            key=lambda agent: (self._agent_runtime_status(agent.agent_id)["priority"], agent.agent_id),
        )

    async def start_all(self) -> None:
        if self._started:
            return
        self._started = True
        started = 0
        for agent in self._ordered_agents():
            if not get_runtime_control().should_autostart_agent(agent.agent_id):
                logger.info("Agent '%s' skipped by runtime policy", agent.agent_id)
                continue
            await agent.start()
            started += 1
        self._supervisor_task = asyncio.create_task(self._health_watch())
        logger.info("AgentSupervisor started — %d of %d agents running", started, len(self._agents))

    async def stop_all(self) -> None:
        self._started = False
        if self._supervisor_task:
            self._supervisor_task.cancel()
        for agent in self._agents.values():
            await agent.stop()

    async def _health_watch(self) -> None:
        """Watchdog: restart agents whose tasks have died."""
        while self._started:
            try:
                for aid, agent in list(self._agents.items()):
                    if agent._running and (agent._task is None or agent._task.done()):
                        if not get_runtime_control().should_autostart_agent(aid):
                            logger.info("Agent '%s' task died and restart is blocked by runtime policy", aid)
                            agent._running = False
                            continue
                        logger.warning("Agent '%s' task died — restarting", aid)
                        agent._running = False
                        await agent.start()
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Supervisor health watch error: %s", exc)
                await asyncio.sleep(60)

    def get_agent(self, agent_id: str) -> Optional[OperationalAgent]:
        return self._agents.get(agent_id)

    def all_status(self) -> List[Dict[str, Any]]:
        statuses: List[Dict[str, Any]] = []
        for agent in self._ordered_agents():
            status = agent.status()
            status.update(self._agent_runtime_status(agent.agent_id))
            statuses.append(status)
        return statuses

    def supervisor_health(self) -> Dict[str, Any]:
        runtime = get_runtime_control()
        statuses = self.all_status()
        running  = sum(1 for s in statuses if s["running"] and not s["paused"])
        errored  = sum(1 for s in statuses if s["error_count"] > 0)
        enabled  = sum(1 for s in statuses if s.get("enabled"))
        disabled = sum(1 for s in statuses if not s.get("enabled"))
        autostart_blocked = sum(1 for s in statuses if s.get("start_blocked_reason"))
        total    = len(statuses)
        return {
            "total_agents":   total,
            "enabled":        enabled,
            "disabled":       disabled,
            "autostart_blocked": autostart_blocked,
            "running":        running,
            "paused":         sum(1 for s in statuses if s["paused"]),
            "errored":        errored,
            "healthy":        running == enabled and errored == 0,
            "supervisor_running": self._started,
            "profile":        runtime.profile,
            "low_resource":   runtime.low_resource,
            "ai_mode":        runtime.ai_mode,
            "agents":         statuses,
        }

    async def trigger(self, agent_id: str) -> Dict[str, Any]:
        agent = self._agents.get(agent_id)
        if not agent:
            raise ValueError(f"Unknown agent: {agent_id}")
        if not get_runtime_control().is_agent_enabled(agent_id):
            raise PermissionError(f"Agent '{agent_id}' is disabled by runtime policy")
        asyncio.create_task(agent.run_cycle())
        return {"ok": True, "agent_id": agent_id, "triggered_at": datetime.now(timezone.utc).isoformat()}


# ── Module singleton ───────────────────────────────────────────────────────────

_supervisor = AgentSupervisor()

# Register all built-in agents
for _agent_cls in (
    InboxMonitorAgent,
    ThreatWatchAgent,
    WorkflowOrchestratorAgent,
    FinanceMonitorAgent,
    PerformanceAnalystAgent,
    SecurityPostureAgent,
):
    _supervisor.register(_agent_cls())


def get_supervisor() -> AgentSupervisor:
    return _supervisor


async def ensure_agents_running() -> None:
    """Call from app startup to launch all agents."""
    await _supervisor.start_all()


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("", summary="List all operational agents and their status")
async def list_agents(_auth=Depends(require_local_auth)):
    # Auto-start agents on first access
    if not _supervisor._started:
        asyncio.create_task(_supervisor.start_all())
    return {"agents": _supervisor.all_status(), "total": len(_supervisor._agents)}


@router.get("/health", summary="Agent supervisor health report")
async def agent_health(_auth=Depends(require_local_auth)):
    if not _supervisor._started:
        asyncio.create_task(_supervisor.start_all())
    return _supervisor.supervisor_health()


@router.get("/actions", summary="Recent agent actions across all agents")
async def agent_actions(
    limit:    int           = 100,
    agent_id: Optional[str] = None,
    _auth=Depends(require_local_auth),
):
    # Read from persistent store (survives restarts); fall back to ring buffer
    actions = _query_actions(agent_id=agent_id, limit=limit)
    if not actions:
        if agent_id:
            actions = _action_log.get_by_agent(agent_id, limit)
        else:
            actions = _action_log.get_all()[:limit]
    return {"actions": actions, "count": len(actions)}


@router.get("/{agent_id}", summary="Get agent detail and recent actions")
async def get_agent(agent_id: str, _auth=Depends(require_local_auth)):
    agent = _supervisor.get_agent(agent_id)
    if not agent:
        raise HTTPException(404, f"Agent '{agent_id}' not found")
    recent = _query_actions(agent_id=agent_id, limit=20) or _action_log.get_by_agent(agent_id, limit=20)
    return {
        **agent.status(),
        "recent_actions": recent,
    }


@router.post("/{agent_id}/trigger", summary="Manually trigger an agent run cycle")
async def trigger_agent(agent_id: str, _auth=Depends(require_local_auth)):
    if not _supervisor._started:
        await _supervisor.start_all()
    try:
        result = await _supervisor.trigger(agent_id)
        return result
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    except PermissionError as exc:
        raise HTTPException(409, str(exc))


@router.post("/{agent_id}/pause", summary="Pause an agent")
async def pause_agent(agent_id: str, _auth=Depends(require_local_auth)):
    agent = _supervisor.get_agent(agent_id)
    if not agent:
        raise HTTPException(404, f"Agent '{agent_id}' not found")
    agent.pause()
    return {"ok": True, "agent_id": agent_id, "state": "paused"}


@router.post("/{agent_id}/resume", summary="Resume a paused agent")
async def resume_agent(agent_id: str, _auth=Depends(require_local_auth)):
    agent = _supervisor.get_agent(agent_id)
    if not agent:
        raise HTTPException(404, f"Agent '{agent_id}' not found")
    agent.resume()
    return {"ok": True, "agent_id": agent_id, "state": "running"}
