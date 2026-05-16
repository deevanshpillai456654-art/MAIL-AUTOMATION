"""Anthropic Claude provider – httpx-based."""
from __future__ import annotations

import os
from typing import Dict, Optional

import httpx

from .provider import AIProviderBase

_DEFAULT_MODEL = "claude-sonnet-4-6"
_BASE_URL = "https://api.anthropic.com"


class ClaudeProvider(AIProviderBase):
    provider_name = "claude"

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None,
                 default_model: Optional[str] = None, **kwargs):
        super().__init__(api_key, base_url, default_model, **kwargs)
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.base_url = (base_url or _BASE_URL).rstrip("/")
        self.default_model = default_model or _DEFAULT_MODEL

    async def complete(self, prompt: str, system_prompt: Optional[str] = None,
                       model: Optional[str] = None, max_tokens: int = 1024,
                       temperature: float = 0.7, **kwargs) -> Dict:
        payload: Dict = {
            "model": model or self.default_model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system_prompt:
            payload["system"] = system_prompt

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{self.base_url}/v1/messages",
                json=payload,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        content = data["content"][0]["text"]
        usage = data.get("usage", {})
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        # claude-sonnet-4-6: $3/1M input, $15/1M output
        cost = (input_tokens * 3.0 + output_tokens * 15.0) / 1_000_000

        return {
            "content": content,
            "model": data.get("model", self.default_model),
            "tokens_used": input_tokens + output_tokens,
            "cost_estimate": cost,
        }
