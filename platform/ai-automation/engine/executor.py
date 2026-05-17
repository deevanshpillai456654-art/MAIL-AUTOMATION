"""Workflow execution engine – node-based sequential/conditional execution."""
from __future__ import annotations

import asyncio
import ast
import json
import logging
import operator
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
}
_CMP_OPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}


class WorkflowExecutor:
    """Executes workflow definitions node by node."""

    def __init__(self):
        self._runners: Dict[str, Any] = {}
        self._register_runners()

    def _register_runners(self):
        from ..backend.models import NodeType
        self._runners = {
            NodeType.AI_CLASSIFY:      self._run_ai_classify,
            NodeType.AI_EXTRACT:       self._run_ai_extract,
            NodeType.AI_SUMMARIZE:     self._run_ai_summarize,
            NodeType.AI_GENERATE:      self._run_ai_generate,
            NodeType.AI_SENTIMENT:     self._run_ai_sentiment,
            NodeType.OCR_PROCESS:      self._run_ocr_process,
            NodeType.CONDITION:        self._run_condition,
            NodeType.SWITCH:           self._run_switch,
            NodeType.APPROVAL_REQUEST: self._run_approval_request,
            NodeType.APPROVAL_GATE:    self._run_approval_gate,
            NodeType.SEND_EMAIL:       self._run_send_email,
            NodeType.HTTP_REQUEST:     self._run_http_request,
            NodeType.TRANSFORM:        self._run_transform,
            NodeType.DELAY:            self._run_delay,
            NodeType.LOG:              self._run_log,
            NodeType.SEARCH:           self._run_search,
            NodeType.AGENT_RUN:        self._run_agent,
            NodeType.MERGE:            self._run_merge,
        }

    async def execute_workflow(
        self,
        workflow_def: Dict,
        trigger_data: Dict,
        tenant_id: str,
        execution_id: Optional[str] = None,
    ) -> str:
        """Create and execute a workflow. Returns execution_id."""
        from ..backend.db import get_db, tx

        exec_id = execution_id or str(uuid.uuid4())
        now = datetime.utcnow().isoformat()

        with tx() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO executions
                   (id,workflow_id,workflow_name,tenant_id,status,trigger_data_json,context_json,started_at)
                   VALUES (?,?,?,?,'running',?,?,?)""",
                (
                    exec_id,
                    workflow_def.get("id", ""),
                    workflow_def.get("name", "Workflow"),
                    tenant_id,
                    json.dumps(trigger_data),
                    json.dumps({"trigger": trigger_data}),
                    now,
                ),
            )

        try:
            context = {"trigger": trigger_data, "tenant_id": tenant_id}
            await self._execute_nodes(exec_id, workflow_def, context, tenant_id)

            with tx() as conn:
                conn.execute(
                    "UPDATE executions SET status='completed', completed_at=? WHERE id=?",
                    (datetime.utcnow().isoformat(), exec_id),
                )
        except _ApprovalGateException as gate:
            with tx() as conn:
                conn.execute(
                    "UPDATE executions SET status='waiting_approval', current_node_id=? WHERE id=?",
                    (gate.node_id, exec_id),
                )
        except Exception as exc:
            log.error("Execution %s failed: %s", exec_id, exc)
            with tx() as conn:
                conn.execute(
                    "UPDATE executions SET status='failed', error=?, completed_at=? WHERE id=?",
                    (str(exc), datetime.utcnow().isoformat(), exec_id),
                )
            raise

        return exec_id

    async def resume_execution(self, exec_id: str, tenant_id: str) -> None:
        """Resume a paused/pending execution."""
        from ..backend.db import get_db, tx
        row = get_db().execute(
            "SELECT * FROM executions WHERE id=? AND tenant_id=?", (exec_id, tenant_id)
        ).fetchone()
        if not row:
            raise ValueError(f"Execution {exec_id} not found")

        d = dict(row)
        if d["status"] not in ("pending", "running", "waiting_approval"):
            return

        wf_row = get_db().execute(
            "SELECT * FROM workflows WHERE id=?", (d["workflow_id"],)
        ).fetchone()
        if not wf_row:
            raise ValueError(f"Workflow {d['workflow_id']} not found")

        wf_d = dict(wf_row)
        workflow_def = {
            "id": wf_d["id"],
            "name": wf_d["name"],
            "nodes": json.loads(wf_d.get("nodes_json") or "[]"),
            "connections": json.loads(wf_d.get("connections_json") or "[]"),
        }
        trigger_data = json.loads(d.get("trigger_data_json") or "{}")
        await self.execute_workflow(workflow_def, trigger_data, tenant_id, exec_id)

    async def _execute_nodes(
        self, exec_id: str, workflow_def: Dict, context: Dict, tenant_id: str
    ) -> None:
        nodes = {n["id"]: n for n in workflow_def.get("nodes", [])}
        connections = workflow_def.get("connections", [])

        # Find trigger/start node
        trigger_types = {"trigger_email", "trigger_webhook", "trigger_schedule", "trigger_manual"}
        start_nodes = [n for n in nodes.values() if n.get("type") in trigger_types]
        if not start_nodes:
            start_nodes = list(nodes.values())[:1]

        if not start_nodes:
            return

        current_id = start_nodes[0]["id"]
        visited = set()

        while current_id and current_id not in visited:
            visited.add(current_id)
            node = nodes.get(current_id)
            if not node:
                break

            output = await self._execute_node(exec_id, node, context, tenant_id)
            context[f"node_{current_id}"] = output

            # Find next node
            outgoing = [c for c in connections if c.get("source_id") == current_id]
            if not outgoing:
                break

            if len(outgoing) == 1:
                current_id = outgoing[0].get("target_id")
            else:
                # Conditional branching: evaluate conditions
                next_id = None
                for conn in outgoing:
                    cond = conn.get("condition")
                    if not cond or self._eval_condition(cond, context):
                        next_id = conn.get("target_id")
                        break
                current_id = next_id

    async def _execute_node(
        self, exec_id: str, node: Dict, context: Dict, tenant_id: str
    ) -> Dict:
        from ..backend.db import tx
        from ..backend.models import NodeType, ExecutionStatus

        node_type_str = node.get("type", "")
        step_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()

        with tx() as conn:
            conn.execute(
                """INSERT INTO execution_steps
                   (id,execution_id,node_id,node_type,status,input_data_json,started_at)
                   VALUES (?,?,?,?,'running',?,?)""",
                (step_id, exec_id, node["id"], node_type_str, json.dumps(context), now),
            )
            conn.execute(
                "UPDATE executions SET current_node_id=? WHERE id=?", (node["id"], exec_id)
            )

        t0 = time.time()
        output: Dict = {}
        error: Optional[str] = None

        try:
            try:
                node_type = NodeType(node_type_str)
            except ValueError:
                node_type = None

            runner = self._runners.get(node_type) if node_type else None
            if runner:
                output = await runner(node, context, tenant_id) or {}
            else:
                log.debug("No runner for node type %s, skipping", node_type_str)
                output = {"skipped": True}

            status = "completed"
        except _ApprovalGateException:
            raise
        except Exception as exc:
            log.error("Node %s (%s) failed: %s", node["id"], node_type_str, exc)
            error = str(exc)
            status = "failed"

        duration_ms = int((time.time() - t0) * 1000)
        completed = datetime.utcnow().isoformat()

        with tx() as conn:
            conn.execute(
                """UPDATE execution_steps SET status=?, output_data_json=?, error=?,
                   completed_at=?, duration_ms=? WHERE id=?""",
                (status, json.dumps(output), error, completed, duration_ms, step_id),
            )

        return output

    def _eval_condition(self, condition: str, context: Dict) -> bool:
        result = self._safe_eval(condition, context)
        return bool(result) if result is not None else False

    def _safe_eval(self, expression: str, context: Dict) -> Any:
        """Evaluate a small expression language without calls or attributes."""
        try:
            tree = ast.parse(str(expression), mode="eval")
            return self._eval_ast(tree.body, context)
        except Exception:
            return None

    def _eval_ast(self, node: ast.AST, context: Dict) -> Any:
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            return context.get(node.id)
        if isinstance(node, ast.List):
            return [self._eval_ast(item, context) for item in node.elts]
        if isinstance(node, ast.Tuple):
            return tuple(self._eval_ast(item, context) for item in node.elts)
        if isinstance(node, ast.Dict):
            return {
                self._eval_ast(key, context): self._eval_ast(value, context)
                for key, value in zip(node.keys, node.values)
            }
        if isinstance(node, ast.Subscript):
            value = self._eval_ast(node.value, context)
            key = self._eval_ast(node.slice, context)
            if isinstance(value, dict):
                return value.get(key)
            if isinstance(value, (list, tuple)) and isinstance(key, int):
                return value[key]
            raise ValueError("Unsupported subscript")
        if isinstance(node, ast.UnaryOp):
            operand = self._eval_ast(node.operand, context)
            if isinstance(node.op, ast.Not):
                return not operand
            if isinstance(node.op, ast.USub):
                return -operand
            raise ValueError("Unsupported unary operator")
        if isinstance(node, ast.BoolOp):
            values = [self._eval_ast(value, context) for value in node.values]
            if isinstance(node.op, ast.And):
                return all(values)
            if isinstance(node.op, ast.Or):
                return any(values)
            raise ValueError("Unsupported boolean operator")
        if isinstance(node, ast.BinOp):
            op = _BIN_OPS.get(type(node.op))
            if not op:
                raise ValueError("Unsupported binary operator")
            return op(self._eval_ast(node.left, context), self._eval_ast(node.right, context))
        if isinstance(node, ast.Compare):
            left = self._eval_ast(node.left, context)
            for op_node, comparator in zip(node.ops, node.comparators):
                right = self._eval_ast(comparator, context)
                op = _CMP_OPS.get(type(op_node))
                if not op or not op(left, right):
                    return False
                left = right
            return True
        raise ValueError("Unsupported expression")

    # ---------------------------------------------------------------------------
    # Node runners
    # ---------------------------------------------------------------------------

    async def _run_ai_classify(self, node: Dict, context: Dict, tenant_id: str) -> Dict:
        from ..ai.provider import get_registry
        config = node.get("config", {})
        text = self._resolve(config.get("text", ""), context)
        categories = config.get("categories", ["spam", "normal", "urgent"])
        provider = config.get("provider")

        registry = get_registry()
        try:
            prov = registry.get(provider)
        except ValueError:
            prov = registry.get()
        result = await prov.classify(text, categories)
        return {"classification": result, "categories": categories}

    async def _run_ai_extract(self, node: Dict, context: Dict, tenant_id: str) -> Dict:
        from ..ai.provider import get_registry
        config = node.get("config", {})
        text = self._resolve(config.get("text", ""), context)
        fields = config.get("fields", [])
        registry = get_registry()
        prov = registry.get(config.get("provider"))
        extracted = await prov.extract(text, fields)
        return {"extracted": extracted}

    async def _run_ai_summarize(self, node: Dict, context: Dict, tenant_id: str) -> Dict:
        from ..ai.provider import get_registry
        config = node.get("config", {})
        text = self._resolve(config.get("text", ""), context)
        max_words = config.get("max_words", 100)
        registry = get_registry()
        prov = registry.get(config.get("provider"))
        summary = await prov.summarize(text, max_words)
        return {"summary": summary}

    async def _run_ai_generate(self, node: Dict, context: Dict, tenant_id: str) -> Dict:
        from ..ai.provider import get_registry
        config = node.get("config", {})
        prompt = self._resolve(config.get("prompt", ""), context)
        system_prompt = config.get("system_prompt")
        registry = get_registry()
        prov = registry.get(config.get("provider"))
        result = await prov.complete(prompt, system_prompt=system_prompt,
                                     max_tokens=config.get("max_tokens", 1024))
        return {"generated": result.get("content", "")}

    async def _run_ai_sentiment(self, node: Dict, context: Dict, tenant_id: str) -> Dict:
        from ..ai.provider import get_registry
        config = node.get("config", {})
        text = self._resolve(config.get("text", ""), context)
        registry = get_registry()
        prov = registry.get(config.get("provider"))
        result = await prov.classify(text, ["positive", "negative", "neutral"])
        return {"sentiment": result}

    async def _run_ocr_process(self, node: Dict, context: Dict, tenant_id: str) -> Dict:
        config = node.get("config", {})
        doc_url = self._resolve(config.get("document_url", ""), context)
        extract_fields = config.get("extract_fields", [])
        try:
            from ...plugins.ocr.pipeline import OCRPipeline
            pipeline = OCRPipeline()
            result = await pipeline.process(document_url=doc_url)
            return {"ocr_result": result}
        except Exception as exc:
            return {"ocr_result": None, "error": str(exc)}

    async def _run_condition(self, node: Dict, context: Dict, tenant_id: str) -> Dict:
        config = node.get("config", {})
        condition = config.get("condition", "True")
        result = self._eval_condition(condition, context)
        return {"condition_result": result}

    async def _run_switch(self, node: Dict, context: Dict, tenant_id: str) -> Dict:
        config = node.get("config", {})
        value = self._resolve(config.get("value", ""), context)
        return {"switch_value": value}

    async def _run_approval_request(self, node: Dict, context: Dict, tenant_id: str) -> Dict:
        from ..backend.db import tx
        import uuid as _uuid
        config = node.get("config", {})
        req_id = str(_uuid.uuid4())
        now = datetime.utcnow().isoformat()
        with tx() as conn:
            conn.execute(
                """INSERT INTO approval_requests
                   (id,tenant_id,title,description,risk_level,data_json,assignee,status,created_at)
                   VALUES (?,?,?,?,?,?,?,'pending',?)""",
                (
                    req_id, tenant_id,
                    config.get("title", "Approval Required"),
                    config.get("description", ""),
                    config.get("risk_level", "low"),
                    json.dumps(context),
                    config.get("assignee"),
                    now,
                ),
            )
        raise _ApprovalGateException(node["id"], req_id)

    async def _run_approval_gate(self, node: Dict, context: Dict, tenant_id: str) -> Dict:
        approval_id = context.get("pending_approval_id")
        if not approval_id:
            return {"gate": "passed"}
        from ..backend.db import get_db
        row = get_db().execute(
            "SELECT status FROM approval_requests WHERE id=?", (approval_id,)
        ).fetchone()
        if row and dict(row)["status"] == "pending":
            raise _ApprovalGateException(node["id"], approval_id)
        return {"gate": "passed", "decision": dict(row)["status"] if row else "unknown"}

    async def _run_send_email(self, node: Dict, context: Dict, tenant_id: str) -> Dict:
        config = node.get("config", {})
        to = self._resolve(config.get("to", ""), context)
        subject = self._resolve(config.get("subject", ""), context)
        body = self._resolve(config.get("body", ""), context)
        log.info("SEND EMAIL to=%s subject=%s", to, subject)
        return {"sent": True, "to": to, "subject": subject}

    async def _run_http_request(self, node: Dict, context: Dict, tenant_id: str) -> Dict:
        import httpx
        config = node.get("config", {})
        url = self._resolve(config.get("url", ""), context)
        method = config.get("method", "GET").upper()
        headers = config.get("headers", {})
        body = config.get("body")

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.request(method, url, headers=headers,
                                        json=body if body else None)
        return {"status_code": resp.status_code, "body": resp.text[:4096]}

    async def _run_transform(self, node: Dict, context: Dict, tenant_id: str) -> Dict:
        config = node.get("config", {})
        mapping = config.get("mapping", {})
        result = {}
        for key, expr in mapping.items():
            value = self._safe_eval(str(expr), context)
            if value is None:
                result[key] = self._resolve(str(expr), context)
            else:
                result[key] = value
        return {"transformed": result}

    async def _run_delay(self, node: Dict, context: Dict, tenant_id: str) -> Dict:
        config = node.get("config", {})
        seconds = config.get("seconds", 1)
        await asyncio.sleep(min(seconds, 300))
        return {"delayed_seconds": seconds}

    async def _run_log(self, node: Dict, context: Dict, tenant_id: str) -> Dict:
        config = node.get("config", {})
        message = self._resolve(config.get("message", ""), context)
        level = config.get("level", "info")
        getattr(log, level, log.info)("WORKFLOW LOG: %s", message)
        return {"logged": message}

    async def _run_search(self, node: Dict, context: Dict, tenant_id: str) -> Dict:
        config = node.get("config", {})
        query = self._resolve(config.get("query", ""), context)
        from ..backend.models import SearchRequest
        from ..backend.search import semantic_search
        req = SearchRequest(query=query, tenant_id=tenant_id, limit=config.get("limit", 10))
        result = await semantic_search(req)
        return {"search_results": [r.model_dump() for r in result.results], "total": result.total}

    async def _run_agent(self, node: Dict, context: Dict, tenant_id: str) -> Dict:
        config = node.get("config", {})
        agent_type = config.get("agent_type", "workflow")
        task_name = config.get("task_name", "")
        from ..agents.orchestrator import AgentOrchestrator
        orch = AgentOrchestrator()
        result = await orch.run_task(agent_type, task_name, context, tenant_id)
        return {"agent_result": result}

    async def _run_merge(self, node: Dict, context: Dict, tenant_id: str) -> Dict:
        return {"merged": True, "context_keys": list(context.keys())}

    def _resolve(self, template: str, context: Dict) -> str:
        """Replace {{key}} placeholders with context values."""
        import re
        def replacer(m):
            key = m.group(1).strip()
            val = context.get(key)
            return str(val) if val is not None else m.group(0)
        return re.sub(r"\{\{(.+?)\}\}", replacer, str(template))


class _ApprovalGateException(Exception):
    def __init__(self, node_id: str, approval_id: str):
        super().__init__(f"Waiting for approval {approval_id} at node {node_id}")
        self.node_id = node_id
        self.approval_id = approval_id
