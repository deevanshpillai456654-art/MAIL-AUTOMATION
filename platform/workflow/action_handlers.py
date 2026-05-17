"""
ActionHandlers — built-in workflow action node implementations.

These are registered into WorkflowNodeRegistry at platform startup and
provide core actions every workflow can use without a plugin.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict

log = logging.getLogger(__name__)


async def delay_action(inputs: Dict[str, Any], ctx: Any) -> Dict[str, Any]:
    """
    Built-in 'delay' node.

    Inputs:
      seconds (int): How long to wait.
    """
    seconds = int(inputs.get("seconds", 1))
    seconds = min(seconds, 3600)  # cap at 1 hour
    await asyncio.sleep(seconds)
    return {"waited_seconds": seconds}


async def log_action(inputs: Dict[str, Any], ctx: Any) -> Dict[str, Any]:
    """
    Built-in 'log' node — emits a log line.

    Inputs:
      message (str): The message to log.
      level (str): debug | info | warning | error  (default: info)
    """
    message = str(inputs.get("message", ""))
    level   = inputs.get("level", "info").lower()
    getattr(log, level, log.info)(message)
    return {"logged": True}


async def condition_action(inputs: Dict[str, Any], ctx: Any) -> Dict[str, Any]:
    """
    Built-in 'condition' node — evaluates a simple equality check.

    Inputs:
      left  (any): Left operand.
      op    (str): == | != | > | < | >= | <=
      right (any): Right operand.

    Outputs:
      result (bool)
    """
    left  = inputs.get("left")
    right = inputs.get("right")
    op    = inputs.get("op", "==")
    result = {
        "==": lambda a, b: a == b,
        "!=": lambda a, b: a != b,
        ">":  lambda a, b: a > b,
        "<":  lambda a, b: a < b,
        ">=": lambda a, b: a >= b,
        "<=": lambda a, b: a <= b,
    }.get(op, lambda a, b: a == b)(left, right)
    return {"result": result}


async def http_request_action(inputs: Dict[str, Any], ctx: Any) -> Dict[str, Any]:
    """
    Built-in 'http_request' node.

    Inputs:
      url     (str)
      method  (str): GET | POST | PUT | DELETE  (default: GET)
      headers (dict)
      body    (dict | str)
      timeout (int): seconds (default: 30)

    Outputs:
      status_code (int)
      body (str)
    """
    try:
        import httpx
    except ImportError:
        return {"error": "httpx not installed", "status_code": 0, "body": ""}

    url     = str(inputs.get("url", ""))
    method  = str(inputs.get("method", "GET")).upper()
    headers = inputs.get("headers") or {}
    body    = inputs.get("body")
    timeout = int(inputs.get("timeout", 30))

    async with httpx.AsyncClient(timeout=timeout) as client:
        kwargs: Dict[str, Any] = {"headers": headers}
        if body:
            kwargs["json" if isinstance(body, dict) else "content"] = body
        resp = await client.request(method, url, **kwargs)
        return {
            "status_code": resp.status_code,
            "body": resp.text,
        }


# ── Registration helper ───────────────────────────────────────────────────

def register_builtin_actions(node_registry: Any) -> None:
    """Register all built-in action nodes into the provided NodeRegistry."""
    from ..sdk.workflow_sdk import WorkflowNode

    builtins = [
        WorkflowNode(
            node_type="delay",
            label="Delay",
            category="Control",
            description="Wait for a fixed number of seconds.",
            input_schema={"seconds": {"type": "integer", "default": 1}},
            output_schema={"waited_seconds": {"type": "integer"}},
            handler=delay_action,
            plugin_id="__system__",
        ),
        WorkflowNode(
            node_type="log",
            label="Log Message",
            category="Utilities",
            description="Write a message to the server log.",
            input_schema={"message": {"type": "string"}, "level": {"type": "string", "default": "info"}},
            output_schema={"logged": {"type": "boolean"}},
            handler=log_action,
            plugin_id="__system__",
        ),
        WorkflowNode(
            node_type="condition",
            label="Condition",
            category="Control",
            description="Evaluate a comparison and return a boolean result.",
            input_schema={
                "left":  {"type": "any"},
                "op":    {"type": "string", "enum": ["==", "!=", ">", "<", ">=", "<="]},
                "right": {"type": "any"},
            },
            output_schema={"result": {"type": "boolean"}},
            handler=condition_action,
            plugin_id="__system__",
        ),
        WorkflowNode(
            node_type="http_request",
            label="HTTP Request",
            category="Integrations",
            description="Make an outbound HTTP request.",
            input_schema={
                "url":     {"type": "string"},
                "method":  {"type": "string", "default": "GET"},
                "headers": {"type": "object"},
                "body":    {"type": "any"},
                "timeout": {"type": "integer", "default": 30},
            },
            output_schema={"status_code": {"type": "integer"}, "body": {"type": "string"}},
            handler=http_request_action,
            plugin_id="__system__",
        ),
    ]
    node_registry.register_many(builtins)
