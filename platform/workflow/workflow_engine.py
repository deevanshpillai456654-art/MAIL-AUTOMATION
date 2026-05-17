"""
WorkflowEngine — async, node-based workflow execution engine.

A workflow is a dict with a 'steps' list.  Each step references a
node_type registered in WorkflowNodeRegistry and may declare
input_map (jinja-style variable references) and output_map (rename
outputs for downstream steps).

Workflow definition schema::

    {
      "workflow_id": "wf_onboard_contact",
      "name": "Onboard Contact",
      "steps": [
        {
          "step_id": "fetch",
          "node_type": "fetch_contacts",
          "inputs": {"contact_id": "{{trigger.contact_id}}"}
        },
        {
          "step_id": "notify",
          "node_type": "log",
          "inputs": {"message": "Contact fetched: {{fetch.name}}"}
        }
      ]
    }
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger(__name__)


# ── Run state ─────────────────────────────────────────────────────────────

@dataclass
class WorkflowRun:
    run_id:      str
    workflow_id: str
    tenant_id:   str
    status:      str = "pending"   # pending | running | completed | failed | cancelled
    inputs:      Dict[str, Any] = field(default_factory=dict)
    outputs:     Dict[str, Any] = field(default_factory=dict)   # step_id → outputs
    error:       Optional[str] = None
    started_at:  Optional[str] = None
    finished_at: Optional[str] = None
    correlation_id: Optional[str] = None


# ── Engine ────────────────────────────────────────────────────────────────

class WorkflowEngine:
    """
    Executes workflows defined as directed acyclic step lists.

    Each step is executed by the handler registered under its node_type
    in WorkflowNodeRegistry.  Step inputs support simple ``{{step.key}}``
    template resolution against accumulated run context.
    """

    def __init__(self, node_registry: Any) -> None:
        self._registry = node_registry
        self._runs: Dict[str, WorkflowRun] = {}
        self._workflows: Dict[str, Dict[str, Any]] = {}
        self._completion_hooks: Dict[str, List[Callable]] = {}
        self._failure_hooks: Dict[str, List[Callable]] = {}

    # ── Workflow definition management ────────────────────────────────────

    def register_workflow(self, definition: Dict[str, Any]) -> str:
        wid = definition.get("workflow_id") or f"wf_{uuid.uuid4().hex[:8]}"
        definition["workflow_id"] = wid
        self._workflows[wid] = definition
        return wid

    def get_workflow(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        return self._workflows.get(workflow_id)

    # ── Trigger ───────────────────────────────────────────────────────────

    async def trigger(
        self,
        workflow_id: str,
        *,
        inputs: Optional[Dict[str, Any]] = None,
        tenant_id: str = "__system__",
        triggered_by: str = "unknown",
        correlation_id: Optional[str] = None,
    ) -> Optional[str]:
        definition = self._workflows.get(workflow_id)
        if not definition:
            log.warning("WorkflowEngine: unknown workflow_id=%s", workflow_id)
            return None

        run = WorkflowRun(
            run_id=f"run_{uuid.uuid4().hex}",
            workflow_id=workflow_id,
            tenant_id=tenant_id,
            inputs=inputs or {},
            correlation_id=correlation_id,
        )
        self._runs[run.run_id] = run
        asyncio.create_task(self._execute(run, definition))
        return run.run_id

    async def await_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Poll until the run finishes, then return the run dict."""
        for _ in range(600):   # up to 60s
            run = self._runs.get(run_id)
            if run and run.status in ("completed", "failed", "cancelled"):
                return self._run_to_dict(run)
            await asyncio.sleep(0.1)
        return None

    def get_status(self, run_id: str) -> Optional[str]:
        run = self._runs.get(run_id)
        return run.status if run else None

    async def cancel(self, run_id: str) -> bool:
        run = self._runs.get(run_id)
        if run and run.status == "running":
            run.status = "cancelled"
            run.finished_at = datetime.now(timezone.utc).isoformat()
            return True
        return False

    # ── Execution ─────────────────────────────────────────────────────────

    async def _execute(self, run: WorkflowRun, definition: Dict[str, Any]) -> None:
        run.status = "running"
        run.started_at = datetime.now(timezone.utc).isoformat()
        ctx = {"tenant_id": run.tenant_id, "run_id": run.run_id}
        scope: Dict[str, Any] = {"trigger": run.inputs}

        steps = definition.get("steps", [])
        try:
            for step in steps:
                if run.status == "cancelled":
                    break
                step_id   = step.get("step_id", f"step_{uuid.uuid4().hex[:4]}")
                node_type = step["node_type"]
                raw_inputs = step.get("inputs", {})
                resolved   = self._resolve_inputs(raw_inputs, scope)

                handler = self._registry.get_handler(node_type)
                if not handler:
                    raise RuntimeError(f"Unknown node_type: {node_type}")

                log.debug("WorkflowEngine: run=%s step=%s node=%s", run.run_id, step_id, node_type)
                step_outputs = await handler(resolved, ctx)
                run.outputs[step_id] = step_outputs
                scope[step_id] = step_outputs

            if run.status != "cancelled":
                run.status = "completed"
            await self._fire_hooks(run)
        except Exception as exc:
            run.status = "failed"
            run.error  = str(exc)
            log.error("WorkflowEngine: run=%s FAILED — %s", run.run_id, exc, exc_info=True)
            await self._fire_hooks(run, failed=True)
        finally:
            run.finished_at = datetime.now(timezone.utc).isoformat()

    # ── Template resolution ───────────────────────────────────────────────

    def _resolve_inputs(self, raw: Dict[str, Any], scope: Dict[str, Any]) -> Dict[str, Any]:
        """Replace {{step_id.key}} tokens in string values."""
        out: Dict[str, Any] = {}
        for k, v in raw.items():
            out[k] = self._resolve_value(v, scope) if isinstance(v, str) else v
        return out

    def _resolve_value(self, value: str, scope: Dict[str, Any]) -> Any:
        import re
        def replacer(m: "re.Match") -> str:
            ref = m.group(1).strip()
            parts = ref.split(".", 1)
            step_out = scope.get(parts[0])
            if step_out is None:
                return m.group(0)
            if len(parts) == 2 and isinstance(step_out, dict):
                return str(step_out.get(parts[1], m.group(0)))
            return str(step_out)
        resolved = re.sub(r"\{\{(.+?)\}\}", replacer, value)
        return resolved

    # ── Hooks ─────────────────────────────────────────────────────────────

    def on_completion(self, workflow_id: str, handler: Callable, *, tenant_id: Optional[str] = None) -> None:
        self._completion_hooks.setdefault(workflow_id, []).append(handler)

    def on_failure(self, workflow_id: str, handler: Callable, *, tenant_id: Optional[str] = None) -> None:
        self._failure_hooks.setdefault(workflow_id, []).append(handler)

    async def _fire_hooks(self, run: WorkflowRun, *, failed: bool = False) -> None:
        hooks = (
            self._failure_hooks.get(run.workflow_id, [])
            if failed
            else self._completion_hooks.get(run.workflow_id, [])
        )
        data = self._run_to_dict(run)
        for hook in hooks:
            try:
                if asyncio.iscoroutinefunction(hook):
                    await hook(data)
                else:
                    hook(data)
            except Exception as exc:
                log.error("WorkflowEngine: hook error for run=%s: %s", run.run_id, exc)

    def _run_to_dict(self, run: WorkflowRun) -> Dict[str, Any]:
        return {
            "run_id":         run.run_id,
            "workflow_id":    run.workflow_id,
            "tenant_id":      run.tenant_id,
            "status":         run.status,
            "inputs":         run.inputs,
            "outputs":        run.outputs,
            "error":          run.error,
            "started_at":     run.started_at,
            "finished_at":    run.finished_at,
            "correlation_id": run.correlation_id,
        }
