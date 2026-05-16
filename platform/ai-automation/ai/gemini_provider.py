"""Google Gemini provider – httpx-based."""
from __future__ import annotations

import os
from typing import Dict, Optional

import httpx

from .provider import AIProviderBase

_DEFAULT_MODEL = "gemini-1.5-flash"
_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


class GeminiProvider(AIProviderBase):
    provider_name = "gemini"

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None,
                 default_model: Optional[str] = None, **kwargs):
        super().__init__(api_key, base_url, default_model, **kwargs)
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self.base_url = base_url or _BASE_URL
        self.default_model = default_model or _DEFAULT_MODEL

    async def complete(self, prompt: str, system_prompt: Optional[str] = None,
                       model: Optional[str] = None, max_tokens: int = 1024,
                       temperature: float = 0.7, **kwargs) -> Dict:
        m = model or self.default_model
        full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt

        payload = {
            "contents": [{"parts": [{"text": full_prompt}]}],
            "generationConfig": {"maxOutputTokens": max_tokens, "temperature": temperature},
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{self.base_url}/models/{m}:generateContent?key={self.api_key}",
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()

        text = data["candidates"][0]["content"]["parts"][0]["text"]
        usage = data.get("usageMetadata", {})
        total_tokens = usage.get("totalTokenCount", 0)
        # gemini-1.5-flash: ~$0.075/1M tokens
        cost = total_tokens * 0.075 / 1_000_000

        return {
            "content": text,
            "model": m,
            "tokens_used": total_tokens,
            "cost_estimate": cost,
        }
