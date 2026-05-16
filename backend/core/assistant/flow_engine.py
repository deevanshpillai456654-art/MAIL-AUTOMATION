"""
Flow engine — drives step-by-step guided troubleshooting sessions.

Loads issue flows from the KnowledgeBase, advances sessions step by step,
handles branching (if_fails_issue redirects), and serialises step data
for the frontend in a format ready to render as visual cards.
"""
from __future__ import annotations

import dataclasses
import logging
from typing import Any, Dict, List, Optional

from .knowledge_base import FlowStep, IssueTemplate, get_knowledge_base
from .session_manager import AssistantSession

logger = logging.getLogger("assistant.flow")


# ── serialisation helpers ─────────────────────────────────────────────────────

def _serialise_visual(v) -> Optional[Dict[str, Any]]:
    if v is None:
        return None
    return {"type": v.type, "title": v.title, "content": v.content, "annotation": v.annotation}


def _serialise_action(a) -> Optional[Dict[str, Any]]:
    if a is None:
        return None
    return {
        "action_id": a.action_id,
        "label": a.label,
        "style": a.style,
        "params": a.params,
        "confirm_required": a.confirm_required,
    }


def _serialise_step(step: FlowStep, total: int) -> Dict[str, Any]:
    return {
        "number": step.number,
        "total": total,
        "title": step.title,
        "instruction": step.instruction,
        "detail": step.detail,
        "visual": _serialise_visual(step.visual),
        "action": _serialise_action(step.action),
        "expected_result": step.expected_result,
        "if_fails_issue": step.if_fails_issue,
        "admin_only": step.admin_only,
    }


def _serialise_issue(issue: IssueTemplate) -> Dict[str, Any]:
    return {
        "id": issue.id,
        "category": issue.category,
        "title": issue.title,
        "description": issue.description,
        "severity": issue.severity,
        "symptoms": issue.symptoms,
        "visual_flow_nodes": issue.visual_flow_nodes,
        "related_issues": issue.related_issues,
        "step_count": len(issue.steps),
        "tags": issue.tags,
    }


# ── flow engine ───────────────────────────────────────────────────────────────

class FlowEngine:

    def __init__(self) -> None:
        self._kb = get_knowledge_base()

    # ── issue discovery ───────────────────────────────────────────────────────

    def suggested_issues(self, signals: Dict[str, Any], limit: int = 5) -> List[Dict[str, Any]]:
        """Return issues whose diagnostic_signals match the runtime signals dict."""
        results = []
        for issue in self._kb.auto_detectable():
            if any(signals.get(sig) for sig in issue.diagnostic_signals):
                results.append(issue)
        # fill remaining slots with popular issues
        if len(results) < limit:
            others = [i for i in self._kb.all_issues() if i not in results]
            results.extend(others[: limit - len(results)])
        return [_serialise_issue(i) for i in results[:limit]]

    def search_issues(self, query: str) -> List[Dict[str, Any]]:
        return [_serialise_issue(i) for i in self._kb.search(query)]

    def get_issue_detail(self, issue_id: str, admin: bool = False) -> Optional[Dict[str, Any]]:
        issue = self._kb.get_issue(issue_id)
        if issue is None:
            return None
        steps = issue.steps if not admin else issue.steps + issue.admin_steps
        return {
            **_serialise_issue(issue),
            "steps": [_serialise_step(s, len(steps)) for s in steps],
        }

    # ── session flow control ──────────────────────────────────────────────────

    def start_flow(self, session: AssistantSession, issue_id: str) -> Dict[str, Any]:
        issue = self._kb.get_issue(issue_id)
        if issue is None:
            return {"error": f"Unknown issue: {issue_id}"}

        session.issue_id = issue_id
        session.step_index = 0
        session.add_history("flow_started", {"issue_id": issue_id})
        logger.info("Flow started: session=%s issue=%s", session.session_id, issue_id)

        steps = self._get_steps(issue, session.mode == "admin")
        return {
            "issue": _serialise_issue(issue),
            "current_step": _serialise_step(steps[0], len(steps)) if steps else None,
            "progress": {"current": 1, "total": len(steps)},
        }

    def advance(self, session: AssistantSession, outcome: str = "ok") -> Dict[str, Any]:
        """
        Advance the session to the next step.

        outcome: "ok" (step succeeded) | "failed" (step failed, check redirect)
        """
        if session.issue_id is None:
            return {"error": "No active flow — start a flow first"}

        issue = self._kb.get_issue(session.issue_id)
        if issue is None:
            return {"error": "Active issue not found"}

        steps = self._get_steps(issue, session.mode == "admin")
        current = steps[session.step_index] if session.step_index < len(steps) else None

        if outcome == "failed" and current and current.if_fails_issue:
            redirect = current.if_fails_issue
            session.add_history("flow_redirected", {
                "from_issue": session.issue_id,
                "to_issue": redirect,
                "at_step": session.step_index,
            })
            return self.start_flow(session, redirect)

        session.step_index += 1
        session.add_history("step_advanced", {"step": session.step_index, "outcome": outcome})

        if session.step_index >= len(steps):
            session.completed_flows.append(session.issue_id)
            session.add_history("flow_completed", {"issue_id": session.issue_id})
            logger.info("Flow completed: session=%s issue=%s", session.session_id, session.issue_id)
            return {
                "completed": True,
                "issue_id": session.issue_id,
                "message": "All steps complete. If the issue persists, try a related issue or contact support.",
                "related_issues": [_serialise_issue(r) for r in self._related(issue)],
            }

        next_step = steps[session.step_index]
        return {
            "completed": False,
            "current_step": _serialise_step(next_step, len(steps)),
            "progress": {"current": session.step_index + 1, "total": len(steps)},
        }

    def current_step(self, session: AssistantSession) -> Optional[Dict[str, Any]]:
        if session.issue_id is None:
            return None
        issue = self._kb.get_issue(session.issue_id)
        if issue is None:
            return None
        steps = self._get_steps(issue, session.mode == "admin")
        if session.step_index >= len(steps):
            return None
        step = steps[session.step_index]
        return {
            "current_step": _serialise_step(step, len(steps)),
            "progress": {"current": session.step_index + 1, "total": len(steps)},
        }

    # ── helpers ───────────────────────────────────────────────────────────────

    def _get_steps(self, issue: IssueTemplate, admin: bool) -> List[FlowStep]:
        if admin:
            return issue.steps + issue.admin_steps
        return issue.steps

    def _related(self, issue: IssueTemplate) -> List[IssueTemplate]:
        result = []
        for rid in issue.related_issues:
            rel = self._kb.get_issue(rid)
            if rel:
                result.append(rel)
        return result[:3]

    # ── knowledge index ───────────────────────────────────────────────────────

    def issue_index(self) -> List[Dict[str, Any]]:
        return self._kb.to_index()

    def categories(self) -> List[Dict[str, Any]]:
        cats: Dict[str, List[str]] = {}
        for issue in self._kb.all_issues():
            cats.setdefault(issue.category, []).append(issue.id)
        return [{"category": k, "issues": v} for k, v in cats.items()]


_engine: Optional[FlowEngine] = None


def get_flow_engine() -> FlowEngine:
    global _engine
    if _engine is None:
        _engine = FlowEngine()
    return _engine
