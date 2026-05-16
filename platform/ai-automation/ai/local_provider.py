"""Local LLM provider via Ollama-compatible API."""
from __future__ import annotations

import os
from typing import Dict, Optional

import httpx

from .provider import AIProviderBase

_DEFAULT_MODEL = "llama3.2"
_BASE_URL = "http://localhost:11434"


class LocalProvider(AIProviderBase):
    provider_name = "local"

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None,
                 default_model: Optional[str] = None, **kwargs):
        super().__init__(api_key, base_url, default_model, **kwargs)
        self.base_url = (base_url or os.environ.get("OLLAMA_BASE_URL", _BASE_URL)).rstrip("/")
        self.default_model = default_model or os.environ.get("LOCAL_LLM_MODEL", _DEFAULT_MODEL)

    async def complete(self, prompt: str, system_prompt: Optional[str] = None,
                       model: Optional[str] = None, max_tokens: int = 1024,
                       temperature: float = 0.7, **kwargs) -> Dict:
        m = model or self.default_model
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": m,
            "messages": messages,
            "stream": False,
            "options": {"num_predict": max_tokens, "temperature": temperature},
        }

        async with httpx.AsyncClient(timeout=180.0) as client:
            resp = await client.post(
                f"{self.base_url}/api/chat",
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()

        content = data.get("message", {}).get("content", "")
        tokens_used = data.get("eval_count", 0) + data.get("prompt_eval_count", 0)

        return {
            "content": content,
            "model": m,
            "tokens_used": tokens_used,
            "cost_estimate": 0.0,  # local inference is free
        }

    async def list_models(self) -> list[str]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{self.base_url}/api/tags")
            resp.raise_for_status()
            return [m["name"] for m in resp.json().get("models", [])]
