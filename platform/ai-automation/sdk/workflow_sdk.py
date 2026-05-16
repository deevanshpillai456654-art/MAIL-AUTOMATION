"""Workflow Builder SDK – fluent API for constructing workflows in code."""
from __future__ import annotations

from typing import Any, Dict, List, Optional
import uuid


class WorkflowBuilder:
    """Fluent builder for WorkflowDefinition."""

    def __init__(self, name: str, tenant_id: str):
        self._name = name
        self._tenant_id = tenant_id
        self._description: Optional[str] = None
        self._nodes: List[Dict] = []
        self._connections: List[Dict] = []
        self._variables: Dict[str, Any] = {}
        self._tags: List[str] = []
        self._last_node_id: Optional[str] = None

    def description(self, text: str) -> "WorkflowBuilder":
        self._description = text
        return self

    def tag(self, *tags: str) -> "WorkflowBuilder":
        self._tags.extend(tags)
        return self

    def variable(self, key: str, value: Any) -> "WorkflowBuilder":
        self._variables[key] = value
        return self

    def add_node(self, node_type: str, label: str, config: Optional[Dict] = None,
                 position: Optional[Dict] = None) -> "WorkflowBuilder":
        node_id = str(uuid.uuid4())
        node = {
            "id": node_id,
            "type": node_type,
            "label": label,
            "config": config or {},
            "position": position or {"x": len(self._nodes) * 200.0, "y": 100.0},
        }
        self._nodes.append(node)
        if self._last_node_id:
            self._connections.append({
                "source_id": self._last_node_id,
                "target_id": node_id,
            })
        self._last_node_id = node_id
        return self

    def connect(self, source_label: str, target_label: str,
                condition: Optional[str] = None) -> "WorkflowBuilder":
        src = self._find_node(source_label)
        tgt = self._find_node(target_label)
        if src and tgt:
            self._connections.append({
                "source_id": src["id"],
                "target_id": tgt["id"],
                "condition": condition,
            })
        return self

    def trigger_email(self, label: str = "Email Trigger", **kwargs) -> "WorkflowBuilder":
        return self.add_node("trigger_email", label, kwargs)

    def trigger_webhook(self, label: str = "Webhook Trigger", **kwargs) -> "WorkflowBuilder":
        return self.add_node("trigger_webhook", label, kwargs)

    def ai_classify(self, text_key: str, categories: List[str],
                    label: str = "AI Classify", **kwargs) -> "WorkflowBuilder":
        return self.add_node("ai_classify", label, {"text": f"{{{{{text_key}}}}}", "categories": categories, **kwargs})

    def ai_extract(self, text_key: str, fields: List[str],
                   label: str = "AI Extract", **kwargs) -> "WorkflowBuilder":
        return self.add_node("ai_extract", label, {"text": f"{{{{{text_key}}}}}", "fields": fields, **kwargs})

    def ai_summarize(self, text_key: str, max_words: int = 100,
                     label: str = "AI Summarize", **kwargs) -> "WorkflowBuilder":
        return self.add_node("ai_summarize", label, {"text": f"{{{{{text_key}}}}}", "max_words": max_words, **kwargs})

    def ai_generate(self, prompt: str, label: str = "AI Generate", **kwargs) -> "WorkflowBuilder":
        return self.add_node("ai_generate", label, {"prompt": prompt, **kwargs})

    def ocr_process(self, url_key: str = "document_url", label: str = "OCR Process",
                    **kwargs) -> "WorkflowBuilder":
        return self.add_node("ocr_process", label, {"document_url": f"{{{{{url_key}}}}}", **kwargs})

    def condition(self, expr: str, label: str = "Condition") -> "WorkflowBuilder":
        return self.add_node("condition", label, {"condition": expr})

    def approval_request(self, title: str, risk_level: str = "medium",
                         assignee: Optional[str] = None, label: str = "Approval") -> "WorkflowBuilder":
        return self.add_node("approval_request", label, {
            "title": title, "risk_level": risk_level, "assignee": assignee
        })

    def send_email(self, to: str, subject: str, body: str,
                   label: str = "Send Email") -> "WorkflowBuilder":
        return self.add_node("send_email", label, {"to": to, "subject": subject, "body": body})

    def http_request(self, url: str, method: str = "GET", label: str = "HTTP Request",
                     **kwargs) -> "WorkflowBuilder":
        return self.add_node("http_request", label, {"url": url, "method": method, **kwargs})

    def delay(self, seconds: int, label: str = "Delay") -> "WorkflowBuilder":
        return self.add_node("delay", label, {"seconds": seconds})

    def log(self, message: str, level: str = "info", label: str = "Log") -> "WorkflowBuilder":
        return self.add_node("log", label, {"message": message, "level": level})

    def build(self) -> Dict:
        return {
            "name": self._name,
            "description": self._description,
            "tenant_id": self._tenant_id,
            "nodes": self._nodes,
            "connections": self._connections,
            "variables": self._variables,
            "tags": self._tags,
        }

    def _find_node(self, label: str) -> Optional[Dict]:
        for n in self._nodes:
            if n["label"] == label:
                return n
        return None
