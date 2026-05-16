"""Agent orchestrator – routes tasks to specialized agents."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)


class AgentOrchestrator:
    """Routes tasks to the appropriate specialized agent."""

    async def run_task(
        self,
        agent_type: str,
        task_name: str,
        input_data: Dict[str, Any],
        tenant_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        agent = self._get_agent(agent_type)
        if not agent:
            log.warning("Unknown agent type: %s", agent_type)
            return {"error": f"Unknown agent type: {agent_type}"}
        try:
            return await agent.run(task_name, input_data, tenant_id)
        except Exception as exc:
            log.error("Agent %s task %s failed: %s", agent_type, task_name, exc)
            return {"error": str(exc)}

    async def run_pipeline(
        self,
        steps: list[Dict],
        initial_data: Dict[str, Any],
        tenant_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        context = dict(initial_data)
        for step in steps:
            agent_type = step.get("agent_type", "workflow")
            task_name = step.get("task_name", "")
            result = await self.run_task(agent_type, task_name, context, tenant_id)
            context.update(result)
            if result.get("error") and step.get("stop_on_error", True):
                break
        return context

    async def run_parallel(
        self,
        tasks: list[Dict],
        tenant_id: Optional[str] = None,
    ) -> list[Dict]:
        import asyncio
        coros = [
            self.run_task(t.get("agent_type", "workflow"), t.get("task_name", ""),
                          t.get("input", {}), tenant_id)
            for t in tasks
        ]
        return list(await asyncio.gather(*coros, return_exceptions=False))

    def _get_agent(self, agent_type: str):
        from . import ocr_agent, communication_agent, approval_agent, search_agent, workflow_agent
        agents = {
            "ocr": ocr_agent.OCRAgent(),
            "communication": communication_agent.CommunicationAgent(),
            "approval": approval_agent.ApprovalAgent(),
            "search": search_agent.SearchAgent(),
            "workflow": workflow_agent.WorkflowAgent(),
        }
        return agents.get(agent_type)
