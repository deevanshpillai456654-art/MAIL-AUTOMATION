"""Communication Agent – AI-assisted email/message drafting."""
from __future__ import annotations

from typing import Any, Dict, Optional

from .base import BaseAgent


class CommunicationAgent(BaseAgent):
    agent_type = "communication"

    async def run(self, task_name: str, input_data: Dict[str, Any],
                  tenant_id: Optional[str] = None) -> Dict[str, Any]:
        if task_name == "draft_reply":
            return await self._draft_reply(input_data)
        elif task_name == "classify_intent":
            return await self._classify_intent(input_data)
        elif task_name == "draft_response":
            return await self._draft_response(input_data)
        return {"error": f"Unknown communication task: {task_name}"}

    async def _draft_reply(self, data: Dict) -> Dict:
        from ..ai.provider import get_registry
        email_body = data.get("email_body", "")
        tone = data.get("tone", "professional")
        registry = get_registry()
        prov = registry.get(data.get("provider"))
        result = await prov.complete(
            prompt=f"Draft a {tone} reply to this email:\n\n{email_body}",
            system_prompt="You are a professional email assistant. Write clear, concise replies.",
            max_tokens=500,
        )
        return {"draft": result.get("content", ""), "tone": tone}

    async def _classify_intent(self, data: Dict) -> Dict:
        from ..ai.provider import get_registry
        text = data.get("text", "")
        registry = get_registry()
        prov = registry.get(data.get("provider"))
        categories = ["inquiry", "complaint", "order", "support", "feedback", "spam", "other"]
        intent = await prov.classify(text, categories)
        return {"intent": intent, "categories": categories}

    async def _draft_response(self, data: Dict) -> Dict:
        from ..ai.provider import get_registry
        context = data.get("context", "")
        template = data.get("template", "")
        registry = get_registry()
        prov = registry.get(data.get("provider"))
        prompt = f"Using this context:\n{context}\n\nGenerate a response based on this template:\n{template}"
        result = await prov.complete(prompt=prompt, max_tokens=600)
        return {"response": result.get("content", "")}
