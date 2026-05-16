"""AI Provider abstraction layer – base class and registry."""
from __future__ import annotations

import abc
import asyncio
import logging
from typing import Dict, Optional

log = logging.getLogger(__name__)


class AIProviderBase(abc.ABC):
    """Abstract base class for all AI providers."""

    provider_name: str = "base"

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None,
                 default_model: Optional[str] = None, **kwargs):
        self.api_key = api_key
        self.base_url = base_url
        self.default_model = default_model

    @abc.abstractmethod
    async def complete(self, prompt: str, system_prompt: Optional[str] = None,
                       model: Optional[str] = None, max_tokens: int = 1024,
                       temperature: float = 0.7, **kwargs) -> Dict:
        """Return dict with keys: content, tokens_used, model, latency_ms."""

    async def classify(self, text: str, categories: list[str], **kwargs) -> str:
        cats = ", ".join(categories)
        result = await self.complete(
            prompt=f"Classify the following text into one of these categories: {cats}\n\nText: {text}\n\nRespond with only the category name.",
            max_tokens=50, temperature=0.1, **kwargs,
        )
        content = result.get("content", "").strip()
        for cat in categories:
            if cat.lower() in content.lower():
                return cat
        return categories[0] if categories else content

    async def extract(self, text: str, fields: list[str], **kwargs) -> Dict:
        fields_str = "\n".join(f"- {f}" for f in fields)
        result = await self.complete(
            prompt=f"Extract the following fields from the text as JSON:\n{fields_str}\n\nText: {text}\n\nRespond with a JSON object only.",
            max_tokens=512, temperature=0.0, **kwargs,
        )
        content = result.get("content", "").strip()
        import json, re
        m = re.search(r"\{.*\}", content, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                pass
        return {f: None for f in fields}

    async def summarize(self, text: str, max_words: int = 100, **kwargs) -> str:
        result = await self.complete(
            prompt=f"Summarize the following text in {max_words} words or fewer:\n\n{text}",
            max_tokens=max_words * 2, **kwargs,
        )
        return result.get("content", "").strip()

    async def embed(self, text: str, **kwargs) -> list[float]:
        raise NotImplementedError(f"{self.provider_name} does not support embeddings")


class AIProviderRegistry:
    """Singleton registry for all configured AI providers."""

    _instance: Optional["AIProviderRegistry"] = None

    def __init__(self):
        self._providers: Dict[str, AIProviderBase] = {}
        self._default: Optional[str] = None

    @classmethod
    def get_instance(cls) -> "AIProviderRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def register(self, name: str, provider: AIProviderBase, *, default: bool = False) -> None:
        self._providers[name] = provider
        if default or self._default is None:
            self._default = name
        log.info("AI provider registered: %s", name)

    def configure_provider(self, provider_enum, config) -> None:
        """Configure a provider from an AIProviderConfig model."""
        name = provider_enum.value
        provider = self._build_provider(name, config)
        if provider:
            self.register(name, provider)

    def _build_provider(self, name: str, config) -> Optional[AIProviderBase]:
        try:
            if name == "openai":
                from .openai_provider import OpenAIProvider
                return OpenAIProvider(api_key=config.api_key, base_url=config.base_url,
                                      default_model=config.default_model)
            elif name == "claude":
                from .claude_provider import ClaudeProvider
                return ClaudeProvider(api_key=config.api_key, base_url=config.base_url,
                                      default_model=config.default_model)
            elif name == "gemini":
                from .gemini_provider import GeminiProvider
                return GeminiProvider(api_key=config.api_key, default_model=config.default_model)
            elif name == "deepseek":
                from .deepseek_provider import DeepSeekProvider
                return DeepSeekProvider(api_key=config.api_key, base_url=config.base_url,
                                        default_model=config.default_model)
            elif name == "local":
                from .local_provider import LocalProvider
                return LocalProvider(base_url=config.base_url, default_model=config.default_model)
        except Exception as exc:
            log.error("Failed to build provider %s: %s", name, exc)
        return None

    def get(self, name: Optional[str] = None) -> AIProviderBase:
        target = name or self._default
        if not target or target not in self._providers:
            raise ValueError(f"AI provider '{target}' not configured")
        return self._providers[target]

    async def complete(self, provider_enum, request) -> "AIResponse":
        from ..backend.models import AIProvider, AIResponse
        import time
        name = provider_enum.value if hasattr(provider_enum, "value") else str(provider_enum)
        provider = self.get(name)
        t0 = time.time()
        result = await provider.complete(
            prompt=request.prompt,
            system_prompt=request.system_prompt,
            model=request.model,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
        )
        latency_ms = int((time.time() - t0) * 1000)
        return AIResponse(
            provider=AIProvider(name),
            model=result.get("model", provider.default_model or name),
            content=result.get("content", ""),
            tokens_used=result.get("tokens_used", 0),
            cost_estimate=result.get("cost_estimate", 0.0),
            latency_ms=latency_ms,
        )


def get_registry() -> AIProviderRegistry:
    return AIProviderRegistry.get_instance()
