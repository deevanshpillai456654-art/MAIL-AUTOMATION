"""Workflow Agent – programmatic workflow triggering."""
from __future__ import annotations

from typing import Any, Dict, Optional

from .base import BaseAgent


class WorkflowAgent(BaseAgent):
    agent_type = "workflow"

    async def run(self, task_name: str, input_data: Dict[str, Any],
                  tenant_id: Optional[str] = None) -> Dict[str, Any]:
        if task_name == "trigger":
            return await self._trigger(input_data, tenant_id)
        elif task_name == "status":
            return await self._status(input_data, tenant_id)
        return {"error": f"Unknown workflow task: {task_name}"}

    async def _trigger(self, data: Dict, tenant_id: Optional[str]) -> Dict:
        workflow_id = data.get("workflow_id")
        trigger_data = data.get("trigger_data", {})
        if not workflow_id or not tenant_id:
            return {"error": "workflow_id and tenant_id required"}

        from ..backend.db import get_db
        wf_row = get_db().execute(
            "SELECT * FROM workflows WHERE id=? AND tenant_id=?", (workflow_id, tenant_id)
        ).fetchone()
        if not wf_row:
            return {"error": "Workflow not found"}

        import json
        wf = dict(wf_row)
        wf_def = {
            "id": wf["id"],
            "name": wf["name"],
            "nodes": json.loads(wf.get("nodes_json") or "[]"),
            "connections": json.loads(wf.get("connections_json") or "[]"),
        }

        from ..engine.executor import WorkflowExecutor
        executor = WorkflowExecutor()
        exec_id = await executor.execute_workflow(wf_def, trigger_data, tenant_id)
        return {"execution_id": exec_id, "triggered": True}

    async def _status(self, data: Dict, tenant_id: Optional[str]) -> Dict:
        exec_id = data.get("execution_id")
        if not exec_id:
            return {"error": "execution_id required"}
        from ..backend.db import get_db
        row = get_db().execute(
            "SELECT id, status, error, started_at, completed_at FROM executions WHERE id=?",
            (exec_id,),
        ).fetchone()
        if not row:
            return {"error": "Execution not found"}
        return dict(row)
