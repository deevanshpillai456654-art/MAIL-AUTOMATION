"""
OpenAI Connector Plugin

Provides AI-powered classification, extraction, summarisation,
and chat completion capabilities to the MailPilot platform.
"""
from __future__ import annotations

import json
import os
from typing import Any, Optional

from ...sdk.plugin_sdk import ConnectorPlugin, ConnectorSyncResult


class OpenAIConnector(ConnectorPlugin):
    """
    OpenAI API connector.

    Capabilities:
    - classify(text)       — email intent/category classification
    - extract(text)        — named entity / field extraction
    - summarise(text)      — email thread summarisation
    - chat(messages)       — general GPT chat completion
    - embed(texts)         — text embedding for semantic search
    """

    OPENAI_API_BASE = "https://api.openai.com/v1"

    @property
    def plugin_id(self) -> str:
        return "openai_connector"

    @property
    def name(self) -> str:
        return "OpenAI"

    @property
    def version(self) -> str:
        return "1.3.0"

    @property
    def category(self) -> str:
        return "ai"

    # ------------------------------------------------------------------
    # Config helpers
    # ------------------------------------------------------------------

    def _get_api_key(self, config: Optional[dict] = None) -> str:
        return (config or {}).get("api_key") or os.environ.get("OPENAI_API_KEY", "")

    def _get_model(self, config: Optional[dict] = None) -> str:
        return (config or {}).get("model") or os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

    def _get_org_id(self, config: Optional[dict] = None) -> Optional[str]:
        return (config or {}).get("organization_id") or os.environ.get("OPENAI_ORGANIZATION_ID")

    def _headers(self, config: Optional[dict] = None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._get_api_key(config)}",
            "Content-Type": "application/json",
        }
        org_id = self._get_org_id(config)
        if org_id:
            headers["OpenAI-Organization"] = org_id
        return headers

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def health_check(self, tenant_id: str) -> dict[str, Any]:
        api_key = self._get_api_key()
        if not api_key:
            return {"status": "error", "message": "OPENAI_API_KEY not configured"}
        try:
            import httpx
            response = httpx.get(
                f"{self.OPENAI_API_BASE}/models",
                headers=self._headers(),
                timeout=10.0,
            )
            if response.is_success:
                return {"status": "ok", "message": "OpenAI API reachable"}
            return {"status": "error", "message": f"API returned {response.status_code}: {response.text[:200]}"}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def test_connection(self, tenant_id: str, config: dict[str, Any]) -> bool:
        if not self._get_api_key(config):
            return False
        try:
            import httpx
            response = httpx.get(
                f"{self.OPENAI_API_BASE}/models",
                headers=self._headers(config),
                timeout=10.0,
            )
            return response.is_success
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Core AI methods
    # ------------------------------------------------------------------

    def classify(
        self,
        text: str,
        categories: list[str],
        tenant_id: str,
        config: Optional[dict] = None,
    ) -> dict[str, Any]:
        """
        Classify text into one of the provided categories.

        Returns:
            {"category": str, "confidence": float, "reasoning": str}
        """
        system_prompt = (
            "You are an email classification assistant. "
            "Classify the provided email text into exactly ONE of the given categories. "
            "Return a JSON object with keys: category (string), confidence (0.0-1.0), reasoning (string)."
        )
        user_prompt = (
            f"Categories: {json.dumps(categories)}\n\n"
            f"Email text:\n{text[:4000]}"
        )

        response = self._chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            config=config,
            response_format={"type": "json_object"},
        )

        try:
            result = json.loads(response["content"])
        except Exception:
            result = {"category": categories[0], "confidence": 0.5, "reasoning": response["content"]}

        # Publish classification event
        self._publish_event(
            "ai.classification.completed",
            tenant_id,
            {"input_length": len(text), "categories": categories, "result": result},
        )
        return result

    def extract(
        self,
        text: str,
        fields: list[dict[str, str]],
        tenant_id: str,
        config: Optional[dict] = None,
    ) -> dict[str, Any]:
        """
        Extract structured fields from text.

        Args:
            text:   Input text to extract from
            fields: List of {"name": str, "type": str, "description": str}
            config: Optional config override

        Returns:
            Dict with extracted field values.
        """
        schema_desc = "\n".join(
            f"- {f['name']} ({f.get('type','string')}): {f.get('description','')}"
            for f in fields
        )
        system_prompt = (
            "You are a data extraction assistant. "
            "Extract the specified fields from the provided text. "
            "Return a JSON object where keys are field names and values are the extracted data. "
            "Use null for fields that cannot be found."
        )
        user_prompt = f"Fields to extract:\n{schema_desc}\n\nText:\n{text[:4000]}"

        response = self._chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            config=config,
            response_format={"type": "json_object"},
        )

        try:
            result = json.loads(response["content"])
        except Exception:
            result = {}

        self._publish_event(
            "ai.extraction.completed",
            tenant_id,
            {"fields": [f["name"] for f in fields], "result": result},
        )
        return result

    def summarise(
        self,
        text: str,
        tenant_id: str,
        max_sentences: int = 3,
        config: Optional[dict] = None,
    ) -> str:
        """Summarise text in up to max_sentences sentences."""
        response = self._chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": f"You are a concise summarisation assistant. Summarise the following text in at most {max_sentences} sentences.",
                },
                {"role": "user", "content": text[:6000]},
            ],
            config=config,
        )
        summary = response["content"]
        self._publish_event("ai.summary.completed", tenant_id, {"length": len(summary)})
        return summary

    def chat(
        self,
        messages: list[dict[str, str]],
        tenant_id: str,
        config: Optional[dict] = None,
        system_prompt: Optional[str] = None,
    ) -> str:
        """
        General-purpose chat completion.

        Args:
            messages:      List of {"role": "user"|"assistant", "content": str}
            tenant_id:     Tenant making the request
            config:        Optional config override
            system_prompt: Optional system message to prepend

        Returns:
            The assistant's response text.
        """
        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)

        response = self._chat_completion(messages=full_messages, config=config)
        return response["content"]

    def embed(
        self,
        texts: list[str],
        config: Optional[dict] = None,
    ) -> list[list[float]]:
        """
        Generate text embeddings for semantic search.

        Args:
            texts:  List of strings to embed
            config: Optional config override

        Returns:
            List of embedding vectors (one per input text).
        """
        import httpx
        response = httpx.post(
            f"{self.OPENAI_API_BASE}/embeddings",
            headers=self._headers(config),
            json={
                "model": "text-embedding-3-small",
                "input": texts,
            },
            timeout=60.0,
        )
        response.raise_for_status()
        data = response.json()
        return [item["embedding"] for item in data["data"]]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _chat_completion(
        self,
        messages: list[dict[str, str]],
        config: Optional[dict] = None,
        response_format: Optional[dict] = None,
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        """Make a chat completion API call. Returns {"content": str, "usage": dict}."""
        import httpx
        body: dict[str, Any] = {
            "model": self._get_model(config),
            "messages": messages,
            "max_tokens": (config or {}).get("max_tokens", max_tokens),
            "temperature": (config or {}).get("temperature", 0.2),
        }
        if response_format:
            body["response_format"] = response_format

        response = httpx.post(
            f"{self.OPENAI_API_BASE}/chat/completions",
            headers=self._headers(config),
            json=body,
            timeout=60.0,
        )
        response.raise_for_status()
        data = response.json()
        return {
            "content": data["choices"][0]["message"]["content"],
            "usage": data.get("usage", {}),
            "finish_reason": data["choices"][0].get("finish_reason"),
        }

    def _publish_event(self, event_type: str, tenant_id: str, payload: dict) -> None:
        try:
            import asyncio
            from ...shared.event_bus import get_event_bus
            bus = get_event_bus()
            loop = asyncio.new_event_loop()
            loop.run_until_complete(bus.publish(event_type, self.plugin_id, tenant_id, payload))
            loop.close()
        except Exception:
            pass

    def fetch_data(self, tenant_id: str, **kwargs: Any) -> list[dict[str, Any]]:
        """
        OpenAI connector does not pull data in the traditional sense.
        Returns model list as a capability check.
        """
        try:
            import httpx
            response = httpx.get(
                f"{self.OPENAI_API_BASE}/models",
                headers=self._headers(),
                timeout=15.0,
            )
            response.raise_for_status()
            data = response.json()
            return data.get("data", [])
        except Exception:
            return []

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "required": ["api_key"],
            "properties": {
                "api_key": {"type": "string", "format": "secret", "description": "OpenAI API Key"},
                "model": {"type": "string", "default": "gpt-4o-mini", "description": "Chat completion model"},
                "max_tokens": {"type": "integer", "default": 1024, "description": "Max response tokens"},
                "temperature": {"type": "number", "default": 0.2, "description": "Sampling temperature (0.0-2.0)"},
                "organization_id": {"type": "string", "description": "Optional OpenAI Organization ID"},
            },
        }

    def get_permissions(self) -> list[str]:
        return ["ai.classify", "ai.extract", "ai.chat", "ai.embed"]

    def get_events(self) -> list[str]:
        return ["ai.classification.completed", "ai.extraction.completed", "ai.summary.completed"]
