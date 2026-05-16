"""DeepSeek provider – OpenAI-compatible API."""
from __future__ import annotations

import os
from typing import Dict, Optional

import httpx

from .provider import AIProviderBase

_DEFAULT_MODEL = "deepseek-chat"
_BASE_URL = "https://api.deepseek.com/v1"


class DeepSeekProvider(AIProviderBase):
    provider_name = "deepseek"

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None,
                 default_model: Optional[str] = None, **kwargs):
        super().__init__(api_key, base_url, default_model, **kwargs)
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        self.base_url = (base_url or _BASE_URL).rstrip("/")
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

        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        total_tokens = usage.get("total_tokens", 0)
        # deepseek-chat: ~$0.14/1M tokens
        cost = total_tokens * 0.14 / 1_000_000

        return {
            "content": content,
            "model": data.get("model", self.default_model),
            "tokens_used": total_tokens,
            "cost_estimate": cost,
        }
