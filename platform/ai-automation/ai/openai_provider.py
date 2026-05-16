"""OpenAI provider – httpx-based, no openai package dependency."""
from __future__ import annotations

import os
from typing import Dict, Optional

import httpx

from .provider import AIProviderBase

_DEFAULT_MODEL = "gpt-4o-mini"
_BASE_URL = "https://api.openai.com/v1"


class OpenAIProvider(AIProviderBase):
    provider_name = "openai"

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None,
                 default_model: Optional[str] = None, **kwargs):
        super().__init__(api_key, base_url, default_model, **kwargs)
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.base_url = base_url or _BASE_URL
        self.default_model = default_model or _DEFAULT_MODEL

    async def complete(self, prompt: str, system_prompt: Optional[str] = None,
                       model: Optional[str] = None, max_tokens: int = 1024,
                       temperature: float = 0.7, **kwargs) -> Dict:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": model or self.default_model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {self.api_key}",
                         "Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()

        choice = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        total_tokens = usage.get("total_tokens", 0)
        # Rough cost estimate: $0.15/1M input + $0.60/1M output for gpt-4o-mini
        cost = (usage.get("prompt_tokens", 0) * 0.15 + usage.get("completion_tokens", 0) * 0.60) / 1_000_000

        return {
            "content": choice,
            "model": data.get("model", self.default_model),
            "tokens_used": total_tokens,
            "cost_estimate": cost,
        }

    async def embed(self, text: str, model: str = "text-embedding-3-small", **kwargs) -> list[float]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self.base_url}/embeddings",
                json={"input": text, "model": model},
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            resp.raise_for_status()
            return resp.json()["data"][0]["embedding"]
